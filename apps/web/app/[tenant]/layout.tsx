import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";
import type { Locale } from "@/lib/i18n";
import { Providers } from "./providers";

type Tenant = { id: string; slug: string; name: string };
type Approval = { id: string };

export default async function TenantLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenant: string }>;
}) {
  const { tenant: slug } = await params;
  const store = await cookies();
  const locale = ((await store.get("locale")?.value) ?? "en") as Locale;

  const tenants = await api<Tenant[]>("/v1/tenants");
  const tenant = tenants.find((t) => t.slug === slug);

  // A slug the caller is not a member of is a 404, never a 403 — the API is
  // deliberately indistinguishable here and the UI must not undo that by
  // saying "you don't have access to this workspace", which confirms it exists.
  if (!tenant) notFound();

  let pending = 0;
  try {
    pending = (await api<Approval[]>("/v1/approvals?status=pending", { tenantId: tenant.id }))
      .length;
  } catch {
    // A badge is not worth failing the whole shell over.
  }

  return (
    <Providers tenantId={tenant.id} slug={tenant.slug} locale={locale}>
      <Shell tenant={tenant} tenants={tenants} locale={locale} pendingApprovals={pending}>
        {children}
      </Shell>
    </Providers>
  );
}
