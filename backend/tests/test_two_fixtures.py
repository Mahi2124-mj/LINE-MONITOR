"""A station with TWO part fixtures worked alternately: every unit leaving either fixture is one cycle,
cycle time = time between consecutive finished units of the station."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("LM_DATA_DIR", tempfile.mkdtemp(prefix="lm_fix2_"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.vision.worker import CameraWorker, LineMeta, StationMeta  # noqa: E402

W, H, FPS = 320, 180, 5
ZONE_A = [[0.1, 0.3], [0.4, 0.3], [0.4, 0.7], [0.1, 0.7]]
ZONE_B = [[0.6, 0.3], [0.9, 0.3], [0.9, 0.7], [0.6, 0.7]]
# (fixture, part arrives, part leaves) in seconds – two units in parallel, alternating
UNITS = [("A", 2, 22), ("B", 12, 32), ("A", 24, 44), ("B", 34, 54), ("A", 46, 66)]


def frame_at(t: float) -> np.ndarray:
    img = np.full((H, W, 3), 60, np.uint8)
    for fx, t_in, t_out in UNITS:
        if t_in <= t < t_out:
            zx = ZONE_A if fx == "A" else ZONE_B
            x1, y1 = int((zx[0][0] + 0.05) * W), int((zx[0][1] + 0.08) * H)
            x2, y2 = int((zx[2][0] - 0.05) * W), int((zx[2][1] - 0.08) * H)
            cv2.rectangle(img, (x1, y1), (x2, y2), (230, 230, 230), -1)
    return img


def test_two_fixtures():
    meta = StationMeta(id=1, line_id=1, name="Two fixture step", sequence=1, target_cycle_sec=12, expected_picks=2)
    info = {"id": 9997, "line_id": 1, "station_id": 1, "name": "cam", "source_type": "file", "source": "none",
            "zones": [{"id": "a", "name": "Fixture A", "type": "part_zone", "station_id": None, "points": ZONE_A},
                      {"id": "b", "name": "Fixture B", "type": "part_zone", "station_id": None, "points": ZONE_B}],
            "config": {"cycle_method": "part_presence", "presence_debounce_sec": 0.8, "min_cycle_sec": 3, "analyzers": ["cycle_time"]}}
    w = CameraWorker(info, {1: meta}, LineMeta(1, "L", 12))
    done: list = []
    w.complete_cycle = lambda d: done.append(d)  # type: ignore[method-assign]
    w._setup_pipeline(W, H)
    assert w.ctx is not None
    w.ctx.reference = cv2.GaussianBlur(cv2.cvtColor(frame_at(-1), cv2.COLOR_BGR2GRAY), (5, 5), 0)  # empty fixtures
    for i in range(int(75 * FPS)):
        t = 1000.0 + i / FPS
        w._process(frame_at(i / FPS), t, 1 / FPS)

    got = [(round(d.ended_ts - 1000, 1), round(d.cycle_sec, 1), round(d.processing_sec, 1)) for d in done]
    print("cycles (end, cycle_sec, processing):", got)
    assert len(done) == len(UNITS), got
    ends = sorted(t_out for _, _, t_out in UNITS)
    expected_cycle = [ends[0] - UNITS[0][1]] + [b - a for a, b in zip(ends, ends[1:])]
    for d, end, exp in zip(done, ends, expected_cycle):
        assert abs(d.ended_ts - 1000 - end) <= 0.5, (d.ended_ts - 1000, end)
        assert abs(d.cycle_sec - exp) <= 0.5, (d.cycle_sec, exp)
        assert abs(d.processing_sec - 20) <= 0.6, d.processing_sec


if __name__ == "__main__":
    test_two_fixtures()
    print("OK")
