import { Link } from 'react-router-dom';
import { ChevronRight, ListVideo, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import { EmptyState, ErrorState, SkeletonPanel } from '../components/EmptyState';
import { Panel } from '../components/Panel';
import { usePageTitle } from '../context/PageTitleContext';
import { usePolling } from '../hooks/usePolling';

/** Every camera, with its cycle-analysis status. Open one to see the element breakup of its cycles. */
export default function AnalysisIndexPage() {
  usePageTitle('Cycle analysis');
  const cams = usePolling(() => api.cameras(), [], 30_000);
  const lines = usePolling(() => api.lines(), [], 0);
  const stations = usePolling(() => api.stations(), [], 0);
  const status = usePolling(() => api.analysisCameras(), [], 15_000);

  if (!cams.data) return cams.error ? <ErrorState error={cams.error} onRetry={cams.reload} /> : <SkeletonPanel className="h-64" />;
  if (!cams.data.length)
    return <EmptyState title="No cameras yet" message="Add a line with its steps and cameras first." action={<Link to="/setup" className="btn btn-primary">Lines & cameras</Link>} />;

  const st = new Map((status.data ?? []).map((s) => [s.camera_id, s]));
  const stationName = (id: number | null) => stations.data?.find((s) => s.id === id);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-edge bg-panel p-4 text-sm text-ink-2">
        <div className="flex items-center gap-2 font-semibold text-ink">
          <Sparkles className="size-4 text-sky-400" /> Element breakup of every cycle
        </div>
        <p className="mt-1 text-ink-3">
          Start recording a station: the system learns its work elements by itself (where the operator's hands work), splits every cycle into
          elements with their times, compares each cycle with the standard / master cycle and lists what went wrong. Click a cycle to watch it.
        </p>
      </div>
      {(lines.data ?? []).map((line) => {
        const lc = cams.data!.filter((c) => c.line_id === line.id);
        if (!lc.length) return null;
        return (
          <Panel key={line.id} title={line.name} icon={<ListVideo className="size-4" />} flush>
            <ul className="divide-y divide-edge">
              {lc
                .sort((a, b) => (stationName(a.station_id)?.sequence ?? 99) - (stationName(b.station_id)?.sequence ?? 99))
                .map((c) => {
                  const s = st.get(c.id);
                  const step = stationName(c.station_id);
                  return (
                    <li key={c.id}>
                      <Link to={`/analysis/${c.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-panel-2">
                        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-panel-3 text-xs font-semibold text-ink-2">{step?.sequence ?? '–'}</span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-ink">{step?.name ?? c.name}</div>
                          <div className="truncate text-xs text-ink-3">{c.name}</div>
                        </div>
                        {s?.has_model ? (
                          <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-300">Elements learned</span>
                        ) : s?.recording ? (
                          <span className="rounded-full bg-sky-500/15 px-2 py-0.5 text-xs font-medium text-sky-300">Learning…</span>
                        ) : (
                          <span className="text-xs text-ink-3">Not recorded</span>
                        )}
                        {s?.recording && (
                          <span className="inline-flex items-center gap-1 text-xs text-rose-300">
                            <span className="size-2 animate-pulse-soft rounded-full bg-rose-500" /> REC
                          </span>
                        )}
                        <ChevronRight className="size-4 text-ink-3" />
                      </Link>
                    </li>
                  );
                })}
            </ul>
          </Panel>
        );
      })}
    </div>
  );
}
