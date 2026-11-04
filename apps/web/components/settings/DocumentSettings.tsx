"use client";

import type { FormEvent } from "react";
import { useDocumentSettings, useSaveDocumentSettings } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

const FIELDS = ["legal_name", "address", "phone", "email", "trn", "invoice_prefix"] as const;

/**
 * Who the documents say sold the car (docs/lifecycle/README.md § L7): the
 * seller block on every commercial invoice. A signed invoice keeps what it said.
 */
export function DocumentSettings() {
  const t = useT();
  const settings = useDocumentSettings();
  const save = useSaveDocumentSettings();
  if (!settings.data) return <p className="text-muted text-sm">…</p>;
  const current = settings.data;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim() || null;
    save.mutate({
      legal_name: text("legal_name"),
      address: text("address"),
      phone: text("phone"),
      email: text("email"),
      trn: text("trn"),
      invoice_prefix: text("invoice_prefix") ?? "INV",
    });
  };

  return (
    <section className="max-w-xl">
      <h1 className="text-lg font-semibold">{t("settings.documents")}</h1>
      <p className="text-muted mt-1 text-sm">{t("documentSettings.intro")}</p>
      <form key={JSON.stringify(current)} onSubmit={submit} className="mt-4 space-y-3 text-sm">
        {FIELDS.map((name) => (
          <label key={name} className="block text-xs">
            <span className="text-muted">{t(`documentSettings.${name}`)}</span>
            {name === "address" ? (
              <textarea
                name={name}
                rows={3}
                maxLength={500}
                defaultValue={current[name] ?? ""}
                className="field mt-1 w-full"
              />
            ) : (
              <input
                name={name}
                dir={name === "legal_name" ? undefined : "ltr"}
                defaultValue={current[name] ?? ""}
                className="field mt-1 w-full"
              />
            )}
          </label>
        ))}
        <div className="flex items-center gap-3">
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {t("common.save")}
          </button>
          {save.isSuccess && <span className="text-muted text-xs">{t("pricingSettings.saved")}</span>}
          {save.isError && <span className="text-danger text-xs">{save.error.message}</span>}
        </div>
      </form>
    </section>
  );
}
