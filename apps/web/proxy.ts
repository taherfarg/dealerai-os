import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = ["/login", "/signup", "/auth"];

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
    if (pathname.startsWith("/dev-login") || request.cookies.get("dev_token")) {
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

  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  if (!user && !isPublic) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    // Come back here after signing in, so a shared link survives the detour.
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  if (user && pathname === "/login") {
    const url = request.nextUrl.clone();
    url.pathname = "/";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
