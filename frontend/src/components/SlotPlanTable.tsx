import { Fragment } from 'react';
import type { SlotRow } from '../api/types';
import { fmtNum } from '../lib/format';

const SHIFT_NAME: Record<string, string> = { A: 'Shift A', B: 'Shift B' };

/** Plan vs actual per time slot of the line (actual = parts finished: the median of the last three operators), with a
 * subtotal per shift when the slots of several shifts are shown. A click on a slot selects it (its bar is highlighted in
 * the chart). */
export function SlotPlanTable({ slots, selected, onSelect }: { slots: SlotRow[]; selected?: string | null; onSelect?: (label: string) => void }) {
  const sign = (v: number) => `${v > 0 ? '+' : ''}${fmtNum(Math.round(v))}`;
  const tone = (v: number | null) => (v === null ? 'text-ink-3' : v < 0 ? 'text-red-400' : 'text-emerald-400');
  const sums = (rows: SlotRow[]) => {
    const started = rows.filter((s) => s.status !== 'future');
    return {
      plan: rows.reduce((k, s) => k + s.plan, 0),
      planToNow: started.reduce((k, s) => k + s.plan_to_now, 0),
      actual: started.reduce((k, s) => k + (s.actual ?? 0), 0),
      started: started.length,
      partly: started.length > 0 && started.length < rows.length,
    };
  };
  const groups: { shift: string; rows: SlotRow[] }[] = [];
  for (const s of slots) {
    const g = groups[groups.length - 1];
    if (g && g.shift === s.shift) g.rows.push(s);
    else groups.push({ shift: s.shift, rows: [s] });
  }
  const totalRow = (label: string, rows: SlotRow[], sub: boolean) => {
    const t = sums(rows);
    return (
      <tr className={sub ? 'border-b border-edge bg-panel-2/60 text-[13px] font-semibold' : 'font-semibold'}>
        <td className={sub ? 'py-1.5 pr-3' : 'pt-2 pr-3'}>{label}</td>
        <td className={`${sub ? 'py-1.5' : 'pt-2'} pr-3 text-right`}>
          {fmtNum(t.plan)}
          {t.partly && <span className="ml-1 text-[11px] font-normal text-ink-3">({fmtNum(Math.round(t.planToNow))} so far)</span>}
        </td>
        <td className={`${sub ? 'py-1.5' : 'pt-2'} pr-3 text-right`}>{t.started ? fmtNum(t.actual) : '—'}</td>
        <td className={`${sub ? 'py-1.5' : 'pt-2'} text-right ${tone(t.started ? t.actual - t.planToNow : null)}`}>
          {t.started ? sign(t.actual - t.planToNow) : '—'}
        </td>
      </tr>
    );
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="border-b border-edge text-left text-[11px] uppercase tracking-wide text-ink-3">
            <th className="py-2 pr-3 font-medium">Slot</th>
            <th className="py-2 pr-3 text-right font-medium">Plan</th>
            <th className="py-2 pr-3 text-right font-medium">Actual</th>
            <th className="py-2 text-right font-medium">Variance</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <Fragment key={`${g.shift}-${g.rows[0].label}`}>
              {g.rows.map((s) => (
                <tr
                  key={s.label}
                  onClick={() => onSelect?.(s.label)}
                  className={`border-b border-edge/60 ${onSelect ? 'cursor-pointer hover:bg-panel-2' : ''} ${
                    selected === s.label ? 'bg-sky-500/15 ring-1 ring-sky-500/40 ring-inset' : s.status === 'running' ? 'bg-sky-500/5' : ''
                  }`}
                >
                  <td className="py-1.5 pr-3 font-mono text-[13px]">
                    {s.label}
                    {s.status === 'running' && <span className="ml-2 rounded bg-sky-500/15 px-1.5 py-0.5 font-sans text-[10px] text-sky-300">now</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-right">
                    {fmtNum(s.plan)}
                    {s.status === 'running' && <span className="ml-1 text-[11px] text-ink-3">({fmtNum(Math.round(s.plan_to_now))} so far)</span>}
                  </td>
                  <td className={`py-1.5 pr-3 text-right ${s.actual === null ? 'text-ink-3' : 'text-ink'}`}>{s.actual === null ? '—' : fmtNum(s.actual)}</td>
                  <td className={`py-1.5 text-right font-medium ${tone(s.variance)}`}>{s.variance === null ? '—' : sign(s.variance)}</td>
                </tr>
              ))}
              {groups.length > 1 && totalRow(SHIFT_NAME[g.shift] ?? `Shift ${g.shift}`, g.rows, true)}
            </Fragment>
          ))}
        </tbody>
        <tfoot>{totalRow(groups.length === 1 && groups[0] ? (SHIFT_NAME[groups[0].shift] ?? 'Total') : 'Total', slots, false)}</tfoot>
      </table>
    </div>
  );
}
