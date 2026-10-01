// SMOKE-r1-1 根因2（R27 收敛修订）反例：管线非终态时前端
// authoringWriteBlocked 同源冻结了「完成第一步」与「保存草稿」——分诊实测
// 38 分钟期间用户整页只读（浏览器证据：两按钮全程 disabled，阻断文案
// 「研究流水线正在分诊中；为保持检索/分诊快照冻结，暂不能保存研究框架…」）。
// 旧契约的单测侧证：tests/test_medical_writing_pipeline_empty_state.py 的
// test_authoring_writes_block_only_while_pipeline_owns_frozen_inputs ——
// triaging 对 authoring_writes_blocked_by_pipeline 返回 True，而旧 /draft
// 端点与旧 saveDraft 都用这个谓词。
//
// 修后契约（快照冻结范围收窄到已提交字段）：
// 1) triaging：保存草稿可用且真实发出 /stages/framing/draft；完成第一步
//    仍冻结，按钮 title 说明「暂不能完成本阶段（提交）」且草稿可用；
// 2) searching：保存草稿冻结（检索快照写入期），按钮 disabled + title
//    给出可操作中文说明。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MedicalWritingAuthoringJourneySetup } from "./MedicalWritingAuthoringJourneySetup";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

function journeyPayload() {
  const framing = {
    protocol_id: "",
    version: "",
    document_title: "",
    indication: "心力衰竭",
    study_phase: "III",
    investigational_product: "TestDrug",
    design_pattern: "",
    population_intent: "",
    intrinsic_objectives: [],
    product_profile: {
      technology_type: "unknown",
      exposure_scope: "unknown",
      dosage_forms: [],
      administration_routes: [],
    },
    structured_design: {
      arm_or_cohort_kind: "",
      arm_or_cohort_labels: [],
    },
  };
  return {
    project_id: "proj_draft_release_test",
    revision: 3,
    entry_mode: "guided_greenfield",
    current_stage: "framing",
    framing_complete: false,
    picos_complete: false,
    framing,
    framing_draft: {
      stage: "framing",
      framing,
      missing_required_fields: ["protocol_id"],
      saved_from_revision: 2,
      saved_at: "2026-09-29T03:00:00Z",
      saved_by: "medical_manager",
    },
    synopsis_import: { status: "confirmed" },
    corpus_gate: {
      readiness_status: "not_ready",
      access_permitted: false,
      missing_requirements: [],
      covered_requirements: [],
      requirements: [],
      override: { active: false, reason: "", actor: "", recorded_at: null, acknowledged_missing_requirements: [] },
    },
    // 真实的 triaging 管线先完成了公开检索：search_plan 已绑定快照，
    // 组件的自动最小检索（saveMinimumAndSearch）因此正确跳过。
    search_plan: { plan_id: "plan_draft_release", registry_filter: {}, latest_snapshot_id: "wref_search_draft_release" },
    corpus_triage: { status: "", snapshot_id: "", retained_candidate_ids: [] },
    study_definition: null,
    prefill_package: null,
  };
}

function installFetch({ pipelineStage } = {}) {
  const draftBodies = [];
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
      return Promise.resolve(jsonResponse(journeyPayload()));
    }
    if (method === "GET" && url.endsWith("/medical-writing/research-pipeline/status")) {
      return Promise.resolve(jsonResponse({
        pipeline: pipelineStage
          ? { pipeline_id: "mwpipe_draft_release", stage: pipelineStage, percent: 40 }
          : null,
      }));
    }
    if (method === "GET" && url.includes("/fact-intake/study_framing")) {
      return Promise.resolve(jsonResponse({ available: false }));
    }
    if (method === "POST" && url.includes("/stages/framing/draft")) {
      try { draftBodies.push(JSON.parse(options.body || "{}")); } catch { draftBodies.push({}); }
      return Promise.resolve(jsonResponse(journeyPayload()));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, draftBodies };
}

async function renderOnFramingStage(pipelineStage) {
  render(<MedicalWritingAuthoringJourneySetup projectId="proj_draft_release_test" projectHeader={{}} />);
  await screen.findByRole("checkbox", { name: /口服/ });
  if (pipelineStage) {
    await waitFor(() => expect(screen.getByText(/研究流水线正在/)).toBeTruthy());
  }
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("pipeline draft release (SMOKE-r1-1 RC2)", () => {
  it("triaging keeps the draft save usable while the stage commit stays frozen", async () => {
    const { draftBodies } = installFetch({ pipelineStage: "triaging" });
    await renderOnFramingStage("triaging");

    // 先制造脏状态（无修改时保存草稿按钮本就因「无修改」禁用，与管线无关）
    fireEvent.change(screen.getByLabelText("方案号"), { target: { value: "MW-REL-001" } });

    const draftButton = screen.getByRole("button", { name: /保存草稿/ });
    expect(draftButton.disabled).toBe(false);

    const commitButton = screen.getByRole("button", { name: /完成第一步/ });
    expect(commitButton.disabled).toBe(true);
    expect(commitButton.title).toContain("暂不能完成本阶段（提交）");
    expect(commitButton.title).toContain("草稿仍可正常编辑与保存");

    fireEvent.click(draftButton);
    await waitFor(() => expect(screen.getByText(/草稿已保存/)).toBeTruthy());
    // 夹具的 search_plan 已绑定快照（真实 triaging 现状），自动最小检索
    // 被正确跳过；即便未来再出现前置自动保存，也断言最后一次草稿保存
    // 携带用户编辑。
    const lastBody = draftBodies[draftBodies.length - 1];
    expect(lastBody.stage).toBe("framing");
    expect(lastBody.framing.protocol_id).toBe("MW-REL-001");
  });

  it("searching keeps the draft save frozen with an actionable Chinese hint", async () => {
    installFetch({ pipelineStage: "searching" });
    await renderOnFramingStage("searching");

    // 脏状态下仍被冻结，才证明冻结来自 searching 而非「无修改」
    fireEvent.change(screen.getByLabelText("方案号"), { target: { value: "MW-SEARCH-001" } });

    const draftButton = screen.getByRole("button", { name: /保存草稿/ });
    expect(draftButton.disabled).toBe(true);
    expect(draftButton.title).toContain("暂不能保存草稿");
    expect(draftButton.title).toContain("检索");
  });

  it("no pipeline leaves both surfaces untouched", async () => {
    installFetch({});
    await renderOnFramingStage();
    expect(screen.getByText(/研究药物、适应症和研究分期足以启动竞品检索/)).toBeTruthy();
  });
});
