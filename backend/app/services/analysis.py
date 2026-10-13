"""Cycle / element analysis orchestration: learn elements, analyse new cycles, master cycle, renames.
A background engine keeps recorded cameras analysed automatically."""
from __future__ import annotations

import asyncio
import logging
import shutil

import numpy as np
from sqlalchemy import delete, func, select

from .. import models
from ..config import settings
from ..database import SessionLocal, session_scope
from ..vision.recorder import list_segments
from . import elements as E

log = logging.getLogger(__name__)

LEARN_AFTER_MIN = 10  # learn automatically once this much recording exists ...
AUTO_LEARN_MIN_CYCLES = 15  # ... and it contains at least this many complete cycles
MAX_WINDOW_H = 6  # never analyse more than this at once


# ------------------------------------------------------------------ data
def data_span(camera_id: int) -> tuple[float, float] | None:
    segs = list_segments(camera_id)
    if not segs:
        return None
    first = segs[0][0]
    last = segs[-1][0]
    try:  # the newest frame of the newest segment
        with open(segs[-1][1], "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            tail = f.read().decode("utf-8", "ignore").strip().splitlines()
        import json

        for line in reversed(tail):
            try:
                last = json.loads(line)["t"]
                break
            except (ValueError, KeyError):
                continue
    except OSError:
        pass
    return first, last


def get_model(camera_id: int) -> dict | None:
    with SessionLocal() as db:
        row = db.scalar(select(models.ElementModel).where(models.ElementModel.camera_id == camera_id))
        return dict(row.model) if row else None


def save_model(camera_id: int, model: dict) -> None:
    with session_scope() as db:
        row = db.scalar(select(models.ElementModel).where(models.ElementModel.camera_id == camera_id))
        if row is None:
            db.add(models.ElementModel(camera_id=camera_id, model=model))
        else:
            row.model = model


def _camera(camera_id: int) -> tuple[models.Camera, models.Line | None] | None:
    with SessionLocal() as db:
        cam = db.get(models.Camera, camera_id)
        if cam is None:
            return None
        return cam, db.get(models.Line, cam.line_id)


# ------------------------------------------------------------------ learn / analyse
def learn_camera(camera_id: int, minutes: float = 60, min_cycles: int = E.MIN_CYCLES_TO_LEARN) -> dict | None:
    got = _camera(camera_id)
    span = data_span(camera_id)
    if got is None or span is None:
        return None
    cam, line = got
    t1 = span[1]
    t0 = max(span[0], t1 - minutes * 60)
    model = E.learn(camera_id, t0, t1, line.takt_time_sec if line else None, list(cam.zones or []), min_cycles)
    if model is None:
        return None
    old = get_model(camera_id)
    if old:  # keep the names the user gave to elements that are still the same spot
        for e in model["elements"]:
            for o in old.get("elements", []):
                if (o.get("renamed") and len(o["center"]) == len(e["center"])
                        and np.linalg.norm(np.array(e["center"]) - np.array(o["center"])) < E.MERGE_DIST * 1.25):
                    e["name"], e["renamed"] = o["name"], True
    save_model(camera_id, model)
    with session_scope() as db:
        db.execute(delete(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id))
    analyze_camera(camera_id, full=True)
    log.info("camera %s: learned %d elements from %d cycles", camera_id, len(model["elements"]), model["cycles_learned"])
    return model


def analyze_camera(camera_id: int, full: bool = False) -> int:
    model = get_model(camera_id)
    span = data_span(camera_id)
    got = _camera(camera_id)
    if model is None or span is None or got is None:
        return 0
    cam, _ = got
    with SessionLocal() as db:
        last = db.scalar(select(func.max(models.AnalysisCycle.start_ts)).where(
            models.AnalysisCycle.camera_id == camera_id, models.AnalysisCycle.model_version == model["version"]))
    t1 = span[1] - 1.0
    t0 = span[0] if full or last is None else last - 2.0
    t0 = max(t0, t1 - MAX_WINDOW_H * 3600)
    cycles = E.analyze(camera_id, model, t0, t1)
    new = [c for c in cycles if last is None or c["start_ts"] > last + 0.5]
    if new:
        with session_scope() as db:
            for c in new:
                db.add(models.AnalysisCycle(camera_id=camera_id, station_id=cam.station_id, model_version=model["version"],
                                            start_ts=c["start_ts"], end_ts=c["end_ts"], cycle_sec=c["cycle_sec"],
                                            elements=c["elements"], issues=c["issues"], status=c["status"]))
    return len(new)


def _names(model: dict) -> dict[int, str]:
    n = {e["id"]: e["name"] for e in model["elements"]}
    n[E.AWAY] = "Operator away"
    return n


def reevaluate(camera_id: int) -> None:
    """Re-compare every stored cycle with the current standard / element names (no video re-processing)."""
    model = get_model(camera_id)
    if model is None:
        return
    names = _names(model)
    with session_scope() as db:
        rows = db.scalars(select(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id,
                                                             models.AnalysisCycle.model_version == model["version"])).all()
        for r in rows:
            elems = [{**e, "name": names.get(e["id"], e["name"]), "std": None, "delta": None, "cont": False} for e in r.elements]
            elems, issues = E.evaluate(elems, model["standard"], names, model.get("cycle_start"))
            keep = [i for i in (r.issues or []) if i.get("type") == "reach"]  # depend on video, not on the standard
            r.elements, r.issues = elems, issues + keep
            r.status = "issues" if any(i["severity"] != "info" for i in r.issues) else "ok"


def standard_from_cycles(element_lists: list[list[dict]], start_id: int | None = None) -> dict:
    return E.standard_from_items([([e["id"] for e in els], [e["dur"] for e in els]) for els in element_lists], start_id)


def set_cycle_start(camera_id: int, element_id: int) -> None:
    model = get_model(camera_id)
    if model is None:
        return
    model["cycle_start"] = element_id
    model["standard"]["master_cycle_id"] = None
    save_model(camera_id, model)
    with session_scope() as db:
        db.execute(delete(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id))
    analyze_camera(camera_id, full=True)
    with SessionLocal() as db:
        rows = db.scalars(select(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id)).all()
        model["standard"] = standard_from_cycles([r.elements for r in rows], element_id)
    save_model(camera_id, model)
    reevaluate(camera_id)


def set_master(cycle_id: int) -> models.AnalysisCycle | None:
    with SessionLocal() as db:
        row = db.get(models.AnalysisCycle, cycle_id)
        if row is None:
            return None
        camera_id, elems, t0, t1 = row.camera_id, list(row.elements), row.start_ts, row.end_ts
    model = get_model(camera_id)
    if model is None:
        return None
    std = E.standard_from_cycle(elems)
    std["master_cycle_id"] = cycle_id
    model["standard"] = std
    save_model(camera_id, model)
    with session_scope() as db:
        for r in db.scalars(select(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id)):
            r.is_master = r.id == cycle_id
    reevaluate(camera_id)
    # keep the master's video even after the recordings rotate out
    try:
        from .clips import cycle_clip

        clip = cycle_clip(camera_id, t0, t1, clip_labels(elems, model))
        if clip:
            shutil.copy(clip, settings.clips_dir / f"master_cam_{camera_id}.webm")
    except Exception:
        log.exception("could not keep master clip")
    with SessionLocal() as db:
        return db.get(models.AnalysisCycle, cycle_id)


def clear_master(camera_id: int) -> None:
    model = get_model(camera_id)
    if model is None:
        return
    with SessionLocal() as db:
        rows = db.scalars(select(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id,
                                                             models.AnalysisCycle.model_version == model["version"])).all()
        model["standard"] = standard_from_cycles([r.elements for r in rows], model.get("cycle_start"))
    save_model(camera_id, model)
    with session_scope() as db:
        for r in db.scalars(select(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id)):
            r.is_master = False
    reevaluate(camera_id)


def rename_element(camera_id: int, element_id: int, name: str) -> dict | None:
    model = get_model(camera_id)
    if model is None:
        return None
    for e in model["elements"]:
        if e["id"] == element_id:
            e["name"], e["renamed"] = name.strip()[:60] or e["name"], True
    save_model(camera_id, model)
    reevaluate(camera_id)
    return model


def clip_labels(elems: list[dict], model: dict) -> list[tuple[float, float, str, str]]:
    colours = {e["id"]: e["color"] for e in model["elements"]}
    return [(e["start"], e["start"] + e["dur"], e["name"], colours.get(e["id"], "#9ca3af")) for e in elems]


# ------------------------------------------------------------------ background engine
class AnalysisEngine:
    INTERVAL = 60.0

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.exception("analysis engine error")
            await asyncio.sleep(self.INTERVAL)

    def tick(self) -> None:
        with SessionLocal() as db:
            cams = [c.id for c in db.scalars(select(models.Camera)) if (c.config or {}).get("record")]
        for cid in cams:
            if get_model(cid) is None:
                span = data_span(cid)
                if span and span[1] - span[0] >= LEARN_AFTER_MIN * 60:
                    learn_camera(cid, 60, min_cycles=AUTO_LEARN_MIN_CYCLES)
            else:
                analyze_camera(cid)


engine = AnalysisEngine()
