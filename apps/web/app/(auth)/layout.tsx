import { cookies } from "next/headers";
import { LocaleToggle } from "@/components/LocaleToggle";
import type { Locale } from "@/lib/i18n";
import { LocaleProvider } from "@/lib/i18n-client";

/** Every page outside a workspace — sign-in, sign-up, joining, the first
 *  workspace — in the language the cookie says, like the pages inside one. */
export default async function AuthLayout({ children }: { children: React.ReactNode }) {
  const locale = ((await cookies()).get("locale")?.value ?? "en") as Locale;
  return (
    <LocaleProvider locale={locale}>
      {/* The canvas, and on it one white card ([11] § 5.3): the same two
          things every page inside a workspace is made of. */}
      <div className="bg-ground min-h-screen">
        <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-4 p-4">
          <div className="flex items-center justify-between">
            <span
              role="img"
              aria-label="DealerAI"
              className="bg-accent text-on-accent grid size-11 place-items-center rounded-xl text-lg font-semibold"
            >
              D
            </span>
            <LocaleToggle locale={locale} />
          </div>
          <div className="bg-background flex flex-col gap-6 rounded-[1.375rem] p-6 shadow-sm">
            {children}
          </div>
        </main>
      </div>
    </LocaleProvider>
  );
}
