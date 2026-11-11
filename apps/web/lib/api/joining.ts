import { createApiClient, unwrap } from "./client";
import type { components } from "./schema";

/** The two calls made before somebody belongs to a workspace, so they carry
 *  no X-Tenant-Id — the API resolves them from the token alone. */
const api = createApiClient();

export type Joined = components["schemas"]["JoinedOut"];
export type Workspace = components["schemas"]["TenantOut"];

export async function acceptInvitation(token: string): Promise<Joined> {
  return unwrap(await api.POST("/v1/invites/accept", { body: { token } }));
}

export async function createWorkspace(
  body: components["schemas"]["TenantCreate"],
): Promise<Workspace> {
  return unwrap(await api.POST("/v1/tenants", { body }));
}
