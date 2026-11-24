"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { ChangeHistory, StaleNotice } from "@/components/ChangeHistory";
import { EntityForm } from "@/components/EntityForm";
import { Badge, ErrorBox, Field, Modal, PageHeader, Section, Spinner, SuccessBox, statusTone } from "@/components/ui";
import { api, describeError, staleConflict } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { EMPLOYEE_SECTIONS, pickInitial } from "@/lib/forms";
import { daysUntil, formatDate, formatDateTime, formatHours, formatMoney } from "@/lib/format";
import type { Employee, EmployeeLicense } from "@/lib/types";

export default function EmployeeDetailPage() {
  return (
    <AppShell>
      <RequireFeature feature="employees.view">
        <EmployeeDetail />
      </RequireFeature>
    </AppShell>
  );
}

function EmployeeDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { hasFeature, lookups, user } = useAuth();
  const canEdit = hasFeature("employees.edit");
  const restricted = lookups?.restricted_fields ?? [];
  const [emp, setEmp] = useState<Employee | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [licenseModal, setLicenseModal] = useState(false);
  const [note, setNote] = useState("");
  const [noteType, setNoteType] = useState("");
  const [stale, setStale] = useState<string | null>(null);
  const [changes, setChanges] = useState(0);

  const load = useCallback(async () => {
    try {
      setEmp(await api.employee(Number(id)));
      setStale(null);
      setChanges((n) => n + 1);
    } catch (e) {
      setError(describeError(e));
    }
  }, [id]);
  const failed = (err: unknown) => {
    const s = staleConflict(err);
    if (s) setStale(s);
    setError(describeError(err));
  };

  useEffect(() => {
    load();
  }, [load]);

  if (error && !emp) return <ErrorBox message={error} />;
  if (!emp) return <Spinner />;

  const e = emp as Employee & Record<string, string | number | boolean | null>;

  const addNote = async () => {
    if (!note.trim()) return;
    try {
      await api.addEmployeeNote(emp.EmployeeID, { EmployeeNote: note.trim(), EmployeeNoteTypeID: noteType ? Number(noteType) : null });
      setNote("");
      setMessage("Note added.");
      await load();
    } catch (err) {
      setError(describeError(err));
    }
  };

  const saveLicenses = async (licenses: EmployeeLicense[]) => {
    try {
      setEmp(await api.updateEmployee(emp.EmployeeID, { licenses: licenses.map(({ state_code, trade_name, license_type_name, EmployeeLicenseID, ...rest }) => rest), expected_version: emp.version }));
      setLicenseModal(false);
      setMessage("Licenses updated.");
      setChanges((n) => n + 1);
    } catch (err) {
      failed(err);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete ${emp.full_name}? This cannot be undone.`)) return;
    try {
      await api.deleteEmployee(emp.EmployeeID);
      router.push("/employees");
    } catch (err) {
      setError(describeError(err));
    }
  };

  if (editing) {
    return (
      <>
        <PageHeader title={`Edit · ${emp.full_name}`} />
        <StaleNotice message={stale} onReload={async () => { setEditing(false); await load(); }} />
        <EntityForm
          sections={EMPLOYEE_SECTIONS}
          initial={pickInitial(emp, EMPLOYEE_SECTIONS)}
          onCancel={() => setEditing(false)}
          onSubmit={async (values) => {
            try {
              setEmp(await api.updateEmployee(emp.EmployeeID, { ...values, expected_version: emp.version }));
              setEditing(false);
              setMessage("Employee saved.");
              setChanges((n) => n + 1);
            } catch (err) {
              const s = staleConflict(err);
              if (s) setStale(s);
              throw new Error(describeError(err));
            }
          }}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={emp.full_name}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(emp.status_name)}>{emp.status_name ?? "No status"}</Badge>
            <span>{emp.trade_name ?? "No trade"}{emp.qualification_name ? ` · ${emp.qualification_name}` : ""}</span>
            <span className="text-slate-400">· Employee #{emp.EmployeeID} · entered by {emp.EmEntryUserName ?? "?"} on {formatDate(emp.EmEntryTimestamp)}</span>
          </span>
        }
        actions={
          <>
            <Link href="/employees" className="btn-secondary">Back to list</Link>
            {canEdit && (
              <button className="btn-primary" onClick={() => setEditing(true)}>
                <Pencil className="h-4 w-4" /> Edit
              </button>
            )}
            {canEdit && user?.OfficeStaffCanDelete && (
              <button className="btn-danger" onClick={remove}>
                <Trash2 className="h-4 w-4" /> Delete
              </button>
            )}
          </>
        }
      />
      <div className="mb-4 space-y-2">
        <ErrorBox message={error} />
        <SuccessBox message={message} />
      </div>
      <StaleNotice message={stale} onReload={load} />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Section title="Profile">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Field label="Mobile" value={e.EmMobilePhone} />
              <Field label="Home phone" value={e.EmHomePhone} />
              <Field label="E-mail" value={e.EmEmail} />
              <Field label="Address" value={[e.EmStreet, e.EmCity && `${e.EmCity}, ${e.EmState} ${e.EmZip ?? ""}`].filter(Boolean).join(" · ") || "—"} className="col-span-2" />
              <Field label="Will travel" value={e.WillTravel} />
              <Field label="Primary trade" value={emp.trade_name} />
              <Field label="Other trades" value={[e.sub_trade1_name, e.sub_trade2_name].filter(Boolean).join(", ") || "—"} />
              <Field label="Qualification" value={emp.qualification_name} />
              <Field label="Experience" value={e.experience_name} />
              <Field label="Years in trade" value={e.YearsInTrade} />
              <Field label="Base rate" value={formatMoney(e.BaseSalary as number | null)} />
              <Field label="OSHA" value={e.OSHA10} />
              <Field label="Payroll company" value={e.payroll_co_name} />
              <Field label="Referred by" value={e.EmReferredBy} />
              {!restricted.includes("EmDOB") && <Field label="Date of birth" value={formatDate(e.EmDOB as string | null)} />}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {[
                ["US citizen", e.USCitizen], ["I-9 complete", e.I9Complete], ["Job app complete", e.JobApplComplete],
                ["Paperwork complete", e.EmApplComplete], ["Posted available", e.PostEmployeeAsAvailable], ["Recruiter", e.Recruiter],
                ["No communication", e.EmployeeNoCommunication],
              ].filter(([label]) => !(restricted.includes("USCitizen") && label === "US citizen") && !(restricted.includes("I9Complete") && label === "I-9 complete")).map(([label, v]) => (
                <Badge key={String(label)} tone={v ? (label === "No communication" ? "red" : "green") : "slate"}>
                  {v ? "✓" : "–"} {label}
                </Badge>
              ))}
            </div>
            {(e.EmAdminNotes || e.EmSalesNotes) && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <Field label="Admin notes" value={e.EmAdminNotes} />
                <Field label="Sales notes" value={e.EmSalesNotes} />
              </div>
            )}
          </Section>

          <Section
            title="Licenses"
            actions={canEdit && <button className="btn-secondary !py-1" onClick={() => setLicenseModal(true)}><Pencil className="h-3.5 w-3.5" /> Manage</button>}
          >
            {emp.licenses.length === 0 && !e.EmLicenseNum ? (
              <p className="text-sm text-slate-500">No licenses on file.</p>
            ) : (
              <table className="table">
                <thead><tr><th>Type</th><th>Number</th><th>State</th><th>Trade</th><th>Expires</th><th>Copy</th></tr></thead>
                <tbody>
                  {e.EmLicenseNum && emp.licenses.length === 0 && (
                    <tr><td>Primary</td><td>{e.EmLicenseNum}</td><td>{e.EmLicensedIn}</td><td>{emp.trade_name}</td><td>{formatDate(e.EmLicenseDateExpires as string | null)}</td><td>—</td></tr>
                  )}
                  {emp.licenses.map((l) => {
                    const d = daysUntil(l.EmployeeLicenseExpDate);
                    return (
                      <tr key={l.EmployeeLicenseID}>
                        <td>{l.license_type_name ?? "—"}</td>
                        <td className="font-mono text-xs">{l.EmployeeLicenseNumber ?? "—"}</td>
                        <td>{l.state_code ?? "—"}</td>
                        <td>{l.trade_name ?? "—"}</td>
                        <td><Badge tone={d === null ? "slate" : d < 0 ? "red" : d <= 60 ? "amber" : "green"}>{formatDate(l.EmployeeLicenseExpDate)}{d !== null && d < 0 ? " · expired" : d !== null && d <= 60 ? ` · ${d}d` : ""}</Badge></td>
                        <td>{l.EmployeeLicenseCopyOnFile ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </Section>

          <Section title="Recent assignments">
            {emp.recent_assignments.length === 0 ? (
              <p className="text-sm text-slate-500">No tracking history.</p>
            ) : (
              <table className="table">
                <thead><tr><th>Week ending</th><th>Customer</th><th>Site</th><th className="text-right">Hours</th><th className="text-right">Pay</th><th className="text-right">Bill</th><th>Grade</th></tr></thead>
                <tbody>
                  {emp.recent_assignments.map((t) => (
                    <tr key={t.TrackingID}>
                      <td>{formatDate(t.WeekEndingDate)}</td>
                      <td><Link className="text-brand-700 hover:underline" href={`/customers/${t.CustomerID}`}>{t.customer_name}</Link></td>
                      <td><Link className="text-brand-700 hover:underline" href={`/projects/${t.ProjectID}`}>{t.site_name}</Link></td>
                      <td className="text-right tabular-nums">{formatHours(t.TotalHours)}{t.OvertimeHours > 0 && <span className="text-amber-700"> (+{formatHours(t.OvertimeHours)} OT)</span>}</td>
                      <td className="text-right tabular-nums">{formatMoney(t.PayRate)}</td>
                      <td className="text-right tabular-nums">{hasFeature("payroll.view") ? formatMoney(t.BillRate) : "•••"}</td>
                      <td>{t.Grade ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </div>

        <div className="space-y-5">
          <Section title="Notes">
            {canEdit && (
              <div className="mb-4 space-y-2">
                <textarea className="input min-h-[72px]" placeholder="Add a note…" value={note} onChange={(ev) => setNote(ev.target.value)} />
                <div className="flex gap-2">
                  <select className="input" value={noteType} onChange={(ev) => setNoteType(ev.target.value)} aria-label="Note type">
                    <option value="">Type…</option>
                    {lookups?.note_types.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
                  </select>
                  <button className="btn-primary" onClick={addNote} disabled={!note.trim()}><Plus className="h-4 w-4" /> Add</button>
                </div>
              </div>
            )}
            <ul className="space-y-3">
              {emp.notes.length === 0 && <li className="text-sm text-slate-500">No notes yet.</li>}
              {emp.notes.map((n) => (
                <li key={n.EmployeeNoteID} className="rounded-md border border-slate-100 bg-slate-50 p-3 text-sm">
                  <div className="text-slate-800">{n.EmployeeNote}</div>
                  <div className="mt-1 text-xs text-slate-500">{n.note_type_name ? `${n.note_type_name} · ` : ""}{n.EmployeeNoteUserName} · {formatDateTime(n.EmployeeNoteTimestamp)}</div>
                </li>
              ))}
            </ul>
          </Section>
          <ChangeHistory entity="employees" id={emp.EmployeeID} refreshKey={changes} />
        </div>
      </div>

      {licenseModal && <LicenseEditor licenses={emp.licenses} onClose={() => setLicenseModal(false)} onSave={saveLicenses} />}
    </>
  );
}

function LicenseEditor({ licenses, onClose, onSave }: { licenses: EmployeeLicense[]; onClose: () => void; onSave: (l: EmployeeLicense[]) => Promise<void> }) {
  const { lookups } = useAuth();
  const [rows, setRows] = useState<EmployeeLicense[]>(licenses.map((l) => ({ ...l })));
  const [busy, setBusy] = useState(false);
  const blank: EmployeeLicense = { EmployeeLicenseStateID: null, EmployeeLicenseTradeID: null, EmployeeLicenseTypeID: null, EmployeeLicenseNumber: "", EmployeeLicenseExpDate: null, EmployeeLicenseCopyOnFile: "No", EmployeeLicenseNotes: null };
  const upd = (i: number, k: keyof EmployeeLicense, v: unknown) => setRows((r) => r.map((row, idx) => (idx === i ? { ...row, [k]: v === "" ? null : v } : row)));
  const num = (v: string) => (v === "" ? null : Number(v));
  return (
    <Modal title="Manage licenses" onClose={onClose} wide>
      <div className="space-y-3">
        {rows.map((l, i) => (
          <div key={i} className="grid grid-cols-2 gap-2 rounded-md border border-slate-200 p-3 sm:grid-cols-6">
            <select className="input" value={l.EmployeeLicenseTypeID ?? ""} onChange={(e) => upd(i, "EmployeeLicenseTypeID", num(e.target.value))} aria-label="License type">
              <option value="">Type…</option>
              {lookups?.license_types.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <input className="input" placeholder="Number" value={l.EmployeeLicenseNumber ?? ""} onChange={(e) => upd(i, "EmployeeLicenseNumber", e.target.value)} aria-label="License number" />
            <select className="input" value={l.EmployeeLicenseStateID ?? ""} onChange={(e) => upd(i, "EmployeeLicenseStateID", num(e.target.value))} aria-label="State">
              <option value="">State…</option>
              {lookups?.states.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </select>
            <select className="input" value={l.EmployeeLicenseTradeID ?? ""} onChange={(e) => upd(i, "EmployeeLicenseTradeID", num(e.target.value))} aria-label="Trade">
              <option value="">Trade…</option>
              {lookups?.trades.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <input className="input" type="date" value={l.EmployeeLicenseExpDate ?? ""} onChange={(e) => upd(i, "EmployeeLicenseExpDate", e.target.value)} aria-label="Expiration" />
            <div className="flex gap-1">
              <select className="input" value={l.EmployeeLicenseCopyOnFile ?? ""} onChange={(e) => upd(i, "EmployeeLicenseCopyOnFile", e.target.value)} aria-label="Copy on file">
                <option value="Yes">Copy: Yes</option>
                <option value="No">Copy: No</option>
              </select>
              <button type="button" className="btn-danger !px-2" onClick={() => setRows((r) => r.filter((_, idx) => idx !== i))} aria-label="Remove license"><Trash2 className="h-4 w-4" /></button>
            </div>
          </div>
        ))}
        <button type="button" className="btn-secondary" onClick={() => setRows((r) => [...r, { ...blank }])}><Plus className="h-4 w-4" /> Add license</button>
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <button className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn-primary" disabled={busy} onClick={async () => { setBusy(true); await onSave(rows); setBusy(false); }}>{busy ? "Saving…" : "Save licenses"}</button>
        </div>
      </div>
    </Modal>
  );
}
