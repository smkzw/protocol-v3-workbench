// R27 全链路自检（本轮）P0-A：部分覆盖语料门的例外放行死锁。
// 现场（proj_user_e9798b965c99）：已覆盖2项+缺失3项时——前端勾5个
// →后端422『must acknowledge every current missing requirement』（要求
// 确认集与缺失集精确相等）；只勾3个→前端按钮禁用『请先逐项确认全部
// 缺口』。根因：勾选清单渲染 gate.requirements 的5项（含已满足），
// allAcknowledged/提交却按 missing_requirements 的3项比对——两侧标签
// 串不一致时（已满足项标签≠缺失项标签文本）勾全部必被后端拒、勾缺
// 失集则前端判不齐=界面永不可满足。
// 契约（红先修后）：①勾选框只渲染当前缺失项（已满足项显示状态行，
// 无勾选框）；②提交集按当前缺失集过滤，保证 acknowledged==missing；
// ③勾齐缺失项后按钮即可用且提交载荷=缺失集。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MedicalWritingAuthoringJourneySetup } from "./MedicalWritingAuthoringJourneySetup";

const PROJECT_ID = "proj_override_deadlock_front";
const COVERED_A = "竞品候选研究已完成人工相关性分诊（要求侧标签A）";
const COVERED_B = "至少一份相关Protocol已完成内容校验与结构化解析（要求侧标签B）";
const MISSING_1 = "英文竞品方案关键章节已形成监管中文参考译文";
const MISSING_2 = "项目适用中文语料已完成医学准入";
const MISSING_3 = "PICOS关键设计事实与语料冲突已处置";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function journeyPayload({ missing, requirements, access_permitted = false }) {
  return {
    project_id: PROJECT_ID,
    revision: 4,
    entry_mode: "guided_greenfield",
    current_stage: "corpus",
    framing_complete: true,
    picos_complete: true,
    corpus_gate: {
      readiness_status: "not_ready",
      access_permitted,
      missing_requirements: missing,
      requirements,
      override: { active: false, reason: "", actor: "", recorded_at: null, acknowledged_missing_requirements: [] },
    },
    search_plan: { plan_id: "plan_x", registry_filter: {}, latest_snapshot_id: "snap_x" },
    corpus_triage: { status: "finalized", snapshot_id: "snap_x", retained_candidate_ids: ["NCT1"] },
    study_definition: null,
    prefill_package: null,
  };
}

function installFetch({ missing, requirements }) {
  const overrides = [];
  const fetchMock = vi.fn(async (url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
      return Promise.resolve(jsonResponse(journeyPayload({ missing, requirements })));
    }
    if (url.includes("/research-pipeline/status")) return Promise.resolve(jsonResponse({ pipeline: null }));
    if (url.includes("/fact-intake/study_framing")) return Promise.resolve(jsonResponse({ available: false }));
    if (method === "POST" && url.includes("/corpus-gate/override")) {
      overrides.push(JSON.parse(options.body || "{}"));
      return Promise.resolve(jsonResponse(journeyPayload({ missing, requirements, access_permitted: true })));
    }
    return Promise.resolve(jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, overrides };
}

async function renderCorpusStage({ missing, requirements }) {
  const { overrides } = installFetch({ missing, requirements });
  const { MedicalWritingAuthoringJourneySetup: Setup } = await import("./MedicalWritingAuthoringJourneySetup.jsx");
  render(<Setup projectId={PROJECT_ID} projectHeader={{}} />);
  await waitFor(() => {
    expect(
      document.querySelectorAll(".authoring-gate-checklist").length,
    ).toBeGreaterThan(0);
  });
  return { overrides };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("corpus override partial-coverage deadlock (R27 P0-A)", () => {
  it("renders checkboxes only for current missing items and submits exactly the missing set", async () => {
    const missing = [MISSING_1, MISSING_2, MISSING_3];
    const requirements = [
      { label: COVERED_A, satisfied: true, detail: "" },
      { label: COVERED_B, satisfied: true, detail: "" },
      { label: MISSING_1, satisfied: false, detail: "" },
      { label: MISSING_2, satisfied: false, detail: "" },
      { label: MISSING_3, satisfied: false, detail: "" },
    ];
    const { overrides } = await renderCorpusStage({ missing, requirements });

    // 展开例外放行面板（如以details呈现）。
    const summary = screen.queryByText(/在保留全部缺口的情况下例外进入写作/);
    if (summary) fireEvent.click(summary);

    // ①勾选框只渲染缺失3项（已满足项不得带可勾选input）。
    await waitFor(() => {
      const boxes = Array.from(document.querySelectorAll(
        ".authoring-gate-checklist input[type='checkbox']",
      ));
      expect(boxes.length).toBe(3);
    });

    // ②勾齐缺失项后按钮可用，提交载荷=缺失集精确相等。
    const boxes = Array.from(document.querySelectorAll(
      ".authoring-gate-checklist input[type='checkbox']:not(:disabled)",
    ));
    for (const box of boxes) fireEvent.click(box);
    const submit = await waitFor(() => {
      const btn = Array.from(document.querySelectorAll("button")).find(
        (b) => b.textContent.includes("确认例外并放行") && !b.disabled,
      );
      expect(btn).toBeTruthy();
      return btn;
    });
    fireEvent.click(submit);
    await waitFor(() => expect(overrides.length).toBe(1));
    expect(overrides[0].acknowledged_missing_requirements.sort()).toEqual(
      [...missing].sort(),
    );
  });
});
