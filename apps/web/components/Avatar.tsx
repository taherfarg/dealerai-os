import { initials, tint } from "@/lib/avatar";
import { Icon } from "./Icon";

// Each class written out whole: Tailwind finds classes by reading this file.
const TINT = [
  "bg-tint-0 text-tint-0-ink",
  "bg-tint-1 text-tint-1-ink",
  "bg-tint-2 text-tint-2-ink",
  "bg-tint-3 text-tint-3-ink",
  "bg-tint-4 text-tint-4-ink",
  "bg-tint-5 text-tint-5-ink",
  "bg-tint-6 text-tint-6-ink",
] as const;

/**
 * A person, as a circle ([11] § 3.6): their initials on a tint that is always
 * theirs. Hidden from a screen reader — the name is beside it, or is the name
 * of the control it sits in.
 */
export function Avatar({ name }: { name: string | null | undefined }) {
  const letters = initials(name);
  return (
    <span
      aria-hidden="true"
      className={`grid size-9 shrink-0 place-items-center rounded-full text-xs font-semibold ${TINT[tint(name)]}`}
    >
      {letters || <Icon name="person" size={18} />}
    </span>
  );
}
