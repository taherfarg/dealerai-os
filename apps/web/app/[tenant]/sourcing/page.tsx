"use client";

import { use } from "react";
import { Appraise } from "@/components/sourcing/Appraise";
import { BuyingList } from "@/components/sourcing/BuyingList";
import { useBuyingList, useMe } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/**
 * What to buy and the most to pay (docs/lifecycle/README.md § L5). For those
 * who may see cost: a bid is what the dealer would pay.
 */
export default function SourcingPage({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const t = useT();
  const me = useMe();
  const allowed = (me.data?.permissions ?? []).includes("costs.view");
  const list = useBuyingList(allowed);

  if (me.data && !allowed) {
    return (
      <div className="mx-auto max-w-md p-6 text-sm">
        <h1 className="text-lg font-semibold">{t("sourcing.title")}</h1>
        <p className="mt-2">{t("sourcing.forCost")}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8">
      <h1 className="text-lg font-semibold">{t("sourcing.title")}</h1>
      {list.isError ? (
        <p role="alert" className="text-danger text-sm">
          {list.error.message}
        </p>
      ) : list.data ? (
        <BuyingList list={list.data} tenant={tenant} />
      ) : (
        <p className="text-muted text-sm">…</p>
      )}
      <Appraise currency={list.data?.currency ?? "AED"} />
    </div>
  );
}
