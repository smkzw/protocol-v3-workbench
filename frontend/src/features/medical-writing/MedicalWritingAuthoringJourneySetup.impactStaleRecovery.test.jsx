// R27 自检20261005 P2-2：变更确认模态的 stale revision 死路（反例先红后绿——
// 修复已并入本批，此测试固化契约）。
// 现场：确认面板反复出现且内嵌『变更未提交：stale authoring journey
// revision: expected 4, current 6』，唯一出路是整页刷新。
// 契约：确认提交遇 409 stale 时，自动拉最新旅程→重算影响预览→需确认则
// 带新数据重开面板（提示已按最新版本重新核验），绝不留死路模态。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { MedicalWritingAuthoringJourneySetup } from "./MedicalWritingAuthoringJourneySetup";

const PROJECT_ID = "proj_impact_stale_test";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

let journeyRevision = 4;
const commitCalls = [];

function installFetch() {
  const fetchMock = vi.fn(async (url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    const target = String(url);
    if (method === "GET" && target.endsWith(`/api/projects/${PROJECT_ID}/medical-writing/authoring-journey`)) {
      return jsonResponse(journeyPayload(journeyRevision));
    }
    if (method === "POST" && target.includes("/impact-preview")) {
      return jsonResponse({
        requires_confirmation: true,
        preview_id: `preview_${commitCalls.length}`,
        affected_dependents: ["protocol_assembly_plan"],
      });
    }
    if (method === "POST" && target.includes("/stages/framing/commit")) {
      commitCalls.push(JSON.parse(options.body || "{}"));
      if (commitCalls.length === 1) {
        // 首次提交：另一并发写已把修订号推高 → 409 stale（现场原文）。
        journeyRevision = 6;
        return jsonResponse(
          { detail: "stale authoring journey revision: expected 4, current 6" },
          { ok: false, status: 409 },
        );
      }
      return jsonResponse(journeyPayload(7));
    }
    if (target.includes("/research-pipeline/status")) {
      return jsonResponse({ pipeline: null });
    }
    if (target.includes("/fact-intake/study_framing")) {
      return jsonResponse({ available: false });
    }
    return jsonResponse({ detail: `not found: ${target}` }, { ok: false, status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

function journeyPayload(revision) {
  const framing = {
    protocol_id: "STALE-001",
    version: "V0.1",
    document_title: "stale恢复验证",
    indication: "慢性咳嗽",
    study_phase: "II",
    investigational_product: "TestDrug",
    design_pattern: "随机、双盲、安慰剂对照",
    population_intent: "慢性咳嗽成人患者",
    intrinsic_objectives: ["概念验证"],
    product_profile: {
      technology_type: "small_molecule", exposure_scope: "systemic",
      dosage_forms: ["片剂"], administration_routes: ["口服"],
    },
    structured_design: { arm_or_cohort_kind: "", arm_or_cohort_labels: [] },
  };
  return {
    project_id: PROJECT_ID,
    revision,
    entry_mode: "guided_greenfield",
    current_stage: "framing",
    framing_complete: false,
    picos_complete: false,
    framing,
    framing_draft: null,
    synopsis_import: { status: "none" },
    corpus_gate: { readiness_status: "not_ready", access_permitted: false, missing_requirements: [], covered_requirements: [], requirements: [], override: { active: false, reason: "", actor: "", recorded_at: null, acknowledged_missing_requirements: [] } },
    search_plan: { plan_id: "plan_stale", registry_filter: {}, latest_snapshot_id: "wref_search_stale" },
    corpus_triage: { status: "", snapshot_id: "", retained_candidate_ids: [] },
    discovery_basket_projection: null,
    study_definition: null,
    prefill_package: null,
  };
}

async function renderAndOpenImpact() {
  render(
    <MedicalWritingAuthoringJourneySetup projectId={PROJECT_ID} projectHeader={{}} />,
  );
  await screen.findByRole("checkbox", { name: /口服/ });
  fireEvent.change(screen.getByLabelText("方案号"), { target: { value: "STALE-002" } });
}

afterEach(() => {
  cleanup();
  vi.unstubsAllGlobals?.();
  vi.unstubAllGlobals();
  commitCalls.length = 0;
  journeyRevision = 4;
});

describe("impact confirm stale-revision recovery (P2-2)", () => {
  it("auto-refreshes the journey and resubmits on 409 stale instead of dead-ending", async () => {
    installFetch();
    render(<MedicalWritingAuthoringJourneySetup projectId={PROJECT_ID} projectHeader={{}} />);
    await screen.findByRole("checkbox", { name: /口服/ });
    fireEvent.change(screen.getByLabelText("方案号"), { target: { value: "STALE-002" } });
    fireEvent.click(screen.getByRole("button", { name: /完成第一步/ }));

    await screen.findByRole("button", { name: "确认变更并重新核验" });
    fireEvent.click(screen.getByRole("button", { name: "确认变更并重新核验" }));

    // 首次409后必须自动重走：拉最新→重算预览→重开确认面板（而非死路报错）。
    await waitFor(() => {
      expect(screen.getByText(/已按最新版本重新核验/)).toBeTruthy();
    }, { timeout: 5000 });
    expect(screen.getByRole("button", { name: "确认变更并重新核验" })).toBeTruthy();
    // 第二次确认（新修订号）应成功提交。
    fireEvent.click(screen.getByRole("button", { name: "确认变更并重新核验" }));
    await waitFor(() => {
      expect(commitCalls.length).toBe(2);
    });
    expect(commitCalls[1].expected_revision).toBe(6);
  });
});
