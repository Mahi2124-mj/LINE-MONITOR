// Formatting helpers. All figures use tabular-nums in the UI (set globally in index.css).

export const DASH = '—';

const isNum = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v);

/** Seconds as "42.3s"; >= 60s as "1m 05s"; >= 1h as "1h 02m". */
export function fmtSec(v: number | null | undefined, decimals = 1): string {
  if (!isNum(v)) return DASH;
  const neg = v < 0;
  const s = Math.abs(v);
  let out: string;
  if (s < 60) out = `${s.toFixed(decimals)}s`;
  else if (s < 3600) {
    const m = Math.floor(s / 60);
    const r = Math.round(s - m * 60);
    out = r === 60 ? `${m + 1}m 00s` : `${m}m ${String(r).padStart(2, '0')}s`;
  } else {
    const h = Math.floor(s / 3600);
    const m = Math.round((s - h * 3600) / 60);
    out = m === 60 ? `${h + 1}h 00m` : `${h}h ${String(m).padStart(2, '0')}m`;
  }
  return neg ? `-${out}` : out;
}

/** Duration that is usually long (uptime, stoppage). Same as fmtSec but 0 decimals below a minute. */
export function fmtDuration(v: number | null | undefined): string {
  return fmtSec(v, 0);
}

/** Signed seconds delta like "+3.2s" / "-1.0s". */
export function fmtDelta(v: number | null | undefined, decimals = 1): string {
  if (!isNum(v)) return DASH;
  const sign = v > 0 ? '+' : v < 0 ? '-' : '±';
  return `${sign}${fmtSec(Math.abs(v), decimals)}`;
}

export function fmtNum(v: number | null | undefined, decimals = 0): string {
  if (!isNum(v)) return DASH;
  return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** Value already in percent (0..100). */
export function fmtPct(v: number | null | undefined, decimals = 0): string {
  if (!isNum(v)) return DASH;
  return `${v.toFixed(decimals)}%`;
}

export function fmtMeters(v: number | null | undefined, decimals = 2): string {
  if (!isNum(v)) return DASH;
  return `${v.toFixed(decimals)} m`;
}

/** Parse the backend's local-time ISO string (no timezone) as local time. */
export function parseTs(ts: string | null | undefined): Date | null {
  if (!ts) return null;
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function fmtTime(ts: string | null | undefined, withSeconds = true): string {
  const d = parseTs(ts);
  if (!d) return DASH;
  return d.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: withSeconds ? '2-digit' : undefined,
    hour12: false,
  });
}

export function fmtHour(ts: string | null | undefined): string {
  const d = parseTs(ts);
  if (!d) return DASH;
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function fmtDateTime(ts: string | null | undefined): string {
  const d = parseTs(ts);
  if (!d) return DASH;
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  if (sameDay) return time;
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${time}`;
}

/** Short tick label for time axes: HH:MM when the span is < 2 days, else "Oct 8 14h". */
export function fmtAxisTime(ts: string | number, spanMs: number): string {
  const d = typeof ts === 'number' ? new Date(ts) : parseTs(ts);
  if (!d) return '';
  if (spanMs < 2 * 86400_000) return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${String(d.getHours()).padStart(2, '0')}h`;
}

/**
 * Analytics `hourly[]` buckets are hourly for ranges <= 48h but DAILY for 7d / 30d.
 * Detect the bucket size from the gap between consecutive bucket starts.
 */
export type BucketKind = 'hour' | 'day';

export function bucketKind(starts: string[]): BucketKind {
  for (let i = 1; i < starts.length; i++) {
    const a = parseTs(starts[i - 1]);
    const b = parseTs(starts[i]);
    if (a && b) return b.getTime() - a.getTime() >= 20 * 3600_000 ? 'day' : 'hour';
  }
  return 'hour';
}

/** Axis tick for a bucket start: "14:00" (hourly, short span), "8 Oct 14h" (hourly, long span) or "8 Oct" (daily). */
export function fmtBucketTick(ts: string, kind: BucketKind, spanMs: number): string {
  const d = parseTs(ts);
  if (!d) return '';
  if (kind === 'day') return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
  return fmtAxisTime(ts, spanMs);
}

/** Tooltip title for a bucket: "Thu 8 Oct" or "8 Oct 14:00–15:00". */
export function fmtBucketTitle(ts: string, kind: BucketKind): string {
  const d = parseTs(ts);
  if (!d) return DASH;
  if (kind === 'day') return d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  const end = new Date(d.getTime() + 3600_000);
  const hm = (x: Date) => x.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${hm(d)}–${hm(end)}`;
}

export function fmtRelative(ts: string | null | undefined, now = Date.now()): string {
  const d = parseTs(ts);
  if (!d) return DASH;
  const diff = Math.round((now - d.getTime()) / 1000);
  if (diff < 5) return 'just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

/** True when the error means the backend is not running / not reachable (network error or proxy 5xx). */
export function isBackendDown(err: unknown): boolean {
  if (err instanceof TypeError) return true; // fetch network failure
  const status = (err as { status?: number } | null)?.status;
  return status === 502 || status === 503 || status === 504; // Vite dev proxy answers 502 when the backend (:6010) is down
}

export function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

export function pct(part: number | null | undefined, whole: number | null | undefined): number | null {
  if (!isNum(part) || !isNum(whole) || whole <= 0) return null;
  return (part / whole) * 100;
}
