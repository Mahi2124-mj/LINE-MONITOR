"""Cycle / element analysis API (element breakup of every recorded operator cycle)."""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..schemas import CameraConfig
from ..services import analysis as A
from ..services import elements as E
from ..services.clips import cycle_clip, element_thumb
from ..vision.manager import manager

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


class RecordIn(BaseModel):
    on: bool
    process_fps: float | None = Field(None, gt=0, le=15)


class LearnIn(BaseModel):
    minutes: float = Field(60, ge=5, le=24 * 60)


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class CycleStartIn(BaseModel):
    element_id: int


def _cam(db: Session, camera_id: int) -> models.Camera:
    cam = db.get(models.Camera, camera_id)
    if cam is None:
        raise HTTPException(404, "camera not found")
    return cam


def _cycle_out(r: models.AnalysisCycle) -> dict:
    return {"id": r.id, "camera_id": r.camera_id, "start_ts": r.start_ts, "end_ts": r.end_ts, "cycle_sec": r.cycle_sec,
            "status": r.status, "is_master": r.is_master, "issue_count": sum(1 for i in r.issues or [] if i["severity"] != "info"),
            "elements": r.elements, "issues": r.issues}


@router.get("/cameras/{camera_id}")
def summary(camera_id: int, db: Session = Depends(get_db)):
    cam = _cam(db, camera_id)
    station = db.get(models.Station, cam.station_id) if cam.station_id else None
    model = A.get_model(camera_id)
    span = A.data_span(camera_id)
    recording = bool((cam.config or {}).get("record"))
    out: dict = {
        "camera_id": cam.id, "camera_name": cam.name, "station_id": cam.station_id, "station_name": station.name if station else None,
        "line_id": cam.line_id, "recording": recording, "process_fps": (cam.config or {}).get("process_fps"),
        "camera_online": bool(manager.status(cam.id).get("online")),
        "data": {"first_ts": span[0], "last_ts": span[1], "minutes": round((span[1] - span[0]) / 60, 1)} if span else None,
        "learn_after_min": A.LEARN_AFTER_MIN, "model": None, "stats": None,
    }
    if model is None:
        out["state"] = "not_recording" if not recording else "collecting"
        return out
    out["state"] = "ready"
    out["model"] = {k: model[k] for k in ("version", "created_at", "cycles_learned", "cycle_start", "elements", "standard")}
    rows = db.scalars(select(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id,
                                                         models.AnalysisCycle.model_version == model["version"])
                      .order_by(models.AnalysisCycle.start_ts)).all()
    if rows:
        ct = np.array([r.cycle_sec for r in rows])
        per_el: dict[int, list[float]] = defaultdict(list)
        for r in rows:
            sums: dict[int, float] = defaultdict(float)
            for e in r.elements:
                sums[e["id"]] += e["dur"]
            for k, v in sums.items():
                per_el[k].append(v)
        issue_counter: Counter = Counter()
        for r in rows:
            for i in r.issues or []:
                if i["severity"] != "info":
                    issue_counter[(i["type"], i.get("element"))] += 1
        names = {e["id"]: e["name"] for e in model["elements"]}
        names[E.AWAY] = "Operator away"
        labels = {"slow": "slower than standard", "missing": "not done", "repeat": "repeated", "extra": "unplanned action",
                  "order": "done out of order", "away": "operator away", "cycle": "cycle over standard", "short": "unusually short"}
        out["stats"] = {
            "cycles": len(rows), "ok": sum(r.status == "ok" for r in rows), "with_issues": sum(r.status != "ok" for r in rows),
            "avg_cycle": round(float(ct.mean()), 2), "median_cycle": round(float(np.median(ct)), 2), "best_cycle": round(float(ct.min()), 2),
            "elements": [{"id": k, "name": names.get(k, "?"), "count": len(v), "avg": round(float(np.mean(v)), 2),
                          "median": round(float(np.median(v)), 2), "p90": round(float(np.percentile(v, 90)), 2)}
                         for k, v in sorted(per_el.items())],
            "top_issues": [{"type": t, "element": el, "count": n,
                            "text": (f"{names.get(el, '')} " if el is not None else "") + labels.get(t, t)}
                           for (t, el), n in issue_counter.most_common(6)],
        }
    return out


@router.post("/cameras/{camera_id}/record")
def set_recording(camera_id: int, data: RecordIn, db: Session = Depends(get_db)):
    cam = _cam(db, camera_id)
    cfg = dict(cam.config or {})
    cfg["record"] = data.on
    if data.process_fps:
        cfg["process_fps"] = data.process_fps
    cam.config = CameraConfig(**cfg).model_dump()
    db.commit()
    if cam.enabled:
        manager.restart(camera_id)
    return {"recording": data.on, "process_fps": cam.config["process_fps"]}


@router.post("/cameras/{camera_id}/learn")
async def learn(camera_id: int, data: LearnIn):
    model = await asyncio.to_thread(A.learn_camera, camera_id, data.minutes)
    if model is None:
        raise HTTPException(409, "Not enough recorded cycles yet to learn the elements (the operator must be visible doing several cycles).")
    return {"elements": len(model["elements"]), "cycles": model["cycles_learned"]}


@router.post("/cameras/{camera_id}/analyze")
async def analyze_now(camera_id: int):
    n = await asyncio.to_thread(A.analyze_camera, camera_id)
    return {"new_cycles": n}


@router.put("/cameras/{camera_id}/elements/{element_id}")
async def rename(camera_id: int, element_id: int, data: NameIn):
    if await asyncio.to_thread(A.rename_element, camera_id, element_id, data.name) is None:
        raise HTTPException(404, "no element model")
    return {"ok": True}


@router.put("/cameras/{camera_id}/cycle-start")
async def cycle_start(camera_id: int, data: CycleStartIn):
    await asyncio.to_thread(A.set_cycle_start, camera_id, data.element_id)
    return {"ok": True}


@router.delete("/cameras/{camera_id}/master")
async def clear_master(camera_id: int):
    await asyncio.to_thread(A.clear_master, camera_id)
    return {"ok": True}


@router.get("/cameras/{camera_id}/cycles")
def cycles(camera_id: int, status: str = Query("all", pattern="^(all|issues|ok)$"), limit: int = Query(300, ge=1, le=2000),
           db: Session = Depends(get_db)):
    model = A.get_model(camera_id)
    if model is None:
        return []
    q = select(models.AnalysisCycle).where(models.AnalysisCycle.camera_id == camera_id,
                                           models.AnalysisCycle.model_version == model["version"])
    if status != "all":
        q = q.where(models.AnalysisCycle.status == status)
    rows = db.scalars(q.order_by(models.AnalysisCycle.start_ts.desc()).limit(limit)).all()
    return [{k: v for k, v in _cycle_out(r).items() if k not in ("elements", "issues")} |
            {"top_issue": next((i["text"] for i in r.issues or [] if i["severity"] != "info"), None),
             "elements": [{"id": e["id"], "start": e["start"], "dur": e["dur"]} for e in r.elements]} for r in rows]


@router.get("/cycles/{cycle_id}")
def cycle(cycle_id: int, db: Session = Depends(get_db)):
    r = db.get(models.AnalysisCycle, cycle_id)
    if r is None:
        raise HTTPException(404, "cycle not found")
    out = _cycle_out(r)
    model = A.get_model(r.camera_id)
    out["standard"] = model["standard"] if model else None
    q = select(models.AnalysisCycle.id).where(models.AnalysisCycle.camera_id == r.camera_id,
                                              models.AnalysisCycle.model_version == r.model_version)
    out["prev_id"] = db.scalar(q.where(models.AnalysisCycle.start_ts < r.start_ts).order_by(models.AnalysisCycle.start_ts.desc()).limit(1))
    out["next_id"] = db.scalar(q.where(models.AnalysisCycle.start_ts > r.start_ts).order_by(models.AnalysisCycle.start_ts).limit(1))
    return out


@router.post("/cycles/{cycle_id}/master")
async def master(cycle_id: int):
    r = await asyncio.to_thread(A.set_master, cycle_id)
    if r is None:
        raise HTTPException(404, "cycle not found")
    return {"ok": True}


@router.get("/cycles/{cycle_id}/clip.webm")
async def clip(cycle_id: int, db: Session = Depends(get_db)):
    r = db.get(models.AnalysisCycle, cycle_id)
    if r is None:
        raise HTTPException(404, "cycle not found")
    model = A.get_model(r.camera_id) or {"elements": []}
    path = await asyncio.to_thread(cycle_clip, r.camera_id, r.start_ts, r.end_ts, A.clip_labels(r.elements, model))
    if path is None:
        raise HTTPException(410, "The recording of this cycle is no longer available.")
    return FileResponse(path, media_type="video/webm", headers={"Cache-Control": "max-age=86400"})


@router.get("/cameras/{camera_id}/elements/{element_id}/thumb.jpg")
async def thumb(camera_id: int, element_id: int):
    model = A.get_model(camera_id)
    el = next((e for e in (model or {}).get("elements", []) if e["id"] == element_id), None)
    if el is None:
        raise HTTPException(404, "element not found")
    jpg = await asyncio.to_thread(element_thumb, camera_id, el["rep_t"], el["center"])
    if jpg is None:
        raise HTTPException(410, "recording no longer available")
    return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Which cameras record / have an element model (for the navigation)."""
    out = []
    for c in db.scalars(select(models.Camera).order_by(models.Camera.id)):
        rec = bool((c.config or {}).get("record"))
        has_model = db.scalar(select(func.count(models.ElementModel.id)).where(models.ElementModel.camera_id == c.id)) > 0
        if rec or has_model:
            out.append({"camera_id": c.id, "camera_name": c.name, "station_id": c.station_id, "recording": rec, "has_model": has_model})
    return out
