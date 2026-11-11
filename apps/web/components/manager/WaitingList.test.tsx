import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Conversation } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { WaitingList } from "./WaitingList";

vi.mock("@/lib/api/hooks", () => ({
  useMembers: () => ({ data: [] }),
  useAssignConversation: () => ({ mutate: vi.fn(), isPending: false }),
}));

const waiting = {
  id: "conversation-1",
  contact: { id: "customer-1", name: "James Whitfield", country: "AE" },
  assignee: null,
  waiting_since: new Date(Date.now() - 12 * 60_000).toISOString(),
  sla_state: "breached",
} as unknown as Conversation;

describe("WaitingList", () => {
  it("keeps room for who is waiting, however much else is on the row", () => {
    render(
      <LocaleProvider locale="ar">
        <WaitingList conversations={[waiting]} tenant="pollux" canAssign />
      </LocaleProvider>,
    );
    const name = screen.getByText("James Whitfield");
    // The name chooses its direction and is cut at its end; its row will not
    // shrink below a width a name can be read in.
    expect(name.getAttribute("dir")).toBe("auto");
    expect((name.parentElement as HTMLElement).className).toContain("min-w-24");
  });
});
