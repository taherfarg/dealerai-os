"use client";

import { useState, type FormEvent } from "react";
import {
  usePricingSettings,
  useSavePricingSettings,
  type PricingSettings as Settings,
} from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

type Step = NonNullable<Settings["steps"]>[number];

/** Basis points to the percentage a person types, and back. 1200 ↔ "12". */
const toPercent = (bps: number) => String(bps / 100);
const toBps = (text: string) => Math.round(Number(text) * 100);

/**
 * The dealer's pricing rules (docs/lifecycle/README.md § L2): the margin it
 * aims for, the margin the floor keeps, rounding, when demand means hold, and
 * the aging ladder. Changing them changes tomorrow's proposals, never a price.
 * And what keeping a car costs (§ L8), which the dashboard and the brief count.
 */
export function PricingSettings() {
  const t = useT();
  const settings = usePricingSettings();
  const save = useSavePricingSettings();
  const [steps, setSteps] = useState<Step[] | null>(null);

  if (!settings.data) return <p className="text-muted text-sm">…</p>;
  const current = settings.data;
  const ladder = steps ?? current.steps ?? [];

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    save.mutate({
      enabled: form.get("enabled") === "on",
      target_margin_bps: toBps(String(form.get("target"))),
      floor_margin_bps: toBps(String(form.get("floor"))),
      round_to_major: Number(form.get("round")),
      hold_if_leads_30d: Number(form.get("hold")),
      holding_rate_bps: toBps(String(form.get("holdingRate"))),
      holding_per_day_major: Number(form.get("holdingPerDay")),
      steps: ladder,
    });
  };

  const editStep = (index: number, change: Partial<Step>) =>
    setSteps(ladder.map((step, i) => (i === index ? { ...step, ...change } : step)));

  return (
    <section className="max-w-xl">
      <h1 className="text-lg font-semibold">{t("settings.pricing")}</h1>
      <p className="text-muted mt-1 text-sm">{t("pricingSettings.intro")}</p>

      <form key={JSON.stringify(current)} onSubmit={submit} className="mt-4 space-y-3 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" name="enabled" defaultChecked={current.enabled ?? true} />
          {t("pricingSettings.enabled")}
        </label>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-xs">
            <span className="text-muted">{t("pricingSettings.target")}</span>
            <input
              name="target"
              type="number"
              min={0}
              max={90}
              step={0.5}
              dir="ltr"
              required
              defaultValue={toPercent(current.target_margin_bps ?? 1200)}
              className="field mt-1 w-full"
            />
          </label>
          <label className="text-xs">
            <span className="text-muted">{t("pricingSettings.floor")}</span>
            <input
              name="floor"
              type="number"
              min={0}
              max={90}
              step={0.5}
              dir="ltr"
              required
              defaultValue={toPercent(current.floor_margin_bps ?? 500)}
              className="field mt-1 w-full"
            />
          </label>
          <label className="text-xs">
            <span className="text-muted">{t("pricingSettings.round")}</span>
            <input
              name="round"
              type="number"
              min={1}
              dir="ltr"
              required
              defaultValue={current.round_to_major ?? 500}
              className="field mt-1 w-full"
            />
          </label>
          <label className="text-xs">
            <span className="text-muted">{t("pricingSettings.hold")}</span>
            <input
              name="hold"
              type="number"
              min={0}
              dir="ltr"
              required
              defaultValue={current.hold_if_leads_30d ?? 3}
              className="field mt-1 w-full"
            />
          </label>
          <label className="text-xs">
            <span className="text-muted">{t("pricingSettings.holdingRate")}</span>
            <input
              name="holdingRate"
              type="number"
              min={0}
              max={50}
              step={0.5}
              dir="ltr"
              required
              defaultValue={toPercent(current.holding_rate_bps ?? 800)}
              className="field mt-1 w-full"
            />
          </label>
          <label className="text-xs">
            <span className="text-muted">{t("pricingSettings.holdingPerDay")}</span>
            <input
              name="holdingPerDay"
              type="number"
              min={0}
              dir="ltr"
              required
              defaultValue={current.holding_per_day_major ?? 0}
              className="field mt-1 w-full"
            />
          </label>
        </div>

        <fieldset>
          <legend className="font-medium">{t("pricingSettings.ladder")}</legend>
          <p className="text-muted text-xs">{t("pricingSettings.ladderHint")}</p>
          <ul className="mt-2 space-y-2">
            {ladder.map((step, index) => (
              <li key={index} className="flex flex-wrap items-end gap-2">
                <label className="text-xs">
                  <span className="text-muted">{t("pricingSettings.days")}</span>
                  <input
                    type="number"
                    min={1}
                    dir="ltr"
                    value={step.days}
                    onChange={(event) => editStep(index, { days: Number(event.target.value) })}
                    className="field mt-1 w-24"
                  />
                </label>
                <label className="text-xs">
                  <span className="text-muted">{t("pricingSettings.cut")}</span>
                  <input
                    type="number"
                    min={0.5}
                    max={50}
                    step={0.5}
                    dir="ltr"
                    value={step.cut_bps / 100}
                    onChange={(event) => editStep(index, { cut_bps: toBps(event.target.value) })}
                    className="field mt-1 w-24"
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={() => setSteps(ladder.filter((_, i) => i !== index))}
                >
                  {t("pricingSettings.removeStep")}
                </button>
              </li>
            ))}
          </ul>
          <button
            type="button"
            className="btn mt-2"
            onClick={() => {
              const last = ladder.at(-1)?.days ?? 30;
              setSteps([...ladder, { days: last + 30, cut_bps: 300 }]);
            }}
          >
            {t("pricingSettings.addStep")}
          </button>
        </fieldset>

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
