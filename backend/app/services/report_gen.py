"""Automatic cycle / segment breakup report of one machine (camera) from its recording.

Picks the latest stretch of consecutive cycles (the cycles the live detection counted), follows the station operator in
the recorded pose data, finds the places where the operator works (clusters of where they stand), and splits every
cycle into segments: at place X, walking to place Y, away / not visible. Where no operator is seen (automatic machine)
the segments are machine moving / machine still. Writes reports/<name>/: index.html, video.webm (with overlay),
frames/*.jpg, data.json, meta.json.

Runs as a separate low-priority process (python -m app.services.report_gen <camera_id>) so it never slows the cameras.
"""
from __future__ import annotations

import html
import json
import logging
import math
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select

from .. import models
from ..config import settings
from ..database import SessionLocal
from ..vision.recorder import list_segments

log = logging.getLogger("report_gen")

MAX_WINDOW_SEC = 300  # report window: latest consecutive cycles, about 5 minutes ...
MIN_CYCLES = 4  # ... with at least this many complete cycles
LOOKBACK_H = 3  # only cycles of the last hours
WALK_SPEED = 0.22  # feet speed (frame widths / s) that counts as walking
STILL_SPEED = 0.10
PLACE_RADIUS = 0.13
MIN_RUN_SEC = 0.5
PALETTE = ["#2563eb", "#16a34a", "#9333ea", "#0891b2", "#db2777"]
WALK_COLOR, AWAY_COLOR, MOVING_COLOR, STILL_COLOR = "#f59e0b", "#dc2626", "#2563eb", "#94a3b8"


# ------------------------------------------------------------------ data
def _inside(poly: list, x: float, y: float) -> bool:
    return cv2.pointPolygonTest(np.asarray(poly, np.float32).reshape(-1, 1, 2), (float(x), float(y)), False) >= 0


def camera_info(camera_id: int) -> dict | None:
    with SessionLocal() as db:
        cam = db.get(models.Camera, camera_id)
        if cam is None or cam.station_id is None:
            return None
        st = db.get(models.Station, cam.station_id)
        line = db.get(models.Line, cam.line_id)
        return {"camera_id": cam.id, "camera_name": cam.name, "station_id": st.id if st else None,
                "station_name": st.name if st else cam.name, "sequence": st.sequence if st else None,
                "target": st.target_cycle_sec if st else None, "line_name": line.name if line else "",
                "takt": line.takt_time_sec if line else None, "zones": list(cam.zones or [])}


def pick_window(info: dict, now: datetime | None = None) -> tuple[float, float, list[dict]] | None:
    """Latest run of back-to-back cycles of the station (up to MAX_WINDOW_SEC, at least MIN_CYCLES)."""
    now = now or datetime.now()
    with SessionLocal() as db:
        rows = db.scalars(select(models.Cycle).where(
            models.Cycle.station_id == info["station_id"], models.Cycle.ended_at >= now - timedelta(hours=LOOKBACK_H))
            .order_by(models.Cycle.ended_at.desc()).limit(200)).all()
        cyc = [{"start": r.started_at.timestamp(), "end": r.ended_at.timestamp(), "sec": float(r.cycle_sec)} for r in rows]
    run: list[dict] = []
    for c in cyc:  # newest first
        if run and abs(run[-1]["start"] - c["end"]) > 2.0:  # a gap (stop / restart): the run ends here
            if len(run) >= MIN_CYCLES:
                break
            run = []
        if run and run[0]["end"] - c["start"] > MAX_WINDOW_SEC and len(run) >= MIN_CYCLES:
            break
        run.append(c)
    if len(run) < MIN_CYCLES:
        return None
    run.reverse()
    return run[0]["start"] - 8.0, run[-1]["end"] + 8.0, run


def load_frames(camera_id: int, t0: float, t1: float) -> list[dict]:
    """Recorded frames in [t0, t1]: time, file + offset of the JPEG, people (pose) and the station operator index."""
    out = []
    for _, jpath in list_segments(camera_id, t0 - 70, t1):
        mpath = jpath.with_suffix(".mjpg")
        if not mpath.exists():
            continue
        with open(jpath, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    break
                if t0 <= r["t"] <= t1 and "o" in r:
                    out.append({"t": r["t"], "path": mpath, "o": r["o"], "n": r["n"], "p": r.get("p") or [], "op": r.get("op")})
    out.sort(key=lambda r: r["t"])
    return out


def read_frame(fr: dict) -> np.ndarray | None:
    with open(fr["path"], "rb") as f:
        f.seek(fr["o"])
        data = f.read(fr["n"])
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if len(data) == fr["n"] else None


# ------------------------------------------------------------------ operator places
def _feet(p: dict) -> tuple[float, float]:
    b = p["b"]
    return ((b[0] + b[2]) / 2, min(1.0, b[3]))


def _region(x: float, y: float) -> str:
    h = "left" if x < 0.35 else "right" if x > 0.65 else "centre"
    v = "front" if y > 0.75 else "back" if y < 0.45 else "middle"
    return f"{v} {h}"


def find_places(pts: np.ndarray) -> list[np.ndarray]:
    """Where the operator stands still: peaks of a coarse 2-D histogram of feet positions."""
    if len(pts) < 10:
        return []
    bins = 20
    hist, _, _ = np.histogram2d(pts[:, 0], pts[:, 1], bins=bins, range=[[0, 1], [0, 1.0001]])
    hist = cv2.GaussianBlur(hist.astype(np.float32), (3, 3), 0)
    peaks = []
    for _ in range(4):
        i, j = np.unravel_index(int(np.argmax(hist)), hist.shape)
        c = np.array([(i + 0.5) / bins, (j + 0.5) / bins])
        near = pts[np.linalg.norm(pts - c, axis=1) < 0.09]
        if len(near) < max(10, 0.08 * len(pts)):
            break
        center = near.mean(axis=0)
        if all(np.linalg.norm(center - q) > 0.12 for q in peaks):
            peaks.append(center)
        hist[max(0, i - 2):i + 3, max(0, j - 2):j + 3] = 0
    return peaks


def _stand(p: dict) -> tuple[float, float]:
    """Where a person stands: feet if the box ends inside the picture, else the shoulder centre."""
    b = p.get("b")
    if b and b[3] < 0.97:
        return ((b[0] + b[2]) / 2, b[3])
    c = p.get("c") or [0.5, 0.5]
    return (c[0], c[1])


def follow_operator(frames: list[dict], zones: list[dict]) -> list[dict | None]:
    """The station operator per frame: a person standing in the work area (nearest to where the operator was), followed
    a little way out of it; nobody there = None. Steadier than the per-frame pick stored in the recording."""
    areas = [z["points"] for z in zones if z.get("type") == "work_area" and z.get("points")]
    centre = None
    if areas:
        pts = np.vstack([np.asarray(a, float) for a in areas])
        centre = pts.mean(axis=0)
    def body(p: dict) -> tuple[float, float]:  # shoulder centre: stays in the picture when the feet are cut off
        c = p.get("c")
        return (c[0], c[1]) if c else ((p["b"][0] + p["b"][2]) / 2, (p["b"][1] + p["b"][3]) / 2)

    def in_area(p: dict) -> bool:
        return not areas or any(_inside(a, *pt) for a in areas for pt in (_stand(p), body(p)))

    out: list[dict | None] = []
    last = None
    for f in frames:
        people = [p for p in f["p"] if p.get("b") and p.get("k")]
        inside = [p for p in people if in_area(p)]
        pick = None
        if inside:
            ref = last if last is not None else centre
            pick = min(inside, key=lambda p: math.dist(body(p), ref)) if ref is not None else max(
                inside, key=lambda p: (p["b"][2] - p["b"][0]) * (p["b"][3] - p["b"][1]))
        elif last is not None and people:  # just walked out of the area: keep following for a moment
            near = min(people, key=lambda p: math.dist(body(p), last))
            if math.dist(body(near), last) < 0.15:
                pick = near
        if pick is not None:
            last = body(pick)
        out.append(pick)
    return out


def _runs(labels: list[str]) -> list[list]:
    rs: list[list] = []
    for i, l in enumerate(labels):
        if rs and rs[-1][0] == l:
            rs[-1][2] = i
        else:
            rs.append([l, i, i])
    return rs


def _smooth(labels: list[str], T: np.ndarray, protect: set[str] = frozenset()) -> list[str]:
    L = list(labels)
    for i in range(1, len(L) - 1):  # single-frame flicker
        if L[i - 1] == L[i + 1] != L[i] and L[i] not in protect:
            L[i] = L[i - 1]
    while True:
        rs = _runs(L)
        short = [k for k, (l, i, j) in enumerate(rs) if T[j] - T[i] < MIN_RUN_SEC and len(rs) > 1 and l not in protect]
        if not short:
            return L
        k = short[0]
        nb = rs[k - 1] if k > 0 else rs[k + 1]
        for q in range(rs[k][1], rs[k][2] + 1):
            L[q] = nb[0]


# ------------------------------------------------------------------ main analysis
def analyse(info: dict, frames: list[dict], cycles: list[dict]) -> dict:
    T = np.array([f["t"] for f in frames])
    parts = [z for z in info["zones"] if z.get("type") == "part_zone" and z.get("points")]
    picks = [z for z in info["zones"] if z.get("type") == "pick_zone" and z.get("points")]
    ops = follow_operator(frames, info["zones"])
    visible = np.mean([p is not None for p in ops]) if ops else 0.0
    machine_mode = bool(visible < 0.25 and parts)

    labels: list[str] = []
    names: dict[str, tuple[str, str]] = {}  # code -> (name, colour)
    fixture_hit = np.zeros(len(frames), bool)
    pos: list[tuple[float, float] | None] = []

    if machine_mode:
        # operator (almost) never in view: segments from motion inside the part zone(s)
        bg = cv2.createBackgroundSubtractorMOG2(history=400, varThreshold=40, detectShadows=False)
        masks = None
        moving = []
        for f in frames:
            img = read_frame(f)
            if img is None:
                moving.append(False)
                continue
            h, w = img.shape[:2]
            if masks is None:
                masks = []
                for z in parts:
                    m = np.zeros((h, w), np.uint8)
                    cv2.fillPoly(m, [(np.asarray(z["points"]) * [w, h]).astype(np.int32)], 255)
                    masks.append(m > 0)
            g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
            fg = bg.apply(cv2.resize(g, (w // 2, h // 2)))
            fg = cv2.resize(cv2.dilate(cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), np.ones((5, 5), np.uint8)),
                            (w, h), interpolation=cv2.INTER_NEAREST)
            moving.append(any(np.count_nonzero(fg[m]) / max(1, m.sum()) >= 0.04 for m in masks))
        labels = ["MOVING" if m else "STILL" for m in moving]
        names = {"MOVING": ("Motion in the fixture zone (machine / hands)", MOVING_COLOR),
                 "STILL": ("No motion in the fixture zone", STILL_COLOR)}
        pos = [None] * len(frames)
        places: list[np.ndarray] = []
    else:
        for k, p in enumerate(ops):
            if p is None:
                pos.append(None)
                continue
            pos.append(_feet(p))
            wr = [(p["k"][q][0], p["k"][q][1]) for q in (9, 10) if len(p.get("k") or []) > q and p["k"][q][2] >= 0.35]
            fixture_hit[k] = any(_inside(z["points"], x, y) for z in parts for x, y in wr)
        speed = np.zeros(len(frames))
        for i in range(1, len(frames) - 1):
            if pos[i - 1] is not None and pos[i + 1] is not None:
                speed[i] = math.dist(pos[i + 1], pos[i - 1]) / max(1e-3, T[i + 1] - T[i - 1])
        still = np.array([pos[i] for i in range(len(frames)) if pos[i] is not None and speed[i] < STILL_SPEED])
        places = find_places(still) if len(still) else []
        # name the places: the one where the hands are at a part fixture gets the fixture's name
        place_names, fixture_places = [], set()
        for k, c in enumerate(places):
            near = [i for i in range(len(frames)) if pos[i] is not None and math.dist(pos[i], c) < PLACE_RADIUS]
            share = float(np.mean(fixture_hit[near])) if near else 0.0
            zname = None
            if share >= 0.25 and parts:
                counts = {}
                for i in near:
                    p = ops[i]
                    for q in (9, 10):
                        if p["k"][q][2] >= 0.35:
                            for z in parts:
                                if _inside(z["points"], p["k"][q][0], p["k"][q][1]):
                                    counts[z.get("name") or "fixture"] = counts.get(z.get("name") or "fixture", 0) + 1
                zname = max(counts, key=counts.get) if counts else None
            label = f"Work at {zname}" if zname else f"Work at place {k + 1}"
            place_names.append(f"{label} ({_region(*c)})")
            if zname:
                fixture_places.add(k)
        for k, nm in enumerate(place_names):
            if k in fixture_places:  # at the fixture: hands in it vs. hands elsewhere (picking parts, other work)
                base = nm.split(" (")[0].replace("Work at ", "")
                names[f"P{k}"] = (f"{base}: hands in the fixture ({_region(*places[k])})", PALETTE[k % len(PALETTE)])
                names[f"P{k}x"] = (f"{base}: hands outside (picking parts / other work)", "#7dd3fc")
            else:
                names[f"P{k}"] = (nm, PALETTE[k % len(PALETTE)])
        for i in range(len(frames)):
            if pos[i] is None:
                labels.append("AWAY")
            elif speed[i] > WALK_SPEED and not fixture_hit[i]:
                labels.append("WALK")
            else:
                d = [math.dist(pos[i], c) for c in places]
                if d and min(d) < PLACE_RADIUS:
                    k = int(np.argmin(d))
                    labels.append(f"P{k}x" if k in fixture_places and not fixture_hit[i] else f"P{k}")
                else:
                    labels.append("WALK")
        names["AWAY"] = ("Operator not visible / away from the station", AWAY_COLOR)

    labels = _smooth(labels, T)
    if not machine_mode:  # walking: towards which place
        rs = _runs(labels)
        for k, (l, i, j) in enumerate(rs):
            if l == "WALK":
                nxt = next((r[0].rstrip("x") for r in rs[k + 1:] if r[0].startswith("P")), None)
                code = f"W{nxt}" if nxt else "WALK"
                for q in range(i, j + 1):
                    labels[q] = code
                if code not in names:
                    names[code] = (f"Walk → {names[nxt][0].split(' (')[0].split(':')[0]}" if nxt else "Walk", WALK_COLOR)
    rs = _runs(labels)
    segments = [{"code": l, "t0": float(T[i]), "t1": float(T[j + 1] if j + 1 < len(T) else T[j])} for l, i, j in rs]

    # cycles of the live detection, cut into segments
    dt_ = np.diff(T, append=T[-1])
    out_cycles = []
    for n, c in enumerate(cycles, start=1):
        segs = []
        for s in segments:
            a, b = max(s["t0"], c["start"]), min(s["t1"], c["end"])
            if b - a > 0.05:
                segs.append({"code": s["code"], "t0": a, "t1": b})
        per = {code: round(sum(s["t1"] - s["t0"] for s in segs if s["code"] == code), 1) for code in names}
        sel = (T >= c["start"]) & (T < c["end"])
        out_cycles.append({"n": n, "start": c["start"], "end": c["end"], "sec": round(c["end"] - c["start"], 1),
                           "segments": segs, "per": per, "fixture_sec": round(float(dt_[sel & fixture_hit].sum()), 1)})
    secs = [c["sec"] for c in out_cycles]
    med = float(np.median(secs))
    base = [c for c in out_cycles if c["sec"] <= 1.3 * med] or out_cycles
    med_per = {code: round(float(np.median([c["per"][code] for c in base])), 1) for code in names}
    for c in out_cycles:
        notes = []
        for code, (nm, _) in names.items():
            extra = c["per"][code] - med_per[code]
            if extra > max(3.0, 0.5 * med_per[code]):
                notes.append(f"{nm}: {c['per'][code]:.1f}s (normal {med_per[code]:.1f}s)")
        c["normal"] = bool(c["sec"] <= 1.3 * med and not notes)
        if c["sec"] > 1.3 * med and not notes:
            notes.append(f"Cycle {c['sec']:.1f}s, normal {med:.1f}s")
        c["notes"] = notes or ["Normal cycle"]
    two_people = np.mean([sum(1 for p in f["p"] if p.get("b") and (p["b"][3] - p["b"][1]) > 0.3) >= 2 for f in frames]) if frames else 0
    return {"T0": float(T[0]), "T1": float(T[-1]), "fps": round(len(T) / max(1e-3, T[-1] - T[0]), 1), "machine_mode": machine_mode,
            "visible": round(float(visible), 2), "two_people": round(float(two_people), 2), "names": names,
            "segments": segments, "cycles": out_cycles, "median": round(med, 1), "median_per": med_per,
            "places": [[round(float(v), 3) for v in c] for c in places], "pos": pos}


# ------------------------------------------------------------------ outputs
def _bgr(hexcol: str) -> tuple[int, int, int]:
    return tuple(int(hexcol[q:q + 2], 16) for q in (5, 3, 1))


def write_video(frames: list[dict], A: dict, path: Path) -> None:
    names, segs, cycles = A["names"], A["segments"], A["cycles"]
    W, H = 640, 360
    fps = max(1.0, len(frames) / max(1e-3, A["T1"] - A["T0"]))
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP90"), fps, (W, H))
    prev = np.zeros((H, W, 3), np.uint8)
    for k, f in enumerate(frames):
        img = read_frame(f)  # a broken picture repeats the previous one: video frame k = recorded frame k
        img = cv2.resize(img, (W, H)) if img is not None else prev.copy()
        prev = img.copy()
        t = f["t"]
        s = next((x for x in segs if x["t0"] <= t < x["t1"]), None)
        c = next((x for x in cycles if x["start"] <= t < x["end"]), None)
        p = A["pos"][k]
        if p is not None:
            cv2.circle(img, (int(p[0] * W), int(min(p[1], 0.97) * H)), 9, (0, 255, 255), 2)
        cv2.rectangle(img, (0, 0), (W, 60), (0, 0, 0), -1)
        clock = datetime.fromtimestamp(t).strftime("%H:%M:%S")
        head = f"{clock}   Cycle {c['n']}   {t - c['start']:5.1f}s / {c['sec']:.1f}s" if c else f"{clock}   (incomplete cycle, not counted)"
        cv2.putText(img, head, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1, cv2.LINE_AA)
        if s:
            nm, col = names[s["code"]]
            cv2.rectangle(img, (10, 34), (26, 52), _bgr(col), -1)
            cv2.putText(img, f"{nm.split(' (')[0][:48]}  {t - s['t0']:.1f}s", (32, 49), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
        if c:
            x0 = 0
            for sg in c["segments"]:
                x1 = int((sg["t1"] - c["start"]) / c["sec"] * W)
                cv2.rectangle(img, (x0, H - 12), (x1, H), _bgr(names[sg["code"]][1]), -1)
                x0 = x1
            cx = int((t - c["start"]) / c["sec"] * W)
            cv2.rectangle(img, (cx - 2, H - 18), (cx + 2, H), (255, 255, 255), -1)
        vw.write(img)
    vw.release()


def timeline(times: list[float], segments: list[dict], cycles: list[dict], names: dict) -> dict:
    """Data for the report player: video seconds of every segment / cycle and the wall clock of every video frame."""
    T = np.asarray(times, float)
    fps = len(T) / max(1e-3, T[-1] - T[0])
    vt = lambda t: round(float(np.searchsorted(T, t) / fps), 3)  # noqa: E731
    return {"fps": round(fps, 4), "t0": float(T[0]), "t": [round(float(x - T[0]), 2) for x in T],
            "names": {k: list(v) for k, v in names.items()},
            "segments": [[s["code"], vt(s["t0"]), vt(s["t1"])] for s in segments],
            "cycles": [[c["n"], vt(c["start"]), vt(c["end"]), bool(c.get("normal", True))] for c in cycles]}


PLAYER_HEAD = '<link rel=stylesheet href="../_assets/report_player.css">'
PLAYER_BODY = '<script src="../_assets/report_player.js"></script>'
CHARTS_BODY = '<script src="../_assets/report_charts.js"></script>'
VARIATION_HTML = ('<h2 id=variation>Variation (baratsuki) – element times of consecutive cycles</h2>'
                  '<div class=card id=baratsuki>Loading…</div>')


def publish(tmp: Path, final: Path) -> None:
    """Replace a report folder by its freshly built .tmp copy. Windows may hold a deleted folder (or a video being
    streamed) for a moment, so the swap is retried."""
    import shutil

    for _ in range(20):
        try:
            if final.exists():
                shutil.rmtree(final)
            tmp.rename(final)
            return
        except OSError:
            time.sleep(1.0)
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)


def variation_data(elements: list[tuple[str, str, str]], cycles: list[dict], v0: float, v1: float) -> dict:
    """cycles.json for the variation chart (static/report_charts.js). elements: (code, name, colour) in cycle order;
    cycles: start, end, sec, el {code: seconds or None}, flag normal / long / stop, optional note."""
    out, vn = [], 0
    for n, c in enumerate(cycles, start=1):
        inv = bool(c["start"] >= v0 and c["end"] <= v1)
        vn += inv
        out.append({"n": n, "vn": vn if inv else None, "clock": datetime.fromtimestamp(float(c["start"])).strftime("%H:%M:%S"),
                    "v": round(float(c["start"] - v0), 2) if inv else None, "sec": round(float(c["sec"]), 2), "flag": c["flag"],
                    "note": c.get("note") or "", "el": {k: (None if v is None else round(float(v), 2)) for k, v in c["el"].items()}})
    return {"elements": [{"code": k, "name": n, "color": col} for k, n, col in elements], "cycles": out}


def _thumb(frames: list[dict], t: float, path: Path) -> bool:
    fr = min(frames, key=lambda f: abs(f["t"] - t))
    img = read_frame(fr)
    if img is None:
        return False
    img = cv2.resize(img, (320, int(img.shape[0] * 320 / img.shape[1])))
    return bool(cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 80]))


def write_report(info: dict, frames: list[dict], A: dict, out: Path) -> dict:
    names, cycles, med, mp = A["names"], A["cycles"], A["median"], A["median_per"]
    normal = [c for c in cycles if c["normal"]] or cycles
    T0 = A["T0"]
    fps = len(frames) / max(1e-3, A["T1"] - T0)
    times = np.array([f["t"] for f in frames])
    vt = lambda t: float(np.searchsorted(times, t) / fps)  # noqa: E731  wall clock -> seconds into the video
    nmed = float(np.median([c["sec"] for c in normal]))
    lost = sum(c["sec"] - nmed for c in cycles if not c["normal"])
    typical = min(normal, key=lambda c: abs(c["sec"] - nmed))
    (out / "frames").mkdir(exist_ok=True)
    trows = []
    for k, s in enumerate(typical["segments"], start=1):
        _thumb(frames, (s["t0"] + s["t1"]) / 2, out / "frames" / f"seg{k}.jpg")
        nm, col = names[s["code"]]
        trows.append(f"<tr onclick=\"seek({vt(s['t0']):.2f})\"><td class=n>{k}</td><td><span class=dot style=\"background:{col}\"></span>{html.escape(nm)}</td>"
                     f"<td class=num>{s['t0'] - typical['start']:.1f} – {s['t1'] - typical['start']:.1f}s</td><td class=num><b>{s['t1'] - s['t0']:.1f}s</b></td>"
                     f"<td><img src=\"frames/seg{k}.jpg\" alt=\"\" loading=lazy></td></tr>")
    order = [code for code in names if any(c["per"][code] > 0 for c in cycles)]
    rows = []
    scale = max(c["sec"] for c in normal) * 1.05
    for c in cycles:
        bar = "".join(f'<i style="width:{(s["t1"] - s["t0"]) / (c["sec"] if not c["normal"] else scale) * 100:.2f}%;background:{names[s["code"]][1]}" '
                      f'title="{html.escape(names[s["code"]][0])}: {s["t1"] - s["t0"]:.1f}s"></i>' for s in c["segments"])
        cells = "".join(f"<td class=num>{c['per'][code]:.1f}</td>" for code in order)
        rows.append(f"<tr{'' if c['normal'] else ' class=bad'} onclick=\"seek({vt(c['start']):.2f})\"><td class=n>{c['n']}</td>"
                    f"<td class=num>{datetime.fromtimestamp(c['start']):%H:%M:%S}</td><td class=num>{datetime.fromtimestamp(c['end']):%H:%M:%S}</td>"
                    f"<td class=num><b>{c['sec']:.1f}s</b></td>{cells}<td class=wide><div class=bar>{bar}</div></td><td>{html.escape('; '.join(c['notes']))}</td></tr>")
    heads = "".join(f"<th><span class=dot style=\"background:{names[code][1]}\"></span>{html.escape(names[code][0].split(' (')[0])}</th>" for code in order)
    foot = "".join(f"<th class=num>{mp[code]:.1f}</th>" for code in order)
    legend = "".join(f'<span><span class=dot style="background:{names[code][1]}"></span>{html.escape(names[code][0])}</span>' for code in order)

    # observations
    obs = []
    share = {code: mp[code] / nmed for code in order if nmed}
    if A["machine_mode"]:
        obs.append("The operator is rarely visible on this camera, so cycles and segments come from <b>machine motion</b> "
                   f"in the fixture zone: motion ~{mp.get('MOVING', 0):.1f}s, no motion ~{mp.get('STILL', 0):.1f}s per cycle.")
    else:
        top = max((c for c in order if c.startswith("P")), key=lambda c: mp[c], default=None)
        if top:
            obs.append(f"Longest: <b>{html.escape(names[top][0])}</b> ~{mp[top]:.1f}s per cycle ({100 * share[top]:.0f}%).")
        walk = sum(mp[c] for c in order if c.startswith("W"))
        obs.append(f"Walking ~{walk:.1f}s per cycle ({100 * walk / nmed:.0f}%)." + ("" if walk / nmed < 0.12 else " Moving material or machines closer would save time."))
        if mp.get("AWAY", 0) > 0.5:
            obs.append(f"Operator not visible or away from the station ~{mp['AWAY']:.1f}s per cycle.")
        fx = float(np.median([c["fixture_sec"] for c in normal]))
        if fx > 0:
            obs.append(f"Hands in the fixture ~{fx:.1f}s per cycle ({100 * fx / nmed:.0f}%).")
        if len({c.rstrip("x") for c in order if c.startswith("P")}) >= 2:
            obs.append("The operator works at more than one place; check whether he also runs another machine or station.")
    q1, q3 = np.percentile([c["sec"] for c in normal], [25, 75])
    obs.append(f"Normal cycles {min(c['sec'] for c in normal):.1f}–{max(c['sec'] for c in normal):.1f}s (middle 50 %: {q1:.1f}–{q3:.1f}s).")
    if lost > 1:
        obs.append(f"{len(cycles) - len(normal)} abnormal cycles: ~{lost:.0f}s lost (see the notes in the table).")
    if info.get("target"):
        diff = nmed - info["target"]
        obs.append(f"Target cycle {info['target']:.1f}s: the normal cycle is {abs(diff):.1f}s {'over' if diff > 0 else 'under'}.")
    if A["two_people"] > 0.3:
        obs.append(f"2+ people in view {100 * A['two_people']:.0f}% of the time; the breakup follows the station operator picked by the system.")

    method = ("start of machine motion → next start" if A["machine_mode"]
              else "operator's hands reach the fixture → next time")
    first, last = cycles[0], cycles[-1]
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{html.escape(info['station_name'])} breakup</title>
<style>
:root{{--bg:#f8fafc;--panel:#fff;--ink:#0f172a;--ink2:#475569;--edge:#e2e8f0;--bad:#fef2f2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--panel:#111827;--ink:#e5e7eb;--ink2:#9ca3af;--edge:#1f2937;--bad:#3b1111}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:16px}} h1{{font-size:20px;margin:4px 0}} h2{{font-size:16px;margin:22px 0 8px}}
.sub{{color:var(--ink2)}} .card{{background:var(--panel);border:1px solid var(--edge);border-radius:10px;padding:14px;margin:12px 0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}} .kpi b{{display:block;font-size:22px}} .kpi span{{color:var(--ink2);font-size:12px}}
video{{width:100%;max-height:560px;background:#000;border-radius:8px}}
table{{width:100%;border-collapse:collapse}} th,td{{padding:6px 8px;border-bottom:1px solid var(--edge);text-align:left;vertical-align:middle}}
th{{font-size:12px;color:var(--ink2);font-weight:600}} td.num,th.num{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}} td.n{{color:var(--ink2)}}
tr.bad{{background:var(--bad)}} tbody tr{{cursor:pointer}} tbody tr:hover{{outline:1px solid #3b82f6}}
.bar{{display:flex;height:14px;border-radius:3px;overflow:hidden;background:var(--edge);min-width:160px}} .bar i{{display:block;height:100%}}
td.wide{{width:26%}} .dot{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0}} td img{{width:160px;border-radius:4px}}
ul{{margin:6px 0;padding-left:20px}} li{{margin:4px 0}} .scroll{{overflow-x:auto}}
</style>{PLAYER_HEAD}</head><body><main>
<h1>{html.escape(info['station_name'])} — cycle and segment breakup</h1>
<div class=sub>{html.escape(info['line_name'])} · {html.escape(info['camera_name'])} · {datetime.fromtimestamp(T0):%d %b %Y, %H:%M:%S}–{datetime.fromtimestamp(A['T1']):%H:%M:%S} · recording {A['fps']} frame/s · automatic report ({datetime.now():%H:%M})</div>
<div class="card kpis">
<div class=kpi><b>{len(cycles)}</b><span>complete cycles in the video</span></div>
<div class=kpi><b>{nmed:.1f}s</b><span>normal cycle (median)</span></div>
<div class=kpi><b>{min(c['sec'] for c in normal):.1f} – {max(c['sec'] for c in normal):.1f}s</b><span>normal cycle range</span></div>
<div class=kpi><b>{len(cycles) - len(normal)}</b><span>abnormal cycles{f' ({lost:.0f}s lost)' if lost > 1 else ''}</span></div>
</div>
<div class=card><video id=v src="video.webm" controls preload=metadata></video><div class=legend>{legend}</div>
<div class=sub>Overlay: clock, cycle number and timer, current segment; yellow circle = operator. Click a table row to jump there.</div></div>
{VARIATION_HTML}
<h2>Where each cycle starts and ends</h2>
<div class=card><ul>
<li><b>One cycle</b>: {method} (same rule as the dashboard cycle time).</li>
<li>First complete cycle starts at <b>{datetime.fromtimestamp(first['start']):%H:%M:%S}</b>; the first {first['start'] - T0:.0f}s of the video are an incomplete cycle (not counted).</li>
<li>Last complete cycle ends at <b>{datetime.fromtimestamp(last['end']):%H:%M:%S}</b>; the last {A['T1'] - last['end']:.0f}s are incomplete.</li>
{''.join(f"<li>Cycle {c['n']} abnormal ({c['sec']:.1f}s): {html.escape('; '.join(c['notes']))}</li>" for c in cycles if not c['normal'])}
</ul></div>
<h2>Segment breakup of every cycle (seconds)</h2>
<div class="card scroll"><table><thead><tr><th>#</th><th>Start</th><th>End</th><th>Cycle</th>{heads}<th>Segments</th><th>Note</th></tr></thead>
<tbody>{''.join(rows)}</tbody><tfoot><tr><th></th><th colspan=2>Normal (median)</th><th class=num>{nmed:.1f}s</th>{foot}<th colspan=2></th></tr></tfoot></table></div>
<h2>One normal cycle (cycle {typical['n']}: {datetime.fromtimestamp(typical['start']):%H:%M:%S} → {datetime.fromtimestamp(typical['end']):%H:%M:%S}, {typical['sec']:.1f}s)</h2>
<div class="card scroll"><table><thead><tr><th>#</th><th>Segment</th><th>In cycle</th><th>Time</th><th>Frame</th></tr></thead><tbody>{''.join(trows)}</tbody></table></div>
<h2>Findings</h2><div class=card><ul>{''.join(f'<li>{o}</li>' for o in obs)}</ul></div>
<div class=sub>Automatic report: cycles from the dashboard's live cycle detection, segments from the operator's position (pose){' and machine motion' if A['machine_mode'] else ''}.
Places are found automatically (where the operator stands still). Short actions such as picking a part are not separated; use the video for those.</div>
</main>{PLAYER_BODY}{CHARTS_BODY}
</body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    for c in cycles:
        c["flag"], c["note"] = ("normal" if c["normal"] else "long"), ("" if c["normal"] else "; ".join(c["notes"]))
        c["el"] = {code: c["per"][code] for code in order}
    var = variation_data([(code, names[code][0], names[code][1]) for code in order], cycles, T0, A["T1"] + 1)
    for c, d in zip(cycles, var["cycles"]):
        d["v"] = round(vt(c["start"]), 2)
    (out / "cycles.json").write_text(json.dumps(var, separators=(",", ":")), encoding="utf-8")
    highlights = [f"Normal cycle {nmed:.1f}s ({min(c['sec'] for c in normal):.1f}–{max(c['sec'] for c in normal):.1f}s), {len(cycles)} cycles"]
    highlights += [o.replace("<b>", "").replace("</b>", "") for o in obs[:2]]
    if lost > 1:
        highlights.append(f"{len(cycles) - len(normal)} abnormal cycles, ~{lost:.0f}s lost")
    return {"title": f"{info['station_name']} — cycle breakup", "subtitle": f"{info['line_name']} · {info['camera_name']}",
            "camera_id": info["camera_id"], "station_id": info["station_id"], "sequence": info["sequence"], "auto": True,
            "date": datetime.fromtimestamp(T0).strftime("%Y-%m-%d"),
            "window": f"{datetime.fromtimestamp(T0):%H:%M:%S} – {datetime.fromtimestamp(A['T1']):%H:%M:%S}",
            "cycles": len(cycles), "median_cycle": round(nmed, 1), "highlights": highlights[:4]}


def generate(camera_id: int, window: tuple[float, float] | None = None) -> Path | None:
    info = camera_info(camera_id)
    if info is None:
        log.info("camera %s: no station", camera_id)
        return None
    picked = pick_window(info)
    if picked is None:
        log.info("camera %s: not enough consecutive cycles in the last %sh", camera_id, LOOKBACK_H)
        return None
    t0, t1, cycles = picked
    frames = load_frames(camera_id, t0, t1)
    if len(frames) < 50 or frames[-1]["t"] - frames[0]["t"] < 0.8 * (t1 - t0):
        log.info("camera %s: recording does not cover %s-%s", camera_id, datetime.fromtimestamp(t0), datetime.fromtimestamp(t1))
        return None
    cycles = [c for c in cycles if c["start"] >= frames[0]["t"] and c["end"] <= frames[-1]["t"]]
    if len(cycles) < MIN_CYCLES:
        return None
    A = analyse(info, frames, cycles)
    name = f"auto_cam{camera_id}_{datetime.fromtimestamp(t0):%Y%m%d_%H%M}"
    out = settings.reports_dir / (name + ".tmp")
    out.mkdir(parents=True, exist_ok=True)
    write_video(frames, A, out / "video.webm")
    meta = write_report(info, frames, A, out)
    tl = timeline([f["t"] for f in frames], A["segments"], A["cycles"], A["names"])
    (out / "timeline.json").write_text(json.dumps(tl, separators=(",", ":")), encoding="utf-8")
    data = {k: v for k, v in A.items() if k != "pos"}
    (out / "data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    final = settings.reports_dir / name
    publish(out, final)
    log.info("camera %s: report %s (%d cycles, median %.1fs)", camera_id, name, len(cycles), A["median"])
    return final


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(settings.data_dir / "report_gen.log", encoding="utf-8"), logging.StreamHandler()])
    cv2.setNumThreads(1)
    started = time.time()
    try:
        res = generate(int(sys.argv[1]))
    except Exception:
        log.exception("report for camera %s failed", sys.argv[1])
        sys.exit(2)
    log.info("done in %.0fs -> %s", time.time() - started, res)
    sys.exit(0 if res else 1)
