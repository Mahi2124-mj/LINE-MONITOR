import type { ReactNode } from 'react';
import { RANGE_OPTIONS, useRange } from '../context/RangeContext';

export function RangeSelector({ className = '' }: { className?: string }) {
  const { range, setRange } = useRange();
  return (
    <div role="radiogroup" aria-label="Time range" className={`inline-flex rounded-lg border border-edge bg-canvas p-0.5 ${className}`}>
      {RANGE_OPTIONS.map((o) => {
        const active = o.key === range;
        return (
          <button
            key={o.key}
            type="button"
            role="radio"
            aria-checked={active}
            title={o.title}
            onClick={() => setRange(o.key)}
            className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
              active ? 'bg-panel-3 text-ink shadow-sm ring-1 ring-edge-2' : 'text-ink-3 hover:text-ink'
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Generic segmented control used for local toggles. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className = '',
  size = 'sm',
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; title?: string }[];
  className?: string;
  size?: 'xs' | 'sm';
}) {
  return (
    <div className={`inline-flex rounded-lg border border-edge bg-canvas p-0.5 ${className}`}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          title={o.title}
          onClick={() => onChange(o.value)}
          className={`inline-flex items-center gap-1 rounded-md font-medium transition ${size === 'xs' ? 'px-2 py-0.5 text-[11px]' : 'px-2.5 py-1 text-xs'} ${
            o.value === value ? 'bg-panel-3 text-ink ring-1 ring-edge-2' : 'text-ink-3 hover:text-ink'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
