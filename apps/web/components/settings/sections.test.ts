import { describe, expect, it } from "vitest";
import { firstSection, mayOpen } from "./sections";

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

  it("lets anyone open their notifications", () => {
    expect(mayOpen("/pollux-motors/settings/notifications", [])).toBe(true);
  });
});

describe("firstSection", () => {
  it("still starts a salesperson on the quick replies", () => {
    expect(firstSection([]).href).toBe("/settings/quick-replies");
  });

  it("starts somebody who runs the place at the top", () => {
    expect(firstSection(["settings.channels", "settings.team"]).href).toBe("/settings/channels");
  });
});
