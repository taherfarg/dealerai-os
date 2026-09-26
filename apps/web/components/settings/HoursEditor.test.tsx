import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { badDays, HoursEditor, type Hours } from "./HoursEditor";

function show(value: Hours) {
  const onChange = vi.fn();
  render(
    <LocaleProvider locale="en">
      <HoursEditor value={value} onChange={onChange} />
    </LocaleProvider>,
  );
  return onChange;
}

describe("HoursEditor", () => {
  it("switching a day off removes it from the week", () => {
    const onChange = show({
      mon: { open: "09:00:00", close: "21:00:00" },
      tue: { open: "09:00:00", close: "21:00:00" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Monday" }));
    expect(onChange).toHaveBeenCalledWith({ tue: { open: "09:00:00", close: "21:00:00" } });
  });

  it("says a week without hours is always open", () => {
    show({});
    expect(screen.getByText(/always open/)).toBeDefined();
    expect(screen.queryByRole("checkbox", { name: "Monday" })).toBeNull();
  });

  it("marks a day that closes before it opens", () => {
    show({ mon: { open: "18:00", close: "09:00" } });
    expect(screen.getByRole("alert").textContent).toMatch(/after opening/);
  });
});

describe("a day that closes before it opens", () => {
  it("is found whichever way the time is written", () => {
    expect(badDays({ mon: { open: "18:00:00", close: "09:00" }, tue: { open: "09:00", close: "21:00:00" } }))
      .toEqual(["mon"]);
  });
});
