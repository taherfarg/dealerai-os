"use client";

import type { Lead, Stage } from "@/lib/api/hooks";
import { useNow } from "@/lib/clock";
import { Auto, CustomerName, Ltr } from "@/components/Bidi";
import { formatDue, formatMoney } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

const BAND_TONE: Record<string, string> = {
  hot: "bg-red-500/15 text-red-700 dark:text-red-300",
  warm: "bg-amber-500/15 text-amber-800 dark:text-amber-200",
  cold: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
};

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
      className="border-border bg-surface rounded-md border p-2 shadow-sm"
    >
      <button type="button" onClick={onOpen} className="block w-full text-start">
        <span className="flex items-baseline justify-between gap-2">
          <CustomerName
            country={lead.contact.country}
            name={lead.contact.name}
            className="text-sm font-medium"
          />
          {lead.band && (
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${BAND_TONE[lead.band]}`}
            >
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
            {days} {t("pipeline.daysInStage")}
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
        className="text-muted mt-2 min-h-11 w-full rounded-md border border-black/10 bg-transparent text-xs dark:border-white/15"
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
