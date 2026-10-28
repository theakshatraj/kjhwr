/**
 * Shared JSON contract for the Wind Forecast Decision Portal API.
 *
 * These interfaces are the single source of truth for the response shape: the
 * backend test `backend/tests/test_contract.py` parses this file and asserts the
 * live API JSON keys match the fields declared here, so a rename on either side
 * fails loudly instead of silently breaking the frontend.
 *
 * Conventions baked into every name below:
 *   - keys are camelCase (`forecastMw`, `energyMwh`)
 *   - timestamps are ISO-8601 UTC strings
 *   - units are part of the field name
 *   - a bound is `null` (with a `reason`) when calibration is insufficient
 */

export type IsoTimestamp = string;

export interface HealthResponse {
  status: string;
  dataAvailable: boolean;
}

export interface MetaResponse {
  deliveryMonth: Record<string, string>;
  defaultCutoffLocalTime: string;
  cutoffNote: string;
  calibrationModes: string[];
  minCalibration: Record<string, number>;
  calibrationWarmup: Record<string, string>;
  resolution: Record<string, unknown>;
  window: Record<string, string>;
  counts: Record<string, number>;
  horizonRangeHours: Record<string, number | null>;
  dataAvailable: boolean;
  snapshotNotice: string;
  attribution: string;
  knownDeviations: string[];
  provenance: Record<string, unknown> | null;
}

export interface CalibrationInfo {
  mode: string;
  label: string;
  strictNoLookahead: boolean;
  available: boolean;
  nDays: number;
  nIntervals: number;
  warmupDays: number;
  historyFrom: string | null;
  historyTo: string | null;
  percentilesMw: Record<string, number>;
  boundsMw: Record<string, number> | null;
  pooled: boolean;
  pooledNote: string;
  reason: string | null;
}

export interface DecisionRow {
  startTime: IsoTimestamp;
  startTimeLocal: string;
  forecastStartTime: IsoTimestamp;
  forecastMw: number | null;
  publishTime: IsoTimestamp | null;
  horizonHours: number | null;
  forecastAgeHours: number | null;
  actualMw: number | null;
  errorMw: number | null;
  lowerBoundMw: number | null;
  upperBoundMw: number | null;
  forecastMwh: number | null;
  flag: string | null;
}

export interface DailyEnergy {
  energyMwh: number | null;
  partial: boolean;
  unavailable: boolean;
  intervalsWithForecast: number;
  intervalsExpected: number;
  reason: string | null;
}

export interface DecisionResponse {
  deliveryDate: string;
  cutoffLocalTime: string;
  cutoffUtc: IsoTimestamp;
  cutoffLabel: string;
  calibrationMode: string;
  calibrationN: number;
  calibration: CalibrationInfo;
  counts: Record<string, number>;
  dailyEnergy: DailyEnergy;
  rows: DecisionRow[];
}

export interface AccuracySummaryResponse {
  window: Record<string, string>;
  cutoffLocalTime: string;
  dataset: string;
  counts: Record<string, number>;
  decisionTime: Record<string, unknown>;
  nativeHourly: Record<string, unknown>;
  coverage: Record<string, unknown>;
  coverageByHorizon: Record<string, unknown>;
  calibration: CalibrationInfo;
}

export interface AccuracySeriesResponse {
  window: Record<string, string>;
  counts: Record<string, number>;
  series: Record<string, unknown>[];
}

export interface AccuracyDistributionResponse {
  window: Record<string, string>;
  counts: Record<string, number>;
  histogram: Record<string, unknown>;
  absoluteErrorPercentilesMw: Record<string, number>;
}

export interface HorizonBucket {
  horizonBucket: string;
  recordCount: number;
  uniqueIntervalCount: number;
  metrics: Record<string, unknown>;
}

export interface AccuracyByHorizonResponse {
  dataset: string;
  note: string;
  totalRecords: number;
  excludedRecords: number;
  excludedHorizonRangeHours: Record<string, number> | null;
  horizonInconsistentRecords: number;
  observedHorizonHours: Record<string, unknown>;
  buckets: HorizonBucket[];
}

export interface ForecastVintage {
  publishTime: IsoTimestamp;
  forecastMw: number | null;
  horizonHours: number | null;
  forecastAgeHours: number | null;
  selected: boolean;
  predictive: boolean;
}

export interface ForecastIntervalVintages {
  forecastStartTime: IsoTimestamp;
  startTimeLocal: string;
  hourlyActualMw: number | null;
  errorMw: number | null;
  vintages: ForecastVintage[];
}

export interface VintagesResponse {
  deliveryDate: string;
  cutoffLocalTime: string;
  cutoffUtc: IsoTimestamp;
  dataset: string;
  counts: Record<string, number>;
  intervals: ForecastIntervalVintages[];
}
