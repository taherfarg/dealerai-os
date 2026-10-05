"use client";

import Link from "next/link";
import { use } from "react";
import { AvailabilitySwitch } from "@/components/AvailabilitySwitch";
import { TaskRow } from "@/components/crm/TaskRow";
import { WaitingTimer } from "@/components/inbox/WaitingTimer";
import { useEditTask, useMe, useMyDay, useSendDraft } from "@/lib/api/hooks";
import { CustomerName } from "@/components/Bidi";
import { formatDuration, formatMoney } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

/** A number with its name under it, which is all three of these need. */
function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface border-border rounded-lg border p-3">
      <p className="text-xl font-semibold">{value}</p>
      <p className="text-muted text-xs">{label}</p>
    </div>
  );
}

export default function TodayPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const locale = useLocale();
  const me = useMe();
  const day = useMyDay();
  const edit = useEditTask();
  const sendDraft = useSendDraft();

  const name = (me.data?.user.name ?? "").split(" ")[0];
  const median = day.data?.median_first_response_seconds;

  return (
    <div className="mx-auto max-w-4xl">
      <h1 className="text-lg font-semibold">
        {/* The comma is the language's own, so it lives in the sentence. */}
        {name ? t("today.hello").replace("{name}", name) : t("today.greeting")}
      </h1>

      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-3">
        <Figure label={t("today.repliedToday")} value={String(day.data?.replied_today ?? 0)} />
        <Figure
          label={t("today.median")}
          value={median ? formatDuration(median, locale) : "—"}
        />
        <div className="bg-surface border-border rounded-lg border p-1">
          <AvailabilitySwitch />
        </div>
      </div>

      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <section>
          <h2 className="text-sm font-semibold">{t("today.waitingOnYou")}</h2>
          {day.data?.waiting_on_you.length ? (
            <ul className="mt-2">
              {day.data.waiting_on_you.map((conversation) => (
                <li key={conversation.id} className="border-b border-border">
                  <Link
                    href={`/${tenant}/inbox/${conversation.id}`}
                    className="hover:bg-surface flex min-h-11 items-center justify-between gap-2 py-2"
                  >
                    <CustomerName
                      country={conversation.contact.country}
                      name={conversation.contact.name}
                      className="text-sm"
                    />
                    <WaitingTimer
                      waitingSince={conversation.waiting_since}
                      state={conversation.sla_state}
                    />
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted mt-2 text-sm">{t("today.nothing")}</p>
          )}
        </section>

        <section>
          <h2 className="text-sm font-semibold">{t("today.dueToday")}</h2>
          {day.data?.due_today.length ? (
            <ul className="mt-2">
              {day.data.due_today.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  tenant={tenant}
                  onComplete={(done) =>
                    edit.mutate({ id: task.id, status: done ? "done" : "open" })
                  }
                  onSnooze={(at) => edit.mutate({ id: task.id, due_at: at.toISOString() })}
                  onSendDraft={async (id) => { await sendDraft.mutateAsync(id); }}
                  onSkipDraft={async (id, reason) => {
                    await edit.mutateAsync({ id, status: "cancelled", cancel_reason: reason });
                  }}
                />
              ))}
            </ul>
          ) : (
            <p className="text-muted mt-2 text-sm">{t("today.nothing")}</p>
          )}
        </section>

        <section className="md:col-span-2">
          <h2 className="text-sm font-semibold">{t("today.hotLeads")}</h2>
          {day.data?.hot_leads.length ? (
            <ul className="mt-2">
              {day.data.hot_leads.map((lead) => (
                <li key={lead.id} className="border-b border-border">
                  <Link
                    href={`/${tenant}/pipeline?lead=${lead.id}`}
                    className="hover:bg-surface flex min-h-11 flex-wrap items-center justify-between gap-2 py-2"
                  >
                    <CustomerName
                      country={lead.contact.country}
                      name={lead.contact.name}
                      className="text-sm"
                    />
                    <span className="text-muted text-xs">
                      {lead.vehicle?.label ?? lead.pipeline_name} · {lead.stage.name}
                      {lead.budget && ` · ${formatMoney(lead.budget)}`}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted mt-2 text-sm">{t("today.nothing")}</p>
          )}
        </section>
      </div>
    </div>
  );
}
