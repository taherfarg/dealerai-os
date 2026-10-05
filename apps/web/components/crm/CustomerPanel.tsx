"use client";

import Link from "next/link";
import { useCreateLead, useCustomer, useEditCustomer, type CustomerDetail } from "@/lib/api/hooks";
import { Auto, CustomerName, Ltr } from "@/components/Bidi";
import { formatMoney } from "@/lib/format";
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
          <h2 className="text-sm font-medium">
            <CustomerName country={record.country} name={record.name} />
          </h2>
          <p className="text-muted truncate text-xs">
            <Ltr>{record.phone}</Ltr>
          </p>
          <p className="text-muted mt-1 text-xs">{record.owner?.name ?? t("customers.nobody")}</p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label={t("customer.close")}
            className="text-muted min-h-11 min-w-11 px-2 text-sm lg:hidden"
          >
            ✕
          </button>
        )}
      </header>

      {record.opted_out && (
        <p className="rounded-md bg-danger-soft px-2 py-1 text-xs text-danger">
          {t("customer.optedOut")}
        </p>
      )}

      {record.tags.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {record.tags.map((tag) => (
            <li key={tag} dir="auto" className="bg-background rounded-full px-2 py-0.5 text-xs">
              {tag}
            </li>
          ))}
        </ul>
      )}

      <section>
        <h3 className="text-muted mb-1 text-xs font-semibold uppercase tracking-wide">
          {t("customer.whatWeKnow")}
        </h3>
        <div className="divide-y divide-border">
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
            // A gap on the row, never a margin on one of its parts: a part with
            // its own direction has its own idea of which side is the start.
            className="hover:bg-background flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-md border border-border p-2"
          >
            <Auto className="text-sm">{openLead.vehicle?.label ?? openLead.pipeline_name}</Auto>
            <Auto className="text-muted text-xs">{openLead.stage.name}</Auto>
            {openLead.budget && (
              <Ltr className="text-muted text-xs">{formatMoney(openLead.budget)}</Ltr>
            )}
            {openLead.band && (
              <span className="text-xs font-medium">{t(`band.${openLead.band}`)}</span>
            )}
          </Link>
        ) : (
          <button
            type="button"
            disabled={createLead.isPending}
            onClick={() => createLead.mutate({ contact_id: contactId })}
            className="hover:bg-background min-h-11 w-full rounded-md border border-dashed border-border-strong text-sm disabled:opacity-60"
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
        className="text-muted mt-auto inline-flex min-h-11 items-center text-xs underline"
      >
        {t("customer.full")}
      </Link>
    </div>
  );
}
