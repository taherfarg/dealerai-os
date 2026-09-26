import { redirect } from "next/navigation";

/** The workspace opens on the inbox: that is where a salesperson's day starts. */
export default async function TenantHome({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = await params;
  redirect(`/${tenant}/inbox`);
}
