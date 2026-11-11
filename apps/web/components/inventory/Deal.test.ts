import { describe, expect, it } from "vitest";
import type { Receipt } from "@/lib/api/hooks";
import { ar } from "@/messages/ar";
import { en } from "@/messages/en";
import { paymentFromReceipt, suggestedDeposit } from "./Deal";

describe("suggestedDeposit", () => {
  it("suggests a tenth of the price, to the nearest thousand", () => {
    expect(suggestedDeposit({ amount_minor: 21_000_000, currency: "AED" })).toBe(2_100_000);
    expect(suggestedDeposit({ amount_minor: 8_900_000, currency: "AED" })).toBe(900_000);
  });

  it("counts a thousand in the currency's own units", () => {
    // KWD has 1000 fils: KWD 12,345 is 12,345,000 fils, a tenth near KWD 1,000.
    expect(suggestedDeposit({ amount_minor: 12_345_000, currency: "KWD" })).toBe(1_000_000);
  });
});

describe("paymentFromReceipt", () => {
  const receipt: Receipt = {
    amount: { amount_minor: 545_000, currency: "USD" },
    paid_on: "2026-11-04",
    reference: "BNA26110400451",
    payer: "SARL ATLAS AUTO",
    bank: "BNA",
    fx_rate: null,
    needs_fx_rate: true,
    stage: "deposit",
    warnings: [],
    document_path: "t/payments/2026/11/x.png",
  };

  it("fills the form with what the receipt said, and no rate it did not print", () => {
    expect(paymentFromReceipt(receipt)).toEqual({
      stage: "deposit",
      amount: "5,450",
      currency: "USD",
      fx_rate: "",
      received_on: "2026-11-04",
      reference: "BNA26110400451",
      document_path: "t/payments/2026/11/x.png",
    });
  });

  it("leaves the amount for a person when it could not be read", () => {
    expect(paymentFromReceipt({ ...receipt, amount: null }).amount).toBe("");
  });
});

describe("the catalogue", () => {
  it("names every stage, charge and method in both languages", () => {
    const keys = [
      ...["deposit", "balance", "logistics"].map((s) => `paymentStage.${s}`),
      ...["vehicle", "fee", "freight", "duties", "other"].map((k) => `chargeKind.${k}`),
      ...["bank_transfer", "cash", "card", "other"].map((m) => `paymentMethod.${m}`),
    ] as (keyof typeof en)[];
    for (const key of keys) {
      expect(en[key]).toBeTruthy();
      expect(ar[key]).toBeTruthy();
    }
  });
});
