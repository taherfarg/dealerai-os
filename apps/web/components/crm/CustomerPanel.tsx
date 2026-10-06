"use client";

import Link from "next/link";
import { useCreateLead, useCustomer, useEditCustomer, type CustomerDetail } from "@/lib/api/hooks";
import { Avatar } from "@/components/Avatar";
import { Auto, CustomerName, Ltr } from "@/components/Bidi";
import { Icon } from "@/components/Icon";
import { countryName, formatMoney } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";
import { BAND_PILL } from "./band";
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
  const locale = useLocale();
  const customer = useCustomer(contactId);
  const edit = useEditCustomer(contactId);
  const createLead = useCreateLead();

  if (!customer.data) return <p className="text-muted p-4 text-sm">…</p>;
  const record: CustomerDetail = customer.data;
  const profile = (record.profile ?? {}) as Record<string, Field>;
  const openLead = record.leads.find((lead) => lead.stage.category === "open");
  const country = countryName(record.country ?? null, locale);

  return (
    <div className="flex h-full flex-col gap-4 p-4" data-customer-panel>
      <header className="flex items-start gap-3">
        {/* The flag rides on the avatar, and the country is said in words below. */}
        <Avatar name={record.name} country={record.country} size="xl" />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold">
            <CustomerName country={null} name={record.name} />
          </h2>
          <p className="text-muted truncate text-xs">
            <Ltr>{record.phone}</Ltr>
          </p>
          {country && <p className="text-muted text-xs">{country}</p>}
          <p className="text-muted mt-1 text-xs">{record.owner?.name ?? t("customers.nobody")}</p>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label={t("customer.close")}
            className="icon-btn text-muted lg:hidden"
          >
            <Icon name="close" />
          </button>
        )}
      </header>

      {record.opted_out && (
        <p className="pill pill-danger self-start">{t("customer.optedOut")}</p>
      )}

      {record.tags.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {record.tags.map((tag) => (
            <li key={tag} dir="auto" className="pill">
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
            className="border-border hover:bg-surface flex flex-wrap items-center gap-x-2 gap-y-2 rounded-2xl border p-3"
          >
            <Auto className="w-full text-sm font-medium">
              {openLead.vehicle?.label ?? openLead.pipeline_name}
            </Auto>
            <Auto className="pill">{openLead.stage.name}</Auto>
            {openLead.band && (
              <span className={`pill ${BAND_PILL[openLead.band]}`}>{t(`band.${openLead.band}`)}</span>
            )}
            {openLead.budget && (
              <Ltr className="ms-auto text-sm font-semibold">{formatMoney(openLead.budget)}</Ltr>
            )}
          </Link>
        ) : (
          <button
            type="button"
            disabled={createLead.isPending}
            onClick={() => createLead.mutate({ contact_id: contactId })}
            className="btn w-full border-dashed"
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
        className="btn mt-auto"
      >
        {t("customer.full")}
      </Link>
    </div>
  );
}
