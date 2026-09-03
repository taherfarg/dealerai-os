"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { LOCALES, type Locale } from "@/lib/i18n";

/**
 * Switch UI language.
 *
 * A server action rather than a `document.cookie` write on the client: the next
 * render then already knows the direction, so the layout never flashes the
 * wrong way round — which in RTL means the whole page visibly jumps sides. It
 * also works with JavaScript disabled, and it keeps the cookie write out of a
 * component body, which React Compiler correctly refuses.
 */
export async function setLocale(formData: FormData) {
  const requested = String(formData.get("locale"));
  // Never trust a form value as a cookie value.
  const locale = (LOCALES as readonly string[]).includes(requested)
    ? (requested as Locale)
    : "en";

  const store = await cookies();
  store.set("locale", locale, {
    path: "/",
    maxAge: 60 * 60 * 24 * 365,
    sameSite: "lax",
  });

  revalidatePath("/", "layout");
}
