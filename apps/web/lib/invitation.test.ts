import { describe, expect, it } from "vitest";
import { readInvitation } from "./invitation";

/** A JWT's shape — header.claims.signature — with the claims in base64url
 *  UTF-8, as PyJWT writes them. The signature is the API's business. */
function tokenWith(claims: object): string {
  const bytes = new TextEncoder().encode(JSON.stringify(claims));
  const base64 = btoa(String.fromCharCode(...bytes));
  return `h.${base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")}.s`;
}

const NOW = Date.UTC(2026, 9, 1);
const valid = {
  kind: "invite",
  tenant_name: "Pollux Motors",
  role: "sales",
  email: "layla@pollux.test",
  exp: NOW / 1000 + 3600,
};

describe("readInvitation", () => {
  it("says who is invited, where, and as what", () => {
    expect(readInvitation(tokenWith(valid), NOW)).toEqual({
      workspace: "Pollux Motors",
      role: "sales",
      email: "layla@pollux.test",
      expiresAt: new Date(valid.exp * 1000),
      expired: false,
    });
  });

  it("reads a workspace named in Arabic", () => {
    expect(readInvitation(tokenWith({ ...valid, tenant_name: "معرض بولكس" }), NOW)?.workspace).toBe(
      "معرض بولكس",
    );
  });

  it("knows an expired one", () => {
    expect(readInvitation(tokenWith({ ...valid, exp: NOW / 1000 - 1 }), NOW)?.expired).toBe(true);
  });

  it("is nothing for a sign-in token or garbage", () => {
    expect(readInvitation(tokenWith({ ...valid, kind: undefined }), NOW)).toBeNull();
    expect(readInvitation("not-a-token", NOW)).toBeNull();
    expect(readInvitation("", NOW)).toBeNull();
  });
});
