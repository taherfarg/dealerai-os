import { describe, expect, it } from "vitest";
import { changes } from "./changes";
import { countriesFrom } from "./RuleEditor";

const saved = {
  first_response_target_min: 5,
  unassigned_visible_to_sales: true,
  default_team_id: null as string | null,
  business_hours: { mon: { open: "09:00:00", close: "21:00:00" } },
  routing_rules: [],
};

describe("a routing save", () => {
  it("carries only what changed", () => {
    expect(changes(saved, { ...saved, first_response_target_min: 2 })).toEqual({
      first_response_target_min: 2,
    });
  });

  it("carries nothing when nothing changed", () => {
    expect(changes(saved, { ...saved })).toEqual({});
  });

  it("clears the default team with null, not by leaving it out", () => {
    const withTeam = { ...saved, default_team_id: "local" };
    expect(changes(withTeam, saved)).toEqual({ default_team_id: null });
  });
});

describe("countries typed into a rule", () => {
  it("are two-letter codes however they were written", () => {
    expect(countriesFrom("dz, ma  MA;sa")).toEqual(["DZ", "MA", "SA"]);
    expect(countriesFrom("Algeria")).toEqual([]);
  });
});
