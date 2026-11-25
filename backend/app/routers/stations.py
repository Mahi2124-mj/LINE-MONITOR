from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..hub import hub, live
from ..schemas import CycleOut, ManualCycleIn, RangeKey, StationAnalytics, StationIn, StationOut, StationUpdate
from ..services.analytics import compute_station, resolve_range
from ..services.serializers import camera_ids_by_station, station_out
from ..vision.manager import manager

router = APIRouter(prefix="/api/stations", tags=["stations"])
LAST_CYCLE_DAYS = 30  # the live "last cycle" of a step: an older one is not shown


def _get(db: Session, station_id: int) -> models.Station:
    s = db.get(models.Station, station_id)
    if s is None:
        raise HTTPException(404, "station not found")
    return s


def _resequence(db: Session, line_id: int, moved: models.Station | None = None, new_seq: int | None = None) -> None:
    sts = db.scalars(select(models.Station).where(models.Station.line_id == line_id).order_by(models.Station.sequence, models.Station.id)).all()
    order = [s for s in sts if s is not moved]
    if moved is not None:
        pos = max(0, min(len(order), (new_seq or len(order) + 1) - 1))
        order.insert(pos, moved)
    for i, s in enumerate(order, start=1):
        s.sequence = i


def _restart_sim_cameras(db: Session, station_id: int) -> None:
    for cid in db.scalars(select(models.Camera.id).where(models.Camera.station_id == station_id, models.Camera.source_type == "simulated",
                                                         models.Camera.enabled.is_(True))):
        manager.restart(cid)


@router.get("", response_model=list[StationOut])
def list_stations(line_id: int | None = None, db: Session = Depends(get_db)):
    q = select(models.Station).order_by(models.Station.line_id, models.Station.sequence)
    if line_id is not None:
        q = q.where(models.Station.line_id == line_id)
    cam_map = camera_ids_by_station(db, line_id)
    return [station_out(s, cam_map) for s in db.scalars(q)]


@router.post("", response_model=StationOut, status_code=201)
def create_station(data: StationIn, db: Session = Depends(get_db)):
    if db.get(models.Line, data.line_id) is None:
        raise HTTPException(400, "line not found")
    vals = data.model_dump(exclude={"sequence"})
    s = models.Station(**vals, sequence=10_000)
    db.add(s)
    db.flush()
    _resequence(db, data.line_id, s, data.sequence)
    db.commit()
    live.ensure(s.id, s.line_id)
    manager.refresh_line_meta(s.line_id)
    if data.sequence is not None:
        manager.restart_line(s.line_id)
    return station_out(s, camera_ids_by_station(db, s.line_id))


@router.get("/{station_id}", response_model=StationOut)
def get_station(station_id: int, db: Session = Depends(get_db)):
    s = _get(db, station_id)
    return station_out(s, camera_ids_by_station(db, s.line_id))


@router.put("/{station_id}", response_model=StationOut)
def update_station(station_id: int, data: StationUpdate, db: Session = Depends(get_db)):
    s = _get(db, station_id)
    upd = data.model_dump(exclude_unset=True)
    new_seq = upd.pop("sequence", None)
    sim_relevant = any(k in upd for k in ("target_cycle_sec", "expected_picks", "name", "parts_added"))
    for k, v in upd.items():
        setattr(s, k, v)
    if new_seq is not None and new_seq != s.sequence:
        _resequence(db, s.line_id, s, new_seq)
    db.commit()
    if new_seq is not None:
        manager.restart_line(s.line_id)
    else:
        manager.refresh_line_meta(s.line_id)
        if sim_relevant:
            _restart_sim_cameras(db, s.id)
    return station_out(s, camera_ids_by_station(db, s.line_id))


@router.delete("/{station_id}", status_code=204)
def delete_station(station_id: int, db: Session = Depends(get_db)):
    s = _get(db, station_id)
    line_id = s.line_id
    db.execute(delete(models.Cycle).where(models.Cycle.station_id == station_id))
    for cam in db.scalars(select(models.Camera).where(models.Camera.line_id == line_id)):
        if cam.station_id == station_id:
            cam.station_id = None
        if any(z.get("station_id") == station_id for z in cam.zones or []):
            cam.zones = [z for z in cam.zones if z.get("station_id") != station_id]
    db.delete(s)
    db.flush()
    _resequence(db, line_id)
    db.commit()
    live.remove(station_id)
    manager.restart_line(line_id)


@router.get("/{station_id}/analytics", response_model=StationAnalytics, response_model_by_alias=True)
def station_analytics(station_id: int, range: RangeKey = Query("24h"), db: Session = Depends(get_db)):
    start, end = resolve_range(range)
    return compute_station(db, _get(db, station_id), start, end)


@router.get("/{station_id}/cycles", response_model=list[CycleOut])
def station_cycles(station_id: int, range: RangeKey = Query("24h"), limit: int = Query(50, ge=1, le=5000), db: Session = Depends(get_db)):
    _get(db, station_id)
    start, end = resolve_range(range)
    q = select(models.Cycle).where(models.Cycle.station_id == station_id, models.Cycle.ended_at >= start, models.Cycle.ended_at <= end)
    from ..services.detector_feed import feed

    if feed.owns(station_id):  # counted by its validated detector: the generic cycles are not shown
        q = q.where(models.Cycle.source != "vision")
    return db.scalars(q.order_by(models.Cycle.ended_at.desc()).limit(limit)).all()


@router.post("/{station_id}/cycles", response_model=CycleOut, status_code=201)
def add_manual_cycle(station_id: int, data: ManualCycleIn, db: Session = Depends(get_db)):
    s = _get(db, station_id)
    now = datetime.now()
    motion = data.motion_waste_sec or 0.0
    wait = data.wait_sec or 0.0
    work = data.work_sec if data.work_sec is not None else max(0.0, data.cycle_sec - motion - wait)
    c = models.Cycle(station_id=s.id, line_id=s.line_id, camera_id=None, started_at=now - timedelta(seconds=data.cycle_sec), ended_at=now,
                     cycle_sec=data.cycle_sec, work_sec=work, motion_waste_sec=motion, wait_sec=wait, source="manual",
                     over_target=(work + motion) > s.target_cycle_sec)
    db.add(c)
    db.commit()
    out = CycleOut.model_validate(c)
    live.record_cycle(s.id, data.cycle_sec, now.timestamp())
    hub.publish("cycle", out.model_dump(mode="json"))
    return out


def today_stats(db: Session) -> dict[int, tuple[int, float, float | None]]:
    """station_id -> (count today, sum cycle sec, last cycle sec) for the live registry."""
    from ..services.detector_feed import feed

    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    C = models.Cycle
    # steps counted by their validated detector: their generic cycles do not count (see services/detector_feed.py)
    counted = ~((C.source == "vision") & C.station_id.in_(sorted(feed.owned))) if feed.owned else C.id.isnot(None)
    # Both queries seek the (station_id, ended_at) index per step. Without station_id in the condition SQLite read the
    # whole cycles table (450k+ rows, on a hard disk) at every server start: over a minute before the page opened.
    ids = list(db.scalars(select(models.Station.id)))
    out: dict[int, tuple[int, float, float | None]] = {}
    for sid, cnt, total in db.execute(select(C.station_id, func.count(C.id), func.sum(C.cycle_sec))
                                      .where(C.station_id.in_(ids), C.ended_at >= start, counted).group_by(C.station_id)):
        out[sid] = (int(cnt), float(total or 0), None)
    since = start - timedelta(days=LAST_CYCLE_DAYS)
    for sid in ids:
        cyc = db.scalar(select(C.cycle_sec).where(C.station_id == sid, C.ended_at >= since, counted).order_by(C.ended_at.desc()).limit(1))
        if cyc is not None:
            cnt, total, _ = out.get(sid, (0, 0.0, None))
            out[sid] = (cnt, total, float(cyc))
    return out
