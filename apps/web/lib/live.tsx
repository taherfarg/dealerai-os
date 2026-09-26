"use client";

import { useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect } from "react";
import { API_BASE } from "@/lib/api/client";
import { useTenantApi } from "@/lib/api/context";
import { keys } from "@/lib/api/keys";
import { getBrowserAccessToken } from "@/lib/auth/token";

/** Ids only — the screen refetches the truth over REST. */
type LiveEvent = { type: string; id?: string | null; conversation_id?: string | null };

const MAX_BACKOFF_MS = 30_000;
/** How long a burst gathers before anything refetches. */
const COALESCE_MS = 250;

/** Pull the `data:` line out of one SSE frame. Comments (`: heartbeat`) have none. */
export function parseFrame(frame: string): LiveEvent | null {
  const line = frame.split("\n").find((candidate) => candidate.startsWith("data:"));
  if (!line) return null;
  try {
    return JSON.parse(line.slice(5).trim()) as LiveEvent;
  } catch {
    return null;
  }
}

/** The state one event makes stale. */
function staleKeys(tenantId: string, event: LiveEvent): QueryKey[] {
  const conversationId = event.conversation_id ?? undefined;
  if (event.type === "suggestion.ready") {
    // Only the draft. A new suggestion changes no thread, list or count, and
    // invalidating those would refetch four queries every time the AI finishes.
    return conversationId ? [keys.suggestion(tenantId, conversationId)] : [];
  }
  // The dashboard counts all of what follows. Only the open day refetches —
  // TanStack marks the rest stale — so one key covers every event below.
  const stale: QueryKey[] = [keys.dashboardAll(tenantId)];
  if (conversationId) {
    if (event.type.startsWith("message.")) stale.push(keys.messages(tenantId, conversationId));
    stale.push(keys.conversation(tenantId, conversationId));
  }
  if (event.type === "notification.created") stale.push(keys.notifications(tenantId));
  if (event.type === "lead.updated") {
    // A lead move is not a conversation change.
    stale.push(keys.leadList(tenantId), keys.myDay(tenantId));
    if (event.id) stale.push(keys.lead(tenantId, event.id));
    return stale;
  }
  if (event.type === "task.updated") {
    return [...stale, keys.taskList(tenantId), keys.myDay(tenantId)];
  }
  return [...stale, keys.conversationList(tenantId), keys.counts(tenantId), keys.myDay(tenantId)];
}

/**
 * Refresh only the state a burst of events affected, each query once. One
 * refresh per event refetched the dashboard thirty times for a thirty-row
 * change — each fetch cancelling the one before it, each still run by the API.
 */
export function invalidateLiveEvents(
  queryClient: QueryClient,
  tenantId: string,
  events: readonly LiveEvent[],
): void {
  const stale = new Map<string, QueryKey>();
  for (const event of events) {
    for (const key of staleKeys(tenantId, event)) stale.set(JSON.stringify(key), key);
  }
  for (const queryKey of stale.values()) void queryClient.invalidateQueries({ queryKey });
}

/**
 * One SSE connection per tab, opened with fetch because the native EventSource
 * cannot send an Authorization header.
 *
 * It only invalidates. A live update that wrote into the cache could disagree
 * with the next refetch, and then which one is right depends on the order they
 * happened to arrive in.
 */
export function useLiveEvents(): void {
  const { tenantId } = useTenantApi();
  const queryClient = useQueryClient();

  useEffect(() => {
    const controller = new AbortController();
    let attempt = 0;
    let stopped = false;
    // A burst — one commit writes many rows — refreshes once, a moment later.
    let burst: LiveEvent[] = [];
    let flush: ReturnType<typeof setTimeout> | undefined;
    const gather = (event: LiveEvent) => {
      burst.push(event);
      flush ??= setTimeout(() => {
        const events = burst;
        burst = [];
        flush = undefined;
        invalidateLiveEvents(queryClient, tenantId, events);
      }, COALESCE_MS);
    };

    const read = async () => {
      while (!stopped) {
        try {
          const token = await getBrowserAccessToken();
          const response = await fetch(`${API_BASE}/v1/stream`, {
            headers: { Authorization: `Bearer ${token ?? ""}`, "X-Tenant-Id": tenantId },
            signal: controller.signal,
          });
          if (!response.ok || !response.body) throw new Error(`stream ${response.status}`);

          // Reconnected: whatever happened while we were away is already in the
          // database, so refetch rather than replay.
          if (attempt > 0) await queryClient.invalidateQueries();
          attempt = 0;

          const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
          let buffer = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += value;
            const frames = buffer.split("\n\n");
            buffer = frames.pop() ?? "";
            for (const frame of frames) {
              const event = parseFrame(frame);
              if (event) gather(event);
            }
          }
        } catch {
          if (controller.signal.aborted) return;
        }
        if (stopped) return;
        // Backoff with jitter: a restarted API must not be hit by every tab at once.
        const wait = Math.min(1000 * 2 ** attempt++, MAX_BACKOFF_MS) * (0.5 + Math.random());
        await new Promise((resolve) => setTimeout(resolve, wait));
      }
    };

    void read();
    return () => {
      stopped = true;
      clearTimeout(flush);
      controller.abort();
    };
  }, [queryClient, tenantId]);
}

/** Mounted once in the tenant layout; renders nothing. */
export function LiveEvents() {
  useLiveEvents();
  return null;
}
