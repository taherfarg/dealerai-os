import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Bid, BuyingList as List } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { BidLines } from "./BidLines";
import { BuyingList } from "./BuyingList";

const aed = (major: number) => ({ amount_minor: major * 100, currency: "AED" });

const bid: Bid = {
  expected_price: aed(235_000),
  price_from: "history",
  target_margin_bps: 1_200,
  margin: aed(28_200),
  on_top: aed(8_000),
  on_top_from: "history",
  holding: aed(454),
  days_to_sell: 10,
  days_from: "history",
  repairs: aed(0),
  max_bid: aed(198_000),
};

const list: List = {
  since: "2026-10-06T00:00:00Z",
  days: 30,
  currency: "AED",
  cars: [
    {
      make: "Toyota",
      model: "Land Cruiser",
      askers: [
        {
          contact_id: "c-1",
          name: "Ahmed",
          model_year: 2025,
          quoted: "لاند كروزر",
          budget: aed(230_000),
          destination: "DZ",
          asked_at: new Date().toISOString(),
        },
      ],
      worth: {
        sold: 1,
        price: aed(235_000),
        landed: aed(213_000),
        on_top: aed(8_000),
        days_to_sell: 10,
      },
      bid,
    },
    {
      make: "BYD",
      model: "Leopard 7",
      askers: [
        {
          contact_id: "c-2",
          name: null,
          model_year: null,
          quoted: "Leopard 7",
          budget: null,
          destination: null,
          asked_at: new Date().toISOString(),
        },
      ],
      worth: { sold: 0, price: null, landed: null, on_top: null, days_to_sell: null },
      bid: null,
    },
  ],
};

describe("BuyingList", () => {
  it("names each car, who asked in their own words, and the most to pay", () => {
    render(
      <LocaleProvider locale="en">
        <BuyingList list={list} tenant="pollux" />
      </LocaleProvider>,
    );
    expect(screen.getByText("Ahmed").closest("a")?.getAttribute("href")).toBe(
      "/pollux/customers/c-1",
    );
    expect(screen.getByText("لاند كروزر")).toBeTruthy();
    expect(
      screen.getByText("Sold in a year: 1 · median price AED 235,000 · 10 days to sell"),
    ).toBeTruthy();
    expect(screen.getAllByText("AED 198,000").length).toBeGreaterThan(0);
    expect(screen.getByText(/You have not sold one in a year/)).toBeTruthy();
  });

  it("says so when nobody asked for a car the dealer lacks", () => {
    render(
      <LocaleProvider locale="en">
        <BuyingList list={{ ...list, cars: [] }} tenant="pollux" />
      </LocaleProvider>,
    );
    expect(screen.getByText(/nobody asked for a car you do not have/)).toBeTruthy();
  });
});

describe("BidLines", () => {
  it("takes each cost off the price and warns when nothing is left", () => {
    render(
      <LocaleProvider locale="en">
        <BidLines bid={{ ...bid, max_bid: aed(0) }} />
      </LocaleProvider>,
    );
    expect(screen.getByText("12%")).toBeTruthy();
    expect(screen.getByText("− AED 8,000")).toBeTruthy();
    expect(screen.getByText(/not worth buying/)).toBeTruthy();
  });
});
