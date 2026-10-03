import { cookies } from "next/headers";
import { getAccessToken } from "@/lib/supabase/server";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** RFC 9457 problem+json — the only error shape the API emits. */
export type Problem = {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  trace_id?: string;
  errors?: { field?: string; code?: string }[];
};

export class ApiError extends Error {
  constructor(readonly problem: Problem) {
    super(problem.detail ?? problem.title);
  }
}

/**
 * Server-side call into the FastAPI service.
 *
 * The tenant is stated explicitly on every request rather than held in a
 * server-side "current workspace" session, so a user in two dealerships can
 * keep both open in two tabs without one leaking into the other.
 */
export async function api<T>(
  path: string,
  opts: RequestInit & { tenantId?: string } = {},
): Promise<T> {
  const token = await getAccessToken();
  const { tenantId, ...init } = opts;

  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (tenantId) headers.set("X-Tenant-Id", tenantId);
  // What the API refuses, it refuses in the language on screen.
  headers.set("Accept-Language", (await cookies()).get("locale")?.value ?? "en");

  const res = await fetch(`${BASE}${path}`, { ...init, headers, cache: "no-store" });

  if (!res.ok) {
    let problem: Problem;
    try {
      problem = (await res.json()) as Problem;
    } catch {
      problem = { type: "about:blank", title: res.statusText, status: res.status };
    }
    throw new ApiError(problem);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}
