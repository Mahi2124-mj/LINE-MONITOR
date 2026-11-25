import { Footprints } from 'lucide-react';
import { api } from '../api/client';
import type { ElementKind, Line, RangeKey } from '../api/types';
import { usePolling } from '../hooks/usePolling';
import { fmtSec } from '../lib/format';
import { rangeWindow } from '../lib/range';
import { EmptyState, ErrorState, SkeletonPanel } from './EmptyState';
import { Panel } from './Panel';

const KIND: Record<ElementKind, { label: string; color: string; badge: string }> = {
  work: { label: 'Hand work', color: '#22c55e', badge: 'bg-emerald-500/15 text-emerald-300' },
  walk: { label: 'Walking / carrying', color: '#f59e0b', badge: 'bg-amber-500/15 text-amber-300' },
  wait: { label: 'Waiting for a part or person', color: '#ef4444', badge: 'bg-red-500/15 text-red-300' },
  machine: { label: 'Waiting for the machine', color: '#a78bfa', badge: 'bg-violet-500/15 text-violet-300' },
};
const ORDER: ElementKind[] = ['work', 'walk', 'wait', 'machine'];

/** Movement and waste per person from the checked step detectors: hand work, walking, waiting, machine waits per part. */
export function OperatorMovement({ line, range, rangeTitle }: { line: Line; range: RangeKey; rangeTitle: string }) {
  const r = usePolling(() => rangeWindow(range).then((w) => api.movementReport(line.id, w.start, w.end)), [line.id, range], 60_000);
  const d = r.data;
  if (!d) return r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : <SkeletonPanel className="h-72" />;
  const ops = d.operators.filter((o) => o.per_part);
  if (!ops.length) return null; // no step-detector data for this line
  const scale = Math.max(line.takt_time_sec, ...ops.map((o) => o.cycle_per_part ?? 0)) * 1.05;
  const t = d.totals_per_part;
  const best = [...ops].sort((a, b) => (b.saving_per_part ?? 0) - (a.saving_per_part ?? 0)).filter((o) => (o.saving_per_part ?? 0) >= 0.3);
  return (
    <Panel
      title={`Movement and waste per operator · ${line.name}`}
      subtitle={`From the checked step detectors · seconds per part · ${rangeTitle}`}
      icon={<Footprints className="size-4" />}
    >
      {t && (
        <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
          {ORDER.map((k) => (
            <div key={k} className="rounded-lg border border-edge px-3 py-2">
              <div className="flex items-center gap-1.5 text-xs text-ink-3">
                <span className="size-2.5 rounded-sm" style={{ background: KIND[k].color }} /> {KIND[k].label}
              </div>
              <div className="text-xl font-semibold text-ink tabular-nums">{fmtSec(t[k])}</div>
              <div className="text-[11px] text-ink-3">per part, all operators</div>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-2.5">
        {ops.map((o) => {
          const pp = o.per_part!;
          return (
            <div key={o.label} className="grid grid-cols-[9rem_minmax(0,1fr)_8rem] items-center gap-3 text-sm">
              <div className="min-w-0">
                <div className="truncate font-medium text-ink">{o.label}</div>
                <div className="truncate text-[11px] text-ink-3" title={o.steps.join(', ')}>
                  {o.steps.length > 1 ? `steps ${o.steps.map((s) => s.split('.')[0]).join('+')}` : o.steps[0]}
                </div>
              </div>
              <div className="relative h-6 rounded bg-white/[0.04]">
                <div className="flex h-full overflow-hidden rounded" style={{ width: `${(100 * (o.cycle_per_part ?? 0)) / scale}%` }}>
                  {ORDER.map((k) =>
                    pp[k] > 0.05 ? (
                      <div
                        key={k}
                        className="flex h-full items-center justify-center text-[10px] font-semibold text-black/70"
                        style={{ width: `${(100 * pp[k]) / (o.cycle_per_part || 1)}%`, background: KIND[k].color }}
                        title={`${KIND[k].label}: ${pp[k].toFixed(1)} s per part`}
                      >
                        {pp[k] >= 1 ? pp[k].toFixed(1) : ''}
                      </div>
                    ) : null,
                  )}
                </div>
                <div className="absolute inset-y-0 border-l-2 border-dashed border-slate-300/70" style={{ left: `${(100 * line.takt_time_sec) / scale}%` }} title={`Takt ${line.takt_time_sec} s`} />
              </div>
              <div className="text-right tabular-nums">
                <div className="text-ink">{fmtSec(o.cycle_per_part)}</div>
                <div className="text-[11px] text-amber-300">walk + wait {fmtSec(o.saving_per_part)}</div>
              </div>
            </div>
          );
        })}
        <div className="pl-[9.75rem] text-[11px] text-ink-3">Dashed line = takt {line.takt_time_sec} s. Bar = one part: hand work, walking, waiting for a part, waiting for the machine.</div>
      </div>

      <h3 className="mb-2 mt-5 text-sm font-semibold text-ink">Where time can be won back</h3>
      {best.length ? (
        <ol className="space-y-1.5 text-sm">
          {best.map((o, i) => (
            <li key={o.label} className="flex flex-wrap gap-x-2">
              <span className="text-ink-3">{i + 1}.</span>
              <span className="font-medium text-ink">{o.label}</span>
              <span className="text-ink-2">
                {fmtSec(o.per_part!.walk)} walking and {fmtSec(o.per_part!.wait)} waiting per part
                {o.lost_h ? ` · ${(o.lost_h * 60).toFixed(0)} min in this period` : ''}
              </span>
              <span className="text-ink-3">· mainly {mainLoss(o.elements)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <EmptyState compact title="Little walking or waiting" message="No operator walks or waits more than 0.3 s per part." />
      )}

      <h3 className="mb-2 mt-5 text-sm font-semibold text-ink">Elements per operator</h3>
      <div className="space-y-2">
        {ops.map((o) => (
          <details key={o.label} className="rounded-lg border border-edge">
            <summary className="cursor-pointer px-3 py-2 text-sm text-ink">
              {o.label} <span className="text-ink-3">· {o.steps.join(', ')} · {o.parts} parts</span>
            </summary>
            <div className="overflow-x-auto border-t border-edge">
              <table className="w-full text-sm tabular-nums">
                <thead>
                  <tr className="text-left text-xs text-ink-3">
                    <th className="px-3 py-1.5 font-medium">Element</th>
                    <th className="px-3 py-1.5 font-medium">Kind</th>
                    <th className="px-3 py-1.5 text-right font-medium">s per part</th>
                    <th className="px-3 py-1.5 text-right font-medium">Share of loop</th>
                    <th className="px-3 py-1.5 text-right font-medium">In % of cycles</th>
                  </tr>
                </thead>
                <tbody>
                  {o.elements.map((e) => (
                    <tr key={e.code} className="border-t border-edge/60">
                      <td className="px-3 py-1.5 text-ink-2">
                        {e.label}
                        {e.step && e.step !== o.detector_step && <div className="text-[11px] text-ink-3">timed on step {e.step}</div>}
                      </td>
                      <td className="px-3 py-1.5">
                        <span className={`rounded px-1.5 py-0.5 text-xs ${KIND[e.kind].badge}`}>{KIND[e.kind].label}</span>
                      </td>
                      <td className="px-3 py-1.5 text-right">{e.avg_per_part.toFixed(2)}</td>
                      <td className="px-3 py-1.5 text-right">{e.share_pct}%</td>
                      <td className="px-3 py-1.5 text-right text-ink-3">{e.in_cycles_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="px-3 py-2 text-[11px] text-ink-3">
                Loop timed on step {o.detector_step}
                {o.parts_per_loop && o.parts_per_loop > 1 ? ` (one loop makes ${o.parts_per_loop} parts)` : ''}: {fmtSec(o.loop_sec)}. Walking and waiting come from the
                step whose camera view separates them; hand work is the rest of the loop.
              </p>
            </div>
          </details>
        ))}
      </div>
    </Panel>
  );
}

function mainLoss(elements: { label: string; kind: ElementKind; avg_per_part: number }[]): string {
  const e = elements.filter((x) => x.kind === 'walk' || x.kind === 'wait').sort((a, b) => b.avg_per_part - a.avg_per_part)[0];
  return e ? `${e.label.charAt(0).toLowerCase()}${e.label.slice(1)} (${e.avg_per_part.toFixed(1)} s)` : '—';
}
