"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useState } from "react";
import { MergeDialog } from "@/components/crm/MergeDialog";
import { ProfileField, type Field } from "@/components/crm/ProfileField";
import { ReassignDialog } from "@/components/crm/ReassignDialog";
import { Timeline } from "@/components/crm/Timeline";
import { ApiError } from "@/lib/api/client";
import { useCustomer, useEditCustomer, useMe, useTasks } from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { countryFlag, formatMoney, formatRelative } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

const TABS = ["timeline", "leads", "tasks", "profile"] as const;
const FIELDS = [
  "interest",
  "budget",
  "purchase_type",
  "destination",
  "timeline",
  "payment",
  "trade_in",
  "objections",
] as const;

export default function CustomerPage({
  params,
}: {
  params: Promise<{ tenant: string; contactId: string }>;
}) {
  const { tenant, contactId } = use(params);
  const t = useT();
  const router = useRouter();
  const me = useMe();
  const customer = useCustomer(contactId);
  const edit = useEditCustomer(contactId);
  const tasks = useTasks({ assignee: "me", bucket: "today" });
  const [tab, setTab] = useFilters({ tab: "timeline" });
  const [dialog, setDialog] = useState<"reassign" | "merge" | null>(null);

  if (customer.isError) {
    const problem = customer.error instanceof ApiError ? customer.error.problem : null;
    const keepId = problem?.errors?.[0]?.keep_id;
    return (
      <div className="p-6 text-sm">
        <p className="text-red-600 dark:text-red-400">
          {keepId ? t("customer.merged") : (problem?.detail ?? t("customer.gone"))}
        </p>
        {keepId && (
          <Link href={`/${tenant}/customers/${keepId}`} className="mt-2 inline-block underline">
            {t("customer.full")}
          </Link>
        )}
      </div>
    );
  }
  if (!customer.data) return <p className="text-muted p-6 text-sm">…</p>;

  const record = customer.data;
  const profile = (record.profile ?? {}) as Record<string, Field>;
  const may = (permission: string) => (me.data?.permissions ?? []).includes(permission);
  const theirTasks = (tasks.data ?? []).filter((task) => task.contact?.id === contactId);

  return (
    <div className="mx-auto max-w-4xl">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold">
            {countryFlag(record.country)} {record.name ?? t("inbox.unknownCustomer")}
          </h1>
          <ul className="text-muted mt-1 flex flex-wrap gap-3 text-xs">
            {record.identities.map((identity) => (
              <li key={identity.id}>{identity.value}</li>
            ))}
          </ul>
          <p className="text-muted mt-1 text-xs">
            {record.owner?.name ?? t("customers.nobody")}
            {record.opted_out && (
              <span className="ms-2 rounded bg-red-500/15 px-1 text-red-700 dark:text-red-300">
                {t("customer.optedOut")}
              </span>
            )}
          </p>
        </div>
        <div className="flex gap-2">
          {may("contacts.reassign") && (
            <button
              type="button"
              onClick={() => setDialog("reassign")}
              className="hover:bg-background min-h-11 rounded-md px-3 text-sm"
            >
              {t("customer.reassign")}
            </button>
          )}
          {may("contacts.merge") && (
            <button
              type="button"
              onClick={() => setDialog("merge")}
              className="hover:bg-background min-h-11 rounded-md px-3 text-sm"
            >
              {t("customer.merge")}
            </button>
          )}
        </div>
      </header>

      <div
        role="tablist"
        className="mt-4 flex gap-1 overflow-x-auto border-b border-black/5 dark:border-white/10"
      >
        {TABS.map((name) => (
          <button
            key={name}
            role="tab"
            type="button"
            aria-selected={tab.tab === name}
            onClick={() => setTab({ tab: name })}
            className={`min-h-11 shrink-0 px-3 text-sm ${
              tab.tab === name ? "border-accent border-b-2 font-medium" : "text-muted"
            }`}
          >
            {t(`customer.tabs.${name}`)}
          </button>
        ))}
      </div>

      <div className="mt-3">
        {tab.tab === "timeline" && <Timeline contactId={contactId} />}

        {tab.tab === "leads" &&
          (record.leads.length === 0 ? (
            <p className="text-muted text-sm">{t("customer.noLeads")}</p>
          ) : (
            <ul className="divide-y divide-black/5 dark:divide-white/10">
              {record.leads.map((lead) => (
                <li key={lead.id} className="py-2">
                  <Link href={`/${tenant}/pipeline?lead=${lead.id}`} className="text-sm">
                    {lead.vehicle?.label ?? lead.pipeline_name}
                    <span className="text-muted ms-2 text-xs">{lead.stage.name}</span>
                    {lead.budget && (
                      <span className="text-muted ms-2 text-xs">{formatMoney(lead.budget)}</span>
                    )}
                    {lead.lost_reason && (
                      <span className="text-muted ms-2 text-xs italic">{lead.lost_reason}</span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          ))}

        {tab.tab === "tasks" &&
          (theirTasks.length === 0 ? (
            <p className="text-muted text-sm">{t("customer.noTasks")}</p>
          ) : (
            <ul className="divide-y divide-black/5 dark:divide-white/10">
              {theirTasks.map((task) => (
                <li key={task.id} className="flex justify-between gap-2 py-2 text-sm">
                  <span>{task.title}</span>
                  <time className="text-muted text-xs" dateTime={task.due_at}>
                    {formatRelative(task.due_at)}
                  </time>
                </li>
              ))}
            </ul>
          ))}

        {tab.tab === "profile" && (
          <div className="max-w-md divide-y divide-black/5 dark:divide-white/10">
            {FIELDS.map((name) => (
              <ProfileField
                key={name}
                name={name}
                field={profile[name] ?? null}
                onSave={(value) => edit.mutate({ profile: { [name]: value } })}
              />
            ))}
          </div>
        )}
      </div>

      {dialog === "reassign" && (
        <ReassignDialog customer={record} onClose={() => setDialog(null)} />
      )}
      {dialog === "merge" && (
        <MergeDialog
          customer={record}
          onClose={() => setDialog(null)}
          onMerged={() => router.refresh()}
        />
      )}
    </div>
  );
}
