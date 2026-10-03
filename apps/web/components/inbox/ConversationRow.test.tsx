import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConversationRow } from "./ConversationRow";
import type { Conversation } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";

const base: Conversation = {
  id: "c1",
  channel: { id: "ch1", platform: "whatsapp", name: "Pollux" },
  contact: {
    id: "k1",
    name: "Karim Benali",
    country: "DZ",
    language: "fr",
    tags: [],
    owner: null,
    last_seen_at: null,
  },
  status: "open",
  assignee: null,
  team: null,
  last_message: {
    preview: "Le prix pour Oran ?",
    type: "text",
    direction: "in",
    origin: "customer",
    at: new Date(Date.now() - 60_000).toISOString(),
  },
  unread_count: 2,
  waiting_since: new Date(Date.now() - 12 * 60_000).toISOString(),
  sla_due_at: new Date(Date.now() - 60_000).toISOString(),
  sla_state: "breached",
  window_expires_at: null,
  has_ai_draft: false,
};

const show = (conversation: Conversation) =>
  render(
    <LocaleProvider locale="en">
      <ConversationRow conversation={conversation} href="/pollux/inbox/c1" active={false} />
    </LocaleProvider>,
  );

describe("ConversationRow", () => {
  it("shows who is waiting, for how long, and what they said", () => {
    show(base);
    expect(screen.getByText(/Karim Benali/)).toBeDefined();
    expect(screen.getByText("Le prix pour Oran ?")).toBeDefined();
    expect(screen.getByLabelText(/12m/)).toBeDefined();
    expect(screen.getByLabelText("Unread messages").textContent).toBe("2");
  });

  it("says a missed target out loud, not only in colour", () => {
    const { container } = show(base);
    expect(screen.getByLabelText(/Missed/)).toBeDefined();
    expect(container.querySelector("li")?.dataset.sla).toBe("breached");
  });

  it("has no timer when nobody is waiting", () => {
    const { container } = show({ ...base, waiting_since: null, sla_state: null });
    expect(container.querySelector("li")?.dataset.sla).toBe("none");
    expect(screen.queryByLabelText(/Waiting/)).toBeNull();
  });

  it("lets the name and what was said each choose their direction", () => {
    show(base);
    expect(screen.getByText("Karim Benali").getAttribute("dir")).toBe("auto");
    expect(screen.getByText("Le prix pour Oran ?").getAttribute("dir")).toBe("auto");
  });

  it("marks our own last message as ours, outside the words that were sent", () => {
    show({ ...base, last_message: { ...base.last_message!, direction: "out", origin: "inbox" } });
    // "You:" is the app's word, in the reader's language. Inside the element
    // that takes its direction from the message it would decide that direction.
    expect(screen.getByText("Le prix pour Oran ?").textContent).toBe("Le prix pour Oran ?");
    expect(screen.getByText("You:")).toBeDefined();
  });

  it("marks a reply typed on the phone as coming from the phone", () => {
    show({
      ...base,
      last_message: { ...base.last_message!, direction: "out", origin: "phone_app" },
    });
    expect(screen.getByText("From phone:")).toBeDefined();
  });

  it("says a voice note is a voice note", () => {
    show({
      ...base,
      last_message: { ...base.last_message!, type: "audio", preview: "Voice note" },
    });
    expect(screen.getByText("Voice note")).toBeDefined();
  });

  it("shows an unassigned conversation as unassigned, and an assigned one by name", () => {
    show(base);
    expect(screen.getByText("Unassigned")).toBeDefined();
    show({ ...base, assignee: { id: "u1", name: "Sara Mansour", avatar_url: null } });
    expect(screen.getByText("Sara Mansour")).toBeDefined();
  });
});
