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
      <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-6 p-6">
        <div className="flex justify-end">
          <LocaleToggle locale={locale} />
        </div>
        {children}
      </main>
    </LocaleProvider>
  );
}
