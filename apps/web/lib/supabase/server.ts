import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/headers";

/** Supabase client for Server Components and route handlers. */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        // Annotated explicitly: CookieMethodsServer is a union with the
        // deprecated get/set/remove shape, so TS cannot infer which branch
        // this literal matches and falls back to implicit any.
        setAll(cookiesToSet: { name: string; value: string; options: CookieOptions }[]) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            );
          } catch {
            // Called from a Server Component, where cookies are read-only.
            // The middleware refreshes the session, so this is safe to ignore.
          }
        },
      },
    },
  );
}

/**
 * The access token to forward to the API.
 *
 * FastAPI verifies this itself with the project's JWT secret rather than
 * calling back to Supabase — a network hop per request, on the critical path
 * of every customer reply, to re-check a signature it can check locally.
 */
export async function getAccessToken(): Promise<string | null> {
  // Local sign-in as a seeded person (lib/dev-auth.ts). Never in a production build.
  if (process.env.NEXT_PUBLIC_DEV_AUTH === "1" && process.env.NODE_ENV !== "production") {
    return (await cookies()).get("dev_token")?.value ?? null;
  }
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}
