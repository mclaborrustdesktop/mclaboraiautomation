"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { DuplicateWarning, useDuplicateCheck } from "@/components/DuplicateWarning";
import { EntityForm, type FormValues } from "@/components/EntityForm";
import { PageHeader } from "@/components/ui";
import { api, describeError, duplicateMatches } from "@/lib/api";
import { EMPLOYEE_SECTIONS, pickInitial } from "@/lib/forms";
import type { DuplicateMatch } from "@/lib/types";

const s = (v: unknown) => (typeof v === "string" ? v.trim() : v ?? null);

export default function NewEmployeePage() {
  const router = useRouter();
  const [conflict, setConflict] = useState<{ matches: DuplicateMatch[]; values: FormValues } | null>(null);
  const [forcing, setForcing] = useState(false);
  const live = useDuplicateCheck(
    api.checkEmployeeDuplicates,
    (v) => ({ EmFirstName: s(v.EmFirstName), EmLastName: s(v.EmLastName), EmMobilePhone: s(v.EmMobilePhone), EmHomePhone: s(v.EmHomePhone), EmEmail: s(v.EmEmail), EmDOB: v.EmDOB || null }),
    (f) => (String(f.EmFirstName ?? "").length >= 2 && String(f.EmLastName ?? "").length >= 2) || String(f.EmEmail ?? "").includes("@") || String(f.EmMobilePhone ?? "").replace(/\D/g, "").length >= 7,
  );

  const createAnyway = async () => {
    if (!conflict) return;
    setForcing(true);
    try {
      const e = await api.createEmployee({ ...conflict.values, allow_duplicate: true });
      router.push(`/employees/${e.EmployeeID}`);
    } catch (err) {
      setForcing(false);
      alert(describeError(err));
    }
  };

  return (
    <AppShell>
      <RequireFeature feature="employees.edit">
        <PageHeader title="New employee" subtitle="We check for existing workers with the same name, phone or e-mail as you type." />
        <EntityForm
          sections={EMPLOYEE_SECTIONS}
          initial={{ ...pickInitial(null, EMPLOYEE_SECTIONS), USCitizen: true }}
          submitLabel="Create employee"
          onCancel={() => router.push("/employees")}
          onValuesChange={(v) => { live.onValuesChange(v); if (conflict) setConflict(null); }}
          onSubmit={async (values) => {
            try {
              const e = await api.createEmployee(values);
              router.push(`/employees/${e.EmployeeID}`);
            } catch (err) {
              const matches = duplicateMatches(err);
              if (matches) {
                setConflict({ matches, values });
                throw new Error("Not saved: this looks like an employee who is already on file. Review the matches above.");
              }
              throw new Error(describeError(err));
            }
          }}
        >
          <DuplicateWarning
            matches={conflict ? conflict.matches : live.matches}
            hrefBase="/employees"
            blocked={!!conflict}
            onCreateAnyway={createAnyway}
            busy={forcing}
          />
        </EntityForm>
      </RequireFeature>
    </AppShell>
  );
}
