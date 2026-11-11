import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { SignOutButton } from "./SignOutButton";

const state = vi.hoisted(() => ({ calls: [] as string[], dev: false }));

vi.mock("@/lib/push", () => ({
  silenceThisDevice: async () => void state.calls.push("silence the device"),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: { signOut: async () => void state.calls.push("end the session") },
  }),
}));
vi.mock("@/lib/dev-auth", () => ({
  get DEV_AUTH() {
    return state.dev;
  },
}));

function signOut() {
  render(
    <LocaleProvider locale="en">
      <SignOutButton />
    </LocaleProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
}

beforeEach(() => {
  state.calls = [];
  state.dev = false;
  vi.stubGlobal("location", { assign: (path: string) => state.calls.push(`go to ${path}`) });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SignOutButton", () => {
  it("silences this device, ends the session, then leaves for the front door", async () => {
    signOut();
    // The order is the point: a phone that changes hands must stop showing the
    // last person's customers before anybody else can be signed in on it.
    await waitFor(() =>
      expect(state.calls).toEqual(["silence the device", "end the session", "go to /"]),
    );
  });

  it("clears the local session in dev mode, and leaves Supabase alone", async () => {
    state.dev = true;
    document.cookie = "dev_token=abc; path=/";
    signOut();
    await waitFor(() => expect(state.calls).toEqual(["silence the device", "go to /"]));
    expect(document.cookie).not.toContain("dev_token");
  });
});
