import { describe, expect, it } from "vitest";
import { slugFrom } from "./slug";

describe("slugFrom", () => {
  it("makes an address out of a name", () => {
    expect(slugFrom("Pollux Motors")).toBe("pollux-motors");
    expect(slugFrom("  Al Futtaim & Sons, Dubai ")).toBe("al-futtaim-sons-dubai");
    expect(slugFrom("Citroën Café")).toBe("citroen-cafe");
  });
  it("leaves an Arabic name for the owner to spell", () => {
    expect(slugFrom("معرض بولكس")).toBe("");
  });
  it("stays inside the API's 60 characters", () => {
    expect(slugFrom("a".repeat(80))).toHaveLength(60);
    expect(slugFrom(`${"a".repeat(59)} b`)).toBe("a".repeat(59));
  });
});
