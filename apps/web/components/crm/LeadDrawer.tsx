"use client";

import Link from "next/link";
import { useLead, useMe, type Stage } from "@/lib/api/hooks";
import { formatDateTime, formatDue, formatMoney, formatRelative } from "@/lib/format";
import { Auto, Ltr } from "@/components/Bidi";
import { useLocale, useT } from "@/lib/i18n-client";
import { word } from "@/lib/words";
import { ScoreReasons } from "./ScoreReasons";

/** Everything about one lead, opened from `?lead=` so the URL can be shared. */
export function LeadDrawer({
  tenant,
  leadId,
  stages,
  onClose,
  onMove,
}: {
  tenant: string;
  leadId: string;
  stages: Stage[];
  onClose: () => void;
  onMove: (leadId: string, stageId: string) => void;
}) {
  const t = useT();
  const locale = useLocale();
  const me = useMe();
  const lead = useLead(leadId);

  return (
    <aside
      aria-label={t("customer.details")}
      className="border-border bg-surface fixed inset-y-0 end-0 z-30 w-full overflow-y-auto border-s p-4 shadow-xl sm:w-96"
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-medium" dir="auto">
          {lead.data?.contact.name ?? "…"}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("lead.close")}
          className="text-muted min-h-11 px-2"
        >
          ✕
        </button>
      </div>

      {lead.data && (
        <div className="mt-3 flex flex-col gap-4">
          <p className="text-sm">{lead.data.vehicle?.label ?? t("pipeline.noCar")}</p>

          <label className="block">
            <span className="text-muted text-xs">{t("lead.stage")}</span>
            <select
              value={lead.data.stage.id}
              onChange={(event) => onMove(leadId, event.target.value)}
              className="mt-1 min-h-11 w-full rounded-md border border-black/10 bg-transparent text-sm dark:border-white/15"
            >
              {stages.map((stage) => (
                <option key={stage.id} value={stage.id}>
                  {stage.name}
                </option>
              ))}
            </select>
          </label>

          <dl className="grid grid-cols-2 gap-2 text-xs">
            <dt className="text-muted">{t("lead.owner")}</dt>
            <dd>{lead.data.owner?.name ?? t("customers.nobody")}</dd>
            {lead.data.budget && (
              <>
                <dt className="text-muted">{t("lead.budget")}</dt>
                <dd>
                  <Ltr>{formatMoney(lead.data.budget)}</Ltr>
                </dd>
              </>
            )}
            <dt className="text-muted">{t("lead.source")}</dt>
            <dd>{lead.data.source ? word(t, "source", lead.data.source) : "—"}</dd>
            <dt className="text-muted">{t("lead.created")}</dt>
            <dd>{formatDateTime(lead.data.created_at, me.data?.tenant.timezone ?? "Asia/Dubai", locale)}</dd>
            {lead.data.lost_reason && (
              <>
                <dt className="text-muted">{t("lead.lostReason")}</dt>
                <dd>
                  <Auto>{lead.data.lost_reason}</Auto>
                </dd>
              </>
            )}
          </dl>

          <ScoreReasons reasons={lead.data.score_reasons} />

          {lead.data.conversation_id && (
            <Link
              href={`/${tenant}/inbox/${lead.data.conversation_id}`}
              className="text-sm underline"
            >
              {t("lead.conversation")}
            </Link>
          )}

          <section>
            <h3 className="text-muted text-xs font-semibold uppercase tracking-wide">
              {t("lead.history")}
            </h3>
            {lead.data.history.length === 0 ? (
              <p className="text-muted mt-1 text-xs">{t("lead.noHistory")}</p>
            ) : (
              <ol className="mt-1">
                {lead.data.history.map((move) => (
                  <li key={move.at} className="flex justify-between gap-2 py-1 text-xs">
                    <Auto>{move.text}</Auto>
                    {/* The name is set apart: beside a Latin name a number joins
                        the name's run, and "3 د" comes out as "د … 3". */}
                    <span className="text-muted shrink-0">
                      <Auto>{move.by}</Auto> · {formatRelative(move.at, locale)}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section>
            <h3 className="text-muted text-xs font-semibold uppercase tracking-wide">
              {t("lead.tasks")}
            </h3>
            {lead.data.tasks.length === 0 ? (
              <p className="text-muted mt-1 text-xs">{t("lead.noTasks")}</p>
            ) : (
              <ul className="mt-1">
                {lead.data.tasks.map((task) => (
                  <li key={task.id} className="flex justify-between gap-2 py-1 text-xs">
                    <Auto className={task.status === "done" ? "line-through" : ""}>
                      {task.title}
                    </Auto>
                    <span className="text-muted shrink-0">{formatDue(task.due_at, locale)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </aside>
  );
}
