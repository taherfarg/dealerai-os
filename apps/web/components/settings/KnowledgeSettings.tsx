"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { useDeleteDocument, useDocuments, useUploadDocument } from "@/lib/api/hooks";
import type { MessageKey } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/i18n-client";
import { counted } from "@/lib/words";

/** routes/documents.KINDS — what a dealership uploads by hand. */
const KINDS = ["policy", "export_policy", "faq", "spec_sheet", "price_list", "other"] as const;
const FIELD = "min-h-11 rounded-md border border-black/10 px-2 dark:border-white/15";

/**
 * The dealership's own documents, which the copilot quotes (08-screens § 13).
 * A document is read in the background, so the list shows where each one is
 * and polls until it is ready — or says, in a sentence, why it could not be.
 */
export function KnowledgeSettings() {
  const t = useT();
  const locale = useLocale();
  const documents = useDocuments();
  const upload = useUploadDocument();
  const remove = useDeleteDocument();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<string>("policy");
  const [title, setTitle] = useState("");
  // Bumped after an upload, to clear the file input — it has no value to set.
  const [form, setForm] = useState(0);

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold">{t("settings.knowledge")}</h1>
      <p className="text-muted text-sm">{t("knowledge.pricesLine")}</p>

      <form
        key={form}
        className="bg-surface border-border flex flex-col gap-2 rounded-lg border p-3 text-sm"
        onSubmit={(event) => {
          event.preventDefault();
          if (!file) return;
          upload.mutate(
            { file, kind, title: title.trim() },
            {
              onSuccess: () => {
                setFile(null);
                setTitle("");
                setForm((n) => n + 1);
              },
            },
          );
        }}
      >
        <input
          type="file"
          accept=".pdf,.docx,.txt"
          aria-label={t("knowledge.file")}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <div className="flex flex-wrap gap-2">
          <select
            value={kind}
            aria-label={t("knowledge.kind")}
            onChange={(event) => setKind(event.target.value)}
            className={FIELD}
          >
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {t(`doc.${value}` as MessageKey)}
              </option>
            ))}
          </select>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={t("knowledge.title")}
            aria-label={t("knowledge.title")}
            className={`${FIELD} flex-1`}
            dir="auto"
          />
          <button
            type="submit"
            disabled={!file || upload.isPending}
            className="bg-accent min-h-11 rounded-md px-4 font-medium text-black disabled:opacity-50"
          >
            {t("knowledge.upload")}
          </button>
        </div>
        {upload.isError && (
          <p role="alert" className="text-xs text-red-600 dark:text-red-400">
            {upload.error instanceof ApiError
              ? (upload.error.problem.detail ?? upload.error.problem.title)
              : t("settings.saveFailed")}
          </p>
        )}
      </form>

      {(documents.data ?? []).length === 0 && !documents.isLoading && (
        <p className="text-muted text-sm">{t("knowledge.empty")}</p>
      )}
      <ul className="divide-y divide-black/5 text-sm dark:divide-white/10">
        {(documents.data ?? []).map((document) => (
          <li key={document.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span className="min-w-0 flex-1">
              <span className="block truncate" dir="auto">
                {document.title ?? t(`doc.${document.kind}` as MessageKey)}
              </span>
              <span className="text-muted text-xs">
                {t(`doc.${document.kind}` as MessageKey)} ·{" "}
                {t(`knowledge.status.${document.status}` as MessageKey)}
                {document.status === "ready" &&
                  ` · ${counted(locale, document.chunk_count, "passages")}`}
              </span>
              {document.error && (
                <span className="block text-xs text-red-600 dark:text-red-400">
                  {document.error}
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={() => remove.mutate(document.id)}
              className="hover:bg-background min-h-11 rounded-md px-3 text-red-700 dark:text-red-400"
            >
              {t("knowledge.delete")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
