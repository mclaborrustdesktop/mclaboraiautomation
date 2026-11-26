"use client";

import { Laptop, ShieldCheck, ShieldOff } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Badge, ErrorBox, SuccessBox } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import type { User, WebDevice } from "@/lib/types";

/** Administrators: the devices behind the password screen (approved-device boundary). Shown only when the server has it on. */
export function DevicesPanel({ staff }: { staff: User[] }) {
  const [enabled, setEnabled] = useState(false);
  const [devices, setDevices] = useState<WebDevice[]>([]);
  const [limit, setLimit] = useState(0);
  const [approved, setApproved] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [choice, setChoice] = useState<Record<number, { staff: string; label: string }>>({});

  const load = useCallback(async () => {
    try {
      const r = await api.devices();
      setEnabled(r.enabled);
      setDevices(r.devices);
      setLimit(r.limit);
      setApproved(r.approved);
    } catch {
      setEnabled(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (!enabled) return null;

  const approve = async (d: WebDevice) => {
    const c = choice[d.id];
    if (!c?.staff) { setError("Choose the employee this device belongs to."); return; }
    setError(null);
    try {
      await api.approveDevice(d.id, c.staff, c.label || "");
      setMessage(`Device ${d.pairing_code} approved for ${c.staff}.`);
      await load();
    } catch (e) { setError(describeError(e)); }
  };
  const revoke = async (d: WebDevice) => {
    setError(null);
    try {
      await api.revokeDevice(d.id);
      setMessage(`Device ${d.label ?? d.id} revoked. Its open session ends at once.`);
      await load();
    } catch (e) { setError(describeError(e)); }
  };
  const nameOf = (id: number | null) => staff.find((s) => s.OfficeStaffID === id)?.OfficeStaffFullName ?? (id ? `staff #${id}` : "—");
  const pending = devices.filter((d) => d.status === "pending");
  const others = devices.filter((d) => d.status !== "pending");

  return (
    <section className="mb-6 rounded-lg border border-slate-200 bg-white" aria-label="Approved devices">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-900"><Laptop className="h-4 w-4" /> Approved devices <span className="text-slate-500">({approved} approved, limit {limit})</span></div>
        <div className="text-xs text-slate-500">Each device holds its own key; the password alone opens nothing from an unknown device.</div>
      </div>
      <div className="space-y-2 px-4 py-3"><ErrorBox message={error} /><SuccessBox message={message} /></div>
      {pending.length > 0 && (
        <div className="px-4 pb-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-700">Waiting for approval</div>
          <ul className="space-y-2">
            {pending.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
                <span className="font-mono text-base font-semibold tracking-widest">{d.pairing_code}</span>
                <span className="text-xs text-slate-600">{d.created_at?.replace("T", " ")} · {d.created_ip} · {(d.user_agent ?? "").slice(0, 60)}</span>
                <select className="input !w-auto !py-0.5 text-xs" aria-label={`Employee for device ${d.pairing_code}`} value={choice[d.id]?.staff ?? ""}
                  onChange={(e) => setChoice({ ...choice, [d.id]: { staff: e.target.value, label: choice[d.id]?.label ?? "" } })}>
                  <option value="">Employee…</option>
                  {staff.filter((s) => s.OfficeStaffActive).map((s) => <option key={s.OfficeStaffID} value={s.Initials}>{s.OfficeStaffFullName} ({s.Initials})</option>)}
                </select>
                <input className="input !w-48 !py-0.5 text-xs" placeholder="Label, e.g. office PC" aria-label={`Label for device ${d.pairing_code}`} value={choice[d.id]?.label ?? ""}
                  onChange={(e) => setChoice({ ...choice, [d.id]: { staff: choice[d.id]?.staff ?? "", label: e.target.value } })} />
                <button className="btn-primary !py-1 text-xs" onClick={() => approve(d)}><ShieldCheck className="h-3.5 w-3.5" /> Approve</button>
                <button className="btn-secondary !py-1 text-xs" onClick={() => revoke(d)}><ShieldOff className="h-3.5 w-3.5" /> Reject</button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="px-4 pb-4">
        {others.length === 0 ? <div className="text-xs text-slate-500">No approved devices yet.</div> : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Device</th><th>Employee</th><th>Status</th><th>Last used</th><th></th></tr></thead>
            <tbody>
              {others.map((d) => (
                <tr key={d.id} className="border-t border-slate-100">
                  <td className="py-1.5">{d.label ?? `device #${d.id}`}<div className="text-xs text-slate-500">{(d.user_agent ?? "").slice(0, 50)}</div></td>
                  <td>{nameOf(d.staff_id)}</td>
                  <td><Badge tone={d.status === "approved" ? "green" : "red"}>{d.status}</Badge></td>
                  <td className="text-xs text-slate-600">{d.last_used_at?.replace("T", " ") ?? "never"} {d.last_ip ? `· ${d.last_ip}` : ""} · {d.uses} use{d.uses === 1 ? "" : "s"}</td>
                  <td className="text-right">{d.status === "approved" && <button className="btn-secondary !py-1 text-xs" onClick={() => revoke(d)}><ShieldOff className="h-3.5 w-3.5" /> Revoke</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
