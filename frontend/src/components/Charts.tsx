import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatCount, formatMw } from "../lib/format";

const AXIS = { fontSize: 11, fill: "#64748b" } as const;
const MAE_COLOR = "#0284c7";
const BIAS_COLOR = "#f59e0b";

export interface HourPoint {
  hour: number;
  maeMw: number | null;
  biasMw: number | null;
  n: number | null;
}

export interface DayPoint {
  deliveryDate: string;
  maeMw: number | null;
  biasMw: number | null;
  n: number | null;
}

export function MaeByHourChart({ points }: { points: readonly HourPoint[] }) {
  const data = points.map((point) => ({
    label: `${String(point.hour).padStart(2, "0")}:00`,
    maeMw: point.maeMw,
    biasMw: point.biasMw,
    n: point.n,
  }));

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} interval={2} />
          <YAxis
            tick={AXIS}
            tickLine={false}
            width={60}
            tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}
          />
          <Tooltip
            formatter={(value: number, name: string) => formatMw(value, 0) + ` (${name})`}
            labelFormatter={(label: string) => `London hour ${label}`}
          />
          <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="4 3" />
          <Bar
            dataKey="maeMw"
            name="MAE"
            fill={MAE_COLOR}
            fillOpacity={0.75}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="biasMw"
            name="Bias (F − A)"
            stroke={BIAS_COLOR}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MaeByDayChart({ points }: { points: readonly DayPoint[] }) {
  const data = points.map((point) => ({
    label: point.deliveryDate.slice(5),
    fullDate: point.deliveryDate,
    maeMw: point.maeMw,
    biasMw: point.biasMw,
    n: point.n,
  }));

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} interval={2} />
          <YAxis
            tick={AXIS}
            tickLine={false}
            width={60}
            tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}
          />
          <Tooltip
            formatter={(value: number, name: string) => formatMw(value, 0) + ` (${name})`}
            labelFormatter={(label: string) => `Delivery day 2026-${label}`}
          />
          <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="4 3" />
          <Bar
            dataKey="maeMw"
            name="MAE"
            fill={MAE_COLOR}
            fillOpacity={0.75}
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="biasMw"
            name="Bias (F − A)"
            stroke={BIAS_COLOR}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Signed-error histogram. Bars left of 0 are under-forecasts, right of 0 over. */
export function SignedErrorHistogram({
  binEdgesMw,
  counts,
}: {
  binEdgesMw: readonly number[];
  counts: readonly number[];
}) {
  const data = counts.map((count, index) => {
    const low = binEdgesMw[index] ?? 0;
    const high = binEdgesMw[index + 1] ?? low;
    const center = (low + high) / 2;
    return {
      label: `${Math.round(center / 1000)}k`,
      center,
      count,
      side: center >= 0 ? "over" : "under",
      range: `${Math.round(low)} to ${Math.round(high)} MW`,
    };
  });

  if (data.length === 0) {
    return <p className="p-4 text-sm text-slate-500">No errors to bin for this window.</p>;
  }

  // Anchor the zero reference to the bin whose centre is closest to zero.
  const zeroLabel = data.reduce((best, point) =>
    Math.abs(point.center) < Math.abs(best.center) ? point : best,
  ).label;

  return (
    <div className="h-72 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis dataKey="label" tick={AXIS} tickLine={false} interval={4} />
          <YAxis tick={AXIS} tickLine={false} width={56} />
          <Tooltip
            formatter={(value: number) => [`${formatCount(value)} intervals`, "count"]}
            labelFormatter={(_label: string, payload) => {
              const point = payload?.[0]?.payload as { range?: string } | undefined;
              return point?.range ? `Error ${point.range}` : "Error bin";
            }}
          />
          <ReferenceLine x={zeroLabel} stroke="#94a3b8" strokeDasharray="4 3" />
          <Bar dataKey="count" name="Intervals" isAnimationActive={false}>
            {data.map((point) => (
              <Cell key={point.center} fill={point.side === "over" ? "#f59e0b" : "#0284c7"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="mt-1 text-xs text-slate-500">
        Amber bars are over-forecasts (F &gt; A); blue bars are under-forecasts (F &lt; A).
      </p>
    </div>
  );
}
