"use client";

import { History } from "lucide-react";
import { useEffect, useState } from "react";
import { api, describeError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/types";
import { Section } from "./ui";

const ACTION_LABEL: Record<string, string> = {
  create: "created", update: "changed", delete: "deleted", note: "added a note", "create.duplicate_confirmed": "created (duplicate confirmed)",
};

function describe(entry: AuditEntry): string {
  const verb = ACTION_LABEL[entry.action.split(".").slice(1).join(".")] ?? entry.action;
  return `${entry.initials ?? "?"} ${verb}`;
}

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (Array.isArray(v)) return `${v.length} item${v.length === 1 ? "" : "s"}`;
  if (typeof v === "object") return JSON.stringify(v);
  const s = String(v);
  return s.length > 60 ? s.slice(0, 57) + "…" : s;
}

/** The change history of one record, from the website's own log (who, when, which fields). */
export function ChangeHistory({ entity, id, refreshKey }: { entity: "employees" | "customers" | "projects" | "tracking"; id: number; refreshKey?: unknown }) {
  const [items, setItems] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    api.history(entity, id).then((r) => { if (alive) setItems(r.items); }).catch((e) => { if (alive) setError(describeError(e)); });
    return () => { alive = false; };
  }, [entity, id, refreshKey]);
  return (
    <Section title="History">
      {error && <p className="text-sm text-red-600">{error}</p>}
      {items && items.length === 0 && <p className="text-sm text-slate-500">No changes recorded through the website yet.</p>}
      {items && items.length > 0 && (
        <ul className="space-y-2">
          {items.map((e) => {
            const changed = Object.keys(e.changes ?? {});
            return (
              <li key={e.id} className="rounded-md border border-slate-100 bg-slate-50 p-2 text-sm">
                <button type="button" className="flex w-full items-start gap-2 text-left" onClick={() => setOpen(open === e.id ? null : e.id)} aria-expanded={open === e.id}>
                  <History className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" aria-hidden />
                  <span className="flex-1">
                    <span className="text-slate-800">{describe(e)}</span>
                    {changed.length > 0 && <span className="text-slate-500"> · {changed.length} field{changed.length === 1 ? "" : "s"}</span>}
                    {e.summary && e.action.endsWith(".note") && <span className="text-slate-600"> · “{e.summary}”</span>}
                    <span className="block text-xs text-slate-500">{formatDateTime(e.at)}</span>
                  </span>
                </button>
                {open === e.id && changed.length > 0 && (
                  <table className="mt-2 w-full text-xs">
                    <tbody>
                      {changed.map((k) => (
                        <tr key={k} className="border-t border-slate-100">
                          <td className="py-1 pr-2 font-medium text-slate-600">{k}</td>
                          <td className="py-1 pr-2 text-slate-500">{show(e.changes[k].from)}</td>
                          <td className="py-1 text-slate-800">{show(e.changes[k].to)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

/** Shown when a save was refused because the record changed since the form was opened. */
export function StaleNotice({ message, onReload }: { message: string | null; onReload: () => void }) {
  if (!message) return null;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" role="alert">
      <span className="flex-1">{message}</span>
      <button type="button" className="btn-secondary !py-1" onClick={onReload}>Reload record</button>
    </div>
  );
}
