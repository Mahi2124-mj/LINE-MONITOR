import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Cctv,
  ChartLine,
  ChartColumn,
  Download,
  Footprints,
  Hand,
  Lightbulb,
  ListChecks,
  Package,
  Plus,
  Repeat,
  Ruler,
  Sigma,
  Sparkles,
  Target,
  Timer,
  User,
} from 'lucide-react';
import { api } from '../api/client';
import type { Camera, CycleRecord, Station, StationAnalytics } from '../api/types';
import { EmptyState, ErrorState, Skeleton, SkeletonPanel, SkeletonTiles, StaleBanner } from '../components/EmptyState';
import { HeatmapCanvas } from '../components/HeatmapCanvas';
import { KpiTile } from '../components/KpiTile';
import { LiveCycleTimer } from '../components/LiveCycleTimer';
import { LiveStream } from '../components/LiveStream';
import { Panel } from '../components/Panel';
import { RecommendationList } from '../components/RecommendationList';
import { Segmented } from '../components/RangeSelector';
import { BottleneckBadge, Chip, StateBadge } from '../components/StateBadge';
import { BreakdownDonut, CycleHistogram, CycleTrendChart, HourlyAvgChart } from '../components/charts/StationCharts';
import { useCycleEvents, useStationLive } from '../context/LiveContext';
import { usePageTitle } from '../context/PageTitleContext';
import { useRange } from '../context/RangeContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage, fmtDateTime, fmtMeters, fmtNum, fmtPct, fmtSec } from '../lib/format';
import { BREAKDOWN } from '../lib/meta';

export default function StationPage() {
  const params = useParams();
  const id = Number(params.id);
  const valid = Number.isInteger(id) && id > 0;
  const { range, rangeTitle } = useRange();

  const analytics = usePolling(() => api.stationAnalytics(id, range), [id, range], valid ? 15_000 : 0);
  const a = analytics.data;

  usePageTitle(
    a ? `Step ${a.station.sequence} · ${a.station.name}` : 'Station',
    a ? [{ label: 'Overview', to: '/' }, { label: a.line.name, to: `/lines/${a.line.id}` }] : [{ label: 'Overview', to: '/' }],
  );

  if (!valid) return <EmptyState title="Invalid station id" action={<Link to="/" className="btn">Back to overview</Link>} />;
  if (analytics.loading && !a) {
    return (
      <div className="space-y-4">
        <div className="grid gap-4 xl:grid-cols-2">
          <SkeletonPanel className="h-72" />
          <SkeletonPanel className="h-72" />
        </div>
        <SkeletonTiles count={8} className="lg:grid-cols-8" />
        <SkeletonPanel className="h-72" />
      </div>
    );
  }
  if (!a) return <ErrorState error={analytics.error} onRetry={analytics.reload} />;

  return <StationView a={a} error={analytics.error} reload={analytics.reload} rangeTitle={rangeTitle} />;
}

function StationView({ a, error, reload, rangeTitle }: { a: StationAnalytics; error: unknown; reload: () => void; rangeTitle: string }) {
  const { range } = useRange();
  const st = a.station;
  const live = useStationLive(st.id, a.live);
  const [camId, setCamId] = useState<number | null>(st.camera_ids[0] ?? null);
  const camKey = st.camera_ids.join(',');
  useEffect(() => {
    const ids = camKey ? camKey.split(',').map(Number) : [];
    setCamId((cur) => (cur !== null && ids.includes(cur) ? cur : (ids[0] ?? null)));
  }, [camKey]);

  const camera = usePolling<Camera | null>(() => (camId !== null ? api.camera(camId) : Promise.resolve(null)), [camId], 30_000);

  const [trendMode, setTrendMode] = useState<'cycle' | 'breakdown'>('cycle');
  const s = a.stats;
  const m = a.movement;
  const takt = a.line.takt_time_sec;

  return (
    <div className="space-y-4">
      <StaleBanner error={error} />

      {/* --- header: info + live ------------------------------------------------ */}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <Panel
            title={
              <span className="flex items-center gap-2">
                Step {st.sequence} · {st.name}
                {a.is_bottleneck && <BottleneckBadge size="xs" />}
              </span>
            }
            subtitle={`${a.line.name} · ${st.code}`}
            actions={<StateBadge state={live?.state ?? (st.camera_ids.length ? 'offline' : 'no_camera')} />}
          >
            <StepNav prev={a.prev_station} current={st} next={a.next_station} />
            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div className="col-span-2">
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Operation</dt>
                <dd className="mt-0.5 text-ink-2">{st.operation || '—'}</dd>
              </div>
              <div className="col-span-2">
                <dt className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                  <Package className="size-3" /> Parts added
                </dt>
                <dd className="mt-1 flex flex-wrap gap-1">
                  {st.parts_added.length ? (
                    st.parts_added.map((p) => (
                      <Chip key={p} className="border-sky-500/30 bg-sky-500/10 text-sky-200">
                        {p}
                      </Chip>
                    ))
                  ) : (
                    <span className="text-ink-3">—</span>
                  )}
                </dd>
              </div>
              <InfoItem icon={<User className="size-3" />} label="Operator" value={st.operator_name || '—'} />
              <InfoItem icon={<Target className="size-3" />} label="Target cycle" value={fmtSec(st.target_cycle_sec)} />
              <InfoItem icon={<Timer className="size-3" />} label="Line takt" value={fmtSec(takt)} />
              <InfoItem icon={<Hand className="size-3" />} label="Expected picks" value={`${fmtNum(st.expected_picks)} / cycle`} />
            </dl>
          </Panel>

          <Panel title="Live" subtitle="Updated every second via WebSocket" icon={<Timer className="size-4" />}>
            <LiveCycleTimer live={live} targetSec={st.target_cycle_sec} size="lg" />
            <div className="mt-3 grid grid-cols-3 gap-2 border-t border-edge pt-3 text-center">
              <MiniStat label="Last cycle" value={fmtSec(live?.last_cycle_sec)} />
              <MiniStat label="Cycles today" value={fmtNum(live?.count_today)} />
              <MiniStat label="Avg today" value={fmtSec(live?.avg_today_sec)} />
            </div>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <Presence ok={live?.operator_present} label="Operator present" />
              <Presence ok={live?.part_present} label="Part present" />
            </div>
          </Panel>
        </div>

        <Panel
          title="Camera"
          icon={<Cctv className="size-4" />}
          flush
          actions={
            st.camera_ids.length > 1 ? (
              <select className="input w-auto py-1 text-xs" value={camId ?? ''} onChange={(e) => setCamId(Number(e.target.value))}>
                {st.camera_ids.map((cid) => (
                  <option key={cid} value={cid}>
                    Camera #{cid}
                  </option>
                ))}
              </select>
            ) : camId !== null ? (
              <span className="flex items-center gap-3">
                <Link to={`/analysis/${camId}`} className="btn btn-sm btn-primary">
                  Element breakup
                </Link>
                <Link to={`/cameras/${camId}`} className="text-xs link">
                  Camera setup
                </Link>
              </span>
            ) : undefined
          }
        >
          {camId !== null ? (
            <div className="relative">
              <LiveStream cameraId={camId} overlay />
              <div className="pointer-events-none absolute top-2 left-2 flex items-center gap-2">
                <StateBadge state={live?.state} />
              </div>
              {camera.data && <div className="px-4 py-2 text-xs text-ink-3">{camera.data.name}</div>}
            </div>
          ) : (
            <EmptyState
              icon={<Cctv className="size-8" strokeWidth={1.5} />}
              title="No camera at this step"
              message="Cycle times can be entered manually below, or assign a camera in Line setup."
            />
          )}
        </Panel>
      </div>

      {/* --- stats ---------------------------------------------------------------- */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 2xl:grid-cols-8">
        <KpiTile label="Cycles" value={fmtNum(s.count)} sub={rangeTitle} icon={<Repeat className="size-4" />} />
        <KpiTile
          label="Average cycle"
          value={fmtSec(s.avg)}
          sub={
            <span>
              content <span className={`font-semibold ${s.avg_content !== null && s.avg_content > st.target_cycle_sec ? 'text-rose-400' : 'text-emerald-400'}`}>{fmtSec(s.avg_content)}</span> · target{' '}
              {fmtSec(st.target_cycle_sec)}
            </span>
          }
          title="Cycle includes waiting; the target is compared with operator content (work + motion)"
        />
        <KpiTile label="Median" value={fmtSec(s.median)} />
        <KpiTile label="P90" value={fmtSec(s.p90)} sub="90% of cycles faster" />
        <KpiTile label="Min" value={fmtSec(s.min)} />
        <KpiTile label="Max" value={fmtSec(s.max)} />
        <KpiTile
          label="Std dev / CV"
          icon={<Sigma className="size-4" />}
          value={fmtSec(s.std)}
          suffix={s.cv !== null ? `CV ${fmtPct(s.cv * 100)}` : undefined}
          tone={s.cv === null ? 'default' : s.cv > 0.25 ? 'bad' : s.cv > 0.15 ? 'warn' : 'good'}
          sub="Stability (CV < 15% is good)"
        />
        <KpiTile
          label="Over target"
          title="Share of cycles whose operator content (work + motion) exceeded the station target"
          value={fmtPct(s.over_target_pct)}
          tone={s.over_target_pct === null ? 'default' : s.over_target_pct > 20 ? 'bad' : s.over_target_pct > 5 ? 'warn' : 'good'}
          sub={s.over_takt_pct !== null ? `${fmtPct(s.over_takt_pct)} over takt` : undefined}
        />
      </div>

      {/* --- charts ---------------------------------------------------------------- */}
      <Panel
        title="Cycle time trend"
        subtitle={`${a.trend.length} cycles (downsampled) · ${rangeTitle}`}
        icon={<ChartLine className="size-4" />}
        actions={
          <Segmented
            size="xs"
            value={trendMode}
            onChange={setTrendMode}
            options={[
              { value: 'cycle', label: 'Cycle time' },
              { value: 'breakdown', label: 'Work / motion / wait' },
            ]}
          />
        }
      >
        <CycleTrendChart trend={a.trend} targetSec={st.target_cycle_sec} taktSec={takt} mode={trendMode} height={280} />
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Distribution" subtitle="Cycle time histogram" icon={<ChartColumn className="size-4" />}>
          <CycleHistogram buckets={a.histogram} targetSec={st.target_cycle_sec} />
        </Panel>
        <Panel title="Hourly average" subtitle="Average cycle time per hour" icon={<ChartColumn className="size-4" />}>
          <HourlyAvgChart hourly={a.hourly} targetSec={st.target_cycle_sec} />
        </Panel>
      </div>

      {/* --- movement --------------------------------------------------------------- */}
      <Panel
        title="Movement analysis"
        subtitle="Where the operator’s time and motion go – lean motion waste"
        icon={<Footprints className="size-4" />}
      >
        <div className="grid gap-5 xl:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
          <div className="min-w-0 space-y-4">
            <BreakdownDonut va={m.va_pct} motion={m.motion_waste_pct} wait={m.wait_pct} />
            <div className="grid grid-cols-2 gap-2">
              <MoveTile icon={<Hand className="size-3.5" />} label="Hand travel" value={fmtMeters(m.avg_hand_travel_m)} unit="per cycle" />
              <MoveTile icon={<Ruler className="size-3.5" />} label="Reaches outside" value={fmtNum(m.avg_reach_count, 1)} unit="per cycle" warn={(m.avg_reach_count ?? 0) > 0.5} />
              <MoveTile icon={<Footprints className="size-3.5" />} label="Walking" value={fmtMeters(m.avg_walk_m)} unit="per cycle" warn={(m.avg_walk_m ?? 0) > 1} />
              <MoveTile
                icon={<ListChecks className="size-3.5" />}
                label="Picks"
                value={`${fmtNum(m.avg_pick_count, 1)} / ${fmtNum(m.expected_picks)}`}
                unit="actual / expected"
                warn={m.avg_pick_count !== null && m.avg_pick_count > m.expected_picks}
              />
              <div className="col-span-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3">
                <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-emerald-300">
                  <Sparkles className="size-3.5" /> Est. saving by removing extra motion
                </div>
                <div className="mt-1 text-2xl font-semibold text-emerald-300 tabular-nums">
                  {m.est_saving_sec !== null ? `~${fmtSec(m.est_saving_sec)}` : '—'}
                  <span className="ml-1.5 text-sm font-normal text-emerald-200/70">per cycle</span>
                </div>
                {m.est_saving_sec !== null && s.avg !== null && s.avg > 0 && (
                  <div className="text-xs text-emerald-200/70">≈ {fmtPct((m.est_saving_sec / s.avg) * 100, 1)} of the average cycle</div>
                )}
              </div>
            </div>
            <p className="text-[11px] leading-relaxed text-ink-3">
              <span className={BREAKDOWN.motion.text}>Motion waste</span> = reaching outside the work area, walking and time away from the station.{' '}
              <span className={BREAKDOWN.wait.text}>Wait</span> = waiting for parts / blocked / idle.
            </p>
          </div>
          <div className="min-w-0">
            {camId !== null ? (
              <HeatmapCanvas cameraId={camId} range={range} zones={camera.data?.zones ?? []} />
            ) : (
              <EmptyState compact title="No camera – no movement tracking" message="Heatmaps and spaghetti diagrams need a camera on this step." />
            )}
          </div>
        </div>
      </Panel>

      <Panel title="Recommendations" subtitle="What to improve at this step" icon={<Lightbulb className="size-4" />}>
        <RecommendationList items={a.recommendations} />
      </Panel>

      <RecentCycles station={st} hasCamera={st.camera_ids.length > 0} onAdded={reload} />
    </div>
  );
}

/* ------------------------------------------------------------------ pieces */

function StepNav({ prev, current, next }: { prev: Station | null; current: Station; next: Station | null }) {
  return (
    <div className="flex items-stretch gap-1.5 text-xs">
      {prev ? (
        <Link to={`/stations/${prev.id}`} className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg border border-edge bg-panel-2 px-2 py-1.5 hover:border-edge-2 hover:bg-panel-3">
          <ArrowLeft className="size-3.5 shrink-0 text-ink-3" />
          <span className="min-w-0">
            <span className="block text-[10px] text-ink-3">Previous · Step {prev.sequence}</span>
            <span className="block truncate font-medium text-ink-2">{prev.name}</span>
          </span>
        </Link>
      ) : (
        <div className="flex flex-1 items-center rounded-lg border border-dashed border-edge px-2 py-1.5 text-ink-3">Line start</div>
      )}
      <div className="flex min-w-0 flex-1 flex-col justify-center rounded-lg border border-sky-500/50 bg-sky-500/10 px-2 py-1.5">
        <span className="text-[10px] text-sky-300">This step · {current.sequence}</span>
        <span className="truncate font-semibold text-ink">{current.name}</span>
      </div>
      {next ? (
        <Link to={`/stations/${next.id}`} className="flex min-w-0 flex-1 items-center justify-end gap-1.5 rounded-lg border border-edge bg-panel-2 px-2 py-1.5 text-right hover:border-edge-2 hover:bg-panel-3">
          <span className="min-w-0">
            <span className="block text-[10px] text-ink-3">Next · Step {next.sequence}</span>
            <span className="block truncate font-medium text-ink-2">{next.name}</span>
          </span>
          <ArrowRight className="size-3.5 shrink-0 text-ink-3" />
        </Link>
      ) : (
        <div className="flex flex-1 items-center justify-end rounded-lg border border-dashed border-edge px-2 py-1.5 text-ink-3">Line end</div>
      )}
    </div>
  );
}

function InfoItem({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
        {icon}
        {label}
      </dt>
      <dd className="mt-0.5 truncate font-medium text-ink tabular-nums">{value}</dd>
    </div>
  );
}

function MiniStat({ label, value, tone = 'default' }: { label: string; value: string; tone?: 'default' | 'good' | 'bad' | 'warn' | 'info' | 'muted' }) {
  const cls = tone === 'bad' ? 'text-rose-400' : tone === 'good' ? 'text-emerald-400' : 'text-ink';
  return (
    <div>
      <div className="text-[10px] text-ink-3">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${cls}`}>{value}</div>
    </div>
  );
}

function Presence({ ok, label }: { ok: boolean | undefined; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 ring-1 ring-inset ${
        ok ? 'bg-emerald-500/10 text-emerald-300 ring-emerald-500/30' : 'bg-zinc-500/10 text-ink-3 ring-zinc-500/30'
      }`}
    >
      <span className={`size-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-zinc-500'}`} />
      {label}: {ok === undefined ? '—' : ok ? 'yes' : 'no'}
    </span>
  );
}

function MoveTile({ icon, label, value, unit, warn }: { icon: ReactNode; label: string; value: string; unit: string; warn?: boolean }) {
  return (
    <div className={`rounded-lg border p-2.5 ${warn ? 'border-orange-500/40 bg-orange-500/5' : 'border-edge bg-panel-2'}`}>
      <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-ink-3">
        {icon}
        {label}
      </div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${warn ? 'text-orange-300' : 'text-ink'}`}>{value}</div>
      <div className="text-[10px] text-ink-3">{unit}</div>
    </div>
  );
}

/* ----------------------------------------------------------- recent cycles */

function RecentCycles({ station, hasCamera, onAdded }: { station: Station; hasCamera: boolean; onAdded: () => void }) {
  const { range } = useRange();
  const cycles = usePolling(() => api.stationCycles(station.id, range, 50), [station.id, range], 30_000);
  const [fresh, setFresh] = useState<Set<number>>(new Set());
  const [showForm, setShowForm] = useState(!hasCamera);

  const prepend = (c: CycleRecord) => {
    cycles.setData((prev) => {
      const list = prev ?? [];
      if (list.some((x) => x.id === c.id)) return list;
      return [c, ...list].slice(0, 100);
    });
    setFresh((f) => new Set(f).add(c.id));
    setTimeout(
      () =>
        setFresh((f) => {
          const n = new Set(f);
          n.delete(c.id);
          return n;
        }),
      4000,
    );
  };

  useCycleEvents(prepend, { stationId: station.id });

  const rows = useMemo(() => [...(cycles.data ?? [])].sort((x, y) => (x.ended_at < y.ended_at ? 1 : -1)), [cycles.data]);

  return (
    <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_340px]">
      <Panel
        title="Recent cycles"
        subtitle="New cycles appear live"
        icon={<Repeat className="size-4" />}
        flush
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => setShowForm((v) => !v)}>
              <Plus className="size-3.5" /> Manual entry
            </button>
            <a className="btn btn-sm" href={api.exportCyclesUrl(range, station.line_id, station.id)} download>
              <Download className="size-3.5" /> CSV
            </a>
          </>
        }
        className={showForm ? '' : '2xl:col-span-2'}
      >
        {!cycles.data ? (
          cycles.error ? (
            <ErrorState compact error={cycles.error} onRetry={cycles.reload} />
          ) : (
            <div className="space-y-2 p-4">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          )
        ) : rows.length === 0 ? (
          <EmptyState compact title="No cycles in this range" />
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="table-dense">
              <thead>
                <tr>
                  <th>Ended</th>
                  <th className="text-right!">Cycle</th>
                  <th className="text-right!" title="Operator content = work + motion (compared with target)">
                    Content
                  </th>
                  <th className="text-right!">Work</th>
                  <th className="text-right!">Motion</th>
                  <th className="text-right!">Wait</th>
                  <th className="text-right!">Reaches</th>
                  <th className="text-right!">Picks</th>
                  <th className="text-right!">Walk</th>
                  <th>Source</th>
                  <th>Target</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id} className={fresh.has(c.id) ? 'animate-slide-in [&>td]:bg-sky-500/10' : ''}>
                    <td className="text-ink-2">{fmtDateTime(c.ended_at)}</td>
                    <td className="text-right font-semibold text-ink tabular-nums">{fmtSec(c.cycle_sec)}</td>
                    <td className={`text-right font-semibold tabular-nums ${c.over_target ? 'text-rose-400' : 'text-emerald-400'}`}>{fmtSec(c.work_sec + c.motion_waste_sec)}</td>
                    <td className="text-right tabular-nums text-emerald-300/90">{fmtSec(c.work_sec)}</td>
                    <td className={`text-right tabular-nums ${c.motion_waste_sec > 0.5 ? 'text-orange-300' : 'text-ink-2'}`}>{fmtSec(c.motion_waste_sec)}</td>
                    <td className="text-right tabular-nums text-ink-2">{fmtSec(c.wait_sec)}</td>
                    <td className={`text-right tabular-nums ${c.reach_count > 0 ? 'text-orange-300' : 'text-ink-2'}`}>{fmtNum(c.reach_count)}</td>
                    <td className={`text-right tabular-nums ${c.pick_count > station.expected_picks ? 'font-semibold text-orange-300' : 'text-ink-2'}`}>
                      {fmtNum(c.pick_count)}
                      <span className="text-ink-3">/{station.expected_picks}</span>
                    </td>
                    <td className="text-right tabular-nums text-ink-2">{fmtMeters(c.walk_m, 1)}</td>
                    <td className="text-xs text-ink-3">{c.source}</td>
                    <td>
                      {c.over_target ? (
                        <span
                          className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-bold text-rose-300 ring-1 ring-rose-500/30"
                          title="Operator content exceeded the station target"
                        >
                          OVER
                        </span>
                      ) : (
                        <span className="text-[10px] font-semibold text-emerald-400/80">OK</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      {showForm && (
        <ManualCycleForm
          station={station}
          onAdded={(c) => {
            prepend(c);
            onAdded();
          }}
        />
      )}
    </div>
  );
}

function ManualCycleForm({ station, onAdded }: { station: Station; onAdded: (c: CycleRecord) => void }) {
  const { push } = useToast();
  const [cycle, setCycle] = useState('');
  const [work, setWork] = useState('');
  const [motion, setMotion] = useState('');
  const [wait, setWait] = useState('');
  const [busy, setBusy] = useState(false);

  const num = (v: string) => (v.trim() === '' ? undefined : Number(v));
  const cycleN = Number(cycle);
  const parts = [num(work), num(motion), num(wait)];
  const invalid = !cycle || !Number.isFinite(cycleN) || cycleN <= 0 || parts.some((p) => p !== undefined && (!Number.isFinite(p) || p < 0));
  const sumParts = parts.reduce<number>((s, p) => s + (p ?? 0), 0);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (invalid) return;
    setBusy(true);
    try {
      const c = await api.addManualCycle(station.id, {
        cycle_sec: cycleN,
        work_sec: num(work),
        motion_waste_sec: num(motion),
        wait_sec: num(wait),
      });
      push({ kind: 'success', title: 'Cycle recorded', message: `${fmtSec(c.cycle_sec)} at Step ${station.sequence} · ${station.name}` });
      onAdded(c);
      setCycle('');
      setWork('');
      setMotion('');
      setWait('');
    } catch (err) {
      push({ kind: 'critical', title: 'Could not add cycle', message: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Manual cycle entry" subtitle="For steps without a camera (stopwatch study)" icon={<Plus className="size-4" />}>
      <form onSubmit={submit} className="space-y-3">
        <label className="block">
          <span className="label">Cycle time (s) *</span>
          <input className="input" type="number" min={0} step="0.1" required value={cycle} onChange={(e) => setCycle(e.target.value)} placeholder={`e.g. ${station.target_cycle_sec}`} />
        </label>
        <div className="grid grid-cols-3 gap-2">
          <label className="block">
            <span className="label">Work (s)</span>
            <input className="input" type="number" min={0} step="0.1" value={work} onChange={(e) => setWork(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Motion (s)</span>
            <input className="input" type="number" min={0} step="0.1" value={motion} onChange={(e) => setMotion(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">Wait (s)</span>
            <input className="input" type="number" min={0} step="0.1" value={wait} onChange={(e) => setWait(e.target.value)} />
          </label>
        </div>
        <p className="hint">
          Breakdown is optional. If given it should add up to the cycle time
          {sumParts > 0 && cycle && Math.abs(sumParts - cycleN) > 0.5 && <span className="text-amber-300"> (currently {fmtSec(sumParts)})</span>}.
        </p>
        <button type="submit" className="btn btn-primary w-full" disabled={invalid || busy}>
          {busy ? 'Saving…' : 'Add cycle'}
        </button>
      </form>
    </Panel>
  );
}
