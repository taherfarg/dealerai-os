import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { safeNext } from "@/lib/auth/next";

// An invitation is opened before its reader has an account, and a forgotten
// password is asked about by somebody who cannot sign in.
const PUBLIC_PATHS = ["/login", "/signup", "/forgot-password", "/auth", "/accept-invite"];

/** Open to somebody signed out. The new-password page is not: the link in the
 *  email signs them in first (app/auth/callback). */
export function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((path) => pathname.startsWith(path));
}

/**
 * Refreshes the Supabase session on every request and gates the app.
 *
 * Named `proxy`, not `middleware`: Next 16 deprecated the middleware file
 * convention.
 *
 * getUser(), not getSession(): getSession reads the cookie without verifying
 * it, so a forged cookie would look like a signed-in user here. It would still
 * fail at the API and at RLS, but the UI would render someone's dashboard shell
 * first, which is its own kind of wrong.
 */
export async function proxy(request: NextRequest) {
  // Local sign-in as a seeded person (lib/dev-auth.ts). Never in a production
  // build; the real Supabase gate below is untouched.
  if (process.env.NEXT_PUBLIC_DEV_AUTH === "1" && process.env.NODE_ENV !== "production") {
    const { pathname, search } = request.nextUrl;
    const open = pathname.startsWith("/dev-login") || pathname.startsWith("/accept-invite");
    if (open || request.cookies.get("dev_token")) {
      return NextResponse.next({ request });
    }
    // Come back here afterwards — with the query, so an invitation's token
    // survives the detour.
    const url = request.nextUrl.clone();
    url.pathname = "/dev-login";
    url.search = "";
    url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }

  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options),
          );
        },
      },
    },
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname, search } = request.nextUrl;
  if (!user && !isPublic(pathname)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    // Come back here after signing in — with the query, so a shared link
    // survives the detour.
    url.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(url);
  }

  // Signed in already: go where the link was going, not to the root.
  if (user && (pathname === "/login" || pathname === "/signup")) {
    const next = new URL(safeNext(request.nextUrl.searchParams.get("next")), request.url);
    return NextResponse.redirect(next);
  }

  return response;
}

// What a signed-out browser must be able to fetch for the app to be installable
// ([07] § 8) passes too: the manifest, its icons, the service worker and the page
// it shows offline — each anchored, so no page whose address merely starts the
// same way slips through (proxy.test.ts).
export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|manifest.webmanifest$|sw.js$|offline.html$|icon/\\d+$|apple-icon$|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
