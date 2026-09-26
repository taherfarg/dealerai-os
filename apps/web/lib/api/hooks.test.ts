import { QueryClient, type InfiniteData } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { appendPending, pendingMessage, type MessagePage } from "./hooks";
import { invalidateLiveEvents, parseFrame } from "@/lib/live";

const page = (texts: string[]): MessagePage => ({
  data: texts.map((text, index) => ({
    ...pendingMessage("c1", text),
    id: `m${index}`,
    status: "sent",
  })),
  next_cursor: null,
});

const thread = (pages: MessagePage[]): InfiniteData<MessagePage> => ({
  pages,
  pageParams: pages.map(() => undefined),
});

describe("the optimistic reply", () => {
  it("appears at the end of the newest page", () => {
    const data = appendPending(thread([page(["Hello"])]), pendingMessage("c1", "On my way"));
    expect(data?.pages[0].data.map((m) => m.text)).toEqual(["Hello", "On my way"]);
  });

  it("is marked queued, not sent", () => {
    const message = pendingMessage("c1", "On my way");
    expect(message.status).toBe("queued");
    expect(message.direction).toBe("out");
    expect(message.origin).toBe("inbox");
  });

  it("leaves an empty thread alone rather than inventing a page", () => {
    expect(appendPending(undefined, pendingMessage("c1", "x"))).toBeUndefined();
    expect(appendPending(thread([]), pendingMessage("c1", "x"))?.pages).toEqual([]);
  });

  it("does not touch the pages it did not append to", () => {
    const older = page(["Older"]);
    const data = appendPending(thread([page(["Newer"]), older]), pendingMessage("c1", "Now"));
    expect(data?.pages[1]).toBe(older);
  });
});

describe("the live stream", () => {
  it("refreshes only the draft when a suggestion is ready", () => {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    invalidateLiveEvents(client, "tenant-1", [
      { type: "suggestion.ready", conversation_id: "conversation-1" },
    ]);
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({
      queryKey: ["suggestion", "tenant-1", "conversation-1"],
    });
  });
  it("refreshes the dashboard on a conversation event", () => {
    // A new draft does not: the test above holds it to exactly one invalidation.
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    invalidateLiveEvents(client, "tenant-1", [
      { type: "message.created", conversation_id: "conversation-1" },
    ]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard", "tenant-1"] });
  });

  it("refreshes each query once for a burst, however many events it holds", () => {
    // A re-seed sent thirty events in five milliseconds, and the dashboard
    // refetched thirty times.
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const burst = Array.from({ length: 30 }, (_, n) => ({
      type: "message.created",
      conversation_id: `conversation-${n % 3}`,
    }));
    invalidateLiveEvents(client, "tenant-1", burst);
    // The dashboard, the lists, the counts and My day once; each of the three
    // threads' messages and header once.
    expect(invalidate).toHaveBeenCalledTimes(4 + 3 * 2);
    expect(
      invalidate.mock.calls.filter(([filters]) => filters?.queryKey?.[0] === "dashboard"),
    ).toHaveLength(1);
  });

  it("reads an event out of a frame", () => {
    const frame = 'event: message.created\ndata: {"type":"message.created","conversation_id":"c1"}';
    expect(parseFrame(frame)).toEqual({ type: "message.created", conversation_id: "c1" });
  });

  it("ignores a heartbeat, which is a comment with no data", () => {
    expect(parseFrame(": heartbeat")).toBeNull();
    expect(parseFrame(": connected")).toBeNull();
  });

  it("survives a frame that is not JSON", () => {
    expect(parseFrame("data: not json")).toBeNull();
  });
});
