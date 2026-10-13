import { Timer } from 'lucide-react';
import type { StationLive } from '../api/types';
import { extrapolateElapsed, useLiveStates } from '../context/LiveContext';
import { useNow } from '../hooks/useNow';
import { fmtSec } from '../lib/format';
import { ProgressBar } from './ProgressBar';

interface LiveCycleTimerProps {
  live: StationLive | null;
  targetSec: number;
  size?: 'sm' | 'lg';
  className?: string;
}

/** Running cycle time, ticking client-side between WS updates, with progress against the target. */
export function LiveCycleTimer({ live, targetSec, size = 'sm', className = '' }: LiveCycleTimerProps) {
  const { receivedAt } = useLiveStates();
  const running = live?.cycle_elapsed_sec !== null && live?.cycle_elapsed_sec !== undefined;
  const now = useNow(200, running);
  const elapsed = extrapolateElapsed(live, receivedAt, now);
  const over = elapsed !== null && targetSec > 0 && elapsed > targetSec;
  const pctOfTarget = elapsed !== null && targetSec > 0 ? (elapsed / targetSec) * 100 : 0;

  return (
    <div className={className}>
      <div className="flex items-baseline justify-between gap-2">
        <span className={`flex items-center gap-1 text-ink-3 ${size === 'lg' ? 'text-xs' : 'text-[11px]'}`}>
          <Timer className={size === 'lg' ? 'size-3.5' : 'size-3'} />
          {running ? 'Current cycle' : 'No cycle running'}
        </span>
        <span
          className={`font-semibold tabular-nums ${size === 'lg' ? 'text-3xl' : 'text-lg'} ${
            elapsed === null ? 'text-ink-3' : over ? 'text-rose-400' : 'text-ink'
          }`}
        >
          {elapsed === null ? '—' : fmtSec(elapsed)}
        </span>
      </div>
      <ProgressBar value={pctOfTarget} tone={over ? 'bad' : 'good'} height={size === 'lg' ? 'md' : 'xs'} className="mt-1" />
      <div className="mt-0.5 flex justify-between text-[10px] text-ink-3 tabular-nums">
        <span>0</span>
        <span>target {fmtSec(targetSec)}</span>
      </div>
    </div>
  );
}
