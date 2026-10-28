import type { ReactNode } from "react";

type Tone = "info" | "warn" | "danger" | "neutral";

const TONES: Record<Tone, string> = {
  info: "border-sky-200 bg-sky-50 text-sky-900",
  warn: "border-amber-200 bg-amber-50 text-amber-900",
  danger: "border-rose-200 bg-rose-50 text-rose-900",
  neutral: "border-slate-200 bg-slate-50 text-slate-700",
};

export function Notice({
  tone = "info",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  return (
    <div className={`rounded-lg border p-3 text-sm ${TONES[tone]}`} role={tone === "danger" ? "alert" : undefined}>
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={title ? "mt-1" : undefined}>{children}</div>
    </div>
  );
}
