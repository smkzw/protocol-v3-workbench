// R6 第6轮末修订 片A′（P0-24 + P2-43 前端契约）：平台入口幂等与已放行提示。
//
// 现场（R6-A w6-13，proj_user_ee74b6fda2c2）：例外放行（rev17）→ 建稿
// 成功（POST greenfield 200）→ 导航重进 → 测试者连点『进入写作平台』
// 8次零响应——后端日志零请求（连 createDocument 首个
// /protocol-templates/default GET 都没有），服务端门状态自洽
// （access_permitted=1、定义已绑定、按钮应可用）。客户端孤儿DOM无法
// 在 jsdom 复现，本文件钉死可在组件层证明的两条硬契约：
// 1) P0-24(b)：点击进入写作平台时必须先 GET /greenfield-document——
//    工作稿已存在（陈旧页签/装载竞态把 setup 挂到已有文档的项目上）
//    时直接经 onCreated 导航进入平台，绝不再次 POST 建稿；
// 2) w6-13 点击契约回归：进入写作平台按钮的 onClick 必须派发
//    （连点8次不得静默——恰好一次建稿/导航，busy 去重）；
// 3) P2-43：重复例外放行收到未膨胀回包（revision 未变）时，界面必须
//    给出『已放行…无需重复放行』而非再次『已记录医学例外放行』。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MedicalWritingAuthoringJourneySetup } from "./MedicalWritingAuthoringJourneySetup";

const PROJECT_ID = "proj_platform_entry_idem_test";
const DEFINITION_SHA = "a".repeat(64);
const PLAN_SHA = "b".repeat(64);

const MISSING_1 = "英文竞品方案关键章节已形成监管中文参考译文";
const MISSING_2 = "项目适用中文语料已完成医学准入";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

function journeyPayload({ revision = 9 } = {}) {
  return {
    project_id: PROJECT_ID,
    revision,
    entry_mode: "guided_greenfield",
    current_stage: "corpus",
    framing_complete: true,
    picos_complete: true,
    framing: {
      protocol_id: "CMS-R6A-T",
      version: "V0.1",
      document_title: "CMS-R6A-T治疗慢性咳嗽的II期临床研究方案",
      indication: "慢性咳嗽",
      clinicaltrials_condition_term: "Refractory Chronic Cough",
      study_phase: "II期",
      investigational_product: "CMS-R6A-T注射液",
    },
    picos: {
      design_archetype: "randomized_confirmatory",
      population_summary: "难治性慢性咳嗽成人患者",
      intervention_summary: "CMS-R6A-T两个剂量组",
      comparator_summary: "安慰剂对照",
      primary_endpoint: "第12周24小时咳嗽次数变化",
    },
    synopsis_import: { status: "confirmed" },
    corpus_gate: {
      readiness_status: "not_ready",
      access_permitted: true,
      missing_requirements: [MISSING_1, MISSING_2],
      covered_requirements: [],
      requirements: [
        { label: "竞品候选研究已完成人工相关性分诊", satisfied: true, detail: "" },
        { label: "至少一份相关Protocol已完成内容校验与结构化解析", satisfied: true, detail: "" },
        { label: MISSING_1, satisfied: false, detail: "" },
        { label: MISSING_2, satisfied: false, detail: "" },
        { label: "PICOS关键设计事实与语料冲突已处置", satisfied: true, detail: "" },
      ],
      override: {
        active: true,
        reason: "先行建稿",
        actor: "medical_manager",
        recorded_at: "2026-10-06T12:53:24Z",
        acknowledged_missing_requirements: [MISSING_1, MISSING_2],
      },
    },
    search_plan: {
      plan_id: "plan-r6a-test",
      registry_filter: {
        condition_term: "Refractory Chronic Cough",
        phases: ["PHASE2"],
        study_type: "INTERVENTIONAL",
      },
      triage_criteria: [],
      latest_snapshot_id: "wref_search_r6a_test",
      returned_count: 32,
      public_document_count: 10,
    },
    corpus_triage: {
      status: "completed",
      snapshot_id: "wref_search_r6a_test",
      retained_candidate_ids: ["NCT1"],
    },
    study_definition: {
      definition_id: "sdef_r6a_test",
      revision: 6,
      state_sha256: DEFINITION_SHA,
    },
    prefill_package: null,
  };
}

function confirmedPlanState() {
  return {
    available: true,
    source_current: true,
    confirmation_current: true,
    stale_reason: "",
    plan: {
      plan_id: "plan-r6a-test",
      revision: 3,
      state_sha256: PLAN_SHA,
      source_definition_id: "sdef_r6a_test",
      source_definition_revision: 6,
      source_definition_sha256: DEFINITION_SHA,
      modules: [],
    },
  };
}

const EXISTING_GREENFIELD = {
  project_id: PROJECT_ID,
  document_id: "doc_r6a_existing",
  protocol_id: "CMS-R6A-T",
  version: "V0.1",
  baseline_revision: 1,
  baseline_sha256: "c".repeat(64),
  source_mode: "greenfield_project_decision",
  decisions: [],
};

const CREATED_DOCUMENT = { document: { document_id: "doc_r6a_created", protocol_id: "CMS-R6A-T", version: "V0.1" } };

function installFetch({ existingDocument = null } = {}) {
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
      return Promise.resolve(jsonResponse(journeyPayload()));
    }
    if (method === "GET" && url.endsWith("/medical-writing/protocol-assembly-plan")) {
      return Promise.resolve(jsonResponse(confirmedPlanState()));
    }
    if (method === "GET" && url.endsWith("/api/medical-writing/protocol-templates/default")) {
      return Promise.resolve(jsonResponse({ template_id: "tpl-default", template_version: "v2024" }));
    }
    if (method === "GET" && url.endsWith("/medical-writing/greenfield-document")) {
      if (!existingDocument) return Promise.resolve(notFound(url));
      return Promise.resolve(jsonResponse(existingDocument));
    }
    if (method === "POST" && url.endsWith("/medical-writing/protocol-assembly-plan/confirm")) {
      return Promise.resolve(jsonResponse(confirmedPlanState()));
    }
    if (method === "POST" && url.endsWith("/medical-writing/greenfield-document")) {
      return Promise.resolve(jsonResponse(CREATED_DOCUMENT));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

function callsOf(fetchMock, suffix, method = "GET") {
  return fetchMock.mock.calls.filter(([url, options = {}]) =>
    url.endsWith(suffix) && (options.method || "GET").toUpperCase() === method);
}

async function findWritingEntryButton() {
  return screen.findByRole("button", { name: /进入写作平台|完成核对后进入写作|完成研究定义后进入写作/ });
}

async function renderCorpusStage({ existingDocument = null } = {}) {
  const { fetchMock } = installFetch({ existingDocument });
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

describe("platform entry idempotency (R6 slice A′)", () => {
  it("navigates via the existing greenfield document (GET first) instead of posting a second creation", async () => {
    const { fetchMock, onCreated } = await renderCorpusStage({
      existingDocument: EXISTING_GREENFIELD,
    });

    const entry = await findWritingEntryButton();
    expect(entry.disabled).toBe(false);

    fireEvent.click(entry);

    await waitFor(() => {
      expect(callsOf(fetchMock, "/medical-writing/greenfield-document", "GET").length).toBeGreaterThanOrEqual(1);
    });
    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({
        document: expect.objectContaining({ document_id: EXISTING_GREENFIELD.document_id }),
      }));
    });
    expect(callsOf(fetchMock, "/medical-writing/greenfield-document", "POST")).toHaveLength(0);
    expect(callsOf(fetchMock, "/medical-writing/protocol-assembly-plan/confirm", "POST")).toHaveLength(0);
  });

  it("still creates (POST path) when no document exists, and 8 rapid clicks yield exactly one creation", async () => {
    const { fetchMock, onCreated } = await renderCorpusStage({ existingDocument: null });

    const entry = await findWritingEntryButton();
    expect(entry.disabled).toBe(false);

    for (let index = 0; index < 8; index += 1) fireEvent.click(entry);

    await waitFor(() => {
      expect(callsOf(fetchMock, "/medical-writing/greenfield-document", "POST")).toHaveLength(1);
    });
    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({
        document: expect.objectContaining({ document_id: CREATED_DOCUMENT.document.document_id }),
      }));
    });
    expect(onCreated).toHaveBeenCalledTimes(1);
  });

  it("tells the user the override is already recorded when a repeat override returns an unbumped journey", async () => {
    const { fetchMock } = installFetch({ existingDocument: null });
    const journey = { ...journeyPayload({ revision: 9 }) };
    journey.corpus_gate = {
      ...journey.corpus_gate,
      access_permitted: false,
      override: { active: false, reason: "", actor: "", recorded_at: null, acknowledged_missing_requirements: [] },
    };
    fetchMock.mockImplementation((url, options = {}) => {
      const method = (options.method || "GET").toUpperCase();
      if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
        return Promise.resolve(jsonResponse(journey));
      }
      if (method === "POST" && url.endsWith("/corpus-gate/override")) {
        // 服务端幂等no-op：门已放行，回包修订号未膨胀。
        const noBump = JSON.parse(JSON.stringify(journey));
        noBump.corpus_gate.access_permitted = true;
        noBump.corpus_gate.override = {
          active: true, reason: "先行建稿", actor: "medical_manager",
          recorded_at: "2026-10-06T12:00:00Z", acknowledged_missing_requirements: [MISSING_1, MISSING_2],
        };
        return Promise.resolve(jsonResponse(noBump));
      }
      if (method === "GET" && url.endsWith("/medical-writing/protocol-assembly-plan")) {
        return Promise.resolve(jsonResponse(confirmedPlanState()));
      }
      return Promise.resolve(notFound(url));
    });
    const onCreated = vi.fn();
    render(
      <MedicalWritingAuthoringJourneySetup
        projectId={PROJECT_ID}
        projectHeader={{}}
        onCreated={onCreated}
      />,
    );
    await screen.findByText("语料准备与写作准入");

    const summary = await screen.findByText(/在保留全部缺口的情况下例外进入写作/);
    fireEvent.click(summary);
    const boxes = Array.from(document.querySelectorAll(".authoring-gate-checklist input[type='checkbox']"));
    expect(boxes.length).toBe(2);
    for (const box of boxes) fireEvent.click(box);
    const submit = await waitFor(() => {
      const btn = Array.from(document.querySelectorAll("button")).find(
        (b) => b.textContent.includes("确认例外并放行") && !b.disabled,
      );
      expect(btn).toBeTruthy();
      return btn;
    });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(callsOf(fetchMock, "/corpus-gate/override", "POST")).toHaveLength(1);
    });
    await waitFor(() => {
      expect(document.body.textContent).toContain("无需重复放行");
    });
  });
});
