// R26 自检第3次 P0-A + P1 前端反例（红先修后）：
// 现场（proj_user_3ea77adeef20）：objectives_endpoints 锚 0/5 忠实度通过，
// '确认译文并准入'被禁用、后端 admit_translation 硬拒——正常语料门无作者
// 出路，只能走项目级'确认例外并放行'。修复契约：
// ①(P0-A) 忠实度阻断译文：作者逐项勾选全部忠实度阻断码+填写核对说明后可
//    '确认译文并准入（已核对全部忠实度残留）'——POST medical-review 携带
//    acknowledged_fidelity_failure_codes；
// ②(P1) 同一 span 存在多条 translation（跨批次重跑）时，面板必须选中
//    '当前评审所属'的那条（有当前评审者优先，其次最高revision），否则
//    '按审核意见重新生成'按钮间歇性消失。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WritingReferencePanel } from "./WritingReferencePanel";

const PROJECT_ID = "proj_residual_front";
const SNAPSHOT_ID = "wref_snap_residual_front";
const ARTIFACT_ID = "wref_doc_residual_front";
const SPAN_ID = "wref_span_residual_front";
const T_STALE = "wref_translation_ch_stale_attempt";
const T_CURRENT = "wref_translation_ch_current_attempt";
const REVIEW_RETURNED = "wref_review_returned_current";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

function baseTranslation(overrides) {
  return {
    project_id: PROJECT_ID,
    span_id: SPAN_ID,
    source_span_revision: `${SPAN_ID}_r1`,
    document_sha256: "a".repeat(64),
    glossary_version: "cms_regulatory_zh_v1",
    revision: 1,
    fidelity_status: "blocked",
    fidelity_failure_codes: ["unit_1:numeric_tokens_changed", "source_abbreviation_missing"],
    status: "pending_author_confirmation",
    provider: "composite_pipeline",
    model_name: "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
    contract_hash: "c".repeat(16),
    translated_text: "主要终点在第16周进行评估。",
    ...overrides,
  };
}

function workspacePayload({ translations, medicalReviews }) {
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
    translations,
    medical_reviews: medicalReviews,
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

function installFetch({ translations, medicalReviews, reviewResponse } = {}) {
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.includes("/references/workspace")) {
      return Promise.resolve(jsonResponse(workspacePayload({ translations, medicalReviews })));
    }
    if (method === "GET" && url.includes(`/references/documents/${ARTIFACT_ID}/spans`)) {
      return Promise.resolve(jsonResponse(spansPayload()));
    }
    if (method === "POST" && url.includes("/medical-review")) {
      return Promise.resolve(jsonResponse(reviewResponse || { review_id: "wref_review_new", decision: "approved" }));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

async function renderTranslationsView(options) {
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

describe("fidelity-residual author admission (R26 self-check #3 P0-A)", () => {
  it("lets the author admit a fidelity-blocked translation after acknowledging every failure code", async () => {
    const { fetchMock } = installFetch({
      translations: [baseTranslation({ translation_id: "wref_translation_ch_blocked_front" })],
      medicalReviews: [],
    });
    await renderTranslationsView();

    // 逐项确认全部阻断码的覆盖面板必须出现。
    const codeA = await screen.findByLabelText(/numeric_tokens_changed/);
    const codeB = screen.getByLabelText(/source_abbreviation_missing/);
    const commentBox = screen.getByLabelText(/核对说明|作者核对意见/);
    const admit = screen.getByRole("button", { name: /确认译文并准入（已核对全部忠实度残留）/ });
    expect(admit.disabled).toBe(true);

    fireEvent.click(codeA);
    fireEvent.click(codeB);
    fireEvent.change(commentBox, { target: { value: "已逐项对照原文，数字与缩写残留确认为格式性问题。" } });
    expect(admit.disabled).toBe(false);
    fireEvent.click(admit);

    await waitFor(() => {
      const calls = fetchMock.mock.calls.filter(([url, options = {}]) =>
        url.endsWith("/medical-review") && (options.method || "GET").toUpperCase() === "POST");
      expect(calls).toHaveLength(1);
      const body = JSON.parse(calls[0][1].body);
      expect(body.decision).toBe("approved");
      expect(body.acknowledged_fidelity_failure_codes).toEqual(
        expect.arrayContaining(["unit_1:numeric_tokens_changed", "source_abbreviation_missing"]),
      );
    });
  });
});

describe("duplicate span translations resolve to the reviewed one (R26 self-check #3 P1)", () => {
  it("selects the translation carrying the current review even when a stale attempt sorts first", async () => {
    installFetch({
      // 数组序在前的旧尝试无评审；后一条带当前退回评审。
      translations: [
        baseTranslation({ translation_id: T_STALE, translated_text: "旧批次残句。" }),
        baseTranslation({ translation_id: T_CURRENT, translated_text: "当前批次译文。" }),
      ],
      medicalReviews: [
        {
          review_id: REVIEW_RETURNED,
          translation_id: T_CURRENT,
          translation_revision: 1,
          decision: "returned",
          revision: 1,
          comment: "请按原文微调措辞后重新生成。",
          decision_type: "author_confirmation",
          admission_status: "not_admitted",
        },
      ],
    });
    await renderTranslationsView();

    // 面板必须选中带当前评审的 T_CURRENT：按审核意见重新生成可见可用。
    const regenerate = await screen.findByRole("button", { name: /按审核意见重新生成/ });
    expect(regenerate.disabled).toBe(false);
  });
});
