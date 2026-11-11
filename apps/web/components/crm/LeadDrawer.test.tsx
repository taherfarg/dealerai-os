import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { LeadDrawer } from "./LeadDrawer";

const lead = vi.hoisted(() => ({
  id: "lead-1",
  contact: { id: "customer-1", name: "James Whitfield", country: "AE" },
  stage: { id: "stage-1", name: "New", position: 0, category: "open" },
  vehicle: { id: "vehicle-1", label: "Toyota Hilux GR Sport 2025" },
  owner: null,
  budget: { amount_minor: 16500000, currency: "AED" },
  source: "whatsapp" as string | null,
  // Half past midnight on the first of October, in Dubai.
  created_at: "2026-09-30T20:30:00Z",
  lost_reason: null,
  score_reasons: [],
  conversation_id: null,
  history: [],
  tasks: [],
}));

vi.mock("@/lib/api/hooks", () => ({
  useMe: () => ({ data: { tenant: { timezone: "Asia/Dubai" } } }),
  useLead: () => ({ data: lead }),
}));

const show = (locale: "en" | "ar") =>
  render(
    <LocaleProvider locale={locale}>
      <LeadDrawer tenant="pollux" leadId="lead-1" stages={[]} onClose={() => {}} onMove={() => {}} />
    </LocaleProvider>,
  );

describe("LeadDrawer", () => {
  it("says where the lead came from as a word, in the reader's language", () => {
    show("ar");
    expect(screen.getByText("واتساب")).toBeDefined();
  });

  it("says when it was created in the workspace's time", () => {
    show("en");
    expect(screen.getByText("1 Oct 2026, 00:30")).toBeDefined();
  });
});
