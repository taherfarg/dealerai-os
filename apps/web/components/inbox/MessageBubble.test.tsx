import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MessageBubble } from "./MessageBubble";
import type { Message } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";

const base: Message = {
  id: "m1",
  conversation_id: "c1",
  kind: "message",
  type: "text",
  direction: "in",
  origin: "customer",
  author: null,
  text: "Is the Hilux still available?",
  attachment: null,
  transcript: null,
  location: null,
  template: null,
  reply_to: null,
  reactions: [],
  status: null,
  error: null,
  event: null,
  referral: null,
  created_at: new Date().toISOString(),
};

const show = (overrides: Partial<Message>) =>
  render(
    <LocaleProvider locale="en">
      <ul>
        <MessageBubble message={{ ...base, ...overrides }} onRetry={() => {}} />
      </ul>
    </LocaleProvider>,
  );

describe("MessageBubble", () => {
  it("shows a voice note's player and its transcript", () => {
    show({
      type: "audio",
      text: null,
      attachment: {
        url: "/v1/media/abc",
        mime: "audio/ogg",
        filename: null,
        size_bytes: 9620,
        duration_s: 6,
        width: null,
        height: null,
      },
      transcript: { text: "Is the white Land Cruiser available?", language: "en" },
    });
    expect(screen.getByRole("application", { name: /voice note/i })).toBeDefined();
    // The transcript sits next to the audio, never instead of it.
    expect(screen.getByText(/white Land Cruiser/)).toBeDefined();
  });

  it("can never be mistaken for a sent message when it is a note", () => {
    const { container } = show({
      kind: "note",
      direction: "out",
      origin: "inbox",
      text: "He bought from us in 2023.",
    });
    expect(screen.getByText(/internal note/i)).toBeDefined();
    expect(container.querySelector("[data-kind='note']")).not.toBeNull();
  });

  it("says a message was not delivered, and offers to try again", () => {
    show({
      direction: "out",
      origin: "inbox",
      status: "failed",
      error: { code: "131047", message: "Window closed" },
    });
    expect(screen.getByText(/not delivered/i)).toBeDefined();
    expect(screen.getByRole("button", { name: /try again/i })).toBeDefined();
  });

  it("shows ticks only for messages we sent", () => {
    show({ direction: "out", origin: "inbox", status: "read" });
    expect(screen.getByText("✓✓")).toBeDefined();
  });

  it("marks a reply typed on the phone as coming from the phone", () => {
    show({ direction: "out", origin: "phone_app", text: "Yes, come at 5." });
    expect(screen.getByText(/sent from phone/i)).toBeDefined();
  });

  it("renders an unsupported type honestly rather than blankly", () => {
    show({ type: "unsupported", text: null });
    expect(screen.getByText(/open it on the phone/i)).toBeDefined();
  });

  it("shows an event as a line, not a bubble", () => {
    const { container } = show({
      kind: "event",
      event: { type: "assigned", text: "Assigned to Sara Mansour" },
    });
    expect(container.querySelector("[data-kind='event']")).not.toBeNull();
    expect(screen.getByText("Assigned to Sara Mansour")).toBeDefined();
  });
});
