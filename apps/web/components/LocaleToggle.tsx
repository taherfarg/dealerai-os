import { setLocale } from "@/app/actions";
import { LOCALES, type Locale } from "@/lib/i18n";

/**
 * A server component: no client bundle, and it works without JavaScript.
 * The cookie is set server-side so the very next render already has the right
 * `dir` — see app/actions.ts.
 */
export function LocaleToggle({ locale }: { locale: Locale }) {
  return (
    <form action={setLocale} className="border-border flex overflow-hidden rounded-full border text-xs">
      {LOCALES.map((l) => (
        <button
          key={l}
          type="submit"
          name="locale"
          value={l}
          aria-pressed={l === locale}
          className={`min-h-11 min-w-11 px-2 uppercase transition-colors ${
            l === locale ? "bg-accent text-on-accent" : "hover:bg-surface"
          }`}
        >
          {l}
        </button>
      ))}
    </form>
  );
}
