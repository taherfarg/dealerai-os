import { setLocale } from "@/app/actions";
import { LOCALES, type Locale } from "@/lib/i18n";

/**
 * A server component: no client bundle, and it works without JavaScript.
 * The cookie is set server-side so the very next render already has the right
 * `dir` — see app/actions.ts.
 */
export function LocaleToggle({ locale }: { locale: Locale }) {
  return (
    <form action={setLocale} className="border-border flex overflow-hidden rounded-md border text-xs">
      {LOCALES.map((l) => (
        <button
          key={l}
          type="submit"
          name="locale"
          value={l}
          aria-pressed={l === locale}
          className={`px-2 py-1 uppercase transition-colors ${
            l === locale ? "bg-brand text-white" : "hover:bg-background"
          }`}
        >
          {l}
        </button>
      ))}
    </form>
  );
}
