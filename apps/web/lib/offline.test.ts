import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// __dirname, not import.meta.url: under jsdom that is not a file: address.
const PAGE = readFileSync(resolve(__dirname, "../public/offline.html"), "utf-8");

describe("the page for no network", () => {
  it("is one landmark with one heading, like every other page", () => {
    const page = new DOMParser().parseFromString(PAGE, "text/html");
    const main = page.querySelectorAll("main");
    expect(main).toHaveLength(1);
    expect(main[0].querySelectorAll("h1")).toHaveLength(1);
    // Nothing a person reads sits outside it.
    expect([...page.body.children].map((child) => child.tagName)).toEqual(["MAIN"]);
  });

  it("still asks for nothing it would need a network for", () => {
    expect(PAGE).not.toMatch(/<script|<link|src=/);
  });
});
