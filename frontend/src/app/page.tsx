"use client";

import { AlertTriangle, Briefcase, Building2, CalendarDays, HardHat, Sparkles, UserCog } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ColumnChart, HBarList } from "@/components/charts";
import { Badge, ErrorBox, Section, Spinner } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatHours, formatMoney, formatPercent } from "@/lib/format";
import type { DashboardStats } from "@/lib/types";

export default function DashboardPage() {
  return (
    <AppShell>
      <Dashboard />
    </AppShell>
  );
}

function Dashboard() {
  const { user, hasFeature } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.dashboard().then(setStats).catch((e) => setError(describeError(e)));
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (!stats) return <Spinner label="Loading dashboard…" />;
  const showMoney = hasFeature("payroll.view") && !user?.OfficeStaffHideHours;

  const weekly = stats.weekly_hours.map((w) => ({
    label: formatDate(w.week_ending, { month: "numeric", day: "numeric" }),
    value: Math.round(w.hours),
    detail: `${w.workers} workers${showMoney ? ` · invoice ${formatMoney(w.invoice, 0)}` : ""}`,
  }));

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Good {greeting()}, {user?.OfficeStaffFirstName}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-500">Here’s what’s happening for the week ending {formatDate(stats.week_ending)}. <Badge tone={stats.ai_mode === "claude" ? "violet" : "slate"}>{stats.ai_mode === "claude" ? "Claude AI search on" : "AI search: built-in parser"}</Badge></p>
        </div>
        {hasFeature("ai.search") && <Link href="/search" className="btn-primary"><Sparkles className="h-4 w-4" /> Ask AI search</Link>}
      </div>

      {/* KPI cards */}
      <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <div className="card relative overflow-hidden p-5 sm:col-span-2 xl:col-span-1">
          <div className="absolute inset-y-0 left-0 w-1 bg-brand-500" aria-hidden />
          <div className="flex items-center justify-between text-sm font-medium text-slate-500">Hours this week<span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600"><CalendarDays className="h-[18px] w-[18px]" /></span></div>
          <div className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">{formatHours(stats.hours_this_week)}</div>
          <div className="mt-1 text-xs text-slate-500">{stats.assignments_this_week} assignments{showMoney && stats.margin_this_week !== null ? ` · margin ${formatPercent(stats.margin_this_week)}` : ""}</div>
        </div>
        <Tile icon={HardHat} tone="bg-sky-50 text-sky-600" label="Employees" value={stats.employees_total} sub={`${stats.employees_active} active · ${stats.employees_available} available`} href="/employees" />
        <Tile icon={Building2} tone="bg-emerald-50 text-emerald-600" label="Customers" value={stats.customers_total} sub={`${stats.customers_active} active`} href="/customers" />
        <Tile icon={Briefcase} tone="bg-amber-50 text-amber-600" label="Jobs" value={stats.projects_total} sub={`${stats.projects_active} active`} href="/projects" />
        <Tile icon={UserCog} tone="bg-violet-50 text-violet-600" label="Users" value={stats.users_total} sub="office staff accounts" href={hasFeature("users.manage") ? "/users" : undefined} />
      </div>

      {showMoney && (
        <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Money label="Invoice this week" value={stats.invoice_this_week} />
          <Money label="Gross payroll this week" value={stats.payroll_this_week} />
          <Money label="Gross margin" value={stats.invoice_this_week - stats.payroll_this_week} sub={formatPercent(stats.margin_this_week)} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Section title="Hours worked per week (last 12 weeks)" className="lg:col-span-2">
          <ColumnChart data={weekly} valueLabel="Hours" />
        </Section>
        <Section title="Workforce by trade">
          <HBarList data={stats.top_trades.map((t) => ({ label: t.trade, value: t.count }))} />
        </Section>
        <Section title="Attention" className="lg:col-span-1">
          <ul className="space-y-2 text-sm">
            <li className="flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 p-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
              <span><strong>{stats.licenses_expiring_90d}</strong> employee licenses expire within 90 days.{" "}
                {hasFeature("ai.search") && <Link href="/employees" className="text-brand-700 underline">Review</Link>}</span>
            </li>
            <li className="rounded-md border border-slate-200 p-3 text-slate-600">
              <strong>{stats.employees_available}</strong> workers are posted as available this week.
            </li>
            <li className="rounded-md border border-slate-200 p-3 text-slate-600">
              <strong>{stats.projects_active}</strong> active jobs across <strong>{stats.customers_active}</strong> active customers.
            </li>
          </ul>
        </Section>
        <Section title="Recent activity" className="lg:col-span-2">
          {stats.recent_activity.length === 0 ? <p className="text-sm text-slate-500">No activity yet.</p> : (
            <table className="table">
              <thead><tr><th>When</th><th>User</th><th>Action</th></tr></thead>
              <tbody>
                {stats.recent_activity.map((a, i) => (
                  <tr key={i}><td className="whitespace-nowrap text-slate-500">{formatDateTime(a.when)}</td><td className="font-mono text-xs">{a.user}</td><td>{a.action.replace(/\./g, " › ")}{a.object_id ? ` #${a.object_id}` : ""}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      </div>
    </>
  );
}

function Tile({ icon: Icon, tone, label, value, sub, href }: { icon: typeof HardHat; tone: string; label: string; value: number; sub: string; href?: string }) {
  const body = (
    <div className={`card h-full p-5 ${href ? "card-hover" : ""}`}>
      <div className="flex items-center justify-between text-sm font-medium text-slate-500">{label}<span className={`flex h-9 w-9 items-center justify-center rounded-lg ${tone}`}><Icon className="h-[18px] w-[18px]" aria-hidden /></span></div>
      <div className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">{value.toLocaleString()}</div>
      <div className="mt-1 text-xs text-slate-500">{sub}</div>
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

function Money({ label, value, sub }: { label: string; value: number; sub?: string }) {
  return (
    <div className="card p-5">
      <div className="text-sm font-medium text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">{formatMoney(value, 0)}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
}
