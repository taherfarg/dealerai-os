import { describe, expect, it } from "vitest";
import { config } from "./proxy";

/** The matcher is a regular expression kept in a string. A too-greedy
 *  exclusion would open pages to a signed-out visitor, so it is pinned. */
const gated = (path: string) => new RegExp(`^${config.matcher[0]}$`).test(path);

describe("the gate's matcher", () => {
  it("lets a browser fetch what makes the app installable", () => {
    for (const path of [
      "/manifest.webmanifest",
      "/sw.js",
      "/offline.html",
      "/icon/192",
      "/icon/512",
      "/apple-icon",
    ]) {
      expect(gated(path), path).toBe(false);
    }
  });

  it("still gates every page", () => {
    for (const path of [
      "/",
      "/pollux-motors/inbox",
      "/pollux-motors/settings/notifications",
      "/icon-motors/inbox",
      "/icons",
      "/icon/inbox",
      "/apple-icon-cars/settings",
      "/pollux-motors/sw.js/anything",
    ]) {
      expect(gated(path), path).toBe(true);
    }
  });
});
