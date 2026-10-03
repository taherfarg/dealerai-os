import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Shell } from "./Shell";

vi.mock("./AvailabilitySwitch", () => ({ AvailabilitySwitch: () => null }));
vi.mock("./LocaleToggle", () => ({ LocaleToggle: () => null }));
vi.mock("./NavLinks", () => ({ NavLinks: () => null }));
vi.mock("./NotificationsBell", () => ({ NotificationsBell: () => null }));
vi.mock("./WorkspaceSwitcher", () => ({ WorkspaceSwitcher: () => null }));

const pollux = { id: "tenant-1", slug: "pollux", name: "Pollux Motors" };

describe("Shell", () => {
  it("names its navigation, so it is told apart from a page's own", () => {
    render(
      <Shell tenant={pollux} tenants={[pollux]} locale="ar" pendingApprovals={0}>
        <p>page</p>
      </Shell>,
    );
    // The same list twice — beside the page on a desk, under it on a phone —
    // and CSS shows one of them.
    const navigations = screen.getAllByRole("navigation", { name: "القائمة الرئيسية" });
    expect(navigations).toHaveLength(2);
    expect(screen.getAllByRole("main")).toHaveLength(1);
  });
});
