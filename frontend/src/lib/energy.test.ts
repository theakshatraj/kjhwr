import { describe, expect, it } from "vitest";

import {
  HALF_HOURS_PER_DAY,
  MWH_PER_HALF_HOUR,
  NO_FORECAST_REASON,
  energyFromSeries,
  forecastAgeRange,
  forecastStats,
  halfHourEnergyMwh,
  meanForecastAgeHours,
} from "./energy";

describe("constants", () => {
  it("uses a half-hour settlement period", () => {
    expect(MWH_PER_HALF_HOUR).toBe(0.5);
    expect(HALF_HOURS_PER_DAY).toBe(48);
  });
});

describe("halfHourEnergyMwh", () => {
  it("converts MW to MWh with the 0.5 h factor", () => {
    expect(halfHourEnergyMwh(1000)).toBe(500);
    expect(halfHourEnergyMwh(0)).toBe(0);
  });

  it("returns null rather than zero when there is no forecast", () => {
    expect(halfHourEnergyMwh(null)).toBeNull();
    expect(halfHourEnergyMwh(undefined)).toBeNull();
  });
});

describe("energyFromSeries", () => {
  it("sums MW * 0.5 over the intervals that carry a forecast", () => {
    const result = energyFromSeries([1000, 2000]);
    expect(result.energyMwh).toBe(1500);
    expect(result.intervalsWithForecast).toBe(2);
    expect(result.intervalsExpected).toBe(2);
    expect(result.partial).toBe(false);
    expect(result.unavailable).toBe(false);
    expect(result.reason).toBeNull();
  });

  it("never zero-fills a missing interval; the day is flagged partial", () => {
    const result = energyFromSeries([1000, null, null, 3000]);
    // (1000 + 3000) * 0.5 - the two missing half-hours contribute nothing.
    expect(result.energyMwh).toBe(2000);
    expect(result.intervalsWithForecast).toBe(2);
    expect(result.intervalsExpected).toBe(4);
    expect(result.partial).toBe(true);
    expect(result.unavailable).toBe(false);
  });

  it("reports an empty day as unavailable with a null total", () => {
    const result = energyFromSeries([]);
    expect(result.energyMwh).toBeNull();
    expect(result.unavailable).toBe(true);
    expect(result.partial).toBe(true);
    expect(result.intervalsExpected).toBe(0);
    expect(result.reason).toBe(NO_FORECAST_REASON);
  });

  it("treats an all-missing day as unavailable, not as a calm day", () => {
    const result = energyFromSeries(Array.from({ length: 48 }, () => null));
    expect(result.energyMwh).toBeNull();
    expect(result.unavailable).toBe(true);
    expect(result.intervalsWithForecast).toBe(0);
    expect(result.intervalsExpected).toBe(48);
    expect(result.reason).toBe(NO_FORECAST_REASON);
  });

  it("matches the hand-checked two-hour working: 13100 and 13400 MW over two half-hours each", () => {
    // Wins the same hand-check the backend contract test pins: 26,500 MWh.
    const series = [13100, 13100, 13400, 13400];
    const result = energyFromSeries(series);
    expect(result.energyMwh).toBeCloseTo(26500, 6);
    expect(result.partial).toBe(false);
  });

  it("scales linearly: a full day at a constant 1000 MW is 24,000 MWh", () => {
    const result = energyFromSeries(Array.from({ length: 48 }, () => 1000));
    expect(result.energyMwh).toBeCloseTo(24000, 6);
    expect(result.intervalsWithForecast).toBe(48);
  });
});

describe("forecastStats", () => {
  it("computes mean, peak and minimum over the forecast intervals", () => {
    expect(forecastStats([1000, 2000, 3000])).toEqual({
      n: 3,
      meanMw: 2000,
      peakMw: 3000,
      minMw: 1000,
    });
  });

  it("ignores missing intervals", () => {
    expect(forecastStats([1000, null, 3000])).toEqual({
      n: 2,
      meanMw: 2000,
      peakMw: 3000,
      minMw: 1000,
    });
  });

  it("returns null when nothing was forecast", () => {
    expect(forecastStats([])).toBeNull();
    expect(forecastStats([null, null])).toBeNull();
  });
});

describe("forecast age helpers", () => {
  it("averages the ages of the selected forecasts", () => {
    expect(meanForecastAgeHours([1.5, 0.5])).toBe(1);
    expect(meanForecastAgeHours([1.5, null])).toBe(1.5);
    expect(meanForecastAgeHours([null])).toBeNull();
  });

  it("reports the age range across the day", () => {
    expect(forecastAgeRange([1.5, 0.5, 2])).toEqual({ min: 0.5, max: 2 });
    expect(forecastAgeRange([])).toBeNull();
  });
});
