import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TenantApiProvider } from "@/lib/api/context";
import { LocaleProvider } from "@/lib/i18n-client";
import { Composer } from "./Composer";

vi.mock("@/lib/auth/token", () => ({ getBrowserAccessToken: async () => null }));
afterEach(() => vi.unstubAllGlobals());

function show(
  draftToEdit?: { id: string; text: string },
  customer: { language?: string; customerName?: string } = {},
) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TenantApiProvider tenantId="tenant-1" slug="pollux">
        <LocaleProvider locale="en">
          <Composer
            conversationId="conversation-1"
            windowOpen
            draftToEdit={draftToEdit}
            {...customer}
          />
        </LocaleProvider>
      </TenantApiProvider>
    </QueryClientProvider>,
  );
}

const QUICK_REPLIES = [
  {
    id: "reply-1",
    shortcut: "/price",
    title: "Price",
    body: { en: "Hello {name}, it is AED 128,000.", ar: "مرحبا {name}، السعر 128,000 درهم.", fr: null },
    updated_at: "2026-09-25T00:00:00Z",
  },
];

/** Quick replies for the GET, an accepted send for anything else. */
function api() {
  return vi.fn<(request: Request) => Promise<Response>>(async (request) =>
    request.url.includes("/v1/quick-replies")
      ? new Response(JSON.stringify(QUICK_REPLIES), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      : new Response(JSON.stringify({ id: "message-1" }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
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

  it("puts a quick reply in the box on Enter, in the customer's language, and does not send it", async () => {
    const fetch = api();
    vi.stubGlobal("fetch", fetch);
    show(undefined, { language: "ar", customerName: "Omar Haddad" });
    const box = screen.getByRole("textbox", { name: "Write a reply" }) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "/pr" } });
    await screen.findByRole("option", { name: /\/price/ });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(box.value).toBe("مرحبا Omar، السعر 128,000 درهم.");
    expect(fetch.mock.calls.filter(([request]) => request.method === "POST")).toEqual([]);
  });

  it("sends a message that starts with a slash and has a space in it as typed", async () => {
    const fetch = api();
    vi.stubGlobal("fetch", fetch);
    show();
    const box = screen.getByRole("textbox", { name: "Write a reply" });
    fireEvent.change(box, { target: { value: "/price is on the website" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const sent = JSON.parse(await fetch.mock.calls[0][0].text());
    expect(sent.text).toBe("/price is on the website");
  });

  it("closes the menu on Escape and leaves the text alone", async () => {
    vi.stubGlobal("fetch", api());
    show();
    const box = screen.getByRole("textbox", { name: "Write a reply" }) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "/pr" } });
    await screen.findByRole("option", { name: /\/price/ });
    fireEvent.keyDown(box, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(box.value).toBe("/pr");
  });
});
