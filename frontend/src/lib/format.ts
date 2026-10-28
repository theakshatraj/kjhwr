/**
 * Number and unit formatting.
 *
 * Two rules hold everywhere in this app:
 *   1. a missing value renders as an explicit gap (`MISSING`), never as 0 - a
 *      missing forecast must not look like a calm day;
 *   2. the unit is part of the rendered string, so no axis or card can show a
 *      bare number without saying whether it is MW, MWh, hours or a count.
 */

/** Rendered for anything null / undefined / NaN. */
export const MISSING = "\u2014";

/** "12,345" - grouping only, for counts and MW with no decimals. */
export function formatNumber(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  return value.toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatCount(value: number | null | undefined): string {
  return formatNumber(value, 0);
}

export function formatMw(value: number | null | undefined, digits = 0): string {
  const text = formatNumber(value, digits);
  return text === MISSING ? MISSING : `${text} MW`;
}

export function formatMwh(value: number | null | undefined, digits = 0): string {
  const text = formatNumber(value, digits);
  return text === MISSING ? MISSING : `${text} MWh`;
}

export function formatHours(value: number | null | undefined, digits = 1): string {
  const text = formatNumber(value, digits);
  return text === MISSING ? MISSING : `${text} h`;
}

/** Signed MW, so an over-forecast is unmistakably "+". Positive = overestimate. */
export function formatSignedMw(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, digits)} MW`;
}

/** A fraction in [0, 1] rendered as a percentage, e.g. 0.913 -> "91.3%". */
export function formatFraction(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  return `${formatNumber(value * 100, digits)}%`;
}

/** A number already expressed in percent, e.g. 12.5 -> "12.5%". */
export function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  return `${formatNumber(value, digits)}%`;
}

/**
 * ISO-8601 UTC rendered explicitly in UTC (never in the browser's local zone),
 * so a timestamp can never be silently shifted by the viewer's clock.
 */
export function formatUtc(iso: string | null | undefined, withDate = true): string {
  if (!iso) return MISSING;
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return MISSING;
  const text = parsed.toISOString();
  const date = text.slice(0, 10);
  const time = text.slice(11, 16);
  return withDate ? `${date} ${time} UTC` : `${time} UTC`;
}

/** "HH:MM" local delivery time as supplied by the API. */
export function formatLocalTime(value: string | null | undefined): string {
  return value && value.trim() !== "" ? value : MISSING;
}

/** "48 of 48 intervals" - the honest coverage statement for any sum. */
export function formatIntervals(withForecast: number, expected: number): string {
  return `${formatCount(withForecast)} of ${formatCount(expected)} intervals`;
}
