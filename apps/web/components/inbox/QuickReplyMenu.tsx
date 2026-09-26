"use client";

import type { QuickReply } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";

/** The replies whose shortcut starts with what was typed after the slash. */
export function matching(replies: QuickReply[], typed: string): QuickReply[] {
  const query = typed.slice(1).toLowerCase();
  return replies.filter((reply) => reply.shortcut.slice(1).startsWith(query)).slice(0, 6);
}

/**
 * The reply in the customer's language, with their first name in it. A
 * language the reply has no text for falls back to English, then to whatever
 * it has: a quick reply in the wrong language beats a blank composer.
 */
export function filled(reply: QuickReply, language: string | null, name: string | null): string {
  const code = (language ?? "").slice(0, 2) as "ar" | "en" | "fr";
  const body = reply.body[code] || reply.body.en || reply.body.ar || reply.body.fr || "";
  const first = (name ?? "").trim().split(/\s+/)[0] ?? "";
  return body.replaceAll("{name}", first);
}

/** The shortcuts matching what is typed, above the composer. */
export function QuickReplyMenu({
  options,
  active,
  onPick,
}: {
  options: QuickReply[];
  active: number;
  onPick: (reply: QuickReply) => void;
}) {
  const t = useT();
  if (options.length === 0) return null;
  return (
    <ul
      role="listbox"
      aria-label={t("quick.menu")}
      className="bg-surface border-border mb-2 rounded-md border text-sm shadow"
    >
      {options.map((reply, index) => (
        <li key={reply.id} role="option" aria-selected={index === active}>
          <button
            type="button"
            // Keep the textarea focused, so typing carries on after a click.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onPick(reply)}
            className={`flex min-h-11 w-full items-center gap-2 px-3 text-start ${
              index === active ? "bg-background" : ""
            }`}
          >
            <span className="font-mono text-xs" dir="ltr">
              {reply.shortcut}
            </span>
            <span className="truncate">{reply.title}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
