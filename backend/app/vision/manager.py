"""Starts / stops / reloads camera workers."""
from __future__ import annotations

import logging
import threading

from sqlalchemy import select

from ..database import SessionLocal
from ..hub import live
from .. import models
from .worker import CameraWorker, LineMeta, StationMeta

log = logging.getLogger(__name__)


def _line_meta(db, line_id: int) -> tuple[dict[int, StationMeta], LineMeta] | None:
    line = db.get(models.Line, line_id)
    if line is None:
        return None
    stations = db.scalars(select(models.Station).where(models.Station.line_id == line_id)).all()
    metas = {
        s.id: StationMeta(s.id, s.line_id, s.name, s.sequence, s.target_cycle_sec, s.expected_picks, list(s.parts_added or []))
        for s in stations
        if s.is_active
    }
    return metas, LineMeta(line.id, line.name, line.takt_time_sec)


def _camera_info(c: models.Camera) -> dict:
    return {
        "id": c.id, "line_id": c.line_id, "station_id": c.station_id, "name": c.name,
        "source_type": c.source_type, "source": c.source, "zones": list(c.zones or []), "config": dict(c.config or {}),
    }


class CameraManager:
    def __init__(self) -> None:
        self.workers: dict[int, CameraWorker] = {}
        self.lock = threading.RLock()

    def start_all(self) -> None:
        with SessionLocal() as db:
            ids = db.scalars(select(models.Camera.id).where(models.Camera.enabled.is_(True))).all()
        for i, cid in enumerate(ids):
            self.start(cid, initial_delay=i * 2.0)  # stagger the first connections (cameras / router dislike bursts)
        log.info("started %d camera workers", len(ids))

    def start(self, camera_id: int, initial_delay: float = 0.0) -> CameraWorker | None:
        with self.lock:
            self.stop(camera_id)
            with SessionLocal() as db:
                cam = db.get(models.Camera, camera_id)
                if cam is None or not cam.enabled:
                    return None
                line = db.get(models.Line, cam.line_id)
                if line is None or not line.is_active:
                    return None
                meta = _line_meta(db, cam.line_id)
                if meta is None:
                    return None
                stations, line_meta = meta
                info = _camera_info(cam)
            for sid, s in stations.items():
                live.ensure(sid, s.line_id)
            w = CameraWorker(info, stations, line_meta)
            w.initial_delay = initial_delay
            self.workers[camera_id] = w
            w.start()
            return w

    def stop(self, camera_id: int) -> None:
        with self.lock:
            w = self.workers.pop(camera_id, None)
        if w is not None:
            w.stop()
            w.join(timeout=5)
            live.release_camera(camera_id)

    def restart(self, camera_id: int) -> CameraWorker | None:
        return self.start(camera_id)

    def stop_all(self) -> None:
        for cid in list(self.workers):
            w = self.workers.get(cid)
            if w:
                w.stop()
        for cid in list(self.workers):
            w = self.workers.pop(cid, None)
            if w:
                w.join(timeout=5)

    def restart_line(self, line_id: int) -> None:
        for cid in [c for c, w in self.workers.items() if w.info["line_id"] == line_id]:
            self.restart(cid)

    def refresh_line_meta(self, line_id: int) -> None:
        """Station / takt edits: update running workers without restarting them."""
        with SessionLocal() as db:
            meta = _line_meta(db, line_id)
        if meta is None:
            return
        stations, line_meta = meta
        for sid, s in stations.items():
            live.ensure(sid, s.line_id)
        for w in list(self.workers.values()):
            if w.info["line_id"] == line_id:
                w.update_meta(stations, line_meta)

    def get(self, camera_id: int) -> CameraWorker | None:
        return self.workers.get(camera_id)

    def status(self, camera_id: int, enabled: bool = True) -> dict:
        w = self.workers.get(camera_id)
        if w is None:
            return {"online": False, "fps": 0.0, "last_frame_at": None, "error": None if enabled else "camera disabled",
                    "tracker": "none", "width": 0, "height": 0, "needs_reference": False}
        return dict(w.status)

    def running_count(self) -> int:
        return sum(1 for w in self.workers.values() if w.status.get("online"))


manager = CameraManager()
