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
import { CUSTOMER_SECTIONS, pickInitial } from "@/lib/forms";
import { formatDate, formatDateTime, formatMoney } from "@/lib/format";
import type { Customer, CustomerContact } from "@/lib/types";

export default function CustomerDetailPage() {
  return (
    <AppShell>
      <RequireFeature feature="customers.view">
        <CustomerDetail />
      </RequireFeature>
    </AppShell>
  );
}

function CustomerDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { hasFeature, user } = useAuth();
  const canEdit = hasFeature("customers.edit");
  const [cust, setCust] = useState<Customer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [contactModal, setContactModal] = useState(false);
  const [note, setNote] = useState("");
  const [stale, setStale] = useState<string | null>(null);
  const [changes, setChanges] = useState(0);

  const load = useCallback(async () => {
    try {
      setCust(await api.customer(Number(id)));
      setStale(null);
      setChanges((n) => n + 1);
    } catch (e) {
      setError(describeError(e));
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  if (error && !cust) return <ErrorBox message={error} />;
  if (!cust) return <Spinner />;
  const c = cust as Customer & Record<string, string | number | boolean | null>;

  const addNote = async () => {
    if (!note.trim()) return;
    try {
      await api.addCustomerNote(cust.CustomerID, { CustomerNote: note.trim() });
      setNote(""); setMessage("Note added."); await load();
    } catch (err) { setError(describeError(err)); }
  };
  const saveContacts = async (contacts: CustomerContact[]) => {
    try {
      setCust(await api.updateCustomer(cust.CustomerID, { contacts: contacts.map(({ title_name, CustomerContactID, ...rest }) => rest), expected_version: cust.version }));
      setContactModal(false); setMessage("Contacts updated."); setChanges((n) => n + 1);
    } catch (err) { const s = staleConflict(err); if (s) setStale(s); setError(describeError(err)); }
  };
  const remove = async () => {
    if (!confirm(`Delete ${cust.CustBusName}? This cannot be undone.`)) return;
    try { await api.deleteCustomer(cust.CustomerID); router.push("/customers"); } catch (err) { setError(describeError(err)); }
  };

  if (editing) {
    return (
      <>
        <PageHeader title={`Edit · ${cust.CustBusName}`} />
        <StaleNotice message={stale} onReload={async () => { setEditing(false); await load(); }} />
        <EntityForm
          sections={CUSTOMER_SECTIONS}
          initial={pickInitial(cust, CUSTOMER_SECTIONS)}
          onCancel={() => setEditing(false)}
          onSubmit={async (values) => {
            try { setCust(await api.updateCustomer(cust.CustomerID, { ...values, expected_version: cust.version })); setEditing(false); setMessage("Customer saved."); setChanges((n) => n + 1); }
            catch (err) { const s = staleConflict(err); if (s) setStale(s); throw new Error(describeError(err)); }
          }}
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={cust.CustBusName}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(cust.status_name)}>{cust.status_name ?? "No status"}</Badge>
            {c.OnHold && <Badge tone="red">On hold</Badge>}
            <span>{cust.type_name ?? ""}{c.Industry ? ` · ${c.Industry}` : ""}</span>
            <span className="text-slate-400">· Customer #{cust.CustomerID} · entered by {cust.CustEntryUserName ?? "?"} on {formatDate(cust.CustEntryTimestamp)}</span>
          </span>
        }
        actions={
          <>
            <Link href="/customers" className="btn-secondary">Back to list</Link>
            {hasFeature("projects.edit") && <Link href={`/projects/new?customer=${cust.CustomerID}`} className="btn-accent"><Plus className="h-4 w-4" /> New job</Link>}
            {canEdit && <button className="btn-primary" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" /> Edit</button>}
            {canEdit && user?.OfficeStaffCanDelete && <button className="btn-danger" onClick={remove}><Trash2 className="h-4 w-4" /> Delete</button>}
          </>
        }
      />
      <div className="mb-4 space-y-2"><ErrorBox message={error} /><SuccessBox message={message} /></div>
      <StaleNotice message={stale} onReload={load} />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Section title="Account">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Field label="Phone" value={c.Phone} />
              <Field label="Fax" value={c.CustFaxNum} />
              <Field label="E-mail" value={c.CustEmail} />
              <Field label="Address" value={[c.Street, c.City && `${c.City}, ${c.State} ${c.Zip ?? ""}`].filter(Boolean).join(" · ") || "—"} className="col-span-2" />
              <Field label="Website" value={c.CustWebSiteHLink ? <a className="text-brand-700 hover:underline" href={String(c.CustWebSiteHLink)} target="_blank" rel="noreferrer">{String(c.CustWebSiteHLink).replace(/^https?:\/\//, "")}</a> : "—"} />
              <Field label="Sales rep" value={cust.salesman_name} />
              <Field label="Sales status" value={c.sales_status_name} />
              <Field label="Company size" value={c.EmployeeSize} />
              <Field label="Contract" value={<Badge tone={c.ContractOnFile ? "green" : "amber"}>{c.ContractOnFile ? `On file · ${formatDate(c.ContractDate as string | null)}` : "Not on file"}</Badge>} />
              <Field label="Contract with" value={c.payroll_co_name} />
              <Field label="Contractor license" value={c.CustomerLicenseNumber} />
              <Field label="Credit limit" value={formatMoney(c.CreditLimit as number | null, 0)} />
              <Field label="Revenue / year" value={formatMoney(c.RevenuePerYear as number | null, 0)} />
              <Field label="Future call" value={formatDate(c.FutureCall as string | null)} />
              {hasFeature("payroll.view") && (
                <>
                  <Field label="A-rate range" value={`${formatMoney(c.LaborRateAFrom as number | null)} – ${formatMoney(c.LaborRateATo as number | null)}`} />
                  <Field label="B-rate range" value={`${formatMoney(c.LaborRateBFrom as number | null)} – ${formatMoney(c.LaborRateBTo as number | null)}`} />
                  <Field label="OT multiplier" value={c.BillRateOTMultiplier} />
                </>
              )}
            </div>
            {(c.CustomerDescription || c.CustomerNote || c.InvoiceNote || c.CollectionsNote) && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <Field label="Description" value={c.CustomerDescription} />
                <Field label="Customer note" value={c.CustomerNote} />
                <Field label="Invoice note" value={c.InvoiceNote} />
                <Field label="Collections note" value={c.CollectionsNote ? <span className="text-red-700">{c.CollectionsNote}</span> : "—"} />
              </div>
            )}
          </Section>

          <Section title="Jobs / projects">
            {cust.projects.length === 0 ? <p className="text-sm text-slate-500">No jobs on file.</p> : (
              <table className="table">
                <thead><tr><th>Site</th><th>Location</th><th>Status</th><th>Start</th><th>End</th><th className="text-right">Workers</th></tr></thead>
                <tbody>
                  {cust.projects.map((p) => (
                    <tr key={p.ProjectID} className="cursor-pointer" onClick={() => router.push(`/projects/${p.ProjectID}`)}>
                      <td className="font-medium">{p.SiteName}</td>
                      <td>{p.SiteCity ? `${p.SiteCity}, ${p.SiteState}` : "—"}</td>
                      <td><Badge tone={statusTone(p.status_name)}>{p.status_name ?? "—"}</Badge></td>
                      <td>{formatDate(p.StartDate)}</td>
                      <td>{formatDate(p.EndDate)}</td>
                      <td className="text-right tabular-nums">{p.assigned_count} / {p.NumberOfEmployees}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
          <ChangeHistory entity="customers" id={cust.CustomerID} refreshKey={changes} />
        </div>

        <div className="space-y-5">
          <Section title="Contacts" actions={canEdit && <button className="btn-secondary !py-1" onClick={() => setContactModal(true)}><Pencil className="h-3.5 w-3.5" /> Manage</button>}>
            <ul className="space-y-3">
              {cust.contacts.length === 0 && <li className="text-sm text-slate-500">No contacts.</li>}
              {[...cust.contacts].sort((a, b) => a.CustomerContactPriority - b.CustomerContactPriority).map((ct, i) => (
                <li key={ct.CustomerContactID ?? i} className="rounded-md border border-slate-100 p-3 text-sm">
                  <div className="font-medium text-slate-900">{ct.CustomerContactFName} {ct.CustomerContactLName} {ct.title_name && <span className="font-normal text-slate-500">· {ct.title_name}</span>}</div>
                  <div className="text-xs text-slate-600">{[ct.CustomerContactCell, ct.CustomerContactOfficePhone, ct.CustomerContactEmail].filter(Boolean).join(" · ")}</div>
                  {ct.CustomerContactNotes && <div className="mt-1 text-xs text-slate-500">{ct.CustomerContactNotes}</div>}
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Notes">
            {canEdit && (
              <div className="mb-4 flex gap-2">
                <textarea className="input min-h-[60px]" placeholder="Add a note…" value={note} onChange={(ev) => setNote(ev.target.value)} />
                <button className="btn-primary" onClick={addNote} disabled={!note.trim()}><Plus className="h-4 w-4" /></button>
              </div>
            )}
            <ul className="space-y-3">
              {cust.notes.length === 0 && <li className="text-sm text-slate-500">No notes yet.</li>}
              {cust.notes.map((n) => (
                <li key={n.CustomerNoteID} className="rounded-md border border-slate-100 bg-slate-50 p-3 text-sm">
                  <div className="text-slate-800">{n.CustomerNote}</div>
                  <div className="mt-1 text-xs text-slate-500">{n.CustomerNoteUserName} · {formatDateTime(n.CustomerNoteTimestamp)}</div>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      </div>

      {contactModal && <ContactEditor contacts={cust.contacts} onClose={() => setContactModal(false)} onSave={saveContacts} />}
    </>
  );
}

function ContactEditor({ contacts, onClose, onSave }: { contacts: CustomerContact[]; onClose: () => void; onSave: (c: CustomerContact[]) => Promise<void> }) {
  const { lookups } = useAuth();
  const [rows, setRows] = useState<CustomerContact[]>(contacts.map((c) => ({ ...c })));
  const [busy, setBusy] = useState(false);
  const blank: CustomerContact = { CustomerContactFName: "", CustomerContactLName: "", CustomerContactTitleID: null, CustomerContactEmail: null, CustomerContactCell: null, CustomerContactOfficePhone: null, CustomerContactNotes: null, CustomerContactPriority: rows.length + 1 };
  const upd = (i: number, k: keyof CustomerContact, v: unknown) => setRows((r) => r.map((row, idx) => (idx === i ? { ...row, [k]: v === "" ? null : v } : row)));
  return (
    <Modal title="Manage contacts" onClose={onClose} wide>
      <div className="space-y-3">
        {rows.map((ct, i) => (
          <div key={i} className="grid grid-cols-2 gap-2 rounded-md border border-slate-200 p-3 sm:grid-cols-6">
            <input className="input" placeholder="First" value={ct.CustomerContactFName} onChange={(e) => upd(i, "CustomerContactFName", e.target.value)} aria-label="First name" />
            <input className="input" placeholder="Last" value={ct.CustomerContactLName} onChange={(e) => upd(i, "CustomerContactLName", e.target.value)} aria-label="Last name" />
            <select className="input" value={ct.CustomerContactTitleID ?? ""} onChange={(e) => upd(i, "CustomerContactTitleID", e.target.value === "" ? null : Number(e.target.value))} aria-label="Title">
              <option value="">Title…</option>
              {lookups?.contact_titles.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
            <input className="input" placeholder="Cell" value={ct.CustomerContactCell ?? ""} onChange={(e) => upd(i, "CustomerContactCell", e.target.value)} aria-label="Cell" />
            <input className="input" placeholder="E-mail" value={ct.CustomerContactEmail ?? ""} onChange={(e) => upd(i, "CustomerContactEmail", e.target.value)} aria-label="E-mail" />
            <div className="flex gap-1">
              <input className="input" type="number" min={1} value={ct.CustomerContactPriority} onChange={(e) => upd(i, "CustomerContactPriority", Number(e.target.value))} aria-label="Priority" title="Priority (1 = primary)" />
              <button type="button" className="btn-danger !px-2" onClick={() => setRows((r) => r.filter((_, idx) => idx !== i))} aria-label="Remove contact"><Trash2 className="h-4 w-4" /></button>
            </div>
          </div>
        ))}
        <button type="button" className="btn-secondary" onClick={() => setRows((r) => [...r, { ...blank }])}><Plus className="h-4 w-4" /> Add contact</button>
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
          <button className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn-primary" disabled={busy || rows.some((r) => !r.CustomerContactFName || !r.CustomerContactLName)} onClick={async () => { setBusy(true); await onSave(rows); setBusy(false); }}>{busy ? "Saving…" : "Save contacts"}</button>
        </div>
      </div>
    </Modal>
  );
}
