"use client";

import type { Message } from "@/lib/api/hooks";
import { API_BASE } from "@/lib/api/client";
import { formatRelative } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

const TICKS: Record<string, string> = {
  queued: "·",
  sending: "·",
  sent: "✓",
  delivered: "✓✓",
  read: "✓✓",
};

/** A stored object is fetched through the API's signed link, never directly. */
const source = (url: string) => (url.startsWith("http") ? url : `${API_BASE}${url}`);

/**
 * One message, whatever kind it is.
 *
 * Two things must be impossible here: an internal note that could pass for a
 * sent message, and a failed message that could pass for a delivered one.
 */
export function MessageBubble({
  message,
  onRetry,
}: {
  message: Message;
  onRetry?: (messageId: string) => void;
}) {
  const t = useT();

  if (message.kind === "event") {
    return (
      <li data-kind="event" className="my-2 text-center">
        <span className="text-muted text-xs">{String(message.event?.text ?? "")}</span>
      </li>
    );
  }

  const note = message.kind === "note";
  const ours = message.direction === "out";

  return (
    <li
      id={`message-${message.id}`}
      data-kind={message.kind}
      data-origin={message.origin}
      className={`flex ${note ? "justify-center" : ours ? "justify-end" : "justify-start"} px-3 py-1`}
    >
      <div
        className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
          note
            ? "w-full border border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-100"
            : ours
              ? "bg-accent text-black"
              : "bg-background"
        }`}
      >
        {note && <p className="mb-1 text-xs font-semibold uppercase">{t("thread.note")}</p>}

        {message.attachment && message.type === "audio" && (
          <audio
            controls
            src={source(message.attachment.url)}
            aria-label={t("thread.voiceNote")}
            role="application"
            className="w-full"
          />
        )}
        {message.attachment && message.type === "image" && (
          // eslint-disable-next-line @next/next/no-img-element -- signed, short-lived link
          <img
            src={source(message.attachment.url)}
            alt={t("thread.photo")}
            className="max-h-80 rounded"
          />
        )}
        {message.attachment && !["audio", "image"].includes(message.type) && (
          <a href={source(message.attachment.url)} className="underline">
            {message.attachment.filename ?? t("thread.attachment")}
          </a>
        )}

        {message.text && <p className="whitespace-pre-wrap">{message.text}</p>}

        {message.transcript?.text ? (
          // Next to the audio, never instead of it: a wrong transcript has to be
          // checkable against what was actually said.
          <p className="text-muted mt-1 border-s-2 border-black/10 ps-2 text-xs italic dark:border-white/20">
            {String(message.transcript.text)}
          </p>
        ) : null}

        {!message.text && !message.attachment && !message.transcript && (
          <p className="text-muted italic">{t("thread.openOnPhone")}</p>
        )}

        <div className="text-muted mt-1 flex items-center gap-2 text-[11px]">
          <time dateTime={message.created_at}>{formatRelative(message.created_at)}</time>
          {message.origin === "phone_app" && <span>{t("thread.sentFromPhone")}</span>}
          {message.author?.name && ours && !note && <span>{message.author.name}</span>}
          {message.status && message.status !== "failed" && <span>{TICKS[message.status]}</span>}
        </div>

        {message.status === "failed" && (
          <p className="mt-1 text-xs text-red-700 dark:text-red-300">
            {t("thread.notDelivered")}
            {message.error?.message ? ` — ${String(message.error.message)}` : ""}{" "}
            {onRetry && (
              <button type="button" onClick={() => onRetry(message.id)} className="underline">
                {t("thread.retry")}
              </button>
            )}
          </p>
        )}
      </div>
    </li>
  );
}
