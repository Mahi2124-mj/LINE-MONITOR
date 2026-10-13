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


STATIONS = {"m1": M1, "m2": M2, "m34": M34, "m5": M5}


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
            "camera_id": st.cams[0], "cameras": list(st.cams), "station_id": st.station_id, "auto": auto, "date": day, "window": f"{hm(v0)} – {hm(v1)}",
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


def validate(key: str, which: str = "") -> None:
    """which = "" (night set, <key>_annotations.json) or "day" (<key>_day_annotations.json; m1 only)."""
    if VALIDATION_RECORDINGS.exists():  # the live recordings are only kept 12 h
        settings.recordings_dir = VALIDATION_RECORDINGS
    st = STATIONS[key]()
    ann = json.load(open(HERE / "validation" / f"{key}{'_' + which if which else ''}_annotations.json", encoding="utf-8"))
    starts = [a.get("start") or a[st.ORDER[0][1]] for a in ann]
    t0, t1 = min(starts) - 60, max(a["end"] for a in ann) + 60
    got = analyse(st, t0, t1)
    if got is None:
        print("recording no longer available for", hm(t0)); return
    _, cycles = got
    keys = [k for _, k in st.ORDER] + ["end"]
    errs = {k: [] for k in keys}
    found = 0
    for a in ann:
        s = a.get("start") or a[st.ORDER[0][1]]
        m = [c for c in cycles if abs(c["start"] - s) < 4]
        if not m:
            continue
        found += 1
        for k in keys:
            if ok(a.get(k)):
                errs[k].append(m[0][k] - a[k] if ok(m[0].get(k)) else None)
    print(f"{key}: {found}/{len(ann)} annotated cycles found")
    for k in keys:
        v = [x for x in errs[k] if x is not None]
        if errs[k]:
            ab = sorted(abs(x) for x in v)
            print(f"  {k:24s} n={len(v):2d}/{len(errs[k]):2d}  median|err| {stat.median(ab) if ab else float('nan'):.2f}s  "
                  f"max {max(ab) if ab else float('nan'):.2f}s  within 0.5s {sum(x <= 0.5 for x in ab)}")


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
