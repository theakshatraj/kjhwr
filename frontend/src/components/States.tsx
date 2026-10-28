import type { ReactNode } from "react";

export function LoadingState({ label = "Loading\u2026" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 p-6 text-sm text-slate-500" role="status" aria-live="polite">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-sky-500" />
      {label}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 p-4" role="alert">
      <h3 className="text-sm font-semibold text-rose-800">Request failed</h3>
      <p className="mt-1 break-words text-sm text-rose-700">{message}</p>
      {onRetry ? (
        <button type="button" className="btn mt-3" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-sm text-slate-500">
      <p className="font-semibold text-slate-600">{title}</p>
      {children ? <div className="mt-1">{children}</div> : null}
    </div>
  );
}

export function SectionCard({
  title,
  subtitle,
  right,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
          {subtitle ? <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p> : null}
        </div>
        {right}
      </header>
      {children}
    </section>
  );
}
