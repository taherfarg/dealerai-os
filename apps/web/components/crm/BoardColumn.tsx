"use client";

import type { Lead, Stage } from "@/lib/api/hooks";
import { Ltr } from "@/components/Bidi";
import { formatMoney } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { LeadCard } from "./LeadCard";

/**
 * One column of the board.
 *
 * Drag and drop is the HTML5 kind, with no library: it is a drop target and a
 * draggable list item, and every card also carries a menu.
 * ponytail: HTML5 drag and drop has no touch support, which is why the menu
 * exists and why a phone gets one column per screen.
 */
export function BoardColumn({
  stage,
  stages,
  leads,
  onOpen,
  onMove,
}: {
  stage: Stage;
  stages: Stage[];
  leads: Lead[];
  onOpen: (leadId: string) => void;
  onMove: (leadId: string, stageId: string) => void;
}) {
  const t = useT();
  const total = leads.reduce((sum, lead) => sum + (lead.budget?.amount_minor ?? 0), 0);
  const currency = leads.find((lead) => lead.budget)?.budget?.currency ?? "AED";

  return (
    <section
      data-stage={stage.id}
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        const leadId = event.dataTransfer.getData("text/plain");
        if (leadId) onMove(leadId, stage.id);
      }}
      className="bg-background/60 flex w-[85vw] shrink-0 snap-center flex-col rounded-lg p-2 sm:w-72"
    >
      <header className="mb-2 flex items-baseline justify-between gap-2 px-1">
        <h2 className="text-sm font-medium" dir="auto">
          {stage.name}
        </h2>
        <span className="text-muted shrink-0 text-xs">
          {leads.length}
          {total > 0 && (
            <>
              {" · "}
              <Ltr>{formatMoney({ amount_minor: total, currency })}</Ltr>
            </>
          )}
        </span>
      </header>

      {leads.length === 0 ? (
        <p className="text-muted px-1 text-xs">{t("pipeline.emptyColumn")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {leads.map((lead) => (
            <LeadCard
              key={lead.id}
              lead={lead}
              stages={stages}
              onOpen={() => onOpen(lead.id)}
              onMove={(stageId) => onMove(lead.id, stageId)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
