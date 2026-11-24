"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth";
import type { LookupItem, Lookups } from "@/lib/types";
import { ErrorBox } from "./ui";

export type FieldType = "text" | "number" | "money" | "date" | "select" | "checkbox" | "textarea" | "email" | "tel";

export interface FieldSpec {
  name: string;
  label: string;
  type?: FieldType;
  lookup?: keyof Lookups;
  options?: { value: string; label: string }[];
  required?: boolean;
  placeholder?: string;
  span?: 1 | 2 | 3;
  help?: string;
  /** filter lookup options against the current form value of another field (e.g. cities by state) */
  dependsOn?: { field: string; extraKey: string };
}

export interface FormSection {
  title: string;
  fields: FieldSpec[];
}

export type FormValues = Record<string, unknown>;

interface Props {
  sections: FormSection[];
  initial: FormValues;
  onSubmit: (values: FormValues) => Promise<void>;
  onCancel?: () => void;
  submitLabel?: string;
  busyLabel?: string;
  children?: React.ReactNode; // extra custom sections rendered before buttons
  /** called with the raw form values whenever a field changes (e.g. live duplicate checks) */
  onValuesChange?: (values: FormValues) => void;
}

export function cleanValues(values: FormValues, sections: FormSection[]): FormValues {
  const out: FormValues = {};
  for (const s of sections) {
    for (const f of s.fields) {
      const v = values[f.name];
      const t = f.type ?? "text";
      if (t === "checkbox") out[f.name] = Boolean(v);
      else if (t === "number" || t === "money" || t === "select") {
        if (v === "" || v === null || v === undefined) out[f.name] = null;
        else if (t === "select" && f.options) out[f.name] = v; // string-valued select
        else out[f.name] = Number(v);
      } else out[f.name] = v === "" || v === undefined ? null : v;
    }
  }
  return out;
}

export function EntityForm({ sections: allSections, initial, onSubmit, onCancel, submitLabel = "Save", busyLabel = "Saving…", children, onValuesChange }: Props) {
  const { lookups } = useAuth();
  // fields the server withholds in production (date of birth, citizenship, I-9) are neither shown nor sent
  const sections = useMemo(() => {
    const hidden = lookups?.restricted_fields ?? [];
    return hidden.length === 0 ? allSections : allSections.map((s) => ({ ...s, fields: s.fields.filter((f) => !hidden.includes(f.name)) })).filter((s) => s.fields.length > 0);
  }, [allSections, lookups]);
  const [values, setValues] = useState<FormValues>(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // fire only when the values change (not when the parent re-renders with a new callback)
  const onChangeRef = useRef(onValuesChange);
  onChangeRef.current = onValuesChange;
  useEffect(() => { onChangeRef.current?.(values); }, [values]);

  const set = (name: string, v: unknown) => setValues((prev) => ({ ...prev, [name]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    for (const s of sections) {
      for (const f of s.fields) {
        if (f.required && (values[f.name] === "" || values[f.name] === null || values[f.name] === undefined)) {
          setError(`${f.label} is required.`);
          return;
        }
      }
    }
    setBusy(true);
    try {
      await onSubmit(cleanValues(values, sections));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-5">
      {sections.map((s) => (
        <section key={s.title} className="card p-5">
          <h2 className="mb-4 text-sm font-semibold tracking-wide text-slate-700 uppercase">{s.title}</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {s.fields.map((f) => (
              <FormField key={f.name} spec={f} value={values[f.name]} values={values} lookups={lookups} onChange={(v) => set(f.name, v)} />
            ))}
          </div>
        </section>
      ))}
      {children}
      <ErrorBox message={error} />
      <div className="flex items-center gap-2">
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? busyLabel : submitLabel}
        </button>
        {onCancel && (
          <button type="button" className="btn-secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function FormField({ spec, value, values, lookups, onChange }: { spec: FieldSpec; value: unknown; values: FormValues; lookups: Lookups | null; onChange: (v: unknown) => void }) {
  const t = spec.type ?? "text";
  const span = spec.span === 3 ? "sm:col-span-2 lg:col-span-3" : spec.span === 2 ? "sm:col-span-2" : "";
  const id = `f-${spec.name}`;

  const options: { value: string; label: string }[] = useMemo(() => {
    if (spec.options) return spec.options;
    if (spec.lookup && lookups) {
      let items = (lookups[spec.lookup] ?? []) as LookupItem[];
      if (spec.dependsOn) {
        const dep = values[spec.dependsOn.field];
        if (dep !== "" && dep !== null && dep !== undefined) items = items.filter((i) => String(i.extra?.[spec.dependsOn!.extraKey]) === String(dep));
      }
      return items.map((i) => ({ value: String(i.id), label: spec.lookup === "cities" ? `${i.label}, ${i.extra?.state ?? ""}` : i.label }));
    }
    return [];
  }, [spec, lookups, values]);

  if (t === "checkbox") {
    return (
      <label className={`flex items-center gap-2 pt-5 text-sm text-slate-700 ${span}`} htmlFor={id}>
        <input id={id} type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        {spec.label}
      </label>
    );
  }

  return (
    <div className={span}>
      <label className="label" htmlFor={id}>
        {spec.label}
        {spec.required && <span className="text-red-500"> *</span>}
      </label>
      {t === "select" ? (
        <select id={id} className="input" value={value === null || value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value)}>
          <option value="">— select —</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : t === "textarea" ? (
        <textarea id={id} className="input min-h-[84px]" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} placeholder={spec.placeholder} />
      ) : (
        <input
          id={id}
          className="input"
          type={t === "money" || t === "number" ? "number" : t}
          step={t === "money" ? "0.01" : t === "number" ? "1" : undefined}
          value={value === null || value === undefined ? "" : String(value)}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.placeholder}
        />
      )}
      {spec.help && <p className="mt-1 text-xs text-slate-500">{spec.help}</p>}
    </div>
  );
}
