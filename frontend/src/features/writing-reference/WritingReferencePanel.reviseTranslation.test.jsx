// R26 自检第2次 P0-A 前端反例（红先修后）：
// 现场（proj_user_953921d37b47）：忠实度阻断的译片段上"退回修改"成功落库
// （medical_review_records returned×3），随后"按审核意见重新生成"点击无任何
// 效果——后端DB中无 direct_translation stage run、无新 revision、无 durable
// job、无报错提示。根因是重新生成走分钟级同步 HTTP（无 durable job、无进展、
// 错误蒸发）。修复后前端契约：
// 1) 点击"按审核意见重新生成"发出 POST /references/translations/{id}/revisions
//    （body 携带 expected_translation_revision 与 medical_review_id）；
// 2) 后端受理为 durable 作业（accepted+job_id）→ 前端轮询
//    GET /medical-writing/jobs/{job_id} 直到 completed；
// 3) 作业完成后给出成功提示；作业失败时把 error_summary 作为可见错误抛出。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WritingReferencePanel } from "./WritingReferencePanel";

const PROJECT_ID = "proj_revise_returned_front";
const SNAPSHOT_ID = "wref_snap_revise_front";
const ARTIFACT_ID = "wref_doc_revise_front";
const SPAN_ID = "wref_span_revise_front";
const TRANSLATION_ID = "wref_translation_ch_revise_front";
const REVIEW_ID = "wref_review_returned_front";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

function workspacePayload() {
  return {
    project_id: PROJECT_ID,
    initialized: true,
    snapshot: {
      snapshot_id: SNAPSHOT_ID,
      request: { indication: "Osteoarthritis", phases: ["PHASE2"] },
      candidates: [{ nct_id: "NCT05492500" }],
      api_version: "v2",
      data_timestamp: "2026-10-02",
      returned_count: 1,
      total_count: 1,
    },
    decisions: [
      { nct_id: "NCT05492500", relevance_status: "direct_competitor", revision: 1 },
    ],
    artifacts: [
      {
        artifact_id: ARTIFACT_ID,
        snapshot_id: SNAPSHOT_ID,
        nct_id: "NCT05492500",
        source_document_id: "source_doc_1",
        document_type: "protocol",
        filename: "competitor-protocol.pdf",
        content_sha256: "a".repeat(64),
        source_current: true,
        state_revision: 1,
      },
    ],
    document_validations: [
      {
        artifact_id: ARTIFACT_ID,
        status: "confirmed",
        revision: 1,
        summary: "Current file content was confirmed for testing.",
        checks: [
          { check_code: "study_identifier", label: "研究标识", outcome: "match", observed_value: "NCT05492500" },
        ],
      },
    ],
    artifact_span_counts: { [ARTIFACT_ID]: 1 },
    extraction_reviews: [
      { artifact_id: ARTIFACT_ID, extraction_revision: "extract_r1", decision: "approved", revision: 1 },
    ],
    ocr_consistency_reviews: [],
    translations: [
      {
        translation_id: TRANSLATION_ID,
        project_id: PROJECT_ID,
        span_id: SPAN_ID,
        source_span_revision: `${SPAN_ID}_r1`,
        document_sha256: "a".repeat(64),
        glossary_version: "cms_regulatory_zh_v1",
        revision: 1,
        translated_text: "主要终点在第61周进行评估。",
        fidelity_status: "blocked",
        fidelity_failure_codes: ["numeric_tokens_changed"],
        status: "pending_author_confirmation",
        provider: "composite_pipeline",
        model_name: "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
        contract_hash: "c".repeat(16),
      },
    ],
    medical_reviews: [
      {
        review_id: REVIEW_ID,
        translation_id: TRANSLATION_ID,
        translation_revision: 1,
        decision: "returned",
        revision: 1,
        comment: "请按原文修正评价时间窗后重新生成。",
        decision_type: "author_confirmation",
        admission_status: "not_admitted",
      },
    ],
    approved_evidence_briefs: [],
    evidence_brief_history: [],
  };
}

function spansPayload() {
  return {
    artifact_id: ARTIFACT_ID,
    extraction_revision: "extract_r1",
    total: 1,
    anchor_counts: { objectives_endpoints: 1 },
    items: [
      {
        span_id: SPAN_ID,
        artifact_id: ARTIFACT_ID,
        extraction_revision: "extract_r1",
        physical_page: 12,
        block_index: 3,
        source_locator: `ctgov:NCT05492500:${ARTIFACT_ID}:p12:b3`,
        ich_m11_anchor: "objectives_endpoints",
        source_text: "The primary endpoint is assessed at Week 16.",
      },
    ],
  };
}

function installFetch({ jobStatusSequence = ["completed"], jobError = "" } = {}) {
  let statusIndex = 0;
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.includes("/references/workspace")) {
      return Promise.resolve(jsonResponse(workspacePayload()));
    }
    if (method === "GET" && url.includes(`/references/documents/${ARTIFACT_ID}/spans`)) {
      return Promise.resolve(jsonResponse(spansPayload()));
    }
    if (method === "POST" && url.endsWith(`/references/translations/${TRANSLATION_ID}/revisions`)) {
      return Promise.resolve(jsonResponse({
        accepted: true,
        job_id: "mwjob_revise_front_test",
        job_type: "reference_translation_revise",
        translation_id: TRANSLATION_ID,
        status: "queued",
      }));
    }
    if (method === "GET" && url.endsWith("/medical-writing/jobs/mwjob_revise_front_test")) {
      const status = jobStatusSequence[Math.min(statusIndex, jobStatusSequence.length - 1)];
      statusIndex += 1;
      return Promise.resolve(jsonResponse({ status, error_summary: jobError, progress: null }));
    }
    if (method === "GET" && url.endsWith("/medical-writing/jobs/mwjob_revise_front_test/result")) {
      return Promise.resolve(jsonResponse({ translation_id: TRANSLATION_ID, revision: 2 }));
    }
    if (method === "POST" && url.endsWith("/medical-writing/authoring-journey/corpus-gate/recalculate")) {
      return Promise.resolve(jsonResponse({ project_id: PROJECT_ID, revision: 4 }));
    }
    if (method === "GET" && url.includes("/medical-writing/authoring-journey?allow_missing=true")) {
      return Promise.resolve(jsonResponse({ project_id: PROJECT_ID, revision: 4, available: true }));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

async function renderTranslationsView() {
  const onJourneyChange = vi.fn();
  render(
    <WritingReferencePanel
      projectId={PROJECT_ID}
      variant="authoring"
      snapshotId={SNAPSHOT_ID}
      journey={{ revision: 3, picos_sha256: "b".repeat(64) }}
      onJourneyChange={onJourneyChange}
    />,
  );
  fireEvent.click(await screen.findByRole("tab", { name: "结构与译文确认" }));
  await screen.findByText("The primary endpoint is assessed at Week 16.");
  return { onJourneyChange };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("revise-on-returned-review recovery loop (R26 self-check #2 P0-A)", () => {
  it("sends the revision POST, polls the accepted durable job to completion, and surfaces the result", async () => {
    const { fetchMock } = installFetch();
    await renderTranslationsView();

    const regenerate = await screen.findByRole("button", { name: /按审核意见重新生成/ });
    expect(regenerate.disabled).toBe(false);

    fireEvent.click(regenerate);

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([url, options = {}]) =>
        url.endsWith(`/references/translations/${TRANSLATION_ID}/revisions`)
        && (options.method || "GET").toUpperCase() === "POST");
      expect(calls).toHaveLength(1);
      const body = JSON.parse(calls[0][1].body);
      expect(body.expected_translation_revision).toBe(1);
      expect(body.medical_review_id).toBe(REVIEW_ID);
    });
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/medical-writing/jobs/mwjob_revise_front_test"))).toBe(true);
    }, { timeout: 8000 });
    await waitFor(() => {
      expect(screen.getByText("已按作者退回意见生成新译文版本，仍需重新核对与确认。")).toBeTruthy();
    }, { timeout: 8000 });
  }, 20000);

  it("surfaces the durable job failure instead of failing silently", async () => {
    installFetch({ jobStatusSequence: ["failed"], jobError: "ValueError: 译文管线暂时不可用" });
    await renderTranslationsView();

    fireEvent.click(await screen.findByRole("button", { name: /按审核意见重新生成/ }));

    await waitFor(() => {
      expect(screen.getByText(/操作未完成：.*译文管线暂时不可用/)).toBeTruthy();
    }, { timeout: 8000 });
  }, 20000);
});
