import { describe, expect, it } from "vitest";
import { en } from "@/messages/en";
import { ar } from "@/messages/ar";
import { asTyped } from "@/lib/format";
import { AREAS, OPERATIONS, stepsFor } from "./Recon";

const money = { amount_minor: 150_000, currency: "AED" };

describe("stepsFor", () => {
  it("commits proposed work only once it has an estimate", () => {
    expect(stepsFor({ status: "proposed", estimate: null })).toEqual(["estimate", "decline"]);
    expect(stepsFor({ status: "proposed", estimate: money })).toEqual([
      "commit",
      "estimate",
      "decline",
    ]);
  });

  it("offers waiting work only a withdrawal: the decision is somebody else's", () => {
    expect(stepsFor({ status: "awaiting_approval", estimate: money })).toEqual(["withdraw"]);
  });

  it("finishes approved work, and offers nothing once it is over", () => {
    expect(stepsFor({ status: "approved", estimate: money })).toEqual(["finish", "decline"]);
    expect(stepsFor({ status: "done", estimate: money })).toEqual([]);
    expect(stepsFor({ status: "declined", estimate: money })).toEqual([]);
  });
});

describe("the catalogue", () => {
  it("names every area and operation the API accepts, in both languages", () => {
    for (const area of AREAS) {
      expect(en[`reconArea.${area}`]).toBeTruthy();
      expect(ar[`reconArea.${area}`]).toBeTruthy();
    }
    for (const operation of OPERATIONS) {
      expect(en[`reconOperation.${operation}`]).toBeTruthy();
      expect(ar[`reconOperation.${operation}`]).toBeTruthy();
    }
  });
});

describe("asTyped", () => {
  it("writes an amount back the way a person types it", () => {
    expect(asTyped(150_000, "AED")).toBe("1,500");
    expect(asTyped(150_050, "AED")).toBe("1,500.50");
    expect(asTyped(1_250, "KWD")).toBe("1.250");
  });
});
