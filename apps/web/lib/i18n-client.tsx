"use client";

import { createContext, useContext, type ReactNode } from "react";
import { type Locale, type MessageKey, t } from "./i18n";

const LocaleContext = createContext<Locale>("en");

export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

/** For content that arrives in both UI languages, like the brief's headline. */
export function useLocale(): Locale {
  return useContext(LocaleContext);
}

/** The message catalogue for client components, in the locale the server rendered. */
export function useT(): (key: MessageKey) => string {
  const locale = useContext(LocaleContext);
  return (key) => t(locale, key);
}
