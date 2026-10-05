import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AccountMenu } from "./AccountMenu";
import { LocaleProvider } from "@/lib/i18n-client";

vi.mock("@/lib/api/hooks", () => ({
  useMe: () => ({ data: { user: { id: "u1", name: "Sara Mansour" } } }),
}));

const show = () =>
  render(
    <LocaleProvider locale="en">
      <AccountMenu>
        <p>what the shell put inside</p>
      </AccountMenu>
    </LocaleProvider>,
  );

describe("AccountMenu", () => {
  it("is a button with a name, showing whose account it is", () => {
    show();
    expect(screen.getByRole("button", { name: "Your account" }).textContent).toBe("SM");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens a dialog with the person's name and what it was given, and closes again", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Your account" }));
    const dialog = screen.getByRole("dialog", { name: "Your account" });
    expect(dialog.textContent).toContain("Sara Mansour");
    expect(dialog.textContent).toContain("what the shell put inside");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
