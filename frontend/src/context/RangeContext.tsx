import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import type { RangeKey } from '../api/types';
import { readStorage, writeStorage } from '../lib/storage';

export const RANGE_OPTIONS: { key: RangeKey; label: string; title: string }[] = [
  { key: '1h', label: '1h', title: 'Last hour' },
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

  const value = useMemo<RangeCtx>(
    () => ({ range, setRange, rangeTitle: RANGE_OPTIONS.find((o) => o.key === range)?.title ?? range }),
    [range, setRange],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useRange(): RangeCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useRange must be used inside <RangeProvider>');
  return v;
}
