import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  CALIBRATION_MODES,
  MODE_LABELS,
  api,
  queryKeys,
  type AccuracyWindowQuery,
  type CalibrationMode,
} from "../api/client";
import { MaeByDayChart, MaeByHourChart, SignedErrorHistogram } from "../components/Charts";
import { Badge, KpiCard } from "../components/KpiCard";
import { ModeToggle } from "../components/ModeToggle";
import { Notice } from "../components/Notice";
import { EmptyState, ErrorState, LoadingState, SectionCard } from "../components/States";
import { Table } from "../components/Table";
import { num, record, records, str, strings } from "../lib/access";
import {
  MISSING,
  formatCount,
  formatFraction,
  formatMw,
  formatPercent,
  formatSignedMw,
} from "../lib/format";
import type { HorizonBucket } from "../types";

const MONTH_FROM = "2026-01-01";
const MONTH_TO = "2026-01-31";

const SIGNED_PERCENTILES = ["p5", "p10", "p50", "p90", "p95"] as const;
const ABSOLUTE_PERCENTILES = ["p50", "p90"] as const;

interface PercentileRow {
  key: string;
  label: string;
  value: number | null;
  meaning: string;
}

function buildPercentileRows(block: unknown): PercentileRow[] {
  return SIGNED_PERCENTILES.map((key) => {
    const value = num(block, key);
    const meaning =
      value === null
        ? MISSING
        : value >= 0
          ? "over-forecast"
          : "under-forecast";
    return { key, label: key.toUpperCase(), value, meaning };
  });
}

function coverageTone(value: number | null, target: number | null): "ok" | "warn" | "neutral" {
  if (value === null || target === null) return "neutral";
  return value + 0.05 >= target ? "ok" : "warn";
}

export default function AccuracyPage() {
  const [mode, setMode] = useState<CalibrationMode>(CALIBRATION_MODES.decisionTime);
  const [cutoff, setCutoff] = useState("09:00");
  const [from, setFrom] = useState(MONTH_FROM);
  const [to, setTo] = useState(MONTH_TO);

  const windowQuery: AccuracyWindowQuery = { mode, cutoff, from, to };

  const meta = useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, retry: 0 });
  const summaryQuery = useQuery({
    queryKey: queryKeys.accuracySummary(windowQuery),
    queryFn: () => api.accuracySummary(windowQuery),
  });
  const byHourQuery = useQuery({
    queryKey: queryKeys.accuracyByHour(windowQuery),
    queryFn: () => api.accuracyByHour(windowQuery),
  });
  const dailyQuery = useQuery({
    queryKey: queryKeys.accuracyDaily(windowQuery),
    queryFn: () => api.accuracyDaily(windowQuery),
  });
  const distributionQuery = useQuery({
    queryKey: queryKeys.accuracyDistribution(windowQuery),
    queryFn: () => api.accuracyDistribution(windowQuery),
  });
  const horizonQuery = useQuery({
    queryKey: queryKeys.accuracyByHorizon(mode),
    queryFn: api.accuracyByHorizon,
  });

  const summary = summaryQuery.data ?? null;
  const decisionTime = summary ? record(summary, "decisionTime") : null;
  const nativeHourly = summary ? record(summary, "nativeHourly") : null;
  const coverage = summary ? record(summary, "coverage") : null;
  const coverageByHorizon = summary ? record(summary, "coverageByHorizon") : null;
  const signedBlock = record(decisionTime, "signedErrorPercentilesMw");
  const absoluteBlock = record(decisionTime, "absoluteErrorPercentilesMw");

  const n = summary ? num(decisionTime, "n") : null;
  const nDays = summary ? summary.counts.nDays ?? null : null;
  const bias = summary ? num(decisionTime, "biasMw") : null;
  const mae = summary ? num(decisionTime, "maeMw") : null;
  const rmse = summary ? num(decisionTime, "rmseMw") : null;
  const maePct = summary ? num(decisionTime, "maePctOfMeanActual") : null;
  const meanActual = summary ? num(decisionTime, "meanActualMw") : null;

  const percentileRows = buildPercentileRows(signedBlock);

  const hourPoints = (byHourQuery.data?.series ?? []).map((item) => ({
    hour: num(item, "hour") ?? 0,
    maeMw: num(item, "maeMw"),
    biasMw: num(item, "biasMw"),
    n: num(item, "n"),
  }));

  const dayPoints = (dailyQuery.data?.series ?? []).map((item) => ({
    deliveryDate: str(item, "deliveryDate") ?? "",
    maeMw: num(item, "maeMw"),
    biasMw: num(item, "biasMw"),
    n: num(item, "n"),
  }));

  const histogram = distributionQuery.data?.histogram ?? {};
  const binEdgesMw = (histogram as { binEdgesMw?: number[] }).binEdgesMw ?? [];
  const counts = (histogram as { counts?: number[] }).counts ?? [];
  const histogramN = num(histogram, "n");

  const horizon = horizonQuery.data ?? null;
  const horizonPoints = horizon?.buckets ?? [];

  const worstMaeBucket = horizonPoints.reduce<HorizonBucket | null>((worst, bucket) => {
    const value = num(bucket.metrics, "maeMw");
    if (value === null) return worst;
    const best = worst ? num(worst.metrics, "maeMw") : null;
    return best === null || value > best ? bucket : worst;
  }, null);
  const bestMaeBucket = horizonPoints.reduce<HorizonBucket | null>((best, bucket) => {
    const value = num(bucket.metrics, "maeMw");
    if (value === null) return best;
    const current = best ? num(best.metrics, "maeMw") : null;
    return current === null || value < current ? bucket : best;
  }, null);

  const maeRange =
    bestMaeBucket && worstMaeBucket
      ? `MAE ranges from ${formatMw(num(bestMaeBucket.metrics, "maeMw"), 0)} in the ${bestMaeBucket.horizonBucket} bucket to ${formatMw(num(worstMaeBucket.metrics, "maeMw"), 0)} in the ${worstMaeBucket.horizonBucket} bucket.`
      : "No lead-time buckets have scored records.";

  const coverageValue = num(coverage, "lowerBoundCoverage");
  const bandValue = num(coverage, "bandCoverage");
  const coverageTarget = num(coverage, "target");
  const coverageDays = num(coverage, "nDays");
  const coverageIntervals = num(coverage, "nIntervals");
  const excludedDays = coverage ? strings(coverage, "excludedDays") : [];
  const coverageSpread = num(coverageByHorizon, "coverageSpread");
  const materialVariation = coverageByHorizon ? coverageByHorizon.materialVariation : null;

  const coverageCaption = (() => {
    if (coverageValue === null) return "No evaluable intervals in this window.";
    const target = coverageTarget === null ? null : formatFraction(coverageTarget, 0);
    const actual = formatFraction(coverageValue, 1);
    return `Lower bound covered the actual in ${actual} of out-of-sample intervals (target ${target ?? MISSING}), evaluated over ${formatCount(coverageIntervals)} interval(s) on ${formatCount(coverageDays)} day(s).`;
  })();

  const groupRows = coverageByHorizon ? records(coverageByHorizon, "groups") : [];
  const spreadCaption = (() => {
    if (coverageSpread === null) return "Coverage by horizon group is not available.";
    const spread = formatFraction(coverageSpread, 1);
    const drift =
      materialVariation === true
        ? "Coverage varies materially across horizon groups"
        : "Coverage does not vary materially across horizon groups";
    return `${drift} (spread ${spread} percentage points). The pooled bound is not conditioned on horizon, so this spread is the honest measure of how well the average holds per group.`;
  })();

  const controls = (
    <section className="card">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
        <div>
          <label className="field-label" htmlFor="window-from">
            Delivery days from
          </label>
          <input
            id="window-from"
            type="date"
            className="input"
            value={from}
            min={MONTH_FROM}
            max={MONTH_TO}
            onChange={(event) => event.target.value && setFrom(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="window-to">
            Delivery days to
          </label>
          <input
            id="window-to"
            type="date"
            className="input"
            value={to}
            min={MONTH_FROM}
            max={MONTH_TO}
            onChange={(event) => event.target.value && setTo(event.target.value)}
          />
        </div>
        <div>
          <label className="field-label" htmlFor="accuracy-cutoff">
            Assumed decision cutoff (editable)
          </label>
          <input
            id="accuracy-cutoff"
            type="time"
            className="input"
            value={cutoff}
            step={60}
            onChange={(event) => event.target.value && setCutoff(event.target.value)}
          />
        </div>
        <div>
          <span className="field-label">Calibration mode</span>
          <ModeToggle mode={mode} onChange={setMode} />
        </div>
      </div>
      {summary ? (
        <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500">
          Window {summary.window.from} → {summary.window.to} · dataset {summary.dataset} · cutoff{" "}
          {summary.cutoffLocalTime} London ·{" "}
          {summary.calibration.available
            ? `${MODE_LABELS[mode]} with ${formatCount(summary.calibration.nIntervals)} calibration intervals`
            : `calibration unavailable (${summary.calibration.reason ?? "insufficient calibration history"})`}
        </p>
      ) : null}
    </section>
  );

  return (
    <div className="space-y-6">
      {controls}

      {mode === CALIBRATION_MODES.retrospective ? (
        <Notice tone="warn" title="Retrospective mode">
          Retrospective uses the whole completed month, including days that closed after the
          delivery day's cutoff. It describes what happened and is <strong>not</strong> decision-time
          evidence.
        </Notice>
      ) : null}

      {summaryQuery.isPending ? <LoadingState label={"Loading accuracy metrics\u2026"} /> : null}
      {summaryQuery.isError ? (
        <ErrorState error={summaryQuery.error} onRetry={() => void summaryQuery.refetch()} />
      ) : null}

      {summary && !summary.calibration.available ? (
        <Notice tone="warn" title="Insufficient calibration history">
          The conservative bound is not shown for this window: {summary.calibration.reason ?? "insufficient calibration history"}.
          Eligible history: {formatCount(summary.calibration.nDays)} day(s),{" "}
          {formatCount(summary.calibration.nIntervals)} interval(s).
        </Notice>
      ) : null}

      {summary ? (
        <>
          <SectionCard
            title="Decision-time error headline"
            subtitle={coverageCaption}
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KpiCard
                label="Bias (mean signed error)"
                value={formatSignedMw(bias, 0)}
                tone={bias !== null && bias > 0 ? "warn" : "default"}
                badge={<Badge tone="neutral">n = {formatCount(n)}</Badge>}
                sub="F − A; positive means the forecast over-predicted wind"
              />
              <KpiCard
                label="MAE"
                value={formatMw(mae, 0)}
                badge={<Badge tone="neutral">n = {formatCount(n)}</Badge>}
                sub={`absolute error, mean actual ${formatMw(meanActual, 0)}`}
              />
              <KpiCard
                label="RMSE"
                value={formatMw(rmse, 0)}
                badge={<Badge tone="neutral">n = {formatCount(n)}</Badge>}
                sub="root mean squared error"
              />
              <KpiCard
                label="MAE as % of mean actual"
                value={formatPercent(maePct, 1)}
                badge={<Badge tone="neutral">n = {formatCount(n)}</Badge>}
                sub="wind output reaches near zero, so this is against the mean"
              />
            </div>

            <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Signed-error percentiles (MW, F − A)
                </h3>
                <p className="mb-2 mt-0.5 text-xs text-slate-500">
                  Pooled across {formatCount(n)} scored intervals on {formatCount(nDays)} day(s);
                  these percentiles build the conservative indicator, so the sign matters.
                </p>
                <Table
                  columns={[
                    { key: "label", header: "Percentile", render: (row: PercentileRow) => row.label },
                    {
                      key: "value",
                      header: "Error MW",
                      align: "right",
                      render: (row: PercentileRow) => formatSignedMw(row.value, 0),
                    },
                    {
                      key: "meaning",
                      header: "Direction",
                      render: (row: PercentileRow) => row.meaning,
                    },
                  ]}
                  rows={percentileRows}
                  rowKey={(row) => row.key}
                  dense
                />
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Absolute-error percentiles (MW)
                </h3>
                <p className="mb-2 mt-0.5 text-xs text-slate-500">
                  Kept separate from the signed family: a bias of zero does not mean small errors.
                </p>
                <Table
                  columns={[
                    { key: "label", header: "Percentile", render: (row: PercentileRow) => row.label },
                    {
                      key: "value",
                      header: "|Error| MW",
                      align: "right",
                      render: (row: PercentileRow) => formatMw(row.value, 0),
                    },
                  ]}
                  rows={ABSOLUTE_PERCENTILES.map((key) => ({
                    key,
                    label: key.toUpperCase(),
                    value: num(absoluteBlock, key),
                    meaning: "",
                  }))}
                  rowKey={(row) => row.key}
                  dense
                />
              </div>
            </div>

            <div className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Resolution comparison
              </h3>
              <p className="mt-0.5 text-xs text-slate-500">
                The half-hourly grid repeats each hourly forecast twice. Collapsing to the native
                hourly resolution gives the independent sample: {formatCount(summary.counts.nHalfHours)}{" "}
                half-hour rows contain {formatCount(summary.counts.nForecastIntervals)} distinct
                forecast intervals.
              </p>
              <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
                <KpiCard
                  label="Half-hourly MAE"
                  value={formatMw(mae, 0)}
                  sub={`n = ${formatCount(n)} display rows`}
                />
                <KpiCard
                  label="Native hourly MAE"
                  value={formatMw(num(nativeHourly, "maeMw"), 0)}
                  sub={`n = ${formatCount(num(nativeHourly, "n"))} independent intervals`}
                />
                <KpiCard
                  label="Native hourly bias"
                  value={formatSignedMw(num(nativeHourly, "biasMw"), 0)}
                  sub="one observation per forecast interval"
                />
              </div>
              {str(nativeHourly, "note") ? (
                <p className="mt-2 text-xs text-slate-500">{str(nativeHourly, "note")}</p>
              ) : null}
            </div>
          </SectionCard>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <SectionCard title="Error by hour of day" subtitle="Bias line against MAE bars, London local hours.">
              {byHourQuery.isPending ? <LoadingState /> : null}
              {byHourQuery.isError ? (
                <ErrorState error={byHourQuery.error} onRetry={() => void byHourQuery.refetch()} />
              ) : null}
              {byHourQuery.data && hourPoints.length > 0 ? (
                <MaeByHourChart points={hourPoints} />
              ) : byHourQuery.data ? (
                <EmptyState title="No hourly breakdown for this window" />
              ) : null}
            </SectionCard>

            <SectionCard title="Daily MAE" subtitle="One bar per delivery day, with the day's bias as a line.">
              {dailyQuery.isPending ? <LoadingState /> : null}
              {dailyQuery.isError ? (
                <ErrorState error={dailyQuery.error} onRetry={() => void dailyQuery.refetch()} />
              ) : null}
              {dailyQuery.data && dayPoints.length > 0 ? (
                <MaeByDayChart points={dayPoints} />
              ) : dailyQuery.data ? (
                <EmptyState title="No daily breakdown for this window" />
              ) : null}
            </SectionCard>
          </div>

          <SectionCard
            title="Signed-error distribution"
            subtitle={
              histogramN !== null
                ? `Histogram of F − A over ${formatCount(histogramN)} scored intervals.`
                : "Histogram of F − A."
            }
          >
            {distributionQuery.isPending ? <LoadingState /> : null}
            {distributionQuery.isError ? (
              <ErrorState
                error={distributionQuery.error}
                onRetry={() => void distributionQuery.refetch()}
              />
            ) : null}
            {distributionQuery.data ? (
              counts.length > 0 ? (
                <SignedErrorHistogram binEdgesMw={binEdgesMw} counts={counts} />
              ) : (
                <EmptyState title="No errors to bin for this window" />
              )
            ) : null}
          </SectionCard>

          <SectionCard
            title="Out-of-sample coverage of the conservative bound"
            subtitle={coverageCaption}
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <KpiCard
                label="Lower-bound coverage"
                value={formatFraction(coverageValue, 1)}
                badge={
                  <Badge tone={coverageTone(coverageValue, coverageTarget)}>
                    target {formatFraction(coverageTarget, 0)}
                  </Badge>
                }
                sub="share of intervals with actual ≥ lower bound"
              />
              <KpiCard
                label="Band coverage"
                value={formatFraction(bandValue, 1)}
                sub="share of intervals with lower ≤ actual ≤ upper"
              />
              <KpiCard
                label="Intervals evaluated"
                value={formatCount(coverageIntervals)}
                sub="out-of-sample only (never the calibration sample)"
              />
              <KpiCard
                label="Days evaluated"
                value={formatCount(coverageDays)}
                sub={
                  excludedDays.length > 0
                    ? `${formatCount(excludedDays.length)} day(s) excluded (insufficient prior history)`
                    : "no days excluded (insufficient prior history)"
                }
              />
            </div>
            {str(coverage, "note") ? (
              <p className="mt-3 text-xs text-slate-500">{str(coverage, "note")}</p>
            ) : null}

            <h3 className="mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Coverage by horizon group
            </h3>
            <p className="mb-2 mt-0.5 text-xs text-slate-500">{spreadCaption}</p>
            {groupRows.length > 0 ? (
              <Table
                columns={[
                  {
                    key: "horizonBucket",
                    header: "Horizon bucket",
                    render: (row) => str(row, "horizonBucket") ?? MISSING,
                  },
                  {
                    key: "nIntervals",
                    header: "Intervals",
                    align: "right",
                    render: (row) => formatCount(num(row, "nIntervals")),
                  },
                  {
                    key: "nDays",
                    header: "Days",
                    align: "right",
                    render: (row) => formatCount(num(row, "nDays")),
                  },
                  {
                    key: "coverage",
                    header: "Lower-bound coverage",
                    align: "right",
                    render: (row) => formatFraction(num(row, "lowerBoundCoverage"), 1),
                  },
                ]}
                rows={groupRows}
                rowKey={(row, index) => `${str(row, "horizonBucket") ?? "bucket"}-${index}`}
                dense
              />
            ) : (
              <EmptyState title="No horizon-group coverage for this window" />
            )}
          </SectionCard>
        </>
      ) : null}

      <SectionCard
        title="Comparison across forecast lead times"
        subtitle="Lead-time comparison only: several forecast vintages share one target hour and are correlated, so the unique interval count is the independent sample."
      >
        {horizonQuery.isPending ? <LoadingState /> : null}
        {horizonQuery.isError ? (
          <ErrorState error={horizonQuery.error} onRetry={() => void horizonQuery.refetch()} />
        ) : null}
        {horizon ? (
          horizonPoints.length > 0 ? (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <KpiCard
                  label="Records scored"
                  value={formatCount(horizon.totalRecords - horizon.excludedRecords)}
                  sub={`of ${formatCount(horizon.totalRecords)} records in the all-vintages dataset`}
                />
                <KpiCard
                  label="Excluded (horizon ≤ 0)"
                  value={formatCount(horizon.excludedRecords)}
                  tone={horizon.excludedRecords > 0 ? "warn" : "default"}
                  sub={
                    horizon.excludedHorizonRangeHours
                      ? `horizons ${horizon.excludedHorizonRangeHours.min} h to ${horizon.excludedHorizonRangeHours.max} h; ran at or after their target time`
                      : "none published at or after their target time"
                  }
                />
                <KpiCard
                  label="Horizon timestamp mismatches"
                  value={formatCount(horizon.horizonInconsistentRecords)}
                  sub="horizonHours disagreeing with startTime − publishTime"
                />
                <KpiCard
                  label="Observed horizons"
                  value={`${num(horizon.observedHorizonHours, "min") ?? MISSING}–${num(horizon.observedHorizonHours, "max") ?? MISSING} h`}
                  sub={`median ${num(horizon.observedHorizonHours, "median") ?? MISSING} h over ${formatCount(num(horizon.observedHorizonHours, "n"))} vintages`}
                />
              </div>

              <p className="mt-3 text-xs text-slate-500">{maeRange}</p>

              <div className="mt-3">
                <Table
                  columns={[
                    {
                      key: "horizonBucket",
                      header: "Horizon bucket",
                      render: (row) => row.horizonBucket,
                    },
                    {
                      key: "recordCount",
                      header: "Records",
                      align: "right",
                      title: "Vintages scored (correlated within a target hour)",
                      render: (row) => formatCount(row.recordCount),
                    },
                    {
                      key: "uniqueIntervalCount",
                      header: "Unique intervals",
                      align: "right",
                      title: "Distinct target hours - the independent sample",
                      render: (row) => formatCount(row.uniqueIntervalCount),
                    },
                    {
                      key: "biasMw",
                      header: "Bias MW",
                      align: "right",
                      render: (row) => formatSignedMw(num(row.metrics, "biasMw"), 0),
                    },
                    {
                      key: "maeMw",
                      header: "MAE MW",
                      align: "right",
                      render: (row) => formatMw(num(row.metrics, "maeMw"), 0),
                    },
                    {
                      key: "rmseMw",
                      header: "RMSE MW",
                      align: "right",
                      render: (row) => formatMw(num(row.metrics, "rmseMw"), 0),
                    },
                  ]}
                  rows={horizonPoints}
                  rowKey={(row) => row.horizonBucket}
                  dense
                />
              </div>
              <p className="mt-2 text-xs text-slate-500">{horizon.note}</p>
            </>
          ) : (
            <EmptyState title="No lead-time buckets available" />
          )
        ) : null}
      </SectionCard>

      <p className="text-xs text-slate-500">
        {meta.data
          ? `Snapshot: ${meta.data.snapshotNotice}`
          : "Snapshot metadata unavailable."}
      </p>
    </div>
  );
}
