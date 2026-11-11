import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import SettingsLayout from "./layout";

vi.mock("next/navigation", () => ({ usePathname: () => "/pollux/settings/team" }));
vi.mock("@/lib/api/hooks", () => ({
  // A salesperson: quick replies and notifications, and nothing about the team.
  useMe: () => ({ data: { permissions: ["inbox.send"] } }),
}));
vi.mock("@/components/NavLinks", () => ({ NavLinks: () => null }));
vi.mock("@/components/SignOutButton", () => ({ SignOutButton: () => null }));

describe("SettingsLayout", () => {
  it("says a section is not theirs under a heading, and names its list of sections", async () => {
    await act(async () => {
      render(
        <LocaleProvider locale="en">
          <Suspense>
            <SettingsLayout params={Promise.resolve({ tenant: "pollux" })}>
              <p>the team</p>
            </SettingsLayout>
          </Suspense>
        </LocaleProvider>,
      );
    });
    expect(screen.queryByText("the team")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeDefined();
    expect(screen.getByRole("navigation", { name: "Settings" })).toBeDefined();
  });
});
