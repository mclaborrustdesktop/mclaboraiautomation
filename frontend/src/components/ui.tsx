"use client";

import { Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "green" | "amber" | "red" | "blue" | "violet" }) {
  const tones: Record<string, [string, string]> = {
    slate: ["bg-slate-100 text-slate-700", "bg-slate-400"],
    green: ["bg-emerald-50 text-emerald-700", "bg-emerald-500"],
    amber: ["bg-amber-50 text-amber-700", "bg-amber-500"],
    red: ["bg-red-50 text-red-700", "bg-red-500"],
    blue: ["bg-brand-50 text-brand-700", "bg-brand-500"],
    violet: ["bg-violet-50 text-violet-700", "bg-violet-500"],
  };
  const [cls, dot] = tones[tone];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${cls}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden />
      {children}
    </span>
  );
}

export function statusTone(status: string | null | undefined): "slate" | "green" | "amber" | "red" | "blue" | "violet" {
  switch ((status ?? "").toLowerCase()) {
    case "active":
    case "active account":
    case "available":
    case "completed":
      return "green";
    case "on assignment":
    case "quoted":
    case "contacted":
      return "blue";
    case "pending":
    case "applicant":
    case "prospect":
    case "new lead":
    case "on hold":
      return "amber";
    case "collections":
    case "do not use":
    case "cancelled":
    case "lost":
      return "red";
    default:
      return "slate";
  }
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-slate-500" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
      {message}
    </div>
  );
}

export function SuccessBox({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status">
      {message}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Section({ title, children, actions, className = "" }: { title: string; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card p-5 ${className}`}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function Field({ label, value, className = "" }: { label: string; value: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{label}</div>
      <div className="mt-0.5 text-sm text-slate-900">{value ?? "—"}</div>
    </div>
  );
}

export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-3 py-2 text-sm text-slate-600">
      <span>
        {from}–{to} of {total.toLocaleString()}
      </span>
      <div className="flex items-center gap-1">
        <button className="btn-secondary !px-2.5 !py-1" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          Prev
        </button>
        <span className="px-2 tabular-nums">
          {page} / {pages}
        </span>
        <button className="btn-secondary !px-2.5 !py-1" disabled={page >= pages} onClick={() => onChange(page + 1)}>
          Next
        </button>
      </div>
    </div>
  );
}

export function Modal({ title, children, onClose, wide = false }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 sm:p-8" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className={`card w-full ${wide ? "max-w-4xl" : "max-w-2xl"} p-5 shadow-xl`} onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
          <button className="btn-secondary !px-2 !py-1" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
