import { clamp } from '../lib/format';
import type { Tone } from './KpiTile';

const BAR: Record<Tone, string> = {
  default: 'bg-sky-500',
  good: 'bg-emerald-500',
  warn: 'bg-amber-500',
  bad: 'bg-rose-500',
  info: 'bg-sky-500',
  muted: 'bg-zinc-500',
};

interface ProgressBarProps {
  /** 0..100 (values above 100 are clamped visually) */
  value: number;
  tone?: Tone;
  className?: string;
  height?: 'xs' | 'sm' | 'md';
  /** optional marker position 0..100 (e.g. expected progress) */
  marker?: number | null;
}

export function ProgressBar({ value, tone = 'default', className = '', height = 'sm', marker }: ProgressBarProps) {
  const h = height === 'xs' ? 'h-1' : height === 'sm' ? 'h-1.5' : 'h-2.5';
  return (
    <div className={`relative w-full overflow-hidden rounded-full bg-panel-3 ${h} ${className}`}>
      <div className={`h-full rounded-full transition-[width] duration-300 ${BAR[tone]}`} style={{ width: `${clamp(value, 0, 100)}%` }} />
      {marker !== undefined && marker !== null && (
        <div className="absolute top-0 h-full w-0.5 bg-ink/70" style={{ left: `${clamp(marker, 0, 100)}%` }} />
      )}
    </div>
  );
}
