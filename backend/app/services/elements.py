"""Automatic work-element breakup of operator cycles - no predefined process needed.

How it works (on the recordings written by vision/recorder.py):
1. Track the operator's two wrists over time (normalized image coordinates).
2. "Dwell" frames = both hands (almost) still. Their wrist positions are clustered (k-means, then close clusters
   merged): every cluster is a recurring hand configuration = a work spot, e.g. "both hands at the fixture",
   "left hand at bin, right hand holding the part", "right hand at the start button".
3. Every frame is labelled with its spot (or "moving" / "operator away"); short flickers are smoothed away and the
   movement before a spot is counted to that spot's element (reach + work, as in MTM).
4. The element that occurs exactly once per cycle with the most regular rhythm marks the cycle start, so cycles are
   found without any fixture zone.
5. The most frequent element sequence + median times = the standard (or a cycle the user marks as master).
   Every cycle is aligned to it (Needleman-Wunsch) -> slow / missing / extra / repeated / out-of-order elements,
   operator away, cycle over standard.
"""
from __future__ import annotations

import json
import math
import time
import warnings
from dataclasses import dataclass
from datetime import datetime

import cv2
import numpy as np

from ..vision.recorder import list_segments

MOVE, AWAY = -1, -2
DWELL_SPEED = 0.15  # image widths per second: below = hands "still" (working at a spot)
MERGE_DIST = 0.07  # spots closer than this (4-D wrist distance) are the same spot
ASSIGN_RADIUS = 0.11  # a frame belongs to a spot if its wrists are within this distance
MIN_SUPPORT = 0.015  # spots with less than 1.5 % of the dwell time are noise
MAX_ELEMENTS = 8
MIN_RUN_SEC = 0.7  # shorter labels are flicker
AWAY_MIN_SEC = 1.5
MAX_CYCLE_SEC = 300.0
FILL_GAP_SEC = 1.0  # bridge short wrist dropouts (occlusion) with the last known position

PALETTE = ["#38bdf8", "#f59e0b", "#10b981", "#a78bfa", "#f43f5e", "#22d3ee", "#eab308", "#84cc16", "#fb7185", "#c084fc", "#2dd4bf", "#f97316"]


# ------------------------------------------------------------------ data
GAP = -3  # no video (camera disconnected / recording paused)
GAP_SEC = 2.5  # frames further apart than this = a hole in the recording
BODY_WEIGHT = 1.0  # weight of the operator's position vs the hands in the element features


@dataclass
class Track:
    t: np.ndarray  # (N,) unix time
    X: np.ndarray  # (N,6) Lx, Ly, Rx, Ry (wrists), Bx, By (body = shoulder centre)  (nan = unknown)
    present: np.ndarray  # (N,) operator visible
    gap_before: np.ndarray  # (N,) True if the recording had a hole right before this frame

    def __len__(self) -> int:
        return len(self.t)

    def feats(self, dims: int) -> np.ndarray:
        """Features used for the element spots (old 4-D models: wrists only)."""
        X = self.X[:, :dims].copy()
        if dims > 4:
            X[:, 4:6] *= BODY_WEIGHT
        return X


def _stand(p: dict) -> tuple[float, float]:
    """Where a recorded person stands: feet (bottom of the box) if visible, else the shoulder centre."""
    b = p.get("b")
    if b and b[3] < 0.97:
        return ((b[0] + b[2]) / 2, b[3])
    c = p.get("c") or [0.5, 0.5]
    return (c[0], c[1])


class _OperatorPicker:
    """Follows the station operator through the recording: acquired where they stand inside the work area,
    then kept frame to frame by position, so colleagues walking past never replace them."""

    FOLLOW = 0.2  # max jump of the standing point between frames (image units)

    def __init__(self, work_areas: list[list] | None) -> None:
        self.areas = [np.asarray(a, np.float32).reshape(-1, 1, 2) for a in (work_areas or [])]
        self.centre = tuple(np.vstack(work_areas[0]).mean(axis=0)) if work_areas else None
        self.last: tuple[float, float] | None = None
        self.last_t = -1e9

    def pick(self, rec: dict) -> dict | None:
        people = rec.get("p") or []
        t = rec.get("t", 0.0)
        if t - self.last_t > 10:  # long hole: acquire again
            self.last = None
        best = None
        if people and self.last is not None:
            near = min(people, key=lambda p: math.dist(_stand(p), self.last))
            if math.dist(_stand(near), self.last) <= self.FOLLOW:
                best = near
        if best is None and people:
            if self.areas:
                inside = [p for p in people if any(cv2.pointPolygonTest(a, _stand(p), False) >= 0 for a in self.areas)]
                if inside:
                    best = min(inside, key=lambda p: math.dist(_stand(p), self.centre))
            else:
                op = rec.get("op")
                best = people[op] if isinstance(op, int) and 0 <= op < len(people) else max(
                    people, key=lambda p: (p["b"][2] - p["b"][0]) * (p["b"][3] - p["b"][1]) if p.get("b") else 0.0)
        if best is not None:
            self.last, self.last_t = _stand(best), t
        return best


def load_track(camera_id: int, t0: float, t1: float, work_areas: list[list] | None = None) -> Track:
    rows = []
    for _, path in list_segments(camera_id, t0, t1):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue  # half-written last line
                    if t0 <= r.get("t", 0) <= t1:
                        rows.append(r)
        except OSError:
            continue
    rows.sort(key=lambda r: r["t"])
    n = len(rows)
    t = np.array([r["t"] for r in rows], float)
    X = np.full((n, 6), np.nan)
    present = np.zeros(n, bool)
    picker = _OperatorPicker(work_areas)
    for i, r in enumerate(rows):
        p = picker.pick(r)
        if p is None:
            continue
        present[i] = True
        w = p.get("w") or [None, None]
        if w[0] is not None:
            X[i, 0:2] = w[0]
        if len(w) > 1 and w[1] is not None:
            X[i, 2:4] = w[1]
        if p.get("c"):
            X[i, 4:6] = p["c"]
    gap = np.zeros(n, bool)
    if n > 1:
        gap[1:] = np.diff(t) > GAP_SEC
    return Track(t, _fill(t, X), present, gap)


def _fill(t: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Bridge short dropouts of each wrist; if one wrist is unknown, use the other (hands work together)."""
    X = X.copy()
    for c in (0, 2):
        last, last_t = None, -1e9
        for i in range(len(t)):
            if not np.isnan(X[i, c]):
                last, last_t = X[i, c : c + 2].copy(), t[i]
            elif last is not None and t[i] - last_t <= FILL_GAP_SEC:
                X[i, c : c + 2] = last
    lmiss, rmiss = np.isnan(X[:, 0]), np.isnan(X[:, 2])
    X[lmiss & ~rmiss, 0:2] = X[lmiss & ~rmiss, 2:4]
    X[rmiss & ~lmiss, 2:4] = X[rmiss & ~lmiss, 0:2]
    return X


def _speed(tr: Track) -> np.ndarray:
    if len(tr) < 3:
        return np.zeros(len(tr))
    sm = tr.X.copy()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN windows (operator not visible) are expected
        sm[1:-1] = np.nanmedian(np.stack([tr.X[:-2], tr.X[1:-1], tr.X[2:]]), axis=0)  # 3-frame median against jitter
    dt = np.diff(tr.t, prepend=tr.t[0] - 0.2)
    dt[dt <= 0] = 0.2
    d = np.diff(sm, axis=0, prepend=sm[:1])
    v = np.maximum(np.hypot(d[:, 0], d[:, 1]), np.hypot(d[:, 2], d[:, 3])) / dt
    return np.nan_to_num(v, nan=np.inf)


# ------------------------------------------------------------------ spots
def discover_spots(tr: Track, dims: int = 6, merge_dist: float = MERGE_DIST) -> tuple[np.ndarray, np.ndarray]:
    """Returns (centers (K,dims), support counts)."""
    F = tr.feats(dims)
    ok = tr.present & ~np.isnan(F).any(axis=1)
    dwell = ok & (_speed(tr) < DWELL_SPEED)
    pts = F[dwell].astype(np.float32)
    if len(pts) < 30:
        return np.zeros((0, dims)), np.zeros(0)
    k = int(min(14, max(2, len(pts) // 25)))
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 1e-4)
    _, lab, centers = cv2.kmeans(pts, k, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    centers = centers.astype(float)
    counts = np.bincount(lab.ravel(), minlength=k).astype(float)
    # merge spots that are really the same place
    while len(centers) > 1:
        d = np.linalg.norm(centers[:, None] - centers[None], axis=2)
        np.fill_diagonal(d, np.inf)
        i, j = np.unravel_index(np.argmin(d), d.shape)
        if d[i, j] >= merge_dist:
            break
        w = counts[i] + counts[j]
        centers[i] = (centers[i] * counts[i] + centers[j] * counts[j]) / w
        counts[i] = w
        centers, counts = np.delete(centers, j, 0), np.delete(counts, j)
    keep = counts >= MIN_SUPPORT * counts.sum()
    centers, counts = centers[keep], counts[keep]
    # a person can follow ~8 elements per station; more usually means one place split by keypoint noise
    while len(centers) > MAX_ELEMENTS:
        d = np.linalg.norm(centers[:, None] - centers[None], axis=2)
        np.fill_diagonal(d, np.inf)
        i, j = np.unravel_index(np.argmin(d), d.shape)
        w = counts[i] + counts[j]
        centers[i] = (centers[i] * counts[i] + centers[j] * counts[j]) / w
        counts[i] = w
        centers, counts = np.delete(centers, j, 0), np.delete(counts, j)
    return centers, counts


def label_frames(tr: Track, centers: np.ndarray, radius: float = ASSIGN_RADIUS) -> np.ndarray:
    lab = np.full(len(tr), MOVE, int)
    lab[~tr.present] = AWAY
    if len(centers) == 0:
        return lab
    F = tr.feats(centers.shape[1])
    ok = tr.present & ~np.isnan(F).any(axis=1)
    if ok.any():
        d = np.linalg.norm(F[ok][:, None, :] - centers[None], axis=2)
        nearest = d.argmin(axis=1)
        within = d[np.arange(len(nearest)), nearest] <= radius
        idx = np.where(ok)[0]
        lab[idx[within]] = nearest[within]
    return lab


# ------------------------------------------------------------------ segmentation
@dataclass
class Run:
    label: int
    t0: float
    t1: float

    @property
    def dur(self) -> float:
        return self.t1 - self.t0


def _runs(t: np.ndarray, lab: np.ndarray, gap_before: np.ndarray | None = None) -> list[Run]:
    """Consecutive frames with the same label. A hole in the recording becomes a GAP run, so no element
    ever 'lasts' across minutes without video."""
    if len(t) == 0:
        return []
    step = float(np.median(np.diff(t))) if len(t) > 1 else 0.2
    gaps = gap_before if gap_before is not None else np.zeros(len(t), bool)
    out: list[Run] = []
    start = 0
    for i in range(1, len(t) + 1):
        if i == len(t) or lab[i] != lab[start] or gaps[i]:
            if i < len(t) and gaps[i]:
                end_t = t[i - 1] + step
                out.append(Run(int(lab[start]), float(t[start]), float(end_t)))
                out.append(Run(GAP, float(end_t), float(t[i])))
            else:
                end_t = t[i] if i < len(t) else t[-1] + step
                out.append(Run(int(lab[start]), float(t[start]), float(end_t)))
            start = i
    return out


def segment(tr: Track, lab: np.ndarray) -> list[Run]:
    """Element runs: flicker removed, movement attached to the following spot, short absences ignored."""
    runs = _runs(tr.t, lab, tr.gap_before)
    # 1) short spot flickers between the same spot -> absorb; other short spot runs -> movement
    changed = True
    while changed and len(runs) > 2:
        changed = False
        for k in range(1, len(runs) - 1):
            r = runs[k]
            if r.label >= 0 and r.dur < MIN_RUN_SEC:
                if runs[k - 1].label == runs[k + 1].label:
                    runs[k - 1] = Run(runs[k - 1].label, runs[k - 1].t0, runs[k + 1].t1)
                    del runs[k : k + 2]
                else:
                    runs[k] = Run(MOVE, r.t0, r.t1)
                changed = True
                break
    # 2) short absences are just occlusions
    runs = [Run(MOVE, r.t0, r.t1) if r.label == AWAY and r.dur < AWAY_MIN_SEC else r for r in runs]
    # 3) merge neighbours with the same label
    merged: list[Run] = []
    for r in runs:
        if merged and merged[-1].label == r.label:
            merged[-1] = Run(r.label, merged[-1].t0, r.t1)
        else:
            merged.append(r)
    # 4) movement belongs to the next element (reach + do); trailing movement to the previous one
    out: list[Run] = []
    pending: float | None = None
    for r in merged:
        if r.label == MOVE:
            pending = r.t0 if pending is None else pending
            continue
        if r.label == GAP:  # a recording hole is a hard boundary: movement before it stays with the previous element
            if pending is not None and out and out[-1].label != GAP:
                out[-1] = Run(out[-1].label, out[-1].t0, r.t0)
            pending = None
            out.append(r)
            continue
        t0 = pending if pending is not None else r.t0
        pending = None
        if out and out[-1].label == r.label:
            out[-1] = Run(r.label, out[-1].t0, r.t1)
        else:
            out.append(Run(r.label, t0, r.t1))
    if pending is not None and out:
        out[-1] = Run(out[-1].label, out[-1].t0, merged[-1].t1)
    return out


def find_cycle_start(runs: list[Run], n_labels: int, takt_hint: float | None) -> int | None:
    """The spot that starts exactly one element per cycle: its occurrences have the most regular rhythm.
    (A spot visited several times per cycle has alternating short / long gaps -> irregular.)"""
    best, best_score = None, 0.0
    gaps = [(r.t0, r.t1) for r in runs if r.label == GAP]
    for lab in range(n_labels):
        occ = np.array([r.t0 for r in runs if r.label == lab])
        if len(occ) < 4:
            continue
        # intervals that contain a recording hole say nothing about the rhythm
        iv = np.array([b - a for a, b in zip(occ, occ[1:]) if not any(g0 < b and g1 > a for g0, g1 in gaps)])
        iv = iv[iv < MAX_CYCLE_SEC]
        if len(iv) < 3:
            continue
        med = float(np.median(iv))
        if med < 3.0:
            continue
        # robust spread: interquartile range relative to the median
        q1, q3 = np.percentile(iv, [25, 75])
        spread = float((q3 - q1) / med)
        regular = float(np.mean((iv > 0.6 * med) & (iv < 1.6 * med)))
        score = regular * max(0.0, 1.0 - spread) * math.log1p(len(iv))
        if takt_hint and not (0.4 * takt_hint <= med <= 8 * takt_hint):
            score *= 0.5
        if score > best_score:
            best, best_score = lab, score
    return best


def split_cycles(runs: list[Run], start_label: int) -> list[list[Run]]:
    starts = [i for i, r in enumerate(runs) if r.label == start_label]
    cycles = []
    for a, b in zip(starts, starts[1:]):
        if runs[b].t0 - runs[a].t0 <= MAX_CYCLE_SEC and all(r.label != GAP for r in runs[a:b]):
            cycles.append(runs[a:b])
    return cycles


# ------------------------------------------------------------------ standard + comparison
def _seq(cycle: list[Run]) -> tuple[int, ...]:
    return tuple(r.label for r in cycle)


MIN_ISSUE_SEC = 2.0  # shorter unplanned actions / order changes are noted (info) but not counted as issues
CORE_RATE = 0.8  # done in at least this share of cycles = must be done every cycle (missing = issue)
STD_MIN_RATE = 0.6  # an element belongs to the standard when it occurs in at least this share of cycles
OPTIONAL_MIN_RATE = 0.25  # rarer than this = unusual action (reported); in between = variable action (not reported)
AWAY_REGULAR = 0.5  # operator out of view in at least this share of cycles = part of the normal work (walks to the next machine ...)


def _compact(seq: list[int], durs: list[float], keep: set[int]) -> tuple[list[int], list[float]]:
    """Keeps only the given elements and merges neighbours with the same id (durations added)."""
    s: list[int] = []
    d: list[float] = []
    for e, x in zip(seq, durs):
        if e not in keep:
            continue
        if s and s[-1] == e:
            d[-1] += x
        else:
            s.append(e)
            d.append(x)
    return s, d


def _profile(seq: list[int], durs: list[float]) -> tuple[dict[int, float], dict[int, int], dict[int, float]]:
    """Per element of one cycle: total time, number of separate occurrences (an element only interrupted by the
    operator being away counts once) and where in the cycle it first happens (0..1)."""
    tot: dict[int, float] = {}
    cnt: dict[int, int] = {}
    first: dict[int, float] = {}
    total = sum(durs) or 1.0
    t, last, prev = 0.0, None, None
    for e, d in zip(seq, durs):
        tot[e] = tot.get(e, 0.0) + d
        first.setdefault(e, t / total)
        if e == AWAY:
            cnt[e] = cnt.get(e, 0) + (prev != AWAY)
        elif e != last:
            cnt[e] = cnt.get(e, 0) + 1
            last = e
        prev = e
        t += d
    return tot, cnt, first


def standard_from_sequences(items: list[tuple[list[int], list[float]]], start_id: int | None = None) -> dict:
    """items: (element sequence, durations) per cycle. The standard = the elements done in most cycles, in their usual
    order, each with its median time per cycle. Elements done in only some cycles are 'optional' (normal variation, not
    reported); total = median cycle time, 'other' = time not in standard elements (transitions, optional elements)."""
    items = [(list(s), list(d)) for s, d in items if s]
    if not items:
        return {"seq": [], "durations": [], "rates": [], "counts": [], "total": 0.0, "other": 0.0, "optional": [],
                "source": "auto", "master_cycle_id": None, "support": 0}
    n = len(items)
    profs = [_profile(s, d) for s, d in items]
    ids = {e for p in profs for e in p[0]}
    rate = {e: sum(e in p[0] for p in profs) / n for e in ids}
    keep = {e for e in ids if rate[e] >= (AWAY_REGULAR if e == AWAY else STD_MIN_RATE)}
    if start_id in ids:
        keep.add(start_id)
    keep = keep or ids
    pos = {e: float(np.median([p[2][e] for p in profs if e in p[2]])) for e in keep}
    seq = sorted(keep, key=lambda e: (e != start_id, pos[e]))
    times = [np.array([p[0][e] for p in profs if e in p[0]]) for e in seq]
    durs = [float(np.median(v)) for v in times]
    counts = [int(round(float(np.median([p[1][e] for p in profs if e in p[1]])))) for e in seq]
    totals = np.array([sum(d) for _, d in items])
    total = float(np.median(totals))
    core = [e for e in seq if e != AWAY and rate[e] >= CORE_RATE]
    support = sum(all(e in p[0] for e in core) for p in profs) / n
    return {"seq": seq, "durations": [round(x, 2) for x in durs], "rates": [round(rate[e], 2) for e in seq],
            "limits": [round(_upper_limit(v), 2) for v in times], "total_limit": round(_upper_limit(totals, 1.5, 0.15), 2),
            "counts": counts, "total": round(total, 2), "other": round(max(0.0, total - sum(durs)), 2),
            "optional": sorted(e for e in ids if e not in keep and e != AWAY and rate[e] >= OPTIONAL_MIN_RATE),
            "source": "auto", "master_cycle_id": None, "support": round(support, 3)}


def _upper_limit(v: np.ndarray, min_abs: float = 1.0, min_rel: float = 0.3) -> float:
    """Longest normal time: median + 2.5 robust sigma (MAD), at least +min_abs s and +min_rel x median."""
    med = float(np.median(v))
    sigma = 1.4826 * float(np.median(np.abs(v - med))) if len(v) >= 5 else 0.0
    return med + max(min_abs, min_rel * med, 2.5 * sigma)


def standard_from_items(items: list[tuple[list[int], list[float]]], start_id: int | None = None) -> dict:
    """When the operator is out of view in most cycles that absence is part of the standard (compared like an
    element); otherwise absences are left out of the standard and reported as losses."""
    items = [(list(s), list(d)) for s, d in items if s]
    away_rate = sum(AWAY in s for s, _ in items) / max(1, len(items))
    if away_rate < AWAY_REGULAR:
        items = [_compact(s, d, set(s) - {AWAY}) for s, d in items]
    return standard_from_sequences(items, start_id)


def build_standard(cycles: list[list[Run]], start_id: int | None = None) -> dict:
    return standard_from_items([(list(_seq(c)), [r.dur for r in c]) for c in cycles], start_id)


def evaluate(cycle_elems: list[dict], standard: dict, names: dict[int, str], start_id: int | None = None) -> tuple[list[dict], list[dict]]:
    """Compares one cycle with the standard. Fills std / delta into the elements and returns (elements, issues).

    Each element's total time in the cycle is compared with its standard time (an element interrupted by the operator
    being away counts as one); elements of the standard done in (almost) every cycle must be there and in order;
    rare elements are unplanned actions."""
    std_seq = list(standard.get("seq") or [])
    std_d = dict(zip(std_seq, standard.get("durations") or []))
    rates = dict(zip(std_seq, standard.get("rates") or [1.0] * len(std_seq)))
    counts = dict(zip(std_seq, standard.get("counts") or [1] * len(std_seq)))
    limits = dict(zip(std_seq, standard.get("limits") or [d + max(1.0, 0.3 * d) for d in standard.get("durations") or []]))
    optional = set(standard.get("optional") or [])
    away_std = AWAY in std_d  # being out of view is part of the normal cycle at this station
    tot, cnt, _ = _profile([e["id"] for e in cycle_elems], [e["dur"] for e in cycle_elems])
    issues: list[dict] = []
    losses: list[tuple[float, str]] = []  # (seconds lost, what) -> explains a long cycle

    def nm(eid: int | None) -> str:
        return names.get(eid, "Element") if eid is not None else "Element"

    # std / delta on the first occurrence; a part after the operator came back is marked as continued
    seen: set[int] = set()
    last = None
    for e in cycle_elems:
        gid = e["id"]
        if gid in std_d and gid not in seen:
            e["std"], e["delta"] = std_d[gid], round(tot[gid] - std_d[gid], 2)
            seen.add(gid)
        elif gid == last and gid != AWAY:
            e["cont"] = True
        if gid != AWAY:
            last = gid

    for gid in std_seq:
        s = std_d[gid]
        if gid == AWAY:
            if gid in tot and tot[gid] > max(limits[gid], s + 3.0):
                losses.append((tot[gid] - s, "operator away"))
                issues.append({"type": "away", "severity": "warning", "element": AWAY, "delta": round(tot[gid] - s, 2),
                               "text": f"Operator away / not visible {tot[gid]:.1f}s (usual {s:.1f}s, +{tot[gid] - s:.1f}s)"})
            continue
        if gid not in tot:
            if gid != start_id and rates.get(gid, 1.0) >= CORE_RATE:
                issues.append({"type": "missing", "severity": "critical", "element": gid, "delta": None,
                               "text": f"{nm(gid)} not done in this cycle"})
            continue
        dur = tot[gid]
        if dur > limits[gid] and dur - s >= MIN_ISSUE_SEC:
            losses.append((dur - s, nm(gid)))
            issues.append({"type": "slow", "severity": "warning", "element": gid, "delta": round(dur - s, 2),
                           "text": f"{nm(gid)} took {dur:.1f}s (standard {s:.1f}s, +{dur - s:.1f}s)"})
        elif gid != start_id and rates.get(gid, 1.0) >= CORE_RATE and s >= 2.0 and dur < 0.4 * s:
            issues.append({"type": "short", "severity": "info", "element": gid, "delta": round(dur - s, 2),
                           "text": f"{nm(gid)} only {dur:.1f}s (standard {s:.1f}s) – check it was done completely"})
        usual = max(1, counts.get(gid, 1))
        if cnt.get(gid, 0) > usual:  # a problem when it cost time, otherwise only noted
            issues.append({"type": "repeat", "severity": "warning" if dur > limits[gid] else "info", "element": gid, "delta": None,
                           "text": f"{nm(gid)} done {cnt[gid]}x (usually {usual}x) – re-pick / rework?"})

    for gid, dur in tot.items():
        if gid in std_d or gid in optional:
            continue  # optional = done in some cycles only, normal variation
        if gid == AWAY:
            losses.append((dur, "operator away"))
            for k, e in enumerate(cycle_elems):
                if e["id"] == AWAY:
                    during = cycle_elems[k - 1]["name"] if k > 0 else None
                    issues.append({"type": "away", "severity": "warning", "element": AWAY, "delta": e["dur"],
                                   "text": f"Operator away / not visible for {e['dur']:.1f}s" + (f" (during {during})" if during else "")})
        elif dur >= 1.0:
            losses.append((dur, nm(gid)))
            issues.append({"type": "extra", "severity": "warning" if dur >= MIN_ISSUE_SEC else "info", "element": gid, "delta": round(dur, 2),
                           "text": f"Unplanned action: {nm(gid)} ({dur:.1f}s)"})

    # order of the elements that are done every cycle
    core = [g for g in std_seq if g != AWAY and rates.get(g, 1.0) >= CORE_RATE]
    first = {}
    for k, e in enumerate(cycle_elems):
        first.setdefault(e["id"], k)
    done = sorted((g for g in core if g in first), key=lambda g: first[g])
    expected = [g for g in core if g in first]
    for a, b in zip(done, expected):
        if a != b:
            # very short elements are only a few frames: their order is not reliable enough to call it a problem
            sure = min(std_d[a], std_d[b]) >= MIN_ISSUE_SEC * 1.5
            issues.append({"type": "order", "severity": "warning" if sure else "info", "element": a, "delta": None,
                           "text": f"{nm(a)} done before {nm(b)} (standard order: {nm(b)} first)"})
            break

    total = sum(e["dur"] for e in cycle_elems)
    std_total = standard.get("total") or 0
    if std_total and total > (standard.get("total_limit") or max(std_total * 1.15, std_total + 1.5)):
        worst = max(losses, default=None)
        why = f" – most time lost: {worst[1]} ({worst[0]:.1f}s)" if worst and worst[0] > 0.5 else ""
        issues.append({"type": "cycle", "severity": "warning", "element": None, "delta": round(total - std_total, 2),
                       "text": f"Cycle {total:.1f}s vs standard {std_total:.1f}s (+{total - std_total:.1f}s){why}"})
    order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: order[x["severity"]])
    return cycle_elems, issues


# ------------------------------------------------------------------ naming
def _region(x: float, y: float) -> str:
    h = "left" if x < 0.33 else "right" if x > 0.67 else "centre"
    v = "top" if y < 0.33 else "bottom" if y > 0.67 else "middle"
    return "centre" if (h, v) == ("centre", "middle") else f"{v} {h}" if h != "centre" else f"{v} centre"


def _in_poly(x: float, y: float, pts: list) -> bool:
    cnt = np.asarray(pts, np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(cnt, (float(x), float(y)), False) >= 0


def describe(center: list[float], zones: list[dict]) -> str:
    def where(x: float, y: float) -> str:
        for z in zones:
            if z.get("type") in ("pick_zone", "part_zone", "trigger_zone") and _in_poly(x, y, z.get("points") or []):
                return z.get("name") or z.get("type")
        return _region(x, y)

    lw, rw = where(center[0], center[1]), where(center[2], center[3])
    together = math.hypot(center[0] - center[2], center[1] - center[3]) < 0.08
    hands = f"both hands at {lw}" if together or lw == rw else f"left hand at {lw}, right hand at {rw}"
    if len(center) >= 6:
        return f"operator at {_region(center[4] / BODY_WEIGHT, center[5] / BODY_WEIGHT)}: {hands}"
    return hands


MIN_CYCLES_TO_LEARN = 5


# ------------------------------------------------------------------ public API
def learn(camera_id: int, t0: float, t1: float, takt_hint: float | None, zones: list[dict],
          min_cycles: int = MIN_CYCLES_TO_LEARN) -> dict | None:
    work_areas = [z["points"] for z in zones if z.get("type") == "work_area" and z.get("points")]
    tr = load_track(camera_id, t0, t1, work_areas)
    if len(tr) < 100:
        return None
    dims = 6
    scale = math.sqrt(dims / 4)  # distances grow with the number of features
    radius = ASSIGN_RADIUS * scale
    centers, counts = discover_spots(tr, dims, MERGE_DIST * scale)
    if len(centers) < 2:
        return None
    lab_all = label_frames(tr, centers, radius)
    runs = segment(tr, lab_all)
    start = find_cycle_start(runs, len(centers), takt_hint)
    if start is None:
        return None
    cycles = split_cycles(runs, start)
    if len(cycles) < min_cycles:
        return None  # not enough complete cycles (e.g. many recording gaps) - learn later
    std = build_standard(cycles, start)
    # number the spots in the order they occur in the standard cycle: Step 1, Step 2, ...
    order = [k for k in dict.fromkeys(std["seq"]) if k >= 0] + [k for k in range(len(centers)) if k not in std["seq"]]
    remap = {old: new + 1 for new, old in enumerate(order)}
    remap[AWAY] = AWAY
    F = tr.feats(dims)
    elements = []
    for old in order:
        c = centers[old]
        idx = np.where(lab_all == old)[0]
        rep = float(tr.t[idx[np.argmin(np.linalg.norm(F[idx] - c, axis=1))]]) if len(idx) else float(tr.t[0])
        n = remap[old]
        in_std = old in std["seq"]
        elements.append({"id": n, "name": f"Step {n}" if in_std else f"Other action {n}", "desc": describe(list(c), zones),
                         "color": PALETTE[(n - 1) % len(PALETTE)], "center": [round(float(v), 4) for v in c], "rep_t": rep,
                         "in_standard": in_std})
    std["seq"] = [remap[s] for s in std["seq"]]
    std["optional"] = [remap[s] for s in std.get("optional", [])]
    return {
        "version": int(time.time()),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "window": [t0, t1],
        "elements": elements,
        "cycle_start": remap[start],
        "standard": std,
        "radius": radius,
        "dims": dims,
        "cycles_learned": len(cycles),
        "work_areas": work_areas,
    }


def analyze(camera_id: int, model: dict, t0: float, t1: float) -> list[dict]:
    """Cycles (complete ones only) in [t0, t1] with their element breakup and issues."""
    tr = load_track(camera_id, t0, t1, model.get("work_areas"))
    if len(tr) < 10:
        return []
    els = sorted(model["elements"], key=lambda e: e["id"])
    centers = np.array([e["center"] for e in els], float)
    ids = [e["id"] for e in els]
    lab = label_frames(tr, centers, model.get("radius", ASSIGN_RADIUS))
    lab = np.array([ids[v] if v >= 0 else v for v in lab])  # cluster index -> element id
    runs = segment(tr, lab)
    names = {e["id"]: e["name"] for e in els}
    names[AWAY] = "Operator away"
    outside = _outside_work_area(tr, model.get("work_areas") or [])
    out = []
    for cyc in split_cycles(runs, model["cycle_start"]):
        c0, c1 = cyc[0].t0, cyc[-1].t1
        elems = [{"id": r.label, "name": names.get(r.label, "?"), "start": round(r.t0 - c0, 2), "dur": round(r.dur, 2),
                  "std": None, "delta": None} for r in cyc]
        elems, issues = evaluate(elems, model["standard"], names, model.get("cycle_start"))
        issues += _reach_issues(tr, outside, c0, c1, elems)
        out.append({"start_ts": c0, "end_ts": c1, "cycle_sec": round(c1 - c0, 2), "elements": elems, "issues": issues,
                    "status": "issues" if any(i["severity"] != "info" for i in issues) else "ok"})
    return out


def _outside_work_area(tr: Track, work_areas: list[list]) -> np.ndarray:
    """Per frame: a wrist is outside every drawn work area (long reach)."""
    out = np.zeros(len(tr), bool)
    if not work_areas:
        return out
    cnts = [np.asarray(p, np.float32).reshape(-1, 1, 2) for p in work_areas]
    for i in range(len(tr)):
        if not tr.present[i]:
            continue
        for c in (0, 2):
            x, y = tr.X[i, c], tr.X[i, c + 1]
            if not np.isnan(x) and all(cv2.pointPolygonTest(cn, (float(x), float(y)), False) < 0 for cn in cnts):
                out[i] = True
    return out


def _reach_issues(tr: Track, outside: np.ndarray, c0: float, c1: float, elems: list[dict]) -> list[dict]:
    issues = []
    idx = np.where((tr.t >= c0) & (tr.t < c1))[0]
    k = 0
    while k < len(idx):
        if not outside[idx[k]]:
            k += 1
            continue
        j = k
        while j + 1 < len(idx) and outside[idx[j + 1]]:
            j += 1
        dur = float(tr.t[idx[j]] - tr.t[idx[k]]) + 0.2
        at = float(tr.t[idx[k]] - c0)
        # hands leaving the area while the operator walks away are already reported as "operator away"
        near_away = any(e["id"] == AWAY and e["start"] - 1.5 <= at <= e["start"] + e["dur"] + 1.5 for e in elems)
        if dur >= 0.4 and not near_away:
            during = next((e["name"] for e in elems if e["start"] <= at < e["start"] + e["dur"]), None)
            issues.append({"type": "reach", "severity": "info", "element": None, "delta": round(dur, 2),
                           "text": f"Hand outside the normal work area for {dur:.1f}s at {at:.1f}s"
                                   + (f" (during {during})" if during else "") + " – long reach / material too far?"})
        k = j + 1
    return issues


def standard_from_cycle(elements: list[dict]) -> dict:
    """The master cycle as standard: its elements in their order with its times (an absence in it counts as part of
    the standard)."""
    tot, cnt, first = _profile([e["id"] for e in elements], [e["dur"] for e in elements])
    seq = sorted(tot, key=lambda e: first[e])
    return {"seq": seq, "durations": [round(tot[e], 2) for e in seq], "rates": [1.0] * len(seq), "counts": [cnt[e] for e in seq],
            "total": round(sum(tot.values()), 2), "other": 0.0, "optional": [], "source": "master", "support": None}
