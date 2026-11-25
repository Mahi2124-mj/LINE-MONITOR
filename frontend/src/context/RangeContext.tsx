import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api } from '../api/client';
import type { RangeKey } from '../api/types';
import { readStorage, writeStorage } from '../lib/storage';

export const RANGE_OPTIONS: { key: RangeKey; label: string; title: string }[] = [
  { key: '1h', label: '1h', title: 'Last hour' },
  { key: 'shiftA', label: 'Shift A', title: 'Shift A' },
  { key: 'shiftB', label: 'Shift B', title: 'Shift B' },
  { key: 'today', label: 'Today', title: 'Since midnight' },
  { key: '24h', label: '24h', title: 'Last 24 hours' },
  { key: '7d', label: '7d', title: 'Last 7 days' },
  { key: '30d', label: '30d', title: 'Last 30 days' },
];

const STORAGE_KEY = 'lm.range';
const DEFAULT_RANGE: RangeKey = '24h';

function isRangeKey(v: string | null): v is RangeKey {
  return RANGE_OPTIONS.some((o) => o.key === v);
}

interface RangeCtx {
  range: RangeKey;
  setRange: (r: RangeKey) => void;
  rangeTitle: string;
  options: typeof RANGE_OPTIONS; // Shift A / B only when the lines have shifts (and the server knows them)
}

const Ctx = createContext<RangeCtx | null>(null);

export function RangeProvider({ children }: { children: ReactNode }) {
  const [range, setRangeState] = useState<RangeKey>(() => {
    const stored = readStorage(STORAGE_KEY);
    return isRangeKey(stored) ? stored : DEFAULT_RANGE;
  });

  const setRange = useCallback((r: RangeKey) => {
    setRangeState(r);
    writeStorage(STORAGE_KEY, r);
  }, []);

  const [shifts, setShifts] = useState<boolean | null>(null);
  useEffect(() => {
    api
      .shifts()
      .then((d) => setShifts(!!(d.A || d.B)))
      .catch(() => setShifts(false));
  }, []);
  const options = useMemo(() => RANGE_OPTIONS.filter((o) => shifts || (o.key !== 'shiftA' && o.key !== 'shiftB')), [shifts]);
  const shown = shifts === false && (range === 'shiftA' || range === 'shiftB') ? DEFAULT_RANGE : range;

  const value = useMemo<RangeCtx>(
    () => ({ range: shown, setRange, rangeTitle: RANGE_OPTIONS.find((o) => o.key === shown)?.title ?? shown, options }),
    [shown, setRange, options],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRange(): RangeCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useRange must be used inside <RangeProvider>');
  return v;
}
