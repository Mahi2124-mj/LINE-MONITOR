"""Simple setup flow: define a line, name each step, type the step's camera IP, check it, go live."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..hub import live
from ..schemas import CameraConfig, LineSetupIn, LineSetupOut, ProbeIn, ProbeOut
from ..services.serializers import camera_ids_by_station, camera_out, line_out, station_out
from ..vision.geometry import default_zones
from ..vision.manager import manager
from ..vision.probe import probe

router = APIRouter(prefix="/api", tags=["setup"])


def real_camera_config() -> dict:
    # CPU friendly defaults for real cameras; pose tracking when the YOLO model is installed
    # 3 fps is plenty for cycle times of 10 s and more, and lets ~7 cameras share one CPU pose model
    return CameraConfig(cycle_method="part_presence", tracker="auto", process_fps=3).model_dump()


@router.post("/cameras/probe", response_model=ProbeOut)
async def check_camera(data: ProbeIn):
    res = await asyncio.to_thread(probe, data.address, data.username, data.password)
    return ProbeOut(**res.__dict__)


@router.post("/setup/line", response_model=LineSetupOut)
def save_line_setup(data: LineSetupIn, db: Session = Depends(get_db)):
    if data.line_id is not None:
        line = db.get(models.Line, data.line_id)
        if line is None:
            raise HTTPException(404, "line not found")
    else:
        line = models.Line(name=data.name)
        db.add(line)
    line.name = data.name.strip()
    line.takt_time_sec = data.takt_time_sec
    if not line.code:
        line.code = "".join(w[0] for w in line.name.split()[:3]).upper()[:6]
    db.flush()

    existing = {s.id: s for s in db.scalars(select(models.Station).where(models.Station.line_id == line.id))}
    cams_by_station: dict[int, models.Camera] = {}
    for c in db.scalars(select(models.Camera).where(models.Camera.line_id == line.id)):
        if c.station_id is not None and c.station_id not in cams_by_station:
            cams_by_station[c.station_id] = c
        elif c.station_id is None:
            db.delete(c)

    touched_cams: set[int] = set()
    removed_cams: list[int] = []
    kept: set[int] = set()
    for seq, step in enumerate(data.steps, start=1):
        st = existing.get(step.station_id) if step.station_id is not None else None
        if st is None:
            st = models.Station(line_id=line.id, target_cycle_sec=line.takt_time_sec, expected_picks=2, parts_added=[])
            db.add(st)
        st.sequence = seq
        st.name = step.name.strip()
        st.code = st.code or f"{line.code}-S{seq}"
        db.flush()
        kept.add(st.id)
        cam = cams_by_station.get(st.id)
        address = step.camera_address.strip()
        if not address:
            if cam is not None:  # camera removed from this step
                removed_cams.append(cam.id)
                db.delete(cam)
            continue
        if step.camera_source:  # freshly checked camera
            if cam is None:
                cam = models.Camera(line_id=line.id, station_id=st.id, zones=default_zones(), config=real_camera_config())
                db.add(cam)
            elif cam.source != step.camera_source:
                (settings.references_dir / f"cam_{cam.id}.png").unlink(missing_ok=True)  # a different view
            cam.source_type = step.camera_source_type or "rtsp"
            cam.source = step.camera_source
            cam.enabled = True
        elif cam is None:
            raise HTTPException(400, f"Step {seq} ({st.name}): click 'Check' for its camera before going live")
        cam.name = f"{st.name} camera"
        db.flush()
        touched_cams.add(cam.id)

    for sid, st in existing.items():
        if sid not in kept:
            c = cams_by_station.get(sid)
            if c is not None and c.id not in touched_cams:
                removed_cams.append(c.id)
                db.delete(c)
            db.execute(delete(models.Cycle).where(models.Cycle.station_id == sid))
            db.delete(st)
    db.commit()

    for cid in removed_cams:
        manager.stop(cid)
        db.execute(delete(models.HeatmapDay).where(models.HeatmapDay.camera_id == cid))
        (settings.references_dir / f"cam_{cid}.png").unlink(missing_ok=True)
    db.commit()
    for sid in set(existing) - kept:
        live.remove(sid)
    stations = db.scalars(select(models.Station).where(models.Station.line_id == line.id).order_by(models.Station.sequence)).all()
    for s in stations:
        live.ensure(s.id, s.line_id)
    manager.refresh_line_meta(line.id)
    for cid in touched_cams:  # (re)start = go live
        manager.restart(cid)

    cam_map = camera_ids_by_station(db, line.id)
    cams = db.scalars(select(models.Camera).where(models.Camera.line_id == line.id).order_by(models.Camera.id)).all()
    return LineSetupOut(line=line_out(db, line), stations=[station_out(s, cam_map) for s in stations], cameras=[camera_out(c) for c in cams])
