// AGG-P0-03 反例（红先修后）：
// 语料门页面上用户已逐项勾选缺口并填写例外说明后，任何把 journey 修订号
// 推进的刷新（后台语料门重算、公开检索回写等）都不得静默清空勾选与理由
// （R26-MW 现场：「5项缺口勾选+首提报stale revision→重试清空勾选」）。
// 预期行为：
// 1) 缺口集合不变、仅修订号变化 → 勾选与理由原样保留；
// 2) 缺口集合真实变化 → 按 label 重映射：仍在的缺口保持勾选，已消失的移除。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MedicalWritingAuthoringJourneySetup } from "./MedicalWritingAuthoringJourneySetup";

const MISSING_V15 = [
  "缺口一：竞品语料尚未分类",
  "缺口二：方案结构核对未完成",
  "缺口三：语料提取未审阅",
  "缺口四：翻译确认未完成",
  "缺口五：证据绑定未完成",
];
const OVERRIDE_REASON = "公开语料不可得，先行建稿，后续补充登记语料。";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => body,
  };
}

function journeyPayload(revision, missing = MISSING_V15) {
  return {
    project_id: "proj_override_ack_test",
    revision,
    entry_mode: "guided_greenfield",
    current_stage: "corpus",
    framing_complete: true,
    picos_complete: true,
    framing: {
      protocol_id: "CMS-RA-T",
      version: "V0.1",
      document_title: "CMS-RA-T治疗类风湿关节炎的II期临床研究方案",
      indication: "类风湿关节炎",
      clinicaltrials_condition_term: "Rheumatoid Arthritis",
      study_phase: "II期",
      investigational_product: "CMS-RA-T注射液",
    },
    picos: {
      design_archetype: "randomized_confirmatory",
      population_summary: "中重度活动性类风湿关节炎成人患者",
      intervention_summary: "CMS-RA-T两个剂量组",
      comparator_summary: "安慰剂对照",
      primary_endpoint: "第12周ACR20应答率",
    },
    synopsis_import: { status: "confirmed" },
    corpus_gate: {
      readiness_status: "not_ready",
      access_permitted: false,
      missing_requirements: missing,
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
      plan_id: "plan-override-ack-test",
      registry_filter: {
        condition_term: "Rheumatoid Arthritis",
        phases: ["PHASE2"],
        study_type: "INTERVENTIONAL",
      },
      triage_criteria: [],
      // 已有检索快照：避免装载期的自动最小检索抢先刷新 journey，
      // 让"刷新"成为用例里显式点击的动作。
      latest_snapshot_id: "wref_search_override_ack_test",
      returned_count: 12,
      public_document_count: 3,
    },
    corpus_triage: { status: "", snapshot_id: "", retained_candidate_ids: [] },
    study_definition: null,
    prefill_package: null,
  };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

/**
 * 脚本化 fetch：
 * - journey GET（装载）→ rev 15，缺口5项；
 * - POST competitor-search（公开检索回写）→ 由用例给定的刷新后 journey；
 * - fact-intake / research-pipeline 等 → 404（组件按缺失吞掉）。
 */
function installFetch({ refreshedJourney }) {
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
      return Promise.resolve(jsonResponse(journeyPayload(15)));
    }
    if (method === "POST" && url.includes("/competitor-search")) {
      return Promise.resolve(jsonResponse(refreshedJourney));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

async function renderAndAcknowledgeAll() {
  render(
    <MedicalWritingAuthoringJourneySetup
      projectId="proj_override_ack_test"
      projectHeader={{}}
    />,
  );
  await screen.findByText(MISSING_V15[0]);
  for (const label of MISSING_V15) {
    const checkbox = screen.getByLabelText(label);
    if (!checkbox.checked) fireEvent.click(checkbox);
  }
  fireEvent.change(screen.getByLabelText(/例外说明/), {
    target: { value: OVERRIDE_REASON },
  });
}

async function refreshViaPublicSearch(refreshedJourney) {
  installFetch({ refreshedJourney });
  await renderAndAcknowledgeAll();
  fireEvent.click(screen.getByRole("button", { name: /重新检索竞品/ }));
  // 等检索回写把 journey 刷新到位（修订号 15→16）。
  await waitFor(() => expect(screen.getByText(/版本 16/)).toBeTruthy());
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("override acknowledgements survive journey revision refresh (AGG-P0-03)", () => {
  it("keeps the checked gaps and reason when the revision bumps with an unchanged gap set", async () => {
    await refreshViaPublicSearch(journeyPayload(16, MISSING_V15));

    for (const label of MISSING_V15) {
      expect(screen.getByLabelText(label).checked).toBe(true);
    }
    expect(screen.getByLabelText(/例外说明/).value).toBe(OVERRIDE_REASON);
    const override = screen.getByRole("button", { name: /确认例外并放行/ });
    expect(override.disabled).toBe(false);
  });

  it("remaps acknowledgements by label when the gap set actually shrinks", async () => {
    const survivingGaps = MISSING_V15.slice(0, 3);
    await refreshViaPublicSearch(journeyPayload(16, survivingGaps));

    for (const label of survivingGaps) {
      expect(screen.getByLabelText(label).checked).toBe(true);
    }
    expect(screen.queryByLabelText(MISSING_V15[3])).toBeNull();
    expect(screen.getByLabelText(/例外说明/).value).toBe(OVERRIDE_REASON);
  });

  it("keeps the checked gaps after a 409 conflict and failed reconcile", async () => {
    const fetchMock = vi.fn((url, options = {}) => {
      const method = (options.method || "GET").toUpperCase();
      if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
        return Promise.resolve(jsonResponse(journeyPayload(15)));
      }
      if (method === "POST" && url.includes("/corpus-gate/override")) {
        return Promise.resolve(
          jsonResponse(
            { detail: "stale authoring journey revision: expected 15, current 16" },
            { ok: false, status: 409 },
          ),
        );
      }
      return Promise.resolve(notFound(url));
    });
    vi.stubGlobal("fetch", fetchMock);
    await renderAndAcknowledgeAll();

    fireEvent.click(screen.getByRole("button", { name: /确认例外并放行/ }));
    await waitFor(() => expect(screen.getByText(/例外放行未完成/)).toBeTruthy());

    for (const label of MISSING_V15) {
      expect(screen.getByLabelText(label).checked).toBe(true);
    }
    expect(screen.getByLabelText(/例外说明/).value).toBe(OVERRIDE_REASON);
    expect(screen.getByRole("button", { name: /确认例外并放行/ }).disabled).toBe(false);
  });
});
