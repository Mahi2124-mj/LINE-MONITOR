import { ChevronRight } from 'lucide-react';
import type { OverviewStation, StationLive } from '../api/types';
import { fmtSec } from '../lib/format';
import { STATE_STYLE } from '../lib/meta';

interface ProcessStripProps {
  stations: OverviewStation[];
  live: Map<number, StationLive>;
}

/** Compact horizontal strip of process steps colored by live state; bottleneck outlined red. */
export function ProcessStrip({ stations, live }: ProcessStripProps) {
  if (!stations.length) return <div className="text-xs text-ink-3">No stations configured</div>;
  const sorted = [...stations].sort((a, b) => a.sequence - b.sequence);
  return (
    <div className="flex items-stretch gap-0.5">
      {sorted.map((s, i) => {
        const state = live.get(s.id)?.state ?? s.state;
        const st = STATE_STYLE[state];
        const over = s.avg_content_sec !== null && s.avg_content_sec > s.target_cycle_sec; // content vs target
        return (
          <div key={s.id} className="flex min-w-0 flex-1 items-center gap-0.5">
            <div
              className={`relative flex h-11 min-w-0 flex-1 flex-col justify-center rounded-md border px-1.5 ${st.block} ${
                s.is_bottleneck ? 'outline-2 outline-offset-1 outline-red-500' : ''
              }`}
              title={`Step ${s.sequence}: ${s.name}\nState: ${st.label}\nAvg content (work + motion): ${fmtSec(s.avg_content_sec)} – target ${fmtSec(
                s.target_cycle_sec,
              )}${over ? ' (over target)' : ''}\nAvg cycle incl. wait: ${fmtSec(s.avg_sec)}${s.is_bottleneck ? '\nBOTTLENECK' : ''}`}
            >
              <div className="truncate text-[10px] leading-tight font-bold opacity-80">S{s.sequence}</div>
              <div className="truncate text-[11px] leading-tight font-semibold">{s.name}</div>
              <div className={`truncate text-[10px] leading-tight tabular-nums ${over ? 'font-bold' : 'opacity-80'}`}>
                {fmtSec(s.avg_content_sec)}
                {over ? ' ▲' : ''}
              </div>
            </div>
            {i < sorted.length - 1 && <ChevronRight className="size-3 shrink-0 text-ink-3" />}
          </div>
        );
      })}
    </div>
  );
}
