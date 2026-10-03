import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LocaleProvider } from "@/lib/i18n-client";
import { Auto, CustomerName, Ltr, Sentence } from "./Bidi";

describe("Ltr", () => {
  it("keeps a number the way it is written", () => {
    render(<Ltr>+971500000104</Ltr>);
    const number = screen.getByText("+971500000104");
    expect(number.getAttribute("dir")).toBe("ltr");
    expect(number.className).toContain("tabular-nums");
  });
});

describe("Auto", () => {
  it("lets what a person wrote choose its direction", () => {
    render(<Auto as="p">Le prix pour Oran ?</Auto>);
    const text = screen.getByText("Le prix pour Oran ?");
    expect(text.getAttribute("dir")).toBe("auto");
    expect(text.tagName).toBe("P");
  });
});

describe("Sentence", () => {
  it("takes its direction from its own words, not from a name it begins with", () => {
    // The server sets names apart with isolates; `dir="auto"` reads the first
    // letter anyway, and `unicode-bidi: plaintext` reads past them.
    render(<Sentence>James Whitfield أصبح من عملائك</Sentence>);
    const sentence = screen.getByText("James Whitfield أصبح من عملائك");
    expect(sentence.className).toContain("[unicode-bidi:plaintext]");
    expect(sentence.getAttribute("dir")).toBeNull();
  });
});

describe("CustomerName", () => {
  const show = (name: string | null, locale: "en" | "ar" = "en") =>
    render(
      <LocaleProvider locale={locale}>
        <CustomerName country="AE" name={name} />
      </LocaleProvider>,
    );

  it("keeps the flag out of the name, so the flag cannot turn an Arabic name left to right", () => {
    show("عمر المزروعي");
    const name = screen.getByText("عمر المزروعي");
    expect(name.getAttribute("dir")).toBe("auto");
    expect(name.textContent).toBe("عمر المزروعي");
    expect(name.parentElement?.textContent).toContain("🇦🇪");
  });

  it("cuts a long name at its end, on the element that chooses the direction", () => {
    show("Omar Al Mazrouei");
    expect(screen.getByText("Omar Al Mazrouei").className).toContain("truncate");
  });

  it("says so when nobody knows the name yet", () => {
    show(null, "ar");
    expect(screen.getByText("عميل غير معروف")).toBeDefined();
  });
});
