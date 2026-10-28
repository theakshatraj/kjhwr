// @vitest-environment jsdom
/**
 * Regression tests for the chart-rendering investigation (January 2026).
 *
 * They pin the two things that can actually make a fully-populated chart look
 * blank in the UI:
 *   1. the Decision chart must emit a plottable, NaN-free path for the forecast,
 *      conservative and actual series for every delivery-day state we ship
 *      (15 Jan at the 09:00 and 15:00 cutoffs, and the 1 Jan warm-up day);
 *   2. the Accuracy histogram must draw its bars straight away - Recharts
 *      animates <Bar> from zero height by default, which renders as "axes but
 *      no bars" until the animation finishes.
 *
 * The numeric fixtures are the real forecast/actual/bound values served by the
 * API for those three states (48 half-hour slots each).
 */
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { SignedErrorHistogram } from "./Charts";
import { ForecastChart } from "./ForecastChart";
import type { DecisionRow } from "../types";

/* ------------------------------------------------------------------ jsdom setup */

beforeAll(() => {
  // jsdom has no ResizeObserver; ResponsiveContainer needs a constructor.
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;

  // jsdom performs no layout, so getBoundingClientRect() is all zeros and
  // ResponsiveContainer would hand the chart a 0x0 canvas. Pin a plot size.
  HTMLElement.prototype.getBoundingClientRect = function getBoundingClientRect() {
    return {
      width: 800,
      height: 400,
      top: 0,
      left: 0,
      right: 800,
      bottom: 400,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect;
  };
});

afterEach(() => {
  cleanup();
});

/* ------------------------------------------------------------------- fixtures */

const LABELS = [
  "00:00", "00:30", "01:00", "01:30", "02:00", "02:30", "03:00", "03:30", "04:00", "04:30",
  "05:00", "05:30", "06:00", "06:30", "07:00", "07:30", "08:00", "08:30", "09:00", "09:30",
  "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30",
  "15:00", "15:30", "16:00", "16:30", "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
  "20:00", "20:30", "21:00", "21:30", "22:00", "22:30", "23:00", "23:30",
];

const JAN15_FORECAST_0900 = [
  15834, 15834, 15478, 15478, 15066, 15066, 14655, 14655, 14497, 14497, 14419, 14419,
  14017, 14017, 13411, 13411, 12931, 12931, 12576, 12576, 12081, 12081, 11578, 11578,
  11049, 11049, 10378, 10378, 9619, 9619, 9050, 9050, 8864, 8864, 8870, 8870,
  8962, 8962, 9130, 9130, 9059, 9059, 9049, 9049, 9091, 9091, 8966, 8966,
];

const JAN15_FORECAST_1500 = [
  15813, 15813, 15441, 15441, 15019, 15019, 14602, 14602, 14519, 14519, 14550, 14550,
  14223, 14223, 13666, 13666, 13230, 13230, 12861, 12861, 12362, 12362, 11888, 11888,
  11351, 11351, 10616, 10616, 9837, 9837, 9261, 9261, 9030, 9030, 9030, 9030,
  9151, 9151, 9304, 9304, 9196, 9196, 9131, 9131, 9129, 9129, 8971, 8971,
];

const JAN15_ACTUAL = [
  14602, 14311, 14200, 14516, 14534, 14202, 14028, 14250, 13901, 13713, 13704, 13389,
  13256, 13518, 13401, 12937, 12719, 12302, 12242, 12144, 9807, 11303, 9930, 9601,
  9742, 9839, 8843, 8771, 8384, 8264, 8482, 8608, 8543, 8378, 8266, 8004,
  7672, 7593, 7631, 7599, 7592, 7183, 7603, 7964, 7685, 7431, 7258, 7407,
];

// 1 January's forecast is genuinely almost flat (19,138-20,028 MW).
const JAN01_FORECAST = [
  19412, 19412, 19620, 19620, 19553, 19553, 19340, 19340, 19198, 19198, 19138, 19138,
  19264, 19264, 19395, 19395, 19512, 19512, 19428, 19428, 19448, 19448, 19589, 19589,
  19764, 19764, 19946, 19946, 20005, 20005, 19991, 19991, 20028, 20028, 19974, 19974,
  19942, 19942, 19797, 19797, 19627, 19627, 19485, 19485, 19307, 19307, 19145, 19145,
];

const JAN01_ACTUAL = [
  13756, 13873, 14036, 14077, 14185, 14575, 14942, 15264, 15303, 15396, 15442, 15363,
  15363, 15445, 15348, 15353, 15595, 15602, 15555, 15514, 15790, 16058, 16242, 16349,
  16408, 16252, 16191, 16130, 16063, 15790, 15257, 15088, 15201, 15187, 15140, 15094,
  15270, 15490, 15381, 15555, 15314, 15172, 15564, 15597, 15626, 15542, 15578, 15538,
];

interface Bounds {
  /** P90(E): lower bound = max(0, F - P90(E)). */
  lowerOffsetMw: number;
  /** P10(E): upper bound = max(0, F - P10(E)). */
  upperOffsetMw: number;
}

const JAN15_0900_BOUNDS: Bounds = { lowerOffsetMw: 4499.4, upperOffsetMw: -1166.1 };
const JAN15_1500_BOUNDS: Bounds = { lowerOffsetMw: 4384.9, upperOffsetMw: -899.7 };
const JAN01_0900_BOUNDS: Bounds = { lowerOffsetMw: 4417.6, upperOffsetMw: -1224.2 };

function buildDay(
  forecast: readonly number[],
  actual: readonly number[],
  bounds: Bounds,
  blankSlots: readonly number[] = [],
): DecisionRow[] {
  return LABELS.map((label, index) => {
    const blank = blankSlots.includes(index);
    const f = blank ? null : forecast[index];
    const a = blank ? null : actual[index];
    return {
      startTime: `2026-01-15T00:00:00Z`,
      startTimeLocal: label,
      forecastStartTime: `2026-01-15T00:00:00Z`,
      forecastMw: f,
      publishTime: f === null ? null : "2026-01-14T07:30:00Z",
      horizonHours: f === null ? null : 16.5,
      forecastAgeHours: f === null ? null : 1.5,
      actualMw: a,
      errorMw: f !== null && a !== null ? f - a : null,
      lowerBoundMw: f === null ? null : Math.max(0, f - bounds.lowerOffsetMw),
      upperBoundMw: f === null ? null : Math.max(0, f - bounds.upperOffsetMw),
      forecastMwh: f === null ? null : f * 0.5,
      flag: null,
    };
  });
}

const JAN15_0900 = buildDay(JAN15_FORECAST_0900, JAN15_ACTUAL, JAN15_0900_BOUNDS);
const JAN15_1500 = buildDay(JAN15_FORECAST_1500, JAN15_ACTUAL, JAN15_1500_BOUNDS);
const JAN01_0900 = buildDay(JAN01_FORECAST, JAN01_ACTUAL, JAN01_0900_BOUNDS);

/* ------------------------------------------------------------------ utilities */

function pathData(container: HTMLElement, selector: string): string[] {
  return Array.from(container.querySelectorAll(selector)).map(
    (node) => node.getAttribute("d") ?? "",
  );
}

/** Recharts writes bar rectangles as `M x,y h w v h h -w Z`, so height is the `v`. */
function barHeights(container: HTMLElement): number[] {
  return pathData(container, ".recharts-bar-rectangle path").map((d) => {
    const match = /[vV]\s*(-?[\d.]+)/.exec(d);
    return match ? Math.abs(Number(match[1])) : 0;
  });
}

function expectPlottable(container: HTMLElement, selector: string, expected: number) {
  const paths = pathData(container, selector);
  expect(paths).toHaveLength(expected);
  for (const d of paths) {
    expect(d.length).toBeGreaterThan(100);
    expect(d).not.toMatch(/NaN|Infinity|undefined/);
  }
  return paths;
}

/* --------------------------------------------------------------------- tests */

describe("ForecastChart: every shipped delivery-day state plots its series", () => {
  const states: Array<[string, DecisionRow[]]> = [
    ["2026-01-15 at the 09:00 cutoff", JAN15_0900],
    ["2026-01-15 at the 15:00 cutoff", JAN15_1500],
    ["2026-01-01 warm-up (December calibration)", JAN01_0900],
  ];

  for (const [name, rows] of states) {
    it(`renders forecast, conservative and actual plus the band for ${name}`, () => {
      const { container } = render(<ForecastChart rows={rows} showActual showBand />);

      // Three lines: forecast, conservative lower bound, actual outturn.
      expectPlottable(container, ".recharts-line-curve", 3);
      // Two stacked areas: the invisible base and the visible band.
      expectPlottable(container, ".recharts-area-area", 2);
      // One real chart canvas. Legend swatches are `.recharts-surface` svgs as
      // well, so they have to be excluded or this counts 1 canvas + 4 swatches.
      expect(container.querySelectorAll(".recharts-wrapper")).toHaveLength(1);
      expect(
        container.querySelectorAll(".recharts-wrapper > svg.recharts-surface"),
      ).toHaveLength(1);
    });
  }

  it("renders the empty-day state without throwing", () => {
    const { container } = render(<ForecastChart rows={[]} showActual showBand />);
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
    expect(container.querySelectorAll(".recharts-line-curve")).toHaveLength(0);
  });

  it("breaks the forecast line at a forecast outage instead of bridging or zero-filling it", () => {
    // Slots 20-29 are the 10:00-14:30 outage: no forecast, no band, no actual.
    const outage = [20, 21, 22, 23, 24, 25, 26, 27, 28, 29];
    const rows = buildDay(JAN15_FORECAST_0900, JAN15_ACTUAL, JAN15_0900_BOUNDS, outage);
    const { container } = render(<ForecastChart rows={rows} showActual showBand />);

    const [forecastCurve] = expectPlottable(container, ".recharts-line-curve", 3);
    // connectNulls={false}: the gap becomes a second sub-path, so the two sides
    // of the outage are never joined and no point is drawn at 0 MW.
    const subPaths = forecastCurve.match(/M/g) ?? [];
    expect(subPaths.length).toBeGreaterThan(1);
    expect(forecastCurve).not.toMatch(/NaN|Infinity|undefined/);
  });

  it("omits the band and the conservative line when calibration is unavailable", () => {
    const { container } = render(<ForecastChart rows={JAN15_0900} showActual showBand={false} />);
    expect(container.querySelectorAll(".recharts-area-area")).toHaveLength(0);
    expectPlottable(container, ".recharts-line-curve", 2);
  });
});

describe("SignedErrorHistogram: bars are drawn on the first paint", () => {
  // The real 40-bin distribution served for January 2026 at the 09:00 cutoff.
  const binEdgesMw = [
    -3835, -3566.775, -3298.55, -3030.325, -2762.1, -2493.875, -2225.65, -1957.425,
    -1689.2, -1420.975, -1152.75, -884.525, -616.3, -348.075, -79.85, 188.375,
    456.6, 724.825, 993.05, 1261.275, 1529.5, 1797.725, 2065.95, 2334.175,
    2602.4, 2870.625, 3138.85, 3407.075, 3675.3, 3943.525, 4211.75, 4479.975,
    4748.2, 5016.425, 5284.65, 5552.875, 5821.1, 6089.325, 6357.55, 6625.775, 6894,
  ];
  const counts = [
    2, 1, 0, 4, 4, 3, 12, 13, 12, 18, 40, 31, 32, 38, 40, 54, 67, 69, 118, 110,
    108, 100, 84, 54, 79, 49, 60, 46, 47, 32, 32, 12, 22, 13, 33, 21, 8, 5, 6, 9,
  ];

  it("draws one non-zero-height bar per bin when valid bins exist", () => {
    const { container } = render(
      <SignedErrorHistogram binEdgesMw={binEdgesMw} counts={counts} />,
    );

    const heights = barHeights(container);
    // Recharts' <Rectangle> returns null for a zero-width/height rect, so an
    // empty bin draws no <path> at all: one bar per non-empty bin, not per bin.
    const nonEmpty = counts.filter((count) => count > 0).length;
    expect(nonEmpty).toBeGreaterThan(0);
    expect(heights).toHaveLength(nonEmpty);
    // Guards the regression: an animated <Bar> starts at height 0, which shows
    // as axes with no bars. Every drawn bar must have visible height.
    expect(heights.every((height) => height > 1)).toBe(true);
  });

  it("renders the empty state when there are no bins", () => {
    const { container } = render(<SignedErrorHistogram binEdgesMw={[]} counts={[]} />);
    expect(container.textContent).toContain("No errors to bin");
    expect(container.querySelectorAll(".recharts-bar-rectangle")).toHaveLength(0);
  });

  it("still draws bars for a partially populated distribution", () => {
    const sparse = counts.map((count, index) => (index % 3 === 0 ? count : 0));
    const { container } = render(<SignedErrorHistogram binEdgesMw={binEdgesMw} counts={sparse} />);
    const heights = barHeights(container);
    const expected = sparse.filter((count) => count > 0).length;
    expect(expected).toBeGreaterThan(0);
    expect(expected).toBeLessThan(sparse.length);
    expect(heights).toHaveLength(expected);
    expect(heights.every((height) => height > 1)).toBe(true);
  });
});
