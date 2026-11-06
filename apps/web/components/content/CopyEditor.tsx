"use client";

import { useState, type FormEvent } from "react";
import { useEditCopy, type ContentDetail } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

type Copy = ContentDetail["copies"][number];

/** "#mg6 dubai, #new" → ["mg6", "dubai", "new"]: however a person types them. */
export function parseHashtags(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((tag) => tag.replace(/^#+/, "").trim())
    .filter(Boolean);
}

/**
 * One language's words. Saving marks them as a person's; the API refuses a
 * price that is not the car's, and says which figure.
 */
export function CopyEditor({
  contentId,
  copy,
  editable,
}: {
  contentId: string;
  copy: Copy;
  editable: boolean;
}) {
  const t = useT();
  const edit = useEditCopy(contentId);
  const [saved, setSaved] = useState(false);
  const dir = copy.locale === "ar" ? "rtl" : "ltr";

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaved(false);
    edit.mutate(
      {
        locale: copy.locale,
        patch: {
          hook: String(form.get("hook") ?? ""),
          caption: String(form.get("caption") ?? ""),
          cta: String(form.get("cta") ?? ""),
          hashtags: parseHashtags(String(form.get("hashtags") ?? "")),
        },
      },
      { onSuccess: () => setSaved(true) },
    );
  };

  return (
    <form onSubmit={submit} className="bg-surface space-y-2 rounded-2xl p-4" lang={copy.locale}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold uppercase">{copy.locale}</h3>
        {copy.edited_by_human && (
          <span className="text-muted text-xs">{t("content.editedByPerson")}</span>
        )}
      </div>
      {(
        [
          ["hook", t("content.hook"), copy.hook],
          ["cta", t("content.cta"), copy.cta],
        ] as const
      ).map(([name, label, value]) => (
        <label key={name} className="flex flex-col gap-1 text-xs">
          <span className="text-muted">{label}</span>
          <input
            name={name}
            defaultValue={value ?? ""}
            dir={dir}
            disabled={!editable}
            className="field"
          />
        </label>
      ))}
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted">{t("content.caption")}</span>
        <textarea
          name="caption"
          defaultValue={copy.caption ?? ""}
          dir={dir}
          rows={5}
          maxLength={2200}
          disabled={!editable}
          className="field"
        />
      </label>
      <label className="flex flex-col gap-1 text-xs">
        <span className="text-muted">{t("content.hashtags")}</span>
        <input
          name="hashtags"
          defaultValue={copy.hashtags.map((tag) => `#${tag}`).join(" ")}
          dir="ltr"
          disabled={!editable}
          className="field"
        />
      </label>
      {editable && (
        <div className="flex items-center gap-2">
          <button type="submit" className="btn" disabled={edit.isPending}>
            {t("content.save")}
          </button>
          {saved && <span className="text-success text-xs">{t("content.saved")}</span>}
        </div>
      )}
      {edit.error && (
        <p role="alert" className="text-danger text-xs">
          {edit.error.message}
        </p>
      )}
    </form>
  );
}
