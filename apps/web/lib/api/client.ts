import createFetchClient, { type Middleware } from "openapi-fetch";
import { getBrowserAccessToken } from "@/lib/auth/token";
import type { paths } from "./schema";

/** Where the API lives. Exported because the SSE reader opens its own fetch. */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** RFC 9457 problem+json — the only error shape the API emits. */
export type Problem = {
  type: string;
  title: string;
  status: number;
  detail?: string;
  trace_id?: string;
  /** `keep_id` rides here on a 409 already-merged: where the customer went. */
  errors?: { field?: string; code?: string; keep_id?: string }[];
};

export class ApiError extends Error {
  constructor(readonly problem: Problem) {
    super(problem.detail ?? problem.title);
  }
}

/**
 * openapi-fetch returns `{ data, error }`. Screens want a value or an exception,
 * because an exception is what React Query stores as the error state.
 */
export function unwrap<T>(result: {
  data?: T;
  error?: unknown;
  response: Response;
}): T {
  if (result.error !== undefined || !result.response.ok) {
    const e = (result.error ?? {}) as Partial<Problem>;
    throw new ApiError({
      type: e.type ?? "about:blank",
      title: e.title ?? result.response.statusText,
      status: e.status ?? result.response.status,
      detail: e.detail,
      trace_id: e.trace_id,
      errors: e.errors,
    });
  }
  return result.data as T;
}

/**
 * The typed client. Every tenant route declares X-Tenant-Id as a required header,
 * so the generated types make each call state its tenant — the compiler, not a
 * middleware, guarantees it is never forgotten. This adds only the token.
 */
export function createApiClient() {
  const client = createFetchClient<paths>({ baseUrl: API_BASE });
  const auth: Middleware = {
    async onRequest({ request }) {
      const token = await getBrowserAccessToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
  };
  client.use(auth);
  return client;
}

export type ApiClient = ReturnType<typeof createApiClient>;
