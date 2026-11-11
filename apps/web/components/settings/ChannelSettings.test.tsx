import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { ChannelSettings } from "./ChannelSettings";

vi.mock("@/lib/api/hooks", () => ({
  useMe: () => ({ data: { permissions: [] } }),
  useChannels: () => ({
    data: [
      {
        id: "channel-1",
        platform: "whatsapp",
        display_name: "Pollux WhatsApp",
        handle: null,
        mode: "cloud_api",
        status: "connected",
        quality_rating: "green",
      },
    ],
  }),
  useTemplates: () => ({
    data: [
      {
        id: "template-1",
        name: "price_update",
        language: "ar",
        category: "utility",
        status: "approved",
        rejected_reason: null,
      },
      {
        id: "template-2",
        name: "eid_offer",
        language: "ar",
        category: "marketing",
        // A status Meta added after this was written.
        status: "in_appeal",
        rejected_reason: null,
      },
    ],
  }),
  useSyncTemplates: () => ({ mutate: vi.fn(), isPending: false }),
}));

const show = (locale: "en" | "ar") =>
  render(
    <LocaleProvider locale={locale}>
      <ChannelSettings />
    </LocaleProvider>,
  );

describe("ChannelSettings", () => {
  it("says a channel's state and a template's in the reader's language", () => {
    show("ar");
    expect(screen.getByText(/متصلة/)).toBeDefined();
    expect(screen.getByText("خدمي · معتمد")).toBeDefined();
  });

  it("shows a status it has no word for as it is stored, rather than nothing", () => {
    show("ar");
    expect(screen.getByText("تسويقي · in_appeal")).toBeDefined();
  });

  it("puts the templates under a heading that follows the page's", () => {
    show("en");
    expect(screen.getByRole("heading", { level: 2, name: "Approved templates" })).toBeDefined();
  });
});
