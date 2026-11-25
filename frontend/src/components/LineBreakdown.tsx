import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ChevronLeft, ChevronRight, Clapperboard, Clock, Hourglass, Layers, Play, TimerOff, X } from 'lucide-react';
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/client';
import type { BreakdownElement, BreakdownLoss, BreakdownStep, ExampleCycle, LineWindow } from '../api/types';
import { usePolling } from '../hooks/usePolling';
import { fmtSec } from '../lib/format';
import { CHART } from '../lib/meta';
import { AXIS_PROPS, TooltipBox } from './charts/ChartTooltip';
import { EmptyState, ErrorState, SkeletonPanel } from './EmptyState';
import { Panel } from './Panel';
import { SPEEDS, Track, clock, type Seg } from './WindowPlayer';

/** What the line video shows: a time window of one camera, optionally one cycle in it to point out. */
export interface WatchTarget {
  cameraId: number | null;
  start: number; // unix s
  sec: number;
  focus?: { stationId: number; cycleId: number };
  label?: string;
}

/** a window around one cycle: a few seconds before it, the whole cycle and a little after */
export function watchOf(ex: ExampleCycle, label: string): WatchTarget {
  const sec = Math.min(300, Math.max(30, Math.ceil((ex.sec ?? 20) + 8)));
  return { cameraId: ex.camera_id, start: ex.start - 3, sec, focus: { stationId: ex.station_id, cycleId: ex.cycle_id }, label };
}

/** the first part of a long element name ("Lay the rail in the jig, fit the small part, ..." -> "Lay the rail in the jig") */
export function shortLabel(label: string): string {
  const cut = label.split(/ \(|, /)[0];
  return cut.length > 4 ? cut : label;
}

const pad = (n: number) => String(n).padStart(2, '0');
const hhmm = (ts: string | number) => {
  const d = new Date(ts);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/* ------------------------------------------------------------------ line flow */

export function FlowStrip({ steps, bottleneck, takt, onOpen }: { steps: BreakdownStep[]; bottleneck: number | null; takt: number; onOpen: (id: number) => void }) {
  if (!steps.length) return <EmptyState compact title="No steps on this line" />;
  return (
    <div className="flex flex-wrap items-stretch gap-y-3">
      {steps.map((s, i) => {
        const bn = s.station_id === bottleneck;
        const over = s.per_part !== null && takt > 0 && s.per_part > takt;
        return (
          <div key={s.station_id} className="flex items-stretch">
            <button
              type="button"
              onClick={() => onOpen(s.station_id)}
              className={`w-44 rounded-xl border px-3 py-2.5 text-left transition hover:bg-panel-3 ${bn ? 'border-red-500/70 bg-red-500/[0.06]' : 'border-edge bg-panel-2'}`}
              title="Open this step"
            >
              {bn && <span className="mb-1 inline-block rounded bg-red-600/80 px-1.5 py-0.5 text-[10px] font-bold text-white">BOTTLENECK</span>}
              <div className="line-clamp-2 text-sm font-semibold leading-tight text-ink">
                {s.sequence}. {s.name}
              </div>
              <div className={`mt-1.5 text-2xl font-semibold tabular-nums ${over ? 'text-red-400' : bn ? 'text-red-300' : 'text-sky-300'}`}>
                {s.per_part ?? '—'}
                <span className="ml-1 text-sm font-medium text-ink-3">s</span>
              </div>
              <div className="text-xs text-ink-3">
                {s.checked ? 'per part, average' : 'per part (median)'}
                {s.copies > 1 ? ` · ${s.copies} machines` : ''}
              </div>
              <div className="mt-1 text-xs text-ink-2 tabular-nums">
                {s.pace_per_hour ? `${s.pace_per_hour} per hour when running` : 'no cycles'} · {s.cycles} cycles
              </div>
              {!s.checked && <div className="mt-1 text-[11px] text-amber-300/90">No element breakup for this step</div>}
            </button>
            {i < steps.length - 1 && (
              <div className="flex w-7 items-center justify-center text-ink-3">
                <ChevronRight className="size-5" />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ where the time goes */

export function TimeBars({
  steps,
  takt,
  selected,
  onSelect,
}: {
  steps: BreakdownStep[];
  takt: number;
  selected: { sid: number; code: string } | null;
  onSelect: (sid: number, code: string) => void;
}) {
  const rows = steps.filter((s) => s.checked && s.elements.length);
  if (!rows.length) return <EmptyState compact title="No element breakup in this window" />;
  const longest = Math.max(...rows.map((s) => s.elements.reduce((a, e) => a + e.avg, 0)));
  const showTakt = takt > 0 && takt <= longest * 1.6;
  const scale = Math.max(longest, showTakt ? takt : 0) * 1.06;
  const pct = (v: number) => `${(100 * v) / scale}%`;
  return (
    <div className="space-y-5">
      {rows.map((s) => {
        const total = s.elements.reduce((a, e) => a + e.avg, 0);
        return (
          <div key={s.station_id}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
              <span className="font-semibold text-ink">
                {s.sequence}. {s.name}
              </span>
              <span className="text-xs text-ink-3 tabular-nums">
                {total.toFixed(1)} s per part on average · normal cycle {fmtSec(s.normal_cycle)}
              </span>
            </div>
            <div className="relative h-9 rounded bg-white/[0.04]">
              <div className="absolute inset-y-0 left-0 flex overflow-hidden rounded" style={{ width: pct(total) }}>
                {s.elements.map((e) => {
                  const on = selected?.sid === s.station_id && selected.code === e.code;
                  const w = (100 * e.avg) / total;
                  return (
                    <button
                      key={e.code}
                      type="button"
                      onClick={() => onSelect(s.station_id, e.code)}
                      title={`${e.label}\n${e.avg.toFixed(1)} s per part on average (usual ${e.median.toFixed(1)} s, in ${e.presence_pct}% of the cycles)`}
                      className={`relative h-full border-r border-black/40 text-[11px] font-semibold text-white transition hover:brightness-125 ${on ? 'ring-2 ring-white ring-inset' : ''}`}
                      style={{ width: `${w}%`, background: e.color }}
                    >
                      {w > 5 && <span className="drop-shadow-[0_0_2px_rgba(0,0,0,0.9)]">{e.avg.toFixed(1)}</span>}
                    </button>
                  );
                })}
              </div>
              {showTakt && (
                <div className="pointer-events-none absolute -inset-y-1 border-l-2 border-dashed border-slate-200" style={{ left: pct(takt) }}>
                  <span className="absolute -top-4 -translate-x-1/2 text-[10px] text-ink-2">takt {takt} s</span>
                </div>
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
              {s.elements.map((e) => {
                const on = selected?.sid === s.station_id && selected.code === e.code;
                return (
                  <button
                    key={e.code}
                    type="button"
                    onClick={() => onSelect(s.station_id, e.code)}
                    title={e.label}
                    className={`flex items-center gap-1.5 rounded px-1 text-[11px] transition hover:text-ink ${on ? 'bg-white/10 text-ink' : 'text-ink-3'}`}
                  >
                    <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: e.color }} />
                    {shortLabel(e.label)} <span className="tabular-nums text-ink-2">{e.avg.toFixed(1)}s</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      {!showTakt && takt > 0 && <p className="text-[11px] text-ink-3">Takt {takt} s is far above these times, so it is not drawn.</p>}
    </div>
  );
}

/* ------------------------------------------------------------------ one element: its trend and a video */

export function ElementDetail({
  step,
  el,
  onWatch,
  onClose,
}: {
  step: BreakdownStep;
  el: BreakdownElement;
  onWatch: (ex: ExampleCycle, label: string) => void;
  onClose: () => void;
}) {
  const pts = step.trend
    .filter((p) => p.el[el.code] !== undefined)
    .map((p) => ({ t: new Date(p.t).getTime(), v: p.el[el.code] as number | null, a: (p.ea?.[el.code] ?? null) as number | null, n: p.n }));
  // a break in the line where there were no cycles (a stop, the lunch break)
  const block = Math.min(...pts.slice(1).map((p, i) => p.t - pts[i].t), Infinity);
  const data: typeof pts = [];
  pts.forEach((p, i) => {
    if (i && p.t - pts[i - 1].t > 2.5 * block) data.push({ t: pts[i - 1].t + block, v: null, a: null, n: 0 });
    data.push(p);
  });
  return (
    <div className="mt-4 rounded-xl border border-edge-2 bg-panel-2 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <span className="mt-1 inline-block size-3 shrink-0 rounded-sm" style={{ background: el.color }} />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-ink">{el.label}</div>
            <div className="text-xs text-ink-3">
              {step.sequence}. {step.name} · usual {el.median.toFixed(1)} s · most cycles {el.p10.toFixed(1)}–{el.p90.toFixed(1)} s · longest {el.max.toFixed(1)} s ·
              clearly slower in {el.slow_cycles} cycles ({el.over_min} min extra)
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {el.slowest && (
            <button type="button" className="btn btn-sm" disabled={!el.slowest.video} onClick={() => el.slowest && onWatch(el.slowest, `${shortLabel(el.label)}: its longest one`)}>
              <Play className="size-3.5" /> Watch its longest
            </button>
          )}
          {step.typical && (
            <button type="button" className="btn btn-sm" disabled={!step.typical.video} onClick={() => step.typical && onWatch(step.typical, `${step.name}: a typical cycle`)}>
              <Play className="size-3.5" /> Watch a typical cycle
            </button>
          )}
          <button type="button" className="btn btn-sm px-2" onClick={onClose} aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
      </div>
      {data.length > 1 ? (
        <div className="mt-2" style={{ height: 170 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={CHART.grid} />
              <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} scale="time" tickFormatter={hhmm} {...AXIS_PROPS} />
              <YAxis {...AXIS_PROPS} width={36} label={{ value: 's', angle: 0, position: 'insideTopLeft', fill: CHART.tick, fontSize: 11 }} />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload?.length) return null;
                  const p = payload[0].payload as (typeof data)[number];
                  return (
                    <TooltipBox
                      title={hhmm(p.t)}
                      rows={[
                        { label: 'Average per part', value: fmtSec(p.a), color: el.color },
                        { label: 'Usual (median)', value: fmtSec(p.v), color: '#e2e8f0' },
                        { label: 'Cycles', value: String(p.n) },
                      ]}
                    />
                  );
                }}
              />
              <ReferenceLine y={el.median} stroke={CHART.takt} strokeDasharray="5 4" />
              <Line dataKey="a" stroke={el.color} strokeWidth={2} dot={{ r: 2, fill: el.color }} isAnimationActive={false} />
              <Line dataKey="v" stroke="#e2e8f0" strokeOpacity={0.6} strokeWidth={1.2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="mt-2 text-xs text-ink-3">Not enough time in this window for a trend.</p>
      )}
      <p className="mt-1 text-[11px] text-ink-3">
        Per time block: coloured line = average per part (slow ones included), thin line = its usual time; dashed = its usual time over the whole window.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ variation (baratsuki) per element */

export function Spread({ steps, onWatch }: { steps: BreakdownStep[]; onWatch: (ex: ExampleCycle, label: string) => void }) {
  const rows = steps.filter((s) => s.checked && s.elements.length);
  if (!rows.length) return <EmptyState compact title="No element breakup in this window" />;
  return (
    <div className="space-y-5">
      {rows.map((s) => {
        const els = [...s.elements].sort((a, b) => b.p90 - b.p10 - (a.p90 - a.p10));
        const top = Math.max(...els.map((e) => e.p90)) * 1.1 || 1;
        const x = (v: number) => `${Math.min(100, (100 * v) / top)}%`;
        return (
          <div key={s.station_id}>
            <div className="mb-1.5 text-sm font-semibold text-ink">
              {s.sequence}. {s.name}
            </div>
            <div className="space-y-1">
              {els.map((e, i) => (
                <button
                  key={e.code}
                  type="button"
                  disabled={!e.slowest?.video}
                  onClick={() => e.slowest && onWatch(e.slowest, `${shortLabel(e.label)}: its longest one`)}
                  title={`${e.label}\nmost cycles ${e.p10.toFixed(1)}–${e.p90.toFixed(1)} s, middle half ${e.q1.toFixed(1)}–${e.q3.toFixed(1)} s, usual ${e.median.toFixed(1)} s, longest ${e.max.toFixed(1)} s\nClick: watch its longest one`}
                  className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left transition hover:bg-white/[0.04] disabled:cursor-default"
                >
                  <span className={`w-40 shrink-0 truncate text-xs ${i === 0 ? 'font-semibold text-ink' : 'text-ink-2'}`}>{shortLabel(e.label)}</span>
                  <span className="relative h-3.5 min-w-0 flex-1">
                    <span className="absolute inset-x-0 top-1/2 h-px bg-white/10" />
                    <span className="absolute top-1/2 h-px -translate-y-1/2" style={{ left: x(e.p10), width: `calc(${x(e.p90)} - ${x(e.p10)})`, background: e.color }} />
                    <span
                      className="absolute inset-y-0 rounded-sm opacity-80"
                      style={{ left: x(e.q1), width: `max(3px, calc(${x(e.q3)} - ${x(e.q1)}))`, background: e.color }}
                    />
                    <span className="absolute inset-y-[-2px] w-0.5 bg-white" style={{ left: x(e.median) }} />
                  </span>
                  <span className="w-20 shrink-0 text-right text-[11px] tabular-nums text-ink-3">
                    {e.p10.toFixed(1)}–{e.p90.toFixed(1)} s
                  </span>
                </button>
              ))}
            </div>
          </div>
        );
      })}
      <p className="text-[11px] text-ink-3">
        Widest first. Thin line = most cycles (10–90%), box = the middle half, white tick = usual time. Click a row to watch that element's longest one.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ biggest losses */

const LOSS_ICON = { element: Layers, wait: Hourglass, long: Clock, stop: TimerOff } as const;

export function LossList({ losses, onWatch }: { losses: BreakdownLoss[]; onWatch: (ex: ExampleCycle, label: string) => void }) {
  if (!losses.length) return <EmptyState compact title="No losses found in this window" />;
  const most = Math.max(...losses.map((l) => l.minutes)) || 1;
  return (
    <div className="space-y-2">
      {losses.map((l, i) => {
        const Icon = LOSS_ICON[l.kind] ?? AlertTriangle;
        return (
          <div key={i} className="flex items-center gap-3 rounded-lg border border-edge bg-panel-2 px-3 py-2">
            <Icon className="size-4 shrink-0" style={{ color: l.color }} />
            <div className="min-w-0 flex-1">
              <div className="text-sm text-ink">{l.title}</div>
              <div className="mt-1 flex items-center gap-2">
                <span className="h-1.5 rounded-full" style={{ width: `${Math.max(4, (60 * l.minutes) / most)}%`, background: l.color }} />
                <span className="truncate text-[11px] text-ink-3">{l.step}</span>
              </div>
            </div>
            <div className="shrink-0 text-right">
              <div className="text-base font-semibold text-ink tabular-nums">{l.minutes}</div>
              <div className="text-[10px] text-ink-3">min</div>
            </div>
            <button
              type="button"
              className="btn btn-sm shrink-0"
              disabled={!l.example?.video}
              title={l.example?.video ? `Watch an example (${l.example.at.slice(11)})` : 'The recording of the example is gone (kept 12 h)'}
              onClick={() => l.example && onWatch(l.example, l.title)}
            >
              <Play className="size-3.5" /> Watch
            </button>
          </div>
        );
      })}
      <p className="text-[11px] text-ink-3">Minutes in this window beyond the usual time, biggest first. Watch plays an example in the video on this page.</p>
    </div>
  );
}

/* ------------------------------------------------------------------ the line video: one camera, a lane per person */

export function LinePlayer({
  lineId,
  target,
  onTarget,
  quick,
}: {
  lineId: number;
  target: WatchTarget | null;
  onTarget: (t: WatchTarget | null) => void;
  quick: BreakdownStep[];
}) {
  const [cam, setCam] = useState<number | null>(null);
  const cameraId = target?.cameraId ?? cam;
  const r = usePolling(() => api.lineWindow(lineId, cameraId, target?.start ?? null, target?.sec ?? 60), [lineId, cameraId, target?.start, target?.sec], 0);
  const w = r.data;
  const newest = w ? w.t0 >= w.latest_t0 - 1 : true;
  const move = (dir: number) => w && onTarget({ cameraId: w.camera_id, start: dir > 0 ? Math.min(w.t0 + w.sec, w.latest_t0) : w.t0 - w.sec, sec: w.sec });
  const onCam = quick.filter((s) => w && s.camera_id === w.camera_id && s.checked);
  return (
    <Panel
      title="Watch it"
      subtitle={
        w
          ? `${target?.label ? `${target.label} · ` : ''}${clock(w.t0, false)} – ${clock(w.t0 + w.sec, false)} · every person on this camera with their elements · recordings are kept 12 h`
          : 'Loading…'
      }
      icon={<Clapperboard className="size-4" />}
      actions={
        <>
          {w && w.cameras.length > 1 && (
            <select
              className="input w-auto py-1 text-xs"
              value={w.camera_id}
              onChange={(e) => {
                setCam(Number(e.target.value));
                onTarget(null);
              }}
              aria-label="Camera"
            >
              {w.cameras.map((c) => (
                <option key={c.camera_id} value={c.camera_id}>
                  Camera {c.camera_id}: {c.steps.join(', ')}
                </option>
              ))}
            </select>
          )}
          <button type="button" className="btn btn-sm" disabled={!w} onClick={() => move(-1)}>
            <ChevronLeft className="size-4" /> Earlier
          </button>
          <button type="button" className="btn btn-sm" disabled={!w || newest} onClick={() => move(1)}>
            Later <ChevronRight className="size-4" />
          </button>
          <button type="button" className="btn btn-sm" disabled={!target} onClick={() => onTarget(null)}>
            Newest
          </button>
        </>
      }
    >
      {onCam.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {onCam.map((s) => (
            <div key={s.station_id} className="flex items-center gap-1.5 rounded-lg border border-edge bg-panel-2 px-2 py-1">
              <span className="text-xs text-ink-2">
                {s.sequence}. {s.name}
              </span>
              <button
                type="button"
                className="rounded px-1.5 py-0.5 text-xs text-sky-300 hover:bg-white/10 disabled:opacity-40"
                disabled={!s.typical?.video}
                onClick={() => s.typical && onTarget(watchOf(s.typical, `${s.name}: a typical cycle`))}
              >
                Typical cycle
              </button>
              <button
                type="button"
                className="rounded px-1.5 py-0.5 text-xs text-amber-300 hover:bg-white/10 disabled:opacity-40"
                disabled={!s.slowest?.video}
                onClick={() => s.slowest && onTarget(watchOf(s.slowest, `${s.name}: the slowest cycle`))}
              >
                Slowest cycle
              </button>
            </div>
          ))}
        </div>
      )}
      {!w ? (
        r.error ? (
          <ErrorState error={r.error} onRetry={r.reload} />
        ) : (
          <SkeletonPanel className="h-72" />
        )
      ) : (
        <LaneVideo key={`${w.camera_id}-${w.t0}-${w.sec}`} w={w} lineId={lineId} focus={target?.focus} />
      )}
    </Panel>
  );
}

function LaneVideo({ w, lineId, focus }: { w: LineWindow; lineId: number; focus?: { stationId: number; cycleId: number } }) {
  const v = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const [paused, setPaused] = useState(true);
  const [rate, setRate] = useState(1);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const D = w.sec;

  useEffect(() => {
    let raf = 0;
    let last = -1;
    const tick = () => {
      const x = v.current;
      if (x && !x.seeking && Math.abs(x.currentTime - last) > 0.01) {
        last = x.currentTime;
        setT(last);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const lanes = w.lanes.map((ln) => {
    const meta = Object.fromEntries(ln.elements.map((e) => [e.code, e]));
    const segs: Seg[] = ln.cycles.flatMap((c) => c.segs.map(([code, a, b]) => ({ code, a: Math.max(0, a), b: Math.min(D, b) }))).filter((g) => g.b > g.a);
    return {
      ...ln,
      segs,
      color: (code: string) => meta[code]?.color ?? '#64748b',
      label: (code: string) => meta[code]?.label ?? code,
    };
  });
  const seek = (s: number) => {
    if (v.current) v.current.currentTime = Math.max(0, Math.min(D - 0.001, s));
    setT(s);
  };
  const was = useRef(false);
  const scrubStart = () => {
    was.current = !!v.current && !v.current.paused;
    v.current?.pause();
  };
  const scrubEnd = () => {
    if (was.current) void v.current?.play();
  };
  const toggle = () => {
    const x = v.current;
    if (x) void (x.paused ? x.play() : x.pause());
  };
  const frameStep = (n: number) => {
    v.current?.pause();
    seek((Math.round((v.current?.currentTime ?? 0) * w.fps - 0.1) + n + 0.1) / w.fps);
  };
  const setSpeed = (x: number) => {
    if (v.current) v.current.playbackRate = x;
    setRate(x);
  };
  const focusLane = lanes.find((l) => l.station_id === focus?.stationId);
  const focusCycle = focusLane?.cycles.find((c) => c.id === focus?.cycleId);
  const pct = (s: number) => `${(100 * Math.max(0, Math.min(D, s))) / D}%`;

  return (
    <div>
      <div className="lg:flex lg:items-start lg:gap-4">
        <div className="relative w-full lg:w-[min(68%,calc((100vh_-_300px)*16/9))] lg:shrink-0">
          <svg className="absolute size-0" aria-hidden="true">
            <filter id="lane-sharpen" colorInterpolationFilters="sRGB">
              <feGaussianBlur in="SourceGraphic" stdDeviation="1.6" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="arithmetic" k1="0" k2="1.8" k3="-0.8" k4="0" />
            </filter>
          </svg>
          <video
            ref={v}
            src={api.lineWindowClipUrl(lineId, w.camera_id, w.t0, w.sec)}
            controls
            muted
            playsInline
            onLoadedData={() => {
              setState('ready');
              if (focusCycle && v.current) v.current.currentTime = Math.max(0, focusCycle.start - 1);
            }}
            onError={() => setState('error')}
            onPlay={() => setPaused(false)}
            onPause={() => setPaused(true)}
            onRateChange={() => v.current && setRate(v.current.playbackRate)}
            className="aspect-video w-full rounded-lg border border-edge bg-black"
            style={{ filter: 'url(#lane-sharpen)' }}
          />
          {/* what each person does now, on the picture */}
          {state === 'ready' && (
            <div className="pointer-events-none absolute top-8 left-2 flex max-w-[70%] flex-col gap-1">
              {lanes.map((ln) => {
                const g = ln.segs.find((x) => t >= x.a && t < x.b);
                const c = ln.cycles.find((x) => t >= x.start && t < x.end);
                return (
                  <span key={ln.station_id} className="w-fit rounded bg-black/75 px-2 py-1 text-xs text-white">
                    <b>{ln.name}</b>
                    {g ? (
                      <>
                        {' · '}
                        <span style={{ color: ln.color(g.code) }}>■</span> {shortLabel(ln.label(g.code))} <span className="tabular-nums text-white/70">{(t - g.a).toFixed(1)}s</span>
                      </>
                    ) : (
                      <span className="text-white/60"> · {c ? 'between elements' : 'no cycle'}</span>
                    )}
                  </span>
                );
              })}
            </div>
          )}
          {state !== 'ready' && (
            <div className="absolute inset-0 grid place-items-center rounded-lg bg-black/70 p-4 text-center text-sm text-ink-2">
              {state === 'loading' ? 'Cutting the video from the recording… (about 10–20 s)' : 'The recording of this time is no longer available (recordings are kept 12 h).'}
            </div>
          )}
        </div>

        <div className="mt-2 min-w-0 flex-1 space-y-3 lg:mt-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <button type="button" className="btn btn-sm min-w-9 px-2" onClick={() => frameStep(-1)} title="Back 1 frame">
              ◂|
            </button>
            <button type="button" className="btn btn-sm min-w-12" onClick={toggle} title="Play / pause">
              {paused ? '▶' : '❚❚'}
            </button>
            <button type="button" className="btn btn-sm min-w-9 px-2" onClick={() => frameStep(1)} title="Forward 1 frame">
              |▸
            </button>
            {focusCycle && (
              <button type="button" className="btn btn-sm" onClick={() => seek(Math.max(0, focusCycle.start - 1))}>
                To the cycle start
              </button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs text-ink-3">Speed</span>
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSpeed(s)}
                className={`rounded-md px-2 py-1 text-xs font-semibold ring-1 ring-inset transition ${rate === s ? 'bg-sky-600 text-white ring-sky-500' : 'text-ink-2 ring-edge hover:bg-panel-3'}`}
              >
                {s}x
              </button>
            ))}
          </div>
          <div className="text-xs text-ink-3">
            <b className="text-base text-ink tabular-nums">{clock(w.t0 + t)}</b>
            <span className="ml-1.5">
              video {t.toFixed(1)}s of {D.toFixed(0)}s · speed {rate}x
            </span>
          </div>
          {lanes.map((ln) => (
            <div key={ln.station_id}>
              <div className="mb-1 text-[11px] font-semibold text-ink-2">
                {ln.sequence}. {ln.name}
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-3">
                {ln.elements.map((e) => (
                  <span key={e.code} className="flex items-center gap-1" title={e.label}>
                    <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: e.color }} />
                    {shortLabel(e.label)}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-3 space-y-2">
        {lanes.map((ln) => (
          <div key={ln.station_id} className="flex items-center gap-2">
            <span className="w-32 shrink-0 truncate text-xs text-ink-2" title={`${ln.sequence}. ${ln.name}`}>
              {ln.sequence}. {ln.name}
            </span>
            <div className="relative min-w-0 flex-1">
              <Track
                a={0}
                b={D}
                segs={ln.segs}
                cycles={ln.cycles}
                t={t}
                color={ln.color}
                label={ln.label}
                clock={(s) => clock(w.t0 + s)}
                onSeek={seek}
                onScrubStart={scrubStart}
                onScrubEnd={scrubEnd}
                className="h-8"
              />
              {focusLane?.station_id === ln.station_id && focusCycle && (
                <div
                  className="pointer-events-none absolute -inset-y-1 rounded border-2 border-white"
                  style={{ left: pct(focusCycle.start), width: `calc(${pct(focusCycle.end)} - ${pct(focusCycle.start)})` }}
                />
              )}
            </div>
          </div>
        ))}
        <p className="text-[11px] text-ink-3">
          One row per person on this camera; numbers mark where a cycle starts{focusCycle ? ', the white frame is the cycle you picked' : ''}. Click or drag a row to move
          the video.
        </p>
      </div>
    </div>
  );
}
