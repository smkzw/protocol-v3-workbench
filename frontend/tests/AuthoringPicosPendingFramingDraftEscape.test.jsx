import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MedicalWritingAuthoringJourneySetup } from "../src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx";

// 自检r1-2红节点④根因乙（2026-10-13）：第一步草稿（framing_draft）存在且
// 第一步已正式完成时，用户正停留在第二步PICOS填写。「完成第二步」被
// framingPendingDraft 锁死，且按钮提示语「请先保存并完成第一步变更后再
// 提交PICOS」把用户引向保存草稿——而保存草稿正是（重新）制造
// framing_draft、维持锁死的动作（现场 rev18 提交→rev20 草稿保存的乒乓，
// proj_user_ee45e60e004d）。期望行为：PICOS 页内提供一键「并入第一步变更」
// （等价返回第一步点击完成第一步），提示语不得再引导先保存草稿；并入后
// 锁解除、按钮消失。

const PID = "proj_test_picos_pending_draft";

const baseFraming = {
  protocol_id: "MW-II-2026-TEST",
  version: "V0.1",
  document_title: "KZ-sGC1801治疗慢性自发性荨麻疹的临床研究方案",
  indication: "慢性自发性荨麻疹",
  clinicaltrials_condition_term: "",
  study_phase: "II期",
  intrinsic_objectives: ["Proof of Concept", "剂量探索"],
  investigational_product: "KZ-sGC1801",
  target_mechanism: "",
  competitor_target_scope: "",
  development_regions: ["中国"],
  design_pattern: "randomized_double_blind_placebo_controlled",
  population_intent: "成人慢性自发性荨麻疹患者",
  key_uncertainties: [],
  manual_source_ids: [],
  terminology_policy: "cde_participant",
  product_profile: { technology_type: "unknown", administration_routes: [] },
};

const basePicos = {
  design_archetype: "", field_applicability: {}, population_summary: "", inclusion_modules: [], exclusion_modules: [], washout_rules: [], intervention_summary: "", intervention_dose_regimen: "", allowed_concomitant_rules: [], required_background_rules: [], prohibited_concomitant_rules: [], assessment_timing_restrictions: [], intervention_rules: null, comparator_summary: "", primary_endpoint: "", key_secondary_endpoints: [], other_secondary_endpoints: [], exploratory_endpoints: [], safety_endpoints: [], aesi_definitions: [], assessment_instruments: [], study_epochs: [], visit_strategy: "", estimand_strategy: "", sample_size_strategy: "", sample_size_anchor: "", statistical_strategy: "",
};

const journeyPayload = (overrides = {}) => ({
  journey_id: "mwjourney_testpending",
  project_id: PID,
  revision: 20,
  entry_mode: "guided_greenfield",
  framing: baseFraming,
  picos: basePicos,
  framing_draft: {
    stage: "framing",
    framing: baseFraming,
    missing_required_fields: [],
    saved_from_revision: 18,
    saved_at: "2026-10-13T04:26:13.175458+00:00",
    saved_by: "medical_manager",
  },
  picos_draft: null,
  framing_complete: true,
  picos_complete: false,
  status: "stage1_complete",
  current_stage: "picos",
  research_pipeline: { stage: "awaiting_corpus_admission", round1_material_ready: true },
  corpus_gate: { stale: false, requirements: [], missing_requirements: [] },
  search_plan: {
    plan_id: "plan_test_01",
    latest_snapshot_id: "wref_search_test01",
    status: "completed",
    registry_filter: { condition_term: "chronic spontaneous urticaria" },
  },
  discovery_basket_projection: { snapshot_id: "wref_search_test01" },
  prefill_package: {
    package_id: "mwprefill_test01",
    package_revision: 1,
    journey_revision: 20,
    status: "partial",
    field_candidates: [],
    candidates: [],
    partial_source_failures: [],
  },
  synopsis_import: null,
  study_definition: null,
  invalidated_dependents: [],
  picos_corpus_alignment: { status: "pending" },
  available: true,
  ...overrides,
});

const okResponse = (payload) => ({ ok: true, status: 200, json: async () => payload });

afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

it("PICOS页内提供并入第一步草稿的一键出口，不再引导先保存草稿", async () => {
  const promoted = journeyPayload({
    revision: 21,
    framing_draft: null,
    status: "stage2_in_progress",
  });
  const calls = [];
  const fetchMock = vi.fn(async (url, options = {}) => {
    const href = String(url);
    calls.push(`${(options.method || "GET").toUpperCase()} ${href}`);
    if (href.includes("/medical-writing/authoring-journey/stages/framing/commit")) {
      return okResponse(promoted);
    }
    if (href.includes("competitor-search")) {
      // 提交后自动复核检索是幂等重放，回包即并入后的旅程形态。
      return okResponse(promoted);
    }
    if (href.includes("/medical-writing/authoring-journey/impact-preview")) {
      return okResponse({
        requires_confirmation: false,
        preview_id: "",
        changed_fields: ["framing.population_intent"],
        affected_dependents: [],
      });
    }
    if (href.includes("/medical-writing/authoring-journey")) {
      return okResponse(journeyPayload());
    }
    if (href.includes("/fact-intake/study_framing")) {
      return okResponse({ available: false });
    }
    if (href.includes("/medical-writing/research-pipeline")) {
      return okResponse({
        pipeline: { stage: "awaiting_corpus_admission", percent: 90, snapshot_id: "wref_search_test01" },
        started: false,
        reason: "already_running",
      });
    }
    return okResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);

  render(
    <MedicalWritingAuthoringJourneySetup
      projectId={PID}
      projectHeader={{ product_name: "KZ-sGC1801", indication: "慢性自发性荨麻疹", study_phase: "II期" }}
      initialStage="picos"
      onJourneyChanged={vi.fn()}
      onCreated={vi.fn()}
    />,
  );

  // ① PICOS 页内必须出现一键「并入第一步变更」出口（当前缺陷：不存在）。
  const promote = await screen.findByRole("button", { name: /并入第一步变更/ });
  expect(promote).toBeTruthy();

  // ② 「完成第二步」的锁定提示不得再引导用户去保存草稿（保存正是制造
  //    framing_draft、维持锁死的动作）。
  const step2 = await screen.findByRole("button", { name: /完成第二步/ });
  expect(step2.title).not.toMatch(/请先保存/);

  // ③ 点击并入 → 走第一步提交契约（impact-preview → commit），成功后
  //    framing_draft 清空、页内出口消失、锁定解除。
  fireEvent.click(promote);
  await waitFor(() => {
    expect(calls.some((item) => item.includes("/authoring-journey/impact-preview"))).toBe(true);
    expect(calls.some((item) => item.includes("/stages/framing/commit"))).toBe(true);
  });
  await waitFor(() => {
    expect(screen.queryByRole("button", { name: /并入第一步变更/ })).toBeNull();
  });
  const step2After = screen.getByRole("button", { name: /完成第二步/ });
  expect(step2After.title).not.toMatch(/草稿/);
});
