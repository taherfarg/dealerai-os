/**
 * The shell (docs/sales/08-screens.md § 1), and S0's exit: it opens as any
 * seeded person, in their language, with the navigation their role has.
 */
import { PEOPLE, WORKSPACE, arrive, expect, fits, signInAs, test } from "./fixtures";

test("each of the seeded five opens the inbox, in the reader's language and direction", async ({
  page,
  say,
  language,
}) => {
  for (const person of Object.values(PEOPLE)) {
    await signInAs(page, person);

    await expect(page.locator("html")).toHaveAttribute("lang", language);
    await expect(page.locator("html")).toHaveAttribute("dir", language === "ar" ? "rtl" : "ltr");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(say("nav.inbox"));

    const here = page
      .getByRole("navigation", { name: say("nav.main") })
      .getByRole("link", { name: say("nav.inbox") });
    await expect(here, person).toHaveAttribute("aria-current", "page");
    await fits(page);
  }
});

test("the dashboard is offered to those who run the team, and to nobody else", async ({
  page,
  say,
  phone,
}) => {
  const offered = page
    .getByRole("navigation", { name: say("nav.main") })
    .getByRole("link", { name: say("nav.dashboard") });

  for (const person of [PEOPLE.owner, PEOPLE.manager]) {
    await signInAs(page, person);
    // A phone's bar holds five destinations, and the dashboard is not one of them.
    await expect(offered, person).toHaveCount(phone ? 0 : 1);
    await arrive(page, "/dashboard");
    await expect(page.getByRole("heading", { name: say("dashboard.waiting") })).toBeVisible();
  }

  await signInAs(page, PEOPLE.ahmed);
  await expect(offered).toHaveCount(0);
  await arrive(page, "/dashboard");
  await expect(page.getByText(say("dashboard.forManagers"))).toBeVisible();
  await page.getByRole("link", { name: say("dashboard.openMyDay") }).click();
  await page.waitForURL((url) => url.pathname === `${WORKSPACE}/today`);
});

test("signed out, an address inside the workspace leads to sign-in and back", async ({
  page,
  say,
}) => {
  await page.goto(`${WORKSPACE}/customers`);
  await page.waitForURL((url) => url.pathname === "/dev-login");
  expect(new URL(page.url()).searchParams.get("next")).toBe(`${WORKSPACE}/customers`);

  await page.getByRole("button", { name: PEOPLE.ahmed }).click();
  await page.waitForURL((url) => url.pathname === `${WORKSPACE}/customers`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(say("customers.title"));
});

test("the app can be installed by somebody signed out", async ({ page, request }) => {
  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.status()).toBe(200);
  const described = await manifest.json();
  expect(described).toMatchObject({ name: "DealerAI", start_url: "/", display: "standalone" });
  expect(described.icons.length).toBeGreaterThan(0);
  for (const icon of described.icons as { src: string }[]) {
    const drawn = await request.get(icon.src);
    expect(drawn.status(), icon.src).toBe(200);
    expect(drawn.headers()["content-type"]).toContain("image/png");
  }

  const worker = await request.get("/sw.js");
  expect(worker.status()).toBe(200);
  expect(worker.headers()["content-type"]).toContain("javascript");

  // What the worker shows when there is no network (Part B).
  await page.goto("/offline.html");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
});
