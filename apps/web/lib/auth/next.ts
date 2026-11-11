/**
 * Where to go after signing in: only somewhere in this app. `next` arrives in
 * a URL anybody can write, so without this a sign-in link is a way to send a
 * rep to a look-alike site straight after they typed their password.
 */
export function safeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return "/";
  }
  return value;
}
