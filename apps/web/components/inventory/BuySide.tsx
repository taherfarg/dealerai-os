"use client";

import { useState, type FormEvent } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import { StatTile } from "@/components/manager/StatTile";
import {
  useAcquisition,
  useAddCosts,
  useCosts,
  useDeleteCost,
  useEconomics,
  useSaveAcquisition,
  type Acquisition,
  type CostIn,
} from "@/lib/api/hooks";
import { formatMoney, parseMajor } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { PricingCard } from "./PricingCard";
import { ReadInvoice } from "./ReadInvoice";

export const CATEGORIES: readonly CostIn["category"][] = [
  "purchase",
  "auction_fee",
  "transport",
  "shipping",
  "customs",
  "registration",
  "inspection",
  "repair",
  "parts",
  "detailing",
  "photography",
  "storage",
  "commission",
  "other",
];

const SOURCES: readonly Acquisition["source"][] = [
  "auction",
  "trade_in",
  "private",
  "dealer",
  "import",
  "other",
];

/**
 * What the dealer paid, and what the car makes — the buy side.
 *
 * Only ever mounted for someone with costs.view; the API refuses anyone else,
 * and Postgres shows them nothing even if it did not.
 */
export function BuySide({ vehicleId, canEdit }: { vehicleId: string; canEdit: boolean }) {
  const t = useT();
  const economics = useEconomics(vehicleId, true);
  const costs = useCosts(vehicleId, true);
  const remove = useDeleteCost(vehicleId);
  const money = economics.data;
  // The dealer's own currency is whatever the landed cost is counted in.
  const home = money?.landed_cost.currency ?? "AED";

  return (
    <div className="space-y-6">
      {money && (
        <section>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile label={t("economics.landed")} value={formatMoney(money.landed_cost)} />
            <StatTile
              label={t("economics.atPrice")}
              value={money.margin_at_price ? formatMoney(money.margin_at_price) : "—"}
              hint={
                money.margin_bps_at_price != null
                  ? `${(money.margin_bps_at_price / 100).toFixed(1)}%`
                  : undefined
              }
              tone={
                money.margin_at_price
                  ? money.margin_at_price.amount_minor < 0
                    ? "bad"
                    : "ok"
                  : null
              }
            />
            <StatTile
              label={t("economics.atFloor")}
              value={money.margin_at_floor ? formatMoney(money.margin_at_floor) : "—"}
              tone={
                money.margin_at_floor
                  ? money.margin_at_floor.amount_minor < 0
                    ? "bad"
                    : "ok"
                  : null
              }
            />
            <StatTile
              label={t("inventory.days")}
              value={String(money.days_in_stock)}
            />
          </div>
          <p className="text-muted mt-2 text-xs">
            {t("economics.paid")} <Ltr>{formatMoney(money.cost_actual)}</Ltr>
            {money.cost_estimate.amount_minor > 0 && (
              <>
                {" · "}
                {t("economics.estimated")} <Ltr>{formatMoney(money.cost_estimate)}</Ltr>
              </>
            )}
            {money.floor && (
              <>
                {" · "}
                {t("economics.floor")} <Ltr>{formatMoney(money.floor)}</Ltr>
              </>
            )}
            {" · "}
            {t("economics.daysHeld")} <Ltr>{String(money.days_held)}</Ltr>
            {" · "}
            {t("economics.holding")} <Ltr>{formatMoney(money.holding_cost)}</Ltr>
          </p>
          {money.margin_note && (
            <p className="text-muted mt-1 text-xs">
              {money.cost_lines === 0 ? t("economics.noCost") : t("economics.otherCurrency")}
            </p>
          )}
        </section>
      )}

      <PricingCard vehicleId={vehicleId} />

      <AcquisitionForm vehicleId={vehicleId} canEdit={canEdit} />

      <section>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">{t("costs.title")}</h2>
        </div>
        {costs.data && costs.data.length === 0 && (
          <p className="text-muted mt-2 text-sm">{t("costs.empty")}</p>
        )}
        <ul className="divide-border mt-2 divide-y text-sm">
          {(costs.data ?? []).map((cost) => (
            <li key={cost.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <span className="min-w-0 flex-1">
                <span className="block font-medium">
                  {t(`category.${cost.category as CostIn["category"]}`)}
                </span>
                <span className="text-muted block truncate text-xs">
                  <Auto>{[cost.description, cost.vendor].filter(Boolean).join(" · ")}</Auto>
                  {cost.source === "document" && (
                    <span className="ms-2">{t("costs.fromDocument")}</span>
                  )}
                </span>
              </span>
              {cost.status === "estimate" && (
                <span className="pill pill-warning">{t("costs.estimate")}</span>
              )}
              <span className="text-end">
                <Ltr className="block">{formatMoney(cost.amount)}</Ltr>
                {cost.amount.currency !== cost.amount_tenant.currency && (
                  <span className="text-muted block text-xs">
                    {t("costs.converted")} <Ltr>{formatMoney(cost.amount_tenant)}</Ltr>
                  </span>
                )}
              </span>
              {canEdit && (
                <button
                  type="button"
                  className="btn btn-quiet text-danger"
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(cost.id)}
                >
                  {t("costs.delete")}
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      {canEdit && (
        <>
          <ReadInvoice vehicleId={vehicleId} homeCurrency={home} />
          <AddCost vehicleId={vehicleId} homeCurrency={home} />
        </>
      )}
    </div>
  );
}

function AcquisitionForm({ vehicleId, canEdit }: { vehicleId: string; canEdit: boolean }) {
  const t = useT();
  const acquisition = useAcquisition(vehicleId, true);
  const save = useSaveAcquisition(vehicleId);
  const known = acquisition.data;

  if (!acquisition.isSuccess) return null;
  if (!canEdit) {
    return (
      <section>
        <h2 className="text-sm font-semibold">{t("acquisition.title")}</h2>
        {known ? (
          <p className="mt-1 text-sm">
            {t(`source.${known.source}`)}
            {known.seller && (
              <>
                {" · "}
                <Auto>{known.seller}</Auto>
              </>
            )}
            {known.reference && (
              <>
                {" · "}
                <Ltr>{known.reference}</Ltr>
              </>
            )}
            {" · "}
            <Ltr>{known.purchased_at}</Ltr>
          </p>
        ) : (
          <p className="text-muted mt-1 text-sm">{t("acquisition.none")}</p>
        )}
      </section>
    );
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim() || null;
    save.mutate({
      source: form.get("source") as Acquisition["source"],
      seller: text("seller"),
      reference: text("reference"),
      purchased_at: String(form.get("purchased_at")),
      notes: text("notes"),
    });
  };

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("acquisition.title")}</h2>
      {/* Keyed on what was loaded, so the fields start from it rather than from
          whatever they held before the query answered. */}
      <form
        key={known?.updated_at ?? "new"}
        onSubmit={submit}
        className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2"
      >
        <label className="text-xs">
          <span className="text-muted">{t("acquisition.source")}</span>
          <select name="source" defaultValue={known?.source ?? "auction"} className="field mt-1 w-full px-3">
            {SOURCES.map((source) => (
              <option key={source} value={source}>
                {t(`source.${source}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("acquisition.date")}</span>
          <input
            type="date"
            name="purchased_at"
            required
            defaultValue={known?.purchased_at ?? ""}
            className="field mt-1 w-full"
          />
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("acquisition.seller")}</span>
          <input
            name="seller"
            maxLength={200}
            defaultValue={known?.seller ?? ""}
            className="field mt-1 w-full"
          />
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("acquisition.reference")}</span>
          <input
            name="reference"
            maxLength={120}
            dir="ltr"
            defaultValue={known?.reference ?? ""}
            className="field mt-1 w-full"
          />
        </label>
        <label className="text-xs sm:col-span-2">
          <span className="text-muted">{t("acquisition.notes")}</span>
          <textarea
            name="notes"
            maxLength={2000}
            rows={2}
            defaultValue={known?.notes ?? ""}
            className="field mt-1 w-full"
          />
        </label>
        <div className="flex items-center gap-3 sm:col-span-2">
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {t("common.save")}
          </button>
          {save.isSuccess && <span className="text-muted text-xs">{t("acquisition.saved")}</span>}
          {save.isError && <span className="text-danger text-xs">{save.error.message}</span>}
        </div>
      </form>
    </section>
  );
}

function AddCost({ vehicleId, homeCurrency }: { vehicleId: string; homeCurrency: string }) {
  const t = useT();
  const add = useAddCosts(vehicleId);
  const [currency, setCurrency] = useState(homeCurrency);
  const [problem, setProblem] = useState<string | null>(null);
  const foreign = currency.toUpperCase() !== homeCurrency;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const amount = parseMajor(String(form.get("amount") ?? ""), currency);
    if (amount === null) return setProblem(t("costs.badAmount"));
    const rate = String(form.get("fx_rate") ?? "").trim();
    if (foreign && !rate) return setProblem(t("costs.needRate"));
    setProblem(null);
    add.mutate(
      [
        {
          category: form.get("category") as CostIn["category"],
          description: String(form.get("description") ?? "").trim() || null,
          vendor: String(form.get("vendor") ?? "").trim() || null,
          amount_minor: amount,
          currency: currency.toUpperCase(),
          fx_rate: foreign ? rate : null,
          incurred_at: String(form.get("incurred_at")),
          status: form.get("estimate") ? "estimate" : "actual",
          source: "manual",
          document_path: null,
        },
      ],
      { onSuccess: () => formElement.reset() },
    );
  };

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("costs.add")}</h2>
      <form onSubmit={submit} className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <label className="text-xs">
          <span className="text-muted">{t("costs.category")}</span>
          <select name="category" className="field mt-1 w-full px-3">
            {CATEGORIES.map((category) => (
              <option key={category} value={category}>
                {t(`category.${category}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("costs.amount")}</span>
          <input name="amount" inputMode="decimal" dir="ltr" required className="field mt-1 w-full" />
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("costs.currency")}</span>
          <input
            value={currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase().slice(0, 3))}
            dir="ltr"
            required
            minLength={3}
            maxLength={3}
            className="field mt-1 w-full uppercase"
          />
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("costs.date")}</span>
          <input type="date" name="incurred_at" required className="field mt-1 w-full" />
        </label>
        {foreign && (
          <label className="col-span-2 text-xs sm:col-span-4">
            <span className="text-muted">
              {t("costs.rate")} ({currency} → {homeCurrency})
            </span>
            <input name="fx_rate" inputMode="decimal" dir="ltr" className="field mt-1 w-full" />
            <span className="text-muted mt-1 block">{t("costs.rateHint")}</span>
          </label>
        )}
        <label className="col-span-2 text-xs">
          <span className="text-muted">{t("costs.description")}</span>
          <input name="description" maxLength={300} className="field mt-1 w-full" />
        </label>
        <label className="col-span-2 text-xs">
          <span className="text-muted">{t("costs.vendor")}</span>
          <input name="vendor" maxLength={200} className="field mt-1 w-full" />
        </label>
        <label className="col-span-2 flex items-center gap-2 text-xs">
          <input type="checkbox" name="estimate" />
          {t("costs.estimate")}
        </label>
        <div className="col-span-2 flex items-center justify-end gap-3 sm:col-span-4">
          {(problem ?? add.error?.message) && (
            <span className="text-danger text-xs">{problem ?? add.error?.message}</span>
          )}
          <button type="submit" className="btn btn-primary" disabled={add.isPending}>
            {t("costs.add")}
          </button>
        </div>
      </form>
    </section>
  );
}
