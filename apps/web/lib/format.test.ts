import { describe, expect, it } from "vitest";
import {
  countryFlag,
  countryName,
  formatDateTime,
  formatDue,
  formatDuration,
  formatMoney,
  formatRelative,
  formatUntil,
} from "./format";

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
    [59, "59s", "59 ث"],
    [130, "2m 10s", "2 د 10 ث"],
    [2331, "38m 51s", "38 د 51 ث"],
    [3600, "1h", "1 س"],
    [3720, "1h 2m", "1 س 2 د"],
    [82800, "23h", "23 س"],
  ])("%i seconds reads as %s, and as %s in Arabic", (seconds, english, arabic) => {
    expect(formatDuration(seconds, "en")).toBe(english);
    expect(formatDuration(seconds, "ar")).toBe(arabic);
  });
});

describe("formatRelative", () => {
  const now = new Date("2026-09-16T12:00:00Z");

  it.each([
    ["2026-09-16T11:41:00Z", "19m", "19 د"],
    ["2026-09-16T10:00:00Z", "2h", "2 س"],
    ["2026-09-13T12:00:00Z", "3d", "3 ي"],
  ])("%s was %s ago, and %s in Arabic", (iso, english, arabic) => {
    expect(formatRelative(iso, "en", now)).toBe(english);
    expect(formatRelative(iso, "ar", now)).toBe(arabic);
  });

  it("says under a minute without a sign in Arabic, where a sign is mirrored", () => {
    expect(formatRelative("2026-09-16T11:59:30Z", "en", now)).toBe("<1m");
    expect(formatRelative("2026-09-16T11:59:30Z", "ar", now)).toBe("الآن");
  });

  it("falls back to a date after a week, in the reader's language", () => {
    expect(formatRelative("2026-09-01T12:00:00Z", "en", now)).toBe("1 Sept");
    expect(formatRelative("2026-09-01T12:00:00Z", "ar", now)).toBe("1 سبتمبر");
  });

  it("does not run ahead of a clock that is a little behind", () => {
    expect(formatRelative("2026-09-16T12:05:00Z", "en", now)).toBe("<1m");
  });
});

describe("formatDue", () => {
  const now = new Date("2026-09-16T12:00:00Z");

  it("says how far ahead a moment is, rather than that it is now", () => {
    expect(formatDue("2026-09-16T15:00:00Z", "en", now)).toBe("in 3h");
    expect(formatDue("2026-09-16T15:00:00Z", "ar", now)).toBe("بعد 3 س");
    expect(formatDue("2026-09-18T12:00:00Z", "en", now)).toBe("in 2d");
  });

  it("reads like an age once the moment has passed", () => {
    expect(formatDue("2026-09-14T12:00:00Z", "en", now)).toBe("2d");
    expect(formatDue("2026-09-14T12:00:00Z", "ar", now)).toBe("2 ي");
  });

  it("is a date when it is more than a week away", () => {
    expect(formatDue("2026-10-01T12:00:00Z", "en", now)).toBe("1 Oct");
    expect(formatDue("2026-10-01T12:00:00Z", "ar", now)).toBe("1 أكتوبر");
  });
});

describe("formatUntil", () => {
  const now = new Date("2026-09-19T12:00:00Z");

  it("says how long is left, not how long ago it was", () => {
    expect(formatUntil("2026-09-20T08:00:00Z", "en", now)).toBe("20h");
    expect(formatUntil("2026-09-19T12:03:00Z", "en", now)).toBe("3m");
    expect(formatUntil("2026-09-20T08:00:00Z", "ar", now)).toBe("20 س");
  });

  it("does not count backwards once the moment has passed", () => {
    expect(formatUntil("2026-09-19T11:00:00Z", "en", now)).toBe("0m");
    expect(formatUntil("2026-09-19T11:00:00Z", "ar", now)).toBe("0 د");
  });
});

describe("formatDateTime", () => {
  // Half past eight in the evening in UTC is half past midnight, a day later, in Dubai.
  const iso = "2026-09-30T20:30:00Z";

  it("keeps a date in the workspace's time, not the viewer's", () => {
    expect(formatDateTime(iso, "Asia/Dubai", "en")).toBe("1 Oct 2026, 00:30");
  });

  it("says it the reader's way, with digits anybody reads", () => {
    // Arabic writes this date in figures — 01/10/2026 — and the time with ص or م.
    const arabic = formatDateTime(iso, "Asia/Dubai", "ar");
    expect(arabic).toMatch(/[؀-ۿ]/);
    expect(arabic).toContain("2026");
    expect(arabic).not.toMatch(/[٠-٩]/);
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

describe("countryName", () => {
  it("says a country as a word, in the reader's language", () => {
    expect(countryName("ae", "en")).toBe("United Arab Emirates");
    expect(countryName("DZ", "ar")).toBe("الجزائر");
  });

  it("says nothing for what is not a country's code", () => {
    expect(countryName(null, "en")).toBe("");
    expect(countryName("Algeria", "en")).toBe("");
  });
});
