"""'Check camera': turn what the user typed (IP, RTSP/HTTP URL, USB index, file path) into a working
video source and grab one frame from it."""
from __future__ import annotations

import base64
import os
import re
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit

import cv2

# Main-stream paths of common IP camera brands, tried in this order when only an IP is given.
RTSP_PATHS = [
    "/Streaming/Channels/101",  # Hikvision, Prama, many OEMs
    "/cam/realmonitor?channel=1&subtype=0",  # Dahua, CP Plus, Lorex
    "/stream1",  # TP-Link Tapo/VIGI, generic
    "/h264/ch1/main/av_stream",  # older Hikvision
    "/live",  # generic
    "/11",  # Uniview / some Chinese OEMs
    "/onvif1",  # generic ONVIF
    "/live/ch00_0",  # some NVR/IPC OEMs
    "/videoMain",  # Foscam
    "/",  # last resort
]
OPEN_TIMEOUT_MS = 5000


@dataclass
class ProbeResult:
    ok: bool
    source_type: str | None = None
    source: str | None = None
    display_source: str | None = None
    width: int = 0
    height: int = 0
    snapshot: str | None = None  # data URL (jpeg)
    elapsed_ms: int = 0
    tried: int = 0
    error: str | None = None


def mask_source(src: str) -> str:
    """rtsp://admin:secret@1.2.3.4/... -> rtsp://admin:****@1.2.3.4/..."""
    return re.sub(r"(://[^:/@]+):[^@/]*@", r"\1:****@", src or "")


def _with_credentials(url: str, user: str, pwd: str) -> str:
    if not user:
        return url
    parts = urlsplit(url)
    if "@" in parts.netloc:
        return url  # credentials already in the URL
    netloc = f"{quote(user, safe='')}:{quote(pwd, safe='')}@{parts.netloc}" if pwd else f"{quote(user, safe='')}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def candidates(address: str, user: str = "", pwd: str = "") -> list[tuple[str, str]]:
    a = (address or "").strip()
    if not a:
        return []
    if re.fullmatch(r"\d{1,2}", a):
        return [("usb", a)]
    low = a.lower()
    if low.startswith(("rtsp://", "rtsps://")):
        return [("rtsp", _with_credentials(a, user, pwd))]
    if low.startswith(("http://", "https://")):
        return [("http", _with_credentials(a, user, pwd))]
    if os.path.exists(a):
        return [("file", a)]
    m = re.fullmatch(r"([A-Za-z0-9.\-]+)(?::(\d{1,5}))?(/.*)?", a)
    if not m:
        return []
    host, port, path = m.group(1), m.group(2) or "554", m.group(3)
    cred = ""
    if user:
        cred = f"{quote(user, safe='')}:{quote(pwd, safe='')}@" if pwd else f"{quote(user, safe='')}@"
    paths = [path] if path else RTSP_PATHS
    return [("rtsp", f"rtsp://{cred}{host}:{port}{p}") for p in paths]


def _reachable(url: str, timeout: float = 2.5) -> str | None:
    """Fast TCP check so a wrong IP fails in seconds instead of timing out on every path."""
    parts = urlsplit(url)
    host = parts.hostname
    port = parts.port or (554 if parts.scheme.startswith("rtsp") else 443 if parts.scheme == "https" else 80)
    if not host:
        return "invalid address"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except OSError:
        return f"Camera not reachable at {host}:{port} - check the IP address, network cable / Wi-Fi and that the camera is powered on."


def _open(kind: str, src: str):
    if kind == "usb":
        api = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        return cv2.VideoCapture(int(src), api)
    if kind == "file":
        return cv2.VideoCapture(src)
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, OPEN_TIMEOUT_MS]
    try:
        return cv2.VideoCapture(src, cv2.CAP_FFMPEG, params)
    except TypeError:  # very old OpenCV without the params overload
        return cv2.VideoCapture(src, cv2.CAP_FFMPEG)


def _grab(kind: str, src: str):
    cap = _open(kind, src)
    try:
        if not cap.isOpened():
            return None
        frame = None
        for _ in range(5):  # first frames of some cameras are grey / incomplete
            ok, f = cap.read()
            if ok and f is not None:
                frame = f
                if kind != "usb":
                    break
        return frame
    finally:
        cap.release()


def probe(address: str, user: str = "", pwd: str = "") -> ProbeResult:
    t0 = time.time()
    cands = candidates(address, user, pwd)
    if not cands:
        return ProbeResult(False, error="Enter the camera IP (e.g. 192.168.1.64) or a full rtsp:// / http:// URL.")
    kind0 = cands[0][0]
    if kind0 in ("rtsp", "http"):
        err = _reachable(cands[0][1])
        if err:
            return ProbeResult(False, error=err, elapsed_ms=int((time.time() - t0) * 1000), tried=0)

    frame, hit = None, None
    if len(cands) == 1:
        frame, hit = _grab(*cands[0]), cands[0]
    else:
        # a few paths in parallel (cameras allow only a handful of sessions), keep the brand priority order
        ex = ThreadPoolExecutor(max_workers=3)
        try:
            futures = [ex.submit(_grab, k, s) for k, s in cands]
            for (k, s), fut in zip(cands, futures):
                try:
                    f = fut.result(timeout=OPEN_TIMEOUT_MS / 1000 * 3)
                except Exception:
                    f = None
                if f is not None:
                    frame, hit = f, (k, s)
                    break
        finally:
            ex.shutdown(wait=False, cancel_futures=True)  # don't wait for slower wrong paths

    elapsed = int((time.time() - t0) * 1000)
    if frame is None or hit is None:
        if kind0 == "rtsp":
            msg = ("Camera is reachable but no video stream was found. Check the username / password, "
                   "or paste the full RTSP URL from the camera's manual.")
        elif kind0 == "usb":
            msg = "No USB camera at this number. Try 0, 1 or 2."
        else:
            msg = "Could not read video from this address."
        return ProbeResult(False, error=msg, elapsed_ms=elapsed, tried=len(cands))

    h, w = frame.shape[:2]
    thumb = cv2.resize(frame, (480, int(h * 480 / w))) if w > 480 else frame
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 75])
    snap = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else None
    kind, src = hit
    return ProbeResult(True, source_type=kind, source=src, display_source=mask_source(src), width=w, height=h,
                       snapshot=snap, elapsed_ms=elapsed, tried=len(cands))
