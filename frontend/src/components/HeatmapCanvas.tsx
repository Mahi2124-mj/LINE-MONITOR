import { useEffect, useMemo, useRef, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '../api/client';
import type { Heatmap, RangeKey, Track, Zone } from '../api/types';
import { usePolling } from '../hooks/usePolling';
import { ZONE_META } from '../lib/meta';
import { errorMessage, fmtDateTime, isBackendDown } from '../lib/format';
import { Segmented } from './RangeSelector';

export const HAND_COLOR = '#22d3ee';
export const BODY_COLOR = '#e879f9';

interface HeatmapCanvasProps {
  cameraId: number;
  range: RangeKey;
  zones?: Zone[];
  className?: string;
}

type Mode = 'heatmap' | 'spaghetti';

/** Hand-position heatmap or spaghetti diagram drawn on a canvas over the camera snapshot. */
export function HeatmapCanvas({ cameraId, range, zones = [], className = '' }: HeatmapCanvasProps) {
  const [mode, setMode] = useState<Mode>('heatmap');
  const [trackLimit, setTrackLimit] = useState(10);
  const [showHand, setShowHand] = useState(true);
  const [showBody, setShowBody] = useState(true);
  const [showZones, setShowZones] = useState(true);
  const [snapKey, setSnapKey] = useState(0);
  const snapshot = useMemo(() => api.snapshotUrl(cameraId), [cameraId, snapKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const [snapFailed, setSnapFailed] = useState(false);
  const [aspect, setAspect] = useState(16 / 9);

  const heat = usePolling(() => api.heatmap(cameraId, range), [cameraId, range], 60_000);
  const tracks = usePolling(() => (mode === 'spaghetti' ? api.tracks(cameraId, trackLimit) : Promise.resolve<Track[]>([])), [cameraId, trackLimit, mode], 30_000);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || size.w === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(size.w * dpr);
    canvas.height = Math.round(size.h * dpr);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);

    if (showZones) drawZones(ctx, zones, size.w, size.h);
    if (mode === 'heatmap' && heat.data) drawHeatmap(ctx, heat.data, size.w, size.h);
    if (mode === 'spaghetti' && tracks.data) drawTracks(ctx, tracks.data, size.w, size.h, showHand, showBody);
  }, [size, mode, heat.data, tracks.data, showHand, showBody, showZones, zones]);

  const error = mode === 'heatmap' ? heat.error : tracks.error;
  const noData =
    mode === 'heatmap' ? heat.data !== undefined && (heat.data.max <= 0 || heat.data.grid.length === 0) : tracks.data !== undefined && tracks.data.length === 0;

  return (
    <div className={className}>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Segmented<Mode>
          value={mode}
          onChange={setMode}
          options={[
            { value: 'heatmap', label: 'Heatmap' },
            { value: 'spaghetti', label: 'Spaghetti' },
          ]}
        />
        {mode === 'spaghetti' && (
          <>
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              Last
              <select className="input w-auto py-0.5 text-xs" value={trackLimit} onChange={(e) => setTrackLimit(Number(e.target.value))}>
                {[5, 10, 20, 50].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
              cycles
            </label>
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              <input type="checkbox" checked={showHand} onChange={(e) => setShowHand(e.target.checked)} className="accent-cyan-400" />
              <span className="inline-block h-0.5 w-3" style={{ backgroundColor: HAND_COLOR }} /> Hands
            </label>
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              <input type="checkbox" checked={showBody} onChange={(e) => setShowBody(e.target.checked)} className="accent-fuchsia-400" />
              <span className="inline-block h-0.5 w-3" style={{ backgroundColor: BODY_COLOR }} /> Body / walking
            </label>
          </>
        )}
        <label className="flex items-center gap-1.5 text-xs text-ink-2">
          <input type="checkbox" checked={showZones} onChange={(e) => setShowZones(e.target.checked)} /> Zones
        </label>
        <button
          type="button"
          className="btn btn-ghost btn-sm ml-auto"
          onClick={() => {
            setSnapFailed(false);
            setSnapKey((k) => k + 1);
            heat.reload();
            tracks.reload();
          }}
          title="Reload snapshot and data"
        >
          <RefreshCw className="size-3.5" /> Refresh
        </button>
      </div>

      <div ref={wrapRef} className="relative w-full overflow-hidden rounded-lg border border-edge bg-black" style={{ aspectRatio: String(aspect) }}>
        {!snapFailed ? (
          <img
            src={snapshot}
            alt="Camera snapshot"
            className="absolute inset-0 h-full w-full object-fill opacity-70"
            onLoad={(e) => {
              const img = e.currentTarget;
              if (img.naturalWidth && img.naturalHeight) setAspect(img.naturalWidth / img.naturalHeight);
            }}
            onError={() => setSnapFailed(true)}
          />
        ) : (
          <div className="absolute inset-0 grid place-items-center text-xs text-ink-3">Snapshot unavailable</div>
        )}
        <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
        {(error || noData) && (
          <div className="absolute inset-x-0 bottom-0 bg-black/70 px-3 py-1.5 text-center text-xs text-ink-2">
            {error ? (isBackendDown(error) ? 'Line Monitor server not running – double-click Line Monitor on the Desktop.' : errorMessage(error)) : mode === 'heatmap' ? 'No hand positions recorded in this range yet.' : 'No tracks recorded yet.'}
          </div>
        )}
      </div>

      {mode === 'heatmap' ? (
        <div className="mt-2 flex items-center gap-2 text-[11px] text-ink-3">
          <span>Hand presence: low</span>
          <span className="h-2 w-32 rounded-full" style={{ background: 'linear-gradient(90deg, rgba(254,240,138,0.15), #facc15, #f97316, #dc2626)' }} />
          <span>high</span>
          <span className="ml-auto">Hot spots outside the work area point to reaches that can be eliminated.</span>
        </div>
      ) : (
        <div className="mt-2 text-[11px] text-ink-3">
          {tracks.data?.length ? `Showing ${tracks.data.length} cycle${tracks.data.length === 1 ? '' : 's'}, latest ${fmtDateTime(tracks.data[0]?.ended_at)}. ` : ''}
          Long or crossing paths = unnecessary hand travel / walking.
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- drawing */

function heatColor(v: number): [number, number, number, number] {
  // v in 0..1 -> pale yellow -> amber -> orange -> red, alpha grows with v
  const stops: [number, [number, number, number]][] = [
    [0, [254, 240, 138]],
    [0.35, [250, 204, 21]],
    [0.65, [249, 115, 22]],
    [1, [220, 38, 38]],
  ];
  let i = 0;
  while (i < stops.length - 2 && v > stops[i + 1][0]) i++;
  const [p0, c0] = stops[i];
  const [p1, c1] = stops[i + 1];
  const f = p1 === p0 ? 0 : Math.min(1, Math.max(0, (v - p0) / (p1 - p0)));
  const rgb = c0.map((c, k) => Math.round(c + (c1[k] - c) * f)) as [number, number, number];
  const alpha = v <= 0 ? 0 : Math.round((0.18 + 0.67 * Math.sqrt(v)) * 255);
  return [rgb[0], rgb[1], rgb[2], alpha];
}

function drawHeatmap(ctx: CanvasRenderingContext2D, hm: Heatmap, w: number, h: number) {
  if (hm.cols <= 0 || hm.rows <= 0 || hm.max <= 0) return;
  const off = document.createElement('canvas');
  off.width = hm.cols;
  off.height = hm.rows;
  const octx = off.getContext('2d');
  if (!octx) return;
  const img = octx.createImageData(hm.cols, hm.rows);
  for (let i = 0; i < hm.cols * hm.rows; i++) {
    const v = (hm.grid[i] ?? 0) / hm.max;
    const [r, g, b, a] = heatColor(v);
    img.data[i * 4] = r;
    img.data[i * 4 + 1] = g;
    img.data[i * 4 + 2] = b;
    img.data[i * 4 + 3] = a;
  }
  octx.putImageData(img, 0, 0);
  ctx.save();
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.globalCompositeOperation = 'source-over';
  ctx.drawImage(off, 0, 0, w, h);
  ctx.restore();
}

function drawPath(ctx: CanvasRenderingContext2D, pts: [number, number][], w: number, h: number, color: string, alpha: number, width: number) {
  if (pts.length < 2) return;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(pts[0][0] * w, pts[0][1] * h);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * w, pts[i][1] * h);
  ctx.stroke();
  // start (hollow) and end (filled) markers
  ctx.globalAlpha = Math.min(1, alpha + 0.2);
  ctx.fillStyle = color;
  const [ex, ey] = pts[pts.length - 1];
  ctx.beginPath();
  ctx.arc(ex * w, ey * h, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(pts[0][0] * w, pts[0][1] * h, 3, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function drawTracks(ctx: CanvasRenderingContext2D, tracks: Track[], w: number, h: number, hand: boolean, body: boolean) {
  const n = tracks.length;
  tracks.forEach((t, i) => {
    // newest first from the API -> newest most opaque
    const alpha = n <= 1 ? 0.9 : 0.35 + 0.55 * (1 - i / (n - 1));
    if (body) drawPath(ctx, t.body, w, h, BODY_COLOR, alpha, 2.5);
    if (hand) drawPath(ctx, t.hand, w, h, HAND_COLOR, alpha, 1.5);
  });
}

export function drawZones(ctx: CanvasRenderingContext2D, zones: Zone[], w: number, h: number) {
  for (const z of zones) {
    if (z.points.length < 3) continue;
    const color = ZONE_META[z.type]?.color ?? '#94a3b8';
    ctx.save();
    ctx.strokeStyle = color;
    ctx.fillStyle = color + '1a';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    z.points.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x * w, y * h) : ctx.lineTo(x * w, y * h)));
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = '600 11px system-ui, sans-serif';
    ctx.fillStyle = color;
    ctx.fillText(z.name || ZONE_META[z.type]?.label || z.type, z.points[0][0] * w + 4, z.points[0][1] * h + 13);
    ctx.restore();
  }
}
