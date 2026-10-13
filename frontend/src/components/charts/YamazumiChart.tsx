import { memo, useMemo } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Rectangle,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  useXAxisScale,
  useYAxisScale,
  type BarShapeProps,
} from 'recharts';
import type { StationSummary } from '../../api/types';
import { fmtSec } from '../../lib/format';
import { BREAKDOWN, CHART } from '../../lib/meta';
import { AXIS_PROPS, ChartLegend, TooltipBox } from './ChartTooltip';

interface Row {
  key: string;
  name: string;
  sequence: number;
  work: number;
  motion: number;
  wait: number;
  content: number | null;
  cycle: number | null;
  target: number;
  bottleneck: boolean;
  count: number;
}

const SURFACE = '#111419';

/** Line balance chart: stacked operator time per station vs takt and each station's target. */
export const YamazumiChart = memo(function YamazumiChart({ stations, taktSec, height = 300 }: { stations: StationSummary[]; taktSec: number; height?: number }) {
  const data = useMemo<Row[]>(
    () =>
      [...stations]
        .sort((a, b) => a.station.sequence - b.station.sequence)
        .map((s) => ({
          key: `Step ${s.station.sequence}`,
          name: s.station.name,
          sequence: s.station.sequence,
          work: s.stats.avg_work ?? 0,
          motion: s.stats.avg_motion_waste ?? 0,
          wait: s.stats.avg_wait ?? 0,
          content: s.stats.avg_content,
          cycle: s.stats.avg,
          target: s.station.target_cycle_sec,
          bottleneck: s.is_bottleneck,
          count: s.stats.count,
        })),
    [stations],
  );

  const maxY = Math.max(taktSec, ...data.map((d) => Math.max(d.work + d.motion + d.wait, d.target))) * 1.15 || 10;

  const shape = (fill: string, top: boolean) =>
    function SegmentShape(p: BarShapeProps) {
      return (
        <Rectangle
          x={p.x}
          y={p.y}
          width={p.width}
          height={p.height}
          fill={fill}
          stroke={SURFACE}
          strokeWidth={1}
          radius={top ? [4, 4, 0, 0] : 0}
        />
      );
    };

  return (
    <div>
      <ChartLegend
        className="mb-2"
        items={[
          { label: BREAKDOWN.work.label, color: BREAKDOWN.work.hex },
          { label: BREAKDOWN.motion.label, color: BREAKDOWN.motion.hex },
          { label: BREAKDOWN.wait.label, color: BREAKDOWN.wait.hex },
          { label: `Takt ${fmtSec(taktSec)}`, color: CHART.takt, kind: 'dash' },
          { label: 'Station target', color: CHART.target, kind: 'line' },
          { label: 'Bottleneck', color: CHART.bottleneck, kind: 'line' },
        ]}
      />
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 22, right: 64, bottom: 4, left: 0 }} barCategoryGap="22%">
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis dataKey="key" {...AXIS_PROPS} interval={0} height={38} tick={<StationTick data={data} />} />
            <YAxis
              {...AXIS_PROPS}
              width={52}
              domain={[0, Math.ceil(maxY)]}
              tickFormatter={(v: number) => `${v}s`}
              label={{ value: 'seconds / cycle', angle: -90, position: 'insideLeft', offset: 12, fill: CHART.tick, fontSize: 11, dy: 50 }}
            />
            <Tooltip cursor={{ fill: 'rgba(148,163,184,0.06)' }} content={({ active, payload }) => (active && payload?.length ? <YamazumiTooltip row={payload[0].payload as Row} takt={taktSec} /> : null)} />
            <Bar dataKey="work" stackId="t" name="Work" fill={BREAKDOWN.work.hex} shape={shape(BREAKDOWN.work.hex, false)} isAnimationActive={false} />
            <Bar dataKey="motion" stackId="t" name="Motion waste" fill={BREAKDOWN.motion.hex} shape={shape(BREAKDOWN.motion.hex, false)} isAnimationActive={false} />
            <Bar dataKey="wait" stackId="t" name="Wait" fill={BREAKDOWN.wait.hex} shape={shape(BREAKDOWN.wait.hex, true)} isAnimationActive={false} />
            {taktSec > 0 && (
              <ReferenceLine
                y={taktSec}
                stroke={CHART.takt}
                strokeDasharray="6 4"
                strokeWidth={1.5}
                ifOverflow="extendDomain"
                label={{ value: `Takt ${fmtSec(taktSec)}`, position: 'right', fill: CHART.takt, fontSize: 11, fontWeight: 600 }}
              />
            )}
            <StationOverlay data={data} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
});

/** Draws per-station target ticks, bottleneck outline and the content label above each bar. */
function StationOverlay({ data }: { data: Row[] }) {
  const x = useXAxisScale();
  const y = useYAxisScale();
  if (!x || !y) return null;
  return (
    <g pointerEvents="none">
      {data.map((d) => {
        const x0 = x(d.key, { position: 'start' });
        const x1 = x(d.key, { position: 'end' });
        if (x0 === undefined || x1 === undefined) return null;
        const band = x1 - x0;
        const pad = band * 0.11; // matches barCategoryGap 22%
        const total = d.work + d.motion + d.wait;
        const yTop = y(total);
        const yBase = y(0);
        const yTarget = y(d.target);
        const cx = (x0 + x1) / 2;
        return (
          <g key={d.key}>
            {d.bottleneck && yTop !== undefined && yBase !== undefined && (
              <rect
                x={x0 + pad - 3}
                y={yTop - 3}
                width={band - pad * 2 + 6}
                height={Math.max(0, yBase - yTop) + 3}
                rx={5}
                fill="none"
                stroke={CHART.bottleneck}
                strokeWidth={2}
              />
            )}
            {yTarget !== undefined && (
              <line x1={x0 + pad - 6} x2={x1 - pad + 6} y1={yTarget} y2={yTarget} stroke={CHART.target} strokeWidth={2} strokeLinecap="round" />
            )}
            {yTop !== undefined && d.content !== null && (
              <text x={cx} y={yTop - 7} textAnchor="middle" fontSize={11} fontWeight={600} fill={d.bottleneck ? '#fca5a5' : '#e6e9ee'}>
                {fmtSec(d.content)}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
}

interface TickProps {
  x?: number;
  y?: number;
  payload?: { value: string };
  data: Row[];
}

function StationTick({ x = 0, y = 0, payload, data }: TickProps) {
  const row = data.find((d) => d.key === payload?.value);
  const name = row?.name ?? '';
  const short = name.length > 16 ? `${name.slice(0, 15)}…` : name;
  return (
    <g transform={`translate(${x},${y})`}>
      <text dy={12} textAnchor="middle" fontSize={11} fontWeight={600} fill={row?.bottleneck ? '#fca5a5' : '#e6e9ee'}>
        {payload?.value}
      </text>
      <text dy={26} textAnchor="middle" fontSize={10} fill="#8b94a3">
        {short}
      </text>
    </g>
  );
}

function YamazumiTooltip({ row, takt }: { row: Row; takt: number }) {
  const total = row.work + row.motion + row.wait;
  return (
    <TooltipBox
      title={
        <span>
          {row.key} · {row.name}
          {row.bottleneck && <span className="ml-1.5 text-red-400">(bottleneck)</span>}
        </span>
      }
      rows={[
        { label: BREAKDOWN.work.short, value: fmtSec(row.work), color: BREAKDOWN.work.hex },
        { label: BREAKDOWN.motion.short, value: fmtSec(row.motion), color: BREAKDOWN.motion.hex },
        { label: BREAKDOWN.wait.short, value: fmtSec(row.wait), color: BREAKDOWN.wait.hex },
        { label: 'Operator content', value: fmtSec(row.content), emphasis: true, tone: row.content !== null && takt > 0 && row.content > takt ? 'bad' : undefined },
        { label: 'Avg cycle', value: fmtSec(row.cycle ?? total) },
        { label: 'Target', value: fmtSec(row.target), color: CHART.target },
        { label: 'Takt', value: fmtSec(takt), color: CHART.takt, dashed: true },
      ]}
      footer={`${row.count.toLocaleString()} cycles`}
    />
  );
}
