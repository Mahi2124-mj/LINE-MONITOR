"""Real-camera path: a recorded (compressed) video, empty-reference part detection and the motion tracker
(no ground-truth hands). Checks that cycle counting still matches the simulator's ground truth."""
from __future__ import annotations

import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = tempfile.mkdtemp(prefix="lm_video_")
os.environ.setdefault("LM_DATA_DIR", TMP)

import cv2  # noqa: E402

from app.vision import synthetic  # noqa: E402
from app.vision.synthetic import SimParams, SyntheticSource  # noqa: E402
from app.vision.worker import CameraWorker, LineMeta, StationMeta  # noqa: E402

VIDEO_FPS = 10
MINUTES = 8


def _record(path: str) -> list[dict]:
    clock = [2_000_000.0]
    synthetic.time = types.SimpleNamespace(time=lambda: clock[0])
    src = SyntheticSource(901, 1, "Video step", ["Part"], SimParams(25, 2, 1.0, 0.2, 0.1, 0.1), seed=90101)  # repeatable
    src.open()
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), VIDEO_FPS, (synthetic.W, synthetic.H))
    for _ in range(MINUTES * 60 * VIDEO_FPS):
        clock[0] += 1 / VIDEO_FPS
        _, frame = src.read()
        out.write(frame)
    out.release()
    src.close()
    return [{**h, "t_in": h["t_in"] - 2_000_000.0, "t_out": h["t_out"] - 2_000_000.0} for h in src.history]


def test_video_motion_tracker():
    path = os.path.join(TMP, "station.mp4")
    truth = _record(path)
    meta = StationMeta(id=1, line_id=901, name="Video step", sequence=1, target_cycle_sec=25, expected_picks=2)
    info = {"id": 9998, "line_id": 901, "station_id": 1, "name": "video cam", "source_type": "file", "source": path,
            "zones": synthetic.demo_zones(),
            "config": {"cycle_method": "part_presence", "tracker": "motion", "process_fps": 5, "presence_debounce_sec": 0.8,
                       "analyzers": ["cycle_time", "movement", "heatmap"]}}
    w = CameraWorker(info, {1: meta}, LineMeta(901, "Video line", 25))
    detected: list = []

    def complete(d):
        for a in w.analyzers:
            a.contribute(d)
        detected.append(d)

    w.complete_cycle = complete  # type: ignore[method-assign]
    from app.vision.trackers import MotionTracker

    w.tracker = MotionTracker()
    cap = cv2.VideoCapture(path)
    ok, first = cap.read()
    assert ok
    w.latest_frame = first
    w._setup_pipeline(first.shape[1], first.shape[0])
    assert w.request_reference()  # "Capture empty reference" with the fixture empty
    w._load_reference(first.shape[1], first.shape[0])
    assert w.ctx is not None and w.ctx.reference is not None
    step = VIDEO_FPS // 5
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        i += 1
        if i % step:
            continue
        w._process(frame, 1000.0 + i / VIDEO_FPS, step / VIDEO_FPS)
    cap.release()
    print(f"cycles det={len(detected)} gt={len(truth)}")
    for d, t in list(zip(detected, truth))[:6]:
        print(f"  det {d.cycle_sec:5.1f}s proc {d.processing_sec:5.1f} work {d.work_sec:5.1f} motion {d.motion_waste_sec:4.1f} wait {d.wait_sec:4.1f}"
              f" reach {d.reach_count} picks {d.pick_count} | gt {t['t_out'] - t['t_in']:5.1f}s far {t['far']} picks {t['picks']} walk {t['walk']}")
    pairs = list(zip(detected[1:], truth[1:]))
    reach_err = sum(abs(d.reach_count - t["far"]) for d, t in pairs)
    print(f"motion-proxy reach error: {reach_err} over {len(pairs)} cycles")
    assert reach_err <= 0.25 * len(pairs)  # walking can't be separated from reaching without pose
    assert all(abs(d.pick_count - t["picks"]) <= 1 for d, t in pairs)
    assert abs(len(detected) - len(truth)) <= 1
    # cycle times (part-out to part-out) agree with ground truth within a second
    gt_cycles = [b["t_out"] - a["t_out"] for a, b in zip(truth, truth[1:])]
    det_cycles = [d.cycle_sec for d in detected[1:]]
    n = min(len(gt_cycles), len(det_cycles))
    err = sorted(abs(a - b) for a, b in zip(gt_cycles[:n], det_cycles[:n]))
    print(f"median abs error {err[len(err) // 2]:.2f}s, max {err[-1]:.2f}s")
    assert err[len(err) // 2] < 0.6
    assert err[-1] < 2.5


if __name__ == "__main__":
    test_video_motion_tracker()
    print("OK")
