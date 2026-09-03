import { createBrowserClient } from "@supabase/ssr";

/**
 * Browser-side Supabase client.
 *
 * The anon key is public by design — it identifies the project, it does not
 * grant anything. RLS is what protects the data, which is why every tenant
 * table is `enable row level security` AND `force row level security`.
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
