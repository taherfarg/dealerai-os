import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { ResetPasswordForm } from "./ResetPasswordForm";

const state = vi.hoisted(() => ({
  push: vi.fn(),
  refresh: vi.fn(),
  update: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push, refresh: state.refresh }),
}));
vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({ auth: { updateUser: state.update } }),
}));

function show(locale: "en" | "ar" = "en") {
  render(
    <LocaleProvider locale={locale}>
      <ResetPasswordForm />
    </LocaleProvider>,
  );
}

beforeEach(() => {
  state.push.mockReset();
  state.refresh.mockReset();
  state.update.mockReset().mockResolvedValue({ data: {}, error: null });
});

describe("ResetPasswordForm", () => {
  it("saves the new password and goes on into the app", async () => {
    show();
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "a new one" } });
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));

    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/"));
    expect(state.update).toHaveBeenCalledWith({ password: "a new one" });
    expect(state.refresh).toHaveBeenCalled();
  });

  it("holds the new password to the rule sign-up has, and tells the browser what it is", () => {
    show();
    const field = screen.getByLabelText("New password") as HTMLInputElement;
    expect(field.required).toBe(true);
    expect(field.minLength).toBe(8);
    expect(field.type).toBe("password");
    // A password manager offers to make one, and to remember it.
    expect(field.autocomplete).toBe("new-password");
    expect(screen.getByText("At least 8 characters.")).toBeTruthy();
  });

  it("says in its own words that it was not saved, and stays", async () => {
    state.update.mockResolvedValue({ data: null, error: { message: "Auth session missing!" } });
    show();
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "a new one" } });
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "That password was not saved. Ask for a new link and try again.",
    );
    expect(state.push).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "Reset your password" }).getAttribute("href")).toBe(
      "/forgot-password",
    );
  });

  it("labels itself in Arabic", () => {
    show("ar");
    expect(screen.getByLabelText("كلمة المرور الجديدة")).toBeTruthy();
    expect(screen.getByRole("button", { name: "احفظ كلمة المرور" })).toBeTruthy();
  });
});
