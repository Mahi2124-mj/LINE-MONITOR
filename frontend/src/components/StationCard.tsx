import { Link } from 'react-router-dom';
import { Package, User } from 'lucide-react';
import type { CycleStats, Station, StationLive } from '../api/types';
import { fmtSec } from '../lib/format';
import { LiveCycleTimer } from './LiveCycleTimer';
import { BottleneckBadge, Chip, StateBadge } from './StateBadge';

interface StationCardProps {
  station: Station;
  stats?: CycleStats | null;
  live: StationLive | null;
  isBottleneck: boolean;
  taktSec: number;
  className?: string;
}

export function StationCard({ station, stats, live, isBottleneck, taktSec, className = '' }: StationCardProps) {
  const avg = stats?.avg ?? live?.avg_today_sec ?? null;
  const content = stats?.avg_content ?? null;
  // Station target and takt are compared with operator content (work + motion), not with the full cycle (which includes waiting).
  const contentOver = content !== null && (content > station.target_cycle_sec || (taktSec > 0 && content > taktSec));

  return (
    <Link
      to={`/stations/${station.id}`}
      className={`group flex w-full flex-col rounded-xl border bg-panel-2 p-3 transition hover:-translate-y-px hover:bg-panel-3 hover:shadow-lg hover:shadow-black/30 ${
        isBottleneck ? 'border-red-500/70 ring-1 ring-red-500/40' : 'border-edge hover:border-edge-2'
      } ${station.is_active ? '' : 'opacity-60'} ${className}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-widest text-ink-3">Step {station.sequence}</div>
          <div className="truncate text-sm font-semibold text-ink" title={station.name}>
            {station.name}
          </div>
        </div>
        <StateBadge state={live?.state ?? (station.camera_ids.length === 0 ? 'no_camera' : 'offline')} size="xs" />
      </div>

      {station.operation && (
        <p className="mt-1 line-clamp-2 min-h-[2.2em] text-xs leading-snug text-ink-2" title={station.operation}>
          {station.operation}
        </p>
      )}

      <div className="mt-2 flex min-h-[22px] flex-wrap items-center gap-1">
        <span className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-ink-3">
          <Package className="size-3" /> Part added:
        </span>
        {station.parts_added.length ? (
          station.parts_added.map((p) => (
            <Chip key={p} className="border-sky-500/30 bg-sky-500/10 text-sky-200">
              {p}
            </Chip>
          ))
        ) : (
          <span className="text-[11px] text-ink-3">—</span>
        )}
      </div>

      <LiveCycleTimer live={live} targetSec={station.target_cycle_sec} className="mt-2.5" />

      <dl className="mt-2.5 grid grid-cols-3 gap-1 border-t border-edge pt-2 text-center">
        <div>
          <dt className="text-[10px] text-ink-3">Last</dt>
          <dd className="text-sm font-semibold text-ink tabular-nums">{fmtSec(live?.last_cycle_sec)}</dd>
        </div>
        <div>
          <dt className="text-[10px] text-ink-3">Avg cycle</dt>
          <dd className="text-sm font-semibold text-ink tabular-nums">{fmtSec(avg)}</dd>
        </div>
        <div title="Operator content = value-added work + motion waste (compared with target & takt; used for bottleneck & balance)">
          <dt className="text-[10px] text-ink-3">Avg content</dt>
          <dd className={`text-sm font-semibold tabular-nums ${content === null ? 'text-ink-3' : contentOver ? 'text-rose-400' : 'text-emerald-400'}`}>{fmtSec(content)}</dd>
        </div>
      </dl>

      <div className="mt-2 flex min-h-[20px] items-center justify-between gap-2 text-[11px] text-ink-3">
        <span className="flex min-w-0 items-center gap-1 truncate">
          {station.operator_name && (
            <>
              <User className="size-3 shrink-0" />
              <span className="truncate">{station.operator_name}</span>
            </>
          )}
        </span>
        {isBottleneck ? <BottleneckBadge size="xs" /> : <span className="tabular-nums">target {fmtSec(station.target_cycle_sec)}</span>}
      </div>
    </Link>
  );
}
