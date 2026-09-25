import { describe, expect, it } from "vitest";
import type { QuickReply } from "@/lib/api/hooks";
import { filled, matching } from "./QuickReplyMenu";

const reply = (shortcut: string, body: QuickReply["body"]): QuickReply => ({
  id: shortcut,
  shortcut,
  title: shortcut.slice(1),
  body,
  updated_at: "2026-09-25T00:00:00Z",
});

const price = reply("/price", {
  en: "Hello {name}, it is AED 128,000.",
  ar: "مرحبا {name}، السعر 128,000 درهم.",
  fr: null,
});
const location = reply("/location", { en: "We are on Sheikh Zayed Road." });

describe("matching quick replies", () => {
  it("lists the replies whose shortcut starts with what was typed", () => {
    expect(matching([price, location], "/pr").map((r) => r.shortcut)).toEqual(["/price"]);
    expect(matching([price, location], "/").map((r) => r.shortcut)).toEqual([
      "/price",
      "/location",
    ]);
  });
});

describe("a quick reply, filled in", () => {
  it("is in the customer's language, with their first name", () => {
    expect(filled(price, "ar", "Omar Haddad")).toBe("مرحبا Omar، السعر 128,000 درهم.");
  });

  it("falls back to English, then to any language it has", () => {
    expect(filled(price, "fr", "Karim")).toBe("Hello Karim, it is AED 128,000.");
    expect(filled(reply("/salam", { ar: "السلام عليكم" }), "fr", null)).toBe("السلام عليكم");
  });

  it("reads a regional language code as its language", () => {
    expect(filled(price, "en_US", "James")).toBe("Hello James, it is AED 128,000.");
  });
});
