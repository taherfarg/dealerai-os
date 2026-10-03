import Link from "next/link";

export type Tone = "ok" | "warn" | "bad";

/** Green within the target, amber within twice it, red beyond. */
export function tone(seconds: number | null | undefined, target: number): Tone | null {
  if (seconds == null) return null;
  if (seconds <= target) return "ok";
  return seconds <= 2 * target ? "warn" : "bad";
}

const EDGE: Record<Tone, string> = {
  ok: "border-s-4 border-s-green-500",
  warn: "border-s-4 border-s-amber-500",
  bad: "border-s-4 border-s-red-500",
};

/**
 * A number, its name, and — when there is one — the list it counted
 * (08-screens § 11: every tile opens the rows behind it).
 *
 * The colour is never the only signal: a tile against a target says the
 * target in `hint`, so a colour-blind manager reads the same thing.
 */
export function StatTile({
  label,
  value,
  href,
  hint,
  tone,
}: {
  label: string;
  value: string;
  href?: string;
  hint?: string;
  tone?: Tone | null;
}) {
  const body = (
    <div className={`bg-surface border-border h-full rounded-lg border p-3 ${tone ? EDGE[tone] : ""}`}>
      {/* No dir here: a duration's units are the reader's, and a bare count
          reads the same either way. */}
      <p className="text-xl font-semibold tabular-nums">
        {value}
      </p>
      <p className="text-muted text-xs">{label}</p>
      {hint && <p className="text-muted text-[11px]">{hint}</p>}
    </div>
  );
  return href ? (
    <Link href={href} className="block h-full hover:opacity-90">
      {body}
    </Link>
  ) : (
    body
  );
}
