"""Helpers: read recorded frames of a camera between two local times and build contact sheets."""
import json, sys, time, datetime as dt
from pathlib import Path
import numpy as np, cv2
REC = Path(r"C:\Users\DX-ADMIN\Pictures\LIne monitoring\backend\data\recordings")

def ts(hms, day="2026-10-09"):
    return time.mktime(time.strptime(f"{day} {hms}", "%Y-%m-%d %H:%M:%S"))

def index(cam, t0, t1):
    out = []
    for j in sorted((REC / f"cam_{cam}").glob("*.jsonl")):
        m = j.with_suffix(".mjpg")
        if not m.exists(): continue
        st = time.mktime(time.strptime(j.stem, "%Y%m%d_%H%M%S"))
        if st > t1 or st < t0 - 70: continue
        for line in open(j, encoding="utf-8"):
            try: r = json.loads(line)
            except ValueError: continue
            if t0 <= r["t"] <= t1: out.append((r["t"], m, r["o"], r["n"], r))
    return out

def frame(m, o, n):
    with open(m, "rb") as f:
        f.seek(o); b = f.read(n)
    return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)

def sheet(cam, t0, t1, step, out, crop=None, cols=8, tw=240, marks=()):
    idx = index(cam, t0, t1)
    tiles, nxt = [], t0
    for t, m, o, n, r in idx:
        if t < nxt: continue
        nxt = t + step
        img = frame(m, o, n)
        h, w = img.shape[:2]
        if crop: x0, y0, x1, y1 = crop; img = img[int(y0*h):int(y1*h), int(x0*w):int(x1*w)]
        th = int(img.shape[0] * tw / img.shape[1])
        img = cv2.resize(img, (tw, th))
        lab = dt.datetime.fromtimestamp(t).strftime("%H:%M:%S")
        hit = any(abs(t - mk) < step / 2 + 0.01 for mk in marks)
        cv2.rectangle(img, (0, 0), (tw, 18), (0, 0, 200) if hit else (0, 0, 0), -1)
        cv2.putText(img, lab + (" END" if hit else ""), (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        tiles.append(img)
    while len(tiles) % cols: tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i+cols]) for i in range(0, len(tiles), cols)]
    cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])
    return len(idx)
