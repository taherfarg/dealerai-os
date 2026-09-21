"use client";

import Link from "next/link";
import { useCreateLead, useCustomer, useEditCustomer, type CustomerDetail } from "@/lib/api/hooks";
import { countryFlag, formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { ProfileField, type Field } from "./ProfileField";

/** The order the panel asks its questions in (docs/sales/08-screens.md § 5). */
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

/**
 * Who this customer is, beside the conversation.
 *
 * The same record as the 360, cut down to what somebody needs while they are
 * typing a reply: what we know, the open lead, what is still to do.
 */
export function CustomerPanel({
  tenant,
  contactId,
  onClose,
  onEvidence,
}: {
  tenant: string;
  contactId: string;
  onClose?: () => void;
  onEvidence?: (messageId: string) => void;
}) {
  const t = useT();
  const customer = useCustomer(contactId);
  const edit = useEditCustomer(contactId);
  const createLead = useCreateLead();

  if (!customer.data) return <p className="text-muted p-4 text-sm">…</p>;
  const record: CustomerDetail = customer.data;
  const profile = (record.profile ?? {}) as Record<string, Field>;
  const openLead = record.leads.find((lead) => lead.stage.category === "open");

  return (
    <div className="flex h-full flex-col gap-4 p-4" data-customer-panel>
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium">
            {countryFlag(record.country)} {record.name ?? t("inbox.unknownCustomer")}
          </h2>
          <p className="text-muted truncate text-xs">{record.phone}</p>
          <p className="text-muted mt-1 text-xs">{record.owner?.name ?? t("customers.nobody")}</p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label={t("customer.close")}
            className="text-muted min-h-11 px-2 text-sm lg:hidden"
          >
            ✕
          </button>
        )}
      </header>

      {record.opted_out && (
        <p className="rounded-md bg-red-500/10 px-2 py-1 text-xs text-red-700 dark:text-red-300">
          {t("customer.optedOut")}
        </p>
      )}

      {record.tags.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {record.tags.map((tag) => (
            <li key={tag} className="bg-background rounded-full px-2 py-0.5 text-xs">
              {tag}
            </li>
          ))}
        </ul>
      )}

      <section>
        <h3 className="text-muted mb-1 text-xs font-semibold uppercase tracking-wide">
          {t("customer.whatWeKnow")}
        </h3>
        <div className="divide-y divide-black/5 dark:divide-white/10">
          {FIELDS.map((name) => (
            <ProfileField
              key={name}
              name={name}
              field={profile[name] ?? null}
              onEvidence={onEvidence}
              onSave={(value) => edit.mutate({ profile: { [name]: value } })}
            />
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-muted mb-1 text-xs font-semibold uppercase tracking-wide">
          {t("customer.openLead")}
        </h3>
        {openLead ? (
          <Link
            href={`/${tenant}/pipeline?lead=${openLead.id}`}
            className="hover:bg-background block rounded-md border border-black/5 p-2 dark:border-white/10"
          >
            <span className="text-sm">{openLead.vehicle?.label ?? openLead.pipeline_name}</span>
            <span className="text-muted ms-2 text-xs">{openLead.stage.name}</span>
            {openLead.budget && (
              <span className="text-muted ms-2 text-xs">{formatMoney(openLead.budget)}</span>
            )}
            {openLead.band && (
              <span className="ms-2 text-xs font-medium">{t(`band.${openLead.band}`)}</span>
            )}
          </Link>
        ) : (
          <button
            type="button"
            disabled={createLead.isPending}
            onClick={() => createLead.mutate({ contact_id: contactId })}
            className="hover:bg-background min-h-11 w-full rounded-md border border-dashed border-black/15 text-sm disabled:opacity-60 dark:border-white/20"
          >
            {t("customer.createLead")}
          </button>
        )}
      </section>

      <p className="text-muted text-xs">
        {t("customer.openTasks")}: {record.open_tasks}
      </p>

      <Link
        href={`/${tenant}/customers/${contactId}`}
        className="text-muted mt-auto text-xs underline"
      >
        {t("customer.full")}
      </Link>
    </div>
  );
}
