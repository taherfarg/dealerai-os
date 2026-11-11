/**
 * Who sees whom (docs/sales/07-frontend.md § 11): a salesperson cannot see a
 * colleague's customer — in a list, in a search, or by pasting the address.
 *
 * Omar, Mona and Priya are Ahmed's. Rashid and Hessa are Mohamed's, in Ahmed's
 * own team; Karim is Salem's, in the other. James is nobody's yet, and waits in
 * the queue of the team both Ahmed and Mohamed are in.
 */
import type { Browser, Page } from "@playwright/test";
import {
  PEOPLE,
  WORKSPACE,
  arrive,
  expect,
  reads,
  signInAs,
  test,
  visit,
  type Language,
} from "./fixtures";

const MINE = ["Omar Al Mazrouei", "Mona Fathy", "Priya Nair"];
const NOBODYS = "James Whitfield";
const RASHID = "Rashid Al Ketbi";
const NOT_MINE = [RASHID, "Hessa Al Mansoori", "Karim Benali"];

const conversations = (page: Page) => page.locator("li[data-sla]");
const customers = (page: Page) => page.locator("main li[data-band]");
const leads = (page: Page) => page.locator("main li[data-lead]");

/** What somebody else can reach, read from their own screen. */
async function as<T>(
  browser: Browser,
  language: Language,
  person: string,
  act: (page: Page) => Promise<T>,
): Promise<T> {
  const context = await browser.newContext();
  await reads(context, language);
  const page = await context.newPage();
  try {
    await signInAs(page, person);
    return await act(page);
  } finally {
    await context.close();
  }
}

test("a salesperson's inbox holds their own customers and their team's unassigned, and nobody else's", async ({
  page,
  say,
}) => {
  await signInAs(page, PEOPLE.ahmed);

  for (const customer of MINE) await expect(conversations(page).filter({ hasText: customer })).toHaveCount(1);
  for (const customer of NOT_MINE) await expect(conversations(page).filter({ hasText: customer })).toHaveCount(0);

  await page.getByRole("tab", { name: say("inbox.tabs.unassigned") }).click();
  await expect(conversations(page).filter({ hasText: NOBODYS })).toHaveCount(1);
  for (const customer of NOT_MINE) await expect(conversations(page).filter({ hasText: customer })).toHaveCount(0);

  // Not by asking for them by name either.
  await page.getByRole("tab", { name: say("inbox.tabs.mine") }).click();
  await page.getByRole("searchbox", { name: say("inbox.search") }).fill("Rashid");
  await expect(conversations(page)).toHaveCount(0);
  await page.getByRole("searchbox", { name: say("inbox.search") }).fill("Omar");
  await expect(conversations(page)).toHaveCount(1);
});

test("…and so do the customers list and the pipeline", async ({ page, say }) => {
  await signInAs(page, PEOPLE.ahmed);

  await visit(page, say, "nav.customers");
  // Listed, however many times: the seed keeps a duplicate of Omar for the merge dialog.
  for (const customer of MINE) await expect(customers(page).filter({ hasText: customer }).first()).toBeVisible();
  for (const customer of NOT_MINE) await expect(customers(page).filter({ hasText: customer })).toHaveCount(0);
  // Typed as a person types, straight away: every letter has to be kept.
  const search = page.getByRole("searchbox", { name: say("customers.search") });
  await search.pressSequentially("Rashid");
  await expect(search).toHaveValue("Rashid");
  await expect(customers(page)).toHaveCount(0);
  await search.fill("");
  await search.pressSequentially("Mona");
  await expect(customers(page)).toHaveCount(1);

  await visit(page, say, "nav.pipeline");
  await expect(leads(page).filter({ hasText: "Mona Fathy" })).toHaveCount(1);
  for (const customer of NOT_MINE) await expect(leads(page).filter({ hasText: customer })).toHaveCount(0);
  // Karim's lead is on the other board, and it is not there for Ahmed either.
  await page.getByRole("combobox", { name: say("pipeline.title") }).selectOption({ label: "Export" });
  await expect(page.getByText(say("pipeline.empty"))).toBeVisible();
  await expect(leads(page)).toHaveCount(0);
});

test("a colleague's conversation, pasted into the address bar, is not there", async ({
  page,
  say,
  browser,
  language,
}) => {
  const address = await as(browser, language, PEOPLE.mohamed, async (theirs) => {
    const row = conversations(theirs).filter({ hasText: RASHID }).getByRole("link");
    return (await row.getAttribute("href"))!;
  });
  expect(address).toMatch(/\/inbox\/[0-9a-f-]{36}$/);

  await signInAs(page, PEOPLE.ahmed);
  await arrive(page, address.slice(WORKSPACE.length));
  await expect(page.getByRole("main").getByText(say("thread.gone"))).toBeVisible();
  // Nothing of it: not the name, not a word he wrote, no box to answer in.
  await expect(page.getByRole("main")).not.toContainText("Rashid");
  await expect(page.getByRole("main")).not.toContainText("X5");
  await expect(page.getByRole("log")).toHaveCount(0);
  await expect(page.getByRole("textbox", { name: say("thread.placeholder") })).toHaveCount(0);
});

test("a colleague's customer, pasted, is not there", async ({ page, say, browser, language }) => {
  const address = await as(browser, language, PEOPLE.mohamed, async (theirs) => {
    await visit(theirs, say, "nav.customers");
    const row = customers(theirs).filter({ hasText: RASHID }).getByRole("link");
    return (await row.getAttribute("href"))!;
  });
  expect(address).toMatch(/\/customers\/[0-9a-f-]{36}$/);

  await signInAs(page, PEOPLE.ahmed);
  await arrive(page, address.slice(WORKSPACE.length));
  await expect(page.getByRole("main").getByText(say("customer.gone"))).toBeVisible();
  await expect(page.getByRole("main")).not.toContainText("Rashid");
  await expect(page.getByRole("main")).not.toContainText("+9715");
});

test("a manager sees both teams' customers, and the owner everybody's", async ({ page, say }) => {
  for (const [person, tab] of [
    [PEOPLE.manager, "inbox.tabs.team"],
    [PEOPLE.owner, "inbox.tabs.all"],
  ] as const) {
    await signInAs(page, person);
    await page.getByRole("tab", { name: say(tab) }).click();
    for (const customer of [...MINE, ...NOT_MINE, NOBODYS]) {
      await expect(conversations(page).filter({ hasText: customer }), `${person}: ${customer}`).toHaveCount(1);
    }
    await visit(page, say, "nav.customers");
    for (const customer of [...MINE, ...NOT_MINE]) {
      await expect(customers(page).filter({ hasText: customer }).first(), `${person}: ${customer}`).toBeVisible();
    }
  }
});

test("a salesperson has no team settings, whatever the address", async ({ page, say }) => {
  await signInAs(page, PEOPLE.ahmed);
  await arrive(page, "/settings/team");
  await expect(page.getByText(say("settings.notYours"))).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(say("nav.settings"));
  // Not offered, and not shown: nobody else's name is on the page.
  const sections = page.getByRole("navigation", { name: say("nav.settings") });
  await expect(sections.getByRole("link", { name: say("settings.team") })).toHaveCount(0);
  await expect(page.getByRole("main")).not.toContainText(PEOPLE.manager);
});
