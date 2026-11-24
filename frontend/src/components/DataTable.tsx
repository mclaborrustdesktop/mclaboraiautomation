"use client";

import type { ReactNode } from "react";
import { Pagination, Spinner } from "./ui";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
  align?: "left" | "right";
}

interface Props<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  page?: number;
  pageSize?: number;
  total?: number;
  onPageChange?: (page: number) => void;
}

export function DataTable<T>({ columns, rows, rowKey, loading, emptyMessage = "No records found.", onRowClick, page, pageSize, total, onPageChange }: Props<T>) {
  return (
    <div className="card overflow-hidden">
      <div className="max-h-[70vh] overflow-auto">
        <table className="table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={`${c.align === "right" ? "text-right" : ""} ${c.className ?? ""}`}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={columns.length}>
                  <Spinner />
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="py-10 text-center text-slate-500">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={rowKey(r)} className={onRowClick ? "cursor-pointer" : ""} onClick={onRowClick ? () => onRowClick(r) : undefined}>
                  {columns.map((c) => (
                    <td key={c.key} className={`${c.align === "right" ? "text-right tabular-nums" : ""} ${c.className ?? ""}`}>
                      {c.render(r)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {page !== undefined && pageSize !== undefined && total !== undefined && onPageChange && <Pagination page={page} pageSize={pageSize} total={total} onChange={onPageChange} />}
    </div>
  );
}
