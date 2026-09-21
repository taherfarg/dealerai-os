"use client";

import { use } from "react";
import { CustomerRow } from "@/components/crm/CustomerRow";
import { useCustomers, useMe, useMembers, type CustomerFilters } from "@/lib/api/hooks";
import { useFilters } from "@/lib/filters";
import { useT } from "@/lib/i18n-client";

const DEFAULTS = { q: "", owner_id: "", band: "", country: "", tag: "" };

export default function CustomersPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const me = useMe();
  const members = useMembers();
  const [filters, setFilters] = useFilters(DEFAULTS);

  // Empty strings mean "no filter" to the API, so they are dropped rather than sent.
  const query = Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== ""),
  ) as CustomerFilters;
  const customers = useCustomers(query);
  const rows = (customers.data?.pages ?? []).flatMap((page) => page.data);
  const canSeeOthers = (me.data?.permissions ?? []).includes("contacts.reassign");

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-lg font-semibold">{t("customers.title")}</h1>

      <div className="mt-3 flex flex-wrap gap-2">
        <input
          type="search"
          value={filters.q}
          placeholder={t("customers.search")}
          aria-label={t("customers.search")}
          onChange={(event) => setFilters({ q: event.target.value })}
          className="min-h-11 flex-1 rounded-md border border-black/10 px-3 text-sm dark:border-white/15"
        />
        {canSeeOthers && (
          <select
            value={filters.owner_id}
            aria-label={t("customers.owner")}
            onChange={(event) => setFilters({ owner_id: event.target.value })}
            className="min-h-11 rounded-md border border-black/10 px-2 text-sm dark:border-white/15"
          >
            <option value="">{t("customers.anyOwner")}</option>
            {(members.data ?? []).map((member) => (
              <option key={member.id} value={member.id}>
                {member.name ?? member.email}
              </option>
            ))}
          </select>
        )}
        <select
          value={filters.band}
          aria-label={t("customers.band")}
          onChange={(event) => setFilters({ band: event.target.value })}
          className="min-h-11 rounded-md border border-black/10 px-2 text-sm dark:border-white/15"
        >
          <option value="">{t("customers.anyBand")}</option>
          {(["hot", "warm", "cold"] as const).map((band) => (
            <option key={band} value={band}>
              {t(`band.${band}`)}
            </option>
          ))}
        </select>
      </div>

      {rows.length === 0 && !customers.isLoading ? (
        <p className="text-muted mt-8 text-center text-sm">{t("customers.empty")}</p>
      ) : (
        <ul className="mt-4">
          {rows.map((customer) => (
            <CustomerRow
              key={customer.id}
              customer={customer}
              href={`/${tenant}/customers/${customer.id}`}
            />
          ))}
        </ul>
      )}

      {customers.hasNextPage && (
        <button
          type="button"
          onClick={() => customers.fetchNextPage()}
          className="text-muted mx-auto mt-4 block min-h-11 px-3 text-sm underline"
        >
          {t("customers.loadMore")}
        </button>
      )}
    </div>
  );
}
