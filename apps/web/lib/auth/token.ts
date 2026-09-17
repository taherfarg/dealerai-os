import { DEV_AUTH } from "@/lib/dev-auth";
import { createClient } from "@/lib/supabase/client";

/** The access token for API calls from the browser: the local dev cookie, or the Supabase session. */
export async function getBrowserAccessToken(): Promise<string | null> {
  if (DEV_AUTH) {
    const match = document.cookie.match(/(?:^|; )dev_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : null;
  }
  const { data } = await createClient().auth.getSession();
  return data.session?.access_token ?? null;
}
