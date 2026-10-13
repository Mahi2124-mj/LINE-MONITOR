"""Cycle detection from operator visits (part zone, no empty reference, pose tracker):
one cycle per visit to the fixture, extra short visits merged, line stops not counted as cycles."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.schemas import CameraConfig  # noqa: E402
from app.vision.analyzers import CycleTimeAnalyzer, FrameContext  # noqa: E402
from app.vision.trackers import Person  # noqa: E402
from app.vision.worker import CameraContext, StationMeta  # noqa: E402

W, H = 640, 360
FIXTURE = (100, 200)  # pixel inside the part zone
AWAY = (500, 200)


class _Tracker:
    name = "pose"


class _Worker:
    def __init__(self, seed: list[float]) -> None:
        self.seed = seed
        self.cycle_memory: dict[int, dict] = {}
        zone = {"id": "z1", "type": "part_zone", "name": "Fixture", "station_id": 1,
                "points": [[0.05, 0.4], [0.3, 0.4], [0.3, 0.8], [0.05, 0.8]]}
        self.info = {"id": 1, "line_id": 1, "station_id": 1, "zones": [zone], "name": "cam"}
        self.config = CameraConfig(cycle_method="part_presence", process_fps=3)
        self.stations = {1: StationMeta(id=1, line_id=1, name="s", sequence=1, target_cycle_sec=15.5, expected_picks=2)}
        self.tracker = _Tracker()
        self.cycle_start: dict[int, float] = {}
        self.cycles = []

    def recent_cycles(self, sid):
        return list(self.seed)

    def reset_station(self, sid, t):
        pass

    def complete_cycle(self, d):
        self.cycles.append(d)


def run(seed: list[float], extra_every: int, extra_from: int) -> None:
    # visits (start, duration): every 25 s; a 4 s extra visit 12 s into some cycles; a 5 min stop after cycle 8
    visits, t = [], 10.0
    for i in range(16):
        visits.append((t, 8.0))
        if i >= extra_from and i % extra_every == extra_from % extra_every:
            visits.append((t + 12.0, 4.0))
        t += 25.0 + (2.0 if i % 2 else -2.0)
        if i == 8:
            t += 300.0
    end = t + 30
    wk = _Worker(seed)
    an = CycleTimeAnalyzer(CameraContext(wk, W, H))
    step, now = 1 / 3, 0.0
    while now < end:
        at = any(s <= now < s + d for s, d in visits)
        p = Person(body=(FIXTURE if at else AWAY), wrists=[FIXTURE if at else AWAY, None])
        an.process(FrameContext(t=now, dt=step, frame=None, gray=None, fg_mask=lambda: None, persons=[p]))
        now += step
    ct = [round(c.cycle_sec, 1) for c in wk.cycles]
    print("cycles:", ct)
    assert len(ct) == 14, ct  # 16 visits -> 15 intervals, minus the one spanning the stop
    assert all(20 <= c <= 30 for c in ct), ct
    assert all(c.processing_sec <= 13 for c in wk.cycles)
    assert len(wk.cycle_memory[1]["recent"]) == 10 and 23 <= sorted(wk.cycle_memory[1]["periods"])[2] <= 27


def run_machine() -> None:
    """Operator never visible at the fixture (automatic machine): cycles from bursts of motion in the part zone."""
    wk = _Worker([])
    an = CycleTimeAnalyzer(CameraContext(wk, W, H))
    moving = np.zeros((H, W), np.uint8)
    moving[150:280, 40:190] = 255  # covers the part zone
    still = np.zeros((H, W), np.uint8)
    step, now = 1 / 3, 0.0
    while now < 300:
        on = (now % 11.2) < 4.0
        p = Person(body=AWAY, wrists=[AWAY, None])
        an.process(FrameContext(t=now, dt=step, frame=None, gray=None, fg_mask=lambda m=(moving if on else still): m, persons=[p]))
        now += step
    ct = [round(c.cycle_sec, 1) for c in wk.cycles]
    print("machine cycles:", ct)
    assert an.states[1].by_motion and len(ct) >= 20 and all(10.5 <= c <= 12 for c in ct[5:]), ct


def main() -> None:
    run([], extra_every=4, extra_from=3)  # cold start: the typical cycle is learned from the first cycles
    run([25.0] * 10, extra_every=3, extra_from=1)  # warm start from recent history
    run_machine()
    print("OK")


if __name__ == "__main__":
    main()
