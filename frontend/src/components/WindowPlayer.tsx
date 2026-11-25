import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { ChevronLeft, ChevronRight, Clapperboard } from 'lucide-react';
import { api } from '../api/client';
import type { MachineWindow } from '../api/types';
import { usePolling } from '../hooks/usePolling';
import { Segmented } from './RangeSelector';
import { ErrorState, SkeletonPanel } from './EmptyState';
import { Panel } from './Panel';

export const SPEEDS = [0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 4];
export const WINDOW_LENGTHS = [60, 72]; // seconds: 1 min, 1.2 min

type Cycle = MachineWindow['cycles'][number];
export interface Seg {
  code: string;
  a: number;
  b: number;
}

const pad = (n: number) => String(n).padStart(2, '0');
export const clock = (unix: number, tenths = true) => {
  const d = new Date(unix * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${tenths ? `.${Math.floor(d.getMilliseconds() / 100)}` : ''}`;
};

/** One window (about a minute) of a machine in one video: every cycle in it numbered on a timeline of its elements, a
 * zoomed timeline of the current cycle, frame steps, cycle / element jumps and speeds 0.1x-4x. */
export function WindowPlayer({
  stationId,
  at,
  sec,
  onWindow,
}: {
  stationId: number;
  at: number | null; // window start (unix s); null = the newest
  sec: number;
  onWindow: (at: number | null, sec: number) => void;
}) {
  const r = usePolling(() => api.machineWindow(stationId, at, sec), [stationId, at, sec], 0);
  const w = r.data;
  const newest = w ? w.t0 >= w.latest_t0 - 1 : true;
  return (
    <Panel
      title="Cycles in one video"
      subtitle={
        w
          ? `${clock(w.t0, false)} – ${clock(w.t0 + w.sec, false)} · ${w.cycles.length} cycle${w.cycles.length === 1 ? '' : 's'} · recordings are kept 12 h`
          : 'Loading…'
      }
      icon={<Clapperboard className="size-4" />}
      actions={
        <>
          <Segmented
            value={String(sec)}
            onChange={(v) => onWindow(w ? w.t0 : at, Number(v))}
            options={WINDOW_LENGTHS.map((s) => ({ value: String(s), label: s === 60 ? '1 min' : `${(s / 60).toFixed(1)} min` }))}
          />
          <button type="button" className="btn btn-sm" disabled={!w} onClick={() => w && onWindow(w.t0 - sec, sec)}>
            <ChevronLeft className="size-4" /> Previous
          </button>
          <button type="button" className="btn btn-sm" disabled={!w || newest} onClick={() => w && onWindow(Math.min(w.t0 + sec, w.latest_t0), sec)}>
            Next <ChevronRight className="size-4" />
          </button>
          <button type="button" className="btn btn-sm" disabled={at === null} onClick={() => onWindow(null, sec)}>
            Newest
          </button>
        </>
      }
    >
      {!w ? r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : <SkeletonPanel className="h-72" /> : <Player key={`${w.t0}-${w.sec}`} w={w} stationId={stationId} />}
    </Panel>
  );
}

function Player({ w, stationId }: { w: MachineWindow; stationId: number }) {
  const v = useRef<HTMLVideoElement>(null);
  const pending = useRef<number | null>(null); // the newest seek target while the browser is still seeking
  const [t, setT] = useState(0);
  const [paused, setPaused] = useState(true);
  const [rate, setRate] = useState(1);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [sharp, setSharp] = useState(true);
  const D = w.sec;

  const segs: Seg[] = w.cycles.flatMap((c) => c.segs.map(([code, a, b]) => ({ code, a: Math.max(0, a), b: Math.min(D, b) }))).filter((g) => g.b > g.a);
  const meta = Object.fromEntries(w.elements.map((e) => [e.code, e]));
  const color = (code: string) => meta[code]?.color ?? '#64748b';
  const label = (code: string) => meta[code]?.label ?? code;
  const cycleAt = (s: number): Cycle | null => w.cycles.find((c) => s >= c.start && s < c.end) ?? null;
  const segAt = (s: number): Seg | null => segs.find((g) => s >= g.a && s < g.b) ?? null;

  // the position follows the video (every frame while it plays)
  useEffect(() => {
    let raf = 0;
    let last = -1;
    const tick = () => {
      const x = v.current;
      if (x && !x.seeking && pending.current === null && Math.abs(x.currentTime - last) > 0.01) {
        last = x.currentTime;
        setT(last);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const seek = (s: number) => {
    const x = v.current;
    if (!x) return;
    s = Math.max(0, Math.min(D - 0.001, s));
    if (x.seeking) pending.current = s;
    else x.currentTime = s;
    setT(s);
  };
  const now = () => pending.current ?? v.current?.currentTime ?? 0;
  const frameStep = (n: number) => {
    v.current?.pause();
    seek((Math.round(now() * w.fps - 0.1) + n + 0.1) / w.fps);
  };
  const jump = (starts: number[], dir: number) => {
    const s = now();
    const target = dir > 0 ? starts.find((a) => a > s + 0.05) : [...starts].reverse().find((a) => a < s - 0.3);
    if (target !== undefined) seek(target + 0.01);
  };
  const jumpCycle = (dir: number) => jump(w.cycles.map((c) => Math.max(0, c.start)), dir);
  const jumpSeg = (dir: number) => jump(segs.map((g) => g.a), dir);
  const setSpeed = (x: number) => {
    if (v.current) v.current.playbackRate = x;
    setRate(x);
  };
  const toggle = () => {
    const x = v.current;
    if (x) void (x.paused ? x.play() : x.pause());
  };

  // keyboard: Space play/pause · ← → 1 frame · Shift+← → 1 s · ↑ ↓ speed · [ ] cycle · , . element · 1-8 speed
  const keys = useRef<(e: KeyboardEvent) => void>(() => {});
  keys.current = (e: KeyboardEvent) => {
    const tg = e.target as HTMLElement | null;
    if (tg && (/INPUT|TEXTAREA|SELECT/.test(tg.tagName) || tg.isContentEditable)) return;
    const i = SPEEDS.indexOf(rate);
    const k = e.key;
    if (k === ' ') toggle();
    else if (k === 'ArrowLeft') (e.shiftKey ? seek(now() - 1) : frameStep(-1));
    else if (k === 'ArrowRight') (e.shiftKey ? seek(now() + 1) : frameStep(1));
    else if (k === 'ArrowUp') setSpeed(SPEEDS[Math.min(SPEEDS.length - 1, (i < 0 ? 4 : i) + 1)]);
    else if (k === 'ArrowDown') setSpeed(SPEEDS[Math.max(0, (i < 0 ? 4 : i) - 1)]);
    else if (k === '[') jumpCycle(-1);
    else if (k === ']') jumpCycle(1);
    else if (k === ',') jumpSeg(-1);
    else if (k === '.') jumpSeg(1);
    else if (k >= '1' && k <= '8') setSpeed(SPEEDS[Number(k) - 1]);
    else return;
    e.preventDefault();
  };
  useEffect(() => {
    const on = (e: KeyboardEvent) => keys.current(e);
    window.addEventListener('keydown', on);
    return () => window.removeEventListener('keydown', on);
  }, []);

  // dragging a timeline pauses the video and plays on after
  const was = useRef(false);
  const scrubStart = () => {
    was.current = !!v.current && !v.current.paused;
    v.current?.pause();
  };
  const scrubEnd = () => {
    if (was.current) void v.current?.play();
  };

  const c = cycleAt(t);
  const g = segAt(t);
  const z: [number, number] = c ? [Math.max(0, c.start - 1), Math.min(D, c.end + 1)] : [Math.max(0, t - 10), Math.min(D, t + 10)];
  const btn = 'btn btn-sm min-w-9 justify-center px-2';
  const track = { segs, cycles: w.cycles, t, color, label, clock: (s: number) => clock(w.t0 + s), onSeek: seek, onScrubStart: scrubStart, onScrubEnd: scrubEnd };

  return (
    <div>
      {/* large screens: the video on the left, as big as fits with the timelines below it still on the screen; the
          controls, cycles and legend use the space beside it */}
      <div className="lg:flex lg:items-start lg:gap-4">
        <div className="relative w-full lg:w-[min(70%,calc((100vh_-_270px)*16/9))] lg:shrink-0">
          {/* the recordings are 640x360, shown about twice as big: an unsharp mask at screen size makes edges crisp again */}
          <svg className="absolute size-0" aria-hidden="true">
            <filter id="window-sharpen" colorInterpolationFilters="sRGB">
              <feGaussianBlur in="SourceGraphic" stdDeviation="1.6" result="blur" />
              <feComposite in="SourceGraphic" in2="blur" operator="arithmetic" k1="0" k2="1.8" k3="-0.8" k4="0" />
            </filter>
          </svg>
          <video
            ref={v}
            src={api.machineWindowClipUrl(stationId, w.t0, w.sec)}
            controls
            muted
            playsInline
            onLoadedData={() => setState('ready')}
            onError={() => setState('error')}
            onPlay={() => setPaused(false)}
            onPause={() => setPaused(true)}
            onRateChange={() => v.current && setRate(v.current.playbackRate)}
            onSeeked={() => {
              if (pending.current !== null && v.current) {
                const p = pending.current;
                pending.current = null;
                v.current.currentTime = p;
              }
            }}
            className="aspect-video w-full rounded-lg border border-edge bg-black"
            style={sharp ? { filter: 'url(#window-sharpen)' } : undefined}
          />
          {state !== 'ready' && (
            <div className="absolute inset-0 grid place-items-center rounded-lg bg-black/70 p-4 text-center text-sm text-ink-2">
              {state === 'loading'
                ? 'Cutting the video of this minute from the recording… (about 10–15 s)'
                : 'The recording of this time is no longer available (recordings are kept 12 h).'}
            </div>
          )}
        </div>

        <div className="mt-2 min-w-0 flex-1 space-y-3 lg:mt-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <button type="button" className={btn} onClick={() => jumpCycle(-1)} title="Previous cycle  [">
              ⏮
            </button>
            <button type="button" className={btn} onClick={() => jumpSeg(-1)} title="Previous element  ,">
              «
            </button>
            <button type="button" className={btn} onClick={() => frameStep(-1)} title="Back 1 frame  ←">
              ◂|
            </button>
            <button type="button" className={`${btn} min-w-12`} onClick={toggle} title="Play / pause  Space">
              {paused ? '▶' : '❚❚'}
            </button>
            <button type="button" className={btn} onClick={() => frameStep(1)} title="Forward 1 frame  →">
              |▸
            </button>
            <button type="button" className={btn} onClick={() => jumpSeg(1)} title="Next element  .">
              »
            </button>
            <button type="button" className={btn} onClick={() => jumpCycle(1)} title="Next cycle  ]">
              ⏭
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-xs text-ink-3">Speed</span>
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSpeed(s)}
                className={`rounded-md px-2 py-1 text-xs font-semibold ring-1 ring-inset transition ${
                  rate === s ? 'bg-sky-600 text-white ring-sky-500' : 'text-ink-2 ring-edge hover:bg-panel-3'
                }`}
              >
                {s}x
              </button>
            ))}
            <button
              type="button"
              onClick={() => setSharp(!sharp)}
              title="Sharpen the picture (the recordings are 640x360)"
              className={`ml-2 rounded-md px-2 py-1 text-xs font-semibold ring-1 ring-inset transition ${
                sharp ? 'bg-sky-600 text-white ring-sky-500' : 'text-ink-2 ring-edge hover:bg-panel-3'
              }`}
            >
              Sharpen {sharp ? 'on' : 'off'}
            </button>
          </div>

          <div className="space-y-0.5 text-xs text-ink-3">
            <div>
              <b className="text-base text-ink tabular-nums">{clock(w.t0 + t)}</b>
              <span className="ml-1.5">video {t.toFixed(1)}s · speed {rate}x</span>
            </div>
            <div>{c ? `Cycle ${c.n}: ${(t - c.start).toFixed(1)}s / ${(c.end - c.start).toFixed(1)}s` : 'Between cycles'}</div>
            {g && (
              <div className="flex items-center gap-1.5">
                <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: color(g.code) }} />
                <span className="text-ink-2">{label(g.code)}</span> ({(t - g.a).toFixed(1)}s / {(g.b - g.a).toFixed(1)}s)
              </div>
            )}
          </div>

          <div>
            <div className="mb-1 text-[11px] text-ink-3">Cycles in this video · click to jump</div>
            <div className="flex flex-wrap gap-1.5">
              {w.cycles.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  onClick={() => seek(Math.max(0, x.start) + 0.01)}
                  className={`rounded-md px-2 py-0.5 text-xs ring-1 ring-inset transition ${c?.n === x.n ? 'bg-sky-500/20 text-ink ring-sky-500/50' : 'text-ink-2 ring-edge hover:bg-panel-3'}`}
                >
                  #{x.n} {clock(w.t0 + x.start, false)} · {x.sec?.toFixed(1)}s
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-3">
            {w.elements.map((e) => (
              <span key={e.code} className="flex items-center gap-1.5">
                <span className="inline-block size-2.5 shrink-0 rounded-sm" style={{ background: e.color }} />
                {e.label}
              </span>
            ))}
          </div>
          <p className="text-[11px] text-ink-3">
            Drag a timeline to scrub. Keys: Space play/pause · ← → 1 frame · Shift+← → 1 s · ↑ ↓ speed · [ ] cycle · , . element · 1–8 speed
          </p>
        </div>
      </div>

      <Track {...track} a={0} b={D} className="mt-2 h-7" />
      <div className="mt-2 text-[11px] text-ink-3">{c ? `Zoom: cycle ${c.n} (${(c.end - c.start).toFixed(1)}s)` : 'Zoom: ±10 s'}</div>
      <Track {...track} a={z[0]} b={z[1]} className="mt-1 h-10" big />
    </div>
  );
}

/** a timeline from a to b (video seconds): the elements in colour, a white tick and number where a cycle starts, the
 * position line; click or drag to seek */
export function Track({
  a,
  b,
  segs,
  cycles,
  t,
  color,
  label,
  clock: clockAt,
  onSeek,
  onScrubStart,
  onScrubEnd,
  className = '',
  big,
}: {
  a: number;
  b: number;
  segs: Seg[];
  cycles: Cycle[];
  t: number;
  color: (code: string) => string;
  label: (code: string) => string;
  clock: (s: number) => string;
  onSeek: (s: number) => void;
  onScrubStart: () => void;
  onScrubEnd: () => void;
  className?: string;
  big?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const drag = useRef(false);
  const [tip, setTip] = useState<{ x: number; text: string } | null>(null);
  const span = Math.max(0.001, b - a);
  const pct = (s: number) => `${(100 * (s - a)) / span}%`;
  const at = (e: ReactPointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return a + Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * span;
  };
  return (
    <div
      ref={ref}
      className={`relative cursor-pointer touch-none select-none rounded bg-white/[0.06] ${className}`}
      onPointerDown={(e) => {
        drag.current = true;
        onScrubStart();
        ref.current?.setPointerCapture(e.pointerId);
        onSeek(at(e));
        e.preventDefault();
      }}
      onPointerMove={(e) => {
        const s = at(e);
        const g = segs.find((x) => s >= x.a && s < x.b);
        setTip({ x: e.clientX - ref.current!.getBoundingClientRect().left, text: `${clockAt(s)}${g ? ` · ${label(g.code)}` : ''}` });
        if (drag.current) onSeek(s);
      }}
      onPointerLeave={() => setTip(null)}
      onPointerUp={() => {
        if (drag.current) onScrubEnd();
        drag.current = false;
      }}
      onPointerCancel={() => {
        drag.current = false;
      }}
    >
      {segs.map((g, i) => {
        const s0 = Math.max(a, g.a);
        const s1 = Math.min(b, g.b);
        if (s1 <= s0) return null;
        return <div key={i} className="absolute inset-y-0 border-r border-black/30" style={{ left: pct(s0), width: `${(100 * (s1 - s0)) / span}%`, background: color(g.code) }} />;
      })}
      {cycles.map((c) =>
        c.start >= a && c.start <= b ? (
          <div key={c.id} className="absolute inset-y-0 border-l-2 border-white" style={{ left: pct(c.start) }}>
            <span className={`absolute top-0 left-0.5 font-bold text-white drop-shadow-[0_0_2px_rgba(0,0,0,0.9)] ${big ? 'text-xs' : 'text-[10px]'}`}>{c.n}</span>
          </div>
        ) : null,
      )}
      {t >= a && t <= b && <div className="pointer-events-none absolute inset-y-0 w-0.5 -translate-x-1/2 bg-red-500" style={{ left: pct(t) }} />}
      {tip && (
        <div
          className="pointer-events-none absolute -top-0.5 z-10 -translate-x-1/2 -translate-y-full rounded bg-black/90 px-1.5 py-0.5 text-[10px] whitespace-nowrap text-white"
          style={{ left: tip.x }}
        >
          {tip.text}
        </div>
      )}
    </div>
  );
}
