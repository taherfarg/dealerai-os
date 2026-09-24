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
