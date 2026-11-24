"use client";

import { Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { CustomerPicker } from "@/components/CustomerPicker";
import { Badge, ErrorBox, Modal, PageHeader, Spinner, SuccessBox } from "@/components/ui";
import { api, describeError, staleConflict } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatHours, formatMoney, formatPercent, todayISO } from "@/lib/format";
import type { EmployeeSummary, ProjectSummary, Tracking, TrackingSummary } from "@/lib/types";

const DAYS: { key: keyof Tracking; label: string }[] = [
  { key: "SatHours", label: "Sat" }, { key: "SunHours", label: "Sun" }, { key: "MonHours", label: "Mon" }, { key: "TueHours", label: "Tue" },
  { key: "WedHours", label: "Wed" }, { key: "ThuHours", label: "Thu" }, { key: "FriHours", label: "Fri" },
];

export default function TrackingPage() {
  return (
    <AppShell>
      <RequireFeature feature="tracking.view">
        <Suspense fallback={<Spinner />}>
          <TrackingBoard />
        </Suspense>
      </RequireFeature>
    </AppShell>
  );
}

function TrackingBoard() {
  const { hasFeature, user } = useAuth();
  const params = useSearchParams();
  const presetProject = params.get("project");
  const canEdit = hasFeature("tracking.edit");
  const showMoney = hasFeature("payroll.view") && !user?.OfficeStaffHideHours;
  const [weeks, setWeeks] = useState<string[]>([]);
  const [week, setWeek] = useState<string>("");
  const [rows, setRows] = useState<TrackingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Tracking | null>(null);
  const [adding, setAdding] = useState(!!presetProject);

  useEffect(() => {
    api.trackingWeeks().then((w) => { setWeeks(w.weeks); setWeek(w.current); }).catch((e) => setError(describeError(e)));
  }, []);

  const load = useCallback(async () => {
    if (!week) return;
    setLoading(true); setError(null);
    try {
      const res = await api.tracking({ week_ending_date: week, page_size: 500, q, project_id: presetProject ? Number(presetProject) : undefined });
      setRows(res.items);
    } catch (e) { setError(describeError(e)); } finally { setLoading(false); }
  }, [week, q, presetProject]);
  useEffect(() => { load(); }, [load]);

  const totals = useMemo(() => {
    const hours = rows.reduce((s, r) => s + r.TotalHours, 0);
    const ot = rows.reduce((s, r) => s + r.OvertimeHours, 0);
    const inv = rows.reduce((s, r) => s + r.InvoiceAmount, 0);
    const pay = rows.reduce((s, r) => s + r.EmGrossPayroll, 0);
    return { hours, ot, inv, pay, margin: inv ? (inv - pay) / inv : null, workers: new Set(rows.map((r) => r.EmployeeID)).size, customers: new Set(rows.map((r) => r.CustomerID)).size };
  }, [rows]);

  const grouped = useMemo(() => {
    const m = new Map<string, TrackingSummary[]>();
    for (const r of rows) {
      const k = `${r.customer_name} — ${r.site_name}`;
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(r);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [rows]);

  const openEdit = async (id: number) => {
    try { setEditing(await api.trackingOne(id)); } catch (e) { setError(describeError(e)); }
  };
  const remove = async (r: TrackingSummary) => {
    if (!confirm(`Remove ${r.employee_name} from ${r.site_name} for the week ending ${formatDate(r.WeekEndingDate)}?`)) return;
    try { await api.deleteTracking(r.TrackingID); setMessage("Assignment removed."); await load(); } catch (e) { setError(describeError(e)); }
  };

  return (
    <>
      <PageHeader
        title="Weekly Tracking"
        subtitle="Assignments and hours by week (Sat–Fri). Week-ending date is the Friday."
        actions={canEdit && <button className="btn-primary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> Assign worker</button>}
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="text-sm text-slate-600" htmlFor="week">Week ending</label>
        <select id="week" className="input !w-auto" value={week} onChange={(e) => setWeek(e.target.value)}>
          {weeks.map((w) => <option key={w} value={w}>{formatDate(w)}</option>)}
        </select>
        <input className="input !w-64" placeholder="Filter by employee, customer, site…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter" />
        {presetProject && <Link href="/tracking" className="btn-secondary !py-1">Showing one job · clear</Link>}
      </div>
      <div className="mb-4 space-y-2"><ErrorBox message={error} /><SuccessBox message={message} /></div>

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Assignments" value={rows.length} />
        <Stat label="Workers" value={totals.workers} />
        <Stat label="Customers" value={totals.customers} />
        <Stat label="Hours" value={formatHours(totals.hours)} sub={totals.ot ? `${formatHours(totals.ot)} OT` : undefined} />
        {showMoney && <Stat label="Invoice" value={formatMoney(totals.inv, 0)} />}
        {showMoney && <Stat label="Margin" value={formatPercent(totals.margin)} sub={`payroll ${formatMoney(totals.pay, 0)}`} />}
      </div>

      {loading ? <Spinner /> : grouped.length === 0 ? (
        <div className="card p-10 text-center text-sm text-slate-500">No assignments for this week.</div>
      ) : (
        <div className="space-y-4">
          {grouped.map(([title, list]) => (
            <div key={title} className="card overflow-hidden">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-2">
                <div className="text-sm font-semibold text-slate-800">
                  <Link href={`/customers/${list[0].CustomerID}`} className="hover:underline">{list[0].customer_name}</Link>
                  <span className="text-slate-400"> — </span>
                  <Link href={`/projects/${list[0].ProjectID}`} className="hover:underline">{list[0].site_name}</Link>
                </div>
                <div className="text-xs text-slate-500">{list.length} workers · {formatHours(list.reduce((s, r) => s + r.TotalHours, 0))} hrs</div>
              </div>
              <table className="table">
                <thead><tr><th>Employee</th><th>Payroll</th><th className="text-right">Reg</th><th className="text-right">OT</th><th className="text-right">Total</th>{showMoney && <><th className="text-right">Pay</th><th className="text-right">Bill</th><th className="text-right">Margin</th></>}<th>Grade</th><th>Directions</th>{canEdit && <th></th>}</tr></thead>
                <tbody>
                  {list.map((r) => (
                    <tr key={r.TrackingID} className={canEdit ? "cursor-pointer" : ""} onClick={canEdit ? () => openEdit(r.TrackingID) : undefined}>
                      <td className="font-medium">{r.employee_name}{r.Placeholder && <Badge tone="amber">placeholder</Badge>}</td>
                      <td>{r.payroll_on_site ?? "—"}</td>
                      <td className="text-right tabular-nums">{formatHours(r.RegularHours)}</td>
                      <td className="text-right tabular-nums">{r.OvertimeHours ? <span className="text-amber-700">{formatHours(r.OvertimeHours)}</span> : "—"}</td>
                      <td className="text-right font-medium tabular-nums">{formatHours(r.TotalHours)}</td>
                      {showMoney && <><td className="text-right tabular-nums">{formatMoney(r.PayRate)}</td><td className="text-right tabular-nums">{formatMoney(r.BillRate)}</td><td className="text-right tabular-nums">{formatPercent(r.CalcProfitMargin)}</td></>}
                      <td>{r.Grade ?? "—"}</td>
                      <td>{r.DirVerified ? <Badge tone="green">verified</Badge> : <Badge tone="amber">pending</Badge>}</td>
                      {canEdit && <td className="text-right"><button className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={(e) => { e.stopPropagation(); remove(r); }} aria-label="Remove"><Trash2 className="h-4 w-4" /></button></td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      )}

      {editing && <HoursEditor row={editing} showMoney={showMoney} onClose={() => setEditing(null)} onSaved={async () => { setEditing(null); setMessage("Hours saved."); await load(); }} />}
      {adding && <AssignModal week={week} presetProject={presetProject ? Number(presetProject) : null} onClose={() => setAdding(false)} onSaved={async () => { setAdding(false); setMessage("Worker assigned."); await load(); }} />}
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="card px-4 py-3">
      <div className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{label}</div>
      <div className="mt-0.5 text-xl font-semibold text-slate-900 tabular-nums">{value}</div>
      {sub && <div className="text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function HoursEditor({ row, showMoney, onClose, onSaved }: { row: Tracking; showMoney: boolean; onClose: () => void; onSaved: () => Promise<void> }) {
  const [v, setV] = useState<Tracking>({ ...row });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const total = DAYS.reduce((s, d) => s + Number(v[d.key] || 0), 0);
  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const body: Record<string, unknown> = { PayRate: Number(v.PayRate), BillRate: Number(v.BillRate), Grade: v.Grade || null, HoursNote: v.HoursNote || null, DirVerified: v.DirVerified, DirectionsSentEmail: v.DirectionsSentEmail, DirectionsSentText: v.DirectionsSentText, PayrollInfoSent: v.PayrollInfoSent, expected_version: row.version };
      for (const d of DAYS) body[d.key] = Number(v[d.key] || 0);
      await api.updateTracking(row.TrackingID, body);
      await onSaved();
    } catch (e) { setErr(staleConflict(e) ? `${staleConflict(e)} Close this window and open the week again.` : describeError(e)); } finally { setBusy(false); }
  };
  return (
    <Modal title={`${row.employee_name} · ${row.site_name} · week ending ${formatDate(row.WeekEndingDate)}`} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
          {DAYS.map((d) => (
            <div key={d.key}>
              <label className="label" htmlFor={`h-${d.key}`}>{d.label}</label>
              <input id={`h-${d.key}`} type="number" step="0.5" min="0" max="24" className="input text-center" value={String(v[d.key] ?? 0)} onChange={(e) => setV({ ...v, [d.key]: e.target.value === "" ? 0 : Number(e.target.value) })} />
            </div>
          ))}
        </div>
        <div className="text-sm text-slate-600">Total <strong>{formatHours(total)}</strong> hrs · regular {formatHours(Math.min(total, 40))} · overtime {formatHours(Math.max(total - 40, 0))}</div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {showMoney && (
            <>
              <div><label className="label" htmlFor="pay">Pay rate</label><input id="pay" type="number" step="0.25" className="input" value={v.PayRate} onChange={(e) => setV({ ...v, PayRate: Number(e.target.value) })} /></div>
              <div><label className="label" htmlFor="bill">Bill rate</label><input id="bill" type="number" step="0.25" className="input" value={v.BillRate} onChange={(e) => setV({ ...v, BillRate: Number(e.target.value) })} /></div>
            </>
          )}
          <div><label className="label" htmlFor="grade">Grade</label>
            <select id="grade" className="input" value={v.Grade ?? ""} onChange={(e) => setV({ ...v, Grade: e.target.value || null })}><option value="">—</option><option>A</option><option>B</option><option>C</option></select></div>
          <div><label className="label" htmlFor="hnote">Hours note</label><input id="hnote" className="input" value={v.HoursNote ?? ""} onChange={(e) => setV({ ...v, HoursNote: e.target.value })} /></div>
        </div>
        <div className="flex flex-wrap gap-4 text-sm">
          {([["DirectionsSentEmail", "Directions e-mailed"], ["DirectionsSentText", "Directions texted"], ["DirVerified", "Directions verified"], ["PayrollInfoSent", "Payroll info sent"]] as const).map(([k, l]) => (
            <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={Boolean(v[k])} onChange={(e) => setV({ ...v, [k]: e.target.checked })} /> {l}</label>
          ))}
        </div>
        <ErrorBox message={err} />
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <button className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save hours"}</button>
        </div>
      </div>
    </Modal>
  );
}

function AssignModal({ week, presetProject, onClose, onSaved }: { week: string; presetProject: number | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const { lookups } = useAuth();
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [customerName, setCustomerName] = useState("");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState<number | null>(presetProject);
  const [empQ, setEmpQ] = useState("");
  const [emps, setEmps] = useState<EmployeeSummary[]>([]);
  const [employee, setEmployee] = useState<EmployeeSummary | null>(null);
  const [weekEnding, setWeekEnding] = useState(week || todayISO());
  const [pay, setPay] = useState("");
  const [bill, setBill] = useState("");
  const [payrollCo, setPayrollCo] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (presetProject) api.project(presetProject).then((p) => { setCustomerId(p.CustomerID); setCustomerName(p.customer_name ?? ""); }).catch(() => {});
  }, [presetProject]);
  useEffect(() => {
    if (!customerId) { setProjects([]); return; }
    api.projects({ customer_id: customerId, page_size: 100 }).then((r) => setProjects(r.items)).catch(() => {});
  }, [customerId]);
  useEffect(() => {
    if (!empQ.trim()) { setEmps([]); return; }
    const t = setTimeout(() => api.employees({ q: empQ, page_size: 8 }).then((r) => setEmps(r.items)).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [empQ]);
  useEffect(() => {
    if (employee?.BaseSalary && !pay) { setPay(String(employee.BaseSalary)); setBill(String(Math.round(employee.BaseSalary * 1.5 * 100) / 100)); }
  }, [employee, pay]);

  const save = async () => {
    if (!projectId || !employee || !customerId) { setErr("Choose a customer, job and employee."); return; }
    setBusy(true); setErr(null);
    try {
      await api.createTracking({ CustomerID: customerId, ProjectID: projectId, EmployeeID: employee.EmployeeID, WeekEndingDate: weekEnding, PayRate: Number(pay || 0), BillRate: Number(bill || 0), PayrollCoOnSiteID: payrollCo ? Number(payrollCo) : null });
      await onSaved();
    } catch (e) { setErr(describeError(e)); } finally { setBusy(false); }
  };

  return (
    <Modal title="Assign a worker to a job" onClose={onClose} wide>
      <div className="space-y-4">
        <div><div className="label">Customer</div><CustomerPicker value={customerId} label={customerName} onChange={(id, name) => { setCustomerId(id); setCustomerName(name); setProjectId(null); }} /></div>
        <div>
          <label className="label" htmlFor="proj">Job / site</label>
          <select id="proj" className="input" value={projectId ?? ""} onChange={(e) => setProjectId(e.target.value ? Number(e.target.value) : null)} disabled={!customerId}>
            <option value="">{customerId ? "Select a job…" : "Pick a customer first"}</option>
            {projects.map((p) => <option key={p.ProjectID} value={p.ProjectID}>{p.SiteName} · {p.SiteCity ?? ""} · {p.status_name ?? ""}</option>)}
          </select>
        </div>
        <div>
          <div className="label">Employee</div>
          {employee ? (
            <div className="flex items-center gap-3"><span className="rounded-md border border-brand-200 bg-brand-50 px-3 py-1.5 text-sm font-medium text-brand-800">{employee.full_name} · {employee.trade_name ?? ""}</span><button className="btn-secondary !py-1" onClick={() => { setEmployee(null); setPay(""); setBill(""); }}>Change</button></div>
          ) : (
            <div className="relative max-w-md">
              <input className="input" placeholder="Type a name or trade…" value={empQ} onChange={(e) => setEmpQ(e.target.value)} aria-label="Employee search" />
              {emps.length > 0 && (
                <ul className="absolute z-20 mt-1 w-full overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg">
                  {emps.map((e) => (
                    <li key={e.EmployeeID}><button className="flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-brand-50" onClick={() => { setEmployee(e); setEmps([]); }}>
                      <span className="font-medium">{e.full_name}</span><span className="text-xs text-slate-500">{e.trade_name ?? "—"} · {e.EmCity ?? ""} · {e.status_name ?? ""}</span></button></li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div><label className="label" htmlFor="we">Week ending</label><input id="we" type="date" className="input" value={weekEnding} onChange={(e) => setWeekEnding(e.target.value)} /><p className="mt-1 text-xs text-slate-500">Snaps to the Friday</p></div>
          <div><label className="label" htmlFor="apay">Pay rate</label><input id="apay" type="number" step="0.25" className="input" value={pay} onChange={(e) => setPay(e.target.value)} /></div>
          <div><label className="label" htmlFor="abill">Bill rate</label><input id="abill" type="number" step="0.25" className="input" value={bill} onChange={(e) => setBill(e.target.value)} /></div>
          <div><label className="label" htmlFor="pco">Payroll co. on site</label>
            <select id="pco" className="input" value={payrollCo} onChange={(e) => setPayrollCo(e.target.value)}><option value="">—</option>{lookups?.payroll_on_site.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></div>
        </div>
        <ErrorBox message={err} />
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <button className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={busy}>{busy ? "Assigning…" : "Assign"}</button>
        </div>
      </div>
    </Modal>
  );
}
