import { describe, expect, it } from "vitest";
import { countryFlag, formatUntil, formatDuration, formatMoney, formatRelative } from "./format";

describe("formatMoney", () => {
  it("shows whole dirhams without decimals", () => {
    expect(formatMoney({ amount_minor: 16500000, currency: "AED" })).toBe("AED 165,000");
  });

  it("keeps fils when there are some", () => {
    expect(formatMoney({ amount_minor: 16500050, currency: "AED" })).toBe("AED 165,000.50");
  });
});

describe("formatDuration", () => {
  it.each([
    [59, "59s"],
    [130, "2m 10s"],
    [3600, "1h"],
    [3720, "1h 2m"],
  ])("%i seconds reads as %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-09-16T12:00:00Z");

  it.each([
    ["2026-09-16T11:59:30Z", "<1m"],
    ["2026-09-16T11:57:00Z", "3m"],
    ["2026-09-16T09:00:00Z", "3h"],
    ["2026-09-14T12:00:00Z", "2d"],
  ])("%s is %s ago", (iso, expected) => {
    expect(formatRelative(iso, now)).toBe(expected);
  });

  it("falls back to a date after a week", () => {
    expect(formatRelative("2026-09-01T12:00:00Z", now)).toBe("1 Sept");
  });
});

describe("countryFlag", () => {
  it("turns an ISO code into a flag", () => {
    expect(countryFlag("dz")).toBe("🇩🇿");
  });

  it("returns nothing for junk rather than a broken glyph", () => {
    expect(countryFlag(null)).toBe("");
    expect(countryFlag("Algeria")).toBe("");
  });
});

describe("formatUntil", () => {
  const now = new Date("2026-09-19T12:00:00Z");

  it("says how long is left, not how long ago it was", () => {
    expect(formatUntil("2026-09-20T08:00:00Z", now)).toBe("20h");
    expect(formatUntil("2026-09-19T12:03:00Z", now)).toBe("3m");
  });

  it("does not count backwards once the moment has passed", () => {
    expect(formatUntil("2026-09-19T11:00:00Z", now)).toBe("0m");
  });
});
