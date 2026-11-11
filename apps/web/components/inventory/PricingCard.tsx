"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Ltr } from "@/components/Bidi";
import { usePricing, useProposePricing } from "@/lib/api/hooks";
import { formatMoney } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

const REASONS = new Set([
  "aged",
  "no_leads",
  "demand",
  "on_target",
  "above_target",
  "floor_missing",
  "floor_low",
]);

/**
 * A reason code from lifecycle/pricing.py, in words. "aged:60" carries its
 * number after a colon; the sentence comes from the catalogue and the number
 * is set beside it, so both languages say it in their own order around a
 * figure that reads the same in either. A code this screen does not know is
 * dropped rather than shown raw.
 */
export function describeReason(code: string, t: (key: MessageKey) => string): string | null {
  const [name, value] = code.split(":");
  if (!REASONS.has(name)) return null;
  const words = t(`pricing.reason.${name}` as MessageKey);
  return value ? `${words} ${value}` : words;
}

const ACTIONS: readonly string[] = [
  "set_price",
  "reduce",
  "hold",
  "below_floor",
  "no_cost",
  "other_currency",
  "not_for_sale",
];

/** What the price should be, why, and one button to send it for approval. */
export function PricingCard({ vehicleId }: { vehicleId: string }) {
  const t = useT();
  const { tenant } = useParams<{ tenant: string }>();
  const pricing = usePricing(vehicleId, true);
  const propose = useProposePricing(vehicleId);
  const rec = pricing.data;
  if (!rec) return null;

  const proposable = rec.action === "set_price" || rec.action === "reduce";
  const reasons = rec.reasons
    .map((code) => describeReason(code, t))
    .filter((line): line is string => line !== null);

  return (
    <section className="bg-surface rounded-2xl p-4">
      <h2 className="text-sm font-semibold">{t("pricing.title")}</h2>
      {ACTIONS.includes(rec.action) && (
        <p className="mt-1 text-sm">{t(`pricing.action.${rec.action}` as MessageKey)}</p>
      )}

      {(rec.price || rec.floor || rec.target) && (
        <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
          {rec.price && (
            <div>
              <dt className="text-muted text-xs">{t("pricing.suggested")}</dt>
              <dd className="font-semibold">
                <Ltr>{formatMoney(rec.price)}</Ltr>
              </dd>
            </div>
          )}
          {rec.floor && (
            <div>
              <dt className="text-muted text-xs">{t("pricing.suggestedFloor")}</dt>
              <dd>
                <Ltr>{formatMoney(rec.floor)}</Ltr>
              </dd>
            </div>
          )}
          {rec.target && (
            <div>
              <dt className="text-muted text-xs">{t("pricing.target")}</dt>
              <dd>
                <Ltr>{formatMoney(rec.target)}</Ltr>
              </dd>
            </div>
          )}
        </dl>
      )}

      {reasons.length > 0 && (
        <ul className="text-muted mt-2 list-disc ps-4 text-xs">
          {reasons.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      {proposable && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {rec.pending_approval_id ? (
            <>
              <span className="pill pill-warning">{t("pricing.proposed")}</span>
              <Link href={`/${tenant}/approvals`} className="text-xs underline">
                {t("pricing.openApprovals")}
              </Link>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-primary"
              disabled={propose.isPending}
              onClick={() => propose.mutate()}
            >
              {t("pricing.propose")}
            </button>
          )}
          {propose.isError && <span className="text-danger text-xs">{propose.error.message}</span>}
        </div>
      )}
    </section>
  );
}
