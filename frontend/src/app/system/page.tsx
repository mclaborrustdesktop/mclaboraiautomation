"use client";

import { AlertTriangle, CheckCircle2, Database, KeyRound, Lock, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { EnvironmentBadge } from "@/components/EnvironmentBadge";
import { Badge, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { SystemStatus } from "@/lib/types";

export default function SystemPage() {
  return (
    <AppShell>
      <Status />
    </AppShell>
  );
}

function Status() {
  const { user } = useAuth();
  const [s, setS] = useState<SystemStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.Profile) api.systemStatus().then(setS).catch((e) => setError(describeError(e)));
  }, [user]);

  if (!user?.Profile) return <div className="card p-8 text-center text-sm text-slate-600">Only administrators can see the system status.</div>;
  if (error) return <ErrorBox message={error} />;
  if (!s) return <Spinner label="Checking the system…" />;

  const environment = s.environment ?? s.database.data_source ?? "demo"; // older backends report only data_source
  const production = environment !== "demo"; // staging or production: real data on SQL Server
  const live = environment === "production";
  return (
    <>
      <PageHeader title="System status" subtitle="Where the data comes from and which safeguards are active. No passwords are shown here." />

      <div className={`mb-5 flex items-start gap-3 rounded-xl border p-4 ${production ? "border-amber-300 bg-amber-50" : "border-sky-200 bg-sky-50"}`}>
        <Database className={`mt-0.5 h-5 w-5 shrink-0 ${production ? "text-amber-600" : "text-sky-600"}`} />
        <div>
          <div className="flex flex-wrap items-center gap-2 font-semibold text-slate-900">{live ? "Connected to the LIVE McLabor database" : production ? "Staging: connected to a restored COPY of the McLabor database" : "Demo mode: synthetic data only"} <EnvironmentBadge environment={environment} /></div>
          <p className="text-sm text-slate-600">
            {production
              ? `Server ${s.database.expected_server_name ?? "?"}, database ${s.database.database}. Changes to this database are ${s.production_writes}. Every connection is refused unless that exact server answers.`
              : "The website is not connected to the McLabor SQL Server. Nothing you do here touches real records or the Access application."}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card icon={Database} title="Data source">
          <Row label="Environment" value={s.environment_label ?? environment} />
          <Row label="Mode" value={s.database.mode} />
          <Row label="Only server allowed" value={s.database.expected_server_name ?? "none (local demo file)"} />
          <Row label="Database" value={s.database.database} />
          <Row label="Server configured" value={<YesNo ok={s.database.server_configured} yes="Yes" no="Not yet" neutral />} />
          <Row label="SQL Server sign-in" value={s.database.auth} />
          <Row label="ODBC driver" value={<>{s.database.driver} <YesNo ok={s.database.driver_installed} yes="installed" no="missing" /></>} />
        </Card>

        <Card icon={Lock} title="Safeguards">
          <Row label="Changes to real data" value={<YesNo ok={s.production_writes === "disabled"} yes="Disabled" no="ENABLED" />} />
          <Row label="Write approval recorded" value={s.database.write_approval_recorded ? "Yes" : "No"} />
          <Row label="Restricted fields" value={<YesNo ok={production ? s.restricted_fields_withheld : true} yes={production ? "Withheld" : "Shown (demo data)"} no="NOT withheld" />} />
          <p className="mt-2 text-xs text-slate-500">Never requested from production: {s.restricted_fields.join(", ")}</p>
        </Card>

        <Card icon={ShieldCheck} title="Database structure check">
          <Row label="Compared with" value={s.schema_check.source} />
          <Row label="Result" value={<YesNo ok={s.schema_check.ok} yes="Matches" no="Differences found" />} />
          <Row label="Checked" value={`${s.schema_check.tables_checked} tables, ${s.schema_check.columns_checked} columns`} />
          {s.schema_check.missing_tables.length > 0 && <p className="mt-2 text-xs text-red-700">Missing tables: {s.schema_check.missing_tables.join(", ")}</p>}
          {s.schema_check.type_mismatches.length > 0 && <p className="mt-2 text-xs text-red-700">Type differences: {s.schema_check.type_mismatches.join("; ")}</p>}
        </Card>

        <Card icon={KeyRound} title="Web sign-in">
          <Row label="Passwords stored in" value={s.sign_in.store} />
          <Row label="Staff with a web password" value={s.sign_in.accounts_with_web_password} />
          <Row label="Demo sign-in offered" value={<YesNo ok={!s.sign_in.demo_sign_in_offered || !production} yes={s.sign_in.demo_sign_in_offered ? "Yes (demo data)" : "No"} no="Yes" />} />
          <Row label="Lockout" value={s.sign_in.lockout} />
          <Row label="Minimum password length" value={s.sign_in.minimum_password_length} />
        </Card>

        <Card icon={Sparkles} title="AI search">
          <Row label="Mode" value={s.ai_mode === "claude" ? `Claude (${s.claude_model})` : "Built-in parser (nothing leaves this PC)"} />
        </Card>

        <Card icon={AlertTriangle} title="Things to fix before real users">
          {s.warnings.length === 0 ? <p className="text-sm text-slate-600">Nothing reported.</p> : (
            <ul className="space-y-2 text-sm text-slate-700">
              {s.warnings.map((w) => <li key={w} className="flex items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />{w}</li>)}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function Card({ icon: Icon, title, children }: { icon: typeof Database; title: string; children: ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-slate-900"><Icon className="h-4 w-4 text-brand-500" /> {title}</h2>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-100 py-2 text-sm last:border-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-900">{value}</span>
    </div>
  );
}

function YesNo({ ok, yes, no, neutral }: { ok: boolean; yes: string; no: string; neutral?: boolean }) {
  return ok
    ? <Badge tone="green"><CheckCircle2 className="h-3 w-3" /> {yes}</Badge>
    : <Badge tone={neutral ? "slate" : "red"}>{no}</Badge>;
}
