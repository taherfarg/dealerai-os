import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { ContentCalendar } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { Calendar, dayLoad } from "./Calendar";
import { addDays, span, step, weekStart } from "./calendarDates";

vi.mock("@/lib/api/context", () => ({
  useTenantApi: () => ({ api: {}, tenantId: "t1", header: {} }),
}));

describe("calendar dates", () => {
  it("counts in whole days, whatever the clocks do", () => {
    expect(addDays("2026-03-28", 2)).toBe("2026-03-30");
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
  });

  it("starts a week on Monday and a month on the Monday of its first week", () => {
    expect(weekStart("2026-11-07")).toBe("2026-11-02"); // a Saturday
    expect(weekStart("2026-11-02")).toBe("2026-11-02");
    expect(span("week", "2026-11-07")).toEqual(["2026-11-02", "2026-11-08"]);
    expect(span("month", "2026-11-07")).toEqual(["2026-10-26", "2026-11-30"]);
  });

  it("steps a week or a month at a time", () => {
    expect(step("week", "2026-11-07", 1)).toBe("2026-11-09");
    expect(step("month", "2026-11-30", 1)).toBe("2026-12-01");
    expect(step("month", "2026-11-07", -1)).toBe("2026-10-01");
  });
});

const calendar: ContentCalendar = {
  timezone: "Asia/Dubai",
  max_posts_per_day: 1,
  quiet_hours: ["23:00", "07:00"],
  days: [
    { date: "2026-11-09", count: 1, full: true },
    { date: "2026-11-10", count: 0, full: false },
  ],
  items: [
    {
      id: "p1",
      kind: "post",
      concept: "just_arrived",
      status: "scheduled",
      vehicle_id: "v1",
      run_id: "r1",
      created_at: "2026-11-06T10:00:00Z",
      locales: ["en"],
      assets: 1,
      vehicle: "2026 BYD Leopard 7 Ultra",
      local_date: "2026-11-09",
      local_time: "10:00",
    },
  ],
  gaps: ["2026-11-10"],
  unscheduled: [],
};

function wrap(children: ReactNode) {
  return (
    <QueryClientProvider client={new QueryClient()}>
      <LocaleProvider locale="en">{children}</LocaleProvider>
    </QueryClientProvider>
  );
}

describe("the calendar", () => {
  it("reads a day against its limit", () => {
    expect(dayLoad(1, 4)).toBe("1/4");
    expect(dayLoad(3, null)).toBe("3");
  });

  it("puts each piece on its own day, marks a full day and a gap, and lets it be dragged", () => {
    const { container } = render(
      wrap(<Calendar calendar={calendar} tenant="pollux" canSchedule compact={false} />),
    );
    expect(screen.getByText("1/1")).toBeTruthy();
    expect(screen.getByText("Nothing going out")).toBeTruthy();
    expect(screen.getByText("10:00", { exact: false })).toBeTruthy();
    expect(container.querySelector("[draggable='true'][data-piece='p1']")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Move…" })).toBeTruthy();
  });

  it("is only looked at by someone who may not schedule", () => {
    const { container } = render(
      wrap(<Calendar calendar={calendar} tenant="pollux" canSchedule={false} compact={false} />),
    );
    expect(container.querySelector("[draggable='true']")).toBeNull();
    expect(screen.queryByRole("button", { name: "Move…" })).toBeNull();
  });
});
