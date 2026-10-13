import { AWAY_ELEMENT, type AnalysisElement } from '../api/types';
import { fmtSec } from '../lib/format';

export const AWAY_COLOR = '#52525b';

export function elementColor(id: number, elements: AnalysisElement[]): string {
  if (id === AWAY_ELEMENT) return AWAY_COLOR;
  return elements.find((e) => e.id === id)?.color ?? '#64748b';
}

export function elementName(id: number, elements: AnalysisElement[]): string {
  if (id === AWAY_ELEMENT) return 'Operator away';
  return elements.find((e) => e.id === id)?.name ?? `Element ${id}`;
}

interface Segment {
  id: number;
  start: number;
  dur: number;
  label?: string;
}

/**
 * Horizontal element bar of one cycle (or the standard). `scale` = seconds that fill 100 % of the width,
 * so a cycle and the standard drawn with the same scale line up for comparison.
 */
export function ElementTimeline({
  segments,
  elements,
  scale,
  height = 'h-6',
  playhead,
  onSeek,
  showLabels = false,
  className = '',
}: {
  segments: Segment[];
  elements: AnalysisElement[];
  scale: number;
  height?: string;
  playhead?: number | null;
  onSeek?: (t: number) => void;
  showLabels?: boolean;
  className?: string;
}) {
  const total = Math.max(scale, 0.001);
  return (
    <div className={`relative w-full overflow-hidden rounded-md bg-panel-3/60 ${height} ${className}`}>
      {segments.map((s, i) => {
        const left = (s.start / total) * 100;
        const width = Math.max(0.4, (s.dur / total) * 100);
        const name = s.label ?? elementName(s.id, elements);
        const away = s.id === AWAY_ELEMENT;
        return (
          <button
            type="button"
            key={i}
            disabled={!onSeek}
            onClick={() => onSeek?.(s.start)}
            title={`${name}: ${fmtSec(s.start)} → ${fmtSec(s.start + s.dur)} (${fmtSec(s.dur)})`}
            className={`absolute top-0 h-full border-r border-black/40 text-left transition ${onSeek ? 'cursor-pointer hover:brightness-125' : 'cursor-default'}`}
            style={{
              left: `${left}%`,
              width: `${width}%`,
              background: away ? `repeating-linear-gradient(135deg, ${AWAY_COLOR} 0 5px, #3f3f46 5px 10px)` : elementColor(s.id, elements),
            }}
          >
            {showLabels && width > 6 && (
              <span className="block truncate px-1 text-[10px] font-semibold leading-6 text-black/80">{name}</span>
            )}
          </button>
        );
      })}
      {playhead != null && (
        <div className="pointer-events-none absolute top-0 h-full w-0.5 bg-white shadow-[0_0_4px_rgba(0,0,0,.8)]" style={{ left: `${Math.min(100, (playhead / total) * 100)}%` }} />
      )}
    </div>
  );
}

/** The standard sequence as timeline segments. */
export function standardSegments(seq: number[], durations: number[]): Segment[] {
  let t = 0;
  return seq.map((id, i) => {
    const s = { id, start: t, dur: durations[i] ?? 0 };
    t += durations[i] ?? 0;
    return s;
  });
}
