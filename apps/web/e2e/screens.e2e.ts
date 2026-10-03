/**
 * A path through every screen (docs/sales/07-frontend.md § 12.7), by its
 * section in docs/sales/08-screens.md — the ones the journey, the shell and
 * joining do not already walk — and Part C's audit, kept: what was measured
 * once by hand is asserted on every pull request.
 */
import { createRequire } from "node:module";
import type { Locator, Page } from "@playwright/test";
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
const JAMES = "James Whitfield";
const KARIM = "Karim Benali";
const MONA = "Mona Fathy";
const HESSA = "Hessa Al Mansoori";
const ARABIC = /[؀-ۿ]/;

const conversations = (page: Page) => page.locator("li[data-sla]");
const customers = (page: Page) => page.locator("main li[data-band]");
const thread = (page: Page) => page.locator("[data-thread]");
const log = (page: Page, say: Say) => page.getByRole("log", { name: say("thread.messages") });

async function open(page: Page, say: Say, tab: Key, customer: string) {
  await page.getByRole("tab", { name: say(tab) }).click();
  await conversations(page).filter({ hasText: customer }).getByRole("link").click();
  await expect(thread(page).getByRole("heading", { level: 1 })).toContainText(customer);
}

/** A task is under Today — unless it is due after the workspace's midnight. */
async function findTask(page: Page, say: Say, row: Locator) {
  await expect(async () => {
    for (const bucket of ["tasks.today", "tasks.upcoming"] as const) {
      await page.getByRole("tab", { name: say(bucket) }).click();
      await page.waitForTimeout(300);
      if (await row.isVisible()) return;
    }
    throw new Error("the task is under neither Today nor Upcoming");
  }).toPass({ timeout: 20_000 });
}

// ---------------------------------------------------------------- § 2 the list

test("an unassigned customer is taken, and found again by their number", async ({
  page,
  say,
  phone,
}) => {
  await signInAs(page, PEOPLE.ahmed);
  await open(page, say, "inbox.tabs.unassigned", JAMES);
  await page.getByRole("button", { name: say("thread.assignToMe") }).click();
  await expect(thread(page).locator("header")).toContainText(say("thread.assignedToYou"));
  await expect(page.getByRole("button", { name: say("thread.assignToMe") })).toHaveCount(0);
  if (phone) await page.getByRole("link", { name: say("thread.back") }).click();

  await page.getByRole("tab", { name: say("inbox.tabs.mine") }).click();
  await expect(conversations(page).filter({ hasText: JAMES })).toHaveCount(1);
  await page.getByRole("searchbox", { name: say("inbox.search") }).pressSequentially("0104");
  await expect(conversations(page)).toHaveCount(1);
  await expect(conversations(page)).toContainText(JAMES);
});

// ------------------------------------------------- § 3, § 4 thread and composer

test("a note for colleagues is marked as one; a shortcut fills the box in the customer's language", async ({
  page,
  say,
}) => {
  await signInAs(page, PEOPLE.ahmed);
  await open(page, say, "inbox.tabs.mine", OMAR);
  const sent = log(page, say).locator('li[data-kind="message"]');
  await expect(sent.first()).toBeVisible();
  const before = await sent.count();

  await page.getByRole("button", { name: say("thread.internalNote") }).click();
  await page.getByRole("textbox", { name: say("thread.internalNote") }).fill("He wants the white one.");
  await page.getByRole("button", { name: say("thread.send"), exact: true }).click();
  const note = log(page, say).locator('li[data-kind="note"]').last();
  await expect(note).toContainText("He wants the white one.");
  await expect(note).toContainText(say("thread.note"));
  // A note is not a message: nothing went to the customer.
  await expect(sent).toHaveCount(before);

  await page.getByRole("button", { name: say("thread.internalNote") }).click();
  const box = page.getByRole("textbox", { name: say("thread.placeholder") });
  await box.pressSequentially("/pr");
  const menu = page.getByRole("listbox", { name: say("quick.menu") });
  await expect(menu.getByRole("option")).toHaveCount(1);
  await expect(menu).toContainText("Today's price");
  await page.keyboard.press("Enter");
  // Omar writes in Arabic, so the reply is the Arabic one, with his first name in it.
  await expect(box).toHaveValue(/Omar/);
  await expect(box).toHaveValue(ARABIC);
  await fits(page);
});

test("with the window closed the box gives way to a template, which sends", async ({
  page,
  say,
}) => {
  await signInAs(page, PEOPLE.salem);
  await open(page, say, "inbox.tabs.mine", KARIM);
  await expect(thread(page).locator("header")).toContainText(say("thread.windowClosed"));
  await expect(page.getByRole("textbox", { name: say("thread.placeholder") })).toHaveCount(0);

  const picker = page.getByLabel(say("thread.windowClosedHint"));
  // Karim writes in French: the French templates come first.
  await expect(picker.locator("option").nth(1)).toContainText(say("language.fr"));
  const french = picker
    .locator("option")
    .filter({ hasText: "price_update" })
    .filter({ hasText: say("language.fr") });
  await picker.selectOption((await french.getAttribute("value"))!);

  const blank = (n: number) => page.getByRole("textbox", { name: `${say("template.blank")} ${n}` });
  const send = page.getByRole("button", { name: say("template.send") });
  // The first blank greets him; the car and the price are for a person to say.
  await expect(blank(1)).toHaveValue("Karim");
  await expect(send).toBeDisabled();
  await blank(2).fill("Toyota Hilux 2.8 Diesel");
  await blank(3).fill("AED 128,000");
  await expect(page.getByRole("group", { name: say("template.preview") })).toContainText(
    "Bonjour Karim, le prix de Toyota Hilux 2.8 Diesel est maintenant AED 128,000.",
  );
  await expect(page.getByText(say("template.paid"))).toBeVisible();
  await fits(page);

  await send.click();
  await expect(log(page, say).locator('li[data-kind="message"]').last()).toContainText(
    "maintenant AED 128,000",
  );
});

// ------------------------------------------------------ § 5 the customer panel

test("the customer panel says what is known, and on a phone it is a dialog that Escape closes", async ({
  page,
  say,
  phone,
}) => {
  await signInAs(page, PEOPLE.ahmed);
  await open(page, say, "inbox.tabs.mine", OMAR);
  const opener = page.getByRole("button", { name: say("customer.details") });
  await opener.click();

  const panel = page.locator("[data-customer-panel]");
  await expect(panel).toContainText(say("customer.whatWeKnow"));
  // What the seed says the AI inferred and what a person answered.
  await expect(panel).toContainText("Land Cruiser 4.0, white");
  await expect(panel).toContainText("+971500000101");
  await fits(page);

  if (phone) {
    // It covers the conversation, so it is a dialog: Escape, and focus goes home.
    await expect(page.getByRole("dialog", { name: say("customer.details") })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(opener).toBeFocused();
  } else {
    // Beside the conversation, there while a reply is typed; the button puts it away.
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await opener.click();
    await expect(panel).toHaveCount(0);
  }
});

// ------------------------------------------- § 6, § 7 customers and one record

test("the customers list finds somebody by their number, and their record has its four tabs", async ({
  page,
  say,
}) => {
  await signInAs(page, PEOPLE.ahmed);
  await visit(page, say, "nav.customers");
  await page.getByRole("searchbox", { name: say("customers.search") }).pressSequentially("0101");
  await expect(customers(page)).toHaveCount(1);
  await customers(page).getByRole("link").click();

  await expect(page.getByRole("heading", { level: 1 })).toContainText(OMAR);
  const tab = (key: Key) => page.getByRole("tab", { name: say(key) });
  const main = page.getByRole("main");
  await expect(tab("customer.tabs.timeline")).toHaveAttribute("aria-selected", "true");
  await tab("customer.tabs.leads").click();
  await expect(main).toContainText("Negotiation");
  await tab("customer.tabs.tasks").click();
  await expect(main).toContainText("Call Omar about the passport copy");
  await tab("customer.tabs.profile").click();
  await expect(main).toContainText("Land Cruiser 4.0, white");
  await fits(page);
});

test("the owner erases a customer only after typing their name", async ({ page, say }) => {
  await signInAs(page, PEOPLE.owner);
  await visit(page, say, "nav.customers");
  await page.getByRole("searchbox", { name: say("customers.search") }).pressSequentially("Hessa");
  await expect(customers(page)).toHaveCount(1);
  await customers(page).getByRole("link").click();

  await page.getByRole("button", { name: say("customer.erase") }).click();
  const dialog = page.getByRole("dialog", { name: say("erase.title") });
  const confirm = dialog.getByRole("button", { name: say("erase.confirm") });
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("textbox").fill("Hessa");
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("textbox").fill(HESSA);
  await confirm.click();

  await page.waitForURL((url) => url.pathname === `${WORKSPACE}/customers`);
  await expect(customers(page).first()).toBeVisible();
  await expect(customers(page).filter({ hasText: HESSA })).toHaveCount(0);
});

// --------------------------------------------------- § 8 the board's lead

test("a lead's drawer opens as a dialog and gives focus back; marking it lost asks why", async ({
  page,
  say,
}) => {
  await signInAs(page, PEOPLE.ahmed);
  await visit(page, say, "nav.pipeline");
  const card = page.locator("li[data-lead]").filter({ hasText: MONA });
  const opener = card.getByRole("button");
  await opener.click();
  const drawer = page.getByRole("dialog", { name: say("lead.details") });
  await expect(drawer).toContainText(MONA);
  await expect(drawer).toContainText(say("lead.history"));
  await fits(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(opener).toBeFocused();

  await card.getByLabel(say("pipeline.moveTo")).selectOption({ label: "Lost" });
  const why = page.getByRole("dialog", { name: say("lost.title") });
  const confirm = why.getByRole("button", { name: say("lost.confirm") });
  await expect(confirm).toBeDisabled();
  await why.getByRole("textbox", { name: say("lost.title") }).fill("Bought elsewhere");
  await confirm.click();
  const lost = page
    .locator("section[data-stage]")
    .filter({ has: page.getByRole("heading", { name: "Lost", exact: true }) });
  await expect(lost.locator("li[data-lead]").filter({ hasText: MONA })).toHaveCount(1);
});

// ------------------------------------------------------- § 9, § 10 tasks, My day

test("a task is added, done, and brought back", async ({ page, say }) => {
  await signInAs(page, PEOPLE.ahmed);
  await visit(page, say, "nav.tasks");
  const title = "Send Priya the finance options";
  await page.getByRole("textbox", { name: say("tasks.newTitle") }).fill(title);
  await page.getByRole("button", { name: say("tasks.add") }).click();

  const row = page.locator("li[data-task]").filter({ hasText: title });
  await findTask(page, say, row);
  // Pressed, not "checked": the box is ticked by the server's answer, and by
  // then the task has left this list for Done.
  await row.getByRole("checkbox", { name: say("tasks.complete") }).click();
  await expect(row).toHaveCount(0);

  // Done by mistake is one press to put right.
  await page.getByRole("button", { name: say("tasks.undo") }).click();
  await expect(row).toHaveCount(1);
  await expect(row.getByRole("checkbox", { name: say("tasks.complete") })).not.toBeChecked();
  await fits(page);
});

test("My day greets by name and lists who is waiting", async ({ page, say }) => {
  await signInAs(page, PEOPLE.ahmed);
  await visit(page, say, "nav.today");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Ahmed");
  const waiting = page
    .locator("section")
    .filter({ has: page.getByRole("heading", { name: say("today.waitingOnYou") }) });
  await expect(waiting).toContainText(OMAR);
  await expect(page.getByRole("heading", { name: say("today.dueToday") })).toBeVisible();
  await fits(page);
});

// -------------------------------------------------------------- § 11 dashboard

test("the manager hands a waiting customer to somebody from the dashboard", async ({
  page,
  say,
}) => {
  await signInAs(page, PEOPLE.manager);
  await visit(page, say, "nav.dashboard");
  const row = page.locator("li").filter({ hasText: JAMES });
  await expect(row).toContainText(say("customers.nobody"));
  await row
    .getByRole("combobox", { name: say("dashboard.reassign") })
    .selectOption({ label: PEOPLE.mohamed });
  await expect(row).toContainText(PEOPLE.mohamed);
  await expect(row).not.toContainText(say("customers.nobody"));
  await fits(page);
});

// ---------------------------------------------------------- § 12 notifications

test("the bell opens, and Escape closes it and gives focus back", async ({ page, say }) => {
  await signInAs(page, PEOPLE.ahmed);
  const bell = page.getByRole("button", { name: new RegExp(`^${say("notifications.title")}`) });
  await bell.click();
  await expect(page.getByRole("dialog", { name: say("notifications.title") })).toBeVisible();
  await fits(page);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(bell).toBeFocused();
});

// ---------------------------------------------------------------- § 13 settings

const SECTIONS: readonly (readonly [string, Key])[] = [
  ["/settings/channels", "settings.channels"],
  ["/settings/team", "settings.team"],
  ["/settings/routing", "settings.routing"],
  ["/settings/pipelines", "settings.pipelines"],
  ["/settings/quick-replies", "settings.quickReplies"],
  ["/settings/knowledge", "settings.knowledge"],
  ["/settings/ai", "settings.ai"],
  ["/settings/notifications", "notifications.title"],
];

test("every settings section opens under its own heading for the owner; a salesperson is told which are not theirs", async ({
  page,
  say,
}) => {
  await signInAs(page, PEOPLE.owner);
  for (const [path, heading] of SECTIONS) {
    await arrive(page, path);
    await expect(page.getByRole("heading", { level: 1 }), path).toHaveText(say(heading));
    await fits(page);
  }
  // The seeded policies, as the Knowledge screen lists them.
  await arrive(page, "/settings/knowledge");
  await expect(page.getByText(say("knowledge.status.ready"))).toHaveCount(3);

  await signInAs(page, PEOPLE.ahmed);
  await arrive(page, "/settings/channels");
  await expect(page.getByText(say("settings.notYours"))).toBeVisible();
  // Quick replies are his to read, and somebody else's to change.
  await arrive(page, "/settings/quick-replies");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(say("settings.quickReplies"));
  await expect(page.getByText(say("quick.readOnly"))).toBeVisible();
  await expect(page.getByRole("button", { name: say("quick.add") })).toHaveCount(0);
});

test("a stage that holds a lead is not removed, and the refusal is in the reader's language", async ({
  page,
  say,
  language,
}) => {
  await signInAs(page, PEOPLE.owner);
  await arrive(page, "/settings/pipelines");
  // "New" holds James's lead.
  const stage = page.locator("li").filter({ has: page.locator('input[value="New"]') });
  await stage.getByRole("button", { name: say("routing.remove") }).click();
  await page.getByRole("button", { name: say("common.save") }).first().click();

  const refusal = page.getByRole("alert").filter({ hasText: "New" });
  await expect(refusal).toBeVisible();
  // The API's own sentence — and it was written for whoever is reading.
  const words = (await refusal.innerText()).replaceAll("New", "");
  expect(ARABIC.test(words), words).toBe(language === "ar");
  await fits(page);
});

test("a quick reply written in settings is offered in the composer", async ({ page, say }) => {
  await signInAs(page, PEOPLE.manager);
  await arrive(page, "/settings/quick-replies");
  await page.getByRole("button", { name: say("quick.add") }).click();
  await page.getByLabel(say("quick.shortcut")).fill("/visit");
  await page.getByLabel(say("quick.title")).fill("Come and see it");
  await page.getByLabel(say("language.ar")).fill("أهلاً {name}، تفضل بزيارتنا في المعرض.");
  await page.getByLabel(say("language.en")).fill("Hello {name}, come and see it at the showroom.");
  await page.getByRole("button", { name: say("common.save") }).click();
  await expect(page.getByRole("main")).toContainText("Come and see it");

  await visit(page, say, "nav.inbox");
  await open(page, say, "inbox.tabs.team", OMAR);
  await page.getByRole("textbox", { name: say("thread.placeholder") }).pressSequentially("/vi");
  await expect(page.getByRole("listbox", { name: say("quick.menu") })).toContainText(
    "Come and see it",
  );
});

// ------------------------------------------- Part C's audit, on every pull request

const AXE = createRequire(__filename).resolve("axe-core/axe.min.js");

/** The checker's verdict, one line a finding: nothing wrong is an empty list. */
async function checked(page: Page): Promise<string[]> {
  await page.addScriptTag({ path: AXE });
  return page.evaluate(async () => {
    type Finding = { id: string; impact: string; nodes: { target: string[] }[] };
    const axe = (window as unknown as { axe: { run: (...args: unknown[]) => Promise<{ violations: Finding[] }> } }).axe;
    const { violations } = await axe.run(document, { resultTypes: ["violations"] });
    return violations.map(
      (found) =>
        `${found.id} (${found.impact}): ${found.nodes
          .slice(0, 3)
          .map((node) => node.target.join(" "))
          .join(" | ")}`,
    );
  });
}

const PAGES: readonly (readonly [string, string, string])[] = [
  // Outside a workspace, signed out.
  ["nobody", "/dev-login", "local sign-in"],
  ["nobody", "/accept-invite?token=nonsense", "a bad invitation"],
  ["nobody", "/offline.html", "the offline page"],
  // A salesperson's day.
  [PEOPLE.ahmed, `${WORKSPACE}/inbox`, "inbox"],
  [PEOPLE.ahmed, `${WORKSPACE}/today`, "My day"],
  [PEOPLE.ahmed, `${WORKSPACE}/customers`, "customers"],
  [PEOPLE.ahmed, `${WORKSPACE}/pipeline`, "pipeline"],
  [PEOPLE.ahmed, `${WORKSPACE}/tasks`, "tasks"],
  [PEOPLE.ahmed, `${WORKSPACE}/dashboard`, "the dashboard, to somebody it is not for"],
  [PEOPLE.ahmed, `${WORKSPACE}/settings/quick-replies`, "quick replies, read only"],
  [PEOPLE.ahmed, `${WORKSPACE}/settings/team`, "a section that is not theirs"],
  [PEOPLE.ahmed, `${WORKSPACE}/inbox/00000000-0000-4000-8000-000000000000`, "a conversation that is not there"],
  [PEOPLE.ahmed, `${WORKSPACE}/customers/00000000-0000-4000-8000-000000000000`, "a customer who is not there"],
  // Those who run the team.
  [PEOPLE.manager, `${WORKSPACE}/dashboard`, "the dashboard"],
  [PEOPLE.owner, `${WORKSPACE}/settings/channels`, "channels"],
  [PEOPLE.owner, `${WORKSPACE}/settings/team`, "team"],
  [PEOPLE.owner, `${WORKSPACE}/settings/routing`, "routing"],
  [PEOPLE.owner, `${WORKSPACE}/settings/pipelines`, "pipelines"],
  [PEOPLE.owner, `${WORKSPACE}/settings/knowledge`, "knowledge"],
  [PEOPLE.owner, `${WORKSPACE}/settings/ai`, "AI"],
  [PEOPLE.owner, `${WORKSPACE}/settings/notifications`, "notifications"],
];

test("no page fails the checker, lacks its one heading, or scrolls sideways", async ({
  page,
  say,
}) => {
  test.slow();
  const findings: string[] = [];
  const look = async (name: string) => {
    // Once what the page asks for has arrived: a list still loading passes anything.
    await expect(page.getByRole("main").first(), name).toBeVisible();
    await page.waitForTimeout(900);
    for (const finding of await checked(page)) findings.push(`${name}: ${finding}`);
    const headings = await page.getByRole("heading", { level: 1 }).count();
    if (headings !== 1) findings.push(`${name}: ${headings} top headings`);
    const [content, screen] = await page.evaluate(() => [
      document.documentElement.scrollWidth,
      document.documentElement.clientWidth,
    ]);
    if (content > screen) findings.push(`${name}: scrolls sideways (${content} > ${screen})`);
  };

  // The checker is trusted only after it has been seen to find something: a
  // button with no name, put on a page for it. A checker that finds nothing
  // because it did not run looks exactly like a clean app.
  await page.goto("/dev-login");
  await page.evaluate(() => document.body.append(document.createElement("button")));
  expect((await checked(page)).join(" ")).toContain("button-name");

  let signedIn = "nobody";
  for (const [person, address, name] of PAGES) {
    if (person !== signedIn) {
      await signInAs(page, person);
      signedIn = person;
    }
    await page.goto(address);
    await look(name);
  }

  // And the states a page load does not show: an open conversation with its
  // draft, and the panel beside it.
  await signInAs(page, PEOPLE.ahmed);
  await open(page, say, "inbox.tabs.mine", OMAR);
  await expect(page.getByRole("region", { name: say("draft.title") })).toBeVisible();
  await look("a conversation, with its draft");
  await page.getByRole("button", { name: say("customer.details") }).click();
  await expect(page.locator("[data-customer-panel]")).toBeVisible();
  await look("the customer panel");

  expect(findings, findings.join("\n")).toEqual([]);
});
