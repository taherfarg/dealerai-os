import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";

afterEach(() => vi.restoreAllMocks());

const show = (onClose = vi.fn()) => {
  const view = render(
    <Modal title="Delete this customer for good" onClose={onClose}>
      <p>Their conversations go with them.</p>
      <button type="button">Cancel</button>
    </Modal>,
  );
  return { onClose, ...view };
};

describe("Modal", () => {
  it("opens as a modal and is named by its title", () => {
    const showModal = vi.spyOn(HTMLDialogElement.prototype, "showModal");
    show();
    expect(showModal).toHaveBeenCalledTimes(1);
    const dialog = screen.getByRole("dialog", { name: "Delete this customer for good" });
    expect(dialog.tagName).toBe("DIALOG");
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(
      "Delete this customer for good",
    );
  });

  it("closes on Escape, and says so rather than closing itself", () => {
    const { onClose } = show();
    const cancel = new Event("cancel", { cancelable: true });
    fireEvent(screen.getByRole("dialog"), cancel);
    expect(onClose).toHaveBeenCalledTimes(1);
    // Whether it is open is its owner's to decide: the browser must not close
    // a dialog React still believes is on screen.
    expect(cancel.defaultPrevented).toBe(true);
  });

  it("closes when its backdrop is pressed, not when its content is", () => {
    const { onClose } = show();
    fireEvent.click(screen.getByText("Their conversations go with them."));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).not.toHaveBeenCalled();
    // A press outside the box lands on the dialog element itself.
    fireEvent.click(screen.getByRole("dialog"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes the dialog when it leaves the page, which is what gives focus back", () => {
    const close = vi.spyOn(HTMLDialogElement.prototype, "close");
    const { unmount } = show();
    expect(close).not.toHaveBeenCalled();
    unmount();
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("can be named without a heading, when what it holds has its own", () => {
    render(
      <Modal label="Customer" variant="sheet" onClose={() => {}}>
        <h2>Omar Al Mazrouei</h2>
      </Modal>,
    );
    const sheet = screen.getByRole("dialog", { name: "Customer" });
    expect(sheet.className).toContain("h-dvh");
    expect(screen.getAllByRole("heading")).toHaveLength(1);
  });
});
