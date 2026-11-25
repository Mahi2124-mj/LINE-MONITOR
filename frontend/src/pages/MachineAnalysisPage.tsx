import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, CircleAlert, Crown, ListVideo, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import type { MachineAnalysis, MachineElementBit } from '../api/types';
import { EmptyState, ErrorState, SkeletonPanel } from '../components/EmptyState';
import { KpiTile } from '../components/KpiTile';
import { Panel } from '../components/Panel';
import { WINDOW_LENGTHS, WindowPlayer } from '../components/WindowPlayer';
import { usePageTitle } from '../context/PageTitleContext';
import { useRange } from '../context/RangeContext';
import { usePolling } from '../hooks/usePolling';
import { fmtDelta, fmtNum, fmtSec } from '../lib/format';
import { rangeWindow } from '../lib/range';

const KIND_LABEL: Record<string, string> = { work: 'Hand work', walk: 'Walking', wait: 'Waiting', machine: 'Machine wait' };
const KIND_BADGE: Record<string, string> = {
  work: 'bg-emerald-500/15 text-emerald-300',
  walk: 'bg-amber-500/15 text-amber-300',
  wait: 'bg-red-500/15 text-red-300',
  machine: 'bg-violet-500/15 text-violet-300',
};
const hhmmss = (iso: string) => iso.slice(11, 19);

/** Cycle analysis per machine, from the cycles of the checked step detectors (the same data as the reports). */
export default function MachineAnalysisPage() {
  const { stationId } = useParams();
  return stationId ? <MachineView stationId={Number(stationId)} /> : <MachineIndex />;
}

/* ------------------------------------------------------------------ all machines */

function MachineIndex() {
  usePageTitle('Cycle analysis');
  const { range, rangeTitle } = useRange();
  const r = usePolling(() => rangeWindow(range).then((w) => api.machineAnalysisOverview(w.start, w.end)), [range], 60_000);
  if (!r.data) return r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : <SkeletonPanel className="h-80" />;
  return (
    <div className="space-y-4">
      <p className="max-w-4xl text-sm text-ink-2">
        Every machine's cycles with their element breakup, compared with the machine's standard cycle · {rangeTitle}. The same checked cycles as the
        reports: each step is counted by its own detector, checked against the video.
      </p>
      {r.data.lines.map((l) => (
        <Panel key={l.line.id} title={l.line.name} subtitle={`Takt ${fmtSec(l.line.takt_time_sec)}`} icon={<ListVideo className="size-4" />} flush>
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="border-b border-edge text-left text-xs text-ink-3">
                {['#', 'Machine', 'Operator', 'Cycles', 'Normal cycle', 'Standard', 'Cycles with issues'].map((h, i) => (
                  <th key={h} className={`px-3 py-2 font-medium ${i >= 3 ? 'text-right' : ''}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {l.steps.map((s) => (
                <tr key={s.station_id} className="border-b border-edge/60 hover:bg-white/[0.03]">
                  <td className="px-3 py-2 text-ink-3">{s.sequence}</td>
                  <td className="px-3 py-2">
                    {s.cycles ? (
                      <Link to={`/analysis/step/${s.station_id}`} className="text-ink hover:text-sky-300 hover:underline">
                        {s.name}
                      </Link>
                    ) : (
                      <span className="text-ink-2">{s.name}</span>
                    )}
                    {!s.checked && <span className="ml-2 text-[11px] text-ink-3">no checked detector</span>}
                  </td>
                  <td className="px-3 py-2 text-ink-3">{s.operator || '—'}</td>
                  <td className="px-3 py-2 text-right">{fmtNum(s.cycles)}</td>
                  <td className="px-3 py-2 text-right">{fmtSec(s.normal_cycle)}</td>
                  <td className="px-3 py-2 text-right">{fmtSec(s.standard)}</td>
                  <td className="px-3 py-2 text-right">
                    {s.issues_pct === null || s.issues_pct === undefined ? (
                      '—'
                    ) : (
                      <span className={`rounded px-1.5 py-0.5 ${s.issues_pct >= 35 ? 'bg-red-600/60 text-white' : s.issues_pct >= 20 ? 'bg-amber-600/50 text-amber-100' : 'bg-emerald-700/50 text-emerald-100'}`}>
                        {s.issues_pct}%
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      ))}
      <p className="text-xs text-ink-3">
        <Link to="/analysis/cameras" className="link">
          Older automatic analysis per camera
        </Link>{' '}
        (learned hand positions; not reliable where one camera sees several people, kept for reference).
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ one machine */

function MachineView({ stationId }: { stationId: number }) {
  const { range, rangeTitle } = useRange();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const len = WINDOW_LENGTHS.includes(Number(params.get('len'))) ? Number(params.get('len')) : WINDOW_LENGTHS[0];
  const r = usePolling(() => rangeWindow(range).then((w) => api.machineAnalysis(stationId, w.start, w.end)), [stationId, range], 60_000);
  const d = r.data;
  usePageTitle(d ? `${d.station.sequence}. ${d.station.name}` : 'Cycle analysis', [{ label: 'Cycle analysis', to: '/analysis' }]);
  if (!d) return r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : <SkeletonPanel className="h-96" />;
  const k = d.kpis;
  const std = d.standard;
  const colors = Object.fromEntries(d.elements.map((e) => [e.code, e.color]));
  const labels = Object.fromEntries(d.elements.map((e) => [e.code, e.label]));
  const scale = Math.max(std.total ?? 0, k.normal_cycle ?? 0) * 1.7 || 30;
  const stdBits = standardBits(d);
  // the window video: ?at= its start (unix s; none = the newest), ?len= its length; ?cycle= (older links) starts it at that cycle
  const unix = (iso: string) => Date.parse(iso) / 1000;
  const linked = params.get('cycle') ? d.cycles.find((c) => c.id === Number(params.get('cycle'))) : undefined;
  const at = params.get('at') ? Number(params.get('at')) : linked ? unix(linked.start) - 1 : null;
  const setWindow = (start: number | null, sec: number) => {
    const p = new URLSearchParams(params);
    if (start === null) p.delete('at');
    else p.set('at', start.toFixed(0));
    p.set('len', String(sec));
    p.delete('cycle');
    setParams(p, { replace: true });
  };
  const inWindow = (iso: string) => at !== null && unix(iso) >= at && unix(iso) < at + len;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">
            {d.station.sequence}. {d.station.name}
          </h1>
          <p className="text-xs text-ink-3">
            {d.station.operator ? `Operator ${d.station.operator} · ` : ''}checked detector {d.detector ?? '—'} · {rangeTitle}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="btn btn-sm" disabled={!d.prev_id} onClick={() => d.prev_id && navigate(`/analysis/step/${d.prev_id}`)}>
            <ChevronLeft className="size-4" /> Previous machine
          </button>
          <button type="button" className="btn btn-sm" disabled={!d.next_id} onClick={() => d.next_id && navigate(`/analysis/step/${d.next_id}`)}>
            Next machine <ChevronRight className="size-4" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <KpiTile label="Cycles analysed" value={fmtNum(k.cycles)} sub={`${fmtNum(k.ok)} OK · ${fmtNum(k.with_issues)} with issues`} />
        <KpiTile
          label="Cycles with issues"
          value={k.cycles ? `${Math.round((100 * k.with_issues) / k.cycles)}%` : '—'}
          tone={k.cycles && k.with_issues / k.cycles >= 0.35 ? 'bad' : 'default'}
        />
        <KpiTile label={std.source === 'master' ? 'Standard (master cycle)' : 'Standard (median)'} value={fmtSec(std.total)} />
        <KpiTile label="Average cycle" value={fmtSec(k.avg_cycle)} sub={std.total && k.avg_cycle ? `${fmtDelta(k.avg_cycle - std.total)} vs standard` : undefined} />
        <KpiTile label="Best cycle" value={fmtSec(k.best_cycle)} tone="good" sub="fastest normal cycle" />
      </div>

      <div id="window-video">
        <WindowPlayer stationId={stationId} at={at} sec={len} onWindow={setWindow} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel title="Elements" subtitle="From the checked detector of this machine · standard = median of the normal cycles" icon={<Sparkles className="size-4" />} flush>
          <div className="px-4 pt-3">
            <div className="mb-1 text-xs text-ink-3">Standard cycle</div>
            <Bits bits={stdBits} colors={colors} labels={labels} scale={scale} />
          </div>
          <div className="overflow-x-auto">
            <table className="mt-2 w-full text-sm tabular-nums">
              <thead>
                <tr className="border-b border-edge text-left text-xs text-ink-3">
                  {['Element', 'Kind', 'Standard', 'Average', 'Slowest 10%', 'In % of cycles'].map((h, i) => (
                    <th key={h} className={`px-3 py-2 font-medium ${i >= 2 ? 'text-right' : ''}`}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.elements.map((e) => (
                  <tr key={e.code} className="border-b border-edge/60">
                    <td className="px-3 py-1.5">
                      <span className="mr-2 inline-block size-2.5 rounded-sm align-middle" style={{ background: e.color }} />
                      <span className="text-ink-2">{e.label}</span>
                    </td>
                    <td className="px-3 py-1.5">
                      <span className={`rounded px-1.5 py-0.5 text-xs ${KIND_BADGE[e.kind] ?? ''}`}>{KIND_LABEL[e.kind] ?? e.kind}</span>
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtSec(e.standard)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtSec(e.avg)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtSec(e.p90)}</td>
                    <td className="px-3 py-1.5 text-right text-ink-3">{e.presence_pct ?? '—'}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        <Panel title="Most frequent issues" icon={<CircleAlert className="size-4" />}>
          {d.top_issues.length ? (
            <ul className="space-y-2 text-sm">
              {d.top_issues.map((t) => (
                <li key={t.text} className="flex items-start justify-between gap-3">
                  <span className="text-ink-2">{t.text}</span>
                  <span className="shrink-0 tabular-nums text-ink">{fmtNum(t.count)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState compact title="No issues" />
          )}
        </Panel>
      </div>

      <Panel title="Cycles" subtitle={`Newest first (last ${d.cycles.length}) · click a cycle to watch its minute in the video above`} flush>
        {d.cycles.length ? (
          <div className="max-h-[36rem] overflow-y-auto">
            <table className="w-full text-sm tabular-nums">
              <thead className="sticky top-0 bg-panel">
                <tr className="border-b border-edge text-left text-xs text-ink-3">
                  <th className="px-3 py-2 font-medium">Start</th>
                  <th className="px-3 py-2 text-right font-medium">Cycle</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="w-[40%] px-3 py-2 font-medium">Elements</th>
                  <th className="px-3 py-2 font-medium">Main issue</th>
                </tr>
              </thead>
              <tbody>
                {d.cycles.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => {
                      setWindow(unix(c.start) - 1, len);
                      document.getElementById('window-video')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }}
                    className={`cursor-pointer border-b border-edge/60 hover:bg-white/[0.04] ${inWindow(c.start) ? 'bg-sky-500/10' : ''}`}
                  >
                    <td className="px-3 py-1.5">
                      {hhmmss(c.start)}
                      {c.is_master && <Crown className="ml-1 inline size-3.5 text-amber-300" aria-label="standard (master) cycle" />}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtSec(c.sec)}</td>
                    <td className="px-3 py-1.5">
                      <span className={`rounded px-2 py-0.5 text-xs font-semibold ${c.status === 'ok' ? 'bg-emerald-600/70 text-white' : 'bg-red-600/70 text-white'}`}>
                        {c.status === 'ok' ? 'OK' : `${c.issue_count} issue${c.issue_count === 1 ? '' : 's'}`}
                      </span>
                    </td>
                    <td className="px-3 py-1.5">
                      <Bits bits={c.el} colors={colors} labels={labels} scale={scale} small />
                    </td>
                    <td className="max-w-[18rem] truncate px-3 py-1.5 text-xs text-ink-3" title={c.top_issue ?? ''}>
                      {c.top_issue ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState compact title="No cycles in this time range" message="The line did not run, or pick a longer range in the top bar." />
        )}
      </Panel>
    </div>
  );
}

/** the standard as a bar: the elements in the detector's order with their standard times */
function standardBits(d: MachineAnalysis): MachineElementBit[] {
  let t = 0;
  return d.elements
    .filter((e) => e.standard)
    .map((e) => {
      const b = { code: e.code, start: t, dur: e.standard ?? 0 };
      t += e.standard ?? 0;
      return b;
    });
}

function Bits({ bits, colors, labels, scale, small }: { bits: MachineElementBit[]; colors: Record<string, string>; labels: Record<string, string>; scale: number; small?: boolean }) {
  return (
    <div className={`relative w-full overflow-hidden rounded bg-white/[0.04] ${small ? 'h-3.5' : 'h-6'}`}>
      {bits.map((b, i) => (
        <div
          key={i}
          className="absolute inset-y-0 border-r border-black/40"
          style={{ left: `${(100 * b.start) / scale}%`, width: `${(100 * b.dur) / scale}%`, background: colors[b.code] ?? '#64748b' }}
          title={`${labels[b.code] ?? b.code}: ${b.dur.toFixed(1)} s`}
        />
      ))}
    </div>
  );
}
