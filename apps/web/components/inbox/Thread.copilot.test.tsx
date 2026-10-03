import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { Thread } from "./Thread";

const calls = vi.hoisted(() => ({ send: vi.fn(), outcome: vi.fn(), regenerate: vi.fn() }));
vi.mock("@/lib/api/hooks", () => ({
  useMe: () => ({ data: { user: { id: "user-1" } } }),
  useConversation: () => ({
    data: {
      id: "conversation-1",
      status: "open",
      contact: { id: "customer-1", name: "Omar", country: "AE" },
      assignee: { id: "user-1", name: "Ahmed" },
      waiting_since: null,
      sla_state: null,
      window_expires_at: "2099-01-01T00:00:00Z",
    },
  }),
  useMessages: () => ({ data: { pages: [] }, hasNextPage: false }),
  useMarkRead: () => ({ mutate: vi.fn() }),
  useAssignConversation: () => ({ mutate: vi.fn() }),
  useSetConversationStatus: () => ({ mutate: vi.fn() }),
  useRetryMessage: () => ({ mutate: vi.fn() }),
  useSuggestion: () => ({ data: {
    id: "draft-1", conversation_id: "conversation-1", status: "ready",
    text: "The car is available.", template: null, language: "en",
    confidence: "high", intent: "availability", sources: [], actions: [],
    needs_human: null, blocked_reason: null, created_at: "2026-09-23T00:00:00Z",
  } }),
  useRegenerateSuggestion: () => ({ mutate: calls.regenerate }),
  useSuggestionOutcome: () => ({ mutate: calls.outcome }),
  useSendMessage: () => ({ mutate: calls.send, isPending: false, isError: false }),
  useAddNote: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
  useQuickReplies: () => ({ data: [] }),
  useCreateLead: () => ({ mutate: vi.fn() }),
  useCreateTask: () => ({ mutate: vi.fn() }),
  useEditCustomer: () => ({ mutate: vi.fn() }),
}));

describe("copilot in the thread", () => {
  beforeEach(() => sessionStorage.clear());
  it("shows a draft and sends it only after the salesperson presses Send", () => {
    calls.send.mockClear();
    render(<LocaleProvider locale="en"><Thread tenant="pollux" conversationId="conversation-1" /></LocaleProvider>);
    expect(screen.getByText("The car is available.")).toBeDefined();
    expect(calls.send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Send draft" }));
    expect(calls.send).toHaveBeenCalledWith(
      { text: "The car is available.", suggestionId: "draft-1" },
      expect.anything(),
    );
  });

  it("lets a draft reach the customer once, however fast Send is pressed", () => {
    // The panel stays up until the refetch lands; a second press in that gap
    // must not be a second message.
    calls.send.mockClear();
    render(<LocaleProvider locale="en"><Thread tenant="pollux" conversationId="conversation-1" /></LocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Send draft" }));
    fireEvent.click(screen.getByRole("button", { name: "Send draft" }));
    fireEvent.keyDown(window, { key: "Enter", altKey: true });
    expect(calls.send).toHaveBeenCalledTimes(1);
  });

  it("prefills Edit while keeping the suggestion identity", async () => {
    render(<LocaleProvider locale="en"><Thread tenant="pollux" conversationId="conversation-1" /></LocaleProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Edit draft" }));
    await waitFor(() =>
      expect((screen.getByRole("textbox", { name: "Write a reply" }) as HTMLTextAreaElement).value)
        .toBe("The car is available."),
    );
  });

  it("prefills an AI follow-up opened from the task card", async () => {
    sessionStorage.setItem("dealerai:followup-edit:conversation-1", JSON.stringify({ text: "New price for you" }));
    render(<LocaleProvider locale="en"><Thread tenant="pollux" conversationId="conversation-1" /></LocaleProvider>);
    await waitFor(() =>
      expect((screen.getByRole("textbox", { name: "Write a reply" }) as HTMLTextAreaElement).value)
        .toBe("New price for you"),
    );
    expect(sessionStorage.getItem("dealerai:followup-edit:conversation-1")).toBeNull();
  });
});

describe("the thread's messages", () => {
  it("are a log, so a screen reader hears a message arrive", () => {
    render(<LocaleProvider locale="en"><Thread tenant="pollux" conversationId="conversation-1" /></LocaleProvider>);
    const log = screen.getByRole("log", { name: "Messages" });
    expect(log.getAttribute("aria-live")).toBe("polite");
    // The list stays a list inside it: a log is not one.
    expect(log.querySelector("ul")).not.toBeNull();
  });
});

describe("the thread's header", () => {
  it("turns the back arrow round for somebody who reads right to left", () => {
    render(<LocaleProvider locale="ar"><Thread tenant="pollux" conversationId="conversation-1" /></LocaleProvider>);
    const back = screen.getByRole("link", { name: "العودة إلى المحادثات" });
    expect(back.querySelector("span")?.className).toContain("rtl:-scale-x-100");
  });
});
