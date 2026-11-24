"use client";

import { AlertTriangle, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import type { SyncStatus } from "@/lib/types";

const REFRESH_MS = 10 * 60 * 1000;

/** "Information as of ..." for the search-only mirror, with a warning when the last refresh from the office is too old. */
export function SyncBanner() {
  const { user, searchOnly } = useAuth();
  const [status, setStatus] = useState<SyncStatus | null>(null);
  useEffect(() => {
    if (!user) return;
    let alive = true;
    const load = () => api.syncStatus().then((s) => { if (alive) setStatus(s); }).catch(() => { /* the demo has no sync */ });
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => { alive = false; window.clearInterval(timer); };
  }, [user]);
  if (!status?.applies) return null;
  const last = status.last_success_at ? formatDateTime(status.last_success_at) : null;
  if (status.level === "fresh" || status.level === undefined) {
    return (
      <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50 px-4 py-1.5 text-xs text-slate-600 md:px-8" role="status">
        <RefreshCw className="h-3.5 w-3.5 text-slate-400" aria-hidden />
        <span>{searchOnly ? "Search-only copy of " : "Copy of "}{status.source}. Information as of <strong className="font-medium text-slate-800">{last}</strong>; refreshed twice a day. Changes are made in the office system.</span>
      </div>
    );
  }
  const severe = status.level === "stale" || status.level === "never";
  return (
    <div className={`flex items-start gap-2 border-b px-4 py-2 text-sm md:px-8 ${severe ? "border-red-200 bg-red-50 text-red-900" : "border-amber-200 bg-amber-50 text-amber-900"}`} role="alert">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span>
        <strong className="font-semibold">{severe ? "Information may be outdated." : "Information is getting old."}</strong>{" "}
        {status.level === "never" ? `Nothing has been loaded from ${status.source} yet.` : `Last update from ${status.source}: ${last} (${Math.round(status.age_hours ?? 0)} hours ago; updates are expected every ${status.stale_after_hours} hours).`}
        {status.last_run?.status === "failed" && " The latest refresh attempt failed; the office has been notified."}
      </span>
    </div>
  );
}
