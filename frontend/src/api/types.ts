// API contract shared with the FastAPI backend (backend/app/schemas.py).
// All timestamps are local-time ISO strings without timezone, e.g. "2026-10-08T10:15:30".
// All zone / track coordinates are normalized to 0..1 of the camera frame.

export type ZoneType = 'work_area' | 'part_zone' | 'trigger_zone' | 'pick_zone' | 'exclusion' | 'stroke_zone';
export type CycleMethod = 'part_presence' | 'trigger_zone' | 'activity';
export type SourceType = 'rtsp' | 'http' | 'usb' | 'file' | 'simulated';
export type TrackerType = 'auto' | 'pose' | 'motion' | 'simulated';
export type StationState = 'working' | 'idle' | 'waiting' | 'offline' | 'no_camera';
export type Severity = 'info' | 'warning' | 'critical';
export type RangeKey = '1h' | 'shiftA' | 'shiftB' | 'today' | '24h' | '7d' | '30d';
/** the newest run of each shift over the active lines' time slots (null: no line has it) */
export type Shifts = Record<'A' | 'B', { start: string; end: string } | null>;

export interface Line {
  id: number;
  name: string;
  code: string;
  description: string;
  takt_time_sec: number; // customer-demand pace; target output/hr = 3600 / takt
  shift_start: string; // "08:00"
  shift_end: string; // "20:00"
  slot_plan: SlotPlan[]; // planned output per time slot of the day; empty = takt × shift
  off_days?: string[]; // "2026-10-20": no production that day (no plan, no stoppage alerts)
  is_active: boolean;
  created_at: string;
  station_count: number;
  camera_count: number;
}
/** Planned output of one time slot (a slot with a break has a lower plan). */
export interface SlotPlan {
  start: string; // "08:30"
  end: string; // "09:30"
  plan: number;
  shift?: string | null; // "A" (morning), "B" (night); empty: from the gaps between the slots
}
export type LineInput = Pick<Line, 'name' | 'code' | 'description' | 'takt_time_sec' | 'shift_start' | 'shift_end' | 'is_active'> & {
  slot_plan?: SlotPlan[];
  off_days?: string[];
};

/** A Station is one process step of a line. The "next step" is the station with the next sequence. */
export interface Station {
  id: number;
  line_id: number;
  sequence: number; // 1-based order inside the line
  name: string;
  code: string;
  operation: string; // what work happens at this step
  parts_added: string[]; // parts that get added at this step
  target_cycle_sec: number;
  expected_picks: number; // expected part/tool picks per cycle (baseline for extra-motion detection)
  operator_name: string; // steps with the same operator name are run by one person (one loop)
  parallel_group: string; // steps with the same parallel group are copies of one machine sharing the parts
  is_active: boolean;
  camera_ids: number[];
}
export type StationInput = Pick<
  Station,
  'line_id' | 'name' | 'code' | 'operation' | 'parts_added' | 'target_cycle_sec' | 'expected_picks' | 'operator_name' | 'is_active'
> & { sequence?: number; parallel_group?: string };

export interface Zone {
  id: string;
  name: string;
  type: ZoneType;
  station_id: number | null; // null -> inherits camera.station_id
  points: [number, number][]; // polygon, normalized 0..1
}

export interface SimProfile {
  speed_factor: number; // >1 = slower operator
  far_reach_prob: number; // chance a pick goes to a far bin (outside work area)
  walk_prob: number; // chance per cycle that the operator walks away
  extra_pick_prob: number; // chance of an extra (unnecessary) pick
}

export interface CameraConfig {
  cycle_method: CycleMethod;
  tracker: TrackerType;
  process_fps: number;
  min_cycle_sec: number;
  max_cycle_sec: number;
  presence_threshold: number; // 0..1 fraction of zone pixels changed vs reference => part present
  presence_debounce_sec: number;
  idle_timeout_sec: number;
  meters_per_frame_width: number; // calibration used when pose shoulder-width scale is unavailable
  analyzers: string[]; // enabled analyzer keys (see GET /api/analyzers)
  use_substream: boolean; // IP cameras: analyse the low-res sub stream when the brand supports it
  sim: SimProfile | null; // only for source_type === 'simulated'
}

export interface CameraStatus {
  online: boolean;
  fps: number;
  last_frame_at: string | null;
  error: string | null;
  tracker: string; // tracker actually in use
  width: number;
  height: number;
  needs_reference: boolean; // part_presence method without an empty reference image
}

export interface Camera {
  id: number;
  line_id: number;
  station_id: number | null;
  name: string;
  source_type: SourceType;
  source: string; // rtsp://..., "0" for usb, file path, or "sim"
  enabled: boolean;
  zones: Zone[];
  config: CameraConfig;
  has_reference: boolean;
  status: CameraStatus;
}
export type CameraInput = Pick<Camera, 'line_id' | 'station_id' | 'name' | 'source_type' | 'source' | 'enabled'> & {
  zones?: Zone[];
  config?: Partial<CameraConfig>;
};

export interface AnalyzerInfo {
  key: string;
  name: string;
  description: string;
  available: boolean; // false => planned / coming soon
  default_enabled: boolean;
}

/**
 * One completed cycle at a station.
 * cycle_sec ~= work_sec + motion_waste_sec + wait_sec
 * operator content (used for bottleneck / line balance) = work_sec + motion_waste_sec
 */
export interface CycleRecord {
  id: number;
  station_id: number;
  line_id: number;
  camera_id: number | null;
  started_at: string;
  ended_at: string;
  cycle_sec: number;
  work_sec: number; // value-added work (hands active inside work area)
  motion_waste_sec: number; // reaching outside work area, walking, operator away
  wait_sec: number; // waiting for part / idle / blocked
  hand_travel_m: number;
  reach_count: number;
  walk_m: number;
  pick_count: number;
  source: 'vision' | 'simulated' | 'manual' | 'seed';
  over_target: boolean;
}

export interface StationLive {
  station_id: number;
  line_id: number;
  state: StationState;
  cycle_elapsed_sec: number | null; // running time of current cycle
  last_cycle_sec: number | null;
  count_today: number;
  avg_today_sec: number | null;
  operator_present: boolean;
  part_present: boolean;
  updated_at: string;
}

export interface Alert {
  id: number;
  line_id: number | null;
  station_id: number | null;
  camera_id: number | null;
  type: 'bottleneck' | 'slow_cycle' | 'stoppage' | 'camera_offline' | 'excess_motion' | 'over_takt' | 'unbalanced';
  severity: Severity;
  message: string;
  created_at: string;
  acknowledged: boolean;
}

export interface CycleStats {
  count: number;
  avg: number | null;
  median: number | null;
  p90: number | null;
  min: number | null;
  max: number | null;
  std: number | null;
  cv: number | null; // coefficient of variation (std/avg)
  avg_work: number | null;
  avg_motion_waste: number | null;
  avg_wait: number | null;
  avg_content: number | null; // avg_work + avg_motion_waste (operator time)
  over_target_pct: number | null;
  over_takt_pct: number | null;
}

export interface MovementStats {
  avg_hand_travel_m: number | null;
  avg_reach_count: number | null;
  avg_walk_m: number | null;
  avg_pick_count: number | null;
  expected_picks: number;
  va_pct: number | null; // value-added share of cycle time
  motion_waste_pct: number | null;
  wait_pct: number | null;
  est_saving_sec: number | null; // achievable saving per cycle by removing extra motion
}

export interface Recommendation {
  id: string;
  line_id: number | null;
  station_id: number | null;
  category: 'balancing' | 'motion' | 'waiting' | 'stability' | 'target' | 'setup';
  severity: Severity;
  title: string;
  detail: string;
  est_saving_sec: number | null;
}

export interface StationSummary {
  station: Station;
  stats: CycleStats;
  movement: MovementStats;
  is_bottleneck: boolean;
  live: StationLive | null;
}

export interface HourlyOutput {
  hour: string; // ISO of hour start (or of the time slot)
  output: number;
  planned: number;
  end?: string | null; // set when the buckets are the line's time slots
  label?: string | null; // "08:30-09:30"
}

/** Today's plan vs actual of one time slot. */
export interface SlotRow {
  label: string;
  start: string;
  end: string;
  plan: number;
  plan_to_now: number; // running slot: plan × elapsed share
  actual: number | null; // null = slot not started
  variance: number | null; // actual − plan (done) or actual − plan to now (running)
  status: 'done' | 'running' | 'future';
  shift: string; // A, B
}

/** One person in the line balance: a person who runs several steps in one loop is one entry. */
export interface OperatorBalance {
  label: string; // e.g. "Op 1 (steps 1+2+3)" or "Step 5: Bending m/c" for a step without an operator name
  station_ids: number[];
  sequences: number[];
  count: number;
  loop_sec: number | null; // one loop (average cycle of his steps)
  loop_content_sec: number | null;
  parts_per_loop: number; // copies of a parallel machine in his loop
  per_part_sec: number | null; // operator time per part = loop content / parts per loop (used for balance)
  work_sec: number | null; // per part
  motion_sec: number | null;
  wait_sec: number | null;
  is_bottleneck: boolean;
}

export interface LineAnalytics {
  line: Line;
  from: string;
  to: string;
  stations: StationSummary[]; // ordered by sequence
  operators: OperatorBalance[]; // the balance per person
  bottleneck_station_id: number | null;
  bottleneck_label: string | null; // the bottleneck person
  line_pace_sec: number | null; // his time per part
  balance_efficiency_pct: number | null; // sum(time per part) / (people * slowest person's time per part)
  output: number; // parts finished in range (with a slot plan: inside the planned time slots)
  output_outside_plan?: number; // parts finished outside the planned time slots (a night shift, overtime)
  planned_output: number; // from takt & shift windows in range
  throughput_per_hour: number | null;
  capacity_per_hour: number | null; // 3600 / bottleneck person's time per part
  hourly: HourlyOutput[];
  slots_today: SlotRow[]; // today's plan vs actual per time slot (lines with a slot plan)
  recommendations: Recommendation[];
  shifts?: ShiftResult[]; // the newest run of each shift, newest first
}

export interface TrendPoint {
  t: string;
  cycle_sec: number;
  work_sec: number;
  motion_waste_sec: number;
  wait_sec: number;
}

export interface HistogramBucket {
  bucket_start: number;
  bucket_end: number;
  count: number;
}

export interface StationAnalytics {
  station: Station;
  line: Line;
  prev_station: Station | null;
  next_station: Station | null;
  from: string;
  to: string;
  stats: CycleStats;
  movement: MovementStats;
  is_bottleneck: boolean;
  trend: TrendPoint[]; // downsampled to <= 300 points
  histogram: HistogramBucket[];
  hourly: { hour: string; avg: number | null; count: number }[];
  recommendations: Recommendation[];
  live: StationLive | null;
}

export interface OverviewStation {
  id: number;
  name: string;
  sequence: number;
  avg_sec: number | null; // avg cycle time
  avg_content_sec: number | null; // avg operator content
  target_cycle_sec: number;
  state: StationState;
  is_bottleneck: boolean;
}

/** the newest run of one shift (A morning, B night): parts finished in its time slots vs its plan so far */
export interface ShiftResult {
  name: string;
  start: string;
  end: string;
  output: number;
  planned_output: number;
  running: boolean;
}
export interface OverviewLine {
  shifts?: ShiftResult[]; // newest first
  line: Line;
  output: number;
  output_outside_plan?: number;
  planned_output: number;
  balance_efficiency_pct: number | null;
  bottleneck_station_id: number | null;
  bottleneck_station_name: string | null;
  line_pace_sec: number | null; // bottleneck content = effective line cycle time
  stations: OverviewStation[];
  open_alerts: number;
}

export interface Overview {
  from: string;
  to: string;
  lines: OverviewLine[];
  totals: {
    output: number;
    output_outside_plan?: number;
    planned_output: number;
    cameras_online: number;
    cameras_total: number;
    open_alerts: number;
    stations: number;
    lines: number;
  };
}

export interface MovementRow {
  station_id: number;
  station_name: string;
  sequence: number;
  line_id: number;
  line_name: string;
  cycles: number;
  avg_cycle_sec: number | null;
  avg_content_sec: number | null;
  movement: MovementStats;
}

export interface Heatmap {
  camera_id: number;
  cols: number;
  rows: number;
  grid: number[]; // row-major, length cols*rows
  max: number;
}

export interface Track {
  cycle_id: number;
  ended_at: string;
  hand: [number, number][]; // normalized wrist path
  body: [number, number][]; // normalized body-center path
}

export interface Health {
  status: 'ok';
  version: string;
  demo_mode: boolean;
  pose_available: boolean;
  cameras_running: number;
  server_time: string;
}

export type WsMessage =
  | { type: 'states'; data: StationLive[] }
  | { type: 'cycle'; data: CycleRecord }
  | { type: 'alert'; data: Alert }
  | { type: 'camera_status'; data: CameraStatus & { camera_id: number } };

// ---------------------------------------------------------------- simple line + camera setup
/** Result of "Check camera": what the user typed resolved to a working stream + one frame. */
export interface ProbeResult {
  ok: boolean;
  source_type: SourceType | null;
  source: string | null; // full URL incl. credentials, send back unchanged when saving
  display_source: string | null; // password masked
  width: number;
  height: number;
  snapshot: string | null; // data:image/jpeg;base64,...
  elapsed_ms: number;
  tried: number;
  error: string | null;
}

export interface LineSetupStep {
  station_id: number | null;
  name: string;
  camera_address: string; // empty = no camera for this step
  camera_source_type: SourceType | null; // from a successful check; null = keep the saved camera
  camera_source: string | null;
}

export interface LineSetupInput {
  line_id: number | null;
  name: string;
  takt_time_sec: number;
  steps: LineSetupStep[];
}

export interface LineSetupResult {
  line: Line;
  stations: Station[];
  cameras: Camera[];
}
// ---------------------------------------------------------------- cycle / element analysis
/** -2 = operator away / not visible */
export const AWAY_ELEMENT = -2;

export interface AnalysisElement {
  id: number;
  name: string;
  desc: string; // e.g. "left hand at Bin A, right hand at Part fixture"
  color: string;
  center: [number, number, number, number];
  rep_t: number;
  in_standard: boolean;
  renamed?: boolean;
}

export interface AnalysisStandard {
  seq: number[]; // element ids in standard order
  durations: number[]; // seconds per position in seq
  total: number; // typical (median) cycle time
  rates?: number[]; // share of cycles in which each element is done
  counts?: number[]; // usual number of times per cycle
  limits?: number[]; // longest normal time per element (above = "slower than standard")
  total_limit?: number;
  other?: number; // typical time outside the standard elements
  optional?: number[]; // elements done in some cycles only (normal variation, not reported)
  source: 'auto' | 'master';
  master_cycle_id: number | null;
  support: number | null; // share of cycles that contain every must-do element
}

export interface AnalysisIssue {
  type: 'slow' | 'short' | 'missing' | 'repeat' | 'extra' | 'order' | 'away' | 'cycle' | 'reach';
  severity: Severity;
  element: number | null;
  delta: number | null;
  text: string;
}

export interface CycleElement {
  id: number;
  name: string;
  start: number; // seconds from cycle start
  dur: number;
  std: number | null;
  delta: number | null;
  cont?: boolean; // continuation of the previous same element after the operator came back
}

export interface AnalysisSummary {
  camera_id: number;
  camera_name: string;
  station_id: number | null;
  station_name: string | null;
  line_id: number;
  recording: boolean;
  process_fps: number | null;
  camera_online: boolean;
  data: { first_ts: number; last_ts: number; minutes: number } | null;
  learn_after_min: number;
  state: 'not_recording' | 'collecting' | 'ready';
  model: {
    version: number;
    created_at: string;
    cycles_learned: number;
    cycle_start: number;
    elements: AnalysisElement[];
    standard: AnalysisStandard;
  } | null;
  stats: {
    cycles: number;
    ok: number;
    with_issues: number;
    avg_cycle: number;
    median_cycle: number;
    best_cycle: number;
    elements: { id: number; name: string; count: number; avg: number; median: number; p90: number }[];
    top_issues: { type: string; element: number | null; count: number; text: string }[];
  } | null;
}

export interface AnalysisCycleRow {
  id: number;
  camera_id: number;
  start_ts: number; // unix seconds
  end_ts: number;
  cycle_sec: number;
  status: 'ok' | 'issues';
  is_master: boolean;
  issue_count: number;
  top_issue: string | null;
  elements: { id: number; start: number; dur: number }[];
}

export interface AnalysisCycleDetail extends Omit<AnalysisCycleRow, 'elements' | 'top_issue'> {
  elements: CycleElement[];
  issues: AnalysisIssue[];
  standard: AnalysisStandard | null;
  prev_id: number | null;
  next_id: number | null;
}

export interface AnalysisCameraRow {
  camera_id: number;
  camera_name: string;
  station_id: number | null;
  recording: boolean;
  has_model: boolean;
}
export interface ReportRow {
  name: string;
  title: string;
  subtitle: string | null;
  camera_id: number | null;
  station_id: number | null;
  cameras: number[]; // all cameras the report covers (e.g. Rail Assy #01 + #02)
  auto: boolean;
  date: string | null;
  window: string | null;
  cycles: number | null;
  median_cycle: number | null;
  highlights: string[];
  created_at: string;
  size_mb: number;
}

export interface ReportStatus {
  running: number | string | null; // camera id being reported now, or "final:<camera id>" (final-station report)
  queue: (number | string)[];
  last: Record<string, { ok: boolean; message: string; at: string; seconds: number }>;
  job_cams: Record<string, number[]>; // report job -> cameras it covers
  job_stations?: Record<string, number[]>; // report job -> the stations it is for (when stations share a camera)
  every_hours: number;
  keep_per_camera: number;
  detector_feed?: { enabled: boolean; owned_stations: number[] }; // steps counted by their checked step detector
}

/* ------------------------------------------------------------------ line reports (Reports pages) */
export interface StepSummary {
  station_id: number;
  sequence: number;
  name: string;
  operator: string;
  total: number;
  normal_cycle: number | null; // median cycle of the step
  avg_cycle: number | null;
  abnormal: number; // cycles longer than 1.5 x normal cycle
  abnormal_pct: number | null;
  work_pct: number | null; // operator work + walking share of the cycle time
  wait_pct: number | null; // waiting for a part or a person
  work_h: number;
  wait_h: number;
}
export interface LineReport {
  line: { id: number; name: string; takt_time_sec: number };
  window: [string, string];
  kpis: {
    total_cycles: number;
    prev_total_cycles: number; // the same length of time just before
    normal: number;
    abnormal: number;
    normal_pct: number | null;
    abnormal_pct: number | null;
    avg_cycle: number | null;
    normal_cycle: number | null;
    work_pct: number | null;
    wait_pct: number | null;
    work_h: number | null;
    wait_h: number | null;
  };
  trend_bucket_sec: number;
  trend: { t: string; cycle: number | null; abnormal: number; n: number }[]; // per time block: median cycle, abnormal and all cycles
  steps: StepSummary[];
}
export interface StationReport {
  station: { id: number; sequence: number; name: string; operator: string; line_id: number };
  prev_id: number | null;
  next_id: number | null;
  window: [string, string];
  kpis: Omit<StepSummary, 'station_id' | 'sequence' | 'name' | 'operator'>;
  histogram: { label: string; count: number }[];
  sequence: { n: number; t: string; cycle: number | null; abnormal: boolean }[];
  recent: { n: number; start: string; cycle: number | null; status: 'Normal' | 'Abnormal'; operator: string; remark: string }[];
  snapshot: { n: number; t: string; cycle: number | null; camera_id: number; frame_ts: number; remark: string } | null;
}
export interface OperatorsReport {
  window: [string, string];
  bucket_sec: number;
  bucket_start: string;
  operators: {
    label: string;
    steps: string[];
    work_h: number | null;
    wait_h: number | null;
    work_pct: number | null;
    cycles: number;
    blocks: { work: number; motion: number; wait: number }[]; // shares of each time block
  }[];
}
export interface VariationReport {
  window: [string, string];
  steps: {
    station_id: number;
    sequence: number;
    name: string;
    total: number;
    normal_cycle: number | null;
    avg: number | null;
    abnormal_count: number;
    abnormal_pct: number | null;
    wait_pct: number | null;
    min: number | null;
    q1: number | null;
    median: number | null;
    q3: number | null;
    max: number | null;
    cv: number | null; // spread of the normal cycles, % of their mean
    abnormal_values: number[];
  }[];
  findings: string[];
}
export type ElementKind = 'work' | 'walk' | 'wait' | 'machine';
/** Movement and waste per person, from the element times of the checked step detectors (per part). */
export interface MovementReport {
  window: [string, string];
  totals_per_part: Record<ElementKind, number> | null; // all people added up
  operators: {
    label: string;
    steps: string[];
    detector_step?: string; // the step whose detector stands for his loop
    parts: number;
    parts_per_loop?: number;
    loop_sec?: number | null;
    cycle_per_part?: number | null;
    per_part: Record<ElementKind, number> | null;
    saving_per_part: number | null; // walking + waiting per part
    saving_per_hour_s?: number | null;
    lost_h: number | null; // walking + waiting in the window
    elements: { code: string; label: string; kind: ElementKind; avg_per_part: number; share_pct: number; in_cycles_pct: number; step?: string }[];
  }[];
}

/* ------------------------------------------------------------------ cycle analysis per machine (checked detectors) */
export interface MachineElementBit {
  code: string;
  start: number; // seconds from the cycle start
  dur: number;
}
export interface MachineAnalysisOverview {
  window: [string, string];
  lines: {
    line: { id: number; name: string; takt_time_sec: number };
    steps: { station_id: number; sequence: number; name: string; checked: boolean; cycles: number; normal_cycle?: number | null; standard?: number | null; issues_pct?: number | null; operator?: string }[];
  }[];
}
export interface MachineAnalysis {
  station: { id: number; sequence: number; name: string; operator: string; line_id: number };
  prev_id: number | null;
  next_id: number | null;
  detector: string | null;
  window: [string, string];
  kpis: { cycles: number; ok: number; with_issues: number; avg_cycle: number | null; normal_cycle: number | null; best_cycle: number | null };
  standard: { source: 'auto' | 'master'; total: number | null; master_id: number | null };
  elements: { code: string; label: string; kind: ElementKind; color: string; standard: number | null; avg: number | null; p90: number | null; presence_pct: number | null }[];
  top_issues: { text: string; count: number }[];
  cycles: { id: number; start: string; sec: number | null; status: 'ok' | 'issues'; issue_count: number; top_issue: string | null; is_master: boolean; el: MachineElementBit[] }[];
}
/** one window (about a minute) of a machine: every cycle in it, times in seconds from the window start (= video time) */
export interface MachineWindow {
  station: { id: number; sequence: number; name: string };
  camera_id: number | null;
  t0: number; // unix time of the window start
  start: string;
  sec: number;
  fps: number;
  latest_t0: number;
  elements: { code: string; label: string; kind: ElementKind; color: string }[];
  cycles: { n: number; id: number; start: number; end: number; sec: number | null; segs: [string, number, number][] }[];
}
export interface MachineCycleDetail {
  id: number;
  station_id: number;
  camera_id: number | null;
  start: string;
  end: string;
  sec: number | null;
  standard_total: number | null;
  is_master: boolean;
  issues: string[];
  elements: (MachineElementBit & { label: string; kind: ElementKind; color: string; standard: number | null })[];
  prev_id: number | null;
  next_id: number | null;
}

// ------------------------------------------------------------------ shift movement reports (data/movement_reports)
export interface ShiftMovementRow {
  id: string;
  title: string;
  shift: string | null;
  day: string | null;
  partial: boolean;
  window: [number, number];
  generated_at: string;
  operators: { name: string; color: string; measured: number; extra_avg: number | null; extra_share: number | null }[];
}

export interface ShiftMovementStatus {
  running: string | null;
  queue: string[];
  last: { ok?: boolean; report?: string | null; title?: string; message?: string; at?: string; seconds?: number };
  after_end_min: number;
  keep_days: number;
}

export type MovementCause = 'movement' | 'walking' | 'waiting' | 'idle' | 'machine' | 'slower';

export interface ShiftMovementOperator {
  name: string;
  camera: number;
  color: string;
  cycles: number;
  measured: number;
  median_sec: number;
  hands_seen: string[];
  steps: { id: number; sequence: number; name: string }[];
  visible: number;
  sure: number;
  regular_neighbour?: boolean;
  note?: string;
  variants?: Record<string, { ref_sec: number; best_cycles: number; of: number }>;
  ref?: { sec: number | null; walk_sec: number | null; trips: number | null; hand: number | null; cycles: number };
  avg_sec?: number | null;
  extra_avg?: number;
  extra_share?: number;
  extra_min?: number;
  hand_index?: number | null;
  hand_more_share?: number | null;
  walk_avg?: number | null;
  trips_avg?: number | null;
  stops?: number;
  stop_min?: number;
  variation_cv?: number | null;
  causes?: Record<MovementCause, number>;
  causes_where?: Partial<Record<MovementCause, string>>;
  elements?: { code: string; label: string; kind: string; avg: number; ref: number; extra: number }[];
  /** per cycle: end (epoch s), seconds, cause ('' = none / not measured, 'stop'), part variant, band ('best' | 'slower' |
   * 'long' | 'stop' | '' = not compared) */
  series: [number, number, string, string?, string?][];
  events: Record<string, number>;
}

export interface ShiftMovementReport {
  id: string;
  title: string;
  shift?: string;
  day?: string;
  partial?: boolean;
  window: [number, number];
  generated_at: string;
  operators: ShiftMovementOperator[];
  maps: { camera: number; image: string; operators: string[] }[];
  worst: { operator: string; start: number; end: number; sec: number; ref: number; extra: number; cause: string; where: string | null; variant: string; text: string; clip: string | null }[];
  events: { type: 'handling' | 'walking' | 'idle' | 'away'; operator: string; start: number; end: number; text: string; value: number; clip: string | null }[];
  top_causes: { operator: string; cause: MovementCause; minutes: number; cycles: number; per_cycle: number; where: string | null; text: string }[];
  suggestions: string[];
  notes: string[];
  seconds: number;
}
