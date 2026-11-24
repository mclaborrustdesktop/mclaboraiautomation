"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { AppShell, RequireFeature } from "@/components/AppShell";
import { EntityForm } from "@/components/EntityForm";
import { CustomerPicker } from "@/components/CustomerPicker";
import { ErrorBox, PageHeader } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { PROJECT_SECTIONS, pickInitial } from "@/lib/forms";

function NewProject() {
  const router = useRouter();
  const params = useSearchParams();
  const preset = params.get("customer");
  const [customerId, setCustomerId] = useState<number | null>(preset ? Number(preset) : null);
  const [customerName, setCustomerName] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (customerId) api.customer(customerId).then((c) => setCustomerName(c.CustBusName)).catch(() => {});
  }, [customerId]);

  return (
    <>
      <PageHeader title="New job / project" subtitle="Fields map directly to tblProject in the production schema." />
      <div className="card mb-5 p-5">
        <h2 className="mb-3 text-sm font-semibold tracking-wide text-slate-700 uppercase">Customer <span className="text-red-500">*</span></h2>
        <CustomerPicker value={customerId} label={customerName} onChange={(id, name) => { setCustomerId(id); setCustomerName(name); }} />
      </div>
      <ErrorBox message={error} />
      <EntityForm
        sections={PROJECT_SECTIONS}
        initial={{ ...pickInitial(null, PROJECT_SECTIONS), NumberOfEmployees: 1, ARateQty: 0, BRateQty: 0, CRateQty: 0 }}
        submitLabel="Create job"
        onCancel={() => router.push("/projects")}
        onSubmit={async (values) => {
          if (!customerId) { setError("Select a customer first."); throw new Error("Select a customer first."); }
          try {
            const p = await api.createProject({ ...values, CustomerID: customerId });
            router.push(`/projects/${p.ProjectID}`);
          } catch (err) { throw new Error(describeError(err)); }
        }}
      />
    </>
  );
}

export default function NewProjectPage() {
  return (
    <AppShell>
      <RequireFeature feature="projects.edit">
        <Suspense fallback={null}>
          <NewProject />
        </Suspense>
      </RequireFeature>
    </AppShell>
  );
}
