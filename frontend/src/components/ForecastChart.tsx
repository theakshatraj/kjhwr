import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { DecisionRow } from "../types";
import { formatHours, formatMw, formatSignedMw, formatUtc } from "../lib/format";

interface BandPoint {
  label: string;
  forecastMw: number | null;
  /** Base of the stacked band: the conservative lower bound. */
  bandBase: number | null;
  /** Visible band height: upper bound − lower bound. */
  bandSpan: number | null;
  conservativeMw: number | null;
  actualMw: number | null;
  row: DecisionRow;
}

function toPoints(rows: readonly DecisionRow[]): BandPoint[] {
  return rows.map((row) => {
    const lower = row.lowerBoundMw;
    const upper = row.upperBoundMw;
    const hasBand = lower !== null && upper !== null;
    return {
      label: row.startTimeLocal,
      forecastMw: row.forecastMw,
      bandBase: hasBand ? lower : null,
      bandSpan: hasBand ? Math.max(0, upper - lower) : null,
      conservativeMw: lower,
      actualMw: row.actualMw,
      row,
    };
  });
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: Array<{ payload?: unknown }>;
}

function ChartTooltip({ active, payload }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0]?.payload as BandPoint | undefined;
  if (!point) return null;
  const { row } = point;

  const entries: Array<[string, string]> = [
    ["Forecast", formatMw(row.forecastMw, 0)],
    ["Conservative lower bound", formatMw(row.lowerBoundMw, 0)],
    ["Upper bound", formatMw(row.upperBoundMw, 0)],
    ["Actual", formatMw(row.actualMw, 0)],
    ["Error (F \u2212 A)", formatSignedMw(row.errorMw, 0)],
    ["Publish time", formatUtc(row.publishTime)],
    ["Forecast horizon", formatHours(row.horizonHours)],
    ["Forecast age at cutoff", formatHours(row.forecastAgeHours)],
  ];

  return (
    <div className="rounded-md border border-slate-200 bg-white/95 p-3 text-xs shadow-lg">
      <p className="font-semibold text-slate-800">
        Delivery {row.startTimeLocal} London ({formatUtc(row.startTime, false)})
      </p>
      <dl className="mt-1.5 grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5">
        {entries.map(([term, value]) => (
          <div key={term} className="contents">
            <dt className="text-slate-500">{term}</dt>
            <dd className="text-right font-medium tabular-nums text-slate-800">{value}</dd>
          </div>
        ))}
      </dl>
      {row.flag ? (
        <p className="mt-1.5 font-medium text-amber-700">
          Flag: {row.flag === "missingForecast" ? "no forecast at this cutoff" : "no actual"}
        </p>
      ) : null}
    </div>
  );
}

export function ForecastChart({
  rows,
  showActual,
  showBand,
}: {
  rows: readonly DecisionRow[];
  showActual: boolean;
  showBand: boolean;
}) {
  const data = toPoints(rows);

  return (
    <div className="h-[360px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
          <XAxis
            dataKey="label"
            interval={3}
            tick={{ fontSize: 11, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: "#cbd5e1" }}
          />
          <YAxis
            domain={["auto", "auto"]}
            tick={{ fontSize: 11, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: "#cbd5e1" }}
            width={64}
            tickFormatter={(value: number) => `${Math.round(value / 1000)}k`}
            label={{ value: "MW", angle: -90, position: "insideLeft", fill: "#64748b", fontSize: 11 }}
          />
          <Tooltip content={<ChartTooltip />} />

          {showBand ? (
            <>
              {/* Invisible base so the visible area spans [lower, upper]. */}
              <Area
                type="monotone"
                dataKey="bandBase"
                stackId="band"
                stroke="none"
                fill="transparent"
                isAnimationActive={false}
                legendType="none"
                name=""
              />
              <Area
                type="monotone"
                dataKey="bandSpan"
                stackId="band"
                stroke="none"
                fill="#0ea5e9"
                fillOpacity={0.18}
                isAnimationActive={false}
                name={"Lower\u2013upper band"}
              />
            </>
          ) : null}

          <Line
            type="monotone"
            dataKey="forecastMw"
            name="Forecast (visible at cutoff)"
            stroke="#0284c7"
            strokeWidth={2}
            dot={false}
            connectNulls={false}
            isAnimationActive={false}
          />
          {showBand ? (
            <Line
              type="monotone"
              dataKey="conservativeMw"
              name="Conservative wind indicator (lower bound)"
              stroke="#7c3aed"
              strokeWidth={1.75}
              strokeDasharray="5 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          ) : null}
          {showActual ? (
            <Line
              type="monotone"
              dataKey="actualMw"
              name="Actual (outturn)"
              stroke="#0f766e"
              strokeWidth={1.75}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          ) : null}

          <Legend wrapperStyle={{ fontSize: 11, color: "#475569" }} />
        </ComposedChart>
      </ResponsiveContainer>
      {showBand ? null : (
        <p className="mt-1 text-xs text-slate-500">
          No band and no conservative line: calibration is unavailable for this delivery day.
        </p>
      )}
    </div>
  );
}
