import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WaitingTimer } from "./WaitingTimer";
import { LocaleProvider } from "@/lib/i18n-client";

const NOW = Date.parse("2026-10-05T10:00:00Z");
const ago = (seconds: number) => new Date(NOW - seconds * 1000).toISOString();
const show = (seconds: number, state: "ok" | "due_soon" | "breached") =>
  render(
    <LocaleProvider locale="en">
      <WaitingTimer waitingSince={ago(seconds)} state={state} now={NOW} />
    </LocaleProvider>,
  );

describe("WaitingTimer", () => {
  it("counts in minutes once a minute has passed", () => {
    show(22 * 60 + 30, "breached");
    expect(screen.getByLabelText("Missed 22m")).toBeDefined();
  });

  it("counts the first minute in seconds", () => {
    show(45, "ok");
    expect(screen.getByLabelText("Waiting 45s")).toBeDefined();
  });

  it("says its state in a word and wears it: plain, then a warning, then danger", () => {
    expect(show(45, "ok").container.querySelector(".pill")?.className).toBe("pill ");
    expect(show(300, "due_soon").container.querySelector(".pill-warning")).not.toBeNull();
    expect(show(900, "breached").container.querySelector(".pill-danger")).not.toBeNull();
  });
});
