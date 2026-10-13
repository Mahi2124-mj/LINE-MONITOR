import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Bell, Cctv, Factory, Flame, Gauge, PackageCheck, Scale, Settings2, Timer } from 'lucide-react';
import { api } from '../api/client';
import type { OverviewLine } from '../api/types';
import { EmptyState, ErrorState, SkeletonPanel, SkeletonTiles, StaleBanner } from '../components/EmptyState';
import { KpiTile, TONE_TEXT } from '../components/KpiTile';
import { ProcessStrip } from '../components/ProcessStrip';
import { ProgressBar } from '../components/ProgressBar';
import { useLive, useLiveStates } from '../context/LiveContext';
import { usePageTitle } from '../context/PageTitleContext';
import { useRange } from '../context/RangeContext';
import { usePolling } from '../hooks/usePolling';
import { fmtNum, fmtPct, fmtSec, pct } from '../lib/format';
import { STATE_STYLE } from '../lib/meta';
import { attainmentTone, balanceTone, limitTone } from '../lib/tones';
import type { StationState } from '../api/types';

export default function OverviewPage() {
  usePageTitle('Overview');
  const { range, rangeTitle } = useRange();
  const { connected, openAlerts } = useLive();
  const { data, error, loading, reload } = usePolling(() => api.overview(range), [range], 15_000);

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <SkeletonTiles />
        <div className="grid gap-4 2xl:grid-cols-2">
          <SkeletonPanel className="h-60" />
          <SkeletonPanel className="h-60" />
        </div>
      </div>
    );
  }
  if (!data) return <ErrorState error={error} onRetry={reload} />;

  const t = data.totals;
  const attain = pct(t.output, t.planned_output);
  const alerts = connected ? openAlerts : t.open_alerts;

  return (
    <div className="space-y-4">
      <StaleBanner error={error} />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          label={`Output · ${rangeTitle}`}
          icon={<PackageCheck className="size-4" />}
          value={fmtNum(t.output)}
          suffix={`/ ${fmtNum(t.planned_output)} planned`}
          progress={attain ?? 0}
          progressTone={attainmentTone(attain)}
          sub={attain === null ? 'No plan in range' : `${fmtPct(attain)} of plan`}
          size="lg"
        />
        <KpiTile label="Lines" icon={<Factory className="size-4" />} value={fmtNum(t.lines)} suffix={`· ${fmtNum(t.stations)} stations`} sub="Production lines monitored" size="lg" />
        <KpiTile
          label="Cameras online"
          icon={<Cctv className="size-4" />}
          value={fmtNum(t.cameras_online)}
          suffix={`/ ${fmtNum(t.cameras_total)}`}
          tone={t.cameras_total === 0 ? 'muted' : t.cameras_online === t.cameras_total ? 'good' : t.cameras_online === 0 ? 'bad' : 'warn'}
          progress={t.cameras_total ? (t.cameras_online / t.cameras_total) * 100 : 0}
          sub={t.cameras_total - t.cameras_online > 0 ? `${t.cameras_total - t.cameras_online} offline` : 'All cameras streaming'}
          size="lg"
        />
        <Link to="/alerts" className="block rounded-xl transition hover:ring-1 hover:ring-edge-2">
          <KpiTile
            label="Open alerts"
            icon={<Bell className="size-4" />}
            value={fmtNum(alerts)}
            tone={alerts > 0 ? 'bad' : 'good'}
            sub={alerts > 0 ? 'Click to review & acknowledge' : 'Nothing needs attention'}
            size="lg"
          />
        </Link>
      </div>

      {data.lines.length === 0 ? (
        <div className="rounded-xl border border-edge bg-panel">
          <EmptyState
            icon={<Factory className="size-9" strokeWidth={1.5} />}
            title="No production lines yet"
            message="Create a line with its process steps (stations) and cameras to start monitoring."
            action={
              <Link to="/setup" className="btn btn-primary">
                <Settings2 className="size-4" /> Go to line setup
              </Link>
            }
          />
        </div>
      ) : (
        <div className="grid gap-4 2xl:grid-cols-2">
          {data.lines.map((l) => (
            <LineCard key={l.line.id} item={l} />
          ))}
        </div>
      )}
    </div>
  );
}

function LineCard({ item }: { item: OverviewLine }) {
  const { states } = useLiveStates();
  const { line } = item;
  const attain = pct(item.output, item.planned_output);
  const paceTone = limitTone(item.line_pace_sec, line.takt_time_sec);

  // live state counts for the header
  const counts = new Map<StationState, number>();
  for (const s of item.stations) {
    const st = states.get(s.id)?.state ?? s.state;
    counts.set(st, (counts.get(st) ?? 0) + 1);
  }

  return (
    <Link
      to={`/lines/${line.id}`}
      className={`group block rounded-xl border border-edge bg-panel p-4 transition hover:border-edge-2 hover:bg-panel-2/60 ${line.is_active ? '' : 'opacity-70'}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-base font-semibold text-ink group-hover:text-sky-300">{line.name}</h2>
            <span className="rounded bg-panel-3 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-ink-2">{line.code}</span>
            {!line.is_active && <span className="rounded bg-zinc-700/50 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-300">INACTIVE</span>}
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-3">
            {[...counts.entries()].map(([st, n]) => (
              <span key={st} className="flex items-center gap-1">
                <span className={`size-1.5 rounded-full ${STATE_STYLE[st].dot}`} />
                {n} {STATE_STYLE[st].label.toLowerCase()}
              </span>
            ))}
          </div>
        </div>
        {item.open_alerts > 0 && (
          <span className="flex items-center gap-1 rounded-full bg-red-500/15 px-2 py-0.5 text-xs font-semibold text-red-300 ring-1 ring-red-500/40">
            <Bell className="size-3" /> {item.open_alerts}
          </span>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <div className="col-span-2">
          <div className="flex items-baseline justify-between text-[11px] font-semibold uppercase tracking-wider text-ink-3">
            <span>Output</span>
            <span className="normal-case tracking-normal tabular-nums">{fmtPct(attain)}</span>
          </div>
          <div className="mt-0.5 flex items-baseline gap-1.5">
            <span className={`text-2xl font-semibold tabular-nums ${TONE_TEXT[attainmentTone(attain)]}`}>{fmtNum(item.output)}</span>
            <span className="text-sm text-ink-3 tabular-nums">/ {fmtNum(item.planned_output)}</span>
          </div>
          <ProgressBar value={attain ?? 0} tone={attainmentTone(attain)} className="mt-1" />
        </div>
        <Metric icon={<Timer className="size-3.5" />} label="Takt" value={fmtSec(line.takt_time_sec)} />
        <Metric
          icon={<Gauge className="size-3.5" />}
          label="Line pace"
          value={fmtSec(item.line_pace_sec)}
          tone={TONE_TEXT[paceTone]}
          title="Bottleneck operator content = effective line cycle time"
        />
        <Metric icon={<Scale className="size-3.5" />} label="Balance" value={fmtPct(item.balance_efficiency_pct)} tone={TONE_TEXT[balanceTone(item.balance_efficiency_pct)]} />
        <div className="col-span-1 sm:col-span-3">
          <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
            <Flame className="size-3.5" /> Bottleneck
          </div>
          <div className={`mt-0.5 truncate text-sm font-semibold ${item.bottleneck_station_name ? 'text-red-300' : 'text-ink-3'}`}>{item.bottleneck_station_name ?? '—'}</div>
        </div>
      </div>

      <div className="mt-4">
        <ProcessStrip stations={item.stations} live={states} />
      </div>
    </Link>
  );
}

function Metric({ icon, label, value, tone = 'text-ink', title }: { icon: ReactNode; label: string; value: string; tone?: string; title?: string }) {
  return (
    <div title={title} className="min-w-0">
      <div className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
        {icon}
        {label}
      </div>
      <div className={`mt-0.5 text-lg font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}
