"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { unwrap } from "./client";
import { useTenantApi } from "./context";
import { keys } from "./keys";
import type { components } from "./schema";

export type Conversation = components["schemas"]["ConversationSummary"];
export type ConversationPage = components["schemas"]["ConversationPage"];
export type Message = components["schemas"]["MessageOut"];
export type MessagePage = components["schemas"]["MessagePage"];
export type ConversationView = "mine" | "unassigned" | "team" | "all";

export type InboxFilters = { view: ConversationView; status: string; q: string };

/** The part of a filter set that changes the list. */
const filterKey = (filters: InboxFilters) => `${filters.status}|${filters.q}`;

export function useMe() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.me(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/me", { params: { header } })),
  });
}

export function useSetAcceptingChats() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (accepting_chats: boolean) =>
      unwrap(await api.PATCH("/v1/me", { params: { header }, body: { accepting_chats } })),
    onSuccess: (me) => queryClient.setQueryData(keys.me(tenantId), me),
  });
}

// --------------------------------------------------------------------------
// the queue
// --------------------------------------------------------------------------

export function useConversations(filters: InboxFilters) {
  const { api, tenantId, header } = useTenantApi();
  return useInfiniteQuery({
    queryKey: keys.conversations(tenantId, filters.view, filterKey(filters)),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/v1/conversations", {
          params: {
            header,
            query: {
              view: filters.view,
              status: filters.status,
              q: filters.q,
              cursor: pageParam,
            },
          },
        }),
      ),
    getNextPageParam: (page: ConversationPage) => page.next_cursor ?? undefined,
  });
}

export function useConversationCounts() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.counts(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/conversations/counts", { params: { header } })),
  });
}

export function useConversation(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.conversation(tenantId, conversationId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/conversations/{conversation_id}", {
          params: { header, path: { conversation_id: conversationId } },
        }),
      ),
  });
}

export function useMessages(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useInfiniteQuery({
    queryKey: keys.messages(tenantId, conversationId),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/v1/conversations/{conversation_id}/messages", {
          params: {
            header,
            path: { conversation_id: conversationId },
            query: { cursor: pageParam },
          },
        }),
      ),
    // The cursor walks backwards in time, so "next page" is older messages.
    getNextPageParam: (page: MessagePage) => page.next_cursor ?? undefined,
  });
}

// --------------------------------------------------------------------------
// acting on one
// --------------------------------------------------------------------------

/** A message the server has not seen yet, shown while it is on its way. */
export function pendingMessage(conversationId: string, text: string): Message {
  return {
    id: `pending-${crypto.randomUUID()}`,
    conversation_id: conversationId,
    kind: "message",
    type: "text",
    direction: "out",
    origin: "inbox",
    author: null,
    text,
    attachment: null,
    transcript: null,
    location: null,
    template: null,
    reply_to: null,
    reactions: [],
    status: "queued",
    error: null,
    event: null,
    referral: null,
    created_at: new Date().toISOString(),
  };
}

/** Append it to the newest page, which is the one the thread is showing. */
export function appendPending(
  data: InfiniteData<MessagePage> | undefined,
  message: Message,
): InfiniteData<MessagePage> | undefined {
  if (!data || data.pages.length === 0) return data;
  const pages = [...data.pages];
  const first = pages[0];
  pages[0] = { ...first, data: [...first.data, message] };
  return { ...data, pages };
}

export function useSendMessage(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  const key = keys.messages(tenantId, conversationId);
  return useMutation({
    mutationFn: async (text: string) =>
      unwrap(
        await api.POST("/v1/conversations/{conversation_id}/messages", {
          params: {
            header: { ...header, "Idempotency-Key": crypto.randomUUID() },
            path: { conversation_id: conversationId },
          },
          body: { text },
        }),
      ),
    // The reply appears as it is typed; the server's row replaces it.
    onMutate: async (text: string) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<InfiniteData<MessagePage>>(key);
      queryClient.setQueryData<InfiniteData<MessagePage>>(key, (old) =>
        appendPending(old, pendingMessage(conversationId, text)),
      );
      return { previous };
    },
    onError: (_error, _text, context) => {
      // Put the thread back: a message that did not send must not look sent.
      queryClient.setQueryData(key, context?.previous);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: key });
      queryClient.invalidateQueries({ queryKey: keys.conversationList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.counts(tenantId) });
    },
  });
}

export function useAddNote(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (text: string) =>
      unwrap(
        await api.POST("/v1/conversations/{conversation_id}/notes", {
          params: { header, path: { conversation_id: conversationId } },
          body: { text },
        }),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.messages(tenantId, conversationId) }),
  });
}

export function useRetryMessage(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (messageId: string) =>
      unwrap(
        await api.POST("/v1/messages/{message_id}/retry", {
          params: { header, path: { message_id: messageId } },
        }),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.messages(tenantId, conversationId) }),
  });
}

export function useMarkRead(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/v1/conversations/{conversation_id}/read", {
          params: { header, path: { conversation_id: conversationId } },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.conversationList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.counts(tenantId) });
    },
  });
}

export function useAssignConversation(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (userId: string | null) =>
      unwrap(
        await api.POST("/v1/conversations/{conversation_id}/assign", {
          params: { header, path: { conversation_id: conversationId } },
          body: { user_id: userId },
        }),
      ),
    onSuccess: (conversation) => {
      queryClient.setQueryData(keys.conversation(tenantId, conversationId), conversation);
      queryClient.invalidateQueries({ queryKey: keys.conversationList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.messages(tenantId, conversationId) });
      queryClient.invalidateQueries({ queryKey: keys.counts(tenantId) });
    },
  });
}

export function useSetConversationStatus(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (status: "open" | "closed" | "spam") =>
      unwrap(
        await api.POST("/v1/conversations/{conversation_id}/status", {
          params: { header, path: { conversation_id: conversationId } },
          body: { status },
        }),
      ),
    onSuccess: (conversation) => {
      queryClient.setQueryData(keys.conversation(tenantId, conversationId), conversation);
      queryClient.invalidateQueries({ queryKey: keys.conversationList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.messages(tenantId, conversationId) });
      queryClient.invalidateQueries({ queryKey: keys.counts(tenantId) });
    },
  });
}

// --------------------------------------------------------------------------
// notifications
// --------------------------------------------------------------------------

export function useNotifications() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.notifications(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/notifications", { params: { header } })),
  });
}

export function useMarkNotificationsRead() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (ids: string[] | "all") =>
      unwrap(
        await api.POST("/v1/notifications/read", {
          params: { header },
          body: ids === "all" ? { all: true } : { ids, all: false },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.notifications(tenantId) }),
  });
}
