"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api/client";
import {
  useAssignConversation,
  useConversation,
  useMarkRead,
  useMe,
  useMessages,
  useRetryMessage,
  useSetConversationStatus,
} from "@/lib/api/hooks";
import { useNow } from "@/lib/clock";
import { countryFlag, formatUntil } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { CustomerPanel } from "@/components/crm/CustomerPanel";
import { Composer } from "./Composer";
import { MessageBubble } from "./MessageBubble";
import { WaitingTimer } from "./WaitingTimer";

/** One conversation: who it is, what was said, and what you can do about it. */
export function Thread({ tenant, conversationId }: { tenant: string; conversationId: string }) {
  const t = useT();
  const me = useMe();
  const conversation = useConversation(conversationId);
  const messages = useMessages(conversationId);
  const markRead = useMarkRead(conversationId);
  const assign = useAssignConversation(conversationId);
  const setStatus = useSetConversationStatus(conversationId);
  const retry = useRetryMessage(conversationId);
  const now = useNow();
  const [panel, setPanel] = useState(false);

  // Opening it is reading it — for this person only.
  const { mutate: read } = markRead;
  useEffect(() => {
    read();
  }, [read, conversationId]);

  if (conversation.isError) {
    const problem = conversation.error instanceof ApiError ? conversation.error.problem : null;
    return (
      <p className="p-6 text-sm text-red-600 dark:text-red-400">
        {problem?.detail ?? problem?.title ?? t("thread.gone")}
      </p>
    );
  }
  if (!conversation.data) return <p className="text-muted p-6 text-sm">…</p>;

  const row = conversation.data;
  const windowOpen = Boolean(
    row.window_expires_at && new Date(row.window_expires_at).getTime() > now,
  );
  const mine = row.assignee?.id === me.data?.user.id;
  const pages = messages.data?.pages ?? [];
  // Pages walk backwards in time, so the oldest page is last.
  const thread = [...pages].reverse().flatMap((page) => page.data);

  return (
    <div data-thread className="flex h-full min-h-0 flex-col">
      <header className="border-b border-black/5 p-3 dark:border-white/10">
        <div className="flex items-center gap-2">
          <Link href={`/${tenant}/inbox`} className="text-muted text-sm lg:hidden">
            ←
          </Link>
          <h1 className="truncate text-sm font-medium">
            {countryFlag(row.contact.country)} {row.contact.name ?? t("inbox.unknownCustomer")}
          </h1>
          <WaitingTimer waitingSince={row.waiting_since} state={row.sla_state} />
          <div className="ms-auto flex items-center gap-2">
            {!row.assignee && (
              <button
                type="button"
                onClick={() => me.data && assign.mutate(me.data.user.id)}
                className="hover:bg-background min-h-11 rounded-md px-3 text-sm"
              >
                {t("thread.assignToMe")}
              </button>
            )}
            <button
              type="button"
              aria-pressed={panel}
              onClick={() => setPanel((was) => !was)}
              className="hover:bg-background min-h-11 rounded-md px-3 text-sm"
            >
              {t("customer.details")}
            </button>
            {row.status === "open" ? (
              <button
                type="button"
                onClick={() => setStatus.mutate("closed")}
                className="hover:bg-background min-h-11 rounded-md px-3 text-sm"
              >
                {t("thread.close")}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => setStatus.mutate("open")}
                className="hover:bg-background min-h-11 rounded-md px-3 text-sm"
              >
                {t("thread.reopen")}
              </button>
            )}
          </div>
        </div>
        <p className="text-muted mt-1 text-xs">
          {row.assignee
            ? `${mine ? t("thread.assignedToYou") : row.assignee.name}`
            : t("inbox.unassigned")}
          {" · "}
          {windowOpen
            ? `${t("thread.windowOpen")} ${formatUntil(row.window_expires_at ?? "", new Date(now))}`
            : t("thread.windowClosed")}
        </p>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="min-h-0 flex-1 overflow-y-auto py-2">
          {messages.hasNextPage && (
            <button
              type="button"
              onClick={() => messages.fetchNextPage()}
              className="text-muted mx-auto block min-h-11 px-3 text-xs underline"
            >
              {t("thread.older")}
            </button>
          )}
          <ul>
            {thread.map((message) => (
              <MessageBubble key={message.id} message={message} onRetry={retry.mutate} />
            ))}
          </ul>
        </div>

        {panel && (
          // A column beside the thread on a desktop, a sheet over it on a phone.
          <aside className="border-border bg-surface fixed inset-y-0 end-0 z-30 w-80 overflow-y-auto border-s lg:static lg:z-auto lg:w-72">
            <CustomerPanel
              tenant={tenant}
              contactId={row.contact.id}
              onClose={() => setPanel(false)}
              onEvidence={(messageId) => {
                const bubble = document.getElementById(`message-${messageId}`);
                bubble?.scrollIntoView({ block: "center" });
                bubble?.animate([{ opacity: 0.35 }, { opacity: 1 }], { duration: 900 });
              }}
            />
          </aside>
        )}
      </div>

      <Composer
        conversationId={conversationId}
        windowOpen={windowOpen}
        disabled={row.status !== "open"}
      />
    </div>
  );
}
