import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Check, MousePointer2, PenLine, RefreshCw, RotateCcw, Save, Trash, Undo2, X } from 'lucide-react';
import { api } from '../api/client';
import type { Camera, Station, Zone, ZoneType } from '../api/types';
import { useToast } from '../context/ToastContext';
import { errorMessage } from '../lib/format';
import { ZONE_META, ZONE_TYPES } from '../lib/meta';

type Pt = [number, number];

interface ZoneEditorProps {
  camera: Camera;
  stations: Station[];
  onSaved: (c: Camera) => void;
}

interface DragState {
  zoneId: string;
  /** vertex index, or -1 to move the whole polygon */
  vertex: number;
  start: Pt;
  original: Pt[];
}

const VERTEX_HIT_PX = 9;
const CLOSE_HIT_PX = 11;

const newId = () => `z_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

function pointInPolygon([x, y]: Pt, poly: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi) inside = !inside;
  }
  return inside;
}

function sameZones(a: Zone[], b: Zone[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Polygon zone editor drawn over a camera snapshot. Coordinates are normalized 0..1.
 * Draw: click points, double-click / click first point / Enter / "Finish" to close, Escape cancels.
 * Edit: drag vertices, drag inside a selected zone to move it, right-click a vertex to delete it.
 */
export function ZoneEditor({ camera, stations, onSaved }: ZoneEditorProps) {
  const { push } = useToast();
  const [zones, setZones] = useState<Zone[]>(camera.zones);
  const [savedZones, setSavedZones] = useState<Zone[]>(camera.zones);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawing, setDrawing] = useState<Pt[] | null>(null);
  const [drawType, setDrawType] = useState<ZoneType>('work_area');
  const [cursor, setCursor] = useState<Pt | null>(null);
  const [saving, setSaving] = useState(false);
  const [snapKey, setSnapKey] = useState(0);
  const [snapFailed, setSnapFailed] = useState(false);
  const [aspect, setAspect] = useState(camera.status.width && camera.status.height ? camera.status.width / camera.status.height : 16 / 9);
  const snapshot = useMemo(() => api.snapshotUrl(camera.id), [camera.id, snapKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  // Sync when the camera prop changes (e.g. after reload) while there are no local edits.
  const savedZonesRef = useRef(savedZones);
  useEffect(() => {
    savedZonesRef.current = savedZones;
  }, [savedZones]);
  useEffect(() => {
    const prevSaved = savedZonesRef.current;
    setSavedZones(camera.zones);
    setZones((cur) => (sameZones(cur, prevSaved) ? camera.zones : cur));
  }, [camera.zones]);

  const dirty = !sameZones(zones, savedZones);
  const selected = zones.find((z) => z.id === selectedId) ?? null;
  const stationName = (id: number | null) => {
    if (id === null) return null;
    const s = stations.find((st) => st.id === id);
    return s ? `Step ${s.sequence} · ${s.name}` : `Station #${id}`;
  };

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /* ------------------------------------------------------------ geometry */

  const toNorm = useCallback(
    (e: { clientX: number; clientY: number }): Pt => {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0) return [0, 0];
      return [clamp01((e.clientX - rect.left) / rect.width), clamp01((e.clientY - rect.top) / rect.height)];
    },
    [],
  );
  const distPx = useCallback((a: Pt, b: Pt) => Math.hypot((a[0] - b[0]) * size.w, (a[1] - b[1]) * size.h), [size]);

  const hitVertex = useCallback(
    (p: Pt): { zoneId: string; vertex: number } | null => {
      // prefer the selected zone
      const ordered = selected ? [selected, ...zones.filter((z) => z.id !== selected.id)] : zones;
      for (const z of ordered) {
        for (let i = 0; i < z.points.length; i++) if (distPx(p, z.points[i]) <= VERTEX_HIT_PX) return { zoneId: z.id, vertex: i };
      }
      return null;
    },
    [zones, selected, distPx],
  );

  const hitZone = useCallback(
    (p: Pt): Zone | null => {
      // topmost (last drawn) first
      for (let i = zones.length - 1; i >= 0; i--) if (pointInPolygon(p, zones[i].points)) return zones[i];
      return null;
    },
    [zones],
  );

  /* ------------------------------------------------------------- drawing */

  const makeZone = useCallback(
    (pts: Pt[]): Zone => {
      const count = zones.filter((z) => z.type === drawType).length + 1;
      return { id: newId(), name: `${ZONE_META[drawType].label} ${count}`, type: drawType, station_id: null, points: pts };
    },
    [zones, drawType],
  );

  const finishDrawing = useCallback(() => {
    if (!drawing) return;
    if (drawing.length < 3) {
      push({ kind: 'warning', title: 'A zone needs at least 3 points' });
      return;
    }
    const zone = makeZone(drawing);
    setZones((zs) => [...zs, zone]);
    setSelectedId(zone.id);
    setDrawing(null);
  }, [drawing, makeZone, push]);

  const cancelDrawing = useCallback(() => setDrawing(null), []);

  // keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
      if (e.key === 'Escape') {
        if (drawing) cancelDrawing();
        else setSelectedId(null);
      } else if (typing) {
        return;
      } else if (e.key === 'Enter' && drawing) {
        e.preventDefault();
        finishDrawing();
      } else if (e.key === 'Backspace' && drawing) {
        e.preventDefault();
        setDrawing((pts) => (pts && pts.length ? pts.slice(0, -1) : pts));
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && selectedId && !drawing) {
        e.preventDefault();
        setZones((zs) => zs.filter((z) => z.id !== selectedId));
        setSelectedId(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawing, selectedId, cancelDrawing, finishDrawing]);

  /* --------------------------------------------------------------- render */

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
    const W = size.w;
    const H = size.h;

    for (const z of zones) {
      if (z.points.length < 2) continue;
      const color = ZONE_META[z.type].color;
      const isSel = z.id === selectedId;
      ctx.beginPath();
      z.points.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x * W, y * H) : ctx.lineTo(x * W, y * H)));
      ctx.closePath();
      ctx.fillStyle = color + (isSel ? '40' : '22');
      ctx.fill();
      ctx.lineWidth = isSel ? 2.5 : 1.75;
      ctx.strokeStyle = color;
      ctx.setLineDash(isSel ? [] : [6, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
      // label
      const minY = Math.min(...z.points.map((p) => p[1]));
      const minX = Math.min(...z.points.map((p) => p[0]));
      const label = z.name || ZONE_META[z.type].label;
      ctx.font = '600 12px system-ui, sans-serif';
      const tw = ctx.measureText(label).width;
      const lx = Math.min(minX * W, W - tw - 10);
      const ly = Math.max(minY * H - 20, 2);
      ctx.fillStyle = 'rgba(0,0,0,0.65)';
      ctx.fillRect(lx, ly, tw + 10, 18);
      ctx.fillStyle = color;
      ctx.fillText(label, lx + 5, ly + 13);
      // vertices
      if (isSel) {
        for (const [x, y] of z.points) {
          ctx.beginPath();
          ctx.rect(x * W - 4.5, y * H - 4.5, 9, 9);
          ctx.fillStyle = '#0a0c0f';
          ctx.fill();
          ctx.lineWidth = 2;
          ctx.strokeStyle = color;
          ctx.stroke();
        }
      }
    }

    if (drawing) {
      const color = ZONE_META[drawType].color;
      ctx.lineWidth = 2;
      ctx.strokeStyle = color;
      ctx.beginPath();
      drawing.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x * W, y * H) : ctx.lineTo(x * W, y * H)));
      ctx.stroke();
      if (cursor && drawing.length) {
        const [lx, ly] = drawing[drawing.length - 1];
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(lx * W, ly * H);
        ctx.lineTo(cursor[0] * W, cursor[1] * H);
        if (drawing.length >= 2) ctx.lineTo(drawing[0][0] * W, drawing[0][1] * H);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      drawing.forEach(([x, y], i) => {
        const nearFirst = i === 0 && drawing.length >= 3 && cursor && Math.hypot((cursor[0] - x) * W, (cursor[1] - y) * H) <= CLOSE_HIT_PX;
        ctx.beginPath();
        ctx.arc(x * W, y * H, i === 0 ? (nearFirst ? 8 : 5.5) : 4, 0, Math.PI * 2);
        ctx.fillStyle = i === 0 ? color : '#0a0c0f';
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.strokeStyle = nearFirst ? '#ffffff' : color;
        ctx.stroke();
      });
    }
  }, [zones, selectedId, drawing, cursor, drawType, size]);

  /* --------------------------------------------------------------- events */

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (e.button !== 0) return;
    const p = toNorm(e);
    if (drawing) {
      if (drawing.length >= 3 && distPx(p, drawing[0]) <= CLOSE_HIT_PX) {
        finishDrawing();
        return;
      }
      const last = drawing[drawing.length - 1];
      if (last && distPx(p, last) < 4) return; // ignore the 2nd click of a double-click
      setDrawing([...drawing, p]);
      return;
    }
    const v = hitVertex(p);
    if (v) {
      const z = zones.find((zz) => zz.id === v.zoneId);
      if (!z) return;
      setSelectedId(z.id);
      dragRef.current = { zoneId: z.id, vertex: v.vertex, start: p, original: z.points };
      e.currentTarget.setPointerCapture(e.pointerId);
      return;
    }
    const z = hitZone(p);
    if (z) {
      setSelectedId(z.id);
      dragRef.current = { zoneId: z.id, vertex: -1, start: p, original: z.points };
      e.currentTarget.setPointerCapture(e.pointerId);
    } else {
      setSelectedId(null);
    }
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const p = toNorm(e);
    setCursor(p);
    const d = dragRef.current;
    if (!d) return;
    setZones((zs) =>
      zs.map((z) => {
        if (z.id !== d.zoneId) return z;
        if (d.vertex >= 0) return { ...z, points: z.points.map((pt, i) => (i === d.vertex ? p : pt)) };
        // move the whole polygon, keeping it inside the frame
        let dx = p[0] - d.start[0];
        let dy = p[1] - d.start[1];
        const xs = d.original.map((q) => q[0]);
        const ys = d.original.map((q) => q[1]);
        dx = Math.min(1 - Math.max(...xs), Math.max(-Math.min(...xs), dx));
        dy = Math.min(1 - Math.max(...ys), Math.max(-Math.min(...ys), dy));
        return { ...z, points: d.original.map(([x, y]) => [x + dx, y + dy] as Pt) };
      }),
    );
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    if (dragRef.current) {
      dragRef.current = null;
      if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    }
  };

  const onDoubleClick = () => {
    if (drawing) finishDrawing();
  };

  const onContextMenu = (e: ReactMouseEvent<HTMLCanvasElement>) => {
    const p = toNorm(e);
    if (drawing) {
      e.preventDefault();
      setDrawing((pts) => (pts && pts.length ? pts.slice(0, -1) : pts));
      return;
    }
    const v = hitVertex(p);
    if (!v) return;
    e.preventDefault();
    setZones((zs) =>
      zs.map((z) => {
        if (z.id !== v.zoneId) return z;
        if (z.points.length <= 3) {
          push({ kind: 'warning', title: 'A zone needs at least 3 points', message: 'Delete the zone instead.' });
          return z;
        }
        return { ...z, points: z.points.filter((_, i) => i !== v.vertex) };
      }),
    );
  };

  const updateZone = (id: string, patch: Partial<Zone>) => setZones((zs) => zs.map((z) => (z.id === id ? { ...z, ...patch } : z)));
  const deleteZone = (id: string) => {
    setZones((zs) => zs.filter((z) => z.id !== id));
    if (selectedId === id) setSelectedId(null);
  };

  const save = async () => {
    // include a polygon that is still being drawn (if it is complete enough)
    const toSave = drawing && drawing.length >= 3 ? [...zones, makeZone(drawing)] : zones;
    setDrawing(null);
    setSaving(true);
    try {
      const updated = await api.updateCamera(camera.id, { zones: toSave });
      setSavedZones(updated.zones);
      setZones(updated.zones);
      onSaved(updated);
      push({ kind: 'success', title: 'Zones saved', message: `${updated.zones.length} zone${updated.zones.length === 1 ? '' : 's'} on ${camera.name}` });
    } catch (err) {
      push({ kind: 'critical', title: 'Saving zones failed', message: errorMessage(err) });
    } finally {
      setSaving(false);
    }
  };

  const hoverCursor = (() => {
    if (drawing) return 'crosshair';
    if (dragRef.current) return 'grabbing';
    if (cursor && hitVertex(cursor)) return 'move';
    if (cursor && hitZone(cursor)) return 'grab';
    return 'default';
  })();

  /* ------------------------------------------------------------------ UI */

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0">
        {/* toolbar */}
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {drawing ? (
            <>
              <span className="flex items-center gap-1.5 rounded-md bg-sky-500/10 px-2 py-1 text-xs text-sky-200 ring-1 ring-sky-500/30">
                <PenLine className="size-3.5" />
                Drawing {ZONE_META[drawType].label}: {drawing.length} point{drawing.length === 1 ? '' : 's'}
              </span>
              <button type="button" className="btn btn-sm btn-primary" onClick={finishDrawing} disabled={drawing.length < 3}>
                <Check className="size-3.5" /> Finish
              </button>
              <button type="button" className="btn btn-sm" onClick={() => setDrawing((pts) => (pts ? pts.slice(0, -1) : pts))} disabled={!drawing.length}>
                <Undo2 className="size-3.5" /> Undo point
              </button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={cancelDrawing}>
                <X className="size-3.5" /> Cancel (Esc)
              </button>
            </>
          ) : (
            <>
              <select className="input w-auto py-1 text-xs" value={drawType} onChange={(e) => setDrawType(e.target.value as ZoneType)} title="Type of the next zone">
                {ZONE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {ZONE_META[t].label}
                  </option>
                ))}
              </select>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => (setSelectedId(null), setDrawing([]))}>
                <PenLine className="size-3.5" /> Draw zone
              </button>
              <span className="hidden items-center gap-1 text-[11px] text-ink-3 md:flex">
                <MousePointer2 className="size-3" /> Drag vertices / zones · right-click vertex to remove · Del deletes zone
              </span>
            </>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              title="Reload snapshot"
              onClick={() => {
                setSnapFailed(false);
                setSnapKey((k) => k + 1);
              }}
            >
              <RefreshCw className="size-3.5" /> Snapshot
            </button>
            <button type="button" className="btn btn-sm" disabled={!dirty || saving} onClick={() => (setZones(savedZones), setSelectedId(null), setDrawing(null))}>
              <RotateCcw className="size-3.5" /> Discard
            </button>
            <button type="button" className="btn btn-sm btn-primary" disabled={!dirty || saving} onClick={() => void save()}>
              <Save className="size-3.5" /> {saving ? 'Saving…' : dirty ? 'Save zones' : 'Saved'}
            </button>
          </div>
        </div>

        {/* canvas */}
        <div ref={wrapRef} className="relative w-full overflow-hidden rounded-lg border border-edge bg-black select-none" style={{ aspectRatio: String(aspect) }}>
          {!snapFailed ? (
            <img
              src={snapshot}
              alt="Camera snapshot"
              draggable={false}
              className="pointer-events-none absolute inset-0 h-full w-full object-fill"
              onLoad={(e) => {
                const img = e.currentTarget;
                if (img.naturalWidth && img.naturalHeight) setAspect(img.naturalWidth / img.naturalHeight);
              }}
              onError={() => setSnapFailed(true)}
            />
          ) : (
            <div className="pointer-events-none absolute inset-0 grid place-items-center bg-[repeating-linear-gradient(135deg,#0d1014_0_10px,#11151a_10px_20px)] text-xs text-ink-3">
              Snapshot unavailable – you can still draw zones (camera offline?)
            </div>
          )}
          <canvas
            ref={canvasRef}
            className="absolute inset-0 h-full w-full touch-none"
            style={{ cursor: hoverCursor }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onPointerLeave={() => setCursor(null)}
            onDoubleClick={onDoubleClick}
            onContextMenu={onContextMenu}
          />
          {drawing && drawing.length === 0 && (
            <div className="pointer-events-none absolute top-2 left-1/2 -translate-x-1/2 rounded bg-black/70 px-2 py-1 text-xs text-ink-2">
              Click to place points · double-click or click the first point to close
            </div>
          )}
        </div>
        {dirty && <div className="mt-1.5 text-xs text-amber-300">Unsaved zone changes</div>}
      </div>

      {/* side panel */}
      <div className="min-w-0 space-y-3">
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-ink-3">Zones ({zones.length})</div>
          {zones.length === 0 && <div className="rounded-lg border border-dashed border-edge-2 p-3 text-xs text-ink-3">No zones yet. Pick a type and click “Draw zone”.</div>}
          <ul className="space-y-1.5">
            {zones.map((z) => {
              const meta = ZONE_META[z.type];
              const isSel = z.id === selectedId;
              return (
                <li
                  key={z.id}
                  className={`rounded-lg border p-2 transition ${isSel ? 'border-sky-500/60 bg-panel-3' : 'border-edge bg-panel-2 hover:border-edge-2'}`}
                  onClick={() => setSelectedId(z.id)}
                >
                  <div className="flex items-center gap-2">
                    <span className="size-3 shrink-0 rounded-sm" style={{ backgroundColor: meta.color }} />
                    {isSel ? (
                      <input className="input py-0.5 text-sm" value={z.name} onChange={(e) => updateZone(z.id, { name: e.target.value })} aria-label="Zone name" />
                    ) : (
                      <span className="min-w-0 flex-1 truncate text-sm text-ink">{z.name || meta.label}</span>
                    )}
                    <button
                      type="button"
                      className="rounded p-1 text-ink-3 hover:bg-red-500/15 hover:text-red-300"
                      title="Delete zone"
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteZone(z.id);
                      }}
                    >
                      <Trash className="size-3.5" />
                    </button>
                  </div>
                  {isSel ? (
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <label className="block">
                        <span className="label">Type</span>
                        <select className="input py-1 text-xs" value={z.type} onChange={(e) => updateZone(z.id, { type: e.target.value as ZoneType })}>
                          {ZONE_TYPES.map((t) => (
                            <option key={t} value={t}>
                              {ZONE_META[t].label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="block">
                        <span className="label">Station</span>
                        <select
                          className="input py-1 text-xs"
                          value={z.station_id ?? ''}
                          onChange={(e) => updateZone(z.id, { station_id: e.target.value === '' ? null : Number(e.target.value) })}
                        >
                          <option value="">Camera default{camera.station_id !== null ? ` (${stationName(camera.station_id)})` : ''}</option>
                          {stations.map((s) => (
                            <option key={s.id} value={s.id}>
                              Step {s.sequence} · {s.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <p className="col-span-2 text-[11px] leading-snug text-ink-3">{meta.description}</p>
                      <p className="col-span-2 text-[10px] text-ink-3 tabular-nums">{z.points.length} points</p>
                    </div>
                  ) : (
                    <div className="mt-0.5 truncate pl-5 text-[11px] text-ink-3">
                      {meta.label} · {stationName(z.station_id) ?? 'camera default station'}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>

        <div className="rounded-lg border border-edge bg-panel-2 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-3">Zone types</div>
          <ul className="space-y-2">
            {ZONE_TYPES.map((t) => (
              <li key={t} className="flex gap-2">
                <span className="mt-1 size-2.5 shrink-0 rounded-sm" style={{ backgroundColor: ZONE_META[t].color }} />
                <div>
                  <div className="text-xs font-semibold text-ink">{ZONE_META[t].label}</div>
                  <div className="text-[11px] leading-snug text-ink-3">{ZONE_META[t].description}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
