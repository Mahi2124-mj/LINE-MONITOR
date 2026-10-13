import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChartColumnBig, Cctv, Download, Flame, Gauge, Lightbulb, PackageCheck, Scale, Timer, TrendingUp, Workflow } from 'lucide-react';
import { api } from '../api/client';
import type { Camera } from '../api/types';
import { CameraTile } from '../components/CameraTile';
import { EmptyState, ErrorState, SkeletonPanel, SkeletonTiles, StaleBanner } from '../components/EmptyState';
import { KpiTile } from '../components/KpiTile';
import { Panel } from '../components/Panel';
import { ProcessFlow } from '../components/ProcessFlow';
import { RecommendationList } from '../components/RecommendationList';
import { HourlyOutputChart } from '../components/charts/HourlyOutputChart';
import { YamazumiChart } from '../components/charts/YamazumiChart';
import { usePageTitle } from '../context/PageTitleContext';
import { useRange } from '../context/RangeContext';
import { usePolling } from '../hooks/usePolling';
import { bucketKind, fmtNum, fmtPct, fmtSec, pct } from '../lib/format';
import { attainmentTone, balanceTone } from '../lib/tones';

export default function LinePage() {
  const params = useParams();
  const id = Number(params.id);
  const { range, rangeTitle } = useRange();
  const valid = Number.isInteger(id) && id > 0;

  const analytics = usePolling(() => api.lineAnalytics(id, range), [id, range], valid ? 15_000 : 0);
  const cameras = usePolling(() => api.cameras(id), [id], valid ? 30_000 : 0);
  const a = analytics.data;

  usePageTitle(a?.line.name ?? 'Line', [{ label: 'Overview', to: '/' }]);

  const stationLabel = useMemo(() => {
    const m = new Map<number, string>();
    a?.stations.forEach((s) => m.set(s.station.id, `Step ${s.station.sequence} · ${s.station.name}`));
    return (sid: number) => m.get(sid);
  }, [a]);

  if (!valid) return <EmptyState title="Invalid line id" action={<Link to="/" className="btn">Back to overview</Link>} />;
  if (analytics.loading && !a) {
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
  const targetPerHour = line.takt_time_sec > 0 ? 3600 / line.takt_time_sec : null;
  const bottleneck = a.stations.find((s) => s.station.id === a.bottleneck_station_id) ?? null;

  return (
    <div className="space-y-4">
      <StaleBanner error={analytics.error} />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded bg-panel-3 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-ink-2">{line.code}</span>
            <span className="text-xs text-ink-3">
              Shift {line.shift_start}–{line.shift_end} · {a.stations.length} steps · {rangeTitle}
            </span>
          </div>
          {line.description && <p className="mt-1 max-w-3xl text-sm text-ink-2">{line.description}</p>}
        </div>
        <a className="btn btn-sm" href={api.exportCyclesUrl(range, line.id)} download>
          <Download className="size-3.5" /> Export cycles CSV
        </a>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
        <KpiTile
          label="Output / planned"
          icon={<PackageCheck className="size-4" />}
          value={fmtNum(a.output)}
          suffix={`/ ${fmtNum(a.planned_output)}`}
          progress={attain ?? 0}
          progressTone={attainmentTone(attain)}
          sub={attain === null ? 'No plan in range' : `${fmtPct(attain)} of plan`}
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
          sub="3600 / bottleneck content"
        />
        <KpiTile
          label="Balance efficiency"
          icon={<Scale className="size-4" />}
          value={fmtPct(a.balance_efficiency_pct)}
          tone={balanceTone(a.balance_efficiency_pct)}
          progress={a.balance_efficiency_pct ?? 0}
          sub="Σ content / (steps × max content)"
        />
        <KpiTile label="Takt time" icon={<Timer className="size-4" />} value={fmtSec(line.takt_time_sec)} sub="Customer demand pace" />
        <KpiTile
          label="Bottleneck"
          icon={<Flame className="size-4" />}
          value={bottleneck ? `Step ${bottleneck.station.sequence}` : '—'}
          tone={bottleneck ? 'bad' : 'muted'}
          sub={bottleneck ? `${bottleneck.station.name} · ${fmtSec(bottleneck.stats.avg_content)} content` : 'Not enough data'}
          title={bottleneck?.station.name}
        />
      </div>

      <Panel title="Process flow" subtitle="Live state per step · click a step for details" icon={<Workflow className="size-4" />}>
        <ProcessFlow stations={a.stations} taktSec={line.takt_time_sec} />
      </Panel>

      <Panel
        title="Line balance (Yamazumi)"
        subtitle={`Average time per cycle by step · ${rangeTitle} · label = operator content (work + motion)`}
        icon={<ChartColumnBig className="size-4" />}
      >
        {a.stations.length ? (
          <YamazumiChart stations={a.stations} taktSec={line.takt_time_sec} height={320} />
        ) : (
          <EmptyState compact title="No stations" />
        )}
      </Panel>

      <div className="grid items-start gap-4 xl:grid-cols-2">
        <Panel
          title={bucketKind(a.hourly.map((h) => h.hour)) === 'day' ? 'Daily output vs plan' : 'Hourly output vs plan'}
          subtitle="Units completed by the last step"
          icon={<PackageCheck className="size-4" />}
        >
          <HourlyOutputChart hourly={a.hourly} height={260} />
        </Panel>
        <Panel title="Improvement recommendations" subtitle="Rule-based, sorted by severity and saving" icon={<Lightbulb className="size-4" />}>
          <div className="max-h-[22rem] overflow-y-auto pr-1">
            <RecommendationList items={a.recommendations} stationLabel={stationLabel} />
          </div>
        </Panel>
      </div>

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
