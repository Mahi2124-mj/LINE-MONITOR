import { api } from '../api/client';
import type { RangeKey, Shifts } from '../api/types';

const pad = (n: number) => String(n).padStart(2, '0');

/** local "YYYY-MM-DDTHH:MM" (what the report APIs and datetime inputs use) */
export const localIso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

/** start of the global time range (top bar) as a local ISO time (a shift: see rangeWindow) */
export function rangeStart(range: RangeKey): string {
  const now = new Date();
  if (range === 'today' || range === 'shiftA' || range === 'shiftB') {
    now.setHours(0, 0, 0, 0);
    return localIso(now);
  }
  const h = { '1h': 1, '24h': 24, '7d': 24 * 7, '30d': 24 * 30 }[range as '1h' | '24h' | '7d' | '30d'];
  return localIso(new Date(Date.now() - h * 3600_000));
}

let shiftCache: { at: number; data: Shifts } | null = null;

/** start and end of the global time range: a shift is its newest run (from the line's time slots: Shift A starts in the
 * morning, Shift B in the evening), the others end now */
export async function rangeWindow(range: RangeKey): Promise<{ start: string; end?: string }> {
  if (range !== 'shiftA' && range !== 'shiftB') return { start: rangeStart(range) };
  if (!shiftCache || Date.now() - shiftCache.at > 30_000) shiftCache = { at: Date.now(), data: await api.shifts() };
  const w = shiftCache.data[range === 'shiftA' ? 'A' : 'B'];
  return w ? { start: w.start.slice(0, 16), end: w.end.slice(0, 16) } : { start: rangeStart(range) };
}
