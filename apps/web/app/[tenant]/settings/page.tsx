"use client";

import { useRouter } from "next/navigation";
import { use, useEffect } from "react";
import { firstSection } from "@/components/settings/sections";
import { useMe } from "@/lib/api/hooks";

/** /settings on its own opens the first section this person may use. */
export default function SettingsIndex({ params }: { params: Promise<{ tenant: string }> }) {
  const { tenant } = use(params);
  const me = useMe();
  const router = useRouter();
  const permissions = me.data?.permissions;
  useEffect(() => {
    if (permissions) router.replace(`/${tenant}${firstSection(permissions).href}`);
  }, [permissions, router, tenant]);
  return null;
}
