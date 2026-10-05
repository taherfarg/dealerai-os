"use client";

import { use, useState } from "react";
import { CustomerRow } from "@/components/crm/CustomerRow";
import { HandOverBar } from "@/components/crm/HandOverBar";
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
  // Handing many over is the same permission as handing one over.
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const toggle = (id: string, on: boolean) =>
    setSelected((before) => {
      const after = new Set(before);
      if (on) after.add(id);
      else after.delete(id);
      return after;
    });
  const allShown = rows.length > 0 && rows.every((row) => selected.has(row.id));

  return (
    <div className="mx-auto max-w-5xl">
      <h1 className="text-lg font-semibold">{t("customers.title")}</h1>

      <div className="mt-3 flex flex-wrap gap-2">
        <input
          type="search"
          // Its own text, not the address's: bound to the address it was put
          // back between one letter and the next, and fast typing lost letters.
          defaultValue={filters.q}
          placeholder={t("customers.search")}
          aria-label={t("customers.search")}
          onChange={(event) => setFilters({ q: event.target.value })}
          className="min-h-11 flex-1 rounded-md border border-border px-3 text-sm"
        />
        {canSeeOthers && (
          <select
            value={filters.owner_id}
            aria-label={t("customers.owner")}
            onChange={(event) => setFilters({ owner_id: event.target.value })}
            className="min-h-11 rounded-md border border-border px-2 text-sm"
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
          className="min-h-11 rounded-md border border-border px-2 text-sm"
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
        <>
          {canSeeOthers && (
            <label className="mt-3 flex min-h-11 items-center gap-2 px-3 text-sm">
              <input
                type="checkbox"
                checked={allShown}
                onChange={(event) =>
                  setSelected(event.target.checked ? new Set(rows.map((row) => row.id)) : new Set())
                }
              />
              {t("bulk.selectAll")}
            </label>
          )}
          <ul className="mt-1">
            {rows.map((customer) => (
              <CustomerRow
                key={customer.id}
                customer={customer}
                href={`/${tenant}/customers/${customer.id}`}
                selected={selected.has(customer.id)}
                onSelect={canSeeOthers ? (on) => toggle(customer.id, on) : undefined}
              />
            ))}
          </ul>
        </>
      )}

      {selected.size > 0 && (
        <HandOverBar
          ids={[...selected]}
          names={Object.fromEntries(rows.map((row) => [row.id, row.name ?? row.id]))}
          onClear={() => setSelected(new Set())}
          onFinished={(failed) => setSelected(new Set(failed))}
        />
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
