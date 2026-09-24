"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import {
  useAssignConversation,
  useConversation,
  useCreateLead,
  useCreateTask,
  useEditCustomer,
  useMarkRead,
  useMe,
  useMessages,
  useRegenerateSuggestion,
  useRetryMessage,
  useSendMessage,
  useSetConversationStatus,
  useSuggestion,
  useSuggestionOutcome,
  type SendReply,
  type Suggestion,
} from "@/lib/api/hooks";
import { useNow } from "@/lib/clock";
import { countryFlag, formatUntil } from "@/lib/format";
import { useT } from "@/lib/i18n-client";
import { CustomerPanel } from "@/components/crm/CustomerPanel";
import { Composer } from "./Composer";
import { DraftPanel } from "./DraftPanel";
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
  const suggestion = useSuggestion(conversationId);
  const regenerate = useRegenerateSuggestion(conversationId);
  const outcome = useSuggestionOutcome(conversationId);
  const sendDraft = useSendMessage(conversationId);
  const createLead = useCreateLead();
  const createTask = useCreateTask();
  const editCustomer = useEditCustomer(conversation.data?.contact.id ?? "");
  const now = useNow();
  const [panel, setPanel] = useState(false);
  const [draftToEdit, setDraftToEdit] = useState<{ id?: string; text: string }>();
  const sentDraft = useRef<string | null>(null);

  // Opening it is reading it — for this person only.
  const { mutate: read } = markRead;
  useEffect(() => {
    read();
  }, [read, conversationId]);

  useEffect(() => {
    try {
      const key = `dealerai:followup-edit:${conversationId}`;
      const saved = sessionStorage.getItem(key);
      if (!saved) return;
      sessionStorage.removeItem(key);
      const candidate = JSON.parse(saved) as { text?: unknown };
      if (typeof candidate.text === "string" && candidate.text.trim()) {
        queueMicrotask(() => setDraftToEdit({ text: candidate.text as string }));
      }
    } catch {
      // Opening the conversation still works in private storage modes.
    }
  }, [conversationId]);

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
  const liveDraft = suggestion.data;
  const template = liveDraft?.template;
  const templateId = template && typeof template.template_id === "string" ? template.template_id : null;
  const cannotSendDraft = row.status !== "open" || (!windowOpen && !templateId);

  const sendSuggestion = (draft: Suggestion) => {
    const draftTemplate = draft.template;
    const id = draftTemplate?.template_id;
    const reply: SendReply | null =
      draftTemplate && typeof id === "string"
        ? {
            templateId: id,
            variables: Array.isArray(draftTemplate.variables)
              ? draftTemplate.variables.filter((value): value is string => typeof value === "string")
              : [],
            suggestionId: draft.id,
          }
        : draft.text && windowOpen
          ? { text: draft.text, suggestionId: draft.id }
          : null;
    // Once per draft, however fast Send is clicked or Alt+Enter repeats: the
    // panel stays up until the refetch lands, and a second press in that gap
    // would reach the customer twice. Only a failed send frees it again.
    if (!reply || sentDraft.current === draft.id) return;
    sentDraft.current = draft.id;
    sendDraft.mutate(reply, {
      onError: () => {
        sentDraft.current = null;
      },
    });
  };

  const takeAction = async (action: Record<string, unknown>) => {
    if (action.kind === "create_lead") {
      await createLead.mutateAsync({
        contact_id: row.contact.id,
        ...(typeof action.vehicle_id === "string" ? { vehicle_id: action.vehicle_id } : {}),
      });
    } else if (action.kind === "create_task" && typeof action.title === "string" && typeof action.due_at === "string") {
      await createTask.mutateAsync({
        title: action.title,
        due_at: action.due_at,
        kind: "follow_up",
        contact_id: row.contact.id,
        conversation_id: conversationId,
      });
    } else if (action.kind === "update_profile" && typeof action.field === "string" && typeof action.value === "string") {
      await editCustomer.mutateAsync({ profile: { [action.field]: action.value } });
    } else {
      throw new Error("This suggested action is incomplete.");
    }
  };

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

      <DraftPanel
        suggestion={liveDraft}
        onSend={sendSuggestion}
        onEdit={(draft) => draft.text && setDraftToEdit({ id: draft.id, text: draft.text })}
        onRegenerate={() => regenerate.mutate()}
        onOutcome={(id, reason) => outcome.mutate({ suggestionId: id, reason })}
        onAction={takeAction}
        sending={sendDraft.isPending}
        sendDisabled={cannotSendDraft}
        error={sendDraft.isError ? (sendDraft.error instanceof ApiError ? sendDraft.error.message : t("thread.sendFailed")) : null}
      />
      <Composer
        key={draftToEdit ? `${draftToEdit.id ?? "followup"}:${draftToEdit.text}` : "plain"}
        conversationId={conversationId}
        windowOpen={windowOpen}
        disabled={row.status !== "open"}
        draftToEdit={draftToEdit}
        onSent={() => setDraftToEdit(undefined)}
      />
    </div>
  );
}
