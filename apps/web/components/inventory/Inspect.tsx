"use client";

import { useState, type FormEvent } from "react";
import { Auto } from "@/components/Bidi";
import { useAddReconItems, useInspect, type Inspection, type ReconItemIn } from "@/lib/api/hooks";
import { asTyped, parseMajor } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

type Finding = Inspection["findings"][number];
type Draft = { keep: boolean; description: string; estimate: string; finding: Finding };

const MAX_PHOTOS = 8;

/**
 * Photos of the car in, proposed work out. Nothing is written by reading:
 * every finding keeps what the model saw beside it, its estimate comes from
 * the dealer's own rates or history (or is left for a person to type), and
 * only "Add the work" writes — as proposed items, committing no money.
 */
export function Inspect({ vehicleId, currency }: { vehicleId: string; currency: string }) {
  const t = useT();
  const read = useInspect(vehicleId);
  const add = useAddReconItems(vehicleId);
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  const start = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const files = form.getAll("files").filter((f): f is File => f instanceof File && f.size > 0);
    if (files.length === 0) return;
    if (files.length > MAX_PHOTOS) return setProblem(t("inspect.tooMany"));
    setProblem(null);
    const note = String(form.get("note") ?? "").trim() || undefined;
    read.mutate(
      { files, note },
      {
        onSuccess: (result) => {
          setWarnings(result.warnings);
          setDrafts(
            result.findings.map((finding) => ({
              keep: true,
              description: finding.description,
              estimate: finding.estimate ? asTyped(finding.estimate.amount_minor, currency) : "",
              finding,
            })),
          );
        },
      },
    );
  };

  const discard = () => {
    setDrafts(null);
    setWarnings([]);
    setProblem(null);
  };

  const edit = (index: number, change: Partial<Draft>) =>
    setDrafts((before) => (before ?? []).map((d, i) => (i === index ? { ...d, ...change } : d)));

  const confirm = () => {
    const kept = (drafts ?? []).filter((d) => d.keep);
    const estimates = kept.map((d) => (d.estimate.trim() ? parseMajor(d.estimate, currency) : null));
    if (kept.some((d, i) => d.estimate.trim() && estimates[i] === null))
      return setProblem(t("costs.badAmount"));
    setProblem(null);
    add.mutate(
      kept.map((d, i) => ({
        area: d.finding.area as ReconItemIn["area"],
        operation: d.finding.operation as ReconItemIn["operation"],
        quantity: d.finding.quantity,
        description: d.description.trim() || d.finding.description,
        severity: d.finding.severity as ReconItemIn["severity"],
        estimate_minor: estimates[i],
        source: "photo",
        photo_path: d.finding.photo_path,
      })),
      { onSuccess: discard },
    );
  };

  if (!drafts) {
    return (
      <section>
        <h2 className="text-sm font-semibold">{t("inspect.title")}</h2>
        <p className="text-muted mt-1 text-xs">{t("inspect.hint")}</p>
        <form onSubmit={start} className="mt-2 flex flex-wrap items-end gap-2">
          <input
            type="file"
            name="files"
            multiple
            required
            accept="image/jpeg,image/png,image/webp"
            aria-label={t("inspect.title")}
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
            {read.isPending ? t("inspect.reading") : t("inspect.read")}
          </button>
        </form>
        {(problem ?? read.error?.message) && (
          <p className="text-danger mt-1 text-xs">{problem ?? read.error?.message}</p>
        )}
      </section>
    );
  }

  return (
    <section className="bg-surface rounded-2xl p-4">
      <h2 className="text-sm font-semibold">{t("inspect.proposal")}</h2>
      {warnings.length > 0 && (
        <ul className="bg-danger-soft text-danger mt-2 list-disc rounded-md p-2 ps-6 text-xs" role="alert">
          {warnings.map((warning) => (
            <li key={warning} dir="auto">
              {warning}
            </li>
          ))}
        </ul>
      )}
      {drafts.length === 0 ? (
        <p className="text-muted mt-3 text-sm">{t("inspect.nothing")}</p>
      ) : (
        <ul className="divide-border mt-3 divide-y">
          {drafts.map((draft, i) => (
            <li key={i} className="grid grid-cols-1 gap-2 py-2 sm:grid-cols-[auto_1fr_9rem]">
              <input
                type="checkbox"
                checked={draft.keep}
                aria-label={t("inspect.keep")}
                onChange={(event) => edit(i, { keep: event.target.checked })}
                className="mt-3"
              />
              <input
                value={draft.description}
                aria-label={t("costs.description")}
                onChange={(event) => edit(i, { description: event.target.value })}
                className="field"
              />
              <input
                value={draft.estimate}
                placeholder={t("recon.estimate")}
                aria-label={t("recon.estimate")}
                inputMode="decimal"
                dir="ltr"
                onChange={(event) => edit(i, { estimate: event.target.value })}
                className="field text-end"
              />
              <p className="text-muted text-xs sm:col-span-3">
                {t("inspect.photo")} {draft.finding.photo} ·{" "}
                {t(`reconOperation.${draft.finding.operation as ReconItemIn["operation"]}`)}
                {draft.finding.quantity > 1 && <> × {draft.finding.quantity}</>} ·{" "}
                {t(`reconSeverity.${draft.finding.severity as NonNullable<ReconItemIn["severity"]>}`)}
                {" · "}
                {draft.finding.estimate_source
                  ? t(`inspect.source.${draft.finding.estimate_source as "rate_card" | "history"}`)
                  : t("inspect.source.none")}
                <br />
                {t("inspect.seen")} <Auto>{draft.finding.seen}</Auto>
              </p>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {(problem ?? add.error?.message) && (
          <span className="text-danger text-xs">{problem ?? add.error?.message}</span>
        )}
        <button type="button" className="btn" onClick={discard}>
          {t("invoice.discard")}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={add.isPending || !drafts.some((d) => d.keep)}
          onClick={confirm}
        >
          {t("inspect.confirm")}
        </button>
      </div>
    </section>
  );
}
