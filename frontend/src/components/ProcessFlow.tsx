import { Fragment, type ReactNode } from 'react';
import { ArrowRight, Flag, PackageCheck } from 'lucide-react';
import type { StationSummary } from '../api/types';
import { useLiveStates } from '../context/LiveContext';
import { StationCard } from './StationCard';
import { EmptyState } from './EmptyState';

interface ProcessFlowProps {
  stations: StationSummary[];
  taktSec: number;
}

/** Station cards in sequence, connected by arrows that name the next step. Wraps to multiple rows. */
export function ProcessFlow({ stations, taktSec }: ProcessFlowProps) {
  const { states } = useLiveStates();
  if (!stations.length) {
    return <EmptyState compact title="No process steps defined" message="Add stations to this line on the Line setup page." />;
  }
  const sorted = [...stations].sort((a, b) => a.station.sequence - b.station.sequence);

  return (
    <div className="flex flex-wrap items-stretch gap-y-4">
      <FlowEndpoint label="Line start" icon={<Flag className="size-4" />} />
      {sorted.map((s, i) => {
        const next = sorted[i + 1];
        return (
          <Fragment key={s.station.id}>
            {/* connector + card form one unit so a wrapped row starts with an arrow naming the step */}
            <div className="flex shrink-0 items-stretch">
              <Connector to={`Step ${s.station.sequence}`} />
              <div className="w-[236px] shrink-0">
                <StationCard
                  station={s.station}
                  stats={s.stats}
                  live={states.get(s.station.id) ?? s.live}
                  isBottleneck={s.is_bottleneck}
                  taktSec={taktSec}
                  className="h-full"
                />
              </div>
            </div>
            {!next && (
              <div className="flex shrink-0 items-stretch">
                <Connector to="Out" />
                <FlowEndpoint label="Finished unit" icon={<PackageCheck className="size-4" />} />
              </div>
            )}
          </Fragment>
        );
      })}
    </div>
  );
}

function Connector({ to }: { to: string }) {
  return (
    <div className="flex w-12 shrink-0 flex-col items-center justify-center gap-0.5 text-ink-3" aria-hidden>
      <span className="text-[9px] font-semibold uppercase tracking-wider whitespace-nowrap">{to}</span>
      <div className="flex w-full items-center">
        <div className="h-0.5 flex-1 rounded bg-gradient-to-r from-edge-2 to-ink-3" />
        <ArrowRight className="-ml-1.5 size-4 shrink-0 text-ink-2" />
      </div>
    </div>
  );
}

function FlowEndpoint({ label, icon }: { label: string; icon: ReactNode }) {
  return (
    <div className="flex w-16 shrink-0 flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-edge-2 px-1 text-center text-[10px] font-medium text-ink-3">
      {icon}
      {label}
    </div>
  );
}
