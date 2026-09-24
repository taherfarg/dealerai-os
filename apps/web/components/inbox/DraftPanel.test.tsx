import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import type { Suggestion } from "@/lib/api/hooks";
import { DraftPanel } from "./DraftPanel";

const ready: Suggestion = {
  id: "draft-1",
  conversation_id: "conversation-1",
  for_message_id: "message-1",
  status: "ready",
  text: "The Land Cruiser is available for AED 170,000.",
  template: null,
  language: "en",
  confidence: "low",
  intent: "price",
  sources: [],
  actions: [],
  needs_human: "Customer asked for a final price",
  blocked_reason: null,
  created_at: "2026-09-23T10:00:00Z",
};

const onSend = vi.fn();
const onEdit = vi.fn();
const onRegenerate = vi.fn();
const onOutcome = vi.fn();

function show(suggestion: Suggestion = ready) {
  return render(
    <LocaleProvider locale="en">
      <DraftPanel
        suggestion={suggestion}
        onSend={onSend}
        onEdit={onEdit}
        onRegenerate={onRegenerate}
        onOutcome={onOutcome}
      />
    </LocaleProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("DraftPanel", () => {
  it("never sends a draft by itself", () => {
    show();
    expect(screen.getByText(ready.text!)).toBeDefined();
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Send draft" }));
    expect(onSend).toHaveBeenCalledExactlyOnceWith(ready);
  });

  it("shows low confidence and why a person must decide", () => {
    show();
    expect(screen.getByText("Low confidence")).toBeDefined();
    expect(screen.getByText("Price")).toBeDefined(); // the intent, in words
    expect(screen.getByText("Customer asked for a final price").getAttribute("dir")).toBe("auto");
    expect(screen.getByText("Customer asked for a final price")).toBeDefined();
  });

  it("shows a blocked draft's reason without a send button", () => {
    show({ ...ready, status: "blocked", text: null, blocked_reason: "Price is not ours" });
    expect(screen.getByText(/Price is not ours/)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Send draft" })).toBeNull();
  });

  it("shows a template's message, not its name", () => {
    show({
      ...ready,
      text: null,
      template: {
        template_id: "t-1",
        name: "vehicle_available",
        variables: ["Hilux", "AED 128,000"],
        preview: "Le véhicule Hilux est disponible à AED 128,000.",
      },
    });
    expect(screen.getByText("Le véhicule Hilux est disponible à AED 128,000.")).toBeDefined();
  });

  it("shows nothing for a superseded draft", () => {
    const { container } = show({ ...ready, status: "superseded" });
    expect(container.firstChild).toBeNull();
  });

  it("names the vehicle and reveals the supporting document paragraph", () => {
    show({
      ...ready,
      sources: [
        { kind: "vehicle", vehicle_id: "car-1", label: "Toyota Land Cruiser 2023" },
        {
          kind: "document",
          document_id: "doc-1",
          title: "Export policy",
          section: "Export › Customs — Algeria",
          excerpt: "Ship to Algeria",
        },
      ],
    });
    expect(screen.getByText("Toyota Land Cruiser 2023")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Export policy · Customs — Algeria" }));
    expect(screen.getByText("Ship to Algeria")).toBeDefined();
  });

  it("warns when a fact-bearing reply has no source", () => {
    show();
    expect(screen.getByText(/No sources were attached/)).toBeDefined();
  });

  it("asks for a reason before dismissing", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.getByRole("button", { name: "Wrong information" })).toBeDefined();
    expect(onOutcome).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Wrong information" }));
    expect(onOutcome).toHaveBeenCalledExactlyOnceWith(ready.id, "wrong_info");
  });

  it("remembers being collapsed", () => {
    const confident = { ...ready, confidence: "high" as const };
    const first = show(confident);
    fireEvent.click(screen.getByRole("button", { name: "Collapse draft" }));
    expect(screen.queryByText(ready.text!)).toBeNull();
    first.unmount();
    show(confident);
    expect(screen.queryByText(ready.text!)).toBeNull();
  });

  it("will not fold away a low-confidence draft, even one remembered as collapsed", () => {
    localStorage.setItem("dealerai:draft-collapsed", "true");
    show();
    expect(screen.getByText(ready.text!)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Collapse draft" })).toBeNull();
  });

  it("opens in a browser that forbids storage", () => {
    // Private windows throw on localStorage. The inbox must still open.
    const denied = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    show();
    expect(screen.getByText(ready.text!)).toBeDefined();
    denied.mockRestore();
  });

  it("sends on Alt+Enter, once for a held key", () => {
    show();
    fireEvent.keyDown(window, { key: "Enter", altKey: true });
    fireEvent.keyDown(window, { key: "Enter", altKey: true, repeat: true });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(onSend).toHaveBeenCalledExactlyOnceWith(ready);
  });
});
