import type { ReactNode } from 'react';

export interface TooltipRow {
  label: ReactNode;
  value: ReactNode;
  color?: string;
  /** dashed swatch for reference lines */
  dashed?: boolean;
  emphasis?: boolean;
  tone?: 'bad' | 'good';
}

/** Dark tooltip card used by all charts. */
export function TooltipBox({ title, rows, footer }: { title?: ReactNode; rows: TooltipRow[]; footer?: ReactNode }) {
  return (
    <div className="min-w-[170px] rounded-lg border border-edge-2 bg-panel-2/95 px-3 py-2 text-xs shadow-xl shadow-black/50 backdrop-blur">
      {title && <div className="mb-1.5 font-semibold text-ink">{title}</div>}
      <div className="space-y-1">
        {rows.map((r, i) => (
          <div key={i} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-ink-2">
              {r.color && (
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={r.dashed ? { border: `1.5px dashed ${r.color}` } : { backgroundColor: r.color }}
                />
              )}
              {r.label}
            </span>
            <span
              className={`tabular-nums ${r.emphasis ? 'font-semibold' : ''} ${
                r.tone === 'bad' ? 'text-rose-400' : r.tone === 'good' ? 'text-emerald-400' : 'text-ink'
              }`}
            >
              {r.value}
            </span>
          </div>
        ))}
      </div>
      {footer && <div className="mt-1.5 border-t border-edge pt-1.5 text-ink-3">{footer}</div>}
    </div>
  );
}

/** Legend row rendered in HTML above/below a chart. */
export function ChartLegend({ items, className = '' }: { items: { label: ReactNode; color: string; kind?: 'box' | 'line' | 'dash' }[]; className?: string }) {
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2 ${className}`}>
      {items.map((it, i) => (
        <span key={i} className="inline-flex items-center gap-1.5">
          {it.kind === 'line' ? (
            <span className="inline-block h-0.5 w-4 rounded" style={{ backgroundColor: it.color }} />
          ) : it.kind === 'dash' ? (
            <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: it.color }} />
          ) : (
            <span className="inline-block size-2.5 rounded-sm" style={{ backgroundColor: it.color }} />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}

export const AXIS_PROPS = {
  stroke: '#3a424d',
  tickLine: false,
  tick: { fill: '#a3acb9', fontSize: 11 },
} as const;
