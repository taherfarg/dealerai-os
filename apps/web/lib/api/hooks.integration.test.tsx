import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TenantApiProvider } from "./context";
import {
  useBulkReassign,
  useSaveSalesSettings,
  useSendMessage,
  useSuggestion,
  useTellServerMyLanguage,
} from "./hooks";

vi.mock("@/lib/auth/token", () => ({ getBrowserAccessToken: async () => null }));

afterEach(() => vi.unstubAllGlobals());

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <TenantApiProvider tenantId="tenant-1" slug="pollux">
        {children}
      </TenantApiProvider>
    </QueryClientProvider>
  );
  return { client, wrapper };
}

describe("copilot API hooks", () => {
  it("loads the current suggestion for one conversation", async () => {
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async () =>
      new Response(JSON.stringify({ id: "draft-1", status: "ready", text: "Hello" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const { wrapper } = setup();
    const { result } = renderHook(() => useSuggestion("conversation-1"), { wrapper });
    await waitFor(() => expect(result.current.data?.id).toBe("draft-1"));
    const request = fetch.mock.calls[0][0] as Request;
    expect(request.url).toContain("/v1/conversations/conversation-1/suggestion");
    expect(request.headers.get("X-Tenant-Id")).toBe("tenant-1");
  });

  it("sends the suggestion id with the reply so the outcome is recorded", async () => {
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async () =>
      new Response(JSON.stringify({ id: "message-1" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const { wrapper } = setup();
    const { result } = renderHook(() => useSendMessage("conversation-1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ text: "Hello", suggestionId: "draft-1" });
    });
    const request = fetch.mock.calls[0][0] as Request;
    expect(JSON.parse(await request.text())).toEqual({
      text: "Hello",
      suggestion_id: "draft-1",
    });
  });

  it("sends an approved template when the draft is outside the free-text window", async () => {
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async () =>
      new Response(JSON.stringify({ id: "message-2" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const { wrapper } = setup();
    const { result } = renderHook(() => useSendMessage("conversation-1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({
        templateId: "template-1",
        variables: ["Omar"],
        suggestionId: "draft-2",
      });
    });
    const request = fetch.mock.calls[0][0];
    expect(JSON.parse(await request.text())).toEqual({
      template_id: "template-1",
      variables: ["Omar"],
      suggestion_id: "draft-2",
    });
  });
});

const JSON_HEADERS = { "Content-Type": "application/json" };

describe("settings and handing customers over", () => {
  it("saves only the settings the screen changed", async () => {
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async () =>
      new Response(JSON.stringify({ first_response_target_min: 7 }), {
        status: 200,
        headers: JSON_HEADERS,
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const { wrapper } = setup();
    const { result } = renderHook(() => useSaveSalesSettings(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ first_response_target_min: 7 });
    });
    const request = fetch.mock.calls[0][0];
    expect(request.method).toBe("PATCH");
    // A manager's save must not carry keys she may not write.
    expect(JSON.parse(await request.text())).toEqual({ first_response_target_min: 7 });
  });

  it("reports who could not be handed over", async () => {
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async (request) => {
      const refused = request.url.includes("customer-2");
      return new Response(
        JSON.stringify(refused ? { title: "Forbidden", status: 403 } : { id: "moved" }),
        { status: refused ? 403 : 200, headers: JSON_HEADERS },
      );
    });
    vi.stubGlobal("fetch", fetch);
    const { wrapper } = setup();
    const { result } = renderHook(() => useBulkReassign(), { wrapper });
    let failed: string[] = [];
    await act(async () => {
      failed = await result.current.mutateAsync({
        ids: ["customer-1", "customer-2", "customer-3"],
        ownerId: "sara",
      });
    });
    expect(failed).toEqual(["customer-2"]);
    expect(fetch).toHaveBeenCalledTimes(3);
  });
});

describe("the reader's language", () => {
  /** An API that knows one language for this person and takes a new one. */
  const server = (knows: "en" | "ar") => {
    const fetch = vi.fn<(request: Request) => Promise<Response>>(async (request) =>
      request.method === "PUT"
        ? new Response(null, { status: 204 })
        : new Response(JSON.stringify({ user: { id: "user-1" }, locale: knows }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
    );
    vi.stubGlobal("fetch", fetch);
    return fetch;
  };
  const told = (fetch: ReturnType<typeof server>) =>
    fetch.mock.calls.map(([request]) => request).filter((request) => request.method === "PUT");

  it("tells the server when the language on screen is not the one it has", async () => {
    const fetch = server("en");
    const { wrapper, client } = setup();
    renderHook(() => useTellServerMyLanguage("ar"), { wrapper });

    await waitFor(() => expect(told(fetch)).toHaveLength(1));
    const [request] = told(fetch);
    expect(request.url).toContain("/v1/me/locale");
    expect(JSON.parse(await request.text())).toEqual({ locale: "ar" });
    // And remembers that it did, so it is said once.
    await waitFor(() =>
      expect(
        (client.getQueryData(["me", "tenant-1"]) as { locale: string } | undefined)?.locale,
      ).toBe("ar"),
    );
    expect(told(fetch)).toHaveLength(1);
  });

  it("says nothing when the server already has it", async () => {
    const fetch = server("ar");
    const { wrapper } = setup();
    renderHook(() => useTellServerMyLanguage("ar"), { wrapper });
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    await act(async () => {});
    expect(told(fetch)).toHaveLength(0);
  });
});
