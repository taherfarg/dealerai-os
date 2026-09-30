import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { SignupForm } from "./SignupForm";

const state = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
  signUp: vi.fn(),
  search: "",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push, refresh: state.refresh }),
  useSearchParams: () => new URLSearchParams(state.search),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signUp: state.signUp } }),
}));

const CHECK_EMAIL = "Check your email: the link in it finishes creating your account.";

function show() {
  render(
    <LocaleProvider locale="en">
      <SignupForm />
    </LocaleProvider>,
  );
}

function signUp() {
  fireEvent.change(screen.getByLabelText("Your name"), { target: { value: " Layla Hassan " } });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "layla@pollux.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough" } });
  fireEvent.click(screen.getByRole("button", { name: "Create an account" }));
}

beforeEach(() => {
  state.push.mockReset();
  state.refresh.mockReset();
  state.signUp.mockReset();
  state.search = "";
});

describe("SignupForm", () => {
  it("asks Supabase for the account with the name, and a way back that keeps where they were going", async () => {
    state.search = "next=%2Faccept-invite%3Ftoken%3Dabc";
    state.signUp.mockResolvedValue({ data: { session: null, user: {} }, error: null });
    show();
    signUp();
    await waitFor(() =>
      expect(state.signUp).toHaveBeenCalledWith({
        email: "layla@pollux.test",
        password: "long enough",
        options: {
          data: { full_name: "Layla Hassan" },
          emailRedirectTo: `${window.location.origin}/auth/callback?next=%2Faccept-invite%3Ftoken%3Dabc`,
        },
      }),
    );
  });

  it.each([
    ["a new address", { identities: [{ id: "x" }] }],
    ["an address that already has an account", { identities: [] }],
  ])("says the same thing for %s", async (_, user) => {
    state.signUp.mockResolvedValue({ data: { session: null, user }, error: null });
    show();
    signUp();
    expect((await screen.findByRole("status")).textContent).toBe(CHECK_EMAIL);
    expect(screen.queryByRole("button", { name: "Create an account" })).toBeNull();
  });

  it("goes straight on when no confirmation is needed", async () => {
    state.search = "next=%2Fpollux-motors%2Finbox";
    state.signUp.mockResolvedValue({ data: { session: {}, user: {} }, error: null });
    show();
    signUp();
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/pollux-motors/inbox"));
  });

  it("fills in the invited address", () => {
    state.search = "email=layla%40pollux.test";
    show();
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("layla@pollux.test");
  });
});
