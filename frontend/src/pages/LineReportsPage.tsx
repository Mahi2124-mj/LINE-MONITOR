import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Activity, ChevronLeft, ChevronRight, Clock, Lightbulb, Play, User } from 'lucide-react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  LabelList,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { api } from '../api/client';
import type { ExampleCycle, Line as LineT, LineReport, StationReport, VariationReport } from '../api/types';
import { AXIS_PROPS, ChartLegend, TooltipBox } from '../components/charts/ChartTooltip';
import { EmptyState, ErrorState, SkeletonPanel } from '../components/EmptyState';
import { ElementDetail, FlowStrip, LinePlayer, LossList, Spread, TimeBars, watchOf, type WatchTarget } from '../components/LineBreakdown';
import { Panel } from '../components/Panel';
import { WindowPlayer } from '../components/WindowPlayer';
import { usePageTitle } from '../context/PageTitleContext';
import { usePolling } from '../hooks/usePolling';
import { fmtNum, fmtSec } from '../lib/format';
import { CHART } from '../lib/meta';

export type ReportView = 'line' | 'step' | 'operators' | 'variation';

const GREEN = '#22c55e';
const RED = '#ef4444';
const AMBER = '#f59e0b';
const BLUE = '#38bdf8';
const VIEWS: { view: ReportView; label: string; path: string }[] = [
  { view: 'line', label: 'Line report', path: '/reports' },
  { view: 'step', label: 'Machine step', path: '/reports/step' },
  { view: 'operators', label: 'Operators', path: '/reports/operators' },
  { view: 'variation', label: 'Variation (baratsuki)', path: '/reports/variation' },
];
const TITLES: Record<ReportView, string> = {
  line: 'Line report',
  step: 'Machine step detail',
  operators: 'Operator work vs waiting',
  variation: 'Cycle time variation (baratsuki)',
};

const pad = (n: number) => String(n).padStart(2, '0');
const localIso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const hhmm = (ts: string | number) => {
  const d = new Date(ts);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** Reports: line summary, machine step detail, operator work vs waiting and cycle variation, for any time window. */
export default function LineReportsPage({ view }: { view: ReportView }) {
  usePageTitle(TITLES[view], [{ label: 'Reports', to: '/reports' }]);
  const [params, setParams] = useSearchParams();
  const lines = usePolling(() => api.lines(), [], 0);
  const active = lines.data?.filter((l) => l.is_active) ?? [];
  const line = lines.data?.find((l) => String(l.id) === params.get('line')) ?? active[0] ?? lines.data?.[0] ?? null;
  // the window: a shift (?shift=A|B: its newest run, live while it runs), auto (no ?from: the running shift, else the
  // newest one) or the times typed in (custom)
  const shifts = usePolling(() => api.shifts().catch(() => null), [], 60_000);
  const sh = shifts.data;
  const running = (w: { end: string } | null | undefined) => !!w && Date.now() - new Date(w.end).getTime() < 120_000;
  const autoShift = sh
    ? (['A', 'B'] as const)
        .filter((n) => sh[n])
        .sort((x, y) => Number(running(sh[y])) - Number(running(sh[x])) || sh[y]!.start.localeCompare(sh[x]!.start))[0] ?? null
    : null;
  const picked = params.get('shift') === 'A' || params.get('shift') === 'B' ? (params.get('shift') as 'A' | 'B') : null;
  const shiftName = picked ?? (params.get('from') ? null : autoShift);
  const sw = shiftName ? sh?.[shiftName] : null;
  const from = sw ? sw.start.slice(0, 16) : (params.get('from') ?? (line ? defaultFrom(line) : localIso(new Date(Date.now() - 8 * 3600_000))));
  const to = sw ? (running(sw) ? '' : sw.end.slice(0, 16)) : (params.get('to') ?? ''); // empty = live, up to now
  const live = to === '';
  const set = (k: string, v: string | null) => {
    const p = new URLSearchParams(params);
    if (k === 'from' || k === 'to') {
      // typed times: a custom window from the one shown now
      p.delete('shift');
      if (from) p.set('from', from);
      if (to) p.set('to', to);
      else p.delete('to');
    }
    if (v === null || v === '') p.delete(k);
    else p.set(k, v);
    setParams(p, { replace: true });
  };
  const setShift = (v: string) => {
    const p = new URLSearchParams(params);
    p.delete('from');
    p.delete('to');
    p.delete('shift');
    if (v === 'A' || v === 'B') p.set('shift', v);
    if (v === 'custom') {
      p.set('from', from);
      if (to) p.set('to', to);
    }
    setParams(p, { replace: true });
  };
  const query = `?${params.toString()}`;

  if (lines.error && !lines.data) return <ErrorState error={lines.error} onRetry={lines.reload} />;
  if (!line) return <SkeletonPanel className="h-72" />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1 rounded-lg border border-edge bg-panel p-1">
          {VIEWS.map((v) => (
            <Link
              key={v.view}
              to={v.path + query}
              className={`rounded-md px-3 py-1.5 text-sm transition ${v.view === view ? 'bg-sky-500/15 font-semibold text-sky-300' : 'text-ink-2 hover:text-ink'}`}
            >
              {v.label}
            </Link>
          ))}
          <Link to={`/reports/saved?line=${line.id}`} className="rounded-md px-3 py-1.5 text-sm text-ink-3 hover:text-ink">
            Saved reports
          </Link>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {sh && (sh.A || sh.B) && (
            <select
              className="input w-auto"
              value={picked ?? (params.get('from') ? 'custom' : 'auto')}
              onChange={(e) => setShift(e.target.value)}
              aria-label="Shift"
              title="Auto: the running shift (else the last one)"
            >
              <option value="auto">Auto</option>
              {sh.A && <option value="A">Shift A</option>}
              {sh.B && <option value="B">Shift B</option>}
              <option value="custom">Custom</option>
            </select>
          )}
          <input className="input w-auto" type="datetime-local" value={from} onChange={(e) => set('from', e.target.value)} aria-label="From" />
          <span className="text-ink-3">→</span>
          <input
            className="input w-auto"
            type="datetime-local"
            value={live ? localIso(new Date()) : to}
            onChange={(e) => set('to', e.target.value)}
            aria-label="To"
          />
          <select className="input w-auto" value={line.id} onChange={(e) => set('line', e.target.value)} aria-label="Line">
            {(lines.data ?? []).map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
                {l.is_active ? '' : ' (disabled)'}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => set('to', null)}
            title={live ? 'Up to now, refreshed every minute' : 'Show up to now'}
            className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${live ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40' : 'bg-panel text-ink-3 ring-1 ring-edge'}`}
          >
            <span className={`size-2 rounded-full ${live ? 'animate-pulse bg-emerald-400' : 'bg-ink-3'}`} /> Live
          </button>
        </div>
      </div>
      {view === 'line' && <LineView line={line} from={from} to={to} query={query} />}
      {view === 'step' && <StepView line={line} from={from} to={to} query={query} />}
      {view === 'operators' && <OperatorsView line={line} from={from} to={to} />}
      {view === 'variation' && <VariationView line={line} from={from} to={to} query={query} />}
    </div>
  );
}

function defaultFrom(line: LineT): string {
  const [h, m] = (line.slot_plan?.[0]?.start ?? line.shift_start).split(':').map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  if (d.getTime() > Date.now()) d.setDate(d.getDate() - 1);
  return localIso(d);
}

interface ViewProps {
  line: LineT;
  from: string;
  to: string;
  query?: string;
}

/* ------------------------------------------------------------------ shared pieces */

function Kpi({ label, value, unit, sub, tone, visual }: { label: string; value: ReactNode; unit?: string; sub?: ReactNode; tone?: string; visual?: ReactNode }) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-2 rounded-xl border border-edge bg-panel px-4 py-3">
      <div className="min-w-0">
        <div className="truncate text-xs text-ink-3">{label}</div>
        <div className={`mt-0.5 text-3xl font-semibold leading-tight tracking-tight tabular-nums ${tone ?? 'text-ink'}`}>
          {value}
          {unit && <span className="ml-1 text-base font-medium">{unit}</span>}
        </div>
        {sub && <div className="mt-0.5 truncate text-xs text-ink-3">{sub}</div>}
      </div>
      {visual && <div className="shrink-0">{visual}</div>}
    </div>
  );
}

function Ring({ pct, color }: { pct: number | null; color: string }) {
  const r = 18;
  const c = 2 * Math.PI * r;
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" aria-hidden="true">
      <circle cx="24" cy="24" r={r} fill="none" stroke="#2a313b" strokeWidth="6" />
      <circle cx="24" cy="24" r={r} fill="none" stroke={color} strokeWidth="6" strokeDasharray={`${(c * (pct ?? 0)) / 100} ${c}`} transform="rotate(-90 24 24)" strokeLinecap="round" />
    </svg>
  );
}

function shade(v: number | null, kind: 'bad' | 'good'): string {
  if (v === null) return '';
  if (kind === 'good') return v >= 85 ? 'bg-emerald-600/70 text-white' : v >= 70 ? 'bg-emerald-700/50 text-emerald-100' : 'bg-amber-600/50 text-amber-100';
  return v >= 15 ? 'bg-red-600/70 text-white' : v >= 8 ? 'bg-red-700/50 text-red-100' : 'bg-red-900/40 text-red-200';
}

function Loading({ error, retry }: { error: unknown; retry: () => void }) {
  return error ? <ErrorState error={error} onRetry={retry} /> : <SkeletonPanel className="h-96" />;
}

/* ------------------------------------------------------------------ line report */

function LineView({ line, from, to, query }: ViewProps) {
  const r = usePolling(() => api.lineReport(line.id, from, to || undefined), [line.id, from, to], to ? 0 : 60_000);
  const d = r.data;
  if (!d) return <Loading error={r.error} retry={r.reload} />;
  const k = d.kpis;
  const change = k.prev_total_cycles ? (100 * (k.total_cycles - k.prev_total_cycles)) / k.prev_total_cycles : null;
  return (
    <>
      <div>
        <div className="flex items-center gap-2">
          <Activity className="size-5 text-sky-400" />
          <h1 className="text-xl font-semibold text-ink">{d.line.name}</h1>
          <span className="text-sm text-ink-3">· machine cycle analytics</span>
        </div>
        <p className="mt-0.5 text-xs text-ink-3">
          Every step's cycles in this window, counted by the camera. Abnormal = longer than 1.5 × the step's normal cycle. Click a step for its detail.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi
          label="Total cycles"
          value={fmtNum(k.total_cycles)}
          sub={change !== null ? <span className={change >= 0 ? 'text-emerald-400' : 'text-red-400'}>{`${change >= 0 ? '↑ +' : '↓ '}${change.toFixed(0)}% vs before`}</span> : 'all steps'}
        />
        <Kpi label="Normal cycles" value={fmtNum(k.normal)} tone="text-emerald-400" sub={`${k.normal_pct ?? 0}%`} visual={<Ring pct={k.normal_pct} color={GREEN} />} />
        <Kpi label="Abnormal cycles" value={fmtNum(k.abnormal)} tone="text-red-400" sub={`${k.abnormal_pct ?? 0}%`} visual={<Ring pct={k.abnormal_pct} color={RED} />} />
        <Kpi label="Avg cycle time" value={k.avg_cycle ?? '—'} unit="s" tone="text-sky-400" sub={`Normal ${fmtSec(k.normal_cycle)} · takt ${fmtSec(d.line.takt_time_sec)}`} />
        <Kpi label="Operator work time" value={`${k.work_pct ?? '—'}%`} tone="text-emerald-400" sub={`Work ${k.work_h ?? 0} h`} visual={<User className="size-6 text-sky-400" />} />
        <Kpi label="Waiting / unattended" value={`${k.wait_pct ?? '—'}%`} tone="text-amber-400" sub={`${k.wait_h ?? 0} h`} visual={<Clock className="size-6 text-amber-400" />} />
      </div>
      <LineVisual line={line} from={from} to={to} query={query} />
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Cycle time trend (all steps)" subtitle={`Median cycle of all steps per ${d.trend_bucket_sec / 60} min · red = 15% or more of the cycles in it abnormal`} className="xl:col-span-2">
          <TrendChart d={d} />
        </Panel>
        <Panel title="Cycle status distribution">
          <StatusDonut normal={k.normal} abnormal={k.abnormal} />
        </Panel>
      </div>
      <Panel title="Machine step summary" flush>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="border-b border-edge text-left text-xs text-ink-3">
                {['#', 'Machine step', 'Operator', 'Normal cycle (s)', 'Avg cycle (s)', 'Total cycles', 'Abnormal', 'Abnormal %', 'Operator work', 'Waiting'].map((h, i) => (
                  <th key={h} className={`px-3 py-2 font-medium ${i >= 3 ? 'text-right' : ''}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.steps.map((s) => (
                <tr key={s.station_id} className="border-b border-edge/60 hover:bg-white/[0.03]">
                  <td className="px-3 py-1.5 text-ink-3">{s.sequence}</td>
                  <td className="px-3 py-1.5">
                    <Link to={`/reports/step/${s.station_id}${query}`} className="text-ink hover:text-sky-300 hover:underline">
                      {s.name}
                    </Link>
                  </td>
                  <td className="px-3 py-1.5 text-ink-3">{s.operator || '—'}</td>
                  <td className="px-3 py-1.5 text-right">{s.normal_cycle ?? '—'}</td>
                  <td className="px-3 py-1.5 text-right">{s.avg_cycle ?? '—'}</td>
                  <td className="px-3 py-1.5 text-right">{fmtNum(s.total)}</td>
                  <td className="px-3 py-1.5 text-right text-red-300">{s.abnormal}</td>
                  <td className="px-3 py-1.5 text-right">
                    <span className={`inline-block min-w-14 rounded px-1.5 py-0.5 ${shade(s.abnormal_pct, 'bad')}`}>{s.abnormal_pct === null ? '—' : `${s.abnormal_pct}%`}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <span className={`inline-block min-w-14 rounded px-1.5 py-0.5 ${shade(s.work_pct, 'good')}`}>{s.work_pct === null ? '—' : `${s.work_pct}%`}</span>
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <span className={`inline-block min-w-14 rounded px-1.5 py-0.5 ${shade(s.wait_pct, 'bad')}`}>{s.wait_pct === null ? '—' : `${s.wait_pct}%`}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

function TrendChart({ d }: { d: LineReport }) {
  // red only where abnormal cycles are a real share of the block (with 12 steps almost every block has one)
  const data = d.trend.map((p) => ({ t: new Date(p.t).getTime(), cycle: p.cycle, ab: p.n && p.abnormal / p.n >= 0.15 ? p.cycle : null, n: p.abnormal, all: p.n }));
  if (!data.length) return <EmptyState compact title="No cycles in this window" />;
  return (
    <div>
      <ChartLegend
        className="mb-2"
        items={[
          { label: 'Cycle time', color: BLUE },
          { label: 'Normal cycle', color: CHART.takt, kind: 'dash' },
          { label: 'Abnormal', color: RED },
        ]}
      />
      <div style={{ height: 260 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time" tickFormatter={hhmm} {...AXIS_PROPS} />
            <YAxis {...AXIS_PROPS} width={40} label={{ value: 'Cycle time (s)', angle: -90, position: 'insideLeft', fill: CHART.tick, fontSize: 11, dy: 40 }} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof data)[number];
                return (
                  <TooltipBox
                    title={hhmm(p.t)}
                    rows={[
                      { label: 'Cycle (median)', value: fmtSec(p.cycle), color: BLUE },
                      { label: 'Abnormal cycles', value: `${p.n} of ${p.all}`, color: RED },
                    ]}
                  />
                );
              }}
            />
            {d.kpis.normal_cycle !== null && <ReferenceLine y={d.kpis.normal_cycle} stroke={CHART.takt} strokeDasharray="6 4" />}
            <Line dataKey="cycle" stroke={BLUE} strokeWidth={1.8} dot={{ r: 2, fill: BLUE }} isAnimationActive={false} connectNulls />
            <Scatter dataKey="ab" fill={RED} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function StatusDonut({ normal, abnormal }: { normal: number; abnormal: number }) {
  const total = normal + abnormal;
  if (!total) return <EmptyState compact title="No cycles" />;
  const data = [
    { name: 'Normal', value: normal, color: GREEN },
    { name: 'Abnormal', value: abnormal, color: RED },
  ];
  return (
    <div className="flex flex-wrap items-center justify-center gap-6">
      <div className="relative" style={{ width: 200, height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" innerRadius={62} outerRadius={90} startAngle={90} endAngle={-270} stroke="none" isAnimationActive={false}>
              {data.map((x) => (
                <Cell key={x.name} fill={x.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-semibold text-ink tabular-nums">{fmtNum(total)}</span>
          <span className="text-xs text-ink-3">cycles</span>
        </div>
      </div>
      <div className="space-y-3 text-sm">
        {data.map((x) => (
          <div key={x.name} className="flex items-start gap-2">
            <span className="mt-1 size-3 rounded-full" style={{ background: x.color }} />
            <div>
              <div className="text-ink">{x.name}</div>
              <div className="text-ink-3 tabular-nums">
                {fmtNum(x.value)} ({((100 * x.value) / total).toFixed(1)}%)
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ machine step detail */

function StepView({ line, from, to, query }: ViewProps) {
  const { stationId } = useParams();
  const navigate = useNavigate();
  const stations = usePolling(() => api.stations(line.id), [line.id], 0);
  const first = stations.data?.filter((s) => s.is_active).sort((a, b) => a.sequence - b.sequence)[0];
  const id = Number(stationId) || null;
  useEffect(() => {
    if (!id && first) navigate(`/reports/step/${first.id}${query ?? ''}`, { replace: true });
  }, [id, first, navigate, query]);
  const r = usePolling(() => (id ? api.stationReport(id, from, to || undefined) : Promise.resolve(null)), [id, from, to], to ? 0 : 60_000);
  const [win, setWin] = useState<{ at: number | null; sec: number }>({ at: null, sec: 60 });
  const player = useRef<HTMLDivElement>(null);
  useEffect(() => setWin({ at: null, sec: 60 }), [id]);
  const d = r.data;
  if (!d) return <Loading error={r.error} retry={r.reload} />;
  const k = d.kpis;
  const go = (sid: number | null) => sid && navigate(`/reports/step/${sid}${query ?? ''}`);
  const watchAt = (start: number) => {
    setWin((w) => ({ at: start - 3, sec: w.sec }));
    player.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const colorOf = Object.fromEntries((d.elements ?? []).map((e) => [e.code, e]));
  const checked = (d.elements ?? []).length > 0;
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">
            {d.station.sequence}. {d.station.name}
          </h1>
          <p className="text-xs text-ink-3">{d.station.operator ? `Operator ${d.station.operator}` : 'Step of ' + line.name}</p>
        </div>
        <div className="flex items-center gap-2">
          <select className="input w-auto" value={d.station.id} onChange={(e) => go(Number(e.target.value))} aria-label="Step">
            {(stations.data ?? [])
              .filter((s) => s.is_active)
              .sort((a, b) => a.sequence - b.sequence)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.sequence}. {s.name}
                </option>
              ))}
          </select>
          <button type="button" className="btn btn-sm" disabled={!d.prev_id} onClick={() => go(d.prev_id)}>
            <ChevronLeft className="size-4" /> Previous step
          </button>
          <button type="button" className="btn btn-sm" disabled={!d.next_id} onClick={() => go(d.next_id)}>
            Next step <ChevronRight className="size-4" />
          </button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Normal cycle" value={k.normal_cycle ?? '—'} unit="s" tone="text-emerald-400" />
        <Kpi label="Average cycle" value={k.avg_cycle ?? '—'} unit="s" tone="text-amber-300" />
        <Kpi label="Total cycles" value={fmtNum(k.total)} tone="text-sky-400" />
        <Kpi label="Abnormal cycles" value={k.abnormal} tone="text-red-400" sub={k.abnormal_pct === null ? '' : `${k.abnormal_pct}%`} />
        <Kpi label="Operator work time" value={`${k.work_pct ?? '—'}%`} tone="text-emerald-400" sub={`${k.work_h} h`} />
        <Kpi label="Waiting / unattended" value={`${k.wait_pct ?? '—'}%`} tone="text-amber-400" sub={`${k.wait_h} h`} />
      </div>
      {checked && <StepVisual line={line} stationId={d.station.id} from={from} to={to} onWatch={(ex) => watchAt(ex.start)} />}
      {checked && (
        <div ref={player} className="scroll-mt-4">
          <WindowPlayer stationId={d.station.id} at={win.at} sec={win.sec} onWindow={(at, sec) => setWin({ at, sec })} />
        </div>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Cycle time distribution" subtitle={`Normal cycle ${fmtSec(k.normal_cycle)}`}>
          <div style={{ height: 250 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={d.histogram} margin={{ top: 18, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={CHART.grid} />
                <XAxis dataKey="label" {...AXIS_PROPS} />
                <YAxis {...AXIS_PROPS} width={40} allowDecimals={false} />
                <Bar dataKey="count" fill="#3b82f6" radius={[3, 3, 0, 0]} isAnimationActive={false}>
                  <LabelList dataKey="count" position="top" fill="#e6e9ee" fontSize={11} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 text-center text-xs text-ink-3">Cycle time (seconds)</div>
        </Panel>
        <Panel title="Cycle time per cycle (sequence)" subtitle={`Last ${d.sequence.length} cycles`}>
          <SequenceChart d={d} />
        </Panel>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Recent cycle records" subtitle={checked ? 'Newest first · the bar shows the elements of each cycle · ▶ plays it' : 'Newest first'} flush className="xl:col-span-2">
          <div className="max-h-[26rem] overflow-y-auto">
            <table className="w-full text-sm tabular-nums">
              <thead className="sticky top-0 z-10 bg-panel">
                <tr className="border-b border-edge text-left text-xs text-ink-3">
                  {['Cycle no.', 'Start time', 'Cycle time (s)', ...(checked ? ['Elements', ''] : []), 'Status', 'Remarks'].map((h, i) => (
                    <th key={i} className="px-3 py-2 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.recent.map((c) => (
                  <tr key={c.id} className="border-b border-edge/60">
                    <td className="px-3 py-1.5 text-ink-3">{c.n}</td>
                    <td className="px-3 py-1.5">{c.start.replace('T', ' ')}</td>
                    <td className={`px-3 py-1.5 ${c.status === 'Abnormal' ? 'text-red-300' : ''}`}>{c.cycle}</td>
                    {checked && (
                      <>
                        <td className="px-3 py-1.5">
                          <MiniBar segs={c.segs ?? []} cycle={c.cycle} normal={k.normal_cycle} meta={colorOf} />
                        </td>
                        <td className="px-1 py-1">
                          <button type="button" className="btn btn-sm px-2" onClick={() => watchAt(c.t0)} title="Watch this cycle (recordings are kept 12 h)" aria-label="Watch this cycle">
                            <Play className="size-3.5" />
                          </button>
                        </td>
                      </>
                    )}
                    <td className="px-3 py-1.5">
                      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${c.status === 'Abnormal' ? 'bg-red-600/80 text-white' : 'bg-emerald-600/80 text-white'}`}>
                        {c.status}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-ink-3">{c.remark || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="Camera snapshot (abnormal cycle)">
          {d.snapshot ? (
            <div className="space-y-3">
              <img
                src={api.recordedFrameUrl(d.snapshot.camera_id, d.snapshot.frame_ts)}
                alt={`Camera frame in the middle of cycle ${d.snapshot.n}`}
                className="w-full rounded-lg border border-edge"
                onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')}
              />
              <dl className="grid grid-cols-[6rem_1fr] gap-y-1 text-sm">
                <dt className="text-ink-3">Cycle no.</dt>
                <dd className="tabular-nums">{d.snapshot.n}</dd>
                <dt className="text-ink-3">Time</dt>
                <dd className="tabular-nums">{d.snapshot.t.replace('T', ' ')}</dd>
                <dt className="text-ink-3">Cycle time</dt>
                <dd className="tabular-nums">{d.snapshot.cycle} s</dd>
                <dt className="text-ink-3">Status</dt>
                <dd className="text-red-400">Abnormal</dd>
                <dt className="text-ink-3">Remark</dt>
                <dd>{d.snapshot.remark || '—'}</dd>
              </dl>
            </div>
          ) : (
            <EmptyState compact title="No abnormal cycle in this window" />
          )}
        </Panel>
      </div>
    </>
  );
}

/** the visual part of the line report: flow, where the time goes, the video, variation and losses */
function LineVisual({ line, from, to, query }: ViewProps) {
  const navigate = useNavigate();
  const r = usePolling(() => api.lineBreakdown(line.id, from, to || undefined), [line.id, from, to], to ? 0 : 60_000);
  const [sel, setSel] = useState<{ sid: number; code: string } | null>(null);
  const [target, setTarget] = useState<WatchTarget | null>(null);
  const player = useRef<HTMLDivElement>(null);
  const d = r.data;
  if (!d) return r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : <SkeletonPanel className="h-40" />;
  const watch = (ex: ExampleCycle, label: string) => {
    setTarget(watchOf(ex, label));
    player.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const checked = d.steps.some((s) => s.checked);
  const selStep = sel ? d.steps.find((s) => s.station_id === sel.sid) : undefined;
  const selEl = selStep?.elements.find((e) => e.code === sel?.code);
  return (
    <>
      <Panel
        title="Line flow"
        subtitle={`Steps in order · time per part = average of the normal cycles${d.bottleneck ? ' · red = the slowest step (bottleneck)' : ''} · click a step for its detail`}
      >
        <FlowStrip steps={d.steps} bottleneck={d.bottleneck} takt={d.line.takt_time_sec} onOpen={(id) => navigate(`/reports/step/${id}${query ?? ''}`)} />
      </Panel>
      {checked && (
        <>
          <Panel title="Where the time goes" subtitle="Average seconds per part, split into what the operator does · click an element for its trend and a video">
            <TimeBars
              steps={d.steps}
              takt={d.line.takt_time_sec}
              selected={sel}
              onSelect={(sid, code) => setSel(sel?.sid === sid && sel.code === code ? null : { sid, code })}
            />
            {selStep && selEl && <ElementDetail step={selStep} el={selEl} onWatch={watch} onClose={() => setSel(null)} />}
          </Panel>
          <div ref={player} className="scroll-mt-4">
            <LinePlayer lineId={line.id} target={target} onTarget={setTarget} quick={d.steps} />
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Variation (baratsuki) per element" subtitle="Which part of the work varies most">
              <Spread steps={d.steps} onWatch={watch} />
            </Panel>
            <Panel title="Biggest losses" subtitle="Time lost beyond the usual, with an example to watch">
              <LossList losses={d.losses} onWatch={watch} />
            </Panel>
          </div>
        </>
      )}
    </>
  );
}

/** one step: where its time goes, the spread of its elements and its losses */
function StepVisual({ line, stationId, from, to, onWatch }: { line: LineT; stationId: number; from: string; to: string; onWatch: (ex: ExampleCycle) => void }) {
  const r = usePolling(() => api.lineBreakdown(line.id, from, to || undefined, stationId), [line.id, stationId, from, to], to ? 0 : 60_000);
  const [sel, setSel] = useState<string | null>(null);
  const d = r.data;
  if (!d) return r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : <SkeletonPanel className="h-40" />;
  const s = d.steps[0];
  if (!s?.checked) return null;
  const el = s.elements.find((e) => e.code === sel);
  return (
    <>
      <Panel title="Where the time goes" subtitle="Average seconds per part, split into what the operator does · click an element for its trend and a video">
        <TimeBars steps={[s]} takt={d.line.takt_time_sec} selected={sel ? { sid: s.station_id, code: sel } : null} onSelect={(_, code) => setSel(sel === code ? null : code)} />
        {el && <ElementDetail step={s} el={el} onWatch={(ex) => onWatch(ex)} onClose={() => setSel(null)} />}
      </Panel>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Variation (baratsuki) per element" subtitle="Which part of the work varies most">
          <Spread steps={[s]} onWatch={(ex) => onWatch(ex)} />
        </Panel>
        <Panel title="Biggest losses" subtitle="Time lost beyond the usual, with an example to watch">
          <LossList losses={d.losses} onWatch={(ex) => onWatch(ex)} />
        </Panel>
      </div>
    </>
  );
}

/** the elements of one cycle as a small bar; a longer cycle gets a longer bar */
function MiniBar({
  segs,
  cycle,
  normal,
  meta,
}: {
  segs: [string, number, number][];
  cycle: number | null;
  normal: number | null;
  meta: Record<string, { label: string; color: string }>;
}) {
  if (!segs.length || !cycle) return <span className="text-xs text-ink-3">—</span>;
  const width = Math.min(100, (100 * cycle) / (2 * (normal || cycle)));
  return (
    <div className="h-3 w-40">
      <div className="relative h-full overflow-hidden rounded-sm bg-white/[0.06]" style={{ width: `${width}%` }}>
        {segs.map(([code, a, dur], i) => (
          <span
            key={i}
            className="absolute inset-y-0 border-r border-black/40"
            style={{ left: `${(100 * a) / cycle}%`, width: `${(100 * dur) / cycle}%`, background: meta[code]?.color ?? '#64748b' }}
            title={`${meta[code]?.label ?? code}: ${dur.toFixed(1)} s`}
          />
        ))}
      </div>
    </div>
  );
}

function SequenceChart({ d }: { d: StationReport }) {
  const data = d.sequence.map((p) => ({ n: p.n, ok: p.abnormal ? null : p.cycle, ab: p.abnormal ? p.cycle : null, t: p.t }));
  if (!data.length) return <EmptyState compact title="No cycles" />;
  return (
    <div>
      <ChartLegend
        className="mb-2"
        items={[
          { label: 'Normal cycle', color: '#3b82f6' },
          { label: 'Abnormal cycle', color: RED },
          { label: `Normal (${fmtSec(d.kpis.normal_cycle)})`, color: CHART.takt, kind: 'dash' },
        ]}
      />
      <div style={{ height: 230 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={CHART.grid} />
            <XAxis dataKey="n" type="number" domain={['dataMin', 'dataMax']} {...AXIS_PROPS} />
            <YAxis {...AXIS_PROPS} width={40} />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const p = payload[0].payload as (typeof data)[number];
                return <TooltipBox title={`Cycle ${p.n} · ${hhmm(p.t)}`} rows={[{ label: 'Cycle time', value: fmtSec(p.ok ?? p.ab), color: p.ab ? RED : BLUE }]} />;
              }}
            />
            {d.kpis.normal_cycle !== null && <ReferenceLine y={d.kpis.normal_cycle} stroke={CHART.takt} strokeDasharray="6 4" />}
            <Scatter dataKey="ok" fill="#3b82f6" isAnimationActive={false} shape="circle" />
            <Scatter dataKey="ab" fill={RED} isAnimationActive={false} shape="circle" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ operators */

function blockColor(b: { work: number; motion: number; wait: number }): string {
  if (b.wait >= 0.5) return RED;
  if (b.work >= 0.7) return GREEN;
  return AMBER;
}

function OperatorsView({ line, from, to }: ViewProps) {
  const r = usePolling(() => api.operatorsReport(line.id, from, to || undefined), [line.id, from, to], to ? 0 : 60_000);
  const d = r.data;
  const ticks = useMemo(() => {
    if (!d) return [];
    const t0 = new Date(d.bucket_start).getTime();
    const t1 = new Date(d.window[1]).getTime();
    const span = Math.max(1, t1 - t0);
    const step = span <= 6 * 3600_000 ? 3600_000 : span <= 26 * 3600_000 ? 2 * 3600_000 : 24 * 3600_000;
    const out: { pct: number; label: string }[] = [];
    for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) out.push({ pct: (100 * (t - t0)) / span, label: hhmm(t) });
    return out;
  }, [d]);
  if (!d) return <Loading error={r.error} retry={r.reload} />;
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold text-ink">Operator work vs waiting timeline</h1>
        <p className="text-xs text-ink-3">
          One row per person (a person who runs several steps is one row), in {d.bucket_sec / 60}-minute blocks. Green = working, yellow = walking or other,
          red = waiting or no cycle (stopped, away, break).
        </p>
      </div>
      <Panel>
        <ChartLegend
          className="mb-3"
          items={[
            { label: 'Working', color: GREEN },
            { label: 'Walking / other', color: AMBER },
            { label: 'Waiting / unattended', color: RED },
          ]}
        />
        <div className="overflow-x-auto">
          <div className="min-w-[720px]">
            <div className="relative ml-[13rem] h-5 text-xs text-ink-3">
              {ticks.map((t) => (
                <span key={t.pct} className="absolute -translate-x-1/2" style={{ left: `${t.pct}%` }}>
                  {t.label}
                </span>
              ))}
            </div>
            {d.operators.map((o) => (
              <div key={o.label} className="flex items-center gap-2 py-1">
                <div className="w-[8rem] truncate text-sm text-ink" title={o.steps.join(', ')}>
                  {o.label}
                </div>
                <div className="w-[4.5rem] text-right text-sm tabular-nums text-ink-2">{o.work_pct ?? '—'}%</div>
                <div className="flex h-6 min-w-0 flex-1 gap-px overflow-hidden rounded">
                  {o.blocks.map((b, i) => (
                    <div
                      key={i}
                      className="h-full flex-1"
                      style={{ background: blockColor(b) }}
                      title={`${hhmm(new Date(d.bucket_start).getTime() + i * d.bucket_sec * 1000)} · work ${Math.round(b.work * 100)}% · walking ${Math.round(b.motion * 100)}% · waiting ${Math.round(b.wait * 100)}%`}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      </Panel>
      <Panel title="Operator summary" flush>
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="border-b border-edge text-left text-xs text-ink-3">
                {['Operator', 'Work time', 'Waiting / unattended', 'Work %', 'Cycles handled', 'Steps'].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {d.operators.map((o) => (
                <tr key={o.label} className="border-b border-edge/60">
                  <td className="px-3 py-1.5 text-ink">{o.label}</td>
                  <td className="px-3 py-1.5">{o.work_h} h</td>
                  <td className="px-3 py-1.5">{o.wait_h} h</td>
                  <td className="px-3 py-1.5">
                    <span className={`inline-block min-w-14 rounded px-1.5 py-0.5 ${shade(o.work_pct, 'good')}`}>{o.work_pct ?? '—'}%</span>
                  </td>
                  <td className="px-3 py-1.5">{fmtNum(o.cycles)}</td>
                  <td className="px-3 py-1.5 text-ink-3">{o.steps.join(', ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

/* ------------------------------------------------------------------ variation (baratsuki) */

function VariationView({ line, from, to, query }: ViewProps) {
  const r = usePolling(() => api.variationReport(line.id, from, to || undefined), [line.id, from, to], to ? 0 : 60_000);
  const d = r.data;
  if (!d) return <Loading error={r.error} retry={r.reload} />;
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold text-ink">Cycle time variation (baratsuki)</h1>
        <p className="text-xs text-ink-3">
          Spread of each step's normal cycles (box = middle half, whiskers = fastest to slowest), average, normal cycle and the abnormal cycles. Click a
          step for its detail.
        </p>
      </div>
      <Panel>
        <ChartLegend
          className="mb-2"
          items={[
            { label: 'Normal cycle', color: CHART.takt, kind: 'dash' },
            { label: 'Cycle range (min–max)', color: '#3b82f6' },
            { label: 'Average', color: AMBER },
            { label: 'Abnormal cycle', color: RED },
          ]}
        />
        <BoxPlot d={d} query={query ?? ''} />
      </Panel>
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Key findings" icon={<Lightbulb className="size-4 text-amber-400" />}>
          {d.findings.length ? (
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-ink-2">
              {d.findings.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : (
            <EmptyState compact title="Not enough cycles" />
          )}
        </Panel>
        <Panel title="Abnormal cycle count by step">
          <div style={{ height: 220 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={d.steps.map((s) => ({ step: s.sequence, n: s.abnormal_count, name: s.name }))} margin={{ top: 18, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid vertical={false} stroke={CHART.grid} />
                <XAxis dataKey="step" {...AXIS_PROPS} />
                <YAxis {...AXIS_PROPS} width={36} allowDecimals={false} />
                <Tooltip content={({ active, payload }) => (active && payload?.length ? <TooltipBox title={(payload[0].payload as { name: string }).name} rows={[{ label: 'Abnormal cycles', value: String(payload[0].value), color: RED }]} /> : null)} />
                <Bar dataKey="n" fill={RED} radius={[3, 3, 0, 0]} isAnimationActive={false}>
                  <LabelList dataKey="n" position="top" fill="#e6e9ee" fontSize={11} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 text-center text-xs text-ink-3">Step no.</div>
        </Panel>
      </div>
    </>
  );
}

function BoxPlot({ d, query }: { d: VariationReport; query: string }) {
  const navigate = useNavigate();
  const steps = d.steps;
  if (!steps.some((s) => s.median !== null)) return <EmptyState compact title="Not enough cycles in this window" />;
  // the scale stops at 2.5 x the slowest normal maximum, longer abnormal cycles sit at the top edge
  const top = Math.max(...steps.map((s) => s.max ?? 0)) * 2.5;
  const yMax = Math.ceil(Math.min(top, Math.max(...steps.flatMap((s) => [s.max ?? 0, ...s.abnormal_values]))) / 10) * 10 || 10;
  const W = 1000;
  const H = 320;
  const L = 44;
  const B = 50;
  const T = 10;
  const bw = (W - L - 10) / steps.length;
  const y = (v: number) => T + (H - T - B) * (1 - Math.min(v, yMax) / yMax);
  const grid = Array.from({ length: 6 }, (_, i) => Math.round((yMax * i) / 5));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Box plot of cycle times per step">
      {grid.map((g) => (
        <g key={g}>
          <line x1={L} x2={W - 6} y1={y(g)} y2={y(g)} stroke={CHART.grid} />
          <text x={L - 6} y={y(g) + 4} textAnchor="end" fontSize="11" fill={CHART.tick}>
            {g}
          </text>
        </g>
      ))}
      <text x={12} y={(H - B) / 2} fontSize="11" fill={CHART.tick} transform={`rotate(-90 12 ${(H - B) / 2})`} textAnchor="middle">
        Cycle time (s)
      </text>
      {steps.map((s, i) => {
        const cx = L + bw * i + bw / 2;
        const half = Math.min(18, bw * 0.28);
        const words = `${s.sequence}. ${s.name}`.split(' ');
        const l1 = words.slice(0, 3).join(' ');
        const l2 = words.slice(3, 6).join(' ');
        return (
          <g key={s.station_id} className="cursor-pointer" onClick={() => navigate(`/reports/step/${s.station_id}${query}`)}>
            <title>{`${s.sequence}. ${s.name}: normal ${s.normal_cycle ?? '—'} s, box ${s.q1 ?? '—'}–${s.q3 ?? '—'} s, range ${s.min ?? '—'}–${s.max ?? '—'} s, average ${s.avg ?? '—'} s, ${s.abnormal_count} abnormal`}</title>
            <rect x={cx - bw / 2} y={T} width={bw} height={H - T - B} fill="transparent" />
            {s.median !== null && s.min !== null && s.max !== null && s.q1 !== null && s.q3 !== null && (
              <>
                <line x1={cx} x2={cx} y1={y(s.max)} y2={y(s.min)} stroke="#93c5fd" />
                <line x1={cx - half / 2} x2={cx + half / 2} y1={y(s.max)} y2={y(s.max)} stroke="#93c5fd" />
                <line x1={cx - half / 2} x2={cx + half / 2} y1={y(s.min)} y2={y(s.min)} stroke="#93c5fd" />
                <rect x={cx - half} y={y(s.q3)} width={half * 2} height={Math.max(2, y(s.q1) - y(s.q3))} fill="#3b82f6" fillOpacity={0.55} stroke="#60a5fa" rx={2} />
                <line x1={cx - half} x2={cx + half} y1={y(s.median)} y2={y(s.median)} stroke="#e0f2fe" strokeWidth={1.5} />
              </>
            )}
            {s.normal_cycle !== null && (
              <line x1={cx - bw * 0.45} x2={cx + bw * 0.45} y1={y(s.normal_cycle)} y2={y(s.normal_cycle)} stroke={CHART.takt} strokeDasharray="4 3" />
            )}
            {s.avg !== null && <circle cx={cx} cy={y(s.avg)} r={4.5} fill={AMBER} />}
            {s.abnormal_values.map((v, k) => (
              <rect key={k} x={cx - 4 + (k % 3) * 3 - 3} y={y(v) - 4} width={7} height={7} fill={RED} transform={`rotate(45 ${cx + (k % 3) * 3 - 3} ${y(v)})`} />
            ))}
            <text x={cx} y={H - B + 16} textAnchor="middle" fontSize="10" fill={CHART.tick}>
              {l1}
            </text>
            <text x={cx} y={H - B + 29} textAnchor="middle" fontSize="10" fill={CHART.tick}>
              {l2}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
