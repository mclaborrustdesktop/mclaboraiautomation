"use client";

import { AlertTriangle, ExternalLink, Info, Mail, MapPin, Phone } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { DuplicateMatch } from "@/lib/types";
import { Badge, statusTone } from "./ui";

/**
 * Debounced live duplicate check while a new record is being typed.
 * `pick` extracts the identifying fields; the check runs only when they change.
 */
export function useDuplicateCheck(
  check: (body: Record<string, unknown>) => Promise<{ matches: DuplicateMatch[] }>,
  pick: (values: Record<string, unknown>) => Record<string, unknown>,
  ready: (fields: Record<string, unknown>) => boolean,
) {
  const [matches, setMatches] = useState<DuplicateMatch[]>([]);
  const [fields, setFields] = useState<Record<string, unknown>>({});
  const key = JSON.stringify(fields);
  const req = useRef(0);

  useEffect(() => {
    if (!ready(fields)) { setMatches([]); return; }
    const id = ++req.current;
    const t = setTimeout(() => {
      check(fields).then((r) => { if (id === req.current) setMatches(r.matches); }).catch(() => {});
    }, 450);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const pickRef = useRef(pick);
  pickRef.current = pick;
  const onValuesChange = useCallback((values: Record<string, unknown>) => {
    const next = pickRef.current(values);
    setFields((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }, []);
  return { matches, onValuesChange };
}

export function DuplicateWarning({ matches, hrefBase, blocked, onCreateAnyway, busy }: {
  matches: DuplicateMatch[];
  hrefBase: string;
  /** true after the server refused the save - shows the confirm button */
  blocked?: boolean;
  onCreateAnyway?: () => void;
  busy?: boolean;
}) {
  if (matches.length === 0) return null;
  const likely = matches.some((m) => m.level === "likely");
  const tone = blocked || likely ? "border-amber-300 bg-amber-50" : "border-sky-200 bg-sky-50";
  const Icon = blocked || likely ? AlertTriangle : Info;
  return (
    <section className={`rounded-xl border p-4 animate-fade-up ${tone}`} role={blocked ? "alert" : "status"} aria-live="polite">
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${blocked || likely ? "text-amber-600" : "text-sky-600"}`} aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-slate-900">
            {blocked ? "This may already be on file - nothing was saved yet" : likely ? "Possible duplicate on file" : "Similar records on file"}
          </h2>
          <p className="mt-0.5 text-sm text-slate-600">
            {blocked ? "Open the existing record to update it instead, or confirm this really is a different one." : "Check these before creating a new record."}
          </p>
          <ul className="mt-3 space-y-2">
            {matches.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-white px-3 py-2 text-sm ring-1 ring-slate-200">
                <a href={`${hrefBase}/${m.id}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
                  {m.name} <ExternalLink className="h-3 w-3" />
                </a>
                {m.status && <Badge tone={statusTone(m.status)}>{m.status}</Badge>}
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${m.level === "likely" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>
                  {m.level === "likely" ? "Likely match" : "Possible match"}
                </span>
                <span className="text-xs text-slate-500">{m.reasons.join(" · ")}</span>
                <span className="flex w-full flex-wrap gap-x-3 text-xs text-slate-500">
                  {m.city && <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{m.city}{m.state ? `, ${m.state}` : ""}</span>}
                  {m.phone && <span className="inline-flex items-center gap-1"><Phone className="h-3 w-3" />{m.phone}</span>}
                  {m.email && <span className="inline-flex items-center gap-1"><Mail className="h-3 w-3" />{m.email}</span>}
                </span>
              </li>
            ))}
          </ul>
          {blocked && onCreateAnyway && (
            <button type="button" onClick={onCreateAnyway} disabled={busy} className="btn-secondary mt-3 !border-amber-300">
              {busy ? "Creating…" : "It's a different record - create anyway"}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
