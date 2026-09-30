"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { JoinInvitation } from "@/components/auth/JoinInvitation";

function FromLink() {
  return <JoinInvitation token={useSearchParams().get("token") ?? ""} />;
}

/** Public: an invitation is opened before its reader has an account. */
export default function AcceptInvitePage() {
  return (
    <Suspense>
      <FromLink />
    </Suspense>
  );
}
