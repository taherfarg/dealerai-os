import { NextResponse, type NextRequest } from "next/server";
import { safeNext } from "@/lib/auth/next";
import { createClient } from "@/lib/supabase/server";

// What the project's two edited templates send (docs/sales/10-staging.md § 3).
const EMAIL_LINKS = ["email", "recovery"] as const;
type EmailLink = (typeof EMAIL_LINKS)[number];

const isEmailLink = (type: string | null): type is EmailLink =>
  EMAIL_LINKS.includes(type as EmailLink);

/**
 * Where Supabase sends somebody back, with something that becomes the session
 * cookie here.
 *
 * An email link carries a token hash: it opens in any browser, which matters
 * to somebody who signed up in the installed app and reads their mail in the
 * mail app's own. Google — and an email from a template nobody edited — come
 * back with a one-time code instead, which only the browser that asked can
 * redeem.
 */
export async function GET(request: NextRequest) {
  const { origin, searchParams } = request.nextUrl;
  const next = safeNext(searchParams.get("next"));
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type");
  const code = searchParams.get("code");

  let signedIn = false;
  if (tokenHash && isEmailLink(type)) {
    const { error } = await (await createClient()).auth.verifyOtp({ token_hash: tokenHash, type });
    signedIn = !error;
  } else if (code && !tokenHash) {
    const { error } = await (await createClient()).auth.exchangeCodeForSession(code);
    signedIn = !error;
  }
  if (signedIn) return NextResponse.redirect(`${origin}${next}`);
  // Expired, already used, a kind of link this app never asks for — or a code
  // opened in another browser from the one that asked.
  return NextResponse.redirect(`${origin}/login?error=link&next=${encodeURIComponent(next)}`);
}
