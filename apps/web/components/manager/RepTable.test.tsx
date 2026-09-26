import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Conversation, RepRow } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { RepTable } from "./RepTable";

function rep(id: string, name: string, overdue: number): RepRow {
  return {
    user: { id, name, avatar_url: null },
    open: 2,
    waiting: 1,
    median_first_response_seconds: 240,
    missed_targets: 0,
    overdue_tasks: overdue,
    hot: 1,
    warm: 0,
    cold: 0,
    won_this_month: 0,
  };
}

// Only the fields the table reads; the rest of a conversation is the inbox's.
const karim = {
  id: "conversation-1",
  contact: { name: "Karim" },
  assignee: { id: "salem", name: "Salem Bousaid" },
} as unknown as Conversation;

describe("RepTable", () => {
  it("opens a person to show who is waiting on them and where their overdue tasks are", () => {
    render(
      <LocaleProvider locale="en">
        <RepTable
          team={[rep("salem", "Salem Bousaid", 4), rep("ahmed", "Ahmed Nasser", 0)]}
          waiting={[karim]}
          target={300}
          tenant="pollux"
        />
      </LocaleProvider>,
    );
    // The table and the phone's cards are both in the DOM; CSS picks one.
    fireEvent.click(screen.getAllByRole("button", { name: "Salem Bousaid" })[0]);
    expect(screen.getAllByRole("link", { name: "Karim" })[0].getAttribute("href")).toBe(
      "/pollux/inbox/conversation-1",
    );
    expect(
      screen.getAllByRole("link", { name: /Their overdue tasks/ })[0].getAttribute("href"),
    ).toBe("/pollux/tasks?bucket=overdue&assignee=salem");
  });

  it("keeps a person closed until they are opened", () => {
    render(
      <LocaleProvider locale="en">
        <RepTable team={[rep("salem", "Salem Bousaid", 4)]} waiting={[karim]} target={300} tenant="pollux" />
      </LocaleProvider>,
    );
    expect(screen.queryByRole("link", { name: "Karim" })).toBeNull();
  });
});
