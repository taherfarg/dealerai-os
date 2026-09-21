import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LeadCard } from "./LeadCard";
import type { Lead, Stage } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";

const NOW = new Date("2026-09-21T10:00:00Z").getTime();

const STAGES: Stage[] = [
  { id: "s1", name: "New", position: 0, category: "open" },
  { id: "s2", name: "Qualified", position: 1, category: "open" },
  { id: "s3", name: "Won", position: 2, category: "won" },
  { id: "s4", name: "Lost", position: 3, category: "lost" },
];

const base: Lead = {
  id: "l1",
  contact: { id: "k1", name: "Omar Al Mazrouei", country: "AE" },
  pipeline_id: "p1",
  pipeline_name: "Local sale",
  stage: STAGES[1],
  vehicle: { id: "v1", label: "Toyota Land Cruiser 2024" },
  budget: { amount_minor: 23500000, currency: "AED" },
  score: 78,
  band: "hot",
  owner: { id: "u1", name: "Ahmed Nasser", avatar_url: null },
  conversation_id: "c1",
  source: "whatsapp",
  lost_reason: null,
  stage_entered_at: new Date(NOW - 3 * 86_400_000).toISOString(),
  created_at: new Date(NOW - 9 * 86_400_000).toISOString(),
  next_action_at: null,
};

const show = (overrides: Partial<Lead>, handlers: { onMove?: (id: string) => void } = {}) =>
  render(
    <LocaleProvider locale="en">
      <ul>
        <LeadCard
          lead={{ ...base, ...overrides }}
          stages={STAGES}
          now={NOW}
          onOpen={() => {}}
          onMove={handlers.onMove ?? (() => {})}
        />
      </ul>
    </LocaleProvider>,
  );

describe("LeadCard", () => {
  it("says who, what car, how much and how long it has sat there", () => {
    show({});
    expect(screen.getByText(/Omar Al Mazrouei/)).toBeDefined();
    expect(screen.getByText("Toyota Land Cruiser 2024")).toBeDefined();
    expect(screen.getByText("AED 235,000")).toBeDefined();
    expect(screen.getByText("Ahmed Nasser")).toBeDefined();
    expect(screen.getByText("3 days here")).toBeDefined();
    expect(screen.getByText(/Hot 78/)).toBeDefined();
  });

  it("counts a lead moved a moment ago as zero days, not minus one", () => {
    // The clock ticks once a minute, so it can be a moment behind the move
    // that just happened — which Math.floor turns into -1.
    show({ stage_entered_at: new Date(NOW + 5_000).toISOString() });
    expect(screen.getByText("0 days here")).toBeDefined();
  });

  it("says a lead has no car rather than showing an empty line", () => {
    show({ vehicle: null });
    expect(screen.getByText(/no car chosen yet/i)).toBeDefined();
  });

  it("offers every stage of the board, so dragging is never the only way", () => {
    const onMove = vi.fn();
    show({}, { onMove });
    const menu = screen.getByRole("combobox", { name: /move to/i });
    expect([...menu.querySelectorAll("option")].map((option) => option.textContent)).toEqual([
      "New",
      "Qualified",
      "Won",
      "Lost",
    ]);
    fireEvent.change(menu, { target: { value: "s3" } });
    expect(onMove).toHaveBeenCalledWith("s3");
  });

  it("can be picked up", () => {
    const { container } = show({});
    expect(container.querySelector("[draggable='true'][data-lead='l1']")).not.toBeNull();
  });

  it("shows no band for a lead nobody has scored", () => {
    show({ band: null, score: null });
    expect(screen.queryByText(/hot|warm|cold/i)).toBeNull();
  });
});
