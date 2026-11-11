/** A JWT's claims, read and NOT verified — for showing, never for deciding.
 *  The API verifies every token it is handed. */
export function readClaims(token: string): Record<string, unknown> | null {
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const binary = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
    const json = new TextDecoder().decode(Uint8Array.from(binary, (c) => c.charCodeAt(0)));
    const claims: unknown = JSON.parse(json);
    return claims && typeof claims === "object" ? (claims as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}
