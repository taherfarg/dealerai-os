import type { Metadata } from "next";
import { cookies } from "next/headers";
import { ServiceWorker } from "@/components/ServiceWorker";
import { dirFor, type Locale } from "@/lib/i18n";
import "./globals.css";

export const metadata: Metadata = {
  title: "DealerAI OS",
  description: "An autonomous AI marketing and sales department for automotive businesses.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // Locale lives in a cookie so the very first server render already has the
  // right dir. Deciding on the client would flash the layout the wrong way
  // round, which in RTL is the whole page jumping sides.
  const store = await cookies();
  const locale = ((await store.get("locale")?.value) ?? "en") as Locale;

  return (
    <html lang={locale} dir={dirFor(locale)}>
      <body className="antialiased">
        {children}
        <ServiceWorker />
      </body>
    </html>
  );
}
