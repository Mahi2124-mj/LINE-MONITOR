"""Pydantic schemas. Keep in sync with frontend/src/api/types.ts."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ZoneType = Literal["work_area", "part_zone", "trigger_zone", "pick_zone", "exclusion", "stroke_zone"]
CycleMethod = Literal["part_presence", "trigger_zone", "activity"]
SourceType = Literal["rtsp", "http", "usb", "file", "simulated"]
TrackerType = Literal["auto", "pose", "motion", "simulated"]
Severity = Literal["info", "warning", "critical"]
RangeKey = Literal["1h", "today", "24h", "7d", "30d"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- lines
class LineIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = ""
    description: str = ""
    takt_time_sec: float = Field(60.0, gt=0)
    shift_start: str = "08:00"
    shift_end: str = "20:00"
    is_active: bool = True

    @field_validator("shift_start", "shift_end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        h, m = v.split(":")
        if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
            raise ValueError("time must be HH:MM")
        return f"{int(h):02d}:{int(m):02d}"


class LineUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    takt_time_sec: Optional[float] = Field(None, gt=0)
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    is_active: Optional[bool] = None


class LineOut(ORM):
    id: int
    name: str
    code: str
    description: str
    takt_time_sec: float
    shift_start: str
    shift_end: str
    is_active: bool
    created_at: datetime
    station_count: int = 0
    camera_count: int = 0


# ---------------------------------------------------------------- stations
class StationIn(BaseModel):
    line_id: int
    name: str = Field(min_length=1, max_length=120)
    code: str = ""
    operation: str = ""
    parts_added: list[str] = []
    target_cycle_sec: float = Field(60.0, gt=0)
    expected_picks: int = Field(2, ge=0)
    operator_name: str = ""
    is_active: bool = True
    sequence: Optional[int] = None


class StationUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    operation: Optional[str] = None
    parts_added: Optional[list[str]] = None
    target_cycle_sec: Optional[float] = Field(None, gt=0)
    expected_picks: Optional[int] = Field(None, ge=0)
    operator_name: Optional[str] = None
    is_active: Optional[bool] = None
    sequence: Optional[int] = None


class StationOut(ORM):
    id: int
    line_id: int
    sequence: int
    name: str
    code: str
    operation: str
    parts_added: list[str]
    target_cycle_sec: float
    expected_picks: int
    operator_name: str
    is_active: bool
    camera_ids: list[int] = []


class ReorderIn(BaseModel):
    station_ids: list[int]


# ---------------------------------------------------------------- cameras
class Zone(BaseModel):
    id: str
    name: str = ""
    type: ZoneType
    station_id: Optional[int] = None
    points: list[tuple[float, float]]

    @field_validator("points")
    @classmethod
    def _norm(cls, pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if len(pts) < 3:
            raise ValueError("a zone needs at least 3 points")
        return [(min(1.0, max(0.0, float(x))), min(1.0, max(0.0, float(y)))) for x, y in pts]


class SimProfile(BaseModel):
    speed_factor: float = 1.0
    far_reach_prob: float = 0.1
    walk_prob: float = 0.05
    extra_pick_prob: float = 0.1


class CameraConfig(BaseModel):
    cycle_method: CycleMethod = "part_presence"
    tracker: TrackerType = "auto"
    process_fps: float = Field(6.0, gt=0, le=30)
    min_cycle_sec: float = Field(5.0, ge=0)
    max_cycle_sec: float = Field(600.0, gt=0)
    presence_threshold: float = Field(0.15, gt=0, lt=1)
    presence_debounce_sec: float = Field(1.0, ge=0)
    idle_timeout_sec: float = Field(10.0, gt=0)
    meters_per_frame_width: float = Field(2.5, gt=0)
    analyzers: list[str] = ["cycle_time", "movement", "heatmap"]
    use_substream: bool = True  # IP cameras: analyse the low-res sub stream (much less CPU / memory)
    record: bool = False  # keep video + pose recordings for cycle / element analysis
    sim: Optional[SimProfile] = None


class CameraStatus(BaseModel):
    online: bool = False
    fps: float = 0.0
    last_frame_at: Optional[datetime] = None
    error: Optional[str] = None
    tracker: str = "none"
    width: int = 0
    height: int = 0
    needs_reference: bool = False


class CameraIn(BaseModel):
    line_id: int
    station_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=120)
    source_type: SourceType = "rtsp"
    source: str = ""
    enabled: bool = True
    zones: Optional[list[Zone]] = None
    config: Optional[dict] = None


class CameraUpdate(BaseModel):
    line_id: Optional[int] = None
    station_id: Optional[int] = None
    name: Optional[str] = None
    source_type: Optional[SourceType] = None
    source: Optional[str] = None
    enabled: Optional[bool] = None
    zones: Optional[list[Zone]] = None
    config: Optional[dict] = None


class CameraOut(BaseModel):
    id: int
    line_id: int
    station_id: Optional[int]
    name: str
    source_type: str
    source: str
    enabled: bool
    zones: list[Zone]
    config: CameraConfig
    has_reference: bool
    status: CameraStatus


class AnalyzerInfo(BaseModel):
    key: str
    name: str
    description: str
    available: bool
    default_enabled: bool


# ---------------------------------------------------------------- cycles / live / alerts
class CycleOut(ORM):
    id: int
    station_id: int
    line_id: int
    camera_id: Optional[int]
    started_at: datetime
    ended_at: datetime
    cycle_sec: float
    work_sec: float
    motion_waste_sec: float
    wait_sec: float
    hand_travel_m: float
    reach_count: int
    walk_m: float
    pick_count: int
    source: str
    over_target: bool


class ManualCycleIn(BaseModel):
    cycle_sec: float = Field(gt=0)
    work_sec: Optional[float] = None
    wait_sec: Optional[float] = None
    motion_waste_sec: Optional[float] = None


class StationLive(BaseModel):
    station_id: int
    line_id: int
    state: Literal["working", "idle", "waiting", "offline", "no_camera"]
    cycle_elapsed_sec: Optional[float]
    last_cycle_sec: Optional[float]
    count_today: int
    avg_today_sec: Optional[float]
    operator_present: bool
    part_present: bool
    updated_at: datetime


class AlertOut(ORM):
    id: int
    line_id: Optional[int]
    station_id: Optional[int]
    camera_id: Optional[int]
    type: str
    severity: str
    message: str
    created_at: datetime
    acknowledged: bool


# ---------------------------------------------------------------- analytics
class CycleStats(BaseModel):
    count: int = 0
    avg: Optional[float] = None
    median: Optional[float] = None
    p90: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    std: Optional[float] = None
    cv: Optional[float] = None
    avg_work: Optional[float] = None
    avg_motion_waste: Optional[float] = None
    avg_wait: Optional[float] = None
    avg_content: Optional[float] = None
    over_target_pct: Optional[float] = None
    over_takt_pct: Optional[float] = None


class MovementStats(BaseModel):
    avg_hand_travel_m: Optional[float] = None
    avg_reach_count: Optional[float] = None
    avg_walk_m: Optional[float] = None
    avg_pick_count: Optional[float] = None
    expected_picks: int = 0
    va_pct: Optional[float] = None
    motion_waste_pct: Optional[float] = None
    wait_pct: Optional[float] = None
    est_saving_sec: Optional[float] = None


class Recommendation(BaseModel):
    id: str
    line_id: Optional[int] = None
    station_id: Optional[int] = None
    category: Literal["balancing", "motion", "waiting", "stability", "target", "setup"]
    severity: Severity
    title: str
    detail: str
    est_saving_sec: Optional[float] = None


class StationSummary(BaseModel):
    station: StationOut
    stats: CycleStats
    movement: MovementStats
    is_bottleneck: bool
    live: Optional[StationLive]


class HourlyOutput(BaseModel):
    hour: datetime
    output: int
    planned: float


class LineAnalytics(BaseModel):
    line: LineOut
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    stations: list[StationSummary]
    bottleneck_station_id: Optional[int]
    balance_efficiency_pct: Optional[float]
    output: int
    planned_output: float
    throughput_per_hour: Optional[float]
    capacity_per_hour: Optional[float]
    hourly: list[HourlyOutput]
    recommendations: list[Recommendation]


class TrendPoint(BaseModel):
    t: datetime
    cycle_sec: float
    work_sec: float
    motion_waste_sec: float
    wait_sec: float


class HistogramBucket(BaseModel):
    bucket_start: float
    bucket_end: float
    count: int


class HourlyAvg(BaseModel):
    hour: datetime
    avg: Optional[float]
    count: int


class StationAnalytics(BaseModel):
    station: StationOut
    line: LineOut
    prev_station: Optional[StationOut]
    next_station: Optional[StationOut]
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    stats: CycleStats
    movement: MovementStats
    is_bottleneck: bool
    trend: list[TrendPoint]
    histogram: list[HistogramBucket]
    hourly: list[HourlyAvg]
    recommendations: list[Recommendation]
    live: Optional[StationLive]


class OverviewStation(BaseModel):
    id: int
    name: str
    sequence: int
    avg_sec: Optional[float]
    avg_content_sec: Optional[float]
    target_cycle_sec: float
    state: str
    is_bottleneck: bool


class OverviewLine(BaseModel):
    line: LineOut
    output: int
    planned_output: float
    balance_efficiency_pct: Optional[float]
    bottleneck_station_id: Optional[int]
    bottleneck_station_name: Optional[str]
    line_pace_sec: Optional[float]
    stations: list[OverviewStation]
    open_alerts: int


class OverviewTotals(BaseModel):
    output: int
    planned_output: float
    cameras_online: int
    cameras_total: int
    open_alerts: int
    stations: int
    lines: int


class Overview(BaseModel):
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    lines: list[OverviewLine]
    totals: OverviewTotals


class MovementRow(BaseModel):
    station_id: int
    station_name: str
    sequence: int
    line_id: int
    line_name: str
    cycles: int
    avg_cycle_sec: Optional[float]
    avg_content_sec: Optional[float]
    movement: MovementStats


class Heatmap(BaseModel):
    camera_id: int
    cols: int
    rows: int
    grid: list[float]
    max: float


class Track(BaseModel):
    cycle_id: int
    ended_at: datetime
    hand: list[tuple[float, float]]
    body: list[tuple[float, float]]


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    demo_mode: bool
    pose_available: bool
    cameras_running: int
    server_time: datetime


# ---------------------------------------------------------------- simple line + camera setup
class ProbeIn(BaseModel):
    address: str
    username: str = ""
    password: str = ""


class ProbeOut(BaseModel):
    ok: bool
    source_type: Optional[str] = None
    source: Optional[str] = None
    display_source: Optional[str] = None
    width: int = 0
    height: int = 0
    snapshot: Optional[str] = None
    elapsed_ms: int = 0
    tried: int = 0
    error: Optional[str] = None


class SetupStepIn(BaseModel):
    station_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=120)
    camera_address: str = ""  # what the user typed; empty = no camera for this step
    camera_source_type: Optional[SourceType] = None  # from a successful check; None = keep the saved camera
    camera_source: Optional[str] = None


class LineSetupIn(BaseModel):
    line_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=120)
    takt_time_sec: float = Field(60.0, gt=0)
    steps: list[SetupStepIn] = Field(min_length=1)


class LineSetupOut(BaseModel):
    line: LineOut
    stations: list[StationOut]
    cameras: list[CameraOut]
