from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..database import get_db
from ..hub import hub, live
from ..schemas import AlertOut, Health, MovementRow, Overview, RangeKey, StationLive
from ..services.analytics import compute_movement_rows, compute_overview, resolve_range
from ..vision.manager import manager
from ..vision.trackers import PoseModel
from .stations import today_stats

router = APIRouter(tags=["dashboard"])


@router.get("/api/health", response_model=Health)
def health():
    return Health(version=settings.version, demo_mode=settings.demo_mode, pose_available=PoseModel.available(),
                  cameras_running=manager.running_count(), server_time=datetime.now())


@router.get("/api/overview", response_model=Overview, response_model_by_alias=True)
def overview(range: RangeKey = Query("24h"), db: Session = Depends(get_db)):
    start, end = resolve_range(range)
    return compute_overview(db, start, end)


@router.get("/api/live", response_model=list[StationLive])
def live_states():
    return live.snapshot()


@router.get("/api/movement", response_model=list[MovementRow])
def movement(range: RangeKey = Query("24h"), line_id: int | None = None, db: Session = Depends(get_db)):
    start, end = resolve_range(range)
    return compute_movement_rows(db, start, end, line_id)


# ------------------------------------------------------------------ alerts
@router.get("/api/alerts", response_model=list[AlertOut])
def alerts(status: str = Query("open", pattern="^(open|all)$"), limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    q = select(models.Alert).order_by(models.Alert.created_at.desc()).limit(limit)
    if status == "open":
        q = q.where(models.Alert.acknowledged.is_(False))
    return db.scalars(q).all()


@router.post("/api/alerts/ack-all")
def ack_all(db: Session = Depends(get_db)):
    res = db.execute(update(models.Alert).where(models.Alert.acknowledged.is_(False)).values(acknowledged=True, acknowledged_at=datetime.now()))
    db.commit()
    return {"acknowledged": res.rowcount or 0}


@router.post("/api/alerts/{alert_id}/ack", response_model=AlertOut)
def ack(alert_id: int, db: Session = Depends(get_db)):
    a = db.get(models.Alert, alert_id)
    if a is None:
        raise HTTPException(404, "alert not found")
    a.acknowledged, a.acknowledged_at = True, datetime.now()
    db.commit()
    return a


# ------------------------------------------------------------------ export / system
@router.get("/api/export/cycles.csv")
def export_cycles(range: RangeKey = Query("24h"), line_id: int | None = None, station_id: int | None = None, db: Session = Depends(get_db)):
    start, end = resolve_range(range)
    C, S, L = models.Cycle, models.Station, models.Line
    q = (select(L.name, S.sequence, S.name, C.started_at, C.ended_at, C.cycle_sec, C.work_sec, C.motion_waste_sec, C.wait_sec,
                C.hand_travel_m, C.reach_count, C.walk_m, C.pick_count, C.over_target, C.source)
         .join(S, S.id == C.station_id).join(L, L.id == C.line_id)
         .where(C.ended_at >= start, C.ended_at <= end).order_by(C.ended_at))
    if line_id is not None:
        q = q.where(C.line_id == line_id)
    if station_id is not None:
        q = q.where(C.station_id == station_id)

    rows = db.execute(q).all()  # fetch now: the DB session closes before the response streams

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["line", "step", "station", "started_at", "ended_at", "cycle_sec", "work_sec", "motion_waste_sec", "wait_sec",
                    "hand_travel_m", "reach_count", "walk_m", "pick_count", "over_target", "source"])
        for row in rows:
            w.writerow([row[0], row[1], row[2], row[3].isoformat(sep=" ", timespec="seconds"), row[4].isoformat(sep=" ", timespec="seconds"), *row[5:]])
            if buf.tell() > 64_000:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    name = f"cycles_{range}_{datetime.now():%Y%m%d_%H%M}.csv"
    return StreamingResponse(gen(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/api/system/clear-data")
def clear_data(db: Session = Depends(get_db)):
    n = db.execute(delete(models.Cycle)).rowcount or 0
    db.execute(delete(models.Alert))
    db.execute(delete(models.HeatmapDay))
    db.commit()
    live.reset([(s.id, s.line_id) for s in db.scalars(select(models.Station))], today_stats(db))
    return {"deleted": n}


# ------------------------------------------------------------------ websocket
@router.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await hub.connect(ws)
    try:
        await ws.send_json({"type": "states", "data": [StationLive(**s).model_dump(mode="json") for s in live.snapshot()]})
        while True:
            await ws.receive_text()  # client pings; we only push
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.disconnect(ws)
