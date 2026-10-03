/**
 * The end-to-end suite's own stack: its own database, its own API and its own
 * web server. A run never empties the workspace somebody is looking at, never
 * buys anything from a model, and meets the same thing on a laptop and in CI.
 */
import path from "node:path";

// Windows sometimes reserves the range that holds 54332; the container is then
// started on another port, and the suite is told which.
const DB_PORT = process.env.E2E_DB_PORT ?? "54332";
const DATABASE = "dealerai_e2e";

export const API_URL = "http://localhost:8100";
export const WEB_URL = "http://localhost:3100";
export const API_DIR = path.resolve(__dirname, "../../api");

/** Every setting the suite's API reads, spelled out: nothing is left to a developer's .env. */
export const API_ENV = {
  ENV: "local",
  LOG_LEVEL: "warning",
  DATABASE_URL: `postgresql://dealerai_app:dealerai_app@localhost:${DB_PORT}/${DATABASE}`,
  MIGRATION_DATABASE_URL: `postgresql://postgres:postgres@localhost:${DB_PORT}/${DATABASE}`,
  // Blank on purpose: no run buys anything, and no draft appears that the seed did not write.
  GOOGLE_API_KEY: "",
  SUPABASE_URL: "",
  SUPABASE_ANON_KEY: "",
  // The Supabase CLI's well-known local secret, as in .env.example and ci.yml.
  SUPABASE_JWT_SECRET: "super-secret-jwt-token-with-at-least-32-characters-long",
  WEB_ORIGINS: WEB_URL,
  STORAGE_DIR: ".storage/e2e",
  VAPID_PRIVATE_KEY: "",
};

export const WEB_ENV = {
  NEXT_PUBLIC_DEV_AUTH: "1",
  NEXT_PUBLIC_API_URL: API_URL,
  // Placeholders, as in CI's build: with the local sign-in on, nothing calls Supabase.
  NEXT_PUBLIC_SUPABASE_URL: "https://placeholder.supabase.co",
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "placeholder-anon-key",
  E2E: "1",
};
