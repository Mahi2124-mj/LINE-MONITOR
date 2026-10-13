import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  Crown,
  Flag,
  Info,
  ListVideo,
  Loader2,
  OctagonAlert,
  Pencil,
  Play,
  RefreshCw,
  Sparkles,
  TriangleAlert,
  Video,
  X,
} from 'lucide-react';
import { api } from '../api/client';
import type { AnalysisCycleDetail, AnalysisCycleRow, AnalysisIssue, AnalysisSummary } from '../api/types';
import { ElementTimeline, elementColor, elementName, standardSegments } from '../components/ElementTimeline';
import { EmptyState, ErrorState, SkeletonPanel } from '../components/EmptyState';
import { KpiTile } from '../components/KpiTile';
import { Panel } from '../components/Panel';
import { usePageTitle } from '../context/PageTitleContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage, fmtDelta, fmtSec } from '../lib/format';

const fmtClock = (ts: number) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
const fmtDay = (ts: number) => new Date(ts * 1000).toLocaleDateString(undefined, { day: '2-digit', month: 'short' });

export default function AnalysisPage() {
  const params = useParams();
  const cameraId = Number(params.cameraId);
  const summary = usePolling(() => api.analysisSummary(cameraId), [cameraId], 20_000);
  const [filter, setFilter] = useState<'all' | 'issues' | 'ok'>('all');
  const cycles = usePolling(() => api.analysisCycles(cameraId, filter), [cameraId, filter, summary.data?.model?.version], 20_000);
  const [openId, setOpenId] = useState<number | null>(null);
  const s = summary.data;

  usePageTitle(s?.station_name ? `Cycle analysis · ${s.station_name}` : 'Cycle analysis', [{ label: 'Cycle analysis', to: '/analysis' }]);

  if (!s) return summary.error ? <ErrorState error={summary.error} onRetry={summary.reload} /> : <SkeletonPanel className="h-96" />;

  const reload = () => {
    summary.reload();
    cycles.reload();
  };

  return (
    <div className="space-y-4">
      <HeaderPanel s={s} onChanged={reload} />
      {s.state !== 'ready' || !s.model ? (
        <NotReady s={s} onChanged={reload} />
      ) : (
        <>
          <Kpis s={s} />
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
            <Panel
              title="Cycles"
              subtitle="Click a cycle to watch it with its element breakup"
              icon={<ListVideo className="size-4" />}
              flush
              actions={
                <div className="flex rounded-lg bg-panel-3 p-0.5 text-xs">
                  {(['all', 'issues', 'ok'] as const).map((f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => setFilter(f)}
                      className={`rounded-md px-2.5 py-1 font-medium ${filter === f ? 'bg-panel text-ink shadow' : 'text-ink-3 hover:text-ink'}`}
                    >
                      {f === 'all' ? 'All' : f === 'issues' ? 'With issues' : 'OK'}
                    </button>
                  ))}
                </div>
              }
            >
              <CycleList rows={cycles.data} loading={cycles.loading} s={s} onOpen={setOpenId} />
            </Panel>
            <div className="space-y-4">
              <StandardPanel s={s} onOpen={setOpenId} onChanged={reload} />
              <ElementsPanel s={s} onChanged={reload} />
              <TopIssues s={s} />
            </div>
          </div>
        </>
      )}
      {openId !== null && s.model && (
        <CycleModal cycleId={openId} s={s} onClose={() => setOpenId(null)} onNavigate={setOpenId} onChanged={reload} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ header */

function HeaderPanel({ s, onChanged }: { s: AnalysisSummary; onChanged: () => void }) {
  const { push } = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key);
    try {
      await fn();
      push({ kind: 'success', title: ok });
      onChanged();
    } catch (e) {
      push({ kind: 'critical', title: 'Action failed', message: errorMessage(e) });
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge bg-panel px-4 py-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <Video className="size-4 text-ink-3" />
          {s.station_name ?? 'Station'} <span className="font-normal text-ink-3">· {s.camera_name}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
          <span className={`inline-flex items-center gap-1 ${s.recording ? 'text-rose-300' : ''}`}>
            <span className={`size-2 rounded-full ${s.recording ? 'animate-pulse-soft bg-rose-500' : 'bg-zinc-500'}`} />
            {s.recording ? `Recording @ ${s.process_fps ?? '?'} fps` : 'Not recording'}
          </span>
          <span>{s.camera_online ? 'Camera online' : 'Camera offline'}</span>
          {s.data && <span>{s.data.minutes.toFixed(0)} min recorded (since {fmtDay(s.data.first_ts)} {fmtClock(s.data.first_ts)})</span>}
          {s.model && <span>Elements learned {new Date(s.model.created_at).toLocaleString()} from {s.model.cycles_learned} cycles</span>}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {s.model && (
          <>
            <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={() => void run('analyze', () => api.analyzeNow(s.camera_id), 'Analysis updated')}>
              <RefreshCw className={`size-3.5 ${busy === 'analyze' ? 'animate-spin' : ''}`} /> Analyse new cycles
            </button>
            <button
              type="button"
              className="btn btn-sm"
              disabled={busy !== null}
              title="Learn the elements again from the last 60 minutes (e.g. after the method or camera changed)"
              onClick={() => void run('learn', () => api.learnElements(s.camera_id, 60), 'Elements learned again')}
            >
              <Sparkles className="size-3.5" /> {busy === 'learn' ? 'Learning…' : 'Re-learn elements'}
            </button>
          </>
        )}
        <button
          type="button"
          className={`btn btn-sm ${s.recording ? '' : 'btn-primary'}`}
          disabled={busy !== null}
          onClick={() => void run('rec', () => api.setRecording(s.camera_id, !s.recording, s.recording ? undefined : 6), s.recording ? 'Recording stopped' : 'Recording started')}
        >
          <span className={`size-2 rounded-full ${s.recording ? 'bg-zinc-400' : 'bg-rose-500'}`} /> {s.recording ? 'Stop recording' : 'Start recording'}
        </button>
      </div>
    </div>
  );
}

function NotReady({ s, onChanged }: { s: AnalysisSummary; onChanged: () => void }) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  const minutes = s.data?.minutes ?? 0;
  if (s.state === 'not_recording') {
    return (
      <EmptyState
        icon={<Video className="size-8" strokeWidth={1.5} />}
        title="Start recording this station"
        message="The operator's hand positions and the video are recorded. After about 10 minutes of normal work the elements of the cycle are found automatically – no process definition needed."
        action={
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.setRecording(s.camera_id, true, 6);
                onChanged();
              } catch (e) {
                push({ kind: 'critical', title: 'Could not start', message: errorMessage(e) });
              } finally {
                setBusy(false);
              }
            }}
          >
            <span className="size-2 rounded-full bg-rose-500" /> Start recording (6 fps)
          </button>
        }
      />
    );
  }
  const pct = Math.min(100, (minutes / s.learn_after_min) * 100);
  return (
    <div className="rounded-xl border border-edge bg-panel p-6 text-center">
      <Loader2 className="mx-auto size-7 animate-spin text-sky-400" />
      <h3 className="mt-3 text-base font-semibold text-ink">Recording – learning the elements soon</h3>
      <p className="mx-auto mt-1 max-w-xl text-sm text-ink-3">
        {minutes.toFixed(1)} of {s.learn_after_min} minutes recorded. The elements are learned automatically, the operator just has to work
        normally in front of the camera. {s.camera_online ? '' : 'The camera is offline right now – nothing is being recorded.'}
      </p>
      <div className="mx-auto mt-4 h-2 max-w-md overflow-hidden rounded-full bg-panel-3">
        <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <button
        type="button"
        className="btn btn-sm mt-4"
        disabled={busy || minutes < 4}
        onClick={async () => {
          setBusy(true);
          try {
            const r = await api.learnElements(s.camera_id, 60);
            push({ kind: 'success', title: `Learned ${r.elements} elements from ${r.cycles} cycles` });
            onChanged();
          } catch (e) {
            push({ kind: 'warning', title: 'Not yet', message: errorMessage(e) });
          } finally {
            setBusy(false);
          }
        }}
      >
        <Sparkles className="size-3.5" /> Learn now
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ KPIs */

function Kpis({ s }: { s: AnalysisSummary }) {
  const st = s.stats;
  const std = s.model!.standard;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-5">
      <KpiTile label="Cycles analysed" value={st?.cycles ?? 0} sub={st ? `${st.ok} OK · ${st.with_issues} with issues` : 'none yet'} />
      <KpiTile
        label="Cycles with issues"
        value={st ? `${Math.round((st.with_issues / Math.max(1, st.cycles)) * 100)}%` : '—'}
        tone={st && st.with_issues / Math.max(1, st.cycles) > 0.3 ? 'warn' : 'good'}
        progress={st ? (st.with_issues / Math.max(1, st.cycles)) * 100 : null}
        progressTone="warn"
      />
      <KpiTile
        label={std.source === 'master' ? 'Standard (master cycle)' : 'Standard (auto)'}
        value={fmtSec(std.total)}
        sub={std.source === 'master' ? 'from the cycle you marked as master' : `typical cycle${std.support ? ` · ${Math.round(std.support * 100)}% of cycles have all must-do steps` : ''}`}
        tone="info"
      />
      <KpiTile label="Average cycle" value={fmtSec(st?.avg_cycle)} sub={st ? `${fmtDelta((st.avg_cycle ?? 0) - std.total)} vs standard` : undefined} />
      <KpiTile label="Best cycle" value={fmtSec(st?.best_cycle)} tone="good" sub="fastest analysed cycle" />
    </div>
  );
}

/* ------------------------------------------------------------------ cycle list */

function CycleList({ rows, loading, s, onOpen }: { rows: AnalysisCycleRow[] | undefined; loading: boolean; s: AnalysisSummary; onOpen: (id: number) => void }) {
  const els = s.model!.elements;
  const scale = useMemo(() => Math.max(s.model!.standard.total * 1.6, ...(rows ?? []).map((r) => Math.min(r.cycle_sec, s.model!.standard.total * 3))), [rows, s.model]);
  if (!rows) return <div className="p-4">{loading ? <SkeletonPanel className="h-64" /> : null}</div>;
  if (!rows.length) return <p className="p-4 text-sm text-ink-3">No cycles in this filter yet.</p>;
  const std = s.model!.standard.total;
  return (
    <div className="max-h-[42rem] overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 z-10 bg-panel text-left text-[11px] uppercase tracking-wide text-ink-3">
          <tr className="border-b border-edge">
            <th className="px-3 py-2 font-medium">Time</th>
            <th className="px-2 py-2 text-right font-medium">Cycle</th>
            <th className="w-[45%] px-2 py-2 font-medium">Elements</th>
            <th className="px-3 py-2 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const d = r.cycle_sec - std;
            return (
              <tr key={r.id} onClick={() => onOpen(r.id)} className="cursor-pointer border-b border-edge/60 hover:bg-panel-2">
                <td className="whitespace-nowrap px-3 py-2 tabular-nums text-ink-2">
                  <div className="flex items-center gap-1.5">
                    <Play className="size-3 text-ink-3" />
                    {fmtClock(r.start_ts)}
                    {r.is_master && <Crown className="size-3.5 text-amber-300" aria-label="master cycle" />}
                  </div>
                </td>
                <td className="whitespace-nowrap px-2 py-2 text-right tabular-nums">
                  <div className="font-medium text-ink">{fmtSec(r.cycle_sec)}</div>
                  <div className={`text-[11px] ${d > std * 0.15 ? 'text-rose-300' : d < -1 ? 'text-emerald-300' : 'text-ink-3'}`}>{fmtDelta(d)}</div>
                </td>
                <td className="px-2 py-2">
                  <ElementTimeline segments={r.elements} elements={els} scale={scale} height="h-4" />
                </td>
                <td className="px-3 py-2">
                  {r.status === 'ok' ? (
                    <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
                      <CircleCheck className="size-3.5" /> OK
                    </span>
                  ) : (
                    <div className="min-w-0">
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-300">
                        <TriangleAlert className="size-3.5" /> {r.issue_count} issue{r.issue_count === 1 ? '' : 's'}
                      </span>
                      {r.top_issue && <div className="max-w-[16rem] truncate text-[11px] text-ink-3" title={r.top_issue}>{r.top_issue}</div>}
                    </div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ standard / elements / issues */

function StandardPanel({ s, onOpen, onChanged }: { s: AnalysisSummary; onOpen: (id: number) => void; onChanged: () => void }) {
  const { push } = useToast();
  const std = s.model!.standard;
  const els = s.model!.elements;
  return (
    <Panel
      title="Standard cycle"
      subtitle={
        std.source === 'master'
          ? 'Taken from the master cycle you chose'
          : 'Learned from the recordings: elements done in most cycles, usual order, median time of each'
      }
      icon={<Flag className="size-4" />}
      actions={
        std.source === 'master' ? (
          <div className="flex gap-2">
            {std.master_cycle_id && (
              <button type="button" className="btn btn-sm" onClick={() => onOpen(std.master_cycle_id!)}>
                <Play className="size-3.5" /> Watch master
              </button>
            )}
            <button
              type="button"
              className="btn btn-sm"
              onClick={async () => {
                try {
                  await api.clearMaster(s.camera_id);
                  push({ kind: 'success', title: 'Back to the automatic standard' });
                  onChanged();
                } catch (e) {
                  push({ kind: 'critical', title: 'Failed', message: errorMessage(e) });
                }
              }}
            >
              Use auto standard
            </button>
          </div>
        ) : undefined
      }
    >
      <ElementTimeline
        segments={standardSegments(std.seq, std.durations)}
        elements={els}
        scale={Math.max(std.total, std.durations.reduce((a, b) => a + b, 0))}
        height="h-7"
        showLabels
      />
      <ol className="mt-3 space-y-1 text-sm">
        {std.seq.map((id, i) => {
          const rate = std.rates?.[i] ?? 1;
          return (
            <li key={i} className="flex items-center gap-2">
              <span className="w-5 text-right text-xs tabular-nums text-ink-3">{i + 1}.</span>
              <span className="size-2.5 shrink-0 rounded-sm" style={{ background: elementColor(id, els) }} />
              <span className="min-w-0 flex-1 truncate text-ink-2">
                {elementName(id, els)}
                {rate < 0.995 && <span className="ml-1.5 text-xs text-ink-3">in {Math.round(rate * 100)}% of cycles</span>}
              </span>
              <span className="tabular-nums text-ink">{fmtSec(std.durations[i])}</span>
            </li>
          );
        })}
        <li className="flex items-center gap-2 border-t border-edge pt-1 font-semibold">
          <span className="flex-1 text-right text-xs text-ink-3">{std.source === 'master' ? 'Total' : 'Typical cycle (median)'}</span>
          <span className="tabular-nums text-ink">{fmtSec(std.total)}</span>
        </li>
      </ol>
      {!!std.optional?.length && (
        <p className="hint mt-2">
          Sometimes done (normal variation, not reported): {std.optional.map((id) => elementName(id, els)).join(', ')}
        </p>
      )}
      {std.source === 'auto' && (
        <p className="hint mt-2">Tip: open a cycle that was done the right way and click “Set as master” to compare every cycle with it.</p>
      )}
    </Panel>
  );
}

function ElementsPanel({ s, onChanged }: { s: AnalysisSummary; onChanged: () => void }) {
  const { push } = useToast();
  const els = s.model!.elements;
  const stats = new Map((s.stats?.elements ?? []).map((e) => [e.id, e]));
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const save = async (id: number) => {
    try {
      await api.renameElement(s.camera_id, id, draft);
      setEditing(null);
      onChanged();
    } catch (e) {
      push({ kind: 'critical', title: 'Rename failed', message: errorMessage(e) });
    }
  };
  return (
    <Panel title="Elements (found automatically)" subtitle="Where the operator's hands work. Give them your own names." icon={<Sparkles className="size-4" />} flush>
      <ul className="divide-y divide-edge">
        {els.map((e) => {
          const st = stats.get(e.id);
          return (
            <li key={e.id} className="flex gap-3 px-4 py-2.5">
              <img
                src={api.elementThumbUrl(s.camera_id, e.id, s.model!.version)}
                alt=""
                loading="lazy"
                className="h-14 w-20 shrink-0 rounded border-2 bg-black object-cover"
                style={{ borderColor: e.color }}
                onError={(ev) => ((ev.currentTarget as HTMLImageElement).style.visibility = 'hidden')}
              />
              <div className="min-w-0 flex-1">
                {editing === e.id ? (
                  <form
                    className="flex gap-1.5"
                    onSubmit={(ev) => {
                      ev.preventDefault();
                      void save(e.id);
                    }}
                  >
                    <input className="input py-1 text-sm" value={draft} onChange={(ev) => setDraft(ev.target.value)} autoFocus maxLength={60} />
                    <button type="submit" className="btn btn-sm btn-primary">
                      Save
                    </button>
                    <button type="button" className="btn btn-sm" onClick={() => setEditing(null)}>
                      <X className="size-3.5" />
                    </button>
                  </form>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <span className="size-2.5 shrink-0 rounded-sm" style={{ background: e.color }} />
                    <span className="truncate text-sm font-medium text-ink">{e.name}</span>
                    {s.model!.cycle_start === e.id && <span className="rounded bg-sky-500/15 px-1.5 text-[10px] font-semibold text-sky-300">cycle start</span>}
                    {!e.in_standard && <span className="rounded bg-amber-500/15 px-1.5 text-[10px] font-semibold text-amber-300">not in standard</span>}
                    <button
                      type="button"
                      className="ml-auto rounded p-1 text-ink-3 hover:bg-panel-3 hover:text-ink"
                      title="Rename"
                      onClick={() => {
                        setEditing(e.id);
                        setDraft(e.name);
                      }}
                    >
                      <Pencil className="size-3.5" />
                    </button>
                  </div>
                )}
                <div className="truncate text-[11px] text-ink-3">{e.desc}</div>
                {st && (
                  <div className="mt-0.5 text-[11px] tabular-nums text-ink-3">
                    median {fmtSec(st.median)} · p90 {fmtSec(st.p90)} · in {st.count} cycles
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <CycleStartPicker s={s} onChanged={onChanged} />
    </Panel>
  );
}

function CycleStartPicker({ s, onChanged }: { s: AnalysisSummary; onChanged: () => void }) {
  const { push } = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-edge px-4 py-2.5 text-xs text-ink-3">
      A cycle starts with
      <select
        className="input w-auto py-1 text-xs"
        value={s.model!.cycle_start}
        disabled={busy}
        onChange={async (e) => {
          setBusy(true);
          try {
            await api.setCycleStart(s.camera_id, Number(e.target.value));
            push({ kind: 'success', title: 'Cycles split again' });
            onChanged();
          } catch (err) {
            push({ kind: 'critical', title: 'Failed', message: errorMessage(err) });
          } finally {
            setBusy(false);
          }
        }}
      >
        {s.model!.elements.map((e) => (
          <option key={e.id} value={e.id}>
            {e.name}
          </option>
        ))}
      </select>
      {busy && <Loader2 className="size-3.5 animate-spin" />}
      <span>(found automatically – change it if cycles are split at the wrong place)</span>
    </div>
  );
}

function TopIssues({ s }: { s: AnalysisSummary }) {
  const top = s.stats?.top_issues ?? [];
  return (
    <Panel title="Most frequent issues" icon={<CircleAlert className="size-4" />}>
      {top.length === 0 ? (
        <p className="text-sm text-ink-3">No issues found in the analysed cycles.</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {top.map((t, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-ink-2">{t.text}</span>
              <span className="rounded-full bg-amber-500/15 px-2 text-xs font-semibold tabular-nums text-amber-300">
                {t.count}× · {Math.round((t.count / Math.max(1, s.stats!.cycles)) * 100)}%
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ cycle detail */

const SEV_ICON = { critical: OctagonAlert, warning: TriangleAlert, info: Info } as const;
const SEV_CLS = { critical: 'text-red-300 bg-red-500/10 border-red-500/30', warning: 'text-amber-200 bg-amber-500/10 border-amber-500/30', info: 'text-sky-200 bg-sky-500/10 border-sky-500/30' } as const;

function CycleModal({
  cycleId,
  s,
  onClose,
  onNavigate,
  onChanged,
}: {
  cycleId: number;
  s: AnalysisSummary;
  onClose: () => void;
  onNavigate: (id: number) => void;
  onChanged: () => void;
}) {
  const { push } = useToast();
  const [d, setD] = useState<AnalysisCycleDetail | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [t, setT] = useState(0);
  const [videoState, setVideoState] = useState<'loading' | 'ready' | 'error'>('loading');
  const videoRef = useRef<HTMLVideoElement>(null);
  const els = s.model!.elements;

  useEffect(() => {
    let cancelled = false;
    setD(null);
    setErr(null);
    setT(0);
    setVideoState('loading');
    api.analysisCycle(cycleId).then((x) => !cancelled && setD(x)).catch((e) => !cancelled && setErr(e));
    return () => {
      cancelled = true;
    };
  }, [cycleId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowRight' && d?.next_id) onNavigate(d.next_id);
      if (e.key === 'ArrowLeft' && d?.prev_id) onNavigate(d.prev_id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [d, onClose, onNavigate]);

  const seek = (sec: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = sec;
      void videoRef.current.play().catch(() => undefined);
    }
  };

  const std = d?.standard ?? s.model!.standard;
  const scale = d ? Math.max(d.cycle_sec, std.total) : std.total;
  const current = d?.elements.find((e) => t >= e.start && t < e.start + e.dur);

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-black/70 p-3 backdrop-blur-sm" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="flex max-h-[95vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-edge-2 bg-panel shadow-2xl">
        <div className="flex items-center gap-3 border-b border-edge px-4 py-2.5">
          <button type="button" className="btn btn-sm" disabled={!d?.prev_id} onClick={() => d?.prev_id && onNavigate(d.prev_id)} title="Previous cycle (←)">
            <ChevronLeft className="size-4" />
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              Cycle {d ? `${fmtDay(d.start_ts)} ${fmtClock(d.start_ts)}` : '…'}
              {d?.is_master && (
                <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 text-[11px] text-amber-300">
                  <Crown className="size-3" /> master
                </span>
              )}
            </div>
            {d && (
              <div className="text-xs text-ink-3">
                {fmtSec(d.cycle_sec)} · standard {fmtSec(std.total)} ({fmtDelta(d.cycle_sec - std.total)}) · {d.elements.length} elements
              </div>
            )}
          </div>
          {d && !d.is_master && (
            <button
              type="button"
              className="btn btn-sm"
              title="Use this cycle as the reference (master) every other cycle is compared with"
              onClick={async () => {
                try {
                  await api.setMaster(d.id);
                  push({ kind: 'success', title: 'Master cycle set', message: 'All cycles are now compared with this one.' });
                  onChanged();
                  setD(await api.analysisCycle(d.id));
                } catch (e) {
                  push({ kind: 'critical', title: 'Failed', message: errorMessage(e) });
                }
              }}
            >
              <Crown className="size-3.5" /> Set as master
            </button>
          )}
          <button type="button" className="btn btn-sm" disabled={!d?.next_id} onClick={() => d?.next_id && onNavigate(d.next_id)} title="Next cycle (→)">
            <ChevronRight className="size-4" />
          </button>
          <button type="button" className="rounded p-1.5 text-ink-3 hover:bg-panel-3 hover:text-ink" onClick={onClose} aria-label="Close">
            <X className="size-4" />
          </button>
        </div>

        {err ? (
          <ErrorState error={err} />
        ) : !d ? (
          <div className="grid h-96 place-items-center">
            <Loader2 className="size-6 animate-spin text-ink-3" />
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 gap-4 overflow-y-auto p-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-3">
              <div className="relative aspect-video overflow-hidden rounded-lg bg-black">
                <video
                  key={d.id}
                  ref={videoRef}
                  src={api.cycleClipUrl(d.id)}
                  className="h-full w-full object-contain"
                  controls
                  autoPlay
                  muted
                  playsInline
                  onLoadedData={() => setVideoState('ready')}
                  onError={() => setVideoState('error')}
                  onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
                />
                {videoState !== 'ready' && (
                  <div className="absolute inset-0 grid place-items-center bg-black/70 text-center text-sm text-ink-3">
                    {videoState === 'loading' ? (
                      <span className="flex items-center gap-2">
                        <Loader2 className="size-4 animate-spin" /> Preparing the video of this cycle…
                      </span>
                    ) : (
                      <span>The recording of this cycle is no longer available (recordings are kept 24 h).</span>
                    )}
                  </div>
                )}
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-[11px] text-ink-3">
                  <span>This cycle {current ? `· now: ${current.name}` : ''}</span>
                  <span className="tabular-nums">{fmtSec(t)}</span>
                </div>
                <ElementTimeline segments={d.elements} elements={els} scale={scale} height="h-8" playhead={t} onSeek={seek} showLabels />
                <div className="text-[11px] text-ink-3">{std.source === 'master' ? 'Master cycle' : 'Standard'}</div>
                <ElementTimeline segments={standardSegments(std.seq, std.durations)} elements={els} scale={scale} height="h-4" />
              </div>
            </div>

            <div className="min-w-0 space-y-3">
              <div>
                <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">Issues</h4>
                {d.issues.length === 0 ? (
                  <div className="flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
                    <CircleCheck className="size-4" /> Done like the standard – no issues.
                  </div>
                ) : (
                  <ul className="space-y-1.5">
                    {d.issues.map((i: AnalysisIssue, k) => {
                      const Icon = SEV_ICON[i.severity];
                      return (
                        <li key={k} className={`flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-sm ${SEV_CLS[i.severity]}`}>
                          <Icon className="mt-0.5 size-4 shrink-0" />
                          <span>{i.text}</span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
              <div>
                <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">Element breakup</h4>
                <table className="w-full text-sm">
                  <thead className="text-left text-[11px] text-ink-3">
                    <tr>
                      <th className="py-1 font-medium">Element</th>
                      <th className="py-1 text-right font-medium">Start</th>
                      <th className="py-1 text-right font-medium">Time</th>
                      <th className="py-1 text-right font-medium">Std</th>
                      <th className="py-1 text-right font-medium">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.elements.map((e, k) => {
                      const active = current === e;
                      return (
                        <tr
                          key={k}
                          onClick={() => seek(e.start)}
                          className={`cursor-pointer border-t border-edge/60 ${active ? 'bg-sky-500/10' : 'hover:bg-panel-2'}`}
                        >
                          <td className="py-1.5 pr-2">
                            <div className="flex items-center gap-1.5">
                              <span className="size-2.5 shrink-0 rounded-sm" style={{ background: elementColor(e.id, els) }} />
                              <span className="truncate text-ink-2">{e.name}</span>
                            </div>
                          </td>
                          <td className="py-1.5 text-right tabular-nums text-ink-3">{fmtSec(e.start)}</td>
                          <td className="py-1.5 text-right tabular-nums font-medium text-ink">{fmtSec(e.dur)}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-3">{e.std != null ? fmtSec(e.std) : '—'}</td>
                          <td
                            className={`py-1.5 text-right tabular-nums ${
                              e.delta == null ? 'text-ink-3' : e.delta > Math.max(1, 0.3 * (e.std ?? 0)) ? 'text-rose-300' : e.delta < -1 ? 'text-emerald-300' : 'text-ink-3'
                            }`}
                          >
                            {e.delta != null ? fmtDelta(e.delta) : e.id === -2 ? 'away' : e.cont ? 'cont.' : 'extra'}
                          </td>
                        </tr>
                      );
                    })}
                    <tr className="border-t border-edge font-semibold">
                      <td className="py-1.5 text-ink-2">Total</td>
                      <td />
                      <td className="py-1.5 text-right tabular-nums text-ink">{fmtSec(d.cycle_sec)}</td>
                      <td className="py-1.5 text-right tabular-nums text-ink-3">{fmtSec(std.total)}</td>
                      <td className={`py-1.5 text-right tabular-nums ${d.cycle_sec - std.total > 1 ? 'text-rose-300' : 'text-emerald-300'}`}>
                        {fmtDelta(d.cycle_sec - std.total)}
                      </td>
                    </tr>
                  </tbody>
                </table>
                <p className="hint mt-1">Click an element (or the bar) to jump the video to it.</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
