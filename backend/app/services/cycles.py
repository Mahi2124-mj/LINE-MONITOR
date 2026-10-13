from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from ..database import session_scope
from ..hub import hub, live
from .. import models
from ..schemas import CycleOut
from . import alerts

if TYPE_CHECKING:
    from ..vision.analyzers import CycleDraft
    from ..vision.worker import LineMeta, StationMeta


def persist_cycle(d: "CycleDraft", camera_id: int | None, meta: "StationMeta", line: "LineMeta", source: str) -> CycleOut:
    content = d.work_sec + d.motion_waste_sec
    row = models.Cycle(
        station_id=d.station_id,
        line_id=meta.line_id,
        camera_id=camera_id,
        started_at=datetime.fromtimestamp(d.started_ts),
        ended_at=datetime.fromtimestamp(d.ended_ts),
        cycle_sec=round(d.cycle_sec, 2),
        work_sec=round(d.work_sec, 2),
        motion_waste_sec=round(d.motion_waste_sec, 2),
        wait_sec=round(d.wait_sec, 2),
        hand_travel_m=round(d.hand_travel_m, 2),
        reach_count=int(d.reach_count),
        walk_m=round(d.walk_m, 2),
        pick_count=int(d.pick_count),
        source=source,
        over_target=content > meta.target_cycle_sec,
        track=d.track,
    )
    with session_scope() as db:
        db.add(row)
        db.flush()
        out = CycleOut.model_validate(row)
    live.record_cycle(d.station_id, d.cycle_sec, d.ended_ts)
    hub.publish("cycle", out.model_dump(mode="json"))
    if content > meta.target_cycle_sec * 1.5:
        alerts.create_alert(
            "slow_cycle",
            "warning",
            f"{line.name} · Step {meta.sequence} {meta.name}: slow cycle {content:.1f}s (target {meta.target_cycle_sec:.0f}s)",
            line_id=meta.line_id,
            station_id=meta.id,
            camera_id=camera_id,
            dedupe_min=10,
        )
    return out
