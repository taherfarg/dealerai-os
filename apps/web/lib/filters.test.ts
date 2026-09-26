import { describe, expect, it } from "vitest";
import { nextQuery, readFilters } from "./filters";

const DEFAULTS = { view: "all", band: "", q: "" };

describe("filters in the URL", () => {
  it("falls back to the defaults for anything the link does not say", () => {
    expect(readFilters(DEFAULTS, new URLSearchParams("band=hot"))).toEqual({
      view: "all",
      band: "hot",
      q: "",
    });
  });

  it("keeps an empty value somebody actually typed", () => {
    expect(readFilters(DEFAULTS, new URLSearchParams("view=")).view).toBe("");
  });

  it("writes a choice and leaves a default out of the link", () => {
    expect(nextQuery(DEFAULTS, new URLSearchParams(), { band: "hot" })).toBe("band=hot");
    expect(nextQuery(DEFAULTS, new URLSearchParams("band=hot"), { band: "all" })).toBe("band=all");
    expect(nextQuery(DEFAULTS, new URLSearchParams("band=hot"), { band: "" })).toBe("");
  });

  it("leaves parameters it knows nothing about alone", () => {
    // The lead drawer lives in ?lead=, and changing a filter must not close it.
    const next = nextQuery(DEFAULTS, new URLSearchParams("lead=abc"), { band: "hot" });
    expect(new URLSearchParams(next).get("lead")).toBe("abc");
    expect(new URLSearchParams(next).get("band")).toBe("hot");
  });

  it("does not write the same filter twice", () => {
    const next = nextQuery(DEFAULTS, new URLSearchParams("band=warm"), { band: "hot" });
    expect(next).toBe("band=hot");
  });
});
