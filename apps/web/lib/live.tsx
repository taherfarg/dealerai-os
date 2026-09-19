"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { API_BASE } from "@/lib/api/client";
import { useTenantApi } from "@/lib/api/context";
import { keys } from "@/lib/api/keys";
import { getBrowserAccessToken } from "@/lib/auth/token";

/** Ids only — the screen refetches the truth over REST. */
type LiveEvent = { type: string; conversation_id?: string | null };

const MAX_BACKOFF_MS = 30_000;

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

    const invalidate = (event: LiveEvent) => {
      const conversationId = event.conversation_id ?? undefined;
      if (conversationId) {
        if (event.type.startsWith("message.")) {
          queryClient.invalidateQueries({ queryKey: keys.messages(tenantId, conversationId) });
        }
        queryClient.invalidateQueries({ queryKey: keys.conversation(tenantId, conversationId) });
      }
      if (event.type === "notification.created") {
        queryClient.invalidateQueries({ queryKey: keys.notifications(tenantId) });
      }
      queryClient.invalidateQueries({ queryKey: keys.conversationList(tenantId) });
      queryClient.invalidateQueries({ queryKey: keys.counts(tenantId) });
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
              if (event) invalidate(event);
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
      controller.abort();
    };
  }, [queryClient, tenantId]);
}

/** Mounted once in the tenant layout; renders nothing. */
export function LiveEvents() {
  useLiveEvents();
  return null;
}
