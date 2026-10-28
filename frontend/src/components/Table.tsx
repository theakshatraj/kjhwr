import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  align?: "left" | "right";
  render: (row: T) => ReactNode;
  /** Optional plain-text value used when the table is exported to CSV. */
  csv?: (row: T) => string | number | null;
  title?: string;
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  dense = false,
  emptyMessage = "No rows",
}: {
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T, index: number) => string;
  dense?: boolean;
  emptyMessage?: string;
}) {
  if (rows.length === 0) {
    return <p className="p-4 text-sm text-slate-500">{emptyMessage}</p>;
  }

  const padding = dense ? "px-2 py-1" : "px-3 py-1.5";

  return (
    <div className="max-h-[520px] overflow-auto rounded-md border border-slate-200">
      <table className="min-w-full border-collapse text-xs">
        <thead className="sticky top-0 z-10 bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                title={column.title}
                scope="col"
                className={`whitespace-nowrap border-b border-slate-200 font-semibold text-slate-600 ${padding} ${
                  column.align === "right" ? "text-right" : "text-left"
                }`}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)} className="even:bg-slate-50/60 hover:bg-sky-50/60">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`whitespace-nowrap border-b border-slate-100 tabular-nums text-slate-700 ${padding} ${
                    column.align === "right" ? "text-right" : "text-left"
                  }`}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
