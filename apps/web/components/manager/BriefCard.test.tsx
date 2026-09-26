import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ManagerDashboard } from "@/lib/api/hooks";
import type { Locale } from "@/lib/i18n";
import { LocaleProvider } from "@/lib/i18n-client";
import { BriefCard } from "./BriefCard";

const brief: ManagerDashboard["brief"] = {
  date: "2026-09-25",
  headline: { en: "2 customers are past the target.", ar: "عميلان تجاوزا الهدف." },
  items: [
    {
      kind: "waiting",
      id: "conversation-1",
      name: "Omar",
      owner: { id: "ahmed", name: "Ahmed Nasser" },
      since: "2026-09-25T04:00:00Z",
      count: null,
    },
    {
      kind: "hot_lead",
      id: "lead-1",
      name: "Mona",
      owner: { id: "salem", name: "Salem Bousaid" },
      since: null,
      count: null,
    },
    { kind: "overdue_tasks", id: "mohamed", name: "Mohamed Riad", owner: null, since: null, count: 3 },
  ],
};

function show(locale: Locale, over: Partial<ManagerDashboard["brief"]> = {}) {
  render(
    <LocaleProvider locale={locale}>
      <BriefCard brief={{ ...brief, ...over }} tenant="pollux" />
    </LocaleProvider>,
  );
}

describe("BriefCard", () => {
  it("shows the headline in the reader's language", () => {
    show("ar");
    expect(screen.getByText("عميلان تجاوزا الهدف.")).toBeDefined();
    expect(screen.queryByText("2 customers are past the target.")).toBeNull();
  });

  it("still lists what needs doing when there is no headline", () => {
    show("en", { headline: null });
    expect(screen.getByText("This morning")).toBeDefined();
    expect(screen.getAllByRole("link")).toHaveLength(3);
  });

  it("links each item to what it is about", () => {
    show("en");
    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/pollux/inbox/conversation-1",
      "/pollux/pipeline?lead=lead-1",
      "/pollux/tasks?bucket=overdue&assignee=mohamed",
    ]);
  });

  it("says when nothing needs anybody", () => {
    show("en", { items: [] });
    expect(screen.getByText("Nothing needs you right now.")).toBeDefined();
  });
});
