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
import { formatCompactMoney } from "@/lib/format";
import type { AISearchInfo, CustomerSummary } from "@/lib/types";

const PAGE_SIZE = 50; // one page of results; filtering, sorting and paging happen in the database

export default function CustomersPage() {
  return (
    <AppShell>
      <RequireFeature feature="customers.view">
        <CustomerList />
      </RequireFeature>
    </AppShell>
  );
}

function CustomerList() {
  const router = useRouter();
  const { lookups, hasFeature } = useAuth();
  const [rows, setRows] = useState<CustomerSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState({ q: "", ai: false });
  const [filters, setFilters] = useState({ status_id: "", type_id: "", salesman_id: "", state: "", sort: "name" });
  const [aiInfo, setAiInfo] = useState<AISearchInfo | null>(null);
  const [examples, setExamples] = useState<string[]>([]);

  useEffect(() => {
    if (hasFeature("ai.search")) api.searchStatus().then((s) => setExamples(s.examples.customers)).catch(() => {});
  }, [hasFeature]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (query.ai && query.q) {
        const res = await api.aiSearch<CustomerSummary>("customers", query.q, page, PAGE_SIZE);
        setRows(res.items); setTotal(res.total); setAiInfo(res.ai);
      } else {
        const res = await api.customers({ q: query.q, page, page_size: PAGE_SIZE, ...filters });
        setRows(res.items); setTotal(res.total); setAiInfo(null);
      }
    } catch (e) {
      setError(describeError(e));
    } finally {
      setLoading(false);
    }
  }, [query, page, filters]);

  useEffect(() => { load(); }, [load]);

  const columns: Column<CustomerSummary>[] = [
    { key: "name", header: "Customer", render: (r) => <div><div className="font-medium text-slate-900">{r.CustBusName}</div><div className="text-xs text-slate-500">{r.type_name ?? ""}{r.Industry ? ` · ${r.Industry}` : ""}</div></div> },
    { key: "loc", header: "Location", render: (r) => (r.City ? `${r.City}, ${r.State}` : "—") },
    { key: "status", header: "Status", render: (r) => <div className="flex gap-1"><Badge tone={statusTone(r.status_name)}>{r.status_name ?? "—"}</Badge>{r.OnHold && <Badge tone="red">Hold</Badge>}</div> },
    { key: "sales", header: "Sales", render: (r) => <div><div>{r.salesman_name ?? "—"}</div><div className="text-xs text-slate-500">{r.sales_status_name ?? ""}</div></div> },
    { key: "contract", header: "Contract", render: (r) => <Badge tone={r.ContractOnFile ? "green" : "amber"}>{r.ContractOnFile ? "On file" : "Missing"}</Badge> },
    { key: "jobs", header: "Jobs", align: "right", render: (r) => <span>{r.active_project_count} active <span className="text-slate-400">/ {r.project_count}</span></span> },
    { key: "rev", header: "Revenue/yr", align: "right", render: (r) => formatCompactMoney(r.RevenuePerYear) },
    { key: "phone", header: "Phone", render: (r) => r.Phone ?? "—" },
  ];

  return (
    <>
      <PageHeader
        title="Customers"
        subtitle={`${total.toLocaleString()} contractor and property accounts`}
        actions={hasFeature("customers.edit") && <Link href="/customers/new" className="btn-primary"><Plus className="h-4 w-4" /> New customer</Link>}
      />
      <div className="mb-4 space-y-3">
        <SearchBar
          placeholder="Search business name, city, contact, notes…"
          aiPlaceholder="Describe the accounts you want, e.g. “active general contractors in Boston with jobs running”"
          examples={examples}
          busy={loading}
          aiInfo={aiInfo}
          onSearch={(q, ai) => { setPage(1); setQuery({ q, ai }); }}
        />
        {!(query.ai && query.q) && (
          <div className="flex flex-wrap gap-2">
            <select className="input !w-auto" value={filters.status_id} onChange={(e) => { setPage(1); setFilters({ ...filters, status_id: e.target.value }); }} aria-label="Status">
              <option value="">All statuses</option>
              {lookups?.customer_statuses.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.type_id} onChange={(e) => { setPage(1); setFilters({ ...filters, type_id: e.target.value }); }} aria-label="Type">
              <option value="">All types</option>
              {lookups?.customer_types.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.salesman_id} onChange={(e) => { setPage(1); setFilters({ ...filters, salesman_id: e.target.value }); }} aria-label="Sales rep">
              <option value="">All sales reps</option>
              {lookups?.salesmen.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.state} onChange={(e) => { setPage(1); setFilters({ ...filters, state: e.target.value }); }} aria-label="State">
              <option value="">All states</option>
              {lookups?.states.map((t) => <option key={t.id} value={t.label}>{t.label}</option>)}
            </select>
            <select className="input !w-auto" value={filters.sort} onChange={(e) => { setPage(1); setFilters({ ...filters, sort: e.target.value }); }} aria-label="Sort">
              <option value="name">Sort: name</option>
              <option value="revenue">Sort: revenue</option>
              <option value="newest">Sort: newest</option>
            </select>
          </div>
        )}
      </div>
      <ErrorBox message={error} />
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.CustomerID} loading={loading} onRowClick={(r) => router.push(`/customers/${r.CustomerID}`)} page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
    </>
  );
}
