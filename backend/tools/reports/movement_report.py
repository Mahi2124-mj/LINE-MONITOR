"""Movement report of the YRA line for one shift: per operator, how much more he moves than in his own best cycles
(hands and walking), where he walks (a map on the camera picture), unusual actions with video, and a summary.

Data: the recorded pose of every frame (person boxes + wrists) and the cycles of the validated step detectors (database,
source "detector"). Each operator is picked out of the people in a frame with the same rules his step detectors use
(see OPERATORS). Nothing is calibrated to metres: movement is measured in the operator's own body heights on the picture
and compared with his own best cycles of the same shift (the same part variant), so camera angle and distance cancel out.

Checked on the video (19 and 21 Oct, camera 13): a visitor or helper standing in an operator's place can be taken for
him, so a frame counts only when the person followed looks like the operator usually does in this shift (upper-body
colour) and nobody else stands right beside him; cycles where that is not sure are not measured. Wrists hidden behind
the body (seen from the back) are guessed by the pose model, so only the wrists the camera sees clearly for an operator
are used, and idle hands only when both are seen.

usage: movement_report.py <t0 epoch> <t1 epoch> <out_dir> [--title TEXT] [--only "Op 1,Op 2"] [--detect] [--recordings DIR]
  --detect      run the step detectors on the recording instead of reading the stored cycles (saved recordings)
  --recordings  read the recording from this folder (e.g. data/validation_recordings)
writes <out_dir>/report.json, map_cam<N>.jpg and clip_<n>.webm"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics as stat
import sys
import time
import warnings
from array import array
from collections import Counter
from datetime import datetime
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # backend
sys.path.insert(0, str(HERE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.config import settings  # noqa: E402
from app.vision.recorder import list_segments  # noqa: E402

# Each operator: his camera, his steps (station ids), the step whose cycles are his loop (the step detector that sees his
# whole loop), and the rule that picks him among the people of a frame (from station_breakup.py: the same thresholds).
# cost: how the nearest candidate to his last place is found; first: whom to take when there is no last place.
# variant: cycles of different parts are compared only with the best cycles of the same part.
# colours: the dataviz reference palette (dark), checked on the page's panel #111419; the people of one camera
# (13: Op 5-7, 18: Op 3-4) get hues that stay apart for colour-blind viewers in every pair.
OPERATORS = (
    {"name": "Op 1", "cam": 8, "stations": (8, 14, 15), "main": 14, "key": "yhs", "color": "#9085e9",
     "rule": lambda cx, top, bot, h, w: 0.25 <= cx <= 0.85 and h > 0.30, "cost": "top", "first": "tallest"},
    {"name": "Op 2", "cam": 9, "stations": (9, 10), "main": 9, "key": "yg1", "color": "#008300",
     "rule": lambda cx, top, bot, h, w: 0.28 <= cx <= 0.80 and top < 0.40, "cost": "top", "first": "tallest"},
    {"name": "Op 3", "cam": 18, "stations": (18, 17), "main": 18, "key": "ylr", "color": "#c98500",
     "rule": lambda cx, top, bot, h, w: (bot > 0.85 and h > 0.40 and 0.20 < cx < 0.80) or (bot > 0.95 and h > 0.18 and cx < 0.56),
     "cost": "bottom", "first": "tallest"},
    {"name": "Op 4", "cam": 18, "stations": (19,), "main": 19, "key": "ysf", "color": "#d55181",
     "rule": lambda cx, top, bot, h, w: 0.55 < bot < 0.85 and top < 0.30 and 0.66 < cx < 0.88, "cost": "fixed", "home": 0.78},
    {"name": "Op 5", "cam": 13, "stations": (13,), "main": 13, "key": "yml", "color": "#3987e5",
     "rule": lambda cx, top, bot, h, w: cx < 0.33 and top < 0.45 and h > 0.35, "cost": "cx", "home": 0.22},
    {"name": "Op 6", "cam": 13, "stations": (20,), "main": 20, "key": "ymm", "color": "#d95926",
     "rule": lambda cx, top, bot, h, w: 0.33 <= cx <= 0.53 and top < 0.40 and h > 0.40, "cost": "cx", "home": 0.43},
    {"name": "Op 7", "cam": 13, "stations": (11, 21), "main": 21, "key": "yfi", "color": "#199e70",
     "rule": lambda cx, top, bot, h, w: 0.50 < cx < 0.76 and bot > 0.62 and w > 0.06, "cost": "cx", "first": "lowest",
     # inner rails get the pop rivet (step 11: stored as a cycle of station 11 with the same times), outer rails do not
     "variant": ("inner rail", "outer rail"), "variant_station": 11},
)
TICK = 0.5            # the tracks are compared on a 2 per second grid, so a camera's frame rate does not change the numbers
NEAR = 0.3            # a grid tick uses the nearest frame at most this far away
MAX_FRAME_GAP = 0.6   # cycles whose frames are further apart than this (median) are not measured (too few frames)
WRIST_CONF = 0.4      # a wrist position is used when the pose model is at least this sure
WRIST_SEEN = 0.5      # an operator's wrist is used at all when it is clearly seen (conf >= 0.5) in at least half his frames
WRIST_JUMP = 0.8      # a wrist moving more than this many body heights in half a second is a wrong keypoint, not a move
WALK_V = 0.30         # body heights per second: the body point (hips) moves faster than this = walking
HIP_CONF = 0.4        # the hips are used as his body point when the pose model is this sure of both
HIPS_SEEN = 0.6       # ... in at least this share of his frames (else the box)
TRIP_MIN = 0.35       # a walk counts as a trip when it moves the body at least this far (body heights)
IDLE_V = 0.08         # both wrists slower than this (body heights per second) = hands idle
SAME_DE = 25.0        # upper-body colour this far (CIE Lab) from his usual = someone else is followed
NEIGHBOUR = 0.10      # another person who fits his rule this close (share of the picture width) = not sure who is who,
REGULAR = 0.30        # unless somebody stands that close in more than this share of the shift (a colleague, not a visitor)
SAME_MIN = 0.85       # a cycle is measured when the operator is surely followed in this share of the frames he is found
BEST_SHARE = 0.25     # the best cycles = the fastest quarter of the measured normal cycles (per part variant)
MIN_BEST = 5
# unusual actions
AWAY_SEC = 10         # out of his work area this long inside a cycle
IDLE_SEC = 8          # hands idle this long inside a cycle, outside machine / wait elements
HAND_X = 1.5          # hand travel this many times his best cycles' ...
EXTRA_MIN = 0.15      # ... in a cycle at least this much (share of his best cycle time) longer
TRIPS_X = 2           # this many more trips than in his best cycles
WALK_X = 3.0          # or this many more seconds walking
CLIPS_WORST = 5
CLIPS_PER_TYPE = 3
CLIP_FPS = 6
CLIP_W = 480
CLIP_MAX = 60.0


def say(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def bgr(hexc: str) -> tuple[int, int, int]:
    return tuple(int(hexc[i:i + 2], 16) for i in (5, 3, 1))


# ------------------------------------------------------------------ reading the recording
class Track:
    """one operator's place per recorded frame: found, box (x0, top, x1, bottom), wrists (x, y, conf) x 2, how far (box
    centres, share of the picture width) the nearest other person that fits his rule is, and the middle of his hips (x, y,
    conf): his body place (the box bottom jumps when the legs are hidden or he bends: no walking)"""
    COLS = 15

    def __init__(self, op: dict):
        self.op = op
        self.rows = array("f")
        self.last: tuple[float, float, float] | None = None  # cx, top, bottom

    def add(self, persons: list[dict]) -> None:
        op, best, bc, fits = self.op, None, 1e9, []
        for p in persons:
            b = p.get("b")
            if not b:
                continue
            cx, top, bot, h, w = (b[0] + b[2]) / 2, b[1], b[3], b[3] - b[1], b[2] - b[0]
            if not op["rule"](cx, top, bot, h, w):
                continue
            fits.append(cx)
            if op["cost"] == "fixed":
                c = abs(cx - op["home"])
            elif self.last is None:
                c = abs(cx - op["home"]) if "home" in op else (-bot if op.get("first") == "lowest" else -h)
            elif op["cost"] == "top":
                c = abs(cx - self.last[0]) + 0.5 * abs(top - self.last[1])
            elif op["cost"] == "bottom":
                c = abs(cx - self.last[0]) + 0.5 * abs(bot - self.last[2])
            else:
                c = abs(cx - self.last[0])
            if c < bc:
                best, bc = p, c
        if best is None:
            self.rows.extend((0.0,) * self.COLS)
            return
        b, k = best["b"], best.get("k") or []
        cx = (b[0] + b[2]) / 2
        self.last = (cx, b[1], b[3])
        wr = []
        for i in (9, 10):
            q = k[i] if len(k) > i and k[i] else None
            wr += [q[0], q[1], q[2]] if q and len(q) > 2 else [0.0, 0.0, 0.0]
        others = [abs(x - cx) for x in fits if abs(x - cx) > 1e-6]
        hips = [k[i] for i in (11, 12) if len(k) > i and k[i] and len(k[i]) > 2]
        hip = ((hips[0][0] + hips[1][0]) / 2, (hips[0][1] + hips[1][1]) / 2, min(hips[0][2], hips[1][2])) if len(hips) == 2 else (0.0, 0.0, 0.0)
        self.rows.extend((1.0, b[0], b[1], b[2], b[3], *wr, min(others, default=9.0), *hip))

    def array(self) -> np.ndarray:
        return np.frombuffer(self.rows, dtype=np.float32).reshape(-1, self.COLS)


class Camera:
    """the frames of one camera in [t0, t1] (time, file, offset, length) and the tracks of its operators"""

    def __init__(self, cam: int, ops: list[dict], t0: float, t1: float):
        self.cam, self.files = cam, []
        T, FI, O, N = array("d"), array("i"), array("q"), array("i")
        tracks = [Track(op) for op in ops]
        for _, jpath in list_segments(cam, t0 - 70, t1):
            mpath = jpath.with_suffix(".mjpg")
            if not mpath.exists():
                continue
            fi = len(self.files)
            self.files.append(mpath)
            with open(jpath, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        break
                    t = r.get("t")
                    if t is None or not (t0 <= t <= t1) or "o" not in r:
                        continue
                    T.append(t); FI.append(fi); O.append(r["o"]); N.append(r["n"])
                    ps = r.get("p") or []
                    for tr in tracks:
                        tr.add(ps)
        self.T = np.frombuffer(T, dtype=np.float64)
        order = np.argsort(self.T, kind="stable")
        self.T = self.T[order]
        self.FI = np.frombuffer(FI, dtype=np.int32)[order]
        self.O = np.frombuffer(O, dtype=np.int64)[order]
        self.N = np.frombuffer(N, dtype=np.int32)[order]
        self.tracks = {tr.op["name"]: tr.array()[order] if len(self.T) else np.zeros((0, Track.COLS), np.float32) for tr in tracks}

    def frame(self, i: int, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
        with open(self.files[self.FI[i]], "rb") as f:
            f.seek(int(self.O[i]))
            data = f.read(int(self.N[i]))
        return cv2.imdecode(np.frombuffer(data, np.uint8), flags) if len(data) == self.N[i] else None

    def torso_lab(self, idx: np.ndarray, names: list[str]) -> dict[str, np.ndarray]:
        """per grid tick and operator: the mean colour (CIE Lab) of the upper body of the person followed (NaN: none)"""
        out = {n: np.full((len(idx), 3), np.nan, np.float32) for n in names}
        for k, i in enumerate(idx):
            if i < 0 or not any(self.tracks[n][i, 0] > 0.5 for n in names):
                continue
            img = self.frame(int(i), cv2.IMREAD_REDUCED_COLOR_4)  # a quarter of the size: fast, enough for a shirt
            if img is None:
                continue
            h, w = img.shape[:2]
            for n in names:
                r = self.tracks[n][i]
                if r[0] < 0.5:
                    continue
                bw, bh = r[3] - r[1], r[4] - r[2]
                x0, x1 = int((r[1] + 0.3 * bw) * w), int((r[3] - 0.3 * bw) * w)
                y0, y1 = int((r[2] + 0.18 * bh) * h), int((r[2] + 0.42 * bh) * h)
                patch = img[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
                if patch.size:
                    out[n][k] = patch.reshape(-1, 3).mean(axis=0)
        for n in names:
            ok = ~np.isnan(out[n][:, 0])
            if ok.any():
                lab = cv2.cvtColor((out[n][ok] / 255.0).reshape(-1, 1, 3).astype(np.float32), cv2.COLOR_BGR2LAB).reshape(-1, 3)
                out[n][ok] = lab
        return out


# ------------------------------------------------------------------ movement on the 2-per-second grid
class Motion:
    """an operator's movement on the TICK grid of [t0, t1]: body point, hand and body speeds in body heights"""

    def __init__(self, cam: Camera, name: str, t0: float, t1: float):
        self.g = np.arange(t0, t1, TICK)
        self.frame_t = cam.T
        T, tr, n = cam.T, cam.tracks[name], len(self.g)
        self.has_frame = np.zeros(n, bool)
        self.idx = np.full(n, -1, np.int64)
        if len(T):
            j = np.clip(np.searchsorted(T, self.g), 1, len(T) - 1) if len(T) > 1 else np.zeros(n, np.int64)
            jl = np.where(np.abs(T[j - 1] - self.g) <= np.abs(T[j] - self.g), j - 1, j) if len(T) > 1 else j
            self.has_frame = np.abs(T[jl] - self.g) <= NEAR
            self.idx = np.where(self.has_frame, jl, -1)
        self.rows = tr[np.maximum(self.idx, 0)] if len(T) else np.zeros((n, Track.COLS), np.float32)
        self.found = self.has_frame & (self.rows[:, 0] > 0.5)
        self.same = self.found.copy()
        self.regular_neighbour = False
        self.hips = False
        self.H = float(np.median((self.rows[self.found, 4] - self.rows[self.found, 2]) * 9.0)) if self.found.any() else 1.0
        self.wrists: list[int] = []

    def finish(self, lab: np.ndarray) -> None:
        """who is surely the operator (looks like himself, nobody right beside him), then his movement"""
        rows, found = self.rows, self.found
        if found.sum() >= 10:
            usual = np.nanmedian(lab[found], axis=0)
            de = np.linalg.norm(lab - usual, axis=1)
            near = found & (rows[:, 11] < NEIGHBOUR)
            # a colleague who stands beside him most of the shift (camera 18: the person right of Op 4) is no visitor:
            # then he is followed by his place and his colour only
            self.regular_neighbour = bool(near.sum() > REGULAR * found.sum())
            self.same = found & (np.nan_to_num(de, nan=0.0) <= SAME_DE) & (~near | self.regular_neighbour)
        sure = self.same
        self.H = float(np.median((rows[sure, 4] - rows[sure, 2]) * 9.0)) if sure.any() else self.H
        # body point: the middle of his hips when the camera sees them in most frames (frames without them are left out),
        # else a point inside the box at hip height; one source per operator (switching would jump); smoothed over 3 ticks
        hip = rows[:, 14] >= HIP_CONF
        self.hips = bool(sure.any() and hip[sure].mean() >= HIPS_SEEN)
        if self.hips:
            x = np.where(sure & hip, rows[:, 12] * 16.0, np.nan)
            y = np.where(sure & hip, rows[:, 13] * 9.0, np.nan)
        else:
            x = np.where(sure, (rows[:, 1] + rows[:, 3]) / 2 * 16.0, np.nan)
            y = np.where(sure, (rows[:, 2] + 0.55 * (rows[:, 4] - rows[:, 2])) * 9.0, np.nan)
        self.bx, self.by = _median3(x), _median3(y)
        self.body_step = np.concatenate([[np.nan], np.hypot(np.diff(self.bx), np.diff(self.by)) / self.H])
        self.walking = sure & (np.nan_to_num(self.body_step) / TICK > WALK_V)
        # the wrists the camera sees clearly for him
        self.wrists = [c for c in (5, 8) if sure.any() and np.mean(rows[sure, c + 2] >= 0.5) >= WRIST_SEEN]
        steps = []
        for c in self.wrists:
            ok = sure & (rows[:, c + 2] >= WRIST_CONF)
            wx = np.where(ok, rows[:, c] * 16.0, np.nan)
            wy = np.where(ok, rows[:, c + 1] * 9.0, np.nan)
            s = np.hypot(np.diff(wx), np.diff(wy)) / self.H
            steps.append(np.concatenate([[np.nan], np.where(s > WRIST_JUMP, np.nan, s)]))
        if steps:
            st = np.vstack(steps)
            self.hand_step = np.nansum(st, axis=0)
            self.hand_ok = ~np.isnan(st).all(axis=0)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                fastest = np.nanmax(st, axis=0)
            self.idle = sure & ~np.isnan(st).any(axis=0) & (np.nan_to_num(fastest, nan=1.0) / TICK < IDLE_V) \
                if len(self.wrists) == 2 else np.zeros(len(self.g), bool)
        else:
            self.hand_step = np.zeros(len(self.g))
            self.hand_ok = np.zeros(len(self.g), bool)
            self.idle = np.zeros(len(self.g), bool)

    def span(self, a: float, b: float) -> slice:
        i0 = int(min(len(self.g), max(0, math.ceil((a - self.g[0]) / TICK))))
        i1 = int(max(i0, min(len(self.g), math.floor((b - self.g[0]) / TICK) + 1)))
        return slice(i0, i1)


def _median3(v: np.ndarray) -> np.ndarray:
    """median of each tick and its two neighbours (a missing neighbour is left out; a missing tick stays missing)"""
    out = v.copy()
    if len(v) >= 3:
        st = np.vstack([v[:-2], v[1:-1], v[2:]])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-missing columns
            out[1:-1] = np.where(np.isnan(v[1:-1]), np.nan, np.nanmedian(st, axis=0))
    return out


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """(start, end) index pairs of the True runs (end exclusive)"""
    if not len(mask):
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


# ------------------------------------------------------------------ cycles
def _db():
    return sqlite3.connect(f"file:{settings.data_dir / 'line_monitor.db'}?mode=ro", uri=True)


def db_cycles(t0: float, t1: float, stations: set[int]) -> dict[int, list[dict]]:
    db = _db()
    out: dict[int, list[dict]] = {s: [] for s in stations}
    for sid, a, b, sec, el in db.execute(
            "select station_id, started_at, ended_at, cycle_sec, elements from cycles where source='detector' and started_at >= ? "
            "and started_at < ? order by started_at", (datetime.fromtimestamp(t0).isoformat(" "), datetime.fromtimestamp(t1).isoformat(" "))):
        if sid not in out:
            continue
        e = json.loads(el) if el else {}
        out[sid].append({"start": datetime.fromisoformat(a).timestamp(), "end": datetime.fromisoformat(b).timestamp(), "sec": sec,
                         "el": e.get("el") or {}, "seg": e.get("seg") or []})
    db.close()
    return out


def detected_cycles(key: str, t0: float, t1: float) -> list[dict]:
    import detector_feed as tool  # tools/reports/detector_feed.py: the same cycles the live feed stores

    return tool.cycles_of(key, t0, t1)


def station_info() -> dict[int, dict]:
    db = _db()
    out = {sid: {"id": sid, "sequence": seq, "name": name} for sid, seq, name in db.execute("select id, sequence, name from stations")}
    db.close()
    return out


def element_info() -> tuple[dict, dict]:
    try:
        meta = json.loads((settings.data_dir / "detector_elements.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    try:
        from detector_feed import KINDS
    except Exception:  # noqa: BLE001
        KINDS = {}
    return meta, KINDS


# ------------------------------------------------------------------ per cycle
def measure(c: dict, m: Motion, kinds: dict) -> dict:
    s = m.span(c["start"], c["end"])
    has, found, same = m.has_frame[s], m.found[s], m.same[s]
    ft = m.frame_t[(m.frame_t >= c["start"]) & (m.frame_t <= c["end"])]
    gap = float(np.median(np.diff(ft))) if len(ft) > 2 else 99.0
    out = {"frames": float(has.mean()) if len(has) else 0.0, "found": float(found.sum() / max(1, has.sum())),
           "sure": float(same.sum() / max(1, found.sum())), "gap": gap}
    out["measured"] = bool(out["frames"] >= 0.9 and out["found"] >= 0.8 and out["sure"] >= SAME_MIN and gap <= MAX_FRAME_GAP)
    # his own work: not the machine / wait elements of the cycle (hands moving while he waits for a part are no handling)
    busy = np.ones(s.stop - s.start, bool)
    for code, off, dur in c.get("seg") or []:
        if kinds.get(code) in ("machine", "wait") and len(busy):
            i0 = max(0, int((c["start"] + off - m.g[s.start]) / TICK))
            i1 = min(len(busy), int(math.ceil((c["start"] + off + dur - m.g[s.start]) / TICK)))
            busy[i0:i1] = False
    out["hand"] = float(np.nansum(np.where(m.hand_ok[s] & busy, m.hand_step[s], 0.0))) if m.wrists else None
    walk = m.walking[s]
    out["walk_sec"] = float(walk.sum() * TICK)
    bs = np.nan_to_num(m.body_step[s])
    out["trips"] = sum(1 for a, b in _runs(walk) if b - a >= 2 and bs[a:b].sum() >= TRIP_MIN)
    out["idle_sec"] = float(max((b - a for a, b in _runs(m.idle[s] & busy)), default=0) * TICK)
    away = max(_runs(has & ~found), key=lambda ab: ab[1] - ab[0], default=None)
    out["away_sec"] = float((away[1] - away[0]) * TICK) if away else 0.0
    return out


def _cause(c: dict, ref: dict, ref_el: dict, kinds: dict, hands: bool) -> tuple[str, str | None]:
    """why a cycle took longer than his best ones: the kind of element that grew (the step detectors' elements), and for
    hand work whether his hands moved more"""
    grow: dict[str, float] = {}
    where: dict[str, tuple[float, str]] = {}
    for code in set(c["el"]) | set(ref_el):
        d = c["el"].get(code, 0.0) - ref_el.get(code, 0.0)
        if d <= 0:
            continue
        k = kinds.get(code, "work")
        grow[k] = grow.get(k, 0.0) + d
        if d > where.get(k, (0.0, ""))[0]:
            where[k] = (d, code)
    total = sum(grow.values())
    if total <= 0:
        return "slower", None
    top = max(grow, key=grow.get)
    code = where[top][1]
    if top == "wait":
        return "waiting", code
    if top == "machine":
        return "machine", code
    if top == "motion" or c["walk_sec"] - ref["walk_sec"] >= 0.5 * c["extra"] or c["trips"] >= ref["trips"] + TRIPS_X:
        return "walking", where.get("motion", (0, code))[1]
    if hands and c.get("hand_x") is not None and c["hand_x"] >= 1.25:
        return "movement", code
    if c["idle_sec"] >= 0.5 * c["extra"]:
        return "idle", code
    return "slower", code


def analyse_operator(op: dict, cycles: list[dict], m: Motion, labels: dict, kinds: dict) -> dict:
    secs = [c["sec"] for c in cycles]
    med = stat.median(secs) if secs else 0.0
    stop_at = max(45.0, 3 * med)
    for c in cycles:
        c["variant"] = (op["variant"][0] if c.get("twin") else op["variant"][1]) if op.get("variant") else ""
        c["stop"] = c["sec"] > stop_at
        c.update(measure(c, m, kinds))
    hands = bool(m.wrists)
    res = {"name": op["name"], "camera": op["cam"], "color": op["color"], "cycles": len(cycles), "median_sec": round(med, 2),
           "hands_seen": ["left" if c == 5 else "right" for c in m.wrists]}
    refs: dict[str, dict] = {}
    for v in sorted({c["variant"] for c in cycles}):
        vc = [c for c in cycles if c["variant"] == v and not c["stop"]]
        vmed = stat.median(c["sec"] for c in vc) if vc else 0.0
        for c in vc:
            c["normal"] = c["sec"] <= 1.5 * vmed
        good = [c for c in vc if c["normal"] and c["measured"]]
        if len(good) < MIN_BEST:
            continue
        best = sorted(good, key=lambda c: c["sec"])[:max(MIN_BEST, int(len(good) * BEST_SHARE))]
        ref = {"sec": stat.median(c["sec"] for c in best), "walk_sec": stat.median(c["walk_sec"] for c in best),
               "trips": stat.median(c["trips"] for c in best), "cycles": len(best), "of": len(good)}
        ref["hand"] = stat.median(c["hand"] for c in best) if hands else None
        ref["el"] = {code: stat.median(c["el"].get(code, 0.0) for c in best) for code in {k for c in best for k in c["el"]}}
        refs[v] = ref
    for c in cycles:
        c.setdefault("normal", False)
        c["compared"] = c["variant"] in refs and c["normal"]
    good = [c for c in cycles if c["compared"] and c["measured"]]
    res["measured"] = len(good)
    if not refs:
        res["note"] = "Too few measured cycles to compare (camera offline, operator not visible, someone else in his place, or line stopped)."
        res["series"] = [[round(c["end"], 1), round(c["sec"], 2), "stop" if c["stop"] else "", "", "stop" if c["stop"] else ""] for c in cycles]
        res["_cycles"], res["_events"] = cycles, []
        return res
    causes = {k: 0.0 for k in CAUSE_TEXT}
    where_by_cause: dict[str, Counter] = {k: Counter() for k in causes}
    events = []
    for c in cycles:
        ref = refs.get(c["variant"])
        c["extra"] = max(0.0, c["sec"] - ref["sec"]) if c["compared"] else 0.0
        c["hand_x"] = c["hand"] / ref["hand"] if hands and c["measured"] and ref and ref["hand"] else None
        c["cause"], c["where"] = ("stop", None) if c["stop"] else ("", None)
        # for the cycle chart: like his best / slower / long (interrupted, over 1.5x the median) / line stop
        slow = c["compared"] and c["extra"] > max(1.5, 0.10 * ref["sec"])
        c["band"] = "stop" if c["stop"] else "long" if not c["normal"] else ("slower" if slow else "best") if c["compared"] else ""
        if slow and c["measured"]:
            c["cause"], c["where"] = _cause(c, ref, ref["el"], kinds, hands)
            causes[c["cause"]] += c["extra"]
            if c["where"]:
                where_by_cause[c["cause"]][c["where"]] += c["extra"]
        # unusual actions (only where the operator is surely followed)
        if c["stop"] or c["frames"] < 0.9:
            continue
        if c["away_sec"] >= AWAY_SEC:
            events.append({"type": "away", "start": c["start"], "end": c["end"], "value": c["away_sec"],
                           "text": f"Not at his work place for {c['away_sec']:.0f} s during the cycle"})
        if not (c["measured"] and c["compared"]):
            continue
        if c["cause"] == "movement" and c["hand_x"] >= HAND_X and c["extra"] >= max(2.0, EXTRA_MIN * ref["sec"]):
            events.append({"type": "handling", "start": c["start"], "end": c["end"], "value": c["hand_x"],
                           "text": f"Hands moved {c['hand_x']:.1f}x as much as in his best cycles, cycle {c['sec']:.1f} s "
                                   f"(best {ref['sec']:.1f} s): re-fixing, double handling or searching?"})
        if c["trips"] >= ref["trips"] + TRIPS_X or c["walk_sec"] >= ref["walk_sec"] + WALK_X:
            events.append({"type": "walking", "start": c["start"], "end": c["end"], "value": c["walk_sec"] - ref["walk_sec"],
                           "text": f"{c['trips']} trips, {c['walk_sec']:.1f} s walking (best cycles: {ref['trips']:.0f} trips, "
                                   f"{ref['walk_sec']:.1f} s)"})
        if c["idle_sec"] >= IDLE_SEC:
            events.append({"type": "idle", "start": c["start"], "end": c["end"], "value": c["idle_sec"],
                           "text": f"Hands idle for {c['idle_sec']:.0f} s (not at a machine or a planned wait)"})
    comp = [c for c in cycles if c["compared"]]
    slow = [c for c in good if c["cause"] in causes]
    label = lambda code: (labels.get(code) or [code])[0]  # noqa: E731
    per_el: dict[str, list[tuple[float, float]]] = {}
    for c in good:
        ref = refs[c["variant"]]
        for code in set(c["el"]) | set(ref["el"]):
            per_el.setdefault(code, []).append((c["el"].get(code, 0.0), ref["el"].get(code, 0.0)))
    res.update({
        "variants": {v: {"ref_sec": round(r["sec"], 2), "best_cycles": r["cycles"], "of": r["of"]} for v, r in refs.items() if v},
        "ref": {"sec": round(stat.median(refs[c["variant"]]["sec"] for c in good), 2) if good else None,
                "walk_sec": round(stat.median(refs[c["variant"]]["walk_sec"] for c in good), 2) if good else None,
                "trips": round(stat.median(refs[c["variant"]]["trips"] for c in good), 1) if good else None,
                "hand": round(stat.median(refs[c["variant"]]["hand"] for c in good), 2) if good and hands else None,
                "cycles": sum(r["cycles"] for r in refs.values())},
        "avg_sec": round(stat.mean(c["sec"] for c in comp), 2) if comp else None,
        "extra_avg": round(stat.mean(c["extra"] for c in good), 2) if good else 0.0,
        "extra_share": round(len(slow) / len(good), 3) if good else 0.0,
        "extra_min": round(sum(c["extra"] for c in comp) / 60, 1),
        "hand_index": round(stat.mean(c["hand_x"] for c in good if c["hand_x"] is not None), 2)
        if hands and any(c["hand_x"] is not None for c in good) else None,
        "hand_more_share": round(sum(1 for c in good if (c["hand_x"] or 0) >= 1.25) / len(good), 3) if hands and good else None,
        "walk_avg": round(stat.mean(c["walk_sec"] for c in good), 2) if good else None,
        "trips_avg": round(stat.mean(c["trips"] for c in good), 2) if good else None,
        "stops": sum(1 for c in cycles if c["stop"]),
        "stop_min": round(sum(c["sec"] - med for c in cycles if c["stop"]) / 60, 1),
        "variation_cv": round(stat.pstdev(c["sec"] for c in comp) / stat.mean(c["sec"] for c in comp), 3) if len(comp) > 2 else None,
        "causes": {k: round(v / 60, 1) for k, v in causes.items()},
        "causes_where": {k: label(w.most_common(1)[0][0]) for k, w in where_by_cause.items() if w},
        "elements": sorted(({"code": code, "label": label(code), "kind": kinds.get(code, "work"),
                             "avg": round(stat.mean(a for a, _ in v), 2), "ref": round(stat.mean(b for _, b in v), 2),
                             "extra": round(stat.mean(a - b for a, b in v), 2)} for code, v in per_el.items()),
                           key=lambda e: -e["extra"]),
        "series": [[round(c["end"], 1), round(c["sec"], 2), c["cause"], c["variant"], c["band"]] for c in cycles],
        "_cycles": cycles, "_events": events, "_refs": refs,
    })
    return res


# ------------------------------------------------------------------ pictures and clips
def walking_map(cam: Camera, motions: dict[str, Motion], ops: list[dict], path: Path) -> bool:
    """the camera picture without people (median of frames over the shift) and each operator's body path on it"""
    if len(cam.T) < 20:
        return False
    imgs = [im for im in (cam.frame(int(i)) for i in np.linspace(0, len(cam.T) - 1, 15).astype(int)) if im is not None]
    if not imgs:
        return False
    bg = np.median(np.stack(imgs), axis=0).astype(np.uint8)
    h, w = bg.shape[:2]
    out = bg.astype(np.float32) * 0.55
    for op in ops:
        m = motions.get(op["name"])
        if m is None:
            continue
        col = np.array(bgr(op["color"]), np.float32)
        px, py = m.bx / 16.0 * w, m.by / 9.0 * h
        ok = ~np.isnan(px) & ~np.isnan(py)
        # where he stands: a soft heat of his body point (brighter = longer there)
        heat = np.zeros((h, w), np.float32)
        np.add.at(heat, (np.clip(py[ok].astype(int), 0, h - 1), np.clip(px[ok].astype(int), 0, w - 1)), 1.0)
        heat = cv2.GaussianBlur(heat, (0, 0), 6)
        if heat.max() > 0:
            a = (np.clip(heat / np.percentile(heat[heat > 0], 99), 0, 1) ** 0.6)[..., None] * 0.55
            out = out * (1 - a) + col * a
        # where he walks: each step of a walk as a line (body moving faster than WALK_V)
        walk = np.zeros((h, w), np.float32)
        for i in np.flatnonzero(ok[1:] & ok[:-1] & m.walking[1:]) + 1:
            cv2.line(walk, (int(px[i - 1]), int(py[i - 1])), (int(px[i]), int(py[i])), 1.0, 2, cv2.LINE_AA)
        if walk.max() > 0:
            a = (np.clip(walk, 0, 3) / 3 * 0.6 + (walk > 0) * 0.35)[..., None]
            out = out * (1 - a) + col * a
    out = np.clip(out, 0, 255).astype(np.uint8)
    y = 10
    for op in ops:
        cv2.rectangle(out, (10, y), (26, y + 14), bgr(op["color"]), -1)
        cv2.putText(out, op["name"], (32, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        y += 20
    out = cv2.resize(out, (960, int(960 * h / w)))
    return bool(cv2.imwrite(str(path), out, [cv2.IMWRITE_JPEG_QUALITY, 85]))


def clip(cam: Camera, op: dict, a: float, b: float, text: str, path: Path, wide: bool = False) -> bool:
    """the cycle (1 s before and after) in real time, the operator's box and wrists drawn, at CLIP_W pixels wide: the
    part of the picture around him (wide: the whole picture, for walking and leaving his place)"""
    a, b = a - 1.0, min(b + 1.0, a - 1.0 + CLIP_MAX)
    sel = np.flatnonzero((cam.T >= a) & (cam.T <= b))
    if len(sel) < 3:
        return False
    first = cam.frame(int(sel[0]))
    if first is None:
        return False
    h0, w0 = first.shape[:2]
    w, h = CLIP_W, int(round(CLIP_W * h0 / w0 / 2)) * 2
    tr, col = cam.tracks[op["name"]], bgr(op["color"])
    rows = tr[sel][tr[sel][:, 0] > 0.5]
    x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
    if not wide and len(rows):
        bx0, by0 = np.percentile(rows[:, 1], 5), np.percentile(rows[:, 2], 5)
        bx1, by1 = np.percentile(rows[:, 3], 95), np.percentile(rows[:, 4], 95)
        half = min(0.5, max(0.22, (bx1 - bx0) / 2 * 1.5, (by1 - by0) / 2 * 1.25))  # same share of width and height: 16:9 stays
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        x0, y0 = min(max(0.0, cx - half), 1 - 2 * half), min(max(0.0, cy - half), 1 - 2 * half)
        x1, y1 = x0 + 2 * half, y0 + 2 * half
    X0, Y0, X1, Y1 = int(x0 * w0), int(y0 * h0), int(x1 * w0), int(y1 * h0)
    px = lambda v: int((v - x0) / (x1 - x0) * w)  # noqa: E731
    py = lambda v: int((v - y0) / (y1 - y0) * h)  # noqa: E731
    tmp = path.with_suffix(".tmp.webm")
    vw = cv2.VideoWriter(str(tmp), cv2.CAP_FFMPEG, cv2.VideoWriter_fourcc(*"VP80"), CLIP_FPS, (w, h))
    if not vw.isOpened():
        return False
    k, cache = 0, {}
    for n in range(int((b - a) * CLIP_FPS) + 1):
        t = a + n / CLIP_FPS
        while k + 1 < len(sel) and cam.T[sel[k + 1]] <= t:
            k += 1
        i = int(sel[k])
        if i not in cache:
            img = cam.frame(i)
            cache = {i: cv2.resize(img[Y0:Y1, X0:X1], (w, h), interpolation=cv2.INTER_AREA) if img is not None else None}
        if cache[i] is None:
            continue
        img = cache[i].copy()
        r = tr[i]
        if r[0] > 0.5:
            cv2.rectangle(img, (px(r[1]), py(r[2])), (px(r[3]), py(r[4])), col, 2)
            for c in (5, 8):
                if r[c + 2] >= WRIST_CONF:
                    cv2.circle(img, (px(r[c]), py(r[c + 1])), 6, (0, 255, 255), 2, cv2.LINE_AA)
        cv2.rectangle(img, (0, 0), (w, 20), (0, 0, 0), -1)
        cv2.putText(img, f"{datetime.fromtimestamp(t):%H:%M:%S}  {op['name']}  {t - a - 1.0:5.1f}s", (5, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.rectangle(img, (0, h - 18), (w, h), (0, 0, 0), -1)
        cv2.putText(img, text.split(": re-")[0][:72], (5, h - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.36, col, 1, cv2.LINE_AA)
        vw.write(img)
    vw.release()
    tmp.replace(path)
    return True


# ------------------------------------------------------------------ summary texts
CAUSE_TEXT = {"movement": "extra hand movement", "walking": "extra walking", "waiting": "waiting for a part or a person",
              "idle": "idle hands", "machine": "machine slower", "slower": "same movement, slower pace"}
OWN = ("movement", "walking", "idle", "slower")  # the causes in the operator's own hands (not upstream, not the machine)
MAX_SUGGESTIONS, PER_OPERATOR = 8, 2


def top_causes(ops: list[dict]) -> list[dict]:
    rows = []
    for o in ops:
        for cause, mins in (o.get("causes") or {}).items():
            if mins <= 0:
                continue
            cyc = [c for c in o["_cycles"] if c["cause"] == cause]
            where = (o.get("causes_where") or {}).get(cause)
            rows.append({"operator": o["name"], "cause": cause, "minutes": mins, "cycles": len(cyc),
                         "per_cycle": round(stat.mean(c["extra"] for c in cyc), 1) if cyc else 0.0, "where": where,
                         "text": f"{o['name']}: {CAUSE_TEXT[cause]} in {len(cyc)} cycles, {mins:.1f} min this shift"
                                 + (f" (mostly in '{where}')" if where else "")})
    return sorted(rows, key=lambda r: -r["minutes"])[:3]


def suggestions(ops: list[dict]) -> list[str]:
    """what to look at first: each finding weighed by the minutes it cost this shift; at most PER_OPERATOR per operator and
    MAX_SUGGESTIONS in all"""
    found: list[tuple[float, str, str]] = []  # (minutes, operator, text)
    for o in ops:
        ref, cs = o.get("ref") or {}, o.get("causes") or {}
        if not ref or not o.get("measured"):
            continue
        name, where = o["name"], o.get("causes_where") or {}
        n = Counter(c["cause"] for c in o["_cycles"])
        ev = [e for e in o["_events"] if e["type"] == "away"]
        if cs.get("walking", 0) >= 1:
            more = (o.get("walk_avg") or 0) - (ref.get("walk_sec") or 0)
            seen = f"he walks {o['walk_avg']:.1f} s per cycle against {ref['walk_sec']:.1f} s in his best cycles" if more >= 0.5 else \
                f"'{where.get('walking', 'walking / carrying')}' takes longer than in his best cycles"
            found.append((cs["walking"], name, f"{name}: extra walking cost {cs['walking']:.1f} min in {n['walking']} cycles ({seen}). "
                                               f"See the walking map: bring the bin or rack closer, or keep the next part ready where he works."))
        if cs.get("movement", 0) >= 1:
            found.append((cs["movement"], name, f"{name}: much more hand movement than in his best cycles in {n['movement']} cycles "
                                                f"({cs['movement']:.1f} min" + (f", mostly in '{where['movement']}'" if where.get("movement") else "")
                                                + "): re-fixing, double handling or searching. Watch the clips; check how the part sits in "
                                                  "the jig and how parts are presented to him."))
        if cs.get("idle", 0) >= 1:
            found.append((cs["idle"], name, f"{name}: hands idle in {n['idle']} cycles ({cs['idle']:.1f} min), not at a machine or a planned "
                                            f"wait. Watch the clips: waiting for something, unclear work, or a pause inside the cycle."))
        if cs.get("waiting", 0) >= 1:
            found.append((cs["waiting"], name, f"{name}: waited for a part or a person in {n['waiting']} cycles ({cs['waiting']:.1f} min"
                                               + (f", '{where['waiting']}'" if where.get("waiting") else "") + "). Not his own movement: check "
                                               "the supply from the step before and the line balance."))
        if cs.get("machine", 0) >= 1:
            found.append((cs["machine"], name, f"{name}: his machine took longer than in his best cycles in {n['machine']} cycles "
                                               f"({cs['machine']:.1f} min" + (f", '{where['machine']}'" if where.get("machine") else "") + "). Check the machine."))
        if len(ev) >= 2:
            mins = sum(e["value"] for e in ev) / 60
            found.append((mins, name, f"{name}: left his work place during {len(ev)} cycles ({mins:.1f} min). Check material supply and "
                                      f"whether he is called away to help another step."))
        if (o.get("variation_cv") or 0) >= 0.15 and cs.get("slower", 0) >= 1:
            found.append((cs["slower"], name, f"{name}: same movement but slower in {n['slower']} cycles ({cs['slower']:.1f} min; cycle times "
                                              f"vary {o['variation_cv'] * 100:.0f}%). Use the video of his best cycles ({ref['sec']:.1f} s) to "
                                              f"make his method the same every cycle."))
    out, per = [], Counter()
    for mins, name, text in sorted(found, key=lambda f: -f[0]):
        if per[name] < PER_OPERATOR and len(out) < MAX_SUGGESTIONS:
            out.append(text)
            per[name] += 1
    return out


# ------------------------------------------------------------------ main
def main() -> None:
    args = sys.argv[1:]
    t0, t1, out = float(args[0]), float(args[1]), Path(args[2])

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default
    title = opt("--title", f"{datetime.fromtimestamp(t0):%d %b %H:%M}-{datetime.fromtimestamp(t1):%H:%M}")
    only = {s.strip() for s in opt("--only", "").split(",") if s.strip()}
    if opt("--recordings"):
        settings.recordings_dir = Path(opt("--recordings"))
    detect = "--detect" in args
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    ops = [o for o in OPERATORS if not only or o["name"] in only]
    sinfo = station_info()
    meta, KINDS = element_info()
    stored = {} if detect else db_cycles(t0, t1, {o["main"] for o in ops} | {o["variant_station"] for o in ops if o.get("variant_station")})
    report = {"title": title, "window": [t0, t1], "generated_at": datetime.now().isoformat(timespec="seconds"),
              "settings": {"tick": TICK, "walk_v": WALK_V, "idle_v": IDLE_V, "best_share": BEST_SHARE},
              "operators": [], "maps": [], "worst": [], "events": [], "notes": []}
    results = []
    for cam_id in sorted({o["cam"] for o in ops}):
        cops = [o for o in ops if o["cam"] == cam_id]
        cam = Camera(cam_id, cops, t0, t1)
        motions = {op["name"]: Motion(cam, op["name"], t0, t1) for op in cops}
        idx = next(iter(motions.values())).idx  # the same grid for every operator of the camera
        labs = cam.torso_lab(idx, [op["name"] for op in cops])
        say(f"camera {cam_id}: {len(cam.T)} frames")
        for op in cops:
            m = motions[op["name"]]
            m.finish(labs[op["name"]])
            cycles = detected_cycles(op["key"], t0, t1) if detect else stored.get(op["main"], [])
            if op.get("variant_station"):  # the part variant: a cycle of that station with the same times
                twins = np.array(sorted(c["start"] for c in stored.get(op["variant_station"], [])))
                for c in cycles:
                    j = int(np.searchsorted(twins, c["start"]))
                    near = [abs(twins[q] - c["start"]) for q in (j - 1, j) if 0 <= q < len(twins)]
                    c["twin"] = bool(c.get("rivet")) if detect else bool(near and min(near) < 0.5)
            r = analyse_operator(op, cycles, m, meta.get(op["key"], {}), KINDS.get(op["key"], {}))
            r["steps"] = [sinfo[s] for s in op["stations"] if s in sinfo]
            r["visible"] = round(float(m.found.sum() / max(1, m.has_frame.sum())), 3)
            r["sure"] = round(float(m.same.sum() / max(1, m.found.sum())), 3)
            r["regular_neighbour"] = m.regular_neighbour
            r["body_point"] = "hips" if m.hips else "box"
            r["_cam"], r["_op"] = cam, op
            results.append(r)
            say(f"  {op['name']}: {len(cycles)} cycles, measured {r['measured']}, visible {r['visible']:.0%}, sure {r['sure']:.0%}, "
                f"hands seen {r['hands_seen']}")
        name = f"map_cam{cam_id}.jpg"
        if walking_map(cam, motions, cops, out / name):
            report["maps"].append({"camera": cam_id, "image": name, "operators": [o["name"] for o in cops]})
    # clips: the worst cycles of the line and the biggest unusual actions of each type
    n = 0
    # (the worst of his own: not the cycles that waited for a part or the machine)
    worst = sorted(((r, c) for r in results for c in r.get("_cycles", []) if c.get("measured") and c.get("cause") in OWN),
                   key=lambda rc: -rc[1]["extra"])[:CLIPS_WORST]
    for r, c in worst:
        n += 1
        fn = f"clip_{n}.webm"
        ref = r["_refs"][c["variant"]]
        txt = f"cycle {c['sec']:.1f} s, best {ref['sec']:.1f} s: +{c['extra']:.1f} s ({CAUSE_TEXT.get(c['cause'], 'slower')})"
        ok = clip(r["_cam"], r["_op"], c["start"], c["end"], txt, out / fn)
        report["worst"].append({"operator": r["name"], "start": c["start"], "end": c["end"], "sec": round(c["sec"], 2),
                                "ref": round(ref["sec"], 2), "extra": round(c["extra"], 2), "cause": c["cause"],
                                "where": (meta.get(r["_op"]["key"], {}).get(c["where"]) or [c["where"]])[0] if c["where"] else None,
                                "variant": c["variant"], "text": txt, "clip": fn if ok else None})
    for typ in ("handling", "walking", "idle", "away"):
        evs = sorted(((r, e) for r in results for e in r.get("_events", []) if e["type"] == typ), key=lambda re: -re[1]["value"])
        for k, (r, e) in enumerate(evs):
            item = {"type": typ, "operator": r["name"], "start": e["start"], "end": e["end"], "text": e["text"],
                    "value": round(e["value"], 2), "clip": None}
            if k < CLIPS_PER_TYPE:
                n += 1
                fn = f"clip_{n}.webm"
                if clip(r["_cam"], r["_op"], e["start"], e["end"], e["text"], out / fn, wide=typ in ("walking", "away")):
                    item["clip"] = fn
            report["events"].append(item)
    report["top_causes"] = top_causes(results)
    report["suggestions"] = suggestions(results)
    for r in results:
        r["events"] = {t: sum(1 for e in r.get("_events", []) if e["type"] == t) for t in ("handling", "walking", "idle", "away")}
        for k in [k for k in r if k.startswith("_")]:
            del r[k]
        report["operators"].append(r)
    if not any(r.get("measured") for r in report["operators"]):
        report["notes"].append("No operator had enough measured cycles in this window.")
    report["seconds"] = round(time.time() - started, 1)
    tmp = out / "report.json.tmp"
    tmp.write_text(json.dumps(report, indent=1), encoding="utf-8")
    os.replace(tmp, out / "report.json")
    say(f"report written in {report['seconds']:.0f} s: {out}")


if __name__ == "__main__":
    main()
