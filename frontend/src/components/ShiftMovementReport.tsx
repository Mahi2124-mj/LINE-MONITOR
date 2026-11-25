import { useMemo, useState } from 'react';
import { AlertTriangle, Clapperboard, Footprints, Lightbulb, Map as MapIcon, Play, RefreshCw, Sigma, Users } from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/client';
import type { MovementCause, ShiftMovementOperator, ShiftMovementReport as Report } from '../api/types';
import { EmptyState, ErrorState, SkeletonPanel } from './EmptyState';
import { Panel } from './Panel';
import { AXIS_PROPS, ChartLegend, TooltipBox } from './charts/ChartTooltip';
import { usePolling } from '../hooks/usePolling';
import { fmtNum, fmtPct, fmtSec } from '../lib/format';

// colours: the dataviz reference palette (dark), validated on the panel #111419 (adjacent pairs for the stacked bar,
// all pairs for the two scatter colours)
const CAUSES: { key: MovementCause; label: string; color: string }[] = [
  { key: 'movement', label: 'Extra hand movement', color: '#3987e5' },
  { key: 'walking', label: 'Extra walking', color: '#d95926' },
  { key: 'waiting', label: 'Waiting for a part / person', color: '#199e70' },
  { key: 'idle', label: 'Idle hands', color: '#c98500' },
  { key: 'machine', label: 'Machine slower', color: '#d55181' },
  { key: 'slower', label: 'Same movement, slower', color: '#9085e9' },
];
const CAUSE_LABEL: Record<string, string> = Object.fromEntries(CAUSES.map((c) => [c.key, c.label]));
// the cycle chart's classes (first three palette slots: apart in every pair)
const BANDS = [
  { key: 'best', label: 'Like his best', color: '#3987e5' },
  { key: 'slower', label: 'Slower than his best', color: '#d95926' },
  { key: 'long', label: 'Long (over 1.5× his median)', color: '#199e70' },
] as const;
const NOT_COMPARED = '#6b7482';
const EVENT_TYPES: { key: Report['events'][number]['type']; label: string }[] = [
  { key: 'handling', label: 'Much more hand movement' },
  { key: 'walking', label: 'Extra walking' },
  { key: 'idle', label: 'Idle hands' },
  { key: 'away', label: 'Left his place' },
];
const GRID = '#252b34';
const EVENTS_SHOWN = 30; // the biggest ones; the rest behind "Show all"

const clock = (t: number, sec = true) =>
  new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: sec ? '2-digit' : undefined });
const stepsOf = (o: ShiftMovementOperator) => {
  const s = o.steps.map((x) => x.sequence).sort((a, b) => a - b);
  return s.length ? (s.length > 1 ? `Steps ${s[0]}–${s[s.length - 1]}` : `Step ${s[0]}`) : '';
};

/** Shift movement report: each operator against his own best cycles of the shift. */
export function ShiftMovementReport() {
  const list = usePolling(() => api.shiftMovementReports(), [], 60_000);
  const status = usePolling(() => api.shiftMovementStatus(), [], 10_000);
  const [picked, setPicked] = useState<string | null>(null);
  const [shift, setShift] = useState<'A' | 'B'>('A');
  const id = picked ?? list.data?.[0]?.id ?? null;
  const rep = usePolling(() => (id ? api.shiftMovementReport(id) : Promise.resolve(null)), [id], 120_000);
  const st = status.data;
  const busy = !!st && (!!st.running || st.queue.length > 0);

  const generate = async (which: 'current' | 'last') => {
    await api.generateShiftMovement(shift, which).catch(() => null);
    status.reload();
  };

  if (list.error && !list.data) {
    if ((list.error as { status?: number }).status === 404)
      return (
        <Panel>
          <EmptyState
            icon={<Footprints className="size-9" strokeWidth={1.5} />}
            title="Shift movement reports start with the next server restart"
            message="The server running now is older than this page. It is restarted between two shifts; then each shift gets its report."
          />
        </Panel>
      );
    return <ErrorState error={list.error} onRetry={list.reload} />;
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <select className="input w-auto" value={id ?? ''} onChange={(e) => setPicked(e.target.value || null)} aria-label="Shift report">
            {(list.data ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.title}
              </option>
            ))}
            {!list.data?.length && <option value="">No report yet</option>}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <select className="input w-auto" value={shift} onChange={(e) => setShift(e.target.value as 'A' | 'B')} aria-label="Shift to make a report of">
            <option value="A">Shift A</option>
            <option value="B">Shift B</option>
          </select>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => generate('current')} title="The running shift up to now">
            <RefreshCw className={`size-3.5 ${busy ? 'animate-spin' : ''}`} /> So far
          </button>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => generate('last')} title="The last finished run of this shift">
            Last finished
          </button>
        </div>
      </div>
      {st && (busy || (st.last.ok === false && st.last.message)) && (
        <p className={`text-xs ${busy ? 'text-ink-2' : 'text-amber-300'}`}>
          {busy
            ? `Making ${st.running ?? st.queue[0]} (reads the whole shift's video, a few minutes)…`
            : `Last attempt: ${st.last.message}`}
        </p>
      )}
      {!list.data && list.loading ? (
        <SkeletonPanel className="h-72" />
      ) : !list.data?.length ? (
        <Panel>
          <EmptyState
            icon={<Footprints className="size-9" strokeWidth={1.5} />}
            title="No shift report yet"
            message={`Each shift's report is made ${st?.after_end_min ?? 25} minutes after the shift ends (Shift A and Shift B). Use "So far" for the running shift.`}
          />
        </Panel>
      ) : !rep.data ? (
        rep.error ? <ErrorState error={rep.error} onRetry={rep.reload} /> : <SkeletonPanel className="h-72" />
      ) : (
        <ReportBody r={rep.data} />
      )}
    </div>
  );
}

function ReportBody({ r }: { r: Report }) {
  const ops = r.operators;
  const [opName, setOpName] = useState<string>(ops.find((o) => o.measured)?.name ?? ops[0]?.name ?? '');
  const op = ops.find((o) => o.name === opName) ?? ops[0];
  return (
    <div className="space-y-4">
      <p className="max-w-4xl text-sm text-ink-2">
        {r.title}. Every operator is compared with his own best cycles of this shift (the fastest quarter, the same part). Hand and
        walking movement come from the camera, measured in his own body heights. Cycles in which he is not surely seen (someone else
        in his place, hidden, video missing) are left out.
        {r.partial && <span className="text-amber-300"> The shift was still running: this is the shift so far.</span>}
      </p>
      <SummaryTable ops={ops} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Biggest causes of extra time" icon={<AlertTriangle className="size-4" />}>
          {r.top_causes.length ? (
            <ol className="space-y-2 text-sm">
              {r.top_causes.map((c, i) => (
                <li key={i} className="flex gap-3">
                  <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-panel-3 text-xs text-ink-2">{i + 1}</span>
                  <span className="text-ink">
                    {c.text}
                    <span className="text-ink-3"> · {fmtSec(c.per_cycle)} longer per cycle</span>
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm text-ink-3">No cycles slower than the operators' best ones.</p>
          )}
        </Panel>
        <Panel title="Suggestions" icon={<Lightbulb className="size-4" />}>
          {r.suggestions.length ? (
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink">
              {r.suggestions.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-3">Nothing stands out in this shift.</p>
          )}
        </Panel>
      </div>
      <CauseChart ops={ops} />
      <Panel
        title="Cycle time variation (baratsuki)"
        subtitle="Spread of every operator's cycle times, and one operator's cycles over the shift against his best"
        icon={<Sigma className="size-4" />}
      >
        <SpreadRows ops={ops} picked={op?.name} onPick={setOpName} />
        {op && <OperatorCycles r={r} op={op} />}
      </Panel>
      <ClipGrid r={r} />
      <Events r={r} />
      {r.maps.length > 0 && (
        <Panel
          title="Walking maps"
          subtitle="Soft colour: where each operator stood (brighter = longer). Lines: where he walked."
          icon={<MapIcon className="size-4" />}
        >
          <div className="grid gap-3 lg:grid-cols-2">
            {r.maps.map((m) => (
              <figure key={m.camera} className="space-y-1">
                <img src={api.shiftMovementFileUrl(r.id, m.image)} alt={`Walking map ${m.operators.join(', ')}`} className="w-full rounded-lg border border-edge" loading="lazy" />
                <figcaption className="text-xs text-ink-3">{m.operators.join(' · ')}</figcaption>
              </figure>
            ))}
          </div>
        </Panel>
      )}
      <Coverage r={r} />
    </div>
  );
}

function SummaryTable({ ops }: { ops: ShiftMovementOperator[] }) {
  return (
    <Panel title="Operators" subtitle="Against his own best cycles of this shift" icon={<Users className="size-4" />} flush>
      <div className="overflow-x-auto">
        <table className="w-full text-sm tabular-nums">
          <thead>
            <tr className="border-b border-edge text-left text-xs text-ink-3">
              {['Operator', 'Cycles measured', 'Avg cycle', 'Best cycles', 'Extra per cycle', 'Cycles slower than best', 'Extra time', 'Hand movement vs best', 'Walking per cycle', 'Unusual actions', 'Variation'].map(
                (h, i) => (
                  <th key={h} className={`px-3 py-2 font-medium ${i ? 'text-right' : ''}`}>
                    {h}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {ops.map((o) => {
              const ev = Object.values(o.events ?? {}).reduce((a, b) => a + b, 0);
              return (
                <tr key={o.name} className="border-b border-edge/60">
                  <td className="px-3 py-1.5">
                    <div className="flex items-center gap-2 whitespace-nowrap">
                      <span className="size-2.5 shrink-0 rounded-full" style={{ background: o.color }} />
                      <span className="font-medium text-ink">{o.name}</span>
                      <span className="text-xs text-ink-3">{stepsOf(o)}</span>
                    </div>
                    {o.note && <div className="text-xs text-amber-300/90">{o.note}</div>}
                  </td>
                  <td className="px-3 py-1.5 text-right text-ink-2">
                    {fmtNum(o.measured)} / {fmtNum(o.cycles)}
                  </td>
                  <td className="px-3 py-1.5 text-right">{fmtSec(o.avg_sec)}</td>
                  <td className="px-3 py-1.5 text-right" title={variantsText(o)}>
                    {fmtSec(o.ref?.sec)}
                  </td>
                  <td className="px-3 py-1.5 text-right font-semibold text-ink">{o.ref ? `+${fmtSec(o.extra_avg)}` : '—'}</td>
                  <td className="px-3 py-1.5 text-right">{o.ref ? fmtPct((o.extra_share ?? 0) * 100) : '—'}</td>
                  <td className="px-3 py-1.5 text-right">{o.ref ? `${fmtNum(o.extra_min, 1)} min` : '—'}</td>
                  <td className="px-3 py-1.5 text-right" title={o.hands_seen.length ? `Hands seen by the camera: ${o.hands_seen.join(', ')}` : 'His hands are hidden from the camera'}>
                    {o.hand_index != null ? `${o.hand_index.toFixed(2)}×` : <span className="text-ink-3">hands hidden</span>}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    {o.walk_avg != null ? (
                      <>
                        {fmtSec(o.walk_avg)}
                        <span className="text-ink-3"> (best {fmtSec(o.ref?.walk_sec)})</span>
                      </>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-right">{o.ref ? fmtNum(ev) : '—'}</td>
                  <td className="px-3 py-1.5 text-right">{o.variation_cv != null ? fmtPct(o.variation_cv * 100) : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function variantsText(o: ShiftMovementOperator): string | undefined {
  const v = Object.entries(o.variants ?? {});
  return v.length ? v.map(([k, x]) => `${k}: best ${x.ref_sec.toFixed(1)} s (${x.best_cycles} of ${x.of} cycles)`).join('\n') : undefined;
}

function CauseChart({ ops }: { ops: ShiftMovementOperator[] }) {
  const data = ops.filter((o) => o.causes).map((o) => ({ name: o.name, ...o.causes }));
  if (!data.length) return null;
  return (
    <Panel title="Where the extra time goes" subtitle="Minutes over his best cycles this shift, by cause (from the step elements and the camera)">
      <ChartLegend items={CAUSES.map((c) => ({ label: c.label, color: c.color }))} className="mb-2" />
      <div style={{ height: 40 + data.length * 34 }}>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 4, right: 16, top: 4, bottom: 4 }} barCategoryGap={8}>
            <CartesianGrid horizontal={false} stroke={GRID} />
            <XAxis type="number" {...AXIS_PROPS} unit=" min" />
            <YAxis type="category" dataKey="name" width={52} {...AXIS_PROPS} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
              content={({ active, payload, label }) =>
                active && payload?.length ? (
                  <TooltipBox
                    title={label}
                    rows={CAUSES.map((c) => ({ label: c.label, value: `${fmtNum(Number((payload[0].payload as Record<string, number>)[c.key] ?? 0), 1)} min`, color: c.color }))}
                  />
                ) : null
              }
            />
            {CAUSES.map((c, i) => (
              <Bar key={c.key} dataKey={c.key} stackId="c" fill={c.color} stroke="#111419" strokeWidth={2} radius={i === CAUSES.length - 1 ? [0, 4, 4, 0] : 0} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}

function quantile(sorted: number[], q: number): number {
  if (!sorted.length) return NaN;
  const i = (sorted.length - 1) * q;
  const lo = Math.floor(i);
  return sorted[lo] + (sorted[Math.min(lo + 1, sorted.length - 1)] - sorted[lo]) * (i - lo);
}

/** one row per operator: 10-90 % range of his cycle times (stops left out), median tick, best marker; click = pick him */
function SpreadRows({ ops, picked, onPick }: { ops: ShiftMovementOperator[]; picked?: string; onPick: (n: string) => void }) {
  const rows = ops.map((o) => {
    const s = o.series.filter((p) => p[2] !== 'stop').map((p) => p[1]).sort((a, b) => a - b);
    return { o, p10: quantile(s, 0.1), p50: quantile(s, 0.5), p90: quantile(s, 0.9), n: s.length };
  });
  const lo = Math.max(0, Math.floor(Math.min(...rows.filter((r) => r.n).map((r) => Math.min(r.p10, r.o.ref?.sec ?? r.p10))) - 1));
  const hi = Math.ceil(Math.max(...rows.filter((r) => r.n).map((r) => r.p90)) + 1);
  const x = (v: number) => `${((v - lo) / Math.max(1, hi - lo)) * 100}%`;
  return (
    <div className="mb-4 space-y-1.5">
      <div className="flex justify-between pl-[72px] text-[11px] text-ink-3">
        <span>{lo}s</span>
        <span>bar = 10–90% of his cycles · white tick = median · dashed = best</span>
        <span>{hi}s</span>
      </div>
      {rows.map(({ o, p10, p50, p90, n }) => (
        <button
          type="button"
          key={o.name}
          onClick={() => onPick(o.name)}
          className={`flex w-full items-center gap-2 rounded-md px-1 py-1 text-left ${picked === o.name ? 'bg-white/[0.05]' : 'hover:bg-white/[0.03]'}`}
          title={n ? `${o.name}: 10% ${p10.toFixed(1)} s · median ${p50.toFixed(1)} s · 90% ${p90.toFixed(1)} s · best ${fmtSec(o.ref?.sec)}` : o.name}
        >
          <span className="w-16 shrink-0 text-xs text-ink">{o.name}</span>
          <span className="relative h-4 flex-1 rounded bg-panel-3">
            {n > 0 && (
              <>
                <span className="absolute top-0.5 bottom-0.5 rounded" style={{ left: x(p10), width: `calc(${x(p90)} - ${x(p10)})`, background: o.color }} />
                <span className="absolute -top-0.5 -bottom-0.5 w-0.5 bg-ink" style={{ left: x(p50) }} />
                {o.ref?.sec != null && <span className="absolute -top-1 -bottom-1 border-l-2 border-dashed border-ink-2" style={{ left: x(o.ref.sec) }} />}
              </>
            )}
          </span>
        </button>
      ))}
    </div>
  );
}

function OperatorCycles({ r, op }: { r: Report; op: ShiftMovementOperator }) {
  type Pt = { t: number; s: number; v: string; c: string; b: string };
  const pts = useMemo(() => {
    const by: Record<string, Pt[]> = { best: [], slower: [], long: [], '': [] };
    for (const [t, s, c, v, b] of op.series) {
      if (b === 'stop' || c === 'stop') continue;
      (by[b ?? ''] ?? by['']).push({ t, s, v: v ?? '', c, b: b ?? '' });
    }
    return by;
  }, [op]);
  const stops = op.series.filter((p) => p[2] === 'stop').length;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-semibold text-ink">
            {op.name} · {stepsOf(op)}
          </span>
          <ChartLegend
            items={[
              ...BANDS.map((b) => ({ label: b.label, color: b.color })),
              ...(pts[''].length ? [{ label: 'Not compared (too few of this part)', color: NOT_COMPARED }] : []),
              { label: `Best ${fmtSec(op.ref?.sec)}`, color: '#a3acb9', kind: 'dash' as const },
            ]}
          />
        </div>
        <div className="h-64">
          <ResponsiveContainer>
            <ScatterChart margin={{ left: 0, right: 12, top: 8, bottom: 4 }}>
              <CartesianGrid stroke={GRID} />
              <XAxis type="number" dataKey="t" domain={r.window} tickFormatter={(v) => clock(v, false)} {...AXIS_PROPS} scale="time" />
              <YAxis type="number" dataKey="s" unit="s" width={44} {...AXIS_PROPS} />
              {op.ref?.sec != null && <ReferenceLine y={op.ref.sec} stroke="#a3acb9" strokeDasharray="5 4" />}
              <Tooltip
                cursor={false}
                content={({ active, payload }) => {
                  const p = active && payload?.length ? (payload[0].payload as Pt) : null;
                  return p ? (
                    <TooltipBox
                      title={clock(p.t)}
                      rows={[
                        { label: 'Cycle', value: fmtSec(p.s), emphasis: true },
                        ...(p.v ? [{ label: 'Part', value: p.v }] : []),
                        {
                          label: 'Against his best',
                          value: p.b === 'best' ? 'like his best' : p.b === 'long' ? 'long (interrupted)' : p.b === 'slower' ? 'slower' : 'not compared',
                        },
                        ...(p.c ? [{ label: 'Why longer', value: CAUSE_LABEL[p.c] ?? p.c }] : []),
                      ]}
                    />
                  ) : null;
                }}
              />
              {pts[''].length > 0 && <Scatter data={pts['']} fill={NOT_COMPARED} shape="circle" isAnimationActive={false} />}
              {BANDS.map((b) => (
                <Scatter key={b.key} data={pts[b.key]} fill={b.color} shape="circle" isAnimationActive={false} />
              ))}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-1 text-xs text-ink-3">
          {fmtNum(op.series.length)} cycles{stops ? ` · ${stops} line stops left out (${fmtNum(op.stop_min, 1)} min)` : ''}
          {variantsText(op) ? ` · ${variantsText(op)!.replace(/\n/g, ' · ')}` : ''}
        </p>
      </div>
      <div>
        <div className="mb-1 text-sm font-semibold text-ink">His elements against his best cycles</div>
        {op.elements?.length ? (
          <table className="w-full text-xs tabular-nums">
            <thead>
              <tr className="border-b border-edge text-left text-ink-3">
                <th className="py-1 font-medium">Element</th>
                <th className="py-1 text-right font-medium">Avg</th>
                <th className="py-1 text-right font-medium">Best</th>
                <th className="py-1 text-right font-medium">Extra</th>
              </tr>
            </thead>
            <tbody>
              {op.elements.map((e) => (
                <tr key={e.code} className="border-b border-edge/50">
                  <td className="py-1 pr-2 text-ink-2">
                    {e.label}
                    {e.kind !== 'work' && <span className="ml-1 text-ink-3">({e.kind})</span>}
                  </td>
                  <td className="py-1 text-right">{fmtSec(e.avg)}</td>
                  <td className="py-1 text-right text-ink-3">{fmtSec(e.ref)}</td>
                  <td className={`py-1 text-right ${e.extra >= 0.5 ? 'font-semibold text-ink' : 'text-ink-3'}`}>{e.extra >= 0 ? '+' : ''}{e.extra.toFixed(1)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-ink-3">{op.note ?? 'No elements.'}</p>
        )}
      </div>
    </div>
  );
}

function Video({ src }: { src: string }) {
  return <video src={src} controls preload="none" className="aspect-video w-full rounded-lg border border-edge bg-black" />;
}

function ClipGrid({ r }: { r: Report }) {
  if (!r.worst.length) return null;
  return (
    <Panel title="Worst cycles of the shift" subtitle="The cycles that took longest over the operator's best, with video" icon={<Clapperboard className="size-4" />}>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {r.worst.map((w, i) => (
          <div key={i} className="space-y-1">
            {w.clip ? <Video src={api.shiftMovementFileUrl(r.id, w.clip)} /> : <div className="aspect-video rounded-lg border border-edge bg-panel-2" />}
            <div className="text-xs">
              <span className="font-semibold text-ink">{w.operator}</span>
              <span className="text-ink-3"> · {clock(w.start)}{w.variant ? ` · ${w.variant}` : ''}</span>
              <div className="text-ink-2">
                {fmtSec(w.sec)} (best {fmtSec(w.ref)}, +{fmtSec(w.extra)}) · {CAUSE_LABEL[w.cause] ?? w.cause}
                {w.where ? ` in '${w.where}'` : ''}
              </div>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function Events({ r }: { r: Report }) {
  const [type, setType] = useState<string>(EVENT_TYPES.find((t) => r.events.some((e) => e.type === t.key))?.key ?? 'handling');
  const [open, setOpen] = useState<number | null>(null);
  const [all, setAll] = useState(false);
  const every = r.events.filter((e) => e.type === type);
  const rows = all ? every : every.slice(0, EVENTS_SHOWN);
  return (
    <Panel
      title="Unusual actions"
      subtitle="Only where the operator is surely followed; the clips show the biggest ones of each kind"
      icon={<AlertTriangle className="size-4" />}
      actions={
        <div className="flex flex-wrap gap-1">
          {EVENT_TYPES.map((t) => {
            const n = r.events.filter((e) => e.type === t.key).length;
            return (
              <button
                type="button"
                key={t.key}
                onClick={() => {
                  setType(t.key);
                  setOpen(null);
                  setAll(false);
                }}
                className={`rounded-md px-2.5 py-1 text-xs ${type === t.key ? 'bg-sky-500/15 font-semibold text-sky-300' : 'text-ink-2 hover:text-ink'}`}
              >
                {t.label} ({n})
              </button>
            );
          })}
        </div>
      }
      flush
    >
      {rows.length ? (
        <ul className="divide-y divide-edge/60 text-sm">
          {rows.map((e, i) => (
            <li key={i} className="px-4 py-2">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="w-20 text-xs text-ink-3 tabular-nums">{clock(e.start)}</span>
                <span className="w-12 font-medium text-ink">{e.operator}</span>
                <span className="min-w-0 flex-1 text-ink-2">{e.text}</span>
                {e.clip && (
                  <button type="button" className="btn btn-sm" onClick={() => setOpen(open === i ? null : i)}>
                    <Play className="size-3.5" /> {open === i ? 'Hide' : 'Video'}
                  </button>
                )}
              </div>
              {open === i && e.clip && (
                <div className="mt-2 max-w-xl">
                  <Video src={api.shiftMovementFileUrl(r.id, e.clip)} />
                </div>
              )}
            </li>
          ))}
          {every.length > rows.length && (
            <li className="px-4 py-2 text-center">
              <button type="button" className="btn btn-sm" onClick={() => setAll(true)}>
                Show all {every.length}
              </button>
            </li>
          )}
        </ul>
      ) : (
        <p className="px-4 py-6 text-center text-sm text-ink-3">None in this shift.</p>
      )}
    </Panel>
  );
}

function Coverage({ r }: { r: Report }) {
  return (
    <Panel title="How well each operator was seen">
      <div className="grid gap-x-6 gap-y-1 text-xs text-ink-2 sm:grid-cols-2 xl:grid-cols-4">
        {r.operators.map((o) => (
          <div key={o.name}>
            <span className="font-medium text-ink">{o.name}</span>: found in {fmtPct(o.visible * 100)} of the frames, surely him in{' '}
            {fmtPct(o.sure * 100)}; hands seen: {o.hands_seen.length ? o.hands_seen.join(' and ') : 'none (hidden)'}
            {o.regular_neighbour ? '; a colleague stands beside him' : ''}
          </div>
        ))}
      </div>
      {r.notes.length > 0 && <p className="mt-2 text-xs text-amber-300">{r.notes.join(' ')}</p>}
      <p className="mt-2 text-xs text-ink-3">
        Made {r.generated_at.replace('T', ' ')} in {Math.round(r.seconds)} s.
      </p>
    </Panel>
  );
}
