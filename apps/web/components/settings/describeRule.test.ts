import { describe, expect, it } from "vitest";
import { t } from "@/lib/i18n";
import { describeRule } from "./describeRule";

const teams = [
  { id: "local", name: "Local sales", member_ids: [] },
  { id: "export", name: "Export", member_ids: [] },
];
const en = (key: Parameters<typeof t>[1]) => t("en", key);

describe("a routing rule in words", () => {
  it("says every part it has", () => {
    const rule = { languages: ["ar", "fr"], countries: ["DZ", "MA"], from_ad: true, team_id: "export" };
    expect(describeRule(rule, teams, en)).toBe("Arabic or French · from DZ, MA · from an ad → Export");
  });

  it("matches everybody when it has no parts", () => {
    expect(describeRule({ languages: [], countries: [], from_ad: null, team_id: "local" }, teams, en))
      .toBe("Everyone → Local sales");
  });

  it("names a team that no longer exists as a question, not an id", () => {
    expect(describeRule({ languages: ["en"], team_id: "gone" }, teams, en)).toBe("English → ?");
  });

  it("can say not from an ad", () => {
    expect(describeRule({ from_ad: false, team_id: "local" }, teams, en)).toBe(
      "not from an ad → Local sales",
    );
  });
});
