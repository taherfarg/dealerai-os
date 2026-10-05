"use client";

import { useState } from "react";
import { useBulkReassign, useMembers } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/**
 * Handing the selected customers to one colleague — S3's single-customer
 * hand-over in a loop, with progress, and the names of anybody who could not
 * be moved, who stay selected so the manager can try again.
 */
export function HandOverBar({
  ids,
  names,
  onClear,
  onFinished,
}: {
  ids: string[];
  names: Record<string, string>;
  onClear: () => void;
  onFinished: (failed: string[]) => void;
}) {
  const t = useT();
  const members = useMembers();
  const bulk = useBulkReassign();
  const [owner, setOwner] = useState("");
  const [done, setDone] = useState(0);
  const [failed, setFailed] = useState<string[]>([]);
  const colleagues = (members.data ?? []).filter((member) => member.role !== "viewer");

  return (
    <div className="bg-surface border-border sticky bottom-16 z-10 mt-3 flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm shadow-lg md:bottom-4">
      <span className="font-medium">
        {ids.length} {t("bulk.selected")}
      </span>
      <select
        value={owner}
        aria-label={t("bulk.handOverTo")}
        onChange={(event) => setOwner(event.target.value)}
        className="min-h-11 rounded-md border border-border px-2"
      >
        <option value="">{t("bulk.handOverTo")}</option>
        {colleagues.map((member) => (
          <option key={member.id} value={member.id}>
            {member.name ?? member.email}
          </option>
        ))}
      </select>
      <button
        type="button"
        disabled={!owner || bulk.isPending}
        onClick={() => {
          setFailed([]);
          setDone(0);
          bulk.mutate(
            { ids, ownerId: owner, onProgress: setDone },
            {
              onSuccess: (notMoved) => {
                setFailed(notMoved);
                onFinished(notMoved);
              },
            },
          );
        }}
        className="bg-accent min-h-11 rounded-md px-4 font-medium text-on-accent disabled:opacity-50"
      >
        {t("bulk.handOver")}
      </button>
      {bulk.isPending && (
        <span className="text-muted tabular-nums" dir="ltr">
          {done} / {ids.length}
        </span>
      )}
      <button type="button" onClick={onClear} className="min-h-11 px-3">
        {t("common.cancel")}
      </button>
      {failed.length > 0 && (
        <p role="alert" className="w-full text-xs text-danger" dir="auto">
          {t("bulk.failed")} {failed.map((id) => names[id] ?? id).join("، ")}
        </p>
      )}
    </div>
  );
}
