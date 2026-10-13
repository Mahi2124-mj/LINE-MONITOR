import type { ReactNode } from 'react';
import { ProgressBar } from './ProgressBar';

export type Tone = 'default' | 'good' | 'warn' | 'bad' | 'info' | 'muted';

export const TONE_TEXT: Record<Tone, string> = {
  default: 'text-ink',
  good: 'text-emerald-400',
  warn: 'text-amber-400',
  bad: 'text-rose-400',
  info: 'text-sky-400',
  muted: 'text-ink-3',
};

interface KpiTileProps {
  label: ReactNode;
  value: ReactNode;
  /** small text after the value, e.g. "/ 480" or "units" */
  suffix?: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: Tone;
  /** 0..100 progress bar under the value */
  progress?: number | null;
  progressTone?: Tone;
  size?: 'md' | 'lg';
  className?: string;
  title?: string;
}

export function KpiTile({ label, value, suffix, sub, icon, tone = 'default', progress, progressTone, size = 'md', className = '', title }: KpiTileProps) {
  return (
    <div className={`min-w-0 rounded-xl border border-edge bg-panel px-4 py-3 ${className}`} title={title}>
      <div className="flex items-center justify-between gap-2 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
        <span className="truncate">{label}</span>
        {icon && <span className="shrink-0 text-ink-3">{icon}</span>}
      </div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className={`${size === 'lg' ? 'text-3xl' : 'text-2xl'} font-semibold leading-tight tracking-tight tabular-nums ${TONE_TEXT[tone]}`}>{value}</span>
        {suffix && <span className="truncate text-sm text-ink-3 tabular-nums">{suffix}</span>}
      </div>
      {progress !== undefined && progress !== null && <ProgressBar value={progress} tone={progressTone ?? tone} className="mt-2" />}
      {sub && <div className="mt-1 truncate text-xs text-ink-3">{sub}</div>}
    </div>
  );
}
