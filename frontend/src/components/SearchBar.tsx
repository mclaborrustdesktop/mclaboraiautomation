"use client";

import { Search, Sparkles, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { AISearchInfo } from "@/lib/types";
import { useAuth } from "@/lib/auth";

interface Props {
  placeholder: string;
  aiPlaceholder: string;
  examples?: string[];
  onSearch: (query: string, ai: boolean) => void;
  aiInfo?: AISearchInfo | null;
  busy?: boolean;
}

export function SearchBar({ placeholder, aiPlaceholder, examples = [], onSearch, aiInfo, busy }: Props) {
  const { hasFeature } = useAuth();
  // AI search is always on for users who have the permission; others get plain keyword search.
  const ai = hasFeature("ai.search");
  const [q, setQ] = useState("");

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    onSearch(q.trim(), ai);
  };
  const clear = () => {
    setQ("");
    onSearch("", ai);
  };

  const filterEntries = aiInfo ? Object.entries(aiInfo.filters) : [];

  return (
    <div className="space-y-2">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[260px] flex-1">
          {ai ? <Sparkles className="pointer-events-none absolute top-2.5 left-3 h-4 w-4 text-violet-500" aria-hidden /> : <Search className="pointer-events-none absolute top-2.5 left-3 h-4 w-4 text-slate-400" aria-hidden />}
          <input
            className={`input !pl-9 ${ai ? "border-violet-300 focus:border-violet-500 focus:ring-violet-100" : ""}`}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={ai ? aiPlaceholder : placeholder}
            aria-label={ai ? "AI search" : "Search"}
          />
          {q && (
            <button type="button" onClick={clear} className="absolute top-2 right-2 rounded p-0.5 text-slate-400 hover:text-slate-600" aria-label="Clear search">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <button type="submit" className="btn-primary" disabled={busy}>
          {ai && <Sparkles className="h-4 w-4" />}
          {busy ? "Searching…" : ai ? "AI Search" : "Search"}
        </button>
      </form>

      {ai && !aiInfo && examples.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
          <span>Try:</span>
          {examples.map((ex) => (
            <button
              key={ex}
              type="button"
              className="rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-xs text-slate-700 hover:border-violet-300 hover:bg-violet-50"
              onClick={() => {
                setQ(ex);
                onSearch(ex, true);
              }}
            >
              {ex}
            </button>
          ))}
        </div>
      )}

      {aiInfo && (
        <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-violet-200 bg-violet-50/60 px-3 py-2 text-xs text-slate-700">
          <Sparkles className="h-3.5 w-3.5 text-violet-500" aria-hidden />
          <span className="font-medium">{aiInfo.mode === "claude" ? "Claude" : "Built-in parser"} understood:</span>
          <span className="text-slate-600">{aiInfo.interpretation}</span>
          {filterEntries.map(([k, v]) => (
            <span key={k} className="chip">
              {k.replace(/_/g, " ")}: {String(v)}
            </span>
          ))}
          {aiInfo.keywords.map((k) => (
            <span key={`kw-${k}`} className="chip !border-slate-200 !bg-white !text-slate-700">
              “{k}”
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
