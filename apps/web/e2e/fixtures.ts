import { execFileSync } from "node:child_process";
import { expect, test as base, type BrowserContext, type Page } from "@playwright/test";
// By their paths, not through "@/": these two files import nothing but each other.
import { ar } from "../messages/ar";
import { en } from "../messages/en";
import { API_DIR, API_ENV, WEB_URL } from "./stack";

export type Language = "en" | "ar";
export type Key = keyof typeof en;
export type Say = (key: Key) => string;
export type Options = { language: Language };

const WORDS = { en, ar } as const;

export const WORKSPACE = "/pollux-motors";

/** The seeded five (apps/api/src/dealerai/scripts/seed_sales.py). */
export const PEOPLE = {
  owner: "Khalid Al Suwaidi",
  manager: "Sara Mansour",
  ahmed: "Ahmed Nasser", // sales, Local sales
  mohamed: "Mohamed Riad", // sales, Local sales
  salem: "Salem Bousaid", // sales, Export
} as const;

/** The workspace as `npm run db:seed` leaves it, in the suite's own database. */
export function reseed(): void {
  execFileSync("uv", ["run", "python", "-m", "dealerai.scripts.seed_sales"], {
    cwd: API_DIR,
    env: { ...process.env, ...API_ENV },
    stdio: ["ignore", "ignore", "inherit"],
  });
}

/** The reader's language is a cookie the app reads on the server. */
export async function reads(context: BrowserContext, language: Language): Promise<void> {
  await context.addCookies([{ name: "locale", value: language, url: WEB_URL }]);
}

/** Through the local sign-in page, as a person would. */
export async function signInAs(page: Page, person: string, next = `${WORKSPACE}/inbox`) {
  await page.goto(`/dev-login?next=${encodeURIComponent(next)}`);
  await page.getByRole("button", { name: person }).click();
  await page.waitForURL((url) => url.pathname + url.search === next);
}

/**
 * An address inside the workspace, typed in — and ready to be used.
 *
 * The server draws the page before the browser has made it work: a tab pressed
 * in that gap does nothing, and a choice made in it is put back. The first
 * thing the app does once it is running is ask who is signed in, so that
 * answer is the sign that it can be pressed.
 */
export async function arrive(page: Page, path: string) {
  const running = page.waitForResponse((response) => new URL(response.url()).pathname === "/v1/me");
  await page.goto(`${WORKSPACE}${path}`);
  await running;
}

const SECTIONS = {
  "nav.inbox": "/inbox",
  "nav.today": "/today",
  "nav.customers": "/customers",
  "nav.pipeline": "/pipeline",
  "nav.tasks": "/tasks",
  "nav.dashboard": "/dashboard",
  "nav.settings": "/settings",
} as const;

/** By the navigation where the navigation has it. A phone's bar holds five, and
 *  a salesperson's has no dashboard: the rest by its address. */
export async function visit(page: Page, say: Say, section: keyof typeof SECTIONS) {
  const link = page
    .getByRole("navigation", { name: say("nav.main") })
    .getByRole("link", { name: say(section) });
  if (await link.count()) await link.click();
  else await arrive(page, SECTIONS[section]);
  await page.waitForURL((url) => url.pathname.startsWith(`${WORKSPACE}${SECTIONS[section]}`));
}

/** Nothing on this page is wider than the screen it is on. */
export async function fits(page: Page): Promise<void> {
  const [content, screen] = await page.evaluate(() => [
    document.documentElement.scrollWidth,
    document.documentElement.clientWidth,
  ]);
  expect(content, "the page scrolls sideways").toBeLessThanOrEqual(screen);
}

type Fixtures = { say: Say; phone: boolean; freshWorkspace: void };

// The second argument of a fixture is `run`, not Playwright's usual `use`: the
// React lint rules take any call to `use(…)` for the hook.
export const test = base.extend<Fixtures & Options>({
  language: ["en", { option: true }],
  context: async ({ context, language }, run) => {
    await reads(context, language);
    await run(context);
  },
  say: async ({ language }, run) => {
    await run((key) => WORDS[language][key]);
  },
  // Tailwind's `md`: below it the navigation is the bar at the foot of the screen.
  phone: async ({ viewport }, run) => {
    await run((viewport?.width ?? 1440) < 768);
  },
  // Every test starts from the seed, whatever the one before it did.
  freshWorkspace: [
    // An empty pattern, because Playwright reads it for which fixtures to build first.
    async ({}, run) => {
      reseed();
      await run();
    },
    { auto: true },
  ],
});

export { expect };
