"""Cycle analysis per machine (step), from the cycles of the validated step detectors (services/detector_feed.py).

Each cycle carries its element times (and, since 2026-10-21, their order). The standard of a step is the median of each
element over its normal cycles in the window (an element counts when it is in at least half of them), or a cycle the
user marks as master. Every cycle is compared with the standard: an element clearly slower, a usual element missing, a
rare element (extra work), the cycle over the standard, or a line stop inside it."""
from __future__ import annotations

import asyncio
import hashlib
import json
import statistics as stat
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..services.clips import OUT_FPS, cycle_clip
from ..services.detector_feed import _jobs, element_meta, feed
from .line_report import ABNORMAL, STOP_MIN, _cycles, _r, _stations, _window

router = APIRouter(prefix="/api/machine-analysis", tags=["machine-analysis"])

MASTERS = settings.data_dir / "machine_masters.json"   # station id -> cycle id chosen as standard
SLOW_ABS, SLOW_REL = 1.0, 0.5    # an element is slow when it is 1 s and 50 % over its standard
OVER = 1.15                      # cycle over the standard: 15 % (and 1.5 s) longer
USUAL, RARE = 0.9, 0.2           # an element is usual in 90 % of the normal cycles, rare in 20 % or less
MAX_LIST = 500
WINDOW_SEC = (20.0, 300.0)       # shortest / longest time one window video covers


def _masters() -> dict:
    try:
        return json.loads(MASTERS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _info(names: dict, code: str) -> tuple[str, str, str]:
    """(label, kind, colour) of an element; kind = work / walk / wait / machine"""
    row = list(names.get(code) or [code, "work"])
    return row[0], row[1], row[2] if len(row) > 2 else "#94a3b8"


def _meta_of(cyc: list[models.Cycle]) -> tuple[str | None, dict]:
    key = next((c.elements.get("key") for c in cyc if c.elements), None)
    return key, element_meta().get(key, {}) if key else {}


def _standard(station_id: int, cyc: list[models.Cycle], db: Session) -> dict:
    """{"source": auto|master, "els": {code: sec}, "presence": {code: share}, "total", "master_id"}"""
    withel = [c for c in cyc if c.elements and c.elements.get("el")]
    presence: dict[str, float] = {}
    if withel:
        med = stat.median(c.cycle_sec for c in withel)
        normal = [c for c in withel if c.cycle_sec <= ABNORMAL * med] or withel
        vals: dict[str, list[float]] = {}
        for c in normal:
            for code, v in c.elements["el"].items():
                vals.setdefault(code, []).append(v)
        presence = {code: len(v) / len(normal) for code, v in vals.items()}
        els = {code: stat.median(v) for code, v in vals.items() if presence[code] >= 0.5}
        total = med
    else:
        els, total = {}, None
    mid = _masters().get(str(station_id))
    if mid:
        m = db.get(models.Cycle, int(mid))
        if m is not None and m.elements and m.elements.get("el"):
            return {"source": "master", "els": dict(m.elements["el"]), "presence": presence, "total": m.cycle_sec, "master_id": m.id}
    return {"source": "auto", "els": els, "presence": presence, "total": total, "master_id": None}


def _issues(c: models.Cycle, std: dict, names: dict, med: float) -> list[str]:
    """What is wrong with one cycle. A cycle has issues when it is clearly over the standard (or a line stop is in it), a
    usual hand-work element is missing, or extra work (a rare element) was done; for a long cycle its clearly slower
    elements are given as the reasons. Every element varies a little, so a slow element alone is not an issue."""
    out = []
    el = (c.elements or {}).get("el") or {}
    label = lambda code: _info(names, code)[0]  # noqa: E731
    kind = lambda code: _info(names, code)[1]  # noqa: E731
    stop = c.cycle_sec >= max(STOP_MIN, 3 * med)
    over = bool(std["total"]) and c.cycle_sec > max(OVER * std["total"], std["total"] + 1.5)
    if stop:
        out.append(f"Line stop in the cycle ({c.cycle_sec:.0f} s)")
    elif over:
        out.append(f"Cycle {c.cycle_sec:.1f} s, over the standard {std['total']:.1f} s")
    for code in std["els"]:
        if code not in el and std["presence"].get(code, 0) >= USUAL and kind(code) == "work":
            out.append(f"{label(code)}: not done")
    for code, v in el.items():
        if code not in std["els"] and std["presence"].get(code, 0) <= RARE and v >= 1.0 and kind(code) in ("work", "walk"):
            out.append(f"Extra: {label(code)} ({v:.1f} s)")
    if over or stop:
        slow = sorted(((v - st, code, v, st) for code, st in std["els"].items()
                       if (v := el.get(code)) is not None and v > st + max(SLOW_ABS, SLOW_REL * st)), reverse=True)
        for _, code, v, st in slow[:3]:
            out.append(f"{label(code)} took {v:.1f} s (standard {st:.1f} s, +{v - st:.1f} s)")
    return out


def _group(text: str) -> str:
    """issue text -> its kind, for the most frequent issues"""
    if text.startswith("Cycle "):
        return "Cycle over the standard"
    if text.startswith("Line stop"):
        return "Line stop in the cycle"
    if " took " in text:
        return text.split(" took ")[0] + " slower than standard"
    if text.endswith(": not done"):
        return text
    return text.split(" (")[0]


def _sequence(c: models.Cycle, names: dict) -> list[dict]:
    """elements of one cycle in time order: from the stored order, else in the detector's element order"""
    e = c.elements or {}
    if e.get("seg"):
        return [{"code": code, "start": off, "dur": dur} for code, off, dur in e["seg"]]
    out, t = [], 0.0
    order = list(names) + [x for x in (e.get("el") or {}) if x not in names]
    for code in order:
        v = (e.get("el") or {}).get(code)
        if v:
            out.append({"code": code, "start": round(t, 2), "dur": v})
            t += v
    return out


# ------------------------------------------------------------------ all machines of the lines
@router.get("")
def overview(start: datetime | None = Query(None), end: datetime | None = Query(None), db: Session = Depends(get_db)):
    start, end = _window(start, end)
    out = []
    for line in db.scalars(select(models.Line).order_by(models.Line.id)):
        if not line.is_active:
            continue
        sts = _stations(db, line.id)
        cyc = _cycles(db, [s.id for s in sts], start, end)
        steps = []
        for s in sts:
            rows = [c for c in cyc[s.id] if c.source == "detector"]
            if not rows:
                steps.append({"station_id": s.id, "sequence": s.sequence, "name": s.name, "checked": feed.owns(s.id), "cycles": 0})
                continue
            med = stat.median(c.cycle_sec for c in rows)
            _, names = _meta_of(rows)
            std = _standard(s.id, rows, db)
            bad = sum(1 for c in rows if _issues(c, std, names, med))
            steps.append({"station_id": s.id, "sequence": s.sequence, "name": s.name, "checked": True, "cycles": len(rows),
                          "normal_cycle": _r(med), "standard": _r(std["total"]), "issues_pct": _r(100 * bad / len(rows)),
                          "operator": s.operator_name})
        out.append({"line": {"id": line.id, "name": line.name, "takt_time_sec": line.takt_time_sec}, "steps": steps})
    return {"window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")], "lines": out}


# ------------------------------------------------------------------ one machine
@router.get("/station/{station_id}")
def machine(station_id: int, start: datetime | None = Query(None), end: datetime | None = Query(None), db: Session = Depends(get_db)):
    s = db.get(models.Station, station_id)
    if s is None:
        raise HTTPException(404, "station not found")
    start, end = _window(start, end)
    sts = _stations(db, s.line_id)
    ids = [x.id for x in sts]
    i = ids.index(s.id) if s.id in ids else 0
    rows = [c for c in _cycles(db, [s.id], start, end)[s.id] if c.source == "detector"]
    key, names = _meta_of(rows)
    std = _standard(s.id, rows, db)
    med = stat.median(c.cycle_sec for c in rows) if rows else 0.0
    cyc_out, counts = [], {}
    normal_secs = []
    for c in rows:
        iss = _issues(c, std, names, med)
        for text in iss:
            counts[_group(text)] = counts.get(_group(text), 0) + 1
        if 0.5 * med <= c.cycle_sec <= ABNORMAL * med:  # a split or merged cycle is not the best one
            normal_secs.append(c.cycle_sec)
        cyc_out.append({"id": c.id, "start": c.started_at.isoformat(timespec="seconds"), "sec": _r(c.cycle_sec), "status": "issues" if iss else "ok",
                        "issue_count": len(iss), "top_issue": iss[0] if iss else None, "is_master": c.id == std["master_id"],
                        "el": _sequence(c, names)})
    elements = []
    for code in list(names) + [x for x in std["presence"] if x not in names]:
        vals = sorted(c.elements["el"][code] for c in rows if c.elements and code in (c.elements.get("el") or {}))
        if not vals:
            continue
        label, kind, color = _info(names, code)
        elements.append({"code": code, "label": label, "kind": kind, "color": color,
                         "standard": _r(std["els"].get(code), 2), "avg": _r(stat.mean(vals), 2), "p90": _r(vals[int(0.9 * (len(vals) - 1))], 2),
                         "presence_pct": _r(100 * std["presence"].get(code, len(vals) / len(rows)))})
    ok = sum(1 for c in cyc_out if c["status"] == "ok")
    return {
        "station": {"id": s.id, "sequence": s.sequence, "name": s.name, "operator": s.operator_name, "line_id": s.line_id},
        "prev_id": ids[i - 1] if i > 0 else None, "next_id": ids[i + 1] if i + 1 < len(ids) else None, "detector": key,
        "window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")],
        "kpis": {"cycles": len(rows), "ok": ok, "with_issues": len(rows) - ok, "avg_cycle": _r(stat.mean(c.cycle_sec for c in rows)) if rows else None,
                 "normal_cycle": _r(med) if rows else None, "best_cycle": _r(min(normal_secs)) if normal_secs else None},
        "standard": {"source": std["source"], "total": _r(std["total"]), "master_id": std["master_id"]},
        "elements": elements,
        "top_issues": sorted(({"text": k, "count": v} for k, v in counts.items()), key=lambda x: -x["count"])[:8],
        "cycles": cyc_out[-MAX_LIST:][::-1],
    }


@router.get("/cycle/{cycle_id}")
def cycle_detail(cycle_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Cycle, cycle_id)
    if c is None or c.source != "detector":
        raise HTTPException(404, "cycle not found")
    day0 = c.started_at.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = [x for x in _cycles(db, [c.station_id], day0, max(c.ended_at, day0))[c.station_id] if x.source == "detector"]
    _, names = _meta_of(rows or [c])
    std = _standard(c.station_id, rows, db)
    med = stat.median(x.cycle_sec for x in rows) if rows else c.cycle_sec
    ids = [x.id for x in rows]
    k = ids.index(c.id) if c.id in ids else -1
    seq = []
    for e in _sequence(c, names):
        label, kind, color = _info(names, e["code"])
        seq.append({**e, "label": label, "kind": kind, "color": color, "standard": _r(std["els"].get(e["code"]), 2)})
    return {"id": c.id, "station_id": c.station_id, "camera_id": c.camera_id, "start": c.started_at.isoformat(timespec="seconds"),
            "end": c.ended_at.isoformat(timespec="seconds"), "sec": _r(c.cycle_sec), "standard_total": _r(std["total"]),
            "is_master": c.id == std["master_id"], "issues": _issues(c, std, names, med), "elements": seq,
            "prev_id": ids[k - 1] if k > 0 else None, "next_id": ids[k + 1] if 0 <= k < len(ids) - 1 else None}


@router.get("/cycle/{cycle_id}/clip.webm")
async def cycle_video(cycle_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Cycle, cycle_id)
    if c is None or c.camera_id is None:
        raise HTTPException(404, "cycle not found")
    _, names = _meta_of([c])
    labels = [(e["start"], e["start"] + e["dur"], _info(names, e["code"])[0], _info(names, e["code"])[2]) for e in _sequence(c, names)]
    path = await asyncio.to_thread(cycle_clip, c.camera_id, c.started_at.timestamp(), c.ended_at.timestamp(), labels)
    if path is None:
        raise HTTPException(410, "The recording of this cycle is no longer available (recordings are kept 12 h).")
    return FileResponse(path, media_type="video/webm", headers={"Cache-Control": "max-age=86400"})


# ------------------------------------------------------------------ a minute of one machine: every cycle in one video
def _window_cycles(db: Session, s: models.Station, t0: float, sec: float) -> tuple[list[dict], dict, int | None]:
    """the machine's cycles in [t0, t0 + sec] (also the ones cut by its ends), numbered, with their elements as
    [code, start, end] in seconds from t0; and the element names and the recorded camera"""
    a, b = datetime.fromtimestamp(t0), datetime.fromtimestamp(t0 + sec)
    rows = db.scalars(select(models.Cycle).where(models.Cycle.station_id == s.id, models.Cycle.source == "detector",
                                                 models.Cycle.ended_at > a, models.Cycle.started_at < b)
                      .order_by(models.Cycle.started_at)).all()
    key, cam = next(((k, v["cams"][0]) for k, v in _jobs().items() if s.id in v["stations"]), (None, None))
    names = element_meta().get(key, {}) if key else _meta_of(rows)[1]
    cam = next((c.camera_id for c in reversed(rows) if c.camera_id), cam)
    out = []
    for n, c in enumerate(rows, 1):
        c0 = c.started_at.timestamp() - t0
        out.append({"n": n, "id": c.id, "start": _r(c0, 2), "end": _r(c.ended_at.timestamp() - t0, 2), "sec": _r(c.cycle_sec),
                    "segs": [[e["code"], _r(c0 + e["start"], 2), _r(c0 + e["start"] + e["dur"], 2)] for e in _sequence(c, names)]})
    return out, names, cam


@router.get("/station/{station_id}/window")
def machine_window(station_id: int, start: float | None = Query(None), sec: float = Query(60.0), db: Session = Depends(get_db)):
    """One window of a machine (default: the newest one) with every cycle in it, for the window video. start = unix time."""
    s = db.get(models.Station, station_id)
    if s is None:
        raise HTTPException(404, "station not found")
    sec = min(max(sec, WINDOW_SEC[0]), WINDOW_SEC[1])
    newest = db.scalar(select(models.Cycle.ended_at).where(models.Cycle.station_id == s.id, models.Cycle.source == "detector")
                       .order_by(models.Cycle.ended_at.desc()).limit(1))
    latest = (newest.timestamp() if newest else time.time() - 300) - sec
    t0 = latest if start is None else start
    cycles, names, cam = _window_cycles(db, s, t0, sec)
    used = {g[0] for c in cycles for g in c["segs"]}
    elements = [{"code": code, "label": _info(names, code)[0], "kind": _info(names, code)[1], "color": _info(names, code)[2]}
                for code in list(names) + sorted(used - set(names)) if code in used]
    return {"station": {"id": s.id, "sequence": s.sequence, "name": s.name}, "camera_id": cam, "t0": t0,
            "start": datetime.fromtimestamp(t0).isoformat(timespec="seconds"), "sec": sec, "fps": OUT_FPS, "latest_t0": latest,
            "elements": elements, "cycles": cycles}


@router.get("/station/{station_id}/window.webm")
async def machine_window_video(station_id: int, start: float = Query(...), sec: float = Query(60.0), db: Session = Depends(get_db)):
    s = db.get(models.Station, station_id)
    if s is None:
        raise HTTPException(404, "station not found")
    sec = min(max(sec, WINDOW_SEC[0]), WINDOW_SEC[1])
    cycles, names, cam = _window_cycles(db, s, start, sec)
    if cam is None:
        raise HTTPException(404, "no recorded camera for this machine")
    labels = [(a, b, f"#{c['n']} {_info(names, code)[0]}", _info(names, code)[2]) for c in cycles for code, a, b in c["segs"]]
    tag = hashlib.md5(json.dumps(labels).encode()).hexdigest()[:8]  # a cycle found later gives a new video
    path = await asyncio.to_thread(cycle_clip, cam, start, start + sec, labels, tag)
    if path is None:
        raise HTTPException(410, "The recording of this time is no longer available (recordings are kept 12 h).")
    return FileResponse(path, media_type="video/webm", headers={"Cache-Control": "max-age=3600"})


@router.post("/cycle/{cycle_id}/master")
def set_master(cycle_id: int, db: Session = Depends(get_db)):
    c = db.get(models.Cycle, cycle_id)
    if c is None or not (c.elements or {}).get("el"):
        raise HTTPException(404, "cycle not found")
    m = _masters()
    m[str(c.station_id)] = c.id
    MASTERS.write_text(json.dumps(m, indent=1), encoding="utf-8")
    return {"ok": True}


@router.delete("/station/{station_id}/master")
def clear_master(station_id: int):
    m = _masters()
    m.pop(str(station_id), None)
    MASTERS.write_text(json.dumps(m, indent=1), encoding="utf-8")
    return {"ok": True}
