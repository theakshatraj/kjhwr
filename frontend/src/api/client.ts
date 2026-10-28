/**
 * Typed API client.
 *
 * Query parameters stay snake_case (that is the wire contract the FastAPI
 * routers declare); response bodies are camelCase and are typed by the shared
 * interfaces in `src/types.ts`, which the backend contract test also reads.
 */

import type {
  AccuracyByHorizonResponse,
  AccuracyDistributionResponse,
  AccuracySeriesResponse,
  AccuracySummaryResponse,
  DecisionResponse,
  HealthResponse,
  MetaResponse,
  VintagesResponse,
} from "../types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type QueryValue = string | number | undefined | null;

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return String(item);
        })
        .join("; ");
    }
    if (detail) return JSON.stringify(detail);
  } catch {
    /* body was not JSON - fall through to the status line */
  }
  return `${response.status} ${response.statusText}`;
}

async function getJson<T>(path: string, query?: Record<string, QueryValue>): Promise<T> {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const suffix = search.size > 0 ? `?${search.toString()}` : "";
  const response = await fetch(`/api${path}${suffix}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status);
  }
  return (await response.json()) as T;
}

export const CALIBRATION_MODES = {
  decisionTime: "decision_time",
  retrospective: "retrospective",
} as const;

export type CalibrationMode =
  (typeof CALIBRATION_MODES)[keyof typeof CALIBRATION_MODES];

export const MODE_LABELS: Record<string, string> = {
  [CALIBRATION_MODES.decisionTime]: "Decision-time calibration",
  [CALIBRATION_MODES.retrospective]: "Retrospective",
};

export interface AccuracyWindowQuery {
  mode: CalibrationMode;
  cutoff: string;
  from?: string;
  to?: string;
}

function accuracyParams({ mode, cutoff, from, to }: AccuracyWindowQuery) {
  return { mode, cutoff, from, to };
}

export const api = {
  health: () => getJson<HealthResponse>("/health"),

  meta: () => getJson<MetaResponse>("/meta"),

  decision: (deliveryDate: string, cutoff: string, mode: CalibrationMode) =>
    getJson<DecisionResponse>("/forecast/decision", {
      delivery_date: deliveryDate,
      cutoff,
      mode,
    }),

  vintages: (deliveryDate: string, cutoff: string) =>
    getJson<VintagesResponse>("/forecast/vintages", {
      delivery_date: deliveryDate,
      cutoff,
    }),

  accuracySummary: (query: AccuracyWindowQuery) =>
    getJson<AccuracySummaryResponse>("/accuracy/summary", accuracyParams(query)),

  accuracyDaily: (query: AccuracyWindowQuery) =>
    getJson<AccuracySeriesResponse>("/accuracy/daily", accuracyParams(query)),

  accuracyByHour: (query: AccuracyWindowQuery) =>
    getJson<AccuracySeriesResponse>("/accuracy/by-hour", accuracyParams(query)),

  accuracyDistribution: (query: AccuracyWindowQuery) =>
    getJson<AccuracyDistributionResponse>("/accuracy/distribution", accuracyParams(query)),

  accuracyByHorizon: () => getJson<AccuracyByHorizonResponse>("/accuracy/by-horizon"),
};

export const queryKeys = {
  health: ["health"] as const,
  meta: ["meta"] as const,
  decision: (date: string, cutoff: string, mode: string) =>
    ["decision", date, cutoff, mode] as const,
  accuracySummary: (q: AccuracyWindowQuery) => ["accuracy", "summary", q] as const,
  accuracyDaily: (q: AccuracyWindowQuery) => ["accuracy", "daily", q] as const,
  accuracyByHour: (q: AccuracyWindowQuery) => ["accuracy", "by-hour", q] as const,
  accuracyDistribution: (q: AccuracyWindowQuery) => ["accuracy", "distribution", q] as const,
  accuracyByHorizon: (mode: string) => ["accuracy", "by-horizon", mode] as const,
};
