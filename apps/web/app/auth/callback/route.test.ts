// @vitest-environment node
import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

const auth = vi.hoisted(() => ({
  verifyOtp: vi.fn(),
  exchangeCodeForSession: vi.fn(),
}));
vi.mock("@/lib/supabase/server", () => ({ createClient: async () => ({ auth }) }));

const SITE = "https://app.dealerai.example";

/** Where somebody ends up after opening the link. */
async function opens(query: string): Promise<string | null> {
  const response = await GET(new NextRequest(`${SITE}/auth/callback?${query}`));
  expect(response.status).toBe(307);
  return response.headers.get("location");
}

beforeEach(() => {
  auth.verifyOtp.mockReset().mockResolvedValue({ error: null });
  auth.exchangeCodeForSession.mockReset().mockResolvedValue({ error: null });
});

describe("where Supabase sends somebody back", () => {
  it("makes a session from a token hash, in whichever browser opened the link", async () => {
    const invitation = encodeURIComponent("/accept-invite?token=abc.def");
    const landed = await opens(`next=${invitation}&token_hash=hash-1&type=email`);

    expect(auth.verifyOtp).toHaveBeenCalledWith({ token_hash: "hash-1", type: "email" });
    expect(auth.exchangeCodeForSession).not.toHaveBeenCalled();
    // The invitation survived the email.
    expect(landed).toBe(`${SITE}/accept-invite?token=abc.def`);
  });

  it("lands a recovery link on the new-password page", async () => {
    const landed = await opens("next=%2Freset-password&token_hash=hash-2&type=recovery");

    expect(auth.verifyOtp).toHaveBeenCalledWith({ token_hash: "hash-2", type: "recovery" });
    expect(landed).toBe(`${SITE}/reset-password`);
  });

  it("still redeems a one-time code — Google, and a template nobody edited", async () => {
    const landed = await opens("next=%2Fpollux-motors%2Finbox&code=code-1");

    expect(auth.exchangeCodeForSession).toHaveBeenCalledWith("code-1");
    expect(auth.verifyOtp).not.toHaveBeenCalled();
    expect(landed).toBe(`${SITE}/pollux-motors/inbox`);
  });

  it("refuses a kind of link the app never asks for", async () => {
    const landed = await opens("token_hash=hash-3&type=invite");

    expect(auth.verifyOtp).not.toHaveBeenCalled();
    expect(landed).toBe(`${SITE}/login?error=link&next=%2F`);
  });

  it("sends a link that was refused to sign-in, saying so, and keeps where it was going", async () => {
    auth.verifyOtp.mockResolvedValue({ error: { message: "Token has expired or is invalid" } });
    const landed = await opens("next=%2Freset-password&token_hash=old&type=recovery");

    expect(landed).toBe(`${SITE}/login?error=link&next=%2Freset-password`);
  });

  it("does the same for a code that was refused, and for nothing at all", async () => {
    auth.exchangeCodeForSession.mockResolvedValue({ error: { message: "invalid grant" } });

    expect(await opens("code=used")).toBe(`${SITE}/login?error=link&next=%2F`);
    expect(await opens("")).toBe(`${SITE}/login?error=link&next=%2F`);
  });

  it.each(["https://evil.example/steal", "//evil.example", "/\\evil.example"])(
    "never leaves the site for %s",
    async (elsewhere) => {
      const landed = await opens(`next=${encodeURIComponent(elsewhere)}&code=code-2`);
      expect(landed).toBe(`${SITE}/`);
    },
  );
});
