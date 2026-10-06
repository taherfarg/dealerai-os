"use client";

import Link from "next/link";
import { WaitingTimer } from "@/components/inbox/WaitingTimer";
import { useAssignConversation, useMembers, type Conversation } from "@/lib/api/hooks";
import { Avatar } from "@/components/Avatar";
import { CustomerName } from "@/components/Bidi";
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
    <li className="border-border flex flex-wrap items-center gap-x-2 gap-y-1 border-b py-2.5">
      {/* Two lines on purpose ([11] § 5.3). First who is waiting, and for how
          long: min-w-24 because that is the row's point, and on a phone the
          rest of the row used to squeeze it to nothing. The flag rides on the
          avatar, so the name beside it is given none. */}
      <Avatar name={conversation.contact.name} country={conversation.contact.country} size="sm" />
      <CustomerName
        country={null}
        name={conversation.contact.name}
        className="min-w-24 flex-1 text-sm font-medium"
      />
      <WaitingTimer waitingSince={conversation.waiting_since} state={conversation.sla_state} />
      {/* Then who has them, and what can be done about it. */}
      <span aria-hidden className="basis-full" />
      <span className="text-muted flex-1 text-xs" dir="auto">
        {conversation.assignee?.name ?? t("customers.nobody")}
      </span>
      <Link
        href={`/${tenant}/inbox/${conversation.id}`}
        className="btn"
      >
        {t("dashboard.open")}
      </Link>
      {canAssign && (
        <select
          aria-label={t("dashboard.reassign")}
          value=""
          disabled={assign.isPending}
          onChange={(event) => event.target.value && assign.mutate(event.target.value)}
          className="field px-3"
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
