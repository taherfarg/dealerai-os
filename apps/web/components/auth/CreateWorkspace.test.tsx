import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { LocaleProvider } from "@/lib/i18n-client";
import { CreateWorkspace } from "./CreateWorkspace";

const state = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn(), create: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push, refresh: state.refresh }),
}));
vi.mock("@/lib/api/joining", () => ({ createWorkspace: state.create }));

function show() {
  render(
    <LocaleProvider locale="en">
      <CreateWorkspace />
    </LocaleProvider>,
  );
}

const name = () => screen.getByLabelText("Dealership name");
const address = () => screen.getByLabelText("Web address") as HTMLInputElement;

beforeEach(() => {
  state.push.mockReset();
  state.refresh.mockReset();
  state.create.mockReset();
});

describe("CreateWorkspace", () => {
  it("suggests the address from the name until the owner edits it", () => {
    show();
    fireEvent.change(name(), { target: { value: "Pollux Motors" } });
    expect(address().value).toBe("pollux-motors");
    fireEvent.change(address(), { target: { value: "pollux" } });
    fireEvent.change(name(), { target: { value: "Pollux Motors Dubai" } });
    expect(address().value).toBe("pollux");
  });

  it("creates the workspace where the showroom is, and opens its Team screen", async () => {
    state.create.mockResolvedValue({ slug: "pollux-motors" });
    show();
    fireEvent.change(name(), { target: { value: "Pollux Motors" } });
    fireEvent.change(screen.getByLabelText("Where the showroom is"), { target: { value: "SA" } });
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    await waitFor(() =>
      expect(state.create).toHaveBeenCalledWith({
        name: "Pollux Motors",
        slug: "pollux-motors",
        country: "SA",
        timezone: "Asia/Riyadh",
        currency: "SAR",
        locales: ["en", "ar"],
      }),
    );
    expect(state.push).toHaveBeenCalledWith("/pollux-motors/settings/team");
  });

  it("shows the API's sentence when the address is taken", async () => {
    state.create.mockRejectedValue(
      new ApiError({
        type: "conflict",
        title: "Conflict",
        status: 409,
        detail: "the slug 'pollux-motors' is taken",
      }),
    );
    show();
    fireEvent.change(name(), { target: { value: "Pollux Motors" } });
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "the slug 'pollux-motors' is taken",
    );
  });
});
