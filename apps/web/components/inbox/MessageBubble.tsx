"use client";

import type { Message } from "@/lib/api/hooks";
import { API_BASE } from "@/lib/api/client";
import { Auto } from "@/components/Bidi";
import { formatRelative } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n-client";
import { eventText } from "@/lib/words";

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
  const locale = useLocale();

  if (message.kind === "event") {
    return (
      <li data-kind="event" className="my-2 text-center">
        <Auto className="text-muted text-xs">{eventText(t, message.event)}</Auto>
      </li>
    );
  }

  const note = message.kind === "note";
  const ours = message.direction === "out";
  const failed = message.status === "failed";
  // A message of ours is the accent's green — unless it did not go. Red on
  // that green is 1.4 to 1, and a message that failed must never pass for one
  // that was sent.
  const sent = ours && !note && !failed;
  // What is said quietly inside a bubble. Grey on the green of a sent message
  // cannot be read; the bubble's own white is 5.3 to 1.
  const quiet = sent ? "text-on-accent" : "text-muted";

  return (
    <li
      id={`message-${message.id}`}
      data-kind={message.kind}
      data-origin={message.origin}
      className={`flex ${note ? "justify-center" : ours ? "justify-end" : "justify-start"} px-3 py-0.5 lg:px-5`}
    >
      <div
        // A bubble has one tight corner, on the side it speaks from — written
        // with logical corners, so it turns with the language ([11] § 3.3).
        className={`max-w-[80%] px-3.5 py-2 text-base leading-6 lg:text-[15px] ${
          note
            ? "w-full rounded-2xl border border-warning/40 bg-warning-soft text-foreground"
            : sent
              ? "rounded-[1.375rem] rounded-ee-md bg-accent text-on-accent"
              : failed
                ? "rounded-[1.375rem] rounded-ee-md bg-danger-soft text-foreground"
                : "rounded-[1.375rem] rounded-es-md bg-background shadow-sm"
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
          <a href={source(message.attachment.url)} className="underline" dir="auto">
            {message.attachment.filename ?? t("thread.attachment")}
          </a>
        )}

        {/* Each message in the direction it was written ([07] § 6): a French
            question in an Arabic thread keeps its question mark at its end. */}
        {message.text && (
          <Auto as="p" className="whitespace-pre-wrap">
            {message.text}
          </Auto>
        )}

        {message.transcript?.text ? (
          // Next to the audio, never instead of it: a wrong transcript has to be
          // checkable against what was actually said.
          <Auto
            as="p"
            className={`${quiet} mt-1 border-s-2 border-border ps-2 text-xs italic`}
          >
            {String(message.transcript.text)}
          </Auto>
        ) : null}

        {!message.text && !message.attachment && !message.transcript && (
          <p className={`${quiet} italic`}>{t("thread.openOnPhone")}</p>
        )}

        <div className={`${quiet} mt-1 flex items-center gap-2 text-[11px]`}>
          <time dateTime={message.created_at}>{formatRelative(message.created_at, locale)}</time>
          {message.origin === "phone_app" && <span>{t("thread.sentFromPhone")}</span>}
          {message.author?.name && ours && !note && <span>{message.author.name}</span>}
          {message.status && message.status !== "failed" && <span>{TICKS[message.status]}</span>}
        </div>

        {message.status === "failed" && (
          <p className="mt-1 text-xs text-danger">
            {t("thread.notDelivered")}
            {message.error?.message ? (
              <>
                {" — "}
                <Auto>{String(message.error.message)}</Auto>
              </>
            ) : null}{" "}
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
