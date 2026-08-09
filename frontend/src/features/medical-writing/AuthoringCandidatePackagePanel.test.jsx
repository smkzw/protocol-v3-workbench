import { describe, expect, it } from "vitest";

import {
  buildCompositePathOverrides,
  collectExplicitCompositeSkips,
  compactCandidatePreview,
  compositeAdoptionReady,
  compositeCandidateBlockedCode,
  compositeCandidateBlockedReason,
  compositeDecisionPaths,
  formatPathValue,
  isPendingCompositeCandidate,
  serializeCompositePathOverride,
  sortCompositeCandidates,
  splitCompositeListValue,
} from "./AuthoringCandidatePackagePanel";

const pendingPackage = {
  candidate_id: "candidate-pending",
  candidate_scope: "design_package",
  recommendation_role: "pending_decision",
  adoption_mode: "manual_only",
  evidence_status: "insufficient",
  target_paths: [
    "design.randomization",
    "design.blinding",
    "design.interim_analysis",
  ],
  structured_value: {
    "design.randomization": "随机",
    "design.blinding": "双盲",
    "design.interim_analysis": "待确认",
  },
};

const safeCandidate = {
  candidate_id: "candidate-safe",
  candidate_scope: "design_package",
  recommendation_role: "recommended",
  adoption_mode: "batch_allowed",
  evidence_status: "supported",
  target_paths: ["design.randomization", "design.blinding"],
  structured_value: {
    "design.randomization": "随机",
    "design.blinding": "双盲",
  },
};

describe("AI-first composite package approval", () => {
  it("renders structured defaults as human-readable Chinese instead of raw JSON", () => {
    expect(formatPathValue({ enabled: false, features: [] })).toBe("启用状态：否；具体特征：未设置");
    expect(formatPathValue({ mode: "", blinded_roles: [] })).toBe("模式：待确认；盲态角色：未设置");
    expect(formatPathValue({ planned: false })).toBe("计划状态：否");
    expect(formatPathValue({ src: false, dmc: false })).toBe("SRC：否；DMC：否");
  });

  it("treats every contributed path of a pending-like candidate as a decision path", () => {
    // The backend per-path gate requires an override or explicit skip for
    // EVERY target path of a restricted candidate — AI-resolved values are
    // never carried as implicit overrides.
    expect(isPendingCompositeCandidate(pendingPackage)).toBe(true);
    expect(compositeCandidateBlockedCode(pendingPackage)).toBe("pending_decision");
    expect(compositeDecisionPaths(pendingPackage)).toEqual(pendingPackage.target_paths);
  });

  it("does not mistake neutral nested scaffold defaults for AI decisions", () => {
    const scaffold = {
      candidate_id: "candidate-structure-only",
      candidate_scope: "module",
      recommendation_role: "pending_decision",
      target_paths: [
        "design.adaptive_design",
        "design.phase1_parts",
        "design.src_dmc",
      ],
      structured_value: {
        "design.adaptive_design": { enabled: false, features: [] },
        "design.phase1_parts": {
          parts: [],
          sequence: "",
          available_part_types: ["SAD", "MAD"],
        },
        "design.src_dmc": { src: false, dmc: false },
      },
    };

    expect(compositeDecisionPaths(scaffold)).toEqual(scaffold.target_paths);
    expect(compositeAdoptionReady(scaffold)).toBe(false);
  });

  it("keeps the backend composite contract complete: restricted candidates need a decision on every path", () => {
    expect(compositeAdoptionReady(pendingPackage)).toBe(false);
    // One decided path of three is not enough.
    expect(
      compositeAdoptionReady(
        pendingPackage,
        { "design.interim_analysis": "不设置期中分析" },
        {},
      ),
    ).toBe(false);
    // Every path explicitly decided (override or skip) enables adoption.
    expect(
      compositeAdoptionReady(
        pendingPackage,
        {
          "design.interim_analysis": "不设置期中分析",
          "design.randomization": "随机",
          "design.blinding": "双盲",
        },
        {},
      ),
    ).toBe(true);
    expect(
      buildCompositePathOverrides(
        pendingPackage,
        {
          "design.interim_analysis": "不设置期中分析",
          "design.randomization": "随机",
          "design.blinding": "双盲",
        },
        {},
      ),
    ).toEqual({
      "design.randomization": "随机",
      "design.blinding": "双盲",
      "design.interim_analysis": "不设置期中分析",
    });
    // Un-decided paths are never carried as implicit overrides.
    expect(
      buildCompositePathOverrides(
        pendingPackage,
        { "design.interim_analysis": "不设置期中分析" },
        {},
      ),
    ).toEqual({ "design.interim_analysis": "不设置期中分析" });
  });

  it("classifies unsafe alternatives and keeps them out of zero-override adoption", () => {
    const manualOnly = {
      ...safeCandidate,
      candidate_id: "candidate-manual",
      adoption_mode: "manual_only",
    };
    const insufficient = {
      ...safeCandidate,
      candidate_id: "candidate-insufficient",
      evidence_status: "insufficient",
    };
    const gapCarrier = {
      ...safeCandidate,
      candidate_id: "candidate-gap",
      evidence_gaps: ["声称内容未在引用原文中出现：双盲优于单盲"],
    };
    expect(compositeCandidateBlockedCode(manualOnly)).toBe("manual_only");
    expect(compositeCandidateBlockedCode(insufficient)).toBe("insufficient");
    expect(compositeCandidateBlockedCode(gapCarrier)).toBe("unsupported_gap");
    for (const unsafe of [manualOnly, insufficient, gapCarrier]) {
      expect(isPendingCompositeCandidate(unsafe)).toBe(true);
      expect(compositeCandidateBlockedReason(unsafe)).not.toBe("");
      // Zero-override adoption of an unsafe alternative is never enabled.
      expect(compositeAdoptionReady(unsafe, {}, {})).toBe(false);
      // Explicit decision on every path re-enables the audited override path.
      expect(
        compositeAdoptionReady(
          unsafe,
          { "design.randomization": "随机", "design.blinding": "双盲" },
          {},
        ),
      ).toBe(true);
    }
  });

  it("keeps genuinely safe alternatives zero-override selectable", () => {
    expect(compositeCandidateBlockedCode(safeCandidate)).toBe("");
    expect(isPendingCompositeCandidate(safeCandidate)).toBe(false);
    expect(compositeDecisionPaths(safeCandidate)).toEqual([]);
    expect(compositeAdoptionReady(safeCandidate, {}, {})).toBe(true);
    expect(compositeAdoptionReady(safeCandidate)).toBe(true);
  });

  it("leaves an empty recommendation slot empty instead of promoting an alternative", () => {
    const emptySlot = {
      field_path: "package.design",
      recommended_candidate_id: "",
      candidates: [
        { ...pendingPackage, candidate_id: "candidate-gap", evidence_gaps: ["声称内容未在引用原文中出现：X"] },
        { ...safeCandidate, candidate_id: "candidate-safe-alt" },
      ],
    };
    const sorted = sortCompositeCandidates(emptySlot);
    expect(sorted.recommended).toBeNull();
    // The safe alternative stays visible and selectable, but is not
    // auto-promoted into the recommendation slot.
    expect(sorted.displayCandidates.map((item) => item.candidate_id)).toContain("candidate-safe-alt");
  });

  it("does not promote a pending-like slot occupant into the recommended card", () => {
    const pendingSlot = {
      field_path: "package.design",
      recommended_candidate_id: pendingPackage.candidate_id,
      candidates: [
        pendingPackage,
        { ...safeCandidate, candidate_id: "candidate-safe-alt" },
      ],
    };
    const sorted = sortCompositeCandidates(pendingSlot);
    expect(sorted.recommended).toBeNull();
    expect(sorted.displayCandidates.map((item) => item.candidate_id)).toContain("candidate-safe-alt");
  });

  it("serializes list-valued paths from candidate metadata while preserving scalar text", () => {
    const listPaths = [
      "picos.inclusion_modules",
      "picos.exclusion_modules",
      "picos.washout_rules",
      "picos.allowed_concomitant_rules",
      "picos.required_background_rules",
      "picos.prohibited_concomitant_rules",
      "picos.assessment_timing_restrictions",
      "picos.primary_objectives",
      "picos.secondary_objectives",
      "picos.exploratory_objectives",
      "picos.key_secondary_endpoints",
      "picos.other_secondary_endpoints",
      "picos.exploratory_endpoints",
      "picos.safety_endpoints",
      "picos.aesi_definitions",
      "picos.study_epochs",
    ];
    const candidate = {
      candidate_id: "candidate-lists",
      candidate_scope: "module",
      recommendation_role: "pending_decision",
      target_paths: [
        "picos.intervention_summary",
        ...listPaths,
      ],
      structured_value: {
        "picos.intervention_summary": "",
        ...Object.fromEntries(listPaths.map((path) => [path, []])),
      },
    };

    expect(splitCompositeListValue("规则 A\n规则 B；规则 A;  ")).toEqual([
      "规则 A",
      "规则 B",
    ]);
    const overrides = buildCompositePathOverrides(candidate, {
      "picos.intervention_summary": "  保留用户原始表述  ",
      ...Object.fromEntries(listPaths.map((path) => [path, "规则 A\n规则 B；规则 A"])),
    });
    expect(overrides["picos.intervention_summary"]).toBe("保留用户原始表述");
    listPaths.forEach((path) => {
      expect(overrides[path]).toEqual(["规则 A", "规则 B"]);
    });
  });

  it("serializes assessment-instrument text into backend-valid structured list items", () => {
    const candidate = {
      candidate_id: "candidate-instruments",
      candidate_scope: "module",
      recommendation_role: "pending_decision",
      target_paths: ["picos.assessment_instruments"],
      structured_value: {
        "picos.assessment_instruments": [],
      },
    };

    const serialized = serializeCompositePathOverride(
      candidate,
      "picos.assessment_instruments",
      "SNOT-22\nLund-Kennedy",
    );
    expect(serialized).toEqual([
      {
        instrument_id: expect.stringMatching(/^manual_instrument_[0-9a-f]{8}$/),
        canonical_name_zh: "SNOT-22",
        instrument_kind: "other",
        confirmation_status: "candidate",
      },
      {
        instrument_id: expect.stringMatching(/^manual_instrument_[0-9a-f]{8}$/),
        canonical_name_zh: "Lund-Kennedy",
        instrument_kind: "other",
        confirmation_status: "candidate",
      },
    ]);
    expect(serialized[0].instrument_id).not.toBe(serialized[1].instrument_id);
  });

  it("allows every decision path to be explicitly skipped but not left undecided", () => {
    const entirelyUnresolved = {
      candidate_id: "candidate-all-unresolved",
      candidate_scope: "module",
      recommendation_role: "pending_decision",
      target_paths: ["picos.primary_objectives", "picos.secondary_objectives"],
      structured_value: {
        "picos.primary_objectives": [],
        "picos.secondary_objectives": [],
      },
    };
    const allSkipped = {
      "picos.primary_objectives": true,
      "picos.secondary_objectives": true,
    };
    expect(compositeAdoptionReady(entirelyUnresolved, {}, allSkipped)).toBe(true);
    expect(buildCompositePathOverrides(entirelyUnresolved, {}, allSkipped)).toEqual({});
    expect(collectExplicitCompositeSkips(entirelyUnresolved, allSkipped)).toEqual([
      "picos.primary_objectives",
      "picos.secondary_objectives",
    ]);
    expect(compositeAdoptionReady(entirelyUnresolved, {}, {})).toBe(false);
  });

  it("keeps the default summary compact even when a package contains many fields", () => {
    expect(compactCandidatePreview({
      preview: "随机；双盲；安慰剂对照；平行分组；多中心；不设置期中分析",
    })).toBe("随机；双盲；安慰剂对照；平行分组；其余设计已纳入整包建议");
  });
});
