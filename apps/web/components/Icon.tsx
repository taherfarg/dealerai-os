import type { ReactNode } from "react";

/**
 * Every drawing the app has, by what it means here ([11] § 3.5): a stroke on a
 * 24 px grid, in the colour of the text around it. A drawing joins this table
 * in the step that first uses it.
 */
const DRAWINGS = {
  inbox: (
    <path d="M5 5.5h14A1.5 1.5 0 0 1 20.5 7v8a1.5 1.5 0 0 1-1.5 1.5h-9L5.5 20v-3.5H5A1.5 1.5 0 0 1 3.5 15V7A1.5 1.5 0 0 1 5 5.5z" />
  ),
  today: (
    <>
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 3.5v2M12 18.5v2M3.5 12h2M18.5 12h2M6 6l1.4 1.4M16.6 16.6 18 18M6 18l1.4-1.4M16.6 7.4 18 6" />
    </>
  ),
  customers: (
    <>
      <circle cx="9" cy="8.5" r="3" />
      <path d="M3.5 19c.6-3 2.7-4.5 5.5-4.5s4.9 1.5 5.5 4.5M15.5 5.8a3 3 0 0 1 0 5.4M17.5 14.7c1.6.7 2.6 2.1 3 4.3" />
    </>
  ),
  pipeline: (
    <>
      <rect x="4" y="4" width="4.5" height="16" rx="1.2" />
      <rect x="9.75" y="4" width="4.5" height="11" rx="1.2" />
      <rect x="15.5" y="4" width="4.5" height="7" rx="1.2" />
    </>
  ),
  tasks: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="m8.5 12.3 2.4 2.4 4.6-5.2" />
    </>
  ),
  dashboard: <path d="M5 20v-7M12 20V5M19 20V10" />,
  inventory: (
    <>
      <path d="M5 11l1.5-4a2 2 0 0 1 1.9-1.3h7.2a2 2 0 0 1 1.9 1.3L19 11" />
      <rect x="3" y="11" width="18" height="6" rx="2" />
      <path d="M6.5 17v2M17.5 17v2" />
    </>
  ),
  approvals: (
    <>
      <path d="M12 3.5 5 6v5.5c0 4 2.8 7 7 9 4.2-2 7-5 7-9V6z" />
      <path d="m9 12 2.2 2.2L15 10" />
    </>
  ),
  settings: (
    <>
      <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
      <circle cx="15" cy="7" r="2" />
      <circle cx="9" cy="17" r="2" />
    </>
  ),
  command: (
    <>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  content: (
    <>
      <path d="M6 3.5h8l4 4v13H6z" />
      <path d="M14 3.5v4h4M9 12h6M9 16h6" />
    </>
  ),
  bell: (
    <>
      <path d="M6.5 16v-5a5.5 5.5 0 0 1 11 0v5l1.5 2h-14z" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </>
  ),
  person: (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20c.8-3.5 3.5-5.5 7-5.5s6.2 2 7 5.5" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6 6 18" />,
  // The ones that point are mirrored in Arabic by whoever draws them.
  back: <path d="M19 12H5M11 6l-6 6 6 6" />,
  chevronUp: <path d="m7 14 5-5 5 5" />,
  chevronDown: <path d="m7 10 5 5 5-5" />,
  send: (
    <>
      <path d="M20 4 4 11l6.5 2.5L13 20z" />
      <path d="M20 4l-9.5 9.5" />
    </>
  ),
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  refresh: (
    <>
      <path d="M19 12a7 7 0 1 1-2.1-5" />
      <path d="M19 5v3.5h-3.5" />
    </>
  ),
  spark: <path d="M12 4l1.7 5.3L19 11l-5.3 1.7L12 18l-1.7-5.3L5 11l5.3-1.7z" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l2.5 2" />
    </>
  ),
  alert: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4.5M12 15.5v.5" />
    </>
  ),
  note: (
    <>
      <path d="M5 4h14v11l-5 5H5z" />
      <path d="M19 15h-5v5" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof DRAWINGS;

/**
 * Always hidden from a screen reader: the control an icon sits in has the
 * name, and an icon with a name of its own would be read twice.
 */
export function Icon({
  name,
  size = 20,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
    >
      {DRAWINGS[name]}
    </svg>
  );
}
