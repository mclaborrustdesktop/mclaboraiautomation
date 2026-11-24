"use client";

import {
  AlarmClock, ArrowRight, ArrowUp, BadgeCheck, Briefcase, Building2, CalendarClock, Check, ChevronDown, ChevronLeft, ChevronRight, Clock, Download,
  FileWarning, HardHat, LayoutGrid, Lightbulb, List, Mail, MapPin, Mic, PauseCircle, Pencil, Phone, Plane, Plus, RotateCcw, ShieldCheck, Sparkles,
  TrendingUp, Users, Wallet, Wand2, X,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState,
  type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type RefObject,
} from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { Badge, ErrorBox, statusTone } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatMoney } from "@/lib/format";
import type { AISearchInfo, CustomerSummary, EmployeeSummary, Entity, Facet, Filters, ProjectSummary } from "@/lib/types";

/* ------------------------------------------------------------------ config */

type Icon = typeof HardHat;
type Quick = { icon: Icon; title: string; hint: string; prompt: string; tone: string };

const ENTITY: Record<Entity, { label: string; noun: string; icon: Icon; feature: string; placeholder: string; fallback: string[]; quick: Quick[]; builders: string[] }> = {
  employees: {
    label: "Employees", noun: "workers", icon: HardHat, feature: "employees.view",
    placeholder: "licensed journeyman electricians in Worcester with 5+ years who will travel",
    fallback: ["licensed electricians in Worcester who will travel", "plumbers with OSHA 30 under $40", "carpenters with 10+ years in Boston"],
    builders: ["electricians", "in Boston", "with 5+ years", "who will travel", "licensed", "with OSHA 30", "under $40"],
    quick: [
      { icon: Plane, title: "Travel-ready electricians", hint: "Licensed and willing to travel", prompt: "licensed electricians who will travel", tone: "from-violet-500 to-fuchsia-500" },
      { icon: AlarmClock, title: "Licenses expiring", hint: "Renewals due in 60 days", prompt: "licenses expiring in 60 days", tone: "from-rose-500 to-orange-500" },
      { icon: BadgeCheck, title: "Seasoned foremen", hint: "10+ years in the trade", prompt: "foreman with 10+ years", tone: "from-sky-500 to-indigo-500" },
      { icon: Wallet, title: "Budget crew", hint: "Laborers under $30/hr", prompt: "laborers under $30", tone: "from-emerald-500 to-teal-500" },
    ],
  },
  customers: {
    label: "Customers", noun: "customers", icon: Building2, feature: "customers.view",
    placeholder: "active general contractors in Boston with jobs running",
    fallback: ["active general contractors in Boston", "customers on hold", "customers with revenue over 100k"],
    builders: ["general contractors", "in Boston", "with active jobs", "on hold", "without a contract", "revenue over 100k"],
    quick: [
      { icon: Building2, title: "Active GCs", hint: "General contractors in good standing", prompt: "active general contractors", tone: "from-violet-500 to-fuchsia-500" },
      { icon: PauseCircle, title: "Accounts on hold", hint: "Need follow-up before dispatch", prompt: "customers on hold", tone: "from-rose-500 to-orange-500" },
      { icon: FileWarning, title: "Missing contracts", hint: "No signed contract on file", prompt: "customers without a contract", tone: "from-amber-500 to-yellow-500" },
      { icon: TrendingUp, title: "Top accounts", hint: "Revenue over $500k", prompt: "revenue over 500k", tone: "from-emerald-500 to-teal-500" },
    ],
  },
  projects: {
    label: "Jobs", noun: "jobs", icon: Briefcase, feature: "projects.view",
    placeholder: "active jobs in Massachusetts that are not manned",
    fallback: ["active jobs in Massachusetts that are not manned", "jobs starting this month", "OCIP jobs needing at least 5 workers"],
    builders: ["active", "in Massachusetts", "not manned", "starting this month", "OCIP", "needing at least 4 workers"],
    quick: [
      { icon: Users, title: "Needs crew", hint: "Active jobs not yet manned", prompt: "active jobs that are not manned", tone: "from-rose-500 to-orange-500" },
      { icon: CalendarClock, title: "Starting soon", hint: "Jobs starting this month", prompt: "jobs starting this month", tone: "from-violet-500 to-fuchsia-500" },
      { icon: ShieldCheck, title: "OCIP jobs", hint: "Owner-controlled insurance", prompt: "ocip jobs", tone: "from-sky-500 to-indigo-500" },
      { icon: HardHat, title: "Large crews", hint: "5+ workers needed", prompt: "jobs needing at least 5 workers", tone: "from-emerald-500 to-teal-500" },
    ],
  },
};

const FILTER_LABELS: Record<string, string> = {
  state: "State", city: "City", zip: "ZIP", trade: "Trade", qualification: "Qualification", status: "Status", customer_type: "Type", licensed: "Licensed",
  osha: "OSHA", will_travel: "Will travel", us_citizen: "US citizen", i9_complete: "I-9", min_years: "Min years", max_years: "Max years",
  min_rate: "Min $/hr", max_rate: "Max $/hr", license_expiring_days: "License expiring (days)", on_hold: "On hold", contract_on_file: "Contract",
  min_revenue: "Min revenue", has_active_projects: "Active jobs", industry: "Industry", salesman: "Sales rep", customer: "Customer",
  manned: "Manned", min_employees: "Min workers", ocip: "OCIP", start_window: "Starts",
};

function describeFilter(key: string, value: unknown): string {
  const label = FILTER_LABELS[key] ?? key.replace(/_/g, " ");
  if (typeof value === "boolean") return value ? label : `Not ${label.toLowerCase()}`;
  if (key === "min_revenue") return `${label} $${Number(value).toLocaleString()}`;
  if (key === "start_window") return `${label} ${String(value).replace(/_/g, " ")}`;
  return `${label}: ${value}`;
}

type Row = EmployeeSummary | CustomerSummary | ProjectSummary;
type SpeechCtor = new () => { lang: string; interimResults: boolean; onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void; onend: () => void; onerror: () => void; start(): void; stop(): void };
type Turn = {
  id: number;
  kind: "ask" | "edit";
  text: string;
  refine: boolean;
  reply?: { filters: Filters; keywords: string[]; summary?: string; total: number; mode: AISearchInfo["mode"] };
  error?: string;
};
type Recent = { entity: Entity; q: string };

const THINKING = ["Reading your request", "Matching trades, places & filters", "Ranking the best fits"];
const RECENT_KEY = "mclabor.ai.recent";

function loadRecent(): Recent[] {
  try { const v = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]"); return Array.isArray(v) ? v.slice(0, 8) : []; } catch { return []; }
}
function saveRecent(list: Recent[]) {
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, 8))); } catch { /* storage unavailable */ }
}

/* -------------------------------------------------------------------- page */

export default function SearchPage() {
  return (
    <AppShell>
      <RequireFeature feature="ai.search">
        <Suspense fallback={null}>
          <Studio />
        </Suspense>
      </RequireFeature>
    </AppShell>
  );
}

function Studio() {
  const router = useRouter();
  const params = useSearchParams();
  const { hasFeature } = useAuth();
  const [entity, setEntity] = useState<Entity>((params.get("entity") as Entity) || "employees");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<{ mode: "claude" | "heuristic"; examples: Record<Entity, string[]> } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<AISearchInfo | null>(null);
  const [facets, setFacets] = useState<Facet[]>([]);
  const [items, setItems] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [sort, setSort] = useState("relevance");
  const [refine, setRefine] = useState(true);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [previewIdx, setPreviewIdx] = useState<number | null>(null);
  const [listening, setListening] = useState(false);
  const [view, setView] = useState<"grid" | "list">("grid");
  const [openFacet, setOpenFacet] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loadingMore, setLoadingMore] = useState(false);
  const [recent, setRecent] = useState<Recent[]>([]);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const reqId = useRef(0);
  const started = turns.length > 0 || busy;
  const preview = previewIdx != null ? items[previewIdx] ?? null : null;

  useEffect(() => { api.searchStatus().then(setStatus).catch(() => {}); setRecent(loadRecent()); }, []);

  const remember = (ent: Entity, text: string) => {
    setRecent((list) => {
      const next = [{ entity: ent, q: text }, ...list.filter((r) => !(r.entity === ent && r.q.toLowerCase() === text.toLowerCase()))].slice(0, 8);
      saveRecent(next);
      return next;
    });
  };

  const run = useCallback(async (
    body: { query?: string; filters?: Filters; keywords?: string[]; refine?: boolean },
    turn: { kind: Turn["kind"]; text: string } | null,
    ent: Entity = entity,
    srt: string = sort,
  ) => {
    const id = ++reqId.current;
    if (turn) setTurns((t) => [...t, { id, ...turn, refine: !!body.refine }]);
    setBusy(true); setError(null); setOpenFacet(null);
    try {
      const res = await api.aiSearchAdvanced<Row>({
        entity: ent, sort: srt, ...body,
        ...(body.refine && info ? { base_filters: info.filters, base_keywords: info.keywords } : {}),
      });
      if (id !== reqId.current) { if (turn) setTurns((t) => t.filter((x) => x.id !== id)); return; }
      setInfo(res.ai); setFacets(res.facets ?? []); setItems(res.items); setTotal(res.total); setPreviewIdx(null); setPage(1);
      if (turn) setTurns((t) => t.map((x) => (x.id === id ? { ...x, reply: { filters: res.ai.filters, keywords: res.ai.keywords, summary: res.ai.summary, total: res.total, mode: res.ai.mode } } : x)));
    } catch (e) {
      if (id !== reqId.current) return;
      const msg = describeError(e);
      if (turn) setTurns((t) => t.map((x) => (x.id === id ? { ...x, error: msg } : x))); else setError(msg);
    } finally {
      if (id === reqId.current) setBusy(false);
    }
  }, [entity, sort, info]);

  // initial query from the URL (e.g. from a list page)
  useEffect(() => {
    const initial = params.get("q");
    if (initial) run({ query: initial }, { kind: "ask", text: initial });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // keyboard: "/" focuses the prompt, Esc closes, ←/→ browse the preview
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement;
      if (e.key === "Escape") { setPreviewIdx(null); setOpenFacet(null); }
      if (e.key === "/" && !typing) { e.preventDefault(); inputRef.current?.focus(); }
      if (!typing && previewIdx != null && (e.key === "ArrowRight" || e.key === "ArrowDown")) { e.preventDefault(); setPreviewIdx((i) => (i == null ? i : Math.min(i + 1, items.length - 1))); }
      if (!typing && previewIdx != null && (e.key === "ArrowLeft" || e.key === "ArrowUp")) { e.preventDefault(); setPreviewIdx((i) => (i == null ? i : Math.max(i - 1, 0))); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [previewIdx, items.length]);

  const focusInput = () => setTimeout(() => inputRef.current?.focus(), 0);
  const ask = (text: string, asRefine = started && refine, ent: Entity = entity) => {
    const t = text.trim();
    if (!t || busy) return;
    setQ("");
    remember(ent, t);
    run({ query: t, refine: asRefine && !!info }, { kind: "ask", text: t }, ent);
  };
  const edit = (filters: Filters, keywords: string[], label: string) => run({ filters, keywords, query: info?.query }, { kind: "edit", text: label });
  const removeFilter = (k: string) => { if (!info) return; const f = { ...info.filters }; const label = describeFilter(k, f[k]); delete f[k]; edit(f, info.keywords, `Removed “${label}”`); };
  const removeKeyword = (kw: string) => info && edit(info.filters, info.keywords.filter((k) => k !== kw), `Removed keyword “${kw}”`);
  const clearAll = () => info && edit({}, [], "Cleared all filters");
  const applyPatch = (label: string, patch: Filters) => info && edit({ ...info.filters, ...patch }, info.keywords, `Added “${label}”`);
  const toggleFacet = (f: Facet, value: string) => {
    if (!info) return;
    const next = { ...info.filters };
    const on = next[f.key] === value;
    if (on) delete next[f.key]; else next[f.key] = value;
    edit(next, info.keywords, on ? `Cleared ${f.label}` : `${f.label}: ${value}`);
  };
  const togglePhrase = (phrase: string) => {
    setQ((cur) => {
      const re = new RegExp(`\\s*${phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "i");
      return re.test(cur) ? cur.replace(re, "").trim() : `${cur.trim()} ${phrase}`.trim();
    });
    focusInput();
  };
  const reset = () => { reqId.current++; setBusy(false); setQ(""); setInfo(null); setItems([]); setFacets([]); setTotal(0); setTurns([]); setPreviewIdx(null); setError(null); setRefine(true); focusInput(); };
  const switchEntity = (e: Entity) => {
    if (e === entity) return;
    const lastAsk = [...turns].reverse().find((t) => t.kind === "ask")?.text;
    setEntity(e); setInfo(null); setItems([]); setFacets([]); setTotal(0); setPreviewIdx(null); setTurns([]);
    if (lastAsk) run({ query: lastAsk }, { kind: "ask", text: lastAsk }, e);
  };
  // next page of the same search, fetched from the server and added below the results already shown
  const loadMore = async () => {
    if (!info || loadingMore || busy) return;
    setLoadingMore(true);
    try {
      const res = await api.aiSearchAdvanced<Row>({ entity, sort, filters: info.filters, keywords: info.keywords, query: info.query, page: page + 1 });
      setItems((cur) => { const seen = new Set(cur.map(rowId)); return [...cur, ...res.items.filter((r) => !seen.has(rowId(r)))]; });
      setTotal(res.total); setPage(page + 1);
    } catch (e) { setError(describeError(e)); } finally { setLoadingMore(false); }
  };
  const changeSort = (s: string) => { setSort(s); if (info) run({ filters: info.filters, keywords: info.keywords, query: info.query }, null, entity, s); };
  const editTurn = (t: Turn) => { setQ(t.text); setRefine(false); focusInput(); };

  const speech = typeof window !== "undefined" ? ((window as unknown as { SpeechRecognition?: SpeechCtor; webkitSpeechRecognition?: SpeechCtor }).SpeechRecognition ?? (window as unknown as { webkitSpeechRecognition?: SpeechCtor }).webkitSpeechRecognition) : undefined;
  const listen = () => {
    if (!speech || listening) return;
    const rec = new speech();
    rec.lang = "en-US"; rec.interimResults = false;
    rec.onresult = (e) => ask(e.results[0][0].transcript);
    rec.onend = () => setListening(false); rec.onerror = () => setListening(false);
    setListening(true); rec.start();
  };

  const entities = (Object.keys(ENTITY) as Entity[]).filter((e) => hasFeature(ENTITY[e].feature));
  const examples = status?.examples[entity]?.length ? status.examples[entity] : ENTITY[entity].fallback;
  const sortOptions = entity === "employees" ? [["relevance", "Best match"], ["years", "Most experienced"], ["rate", "Lowest rate"], ["name", "Name"]] : entity === "customers" ? [["relevance", "Best match"], ["revenue", "Revenue"], ["name", "Name"]] : [["relevance", "Best match"], ["start", "Start date"], ["name", "Name"]];
  const filterCount = info ? Object.keys(info.filters).length + info.keywords.length : 0;

  const composer = (
    <Composer
      inputRef={inputRef} value={q} onChange={setQ} onSubmit={() => ask(q)} busy={busy}
      entity={entity} entities={entities} onEntity={switchEntity}
      started={started} refine={refine} onRefine={setRefine} hasInfo={!!info}
      examples={examples} canListen={!!speech} listening={listening} onListen={listen} onPhrase={togglePhrase}
    />
  );

  /* ---------- Start screen ---------- */
  if (!started) {
    const recentHere = recent.filter((r) => entities.includes(r.entity)).slice(0, 5);
    return (
      <div className="relative mx-auto max-w-4xl py-6 md:py-10">
        <div className="pointer-events-none absolute -top-10 left-1/2 -z-10 h-72 w-[38rem] max-w-full -translate-x-1/2 rounded-full bg-gradient-to-r from-violet-200/60 via-pink-200/50 to-amber-200/60 blur-3xl" aria-hidden />

        <div className="text-center animate-fade-up">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-slate-600 shadow-xs ring-1 ring-slate-200 backdrop-blur">
            <span className={`h-1.5 w-1.5 rounded-full ${status?.mode === "claude" ? "bg-violet-500" : "bg-emerald-500"}`} />
            {status ? (status.mode === "claude" ? "Powered by Claude" : "Built-in AI parser") : "AI Search"}
          </span>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight text-slate-900 md:text-5xl">
            What should we <span className="ai-text">find</span> today?
          </h1>
          <p className="mx-auto mt-3 max-w-xl text-sm text-slate-500 md:text-base">Describe the {ENTITY[entity].noun} you need, like you would to a coworker. Tap the chips to build your request.</p>
        </div>

        <div className="mx-auto mt-8 max-w-3xl animate-fade-up" style={{ animationDelay: "60ms" }}>{composer}</div>

        {/* Quick-start tiles */}
        <div className="mt-10 animate-fade-up" style={{ animationDelay: "120ms" }}>
          <SectionTitle icon={Wand2}>Quick start</SectionTitle>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {ENTITY[entity].quick.map((t, i) => (
              <button key={t.title} type="button" onClick={() => ask(t.prompt, false)}
                className="group card relative overflow-hidden p-4 text-left transition hover:-translate-y-1 hover:shadow-lg animate-fade-up" style={{ animationDelay: `${160 + i * 50}ms` }}>
                <span className={`flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br ${t.tone} text-white shadow-md transition group-hover:scale-110 group-hover:rotate-3`}><t.icon className="h-5 w-5" /></span>
                <div className="mt-3 text-sm font-semibold text-slate-900">{t.title}</div>
                <div className="mt-0.5 text-xs text-slate-500">{t.hint}</div>
                <ArrowRight className="absolute top-4 right-4 h-4 w-4 -translate-x-1 text-slate-300 opacity-0 transition group-hover:translate-x-0 group-hover:text-violet-500 group-hover:opacity-100" />
              </button>
            ))}
          </div>
        </div>

        <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* Example prompts */}
          <div className="animate-fade-up" style={{ animationDelay: "220ms" }}>
            <SectionTitle icon={Lightbulb}>Try asking</SectionTitle>
            <div className="flex flex-wrap gap-2">
              {examples.map((ex) => (
                <button key={ex} type="button" onClick={() => ask(ex, false)} className="ai-pill text-left">
                  <Sparkles className="h-3.5 w-3.5 shrink-0 text-violet-500" /> {ex}
                </button>
              ))}
            </div>
          </div>

          {/* Recent */}
          <div className="animate-fade-up" style={{ animationDelay: "260ms" }}>
            <SectionTitle icon={Clock} action={recentHere.length > 0 ? <button type="button" onClick={() => { setRecent([]); saveRecent([]); }} className="text-xs text-slate-400 hover:text-slate-700">Clear</button> : undefined}>Recent searches</SectionTitle>
            {recentHere.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-200 bg-white/60 p-4 text-sm text-slate-400">Your searches will show up here so you can rerun them in one click.</div>
            ) : (
              <ul className="card divide-y divide-slate-100 overflow-hidden">
                {recentHere.map((r) => { const I = ENTITY[r.entity].icon; return (
                  <li key={`${r.entity}-${r.q}`}>
                    <button type="button" onClick={() => { if (r.entity !== entity) setEntity(r.entity); ask(r.q, false, r.entity); }} className="group flex w-full items-center gap-3 px-3.5 py-2.5 text-left text-sm transition hover:bg-violet-50/60">
                      <I className="h-4 w-4 shrink-0 text-slate-400 group-hover:text-violet-500" />
                      <span className="flex-1 truncate text-slate-700 group-hover:text-slate-900">{r.q}</span>
                      <span className="text-[11px] text-slate-400">{ENTITY[r.entity].label}</span>
                    </button>
                  </li>
                ); })}
              </ul>
            )}
          </div>
        </div>

        <p className="mt-8 text-center text-xs text-slate-400">Press <span className="kbd">/</span> to focus · <span className="kbd">Enter</span> to search · <span className="kbd">Shift</span>+<span className="kbd">Enter</span> for a new line</p>
      </div>
    );
  }

  /* ---------- Workspace: chat + results ---------- */
  const highlights = facets.slice(0, 3).map((f) => ({ label: f.label, value: f.values[0]?.value, count: f.values[0]?.count })).filter((h) => h.value);

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[380px_1fr]">
      <Conversation
        turns={turns} busy={busy} info={info} composer={composer} onReset={reset}
        onSuggestion={applyPatch} onRetry={(t) => ask(t.text, t.refine)} onEdit={editTurn}
      />

      <section className="min-w-0 space-y-4">
        <ErrorBox message={error} />

        {/* Overview */}
        <div className="card relative overflow-hidden p-4">
          <div className="ai-gradient absolute inset-x-0 top-0 h-1" aria-hidden />
          <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
            <div>
              <div className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">Matches</div>
              <div className="text-3xl font-semibold text-slate-900 tabular-nums">{busy && !info ? <span className="skeleton inline-block h-8 w-16" /> : total.toLocaleString()}</div>
            </div>
            {highlights.map((h) => (
              <div key={h.label} className="min-w-0">
                <div className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">Top {h.label.toLowerCase()}</div>
                <div className="truncate text-sm font-medium text-slate-900">{h.value} <span className="text-slate-400">· {h.count}</span></div>
              </div>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <button type="button" onClick={() => exportCsv(items, entity)} disabled={items.length === 0} className="btn-secondary !px-2.5 !py-1.5 text-xs" title="Download the results shown as a CSV file"><Download className="h-3.5 w-3.5" /> Export</button>
            </div>
          </div>

          {/* Active filters */}
          <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-3">
            <span className="mr-1 text-xs font-medium text-slate-500">Showing</span>
            {info && Object.entries(info.filters).map(([k, v]) => (
              <span key={k} className="group inline-flex items-center gap-1 rounded-full bg-violet-50 py-1 pr-1 pl-2.5 text-xs font-medium text-violet-800 ring-1 ring-violet-200 animate-pop">
                {describeFilter(k, v)}
                <button type="button" onClick={() => removeFilter(k)} disabled={busy} className="rounded-full p-0.5 text-violet-400 transition hover:bg-violet-200 hover:text-violet-800" aria-label={`Remove ${k}`}><X className="h-3 w-3" /></button>
              </span>
            ))}
            {info?.keywords.map((k) => (
              <span key={k} className="inline-flex items-center gap-1 rounded-full bg-white py-1 pr-1 pl-2.5 text-xs font-medium text-slate-700 ring-1 ring-slate-200 animate-pop">
                “{k}”
                <button type="button" onClick={() => removeKeyword(k)} disabled={busy} className="rounded-full p-0.5 text-slate-400 transition hover:bg-slate-200 hover:text-slate-800" aria-label={`Remove ${k}`}><X className="h-3 w-3" /></button>
              </span>
            ))}
            {info && filterCount === 0 && <span className="text-xs text-slate-500">all {ENTITY[entity].noun}, best text matches first</span>}
            {filterCount > 1 && <button type="button" onClick={clearAll} disabled={busy} className="ml-1 text-xs text-slate-400 underline-offset-2 hover:text-slate-700 hover:underline">Clear all</button>}
          </div>

          {facets.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs font-medium text-slate-500">Narrow by</span>
              {facets.map((f) => (
                <FacetPill key={f.key} facet={f} active={info?.filters[f.key] != null ? String(info.filters[f.key]) : null} open={openFacet === f.key} onOpen={() => setOpenFacet(openFacet === f.key ? null : f.key)} onClose={() => setOpenFacet(null)} onPick={(v) => toggleFacet(f, v)} />
              ))}
            </div>
          )}
        </div>

        {/* Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
          <span>{busy ? <span className="ai-text font-medium">Updating results…</span> : total > items.length ? `Top ${items.length} of ${total.toLocaleString()}` : `${items.length} result${items.length === 1 ? "" : "s"}`}<span className="ml-2 hidden text-xs text-slate-400 sm:inline">Click a card to preview</span></span>
          <div className="flex items-center gap-2">
            <select aria-label="Sort" className="input !w-auto !rounded-full !py-1 text-xs" value={sort} onChange={(e) => changeSort(e.target.value)}>
              {sortOptions.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <div className="flex rounded-full border border-slate-200 bg-white p-0.5">
              {([["grid", LayoutGrid], ["list", List]] as const).map(([v, I]) => (
                <button key={v} type="button" onClick={() => setView(v)} className={`rounded-full p-1.5 transition ${view === v ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-900"}`} aria-pressed={view === v} aria-label={`${v} view`}><I className="h-3.5 w-3.5" /></button>
              ))}
            </div>
          </div>
        </div>

        {/* Results */}
        {busy && items.length === 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">{[1, 2, 3, 4, 5, 6].map((i) => <div key={i} className="skeleton h-40" />)}</div>
        ) : items.length === 0 && info ? (
          <div className="card flex flex-col items-center p-10 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-violet-100 to-pink-100 text-violet-600"><Sparkles className="h-6 w-6" /></div>
            <p className="mt-3 font-semibold text-slate-900">No {ENTITY[entity].noun} match all of that</p>
            <p className="mt-1 max-w-sm text-sm text-slate-500">Loosen it up: remove a filter, or ask the assistant for something broader.</p>
            {filterCount > 0 && (
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {info && Object.entries(info.filters).map(([k, v]) => (
                  <button key={k} type="button" onClick={() => removeFilter(k)} className="ai-pill text-xs"><X className="h-3 w-3" /> Drop {describeFilter(k, v)}</button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className={`transition-opacity ${busy ? "pointer-events-none opacity-50" : ""} ${view === "grid" ? "grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3" : "card divide-y divide-slate-100 overflow-hidden"}`}>
            {items.map((r, i) => <ResultCard key={rowId(r)} row={r} entity={entity} keywords={info?.keywords ?? []} index={i} compact={view === "list"} active={previewIdx === i} onOpen={() => setPreviewIdx(i)} onGo={() => router.push(rowHref(r, entity))} />)}
          </div>
        )}

        {!busy && items.length > 0 && items.length < total && (
          <div className="flex flex-col items-center gap-1 pt-1">
            <button type="button" onClick={loadMore} disabled={loadingMore} className="btn-secondary !rounded-full">
              {loadingMore ? "Loading…" : `Show ${Math.min(50, total - items.length)} more`}
            </button>
            <span className="text-xs text-slate-400">Showing {items.length.toLocaleString()} of {total.toLocaleString()}. Add a filter to narrow the list.</span>
          </div>
        )}
      </section>

      {preview && previewIdx != null && (
        <PreviewDrawer row={preview} entity={entity} position={previewIdx + 1} count={items.length}
          onPrev={previewIdx > 0 ? () => setPreviewIdx(previewIdx - 1) : undefined}
          onNext={previewIdx < items.length - 1 ? () => setPreviewIdx(previewIdx + 1) : undefined}
          onClose={() => setPreviewIdx(null)} />
      )}
    </div>
  );
}

function SectionTitle({ icon: I, children, action }: { icon: Icon; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center justify-between">
      <h2 className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase"><I className="h-3.5 w-3.5 text-violet-500" /> {children}</h2>
      {action}
    </div>
  );
}

/* ---------------------------------------------------------------- Composer */

function Composer({
  inputRef, value, onChange, onSubmit, busy, entity, entities, onEntity, started, refine, onRefine, hasInfo, examples, canListen, listening, onListen, onPhrase,
}: {
  inputRef: RefObject<HTMLTextAreaElement | null>; value: string; onChange: (v: string) => void; onSubmit: () => void; busy: boolean;
  entity: Entity; entities: Entity[]; onEntity: (e: Entity) => void; started: boolean; refine: boolean; onRefine: (v: boolean) => void; hasInfo: boolean;
  examples: string[]; canListen: boolean; listening: boolean; onListen: () => void; onPhrase: (p: string) => void;
}) {
  const [showBuilders, setShowBuilders] = useState(!started);
  const typed = useTypewriter(started ? [] : [ENTITY[entity].placeholder, ...examples], !value);
  const placeholder = started ? (refine && hasInfo ? "Ask a follow-up… e.g. “only OSHA 30”" : `Start a new ${ENTITY[entity].label.toLowerCase()} search…`) : "";
  const lower = value.toLowerCase();

  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [value, inputRef]);

  const onKey = (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); onSubmit(); }
  };

  return (
    <div className="ai-frame">
      <form onSubmit={(e) => { e.preventDefault(); onSubmit(); }} className={`rounded-[22px] bg-white ${started ? "p-2.5" : "p-3 md:p-4"}`}>
        {/* entity switch on top for the start screen */}
        {!started && entities.length > 1 && (
          <div className="mb-2 flex flex-wrap gap-1 px-1">
            {entities.map((e) => { const I = ENTITY[e].icon; const on = entity === e; return (
              <button key={e} type="button" onClick={() => onEntity(e)} aria-pressed={on}
                className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all ${on ? "bg-slate-900 text-white shadow" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900"}`}>
                <I className="h-3.5 w-3.5" /> {ENTITY[e].label}
              </button>
            ); })}
          </div>
        )}

        <div className="relative">
          <textarea
            ref={inputRef} rows={1} value={value} onChange={(e) => onChange(e.target.value)} onKeyDown={onKey}
            placeholder={placeholder} aria-label="AI search prompt" autoFocus
            className={`block w-full resize-none bg-transparent px-2 text-slate-900 outline-none placeholder:text-slate-400 ${started ? "py-1.5 text-sm" : "py-2 text-base md:text-lg"}`}
          />
          {!started && !value && (
            <div className="pointer-events-none absolute inset-0 truncate px-2 py-2 text-base text-slate-400 md:text-lg" aria-hidden>
              {typed}<span className="ml-px inline-block h-5 w-px translate-y-1 bg-violet-500 animate-caret" />
            </div>
          )}
        </div>

        {/* prompt builder */}
        {showBuilders && (
          <div className={`flex gap-1.5 overflow-x-auto px-1 pb-0.5 ${started ? "mt-1.5" : "mt-3 flex-wrap"}`} style={{ scrollbarWidth: "none" }}>
            {ENTITY[entity].builders.map((p) => { const on = lower.includes(p.toLowerCase()); return (
              <button key={p} type="button" onClick={() => onPhrase(p)} aria-pressed={on}
                className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition ${on ? "border-violet-300 bg-violet-600 text-white" : "border-dashed border-slate-300 text-slate-600 hover:border-violet-400 hover:bg-violet-50 hover:text-violet-700"}`}>
                {on ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />} {p}
              </button>
            ); })}
          </div>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-2">
          {started && (
            <>
              <EntityMenu entity={entity} entities={entities} onEntity={onEntity} />
              {hasInfo && (
                <div className="flex rounded-full bg-slate-100 p-0.5 text-xs font-medium" title="Refine narrows the current results; New starts over">
                  {([[true, "Refine"], [false, "New"]] as const).map(([v, l]) => (
                    <button key={l} type="button" onClick={() => onRefine(v)} aria-pressed={refine === v}
                      className={`rounded-full px-2.5 py-0.5 transition ${refine === v ? "bg-white text-violet-700 shadow-xs" : "text-slate-500 hover:text-slate-800"}`}>{l}</button>
                  ))}
                </div>
              )}
              <button type="button" onClick={() => setShowBuilders((v) => !v)} aria-pressed={showBuilders} title="Show phrase chips"
                className={`rounded-full p-1.5 transition ${showBuilders ? "bg-violet-100 text-violet-700" : "text-slate-400 hover:bg-slate-100 hover:text-slate-700"}`}>
                <Wand2 className="h-3.5 w-3.5" />
              </button>
            </>
          )}
          {!started && <span className="px-1 text-xs text-slate-400">Tap chips to add details, or just type.</span>}

          <div className="ml-auto flex items-center gap-1">
            {canListen && (
              <button type="button" onClick={onListen} title="Search by voice" aria-label="Search by voice"
                className={`rounded-full p-2 transition ${listening ? "bg-red-500 text-white animate-pulse" : "text-slate-400 hover:bg-slate-100 hover:text-slate-700"}`}>
                <Mic className="h-4 w-4" />
              </button>
            )}
            <button type="submit" disabled={busy || !value.trim()} aria-label="Search"
              className={`ai-gradient flex items-center justify-center gap-1.5 rounded-full font-medium text-white shadow-md transition hover:scale-105 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100 ${started ? "h-9 w-9" : "h-10 px-4 text-sm"}`}>
              {busy ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" /> : started ? <ArrowUp className="h-4 w-4" /> : <><Sparkles className="h-4 w-4" /> Search</>}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function EntityMenu({ entity, entities, onEntity }: { entity: Entity; entities: Entity[]; onEntity: (e: Entity) => void }) {
  const [open, setOpen] = useState(false);
  const I = ENTITY[entity].icon;
  return (
    <div className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex items-center gap-1.5 rounded-full bg-slate-900 px-2.5 py-1 text-xs font-medium text-white">
        <I className="h-3.5 w-3.5" /> {ENTITY[entity].label} {entities.length > 1 && <ChevronDown className="h-3 w-3 opacity-70" />}
      </button>
      {open && entities.length > 1 && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute bottom-full left-0 z-40 mb-1.5 w-44 rounded-xl border border-slate-200 bg-white p-1 shadow-xl animate-pop">
            {entities.map((e) => { const E = ENTITY[e].icon; return (
              <button key={e} type="button" onClick={() => { setOpen(false); onEntity(e); }} className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm ${e === entity ? "bg-violet-50 text-violet-700" : "text-slate-700 hover:bg-slate-50"}`}>
                <E className="h-4 w-4" /> {ENTITY[e].label}{e === entity && <Check className="ml-auto h-3.5 w-3.5" />}
              </button>
            ); })}
            <p className="px-2.5 pt-1 pb-1.5 text-[11px] text-slate-400">Switching reruns your last question.</p>
          </div>
        </>
      )}
    </div>
  );
}

function useTypewriter(lines: string[], enabled: boolean): string {
  const [text, setText] = useState("");
  const key = lines.join("|");
  useEffect(() => {
    if (!enabled || lines.length === 0) { setText(""); return; }
    let line = 0, char = 0, deleting = false;
    let t: ReturnType<typeof setTimeout>;
    const tick = () => {
      const full = lines[line];
      if (!deleting) {
        char++;
        setText(full.slice(0, char));
        if (char >= full.length) { deleting = true; t = setTimeout(tick, 1800); return; }
        t = setTimeout(tick, 35);
      } else {
        char -= 2;
        setText(full.slice(0, Math.max(char, 0)));
        if (char <= 0) { deleting = false; char = 0; line = (line + 1) % lines.length; t = setTimeout(tick, 300); return; }
        t = setTimeout(tick, 15);
      }
    };
    t = setTimeout(tick, 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);
  return text;
}

/* ------------------------------------------------------------ Conversation */

function Conversation({ turns, busy, info, composer, onReset, onSuggestion, onRetry, onEdit }: {
  turns: Turn[]; busy: boolean; info: AISearchInfo | null; composer: ReactNode; onReset: () => void;
  onSuggestion: (label: string, patch: Filters) => void; onRetry: (t: Turn) => void; onEdit: (t: Turn) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns, busy]);
  const lastReplied = [...turns].reverse().find((t) => t.reply)?.id;

  return (
    <aside className="card flex flex-col overflow-hidden lg:sticky lg:top-22 lg:h-[calc(100vh-7rem)] lg:self-start">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="ai-gradient flex h-8 w-8 items-center justify-center rounded-xl text-white shadow-md"><Sparkles className="h-4 w-4" /></span>
          <div>
            <div className="text-sm font-semibold text-slate-900">Search assistant</div>
            <div className="flex items-center gap-1 text-[11px] text-slate-500"><span className={`h-1.5 w-1.5 rounded-full ${busy ? "bg-amber-400 animate-pulse" : "bg-emerald-500"}`} /> {busy ? "Working…" : "Ready for follow-ups"}</div>
          </div>
        </div>
        <button type="button" onClick={onReset} className="btn-ghost !rounded-full !px-2.5 !py-1 text-xs" title="Start a new search"><RotateCcw className="h-3.5 w-3.5" /> New chat</button>
      </div>

      <div className="max-h-[50vh] flex-1 space-y-4 overflow-y-auto bg-gradient-to-b from-white to-slate-50/60 px-4 py-4 lg:max-h-none">
        {turns.map((t) => (
          <div key={t.id} className="space-y-2 animate-fade-up">
            {t.kind === "ask" ? (
              <div className="group flex items-start justify-end gap-1">
                <button type="button" onClick={() => onEdit(t)} className="mt-1 rounded-full p-1 text-slate-300 opacity-0 transition group-hover:opacity-100 hover:bg-slate-100 hover:text-slate-600 focus:opacity-100" title="Edit and ask again" aria-label="Edit this question"><Pencil className="h-3 w-3" /></button>
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-slate-900 px-3.5 py-2 text-sm text-white shadow-sm">
                  {t.refine && <span className="mb-0.5 block text-[10px] font-semibold tracking-wide text-violet-300 uppercase">Follow-up</span>}
                  {t.text}
                </div>
              </div>
            ) : (
              <div className="flex justify-center">
                <span className="inline-flex items-center gap-1 rounded-full bg-white px-2.5 py-1 text-[11px] text-slate-600 ring-1 ring-slate-200"><Pencil className="h-3 w-3 text-violet-500" /> {t.text}</span>
              </div>
            )}

            {(t.reply || t.error || busy) && (
              <div className="flex gap-2">
                <span className="ai-gradient mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-white"><Sparkles className="h-3 w-3" /></span>
                <div className="min-w-0 flex-1">
                  {t.error ? (
                    <div className="rounded-2xl rounded-tl-md bg-red-50 px-3.5 py-2 text-sm text-red-700 ring-1 ring-red-100">
                      Something went wrong: {t.error}
                      <button type="button" onClick={() => onRetry(t)} className="mt-1 block text-xs font-medium underline">Try again</button>
                    </div>
                  ) : t.reply ? (
                    <Reply turn={t} latest={t.id === lastReplied} info={info} busy={busy} onSuggestion={onSuggestion} />
                  ) : <Thinking />}
                </div>
              </div>
            )}
          </div>
        ))}
        {busy && turns.length > 0 && turns[turns.length - 1].reply && (
          <div className="flex gap-2"><span className="ai-gradient flex h-6 w-6 shrink-0 items-center justify-center rounded-lg text-white"><Sparkles className="h-3 w-3" /></span><Thinking /></div>
        )}
        <div ref={endRef} />
      </div>

      <div className="border-t border-slate-100 bg-white p-3">{composer}</div>
    </aside>
  );
}

function Reply({ turn, latest, info, busy, onSuggestion }: { turn: Turn; latest: boolean; info: AISearchInfo | null; busy: boolean; onSuggestion: (label: string, patch: Filters) => void }) {
  const r = turn.reply!;
  const tokens = [...Object.entries(r.filters).map(([k, v]) => describeFilter(k, v)), ...r.keywords.map((k) => `“${k}”`)];
  return (
    <div className="rounded-2xl rounded-tl-md bg-white px-3.5 py-2.5 text-sm text-slate-700 shadow-xs ring-1 ring-slate-200">
      <p className="font-medium text-slate-900">
        {r.total === 0 ? "I couldn’t find a match for that." : <>Found <span className="ai-text font-semibold">{r.total.toLocaleString()}</span> match{r.total === 1 ? "" : "es"}{r.summary ? <span className="font-normal text-slate-500"> · {r.summary}</span> : null}</>}
      </p>
      {turn.kind === "ask" && tokens.length > 0 && (
        <div className="mt-2">
          <div className="mb-1 text-[10px] font-semibold tracking-wide text-slate-400 uppercase">I understood</div>
          <div className="flex flex-wrap gap-1">{tokens.map((x) => <span key={x} className="rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700">{x}</span>)}</div>
        </div>
      )}
      {turn.kind === "ask" && tokens.length === 0 && <p className="mt-1 text-xs text-slate-500">I didn’t spot specific filters, so I ranked by best text match.</p>}
      {r.total === 0 && <p className="mt-1 text-xs text-slate-500">Try removing a filter on the right, or switch to <b>New</b> and ask more broadly.</p>}
      {latest && info?.suggestions && info.suggestions.length > 0 && (
        <div className="mt-2.5 border-t border-slate-100 pt-2">
          <div className="mb-1 text-[10px] font-semibold tracking-wide text-violet-600 uppercase">Try next</div>
          <div className="flex flex-wrap gap-1">
            {info.suggestions.map((s) => (
              <button key={s.label} type="button" onClick={() => onSuggestion(s.label, s.patch)} disabled={busy}
                className="inline-flex items-center gap-1 rounded-full border border-violet-200 bg-violet-50/50 px-2.5 py-1 text-xs text-violet-800 transition hover:-translate-y-0.5 hover:border-violet-400 hover:bg-violet-100 disabled:opacity-50">
                <Plus className="h-3 w-3" /> {s.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Thinking() {
  const [step, setStep] = useState(0);
  useEffect(() => { const t = setInterval(() => setStep((s) => Math.min(s + 1, THINKING.length - 1)), 900); return () => clearInterval(t); }, []);
  return (
    <div className="rounded-2xl rounded-tl-md bg-white px-3.5 py-2.5 text-sm shadow-xs ring-1 ring-violet-100" role="status">
      <div className="flex items-center gap-2">
        <span className="flex gap-0.5">{[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 rounded-full bg-violet-500 animate-dot" style={{ animationDelay: `${i * 0.15}s` }} />)}</span>
        <span className="ai-text font-medium">{THINKING[step]}…</span>
      </div>
      <div className="mt-2 flex gap-1">{THINKING.map((_, i) => <span key={i} className={`h-1 flex-1 rounded-full transition-colors duration-500 ${i <= step ? "ai-gradient" : "bg-slate-100"}`} />)}</div>
    </div>
  );
}

/* -------------------------------------------------------------- Facet pill */

function FacetPill({ facet, active, open, onOpen, onClose, onPick }: { facet: Facet; active: string | null; open: boolean; onOpen: () => void; onClose: () => void; onPick: (v: string) => void }) {
  const max = facet.values[0]?.count || 1;
  return (
    <div className="relative">
      <button type="button" onClick={onOpen} aria-expanded={open}
        className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium transition ${active ? "border-violet-300 bg-violet-50 text-violet-800" : open ? "border-slate-400 bg-white text-slate-900" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"}`}>
        {facet.label}{active && <span className="font-normal">: {active}</span>}
        <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={onClose} aria-hidden />
          <div className="absolute left-0 z-40 mt-1.5 w-64 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl animate-pop">
            <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold tracking-wide text-slate-400 uppercase">{facet.label} in these results</div>
            <ul className="max-h-72 space-y-0.5 overflow-y-auto">
              {facet.values.map((v) => { const on = active === v.value; return (
                <li key={v.value}>
                  <button type="button" onClick={() => onPick(v.value)} aria-pressed={on}
                    className={`group relative flex w-full items-center justify-between overflow-hidden rounded-lg px-2.5 py-1.5 text-left text-sm transition ${on ? "bg-violet-600 text-white" : "hover:bg-slate-50"}`}>
                    {!on && <span className="absolute inset-y-1 left-1 rounded bg-violet-100/60 transition-all group-hover:bg-violet-100" style={{ width: `calc(${(v.count / max) * 100}% - 8px)` }} aria-hidden />}
                    <span className="relative flex items-center gap-1.5 truncate">{on && <Check className="h-3.5 w-3.5" />}{v.value}</span>
                    <span className={`relative ml-2 text-xs tabular-nums ${on ? "text-violet-100" : "text-slate-500"}`}>{v.count}</span>
                  </button>
                </li>
              ); })}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- Results */

function rowId(r: Row): number { return "EmployeeID" in r ? r.EmployeeID : "CustBusName" in r ? r.CustomerID : r.ProjectID; }
function rowHref(r: Row, entity: Entity): string { return `/${entity}/${rowId(r)}`; }

function exportCsv(rows: Row[], entity: Entity) {
  const cols: [string, string][] = entity === "employees"
    ? [["full_name", "Name"], ["trade_name", "Trade"], ["qualification_name", "Qualification"], ["YearsInTrade", "Years"], ["EmCity", "City"], ["EmState", "State"], ["EmMobilePhone", "Mobile"], ["EmEmail", "E-mail"], ["status_name", "Status"]]
    : entity === "customers"
      ? [["CustBusName", "Customer"], ["type_name", "Type"], ["City", "City"], ["State", "State"], ["Phone", "Phone"], ["CustEmail", "E-mail"], ["active_project_count", "Active jobs"], ["status_name", "Status"]]
      : [["SiteName", "Job"], ["customer_name", "Customer"], ["SiteCity", "City"], ["SiteState", "State"], ["StartDate", "Start"], ["NumberOfEmployees", "Workers needed"], ["assigned_count", "Assigned"], ["status_name", "Status"]];
  const esc = (v: unknown) => { const s = v == null ? "" : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const csv = [cols.map(([, h]) => h).join(","), ...rows.map((r) => cols.map(([k]) => esc((r as unknown as Record<string, unknown>)[k])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `ai-search-${entity}.csv` });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Highlight({ text, keywords }: { text: string | null | undefined; keywords: string[] }) {
  if (!text) return null;
  const kws = keywords.filter((k) => k.length > 1);
  if (kws.length === 0) return <>{text}</>;
  const re = new RegExp(`(${kws.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "ig");
  return <>{text.split(re).map((p, i) => (kws.some((k) => k.toLowerCase() === p.toLowerCase()) ? <mark key={i} className="hl">{p}</mark> : <span key={i}>{p}</span>))}</>;
}

const AVATAR_TONES = ["from-violet-500 to-pink-500", "from-sky-500 to-indigo-500", "from-amber-500 to-orange-500", "from-emerald-500 to-teal-500", "from-rose-500 to-fuchsia-500"];
function initials(s: string): string { return s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase()).join(""); }

function MatchMeter({ n }: { n: number }) {
  const level = n >= 4 ? 3 : n >= 2 ? 2 : n >= 1 ? 1 : 0;
  if (level === 0) return null;
  const label = ["", "Partial match", "Good match", "Strong match"][level];
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-700" title={label}>
      <span className="flex gap-0.5">{[1, 2, 3].map((i) => <span key={i} className={`h-2.5 w-1 rounded-full ${i <= level ? "bg-emerald-500" : "bg-slate-200"}`} />)}</span>
      {label}
    </span>
  );
}

function ResultCard({ row, entity, keywords, index, compact, active, onOpen, onGo }: { row: Row; entity: Entity; keywords: string[]; index: number; compact: boolean; active: boolean; onOpen: () => void; onGo: () => void }) {
  const reasons = ("reasons" in row ? (row as { reasons?: string[] }).reasons : undefined) ?? [];
  let title = "", status: string | null = null, line1 = "", place: string | null = null, extra = "", phone: string | null = null, email: string | null = null;
  if (entity === "employees") {
    const e = row as EmployeeSummary;
    title = e.full_name; status = e.status_name; phone = e.EmMobilePhone; email = e.EmEmail;
    line1 = [e.trade_name, e.qualification_name, e.YearsInTrade != null ? `${e.YearsInTrade} yrs` : null].filter(Boolean).join(" · ");
    place = e.EmCity ? `${e.EmCity}, ${e.EmState}` : null;
    extra = [e.license_count ? `${e.license_count} license${e.license_count > 1 ? "s" : ""}` : null, e.OSHA10, e.BaseSalary != null ? `${formatMoney(e.BaseSalary)}/hr` : null].filter(Boolean).join(" · ");
  } else if (entity === "customers") {
    const c = row as CustomerSummary;
    title = c.CustBusName; status = c.status_name; phone = c.Phone; email = c.CustEmail;
    line1 = [c.type_name, c.Industry].filter(Boolean).join(" · ");
    place = c.City ? `${c.City}, ${c.State}` : null;
    extra = [`${c.active_project_count} active jobs`, c.ContractOnFile ? "contract on file" : "no contract", c.OnHold ? "ON HOLD" : null].filter(Boolean).join(" · ");
  } else {
    const p = row as ProjectSummary;
    title = p.SiteName; status = p.status_name;
    line1 = p.customer_name ?? "";
    place = p.SiteCity ? `${p.SiteCity}, ${p.SiteState}` : null;
    extra = [`starts ${formatDate(p.StartDate)}`, `crew ${p.assigned_count}/${p.NumberOfEmployees}`, p.JobBeingManned ? null : "needs crew"].filter(Boolean).join(" · ");
  }
  const tone = AVATAR_TONES[rowId(row) % AVATAR_TONES.length];
  const avatar = <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${tone} text-xs font-semibold text-white shadow-sm`}>{initials(title) || "?"}</span>;
  const stop = (e: { stopPropagation(): void }) => e.stopPropagation();
  const actions = (
    <div className="flex items-center gap-1">
      {phone && <a href={`tel:${phone}`} onClick={stop} className="rounded-full p-1.5 text-slate-400 transition hover:bg-emerald-50 hover:text-emerald-700" title={`Call ${phone}`} aria-label="Call"><Phone className="h-3.5 w-3.5" /></a>}
      {email && <a href={`mailto:${email}`} onClick={stop} className="rounded-full p-1.5 text-slate-400 transition hover:bg-sky-50 hover:text-sky-700" title={`E-mail ${email}`} aria-label="E-mail"><Mail className="h-3.5 w-3.5" /></a>}
      <button type="button" onClick={(e) => { e.stopPropagation(); onGo(); }} className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium text-slate-500 transition hover:bg-violet-50 hover:text-violet-700">Open <ArrowRight className="h-3 w-3" /></button>
    </div>
  );

  if (compact) {
    return (
      <div className={`group flex cursor-pointer items-center gap-3 px-4 py-2.5 transition hover:bg-violet-50/50 ${active ? "bg-violet-50" : ""}`} onClick={onOpen} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
        {avatar}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2"><span className="truncate font-medium text-slate-900"><Highlight text={title} keywords={keywords} /></span><Badge tone={statusTone(status)}>{status ?? "—"}</Badge></div>
          <div className="truncate text-xs text-slate-500"><Highlight text={[line1, place, extra].filter(Boolean).join(" · ")} keywords={keywords} /></div>
        </div>
        <span className="hidden sm:inline"><MatchMeter n={reasons.length} /></span>
        {actions}
      </div>
    );
  }

  return (
    <div className={`card card-hover group relative flex cursor-pointer flex-col p-4 animate-fade-up ${active ? "!border-violet-400 ring-4 ring-violet-100" : ""}`} style={{ animationDelay: `${Math.min(index, 12) * 40}ms` }} onClick={onOpen} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <div className="flex items-start gap-3">
        {avatar}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="truncate font-semibold text-slate-900"><Highlight text={title} keywords={keywords} /></div>
            <Badge tone={statusTone(status)}>{status ?? "—"}</Badge>
          </div>
          <div className="mt-0.5 truncate text-sm text-slate-600"><Highlight text={line1} keywords={keywords} /></div>
        </div>
      </div>
      <div className="mt-3 space-y-1 text-xs text-slate-500">
        {place && <div className="flex items-center gap-1.5"><MapPin className="h-3.5 w-3.5 text-slate-400" /><Highlight text={place} keywords={keywords} /></div>}
        {extra && <div className="pl-5"><Highlight text={extra} keywords={keywords} /></div>}
      </div>
      {reasons.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1">
          {reasons.slice(0, 4).map((r) => <span key={r} className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800 ring-1 ring-emerald-100">✓ {r}</span>)}
          {reasons.length > 4 && <span className="rounded-md bg-slate-50 px-1.5 py-0.5 text-[11px] text-slate-500">+{reasons.length - 4}</span>}
        </div>
      )}
      <div className="mt-auto pt-3">
        <div className="flex items-center justify-between border-t border-slate-100 pt-2.5">
          <MatchMeter n={reasons.length} />
          <div className="ml-auto">{actions}</div>
        </div>
      </div>
    </div>
  );
}

function PreviewDrawer({ row, entity, position, count, onPrev, onNext, onClose }: { row: Row; entity: Entity; position: number; count: number; onPrev?: () => void; onNext?: () => void; onClose: () => void }) {
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const id = rowId(row);
  useEffect(() => {
    let alive = true;
    setDetail(null);
    const p = entity === "employees" ? api.employee(id) : entity === "customers" ? api.customer(id) : api.project(id);
    p.then((d) => { if (alive) setDetail(d as Record<string, unknown>); }).catch(() => {});
    return () => { alive = false; };
  }, [entity, id]);
  const d = detail ?? {};
  const str = (k: string) => (d[k] === null || d[k] === undefined || d[k] === "" ? "—" : String(d[k]));
  const title = detail ? (entity === "employees" ? str("full_name") : entity === "customers" ? str("CustBusName") : str("SiteName")) : ("full_name" in row ? row.full_name : "CustBusName" in row ? row.CustBusName : row.SiteName);
  const phone = entity === "employees" ? d.EmMobilePhone : entity === "customers" ? d.Phone : d.CustomerPhone;
  const email = entity === "employees" ? d.EmEmail : entity === "customers" ? d.CustEmail : null;
  const fields: [string, string][] = entity === "employees"
    ? [["Trade", str("trade_name")], ["Qualification", str("qualification_name")], ["Experience", str("experience_name")], ["Years", str("YearsInTrade")], ["Mobile", str("EmMobilePhone")], ["E-mail", str("EmEmail")], ["Address", `${str("EmStreet")}, ${str("EmCity")} ${str("EmState")}`], ["Base rate", d.BaseSalary != null ? formatMoney(Number(d.BaseSalary)) : "—"], ["OSHA", str("OSHA10")], ["Will travel", str("WillTravel")], ["Payroll co.", str("payroll_co_name")], ["Admin notes", str("EmAdminNotes")]]
    : entity === "customers"
      ? [["Type", str("type_name")], ["Status", str("status_name")], ["Sales rep", str("salesman_name")], ["Phone", str("Phone")], ["E-mail", str("CustEmail")], ["Address", `${str("Street")}, ${str("City")} ${str("State")}`], ["Industry", str("Industry")], ["Revenue/yr", d.RevenuePerYear != null ? formatMoney(Number(d.RevenuePerYear), 0) : "—"], ["Contract", d.ContractOnFile ? "On file" : "Not on file"], ["Note", str("CustomerNote")]]
      : [["Customer", str("customer_name")], ["Status", str("status_name")], ["Site", `${str("SiteStreet")}, ${str("SiteCity")} ${str("SiteState")}`], ["Start", formatDate(d.StartDate as string | null)], ["End", formatDate(d.EndDate as string | null)], ["Workers needed", str("NumberOfEmployees")], ["WCC", str("wcc_code")], ["Contact", `${str("CustomerContact")} ${str("CustomerPhone")}`], ["Site instructions", str("ProjNote")]];
  const lists = entity === "employees" ? [["Licenses", (d.licenses as unknown[] | undefined)?.length ?? 0], ["Notes", (d.notes as unknown[] | undefined)?.length ?? 0], ["Recent weeks", (d.recent_assignments as unknown[] | undefined)?.length ?? 0]] : entity === "customers" ? [["Contacts", (d.contacts as unknown[] | undefined)?.length ?? 0], ["Jobs", (d.projects as unknown[] | undefined)?.length ?? 0], ["Notes", (d.notes as unknown[] | undefined)?.length ?? 0]] : [["Assignments", (d.assignments as unknown[] | undefined)?.length ?? 0]];
  const reasons = ("reasons" in row ? (row as { reasons?: string[] }).reasons : undefined) ?? [];
  const tone = AVATAR_TONES[id % AVATAR_TONES.length];

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-[2px] animate-fade-in" onClick={onClose}>
      <aside className="flex h-full w-full max-w-md flex-col bg-white shadow-2xl animate-slide-in" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={`Preview ${title}`}>
        <div className="ai-gradient h-1.5 shrink-0" aria-hidden />
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2 text-xs text-slate-500">
          <div className="flex items-center gap-1">
            <button type="button" onClick={onPrev} disabled={!onPrev} className="rounded-full p-1.5 hover:bg-slate-100 disabled:opacity-30" aria-label="Previous result"><ChevronLeft className="h-4 w-4" /></button>
            <span className="tabular-nums">{position} of {count}</span>
            <button type="button" onClick={onNext} disabled={!onNext} className="rounded-full p-1.5 hover:bg-slate-100 disabled:opacity-30" aria-label="Next result"><ChevronRight className="h-4 w-4" /></button>
            <span className="ml-1 hidden text-slate-400 sm:inline">Use <span className="kbd">←</span> <span className="kbd">→</span></span>
          </div>
          <button onClick={onClose} className="rounded-full p-1.5 hover:bg-slate-100" aria-label="Close preview"><X className="h-4 w-4" /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="flex items-center gap-3">
            <span className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br ${tone} text-sm font-semibold text-white shadow-md`}>{initials(title)}</span>
            <div className="min-w-0">
              <div className="text-[11px] font-semibold tracking-wide text-slate-500 uppercase">{ENTITY[entity].label.replace(/s$/, "")}</div>
              <h2 className="truncate text-xl font-semibold text-slate-900">{title}</h2>
            </div>
          </div>

          {reasons.length > 0 && (
            <div className="mt-4 rounded-xl bg-emerald-50/70 p-3 ring-1 ring-emerald-100">
              <div className="mb-1.5 flex items-center justify-between text-[11px] font-semibold tracking-wide text-emerald-700 uppercase">Why it matches <MatchMeter n={reasons.length} /></div>
              <div className="flex flex-wrap gap-1">{reasons.map((r) => <span key={r} className="rounded-md bg-white px-1.5 py-0.5 text-[11px] font-medium text-emerald-800 ring-1 ring-emerald-100">✓ {r}</span>)}</div>
            </div>
          )}

          {!detail ? <div className="mt-5 space-y-2">{[1, 2, 3, 4, 5].map((i) => <div key={i} className="skeleton h-9" />)}</div> : (
            <>
              {(phone || email) && (
                <div className="mt-4 flex gap-2">
                  {phone ? <a href={`tel:${String(phone)}`} className="btn-secondary flex-1 !rounded-full text-xs"><Phone className="h-3.5 w-3.5" /> Call</a> : null}
                  {email ? <a href={`mailto:${String(email)}`} className="btn-secondary flex-1 !rounded-full text-xs"><Mail className="h-3.5 w-3.5" /> E-mail</a> : null}
                </div>
              )}
              <div className="mt-4 flex gap-2">{lists.map(([l, n]) => <div key={String(l)} className="flex-1 rounded-xl bg-slate-50 p-2.5 text-center"><div className="text-lg font-semibold text-slate-900">{n}</div><div className="text-[11px] text-slate-500 uppercase">{l}</div></div>)}</div>
              <dl className="mt-4 divide-y divide-slate-100">
                {fields.map(([k, v]) => <div key={k} className="grid grid-cols-[110px_1fr] gap-2 py-2 text-sm"><dt className="text-slate-500">{k}</dt><dd className="break-words text-slate-900">{v}</dd></div>)}
              </dl>
            </>
          )}
        </div>

        <div className="border-t border-slate-100 p-4">
          <Link href={rowHref(row, entity)} className="btn-primary w-full !rounded-full">Open full record <ArrowRight className="h-4 w-4" /></Link>
        </div>
      </aside>
    </div>
  );
}
