"use client";

import { useState, type FormEvent } from "react";
import { Auto, Ltr } from "@/components/Bidi";
import { useAppraise, useInspectTradeIn, type Appraisal, type Inspection } from "@/lib/api/hooks";
import { asTyped, formatMoney, parseMajor } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { BidLines } from "./BidLines";

type Finding = Inspection["findings"][number];
type Repair = { keep: boolean; estimate: string; finding: Finding };

const MAX_PHOTOS = 8;

/** The typed amount in minor units, undefined when blank, null when unreadable. */
function amount(text: string, currency: string): number | null | undefined {
  return text.trim() ? parseMajor(text, currency) : undefined;
}

/**
 * One car, valued from the dealer's own sales and bid for line by line. For a
 * trade-in, its photos are read into repairs (L3's reader) that a person keeps
 * or drops; their sum is the repairs the bid takes off. Nothing is written.
 */
export function Appraise({ currency }: { currency: string }) {
  const t = useT();
  const value = useAppraise();
  const inspect = useInspectTradeIn();
  const [car, setCar] = useState({ make: "", model: "", year: "", mileage: "" });
  const [money, setMoney] = useState({ expected: "", onTop: "", repairs: "" });
  const [repairs, setRepairs] = useState<Repair[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [result, setResult] = useState<Appraisal | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const typed = {
      expected: amount(money.expected, currency),
      onTop: amount(money.onTop, currency),
      repairs: amount(money.repairs, currency),
    };
    if (Object.values(typed).some((v) => v === null)) return setProblem(t("costs.badAmount"));
    setProblem(null);
    value.mutate(
      {
        make: car.make.trim(),
        model: car.model.trim(),
        model_year: car.year ? Number(car.year) : null,
        expected_price_minor: typed.expected ?? null,
        on_top_minor: typed.onTop ?? null,
        repairs_minor: typed.repairs ?? 0,
      },
      { onSuccess: setResult },
    );
  };

  const readPhotos = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const files = form.getAll("files").filter((f): f is File => f instanceof File && f.size > 0);
    if (files.length === 0) return;
    if (files.length > MAX_PHOTOS) return setProblem(t("inspect.tooMany"));
    setProblem(null);
    inspect.mutate(
      {
        files,
        car: {
          make: car.make.trim() || undefined,
          model: car.model.trim() || undefined,
          model_year: car.year ? Number(car.year) : null,
          mileage_km: car.mileage ? Number(car.mileage) : null,
        },
      },
      {
        onSuccess: (read) =>
          setRepairs(
            read.findings.map((finding) => ({
              keep: true,
              estimate: finding.estimate ? asTyped(finding.estimate.amount_minor, currency) : "",
              finding,
            })),
          ),
      },
    );
  };

  const applyRepairs = () => {
    const kept = (repairs ?? []).filter((r) => r.keep && r.estimate.trim());
    const sums = kept.map((r) => parseMajor(r.estimate, currency));
    if (sums.some((s) => s === null)) return setProblem(t("costs.badAmount"));
    const total = sums.reduce<number>((all, s) => all + (s ?? 0), 0);
    setMoney((before) => ({ ...before, repairs: total ? asTyped(total, currency) : "" }));
    setRepairs(null);
    setProblem(null);
  };

  const field = (label: string, value: string, set: (v: string) => void, more = {}) => (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted">{label}</span>
      <input value={value} onChange={(e) => set(e.target.value)} className="field" {...more} />
    </label>
  );

  return (
    <section>
      <h2 className="text-sm font-semibold">{t("sourcing.appraise")}</h2>
      <p className="text-muted mt-1 text-xs">{t("sourcing.appraiseHint")}</p>
      <form onSubmit={submit} className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {field(t("sourcing.make"), car.make, (make) => setCar({ ...car, make }), {
          required: true,
          maxLength: 60,
        })}
        {field(t("sourcing.model"), car.model, (model) => setCar({ ...car, model }), {
          required: true,
          maxLength: 80,
        })}
        {field(t("sourcing.year"), car.year, (year) => setCar({ ...car, year }), {
          type: "number",
          min: 1950,
          max: 2100,
        })}
        {field(t("sourcing.mileage"), car.mileage, (mileage) => setCar({ ...car, mileage }), {
          type: "number",
          min: 0,
        })}
        {field(
          t("sourcing.expectedTyped"),
          money.expected,
          (expected) => setMoney({ ...money, expected }),
          { inputMode: "decimal" },
        )}
        {field(t("sourcing.onTopTyped"), money.onTop, (onTop) => setMoney({ ...money, onTop }), {
          inputMode: "decimal",
        })}
        {field(
          t("sourcing.repairsTyped"),
          money.repairs,
          (repairs) => setMoney({ ...money, repairs }),
          { inputMode: "decimal" },
        )}
        <div className="flex items-end">
          <button type="submit" className="btn btn-primary w-full" disabled={value.isPending}>
            {value.isPending ? t("sourcing.valuing") : t("sourcing.value")}
          </button>
        </div>
      </form>

      <details className="mt-3">
        <summary className="cursor-pointer text-sm">{t("sourcing.tradeIn")}</summary>
        <p className="text-muted mt-1 text-xs">{t("sourcing.tradeInHint")}</p>
        <form onSubmit={readPhotos} className="mt-2 flex flex-wrap items-end gap-2">
          <input
            type="file"
            name="files"
            multiple
            required
            accept="image/jpeg,image/png,image/webp"
            aria-label={t("sourcing.tradeIn")}
            className="field flex-1"
          />
          <button type="submit" className="btn" disabled={inspect.isPending}>
            {inspect.isPending ? t("inspect.reading") : t("inspect.read")}
          </button>
        </form>
        {repairs && (
          <div className="bg-surface mt-2 rounded-2xl p-3">
            {repairs.length === 0 ? (
              <p className="text-muted text-sm">{t("inspect.nothing")}</p>
            ) : (
              <ul className="divide-border divide-y">
                {repairs.map((repair, i) => (
                  <li key={i} className="grid grid-cols-[auto_1fr_8rem] items-start gap-2 py-2">
                    <input
                      type="checkbox"
                      checked={repair.keep}
                      aria-label={t("inspect.keep")}
                      onChange={(e) =>
                        setRepairs(
                          repairs.map((r, j) => (j === i ? { ...r, keep: e.target.checked } : r)),
                        )
                      }
                      className="mt-1"
                    />
                    <div className="min-w-0 text-sm">
                      <Auto>{repair.finding.description}</Auto>
                      <p className="text-muted text-xs">
                        {t("inspect.seen")} <Auto>{repair.finding.seen}</Auto>
                      </p>
                    </div>
                    <input
                      value={repair.estimate}
                      placeholder={t("recon.estimate")}
                      aria-label={t("recon.estimate")}
                      inputMode="decimal"
                      onChange={(e) =>
                        setRepairs(
                          repairs.map((r, j) => (j === i ? { ...r, estimate: e.target.value } : r)),
                        )
                      }
                      className="field"
                    />
                  </li>
                ))}
              </ul>
            )}
            <button type="button" onClick={applyRepairs} className="btn btn-primary mt-2">
              {t("sourcing.useRepairs")}
            </button>
          </div>
        )}
      </details>

      {(problem ?? value.error?.message ?? inspect.error?.message) && (
        <p role="alert" className="text-danger mt-2 text-xs">
          {problem ?? value.error?.message ?? inspect.error?.message}
        </p>
      )}

      {result && (
        <div className="bg-surface mt-4 max-w-md rounded-2xl p-4">
          <h3 className="font-semibold">
            <Ltr>{[result.model_year, result.make, result.model].filter(Boolean).join(" ")}</Ltr>
          </h3>
          {result.worth.sold > 0 && (
            <p className="text-muted mt-1 text-xs">
              {t("sourcing.sold")}: {result.worth.sold}
              {result.worth.price &&
                ` · ${t("sourcing.median")} ${formatMoney(result.worth.price)}`}
              {result.worth.days_to_sell != null &&
                ` · ${result.worth.days_to_sell} ${t("sourcing.daysToSell")}`}
            </p>
          )}
          <div className="mt-2">
            {result.bid ? (
              <BidLines bid={result.bid} />
            ) : (
              <p className="text-sm">{t("sourcing.noPrice")}</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
