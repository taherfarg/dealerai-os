import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextQuery, readFilters, useFilters } from "./filters";

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

// The page as it was last drawn: no filter chosen. The address moves on without it.
vi.mock("next/navigation", () => ({
  usePathname: () => "/pollux-motors/customers",
  useSearchParams: () => new URLSearchParams(""),
  useRouter: () => ({ replace: () => undefined }),
}));

describe("changing a filter", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/pollux-motors/customers");
  });

  it("is in the address at once, with nothing to wait for", () => {
    const { result } = renderHook(() => useFilters({ q: "", band: "" }));
    act(() => result.current[1]({ q: "Omar" }));
    expect(window.location.search).toBe("?q=Omar");
  });

  it("keeps the choice made a moment before, though the page has not been drawn again", () => {
    // A tab pressed and a search typed straight after it; letters typed faster
    // than the page redraws. The second change must build on the first.
    const { result } = renderHook(() => useFilters({ q: "", band: "" }));
    act(() => {
      result.current[1]({ band: "hot" });
      result.current[1]({ q: "Omar" });
    });
    expect(window.location.search).toBe("?band=hot&q=Omar");
  });

  it("takes a default back out of the address", () => {
    window.history.replaceState(null, "", "/pollux-motors/customers?q=Omar&band=hot");
    const { result } = renderHook(() => useFilters({ q: "", band: "" }));
    act(() => result.current[1]({ q: "" }));
    expect(window.location.search).toBe("?band=hot");
    act(() => result.current[1]({ band: "" }));
    expect(window.location.pathname + window.location.search).toBe("/pollux-motors/customers");
  });
});
