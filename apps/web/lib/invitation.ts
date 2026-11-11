import { readClaims } from "./jwt";

export type Invitation = {
  workspace: string;
  role: string;
  email: string;
  expiresAt: Date;
  expired: boolean;
};

/** What an invitation link says, for the page that opens it
 *  (routes/tenants.create_invite writes these claims). */
export function readInvitation(token: string, now = Date.now()): Invitation | null {
  const claims = readClaims(token);
  if (!claims || claims.kind !== "invite") return null;
  const { tenant_name: workspace, role, email, exp } = claims;
  if (typeof workspace !== "string" || typeof role !== "string") return null;
  if (typeof email !== "string" || typeof exp !== "number") return null;
  const expiresAt = new Date(exp * 1000);
  return { workspace, role, email, expiresAt, expired: expiresAt.getTime() <= now };
}
