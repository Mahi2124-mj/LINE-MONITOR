from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..schemas import CameraConfig, CameraOut, CameraStatus, LineOut, StationOut, Zone
from ..config import settings


def line_out(db: Session, line: models.Line, counts: tuple[int, int] | None = None) -> LineOut:
    if counts is None:
        sc = db.scalar(select(func.count(models.Station.id)).where(models.Station.line_id == line.id)) or 0
        cc = db.scalar(select(func.count(models.Camera.id)).where(models.Camera.line_id == line.id)) or 0
    else:
        sc, cc = counts
    out = LineOut.model_validate(line)
    out.station_count, out.camera_count = sc, cc
    return out


def lines_out(db: Session, lines: list[models.Line]) -> list[LineOut]:
    sc = dict(db.execute(select(models.Station.line_id, func.count(models.Station.id)).group_by(models.Station.line_id)).all())
    cc = dict(db.execute(select(models.Camera.line_id, func.count(models.Camera.id)).group_by(models.Camera.line_id)).all())
    return [line_out(db, l, (sc.get(l.id, 0), cc.get(l.id, 0))) for l in lines]


def camera_ids_by_station(db: Session, line_id: int | None = None) -> dict[int, list[int]]:
    q = select(models.Camera.id, models.Camera.station_id, models.Camera.zones)
    if line_id is not None:
        q = q.where(models.Camera.line_id == line_id)
    out: dict[int, set[int]] = defaultdict(set)
    for cid, sid, zones in db.execute(q).all():
        if sid is not None:
            out[sid].add(cid)
        for z in zones or []:
            if z.get("station_id") is not None:
                out[z["station_id"]].add(cid)
    return {k: sorted(v) for k, v in out.items()}


def station_out(s: models.Station, cam_map: dict[int, list[int]]) -> StationOut:
    out = StationOut.model_validate(s)
    out.parts_added = list(s.parts_added or [])
    out.camera_ids = cam_map.get(s.id, [])
    return out


def camera_out(c: models.Camera) -> CameraOut:
    from ..vision.manager import manager
    from ..vision.probe import mask_source

    zones = []
    for z in c.zones or []:
        try:
            zones.append(Zone(**z))
        except Exception:
            continue
    return CameraOut(
        id=c.id,
        line_id=c.line_id,
        station_id=c.station_id,
        name=c.name,
        source_type=c.source_type,
        source=mask_source(c.source),  # never send camera passwords to the browser
        enabled=c.enabled,
        zones=zones,
        config=CameraConfig(**(c.config or {})),
        has_reference=(settings.references_dir / f"cam_{c.id}.png").exists(),
        status=CameraStatus(**manager.status(c.id, c.enabled)),
    )
