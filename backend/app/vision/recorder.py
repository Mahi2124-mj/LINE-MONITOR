"""Continuous recording for cycle / element analysis.

Every processed frame of a camera with `config.record = true` is written to 1-minute segments of
concatenated JPEGs (cheap to encode) plus a JSON-lines file with the pose of every person in that frame:

    data/recordings/cam_<id>/<YYYYmmdd_HHMMSS>.mjpg   JPEG frames back to back (processing resolution)
    data/recordings/cam_<id>/<YYYYmmdd_HHMMSS>.jsonl  {"t": unix_ts, "i": frame_index, "o": byte offset, "n": byte length, "op": operator_index, "p": [person...]}

person = {"w": [[lx,ly],[rx,ry]] (wrists, normalized 0..1, null if not seen), "c": [bx,by] body,
          "k": [[x,y,conf] x17] (pose keypoints, normalized) or null, "b": [x1,y1,x2,y2] or null}
Browser-playable WebM clips of single cycles are cut from these segments on demand (services/clips.py).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from ..config import settings

if TYPE_CHECKING:
    from .trackers import Person

log = logging.getLogger(__name__)

SEGMENT_SEC = 60.0


def camera_dir(camera_id: int) -> Path:
    return settings.recordings_dir / f"cam_{camera_id}"


def segment_start(path: Path) -> float | None:
    try:
        return datetime.strptime(path.stem, "%Y%m%d_%H%M%S").timestamp()
    except ValueError:
        return None


def list_segments(camera_id: int, t0: float | None = None, t1: float | None = None) -> list[tuple[float, Path]]:
    """(start_ts, jsonl path) of segments overlapping [t0, t1], oldest first."""
    d = camera_dir(camera_id)
    if not d.exists():
        return []
    out = []
    for p in d.glob("*.jsonl"):
        s = segment_start(p)
        if s is None:
            continue
        if t1 is not None and s > t1:
            continue
        if t0 is not None and s + SEGMENT_SEC * 2 < t0:
            continue
        out.append((s, p))
    out.sort()
    return out


def _r(v: float) -> float:
    return round(float(v), 4)


class Recorder:
    def __init__(self, camera_id: int, fps: float) -> None:
        self.camera_id = camera_id
        self.fps = max(1.0, fps)
        self.dir = camera_dir(camera_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.writer = None  # binary file of concatenated JPEGs
        self.meta = None
        self.seg_start = 0.0
        self.size: tuple[int, int] | None = None
        self.idx = 0
        self.last_cleanup = 0.0

    def _rotate(self, t: float, w: int, h: int) -> None:
        self.close()
        name = datetime.fromtimestamp(t).strftime("%Y%m%d_%H%M%S")
        # Frames are stored as plain concatenated JPEGs (offset/length in the json lines), NOT via cv2.VideoWriter:
        # OpenCV's FFmpeg layer holds a global lock while any camera is (re)connecting, which blocked the
        # recording for 10-60 s every minute on a flaky camera network.
        self.writer = open(self.dir / f"{name}.mjpg", "wb")
        self.meta = open(self.dir / f"{name}.jsonl", "w", encoding="utf-8", buffering=1)
        self.seg_start, self.size, self.idx = t, (w, h), 0
        if t - self.last_cleanup > 600:
            self.last_cleanup = t
            self.cleanup()

    def write(self, t: float, frame: np.ndarray, persons: list["Person"], operator: "Person | None") -> None:
        h, w = frame.shape[:2]
        if self.writer is None or t - self.seg_start >= SEGMENT_SEC or self.size != (w, h):
            self._rotate(t, w, h)
        assert self.writer is not None and self.meta is not None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return
        offset = self.writer.tell()
        self.writer.write(buf.tobytes())
        self.writer.flush()  # readers (clips) use the offsets from the json line right away
        people = []
        op_index = None
        for n, p in enumerate(persons):
            if p is operator:
                op_index = n
            item = {
                "w": [[_r(q[0] / w), _r(q[1] / h)] if q is not None else None for q in p.wrists[:2]],
                "c": [_r(p.body[0] / w), _r(p.body[1] / h)],
            }
            if p.keypoints is not None:
                item["k"] = [[_r(k[0] / w), _r(k[1] / h), round(float(k[2]), 2)] for k in p.keypoints]
            if p.bbox is not None:
                item["b"] = [_r(p.bbox[0] / w), _r(p.bbox[1] / h), _r(p.bbox[2] / w), _r(p.bbox[3] / h)]
            people.append(item)
        self.meta.write(json.dumps({"t": round(t, 3), "i": self.idx, "o": offset, "n": len(buf), "op": op_index, "p": people},
                                   separators=(",", ":")) + "\n")
        self.idx += 1

    def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            self.writer = None
        if self.meta is not None:
            self.meta.close()
            self.meta = None

    def cleanup(self) -> None:
        """Delete segments older than the retention period (clips of master cycles are kept elsewhere).
        Measured from the newest recording, and the segment being written is never touched."""
        limit = self.seg_start - settings.record_retention_hours * 3600
        for p in self.dir.glob("*.jsonl"):
            s = segment_start(p)
            if s is not None and s < limit and abs(s - self.seg_start) > 1:
                p.unlink(missing_ok=True)
                p.with_suffix(".avi").unlink(missing_ok=True)
                p.with_suffix(".mjpg").unlink(missing_ok=True)
