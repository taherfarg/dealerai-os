/**
 * The day's work (docs/sales/07-frontend.md § 11): sign in, the inbox, a reply
 * from a draft, a lead made and moved, a follow-up sent, the manager's
 * dashboard — as a salesperson, a manager and the owner. The projects run it in
 * both languages, on a phone and on a desk.
 *
 * The seed decides who can do what. Omar is Ahmed's: he is waiting, and a draft
 * is ready for him. Priya is Ahmed's and has no lead. Karim is Salem's: his
 * 24 hours are over, and the copilot has a template ready to follow up with.
 */
import type { Page } from "@playwright/test";
import {
  PEOPLE,
  WORKSPACE,
  arrive,
  expect,
  fits,
  signInAs,
  test,
  visit,
  type Key,
  type Say,
} from "./fixtures";

const OMAR = "Omar Al Mazrouei";
const PRIYA = "Priya Nair";
const KARIM = "Karim Benali";
const JAMES = "James Whitfield";
/** What the seeded draft and the seeded follow-up both quote. */
const PRICE = "AED 128,000";
const FOLLOW_UP = "Price drop";

test.beforeEach(() => {
  test.setTimeout(150_000);
});

const messages = (page: Page, say: Say) =>
  page.getByRole("log", { name: say("thread.messages") }).locator('li[data-kind="message"]');

const column = (page: Page, stage: string) =>
  page
    .locator("section[data-stage]")
    .filter({ has: page.getByRole("heading", { name: stage, exact: true }) });

const leadOf = (page: Page, stage: string, customer: string) =>
  column(page, stage).locator("li[data-lead]").filter({ hasText: customer });

async function open(page: Page, say: Say, tab: Key, customer: string) {
  await page.getByRole("tab", { name: say(tab) }).click();
  await page.locator("li[data-sla]").filter({ hasText: customer }).getByRole("link").click();
  await expect(page.locator("[data-thread]").getByRole("heading", { level: 1 })).toContainText(
    customer,
  );
}

/** Steps 1 to 3: the inbox, the conversation, the draft sent. */
async function answersOmarFromTheDraft(page: Page, say: Say, phone: boolean, tab: Key) {
  await page.getByRole("tab", { name: say(tab) }).click();
  const row = page.locator("li[data-sla]").filter({ hasText: OMAR });
  // In words, not only in red: he has waited past the target.
  await expect(row).toContainText(say("inbox.missed"));
  await fits(page);

  await open(page, say, tab, OMAR);
  const back = page.getByRole("link", { name: say("thread.back") });
  if (phone) await expect(back).toBeVisible();
  else await expect(page.getByRole("tablist", { name: say("nav.inbox") })).toBeVisible();

  const draft = page.getByRole("region", { name: say("draft.title") });
  await expect(draft).toContainText(PRICE);
  await expect(draft).toContainText(say("draft.basedOn"));
  await expect(messages(page, say).first()).toBeVisible();
  const before = await messages(page, say).count();
  await fits(page);

  await draft.getByRole("button", { name: say("draft.send") }).click();
  await expect(messages(page, say)).toHaveCount(before + 1);
  await expect(messages(page, say).last()).toContainText(PRICE);
  await expect(draft).toHaveCount(0);
  if (phone) await back.click();
}

/** Step 4: a lead for somebody who has none, from the panel beside their conversation. */
async function makesPriyaALead(page: Page, say: Say, phone: boolean, tab: Key) {
  await open(page, say, tab, PRIYA);
  await page.getByRole("button", { name: say("customer.details") }).click();
  const panel = page.locator("[data-customer-panel]");
  await panel.getByRole("button", { name: say("customer.createLead") }).click();
  await expect(panel.locator('a[href*="/pipeline?lead="]')).toContainText("New");
  await expect(panel.getByRole("button", { name: say("customer.createLead") })).toHaveCount(0);
  await fits(page);
  // On a phone the panel is a dialog over the conversation.
  if (phone) await page.keyboard.press("Escape");
}

/** Step 5: the board. */
async function movesTheLead(page: Page, say: Say) {
  await visit(page, say, "nav.pipeline");
  await expect(leadOf(page, "New", PRIYA)).toHaveCount(1);
  await fits(page);
  await leadOf(page, "New", PRIYA)
    .getByLabel(say("pipeline.moveTo"))
    .selectOption({ label: "Contacted" });
  await expect(leadOf(page, "Contacted", PRIYA)).toHaveCount(1);
  await expect(leadOf(page, "New", PRIYA)).toHaveCount(0);
  await page.reload();
  await expect(leadOf(page, "Contacted", PRIYA)).toHaveCount(1);
}

/** Step 6: the follow-up the copilot prepared for Karim, sent as it stands. */
async function sendsTheFollowUp(page: Page, say: Say, tab: Key) {
  const card = page.locator("li[data-task]").filter({ hasText: FOLLOW_UP });
  // Due in three hours: today's, unless the workspace's day ends first.
  await expect(async () => {
    for (const bucket of ["tasks.today", "tasks.upcoming"] as const) {
      await page.getByRole("tab", { name: say(bucket) }).click();
      await page.waitForTimeout(300);
      if (await card.isVisible()) return;
    }
    throw new Error("the follow-up is under neither Today nor Upcoming");
  }).toPass({ timeout: 20_000 });

  // The message that would go, not the template's name — and why it is a template.
  await expect(card).toContainText(`Bonjour Karim, le prix de Toyota Hilux 2.8 Diesel est maintenant ${PRICE}.`);
  await expect(card).toContainText(say("followup.windowClosed"));
  await fits(page);

  await card.getByRole("button", { name: say("followup.send") }).click();
  await page.getByRole("tab", { name: say("tasks.done") }).click();
  await expect(card).toBeVisible();
  await expect(card.getByRole("checkbox", { name: say("tasks.complete") })).toBeChecked();

  await visit(page, say, "nav.inbox");
  await open(page, say, tab, KARIM);
  await expect(messages(page, say).last()).toContainText(`maintenant ${PRICE}`);
}

/** Step 7, for those who run the team. */
async function readsTheDashboard(page: Page, say: Say) {
  await visit(page, say, "nav.dashboard");
  const waiting = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: say("dashboard.waiting") }) });
  // Nobody has taken James; Omar has just been answered.
  await expect(waiting).toContainText(JAMES);
  await expect(waiting).not.toContainText(OMAR);
  await expect(page.getByRole("heading", { name: say("dashboard.team"), exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: say("dashboard.pipeline") })).toBeVisible();
  await fits(page);
}

test("a salesperson's day", async ({ page, say, phone }) => {
  await signInAs(page, PEOPLE.ahmed);
  await answersOmarFromTheDraft(page, say, phone, "inbox.tabs.mine");
  await makesPriyaALead(page, say, phone, "inbox.tabs.mine");
  await movesTheLead(page, say);

  // The dashboard is not his, whatever the address.
  await arrive(page, "/dashboard");
  await expect(page.getByText(say("dashboard.forManagers"))).toBeVisible();

  // Karim is Salem's, and so is the follow-up.
  await signInAs(page, PEOPLE.salem, `${WORKSPACE}/tasks`);
  await sendsTheFollowUp(page, say, "inbox.tabs.mine");
});

test("a manager's day", async ({ page, say, phone }) => {
  await signInAs(page, PEOPLE.manager);
  await answersOmarFromTheDraft(page, say, phone, "inbox.tabs.team");
  await makesPriyaALead(page, say, phone, "inbox.tabs.team");
  await movesTheLead(page, say);

  await visit(page, say, "nav.tasks");
  await page
    .getByRole("combobox", { name: say("tasks.team"), exact: true })
    .selectOption({ label: say("tasks.team") });
  await expect(page).toHaveURL(/assignee=team/);
  await sendsTheFollowUp(page, say, "inbox.tabs.team");
  await readsTheDashboard(page, say);
});

test("the owner's day", async ({ page, say, phone }) => {
  await signInAs(page, PEOPLE.owner);
  await answersOmarFromTheDraft(page, say, phone, "inbox.tabs.all");
  await makesPriyaALead(page, say, phone, "inbox.tabs.all");
  await movesTheLead(page, say);

  await visit(page, say, "nav.tasks");
  await page
    .getByRole("combobox", { name: say("tasks.team"), exact: true })
    .selectOption({ label: say("tasks.team") });
  await expect(page).toHaveURL(/assignee=team/);
  await sendsTheFollowUp(page, say, "inbox.tabs.all");
  await readsTheDashboard(page, say);

  // And the one section that is the owner's alone: everybody is listed.
  await arrive(page, "/settings/team");
  for (const person of Object.values(PEOPLE)) {
    await expect(page.getByRole("main")).toContainText(person);
  }
});
