"use client";

import Link from "next/link";
import { WaitingTimer } from "@/components/inbox/WaitingTimer";
import { useAssignConversation, useMembers, type Conversation } from "@/lib/api/hooks";
import { countryFlag } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

/** Enough to act on from the dashboard; the inbox has the rest. */
const SHOWN = 10;

/** Its own component so each row has its own mutation state. */
function WaitingRow({
  conversation,
  tenant,
  canAssign,
}: {
  conversation: Conversation;
  tenant: string;
  canAssign: boolean;
}) {
  const t = useT();
  const members = useMembers();
  const assign = useAssignConversation(conversation.id);
  // People taking chats first: handing a waiting customer to somebody who is
  // away is how they wait twice.
  const colleagues = (members.data ?? [])
    .filter((member) => member.role !== "viewer" && member.id !== conversation.assignee?.id)
    .sort((a, b) => Number(b.accepting_chats) - Number(a.accepting_chats));

  return (
    <li className="flex flex-wrap items-center gap-2 border-b border-black/5 py-2 dark:border-white/10">
      <span className="min-w-0 flex-1 truncate text-sm" dir="auto">
        {countryFlag(conversation.contact.country)}{" "}
        {conversation.contact.name ?? t("inbox.unknownCustomer")}
      </span>
      <span className="text-muted text-xs" dir="auto">
        {conversation.assignee?.name ?? t("customers.nobody")}
      </span>
      <WaitingTimer waitingSince={conversation.waiting_since} state={conversation.sla_state} />
      <Link
        href={`/${tenant}/inbox/${conversation.id}`}
        className="hover:bg-background inline-flex min-h-11 items-center rounded-md px-3 text-sm"
      >
        {t("dashboard.open")}
      </Link>
      {canAssign && (
        <select
          aria-label={t("dashboard.reassign")}
          value=""
          disabled={assign.isPending}
          onChange={(event) => event.target.value && assign.mutate(event.target.value)}
          className="min-h-11 rounded-md border border-black/10 px-2 text-sm dark:border-white/15"
        >
          <option value="">{t("dashboard.reassign")}</option>
          {colleagues.map((member) => (
            <option key={member.id} value={member.id}>
              {member.name ?? member.email}
            </option>
          ))}
        </select>
      )}
    </li>
  );
}

export function WaitingList({
  conversations,
  tenant,
  canAssign,
}: {
  conversations: Conversation[];
  tenant: string;
  canAssign: boolean;
}) {
  const t = useT();
  return (
    <section>
      <h2 className="text-sm font-semibold">{t("dashboard.waiting")}</h2>
      {conversations.length === 0 ? (
        <p className="text-muted mt-2 text-sm">{t("dashboard.nobodyWaiting")}</p>
      ) : (
        <ul className="mt-1">
          {conversations.slice(0, SHOWN).map((conversation) => (
            <WaitingRow
              key={conversation.id}
              conversation={conversation}
              tenant={tenant}
              canAssign={canAssign}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
