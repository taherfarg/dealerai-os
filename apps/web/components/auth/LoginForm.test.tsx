import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { LoginForm } from "./LoginForm";

const state = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
  signIn: vi.fn(),
  search: "",
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push, refresh: state.refresh }),
  useSearchParams: () => new URLSearchParams(state.search),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { signInWithPassword: state.signIn } }),
}));

function show(locale: "en" | "ar" = "en") {
  render(
    <LocaleProvider locale={locale}>
      <LoginForm />
    </LocaleProvider>,
  );
}

function signIn() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "sara@pollux.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct horse" } });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

beforeEach(() => {
  state.push.mockReset();
  state.refresh.mockReset();
  state.signIn.mockReset();
  state.search = "";
});

describe("LoginForm", () => {
  it("labels itself in Arabic", () => {
    show("ar");
    expect(screen.getByLabelText("البريد الإلكتروني")).toBeTruthy();
    expect(screen.getByRole("button", { name: "تسجيل الدخول" })).toBeTruthy();
  });

  it("says it did not work in its own words, without saying which half was wrong", async () => {
    state.signIn.mockResolvedValue({ error: { message: "Invalid login credentials" } });
    show();
    signIn();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "That did not sign you in. Check the email and the password, and try again.",
    );
    expect(state.push).not.toHaveBeenCalled();
  });

  it("says so in Arabic to somebody reading Arabic, not in Supabase's English", async () => {
    state.signIn.mockResolvedValue({ error: { message: "Invalid login credentials" } });
    show("ar");
    fireEvent.change(screen.getByLabelText("البريد الإلكتروني"), {
      target: { value: "sara@pollux.test" },
    });
    fireEvent.change(screen.getByLabelText("كلمة المرور"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "تسجيل الدخول" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/^تعذّر تسجيل الدخول/);
    expect(alert.textContent).not.toMatch(/[A-Za-z]/);
  });

  it("goes where it was sent", async () => {
    state.search = "next=%2Fpollux-motors%2Finbox";
    state.signIn.mockResolvedValue({ error: null });
    show();
    signIn();
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/pollux-motors/inbox"));
  });

  it("never anywhere else", async () => {
    state.search = "next=%2F%2Fevil.example";
    state.signIn.mockResolvedValue({ error: null });
    show();
    signIn();
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/"));
  });

  it("says so when an email link or Google came back without a session", () => {
    state.search = "error=link";
    show();
    expect(screen.getByRole("alert").textContent).toBe(
      "That link has expired or was already used. Sign in, or ask for a new one.",
    );
  });

  it("offers an account, keeping where they were going", () => {
    state.search = "next=%2Faccept-invite%3Ftoken%3Dabc";
    show();
    expect(screen.getByRole("link", { name: "Create an account" }).getAttribute("href")).toBe(
      "/signup?next=%2Faccept-invite%3Ftoken%3Dabc",
    );
  });
});
