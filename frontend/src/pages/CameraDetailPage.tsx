import { useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Camera as CameraIcon, CircleAlert, Cpu, Eye, EyeOff, Power, PowerOff, Puzzle, RotateCw, Save, ScanEye, Shapes, Trash, Video } from 'lucide-react';
import { api } from '../api/client';
import type { AnalyzerInfo, Camera, CameraConfig, CycleMethod, SimProfile, SourceType, Station, TrackerType, ZoneType } from '../api/types';
import { EmptyState, ErrorState, SkeletonPanel, StaleBanner } from '../components/EmptyState';
import { ConfirmDialog, Field, NumberInput, Toggle } from '../components/Form';
import { LiveStream } from '../components/LiveStream';
import { Panel } from '../components/Panel';
import { useLive } from '../context/LiveContext';
import { usePageTitle } from '../context/PageTitleContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage, fmtDateTime, fmtNum, fmtRelative } from '../lib/format';
import { CYCLE_METHOD_META, SOURCE_TYPE_META, TRACKER_META, ZONE_META, ZONE_TYPES } from '../lib/meta';

export default function CameraDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const valid = Number.isInteger(id) && id > 0;
  const cam = usePolling(() => api.camera(id), [id], valid ? 10_000 : 0);
  const camera = cam.data;
  const stations = usePolling(() => (camera ? api.stations(camera.line_id) : Promise.resolve<Station[]>([])), [camera?.line_id], 60_000);
  const lines = usePolling(() => api.lines(), [], 0);
  const lineName = camera ? lines.data?.find((l) => l.id === camera.line_id)?.name : undefined;

  usePageTitle(camera?.name ?? 'Camera', [
    { label: 'Cameras', to: '/cameras' },
    ...(camera && lineName ? [{ label: lineName, to: `/lines/${camera.line_id}` }] : []),
  ]);

  if (!valid) return <EmptyState title="Invalid camera id" action={<Link to="/cameras" className="btn">Back to cameras</Link>} />;
  if (!camera) {
    if (cam.loading)
      return (
        <div className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <SkeletonPanel className="h-96" />
            <SkeletonPanel className="h-96" />
          </div>
          <SkeletonPanel className="h-96" />
        </div>
      );
    return <ErrorState error={cam.error} onRetry={cam.reload} />;
  }

  return <CameraView camera={camera} setCamera={(c) => cam.setData(c)} error={cam.error} stations={stations.data ?? []} />;
}

function CameraView({ camera, setCamera, error, stations }: { camera: Camera; setCamera: (c: Camera) => void; error: unknown; stations: Station[] }) {
  const { push } = useToast();
  const { cameraStatus } = useLive();
  const [overlay, setOverlay] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const status = { ...camera.status, ...(cameraStatus.get(camera.id) ?? {}) };
  const station = stations.find((s) => s.id === camera.station_id);

  const run = async (key: string, fn: () => Promise<Camera>, ok: string) => {
    setBusy(key);
    try {
      const c = await fn();
      setCamera(c);
      push({ kind: 'success', title: ok });
    } catch (err) {
      push({ kind: 'critical', title: 'Action failed', message: errorMessage(err) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <StaleBanner error={error} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel
          title="Live view"
          subtitle={station ? `Step ${station.sequence} · ${station.name}` : 'No station assigned'}
          icon={<Video className="size-4" />}
          flush
          actions={
            <>
              <button type="button" className="btn btn-sm" onClick={() => setOverlay((v) => !v)} disabled={!camera.enabled}>
                {overlay ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />} Overlay {overlay ? 'on' : 'off'}
              </button>
              <EnableButton camera={camera} busy={busy} onToggle={(on) => void run('enable', () => api.updateCamera(camera.id, { enabled: on }), on ? 'Camera enabled' : 'Camera disabled')} />
            </>
          }
        >
          {camera.enabled ? (
            <LiveStream cameraId={camera.id} overlay={overlay} className="rounded-b-xl" />
          ) : (
            <EmptyState
              icon={<Power className="size-8" strokeWidth={1.5} />}
              title="Camera disabled"
              message="It is not connected or analysed. Click “Enable camera” to start it again."
            />
          )}
        </Panel>

        <Panel title="Status" icon={<CameraIcon className="size-4" />}>
          <div className="flex items-center gap-2">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${
                status.online && camera.enabled ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40' : 'bg-zinc-500/15 text-zinc-300 ring-zinc-500/40'
              }`}
            >
              <span className={`size-1.5 rounded-full ${status.online && camera.enabled ? 'animate-pulse-soft bg-emerald-400' : 'bg-zinc-500'}`} />
              {!camera.enabled ? 'Disabled' : status.online ? 'Online' : 'Offline'}
            </span>
            {status.needs_reference && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-300 ring-1 ring-amber-500/40">
                <CircleAlert className="size-3.5" /> Needs reference
              </span>
            )}
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
            <StatusItem label="FPS" value={fmtNum(status.fps, 1)} />
            <StatusItem label="Tracker" value={status.tracker || '—'} />
            <StatusItem label="Resolution" value={status.width && status.height ? `${status.width}×${status.height}` : '—'} />
            <StatusItem label="Last frame" value={<span title={fmtDateTime(status.last_frame_at)}>{fmtRelative(status.last_frame_at)}</span>} />
            <StatusItem label="Source" value={SOURCE_TYPE_META[camera.source_type]?.label ?? camera.source_type} />
            <StatusItem label="Reference image" value={camera.has_reference ? 'Captured' : 'None'} />
          </dl>
          {status.error && <div className="mt-3 rounded-md border border-rose-500/30 bg-rose-500/10 px-2.5 py-2 text-xs break-words text-rose-300">{status.error}</div>}

          <div className="mt-4 space-y-3 border-t border-edge pt-3">
            <div>
              <button
                type="button"
                className="btn w-full"
                disabled={busy !== null || !camera.enabled}
                onClick={() => void run('ref', () => api.captureReference(camera.id), 'Empty reference captured')}
              >
                <ScanEye className="size-4" /> {busy === 'ref' ? 'Capturing…' : 'Capture empty reference'}
              </button>
              <p className="hint">
                Take it while the part fixture / part zone is <b className="text-ink-2">empty</b> and nobody’s hands are in view. The part-presence method
                compares each frame with this image to detect when a part arrives and leaves.
              </p>
            </div>
            <button type="button" className="btn w-full" disabled={busy !== null} onClick={() => void run('restart', () => api.restartCamera(camera.id), 'Camera restarted')}>
              <RotateCw className={`size-4 ${busy === 'restart' ? 'animate-spin' : ''}`} /> {busy === 'restart' ? 'Restarting…' : 'Restart'}
            </button>
          </div>
        </Panel>
      </div>

      <ZonesSummary camera={camera} />

      <div className="grid gap-4 xl:grid-cols-2">
        <ConfigForm key={`cfg-${camera.id}`} camera={camera} onSaved={setCamera} />
        <div className="space-y-4">
          <AnalyzerPanel camera={camera} onSaved={setCamera} />
          <SourceForm key={`src-${camera.id}-${camera.enabled}`} camera={camera} stations={stations} onSaved={setCamera} />
        </div>
      </div>
    </div>
  );
}

/** Enable / disable the camera (disabled = not connected, not analysed). */
export function EnableButton({ camera, busy, onToggle }: { camera: Camera; busy: string | null; onToggle: (on: boolean) => void }) {
  return camera.enabled ? (
    <button type="button" className="btn btn-sm" disabled={busy !== null} onClick={() => onToggle(false)} title="Stop this camera (no connection, no analysis)">
      <PowerOff className="size-3.5" /> {busy === 'enable' ? 'Disabling…' : 'Disable camera'}
    </button>
  ) : (
    <button type="button" className="btn btn-sm btn-primary" disabled={busy !== null} onClick={() => onToggle(true)}>
      <Power className="size-3.5" /> {busy === 'enable' ? 'Enabling…' : 'Enable camera'}
    </button>
  );
}

function ZonesSummary({ camera }: { camera: Camera }) {
  const counts = new Map<ZoneType, number>();
  camera.zones.forEach((z) => counts.set(z.type, (counts.get(z.type) ?? 0) + 1));
  const hasPart = (counts.get('part_zone') ?? 0) + (counts.get('trigger_zone') ?? 0) + (counts.get('stroke_zone') ?? 0) > 0;
  return (
    <Panel
      title="Zones"
      subtitle="Where the part sits, the normal work area, bins and areas to ignore"
      icon={<Shapes className="size-4" />}
      actions={
        <Link to={`/cameras/${camera.id}/zones`} className="btn btn-sm btn-primary">
          <Shapes className="size-3.5" /> Open zone editor
        </Link>
      }
    >
      {camera.zones.length === 0 ? (
        <p className="text-sm text-ink-3">No zones drawn yet. Open the zone editor and draw at least the part zone (where the unit sits) for cycle detection.</p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {ZONE_TYPES.filter((t) => counts.get(t)).map((t) => (
            <span key={t} className="inline-flex items-center gap-1.5 rounded-full bg-panel-2 px-2.5 py-1 text-xs text-ink-2 ring-1 ring-edge">
              <span className="size-2 rounded-full" style={{ background: ZONE_META[t].color }} />
              {ZONE_META[t].label} × {counts.get(t)}
            </span>
          ))}
          {!hasPart && <span className="text-xs text-amber-300">No part / trigger zone – cycles can't be detected precisely.</span>}
          {hasPart && camera.status.needs_reference && (
            <span className="text-xs text-amber-300">Capture the empty reference (Status panel) so part presence can be detected.</span>
          )}
          {hasPart && !camera.has_reference && camera.config.cycle_method === 'part_presence' && camera.status.tracker === 'pose' && (
            <span className="text-xs text-ink-3">A cycle is counted each time the operator comes to the part zone (hands detected by pose).</span>
          )}
        </div>
      )}
    </Panel>
  );
}

function StatusItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className="truncate font-medium text-ink tabular-nums">{value}</dd>
    </div>
  );
}

/* ------------------------------------------------------------ config form */

const DEFAULT_SIM: SimProfile = { speed_factor: 1, far_reach_prob: 0.1, walk_prob: 0.05, extra_pick_prob: 0.1 };

function ConfigForm({ camera, onSaved }: { camera: Camera; onSaved: (c: Camera) => void }) {
  const { push } = useToast();
  const [cfg, setCfg] = useState<CameraConfig>(camera.config);
  const [saving, setSaving] = useState(false);
  const dirty = JSON.stringify(cfg) !== JSON.stringify(camera.config);
  const set = <K extends keyof CameraConfig>(k: K, v: CameraConfig[K]) => setCfg((c) => ({ ...c, [k]: v }));
  const setSim = <K extends keyof SimProfile>(k: K, v: SimProfile[K]) => setCfg((c) => ({ ...c, sim: { ...(c.sim ?? DEFAULT_SIM), [k]: v } }));

  // keep analyzers in sync (they are saved from their own panel)
  useEffect(() => {
    setCfg((c) => ({ ...c, analyzers: camera.config.analyzers }));
  }, [camera.config.analyzers]);

  const invalid = cfg.min_cycle_sec <= 0 || cfg.max_cycle_sec <= cfg.min_cycle_sec || cfg.presence_threshold < 0 || cfg.presence_threshold > 1 || cfg.process_fps <= 0;

  const save = async () => {
    setSaving(true);
    try {
      const { analyzers: _ignored, ...rest } = cfg;
      void _ignored;
      const c = await api.updateCamera(camera.id, { config: rest });
      onSaved(c);
      setCfg(c.config);
      push({ kind: 'success', title: 'Detection settings saved', message: 'The camera pipeline restarts with the new settings.' });
    } catch (err) {
      push({ kind: 'critical', title: 'Saving failed', message: errorMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel
      title="Detection settings"
      subtitle="How cycles are detected from this camera"
      icon={<Cpu className="size-4" />}
      actions={
        <>
          <button type="button" className="btn btn-sm" disabled={!dirty || saving} onClick={() => setCfg(camera.config)}>
            Reset
          </button>
          <button type="button" className="btn btn-sm btn-primary" disabled={!dirty || saving || invalid} onClick={() => void save()}>
            <Save className="size-3.5" /> {saving ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <span className="label">Cycle detection method</span>
          <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-1 2xl:grid-cols-3">
            {(Object.keys(CYCLE_METHOD_META) as CycleMethod[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => set('cycle_method', m)}
                className={`rounded-lg border p-2.5 text-left transition ${
                  cfg.cycle_method === m ? 'border-sky-500/70 bg-sky-500/10 ring-1 ring-sky-500/30' : 'border-edge bg-panel-2 hover:border-edge-2'
                }`}
              >
                <div className="text-sm font-semibold text-ink">{CYCLE_METHOD_META[m].label}</div>
                <div className="mt-0.5 text-[11px] leading-snug text-ink-3">{CYCLE_METHOD_META[m].description}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
          <Field label="Tracker" hint={TRACKER_META[cfg.tracker]}>
            <select className="input" value={cfg.tracker} onChange={(e) => set('tracker', e.target.value as TrackerType)}>
              {(Object.keys(TRACKER_META) as TrackerType[]).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Process FPS" hint="Frames analysed per second">
            <NumberInput value={cfg.process_fps} onChange={(v) => set('process_fps', v)} min={1} max={60} step={1} />
          </Field>
          <Field label="Idle timeout" hint="No activity → station idle">
            <NumberInput value={cfg.idle_timeout_sec} onChange={(v) => set('idle_timeout_sec', v)} min={1} suffix="s" />
          </Field>
          <Field label="Min cycle" hint="Shorter = ignored (noise)">
            <NumberInput value={cfg.min_cycle_sec} onChange={(v) => set('min_cycle_sec', v)} min={0} suffix="s" />
          </Field>
          <Field label="Max cycle" hint="Longer = stoppage, not a cycle">
            <NumberInput value={cfg.max_cycle_sec} onChange={(v) => set('max_cycle_sec', v)} min={1} suffix="s" />
          </Field>
          <Field label="Meters / frame width" hint="Calibration if pose scale unavailable">
            <NumberInput value={cfg.meters_per_frame_width} onChange={(v) => set('meters_per_frame_width', v)} min={0.1} step={0.1} suffix="m" />
          </Field>
          <Field label="Presence threshold" hint="0..1 share of part-zone pixels changed vs reference">
            <NumberInput value={cfg.presence_threshold} onChange={(v) => set('presence_threshold', v)} min={0} max={1} step={0.01} />
          </Field>
          <Field label="Presence debounce" hint="Part must be stable this long">
            <NumberInput value={cfg.presence_debounce_sec} onChange={(v) => set('presence_debounce_sec', v)} min={0} step={0.1} suffix="s" />
          </Field>
        </div>
        {invalid && <div className="text-xs text-rose-300">Check the values: max cycle must exceed min cycle, threshold must be 0..1, FPS &gt; 0.</div>}

        {(camera.source_type === 'rtsp' || camera.source_type === 'http') && (
          <Toggle
            checked={cfg.use_substream ?? true}
            onChange={(v) => set('use_substream', v)}
            label="Use the camera's low-resolution sub stream (recommended)"
            description="Analysis runs at 640 px anyway. The sub stream needs far less CPU and memory than the 4–8 MP main stream; the main stream is used automatically if no sub stream exists."
          />
        )}

        {camera.source_type === 'simulated' && (
          <div className="rounded-lg border border-dashed border-edge-2 p-3">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-3">Simulation profile (demo source)</div>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Field label="Speed factor" hint=">1 = slower operator">
                <NumberInput value={(cfg.sim ?? DEFAULT_SIM).speed_factor} onChange={(v) => setSim('speed_factor', v)} min={0.1} step={0.05} />
              </Field>
              <Field label="Far reach prob.">
                <NumberInput value={(cfg.sim ?? DEFAULT_SIM).far_reach_prob} onChange={(v) => setSim('far_reach_prob', v)} min={0} max={1} step={0.01} />
              </Field>
              <Field label="Walk prob.">
                <NumberInput value={(cfg.sim ?? DEFAULT_SIM).walk_prob} onChange={(v) => setSim('walk_prob', v)} min={0} max={1} step={0.01} />
              </Field>
              <Field label="Extra pick prob.">
                <NumberInput value={(cfg.sim ?? DEFAULT_SIM).extra_pick_prob} onChange={(v) => setSim('extra_pick_prob', v)} min={0} max={1} step={0.01} />
              </Field>
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

/* -------------------------------------------------------------- analyzers */

function AnalyzerPanel({ camera, onSaved }: { camera: Camera; onSaved: (c: Camera) => void }) {
  const { push } = useToast();
  const analyzers = usePolling<AnalyzerInfo[]>(() => api.analyzers(), [], 0);
  const [pending, setPending] = useState<string | null>(null);
  const enabled = new Set(camera.config.analyzers);

  const toggle = async (key: string, on: boolean) => {
    const next = on ? [...new Set([...camera.config.analyzers, key])] : camera.config.analyzers.filter((k) => k !== key);
    setPending(key);
    try {
      const c = await api.updateCamera(camera.id, { config: { analyzers: next } });
      onSaved(c);
    } catch (err) {
      push({ kind: 'critical', title: 'Could not change analyzer', message: errorMessage(err) });
    } finally {
      setPending(null);
    }
  };

  return (
    <Panel title="Analyzers" subtitle="What this camera analyses (saved immediately)" icon={<Puzzle className="size-4" />}>
      {!analyzers.data ? (
        analyzers.error ? (
          <ErrorState compact error={analyzers.error} onRetry={analyzers.reload} />
        ) : (
          <div className="h-24 animate-pulse rounded-lg bg-panel-3/60" />
        )
      ) : analyzers.data.length === 0 ? (
        <EmptyState compact title="No analyzers available" />
      ) : (
        <div className="space-y-3">
          {analyzers.data.map((an) => (
            <Toggle
              key={an.key}
              checked={an.available && enabled.has(an.key)}
              disabled={!an.available || pending !== null}
              onChange={(v) => void toggle(an.key, v)}
              label={an.name}
              description={an.description}
              badge={
                !an.available ? (
                  <span className="rounded-full bg-violet-500/15 px-1.5 py-px text-[10px] font-semibold text-violet-300 ring-1 ring-violet-500/30">Coming soon</span>
                ) : pending === an.key ? (
                  <span className="text-[10px] text-ink-3">saving…</span>
                ) : undefined
              }
            />
          ))}
        </div>
      )}
    </Panel>
  );
}

/* ----------------------------------------------------------------- source */

function SourceForm({ camera, stations, onSaved }: { camera: Camera; stations: Station[]; onSaved: (c: Camera) => void }) {
  const { push } = useToast();
  const navigate = useNavigate();
  const initial = { name: camera.name, source_type: camera.source_type, source: camera.source, station_id: camera.station_id };
  const [form, setForm] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);

  const save = async () => {
    setSaving(true);
    try {
      const c = await api.updateCamera(camera.id, form);
      onSaved(c);
      setForm({ name: c.name, source_type: c.source_type, source: c.source, station_id: c.station_id });
      push({ kind: 'success', title: 'Source settings saved' });
    } catch (err) {
      push({ kind: 'critical', title: 'Saving failed', message: errorMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    setDeleting(true);
    try {
      await api.deleteCamera(camera.id);
      push({ kind: 'success', title: `Camera “${camera.name}” deleted` });
      navigate('/cameras');
    } catch (err) {
      push({ kind: 'critical', title: 'Delete failed', message: errorMessage(err) });
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  return (
    <Panel
      title="Source settings"
      icon={<Video className="size-4" />}
      actions={
        <button type="button" className="btn btn-sm btn-primary" disabled={!dirty || saving || !form.name.trim() || !form.source.trim()} onClick={() => void save()}>
          <Save className="size-3.5" /> {saving ? 'Saving…' : 'Save'}
        </button>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Name">
          <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Station (process step)">
          <select className="input" value={form.station_id ?? ''} onChange={(e) => setForm({ ...form, station_id: e.target.value ? Number(e.target.value) : null })}>
            <option value="">— none —</option>
            {stations.map((s) => (
              <option key={s.id} value={s.id}>
                Step {s.sequence} · {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Source type">
          <select className="input" value={form.source_type} onChange={(e) => setForm({ ...form, source_type: e.target.value as SourceType })}>
            {(Object.keys(SOURCE_TYPE_META) as SourceType[]).filter((t) => t !== 'simulated').map((t) => (
              <option key={t} value={t}>
                {SOURCE_TYPE_META[t].label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Source" hint={form.source_type === 'usb' ? 'Device index, e.g. 0' : undefined}>
          <input className="input font-mono text-xs" value={form.source} placeholder={SOURCE_TYPE_META[form.source_type].placeholder} onChange={(e) => setForm({ ...form, source: e.target.value })} />
        </Field>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-edge pt-3">
        <span className="text-xs text-ink-3">Removes the camera and its zones. Recorded cycles are kept.</span>
        <button type="button" className="btn btn-sm btn-danger" onClick={() => setConfirmDelete(true)}>
          <Trash className="size-3.5" /> Delete camera
        </button>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        danger
        busy={deleting}
        title="Delete camera?"
        message={
          <>
            Delete <b className="text-ink">{camera.name}</b>? Its zones and configuration will be lost.
          </>
        }
        confirmLabel="Delete camera"
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void remove()}
      />
    </Panel>
  );
}
