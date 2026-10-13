"""Element breakup on the simulator: record ~25 min of a synthetic station (fast clock), learn the elements
automatically, analyse the cycles and compare with the simulator's ground truth."""
from __future__ import annotations

import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LM_DATA_DIR"] = tempfile.mkdtemp(prefix="lm_elem_")
os.environ["LM_RECORDINGS_DIR"] = os.path.join(os.environ["LM_DATA_DIR"], "recordings")

from app.services import elements as E  # noqa: E402
from app.vision import synthetic  # noqa: E402
from app.vision.worker import CameraWorker, LineMeta, StationMeta  # noqa: E402

FPS = 6.0
T0 = 1_700_000_000.0  # a real-looking unix time (segment file names use local time)


def record(minutes: float, sim: dict, seed: int = 5) -> list[dict]:
    clock = [T0]
    synthetic.time = types.SimpleNamespace(time=lambda: clock[0])
    meta = StationMeta(id=1, line_id=1, name="Rail assy", sequence=1, target_cycle_sec=20, expected_picks=2)
    info = {"id": 4242, "line_id": 1, "station_id": 1, "name": "cam", "source_type": "simulated", "source": "sim",
            "zones": synthetic.demo_zones(),
            "config": {"cycle_method": "part_presence", "tracker": "simulated", "process_fps": FPS, "record": True,
                       "analyzers": ["cycle_time"], "sim": sim}}
    w = CameraWorker(info, {1: meta}, LineMeta(1, "L", 20))
    w.complete_cycle = lambda d: None  # type: ignore[method-assign]
    assert w._open_source()
    w.source.rng.seed(seed)
    w._setup_pipeline(synthetic.W, synthetic.H)
    for _ in range(int(minutes * 60 * FPS)):
        clock[0] += 1 / FPS
        ok, frame = w.source.read()
        w._process(frame, clock[0], 1 / FPS)
    w.recorder.close()
    w.source.close()
    return w.source.history


def test_element_breakup():
    sim = {"speed_factor": 1.0, "far_reach_prob": 0.15, "walk_prob": 0.1, "extra_pick_prob": 0.1}
    truth = record(25, sim)
    t_end = T0 + 25 * 60
    model = E.learn(4242, T0, t_end, takt_hint=20, zones=synthetic.demo_zones())
    assert model is not None, "no model learned"
    print(f"learned {len(model['elements'])} elements from {model['cycles_learned']} cycles; cycle starts with element {model['cycle_start']}")
    for e in model["elements"]:
        print(f"  {e['id']:2d} {e['name']:<16} {e['desc']}")
    std = model["standard"]
    print("standard:", std["seq"], std["durations"], "total", std["total"], "support", std["support"])

    cycles = E.analyze(4242, model, T0, t_end)
    gt_dur = sorted(h["t_out"] - h["t_in"] for h in truth)
    print(f"cycles found {len(cycles)} vs truth {len(truth)}; median cycle {sorted(c['cycle_sec'] for c in cycles)[len(cycles)//2]:.1f}s")
    assert abs(len(cycles) - len(truth)) <= max(3, 0.1 * len(truth)), (len(cycles), len(truth))

    # every truth cycle with a far reach / walk / extra pick should show an issue around that time
    def cycle_at(t: float):
        return next((c for c in cycles if c["start_ts"] - 2 <= t <= c["end_ts"] + 2), None)

    hits = misses = clean_flagged = clean = 0
    for h in truth:
        c = cycle_at((h["t_in"] + h["t_out"]) / 2)
        if c is None:
            continue
        flagged = any(i["severity"] != "info" for i in c["issues"])
        if h["far"] or h["walk"] or h["picks"] > 2:
            hits += flagged
            misses += not flagged
        else:
            clean += 1
            clean_flagged += flagged
    print(f"deviating cycles flagged: {hits}/{hits + misses}; clean cycles flagged: {clean_flagged}/{clean}")
    for c in [c for c in cycles if c["issues"]][:4]:
        print("  cycle", round(c["cycle_sec"], 1), "->", "; ".join(i["text"] for i in c["issues"]))
    for c in cycles[:2]:
        print("  breakup:", " | ".join(f"{e['name']} {e['start']:.1f}+{e['dur']:.1f}s" for e in c["elements"]))
    assert hits >= 0.7 * (hits + misses)
    assert clean_flagged <= 0.35 * max(1, clean)


if __name__ == "__main__":
    test_element_breakup()
    print("OK")
