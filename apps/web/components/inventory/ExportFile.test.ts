import { describe, expect, it } from "vitest";
import type { ExportStep } from "@/lib/api/hooks";
import { ar } from "@/messages/ar";
import { en } from "@/messages/en";
import { stepActions } from "./ExportFile";

const step = (over: Partial<ExportStep>): ExportStep => ({
  code: "export_certificate",
  status: "pending",
  done_on: null,
  note: null,
  has_document: false,
  takes_document: true,
  ...over,
});

describe("stepActions", () => {
  it("does, skips and uploads a pending step that takes a paper", () => {
    expect(stepActions(step({}), true)).toEqual(["done", "skip", "upload"]);
  });

  it("undoes a done step and gives its paper back", () => {
    expect(stepActions(step({ status: "done", has_document: true }), true)).toEqual([
      "undo",
      "upload",
      "download",
    ]);
  });

  it("does the invoice only by opening it — signing is on its own page", () => {
    expect(stepActions(step({ code: "commercial_invoice", takes_document: false }), true)).toEqual([
      "invoice",
    ]);
  });

  it("checks a bill of lading draft before it is confirmed", () => {
    expect(stepActions(step({ code: "bl_draft_confirmed" }), true)).toContain("check");
  });

  it("lets somebody who cannot edit only read and download", () => {
    expect(stepActions(step({ status: "done", has_document: true }), false)).toEqual(["download"]);
  });
});

describe("the catalogue", () => {
  it("names every step and procedure in both languages", () => {
    const keys = [
      ...[
        "customer_documents",
        "assign_vehicle",
        "customs_card",
        "book_shipping",
        "export_inspection",
        "export_plates",
        "deliver_to_carrier",
        "export_certificate",
        "bl_draft_confirmed",
        "bl_original",
        "chamber_certificate",
        "commercial_invoice",
        "file_delivered",
        "rta_registration",
        "delivered",
      ].map((code) => `step.${code}`),
      ...["DZ", "TN", "other", "local"].map((p) => `procedure.${p}`),
    ] as (keyof typeof en)[];
    for (const key of keys) {
      expect(en[key]).toBeTruthy();
      expect(ar[key]).toBeTruthy();
    }
  });
});
