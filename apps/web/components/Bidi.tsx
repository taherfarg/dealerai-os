"use client";

import type { ReactNode } from "react";
import { countryFlag } from "@/lib/format";
import { useT } from "@/lib/i18n-client";

/**
 * What is a number stays the way it is written — a phone number, a price, a
 * score — whatever the language around it ([07] § 6). Without this an Arabic
 * line moves the plus sign of +971… to the other end.
 *
 * Inline, inside an element that keeps the page's direction: as a block of its
 * own it would also carry the number to the left edge of an Arabic screen.
 */
export function Ltr({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <span dir="ltr" className={`tabular-nums ${className}`}>
      {children}
    </span>
  );
}

/**
 * What a person wrote chooses its own direction: a name, a message, a title.
 * On the element that truncates, so a Latin name in an Arabic line loses its
 * end and not its beginning.
 */
export function Auto({
  children,
  className = "",
  as: Tag = "span",
}: {
  children: ReactNode;
  className?: string;
  as?: "span" | "p" | "div";
}) {
  return (
    <Tag dir="auto" className={className}>
      {children}
    </Tag>
  );
}

/**
 * A sentence written for this reader somewhere else — a notification — which
 * may begin with a name in another script: "James Whitfield أصبح من عملائك".
 * The server sets such names apart with isolates, and the sentence runs the way
 * its own first letter outside them does. `unicode-bidi: plaintext` reads it
 * that way; `dir="auto"` takes the J and turns the line left to right.
 */
export function Sentence({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`[unicode-bidi:plaintext] ${className}`}>{children}</span>;
}

/**
 * A customer's name beside their flag. The flag stays outside the name: a flag
 * is two left-to-right characters, and inside `dir="auto"` it would be the
 * first thing read and turn an Arabic name left to right.
 */
export function CustomerName({
  country,
  name,
  className = "",
  wrap = false,
}: {
  country: string | null | undefined;
  name: string | null | undefined;
  className?: string;
  /** For a page's heading, where a long name takes a second line instead of being cut. */
  wrap?: boolean;
}) {
  const t = useT();
  const flag = countryFlag(country ?? null);
  return (
    <span className={`flex min-w-0 items-baseline gap-1 ${className}`}>
      {flag && <span className="shrink-0">{flag}</span>}
      <Auto className={wrap ? "min-w-0" : "min-w-0 truncate"}>
        {name ?? t("inbox.unknownCustomer")}
      </Auto>
    </span>
  );
}
