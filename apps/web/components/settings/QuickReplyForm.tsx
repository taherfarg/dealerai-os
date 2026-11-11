"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { useSaveQuickReply, type QuickReply } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

const LANGUAGES = ["ar", "en", "fr"] as const;
/** The table's own check (0011): a slash and a lowercase word. */
const SHORTCUT = /^\/[a-z0-9-]{1,30}$/;
const FIELD = "field px-3";

/** A new quick reply, or one being changed — saved whole, every language. */
export function QuickReplyForm({
  reply,
  onDone,
}: {
  reply: QuickReply | null;
  onDone: () => void;
}) {
  const t = useT();
  const save = useSaveQuickReply();
  const [shortcut, setShortcut] = useState(reply?.shortcut ?? "/");
  const [title, setTitle] = useState(reply?.title ?? "");
  const [bodies, setBodies] = useState({
    ar: reply?.body.ar ?? "",
    en: reply?.body.en ?? "",
    fr: reply?.body.fr ?? "",
  });
  const valid =
    SHORTCUT.test(shortcut) && title.trim() !== "" && Object.values(bodies).some((b) => b.trim());

  return (
    <form
      className="bg-surface border-border flex flex-col gap-2 rounded-lg border p-3 text-sm"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(
          {
            id: reply?.id,
            reply: {
              shortcut,
              title: title.trim(),
              body: {
                ar: bodies.ar.trim() || null,
                en: bodies.en.trim() || null,
                fr: bodies.fr.trim() || null,
              },
            },
          },
          { onSuccess: onDone },
        );
      }}
    >
      <div className="flex flex-wrap gap-2">
        <label className="flex items-center gap-2">
          <span className="text-muted">{t("quick.shortcut")}</span>
          <input
            value={shortcut}
            onChange={(event) => setShortcut(event.target.value.toLowerCase())}
            aria-invalid={!SHORTCUT.test(shortcut)}
            className={`${FIELD} w-40 font-mono`}
            dir="ltr"
          />
        </label>
        <label className="flex flex-1 items-center gap-2">
          <span className="text-muted">{t("quick.title")}</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            className={`${FIELD} flex-1`}
            dir="auto"
          />
        </label>
      </div>
      {LANGUAGES.map((code) => (
        <label key={code} className="flex flex-col gap-1">
          <span className="text-muted">{t(`language.${code}`)}</span>
          <textarea
            value={bodies[code]}
            rows={2}
            onChange={(event) => setBodies({ ...bodies, [code]: event.target.value })}
            className={`${FIELD} py-2`}
            dir={code === "ar" ? "rtl" : "ltr"}
          />
        </label>
      ))}
      <p className="text-muted text-xs">{t("quick.nameHint")}</p>
      {save.isError && (
        <p role="alert" className="text-xs text-danger">
          {save.error instanceof ApiError
            ? (save.error.problem.detail ?? save.error.problem.title)
            : t("settings.saveFailed")}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onDone} className="btn btn-quiet">
          {t("common.cancel")}
        </button>
        <button
          type="submit"
          disabled={!valid || save.isPending}
          className="btn btn-primary"
        >
          {t("common.save")}
        </button>
      </div>
    </form>
  );
}
