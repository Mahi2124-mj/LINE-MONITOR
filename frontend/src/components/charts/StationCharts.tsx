import { memo, useMemo } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  Rectangle,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type BarShapeProps,
} from 'recharts';
import type { HistogramBucket, TrendPoint } from '../../api/types';
import { bucketKind, fmtAxisTime, fmtBucketTick, fmtBucketTitle, fmtDateTime, fmtNum, fmtPct, fmtSec, parseTs } from '../../lib/format';
import { BREAKDOWN, CHART } from '../../lib/meta';
import { EmptyState } from '../EmptyState';
import { AXIS_PROPS, ChartLegend, TooltipBox } from './ChartTooltip';

/* ------------------------------------------------------------------ trend */

interface TrendRow {
  t: number;
  ts: string;
  cycle: number;
  /** operator content = work + motion waste (compared with the station target) */
  content: number;
  work: number;
  motion: number;
  wait: number;
  over: boolean;
}

interface TrendProps {
  trend: TrendPoint[];
  targetSec: number;
  taktSec: number;
  mode: 'cycle' | 'breakdown';
  height?: number;
}

const CYCLE_MUTED = '#7c8797';

function refLine(y: number, label: string, color: string, dash?: string) {
  return (
    <ReferenceLine
      y={y}
      stroke={color}
      strokeDasharray={dash}
      strokeWidth={1.5}
      ifOverflow="extendDomain"
      label={{ value: label, position: 'insideTopRight', fill: color, fontSize: 11, fontWeight: 600 }}
    />
  );
}

export const CycleTrendChart = memo(function CycleTrendChart({ trend, targetSec, taktSec, mode, height = 260 }: TrendProps) {
  const data = useMemo<TrendRow[]>(
    () =>
      trend
        .map((p) => ({
          t: parseTs(p.t)?.getTime() ?? 0,
          ts: p.t,
          cycle: p.cycle_sec,
          content: p.work_sec + p.motion_waste_sec,
          work: p.work_sec,
          motion: p.motion_waste_sec,
          wait: p.wait_sec,
          over: p.work_sec + p.motion_waste_sec > targetSec,
        }))
        .sort((a, b) => a.t - b.t),
    [trend, targetSec],
  );
  if (!data.length) return <EmptyState compact title="No cycles in this range" />;
  const span = data[data.length - 1].t - data[0].t;
  const xAxis = (
    <XAxis
      dataKey="t"
      type="number"
      scale="time"
      domain={['dataMin', 'dataMax']}
      {...AXIS_PROPS}
      minTickGap={32}
      tickFormatter={(v: number) => fmtAxisTime(v, span)}
    />
  );
  const yAxis = <YAxis {...AXIS_PROPS} width={52} tickFormatter={(v: number) => `${Math.round(v)}s`} label={{ value: 'seconds', angle: -90, position: 'insideLeft', offset: 14, fill: CHART.tick, fontSize: 11, dy: 26 }} />;
  const tooltip = (
    <Tooltip
      cursor={{ stroke: '#475569', strokeDasharray: '3 3' }}
      content={({ active, payload }) => {
        if (!active || !payload?.length) return null;
        const r = payload[0].payload as TrendRow;
        return (
          <TooltipBox
            title={fmtDateTime(r.ts)}
            rows={[
              { label: 'Cycle', value: fmtSec(r.cycle), color: CYCLE_MUTED, emphasis: true },
              { label: 'Content (work + motion)', value: fmtSec(r.content), color: CHART.cycle, tone: r.over ? 'bad' : 'good' },
              { label: BREAKDOWN.work.short, value: fmtSec(r.work), color: BREAKDOWN.work.hex },
              { label: BREAKDOWN.motion.short, value: fmtSec(r.motion), color: BREAKDOWN.motion.hex },
              { label: BREAKDOWN.wait.short, value: fmtSec(r.wait), color: BREAKDOWN.wait.hex },
            ]}
          />
        );
      }}
    />
  );

  if (mode === 'breakdown') {
    return (
      <div>
        <ChartLegend
          className="mb-2"
          items={[
            { label: BREAKDOWN.work.label, color: BREAKDOWN.work.hex },
            { label: BREAKDOWN.motion.label, color: BREAKDOWN.motion.hex },
            { label: BREAKDOWN.wait.label, color: BREAKDOWN.wait.hex },
            { label: `Target ${fmtSec(targetSec)}`, color: CHART.target, kind: 'line' },
            { label: `Takt ${fmtSec(taktSec)}`, color: CHART.takt, kind: 'dash' },
          ]}
        />
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={CHART.grid} />
              {xAxis}
              {yAxis}
              {tooltip}
              <Area dataKey="work" stackId="b" type="monotone" stroke={BREAKDOWN.work.hex} fill={BREAKDOWN.work.hex} fillOpacity={0.55} strokeWidth={1} isAnimationActive={false} />
              <Area dataKey="motion" stackId="b" type="monotone" stroke={BREAKDOWN.motion.hex} fill={BREAKDOWN.motion.hex} fillOpacity={0.55} strokeWidth={1} isAnimationActive={false} />
              <Area dataKey="wait" stackId="b" type="monotone" stroke={BREAKDOWN.wait.hex} fill={BREAKDOWN.wait.hex} fillOpacity={0.45} strokeWidth={1} isAnimationActive={false} />
              {targetSec > 0 && refLine(targetSec, `Target ${fmtSec(targetSec)}`, CHART.target)}
              {taktSec > 0 && refLine(taktSec, `Takt ${fmtSec(taktSec)}`, CHART.takt, '6 4')}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    );
  }

  return (
    <div>
      <ChartLegend
        className="mb-2"
        items={[
          { label: 'Operator content (work + motion)', color: CHART.cycle, kind: 'line' },
          { label: 'Cycle time (incl. wait)', color: CYCLE_MUTED, kind: 'line' },
          { label: 'Content over target', color: CHART.over },
          { label: `Target ${fmtSec(targetSec)}`, color: CHART.target, kind: 'line' },
          { label: `Takt ${fmtSec(taktSec)}`, color: CHART.takt, kind: 'dash' },
        ]}
      />
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            {xAxis}
            {yAxis}
            {tooltip}
            {targetSec > 0 && refLine(targetSec, `Target ${fmtSec(targetSec)}`, CHART.target)}
            {taktSec > 0 && refLine(taktSec, `Takt ${fmtSec(taktSec)}`, CHART.takt, '6 4')}
            <Line dataKey="cycle" type="linear" stroke={CYCLE_MUTED} strokeWidth={1} strokeOpacity={0.7} dot={false} activeDot={false} isAnimationActive={false} />
            <Line
              dataKey="content"
              type="linear"
              stroke={CHART.cycle}
              strokeWidth={1.5}
              strokeOpacity={0.9}
              isAnimationActive={false}
              activeDot={{ r: 4, stroke: '#111419', strokeWidth: 2 }}
              dot={(p: { cx?: number; cy?: number; index?: number; payload?: TrendRow }) =>
                p.payload?.over && p.cx !== undefined && p.cy !== undefined ? (
                  <circle key={`d${p.index}`} cx={p.cx} cy={p.cy} r={2.75} fill={CHART.over} stroke="#111419" strokeWidth={1} />
                ) : (
                  <g key={`d${p.index}`} />
                )
              }
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
});

/* -------------------------------------------------------------- histogram */

interface HistRow {
  label: string;
  start: number;
  end: number;
  count: number;
  over: boolean;
}

export const CycleHistogram = memo(function CycleHistogram({ buckets, targetSec, height = 220 }: { buckets: HistogramBucket[]; targetSec: number; height?: number }) {
  const total = buckets.reduce((s, b) => s + b.count, 0);
  const data = useMemo<HistRow[]>(
    () =>
      buckets.map((b) => ({
        label: b.bucket_end - b.bucket_start < 2 ? b.bucket_start.toFixed(1) : `${Math.round(b.bucket_start)}`,
        start: b.bucket_start,
        end: b.bucket_end,
        count: b.count,
        over: b.bucket_start >= targetSec,
      })),
    [buckets, targetSec],
  );
  if (!data.length || total === 0) return <EmptyState compact title="No cycles in this range" />;
  return (
    <div>
      <ChartLegend
        className="mb-2"
        items={[
          { label: `Cycle < target (${fmtSec(targetSec)})`, color: CHART.primary },
          { label: 'Cycle ≥ target', color: CHART.over },
        ]}
      />
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} barCategoryGap={2}>
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis dataKey="label" {...AXIS_PROPS} minTickGap={8} tickFormatter={(v: string) => `${v}s`} />
            <YAxis {...AXIS_PROPS} width={40} allowDecimals={false} label={{ value: 'cycles', angle: -90, position: 'insideLeft', offset: 14, fill: CHART.tick, fontSize: 11, dy: 22 }} />
            <Tooltip
              cursor={{ fill: 'rgba(148,163,184,0.06)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as HistRow;
                return (
                  <TooltipBox
                    title={`${fmtSec(r.start)} – ${fmtSec(r.end)}`}
                    rows={[
                      { label: 'Cycles', value: fmtNum(r.count), emphasis: true, color: r.over ? CHART.over : CHART.primary },
                      { label: 'Share', value: fmtPct((r.count / total) * 100, 1) },
                    ]}
                  />
                );
              }}
            />
            <Bar
              dataKey="count"
              isAnimationActive={false}
              shape={(p: BarShapeProps) => {
                const r = p.payload as HistRow | undefined;
                return <Rectangle x={p.x} y={p.y} width={p.width} height={p.height} radius={[3, 3, 0, 0]} fill={r?.over ? CHART.over : CHART.primary} />;
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
});

/* ------------------------------------------------------------- hourly avg */

interface HourRow {
  hour: string;
  avg: number | null;
  count: number;
}

export const HourlyAvgChart = memo(function HourlyAvgChart({
  hourly,
  targetSec,
  height = 220,
}: {
  hourly: { hour: string; avg: number | null; count: number }[];
  targetSec: number;
  height?: number;
}) {
  const data: HourRow[] = hourly;
  const kind = bucketKind(data.map((d) => d.hour));
  if (!data.some((d) => d.avg !== null)) return <EmptyState compact title="No cycles in this range" />;
  const t0 = parseTs(data[0]?.hour)?.getTime() ?? 0;
  const t1 = parseTs(data[data.length - 1]?.hour)?.getTime() ?? 0;
  return (
    <div>
      <ChartLegend
        className="mb-2"
        items={[
          { label: 'Avg cycle ≤ target', color: CHART.primary },
          { label: 'Avg cycle > target', color: CHART.over },
          { label: `Target ${fmtSec(targetSec)}`, color: CHART.target, kind: 'line' },
        ]}
      />
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barCategoryGap="18%">
            <CartesianGrid vertical={false} stroke={CHART.grid} />
            <XAxis dataKey="hour" {...AXIS_PROPS} minTickGap={24} tickFormatter={(v: string) => fmtBucketTick(v, kind, t1 - t0)} />
            <YAxis {...AXIS_PROPS} width={48} tickFormatter={(v: number) => `${Math.round(v)}s`} />
            <Tooltip
              cursor={{ fill: 'rgba(148,163,184,0.06)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const r = payload[0].payload as HourRow;
                return (
                  <TooltipBox
                    title={fmtBucketTitle(r.hour, kind)}
                    rows={[
                      { label: 'Avg cycle', value: fmtSec(r.avg), emphasis: true, tone: r.avg !== null && r.avg > targetSec ? 'bad' : 'good' },
                      { label: 'Cycles', value: fmtNum(r.count) },
                    ]}
                  />
                );
              }}
            />
            {targetSec > 0 && refLine(targetSec, `Target ${fmtSec(targetSec)}`, CHART.target)}
            <Bar
              dataKey="avg"
              isAnimationActive={false}
              shape={(p: BarShapeProps) => {
                const r = p.payload as HourRow | undefined;
                return (
                  <Rectangle x={p.x} y={p.y} width={p.width} height={p.height} radius={[3, 3, 0, 0]} fill={r?.avg !== null && r?.avg !== undefined && r.avg > targetSec ? CHART.over : CHART.primary} />
                );
              }}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
});

/* ------------------------------------------------------------------ donut */

interface DonutProps {
  va: number | null;
  motion: number | null;
  wait: number | null;
  size?: number;
}

/** Value-added vs motion waste vs wait share of cycle time (percent values 0..100). */
export function BreakdownDonut({ va, motion, wait, size = 156 }: DonutProps) {
  const parts = [
    { key: 'work', value: va ?? 0, ...BREAKDOWN.work },
    { key: 'motion', value: motion ?? 0, ...BREAKDOWN.motion },
    { key: 'wait', value: wait ?? 0, ...BREAKDOWN.wait },
  ];
  const total = parts.reduce((s, p) => s + p.value, 0);
  const r = 42;
  const c = 2 * Math.PI * r;
  const gap = total > 0 ? 1.2 : 0; // surface gap between segments
  let offset = 0;
  return (
    <div className="flex items-center gap-4">
      <svg width={size} height={size} viewBox="0 0 100 100" role="img" aria-label="Cycle time breakdown">
        <circle cx={50} cy={50} r={r} fill="none" stroke="#1e232b" strokeWidth={12} />
        {total > 0 &&
          parts.map((p) => {
            const len = (p.value / total) * c;
            const seg = (
              <circle
                key={p.key}
                cx={50}
                cy={50}
                r={r}
                fill="none"
                stroke={p.hex}
                strokeWidth={12}
                strokeDasharray={`${Math.max(0, len - gap)} ${c}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 50 50)"
              >
                <title>{`${p.label}: ${fmtPct(p.value, 1)}`}</title>
              </circle>
            );
            offset += len;
            return seg;
          })}
        <text x={50} y={48} textAnchor="middle" fontSize={15} fontWeight={700} fill="#e6e9ee">
          {va === null ? '—' : `${Math.round(va)}%`}
        </text>
        <text x={50} y={60} textAnchor="middle" fontSize={7} fill="#8b94a3">
          value-added
        </text>
      </svg>
      <ul className="space-y-1.5 text-xs">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center gap-2">
            <span className="size-2.5 rounded-sm" style={{ backgroundColor: p.hex }} />
            <span className="w-28 text-ink-2">{p.label}</span>
            <span className="font-semibold text-ink tabular-nums">{fmtPct(p.value, 1)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
