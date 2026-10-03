import { NextResponse, type NextRequest } from "next/server";
import { safeNext } from "@/lib/auth/next";
import { createClient } from "@/lib/supabase/server";

/** Where Supabase sends somebody back — from a confirmation email or from
 *  Google — with a one-time code, which becomes the session cookie here. */
export async function GET(request: NextRequest) {
  const { origin, searchParams } = request.nextUrl;
  const next = safeNext(searchParams.get("next"));
  const code = searchParams.get("code");
  if (code) {
    const { error } = await (await createClient()).auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(`${origin}${next}`);
  }
  // Expired, already used, or opened in another browser from the one that asked.
  return NextResponse.redirect(`${origin}/login?error=link&next=${encodeURIComponent(next)}`);
}
