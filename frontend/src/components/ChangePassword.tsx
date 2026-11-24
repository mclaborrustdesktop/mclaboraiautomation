"use client";

import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, describeError } from "@/lib/api";
import { ErrorBox, Modal } from "./ui";

/** Change your own web password. This is separate from the password used in the Access application. */
export function ChangePasswordDialog({ forced, onDone, onClose }: { forced?: boolean; onDone: () => void; onClose: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (next !== again) { setError("The two new passwords do not match."); return; }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      onDone();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={forced ? "Choose your own password" : "Change password"} onClose={forced ? () => {} : onClose}>
      <form onSubmit={submit} className="space-y-4">
        <p className="flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2.5 text-sm text-slate-600 ring-1 ring-slate-100">
          <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" aria-hidden />
          {forced
            ? "An administrator set a temporary password for you. Choose a new one before you continue."
            : "This password is only for this website. It does not change your password in the Access application."}
        </p>
        <div>
          <label className="label" htmlFor="cp-current">{forced ? "Temporary password" : "Current password"}</label>
          <input id="cp-current" type="password" className="input" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" autoFocus required />
        </div>
        <div>
          <label className="label" htmlFor="cp-new">New password</label>
          <input id="cp-new" type="password" className="input" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" required />
        </div>
        <div>
          <label className="label" htmlFor="cp-again">New password again</label>
          <input id="cp-again" type="password" className="input" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required />
        </div>
        <ErrorBox message={error} />
        <div className="flex items-center gap-2">
          <button className="btn-primary" disabled={busy}>{busy ? "Saving…" : "Save password"}</button>
          {!forced && <button type="button" className="btn-secondary" onClick={onClose} disabled={busy}>Cancel</button>}
        </div>
      </form>
    </Modal>
  );
}
