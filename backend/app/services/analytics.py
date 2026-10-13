"""Cycle-time, line-balance and movement analytics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..hub import live
from ..schemas import (
    CycleStats,
    HistogramBucket,
    HourlyAvg,
    HourlyOutput,
    LineAnalytics,
    MovementRow,
    MovementStats,
    Overview,
    OverviewLine,
    OverviewStation,
    OverviewTotals,
    StationAnalytics,
    StationLive,
    StationSummary,
    TrendPoint,
)
from . import recommendations as recs
from .serializers import camera_ids_by_station, line_out, lines_out, station_out

MIN_CYCLES_FOR_BOTTLENECK = 3


# ------------------------------------------------------------------ ranges
def resolve_range(key: str | None) -> tuple[datetime, datetime]:
    now = datetime.now()
    key = key or "24h"
    if key == "1h":
        return now - timedelta(hours=1), now
    if key == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    if key == "7d":
        return now - timedelta(days=7), now
    if key == "30d":
        return now - timedelta(days=30), now
    return now - timedelta(hours=24), now


def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def shift_windows(line: models.Line, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    end = min(end, datetime.now())
    if end <= start:
        return []
    sh, sm = _hm(line.shift_start)
    eh, em = _hm(line.shift_end)
    out = []
    day = (start - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        ws = day.replace(hour=sh, minute=sm)
        we = day.replace(hour=eh, minute=em)
        if we <= ws:
            we += timedelta(days=1)  # night shift crossing midnight
        a, b = max(ws, start), min(we, end)
        if b > a:
            out.append((a, b))
        day += timedelta(days=1)
    return out


def _overlap_sec(windows: list[tuple[datetime, datetime]], a: datetime, b: datetime) -> float:
    return sum(max(0.0, (min(we, b) - max(ws, a)).total_seconds()) for ws, we in windows)


def _buckets(start: datetime, end: datetime) -> tuple[list[datetime], timedelta]:
    if end - start <= timedelta(hours=48):
        step = timedelta(hours=1)
        first = start.replace(minute=0, second=0, microsecond=0)
    else:
        step = timedelta(days=1)
        first = start.replace(hour=0, minute=0, second=0, microsecond=0)
    out, t = [], first
    while t < end:
        out.append(t)
        t += step
    return out, step


# ------------------------------------------------------------------ rows
@dataclass
class Rows:
    ts: np.ndarray
    cyc: np.ndarray
    work: np.ndarray
    motion: np.ndarray
    wait: np.ndarray
    hand: np.ndarray
    reach: np.ndarray
    walk: np.ndarray
    pick: np.ndarray
    over: np.ndarray
    has_move: np.ndarray

    def __len__(self) -> int:
        return len(self.cyc)

    @property
    def content(self) -> np.ndarray:
        return self.work + self.motion


def _empty_rows() -> Rows:
    z = np.zeros(0)
    return Rows(z, z, z, z, z, z, z, z, z, np.zeros(0, bool), np.zeros(0, bool))


def load_rows(db: Session, start: datetime, end: datetime, line_id: int | None = None, station_id: int | None = None) -> dict[int, Rows]:
    C = models.Cycle
    q = select(C.station_id, C.ended_at, C.cycle_sec, C.work_sec, C.motion_waste_sec, C.wait_sec, C.hand_travel_m,
               C.reach_count, C.walk_m, C.pick_count, C.over_target, C.source).where(C.ended_at >= start, C.ended_at <= end)
    if line_id is not None:
        q = q.where(C.line_id == line_id)
    if station_id is not None:
        q = q.where(C.station_id == station_id)
    q = q.order_by(C.ended_at)
    grouped: dict[int, list] = {}
    for r in db.execute(q).all():
        grouped.setdefault(r[0], []).append(r)
    out: dict[int, Rows] = {}
    for sid, rs in grouped.items():
        cols = list(zip(*rs))
        out[sid] = Rows(
            ts=np.array([t.timestamp() for t in cols[1]]),
            cyc=np.array(cols[2], float),
            work=np.array(cols[3], float),
            motion=np.array(cols[4], float),
            wait=np.array(cols[5], float),
            hand=np.array(cols[6], float),
            reach=np.array(cols[7], float),
            walk=np.array(cols[8], float),
            pick=np.array(cols[9], float),
            over=np.array(cols[10], bool),
            has_move=np.array([s != "manual" for s in cols[11]], bool),
        )
    return out


def _r(v: float | None, n: int = 2) -> float | None:
    if v is None or not np.isfinite(v):
        return None
    return round(float(v), n)


def compute_stats(r: Rows, takt: float) -> CycleStats:
    n = len(r)
    if n == 0:
        return CycleStats()
    c = r.cyc
    avg = float(c.mean())
    std = float(c.std()) if n > 1 else 0.0
    content = r.content
    return CycleStats(
        count=n,
        avg=_r(avg),
        median=_r(np.median(c)),
        p90=_r(np.percentile(c, 90)),
        min=_r(c.min()),
        max=_r(c.max()),
        std=_r(std),
        cv=_r(std / avg if avg > 0 else None, 3),
        avg_work=_r(r.work.mean()),
        avg_motion_waste=_r(r.motion.mean()),
        avg_wait=_r(r.wait.mean()),
        avg_content=_r(content.mean()),
        over_target_pct=_r(r.over.mean() * 100, 1),
        over_takt_pct=_r((content > takt).mean() * 100, 1),
    )


def compute_movement(r: Rows, expected_picks: int) -> MovementStats:
    m = MovementStats(expected_picks=expected_picks)
    if len(r) == 0:
        return m
    total = r.cyc.sum()
    if total > 0:
        m.va_pct = _r(r.work.sum() / total * 100, 1)
        m.motion_waste_pct = _r(r.motion.sum() / total * 100, 1)
        m.wait_pct = _r(r.wait.sum() / total * 100, 1)
    mv = r.has_move
    if mv.any():
        m.avg_hand_travel_m = _r(r.hand[mv].mean())
        m.avg_reach_count = _r(r.reach[mv].mean())
        m.avg_walk_m = _r(r.walk[mv].mean())
        m.avg_pick_count = _r(r.pick[mv].mean())
        extra_picks = max(0.0, float(r.pick[mv].mean()) - expected_picks) if expected_picks > 0 else 0.0
        # ~80% of motion waste is realistically removable (bins closer, tools at point of use), ~1 s per extra pick
        m.est_saving_sec = _r(float(r.motion[mv].mean()) * 0.8 + extra_picks * 1.0, 1)
    return m


def _live_obj(d: dict | None) -> StationLive | None:
    return StationLive(**d) if d else None


def _pick_bottleneck(summaries: list[StationSummary]) -> StationSummary | None:
    cands = [s for s in summaries if s.stats.count >= MIN_CYCLES_FOR_BOTTLENECK and s.stats.avg_content is not None]
    if not cands:
        return None
    return max(cands, key=lambda s: s.stats.avg_content or 0)


# ------------------------------------------------------------------ line
def compute_line(db: Session, line: models.Line, start: datetime, end: datetime, with_recs: bool = True,
                 rows: dict[int, Rows] | None = None) -> LineAnalytics:
    stations = db.scalars(select(models.Station).where(models.Station.line_id == line.id).order_by(models.Station.sequence)).all()
    stations = [s for s in stations if s.is_active]
    if rows is None:
        rows = load_rows(db, start, end, line_id=line.id)
    cam_map = camera_ids_by_station(db, line.id)
    live_map = live.as_map()
    summaries: list[StationSummary] = []
    for s in stations:
        r = rows.get(s.id, _empty_rows())
        summaries.append(StationSummary(
            station=station_out(s, cam_map),
            stats=compute_stats(r, line.takt_time_sec),
            movement=compute_movement(r, s.expected_picks),
            is_bottleneck=False,
            live=_live_obj(live_map.get(s.id)),
        ))
    bn = _pick_bottleneck(summaries)
    if bn:
        bn.is_bottleneck = True
    contents = [s.stats.avg_content for s in summaries if s.stats.count >= MIN_CYCLES_FOR_BOTTLENECK and s.stats.avg_content]
    balance = _r(sum(contents) / (len(contents) * max(contents)) * 100, 1) if contents else None

    # output = units finished by the last step that has data
    last = next((s for s in reversed(summaries) if s.stats.count > 0), None)
    last_rows = rows.get(last.station.id, _empty_rows()) if last else _empty_rows()
    output = len(last_rows)
    windows = shift_windows(line, start, end)
    shift_sec = _overlap_sec(windows, start, end)
    planned = _r(shift_sec / line.takt_time_sec, 1) or 0.0
    hours = shift_sec / 3600 if shift_sec > 0 else (end - start).total_seconds() / 3600
    throughput = _r(output / hours, 1) if hours > 0 and output else None
    capacity = _r(3600 / bn.stats.avg_content, 1) if bn and bn.stats.avg_content else None

    buckets, step = _buckets(start, end)
    hourly = []
    for b in buckets:
        e = b + step
        cnt = int(((last_rows.ts >= b.timestamp()) & (last_rows.ts < e.timestamp())).sum()) if output else 0
        hourly.append(HourlyOutput(hour=b, output=cnt, planned=round(_overlap_sec(windows, max(b, start), min(e, end)) / line.takt_time_sec, 1)))

    la = LineAnalytics(
        line=line_out(db, line),
        from_=start,
        to=end,
        stations=summaries,
        bottleneck_station_id=bn.station.id if bn else None,
        balance_efficiency_pct=balance,
        output=output,
        planned_output=planned,
        throughput_per_hour=throughput,
        capacity_per_hour=capacity,
        hourly=hourly,
        recommendations=[],
    )
    if with_recs:
        la.recommendations = recs.for_line(la)
    return la


# ------------------------------------------------------------------ station
def _downsample(r: Rows, max_points: int = 300) -> list[TrendPoint]:
    n = len(r)
    if n == 0:
        return []
    if n <= max_points:
        return [TrendPoint(t=datetime.fromtimestamp(r.ts[i]), cycle_sec=round(r.cyc[i], 2), work_sec=round(r.work[i], 2),
                           motion_waste_sec=round(r.motion[i], 2), wait_sec=round(r.wait[i], 2)) for i in range(n)]
    pts = []
    for idx in np.array_split(np.arange(n), max_points):
        if len(idx) == 0:
            continue
        pts.append(TrendPoint(t=datetime.fromtimestamp(float(r.ts[idx].mean())), cycle_sec=round(float(r.cyc[idx].mean()), 2),
                              work_sec=round(float(r.work[idx].mean()), 2), motion_waste_sec=round(float(r.motion[idx].mean()), 2),
                              wait_sec=round(float(r.wait[idx].mean()), 2)))
    return pts


def _histogram(values: np.ndarray, bins: int = 20) -> list[HistogramBucket]:
    if len(values) == 0:
        return []
    lo = float(np.floor(values.min()))
    hi = float(np.ceil(np.percentile(values, 99)))
    if hi - lo < 1:
        hi = lo + 1
    counts, edges = np.histogram(np.clip(values, lo, hi), bins=bins, range=(lo, hi))
    return [HistogramBucket(bucket_start=round(float(edges[i]), 2), bucket_end=round(float(edges[i + 1]), 2), count=int(counts[i])) for i in range(len(counts))]


def compute_station(db: Session, station: models.Station, start: datetime, end: datetime) -> StationAnalytics:
    line = db.get(models.Line, station.line_id)
    assert line is not None
    la = compute_line(db, line, start, end, with_recs=False)
    summary = next((s for s in la.stations if s.station.id == station.id), None)
    cam_map = camera_ids_by_station(db, line.id)
    all_st = db.scalars(select(models.Station).where(models.Station.line_id == line.id, models.Station.is_active.is_(True))
                        .order_by(models.Station.sequence)).all()
    idx = next((i for i, s in enumerate(all_st) if s.id == station.id), None)
    prev_s = all_st[idx - 1] if idx is not None and idx > 0 else None
    next_s = all_st[idx + 1] if idx is not None and idx + 1 < len(all_st) else None
    r = load_rows(db, start, end, station_id=station.id).get(station.id, _empty_rows())
    stats = summary.stats if summary else compute_stats(r, line.takt_time_sec)
    movement = summary.movement if summary else compute_movement(r, station.expected_picks)
    buckets, step = _buckets(start, end)
    hourly = []
    for b in buckets:
        e = b + step
        mask = (r.ts >= b.timestamp()) & (r.ts < e.timestamp()) if len(r) else np.zeros(0, bool)
        cnt = int(mask.sum()) if len(r) else 0
        hourly.append(HourlyAvg(hour=b, avg=_r(r.cyc[mask].mean()) if cnt else None, count=cnt))
    sa = StationAnalytics(
        station=station_out(station, cam_map),
        line=la.line,
        prev_station=station_out(prev_s, cam_map) if prev_s else None,
        next_station=station_out(next_s, cam_map) if next_s else None,
        from_=start,
        to=end,
        stats=stats,
        movement=movement,
        is_bottleneck=bool(summary and summary.is_bottleneck),
        trend=_downsample(r),
        histogram=_histogram(r.cyc),
        hourly=hourly,
        recommendations=[],
        live=_live_obj(live.get(station.id)),
    )
    sa.recommendations = recs.for_station(la, station.id)
    return sa


# ------------------------------------------------------------------ overview / movement
def compute_overview(db: Session, start: datetime, end: datetime) -> Overview:
    from ..vision.manager import manager

    lines = db.scalars(select(models.Line).order_by(models.Line.id)).all()
    rows_all = load_rows(db, start, end)
    open_alerts = db.execute(select(models.Alert.line_id).where(models.Alert.acknowledged.is_(False))).scalars().all()
    out_lines = []
    tot_out, tot_plan, n_st = 0, 0.0, 0
    for line in lines:
        la = compute_line(db, line, start, end, with_recs=False, rows=rows_all)
        bn = next((s for s in la.stations if s.is_bottleneck), None)
        n_st += len(la.stations)
        ol = OverviewLine(
            line=la.line,
            output=la.output,
            planned_output=la.planned_output,
            balance_efficiency_pct=la.balance_efficiency_pct,
            bottleneck_station_id=la.bottleneck_station_id,
            bottleneck_station_name=f"Step {bn.station.sequence}: {bn.station.name}" if bn else None,
            line_pace_sec=bn.stats.avg_content if bn else None,
            stations=[OverviewStation(
                id=s.station.id, name=s.station.name, sequence=s.station.sequence, avg_sec=s.stats.avg,
                avg_content_sec=s.stats.avg_content, target_cycle_sec=s.station.target_cycle_sec,
                state=s.live.state if s.live else "no_camera", is_bottleneck=s.is_bottleneck,
            ) for s in la.stations],
            open_alerts=sum(1 for lid in open_alerts if lid == line.id),
        )
        out_lines.append(ol)
        if line.is_active:
            tot_out += la.output
            tot_plan += la.planned_output
    cams = db.scalars(select(models.Camera.id)).all()
    return Overview(
        from_=start,
        to=end,
        lines=out_lines,
        totals=OverviewTotals(
            output=tot_out, planned_output=round(tot_plan, 1), cameras_online=sum(1 for c in cams if manager.status(c).get("online")),
            cameras_total=len(cams), open_alerts=len(open_alerts), stations=n_st, lines=len(lines),
        ),
    )


def compute_movement_rows(db: Session, start: datetime, end: datetime, line_id: int | None = None) -> list[MovementRow]:
    q = select(models.Line)
    if line_id is not None:
        q = q.where(models.Line.id == line_id)
    out = []
    rows_all = load_rows(db, start, end, line_id=line_id)
    for line in db.scalars(q).all():
        sts = db.scalars(select(models.Station).where(models.Station.line_id == line.id, models.Station.is_active.is_(True))
                         .order_by(models.Station.sequence)).all()
        for s in sts:
            r = rows_all.get(s.id, _empty_rows())
            st = compute_stats(r, line.takt_time_sec)
            out.append(MovementRow(station_id=s.id, station_name=s.name, sequence=s.sequence, line_id=line.id, line_name=line.name,
                                   cycles=len(r), avg_cycle_sec=st.avg, avg_content_sec=st.avg_content,
                                   movement=compute_movement(r, s.expected_picks)))
    out.sort(key=lambda m: -(m.movement.est_saving_sec or 0))
    return out


def lines_list(db: Session) -> list:
    return lines_out(db, db.scalars(select(models.Line).order_by(models.Line.id)).all())
