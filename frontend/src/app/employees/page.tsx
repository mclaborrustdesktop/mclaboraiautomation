"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { SearchBar } from "@/components/SearchBar";
import { Badge, ErrorBox, PageHeader, statusTone } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { daysUntil, formatDate, formatMoney } from "@/lib/format";
import type { AISearchInfo, EmployeeSummary } from "@/lib/types";

const PAGE_SIZE = 50; // one page of results; filtering, sorting and paging happen in the database

export default function EmployeesPage() {
  return (
    <AppShell>
      <RequireFeature feature="employees.view">
        <EmployeeList />
      </RequireFeature>
    </AppShell>
  );
}

function EmployeeList() {
  const router = useRouter();
  const { lookups, hasFeature } = useAuth();
  const [rows, setRows] = useState<EmployeeSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState({ q: "", ai: false });
  const [filters, setFilters] = useState({ trade_id: "", status_id: "", state: "", available: "", licensed: "" });
  const [aiInfo, setAiInfo] = useState<AISearchInfo | null>(null);
  const [examples, setExamples] = useState<string[]>([]);

  useEffect(() => {
    if (hasFeature("ai.search")) api.searchStatus().then((s) => setExamples(s.examples.employees)).catch(() => {});
  }, [hasFeature]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (query.ai && query.q) {
        const res = await api.aiSearch<EmployeeSummary>("employees", query.q, page, PAGE_SIZE);
        setRows(res.items);
        setTotal(res.total);
        setAiInfo(res.ai);
      } else {
        const res = await api.employees({ q: query.q, page, page_size: PAGE_SIZE, ...filters });
        setRows(res.items);
        setTotal(res.total);
        setAiInfo(null);
      }
    } catch (e) {
      setError(describeError(e));
    } finally {
      setLoading(false);
    }
  }, [query, page, filters]);

  useEffect(() => {
    load();
  }, [load]);

  const columns: Column<EmployeeSummary>[] = [
    {
      key: "name",
      header: "Employee",
      render: (r) => (
        <div>
          <div className="font-medium text-slate-900">{r.full_name}</div>
          <div className="text-xs text-slate-500">{r.EmMobilePhone ?? r.EmEmail ?? ""}</div>
        </div>
      ),
    },
    { key: "trade", header: "Trade", render: (r) => <span>{r.trade_name ?? "—"}{r.qualification_name ? <span className="text-slate-500"> · {r.qualification_name}</span> : null}</span> },
    { key: "loc", header: "Location", render: (r) => (r.EmCity ? `${r.EmCity}, ${r.EmState}` : "—") },
    { key: "status", header: "Status", render: (r) => <Badge tone={statusTone(r.status_name)}>{r.status_name ?? "—"}</Badge> },
    { key: "years", header: "Yrs", align: "right", render: (r) => r.YearsInTrade ?? "—" },
    { key: "rate", header: "Rate", align: "right", render: (r) => formatMoney(r.BaseSalary) },
    {
      key: "license",
      header: "License",
      render: (r) => {
        if (!r.license_count && !r.EmLicenseDateExpires) return <span className="text-slate-400">—</span>;
        const d = daysUntil(r.EmLicenseDateExpires);
        const tone = d === null ? "slate" : d < 0 ? "red" : d <= 60 ? "amber" : "green";
        return <Badge tone={tone}>{r.license_count} lic · exp {formatDate(r.EmLicenseDateExpires, { month: "short", year: "2-digit" })}</Badge>;
      },
    },
    { key: "osha", header: "OSHA", render: (r) => r.OSHA10 ?? "—" },
    { key: "last", header: "Last worked", render: (r) => formatDate(r.last_week_ending) },
  ];

  return (
    <>
      <PageHeader
        title="Employees"
        subtitle={`${total.toLocaleString()} skilled-trades workers in the demo database`}
        actions={
          hasFeature("employees.edit") && (
            <Link href="/employees/new" className="btn-primary">
              <Plus className="h-4 w-4" /> New employee
            </Link>
          )
        }
      />
      <div className="mb-4 space-y-3">
        <SearchBar
          placeholder="Search name, city, phone, notes…"
          aiPlaceholder="Describe who you need, e.g. “licensed journeyman electricians in Worcester with 5+ years”"
          examples={examples}
          busy={loading}
          aiInfo={aiInfo}
          onSearch={(q, ai) => {
            setPage(1);
            setQuery({ q, ai });
          }}
        />
        {!(query.ai && query.q) && (
          <div className="flex flex-wrap gap-2">
            <select className="input !w-auto" value={filters.trade_id} onChange={(e) => { setPage(1); setFilters({ ...filters, trade_id: e.target.value }); }} aria-label="Trade">
              <option value="">All trades</option>
              {lookups?.trades.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.status_id} onChange={(e) => { setPage(1); setFilters({ ...filters, status_id: e.target.value }); }} aria-label="Status">
              <option value="">All statuses</option>
              {lookups?.employee_statuses.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.state} onChange={(e) => { setPage(1); setFilters({ ...filters, state: e.target.value }); }} aria-label="State">
              <option value="">All states</option>
              {lookups?.states.map((t) => <option key={t.id} value={t.label}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.available} onChange={(e) => { setPage(1); setFilters({ ...filters, available: e.target.value }); }} aria-label="Availability">
              <option value="">Any availability</option>
              <option value="true">Posted as available</option>
            </select>
            <select className="input !w-auto" value={filters.licensed} onChange={(e) => { setPage(1); setFilters({ ...filters, licensed: e.target.value }); }} aria-label="Licensed">
              <option value="">Licensed or not</option>
              <option value="true">Licensed only</option>
              <option value="false">Unlicensed only</option>
            </select>
          </div>
        )}
      </div>
      <ErrorBox message={error} />
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.EmployeeID} loading={loading} onRowClick={(r) => router.push(`/employees/${r.EmployeeID}`)} page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
    </>
  );
}
