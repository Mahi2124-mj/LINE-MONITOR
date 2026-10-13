import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, Footprints, Info, Sparkles } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Rectangle, ResponsiveContainer, Tooltip, XAxis, YAxis, type BarShapeProps } from 'recharts';
import { api } from '../api/client';
import type { MovementRow } from '../api/types';
import { EmptyState, ErrorState, SkeletonPanel, StaleBanner } from '../components/EmptyState';
import { Panel } from '../components/Panel';
import { AXIS_PROPS, TooltipBox } from '../components/charts/ChartTooltip';
import { usePageTitle } from '../context/PageTitleContext';
import { useRange } from '../context/RangeContext';
import { usePolling } from '../hooks/usePolling';
import { fmtMeters, fmtNum, fmtPct, fmtSec } from '../lib/format';
import { BREAKDOWN, CHART } from '../lib/meta';

type SortKey = 'saving' | 'line' | 'cycle' | 'content' | 'va' | 'motion' | 'wait' | 'reach' | 'walk' | 'picks';

const SORTERS: Record<SortKey, (r: MovementRow) => number | string> = {
  saving: (r) => r.movement.est_saving_sec ?? -1,
  line: (r) => `${r.line_name}#${String(r.sequence).padStart(3, '0')}`,
  cycle: (r) => r.avg_cycle_sec ?? -1,
  content: (r) => r.avg_content_sec ?? -1,
  va: (r) => r.movement.va_pct ?? -1,
  motion: (r) => r.movement.motion_waste_pct ?? -1,
  wait: (r) => r.movement.wait_pct ?? -1,
  reach: (r) => r.movement.avg_reach_count ?? -1,
  walk: (r) => r.movement.avg_walk_m ?? -1,
  picks: (r) => (r.movement.avg_pick_count ?? 0) - r.movement.expected_picks,
};

export default function MovementPage() {
  usePageTitle('Movement & waste');
  const { range, rangeTitle } = useRange();
  const [params, setParams] = useSearchParams();
  const lineId = params.get('line') ? Number(params.get('line')) : undefined;
  const lines = usePolling(() => api.lines(), [], 60_000);
  const rows = usePolling(() => api.movement(range, lineId), [range, lineId], 30_000);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'saving', desc: true });

  const sorted = useMemo(() => {
    const list = [...(rows.data ?? [])];
    const f = SORTERS[sort.key];
    list.sort((a, b) => {
      const va = f(a);
      const vb = f(b);
      const c = typeof va === 'string' && typeof vb === 'string' ? va.localeCompare(vb) : (va as number) - (vb as number);
      return sort.desc ? -c : c;
    });
    return list;
  }, [rows.data, sort]);

  const top = useMemo(
    () =>
      [...(rows.data ?? [])]
        .filter((r) => (r.movement.est_saving_sec ?? 0) > 0)
        .sort((a, b) => (b.movement.est_saving_sec ?? 0) - (a.movement.est_saving_sec ?? 0))
        .slice(0, 10)
        .map((r) => ({
          id: r.station_id,
          // short line name ("Line A – Smart Meter Assembly" -> "Line A") so the step name stays readable
          label: `${r.line_name.split(/\s+[–-]\s+/)[0]} · S${r.sequence} ${r.station_name}`,
          saving: r.movement.est_saving_sec ?? 0,
          pctOfCycle: r.avg_cycle_sec ? ((r.movement.est_saving_sec ?? 0) / r.avg_cycle_sec) * 100 : null,
        })),
    [rows.data],
  );

  const totalSaving = (rows.data ?? []).reduce((s, r) => s + (r.movement.est_saving_sec ?? 0), 0);

  const header = (key: SortKey, label: string, right = true) => (
    <th className={right ? 'text-right!' : ''}>
      <button
        type="button"
        className={`inline-flex items-center gap-1 uppercase hover:text-ink ${sort.key === key ? 'text-ink' : ''}`}
        onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== 'line' }))}
      >
        {label}
        {sort.key === key && (sort.desc ? <ArrowDown className="size-3" /> : <ArrowUp className="size-3" />)}
      </button>
    </th>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-3xl text-sm text-ink-2">
          Every step ranked by how much time could be saved per cycle by removing unnecessary motion · {rangeTitle}.
        </p>
        <label className="flex items-center gap-2 text-sm text-ink-2">
          Line
          <select
            className="input w-auto"
            value={lineId ?? ''}
            onChange={(e) => {
              const v = e.target.value;
              setParams(v ? { line: v } : {}, { replace: true });
            }}
          >
            <option value="">All lines</option>
            {lines.data?.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <StaleBanner error={rows.data ? rows.error : null} />

      {!rows.data && rows.loading ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <SkeletonPanel className="h-80" />
          <SkeletonPanel className="h-80" />
        </div>
      ) : !rows.data ? (
        <ErrorState error={rows.error} onRetry={rows.reload} />
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
            <Panel
              title="Top 10 potential savings"
              subtitle={`Seconds per cycle · total ${fmtSec(totalSaving)} across ${rows.data.length} steps`}
              icon={<Sparkles className="size-4" />}
            >
              {top.length ? (
                <div style={{ height: Math.max(180, top.length * 34 + 30) }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={top} layout="vertical" margin={{ top: 0, right: 56, bottom: 0, left: 8 }} barCategoryGap="22%">
                      <CartesianGrid horizontal={false} stroke={CHART.grid} />
                      <XAxis type="number" {...AXIS_PROPS} tickFormatter={(v: number) => `${v}s`} />
                      <YAxis
                        type="category"
                        dataKey="label"
                        {...AXIS_PROPS}
                        width={220}
                        interval={0}
                        tickFormatter={(v: string) => (v.length > 32 ? `${v.slice(0, 31)}…` : v)}
                      />
                      <Tooltip
                        cursor={{ fill: 'rgba(148,163,184,0.06)' }}
                        content={({ active, payload }) => {
                          if (!active || !payload?.length) return null;
                          const r = payload[0].payload as (typeof top)[number];
                          return (
                            <TooltipBox
                              title={r.label}
                              rows={[
                                { label: 'Est. saving', value: `~${fmtSec(r.saving)} / cycle`, color: BREAKDOWN.motion.hex, emphasis: true },
                                { label: 'Share of cycle', value: fmtPct(r.pctOfCycle, 1) },
                              ]}
                            />
                          );
                        }}
                      />
                      <Bar
                        dataKey="saving"
                        isAnimationActive={false}
                        label={{ position: 'right', fill: '#e6e9ee', fontSize: 11, formatter: (v: unknown) => (typeof v === 'number' ? fmtSec(v) : '') }}
                        shape={(p: BarShapeProps) => <Rectangle x={p.x} y={p.y} width={p.width} height={p.height} radius={[0, 4, 4, 0]} fill={BREAKDOWN.motion.hex} />}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState compact icon={<Footprints className="size-6" strokeWidth={1.5} />} title="No motion savings identified" message="Either there is no movement data yet or all steps are already lean." />
              )}
            </Panel>

            <Panel title="How to read this" icon={<Info className="size-4" />}>
              <ul className="space-y-2.5 text-xs leading-relaxed text-ink-2">
                <li>
                  <b className={BREAKDOWN.work.text}>Value-added (VA)</b> – hands active inside the normal work area, i.e. actually assembling.
                </li>
                <li>
                  <b className={BREAKDOWN.motion.text}>Motion waste</b> – time spent reaching outside the work area (far bins, tools), walking away from the
                  station and extra picks beyond the expected number. Lean calls this <i>motion</i> waste: it can usually be removed by moving bins closer,
                  presenting parts in sequence or fixing tool positions.
                </li>
                <li>
                  <b className={BREAKDOWN.wait.text}>Wait</b> – operator idle: waiting for the part from the previous step, blocked by the next step, or no
                  operator. Not motion waste, but a sign of imbalance.
                </li>
                <li>
                  <b className="text-ink">Reaches</b> = hand excursions outside the work area per cycle · <b className="text-ink">Walk</b> = body travel per
                  cycle · <b className="text-ink">Picks</b> = visits to pick zones vs the expected count.
                </li>
                <li>
                  <b className="text-emerald-400">Est. saving</b> = achievable time per cycle if the extra motion is eliminated. Savings at the bottleneck step
                  increase line output directly.
                </li>
              </ul>
            </Panel>
          </div>

          <Panel title="All steps" subtitle="Click a column to sort · click a step for details" icon={<Footprints className="size-4" />} flush>
            {sorted.length === 0 ? (
              <EmptyState compact title="No stations" />
            ) : (
              <div className="max-h-[640px] overflow-auto">
                <table className="table-dense">
                  <thead>
                    <tr>
                      {header('line', 'Line / step', false)}
                      <th className="text-right!">Cycles</th>
                      {header('cycle', 'Avg cycle')}
                      {header('content', 'Content')}
                      <th>Breakdown</th>
                      {header('va', 'VA %')}
                      {header('motion', 'Motion %')}
                      {header('wait', 'Wait %')}
                      {header('reach', 'Reaches')}
                      {header('walk', 'Walk')}
                      {header('picks', 'Picks / exp.')}
                      {header('saving', 'Est. saving')}
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((r) => {
                      const mv = r.movement;
                      const extraPicks = mv.avg_pick_count !== null && mv.avg_pick_count > mv.expected_picks;
                      return (
                        <tr key={r.station_id}>
                          <td className="max-w-[260px]">
                            <div className="truncate text-[11px] text-ink-3">{r.line_name}</div>
                            <Link to={`/stations/${r.station_id}`} className="block truncate font-medium text-ink hover:text-sky-300">
                              Step {r.sequence} · {r.station_name}
                            </Link>
                          </td>
                          <td className="text-right tabular-nums text-ink-2">{fmtNum(r.cycles)}</td>
                          <td className="text-right tabular-nums">{fmtSec(r.avg_cycle_sec)}</td>
                          <td className="text-right tabular-nums">{fmtSec(r.avg_content_sec)}</td>
                          <td>
                            <MiniBreakdown va={mv.va_pct} motion={mv.motion_waste_pct} wait={mv.wait_pct} />
                          </td>
                          <td className="text-right tabular-nums text-emerald-300/90">{fmtPct(mv.va_pct)}</td>
                          <td className={`text-right tabular-nums ${(mv.motion_waste_pct ?? 0) >= 10 ? 'font-semibold text-orange-300' : 'text-ink-2'}`}>{fmtPct(mv.motion_waste_pct)}</td>
                          <td className="text-right tabular-nums text-ink-2">{fmtPct(mv.wait_pct)}</td>
                          <td className={`text-right tabular-nums ${(mv.avg_reach_count ?? 0) > 0.5 ? 'text-orange-300' : 'text-ink-2'}`}>{fmtNum(mv.avg_reach_count, 1)}</td>
                          <td className={`text-right tabular-nums ${(mv.avg_walk_m ?? 0) > 1 ? 'text-orange-300' : 'text-ink-2'}`}>{fmtMeters(mv.avg_walk_m, 1)}</td>
                          <td className="text-right tabular-nums">
                            <span className={extraPicks ? 'rounded bg-orange-500/15 px-1 font-semibold text-orange-300 ring-1 ring-orange-500/30' : 'text-ink-2'}>
                              {fmtNum(mv.avg_pick_count, 1)}
                            </span>
                            <span className="text-ink-3"> / {fmtNum(mv.expected_picks)}</span>
                          </td>
                          <td className="text-right font-semibold tabular-nums text-emerald-300">
                            {mv.est_saving_sec !== null && mv.est_saving_sec > 0 ? `~${fmtSec(mv.est_saving_sec)}` : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
}

function MiniBreakdown({ va, motion, wait }: { va: number | null; motion: number | null; wait: number | null }) {
  const total = (va ?? 0) + (motion ?? 0) + (wait ?? 0);
  if (total <= 0) return <span className="text-ink-3">—</span>;
  const w = (v: number | null) => `${((v ?? 0) / total) * 100}%`;
  return (
    <div className="flex h-2 w-28 gap-px overflow-hidden rounded-full bg-panel-3" title={`VA ${fmtPct(va)} · motion ${fmtPct(motion)} · wait ${fmtPct(wait)}`}>
      <div style={{ width: w(va), backgroundColor: BREAKDOWN.work.hex }} />
      <div style={{ width: w(motion), backgroundColor: BREAKDOWN.motion.hex }} />
      <div style={{ width: w(wait), backgroundColor: BREAKDOWN.wait.hex }} />
    </div>
  );
}
