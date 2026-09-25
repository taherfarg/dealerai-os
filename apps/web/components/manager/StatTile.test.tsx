import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatTile, tone } from "./StatTile";

describe("the colour of a median", () => {
  it("is green within the target, amber within twice it, red beyond", () => {
    expect(tone(299, 300)).toBe("ok");
    expect(tone(300, 300)).toBe("ok");
    expect(tone(599, 300)).toBe("warn");
    expect(tone(601, 300)).toBe("bad");
  });

  it("is nothing before anything was answered", () => {
    expect(tone(null, 300)).toBeNull();
  });
});

describe("a tile", () => {
  it("opens the list it counted", () => {
    render(<StatTile label="Hot leads" value="4" href="/pollux/customers?band=hot" />);
    expect(screen.getByRole("link").getAttribute("href")).toBe("/pollux/customers?band=hot");
  });

  it("says the target in words, not only in colour", () => {
    render(<StatTile label="Median first reply" value="4m" hint="target 5m" tone="ok" />);
    expect(screen.getByText("target 5m")).toBeDefined();
    expect(screen.queryByRole("link")).toBeNull();
  });
});
