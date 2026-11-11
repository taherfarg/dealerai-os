/**
 * What one person does reaches another's screen by itself (S2's exit:
 * "a salesperson answers a customer while the manager watches the timer";
 * docs/sales/07-frontend.md § 12.4).
 *
 * The reply is a row; its commit notifies; the API tells every open stream that
 * may see it; the page asks again for what changed. Nothing here reloads.
 */
import type { Page } from "@playwright/test";
import { PEOPLE, arrive, expect, reads, signInAs, test, type Say } from "./fixtures";

const OMAR = "Omar Al Mazrouei";
const PRICE = "AED 128,000";

const messages = (page: Page, say: Say) =>
  page.getByRole("log", { name: say("thread.messages") }).locator('li[data-kind="message"]');

async function openOmar(page: Page, say: Say, tab: "inbox.tabs.mine" | "inbox.tabs.team") {
  await page.getByRole("tab", { name: say(tab) }).click();
  await page.locator("li[data-sla]").filter({ hasText: OMAR }).getByRole("link").click();
  await expect(messages(page, say).first()).toBeVisible();
}

test("a manager sees a customer stop waiting, and the reply arrive, without touching the page", async ({
  page,
  say,
  browser,
  language,
}) => {
  // Sara has Omar's conversation open on one page, and the dashboard on another.
  await signInAs(page, PEOPLE.manager);
  await openOmar(page, say, "inbox.tabs.team");
  const header = page.locator("[data-thread] header");
  await expect(header).toContainText(say("inbox.missed"));
  const before = await messages(page, say).count();

  const dashboard = await page.context().newPage();
  await arrive(dashboard, "/dashboard");
  const waiting = dashboard
    .locator("section")
    .filter({ has: dashboard.getByRole("heading", { name: say("dashboard.waiting") }) });
  await expect(waiting).toContainText(OMAR);

  // Ahmed, somewhere else, answers him from the draft.
  const elsewhere = await browser.newContext();
  await reads(elsewhere, language);
  const his = await elsewhere.newPage();
  await signInAs(his, PEOPLE.ahmed);
  await openOmar(his, say, "inbox.tabs.mine");
  await his
    .getByRole("region", { name: say("draft.title") })
    .getByRole("button", { name: say("draft.send") })
    .click();
  await expect(messages(his, say).last()).toContainText(PRICE);

  // On Sara's two pages, untouched: the reply is there, and he is not waiting.
  await expect(messages(page, say)).toHaveCount(before + 1);
  await expect(messages(page, say).last()).toContainText(PRICE);
  await expect(header).not.toContainText(say("inbox.missed"));
  await expect(waiting).not.toContainText(OMAR);

  await elsewhere.close();
});
