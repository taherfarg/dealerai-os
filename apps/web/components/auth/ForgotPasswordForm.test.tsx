import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { ForgotPasswordForm } from "./ForgotPasswordForm";

const state = vi.hoisted(() => ({ reset: vi.fn() }));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { resetPasswordForEmail: state.reset } }),
}));

const SENT = "If that address has an account, a link is on its way to it.";

function show(locale: "en" | "ar" = "en") {
  render(
    <LocaleProvider locale={locale}>
      <ForgotPasswordForm />
    </LocaleProvider>,
  );
}

function ask(address = "layla@pollux.test") {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: address } });
  fireEvent.click(screen.getByRole("button", { name: "Send the link" }));
}

beforeEach(() => {
  state.reset.mockReset().mockResolvedValue({ data: {}, error: null });
});

describe("ForgotPasswordForm", () => {
  it("asks for a link that comes back to the new-password page", async () => {
    show();
    ask();

    await waitFor(() => expect(state.reset).toHaveBeenCalledTimes(1));
    expect(state.reset).toHaveBeenCalledWith("layla@pollux.test", {
      redirectTo: `${window.location.origin}/auth/callback?next=%2Freset-password`,
    });
    expect((await screen.findByRole("status")).textContent).toBe(SENT);
  });

  it("says the same thing whether or not the address has an account", async () => {
    // Refused, rate-limited, unknown: one answer. Which addresses have an
    // account is what the sign-in form will not say either.
    state.reset.mockResolvedValue({ data: null, error: { message: "User not found" } });
    show();
    ask("nobody@pollux.test");

    expect((await screen.findByRole("status")).textContent).toBe(SENT);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says it even when the request never arrived", async () => {
    state.reset.mockRejectedValue(new TypeError("Failed to fetch"));
    show();
    ask();

    expect((await screen.findByRole("status")).textContent).toBe(SENT);
  });

  it("offers the way back to sign-in, before and after", async () => {
    show();
    expect(screen.getByRole("link", { name: "Back to sign in" }).getAttribute("href")).toBe(
      "/login",
    );
    ask();
    await screen.findByRole("status");
    expect(screen.getByRole("link", { name: "Back to sign in" })).toBeTruthy();
  });

  it("labels itself in Arabic", () => {
    show("ar");
    expect(screen.getByLabelText("البريد الإلكتروني")).toBeTruthy();
    expect(screen.getByRole("button", { name: "أرسل الرابط" })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("إعادة تعيين كلمة المرور");
  });
});
