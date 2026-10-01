// L1/L2/L4 反例（红先修后，复现 R26-MW/R26-QA 现场死锁）：
// 1) L1：非只读写作流中，研究框架/PICOS 的表单体（6组字段标签）默认折叠在
//    「高级微调」里，且每次切换步骤都被重置为折叠（R26-MW：建稿失败后返回
//    补填时表单体塌缩，硬刷新不恢复）。
// 2) L2：PICOS 完成被 design_archetype（研究设计类型）阻断时，唯一可设置
//    该字段的「手动选择兼容设计类型」选择器也被折叠（R26-QA：第二步被隐性
//    阻断，字段又只等语料AI生成 → 与例外放行互为前置）。
// 3) L4：必填缺项只报数量不报字段名（R26-QA：靠逐面板排查才找到）。
// 预期行为：
// 1) 高级微调 details 默认展开（含切换步骤、硬刷新后重挂载）；
// 2) design_archetype 为空时设计类型选择器自动展开；
// 3) 草稿保存提示与「完成第二步」禁用理由都点名缺失字段。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MedicalWritingAuthoringJourneySetup } from "./MedicalWritingAuthoringJourneySetup";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => body,
  };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

const PICOS_DRAFT = {
  design_archetype: "",
  population_summary: "成人慢性免疫性血小板减少症患者，既往一线治疗失败。",
  inclusion_modules: ["筛选期血小板计数<30×10^9/L", "年龄18至75岁"],
  exclusion_modules: ["妊娠期或哺乳期女性", "活动性乙型肝炎"],
  intervention_summary: "口服TPO-RA两个剂量组。",
  intervention_dose_regimen: "每日一次口服，连续24周。",
  comparator_summary: "匹配安慰剂，每日一次口服。",
  primary_endpoint: "第24周血小板应答率。",
  safety_endpoints: ["TEAE、SAE发生率"],
  study_epochs: ["筛选期", "双盲治疗期"],
  visit_strategy: "筛选、基线，治疗期每4周访视。",
  estimand_strategy: "治疗策略估计目标下第24周应答差异。",
  sample_size_strategy: "基于预期应答率差异估算。",
  statistical_strategy: "主要终点采用分层分析。",
};

function journeyPayload() {
  return {
    project_id: "proj_required_surfaces_test",
    revision: 22,
    entry_mode: "guided_greenfield",
    current_stage: "picos",
    framing_complete: true,
    picos_complete: false,
    framing: {
      protocol_id: "MW-III-730D1531",
      version: "V0.1",
      document_title: "TPO-RA治疗慢性免疫性血小板减少症的III期研究方案",
      indication: "慢性免疫性血小板减少症",
      clinicaltrials_condition_term: "Immune Thrombocytopenic Purpura",
      study_phase: "III期",
      investigational_product: "R26QA-TP021片",
      design_pattern: "随机、双盲、安慰剂对照、平行组",
      population_intent: "年龄段：成人；疾病状态：慢性免疫性血小板减少症",
      intrinsic_objectives: ["确证性研究"],
    },
    picos: { ...PICOS_DRAFT },
    picos_draft: {
      stage: "picos",
      picos: { ...PICOS_DRAFT },
      missing_required_fields: ["design_archetype"],
      saved_from_revision: 3,
      saved_at: "2026-09-28T11:00:00Z",
      saved_by: "medical_manager",
    },
    synopsis_import: { status: "confirmed" },
    corpus_gate: {
      readiness_status: "not_ready",
      access_permitted: false,
      missing_requirements: ["缺口一：竞品语料尚未分类"],
      covered_requirements: [],
      requirements: [],
      override: {
        active: false,
        reason: "",
        actor: "",
        recorded_at: null,
        acknowledged_missing_requirements: [],
      },
    },
    search_plan: {
      plan_id: "plan-required-surfaces-test",
      registry_filter: {
        condition_term: "Immune Thrombocytopenic Purpura",
        phases: ["PHASE3"],
        study_type: "INTERVENTIONAL",
      },
      triage_criteria: [],
      latest_snapshot_id: "wref_search_required_surfaces_test",
      returned_count: 129,
      public_document_count: 17,
    },
    corpus_triage: { status: "", snapshot_id: "", retained_candidate_ids: [] },
    study_definition: null,
    prefill_package: {
      status: "partial",
      package_revision: 3,
      field_candidates: {
        "picos.design_archetype": {
          field_path: "picos.design_archetype",
          recommended_candidate_id: "",
          candidates: [
            {
              candidate_id: "mwprefillcand_test_archetype",
              field_path: "picos.design_archetype",
              recommendation_role: "pending_decision",
              adoption_mode: "manual_only",
              preview: "待选择研究设计类型",
            },
          ],
        },
        "design.arms_or_cohorts": {
          field_path: "design.arms_or_cohorts",
          recommended_candidate_id: "",
          candidates: [
            {
              candidate_id: "mwprefillcand_test_arms",
              field_path: "design.arms_or_cohorts",
              recommendation_role: "pending_decision",
              adoption_mode: "manual_only",
              preview: "待确认臂/队列结构",
            },
          ],
        },
      },
      progress: {
        total_fields: 2,
        fields_with_recommendation: 0,
        fields_blocked_missing_evidence: 2,
        percent_complete: 0,
        stage: "generated",
        message: "无证据时仅生成待决骨架。",
      },
    },
  };
}

function installFetch({ savedJourney } = {}) {
  const draftBodies = [];
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
      return Promise.resolve(jsonResponse(journeyPayload()));
    }
    if (method === "POST" && url.includes("/stages/picos/draft")) {
      try {
        draftBodies.push(JSON.parse(options.body || "{}"));
      } catch {
        draftBodies.push({});
      }
      return Promise.resolve(jsonResponse(savedJourney || journeyPayload()));
    }
    if (method === "POST" && url.includes("/stages/framing/draft")) {
      try {
        draftBodies.push(JSON.parse(options.body || "{}"));
      } catch {
        draftBodies.push({});
      }
      return Promise.resolve(jsonResponse(savedJourney || journeyPayload()));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, draftBodies };
}

async function renderOnPicosStage() {
  render(
    <MedicalWritingAuthoringJourneySetup
      projectId="proj_required_surfaces_test"
      projectHeader={{}}
    />,
  );
  // 装载后恢复到第二步（无 framing_draft、有 picos_draft，与 R26-QA 现场一致）。
  await screen.findByRole("button", { name: /完成第二步/ });
  return waitFor(() => expect(screen.getByRole("button", { name: /完成第二步/ }).disabled).toBe(true));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("authoring journey required-field surfaces stay reachable and named (L1/L2/L4)", () => {
  it("L1: 高级微调表单体默认展开，第二步与第一步皆可直接编辑", async () => {
    installFetch();
    await renderOnPicosStage();

    const refinement = document.querySelector(".authoring-advanced-refinement");
    expect(refinement).not.toBeNull();
    // 塌缩回归断言：6组表标签必须随表单体默认可见。
    expect(refinement.open).toBe(true);
    expect(screen.getByRole("tab", { name: "设计适用性" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "研究人群" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "干预措施" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "对照" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "结局指标" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "执行与统计" })).toBeTruthy();
  });

  it("L2: design_archetype 为空时「手动选择兼容设计类型」选择器自动展开", async () => {
    installFetch();
    await renderOnPicosStage();

    const picker = document.querySelector(".authoring-manual-design-options");
    expect(picker).not.toBeNull();
    expect(picker.open).toBe(true);
    expect(screen.getByRole("radio", { name: /随机对照确证性研究/ })).toBeTruthy();
  });

  it("L4: 完成第二步被禁用时点名缺失的必填字段", async () => {
    installFetch();
    await renderOnPicosStage();

    const commit = screen.getByRole("button", { name: /完成第二步/ });
    expect(commit.disabled).toBe(true);
    expect(commit.title).toContain("研究设计类型");
  });

  it("L4: 草稿保存后提示缺失字段名称而非仅数量", async () => {
    installFetch({ savedJourney: journeyPayload() });
    await renderOnPicosStage();

    fireEvent.click(screen.getByRole("tab", { name: "研究人群" }));
    const summary = screen.getByLabelText(/目标人群概述/);
    fireEvent.change(summary, { target: { value: `${PICOS_DRAFT.population_summary}（修订）` } });
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));

    await waitFor(() => expect(screen.getByText(/仍缺必填项/)).toBeTruthy());
    // NEW-42 后缺项字段名同时出现在按钮 title 与常显清单里——两处都算命名。
    expect(screen.getAllByText(/研究设计类型/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/仍有\d+项必填内容待确认/)).toBeNull();
  });

  // L2 残余缺口（R26-QA P0-2）：「研究臂/队列」卡片在语料门阻断时唯一入口
  // 「其他/高级微调」落到设计适用性组，而该组此前没有任何臂/队列输入——
  // 用户被锁死。反例：设计适用性组必须提供研究臂/队列手动编辑（结构类型+
  // 组名），并随草稿保存写入 framing.structured_design 权威事实。
  it("L2: 「研究臂/队列」在设计适用性组可手动编辑并写入结构化设计事实", async () => {
    const { draftBodies } = installFetch({ savedJourney: journeyPayload() });
    await renderOnPicosStage();

    fireEvent.click(screen.getByRole("tab", { name: "设计适用性" }));
    const kind = screen.getByLabelText("研究臂/队列结构");
    const labels = screen.getByLabelText("研究臂/队列名称");
    fireEvent.change(kind, { target: { value: "parallel_arms" } });
    fireEvent.change(labels, { target: { value: "试验药组\n对照组" } });
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));

    await waitFor(() => expect(draftBodies.length).toBeGreaterThan(0));
    const framingDraft = draftBodies.find((body) => body.stage === "framing");
    expect(framingDraft).toBeTruthy();
    const structured = framingDraft.framing.structured_design;
    expect(structured.arm_or_cohort_kind).toBe("parallel_arms");
    expect(structured.arm_or_cohort_labels).toEqual(["试验药组", "对照组"]);
  });

  // NEW-7（R27 第1轮末修订）：刷新/重开弹窗后 UI 锚点（stage/group）按项目
  // 恢复——旧行为回到默认「设计适用性」组，用户每刷新一次都要重新找路。
  it("NEW-7: restores the last visited stage-group anchor for the same project after remount", async () => {
    globalThis.sessionStorage.clear();
    installFetch();
    const { unmount } = render(
      <MedicalWritingAuthoringJourneySetup
        projectId="proj_required_surfaces_test"
        projectHeader={{}}
      />,
    );
    await screen.findByRole("button", { name: /完成第二步/ });
    fireEvent.click(screen.getByRole("tab", { name: "结局指标" }));
    await waitFor(() =>
      expect(
        JSON.parse(globalThis.sessionStorage.getItem("workbench.authoring.uiAnchor.proj_required_surfaces_test") || "{}"),
      ).toMatchObject({ stage: "picos", group: "outcomes" }),
    );
    unmount();

    installFetch();
    render(
      <MedicalWritingAuthoringJourneySetup
        projectId="proj_required_surfaces_test"
        projectHeader={{}}
      />,
    );
    await screen.findByRole("button", { name: /完成第二步/ });
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "结局指标" }).getAttribute("aria-selected")).toBe("true"),
    );
  });

  it("NEW-7: clears the anchor when switching to another project", async () => {
    globalThis.sessionStorage.clear();
    installFetch();
    const { rerender } = render(
      <MedicalWritingAuthoringJourneySetup
        projectId="proj_required_surfaces_test"
        projectHeader={{}}
      />,
    );
    await screen.findByRole("button", { name: /完成第二步/ });
    fireEvent.click(screen.getByRole("tab", { name: "结局指标" }));
    await waitFor(() =>
      expect(globalThis.sessionStorage.getItem("workbench.authoring.uiAnchor.proj_required_surfaces_test")).toBeTruthy(),
    );

    // 同一挂载实例切换项目：旧锚点必须被清除，另一项目不得继承界面位置。
    rerender(
      <MedicalWritingAuthoringJourneySetup
        projectId="proj_someone_else"
        projectHeader={{}}
      />,
    );
    await waitFor(() =>
      expect(globalThis.sessionStorage.getItem("workbench.authoring.uiAnchor.proj_required_surfaces_test")).toBeNull(),
    );
  });
});
