import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TaskRow, snoozeOptions } from "./TaskRow";
import type { Task } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";

const NOW = new Date("2026-09-21T10:00:00Z").getTime();

const base: Task = {
  id: "t1",
  title: "Call Omar back",
  kind: "call",
  due_at: new Date(NOW + 3_600_000).toISOString(),
  status: "open",
  completed_at: null,
  source: "human",
  assignee: { id: "u1", name: "Ahmed Nasser", avatar_url: null },
  contact: { id: "k1", name: "Omar Al Mazrouei" },
  lead_id: null,
  conversation_id: null,
};

const show = (
  overrides: Partial<Task>,
  handlers: { onComplete?: (done: boolean) => void; onSnooze?: (at: Date) => void } = {},
  showAssignee = false,
) =>
  render(
    <LocaleProvider locale="en">
      <ul>
        <TaskRow
          task={{ ...base, ...overrides }}
          tenant="pollux-motors"
          now={NOW}
          showAssignee={showAssignee}
          onComplete={handlers.onComplete ?? (() => {})}
          onSnooze={handlers.onSnooze ?? (() => {})}
          onSendDraft={async () => {}}
          onSkipDraft={async () => {}}
        />
      </ul>
    </LocaleProvider>,
  );

describe("TaskRow", () => {
  it("says what to do and who it is about", () => {
    show({});
    expect(screen.getByText(/Call Omar back/)).toBeDefined();
    expect(screen.getByRole("link", { name: "Omar Al Mazrouei" })).toBeDefined();
  });

  it("reads as overdue in words as well as in red", () => {
    const { container } = show({ due_at: new Date(NOW - 86_400_000).toISOString() });
    expect(screen.getByText("Overdue")).toBeDefined();
    expect(container.querySelector("[data-overdue='true']")).not.toBeNull();
  });

  it("completes once, and offers to be undone by completing back", () => {
    const onComplete = vi.fn();
    show({}, { onComplete });
    fireEvent.click(screen.getByRole("checkbox", { name: /mark as done/i }));
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith(true);
  });

  it("strikes through what is already done, and stops offering a snooze", () => {
    show({ status: "done", completed_at: new Date(NOW).toISOString() });
    expect(screen.queryByRole("combobox", { name: /snooze/i })).toBeNull();
    expect(screen.getByRole("checkbox", { name: /mark as done/i })).toHaveProperty("checked", true);
  });

  it("snoozes to an hour, tomorrow morning or next week", () => {
    const onSnooze = vi.fn();
    show({}, { onSnooze });
    fireEvent.change(screen.getByRole("combobox", { name: /snooze/i }), {
      target: { value: "snoozeTomorrow" },
    });
    const at = onSnooze.mock.calls[0][0] as Date;
    expect(at.getHours()).toBe(9);
    expect(at.getDate()).toBe(new Date(NOW).getDate() + 1);
  });

  it("marks a task the copilot wrote", () => {
    show({ source: "ai" });
    expect(screen.getByText("AI")).toBeDefined();
  });

  it("puts the AI follow-up draft under its task", () => {
    show({
      source: "ai",
      ai_draft: { reason: "Price dropped", text: "Good news, the price is lower." },
      conversation_id: "conversation-1",
    });
    expect(screen.getByText("Price dropped")).toBeDefined();
    expect(screen.getByText("Good news, the price is lower.")).toBeDefined();
  });

  it("renders a task with no customer without an empty link", () => {
    show({ contact: null });
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("names the assignee only in the team view", () => {
    show({}, {}, true);
    expect(screen.getByText("Ahmed Nasser")).toBeDefined();
  });
});

describe("snoozeOptions", () => {
  it("offers an hour from now, tomorrow at nine and next week at nine", () => {
    const options = snoozeOptions(new Date("2026-09-21T14:30:00"));
    expect(options.map((option) => option.key)).toEqual([
      "snoozeHour",
      "snoozeTomorrow",
      "snoozeWeek",
    ]);
    expect(options[0].at.getHours()).toBe(15);
    expect(options[1].at.getDate()).toBe(22);
    expect(options[2].at.getDate()).toBe(28);
  });
});
