import { describe, expect, it } from "vitest";
import { ar } from "@/messages/ar";
import { en } from "@/messages/en";
import type { MessageKey } from "@/lib/i18n";
import { describeReason } from "./PricingCard";

const english = (key: MessageKey) => en[key];
const arabic = (key: MessageKey) => ar[key];

describe("describeReason", () => {
  it("sets a code's number beside its sentence", () => {
    expect(describeReason("aged:60", english)).toBe("In stock past day 60");
    expect(describeReason("demand:4", arabic)).toBe("العملاء المحتملون خلال آخر 30 يومًا: 4");
  });

  it("says a code with no number as it is", () => {
    expect(describeReason("no_leads", english)).toBe("No leads in the last 30 days");
  });

  it("drops a code it does not know rather than showing it raw", () => {
    expect(describeReason("status:sold", english)).toBeNull();
    expect(describeReason("something_new", english)).toBeNull();
  });
});
