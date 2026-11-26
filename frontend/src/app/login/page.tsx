"use client";

import { ShieldCheck, Sparkles, Users } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { api, describeError } from "@/lib/api";
import { createCredential, getAssertion, webauthnSupported } from "@/lib/webauthn";
import { useAuth } from "@/lib/auth";
import { EnvironmentBadge } from "@/components/EnvironmentBadge";
import { ErrorBox } from "@/components/ui";

function LoginForm() {
  const { login, user, loading, accessMode } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  // The demo sign-in is offered only when the server says it is running on demo data.
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [demo, setDemo] = useState(false);
  const [environment, setEnvironment] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // There is a sign-in form only in "login" mode. In the demo and behind the company gateway this page
  // sends people straight to the site.
  useEffect(() => {
    if (!loading && (user || (accessMode && accessMode !== "login" && accessMode !== "passcode"))) router.replace(next);
  }, [loading, user, router, next, accessMode]);

  useEffect(() => {
    api.health().then((h) => {
      setEnvironment(h.environment ?? (h.database === "sqlite" ? "demo" : "production"));
      if (!(h.demo ?? h.database === "sqlite")) return;
      setDemo(true);
      setUsername((u) => u || "ADMIN");
      setPassword((p) => p || "mclabor2025");
    }).catch(() => {});
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      router.replace(next);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  if (accessMode !== "login") return null; // no sign-in form in the demo or behind the gateway

  return (
    <form onSubmit={submit} className="space-y-4">
      {environment && <EnvironmentBadge environment={environment} />}
      <div>
        <label className="label" htmlFor="username">Initials or e-mail</label>
        <input id="username" className="input h-10"value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
      </div>
      <div>
        <label className="label" htmlFor="password">Password</label>
        <input id="password" type="password" className="input h-10"value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      </div>
      <ErrorBox message={error} />
      <button className="btn-primary h-10 w-full" disabled={busy}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
      {demo && <p className="rounded-lg bg-slate-50 px-3 py-2.5 text-center text-xs text-slate-500 ring-1 ring-slate-100">
        Demo: every seeded user signs in with password <code className="rounded bg-white px-1 ring-1 ring-slate-200">mclabor2025</code>. Use <strong>ADMIN</strong> for full access.
      </p>}
    </form>
  );
}

/** ACCESS_MODE=passcode: one site password, no user name. The server records every attempt and locks an address after
 * repeated failures; the message it returns is shown as is (it never says more than "incorrect" or "try again later").
 * With approved devices on, the correct password is followed by the device step: the browser signs a server challenge
 * with the key its authenticator holds for this site; an unknown device registers and waits for an administrator. */
function PasscodeForm() {
  const { unlock, setSession, user, loading, accessMode } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ticket, setTicket] = useState<string | null>(null);
  const [pairing, setPairing] = useState<string | null>(null);
  const [pairingStatus, setPairingStatus] = useState<string>("pending");
  const [bootstrap, setBootstrap] = useState("");
  const [showBootstrap, setShowBootstrap] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace(next);
  }, [loading, user, router, next]);

  // the waiting screen asks every 10 s whether the administrator approved this device
  useEffect(() => {
    if (!pairing || pairingStatus !== "pending") return;
    const id = window.setInterval(async () => {
      try {
        const s = (await api.deviceStatus(pairing)).status;
        if (s !== "pending") setPairingStatus(s);
      } catch { /* keep waiting */ }
    }, 10000);
    return () => window.clearInterval(id);
  }, [pairing, pairingStatus]);

  /** sign the server's challenge with this device; register it first when it holds no credential for this site */
  const deviceStep = async (t: string, bootstrapCode?: string) => {
    if (!webauthnSupported()) throw new Error("This browser cannot hold a device credential. Use a current Chrome, Edge, Safari or Firefox on a device with Windows Hello, Touch ID or a security key.");
    const o = await api.deviceOptions(t);
    let assertion: unknown;
    try {
      assertion = await getAssertion(o.options);
    } catch {
      // no credential on this device for this site: create one and wait for approval
      const ro = await api.deviceRegisterOptions(t);
      const created = await createCredential(ro.options);
      const reg = await api.deviceRegisterVerify({ ticket: t, challenge: ro.challenge, credential: created });
      setPairing(reg.pairing_code);
      setPairingStatus("pending");
      return;
    }
    try {
      const res = await api.deviceVerify({ ticket: t, challenge: o.challenge, credential: assertion, bootstrap_code: bootstrapCode || undefined });
      if (res.stage === "session") {
        await setSession(res);
        router.replace(next);
      }
    } catch (err) {
      const d = (err as { detail?: { detail?: { code?: string; pairing_code?: string; message?: string } } }).detail?.detail;
      if (d && typeof d === "object" && d.code === "pending" && d.pairing_code) {
        setPairing(d.pairing_code);
        setPairingStatus("pending");
        return;
      }
      throw err;
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await unlock(password);
      setPassword("");
      if (res.stage === "session") {
        router.replace(next);
      } else {
        setTicket(res.ticket);
        await deviceStep(res.ticket);
      }
    } catch (err) {
      setError(describeError(err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  /** after the administrator approved the device (or with the one-time bootstrap code): a fresh password, then the device */
  const retry = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await unlock(password);
      setPassword("");
      if (res.stage === "session") router.replace(next);
      else { setTicket(res.ticket); await deviceStep(res.ticket, bootstrap || undefined); }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  if (accessMode !== "passcode") return null;

  if (pairing) {
    return (
      <form onSubmit={retry} className="space-y-4" aria-label="Device approval">
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <div className="font-medium">{pairingStatus === "approved" ? "This device is approved." : pairingStatus === "revoked" ? "Access from this device was revoked." : "This device is waiting for an administrator's approval."}</div>
          <div className="mt-1">Pairing code: <span className="font-mono text-base font-semibold tracking-widest">{pairing}</span></div>
          {pairingStatus === "pending" && <div className="mt-1 text-xs">Give this code to an administrator. The page checks automatically; once approved, enter the password again.</div>}
        </div>
        <div>
          <label className="label" htmlFor="site-password-2">Access password</label>
          <input id="site-password-2" type="password" className="input h-11 text-base" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        </div>
        {showBootstrap ? (
          <div>
            <label className="label" htmlFor="bootstrap">Administrator bootstrap code (first device only)</label>
            <input id="bootstrap" className="input h-11" value={bootstrap} onChange={(e) => setBootstrap(e.target.value)} autoComplete="off" />
          </div>
        ) : (
          <button type="button" className="text-xs text-slate-500 underline" onClick={() => setShowBootstrap(true)}>I have the administrator bootstrap code</button>
        )}
        <ErrorBox message={error} />
        <button className="btn-primary h-11 w-full text-base" disabled={busy || !password || pairingStatus === "revoked"}>{busy ? "Checking…" : "Continue"}</button>
      </form>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-4" aria-label="Access password">
      <div>
        <label className="label" htmlFor="site-password">Access password</label>
        <input id="site-password" type="password" className="input h-11 text-base" value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password" autoFocus required />
      </div>
      <ErrorBox message={error} />
      <button className="btn-primary h-11 w-full text-base" disabled={busy || !password}>
        {busy ? (ticket ? "Checking this device…" : "Checking…") : "Enter"}
      </button>
      <p className="text-center text-xs text-slate-500">Authorized MC Labor Sources staff only. Every entry is recorded, and access ends automatically after a period of inactivity.</p>
    </form>
  );
}

const HIGHLIGHTS = [
  { icon: Sparkles, title: "AI search", text: "Find the right workers, customers and jobs by just describing them." },
  { icon: Users, title: "One place for every record", text: "Employees, customers, jobs and weekly tracking, all connected." },
  { icon: ShieldCheck, title: "Role-based access", text: "Each office user sees only what their permissions allow." },
];

export default function LoginPage() {
  const { accessMode } = useAuth();
  if (accessMode !== "login" && accessMode !== "passcode") {
    // Demo / company gateway: nothing to sign in to. LoginForm only performs the redirect to the site.
    return <Suspense fallback={null}><LoginForm /></Suspense>;
  }
  const passcode = accessMode === "passcode";
  return (
    <div className="grid min-h-screen bg-white lg:grid-cols-2">
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <img src="/brand/mclabor-logo.png" alt="MC Labor Sources Inc." className="h-8 w-auto self-start" />
        <div className="flex flex-1 items-center">
          <div className="mx-auto w-full max-w-sm py-10">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{passcode ? "MC Labor Search" : "Sign in to your workspace"}</h1>
            <p className="mt-1.5 mb-8 text-sm text-slate-500">{passcode ? "Enter the access password to open the search dashboard." : "Office portal for MC Labor Sources staff."}</p>
            <Suspense fallback={null}>
              {passcode ? <PasscodeForm /> : <LoginForm />}
            </Suspense>
          </div>
        </div>
        <p className="text-xs text-slate-400">© MC Labor Sources Inc.</p>
      </div>

      <div className="relative hidden overflow-hidden bg-brand-700 lg:flex lg:flex-col lg:justify-center lg:px-16">
        <div className="pointer-events-none absolute -top-32 -right-32 h-96 w-96 rounded-full bg-brand-500/50 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-brand-900/60 blur-3xl" aria-hidden />
        <div className="relative max-w-md">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white shadow-lg"><img src="/brand/mclabor-mark.png" alt="" className="h-12 w-12" /></div>
          <h2 className="mt-8 text-3xl leading-tight font-semibold text-white">Staffing operations, simplified.</h2>
          <p className="mt-3 text-brand-100">Everything your office team needs to place the right people on the right jobs.</p>
          <ul className="mt-10 space-y-5">
            {HIGHLIGHTS.map((h) => (
              <li key={h.title} className="flex gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/10 text-white ring-1 ring-white/20"><h.icon className="h-5 w-5" /></span>
                <div>
                  <div className="font-medium text-white">{h.title}</div>
                  <div className="text-sm text-brand-100">{h.text}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
