// 自检r1-4红节点②（2026-10-14，proj_user_c1b741eab57a）：云端退化日分诊
// partial_failed（现场 4/6 批成功、9 项直接/间接已分类），但抽屉只渲染
// review_ready 的批量确认区——成功批分类不可见、篮子恒 0、唯一出路是
// 小时级重试且重试再失败。期望：partial_failed 也呈现批量确认区，未分诊
// 候选预选「排除」并可被医学经理改为保留以外的判断；确认请求携带
// partial_coverage_acknowledgement=true，保留篮只含成功批分类。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WritingReferencePanel } from "./WritingReferencePanel";

const PROJECT_ID = "proj_partial_confirm_front";
const SNAPSHOT_ID = "wref_snap_partial_confirm";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function candidate(nctId) {
  return {
    nct_id: nctId,
    brief_title: `研究 ${nctId}`,
    official_title: "",
    lead_sponsor: "Sponsor",
    phases: ["PHASE2"],
    conditions: ["Chronic Spontaneous Urticaria"],
    relevance_status: "excluded",
    public_documents: [],
  };
}

const TRIAGED = ["NCT00000001", "NCT00000002", "NCT00000003", "NCT00000004", "NCT00000005"];
const UNTRIAGED = ["NCT00000006", "NCT00000007", "NCT00000008", "NCT00000009"];

let confirmBodies = [];

function installFetch() {
  const fetchMock = vi.fn(async (url, options = {}) => {
    const target = String(url);
    if (target.includes("/references/workspace")) {
      return jsonResponse({
        project_id: PROJECT_ID,
        initialized: true,
        snapshot: {
          snapshot_id: SNAPSHOT_ID,
          request: { indication: "CSU", phases: ["PHASE2"] },
          candidates: [...TRIAGED, ...UNTRIAGED].map(candidate),
          api_version: "v2",
          data_timestamp: "2026-10-14",
          returned_count: 9,
          total_count: 9,
        },
        decisions: [],
        artifacts: [],
        document_validations: [],
        artifact_span_counts: {},
        ocr_consistency_reviews: [],
      });
    }
    if (target.includes("/competitor-triage/latest")) {
      return jsonResponse({
        run: {
          run_id: "ct_run_partial_front",
          snapshot_id: SNAPSHOT_ID,
          status: "partial_failed",
          canonical_input_hash: "hash_partial_front",
          chunks: [
            {
              chunk_index: 0,
              status: "succeeded",
              results: TRIAGED.map((nctId, index) => ({
                nct_id: nctId,
                classification: index < 3 ? "direct_competitor" : "indirect_reference",
                confidence: 0.9,
                reason: "同适应症随机双盲安慰剂对照",
                matching_dimensions: [],
                evidence_gaps: [],
              })),
            },
            {
              chunk_index: 1,
              status: "failed",
              results: [],
              error_message: "provider error: timeout",
            },
          ],
        },
        summary: { status: "partial_failed" },
      });
    }
    if (target.includes("/research-pipeline/status")) {
      return jsonResponse({
        pipeline: {
          stage: "failed",
          error_summary: "competitor_triage_partial_failed",
        },
      });
    }
    if (target.includes("/competitor-triage/") && target.endsWith("/confirm")) {
      confirmBodies.push(JSON.parse(options.body || "{}"));
      return jsonResponse({
        confirmation_id: "ct_conf_partial_front",
        projection_status: "discovery_projected",
      });
    }
    return jsonResponse({ detail: `not found: ${target}` }, { ok: false, status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

const JOURNEY = {
  revision: 18,
  picos_sha256: "",
  framing_complete: true,
  picos_complete: false,
  corpus_triage: { status: "pending", snapshot_id: SNAPSHOT_ID, retained_candidate_ids: [] },
  discovery_basket_projection: null,
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  confirmBodies = [];
});

describe("partial_failed分诊呈现成功批分类并允许显式知晓确认（自检r1-4红节点②）", () => {
  it("渲染批量确认区、未分诊预选排除、确认请求携带知晓标记", async () => {
    installFetch();
    render(
      <WritingReferencePanel
        projectId={PROJECT_ID}
        variant="authoring"
        snapshotId={SNAPSHOT_ID}
        journey={JOURNEY}
        onJourneyChange={() => {}}
      />,
    );

    // ① partial_failed 也呈现批量确认区（当前缺陷：仅 review_ready 渲染）。
    expect(await screen.findByText(/批量确认AI分诊建议/)).toBeTruthy();

    // ② 未分诊候选预选「排除」——覆盖完整即可确认。
    const confirmButton = await screen.findByRole("button", { name: /确认锁定|确认并锁定|确认当前/ });
    await waitFor(() => {
      expect(confirmButton.disabled).toBe(false);
    });

    // ③ 确认请求：保留篮只含成功批分类，未分诊全部排除，
    //    且携带 partial_coverage_acknowledgement=true。
    fireEvent.click(confirmButton);
    await waitFor(() => {
      expect(confirmBodies.length).toBe(1);
    });
    const body = confirmBodies[0];
    expect(body.partial_coverage_acknowledgement).toBe(true);
    expect(body.retained_nct_ids.sort()).toEqual([...TRIAGED].sort());
    expect(body.excluded_nct_ids.sort()).toEqual([...UNTRIAGED].sort());
  });
});

import { R21_RUN, R21_CANDIDATE_IDS } from "./__r21Fixture.mjs";

describe("真实r2-1载荷（proj_user_fbfddeb2f6e0，31候选/16分类/15未分诊）复验", () => {
  it("批量确认区按真实载荷呈现，确认请求保留篮=4项成功批分类、15项未分诊排除+知晓标记", async () => {
    const classified = new Set(
      R21_RUN.chunks.filter((chunk) => chunk.status === "succeeded")
        .flatMap((chunk) => chunk.results.map((result) => result.nct_id)),
    );
    const retainedExpected = ["NCT06215911", "NCT0636970", "NCT06215911"].filter(Boolean);
    const fetchMock = vi.fn(async (url, options = {}) => {
      const target = String(url);
      if (target.includes("/references/workspace")) {
        return jsonResponse({
          project_id: "proj_fbfddeb2f6e0",
          initialized: true,
          snapshot: {
            snapshot_id: R21_RUN.snapshot_id,
            request: { indication: "CSU", phases: ["PHASE2"] },
            candidates: R21_CANDIDATE_IDS.map((nctId) => candidate(nctId)),
            api_version: "v2",
            data_timestamp: "2026-10-14",
            returned_count: R21_CANDIDATE_IDS.length,
            total_count: R21_CANDIDATE_IDS.length,
          },
          decisions: [],
          artifacts: [],
          document_validations: [],
          artifact_span_counts: {},
          ocr_consistency_reviews: [],
        });
      }
      if (target.includes("/competitor-triage/latest")) {
        return jsonResponse({ run: R21_RUN, summary: { status: R21_RUN.status } });
      }
      if (target.includes("/research-pipeline/status")) {
        return jsonResponse({
          pipeline: { stage: "failed", error_summary: "competitor_triage_partial_failed" },
        });
      }
      if (target.includes("/competitor-triage/") && target.endsWith("/confirm")) {
        confirmBodies.push(JSON.parse(options.body || "{}"));
        return jsonResponse({
          confirmation_id: "ct_conf_r21_front",
          projection_status: "discovery_projected",
        });
      }
      return jsonResponse({ detail: `not found: ${target}` }, { ok: false, status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <WritingReferencePanel
        projectId="proj_fbfddeb2f6e0"
        variant="authoring"
        snapshotId={R21_RUN.snapshot_id}
        journey={JOURNEY}
        onJourneyChange={() => {}}
      />,
    );

    expect(await screen.findByText(/批量确认AI分诊建议/)).toBeTruthy();
    const confirmButton = await screen.findByRole("button", { name: /确认锁定|确认并锁定|确认当前/ });
    await waitFor(() => {
      expect(confirmButton.disabled).toBe(false);
    });
    fireEvent.click(confirmButton);
    await waitFor(() => {
      expect(confirmBodies.length).toBe(1);
    });
    const body = confirmBodies[0];
    expect(body.partial_coverage_acknowledgement).toBe(true);
    const retained = body.retained_nct_ids.filter((nctId) => classified.has(nctId));
    expect(retained.length).toBe(4);
    expect(body.excluded_nct_ids.length).toBe(27);
  });
});
