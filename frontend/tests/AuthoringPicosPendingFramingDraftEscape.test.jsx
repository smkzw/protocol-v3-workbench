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
  design_pattern: "随机双盲、安慰剂对照的平行组多中心设计",
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

it("「采用当前方案文字建议」应用后立即落库第一步草稿（不再只写UI态）", async () => {
  const savedDraft = journeyPayload({
    revision: 21,
    framing: { ...baseFraming, structured_design: { randomization_mode: "randomized", center_model: "多中心" } },
    framing_draft: {
      stage: "framing",
      framing: { ...baseFraming, structured_design: { randomization_mode: "randomized", center_model: "多中心" } },
      missing_required_fields: [],
      saved_from_revision: 20,
      saved_at: "2026-10-14T00:30:00.000000+00:00",
      saved_by: "medical_manager",
    },
  });
  const draftCalls = [];
  const fetchMock = vi.fn(async (url, options = {}) => {
    const href = String(url);
    if (href.includes("/stages/framing/draft")) {
      draftCalls.push(JSON.parse(options.body || "{}"));
      return okResponse(savedDraft);
    }
    if (href.includes("/medical-writing/authoring-journey")) return okResponse(journeyPayload());
    if (href.includes("/fact-intake/study_framing")) return okResponse({ available: false });
    if (href.includes("/research-pipeline")) {
      return okResponse({ pipeline: { stage: "awaiting_corpus_admission", percent: 90 } });
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
  const applyButton = await screen.findByRole("button", { name: /采用当前方案文字建议/ });
  fireEvent.click(applyButton);
  await waitFor(() => {
    expect(draftCalls.length).toBeGreaterThanOrEqual(1);
  });
  const body = draftCalls[0];
  expect(body.stage).toBe("framing");
  const design = (body.framing || {}).structured_design || {};
  expect(design.randomization_mode).toBe("randomized");
});

it("完成第二步锁定提示同时列出第一步未并入与第二步14项缺失（不再'消失又复现'）", async () => {
  const fetchMock = vi.fn(async (url) => {
    const href = String(url);
    if (href.includes("/medical-writing/authoring-journey")) return okResponse(journeyPayload());
    if (href.includes("/fact-intake/study_framing")) return okResponse({ available: false });
    if (href.includes("/research-pipeline")) {
      return okResponse({ pipeline: { stage: "awaiting_corpus_admission", percent: 90 } });
    }
    return okResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MedicalWritingAuthoringJourneySetup
      projectId={PID}
      projectHeader={{ product_name: "KZ-sGC2201", indication: "慢性自发性荨麻疹", study_phase: "II期" }}
      initialStage="picos"
      onJourneyChanged={vi.fn()}
      onCreated={vi.fn()}
    />,
  );
  const step2 = await screen.findByRole("button", { name: /完成第二步/ });
  // 修前：title 只显示优先级最高的一条（第一步未并入），并入后14项"复现"
  // ——测试者读作表单重置（r2-2现场循环的感知根因）。修后：两条都在。
  expect(step2.title).toMatch(/第一步草稿未并入/);
  expect(step2.title).toMatch(/请先补齐第二步必填项：研究设计类型/);
});

it("采用建议后双草稿落库：framing/draft + picos/draft（含推导的design_archetype）", async () => {
  const drafts = [];
  const savedFraming = journeyPayload({
    revision: 21,
    framing: { ...baseFraming, structured_design: { randomization_mode: "randomized", blinding_mode: "double_blind", comparator_type: "placebo", assignment_model: "平行组", center_model: "多中心" } },
    framing_draft: {
      stage: "framing",
      framing: { ...baseFraming, structured_design: { randomization_mode: "randomized", blinding_mode: "double_blind", comparator_type: "placebo", assignment_model: "平行组", center_model: "多中心" } },
      missing_required_fields: [],
      saved_from_revision: 20,
      saved_at: "2026-10-15T00:00:00.000000+00:00",
      saved_by: "medical_manager",
    },
  });
  const savedPicos = journeyPayload({
    revision: 22,
    picos: { ...basePicos, design_archetype: "randomized_confirmatory" },
    picos_draft: {
      stage: "picos",
      picos: { ...basePicos, design_archetype: "randomized_confirmatory" },
      missing_required_fields: ["population_summary"],
      saved_from_revision: 21,
      saved_at: "2026-10-15T00:00:01.000000+00:00",
      saved_by: "medical_manager",
    },
  });
  const fetchMock = vi.fn(async (url, options = {}) => {
    const href = String(url);
    if (href.includes("/stages/framing/draft")) {
      drafts.push({ stage: "framing", body: JSON.parse(options.body || "{}") });
      return okResponse(savedFraming);
    }
    if (href.includes("/stages/picos/draft")) {
      drafts.push({ stage: "picos", body: JSON.parse(options.body || "{}") });
      return okResponse(savedPicos);
    }
    if (href.includes("/medical-writing/authoring-journey")) return okResponse(journeyPayload());
    if (href.includes("/fact-intake/study_framing")) return okResponse({ available: false });
    if (href.includes("/research-pipeline")) {
      return okResponse({ pipeline: { stage: "awaiting_corpus_admission", percent: 90 } });
    }
    return okResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MedicalWritingAuthoringJourneySetup
      projectId={PID}
      projectHeader={{ product_name: "KZ-sGC2201", indication: "慢性自发性荨麻疹", study_phase: "II期" }}
      initialStage="picos"
      onJourneyChanged={vi.fn()}
      onCreated={vi.fn()}
    />,
  );
  const applyButton = await screen.findByRole("button", { name: /采用当前方案文字建议/ });
  fireEvent.click(applyButton);
  await waitFor(() => {
    expect(drafts.some((item) => item.stage === "framing")).toBe(true);
    expect(drafts.some((item) => item.stage === "picos")).toBe(true);
  });
  const picosDraft = drafts.find((item) => item.stage === "picos");
  expect(picosDraft.body.stage).toBe("picos");
  expect(picosDraft.body.picos.design_archetype).toBe("randomized_confirmatory");
});

it("PICOS阶段保存草稿绑定stages/picos/draft（契约锁定：r2-2后端日志实证断裂面）", async () => {
  const drafts = [];
  const savedPicos = journeyPayload({
    revision: 21,
    picos: { ...basePicos, population_summary: "成人慢性自发性荨麻疹患者" },
    picos_draft: {
      stage: "picos",
      picos: { ...basePicos, population_summary: "成人慢性自发性荨麻疹患者" },
      missing_required_fields: [],
      saved_from_revision: 20,
      saved_at: "2026-10-15T00:00:00.000000+00:00",
      saved_by: "medical_manager",
    },
  });
  const fetchMock = vi.fn(async (url, options = {}) => {
    const href = String(url);
    if (href.includes("/stages/picos/draft")) {
      drafts.push(JSON.parse(options.body || "{}"));
      return okResponse(savedPicos);
    }
    if (href.includes("/medical-writing/authoring-journey")) return okResponse(journeyPayload());
    if (href.includes("/fact-intake/study_framing")) return okResponse({ available: false });
    if (href.includes("/research-pipeline")) {
      return okResponse({ pipeline: { stage: "awaiting_corpus_admission", percent: 90 } });
    }
    return okResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MedicalWritingAuthoringJourneySetup
      projectId={PID}
      projectHeader={{ product_name: "KZ-sGC2201", indication: "慢性自发性荨麻疹", study_phase: "II期" }}
      initialStage="picos"
      onJourneyChanged={vi.fn()}
      onCreated={vi.fn()}
    />,
  );
  fireEvent.click(await screen.findByRole("tab", { name: "研究人群" }));
  const summaryField = await screen.findByLabelText(/目标人群概述/);
  fireEvent.change(summaryField, { target: { value: "成人慢性自发性荨麻疹患者" } });
  const saveButton = await screen.findByRole("button", { name: /保存草稿/ });
  fireEvent.click(saveButton);
  await waitFor(() => {
    expect(drafts.length).toBeGreaterThanOrEqual(1);
  });
  expect(drafts[0].stage).toBe("picos");
  expect(drafts[0].picos.population_summary).toBe("成人慢性自发性荨麻疹患者");
});

it("r2-3场景：画像四字段经服务端回写（unknown）后仍存活并随完成第一步落库", async () => {
  const profileKept = { technology_type: "small_molecule", exposure_scope: "systemic", administration_routes: ["口服"], dosage_forms: ["口服固体制剂"] };
  const committed = journeyPayload({
    revision: 21,
    framing: { ...baseFraming, product_profile: profileKept, design_pattern: "随机双盲、安慰剂对照的平行组多中心设计", population_intent: "成人慢性自发性荨麻疹患者", intrinsic_objectives: ["Proof of Concept", "剂量探索"] },
    framing_complete: true,
    status: "stage2_in_progress",
    current_stage: "picos",
  });
  // 保存草稿回包：服务端旧快照——画像带 unknown 哨兵（现场clobber向量）。
  const staleServer = journeyPayload({ revision: 20 });
  (staleServer.framing.product_profile = { technology_type: "unknown", exposure_scope: "unknown", administration_routes: [], dosage_forms: [] });
  const posts = [];
  const fetchMock = vi.fn(async (url, options = {}) => {
    const href = String(url);
    if (href.includes("/stages/framing/draft")) {
      posts.push({ kind: "draft", body: JSON.parse(options.body || "{}") });
      return okResponse(staleServer);
    }
    if (href.includes("/stages/framing/commit")) {
      posts.push({ kind: "commit", body: JSON.parse(options.body || "{}") });
      return okResponse(committed);
    }
    if (href.includes("impact-preview")) {
      return okResponse({ requires_confirmation: false, preview_id: "", changed_fields: ["framing.product_profile.technology_type"], affected_dependents: [] });
    }
    if (href.includes("/medical-writing/authoring-journey")) return okResponse(journeyPayload());
    if (href.includes("/fact-intake/study_framing")) return okResponse({ available: false });
    if (href.includes("/research-pipeline")) {
      return okResponse({ pipeline: { stage: "awaiting_corpus_admission", percent: 90 } });
    }
    return okResponse({});
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MedicalWritingAuthoringJourneySetup
      projectId={PID}
      projectHeader={{ product_name: "KZ-sGC2201", indication: "慢性自发性荨麻疹", study_phase: "II期" }}
      initialStage="framing"
      onJourneyChanged={vi.fn()}
      onCreated={vi.fn()}
    />,
  );
  // 填画像四字段（第一步 项目与产品 组）
  fireEvent.change(await screen.findByLabelText("药物技术类型", { selector: "select" }), { target: { value: "small_molecule" } });
  fireEvent.change(await screen.findByLabelText("暴露范围", { selector: "select" }), { target: { value: "systemic" } });
  fireEvent.change(await screen.findByLabelText("剂型", { selector: "select" }), { target: { value: "口服固体制剂" } });
  const routeGroup = await screen.findByRole("group", { name: "给药途径" });
  const oralCheckbox = Array.from(routeGroup.querySelectorAll("input[type=\"checkbox\"]"))[0];
  fireEvent.click(oralCheckbox);
  // 服务端回写（保存草稿返回unknown画像）——修前此处把标量清回unknown
  fireEvent.click(await screen.findByRole("button", { name: /保存草稿/ }));
  await waitFor(() => {
    expect(posts.some((item) => item.kind === "draft")).toBe(true);
  });
  // 表单值仍存活
  await waitFor(() => {
    expect(screen.getByLabelText("药物技术类型", { selector: "select" }).value).toBe("small_molecule");
    expect(screen.getByLabelText("暴露范围", { selector: "select" }).value).toBe("systemic");
  });
  // 完成第一步：画像随提交落库
  fireEvent.click(await screen.findByRole("button", { name: /完成第一步/ }));
  await waitFor(() => {
    expect(posts.some((item) => item.kind === "commit")).toBe(true);
  });
  const commitBody = posts.find((item) => item.kind === "commit").body;
  const pp = (commitBody.framing || {}).product_profile || {};
  expect(pp.technology_type).toBe("small_molecule");
  expect(pp.exposure_scope).toBe("systemic");
  expect(pp.administration_routes).toEqual(["口服"]);
  expect(pp.dosage_forms).toEqual(["口服固体制剂"]);
});
