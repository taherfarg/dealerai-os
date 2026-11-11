/**
 * Local-only sign-in as a seeded person (docs/sales/01-architecture.md § 7).
 *
 * Active only when NEXT_PUBLIC_DEV_AUTH=1 in a non-production build, and the API
 * route it calls exists only when the API runs with ENV=local — both sides have
 * to be wrong for this to be reachable anywhere real.
 */
export const DEV_AUTH =
  process.env.NEXT_PUBLIC_DEV_AUTH === "1" && process.env.NODE_ENV !== "production";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DevPerson = { email: string; name: string; role: string };

export async function listDevPeople(): Promise<DevPerson[]> {
  const res = await fetch(`${API}/internal/dev/people`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Could not list seeded people (${res.status}). Is the API running with ENV=local?`);
  return res.json();
}

/** Starts a session and returns the workspace slug to open — null for somebody
 *  new, who belongs to no workspace yet. */
export async function startDevSession(email: string, name?: string): Promise<string | null> {
  const res = await fetch(`${API}/internal/dev/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, name: name || null }),
  });
  if (!res.ok) throw new Error(`Could not sign in (${res.status}).`);
  const session: { access_token: string; tenant_slug: string | null } = await res.json();
  document.cookie = `dev_token=${session.access_token}; path=/; samesite=lax; max-age=43200`;
  return session.tenant_slug;
}
