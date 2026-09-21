import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CustomerRow } from "./CustomerRow";
import type { Customer } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";

const base: Customer = {
  id: "k1",
  name: "Omar Al Mazrouei",
  phone: "+971500000101",
  country: "AE",
  language: "ar",
  tags: ["vip"],
  owner: { id: "u1", name: "Ahmed Nasser", avatar_url: null },
  band: "hot",
  opted_out: false,
  last_seen_at: new Date(Date.now() - 3 * 60_000).toISOString(),
};

const show = (overrides: Partial<Customer>) =>
  render(
    <LocaleProvider locale="en">
      <ul>
        <CustomerRow customer={{ ...base, ...overrides }} href="/pollux-motors/customers/k1" />
      </ul>
    </LocaleProvider>,
  );

describe("CustomerRow", () => {
  it("says who they are, who has them, and how interested they are", () => {
    show({});
    expect(screen.getByText(/Omar Al Mazrouei/)).toBeDefined();
    expect(screen.getByText("+971500000101")).toBeDefined();
    expect(screen.getByText("Ahmed Nasser")).toBeDefined();
    expect(screen.getByText("Hot")).toBeDefined();
    expect(screen.getByText("3m")).toBeDefined();
  });

  it("says nobody owns them rather than leaving a gap", () => {
    show({ owner: null });
    expect(screen.getByText("Nobody")).toBeDefined();
  });

  it("shows no band for a customer with no open lead", () => {
    const { container } = show({ band: null });
    expect(screen.queryByText("Hot")).toBeNull();
    expect(container.querySelector("[data-band='none']")).not.toBeNull();
  });

  it("warns before anybody opens a customer who asked not to be messaged", () => {
    show({ opted_out: true });
    expect(screen.getByText(/asked not to be messaged/i)).toBeDefined();
  });
});
