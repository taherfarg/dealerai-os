export const LOCALES = ["en", "ar"] as const;
export type Locale = (typeof LOCALES)[number];

export const RTL_LOCALES = new Set<Locale>(["ar"]);

export function dirFor(locale: Locale): "ltr" | "rtl" {
  return RTL_LOCALES.has(locale) ? "rtl" : "ltr";
}

/**
 * Minimal message catalogue.
 *
 * A full i18n library buys plurals, dates and namespacing we do not need yet —
 * the tenant-facing surface is a handful of nav labels. The product's real
 * multilingual work is in generated content and customer replies, which never
 * touch this file.
 */
const MESSAGES = {
  en: {
    "nav.command": "Command Center",
    "nav.inventory": "Inventory",
    "nav.content": "Content",
    "nav.inbox": "Inbox",
    "nav.leads": "Leads",
    "nav.approvals": "Approvals",
    "nav.analytics": "Analytics",
    "nav.settings": "Settings",
    "approvals.title": "Approvals",
    "approvals.empty": "Nothing waiting on you.",
    "approvals.approve": "Approve",
    "approvals.reject": "Reject",
    "approvals.requires": "Requires",
    "auth.signIn": "Sign in",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.working": "Signing in…",
    "workspace.switch": "Workspace",
    "workspace.none": "No workspace yet",
  },
  ar: {
    "nav.command": "مركز القيادة",
    "nav.inventory": "المخزون",
    "nav.content": "المحتوى",
    "nav.inbox": "الرسائل",
    "nav.leads": "العملاء المحتملون",
    "nav.approvals": "الموافقات",
    "nav.analytics": "التحليلات",
    "nav.settings": "الإعدادات",
    "approvals.title": "الموافقات",
    "approvals.empty": "لا يوجد ما ينتظر موافقتك.",
    "approvals.approve": "موافقة",
    "approvals.reject": "رفض",
    "approvals.requires": "يتطلب",
    "auth.signIn": "تسجيل الدخول",
    "auth.email": "البريد الإلكتروني",
    "auth.password": "كلمة المرور",
    "auth.working": "جارٍ تسجيل الدخول…",
    "workspace.switch": "مساحة العمل",
    "workspace.none": "لا توجد مساحة عمل",
  },
} as const;

export type MessageKey = keyof (typeof MESSAGES)["en"];

export function t(locale: Locale, key: MessageKey): string {
  return MESSAGES[locale][key] ?? MESSAGES.en[key] ?? key;
}
