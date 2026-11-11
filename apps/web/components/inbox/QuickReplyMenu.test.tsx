import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QuickReply } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { QuickReplyMenu } from "./QuickReplyMenu";

const price = {
  id: "reply-1",
  shortcut: "/price",
  title: "Today's price",
  body: { en: "Hello {name}", ar: null, fr: null },
} as QuickReply;

const show = (onPick = vi.fn()) => {
  render(
    <LocaleProvider locale="en">
      <QuickReplyMenu options={[price]} active={0} onPick={onPick} />
    </LocaleProvider>,
  );
  return onPick;
};

describe("QuickReplyMenu", () => {
  it("makes the option the control itself, with nothing to press inside it", () => {
    const onPick = show();
    const option = screen.getByRole("option", { name: /\/price/ });
    expect(option.querySelector("button, a, input")).toBeNull();
    expect(option.getAttribute("aria-selected")).toBe("true");
    fireEvent.click(option);
    expect(onPick).toHaveBeenCalledWith(price);
  });

  it("leaves the keyboard in the reply box when an option is pressed", () => {
    show();
    const down = createEvent.mouseDown(screen.getByRole("option"));
    fireEvent(screen.getByRole("option"), down);
    expect(down.defaultPrevented).toBe(true);
  });
});
