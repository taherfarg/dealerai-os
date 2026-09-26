import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Task } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { FollowUpCard } from "./FollowUpCard";

const task: Task = {
  id: "task-1",
  title: "Follow up with Omar",
  kind: "follow_up",
  due_at: "2026-09-23T10:00:00Z",
  status: "open",
  completed_at: null,
  source: "ai",
  assignee: null,
  contact: { id: "customer-1", name: "Omar" },
  lead_id: null,
  conversation_id: "conversation-1",
  ai_draft: { reason: "The Land Cruiser price dropped AED 4,000", text: "The price has dropped." },
};

function show(overrides: Partial<Task> = {}, onSend = vi.fn(async () => {}), onSkip = vi.fn(async () => {})) {
  render(
    <LocaleProvider locale="en">
      <FollowUpCard task={{ ...task, ...overrides }} tenant="pollux" onSend={onSend} onSkip={onSkip} />
    </LocaleProvider>,
  );
  return { onSend, onSkip };
}

describe("FollowUpCard", () => {
  it("leads with the reason and offers the drafted reply", () => {
    show();
    expect(screen.getByText("The Land Cruiser price dropped AED 4,000")).toBeDefined();
    expect(screen.getByText("The price has dropped.")).toBeDefined();
    expect(screen.getByRole("button", { name: "Send now" })).toBeDefined();
  });

  it("opens the conversation when there is no sendable draft", () => {
    show({ ai_draft: { reason: "Call the customer", text: null } });
    expect(screen.queryByRole("button", { name: "Send now" })).toBeNull();
    expect(screen.getByRole("link", { name: "Open conversation" }).getAttribute("href"))
      .toBe("/pollux/inbox/conversation-1");
  });

  it("shows the approved template when the window is closed", () => {
    show({
      ai_draft: {
        reason: "New price",
        text: null,
        template_id: "template-1",
        template_name: "price_update",
        variables: ["Omar"],
        preview: "Hello Omar, the Hilux is now AED 128,000.",
      },
    });
    expect(screen.getByText(/24-hour window is closed/)).toBeDefined();
    // The message that would go, not only the template's name.
    expect(screen.getByText("Hello Omar, the Hilux is now AED 128,000.")).toBeDefined();
    expect(screen.getByText(/price_update/)).toBeDefined();
    expect(screen.getByRole("button", { name: "Send now" })).toBeDefined();
  });

  it("sends once however quickly it is clicked", async () => {
    let finish!: () => void;
    const onSend = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    show({}, onSend);
    const button = screen.getByRole("button", { name: "Send now" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(onSend).toHaveBeenCalledTimes(1);
    finish();
    await waitFor(() => expect(button).toHaveProperty("disabled", true));
  });

  it("carries the follow-up text into the conversation for editing", () => {
    sessionStorage.clear();
    show();
    fireEvent.click(screen.getByRole("link", { name: "Edit in conversation" }));
    expect(JSON.parse(sessionStorage.getItem("dealerai:followup-edit:conversation-1") ?? "null"))
      .toEqual({ text: "The price has dropped." });
  });

  it("asks for a reason before skipping", async () => {
    const { onSkip } = show();
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(onSkip).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", { name: "Reason for skipping" }), {
      target: { value: "Customer bought elsewhere" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm skip" }));
    await waitFor(() => expect(onSkip).toHaveBeenCalledExactlyOnceWith("Customer bought elsewhere"));
  });
});
