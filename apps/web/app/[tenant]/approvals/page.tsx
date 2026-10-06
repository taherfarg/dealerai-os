import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";
import { api } from "@/lib/api";
import { type Locale, t } from "@/lib/i18n";

type Approval = {
  id: string;
  kind: string;
  summary: string;
  status: string;
  required_role: string;
  created_at: string;
  expires_at: string | null;
};

type Tenant = { id: string; slug: string };

async function tenantId(slug: string): Promise<string> {
  const tenants = await api<Tenant[]>("/v1/tenants");
  const found = tenants.find((t) => t.slug === slug);
  if (!found) throw new Error("no such workspace");
  return found.id;
}

export default async function ApprovalsPage({
  params,
}: {
  params: Promise<{ tenant: string }>;
}) {
  const { tenant: slug } = await params;
  const store = await cookies();
  const locale = ((await store.get("locale")?.value) ?? "en") as Locale;

  const id = await tenantId(slug);
  const approvals = await api<Approval[]>("/v1/approvals?status=pending", { tenantId: id });

  async function decide(formData: FormData) {
    "use server";
    const approvalId = String(formData.get("id"));
    const action = String(formData.get("action"));
    const tid = await tenantId(slug);
    await api(`/v1/approvals/${approvalId}/${action}`, {
      method: "POST",
      body: JSON.stringify({}),
      tenantId: tid,
    });
    revalidatePath(`/${slug}/approvals`);
  }

  return (
    <section className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{t(locale, "approvals.title")}</h1>
      </header>

      {approvals.length === 0 ? (
        <p className="text-muted text-sm">{t(locale, "approvals.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {approvals.map((a) => (
            <li
              key={a.id}
              className="border-border bg-surface flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium">{a.summary}</p>
                <p className="text-muted mt-1 text-xs">
                  {a.kind} · {t(locale, "approvals.requires")} {a.required_role}
                </p>
              </div>

              {/* Server actions, so a decision is a real POST that works
                  without JavaScript and cannot be double-fired by a fast
                  second click — the API takes the row FOR UPDATE anyway. */}
              <div className="flex shrink-0 gap-2">
                <form action={decide}>
                  <input type="hidden" name="id" value={a.id} />
                  <input type="hidden" name="action" value="approve" />
                  <button className="bg-accent rounded-md px-3 py-1.5 text-sm text-on-accent">
                    {t(locale, "approvals.approve")}
                  </button>
                </form>
                <form action={decide}>
                  <input type="hidden" name="id" value={a.id} />
                  <input type="hidden" name="action" value="reject" />
                  <button className="border-border rounded-md border px-3 py-1.5 text-sm">
                    {t(locale, "approvals.reject")}
                  </button>
                </form>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
