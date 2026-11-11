/**
 * Joining (docs/sales/08-screens.md § 14, and Part A's exit): an owner invites
 * a salesperson by a link; she joins with the invited address and lands in the
 * inbox with the invited role and team.
 *
 * A laptop has no Supabase Auth, so "creating an account" here is the local
 * sign-in's "somebody new" — which puts her where Supabase would. The real
 * round trip is staging's.
 */
import type { Page } from "@playwright/test";
import { PEOPLE, WORKSPACE, expect, reads, signInAs, test, type Say } from "./fixtures";

const LAYLA = { email: "layla@e2e.test", name: "Layla Hassan" };

/** The owner makes an invitation on the Team screen and reads its link off the page. */
async function invites(page: Page, say: Say, email: string): Promise<string> {
  await signInAs(page, PEOPLE.owner, `${WORKSPACE}/settings/team`);
  const form = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: say("invite.title") }) });
  await form.getByRole("textbox", { name: say("invite.email") }).fill(email);
  await form.getByRole("combobox", { name: say("team.role") }).selectOption("sales");
  await form.getByRole("checkbox", { name: "Local sales" }).check();
  await form.getByRole("button", { name: say("invite.create") }).click();
  await expect(form.getByText(say("invite.ready"))).toBeVisible();
  const link = await form.locator("input[readonly]").inputValue();
  expect(link).toContain("/accept-invite?token=");
  return link;
}

/** The local sign-in's own form, which is English wherever it is. */
async function signsInAsSomebodyNew(page: Page, email: string, name: string) {
  await page.waitForURL((url) => url.pathname === "/dev-login");
  // The seeded people are listed once the page is running: until then the form
  // below them would lose what is typed into it.
  await expect(page.getByRole("button", { name: PEOPLE.owner })).toBeVisible();
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByRole("textbox", { name: "Name" }).fill(name);
  await page.getByRole("button", { name: "Sign in as them" }).click();
}

test("the owner invites a salesperson into a team; she joins with that address and lands in the inbox as that", async ({
  page,
  say,
  browser,
  language,
}) => {
  const link = await invites(page, say, LAYLA.email);

  // Layla, on her own phone, signed in to nothing.
  const hers = await browser.newContext({ viewport: page.viewportSize() });
  await reads(hers, language);
  const her = await hers.newPage();
  await her.goto(link);
  await expect(her.getByText(say("accept.invitedTo"))).toBeVisible();
  await expect(her.getByRole("heading", { level: 1 })).toHaveText("Pollux Motors");
  await expect(her.getByText(`${say("accept.role")} ${say("role.sales")}`)).toBeVisible();

  await her.getByRole("link", { name: say("accept.createAccount") }).click();
  await signsInAsSomebodyNew(her, LAYLA.email, LAYLA.name);

  // Back at the invitation, which survived the detour.
  await her.waitForURL((url) => url.pathname === "/accept-invite");
  await her.getByRole("button", { name: say("accept.join") }).click();
  await her.waitForURL((url) => url.pathname === `${WORKSPACE}/inbox`);

  // In the team she was invited into: its unassigned customer is hers to take.
  await her.getByRole("tab", { name: say("inbox.tabs.unassigned") }).click();
  await expect(her.locator("li[data-sla]").filter({ hasText: "James Whitfield" })).toHaveCount(1);
  // And a salesperson: nobody else's customers, and no dashboard.
  await expect(her.locator("li[data-sla]").filter({ hasText: "Omar Al Mazrouei" })).toHaveCount(0);
  await expect(
    her.getByRole("navigation", { name: say("nav.main") }).getByRole("link", { name: say("nav.dashboard") }),
  ).toHaveCount(0);
  await hers.close();

  // The owner sees her, by her name, with her role and her team.
  await page.reload();
  const row = page.locator("li").filter({ hasText: LAYLA.name });
  await expect(row.getByRole("combobox", { name: say("team.role") })).toHaveValue("sales");
  await expect(row.getByRole("checkbox", { name: "Local sales" })).toBeChecked();
  await expect(row.getByRole("checkbox", { name: "Export" })).not.toBeChecked();
});

test("an invitation is for one address: somebody else is told so, and offered the way out", async ({
  page,
  say,
  browser,
  language,
}) => {
  const link = await invites(page, say, LAYLA.email);

  const his = await browser.newContext();
  await reads(his, language);
  const ahmed = await his.newPage();
  await signInAs(ahmed, PEOPLE.ahmed);
  await ahmed.goto(link);

  await expect(ahmed.getByText(say("accept.forEmail"))).toContainText(LAYLA.email);
  await expect(ahmed.getByText(say("accept.signedInAs"))).toBeVisible();
  await expect(ahmed.getByRole("button", { name: say("accept.signOut") })).toBeVisible();
  await expect(ahmed.getByRole("button", { name: say("accept.join") })).toHaveCount(0);
  await his.close();
});

test("an address that is not an invitation says so", async ({ page, say }) => {
  await page.goto("/accept-invite?token=nonsense");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(say("accept.title"));
  await expect(page.getByRole("alert").filter({ hasText: say("accept.invalid") })).toBeVisible();
  await expect(page.getByRole("button", { name: say("accept.join") })).toHaveCount(0);
});

test("somebody with no workspace makes one, and is in it", async ({ page, say }) => {
  // Its own address and its own person each run: the suite's database outlives
  // a run, and somebody who already has a workspace is not asked to make one.
  const run = Date.now().toString(36);
  const founder = { email: `founder-${run}@e2e.test`, name: "Noura Al Falasi" };

  await page.goto("/dev-login");
  await signsInAsSomebodyNew(page, founder.email, founder.name);
  await page.waitForURL((url) => url.pathname === "/onboarding");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(say("onboarding.title"));

  await page.getByLabel(say("onboarding.name")).fill(`Falasi Motors ${run}`);
  await page.getByLabel(say("onboarding.slug")).fill(`falasi-${run}`);
  await page.getByRole("button", { name: say("onboarding.create") }).click();

  // Straight to the team: the next thing a new owner does is invite somebody.
  await page.waitForURL((url) => url.pathname === `/falasi-${run}/settings/team`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(say("settings.team"));
  const row = page.locator("li").filter({ hasText: founder.name });
  await expect(row.getByRole("combobox", { name: say("team.role") })).toHaveValue("owner");
});
