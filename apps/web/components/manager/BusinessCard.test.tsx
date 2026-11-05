import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ManagerDashboard } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";
import { BusinessCard } from "./BusinessCard";

const aed = (major: number) => ({ amount_minor: major * 100, currency: "AED" });

const business: NonNullable<ManagerDashboard["business"]> = {
  month: {
    sold: 2,
    revenue: aed(420_000),
    gross: aed(20_000),
    costed: 1,
    gross_per_car: aed(20_000),
    avg_days_held: 30,
  },
  in_stock: 3,
  tied_up: aed(600_000),
  holding_per_day: aed(132),
  old_after_days: 45,
  costly: [
    {
      vehicle_id: "car-1",
      label: "2025 BYD Destroyer 05",
      days_held: 73,
      holding: aed(3_200),
      margin_left: aed(-1_200),
    },
  ],
};

describe("BusinessCard", () => {
  it("says what the month made, and that it is only the cars with a cost", () => {
    render(
      <LocaleProvider locale="en">
        <BusinessCard business={business} tenant="pollux" />
      </LocaleProvider>,
    );
    expect(screen.getByText("Gross this month")).toBeTruthy();
    expect(screen.getAllByText("AED 20,000")).toHaveLength(2);
    expect(screen.getByText("Only the cars with a cost: 1 / 2")).toBeTruthy();
  });

  it("names the car costing money to keep, links to it, and marks a margin gone", () => {
    render(
      <LocaleProvider locale="ar">
        <BusinessCard business={business} tenant="pollux" />
      </LocaleProvider>,
    );
    const car = screen.getByText("2025 BYD Destroyer 05").closest("a");
    expect(car?.getAttribute("href")).toBe("/pollux/inventory/car-1");
    expect(screen.getByText("AED 3,200")).toBeTruthy();
    expect(screen.getByText("AED -1,200").closest("span.text-danger")).toBeTruthy();
  });

  it("says so when no car is old yet", () => {
    render(
      <LocaleProvider locale="en">
        <BusinessCard business={{ ...business, costly: [] }} tenant="pollux" />
      </LocaleProvider>,
    );
    expect(screen.getByText("No car has been held that long.")).toBeTruthy();
  });
});
