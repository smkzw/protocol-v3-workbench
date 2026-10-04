// R26 自检第4次（本轮）P2-5：『确认变更并重新核验』下游失效模态被抽屉遮盖。
//
// 现场（proj_user_97c9c19afb20）：完成第一步/第二步触发下游失效确认
// （impact panel）后，竞品处理抽屉（AuthoringCompetitorDrawer 覆盖层）
// 仍保持打开，遮盖确认面板——点击落点被抽屉拦截，无任何反馈静默无效；
// 且面板不滚动到可见位置，用户找不到唯一出路（footer 在 impact 打开时
// 隐藏，确认面板是唯一提交路径）。
//
// 修后契约：impact 确认面板出现时（含排队后自动重开），竞品抽屉必须
// 自动关闭并把面板滚动到可见位置——确认路径永远不被覆盖、不静默。
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
    protocol_id: "MW-IMPACT-001",
    version: "V0.1",
    document_title: "TestSgc治疗慢性心力衰竭的II期临床研究方案",
    indication: "慢性心力衰竭",
    study_phase: "II",
    investigational_product: "TestSgc",
    design_pattern: "随机、双盲、安慰剂对照",
    population_intent: "慢性心力衰竭成人患者",
    intrinsic_objectives: ["概念验证"],
    product_profile: {
      technology_type: "小分子",
      exposure_scope: "unknown",
      dosage_forms: ["片剂"],
      administration_routes: ["口服"],
    },
    structured_design: {
      arm_or_coort_kind: "",
      arm_or_cohort_kind: "arm",
      arm_or_cohort_labels: ["试验组", "安慰剂组"],
    },
  };
  return {
    project_id: "proj_impact_visibility_test",
    revision: 3,
    entry_mode: "guided_greenfield",
    current_stage: "framing",
    framing_complete: false,
    picos_complete: false,
    framing,
    framing_draft: null,
    synopsis_import: { status: "none" },
    corpus_gate: {
      readiness_status: "not_ready",
      access_permitted: false,
      missing_requirements: [],
      covered_requirements: [],
      requirements: [],
      override: { active: false, reason: "", actor: "", recorded_at: null, acknowledged_missing_requirements: [] },
    },
    search_plan: {
      plan_id: "plan_impact_visibility",
      registry_filter: {},
      latest_snapshot_id: "wref_search_impact_visibility",
    },
    corpus_triage: { status: "", snapshot_id: "", retained_candidate_ids: [] },
    discovery_basket_projection: null,
    study_definition: null,
    prefill_package: null,
  };
}

export function installFetch({ requiresConfirmation = true } = {}) {
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
      return Promise.resolve(jsonResponse(journeyPayload()));
    }
    if (method === "GET" && url.endsWith("/medical-writing/research-pipeline/status")) {
      return Promise.resolve(jsonResponse({ pipeline: null }));
    }
    if (method === "GET" && url.includes("/fact-intake/study_framing")) {
      return Promise.resolve(jsonResponse({ available: false }));
    }
    if (method === "POST" && url.includes("/impact-preview")) {
      return Promise.resolve(jsonResponse({
        requires_confirmation: requiresConfirmation,
        preview_id: "preview_impact_001",
        affected_dependents: ["protocol_assembly_plan"],
      }));
    }
    if (method === "GET" && url.includes("/references/workspace")) {
      return Promise.resolve(jsonResponse({
        project_id: "proj_impact_visibility_test",
        initialized: true,
        snapshot: {
          snapshot_id: "wref_search_impact_visibility",
          request: {},
          candidates: [],
          api_version: "v2",
          data_timestamp: "2026-10-03",
          returned_count: 0,
          total_count: 0,
        },
        decisions: [],
        artifacts: [],
        document_validations: [],
        artifact_span_counts: {},
        ocr_consistency_reviews: [],
      }));
    }
    if (url.includes("/competitor-triage/latest")) {
      return Promise.resolve(notFound(url));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

export async function renderSetup() {
  render(
    <MedicalWritingAuthoringJourneySetup
      projectId="proj_impact_visibility_test"
      projectHeader={{}}
    />,
  );
  await screen.findByRole("checkbox", { name: /口服/ });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("impact confirmation visibility (R26 self-check #4 P2-5)", () => {
  it("closes the competitor drawer and reveals the confirmation when impact opens", async () => {
    installFetch();
    await renderSetup();

    // 打开竞品抽屉（现场：填写期间查看竞品资料很常见）。
    fireEvent.click(await screen.findByTestId("open-competitor-drawer"));
    const drawerHost = await waitFor(() => {
      const host = document.querySelector(".authoring-competitor-drawer-host");
      expect(host?.dataset.open).toBe("true");
      return host;
    });

    // 制造脏框架并提交，触发下游失效确认面板。
    fireEvent.change(screen.getByLabelText("方案号"), { target: { value: "MW-IMPACT-002" } });
    fireEvent.click(screen.getByRole("button", { name: /完成第一步/ }));

    const confirmButton = await screen.findByRole("button", { name: "确认变更并重新核验" });
    expect(confirmButton).toBeTruthy();

    // 抽屉必须已自动关闭——确认面板不得被覆盖、点击不得静默无效。
    await waitFor(() => {
      expect(drawerHost.dataset.open).toBe("false");
    });

    // 面板滚动到可见位置（不是只渲染在视口之外）。
    const panel = document.querySelector(".authoring-impact-panel");
    expect(panel).toBeTruthy();
    await waitFor(() => {
      expect(panel.getAttribute("data-revealed")).toBe("true");
    });
  });
});
