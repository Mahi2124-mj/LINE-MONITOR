"""Runs the real vision pipeline on the synthetic camera with a fast-forwarded clock and compares
detected cycles with the simulator's ground truth.

    .venv\\Scripts\\python -m pytest tests -q        (or)   .venv\\Scripts\\python tests\\test_pipeline_sim.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LM_DATA_DIR", tempfile.mkdtemp(prefix="lm_test_"))

from app.vision import synthetic  # noqa: E402
from app.vision.trackers import SimulatedTracker  # noqa: E402
from app.vision.worker import CameraWorker, LineMeta, StationMeta  # noqa: E402

FPS = 6.0


def run_station(target: float, picks: int, sim: dict, minutes: float, line_id: int = 900, seq: int = 1) -> tuple[list, list]:
    clock = [1_000_000.0]
    synthetic.time = types.SimpleNamespace(time=lambda: clock[0])  # fake clock for the simulator

    meta = StationMeta(id=1, line_id=line_id, name="Test step", sequence=seq, target_cycle_sec=target, expected_picks=picks)
    info = {"id": 9999, "line_id": line_id, "station_id": 1, "name": "test cam", "source_type": "simulated", "source": "sim",
            "zones": synthetic.demo_zones(),
            "config": {"cycle_method": "part_presence", "tracker": "simulated", "process_fps": FPS, "presence_debounce_sec": 0.8,
                       "analyzers": ["cycle_time", "movement"], "sim": sim}}
    w = CameraWorker(info, {1: meta}, LineMeta(line_id, "Test line", target))
    detected: list = []

    def complete(draft):
        for a in w.analyzers:
            a.contribute(draft)
        detected.append(draft)

    w.complete_cycle = complete  # type: ignore[method-assign]
    assert w._open_source()
    assert isinstance(w.tracker, SimulatedTracker)
    src = w.source
    w._setup_pipeline(synthetic.W, synthetic.H)
    steps = int(minutes * 60 * FPS)
    for _ in range(steps):
        clock[0] += 1 / FPS
        ok, frame = src.read()
        assert ok
        w._process(frame, clock[0], 1 / FPS)
    src.close()
    return detected, src.history


def _report(detected: list, truth: list) -> None:
    for d in detected[:8]:
        print(f"  det cyc {d.cycle_sec:5.1f} proc {d.processing_sec:5.1f} work {d.work_sec:5.1f} motion {d.motion_waste_sec:4.1f} "
              f"wait {d.wait_sec:4.1f} reach {d.reach_count} picks {d.pick_count} walk {d.walk_m:.1f}m hand {d.hand_travel_m:.1f}m")
    for t in truth[:8]:
        print(f"  gt  dur {t['t_out'] - t['t_in']:5.1f} picks {t['picks']} far {t['far']} walk {t['walk']}")


def test_cycles_match_ground_truth():
    sim = {"speed_factor": 1.0, "far_reach_prob": 0.3, "walk_prob": 0.2, "extra_pick_prob": 0.2}
    detected, truth = run_station(target=30, picks=2, sim=sim, minutes=20)
    _report(detected, truth)
    # every completed unit is detected exactly once (the last one may still be in progress)
    assert abs(len(detected) - len(truth)) <= 1, (len(detected), len(truth))
    n = min(len(detected), len(truth))
    assert n >= 20
    # skip the first cycle (no previous part-out yet)
    reach_err = sum(abs(d.reach_count - t["far"]) for d, t in zip(detected[1:n], truth[1:n]))
    pick_err = sum(abs(d.pick_count - t["picks"]) for d, t in zip(detected[1:n], truth[1:n]))
    walk_hits = sum(1 for d, t in zip(detected[1:n], truth[1:n]) if (d.walk_m > 1.5) == t["walk"])
    print(f"cycles det={len(detected)} gt={len(truth)} reach_err={reach_err} pick_err={pick_err} walk_ok={walk_hits}/{n - 1}")
    assert reach_err <= 0.1 * n
    assert pick_err <= 0.1 * n
    assert walk_hits >= 0.9 * (n - 1)
    # time split adds up to the cycle time
    for d in detected:
        assert abs(d.work_sec + d.motion_waste_sec + d.wait_sec - d.cycle_sec) < 0.05
    # standard work (no waste) ~ target; waste cycles take longer and show motion waste
    clean = [d for d, t in zip(detected[1:n], truth[1:n]) if t["far"] == 0 and not t["walk"] and t["picks"] == 2]
    wasteful = [d for d, t in zip(detected[1:n], truth[1:n]) if t["far"] > 0 or t["walk"]]
    if clean and wasteful:
        avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
        print(f"clean content {avg([d.work_sec + d.motion_waste_sec for d in clean]):.1f}s motion {avg([d.motion_waste_sec for d in clean]):.1f}s | "
              f"wasteful motion {avg([d.motion_waste_sec for d in wasteful]):.1f}s")
        assert avg([d.motion_waste_sec for d in wasteful]) > avg([d.motion_waste_sec for d in clean]) + 1.0


if __name__ == "__main__":
    test_cycles_match_ground_truth()
    print("OK")
