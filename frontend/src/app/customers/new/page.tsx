"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { DuplicateWarning, useDuplicateCheck } from "@/components/DuplicateWarning";
import { EntityForm, type FormValues } from "@/components/EntityForm";
import { PageHeader } from "@/components/ui";
import { api, describeError, duplicateMatches } from "@/lib/api";
import { CUSTOMER_SECTIONS, pickInitial } from "@/lib/forms";
import type { DuplicateMatch } from "@/lib/types";

const s = (v: unknown) => (typeof v === "string" ? v.trim() : v ?? null);

export default function NewCustomerPage() {
  const router = useRouter();
  const [conflict, setConflict] = useState<{ matches: DuplicateMatch[]; values: FormValues } | null>(null);
  const [forcing, setForcing] = useState(false);
  const live = useDuplicateCheck(
    api.checkCustomerDuplicates,
    (v) => ({ CustBusName: s(v.CustBusName), Phone: s(v.Phone), CustEmail: s(v.CustEmail), CustWebSiteHLink: s(v.CustWebSiteHLink) }),
    (f) => String(f.CustBusName ?? "").length >= 3 || String(f.CustEmail ?? "").includes("@") || String(f.Phone ?? "").replace(/\D/g, "").length >= 7 || String(f.CustWebSiteHLink ?? "").includes("."),
  );

  const createAnyway = async () => {
    if (!conflict) return;
    setForcing(true);
    try {
      const c = await api.createCustomer({ ...conflict.values, allow_duplicate: true });
      router.push(`/customers/${c.CustomerID}`);
    } catch (err) {
      setForcing(false);
      alert(describeError(err));
    }
  };

  return (
    <AppShell>
      <RequireFeature feature="customers.edit">
        <PageHeader title="New customer" subtitle="We check for existing customers with the same name, phone, e-mail or website as you type." />
        <EntityForm
          sections={CUSTOMER_SECTIONS}
          initial={{ ...pickInitial(null, CUSTOMER_SECTIONS), BillRateOTMultiplier: 1.5 }}
          submitLabel="Create customer"
          onCancel={() => router.push("/customers")}
          onValuesChange={(v) => { live.onValuesChange(v); if (conflict) setConflict(null); }}
          onSubmit={async (values) => {
            try {
              const c = await api.createCustomer(values);
              router.push(`/customers/${c.CustomerID}`);
            } catch (err) {
              const matches = duplicateMatches(err);
              if (matches) {
                setConflict({ matches, values });
                throw new Error("Not saved: this looks like a customer that is already on file. Review the matches above.");
              }
              throw new Error(describeError(err));
            }
          }}
        >
          <DuplicateWarning
            matches={conflict ? conflict.matches : live.matches}
            hrefBase="/customers"
            blocked={!!conflict}
            onCreateAnyway={createAnyway}
            busy={forcing}
          />
        </EntityForm>
      </RequireFeature>
    </AppShell>
  );
}
