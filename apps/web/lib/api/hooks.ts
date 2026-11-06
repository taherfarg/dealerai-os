"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { useEffect } from "react";
import { unwrap } from "./client";
import { useTenantApi } from "./context";
import { keys } from "./keys";
import type { components, paths } from "./schema";

export type Conversation = components["schemas"]["ConversationSummary"];
export type ConversationPage = components["schemas"]["ConversationPage"];
export type Message = components["schemas"]["MessageOut"];
export type MessagePage = components["schemas"]["MessagePage"];
export type Suggestion = components["schemas"]["Suggestion"];
export type ConversationView = "mine" | "unassigned" | "team" | "all";

export type InboxFilters = {
  view: ConversationView;
  status: string;
  q: string;
};

/** The part of a filter set that changes the list. */
const filterKey = (filters: InboxFilters) => `${filters.status}|${filters.q}`;

export function useMe() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.me(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/me", { params: { header } })),
  });
}

/**
 * Tells the server which language is on screen, whenever that is not the one
 * it has for this person — so what it writes for them while they are away, a
 * notification or a push, is in it. Said on a difference rather than on a
 * click: that covers the toggle, a second device, and everybody who chose
 * Arabic before the server kept it.
 */
export function useTellServerMyLanguage(locale: "en" | "ar") {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  const known = useMe().data?.locale;
  const { mutate } = useMutation({
    mutationFn: async (said: "en" | "ar") =>
      unwrap(await api.PUT("/v1/me/locale", { params: { header }, body: { locale: said } })),
    // Remembered here, so it is said once and not again on the next render.
    onSuccess: (_nothing, said) =>
      queryClient.setQueryData(
        keys.me(tenantId),
        (me: components["schemas"]["MeOut"] | undefined) => me && { ...me, locale: said },
      ),
  });
  useEffect(() => {
    if (known && known !== locale) mutate(locale);
  }, [known, locale, mutate]);
}

export type Member = components["schemas"]["dealerai__routes__team__MemberOut"];

/** Everyone in the workspace — who a customer can be handed to, and whether
 *  they are taking chats at all. */
export function useMembers() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.members(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/members", { params: { header } })),
  });
}

export function useSetAcceptingChats() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (accepting_chats: boolean) =>
      unwrap(
        await api.PATCH("/v1/me", {
          params: { header },
          body: { accepting_chats },
        }),
      ),
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

/** A draft arrives after the message, and has its own live-update key. */
export function useSuggestion(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.suggestion(tenantId, conversationId),
    staleTime: 0,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/conversations/{conversation_id}/suggestion", {
          params: { header, path: { conversation_id: conversationId } },
        }),
      ),
  });
}

export function useRegenerateSuggestion(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/v1/conversations/{conversation_id}/suggestion/regenerate", {
          params: { header, path: { conversation_id: conversationId } },
        }),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.suggestion(tenantId, conversationId) }),
  });
}

export function useSuggestionOutcome(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      suggestionId,
      reason,
    }: {
      suggestionId: string;
      reason: "wrong_info" | "wrong_tone" | "not_needed" | "other";
    }) =>
      unwrap(
        await api.POST("/v1/suggestions/{suggestion_id}/outcome", {
          params: { header, path: { suggestion_id: suggestionId } },
          body: { outcome: "discarded", reason },
        }),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.suggestion(tenantId, conversationId) }),
  });
}

export function useSendDraft() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (taskId: string) =>
      unwrap(
        await api.POST("/v1/tasks/{task_id}/send-draft", {
          params: {
            header: { ...header, "Idempotency-Key": crypto.randomUUID() },
            path: { task_id: taskId },
          },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.taskList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.myDay(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.conversationList(tenantId) });
    },
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

export type SendReply =
  | { text: string; suggestionId?: string }
  | { templateId: string; variables: string[]; suggestionId?: string };

export function useSendMessage(conversationId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  const key = keys.messages(tenantId, conversationId);
  return useMutation({
    mutationFn: async (reply: SendReply) =>
      unwrap(
        await api.POST("/v1/conversations/{conversation_id}/messages", {
          params: {
            header: { ...header, "Idempotency-Key": crypto.randomUUID() },
            path: { conversation_id: conversationId },
          },
          body: "text" in reply
            ? { text: reply.text, suggestion_id: reply.suggestionId ?? null }
            : {
                template_id: reply.templateId,
                variables: reply.variables,
                suggestion_id: reply.suggestionId ?? null,
              },
        }),
      ),
    // The reply appears as it is typed; the server's row replaces it.
    onMutate: async (reply: SendReply) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<InfiniteData<MessagePage>>(key);
      if ("text" in reply) {
        queryClient.setQueryData<InfiniteData<MessagePage>>(key, (old) =>
          appendPending(old, pendingMessage(conversationId, reply.text)),
        );
      }
      return { previous };
    },
    onError: (_error, _text, context) => {
      // Put the thread back: a message that did not send must not look sent.
      queryClient.setQueryData(key, context?.previous);
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: key });
      queryClient.invalidateQueries({
        queryKey: keys.conversationList(tenantId),
      });
      queryClient.invalidateQueries({ queryKey: keys.counts(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.suggestion(tenantId, conversationId) });
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
      queryClient.invalidateQueries({
        queryKey: keys.messages(tenantId, conversationId),
      }),
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
      queryClient.invalidateQueries({
        queryKey: keys.messages(tenantId, conversationId),
      }),
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
      queryClient.invalidateQueries({
        queryKey: keys.conversationList(tenantId),
      });
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
      queryClient.invalidateQueries({
        queryKey: keys.conversationList(tenantId),
      });
      queryClient.invalidateQueries({
        queryKey: keys.messages(tenantId, conversationId),
      });
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
      queryClient.invalidateQueries({
        queryKey: keys.conversationList(tenantId),
      });
      queryClient.invalidateQueries({
        queryKey: keys.messages(tenantId, conversationId),
      });
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

// --------------------------------------------------------------------------
// push: the caller's own devices ([07] § 8)
// --------------------------------------------------------------------------

export type PushDevice = components["schemas"]["PushDevice"];

/** The key a browser subscribes with. Not retried: a 503 is an answer — push
 *  is not set up on this server — and the screen says so. */
export function usePushKey() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.pushKey(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/push/key", { params: { header } })),
    retry: false,
    staleTime: Infinity,
  });
}

export function usePushDevices() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.pushDevices(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/push-subscriptions", { params: { header } })),
  });
}

export function useSubscribeDevice() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: components["schemas"]["PushSubscriptionIn"]) =>
      unwrap(await api.POST("/v1/push-subscriptions", { params: { header }, body })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.pushDevices(tenantId) }),
  });
}

export function useRemoveDevice() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (deviceId: string) =>
      unwrap(
        await api.DELETE("/v1/push-subscriptions/{device_id}", {
          params: { header, path: { device_id: deviceId } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.pushDevices(tenantId) }),
  });
}

/** A push to my own devices, now. It can forget one that is gone, so the list is re-read. */
export function useTestPush() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/v1/push-subscriptions/test", { params: { header } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.pushDevices(tenantId) }),
  });
}

// --------------------------------------------------------------------------
// customers
// --------------------------------------------------------------------------

export type Customer = components["schemas"]["CustomerSummary"];
export type CustomerDetail = components["schemas"]["CustomerDetail"];
export type TimelineEntry = components["schemas"]["TimelineEntry"];
export type Lead = components["schemas"]["LeadOut"];
export type LeadDetail = components["schemas"]["LeadDetail"];
export type Task = components["schemas"]["SalesTask"];
export type Pipeline = components["schemas"]["Pipeline"];
export type Stage = components["schemas"]["Stage"];
export type MyDay = components["schemas"]["MyDay"];

export type CustomerFilters = {
  q?: string;
  owner_id?: string;
  band?: "hot" | "warm" | "cold";
  country?: string;
  tag?: string;
};

export function useCustomers(filters: CustomerFilters) {
  const { api, tenantId, header } = useTenantApi();
  return useInfiniteQuery({
    queryKey: keys.customers(tenantId, JSON.stringify(filters)),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/v1/customers", {
          params: { header, query: { ...filters, cursor: pageParam } },
        }),
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

export function useCustomer(customerId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.customer(tenantId, customerId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/customers/{customer_id}", {
          params: { header, path: { customer_id: customerId } },
        }),
      ),
  });
}

export function useCustomerTimeline(customerId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useInfiniteQuery({
    queryKey: keys.timeline(tenantId, customerId),
    initialPageParam: 0,
    queryFn: async ({ pageParam }) =>
      unwrap(
        await api.GET("/v1/customers/{customer_id}/timeline", {
          params: {
            header,
            path: { customer_id: customerId },
            query: { offset: pageParam },
          },
        }),
      ),
    getNextPageParam: (page) => page.next_offset ?? undefined,
  });
}

type CustomerEdit = {
  name?: string | null;
  tags?: string[] | null;
  profile?: Record<string, unknown> | null;
};

export function useEditCustomer(customerId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CustomerEdit) =>
      unwrap(
        await api.PATCH("/v1/customers/{customer_id}", {
          params: { header, path: { customer_id: customerId } },
          body,
        }),
      ),
    onSuccess: (customer) => {
      queryClient.setQueryData(keys.customer(tenantId, customerId), customer);
      queryClient.invalidateQueries({ queryKey: keys.customerList(tenantId) });
    },
  });
}

export function useReassignCustomer(customerId: string) {
  const { api, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (owner_id: string) =>
      unwrap(
        await api.POST("/v1/customers/{customer_id}/reassign", {
          params: { header, path: { customer_id: customerId } },
          body: { owner_id },
        }),
      ),
    // Their conversations, leads and tasks all moved with them, so nothing held
    // locally is still true. This is the one case where invalidating everything
    // is the honest answer rather than the lazy one.
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

export function useMergeCustomers() {
  const { api, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { keep_id: string; merge_id: string }) =>
      unwrap(await api.POST("/v1/customers/merge", { params: { header }, body })),
    onSuccess: () => queryClient.invalidateQueries(),
  });
}

// --------------------------------------------------------------------------
// the board
// --------------------------------------------------------------------------

export function usePipelines() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.pipelines(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/pipelines", { params: { header } })),
    // The shape of a board changes about once a quarter.
    staleTime: 5 * 60_000,
  });
}

export function useReplaceStages(pipelineId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (stages: { id?: string; name: string; category: Stage["category"] }[]) =>
      unwrap(
        await api.PUT("/v1/pipelines/{pipeline_id}/stages", {
          params: { header, path: { pipeline_id: pipelineId } },
          body: { stages },
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.pipelines(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.leadList(tenantId) });
    },
  });
}

export type LeadFilters = {
  pipeline_id?: string;
  owner_id?: string;
  band?: "hot" | "warm" | "cold";
  q?: string;
};

export function useLeads(filters: LeadFilters) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.leads(tenantId, JSON.stringify(filters)),
    queryFn: async () => unwrap(await api.GET("/v1/leads", { params: { header, query: filters } })),
  });
}

export function useLead(leadId: string | null) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.lead(tenantId, leadId ?? "none"),
    enabled: Boolean(leadId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/leads/{lead_id}", {
          params: { header, path: { lead_id: leadId ?? "" } },
        }),
      ),
  });
}

export function useCreateLead() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { contact_id: string; pipeline_id?: string; vehicle_id?: string }) =>
      unwrap(await api.POST("/v1/leads", { params: { header }, body })),
    onSuccess: (lead) => {
      queryClient.invalidateQueries({ queryKey: keys.leadList(tenantId) });
      queryClient.invalidateQueries({
        queryKey: keys.customer(tenantId, lead.contact.id),
      });
      queryClient.invalidateQueries({ queryKey: keys.myDay(tenantId) });
    },
  });
}

type LeadEdit = {
  id: string;
  stage_id?: string;
  owner_id?: string;
  vehicle_id?: string;
  lost_reason?: string;
  budget?: { amount_minor: number; currency: string };
};

/**
 * Moving a lead is the move a person makes over and over and watches, so the
 * card lands in its new column before the round trip — and goes back if the API
 * refuses, which it does for a lost lead with no reason.
 *
 * The lead's id is a mutation variable rather than a hook argument: a board
 * moves whichever card was dragged, and a hook per card would mean a hook
 * inside a loop.
 */
export function useEditLead() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: LeadEdit) =>
      unwrap(
        await api.PATCH("/v1/leads/{lead_id}", {
          params: { header, path: { lead_id: id } },
          body,
        }),
      ),
    onMutate: async ({ id, stage_id }) => {
      if (!stage_id) return undefined;
      await queryClient.cancelQueries({ queryKey: keys.leadList(tenantId) });
      const previous = queryClient.getQueriesData<Lead[]>({ queryKey: keys.leadList(tenantId) });
      const moved = queryClient
        .getQueryData<Pipeline[]>(keys.pipelines(tenantId))
        ?.flatMap((pipeline) => pipeline.stages)
        .find((stage) => stage.id === stage_id);
      if (moved) {
        for (const [key, leads] of previous) {
          queryClient.setQueryData<Lead[]>(
            key,
            leads?.map((lead) => (lead.id === id ? { ...lead, stage: moved } : lead)),
          );
        }
      }
      return { previous };
    },
    onError: (_error, _body, context) => {
      for (const [key, leads] of context?.previous ?? []) {
        queryClient.setQueryData(key, leads);
      }
    },
    onSettled: (lead, _error, { id }) => {
      queryClient.invalidateQueries({ queryKey: keys.leadList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.lead(tenantId, id) });
      queryClient.invalidateQueries({ queryKey: keys.myDay(tenantId) });
      if (lead) {
        queryClient.invalidateQueries({ queryKey: keys.customer(tenantId, lead.contact.id) });
      }
    },
  });
}

// --------------------------------------------------------------------------
// tasks and the day
// --------------------------------------------------------------------------

/** The four tabs of the tasks screen, as the API names them. */
export type Bucket = "overdue" | "today" | "upcoming" | "done";

export type TaskFilters = { assignee: string; bucket: Bucket };

export function useTasks(filters: TaskFilters) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.tasks(tenantId, JSON.stringify(filters)),
    queryFn: async () => unwrap(await api.GET("/v1/tasks", { params: { header, query: filters } })),
  });
}

export function useCreateTask() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      title: string;
      due_at: string;
      kind: Task["kind"];
      contact_id?: string;
      lead_id?: string;
      conversation_id?: string;
      assignee_id?: string;
    }) => unwrap(await api.POST("/v1/tasks", { params: { header }, body })),
    onSuccess: (task) => {
      queryClient.invalidateQueries({ queryKey: keys.taskList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.myDay(tenantId) });
      if (task.lead_id) {
        queryClient.invalidateQueries({
          queryKey: keys.lead(tenantId, task.lead_id),
        });
      }
      if (task.contact) {
        queryClient.invalidateQueries({
          queryKey: keys.customer(tenantId, task.contact.id),
        });
      }
    },
  });
}

/** Ticking a task is instant; the Undo toast sends `status: "open"` straight back. */
export function useEditTask() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: {
      id: string;
      title?: string;
      due_at?: string;
      status?: Task["status"];
      cancel_reason?: string;
    }) =>
      unwrap(
        await api.PATCH("/v1/tasks/{task_id}", {
          params: { header, path: { task_id: id } },
          body,
        }),
      ),
    onMutate: async ({ id, status }) => {
      if (!status) return undefined;
      await queryClient.cancelQueries({ queryKey: keys.taskList(tenantId) });
      const previous = queryClient.getQueriesData<Task[]>({
        queryKey: keys.taskList(tenantId),
      });
      for (const [key, tasks] of previous) {
        queryClient.setQueryData<Task[]>(
          key,
          tasks?.map((task) => (task.id === id ? { ...task, status } : task)),
        );
      }
      return { previous };
    },
    onError: (_error, _body, context) => {
      for (const [key, tasks] of context?.previous ?? []) {
        queryClient.setQueryData(key, tasks);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.taskList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.myDay(tenantId) });
    },
  });
}

export function useMyDay() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.myDay(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/dashboard/me", { params: { header } })),
  });
}

// --------------------------------------------------------------------------
// the manager's morning
// --------------------------------------------------------------------------

export type ManagerDashboard = components["schemas"]["ManagerDashboard"];
export type AttentionItem = components["schemas"]["AttentionItem"];
export type RepRow = components["schemas"]["RepRow"];

/** Not fetched at all for somebody who may not read it: a 403 in the console
 *  on every visit is noise, and the page says why instead. */
export function useManagerDashboard(date: string | null, enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.dashboard(tenantId, date ?? "today"),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/dashboard/manager", {
          params: { header, query: date ? { date } : {} },
        }),
      ),
  });
}

// --------------------------------------------------------------------------
// settings
// --------------------------------------------------------------------------

export type SalesSettings = components["schemas"]["SalesSettings"];
export type SalesSettingsPatch = components["schemas"]["SalesSettingsPatch"];
export type RoutingRule = components["schemas"]["RoutingRule"];
export type Team = components["schemas"]["TeamOut"];
export type Acceptance = components["schemas"]["Acceptance"];

export function useSalesSettings() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.salesSettings(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/settings/sales", { params: { header } })),
  });
}

export function useSaveSalesSettings() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    // Only what the screen changed: a manager's routing save must not carry
    // the AI keys she may not write, or the whole save is refused.
    mutationFn: async (patch: SalesSettingsPatch) =>
      unwrap(await api.PATCH("/v1/settings/sales", { params: { header }, body: patch })),
    onSuccess: (saved) => queryClient.setQueryData(keys.salesSettings(tenantId), saved),
  });
}

export function useAcceptance(days: number) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.acceptance(tenantId, days),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/settings/ai/acceptance", { params: { header, query: { days } } }),
      ),
  });
}

export function useTeams() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.teams(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/teams", { params: { header } })),
  });
}

export type Invitation = components["schemas"]["InviteOut"];

/** A signed, expiring link for one email, into teams (routes/tenants.create_invite). */
export function useInvite() {
  const { api, tenantId, header } = useTenantApi();
  return useMutation({
    mutationFn: async (body: components["schemas"]["InviteCreate"]) =>
      unwrap(
        await api.POST("/v1/tenants/{tenant_id}/invites", {
          params: { header, path: { tenant_id: tenantId } },
          body,
        }),
      ),
  });
}

/** A new team without an id, a new name with one. */
export function useSaveTeam() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, name }: { id?: string; name: string }) =>
      id
        ? unwrap(
            await api.PATCH("/v1/teams/{team_id}", {
              params: { header, path: { team_id: id } },
              body: { name, member_ids: [] },
            }),
          )
        : unwrap(await api.POST("/v1/teams", { params: { header }, body: { name, member_ids: [] } })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.teams(tenantId) }),
  });
}

export function useDeleteTeam() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (teamId: string) =>
      unwrap(
        await api.DELETE("/v1/teams/{team_id}", { params: { header, path: { team_id: teamId } } }),
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.teams(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.members(tenantId) });
    },
  });
}

export type MemberPatch = components["schemas"]["MemberPatch"];

export function useEditMember() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ userId, patch }: { userId: string; patch: MemberPatch }) =>
      unwrap(
        await api.PATCH("/v1/members/{user_id}", {
          params: { header, path: { user_id: userId } },
          body: patch,
        }),
      ),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.members(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.teams(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.me(tenantId) });
    },
  });
}

export type QuickReply = components["schemas"]["QuickReply"];
export type QuickReplyIn = components["schemas"]["QuickReplyIn"];

/** `enabled` lets the composer ask only once somebody types "/". */
export function useQuickReplies(enabled = true) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.quickReplies(tenantId),
    enabled,
    queryFn: async () => unwrap(await api.GET("/v1/quick-replies", { params: { header } })),
    // Edited in settings a few times a year; read on every keystroke of "/".
    staleTime: 5 * 60_000,
  });
}

/** A new reply without an id; a whole replacement with one. */
export function useSaveQuickReply() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, reply }: { id?: string; reply: QuickReplyIn }) =>
      id
        ? unwrap(
            await api.PATCH("/v1/quick-replies/{reply_id}", {
              params: { header, path: { reply_id: id } },
              body: reply,
            }),
          )
        : unwrap(await api.POST("/v1/quick-replies", { params: { header }, body: reply })),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.quickReplies(tenantId) }),
  });
}

export function useDeleteQuickReply() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (replyId: string) =>
      unwrap(
        await api.DELETE("/v1/quick-replies/{reply_id}", {
          params: { header, path: { reply_id: replyId } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.quickReplies(tenantId) }),
  });
}

export type KnowledgeDocument = components["schemas"]["Document"];

const STILL_READING = new Set(["pending", "processing"]);

export function useDocuments() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.documents(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/documents", { params: { header } })),
    // Reading a PDF takes seconds, and the row says when it is done.
    refetchInterval: (query) =>
      (query.state.data ?? []).some((document) => STILL_READING.has(document.status))
        ? 3000
        : false,
  });
}

export function useUploadDocument() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, kind, title }: { file: File; kind: string; title: string }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);
      if (title) form.append("title", title);
      return unwrap(
        await api.POST("/v1/documents", {
          params: { header },
          // The typed body describes the fields; the serializer sends the form.
          body: { file: "", kind, title },
          bodySerializer: () => form,
        }),
      );
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.documents(tenantId) }),
  });
}

export function useDeleteDocument() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (documentId: string) =>
      unwrap(
        await api.DELETE("/v1/documents/{document_id}", {
          params: { header, path: { document_id: documentId } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.documents(tenantId) }),
  });
}

export type Channel = components["schemas"]["ChannelOut"];
export type Template = components["schemas"]["TemplateOut"];

export function useChannels() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.channels(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/channels", { params: { header } })),
  });
}

export function useTemplates(channelId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.templates(tenantId, channelId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/channels/{channel_id}/templates", {
          params: { header, path: { channel_id: channelId } },
        }),
      ),
  });
}

export function useSyncTemplates(channelId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/v1/channels/{channel_id}/templates/sync", {
          params: { header, path: { channel_id: channelId } },
        }),
      ),
    // The sync is queued (202); the list catches up on the next look.
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: keys.templates(tenantId, channelId) }),
  });
}

// --------------------------------------------------------------------------
// a customer's data, and many customers at once
// --------------------------------------------------------------------------

/** The customer's file, saved by the browser. A fetch rather than a link:
 *  the request needs an Authorization header an <a href> cannot send. */
export function useExportCustomer(customerId: string) {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async () => {
      const blob = unwrap(
        await api.GET("/v1/customers/{customer_id}/export", {
          params: { header, path: { customer_id: customerId } },
          parseAs: "blob",
        }),
      ) as Blob;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `customer-${customerId}.json`;
      link.click();
      URL.revokeObjectURL(url);
    },
  });
}

export function useEraseCustomer(customerId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/v1/customers/{customer_id}", {
          params: { header, path: { customer_id: customerId } },
        }),
      ),
    onSuccess: () => {
      // Their conversations, leads and tasks went with them: nothing held
      // locally about the workspace is still true (as after a reassign).
      queryClient.removeQueries({ queryKey: keys.customer(tenantId, customerId) });
      queryClient.invalidateQueries();
    },
  });
}

/** S3 left bulk reassign as "the single-customer call in a loop behind a
 *  confirm" — that, returning whoever could not be moved. */
export function useBulkReassign() {
  const { api, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      ids,
      ownerId,
      onProgress,
    }: {
      ids: string[];
      ownerId: string;
      onProgress?: (done: number) => void;
    }) => {
      const failed: string[] = [];
      for (const [index, id] of ids.entries()) {
        const { response } = await api.POST("/v1/customers/{customer_id}/reassign", {
          params: { header, path: { customer_id: id } },
          body: { owner_id: ownerId },
        });
        if (!response.ok) failed.push(id);
        onProgress?.(index + 1);
      }
      return failed;
    },
    onSettled: () => queryClient.invalidateQueries(),
  });
}

// --------------------------------------------------------------------------
// Inventory and the buy side — docs/lifecycle/README.md § L1
// --------------------------------------------------------------------------

export type Vehicle = components["schemas"]["VehicleOut"];
export type VehicleStatus = Vehicle["status"];
export type Economics = components["schemas"]["Economics"];
export type Cost = components["schemas"]["CostOut"];
export type CostIn = components["schemas"]["CostIn"];
export type Acquisition = components["schemas"]["Acquisition"];
export type Extraction = components["schemas"]["ExtractionOut"];

export type VehicleFilters = { status?: VehicleStatus; q?: string };

export function useVehicles(filters: VehicleFilters) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.vehicles(tenantId, JSON.stringify(filters)),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles", {
          params: { header, query: { ...filters, limit: 200 } },
        }),
      ),
  });
}

export function useVehicle(vehicleId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.vehicle(tenantId, vehicleId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles/{vehicle_id}", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
  });
}

/**
 * Every buy-side query takes `enabled`: a screen asks only when the person
 * holds costs.view. The API would refuse anyway — this keeps a salesperson's
 * screen from making requests that can only come back 403.
 */
export function useEconomicsList(enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.economicsList(tenantId),
    enabled,
    queryFn: async () =>
      unwrap(await api.GET("/v1/vehicles/economics", { params: { header } })),
  });
}

export function useEconomics(vehicleId: string, enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.economics(tenantId, vehicleId),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles/{vehicle_id}/economics", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
  });
}

export function useCosts(vehicleId: string, enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.costs(tenantId, vehicleId),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles/{vehicle_id}/costs", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
  });
}

export function useAcquisition(vehicleId: string, enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.acquisition(tenantId, vehicleId),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles/{vehicle_id}/acquisition", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
  });
}

export function useSaveAcquisition(vehicleId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Acquisition) =>
      unwrap(
        await api.PUT("/v1/vehicles/{vehicle_id}/acquisition", {
          params: { header, path: { vehicle_id: vehicleId } },
          body,
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.buySide(tenantId) }),
  });
}

export function useAddCosts(vehicleId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (lines: CostIn[]) =>
      unwrap(
        await api.POST("/v1/vehicles/{vehicle_id}/costs", {
          params: { header, path: { vehicle_id: vehicleId } },
          body: { lines },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.buySide(tenantId) }),
  });
}

export function useDeleteCost(vehicleId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (costId: string) =>
      unwrap(
        await api.DELETE("/v1/vehicles/{vehicle_id}/costs/{cost_id}", {
          params: { header, path: { vehicle_id: vehicleId, cost_id: costId } },
        }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.buySide(tenantId) }),
  });
}

/** Reads a document into proposed lines. Writes nothing — confirming is useAddCosts. */
export function useReadInvoice(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async ({ file, note }: { file: File; note?: string }) => {
      const form = new FormData();
      form.append("file", file);
      if (note) form.append("note", note);
      return unwrap(
        await api.POST("/v1/vehicles/{vehicle_id}/costs/extract", {
          params: { header, path: { vehicle_id: vehicleId } },
          // The typed body describes the fields; the serializer sends the form.
          body: { file: "", note },
          bodySerializer: () => form,
        }),
      );
    },
  });
}

// --------------------------------------------------------------------------
// Pricing — docs/lifecycle/README.md § L2
// --------------------------------------------------------------------------

export type Recommendation = components["schemas"]["RecommendationOut"];
export type PricingSettings = components["schemas"]["PricingSettings"];

export function usePricing(vehicleId: string, enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.pricing(tenantId, vehicleId),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles/{vehicle_id}/pricing", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
  });
}

/** Puts today's recommendation in the approvals queue. Changes no price. */
export function useProposePricing(vehicleId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/v1/vehicles/{vehicle_id}/pricing/propose", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: keys.pricing(tenantId, vehicleId) }),
  });
}

export function usePricingSettings() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.pricingSettings(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/settings/pricing", { params: { header } })),
  });
}

export function useSavePricingSettings() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: PricingSettings) =>
      unwrap(await api.PUT("/v1/settings/pricing", { params: { header }, body })),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.pricingSettings(tenantId), saved);
      // Every recommendation on screen was made under the old rules.
      queryClient.invalidateQueries({ queryKey: keys.buySide(tenantId) });
    },
  });
}

// --------------------------------------------------------------------------
// Reconditioning — docs/lifecycle/README.md § L3
// --------------------------------------------------------------------------

export type Recon = components["schemas"]["ReconOut"];
export type ReconItem = components["schemas"]["ItemOut"];
export type ReconItemIn = components["schemas"]["ItemIn"];
export type ReconPatch = components["schemas"]["ReconPatch"];
export type Inspection = components["schemas"]["InspectionOut"];
export type ReconSettings = components["schemas"]["ReconSettings"];

export function useRecon(vehicleId: string, enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.recon(tenantId, vehicleId),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles/{vehicle_id}/recon", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
  });
}

/** Every recon write can move the ledger, so each one refreshes the buy side. */
function useReconWrite<In, Out>(run: (input: In) => Promise<Out>) {
  const { tenantId } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.buySide(tenantId) }),
  });
}

export function useSaveRecon(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useReconWrite(async (body: ReconPatch) =>
    unwrap(
      await api.PATCH("/v1/vehicles/{vehicle_id}/recon", {
        params: { header, path: { vehicle_id: vehicleId } },
        body,
      }),
    ),
  );
}

export function useAddReconItems(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useReconWrite(async (items: ReconItemIn[]) =>
    unwrap(
      await api.POST("/v1/vehicles/{vehicle_id}/recon/items", {
        params: { header, path: { vehicle_id: vehicleId } },
        body: { items },
      }),
    ),
  );
}

/** Commit, decline: the item moves; what happened comes back on the item. */
export function useReconStep(vehicleId: string, step: "commit" | "decline") {
  const { api, header } = useTenantApi();
  return useReconWrite(async (itemId: string) => {
    const params = { header, path: { vehicle_id: vehicleId, item_id: itemId } };
    return step === "commit"
      ? unwrap(await api.POST("/v1/vehicles/{vehicle_id}/recon/items/{item_id}/commit", { params }))
      : unwrap(await api.POST("/v1/vehicles/{vehicle_id}/recon/items/{item_id}/decline", { params }));
  });
}

/** Correct proposed work — in practice, give it the estimate it lacks. */
export function useUpdateReconItem(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useReconWrite(async ({ itemId, ...body }: { itemId: string; estimate_minor: number }) =>
    unwrap(
      await api.PATCH("/v1/vehicles/{vehicle_id}/recon/items/{item_id}", {
        params: { header, path: { vehicle_id: vehicleId, item_id: itemId } },
        body,
      }),
    ),
  );
}

export function useFinishReconItem(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useReconWrite(
    async ({ itemId, actual_minor, vendor }: { itemId: string; actual_minor: number; vendor?: string | null }) =>
      unwrap(
        await api.POST("/v1/vehicles/{vehicle_id}/recon/items/{item_id}/done", {
          params: { header, path: { vehicle_id: vehicleId, item_id: itemId } },
          body: { actual_minor, vendor: vendor ?? null },
        }),
      ),
  );
}

export function useMarkReady(vehicleId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/v1/vehicles/{vehicle_id}/recon/ready", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
    // A car in draft goes on sale: its status on screen changes too.
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.buySide(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.vehicle(tenantId, vehicleId) });
    },
  });
}

/** Reads inspection photos into proposed work. Writes nothing — confirming is useAddReconItems. */
export function useInspect(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async ({ files, note }: { files: File[]; note?: string }) => {
      const form = new FormData();
      for (const file of files) form.append("files", file);
      if (note) form.append("note", note);
      return unwrap(
        await api.POST("/v1/vehicles/{vehicle_id}/recon/inspect", {
          params: { header, path: { vehicle_id: vehicleId } },
          // The typed body describes the fields; the serializer sends the form.
          body: { files: [], note },
          bodySerializer: () => form,
        }),
      );
    },
  });
}

export function useReconSettings() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.reconSettings(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/settings/recon", { params: { header } })),
  });
}

export function useSaveReconSettings() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: ReconSettings) =>
      unwrap(await api.PUT("/v1/settings/recon", { params: { header }, body })),
    onSuccess: (saved) => {
      queryClient.setQueryData(keys.reconSettings(tenantId), saved);
      queryClient.invalidateQueries({ queryKey: keys.buySide(tenantId) });
    },
  });
}

// --------------------------------------------------------------------------
// Inbound — docs/lifecycle/README.md § L4
// --------------------------------------------------------------------------

export type Inbound = components["schemas"]["InboundOut"];
export type Journey = components["schemas"]["Journey"];
export type MilestoneIn = components["schemas"]["MilestoneIn"];
export type ShippingReading = components["schemas"]["ShippingOut"];
export type ShippingConfirmation = components["schemas"]["Confirmation"];
type MilestoneCode = components["schemas"]["Step"]["code"];
type PaperCode = components["schemas"]["Paper"]["code"];

/** Where the car is — for everybody; its papers and missing fees only for the buy side. */
export function useInbound(vehicleId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.inbound(tenantId, vehicleId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles/{vehicle_id}/inbound", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
  });
}

/** Every inbound write answers with the whole journey: it goes straight on screen. */
function useJourneyWrite<In>(vehicleId: string, run: (input: In) => Promise<Inbound>) {
  const { tenantId } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (journey) => queryClient.setQueryData(keys.inbound(tenantId, vehicleId), journey),
  });
}

export function useSaveJourney(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useJourneyWrite(vehicleId, async (body: Journey) =>
    unwrap(
      await api.PATCH("/v1/vehicles/{vehicle_id}/inbound", {
        params: { header, path: { vehicle_id: vehicleId } },
        body,
      }),
    ),
  );
}

export function useMoveMilestone(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useJourneyWrite(vehicleId, async ({ code, ...body }: MilestoneIn & { code: MilestoneCode }) =>
    unwrap(
      await api.POST("/v1/vehicles/{vehicle_id}/inbound/milestones/{code}", {
        params: { header, path: { vehicle_id: vehicleId, code } },
        body,
      }),
    ),
  );
}

export function useSetPaper(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useJourneyWrite(
    vehicleId,
    async ({ code, status }: { code: PaperCode; status: "missing" | "received" | "not_needed" }) =>
      unwrap(
        await api.PATCH("/v1/vehicles/{vehicle_id}/inbound/documents/{code}", {
          params: { header, path: { vehicle_id: vehicleId, code } },
          body: { status },
        }),
      ),
  );
}

export function useUploadPaper(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useJourneyWrite(vehicleId, async ({ code, file }: { code: PaperCode; file: File }) => {
    const form = new FormData();
    form.append("file", file);
    return unwrap(
      await api.POST("/v1/vehicles/{vehicle_id}/inbound/documents/{code}/file", {
        params: { header, path: { vehicle_id: vehicleId, code } },
        // The typed body describes the fields; the serializer sends the form.
        body: { file: "" },
        bodySerializer: () => form,
      }),
    );
  });
}

/** Reads a shipping document. Applies nothing — confirming is useConfirmShipping. */
export function useReadShipping(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return unwrap(
        await api.POST("/v1/vehicles/{vehicle_id}/inbound/read", {
          params: { header, path: { vehicle_id: vehicleId } },
          body: { file: "" },
          bodySerializer: () => form,
        }),
      );
    },
  });
}

export function useConfirmShipping(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useJourneyWrite(vehicleId, async (body: ShippingConfirmation) =>
    unwrap(
      await api.POST("/v1/vehicles/{vehicle_id}/inbound/confirm", {
        params: { header, path: { vehicle_id: vehicleId } },
        body,
      }),
    ),
  );
}

// --------------------------------------------------------------------------
// The deal desk — docs/lifecycle/README.md § L6
// --------------------------------------------------------------------------

export type Order = components["schemas"]["OrderOut"];
export type OrderIn = components["schemas"]["OrderIn"];
export type OrderPatch = components["schemas"]["OrderPatch"];
export type PaymentIn = components["schemas"]["PaymentIn"];
export type Receipt = components["schemas"]["ReceiptOut"];

export function useOrders(vehicleId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.orders(tenantId, vehicleId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/vehicles/{vehicle_id}/orders", {
          params: { header, path: { vehicle_id: vehicleId } },
        }),
      ),
  });
}

/** An order write can reserve or sell the car: its orders and its own status both refresh. */
function useOrderWrite<In, Out>(vehicleId: string, run: (input: In) => Promise<Out>) {
  const { tenantId } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.orders(tenantId, vehicleId) });
      queryClient.invalidateQueries({ queryKey: keys.vehicle(tenantId, vehicleId) });
      queryClient.invalidateQueries({ queryKey: keys.vehicleList(tenantId) });
    },
  });
}

export function useCreateOrder(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useOrderWrite(vehicleId, async (body: OrderIn) =>
    unwrap(
      await api.POST("/v1/vehicles/{vehicle_id}/orders", {
        params: { header, path: { vehicle_id: vehicleId } },
        body,
      }),
    ),
  );
}

export function useUpdateOrder(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useOrderWrite(vehicleId, async ({ orderId, ...body }: OrderPatch & { orderId: string }) =>
    unwrap(
      await api.PATCH("/v1/orders/{order_id}", {
        params: { header, path: { order_id: orderId } },
        body,
      }),
    ),
  );
}

export function useRecordPayment(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useOrderWrite(vehicleId, async ({ orderId, ...body }: PaymentIn & { orderId: string }) =>
    unwrap(
      await api.POST("/v1/orders/{order_id}/payments", {
        params: { header, path: { order_id: orderId } },
        body,
      }),
    ),
  );
}

/** Reads a transfer receipt. Records nothing — confirming is useRecordPayment. */
export function useReadReceipt() {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async ({ orderId, file }: { orderId: string; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return unwrap(
        await api.POST("/v1/orders/{order_id}/payments/read", {
          params: { header, path: { order_id: orderId } },
          // The typed body describes the fields; the serializer sends the form.
          body: { file: "" },
          bodySerializer: () => form,
        }),
      );
    },
  });
}

export function useFinishOrder(vehicleId: string) {
  const { api, header } = useTenantApi();
  return useOrderWrite(
    vehicleId,
    async ({ orderId, cancel }: { orderId: string; cancel?: string }) => {
      const params = { header, path: { order_id: orderId } };
      return cancel
        ? unwrap(await api.POST("/v1/orders/{order_id}/cancel", { params, body: { reason: cancel } }))
        : unwrap(await api.POST("/v1/orders/{order_id}/complete", { params }));
    },
  );
}

// --------------------------------------------------------------------------
// The export file — docs/lifecycle/README.md § L7
// --------------------------------------------------------------------------

export type ExportFile = components["schemas"]["ExportOut"];
export type ExportStep = ExportFile["steps"][number];
export type Consignee = components["schemas"]["Consignee"];
export type Invoice = components["schemas"]["InvoiceOut"];
export type DraftCheck = components["schemas"]["DraftCheckOut"];
export type DocumentSettings = components["schemas"]["DocumentSettings"];
export type StepCode =
  paths["/v1/orders/{order_id}/export/steps/{code}"]["post"]["parameters"]["path"]["code"];

export function useExportFile(orderId: string, enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.exportFile(tenantId, orderId),
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/orders/{order_id}/export", {
          params: { header, path: { order_id: orderId } },
        }),
      ),
  });
}

/** Every write to the file answers with the whole file: it goes straight on screen. */
function useFileWrite<In>(orderId: string, run: (input: In) => Promise<ExportFile>) {
  const { tenantId } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (file) => {
      queryClient.setQueryData(keys.exportFile(tenantId, orderId), file);
      // What the invoice says about the consignee is drawn from the same row.
      queryClient.invalidateQueries({ queryKey: keys.invoice(tenantId, orderId) });
    },
  });
}

export function useStartExport(orderId: string) {
  const { api, header } = useTenantApi();
  return useFileWrite(orderId, async () =>
    unwrap(
      await api.POST("/v1/orders/{order_id}/export/start", {
        params: { header, path: { order_id: orderId } },
      }),
    ),
  );
}

export function useSetConsignee(orderId: string) {
  const { api, header } = useTenantApi();
  return useFileWrite(orderId, async (body: Consignee) =>
    unwrap(
      await api.PATCH("/v1/orders/{order_id}/export", {
        params: { header, path: { order_id: orderId } },
        body,
      }),
    ),
  );
}

export function useMoveStep(orderId: string) {
  const { api, header } = useTenantApi();
  return useFileWrite(
    orderId,
    async ({ code, ...body }: components["schemas"]["StepIn"] & { code: StepCode }) =>
      unwrap(
        await api.POST("/v1/orders/{order_id}/export/steps/{code}", {
          params: { header, path: { order_id: orderId, code } },
          body,
        }),
      ),
  );
}

export function useUploadStep(orderId: string) {
  const { api, header } = useTenantApi();
  return useFileWrite(orderId, async ({ code, file }: { code: StepCode; file: File }) => {
    const form = new FormData();
    form.append("file", file);
    return unwrap(
      await api.POST("/v1/orders/{order_id}/export/steps/{code}/document", {
        params: { header, path: { order_id: orderId, code } },
        // The typed body describes the fields; the serializer sends the form.
        body: { file: "" },
        bodySerializer: () => form,
      }),
    );
  });
}

/** A step's paper, saved by the browser. A fetch rather than a link: the
 *  request needs an Authorization header an <a href> cannot send. */
export function useDownloadStep(orderId: string) {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async (code: StepCode) => {
      const response = await api.GET("/v1/orders/{order_id}/export/steps/{code}/document", {
        params: { header, path: { order_id: orderId, code } },
        parseAs: "blob",
      });
      const blob = unwrap(response) as unknown as Blob;
      const disposition = response.response.headers.get("content-disposition") ?? "";
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = /filename="([^"]+)"/.exec(disposition)?.[1] ?? code;
      link.click();
      URL.revokeObjectURL(url);
    },
  });
}

/** Reads a bill of lading draft against the order. Confirms nothing. */
export function useCheckDraft(orderId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return unwrap(
        await api.POST("/v1/orders/{order_id}/export/bl-check", {
          params: { header, path: { order_id: orderId } },
          body: { file: "" },
          bodySerializer: () => form,
        }),
      );
    },
    // The draft is now kept on its step.
    onSettled: () => queryClient.invalidateQueries({ queryKey: keys.exportFile(tenantId, orderId) }),
  });
}

export function useInvoice(orderId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.invoice(tenantId, orderId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/orders/{order_id}/invoice", {
          params: { header, path: { order_id: orderId } },
        }),
      ),
  });
}

export function useSignInvoice(orderId: string) {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/v1/orders/{order_id}/invoice/sign", {
          params: { header, path: { order_id: orderId } },
        }),
      ),
    onSuccess: (invoice) => {
      queryClient.setQueryData(keys.invoice(tenantId, orderId), invoice);
      queryClient.invalidateQueries({ queryKey: keys.exportFile(tenantId, orderId) });
    },
  });
}

export function useDocumentSettings() {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.documentSettings(tenantId),
    queryFn: async () => unwrap(await api.GET("/v1/settings/documents", { params: { header } })),
  });
}

export function useSaveDocumentSettings() {
  const { api, tenantId, header } = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: DocumentSettings) =>
      unwrap(await api.PUT("/v1/settings/documents", { params: { header }, body })),
    onSuccess: (saved) => queryClient.setQueryData(keys.documentSettings(tenantId), saved),
  });
}


// --------------------------------------------------------------------------
// sourcing (Lifecycle L5) — all buy side
// --------------------------------------------------------------------------

export type BuyingList = components["schemas"]["BuyingListOut"];
export type Wanted = components["schemas"]["WantedOut"];
export type Bid = components["schemas"]["BidOut"];
export type Appraisal = components["schemas"]["AppraisalOut"];
export type AppraiseIn = components["schemas"]["AppraiseIn"];

export function useBuyingList(enabled: boolean) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.buyingList(tenantId),
    enabled,
    queryFn: async () => unwrap(await api.GET("/v1/sourcing/buying-list", { params: { header } })),
  });
}

/** Values one car and works out the most to pay. Writes nothing. */
export function useAppraise() {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async (body: AppraiseIn) =>
      unwrap(await api.POST("/v1/sourcing/appraise", { params: { header }, body })),
  });
}

export type TradeIn = {
  make?: string;
  model?: string;
  model_year?: number | null;
  mileage_km?: number | null;
};

/** Reads a trade-in's photos into priced repairs. Stores nothing. */
export function useInspectTradeIn() {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async ({ files, car }: { files: File[]; car: TradeIn }) => {
      const form = new FormData();
      for (const file of files) form.append("files", file);
      for (const [name, value] of Object.entries(car)) {
        if (value !== undefined && value !== null && value !== "") form.append(name, String(value));
      }
      return unwrap(
        await api.POST("/v1/sourcing/inspect", {
          params: { header },
          // The typed body describes the fields; the serializer sends the form.
          body: { files: [] },
          bodySerializer: () => form,
        }),
      );
    },
  });
}

// --------------------------------------------------------------------------
// content review (T3.7)
// --------------------------------------------------------------------------

export type ContentItem = components["schemas"]["ContentItemOut"];
export type ContentDetail = components["schemas"]["ContentDetail"];
export type CopyPatch = components["schemas"]["CopyPatch"];

export function useContentList(status: string | null) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: [...keys.contentList(tenantId), status ?? "all"],
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/content", {
          params: { header, query: { status: status ?? undefined, limit: 200 } },
        }),
      ),
  });
}

export function useContent(contentId: string) {
  const { api, tenantId, header } = useTenantApi();
  return useQuery({
    queryKey: keys.content(tenantId, contentId),
    queryFn: async () =>
      unwrap(
        await api.GET("/v1/content/{content_id}", {
          params: { header, path: { content_id: contentId } },
        }),
      ),
  });
}

/** Starts a content run; returns at once with its id. */
export function useGenerateContent() {
  const { api, header } = useTenantApi();
  return useMutation({
    mutationFn: async ({ vehicle_ids, count }: { vehicle_ids: string[]; count: number }) =>
      unwrap(
        await api.POST("/v1/content/generate", {
          params: { header },
          body: { vehicle_ids, count, objective: "sell this stock" },
        }),
      ),
  });
}

/** Approve, reject or edit: each answers with the piece as it now is. */
function useContentChange<T>(
  contentId: string,
  send: (api: ReturnType<typeof useTenantApi>, input: T) => Promise<ContentDetail>,
) {
  const tenant = useTenantApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: T) => send(tenant, input),
    onSuccess: (piece) => {
      queryClient.setQueryData(keys.content(tenant.tenantId, contentId), piece);
      void queryClient.invalidateQueries({ queryKey: keys.contentList(tenant.tenantId) });
    },
  });
}

export function useEditCopy(contentId: string) {
  return useContentChange(
    contentId,
    async ({ api, header }, { locale, patch }: { locale: string; patch: CopyPatch }) =>
      unwrap(
        await api.PATCH("/v1/content/{content_id}/copy/{locale}", {
          params: { header, path: { content_id: contentId, locale } },
          body: patch,
        }),
      ),
  );
}

export function useApproveContent(contentId: string) {
  return useContentChange<void>(contentId, async ({ api, header }) =>
    unwrap(
      await api.POST("/v1/content/{content_id}/approve", {
        params: { header, path: { content_id: contentId } },
      }),
    ),
  );
}

export function useRejectContent(contentId: string) {
  return useContentChange(contentId, async ({ api, header }, reason: string) =>
    unwrap(
      await api.POST("/v1/content/{content_id}/reject", {
        params: { header, path: { content_id: contentId } },
        body: { reason },
      }),
    ),
  );
}
