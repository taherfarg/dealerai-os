import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { CustomerDetail } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { EraseDialog } from "./EraseDialog";

const state = vi.hoisted(() => ({
  erase: vi.fn(),
  exportCopy: vi.fn(),
  error: null as unknown,
}));
vi.mock("@/lib/api/hooks", () => ({
  useEraseCustomer: () => ({
    mutate: state.erase,
    isPending: false,
    isError: state.error !== null,
    error: state.error,
  }),
  useExportCustomer: () => ({ mutate: state.exportCopy, isPending: false }),
}));

const omar = { id: "customer-1", name: "Omar Haddad" } as CustomerDetail;

function show(customer: CustomerDetail = omar) {
  const onErased = vi.fn();
  render(
    <LocaleProvider locale="en">
      <EraseDialog customer={customer} onClose={vi.fn()} onErased={onErased} />
    </LocaleProvider>,
  );
  return onErased;
}

const confirm = () => screen.getByRole("button", { name: "Delete for good" });

beforeEach(() => {
  state.erase.mockReset();
  state.exportCopy.mockReset();
  state.error = null;
});

describe("EraseDialog", () => {
  it("is a dialog, named by what it is about to do", () => {
    show();
    expect(
      screen.getByRole("dialog", { name: "Delete this customer for good" }).tagName,
    ).toBe("DIALOG");
  });

  it("keeps Delete disabled until the customer's name is typed", () => {
    show();
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "Omar" } });
    expect(confirm().hasAttribute("disabled")).toBe(true);
    fireEvent.change(box, { target: { value: "omar haddad" } });
    expect(confirm().hasAttribute("disabled")).toBe(false);
    fireEvent.click(confirm());
    expect(state.erase).toHaveBeenCalledTimes(1);
  });

  it("asks for the word delete when the customer has no name", () => {
    show({ ...omar, name: null });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "delete" } });
    expect(confirm().hasAttribute("disabled")).toBe(false);
  });

  it("offers the copy first", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Download a copy first" }));
    expect(state.exportCopy).toHaveBeenCalledTimes(1);
  });

  it("shows the API's sentence when it is refused", () => {
    state.error = new ApiError({
      type: "forbidden",
      title: "Forbidden",
      status: 403,
      detail: "this action requires the admin role or higher",
    });
    show();
    expect(screen.getByRole("alert").textContent).toBe(
      "this action requires the admin role or higher",
    );
  });
});
