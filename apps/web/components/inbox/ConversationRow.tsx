"use client";

import Link from "next/link";
import type { Conversation } from "@/lib/api/hooks";
import { Auto, CustomerName } from "@/components/Bidi";
import { formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";
import { WaitingTimer } from "./WaitingTimer";

/** What the preview says came from us, rather than from the customer. */
function prefix(conversation: Conversation, mine: string, phone: string): string {
  const last = conversation.last_message;
  if (!last || last.direction === "in") return "";
  return last.origin === "phone_app" ? phone : mine;
}

/**
 * One line of the queue: who, what they said, how long they have waited, and
 * whether anybody has it. Dense on purpose — this is where a salesperson
 * decides what to do next.
 */
export function ConversationRow({
  conversation,
  href,
  active,
}: {
  conversation: Conversation;
  href: string;
  active: boolean;
}) {
  const t = useT();
  const locale = useLocale();
  const { contact, last_message: last } = conversation;
  const unread = conversation.unread_count;
  const ours = prefix(conversation, t("inbox.you"), t("inbox.fromPhone"));
  return (
    <li data-sla={conversation.sla_state ?? "none"}>
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={`block border-b border-black/5 px-3 py-3 transition-colors dark:border-white/10 ${
          active ? "bg-background" : "hover:bg-background"
        }`}
      >
        <div className="flex items-baseline justify-between gap-2">
          <CustomerName
            country={contact.country}
            name={contact.name}
            className="text-sm font-medium"
          />
          {last && (
            <time className="text-muted shrink-0 text-xs" dateTime={last.at}>
              {formatRelative(last.at, locale)}
            </time>
          )}
        </div>

        {/* What was said sits in an element of its own: it chooses its
            direction and is cut at its own end, and "You:" stays the reader's. */}
        <p className="text-muted mt-1 flex gap-1 text-sm">
          {last ? (
            <>
              {ours && <span className="shrink-0">{ours}</span>}
              <Auto className="min-w-0 truncate">{last.preview}</Auto>
            </>
          ) : (
            t("inbox.noMessages")
          )}
        </p>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <WaitingTimer waitingSince={conversation.waiting_since} state={conversation.sla_state} />
          {conversation.assignee ? (
            <span className="text-muted text-xs">{conversation.assignee.name}</span>
          ) : (
            <span className="bg-accent/20 rounded-full px-2 py-0.5 text-xs font-medium">
              {t("inbox.unassigned")}
            </span>
          )}
          {unread > 0 && (
            <span
              className="bg-accent ms-auto min-w-5 rounded-full px-1.5 py-0.5 text-center text-xs font-medium text-black"
              aria-label={t("inbox.unreadCount")}
            >
              {unread}
            </span>
          )}
        </div>
      </Link>
    </li>
  );
}
