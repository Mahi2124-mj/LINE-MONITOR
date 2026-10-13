from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..hub import live
from ..schemas import LineAnalytics, LineIn, LineOut, LineUpdate, RangeKey, ReorderIn, StationOut
from ..services.analytics import compute_line, lines_list, resolve_range
from ..services.serializers import camera_ids_by_station, line_out, station_out
from ..vision.manager import manager

router = APIRouter(prefix="/api/lines", tags=["lines"])


def _get(db: Session, line_id: int) -> models.Line:
    line = db.get(models.Line, line_id)
    if line is None:
        raise HTTPException(404, "line not found")
    return line


@router.get("", response_model=list[LineOut])
def list_lines(db: Session = Depends(get_db)):
    return lines_list(db)


@router.post("", response_model=LineOut, status_code=201)
def create_line(data: LineIn, db: Session = Depends(get_db)):
    line = models.Line(**data.model_dump())
    db.add(line)
    db.commit()
    return line_out(db, line)


@router.get("/{line_id}", response_model=LineOut)
def get_line(line_id: int, db: Session = Depends(get_db)):
    return line_out(db, _get(db, line_id))


@router.put("/{line_id}", response_model=LineOut)
def update_line(line_id: int, data: LineUpdate, db: Session = Depends(get_db)):
    line = _get(db, line_id)
    was_active = line.is_active
    upd = data.model_dump(exclude_unset=True)
    if "shift_start" in upd or "shift_end" in upd:
        LineIn(name=line.name, **{k: upd.get(k, getattr(line, k)) for k in ("shift_start", "shift_end")})  # validate HH:MM
    for k, v in upd.items():
        setattr(line, k, v)
    db.commit()
    if was_active != line.is_active:
        if line.is_active:
            for cid in db.scalars(select(models.Camera.id).where(models.Camera.line_id == line_id, models.Camera.enabled.is_(True))):
                manager.start(cid)
        else:
            for cid in db.scalars(select(models.Camera.id).where(models.Camera.line_id == line_id)):
                manager.stop(cid)
    else:
        manager.refresh_line_meta(line_id)
    return line_out(db, line)


@router.delete("/{line_id}", status_code=204)
def delete_line(line_id: int, db: Session = Depends(get_db)):
    line = _get(db, line_id)
    cam_ids = db.scalars(select(models.Camera.id).where(models.Camera.line_id == line_id)).all()
    for cid in cam_ids:
        manager.stop(cid)
    st_ids = db.scalars(select(models.Station.id).where(models.Station.line_id == line_id)).all()
    db.execute(delete(models.Cycle).where(models.Cycle.line_id == line_id))
    db.execute(delete(models.Alert).where(models.Alert.line_id == line_id))
    if cam_ids:
        db.execute(delete(models.HeatmapDay).where(models.HeatmapDay.camera_id.in_(cam_ids)))
    db.execute(delete(models.Camera).where(models.Camera.line_id == line_id))
    db.execute(delete(models.Station).where(models.Station.line_id == line_id))
    db.delete(line)
    db.commit()
    for sid in st_ids:
        live.remove(sid)


@router.get("/{line_id}/analytics", response_model=LineAnalytics, response_model_by_alias=True)
def line_analytics(line_id: int, range: RangeKey = Query("24h"), db: Session = Depends(get_db)):
    start, end = resolve_range(range)
    return compute_line(db, _get(db, line_id), start, end)


@router.post("/{line_id}/stations/reorder", response_model=list[StationOut])
def reorder(line_id: int, data: ReorderIn, db: Session = Depends(get_db)):
    _get(db, line_id)
    stations = {s.id: s for s in db.scalars(select(models.Station).where(models.Station.line_id == line_id))}
    if set(data.station_ids) != set(stations):
        raise HTTPException(400, "station_ids must contain every station of the line exactly once")
    for i, sid in enumerate(data.station_ids, start=1):
        stations[sid].sequence = i
    db.commit()
    manager.restart_line(line_id)
    cam_map = camera_ids_by_station(db, line_id)
    return [station_out(stations[sid], cam_map) for sid in data.station_ids]
