import { cookies } from "next/headers";
import { api } from "@/lib/api";
import { type Locale, t } from "@/lib/i18n";

type Tenant = { id: string; slug: string; name: string; autonomy_mode: string };
type StockRow = { id: string; make: string; model: string; days_in_stock: number; published_content_count: number };
type Usage = { spent_usd: number; budget_usd: number };

export default async function CommandCenter({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant: slug } = await params;
  const store = await cookies();
  const locale = ((await store.get("locale")?.value) ?? "en") as Locale;

  const tenants = await api<Tenant[]>("/v1/tenants");
  const tenant = tenants.find((t) => t.slug === slug)!;

  const [stale, usage] = await Promise.all([
    api<StockRow[]>("/v1/vehicles/stock-report?min_days=30&uncovered_only=true", { tenantId: tenant.id }),
    api<Usage>(`/v1/tenants/${tenant.id}/usage`, { tenantId: tenant.id }),
  ]);

  return (
    <section className="flex flex-col gap-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{t(locale, "nav.command")}</h1>
        <p className="text-muted mt-1 text-sm">
          {tenant.name} · {tenant.autonomy_mode}
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2">
        <article className="border-border bg-surface rounded-lg border p-4">
          <p className="text-muted text-xs uppercase tracking-wide">Aging, no content</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums">{stale.length}</p>
          <p className="text-muted mt-1 text-xs">30+ days in stock, never posted about</p>
        </article>
        <article className="border-border bg-surface rounded-lg border p-4">
          <p className="text-muted text-xs uppercase tracking-wide">AI spend this month</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums">
            ${usage.spent_usd.toFixed(2)}
          </p>
          <p className="text-muted mt-1 text-xs">of ${usage.budget_usd.toFixed(2)} budget</p>
        </article>
      </div>

      {stale.length > 0 && (
        <div className="border-border overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="p-3 text-start font-medium">Vehicle</th>
                <th className="p-3 text-end font-medium">Days</th>
              </tr>
            </thead>
            <tbody>
              {stale.slice(0, 10).map((v) => (
                <tr key={v.id} className="border-border border-t">
                  <td className="p-3">{v.make} {v.model}</td>
                  <td className="p-3 text-end tabular-nums">{v.days_in_stock}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
