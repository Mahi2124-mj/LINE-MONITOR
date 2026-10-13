import { useState, type MouseEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CircleAlert, ImageOff, Power, PowerOff, Shapes } from 'lucide-react';
import { api } from '../api/client';
import type { Camera } from '../api/types';
import { useLive } from '../context/LiveContext';
import { useToast } from '../context/ToastContext';
import { errorMessage, fmtNum, fmtRelative } from '../lib/format';
import { SOURCE_TYPE_META } from '../lib/meta';
import { LiveStream } from './LiveStream';

interface CameraTileProps {
  camera: Camera;
  stationLabel?: string | null;
  overlay?: boolean;
  className?: string;
  /** show tracker / resolution / source / last frame */
  detailed?: boolean;
  /** when given, the tile shows Enable / Disable and Zones buttons */
  onEnabledChange?: (c: Camera) => void;
}

/** Live thumbnail with name, station and status. Click opens the camera page. */
export function CameraTile({ camera, stationLabel, overlay = true, className = '', detailed, onEnabledChange }: CameraTileProps) {
  const { cameraStatus } = useLive();
  const { push } = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const status = { ...camera.status, ...(cameraStatus.get(camera.id) ?? {}) };
  const online = camera.enabled && status.online;

  const toggleEnabled = async (e: MouseEvent) => {
    e.preventDefault(); // the tile itself is a link
    e.stopPropagation();
    setBusy(true);
    try {
      const c = await api.updateCamera(camera.id, { enabled: !camera.enabled });
      onEnabledChange?.(c);
      push({ kind: 'success', title: `${c.name} ${c.enabled ? 'enabled' : 'disabled'}` });
    } catch (err) {
      push({ kind: 'critical', title: 'Could not change camera', message: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Link
      to={`/cameras/${camera.id}`}
      className={`group block overflow-hidden rounded-xl border border-edge bg-panel-2 transition hover:border-edge-2 hover:shadow-lg hover:shadow-black/30 ${className}`}
    >
      <div className="relative">
        {camera.enabled ? (
          <LiveStream cameraId={camera.id} overlay={overlay} fit="cover" mode="snapshot" intervalMs={500} />
        ) : (
          <div className="grid aspect-video place-items-center bg-black text-ink-3">
            <div className="flex flex-col items-center gap-1 text-xs">
              <ImageOff className="size-6" /> Disabled
            </div>
          </div>
        )}
        <div className="absolute top-2 left-2 flex items-center gap-1.5">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide backdrop-blur ${
              online ? 'bg-emerald-500/25 text-emerald-200' : 'bg-zinc-800/80 text-zinc-300'
            }`}
          >
            <span className={`size-1.5 rounded-full ${online ? 'bg-emerald-400 animate-pulse-soft' : 'bg-zinc-500'}`} />
            {online ? 'Live' : camera.enabled ? 'Offline' : 'Off'}
          </span>
          {status.needs_reference && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/25 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200 backdrop-blur" title="Part-presence detection needs an empty reference image">
              <CircleAlert className="size-3" /> Reference
            </span>
          )}
        </div>
        {online && (
          <span className="absolute top-2 right-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-ink-2 tabular-nums">{fmtNum(status.fps, 1)} fps</span>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium text-ink group-hover:text-sky-300">{camera.name}</div>
          <div className="truncate text-[11px] text-ink-3">{stationLabel ?? 'No station assigned'}</div>
        </div>
        {status.error && !detailed && (
          <span className="max-w-[45%] truncate text-[11px] text-rose-400" title={status.error}>
            {status.error}
          </span>
        )}
      </div>
      {detailed && (
        <div className="space-y-1 border-t border-edge px-3 py-2 text-[11px]">
          <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-ink-3">
            <span>
              Source: <span className="text-ink-2">{SOURCE_TYPE_META[camera.source_type]?.label ?? camera.source_type}</span>
            </span>
            <span>
              Tracker: <span className="text-ink-2">{status.tracker || '—'}</span>
            </span>
            <span>
              Resolution: <span className="text-ink-2 tabular-nums">{status.width && status.height ? `${status.width}×${status.height}` : '—'}</span>
            </span>
            <span>
              Last frame: <span className="text-ink-2">{fmtRelative(status.last_frame_at)}</span>
            </span>
            <span>
              Zones: <span className="text-ink-2 tabular-nums">{camera.zones.length}</span>
            </span>
            <span>
              Method: <span className="text-ink-2">{camera.config.cycle_method}</span>
            </span>
          </div>
          {status.needs_reference && <div className="text-amber-300">Needs an empty reference image (part presence).</div>}
          {status.error && (
            <div className="truncate text-rose-400" title={status.error}>
              Error: {status.error}
            </div>
          )}
        </div>
      )}
      {onEnabledChange && (
        <div className="flex gap-2 border-t border-edge px-3 py-2">
          <button type="button" className={`btn btn-sm ${camera.enabled ? '' : 'btn-primary'}`} disabled={busy} onClick={(e) => void toggleEnabled(e)}>
            {camera.enabled ? <PowerOff className="size-3.5" /> : <Power className="size-3.5" />}
            {busy ? 'Saving…' : camera.enabled ? 'Disable' : 'Enable'}
          </button>
          <button
            type="button"
            className="btn btn-sm"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              navigate(`/cameras/${camera.id}/zones`);
            }}
          >
            <Shapes className="size-3.5" /> Zones
          </button>
        </div>
      )}
    </Link>
  );
}
