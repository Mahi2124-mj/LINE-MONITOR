"""Analyzer plugins.

Each camera worker runs an ordered list of analyzers on every processed frame. To add a new
capability later (PPE check, part verification, ergonomics ...), subclass `Analyzer`, decorate
it with `@register`, and enable its key in the camera's `config.analyzers`. Analyzers can:

- `process(fc)`      inspect the frame / tracked persons and update their own state
- `contribute(d)`    add metrics to a completed cycle before it is saved
- `draw(img, fc)`    draw their overlay on the live stream
- `flush()`          persist accumulated data (called periodically and on shutdown)
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Callable, ClassVar

import cv2
import numpy as np

from .geometry import ZonePoly, dist
from .trackers import Person

if TYPE_CHECKING:
    from .worker import CameraContext

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ shared data
@dataclass
class FrameContext:
    t: float  # wall-clock time of the frame
    dt: float  # seconds since previous processed frame (capped)
    frame: np.ndarray  # BGR at processing resolution
    gray: np.ndarray  # blurred grayscale
    fg_mask: Callable[[], np.ndarray | None]  # lazily computed motion mask
    persons: list[Person] = field(default_factory=list)
    station_person: dict[int, Person | None] = field(default_factory=dict)
    part_present: dict[int, bool | None] = field(default_factory=dict)
    zone_ratio: dict[str, float] = field(default_factory=dict)  # for overlay/debug


@dataclass
class CycleDraft:
    station_id: int
    started_ts: float
    ended_ts: float
    cycle_sec: float
    processing_sec: float
    work_sec: float = 0.0
    motion_waste_sec: float = 0.0
    wait_sec: float = 0.0
    hand_travel_m: float = 0.0
    reach_count: int = 0
    walk_m: float = 0.0
    pick_count: int = 0
    track: dict | None = None
    has_movement: bool = False


class Analyzer:
    key: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    available: ClassVar[bool] = True
    default_enabled: ClassVar[bool] = True
    order: ClassVar[int] = 100

    def __init__(self, cam: "CameraContext") -> None:
        self.cam = cam

    def process(self, fc: FrameContext) -> None: ...

    def contribute(self, draft: CycleDraft) -> None: ...

    def reset_station(self, station_id: int, t: float) -> None: ...

    def draw(self, img: np.ndarray, fc: FrameContext) -> None: ...

    def flush(self, force: bool = False) -> None: ...

    def station_flags(self, station_id: int) -> dict:
        return {}


REGISTRY: dict[str, type[Analyzer]] = {}

# Planned analyzers shown in the UI as "coming soon". Implement them as Analyzer subclasses.
PLANNED = [
    ("part_verification", "Part verification", "Object detection checks that the correct part was added at each step (missing / wrong part alarm)."),
    ("ppe_check", "PPE compliance", "Detects gloves, caps, safety glasses and raises an alert when missing."),
    ("ergonomics", "Ergonomics (RULA/REBA)", "Scores posture risk from pose keypoints: bending, over-head reach, twisting."),
    ("operator_id", "Operator identification", "Associates cycles with operators (badge / face) for skill-wise analysis."),
    ("defect_detection", "Visual defect detection", "Flags scratches, misalignment or missing screws on the finished unit."),
]


def register(cls: type[Analyzer]) -> type[Analyzer]:
    REGISTRY[cls.key] = cls
    return cls


def analyzer_catalog() -> list[dict]:
    items = [
        {"key": c.key, "name": c.name, "description": c.description, "available": c.available, "default_enabled": c.default_enabled}
        for c in sorted(REGISTRY.values(), key=lambda c: c.order)
    ]
    items += [{"key": k, "name": n, "description": d, "available": False, "default_enabled": False} for k, n, d in PLANNED]
    return items


# ------------------------------------------------------------------ cycle detection
class _PresenceDetector:
    """Debounced presence state machine: part arrives ('in') -> part leaves ('out') = one cycle."""

    def __init__(self, in_db: float, out_db: float) -> None:
        self.in_db, self.out_db = in_db, out_db
        self.present: bool | None = None
        self.cand_since: float | None = None

    def update(self, t: float, raw: bool) -> tuple[str, float] | None:
        if self.present is None:  # first frame: adopt current state silently
            self.present = raw
            return None
        if raw == self.present:
            self.cand_since = None
            return None
        if self.cand_since is None:
            self.cand_since = t
        if t - self.cand_since >= (self.in_db if raw else self.out_db):
            self.present = raw
            ev = ("in" if raw else "out", self.cand_since)
            self.cand_since = None
            return ev
        return None


def typical_period(starts: list[float], lo: float = 5.0, hi: float = 180.0, tol: float = 2.0) -> float | None:
    """Rhythm of a station from the start times of all visits (extra or missed visits included): the lag at which
    clearly more visits have a successor than chance would give, preferring the fundamental over its multiples.
    Unlike the median of counted cycles it cannot lock onto a multiple of the real cycle."""
    s = np.asarray(sorted(starts), float)
    if len(s) < 6:
        return None
    density = (len(s) - 1) / max(1e-6, s[-1] - s[0])
    chance = 1.0 - math.exp(-density * 2 * tol)
    lags = np.arange(lo, min(hi, (s[-1] - s[0]) / 3) + 1e-9, 0.25)
    scores = np.zeros(len(lags))
    for k, lag in enumerate(lags):
        base = s[s + lag + tol <= s[-1]]
        if len(base) < max(4, 0.5 * len(s)):
            continue
        j = np.searchsorted(s, base + lag - tol)
        ok = (j < len(s)) & (s[np.minimum(j, len(s) - 1)] <= base + lag + tol)
        scores[k] = (ok.mean() - chance) / max(1e-6, 1.0 - chance)
    if not len(scores) or scores.max() < 0.3:
        return None
    best = int(np.argmax(scores))
    for d in (3, 2):  # a multiple of the real cycle also scores well: prefer the fundamental
        w = np.abs(lags - lags[best] / d) <= tol
        if w.any() and scores[w].max() >= 0.6 * scores[best]:
            return float(lags[w][np.argmax(scores[w])])
    return float(lags[best])


class _VisitDetector:
    """Visits to a fixture (operator's wrists from pose, or bursts of machine motion): a visit starts when the signal
    stays on for start_sec and ends after END_GAP seconds without it."""

    START_SEC = 0.3
    END_GAP = 3.0
    RUN_GAP = 1.0  # hits closer than this belong to the same run

    def __init__(self, start_sec: float = START_SEC) -> None:
        self.start_sec = start_sec
        self.active = False
        self.run_start: float | None = None
        self.last_hit: float | None = None

    def update(self, t: float, hit: bool) -> float | None:
        """Returns the start time of a new visit."""
        if hit:
            if self.run_start is None or (self.last_hit is not None and t - self.last_hit > self.RUN_GAP):
                self.run_start = t
            self.last_hit = t
            if not self.active and t - self.run_start >= self.start_sec - 1e-6:
                self.active = True
                return self.run_start
        elif self.active and self.last_hit is not None and t - self.last_hit >= self.END_GAP:
            self.active = False
            self.run_start = None
        return None


class _StrokeDetector:
    """Machine strokes in a small 'stroke_zone' around a moving machine part (e.g. the carriage plate of station 1).
    Each frame of the zone is compared with the median picture of the zone over the surrounding minute, so a stroke is
    found whatever colour the part in the machine has (it changes red / blue / none during a shift). A frame is judged
    LAG seconds after it arrived, so the median covers both sides of it and a colour change is not taken for a stroke.
    Rule and thresholds validated against frame-by-frame video (tools/reports/validation/m1_findings_day.md)."""

    WINDOW = 60.0  # seconds of zone pictures kept for the median
    STEP = 5.0  # median picture recomputed this often
    ON, PEAK = 12.0, 20.0  # mean grey difference: stroke frame / required peak of a stroke
    JOIN = 1.0  # changes closer than this are one stroke
    MAX_RUN = 6.0  # a longer change is a scene change (light, part colour), not a stroke
    NEAR = 3.0  # the operator must be seen within this many seconds of a stroke

    def __init__(self, lag: float = 30.0) -> None:
        self.lag = lag
        self.buf: list[tuple[float, np.ndarray, bool]] = []  # time, zone picture, operator seen
        self.med: np.ndarray | None = None
        self.med_t = -math.inf
        self.judged = -math.inf  # time of the last judged frame
        self.run: list | None = None  # [start, first frame after the change (None while changing), peak]
        self.dev = 0.0

    def update(self, t: float, zone_gray: np.ndarray, operator: bool) -> list[float]:
        """Add a frame (grey picture of the zone); returns the start times of strokes confirmed now."""
        if self.buf and self.buf[-1][1].shape != zone_gray.shape:  # resolution changed
            self.buf, self.med = [], None
        self.buf.append((t, zone_gray.astype(np.float32), operator))
        while self.buf and self.buf[0][0] < t - self.WINDOW:
            self.buf.pop(0)
        if len(self.buf) >= 20 and t - self.med_t >= self.STEP:
            self.med = np.median(np.stack([b[1] for b in self.buf]), axis=0)
            self.med_t = t
        out: list[float] = []
        if self.med is None:
            return out
        for k, (tf, img, _) in enumerate(self.buf):
            if tf <= self.judged:
                continue
            if tf > t - self.lag:
                break
            self.judged = tf
            self.dev = float(np.abs(img - self.med).mean())
            s = self._step(tf, self.dev)
            if s is not None and any(op for tb, _, op in self.buf if abs(tb - s) <= self.NEAR):
                out.append(s)
        return out

    def _step(self, tf: float, dev: float) -> float | None:
        run, done = self.run, None
        if dev > self.ON:
            if run is None:
                self.run = [tf, None, dev]
            elif run[1] is not None and tf - run[1] >= self.JOIN:
                done, self.run = self._close(run), [tf, None, dev]
            else:
                run[1], run[2] = None, max(run[2], dev)
        elif run is not None:
            if run[1] is None:
                run[1] = tf
            elif tf - run[1] >= self.JOIN:
                done, self.run = self._close(run), None
        return done

    def _close(self, run: list) -> float | None:
        return run[0] if run[2] >= self.PEAK and run[1] - run[0] <= self.MAX_RUN else None


@dataclass
class _ZoneTrack:
    """One fixture / trigger zone of a station (a station can have several, e.g. 2 part fixtures)."""

    zone: ZonePoly | None
    detector: _PresenceDetector | None = None
    t_in: float | None = None  # when the unit currently in this fixture arrived
    ratio: float = 0.0
    trigger_inside: bool = False
    trigger_since: float | None = None
    visit: _VisitDetector = field(default_factory=_VisitDetector)
    motion: _VisitDetector = field(default_factory=lambda: _VisitDetector(0.6))
    occupancy: float = 0.0  # share of recent time with a wrist in the zone


@dataclass
class _StationCycleState:
    method: str
    zones: list[_ZoneTrack]
    last_out: float | None = None  # end of previous cycle (any fixture)
    cycle_start: float | None = None
    # operator-visit mode
    last_visit: float | None = None  # start of the visit that began the current cycle
    visit_sec: float = 0.0  # time the operator spent at the fixture in the current cycle
    recent: list[float] = field(default_factory=list)  # recent cycle times (fallback for the rhythm)
    starts: list[float] = field(default_factory=list)  # all visit starts of the last RHYTHM_WINDOW seconds
    periods: list[float] = field(default_factory=list)  # last rhythm estimates (median used)
    by_visit: bool = False
    by_motion: bool = False  # operator not visible at the fixture: cycles from bursts of machine motion instead
    pose_starts: float = 0.0  # recent number of operator visits / motion bursts (decaying counters)
    motion_starts: float = 0.0
    # machine-stroke mode (station with a stroke_zone): cycles counted from confirmed strokes, the live timer from fast ones
    stroke: _StrokeDetector | None = None
    fast: _StrokeDetector | None = None

    @property
    def busy(self) -> bool:
        return any(z.t_in is not None for z in self.zones)


@register
class CycleTimeAnalyzer(Analyzer):
    key = "cycle_time"
    name = "Cycle time"
    description = (
        "Detects every cycle per station (part arrives/leaves a fixture, or hand enters a trigger zone) and records cycle time. "
        "Several part fixtures per station are supported: a unit leaving any of them is one finished cycle."
    )
    order = 10

    MOTION_RATIO = 0.04  # fraction of moving pixels in a zone that counts as 'activity'
    DIFF_LEVEL = 28
    # operator-visit mode (part zone without an empty reference image, pose available): a cycle starts each time the
    # operator comes to the fixture. Motion in the zone is not used there - it misses cycles and splits others.
    VISIT_MERGE = 0.65  # a new visit sooner than this x the typical cycle belongs to the same cycle
    STOP_FACTOR = 4.0  # no new visit for this x the typical cycle (and >= STOP_MIN_SEC) = line stopped, not a cycle
    STOP_MIN_SEC = 120.0
    BUSY_ZONE = 0.7  # a zone with hands in it most of the time (work table) says nothing about cycles
    OCCUPANCY_TAU = 300.0
    COUNT_TAU = 600.0
    RHYTHM_WINDOW = 600.0

    def __init__(self, cam: "CameraContext") -> None:
        super().__init__(cam)
        self.states: dict[int, _StationCycleState] = {}
        cfg = cam.config
        for sid in cam.cycle_station_ids:
            method = cfg.cycle_method
            zones: list[ZonePoly | None] = []
            if cam.zones_of("stroke_zone", sid):  # one machine stroke = one cycle; beats any other method
                method = "machine_stroke"
                zones = cam.zones_of("stroke_zone", sid)[:1]
            if method == "part_presence":
                zones = list(cam.zones_of("part_zone", sid))
                if not zones:
                    method = "activity"
            if method == "trigger_zone":
                zones = list(cam.zones_of("trigger_zone", sid))
                if not zones:
                    method = "activity"
            if method == "activity":
                zones = list(cam.zones_of("part_zone", sid)) or cam.zones_of("work_area", sid)[:1] or [None]
            tracks = []
            for z in zones:
                zt = _ZoneTrack(zone=z)
                if method in ("part_presence", "activity"):
                    out_db = cfg.presence_debounce_sec if method == "part_presence" else max(3.0, cfg.presence_debounce_sec)
                    zt.detector = _PresenceDetector(cfg.presence_debounce_sec, out_db)
                tracks.append(zt)
            self.states[sid] = _StationCycleState(method=method, zones=tracks)
            if method == "machine_stroke":
                self.states[sid].stroke, self.states[sid].fast = _StrokeDetector(30.0), _StrokeDetector(3.0)
            memory = getattr(cam.worker, "cycle_memory", None)
            if memory is not None:  # operator-visit mode: start with the station's rhythm already known
                if sid not in memory:
                    memory[sid] = {"recent": cam.worker.recent_cycles(sid)[-10:], "periods": []}
                self.states[sid].recent = list(memory[sid]["recent"])
                self.states[sid].periods = list(memory[sid]["periods"])

    # ---- signals
    def _presence_raw(self, method: str, zt: _ZoneTrack, fc: FrameContext) -> bool:
        z = zt.zone
        if method == "part_presence" and self.cam.reference is not None and z is not None:
            ref = z.roi(self.cam.reference)
            cur = z.roi(fc.gray)
            if ref.shape == cur.shape:
                diff = cv2.absdiff(cur, ref)
                zt.ratio = float(np.count_nonzero(diff[z.mask_roi] > self.DIFF_LEVEL)) / z.area_px
                fc.zone_ratio[z.id] = zt.ratio
                return zt.ratio >= self.cam.config.presence_threshold
        # activity / no reference yet: motion inside the zone
        fg = fc.fg_mask()
        if fg is None:
            return False
        zt.ratio = z.ratio(fg) if z is not None else float(np.count_nonzero(fg)) / fg.size
        if z is not None:
            fc.zone_ratio[z.id] = zt.ratio
        return zt.ratio >= self.MOTION_RATIO

    def _trigger_raw(self, zt: _ZoneTrack, fc: FrameContext) -> bool:
        z = zt.zone
        if z is None:
            return False
        if fc.persons:
            return any(z.contains(w) for p in fc.persons for w in p.wrists)
        fg = fc.fg_mask()
        return fg is not None and z.ratio(fg) >= self.MOTION_RATIO * 1.5

    # ---- main
    def process(self, fc: FrameContext) -> None:
        for sid, st in self.states.items():
            if st.method == "trigger_zone":
                fc.part_present[sid] = None
                for zt in st.zones:
                    raw = self._trigger_raw(zt, fc)
                    if raw and not zt.trigger_inside:
                        zt.trigger_since = zt.trigger_since or fc.t
                        if fc.t - zt.trigger_since >= 0.2:
                            zt.trigger_inside = True
                            self._on_trigger(sid, st, zt.trigger_since)
                    elif not raw:
                        zt.trigger_since = None
                        zt.trigger_inside = False
                continue

            if st.method == "machine_stroke":
                self._process_strokes(sid, st, fc)
                continue

            st.by_visit = st.method == "part_presence" and self.cam.reference is None and self._pose()
            if st.by_visit:
                self._process_visits(sid, st, fc)
                continue

            events = []
            for zt in st.zones:
                raw = self._presence_raw(st.method, zt, fc)
                assert zt.detector is not None
                ev = zt.detector.update(fc.t, raw)
                if ev is not None:
                    events.append((zt, *ev))
            fc.part_present[sid] = any(bool(zt.detector and zt.detector.present) for zt in st.zones)
            for zt, kind, t_ev in sorted(events, key=lambda e: e[2]):
                if kind == "in":
                    self._on_in(sid, st, zt, t_ev)
                else:
                    self._on_out(sid, st, zt, t_ev)

    def _process_strokes(self, sid: int, st: _StationCycleState, fc: FrameContext) -> None:
        zt = st.zones[0]
        z = zt.zone
        assert z is not None and st.stroke is not None and st.fast is not None
        x, y, w, h = z.bbox
        pic = cv2.cvtColor(fc.frame[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)[z.mask_roi]  # not blurred, as validated
        operator = fc.station_person.get(sid) is not None
        for s in st.fast.update(fc.t, pic, operator):  # live timer only (3 s behind)
            if st.last_out is not None and s - st.last_out >= self.cam.config.min_cycle_sec:
                self.cam.set_cycle_start(sid, s)
        for s in st.stroke.update(fc.t, pic, operator):  # counted cycles (30 s behind: colour changes ruled out)
            self._on_stroke(sid, st, s)
        zt.ratio = min(1.0, st.fast.dev / _StrokeDetector.PEAK)
        fc.zone_ratio[z.id] = zt.ratio
        fc.part_present[sid] = None  # the part itself is not seen; operator / idle state decides

    def _on_stroke(self, sid: int, st: _StationCycleState, t: float) -> None:
        cfg = self.cam.config
        if st.last_out is None:
            st.last_out = t
            self.cam.reset_station(sid, t)
            self.cam.set_cycle_start(sid, t)
            return
        gap = t - st.last_out
        if gap < cfg.min_cycle_sec:
            return  # same stroke seen twice
        typical = float(np.median(st.recent)) if len(st.recent) >= 3 else None
        stop = min(cfg.max_cycle_sec, max(self.STOP_MIN_SEC, self.STOP_FACTOR * typical)) if typical else cfg.max_cycle_sec
        start, st.last_out = st.last_out, t
        if gap > stop:  # break / line stop - not a cycle
            self.cam.reset_station(sid, t)
            return
        self.cam.complete_cycle(CycleDraft(sid, start, t, gap, gap))
        st.recent = (st.recent + [gap])[-10:]

    def _pose(self) -> bool:
        return getattr(getattr(self.cam.worker, "tracker", None), "name", "") == "pose"

    def _process_visits(self, sid: int, st: _StationCycleState, fc: FrameContext) -> None:
        wrists = [w for p in fc.persons if not p.approx for w in p.wrists if w is not None]
        fg = fc.fg_mask()
        free = [zt for zt in st.zones if zt.occupancy < self.BUSY_ZONE] or st.zones
        a = min(1.0, fc.dt / self.OCCUPANCY_TAU)
        decay = math.exp(-fc.dt / self.COUNT_TAU)
        st.pose_starts *= decay
        st.motion_starts *= decay
        pose, motion, hit_any, moving_any = [], [], False, False
        for zt in st.zones:
            hit = zt.zone is not None and any(zt.zone.contains(w) for w in wrists)
            moving = zt.zone is not None and fg is not None and zt.zone.ratio(fg) >= self.MOTION_RATIO
            zt.occupancy += a * (float(hit) - zt.occupancy)
            zt.ratio = 1.0 if hit else 0.0
            s, m = zt.visit.update(fc.t, hit), zt.motion.update(fc.t, moving)
            if any(zt is f for f in free):
                hit_any |= hit
                moving_any |= moving
                if s is not None:
                    pose.append(s)
                if m is not None:
                    motion.append(m)
        st.pose_starts += len(pose)
        st.motion_starts += len(motion)
        # machine-motion mode only where the operator's hands are (almost) never seen at the fixture
        st.by_motion = st.motion_starts >= 5 and st.pose_starts < 0.2 * st.motion_starts
        at_fixture = any((zt.motion if st.by_motion else zt.visit).active for zt in free)
        fc.part_present[sid] = True if at_fixture else None  # unknown between visits (operator may be busy elsewhere)
        if moving_any if st.by_motion else hit_any:
            st.visit_sec += fc.dt
        for s in sorted(motion if st.by_motion else pose):
            self._on_visit(sid, st, s)

    def _on_visit(self, sid: int, st: _StationCycleState, t: float) -> None:
        cfg = self.cam.config
        st.starts = [x for x in st.starts if x >= t - self.RHYTHM_WINDOW] + [t]
        period = typical_period(st.starts, lo=max(3.0, cfg.min_cycle_sec), hi=min(180.0, cfg.max_cycle_sec))
        if period is not None:
            st.periods = (st.periods + [period])[-5:]
            self._remember(sid, st)
        if st.last_visit is None:
            self._restart_visits(sid, st, t)
            return
        gap = t - st.last_visit
        # typical cycle: median of the recent cycles, unless the visit rhythm shows it has locked onto a multiple
        known = ([float(np.median(st.recent))] if len(st.recent) >= 3 else []) + ([float(np.median(st.periods))] if st.periods else [])
        typical = min(known) if known else None
        prior = typical or (self.cam.stations[sid].target_cycle_sec if sid in self.cam.stations else None)
        if gap < max(cfg.min_cycle_sec, self.VISIT_MERGE * prior if prior else 0.0):
            return  # another visit within the same cycle (fetching a part, checking ...)
        stop = min(cfg.max_cycle_sec, max(self.STOP_MIN_SEC, self.STOP_FACTOR * typical)) if typical else cfg.max_cycle_sec
        if gap > stop:  # break / line stop - not a cycle
            self._restart_visits(sid, st, t)
            return
        self.cam.complete_cycle(CycleDraft(sid, st.last_visit, t, gap, min(st.visit_sec, gap)))
        st.recent = (st.recent + [gap])[-10:]
        self._remember(sid, st)
        st.last_visit, st.visit_sec = t, 0.0
        self.cam.set_cycle_start(sid, t)

    def _remember(self, sid: int, st: _StationCycleState) -> None:
        memory = getattr(self.cam.worker, "cycle_memory", None)
        if memory is not None:  # kept by the worker across reconnects
            memory[sid] = {"recent": list(st.recent), "periods": list(st.periods)}

    def _restart_visits(self, sid: int, st: _StationCycleState, t: float) -> None:
        st.last_visit, st.visit_sec = t, 0.0
        self.cam.reset_station(sid, t)
        self.cam.set_cycle_start(sid, t)

    def _on_in(self, sid: int, st: _StationCycleState, zt: _ZoneTrack, t: float) -> None:
        cfg = self.cam.config
        idle_before = not st.busy
        zt.t_in = t
        if idle_before and (st.last_out is None or t - st.last_out > cfg.max_cycle_sec):
            # first unit after start-up / a long stop: the cycle starts with this part
            st.cycle_start = t
            self.cam.reset_station(sid, t)
        elif st.cycle_start is None:
            st.cycle_start = st.last_out if st.last_out is not None else t
        self.cam.set_cycle_start(sid, st.cycle_start)

    def _on_out(self, sid: int, st: _StationCycleState, zt: _ZoneTrack, t: float) -> None:
        cfg = self.cam.config
        if zt.t_in is None:
            return
        processing = t - zt.t_in
        if processing < cfg.min_cycle_sec:
            return  # noise (hand passing over an empty fixture, flicker)
        start = st.cycle_start if st.cycle_start is not None else zt.t_in
        cycle_sec = t - start
        zt.t_in = None
        st.last_out = t
        st.cycle_start = t
        self.cam.set_cycle_start(sid, t)
        if cycle_sec > cfg.max_cycle_sec:
            self.cam.reset_station(sid, t)
            return
        self.cam.complete_cycle(CycleDraft(sid, start, t, cycle_sec, processing))

    def _on_trigger(self, sid: int, st: _StationCycleState, t: float) -> None:
        cfg = self.cam.config
        if st.last_out is None or t - st.last_out > cfg.max_cycle_sec:
            st.last_out = t
            self.cam.reset_station(sid, t)
            self.cam.set_cycle_start(sid, t)
            return
        cycle_sec = t - st.last_out
        if cycle_sec < cfg.min_cycle_sec:
            return
        start = st.last_out
        st.last_out = t
        self.cam.set_cycle_start(sid, t)
        self.cam.complete_cycle(CycleDraft(sid, start, t, cycle_sec, cycle_sec))

    def contribute(self, draft: CycleDraft) -> None:
        pass

    def station_flags(self, station_id: int) -> dict:
        st = self.states.get(station_id)
        if st is None:
            return {}
        method = ("machine_motion" if st.by_motion else "operator_visit") if st.by_visit else st.method
        return {"method": method, "ratio": max((z.ratio for z in st.zones), default=0.0),
                "fixtures": len(st.zones)}

    def draw(self, img: np.ndarray, fc: FrameContext) -> None:
        label = {"part_presence": "PART", "activity": "ACTIVITY", "trigger_zone": "TRIGGER", "machine_stroke": "STROKE"}
        for st in self.states.values():
            many = len(st.zones) > 1
            for i, zt in enumerate(st.zones, start=1):
                z = zt.zone
                if z is None:
                    continue
                if st.by_visit:
                    present = (zt.motion if st.by_motion else zt.visit).active
                elif st.method == "trigger_zone":
                    present = None
                elif st.method == "machine_stroke":
                    present = zt.ratio >= 1.0
                else:
                    present = bool(zt.detector and zt.detector.present)
                color = (80, 220, 80) if present else (0, 170, 255)
                x, y, _, _ = z.bbox
                kind = ("MACHINE" if st.by_motion else "OPERATOR") if st.by_visit else label[st.method]
                name = f"{kind}{' ' + str(i) if many else ''}"
                state = "YES" if present else "NO" if present is not None else ""
                pct = "" if st.by_visit else f" {zt.ratio * 100:.0f}%"
                cv2.putText(img, f"{name} {state}{pct}", (x + 2, max(12, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1, cv2.LINE_AA)


# ------------------------------------------------------------------ movement / motion waste
@dataclass
class _Excursion:
    outside_since: float | None = None
    inside_since: float | None = None  # back inside, but not yet long enough to close the excursion
    counted: bool = False


@dataclass
class _Movement:
    t_work: float = 0.0
    t_motion: float = 0.0
    t_wait: float = 0.0
    hand_px_m: float = 0.0  # already in meters
    walk_m: float = 0.0
    reaches: int = 0
    picks: int = 0
    prev_wrists: list = field(default_factory=lambda: [None, None])
    prev_body: tuple[float, float] | None = None
    reach_state: list = field(default_factory=lambda: [_Excursion(), _Excursion()])
    pick_inside: list = field(default_factory=lambda: [None, None])  # zone id currently inside, per wrist
    pick_since: list = field(default_factory=lambda: [None, None])
    still_since: float | None = None
    hand: list = field(default_factory=list)
    body: list = field(default_factory=list)
    last_track_t: float = 0.0
    idle: bool = False
    away: bool = False
    reaching: bool = False
    scale_m_per_px: float | None = None


@register
class MovementAnalyzer(Analyzer):
    key = "movement"
    name = "Operator movement"
    description = (
        "Tracks hands and body: hand travel, reaches outside the normal work area, picks vs expected, walking, idle. "
        "Splits each cycle into value-added work, motion waste and waiting."
    )
    order = 20

    REACH_DEBOUNCE = 0.3
    REENTRY_GRACE = 0.6
    PICK_DEBOUNCE = 0.4  # hand must dwell in a bin zone (grasp), passing over it is not a pick
    ACTIVITY_RATIO = 0.003  # motion-proxy mode: moving pixel fraction in the work area that means "hands busy"
    IDLE_SPEED = 0.06  # m/s below which hands count as still
    IDLE_AFTER = 1.5  # s of stillness before it counts as waiting
    WALK_SPEED = 0.25  # m/s body speed that counts as walking
    JITTER_M = 0.012  # ignore steps smaller than this (keypoint noise)

    def __init__(self, cam: "CameraContext") -> None:
        super().__init__(cam)
        self.acc: dict[int, _Movement] = {sid: _Movement() for sid in cam.station_ids}

    def reset_station(self, station_id: int, t: float) -> None:
        self.acc[station_id] = _Movement()

    def _m_per_px(self, m: _Movement, p: Person | None) -> float:
        if p is not None and p.shoulder_px:
            s = 0.40 / p.shoulder_px
            m.scale_m_per_px = s if m.scale_m_per_px is None else 0.9 * m.scale_m_per_px + 0.1 * s
        return m.scale_m_per_px or self.cam.default_m_per_px

    def process(self, fc: FrameContext) -> None:
        for sid, m in self.acc.items():
            self._update(sid, m, fc)

    def _reach(self, m: _Movement, ex: _Excursion, outside: bool, seen: bool, t: float) -> bool:
        """Excursion state machine; returns True while a counted reach is in progress."""
        if outside:
            ex.inside_since = None
            if ex.outside_since is None:
                ex.outside_since, ex.counted = t, False
            if not ex.counted and t - ex.outside_since >= self.REACH_DEBOUNCE:
                ex.counted = True
                m.reaches += 1
            return ex.counted
        if ex.outside_since is not None and seen:
            # short flickers back inside (keypoint noise, blob jitter) do not end the excursion
            ex.inside_since = ex.inside_since or t
            if t - ex.inside_since >= self.REENTRY_GRACE:
                ex.outside_since, ex.inside_since, ex.counted = None, None, False
        return False

    def _update(self, sid: int, m: _Movement, fc: FrameContext) -> None:
        p = fc.station_person.get(sid)
        part = fc.part_present.get(sid)
        dt = fc.dt
        work_areas = self.cam.zones_of("work_area", sid)
        picks = self.cam.zones_of("pick_zone", sid)
        k = self._m_per_px(m, p)

        if p is None:
            m.prev_wrists, m.prev_body = [None, None], None
            m.away, m.reaching, m.idle = True, False, False
            if part is True:
                m.t_motion += dt  # part waiting while the operator is away
            else:
                m.t_wait += dt
            return

        # body / walking (not measurable with the motion-blob proxy)
        walking = False
        if m.prev_body is not None and not p.approx:
            step_m = dist(p.body, m.prev_body) * k
            if dt > 0 and step_m / dt >= self.WALK_SPEED and step_m >= self.JITTER_M:
                m.walk_m += step_m
                walking = True
        m.prev_body = p.body
        away = bool(work_areas) and not p.approx and not any(z.contains(p.body) for z in work_areas)

        # wrists: travel, reaches, picks
        max_speed = 0.0
        reaching_now = False
        can_reach = bool(work_areas) and not away and not walking
        outside = [w is not None and can_reach and not any(z.contains(w) for z in work_areas) for w in p.wrists[:2]]
        if p.approx:
            # blob "hands" swap order / split, so track one combined excursion for the station
            reaching_now = self._reach(m, m.reach_state[0], any(outside), any(w is not None for w in p.wrists), fc.t)
        for i in range(2):
            w = p.wrists[i] if i < len(p.wrists) else None
            prev = m.prev_wrists[i]
            if w is not None and prev is not None:
                step_m = dist(w, prev) * k
                if step_m >= self.JITTER_M:
                    m.hand_px_m += step_m
                if dt > 0:
                    max_speed = max(max_speed, step_m / dt)
            m.prev_wrists[i] = w
            if w is None:
                continue
            if not p.approx:
                # a hand outside the work area while the body is inside = a long reach (walking away is counted separately)
                reaching_now = self._reach(m, m.reach_state[i], outside[i], True, fc.t) or reaching_now
            zin = next((z.id for z in picks if z.contains(w)), None)
            if zin is None:
                m.pick_inside[i], m.pick_since[i] = None, None
            elif m.pick_inside[i] != zin:
                if m.pick_since[i] is None:
                    m.pick_since[i] = fc.t
                elif fc.t - m.pick_since[i] >= self.PICK_DEBOUNCE:
                    m.pick_inside[i] = zin
                    m.picks += 1

        # idle detection
        if p.approx:  # motion proxy: busy = something moves inside the work area
            fg = fc.fg_mask()
            busy = fg is not None and any(z.ratio(fg) >= self.ACTIVITY_RATIO for z in work_areas) if work_areas else max_speed > 0
        else:
            busy = max_speed >= self.IDLE_SPEED or walking
        if not busy:
            m.still_since = m.still_since or fc.t
        else:
            m.still_since = None
        idle = m.still_since is not None and fc.t - m.still_since >= self.IDLE_AFTER
        m.idle, m.away, m.reaching = idle, away, reaching_now

        # time classification
        if part is False:
            m.t_wait += dt
        elif away or walking or reaching_now:
            m.t_motion += dt
        elif idle:
            m.t_wait += dt
        else:
            m.t_work += dt

        # path for spaghetti diagram
        if fc.t - m.last_track_t >= 0.25:
            m.last_track_t = fc.t
            h, w_ = fc.frame.shape[:2]
            vis = [x for x in p.wrists if x is not None]
            if vis:
                # follow the hand that is farther from the body (the one doing the reaching)
                hw = max(vis, key=lambda x: dist(x, p.body))
                m.hand.append((round(hw[0] / w_, 4), round(hw[1] / h, 4)))
            m.body.append((round(p.body[0] / w_, 4), round(p.body[1] / h, 4)))
            if len(m.hand) > 800:
                m.hand = m.hand[::2]
            if len(m.body) > 800:
                m.body = m.body[::2]

    def contribute(self, d: CycleDraft) -> None:
        m = self.acc.get(d.station_id)
        if m is None:
            return
        total = m.t_work + m.t_motion + m.t_wait
        if total > 0.5:
            f = d.cycle_sec / total
            d.work_sec, d.motion_waste_sec, d.wait_sec = m.t_work * f, m.t_motion * f, m.t_wait * f
            d.has_movement = True
        d.hand_travel_m = m.hand_px_m
        d.walk_m = m.walk_m
        d.reach_count = m.reaches
        d.pick_count = m.picks

        def thin(pts: list) -> list:
            step = max(1, len(pts) // 150)
            return pts[::step]

        if m.hand or m.body:
            d.track = {"hand": thin(m.hand), "body": thin(m.body)}
        # start a fresh accumulator for the next cycle, keeping continuity of positions
        nm = _Movement(prev_wrists=m.prev_wrists, prev_body=m.prev_body, scale_m_per_px=m.scale_m_per_px)
        nm.reach_state, nm.pick_inside = m.reach_state, m.pick_inside
        for ex in nm.reach_state:  # an excursion that is still ongoing belongs to the next cycle
            if ex.outside_since is not None:
                ex.counted = False
                ex.outside_since = d.ended_ts
        self.acc[d.station_id] = nm

    def station_flags(self, station_id: int) -> dict:
        m = self.acc.get(station_id)
        if m is None:
            return {}
        return {"idle": m.idle, "away": m.away, "reaching": m.reaching, "reaches": m.reaches, "picks": m.picks}

    def draw(self, img: np.ndarray, fc: FrameContext) -> None:
        for sid, m in self.acc.items():
            p = fc.station_person.get(sid)
            if p is None:
                continue
            for i, w in enumerate(p.wrists):
                if w is None:
                    continue
                ex = m.reach_state[i] if i < len(m.reach_state) else None
                bad = ex is not None and ex.counted
                cv2.circle(img, (int(w[0]), int(w[1])), 12 if bad else 8, (40, 40, 240) if bad else (60, 220, 255), 2, cv2.LINE_AA)
            cv2.circle(img, (int(p.body[0]), int(p.body[1])), 6, (255, 200, 60), -1, cv2.LINE_AA)


# ------------------------------------------------------------------ heatmap
@register
class HeatmapAnalyzer(Analyzer):
    key = "heatmap"
    name = "Hand heatmap"
    description = "Accumulates where the operator's hands spend time (per camera, per day) to spot long reaches and unused areas."
    order = 30
    FLUSH_SEC = 60.0

    def __init__(self, cam: "CameraContext") -> None:
        super().__init__(cam)
        from ..config import settings

        self.cols, self.rows = settings.heatmap_cols, settings.heatmap_rows
        self.grid = np.zeros((self.rows, self.cols), np.float32)
        self.last_flush = time.time()

    def process(self, fc: FrameContext) -> None:
        h, w = fc.frame.shape[:2]
        seen: set[int] = set()
        for p in fc.station_person.values():
            if p is None or id(p) in seen:
                continue
            seen.add(id(p))
            for wr in p.wrists:
                if wr is None:
                    continue
                c = min(self.cols - 1, max(0, int(wr[0] / w * self.cols)))
                r = min(self.rows - 1, max(0, int(wr[1] / h * self.rows)))
                self.grid[r, c] += fc.dt
        if time.time() - self.last_flush >= self.FLUSH_SEC:
            self.flush()

    def flush(self, force: bool = False) -> None:
        self.last_flush = time.time()
        if not self.grid.any():
            return
        grid, self.grid = self.grid, np.zeros_like(self.grid)
        try:
            from ..services.heatmaps import add_heatmap

            add_heatmap(self.cam.camera_id, date.today().isoformat(), self.cols, self.rows, grid)
        except Exception as e:  # pragma: no cover
            log.warning("heatmap flush failed: %s", e)
