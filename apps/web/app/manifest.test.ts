import { describe, expect, it } from "vitest";
import manifest from "./manifest";

describe("manifest", () => {
  it("is installable", () => {
    const app = manifest();
    expect(app.name).toBeTruthy();
    expect(app.start_url).toBe("/");
    expect(app.display).toBe("standalone");
    const icons = app.icons ?? [];
    expect(icons.every((icon) => icon.type === "image/png")).toBe(true);
    expect(icons.map((icon) => icon.sizes)).toEqual(expect.arrayContaining(["192x192", "512x512"]));
    expect(icons.some((icon) => icon.purpose === "maskable")).toBe(true);
  });
});
