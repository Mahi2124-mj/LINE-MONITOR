"""Person / hand trackers. Every tracker returns a list of Person in processing-pixel coordinates.

- PoseTracker: YOLO pose (ultralytics) -> real wrist + shoulder keypoints. Best accuracy.
- MotionTracker: background subtraction blobs -> rough hand/body proxy when no pose model is available.
- SimulatedTracker: ground truth from the synthetic demo camera (exercises the same downstream analytics).
"""
from __future__ import annotations

import importlib.util
import logging
import queue
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from ..config import settings

if TYPE_CHECKING:
    from .analyzers import FrameContext

log = logging.getLogger(__name__)

# COCO keypoint indices
L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST, L_HIP, R_HIP = 5, 6, 9, 10, 11, 12
SKELETON = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]
KP_CONF = 0.35


@dataclass
class Person:
    body: tuple[float, float]  # body reference point (shoulder midpoint for pose)
    wrists: list[tuple[float, float] | None]  # [left, right]
    shoulder_px: float | None = None  # shoulder width in px -> metric scale
    bbox: tuple[float, float, float, float] | None = None
    keypoints: np.ndarray | None = None  # (17,3) for drawing
    conf: float = 1.0
    approx: bool = False  # motion-blob proxy: no real body position (no walking / away analysis)


# ------------------------------------------------------------------ pose
class PoseModel:
    """Single YOLO pose model shared by all camera workers.

    Workers submit frames to a queue; one inference thread runs them in batches (up to MAX_BATCH frames of
    different cameras at once), which gives ~1.7x more frames per second on CPU than one frame at a time."""

    MAX_BATCH = 8
    GATHER_SEC = 0.015  # wait this long for frames of other cameras to join a batch

    _instance: "PoseModel | None" = None
    _init_lock = threading.Lock()
    _failed = False

    def __init__(self, model: Any) -> None:
        self.model = model
        self.queue: "queue.Queue[tuple[np.ndarray, Future]]" = queue.Queue()
        threading.Thread(target=self._serve, daemon=True, name="pose-inference").start()

    def _serve(self) -> None:
        while True:
            batch = [self.queue.get()]
            deadline = time.time() + self.GATHER_SEC
            while len(batch) < self.MAX_BATCH:
                try:
                    batch.append(self.queue.get(timeout=max(0.0, deadline - time.time())))
                except queue.Empty:
                    break
            try:
                results = self.model.predict(
                    [f for f, _ in batch], imgsz=settings.pose_imgsz, conf=settings.pose_conf, device=settings.pose_device,
                    classes=[0], verbose=False,
                )
                for (_, fut), r in zip(batch, results):
                    fut.set_result(self._parse(r))
            except Exception as e:
                for _, fut in batch:
                    if not fut.done():
                        fut.set_exception(e)

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("ultralytics") is not None and settings.pose_model.exists() and not PoseModel._failed

    @classmethod
    def get(cls) -> "PoseModel | None":
        if cls._instance is not None:
            return cls._instance
        if not cls.available():
            return None
        with cls._init_lock:
            if cls._instance is None and not cls._failed:
                try:
                    from ultralytics import YOLO  # CPU thread limits are set in run.py (OMP_NUM_THREADS)

                    model = YOLO(str(settings.pose_model))
                    # warm-up so the first real frame is not slow
                    model.predict(np.zeros((360, 640, 3), np.uint8), imgsz=settings.pose_imgsz, device=settings.pose_device, verbose=False)
                    cls._instance = PoseModel(model)
                    log.info("Pose model loaded: %s on %s", settings.pose_model.name, settings.pose_device)
                except Exception as e:  # pragma: no cover - depends on local install
                    cls._failed = True
                    log.error("Could not load pose model (%s) - falling back to motion tracker", e)
        return cls._instance

    def infer(self, frame: np.ndarray) -> list[Person]:
        fut: Future = Future()
        self.queue.put((frame, fut))
        return fut.result(timeout=15)

    @staticmethod
    def _parse(r: Any) -> list[Person]:
        if r.keypoints is None or r.boxes is None or len(r.boxes) == 0:
            return []
        boxes = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        kps = r.keypoints.data.cpu().numpy()  # (N,17,3)
        people: list[Person] = []
        for box, conf, kp in zip(boxes, confs, kps):
            def pt(i: int) -> tuple[float, float] | None:
                return (float(kp[i, 0]), float(kp[i, 1])) if kp.shape[1] > 2 and kp[i, 2] >= KP_CONF else None

            ls, rs, lh, rh = pt(L_SHOULDER), pt(R_SHOULDER), pt(L_HIP), pt(R_HIP)
            if ls and rs:
                body = ((ls[0] + rs[0]) / 2, (ls[1] + rs[1]) / 2)
                shoulder = float(np.hypot(ls[0] - rs[0], ls[1] - rs[1]))
            elif lh and rh:
                body = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2)
                shoulder = None
            else:
                body = (float((box[0] + box[2]) / 2), float((box[1] + box[3]) / 2))
                shoulder = None
            people.append(
                Person(
                    body=body,
                    wrists=[pt(L_WRIST), pt(R_WRIST)],
                    shoulder_px=shoulder if shoulder and shoulder > 8 else None,
                    bbox=tuple(float(v) for v in box),  # type: ignore[arg-type]
                    keypoints=kp,
                    conf=float(conf),
                )
            )
        return people


class PoseTracker:
    name = "pose"

    def __init__(self, model: PoseModel) -> None:
        self.model = model

    def detect(self, fc: "FrameContext") -> list[Person]:
        return self.model.infer(fc.frame)


# ------------------------------------------------------------------ motion fallback
class MotionTracker:
    """Fallback without a pose model: the moving regions' extreme points (farthest from the operator's
    position) are used as hand proxies. Good for reaches / picks / idle; walking cannot be measured."""

    name = "motion"

    def __init__(self) -> None:
        self.min_area_frac = 0.0015
        self.anchor: tuple[float, float] | None = None  # operator position (set by the worker from the work area)

    def detect(self, fc: "FrameContext") -> list[Person]:
        h, w = fc.gray.shape[:2]
        anchor = self.anchor or (w / 2, h * 0.9)
        fg = fc.fg_mask()
        hands: list[tuple[float, float]] = []
        if fg is not None:
            cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            big = sorted((c for c in cnts if cv2.contourArea(c) >= self.min_area_frac * w * h), key=cv2.contourArea, reverse=True)[:2]
            for c in big:
                pts = c.reshape(-1, 2).astype(np.float32)
                d = np.hypot(pts[:, 0] - anchor[0], pts[:, 1] - anchor[1])
                x, y = pts[int(np.argmax(d))]
                hands.append((float(x), float(y)))
        hands.sort(key=lambda p: p[0])  # keep a stable left / right order
        wrists: list[tuple[float, float] | None] = [hands[0] if hands else None, hands[1] if len(hands) > 1 else None]
        # always report the operator: "no motion" means idle hands, not an empty station
        return [Person(body=anchor, wrists=wrists, conf=0.5, approx=True)]


# ------------------------------------------------------------------ simulated
class SimulatedTracker:
    name = "simulated"

    def __init__(self, source: Any) -> None:
        self.source = source

    def detect(self, fc: "FrameContext") -> list[Person]:
        gt = self.source.ground_truth()
        if not gt or gt.get("body") is None:
            return []
        h, w = fc.frame.shape[:2]
        bx, by = gt["body"]
        wrists = [(x * w, y * h) if (x is not None and 0 <= x <= 1 and 0 <= y <= 1) else None for x, y in gt["wrists"]]
        return [Person(body=(bx * w, by * h), wrists=wrists, shoulder_px=gt["shoulder_w"] * w, conf=1.0)]


def make_tracker(kind: str, source: Any) -> Any:
    if kind == "simulated" or (kind == "auto" and getattr(source, "is_synthetic", False)):
        if getattr(source, "is_synthetic", False):
            return SimulatedTracker(source)
        kind = "auto"
    if kind in ("pose", "auto"):
        model = PoseModel.get()
        if model is not None:
            return PoseTracker(model)
        if kind == "pose":
            log.warning("Pose tracker requested but unavailable - using motion tracker")
    return MotionTracker()
