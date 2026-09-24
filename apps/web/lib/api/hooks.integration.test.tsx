import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TenantApiProvider } from "./context";
import { useSendMessage, useSuggestion } from "./hooks";

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
