import { describe, expect, it } from "vitest";
import { mayOpen } from "./sections";

describe("mayOpen", () => {
  it("keeps a salesperson out of a section typed into the address bar", () => {
    // The exit run: the nav hid Routing, and the typed URL showed the form.
    expect(mayOpen("/pollux-motors/settings/routing", [])).toBe(false);
  });

  it("lets anyone read the quick replies", () => {
    expect(mayOpen("/pollux-motors/settings/quick-replies", [])).toBe(true);
  });

  it("opens a section for the permission it needs", () => {
    expect(mayOpen("/pollux-motors/settings/routing", ["settings.routing"])).toBe(true);
  });

  it("does not decide before the permissions have loaded", () => {
    expect(mayOpen("/pollux-motors/settings/routing", undefined)).toBeUndefined();
  });
});
