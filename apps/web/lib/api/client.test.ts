import { describe, expect, it } from "vitest";
import { ApiError, unwrap } from "./client";

describe("unwrap", () => {
  it("returns the data of a successful response", () => {
    const result = { data: { ok: 1 }, response: new Response(null, { status: 200 }) };
    expect(unwrap(result)).toEqual({ ok: 1 });
  });

  it("turns problem+json into an ApiError that carries the detail", () => {
    const problem = {
      type: "https://api.dealerai.os/errors/window-closed",
      title: "The 24-hour window is closed",
      status: 422,
      detail: "Send an approved template.",
    };
    try {
      unwrap({ error: problem, response: new Response(null, { status: 422 }) });
      expect.unreachable();
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).problem.status).toBe(422);
      expect((error as ApiError).message).toBe("Send an approved template.");
    }
  });

  it("still produces an error when a gateway answers without JSON", () => {
    const response = new Response(null, { status: 502, statusText: "Bad Gateway" });
    expect(() => unwrap({ error: undefined, response })).toThrow("Bad Gateway");
  });
});
