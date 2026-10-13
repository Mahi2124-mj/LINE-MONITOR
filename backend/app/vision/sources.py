"""Video sources: RTSP / HTTP IP cameras, USB webcams, video files and the synthetic demo camera."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any

import cv2
import numpy as np

from .synthetic import SimParams, SyntheticSource

log = logging.getLogger(__name__)

# TCP is far more reliable than UDP for RTSP over factory Wi-Fi / busy switches.
# 2 decoder threads per camera are plenty for sub streams (default = one per CPU core, per camera).
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000|threads;2")
cv2.setNumThreads(2)


# Main stream -> sub stream of common IP camera brands. Analysis runs at 640 px, so the small sub stream
# saves a lot of CPU and memory compared to decoding 4–8 MP main streams for many cameras.
SUBSTREAM_RULES = [
    ("/h264/ch1/main/av_stream", "/h264/ch1/sub/av_stream"),  # Hikvision (older) / many OEMs
    ("/Streaming/Channels/101", "/Streaming/Channels/102"),  # Hikvision, Prama
    ("/Streaming/channels/101", "/Streaming/channels/102"),
    ("subtype=0", "subtype=1"),  # Dahua, CP Plus
    ("/ch01/0", "/ch01/1"),
]


def substream_url(url: str) -> str | None:
    for main, sub in SUBSTREAM_RULES:
        if main in url:
            return url.replace(main, sub)
    return None


def _mask(url: str) -> str:
    import re

    return re.sub(r"(://[^:/@]+):[^@/]*@", r"\1:****@", str(url))


class ThreadedCapture:
    """A background thread keeps grabbing (decoding) the stream so the newest frame is always ready,
    but the expensive conversion to an image (retrieve) only happens when the worker asks for a frame."""

    is_synthetic = False
    STALE_SEC = 10.0
    OPEN_TIMEOUT_MS = 8000

    def __init__(self, src: Any, api: int, prefer_substream: bool = False) -> None:
        self.src, self.api = src, api
        sub = substream_url(src) if prefer_substream and isinstance(src, str) else None
        self.candidates: list[Any] = [sub, src] if sub else [src]
        self.cap: cv2.VideoCapture | None = None
        self.frame: np.ndarray | None = None
        self.has_frame = False
        self.grab_ts = 0.0
        self.lock = threading.Lock()
        self.running = False
        self.thread: threading.Thread | None = None
        self.active: Any = None
        self.opened_at = 0.0
        # sub streams are often 704x576 (4:3) for a 16:9 camera: frames are resized back to the main aspect
        self.target_aspect: float | None = None

    def _open_one(self, src: Any) -> cv2.VideoCapture | None:
        if self.api == cv2.CAP_FFMPEG:
            params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, self.OPEN_TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, self.OPEN_TIMEOUT_MS]
            try:
                cap = cv2.VideoCapture(src, self.api, params)
            except TypeError:
                cap = cv2.VideoCapture(src, self.api)
        else:
            cap = cv2.VideoCapture(src, self.api)
        if cap.isOpened() and cap.grab():
            return cap
        cap.release()
        return None

    SUB_RETRY_SEC = 300.0  # when stuck on the heavy main stream, try the sub stream again after this
    # sub-stream sizes that are anamorphic (PAL/NTSC D1 / CIF): the camera picture itself is 16:9
    ANAMORPHIC = {(704, 576), (720, 576), (352, 288), (704, 480), (720, 480), (352, 240)}

    def open(self) -> bool:
        for src in self.candidates:
            cap = self._open_one(src)
            if cap is not None:
                self.cap, self.active = cap, src
                self.grab_ts = self.opened_at = time.time()
                if src != self.src:
                    ok, f = cap.retrieve()
                    if ok and f is not None and (f.shape[1], f.shape[0]) in self.ANAMORPHIC:
                        self.target_aspect = 16 / 9  # no extra connection to the main stream just to learn its shape
                if len(self.candidates) > 1:
                    log.info("camera stream %s (%s)", _mask(src), "sub stream" if src != self.src else "main stream - sub stream not available")
                break
        if self.cap is None:
            return False
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True, name="grab")
        self.thread.start()
        return True

    @property
    def wants_reopen(self) -> bool:
        """On the main stream although a sub stream exists: reconnect now and then to get back to the light one."""
        return len(self.candidates) > 1 and self.active == self.src and time.time() - self.opened_at > self.SUB_RETRY_SEC

    RETRIEVE_EVERY = 0.1  # convert at most 10 frames/s to images; all others are only decoded

    def _loop(self) -> None:
        # grab() blocks until the next frame arrives from the network, so it must not hold a lock that
        # read() needs (that starved the workers). Grab and retrieve both happen here; read() just hands out
        # the newest converted frame.
        last_retrieve = 0.0
        while self.running and self.cap is not None:
            try:
                if not self.cap.grab():
                    time.sleep(0.05)
                    continue
                now = time.time()
                self.grab_ts = now
                if now - last_retrieve >= self.RETRIEVE_EVERY:
                    ok, frame = self.cap.retrieve()
                    if ok and frame is not None:
                        self.frame, self.has_frame, last_retrieve = frame, True, now
            except Exception as e:  # never let the grab thread die silently
                log.warning("grab error: %s", e)
                time.sleep(0.5)

    def read(self) -> tuple[bool, np.ndarray | None]:
        frame = self.frame
        if frame is None or time.time() - self.grab_ts > self.STALE_SEC:
            return False, None
        return True, frame  # never modified in place by the worker (resize / overlay make copies)

    def close(self) -> None:
        self.running = False
        if self.thread:
            self.thread.join(timeout=self.OPEN_TIMEOUT_MS / 1000 + 1)  # grab() may block up to the read timeout
            if self.thread.is_alive():
                log.warning("camera grab thread did not stop in time; leaving the stream to be closed by the OS")
                return
        if self.cap is not None:
            self.cap.release()
            self.cap = None


class FileSource:
    """Plays a video file in real time (looping), so recorded footage behaves like a live camera."""

    is_synthetic = False

    def __init__(self, path: str) -> None:
        self.path = path
        self.cap: cv2.VideoCapture | None = None
        self.fps = 25.0
        self.t0 = 0.0
        self.idx = -1
        self.last: np.ndarray | None = None

    def open(self) -> bool:
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"video file not found: {self.path}")
        self.cap = cv2.VideoCapture(self.path)
        if not self.cap.isOpened():
            return False
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        if not (1 <= self.fps <= 240):
            self.fps = 25.0
        self.t0, self.idx = time.time(), -1
        return True

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self.cap is None:
            return False, None
        target = int((time.time() - self.t0) * self.fps)
        if target - self.idx > self.fps * 3:  # far behind: seek
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            self.idx = target - 1
        grabbed = False
        while self.idx < target:
            if not self.cap.grab():
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop
                self.t0, self.idx = time.time(), -1
                target = 0
                if not self.cap.grab():
                    return False, None
            self.idx += 1
            grabbed = True
        if grabbed:
            ok, frame = self.cap.retrieve()
            if ok:
                self.last = frame
        return (self.last is not None), (None if self.last is None else self.last.copy())

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None


def make_source(info: dict, station: Any | None) -> Any:
    st, src = info["source_type"], (info.get("source") or "").strip()
    if st == "simulated":
        if station is None:
            raise ValueError("simulated camera needs a station")
        sim = (info.get("config") or {}).get("sim") or {}
        params = SimParams(
            target_cycle_sec=station.target_cycle_sec,
            expected_picks=station.expected_picks,
            speed_factor=float(sim.get("speed_factor", 1.0)),
            far_reach_prob=float(sim.get("far_reach_prob", 0.1)),
            walk_prob=float(sim.get("walk_prob", 0.05)),
            extra_pick_prob=float(sim.get("extra_pick_prob", 0.1)),
        )
        return SyntheticSource(station.line_id, station.sequence, station.name, list(station.parts_added), params)
    if st == "usb":
        index = int(src or "0")
        api = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        return ThreadedCapture(index, api)
    if st == "file":
        return FileSource(src)
    if st in ("rtsp", "http"):
        if not src:
            raise ValueError("camera URL is empty")
        prefer_sub = bool((info.get("config") or {}).get("use_substream", True))
        return ThreadedCapture(src, cv2.CAP_FFMPEG, prefer_substream=prefer_sub)
    raise ValueError(f"unknown source type {st}")
