import type { NavItem } from "@/components/NavLinks";

/**
 * The settings sections, hidden when the role lacks their permission
 * (08-screens § 13). Quick replies has none: a salesperson reads them.
 * Notifications arrive with push in S7.
 */
export const SECTIONS: readonly NavItem[] = [
  { href: "/settings/channels", key: "settings.channels", permission: "settings.channels" },
  { href: "/settings/team", key: "settings.team", permission: "settings.team" },
  { href: "/settings/routing", key: "settings.routing", permission: "settings.routing" },
  { href: "/settings/pipelines", key: "settings.pipelines", permission: "pipeline.edit_stages" },
  { href: "/settings/quick-replies", key: "settings.quickReplies" },
  { href: "/settings/knowledge", key: "settings.knowledge", permission: "settings.knowledge" },
  { href: "/settings/ai", key: "settings.ai", permission: "settings.ai" },
];

/**
 * Whether the section at this path is this person's to open. The nav hides the
 * rest, and a typed URL must not show them either — the form would render,
 * and only Save would be refused. Undefined until their permissions load.
 */
export function mayOpen(
  pathname: string,
  permissions: readonly string[] | undefined,
): boolean | undefined {
  const section = SECTIONS.find((item) => pathname.endsWith(item.href));
  if (!section?.permission) return true;
  return permissions && permissions.includes(section.permission);
}

/** The first section somebody may open, for the bare /settings link. */
export function firstSection(permissions: readonly string[]): NavItem {
  return (
    SECTIONS.find((section) => !section.permission || permissions.includes(section.permission)) ??
    SECTIONS[4]
  );
}
