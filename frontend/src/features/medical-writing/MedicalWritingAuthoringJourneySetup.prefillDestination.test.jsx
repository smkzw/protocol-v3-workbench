import { describe, expect, it } from "vitest";

import { prefillDestination } from "./MedicalWritingAuthoringJourneySetup";

describe("prefill card destination mapping (AGG25-P1-5)", () => {
  it("resolves the product-profile and CT.gov cards that previously did nothing", () => {
    for (const fieldPath of [
      "framing.product_profile.technology_type",
      "framing.product_profile.administration_routes",
      "framing.product_profile.exposure_scope",
      "framing.product_profile.confirmed_facts.recommended_phase2_dose",
      "framing.clinicaltrials_condition_term",
    ]) {
      const destination = prefillDestination(fieldPath);
      expect(destination, fieldPath).not.toBeNull();
      expect(destination.stage).toBe("framing");
      expect(destination.group).toBe("identity");
    }
  });

  it("keeps exact mappings for already-covered fields", () => {
    expect(prefillDestination("framing.population_intent")).toEqual({
      stage: "framing",
      group: "purpose",
    });
    expect(prefillDestination("picos.population_summary")).toEqual({
      stage: "picos",
      group: "population",
    });
  });

  it("falls back by prefix for unknown framing/picos paths instead of null", () => {
    expect(prefillDestination("framing.something_new")).toEqual({
      stage: "framing",
      group: "identity",
    });
    expect(prefillDestination("design.new_knob")).toEqual({
      stage: "picos",
      group: "applicability",
    });
  });
});
