"use client";

import { Auto, Ltr } from "@/components/Bidi";
import { Icon } from "@/components/Icon";
import { BAND_PILL } from "@/components/crm/band";
import { useCustomer } from "@/lib/api/hooks";
import { formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

/**
 * The customer's open lead, in one line under their name ([11] § 5.1). It reads
 * what the customer panel reads, so opening the panel asks for nothing new —
 * and it is a button that opens that panel, not a second link to the pipeline.
 */
export function LeadStrip({ contactId, onOpen }: { contactId: string; onOpen: () => void }) {
  const t = useT();
  const customer = useCustomer(contactId);
  const lead = customer.data?.leads.find((candidate) => candidate.stage.category === "open");
  if (!lead) return null;
  return (
    <button
      type="button"
      onClick={onOpen}
      className="bg-background hover:bg-surface mx-3 mt-3 flex min-h-11 flex-wrap items-center gap-x-2 gap-y-1 rounded-2xl px-4 py-2 text-start text-xs lg:mx-5"
    >
      <Icon name="inventory" size={16} className="text-muted" />
      <span className="text-muted">{t("customer.openLead")}</span>
      <Auto className="text-sm font-medium">{lead.vehicle?.label ?? lead.pipeline_name}</Auto>
      <Auto className="pill">{lead.stage.name}</Auto>
      {lead.band && (
        <span className={`pill ${BAND_PILL[lead.band]}`}>{t(`band.${lead.band}`)}</span>
      )}
      {lead.budget && (
        <Ltr className="ms-auto text-sm font-semibold">{formatMoney(lead.budget)}</Ltr>
      )}
    </button>
  );
}
