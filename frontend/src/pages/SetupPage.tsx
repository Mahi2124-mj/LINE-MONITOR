import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowDown, ArrowUp, CircleCheck, CircleX, Factory, KeyRound, Loader2, Plus, Radio, Settings2, Trash2, Video } from 'lucide-react';
import { api } from '../api/client';
import type { Line, LineSetupStep, ProbeResult } from '../api/types';
import { ErrorState, Skeleton } from '../components/EmptyState';
import { ConfirmDialog, Field, NumberInput } from '../components/Form';
import { Panel } from '../components/Panel';
import { usePageTitle } from '../context/PageTitleContext';
import { useToast } from '../context/ToastContext';
import { usePolling } from '../hooks/usePolling';
import { errorMessage } from '../lib/format';

/**
 * Simple setup: define a line -> name each step -> type the step's camera IP -> Check -> Save & go live.
 */
export default function SetupPage() {
  usePageTitle('Lines & cameras');
  const [params, setParams] = useSearchParams();
  const lines = usePolling(() => api.lines(), [], 0);
  const selected = params.get('line');
  const lineId = selected && selected !== 'new' ? Number(selected) : null;
  const list = lines.data ?? [];
  const creatingFirst = lines.data !== undefined && list.length === 0;

  const select = (id: number | 'new') => setParams({ line: String(id) }, { replace: true });

  // open the first line (or the new-line form) by default
  useEffect(() => {
    if (!selected && lines.data) select(lines.data.length ? lines.data[0].id : 'new');
  }, [selected, lines.data]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
      <Panel
        title="Lines"
        icon={<Factory className="size-4" />}
        actions={
          <button type="button" className="btn btn-primary btn-sm" onClick={() => select('new')}>
            <Plus className="size-3.5" /> New line
          </button>
        }
        flush
        className="self-start"
      >
        {lines.error && !lines.data ? (
          <ErrorState error={lines.error} onRetry={lines.reload} compact />
        ) : !lines.data ? (
          <div className="space-y-2 p-3">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : list.length === 0 ? (
          <p className="p-4 text-sm text-ink-3">No lines yet. Fill in the form to add your first line.</p>
        ) : (
          <ul className="divide-y divide-edge">
            {list.map((l) => (
              <li key={l.id}>
                <button
                  type="button"
                  onClick={() => select(l.id)}
                  className={`w-full px-4 py-2.5 text-left transition hover:bg-panel-2 ${lineId === l.id ? 'bg-panel-2 shadow-[inset_3px_0_0_#38bdf8]' : ''}`}
                >
                  <div className="truncate text-sm font-medium text-ink">{l.name}</div>
                  <div className="text-xs text-ink-3">
                    {l.station_count} steps · {l.camera_count} cameras
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="border-t border-edge px-4 py-2.5">
          <Link to="/setup/advanced" className="inline-flex items-center gap-1.5 text-xs text-ink-3 hover:text-ink">
            <Settings2 className="size-3.5" /> Advanced (parts, targets, zones)
          </Link>
        </div>
      </Panel>

      {selected && (
        <LineEditor
          key={selected}
          lineId={lineId}
          first={creatingFirst}
          onSaved={(l) => {
            lines.reload();
            select(l.id);
          }}
          onDeleted={() => {
            lines.reload();
            setParams({}, { replace: true });
          }}
        />
      )}
    </div>
  );
}

type RowStatus = 'empty' | 'unchecked' | 'checking' | 'ok' | 'error' | 'saved';

interface Row {
  key: string;
  stationId: number | null;
  name: string;
  address: string;
  status: RowStatus;
  probe: ProbeResult | null;
  savedCameraId: number | null;
  savedAddress: string;
}

let rowSeq = 0;
const newRow = (): Row => ({
  key: `r${++rowSeq}`,
  stationId: null,
  name: '',
  address: '',
  status: 'empty',
  probe: null,
  savedCameraId: null,
  savedAddress: '',
});

function LineEditor({ lineId, first, onSaved, onDeleted }: { lineId: number | null; first: boolean; onSaved: (l: Line) => void; onDeleted: () => void }) {
  const { push } = useToast();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(lineId !== null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [name, setName] = useState('');
  const [takt, setTakt] = useState(60);
  const [user, setUser] = useState('');
  const [pass, setPass] = useState('');
  const [rows, setRows] = useState<Row[]>(() => [newRow(), newRow()]);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (lineId === null) return;
    let cancelled = false;
    Promise.all([api.line(lineId), api.stations(lineId), api.cameras(lineId)])
      .then(([line, stations, cameras]) => {
        if (cancelled) return;
        setName(line.name);
        setTakt(line.takt_time_sec);
        const sorted = [...stations].sort((a, b) => a.sequence - b.sequence);
        setRows(
          sorted.length
            ? sorted.map((s) => {
                const cam = cameras.find((c) => c.station_id === s.id);
                return {
                  ...newRow(),
                  stationId: s.id,
                  name: s.name,
                  address: cam?.source ?? '',
                  status: cam ? 'saved' : 'empty',
                  savedCameraId: cam?.id ?? null,
                  savedAddress: cam?.source ?? '',
                };
              })
            : [newRow()],
        );
        setLoading(false);
      })
      .catch((e) => {
        if (!cancelled) {
          setLoadError(e);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [lineId]);

  const update = (key: string, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const setAddress = (r: Row, address: string) => {
    const a = address.trim();
    let status: RowStatus = a ? 'unchecked' : 'empty';
    if (r.savedCameraId !== null && a === r.savedAddress) status = 'saved';
    update(r.key, { address, status, probe: null });
  };

  const check = async (r: Row) => {
    if (!r.address.trim()) return;
    update(r.key, { status: 'checking', probe: null });
    try {
      const res = await api.probeCamera(r.address.trim(), user.trim(), pass);
      setRows((rs) => rs.map((x) => (x.key === r.key && x.address === r.address ? { ...x, status: res.ok ? 'ok' : 'error', probe: res } : x)));
    } catch (e) {
      const res: ProbeResult = { ok: false, source_type: null, source: null, display_source: null, width: 0, height: 0, snapshot: null, elapsed_ms: 0, tried: 0, error: errorMessage(e) };
      setRows((rs) => rs.map((x) => (x.key === r.key ? { ...x, status: 'error', probe: res } : x)));
    }
  };

  const checkAll = async () => {
    for (const r of rows.filter((x) => x.status === 'unchecked' || x.status === 'error')) {
      await check(r);
    }
  };

  // changing the login invalidates successful checks of plain IPs (the stream URL contains the login)
  const onCredentials = (u: string, p: string) => {
    setUser(u);
    setPass(p);
    setRows((rs) => rs.map((r) => (r.status === 'ok' || r.status === 'error' ? { ...r, status: 'unchecked', probe: null } : r)));
  };

  const move = (i: number, d: -1 | 1) =>
    setRows((rs) => {
      const j = i + d;
      if (j < 0 || j >= rs.length) return rs;
      const copy = [...rs];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });

  const problems = useMemo(() => {
    const p: string[] = [];
    if (!name.trim()) p.push('Enter the line name');
    if (!rows.length) p.push('Add at least one step');
    rows.forEach((r, i) => {
      if (!r.name.trim()) p.push(`Step ${i + 1}: enter the step name`);
      if (r.status === 'unchecked') p.push(`Step ${i + 1}: click Check for the camera`);
      if (r.status === 'checking') p.push(`Step ${i + 1}: checking camera…`);
      if (r.status === 'error') p.push(`Step ${i + 1}: camera check failed`);
    });
    return p;
  }, [name, rows]);

  const camerasReady = rows.filter((r) => r.status === 'ok' || r.status === 'saved').length;
  const noCamera = rows.filter((r) => r.status === 'empty').length;

  const save = async () => {
    if (problems.length) return;
    setSaving(true);
    try {
      const steps: LineSetupStep[] = rows.map((r) => ({
        station_id: r.stationId,
        name: r.name.trim(),
        camera_address: r.address.trim(),
        camera_source_type: r.status === 'ok' ? r.probe?.source_type ?? null : null,
        camera_source: r.status === 'ok' ? r.probe?.source ?? null : null,
      }));
      const res = await api.saveLineSetup({ line_id: lineId, name: name.trim(), takt_time_sec: takt, steps });
      push({ kind: 'success', title: `${res.line.name} is live`, message: `${res.stations.length} steps · ${res.cameras.length} cameras running` });
      onSaved(res.line);
      navigate(`/lines/${res.line.id}`);
    } catch (e) {
      push({ kind: 'critical', title: 'Could not save the line', message: errorMessage(e) });
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (lineId === null) return;
    setDeleting(true);
    try {
      await api.deleteLine(lineId);
      push({ kind: 'success', title: 'Line deleted' });
      setConfirmDelete(false);
      onDeleted();
    } catch (e) {
      push({ kind: 'critical', title: 'Delete failed', message: errorMessage(e) });
    } finally {
      setDeleting(false);
    }
  };

  if (loading) return <Skeleton className="h-96" />;
  if (loadError) return <ErrorState error={loadError} />;

  return (
    <div className="min-w-0 space-y-4">
      <ol className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-3">
        {['Line name', 'Step names + camera IP', 'Check each camera', 'Save & go live'].map((s, i) => (
          <li key={s} className="flex items-center gap-1.5">
            <span className="grid size-5 place-items-center rounded-full bg-panel-3 text-[11px] font-semibold text-ink-2">{i + 1}</span>
            {s}
          </li>
        ))}
      </ol>

      <Panel title={lineId === null ? (first ? 'Set up your first line' : 'New line') : 'Line'} icon={<Factory className="size-4" />}>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_200px]">
          <Field label="Line name *">
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Line 1 – Meter assembly" autoFocus={lineId === null} />
          </Field>
          <Field label="Takt time" hint="Target time per unit. Leave 60 s if not known.">
            <NumberInput value={takt} onChange={(v) => setTakt(v > 0 ? v : 60)} min={1} suffix="s" />
          </Field>
        </div>
      </Panel>

      <Panel title="Camera login" subtitle="Used when you type only the IP address. Leave empty if the cameras have no password." icon={<KeyRound className="size-4" />}>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Username">
            <input className="input" value={user} onChange={(e) => onCredentials(e.target.value, pass)} placeholder="admin" autoComplete="off" />
          </Field>
          <Field label="Password">
            <input className="input" type="password" value={pass} onChange={(e) => onCredentials(user, e.target.value)} autoComplete="new-password" />
          </Field>
        </div>
      </Panel>

      <Panel
        title="Steps & cameras"
        subtitle="In production order – each step is followed by the one below it"
        icon={<Video className="size-4" />}
        actions={
          <button type="button" className="btn btn-sm" onClick={checkAll} disabled={!rows.some((r) => r.status === 'unchecked' || r.status === 'error')}>
            <Radio className="size-3.5" /> Check all
          </button>
        }
        flush
      >
        <div className="@container divide-y divide-edge">
          {rows.map((r, i) => (
            <div
              key={r.key}
              className="grid grid-cols-[2rem_minmax(0,1fr)] items-start gap-x-3 gap-y-2 px-4 py-3 @3xl:grid-cols-[2rem_minmax(0,1fr)_minmax(0,1.4fr)_auto]"
            >
              <div className="mt-5 grid size-8 place-items-center rounded-full bg-panel-3 text-sm font-semibold text-ink">{i + 1}</div>
              <Field label="Step name *">
                <input className="input" value={r.name} onChange={(e) => update(r.key, { name: e.target.value })} placeholder={i === 0 ? 'e.g. Base fitting' : 'e.g. PCB mounting'} />
              </Field>
              <div className="col-start-2 min-w-0 @3xl:col-start-auto">
                <span className="label">Camera IP / RTSP URL</span>
                <div className="flex gap-2">
                  <input
                    className="input font-mono"
                    value={r.address}
                    onChange={(e) => setAddress(r, e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && check(r)}
                    placeholder="192.168.1.64"
                    spellCheck={false}
                  />
                  <button type="button" className="btn shrink-0" onClick={() => check(r)} disabled={!r.address.trim() || r.status === 'checking'}>
                    {r.status === 'checking' ? <Loader2 className="size-4 animate-spin" /> : <Radio className="size-4" />} Check
                  </button>
                </div>
                <RowStatusView row={r} />
              </div>
              <div className="col-start-2 flex gap-1 @3xl:col-start-auto @3xl:pt-5">
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => move(i, -1)} disabled={i === 0} aria-label="Move up">
                  <ArrowUp className="size-4" />
                </button>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => move(i, 1)} disabled={i === rows.length - 1} aria-label="Move down">
                  <ArrowDown className="size-4" />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm text-rose-300"
                  onClick={() => setRows((rs) => rs.filter((x) => x.key !== r.key))}
                  disabled={rows.length === 1}
                  aria-label="Remove step"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="border-t border-edge px-4 py-3">
          <button type="button" className="btn btn-sm" onClick={() => setRows((rs) => [...rs, newRow()])}>
            <Plus className="size-3.5" /> Add step
          </button>
        </div>
      </Panel>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-edge bg-panel px-4 py-3">
        <div className="min-w-0 text-sm">
          <div className="text-ink-2">
            {rows.length} steps · <span className="text-emerald-300">{camerasReady} cameras ready</span>
            {noCamera > 0 && <span className="text-ink-3"> · {noCamera} without camera</span>}
          </div>
          {problems.length > 0 && <div className="truncate text-xs text-amber-300">{problems[0]}</div>}
        </div>
        <div className="flex gap-2">
          {lineId !== null && (
            <button type="button" className="btn btn-danger" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="size-4" /> Delete line
            </button>
          )}
          <button type="button" className="btn btn-primary" onClick={save} disabled={saving || problems.length > 0}>
            {saving ? <Loader2 className="size-4 animate-spin" /> : <Radio className="size-4" />} Save & go live
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this line?"
        message="The line, its steps, cameras and all recorded cycles will be deleted."
        confirmLabel="Delete line"
        danger
        busy={deleting}
        onConfirm={remove}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

function RowStatusView({ row }: { row: Row }) {
  const p = row.probe;
  switch (row.status) {
    case 'empty':
      return <p className="mt-1.5 text-xs text-ink-3">No camera for this step (optional).</p>;
    case 'unchecked':
      return <p className="mt-1.5 text-xs text-amber-300">Not checked yet – click Check.</p>;
    case 'checking':
      return <p className="mt-1.5 text-xs text-sky-300">Connecting to the camera… (trying common camera stream paths, up to ~15 s)</p>;
    case 'error':
      return (
        <p className="mt-1.5 flex items-start gap-1.5 text-xs text-rose-300">
          <CircleX className="mt-0.5 size-3.5 shrink-0" /> {p?.error ?? 'Camera check failed'}
        </p>
      );
    case 'saved':
      return (
        <div className="mt-2 flex items-center gap-3">
          {row.savedCameraId !== null && (
            <img src={api.snapshotUrl(row.savedCameraId, false)} alt="" className="h-14 w-24 rounded border border-edge bg-black object-cover" />
          )}
          <p className="flex items-center gap-1.5 text-xs text-emerald-300">
            <CircleCheck className="size-3.5" /> Saved camera
          </p>
        </div>
      );
    case 'ok':
      return (
        <div className="mt-2 flex items-center gap-3">
          {p?.snapshot && <img src={p.snapshot} alt="Camera check" className="h-14 w-24 rounded border border-emerald-500/40 bg-black object-cover" />}
          <div className="min-w-0 text-xs">
            <p className="flex items-center gap-1.5 text-emerald-300">
              <CircleCheck className="size-3.5" /> Connected · {p?.width}×{p?.height}
            </p>
            <p className="truncate font-mono text-[11px] text-ink-3" title={p?.display_source ?? ''}>
              {p?.display_source}
            </p>
          </div>
        </div>
      );
  }
}
