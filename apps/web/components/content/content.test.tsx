import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ContentItem } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { ContentGrid, mayReview } from "./ContentGrid";
import { parseHashtags, patchFrom } from "./CopyEditor";
import { EMPTY_RUN, applyEvent, followRun, parseRunFrame } from "./RunStream";

describe("the run stream", () => {
  it("reads a frame and ignores a heartbeat", () => {
    expect(parseRunFrame('event: task.updated\ndata: {"task_key":"plan"}')).toEqual([
      "task.updated",
      { task_key: "plan" },
    ]);
    expect(parseRunFrame(": heartbeat")).toBeNull();
  });

  it("follows tasks and pieces until the run says it is done", () => {
    const frames: [string, Record<string, unknown>][] = [
      ["task.updated", { task_key: "plan", agent: "content_strategist", status: "running" }],
      ["run.updated", { status: "running", cost_usd: 0.01 }],
      ["content.updated", { id: "p1", status: "rendering" }],
      ["task.updated", { task_key: "plan", agent: "content_strategist", status: "completed" }],
      ["content.updated", { id: "p1", status: "pending_approval" }],
      ["run.completed", { status: "completed", cost_usd: 0.42 }],
    ];
    const view = frames.reduce((v, [event, data]) => applyEvent(v, event, data), EMPTY_RUN);
    expect(view.tasks.plan.status).toBe("completed");
    expect(view.pieces).toEqual({ p1: "pending_approval" });
    expect([view.status, view.finished, view.costUsd]).toEqual(["completed", true, 0.42]);
  });
});

/** A stream response that sends these frames, then ends. */
function streamOf(...frames: string[]): Response {
  return new Response(frames.map((f) => `${f}\n\n`).join(""), { status: 200 });
}

const TASK = 'event: task.updated\ndata: {"task_key":"plan"}';
const DONE = 'event: run.completed\ndata: {"status":"completed"}';

describe("a dropped run stream", () => {
  it("is opened again until the run says it is done", async () => {
    const answers = [
      () => Promise.reject(new TypeError("network down")),
      () => Promise.resolve(streamOf(TASK)),
      () => Promise.resolve(streamOf(TASK, DONE)),
    ];
    const seen: string[] = [];
    const finished = await followRun(
      () => answers[seen.filter((e) => e === "open").length]().finally(() => seen.push("open")),
      (event) => seen.push(event),
      new AbortController().signal,
      async () => {},
    );
    expect(finished).toBe(true);
    expect(seen.filter((e) => e === "open")).toHaveLength(3);
    expect(seen.at(-1)).toBe("run.completed");
  });

  it("stops at a 4xx and when the panel goes away", async () => {
    let opened = 0;
    const gone = () => {
      opened += 1;
      return Promise.resolve(new Response("no such run", { status: 404 }));
    };
    expect(await followRun(gone, () => {}, new AbortController().signal, async () => {})).toBe(
      false,
    );
    expect(opened).toBe(1);

    const controller = new AbortController();
    controller.abort();
    expect(await followRun(gone, () => {}, controller.signal, async () => {})).toBe(false);
    expect(opened).toBe(1);
  });
});

describe("content review", () => {
  it("does not send the words the images print", () => {
    const form = new FormData();
    form.set("hook", "Just in");
    form.set("caption", "The MG6 is here.");
    form.set("hashtags", "#mg6");
    expect(patchFrom(form, ["cta"])).toEqual({
      hook: "Just in",
      caption: "The MG6 is here.",
      hashtags: ["mg6"],
    });
  });

  it("takes hashtags however a person types them", () => {
    expect(parseHashtags("#mg6 dubai,  #new ##offer")).toEqual(["mg6", "dubai", "new", "offer"]);
  });

  it("lets marketers and up review, nobody else", () => {
    expect(["viewer", "sales", "marketer", "owner", undefined].map(mayReview)).toEqual([
      false,
      false,
      true,
      true,
      false,
    ]);
  });

  it("shows each piece with its image, car and status, linked to its review", () => {
    const item: ContentItem = {
      id: "p1",
      kind: "post",
      concept: "just_arrived",
      status: "pending_approval",
      vehicle_id: "v1",
      run_id: "r1",
      created_at: new Date().toISOString(),
      locales: ["ar", "en"],
      assets: 1,
      thumbnail_url: "http://api/v1/media/token",
      vehicle: "2026 BYD Leopard 7",
    };
    render(
      <LocaleProvider locale="en">
        <ContentGrid items={[item]} tenant="pollux" />
      </LocaleProvider>,
    );
    expect(screen.getByRole("link").getAttribute("href")).toBe("/pollux/content/p1");
    expect(screen.getByRole("img").getAttribute("alt")).toBe("just arrived");
    expect(screen.getByText("2026 BYD Leopard 7")).toBeTruthy();
    expect(screen.getByText("To approve")).toBeTruthy();
  });
});
