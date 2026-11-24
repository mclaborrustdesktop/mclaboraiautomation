"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CustomerSummary } from "@/lib/types";

/** Type-ahead picker for a customer (used on job and tracking forms). */
export function CustomerPicker({ value, label, onChange }: { value: number | null; label?: string; onChange: (id: number | null, name: string) => void }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<CustomerSummary[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!q.trim()) { setResults([]); return; }
    const t = setTimeout(() => {
      api.customers({ q, page_size: 8 }).then((r) => setResults(r.items)).catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  if (value) {
    return (
      <div className="flex items-center gap-3">
        <span className="rounded-md border border-brand-200 bg-brand-50 px-3 py-1.5 text-sm font-medium text-brand-800">{label || `Customer #${value}`}</span>
        <button type="button" className="btn-secondary !py-1" onClick={() => { onChange(null, ""); setQ(""); }}>Change</button>
      </div>
    );
  }

  return (
    <div className="relative max-w-md">
      <input className="input" placeholder="Type a customer name…" value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)} aria-label="Customer search" />
      {open && results.length > 0 && (
        <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg">
          {results.map((c) => (
            <li key={c.CustomerID}>
              <button type="button" className="flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-brand-50" onClick={() => { onChange(c.CustomerID, c.CustBusName); setOpen(false); }}>
                <span className="font-medium text-slate-900">{c.CustBusName}</span>
                <span className="text-xs text-slate-500">{c.City ? `${c.City}, ${c.State}` : ""}{c.type_name ? ` · ${c.type_name}` : ""}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
