"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import { StatTile } from "@/components/manager/StatTile";
import {
  useAddReconItems,
  useFinishReconItem,
  useMarkReady,
  useRecon,
  useReconStep,
  useSaveRecon,
  useUpdateReconItem,
  type Recon as ReconRecord,
  type ReconItem,
  type ReconItemIn,
} from "@/lib/api/hooks";
import { asTyped, formatMoney, parseMajor } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { Inspect } from "./Inspect";

export const AREAS: readonly ReconItemIn["area"][] = [
  "exterior",
  "interior",
  "mechanical",
  "tyres_wheels",
  "glass",
  "electrical",
  "other",
];

export const OPERATIONS: readonly ReconItemIn["operation"][] = [
  "paint_panel",
  "dent_repair",
  "scratch_polish",
  "replace_part",
  "tyre",
  "windscreen",
  "wheel_refurb",
  "interior_clean",
  "upholstery",
  "mechanical",
  "service",
  "detailing",
  "other",
];

export type Step = "estimate" | "commit" | "finish" | "decline" | "withdraw";

/**
 * What a person can do with an item next. The API enforces the same moves;
 * this keeps the screen from offering one that can only come back refused.
 */
export function stepsFor(item: Pick<ReconItem, "status" | "estimate">): Step[] {
  switch (item.status) {
    case "proposed":
      return item.estimate ? ["commit", "estimate", "decline"] : ["estimate", "decline"];
    case "awaiting_approval":
      return ["withdraw"];
    case "approved":
      return ["finish", "decline"];
    default:
      return [];
  }
}

const PILL: Record<ReconItem["status"], string> = {
  proposed: "pill",
  awaiting_approval: "pill pill-warning",
  approved: "pill pill-info",
  done: "pill pill-accent",
  declined: "pill text-muted",
};

/**
 * Getting the car ready to sell, inside a budget (docs/lifecycle/README.md
 * § L3). Only mounted for someone with costs.view — an estimate is what the
 * dealer will pay.
 */
export function Recon({
  vehicleId,
  canRun,
  canSetBudget,
}: {
  vehicleId: string;
  canRun: boolean;
  canSetBudget: boolean;
}) {
  const t = useT();
  const recon = useRecon(vehicleId, true);
  const record = recon.data;
  if (!record) return <p className="text-muted text-sm">…</p>;

  const open = record.items.filter(
    (item) => item.status === "approved" || item.status === "awaiting_approval",
  ).length;

  return (
    <div className="space-y-6">
      <section>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatTile
            label={t("recon.budget")}
            value={record.budget ? formatMoney(record.budget) : "—"}
          />
          <StatTile
            label={t("recon.committed")}
            value={formatMoney(record.committed)}
            tone={record.over_budget ? "bad" : null}
            hint={record.over_budget ? t("recon.overBudget") : undefined}
          />
          <StatTile label={t("recon.spent")} value={formatMoney(record.spent)} />
          <StatTile
            label={t("recon.remaining")}
            value={record.remaining ? formatMoney(record.remaining) : "—"}
            tone={record.remaining && record.remaining.amount_minor < 0 ? "bad" : null}
          />
        </div>
        {!record.budget && <p className="text-muted mt-2 text-xs">{t("recon.noBudget")}</p>}
      </section>

      <RecordForm vehicleId={vehicleId} record={record} canRun={canRun} canSetBudget={canSetBudget} />

      <section>
        <h2 className="text-sm font-semibold">{t("recon.items")}</h2>
        {record.items.length === 0 && (
          <p className="text-muted mt-2 text-sm">{t("recon.empty")}</p>
        )}
        <ul className="divide-border mt-2 divide-y text-sm">
          {record.items.map((item) => (
            <ItemRow
              key={item.id}
              vehicleId={vehicleId}
              item={item}
              currency={record.currency}
              canRun={canRun}
            />
          ))}
        </ul>
      </section>

      {canRun && (
        <>
          <Ready vehicleId={vehicleId} record={record} open={open} />
          <Inspect vehicleId={vehicleId} currency={record.currency} />
          <AddItem vehicleId={vehicleId} currency={record.currency} />
        </>
      )}
    </div>
  );
}

function RecordForm({
  vehicleId,
  record,
  canRun,
  canSetBudget,
}: {
  vehicleId: string;
  record: ReconRecord;
  canRun: boolean;
  canSetBudget: boolean;
}) {
  const t = useT();
  const save = useSaveRecon(vehicleId);
  const [problem, setProblem] = useState<string | null>(null);
  if (!canRun) return null;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body: Parameters<typeof save.mutate>[0] = {
      ready_by: String(form.get("ready_by") ?? "") || null,
      notes: String(form.get("notes") ?? "").trim() || null,
    };
    if (canSetBudget) {
      const typed = String(form.get("budget") ?? "").trim();
      const budget = typed ? parseMajor(typed, record.currency) : null;
      if (typed && budget === null) return setProblem(t("costs.badAmount"));
      body.budget_minor = budget;
    }
    setProblem(null);
    save.mutate(body);
  };

  return (
    <section>
      <form
        key={`${record.budget?.amount_minor}-${record.ready_by}`}
        onSubmit={submit}
        className="grid grid-cols-1 gap-2 sm:grid-cols-3"
      >
        {canSetBudget && (
          <label className="text-xs">
            <span className="text-muted">
              {t("recon.budget")} ({record.currency})
            </span>
            <input
              name="budget"
              inputMode="decimal"
              dir="ltr"
              defaultValue={record.budget ? asTyped(record.budget.amount_minor, record.currency) : ""}
              className="field mt-1 w-full"
            />
          </label>
        )}
        <label className="text-xs">
          <span className="text-muted">{t("recon.readyBy")}</span>
          <input
            type="date"
            name="ready_by"
            defaultValue={record.ready_by ?? ""}
            className="field mt-1 w-full"
          />
        </label>
        <label className="text-xs sm:col-span-3">
          <span className="text-muted">{t("acquisition.notes")}</span>
          <textarea
            name="notes"
            rows={2}
            maxLength={2000}
            defaultValue={record.notes ?? ""}
            className="field mt-1 w-full"
          />
        </label>
        <div className="flex items-center gap-3 sm:col-span-3">
          <button type="submit" className="btn btn-primary" disabled={save.isPending}>
            {t("common.save")}
          </button>
          {(problem ?? save.error?.message) && (
            <span className="text-danger text-xs">{problem ?? save.error?.message}</span>
          )}
        </div>
      </form>
    </section>
  );
}

function ItemRow({
  vehicleId,
  item,
  currency,
  canRun,
}: {
  vehicleId: string;
  item: ReconItem;
  currency: string;
  canRun: boolean;
}) {
  const t = useT();
  const { tenant } = useParams<{ tenant: string }>();
  const commit = useReconStep(vehicleId, "commit");
  const decline = useReconStep(vehicleId, "decline");
  const finish = useFinishReconItem(vehicleId);
  const update = useUpdateReconItem(vehicleId);
  const [editing, setEditing] = useState<"estimate" | "finish" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const steps = canRun ? stepsFor(item) : [];
  const failed = commit.error ?? decline.error ?? finish.error ?? update.error;

  const amountFrom = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const amount = parseMajor(String(form.get("amount") ?? ""), currency);
    if (amount === null) {
      setProblem(t("costs.badAmount"));
      return null;
    }
    setProblem(null);
    return { amount, vendor: String(form.get("vendor") ?? "").trim() || null };
  };

  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0 flex-1">
          <span className="block font-medium">
            <Auto>{item.description}</Auto>
          </span>
          <span className="text-muted block text-xs">
            {t(`reconArea.${item.area as ReconItemIn["area"]}`)} ·{" "}
            {t(`reconOperation.${item.operation as ReconItemIn["operation"]}`)}
            {item.quantity > 1 && <> × {item.quantity}</>}
            {item.vendor && (
              <>
                {" · "}
                <Auto>{item.vendor}</Auto>
              </>
            )}
            {item.source === "photo" && <span className="ms-2">{t("recon.fromPhoto")}</span>}
          </span>
        </span>
        {item.severity && (
          <span className={item.severity === "major" ? "pill pill-danger" : "pill"}>
            {t(`reconSeverity.${item.severity as NonNullable<ReconItemIn["severity"]>}`)}
          </span>
        )}
        <span className={PILL[item.status]}>{t(`reconStatus.${item.status}`)}</span>
        <span className="text-end">
          {item.actual ? (
            <>
              <Ltr className="block">{formatMoney(item.actual)}</Ltr>
              {item.estimate && item.estimate.amount_minor !== item.actual.amount_minor && (
                <span className="text-muted block text-xs">
                  {t("recon.estimated")} <Ltr>{formatMoney(item.estimate)}</Ltr>
                </span>
              )}
            </>
          ) : item.estimate ? (
            <Ltr className="block">{formatMoney(item.estimate)}</Ltr>
          ) : (
            <span className="text-muted text-xs">{t("recon.noEstimate")}</span>
          )}
        </span>
      </div>

      {steps.length > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {steps.includes("commit") && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={commit.isPending}
              onClick={() => commit.mutate(item.id)}
            >
              {t("recon.commit")}
            </button>
          )}
          {steps.includes("estimate") && (
            <button type="button" className="btn" onClick={() => setEditing("estimate")}>
              {t("recon.setEstimate")}
            </button>
          )}
          {steps.includes("finish") && (
            <button type="button" className="btn btn-primary" onClick={() => setEditing("finish")}>
              {t("recon.finish")}
            </button>
          )}
          {steps.includes("withdraw") && (
            <>
              <Link href={`/${tenant}/approvals`} className="text-xs underline">
                {t("pricing.openApprovals")}
              </Link>
              <button
                type="button"
                className="btn btn-quiet"
                disabled={decline.isPending}
                onClick={() => decline.mutate(item.id)}
              >
                {t("recon.withdraw")}
              </button>
            </>
          )}
          {steps.includes("decline") && (
            <button
              type="button"
              className="btn btn-quiet text-danger"
              disabled={decline.isPending}
              onClick={() => decline.mutate(item.id)}
            >
              {t("recon.decline")}
            </button>
          )}
        </div>
      )}

      {editing === "estimate" && (
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            const typed = amountFrom(event);
            if (typed)
              update.mutate(
                { itemId: item.id, estimate_minor: typed.amount },
                { onSuccess: () => setEditing(null) },
              );
          }}
        >
          <label className="text-xs">
            <span className="text-muted">
              {t("recon.estimate")} ({currency})
            </span>
            <input
              name="amount"
              inputMode="decimal"
              dir="ltr"
              required
              defaultValue={item.estimate ? asTyped(item.estimate.amount_minor, currency) : ""}
              className="field mt-1 w-32"
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={update.isPending}>
            {t("common.save")}
          </button>
        </form>
      )}

      {editing === "finish" && (
        <form
          className="mt-2 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            const typed = amountFrom(event);
            if (typed)
              finish.mutate(
                { itemId: item.id, actual_minor: typed.amount, vendor: typed.vendor },
                { onSuccess: () => setEditing(null) },
              );
          }}
        >
          <label className="text-xs">
            <span className="text-muted">
              {t("recon.actual")} ({currency})
            </span>
            <input
              name="amount"
              inputMode="decimal"
              dir="ltr"
              required
              defaultValue={item.estimate ? asTyped(item.estimate.amount_minor, currency) : ""}
              className="field mt-1 w-32"
            />
          </label>
          <label className="text-xs">
            <span className="text-muted">{t("costs.vendor")}</span>
            <input
              name="vendor"
              maxLength={200}
              defaultValue={item.vendor ?? ""}
              className="field mt-1 w-48"
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={finish.isPending}>
            {t("recon.finish")}
          </button>
        </form>
      )}

      {(problem ?? failed?.message) && (
        <p className="text-danger mt-1 text-xs">{problem ?? failed?.message}</p>
      )}
    </li>
  );
}

function Ready({ vehicleId, record, open }: { vehicleId: string; record: ReconRecord; open: number }) {
  const t = useT();
  const ready = useMarkReady(vehicleId);
  return (
    <section className="bg-surface rounded-2xl p-4">
      <h2 className="text-sm font-semibold">{t("recon.ready")}</h2>
      {record.ready_at ? (
        <p className="mt-1 text-sm">
          {t("recon.readySince")} <Ltr>{record.ready_at.slice(0, 10)}</Ltr>
          {record.days != null && (
            <span className="text-muted">
              {" · "}
              {record.days} {t("inventory.daysUnit")}
            </span>
          )}
        </p>
      ) : (
        <>
          <p className="text-muted mt-1 text-xs">
            {open > 0 ? t("recon.workInHand") : t("recon.readyHint")}
            {record.overdue && <span className="pill pill-danger ms-2">{t("recon.overdue")}</span>}
          </p>
          <button
            type="button"
            className="btn btn-primary mt-2"
            disabled={open > 0 || ready.isPending}
            onClick={() => ready.mutate()}
          >
            {t("recon.markReady")}
          </button>
          {ready.isError && <p className="text-danger mt-1 text-xs">{ready.error.message}</p>}
        </>
      )}
    </section>
  );
}

function AddItem({ vehicleId, currency }: { vehicleId: string; currency: string }) {
  const t = useT();
  const add = useAddReconItems(vehicleId);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const typed = String(form.get("estimate") ?? "").trim();
    const estimate = typed ? parseMajor(typed, currency) : null;
    if (typed && estimate === null) return setProblem(t("costs.badAmount"));
    setProblem(null);
    add.mutate(
      [
        {
          area: form.get("area") as ReconItemIn["area"],
          operation: form.get("operation") as ReconItemIn["operation"],
          quantity: Number(form.get("quantity") || 1),
          description: String(form.get("description")).trim(),
          vendor: String(form.get("vendor") ?? "").trim() || null,
          estimate_minor: estimate,
          source: "manual",
          photo_path: null,
        },
      ],
      { onSuccess: () => formElement.reset() },
    );
  };

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("recon.add")}</h2>
      <form onSubmit={submit} className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <label className="text-xs">
          <span className="text-muted">{t("recon.area")}</span>
          <select name="area" className="field mt-1 w-full px-3">
            {AREAS.map((area) => (
              <option key={area} value={area}>
                {t(`reconArea.${area}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("recon.operation")}</span>
          <select name="operation" className="field mt-1 w-full px-3">
            {OPERATIONS.map((operation) => (
              <option key={operation} value={operation}>
                {t(`reconOperation.${operation}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("recon.quantity")}</span>
          <input
            name="quantity"
            type="number"
            min={1}
            max={50}
            defaultValue={1}
            dir="ltr"
            className="field mt-1 w-full"
          />
        </label>
        <label className="text-xs">
          <span className="text-muted">
            {t("recon.estimate")} ({currency})
          </span>
          <input name="estimate" inputMode="decimal" dir="ltr" className="field mt-1 w-full" />
        </label>
        <label className="col-span-2 text-xs">
          <span className="text-muted">{t("costs.description")}</span>
          <input name="description" required maxLength={300} className="field mt-1 w-full" />
        </label>
        <label className="col-span-2 text-xs">
          <span className="text-muted">{t("costs.vendor")}</span>
          <input name="vendor" maxLength={200} className="field mt-1 w-full" />
        </label>
        <div className="col-span-2 flex items-center justify-end gap-3 sm:col-span-4">
          {(problem ?? add.error?.message) && (
            <span className="text-danger text-xs">{problem ?? add.error?.message}</span>
          )}
          <button type="submit" className="btn btn-primary" disabled={add.isPending}>
            {t("recon.add")}
          </button>
        </div>
      </form>
    </section>
  );
}
