import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import type { Pipeline } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { StageEditor } from "./StageEditor";

const state = vi.hoisted(() => ({
  mutate: vi.fn(),
  error: null as unknown,
}));
vi.mock("@/lib/api/hooks", () => ({
  useReplaceStages: () => ({
    mutate: state.mutate,
    reset: vi.fn(),
    isPending: false,
    isError: state.error !== null,
    error: state.error,
  }),
}));

const board: Pipeline = {
  id: "local",
  name: "Local sale",
  position: 0,
  is_default: true,
  stages: [
    { id: "new", name: "New", position: 0, category: "open" },
    { id: "negotiation", name: "Negotiation", position: 1, category: "open" },
    { id: "won", name: "Won", position: 2, category: "won" },
    { id: "lost", name: "Lost", position: 3, category: "lost" },
  ],
};

function show() {
  render(
    <LocaleProvider locale="en">
      <StageEditor pipeline={board} />
    </LocaleProvider>,
  );
}

beforeEach(() => {
  state.mutate.mockReset();
  state.error = null;
});

describe("StageEditor", () => {
  it("sends the board in its new order when a stage moves up", () => {
    show();
    fireEvent.click(screen.getAllByRole("button", { name: "Move up" })[1]);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    const [sent] = state.mutate.mock.calls[0];
    expect(sent.map((stage: { id: string }) => stage.id)).toEqual([
      "negotiation",
      "new",
      "won",
      "lost",
    ]);
  });

  it("shows the server's sentence when a stage still holds leads", () => {
    state.error = new ApiError({
      type: "stage-in-use",
      title: "Stage in use",
      status: 409,
      detail: "Negotiation still holds 3 leads. Move them first.",
    });
    show();
    expect(screen.getByRole("alert").textContent).toBe(
      "Negotiation still holds 3 leads. Move them first.",
    );
  });

  it("will not save a stage without a name", () => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Add a stage" }));
    expect(screen.getByRole("button", { name: "Save" }).hasAttribute("disabled")).toBe(true);
  });
});
