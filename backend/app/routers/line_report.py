"""Line reports for the Reports pages: line summary, machine step detail, operator work vs waiting, cycle variation.

All numbers come from the stored cycles of the chosen time window. Steps counted by the validated step detectors use
only those cycles (see services/detector_feed.py). A cycle is "abnormal" when it is longer than 1.5 x the step's
normal cycle (its median), the same rule the breakup reports use; a line stop inside a cycle makes it abnormal too.
Operator work = work + walking of the operator in the cycle; waiting = waiting for a part or another person."""
from __future__ import annotations

import asyncio
import json
import statistics as stat
import time
from datetime import datetime, timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..services.detector_feed import feed
from ..vision.recorder import list_segments

router = APIRouter(prefix="/api/line-report", tags=["line-report"])

ABNORMAL = 1.5          # x normal cycle
STOP_MIN = 45.0         # a cycle at least this long and 3 x normal = a line stop inside it
MAX_POINTS = 600        # cycles sent for the sequence chart


def _window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    end = end or datetime.now()
    start = start or end.replace(hour=0, minute=0, second=0, microsecond=0)
    if end <= start:
        raise HTTPException(400, "end must be after start")
    if end - start > timedelta(days=31):
        raise HTTPException(400, "at most 31 days")
    return start, end


def _stations(db: Session, line_id: int) -> list[models.Station]:
    return [s for s in db.scalars(select(models.Station).where(models.Station.line_id == line_id).order_by(models.Station.sequence)) if s.is_active]


def _cycles(db: Session, station_ids: list[int], start: datetime, end: datetime) -> dict[int, list[models.Cycle]]:
    C = models.Cycle
    out: dict[int, list[models.Cycle]] = {sid: [] for sid in station_ids}
    q = select(C).where(C.station_id.in_(station_ids), C.ended_at >= start, C.ended_at <= end).order_by(C.ended_at)
    for c in db.scalars(q):
        if c.source == "vision" and feed.owns(c.station_id):  # counted by its validated detector
            continue
        out[c.station_id].append(c)
    return out


def _r(v, n: int = 1):
    return None if v is None else round(float(v), n)


def _stats(cyc: list[models.Cycle]) -> dict:
    """normal cycle, abnormal flags and work / waiting share of one step's cycles"""
    if not cyc:
        return {"total": 0, "normal_cycle": None, "avg_cycle": None, "abnormal": 0, "abnormal_pct": None, "work_pct": None,
                "wait_pct": None, "work_h": 0.0, "wait_h": 0.0, "flags": []}
    secs = [c.cycle_sec for c in cyc]
    med = stat.median(secs)
    flags = [s > ABNORMAL * med for s in secs]
    total_t = sum(secs)
    wait_t = sum(c.wait_sec for c in cyc)
    work_t = max(0.0, total_t - wait_t)
    return {"total": len(cyc), "normal_cycle": _r(med), "avg_cycle": _r(stat.mean(secs)), "abnormal": sum(flags),
            "abnormal_pct": _r(100 * sum(flags) / len(cyc)), "work_pct": _r(100 * work_t / total_t) if total_t else None,
            "wait_pct": _r(100 * wait_t / total_t) if total_t else None, "work_h": _r(work_t / 3600, 2), "wait_h": _r(wait_t / 3600, 2),
            "flags": flags}


def _remark(c: models.Cycle, med: float) -> str:
    if c.cycle_sec >= max(STOP_MIN, 3 * med):
        return "Line stop"
    if c.cycle_sec > ABNORMAL * med:
        return f"Long cycle (+{c.cycle_sec - med:.0f} s)"
    return ""


def _people(stations: list[models.Station]) -> list[tuple[str, list[models.Station]]]:
    groups: dict[str, list[models.Station]] = {}
    for s in stations:
        groups.setdefault(s.operator_name.strip() or f"Step {s.sequence}", []).append(s)
    return sorted(groups.items(), key=lambda g: min(x.sequence for x in g[1]))


# ------------------------------------------------------------------ line summary
@router.get("/{line_id}")
def line_report(line_id: int, start: datetime | None = Query(None), end: datetime | None = Query(None), db: Session = Depends(get_db)):
    line = db.get(models.Line, line_id)
    if line is None:
        raise HTTPException(404, "line not found")
    start, end = _window(start, end)
    sts = _stations(db, line_id)
    cyc = _cycles(db, [s.id for s in sts], start, end)
    steps, allc, flags = [], [], []
    for s in sts:
        st = _stats(cyc[s.id])
        steps.append({"station_id": s.id, "sequence": s.sequence, "name": s.name, "operator": s.operator_name,
                      **{k: v for k, v in st.items() if k != "flags"}})
        allc += cyc[s.id]
        flags += st["flags"]
    total = len(allc)
    abn = sum(flags)
    total_t = sum(c.cycle_sec for c in allc)
    wait_t = sum(c.wait_sec for c in allc)
    # the same window just before, for the change in cycles
    prev = _cycles(db, [s.id for s in sts], start - (end - start), start)
    prev_n = sum(len(v) for v in prev.values())
    # trend: per bucket the average cycle over all steps, and the abnormal cycles in it
    span = (end - start).total_seconds()
    bucket = 300 if span <= 12 * 3600 else 900 if span <= 3 * 86400 else 3600
    by_b: dict[int, list[float]] = {}
    ab_b: dict[int, int] = {}
    for c, f in zip(allc, flags):
        b = int(c.ended_at.timestamp() // bucket * bucket)
        by_b.setdefault(b, []).append(c.cycle_sec)
        ab_b[b] = ab_b.get(b, 0) + int(f)
    trend = [{"t": datetime.fromtimestamp(b).isoformat(timespec="seconds"), "cycle": _r(stat.median(v)), "abnormal": ab_b.get(b, 0), "n": len(v)}
             for b, v in sorted(by_b.items())]
    normal_steps = [x["normal_cycle"] for x in steps if x["normal_cycle"]]
    return {
        "line": {"id": line.id, "name": line.name, "takt_time_sec": line.takt_time_sec},
        "window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")],
        "kpis": {"total_cycles": total, "prev_total_cycles": prev_n,
                 "normal": total - abn, "abnormal": abn,
                 "normal_pct": _r(100 * (total - abn) / total) if total else None, "abnormal_pct": _r(100 * abn / total) if total else None,
                 "avg_cycle": _r(stat.mean(c.cycle_sec for c in allc)) if allc else None,
                 "normal_cycle": _r(stat.median(normal_steps)) if normal_steps else None,
                 "work_pct": _r(100 * (total_t - wait_t) / total_t) if total_t else None, "wait_pct": _r(100 * wait_t / total_t) if total_t else None,
                 "work_h": _r((total_t - wait_t) / 3600, 1), "wait_h": _r(wait_t / 3600, 1)},
        "trend_bucket_sec": bucket,
        "trend": trend,
        "steps": steps,
    }


# ------------------------------------------------------------------ machine step detail
@router.get("/station/{station_id}")
def station_report(station_id: int, start: datetime | None = Query(None), end: datetime | None = Query(None), db: Session = Depends(get_db)):
    s = db.get(models.Station, station_id)
    if s is None:
        raise HTTPException(404, "station not found")
    start, end = _window(start, end)
    sts = _stations(db, s.line_id)
    ids = [x.id for x in sts]
    i = ids.index(s.id) if s.id in ids else 0
    cyc = _cycles(db, [s.id], start, end)[s.id]
    st = _stats(cyc)
    med = st["normal_cycle"] or 0.0
    # distribution: 2-second bins around the normal cycle (wider for slow steps), longer cycles in the last bin
    hist = []
    if cyc:
        width = 2.0 if med <= 20 else 4.0
        lo = max(0.0, np.floor((med - 3 * width) / width) * width)
        edges = [lo + k * width for k in range(8)]
        for k, a in enumerate(edges):
            b = a + width
            last = k == len(edges) - 1
            n = sum(1 for c in cyc if c.cycle_sec >= a and (last or c.cycle_sec < b)) if k else sum(1 for c in cyc if c.cycle_sec < b)
            hist.append({"label": f"{a:.0f}-{b:.0f}" if not last else f"{a:.0f}+", "count": n})
    seq = [{"n": k + 1, "t": c.ended_at.isoformat(timespec="seconds"), "cycle": _r(c.cycle_sec), "abnormal": f}
           for k, (c, f) in enumerate(zip(cyc, st["flags"]))][-MAX_POINTS:]
    from ..services.detector_feed import element_meta
    from .machine_analysis import _sequence

    key = next((c.elements.get("key") for c in reversed(cyc) if c.elements), None)
    names = element_meta().get(key, {}) if key else {}
    recent = [{"n": k + 1, "id": c.id, "start": c.started_at.isoformat(timespec="seconds"), "t0": round(c.started_at.timestamp(), 2),
               "cycle": _r(c.cycle_sec), "status": "Abnormal" if f else "Normal", "operator": s.operator_name or "-", "remark": _remark(c, med),
               "segs": [[e["code"], _r(e["start"], 2), _r(e["dur"], 2)] for e in _sequence(c, names)] if c.elements else []}
              for k, (c, f) in enumerate(zip(cyc, st["flags"]))][-60:][::-1]
    el_meta = [dict(zip(("code", "label", "kind", "color"), (code, *_el_info(names, code)))) for code in names]
    snap = None
    for k in range(len(cyc) - 1, -1, -1):
        if st["flags"][k] and cyc[k].camera_id is not None:
            c = cyc[k]
            mid = c.started_at.timestamp() + c.cycle_sec / 2
            snap = {"n": k + 1, "t": c.started_at.isoformat(timespec="seconds"), "cycle": _r(c.cycle_sec), "camera_id": c.camera_id,
                    "frame_ts": round(mid, 2), "remark": _remark(c, med)}
            break
    return {
        "station": {"id": s.id, "sequence": s.sequence, "name": s.name, "operator": s.operator_name, "line_id": s.line_id},
        "prev_id": ids[i - 1] if i > 0 else None, "next_id": ids[i + 1] if i + 1 < len(ids) else None,
        "window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")],
        "kpis": {k: v for k, v in st.items() if k != "flags"},
        "histogram": hist, "sequence": seq, "recent": recent, "snapshot": snap, "elements": el_meta,
    }


# ------------------------------------------------------------------ operator work vs waiting
@router.get("/{line_id}/operators")
def operators_report(line_id: int, start: datetime | None = Query(None), end: datetime | None = Query(None), db: Session = Depends(get_db)):
    if db.get(models.Line, line_id) is None:
        raise HTTPException(404, "line not found")
    start, end = _window(start, end)
    sts = _stations(db, line_id)
    cyc = _cycles(db, [s.id for s in sts], start, end)
    span = (end - start).total_seconds()
    bucket = 300 if span <= 12 * 3600 else 900 if span <= 3 * 86400 else 3600
    t0 = start.timestamp() // bucket * bucket
    nb = int(np.ceil((end.timestamp() - t0) / bucket))
    out = []
    for label, members in _people(sts):
        # his steps are one loop: the step with most cycles stands for his time
        rep = max(members, key=lambda x: len(cyc[x.id]))
        work = np.zeros(nb)
        motion = np.zeros(nb)
        wait = np.zeros(nb)
        for c in cyc[rep.id]:
            a, b = c.started_at.timestamp(), c.ended_at.timestamp()
            if b <= a:
                continue
            fw, fm, fz = c.work_sec / c.cycle_sec, c.motion_waste_sec / c.cycle_sec, c.wait_sec / c.cycle_sec
            for k in range(max(0, int((a - t0) // bucket)), min(nb, int((b - t0) // bucket) + 1)):
                lo, hi = t0 + k * bucket, t0 + (k + 1) * bucket
                ov = max(0.0, min(b, hi) - max(a, lo))
                work[k] += ov * fw
                motion[k] += ov * fm
                wait[k] += ov * fz
        blocks = []
        for k in range(nb):
            lo = t0 + k * bucket
            length = max(1.0, min(bucket, end.timestamp() - lo, end.timestamp() - start.timestamp()))
            covered = work[k] + motion[k] + wait[k]
            blocks.append({"work": _r(min(1.0, work[k] / length), 2), "motion": _r(min(1.0, motion[k] / length), 2),
                           "wait": _r(min(1.0, (wait[k] + max(0.0, length - covered)) / length), 2)})
        tot = sum(c.cycle_sec for c in cyc[rep.id])
        wt = sum(c.wait_sec for c in cyc[rep.id])
        idle = max(0.0, span - tot)  # no cycle at all (stopped, away, break)
        out.append({"label": label, "steps": [f"{x.sequence}. {x.name}" for x in members],
                    "work_h": _r((tot - wt) / 3600, 2), "wait_h": _r((wt + idle) / 3600, 2),
                    "work_pct": _r(100 * (tot - wt) / span) if span else None, "cycles": len(cyc[rep.id]), "blocks": blocks})
    return {"window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")], "bucket_sec": bucket,
            "bucket_start": datetime.fromtimestamp(t0).isoformat(timespec="seconds"), "operators": out}


# ------------------------------------------------------------------ cycle variation (baratsuki)
@router.get("/{line_id}/variation")
def variation_report(line_id: int, start: datetime | None = Query(None), end: datetime | None = Query(None), db: Session = Depends(get_db)):
    if db.get(models.Line, line_id) is None:
        raise HTTPException(404, "line not found")
    start, end = _window(start, end)
    sts = _stations(db, line_id)
    cyc = _cycles(db, [s.id for s in sts], start, end)
    steps = []
    for s in sts:
        st = _stats(cyc[s.id])
        secs = [c.cycle_sec for c in cyc[s.id]]
        normal = [v for v, f in zip(secs, st["flags"]) if not f]
        row = {"station_id": s.id, "sequence": s.sequence, "name": s.name, "total": st["total"], "normal_cycle": st["normal_cycle"],
               "avg": st["avg_cycle"], "abnormal_count": st["abnormal"], "abnormal_pct": st["abnormal_pct"],
               "wait_pct": st["wait_pct"], "min": None, "q1": None, "median": None, "q3": None, "max": None, "cv": None, "abnormal_values": []}
        if len(normal) >= 3:
            q = np.percentile(normal, [0, 25, 50, 75, 100])
            row.update({"min": _r(q[0]), "q1": _r(q[1]), "median": _r(q[2]), "q3": _r(q[3]), "max": _r(q[4]),
                        "cv": _r(100 * float(np.std(normal)) / float(np.mean(normal)))})
        ab = sorted((v for v, f in zip(secs, st["flags"]) if f), reverse=True)
        row["abnormal_values"] = [_r(v) for v in ab[:12]]
        steps.append(row)
    findings = []
    timed = [x for x in steps if x["cv"] is not None]
    if timed:
        worst = max(timed, key=lambda x: x["cv"])
        findings.append(f"{worst['sequence']}. {worst['name']} varies most: normal cycles spread {worst['cv']:.0f}% around "
                        f"{worst['avg']:.1f} s.")
        ab = [x for x in steps if x["abnormal_count"]]
        if ab:
            top = max(ab, key=lambda x: x["abnormal_pct"] or 0)
            findings.append(f"Most abnormal cycles: {top['sequence']}. {top['name']} ({top['abnormal_count']} of {top['total']}, "
                            f"{top['abnormal_pct']:.0f}%).")
        steady = [x for x in timed if x["cv"] <= 10]
        if steady:
            findings.append(f"{len(steady)} of {len(timed)} steps are steady (spread 10% or less).")
        waits = [x for x in steps if x["wait_pct"] is not None and x["wait_pct"] >= 10]
        if waits:
            w = max(waits, key=lambda x: x["wait_pct"])
            findings.append(f"Most waiting: {w['sequence']}. {w['name']} ({w['wait_pct']:.0f}% of its time waits for a part or a person).")
    return {"window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")], "steps": steps, "findings": findings}


# ------------------------------------------------------------------ a frame of the recording
@router.get("/frame/{camera_id}.jpg")
def recorded_frame(camera_id: int, t: float = Query(...)):
    """the recorded frame nearest to t (epoch seconds), from the camera's 640 recording"""
    best = None
    for _, js in list_segments(camera_id, t - 90, t + 5):
        try:
            for line in js.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                d = abs(r["t"] - t)
                if best is None or d < best[0]:
                    best = (d, js.with_suffix(".mjpg"), r["o"], r["n"])
        except (OSError, ValueError, KeyError):
            continue
    if best is None or best[0] > 10:
        raise HTTPException(404, "no recording at that time (recordings are kept 12 h)")
    with open(best[1], "rb") as fh:
        fh.seek(best[2])
        data = fh.read(best[3])
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})


# ------------------------------------------------------------------ movement and waste per operator
@router.get("/{line_id}/movement")
def movement_report(line_id: int, start: datetime | None = Query(None), end: datetime | None = Query(None), db: Session = Depends(get_db)):
    """Per person, from the element times of the validated step detectors: hand work, walking / carrying, waiting for
    a part or a person, and waiting for a machine, per part. Walking + waiting is the time a better layout or flow
    could win back (an upper bound: some walking is always needed)."""
    from ..services.detector_feed import element_meta

    if db.get(models.Line, line_id) is None:
        raise HTTPException(404, "line not found")
    start, end = _window(start, end)
    sts = _stations(db, line_id)
    cyc = _cycles(db, [s.id for s in sts], start, end)
    meta = element_meta()
    copies: dict[str, int] = {}
    for s in sts:
        if s.parallel_group:
            copies[s.parallel_group] = copies.get(s.parallel_group, 0) + 1
    hours = (end - start).total_seconds() / 3600
    out = []
    for label, members in _people(sts):
        steps = [f"{x.sequence}. {x.name}" for x in members]
        withel = {m.id: [c for c in cyc[m.id] if c.elements] for m in members}
        cands = [m for m in members if withel[m.id]]
        if not cands:
            out.append({"label": label, "steps": steps, "parts": 0, "per_part": None, "elements": [], "saving_per_part": None, "lost_h": None})
            continue
        # each of his steps' detectors sees his whole loop from its own machine, and each separates other parts of it
        # (day crew steps 1-3: the step-3 detector times the walk, the step-2 detector the wait at the jig). Per kind
        # the largest value over his steps counts (the same walk seen by two detectors is not added twice); hand work
        # is the rest of his loop. The loop comes from the step with most cycles.
        k = max((copies.get(m.parallel_group, 1) if m.parallel_group else 1) for m in cands)
        per_st = {}
        for m in cands:
            rows = withel[m.id]
            key = rows[0].elements.get("key")
            names = meta.get(key, {})
            med = stat.median(c.cycle_sec for c in rows)
            normal = [c for c in rows if c.cycle_sec <= ABNORMAL * med] or rows
            sums: dict[str, float] = {}
            seen: dict[str, int] = {}
            for c in normal:
                for code, v in (c.elements.get("el") or {}).items():
                    sums[code] = sums.get(code, 0.0) + v
                    seen[code] = seen.get(code, 0) + 1
            n = len(normal)
            loop = stat.mean(c.cycle_sec for c in normal)
            kinds = {code: names.get(code, [code, "work"])[1] for code in sums}
            split = {kk: sum(sums[c] / n for c in sums if kinds[c] == kk) for kk in ("walk", "wait", "machine")}
            els = [{"code": code, "label": names.get(code, [code])[0], "kind": kinds[code], "avg_per_part": _r(sums[code] / n / k, 2),
                    "share_pct": _r(100 * (sums[code] / n) / loop), "in_cycles_pct": _r(100 * seen[code] / n), "step": f"{m.sequence}. {m.name}"}
                   for code in list(names) + [c for c in sums if c not in names] if code in sums]
            per_st[m.id] = {"station": m, "rows": withel[m.id], "loop": loop, "split": split, "elements": els}
        main = max(per_st.values(), key=lambda x: len(x["rows"]))
        loop = main["loop"]
        split = {"work": 0.0}
        src = {}
        for kk in ("walk", "wait", "machine"):
            best = max(per_st.values(), key=lambda x: x["split"][kk])
            split[kk] = best["split"][kk]
            src[kk] = best
        split["work"] = max(0.0, loop - split["walk"] - split["wait"] - split["machine"])
        # elements: the hand work of the main step, and each walking / waiting element from the step it was taken from
        elements = [e for e in main["elements"] if e["kind"] == "work"]
        for kk in ("walk", "wait", "machine"):
            elements += [e for e in src[kk]["elements"] if e["kind"] == kk]
        per_part = {kk: _r(v / k, 2) for kk, v in split.items()}
        parts = len(main["rows"]) * k
        lost = (split["walk"] + split["wait"]) * len(main["rows"])
        out.append({"label": label, "steps": steps, "detector_step": f"{main['station'].sequence}. {main['station'].name}", "parts": parts,
                    "parts_per_loop": k, "loop_sec": _r(loop), "per_part": per_part, "cycle_per_part": _r(loop / k, 2),
                    "saving_per_part": _r((split["walk"] + split["wait"]) / k, 2), "lost_h": _r(lost / 3600, 2),
                    "saving_per_hour_s": _r((split["walk"] + split["wait"]) / k * (parts / hours), 0) if hours else None,
                    "elements": elements})
    timed = [o for o in out if o["per_part"]]
    totals = {kk: _r(sum(o["per_part"][kk] for o in timed), 1) for kk in ("work", "walk", "wait", "machine")} if timed else None
    return {"window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")], "operators": out, "totals_per_part": totals}


# ------------------------------------------------------------------ element breakup per step (the visual line report)
VIDEO_SEC = 12 * 3600 - 900   # recordings are kept 12 h: example cycles come from the part still recorded
SLOW_ABS, SLOW_REL = 1.0, 0.5  # an element is clearly slower than usual: 1 s and 50 % over its median


def _step_jobs() -> tuple[dict[int, int], dict[int, str]]:
    """station id -> camera its detector reads, station id -> detector key"""
    from ..services.detector_feed import _jobs

    cam, key = {}, {}
    for k, v in _jobs().items():
        for sid in v["stations"]:
            cam[sid], key[sid] = v["cams"][0], k
    return cam, key


def _el_info(names: dict, code: str) -> tuple[str, str, str]:
    row = list(names.get(code) or [code, "work"])
    return row[0], row[1], row[2] if len(row) > 2 else "#94a3b8"


def _example(cands: list[tuple[float, models.Cycle]], cam: int | None) -> dict | None:
    """the cycle with the highest score, from the part of the window still recorded if there is one"""
    if not cands:
        return None
    fresh = [x for x in cands if x[1].started_at.timestamp() >= time.time() - VIDEO_SEC]
    _, c = max(fresh or cands, key=lambda x: x[0])
    return {"cycle_id": c.id, "station_id": c.station_id, "camera_id": c.camera_id or cam, "start": round(c.started_at.timestamp(), 2),
            "end": round(c.ended_at.timestamp(), 2), "sec": _r(c.cycle_sec), "at": c.started_at.isoformat(timespec="seconds"),
            "video": bool(fresh)}


@router.get("/{line_id}/breakdown")
def breakdown_report(line_id: int, start: datetime | None = Query(None), end: datetime | None = Query(None),
                     station_id: int | None = Query(None), db: Session = Depends(get_db)):
    """Per step, from the element times of its checked detector: where the time goes (average per cycle), the spread
    of each element, its trend through the window, the biggest losses with an example cycle each, and a typical and
    the slowest cycle to watch. Steps without a detector get their cycle time only."""
    from ..services.detector_feed import element_meta

    line = db.get(models.Line, line_id)
    if line is None:
        raise HTTPException(404, "line not found")
    start, end = _window(start, end)
    all_sts = _stations(db, line_id)
    sts = [s for s in all_sts if station_id is None or s.id == station_id]
    cyc = _cycles(db, [s.id for s in sts], start, end)
    meta = element_meta()
    cam_of, key_of = _step_jobs()
    span = (end - start).total_seconds()
    bucket = 300 if span <= 12 * 3600 else 900 if span <= 3 * 86400 else 3600
    copies: dict[str, int] = {}
    for s in all_sts:
        if s.parallel_group:
            copies[s.parallel_group] = copies.get(s.parallel_group, 0) + 1
    steps, losses = [], []
    for s in sts:
        allc = cyc[s.id]
        k = copies.get(s.parallel_group, 1) if s.parallel_group else 1
        med_all = stat.median(c.cycle_sec for c in allc) if allc else None
        row = {"station_id": s.id, "sequence": s.sequence, "name": s.name, "operator": s.operator_name, "camera_id": cam_of.get(s.id),
               "cycles": len(allc), "normal_cycle": _r(med_all), "per_part": _r(med_all / k) if med_all else None,
               "pace_per_hour": round(3600 * k / med_all) if med_all else None, "copies": k, "checked": False,
               "avg_normal": None, "elements": [], "trend": [], "typical": None, "slowest": None}
        steps.append(row)
        rows = [c for c in allc if c.source == "detector" and c.elements and c.elements.get("el")]
        if not rows:
            continue
        names = meta.get(rows[0].elements.get("key") or key_of.get(s.id), {})
        cam = cam_of.get(s.id)
        step = f"{s.sequence}. {s.name}"
        med = stat.median(c.cycle_sec for c in rows)
        stop_at = max(STOP_MIN, 3 * med)
        normal = [c for c in rows if c.cycle_sec <= ABNORMAL * med] or rows
        vals: dict[str, list[tuple[float, models.Cycle]]] = {}
        for c in normal:
            for code, v in c.elements["el"].items():
                vals.setdefault(code, []).append((v, c))
        presence = {code: len(v) / len(normal) for code, v in vals.items()}
        elements = []
        for code in list(names) + sorted(set(vals) - set(names)):
            if code not in vals:
                continue
            label, kind, color = _el_info(names, code)
            v = [x for x, _ in vals[code]]
            p10, q1, p50, q3, p90 = (float(x) for x in np.percentile(v, [10, 25, 50, 75, 90]))
            slow = [(x, c) for x, c in vals[code] if x > p50 + max(SLOW_ABS, SLOW_REL * p50)]
            over = sum(x - p50 for x, _ in slow)
            elements.append({"code": code, "label": label, "kind": kind, "color": color, "avg": _r(sum(v) / len(normal), 2),
                             "median": _r(p50, 2), "p10": _r(p10, 2), "q1": _r(q1, 2), "q3": _r(q3, 2), "p90": _r(p90, 2),
                             "max": _r(max(v), 2), "presence_pct": _r(100 * presence[code]), "slow_cycles": len(slow),
                             "over_min": _r(over / 60, 1), "slowest": _example(vals[code], cam)})
            if over >= 30 and slow:
                losses.append({"station_id": s.id, "step": step, "kind": "wait" if kind == "wait" else "element", "code": code,
                               "color": color, "minutes": _r(over / 60, 1), "count": len(slow),
                               "title": f"{label}: longer than its usual {p50:.1f} s in {len(slow)} cycles",
                               "example": _example(slow, cam)})
        longc = [c for c in rows if ABNORMAL * med < c.cycle_sec < stop_at]
        stops = [c for c in rows if c.cycle_sec >= stop_at]
        if longc:
            losses.append({"station_id": s.id, "step": step, "kind": "long", "code": None, "color": "#f59e0b",
                           "minutes": _r(sum(c.cycle_sec - med for c in longc) / 60, 1), "count": len(longc),
                           "title": f"{len(longc)} long cycles ({ABNORMAL:.1f} to 3 x the normal {med:.1f} s)",
                           "example": _example([(c.cycle_sec, c) for c in longc], cam)})
        if stops:
            losses.append({"station_id": s.id, "step": step, "kind": "stop", "code": None, "color": "#ef4444",
                           "minutes": _r(sum(c.cycle_sec - med for c in stops) / 60, 1), "count": len(stops),
                           "title": f"{len(stops)} stops inside a cycle (longest {max(c.cycle_sec for c in stops) / 60:.1f} min)",
                           "example": _example([(c.cycle_sec, c) for c in stops], cam)})
        # a typical cycle: closest to the normal cycle with every usual element (the newest of equal ones)
        usual = {code for code, p in presence.items() if p >= 0.9}
        typical = [(-round(abs(c.cycle_sec - med), 1) + c.started_at.timestamp() * 1e-12, c) for c in normal if usual <= set(c.elements["el"])]
        slowest = [(c.cycle_sec, c) for c in rows if c.cycle_sec < stop_at]
        # the trend: per time block the median cycle and the median of each element
        by_b: dict[int, list[models.Cycle]] = {}
        for c in normal:
            by_b.setdefault(int(c.ended_at.timestamp() // bucket * bucket), []).append(c)
        trend = []
        for b, cs in sorted(by_b.items()):
            el: dict[str, float] = {}
            ea: dict[str, float] = {}  # average per cycle (0 where not done): shows a bin change every few parts
            for code in vals:
                xs = [c.elements["el"][code] for c in cs if code in c.elements["el"]]
                if xs:
                    el[code] = round(stat.median(xs), 2)
                    ea[code] = round(sum(xs) / len(cs), 2)
            trend.append({"t": datetime.fromtimestamp(b).isoformat(timespec="seconds"), "n": len(cs),
                          "cycle": _r(stat.median(c.cycle_sec for c in cs)), "el": el, "ea": ea})
        # pace and bottleneck from the average of the normal cycles: a bin change every few parts slows the step down
        # although its median does not show it
        avg_normal = stat.mean(c.cycle_sec for c in normal)
        row.update({"checked": True, "normal_cycle": _r(med), "per_part": _r(avg_normal / k), "pace_per_hour": round(3600 * k / avg_normal),
                    "avg_normal": _r(avg_normal), "elements": elements, "trend": trend,
                    "typical": _example(typical, cam), "slowest": _example(slowest, cam)})
    timed = [x for x in steps if x["per_part"]]
    bottleneck = max(timed, key=lambda x: x["per_part"])["station_id"] if len(timed) >= 2 else None
    losses.sort(key=lambda x: -(x["minutes"] or 0))
    return {"line": {"id": line.id, "name": line.name, "takt_time_sec": line.takt_time_sec},
            "window": [start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")], "bucket_sec": bucket,
            "bottleneck": bottleneck, "steps": steps, "losses": losses[:10]}


# ------------------------------------------------------------------ one camera of the line in one video, a lane per step on it
def _line_cams(db: Session, line_id: int) -> tuple[list[models.Station], dict[int, int], list[int]]:
    sts = _stations(db, line_id)
    cam_of, _ = _step_jobs()
    cams: list[int] = []
    for s in sts:
        if s.id in cam_of and cam_of[s.id] not in cams:
            cams.append(cam_of[s.id])
    return sts, cam_of, cams


@router.get("/{line_id}/window")
def line_window(line_id: int, camera_id: int | None = Query(None), start: float | None = Query(None), sec: float = Query(60.0),
                db: Session = Depends(get_db)):
    """One window of one camera (default: the newest one) with every checked step on it as a lane of its cycles and
    elements, for the line video. start = unix time."""
    from ..services.clips import OUT_FPS
    from .machine_analysis import WINDOW_SEC, _window_cycles

    if db.get(models.Line, line_id) is None:
        raise HTTPException(404, "line not found")
    sts, cam_of, cams = _line_cams(db, line_id)
    if not cams:
        raise HTTPException(404, "no step of this line has a checked detector")
    cam = camera_id if camera_id in cams else cams[0]
    lane_sts = [s for s in sts if cam_of.get(s.id) == cam]
    sec = min(max(sec, WINDOW_SEC[0]), WINDOW_SEC[1])
    newest = db.scalar(select(models.Cycle.ended_at).where(models.Cycle.station_id.in_([s.id for s in lane_sts]),
                                                          models.Cycle.source == "detector")
                       .order_by(models.Cycle.ended_at.desc()).limit(1))
    latest = (newest.timestamp() if newest else time.time() - 300) - sec
    t0 = latest if start is None else start
    lanes = []
    for s in lane_sts:
        cycles, names, _ = _window_cycles(db, s, t0, sec)
        used = {g[0] for c in cycles for g in c["segs"]}
        lanes.append({"station_id": s.id, "sequence": s.sequence, "name": s.name, "cycles": cycles,
                      "elements": [dict(zip(("code", "label", "kind", "color"), (code, *_el_info(names, code))))
                                   for code in list(names) + sorted(used - set(names))]})
    return {"camera_id": cam, "t0": t0, "start": datetime.fromtimestamp(t0).isoformat(timespec="seconds"), "sec": sec, "fps": OUT_FPS,
            "latest_t0": latest, "lanes": lanes,
            "cameras": [{"camera_id": c, "steps": [f"{s.sequence}. {s.name}" for s in sts if cam_of.get(s.id) == c]} for c in cams]}


@router.get("/{line_id}/window.webm")
async def line_window_video(line_id: int, camera_id: int = Query(...), start: float = Query(...), sec: float = Query(60.0),
                            db: Session = Depends(get_db)):
    from ..services.clips import cycle_clip
    from .machine_analysis import WINDOW_SEC

    _, _, cams = _line_cams(db, line_id)
    if camera_id not in cams:
        raise HTTPException(404, "not a camera of this line")
    sec = min(max(sec, WINDOW_SEC[0]), WINDOW_SEC[1])
    path = await asyncio.to_thread(cycle_clip, camera_id, start, start + sec, None, "plain")
    if path is None:
        raise HTTPException(410, "The recording of this time is no longer available (recordings are kept 12 h).")
    return FileResponse(path, media_type="video/webm", headers={"Cache-Control": "max-age=3600"})
