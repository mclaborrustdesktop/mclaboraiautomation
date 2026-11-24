"use client";

import { Plus, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { DataTable, type Column } from "@/components/DataTable";
import { Badge, ErrorBox, Modal, PageHeader, SuccessBox } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AccessSummary, User } from "@/lib/types";

const ROLE_PRESETS: Record<string, string[]> = {
  "Office Manager": ["employees.view", "employees.edit", "customers.view", "customers.edit", "projects.view", "projects.edit", "tracking.view", "tracking.edit", "payroll.view", "reports.view", "ai.search"],
  Recruiter: ["employees.view", "employees.edit", "projects.view", "tracking.view", "ai.search", "reports.view"],
  "Sales Representative": ["customers.view", "customers.edit", "projects.view", "projects.edit", "employees.view", "ai.search", "reports.view"],
  Dispatcher: ["employees.view", "customers.view", "projects.view", "projects.edit", "tracking.view", "tracking.edit", "ai.search"],
  "Payroll Specialist": ["employees.view", "tracking.view", "tracking.edit", "payroll.view", "reports.view"],
  Accounting: ["customers.view", "tracking.view", "payroll.view", "reports.view"],
  "Safety Coordinator": ["employees.view", "projects.view", "ai.search"],
};

export default function UsersPage() {
  return (
    <AppShell>
      <RequireFeature feature="users.manage">
        <UserAdmin />
      </RequireFeature>
    </AppShell>
  );
}

function UserAdmin() {
  const { user: me, lookups } = useAuth();
  const realData = !!lookups && lookups.environment !== "demo";
  const [rows, setRows] = useState<User[]>([]);
  const [summary, setSummary] = useState<AccessSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [active, setActive] = useState("true");
  const [editing, setEditing] = useState<User | null | "new">(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setRows((await api.users({ q, active: active === "" ? undefined : active === "true", page_size: 200 })).items);
      if (realData) setSummary(await api.accessSummary());
    }
    catch (e) { setError(describeError(e)); } finally { setLoading(false); }
  }, [q, active, realData]);
  useEffect(() => { load(); }, [load]);

  /** real data: grant or remove website access; effective on the person's next request, no restart */
  const changeAccess = async (u: User, role: "admin" | "user" | "none") => {
    setError(null);
    try { await api.setWebAccess(u.OfficeStaffID, role); setMessage(`${u.OfficeStaffFullName}: website access set to ${role === "none" ? "none" : role === "user" ? "look-up only" : "administrator"}.`); await load(); }
    catch (e) { setError(describeError(e)); }
  };

  const columns: Column<User>[] = [
    { key: "name", header: "User", render: (u) => <div><div className="font-medium text-slate-900">{u.OfficeStaffFullName} <span className="font-mono text-xs text-slate-500">{u.Initials}</span></div><div className="text-xs text-slate-500">{u.OfficeStaffEmail}</div></div> },
    { key: "title", header: "Role / title", render: (u) => u.OfficeStaffTitle ?? "—" },
    { key: "admin", header: "Access", render: (u) => <div className="flex flex-wrap items-center gap-1">
        {realData ? (
          <select className="input !w-auto !py-0.5 text-xs" value={u.web_access === "admin" || u.web_access === "user" ? u.web_access : "none"} aria-label={`Website access for ${u.OfficeStaffFullName}`}
            disabled={u.web_access_source === "settings" || u.OfficeStaffID === me?.OfficeStaffID || !u.OfficeStaffActive}
            title={u.web_access_source === "settings" ? "Named in the website's settings file: changed on the server" : u.OfficeStaffID === me?.OfficeStaffID ? "You cannot change your own access" : "Takes effect on the person's next request"}
            onClick={(e) => e.stopPropagation()} onChange={(e) => { e.stopPropagation(); changeAccess(u, e.target.value as "admin" | "user" | "none"); }}>
            <option value="none">No website access</option><option value="user">Look-up only</option><option value="admin">Administrator</option>
          </select>
        ) : u.Profile && <Badge tone="violet"><ShieldCheck className="mr-1 h-3 w-3" />Admin</Badge>}
        {realData && u.web_access_source === "settings" && <Badge tone="slate">from settings</Badge>}
        {u.OfficeStaffCanDelete && <Badge tone="amber">Can delete</Badge>}<Badge tone={u.OfficeStaffActive ? "green" : "slate"}>{u.OfficeStaffActive ? "Active" : "Inactive"}</Badge></div> },
    { key: "features", header: "Permissions", render: (u) => <span className="text-xs text-slate-600">{u.Profile ? "All features" : u.web_access === "user" ? "Employees, customers, jobs, tracking, AI search (read)" : u.web_access === "none" ? "No website access" : `${u.features.length} features`}</span> },
  ];

  return (
    <>
      <PageHeader title="Users & Permissions" subtitle={realData ? "Office staff (tblOfficeStaff). Website access is granted here and takes effect at once; nothing is written to the McLabor database." : "Office staff accounts (tblOfficeStaff) and per-feature permissions (tblOfficeStaffPermission)."} actions={!realData && <button className="btn-primary" onClick={() => setEditing("new")}><Plus className="h-4 w-4" /> New user</button>} />
      {summary && (
        <div className={`mb-4 rounded-md border px-4 py-3 text-sm ${summary.warning ? "border-amber-300 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-700"}`} role={summary.warning ? "alert" : undefined}>
          <span className="font-medium">{summary.authorized}{summary.seat_limit ? ` of ${summary.seat_limit}` : ""} people authorized</span>
          {" · "}{summary.administrators} administrator{summary.administrators === 1 ? "" : "s"}, {summary.users} look-up only{" · "}{summary.used_this_month} used the website this month
          {summary.message && <div className="mt-1">{summary.message}</div>}
        </div>
      )}
      <div className="mb-4 flex flex-wrap gap-2">
        <input className="input !w-72" placeholder="Search name, initials, e-mail, role…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search users" />
        <select className="input !w-auto" value={active} onChange={(e) => setActive(e.target.value)} aria-label="Active filter"><option value="true">Active only</option><option value="false">Inactive only</option><option value="">All users</option></select>
      </div>
      <div className="mb-4 space-y-2"><ErrorBox message={error} /><SuccessBox message={message} /></div>
      <DataTable columns={columns} rows={rows} rowKey={(u) => u.OfficeStaffID} loading={loading} onRowClick={realData ? undefined : (u) => setEditing(u)} />
      {editing && <UserEditor user={editing === "new" ? null : editing} isSelf={editing !== "new" && editing.OfficeStaffID === me?.OfficeStaffID} onClose={() => setEditing(null)} onSaved={async (msg) => { setEditing(null); setMessage(msg); await load(); }} />}
    </>
  );
}

function UserEditor({ user, isSelf, onClose, onSaved }: { user: User | null; isSelf: boolean; onClose: () => void; onSaved: (msg: string) => Promise<void> }) {
  const { lookups } = useAuth();
  const [v, setV] = useState({
    OfficeStaffFirstName: user?.OfficeStaffFirstName ?? "", OfficeStaffLastName: user?.OfficeStaffLastName ?? "", Initials: user?.Initials ?? "",
    OfficeStaffTitle: user?.OfficeStaffTitle ?? "", OfficeStaffEmail: user?.OfficeStaffEmail ?? "", Profile: user?.Profile ?? false,
    OfficeStaffActive: user?.OfficeStaffActive ?? true, OfficeStaffCanDelete: user?.OfficeStaffCanDelete ?? false,
    OfficeStaffHideHours: user?.OfficeStaffHideHours ?? false, OfficeStaffEmployeeResearch: user?.OfficeStaffEmployeeResearch ?? false,
    OfficeStaffTrackingReportEmailReceive: user?.OfficeStaffTrackingReportEmailReceive ?? false, password: "",
  });
  const [featureIds, setFeatureIds] = useState<number[]>(user?.feature_ids ?? []);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const features = lookups?.features ?? [];
  const toggle = (id: number) => setFeatureIds((f) => (f.includes(id) ? f.filter((x) => x !== id) : [...f, id]));
  const applyPreset = (role: string) => {
    const objs = ROLE_PRESETS[role];
    if (!objs) return;
    setFeatureIds(features.filter((f) => objs.includes(String(f.extra?.object))).map((f) => f.id));
    setV((x) => ({ ...x, OfficeStaffTitle: role }));
  };

  const save = async () => {
    setBusy(true); setErr(null);
    try {
      const body: Record<string, unknown> = { ...v, feature_ids: featureIds };
      if (!body.password) delete body.password;
      if (user) { await api.updateUser(user.OfficeStaffID, body); await onSaved("User saved."); }
      else { if (!v.password) throw new Error("A password is required for a new user."); await api.createUser(body); await onSaved("User created."); }
    } catch (e) { setErr(describeError(e)); } finally { setBusy(false); }
  };
  const deactivate = async () => {
    if (!user || !confirm(`Deactivate ${user.OfficeStaffFullName}? They will no longer be able to sign in.`)) return;
    setBusy(true);
    try { await api.deactivateUser(user.OfficeStaffID); await onSaved("User deactivated."); } catch (e) { setErr(describeError(e)); } finally { setBusy(false); }
  };

  const text = (k: keyof typeof v, label: string, type = "text", span = "") => (
    <div className={span}><label className="label" htmlFor={`u-${k}`}>{label}</label><input id={`u-${k}`} type={type} className="input" value={String(v[k] ?? "")} onChange={(e) => setV({ ...v, [k]: e.target.value })} autoComplete={type === "password" ? "new-password" : "off"} /></div>
  );
  const check = (k: keyof typeof v, label: string, disabled = false) => (
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={Boolean(v[k])} disabled={disabled} onChange={(e) => setV({ ...v, [k]: e.target.checked })} /> {label}</label>
  );

  return (
    <Modal title={user ? `Edit user · ${user.OfficeStaffFullName}` : "New user"} onClose={onClose} wide>
      <div className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {text("OfficeStaffFirstName", "First name")}
          {text("OfficeStaffLastName", "Last name")}
          {text("Initials", "Initials (login)")}
          {text("OfficeStaffEmail", "E-mail", "email")}
          <div>
            <label className="label" htmlFor="u-role">Role / title</label>
            <input id="u-role" className="input" list="role-presets" value={v.OfficeStaffTitle} onChange={(e) => setV({ ...v, OfficeStaffTitle: e.target.value })} onBlur={(e) => { if (ROLE_PRESETS[e.target.value] && !user) applyPreset(e.target.value); }} />
            <datalist id="role-presets">{Object.keys(ROLE_PRESETS).map((r) => <option key={r} value={r} />)}</datalist>
          </div>
          {text("password", user ? "New password (leave blank to keep)" : "Password", "password")}
        </div>
        <div className="flex flex-wrap gap-4">
          {check("Profile", "Administrator (all features)", isSelf)}
          {check("OfficeStaffActive", "Active", isSelf)}
          {check("OfficeStaffCanDelete", "Can delete records")}
          {check("OfficeStaffHideHours", "Hide pay/bill rates")}
          {check("OfficeStaffEmployeeResearch", "Employee research")}
          {check("OfficeStaffTrackingReportEmailReceive", "Receives tracking report e-mail")}
        </div>
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="label !mb-0">Feature permissions {v.Profile && <span className="text-slate-400">(admins have all)</span>}</div>
            <div className="flex flex-wrap gap-1 text-xs">
              <span className="text-slate-500">Preset:</span>
              {Object.keys(ROLE_PRESETS).map((r) => <button key={r} type="button" className="rounded border border-slate-200 bg-white px-2 py-0.5 hover:bg-slate-50" onClick={() => applyPreset(r)}>{r}</button>)}
            </div>
          </div>
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((f) => (
              <label key={f.id} className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${featureIds.includes(f.id) ? "border-brand-200 bg-brand-50" : "border-slate-200"} ${v.Profile ? "opacity-60" : ""}`}>
                <input type="checkbox" className="mt-0.5" checked={featureIds.includes(f.id)} disabled={v.Profile} onChange={() => toggle(f.id)} />
                <span><span className="font-medium text-slate-800">{f.label}</span><br /><span className="text-xs text-slate-500">{String(f.extra?.description ?? "")}</span></span>
              </label>
            ))}
          </div>
        </div>
        <ErrorBox message={err} />
        <div className="flex items-center justify-between gap-2 border-t border-slate-100 pt-3">
          <div>{user && !isSelf && user.OfficeStaffActive && <button className="btn-danger" onClick={deactivate} disabled={busy}>Deactivate</button>}</div>
          <div className="flex gap-2"><button className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button><button className="btn-primary" onClick={save} disabled={busy}>{busy ? "Saving…" : user ? "Save user" : "Create user"}</button></div>
        </div>
      </div>
    </Modal>
  );
}
