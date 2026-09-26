import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { HandOverBar } from "./HandOverBar";

const state = vi.hoisted(() => ({ calls: [] as unknown[] }));
vi.mock("@/lib/api/hooks", () => ({
  useMembers: () => ({
    data: [
      { id: "sara", name: "Sara Mansour", role: "manager", accepting_chats: true },
      { id: "watcher", name: "Viewer", role: "viewer", accepting_chats: false },
    ],
  }),
  useBulkReassign: () => ({
    isPending: false,
    // Moves Omar, refuses Mona.
    mutate: (
      variables: { ids: string[]; ownerId: string; onProgress?: (done: number) => void },
      options: { onSuccess: (failed: string[]) => void },
    ) => {
      state.calls.push(variables);
      variables.onProgress?.(2);
      options.onSuccess(["mona"]);
    },
  }),
}));

describe("HandOverBar", () => {
  it("hands the customers over and names the one that could not be moved", () => {
    const onFinished = vi.fn();
    render(
      <LocaleProvider locale="en">
        <HandOverBar
          ids={["omar", "mona"]}
          names={{ omar: "Omar Haddad", mona: "Mona Fathy" }}
          onClear={vi.fn()}
          onFinished={onFinished}
        />
      </LocaleProvider>,
    );
    expect(screen.queryByRole("option", { name: "Viewer" })).toBeNull();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "sara" } });
    fireEvent.click(screen.getByRole("button", { name: "Hand over" }));
    expect(state.calls).toEqual([expect.objectContaining({ ids: ["omar", "mona"], ownerId: "sara" })]);
    expect(screen.getByRole("alert").textContent).toContain("Mona Fathy");
    expect(onFinished).toHaveBeenCalledWith(["mona"]);
  });
});
