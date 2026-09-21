"use client";

import { useState } from "react";
import { useMembers, useReassignCustomer, type CustomerDetail } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/**
 * Handing a customer to a colleague.
 *
 * It says what moves before it moves it: their conversations, their open leads
 * and their open tasks all change hands, and somebody pressing this button
 * should not find that out afterwards.
 */
export function ReassignDialog({
  customer,
  onClose,
}: {
  customer: CustomerDetail;
  onClose: () => void;
}) {
  const t = useT();
  const members = useMembers();
  const reassign = useReassignCustomer(customer.id);
  const [chosen, setChosen] = useState("");

  const colleagues = (members.data ?? []).filter(
    (member) => member.id !== customer.owner?.id && member.role !== "viewer",
  );
  const openLeads = customer.leads.filter((lead) => lead.stage.category === "open").length;

  return (
    <div
      role="dialog"
      aria-label={t("customer.reassign")}
      className="bg-surface border-border fixed inset-x-4 top-20 z-40 mx-auto max-w-md rounded-lg border p-4 shadow-xl"
    >
      <h2 className="text-sm font-medium">{t("reassign.title")}</h2>
      <p className="text-muted mt-1 text-xs">{customer.name}</p>

      <fieldset className="mt-3">
        <legend className="text-muted text-xs">{t("reassign.pick")}</legend>
        <ul className="mt-1 max-h-56 overflow-y-auto">
          {colleagues.map((member) => (
            <li key={member.id}>
              <label className="hover:bg-background flex min-h-11 items-center gap-2 rounded-md px-2 text-sm">
                <input
                  type="radio"
                  name="owner"
                  value={member.id}
                  checked={chosen === member.id}
                  onChange={() => setChosen(member.id)}
                />
                <span className="flex-1">{member.name ?? member.email}</span>
                <span className="text-muted text-xs">
                  {member.open_conversations} ·{" "}
                  {member.accepting_chats ? t("reassign.taking") : t("reassign.away")}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </fieldset>

      <section className="text-muted mt-3 text-xs">
        <h3 className="font-semibold">{t("reassign.moves")}</h3>
        <ul className="mt-1 list-inside list-disc">
          <li>{`${openLeads} ${t("reassign.leads")}`}</li>
          <li>{`${customer.open_tasks} ${t("reassign.tasks")}`}</li>
        </ul>
      </section>

      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="min-h-11 px-3 text-sm">
          {t("common.cancel")}
        </button>
        <button
          type="button"
          disabled={!chosen || reassign.isPending}
          onClick={() => reassign.mutate(chosen, { onSuccess: onClose })}
          className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-black disabled:opacity-50"
        >
          {t("reassign.confirm")}
        </button>
      </div>
    </div>
  );
}
