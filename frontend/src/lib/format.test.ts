import { describe, expect, it } from "vitest";

import {
  MISSING,
  formatCount,
  formatFraction,
  formatHours,
  formatIntervals,
  formatMw,
  formatMwh,
  formatNumber,
  formatPercent,
  formatSignedMw,
  formatUtc,
} from "./format";

describe("formatNumber", () => {
  it("renders an explicit gap for absent values, never zero", () => {
    expect(formatNumber(null)).toBe(MISSING);
    expect(formatNumber(undefined)).toBe(MISSING);
    expect(formatNumber(Number.NaN)).toBe(MISSING);
  });

  it("groups thousands and respects the digit count", () => {
    expect(formatNumber(2112)).toBe("2,112");
    expect(formatNumber(12345.678, 1)).toBe("12,345.7");
    expect(formatNumber(0)).toBe("0");
  });
});

describe("unit formatting", () => {
  it("appends the unit for MW, MWh, hours and counts", () => {
    expect(formatMw(15834)).toBe("15,834 MW");
    expect(formatMwh(278630)).toBe("278,630 MWh");
    expect(formatHours(1.5)).toBe("1.5 h");
    expect(formatCount(48)).toBe("48");
  });

  it("keeps absent values absent in every unit", () => {
    expect(formatMw(null)).toBe(MISSING);
    expect(formatMwh(undefined)).toBe(MISSING);
    expect(formatHours(null)).toBe(MISSING);
  });
});

describe("formatSignedMw", () => {
  it("marks over-forecasts with an explicit plus sign", () => {
    expect(formatSignedMw(1232)).toBe("+1,232 MW");
    expect(formatSignedMw(-500)).toBe("-500 MW");
    expect(formatSignedMw(0)).toBe("0 MW");
    expect(formatSignedMw(null)).toBe(MISSING);
  });
});

describe("percentages", () => {
  it("scales a fraction for coverage-style values", () => {
    expect(formatFraction(0.9134, 1)).toBe("91.3%");
    expect(formatFraction(0.9, 0)).toBe("90%");
    expect(formatFraction(null)).toBe(MISSING);
  });

  it("passes through values already expressed in percent", () => {
    expect(formatPercent(12.5)).toBe("12.5%");
    expect(formatPercent(null)).toBe(MISSING);
  });
});

describe("formatUtc", () => {
  it("renders ISO timestamps in UTC, never the viewer's local zone", () => {
    expect(formatUtc("2026-01-14T09:00:00Z")).toBe("2026-01-14 09:00 UTC");
    expect(formatUtc("2026-01-14T09:00:00Z", false)).toBe("09:00 UTC");
    expect(formatUtc("2026-01-14T07:30:00Z", false)).toBe("07:30 UTC");
  });

  it("degrades to a gap for missing or unparseable input", () => {
    expect(formatUtc(null)).toBe(MISSING);
    expect(formatUtc("not-a-timestamp")).toBe(MISSING);
  });
});

describe("formatIntervals", () => {
  it("states coverage as 'N of M intervals'", () => {
    expect(formatIntervals(48, 48)).toBe("48 of 48 intervals");
    expect(formatIntervals(4, 48)).toBe("4 of 48 intervals");
  });
});
