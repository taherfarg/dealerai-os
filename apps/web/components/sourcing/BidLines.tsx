"use client";

import { Ltr } from "@/components/Bidi";
import type { Bid } from "@/lib/api/hooks";
import { formatMoney } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/i18n-client";

const FROM: Record<Bid["price_from"], MessageKey> = {
  history: "sourcing.from.history",
  typed: "sourcing.from.typed",
  assumed: "sourcing.from.assumed",
};

/** Whether the bid has anything left once the costs are paid. */
export function worthBuying(bid: Bid): boolean {
  return bid.max_bid.amount_minor > 0;
}

/**
 * The bid from the price down, one line per thing taken off, each saying
 * where its figure came from — so a person can see which number to argue with.
 */
export function BidLines({ bid }: { bid: Bid }) {
  const t = useT();
  const less = (label: string, amount: Bid["margin"], note?: string) => (
    <div className="flex items-baseline justify-between gap-3">
      <dt>
        {label}
        {note && <span className="text-muted ms-1 text-xs">{note}</span>}
      </dt>
      <dd>
        <Ltr>− {formatMoney(amount)}</Ltr>
      </dd>
    </div>
  );
  return (
    <dl className="space-y-1 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <dt>
          {t("sourcing.expected")}
          <span className="text-muted ms-1 text-xs">{t(FROM[bid.price_from])}</span>
        </dt>
        <dd>
          <Ltr>{formatMoney(bid.expected_price)}</Ltr>
        </dd>
      </div>
      {less(t("sourcing.margin"), bid.margin, `${bid.target_margin_bps / 100}%`)}
      {less(t("sourcing.onTop"), bid.on_top, t(FROM[bid.on_top_from]))}
      {less(
        t("sourcing.holding"),
        bid.holding,
        `${bid.days_to_sell} ${t("economics.days")} · ${t(FROM[bid.days_from])}`,
      )}
      {bid.repairs.amount_minor > 0 && less(t("sourcing.repairs"), bid.repairs)}
      <div className="border-border flex items-baseline justify-between gap-3 border-t pt-1 font-semibold">
        <dt>{t("sourcing.maxBid")}</dt>
        <dd>
          <Ltr>{formatMoney(bid.max_bid)}</Ltr>
        </dd>
      </div>
      {!worthBuying(bid) && <p className="text-danger text-xs">{t("sourcing.nothingLeft")}</p>}
    </dl>
  );
}
