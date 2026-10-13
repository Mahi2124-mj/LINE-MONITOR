from __future__ import annotations

import asyncio
from datetime import timedelta
from functools import lru_cache

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..schemas import AnalyzerInfo, CameraConfig, CameraIn, CameraOut, CameraUpdate, Heatmap, RangeKey, Track
from ..services.analytics import resolve_range
from ..services.heatmaps import get_heatmap
from ..services.serializers import camera_out
from ..vision import synthetic
from ..vision.analyzers import analyzer_catalog
from ..vision.geometry import default_zones
from ..vision.manager import manager
from ..vision.probe import mask_source

router = APIRouter(prefix="/api", tags=["cameras"])
NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


def _get(db: Session, camera_id: int) -> models.Camera:
    c = db.get(models.Camera, camera_id)
    if c is None:
        raise HTTPException(404, "camera not found")
    return c


def _check_refs(db: Session, line_id: int, station_id: int | None) -> None:
    if db.get(models.Line, line_id) is None:
        raise HTTPException(400, "line not found")
    if station_id is not None:
        s = db.get(models.Station, station_id)
        if s is None or s.line_id != line_id:
            raise HTTPException(400, "station does not belong to this line")


@lru_cache(maxsize=8)
def placeholder_jpeg(text: str) -> bytes:
    img = np.full((360, 640, 3), (28, 30, 34), np.uint8)
    for k in range(0, 640, 32):
        cv2.line(img, (k, 0), (k, 360), (34, 36, 40), 1)
    size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)[0]
    cv2.putText(img, text, ((640 - size[0]) // 2, 190), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (140, 140, 150), 2, cv2.LINE_AA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()


@router.get("/analyzers", response_model=list[AnalyzerInfo])
def analyzers():
    return analyzer_catalog()


@router.get("/cameras", response_model=list[CameraOut])
def list_cameras(line_id: int | None = None, db: Session = Depends(get_db)):
    q = select(models.Camera).order_by(models.Camera.line_id, models.Camera.id)
    if line_id is not None:
        q = q.where(models.Camera.line_id == line_id)
    return [camera_out(c) for c in db.scalars(q)]


@router.post("/cameras", response_model=CameraOut, status_code=201)
def create_camera(data: CameraIn, db: Session = Depends(get_db)):
    _check_refs(db, data.line_id, data.station_id)
    if data.source_type == "simulated" and data.station_id is None:
        raise HTTPException(400, "a simulated camera needs a station")
    cfg = dict(data.config or {})
    if data.source_type == "simulated":
        cfg.setdefault("tracker", "simulated")
        cfg.setdefault("sim", {})
    config = CameraConfig(**cfg)
    if data.zones is not None:
        zones = [z.model_dump() for z in data.zones]
    else:
        zones = synthetic.demo_zones() if data.source_type == "simulated" else default_zones()
    cam = models.Camera(line_id=data.line_id, station_id=data.station_id, name=data.name, source_type=data.source_type,
                        source=data.source or ("sim" if data.source_type == "simulated" else ""), enabled=data.enabled,
                        zones=zones, config=config.model_dump())
    db.add(cam)
    db.commit()
    if cam.enabled:
        manager.start(cam.id)
    return camera_out(cam)


@router.get("/cameras/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    return camera_out(_get(db, camera_id))


@router.put("/cameras/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, data: CameraUpdate, db: Session = Depends(get_db)):
    cam = _get(db, camera_id)
    upd = data.model_dump(exclude_unset=True)
    line_id = upd.get("line_id", cam.line_id)
    station_id = upd.get("station_id", cam.station_id)
    _check_refs(db, line_id, station_id)
    if "zones" in upd:
        upd["zones"] = [z.model_dump() for z in (data.zones or [])]
    if "config" in upd:
        merged = {**(cam.config or {}), **(upd["config"] or {})}
        upd["config"] = CameraConfig(**merged).model_dump()
    if "source" in upd and upd["source"] == mask_source(cam.source):
        upd.pop("source")  # the browser only knows the masked URL: keep the stored password
    source_changed = any(k in upd and upd[k] != getattr(cam, k) for k in ("source", "source_type"))
    for k, v in upd.items():
        setattr(cam, k, v)
    db.commit()
    if source_changed:  # a different camera view: the old empty-reference image no longer matches
        (settings.references_dir / f"cam_{camera_id}.png").unlink(missing_ok=True)
    if cam.enabled:
        manager.restart(camera_id)
    else:
        manager.stop(camera_id)
    return camera_out(cam)


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    cam = _get(db, camera_id)
    manager.stop(camera_id)
    db.execute(delete(models.HeatmapDay).where(models.HeatmapDay.camera_id == camera_id))
    db.delete(cam)
    db.commit()
    (settings.references_dir / f"cam_{camera_id}.png").unlink(missing_ok=True)


@router.post("/cameras/{camera_id}/restart", response_model=CameraOut)
def restart_camera(camera_id: int, db: Session = Depends(get_db)):
    cam = _get(db, camera_id)
    if not cam.enabled:
        raise HTTPException(400, "camera is disabled")
    manager.restart(camera_id)
    return camera_out(cam)


@router.post("/cameras/{camera_id}/reference", response_model=CameraOut)
def capture_reference(camera_id: int, db: Session = Depends(get_db)):
    cam = _get(db, camera_id)
    w = manager.get(camera_id)
    if w is None or not w.request_reference():
        raise HTTPException(409, "camera has no live frame yet")
    return camera_out(cam)


@router.get("/cameras/{camera_id}/snapshot.jpg")
def snapshot(camera_id: int, overlay: int = 0, db: Session = Depends(get_db)):
    _get(db, camera_id)
    w = manager.get(camera_id)
    jpg = w.render_jpeg(bool(overlay)) if w is not None else None
    if jpg is None:
        ref = settings.references_dir / f"cam_{camera_id}.png"
        if ref.exists():
            img = cv2.imread(str(ref))
            if img is not None:
                jpg = cv2.imencode(".jpg", img)[1].tobytes()
    return Response(jpg or placeholder_jpeg("NO SIGNAL"), media_type="image/jpeg", headers=NO_CACHE)


@router.get("/cameras/{camera_id}/stream.mjpg")
async def stream(camera_id: int, request: Request, overlay: int = 1):
    boundary = "frame"

    def part(jpg: bytes) -> bytes:
        return b"--" + boundary.encode() + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"

    async def gen():
        counted = None
        last_seq = -1
        interval = 1.0 / max(1.0, settings.stream_fps)
        try:
            while True:
                if await request.is_disconnected():
                    break
                w = manager.get(camera_id)
                if w is not counted:
                    if counted is not None:
                        counted.viewers = max(0, counted.viewers - 1)
                    if w is not None:
                        w.viewers += 1
                    counted, last_seq = w, -1
                jpg = None
                if w is None or not w.status.get("online"):
                    if last_seq != -2:
                        jpg, last_seq = placeholder_jpeg("NO SIGNAL" if w is not None else "CAMERA STOPPED"), -2
                    await asyncio.sleep(1.0)
                elif overlay:
                    if w.jpeg is not None and w.jpeg_seq != last_seq:
                        jpg, last_seq = w.jpeg, w.jpeg_seq
                else:
                    jpg = await asyncio.to_thread(w.render_jpeg, False)
                if jpg:
                    yield part(jpg)
                await asyncio.sleep(interval)
        finally:
            if counted is not None:
                counted.viewers = max(0, counted.viewers - 1)

    return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}", headers=NO_CACHE)


@router.get("/cameras/{camera_id}/heatmap", response_model=Heatmap)
def heatmap(camera_id: int, range: RangeKey = Query("24h"), db: Session = Depends(get_db)):
    _get(db, camera_id)
    start, end = resolve_range(range)
    days, d = [], start.date()
    while d <= end.date():
        days.append(d.isoformat())
        d += timedelta(days=1)
    cols, rows = settings.heatmap_cols, settings.heatmap_rows
    grid = get_heatmap(camera_id, days, cols, rows)
    w = manager.get(camera_id)  # include not-yet-flushed live data
    hm = next((a for a in (w.analyzers if w else []) if a.key == "heatmap"), None)
    if hm is not None and hm.grid.shape == (rows, cols):
        grid = grid + hm.grid.reshape(-1)
    return Heatmap(camera_id=camera_id, cols=cols, rows=rows, grid=np.round(grid, 2).tolist(), max=round(float(grid.max()) if grid.size else 0.0, 2))


@router.get("/cameras/{camera_id}/tracks", response_model=list[Track])
def tracks(camera_id: int, limit: int = Query(10, ge=1, le=100), db: Session = Depends(get_db)):
    _get(db, camera_id)
    q = (select(models.Cycle).where(models.Cycle.camera_id == camera_id, models.Cycle.track.is_not(None))
         .order_by(models.Cycle.ended_at.desc()).limit(limit))
    out = []
    for c in db.scalars(q):
        t = c.track or {}
        out.append(Track(cycle_id=c.id, ended_at=c.ended_at, hand=t.get("hand") or [], body=t.get("body") or []))
    return out
