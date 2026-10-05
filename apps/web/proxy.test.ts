import { describe, expect, it } from "vitest";
import { config, isPublic } from "./proxy";

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

describe("what somebody signed out may open", () => {
  it("is signing in, signing up, asking for a new password, the way back from an email, and an invitation", () => {
    for (const path of [
      "/login",
      "/signup",
      "/forgot-password",
      "/auth/callback",
      "/accept-invite",
    ]) {
      expect(isPublic(path), path).toBe(true);
    }
  });

  it("is not the new-password page: the link in the email signs them in first", () => {
    expect(isPublic("/reset-password")).toBe(false);
  });

  it("is nothing inside a workspace, nor the first one", () => {
    for (const path of ["/", "/onboarding", "/pollux-motors/inbox", "/pollux-motors/login"]) {
      expect(isPublic(path), path).toBe(false);
    }
  });
});
