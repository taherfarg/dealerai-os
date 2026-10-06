import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { ConversationList } from "./ConversationList";

const state = vi.hoisted(() => ({ conversationId: undefined as string | undefined }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ tenant: "pollux", conversationId: state.conversationId }),
  usePathname: () => "/pollux/inbox",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("@/lib/api/hooks", () => ({
  useMe: () => ({ data: { scope: "own" } }),
  useConversationCounts: () => ({ data: undefined }),
  useConversations: () => ({
    data: { pages: [{ data: [] }] },
    isPending: false,
    isError: false,
    isSuccess: true,
    hasNextPage: false,
  }),
}));

const show = () =>
  render(
    <LocaleProvider locale="en">
      <ConversationList />
    </LocaleProvider>,
  );

beforeEach(() => {
  state.conversationId = undefined;
});

describe("ConversationList", () => {
  it("has a heading to land on, which the eye does not need: the tabs already say where one is", () => {
    show();
    const heading = screen.getByRole("heading", { level: 1, name: "Inbox" });
    expect(heading.className).toContain("sr-only");
  });

  it("steps down a level beside an open conversation, whose customer is the page's heading", () => {
    state.conversationId = "conversation-1";
    show();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    expect(screen.getByRole("heading", { level: 2, name: "Inbox" })).toBeDefined();
  });
});
