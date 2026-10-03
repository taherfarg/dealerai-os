import { defineConfig } from "@playwright/test";
import type { Options } from "./e2e/fixtures";
import { API_DIR, API_ENV, API_URL, WEB_ENV, WEB_URL } from "./e2e/stack";

const phone = { viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true };
const desk = { viewport: { width: 1440, height: 900 } };
const JOURNEY = /journey\.e2e\.ts/;

export default defineConfig<Options>({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  // One workspace in one database, put back before each test: two tests at once
  // would pull it out from under each other.
  // ponytail: one worker. A stack per worker when a run passes fifteen minutes.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: { baseURL: WEB_URL, trace: "retain-on-failure" },
  projects: [
    // The day's work in every combination (docs/sales/07-frontend.md § 11).
    { name: "journey-en-360", testMatch: JOURNEY, use: { ...phone, language: "en" } },
    { name: "journey-en-1440", testMatch: JOURNEY, use: { ...desk, language: "en" } },
    { name: "journey-ar-360", testMatch: JOURNEY, use: { ...phone, language: "ar" } },
    { name: "journey-ar-1440", testMatch: JOURNEY, use: { ...desk, language: "ar" } },
    // Everything else at the two ends: English on a desk, and Arabic on a phone,
    // which is where a layout breaks first. Who sees what, and what arrives
    // live, do not change with the language.
    { name: "en-1440", testIgnore: JOURNEY, use: { ...desk, language: "en" } },
    {
      name: "ar-360",
      testIgnore: [JOURNEY, /(visibility|live)\.e2e\.ts/],
      use: { ...phone, language: "ar" },
    },
  ],
  webServer: [
    {
      // Its database is made and migrated before the API opens a pool on it.
      command:
        "uv run python -m dealerai.scripts.migrate --create && uv run uvicorn dealerai.main:app --port 8100",
      cwd: API_DIR,
      env: API_ENV,
      url: `${API_URL}/internal/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
    {
      // A development server, because the local sign-in is compiled out of a
      // production build (lib/dev-auth.ts) — and that lock stays.
      command: "npx next dev --port 3100",
      env: WEB_ENV,
      url: `${WEB_URL}/dev-login`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
