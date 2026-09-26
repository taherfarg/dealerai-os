import { t, type Locale } from "@/lib/i18n";
import { cookies } from "next/headers";

/** The list is the layout; this is what the second pane says before you pick one. */
export default async function InboxPage() {
  const locale = ((await cookies()).get("locale")?.value ?? "en") as Locale;
  return (
    <div className="text-muted hidden h-full place-items-center p-8 text-sm lg:grid">
      {t(locale, "inbox.pickOne")}
    </div>
  );
}
