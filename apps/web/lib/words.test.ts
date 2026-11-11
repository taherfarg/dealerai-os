import { describe, expect, it } from "vitest";
import { type MessageKey, t as translate } from "./i18n";
import { blockedReasons, counted, eventText, word } from "./words";

const en = (key: MessageKey) => translate("en", key);
const ar = (key: MessageKey) => translate("ar", key);

describe("word", () => {
  it("says a stored code in the reader's language", () => {
    expect(word(en, "channels.status", "connected")).toBe("connected");
    expect(word(ar, "channels.status", "connected")).toBe("متصلة");
    expect(word(ar, "template.status", "approved")).toBe("معتمد");
    expect(word(ar, "source", "whatsapp")).toBe("واتساب");
  });

  it("shows a code nobody has a word for, rather than nothing", () => {
    expect(word(ar, "channels.status", "throttled")).toBe("throttled");
  });

  it("can fall back to words the API sent with the code", () => {
    expect(word(ar, "score", "asked_price", "Asked the price")).toBe("سأل عن السعر");
    expect(word(ar, "score", "a_signal_from_next_year", "A new signal")).toBe("A new signal");
  });
});

describe("counted", () => {
  it.each([
    [0, "0 شخص"],
    [1, "شخص واحد"],
    [2, "شخصان"],
    [3, "3 أشخاص"],
    [10, "10 أشخاص"],
    [11, "11 شخصًا"],
    [99, "99 شخصًا"],
    [100, "100 شخص"],
  ])("counts %i the Arabic way: %s", (n, expected) => {
    expect(counted("ar", n, "people")).toBe(expected);
  });

  it("counts in English with a singular and a plural", () => {
    expect(counted("en", 1, "people")).toBe("1 person");
    expect(counted("en", 3, "people")).toBe("3 people");
    expect(counted("en", 0, "days")).toBe("0 days");
    expect(counted("en", 1, "passages")).toBe("1 passage");
  });
});

describe("eventText", () => {
  it("says what happened in the reader's language, with the name as it is written", () => {
    const event = { type: "assigned", text: "Assigned to Sara Mansour", name: "Sara Mansour" };
    expect(eventText(en, event)).toBe("Assigned to Sara Mansour");
    expect(eventText(ar, event)).toBe("أُسندت إلى Sara Mansour");
  });

  it("says an event that names nobody", () => {
    expect(eventText(ar, { type: "closed", text: "Closed" })).toBe("أُغلقت");
    // WhatsApp's own event carries no sentence at all.
    expect(eventText(en, { type: "conversation.reopened" })).toBe("The customer wrote again");
  });

  it("keeps the sentence it was given when the name was never kept apart", () => {
    // Events written before this release hold the name only inside the sentence.
    expect(eventText(ar, { type: "assigned", text: "Assigned to Sara Mansour" })).toBe(
      "Assigned to Sara Mansour",
    );
  });

  it("shows an event it has no words for as it was written", () => {
    expect(eventText(ar, { type: "merged", text: "Merged with another record" })).toBe(
      "Merged with another record",
    );
    expect(eventText(ar, null)).toBe("");
  });
});

describe("blockedReasons", () => {
  it("says which check refused the draft, in the reader's language", () => {
    const raw = "price: 'AED 199,000' is not a price from the record";
    expect(blockedReasons(en, raw)).toBe("it quoted a price that is not on the car's record");
    expect(blockedReasons(ar, raw)).toBe("ذكرت سعرًا غير مسجّل للسيارة");
  });

  it("says each check once, however many things it found", () => {
    const raw = "price: 'AED 1' is not a price; price: 'AED 2' is not a price; script: wrong script";
    expect(blockedReasons(en, raw)).toBe(
      "it quoted a price that is not on the car's record · it was not written in the customer's language",
    );
  });

  it("shows a reason it has no words for as it was written", () => {
    expect(blockedReasons(ar, "it quoted a price that is not ours")).toBe(
      "it quoted a price that is not ours",
    );
    expect(blockedReasons(ar, "promises delivery: 'tomorrow'")).toBe("promises delivery: 'tomorrow'");
  });
});
