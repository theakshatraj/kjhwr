import { useQuery } from "@tanstack/react-query";

import { api, queryKeys } from "../api/client";
import { Notice } from "../components/Notice";
import { ErrorState, LoadingState, SectionCard } from "../components/States";
import { Table, type Column } from "../components/Table";
import { num, records, str } from "../lib/access";
import { MISSING, formatCount, formatHours, formatPercent, formatUtc } from "../lib/format";

interface Definition {
  term: string;
  definition: string;
}

const DEFINITIONS: Definition[] = [
  {
    term: "Error E",
    definition:
      "E = F − A (forecast minus actual). Positive means the forecast over-estimated wind; negative means it under-estimated.",
  },
  {
    term: "Forecast horizon",
    definition:
      "startTime − publishTime: how far ahead of the target settlement period the forecast was issued. Hourly in the source data.",
  },
  {
    term: "Forecast age at decision",
    definition:
      "decision cutoff − publishTime: how old the selected forecast already was when the decision was taken. A different quantity from the horizon.",
  },
  {
    term: "Settlement half-hour energy",
    definition: "MWh = MW × 0.5 for each 30-minute settlement period; the delivery day total sums those half-hours.",
  },
  {
    term: "Conservative wind indicator",
    definition:
      "Lower = max(0, F − P90(E)); Upper = max(0, F − P10(E)). Built from the pooled empirical distribution of past decision-time errors.",
  },
  {
    term: "Lower-bound coverage",
    definition:
      "Share of out-of-sample intervals where the actual outturn was at or above the lower bound. Nominally 90% (the P90 choice).",
  },
  {
    term: "Bias / MAE / RMSE",
    definition:
      "Bias = mean(F − A); MAE = mean|F − A|; RMSE = sqrt(mean((F − A)²)). MAE% is expressed against mean actual, because wind output reaches near zero.",
  },
  {
    term: "Decision cutoff",
    definition:
      "An assumption, not an official gate closure: the day before delivery at the configured local time in Europe/London.",
  },
];

const FORMULAS = [
  "E            = F − A                       # forecast error, positive = over-forecast",
  "bias         = mean(E)",
  "MAE          = mean(|E|)",
  "RMSE         = sqrt(mean(E²))",
  "Energy(MWh)  = Σ (F × 0.5)  over intervals that have a forecast",
  "lower bound  = max(0, F − P90(E))          # P90 of the pooled signed-error history",
  "upper bound  = max(0, F − P10(E))          # P10 of the pooled signed-error history",
  "horizon(h)   = (startTime − publishTime) / 1h",
  "forecast age = (cutoff − publishTime) / 1h  # at the decision instant",
].join("\n");

export default function MethodologyPage() {
  const meta = useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, retry: 0 });

  if (meta.isPending) return <LoadingState label={"Loading methodology metadata\u2026"} />;
  if (meta.isError) return <ErrorState error={meta.error} onRetry={() => void meta.refetch()} />;

  const data = meta.data;
  const provenance = data.provenance;
  const source = provenance ? (provenance as { source?: unknown }).source : null;
  const datasets = source ? records(source, "datasets") : [];
  const snapshotDate = provenance ? str(provenance, "generatedAtUtc") : null;
  const licence = source ? str(source, "licence") : null;
  const provider = source ? str(source, "provider") : null;
  const rowCounts = provenance ? (provenance as { rowCounts?: unknown }).rowCounts : null;

  const definitions: Column<Definition>[] = [
    { key: "term", header: "Term", render: (row) => <span className="font-medium">{row.term}</span> },
    { key: "definition", header: "Definition", render: (row) => row.definition },
  ];

  return (
    <div className="space-y-6">
      <Notice tone="neutral" title="Scope">
        <p>{data.snapshotNotice}</p>
        <p className="mt-1 text-xs">{data.attribution}</p>
      </Notice>

      <SectionCard title="Definitions" subtitle="Every number on the Decision and Accuracy pages uses one of these terms.">
        <Table columns={definitions} rows={DEFINITIONS} rowKey={(row) => row.term} dense />
      </SectionCard>

      <SectionCard title="Formulas" subtitle="Applied exactly as written; no hidden smoothing or gap filling.">
        <pre className="overflow-x-auto rounded-md bg-slate-900 p-3 text-xs leading-relaxed text-slate-100">
          {FORMULAS}
        </pre>
      </SectionCard>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <SectionCard title="Calibration modes">
          <dl className="space-y-3 text-sm text-slate-700">
            <div>
              <dt className="font-medium text-slate-800">decision_time (default) — strict, no look-ahead</dt>
              <dd className="mt-0.5 text-xs text-slate-600">
                Only delivery days that had fully closed before the cutoff contribute (days ≤ D − 2).
                The indicator then reflects information genuinely available at decision time. The
                block is labelled unavailable until {formatCount(data.minCalibration.days)} days and{" "}
                {formatCount(data.minCalibration.intervals)} intervals of history exist, and no
                future-data fallback is used.
              </dd>
            </div>
            <div>
              <dt className="font-medium text-slate-800">retrospective — whole month</dt>
              <dd className="mt-0.5 text-xs text-slate-600">
                Uses the whole completed month, including days after the cutoff. It describes what
                happened and is <strong>not</strong> decision-time evidence. It is intended for
                diagnosing the indicator, not for judging decision-time performance.
              </dd>
            </div>
          </dl>
          <p className="mt-3 text-xs text-slate-500">
            Available modes: {data.calibrationModes.join(", ")}. Calibration is <strong>pooled</strong>:
            every historical decision-time half-hour contributes to one error distribution, so the
            nominal coverage is an average rather than a per-interval or per-horizon guarantee.
          </p>
        </SectionCard>

        <SectionCard title="Cutoff assumption">
          <p className="text-sm text-slate-700">{data.cutoffNote}</p>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <dt className="text-slate-500">Default cutoff (local)</dt>
            <dd className="text-right font-medium tabular-nums">{data.defaultCutoffLocalTime}</dd>
            <dt className="text-slate-500">Delivery month</dt>
            <dd className="text-right font-medium tabular-nums">
              {data.deliveryMonth.start} → {data.deliveryMonth.end}
            </dd>
            <dt className="text-slate-500">Calibration warm-up</dt>
            <dd className="text-right font-medium tabular-nums">
              {data.calibrationWarmup.from} → {data.calibrationWarmup.to}
            </dd>
            <dt className="text-slate-500">Minimum history</dt>
            <dd className="text-right font-medium tabular-nums">
              {formatCount(data.minCalibration.days)} days /{" "}
              {formatCount(data.minCalibration.intervals)} intervals
            </dd>
            <dt className="text-slate-500">Actuals window</dt>
            <dd className="text-right font-medium tabular-nums">
              {str(data.window, "actualsSettlementFrom")} → {str(data.window, "actualsSettlementTo")}
            </dd>
            <dt className="text-slate-500">Forecast publish window</dt>
            <dd className="text-right font-medium tabular-nums">
              {str(data.window, "forecastPublishFrom")} → {str(data.window, "forecastPublishTo")}
            </dd>
            <dt className="text-slate-500">Observed horizons</dt>
            <dd className="text-right font-medium tabular-nums">
              {formatHours(data.horizonRangeHours.min, 1)} to{" "}
              {formatHours(data.horizonRangeHours.max, 1)}
            </dd>
          </dl>
        </SectionCard>
      </div>

      <SectionCard title="Data resolution" subtitle="Why half-hourly rows are not independent observations.">
        <p className="text-sm text-slate-700">{str(data.resolution, "note")}</p>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
          <dt className="text-slate-500">Forecast interval</dt>
          <dd className="text-right font-medium tabular-nums">
            {num(data.resolution, "forecastIntervalMinutes") ?? MISSING} min
          </dd>
          <dt className="text-slate-500">Settlement interval</dt>
          <dd className="text-right font-medium tabular-nums">
            {num(data.resolution, "settlementIntervalMinutes") ?? MISSING} min
          </dd>
          <dt className="text-slate-500">Half-hours per forecast</dt>
          <dd className="text-right font-medium tabular-nums">
            {num(data.resolution, "settlementHalfHoursPerForecastValue") ?? MISSING}
          </dd>
        </dl>
      </SectionCard>

      <SectionCard
        title="Snapshot and attribution"
        subtitle={snapshotDate ? `Snapshot generated ${formatUtc(snapshotDate)}` : undefined}
      >
        <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
          <dt className="text-slate-500">Provider</dt>
          <dd className="font-medium">{provider ?? "Elexon Insights Solution (BMRS)"}</dd>
          <dt className="text-slate-500">Licence</dt>
          <dd>{licence ?? MISSING}</dd>
          <dt className="text-slate-500">Snapshot generated (UTC)</dt>
          <dd className="font-medium tabular-nums">{formatUtc(snapshotDate)}</dd>
          <dt className="text-slate-500">Data available</dt>
          <dd className="font-medium">{data.dataAvailable ? "yes" : "no"}</dd>
        </dl>

        {rowCounts ? (
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            <dt className="text-slate-500">Raw forecast records</dt>
            <dd className="text-right font-medium tabular-nums">
              {formatCount(num(rowCounts, "rawForecastRecords"))}
            </dd>
            <dt className="text-slate-500">Raw actual records</dt>
            <dd className="text-right font-medium tabular-nums">
              {formatCount(num(rowCounts, "rawActualRecords"))}
            </dd>
            <dt className="text-slate-500">Processed forecast records</dt>
            <dd className="text-right font-medium tabular-nums">
              {formatCount(num(rowCounts, "processedForecastRecords"))}
            </dd>
            <dt className="text-slate-500">Processed actual records</dt>
            <dd className="text-right font-medium tabular-nums">
              {formatCount(num(rowCounts, "processedActualRecords"))}
            </dd>
          </dl>
        ) : null}

        {datasets.length > 0 ? (
          <div className="mt-3">
            <Table
              columns={[
                { key: "dataset", header: "Dataset", render: (row) => str(row, "dataset") ?? MISSING },
                { key: "path", header: "Endpoint", render: (row) => str(row, "path") ?? MISSING },
                { key: "note", header: "Note", render: (row) => str(row, "note") ?? MISSING },
              ]}
              rows={datasets}
              rowKey={(row) => str(row, "dataset") ?? "dataset"}
              dense
            />
          </div>
        ) : null}

        <p className="mt-3 text-xs text-slate-500">
          Coverage in the raw snapshot:{" "}
          {provenance
            ? `${formatCount(num((provenance as { coverage?: unknown }).coverage, "actualsPresentIntervals"))} of ${formatCount(num((provenance as { coverage?: unknown }).coverage, "actualsExpectedIntervals"))} expected actual intervals present (missing never zero-filled).`
            : MISSING}
        </p>
      </SectionCard>

      <SectionCard title="Limitations">
        <ul className="list-disc space-y-2 pl-5 text-sm text-slate-700">
          <li>
            <strong>Fixed historical snapshot.</strong> This is not a live trading system: it analyses
            one frozen extract of Elexon BMRS data, so nothing here reacts to new information.
          </li>
          <li>
            <strong>Empirical, pooled bounds.</strong> The indicator is estimated from historical
            error percentiles and pooled across horizons and times of day. It is not conditioned on
            horizon or wind level, so the target coverage is an average, not a per-interval guarantee.
          </li>
          <li>
            <strong>No guarantee.</strong> Coverage is validated out of sample and reported with the
            intervals and days evaluated, plus the number of days excluded for lack of prior history.
            A realised coverage near the target does not bound the error on any single interval.
          </li>
          <li>
            <strong>Hourly source, half-hourly delivery.</strong> WINDFOR publishes one value per hour;
            that value is applied to both constituent settlement half-hours without interpolation, so
            half-hourly rows repeat an hourly forecast and are not independent observations.
          </li>
          <li>
            <strong>The cutoff is an assumption.</strong> The real day-ahead auction deadline differs
            by exchange and has not been confirmed here.
          </li>
          <li>
            <strong>Not a procurement recommendation.</strong> The conservative indicator excludes
            demand and every other supply source.
          </li>
        </ul>
      </SectionCard>

      {data.knownDeviations.length > 0 ? (
        <SectionCard title="Known deviations from the brief">
          <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
            {data.knownDeviations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </SectionCard>
      ) : null}

      {data.counts ? (
        <p className="text-xs text-slate-500">
          Snapshot counts: {formatCount(num(data.counts, "forecastRecords"))} forecast records ·{" "}
          {formatCount(num(data.counts, "actualRecords"))} actual records ·{" "}
          {formatCount(num(data.counts, "forecastIntervals"))} forecast intervals ·{" "}
          {formatCount(num(data.counts, "publishVersions"))} publish versions
        </p>
      ) : null}

      <p className="text-xs text-slate-500">
        Target lower-bound coverage used throughout: {formatPercent(90, 0)} of pooled signed-error
        history (the P90 offset).
      </p>
    </div>
  );
}
