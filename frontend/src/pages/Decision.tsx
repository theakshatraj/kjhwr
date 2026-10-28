import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  CALIBRATION_MODES,
  MODE_LABELS,
  api,
  queryKeys,
  type CalibrationMode,
} from "../api/client";
import { DecisionTable } from "../components/DecisionTable";
import { ForecastChart } from "../components/ForecastChart";
import { Badge, KpiCard } from "../components/KpiCard";
import { ModeToggle } from "../components/ModeToggle";
import { Notice } from "../components/Notice";
import { EmptyState, ErrorState, LoadingState, SectionCard } from "../components/States";
import {
  energyFromSeries,
  forecastAgeRange,
  forecastStats,
  meanForecastAgeHours,
} from "../lib/energy";
import {
  MISSING,
  formatCount,
  formatHours,
  formatIntervals,
  formatMw,
  formatMwh,
  formatUtc,
} from "../lib/format";
import type { CalibrationInfo, DecisionResponse } from "../types";

const DELIVERY_MIN = "2026-01-01";
const DELIVERY_MAX = "2026-01-31";

const PLANNING_NOTICE =
  "Wind planning buffer indicator, not a procurement recommendation: demand and other supply are not included.";

function CalibrationNotice({ calibration }: { calibration: CalibrationInfo }) {
  return (
    <Notice tone="warn" title="Insufficient calibration history">
      <p>
        {calibration.reason ?? "insufficient calibration history"} - the conservative wind indicator
        is not shown for this delivery day, and no bound is returned rather than falling back to a
        future-data or zero-filled estimate.
      </p>
      <p className="mt-1">
        Eligible history for this cutoff: {formatCount(calibration.nDays)} delivery day(s),{" "}
        {formatCount(calibration.nIntervals)} interval(s). Mode: {calibration.label}.
      </p>
    </Notice>
  );
}

function CalibrationCard({ calibration, mode, n }: { calibration: CalibrationInfo; mode: string; n: number }) {
  const history =
    calibration.historyFrom && calibration.historyTo
      ? `${calibration.historyFrom} \u2192 ${calibration.historyTo}`
      : MISSING;
  const warmup =
    calibration.warmupDays > 0
      ? `includes ${calibration.warmupDays} December warm-up day(s)`
      : "no warm-up days used";

  return (
    <KpiCard
      label="Calibration mode and n"
      badge={
        calibration.available ? (
          <Badge tone="ok">bounds available</Badge>
        ) : (
          <Badge tone="warn">unavailable</Badge>
        )
      }
      value={calibration.available ? `${formatCount(n)} intervals` : "Not available"}
      tone={calibration.available ? "default" : "warn"}
      sub={
        <>
          {MODE_LABELS[mode] ?? calibration.label} · {formatCount(calibration.nDays)} delivery
          day(s) · {warmup}
          <br />
          History {history}
        </>
      }
    />
  );
}

function DecisionView({ data }: { data: DecisionResponse }) {
  const [showActual, setShowActual] = useState(true);
  const [bandRequested, setBandRequested] = useState(true);

  const calibration = data.calibration;
  const canShowBand = calibration.available;
  const showBand = bandRequested && canShowBand;

  const forecasts = data.rows.map((row) => row.forecastMw);
  const ages = data.rows.map((row) => row.forecastAgeHours);
  const stats = forecastStats(forecasts);
  const energy = energyFromSeries(forecasts);
  const meanAge = meanForecastAgeHours(ages);
  const ageRange = forecastAgeRange(ages);

  const energyBadge = energy.unavailable ? (
    <Badge tone="danger">unavailable</Badge>
  ) : energy.partial ? (
    <Badge tone="warn">partial</Badge>
  ) : (
    <Badge tone="ok">complete</Badge>
  );

  return (
    <div className="space-y-6">
      <Notice tone="neutral">
        <p className="font-medium">{PLANNING_NOTICE}</p>
        <p className="mt-1 text-xs">
          {data.cutoffLabel} · cutoff instant {formatUtc(data.cutoffUtc)} · delivery day{" "}
          {data.deliveryDate} (London calendar day)
        </p>
      </Notice>

      {canShowBand ? null : <CalibrationNotice calibration={calibration} />}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard
          label="Average generation"
          value={formatMw(stats ? stats.meanMw : null, 0)}
          sub={stats ? `across ${formatCount(stats.n)} intervals with a forecast` : "no forecast"}
        />
        <KpiCard
          label="Peak generation"
          value={formatMw(stats ? stats.peakMw : null, 0)}
          sub="highest half-hour forecast"
        />
        <KpiCard
          label="Minimum generation"
          value={formatMw(stats ? stats.minMw : null, 0)}
          sub="lowest half-hour forecast"
        />
        <KpiCard
          label="Estimated daily wind energy"
          badge={energyBadge}
          value={formatMwh(energy.energyMwh, 0)}
          tone={energy.unavailable ? "warn" : "accent"}
          sub={
            <>
              {formatIntervals(energy.intervalsWithForecast, energy.intervalsExpected)} with a
              forecast · sum of MW × 0.5
              {energy.reason ? <span className="block">{energy.reason}</span> : null}
            </>
          }
        />
        <KpiCard
          label="Forecast age at decision"
          value={formatHours(meanAge, 1)}
          sub={
            ageRange
              ? `mean age of the selected forecast · range ${formatHours(ageRange.min, 1)} to ${formatHours(ageRange.max, 1)}`
              : "no forecast published before the cutoff"
          }
        />
        <CalibrationCard
          calibration={calibration}
          mode={data.calibrationMode}
          n={data.calibrationN}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <KpiCard
          label="Settlement intervals"
          value={formatCount(data.counts.intervalsExpected)}
          sub="delivery day half-hours"
        />
        <KpiCard
          label="Intervals with a forecast"
          value={formatCount(data.counts.intervalsWithForecast)}
          sub={`${formatCount(data.counts.nForecastIntervals ?? 0)} distinct hourly forecast intervals`}
        />
        <KpiCard
          label="Intervals with an actual"
          value={formatCount(data.counts.intervalsWithActual)}
          sub="FUELHH wind outturn present"
        />
      </div>

      <SectionCard
        title="Forecast, empirical band and conservative indicator"
        subtitle="One point per settlement half-hour of the delivery day (London local time)."
        right={
          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={showActual}
                onChange={(event) => setShowActual(event.target.checked)}
              />
              Actual outturn overlay
            </label>
            <label className={`flex items-center gap-2 ${canShowBand ? "" : "opacity-50"}`}>
              <input
                type="checkbox"
                checked={showBand}
                disabled={!canShowBand}
                onChange={(event) => setBandRequested(event.target.checked)}
              />
              Band &amp; conservative indicator
            </label>
          </div>
        }
      >
        {data.rows.length === 0 ? (
          <EmptyState title="No intervals for this delivery day" />
        ) : (
          <ForecastChart rows={data.rows} showActual={showActual} showBand={showBand} />
        )}
      </SectionCard>

      <SectionCard
        title="Delivery-day detail"
        subtitle="Every settlement half-hour is listed, including slots with no eligible forecast (flagged, never zero-filled)."
      >
        <DecisionTable data={data} />
      </SectionCard>
    </div>
  );
}

export default function DecisionPage() {
  const [deliveryDate, setDeliveryDate] = useState("2026-01-15");
  const [cutoff, setCutoff] = useState("09:00");
  const [mode, setMode] = useState<CalibrationMode>(CALIBRATION_MODES.decisionTime);

  const meta = useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, retry: 0 });
  const query = useQuery({
    queryKey: queryKeys.decision(deliveryDate, cutoff, mode),
    queryFn: () => api.decision(deliveryDate, cutoff, mode),
  });

  return (
    <div className="space-y-6">
      <section className="card">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-4">
          <div>
            <label className="field-label" htmlFor="delivery-date">
              Delivery date (January 2026)
            </label>
            <input
              id="delivery-date"
              type="date"
              className="input"
              value={deliveryDate}
              min={DELIVERY_MIN}
              max={DELIVERY_MAX}
              onChange={(event) => {
                if (event.target.value) setDeliveryDate(event.target.value);
              }}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="cutoff">
              Assumed decision cutoff (editable)
            </label>
            <input
              id="cutoff"
              type="time"
              className="input"
              value={cutoff}
              step={60}
              onChange={(event) => {
                if (event.target.value) setCutoff(event.target.value);
              }}
            />
            <p className="mt-1 text-2xs text-slate-500">
              London time on the day before delivery. {meta.data?.defaultCutoffLocalTime ?? "09:00"}{" "}
              is the assumed default.
            </p>
          </div>
          <div className="lg:col-span-2">
            <span className="field-label">Calibration mode</span>
            <ModeToggle mode={mode} onChange={setMode} />
            <p className="mt-1 text-2xs text-slate-500">
              Decision-time uses only delivery days that closed before the cutoff; retrospective
              uses the whole month and is not decision-time evidence.
            </p>
          </div>
        </div>
        {meta.data?.cutoffNote ? (
          <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500">
            {meta.data.cutoffNote}
          </p>
        ) : null}
      </section>

      {query.isPending ? <LoadingState label={"Loading the delivery day\u2026"} /> : null}
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : null}
      {query.data ? <DecisionView data={query.data} /> : null}
    </div>
  );
}
