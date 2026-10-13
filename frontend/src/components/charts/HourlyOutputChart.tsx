import { memo, useMemo } from 'react';
import { Bar, CartesianGrid, ComposedChart, Line, Rectangle, ResponsiveContainer, Tooltip, XAxis, YAxis, type BarShapeProps } from 'recharts';
import type { HourlyOutput } from '../../api/types';
import { bucketKind, fmtBucketTick, fmtBucketTitle, fmtNum, parseTs } from '../../lib/format';
import { CHART } from '../../lib/meta';
import { AXIS_PROPS, ChartLegend, TooltipBox } from './ChartTooltip';
import { EmptyState } from '../EmptyState';

interface Row {
  t: number;
  hour: string;
  output: number;
  planned: number;
}

const BELOW = '#f43f5e';
const OK = '#38bdf8';

/** Units per bucket (bars) vs plan (step line). Buckets are hourly (<= 48h ranges) or daily (7d/30d). Bars below plan are rose. */
export const HourlyOutputChart = memo(function HourlyOutputChart({ hourly, height = 240 }: { hourly: HourlyOutput[]; height?: number }) {
  const data = useMemo<Row[]>(
    () => hourly.map((h) => ({ t: parseTs(h.hour)?.getTime() ?? 0, hour: h.hour, output: h.output, planned: h.planned })),
    [hourly],
  );
  const kind = useMemo(() => bucketKind(hourly.map((h) => h.hour)), [hourly]);
  if (!data.length) return <EmptyState compact title="No output in this range" />;
  const span = data.length > 1 ? data[data.length - 1].t - data[0].t : 0;
  const unit = kind === 'day' ? 'units / day' : 'units / h';

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
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barCategoryGap="18%">
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis dataKey="hour" {...AXIS_PROPS} minTickGap={24} tickFormatter={(v: string) => fmtBucketTick(v, kind, span)} />
            <YAxis
              {...AXIS_PROPS}
              width={48}
              allowDecimals={false}
              label={{ value: unit, angle: -90, position: 'insideLeft', offset: 14, fill: CHART.tick, fontSize: 11, dy: 30 }}
            />
            <Tooltip
              cursor={{ fill: 'rgba(148,163,184,0.06)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as Row;
                const diff = r.output - r.planned;
                return (
                  <TooltipBox
                    title={fmtBucketTitle(r.hour, kind)}
                    rows={[
                      { label: 'Output', value: `${fmtNum(r.output)} units`, color: r.output >= r.planned ? OK : BELOW, emphasis: true },
                      { label: 'Planned', value: `${fmtNum(r.planned)} units`, color: CHART.planned, dashed: true },
                      { label: 'Difference', value: `${diff > 0 ? '+' : ''}${fmtNum(diff)}`, tone: diff < 0 ? 'bad' : 'good' },
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
              shape={(p: BarShapeProps) => {
                const r = p.payload as Row | undefined;
                return <Rectangle x={p.x} y={p.y} width={p.width} height={p.height} radius={[3, 3, 0, 0]} fill={r && r.output < r.planned ? BELOW : OK} />;
              }}
            />
            <Line dataKey="planned" name="Planned" type="step" stroke={CHART.planned} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
});
