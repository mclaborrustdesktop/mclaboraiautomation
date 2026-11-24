"use client";

import { Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { ChangeHistory, StaleNotice } from "@/components/ChangeHistory";
import { EntityForm } from "@/components/EntityForm";
import { Badge, ErrorBox, Field, PageHeader, Section, Spinner, SuccessBox, statusTone } from "@/components/ui";
import { api, describeError, staleConflict } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { PROJECT_SECTIONS, pickInitial } from "@/lib/forms";
import { formatDate, formatHours, formatMoney, formatPercent } from "@/lib/format";
import type { Project } from "@/lib/types";

export default function ProjectDetailPage() {
  return (
    <AppShell>
      <RequireFeature feature="projects.view">
        <ProjectDetail />
      </RequireFeature>
    </AppShell>
  );
}

function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { hasFeature, user } = useAuth();
  const canEdit = hasFeature("projects.edit");
  const showMoney = hasFeature("payroll.view");
  const [proj, setProj] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [stale, setStale] = useState<string | null>(null);
  const [changes, setChanges] = useState(0);

  const load = useCallback(async () => {
    try { setProj(await api.project(Number(id))); setStale(null); setChanges((n) => n + 1); } catch (e) { setError(describeError(e)); }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (error && !proj) return <ErrorBox message={error} />;
  if (!proj) return <Spinner />;
  const p = proj as Project & Record<string, string | number | boolean | null>;

  const remove = async () => {
    if (!confirm(`Delete job "${proj.SiteName}"? This cannot be undone.`)) return;
    try { await api.deleteProject(proj.ProjectID); router.push("/projects"); } catch (err) { setError(describeError(err)); }
  };

  if (editing) {
    return (
      <>
        <PageHeader title={`Edit · ${proj.SiteName}`} subtitle={proj.customer_name ?? ""} />
        <StaleNotice message={stale} onReload={async () => { setEditing(false); await load(); }} />
        <EntityForm
          sections={PROJECT_SECTIONS}
          initial={pickInitial(proj, PROJECT_SECTIONS)}
          onCancel={() => setEditing(false)}
          onSubmit={async (values) => {
            try { setProj(await api.updateProject(proj.ProjectID, { ...values, expected_version: proj.version })); setEditing(false); setMessage("Job saved."); setChanges((n) => n + 1); }
            catch (err) { const s = staleConflict(err); if (s) setStale(s); throw new Error(describeError(err)); }
          }}
        />
      </>
    );
  }

  const weeks = new Map<string, typeof proj.assignments>();
  for (const a of proj.assignments) {
    if (!weeks.has(a.WeekEndingDate)) weeks.set(a.WeekEndingDate, []);
    weeks.get(a.WeekEndingDate)!.push(a);
  }

  return (
    <>
      <PageHeader
        title={proj.SiteName}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(proj.status_name)}>{proj.status_name ?? "No status"}</Badge>
            <Badge tone={p.JobBeingManned ? "green" : "amber"}>{p.JobBeingManned ? "Manned" : "Needs crew"}</Badge>
            <Link href={`/customers/${proj.CustomerID}`} className="text-brand-700 hover:underline">{proj.customer_name}</Link>
            <span className="text-slate-400">· Job #{proj.ProjectID} · entered by {proj.ProjectEntryUserName ?? "?"} on {formatDate(proj.ProjectEntryTimestamp)}</span>
          </span>
        }
        actions={
          <>
            <Link href="/projects" className="btn-secondary">Back to list</Link>
            {hasFeature("tracking.edit") && <Link href={`/tracking?project=${proj.ProjectID}`} className="btn-accent">Assign workers</Link>}
            {canEdit && <button className="btn-primary" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" /> Edit</button>}
            {canEdit && user?.OfficeStaffCanDelete && <button className="btn-danger" onClick={remove}><Trash2 className="h-4 w-4" /> Delete</button>}
          </>
        }
      />
      <div className="mb-4 space-y-2"><ErrorBox message={error} /><SuccessBox message={message} /></div>
      <StaleNotice message={stale} onReload={load} />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Section title="Job details">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Field label="Site address" value={[p.SiteStreet, p.SiteCity && `${p.SiteCity}, ${p.SiteState} ${p.SiteZip ?? ""}`].filter(Boolean).join(" · ") || "—"} className="col-span-2" />
              <Field label="Start time" value={p.ProjStartTime} />
              <Field label="Start date" value={formatDate(p.StartDate as string | null)} />
              <Field label="Projected end" value={formatDate(p.EndDate as string | null)} />
              <Field label="Workers needed" value={p.NumberOfEmployees} />
              <Field label="WCC class" value={proj.wcc_code ? `${proj.wcc_code} · ${proj.wcc_desc}` : "—"} className="col-span-2" />
              <Field label="Rate mix (A/B/C)" value={`${p.ARateQty ?? 0} / ${p.BRateQty ?? 0} / ${p.CRateQty ?? 0}`} />
              <Field label="On-site contact" value={p.CustomerContact} />
              <Field label="Contact phone" value={p.CustomerPhone} />
              <Field label="Contact e-mail" value={p.CustomerEmail} />
              {showMoney && (
                <>
                  <Field label="Contract amount" value={formatMoney(p.ContractAmount as number | null, 0)} />
                  <Field label="Payments received" value={formatMoney(p.ContractTotalPayments as number | null, 0)} />
                  <Field label="Balance owed" value={formatMoney(p.ContractBalanceOwed as number | null, 0)} />
                </>
              )}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {[["OCIP", p.OCIPJob], ["Rate job", p.RateJob], ["Shift differential", p.ShiftDifferential], ["GC on site", p.GCOnSite]].map(([l, v]) => (
                <Badge key={String(l)} tone={v ? "blue" : "slate"}>{v ? "✓" : "–"} {l}</Badge>
              ))}
            </div>
            {(p.ProjNote || p.JobNote || p.ProjOfficeNote) && (
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <Field label="Site instructions" value={p.ProjNote} />
                <Field label="Job note" value={p.JobNote} />
                <Field label="Office note" value={p.ProjOfficeNote} />
              </div>
            )}
          </Section>

          <Section title="Weekly assignments">
            {weeks.size === 0 ? <p className="text-sm text-slate-500">No workers assigned yet.</p> : (
              <div className="space-y-4">
                {[...weeks.entries()].map(([we, rows]) => {
                  const hours = rows.reduce((s, r) => s + r.TotalHours, 0);
                  const inv = rows.reduce((s, r) => s + r.InvoiceAmount, 0);
                  const pay = rows.reduce((s, r) => s + r.EmGrossPayroll, 0);
                  return (
                    <div key={we}>
                      <div className="mb-1 flex items-center justify-between text-sm">
                        <span className="font-medium text-slate-800">Week ending {formatDate(we)}</span>
                        <span className="text-xs text-slate-500">{rows.length} workers · {formatHours(hours)} hrs{showMoney && inv > 0 ? ` · invoice ${formatMoney(inv, 0)} · margin ${formatPercent((inv - pay) / inv)}` : ""}</span>
                      </div>
                      <table className="table">
                        <thead><tr><th>Employee</th><th>Payroll co.</th><th className="text-right">Hours</th><th className="text-right">OT</th>{showMoney && <><th className="text-right">Pay</th><th className="text-right">Bill</th></>}<th>Grade</th><th>Dir.</th></tr></thead>
                        <tbody>
                          {rows.map((r) => (
                            <tr key={r.TrackingID}>
                              <td><Link href={`/employees/${r.EmployeeID}`} className="text-brand-700 hover:underline">{r.employee_name}</Link></td>
                              <td>{r.payroll_on_site ?? "—"}</td>
                              <td className="text-right tabular-nums">{formatHours(r.TotalHours)}</td>
                              <td className="text-right tabular-nums">{r.OvertimeHours ? formatHours(r.OvertimeHours) : "—"}</td>
                              {showMoney && <><td className="text-right tabular-nums">{formatMoney(r.PayRate)}</td><td className="text-right tabular-nums">{formatMoney(r.BillRate)}</td></>}
                              <td>{r.Grade ?? "—"}</td>
                              <td>{r.DirVerified ? <Badge tone="green">verified</Badge> : <Badge tone="slate">—</Badge>}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                })}
              </div>
            )}
          </Section>
          <ChangeHistory entity="projects" id={proj.ProjectID} refreshKey={changes} />
        </div>
        <div className="space-y-5">
          <Section title="Summary">
            <div className="grid grid-cols-2 gap-4">
              <Field label="Distinct workers" value={new Set(proj.assignments.map((a) => a.EmployeeID)).size} />
              <Field label="Weeks tracked" value={weeks.size} />
              <Field label="Total hours" value={formatHours(proj.assignments.reduce((s, r) => s + r.TotalHours, 0))} />
              {showMoney && <Field label="Total invoiced" value={formatMoney(proj.assignments.reduce((s, r) => s + r.InvoiceAmount, 0), 0)} />}
            </div>
          </Section>
        </div>
      </div>
    </>
  );
}
