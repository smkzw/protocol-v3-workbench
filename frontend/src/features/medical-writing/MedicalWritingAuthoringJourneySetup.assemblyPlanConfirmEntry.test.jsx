// R26 全链路自检节点⑤反例（红先修后）：
// 语料门"正常就绪"（readiness_status=ready + access_permitted=true）路径下，
// 装配计划 available + source_current + 零 blocker 但 confirmation_current=false
// 时，写作入口按钮不得永久 disabled——装配计划唯一的作者确认入口就是
// createDocument 内的 /protocol-assembly-plan/confirm（进入写作平台即确认动作），
// 若按钮因"未确认"而禁用，就形成"按钮需已确认才可点、确认只能靠点按钮"的
// 循环门（现场：按钮 title='方案结构尚未完成核对，暂不能建立工作稿。'）。
// 预期行为：
// 1) 计划完整（available+source_current+0 blocker）→ 按钮可点；
//    点击后先 POST /protocol-assembly-plan/confirm（CAS 补确认）再 POST
//    /greenfield-document 建稿；
// 2) 存在 severity=blocker 的未决问题 → 按钮保持禁用并给出中文字段指引
//    （fail-closed 语义不得因本修复放宽）；
// 3) 已确认（confirmation_current=true）→ 既有就绪路径保持一键可进。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MedicalWritingAuthoringJourneySetup } from "./MedicalWritingAuthoringJourneySetup";

const PROJECT_ID = "proj_assembly_confirm_entry_test";
const PLAN_SHA = "f".repeat(64);
const DEFINITION_SHA = "e".repeat(64);

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

function journeyPayload() {
  return {
    project_id: PROJECT_ID,
    revision: 7,
    entry_mode: "guided_greenfield",
    current_stage: "corpus",
    framing_complete: true,
    picos_complete: true,
    framing: {
      protocol_id: "CMS-ENTRY-T",
      version: "V0.1",
      document_title: "CMS-ENTRY-T治疗骨关节炎的II期临床研究方案",
      indication: "骨关节炎",
      clinicaltrials_condition_term: "Osteoarthritis",
      study_phase: "II期",
      investigational_product: "CMS-ENTRY-T注射液",
    },
    picos: {
      design_archetype: "randomized_confirmatory",
      population_summary: "中重度骨关节炎成人患者",
      intervention_summary: "CMS-ENTRY-T两个剂量组",
      comparator_summary: "安慰剂对照",
      primary_endpoint: "第12周WOMAC疼痛评分变化",
    },
    synopsis_import: { status: "confirmed" },
    corpus_gate: {
      readiness_status: "ready",
      access_permitted: true,
      missing_requirements: [],
      covered_requirements: [],
      requirements: [
        { label: "竞品语料已分类", satisfied: true, detail: "" },
        { label: "关键章节译文可用", satisfied: true, detail: "" },
        { label: "PICOS对齐完成", satisfied: true, detail: "" },
      ],
      override: {
        active: false,
        reason: "",
        actor: "",
        recorded_at: null,
        acknowledged_missing_requirements: [],
      },
    },
    search_plan: {
      plan_id: "plan-confirm-entry-test",
      registry_filter: {
        condition_term: "Osteoarthritis",
        phases: ["PHASE2"],
        study_type: "INTERVENTIONAL",
      },
      triage_criteria: [],
      // 已有检索快照：避免装载期自动最小检索抢跑刷新 journey。
      latest_snapshot_id: "wref_search_confirm_entry_test",
      returned_count: 12,
      public_document_count: 3,
    },
    corpus_triage: { status: "completed", snapshot_id: "wref_search_confirm_entry_test", retained_candidate_ids: [] },
    study_definition: {
      definition_id: "sdef_confirm_entry_test",
      revision: 2,
      state_sha256: DEFINITION_SHA,
    },
    prefill_package: null,
  };
}

function planState({ confirmationCurrent, modules = [] }) {
  return {
    available: true,
    source_current: true,
    confirmation_current: confirmationCurrent,
    stale_reason: "",
    plan: {
      plan_id: "plan-confirm-entry-test",
      revision: 4,
      state_sha256: PLAN_SHA,
      source_definition_id: "sdef_confirm_entry_test",
      source_definition_revision: 2,
      source_definition_sha256: DEFINITION_SHA,
      modules,
    },
  };
}

function confirmedPlanState() {
  return planState({
    confirmationCurrent: true,
    modules: [
      {
        module_id: "intervention",
        unresolved_questions: [
          { code: "q_optional_1", prompt: "背景治疗规则可选细化", severity: "advisory" },
        ],
      },
    ],
  });
}

function blockedPlanState() {
  return planState({
    confirmationCurrent: false,
    modules: [
      {
        module_id: "intervention",
        unresolved_questions: [
          { code: "q_dose", prompt: "试验药物给药方案未确认", severity: "blocker" },
        ],
      },
    ],
  });
}

const CONFIRMED_DOCUMENT = {
  document_id: "doc_confirm_entry_test",
  protocol_id: "CMS-ENTRY-T",
  version: "V0.1",
};

/**
 * 脚本化 fetch：
 * - journey GET（装载）→ 语料门 ready + 研究定义已绑定的正常就绪现场；
 * - 装配计划 GET → 由用例给定的计划状态；
 * - confirm POST → 返回确认后的计划状态；
 * - greenfield-document POST → 建稿回包；
 * - 其余（fact-intake / reference 面板等）→ 404（组件按缺失吞掉）。
 */
function installFetch({ plan }) {
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
      return Promise.resolve(jsonResponse(journeyPayload()));
    }
    if (method === "GET" && url.endsWith("/medical-writing/protocol-assembly-plan")) {
      return Promise.resolve(jsonResponse(plan));
    }
    if (method === "GET" && url.endsWith("/api/medical-writing/protocol-templates/default")) {
      return Promise.resolve(jsonResponse({ template_id: "tpl-default", template_version: "v2024" }));
    }
    if (method === "POST" && url.endsWith("/medical-writing/protocol-assembly-plan/confirm")) {
      return Promise.resolve(jsonResponse(confirmedPlanState()));
    }
    if (method === "POST" && url.endsWith("/medical-writing/greenfield-document")) {
      return Promise.resolve(jsonResponse(CONFIRMED_DOCUMENT));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

function postCalls(fetchMock, suffix) {
  return fetchMock.mock.calls.filter(([url, options = {}]) =>
    url.endsWith(suffix) && (options.method || "GET").toUpperCase() === "POST");
}

async function findWritingEntryButton() {
  return screen.findByRole("button", { name: /进入写作平台|完成核对后进入写作|完成研究定义后进入写作/ });
}

async function renderCorpusStage({ plan }) {
  const { fetchMock } = installFetch({ plan });
  const onCreated = vi.fn();
  render(
    <MedicalWritingAuthoringJourneySetup
      projectId={PROJECT_ID}
      projectHeader={{}}
      onCreated={onCreated}
    />,
  );
  await screen.findByText("语料准备与写作准入");
  return { fetchMock, onCreated };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("assembly-plan confirm-on-entry closes the ready-path deadlock (R26 node ⑤)", () => {
  it("enables the writing entry when the plan is complete but unconfirmed, and the click confirms the plan before creating the document", async () => {
    const { fetchMock, onCreated } = await renderCorpusStage({
      plan: planState({ confirmationCurrent: false }),
    });

    const entry = await findWritingEntryButton();
    // 按钮可点依赖异步装配计划读取——在重负载下 findByRole 先于计划
    // 解析返回，此处等待同一断言成立（R6/R8 全量清单两次flaky根因）。
    await waitFor(() => expect(entry.disabled).toBe(false));

    fireEvent.click(entry);

    await waitFor(() => {
      expect(postCalls(fetchMock, "/medical-writing/protocol-assembly-plan/confirm")).toHaveLength(1);
    });
    const confirmCall = postCalls(fetchMock, "/medical-writing/protocol-assembly-plan/confirm")[0];
    expect(confirmCall[1].body).toContain(`"expected_plan_revision":4`);
    expect(confirmCall[1].body).toContain(`"expected_plan_sha256":"${PLAN_SHA}"`);
    await waitFor(() => {
      expect(postCalls(fetchMock, "/medical-writing/greenfield-document")).toHaveLength(1);
    });
    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ document_id: CONFIRMED_DOCUMENT.document_id }));
    });
  });

  it("keeps the entry disabled with actionable Chinese guidance while blocking drivers remain unresolved", async () => {
    await renderCorpusStage({ plan: blockedPlanState() });

    const entry = await findWritingEntryButton();
    expect(entry.disabled).toBe(true);
    expect(screen.getByText(/还需确认：.*试验药物给药方案未确认/)).toBeTruthy();
  });

  it("keeps the already-confirmed ready path one-click", async () => {
    const { fetchMock, onCreated } = await renderCorpusStage({ plan: confirmedPlanState() });

    const entry = await findWritingEntryButton();
    await waitFor(() => expect(entry.disabled).toBe(false));
    expect(entry.textContent).toContain("进入写作平台");

    fireEvent.click(entry);
    await waitFor(() => {
      expect(postCalls(fetchMock, "/medical-writing/protocol-assembly-plan/confirm")).toHaveLength(1);
    });
    await waitFor(() => {
      expect(onCreated).toHaveBeenCalled();
    });
  });
});
