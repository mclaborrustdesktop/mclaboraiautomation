"use client";

import {
  Briefcase, Building2, CalendarDays, ChevronRight, ChevronsLeft, ChevronsRight, HardHat, KeyRound, LayoutDashboard, LogOut, Menu, Plus, ShieldCheck, Sparkles,
  UserCog, Users, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { initials } from "@/lib/format";
import { ChangePasswordDialog } from "./ChangePassword";
import { EnvironmentBadge } from "./EnvironmentBadge";
import { SyncBanner } from "./SyncBanner";
import { Spinner } from "./ui";

type NavItem = { href: string; label: string; icon: typeof HardHat; feature: string | null; ai?: boolean };

const NAV: { section: string; items: NavItem[] }[] = [
  { section: "", items: [
    { href: "/", label: "Dashboard", icon: LayoutDashboard, feature: null },
    { href: "/search", label: "AI Search", icon: Sparkles, feature: "ai.search", ai: true },
  ] },
  { section: "Records", items: [
    { href: "/employees", label: "Employees", icon: HardHat, feature: "employees.view" },
    { href: "/customers", label: "Customers", icon: Building2, feature: "customers.view" },
    { href: "/projects", label: "Jobs", icon: Briefcase, feature: "projects.view" },
  ] },
  { section: "Operations", items: [
    { href: "/tracking", label: "Weekly Tracking", icon: CalendarDays, feature: "tracking.view" },
  ] },
  { section: "Admin", items: [
    { href: "/users", label: "Users & Permissions", icon: UserCog, feature: "users.manage" },
    { href: "/system", label: "System status", icon: ShieldCheck, feature: "users.manage" },
  ] },
];

const CREATE = [
  { href: "/employees/new", label: "Employee", icon: HardHat, feature: "employees.edit" },
  { href: "/customers/new", label: "Customer", icon: Building2, feature: "customers.edit" },
  { href: "/projects/new", label: "Job", icon: Briefcase, feature: "projects.edit" },
];

const SEGMENT_LABELS: Record<string, string> = {
  search: "AI Search", employees: "Employees", customers: "Customers", projects: "Jobs", tracking: "Weekly Tracking", users: "Users & Permissions", system: "System status", new: "New",
};

const COLLAPSE_KEY = "mclabor.sidebar.collapsed";

export function AppShell({ children }: { children: ReactNode }) {
  const { user, loading, logout, hasFeature, mustChangePassword, passwordChanged, lookups, accessMode, searchOnly } = useAuth();
  const [passwordOpen, setPasswordOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  // Only the "login" mode has a sign-in page. In the demo ("open") and behind the company gateway there is none.
  useEffect(() => {
    if (!loading && !user && accessMode === "login") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [loading, user, router, pathname, accessMode]);

  useEffect(() => { try { setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1"); } catch { /* ignore */ } }, []);
  useEffect(() => { setMobileOpen(false); }, [pathname]);

  const toggleCollapsed = () => setCollapsed((c) => { try { localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1"); } catch { /* ignore */ } return !c; });

  if (loading || !user) {
    const waiting = loading || accessMode === "login";
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <img src="/brand/mclabor-logo.png" alt="MC Labor Sources Inc." className="h-8 w-auto" />
        {waiting ? <Spinner label="Opening…" /> : (
          <div className="max-w-md">
            <h1 className="text-lg font-semibold text-slate-900">
              {accessMode === "gateway" ? "This site opens only through the company gateway" : "The site cannot reach its server"}
            </h1>
            <p className="mt-2 text-sm text-slate-500">
              {accessMode === "gateway"
                ? "Connect to the company VPN and open the site from the company portal. If you are connected and still see this, your e-mail address is not on the list of approved office staff."
                : "The backend is not answering. Start it (or ask whoever runs this PC to), then reload this page."}
            </p>
            <button type="button" className="btn-primary mt-5 h-10 px-5" onClick={() => window.location.reload()}>Try again</button>
          </div>
        )}
      </div>
    );
  }

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  const sections = NAV.map((s) => ({ ...s, items: s.items.filter((n) => !n.feature || hasFeature(n.feature)) })).filter((s) => s.items.length > 0);
  const roleLabel = user.OfficeStaffTitle ?? (user.Profile ? "Administrator" : "Staff");

  const sidebar = (mini: boolean) => (
    <div className="flex h-full flex-col">
      <div className={`flex h-16 shrink-0 items-center border-b border-slate-100 ${mini ? "justify-center px-2" : "px-5"}`}>
        <Link href="/" className="flex items-center" aria-label="MC Labor Sources home">
          {mini
            ? <img src="/brand/mclabor-mark.png" alt="MC Labor Sources" className="h-9 w-9 object-contain" />
            : <img src="/brand/mclabor-logo.png" alt="MC Labor Sources Inc." className="h-7 w-auto max-w-[200px]" />}
        </Link>
      </div>

      <nav className={`flex-1 space-y-5 overflow-y-auto py-4 ${mini ? "px-2" : "px-3"}`} aria-label="Main">
        {sections.map((s) => (
          <div key={s.section || "main"}>
            {s.section && !mini && <div className="mb-1.5 px-2.5 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">{s.section}</div>}
            {s.section && mini && <div className="mx-auto mb-2 h-px w-6 bg-slate-200" aria-hidden />}
            <ul className="space-y-0.5">
              {s.items.map((n) => (
                <li key={n.href}>
                  <Link href={n.href} aria-current={isActive(n.href) ? "page" : undefined} title={mini ? n.label : undefined}
                    className={`nav-link ${mini ? "justify-center !px-0" : ""}`}>
                    <n.icon className={`h-[18px] w-[18px] shrink-0 ${n.ai ? "text-violet-500" : ""}`} aria-hidden />
                    {!mini && <span className="truncate">{n.label}</span>}
                    {!mini && n.ai && <span className="ai-gradient ml-auto rounded-full px-1.5 py-px text-[10px] font-semibold text-white">AI</span>}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className={`border-t border-slate-100 ${mini ? "p-2" : "p-3"}`}>
        <button type="button" onClick={toggleCollapsed} className={`nav-link hidden w-full md:flex ${mini ? "justify-center !px-0" : ""}`} title={mini ? "Expand sidebar" : "Collapse sidebar"}>
          {mini ? <ChevronsRight className="h-[18px] w-[18px]" /> : <><ChevronsLeft className="h-[18px] w-[18px]" /> <span>Collapse</span></>}
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className={`sticky top-0 hidden h-screen shrink-0 border-r border-slate-200 bg-white transition-[width] duration-200 md:block ${collapsed ? "w-[68px]" : "w-60"}`}>
        {sidebar(collapsed)}
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-slate-900/40 animate-fade-in" onClick={() => setMobileOpen(false)} />
          <aside className="relative h-full w-64 bg-white shadow-xl animate-slide-in">
            <button type="button" onClick={() => setMobileOpen(false)} className="absolute top-4 right-3 rounded-md p-1.5 text-slate-500 hover:bg-slate-100" aria-label="Close menu"><X className="h-4 w-4" /></button>
            {sidebar(false)}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          pathname={pathname}
          onMenu={() => setMobileOpen(true)}
          canAi={hasFeature("ai.search")}
          creates={CREATE.filter((c) => hasFeature(c.feature))}
          name={user.OfficeStaffFullName}
          role={roleLabel}
          email={user.OfficeStaffEmail}
          onLogout={logout}
          onChangePassword={() => setPasswordOpen(true)}
          signIn={accessMode === "login"}
          environment={lookups?.environment}
        />
        {accessMode === "login" && (passwordOpen || mustChangePassword) && (
          <ChangePasswordDialog forced={mustChangePassword} onClose={() => setPasswordOpen(false)} onDone={() => { passwordChanged(); setPasswordOpen(false); }} />
        )}
        <SyncBanner />
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 md:px-8 animate-fade-in">{children}</main>
        <footer className="px-4 py-4 text-center text-[11px] text-slate-400">© MC Labor Sources Inc. · {searchOnly ? "Search-only copy of the office McLabor system, refreshed twice a day; records are changed in the office" : lookups?.environment === "production" ? "Connected to the LIVE McLabor database" : lookups?.environment === "staging" ? "STAGING: restored copy of the McLabor database, not the live one" : "Demo build with synthetic data, not connected to the McLabor database"}</footer>
      </div>
    </div>
  );
}

function TopBar({ pathname, onMenu, canAi, creates, name, role, email, onLogout, onChangePassword, signIn, environment }: {
  pathname: string; onMenu: () => void; canAi: boolean; creates: typeof CREATE; name: string; role: string; email: string | null; onLogout: () => void; onChangePassword: () => void; signIn: boolean; environment?: string;
}) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [menu, setMenu] = useState<"create" | "user" | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const onSearchPage = pathname.startsWith("/search");
  const segments = pathname.split("/").filter(Boolean);
  const entity = ["employees", "customers", "projects"].includes(segments[0]) ? segments[0] : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (onSearchPage) document.querySelector<HTMLTextAreaElement>('textarea[aria-label="AI search prompt"]')?.focus(); else inputRef.current?.focus(); }
      if (e.key === "Escape") setMenu(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onSearchPage]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = q.trim();
    if (!text) return;
    setQ("");
    router.push(`/search?q=${encodeURIComponent(text)}${entity ? `&entity=${entity}` : ""}`);
  };

  const crumbs = [{ href: "/", label: "Home" }, ...segments.map((s, i) => ({ href: "/" + segments.slice(0, i + 1).join("/"), label: SEGMENT_LABELS[s] ?? (/^\d+$/.test(s) ? `#${s}` : s) }))];

  return (
    <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/85 px-4 backdrop-blur md:px-8">
      <button type="button" onClick={onMenu} className="rounded-md p-1.5 text-slate-600 hover:bg-slate-100 md:hidden" aria-label="Open menu"><Menu className="h-5 w-5" /></button>
      <img src="/brand/mclabor-mark.png" alt="" className="h-8 w-8 md:hidden" aria-hidden />

      <nav aria-label="Breadcrumb" className="hidden min-w-0 items-center gap-1 text-sm lg:flex">
        {crumbs.map((c, i) => (
          <span key={c.href} className="flex min-w-0 items-center gap-1">
            {i > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-300" aria-hidden />}
            {i === crumbs.length - 1
              ? <span className="truncate font-medium text-slate-900">{c.label}</span>
              : <Link href={c.href} className="truncate text-slate-500 hover:text-slate-900">{c.label}</Link>}
          </span>
        ))}
      </nav>

      <EnvironmentBadge environment={environment} className="hidden sm:inline-flex" />

      <div className="ml-auto flex flex-1 items-center justify-end gap-2 lg:flex-none">
        {canAi && !onSearchPage && (
          <form onSubmit={submit} className="relative w-full max-w-md lg:w-96">
            <Sparkles className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-violet-500" aria-hidden />
            <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask AI${entity ? ` about ${entity === "projects" ? "jobs" : entity}` : ""}…`} aria-label="Ask AI search"
              className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pr-14 pl-9 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-violet-400 focus:bg-white focus:ring-3 focus:ring-violet-100" />
            <span className="pointer-events-none absolute top-1/2 right-2 hidden -translate-y-1/2 items-center gap-0.5 sm:flex"><span className="kbd">Ctrl</span><span className="kbd">K</span></span>
          </form>
        )}

        {creates.length > 0 && (
          <div className="relative">
            <button type="button" onClick={() => setMenu(menu === "create" ? null : "create")} aria-expanded={menu === "create"} className="btn-primary !h-9 !px-3">
              <Plus className="h-4 w-4" /><span className="hidden sm:inline">Create</span>
            </button>
            {menu === "create" && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} aria-hidden />
                <div className="absolute right-0 z-50 mt-2 w-48 rounded-xl border border-slate-200 bg-white p-1 shadow-lg animate-pop">
                  <div className="px-2.5 pt-1.5 pb-1 text-[11px] font-semibold tracking-wider text-slate-400 uppercase">New record</div>
                  {creates.map((c) => (
                    <Link key={c.href} href={c.href} onClick={() => setMenu(null)} className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-slate-700 hover:bg-slate-50">
                      <c.icon className="h-4 w-4 text-slate-400" /> {c.label}
                    </Link>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        <div className="relative">
          <button type="button" onClick={() => setMenu(menu === "user" ? null : "user")} aria-expanded={menu === "user"} className="flex items-center gap-2 rounded-full p-0.5 pr-0.5 transition hover:bg-slate-100 md:pr-2.5" aria-label="Account menu">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-500 text-xs font-semibold text-white">{initials(name)}</span>
            <span className="hidden text-left md:block">
              <span className="block max-w-[140px] truncate text-sm leading-tight font-medium text-slate-900">{name}</span>
              <span className="block max-w-[140px] truncate text-[11px] leading-tight text-slate-500">{role}</span>
            </span>
          </button>
          {menu === "user" && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} aria-hidden />
              <div className="absolute right-0 z-50 mt-2 w-60 rounded-xl border border-slate-200 bg-white p-1 shadow-lg animate-pop">
                <div className="border-b border-slate-100 px-3 py-2.5">
                  <div className="truncate text-sm font-medium text-slate-900">{name}</div>
                  <div className="truncate text-xs text-slate-500">{email ?? role}</div>
                </div>
                {signIn ? (
                  <>
                    <button type="button" onClick={() => { setMenu(null); onChangePassword(); }} className="mt-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50">
                      <KeyRound className="h-4 w-4 text-slate-400" /> Change password
                    </button>
                    <button type="button" onClick={onLogout} className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50">
                      <LogOut className="h-4 w-4 text-slate-400" /> Sign out
                    </button>
                  </>
                ) : (
                  <p className="px-3 py-2 text-xs text-slate-500">No sign-in is needed here.</p>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

export function RequireFeature({ feature, children }: { feature: string; children: ReactNode }) {
  const { hasFeature } = useAuth();
  if (!hasFeature(feature)) {
    return (
      <div className="card p-8 text-center">
        <Users className="mx-auto mb-3 h-8 w-8 text-slate-300" />
        <h2 className="text-lg font-semibold">You don&apos;t have access to this area</h2>
        <p className="mt-1 text-sm text-slate-500">Ask an administrator to grant the “{feature}” permission.</p>
      </div>
    );
  }
  return <>{children}</>;
}
