import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, FileText, Loader2, RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import type { ReportRow } from '../api/types';
import { EmptyState, ErrorState, SkeletonPanel } from '../components/EmptyState';
import { Panel } from '../components/Panel';
import { usePageTitle } from '../context/PageTitleContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage } from '../lib/format';

/** Breakup reports of every machine (made automatically every few hours, or on request): a recorded video with every
 *  cycle split into segments. Grouped by machine, newest first. */
export default function ReportsPage() {
  usePageTitle('Reports');
  const { push } = useToast();
  const reports = usePolling(() => api.reports(), [], 20_000);
  const status = usePolling(() => api.reportStatus(), [], 5_000);
  const cams = usePolling(() => api.cameras(), [], 0);
  const stations = usePolling(() => api.stations(), [], 0);
  const [asked, setAsked] = useState<number[]>([]);

  if (!reports.data || !cams.data) {
    const err = reports.error ?? cams.error;
    return err ? <ErrorState error={err} onRetry={reports.reload} /> : <SkeletonPanel className="h-48" />;
  }
  const station = (id: number | null) => stations.data?.find((s) => s.id === id);
  const machines = cams.data
    .filter((c) => c.station_id)
    .sort((a, b) => (station(a.station_id)?.sequence ?? 99) - (station(b.station_id)?.sequence ?? 99));
  const covers = (r: ReportRow, id: number) => r.camera_id === id || (r.cameras ?? []).includes(id);
  const other = reports.data.filter((r) => !machines.some((c) => covers(r, c.id)));
  const st = status.data;

  const generate = async (cameraId: number) => {
    try {
      setAsked((a) => [...a, cameraId]);
      await api.generateReport(cameraId);
      push({ kind: 'success', title: 'Report is being made', message: 'Takes 1–3 minutes; it appears here when ready.' });
      status.reload();
    } catch (e) {
      push({ kind: 'critical', title: 'Could not start', message: errorMessage(e) });
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-edge bg-panel p-4 text-sm text-ink-3">
        Every machine gets a report automatically every {st?.every_hours ?? 2} hours while the line runs: about 5 minutes of video with
        every cycle split into its elements, where each cycle starts and ends, the abnormal cycles, and a variation (baratsuki) chart of
        consecutive cycles. Use <b className="text-ink-2">Generate now</b> for a fresh one.
      </div>
      {machines.map((c) => {
        const mine = reports.data!.filter((r) => covers(r, c.id));
        const mineJob = (j: number | string) => j === c.id || (st?.job_cams[String(j)] ?? []).includes(c.id);
        const running = st?.running != null && mineJob(st.running);
        const queued = !running && (st?.queue.some(mineJob) ?? false);
        const busy = running || queued;
        const last = st?.last[String(c.id)];
        const s = station(c.station_id);
        return (
          <Panel
            key={c.id}
            title={`${s?.sequence ?? '–'}. ${s?.name ?? c.name}`}
            subtitle={c.name}
            icon={<FileText className="size-4" />}
            actions={
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => generate(c.id)}>
                {busy ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                {running ? 'Making report…' : queued ? 'Waiting…' : 'Generate now'}
              </button>
            }
          >
            {last && !last.ok && asked.includes(c.id) && <p className="mb-2 text-sm text-amber-300">{last.message}</p>}
            {mine.length ? (
              <div className="space-y-2">
                <ReportCard r={mine[0]} big />
                {mine.slice(1).map((r) => (
                  <ReportCard key={r.name} r={r} />
                ))}
              </div>
            ) : (
              <p className="text-sm text-ink-3">
                {busy ? 'The first report is being made…' : last && !last.ok ? last.message : 'No report yet – it is made automatically once the machine has run a few minutes.'}
              </p>
            )}
          </Panel>
        );
      })}
      {!!other.length && (
        <Panel title="Other reports" icon={<FileText className="size-4" />}>
          <div className="space-y-2">
            {other.map((r) => (
              <ReportCard key={r.name} r={r} />
            ))}
          </div>
        </Panel>
      )}
      {!machines.length && !other.length && <EmptyState title="No machines yet" message="Add a line with its steps and cameras first." />}
    </div>
  );
}

function ReportCard({ r, big = false }: { r: ReportRow; big?: boolean }) {
  return (
    <Link
      to={`/reports/${encodeURIComponent(r.name)}`}
      className={`flex items-start gap-3 rounded-lg border border-edge px-3 hover:bg-panel-2 ${big ? 'bg-panel-2/40 py-3' : 'py-2'}`}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
          <span className="font-medium text-ink">
            {r.date} · {r.window}
          </span>
          {r.median_cycle != null && <span className="text-ink-2">normal cycle {r.median_cycle.toFixed(1)}s</span>}
          {r.cycles != null && <span className="text-ink-3">{r.cycles} cycles</span>}
          <span className="text-ink-3">{r.auto ? 'automatic' : 'detailed (checked by hand)'}</span>
        </div>
        {big && !!r.highlights.length && (
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-ink-2">
            {r.highlights.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
        )}
      </div>
      <ChevronRight className="mt-1 size-4 shrink-0 text-ink-3" />
    </Link>
  );
}
