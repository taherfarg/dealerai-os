import { initials, tint } from "@/lib/avatar";
import { countryFlag } from "@/lib/format";
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

const SIZE = {
  sm: "size-7 text-[10px]",
  md: "size-9 text-xs",
  lg: "size-11 text-sm",
  xl: "size-14 text-lg",
} as const;

/**
 * A person, as a circle ([11] § 3.6): their initials on a tint that is always
 * theirs. Hidden from a screen reader — the name is beside it, or is the name
 * of the control it sits in.
 *
 * A customer's country rides on the corner: a flag where the system has
 * pictures of flags, and its two letters where it has not.
 */
export function Avatar({
  name,
  country,
  size = "md",
}: {
  name: string | null | undefined;
  country?: string | null;
  size?: keyof typeof SIZE;
}) {
  const letters = initials(name);
  const flag = countryFlag(country ?? null);
  return (
    <span
      aria-hidden="true"
      className={`relative grid shrink-0 place-items-center rounded-full font-semibold ${SIZE[size]} ${TINT[tint(name)]}`}
    >
      {letters || <Icon name="person" size={18} />}
      {flag && (
        <span className="bg-background text-foreground absolute -end-1.5 -bottom-1 grid min-w-4 place-items-center rounded-full px-0.5 text-[10px] leading-4 font-medium">
          {flag}
        </span>
      )}
    </span>
  );
}
