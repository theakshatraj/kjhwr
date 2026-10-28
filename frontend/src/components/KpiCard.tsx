import type { ReactNode } from "react";

type Tone = "default" | "accent" | "warn" | "muted";

const VALUE_TONE: Record<Tone, string> = {
  default: "text-slate-900",
  accent: "text-sky-700",
  warn: "text-amber-700",
  muted: "text-slate-400",
};

export function KpiCard({
  label,
  value,
  sub,
  tone = "default",
  badge,
  title,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  badge?: ReactNode;
  title?: string;
}) {
  return (
    <div className="card" title={title}>
      <div className="flex items-start justify-between gap-2">
        <p className="card-title">{label}</p>
        {badge}
      </div>
      <p className={`mt-2 text-xl font-semibold tabular-nums ${VALUE_TONE[tone]}`}>{value}</p>
      {sub ? <p className="mt-1 text-xs text-slate-500">{sub}</p> : null}
    </div>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "danger";
}) {
  const tones = {
    neutral: "bg-slate-100 text-slate-600",
    ok: "bg-emerald-100 text-emerald-700",
    warn: "bg-amber-100 text-amber-800",
    danger: "bg-rose-100 text-rose-700",
  } as const;
  return <span className={`badge ${tones[tone]}`}>{children}</span>;
}
