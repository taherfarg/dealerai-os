import { ApiError } from "@/lib/api/client";

/** The Sales roles a person can hold, most powerful first. */
export const ROLES = ["owner", "admin", "manager", "sales", "viewer"] as const;

export const FIELD = "min-h-11 rounded-md border border-black/10 px-2 dark:border-white/15";

/** The API's own sentence for a refusal, or ours when there is none. */
export function problem(error: unknown, fallback: string): string {
  return error instanceof ApiError ? (error.problem.detail ?? error.problem.title) : fallback;
}
