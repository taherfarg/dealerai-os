"use client";

import { use, useState } from "react";
import { BoardColumn } from "@/components/crm/BoardColumn";
import { LeadDrawer } from "@/components/crm/LeadDrawer";
import { LostReasonDialog } from "@/components/crm/LostReasonDialog";
import { useEditLead, useLeads, useMe, useMembers, usePipelines } from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { useT } from "@/lib/i18n-client";

const DEFAULTS = { pipeline: "", band: "", owner_id: "", q: "", lead: "" };

export default function PipelinePage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const me = useMe();
  const members = useMembers();
  const pipelines = usePipelines();
  const [filters, setFilters] = useFilters(DEFAULTS);
  const [losing, setLosing] = useState<{ leadId: string; stageId: string } | null>(null);

  const boards = pipelines.data ?? [];
  const board = boards.find((one) => one.id === filters.pipeline) ?? boards[0];
  const leads = useLeads({
    pipeline_id: board?.id,
    band: (filters.band || undefined) as "hot" | "warm" | "cold" | undefined,
    owner_id: filters.owner_id || undefined,
    q: filters.q || undefined,
  });

  const edit = useEditLead();
  // Losing a lead needs a reason, so that move stops here and asks for one;
  // every other move goes straight through.
  const move = (leadId: string, stageId: string) => {
    const stage = board?.stages.find((one) => one.id === stageId);
    if (!stage) return;
    if (stage.category === "lost") return setLosing({ leadId, stageId });
    edit.mutate({ id: leadId, stage_id: stageId });
  };

  const canSeeOthers = (me.data?.permissions ?? []).includes("contacts.reassign");
  const rows = leads.data ?? [];

  return (
    <div className="flex h-[calc(100dvh-10rem)] flex-col">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold">{t("pipeline.title")}</h1>
        {boards.length > 1 && (
          <select
            value={board?.id ?? ""}
            aria-label={t("pipeline.title")}
            onChange={(event) => setFilters({ pipeline: event.target.value })}
            className="field px-3"
          >
            {boards.map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </select>
        )}
        <input
          type="search"
          // Its own text, not the address's: bound to the address it was put
          // back between one letter and the next, and fast typing lost letters.
          defaultValue={filters.q}
          placeholder={t("pipeline.search")}
          aria-label={t("pipeline.search")}
          onChange={(event) => setFilters({ q: event.target.value })}
          className="field field-soft flex-1"
        />
        <select
          value={filters.band}
          aria-label={t("customers.band")}
          onChange={(event) => setFilters({ band: event.target.value })}
          className="field px-3"
        >
          <option value="">{t("customers.anyBand")}</option>
          {(["hot", "warm", "cold"] as const).map((band) => (
            <option key={band} value={band}>
              {t(`band.${band}`)}
            </option>
          ))}
        </select>
        {canSeeOthers && (
          <select
            value={filters.owner_id}
            aria-label={t("customers.owner")}
            onChange={(event) => setFilters({ owner_id: event.target.value })}
            className="field px-3"
          >
            <option value="">{t("pipeline.anyOwner")}</option>
            {(members.data ?? []).map((member) => (
              <option key={member.id} value={member.id}>
                {member.name ?? member.email}
              </option>
            ))}
          </select>
        )}
      </header>

      {board && rows.length === 0 && !leads.isLoading && (
        <p className="text-muted mt-8 text-center text-sm">{t("pipeline.empty")}</p>
      )}

      <div className="mt-3 flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2">
        {(board?.stages ?? []).map((stage) => (
          <BoardColumn
            key={stage.id}
            stage={stage}
            stages={board?.stages ?? []}
            leads={rows.filter((lead) => lead.stage.id === stage.id)}
            onOpen={(leadId) => setFilters({ lead: leadId })}
            onMove={move}
          />
        ))}
      </div>

      {filters.lead && board && (
        <LeadDrawer
          tenant={tenant}
          leadId={filters.lead}
          stages={board.stages}
          onClose={() => setFilters({ lead: "" })}
          onMove={move}
        />
      )}

      {losing && (
        <LostReasonDialog
          onCancel={() => setLosing(null)}
          onConfirm={(reason) => {
            edit.mutate({
              id: losing.leadId,
              stage_id: losing.stageId,
              lost_reason: reason,
            });
            setLosing(null);
          }}
        />
      )}
    </div>
  );
}
