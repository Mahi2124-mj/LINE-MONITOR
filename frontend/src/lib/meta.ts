// Shared color semantics and human labels. Keep every page consistent by using these maps.
import type { Alert, CycleMethod, Recommendation, Severity, SourceType, StationState, TrackerType, ZoneType } from '../api/types';

export interface StateStyle {
  label: string;
  /** small dot / solid fill */
  dot: string;
  /** badge classes */
  badge: string;
  /** process-strip block classes */
  block: string;
  /** hex for canvas / charts */
  hex: string;
}

export const STATE_STYLE: Record<StationState, StateStyle> = {
  working: {
    label: 'Working',
    dot: 'bg-emerald-400',
    badge: 'bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/40',
    block: 'bg-emerald-500/80 text-emerald-950 border-emerald-400/60',
    hex: '#10b981',
  },
  waiting: {
    label: 'Waiting',
    dot: 'bg-amber-400',
    badge: 'bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/40',
    block: 'bg-amber-400/80 text-amber-950 border-amber-300/60',
    hex: '#f59e0b',
  },
  idle: {
    label: 'Idle',
    dot: 'bg-orange-400',
    badge: 'bg-orange-500/15 text-orange-300 ring-1 ring-inset ring-orange-500/40',
    block: 'bg-orange-500/80 text-orange-950 border-orange-400/60',
    hex: '#f97316',
  },
  offline: {
    label: 'Offline',
    dot: 'bg-zinc-500',
    badge: 'bg-zinc-500/15 text-zinc-300 ring-1 ring-inset ring-zinc-500/40',
    block: 'bg-zinc-600/70 text-zinc-200 border-zinc-500/60',
    hex: '#71717a',
  },
  no_camera: {
    label: 'No camera',
    dot: 'border border-slate-400 bg-transparent',
    badge: 'bg-transparent text-slate-400 ring-1 ring-inset ring-slate-500/60',
    block: 'bg-transparent text-slate-300 border-slate-500 border-dashed',
    hex: '#64748b',
  },
};

export const SEVERITY_STYLE: Record<Severity, { label: string; badge: string; text: string; border: string; dot: string; bg: string }> = {
  info: {
    label: 'Info',
    badge: 'bg-sky-500/15 text-sky-300 ring-1 ring-inset ring-sky-500/40',
    text: 'text-sky-400',
    border: 'border-l-sky-500',
    dot: 'bg-sky-400',
    bg: 'bg-sky-500/10',
  },
  warning: {
    label: 'Warning',
    badge: 'bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/40',
    text: 'text-amber-400',
    border: 'border-l-amber-500',
    dot: 'bg-amber-400',
    bg: 'bg-amber-500/10',
  },
  critical: {
    label: 'Critical',
    badge: 'bg-red-500/15 text-red-300 ring-1 ring-inset ring-red-500/40',
    text: 'text-red-400',
    border: 'border-l-red-500',
    dot: 'bg-red-500',
    bg: 'bg-red-500/10',
  },
};

/** Cycle breakdown colours (chart fills validated for the dark surface). */
export const BREAKDOWN = {
  work: { label: 'Value-added work', short: 'Work', hex: '#059669', text: 'text-emerald-400', bg: 'bg-emerald-600' },
  motion: { label: 'Motion waste', short: 'Motion', hex: '#ea580c', text: 'text-orange-400', bg: 'bg-orange-600' },
  wait: { label: 'Waiting / idle', short: 'Wait', hex: '#64748b', text: 'text-slate-400', bg: 'bg-slate-500' },
} as const;

export const CHART = {
  grid: '#1f252d',
  axis: '#3a424d',
  tick: '#a3acb9',
  takt: '#e2e8f0',
  target: '#38bdf8',
  bottleneck: '#ef4444',
  primary: '#38bdf8',
  planned: '#cbd5e1',
  cycle: '#38bdf8',
  over: '#f43f5e',
} as const;

export interface ZoneMeta {
  label: string;
  color: string; // hex, used for canvas
  description: string;
}

export const ZONE_META: Record<ZoneType, ZoneMeta> = {
  work_area: {
    label: 'Work area',
    color: '#10b981',
    description: 'Normal working envelope of the operator. Hand time inside counts as value-added work; reaches outside it count as motion waste.',
  },
  part_zone: {
    label: 'Part zone',
    color: '#38bdf8',
    description: 'Where the part / fixture sits. A cycle starts when a part appears here and ends when it leaves (compared against the empty reference). A step with 2 fixtures gets 2 part zones: a unit leaving either one counts as a finished cycle.',
  },
  trigger_zone: {
    label: 'Trigger zone',
    color: '#a78bfa',
    description: 'A hand entering this zone marks a cycle boundary (e.g. pressing the done button or placing the part on the outfeed). Used by the trigger_zone method.',
  },
  pick_zone: {
    label: 'Pick zone',
    color: '#f59e0b',
    description: 'Part bins / tool positions. Each hand visit counts as one pick, compared with the station’s expected picks per cycle.',
  },
  exclusion: {
    label: 'Exclusion',
    color: '#f43f5e',
    description: 'Ignored area (other operators, conveyors, screens). Motion here is not analysed.',
  },
  stroke_zone: {
    label: 'Machine stroke',
    color: '#ef4444',
    description: 'Small area around a machine part that moves once per part (carriage, press). Each stroke is one cycle, whatever colour the part has. Overrides the cycle method; counted cycles appear ~30 s after the stroke.',
  },
};

export const ZONE_TYPES = Object.keys(ZONE_META) as ZoneType[];

export const CYCLE_METHOD_META: Record<CycleMethod, { label: string; description: string }> = {
  part_presence: {
    label: 'Part presence',
    description: 'Compares the part zone with an empty reference image. Part arrives → cycle starts, part leaves → cycle ends. Most robust for fixtures; needs a reference capture.',
  },
  trigger_zone: {
    label: 'Trigger zone',
    description: 'A cycle ends each time the operator’s hand enters the trigger zone (e.g. outfeed or button). Good when parts are hard to see.',
  },
  activity: {
    label: 'Activity',
    description: 'Detects cycles from bursts of hand activity in the work area separated by pauses. No zones required, least accurate.',
  },
};

export const TRACKER_META: Record<TrackerType, string> = {
  auto: 'Auto (pose if available, else motion)',
  pose: 'Pose estimation (hands & body keypoints)',
  motion: 'Motion / blob tracking',
  simulated: 'Simulated (demo)',
};

export const SOURCE_TYPE_META: Record<SourceType, { label: string; placeholder: string }> = {
  rtsp: { label: 'RTSP stream', placeholder: 'rtsp://user:pass@192.168.1.20:554/stream1' },
  http: { label: 'HTTP / MJPEG', placeholder: 'http://192.168.1.21/video.mjpg' },
  usb: { label: 'USB camera', placeholder: '0' },
  file: { label: 'Video file', placeholder: 'C:\\videos\\station1.mp4' },
  simulated: { label: 'Simulated (demo)', placeholder: 'sim' },
};

export const ALERT_TYPE_LABEL: Record<Alert['type'], string> = {
  bottleneck: 'Bottleneck',
  slow_cycle: 'Slow cycle',
  stoppage: 'Stoppage',
  camera_offline: 'Camera offline',
  excess_motion: 'Excess motion',
  over_takt: 'Over takt',
  unbalanced: 'Unbalanced line',
};

export const RECO_CATEGORY_LABEL: Record<Recommendation['category'], string> = {
  balancing: 'Line balancing',
  motion: 'Motion waste',
  waiting: 'Waiting',
  stability: 'Stability',
  target: 'Target',
  setup: 'Setup',
};
