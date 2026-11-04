"use client";

import { useState, type FormEvent } from "react";
import { OPERATIONS } from "@/components/inventory/Recon";
import { useMe, useReconSettings, useSaveReconSettings, type ReconSettings as Settings } from "@/lib/api/hooks";
import { asTyped, parseMajor } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

/**
 * The dealer's reconditioning rules (docs/lifecycle/README.md § L3): the budget
 * a car starts with, and a rate per unit of each operation, which is what turns
 * "two panels to paint" read from a photo into an estimate. A rate left empty
 * falls back to what that work cost the last few times, or to a person typing it.
 */
export function ReconSettings() {
  const t = useT();
  const me = useMe();
  const settings = useReconSettings();
  const save = useSaveReconSettings();
  const [problem, setProblem] = useState<string | null>(null);
  const currency = me.data?.tenant.currency ?? "AED";

  if (!settings.data) return <p className="text-muted text-sm">…</p>;
  const current = settings.data;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const read = (name: string): number | null | undefined => {
      const typed = String(form.get(name) ?? "").trim();
      if (!typed) return null;
      return parseMajor(typed, currency) ?? undefined;
    };
    const budget = read("budget");
    const rates: NonNullable<Settings["rates"]> = {};
    let bad = budget === undefined;
    for (const operation of OPERATIONS) {
      const rate = read(`rate-${operation}`);
      if (rate === undefined) bad = true;
      else if (rate !== null) rates[operation] = rate;
    }
    if (bad) return setProblem(t("costs.badAmount"));
    setProblem(null);
    save.mutate({ default_budget_minor: budget ?? null, rates });
  };

  const rates = current.rates ?? {};
  return (
    <section className="max-w-xl">
      <h1 className="text-lg font-semibold">{t("settings.recon")}</h1>
      <p className="text-muted mt-1 text-sm">{t("reconSettings.intro")}</p>

      <form key={JSON.stringify(current)} onSubmit={submit} className="mt-4 space-y-4 text-sm">
        <label className="block text-xs">
          <span className="text-muted">
            {t("reconSettings.budget")} ({currency})
          </span>
          <input
            name="budget"
            inputMode="decimal"
            dir="ltr"
            defaultValue={
              current.default_budget_minor != null
                ? asTyped(current.default_budget_minor, currency)
                : ""
            }
            className="field mt-1 w-full"
          />
          <span className="text-muted mt-1 block">{t("reconSettings.budgetHint")}</span>
        </label>

        <fieldset>
          <legend className="font-medium">{t("reconSettings.rates")}</legend>
          <p className="text-muted text-xs">{t("reconSettings.ratesHint")}</p>
          <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {OPERATIONS.map((operation) => {
              const rate = rates[operation];
              return (
                <label key={operation} className="text-xs">
                  <span className="text-muted">{t(`reconOperation.${operation}`)}</span>
                  <input
                    name={`rate-${operation}`}
                    inputMode="decimal"
                    dir="ltr"
                    defaultValue={rate != null ? asTyped(rate, currency) : ""}
                    className="field mt-1 w-full"
                  />
                </label>
              );
            })}
          </div>
        </fieldset>

        <div className="flex items-center gap-3">
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {t("common.save")}
          </button>
          {save.isSuccess && <span className="text-muted text-xs">{t("pricingSettings.saved")}</span>}
          {(problem ?? save.error?.message) && (
            <span className="text-danger text-xs">{problem ?? save.error?.message}</span>
          )}
        </div>
      </form>
    </section>
  );
}
