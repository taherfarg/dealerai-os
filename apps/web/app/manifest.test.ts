import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

  it("wears the app's own colour", () => {
    // Neither the manifest nor an icon drawn in code can read a CSS variable.
    // This is what keeps them in step with the palette.
    const here = (file: string) => readFileSync(resolve(__dirname, file), "utf-8");
    const accent = /--accent:\s*(#[0-9a-f]{6})/.exec(here("./globals.css"))?.[1];
    expect(accent).toBeTruthy();
    expect(manifest().theme_color).toBe(accent);
    expect(manifest().background_color).toBe(accent);
    for (const icon of ["./icon.tsx", "./apple-icon.tsx"]) {
      expect(here(icon)).toContain(`background: "${accent}"`);
    }
  });
});
