import { DEV_AUTH } from "@/lib/dev-auth";
import { silenceThisDevice } from "@/lib/push";
import { createClient } from "@/lib/supabase/client";

/** Signing out, wherever the session lives — after silencing this device: a
 *  phone that changes hands must not keep showing the last person's customers
 *  on its lock screen. */
export async function signOut(): Promise<void> {
  await silenceThisDevice();
  if (DEV_AUTH) document.cookie = "dev_token=; path=/; max-age=0; samesite=lax";
  else await createClient().auth.signOut();
}
