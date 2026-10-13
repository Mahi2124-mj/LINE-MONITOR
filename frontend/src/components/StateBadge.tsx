import type { Severity, StationState } from '../api/types';
import { SEVERITY_STYLE, STATE_STYLE } from '../lib/meta';
import { Flame } from 'lucide-react';
import type { ReactNode } from 'react';

export function StateDot({ state, pulse }: { state: StationState; pulse?: boolean }) {
  const s = STATE_STYLE[state];
  return <span className={`inline-block size-2 shrink-0 rounded-full ${s.dot} ${pulse && state === 'working' ? 'animate-pulse-soft' : ''}`} />;
}

export function StateBadge({ state, size = 'sm' }: { state: StationState | null | undefined; size?: 'xs' | 'sm' }) {
  const st = state ?? 'offline';
  const s = STATE_STYLE[st];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-medium whitespace-nowrap ${s.badge} ${
        size === 'xs' ? 'px-1.5 py-px text-[10px]' : 'px-2 py-0.5 text-xs'
      }`}
    >
      <StateDot state={st} pulse />
      {s.label}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY_STYLE[severity];
  return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${s.badge}`}>{s.label}</span>;
}

export function BottleneckBadge({ size = 'sm' }: { size?: 'xs' | 'sm' }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full bg-red-500/15 font-semibold text-red-300 ring-1 ring-inset ring-red-500/50 whitespace-nowrap ${
        size === 'xs' ? 'px-1.5 py-px text-[10px]' : 'px-2 py-0.5 text-xs'
      }`}
      title="Bottleneck: highest operator content (work + motion) on this line"
    >
      <Flame className={size === 'xs' ? 'size-3' : 'size-3.5'} />
      Bottleneck
    </span>
  );
}

export function Chip({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center rounded-md border border-edge-2 bg-panel-3 px-1.5 py-0.5 text-[11px] font-medium text-ink-2 ${className}`}>
      {children}
    </span>
  );
}
