// 自检第1次红节点④——行"核对译文"→片段区选中失效（20261015 现场复现链）：
// 1) 行锚点是抽取期冻结锚；文档计划可 refine 章节归属。行入口用行锚点过滤
//    片段列表会把目标片段滤空，读取回调再以首条静默覆盖选中——片段区显示
//    错误片段或空。
// 2) 章节级译文按章节首片段 span_id 落库（research_like 除外）；点击同一章
//    非首片段的行时，片段区按 span_id 找不到译文——行核对译文等于不可用。
// 期望：点击批次行后，片段区必须显示该行片段原文 + 该行候选译文
// （按行携带的 translation_id 对准章节候选），且不因锚点过滤丢失选中。
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { WritingReferencePanel } from "./WritingReferencePanel";

beforeAll(() => {
  // jsdom 不实现 scrollIntoView；行入口的定位滚动与本缺陷无关。
  Element.prototype.scrollIntoView = vi.fn();
});

const PROJECT_ID = "proj_row_span_focus_front";
const SNAPSHOT_ID = "wref_snap_row_span_focus";
const BATCH_ID = "wref_translation_batch_focus_front";
const TRANSLATION_ID = "wref_translation_ch_focus_front";
const TRANSLATED_TEXT = "主要终点在第16周评估，按章节整合的监管中文候选译文。";
const SECONDARY_SOURCE = "Secondary endpoint is assessed at Week 24.";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

const SPANS = [
  {
    span_id: "span_focus_primary",
    artifact_id: "artifact_focus_front",
    extraction_revision: "extract_r1",
    ich_m11_anchor: "background",
    physical_page: 12,
    block_index: 1,
    source_text: "Primary endpoint is assessed at Week 16.",
    source_locator: "p12 b1",
    source_fragments: [],
  },
  {
    span_id: "span_focus_secondary",
    artifact_id: "artifact_focus_front",
    extraction_revision: "extract_r1",
    ich_m11_anchor: "background",
    physical_page: 12,
    block_index: 2,
    source_text: SECONDARY_SOURCE,
    source_locator: "p12 b2",
    source_fragments: [],
  },
];

function workspacePayload() {
  return {
    project_id: PROJECT_ID,
    initialized: true,
    snapshot: {
      snapshot_id: SNAPSHOT_ID,
      request: { indication: "慢性心力衰竭", phases: ["PHASE2"] },
      candidates: [
        {
          nct_id: "NCT00000042",
          brief_title: "研究 NCT00000042",
          official_title: "",
          lead_sponsor: "Sponsor",
          phases: ["PHASE2"],
          conditions: ["Chronic Heart Failure"],
          relevance_status: "direct_competitor",
          public_documents: [],
        },
      ],
      api_version: "v2",
      data_timestamp: "2026-10-15",
      returned_count: 1,
      total_count: 1,
    },
    decisions: [],
    artifacts: [
      {
        artifact_id: "artifact_focus_front",
        project_id: PROJECT_ID,
        snapshot_id: SNAPSHOT_ID,
        nct_id: "NCT00000042",
        filename: "protocol.pdf",
        document_type: "protocol",
        content_sha256: "a".repeat(64),
        source_current: true,
      },
    ],
    document_validations: [],
    artifact_span_counts: { artifact_focus_front: 2 },
    ocr_consistency_reviews: [],
    extraction_reviews: [],
    translations: [
      {
        translation_id: TRANSLATION_ID,
        project_id: PROJECT_ID,
        span_id: "span_focus_primary",
        revision: 1,
        status: "candidate_ready",
        glossary_version: "cms_regulatory_zh_v1",
        translated_text: TRANSLATED_TEXT,
        fidelity_status: "passed",
        fidelity_failure_codes: [],
      },
    ],
    medical_reviews: [],
    evidence_brief_history: [],
  };
}

function batchPayload() {
  return {
    batch_id: BATCH_ID,
    project_id: PROJECT_ID,
    snapshot_id: SNAPSHOT_ID,
    glossary_version: "cms_regulatory_zh_v1",
    anchor_filter: ["objectives_endpoints"],
    preparation_batch_id: "prep_focus_front",
    scope_sha256: "scope_focus_front",
    status: "completed",
    attempt: 1,
    counts: { candidate_ready_count: 2, pending_author_confirmation_count: 2 },
    items: [
      {
        item_id: "item_focus_1",
        nct_id: "NCT00000042",
        artifact_id: "artifact_focus_front",
        span_id: "span_focus_primary",
        filename: "protocol.pdf",
        document_type: "protocol",
        ich_m11_anchor: "objectives_endpoints",
        source_locator: "p12 b1",
        origin: "new",
        generation_status: "candidate_ready",
        translation_id: TRANSLATION_ID,
        translation_revision: 1,
        fidelity_status: "passed",
        author_confirmation_status: "not_confirmed",
        admission_status: "not_admitted",
        fidelity_failure_codes: [],
      },
      {
        item_id: "item_focus_2",
        nct_id: "NCT00000042",
        artifact_id: "artifact_focus_front",
        span_id: "span_focus_secondary",
        filename: "protocol.pdf",
        document_type: "protocol",
        ich_m11_anchor: "objectives_endpoints",
        source_locator: "p12 b2",
        origin: "new",
        generation_status: "candidate_ready",
        translation_id: TRANSLATION_ID,
        translation_revision: 1,
        fidelity_status: "passed",
        author_confirmation_status: "not_confirmed",
        admission_status: "not_admitted",
        fidelity_failure_codes: [],
      },
    ],
    exclusions: [],
    created_by: "medical_manager",
    created_at: "2026-10-15T10:00:00+00:00",
    updated_at: "2026-10-15T10:30:00+00:00",
  };
}

function previewPayload() {
  return {
    eligible_count: 2,
    eligible_new_count: 0,
    existing_candidate_count: 2,
    fidelity_blocked_count: 0,
    anchor_filter: ["objectives_endpoints"],
    anchor_summaries: [
      {
        ich_m11_anchor: "objectives_endpoints",
        eligible_new: 0,
        existing_candidate: 2,
        fidelity_blocked: 0,
      },
    ],
    exclusions: [],
    document_exclusion_reason_counts: {},
    span_exclusion_reason_counts: {},
  };
}

function installFetch() {
  const fetchMock = vi.fn(async (url) => {
    const target = String(url);
    if (target.includes("/references/workspace")) {
      return jsonResponse(workspacePayload());
    }
    if (target.includes("/documents/artifact_focus_front/spans")) {
      const anchor = new URL(target, "http://localhost").searchParams.get(
        "ich_m11_anchor",
      );
      const items = anchor
        ? SPANS.filter((span) => span.ich_m11_anchor === anchor)
        : SPANS;
      return jsonResponse({
        artifact_id: "artifact_focus_front",
        extraction_revision: "extract_r1",
        anchor_counts: { background: 2 },
        total: items.length,
        offset: 0,
        limit: 500,
        items,
      });
    }
    if (target.includes("/translation-batches/latest")) {
      return jsonResponse(batchPayload());
    }
    if (target.includes("/translation-batches/preview")) {
      return jsonResponse(previewPayload());
    }
    if (target.includes("/competitor-triage/latest")) {
      return jsonResponse({ detail: "not found" }, { ok: false, status: 404 });
    }
    if (target.includes("/research-pipeline/status")) {
      return jsonResponse({ pipeline: null });
    }
    if (target.includes("/authoring-journey/corpus-gate/recalculate")) {
      return jsonResponse({ status: "not_ready", missing: [] });
    }
    if (target.includes("/authoring-journey?allow_missing=true")) {
      return jsonResponse({ available: false });
    }
    return jsonResponse({ detail: `not found: ${target}` }, { ok: false, status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

const JOURNEY = {
  revision: 3,
  picos_sha256: "",
  framing_complete: true,
  picos_complete: false,
  corpus_triage: { status: "pending", snapshot_id: SNAPSHOT_ID, retained_candidate_ids: [] },
  discovery_basket_projection: null,
};

async function flushMount() {
  for (let round = 0; round < 8; round += 1) {
    await vi.advanceTimersByTimeAsync(0);
  }
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("批次行核对译文必须选中该行片段并显示章节候选（自检红节点④）", () => {
  it("点击非首片段行后片段区显示该行原文与该行候选译文", async () => {
    vi.useFakeTimers();
    installFetch();
    render(
      <WritingReferencePanel
        projectId={PROJECT_ID}
        variant="authoring"
        snapshotId={SNAPSHOT_ID}
        journey={JOURNEY}
      />,
    );
    await flushMount();

    fireEvent.click(screen.getByRole("tab", { name: "结构与译文确认" }));
    await flushMount();

    const rows = screen.getAllByRole("button", { name: /核对译文/ });
    expect(rows.length).toBe(2);
    // 点击第二行（章节非首片段 span_focus_secondary）。
    fireEvent.click(rows[1]);
    await flushMount();

    expect(
      screen.getByText(SECONDARY_SOURCE),
      "片段区必须显示被点击行的原文，而不是锚点过滤后残留的其他片段。",
    ).toBeTruthy();
    expect(
      screen.getByText(TRANSLATED_TEXT),
      "章节级译文按章节首片段落库；点击同章非首片段的行必须仍能对准该候选译文。",
    ).toBeTruthy();
    const selectValues = [...document.querySelectorAll("select")].map((el) => el.value);
    expect(
      selectValues,
      "结构化片段下拉必须选中被点击行的片段。",
    ).toContain("span_focus_secondary");
  });
});
