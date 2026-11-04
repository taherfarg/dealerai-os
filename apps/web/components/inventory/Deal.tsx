"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import {
  useCreateOrder,
  useFinishOrder,
  useOrders,
  useReadReceipt,
  useRecordPayment,
  type Order,
  type OrderIn,
  type PaymentIn,
  type Receipt,
} from "@/lib/api/hooks";
import { asTyped, exponentOf, formatMoney, parseMajor, type Money } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

type Stage = PaymentIn["stage"];
type ChargeKind = OrderIn["charges"] extends (infer C)[] | undefined
  ? C extends { kind: infer K }
    ? K
    : never
  : never;

const STAGES: readonly Stage[] = ["deposit", "balance", "logistics"];
const CHARGE_KINDS: readonly ChargeKind[] = ["fee", "freight", "duties", "other"];
const METHODS: readonly PaymentIn["method"][] = ["bank_transfer", "cash", "card", "other"];

/** A deposit to suggest: a tenth of the price, to the nearest thousand. The person changes it. */
export function suggestedDeposit(price: Money): number {
  const thousand = 1000 * 10 ** exponentOf(price.currency);
  return Math.round(price.amount_minor / 10 / thousand) * thousand;
}

/** What a read receipt puts in the payment form. Nothing the receipt did not say is filled. */
export function paymentFromReceipt(receipt: Receipt) {
  return {
    stage: (receipt.stage ?? "deposit") as Stage,
    amount: receipt.amount ? asTyped(receipt.amount.amount_minor, receipt.amount.currency) : "",
    currency: receipt.amount?.currency ?? "",
    fx_rate: receipt.fx_rate ?? "",
    received_on: receipt.paid_on ?? "",
    reference: receipt.reference ?? "",
    document_path: receipt.document_path ?? null,
  };
}

const PILL: Record<string, string> = {
  quoted: "pill",
  reserved: "pill pill-warning",
  completed: "pill pill-accent",
  cancelled: "pill text-muted",
};

/**
 * The deal desk for one car (docs/lifecycle/README.md § L6): its orders, the
 * invoice each is priced on, the stages a buyer pays it in, and the payments
 * that reserve and then sell it.
 */
export function Deal({
  vehicleId,
  listPrice,
  canQuote,
  canTakePayment,
}: {
  vehicleId: string;
  listPrice: Money | null | undefined;
  canQuote: boolean;
  canTakePayment: boolean;
}) {
  const t = useT();
  const orders = useOrders(vehicleId);
  const [quoting, setQuoting] = useState(false);
  if (!orders.data) return <p className="text-muted text-sm">…</p>;

  return (
    <div className="space-y-6">
      {orders.data.length === 0 && !quoting && (
        <p className="text-muted text-sm">{t("deal.none")}</p>
      )}
      {orders.data.map((order) => (
        <OrderCard
          key={order.id}
          vehicleId={vehicleId}
          order={order}
          canQuote={canQuote}
          canTakePayment={canTakePayment}
        />
      ))}
      {canQuote &&
        (quoting ? (
          <QuoteForm vehicleId={vehicleId} listPrice={listPrice} onDone={() => setQuoting(false)} />
        ) : (
          <button type="button" className="btn btn-primary" onClick={() => setQuoting(true)}>
            {t("deal.newQuote")}
          </button>
        ))}
    </div>
  );
}

function OrderCard({
  vehicleId,
  order,
  canQuote,
  canTakePayment,
}: {
  vehicleId: string;
  order: Order;
  canQuote: boolean;
  canTakePayment: boolean;
}) {
  const t = useT();
  const { tenant } = useParams<{ tenant: string }>();
  const finish = useFinishOrder(vehicleId);
  const [reason, setReason] = useState("");
  const open = order.status === "quoted" || order.status === "reserved";
  const mayCancel = order.status === "quoted" ? canQuote : order.status === "reserved" && canTakePayment;
  const paidUp = order.schedule.outstanding.amount_minor === 0;

  return (
    <section className="bg-surface rounded-2xl p-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">
          <Auto>{order.buyer_name}</Auto>
          <span className="text-muted ms-2 text-xs font-normal">
            {t(`deal.type.${order.purchase_type as "local" | "export"}`)}
            {order.destination && <> · <Ltr>{order.destination}</Ltr></>}
          </span>
        </h2>
        <span className={PILL[order.status]}>
          {t(`dealStatus.${order.status as "quoted" | "reserved" | "completed" | "cancelled"}`)}
        </span>
      </header>

      {!order.cleared && open && (
        <p className="bg-danger-soft text-danger mt-2 rounded-md p-2 text-xs" role="alert">
          {t("deal.underFloor")} {order.floor && <Ltr>{formatMoney(order.floor)}</Ltr>}.{" "}
          {t("deal.waitingApproval")}{" "}
          <Link href={`/${tenant}/approvals`} className="underline">
            {t("pricing.openApprovals")}
          </Link>
        </p>
      )}

      <table className="mt-3 w-full text-sm">
        <tbody>
          {order.charges.map((line, i) => (
            <tr key={i} className="border-border border-b">
              <td className="py-1">
                {t(`chargeKind.${line.kind as "vehicle" | ChargeKind}`)}
                {line.description && (
                  <span className="text-muted ms-2 text-xs">
                    <Auto>{line.description}</Auto>
                  </span>
                )}
              </td>
              <td className="py-1 text-end">
                <Ltr>{formatMoney(line.amount)}</Ltr>
              </td>
            </tr>
          ))}
          <tr>
            <td className="py-1 font-semibold">{t("deal.total")}</td>
            <td className="py-1 text-end font-semibold">
              <Ltr>{formatMoney(order.schedule.total)}</Ltr>
            </td>
          </tr>
        </tbody>
      </table>
      {order.margin && (
        <p className="text-muted mt-1 text-xs">
          {t("deal.margin")} <Ltr>{formatMoney(order.margin)}</Ltr>
        </p>
      )}

      <h3 className="mt-4 text-xs font-semibold">{t("deal.schedule")}</h3>
      <table className="mt-1 w-full text-xs">
        <thead className="text-muted">
          <tr>
            <th className="text-start font-normal">{t("deal.stage")}</th>
            <th className="text-end font-normal">{t("deal.due")}</th>
            <th className="text-end font-normal">{t("deal.paid")}</th>
            <th className="text-end font-normal">{t("deal.left")}</th>
          </tr>
        </thead>
        <tbody>
          {order.schedule.stages.map((row) => (
            <tr key={row.stage} className={row.stage === order.schedule.next_stage ? "font-semibold" : ""}>
              <td>{t(`paymentStage.${row.stage as Stage}`)}</td>
              <td className="text-end"><Ltr>{formatMoney(row.due)}</Ltr></td>
              <td className="text-end"><Ltr>{formatMoney(row.paid)}</Ltr></td>
              <td className="text-end"><Ltr>{formatMoney(row.left)}</Ltr></td>
            </tr>
          ))}
        </tbody>
      </table>

      {order.payments.length > 0 && (
        <ul className="divide-border mt-3 divide-y text-xs">
          {order.payments.map((payment) => (
            <li key={payment.id} className="flex flex-wrap justify-between gap-2 py-1">
              <span>
                <Ltr>{payment.received_on}</Ltr> · {t(`paymentStage.${payment.stage as Stage}`)} ·{" "}
                {t(`paymentMethod.${payment.method as PaymentIn["method"]}`)}
                {payment.reference && <> · <Ltr>{payment.reference}</Ltr></>}
              </span>
              <span>
                <Ltr>{formatMoney(payment.amount)}</Ltr>
                {payment.amount.currency !== payment.amount_tenant.currency && (
                  <span className="text-muted ms-1">
                    (<Ltr>{formatMoney(payment.amount_tenant)}</Ltr>)
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {canTakePayment && open && order.cleared && (
        // Keyed on the payments so far: after each one the form starts again
        // at the next stage owed.
        <PaymentForm key={order.payments.length} vehicleId={vehicleId} order={order} />
      )}

      {open && (canTakePayment || mayCancel) && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {canTakePayment && order.status === "reserved" && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={!paidUp || finish.isPending}
              onClick={() => finish.mutate({ orderId: order.id })}
            >
              {t("deal.complete")}
            </button>
          )}
          {mayCancel && (
            <>
              <input
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={500}
                placeholder={t("deal.cancelReason")}
                aria-label={t("deal.cancelReason")}
                className="field flex-1"
              />
              <button
                type="button"
                className="btn btn-quiet text-danger"
                disabled={!reason.trim() || finish.isPending}
                onClick={() => finish.mutate({ orderId: order.id, cancel: reason.trim() })}
              >
                {t("deal.cancel")}
              </button>
            </>
          )}
          {finish.isError && <span className="text-danger text-xs">{finish.error.message}</span>}
        </div>
      )}
    </section>
  );
}

type ChargeDraft = { kind: ChargeKind; description: string; amount: string };

function QuoteForm({
  vehicleId,
  listPrice,
  onDone,
}: {
  vehicleId: string;
  listPrice: Money | null | undefined;
  onDone: () => void;
}) {
  const t = useT();
  const create = useCreateOrder(vehicleId);
  const currency = listPrice?.currency ?? "AED";
  const [type, setType] = useState<"local" | "export">("export");
  const [charges, setCharges] = useState<ChargeDraft[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const price = parseMajor(String(form.get("price") ?? ""), currency);
    const deposit = parseMajor(String(form.get("deposit") ?? ""), currency);
    const lines = charges.map((c) => ({ ...c, minor: parseMajor(c.amount, currency) }));
    if (price === null || deposit === null || lines.some((l) => l.minor === null))
      return setProblem(t("costs.badAmount"));
    setProblem(null);
    create.mutate(
      {
        buyer_name: String(form.get("buyer")).trim(),
        purchase_type: type,
        destination: type === "export" ? String(form.get("destination") ?? "").trim() || null : null,
        price_minor: price,
        deposit_minor: deposit,
        charges: lines.map((l) => ({
          kind: l.kind,
          description: l.description.trim() || null,
          amount_minor: l.minor as number,
        })),
      },
      { onSuccess: onDone },
    );
  };

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("deal.newQuote")}</h2>
      <form onSubmit={submit} className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="text-xs sm:col-span-2">
          <span className="text-muted">{t("deal.buyer")}</span>
          <input name="buyer" required maxLength={200} className="field mt-1 w-full" />
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("deal.purchaseType")}</span>
          <select
            value={type}
            onChange={(event) => setType(event.target.value as "local" | "export")}
            className="field mt-1 w-full px-3"
          >
            <option value="export">{t("deal.type.export")}</option>
            <option value="local">{t("deal.type.local")}</option>
          </select>
        </label>
        {type === "export" && (
          <label className="text-xs">
            <span className="text-muted">{t("deal.destination")}</span>
            <input
              name="destination"
              required
              minLength={2}
              maxLength={2}
              dir="ltr"
              placeholder="DZ"
              className="field mt-1 w-full uppercase"
            />
          </label>
        )}
        <label className="text-xs">
          <span className="text-muted">
            {t("deal.price")} ({currency})
          </span>
          <input
            name="price"
            inputMode="decimal"
            dir="ltr"
            required
            defaultValue={listPrice ? asTyped(listPrice.amount_minor, currency) : ""}
            className="field mt-1 w-full"
          />
        </label>
        <label className="text-xs">
          <span className="text-muted">
            {t("deal.deposit")} ({currency})
          </span>
          <input
            name="deposit"
            inputMode="decimal"
            dir="ltr"
            required
            defaultValue={listPrice ? asTyped(suggestedDeposit(listPrice), currency) : ""}
            className="field mt-1 w-full"
          />
        </label>

        <fieldset className="sm:col-span-2">
          <legend className="text-xs font-medium">{t("deal.charges")}</legend>
          {charges.map((charge, i) => (
            <div key={i} className="mt-1 grid grid-cols-[8rem_1fr_8rem_auto] gap-2">
              <select
                value={charge.kind}
                aria-label={t("deal.chargeKind")}
                onChange={(event) =>
                  setCharges(charges.map((c, j) => (j === i ? { ...c, kind: event.target.value as ChargeKind } : c)))
                }
                className="field px-2"
              >
                {CHARGE_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {t(`chargeKind.${kind}`)}
                  </option>
                ))}
              </select>
              <input
                value={charge.description}
                aria-label={t("costs.description")}
                onChange={(event) =>
                  setCharges(charges.map((c, j) => (j === i ? { ...c, description: event.target.value } : c)))
                }
                className="field"
              />
              <input
                value={charge.amount}
                aria-label={t("costs.amount")}
                inputMode="decimal"
                dir="ltr"
                onChange={(event) =>
                  setCharges(charges.map((c, j) => (j === i ? { ...c, amount: event.target.value } : c)))
                }
                className="field text-end"
              />
              <button
                type="button"
                className="btn btn-quiet"
                onClick={() => setCharges(charges.filter((_, j) => j !== i))}
              >
                {t("pricingSettings.removeStep")}
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn mt-2"
            onClick={() => setCharges([...charges, { kind: "freight", description: "", amount: "" }])}
          >
            {t("deal.addCharge")}
          </button>
        </fieldset>

        <div className="flex flex-wrap items-center justify-end gap-2 sm:col-span-2">
          {(problem ?? create.error?.message) && (
            <span className="text-danger text-xs">{problem ?? create.error?.message}</span>
          )}
          <button type="button" className="btn" onClick={onDone}>
            {t("invoice.discard")}
          </button>
          <button type="submit" className="btn btn-primary" disabled={create.isPending}>
            {t("deal.saveQuote")}
          </button>
        </div>
      </form>
    </section>
  );
}

function PaymentForm({ vehicleId, order }: { vehicleId: string; order: Order }) {
  const t = useT();
  const record = useRecordPayment(vehicleId);
  const read = useReadReceipt();
  const home = order.currency;
  const blank = {
    stage: (order.schedule.next_stage ?? "deposit") as Stage,
    amount: "",
    currency: home,
    fx_rate: "",
    received_on: new Date().toISOString().slice(0, 10),
    reference: "",
    document_path: null as string | null,
  };
  const [draft, setDraft] = useState(blank);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const foreign = draft.currency.toUpperCase() !== home;
  const set = (change: Partial<typeof draft>) => setDraft({ ...draft, ...change });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const amount = parseMajor(draft.amount, draft.currency.toUpperCase());
    if (amount === null || amount === 0) return setProblem(t("costs.badAmount"));
    if (foreign && !draft.fx_rate.trim()) return setProblem(t("costs.needRate"));
    setProblem(null);
    record.mutate(
      {
        orderId: order.id,
        stage: draft.stage,
        amount_minor: amount,
        currency: draft.currency.toUpperCase(),
        fx_rate: foreign ? draft.fx_rate.trim() : null,
        received_on: draft.received_on,
        method: (new FormData(event.currentTarget).get("method") as PaymentIn["method"]) ?? "bank_transfer",
        reference: draft.reference.trim() || null,
        document_path: draft.document_path,
      },
      {
        onSuccess: () => {
          setDraft(blank);
          setWarnings([]);
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="border-border mt-4 border-t pt-3">
      <h3 className="text-xs font-semibold">{t("deal.recordPayment")}</h3>
      <label className="mt-2 block text-xs">
        <span className="text-muted">{t("deal.readReceipt")}</span>
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          className="field mt-1 w-full"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (!file) return;
            read.mutate(
              { orderId: order.id, file },
              {
                onSuccess: (receipt) => {
                  setDraft({ ...blank, ...paymentFromReceipt(receipt) });
                  setWarnings(receipt.warnings);
                },
              },
            );
          }}
        />
        {read.isPending && <span className="text-muted mt-1 block">{t("invoice.reading")}</span>}
      </label>
      {warnings.length > 0 && (
        <ul className="bg-danger-soft text-danger mt-2 list-disc rounded-md p-2 ps-6 text-xs" role="alert">
          {warnings.map((warning) => (
            <li key={warning} dir="auto">
              {warning}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <label className="text-xs">
          <span className="text-muted">{t("deal.stage")}</span>
          <select
            value={draft.stage}
            onChange={(event) => set({ stage: event.target.value as Stage })}
            className="field mt-1 w-full px-3"
          >
            {STAGES.map((stage) => (
              <option key={stage} value={stage}>
                {t(`paymentStage.${stage}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("costs.amount")}</span>
          <input
            value={draft.amount}
            onChange={(event) => set({ amount: event.target.value })}
            inputMode="decimal"
            dir="ltr"
            required
            className="field mt-1 w-full"
          />
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("costs.currency")}</span>
          <input
            value={draft.currency}
            onChange={(event) => set({ currency: event.target.value.toUpperCase().slice(0, 3) })}
            dir="ltr"
            required
            minLength={3}
            maxLength={3}
            className="field mt-1 w-full uppercase"
          />
        </label>
        <label className="text-xs">
          <span className="text-muted">{t("deal.receivedOn")}</span>
          <input
            type="date"
            value={draft.received_on}
            onChange={(event) => set({ received_on: event.target.value })}
            required
            className="field mt-1 w-full"
          />
        </label>
        {foreign && (
          <label className="col-span-2 text-xs sm:col-span-4">
            <span className="text-muted">
              {t("costs.rate")} ({draft.currency} → {home})
            </span>
            <input
              value={draft.fx_rate}
              onChange={(event) => set({ fx_rate: event.target.value })}
              inputMode="decimal"
              dir="ltr"
              className="field mt-1 w-full"
            />
          </label>
        )}
        <label className="text-xs">
          <span className="text-muted">{t("deal.method")}</span>
          <select name="method" defaultValue="bank_transfer" className="field mt-1 w-full px-3">
            {METHODS.map((method) => (
              <option key={method} value={method}>
                {t(`paymentMethod.${method}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="col-span-1 text-xs sm:col-span-3">
          <span className="text-muted">{t("deal.reference")}</span>
          <input
            value={draft.reference}
            onChange={(event) => set({ reference: event.target.value })}
            maxLength={120}
            dir="ltr"
            className="field mt-1 w-full"
          />
        </label>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
        {(problem ?? record.error?.message ?? read.error?.message) && (
          <span className="text-danger text-xs">
            {problem ?? record.error?.message ?? read.error?.message}
          </span>
        )}
        <button type="submit" className="btn btn-primary" disabled={record.isPending}>
          {t("deal.record")}
        </button>
      </div>
    </form>
  );
}
