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

/** The first section somebody may open, for the bare /settings link. */
export function firstSection(permissions: readonly string[]): NavItem {
  return (
    SECTIONS.find((section) => !section.permission || permissions.includes(section.permission)) ??
    SECTIONS[4]
  );
}
