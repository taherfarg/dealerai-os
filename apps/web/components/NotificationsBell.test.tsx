import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NotificationsBell } from "./NotificationsBell";
import { TenantApiProvider } from "@/lib/api/context";
import type { components } from "@/lib/api/schema";
import { LocaleProvider } from "@/lib/i18n-client";

type Page = components["schemas"]["NotificationPage"];

let page: Page;
const marked: (string[] | "all")[] = [];

// The bell is a view of one query and one mutation. Faking those two is what
// lets the test say what the screen does with them; the rows themselves are
// the API's business, and its own tests cover those.
vi.mock("@/lib/api/hooks", () => ({
  useNotifications: () => ({ data: page }),
  useMarkNotificationsRead: () => ({
    mutate: (ids: string[] | "all") => {
      marked.push(ids);
      const read = (id: string) => ids === "all" || ids.includes(id);
      page = {
        data: page.data.map((row) =>
          read(row.id) ? { ...row, read_at: new Date().toISOString() } : row,
        ),
        unread: page.data.filter((row) => !row.read_at && !read(row.id)).length,
      };
    },
  }),
}));

const notification = (over: Partial<Page["data"][number]>): Page["data"][number] => ({
  id: "n1",
  kind: "assigned",
  title: "Assigned to you",
  body: "Omar Haddad",
  href: "/inbox/c1",
  entity: { type: "conversation", id: "c1" },
  read_at: null,
  created_at: new Date(Date.now() - 4 * 60_000).toISOString(),
  ...over,
});

const show = () =>
  render(
    <TenantApiProvider tenantId="t1" slug="pollux-motors">
      <LocaleProvider locale="en">
        <NotificationsBell />
      </LocaleProvider>
    </TenantApiProvider>,
  );

const bell = () => screen.getByRole("button", { name: /notifications/i });

beforeEach(() => {
  marked.length = 0;
  page = {
    data: [notification({}), notification({ id: "n2", title: "Still waiting", href: "/inbox/c2" })],
    unread: 2,
  };
});

describe("NotificationsBell", () => {
  it("says how many are waiting, and does not clear them for being looked at", () => {
    show();
    expect(bell().textContent).toContain("2");
    fireEvent.click(bell());
    expect(screen.getByText("Assigned to you")).toBeDefined();
    // Opening is not reading: the badge survives the look.
    expect(marked).toEqual([]);
    expect(bell().textContent).toContain("2");
  });

  it("reads the one you act on, and takes you to it", () => {
    show();
    fireEvent.click(bell());
    const link = screen.getByRole("link", { name: /Assigned to you/ });
    expect(link.getAttribute("href")).toBe("/pollux-motors/inbox/c1");
    fireEvent.click(link);
    expect(marked).toEqual([["n1"]]);
  });

  it("clears the badge when you say so, and keeps the record", () => {
    const view = show();
    fireEvent.click(bell());
    fireEvent.click(screen.getByRole("button", { name: /mark all read/i }));
    expect(marked).toEqual(["all"]);
    view.rerender(
      <TenantApiProvider tenantId="t1" slug="pollux-motors">
        <LocaleProvider locale="en">
          <NotificationsBell />
        </LocaleProvider>
      </TenantApiProvider>,
    );
    expect(bell().textContent).not.toContain("2");
    // What you were told stays readable — it is the record of it.
    expect(screen.getByText("Assigned to you")).toBeDefined();
    expect(screen.queryByRole("button", { name: /mark all read/i })).toBeNull();
  });

  it("says there is nothing rather than opening an empty box", () => {
    page = { data: [], unread: 0 };
    show();
    fireEvent.click(bell());
    expect(screen.getByText(/nothing new/i)).toBeDefined();
  });
});
