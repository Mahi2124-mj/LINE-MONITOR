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
        self.last_bottleneck: dict[int, str] = {}  # line id -> bottleneck person at the last line check
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

        # stoppage: a station that has the part / operator but has not finished a cycle for long. Steps counted by the
        # step detectors get their stoppage alerts from services/detector_feed.py (the live timer misses their cycles)
        from .detector_feed import feed

        for s in live.snapshot():
            if feed.owns(s["station_id"]):
                continue
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
        from .detector_feed import feed

        end = datetime.now()
        start = end - timedelta(hours=1)
        with SessionLocal() as db:
            for line in lines.values():
                if not line.is_active:
                    continue
                la = compute_line(db, line, start, end, with_recs=False)
                # a new bottleneck person (last hour): warning when he is slower than takt, else info. Only when every
                # person has enough cycles up to now (the live count of some steps comes minutes late, or is catching up)
                fresh = end - timedelta(minutes=15)
                timed = [o for o in la.operators if o.per_part_sec and o.count >= 10 and o.last_cycle_at and o.last_cycle_at >= fresh]
                if la.bottleneck_label and la.line_pace_sec and len(timed) >= 2 and len(timed) == len(la.operators):  # everyone timed
                    # only a clear bottleneck: in a well balanced line the slowest person changes every few minutes
                    per = sorted((o.per_part_sec or 0.0 for o in timed), reverse=True)
                    clear = per[0] - per[1] >= max(0.3, 0.02 * per[0])
                    if clear and self.last_bottleneck.get(line.id) != la.bottleneck_label:
                        over = la.line_pace_sec > line.takt_time_sec
                        create_alert("bottleneck", "warning" if over else "info",
                                     f"{la.bottleneck_label} is now the bottleneck: {la.line_pace_sec:.1f} s per part",
                                     line_id=line.id, station_id=la.bottleneck_station_id, dedupe_min=60)
                        self.last_bottleneck[line.id] = la.bottleneck_label
                if la.line_pace_sec and la.line_pace_sec > line.takt_time_sec and len(timed) == len(la.operators):
                    create_alert("over_takt", "warning",
                                 f"{la.bottleneck_label} needs {la.line_pace_sec:.1f} s per part, takt is {line.takt_time_sec:.1f} s",
                                 line_id=line.id, station_id=la.bottleneck_station_id, dedupe_min=60)
                if la.balance_efficiency_pct is not None and la.balance_efficiency_pct < 70:
                    create_alert("unbalanced", "info", f"{line.name}: line balance efficiency only {la.balance_efficiency_pct:.0f}% — redistribute work between operators",
                                 line_id=line.id, dedupe_min=240)
                for s in la.stations:
                    mv = s.movement
                    if feed.owns(s.station.id):
                        continue
                    if s.stats.count >= 10 and ((mv.avg_reach_count or 0) >= 1.5 or (mv.avg_walk_m or 0) >= 2.0):
                        create_alert("excess_motion", "info",
                                     f"{line.name} · Step {s.station.sequence} {s.station.name}: {mv.avg_reach_count or 0:.1f} reaches & {mv.avg_walk_m or 0:.1f} m walking per cycle",
                                     line_id=line.id, station_id=s.station.id, dedupe_min=240)


engine = AlertEngine()
