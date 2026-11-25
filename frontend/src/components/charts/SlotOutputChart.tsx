import { memo } from 'react';
import { Bar, CartesianGrid, ComposedChart, Line, Rectangle, ResponsiveContainer, Tooltip, XAxis, YAxis, type BarShapeProps } from 'recharts';
import type { SlotRow } from '../../api/types';
import { fmtNum } from '../../lib/format';
import { CHART } from '../../lib/meta';
import { AXIS_PROPS, ChartLegend, TooltipBox } from './ChartTooltip';

interface Row {
  label: string;
  output: number | null; // null = the slot has not started
  planned: number; // the slot's plan; the running slot: its plan so far
  plan: number;
  status: SlotRow['status'];
}

const BELOW = '#f43f5e';
const OK = '#38bdf8';

/** Today's output per time slot of the line (bars) vs its plan (step line), all slots of the day; a bar appears when its
 * slot has data. The selected slot is highlighted with its numbers. */
export const SlotOutputChart = memo(function SlotOutputChart({
  slots,
  selected,
  onSelect,
  height = 260,
}: {
  slots: SlotRow[];
  selected: string | null;
  onSelect: (label: string) => void;
  height?: number;
}) {
  const data: Row[] = slots.map((s) => ({
    label: s.label,
    output: s.actual,
    planned: s.status === 'running' ? Math.round(s.plan_to_now) : s.plan,
    plan: s.plan,
    status: s.status,
  }));
  const below = (r: Row) => r.output !== null && r.output < r.planned;
  return (
    <div>
      <ChartLegend
        className="mb-2"
        items={[
          { label: 'Output ≥ plan', color: OK },
          { label: 'Output < plan', color: BELOW },
          { label: 'Planned', color: CHART.planned, kind: 'dash' },
        ]}
      />
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 22, right: 12, bottom: 0, left: 0 }} barCategoryGap="18%">
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis
              dataKey="label"
              {...AXIS_PROPS}
              interval={0}
              minTickGap={0}
              tick={{ ...AXIS_PROPS.tick, fontSize: 10 }}
              tickFormatter={(v: string) => (data.length > 10 ? v.split('-')[0] : v)} // day + night shift: the slot start only
            />
            <YAxis
              {...AXIS_PROPS}
              width={48}
              allowDecimals={false}
              label={{ value: 'units / slot', angle: -90, position: 'insideLeft', offset: 14, fill: CHART.tick, fontSize: 11, dy: 30 }}
            />
            <Tooltip
              cursor={{ fill: 'rgba(148,163,184,0.06)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as Row;
                const diff = r.output !== null ? r.output - r.planned : null;
                return (
                  <TooltipBox
                    title={`${r.label}${r.status === 'running' ? ' · now' : ''}`}
                    rows={[
                      { label: 'Output', value: r.output !== null ? `${fmtNum(r.output)} units` : 'not started', color: below(r) ? BELOW : OK, emphasis: true },
                      { label: r.status === 'running' ? 'Planned so far' : 'Planned', value: `${fmtNum(r.planned)} units`, color: CHART.planned, dashed: true },
                      ...(diff !== null ? [{ label: 'Difference', value: `${diff > 0 ? '+' : ''}${fmtNum(diff)}`, tone: diff < 0 ? ('bad' as const) : ('good' as const) }] : []),
                    ]}
                  />
                );
              }}
            />
            <Bar
              dataKey="output"
              name="Output"
              fill={OK}
              isAnimationActive={false}
              cursor="pointer"
              onClick={(_: unknown, i: number) => data[i] && onSelect(data[i].label)}
              shape={(p: BarShapeProps) => {
                const r = p.payload as Row | undefined;
                if (!r || r.output === null) return <g />;
                const on = selected === r.label;
                const dim = selected !== null && !on;
                return (
                  <g>
                    <Rectangle
                      x={p.x}
                      y={p.y}
                      width={p.width}
                      height={p.height}
                      radius={[3, 3, 0, 0]}
                      fill={below(r) ? BELOW : OK}
                      fillOpacity={dim ? 0.3 : 1}
                      stroke={on ? '#ffffff' : 'none'}
                      strokeWidth={on ? 2 : 0}
                    />
                    {on && (
                      <text x={(p.x ?? 0) + (p.width ?? 0) / 2} y={(p.y ?? 0) - 6} textAnchor="middle" fontSize={11} fontWeight={700} fill="#ffffff">
                        {fmtNum(r.output)} / {fmtNum(r.planned)}
                      </text>
                    )}
                  </g>
                );
              }}
            />
            <Line dataKey="planned" name="Planned" type="step" stroke={CHART.planned} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
});
