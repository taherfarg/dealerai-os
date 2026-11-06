"use client";

import Link from "next/link";
import { use, useState } from "react";
import { STATUS, concept, mayReview } from "@/components/content/ContentGrid";
import { CopyEditor } from "@/components/content/CopyEditor";
import { useApproveContent, useContent, useMe, useRejectContent } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";
import { mediaSrc } from "@/lib/media";

/** Words a person may still change: nothing has gone out. Mirrors routes/content.py. */
const EDITABLE = new Set(["draft", "pending_approval", "approved", "rejected"]);

/** One piece: its images, its words in each language, and the decision. */
export default function ContentPiecePage({
  params,
}: {
  params: Promise<{ tenant: string; contentId: string }>;
}) {
  const { tenant, contentId } = use(params);
  const t = useT();
  const me = useMe();
  const piece = useContent(contentId);
  const approve = useApproveContent(contentId);
  const reject = useRejectContent(contentId);
  const [reason, setReason] = useState("");

  if (piece.isError) {
    return (
      <p role="alert" className="text-danger p-6 text-sm">
        {piece.error.message}
      </p>
    );
  }
  if (!piece.data) return <p className="text-muted p-6 text-sm">…</p>;

  const item = piece.data;
  const reviewer = mayReview(me.data?.role);
  const editable = reviewer && EDITABLE.has(item.status);
  const problem = approve.error?.message ?? reject.error?.message;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <header className="space-y-1">
        <Link href={`/${tenant}/content`} className="text-muted text-sm underline-offset-2 hover:underline">
          {t("nav.content")}
        </Link>
        <h1 className="text-lg font-semibold capitalize">{concept(item)}</h1>
        <p className="text-muted text-sm">
          {[item.vehicle, item.kind, t(STATUS[item.status] ?? "content.status.draft")]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {item.status === "rejected" && item.rejection_reason && (
          <p className="text-danger text-sm" dir="auto">
            {t("content.rejectedBecause")} {item.rejection_reason}
          </p>
        )}
      </header>

      {item.images.length > 0 && (
        <ul className="flex gap-3 overflow-x-auto pb-1">
          {item.images.map((image) => (
            <li key={image.id} className="w-48 shrink-0">
              {/* eslint-disable-next-line @next/next/no-img-element -- a signed link the image optimiser cannot fetch */}
              <img
                src={mediaSrc(image.url)}
                alt={`${concept(item)} ${image.aspect_ratio} ${image.locale ?? ""}`}
                className="w-full rounded-xl"
              />
              <p className="text-muted mt-1 text-xs">
                {image.aspect_ratio}
                {image.locale && ` · ${image.locale}`}
              </p>
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {item.copies.map((copy) => (
          <CopyEditor key={copy.locale} contentId={contentId} copy={copy} editable={editable} />
        ))}
      </div>

      {reviewer && (item.status === "pending_approval" || item.status === "approved") && (
        <section className="flex flex-wrap items-end gap-2">
          {item.status === "pending_approval" && (
            <button
              type="button"
              className="btn btn-primary"
              disabled={approve.isPending}
              onClick={() => approve.mutate()}
            >
              {t("content.approve")}
            </button>
          )}
          <label className="flex min-w-60 flex-1 flex-col gap-1 text-xs">
            <span className="text-muted">{t("content.reason")}</span>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={500}
              dir="auto"
              className="field"
            />
          </label>
          <button
            type="button"
            className="btn"
            disabled={reject.isPending || !reason.trim()}
            onClick={() => reject.mutate(reason.trim(), { onSuccess: () => setReason("") })}
          >
            {t("content.reject")}
          </button>
        </section>
      )}
      {item.status === "approved" && (
        <p className="text-success text-sm">{t("content.approvedNext")}</p>
      )}
      {problem && (
        <p role="alert" className="text-danger text-sm">
          {problem}
        </p>
      )}
    </div>
  );
}
