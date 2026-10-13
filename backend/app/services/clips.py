"""Cut browser-playable WebM (VP8) clips and element thumbnails out of the recordings."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import cv2
import numpy as np

from ..config import settings
from ..vision.recorder import list_segments

OUT_FPS = 6
_lock = threading.Lock()  # one encode at a time (CPU)


def _frames(camera_id: int, t0: float, t1: float):
    """Yields (t, frame, operator wrists) for recorded frames in [t0, t1], oldest first."""
    for start, jpath in list_segments(camera_id, t0, t1):
        metas = []
        with open(jpath, encoding="utf-8") as f:
            for line in f:
                try:
                    metas.append(json.loads(line))
                except ValueError:
                    break
        if not metas or metas[-1]["t"] < t0 or metas[0]["t"] > t1:
            continue
        first = next(i for i, m in enumerate(metas) if m["t"] >= t0)

        def wrists(m: dict):
            op = m.get("op")
            people = m.get("p") or []
            person = people[op] if isinstance(op, int) and op < len(people) else (people[0] if people else None)
            return (person or {}).get("w")

        mpath = jpath.with_suffix(".mjpg")
        if mpath.exists():  # current format: JPEGs back to back, offsets in the json lines
            with open(mpath, "rb") as vf:
                for m in metas[first:]:
                    if m["t"] > t1:
                        break
                    if "o" not in m:
                        continue
                    vf.seek(m["o"])
                    data = vf.read(m["n"])
                    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) if len(data) == m["n"] else None
                    if frame is not None:
                        yield m["t"], frame, wrists(m)
            continue
        vpath = jpath.with_suffix(".avi")  # older recordings
        if not vpath.exists():
            continue
        cap = cv2.VideoCapture(str(vpath), cv2.CAP_FFMPEG)
        if first:
            cap.set(cv2.CAP_PROP_POS_FRAMES, first)
        for m in metas[first:]:
            ok, frame = cap.read()
            if not ok or m["t"] > t1:
                break
            yield m["t"], frame, wrists(m)
        cap.release()


def cycle_clip(camera_id: int, t0: float, t1: float, labels: list[tuple[float, float, str, str]] | None = None) -> Path | None:
    """WebM of [t0, t1] at a constant frame rate (real time), with elapsed time and current element burnt in.
    labels: (start, end, name, hex colour) relative to t0. Cached on disk."""
    out_dir = settings.clips_dir / f"cam_{camera_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{int(t0 * 1000)}_{int(t1 * 1000)}.webm"
    if out.exists() and out.stat().st_size > 0:
        return out
    with _lock:
        if out.exists() and out.stat().st_size > 0:
            return out
        src = list(_frames(camera_id, t0 - 0.5, t1 + 0.5))
        if not src:
            return None
        h, w = src[0][1].shape[:2]
        tmp = out.with_suffix(".tmp.webm")
        writer = cv2.VideoWriter(str(tmp), cv2.CAP_FFMPEG, cv2.VideoWriter_fourcc(*"VP80"), OUT_FPS, (w, h))
        if not writer.isOpened():
            return None
        times = np.array([s[0] for s in src])
        k = 0
        for n in range(int((t1 - t0) * OUT_FPS) + 1):
            t = t0 + n / OUT_FPS
            while k + 1 < len(times) and times[k + 1] <= t:
                k += 1
            frame = src[k][1].copy()
            rel = t - t0
            wr = src[k][2]
            if wr:
                for q in wr:
                    if q:
                        cv2.circle(frame, (int(q[0] * w), int(q[1] * h)), 9, (0, 255, 255), 2, cv2.LINE_AA)
            name, colour = "", (255, 255, 255)
            for a, b, nm, hexc in labels or []:
                if a <= rel < b:
                    name = nm
                    colour = tuple(int(hexc.lstrip("#")[i : i + 2], 16) for i in (4, 2, 0))  # BGR
                    break
            cv2.rectangle(frame, (0, 0), (w, 26), (0, 0, 0), -1)
            cv2.putText(frame, f"{rel:5.1f}s", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
            if name:
                cv2.putText(frame, name, (80, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 1, cv2.LINE_AA)
            writer.write(frame)
        writer.release()
        tmp.replace(out)
        return out


def element_thumb(camera_id: int, t: float, center: list[float]) -> bytes | None:
    """JPEG crop around the hands at a representative moment of an element."""
    for _, frame, _ in _frames(camera_id, t - 0.3, t + 0.5):
        h, w = frame.shape[:2]
        xs = [center[0] * w, center[2] * w]
        ys = [center[1] * h, center[3] * h]
        cx, cy = sum(xs) / 2, sum(ys) / 2
        half = max(70, (max(xs) - min(xs)) / 2 + 45, (max(ys) - min(ys)) / 2 + 45)
        x0, y0 = int(max(0, cx - half * 1.33)), int(max(0, cy - half))
        x1, y1 = int(min(w, cx + half * 1.33)), int(min(h, cy + half))
        crop = frame[y0:y1, x0:x1].copy()
        for i in (0, 2):
            cv2.circle(crop, (int(center[i] * w) - x0, int(center[i + 1] * h) - y0), 8, (0, 255, 255), 2, cv2.LINE_AA)
        crop = cv2.resize(crop, (240, int(240 * crop.shape[0] / max(1, crop.shape[1]))))
        ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None
    return None
