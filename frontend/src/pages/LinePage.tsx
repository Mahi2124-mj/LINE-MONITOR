import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChartColumnBig, Cctv, Download, Flame, Gauge, Lightbulb, PackageCheck, Scale, Timer, TrendingUp, Workflow } from 'lucide-react';
import { api } from '../api/client';
import type { Camera, LineAnalytics, RangeKey } from '../api/types';
import { readStorage, writeStorage } from '../lib/storage';
import { CameraTile } from '../components/CameraTile';
import { EmptyState, ErrorState, SkeletonPanel, SkeletonTiles, StaleBanner } from '../components/EmptyState';
import { KpiTile } from '../components/KpiTile';
import { Panel } from '../components/Panel';
import { ProcessFlow } from '../components/ProcessFlow';
import { RecommendationList } from '../components/RecommendationList';
import { HourlyOutputChart } from '../components/charts/HourlyOutputChart';
import { SlotOutputChart } from '../components/charts/SlotOutputChart';
import { YamazumiChart } from '../components/charts/YamazumiChart';
import { SlotPlanTable } from '../components/SlotPlanTable';
import { usePageTitle } from '../context/PageTitleContext';
import { useRange } from '../context/RangeContext';
import { usePolling } from '../hooks/usePolling';
import { bucketKind, fmtNum, fmtPct, fmtSec, pct } from '../lib/format';
import { attainmentTone, balanceTone } from '../lib/tones';

type PageShift = 'auto' | 'A' | 'B' | 'range';
const PAGE_SHIFT_KEY = 'lm.slotShift';
const SHIFT_NAME: Record<string, string> = { A: 'Shift A', B: 'Shift B' };
const RANGE_LABEL: Record<string, string> = { '1h': '1h', today: 'Today', '24h': '24h', '7d': '7d', '30d': '30d' };

export default function LinePage() {
  const params = useParams();
  const id = Number(params.id);
  const { range, rangeTitle } = useRange();
  const valid = Number.isInteger(id) && id > 0;

  // the whole page shows one shift: auto = the running shift (else the last one), or the one picked here (e.g. last
  // night's Shift B in the morning), or the range of the top bar. A shift picked in the top bar wins.
  const [pageShift, setPageShiftState] = useState<PageShift>(() => {
    const v = readStorage(PAGE_SHIFT_KEY);
    return v === 'A' || v === 'B' || v === 'range' ? v : 'auto';
  });
  const shiftInfo = usePolling(() => api.shifts().catch(() => null), [], 60_000);
  const sh = shiftInfo.data;
  const isRunning = (w: { end: string } | null | undefined) => !!w && Date.now() - new Date(w.end).getTime() < 120_000;
  const autoShift = sh
    ? ((['A', 'B'] as const)
        .filter((n) => sh[n])
        .sort((x, y) => Number(isRunning(sh[y])) - Number(isRunning(sh[x])) || sh[y]!.start.localeCompare(sh[x]!.start))[0] ?? null)
    : null;
  const shown: 'A' | 'B' | null =
    range === 'shiftA' ? 'A' : range === 'shiftB' ? 'B' : pageShift === 'range' ? null : pageShift === 'auto' ? autoShift : pageShift;
  const waiting = range !== 'shiftA' && range !== 'shiftB' && pageShift === 'auto' && shiftInfo.loading && !sh; // auto: which shift
  const key: RangeKey = shown === 'A' ? 'shiftA' : shown === 'B' ? 'shiftB' : range;

  const analytics = usePolling(() => (waiting ? Promise.resolve(null) : api.lineAnalytics(id, key)), [id, key, waiting], valid ? 15_000 : 0);
  const cameras = usePolling(() => api.cameras(id), [id], valid ? 30_000 : 0);
  const a = analytics.data;

  usePageTitle(a?.line.name ?? 'Line', [{ label: 'Overview', to: '/' }]);
  const [slot, setSlot] = useState<string | null>(null); // the time slot picked in the chart or the table
  const pickSlot = (label: string) => setSlot((s) => (s === label ? null : label));
  const setPageShift = (v: PageShift) => {
    setPageShiftState(v);
    writeStorage(PAGE_SHIFT_KEY, v);
    setSlot(null);
  };
  const shownTitle = shown ? (SHIFT_NAME[shown] ?? `Shift ${shown}`) : rangeTitle;

  const stationLabel = useMemo(() => {
    const m = new Map<number, string>();
    a?.stations.forEach((s) => m.set(s.station.id, `Step ${s.station.sequence} · ${s.station.name}`));
    return (sid: number) => m.get(sid);
  }, [a]);

  if (!valid) return <EmptyState title="Invalid line id" action={<Link to="/" className="btn">Back to overview</Link>} />;
  if ((analytics.loading || waiting) && !a) {
    return (
      <div className="space-y-4">
        <SkeletonTiles count={6} className="lg:grid-cols-6" />
        <SkeletonPanel className="h-72" />
        <SkeletonPanel className="h-80" />
      </div>
    );
  }
  if (!a) return <ErrorState error={analytics.error} onRetry={analytics.reload} />;

  const line = a.line;
  const attain = pct(a.output, a.planned_output);
  const slots = a.slots_today; // the shift shown (or today's production day for a range)
  const slotsOf = shown ? shownTitle : 'today';
  const shiftPick =
    sh && (sh.A || sh.B) && range !== 'shiftA' && range !== 'shiftB' ? (
      <select
        className="input h-8 w-auto py-0 text-xs"
        value={pageShift}
        onChange={(e) => setPageShift(e.target.value as PageShift)}
        aria-label="Shift"
        title="Which shift this page shows (Range: the time range of the top bar)"
      >
        <option value="auto">Auto</option>
        <option value="A">Shift A</option>
        <option value="B">Shift B</option>
        <option value="range">Range ({RANGE_LABEL[range] ?? range})</option>
      </select>
    ) : null;
  const targetPerHour = line.takt_time_sec > 0 ? 3600 / line.takt_time_sec : null;
  const bottleneck = a.operators?.find((o) => o.is_bottleneck) ?? null; // the bottleneck PERSON (may run several steps)

  return (
    <div className="space-y-4">
      <StaleBanner error={analytics.error} />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-ink-3">
              {shownTitle} · {a.stations.length} steps
            </span>
          </div>
          {line.description && <p className="mt-1 max-w-3xl text-sm text-ink-2">{line.description}</p>}
        </div>
        <div className="flex items-center gap-2">
          {shiftPick}
          <a className="btn btn-sm" href={api.exportCyclesUrl(key, line.id)} download>
            <Download className="size-3.5" /> Export cycles CSV
          </a>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
        <KpiTile
          label="Output / planned"
          icon={<PackageCheck className="size-4" />}
          value={fmtNum(a.output)}
          suffix={`/ ${fmtNum(a.planned_output)}`}
          progress={attain ?? 0}
          progressTone={attainmentTone(attain)}
          sub={`${attain === null ? 'No plan in range' : `${fmtPct(attain)} of plan`}${a.output_outside_plan ? ` · +${fmtNum(a.output_outside_plan)} outside planned time` : ''}`}
          title={a.output_outside_plan ? 'Output counts the parts of the planned time slots; parts made outside them (night shift, overtime) are shown apart' : undefined}
        />
        <KpiTile
          label="Throughput"
          icon={<TrendingUp className="size-4" />}
          value={fmtNum(a.throughput_per_hour, 1)}
          suffix="units/h"
          tone={a.throughput_per_hour !== null && targetPerHour !== null ? (a.throughput_per_hour >= targetPerHour * 0.95 ? 'good' : 'bad') : 'default'}
          sub={targetPerHour !== null ? `Demand ${fmtNum(targetPerHour, 1)} units/h` : undefined}
        />
        <KpiTile
          label="Capacity"
          icon={<Gauge className="size-4" />}
          value={fmtNum(a.capacity_per_hour, 1)}
          suffix="units/h"
          tone={a.capacity_per_hour !== null && targetPerHour !== null ? (a.capacity_per_hour >= targetPerHour ? 'good' : 'bad') : 'default'}
          sub="3600 / bottleneck time per part"
        />
        <KpiTile
          label="Balance efficiency"
          icon={<Scale className="size-4" />}
          value={fmtPct(a.balance_efficiency_pct)}
          tone={balanceTone(a.balance_efficiency_pct)}
          progress={a.balance_efficiency_pct ?? 0}
          sub="Σ time per part / (operators × slowest)"
        />
        <KpiTile label="Takt time" icon={<Timer className="size-4" />} value={fmtSec(line.takt_time_sec)} sub="Customer demand pace" />
        <KpiTile
          label="Bottleneck"
          icon={<Flame className="size-4" />}
          value={bottleneck ? (bottleneck.sequences.length > 1 ? `Steps ${bottleneck.sequences.join('+')}` : `Step ${bottleneck.sequences[0]}`) : '—'}
          tone={bottleneck ? 'bad' : 'muted'}
          sub={bottleneck ? `${bottleneck.label} · ${fmtSec(bottleneck.per_part_sec)} per part` : 'Not enough data'}
          title={bottleneck?.label}
        />
      </div>

      <Panel title="Process flow" subtitle="Live state per step · click a step for details" icon={<Workflow className="size-4" />}>
        <ProcessFlow stations={a.stations} taktSec={line.takt_time_sec} />
      </Panel>

      <Panel
        title="Line balance (Yamazumi)"
        subtitle={`Average time per part by operator (people who run several steps are one bar) · ${shownTitle} · label = operator content (work + motion)`}
        icon={<ChartColumnBig className="size-4" />}
      >
        {a.stations.length ? (
          <YamazumiChart stations={a.stations} operators={a.operators} taktSec={line.takt_time_sec} height={320} />
        ) : (
          <EmptyState compact title="No stations" />
        )}
      </Panel>

      <div className="grid items-start gap-4 xl:grid-cols-2">
        {a.slots_today.length > 0 ? (
          <Panel
            title={`Output vs plan per time slot · ${slotsOf}`}
            subtitle="Parts finished (median of the last three operators) · click a bar or a slot"
            icon={<PackageCheck className="size-4" />}
          >
            <SlotOutputChart slots={slots} selected={slot} onSelect={pickSlot} height={260} />
          </Panel>
        ) : (
          <Panel
            title={bucketKind(a.hourly.map((h) => h.hour)) === 'day' ? 'Daily output vs plan' : 'Hourly output vs plan'}
            subtitle="Parts finished (median of the last three operators)"
            icon={<PackageCheck className="size-4" />}
          >
            <HourlyOutputChart hourly={a.hourly} height={260} />
          </Panel>
        )}
        {a.slots_today.length > 0 ? (
          <Panel title={`Hourly plan vs actual · ${slotsOf}`} subtitle="Per time slot of the line (Setup → line → time slots)" icon={<Timer className="size-4" />}>
            <SlotPlanTable slots={slots} selected={slot} onSelect={pickSlot} />
          </Panel>
        ) : (
          <RecommendationsPanel a={a} stationLabel={stationLabel} />
        )}
      </div>
      {a.slots_today.length > 0 && <RecommendationsPanel a={a} stationLabel={stationLabel} />}

      <Panel
        title="Cameras"
        subtitle={cameras.data ? `${cameras.data.filter((c) => c.status.online).length} / ${cameras.data.length} online` : undefined}
        icon={<Cctv className="size-4" />}
        actions={
          <Link to="/cameras" className="text-xs link">
            All cameras
          </Link>
        }
      >
        <LineCameras cameras={cameras.data} error={cameras.error} stationLabel={stationLabel} onRetry={cameras.reload} />
      </Panel>
    </div>
  );
}

function LineCameras({
  cameras,
  error,
  stationLabel,
  onRetry,
}: {
  cameras: Camera[] | undefined;
  error: unknown;
  stationLabel: (id: number) => string | undefined;
  onRetry: () => void;
}) {
  if (!cameras) {
    if (error) return <ErrorState compact error={error} onRetry={onRetry} />;
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="aspect-video animate-pulse rounded-xl bg-panel-3/60" />
        ))}
      </div>
    );
  }
  if (!cameras.length) {
    return (
      <EmptyState
        compact
        icon={<Cctv className="size-6" strokeWidth={1.5} />}
        title="No cameras on this line"
        action={
          <Link to="/setup" className="btn btn-sm">
            Add cameras in Line setup
          </Link>
        }
      />
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-4">
      {cameras.map((c) => (
        <CameraTile key={c.id} camera={c} stationLabel={c.station_id !== null ? (stationLabel(c.station_id) ?? null) : null} />
      ))}
    </div>
  );
}

function RecommendationsPanel({ a, stationLabel }: { a: LineAnalytics; stationLabel: (id: number) => string | undefined }) {
  return (
    <Panel title="Improvement recommendations" subtitle="Rule-based, sorted by severity and saving" icon={<Lightbulb className="size-4" />}>
      <div className="max-h-[22rem] overflow-y-auto pr-1">
        <RecommendationList items={a.recommendations} stationLabel={stationLabel} />
      </div>
    </Panel>
  );
}
