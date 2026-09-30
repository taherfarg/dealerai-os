import { describe, expect, it } from "vitest";
import { safeNext } from "./next";

describe("safeNext", () => {
  it("keeps a path in this app", () => {
    expect(safeNext("/accept-invite?token=abc")).toBe("/accept-invite?token=abc");
  });
  it.each(["//evil.example", "/\\evil.example", "https://evil.example", "evil", "", null])(
    "sends %s home: a sign-in must not be a way to send somebody elsewhere",
    (value) => {
      expect(safeNext(value)).toBe("/");
    },
  );
});
