"""Line reports for the Reports pages: line summary, machine step detail, operator work vs waiting, cycle variation.

All numbers come from the stored cycles of the chosen time window. Steps counted by the validated step detectors use
only those cycles (see services/detector_feed.py). A cycle is "abnormal" when it is longer than 1.5 x the step's
normal cycle (its median), the same rule the breakup reports use; a line stop inside a cycle makes it abnormal too.
Operator work = work + walking of the operator in the cycle; waiting = waiting for a part or another person."""
from __future__ import annotations

import json
import statistics as stat
from datetime import datetime, timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Response
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
    recent = [{"n": k + 1, "start": c.started_at.isoformat(timespec="seconds"), "cycle": _r(c.cycle_sec),
               "status": "Abnormal" if f else "Normal", "operator": s.operator_name or "-", "remark": _remark(c, med)}
              for k, (c, f) in enumerate(zip(cyc, st["flags"]))][-25:][::-1]
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
        "histogram": hist, "sequence": seq, "recent": recent, "snapshot": snap,
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
