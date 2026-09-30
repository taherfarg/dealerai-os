import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { LocaleProvider } from "@/lib/i18n-client";
import { JoinInvitation } from "./JoinInvitation";

const state = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
  accept: vi.fn(),
  email: null as string | null,
  devAuth: false,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push, refresh: state.refresh }),
}));
vi.mock("@/lib/auth/token", () => ({ signedInEmail: () => Promise.resolve(state.email) }));
vi.mock("@/lib/api/joining", () => ({ acceptInvitation: state.accept }));
vi.mock("@/lib/dev-auth", () => ({
  get DEV_AUTH() {
    return state.devAuth;
  },
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signOut: vi.fn() } }),
}));

function tokenWith(claims: object): string {
  const bytes = new TextEncoder().encode(JSON.stringify(claims));
  const base64 = btoa(String.fromCharCode(...bytes));
  return `h.${base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}.s`;
}

const INVITED = "layla@pollux.test";
const TOKEN = tokenWith({
  kind: "invite",
  tenant_name: "Pollux Motors",
  role: "sales",
  email: INVITED,
  exp: Date.now() / 1000 + 3600,
});
const BACK = encodeURIComponent(`/accept-invite?token=${encodeURIComponent(TOKEN)}`);

function show(token = TOKEN) {
  render(
    <LocaleProvider locale="en">
      <JoinInvitation token={token} />
    </LocaleProvider>,
  );
}

beforeEach(() => {
  state.push.mockReset();
  state.refresh.mockReset();
  state.accept.mockReset();
  state.email = null;
  state.devAuth = false;
});

describe("JoinInvitation", () => {
  it("shows a signed-out visitor both ways in, each keeping the invitation", async () => {
    show();
    const create = await screen.findByRole("link", { name: "Create an account with this email" });
    expect(create.getAttribute("href")).toBe(`/signup?email=${encodeURIComponent(INVITED)}&next=${BACK}`);
    expect(
      screen.getByRole("link", { name: "I already have an account" }).getAttribute("href"),
    ).toBe(`/login?next=${BACK}`);
    expect(screen.getByText("Pollux Motors")).toBeTruthy();
  });

  it("sends both ways in to the local sign-in when there is no Supabase Auth", async () => {
    state.devAuth = true;
    show();
    const create = await screen.findByRole("link", { name: "Create an account with this email" });
    expect(create.getAttribute("href")).toBe(`/dev-login?next=${BACK}`);
  });

  it("says whose invitation it is when somebody else is signed in", async () => {
    state.email = "someone.else@pollux.test";
    show();
    expect(
      await screen.findByRole("button", { name: "Sign out and use the invited email" }),
    ).toBeTruthy();
    expect(screen.getByText(INVITED)).toBeTruthy();
    expect(screen.getByText("someone.else@pollux.test")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Join" })).toBeNull();
  });

  it("joins and opens the inbox", async () => {
    state.email = INVITED;
    state.accept.mockResolvedValue({ tenant_slug: "pollux-motors", role: "sales" });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Join" }));
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/pollux-motors/inbox"));
    expect(state.accept).toHaveBeenCalledWith(TOKEN);
  });

  it("shows the API's sentence when joining is refused", async () => {
    state.email = INVITED;
    state.accept.mockRejectedValue(
      new ApiError({
        type: "forbidden",
        title: "Forbidden",
        status: 403,
        detail: "this invitation is for another email address",
      }),
    );
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Join" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "this invitation is for another email address",
    );
  });

  it("does not offer to join an expired invitation", () => {
    show(tokenWith({ kind: "invite", tenant_name: "Pollux Motors", role: "sales", email: INVITED, exp: 1 }));
    expect(screen.getByRole("alert").textContent).toBe(
      "This invitation has expired. Ask whoever sent it for a new one.",
    );
    expect(screen.queryByRole("button", { name: "Join" })).toBeNull();
  });

  it("says so when the link is not an invitation", () => {
    show("garbage");
    expect(screen.getByRole("alert").textContent).toBe("This link is not an invitation.");
  });
});
