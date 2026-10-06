"use client";

import type { Lead, Stage } from "@/lib/api/hooks";
import { useNow } from "@/lib/clock";
import { Avatar } from "@/components/Avatar";
import { Auto, CustomerName, Ltr } from "@/components/Bidi";
import { formatDue, formatMoney } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";
import { counted } from "@/lib/words";
import { BAND_PILL } from "./band";

/**
 * One lead on the board.
 *
 * The Move to… menu is here rather than only on the drag handle, because
 * dragging is a mouse with a steady hand: it must never be the only way to move
 * a lead.
 */
export function LeadCard({
  lead,
  stages,
  onOpen,
  onMove,
  now,
}: {
  lead: Lead;
  stages: Stage[];
  onOpen: () => void;
  onMove: (stageId: string) => void;
  /** Fixed clock, for tests. */
  now?: number;
}) {
  const t = useT();
  const locale = useLocale();
  const clock = useNow(60_000, now);
  // Never below zero: the ticking clock lags by up to a minute, and a lead
  // moved a second ago would otherwise read "-1 days here".
  const days = Math.max(
    0,
    Math.floor((clock - new Date(lead.stage_entered_at).getTime()) / 86_400_000),
  );

  return (
    <li
      draggable
      data-lead={lead.id}
      onDragStart={(event) => event.dataTransfer.setData("text/plain", lead.id)}
      // A white card on its soft column ([11] § 5.2).
      className="bg-background rounded-2xl p-3 shadow-sm"
    >
      <button type="button" onClick={onOpen} className="block w-full text-start">
        <span className="flex items-center gap-2">
          {/* The flag rides on the avatar, so the name beside it is given none. */}
          <Avatar name={lead.contact.name} country={lead.contact.country} size="sm" />
          <CustomerName
            country={null}
            name={lead.contact.name}
            className="flex-1 text-sm font-medium"
          />
          {lead.band && (
            <span className={`pill shrink-0 ${BAND_PILL[lead.band]}`}>
              {t(`band.${lead.band}`)} {lead.score ?? ""}
            </span>
          )}
        </span>

        <span className="text-muted mt-1 flex text-xs">
          <Auto className="min-w-0 truncate">{lead.vehicle?.label ?? t("pipeline.noCar")}</Auto>
        </span>

        <span className="text-muted mt-1 flex flex-wrap items-center gap-2 text-[11px]">
          {lead.budget && <Ltr>{formatMoney(lead.budget)}</Ltr>}
          <span>{lead.owner?.name ?? t("customers.nobody")}</span>
          <span>
            {counted(locale, days, "days")} {t("pipeline.here")}
          </span>
          {lead.next_action_at && (
            <span>
              {t("pipeline.nextAction")} {formatDue(lead.next_action_at, locale, new Date(clock))}
            </span>
          )}
        </span>
      </button>

      <select
        aria-label={t("pipeline.moveTo")}
        value={lead.stage.id}
        onChange={(event) => onMove(event.target.value)}
        className="field text-muted mt-2 w-full px-3 text-xs"
      >
        {stages.map((stage) => (
          <option key={stage.id} value={stage.id}>
            {stage.name}
          </option>
        ))}
      </select>
    </li>
  );
}
