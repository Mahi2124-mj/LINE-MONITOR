import type { Tone } from '../components/KpiTile';

/** Output attainment (output / planned, %). */
export function attainmentTone(pct: number | null): Tone {
  if (pct === null) return 'muted';
  if (pct >= 95) return 'good';
  if (pct >= 80) return 'warn';
  return 'bad';
}

/** Line balance efficiency %. */
export function balanceTone(pct: number | null): Tone {
  if (pct === null) return 'muted';
  if (pct >= 85) return 'good';
  if (pct >= 70) return 'warn';
  return 'bad';
}

/** Time vs limit: within = good, over = bad. */
export function limitTone(v: number | null | undefined, limit: number | null | undefined): Tone {
  if (v === null || v === undefined || limit === null || limit === undefined || limit <= 0) return 'default';
  return v > limit ? 'bad' : 'good';
}
