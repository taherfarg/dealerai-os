"use client";

import { useState } from "react";
import {
  useCustomers,
  useMergeCustomers,
  type Customer,
  type CustomerDetail,
} from "@/lib/api/hooks";
import { Auto, CustomerName, Ltr } from "@/components/Bidi";
import { Modal } from "@/components/Modal";
import { formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";

/**
 * Two records, one customer.
 *
 * Both sides are shown before anything happens, because this cannot be undone:
 * the duplicate's conversations, leads and tasks move to the one being kept,
 * and the duplicate is deleted.
 */
export function MergeDialog({
  customer,
  onClose,
  onMerged,
}: {
  customer: CustomerDetail;
  onClose: () => void;
  onMerged?: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState<Customer | null>(null);
  const found = useCustomers({ q: search });
  const merge = useMergeCustomers();

  const candidates = (found.data?.pages ?? [])
    .flatMap((page) => page.data)
    .filter((row) => row.id !== customer.id)
    .slice(0, 8);

  return (
    <Modal title={t("merge.title")} onClose={onClose}>

      <label className="mt-3 block">
        <span className="text-muted text-xs">{t("merge.search")}</span>
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="mt-1 min-h-11 w-full rounded-md border border-black/10 px-3 text-sm dark:border-white/15"
        />
      </label>

      <ul className="mt-2 max-h-40 overflow-y-auto">
        {candidates.map((row) => (
          <li key={row.id}>
            <button
              type="button"
              onClick={() => setChosen(row)}
              className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-md px-2 text-start text-sm ${
                chosen?.id === row.id ? "bg-accent/20" : "hover:bg-background"
              }`}
            >
              <CustomerName country={row.country} name={row.name} />
              <Ltr className="text-muted shrink-0 text-xs">{row.phone}</Ltr>
            </button>
          </li>
        ))}
      </ul>

      {chosen && (
        <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
          {(
            [
              [t("merge.keeping"), customer.name, customer.phone, customer.owner?.name],
              [t("merge.merging"), chosen.name, chosen.phone, chosen.owner?.name],
            ] as const
          ).map(([label, name, phone, owner]) => (
            <section key={label} className="border-border rounded-md border p-2">
              <h3 className="text-muted font-semibold uppercase">{label}</h3>
              <p className="mt-1 text-sm">
                <Auto>{name}</Auto>
              </p>
              <p className="text-muted">
                <Ltr>{phone}</Ltr>
              </p>
              <p className="text-muted">{owner ?? t("customers.nobody")}</p>
            </section>
          ))}
          <p className="text-muted col-span-2">
            {t("customers.lastSeen")}: {formatRelative(chosen.last_seen_at, locale)}
          </p>
        </div>
      )}

      <p className="mt-3 rounded-md bg-amber-500/10 px-2 py-1 text-xs text-amber-800 dark:text-amber-200">
        {t("merge.warning")}
      </p>

      <div className="mt-4 flex justify-end gap-2">
        <button type="button" onClick={onClose} className="min-h-11 px-3 text-sm">
          {t("common.cancel")}
        </button>
        <button
          type="button"
          disabled={!chosen || merge.isPending}
          onClick={() =>
            chosen &&
            merge.mutate(
              { keep_id: customer.id, merge_id: chosen.id },
              {
                onSuccess: () => {
                  onClose();
                  onMerged?.();
                },
              },
            )
          }
          className="bg-accent min-h-11 rounded-md px-4 text-sm font-medium text-black disabled:opacity-50"
        >
          {t("merge.confirm")}
        </button>
      </div>
    </Modal>
  );
}
