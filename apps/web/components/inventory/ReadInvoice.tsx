"use client";

import { useState, type FormEvent } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import { useAddCosts, useReadInvoice, type CostIn, type Extraction } from "@/lib/api/hooks";
import { asTyped, formatMoney, parseMajor } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { CATEGORIES } from "./BuySide";

type Draft = { category: CostIn["category"]; description: string; amount: string; quote: string };

/**
 * Upload a purchase document, see what it says, correct it, record it.
 *
 * Nothing is written by reading. The proposal is the person's to edit — every
 * line keeps the text it was read from beside it, so checking a figure is a
 * glance rather than a hunt through the photo — and only "Record" writes.
 */
export function ReadInvoice({
  vehicleId,
  homeCurrency,
}: {
  vehicleId: string;
  homeCurrency: string;
}) {
  const t = useT();
  const read = useReadInvoice(vehicleId);
  const record = useAddCosts(vehicleId);
  const [proposal, setProposal] = useState<Extraction | null>(null);
  const [lines, setLines] = useState<Draft[]>([]);
  const [rate, setRate] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const start = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) return;
    const note = String(form.get("note") ?? "").trim() || undefined;
    read.mutate(
      { file, note },
      {
        onSuccess: (result) => {
          setProposal(result);
          setRate(result.fx_rate ?? "");
          setProblem(null);
          setLines(
            result.lines.map((line) => ({
              category: line.category as CostIn["category"],
              description: line.description,
              amount: asTyped(line.amount_minor, line.currency),
              quote: line.quote,
            })),
          );
        },
      },
    );
  };

  const discard = () => {
    setProposal(null);
    setLines([]);
    setRate("");
    setProblem(null);
  };

  const edit = (index: number, change: Partial<Draft>) =>
    setLines((before) => before.map((line, i) => (i === index ? { ...line, ...change } : line)));

  const confirm = () => {
    if (!proposal) return;
    const currency = proposal.currency;
    const foreign = currency !== homeCurrency;
    if (foreign && !rate.trim()) return setProblem(t("costs.needRate"));
    const parsed = lines.map((line) => parseMajor(line.amount, currency));
    if (parsed.some((amount) => amount === null)) return setProblem(t("costs.badAmount"));
    setProblem(null);
    record.mutate(
      lines.map((line, i) => ({
        category: line.category,
        description: line.description || null,
        vendor: proposal.vendor,
        amount_minor: parsed[i] as number,
        currency,
        fx_rate: foreign ? rate.trim() : null,
        incurred_at: proposal.incurred_at ?? new Date().toISOString().slice(0, 10),
        status: "actual",
        source: "document",
        document_path: proposal.document_path,
      })),
      { onSuccess: discard },
    );
  };

  if (!proposal) {
    return (
      <section>
        <h2 className="text-sm font-semibold">{t("invoice.read")}</h2>
        <p className="text-muted mt-1 text-xs">{t("invoice.hint")}</p>
        <form onSubmit={start} className="mt-2 flex flex-wrap items-end gap-2">
          <input
            type="file"
            name="file"
            required
            accept="image/jpeg,image/png,image/webp,application/pdf"
            aria-label={t("invoice.read")}
            className="field flex-1"
          />
          <input
            name="note"
            maxLength={300}
            placeholder={t("invoice.note")}
            aria-label={t("invoice.note")}
            className="field flex-1"
          />
          <button type="submit" className="btn btn-primary" disabled={read.isPending}>
            {read.isPending ? t("invoice.reading") : t("invoice.read")}
          </button>
        </form>
        {read.isError && <p className="text-danger mt-1 text-xs">{read.error.message}</p>}
      </section>
    );
  }

  const parsed = lines.map((line) => parseMajor(line.amount, proposal.currency));
  const sum = parsed.reduce<number>((total, amount) => total + (amount ?? 0), 0);
  const adds_up = proposal.total_minor == null || Math.abs(sum - proposal.total_minor) <= lines.length;

  return (
    <section className="bg-surface rounded-2xl p-4">
      <h2 className="text-sm font-semibold">{t("invoice.proposal")}</h2>
      <p className="text-muted mt-1 text-xs">
        {proposal.vendor && (
          <>
            {t("invoice.from")} <Auto>{proposal.vendor}</Auto>
          </>
        )}
        {proposal.reference && (
          <>
            {" · "}
            <Ltr>{proposal.reference}</Ltr>
          </>
        )}
        {proposal.incurred_at && (
          <>
            {" · "}
            <Ltr>{proposal.incurred_at}</Ltr>
          </>
        )}
      </p>

      {proposal.warnings.length > 0 && (
        <div className="bg-danger-soft text-danger mt-3 rounded-md p-2 text-xs" role="alert">
          <p className="font-medium">{t("invoice.check")}</p>
          <ul className="mt-1 list-disc ps-4">
            {proposal.warnings.map((warning) => (
              <li key={warning} dir="auto">
                {warning}
              </li>
            ))}
          </ul>
        </div>
      )}

      {lines.length === 0 ? (
        <p className="text-muted mt-3 text-sm">{t("invoice.noLines")}</p>
      ) : (
        <ul className="divide-border mt-3 divide-y">
          {lines.map((line, i) => (
            <li key={i} className="grid grid-cols-1 gap-2 py-2 sm:grid-cols-[10rem_1fr_9rem]">
              <select
                value={line.category}
                aria-label={t("costs.category")}
                onChange={(event) =>
                  edit(i, { category: event.target.value as CostIn["category"] })
                }
                className="field px-3"
              >
                {CATEGORIES.map((category) => (
                  <option key={category} value={category}>
                    {t(`category.${category}`)}
                  </option>
                ))}
              </select>
              <input
                value={line.description}
                aria-label={t("costs.description")}
                onChange={(event) => edit(i, { description: event.target.value })}
                className="field"
              />
              <input
                value={line.amount}
                aria-label={t("costs.amount")}
                inputMode="decimal"
                dir="ltr"
                onChange={(event) => edit(i, { amount: event.target.value })}
                className={`field text-end ${parsed[i] === null ? "border-danger" : ""}`}
              />
              <p className="text-muted text-xs sm:col-span-3">
                {t("invoice.quote")} <Auto>{line.quote}</Auto>
              </p>
            </li>
          ))}
        </ul>
      )}

      <p className={`mt-2 text-xs ${adds_up ? "text-muted" : "text-danger"}`}>
        {t("invoice.linesTotal")}{" "}
        <Ltr>{formatMoney({ amount_minor: sum, currency: proposal.currency })}</Ltr>
        {proposal.total_minor != null && (
          <>
            {" · "}
            {t("invoice.total")}{" "}
            <Ltr>{formatMoney({ amount_minor: proposal.total_minor, currency: proposal.currency })}</Ltr>
          </>
        )}
      </p>

      {proposal.currency !== homeCurrency && (
        <label className="mt-3 block text-xs">
          <span className="text-muted">
            {t("costs.rate")} ({proposal.currency} → {homeCurrency})
          </span>
          <input
            value={rate}
            onChange={(event) => setRate(event.target.value)}
            inputMode="decimal"
            dir="ltr"
            className="field mt-1 w-full"
          />
          {proposal.needs_fx_rate && (
            <span className="text-muted mt-1 block">{t("invoice.needsRate")}</span>
          )}
        </label>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {(problem ?? record.error?.message) && (
          <span className="text-danger text-xs">{problem ?? record.error?.message}</span>
        )}
        <button type="button" className="btn" onClick={discard}>
          {t("invoice.discard")}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={record.isPending || lines.length === 0}
          onClick={confirm}
        >
          {t("invoice.confirm")}
        </button>
      </div>
    </section>
  );
}
