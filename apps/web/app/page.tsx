import { redirect } from "next/navigation";
import { api } from "@/lib/api";

type Tenant = { id: string; slug: string; name: string };

/**
 * Root just resolves which workspace to open.
 *
 * The tenant is a URL segment, not a cookie: a link someone pastes into Slack
 * must open the same workspace for the person who clicks it.
 */
export default async function Home() {
  let tenants: Tenant[] = [];
  try {
    tenants = await api<Tenant[]>("/v1/tenants");
  } catch {
    // API down or not reachable — fall through to onboarding rather than a 500.
  }

  if (tenants.length === 0) redirect("/onboarding");
  redirect(`/${tenants[0].slug}`);
}
