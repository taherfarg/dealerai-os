import type { InfiniteData } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { appendPending, pendingMessage, type MessagePage } from "./hooks";
import { parseFrame } from "@/lib/live";

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
