"use client";

import { useId, useState } from "react";
import { Auto } from "@/components/Bidi";
import { ApiError } from "@/lib/api/client";
import { useSendMessage, useTemplates, type Template } from "@/lib/api/hooks";
import { useT } from "@/lib/i18n-client";
import { word } from "@/lib/words";

const BLANK = /\{\{(\d+)\}\}/g;

/** The blanks a template has — {{1}}, {{2}} … — once each, in order. */
function blanks(body: string): number[] {
  return [...new Set([...body.matchAll(BLANK)].map((found) => Number(found[1])))].sort(
    (a, b) => a - b,
  );
}

/** The message as it will be read. A blank still empty stays visible as one. */
function filled(body: string, values: string[]): string {
  return body.replace(BLANK, (whole, n) => values[Number(n) - 1]?.trim() || whole);
}

/**
 * What each blank starts as. A template does not say what a blank is for, so
 * only one thing is assumed: a first blank followed by a comma is somebody
 * being greeted — "Hello {{1}}," — and takes the customer's first name.
 * ponytail: a guess from punctuation; WhatsApp's named parameters would say it
 * outright, if the templates are ever written with them.
 */
function starting(template: Template, customerName: string | null): string[] {
  const greeted = /\{\{1\}\}\s*[,،]/.test(template.body);
  const first = (customerName ?? "").trim().split(/\s+/)[0] ?? "";
  return blanks(template.body).map((n) => (n === 1 && greeted ? first : ""));
}

/**
 * What can be sent once the 24-hour window has closed: a template WhatsApp
 * approved, with its blanks filled ([08] § 4).
 *
 * It shows the message as the customer will read it before anything goes, and
 * will not send one with a blank left in it — WhatsApp would, as "{{2}}".
 */
export function TemplatePicker({
  conversationId,
  channelId,
  language = null,
  customerName = null,
  onSent,
}: {
  conversationId: string;
  channelId: string;
  /** The customer's, so their own language is offered first. */
  language?: string | null;
  customerName?: string | null;
  onSent?: () => void;
}) {
  const t = useT();
  const templates = useTemplates(channelId);
  const send = useSendMessage(conversationId);
  const [chosen, setChosen] = useState<Template | null>(null);
  const [values, setValues] = useState<string[]>([]);
  const caption = useId();

  const theirs = (template: Template) =>
    template.language.slice(0, 2) === (language ?? "").slice(0, 2);
  // Only what WhatsApp approved can be sent. The customer's language first;
  // otherwise in the order the channel lists them.
  const offered = (templates.data ?? [])
    .filter((template) => template.status === "approved")
    .sort((a, b) => Number(theirs(b)) - Number(theirs(a)));

  if (templates.isSuccess && offered.length === 0) {
    return <p className="text-muted text-sm">{t("template.none")}</p>;
  }

  const pick = (id: string) => {
    const template = offered.find((candidate) => candidate.id === id) ?? null;
    setChosen(template);
    setValues(template ? starting(template, customerName) : []);
  };
  const numbers = chosen ? blanks(chosen.body) : [];
  const complete = values.every((value) => value.trim());

  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1">
        <span className="text-muted text-xs">{t("thread.windowClosedHint")}</span>
        <select
          value={chosen?.id ?? ""}
          onChange={(event) => pick(event.target.value)}
          className="min-h-11 rounded-md border border-border bg-transparent px-2 text-sm"
        >
          <option value="">{t("template.pick")}</option>
          {offered.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name} ·{" "}
              {word(t, "language", template.language.slice(0, 2), template.language)}
            </option>
          ))}
        </select>
      </label>

      {chosen && (
        <>
          {numbers.map((n, index) => (
            <label key={n} className="flex items-center gap-2 text-sm">
              <span className="text-muted shrink-0 font-mono text-xs" dir="ltr" aria-hidden>
                {`{{${n}}}`}
              </span>
              <input
                value={values[index] ?? ""}
                aria-label={`${t("template.blank")} ${n}`}
                onChange={(event) =>
                  setValues(values.map((old, at) => (at === index ? event.target.value : old)))
                }
                className="min-h-11 min-w-0 flex-1 rounded-md border border-border px-3 text-sm"
                dir="auto"
              />
            </label>
          ))}

          {/* Drawn as the bubble it will be, so it is read as a message. */}
          <div role="group" aria-labelledby={caption} className="flex flex-col gap-1">
            <span id={caption} className="text-muted text-xs">
              {t("template.preview")}
            </span>
            <Auto
              as="p"
              className="bg-accent max-w-[80%] self-end whitespace-pre-wrap rounded-lg px-3 py-2 text-sm text-on-accent"
            >
              {filled(chosen.body, values)}
            </Auto>
          </div>
          <p className="text-muted text-xs">{t("template.paid")}</p>

          <button
            type="button"
            disabled={!complete || send.isPending}
            onClick={() =>
              send.mutate(
                { templateId: chosen.id, variables: values.map((value) => value.trim()) },
                {
                  onSuccess: () => {
                    pick("");
                    onSent?.();
                  },
                },
              )
            }
            className="bg-accent min-h-11 self-end rounded-md px-4 text-sm font-medium text-on-accent disabled:opacity-50"
          >
            {t("template.send")}
          </button>
        </>
      )}

      {send.isError && (
        <p role="alert" className="text-xs text-danger">
          {send.error instanceof ApiError
            ? (send.error.problem.detail ?? send.error.problem.title)
            : t("thread.sendFailed")}
        </p>
      )}
    </div>
  );
}
