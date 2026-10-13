"""Alert creation (deduplicated) and the periodic alert engine."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from ..database import SessionLocal, session_scope
from ..hub import hub, live
from .. import models
from ..schemas import AlertOut

log = logging.getLogger(__name__)


def create_alert(
    type_: str,
    severity: str,
    message: str,
    line_id: int | None = None,
    station_id: int | None = None,
    camera_id: int | None = None,
    dedupe_min: float = 10,
) -> AlertOut | None:
    since = datetime.now() - timedelta(minutes=dedupe_min)
    with session_scope() as db:
        q = select(models.Alert.id).where(
            models.Alert.type == type_,
            models.Alert.created_at >= since,
            models.Alert.line_id.is_(None) if line_id is None else models.Alert.line_id == line_id,
            models.Alert.station_id.is_(None) if station_id is None else models.Alert.station_id == station_id,
            models.Alert.camera_id.is_(None) if camera_id is None else models.Alert.camera_id == camera_id,
        )
        if db.scalar(q.limit(1)) is not None:
            return None
        a = models.Alert(type=type_, severity=severity, message=message, line_id=line_id, station_id=station_id, camera_id=camera_id)
        db.add(a)
        db.flush()
        out = AlertOut.model_validate(a)
    hub.publish("alert", out.model_dump(mode="json"))
    return out


class AlertEngine:
    INTERVAL = 20.0
    LINE_CHECK_EVERY = 300.0

    def __init__(self) -> None:
        self.offline_since: dict[int, float] = {}
        self.last_line_check = 0.0
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(30)  # let cameras connect first
        while True:
            try:
                await asyncio.to_thread(self.check)
            except Exception:
                log.exception("alert engine error")
            await asyncio.sleep(self.INTERVAL)

    def check(self) -> None:
        from ..vision.manager import manager

        now = time.time()
        with SessionLocal() as db:
            cams = db.scalars(select(models.Camera).where(models.Camera.enabled.is_(True))).all()
            stations = {s.id: s for s in db.scalars(select(models.Station)).all()}
            lines = {l.id: l for l in db.scalars(select(models.Line)).all()}

        # cameras offline > 30 s
        for c in cams:
            if manager.get(c.id) is None:  # not running (line paused)
                self.offline_since.pop(c.id, None)
                continue
            st = manager.status(c.id)
            if st.get("online"):
                self.offline_since.pop(c.id, None)
                continue
            since = self.offline_since.setdefault(c.id, now)
            if now - since >= 30:
                err = st.get("error") or "no video"
                create_alert("camera_offline", "critical", f"Camera '{c.name}' offline: {err}", line_id=c.line_id,
                             station_id=c.station_id, camera_id=c.id, dedupe_min=60)

        # stoppage: a station that has the part / operator but has not finished a cycle for long
        for s in live.snapshot():
            meta = stations.get(s["station_id"])
            el = s["cycle_elapsed_sec"]
            if meta is None or el is None or s["state"] not in ("working", "idle"):
                continue
            limit = max(3 * meta.target_cycle_sec, 180.0)
            if el > limit:
                line = lines.get(meta.line_id)
                create_alert("stoppage", "warning",
                             f"{line.name if line else 'Line'} · Step {meta.sequence} {meta.name}: no cycle completed for {int(el // 60)}m {int(el % 60):02d}s",
                             line_id=meta.line_id, station_id=meta.id, dedupe_min=15)

        if now - self.last_line_check >= self.LINE_CHECK_EVERY:
            self.last_line_check = now
            self._line_checks(lines)

    def _line_checks(self, lines: dict[int, models.Line]) -> None:
        from .analytics import compute_line

        end = datetime.now()
        start = end - timedelta(hours=1)
        with SessionLocal() as db:
            for line in lines.values():
                if not line.is_active:
                    continue
                la = compute_line(db, line, start, end, with_recs=False)
                bn = next((s for s in la.stations if s.is_bottleneck), None)
                if bn and bn.stats.avg_content and bn.stats.avg_content > line.takt_time_sec:
                    create_alert("over_takt", "warning",
                                 f"{line.name}: bottleneck Step {bn.station.sequence} {bn.station.name} needs {bn.stats.avg_content:.1f}s > takt {line.takt_time_sec:.0f}s — line cannot meet demand",
                                 line_id=line.id, station_id=bn.station.id, dedupe_min=60)
                if la.balance_efficiency_pct is not None and la.balance_efficiency_pct < 70:
                    create_alert("unbalanced", "info", f"{line.name}: line balance efficiency only {la.balance_efficiency_pct:.0f}% — redistribute work between steps",
                                 line_id=line.id, dedupe_min=240)
                for s in la.stations:
                    mv = s.movement
                    if s.stats.count >= 10 and ((mv.avg_reach_count or 0) >= 1.5 or (mv.avg_walk_m or 0) >= 2.0):
                        create_alert("excess_motion", "info",
                                     f"{line.name} · Step {s.station.sequence} {s.station.name}: {mv.avg_reach_count or 0:.1f} reaches & {mv.avg_walk_m or 0:.1f} m walking per cycle",
                                     line_id=line.id, station_id=s.station.id, dedupe_min=240)


engine = AlertEngine()
