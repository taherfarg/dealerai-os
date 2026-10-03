import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoreReasons } from "./ScoreReasons";
import type { LeadDetail } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";

const reasons: LeadDetail["score_reasons"] = [
  { signal: "asked_availability", label: "Asked whether it is available", points: 10, evidence_message_id: null },
  { signal: "went_quiet", label: "Went quiet", points: -5, evidence_message_id: null },
];

const show = (locale: "en" | "ar" = "en") =>
  render(
    <LocaleProvider locale={locale}>
      <ScoreReasons reasons={reasons} />
    </LocaleProvider>,
  );

describe("ScoreReasons", () => {
  it("keeps the plus sign in front of the points, whatever the language around it", () => {
    show("ar");
    const points = screen.getByText("+10");
    expect(points.getAttribute("dir")).toBe("ltr");
    expect(screen.getByText("-5").getAttribute("dir")).toBe("ltr");
  });
});
