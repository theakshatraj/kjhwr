import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, queryKeys } from "../api/client";

const NAV = [
  { to: "/", label: "Decision" },
  { to: "/accuracy", label: "Accuracy" },
  { to: "/about", label: "Methodology" },
];

function navClass({ isActive }: { isActive: boolean }): string {
  return [
    "rounded-md px-3 py-1.5 text-sm font-medium transition",
    isActive ? "bg-sky-600 text-white" : "text-slate-600 hover:bg-slate-200",
  ].join(" ");
}

export default function Layout({ children }: { children: ReactNode }) {
  // The footer carries the snapshot caveat and attribution straight from /api/meta.
  const meta = useQuery({ queryKey: queryKeys.meta, queryFn: api.meta, retry: 0 });

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-base font-semibold text-slate-900">
              Wind Forecast Decision Portal
            </p>
            <p className="text-xs text-slate-500">
              Day-ahead UK wind: the forecast visible at the assumed decision cutoff
            </p>
          </div>
          <nav className="flex gap-1" aria-label="Primary">
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} className={navClass} end={item.to === "/"}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">{children}</main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto max-w-7xl space-y-1 px-4 py-4 text-xs text-slate-500">
          <p>
            Wind planning buffer indicator, not a procurement recommendation: demand and other
            supply are not included.
          </p>
          {meta.data ? (
            <>
              <p>{meta.data.snapshotNotice}</p>
              <p>{meta.data.attribution}</p>
            </>
          ) : null}
        </div>
      </footer>
    </div>
  );
}
