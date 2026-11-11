import { describe, expect, it } from "vitest";
import { TINTS, initials, tint } from "./avatar";

describe("initials", () => {
  it("takes the first letter of the first word and of the last", () => {
    expect(initials("Omar Al Mazrouei")).toBe("OM");
    expect(initials("  james   whitfield ")).toBe("JW");
  });

  it("takes one letter from one word", () => {
    expect(initials("Sara")).toBe("S");
  });

  it("takes one letter from an Arabic name: two would join and read as a word", () => {
    expect(initials("عمر المزروعي")).toBe("ع");
  });

  it("has nothing to say for nobody", () => {
    expect(initials(null)).toBe("");
    expect(initials("   ")).toBe("");
  });
});

describe("tint", () => {
  it("is the same for the same person, however the name was typed", () => {
    expect(tint("Omar Al Mazrouei")).toBe(tint("  omar al mazrouei "));
  });

  it("is always one of the seven", () => {
    for (const name of ["Omar Al Mazrouei", "Mona Fathy", "عمر", "", null]) {
      const chosen = tint(name);
      expect(Number.isInteger(chosen) && chosen >= 0 && chosen < TINTS).toBe(true);
    }
  });
});
