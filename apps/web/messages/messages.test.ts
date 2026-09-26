import { describe, expect, it } from "vitest";
import { ar } from "./ar";
import { en } from "./en";

describe("message catalogue", () => {
  it("has a non-empty Arabic string for every English key", () => {
    const missing = Object.keys(en).filter((key) => !ar[key as keyof typeof ar]?.trim());
    expect(missing).toEqual([]);
  });

  it("does not ship an English sentence as the Arabic translation", () => {
    const untranslated = Object.keys(en).filter(
      (key) => ar[key as keyof typeof ar] === en[key as keyof typeof en],
    );
    expect(untranslated).toEqual([]);
  });
});
