import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProfileField, type Field } from "./ProfileField";
import { LocaleProvider } from "@/lib/i18n-client";

const show = (
  name: string,
  field: Field,
  handlers: Partial<Parameters<typeof ProfileField>[0]> = {},
) =>
  render(
    <LocaleProvider locale="en">
      <ProfileField
        name={name}
        field={field}
        onSave={handlers.onSave ?? (() => {})}
        onEvidence={handlers.onEvidence}
      />
    </LocaleProvider>,
  );

const ai = (value: unknown, evidence: string | null = "m1"): Field => ({
  value,
  source: "ai",
  evidence_message_id: evidence,
});

const mine = (value: unknown): Field => ({
  value,
  source: "human",
  evidence_message_id: null,
});

describe("ProfileField", () => {
  it("says a stored choice as a word, in the reader's language", () => {
    render(
      <LocaleProvider locale="ar">
        <ProfileField name="purchase_type" field={mine("local")} onSave={() => {}} />
      </LocaleProvider>,
    );
    expect(screen.getByRole("button", { name: "محلي" })).toBeDefined();
  });

  it("offers the choices as words, saves the code, and saves nothing when nothing changed", () => {
    const onSave = vi.fn();
    show("payment", mine("cash"), { onSave });
    fireEvent.click(screen.getByRole("button", { name: "Cash" }));
    expect(screen.getByRole("option", { name: "Finance" })).toBeDefined();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "cash" } });
    expect(onSave).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cash" }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "finance" } });
    expect(onSave).toHaveBeenCalledWith("finance");
  });

  it("marks a value the AI inferred, and leaves a person's unmarked", () => {
    const { container, unmount } = show("budget", ai({ amount_minor: 15000000, currency: "AED" }));
    expect(screen.getByText("AED 150,000")).toBeDefined();
    expect(screen.getByRole("button", { name: /open the message/i })).toBeDefined();
    expect(container.querySelector("[data-source='ai']")).not.toBeNull();
    unmount();

    show("budget", mine({ amount_minor: 14000000, currency: "AED" }));
    expect(screen.queryByRole("button", { name: /open the message/i })).toBeNull();
  });

  it("jumps to the message a value came from", () => {
    const onEvidence = vi.fn();
    show("interest", ai("Hilux"), { onEvidence });
    fireEvent.click(screen.getByRole("button", { name: /open the message/i }));
    expect(onEvidence).toHaveBeenCalledWith("m1");
  });

  it("offers no jump when the AI kept no evidence", () => {
    show("interest", ai("Hilux", null));
    expect(screen.getByRole("button", { name: /open the message/i })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("shows an empty field as a question rather than a blank", () => {
    show("timeline", null);
    expect(screen.getByRole("button", { name: /not known yet/i })).toBeDefined();
  });

  it("saves what was typed, and abandons on Escape", () => {
    const onSave = vi.fn();
    show("interest", ai("Hilux"), { onSave });
    fireEvent.click(screen.getByRole("button", { name: "Hilux" }));
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Escape" });
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Hilux" }));
    const input = screen.getByRole("textbox") as HTMLInputElement;
    input.value = "Land Cruiser";
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSave).toHaveBeenCalledWith("Land Cruiser");
  });

  it("clears a field when the text is emptied", () => {
    const onSave = vi.fn();
    show("timeline", mine("This week"), { onSave });
    fireEvent.click(screen.getByRole("button", { name: "This week" }));
    const input = screen.getByRole("textbox") as HTMLInputElement;
    input.value = "";
    fireEvent.blur(input);
    expect(onSave).toHaveBeenCalledWith(null);
  });

  it("offers the only two answers a choice has", () => {
    show("purchase_type", null);
    fireEvent.click(screen.getByRole("button", { name: /not known yet/i }));
    const options = screen.getAllByRole("option") as HTMLOptionElement[];
    expect(options.map((option) => option.textContent)).toEqual(["Not known yet", "Local", "Export"]);
    // Read as words, stored as the codes they always were.
    expect(options.map((option) => option.value)).toEqual(["", "local", "export"]);
  });

  it("hands a plain number to whoever is typing over a budget", () => {
    // "AED 235,000" in an editable box is how you get "AED 235,000228000".
    show("budget", ai({ amount_minor: 23500000, currency: "AED" }));
    fireEvent.click(screen.getByRole("button", { name: "AED 235,000" }));
    expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("235000");
  });

  it("reads a budget back as money, not as fils", () => {
    const onSave = vi.fn();
    show("budget", null, { onSave });
    fireEvent.click(screen.getByRole("button", { name: /not known yet/i }));
    const input = screen.getByRole("textbox") as HTMLInputElement;
    input.value = "235,000";
    fireEvent.blur(input);
    expect(onSave).toHaveBeenCalledWith({ amount_minor: 23500000 });
  });
});
