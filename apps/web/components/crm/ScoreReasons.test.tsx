import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoreReasons } from "./ScoreReasons";
import type { LeadDetail } from "@/lib/api/hooks";
import { LocaleProvider } from "@/lib/i18n-client";

const reasons: LeadDetail["score_reasons"] = [
  { signal: "asked_availability", label: "Asked whether it is available", points: 10, evidence_message_id: null },
  { signal: "silent", label: "Has gone quiet", points: -10, evidence_message_id: null },
  { signal: "a_signal_from_next_year", label: "Something new", points: 5, evidence_message_id: null },
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
    expect(screen.getByText("-10").getAttribute("dir")).toBe("ltr");
  });

  it("says a signal it knows in the reader's language, and any other as the API put it", () => {
    show("ar");
    expect(screen.getByText("سأل عن توفر السيارة")).toBeDefined();
    expect(screen.getByText("توقف عن الرد")).toBeDefined();
    expect(screen.getByText("Something new")).toBeDefined();
  });
});
