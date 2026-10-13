import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, Cctv, Factory, ListOrdered, Pencil, Plus, Save, Shapes, Trash, TriangleAlert } from 'lucide-react';
import { api } from '../api/client';
import type { Camera, CameraInput, Line, LineInput, SourceType, Station, StationInput } from '../api/types';
import { EmptyState, ErrorState, Skeleton } from '../components/EmptyState';
import { ConfirmDialog, Field, Modal, NumberInput, TagInput, Toggle } from '../components/Form';
import { Panel } from '../components/Panel';
import { Chip } from '../components/StateBadge';
import { usePageTitle } from '../context/PageTitleContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage, fmtSec } from '../lib/format';
import { SOURCE_TYPE_META } from '../lib/meta';

const EMPTY_LINE: LineInput = { name: '', code: '', description: '', takt_time_sec: 60, shift_start: '08:00', shift_end: '16:00', is_active: true };

export default function SetupPage() {
  usePageTitle('Advanced setup', [{ label: 'Lines & cameras', to: '/setup' }]);
  const [params, setParams] = useSearchParams();
  const selected = params.get('line') === 'new' ? 'new' : params.get('line') ? Number(params.get('line')) : null;
  const lines = usePolling(() => api.lines(), [], 0);

  const select = (v: number | 'new' | null) => setParams(v === null ? {} : { line: String(v) }, { replace: true });

  // default: first line
  useEffect(() => {
    if (selected === null && lines.data && lines.data.length) select(lines.data[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lines.data, selected]);

  const line = typeof selected === 'number' ? lines.data?.find((l) => l.id === selected) : undefined;

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)]">
        <Panel
          title="Lines"
          icon={<Factory className="size-4" />}
          flush
          actions={
            <button type="button" className="btn btn-sm btn-primary" onClick={() => select('new')}>
              <Plus className="size-3.5" /> New line
            </button>
          }
          className="self-start"
        >
          {!lines.data ? (
            lines.loading ? (
              <div className="space-y-2 p-3">
                {Array.from({ length: 3 }, (_, i) => (
                  <Skeleton key={i} className="h-12" />
                ))}
              </div>
            ) : (
              <ErrorState compact error={lines.error} onRetry={lines.reload} />
            )
          ) : lines.data.length === 0 ? (
            <EmptyState compact title="No lines yet" message="Create your first production line." />
          ) : (
            <ul className="divide-y divide-edge">
              {lines.data.map((l) => (
                <li key={l.id}>
                  <button
                    type="button"
                    onClick={() => select(l.id)}
                    className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition ${selected === l.id ? 'bg-panel-3' : 'hover:bg-panel-2'}`}
                  >
                    <span className={`h-8 w-1 rounded-full ${selected === l.id ? 'bg-sky-500' : 'bg-transparent'}`} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-ink">{l.name}</span>
                        <span className="text-[10px] font-bold text-ink-3">{l.code}</span>
                      </span>
                      <span className="block text-[11px] text-ink-3 tabular-nums">
                        {l.station_count} steps · {l.camera_count} cameras · takt {fmtSec(l.takt_time_sec)}
                        {!l.is_active && ' · inactive'}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="min-w-0 space-y-4">
          {selected === 'new' ? (
            <LineForm
              key="new"
              initial={EMPTY_LINE}
              onSaved={(l) => {
                lines.reload();
                select(l.id);
              }}
            />
          ) : line ? (
            <>
              <LineForm
                key={line.id}
                line={line}
                initial={{
                  name: line.name,
                  code: line.code,
                  description: line.description,
                  takt_time_sec: line.takt_time_sec,
                  shift_start: line.shift_start,
                  shift_end: line.shift_end,
                  is_active: line.is_active,
                }}
                onSaved={() => lines.reload()}
                onDeleted={() => {
                  lines.reload();
                  select(null);
                }}
              />
              <StationsEditor line={line} onChanged={lines.reload} />
              <CamerasEditor line={line} onChanged={lines.reload} />
            </>
          ) : lines.data && lines.data.length > 0 && typeof selected === 'number' ? (
            <EmptyState title="Line not found" />
          ) : lines.data && lines.data.length === 0 ? (
            <Panel>
              <EmptyState
                icon={<Factory className="size-9" strokeWidth={1.5} />}
                title="Set up your first line"
                message="A line has an ordered list of process steps (stations). Each step can have one or more cameras."
                action={
                  <button type="button" className="btn btn-primary" onClick={() => select('new')}>
                    <Plus className="size-4" /> New line
                  </button>
                }
              />
            </Panel>
          ) : null}
        </div>
      </div>

      <DangerZone />
    </div>
  );
}

/* ------------------------------------------------------------------ line */

function LineForm({ line, initial, onSaved, onDeleted }: { line?: Line; initial: LineInput; onSaved: (l: Line) => void; onDeleted?: () => void }) {
  const { push } = useToast();
  const [form, setForm] = useState<LineInput>(initial);
  const [saving, setSaving] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  const valid = form.name.trim() !== '' && form.code.trim() !== '' && form.takt_time_sec > 0;
  const set = <K extends keyof LineInput>(k: K, v: LineInput[K]) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    setSaving(true);
    try {
      const l = line ? await api.updateLine(line.id, form) : await api.createLine(form);
      push({ kind: 'success', title: line ? 'Line saved' : 'Line created', message: l.name });
      onSaved(l);
    } catch (err) {
      push({ kind: 'critical', title: 'Saving line failed', message: errorMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!line) return;
    setDeleting(true);
    try {
      await api.deleteLine(line.id);
      push({ kind: 'success', title: `Line “${line.name}” deleted` });
      onDeleted?.();
    } catch (err) {
      push({ kind: 'critical', title: 'Delete failed', message: errorMessage(err) });
    } finally {
      setDeleting(false);
      setConfirm(false);
    }
  };

  return (
    <Panel
      title={line ? `Line · ${line.name}` : 'New line'}
      icon={<Factory className="size-4" />}
      actions={
        <>
          {line && (
            <Link to={`/lines/${line.id}`} className="btn btn-sm btn-ghost">
              Open dashboard
            </Link>
          )}
          {line && (
            <button type="button" className="btn btn-sm btn-danger" onClick={() => setConfirm(true)}>
              <Trash className="size-3.5" /> Delete
            </button>
          )}
          <button type="button" className="btn btn-sm btn-primary" disabled={!valid || saving || (!!line && !dirty)} onClick={() => void save()}>
            <Save className="size-3.5" /> {saving ? 'Saving…' : line ? 'Save' : 'Create line'}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Name *" className="col-span-2">
          <input className="input" value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Pump assembly line 1" />
        </Field>
        <Field label="Code *">
          <input className="input uppercase" value={form.code} onChange={(e) => set('code', e.target.value.toUpperCase())} placeholder="PA1" maxLength={12} />
        </Field>
        <Field label="Takt time *" hint={form.takt_time_sec > 0 ? `= ${(3600 / form.takt_time_sec).toFixed(1)} units/h demand` : undefined}>
          <NumberInput value={form.takt_time_sec} onChange={(v) => set('takt_time_sec', v)} min={1} step={0.5} suffix="s" />
        </Field>
        <Field label="Description" className="col-span-2 md:col-span-4">
          <input className="input" value={form.description} onChange={(e) => set('description', e.target.value)} placeholder="What the line builds" />
        </Field>
        <Field label="Shift start">
          <input className="input" type="time" value={form.shift_start} onChange={(e) => set('shift_start', e.target.value)} />
        </Field>
        <Field label="Shift end">
          <input className="input" type="time" value={form.shift_end} onChange={(e) => set('shift_end', e.target.value)} />
        </Field>
        <div className="col-span-2 flex items-end pb-1">
          <Toggle checked={form.is_active} onChange={(v) => set('is_active', v)} label="Active" description="Inactive lines are not planned or alerted." />
        </div>
      </div>
      <ConfirmDialog
        open={confirm}
        danger
        busy={deleting}
        title="Delete line?"
        message={
          <>
            Delete <b className="text-ink">{line?.name}</b> including its stations and cameras? Recorded cycles of this line will be removed as well.
          </>
        }
        requireText={line?.code}
        confirmLabel="Delete line"
        onCancel={() => setConfirm(false)}
        onConfirm={() => void remove()}
      />
    </Panel>
  );
}

/* -------------------------------------------------------------- stations */

function emptyStation(lineId: number): StationInput {
  return { line_id: lineId, name: '', code: '', operation: '', parts_added: [], target_cycle_sec: 45, expected_picks: 2, operator_name: '', is_active: true };
}

function StationsEditor({ line, onChanged }: { line: Line; onChanged: () => void }) {
  const { push } = useToast();
  const stations = usePolling(() => api.stations(line.id), [line.id], 0);
  const [editing, setEditing] = useState<Station | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Station | null>(null);
  const [busy, setBusy] = useState(false);
  const list = [...(stations.data ?? [])].sort((a, b) => a.sequence - b.sequence);

  const move = async (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= list.length) return;
    const ids = list.map((s) => s.id);
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    setBusy(true);
    try {
      const updated = await api.reorderStations(line.id, ids);
      stations.setData(updated);
    } catch (err) {
      push({ kind: 'critical', title: 'Reorder failed', message: errorMessage(err) });
      stations.reload();
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.deleteStation(deleting.id);
      push({ kind: 'success', title: `Station “${deleting.name}” deleted` });
      stations.reload();
      onChanged();
    } catch (err) {
      push({ kind: 'critical', title: 'Delete failed', message: errorMessage(err) });
    } finally {
      setBusy(false);
      setDeleting(null);
    }
  };

  return (
    <Panel
      title="Process steps (stations)"
      subtitle="In production order – the next step is the one below"
      icon={<ListOrdered className="size-4" />}
      flush
      actions={
        <button type="button" className="btn btn-sm btn-primary" onClick={() => setEditing('new')}>
          <Plus className="size-3.5" /> Add station
        </button>
      }
    >
      {!stations.data ? (
        stations.loading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : (
          <ErrorState compact error={stations.error} onRetry={stations.reload} />
        )
      ) : list.length === 0 ? (
        <EmptyState compact title="No stations yet" message="Add the process steps of this line in order (e.g. 5–6 steps)." />
      ) : (
        <ol className="divide-y divide-edge">
          {list.map((s, i) => (
            <li key={s.id} className={`flex items-start gap-3 px-4 py-3 ${s.is_active ? '' : 'opacity-60'}`}>
              <div className="flex flex-col items-center gap-0.5">
                <button type="button" className="rounded p-0.5 text-ink-3 hover:bg-panel-3 hover:text-ink disabled:opacity-30" disabled={i === 0 || busy} onClick={() => void move(i, -1)} title="Move up">
                  <ArrowUp className="size-3.5" />
                </button>
                <span className="grid size-7 place-items-center rounded-md bg-panel-3 text-xs font-bold text-ink tabular-nums">{s.sequence}</span>
                <button
                  type="button"
                  className="rounded p-0.5 text-ink-3 hover:bg-panel-3 hover:text-ink disabled:opacity-30"
                  disabled={i === list.length - 1 || busy}
                  onClick={() => void move(i, 1)}
                  title="Move down"
                >
                  <ArrowDown className="size-3.5" />
                </button>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/stations/${s.id}`} className="text-sm font-semibold text-ink hover:text-sky-300">
                    {s.name}
                  </Link>
                  <span className="text-[10px] font-bold text-ink-3">{s.code}</span>
                  {!s.is_active && <span className="rounded bg-zinc-700/50 px-1.5 text-[10px] font-semibold text-zinc-300">inactive</span>}
                  {s.camera_ids.length === 0 && <span className="rounded px-1.5 text-[10px] text-slate-400 ring-1 ring-slate-500/50">no camera</span>}
                </div>
                {s.operation && <p className="mt-0.5 text-xs text-ink-2">{s.operation}</p>}
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-3">
                  <span className="tabular-nums">target {fmtSec(s.target_cycle_sec)}</span>
                  <span className="tabular-nums">{s.expected_picks} picks/cycle</span>
                  {s.operator_name && <span>operator {s.operator_name}</span>}
                  {s.parts_added.length > 0 && (
                    <span className="flex flex-wrap items-center gap-1">
                      adds:
                      {s.parts_added.map((p) => (
                        <Chip key={p}>{p}</Chip>
                      ))}
                    </span>
                  )}
                </div>
                {i < list.length - 1 && <div className="mt-1 text-[10px] text-ink-3">→ next: Step {list[i + 1].sequence} · {list[i + 1].name}</div>}
              </div>
              <div className="flex shrink-0 gap-1">
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEditing(s)} title="Edit">
                  <Pencil className="size-3.5" />
                </button>
                <button type="button" className="btn btn-sm btn-ghost hover:text-red-300" onClick={() => setDeleting(s)} title="Delete">
                  <Trash className="size-3.5" />
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}

      {editing && (
        <StationModal
          lineId={line.id}
          station={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            stations.reload();
            onChanged();
          }}
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        danger
        busy={busy}
        title="Delete station?"
        message={
          <>
            Delete <b className="text-ink">{deleting?.name}</b>? Its cycle history will no longer be shown on dashboards.
          </>
        }
        confirmLabel="Delete station"
        onCancel={() => setDeleting(null)}
        onConfirm={() => void remove()}
      />
    </Panel>
  );
}

function StationModal({ lineId, station, onClose, onSaved }: { lineId: number; station: Station | null; onClose: () => void; onSaved: () => void }) {
  const { push } = useToast();
  const [form, setForm] = useState<StationInput>(
    station
      ? {
          line_id: station.line_id,
          name: station.name,
          code: station.code,
          operation: station.operation,
          parts_added: station.parts_added,
          target_cycle_sec: station.target_cycle_sec,
          expected_picks: station.expected_picks,
          operator_name: station.operator_name,
          is_active: station.is_active,
        }
      : emptyStation(lineId),
  );
  const [saving, setSaving] = useState(false);
  const set = <K extends keyof StationInput>(k: K, v: StationInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const valid = form.name.trim() !== '' && form.target_cycle_sec > 0 && form.expected_picks >= 0;

  const save = async () => {
    setSaving(true);
    try {
      if (station) await api.updateStation(station.id, form);
      else await api.createStation(form);
      push({ kind: 'success', title: station ? 'Station saved' : 'Station added', message: form.name });
      onSaved();
    } catch (err) {
      push({ kind: 'critical', title: 'Saving station failed', message: errorMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      width="max-w-2xl"
      title={station ? `Edit Step ${station.sequence} · ${station.name}` : 'Add station (appended as last step)'}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={!valid || saving} onClick={() => void save()}>
            <Save className="size-4" /> {saving ? 'Saving…' : 'Save station'}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Field label="Name *" className="col-span-2">
          <input className="input" value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="e.g. Fit impeller" autoFocus />
        </Field>
        <Field label="Code">
          <input className="input uppercase" value={form.code} onChange={(e) => set('code', e.target.value.toUpperCase())} placeholder="S1" />
        </Field>
        <Field label="Operator">
          <input className="input" value={form.operator_name} onChange={(e) => set('operator_name', e.target.value)} />
        </Field>
        <Field label="Operation" className="col-span-2 md:col-span-4" hint="What work happens at this step">
          <textarea className="input min-h-[60px]" value={form.operation} onChange={(e) => set('operation', e.target.value)} />
        </Field>
        <Field label="Parts added" className="col-span-2 md:col-span-4" hint="Enter or comma to add each part">
          <TagInput value={form.parts_added} onChange={(v) => set('parts_added', v)} />
        </Field>
        <Field label="Target cycle *" hint="Planned time per unit">
          <NumberInput value={form.target_cycle_sec} onChange={(v) => set('target_cycle_sec', v)} min={1} step={0.5} suffix="s" />
        </Field>
        <Field label="Expected picks" hint="Part/tool picks per cycle">
          <NumberInput value={form.expected_picks} onChange={(v) => set('expected_picks', Math.max(0, Math.round(v)))} min={0} step={1} />
        </Field>
        <div className="col-span-2 flex items-end pb-1">
          <Toggle checked={form.is_active} onChange={(v) => set('is_active', v)} label="Active" />
        </div>
      </div>
    </Modal>
  );
}

/* --------------------------------------------------------------- cameras */

function CamerasEditor({ line, onChanged }: { line: Line; onChanged: () => void }) {
  const { push } = useToast();
  const cameras = usePolling(() => api.cameras(line.id), [line.id], 0);
  const stations = usePolling(() => api.stations(line.id), [line.id, line.station_count], 0);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState<CameraInput>({ line_id: line.id, station_id: null, name: '', source_type: 'rtsp', source: '', enabled: true });
  const [saving, setSaving] = useState(false);
  const stationName = (id: number | null) => {
    if (id === null) return '—';
    const s = stations.data?.find((x) => x.id === id);
    return s ? `Step ${s.sequence} · ${s.name}` : `#${id}`;
  };

  const add = async () => {
    setSaving(true);
    try {
      const c = await api.createCamera({ ...form, line_id: line.id });
      push({ kind: 'success', title: 'Camera added', message: `${c.name} – now draw its zones` });
      setAdding(false);
      setForm({ line_id: line.id, station_id: null, name: '', source_type: 'rtsp', source: '', enabled: true });
      cameras.reload();
      onChanged();
    } catch (err) {
      push({ kind: 'critical', title: 'Adding camera failed', message: errorMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  const valid = form.name.trim() !== '' && form.source.trim() !== '';

  return (
    <Panel
      title="Cameras"
      subtitle="Assign each camera to the step it watches; draw zones on the camera page"
      icon={<Cctv className="size-4" />}
      flush
      actions={
        <button type="button" className="btn btn-sm btn-primary" onClick={() => setAdding(true)}>
          <Plus className="size-3.5" /> Add camera
        </button>
      }
    >
      {!cameras.data ? (
        cameras.loading ? (
          <div className="p-4">
            <Skeleton className="h-16" />
          </div>
        ) : (
          <ErrorState compact error={cameras.error} onRetry={cameras.reload} />
        )
      ) : cameras.data.length === 0 ? (
        <EmptyState compact title="No cameras on this line" message="Add one camera per step (RTSP, HTTP/MJPEG, USB, video file or simulated)." />
      ) : (
        <div className="overflow-x-auto">
          <table className="table-dense">
            <thead>
              <tr>
                <th>Name</th>
                <th>Station</th>
                <th>Source</th>
                <th>Zones</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {cameras.data.map((c: Camera) => (
                <tr key={c.id}>
                  <td className="font-medium text-ink">{c.name}</td>
                  <td className="text-ink-2">{stationName(c.station_id)}</td>
                  <td className="max-w-[260px] truncate text-xs text-ink-3" title={c.source}>
                    <span className="text-ink-2">{SOURCE_TYPE_META[c.source_type]?.label ?? c.source_type}</span> · <span className="font-mono">{c.source}</span>
                  </td>
                  <td className="tabular-nums text-ink-2">{c.zones.length}</td>
                  <td>
                    {!c.enabled ? (
                      <span className="text-xs text-ink-3">disabled</span>
                    ) : c.status.online ? (
                      <span className="text-xs text-emerald-400">online</span>
                    ) : (
                      <span className="text-xs text-zinc-400">offline</span>
                    )}
                    {c.status.needs_reference && <span className="ml-2 text-xs text-amber-300">needs reference</span>}
                  </td>
                  <td className="text-right">
                    <Link to={`/cameras/${c.id}`} className="btn btn-sm">
                      <Shapes className="size-3.5" /> Zones & settings
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={adding}
        title={`Add camera to ${line.name}`}
        onClose={() => setAdding(false)}
        footer={
          <>
            <button type="button" className="btn" onClick={() => setAdding(false)}>
              Cancel
            </button>
            <button type="button" className="btn btn-primary" disabled={!valid || saving} onClick={() => void add()}>
              <Plus className="size-4" /> {saving ? 'Adding…' : 'Add camera'}
            </button>
          </>
        }
      >
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name *">
            <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Cam S1 top" autoFocus />
          </Field>
          <Field label="Station">
            <select className="input" value={form.station_id ?? ''} onChange={(e) => setForm({ ...form, station_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">— none —</option>
              {[...(stations.data ?? [])]
                .sort((a, b) => a.sequence - b.sequence)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    Step {s.sequence} · {s.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Source type">
            <select
              className="input"
              value={form.source_type}
              onChange={(e) => {
                const t = e.target.value as SourceType;
                setForm({ ...form, source_type: t, source: t === 'simulated' && !form.source ? 'sim' : form.source });
              }}
            >
              {(Object.keys(SOURCE_TYPE_META) as SourceType[]).filter((t) => t !== 'simulated').map((t) => (
                <option key={t} value={t}>
                  {SOURCE_TYPE_META[t].label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Source *">
            <input className="input font-mono text-xs" value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} placeholder={SOURCE_TYPE_META[form.source_type].placeholder} />
          </Field>
          <div className="col-span-2">
            <Toggle checked={form.enabled} onChange={(v) => setForm({ ...form, enabled: v })} label="Enabled" description="Start processing immediately" />
          </div>
        </div>
      </Modal>
    </Panel>
  );
}

/* ------------------------------------------------------------ danger zone */

function DangerZone() {
  const { push } = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const clear = async () => {
    setBusy(true);
    try {
      const r = await api.clearData();
      push({ kind: 'success', title: 'Data cleared', message: `${r.deleted.toLocaleString()} records deleted` });
      setOpen(false);
    } catch (err) {
      push({ kind: 'critical', title: 'Clearing data failed', message: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="rounded-xl border border-red-900/60 bg-red-950/20 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-red-300">
            <TriangleAlert className="size-4" /> Danger zone
          </h2>
          <p className="mt-0.5 text-xs text-ink-3">
            Delete all recorded cycles, alerts and heatmaps (e.g. demo data). Lines, stations, cameras and zones are kept.
          </p>
        </div>
        <button type="button" className="btn btn-danger" onClick={() => setOpen(true)}>
          <Trash className="size-4" /> Clear recorded data
        </button>
      </div>
      <ConfirmDialog
        open={open}
        danger
        busy={busy}
        title="Clear all recorded data?"
        message="This permanently deletes all cycles, alerts and heatmaps. Configuration (lines, stations, cameras, zones) is not affected. This cannot be undone."
        requireText="DELETE"
        confirmLabel="Delete all data"
        onCancel={() => setOpen(false)}
        onConfirm={() => void clear()}
      />
    </section>
  );
}
