import type { DailyEnergy } from "../types";

/** A settlement half-hour is 0.5 h, so a period at P MW delivers P * 0.5 MWh. */
export const MWH_PER_HALF_HOUR = 0.5;

/** Settlement periods in an ordinary London delivery day (46/50 on DST days). */
export const HALF_HOURS_PER_DAY = 48;

export const NO_FORECAST_REASON =
  "no forecast available for any delivery interval of this day";

type MaybeNumber = number | null | undefined;

function isNumber(value: MaybeNumber): value is number {
  return typeof value === "number" && !Number.isNaN(value);
}

/** Energy in MWh for one half-hour, or `null` when there is no forecast. */
export function halfHourEnergyMwh(forecastMw: MaybeNumber): number | null {
  return isNumber(forecastMw) ? forecastMw * MWH_PER_HALF_HOUR : null;
}

/**
 * Daily energy over a delivery day's half-hour series.
 *
 * Only intervals that actually carry a forecast contribute. A missing interval
 * is *never* counted as zero: if some are missing the total is flagged
 * `partial`, and if none are present it is `unavailable` with a null total.
 * This mirrors `metrics.daily_energy_mwh` on the backend so the number on screen
 * always agrees with the table and chart rendered from the same rows.
 */
export function energyFromSeries(forecastsMw: readonly MaybeNumber[]): DailyEnergy {
  const intervalsExpected = forecastsMw.length;
  const valid = forecastsMw.filter(isNumber);

  if (intervalsExpected === 0 || valid.length === 0) {
    return {
      energyMwh: null,
      partial: true,
      unavailable: true,
      intervalsWithForecast: 0,
      intervalsExpected,
      reason: NO_FORECAST_REASON,
    };
  }

  const total = valid.reduce((sum, value) => sum + value * MWH_PER_HALF_HOUR, 0);
  return {
    energyMwh: total,
    partial: valid.length < intervalsExpected,
    unavailable: false,
    intervalsWithForecast: valid.length,
    intervalsExpected,
    reason: null,
  };
}

export interface ForecastStats {
  /** Number of half-hours that actually carry a forecast. */
  n: number;
  meanMw: number;
  peakMw: number;
  minMw: number;
}

/**
 * Average / peak / minimum generation across the intervals that have a
 * forecast. `null` when the day has no forecast at all - the cards then show an
 * explicit gap rather than a reassuring 0 MW.
 */
export function forecastStats(forecastsMw: readonly MaybeNumber[]): ForecastStats | null {
  const valid = forecastsMw.filter(isNumber);
  if (valid.length === 0) return null;
  const sum = valid.reduce((total, value) => total + value, 0);
  return {
    n: valid.length,
    meanMw: sum / valid.length,
    peakMw: Math.max(...valid),
    minMw: Math.min(...valid),
  };
}

/** Mean forecast age at the decision cutoff; `null` when nothing was published. */
export function meanForecastAgeHours(ages: readonly MaybeNumber[]): number | null {
  const valid = ages.filter(isNumber);
  if (valid.length === 0) return null;
  return valid.reduce((total, value) => total + value, 0) / valid.length;
}

/** Spread of forecast age in hours, useful for the decision card's sub-label. */
export function forecastAgeRange(
  ages: readonly MaybeNumber[],
): { min: number; max: number } | null {
  const valid = ages.filter(isNumber);
  if (valid.length === 0) return null;
  return { min: Math.min(...valid), max: Math.max(...valid) };
}
