"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api/client";
import { useTenantApi } from "@/lib/api/context";
import { keys } from "@/lib/api/keys";
import { getBrowserAccessToken } from "@/lib/auth/token";
import { useT } from "@/lib/i18n-client";

export type RunView = {
  status: string | null;
  tasks: Record<string, { agent: string; status: string }>;
  pieces: Record<string, string>;
  finished: boolean;
  costUsd: number | null;
};

export const EMPTY_RUN: RunView = {
  status: null,
  tasks: {},
  pieces: {},
  finished: false,
  costUsd: null,
};

/** One SSE frame into the view. Pure, so the stream's meaning is testable. */
export function applyEvent(view: RunView, event: string, data: Record<string, unknown>): RunView {
  switch (event) {
    case "task.updated":
      return {
        ...view,
        tasks: {
          ...view.tasks,
          [String(data.task_key)]: { agent: String(data.agent), status: String(data.status) },
        },
      };
    case "content.updated":
      return { ...view, pieces: { ...view.pieces, [String(data.id)]: String(data.status) } };
    case "run.updated":
    case "run.completed":
      return {
        ...view,
        status: String(data.status),
        costUsd: typeof data.cost_usd === "number" ? data.cost_usd : view.costUsd,
        finished: view.finished || event === "run.completed",
      };
    default:
      return view;
  }
}

/** "event: x\ndata: {...}" — or null for a comment (heartbeat). */
export function parseRunFrame(frame: string): [string, Record<string, unknown>] | null {
  let event: string | null = null;
  let data = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!event) return null;
  try {
    return [event, JSON.parse(data || "{}")];
  } catch {
    return null;
  }
}

/** How many times a dropped stream is opened again before the panel gives up. */
export const MAX_ATTEMPTS = 20;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Read a run's stream until it says the run is done, opening it again when it
 * drops first — a failed request, a 5xx, or an end without `run.completed`.
 * Nothing needs replaying: a new stream starts by sending every task and piece
 * as it is now. A 4xx (no such run, not yours) is final, and an abort is silent.
 */
export async function followRun(
  open: () => Promise<Response>,
  onFrame: (event: string, data: Record<string, unknown>) => void,
  signal: AbortSignal,
  wait: (ms: number) => Promise<void> = sleep,
): Promise<boolean> {
  for (let attempt = 0; attempt < MAX_ATTEMPTS && !signal.aborted; attempt++) {
    if (attempt > 0) await wait(Math.min(1000 * 2 ** (attempt - 1), 15_000));
    if (signal.aborted) return false;
    try {
      const response = await open();
      if (response.status >= 400 && response.status < 500) return false;
      if (!response.ok || !response.body) continue;
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += value;
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const parsed = parseRunFrame(frame);
          if (!parsed) continue;
          onFrame(...parsed);
          if (parsed[0] === "run.completed") return true;
        }
      }
    } catch {
      if (signal.aborted) return false;
    }
  }
  return false;
}

/**
 * The run as it happens (GET /v1/runs/{id}/stream), opened with fetch because
 * EventSource cannot send an Authorization header. A piece that appears or
 * moves refreshes the content grid; the stream itself is only a view.
 */
export function useRunStream(runId: string | null): RunView {
  const { tenantId } = useTenantApi();
  const queryClient = useQueryClient();
  const [view, setView] = useState<RunView>(EMPTY_RUN);

  useEffect(() => {
    if (!runId) return;
    // A new run is a new component (`key={runId}`), so the view starts empty.
    const controller = new AbortController();
    const refresh = () =>
      void queryClient.invalidateQueries({ queryKey: keys.contentList(tenantId) });
    const open = async () =>
      fetch(`${API_BASE}/v1/runs/${runId}/stream`, {
        headers: {
          Authorization: `Bearer ${(await getBrowserAccessToken()) ?? ""}`,
          "X-Tenant-Id": tenantId,
        },
        signal: controller.signal,
      });
    void followRun(
      open,
      (event, data) => {
        setView((before) => applyEvent(before, event, data));
        if (event === "content.updated" || event === "run.completed") refresh();
      },
      controller.signal,
    ).finally(refresh);
    return () => controller.abort();
  }, [runId, tenantId, queryClient]);

  return view;
}

const READY = new Set(["pending_approval", "approved"]);

export function RunStream({ runId }: { runId: string }) {
  const t = useT();
  const view = useRunStream(runId);
  const tasks = Object.entries(view.tasks);
  const pieces = Object.values(view.pieces);
  const ready = pieces.filter((status) => READY.has(status)).length;
  const stopped = pieces.filter((status) => status === "rejected" || status === "failed").length;

  return (
    <section className="bg-surface rounded-2xl p-4" aria-live="polite">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">
          {view.finished ? t("content.run.finished") : t("content.run.working")}
        </h2>
        <span className="text-muted text-xs">
          {ready} {t("content.run.ready")}
          {stopped > 0 && ` · ${stopped} ${t("content.run.stopped")}`}
          {view.costUsd != null && ` · $${view.costUsd.toFixed(2)}`}
        </span>
      </div>
      {tasks.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs">
          {tasks.map(([key, task]) => (
            <li key={key} className="flex justify-between gap-2">
              <span className="font-mono">{task.agent}</span>
              <span className={task.status === "failed" ? "text-danger" : "text-muted"}>
                {task.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
