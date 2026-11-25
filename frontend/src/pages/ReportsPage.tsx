import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ChevronRight, Factory, FileText, ListOrdered, Loader2, RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import type { Camera, Line, ReportRow, ReportStatus, Station } from '../api/types';
import { EmptyState, ErrorState, SkeletonPanel } from '../components/EmptyState';
import { Panel } from '../components/Panel';
import { usePageTitle } from '../context/PageTitleContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage } from '../lib/format';

const OLDER_SHOWN = 3;

/** Breakup reports, line by line and process step by process step (in production order). Every step's machine gets a
 *  report automatically every few hours; a report that covers two machines (e.g. Rail Assy #01 + #02) shows under both. */
export default function ReportsPage() {
  usePageTitle('Reports');
  const { push } = useToast();
  const [params, setParams] = useSearchParams();
  const reports = usePolling(() => api.reports(), [], 20_000);
  const status = usePolling(() => api.reportStatus(), [], 5_000);
  const lines = usePolling(() => api.lines(), [], 0);
  const stations = usePolling(() => api.stations(), [], 0);
  const cams = usePolling(() => api.cameras(), [], 0);
  const [asked, setAsked] = useState<number[]>([]);

  if (!reports.data || !lines.data || !stations.data || !cams.data) {
    const err = reports.error ?? lines.error ?? stations.error ?? cams.error;
    return err ? <ErrorState error={err} onRetry={reports.reload} /> : <SkeletonPanel className="h-48" />;
  }
  const allReports = reports.data;
  const camsOf = (s: Station) => cams.data!.filter((c) => c.station_id === s.id);
  // a report belongs to the step it was made for, and to further steps only through its extra cameras (Rail Assy #01 + #02);
  // two steps can share one camera (YRA Mechanical Movement / Final Inspection), so the main camera alone does not decide
  const knownStation = new Set(stations.data.map((s) => s.id));
  const forStation = (s: Station) => {
    const ids = new Set(camsOf(s).map((c) => c.id));
    return allReports.filter((r) =>
      r.station_id != null && knownStation.has(r.station_id)
        ? r.station_id === s.id || (r.cameras ?? []).some((id) => id !== r.camera_id && ids.has(id))
        : ids.has(r.camera_id ?? -1) || (r.cameras ?? []).some((id) => ids.has(id)),
    );
  };
  const stepsOf = (l: Line) => stations.data!.filter((s) => s.line_id === l.id).sort((a, b) => a.sequence - b.sequence);
  const other = allReports.filter((r) => !stations.data!.some((s) => forStation(s).includes(r)));

  const chosen = params.get('line');
  const line =
    lines.data.find((l) => String(l.id) === chosen) ?? (chosen === 'other' ? null : lines.data.find((l) => l.is_active) ?? lines.data[0] ?? null);
  const pick = (id: number | 'other') => setParams({ line: String(id) }, { replace: true });

  const generate = async (cameraId: number) => {
    try {
      setAsked((a) => [...a, cameraId]);
      await api.generateReport(cameraId);
      push({ kind: 'success', title: 'Report is being made', message: 'Takes 1–5 minutes; it appears here when ready.' });
      status.reload();
    } catch (e) {
      push({ kind: 'critical', title: 'Could not start', message: errorMessage(e) });
    }
  };

  if (!lines.data.length && !other.length) return <EmptyState title="No lines yet" message="Add a line with its steps and cameras first." />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Lines">
        {lines.data.map((l) => {
          const n = stepsOf(l).reduce((k, s) => k + forStation(s).length, 0);
          const on = line?.id === l.id;
          return (
            <button
              key={l.id}
              type="button"
              role="tab"
              aria-selected={on}
              onClick={() => pick(l.id)}
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition ${
                on ? 'border-sky-400/60 bg-sky-500/10 text-ink' : 'border-edge bg-panel text-ink-2 hover:bg-panel-2'
              } ${l.is_active ? '' : 'opacity-70'}`}
            >
              <Factory className="size-4" />
              <span className="font-medium">{l.name}</span>
              <span className="text-xs text-ink-3">
                {stepsOf(l).length} steps · {n} reports
              </span>
              {!l.is_active && <span className="rounded bg-zinc-700/50 px-1.5 py-0.5 text-[10px] font-semibold text-zinc-300">DISABLED</span>}
            </button>
          );
        })}
        {!!other.length && (
          <button
            type="button"
            role="tab"
            aria-selected={chosen === 'other'}
            onClick={() => pick('other')}
            className={`rounded-lg border px-3 py-2 text-sm transition ${chosen === 'other' ? 'border-sky-400/60 bg-sky-500/10 text-ink' : 'border-edge bg-panel text-ink-2 hover:bg-panel-2'}`}
          >
            Other reports <span className="text-xs text-ink-3">{other.length}</span>
          </button>
        )}
      </div>

      {chosen === 'other' ? (
        <Panel title="Other reports" subtitle="Not linked to a step of any line" icon={<FileText className="size-4" />}>
          <div className="space-y-2">
            {other.map((r) => (
              <ReportCard key={r.name} r={r} />
            ))}
          </div>
        </Panel>
      ) : line ? (
        <LineReports
          line={line}
          steps={stepsOf(line)}
          camsOf={camsOf}
          forStation={forStation}
          status={status.data}
          asked={asked}
          onGenerate={generate}
        />
      ) : null}
    </div>
  );
}

function LineReports({
  line,
  steps,
  camsOf,
  forStation,
  status,
  asked,
  onGenerate,
}: {
  line: Line;
  steps: Station[];
  camsOf: (s: Station) => Camera[];
  forStation: (s: Station) => ReportRow[];
  status: ReportStatus | undefined;
  asked: number[];
  onGenerate: (cameraId: number) => void;
}) {
  if (!steps.length) return <EmptyState title="No steps on this line" message="Add the line's process steps and cameras on Lines & cameras." />;
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-3">
        {line.is_active
          ? `Each step's machine gets a report automatically every ${status?.every_hours ?? 2} hours while the line runs: about 5 minutes of video with every cycle split into its elements, the abnormal cycles, and a variation (baratsuki) chart. Use Generate now for a fresh one.`
          : 'This line is disabled: no new reports are made. Earlier reports stay available below.'}
      </p>

      <Panel title={`${line.name} – process steps`} subtitle="Latest report of every step, in production order" icon={<ListOrdered className="size-4" />} flush>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-xs text-ink-3">
                <th className="px-4 py-2 font-medium">Step</th>
                <th className="px-3 py-2 font-medium">Machine / camera</th>
                <th className="px-3 py-2 text-right font-medium">Normal cycle</th>
                <th className="px-3 py-2 text-right font-medium">Cycles</th>
                <th className="px-3 py-2 font-medium">Latest report</th>
              </tr>
            </thead>
            <tbody>
              {steps.map((s) => {
                const r = forStation(s)[0];
                return (
                  <tr key={s.id} className="border-b border-edge last:border-0 hover:bg-panel-2">
                    <td className="px-4 py-2">
                      <a href={`#step-${s.id}`} className="font-medium text-ink hover:text-sky-300">
                        {s.sequence}. {s.name}
                      </a>
                    </td>
                    <td className="px-3 py-2 text-ink-3">{camsOf(s).map((c) => c.name).join(', ') || 'no camera'}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink">{r?.median_cycle != null ? `${r.median_cycle.toFixed(1)}s` : '–'}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink-2">{r?.cycles ?? '–'}</td>
                    <td className="px-3 py-2">
                      {r ? (
                        <Link to={`/reports/${encodeURIComponent(r.name)}`} className="text-sky-300 hover:underline">
                          {r.date} · {r.window}
                        </Link>
                      ) : (
                        <span className="text-ink-3">none yet</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {steps.map((s) => (
        <StepReports key={s.id} step={s} cams={camsOf(s)} reports={forStation(s)} status={status} asked={asked} onGenerate={onGenerate} lineActive={line.is_active} />
      ))}
    </div>
  );
}

function StepReports({
  step,
  cams,
  reports,
  status,
  asked,
  onGenerate,
  lineActive,
}: {
  step: Station;
  cams: Camera[];
  reports: ReportRow[];
  status: ReportStatus | undefined;
  asked: number[];
  onGenerate: (cameraId: number) => void;
  lineActive: boolean;
}) {
  const [all, setAll] = useState(false);
  const ids = cams.map((c) => c.id);
  const mineJob = (j: number | string) => {
    const forStations = status?.job_stations?.[String(j)];
    if (forStations != null) return forStations.includes(step.id);
    return ids.includes(Number(j)) || (status?.job_cams[String(j)] ?? []).some((c) => ids.includes(c));
  };
  const running = status?.running != null && mineJob(status.running);
  const queued = !running && (status?.queue.some(mineJob) ?? false);
  const busy = running || queued;
  const last = ids.map((id) => status?.last[String(id)]).find(Boolean);
  const older = reports.slice(1);
  const shown = all ? older : older.slice(0, OLDER_SHOWN);
  const cam = cams[0];

  return (
    <div id={`step-${step.id}`} className="scroll-mt-4">
      <Panel
        title={`${step.sequence}. ${step.name}`}
        subtitle={cams.length ? cams.map((c) => c.name).join(' · ') : 'No camera on this step'}
        icon={<FileText className="size-4" />}
        actions={
          cam && lineActive ? (
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => onGenerate(cam.id)}>
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
              {running ? 'Making report…' : queued ? 'Waiting…' : 'Generate now'}
            </button>
          ) : undefined
        }
      >
        {last && !last.ok && cam && asked.includes(cam.id) && <p className="mb-2 text-sm text-amber-300">{last.message}</p>}
        {reports.length ? (
          <div className="space-y-2">
            <ReportCard r={reports[0]} big />
            {shown.map((r) => (
              <ReportCard key={r.name} r={r} />
            ))}
            {older.length > OLDER_SHOWN && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAll((v) => !v)}>
                {all ? 'Show fewer' : `Show all ${older.length} older reports`}
              </button>
            )}
          </div>
        ) : (
          <p className="text-sm text-ink-3">
            {!cam
              ? 'Add a camera to this step to get reports.'
              : busy
                ? 'The first report is being made…'
                : last && !last.ok
                  ? last.message
                  : 'No report yet – it is made automatically once the machine has run a few minutes.'}
          </p>
        )}
      </Panel>
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
