"""Synthetic top-down workstation camera used in demo mode.

It renders a bench with a part fixture, part bins and in/out conveyors, plus an operator
(head, shoulders, arms, hands) doing the assembly. Stations of one line are coupled through
small buffers (LineFlow), so the bottleneck starves downstream steps and blocks upstream
steps just like a real line. The frames go through the *real* vision pipeline
(part-presence cycle detection against an empty reference image), while the operator's
hand/body positions are exposed as ground truth for the SimulatedTracker.
"""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

W, H = 640, 360

# ---- scene layout (normalized coordinates) – also used to create the demo zones
FIXTURE = (0.43, 0.53, 0.57, 0.71)
PART_ZONE = [[0.39, 0.49], [0.61, 0.49], [0.61, 0.75], [0.39, 0.75]]
WORK_AREA = [[0.17, 0.27], [0.83, 0.27], [0.83, 1.0], [0.17, 1.0]]
TRIGGER_ZONE = [[0.80, 0.53], [0.97, 0.53], [0.97, 0.72], [0.80, 0.72]]
BINS = [
    {"name": "Bin A", "center": (0.31, 0.42), "far": False, "color": (200, 140, 40)},
    {"name": "Bin B", "center": (0.69, 0.42), "far": False, "color": (40, 170, 220)},
    {"name": "Far rack", "center": (0.07, 0.86), "far": True, "color": (60, 60, 200)},
]
PICK_HALF = (0.055, 0.06)
CONVEYOR_Y = (0.555, 0.685)
PART_Y = 0.62
PART_HALF = (0.055, 0.07)
BODY_HOME = (0.5, 0.965)
REST_L, REST_R = (0.41, 0.86), (0.59, 0.86)
FIX_L, FIX_R = (0.465, 0.64), (0.535, 0.64)
SHOULDER_W = 0.16  # normalized -> 0.40 m => frame width ~2.5 m
HAND_SPEED = 0.33  # normalized units / s
LAYER_COLORS = [(70, 200, 90), (220, 160, 60), (90, 120, 230), (200, 90, 200), (60, 200, 220), (230, 230, 230), (40, 90, 200)]


def demo_zones() -> list[dict]:
    zones = [
        {"id": "work", "name": "Normal work area", "type": "work_area", "station_id": None, "points": WORK_AREA},
        {"id": "part", "name": "Part fixture", "type": "part_zone", "station_id": None, "points": PART_ZONE},
        {"id": "out", "name": "Out conveyor", "type": "trigger_zone", "station_id": None, "points": TRIGGER_ZONE},
        # moving parts on the conveyors are not operator motion
        {"id": "conv_in", "name": "In conveyor", "type": "exclusion", "station_id": None,
         "points": [[0.0, CONVEYOR_Y[0]], [0.385, CONVEYOR_Y[0]], [0.385, CONVEYOR_Y[1]], [0.0, CONVEYOR_Y[1]]]},
        {"id": "conv_out", "name": "Out conveyor", "type": "exclusion", "station_id": None,
         "points": [[0.615, CONVEYOR_Y[0]], [1.0, CONVEYOR_Y[0]], [1.0, CONVEYOR_Y[1]], [0.615, CONVEYOR_Y[1]]]},
    ]
    for i, b in enumerate(BINS):
        cx, cy = b["center"]
        hx, hy = PICK_HALF
        zones.append({"id": f"pick{i+1}", "name": b["name"], "type": "pick_zone", "station_id": None,
                      "points": [[cx - hx, cy - hy], [cx + hx, cy - hy], [cx + hx, cy + hy], [cx - hx, cy + hy]]})
    return zones


# ------------------------------------------------------------------ line coupling
class LineFlow:
    """Unit buffers between consecutive simulated stations of the same line."""

    CAPACITY = 2

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.positions: dict[int, set[int]] = {}
        self.buffers: dict[tuple[int, int], int] = {}  # (line, seq) -> units waiting after station seq
        self.reserved: dict[tuple[int, int], int] = {}

    def register(self, line: int, seq: int) -> None:
        with self.lock:
            self.positions.setdefault(line, set()).add(seq)
            self.buffers.setdefault((line, seq), 1)
            self.reserved.setdefault((line, seq), 0)

    def unregister(self, line: int, seq: int) -> None:
        with self.lock:
            self.positions.get(line, set()).discard(seq)

    def _up(self, line: int, seq: int) -> int | None:
        s = [p for p in self.positions.get(line, ()) if p < seq]
        return max(s) if s else None

    def _down(self, line: int, seq: int) -> int | None:
        s = [p for p in self.positions.get(line, ()) if p > seq]
        return min(s) if s else None

    def try_take(self, line: int, seq: int) -> bool:
        with self.lock:
            up = self._up(line, seq)
            if up is None:
                return True  # first station: unlimited raw material
            if self.buffers.get((line, up), 0) > 0:
                self.buffers[(line, up)] -= 1
                return True
            return False

    def try_reserve_out(self, line: int, seq: int) -> bool:
        with self.lock:
            if self._down(line, seq) is None:
                return True  # last station: finished goods leave the line
            k = (line, seq)
            if self.buffers.get(k, 0) + self.reserved.get(k, 0) < self.CAPACITY:
                self.reserved[k] = self.reserved.get(k, 0) + 1
                return True
            return False

    def push(self, line: int, seq: int) -> None:
        with self.lock:
            k = (line, seq)
            if self._down(line, seq) is None:
                return
            self.reserved[k] = max(0, self.reserved.get(k, 0) - 1)
            self.buffers[k] = self.buffers.get(k, 0) + 1

    def queue_before(self, line: int, seq: int) -> int:
        with self.lock:
            up = self._up(line, seq)
            return 3 if up is None else self.buffers.get((line, up), 0)


LINE_FLOW = LineFlow()


# ------------------------------------------------------------------ animation helpers
def _smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


class Anim:
    """Piecewise eased interpolation between keyframes of a 2D point."""

    def __init__(self, t: float, pos: tuple[float, float]) -> None:
        self.kf: list[tuple[float, tuple[float, float]]] = [(t, pos)]

    @property
    def last(self) -> tuple[float, float]:
        return self.kf[-1][1]

    def to(self, t: float, pos: tuple[float, float]) -> None:
        if t <= self.kf[-1][0]:
            t = self.kf[-1][0] + 1e-3
        self.kf.append((t, pos))

    def hold(self, t: float) -> None:
        self.to(t, self.last)

    def at(self, t: float) -> tuple[float, float]:
        kf = self.kf
        if t <= kf[0][0]:
            return kf[0][1]
        if t >= kf[-1][0]:
            return kf[-1][1]
        lo, hi = 0, len(kf) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if kf[mid][0] <= t:
                lo = mid
            else:
                hi = mid
        (t0, p0), (t1, p1) = kf[lo], kf[hi]
        a = _smooth((t - t0) / (t1 - t0))
        return (p0[0] + (p1[0] - p0[0]) * a, p0[1] + (p1[1] - p0[1]) * a)


def _d(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class SimParams:
    target_cycle_sec: float
    expected_picks: int
    speed_factor: float = 1.0
    far_reach_prob: float = 0.1
    walk_prob: float = 0.05
    extra_pick_prob: float = 0.1


# ------------------------------------------------------------------ the source
class SyntheticSource:
    is_synthetic = True

    def __init__(self, line_id: int, sequence: int, station_name: str, parts: list[str], params: SimParams, seed: int = 0) -> None:
        self.line_id, self.sequence = line_id, sequence
        self.station_name, self.parts = station_name, parts
        self.p = params
        # seed=0 -> fresh randomness on every start, so a restart does not replay the same cycles
        self.rng = random.Random(seed) if seed else random.Random()
        self.width, self.height = W, H
        self._bg = self._render_background()
        nr = np.random.default_rng(sequence)
        self._noise = [nr.integers(0, 6, (H, W, 3), dtype=np.uint8) for _ in range(4)]
        self._frame_i = 0
        self._gt: dict | None = None
        self._lock = threading.Lock()
        self.opened = False
        t = time.time()
        self.state = "wait_part"
        self.state_until = t
        self.L, self.R, self.B = Anim(t, REST_L), Anim(t, REST_R), Anim(t, BODY_HOME)
        self.P: Anim | None = None
        self.layer_t: float | None = None  # time the new layer appears
        self._plan_info: dict = {}
        self.history: list[dict] = []  # ground truth of completed cycles (used by tests / debugging)

    # ---- VideoSource API
    def open(self) -> bool:
        LINE_FLOW.register(self.line_id, self.sequence)
        self.opened = True
        return True

    def close(self) -> None:
        if self.opened:
            LINE_FLOW.unregister(self.line_id, self.sequence)
        self.opened = False

    def read(self) -> tuple[bool, np.ndarray | None]:
        now = time.time()
        with self._lock:
            self._step(now)
            frame = self._render(now)
        return True, frame

    def reference_frame(self) -> np.ndarray:
        return self._bg.copy()

    def ground_truth(self) -> dict | None:
        with self._lock:
            return self._gt

    # ---- state machine
    def _step(self, now: float) -> None:
        if self.state == "wait_part":
            if now >= self.state_until and LINE_FLOW.try_take(self.line_id, self.sequence):
                self._plan_cycle(now)
                self.state = "working"
            elif now >= self.state_until:
                self.state_until = now + 0.3
        elif self.state == "working" and now >= self.state_until:
            self.state = "done"
        elif self.state == "done":
            if LINE_FLOW.try_reserve_out(self.line_id, self.sequence):
                assert self.P is not None
                self.P.hold(now)
                self.P.to(now + 1.3, (1.12, PART_Y))
                self.state, self.state_until = "part_out", now + 1.3
        elif self.state == "part_out" and now >= self.state_until:
            LINE_FLOW.push(self.line_id, self.sequence)
            self.history.append({**self._plan_info, "t_out": now})
            del self.history[:-200]
            self.P, self.layer_t = None, None
            self.state = "wait_part"
            self.state_until = now + self.rng.uniform(0.3, 1.0)
            # occasional micro-stoppage (material shortage / talk / break)
            if self.rng.random() < 0.015:
                self.state_until = now + self.rng.uniform(25, 70)

    def _plan_cycle(self, t0: float) -> None:
        rng, p = self.rng, self.p
        L, R, B = Anim(t0, self.L.at(t0)), Anim(t0, self.R.at(t0)), Anim(t0, self.B.at(t0))
        P = Anim(t0, (-0.1, PART_Y))
        c = t0
        P.to(c + 1.3, (0.5, PART_Y))
        c += 1.3
        L.hold(c), R.hold(c), B.hold(c)
        L.to(c + 0.5, FIX_L), R.to(c + 0.5, FIX_R)
        c += 0.5

        # The standard method (expected picks from the near bins + assembly) takes target * speed seconds.
        # Long reaches to the far rack, walking and extra picks come ON TOP of it - that is the motion waste.
        standard = p.target_cycle_sec * p.speed_factor * rng.lognormvariate(0, 0.07)
        if rng.random() < 0.03:  # fumbling / small rework (a few seconds, never minutes)
            standard += min(rng.expovariate(1 / 5), 12.0)
        exp_picks = max(1, p.expected_picks)
        picks = exp_picks + (1 if rng.random() < p.extra_pick_prob else 0)
        bins = []
        for i in range(picks):
            if rng.random() < p.far_reach_prob:
                bins.append(BINS[2])
            else:
                bins.append(BINS[i % 2])
        walk_after = rng.randrange(picks) if rng.random() < p.walk_prob else -1
        self._plan_info = {"t_in": t0, "picks": picks, "far": sum(1 for b in bins if b["far"]), "walk": walk_after >= 0}

        near_trip = 2 * (_d(FIX_L, BINS[0]["center"]) / HAND_SPEED + 0.15) + 0.35
        assemble_each = max(1.2, (standard - 1.3 - 0.5 - 0.5 - exp_picks * near_trip) / exp_picks)

        for i, b in enumerate(bins):
            left = b["center"][0] < 0.5
            hand, fix = (L, FIX_L) if left else (R, FIX_R)
            other = R if left else L
            dur = _d(hand.last, b["center"]) / HAND_SPEED + 0.15
            if b["far"]:  # lean towards the far rack
                B.hold(c)
                B.to(c + dur, (0.4, 0.93))
            hand.to(c + dur, b["center"])
            other.hold(c + dur)
            c += dur
            hand.hold(c + 0.35)
            c += 0.35
            dur = _d(b["center"], fix) / HAND_SPEED + 0.15
            hand.to(c + dur, fix)
            if b["far"]:
                B.hold(c)
                B.to(c + dur, BODY_HOME)
            c += dur
            if i == 0:
                self.layer_t = c + assemble_each * 0.5
            end = c + (assemble_each if i < exp_picks else 1.0)  # an extra pick is just re-handling
            while c < end - 0.05:
                step = min(0.4, end - c)
                L.to(c + step, (FIX_L[0] + rng.uniform(-0.018, 0.018), FIX_L[1] + rng.uniform(-0.02, 0.02)))
                R.to(c + step, (FIX_R[0] + rng.uniform(-0.018, 0.018), FIX_R[1] + rng.uniform(-0.02, 0.02)))
                c += step
            if i == walk_after:  # operator walks away (fetch material / tool / ask supervisor)
                away = (1.16, BODY_HOME[1])
                B.hold(c), L.hold(c), R.hold(c)
                B.to(c + 2.6, away)
                L.to(c + 2.6, (away[0] - 0.08, 0.88))
                R.to(c + 2.6, (away[0] + 0.08, 0.88))
                c += 2.6 + rng.uniform(1.0, 3.0)
                B.hold(c), L.hold(c), R.hold(c)
                B.to(c + 2.6, BODY_HOME)
                L.to(c + 2.6, FIX_L)
                R.to(c + 2.6, FIX_R)
                c += 2.6
        L.to(c + 0.5, REST_L), R.to(c + 0.5, REST_R), B.hold(c + 0.5)
        c += 0.5
        self.L, self.R, self.B, self.P = L, R, B, P
        self.state_until = c

    # ---- rendering
    def _px(self, p: tuple[float, float]) -> tuple[int, int]:
        return int(p[0] * W), int(p[1] * H)

    def _render_background(self) -> np.ndarray:
        img = np.full((H, W, 3), (38, 40, 44), np.uint8)
        # floor texture
        rng = np.random.default_rng(7)
        img = cv2.add(img, rng.integers(0, 8, (H, W, 3), dtype=np.uint8))
        # bench
        cv2.rectangle(img, self._px((0.12, 0.3)), self._px((0.88, 1.0)), (72, 82, 92), -1)
        cv2.rectangle(img, self._px((0.12, 0.3)), self._px((0.88, 1.0)), (95, 105, 115), 2)
        # conveyors
        y1, y2 = CONVEYOR_Y
        for x1, x2 in ((0.0, 0.41), (0.59, 1.0)):
            cv2.rectangle(img, self._px((x1, y1)), self._px((x2, y2)), (55, 55, 58), -1)
            for k in np.arange(x1, x2, 0.025):
                cv2.line(img, self._px((k, y1)), self._px((k, y2)), (70, 70, 74), 1)
        # fixture
        cv2.rectangle(img, self._px(FIXTURE[:2]), self._px(FIXTURE[2:]), (40, 44, 48), -1)
        cv2.rectangle(img, self._px(FIXTURE[:2]), self._px(FIXTURE[2:]), (0, 170, 255), 1)
        # bins / far rack
        for b in BINS:
            cx, cy = b["center"]
            hx, hy = 0.045, 0.05
            cv2.rectangle(img, self._px((cx - hx, cy - hy)), self._px((cx + hx, cy + hy)), b["color"], -1)
            cv2.rectangle(img, self._px((cx - hx, cy - hy)), self._px((cx + hx, cy + hy)), (20, 20, 20), 1)
            for k in range(3):
                cv2.circle(img, self._px((cx - 0.02 + k * 0.02, cy)), 3, (230, 230, 230), -1)
        label = f"SIM CAM  |  Step {self.sequence}: {self.station_name}"
        cv2.putText(img, label, (10, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
        if self.parts:
            cv2.putText(img, "Adds: " + ", ".join(self.parts)[:60], (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 200, 150), 1, cv2.LINE_AA)
        return img

    def _draw_part(self, img: np.ndarray, center: tuple[float, float], layers: int) -> None:
        cx, cy = center
        hx, hy = PART_HALF
        cv2.rectangle(img, self._px((cx - hx, cy - hy)), self._px((cx + hx, cy + hy)), (150, 150, 155), -1)
        cv2.rectangle(img, self._px((cx - hx, cy - hy)), self._px((cx + hx, cy + hy)), (230, 230, 235), 1)
        for i in range(min(layers, len(LAYER_COLORS))):
            s = 0.85 - i * 0.11
            if s <= 0.1:
                break
            cv2.rectangle(img, self._px((cx - hx * s, cy - hy * s)), self._px((cx + hx * s, cy + hy * s)), LAYER_COLORS[i], -1 if i % 2 == 0 else 2)

    def _render(self, now: float) -> np.ndarray:
        img = self._bg.copy()
        # queue of parts waiting on the input conveyor (WIP from upstream)
        q = min(3, LINE_FLOW.queue_before(self.line_id, self.sequence))
        for k in range(q):
            self._draw_part(img, (0.31 - k * 0.12, PART_Y), self.sequence - 1)
        # current part
        if self.P is not None:
            pos = self.P.at(now)
            layers = self.sequence if (self.layer_t is not None and now >= self.layer_t) else self.sequence - 1
            if -0.2 < pos[0] < 1.2:
                self._draw_part(img, pos, layers)
        # operator (top-down)
        b, l, r = self.B.at(now), self.L.at(now), self.R.at(now)
        sw = SHOULDER_W / 2
        ls, rs = (b[0] - sw, b[1]), (b[0] + sw, b[1])
        shirt, skin = (120, 70, 30), (120, 160, 215)
        for s, h in ((ls, l), (rs, r)):
            cv2.line(img, self._px(s), self._px(h), shirt, 14, cv2.LINE_AA)
        cv2.ellipse(img, self._px(b), (int(sw * W) + 6, 26), 0, 180, 360, shirt, -1, cv2.LINE_AA)
        cv2.circle(img, self._px((b[0], b[1] - 0.005)), 17, (30, 30, 35), -1, cv2.LINE_AA)
        for h in (l, r):
            cv2.circle(img, self._px(h), 9, skin, -1, cv2.LINE_AA)
        self._frame_i = (self._frame_i + 1) % 4
        img = cv2.add(img, self._noise[self._frame_i])
        present = -0.02 <= b[0] <= 1.02
        self._gt = {
            "body": b if present else None,
            "wrists": [l if present else (None, None), r if present else (None, None)],
            "shoulder_w": SHOULDER_W,
        }
        return img
