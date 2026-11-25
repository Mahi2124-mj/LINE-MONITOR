"""Element breakup reports of stations 1-5 from the recordings (same idea as final_report.py for the final station).

Every detector below was built after watching the station's video frame by frame (2026-10-09 23:30-23:50 and
2026-10-10 00:00-00:20); the rules, regions and thresholds come from those annotations and were checked against them
(see validation/<station>_findings.md and `python station_breakup.py <station> --validate`).

  m1  - Upper Rail Greasing (camera 1): one operator; machine stroke = red carriage in a small region.
  m2  - Lower Rail Grease & Bar Coding (camera 2): operator A (rack -> left machine -> chute -> holder of the right
        machine); operator B at the right machine is only summarised.
  m34 - Rail Assy #01 + #02 (cameras 3 + 4): one operator runs both machines in a loop.
  m5  - Semi Automatic & Bending (camera 5): operator only visible as a hand loading the nest; machine elements from
        template differences of the press / ram / carriage regions.

usage: python station_breakup.py <m1|m2|m34|m5> --auto
       python station_breakup.py <m1|m2|m34|m5> <stats from> <stats to> <video from> <video to> [YYYY-MM-DD]
       python station_breakup.py <m1|m2|m34|m5> --validate      (detector vs the frame-by-frame annotations)
       python station_breakup.py m1 --validate day              (m1 day-shift set, 2026-10-10 09:21-09:25)
       python station_breakup.py <key> --validate <set>         (validation/<key>_<set>_annotations.json, e.g. ylr evening,
                                                                 ysr day1652, yfi day1612, yfi day1021; prints found /
                                                                 extra cycles)
"""
from __future__ import annotations

import html
import json
import math
import statistics as stat
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.config import settings  # noqa: E402
from app.services.report_gen import (CHARTS_BODY, PLAYER_BODY, PLAYER_HEAD, VARIATION_HTML, load_frames, publish,  # noqa: E402
                                     read_frame, timeline, variation_data)

HERE = Path(__file__).resolve().parent
NAN = float("nan")


def ok(*v) -> bool:
    return all(v_ is not None and not (isinstance(v_, float) and math.isnan(v_)) for v_ in v)


def inb(p, box) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def roi(img, box):
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


# ======================================================================== m1: Upper Rail Greasing (camera 1)
class M1:
    """Station 1, 8 steps given by the process owner (2026-10-12), checked frame by frame on the 1600x900 video of
    2026-10-12 09:37:20-09:41:20 (validation/m1_hd_annotations.json, 15 cycles).

    Seen in the video, per cycle (times relative to the machine stroke S):
      walk back -> fixture front: wire part into the small holder at the end of the yellow bar, both hands low (S-8)
      -> pick a rail from the blue bin behind the fixture (S-6.3) -> rail into the greasing position behind the red
      column (S-5.1) -> spring support + handle from the second bin / box under it, placed in the holder (S-4.0) and
      taken out again (S-3.4) -> a greased rail taken out along the yellow bar / white roller (S-2.3)
      -> lock bar from the near side of the tiger-tape box (S-1.0) -> machine stroke S (1.3 s) while he assembles
      (S-0.2) -> reach over the tiger-tape box to Station 2 (S+2.9) -> walk back.
    """
    key, cams, station_id, title = "m1", (1,), 1, "Upper Rail Greasing m/c"
    # machine stroke = the carriage plate moves; its colour block changes during the shift (red, blue or none), so the cue is
    # the change of the plate region against its own +-30 s median picture, not a colour
    PLATE = (0.345, 0.470, 0.400, 0.565)
    DEV_ON, DEV_PEAK, DEV_HALF, DEV_STEP = 12.0, 20.0, 30.0, 5.0
    STROKE_MERGE = 1.0                 # plate-change runs closer than this are one stroke
    DEV_PEAK_GAP, GAP_SEC = 14.0, 1.0  # a stroke seen in one frame next to a recording gap (the recorder drops frames)
    FIX_X, BOX_X = 0.585, 0.625        # operator side from his box centre x (fixture / tiger-tape box side)
    WALK_KEY = "cx"                    # "cx" box centre (validated) or "x0" box left edge
    WALK_DROP = 0.015                  # walk back = his box centre leaves its right-most point after the hand-over
    MAX_CYCLE = 90.0
    OVER_X, OVER_CX = 0.72, 0.67       # hand-over: a wrist over the tiger-tape box, or the body far right
    LOCK_CX, LOCK_WX = 0.615, 0.67     # lock bar: body moves to the box side, or a wrist at its near side
    ORDER = [("WALK", "walk_to_fixture"), ("FRONT", "fixture_front"), ("PICK", "pick_rail"), ("LOAD", "load_rail"),
             ("SPRING", "spring_parts"), ("LOCK", "lock_bar"), ("ASSY", "assemble"), ("HAND", "hand_over")]
    NAMES = {
        "WALK": ("Walk back to the fixture", "#94a3b8"),
        "FRONT": ("Fixture front (wire part in, hands low)", "#2563eb"),
        "PICK": ("Pick upper rail from the blue bin", "#16a34a"),
        "LOAD": ("Put rail on the fixture for greasing", "#0891b2"),
        "SPRING": ("Spring support + handle; greased rail out", "#a855f7"),
        "LOCK": ("Lock bar from the tiger-tape box", "#be185d"),
        "ASSY": ("Assemble the parts (machine greases)", "#f59e0b"),
        "HAND": ("Reach over the box to Station 2", "#78716c"),
    }
    METHOD = [
        "Cycle: walk back to the fixture → next walk back. The walk back starts when his body leaves its right-most point after "
        "the reach over the tiger-tape box (box centre x drops 0.015).",
        "Machine stroke: the carriage plate area (x 0.345–0.400, y 0.470–0.565) differs from its own median picture of ±30 s "
        "(mean grey difference > 12, peak ≥ 20, or ≥ 14 when the stroke falls in a recording gap).",
        "Fixture front: right wrist x ≤ 0.56 and y ≥ 0.50, or left wrist low (x ≤ 0.62, y ≥ 0.64) · put rail: the last reach of "
        "the right wrist far up-left (x < 0.49 and y < 0.47, or x < 0.53 and y < 0.445) · pick: right wrist up (y < 0.51) or hidden "
        "in the bin within 1.8 s before that reach · spring parts: right hand back from the reach · greased rail out (shown in "
        "the data, inside spring parts): a wrist at x < 0.52 at bar height, or the body's left edge < 0.475 · lock bar: body "
        "centre x ≥ 0.615 or a wrist x ≥ 0.67 · assemble: body back from the box side, or the stroke if earlier · hand-over: a "
        "wrist x ≥ 0.72 at box-top height, or body centre x ≥ 0.67 with the hands not raised.",
        "Event times are the middle between the last frame before and the first frame with the cue (camera-1 recordings run at ~2 fps).",
        "Checked against 15 cycles annotated frame by frame on the full-resolution video (2026-10-12 09:37–09:41): 15/15 cycles "
        "found; step start median error 0.1–0.25 s (lock bar 0.45 s, assemble 0.4 s). The night (16/16) and Saturday-day (19/19) "
        "validation cycles are all still found.",
    ]
    UNSEEN = ["Whether the rail taken out ~2.3 s before the stroke is the one greased in the previous stroke (most likely) or the "
              "one loaded 3 s before: the rail is hidden behind the red column.",
              "What the thin wire part with the white clip is (taken from the front-bottom bin at every hand-over).",
              "What starts the machine: its first motion (slide at the red-column foot) comes 4.0–4.3 s before most strokes "
              "(13 of 16), at the moment he places the spring parts in the holder."]

    def features(self, frames):
        rows, thumbs = [], []
        for f in frames:
            img = read_frame(f)
            th = None
            if img is not None:
                th = cv2.cvtColor(roi(img, self.PLATE), cv2.COLOR_BGR2GRAY)
            thumbs.append(th)
            p = f["p"][f["op"]] if isinstance(f["op"], int) and f["op"] < len(f["p"]) else None
            if p is None:
                rows.append([f["t"], NAN] + [NAN] * 8)
                continue
            k = p["k"]
            kp = lambda j: [k[j][0], k[j][1]] if k[j][2] > 0.3 else [NAN, NAN]  # noqa: E731
            rows.append([f["t"], NAN, *p["b"], *kp(9), *kp(10)])
        A = np.array(rows, float)
        if len(A):
            A[:, 1] = self.plate_change(A[:, 0], thumbs)
        return A

    def plate_change(self, T, thumbs):
        """Mean |grey - median grey| of the carriage plate, median over +-DEV_HALF s (one median per DEV_STEP s)."""
        shp = next((t.shape for t in thumbs if t is not None), None)
        dev = np.full(len(T), NAN)
        if shp is None:
            return dev
        good = np.array([t is not None and t.shape == shp for t in thumbs])
        G = np.zeros((len(T),) + shp, np.float32)
        for i, t in enumerate(thumbs):
            if good[i]:
                G[i] = t
        for a in np.arange(T[0], T[-1] + self.DEV_STEP, self.DEV_STEP):
            lo, hi = np.searchsorted(T, a - self.DEV_HALF), np.searchsorted(T, a + self.DEV_HALF)
            idx = np.arange(lo, hi)[good[lo:hi]]
            if len(idx) < 20:
                continue
            med = np.median(G[idx], axis=0)
            i0, i1 = np.searchsorted(T, a - self.DEV_STEP / 2), np.searchsorted(T, a + self.DEV_STEP / 2)
            for i in range(i0, i1):
                if good[i]:
                    dev[i] = float(np.abs(G[i] - med).mean())
        return dev

    def strokes(self, T, dev):
        on = np.nan_to_num(dev) > self.DEV_ON
        runs, i = [], 0
        while i < len(T):
            if on[i]:
                j = i
                while j + 1 < len(T) and on[j + 1]:
                    j += 1
                runs.append([i, min(j + 1, len(T) - 1)])
                i = j + 1
            else:
                i += 1
        st: list = []
        for r in runs:
            if st and T[r[0]] - T[st[-1][1]] < self.STROKE_MERGE:
                st[-1][1] = r[1]
            else:
                st.append(r)
        out = []
        for a, b in st:
            pk = np.nanmax(dev[a:b + 1])
            gap = (a > 0 and T[a] - T[a - 1] > self.GAP_SEC) or (b > a and T[b] - T[b - 1] > self.GAP_SEC)
            if pk >= self.DEV_PEAK or (pk >= self.DEV_PEAK_GAP and gap):
                out.append([a, b])
        return out

    def detect(self, frames):
        A = self.features(frames)
        if len(A) < 50:
            return []
        T, dev = A[:, 0], A[:, 1]
        x0b, top, x1b = A[:, 2], A[:, 3], A[:, 4]
        cx = (x0b + x1b) / 2
        bad = (top < 0.05) | np.isnan(cx) | (cx < 0.45) | (cx > 0.80)
        m = lambda v: np.where(bad, NAN, v)  # noqa: E731
        Lx, Ly, Rx, Ry = m(A[:, 6]), m(A[:, 7]), m(A[:, 8]), m(A[:, 9])
        x0m = m(x0b)
        n = len(T)

        def ffill(x):
            y = x.copy()
            for i in range(1, len(y)):
                if np.isnan(y[i]):
                    y[i] = y[i - 1]
            return y
        cxf = ffill(m(cx))
        x0f = ffill(x0m)
        state, s_ = [], None
        for v in cxf:
            if v < self.FIX_X:
                s_ = "F"
            elif v > self.BOX_X:
                s_ = "B"
            state.append(s_)

        def onset(i):
            """Cue first seen in frame i: the event started between frame i-1 and i, so take the middle."""
            if i <= 0:
                return T[0]
            return (T[i - 1] + T[i]) / 2 if T[i] - T[i - 1] < 1.5 else T[i] - 0.25

        def first(a, b, cond):
            for i in range(max(a, 0), min(b, n)):
                if cond(i):
                    return i
            return None
        R = lambda i: ok(Rx[i], Ry[i])  # noqa: E731
        L = lambda i: ok(Lx[i], Ly[i])  # noqa: E731
        # the pose model sometimes swaps left and right while he holds the rail, so the box-side cues use either wrist
        wx_max = lambda i: max([v for v in (Lx[i], Rx[i]) if ok(v)], default=NAN)  # noqa: E731
        raised = lambda i: (L(i) and Ly[i] < 0.30) or (R(i) and Ry[i] < 0.30)  # noqa: E731

        def reach_over(i):
            """Hand-over: a wrist far over the tiger-tape box (x >= 0.74 at its top height) or the body far right."""
            wr = any(ok(x, y) and x >= self.OVER_X and 0.35 <= y <= 0.62 for x, y in ((Lx[i], Ly[i]), (Rx[i], Ry[i])))
            return wr or (ok(cx[i]) and not bad[i] and cx[i] >= self.OVER_CX and not raised(i))
        far = lambda q: R(q) and ((Rx[q] < 0.49 and Ry[q] < 0.47) or (Rx[q] < 0.53 and Ry[q] < 0.445))  # noqa: E731

        # walk back to the fixture: end of every box-side visit with a reach over the box (B run followed by F);
        # the walk starts when the body leaves its right-most point of that visit
        walks, i = [], 1
        while i < n:
            if state[i] == "B" and state[i - 1] != "B":
                j = i
                while j + 1 < n and state[j + 1] == "B":
                    j += 1
                seg = np.arange(i, j + 1)
                if j + 1 < n and state[j + 1] == "F" and any(reach_over(q) for q in seg):
                    wv = x0f if self.WALK_KEY == "x0" else cxf
                    pk = float(np.nanmax(wv[seg]))
                    last = max(q for q in seg if wv[q] >= pk - self.WALK_DROP)
                    ho = next(q for q in seg if reach_over(q))
                    tw = (T[last] + T[last + 1]) / 2 if T[last + 1] - T[last] < 1.5 else T[last] + 0.25
                    walks.append((last + 1, tw, ho))
                i = j + 1
            else:
                i += 1
        st = self.strokes(T, dev)
        seen = ~bad
        self.stroke_times = [T[a] for a, _ in st if seen[max(0, a - 6):a + 7].any()]

        def build(walks):
            """Cycles between consecutive walk-backs and the step times inside each."""
            cyc = []
            for (w0, tw0, _), (w1, tw1, ho) in zip(walks, walks[1:]):
                if tw1 - tw0 > self.MAX_CYCLE:
                    continue
                c = {"walk_to_fixture": tw0, "start": tw0, "end": tw1, "hand_over": onset(ho)}
                fr = first(w0, ho, lambda q: (R(q) and Rx[q] <= 0.56 and Ry[q] >= 0.50) or (L(q) and Lx[q] <= 0.62 and Ly[q] >= 0.64))
                if fr is None:
                    continue
                c["fixture_front"] = T[fr]
                # put rail: the last reach far up-left before the hand-over (a bin change has other high reaches before it)
                fars = [q for q in range(fr + 1, ho) if far(q)]
                ld = None
                if fars:
                    ld = fars[-1]
                    while ld - 1 in fars:
                        ld -= 1
                s0 = None
                if ld is not None:
                    c["load_rail"] = onset(ld)
                    # pick: the right hand goes up into the bin (or is hidden in it) in the 1.8 s before the reach to the greasing
                    # position; the pick starts at the last frame before that
                    up = lambda q: (R(q) and Ry[q] < 0.51) or (not R(q) and L(q))  # noqa: E731
                    pq = first(max(fr + 1, int(np.searchsorted(T, T[ld] - 1.8))), ld, up)
                    c["pick_rail"] = T[pq - 1] if pq is not None and pq - 1 > fr else T[ld - 1] if ld - 1 > fr else onset(ld)
                    sp = first(ld + 1, ho, lambda q: R(q) and not far(q))
                    if sp is not None:
                        c["spring_parts"] = s0 = onset(sp)
                # strokes of this cycle (one expected)
                a_s = s0 if s0 is not None else T[fr]
                ins = [(a, b) for a, b in st if a_s <= T[a] < tw1]
                if ins:
                    a, b = ins[0]
                    c["stroke_on"], c["stroke_off"] = T[a], T[b]
                    c["machine"] = {"Stroke": (T[a], T[b])}
                if s0 is None:
                    cyc.append(c)
                    continue
                i_s = int(np.searchsorted(T, s0))
                # greased rail out: he leans left to the rail lying along the yellow bar (a wrist at x < 0.52 at bar height, or the body's
                # left edge x0 < 0.475), after the spring parts were taken out of the holder
                ro = first(i_s + 1, ho, lambda q: T[q] >= s0 + 1.2 and (
                    any(ok(x, y) and x < 0.52 and 0.47 <= y <= 0.60 for x, y in ((Lx[q], Ly[q]), (Rx[q], Ry[q])))
                    or (ok(x0m[q]) and x0m[q] < 0.475)))
                if ro is not None:
                    c["greased_rail_out"] = onset(ro)
                a_lk = ro + 1 if ro is not None else int(np.searchsorted(T, s0 + 2.0))
                lk = first(a_lk, ho, lambda q: (ok(cx[q]) and not bad[q] and cx[q] >= self.LOCK_CX) or wx_max(q) >= self.LOCK_WX)
                if lk is not None:
                    c["lock_bar"] = T[lk]  # he is already at the box side in this frame
                    # assemble: the body comes back from the box side (centre x 0.01 below its lock-bar position) or the stroke
                    peak, q = cxf[lk], lk
                    while q + 1 < ho and cxf[q + 1] >= peak - 0.01:
                        q += 1
                        peak = max(peak, cxf[q])
                    asy = q + 1 if q + 1 < ho else None
                    if "stroke_on" in c and c["stroke_on"] > c["lock_bar"] and (asy is None or c["stroke_on"] < onset(asy)):
                        c["assemble"] = c["stroke_on"]
                    elif asy is not None:
                        c["assemble"] = onset(asy)
                cyc.append(c)
            return cyc
        # a box-side visit in the middle of a cycle (no rail put on the fixture, no stroke) is not a cycle end: merge it
        for _ in range(len(walks)):
            cyc = build(walks)
            bad_end = next((k + 1 for k, c in enumerate(cyc) if "load_rail" not in c and "stroke_on" not in c
                            and k + 1 < len(cyc)), None)
            if bad_end is None:
                break
            tw = cyc[bad_end - 1]["end"]
            walks = [w for w in walks if w[1] != tw]
        return cyc

    def extra(self, cycles):
        st = [c["stroke_on"] for c in cycles if "stroke_on" in c]
        n = len(getattr(self, "stroke_times", []))
        out = [f"Machine strokes in the window: {n} (operator cycles found: {len(cycles)})."] if n else []
        if len(st) > 2:
            out.append(f"Machine stroke (carriage plate moves) once per cycle, ~{stat.median([c['stroke_off'] - c['stroke_on'] for c in cycles if 'stroke_on' in c]):.1f}s; "
                       f"stroke to stroke median {stat.median(np.diff(st)):.1f}s.")
        ro = [c["stroke_on"] - c["greased_rail_out"] for c in cycles if "stroke_on" in c and "greased_rail_out" in c]
        if len(ro) > 2:
            out.append(f"The greased rail comes out ~{stat.median(ro):.1f}s before the next stroke, after the new rail is put in.")
        return out


# ======================================================================== m2: Lower Rail Grease & Bar Coding (camera 2)
class M2:
    key, cams, station_id, title = "m2", (2,), 2, "Lower Rail Grease & Bar Coding m/c"
    HOLD = (0.488, 0.435, 0.535, 0.500)     # white V-holder of the right machine
    GRIP = (0.500, 0.250, 0.600, 0.400)     # transfer gripper path
    LAMP = (0.503, 0.603, 0.522, 0.628)     # green lamp
    NESTB = (0.29, 0.38, 0.46, 0.56)
    HOLDB = (0.455, 0.40, 0.56, 0.555)
    GAPB = (0.40, 0.55, 0.48, 0.70)
    FIXB = (0.60, 0.33, 0.80, 0.62)
    ORDER = [("CARRY", "start"), ("RACK", "rack_arrive"), ("BACK", "rack_leave"), ("NEST", "nest_in"), ("CHECK", "nest_out"),
             ("CHUTE", "place_chute"), ("PICK", "reach_holder")]
    NAMES = {
        "CARRY": ("Carry holder rail to the rack", "#94a3b8"),
        "RACK": ("At the rack (hands in blue bins)", "#f59e0b"),
        "BACK": ("Walk back to the machine with a rail", "#78716c"),
        "NEST": ("Change rail in the left machine nest", "#2563eb"),
        "CHECK": ("In-hand check", "#06b6d4"),
        "CHUTE": ("Place rail on the chute", "#16a34a"),
        "PICK": ("Pick rail from the right machine holder", "#a855f7"),
    }
    METHOD = [
        "Operator A: person on the left (centre x < 0.6, box top < 0.5). Operator B: right machine (x ≥ 0.6). The breakup is for A.",
        "Cycle: the white holder of the right machine turns empty (A picked the rail) → next time.",
        "Rack: A centre x < 0.08 · leave rack: A's left shoulder clearly visible (turned) · nest: wrist in the nest · "
        "chute: wrist x > 0.42 or in chute / holder · pick: hand over the holder.",
        "Checked against 18 hand-annotated cycles: cycle start 18/18 same frame, rack ±0.2–0.3 s, nest / chute / holder ±0.15 s.",
    ]
    UNSEEN = ["Which machine greases and which bar-codes.",
              "Where the chute rail and the holder rail go, and what the rack bins are for.",
              "About 9 s of operator B's work per cycle is off-screen to the right."]

    def detect(self, frames):
        F, prev, lastA = [], None, None
        for f in frames:
            img = read_frame(f)
            if img is None:
                continue
            g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gb = cv2.GaussianBlur(g, (3, 3), 0).astype(np.int16)
            hold = float((roi(g, self.HOLD) > 165).mean())
            grip = 0.0 if prev is None else float((np.abs(roi(gb, self.GRIP) - roi(prev, self.GRIP)) > 18).mean())
            c = roi(img, self.LAMP).astype(np.float32)
            lamp = float((c[..., 1] - (c[..., 0] + c[..., 2]) / 2).mean())
            prev = gb
            ps = f["p"]
            cand = [q for q in ps if q.get("c") and q["c"][0] < 0.6 and q["b"][1] < 0.5]
            if lastA is not None:
                cand.sort(key=lambda q: abs(q["c"][0] - lastA))
            A = cand[0] if cand else None
            if A:
                lastA = A["c"][0]
            ws = [w for w in ((A["k"][9], A["k"][10]) if A else ()) if w[2] >= 0.3]
            Bs = [q for q in ps if q.get("c") and q["c"][0] >= 0.6 and q["b"][1] > 0.2]
            B = max(Bs, key=lambda q: (q["b"][2] - q["b"][0]) * (q["b"][3] - q["b"][1])) if Bs else None
            bws = [w for w in ((B["k"][9], B["k"][10]) if B else ()) if w[2] >= 0.3]
            F.append(dict(t=f["t"], hold=hold, grip=grip, lamp=lamp, Acx=A["c"][0] if A else NAN,
                          Lsh=(A["k"][5][0], A["k"][5][2]) if A else (NAN, 0.0),
                          nest=any(inb(w, self.NESTB) for w in ws), holdw=any(inb(w, self.HOLDB) for w in ws),
                          gap=any(inb(w, self.GAPB) for w in ws), wx=max([w[0] for w in ws], default=NAN),
                          Bx0=B["b"][0] if B else NAN, Bfix=any(inb(w, self.FIXB) for w in bws)))
        self.F = F
        H = np.array([f["hold"] for f in F])
        ev = []
        for i in range(3, len(F) - 1):
            if H[i] > 0.36 and H[i + 1] > 0.36 and H[i - 1] <= 0.36 and H[i - 3:i].min() < 0.30:
                if not ev or F[i]["t"] - F[ev[-1]]["t"] > 5:
                    ev.append(i)
        tr = []
        for i, f in enumerate(F):
            if f["grip"] > 0.2 and (f["lamp"] > 12 or (i + 1 < len(F) and F[i + 1]["lamp"] > 12)):
                if not tr or f["t"] - F[tr[-1]]["t"] > 5:
                    tr.append(i)
        self.transfers = [F[i]["t"] for i in tr]
        cyc = []
        for a, b in zip(ev, ev[1:]):
            c = {"start": F[a]["t"], "end": F[b]["t"]}

            def first(cond, s, e=b):
                for q in range(s, e):
                    if cond(F[q]):
                        return q
                return None
            q1 = first(lambda f: f["Acx"] < 0.08, a)
            q4 = first(lambda f: f["nest"], q1 or a)
            q2 = None
            if q1 is not None and q4 is not None:
                z = q4 - 1
                while z > q1 and F[z]["Acx"] >= 0.08:  # NaN (A not seen) stops the search, as in the validated rule
                    z -= 1
                s0 = z + 1
                while s0 - 1 > q1 and F[s0 - 1]["t"] > F[q1]["t"] + 1.0 and F[s0 - 1]["Lsh"][1] >= 0.85 and F[s0 - 1]["Lsh"][0] >= 0.03:
                    s0 -= 1
                q2 = min(s0, q4)
            q5 = None
            if q4 is not None:
                q5, gap = q4, 0
                for z in range(q4, b):
                    if F[z]["nest"]:
                        q5, gap = z, 0
                    else:
                        gap += 1
                        if gap > 1:
                            break
                q5 = min(q5 + 1, b)
            q6 = first(lambda f: f["wx"] > 0.42 or f["gap"] or f["holdw"], q5) if q5 is not None else None
            q7 = first(lambda f: f["hold"] < 0.22, q6) if q6 is not None else None
            for k, q in (("rack_arrive", q1), ("rack_leave", q2), ("nest_in", q4), ("nest_out", q5), ("place_chute", q6), ("reach_holder", q7)):
                if q is not None:
                    c[k] = F[q]["t"]
            trs = [t for t in self.transfers if c["start"] <= t < c["end"]]
            if trs:
                c["machine"] = {"Right machine transfer": (trs[0], trs[0] + 2.5)}
            cyc.append(c)
        return cyc

    def extra(self, cycles):
        F = getattr(self, "F", [])
        if not F:
            return []
        b_at = np.mean([ok(f["Bx0"]) and f["Bx0"] < 0.76 for f in F])
        return [f"Right machine transfer (gripper + green lamp) {len(self.transfers)} times; one transfer after each pick from the holder.",
                f"Operator B is at the machine ~{100 * b_at:.0f}% of the time; the rest is off-screen to the right."]


# ======================================================================== m34: Rail Assy #01 + #02 (cameras 3 + 4)
class M34:
    key, cams, station_id, title = "m34", (3, 4), 3, "Rail Assy m/c #01 + #02"
    BIN3, TRAY4, MACH4 = (0.30, 0.70, 0.45, 0.82), (0.50, 0.40, 0.64, 0.58), (0.60, 0.00, 1.00, 0.32)
    OUT4, STAND4, FIX3 = (0.60, 0.56, 0.76, 0.72), (0.22, 0.66, 0.50, 1.00), (0.00, 0.40, 0.30, 0.62)
    ORDER = [("L01", "01_load_rail"), ("P01", "01_parts"), ("U01", "01_unload_pick"), ("W12", "walk_01_02"),
             ("L02", "02_load_rail"), ("P02", "02_parts"), ("U02", "02_unload_to_stand"), ("W21", "walk_02_01")]
    NAMES = {
        "L01": ("#01: rail from rack into fixture", "#2563eb"),
        "P01": ("#01: fit small green parts", "#16a34a"),
        "U01": ("#01: unload rail + pick next rail", "#0891b2"),
        "W12": ("Walk #01 → #02 (hand at the stand)", "#cbd5e1"),
        "L02": ("#02: rail into fixture", "#7c3aed"),
        "P02": ("#02: fit small green parts", "#22c55e"),
        "U02": ("#02: unload rail, stand it in the rail stand", "#f59e0b"),
        "W21": ("Walk back to #01", "#94a3b8"),
    }
    METHOD = [
        "One operator (A, blue trousers) runs both machines; B (black trousers) is at the right edge of camera 3. "
        "A is told apart by trouser colour and position.",
        "Loop: A's first hand contact at #01 (camera 3) → next one. #02 elements come from camera 4.",
        "#01: wrist between fixture and green bin = parts; body x0 0.29 → 0.31 = unload and turn · entering camera 4 bottom-left = walk · "
        "#02: right wrist in the upper fixture → green tray = parts; front-right corner = unload; hand in the stand = place.",
        "Checked against 14 hand-annotated loops (+4 held out): every element median 0.05–0.4 s (max 1.3 s); "
        "loop start up to ~0.9 s off when A and B stand together.",
    ]
    UNSEEN = ["What is in his hands (number of parts / rails) and button presses.",
              "What he leaves at the rail stand on the way, and what his hand does near the #02 panel."]

    @staticmethod
    def _rows(frames):
        rows = []
        for f in frames:
            img = read_frame(f)
            ps = []
            if img is not None:
                H, W = img.shape[:2]
                for p in f["p"]:
                    kp, col = p["k"], None
                    pts = [((kp[h][0] + kp[k][0]) / 2, (kp[h][1] + kp[k][1]) / 2) for h, k in ((11, 13), (12, 14))
                           if kp[h][2] > .4 and kp[k][2] > .4]
                    cs = []
                    for x, y in pts:
                        xi, yi = int(x * W), int(y * H)
                        patch = img[max(0, yi - 4):yi + 5, max(0, xi - 4):xi + 5]
                        if patch.size:
                            cs.append(patch.reshape(-1, 3).mean(0))
                    if cs:
                        col = [float(v) for v in np.mean(cs, 0)]
                    ps.append({"b": p["b"], "k": kp, "col": col})
            rows.append({"t": f["t"], "p": ps})
        return rows

    @staticmethod
    def _track(rows, cam):
        out, last, lastt = [], None, None
        blue = lambda p: None if p.get("col") is None else p["col"][0] - p["col"][2]  # noqa: E731
        for r in rows:
            cand = []
            for p in r["p"]:
                b = p["b"]
                cx, by = (b[0] + b[2]) / 2, b[3]
                bl = blue(p)
                score = 0.0
                if bl is not None:
                    score += 2.0 if bl > 20 else (-2.0 if bl < 8 else 0)
                if last is not None and lastt is not None and r["t"] - lastt < 2.5:
                    score -= 4.0 * math.hypot(cx - last[0], by - last[1])
                if cam == 3 and b[0] > 0.74:
                    score -= 1.0
                if cam == 4 and b[2] < 0.22 and b[3] > 0.85:
                    score -= 1.0
                cand.append((score, p, cx, by))
            if not cand:
                out.append((r["t"], None))
                continue
            cand.sort(key=lambda c: -c[0])
            s, p, cx, by = cand[0]
            if s < -1.5 and (blue(p) is None or blue(p) < 8):
                out.append((r["t"], None))
                continue
            last, lastt = (cx, by), r["t"]
            out.append((r["t"], p))
        return out

    def detect(self, frames3, frames4):
        s3, s4 = self._track(self._rows(frames3), 3), self._track(self._rows(frames4), 4)
        wr = lambda P: [(P["k"][j][0], P["k"][j][1]) for j in (9, 10) if P["k"][j][2] > .3] if P else []  # noqa: E731
        at01 = lambda P: P is not None and P["b"][0] < 0.48 and P["b"][3] > 0.80  # noqa: E731
        left01 = lambda P: P is not None and P["b"][0] >= 0.55  # noqa: E731
        at02 = lambda P: P is not None and P["b"][0] >= 0.30 and P["b"][1] < 0.03 and P["b"][3] < 0.90  # noqa: E731

        def first(seq, t0, t1, cond, n=1):
            run = 0
            for i, (t, P) in enumerate(seq):
                if t < t0:
                    continue
                if t > t1:
                    return None
                run = run + 1 if cond(P) else 0
                if run >= n:
                    return seq[i - n + 1][0]
            return None
        runs, cur = [], None
        for t, P in s3:
            if at01(P):
                if cur and t - cur[1] < 2.5:
                    cur[1] = t
                else:
                    cur = [t, t]
                    runs.append(cur)
        runs = [r for r in runs if r[1] - r[0] >= 4.0]
        loops = []
        for i, (a, b) in enumerate(runs):
            e = {"01_load_rail": first(s3, a - 0.01, b, at01, 2)}
            if e["01_load_rail"] is None:
                continue
            tf = first(s3, e["01_load_rail"] + 0.5, b + 1, lambda P: any(inb(w, self.FIX3) for w in wr(P)))
            e["01_parts"] = first(s3, (tf or e["01_load_rail"]) + 0.01, b + 1, lambda P: any(inb(w, self.BIN3) for w in wr(P)))
            lo = None
            for t, P in s3:
                if a <= t <= b + 1.5 and P is not None and P["b"][0] < 0.29:
                    lo = t
            e["01_unload_pick"] = first(s3, lo + 0.01, b + 2, lambda P: P is not None and P["b"][0] >= 0.31) if lo else None
            t4in = first(s4, (e["01_unload_pick"] or b) + 1.0, b + 12,
                         lambda P: P is not None and P["b"][3] >= 0.845 and P["b"][0] < 0.35 and P["b"][1] < 0.2, 1)
            e["walk_01_02"] = t4in - 0.5 if t4in else first(s3, (e["01_unload_pick"] or b) + 1.0, b + 8, left01, 2)
            nxt = runs[i + 1][0] if i + 1 < len(runs) else None
            if e["walk_01_02"] is None or nxt is None:
                continue
            e["02_load_rail"] = first(s4, e["walk_01_02"], nxt, at02, 2)
            if e["02_load_rail"] is None:
                continue
            rw = lambda P: P is not None and P["k"][10][2] > .3 and inb(P["k"][10][:2], self.MACH4)  # noqa: E731
            tm = first(s4, e["02_load_rail"], nxt, rw, 2)
            e["02_parts"] = first(s4, (tm or e["02_load_rail"]) + 0.01, nxt, lambda P: any(inb(w, self.TRAY4) for w in wr(P)))
            t5 = e["02_parts"] or e["02_load_rail"]
            tturn = first(s4, t5 + 2.0, nxt, lambda P: P is not None and P["b"][0] < 0.32, 2)
            e["02_unload_to_stand"] = first(s4, t5 + 2.0, tturn or nxt, lambda P: any(inb(w, self.OUT4) for w in wr(P)))
            if e["02_unload_to_stand"] is None and tturn:
                e["02_unload_to_stand"] = tturn - 0.8
            t7 = None
            for t, P in s4:
                if (e["02_unload_to_stand"] or t5 + 3) + 0.8 <= t <= nxt and any(inb(w, self.STAND4) for w in wr(P)):
                    t7 = t
            e["walk_02_01"] = t7 - 0.3 if t7 else None
            e["end"] = nxt
            e["start"] = e["01_load_rail"]
            loops.append({k: v for k, v in e.items() if v is not None})
        return loops

    def extra(self, cycles):
        v01 = [c["01_unload_pick"] - c["01_load_rail"] for c in cycles if "01_unload_pick" in c]
        v02 = [c["02_unload_to_stand"] - c["02_load_rail"] for c in cycles if "02_unload_to_stand" in c and "02_load_rail" in c]
        out = []
        if v01 and v02:
            out.append(f"Per loop ~{stat.median(v01):.1f}s at #01 and ~{stat.median(v02):.1f}s at #02 (until the rail is unloaded).")
        out.append("In the annotated video both machines had finished before A came back: the machines wait for the operator "
                   "(~4 s per loop), not the other way round.")
        return out


# ======================================================================== m5: Semi Automatic & Bending (camera 5)
class M5:
    key, cams, station_id, title = "m5", (5,), 5, "Semi Automatic & Bending m/c"
    R = {"tube": (.25, 0, .43, .25), "nest": (.55, .3, .70, .55), "right": (.78, .5, 1, .95), "ladder": (.55, .3, .8, .6)}
    ORDER = [("LOAD", "load_part"), ("WAIT", "wait_for_machine_start"), ("TRANS", "transfer"), ("SHORT", "carriage_short_stroke"),
             ("FR", "fr_press_down"), ("RAM", "ram_down"), ("CARR", "carriage_forward"), ("BACK", "carriage_back"), ("IDLE", "machine_rest")]
    NAMES = {
        "LOAD": ("Operator: load rail into the nest by hand", "#16a34a"),
        "WAIT": ("Wait for machine start", "#cbd5e1"),
        "TRANS": ("Machine: transfer (start)", "#2563eb"),
        "SHORT": ("Machine: carriage short stroke", "#0891b2"),
        "FR": ("Machine: Fr press down", "#7c3aed"),
        "RAM": ("Machine: centre ram down", "#ec4899"),
        "CARR": ("Machine: carriage forward (long stroke)", "#f97316"),
        "BACK": ("Machine: carriage back", "#facc15"),
        "IDLE": ("Machine idle, waiting for the operator", "#dc2626"),
    }
    METHOD = [
        "The operator's body is not visible on camera 5; only the hand loading the rail (bottom-right) shows for 1–3 frames.",
        "Cycle: rail loaded by hand → next load. Machine elements: difference of the press / ram / carriage regions to 4 reference "
        "images (idle, Fr down, ram down, carriage forward).",
        "Checked against 15 hand-annotated cycles (+6 held out): load 15/15, machine start 14/14, ram 15/15, Fr press / carriage within 1 frame (0.35 s).",
        "If the camera moves or the lighting changes, the reference images must be taken again.",
    ]
    UNSEEN = ["Where the operator stands and how the machine is started (button / pedal / sensor).",
              "Where the finished rail goes and what the operator does during long waits."]

    def __init__(self):
        self.TPL = {k: cv2.imread(str(HERE / "templates" / f"m5_{f}.png"), cv2.IMREAD_GRAYSCALE).astype(np.float32)
                    for k, f in (("idle", "idle"), ("dwell", "fr_down"), ("tool", "ram_down"), ("fwd", "carriage_fwd"))}

    def features(self, frames):
        T, feats, prev_corner = [], [], None
        sl = lambda r: (slice(int(r[1] * 90), int(r[3] * 90)), slice(int(r[0] * 160), int(r[2] * 160)))  # noqa: E731
        for f in frames:
            img = read_frame(f)
            if img is None:
                continue
            g = cv2.resize(img, (160, 90), interpolation=cv2.INTER_AREA)
            gr = g.astype(np.float32).mean(-1)
            d = lambda reg, tp: float(np.abs(gr[sl(self.R[reg])] - self.TPL[tp][sl(self.R[reg])]).mean())  # noqa: E731
            hsv = cv2.cvtColor(g[72:90, 140:160], cv2.COLOR_BGR2HSV)
            cb = float(((hsv[..., 0] >= 95) & (hsv[..., 0] <= 130) & (hsv[..., 1] > 60) & (hsv[..., 2] > 40)).mean())
            corner = gr[int(.70 * 90):90, int(.80 * 160):160]
            cm = 0.0 if prev_corner is None else float(np.abs(corner - prev_corner).mean())
            prev_corner = corner
            T.append(f["t"])
            feats.append([d("tube", "idle"), d("tube", "dwell"), d("nest", "tool"), d("nest", "idle"), d("right", "fwd"),
                          d("right", "idle"), d("ladder", "idle"), cb, cm])
        return np.array(T), np.array(feats)

    def detect(self, frames):
        TT, X = self.features(frames)
        if len(TT) < 50:
            return []
        ti, td, nt, ni, rf, ri, li, cb, cm = X.T
        N = len(TT)

        def first(cond, a, b):
            for k in range(max(a, 0), min(b, N)):
                if cond(k):
                    return k
            return None
        disc, runs, i = td < 30, [], 0
        while i < N:
            if disc[i]:
                j = i
                while j + 1 < N and disc[j + 1]:
                    j += 1
                if j - i + 1 >= 2:
                    runs.append((i, j))
                i = j + 1
            else:
                i += 1
        cyc = []
        for i, j in runs:
            s = i
            while s - 1 >= 0 and ti[s - 1] > 17 and td[s - 1] < 38.5 and i - s < 2:
                s -= 1
            e = j + 1
            while e < N and ti[e] > 17 and e - j < 3:
                e += 1
            k = s - 1
            while k - 1 >= 0 and (ni[k] > 7 or li[k] > 7 or ri[k] > 8) and TT[s] - TT[k - 1] <= 2.7:
                k -= 1
            start = k + 1
            est = TT[s] - TT[start] < 1.0
            sp = first(lambda q: rf[q] < 20, start, s + 1)
            tdn = first(lambda q: nt[q] < 12, j, j + 12)
            tup = first(lambda q: nt[q] >= 12, tdn + 1, tdn + 20) if tdn is not None else None
            sf = first(lambda q: rf[q] < 20, (tdn or j), (tdn or j) + 15)
            sb = first(lambda q: rf[q] >= 20, sf + 1, sf + 20) if sf is not None else None
            rest = first(lambda q: ri[q] < 8 and li[q] < 8, sb, sb + 20) if sb is not None else None
            T0 = TT[start] if not est else TT[s] - 1.73
            lo = T0 - 3.3
            if cyc and cyc[-1].get("machine_rest"):
                lo = max(lo, cyc[-1]["machine_rest"] + 0.3)
            h = first(lambda q: TT[q] >= lo and ((cm[q] > 6 and cm[q - 1] < 6) or cb[q] > 0.07),
                      int(np.searchsorted(TT, lo)), int(np.searchsorted(TT, T0 - 0.9)))
            ho = first(lambda q: cm[q] < 6 and cb[q] <= 0.07, h + 1, h + 8) if h is not None else None
            g = lambda q: float(TT[q]) if q is not None else None  # noqa: E731
            cyc.append(dict(load_part=g(h), wait_for_machine_start=g(ho), transfer=float(T0), carriage_short_stroke=g(sp),
                            fr_press_down=g(s), ram_down=g(tdn), carriage_forward=g(sf), ram_up=g(tup), carriage_back=g(sb),
                            machine_rest=g(rest)))
        out = []
        for a, b in zip(cyc, cyc[1:]):
            a = {k: v for k, v in a.items() if v is not None}
            a["start"] = a.get("load_part", a["transfer"] - 2.08)
            a["end"] = b["load_part"] or b["transfer"] - 2.08
            if a["end"] > a["start"]:
                out.append(a)
        return out

    def extra(self, cycles):
        mv = [c["machine_rest"] - c["transfer"] for c in cycles if "machine_rest" in c]
        idle = [c["end"] - c["machine_rest"] for c in cycles if "machine_rest" in c]
        out = []
        if mv:
            out.append(f"The machine runs ~{stat.median(mv):.1f}s per cycle (almost constant), then waits for the operator: "
                       f"median {stat.median(idle):.1f}s, longest {max(idle):.0f}s.")
        return out


# ======================================================================== ymm: Mechanical Movement #2, YRA line (camera 13)
class YMM:
    """YRA SEAT SLIDER, station 20 "Mechanical Movement #2" (camera 13 = 192.168.31.39, overlay YRA_SS_FINAL). The camera sees
    three people; this station is the MIDDLE one (back to the camera, box centre x 0.36-0.50), confirmed by the process owner
    on 2026-10-14; the left person is station 13 "Mechanical Movement" (class YML) and hands him every rail. Watched frame by frame on two 1600x900 videos of 2026-10-14: 14:11:12-14:15:12 (afternoon, teal tray,
    17 cycles, ymm_hd_annotations.json) and 23:26:21-23:30:21 (night, blue bin, 14 cycles, ymm_night_annotations.json).

    Seen in the video, per cycle (median seconds after the pick, afternoon / night):
      the dark rail comes from the left person through the amber INPUT holder at the right end of his machine. Afternoon: the
      left person stands it in the holder and the middle person takes it from there (0). Night: the middle person waits with his
      left glove at the holder and the left person hands the rail to him glove to glove (0) -> rail lifted and laid on his
      fixture (0.9 / 0.6) -> right hand into the clear plastic guard at the right end of the fixture (2.5 / 1.6) -> left side:
      afternoon he bends left with the head down, night he lifts a small black part with the left hand to head height (3.4 / 2.6)
      -> both hands at the fixture in front of him, hidden by his body (4.6 / 4.0) -> lifts the finished rail out to the right
      and puts it into the OUTPUT holder at the right person's left (afternoon an amber holder, night a brown rack), lets go
      (11.6 / 8.9) -> back to the input holder; if no rail is there yet he waits (afternoon 4 of 17 cycles, night 11 of 11).
    After midnight (video 2026-10-15 01:23:30-01:27:30, ymm_late_annotations.json, 15 cycles) the middle person wears a
    blue cap and glasses; he takes the rail from the input holder himself (the left person's hand comes to the holder 1-3 s
    later), lifts it upright with the left glove 0.5-0.7 s after the take, and the drop into the output holder is hidden
    behind his body and the right person.
    In the grey-box layout (video 2026-10-15 02:30:49-02:34:49, ymm_grey_annotations.json, 15 cycles) his work is the same;
    the left person hands him the rail at the input holder glove to glove in most cycles (~13.5 s apart).
    """
    key, cams, station_id, title = "ymm", (13,), 20, "Mechanical Movement #2 (YRA)"  # middle person; station 20 since 2026-10-15
    STAND = (0.318, 0.56, 0.345, 0.69)   # input holder patch: rail standing in it = dark; hand / rail passing = motion
    M_CX = (0.33, 0.53)                  # the middle person's box centre x
    PICK_X, PICK_Y = 0.365, 0.485        # his left wrist at the input holder (low, at the holder: not at the fixture end)
    PICK_REL = -0.075                    # ... or his left wrist this far left of his left hip, with a hand burst at the holder
    MERGE = 9.0                          # holder visits closer than this are one take (no real cycle was shorter than 10 s)
    HOLD_MERGE = 10.0                    # a take not lifted within 2.5 s and followed by another within this = one rail
    FILL_REL, FILL_GAP = -0.05, 0.6      # holder burst with his left wrist not stretched to it (wrist - hip x > -0.05) = the left
                                         # person putting the next rail in (at least 0.6 s before the next take)
    HAND_MOT = 30.0                      # holder patch frame-to-frame change: a hand / rail passes (pick or hand-over)
    RUN_GAP = 0.3                        # motion frames closer than this are one burst
    LIFT_DX = 0.03                       # rail lifted: his left wrist this far right of the holder line
    MAX_CYCLE = 60.0
    LEAN, UPRIGHT = -0.022, -0.016       # shoulder-mid minus hip-mid x: bent left / upright again
    RAISE_Y, DOWN_Y = 0.42, 0.46         # left wrist raised (small black part at head height) / back down
    OUT_X, SWING = 0.51, 0.3             # right wrist at the output holder; the swing from the fixture takes ~0.3 s
    DARK_SHARE = 0.4                     # holder threshold between its dark (rail in) and bright (empty) levels
    WAIT_MIN = 0.5                       # next rail more than this after he let go = he waited (the cue is ~0.25 s late)
    ORDER = [("PICK", "pick_rail"), ("LOAD", "load_rail"), ("RIGHT", "right_end"), ("LEAN", "lean_left"), ("WORK", "upright"),
             ("OUT", "take_out"), ("DROP", "drop"), ("WAIT", "wait_rail"), ("BACK", "to_stand")]
    NAMES = {
        "PICK": ("Take the rail at the input holder (left)", "#16a34a"),
        "LOAD": ("Lay the rail on his fixture", "#0891b2"),
        "RIGHT": ("Right hand into the clear guard (right end)", "#7c3aed"),
        "LEAN": ("Left side: bend left / small black part", "#a855f7"),
        "WORK": ("Both hands at the fixture (hidden)", "#2563eb"),
        "OUT": ("Lift the finished rail out to the right", "#f59e0b"),
        "DROP": ("Put the rail into the output holder (right)", "#be185d"),
        "WAIT": ("Wait for the next rail from the left person", "#dc2626"),
        "BACK": ("Back to the input holder", "#94a3b8"),
    }
    METHOD = [
        "Operator: the middle person (box centre x 0.33-0.53, standing, top above y 0.40), followed from frame to frame; the "
        "live operator pick (op) is not used.",
        "Cycle: rail taken → next rail taken. A visit = his left wrist at the input holder (x < 0.365, y > 0.485); visits less "
        "than 8 s apart are one. The take = the first hand burst at the holder patch (frame-to-frame change > 30) around the "
        "visit: in the afternoon his own reach (the rail was standing there), at night the hand-over from the left person "
        "(he waits with his glove next to the holder; the pose shows the wrist there only at the hand-over).",
        "Waiting for the next rail counts from the moment he let go of the last one until the next rail is there: put into the "
        "holder by the left person (a hand burst, then the holder patch stays dark; dark / bright levels found from the window "
        "itself), or handed over glove to glove at the next take.",
        "Lay on the fixture: the holder turns bright (rail out) or his left wrist leaves the holder · right end: right wrist "
        "y < 0.42 or right elbow y < 0.43 · left side: shoulders 0.022 left of the hips, his right ear hidden, or his left wrist "
        "raised above y 0.42 · back to work: shoulders over the hips with the right ear visible, or the raised wrist back below "
        "0.46 · drop: the last stay of his right wrist at the output holder (x > 0.51) before the next take; its end = he lets "
        "go; the lift-out starts 0.3 s before the drop.",
        "Checked against 17 afternoon cycles (teal tray, 14:11-14:15) and 10 night cycles (blue bin, 23:28-23:30) annotated frame "
        "by frame on full-resolution video: all found; take, lay, right end, left side within 0.1-0.2 s (median). At night the "
        "right person often stands in front of the output holder: the drop is found in 8 of 10 night cycles. After midnight "
        "(01:23-01:27, other people at the same places): 15 of 15 annotated cycles found, take within 0.08 s (median, max 0.7 s). "
        "Grey-box layout (02:30-02:34): 15 of 15, take within 0.14 s (median, max 0.9 s); one take was lost to dropped "
        "frames in the recording (02:34:36).",
    ]
    UNSEEN = ["What he does with both hands at the fixture (hidden by his body, ~4-6 s): most likely the mechanical movement "
              "check itself.",
              "What is inside the clear guard at the right end of the fixture; what the small black part is (night).",
              "At night the right person often stands in front of the output holder, so the drop is not always visible; after "
              "midnight the drop is hidden in almost every cycle, so the drop / wait times of that hour are estimates.",
              "Whether a rail is ever rejected: no reject bin was seen."]

    # ------------------------------------------------------------------ features
    def features(self, frames):
        rows, last, prev = [], None, None
        for f in frames:
            img = read_frame(f)
            lv = mo = NAN
            if img is not None:
                g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                r = roi(g, self.STAND).astype(np.float32)
                lv = float(r.mean())
                if prev is not None and prev.shape == r.shape:
                    mo = float(np.abs(r - prev).mean())
                prev = r
            cand = []
            for p in f["p"]:
                b = p.get("b")
                if not b or not p.get("k"):
                    continue
                cx, top, h = (b[0] + b[2]) / 2, b[1], b[3] - b[1]
                if self.M_CX[0] <= cx <= self.M_CX[1] and top < 0.40 and h > 0.40:
                    cand.append((abs(cx - last) if last is not None else abs(cx - 0.43), p, cx))
            row = [f["t"], lv, NAN, NAN, NAN, NAN, NAN, NAN, NAN, NAN, mo, NAN]
            if cand:
                _, p, cx = min(cand, key=lambda c: c[0])
                last = cx
                k = p["k"]
                kp = lambda j, c, th=0.3: k[j][c] if k[j][2] > th else NAN  # noqa: E731
                shm = (kp(5, 0) + kp(6, 0)) / 2
                hipm = (kp(11, 0) + kp(12, 0)) / 2
                row = [f["t"], lv, cx, kp(9, 0), kp(9, 1), kp(10, 0), kp(10, 1), kp(8, 1), shm - hipm, kp(4, 0) - shm, mo,
                       kp(9, 0) - kp(11, 0)]
            rows.append(row)
        return np.array(rows, float)

    @staticmethod
    def levels(lv):
        """Two-level split of the holder patch (rail in = dark, empty = bright); None if the two levels are not apart."""
        v = lv[~np.isnan(lv)]
        if len(v) < 50:
            return None
        lo, hi = np.percentile(v, [2, 90])
        v = v[(v >= lo) & (v <= hi)]
        best = None
        for thr in np.linspace(lo + 1, hi - 1, 60):
            a, b = v[v < thr], v[v >= thr]
            if len(a) < 10 or len(b) < 10:
                continue
            sc = len(a) * len(b) * (b.mean() - a.mean()) ** 2
            if best is None or sc > best[0]:
                best = (sc, a.mean(), b.mean())
        if best is None or best[2] - best[1] < 8:
            return None
        return best[1], best[2]

    # ------------------------------------------------------------------ detection
    def detect(self, frames):
        A = self.features(frames)
        if len(A) < 50:
            return []
        T, lv, cx, Lx, Ly, Rx, Ry, Rey, lean, earR, mo, Lrel = (A[:, j] for j in range(12))
        n = len(T)
        lev = self.levels(lv)

        def first(a, b, cond):
            for i in range(max(a, 0), min(b, n)):
                if cond(i):
                    return i
            return None

        def mid(i):
            return (T[i - 1] + T[i]) / 2 if i > 0 and T[i] - T[i - 1] < 1.0 else T[i]
        # hand bursts at the holder patch (onset index, end index)
        hot = np.nan_to_num(mo) > self.HAND_MOT
        bursts, i = [], 0
        while i < n:
            if hot[i]:
                j = i
                while j + 1 < n and (hot[j + 1] or (j + 2 < n and hot[j + 2] and T[j + 2] - T[j] <= self.RUN_GAP + 0.25)):
                    j += 1
                bursts.append((i, j))
                i = j + 1
            else:
                i += 1
        # visits: his left wrist at the input holder (low, and left of the holder line, or stretched out to the left of his hip
        # while a hand burst at the holder shows a rail moving); one per MERGE s
        low = np.nan_to_num(Ly) > self.PICK_Y
        burst_near = np.zeros(n, bool)
        for b0, b1 in bursts:
            burst_near[max(0, b0 - 3):b1 + 4] = True
        at_stand = low & ((np.nan_to_num(Lx, nan=9) < self.PICK_X) | ((np.nan_to_num(Lrel, nan=9) < self.PICK_REL) & burst_near))
        visits = []
        for q in range(n):
            if at_stand[q] and (not visits or T[q] - T[visits[-1]] > self.MERGE):
                visits.append(q)
        # holder state: 1 rail in (dark), -1 empty (bright), 0 hand / unknown
        if lev is not None:
            dark, bright = lev
            thr = dark + self.DARK_SHARE * (bright - dark)
            st = np.where(np.isnan(lv), 0, np.where(lv < thr, 1, np.where(lv <= bright + 6, -1, 0)))
        else:
            st = np.zeros(n, int)
        full = np.zeros(n, bool)          # rail standing in the holder: dark for at least 3 frames (an arm passing is shorter)
        for q in range(2, n):
            if st[q] == 1 and st[q - 1] == 1 and st[q - 2] == 1:
                full[q - 2:q + 1] = True
        self.stand_ok = lev is not None
        # the take in each visit: the last hand burst at the holder before the rail is lifted
        picks = []
        for v in visits:
            # lift: his left wrist leaves the holder towards the fixture
            s = v
            while s - 1 > 0 and (np.isnan(Lx[s - 1]) or Lx[s - 1] < self.PICK_X + 0.01) and T[v] - T[s - 1] < 1.5:
                s -= 1
            t0 = T[s - 1] if s > 0 else T[s]
            # the take: the first hand burst at the holder around the visit (his reach, or the hand-over at night)
            bs = [b for b in bursts if t0 - 0.3 <= T[b[0]] <= T[v] + 1.0]
            if bs:
                picks.append((max(t0, mid(bs[0][0])) if T[bs[0][0]] > t0 else mid(bs[0][0]), v, bs[0][0]))
            else:
                picks.append((t0, v, None))
        # a rail taken but kept at the holder (not lifted within 2.5 s) and lifted at the next visit is one take
        lifted = lambda q: ok(Ly[q], Lx[q]) and ((Ly[q] < 0.50 and Lx[q] > self.PICK_X - 0.005) or Lx[q] > self.PICK_X + self.LIFT_DX)  # noqa: E731
        kept = []
        for p in picks:
            if kept and p[0] - kept[-1][0] < self.HOLD_MERGE:
                v0 = kept[-1][1]
                if first(v0, int(np.searchsorted(T, kept[-1][0] + 2.5)), lifted) is None:
                    continue
            kept.append(p)
        picks = kept
        cyc = []
        for k_, ((tp, s, bq), nxt) in enumerate(zip(picks, picks[1:] + [None])):
            if nxt is None:
                break
            tb, s2, _ = nxt
            b = s2                                   # next visit start (index)
            if tb - tp > self.MAX_CYCLE:
                continue
            a = int(np.searchsorted(T, tp))
            av = max(a, s)                            # his wrist is at the holder from here
            c = {"start": tp, "pick_rail": tp}
            # rail out of the holder: holder turns empty after a full state, else his left wrist leaves the holder (up to the
            # fixture, or to the right)
            was_full = self.stand_ok and bool(full[max(0, a - 6):a + 2].any())
            q_out = first(a, n, lambda q: q > a and st[q] == -1 and st[q - 1] != 1) if was_full else None
            q_up = first(av, n, lambda q: ok(Ly[q], Lx[q]) and ((Ly[q] < 0.50 and Lx[q] > self.PICK_X - 0.005)
                                                                 or Lx[q] > self.PICK_X + self.LIFT_DX))
            cands = [q for q in (q_out, q_up) if q is not None and T[q] - tp < 3.0]
            ld = min(cands) if cands else None
            if ld is not None:
                c["load_rail"] = mid(ld)
            a2 = ld if ld is not None else a + 3
            end_i = int(np.searchsorted(T, tb))
            rq = first(a2, end_i, lambda q: T[q] - tp < 7.0 and ((ok(Ry[q]) and Ry[q] < 0.42) or (ok(Rey[q]) and Rey[q] < 0.43)))
            if rq is not None:
                c["right_end"] = mid(rq)
            a3 = rq + 1 if rq is not None else a2 + 3
            # left side: shoulders left of the hips, his right ear hidden (head turned down to the left) for 2 frames, or the
            # left wrist raised (small black part at head height)
            ear_off = lambda q: q + 1 < n and np.isnan(earR[q]) and np.isnan(earR[q + 1])  # noqa: E731
            raised = lambda q: ok(Ly[q], Lx[q]) and Ly[q] < self.RAISE_Y and Lx[q] > self.PICK_X + 0.01  # noqa: E731
            lq = first(a3, end_i, lambda q: T[q] - tp < 8.0 and ((ok(lean[q]) and lean[q] < self.LEAN) or ear_off(q) or raised(q)))
            if lq is not None:
                c["lean_left"] = mid(lq)
                up = lambda q: ok(lean[q], earR[q]) and lean[q] > self.UPRIGHT and earR[q] > 0.008  # noqa: E731
                down = lambda q: ok(Ly[q]) and Ly[q] > self.DOWN_Y  # noqa: E731
                if raised(lq):
                    uq = first(lq + 1, end_i, lambda q: down(q) and q + 1 < n and down(q + 1))
                else:
                    uq = first(lq + 1, end_i, lambda q: up(q) and q + 1 < n and up(q + 1))
                if uq is not None:
                    c["upright"] = mid(uq)
            # take-out, drop, let go: the last run of the right wrist at the output holder before he goes back to the
            # input holder (the next visit)
            a4 = int(np.searchsorted(T, c.get("upright", c.get("lean_left", tp + 4.0)) + 1.5))
            far = [q for q in range(a4, end_i + 1) if ok(Rx[q]) and Rx[q] > self.OUT_X]
            runs_r = []
            for q in far:
                if runs_r and T[q] - T[runs_r[-1][-1]] <= 0.65:
                    runs_r[-1].append(q)
                else:
                    runs_r.append([q])
            if runs_r:
                run = runs_r[-1]                         # the last stay at the output holder before the next take
                c["drop"] = mid(run[0])
                c["take_out"] = c["drop"] - self.SWING
                c["release"] = min(T[run[-1]] + 0.1, tb)
            rel = c.get("release")
            # next rail available: put into the holder by the left person (a hand burst, then the patch stays dark), or
            # handed over at the next take (night); if neither is seen, the first hand burst shortly before the next take
            t_fill = None
            a5 = max(int(np.searchsorted(T, T[a2] + 0.6)), a + 1)
            if self.stand_ok:
                f0 = first(a5, end_i + 1, lambda q: full[q] and any(T[q] - 2.0 <= T[b0] <= T[q] + 0.3 for b0, _ in bursts))
                if f0 is not None:
                    z = f0
                    while z - 1 > a5 and st[z - 1] != -1:
                        z -= 1
                    t_fill = mid(z)
            # a hand burst at the holder while his own left hand is away from it = the left person putting the next rail in
            away = lambda q: not (ok(Ly[q]) and Ly[q] > self.PICK_Y and ((ok(Lx[q]) and Lx[q] < self.PICK_X)  # noqa: E731
                                                                         or (ok(Lrel[q]) and Lrel[q] < self.FILL_REL)))
            fb = [b0 for b0, b1 in bursts if a5 <= b0 and T[b0] < tb - self.FILL_GAP and all(away(q) for q in range(b0, min(b1 + 1, n)))]
            if fb:
                t_fill = mid(fb[0]) if t_fill is None else min(t_fill, mid(fb[0]))
            if t_fill is None:
                bb = [b0 for b0, _ in bursts if a5 <= b0 and tb - 1.5 <= T[b0] <= tb + 0.05]
                t_fill = min(mid(bb[0]), tb) if bb else tb
            c["stand_filled"] = min(t_fill, tb)
            if rel is not None and c["stand_filled"] > rel + self.WAIT_MIN:
                c["wait_rail"] = rel
                c["to_stand"] = c["stand_filled"]
            elif rel is not None:
                c["to_stand"] = rel
            c["end"] = tb
            for key in [x for _, x in self.ORDER] + ["release", "stand_filled"]:
                if key in c and c[key] is not None and c[key] > tb:
                    c[key] = tb
            cyc.append(c)
        self.picks = [p[0] for p in picks]
        return cyc

    def extra(self, cycles):
        out = []
        w = [c["to_stand"] - c["wait_rail"] for c in cycles if "wait_rail" in c and "to_stand" in c]
        if cycles:
            out.append(f"Waited for the next rail from the left person in {len(w)} of {len(cycles)} cycles"
                       + (f" (median {stat.median(w):.1f}s, {100 * sum(w) / max(1e-6, sum(c['end'] - c['start'] for c in cycles)):.0f}% "
                          f"of the time)." if w else "."))
        work = [c["release"] - c["start"] for c in cycles if "release" in c]
        if work:
            out.append(f"Work per rail (rail taken → rail left in the output holder) median {stat.median(work):.1f}s.")
        return out


# ======================================================================== yfi: Pop Rivet Gun + Final Inspection, YRA line (camera 13)
class YFI:
    """YRA SEAT SLIDER, stations 11 "Pop Rivet Gun" and 21 "Final Inspection m/c": both are worked by the RIGHT person (cap
    with a yellow badge, near the camera, box centre x > 0.50), who takes every rail from the Mechanical Movement #2
    operator. Camera 11 is the same camera as 13 (192.168.31.39) and is not recorded, so this runs on the camera-13
    recording. Watched frame by frame on the 1600x900 videos of 2026-10-14 14:11:12-14:15:12 (teal grid tray, 15 rails,
    yfi_hd_annotations.json) and 23:26:21-23:30:21 (blue bin with liner and white separators, 12 rails,
    yfi_night_annotations.json). At night the rail is laid flat into the separators of a blue bin; every ~5 rails he puts a
    new empty bin with a liner on top (~5 s), and changes the stack.
    The "shelf" at the top-left of his machine is the pop rivet station (seen when he was away, 2026-10-15 01:24): a blue
    pneumatic rivet tool with an air hose on a holder at a vertical cylinder, a black rail nest below it, a yellow safety
    light curtain at its right, and bins and a tray of small parts in front. The machine below / right of it, where the
    rail goes next, is the Final Inspection m/c.

    Seen in the video, per rail (median seconds after the take):
      takes the rail from the amber output holder at his left, back to the camera (0) -> turns to the pop rivet station and
      holds the rail end in the nest under the rivet tool; a small white object with a pink tip in his right fingers at the
      rail end (most likely the rivet; too small to be sure) (0.4) -> lays the rail into the lower fixture of the Final
      Inspection machine with both hands (1.6) -> lifts it out again (2.7) -> holds it up in front of him and turns it,
      looking at it (in-hand check after the machine) -> stands it into a cell of the teal grid tray in front of him
      (5.3) -> hands at his chest, turns back to the holder (7.6) -> waits for the next rail (3.3 s median).
    After midnight (video 2026-10-15 01:23:30-01:27:30, 16 rails, yfi_late_annotations.json) the same steps are done by a
    person who stands upright at the shelf: back to the camera at the shelf at the top-left of his machine for 6-8 s (the
    hand-over and the in-hand check are hidden), then he turns and leans right and puts the rail into the lower fixture
    with both hands, takes it out after 1.3-1.6 s, lays it into the blue bin 0.6-1.2 s later, and turns back to the shelf
    ~0.5 s after his hands leave the bin. Every 5 rails he puts a new empty bin with a liner on top (4-5 s). In long
    stretches his legs are hidden behind the bin, so his person box ends at y 0.62-0.70 and the old rule (box bottom below
    0.70) lost him: half of his rails were missed. Now: box bottom below 0.62, and the fixture is also found from image
    motion in the fixture area, which does not depend on the person detection or on how he stands.
    From ~02:07 on 2026-10-15 the blue bin is gone (video 02:30:49-02:34:49, 16 rails, yfi_grey_annotations.json): grey
    boxes stand in front of the camera (bottom middle and right of him) and the finished rails go one by one, upright,
    into the cells of a blue grid tray with orange cells at the bottom edge of the picture. He faces the camera at his
    machine: hands at the lower fixture (~1.3 s), rail out and held at his waist, looking at it (~2.6 s), then he bends
    and stands it into the tray (~1.5 s). Often he does two rails one after the other (the second ~6 s after the first)
    and then waits with his hands down. The rails look the same (black); whether it is another model cannot be seen.

    Pop rivet gun (step 11) and the two rail variants, watched on 2026-10-19 (640 recording 08:30-13:20, frame by frame
    around 08:50, 09:00-09:05, 09:20, 10:10-10:50, 10:57, 11:02-11:05, 11:40-11:46, and the 1600 px video
    cam13_hd_20261019_1200.mp4, 11:57:41-12:03:41):
      INNER rails are riveted: after the take he stands at the shelf with his back to the camera, his right arm up at the
      blue pop rivet gun (light-blue air hose) for ~4-6 s (median 4.5 s), then turns and loads the Final Inspection
      machine; take to load (RIVET element) 6-7 s.
      OUTER rails are not riveted (step 11 is not used): the rivet station is covered (a blue tray with a black or blue bag
      on it, 08:30-10:17), he only marks the rail with a white pen at the shelf (~1-2 s, MARK element) and loads it.
    The riveting is done by the right person himself (no separate person): his cap is two-tone, a dark navy crown and a
    light-blue front with the yellow badge, so from behind at the shelf it looks dark; in the same continuous frames he
    turns round with the rail at 11:05:04.4. Between 10:28 and 10:39 a helper in a dark polo and visitors stood next to
    him, but the helper did not rivet.
    2026-10-19: outer until 10:20; changeover 10:17-10:32 (a helper took the covered tray off the station and put an open
    tray of parts there at 10:17:17-10:17:37; trial rails and visitors; first riveted rail 10:25:41); inner from 10:25
    (steady from 10:32) to at least 13:20. Earlier videos: 2026-10-14 afternoon and night, 2026-10-15 02:30 (grey boxes)
    and 2026-10-17 16:12 were outer (no gun use; the ~1-2 s at the shelf was the pen mark), 2026-10-15 01:23 was inner
    (all 16 rails riveted, ~3.9 s at the gun).
    Every cycle from analyse() carries c["rivet"] (bool; False = outer rail, step 11 not used for it), c["rivet_seen"]
    (the gun use itself was seen), c["rivet_sec"] / c["rivet_t0"] / c["rivet_t1"] (rivet time: his arm at the gun) and
    c["variant"] ("inner" / "outer"). See _rivet.

    Bin layouts and the count (2026-10-19): the layout rules above find a rail from its bin / tray cue. When the bin in
    front of him changed they lost rails: in the morning (outer rails; a grey box with an orange grid tray at the bottom
    edge, from 09:11:40 a large orange grid tray right in front of him) the grey-layout check switched on and off and the
    old rules counted 18 of 44 rails in 09:10-09:20; from ~15:20 a GREEN grid bin stands in front of him, which is neither
    blue nor orange, so it was taken for the grey-box layout and the bottom-edge tray rule found almost nothing (0 of 39
    rails, 15:26-15:38). The partner check then dropped whole 10-minute blocks. The load into the Final Inspection
    fixture looks the same in every layout, and every rail comes from the middle person: since 2026-10-19 the rails are
    the fixture loads paired one to one, in order, with the Mechanical Movement #2 releases (see pair_rails in detect);
    the layout rules only add evidence and the element times. Checked frame by frame on 2026-10-19 09:09-09:19 (43 outer
    rails, orange grid tray, yfi_day1019am_annotations.json) and 15:26-15:38 (39 inner rails, green bin,
    yfi_day1019green_annotations.json).

    Count check against the final machine's own counter, 2026-10-21 13:05-16:05 (645 parts; the live feed stored 597 rails,
    -7%; camera 13 had no gaps then; 640 recording saved in data/validation_recordings_yfi1021). Layouts that afternoon: a dark
    grey box in front of him (13:00-13:10, 13:38-14:08, ~14:50-15:00; the layout check calls it grey), the teal grid tray
    (13:10-13:37, 14:10-14:45), a green grid tray (15:05-15:20) and a blue bin with a liner (15:30-16:05). Two kinds of loss:
      - the live feed (app/services/detector_feed.py) keeps the cycles of a run that start after the previous run's window
        and end inside this one; the cycle of the last rail of a run ends with the next take, after the window, so it was
        stored by neither run: one rail per 5-minute run (~11 per hour, the stored cycles have a hole at every run). Fixed in
        the feed: it keeps a run's cycles from the end of the newest cycle found before, so that cycle is stored whole by the
        next run. (OPEN_LAST = 1 would instead keep the last rail as an open cycle up to the window end, c["open"].)
      - the release pairing: in the dark box layout (checked rail by rail, 13:38-13:54, yfi_day1021_annotations.json) it
        found 53 of 65 rails. Two rails often come close together: he puts one away and takes a second one out of the
        fixture right after it (twice in that stretch without a new load: the machine held two rails), or loads the next
        within ~6 s; the Mechanical Movement #2 rules then see one release, and the pairing drops the rail. It also used
        releases for fixture visits that were no rail (pen work at the machine, a hand at the fixture while talking), and
        a rail left ~12 s in the fixture (13:46:58) was paired late. There his put into the box is clear: he bends (shoulders
        below their usual height) and a wrist goes below y 0.80; each put is one rail (bin_put_rails in detect, "put mode",
        only where the layout check says grey and most paired rails around have their put seen). The puts are not used
        with the teal / green trays and the blue bin, where his hands often stay above y 0.80 (put seen for only 35-65% of
        the paired rails).
    Result on the saved recording (offline, one run per hour): 235 / 183 / 231 rails in 13:05-14:05 / 14:05-15:05 /
    15:05-16:05 against the machine's 228 / 182 / 235 (649 against 645); the live feed (simulated 5-minute runs, four run
    phases): total 636-644 (-1.4% to -0.2%). The set 13:38-13:54: 64 of 65 rails, 3 extra (before: 53, 4 extra).
    """
    key, cams, station_id, title = "yfi", (13,), 21, "Pop Rivet Gun + Final Inspection (YRA)"  # right person: stations 11 + 21
    also_cameras = (11,)  # filed under the Pop Rivet Gun step too (its camera 11 = same physical camera)
    R_CX, R_CX_MAX = 0.50, 0.76    # the right person: box centre x between these
    R_BOTTOM = 0.62                # ... and box bottom below this (0.70 before: after midnight his legs are often hidden by
                                   # the bin, box bottom 0.62-0.70)
    MACH_CX, MACH_PEAK = 0.655, 0.675  # rail in the machine fixture: he leans right, body centre x right of 0.655 (peak 0.675)
    MACH_MIN = 0.35                # shortest machine run (s)
    MACH_GAP = 0.9                 # frames without the cue up to this keep a machine run going (pose drop-outs)
    MACH_WX = 9.0                  # or: both wrists right of this (off when 9)
    TRAY_SUM = 0.0                 # a tray visit needs at least this much summed motion (a hand only touching the bin is less)
    GROUP_BY_BIN = 1               # 1: machine runs without a bin visit in between are one rail; 0: one rail per ymm drop
    NEW_RAIL_GAP = 8.0             # a machine run this long after the last one is a new rail even without a ymm drop
    TRAY = (0.48, 0.70, 0.80, 1.0)  # the teal tray in front of him
    TRAY_ON, TRAY_EDGE = 0.05, 0.03  # share of moving pixels in the tray area: hand + rail going in / visit continues
    TRAY_SKIP = 1.2                # look for the tray visit from 1.2 s after the rail came out
    TRAY_LEAD, TRAY_TAIL = 0.4, 0.6  # the rail starts down 0.4 s before the motion; the motion ends 0.6 s after the hand is out
    TRAY_AFTER = 8.0               # the tray visit follows the machine within this
    FACE_ON, FACE_OFF = 0.5, 0.35  # nose confidence: face turned to the machine / turned away (back to the camera)
    OTHER_A_BENT = 1               # 1: other work before the machine only while bent (0: any delay > AWAY_SEC)
    OTHER_A_TOP = 0.30             # bent before the machine: box top below y 0.30 for BENT_SEC (upright at the shelf: 0.20-0.26)
    BENT_TOP, BENT_SEC = 0.36, 1.0  # other work after the tray: bent low (box top below y 0.36) for 1 s or more
    AWAY_SEC = 2.0                 # other work before the machine: face away for more than 2 s after the take
    TAKE_LEAD = 0.4                # he turns to the machine ~0.4 s after he has the rail
    TAKE_AFTER_BACK = 15.0         # no ymm release since the last rail and the load within this after he turned back:
                                   # the rail was waiting, take = turned back + 0.3 s (0 = off)
    MAX_CYCLE = 60.0
    KEEP_LONG = 1                  # 1: a rail whose next rail comes more than MAX_CYCLE s later is kept (the report marks
                                   # the long cycle as a line stop); 0: left out
    OPEN_LAST, OPEN_MIN = 0, 0.6   # 1: the last rail of the window (taken at least 0.6 s before its end, loaded) is kept as
                                   # an open cycle ending at the end of the window. Off: the live feed now stores the cycle
                                   # going past a run's end with the next run, whole (it lost one per run before 2026-10-21)
    REL_MATCH = 2                  # a rail needs an unused Mechanical Movement #2 release before it (releases taken in
                                   # order): 1 = every rail, 2 = only a grey-layout put without fixture motion before it
                                   # (1 loses rails at night, where the drop into the holder is often hidden), 0 = off
    # image cue that does not depend on how he stands: motion in a small area at the top of the lower fixture of his
    # machine (x 0.70-0.75, y 0.30-0.45) moves only while the rail is put into the fixture and taken out again
    FIX = (0.70, 0.30, 0.75, 0.45)
    FIX_ON = 0.10                  # share of moving pixels in FIX
    FIX_GAP = 0.5                  # frames below FIX_ON up to this keep a fixture run going
    FIX_MIN = 0.3                  # shortest fixture run (s); a hand only passing the machine is shorter
    FIX_LEAD = 0.5                 # the rail goes in ~0.5 s before the motion starts; the motion ends when it is out
    USE_POSE = 1                   # 1: also use the body-centre machine runs (afternoon / night posture)
    MERGE_GAP = 1.5                # visits with no bin visit in between: merged when this close, else the earlier is dropped
    TRAY_BACK = 1                  # 1: the bin visit starts at the first frame of its motion run (not before the rail is out)
    BIN_CHANGE_SUM = 3.0           # summed bin motion of a new empty bin put on top (a rail alone is 0.3-2.1)
    BIN_CHANGE_MAX = 12.0          # longest bin work followed (s)
    BIN_CHANGE_TRAY = 1.1          # rail in the bin before the bin work starts (s)
    BIN_RAILS = 1                  # 1: also count a clear bin visit with a short fixture look as a rail
    BIN_RAIL_SUM, BIN_RAIL_MAX = 0.6, 0.15  # a clear bin visit (a hand only touching the bin is less)
    BIN_LOOK, BIN_LOOK_MAX = 0.3, 4.0  # fixture motion this long before the bin visit
    BIN_LOAD = 1.2                 # rail in the fixture this long before the last fixture motion
    # grey-box layout (no blue bin; grey boxes in front and a blue / orange grid tray at the bottom edge of the picture)
    LAYOUT_BOX = (0.50, 0.74, 0.76, 0.92)  # blue share here: blue bin 0.35-0.9, grey boxes 0.04-0.1
    LAYOUT_BLUE = 0.20             # below this (median of 10 s steps over LAYOUT_WIN) ...
    LAYOUT_ORANGE = 0.25           # ... and orange share below this (big grid tray in front: 0.35-0.46; grey boxes 0.08-0.15) = grey-box layout
    LAYOUT_WIN = 60.0
    LAYOUT_MIN = 180.0             # the grey-box layout must last this long (a bin change at night took ~1 minute)
    BOTTOM = (0.45, 0.91, 0.85, 1.0)  # the grid tray at the bottom edge: his hand puts the rail into a cell
    BOT_ON, BOT_EDGE = 0.05, 0.03  # moving-pixel share there: a burst starts / continues
    BOT_MAX, BOT_SUM = 0.08, 0.25  # a rail put in: peak and summed motion of the burst (legs or a hand passing are less;
                                   # 0.09 lost a put of the day crew, 2026-10-17 16:15:36)
    BOT_MERGE = 3.0                # bursts within this after a put are the same put (hand going in and out)
    GREY_TRAY_LEAD, GREY_TRAY_TAIL = 0.1, 0.8  # rail into the tray this long before the burst / hand out before it ends
    GREY_FIX_MIN, GREY_FIX_MAX = 0.8, 7.0      # the fixture motion ends this long before the put (= rail out)
    GREY_FIX_LEAD = 0.2            # hands at the lower fixture this long before its motion starts
    GREY_CHECK2, GREY_MACHINE = 2.6, 1.3       # without fixture motion: rail out 2.6 s before the put, in 1.3 s before that
    GREY_BACK = 0.3                # standing up again after his hand left the tray
    # rails paired with the Mechanical Movement #2 releases (any bin layout, 2026-10-19): every rail he finishes was let go
    # into the output holder by the middle person first (2-slot holder, no other buffer), so one rail per release, each
    # one a load into the Final Inspection fixture (image motion in FIX) after its release. The bin / tray cues of the
    # layout rules above only add evidence and element times; they no longer decide whether a rail is counted.
    PAIR = 1                       # 1: rails = loads paired with the releases; 0: the layout rules alone (before 2026-10-19)
    PAIR_LAG = -2.0                # a load from 2 s before its release on (the release cue can be late) ...
    PAIR_MIN_WORK = 9.0            # ... or from this long after the middle person took that rail (his shortest work)
    PAIR_HOLD = 14.0               # ... and at most this long after release k+2 (the holder has 2 slots)
    PAIR_WORK = 10.0               # a take with no release and no next take: released this long after it
    PAIR_GAP = 5.0                 # two loads at least this far apart (after a grey-layout put: an estimated load time) ...
    PAIR_GAP_FIX = 6.5             # ... or this before a load seen at the fixture (shortest real cycle seen: 7.2 s)
    PAIR_PEAK, PAIR_FAINT = 0.23, 0.20  # a fixture-motion run with this peak share can be a load; down to 0.20 a faint one
    PAIR_CLEAR_PK, PAIR_CLEAR_DUR = 0.35, 0.5  # a clear fixture visit: peak share and duration (s)
    CAND_GAP = 1.0                 # fixture-motion runs: frames this far apart with no frame between (recording gap) bridged
    CAND_PEAK = 0.4                # ... and a run shorter than FIX_MIN counts if its peak reaches this
    LINK_TOL = 2.0                 # a rail of the layout rules this close to a fixture visit is the same rail (its times kept)
    # rails the release pairing left out, confirmed by the bin (2026-10-21, see bin_put_rails in detect): a put into the bin =
    # his lowest wrist at y 0.80 or lower (frames up to 0.6 s apart bridged) with summed motion 0.3 or more in the lower
    # part of the picture (LOW, from 0.8 s before); an unpaired candidate (any tier) at least 5 s from the rails found
    # counts when a put lies between the rail before and 0.3 s before it, and another 1.5-9 s after it (before the next rail)
    BIN_PUT = 1
    PUT_WY, PUT_BEND, PUT_GAP, PUT_PRE, PUT_LOW = 0.80, 0.035, 0.6, 0.8, 0.3
    PUT_MERGE, PUT_WORK_N, PUT_WORK = 3.5, 3, 6.0
    PUT_MIN, PUT_AFTER, PUT_SEP = 1.5, 9.0, 6.5
    PUT_WIN, PUT_N, PUT_SHARE = 120.0, 6, 0.7
    # preference when candidates compete for the releases (more rails first, then the higher value): a rail of the layout
    # rules at a fixture visit (old) > one with a bin visit but no fixture motion (weak: the old pose rule) > a clear
    # load-like fixture visit (load) > a short or weak one (soft) > a grey-layout put without fixture motion (weakgrey) > a
    # faint fixture visit or a layout-rule rail with neither (faint, weaknotray) > a fixture visit that is not a load (put:
    # never counted)
    PAIR_W = {"old": 1.0, "weak": 0.7, "load": 0.6, "soft": 0.3, "weakgrey": 0.15, "faint": 0.0, "weaknotray": 0.0,
              "put": -1.2}
    # a load looks the same in every layout: he stands at the machine (person box right edge at most x 0.81, wrists at
    # most x 0.80 and one of them up at the fixture, y 0.62 or higher) and the motion reaches the upper part of the
    # fixture area (12% or more); the rail taken out and swung into the bin (arm stretched right / down) does not
    LOAD_X1, LOAD_WX, LOAD_WY, LOAD_UP = 0.81, 0.80, 0.62, 0.12
    FIX_UP = (0.675, 0.30, 0.75, 0.40)  # upper part of the fixture area (a little wider to the left)
    LOW = (0.50, 0.70, 1.0, 1.0)   # the whole lower part of the picture right of the middle person: the bin / tray in front
                                   # of him, wherever it stands (blue / green bin, grid trays, tray at the bottom edge)
    LOW_ON, LOW_EDGE = 0.05, 0.03  # moving share there: the rail and his hand going into the bin / visit continues
    LOW_CHANGE_SUM = 2.0           # summed motion there of a new empty bin put on top
    # self-check against the Mechanical Movement cycles on the same frames
    SC_BLOCK = 600.0               # blocks of 10 minutes of the clock
    SC_TOL, SC_MIN = 0.20, 3       # rails may differ from the ymm cycles by 20% (at least 3) in a block
    SC_SHORT, SC_SHORT_SHARE = 4.0, 0.10  # rail cycles under 4 s are impossible; more than 10% of them = not checked
    # pop rivet gun used (inner rail) or not (outer rail): between the previous rail coming out and this rail going in, he
    # stands at the shelf (navy shirt fills RIV_A, RIV_B at the machine below is not navy) with his right arm up at the gun
    # (navy in RIV_G). Outer rails: at most 0.2 s of this on 326 rails of 5 sets; inner rails 1.3-9 s (median 4.5 s)
    RIV_AREA = (0.54, 0.36, 0.72, 0.68)   # the three regions below lie in here (HSV of this crop only)
    RIV_A = (0.54, 0.40, 0.64, 0.48)      # his back when he faces the shelf
    RIV_B = (0.64, 0.52, 0.72, 0.68)      # his body when he leans into the Final Inspection machine
    RIV_G = (0.64, 0.36, 0.68, 0.40)      # his right arm at the gun / rivet nest
    RIV_A_ON, RIV_B_OFF, RIV_G_ON = 0.5, 0.3, 0.3  # navy shares: at the shelf / not at the machine / arm at the gun
    RIV_WIN = 15.0                 # look back at most this far before the load (and not before the previous rail is out)
    RIV_SEEN = 1.0                 # seconds with his arm at the gun = gun used on this rail
    RIV_GAP = 1.0                  # frames at the gun this close are one run; the run with the most time is the riveting
    RIV_COV = 0.6                  # share of the look-back window with frames (recording gaps: the period decides)
    RIV_VOTE_WIN, RIV_VAR_SEC, RIV_VAR_SHARE = 8.0, 240.0, 0.5  # variant of a rail: rails within 4 min (look-back 8 s or
                                   # more), half of them with the gun used = inner period
    RIV_CLEAR_N, RIV_CLEAR_OUT = 5, 0.1  # an outer period this clear (at most 10% of 5+ rails around with the gun pose):
                                   # a single gun pose there is not riveting (e.g. arms up at the shelf while the bin changes)
    RIV_DROP, RIV_DROP_WIN = 0, 7.5  # 1: in an inner period a "rail" without gun use within 7.5 s of the last rail being out is
                                   # not a rail (false ones 2.4-6.6 s, real inner rails 7.9 s or more after the last one)
    ORDER = [("TAKE", "take"), ("RIVET", "mark"), ("MARK", "pen"), ("OTHER", "other_a"), ("MACHINE", "load"),
             ("CHECK2", "out"), ("BIN", "tray"), ("AFTER", "tray_end"), ("OTHER", "other_b"), ("WAIT", "back")]
    NAMES = {
        "TAKE": ("Take the rail from the output holder", "#94a3b8"),
        "RIVET": ("Pop rivet gun at the shelf (inner rails only; rail end in the rivet nest)", "#0ea5e9"),
        "MARK": ("Pen mark / check before the machine (outer rails: no pop rivet)", "#a78bfa"),
        "MACHINE": ("Final Inspection m/c: rail in the fixture (load → take out)", "#2563eb"),
        "CHECK2": ("In-hand check after the machine (rail held up)", "#ec4899"),
        "BIN": ("Put the rail into the tray (bin)", "#16a34a"),
        "AFTER": ("Hands at chest, turn back", "#a3a3a3"),
        "OTHER": ("Other work (bent low / away / new empty bin)", "#64748b"),
        "WAIT": ("Wait for the next rail", "#dc2626"),
    }
    METHOD = [
        "Operator: the right person (box centre x 0.50-0.76, box bottom below y 0.62 - his legs can be hidden by the bin), "
        "followed from frame to frame.",
        "Rail count (any bin layout, since 2026-10-19): every rail he finishes was let go into the output holder by the "
        "Mechanical Movement #2 operator first (2-slot holder, no other buffer), so each rail is one load into the Final "
        "Inspection fixture paired with one of his releases, in order. Candidate loads: runs of image motion in the fixture "
        "area (x 0.70-0.75, y 0.30-0.45; 10% of the pixels changing, peak 0.20 or more; frame gaps of the recording up to 1 s "
        "bridged) and the rails of the layout rules below. A run is a load only if he stands at the machine (person box right "
        "edge at most x 0.81, wrists at most x 0.80, one wrist at the fixture, y 0.62 or higher) and the motion reaches the "
        "upper fixture area (x 0.675-0.75, y 0.30-0.40; 12%); the rail swung out into the bin is not. Release k may pair with "
        "a load from 2 s before it (or 9 s after the middle person took that rail) to 14 s after release k+2; loads at least "
        "6.5 s apart (5 s after a grey-layout put). A dynamic programme picks the pairing with the most rails, and among those "
        "the strongest candidates: a layout-rule rail at a clear fixture run > a layout-rule rail with a bin visit but no "
        "fixture motion > a clear fixture run (peak 0.35, 0.5 s) > a weak one (peak 0.23) > a grey-layout put without "
        "fixture motion > a faint run (0.20). A release with no load found adds no rail; a load with no release is not a "
        "rail. Element times come from the layout rule's rail where it is the same one (within 2 s), else from the "
        "fixture run (rail in 0.5 s before it starts, out when it ends) and the bin visit = motion in the lower part of the "
        "picture right of the middle person (x 0.50-1.0, y 0.70-1.0) from 1.2 s after the rail came out.",
        "Machine visit (rail in the lower fixture): image motion in the fixture area (x 0.70-0.75, y 0.30-0.45; more than 10% "
        "of its pixels changing, for 0.3 s or more) - rail in 0.5 s before the motion starts, out when it stops; or his body "
        "centre right of x 0.655 for 0.35 s or more (peak 0.675), which then gives the times. Every rail ends in the bin, so "
        "visits with no bin visit in between are one rail (merged when less than 1.5 s apart, else the earlier one was only a "
        "touch); a clear bin visit (summed motion 0.6 or more) with only a short fixture motion before it is also a rail.",
        "Take: the moment the Mechanical Movement operator lets go of the rail in the output holder (ymm rules on the same "
        "frames); if the inspector was still busy then, the moment he turned back + 0.3 s; without a ymm cue, 0.4 s before his "
        "face turns to the machine. The pop rivet step starts when his face turns to the rivet station (nose confidence > "
        "0.5); it ends when the rail goes into the Final Inspection machine. Pop Rivet Gun part of his cycle = take + rivet "
        "(+ other work before the machine) on inner rails only (outer rails: take + pen mark, no step 11); Final "
        "Inspection part = machine + check after it + bin + turn back.",
        "Tray (bin): moving pixels in the tray area (x 0.48-0.80, y 0.70-1.0) from 1.2 s after the rail came out; the rail starts "
        "down 0.4 s before the motion, the hand is out 0.6 s before the motion ends. Face turned away again (nose confidence "
        "< 0.35 in two frames in which he is seen) = back at the holder; from there until the next take is waiting. A bin "
        "visit with summed motion of 3 or more is a new empty bin put on top: the rail goes in first (1.1 s), the bin work is "
        "other work, and he is back after it.",
        "Other work: bent low (box top below y 0.36, or out of sight) for 1 s or more after the tray; before the machine, bent "
        "(box top below y 0.30) for 1 s or more between the take and the machine.",
        "Checked against 15 rails annotated frame by frame on the full-resolution video (2026-10-14 14:11-14:15, teal tray): "
        "15/15 found; load / out / tray start within 0.1-0.15 s (median); and 12 rails at night (23:27-23:30, blue bin with "
        "liners): 10 of the 11 inside the recording found (one with a very short lean missed), one extra (a hand touching "
        "the bin); load / out / tray within 0.2-0.5 s. At night his left hand reaches the rack without turning away, so the "
        "take and the wait are less exact than in the afternoon. Version 3 (fixture-area motion, bin-change rule): afternoon "
        "15/15 unchanged; night 11 of the 11 rails inside the recording (one extra: a hand at the machine before he tidies the "
        "bin); after midnight (2026-10-15 01:23-01:27, upright person) 16/16, load / out within 0.2 / 0.1 s (median), bin "
        "0.3 s, back 0.3 s. After midnight the hand-over and the check at the shelf are hidden (back to the camera), so the "
        "take, the in-hand check and the wait of that hour are estimates.",
        "Layout check: the blue and the orange share of the bin area (x 0.50-0.76, y 0.74-0.92), median per 10 s over a "
        "minute; blue below 0.20 and orange below 0.25 = grey-box layout (a blue bin, the teal tray or the big orange grid tray "
        "in front of him keep the rules above). There one rail = a clear motion burst in the grid tray at the bottom edge (x 0.45-0.85, y 0.91-1.0; "
        "peak 8% of the pixels, summed 0.25; bursts within 3 s are the same rail); rail out = end of the fixture-area motion "
        "0.8-7 s before (else 2.6 s before the tray), in the fixture 1.3 s before that. A put with no fixture motion before "
        "it counts only if the Mechanical Movement #2 operator let go of a rail into the output holder before it that no "
        "other rail has used (releases taken in order; e.g. bent at the box and tray, arranging). Checked against 16 rails "
        "of the video 02:30:49-02:34:49: 15 found (the 16th is the last rail of the recording), tray within 0.13 s, rail out "
        "0.12 s (median); and the day crew 2026-10-17 16:12:47-16:22:47 (yfi_day1612_annotations.json): 39 of 39 rails "
        "(one before an 85 s absence), no extra rail, load / out / tray within 0.12 / 0.12 / 0.13 s (median).",
        "Pop rivet gun (inner rail) or not (outer rail): between the previous rail coming out of the fixture (+0.5 s, at most "
        "15 s back) and this rail going in, he stands at the shelf with his right arm up at the gun: navy (shirt) pixels fill "
        "the shelf area (x 0.54-0.64, y 0.40-0.48; more than 50%), the machine area below (x 0.64-0.72, y 0.52-0.68) is not "
        "navy (under 30%: he is not leaning into the machine) and the gun area (x 0.64-0.68, y 0.36-0.40) is navy (over 30%: "
        "his arm). 1 s or more of this = the gun was used on the rail; the rivet time is the main run at the gun (frames up "
        "to 1 s apart bridged). The variant (inner / outer) of a rail = the majority of the rails within 4 minutes whose "
        "look-back was seen (8 s or more, 60% with frames); a rail whose own look-back is missing (recording gap) takes it. "
        "An outer rail has no Pop Rivet Gun element: its time at the shelf is the pen mark (MARK), and step 11 is not "
        "counted for it. In a clear outer period (5 or more rails around, at most 10% with the gun pose) a single gun pose is "
        "not riveting (2026-10-19 09:12: arms up at the covered shelf while the tray was changed). The earlier rule that "
        "dropped a fixture visit without gun use within 7.5 s of the last rail is off since the release pairing.",
        "Pop rivet check, 2026-10-19 10:11-10:50 (yfi_day1019_annotations.json, 86 rails checked on frame strips): 36/36 "
        "outer and 50/50 inner rails right, no rail lost or added; start / end of the rivet time within 0.2 / 0.5 s "
        "(median of 12 rails read frame by frame; 2.7 / 3.1 s at most while a helper stood next to him). Outer rails of all "
        "six sets show at most 0.2 s of this pose, inner rails 1.3-9 s (median 4.5 s). The look of the station (covered "
        "tray = outer, light-blue hose of the gun visible = inner) agreed with it in 715 of 726 ten-second views with a "
        "clear station on 2026-10-19 (the 11 others: 10:17-10:21, station already cleared, rails still outer), but on "
        "2026-10-15 01:23 he riveted every rail while the hose was never visible, so the station look is not used. The set "
        "was corrected on 2026-10-19 evening on every frame (it listed the old detector's rails only): two rails added "
        "(10:18:56.8 outer, 10:40:00.5 inner) and one load moved (10:40:09.5 -> 10:40:12.6); now 88 rails.",
        "Release pairing, checked 2026-10-19 (frame by frame, 0.5 s contact sheets of the right person): morning outer rails "
        "with the orange grid tray 09:09-09:19, 43/43 found (old rules 2/43 after their self-check, 18 of 44 in 09:10-09:20 "
        "before it), no extra rail, rivet flag 43/43; green bin 15:26-15:38, 37/39 found (old rules 0/39), one extra (his arm "
        "brought down from the top of the machine while he waited, 15:33:43), missed: a load during which he raised his arm "
        "to the top of the machine (15:32:48, taken for a swing-out) and one done left of the fixture area (15:37:33); "
        "the corrected 10:11-10:50 set 87/88 (one load left of the fixture area missed, 10:18:57), no extra; the older sets "
        "unchanged or better (night: the extra rail gone; grey: 16/16).",
        "Puts into the bin (since 2026-10-21): where a dark box stands in front of him (layout check: grey) and his puts "
        "are seen for 70% or more of the paired rails within 2 minutes, each put is one rail. Put = a wrist at y 0.80 or "
        "lower while he bends (shoulders 0.035 or more below their median height in the window; with his arms hanging at "
        "his sides the wrists are at y 0.80-0.88 too), frames up to 0.6 s apart bridged, with summed motion 0.3 or more in "
        "the lower part of the picture right of the middle person (x 0.50-1.0, y 0.70-1.0) from 0.8 s before; puts less than "
        "3.5 s apart are one, and a group of 3 or more or longer than 6 s is bin work (a liner, arranging), no rail. The "
        "rail of a put = the last paired rail 1.5-9 s before it and after the put before (+0.3 s), else the last other "
        "candidate fixture visit there (a load-like one first): this adds the second of two rails close together, whose "
        "release the Mechanical Movement #2 rules did not see. A paired rail with no put 1.5-9 s after it is kept (put "
        "not seen), unless it lies between another rail's load and put, or less than 6.5 s before another rail's load. "
        "Checked rail by rail on 2026-10-21 13:38-13:54 (dark box, 65 rails, yfi_day1021_annotations.json): 64 found, 3 "
        "extra (before: 53 found, 4 extra).",
        "The live feed keeps a run's cycles from the end of the newest cycle found before (since 2026-10-21), so the rail "
        "going past the end of a 5-minute run is stored whole by the next run; before, one rail per run was lost (~11 per hour).",
        "A rail whose next rail comes more than 60 s later (he was away, the line stopped) is kept; the report marks that "
        "long cycle as a line stop.",
        "Self-check: per 10 minutes of the clock the rails are compared with the Mechanical Movement cycles found on the same "
        "frames. A block where they differ by more than 20% (and more than 3) - both the rails and the rails of the release "
        "pairing alone (without the changes of the puts into the bin and the open last cycle) too few or both too many - or "
        "where more than 10% of the rail cycles are "
        "shorter than 4 s, is left out of the statistics and the cycle table and named in the findings (layout not validated). "
        "With the release pairing the rails can no longer outnumber the releases; a block is left out mainly when many "
        "releases found no load (he is hidden, or the fixture is not used).",
    ]
    UNSEEN = ["The rivet itself and the setting stroke: from behind only his raised right arm at the gun (~4.5 s) is seen; "
              "how many rivets are set per rail and whether the gun fires cannot be seen. Inner / outer cannot be read from the "
              "rail; it is read from the gun use. If inner and outer rails were ever mixed one by one, an outer rail inside an "
              "inner period would still be counted as inner when his body hides the gun (not seen so far: the variants came in "
              "blocks).",
              "On outer rails: the white pen mark at the shelf (1-2 s); what is marked cannot be seen at 640 px.",
              "Whether the machine itself checks the rail (a light or screen result): no indicator is visible.",
              "What he does at the grey box at the right foot of the machine and when he bends behind the machine.",
              "Rejected rails: none were seen in the 4-minute video.",
              "After midnight: the hand-over from the Mechanical Movement operator and what he does at the shelf for 6-8 s "
              "(both with his back to the camera); whether part of that time is waiting cannot be seen.",
              "Grey-box layout: where he gets the rail from (the hand-over is not seen), whether the machine holds two rails "
              "(he often takes two out one after the other; on 2026-10-21 twice in 17 minutes a second rail came out of the "
              "fixture without a new load), and whether the product is another model.",
              "Puts into the bin are used only with the dark box in front of him; with the teal / green grid trays and the "
              "blue bin the count still follows the Mechanical Movement #2 releases, which miss ~2-3% of the rails (two rails "
              "close together). A put while talking or arranging the box, right after a fixture touch, can add a rail; a "
              "fixture visit without a rail before a missed put can stay (13:41:27 and 13:46:41 on 2026-10-21).",
              "The rail count follows the Mechanical Movement #2 releases: a release that rule misses (a long cycle of the "
              "middle person, e.g. 2026-10-19 15:26:45-15:27:14) costs one rail, and a release it adds can let a hand at the "
              "fixture count. A load done left of the fixture area, or one during which he raises his arm to the top of the "
              "machine, can be missed; what he does at the top of the machine (button, adjustment) cannot be seen.",
              "Green bin (from 2026-10-19 ~15:20): the bin visit is found from the lower part of the picture; the layout "
              "check still calls it the grey-box layout, so the bin times of that period are less exact."]

    def __init__(self):
        self.ymm = YMM()

    def _navy(self, img):
        """Share of navy (shirt) pixels in the shelf, machine and gun regions (RIV_A, RIV_B, RIV_G)."""
        h, w = img.shape[:2]
        x0, y0, x1, y1 = self.RIV_AREA
        ox, oy = int(x0 * w), int(y0 * h)
        hsv = cv2.cvtColor(img[oy:int(y1 * h), ox:int(x1 * w)], cv2.COLOR_BGR2HSV)
        H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        navy = (H >= 100) & (H <= 125) & (S > 120) & (V >= 40) & (V < 135)
        return [float(navy[int(b[1] * h) - oy:int(b[3] * h) - oy, int(b[0] * w) - ox:int(b[2] * w) - ox].mean())
                for b in (self.RIV_A, self.RIV_B, self.RIV_G)]

    def features(self, frames):
        rows, last, prev, prevf, prevb, tprev = [], None, None, None, None, None
        prevl = tprev_l = prevu = None
        for f in frames:
            img = read_frame(f)
            mv = fm = bm = blue = orange = lm = um = NAN
            nav = [NAN, NAN, NAN]
            if img is not None:
                nav = self._navy(img)
                g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.int16)
                r, rf, rb = roi(g, self.TRAY), roi(g, self.FIX), roi(g, self.BOTTOM)
                if prev is not None and prev.shape == r.shape and f["t"] - tprev < 1.0:  # no difference across a gap
                    mv = float((np.abs(r - prev) > 20).mean())
                    fm = float((np.abs(rf - prevf) > 20).mean())
                    bm = float((np.abs(rb - prevb) > 20).mean())
                prev, prevf, prevb, tprev = r, rf, rb, f["t"]
                ru = roi(g, self.FIX_UP)
                if prevu is not None and prevu.shape == ru.shape and f["t"] - tprev_l < 1.0:
                    um = float((np.abs(ru - prevu) > 20).mean())
                prevu = ru
                rl = roi(g, self.LOW)
                if prevl is not None and prevl.shape == rl.shape and f["t"] - tprev_l < 1.0:
                    lm = float((np.abs(rl - prevl) > 20).mean())
                prevl, tprev_l = rl, f["t"]
                hsv = cv2.cvtColor(roi(img, self.LAYOUT_BOX)[::2, ::2], cv2.COLOR_BGR2HSV)
                blue = float(((hsv[..., 0] >= 85) & (hsv[..., 0] <= 130) & (hsv[..., 1] > 110) & (hsv[..., 2] > 60)).mean())
                orange = float((((hsv[..., 0] <= 22) | (hsv[..., 0] >= 170)) & (hsv[..., 1] > 120) & (hsv[..., 2] > 90)).mean())
            cand = []
            for p in f["p"]:
                b = p.get("b")
                if not b or not p.get("k"):
                    continue
                cx = (b[0] + b[2]) / 2
                if self.R_CX < cx < self.R_CX_MAX and b[3] > self.R_BOTTOM and (b[2] - b[0]) > 0.06:
                    cand.append((abs(cx - last) if last is not None else -b[3], p, cx))
            row = [f["t"], mv, NAN, NAN, NAN, NAN, fm, bm, blue, orange]
            pz = [NAN, NAN, NAN, NAN, NAN]
            if cand:
                _, p, cx = min(cand, key=lambda c: c[0])
                last = cx
                k = p["k"]
                wmin = min(k[9][0], k[10][0]) if k[9][2] > 0.3 and k[10][2] > 0.3 else NAN
                row = [f["t"], mv, cx, p["b"][1], k[0][2], wmin, fm, bm, blue, orange]
                wx = [k[j][0] for j in (9, 10) if k[j][2] > 0.3]
                wy = [k[j][1] for j in (9, 10) if k[j][2] > 0.3]
                shy = [k[j][1] for j in (5, 6) if k[j][2] > 0.3]
                pz = [p["b"][2], max(wx) if wx else NAN, min(wy) if wy else NAN, max(wy) if wy else NAN,
                      float(np.mean(shy)) if shy else NAN]
            rows.append(row + nav + [lm] + pz[:3] + [um] + pz[3:])   # columns 18, 19: his lowest wrist (y), shoulders (y)
        return np.array(rows, float)

    def detect(self, frames):
        A = self.features(frames)
        self.check, self.layout_note = [], ""
        if len(A) < 50:
            return []
        T, mv, cx, top, nose, wmin, fm, bm, blue, orange = (A[:, j] for j in range(10))
        self.nav = A[:, 10:13]
        lown = np.nan_to_num(A[:, 13]) if A.shape[1] > 13 else np.zeros(len(A))
        px1, pwx, pwy = (A[:, j] if A.shape[1] > 16 else np.full(len(A), NAN) for j in (14, 15, 16))
        upn = np.nan_to_num(A[:, 17]) if A.shape[1] > 17 else np.ones(len(A))
        wlow = np.nan_to_num(A[:, 18]) if A.shape[1] > 19 else np.zeros(len(A))
        shy = A[:, 19] if A.shape[1] > 19 else np.full(len(A), NAN)
        sh_up = float(np.nanmedian(shy)) if np.any(~np.isnan(shy)) else NAN   # his shoulders standing upright (y)
        wput = wlow * (np.nan_to_num(shy) >= sh_up + self.PUT_BEND) if ok(sh_up) else np.zeros(len(A))

        def load_like(a, b):
            # he stands at the machine and the motion reaches the upper half of the fixture area (see LOAD_X1)
            mx = lambda v: float(np.nanmax(v[a:b + 1])) if np.any(~np.isnan(v[a:b + 1])) else NAN  # noqa: E731
            x1, wx, wy = mx(px1), mx(pwx), (-mx(-pwy))
            return (not ok(x1) or x1 <= self.LOAD_X1) and (not ok(wx) or wx <= self.LOAD_WX) \
                and (not ok(wy) or wy <= self.LOAD_WY) and float(upn[a:b + 1].max()) >= self.LOAD_UP
        n = len(T)
        mcyc = self.ymm.detect(frames)
        rel = sorted(c["release"] for c in mcyc if "release" in c)

        def first(a, b, cond):
            for i in range(max(a, 0), min(b, n)):
                if cond(i):
                    return i
            return None

        def mid(i):
            return (T[i - 1] + T[i]) / 2 if 0 < i < n and T[i] - T[i - 1] < 1.0 else T[min(i, n - 1)]

        def runs_of(flag, gap, min_len=0.0, min_frames=1):
            out, i = [], 0
            while i < n:
                if flag[i]:
                    j = i
                    while True:
                        k = j + 1
                        while k < n and not flag[k] and T[k] - T[j] <= gap:
                            k += 1
                        if k < n and flag[k] and T[k] - T[j] <= gap:
                            j = k
                        else:
                            break
                    if T[j] - T[i] >= min_len and sum(flag[i:j + 1]) >= min_frames:
                        out.append((i, j))
                    i = j + 1
                else:
                    i += 1
            return out
        def bin_end(ta, lim, max_sec, s=None):
            # last frame of the bin motion run that starts at ta (one quiet frame bridged); s = the bin motion series
            s = mvn if s is None else s
            edge = self.TRAY_EDGE if s is mvn else self.LOW_EDGE
            tb = ta
            while tb + 1 < lim and (s[tb + 1] >= edge or (tb + 2 < lim and s[tb + 2] >= edge)) \
                    and T[tb + 1] - T[ta] < max_sec:
                tb += 1
            return tb
        def nxt_seen(q):
            # the next frame after q in which he is detected (frames where he is not detected are skipped, up to 1 s)
            for r in range(q + 1, n):
                if T[r] - T[q] > 1.0:
                    return None
                if not np.isnan(nose[r]):
                    return r
            return None
        mvn = np.nan_to_num(mv)
        face_on = np.nan_to_num(nose) > self.FACE_ON
        face_off = np.nan_to_num(nose, nan=1.0) < self.FACE_OFF
        cxn = np.nan_to_num(cx)
        at_m = (cxn >= self.MACH_CX) | (np.nan_to_num(wmin) >= self.MACH_WX)
        pose_runs = [(a, b) for a, b in runs_of(at_m, self.MACH_GAP, self.MACH_MIN, 2)
                     if cxn[a:b + 1].max() >= self.MACH_PEAK or np.nan_to_num(wmin[a:b + 1]).max() >= self.MACH_WX]
        fmn = np.nan_to_num(fm)
        fix_runs = runs_of(fmn >= self.FIX_ON, self.FIX_GAP, self.FIX_MIN, 2)
        # a fixture visit is a fixture-motion run and / or a body-centre machine run; overlapping ones are one visit.
        # Times: from the body run when there is one (he leans in as the rail goes in), else from the fixture motion
        # (rail in FIX_LEAD s before it starts, out when it ends)
        ivs = [(T[a] - self.FIX_LEAD, T[b], a, b, "fix") for a, b in fix_runs]
        if self.USE_POSE:
            ivs += [(mid(a), mid(b + 1), a, b, "pose") for a, b in pose_runs]
        ivs.sort()
        visits = []                    # [t_in, t_out, i_first, i_last, has_pose]
        for t0, t1, a, b, kind in ivs:
            if visits and t0 <= visits[-1][1] + 0.3:
                v = visits[-1]
                if kind == "pose":
                    v[0], v[1] = (t0, t1) if not v[4] else (min(v[0], t0), max(v[1], t1))
                    v[4] = True
                elif not v[4]:
                    v[1] = max(v[1], t1)
                v[2], v[3] = min(v[2], a), max(v[3], b)
            else:
                visits.append([t0, t1, a, b, kind == "pose"])
        runs = [(v[2], v[3]) for v in visits]
        vt = {(v[2], v[3]): (v[0], v[1]) for v in visits}
        mvn = np.nan_to_num(mv)
        if self.GROUP_BY_BIN:
            # one machine visit per rail: every rail ends in the bin, so visits with no bin visit before the next visit
            # are the same rail: merged when close (he leans out and back in), else the earlier one was only a touch
            machs, cur = [], None
            for k, (a, b) in enumerate(runs):
                nm = runs[k + 1][0] if k + 1 < len(runs) else n
                if cur and T[a] - T[cur[1]] > self.MERGE_GAP:
                    cur = None
                cur = (cur[0] if cur else a, b)
                if nm >= n or first(b + 1, nm, lambda q: self.TRAY_SKIP <= T[q] - T[b] < self.TRAY_AFTER and mvn[q] >= self.TRAY_ON) is not None \
                        or T[nm] - T[b] > self.NEW_RAIL_GAP:
                    machs.append(cur)
                    cur = None
            if cur:
                machs.append(cur)
            vt.update({m: (vt[next(r for r in runs if r[0] == m[0])][0], vt[next(r for r in runs if r[1] == m[1])][1]) for m in machs})
        else:
            # one machine visit per rail: a new visit needs a rail that the Mechanical Movement operator has put in the holder
            # and that was not used yet; without one, the run is the same rail again (he leans out and back in) and is
            # merged, unless it comes more than NEW_RAIL_GAP s after the last run (a rail drop the ymm rules missed)
            machs, used = [], 0
            for a, b in runs:
                avail = sum(1 for t in rel if t < T[a] - 0.3) - used
                if machs and avail <= 0 and T[a] - T[machs[-1][1]] <= self.NEW_RAIL_GAP:
                    machs[-1] = (machs[-1][0], b)
                    continue
                machs.append((a, b))
                used = max(used + 1, sum(1 for t in rel if t < T[a] - 0.3)) if avail > 1 else used + 1
        # tray visit: the first tray motion from 1.2 s after the rail came out (before that the long rail can swing over the
        # tray while he lifts it), extended while the motion stays above TRAY_EDGE
        pairs = []
        for k, (a, b) in enumerate(machs):
            nm = machs[k + 1][0] if k + 1 < len(machs) else n
            ta = first(b + 1, nm, lambda q: T[q] - T[b] >= self.TRAY_SKIP and T[q] - T[b] < self.TRAY_AFTER and mvn[q] >= self.TRAY_ON)
            tb = None
            if ta is not None:
                t_out = vt.get((a, b), (0, T[b]))[1]
                while self.TRAY_BACK and ta - 1 > b and mvn[ta - 1] >= self.TRAY_EDGE and T[ta - 1] - self.TRAY_LEAD > t_out:
                    ta -= 1             # the bin visit started before the search window: go back to its first frame
                tb = bin_end(ta, nm, 3.0)
                if float(np.sum(mvn[ta:tb + 1])) < self.TRAY_SUM and k + 1 < len(machs):
                    continue                  # only a touch in the bin, no rail put down: not a rail of its own
            pairs.append([a, b, ta, tb, nm])
        # a rail put into the bin with only a very short look into the fixture (no fixture run): a clear bin visit that no
        # rail above explains, with some fixture motion (or body at the machine) in the 4 s before it
        claimed = [(vt.get((p[0], p[1]), (T[p[0]], 0))[0] - 0.5,
                    T[bin_end(p[2], n, self.BIN_CHANGE_MAX)] + 3.0 if p[2] is not None else T[p[1]] + self.TRAY_AFTER)
                   for p in pairs]
        q = 0
        while self.BIN_RAILS and q < n:
            if mvn[q] >= self.TRAY_ON:
                e = bin_end(q, n, 3.0)
                s_, m_ = float(mvn[q:e + 1].sum()), float(mvn[q:e + 1].max())
                if s_ >= self.BIN_RAIL_SUM and m_ >= self.BIN_RAIL_MAX and not any(lo_ <= T[q] <= hi_ for lo_, hi_ in claimed):
                    ev = [i for i in range(max(0, q - 80), q) if self.BIN_LOOK <= T[q] - T[i] <= self.BIN_LOOK_MAX
                          and (fmn[i] >= self.FIX_ON or at_m[i])]
                    if ev:
                        a = b = ev[-1]
                        vt[(a, b)] = (T[b] - self.BIN_LOAD, T[b])
                        pairs.append([a, b, q, e, n])
                        claimed.append((T[q] - 1.0, T[bin_end(q, n, self.BIN_CHANGE_MAX)] + 3.0))
                q = e + 1
            else:
                q += 1
        pairs.sort(key=lambda p: p[0])
        for k in range(len(pairs)):
            pairs[k][4] = pairs[k + 1][0] if k + 1 < len(pairs) else n
        def elements(pairs, vt, s=None):
            # element times of each rail: pairs = [machine first / last index, bin visit first / last index (or None),
            # next rail's first index]; s = the bin motion series (default: the tray area); a pair whose last item is a
            # cycle dict found before is kept as it is (it only sets where the next rail's take is looked for)
            s = mvn if s is None else s
            out_, prev_back, prev_end = [], None, 0
            for p in pairs:
                if isinstance(p[-1], dict):
                    c = p[-1]
                    prev_back = c.get("back")
                    prev_end = int(np.searchsorted(T, c.get("tray_end", c["out"])))
                    out_.append(c)
                    continue
                c = one_rail(p, vt, s, prev_back, prev_end)
                prev_back = c.get("back")
                prev_end = c.pop("_tb")
                out_.append(c)
            return out_

        def one_rail(p, vt, s, prev_back, prev_end):
            a, b, ta, tb, nm = p
            t_in, t_out = vt.get((a, b), (mid(a), mid(b + 1)))
            c = {"load": t_in, "out": t_out}
            if ta is not None:
                c["tray"] = max(T[ta] - self.TRAY_LEAD, c["out"])
                c["tray_end"] = max(T[tb] - self.TRAY_TAIL, c["tray"] + 0.3)
                te = bin_end(ta, nm, self.BIN_CHANGE_MAX, s)
                if float(s[ta:te + 1].sum()) >= (self.BIN_CHANGE_SUM if s is mvn else self.LOW_CHANGE_SUM):
                    # a new empty bin (with a liner) put on top: the rail goes in first, then the long bin work is other work
                    c["tray_end"] = min(c["tray"] + self.BIN_CHANGE_TRAY, c["tray_end"])
                    c["other_b"] = c["tray_end"]
                    tb = te
            else:
                tb = b + 1
            # his own cue: the face turns to the machine (start of the last face-on run before the load, short drop-outs bridged)
            mk = a
            while mk - 1 > 0 and c["load"] - T[mk - 1] < 8.0 and (face_on[mk - 1] or (mk - 2 > 0 and face_on[mk - 2])):
                mk -= 1
            t_turn = mid(mk) if mk < a else c["load"]
            # take: M lets go of the rail in the holder; if R was still busy with the previous rail then, the moment he turned
            # back + 0.3 s; without either (or if they are far before he turns), 0.4 s before he turns to the machine
            lo = T[prev_end] if prev_end else T[0]
            rr = [t for t in rel if lo - 1.5 < t < c["load"] - 0.3]
            t_take = rr[-1] if rr else None
            if t_take is not None and prev_back is not None and t_take < prev_back:
                t_take = prev_back + 0.3
            if t_take is None and prev_back is not None and c["load"] - prev_back < self.TAKE_AFTER_BACK:
                # no release since he finished the last rail: the next rail was already waiting in the holder (the
                # release was before; after midnight the drop is hidden), so he takes it as he turns back
                t_take = prev_back + 0.3
            if t_take is None or t_take > t_turn:
                t_take = t_turn - self.TAKE_LEAD
            t_take = min(t_take, c["load"] - 0.2)
            c["take"] = c["start"] = t_take
            # in-hand check 1 starts when he turns to the machine; if he only turns more than AWAY_SEC after he took the rail
            # (and the take came from M letting go), the time in between is other work
            if t_turn - t_take > self.AWAY_SEC + 0.5 and rr:
                c["mark"] = min(t_take + self.TAKE_LEAD, c["load"])
                if not self.OTHER_A_BENT:
                    c["other_a"] = t_take + self.AWAY_SEC
                else:
                    # other work before the machine only while he is bent low (standing at the shelf of his machine with
                    # his back to the camera is the in-hand check, as he does after midnight)
                    run0 = None
                    for q in range(int(np.searchsorted(T, c["mark"])), int(np.searchsorted(T, c["load"] - 0.3))):
                        if ok(top[q]) and top[q] > self.OTHER_A_TOP:
                            run0 = q if run0 is None else run0
                            if T[q] - T[run0] >= self.BENT_SEC:
                                c["other_a"] = mid(run0)
                                break
                        elif ok(top[q]):
                            run0 = None
            else:
                c["mark"] = max(t_turn, t_take + 0.1) if t_turn - t_take <= self.AWAY_SEC + 0.5 else t_take + self.TAKE_LEAD
            # back: face turned away for 2 frames after the tray; other work = bent low for BENT_SEC before that
            nxt = nm
            bq = first(tb + 1, nxt, lambda q: face_off[q] and nxt_seen(q) is not None and face_off[nxt_seen(q)])
            if bq is not None:
                c["back"] = mid(bq)
            q, run0, end_b = tb, None, (bq if bq is not None else nxt)
            while q < end_b and "other_b" not in c:
                if (ok(top[q]) and top[q] > self.BENT_TOP) or not ok(cx[q]):  # bent low, or so low he is not detected
                    run0 = q if run0 is None else run0
                    if T[q] - T[run0] >= self.BENT_SEC:
                        c["other_b"] = mid(run0)
                        break
                else:
                    run0 = None
                q += 1
            c["_tb"] = tb
            return c

        cyc = elements(pairs, vt)

        def avail_times():
            # when each rail the middle person took was let go into the output holder: his release, else his next take
            # (he lets go before he takes the next rail), else (no next take for long / end of the window) his usual work
            picks = list(self.ymm.picks)
            relof = {round(c["start"], 3): c["release"] for c in mcyc if "release" in c}
            out_ = []
            for k, p in enumerate(picks):
                r = relof.get(round(p, 3))
                nx = picks[k + 1] if k + 1 < len(picks) else None
                if r is None and nx is not None and nx - p <= self.ymm.MAX_CYCLE:
                    r = nx
                if r is None and p + self.PAIR_WORK < T[-1]:
                    r = p + self.PAIR_WORK
                if r is not None:
                    # earliest load: the release cue can be late (hidden drop, his wrist kept at the holder), but he
                    # never lets go sooner than PAIR_MIN_WORK s after his take
                    out_.append((r, min(r + self.PAIR_LAG, p + self.PAIR_MIN_WORK)))
            return sorted(out_)

        def put_events():
            # his hand with a rail going down into the bin / box in front of him (2026-10-21): a wrist at y PUT_WY or lower in
            # the picture while he bends (shoulders PUT_BEND or more below their median height in the window; standing with
            # his arms hanging the wrists are at y 0.80-0.88 too), frames up to PUT_GAP s apart bridged, with motion in the lower part of the picture (LOW, summed from PUT_PRE s before) of
            # PUT_LOW or more (a single frame: twice that). Puts less than PUT_MERGE s apart are one (hand in and out, a second
            # cell); a group of PUT_WORK_N or more, or longer than PUT_WORK s, is bin work (a new liner, arranging), no rail
            runs_ = []
            for a, b in runs_of(wput >= self.PUT_WY, self.PUT_GAP):
                lo_ = int(np.searchsorted(T, T[a] - self.PUT_PRE))
                hi_ = int(np.searchsorted(T, T[b] + 0.3, side="right"))
                s = float(lown[lo_:hi_].sum())
                if s >= self.PUT_LOW and (b > a or s >= 2 * self.PUT_LOW):
                    runs_.append([float(T[a]), float(T[b]), 1])
            out_ = []
            for r in runs_:
                if out_ and r[0] - out_[-1][1] < self.PUT_MERGE:
                    out_[-1][1], out_[-1][2] = r[1], out_[-1][2] + 1
                else:
                    out_.append(list(r))
            self.bin_work = [(p0, p1) for p0, p1, k in out_ if k >= self.PUT_WORK_N or p1 - p0 > self.PUT_WORK]
            return [(p0, p1) for p0, p1, k in out_ if not (k >= self.PUT_WORK_N or p1 - p0 > self.PUT_WORK)]

        def bin_put_rails(sel, cands):
            # every rail ends in the bin, one at a time (load, take out, check, put into the bin; on 2026-10-21 also two rails
            # taken out of the fixture one after the other). Where his puts into the bin are seen reliably (PUT_SHARE of the
            # paired rails within PUT_WIN s have a put PUT_MIN-PUT_AFTER s after them), each put is one rail: the last
            # rail of the pairing between the put before (+0.3 s) and this put (PUT_MIN-PUT_AFTER s before it), else the last
            # other candidate fixture visit there (a load-like one first). A paired
            # rail with no put after it (put not seen) is kept, unless it lies between another rail's load and put, or less
            # than PUT_SEP s before another rail's load (no rail of its own). The release pairing lost the rails whose release
            # the Mechanical Movement #2 rules did not see (two rails close together), and used releases for fixture visits
            # that were no rail (pen work at the machine, a hand at the fixture while talking).
            puts = put_events()
            self.puts = puts
            ps = np.array([p[0] for p in puts]) if puts else np.zeros(0)
            if not len(ps):
                return sel
            st_ = np.array([x["t"] for x in sel])
            nx_ = np.append(st_[1:], 1e18)
            # a paired rail has its put seen: a put PUT_MIN-PUT_AFTER s after it, before the next paired rail (+1 s)
            hp = np.array([bool(np.any((ps > t + self.PUT_MIN) & (ps <= min(t + self.PUT_AFTER, t2 + 1.0))))
                           for t, t2 in zip(st_, nx_)])

            def put_mode(t):
                # only with the dark box / grey layout in front of him (the bin is low: his wrist goes below y 0.80), and
                # where most paired rails around have their put seen
                w = np.abs(st_ - t) <= self.PUT_WIN
                return bool(is_grey(t)) and w.sum() >= self.PUT_N and hp[w].mean() >= self.PUT_SHARE
            pm = {p: put_mode(p) for p in ps}
            order = sorted(cands, key=lambda x: x["t"])
            ct_ = np.array([x["t"] for x in order])
            new, prev_p = [], -1e18
            for p in ps:
                if pm[p]:
                    lo, hi = max(prev_p + 0.3, p - self.PUT_AFTER), p - self.PUT_MIN
                    k = list(np.flatnonzero((ct_ >= lo) & (ct_ <= hi)))
                    paired_ = [i for i in k if order[i]["used"]]     # a rail of the release pairing there: that one
                    good = [i for i in k if order[i]["tier"] != "put"]
                    if paired_ or good or k:
                        new.append((p, order[(paired_ or good or k)[-1]]))
                prev_p = p
            keep = []
            for x in sel:
                own = [p for p in ps if x["t"] + self.PUT_MIN < p <= x["t"] + self.PUT_AFTER]
                if own and any(pm[p] for p in own):
                    continue               # its put is counted (as this rail or a later fixture visit before it)
                if put_mode(x["t"]) and not own:
                    if any(c is not x and c["t"] <= x["t"] <= p + 0.5 for p, c in new):
                        continue           # between another rail's load and put: the same rail
                    if any(0 < c["t"] - x["t"] < self.PUT_SEP for _, c in new):
                        continue           # another rail's load follows too soon and this one has no put
                keep.append(x)
            out_, seen = [], set()
            for x in sorted(keep + [c for _, c in new], key=lambda x: x["t"]):
                if id(x) in seen:
                    continue
                seen.add(id(x))
                if not x["used"]:
                    x["used"], x["rel"], x["bin_put"] = True, None, True
                out_.append(x)
            for x in sel:
                if id(x) not in seen:
                    x["used"], x["dropped_put"] = False, True
            return out_

        def pair_rails(old):
            # candidate loads: fixture-motion runs (any layout; recording gaps of up to CAND_GAP bridged) and the rails of
            # the layout rules; a rail of the layout rules this close to a clear run is the same rail and keeps its times
            cands, cs = [], fmn
            crun, q = [], 0
            while q < n:
                if cs[q] >= self.FIX_ON:
                    e = q
                    while True:
                        m = e + 1
                        while m < n and cs[m] < self.FIX_ON and T[m] - T[e] <= self.FIX_GAP:
                            m += 1
                        if m < n and cs[m] >= self.FIX_ON and (T[m] - T[e] <= self.FIX_GAP or (m == e + 1 and T[m] - T[e] <= self.CAND_GAP)):
                            e = m
                        else:
                            break
                    if e > q and (T[e] - T[q] >= self.FIX_MIN or cs[q:e + 1].max() >= self.CAND_PEAK):
                        crun.append((q, e))
                    q = e + 1
                else:
                    q += 1
            for a, b in crun:
                pk = float(fmn[a:b + 1].max())
                if pk < self.PAIR_FAINT:
                    continue
                put = not load_like(a, b)      # e.g. the rail taken out and swung into the bin, pointing, a helper
                cands.append({"t": T[a] - self.FIX_LEAD, "a": a, "b": b, "put": put, "old": None, "pk": pk,
                              "dur": float(T[b] - T[a])})
            for c in old:
                near = [x for x in cands if abs(x["t"] - c["load"]) <= self.LINK_TOL and x["pk"] >= self.PAIR_PEAK]
                if near:
                    x = min(near, key=lambda x: abs(x["t"] - c["load"]))
                    if x["old"] is None or abs(x["old"]["load"] - x["t"]) > abs(c["load"] - x["t"]):
                        x["old"], x["t"] = c, c["load"]
                else:
                    # no clear fixture visit there (at most a faint one): a weak rail of the layout rules
                    q = int(np.searchsorted(T, c["load"]))
                    cands.append({"t": c["load"], "a": min(q, n - 1), "b": min(int(np.searchsorted(T, c["out"])), n - 1),
                                  "put": False, "old": c, "weak": True, "pk": 0.0, "dur": 0.0})
            for x in cands:                    # preference tier of each candidate (see PAIR_W)
                x["tier"] = (("weakgrey" if x["old"].get("_grey") else "weak" if "tray" in x["old"] else "weaknotray")
                             if x.get("weak") else "put" if x["put"] else "old" if x["old"] is not None else
                             "faint" if x["pk"] < self.PAIR_PEAK else
                             "load" if x["pk"] >= self.PAIR_CLEAR_PK and x["dur"] >= self.PAIR_CLEAR_DUR else "soft")
            cands.sort(key=lambda x: x["t"])
            avl = avail_times()
            av, lo_av = [r for r, _ in avl], [lo for _, lo in avl]
            self.avail = av
            # best order-keeping pairing of releases (i) and candidate loads (j), by dynamic programming: as many pairs as
            # possible, then the highest summed preference (PAIR_W); load j may use release i from lo_av[i] (PAIR_LAG /
            # PAIR_MIN_WORK) to release i+2 + PAIR_HOLD; two loads at least PAIR_GAP / PAIR_GAP_FIX apart
            na, nc = len(av), len(cands)
            sel = []
            if na and nc:
                ct = np.array([x["t"] for x in cands])
                val = np.array([1.0 + self.PAIR_W[x["tier"]] for x in cands])
                gap = np.array([self.PAIR_GAP if x["old"] is not None and x["old"].get("_grey") else self.PAIR_GAP_FIX
                                for x in cands])  # a grey-layout put gives only an estimated load time
                jgap = np.searchsorted(ct, ct - gap, side="right") - 1   # last candidate at least the gap before
                f = np.full((na, nc), -1e9)
                P = np.full((na + 1, nc + 1), 0.0)          # P[i+1][j+1] = best over pairs (<= i, <= j)
                for i in range(na):
                    hi_ = av[i + 2] + self.PAIR_HOLD if i + 2 < na else 1e18
                    for j in range(nc):
                        if lo_av[i] <= ct[j] <= hi_:
                            f[i, j] = val[j] - 0.002 * abs(ct[j] - av[i] - 2.0) + P[i, jgap[j] + 1]
                        P[i + 1, j + 1] = max(P[i, j + 1], P[i + 1, j], f[i, j])
                # trace back
                i, j = na - 1, nc - 1
                while i >= 0 and j >= 0:
                    best = P[i + 1, j + 1]
                    if best <= 0:
                        break
                    if f[i, j] == best:
                        sel.append(cands[j])
                        cands[j]["rel"] = av[i]
                        j = jgap[j]
                        i -= 1
                    elif P[i, j + 1] == best:
                        i -= 1
                    else:
                        j -= 1
            got_rel = {x["rel"] for x in sel}
            self.unpaired = [r for r in av if r not in got_rel]   # releases with no rail found (for the findings)
            used = {id(x) for x in sel}
            for x in cands:
                x["used"] = id(x) in used
            sel.sort(key=lambda x: x["t"])
            self.cands = cands
            self.dropped = []              # rails of the release pairing that the puts into the bin took away
            if self.BIN_PUT and sel:
                sel = bin_put_rails(sel, cands)
                self.dropped = [x["t"] for x in cands if x.get("dropped_put")]
            pairs2, vt2 = [], {}
            for i, x in enumerate(sel):
                nxt_t = sel[i + 1]["t"] if i + 1 < len(sel) else T[-1] + 1.0
                nm = min(n, int(np.searchsorted(T, nxt_t)))
                c = x["old"]
                if c is not None and c["out"] <= nxt_t - 0.5 and c.get("tray", c["out"]) <= nxt_t - 0.5:
                    pairs2.append([x["a"], x["b"], None, None, c])
                    continue
                a, b = x["a"], x["b"]
                vt2[(a, b)] = (x["t"], max(T[b], x["t"] + 0.3)) if c is None else (c["load"], min(c["out"], nxt_t - 0.5))
                ta = first(b + 1, nm, lambda q: self.TRAY_SKIP <= T[q] - T[b] < self.TRAY_AFTER and lown[q] >= self.LOW_ON)
                tb = None
                if ta is not None:
                    while ta - 1 > b and lown[ta - 1] >= self.LOW_EDGE and T[ta - 1] - self.TRAY_LEAD > T[b]:
                        ta -= 1
                    tb = bin_end(ta, nm, 3.0, lown)
                pairs2.append([a, b, ta, tb, nm])
            out_ = elements(pairs2, vt2, lown)
            for x, c in zip(sel, out_):
                if x.get("bin_put"):
                    c["_put"] = True       # a rail of the puts into the bin, not of the release pairing
            return out_

        # ---- layout: a blue bin or a big blue / orange grid tray in front of him (afternoon, night, after midnight) or grey
        # boxes with a small grid tray at the bottom edge of the picture (from ~02:07 on 2026-10-15). Decided per 10 s from
        # the blue and orange shares of the bin area, smoothed over LAYOUT_WIN s, so a person passing does not switch it.
        bins_ = np.floor((T - T[0]) / 10.0).astype(int)
        nb = int(bins_[-1]) + 1

        def smooth(sig):
            med = np.full(nb, np.nan)
            for k in range(nb):
                v = sig[bins_ == k]
                v = v[~np.isnan(v)]
                if len(v):
                    med[k] = np.median(v)
            h = int(self.LAYOUT_WIN / 20)
            return np.array([np.nanmedian(med[max(0, k - h):k + h + 1]) if np.any(~np.isnan(med[max(0, k - h):k + h + 1]))
                             else 1.0 for k in range(nb)])
        g = (smooth(blue) < self.LAYOUT_BLUE) & (smooth(orange) < self.LAYOUT_ORANGE)
        k = 0
        while k < nb:                  # a short stretch without the bin is a bin change, not the grey-box layout
            if g[k]:
                e = k
                while e + 1 < nb and g[e + 1]:
                    e += 1
                if (e - k + 1) * 10.0 < self.LAYOUT_MIN:
                    g[k:e + 1] = False
                k = e + 1
            else:
                k += 1
        grey = g[bins_]
        is_grey = lambda t: bool(grey[min(n - 1, int(np.searchsorted(T, t)))])  # noqa: E731
        cyc = [c for c in cyc if not is_grey(c["load"])]
        if grey.any():
            cyc = sorted(cyc + self._grey_rails(T, bm, fm, grey, rel), key=lambda c: c["start"])
            g0 = T[np.argmax(grey)]
            self.layout_note = (f"Layout: grey boxes with a grid tray at the bottom edge (no blue bin) from {hm(g0)}; there the rails "
                                f"are counted from his hand putting each rail into the grid tray.")
        if self.PAIR and len(getattr(self.ymm, "picks", [])) > 1:
            cyc = pair_rails(cyc)
        elif self.REL_MATCH and rel:
            cyc = sorted(self._release_match(cyc, rel), key=lambda c: c["start"])
        for c in cyc:
            c.pop("_weak", None)
            c.pop("_grey", None)
        cyc = self._rivet(cyc, T)
        out = []
        for c, d in zip(cyc, cyc[1:]):
            if d["start"] - c["start"] > self.MAX_CYCLE and not self.KEEP_LONG:
                continue
            c["end"] = d["start"]
            if "back" not in c or c["back"] > c["end"]:
                c["back"] = c["end"]
            out.append(c)
        if self.OPEN_LAST and cyc:
            # the last rail of the window: its cycle ends with the next take, which is not in the window yet. It is kept as
            # an open cycle up to the end of the window (c["open"]), else the live feed loses one rail per run: it keeps
            # the cycles that end inside a run's window and start after the previous run's window
            c = cyc[-1]
            if c["start"] <= T[-1] - self.OPEN_MIN and c["load"] <= T[-1] \
                    and (T[-1] - c["start"] <= self.MAX_CYCLE or self.KEEP_LONG):
                c["end"], c["open"] = float(T[-1]), True
                c["out"] = min(c["out"], c["end"])
                for k_ in [k for _, k in self.ORDER if k not in ("load", "out")] + ["tray_end"]:
                    if ok(c.get(k_)) and c[k_] > c["end"]:
                        c.pop(k_)          # not seen before the end of the window
                if "back" not in c:
                    c["back"] = c["end"]
                out.append(c)
        self.m_cycles = mcyc
        return self._self_check(out, mcyc, T[0], T[-1])

    def _rivet(self, cyc, T):
        """Pop rivet gun used on this rail (inner rail) or not (outer rail). Per rail, in the frames from the previous rail
        coming out of the fixture (+0.5 s; at most RIV_WIN s) to this rail going in: he stands at the shelf (navy shirt
        fills RIV_A, RIV_B at the Final Inspection machine is not navy) with his right arm up at the gun (navy in RIV_G).
        RIV_SEEN s of that = the gun was used on this rail. Sets c["rivet"] (bool), c["rivet_seen"] (the gun use itself was
        seen), c["rivet_t0"] / c["rivet_t1"] (start / end of the main run at the gun, frames bridged over RIV_GAP s) and
        c["rivet_sec"] (their difference = the rivet time; 0 when the gun use was not seen) and c["variant"] ("inner" /
        "outer": at least half of the rails within RIV_VAR_SEC that could be checked had the gun used). c["rivet"] is True
        when the gun use was seen or the rail lies in an inner period. A rail whose look-back is mostly missing (recording gap) or too short takes the variant. In an inner
        period a detected rail without gun use, although the look-back was seen, within RIV_DROP_WIN s of the last rail is
        not a rail (a second fixture visit or bin work of the same rail; every inner rail is riveted right before it goes
        in): it is dropped. An outer rail gets c["pen"] = c["mark"]: its time at the shelf is MARK, not RIVET."""
        if not cyc:
            return cyc
        nA, nB, nG = (np.nan_to_num(self.nav[:, j]) for j in range(3))
        seen_f = ~np.isnan(self.nav[:, 0])
        at_gun = (nA > self.RIV_A_ON) & (nB < self.RIV_B_OFF) & (nG > self.RIV_G_ON) & seen_f

        def look(c, prev_out):
            lo = c["load"] - self.RIV_WIN if prev_out is None else max(c["load"] - self.RIV_WIN, prev_out + 0.5)
            lo = min(lo, c["load"] - 1.0)
            i, j = int(np.searchsorted(T, lo)), int(np.searchsorted(T, c["load"]))
            dt = np.minimum(np.diff(np.append(T[i:j], c["load"])), 0.5)
            g = at_gun[i:j]
            run, best = None, None      # the main run at the gun: frames bridged over gaps up to RIV_GAP s, most time
            for k in np.flatnonzero(g):
                if run and T[i + k] - run[1] <= self.RIV_GAP:
                    run = [run[0], T[i + k] + dt[k], run[2] + dt[k]]
                else:
                    run = [T[i + k], T[i + k] + dt[k], dt[k]]
                if best is None or run[2] > best[2]:
                    best = list(run)
            return {"win": c["load"] - lo, "cov": float((dt * seen_f[i:j]).sum()) / (c["load"] - lo),
                    "gun": float((dt * g).sum()), "t0": float(best[0]) if best else None, "t1": float(best[1]) if best else None}
        cyc = sorted(cyc, key=lambda c: c["load"])
        votes, prev_out = [], None
        for c in cyc:                  # the variant: rails that could be checked (look-back long enough and seen)
            i = look(c, prev_out)
            if i["win"] >= self.RIV_VOTE_WIN and i["cov"] >= self.RIV_COV:
                votes.append((c["load"], i["gun"] >= self.RIV_SEEN))
            prev_out = c["out"]
        out, last_out = [], None
        for c in cyc:
            i = look(c, last_out)
            s = i["gun"] >= self.RIV_SEEN
            v = [x for t, x in votes if abs(t - c["load"]) <= self.RIV_VAR_SEC]
            inner = sum(v) >= self.RIV_VAR_SHARE * len(v) if v else s
            if (self.RIV_DROP and inner and not s and i["cov"] >= self.RIV_COV and last_out is not None
                    and c["load"] - last_out < self.RIV_DROP_WIN):
                continue               # not a rail: no gun use since the last rail was out
            c["variant"] = "inner" if inner else "outer"
            c["rivet_seen"] = bool(s)
            clear_outer = len(v) >= self.RIV_CLEAR_N and sum(v) <= self.RIV_CLEAR_OUT * len(v)
            c["rivet"] = bool((s and not clear_outer) or inner)
            c["rivet_sec"] = round(i["t1"] - i["t0"], 2) if s else 0.0
            if s:
                c["rivet_t0"], c["rivet_t1"] = i["t0"], i["t1"]
            if not c["rivet"]:
                c["pen"] = c.get("mark", c["load"])   # outer rail: no pop rivet, the time at the shelf is MARK
            out.append(c)
            last_out = c["out"]
        return sorted(out, key=lambda c: c["start"])

    def _release_match(self, cyc, rel):
        """Every rail he finishes was let go into the output holder by the Mechanical Movement #2 operator first: a rail
        is counted only if a release before its load (0.3 s) is still unused, releases taken in order."""
        out, used = [], 0
        for c in sorted(cyc, key=lambda c: c["load"]):
            if [r for r in rel[used:] if r < c["load"] - 0.3]:
                used += 1
            elif self.REL_MATCH == 2 and not c.get("_weak"):
                pass                   # 2: only a rail without a fixture visit of its own is dropped
            else:
                continue
            out.append(c)
        return out

    def _grey_rails(self, T, bm, fm, grey, rel):
        """Grey-box layout: one rail = his hand going into the grid tray at the bottom edge (a clear motion burst there);
        the fixture visit before it from the fixture-area motion."""
        n, bmn, fmn = len(T), np.nan_to_num(bm), np.nan_to_num(fm)

        def run_end(i, s, on, edge, gap):
            j = i
            while True:
                k = j + 1
                while k < n and s[k] < edge and T[k] - T[j] <= gap:
                    k += 1
                if k < n and s[k] >= edge and T[k] - T[j] <= gap:
                    j = k
                else:
                    return j
        puts, i = [], 0
        while i < n:
            if grey[i] and bmn[i] >= self.BOT_ON:
                j = run_end(i, bmn, self.BOT_ON, self.BOT_EDGE, 0.5)
                strong = bmn[i:j + 1].max() >= self.BOT_MAX and bmn[i:j + 1].sum() >= self.BOT_SUM
                if puts and T[i] - puts[-1][0] < self.BOT_MERGE:
                    puts[-1][1] = T[j]          # the hand coming out again, or the next cell
                elif strong:
                    puts.append([T[i], T[j]])
                i = j + 1
            else:
                i += 1
        fixr, i = [], 0
        while i < n:
            if fmn[i] >= self.FIX_ON:
                j = run_end(i, fmn, self.FIX_ON, self.FIX_ON, self.FIX_GAP)
                fixr.append((T[i], T[j]))
                i = j + 1
            else:
                i += 1
        out, prev_te, prev_back = [], -1e18, None
        for p0, p1 in puts:
            tray = p0 - self.GREY_TRAY_LEAD
            fr = [r for r in fixr if r[1] > prev_te and tray - self.GREY_FIX_MAX <= r[1] <= tray - self.GREY_FIX_MIN]
            if fr:
                t_out, t_load = fr[-1][1], max(fr[-1][0] - self.GREY_FIX_LEAD, prev_te + 0.1)
            else:
                t_out = tray - self.GREY_CHECK2
                t_load = t_out - self.GREY_MACHINE
            t_load = min(max(t_load, prev_te + 0.1), t_out - 0.2)
            rr = [t for t in rel if prev_te - 1.5 < t < t_load - 0.3]
            t_take = rr[-1] if rr else None
            if t_take is not None and prev_back is not None and t_take < prev_back:
                t_take = prev_back + 0.3
            if t_take is None:
                t_take = prev_back + 0.3 if prev_back is not None and t_load - prev_back < self.TAKE_AFTER_BACK else t_load - self.TAKE_LEAD
            t_take = min(t_take, t_load - 0.2)
            c = {"take": t_take, "start": t_take, "mark": min(t_take + self.TAKE_LEAD, t_load), "load": t_load, "out": t_out,
                 "tray": tray, "tray_end": max(p1 - self.GREY_TRAY_TAIL, tray + 0.5)}
            c["_grey"] = True          # a rail of the grey-layout rules (from his hand in the grid tray)
            if not fr:
                c["_weak"] = True      # no fixture motion before the put: checked against the releases
            c["back"] = c["tray_end"] + self.GREY_BACK
            prev_te, prev_back = c["tray_end"], c["back"]
            out.append(c)
        return out

    def _self_check(self, cycles, mcyc, t0, t1):
        """Rails against the Mechanical Movement cycles found on the same frames, per 10 minutes of the clock. A block whose
        counts differ by more than SC_TOL (at least SC_MIN rails), or with impossible rail cycles (under SC_SHORT s), is not
        checked: its rails are left out of the statistics and the cycle table."""
        blocks = {}
        for c in cycles:
            blocks.setdefault(int(c["start"] // self.SC_BLOCK), [[], [], []])[0].append(c)
        # also compared: the count of the release pairing alone (the rails the puts into the bin add or take away are
        # checked by the puts themselves; the open last rail of the window has no Mechanical Movement cycle yet)
        dropped = getattr(self, "dropped", None) if self.PAIR else None
        for t in [c["start"] for c in mcyc]:
            blocks.setdefault(int(t // self.SC_BLOCK), [[], [], []])[1].append(t)
        for t in dropped or []:
            blocks.setdefault(int(t // self.SC_BLOCK), [[], [], []])[2].append(t)
        keep, self.check = [], []
        for b in sorted(blocks):
            rails, ms, pr = blocks[b]
            nm = len(ms)
            ns = [len(rails)] + ([sum(1 for c in rails if not c.get("_put") and not c.get("open")) + len(pr)]
                                 if dropped is not None else [])   # rails, and the release-paired rails
            short = sum(1 for c in rails if c["end"] - c["start"] < self.SC_SHORT)
            why, tol = "", max(self.SC_TOL * nm, self.SC_MIN)
            if max(ns) < nm - tol or min(ns) > nm + tol:   # both too few or both too many
                why = f"{len(rails)} rails ({ns[-1]} release-paired) against {nm} Mechanical Movement cycles"
            elif rails and short > max(self.SC_SHORT_SHARE * len(rails), 1):
                why = f"{short} rail cycles shorter than {self.SC_SHORT:.0f} s"
            self.check.append({"block": b * self.SC_BLOCK, "rails": len(rails), "paired": ns[-1], "ymm": nm, "short": short,
                               "ok": not why, "why": why})
            if not why:
                keep += rails
        for c in cycles:
            c.pop("_put", None)
        return sorted(keep, key=lambda c: c["start"])

    def extra(self, cycles):
        out = []
        chk = getattr(self, "check", [])
        bad = [b for b in chk if not b["ok"]]
        if bad:
            out.append(f"Self-check: {len(bad)} of {len(chk)} ten-minute blocks left out of the statistics and the cycle table "
                       f"(layout not validated): " + "; ".join(f"{hm(b['block'])[:5]} {b['why']}" for b in bad) + ".")
        w = [c["end"] - c["back"] for c in cycles if "back" in c]
        work = [c["back"] - c["start"] for c in cycles if "back" in c]
        if w:
            out.append(f"Work per rail median {stat.median(work):.1f}s, waiting for the next rail median {stat.median(w):.1f}s "
                       f"({100 * sum(w) / max(1e-6, sum(w) + sum(work)):.0f}% of the time).")
        inner = [c for c in cycles if c.get("rivet")]
        outer = [c for c in cycles if c.get("rivet") is False]
        if inner or outer:
            rs = [c["rivet_sec"] for c in inner if c.get("rivet_seen")]
            runs = []                  # variant periods in time order
            for c in cycles:
                v = c.get("variant")
                if runs and runs[-1][0] == v:
                    runs[-1][2] = c["end"]
                else:
                    runs.append([v, c["start"], c["end"]])
            out.append(f"Pop rivet gun: {len(inner)} inner rails (gun used"
                       + (f", rivet time median {stat.median(rs):.1f}s" if rs else "") + f"), {len(outer)} outer rails (no pop "
                       f"rivet: step 11 not used). Periods: " + ", ".join(f"{v} {hm(a)[:5]}-{hm(b)[:5]}" for v, a, b in runs if v) + ".")
        riv = [c["load"] - c["start"] for c in inner if "load" in c]
        ins = [c["back"] - c["load"] for c in cycles if "load" in c and "back" in c]
        if riv and ins:
            out.append(f"His cycle split: Pop Rivet Gun part (take + rivet at the shelf, inner rails) median {stat.median(riv):.1f}s, "
                       f"Final Inspection part (machine + check after + bin + turn back) median {stat.median(ins):.1f}s.")
        oth = [c for c in cycles if "other_a" in c or "other_b" in c]
        if oth:
            out.append(f"Other work (bent low / away) in {len(oth)} of {len(cycles)} cycles.")
        if chk:
            out.append("Self-check, rails / Mechanical Movement cycles per 10 minutes: "
                       + ", ".join(f"{hm(b['block'])[:5]} {b['rails']}/{b['ymm']}{'' if b['ok'] else ' left out'}" for b in chk)
                       + (". Rails per hour above count only the checked blocks." if bad else "."))
        pa = [x for x in getattr(self, "cands", []) if x.get("bin_put")]
        pd = [x for x in getattr(self, "cands", []) if x.get("dropped_put")]
        if pa or pd:
            out.append(f"Puts into the bin (dark box in front of him, puts seen): {len(pa)} rails added that the release pairing "
                       f"had left out (two rails close together, one release seen), {len(pd)} paired fixture visits taken away "
                       f"(no rail of their own).")
        if getattr(self, "layout_note", ""):
            out.append(self.layout_note)
        return out


# ======================================================================== yml: Mechanical Movement, YRA line, left person (camera 13)
class YML:
    """YRA SEAT SLIDER, station 13 "Mechanical Movement" (camera 13 = 192.168.31.39, overlay YRA_SS_FINAL): the LEFT person of
    the final-area camera (zone x 0.00-0.34), who makes every rail that the middle person (Mechanical Movement #2, ymm) works
    on next. Watched frame by frame on four 1600x900 videos: 2026-10-14 14:11-14:15 (afternoon), 23:26-23:30 (night, blue
    bin), 2026-10-15 01:23-01:27 (after midnight) and 02:30-02:34 (grey boxes); yml_<set>_annotations.json. The person
    changed between the afternoon and the night; the work is the same.

    Seen in the video, per rail (median seconds after he handed over the previous rail):
      hands the finished rail to the middle person at the amber input holder at the right end of his fixture (0): in the
      afternoon and after midnight he stands it into the holder and the middle person takes it from there; at night and
      in the grey-box layout the middle person waits with his glove at the holder and takes it glove to glove -> turns
      left, steps behind the white post at his left and comes back with the next rail (0.5 - 1.5) -> lays it on his
      fixture and works at it with both hands, mostly the right glove on the fixture bed, his body hiding most of it
      (1.5 - ~11) -> right hand up to the clear box at the top right of the fixture (~1.5 s before the next hand-over;
      part or button, too small to see) -> lifts the finished rail out and hands it over (next cycle).
    """
    key, cams, station_id, title = "yml", (13,), 13, "Mechanical Movement (YRA)"
    L_CX = 0.33                    # the left person: box centre x left of this (the middle person is at 0.36-0.50)
    L_TOP, L_H = 0.45, 0.35        # standing: box top above y 0.45, box height over 0.35
    AWAY_X = 0.17                  # behind the white post (taking the next rail): box centre left of this, or not detected
    GAP_AWAY = 0.7                 # a gap in the recording this long right after he reached the holder counts as away
    TRIP_MIN = 0.8                 # shortest walk to the left (s)
    TRIP_RX = 0.27                 # his right wrist reached right of this (towards the holder) in the 1.6 s before the walk
    HO_LEAD = 0.5                  # the rail left his glove this long before he turned away
    BACK_LAG = -0.2                # next rail on his fixture: 0.2 s before he is detected at his place again (detection lags)
    MERGE = 6.0                    # walks closer than this to the last hand-over belong to the same rail
    HOLD_X, HOLD_MOT = 0.30, 30.0  # hand-over without a walk: his right wrist right of 0.30 at a hand burst in the holder
    HOLD_ISO = 8.0                 # ... and no hand-over found within this
    STAND = (0.318, 0.56, 0.345, 0.69)  # the input holder patch (as in ymm)
    REACH_X, REACH_WIN = 0.285, (3.0, 0.5)  # right hand to the clear box: wrist right of 0.285, highest point 3.0-0.5 s before
    MAX_CYCLE = 60.0
    REC_GAP = 3.0                  # a cycle with a gap in the recording longer than this inside is not counted
    # self-check against the Mechanical Movement #2 cycles found on the same frames (every rail he makes goes there)
    SC_BLOCK = 600.0
    SC_TOL, SC_MIN = 0.20, 3
    SC_SHORT, SC_SHORT_SHARE = 6.0, 0.10
    ORDER = [("GIVE", "handover"), ("FETCH", "fetch"), ("WORK", "load"), ("OUT", "reach")]
    NAMES = {
        "GIVE": ("Hand the rail to Mechanical Movement #2 (input holder / glove)", "#16a34a"),
        "FETCH": ("Turn left, take the next rail (behind the white post)", "#f59e0b"),
        "WORK": ("Rail on his fixture, working at it", "#2563eb"),
        "OUT": ("Right hand to the clear box, lift the finished rail out", "#a855f7"),
    }
    METHOD = [
        "Operator: the left person (box centre x left of 0.33, standing), followed from frame to frame.",
        "Hand-over: after each rail he turns left and steps behind the white post for the next rail; he is then not seen at "
        "his place (box centre left of x 0.17, or not detected) for 0.8 s or more, right after his right wrist was at the "
        "input holder (x 0.27 or more). The rail left his glove 0.5 s before he turned away; walks within 6 s of the last "
        "hand-over are the same rail. Without a walk: a hand burst in the input holder while his right wrist is right of "
        "x 0.30, at least 8 s from any other hand-over. A cycle with a gap of more than 3 s in the recording is not counted.",
        "Fetch: from the moment he turned away until he is back at his place (-0.2 s, the detection lags) = next rail on his "
        "fixture. Out: his right wrist highest at x 0.285 or more in the 3.0-0.5 s before the next hand-over (right hand to "
        "the clear box), then the rail is lifted out and handed over.",
        "Checked against cycles annotated frame by frame on four full-resolution videos: afternoon 2026-10-14 14:11-14:15 "
        "16/16, night 23:27-23:30 11 of the 11 inside the recording (3 more fall in a gap of the recording), after midnight "
        "01:23-01:27 15/15, grey boxes 02:30-02:34 15/15; hand-over within 0.1-0.3 s (median), fetch 0.1-0.2 s, next rail "
        "on the fixture 0.1-0.2 s. A visitor standing at his place (23:22:30-23:23:20) gives wrong hand-overs there.",
        "Self-check: per 10 minutes the rails he hands over are compared with the Mechanical Movement #2 cycles found on the "
        "same frames; a block where they differ by more than 20% (and more than 3), or with more than 10% of his cycles "
        "shorter than 6 s, is left out of the statistics and the cycle table.",
    ]
    UNSEEN = ["What his fixture does and what he does with both hands at it (his body hides most of it).",
              "What his right hand does at the clear box at the top right of the fixture (a part or a button).",
              "Where the next rail comes from behind the white post (the previous station or a rack)."]

    def __init__(self):
        self.ymm = YMM()

    def features(self, frames):
        rows, last, prev = [], None, None
        for f in frames:
            img = read_frame(f)
            mo = NAN
            if img is not None:
                g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                r = roi(g, self.STAND).astype(np.float32)
                if prev is not None and prev.shape == r.shape:
                    mo = float(np.abs(r - prev).mean())
                prev = r
            cand = []
            for p in f["p"]:
                b, k = p.get("b"), p.get("k")
                if not b or not k:
                    continue
                cx = (b[0] + b[2]) / 2
                if cx < self.L_CX and b[1] < self.L_TOP and (b[3] - b[1]) > self.L_H:
                    cand.append((abs(cx - last) if last is not None else abs(cx - 0.22), p, cx))
            row = [f["t"], NAN, NAN, NAN, mo]
            if cand:
                _, p, cx = min(cand, key=lambda c: c[0])
                last = cx
                k = p["k"]
                row = [f["t"], cx, k[10][0] if k[10][2] > 0.3 else NAN, k[10][1] if k[10][2] > 0.3 else NAN, mo]
            rows.append(row)
        return np.array(rows, float)

    def detect(self, frames):
        A = self.features(frames)
        self.check = []
        if len(A) < 50:
            return []
        T, cx, rx, ry, mo = (A[:, j] for j in range(5))
        n = len(T)
        mcyc = self.ymm.detect(frames)
        away = np.isnan(cx) | (np.nan_to_num(cx, nan=0.0) < self.AWAY_X)
        cxn = np.nan_to_num(cx, nan=0.0)
        # a gap in the recording after which he is away or further left = he turned away during the gap
        gap = np.r_[(np.diff(T) > self.GAP_AWAY) & (away[1:] | (cxn[1:] < cxn[:-1] - 0.02)), False]

        def rx_max(t0, t1):
            m = (T >= t0) & (T < t1)
            v = rx[m]
            return float(np.nanmax(v)) if np.any(~np.isnan(v)) else 0.0
        # walks to the left (trip = [last frame at his place, first frame back at his place])
        trips, i = [], 0
        while i < n:
            if away[i] or gap[i]:
                j = i
                while j + 1 < n and away[j + 1]:
                    j += 1
                a0 = T[i - 1] if i > 0 and away[i] and not away[i - 1] else T[i]
                a1 = T[j + 1] if j + 1 < n else T[j]
                if a1 - a0 >= self.TRIP_MIN and rx_max(a0 - 1.6, a0 + 0.01) >= self.TRIP_RX:
                    trips.append((a0, a1))
                i = j + 1
            else:
                i += 1
        mon = np.nan_to_num(mo)
        ev = []
        for a0, a1 in trips:
            h = a0 - self.HO_LEAD
            if ev and h - ev[-1]["handover"] < self.MERGE:
                continue
            ev.append({"handover": h, "fetch": a0, "load": a1 + self.BACK_LAG})
        # hand-over without a walk (the next rail was already at hand): a hand burst in the holder with his wrist there
        for q in range(n):
            if mon[q] >= self.HOLD_MOT and (q == 0 or mon[q - 1] < self.HOLD_MOT) and rx_max(T[q] - 0.4, T[q] + 0.4) >= self.HOLD_X:
                if all(abs(T[q] - e["handover"]) >= self.HOLD_ISO for e in ev):
                    ev.append({"handover": float(T[q])})
                    ev.sort(key=lambda e: e["handover"])
        # right hand to the clear box before each hand-over
        for e in ev:
            m = (T >= e["handover"] - self.REACH_WIN[0]) & (T <= e["handover"] - self.REACH_WIN[1]) & (np.nan_to_num(rx) >= self.REACH_X)
            if m.any():
                e["reach"] = float(T[m][np.nanargmin(np.where(np.isnan(ry[m]), 9.0, ry[m]))])
        cycles = []
        for e, d in zip(ev, ev[1:]):
            inside = T[(T >= e["handover"]) & (T <= d["handover"])]
            if d["handover"] - e["handover"] > self.MAX_CYCLE or (len(inside) > 1 and np.diff(inside).max() > self.REC_GAP):
                continue                  # too long, or a gap in the recording inside: not a cycle of its own
            c = {"start": e["handover"], "handover": e["handover"], "end": d["handover"]}
            for k in ("fetch", "load"):
                if k in e and e[k] < d["handover"]:
                    c[k] = e[k]
            if "reach" in d and d["reach"] > c.get("load", c["start"]):
                c["reach"] = d["reach"]
            cycles.append(c)
        self.m_cycles = mcyc
        return self._self_check(cycles, mcyc)

    def _self_check(self, cycles, mcyc):
        blocks = {}
        for c in cycles:
            blocks.setdefault(int(c["start"] // self.SC_BLOCK), [[], []])[0].append(c)
        for c in mcyc:
            blocks.setdefault(int(c["start"] // self.SC_BLOCK), [[], []])[1].append(c)
        keep, self.check = [], []
        for b in sorted(blocks):
            rails, ms = blocks[b]
            nr, nm = len(rails), len(ms)
            short = sum(1 for c in rails if c["end"] - c["start"] < self.SC_SHORT)
            why = ""
            if abs(nr - nm) > max(self.SC_TOL * nm, self.SC_MIN):
                why = f"{nr} rails against {nm} Mechanical Movement #2 cycles"
            elif nr and short > max(self.SC_SHORT_SHARE * nr, 1):
                why = f"{short} cycles shorter than {self.SC_SHORT:.0f} s"
            self.check.append({"block": b * self.SC_BLOCK, "rails": nr, "ymm": nm, "short": short, "ok": not why, "why": why})
            if not why:
                keep += rails
        return sorted(keep, key=lambda c: c["start"])

    def extra(self, cycles):
        out = []
        chk = getattr(self, "check", [])
        bad = [b for b in chk if not b["ok"]]
        if bad:
            out.append(f"Self-check: {len(bad)} of {len(chk)} ten-minute blocks left out of the statistics and the cycle table "
                       f"(layout not validated): " + "; ".join(f"{hm(b['block'])[:5]} {b['why']}" for b in bad) + ".")
        fet = [c["load"] - c["fetch"] for c in cycles if "fetch" in c and "load" in c]
        if fet:
            out.append(f"Taking the next rail (turn left and back) median {stat.median(fet):.1f}s; it was seen in "
                       f"{len(fet)} of {len(cycles)} cycles.")
        if chk:
            out.append("Self-check, his rails / Mechanical Movement #2 cycles per 10 minutes: "
                       + ", ".join(f"{hm(b['block'])[:5]} {b['rails']}/{b['ymm']}{'' if b['ok'] else ' left out'}" for b in chk)
                       + (". Rails per hour above count only the checked blocks." if bad else "."))
        return out


# ======================================================================== yur / yhs / yxl: YRA upper rail, steps 1-3 (camera 8)
class YUR:
    """YRA SEAT SLIDER, step 1 "Upr Rail Greasing m/c" (station 8). Cameras 8, 14 and 15 are one physical camera
    (192.168.31.30, overlay YRA_SS_UPR_RAIL); only camera 8 is recorded, so steps 1-3 (YUR, YHS, YXL) all run on it.
    Watched frame by frame on two 1600x900 videos of 2026-10-15: 21:50:58-21:54:58 (13 loops; the camera-8 recording ran
    at only ~1.5-2 frames/s then) and 22:44:59-22:49:59 (20 loops; recording at ~4.4 frames/s, with a 31 s gap at
    22:46:28-22:46:59).

    One operator (blue shirt, navy cap with a yellow badge, gloves) runs all three machines in one loop of ~14 s. His home
    is the step-2 machine (middle of the picture); the person at the far left edge works at another station. Rails go
    1 -> 2 -> 3. Seen per loop (median seconds after the step-2 lamps go off, first / second video):
      the two green lamps on the step-2 button box go off while he stands at the jig with his right hand at the box (0)
      -> he turns right, bends to the blue bins at the bottom right and picks a rail with the right hand (0.3 / 0.1; every
      few loops he first lifts a white separator sheet out of the bin, and once the empty top bin was lifted away: +2-6 s)
      -> right hand with the new rail into the opening of the step-1 greasing machine between the light-curtain posts
      (0.9 / 0.9) -> the left hand carries the greased rail out to the left -> right hand at the bottom-left corner of the
      step-1 machine for ~1 s -> hand leaves step 1, he is at the step-2 jig (2.9 / 2.8) -> hands at the jig (hidden by his
      back), left hand into the small blue parts bin on top of the step-2 machine -> lamps lit again (4.3 / 4.3) -> hands
      at the jig -> walks left to step 3 with a dark rail in the right hand (8.6 / 7.4) -> at the step-3 nest (9.9 / 8.9),
      hands hidden -> left hand lays a finished rail on the yellow rack at the left front (10.2 / 9.4) -> walks back
      (10.8 / 10.0) -> at the step-2 jig (12.5 / 11.6), hands at the jig and the button box until the lamps go off (14.3 /
      13.5). Twice the order changed: the next step-1 exchange was done while the step-2 lamps were still lit (22:48:06),
      and after one exchange he went back to the bin for ~4 s (rails arranged, 21:52:37).
    The step-3 machine starts ~0.7 s after he leaves it and presses twice (upper slides at +0.5..+4 s, slides and bed at
    +7..+10.5 s); then it stands still until he is back (~2.6 s). The step-1 machine shows no visible motion.
    Day crew (2026-10-17 16:52-17:02, full-resolution video, *_day1652_annotations.json): the loop runs bin -> step 1 ->
    step 2 -> step 3 -> bin. He loads and starts the step-2 jig, keeps his hands at it while the lamps are lit (~4.3 s),
    releases it himself and walks to step 3 with the rail; at step 3 he often waits beside the press until it is done
    (standing ~0.05 right of his nest position), then lays the finished rail on the rack and the new rail in. Unusual
    cycles: a bin change with a second step-1 exchange and rails arranged on the rack (16:53:58), a press that did not run
    and was reset at its panel (16:56:12), waits while the steps 4-5 operator took rails from the rack, and a line stop
    of 127 s at the step-2 jig (16:59:56-17:02:03).
    """
    key, cams, station_id, title = "yur", (8,), 8, "Upper Rail Greasing m/c (YRA step 1)"
    OP_CX = (0.25, 0.85)              # the operator: person box centre x in this range, box at least 0.3 high
    # image areas (normalised x0, y0, x1, y1)
    LAMPS = ((0.629, 0.349, 0.639, 0.366), (0.643, 0.349, 0.652, 0.366))  # the two lamps of the step-2 button box
    BIN = (0.59, 0.82, 0.70, 0.97)    # front blue bin (step 1)
    S1 = (0.68, 0.52, 0.74, 0.64)     # step-1 machine opening and its front corner (his right hand)
    S3UP = (0.27, 0.22, 0.42, 0.40)   # upper slides of the step-3 machine
    RACK = (0.17, 0.54, 0.26, 0.64)   # rack at the left front of step 3
    LAMP_ON, LAMP_OFF = 18.5, 15.5    # lamp greenness (G - (R+B)/2): lit above / unlit below; his head can hide the box
    OFF_MIN = 0.9                     # lamps off for at least this long (s) = jig released; shorter = his head in front
    ON_BLIP = 2.5                     # a lit spell shorter than this inside an unlit one is not a start (real: 6 s or more)
    BENT_TOP, BENT_CX = 0.30, 0.54    # step-1 visit: bent to the bin (box top below y 0.30) right of x 0.54
    BIN_MOT = 0.15                    # moving-pixel share in the bin area: a hand in the bin ...
    LOW_WY = 0.72                     # ... with a wrist this low or the body bent (his feet also pass there)
    VISIT_GAP = 1.2                   # step-1 visit frames closer than this are one visit, and next frames up to
    FRAME_GAP = 3.0                   # this far apart (frames missing in the recording)
    MISS_GAP, MISS_FREE = 1.5, 6.0    # a bend with frames missing (gap of 1.5 s or more) right after it and no exchange
                                      # within 6 s: the rail went in unseen, an exchange
    S1_MOT, S1_END = 0.10, 0.05       # moving-pixel share at the step-1 opening: rail goes in / hand still there
    S1_GAP = 0.8                      # hand still at step 1 across frames without motion up to this (low frame rates)
    S1_RUN = 1.4                      # rail-in motion frames closer than this are one run; the rail goes in at the last run
    DEEP_TOP = 0.36                   # ... not counted while he is bent deep into the bin (head near the opening)
    S1_ALONE = 0.25                   # rail-in motion with no bend seen: two frames within 2.5 s, or one above this
    MERGE_S1 = 2.0                    # a bend without a rail going in that ends this close before an exchange is part
                                      # of its pick (separator sheet, bin change)
    PICK_LEAD = 0.9                   # rail-in motion with no bend seen (recording gaps): the pick is this much earlier
    MID_GAP = 3.0                     # event between two frames up to this far apart: the middle; else the later frame
    BACK_TOP, BACK_CX = 0.30, 0.62    # back at step 2 after other bin work: upright, centre left of 0.62
    S3_CX = 0.42                      # at step 3: box centre left of this
    S3_ARRIVE, S3_LEAVE = 0.03, 0.02  # arrived: the walk ends (he gets no more than 0.03 further left in the next
    ARRIVE_LOOK = 1.5                 # 1.5 s; 0 = within 0.03 of his left-most position in the first ARRIVE_WIN s) ·
    ARRIVE_WIN = 3.0                  # leaving: last frame within 0.02 of his left-most position in the last 3 s
    S3_MERGE = 10.0                   # step-3 visits less than 10 s apart with no return to step 2 between: one visit
    ONE_PER_S3 = 1                    # yur: a second step-1 exchange before he has been to step 3 is not a new cycle
    S2_CX = 0.52                      # back at step 2: centre right of this
    LEAVE_DROP = 0.015                # walk to step 3 starts: centre this far left of his step-2 position
    RACK_WX, RACK_WY = 0.27, 0.50     # rail on the rack: left wrist left of x 0.27, below y 0.50
    RACK_MOT, RACK_AFTER = 0.15, 0.3  # or motion at the rack, from 0.3 s after he arrived
    PRESS_MOT, AWAY_CX = 0.08, 0.45   # step-3 press: motion of its upper slides while he is right of x 0.45
    PRESS_WIN, PRESS_SPAN = 4.0, 12.0  # first stroke within 4 s after he left; both strokes end within 12 s
    MAX_CYCLE = 60.0
    HOLE = 5.0                        # frames missing for longer than this inside a cycle: the cycle is not used
    # self-check against the neighbour station, per 10 minutes of the clock
    SC_BLOCK, SC_TOL, SC_MIN = 600.0, 0.20, 3
    NEIGHBOUR = "yhs"
    ORDER = [("PICK", "pick"), ("EXCH", "s1_in"), ("AT2", "at_jig"), ("BINW", "bin_work"), ("AT2B", "bin_back"),
             ("AT3", "leave_s2"), ("BACK2", "at_s2")]
    NAMES = {
        "PICK": ("Turn to the blue bin and pick a rail (incl. separator sheet / bin change)", "#16a34a"),
        "EXCH": ("New rail into the greasing machine, greased rail out, hand at its front", "#2563eb"),
        "AT2": ("Step 1 unattended: operator loads and starts step 2", "#94a3b8"),
        "BINW": ("Other work at the bins after the exchange (rails arranged)", "#a855f7"),
        "AT2B": ("Step 1 unattended: operator back at step 2 after the bin work", "#9ca3af"),
        "AT3": ("Step 1 unattended: operator walks to step 3, works there, walks back", "#cbd5e1"),
        "BACK2": ("Step 1 unattended: operator back at step 2 until the next pick", "#64748b"),
    }
    METHOD = [
        "One operator runs steps 1, 2 and 3 in one loop (~14 s). He is followed from frame to frame: the person box with "
        "centre x 0.25-0.85 and at least 0.3 high, nearest to his last position and height (the person at the far left edge "
        "works at another station; a second person who stands at the bins now and then is not followed).",
        "Cycle: he turns to the blue bin for the rail that goes into the machine → the next time. Step-1 visit: bent (box "
        "top below y 0.30) right of x 0.54, or a hand moving low in the front bin area (x 0.59-0.70, y 0.82-0.97, more than "
        "15% of its pixels changing). A second exchange before he has been to step 3 belongs to the same cycle (exchange "
        "done again after a bin change).",
        "Rail into the machine: motion at the step-1 opening (x 0.68-0.74, y 0.52-0.64, more than 10% of the pixels) after "
        "the bin, the start of the last run of such frames (earlier ones are his head or a separator sheet; not counted "
        "while he is bent deep into the bin) · hand leaves step 1: that motion stops (below 5%, gaps up to 0.8 s bridged). "
        "A bend without a rail going in that ends less than 2 s before an exchange is part of its pick (separator sheet, "
        "bin change); after an exchange it is other work at the bins.",
        "Frames missing in the recording (seen at ~1.5-2 frames/s, gaps up to 2.4 s): a bend followed by a gap of 1.5 s "
        "or more, with no exchange within 6 s, is an exchange whose rail-in was not recorded; rail-in motion with no "
        "bend seen (two frames within 2.5 s, or one above 25%) is an exchange with the pick 0.9 s before it.",
        "The rest of the loop: walk to step 3 = his centre leaves his step-2 position (0.015); back at step 2 = centre right "
        "of x 0.52 again (the same rules as steps 2 and 3). Step 1 has no visible machine motion, so its time without the "
        "operator is shown as unattended, split by where he is.",
        "Cycles with frames missing for more than 5 s (recording gaps) are not used.",
        "Self-check: per 10 minutes of the clock, the step-1 cycles are compared with the step-2 lamp cycles on the same "
        "frames; a block that differs by more than 20% (and more than 3) is left out of the statistics and the cycle table.",
        "Checked frame by frame on full-resolution video against 13 loops recorded at ~1.5-2 frames/s (2026-10-15 "
        "21:51-21:55) and 17 loops at ~4.4 frames/s (22:45-22:50; 3 more loops fell in a 31 s recording gap): all found, "
        "pick within 0.3 / 0.16 s, rail in 0.35 / 0.09 s, hand leaves step 1 0.26 / 0.16 s (median). Day crew 2026-10-17 "
        "16:52-17:02 (~4 frames/s): 24 of 24 cycles outside the line stop, no extra cycle; pick 0.21 s, rail in 0.24 s, "
        "hand leaves step 1 0.26 s (median; a bin change can put the pick 3-4 s late).",
        "Event times are the middle between the last frame before and the first frame with the cue.",
    ]
    UNSEEN = ["What his right hand does at the bottom-left corner of the step-1 machine for ~1 s after the exchange (a "
              "clamp or a start button cannot be seen), and when the greasing itself runs: the step-1 machine shows no "
              "visible motion, so its machine time cannot be measured.",
              "Every few loops he lifts a white separator sheet out of the bin (a new layer of rails); this is inside the pick."]

    # ------------------------------------------------------------------ features
    def _features(self, frames):
        rows, prev, tprev, last = [], None, None, None
        for f in frames:
            img = read_frame(f)
            g = lum = NAN
            mo = [NAN] * 4
            if img is not None:
                H, W = img.shape[:2]
                gs, ls = [], []
                for x0, y0, x1, y1 in self.LAMPS:
                    c = img[int(y0 * H):int(math.ceil(y1 * H)), int(x0 * W):int(math.ceil(x1 * W))].reshape(-1, 3).astype(np.float32).mean(0)
                    gs.append(float(c[1] - (c[0] + c[2]) / 2)); ls.append(float(c.mean()))
                g, lum = max(gs), max(ls)
                gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.int16)
                if prev is not None and prev.shape == gray.shape and f["t"] - tprev < 1.0:  # no difference across a gap
                    mo = [float((np.abs(roi(gray, r) - roi(prev, r)) > 20).mean()) for r in (self.BIN, self.S1, self.S3UP, self.RACK)]
                prev, tprev = gray, f["t"]
            cand = []
            for p in f["p"]:
                b = p.get("b")
                if not b or not p.get("k"):
                    continue
                cx = (b[0] + b[2]) / 2
                if self.OP_CX[0] <= cx <= self.OP_CX[1] and b[3] - b[1] > 0.3:
                    d = abs(cx - last[0]) + 0.5 * abs(b[1] - last[1]) if last is not None else 0.0
                    cand.append((d, p, cx))
            op = [NAN] * 6
            if cand:
                _, p, cx = min(cand, key=lambda c: c[0])
                last = (cx, p["b"][1])
                k = p["k"]
                kp = lambda j, c: k[j][c] if k[j][2] > 0.3 else NAN  # noqa: E731
                op = [cx, p["b"][1], kp(9, 0), kp(9, 1), kp(10, 0), kp(10, 1)]
            rows.append([f["t"], g, lum, *mo, *op])
        return np.array(rows, float)

    # ------------------------------------------------------------------ the operator loop (shared by steps 1-3)
    def loops(self, frames):
        """All events of the operator loop on these frames (cached per frame list)."""
        key = (id(frames), len(frames), frames[0]["t"] if frames else 0)
        if getattr(self, "_cache_key", None) == key:
            return self._cache
        A = self._features(frames)
        ev = self._events(A) if len(A) >= 50 else {}
        self._cache_key, self._cache = key, ev
        return ev

    def _events(self, A):
        T, g, lum, mbin, ms1, ms3, mrack, cx, top, Lx, Ly, Rx, Ry = (A[:, j] for j in range(13))
        n = len(T)

        def mid(i):
            return (T[i - 1] + T[i]) / 2 if 0 < i < n and T[i] - T[i - 1] < self.MID_GAP else T[min(i, n - 1)]

        def first(a, b, cond):
            for i in range(max(a, 0), min(b, n)):
                if cond(i):
                    return i
            return None

        def last(a, b, cond):
            for i in range(min(b, n) - 1, max(a, 0) - 1, -1):
                if cond(i):
                    return i
            return None
        seen = ~np.isnan(cx)
        idx = lambda t: int(np.searchsorted(T, t))  # noqa: E731
        # ---- step 2: lamps lit / unlit / unknown (unknown keeps the last state); short spells are glitches: an unlit
        # spell under OFF_MIN s is his head in front of the box, a lit spell under ON_BLIP s is not a start
        st = np.where(np.nan_to_num(g, nan=-99) >= self.LAMP_ON, 1, np.where(np.nan_to_num(g, nan=99) <= self.LAMP_OFF, -1, 0))
        for i in range(1, n):
            if st[i] == 0:
                st[i] = st[i - 1]
        while True:
            runs, i = [], 0
            while i < n:
                j = i
                while j + 1 < n and st[j + 1] == st[i]:
                    j += 1
                runs.append([i, j])
                i = j + 1
            bad = []
            for k, (i, j) in enumerate(runs):
                if 0 < k < len(runs) - 1:
                    dur = T[j + 1] - T[i]
                    if st[i] == 1 and dur < self.ON_BLIP:
                        bad.append((dur, i, j))
                    elif st[i] == -1 and (dur < self.OFF_MIN or j - i < 1):
                        bad.append((dur, i, j))
            if not bad:
                break
            _, i, j = min(bad)
            st[i:j + 1] = -st[i]
        releases, starts = [], []
        for i in range(1, n):
            if st[i - 1] == 1 and st[i] == -1:
                releases.append(mid(i))
            elif st[i - 1] == -1 and st[i] == 1 and releases:
                starts.append(mid(i))
        starts = starts[:len(releases)]
        while len(starts) < len(releases):
            starts.append(None)
        # ---- step 1 visits: bent to the bin on the right, or a hand moving low in the bin
        bent = seen & (np.nan_to_num(top) > self.BENT_TOP) & (np.nan_to_num(cx) > self.BENT_CX)
        low_hand = (np.nan_to_num(Ly) > self.LOW_WY) | (np.nan_to_num(Ry) > self.LOW_WY) | (np.nan_to_num(top) > self.BENT_TOP - 0.03)
        hand_bin = (np.nan_to_num(mbin) > self.BIN_MOT) & (np.nan_to_num(cx, nan=1) > self.BENT_CX - 0.02) & low_hand
        v1 = bent | hand_bin
        visits, i = [], 0
        while i < n:
            if v1[i]:
                j = i
                while True:
                    k = next((q for q in range(j + 1, n) if v1[q]), None)
                    if k is not None and (T[k] - T[j] <= self.VISIT_GAP or (k == j + 1 and T[k] - T[j] <= self.FRAME_GAP)):
                        j = k
                    else:
                        break
                visits.append((i, j))
                i = j + 1
            else:
                i += 1
        m1 = np.nan_to_num(ms1)
        vis1 = []
        for a, b in visits:
            e = {"pick": mid(a), "end_v": T[b], "i0": a, "i1": b}
            # the rail goes into the opening: motion there after the bin (not while he is still deep in the bin)
            i_end = max(int(np.searchsorted(T, T[b] + 1.5)), b + 3)
            qs = [q for q in range(a, min(i_end, n)) if m1[q] > self.S1_MOT
                  and (T[q] - T[a] > 0.25 or np.nan_to_num(top[q], nan=1) <= self.BENT_TOP + 0.01)
                  and not (np.nan_to_num(mbin[q]) > self.BIN_MOT and np.nan_to_num(top[q]) > self.DEEP_TOP)]
            q_in = None
            for q in qs:              # start of the last run (earlier runs: his head or a separator sheet near the opening)
                if q_in is None or T[q] - T[prev_q] > self.S1_RUN:
                    q_in = q
                prev_q = q
            if q_in is not None:
                e["s1_in"] = mid(q_in)
                e["at_jig"], e["q_end"] = self._s1_end(T, m1, q_in, mid)
            else:
                qb = first(b + 1, n, lambda q: seen[q] and top[q] < self.BACK_TOP and cx[q] < self.BACK_CX)
                e["back"] = mid(qb) if qb is not None and T[qb] - T[b] < 5 else mid(min(b + 1, n - 1))
            vis1.append(e)
        # a bend without a rail going in, shortly before an exchange, is part of that pick (separator sheet, bin
        # change); any other one is other work at the bins
        # rail-in motion that no bend explains (frames missing in the recording): an exchange of its own
        used = np.zeros(n, bool)
        for e in vis1:
            used[e["i0"]:max(e["i1"], e.get("q_end", 0)) + 1] = True
        q = 0
        while q < n:
            two = any(m1[r] > self.S1_MOT and not used[r] for r in range(q + 1, n) if T[r] - T[q] <= 2.5)
            if m1[q] > self.S1_MOT and not used[q] and seen[q] and cx[q] > self.BENT_CX and (two or m1[q] > self.S1_ALONE):
                at_jig, qe = self._s1_end(T, m1, q, mid)
                vis1.append({"pick": mid(q) - self.PICK_LEAD, "s1_in": mid(q), "at_jig": at_jig, "q_end": qe, "end_v": T[q],
                             "estimated": True})
                q = qe + 1
            else:
                q += 1
        vis1.sort(key=lambda e: e["pick"])
        # a bend without a seen rail-in, with frames missing right after it and no other exchange near: the rail went in
        # while no frames were recorded
        for e in vis1:
            if "s1_in" in e or "i0" not in e:
                continue
            j1 = min(e["i1"] + 3, n - 1)
            gap = any(T[q + 1] - T[q] >= self.MISS_GAP for q in range(e["i0"], j1))
            near = any("s1_in" in x and abs(x["pick"] - e["pick"]) < self.MISS_FREE for x in vis1 if x is not e)
            if gap and not near:
                e["s1_in"], e["at_jig"], e["estimated"] = None, e["back"], True
        s1, binw = [], []
        for k, e in enumerate(vis1):
            if "s1_in" in e:
                s1.append(e)
                continue
            nxt = next((x for x in vis1[k + 1:] if "s1_in" in x), None)
            if nxt is not None and nxt["pick"] - e["end_v"] <= self.MERGE_S1:
                nxt["pick"] = min(nxt["pick"], e["pick"])
            else:
                binw.append((e["pick"], e["back"]))
        # ---- step 3 visits: centre left of S3_CX
        at3 = seen & (np.nan_to_num(cx, nan=1) < self.S3_CX)
        v3, i = [], 0
        while i < n:
            if at3[i]:
                j = i
                while j + 1 < n and (at3[j + 1] or not seen[j + 1]) and T[j + 1] - T[j] < 2.0:
                    j += 1
                while j > i and not at3[j]:
                    j -= 1
                # he stepped away from step 3 and came back without going to step 2: the same visit (rails arranged
                # on the rack, press restarted at its panel, waited while the steps 4-5 operator was at the rack)
                if v3 and T[i] - T[v3[-1][1]] < self.S3_MERGE and not any(
                        seen[r] and cx[r] >= self.S2_CX for r in range(v3[-1][1] + 1, i)):
                    v3[-1] = (v3[-1][0], j)
                else:
                    v3.append((i, j))
                i = j + 1
            else:
                i += 1
        s3 = []
        for a, b in v3:
            # arrived: within S3_ARRIVE of his left-most position in the first ARRIVE_WIN s of the visit; leaves: last
            # frame within S3_LEAVE of his left-most position in its last ARRIVE_WIN s (in a long visit he also goes
            # further left to the rack)
            b0 = idx(T[b] - self.ARRIVE_WIN)
            e = {}
            if self.ARRIVE_LOOK:      # the walk ends: he gets no more than S3_ARRIVE further left in the next ARRIVE_LOOK s
                q = first(a, b + 1, lambda q: seen[q] and cx[q] <= np.nanmin(cx[q:max(idx(T[q] + self.ARRIVE_LOOK), q + 1)])
                          + self.S3_ARRIVE)
            else:
                mn = float(np.nanmin(cx[a:max(idx(T[a] + self.ARRIVE_WIN), a + 1)]))
                q = first(a, b + 1, lambda q: seen[q] and cx[q] <= mn + self.S3_ARRIVE)
            e["at_s3"] = mid(q if q is not None else a)
            mn = float(np.nanmin(cx[min(b0, b):b + 1]))
            ql = last(a, b + 1, lambda q: seen[q] and cx[q] <= mn + self.S3_LEAVE)
            if ql is None:  # his position not measured near the end of the visit (merged visit, start-up): its last frame
                ql = b
            e["leave_s3"] = mid(ql + 1) if ql + 1 < n else T[ql]
            # walk there: his step-2 position over the 2.5 s before the walk; the walk starts when he leaves it
            p0 = int(np.searchsorted(T, T[a] - 2.5))
            pre = [q for q in range(p0, a) if seen[q] and cx[q] > self.S3_CX]
            if pre:
                base = float(np.nanmedian(cx[pre[: max(1, len(pre) // 2 + 1)]]))
                ls = last(p0, a, lambda q: seen[q] and cx[q] >= base - self.LEAVE_DROP)
                e["leave_s2"] = mid(ls + 1) if ls is not None else mid(a)
            else:
                e["leave_s2"] = mid(a)
            qb = first(ql + 1, n, lambda q: seen[q] and cx[q] >= self.S2_CX)
            if qb is not None and T[qb] - T[ql] < 6:
                e["at_s2"] = mid(qb)
            # rail on the rack: left wrist low at the left, or motion at the rack (from RACK_AFTER s after he arrived)
            r0 = int(np.searchsorted(T, e["at_s3"] + self.RACK_AFTER))
            r1 = int(np.searchsorted(T, e["leave_s3"] + 0.3))
            qr = first(r0, r1, lambda q: ok(Lx[q], Ly[q]) and Lx[q] <= self.RACK_WX and Ly[q] >= self.RACK_WY)
            if qr is None:
                qr = first(r0, r1, lambda q: np.nan_to_num(mrack[q]) > self.RACK_MOT)
            if qr is not None:
                e["rack"] = min(mid(qr), e["leave_s3"])
            s3.append(e)
        # step-3 press: motion of its upper slides while he is away (right of AWAY_CX): the first within PRESS_WIN s after
        # he left, the last within PRESS_SPAN s after he left and before he is back
        cxf = cx.copy()                  # not detected: still where he was last seen
        for i in range(1, n):
            if np.isnan(cxf[i]):
                cxf[i] = cxf[i - 1]
        away = np.nan_to_num(cxf) > self.AWAY_CX
        pm = away & (np.nan_to_num(ms3) > self.PRESS_MOT)
        for k, e in enumerate(s3):
            nxt = s3[k + 1]["at_s3"] if k + 1 < len(s3) else T[-1]
            i0 = int(np.searchsorted(T, e["leave_s3"]))
            i1 = int(np.searchsorted(T, min(nxt, e["leave_s3"] + self.PRESS_SPAN)))
            q = first(i0, i1, lambda q: pm[q] and T[q] - e["leave_s3"] <= self.PRESS_WIN)
            if q is not None:
                e["press_on"] = mid(q)
                ql = last(q, i1, lambda q: pm[q])
                e["press_off"] = T[ql] if ql + 1 >= n else (T[ql] + T[ql + 1]) / 2
        holes = [(T[i], T[i + 1]) for i in range(n - 1) if T[i + 1] - T[i] > self.HOLE]
        return {"releases": releases, "starts": starts, "s1": s1, "binw": binw, "s3": s3, "holes": holes}

    def _s1_end(self, T, m1, q_in, mid):
        """His hand stays at step 1 while there is motion at the opening (gaps up to S1_GAP bridged): (time, last index)."""
        q, n = q_in, len(T)
        while True:
            k = next((r for r in range(q + 1, n) if m1[r] > self.S1_END), None)
            if k is not None and T[k] - T[q] <= self.S1_GAP and T[k] - T[q_in] < 5.0:
                q = k
            else:
                break
        return (mid(q + 1) if q + 1 < n else T[q]), q

    # ------------------------------------------------------------------ cycles of this station
    def detect(self, frames):
        ev = self.loops(frames)
        if not ev:
            return []
        s1, s3 = [], ev["s3"]
        for e in ev["s1"]:
            # a second exchange before he has been to step 3 belongs to the same loop (exchange done again, bin change)
            if (self.ONE_PER_S3 and s1 and e["pick"] - s1[-1]["pick"] < self.MAX_CYCLE
                    and not any(s1[-1]["pick"] < x["at_s3"] < e["pick"] for x in s3)):
                continue
            s1.append(e)
        cyc = []
        for e, nx in zip(s1, s1[1:]):
            if nx["pick"] - e["pick"] > self.MAX_CYCLE:
                continue
            c = {"start": e["pick"], "end": nx["pick"], "pick": e["pick"]}
            for k in ("s1_in", "at_jig"):
                if e.get(k) is not None and e[k] < c["end"]:
                    c[k] = e[k]
            if e.get("estimated"):
                c["note"] = "frames missing at step 1: exchange times estimated"
            v = next((x for x in s3 if c.get("at_jig", c["start"]) <= x.get("leave_s2", -1) < c["end"]), None)
            if v is not None:
                c["leave_s2"] = v["leave_s2"]
                if v.get("at_s2") is not None and v["at_s2"] < c["end"]:
                    c["at_s2"] = v["at_s2"]
            bw = [w for w in ev["binw"] if c.get("at_jig", c["start"]) <= w[0] < c.get("leave_s2", c["end"])]
            if bw:
                c["bin_work"], c["bin_back"] = bw[0][0], min(bw[0][1], c.get("leave_s2", c["end"]))
            cyc.append(c)
        return self._self_check(cyc, ev)

    def _anchor_times(self, key, ev):
        if key == "yur":
            return [e["pick"] for e in ev["s1"]]
        if key == "yhs":
            return list(ev["releases"])
        return [e["at_s3"] for e in ev["s3"]]

    def _self_check(self, cycles, ev):
        """Cycles against the neighbour station's cycles on the same frames, per 10 minutes of the clock; a block that
        differs by more than SC_TOL (and more than SC_MIN) is left out of the statistics and the cycle table. Cycles with
        frames missing for more than HOLE s (recording gaps) are dropped first."""
        cycles = [c for c in cycles if not any(c["start"] < b and a < c["end"] for a, b in ev["holes"])]
        mine = [c["start"] for c in cycles]
        other = self._anchor_times(self.NEIGHBOUR, ev)
        blocks = {}
        for t in mine:
            blocks.setdefault(int(t // self.SC_BLOCK), [0, 0])[0] += 1
        for t in other:
            blocks.setdefault(int(t // self.SC_BLOCK), [0, 0])[1] += 1
        self.check, keep_b = [], set()
        for b in sorted(blocks):
            nm, no = blocks[b]
            good = abs(nm - no) <= max(self.SC_TOL * max(nm, no), self.SC_MIN)
            self.check.append({"block": b * self.SC_BLOCK, "mine": nm, "other": no, "ok": good})
            if good:
                keep_b.add(b)
        return [c for c in cycles if int(c["start"] // self.SC_BLOCK) in keep_b]

    def _check_text(self, mine, other):
        chk = getattr(self, "check", [])
        if not chk:
            return []
        bad = [b for b in chk if not b["ok"]]
        out = [f"Self-check, {mine} / {other} per 10 minutes: "
               + ", ".join(f"{hm(b['block'])[:5]} {b['mine']}/{b['other']}{'' if b['ok'] else ' left out'}" for b in chk) + "."]
        if bad:
            out.insert(0, f"Self-check: {len(bad)} of {len(chk)} ten-minute blocks differ from the {other} by more than "
                          f"{100 * self.SC_TOL:.0f}% and are left out of the statistics and the cycle table (not validated).")
        return out

    def extra(self, cycles):
        out = []
        w = [c["at_jig"] - c["start"] for c in cycles if "at_jig" in c]
        if w:
            sec = [c["end"] - c["start"] for c in cycles]
            out.append(f"Operator work at step 1 (turn, pick, rail in, greased rail out) median {stat.median(w):.1f}s of a "
                       f"{stat.median(sec):.1f}s cycle; the rest step 1 is unattended while he works at steps 2 and 3.")
        lp = [c["s1_in"] - c["pick"] for c in cycles if "s1_in" in c]
        if lp:
            long_ = sum(1 for v in lp if v > 1.6)
            out.append(f"Pick from the bin median {stat.median(lp):.1f}s; {long_} of {len(lp)} picks took over 1.6 s "
                       f"(separator sheet lifted out or bin change).")
        bw = [c for c in cycles if "bin_work" in c]
        if bw:
            out.append(f"Other work at the bins after the exchange in {len(bw)} of {len(cycles)} cycles "
                       f"(median {stat.median([c['bin_back'] - c['bin_work'] for c in bw]):.1f}s).")
        return out + self._check_text("step-1 cycles", "step-2 lamp cycles")


class YHS(YUR):
    """YRA SEAT SLIDER, step 2 "Handle Supt Greasing & Spr Supt Greasing" (station 14; camera 14 = camera 8). The same
    operator and loop as YUR (see there). The step-2 machine state is seen on its button box: the two green lamps are
    lit from the moment he starts it until he releases the jig, which he does standing at the jig with his right hand at
    the box (once the lamps stayed lit for 28 s while he had walked away, so the release is his action, not a timer).
    What his hands do at the jig is hidden by his back."""
    key, station_id, title = "yhs", 14, "Handle Supt & Spr Supt Greasing m/c (YRA step 2)"
    NEIGHBOUR = "yur"
    ORDER = [("OPEN", "release"), ("LOAD", "at_jig"), ("ON", "lamp_on"), ("WALK", "leave_s2"), ("AT3", "at_s3"),
             ("BACK", "leave_s3"), ("END", "at_s2")]
    NAMES = {
        "OPEN": ("Jig released, waits while the operator is at step 1", "#94a3b8"),
        "LOAD": ("At the jig: rails changed, parts from the small blue bin, start (hidden)", "#2563eb"),
        "ON": ("Lamps lit (machine on), hands still at the jig", "#0891b2"),
        "WALK": ("Walk to step 3 with a rail (machine on)", "#f59e0b"),
        "AT3": ("Operator at step 3 (machine on)", "#cbd5e1"),
        "BACK": ("Walk back to step 2 (machine on)", "#fbbf24"),
        "END": ("Lamps lit, operator back at the jig until he releases it", "#6366f1"),
    }
    METHOD = [
        "One operator runs steps 1, 2 and 3 in one loop (~14 s), followed from frame to frame (person box centre x "
        "0.25-0.85, at least 0.3 high, nearest to his last position).",
        "Cycle: the two lamps of the step-2 button box (x 0.63-0.65, y 0.35) go off → next time. Lamp lit = green minus "
        "red/blue above 18.5, unlit below 15.5, in between = unchanged; an unlit spell shorter than 0.9 s is his head in "
        "front of the box, a lit spell shorter than 2.5 s is a flash while he presses the buttons, not a start.",
        "At the jig after step 1: his hand leaves the step-1 machine (end of the motion at the step-1 opening); if the "
        "step-1 exchange was done before the release he is at the jig from the release on · machine started: the lamps "
        "light again · walk to step 3: his centre leaves his step-2 position (0.015) · at step 3: the walk ends (his centre "
        "gets no more than 0.03 further left in the next 1.5 s) · walk back: leaves it · back at step 2: centre right of "
        "x 0.52. Day crew order (step 1 before step 2, release before the walk to step 3): the walk and step 3 fall inside "
        "'jig released' and are not shown as their own elements.",
        "Machine time (lamps lit) runs from the start to the release and is shown with each cycle. Rare cases are kept "
        "inside the main elements and counted in the findings: other work at the bins before the start (inside 'at the "
        "jig') and the next step-1 exchange done before the release (inside 'lamps lit until he releases it').",
        "Checked frame by frame on full-resolution video against 13 loops at ~1.5-2 frames/s and 17 at ~4.4 frames/s: all "
        "found; release within 0.16 / 0.31 s, at the jig 0.19 / 0.17 s, start 0.33 / 0.09 s, walk 0.18 / 0.16 s (median). "
        "Day crew 2026-10-17 16:52-17:02: 24 of 24 cycles, no extra cycle; release 0.06 s, lamps on 0.07 s (median).",
        "Self-check: per 10 minutes of the clock, the step-2 lamp cycles are compared with the step-1 cycles on the same "
        "frames; a block that differs by more than 20% (and more than 3) is left out of the statistics and the cycle table.",
        "Event times are the middle between the last frame before and the first frame with the cue.",
    ]
    UNSEEN = ["What he does at the jig: his back hides his hands (finished rail out, greased rail from step 1 in, handle "
              "and spring supports from the small blue bin on top).",
              "Whether the machine has finished well before he releases the jig: the lamps stay lit until he acts, so the "
              "time at the jig with the lamps lit may partly be waiting.",
              "Where exactly the rail he carries to step 3 comes from (it is in his right hand when he walks)."]

    def detect(self, frames):
        ev = self.loops(frames)
        if not ev:
            return []
        rel, sta, s1, s3 = ev["releases"], ev["starts"], ev["s1"], ev["s3"]
        cyc = []
        for k, (r, rn) in enumerate(zip(rel, rel[1:])):
            if rn - r > self.MAX_CYCLE:
                continue
            c = {"start": r, "end": rn, "release": r}
            if sta[k] is not None and sta[k] < rn:
                c["lamp_on"] = sta[k]
            lo = c.get("lamp_on", rn)
            ex = next((e for e in s1 if r - 1.0 <= e["pick"] < lo), None)
            if ex is None:
                c["at_jig"] = r              # the step-1 exchange was done before the release: he is at the jig
            elif ex.get("at_jig") is not None and ex["at_jig"] < lo:
                c["at_jig"] = ex["at_jig"]
            bw = [w for w in ev["binw"] if c.get("at_jig", r) <= w[0] < lo]
            if bw:
                c["bin_work"], c["bin_back"] = bw[0][0], min(bw[0][1], lo)
            v = next((x for x in s3 if lo - 0.5 <= x.get("leave_s2", -1) < rn), None)
            if v is not None:
                for kk in ("leave_s2", "at_s3", "leave_s3", "at_s2"):
                    if v.get(kk) is not None and v[kk] < rn:
                        c[kk] = v[kk]
            e2 = next((e for e in s1 if c.get("at_s2", lo) <= e["pick"] < rn - 1.0), None)
            if e2 is not None:
                c["s1_early"] = e2["pick"]
                if e2.get("at_jig") is not None and e2["at_jig"] < rn:
                    c["s1_early_back"] = e2["at_jig"]
            if "lamp_on" in c:
                c["machine"] = {"Lamps lit": (c["lamp_on"], rn)}
            cyc.append(c)
        return self._self_check(cyc, ev)

    def extra(self, cycles):
        out = []
        on = [c["end"] - c["lamp_on"] for c in cycles if "lamp_on" in c]
        if on:
            off = [c["lamp_on"] - c["start"] for c in cycles if "lamp_on" in c]
            wt = [c["at_jig"] - c["start"] for c in cycles if "at_jig" in c]
            out.append(f"Lamps lit (machine on) median {stat.median(on):.1f}s per cycle; jig released median "
                       f"{stat.median(off):.1f}s, of which median {stat.median(wt):.1f}s the jig waits while he is at step 1.")
        w = [c["at_s2"] - c["leave_s2"] for c in cycles if "at_s2" in c and "leave_s2" in c]
        if w:
            out.append(f"Away to step 3 (walk there, work, walk back) median {stat.median(w):.1f}s per cycle.")
        e = [c for c in cycles if "s1_early" in c]
        if e:
            out.append(f"In {len(e)} of {len(cycles)} cycles he did the next step-1 exchange before releasing the jig "
                       f"(inside 'lamps lit until he releases it').")
        b = [c for c in cycles if "bin_work" in c]
        if b:
            out.append(f"In {len(b)} of {len(cycles)} cycles he went back to the bins for other work before starting the "
                       f"machine (inside 'at the jig').")
        return out + self._check_text("step-2 lamp cycles", "step-1 cycles")


class YXL(YUR):
    """YRA SEAT SLIDER, step 3 "Upper Rail X Lock Mecha Assy m/c" (station 15; camera 15 = camera 8). The same operator
    and loop as YUR (see there). He arrives with a dark rail in his right hand, works at the nest with both hands (hidden
    by his back), lays a finished rail on the yellow rack at the left front with his left hand and walks back empty-handed.
    The machine starts ~0.7 s after he leaves and presses twice: the two upper slides come down 0.5-4 s after he left,
    the slides and the bed move again 7-10.5 s after he left; then it stands still until he is back (~2.6 s)."""
    key, station_id, title = "yxl", 15, "Upper Rail X Lock Mecha Assy m/c (YRA step 3)"
    NEIGHBOUR = "yhs"
    ORDER = [("NEST", "at_s3"), ("RACK", "rack"), ("PRESS", "leave_s3"), ("IDLE", "idle"), ("WALK", "leave_s2")]
    NAMES = {
        "NEST": ("At the nest: his rail in, finished rail out (hands hidden)", "#2563eb"),
        "RACK": ("Lay the finished rail on the rack (left front)", "#16a34a"),
        "PRESS": ("Operator leaves; machine presses (two strokes)", "#f59e0b"),
        "IDLE": ("Machine done, waits for the operator", "#dc2626"),
        "WALK": ("Operator walks over with the next rail (machine waits)", "#fca5a5"),
    }
    METHOD = [
        "One operator runs steps 1, 2 and 3 in one loop (~14 s), followed from frame to frame (person box centre x "
        "0.25-0.85, at least 0.3 high, nearest to his last position).",
        "Cycle: he arrives at step 3 → next time. At step 3 = centre left of x 0.42; visits less than 10 s apart with no "
        "return to step 2 (centre right of x 0.52) between them are one visit (rails arranged on the rack, the press reset "
        "at its panel, a wait while someone takes rails from the rack). Arrived = the walk ends: his centre gets no more "
        "than 0.03 further left in the next 1.5 s (a wait beside the running press belongs to step 3); leaves = last frame "
        "within 0.02 of his left-most position in the last 3 s of the visit.",
        "Rail on the rack: his left wrist left of x 0.27 and below y 0.50, or motion at the rack (x 0.17-0.26, y 0.54-0.64), "
        "from 0.3 s after he arrived · walk over with the next rail: his centre leaves his step-2 position (0.015).",
        "Machine presses: motion of the upper slides (x 0.27-0.42, y 0.22-0.40, more than 8% of the pixels changing) while "
        "he is right of x 0.45; the first within 4 s after he left; the last within 12 s after he left and before he is "
        "back = machine done. From then until he arrives the machine waits for him.",
        "Self-check: per 10 minutes of the clock, the step-3 cycles are compared with the step-2 lamp cycles on the same "
        "frames; a block that differs by more than 20% (and more than 3) is left out of the statistics and the cycle table.",
        "Checked frame by frame on full-resolution video against 13 loops at ~1.5-2 frames/s and 16 at ~4.4 frames/s: all "
        "found; arrival within 0.24 / 0.20 s, rail on the rack 0.26 / 0.23 s, leaves 0.14 / 0.07 s, press start 0.16 / "
        "0.10 s, press end 0.21 / 0.07 s (median). At ~1.5-2 frames/s the press is not seen in 3 of 13 cycles (frames "
        "missing). Day crew 2026-10-17 16:52-17:02: 23 of 23 cycles outside the line stop, no extra cycle; arrival 0.22 s, "
        "leaves 0.42 s (median; he leaves the nest first and stands beside the press before he walks).",
        "Event times are the middle between the last frame before and the first frame with the cue.",
    ]
    UNSEEN = ["What he does at the nest (hands hidden by his back): taking the assembled rail out, putting his rail and any "
              "parts in, starting the machine.",
              "Whether a rail is ever rejected: no reject place was seen."]

    def detect(self, frames):
        ev = self.loops(frames)
        if not ev:
            return []
        s3 = ev["s3"]
        cyc = []
        for e, nx in zip(s3, s3[1:]):
            if nx["at_s3"] - e["at_s3"] > self.MAX_CYCLE:
                continue
            c = {"start": e["at_s3"], "end": nx["at_s3"], "at_s3": e["at_s3"]}
            for k in ("rack", "leave_s3", "at_s2", "press_on", "press_off"):
                if e.get(k) is not None and e[k] < c["end"]:
                    c[k] = e[k]
            if nx.get("leave_s2") is not None and c.get("leave_s3", c["start"]) < nx["leave_s2"] < c["end"]:
                c["leave_s2"] = nx["leave_s2"]
            if "press_off" in c and ("leave_s2" not in c or c["press_off"] <= c["leave_s2"]):
                c["idle"] = c["press_off"]      # machine done before he set off with the next rail: it waits
            if "press_on" in c:
                c["machine"] = {"Press": (c["press_on"], c.get("press_off", c["press_on"]))}
            cyc.append(c)
        return self._self_check(cyc, ev)

    def extra(self, cycles):
        out = []
        m = [c["press_off"] - c["leave_s3"] for c in cycles if "press_off" in c and "leave_s3" in c]
        idle = [c["end"] - c["press_off"] for c in cycles if "press_off" in c]
        if m:
            out.append(f"Machine works for median {stat.median(m):.1f}s after he leaves (start ~"
                       f"{stat.median([c['press_on'] - c['leave_s3'] for c in cycles if 'press_on' in c and 'leave_s3' in c]):.1f}s "
                       f"after he leaves, two strokes); then it waits median {stat.median(idle):.1f}s for him.")
        at = [c["leave_s3"] - c["start"] for c in cycles if "leave_s3" in c]
        if at:
            out.append(f"Operator at step 3 median {stat.median(at):.1f}s per cycle; finished rail laid on the rack seen in "
                       f"{sum(1 for c in cycles if 'rack' in c)} of {len(cycles)} cycles.")
        return out + self._check_text("step-3 cycles", "step-2 lamp cycles")


# ======================================================================== yg1 / yg2: Guide S/A Insert #1 / #2, YRA line (camera 9)
class YG1:
    """YRA SEAT SLIDER, step 4 "Guide S/A Insert #1 m/c" (station 9). Cameras 9 and 10 are one physical camera
    (192.168.31.32, overlay YRA_SS_SEAT_TRACK); only camera 9 is recorded, so steps 4 and 5 (YG1, YG2) both run on it.
    Step 4 is the RIGHT machine (the user's part zone x 0.51-0.83), step 5 the LEFT machine (x 0.23-0.53).
    Watched frame by frame on two 1600x900 videos: 2026-10-15 21:55:05-21:59:05 (night; the camera-9 recording ran at
    only ~1.5 frames/s then) and 2026-10-16 09:28:43-09:37:43 (day; recording at ~4.5 frames/s).

    One operator (blue shirt, cap, white gloves) runs BOTH machines in one loop of ~26.5 s, one rail per machine per
    loop. Both machines use the same yellow rail stand (trolley) in front of them: he lays each finished rail in the
    upper yellow comb of the stand and takes the next rail from the lower bars of the stand. The person at the machine
    in the bottom-left corner takes rails out of the upper comb (seen right after the operator put one there) and reaches
    to the lower bars now and then; the people at the far left and at the back are not part of steps 4-5. The night
    operator (short sleeves) and the day operator (long sleeves, glasses) are different people doing the same loop.
    Seen per visit to a machine (median seconds after he arrives, night / day, step 4):
      he arrives from the other machine -> hands between the two teal parts bins (left and right of the fixture) and
      the machine: green guide parts set in (if the machine is still running he takes parts meanwhile) -> he turns away
      with the finished rail (4.0 / 4.2) -> lays it in the upper yellow comb of the stand (4.8 / 5.0) -> takes the
      next rail from the lower bars of the stand (5.8 / 5.5) -> back at the machine (6.7 / 7.5) -> rail into the machine,
      more guide parts from both bins -> leaves for the other machine (10.3 / 10.7); the walk between the machines takes
      ~1 s. Once (day, 09:32:55) both hands were inside the machine for ~6 s before the rail came out.
    Step-4 machine: a small green lamp at its carriage (x 0.718, y 0.278) lights a fixed time after he leaves (2.4-2.7 s
    at night, 1.4-1.6 s in the day video) and stays lit 12.1-12.2 s (the carriage moves in that time); then the machine
    waits until he is back (at night in 4 of 8 cycles he was back before the lamp went off and took parts meanwhile).
    """
    key, cams, station_id, title = "yg1", (9,), 9, "Guide S/A Insert #1 m/c (YRA step 4)"
    MACH, OTHER, NEIGHBOUR = 4, 5, "yg2"
    # the operator: person box with centre x in OP_CX and top above OP_TOP (the person in the bottom-left corner and
    # people passing in front are lower in the picture), followed from frame to frame
    OP_CX, OP_TOP = (0.28, 0.80), 0.40
    TOP_AT = 0.22                       # standing at a machine: box top at or above y 0.22 (further from the camera) ...
    X4, X5 = 0.585, 0.435               # ... and box centre x right of 0.585 (step 4) or left of 0.435 (step 5)
    SEEN_GAP = 1.0                      # frames without him up to this long keep his last place
    TRIP_MAX = 11.0                     # away from a machine and back at it within this = the trip to the stands (8 s
                                        # split two day-crew visits: rail held up and checked for 7 s, a talk at the stand)
    STAND_TOP, STAND_BOT, STAND_WY = 0.235, 0.86, 0.53  # at the stands: box top below 0.235, bottom below 0.86 or a wrist below 0.53
    TRIP_GAP = 1.5                      # ... or no frames for at least this long (recording gap) while he was away
    TRIP_MIN = 0.8                      # the exchange is the longest such departure, at least this long
    CROWN = (0.33, 0.555, 0.465, 0.80)  # upper yellow comb of the stand (finished rails): a wrist here = rail put down
    RACK = (0.455, 0.62, 0.68, 0.95)    # lower bars of the stand (rails to load): a wrist here = next rail taken
    PLACE_AT, PICK_AT = 0.30, 0.55      # no wrist seen there: estimated at this share of the trip
    LAMPS = {4: (0.718, 0.278, 0.005), 5: (0.458, 0.267, 0.006)}  # lamp x, y, half size (share of the width)
    LEVEL_BLOCK = 600.0                 # lamp lit / unlit levels found per 10 minutes (they differ by day and night)
    LEVEL_MIN = 10.0                    # lit and unlit levels at least this far apart, else no lamp state
    SPELL = {4: (1.0, 2.0), 5: (1.6, 1.0)}  # shortest real unlit / lit spell (s); shorter = his head or arm in front
    START_WIN = (0.0, 6.0)              # step 4: lamp lights within this after he left (seen: 2.4-2.7 s)
    RUN_MAX = 20.0                      # lamp lit at most this long
    MID_GAP = 3.0                       # event between two frames up to this far apart: the middle; else the later frame
    MAX_CYCLE = 60.0
    HOLE = 5.0                          # frames missing for longer than this inside a cycle: the cycle is not used
    SC_BLOCK, SC_TOL, SC_MIN = 600.0, 0.20, 3
    ORDER = [("WAITM", "start"), ("PARTS", "parts"), ("OUT", "rail_out"), ("SWAP", "place"), ("BACK", "pick"),
             ("LOAD", "back"), ("START", "leave"), ("RUN", "machine_on"), ("IDLE", "machine_off")]
    NAMES = {
        "WAITM": ("Machine still running when he arrives (he takes guide parts meanwhile)", "#fca5a5"),
        "PARTS": ("At the machine before the rail exchange: guide parts from both bins", "#2563eb"),
        "OUT": ("Finished rail out, carried to the stand in front", "#f59e0b"),
        "SWAP": ("Rail laid in the upper yellow comb, reach down to the lower bars", "#be185d"),
        "BACK": ("Next rail taken from the lower bars, walk back", "#16a34a"),
        "LOAD": ("Rail into the machine, guide parts from both bins", "#0891b2"),
        "START": ("Operator walks to step 5; machine starts ~2.5 s later", "#cbd5e1"),
        "RUN": ("Machine runs (green lamp lit); operator at step 5", "#94a3b8"),
        "IDLE": ("Machine done, waits for the operator", "#dc2626"),
    }
    METHOD = [
        "One operator runs steps 4 and 5 (the right and the left machine) in one loop of ~26.5 s. He is followed from "
        "frame to frame: the person box with centre x 0.28-0.80 and top above y 0.40, nearest to his last position.",
        "At a machine = box top at or above y 0.22 and centre x right of 0.585 (step 4) or left of 0.435 (step 5). "
        "Cycle: he arrives at step 4 -> the next time. Away from step 4 and back within 11 s, with a frame at the stands "
        "(box top below 0.235, box bottom below 0.86 or a wrist below y 0.53), the longest such departure of at least "
        "0.8 s = the rail exchange: rail out = he leaves "
        "the machine, back = he is at the machine again; leaves = he goes on to step 5.",
        "Rail put down = first wrist at the upper yellow comb of the stand (x 0.33-0.465, y 0.555-0.80); next rail = then "
        "the first wrist at its lower bars (x 0.455-0.68, y 0.62-0.95). Not seen (frames missing): estimated at 30% / 55% "
        "of the trip.",
        "Machine: the green lamp at the step-4 carriage (x 0.718, y 0.278; green minus red/blue). Lit and unlit levels are "
        "found per 10 minutes (they differ between day and night); unlit spells under 1 s are his head in front. "
        "Lamp lit within 6 s after he left = machine runs; lamp off before he is back = the machine waits for him; "
        "lamp still lit when he arrives = he waits for the machine (he takes guide parts meanwhile).",
        "Self-check: per 10 minutes of the clock, the step-4 cycles are compared with his visits to step 5 on the same "
        "frames; a block that differs by more than 20% (and more than 3) is left out of the statistics and the cycle table. "
        "Cycles with frames missing for more than 5 s (recording gaps) are not used.",
        "Checked frame by frame on full-resolution video: 8 cycles recorded at ~1.5 frames/s (2026-10-15 21:55-21:59) "
        "and 19 at ~4.5 frames/s (2026-10-16 09:29-09:37): all found. Median error at 1.5 / 4.5 frames/s: arrival 0.23 / "
        "0.21 s, rail out 0.31 / 0.06 s, rail put down 0.19 / 0.07 s, next rail 0.18 / 0.07 s, back 0.28 / 0.06 s, "
        "leaves 0.19 / 0.16 s, lamp on 0.24 / 0.09 s, lamp off 0.21 / 0.07 s. The 19 day cycles with only every third "
        "frame (1.5 frames/s): all found, 0.10-0.28 s. Day crew 2026-10-17 16:52-17:02 (~4 frames/s): 13 of 13 cycles "
        "outside the line stop, no extra cycle; arrival 0.34 s, rail out 0.12 s, leaves 0.09 s, lamp on 0.08 s (median).",
        "Event times are the middle between the last frame before and the first frame with the cue.",
    ]
    UNSEEN = ["What exactly he does with the guide parts: his back hides his hands at the fixture. Both hands go into the "
              "two teal bins several times per rail; the number of parts per rail cannot be counted on the recordings.",
              "What starts the step-4 machine: its lamp lights a fixed time after he leaves (2.4-2.7 s at night, "
              "1.4-1.6 s in the day video); a start button pressed while leaving or a light curtain with a delay cannot "
              "be told apart, and why the delay changed between the two videos is not visible.",
              "Which station the person at the bottom-left machine belongs to, and who fills the lower bars of the stand: "
              "he takes rails out of the upper comb and reaches to the lower bars now and then, but the rails cannot be "
              "followed on the camera.",
              "Whether steps 4 and 5 work in series (a rail through both machines) or side by side: both lay their "
              "finished rails in the same upper comb and take from the same lower bars, and the rails look alike."]

    # ------------------------------------------------------------------ features
    def _features(self, frames):
        rows, last = [], None
        for f in frames:
            img = read_frame(f)
            gl = [NAN, NAN]
            if img is not None:
                H, W = img.shape[:2]
                for k, m in enumerate((4, 5)):
                    x, y, h = self.LAMPS[m]
                    r = max(2, int(round(h * W)))
                    X, Y = int(x * W), int(y * H)
                    p = img[Y - r:Y + r + 1, X - r:X + r + 1].reshape(-1, 3).astype(np.float32)
                    gl[k] = float(np.percentile(p[:, 1] - (p[:, 0] + p[:, 2]) / 2, 90))
            cand = []
            for p in f["p"]:
                b = p.get("b")
                if not b or not p.get("k"):
                    continue
                cx = (b[0] + b[2]) / 2
                if self.OP_CX[0] <= cx <= self.OP_CX[1] and b[1] < self.OP_TOP:
                    d = abs(cx - last[0]) + 0.5 * abs(b[1] - last[1]) if last is not None else 0.0
                    cand.append((d, p, cx))
            op = [NAN] * 7
            if cand:
                _, p, cx = min(cand, key=lambda c: c[0])
                last = (cx, p["b"][1])
                k = p["k"]
                kp = lambda j, c: k[j][c] if k[j][2] > 0.3 else NAN  # noqa: E731
                op = [cx, p["b"][1], p["b"][3], kp(9, 0), kp(9, 1), kp(10, 0), kp(10, 1)]
            rows.append([f["t"], *gl, *op])
        return np.array(rows, float)

    # ------------------------------------------------------------------ lamps
    @staticmethod
    def _levels(v):
        """Two-level split (unlit / lit) of lamp values; None if the two levels are not apart."""
        v = v[~np.isnan(v)]
        if len(v) < 40:
            return None
        lo, hi = np.percentile(v, [2, 98])
        best = None
        for thr in np.linspace(lo + 1, hi - 1, 60):
            a, b = v[v < thr], v[v >= thr]
            if len(a) < 10 or len(b) < 10:
                continue
            sc = len(a) * len(b) * (b.mean() - a.mean()) ** 2
            if best is None or sc > best[0]:
                best = (sc, float(np.median(a)), float(np.median(b)))
        return None if best is None else (best[1], best[2])

    def _lamp_runs(self, T, g, mach, mid):
        """Lit spells (t_on, t_off) of a lamp. A value below 0 is his blue shirt in front (unknown)."""
        n = len(T)
        g = np.where(g < 0, NAN, g)
        whole = self._levels(g)
        st = np.zeros(n, int)
        for b0 in np.arange(T[0], T[-1] + 1e-6, self.LEVEL_BLOCK):
            i0, i1 = np.searchsorted(T, b0), np.searchsorted(T, b0 + self.LEVEL_BLOCK)
            lev = self._levels(g[i0:i1])
            if lev is None or lev[1] - lev[0] < self.LEVEL_MIN:
                lev = whole
            if lev is None or lev[1] - lev[0] < self.LEVEL_MIN:
                continue
            lo, hi = lev
            seg = g[i0:i1]
            st[i0:i1] = np.where(np.nan_to_num(seg, nan=-1e9) >= lo + 0.6 * (hi - lo), 1,
                                 np.where(np.nan_to_num(seg, nan=1e9) <= lo + 0.4 * (hi - lo), -1, 0))
        if not (st != 0).any():
            return []
        cur = next(s for s in st if s != 0)
        for i in range(n):
            if st[i] == 0:
                st[i] = cur
            cur = st[i]
        min_off, min_on = self.SPELL[mach]
        while True:
            runs, i = [], 0
            while i < n:
                j = i
                while j + 1 < n and st[j + 1] == st[i]:
                    j += 1
                runs.append((i, j))
                i = j + 1
            bad = []
            for k, (i, j) in enumerate(runs):
                if 0 < k < len(runs) - 1:
                    dur = T[j + 1] - T[i]
                    if (st[i] == 1 and dur < min_on) or (st[i] == -1 and dur < min_off):
                        bad.append((dur, i, j))
            if not bad:
                break
            _, i, j = min(bad)
            st[i:j + 1] = -st[i]
        out, on = [], None
        for i in range(1, n):
            if st[i - 1] != 1 and st[i] == 1:
                on = mid(i)
            elif st[i - 1] == 1 and st[i] != 1 and on is not None:
                if mid(i) - on <= self.RUN_MAX:
                    out.append((on, mid(i)))
                on = None
        return out

    # ------------------------------------------------------------------ the operator loop (shared by steps 4 and 5)
    def loops(self, frames):
        """All events of the operator loop on these frames (cached per frame list)."""
        key = (id(frames), len(frames), frames[0]["t"] if frames else 0)
        if getattr(self, "_cache_key", None) == key:
            return self._cache
        A = self._features(frames)
        ev = self._events(A) if len(A) >= 50 else {}
        self._cache_key, self._cache = key, ev
        return ev

    def _events(self, A):
        T, g4, g5, cx, top, bot, Lx, Ly, Rx, Ry = (A[:, j] for j in range(10))
        n = len(T)

        def mid(i):
            if i <= 0:
                return T[0]
            if i >= n:
                return T[-1]
            return (T[i - 1] + T[i]) / 2 if T[i] - T[i - 1] < self.MID_GAP else T[i]
        seen = ~np.isnan(cx)
        # where he is: 4 / 5 = standing at that machine, 0 = elsewhere (walking, at the stands), -1 = not found
        lab = np.full(n, -1)
        for i in range(n):
            if seen[i]:
                at = top[i] <= self.TOP_AT
                lab[i] = 4 if at and cx[i] >= self.X4 else 5 if at and cx[i] <= self.X5 else 0
        last, tl = -1, -1e9
        for i in range(n):
            if lab[i] >= 0:
                last, tl = lab[i], T[i]
            elif T[i] - tl <= self.SEEN_GAP:
                lab[i] = last
        runs, i = [], 0
        while i < n:
            if lab[i] in (4, 5):
                j = i
                while j + 1 < n and lab[j + 1] == lab[i]:
                    j += 1
                runs.append((int(lab[i]), i, j))
                i = j + 1
            else:
                i += 1
        wr = lambda q, box: any(ok(x, y) and box[0] <= x <= box[2] and box[1] <= y <= box[3]  # noqa: E731
                                for x, y in ((Lx[q], Ly[q]), (Rx[q], Ry[q])))
        low = lambda q: lab[q] == 0 and seen[q] and (top[q] >= self.STAND_TOP or bot[q] >= self.STAND_BOT  # noqa: E731
                                                       or any(ok(y) and y >= self.STAND_WY for y in (Ly[q], Ry[q])))
        visits = []
        for m, a, b in runs:
            v = visits[-1] if visits else None
            if v is not None and v["mach"] == m and T[a] - T[v["runs"][-1][1]] <= self.TRIP_MAX:
                v["runs"].append((a, b))
            else:
                visits.append({"mach": m, "runs": [(a, b)]})
        out = []
        for v in visits:
            rs = v["runs"]
            e = {"mach": v["mach"], "arrive": mid(rs[0][0]), "leave": mid(rs[-1][1] + 1), "i0": rs[0][0], "i1": rs[-1][1]}
            # the rail exchange: the longest time away with a frame at the stands (or frames missing); shorter
            # departures (bending to a bin, pose glitches) stay part of the visit
            trips = []
            for (a0, b0), (a1, b1) in zip(rs, rs[1:]):
                inside = range(b0 + 1, a1)
                gap = any(T[q + 1] - T[q] >= self.TRIP_GAP for q in range(b0, a1))
                if (any(low(q) for q in inside) or gap) and mid(a1) - mid(b0 + 1) >= self.TRIP_MIN:
                    trips.append((mid(a1) - mid(b0 + 1), b0, a1))
            if trips:
                _, b0, a1 = max(trips)
                inside = range(b0 + 1, a1)
                e["rail_out"], e["back"] = mid(b0 + 1), mid(a1)
                pl = next((q for q in inside if wr(q, self.CROWN)), None)
                pk = next((q for q in inside if (pl is None or q > pl) and wr(q, self.RACK)), None)
                dur = e["back"] - e["rail_out"]
                e["place"] = max(mid(pl), e["rail_out"]) if pl is not None else e["rail_out"] + self.PLACE_AT * dur
                e["pick"] = max(mid(pk), e["place"]) if pk is not None else max(e["place"], e["rail_out"] + self.PICK_AT * dur)
                e["estimated"] = [k for k, q in (("place", pl), ("pick", pk)) if q is None]
            out.append(e)
        lamps = {4: self._lamp_runs(T, g4, 4, mid), 5: self._lamp_runs(T, g5, 5, mid)}
        holes = [(T[i], T[i + 1]) for i in range(n - 1) if T[i + 1] - T[i] > self.HOLE]
        return {"visits": out, "lamps": lamps, "holes": holes}

    # ------------------------------------------------------------------ cycles of this station
    def _machine(self, c, e, lamps):
        """Step 4: lamp lit within 6 s after he left = machine runs."""
        run = next(((a, b) for a, b in lamps if e["leave"] + self.START_WIN[0] <= a <= e["leave"] + self.START_WIN[1]), None)
        if run is not None and run[0] < c["end"]:
            c["machine_on"] = run[0]
            if run[1] < c["end"]:
                c["machine_off"] = run[1]
            c["machine"] = {"Machine runs": (run[0], min(run[1], c["end"]))}

    def detect(self, frames):
        ev = self.loops(frames)
        if not ev:
            return []
        vs = [e for e in ev["visits"] if e["mach"] == self.MACH]
        lamps = ev["lamps"][self.MACH]
        cyc = []
        for e, nx in zip(vs, vs[1:]):
            if nx["arrive"] - e["arrive"] > self.MAX_CYCLE:
                continue
            c = {"start": e["arrive"], "end": nx["arrive"], "parts": e["arrive"]}
            for k in ("rail_out", "place", "pick", "back", "leave"):
                if e.get(k) is not None and e[k] < c["end"]:
                    c[k] = e[k]
            # machine still running when he arrived: its lamp goes off after the arrival (before the rail comes out)
            busy = next((b for a, b in lamps if a < e["arrive"] < b < c.get("rail_out", e["leave"])), None)
            if busy is not None:
                c["parts"] = busy
            if e.get("estimated"):
                c["note"] = "frames missing at the stands: " + " / ".join(e["estimated"]) + " estimated"
            self._machine(c, e, lamps)
            cyc.append(c)
        return self._self_check(cyc, ev)

    def _self_check(self, cycles, ev):
        """Cycles against his visits to the other machine on the same frames, per 10 minutes of the clock; a block that
        differs by more than SC_TOL (and more than SC_MIN) is left out of the statistics and the cycle table. Cycles with
        frames missing for more than HOLE s (recording gaps) are dropped first."""
        cycles = [c for c in cycles if not any(c["start"] < b and a < c["end"] for a, b in ev["holes"])]
        mine = [c["start"] for c in cycles]
        other = [e["arrive"] for e in ev["visits"] if e["mach"] == self.OTHER]
        blocks = {}
        for t in mine:
            blocks.setdefault(int(t // self.SC_BLOCK), [0, 0])[0] += 1
        for t in other:
            blocks.setdefault(int(t // self.SC_BLOCK), [0, 0])[1] += 1
        self.check, keep_b = [], set()
        for b in sorted(blocks):
            nm, no = blocks[b]
            good = abs(nm - no) <= max(self.SC_TOL * max(nm, no), self.SC_MIN)
            self.check.append({"block": b * self.SC_BLOCK, "mine": nm, "other": no, "ok": good})
            if good:
                keep_b.add(b)
        return [c for c in cycles if int(c["start"] // self.SC_BLOCK) in keep_b]

    def _check_text(self, mine, other):
        chk = getattr(self, "check", [])
        if not chk:
            return []
        bad = [b for b in chk if not b["ok"]]
        out = [f"Self-check, {mine} / {other} per 10 minutes: "
               + ", ".join(f"{hm(b['block'])[:5]} {b['mine']}/{b['other']}{'' if b['ok'] else ' left out'}" for b in chk) + "."]
        if bad:
            out.insert(0, f"Self-check: {len(bad)} of {len(chk)} ten-minute blocks differ from the {other} by more than "
                          f"{100 * self.SC_TOL:.0f}% and are left out of the statistics and the cycle table (not validated).")
        return out

    def _common_extra(self, cycles, other_step):
        out = []
        at = [c["leave"] - c["start"] for c in cycles if "leave" in c]
        if at:
            sec = [c["end"] - c["start"] for c in cycles]
            out.append(f"Operator at this machine (arrival to leaving) median {stat.median(at):.1f}s of a "
                       f"{stat.median(sec):.1f}s cycle; the rest of the cycle he is walking to and working at {other_step}.")
        ex = [c for c in cycles if all(k in c for k in ("rail_out", "place", "pick", "back"))]
        if ex:
            out.append(f"Rail exchange (finished rail to the upper comb of the stand, next rail from its lower bars, back at "
                       f"the machine) median {stat.median([c['back'] - c['rail_out'] for c in ex]):.1f}s: rail put down "
                       f"{stat.median([c['place'] - c['rail_out'] for c in ex]):.1f}s after leaving the machine, next "
                       f"rail picked {stat.median([c['pick'] - c['place'] for c in ex]):.1f}s later.")
        idle = [c["end"] - c["machine_off"] for c in cycles if "machine_off" in c]
        if idle:
            out.append(f"Machine done before he was back in {len(idle)} of {len(cycles)} cycles: it waits median "
                       f"{stat.median(idle):.1f}s.")
        busy = [c["parts"] - c["start"] for c in cycles if c.get("parts", c["start"]) > c["start"] + 0.05]
        if busy:
            out.append(f"Machine still running when he arrived in {len(busy)} of {len(cycles)} cycles (median "
                       f"{stat.median(busy):.1f}s; he takes guide parts from the bins meanwhile).")
        return out

    def extra(self, cycles):
        out = self._common_extra(cycles, "step 5")
        on = [c["machine_off"] - c["machine_on"] for c in cycles if "machine_off" in c and "machine_on" in c]
        if on:
            out.insert(1, f"Machine runs (green lamp lit) median {stat.median(on):.1f}s, starting median "
                          f"{stat.median([c['machine_on'] - c['leave'] for c in cycles if 'machine_on' in c and 'leave' in c]):.1f}s "
                          f"after he leaves.")
        return out + self._check_text("step-4 cycles", "visits to step 5")


class YG2(YG1):
    """YRA SEAT SLIDER, step 5 "Guide S/A Insert #2 m/c" (station 10; camera 10 = camera 9). The LEFT machine; the same
    operator and loop as YG1 (see there). The visit is the same as at step 4 (guide parts from the two teal bins, finished
    rail to the upper yellow comb of the stand, next rail from its lower bars, rail in, more guide parts), but the stand
    is right in front of this machine, so the walk is shorter. Median seconds after he arrives, night / day: rail
    out 2.7 / 5.0, put down 3.5 / 5.9, next rail 4.6 / 6.1, back 6.6 / 8.3, slide out 9.0 / 10.6, leaves 12.2 / 12.2.
    Once (day, 09:31:32) he held the finished rail upright in front of him for ~2 s before putting it down.
    Step-5 machine: a slide in front of a green-lit plate (x 0.458, y 0.267) moves out 1.6 / 2.2 s after he is back with
    the rail (he is still at the machine, taking guide parts) and comes home 7.3-8.1 s after he leaves; the machine moves
    most in the last 3 s before that. Then it waits until he is back (every annotated cycle, median 5.2 / 6.5 s).
    """
    key, station_id, title = "yg2", 10, "Guide S/A Insert #2 m/c (YRA step 5)"
    also_cameras = (10,)  # filed under camera 10 too (the same physical camera, not recorded)
    MACH, OTHER, NEIGHBOUR = 5, 4, "yg1"
    SLIDE_WIN = (-1.0, 0.5)             # slide out between 1 s before he is back and 0.5 s after he leaves
    HOME_MAX = 15.0                     # slide home at most this long after he left (seen: 7.2-7.6 s)
    ORDER = [("WAITM", "start"), ("PARTS", "parts"), ("OUT", "rail_out"), ("SWAP", "place"), ("BACK", "pick"),
             ("LOAD", "back"), ("HOLD", "slide_out"), ("RUN", "leave"), ("IDLE", "machine_off")]
    NAMES = {
        "WAITM": ("Machine still working when he arrives (he takes guide parts meanwhile)", "#fca5a5"),
        "PARTS": ("At the machine before the rail exchange: guide parts from both bins", "#2563eb"),
        "OUT": ("Finished rail out, carried to the stand in front", "#f59e0b"),
        "SWAP": ("Rail laid in the upper yellow comb, reach down to the lower bars", "#be185d"),
        "BACK": ("Next rail taken from the lower bars, walk back", "#16a34a"),
        "LOAD": ("Rail into the machine until its slide moves out", "#0891b2"),
        "HOLD": ("Slide out: guide parts from both bins, then he leaves", "#7c3aed"),
        "RUN": ("Machine works after he leaves (until the slide is home); operator at step 4", "#94a3b8"),
        "IDLE": ("Machine done, waits for the operator", "#dc2626"),
    }
    METHOD = [
        "One operator runs steps 4 and 5 (the right and the left machine) in one loop of ~26.5 s. He is followed from "
        "frame to frame: the person box with centre x 0.28-0.80 and top above y 0.40, nearest to his last position.",
        "At a machine = box top at or above y 0.22 and centre x right of 0.585 (step 4) or left of 0.435 (step 5). "
        "Cycle: he arrives at step 5 -> the next time. Away from step 5 and back within 11 s, with a frame at the stands "
        "(box top below 0.235, box bottom below 0.86 or a wrist below y 0.53), the longest such departure of at least "
        "0.8 s = the rail exchange: rail out = he leaves "
        "the machine, back = he is at the machine again; leaves = he goes on to step 4.",
        "Rail put down = first wrist at the upper yellow comb of the stand (x 0.33-0.465, y 0.555-0.80); next rail = then "
        "the first wrist at its lower bars (x 0.455-0.68, y 0.62-0.95). Not seen (frames missing): estimated at 30% / 55% "
        "of the trip.",
        "Machine: the green-lit plate behind the step-5 slide (x 0.458, y 0.267; green minus red/blue) is covered while "
        "the slide is home. Lit and unlit levels are found per 10 minutes; unlit spells under 1.6 s are a blink of the "
        "slide or his arm. Slide out = lit from 1 s before he is back until he leaves; machine works from his leaving until "
        "the slide is home (unlit, within 15 s); home before he is back = the machine waits for him.",
        "Self-check: per 10 minutes of the clock, the step-5 cycles are compared with his visits to step 4 on the same "
        "frames; a block that differs by more than 20% (and more than 3) is left out of the statistics and the cycle table. "
        "Cycles with frames missing for more than 5 s (recording gaps) are not used.",
        "Checked frame by frame on full-resolution video: 8 cycles recorded at ~1.5 frames/s (2026-10-15 21:55-21:59) "
        "and 19 at ~4.5 frames/s (2026-10-16 09:28-09:37): all found. Median error at 1.5 / 4.5 frames/s: arrival 0.16 / "
        "0.05 s, rail out 0.33 / 0.09 s, rail put down 0.15 / 0.13 s, next rail 0.09 / 0.10 s, back 0.15 / 0.17 s, "
        "slide out 0.57 / 0.06 s, leaves 0.48 / 0.20 s, slide home 0.17 / 0.06 s. The 19 day cycles with only every "
        "third frame (1.5 frames/s): all found, 0.15-0.36 s. Day crew 2026-10-17 16:52-17:02: 12 of 12 cycles outside the "
        "line stop, no extra cycle (an 8 s limit for the trip split two visits: the finished rail held up and looked at "
        "for 7 s, a talk at the stand); arrival 0.15 s, rail out 0.05 s, slide out 0.21 s (median).",
        "Event times are the middle between the last frame before and the first frame with the cue.",
    ]
    UNSEEN = ["What exactly he does with the guide parts: his back hides his hands at the fixture. Both hands go into the "
              "two teal bins several times per rail; the number of parts per rail cannot be counted on the recordings.",
              "What moves the slide out ~2 s after he is back with the rail (his hand, a clamp sensor or a button), and "
              "what starts the press work after he leaves: hidden by his body.",
              "Which station the person at the bottom-left machine belongs to, and who fills the lower bars of the stand: "
              "he takes rails out of the upper comb and reaches to the lower bars now and then, but the rails cannot be "
              "followed on the camera.",
              "Whether steps 4 and 5 work in series (a rail through both machines) or side by side: both lay their "
              "finished rails in the same upper comb and take from the same lower bars, and the rails look alike."]

    def _machine(self, c, e, lamps):
        """Step 5: slide out while he loads; machine works from his leaving until the slide is home."""
        if "leave" not in c:
            return
        run = next(((a, b) for a, b in lamps if e.get("back", e["arrive"]) + self.SLIDE_WIN[0] <= a <= e["leave"] + self.SLIDE_WIN[1]
                    and b > e["leave"]), None)
        if run is None:
            return
        if run[0] < c["leave"]:
            c["slide_out"] = run[0]
        if run[1] - e["leave"] <= self.HOME_MAX:
            if run[1] < c["end"]:
                c["machine_off"] = run[1]
            c["machine"] = {"Machine works": (c["leave"], min(run[1], c["end"]))}

    def extra(self, cycles):
        out = self._common_extra(cycles, "step 4")
        w = [c["machine_off"] - c["leave"] for c in cycles if "machine_off" in c and "leave" in c]
        if w:
            out.insert(1, f"Machine works median {stat.median(w):.1f}s after he leaves (until its slide is home); the slide "
                          f"moved out median {stat.median([c['slide_out'] - c['back'] for c in cycles if 'slide_out' in c and 'back' in c]):.1f}s "
                          f"after he was back with the rail.")
        return out + self._check_text("step-5 cycles", "visits to step 4")


# ======================================================================== ylr / ysr / ysf: YRA lower rail, steps 6-8 (camera 18)
class YLR:
    """YRA SEAT SLIDER, step 6 "LWR Rail Greasing m/c" (station 18). Cameras 17, 18 and 19 are one physical camera
    (192.168.31.34); only camera 18 is recorded, so steps 6-8 (YLR, YSR, YSF) all run on it. The user's zones: step 6 =
    the greasing machine (left / bottom left), step 7 = the Rr bending machine (middle), step 8 = the Fr bending
    machine (right of middle).
    Watched frame by frame on 1600x900 videos of 2026-10-15 21:59 and 2026-10-16 00:25, 00:36 and 09:19, with the 640
    recordings of the same minutes (~2 frames/s at 21:56-22:00, ~5 frames/s since 22:47).

    Two people work these three machines. Operator A (front, blue shirt and cap, khaki trousers) runs the greasing
    machine and the Rr machine and loads the Fr machine, in one loop of ~13 s. Operator B (blue shirt, green trousers,
    standing behind the right end of the Fr machine) works the rail in the Fr nest, lifts it out, works on it in his
    hands and puts it down at the back. A third person at the rack (front right) and the people behind B belong to
    other stations.
    A's loop, seen per cycle (median seconds from his bend to the blue bin, night 00:37-00:40, 12 loops):
      walks left from the Fr machine (-1.3) -> bends to the blue bin at the bottom left and picks a new lower rail
      (0; 1 in 4 picks 2-6 s: he searches in the bin) -> hand comes up at the machine with the greased rail (+1.3)
      -> new rail into the slide, start, both hands low at the machine (to +3.0) -> turns right and lays the greased
      rail on the rack at the front right (+3.5), takes the next rail from the rack -> lays it in the Rr nest and
      positions it with both hands (+5.0) -> right hand to the start button at the front left corner of the Rr machine
      (+6.2) -> lifts the bent rail out of the Rr nest (+7.5) and lays it in the Fr nest, pushes it in, reaches to the
      back of the nest (to +11.7) -> walks left again.
    The greasing machine's slide moves back ~9.0 s after he started it (8.9-9.7 s, 9 of 9 seen): greasing done; the
    greased rail then waits ~1 s until he is back. Once (00:38:59) he went back to the greasing machine's touch panel
    for 6 s between the Rr start and the Rr unload.
    Day crew (2026-10-17 16:52-17:02, full-resolution video, ylr/ysr/ysf_day1652_annotations.json; operator A with blue
    cap, glasses and khaki trousers): the same loop, but the order at the greasing machine and the rack varies (rack
    skipped in 4 of 27 loops; twice the greased rail went to the rack first and he came back to load and start), and he
    stands nearer to the Rr nest (body centre x 0.51-0.60, the night crew 0.60-0.66) and lays the rail in lower (wrists
    at y 0.69-0.75). He positions the rail standing upright and moving right, presses the start button with his hands
    low, and lifts the bent rail out as he steps back to the Fr nest (~0.3 s before his feet move). Once (16:54:56) he
    used the touch panel for 14 s between two bends to the bin. Two line stops (Fr machine problems, 16:56:04-16:57:53
    and 16:59:12-17:01:59): he waited at the Fr nest, re-arranged rails at the rack and the bin, touched the greasing
    panel and touched the Rr nest several times before the next rail went to the Fr nest.
    """
    key, cams, station_id, title = "ylr", (18,), 18, "LWR Rail Greasing m/c (YRA step 6)"
    # operator A: the front person (box bottom below y 0.85, at least 0.4 high, centre x 0.2-0.8), nearest to his last place
    A_BOTTOM, A_HEIGHT, A_CX = 0.85, 0.40, (0.20, 0.80)
    LOW_BOTTOM, LOW_HEIGHT = 0.95, 0.18  # ... or bent deep into the bin: bottom below 0.95, at least 0.18 high, left of 0.56
    # operator B: behind the right end of the Fr machine (box bottom y 0.55-0.85, top above 0.30, centre x 0.66-0.88)
    B_BOTTOM, B_TOP, B_CX = (0.55, 0.85), 0.30, (0.66, 0.88)
    G_X, VISIT_GAP = 0.52, 1.5        # at the greasing machine: centre left of x 0.52 (runs closer than 1.5 s are one visit)
    G_SHALLOW = 0.03                  # a visit with no bend that never gets 0.03 left of G_X is not one (the day crew
                                      # stands at the Rr nest with his centre at x 0.51-0.56)
    LOOP_MIN = 6.0                    # greasing visits closer than this (bends to the bin) are one cycle (shortest: ~10 s)
    RR_TRIES, RR_AWAY = 40, 2.0       # Rr nest visits tried per loop; a new visit after 2 s without a hand at the nest
    BEND_X, BEND_TOP, BEND_WY = 0.56, 0.48, 0.84  # bent to the bin: centre left of 0.56, box top below 0.48, a wrist
                                      # below 0.84 (or no wrist seen)
    LOST_TOP, LOST_WY = 0.44, 0.80    # ... or his pose is lost right after a frame left of 0.56 with the top below
                                      # 0.44 and a wrist below 0.80
    PANEL, PANEL_N = (0.0, 0.60, 0.30, 0.80), 2  # a visit with a wrist here in 2 frames or more: at the touch panel of the
                                      # greasing machine, not a cycle (unless he bends to the bin and exchanges after it)
    UP_TOP, UP_WY, UP_MIN = 0.56, 0.885, 0.4  # hand up with the greased rail: top above 0.56, all wrists above 0.885
    G_NEAR = 0.03                     # leaves the machine: last frame within 0.03 of his left-most centre
    WALK_LOOK, WALK_DROP, WALK_TOP = 3.0, 0.015, 0.03  # walk to the greasing machine: centre 0.015 left of, or box top
                                      # 0.03 lower than, his position at the Fr machine in the 3 s before the visit
    RACK = (0.65, 0.78, 1.0, 1.0)     # a wrist at the rack (front right)
    RACK_HOLD = (0.65, 0.70, 1.0, 1.0)  # still at the rack (taking the next rail)
    RR_NEST = (0.44, 0.52, 0.565, 0.68)  # a wrist at the Rr nest
    RR_LOW, RR_LOW_CX = (0.44, 0.52, 0.62, 0.75), (0.51, 0.60)  # ... or lower and further right, with his centre at x
                                      # 0.51-0.60 (day crew: he stands nearer the nest and lays the rail in lower)
    RACK_NEAR = (0.63, 0.76, 1.0, 1.0)  # ... and no hand still at the rack
    RR_FEET = 0.95                    # ... with his feet at the front (box bottom below y 0.95)
    RR_BTN = (0.47, 0.685, 0.56, 0.79)   # a wrist at the Rr start button (front left corner of the Rr machine)
    RR_LIFT_WY, RR_LIFT_TOP = 0.58, 0.33  # bent rail lifted: a wrist above y 0.58, or the box top above 0.33
    FR_CX, RR_MIN = 0.625, 0.8        # at the Fr nest: centre right of x 0.625 or feet back, from 0.8 s after the rail in
    STEP_LEAD, STEP_LEAD_MAX = 0.3, 1.6  # the bent rail comes out 0.3 s before his feet step back to the Fr nest; a lift
                                      # cue more than 1.6 s before that step is not the lift
    B_UP_WY, B_HOLD_X, B_HOLD = 0.345, 0.72, 1.5  # B holds the rail at his chest: all wrists above y 0.345 and right
                                      # of x 0.72, for at least 1.5 s ...
    B_NEST_WY, B_BEFORE = 0.355, 3.0  # ... after his hands were at the nest (a wrist below y 0.355 or left of x 0.72)
    B_PUT, B_PUT_MEAN = 0.02, 0.026   # B puts the rail down: both wrists 0.02 (mean 0.026) lower than while he held it
    CAR = (0.325, 0.625, 0.425, 0.75)  # greasing machine slide
    CAR_MOT, CAR_AWAY, CAR_FROM = 0.05, 0.56, 3.0  # slide moves: >5% of its pixels change while A is right of x 0.56,
                                      # from 3 s after he started it
    PLATE = (0.618, 0.25, 0.635, 0.42)  # small vertical plate behind the Fr bed (bright while it is up)
    PLATE_UP = 20.0                   # grey level above its own median by this much
    PLATE_MERGE = 3.0                 # bright spells closer than this are one movement
    MID_GAP = 3.0
    MAX_CYCLE = 60.0
    HOLE = 5.0                        # frames missing for longer than this inside a cycle: the cycle is not used
    SC_BLOCK, SC_TOL, SC_MIN = 600.0, 0.20, 3
    NEIGHBOUR = "ysr"
    ORDER = [("PICK", "at_g"), ("EXCH", "g_up"), ("CARRY", "leave_g"), ("RUN", "rack"), ("IDLE", "done_early"),
             ("WALK", "walk_g"), ("DONE", "g_done")]
    NAMES = {
        "PICK": ("Bend to the blue bin, pick a new rail", "#16a34a"),
        "EXCH": ("Greased rail out, new rail in, start", "#2563eb"),
        "CARRY": ("Carry the greased rail to the rack", "#a855f7"),
        "RUN": ("Machine greasing; operator at the rack, Rr and Fr", "#94a3b8"),
        "IDLE": ("Greasing done, waits; operator still at the Fr machine", "#f87171"),
        "WALK": ("Operator walks back to the greasing machine", "#f59e0b"),
        "DONE": ("Greasing done, waits for the operator", "#dc2626"),
    }
    METHOD = [
        "Two people work steps 6-8. Operator A (front) runs the greasing machine and the Rr machine and loads the Fr "
        "machine in one loop (~13 s); he is followed from frame to frame: the person with the box bottom below y 0.85, "
        "at least 0.4 high and centre x 0.2-0.8, nearest to his last position. Operator B: the person behind the right "
        "end of the Fr machine (box bottom y 0.55-0.85, top above y 0.30, centre x 0.66-0.88).",
        "Cycle: A bends to the blue bin (body centre left of x 0.56, box top below y 0.48 and a wrist below y 0.84, or "
        "his pose lost while bending) → next time. Visits to the greasing machine: centre left of x 0.52; a visit "
        "without a bend that never gets 0.03 left of that line is not one (the day crew stands at the Rr nest with his "
        "centre at x 0.51-0.56). Visits whose bends are less than 6 s apart are one cycle (greased rail to the rack "
        "first, then back to load and start). A visit is a cycle only if he goes on to the Rr nest after it (re-arranging "
        "rails at the bin, the touch panel and line stops are not cycles). Touch panel (a wrist at x < 0.30, y 0.60-0.80 "
        "in 2 frames or more): not a cycle, unless he bends to the bin and exchanges the rail after it in the same visit "
        "(then the panel time is part of the pick) and the Rr exchange of the loop before is complete.",
        "Greased rail out: the first frame after the bend with the box top above y 0.56 and all wrists above y 0.885 · "
        "leaves the machine: last frame within 0.03 of his left-most centre · rail on the rack: a wrist at x ≥ 0.65, "
        "y ≥ 0.78 · walk back: his centre 0.015 left of, or his box top 0.03 lower than, his position at the Fr machine.",
        "Greasing done: the slide of the greasing machine (x 0.325-0.425, y 0.625-0.75) moves (more than 5% of its "
        "pixels change) while A is right of x 0.56, from 3 s after he started it; not seen when he is already back in "
        "front of it. Machine time = from his leaving the machine to that movement.",
        "Cycles with frames missing for more than 5 s are not used. Self-check: per 10 minutes of the clock, the "
        "greasing cycles are compared with the Rr cycles on the same frames; a block that differs by more than 20% "
        "(and more than 3) is left out of the statistics and the cycle table.",
        "Checked on full-resolution video: night 00:37-00:40 12/12 cycles, evening 21:56-21:59 15/15 (~1.3 frames/s), day "
        "2026-10-17 16:52-17:02 24/24 outside the two line stops, no extra cycles (none inside the stops either); bend "
        "to the bin within 0.12 / 0.06 / 0.24 s (median). Cycles over 60 s (line stops) are left out.",
        "Event times are the middle between the last frame before and the first frame with the cue.",
    ]
    UNSEEN = ["What starts the greasing machine (his hands are low at the slide, hidden by his body), and the greasing "
              "itself: the only visible machine motion is the slide moving back ~9 s after the start.",
              "When the greasing ends while he is already standing in front of the machine (the slide is hidden then)."]

    # ------------------------------------------------------------------ features
    def _features(self, frames):
        rows, prev, tprev, last, lastb = [], None, None, None, None
        for f in frames:
            img = read_frame(f)
            mo = pl = NAN
            if img is not None:
                gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.int16)
                if prev is not None and prev.shape == gray.shape and f["t"] - tprev < 1.0:  # no difference across a gap
                    mo = float((np.abs(roi(gray, self.CAR) - roi(prev, self.CAR)) > 20).mean())
                pl = float(roi(gray, self.PLATE).mean())
                prev, tprev = gray, f["t"]
            ca, cb = [], []
            for p in f["p"]:
                b = p.get("b")
                if not b or not p.get("k"):
                    continue
                cx = (b[0] + b[2]) / 2
                if (b[3] > self.A_BOTTOM and b[3] - b[1] > self.A_HEIGHT and self.A_CX[0] < cx < self.A_CX[1]) or                         (b[3] > self.LOW_BOTTOM and b[3] - b[1] > self.LOW_HEIGHT and cx < self.BEND_X):  # bent deep into the bin
                    d = abs(cx - last) + 0.5 * abs(b[3] - lastb) if last is not None else 0.0
                    ca.append((d, p, cx))
                if self.B_BOTTOM[0] < b[3] < self.B_BOTTOM[1] and b[1] < self.B_TOP and self.B_CX[0] < cx < self.B_CX[1]:
                    cb.append((abs(cx - 0.78), p, cx))
            opa, opb = [NAN] * 7, [NAN] * 4
            if ca:
                _, p, cx = min(ca, key=lambda c: c[0])
                last, lastb = cx, p["b"][3]
                k = p["k"]
                kp = lambda j, c: k[j][c] if k[j][2] > 0.3 else NAN  # noqa: E731
                opa = [cx, p["b"][1], p["b"][3], kp(9, 0), kp(9, 1), kp(10, 0), kp(10, 1)]
            if cb:
                _, p, cx = min(cb, key=lambda c: c[0])
                k = p["k"]
                kp = lambda j, c: k[j][c] if k[j][2] > 0.3 else NAN  # noqa: E731
                opb = [kp(9, 0), kp(9, 1), kp(10, 0), kp(10, 1)]
            rows.append([f["t"], mo, pl, *opa, *opb])
        return np.array(rows, float)

    # ------------------------------------------------------------------ the loop of A and B (shared by steps 6-8)
    def loops(self, frames):
        key = (id(frames), len(frames), frames[0]["t"] if frames else 0)
        if getattr(self, "_cache_key", None) == key:
            return self._cache
        A = self._features(frames)
        ev = self._events(A) if len(A) >= 50 else {}
        self._cache_key, self._cache = key, ev
        return ev

    def _events(self, A):
        T, car, plate, cx, top, bot, w1x, w1y, w2x, w2y, b1x, b1y, b2x, b2y = (A[:, j] for j in range(14))
        n = len(T)
        seen = ~np.isnan(cx)

        def mid(i):
            return (T[i - 1] + T[i]) / 2 if 0 < i < n and T[i] - T[i - 1] < self.MID_GAP else T[min(i, n - 1)]

        def first(a, b, cond):
            for i in range(max(a, 0), min(b, n)):
                if cond(i):
                    return i
            return None

        def last(a, b, cond):
            for i in range(min(b, n) - 1, max(a, 0) - 1, -1):
                if cond(i):
                    return i
            return None
        idx = lambda t: int(np.searchsorted(T, t))  # noqa: E731
        wr = lambda i: [(x, y) for x, y in ((w1x[i], w1y[i]), (w2x[i], w2y[i])) if ok(x, y)]  # noqa: E731
        wb = lambda i: [y for y in (b1y[i], b2y[i]) if ok(y)]  # noqa: E731
        inbox = lambda pts, box: any(inb(p, box) for p in pts)  # noqa: E731
        maxwy = lambda i: max([y for _, y in wr(i)], default=NAN)  # noqa: E731
        cxf = cx.copy()                    # not detected: still where he was last seen
        for i in range(1, n):
            if np.isnan(cxf[i]):
                cxf[i] = cxf[i - 1]
        # ---- visits to the greasing machine: centre left of G_X (runs closer than VISIT_GAP s are one visit)
        atg = seen & (np.nan_to_num(cx, nan=1) < self.G_X)
        runs, i = [], 0
        while i < n:
            if atg[i]:
                j = i
                while j + 1 < n and (atg[j + 1] or not seen[j + 1]) and T[j + 1] - T[j] < 2.5:
                    j += 1
                while j > i and not atg[j]:
                    j -= 1
                if runs and T[i] - T[runs[-1][1]] < self.VISIT_GAP:
                    runs[-1][1] = j
                else:
                    runs.append([i, j])
                i = j + 1
            else:
                i += 1

        def bent(q):
            if seen[q]:
                return (cx[q] < self.BEND_X and top[q] > self.BEND_TOP and np.nan_to_num(maxwy(q), nan=1.0) > self.BEND_WY
                        and not inbox(wr(q), self.PANEL))
            return (q > 0 and seen[q - 1] and cx[q - 1] < self.BEND_X and top[q - 1] > self.LOST_TOP
                    and np.nan_to_num(maxwy(q - 1)) > self.LOST_WY and not inbox(wr(q - 1), self.PANEL))
        loops = []
        upright = seen & (np.nan_to_num(top, nan=1) < self.UP_TOP)
        for a, b in runs:
            if not upright[a:b + 1].any():
                continue
            mn = float(np.nanmin(np.where(upright[a:b + 1], cx[a:b + 1], np.nan)))
            e = {"i0": a, "i1": b}
            # bend to the bin: from 1 s before the visit (and before frames without him just before it); a visit without
            # a bend is not a cycle (e.g. the touch panel)
            a0 = a
            while a0 > 0 and not seen[a0 - 1] and T[a] - T[a0 - 1] < 8.0:
                a0 -= 1
            q = first(idx(T[a0] - 1.0), b + 1, bent)
            if q is None and float(np.nanmin(cx[a:b + 1])) > self.G_X - self.G_SHALLOW:
                continue                           # only just left of the line and no bend: he is at the Rr nest
            ql = last(a, b + 1, lambda r: upright[r] and cx[r] <= mn + self.G_NEAR)
            e["leave_g"] = mid(ql + 1) if ql + 1 < n else T[ql]
            pan = [r for r in range(a, b + 1) if inbox(wr(r), self.PANEL)]
            # touch panel first, then a bend to the bin and the exchange in the same visit: a cycle (the panel time is
            # part of its pick)
            q2 = first(pan[-1] + 1, b + 1, bent) if len(pan) >= self.PANEL_N else None
            if q2 is not None:                     # he leaves the machine after that second bend
                up2 = upright[q2:b + 1]
                if up2.any():
                    mn2 = float(np.nanmin(np.where(up2, cx[q2:b + 1], np.nan)))
                    ql = last(q2, b + 1, lambda r: upright[r] and cx[r] <= mn2 + self.G_NEAR)
                    e["leave_g"] = mid(ql + 1) if ql + 1 < n else T[ql]
                else:
                    q2 = None
            if (len(pan) >= self.PANEL_N and (q2 is None or q2 > ql)) or (q is not None and q > ql):
                e["panel"] = mid(a)
                loops.append(e)
                continue
            q = a if q is None else q              # arrival: bent to the bin (pose lost while bent: the visit start)
            e["at_g"] = mid(q)
            if q2 is not None:
                e["panel_t"] = mid(pan[0])
            u = first((q2 if q2 is not None else q) + 1, ql + 1, lambda r: seen[r] and T[r] - e["at_g"] >= self.UP_MIN
                      and top[r] < self.UP_TOP and wr(r) and maxwy(r) < self.UP_WY)
            if u is not None:
                e["g_up"] = mid(u)
            # walk: his position at the Fr machine in the WALK_LOOK s before the bend; the walk starts when he leaves it
            p0 = idx(e["at_g"] - self.WALK_LOOK)
            pre = [r for r in range(p0, q) if seen[r] and cx[r] >= self.BEND_X]
            if pre:
                bx, bt = float(np.nanmax(cx[pre])), float(np.nanmin(top[pre]))
                ls = last(p0, q, lambda r: seen[r] and cx[r] >= bx - self.WALK_DROP and top[r] <= bt + self.WALK_TOP)
                e["walk_g"] = mid(ls + 1) if ls is not None else mid(q)
            loops.append(e)
        # greasing visits closer than LOOP_MIN s are one cycle (he went to the rack in between, or bent to the bin twice):
        # the first bend starts it, the last visit gives the exchange times
        merged = []
        for e in loops:
            p = merged[-1] if merged else None
            if p is not None and "at_g" in p and "at_g" in e and e["at_g"] - p["at_g"] < self.LOOP_MIN:
                for k_ in ("i1", "leave_g"):
                    p[k_] = e[k_]
                if "g_up" not in p and "g_up" in e:
                    p["g_up"] = e["g_up"]
                continue
            merged.append(e)
        loops = merged
        # ---- after the greasing machine: rack, Rr, Fr (until the next visit)
        def next_walk(k, nb):
            """Index where he starts walking to the next greasing visit (or that visit's first frame)."""
            if k + 1 < len(loops) and loops[k + 1].get("walk_g") is not None:
                return min(idx(loops[k + 1]["walk_g"]), nb)
            return nb
        at_rr = lambda q: (np.nan_to_num(bot[q]) >= self.RR_FEET and not inbox(wr(q), self.RACK_NEAR)  # noqa: E731
                           and (inbox(wr(q), self.RR_NEST) or (self.RR_LOW_CX[0] <= cx[q] <= self.RR_LOW_CX[1]
                                                               and inbox(wr(q), self.RR_LOW))))

        def rr_visit(q, lim):
            # start button: a wrist at the front left corner, before he walks back to the greasing machine; bent rail out:
            # after the button the rail is lifted or he moves right to the Fr nest; with no button seen (low frame rates)
            # the rail out is taken at his step to the Fr nest (feet back, or centre right of FR_CX in two frames)
            d = {"rr_in": mid(q), "_q": q}
            bt = first(max(idx(d["rr_in"] + 0.3), q + 1), lim, lambda q: inbox(wr(q), self.RR_BTN))
            if bt is not None and T[bt] - d["rr_in"] < 8.0:
                d["rr_btn"] = mid(bt)
                o = first(bt + 1, lim, lambda q: (wr(q) and min(y for _, y in wr(q)) < self.RR_LIFT_WY)
                          or np.nan_to_num(top[q], nan=1) < self.RR_LIFT_TOP or (seen[q] and cx[q] >= self.FR_CX))
                if o is not None and T[o] - T[bt] < 6.0:
                    d["rr_out"] = mid(o)
            else:
                atfr = lambda q: seen[q] and (bot[q] < self.RR_FEET or cx[q] >= self.FR_CX)  # noqa: E731
                o = first(idx(d["rr_in"] + self.RR_MIN), lim, lambda q: atfr(q) and (q + 1 >= n or atfr(q + 1)))
                if o is not None and T[o] - d["rr_in"] < 8.0:
                    d["rr_out"] = mid(o)
            # his step back to the Fr nest (feet back in two frames): no lift seen, or one long before that step (the day
            # crew stands upright and moves right while he positions the rail, with his hands low at the nest): the rail
            # comes out STEP_LEAD s before the step, and the start button is the last time a wrist was there before that
            back = lambda q: seen[q] and bot[q] < self.RR_FEET  # noqa: E731
            s = first(idx(d["rr_in"] + self.RR_MIN), lim, lambda q: back(q) and (q + 1 >= n or back(q + 1)))
            if s is not None and T[s] - d["rr_in"] < 10.0 and d.get("rr_out", -1e18) < mid(s) - self.STEP_LEAD_MAX:
                d["rr_out"] = max(mid(s) - self.STEP_LEAD, d["rr_in"] + 0.5)
                rb = last(max(idx(d["rr_in"] + 0.3), q + 1), idx(d["rr_out"]), lambda q: inbox(wr(q), self.RR_BTN))
                d.pop("rr_btn", None)
                if rb is not None:
                    while rb - 1 > q and inbox(wr(rb - 1), self.RR_BTN):
                        rb -= 1
                    d["rr_btn"] = mid(rb)
            return d

        def next_rr(q, lim):
            """The next Rr visit: a hand at the nest again after RR_AWAY s or more without one."""
            last_in = q
            for r in range(q + 1, lim):
                if at_rr(r):
                    if T[r] - T[last_in] >= self.RR_AWAY:
                        return r
                    last_in = r
            return None
        for k, e in enumerate(loops):
            b = e["i1"]
            nb = loops[k + 1]["i0"] if k + 1 < len(loops) else n
            p = loops[k - 1] if k > 0 else {}
            if "panel_t" in e and "_q" in p and "rr_out" not in p:
                # touch panel (and a bend) in the middle of the Rr exchange of the loop before (rail in, not yet out; night
                # 00:38:59): not a new cycle
                for kk in ("at_g", "g_up", "panel_t", "walk_g"):
                    e.pop(kk, None)
                e["panel"] = mid(e["i0"])
                for kk in ("rr_btn", "rr_out"):
                    p.pop(kk, None)
                p.update(rr_visit(p["_q"], e["i0"]))
            r = first(idx(e["leave_g"] - 0.5), nb, lambda q: inbox(wr(q), self.RACK))
            j0 = b + 1
            if r is not None and "panel" not in e:
                e["rack"] = mid(r)
                re_ = r
                while True:     # still at the rack (gaps of one frame bridged)
                    nx = first(re_ + 1, min(re_ + 3, nb), lambda q: inbox(wr(q), self.RACK_HOLD))
                    if nx is None or T[nx] - T[r] > 6.0:
                        break
                    re_ = nx
                j0 = re_ + 1
            # the Rr exchange: the first visit to the Rr nest that sends a rail on to the Fr nest (when the Fr machine is
            # stopped he may touch the nest several times before that); the first visit if none does
            if "panel" not in e:
                lim = next_walk(k, nb)
                q, cands = first(j0, nb, at_rr), []
                while q is not None and len(cands) < self.RR_TRIES:
                    cands.append(rr_visit(q, lim))
                    if "rr_out" in cands[-1]:
                        break
                    q = next_rr(q, lim)
                if cands:
                    e.update(next((d for d in cands if "rr_out" in d), cands[0]))
            # the start button and the bent rail out may follow a panel visit (they are then filed under that visit)
            if "rr_in" not in e and "panel" not in e and "rack" in e:  # hand at the Rr nest not seen (frames missing)
                atfr = lambda q: seen[q] and (bot[q] < self.RR_FEET or cx[q] >= self.FR_CX)  # noqa: E731
                o = first(idx(e["rack"] + 2.0), next_walk(k, nb), lambda q: atfr(q) and (q + 1 >= n or atfr(q + 1)))
                if o is not None and T[o] - e["rack"] < 10.0:
                    e["rr_out"] = mid(o)
            elif "panel" in e:          # after a visit to the touch panel: the bent rail out (start button before it)
                o = first(b + 1, nb, lambda q: (wr(q) and min(y for _, y in wr(q)) < self.RR_LIFT_WY)
                          or np.nan_to_num(top[q], nan=1) < self.RR_LIFT_TOP)
                if o is not None and T[o] - T[b] < 8.0:
                    e["rr_out"] = mid(o)
        # a panel visit between the Rr start and the bent rail out: the rail out belongs to the loop before it
        for k, e in enumerate(loops):
            if "panel" in e and "rr_out" in e and k > 0 and "rr_out" not in loops[k - 1]:
                loops[k - 1]["rr_out"] = e.pop("rr_out")
            e.pop("_q", None)
        loops = [e for e in loops if "at_g" in e]
        for k, e in enumerate(loops):    # A leaves the Fr machine = the walk to the next greasing visit
            if k + 1 < len(loops) and "rr_out" in e and loops[k + 1].get("walk_g", 0) > e["rr_out"]:
                e["fr_leave"] = loops[k + 1]["walk_g"]
        # ---- greasing done: slide movement while he is away, the first one from CAR_FROM s after he left the machine
        slide = (np.nan_to_num(car) > self.CAR_MOT) & (np.nan_to_num(cxf, nan=0) > self.CAR_AWAY)
        for k, e in enumerate(loops):
            nxt = loops[k + 1]["at_g"] if k + 1 < len(loops) else T[-1]
            q = first(idx(e["leave_g"] + self.CAR_FROM), idx(nxt + 0.3), lambda q: slide[q])
            if q is not None:
                e["g_done"] = mid(q)
        # ---- operator B: lifts the rail out of the Fr nest (holds it up at his chest for >= B_HOLD s after his hands were
        # down at the nest) and puts it down (wrists clearly lower than while he held it, two frames in a row)
        bx = lambda i: [x for x in (b1x[i], b2x[i]) if ok(x)]  # noqa: E731
        bseen = np.array([bool(wb(i)) for i in range(n)])
        up = np.array([bseen[i] and max(wb(i)) < self.B_UP_WY and min(bx(i), default=1) > self.B_HOLD_X for i in range(n)])
        atnest = np.array([bseen[i] and (max(wb(i)) > self.B_NEST_WY or min(bx(i), default=1) < self.B_HOLD_X) for i in range(n)])
        lifts, i = [], 1
        while i < n:
            if up[i] and not up[i - 1]:
                j = i
                while j + 1 < n and T[j + 1] - T[j] < 1.5 and (up[j + 1] or (j + 2 < n and up[j + 2] and T[j + 2] - T[j] < 1.5)):
                    j += 1
                if T[j] - T[i] >= self.B_HOLD and atnest[idx(T[i] - self.B_BEFORE):i].any():
                    lv = float(np.median([np.mean(wb(r)) for r in range(i, j + 1) if bseen[r] and T[r] - T[i] <= 2.0]))
                    put = lambda r: bseen[r] and min(wb(r)) >= lv + self.B_PUT and np.mean(wb(r)) >= lv + self.B_PUT_MEAN  # noqa: E731
                    pd = first(idx(T[i] + 3.0), idx(T[i] + 25.0), lambda r: put(r) and (r + 1 >= n or not bseen[r + 1] or put(r + 1)))
                    lifts.append({"b_out": mid(i), "b_down": mid(pd) if pd is not None else None})
                i = j + 1
            else:
                i += 1
        # ---- small plate behind the Fr bed: bright spells
        med = np.nanmedian(plate) if np.any(~np.isnan(plate)) else NAN
        pu = np.nan_to_num(plate - med) > self.PLATE_UP
        plates = []
        for i in range(1, n):
            if pu[i] and not pu[i - 1] and (not plates or mid(i) - plates[-1] > self.PLATE_MERGE):
                plates.append(mid(i))
        holes = [(T[i], T[i + 1]) for i in range(n - 1) if T[i + 1] - T[i] > self.HOLE]
        return {"loops": loops, "lifts": lifts, "plates": plates, "holes": holes}

    # ------------------------------------------------------------------ cycles of this station
    def detect(self, frames):
        ev = self.loops(frames)
        if not ev:
            return []
        # a greasing cycle goes on to the Rr nest; a visit after which he does not (re-arranging rails at the bin, touch
        # panel, line stops) is not a cycle of its own
        L = [e for e in ev["loops"] if "rr_in" in e or "rr_out" in e]
        cyc = []
        for e, nx in zip(L, L[1:]):
            if nx["at_g"] - e["at_g"] > self.MAX_CYCLE:
                continue
            c = {"start": e["at_g"], "end": nx["at_g"], "at_g": e["at_g"]}
            for k in ("g_up", "leave_g", "rack"):
                if e.get(k) is not None and c["start"] <= e[k] < c["end"]:
                    c[k] = e[k]
            w = nx.get("walk_g")
            if w is not None and c.get("rack", c.get("leave_g", c["start"])) < w < c["end"]:
                c["walk_g"] = w
            gd = e.get("g_done")
            if gd is not None and gd < c["end"]:
                c["g_done_t"] = gd
                c["machine"] = {"Greasing": (c.get("leave_g", c["start"]), gd)}
                if gd >= c.get("walk_g", c["end"]):
                    c["g_done"] = gd
                elif gd >= c.get("rack", c.get("leave_g", c["start"])):
                    c["done_early"] = gd
            cyc.append(c)
        return self._self_check(cyc, ev)

    def _anchor_times(self, key, ev):
        L = ev["loops"]
        if key == "ylr":
            return [e["at_g"] for e in L if "rr_in" in e or "rr_out" in e]
        if key == "ysr":
            return [e["rr_in"] for e in L if "rr_in" in e]
        if key == "ysf":
            return [e["rr_out"] for e in L if "rr_out" in e]
        return list(ev["plates"])          # "plate": the small plate behind the Fr bed (once per rail of operator B)

    def _self_check(self, cycles, ev):
        """Cycles with frames missing for more than HOLE s are dropped; then per 10 minutes of the clock the cycles are
        compared with the neighbour's on the same frames, and a block that differs by more than SC_TOL (and more than
        SC_MIN) is left out of the statistics and the cycle table."""
        cycles = [c for c in cycles if not any(c["start"] < b and a < c["end"] for a, b in ev["holes"])]
        mine = [c["start"] for c in cycles]
        span = (min(mine), max(c["end"] for c in cycles)) if cycles else (0, 0)
        other = [t for t in self._anchor_times(self.NEIGHBOUR, ev) if span[0] <= t < span[1]]  # same stretch of time
        blocks = {}
        for t in mine:
            blocks.setdefault(int(t // self.SC_BLOCK), [0, 0])[0] += 1
        for t in other:
            blocks.setdefault(int(t // self.SC_BLOCK), [0, 0])[1] += 1
        self.check, keep_b = [], set()
        for b in sorted(blocks):
            nm, no = blocks[b]
            good = abs(nm - no) <= max(self.SC_TOL * max(nm, no), self.SC_MIN)
            self.check.append({"block": b * self.SC_BLOCK, "mine": nm, "other": no, "ok": good})
            if good:
                keep_b.add(b)
        return [c for c in cycles if int(c["start"] // self.SC_BLOCK) in keep_b]

    def _check_text(self, mine, other):
        chk = getattr(self, "check", [])
        if not chk:
            return []
        bad = [b for b in chk if not b["ok"]]
        out = [f"Self-check, {mine} / {other} per 10 minutes: "
               + ", ".join(f"{hm(b['block'])[:5]} {b['mine']}/{b['other']}{'' if b['ok'] else ' left out'}" for b in chk) + "."]
        if bad:
            out.insert(0, f"Self-check: {len(bad)} of {len(chk)} ten-minute blocks differ from the {other} by more than "
                          f"{100 * self.SC_TOL:.0f}% and are left out of the statistics and the cycle table (not validated).")
        return out

    def extra(self, cycles):
        out = []
        w = [c["leave_g"] - c["start"] for c in cycles if "leave_g" in c]
        if w:
            out.append(f"Operator at the greasing machine (bin pick, greased rail out, new rail in) median "
                       f"{stat.median(w):.1f}s of a {stat.median([c['end'] - c['start'] for c in cycles]):.1f}s cycle.")
        m = [b - a for c in cycles for a, b in (c.get("machine") or {}).values()]
        if m:
            wt = [c["end"] - c["g_done_t"] for c in cycles if "g_done_t" in c]
            out.append(f"Greasing (his leaving the machine to the slide moving back) median {stat.median(m):.1f}s; the "
                       f"greased rail then waits median {stat.median(wt):.1f}s until he is back (slide movement seen in "
                       f"{len(m)} of {len(cycles)} cycles).")
        p = [c["g_up"] - c["start"] for c in cycles if "g_up" in c]
        if p:
            out.append(f"Pick from the blue bin median {stat.median(p):.1f}s; {sum(1 for v in p if v > 2.5)} of {len(p)} "
                       f"picks took over 2.5 s (searching in the bin).")
        return out + self._check_text("greasing cycles", "Rr cycles")


class YSR(YLR):
    """YRA SEAT SLIDER, step 7 "Stopper Bending Rr & TAB Bending Rr m/c" (station 17; camera 17 = camera 18). The same
    operator A and loop as YLR (see there). The Rr nest always holds a rail: at every visit he exchanges it. Night crew
    (00:37-00:40): lays the greased rail from the rack into the nest and positions it with both hands (~1.2 s), presses
    the start button at the front left corner of the machine with his right hand (the clamp in the nest moves for a
    moment), then lifts the bent rail out (~1.3 s after the button) and lays it into the Fr nest one step to the right.
    Evening crew (21:56-21:59): lifts the bent rail out first, lays the greased rail in, presses the button and steps to
    the Fr nest with the bent rail. Day crew (2026-10-17 16:52-17:02): lays the rail in from the rack (median 3.5 s at
    the nest), positions it standing upright, presses the start button with his hands low at the front left corner and
    lifts the bent rail out as he steps right to the Fr nest. No bending stroke can be seen while he is away, so the Rr
    machine time is not measured; the rail stays in the nest until his next visit (~13 s)."""
    key, station_id, title = "ysr", 17, "Stopper Bending Rr & TAB Bending Rr m/c (YRA step 7)"
    NEIGHBOUR = "ylr"
    ORDER = [("EXCH", "rr_in"), ("START", "rr_btn"), ("FR", "rr_out"), ("AWAY", "fr_leave"), ("FETCH", "rack")]
    NAMES = {
        "EXCH": ("Rail exchange at the Rr nest (greased rail in, bent rail out)", "#2563eb"),
        "START": ("Start button; bent rail lifted, to the Fr", "#f59e0b"),
        "FR": ("Operator at the Fr nest (Rr machine holds the new rail)", "#16a34a"),
        "AWAY": ("Operator walks to and works at the greasing machine", "#94a3b8"),
        "FETCH": ("At the rack: greased rail down, next rail taken", "#a855f7"),
    }
    METHOD = [
        "One operator (A, front) runs steps 6 and 7 and loads step 8 in one loop (~13 s), followed from frame to frame "
        "(box bottom below y 0.85, at least 0.4 high, centre x 0.2-0.8, nearest to his last position).",
        "Cycle: his hand at the Rr nest → the next Rr exchange (a greasing visit without one, e.g. re-arranging rails, "
        "does not break the chain). Hand at the nest: feet at the front, no hand still at the rack (x ≥ 0.63, "
        "y ≥ 0.76), after the rack, and a wrist at x 0.44-0.565, y 0.52-0.68, or at x 0.44-0.62, y 0.52-0.75 with his "
        "centre at x 0.51-0.60 (the day crew stands nearer and lays the rail in lower). When he touches the nest several "
        "times (Fr machine stopped), the visit that sends a rail on to the Fr nest counts.",
        "Start: a wrist at the start button (x 0.47-0.56, y 0.685-0.79), before he walks back to the greasing machine · "
        "bent rail out to the Fr: after the button a wrist above y 0.58, the box top above y 0.33 or his centre right of "
        "x 0.625; with no button seen (low frame rates) his step to the Fr nest (feet back or centre right of x 0.625 in "
        "two frames). If his feet step back to the Fr nest (box bottom above y 0.95 in two frames) more than 1.6 s after "
        "that cue, or there is no cue, the rail comes out 0.3 s before that step and the start is the last time a wrist "
        "was at the button before it (day crew: upright at the nest and his hands low, which looked like the cues) · "
        "leaves the Fr nest: his walk to the greasing machine starts · at the rack: a wrist at x ≥ 0.65, y ≥ 0.78.",
        "The Rr nest always holds a rail; no bending stroke is visible while he is away, so the Rr machine time cannot be "
        "measured. Once (00:38:59) he went to the greasing machine's touch panel between the start and the rail out; "
        "that rail out is still found.",
        "Checked on full-resolution video: night 00:37-00:40 12/12 cycles, evening 21:56-21:59 13/13 (~1.3 frames/s), day "
        "2026-10-17 16:52-17:02 24/24 outside the two line stops, no extra cycles; hand at the nest within 0.24 / 0.06 / "
        "0.05 s, bent rail out within 0.25 / 0.06 / 0.08 s (median).",
        "Cycles with frames missing for more than 5 s are not used. Self-check: per 10 minutes of the clock, the Rr "
        "cycles are compared with the greasing cycles on the same frames; a block that differs by more than 20% (and "
        "more than 3) is left out of the statistics and the cycle table.",
        "Event times are the middle between the last frame before and the first frame with the cue.",
    ]
    UNSEEN = ["When the Rr machine bends and for how long (stopper / TAB bending): no stroke is visible; the nest is "
              "covered by his hands while he is there.",
              "Whether the rail he takes from the rack is the greased rail he has just laid there or one laid earlier.",
              "Day crew: the start button press itself (his hands are low at the front of the nest for most of the visit); "
              "its time is an estimate."]

    def detect(self, frames):
        ev = self.loops(frames)
        if not ev:
            return []
        L = [e for e in ev["loops"] if "rr_in" in e]   # one Rr exchange per loop; an extra greasing visit without one
        cyc = []                                        # (re-arranging rails, line stop) does not break the chain
        for e, nx in zip(L, L[1:]):
            if nx["rr_in"] - e["rr_in"] > self.MAX_CYCLE:
                continue
            c = {"start": e["rr_in"], "end": nx["rr_in"], "rr_in": e["rr_in"]}
            for k in ("rr_btn", "rr_out", "fr_leave"):
                if e.get(k) is not None and c["start"] <= e[k] < c["end"]:
                    c[k] = e[k]
            if nx.get("rack") is not None and c.get("fr_leave", c.get("rr_out", c["start"])) < nx["rack"] < c["end"]:
                c["rack"] = nx["rack"]
            if "rr_btn" in c and "rr_out" in c:
                c["machine"] = {"Start button": (c["rr_btn"], c["rr_btn"] + 0.3)}
            cyc.append(c)
        return self._self_check(cyc, ev)

    def extra(self, cycles):
        out = []
        at = [c["rr_out"] - c["start"] for c in cycles if "rr_out" in c]
        if at:
            out.append(f"Operator at the Rr machine (exchange, start, bent rail out) median {stat.median(at):.1f}s of a "
                       f"{stat.median([c['end'] - c['start'] for c in cycles]):.1f}s cycle.")
        b = [c["rr_out"] - c["rr_btn"] for c in cycles if "rr_out" in c and "rr_btn" in c]
        if b:
            out.append(f"Start button to the bent rail out median {stat.median(b):.1f}s (button seen in {len(b)} of "
                       f"{len(cycles)} cycles).")
        return out + self._check_text("Rr cycles", "greasing cycles")


class YSF(YLR):
    """YRA SEAT SLIDER, step 8 "Stopper Bending Fr & TAB Bending Fr m/c" (station 19; camera 19 = camera 18). Two
    people. Operator A (see YLR) lays the bent rail from the Rr machine into the Fr nest, pushes it in and reaches to
    the back of the nest (~3.7 s), then walks to the greasing machine. Operator B, behind the right end of the Fr
    machine, has his hands in the Fr nest from about when A lays the rail in (the light curtain over the nest turns
    red), lifts the rail out ~1-6 s after A has left, works on it upright in both hands (~6 s; the small vertical plate
    behind the Fr bed rises once ~1.2 s after he lifted the rail) and puts it down behind the machine on his right; then
    he reaches into the nest again for the next rail."""
    key, station_id, title = "ysf", 19, "Stopper Bending Fr & TAB Bending Fr m/c (YRA step 8)"
    NEIGHBOUR = "ysr"
    ORDER = [("LOAD", "rr_out"), ("NEST", "fr_leave"), ("HAND", "b_out"), ("BACK", "b_down")]
    NAMES = {
        "LOAD": ("A lays the rail into the Fr nest, pushes it in", "#2563eb"),
        "NEST": ("Rail in the Fr nest, B works it until he lifts it out", "#f59e0b"),
        "HAND": ("B works on the rail in his hands, puts it down", "#a855f7"),
        "BACK": ("B back at the Fr nest, waits for the next rail", "#94a3b8"),
    }
    METHOD = [
        "Operator A (front) is followed as in steps 6 and 7. Operator B: the person behind the right end of the Fr "
        "machine (box bottom y 0.55-0.85, top above y 0.30, centre x 0.66-0.88).",
        "Cycle: A lifts the bent rail out of the Rr nest and lays it into the Fr nest → the next rail he brings (a "
        "greasing visit without one does not break the chain; bent rail out as in step 7, day crew: 0.3 s before his "
        "feet step back to the Fr nest). A leaves the Fr nest when he starts walking to the greasing machine.",
        "B lifts the rail out: his hands were at the nest (a wrist below y 0.355 or left of x 0.72) in the 3 s before and "
        "then hold it up (all wrists above y 0.345 and right of x 0.72) for at least 1.5 s. B puts it down: both wrists "
        "0.02 (mean 0.026) lower than while he held it (two frames in a row), from 3 s after the lift. When he puts it "
        "down only after A's next rail, 'B works on the rail' runs to the end of the cycle.",
        "Checked on full-resolution video: night 00:37-00:40 12/12 cycles, evening 21:56-21:59 15/15, day 2026-10-17 "
        "16:52-17:02 24/24 outside the two line stops (Fr machine problems), no extra cycles; rail into the Fr nest "
        "within 0.25 / 0.06 / 0.08 s, B's lift-out within 0.12 / - / 0.05 s (median).",
        "Machine cue: the small vertical plate behind the Fr bed (x 0.618-0.635, y 0.25-0.42) is bright while it is up; it "
        "rises once per rail ~1.2 s after B lifted it out (shown with each cycle).",
        "Cycles with frames missing for more than 5 s are not used. Self-check: per 10 minutes of the clock, the Fr "
        "cycles are compared with the Rr cycles on the same frames; a block that differs by more than 20% (and more "
        "than 3) is left out of the statistics and the cycle table.",
        "Event times are the middle between the last frame before and the first frame with the cue.",
    ]
    UNSEEN = ["When the Fr machine bends and what B does in the nest: his and A's hands cover the nest; no separate machine "
              "stroke could be told apart.",
              "What B does to the rail in his hands (parts from the clear box behind him?) and what moves the small plate."]

    def detect(self, frames):
        ev = self.loops(frames)
        if not ev:
            return []
        L = [e for e in ev["loops"] if "rr_out" in e]  # one rail into the Fr nest per loop (see YSR)
        lifts = ev["lifts"]
        cyc = []
        for e, nx in zip(L, L[1:]):
            if nx["rr_out"] - e["rr_out"] > self.MAX_CYCLE:
                continue
            c = {"start": e["rr_out"], "end": nx["rr_out"], "rr_out": e["rr_out"]}
            if e.get("fr_leave") is not None and c["start"] < e["fr_leave"] < c["end"]:
                c["fr_leave"] = e["fr_leave"]
            lf = next((x for x in lifts if c["start"] + 1.0 <= x["b_out"] < c["end"]), None)
            if lf is not None:
                c["b_out"] = lf["b_out"]
                if lf["b_out"] < c.get("fr_leave", 0):   # B lifted it while A was still at the nest
                    c["a_leave_t"] = c.pop("fr_leave")
                if lf["b_down"] is not None:
                    c["b_down_t"] = lf["b_down"]
                    if lf["b_down"] < c["end"]:
                        c["b_down"] = lf["b_down"]
                pl = next((t for t in ev["plates"] if lf["b_out"] <= t < lf["b_out"] + 4.0), None)
                if pl is not None:
                    c["plate"] = pl
                    c["machine"] = {"Plate rises": (pl, pl + 0.6)}
            cyc.append(c)
        return self._self_check(cyc, ev)

    def extra(self, cycles):
        out = []
        a = [c.get("fr_leave", c.get("a_leave_t")) - c["start"] for c in cycles if "fr_leave" in c or "a_leave_t" in c]
        if a:
            out.append(f"Operator A at the Fr nest median {stat.median(a):.1f}s per cycle.")
        w = [c["b_out"] - c["fr_leave"] for c in cycles if "b_out" in c and "fr_leave" in c]
        if w:
            out.append(f"B lifts the rail out median {stat.median(w):.1f}s after A left the nest "
                       f"(lift-out seen in {sum(1 for c in cycles if 'b_out' in c)} of {len(cycles)} cycles).")
        h = [c["b_down_t"] - c["b_out"] for c in cycles if "b_down_t" in c and "b_out" in c]
        if h:
            late = sum(1 for c in cycles if "b_down_t" in c and c["b_down_t"] >= c["end"])
            out.append(f"B works on the rail in his hands median {stat.median(h):.1f}s; in {late} of {len(h)} cycles he "
                       f"puts it down only after A has laid the next rail in.")
        pl = [c["plate"] - c["b_out"] for c in cycles if "plate" in c]
        if pl:
            out.append(f"The small plate behind the Fr bed rises median {stat.median(pl):.1f}s after B lifted the rail "
                       f"({len(pl)} of {sum(1 for c in cycles if 'b_out' in c)} lifts).")
        return out + self._check_text("Fr cycles", "Rr cycles")


STATIONS = {"m1": M1, "m2": M2, "m34": M34, "m5": M5, "ymm": YMM, "yfi": YFI, "yml": YML, "yur": YUR, "yhs": YHS, "yxl": YXL, "yg1": YG1, "yg2": YG2, "ylr": YLR, "ysr": YSR, "ysf": YSF}


# ======================================================================== shared: segments, stats, report
def segments_of(st, c) -> list[dict]:
    """Element segments of one cycle: each element from its start event to the next present event (or the cycle end)."""
    ev = [(code, c[k]) for code, k in st.ORDER if ok(c.get(k))]
    out, last = [], -1e18
    ev = [(code, t) for code, t in ev if t >= c["start"] - 0.01]
    clean = []
    for code, t in ev:
        if t >= last:
            clean.append((code, t))
            last = t
    for (code, t), nxt in zip(clean, [t for _, t in clean[1:]] + [c["end"]]):
        if nxt > t:
            out.append({"code": code, "t0": t, "t1": nxt})
    return out


def analyse(st, t0: float, t1: float):
    frames = {cam: load_frames(cam, t0, t1) for cam in st.cams}
    if any(len(v) < 200 for v in frames.values()):
        return None
    cycles = st.detect(*[frames[c] for c in st.cams])
    for c in cycles:
        c["segments"] = segments_of(st, c)
        c["sec"] = c["end"] - c["start"]
        c["el"] = {code: sum(s["t1"] - s["t0"] for s in c["segments"] if s["code"] == code) for code in st.NAMES}
        c["have"] = {s["code"] for s in c["segments"]}
    return frames, cycles


def classify(cycles):
    secs = [c["sec"] for c in cycles]
    med = stat.median(secs) if secs else 0
    stop = max(45.0, 3 * med)
    for c in cycles:
        c["stop"] = bool(c["sec"] > stop)
        c["normal"] = bool((not c["stop"]) and c["sec"] <= 1.5 * med)
    return med


def build(key: str, t0: float, t1: float, v0: float | None, v1: float | None, auto: bool) -> Path | None:
    st = STATIONS[key]()
    got = analyse(st, t0, t1)
    if got is None:
        print("not enough recording"); return None
    frames, cycles = got
    if len(cycles) < 15:
        print("too few cycles (line stopped?)"); return None
    med = classify(cycles)
    work = [c for c in cycles if not c["stop"]]
    normal = [c for c in cycles if c["normal"]]
    q = lambda v, p: [round(float(x), 1) for x in np.percentile(v, p)] if len(v) else [0, 0]  # noqa: E731
    el_stats = {}
    for code in st.NAMES:
        v = [c["el"][code] for c in work if code in c["have"]]
        if v:
            el_stats[code] = {"med": round(stat.median(v), 1), "q": q(v, [10, 90]), "n": len(v)}
    span = t1 - t0
    covered = {code: sum(c["el"][code] for c in cycles) for code in st.NAMES}
    in_cycles = sum(c["sec"] for c in cycles)
    share = {code: round(100 * v / span, 1) for code, v in covered.items()}
    gaps = round(100 * max(0.0, span - in_cycles) / span, 1)
    S = {"cycles": len(cycles), "per_hour": round(len(work) / (span / 3600)), "cycle_med": round(stat.median([c["sec"] for c in work]), 1),
         "cycle_q": q([c["sec"] for c in work], [25, 75]), "abnormal": len(cycles) - len(normal), "stops": len([c for c in cycles if c["stop"]]),
         "el": el_stats, "share": share, "gaps": gaps,
         "lost": round(sum(c["sec"] - med for c in cycles if not c["normal"] and not c["stop"]), 0)}
    print(json.dumps({k: v for k, v in S.items() if k != "share"}, indent=1, default=str))
    for c in cycles:
        c["flag"] = "stop" if c["stop"] else ("normal" if c["normal"] else "long")
        c["note"] = "Line stop" if c["stop"] else ("" if c["normal"] else f"Long cycle (+{c['sec'] - S['cycle_med']:.0f}s)")

    # video window: the latest ~5.5 min with cycles (auto), or the given one
    if v0 is None:
        v1 = max(c["end"] for c in cycles) + 3
        v0 = max(t0, v1 - 330)
    segs = []
    for c in cycles:
        for s in c["segments"]:
            if s["t1"] > v0 and s["t0"] < v1:
                segs.append({"code": s["code"], "t0": max(s["t0"], v0), "t1": min(s["t1"], v1)})
    names = dict(st.NAMES)
    names["GAP"] = ("No cycle detected / stopped", "#7f1d1d")
    cur = v0
    for s in sorted(segs, key=lambda s: s["t0"]):
        if s["t0"] - cur > 3:
            segs.append({"code": "GAP", "t0": cur, "t1": s["t0"]})
        cur = max(cur, s["t1"])
    if v1 - cur > 3:
        segs.append({"code": "GAP", "t0": cur, "t1": v1})
    segs.sort(key=lambda s: s["t0"])
    vcyc = [dict(c) for c in cycles if c["start"] >= v0 and c["end"] <= v1]
    for n, c in enumerate(vcyc, start=1):
        c["n"] = n

    day = datetime.fromtimestamp(v0).strftime("%Y-%m-%d")
    name = f"auto_{key}_{datetime.fromtimestamp(v0):%Y%m%d_%H%M}" if auto else f"{key}-breakup_{datetime.fromtimestamp(v0):%Y%m%d_%H%M}"
    out = settings.reports_dir / (name + ".tmp")
    (out / "frames").mkdir(parents=True, exist_ok=True)
    vfr = {cam: [f for f in frames[cam] if v0 - 2 <= f["t"] <= v1 + 2] for cam in st.cams}
    vtimes = write_video(st, vfr, v0, v1, segs, vcyc, names, out / "video.webm")
    (out / "timeline.json").write_text(json.dumps(timeline(vtimes, segs, vcyc, names), separators=(",", ":")), encoding="utf-8")
    var = variation_data([(code, st.NAMES[code][0], st.NAMES[code][1]) for code, _ in st.ORDER],
                         [dict(c, el={code: (c["el"][code] if code in c["have"] else None) for code, _ in st.ORDER}) for c in cycles], v0, v1)
    (out / "cycles.json").write_text(json.dumps(var, separators=(",", ":")), encoding="utf-8")
    page = render(st, S, cycles, vcyc, names, t0, t1, v0, v1, out, frames, auto)
    (out / "index.html").write_text(page, encoding="utf-8")
    top = max(el_stats.items(), key=lambda kv: kv[1]["med"]) if el_stats else None
    meta = {"title": f"{st.title} — element breakup", "subtitle": "Element times of every cycle, checked against the video",
            "camera_id": st.cams[0], "cameras": list(st.cams) + list(getattr(st, "also_cameras", ())), "station_id": st.station_id, "auto": auto, "date": day, "window": f"{hm(v0)} – {hm(v1)}",
            "cycles": len(vcyc), "median_cycle": S["cycle_med"],
            "highlights": [f"Cycle ~{S['cycle_med']:.1f}s ({S['per_hour']}/h), {S['abnormal']} abnormal cycles"]
            + ([f"Longest element: {st.NAMES[top[0]][0]} ~{top[1]['med']:.1f}s"] if top else []) + [x for x in st.extra(work) if x][:1]}
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "data.json").write_text(json.dumps({"stats": S, "window": [t0, t1], "video": [v0, v1],
                                               "cycles": [{k: v for k, v in c.items() if k not in ("segments", "have")} for c in cycles]},
                                              indent=1, default=lambda o: sorted(o) if isinstance(o, set) else str(o)), encoding="utf-8")
    final = settings.reports_dir / name
    publish(out, final)
    print("report", final)
    return final


def hm(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


def write_video(st, vfr, v0, v1, segs, cycles, names, path) -> list[float]:
    two = len(st.cams) == 2
    W, H = (480, 270) if two else (640, 360)
    times = list(np.arange(v0, v1, 1 / 3))
    Ts = {cam: np.array([f["t"] for f in vfr[cam]]) for cam in st.cams}
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"VP90"), 3.0, (W * len(st.cams), H + 56))
    last: dict = {}

    def pic(cam, t):
        T = Ts[cam]
        if not len(T):
            return np.zeros((H, W, 3), np.uint8)
        i = int(np.argmin(np.abs(T - t)))
        if abs(T[i] - t) > 1.5:
            return np.zeros((H, W, 3), np.uint8)
        if last.get(cam, (None,))[0] != i:
            img = read_frame(vfr[cam][i])
            last[cam] = (i, cv2.resize(img, (W, H)) if img is not None else np.zeros((H, W, 3), np.uint8))
        return last[cam][1]

    for t in times:
        tiles = []
        for cam in st.cams:
            im = pic(cam, t).copy()
            cv2.putText(im, f"Cam {cam}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            tiles.append(im)
        img = np.vstack([np.zeros((56, W * len(st.cams), 3), np.uint8), np.hstack(tiles)])
        s = next((x for x in segs if x["t0"] <= t < x["t1"]), None)
        c = next((x for x in cycles if x["start"] <= t < x["end"]), None)
        head = hm(t) + (f"   Cycle {c['n']}   {t - c['start']:4.1f}s / {c['sec']:.1f}s" if c else "")
        cv2.putText(img, head, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        if s:
            col = tuple(int(names[s["code"]][1][q:q + 2], 16) for q in (5, 3, 1))
            cv2.rectangle(img, (10, 32), (26, 50), col, -1)
            cv2.putText(img, f"{names[s['code']][0][:66]}  {t - s['t0']:.1f}s", (32, 47), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        vw.write(img)
    vw.release()
    return times


def render(st, S, cycles, vcyc, names, t0, t1, v0, v1, out, frames, auto) -> str:
    esc = html.escape
    codes = [code for code, _ in st.ORDER]
    vt = lambda t: max(0.0, t - v0)  # noqa: E731
    # one frame per element of a typical cycle
    typ = min([c for c in vcyc if c["normal"]] or vcyc or cycles, key=lambda c: abs(c["sec"] - S["cycle_med"]))
    shots = []
    for k, s in enumerate(typ["segments"], start=1):
        tm, imgs = (s["t0"] + s["t1"]) / 2, []
        for cam in st.cams:
            fr = min(frames[cam], key=lambda f: abs(f["t"] - tm))
            im = read_frame(fr)
            imgs.append(cv2.resize(im, (320, 180)) if im is not None else np.zeros((180, 320, 3), np.uint8))
        cv2.imwrite(str(out / "frames" / f"seg{k}.jpg"), np.hstack(imgs), [cv2.IMWRITE_JPEG_QUALITY, 80])
        shots.append(f"<tr onclick=\"seek({vt(s['t0']):.2f})\"><td class=n>{k}</td><td><span class=dot style=\"background:{names[s['code']][1]}\"></span>"
                     f"{esc(names[s['code']][0])}</td><td class=num>{s['t0'] - typ['start']:.1f} – {s['t1'] - typ['start']:.1f}s</td>"
                     f"<td class=num><b>{s['t1'] - s['t0']:.1f}s</b></td><td><img src=\"frames/seg{k}.jpg\" alt=\"\" loading=lazy></td></tr>")
    kpis = "".join(f"<div class=kpi><b>{S['el'][c]['med']:.1f}s</b><span><span class=dot style=\"background:{st.NAMES[c][1]}\"></span>"
                   f"{esc(st.NAMES[c][0])} (80%: {S['el'][c]['q'][0]}–{S['el'][c]['q'][1]}s)</span></div>" for c in codes if c in S["el"])
    heads = "".join(f"<th>{esc(st.NAMES[c][0].split(' (')[0][:28])}</th>" for c in codes)
    rows = []
    for c in vcyc:
        cells = "".join(f"<td class=num>{c['el'][code]:.1f}</td>" if code in c["have"] else "<td class=num>–</td>" for code in codes)
        note = c["note"] or "Normal"
        mach = "".join(f" · {esc(k)} {a - c['start']:+.1f}s" for k, (a, b) in (c.get("machine") or {}).items())
        rows.append(f"<tr{'' if c['normal'] else ' class=bad'} onclick=\"seek({vt(c['start']):.2f})\"><td class=n>{c['n']}</td>"
                    f"<td class=num>{hm(c['start'])}</td><td class=num><b>{c['sec']:.1f}s</b></td>{cells}<td>{esc(note)}{mach}</td></tr>")
    split = "".join(f'<i style="width:{S["share"][c]}%;background:{st.NAMES[c][1]}" title="{esc(st.NAMES[c][0])} {S["share"][c]}%"></i>'
                    for c in codes if S["share"].get(c))
    split_leg = "".join(f'<span><span class=dot style="background:{st.NAMES[c][1]}"></span>{esc(st.NAMES[c][0].split(" (")[0][:34])} {S["share"][c]}%</span>'
                        for c in codes if S["share"].get(c)) + (f"<span>outside cycles / stopped {S['gaps']}%</span>" if S["gaps"] > 0.5 else "")
    legend = "".join(f'<span><span class=dot style="background:{v[1]}"></span>{esc(v[0])}</span>' for v in names.values())
    top = sorted(((S["el"][c]["med"], c) for c in codes if c in S["el"]), reverse=True)[:2]
    var = sorted(((S["el"][c]["q"][1] - S["el"][c]["q"][0], c) for c in codes if c in S["el"]), reverse=True)[:1]
    obs = [f"Cycle ~{S['cycle_med']:.1f}s (middle 50 %: {S['cycle_q'][0]}–{S['cycle_q'][1]}s), {S['per_hour']} per hour."]
    obs += [f"{'Longest element' if i == 0 else 'Next'}: {esc(st.NAMES[c][0])} ~{m:.1f}s ({100 * m / max(1, S['cycle_med']):.0f}% of the cycle)."
            for i, (m, c) in enumerate(top)]
    if var:
        obs.append(f"Most variable element: {esc(st.NAMES[var[0][1]][0])} (80 % of cycles {S['el'][var[0][1]]['q'][0]}–{S['el'][var[0][1]]['q'][1]}s).")
    if S["stops"]:
        obs.append(f"{S['stops']} line stops (cycle over {max(45, 3 * S['cycle_med']):.0f}s), red in the table.")
    if S["abnormal"] - S["stops"] > 0:
        obs.append(f"{S['abnormal'] - S['stops']} long cycles (over 1.5× median), ~{S['lost']:.0f}s lost in total.")
    obs += [esc(x) for x in st.extra([c for c in cycles if not c["stop"]]) if x]
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{esc(st.title)} breakup</title>
<style>
:root{{--bg:#f8fafc;--panel:#fff;--ink:#0f172a;--ink2:#475569;--edge:#e2e8f0;--bad:#fef2f2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1220;--panel:#111827;--ink:#e5e7eb;--ink2:#9ca3af;--edge:#1f2937;--bad:#3b1111}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}} main{{max-width:1180px;margin:0 auto;padding:16px}}
h1{{font-size:20px;margin:4px 0}} h2{{font-size:16px;margin:22px 0 8px}} .sub{{color:var(--ink2)}}
.card{{background:var(--panel);border:1px solid var(--edge);border-radius:10px;padding:14px;margin:12px 0}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}} .kpi b{{display:block;font-size:22px}} .kpi span{{color:var(--ink2);font-size:12px}}
video{{width:100%;background:#000;border-radius:8px}} table{{width:100%;border-collapse:collapse}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--edge);text-align:left}} th{{font-size:12px;color:var(--ink2)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}} td.n{{color:var(--ink2)}} tr.bad{{background:var(--bad)}} tbody tr{{cursor:pointer}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}}
.legend{{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--ink2);margin:6px 0}} ul,ol{{margin:6px 0;padding-left:20px}} li{{margin:4px 0}}
td img{{width:200px;border-radius:4px}} .scroll{{overflow:auto;max-height:480px}}
.split{{display:flex;height:22px;border-radius:5px;overflow:hidden;margin:8px 0;background:var(--edge)}} .split i{{display:block;height:100%}}
</style>{PLAYER_HEAD}</head><body><main>
<h1>{esc(st.title)} — element breakup</h1>
<div class=sub>Camera {' + '.join(str(c) for c in st.cams)} · {datetime.fromtimestamp(v0):%Y-%m-%d} · statistics {hm(t0)}–{hm(t1)} ({(t1 - t0) / 60:.0f} min, {S['cycles']} cycles) · video {hm(v0)}–{hm(v1)}{' · automatic report (' + datetime.now().strftime('%H:%M') + ')' if auto else ''}</div>
<div class="card kpis"><div class=kpi><b>{S['cycle_med']:.1f}s</b><span>normal cycle (median; middle 50 % {S['cycle_q'][0]}–{S['cycle_q'][1]}s) · {S['per_hour']}/h</span></div>{kpis}</div>
<div class=card><b>Where the time went ({(t1 - t0) / 60:.0f} min)</b><div class=split>{split}</div><div class=legend>{split_leg}</div></div>
<div class=card><video id=v src="video.webm" controls preload=metadata></video><div class=legend>{legend}</div>
<div class=sub>Overlay: clock, cycle number and timer, current element. Click a table row to jump there.</div></div>
{VARIATION_HTML}
<h2>One normal cycle (Cycle {typ.get('n', '')}: {hm(typ['start'])}, {typ['sec']:.1f}s)</h2>
<div class="card scroll"><table><thead><tr><th>#</th><th>Element</th><th>In cycle</th><th>Time</th><th>Frame</th></tr></thead><tbody>{''.join(shots)}</tbody></table></div>
<h2>Every cycle in the video (seconds)</h2>
<div class="card scroll"><table><thead><tr><th>#</th><th>Start</th><th>Cycle</th>{heads}<th>Note</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<h2>Findings</h2><div class=card><ul>{''.join(f'<li>{o}</li>' for o in obs)}</ul></div>
<h2>Method</h2><div class=card><ul>{''.join(f'<li>{esc(m)}</li>' for m in st.METHOD)}</ul>
<b>Not visible on camera</b><ul>{''.join(f'<li>{esc(u)}</li>' for u in st.UNSEEN)}</ul></div>
</main>{PLAYER_BODY}{CHARTS_BODY}</body></html>"""


# ======================================================================== validation against the frame-by-frame annotations
VALIDATION_RECORDINGS = settings.data_dir / "validation_recordings"  # night 2026-10-09 23:30 - 10-10 00:40, all cameras
# further saved stretches, one folder each (data/validation_recordings_<name>/cam_<id>/, same layout as the recordings), e.g.
# validation_recordings_yfi1021 = camera 13, 2026-10-21 12:59-16:11 (yfi day1021 set and the afternoon count check)


def validation_dir(cams, t0: float, t1: float) -> Path | None:
    """the saved recordings folder whose segments cover [t0, t1] for all cameras (None: use the live recordings)"""
    lo = datetime.fromtimestamp(t0 - 70).strftime("%Y%m%d_%H%M%S")
    hi = datetime.fromtimestamp(t1).strftime("%Y%m%d_%H%M%S")
    dirs = [VALIDATION_RECORDINGS] + sorted(p for p in settings.data_dir.glob("validation_recordings_*") if p.is_dir())
    for d in dirs:
        if all((d / f"cam_{cam}").is_dir() and any(lo <= p.name[:-6] <= hi for p in (d / f"cam_{cam}").glob("*.jsonl"))
               for cam in cams):
            return d
    return None


def validate(key: str, which: str = "", quiet: bool = False) -> dict | None:
    """which = "" (<key>_annotations.json) or the set name (<key>_<which>_annotations.json, e.g. "day", "night", "late",
    "grey", "evening", "45fps", "5fps", "day1652", "day1612", "day1021").
    An annotated cycle is matched on its first annotated step (within 4 s). Detected cycles that match no annotation and
    start inside an annotated cycle are extra (false) cycles; annotated cycles marked "stop" (line stops: the detectors
    leave out cycles over 60 s) are counted apart, and so are extra cycles inside them. Returns the numbers as a dict."""
    st = STATIONS[key]()
    ann = load_annotations(key, which)
    t0, t1 = annotation_window(ann)
    d = validation_dir(st.cams, t0, t1) or (VALIDATION_RECORDINGS if VALIDATION_RECORDINGS.exists() else None)
    if d is not None:  # the live recordings are only kept 12 h
        settings.recordings_dir = d
    got = analyse(st, t0, t1)
    if got is None:
        print("recording no longer available for", hm(t0)); return None
    res = score(st, ann, got[1])
    res.update({"key": key, "which": which or "-"})
    if quiet:
        return res
    print(f"{key}: {res['found']}/{res['annotated']} annotated cycles found")
    print(f"  normal cycles {res['normal_found']}/{res['normal']}, line-stop cycles {res['stop_found']}/{res['stop']}; extra "
          f"cycles {len(res['extra'])}{' ' + ' '.join(res['extra']) if res['extra'] else ''}"
          f"{' (+%d inside line stops)' % len(res['extra_in_stops']) if res['extra_in_stops'] else ''}"
          f"{'; missed ' + ' '.join(res['missed']) if res['missed'] else ''}")
    for k, e in res["err"].items():
        print(f"  {k:24s} n={e['n']:2d}/{e['of']:2d}  median|err| {e['med'] if e['med'] is not None else float('nan'):.2f}s  "
              f"max {e['max'] if e['max'] is not None else float('nan'):.2f}s  within 0.5s {e['in05']}")
    if "rivet" in res:
        r = res["rivet"]
        print(f"  pop rivet flag: inner rails (gun used) {r['inner'][0]}/{r['inner'][1]} right, outer rails (not used) "
              f"{r['outer'][0]}/{r['outer'][1]} right{'; wrong ' + ' '.join(r['wrong']) if r['wrong'] else ''}")
    return res


def load_annotations(key: str, which: str = "") -> list[dict]:
    return json.load(open(HERE / "validation" / f"{key}{'_' + which if which else ''}_annotations.json", encoding="utf-8"))


def annotation_window(ann) -> tuple[float, float]:
    times = [v for a in ann for v in a.values() if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 1e9]
    return min(times) - 60, max(times) + 60


def score(st, ann, cycles) -> dict:
    """Detected cycles against the annotated ones (see validate)."""
    # an annotated cycle is matched on its first annotated step (some steps are not visible in every cycle)
    def first_key(a):
        return "start" if ok(a.get("start")) else next((k for _, k in st.ORDER if ok(a.get(k))), None)
    keys = [k for _, k in st.ORDER] + ["end"] + [k for k in ("rivet_t0", "rivet_t1") if any(ok(a.get(k)) for a in ann)]
    errs = {k: [] for k in keys}
    found, used, missed = 0, set(), []
    riv = []                       # (annotated rivet flag, detected rivet flag, annotated load) of matched rails
    n_stop = f_stop = 0
    for a in ann:
        k0 = first_key(a)
        if k0 is None:
            continue
        n_stop += bool(a.get("stop"))
        m = [c for c in cycles if ok(c.get(k0)) and abs(c[k0] - a[k0]) < 4]
        if not m:
            if not a.get("stop"):
                missed.append(a[k0])
            continue
        found += 1
        f_stop += bool(a.get("stop"))
        used.add(id(m[0]))
        for k in keys:
            if ok(a.get(k)):
                errs[k].append(m[0][k] - a[k] if ok(m[0].get(k)) else None)
        if isinstance(a.get("rivet"), bool):
            riv.append((a["rivet"], m[0].get("rivet"), a[k0]))
    # extra cycles: not matched, and starting (on the matching step) inside an annotated cycle (sets with gaps between
    # the annotated cycles are not penalised for cycles in the gaps)
    spans = []
    for i, a in enumerate(ann):
        k0 = first_key(a)
        if k0 is None:
            continue
        nxt = next((b for b in ann[i + 1:] if first_key(b)), None)
        e = a["end"] if ok(a.get("end")) else (nxt[first_key(nxt)] if nxt else None)
        if e is not None and e > a[k0]:
            spans.append((a[k0], e, k0, bool(a.get("stop"))))
    extra, extra_stop = [], []
    for c in cycles:
        if id(c) in used:
            continue
        for s0, s1, k0, stop_ in spans:
            t = c.get(k0, c["start"])
            if ok(t) and s0 + 1.0 < t < s1 - 2.0:      # (just before the next annotated start: that cycle, early)
                (extra_stop if stop_ else extra).append(t)
                break
    n_ann = sum(1 for a in ann if first_key(a))
    res = {"annotated": len(ann), "found": found, "normal": n_ann - n_stop,
           "normal_found": found - f_stop, "stop": n_stop, "stop_found": f_stop, "missed": [hm(t) for t in missed],
           "extra": [hm(t) for t in extra], "extra_in_stops": [hm(t) for t in extra_stop], "err": {}}
    if riv:                        # pop rivet flag of the matched rails (inner = gun used, outer = not)
        res["rivet"] = {"inner": [sum(1 for a, d, _ in riv if a and d is True), sum(1 for a, _, _ in riv if a)],
                        "outer": [sum(1 for a, d, _ in riv if not a and d is False), sum(1 for a, _, _ in riv if not a)],
                        "wrong": [hm(t) for a, d, t in riv if d is not a]}
    for k in keys:
        v = [x for x in errs[k] if x is not None]
        if errs[k]:
            ab = sorted(abs(float(x)) for x in v)
            res["err"][k] = {"n": len(v), "of": len(errs[k]), "med": round(stat.median(ab), 2) if ab else None,
                             "max": round(max(ab), 2) if ab else None, "in05": int(sum(x <= 0.5 for x in ab))}
    return res


def main() -> None:
    key = sys.argv[1]
    if key not in STATIONS:
        sys.exit(f"unknown station {key}; use one of {list(STATIONS)}")
    if sys.argv[2:3] == ["--validate"]:
        validate(key, sys.argv[3] if len(sys.argv) > 3 else ""); return
    if sys.argv[2:3] == ["--auto"]:
        cam = STATIONS[key].cams[0]
        recent = load_frames(cam, time.time() - 900, time.time())
        if not recent:
            print("no recent recording"); sys.exit(1)
        t1 = recent[-1]["t"] - 2
        res = build(key, t1 - 3600, t1, None, None, auto=True)
    else:
        a, b, va, vb = sys.argv[2:6]
        day = sys.argv[6] if len(sys.argv) > 6 else datetime.now().strftime("%Y-%m-%d")
        ts = lambda s: time.mktime(time.strptime(f"{day} {s}", "%Y-%m-%d %H:%M:%S"))  # noqa: E731
        res = build(key, ts(a), ts(b), ts(va), ts(vb), auto=False)
    sys.exit(0 if res else 1)


if __name__ == "__main__":
    main()
