/**
 * Narrow readers for the API's dynamic `dict[str, Any]` analytics blocks.
 *
 * The typed headline blocks come from `types.ts`; the analytics payloads are
 * declared as `Record<string, unknown>` there because their keys are built at
 * runtime on the backend. These helpers keep that boundary in one place so the
 * pages stay readable and a missing key degrades to `null` (rendered as a gap)
 * instead of throwing.
 */

export type Json = Record<string, unknown>;

function asObject(value: unknown): Json | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Json)
    : null;
}

export function record(source: unknown, key: string): Json | null {
  const object = asObject(source);
  return object ? asObject(object[key]) : null;
}

export function records(source: unknown, key: string): Json[] {
  const object = asObject(source);
  if (!object) return [];
  const value = object[key];
  return Array.isArray(value) ? value.map(asObject).filter((item): item is Json => item !== null) : [];
}

export function num(source: unknown, key: string): number | null {
  const object = asObject(source);
  if (!object) return null;
  const value = object[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function str(source: unknown, key: string): string | null {
  const object = asObject(source);
  if (!object) return null;
  const value = object[key];
  return typeof value === "string" ? value : null;
}

export function bool(source: unknown, key: string): boolean | null {
  const object = asObject(source);
  if (!object) return null;
  const value = object[key];
  return typeof value === "boolean" ? value : null;
}

export function numbers(source: unknown, key: string): number[] {
  const object = asObject(source);
  if (!object) return [];
  const value = object[key];
  return Array.isArray(value)
    ? value.filter((item): item is number => typeof item === "number" && Number.isFinite(item))
    : [];
}

export function strings(source: unknown, key: string): string[] {
  const object = asObject(source);
  if (!object) return [];
  const value = object[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}
