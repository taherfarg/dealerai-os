import { describe, expect, it } from "vitest";
import type { ShippingReading } from "@/lib/api/hooks";
import { ar } from "@/messages/ar";
import { en } from "@/messages/en";
import { confirmationFrom } from "./Inbound";

const reading: ShippingReading = {
  kind: "bill_of_lading",
  reference: "MEDU8812345",
  carrier: "MSC",
  vessel: "MSC AURORA",
  container: null,
  port_of_loading: "Houston, TX",
  port_of_discharge: "Jebel Ali",
  departed_on: "2026-10-20",
  eta: "2026-11-18",
  vins: ["1C4RJFBG5MC000123"],
  matches: true,
  milestone: "departed",
  paper: "bill_of_lading",
  warnings: [],
  document_path: "t/inbound/2026/11/x.pdf",
};

describe("confirmationFrom", () => {
  it("sends what the paper said, the step it proves and the paper it is", () => {
    expect(confirmationFrom(reading)).toEqual({
      journey: {
        carrier: "MSC",
        reference: "MEDU8812345",
        vessel: "MSC AURORA",
        port_of_loading: "Houston, TX",
        port_of_discharge: "Jebel Ali",
        eta: "2026-11-18",
      },
      milestone: { code: "departed", done_on: "2026-10-20" },
      paper: { code: "bill_of_lading", document_path: "t/inbound/2026/11/x.pdf" },
    });
  });

  it("never blanks a field the paper did not print", () => {
    const sent = confirmationFrom(reading).journey ?? {};
    expect("container" in sent).toBe(false);
  });

  it("proves nothing and files nothing when the reading says neither", () => {
    const bare = confirmationFrom({ ...reading, milestone: null, paper: null, document_path: null });
    expect(bare.milestone).toBeNull();
    expect(bare.paper).toBeNull();
  });
});

describe("the catalogue", () => {
  const milestones = [
    "purchased",
    "paid",
    "picked_up",
    "at_origin_port",
    "departed",
    "arrived_port",
    "customs_cleared",
    "delivered",
    "collected",
    "registered",
  ] as const;
  const papers = [
    "bill_of_sale",
    "title",
    "bill_of_lading",
    "customs_declaration",
    "customs_certificate",
    "registration_card",
  ] as const;

  it("names every step and paper the API has, in both languages", () => {
    for (const code of milestones) {
      expect(en[`milestone.${code}`]).toBeTruthy();
      expect(ar[`milestone.${code}`]).toBeTruthy();
    }
    for (const code of papers) {
      expect(en[`paper.${code}`]).toBeTruthy();
      expect(ar[`paper.${code}`]).toBeTruthy();
    }
  });
});
