import { describe, expect, it } from "vitest";
import { titleWithUnread } from "./title";

describe("titleWithUnread", () => {
  it("puts the count on the front, once, however often it is applied", () => {
    const once = titleWithUnread(3, "Inbox · DealerAI");
    expect(once).toBe("(3) Inbox · DealerAI");
    expect(titleWithUnread(3, once)).toBe(once);
    expect(titleWithUnread(4, once)).toBe("(4) Inbox · DealerAI");
  });

  it("takes it off again when nothing is unread", () => {
    expect(titleWithUnread(0, "(3) Inbox · DealerAI")).toBe("Inbox · DealerAI");
  });
});
