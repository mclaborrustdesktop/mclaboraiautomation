"use client";

/** Always-visible label saying which data the site is showing, so one environment is never mistaken for another. */
const STYLES: Record<string, { text: string; hint: string; cls: string }> = {
  demo: { text: "DEMO", hint: "Synthetic data. Not connected to the McLabor database.", cls: "bg-sky-100 text-sky-800 ring-sky-200" },
  staging: { text: "STAGING · test copy", hint: "A restored copy of the real McLabor data, for testing. Read-only. Not the live database.", cls: "bg-amber-100 text-amber-900 ring-amber-300" },
  production: { text: "PRODUCTION · live data", hint: "The live McLabor database. Read-only unless writes were approved.", cls: "bg-red-100 text-red-800 ring-red-300" },
};

export function EnvironmentBadge({ environment, className = "" }: { environment?: string | null; className?: string }) {
  const s = STYLES[environment ?? "demo"] ?? STYLES.demo;
  return (
    <span title={s.hint} className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-wide whitespace-nowrap ring-1 ${s.cls} ${className}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {s.text}
    </span>
  );
}
