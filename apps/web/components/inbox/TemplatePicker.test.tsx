import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Template } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { TemplatePicker } from "./TemplatePicker";

const state = vi.hoisted(() => ({
  send: vi.fn(),
  templates: [] as unknown[],
}));
vi.mock("@/lib/api/hooks", () => ({
  useTemplates: () => ({ data: state.templates, isSuccess: true }),
  useSendMessage: () => ({ mutate: state.send, isPending: false, isError: false, error: null }),
}));

const template = (over: Partial<Template>): Template => {
  const made = {
    channel_id: "channel-1",
    external_id: "x",
    name: "price_update",
    language: "en_US",
    category: "utility",
    status: "approved",
    body: "Hello {{1}}, the {{2}} price is now {{3}}.",
    rejected_reason: null,
    synced_at: "2026-10-01T00:00:00Z",
    ...over,
  };
  return { ...made, id: `${made.name}-${made.language}` } as Template;
};

const TEMPLATES = [
  template({ language: "ar", body: "مرحباً {{1}}، سعر {{2}} الآن {{3}}." }),
  template({ language: "en_US" }),
  template({ language: "fr", body: "Bonjour {{1}}, le prix de {{2}} est maintenant {{3}}." }),
  template({
    name: "vehicle_available",
    language: "fr",
    body: "Le véhicule {{1}} est disponible à {{2}}.",
  }),
  template({
    name: "eid_offer",
    language: "fr",
    category: "marketing",
    body: "Offre de l'Aïd : {{1}}.",
  }),
  template({ name: "old_offer", language: "fr", status: "rejected", body: "Ancienne offre." }),
];

const show = (locale: "en" | "ar" = "en") =>
  render(
    <LocaleProvider locale={locale}>
      <TemplatePicker
        conversationId="conversation-1"
        channelId="channel-1"
        language="fr"
        customerName="Karim Benali"
      />
    </LocaleProvider>,
  );

const choose = (id: string) =>
  fireEvent.change(screen.getByRole("combobox"), { target: { value: id } });
const blank = (n: number) =>
  screen.getByRole("textbox", { name: `Blank ${n}` }) as HTMLInputElement;
const sendButton = () => screen.getByRole("button", { name: "Send template" });

beforeEach(() => {
  state.send.mockReset();
  state.templates = TEMPLATES;
});

describe("TemplatePicker", () => {
  it("offers the approved templates, the customer's language first", () => {
    show();
    const offered = (screen.getAllByRole("option") as HTMLOptionElement[]).map(
      (o) => o.textContent,
    );
    expect(offered).toEqual([
      "Choose a template",
      "price_update · French",
      "vehicle_available · French",
      "eid_offer · French",
      "price_update · Arabic",
      "price_update · English",
    ]);
    // One that WhatsApp has not approved cannot be sent, so it is not offered.
    expect(offered.join()).not.toContain("old_offer");
  });

  it("shows what will be sent, with what was typed", () => {
    show();
    choose("price_update-fr");
    const preview = screen
      .getByRole("group", { name: "What the customer will read" })
      .querySelector("p") as HTMLElement;
    expect(preview.textContent).toBe("Bonjour Karim, le prix de {{2}} est maintenant {{3}}.");
    expect(preview.getAttribute("dir")).toBe("auto");

    fireEvent.change(blank(2), { target: { value: "Toyota Hilux" } });
    expect(preview.textContent).toBe(
      "Bonjour Karim, le prix de Toyota Hilux est maintenant {{3}}.",
    );
  });

  it("puts the customer's first name where a greeting waits for it, and nowhere else", () => {
    show();
    choose("price_update-fr");
    expect(blank(1).value).toBe("Karim");
    // Here the first blank is the car: a name in it would be sent as one.
    choose("vehicle_available-fr");
    expect(blank(1).value).toBe("");
  });

  it("does not send with a blank left in it", () => {
    show();
    choose("price_update-fr");
    expect(sendButton().hasAttribute("disabled")).toBe(true);
    fireEvent.change(blank(2), { target: { value: "Toyota Hilux" } });
    fireEvent.change(blank(3), { target: { value: "   " } });
    expect(sendButton().hasAttribute("disabled")).toBe(true);
    fireEvent.change(blank(3), { target: { value: "AED 128,000" } });
    expect(sendButton().hasAttribute("disabled")).toBe(false);
  });

  it("sends the template and its variables, in order", () => {
    show();
    choose("price_update-fr");
    fireEvent.change(blank(2), { target: { value: " Toyota Hilux " } });
    fireEvent.change(blank(3), { target: { value: "AED 128,000" } });
    fireEvent.click(sendButton());
    expect(state.send).toHaveBeenCalledTimes(1);
    expect(state.send.mock.calls[0][0]).toEqual({
      templateId: "price_update-fr",
      variables: ["Karim", "Toyota Hilux", "AED 128,000"],
    });
  });

  it("says a template sent after the 24 hours is a paid message", () => {
    show();
    expect(screen.queryByText(/paid message/)).toBeNull();
    choose("eid_offer-fr");
    expect(screen.getByText(/paid message/)).toBeDefined();
  });

  it("says so, in the reader's language, when nothing is approved yet", () => {
    state.templates = [template({ status: "pending" })];
    show("ar");
    expect(screen.getByText(/لا توجد قوالب معتمدة بعد/)).toBeDefined();
    expect(screen.queryByRole("combobox")).toBeNull();
  });
});
