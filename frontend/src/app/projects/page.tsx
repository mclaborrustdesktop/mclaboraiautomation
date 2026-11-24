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
import { formatCompactMoney, formatDate } from "@/lib/format";
import type { AISearchInfo, ProjectSummary } from "@/lib/types";

const PAGE_SIZE = 50; // one page of results; filtering, sorting and paging happen in the database

export default function ProjectsPage() {
  return (
    <AppShell>
      <RequireFeature feature="projects.view">
        <ProjectList />
      </RequireFeature>
    </AppShell>
  );
}

function ProjectList() {
  const router = useRouter();
  const { lookups, hasFeature } = useAuth();
  const [rows, setRows] = useState<ProjectSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState({ q: "", ai: false });
  const [filters, setFilters] = useState({ status_id: "", state: "", manned: "" });
  const [aiInfo, setAiInfo] = useState<AISearchInfo | null>(null);
  const [examples, setExamples] = useState<string[]>([]);

  useEffect(() => {
    if (hasFeature("ai.search")) api.searchStatus().then((s) => setExamples(s.examples.projects)).catch(() => {});
  }, [hasFeature]);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      if (query.ai && query.q) {
        const res = await api.aiSearch<ProjectSummary>("projects", query.q, page, PAGE_SIZE);
        setRows(res.items); setTotal(res.total); setAiInfo(res.ai);
      } else {
        const res = await api.projects({ q: query.q, page, page_size: PAGE_SIZE, ...filters });
        setRows(res.items); setTotal(res.total); setAiInfo(null);
      }
    } catch (e) { setError(describeError(e)); } finally { setLoading(false); }
  }, [query, page, filters]);
  useEffect(() => { load(); }, [load]);

  const columns: Column<ProjectSummary>[] = [
    { key: "site", header: "Job / site", render: (r) => <div><div className="font-medium text-slate-900">{r.SiteName}</div><div className="text-xs text-slate-500">{r.customer_name}</div></div> },
    { key: "loc", header: "Location", render: (r) => (r.SiteCity ? `${r.SiteCity}, ${r.SiteState}` : "—") },
    { key: "status", header: "Status", render: (r) => <Badge tone={statusTone(r.status_name)}>{r.status_name ?? "—"}</Badge> },
    { key: "dates", header: "Dates", render: (r) => <span className="whitespace-nowrap">{formatDate(r.StartDate, { month: "short", day: "numeric" })} → {formatDate(r.EndDate, { month: "short", day: "numeric", year: "2-digit" })}</span> },
    { key: "crew", header: "Crew", align: "right", render: (r) => <span>{r.assigned_count} <span className="text-slate-400">/ {r.NumberOfEmployees}</span></span> },
    { key: "manned", header: "Manned", render: (r) => <Badge tone={r.JobBeingManned ? "green" : "amber"}>{r.JobBeingManned ? "Yes" : "Needs crew"}</Badge> },
    { key: "wcc", header: "WCC", render: (r) => r.wcc_code ?? "—" },
    { key: "amt", header: "Contract", align: "right", render: (r) => formatCompactMoney(r.ContractAmount) },
  ];

  return (
    <>
      <PageHeader
        title="Jobs / Projects"
        subtitle={`${total.toLocaleString()} job sites`}
        actions={hasFeature("projects.edit") && <Link href="/projects/new" className="btn-primary"><Plus className="h-4 w-4" /> New job</Link>}
      />
      <div className="mb-4 space-y-3">
        <SearchBar
          placeholder="Search site, customer, city, notes…"
          aiPlaceholder="Describe the jobs, e.g. “active jobs in Boston that are not manned”"
          examples={examples}
          busy={loading}
          aiInfo={aiInfo}
          onSearch={(q, ai) => { setPage(1); setQuery({ q, ai }); }}
        />
        {!(query.ai && query.q) && (
          <div className="flex flex-wrap gap-2">
            <select className="input !w-auto" value={filters.status_id} onChange={(e) => { setPage(1); setFilters({ ...filters, status_id: e.target.value }); }} aria-label="Status">
              <option value="">All statuses</option>
              {lookups?.project_statuses.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.state} onChange={(e) => { setPage(1); setFilters({ ...filters, state: e.target.value }); }} aria-label="State">
              <option value="">All states</option>
              {lookups?.states.map((t) => <option key={t.id} value={t.label}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.manned} onChange={(e) => { setPage(1); setFilters({ ...filters, manned: e.target.value }); }} aria-label="Manned">
              <option value="">Manned or not</option>
              <option value="true">Manned</option>
              <option value="false">Needs crew</option>
            </select>
          </div>
        )}
      </div>
      <ErrorBox message={error} />
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.ProjectID} loading={loading} onRowClick={(r) => router.push(`/projects/${r.ProjectID}`)} page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
    </>
  );
}
