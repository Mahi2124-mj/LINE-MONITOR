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
    ShiftResult,
    CycleStats,
    HistogramBucket,
    HourlyAvg,
    HourlyOutput,
    LineAnalytics,
    MovementRow,
    MovementStats,
    OperatorBalance,
    Overview,
    OverviewLine,
    OverviewStation,
    OverviewTotals,
    SlotRow,
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
    if key in ("shiftA", "shiftB"):  # the newest run of that shift (started, up to now)
        w = shift_window(key[-1], now)
        return w if w else (now.replace(hour=0, minute=0, second=0, microsecond=0), now)
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


SHIFT_GAP = timedelta(minutes=45)  # a gap this long between two slots starts the next shift (A, then B, ...)


def _slot_rows(line: models.Line, day: datetime) -> list[tuple[datetime, datetime, int, str, str]]:
    """the line's planned time slots of one production day: (start, end, plan, "08:30-09:30", shift); none on a
    non-working day. The slots are in shift order from the day's first slot (day shift, then night shift): a slot that
    starts earlier than the one before it is after midnight, on the next calendar day, and still belongs to this
    production day. A slot's shift is the one it names, else A for the first and the next letter after each gap of
    SHIFT_GAP or more."""
    if day.strftime("%Y-%m-%d") in (line.off_days or []):
        return []
    out, prev, later, end, k = [], None, timedelta(0), None, 0
    for sl in line.slot_plan or []:
        (h0, m0), (h1, m1) = _hm(sl["start"]), _hm(sl["end"])
        if prev is not None and h0 * 60 + m0 < prev:
            later = timedelta(days=1)
        prev = h0 * 60 + m0
        a = day.replace(hour=h0, minute=m0, second=0, microsecond=0) + later
        b = day.replace(hour=h1, minute=m1, second=0, microsecond=0) + later
        if b <= a:
            b += timedelta(days=1)  # a slot crossing midnight
        if end is not None and a - end >= SHIFT_GAP:
            k += 1
        end = b
        name = (sl.get("shift") or "").strip() or "ABCDEFGH"[min(k, 7)]
        out.append((a, b, int(sl["plan"]), f"{sl['start']}-{sl['end']}", name))
    return sorted(out)


def _slots_of_day(line: models.Line, day: datetime) -> list[tuple[datetime, datetime, int, str]]:
    """the line's planned time slots of one production day: (start, end, plan, "08:30-09:30") (see _slot_rows)"""
    return [r[:4] for r in _slot_rows(line, day)]


def _shift_run(line: models.Line, name: str, now: datetime) -> list[tuple[datetime, datetime, int, str, str]]:
    """the slots of the newest run of shift <name> of the line that has started by now (non-working days skipped)"""
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for back in range(8):
        rows = [r for r in _slot_rows(line, today - timedelta(days=back)) if r[4] == name]
        if rows and rows[0][0] <= now:
            return rows
    return []


def shift_window(name: str, now: datetime | None = None) -> tuple[datetime, datetime] | None:
    """the newest run of shift <name> over the active lines: (its first slot start, its last slot end, not beyond now)"""
    from ..database import SessionLocal

    now = now or datetime.now()
    with SessionLocal() as db:
        lines = [ln for ln in db.scalars(select(models.Line)) if ln.is_active and ln.slot_plan]
    best = None
    for ln in lines:
        rows = _shift_run(ln, name, now)
        if rows and (best is None or rows[0][0] > best[0]):
            best = (rows[0][0], min(rows[-1][1], now))
    return best


def slots_between(line: models.Line, start: datetime, end: datetime) -> list[tuple[datetime, datetime, int, str]]:
    out = []
    day = (start - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        out += [w for w in _slots_of_day(line, day) if w[1] > start and w[0] < end]
        day += timedelta(days=1)
    return out


def planned_between(line: models.Line, a: datetime, b: datetime) -> float:
    """planned output from a to b (not beyond now): each slot's plan in proportion to its elapsed time, or takt × shift"""
    b = min(b, datetime.now())
    if b <= a:
        return 0.0
    if line.slot_plan:
        return sum(plan * max(0.0, (min(we, b) - max(ws, a)).total_seconds()) / (we - ws).total_seconds()
                   for ws, we, plan, _ in slots_between(line, a, b))
    return _overlap_sec(shift_windows(line, a, b), a, b) / line.takt_time_sec


def shift_windows(line: models.Line, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    end = min(end, datetime.now())
    if end <= start:
        return []
    if line.slot_plan:  # the working time is the planned slots
        return [(max(ws, start), min(we, end)) for ws, we, _, _ in slots_between(line, start, end) if min(we, end) > max(ws, start)]
    sh, sm = _hm(line.shift_start)
    eh, em = _hm(line.shift_end)
    out = []
    day = (start - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end:
        if day.strftime("%Y-%m-%d") in (line.off_days or []):  # no production on a non-working day
            day += timedelta(days=1)
            continue
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
    from .detector_feed import feed

    grouped: dict[int, list] = {}
    for r in db.execute(q).all():
        if r[11] == "vision" and feed.owns(r[0]):  # a step counted by its validated detector: the generic count merged cycles
            continue
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
            has_move=np.array([s not in ("manual", "detector") for s in cols[11]], bool),  # no hand / walk tracking
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
    # the work split (and so the content used for bottleneck / balance) comes from the normal cycles: a line stop or a
    # break inside one cycle is not work content of the step
    ok = c <= max(45.0, 2.5 * float(np.median(c)))
    if ok.sum() < 3:
        ok = np.ones(n, bool)
    return CycleStats(
        count=n,
        avg=_r(avg),
        median=_r(np.median(c)),
        p90=_r(np.percentile(c, 90)),
        min=_r(c.min()),
        max=_r(c.max()),
        std=_r(std),
        cv=_r(std / avg if avg > 0 else None, 3),
        avg_work=_r(r.work[ok].mean()),
        avg_motion_waste=_r(r.motion[ok].mean()),
        avg_wait=_r(r.wait[ok].mean()),
        avg_content=_r(content[ok].mean()),
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


def operator_groups(summaries: list[StationSummary]) -> list[OperatorBalance]:
    """The line balance per PERSON: steps with the same operator name are one person's loop, every other step is its own
    operator. Each step of a loop cycles once per loop, so the loop = the average over his steps. Copies of one machine
    (same parallel group) each take every n-th part, so his time per part = loop / copies (Guide S/A Insert #1 + #2)."""
    copies: dict[str, int] = {}
    for s in summaries:
        if s.station.parallel_group:
            copies[s.station.parallel_group] = copies.get(s.station.parallel_group, 0) + 1
    groups: dict[str, list[StationSummary]] = {}
    for s in summaries:
        groups.setdefault(s.station.operator_name.strip() or f"\0{s.station.id}", []).append(s)
    out = []
    for key, members in groups.items():
        members.sort(key=lambda s: s.station.sequence)
        data = [s for s in members if s.stats.count >= MIN_CYCLES_FOR_BOTTLENECK and s.stats.avg_content is not None]
        # a loop over a stage with n copies makes n parts; a loop that also covers a single-copy stage makes one
        k = min((copies.get(s.station.parallel_group, 1) if s.station.parallel_group else 1) for s in members)
        # weighted by cycles: a step he works at only for some parts (YRA Pop Rivet Gun: inner rails) counts less
        w = sum(s.stats.count for s in data)
        mean = lambda f: (sum((f(s) or 0.0) * s.stats.count for s in data) / w) if data and w else None  # noqa: E731
        loop_content = mean(lambda s: s.stats.avg_content)
        steps = "+".join(str(s.station.sequence) for s in members)
        label = (f"{key} (steps {steps})" if len(members) > 1 else f"{key} (step {steps})") if not key.startswith("\0") \
            else f"Step {steps}: {members[0].station.name}"
        out.append(OperatorBalance(
            label=label, station_ids=[s.station.id for s in members], sequences=[s.station.sequence for s in members],
            count=max((s.stats.count for s in members), default=0),
            loop_sec=_r(mean(lambda s: s.stats.avg)), loop_content_sec=_r(loop_content), parts_per_loop=k,
            per_part_sec=_r(loop_content / k) if loop_content is not None else None,
            work_sec=_r(mean(lambda s: s.stats.avg_work) / k) if data else None,
            motion_sec=_r(mean(lambda s: s.stats.avg_motion_waste) / k) if data else None,
            wait_sec=_r(mean(lambda s: s.stats.avg_wait) / k) if data else None,
        ))
    out.sort(key=lambda o: min(o.sequences))
    return out


def parts_counter(stations: list, rows: dict[int, Rows]):
    """count(a, b) -> parts finished between a and b, per 10 minutes: the median count of the line's last three people
    (the final machine and the two before it; there are no buffers between them, so they make the same parts within a
    few, and one detector that loses or adds parts cannot move it). Checked against the final machine's own counter on
    2026-10-21 11:30-16:05: 881 vs 877 (the final machine's detector alone: 899). A person whose count is incomplete there
    for over a minute (no video: camera offline, server restart; or a block the detector feed left out) is not counted;
    when fewer than two of the last three are complete, the median of all complete people of the line; when nobody is
    complete, the highest count of the people recorded at least half of the time (a lost cycle is far more common than a
    false one). A person = the steps with one operator name; his count = the most parts any of his steps made (a step
    used only for some parts, like the Pop Rivet Gun for inner rails, does not lower it), copies of one machine
    (parallel group) added up."""
    from .detector_feed import missing_times

    people: dict[str, list] = {}
    for s in stations:
        people.setdefault(s.operator_name.strip() or f"\0{s.id}", []).append(s)
    order = sorted(people.values(), key=lambda g: max(x.sequence for x in g))
    have = [g for g in order if any(len(rows.get(x.id, _empty_rows())) for x in g)]
    ts = {x.id: np.sort(rows.get(x.id, _empty_rows()).ts) for g in have for x in g}
    missing = missing_times()

    def n(sid: int, a: float, b: float) -> int:
        return int(np.searchsorted(ts[sid], b) - np.searchsorted(ts[sid], a))

    def person(g: list, a: float, b: float) -> int:
        stages: dict[str, int] = {}
        for x in g:
            key = x.parallel_group or f"\0{x.id}"
            stages[key] = stages.get(key, 0) + n(x.id, a, b)
        return max(stages.values())

    def lost(g: list, a: float, b: float, miss: dict) -> float:
        """seconds of [a, b] the person's count is incomplete: that of his best step (copies of one machine all needed)"""
        stages: dict[str, float] = {}
        for x in g:
            key = x.parallel_group or f"\0{x.id}"
            sec = sum(max(0.0, min(y, b) - max(x0, a)) for x0, y in miss.get(x.id, ()))
            stages[key] = max(stages.get(key, 0.0), sec)
        return min(stages.values())

    def count(a: datetime, b: datetime) -> int:
        t, tb, total = a.timestamp(), b.timestamp(), 0.0
        miss = {sid: [(x, y) for x, y in iv if y > t and x < tb] for sid, iv in missing.items()}
        while t < tb:
            u = min(tb, (t // 600 + 1) * 600)  # 10-minute blocks on the clock
            gone = {id(g): lost(g, t, u, miss) for g in have}
            ok = [g for g in have if gone[id(g)] <= 0.1 * (u - t)]
            end = [g for g in have[-3:] if g in ok]
            use = end if len(end) >= 2 else ok  # one detector alone is not trusted
            if use:
                total += float(np.median([person(g, t, u) for g in use]))
            else:  # nobody complete (every camera off, server restart): the best of the partly recorded, at least that many
                part = [person(g, t, u) for g in have if gone[id(g)] < 0.5 * (u - t)]
                total += float(max(part, default=0))
            t = u
        return int(round(total))

    return count


def slots_today(db: Session, line: models.Line, stations: list, shift: str | None = None) -> list[SlotRow]:
    """today's plan vs actual per time slot; actual = parts finished (see parts_counter). Until today's first slot the
    production day before (its night shift after midnight, then its result for a few hours). shift "A": only the slots
    of the newest run of that shift."""
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if shift:
        sl = _shift_run(line, shift, now)
    else:
        sl = _slot_rows(line, today)
        before = _slot_rows(line, today - timedelta(days=1))
        if before and (not sl or now < sl[0][0]) and now < before[-1][1] + timedelta(hours=6):
            sl = before
    if not sl:
        return []
    count = parts_counter(stations, load_rows(db, sl[0][0], min(now, sl[-1][1]), line_id=line.id))
    out = []
    for ws, we, plan, label, name in sl:
        if now < ws:
            out.append(SlotRow(label=label, start=ws, end=we, plan=plan, plan_to_now=0.0, actual=None, variance=None, status="future",
                               shift=name))
            continue
        done = now >= we
        to_now = float(plan) if done else plan * (now - ws).total_seconds() / (we - ws).total_seconds()
        actual = count(ws, min(we, now))
        out.append(SlotRow(label=label, start=ws, end=we, plan=plan, plan_to_now=round(to_now, 1), actual=actual,
                           variance=round(actual - to_now, 1), status="done" if done else "running", shift=name))
    return out


def shift_results(db: Session, line: models.Line, stations: list) -> list[ShiftResult]:
    """the newest run of each shift of the line that has started (A morning, B night): parts finished in its time slots
    vs its plan up to now (or to its end), newest first"""
    if not line.slot_plan or not line.is_active:
        return []
    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    names: list[str] = []
    for back in range(8):  # the shift names of the plan (a non-working day has none)
        names = sorted({r[4] for r in _slot_rows(line, today - timedelta(days=back))})
        if names:
            break
    runs = [(n, r) for n in names if (r := _shift_run(line, n, now))]
    if not runs:
        return []
    count = parts_counter(stations, load_rows(db, min(r[0][0] for _, r in runs), now, line_id=line.id))
    out = []
    for n, r in runs:
        start, end = r[0][0], r[-1][1]
        output = sum(count(ws, min(we, now)) for ws, we, *_ in r if ws < now)
        out.append(ShiftResult(name=n, start=start, end=end, output=output, planned_output=round(planned_between(line, start, min(end, now)), 1),
                               running=start <= now < end))
    return sorted(out, key=lambda x: x.start, reverse=True)


# ------------------------------------------------------------------ line
def compute_line(db: Session, line: models.Line, start: datetime, end: datetime, with_recs: bool = True,
                 rows: dict[int, Rows] | None = None, shift: str | None = None) -> LineAnalytics:
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
    # balance and bottleneck per person (see operator_groups): Σ time per part / (people × slowest person's time per part)
    operators = operator_groups(summaries)
    for o in operators:
        ends = [rows[sid].ts[-1] for sid in o.station_ids if sid in rows and len(rows[sid])]
        o.last_cycle_at = datetime.fromtimestamp(max(ends)) if ends else None
    timed = [o for o in operators if o.per_part_sec]
    bn_op = max(timed, key=lambda o: o.per_part_sec or 0.0) if timed else None
    balance = _r(sum(o.per_part_sec or 0.0 for o in timed) / (len(timed) * bn_op.per_part_sec) * 100, 1) if bn_op else None
    bn = None
    if bn_op:
        bn_op.is_bottleneck = True
        for s in summaries:
            if s.station.id in bn_op.station_ids:
                s.is_bottleneck = True
        # the step of his loop with the most work stands for him where one step is needed (alerts, links)
        bn = max((s for s in summaries if s.station.id in bn_op.station_ids), key=lambda s: s.stats.avg_content or 0.0)

    # output = parts finished: the median count of the line's last three people, per 10 minutes (see parts_counter)
    count_in = parts_counter(stations, rows)
    output = count_in(start, end)
    outside = 0
    if line.slot_plan:  # compared with the plan: the parts of the planned time slots; a night shift etc. is shown apart
        made = output
        output = sum(count_in(max(ws, start), min(we, end)) for ws, we, _, _ in slots_between(line, start, end) if min(we, end) > max(ws, start))
        outside = max(0, made - output)
    windows = shift_windows(line, start, end)
    shift_sec = _overlap_sec(windows, start, end)
    planned = _r(planned_between(line, start, end), 1) or 0.0
    hours = shift_sec / 3600 if shift_sec > 0 else (end - start).total_seconds() / 3600
    throughput = _r(output / hours, 1) if hours > 0 and output else None
    capacity = _r(3600 / bn_op.per_part_sec, 1) if bn_op and bn_op.per_part_sec else None

    hourly = []
    if line.slot_plan and end - start <= timedelta(hours=48):  # the line's own time slots instead of clock hours
        for ws, we, _, label in slots_between(line, start, min(end, datetime.now())):
            hourly.append(HourlyOutput(hour=ws, end=we, label=label, output=count_in(max(ws, start), min(we, end)),
                                       planned=round(planned_between(line, max(ws, start), min(we, end)), 1)))
    else:
        buckets, step = _buckets(start, end)
        for b in buckets:
            e = b + step
            hourly.append(HourlyOutput(hour=b, output=count_in(b, e), planned=round(planned_between(line, max(b, start), min(e, end)), 1)))
    slots = slots_today(db, line, [s.station for s in summaries], shift) if with_recs else []

    la = LineAnalytics(
        line=line_out(db, line),
        from_=start,
        to=end,
        stations=summaries,
        operators=operators,
        bottleneck_station_id=bn.station.id if bn else None,
        bottleneck_label=bn_op.label if bn_op else None,
        line_pace_sec=bn_op.per_part_sec if bn_op else None,
        balance_efficiency_pct=balance,
        output=output,
        output_outside_plan=outside,
        planned_output=planned,
        throughput_per_hour=throughput,
        capacity_per_hour=capacity,
        hourly=hourly,
        slots_today=slots,
        shifts=shift_results(db, line, stations),
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
    tot_out, tot_plan, tot_outside, n_st = 0, 0.0, 0, 0
    for line in lines:
        la = compute_line(db, line, start, end, with_recs=False, rows=rows_all)
        n_st += len(la.stations)
        ol = OverviewLine(
            line=la.line,
            output=la.output,
            output_outside_plan=la.output_outside_plan,
            planned_output=la.planned_output,
            balance_efficiency_pct=la.balance_efficiency_pct,
            bottleneck_station_id=la.bottleneck_station_id,
            bottleneck_station_name=la.bottleneck_label,
            line_pace_sec=la.line_pace_sec,
            stations=[OverviewStation(
                id=s.station.id, name=s.station.name, sequence=s.station.sequence, avg_sec=s.stats.avg,
                avg_content_sec=s.stats.avg_content, target_cycle_sec=s.station.target_cycle_sec,
                state=s.live.state if s.live else "no_camera", is_bottleneck=s.is_bottleneck,
            ) for s in la.stations],
            open_alerts=sum(1 for lid in open_alerts if lid == line.id),
            shifts=la.shifts,
        )
        out_lines.append(ol)
        if line.is_active:
            tot_out += la.output
            tot_plan += la.planned_output
            tot_outside += la.output_outside_plan
    active = {ln.id for ln in lines if ln.is_active}
    cams = [cid for cid, lid in db.execute(select(models.Camera.id, models.Camera.line_id)) if lid in active]
    return Overview(
        from_=start,
        to=end,
        lines=out_lines,
        totals=OverviewTotals(
            output=tot_out, output_outside_plan=tot_outside, planned_output=round(tot_plan, 1), cameras_online=sum(1 for c in cams if manager.status(c).get("online")),
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
