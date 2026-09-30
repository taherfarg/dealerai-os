import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { LocaleProvider } from "@/lib/i18n-client";
import { InviteForm } from "./InviteForm";

const state = vi.hoisted(() => ({ calls: [] as unknown[], error: null as unknown }));
vi.mock("@/lib/api/hooks", () => ({
  useMe: () => ({ data: { role: "admin", tenant: { timezone: "Asia/Dubai" } } }),
  useTeams: () => ({
    data: [
      { id: "local", name: "Local sales", member_ids: [] },
      { id: "export", name: "Export", member_ids: [] },
    ],
  }),
  useInvite: () => ({
    isPending: false,
    isError: state.error !== null,
    error: state.error,
    mutate: (
      body: { role: string },
      options: { onSuccess: (invitation: object) => void },
    ) => {
      state.calls.push(body);
      if (state.error === null) {
        options.onSuccess({ token: "tok", expires_at: "2026-10-07T12:00:00Z", role: body.role });
      }
    },
  }),
}));

function show() {
  render(
    <LocaleProvider locale="en">
      <InviteForm />
    </LocaleProvider>,
  );
}

function invite() {
  fireEvent.change(screen.getByLabelText("Their email"), {
    target: { value: "layla@pollux.test" },
  });
  fireEvent.click(screen.getByLabelText("Local sales"));
  fireEvent.click(screen.getByRole("button", { name: "Create invitation link" }));
}

const LINK = `${window.location.origin}/accept-invite?token=tok`;

beforeEach(() => {
  state.calls = [];
  state.error = null;
});

describe("InviteForm", () => {
  it("offers no role above the inviter's own", () => {
    show();
    const roles = [...(screen.getByLabelText("Role") as HTMLSelectElement).options].map(
      (option) => option.value,
    );
    expect(roles).toEqual(["admin", "manager", "sales", "viewer"]);
  });

  it("sends the address, a salesperson by default, and the teams ticked", () => {
    show();
    invite();
    expect(state.calls).toEqual([
      { email: "layla@pollux.test", role: "sales", team_ids: ["local"] },
    ]);
  });

  it("makes a link out of the token", () => {
    show();
    invite();
    const field = screen.getByDisplayValue(LINK);
    expect(field.getAttribute("readonly")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Copy link" })).toBeTruthy();
  });

  it("sends it on WhatsApp", () => {
    show();
    invite();
    expect(screen.getByRole("link", { name: "Send on WhatsApp" }).getAttribute("href")).toBe(
      `https://wa.me/?text=${encodeURIComponent(`You are invited to join us on DealerAI:\n${LINK}`)}`,
    );
  });

  it("shows the API's sentence when it refuses", () => {
    state.error = new ApiError({
      type: "forbidden",
      title: "Forbidden",
      status: 403,
      detail: "cannot grant 'owner': you are 'admin'",
    });
    show();
    invite();
    expect(screen.getByRole("alert").textContent).toBe("cannot grant 'owner': you are 'admin'");
  });
});
