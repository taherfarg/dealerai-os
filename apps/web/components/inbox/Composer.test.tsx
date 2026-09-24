import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TenantApiProvider } from "@/lib/api/context";
import { LocaleProvider } from "@/lib/i18n-client";
import { Composer } from "./Composer";

vi.mock("@/lib/auth/token", () => ({ getBrowserAccessToken: async () => null }));
afterEach(() => vi.unstubAllGlobals());

function show(draftToEdit?: { id: string; text: string }) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TenantApiProvider tenantId="tenant-1" slug="pollux">
        <LocaleProvider locale="en">
          <Composer conversationId="conversation-1" windowOpen draftToEdit={draftToEdit} />
        </LocaleProvider>
      </TenantApiProvider>
    </QueryClientProvider>,
  );
}

describe("Composer", () => {
  it("prefills a draft and sends its id with edited text", async () => {
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async () =>
      new Response(JSON.stringify({ id: "message-1" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    show({ id: "draft-1", text: "Original draft" });
    const box = screen.getByRole("textbox", { name: "Write a reply" }) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toBe("Original draft"));
    fireEvent.change(box, { target: { value: "Edited draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(JSON.parse(await fetch.mock.calls[0][0].text())).toEqual({
      text: "Edited draft",
      suggestion_id: "draft-1",
    });
  });

  it("leaves Alt+Enter to the draft panel", () => {
    // Otherwise a half-typed reply goes out beside the draft: two messages.
    const fetch = vi.fn<(request: Request) => Promise<Response>>();
    vi.stubGlobal("fetch", fetch);
    show();
    const box = screen.getByRole("textbox", { name: "Write a reply" });
    fireEvent.change(box, { target: { value: "half a thought" } });
    fireEvent.keyDown(box, { key: "Enter", altKey: true });
    expect(fetch).not.toHaveBeenCalled();
    expect((box as HTMLTextAreaElement).value).toBe("half a thought");
  });
});
