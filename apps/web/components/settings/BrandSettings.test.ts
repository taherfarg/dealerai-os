import { describe, expect, it } from "vitest";
import { confirmationFrom, formFrom } from "./BrandSettings";

const draft = {
  colors: { primary: "#0A2540", secondary: "#C8A15A" },
  palette: [
    { hex: "#0A2540", share: 0.8 },
    { hex: "#C8A15A", share: 0.17 },
  ],
  typography: { heading: { family: "Montserrat", weight: 800, style: "sans" } },
  tone: { voice: "confident", person: "we", formality: "medium", emoji: "sparse" },
  cta_styles: [
    { text: "DM to book a viewing", locale: "en" },
    { text: "راسلنا لحجز معاينة", locale: "ar" },
  ],
  hashtag_rules: { max: 3 },
  photography_style: "Studio, white floor.",
  logo_asset_id: "6a6c0c4e-0000-4000-8000-000000000001",
};

describe("formFrom and confirmationFrom", () => {
  it("confirms what the reading proposed, unchanged, when the person changes nothing", () => {
    expect(confirmationFrom(formFrom(draft))).toEqual({
      colors: { primary: "#0A2540", secondary: "#C8A15A" },
      typography: { heading: { family: "Montserrat", weight: 800 }, body: null, arabic: null },
      tone: { voice: "confident", person: "we", formality: "medium", emoji: "sparse" },
      cta_styles: draft.cta_styles,
      hashtag_rules: { max: 3 },
      photography_style: "Studio, white floor.",
      logo_asset_id: draft.logo_asset_id,
    });
  });

  it("cannot be confirmed without a primary colour", () => {
    const form = formFrom({ ...draft, colors: {} });
    expect(confirmationFrom(form)).toBeNull();
  });

  it("drops a call to action somebody emptied", () => {
    const form = formFrom(draft);
    form.ctas[0] = { ...form.ctas[0], text: "  " };
    expect(confirmationFrom(form)?.cta_styles).toEqual([{ text: "راسلنا لحجز معاينة", locale: "ar" }]);
  });

  it("reads an old profile whose calls to action are bare strings", () => {
    expect(formFrom({ colors: { primary: "#000000" }, cta_styles: ["Visit us"] }).ctas).toEqual([
      { text: "Visit us", locale: "en" },
    ]);
  });
});
