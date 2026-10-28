import type { DecisionRow, DecisionResponse } from "../types";
import { downloadCsv, toCsv } from "../lib/csv";
import { MISSING, formatHours, formatMw, formatSignedMw, formatUtc } from "../lib/format";
import { Table, type Column } from "./Table";

/** CSV header names carry the unit, exactly like the on-screen column headers. */
const CSV_HEADERS = [
  "deliveryDate",
  "startTimeUtc",
  "startTimeLondon",
  "forecastMw",
  "publishTimeUtc",
  "horizonHours",
  "forecastAgeHoursAtCutoff",
  "lowerBoundMw",
  "upperBoundMw",
  "actualMw",
  "errorMw_F_minus_A",
  "forecastMwh",
  "flag",
] as const;

function numeric(value: number | null, digits = 1): string {
  return value === null ? "" : value.toFixed(digits);
}

export function DecisionTable({ data }: { data: DecisionResponse }) {
  const columns: Column<DecisionRow>[] = [
    {
      key: "startTimeLocal",
      header: "Delivery (London)",
      render: (row) => row.startTimeLocal,
      csv: (row) => row.startTimeLocal,
    },
    {
      key: "startTime",
      header: "Start time (UTC)",
      render: (row) => formatUtc(row.startTime, false),
      csv: (row) => row.startTime,
    },
    {
      key: "forecastMw",
      header: "Forecast MW",
      align: "right",
      title: "Forecast visible at the assumed cutoff",
      render: (row) => formatMw(row.forecastMw, 0),
      csv: (row) => numeric(row.forecastMw, 1),
    },
    {
      key: "publishTime",
      header: "Published (UTC)",
      render: (row) => formatUtc(row.publishTime),
      csv: (row) => row.publishTime ?? "",
    },
    {
      key: "horizonHours",
      header: "Horizon h",
      align: "right",
      title: "startTime − publishTime",
      render: (row) => formatHours(row.horizonHours, 1),
      csv: (row) => numeric(row.horizonHours, 2),
    },
    {
      key: "forecastAgeHours",
      header: "Forecast age at cutoff h",
      align: "right",
      title: "cutoff − publishTime",
      render: (row) => formatHours(row.forecastAgeHours, 1),
      csv: (row) => numeric(row.forecastAgeHours, 2),
    },
    {
      key: "lowerBoundMw",
      header: "Lower bound MW",
      align: "right",
      title: "max(0, F − P90(E))",
      render: (row) => formatMw(row.lowerBoundMw, 0),
      csv: (row) => numeric(row.lowerBoundMw, 1),
    },
    {
      key: "upperBoundMw",
      header: "Upper bound MW",
      align: "right",
      title: "max(0, F − P10(E))",
      render: (row) => formatMw(row.upperBoundMw, 0),
      csv: (row) => numeric(row.upperBoundMw, 1),
    },
    {
      key: "actualMw",
      header: "Actual MW",
      align: "right",
      render: (row) => formatMw(row.actualMw, 0),
      csv: (row) => numeric(row.actualMw, 1),
    },
    {
      key: "errorMw",
      header: "Error MW (F − A)",
      align: "right",
      title: "Positive means the forecast overestimated wind",
      render: (row) => formatSignedMw(row.errorMw, 0),
      csv: (row) => numeric(row.errorMw, 1),
    },
    {
      key: "flag",
      header: "Flag",
      render: (row) =>
        row.flag ? (
          <span className="text-amber-700">
            {row.flag === "missingForecast" ? "no forecast" : "no actual"}
          </span>
        ) : (
          <span className="text-slate-300">{MISSING}</span>
        ),
      csv: (row) => row.flag ?? "",
    },
  ];

  const handleExport = () => {
    const rows = data.rows.map((row) => [
      data.deliveryDate,
      row.startTime,
      row.startTimeLocal,
      numeric(row.forecastMw, 1),
      row.publishTime ?? "",
      numeric(row.horizonHours, 2),
      numeric(row.forecastAgeHours, 2),
      numeric(row.lowerBoundMw, 1),
      numeric(row.upperBoundMw, 1),
      numeric(row.actualMw, 1),
      numeric(row.errorMw, 1),
      numeric(row.forecastMwh, 2),
      row.flag ?? "",
    ]);
    downloadCsv(
      `wind-forecast-${data.deliveryDate}-cutoff-${data.cutoffLocalTime.replace(":", "")}.csv`,
      toCsv(CSV_HEADERS, rows),
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-500">
          {data.rows.length} settlement intervals · cutoff {data.cutoffLocalTime} London (
          {formatUtc(data.cutoffUtc)})
        </p>
        <button type="button" className="btn" onClick={handleExport}>
          Export CSV
        </button>
      </div>
      <Table
        columns={columns}
        rows={data.rows}
        rowKey={(row) => row.startTime}
        dense
        emptyMessage="No intervals returned for this delivery day."
      />
    </div>
  );
}
