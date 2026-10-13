import { Link } from 'react-router-dom';
import { Footprints, Gauge, Hourglass, Lightbulb, Scale, Target, Wrench, type LucideIcon } from 'lucide-react';
import type { Recommendation } from '../api/types';
import { fmtSec } from '../lib/format';
import { RECO_CATEGORY_LABEL, SEVERITY_STYLE } from '../lib/meta';
import { EmptyState } from './EmptyState';

const CATEGORY_ICON: Record<Recommendation['category'], LucideIcon> = {
  balancing: Scale,
  motion: Footprints,
  waiting: Hourglass,
  stability: Gauge,
  target: Target,
  setup: Wrench,
};

const SEVERITY_ORDER = { critical: 0, warning: 1, info: 2 } as const;

interface RecommendationListProps {
  items: Recommendation[];
  /** map station id -> label for a link chip (line pages) */
  stationLabel?: (stationId: number) => string | undefined;
  emptyText?: string;
}

export function RecommendationList({ items, stationLabel, emptyText = 'No improvement opportunities detected in this range.' }: RecommendationListProps) {
  if (!items.length) {
    return <EmptyState compact icon={<Lightbulb className="size-6" strokeWidth={1.5} />} title="Nothing to recommend" message={emptyText} />;
  }
  const sorted = [...items].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || (b.est_saving_sec ?? 0) - (a.est_saving_sec ?? 0),
  );
  return (
    <ul className="space-y-2">
      {sorted.map((r) => {
        const Icon = CATEGORY_ICON[r.category] ?? Lightbulb;
        const sev = SEVERITY_STYLE[r.severity];
        const label = r.station_id !== null ? stationLabel?.(r.station_id) : undefined;
        return (
          <li key={r.id} className={`flex gap-3 rounded-lg border border-edge border-l-4 ${sev.border} bg-panel-2 px-3 py-2.5`}>
            <div className={`mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg ${sev.bg} ${sev.text}`} title={RECO_CATEGORY_LABEL[r.category]}>
              <Icon className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                <span className="text-sm font-semibold text-ink">{r.title}</span>
                <span className={`text-[10px] font-semibold uppercase tracking-wider ${sev.text}`}>{RECO_CATEGORY_LABEL[r.category]}</span>
                {label && r.station_id !== null && (
                  <Link to={`/stations/${r.station_id}`} className="text-[11px] link">
                    {label}
                  </Link>
                )}
              </div>
              <p className="mt-0.5 text-xs leading-relaxed text-ink-2">{r.detail}</p>
            </div>
            {r.est_saving_sec !== null && r.est_saving_sec > 0 && (
              <div className="shrink-0 text-right" title="Estimated achievable saving per cycle">
                <div className="text-sm font-semibold text-emerald-400 tabular-nums">~{fmtSec(r.est_saving_sec)}</div>
                <div className="text-[10px] text-ink-3">per cycle</div>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
