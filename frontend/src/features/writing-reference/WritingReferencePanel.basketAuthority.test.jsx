// R26 自检第4次（本轮）P0-2：AI分诊确认路径语料准备/翻译无UI通路。
//
// 现场（proj_user_97c9c19afb20）：AI分诊确认（『确认并锁定全部824项』）
// 写入 journey.discovery_basket_projection（PICOS未完成，corpus_triage 保持
// pending）后：
//  - ReferencePreparationBatchPanel/MixedOcrReviewPanel/逐文件问题处理入口
//    只按 triageFinalized（corpus_triage.status==='finalized'，仅人工
//    finalize/PICOS后投影可置）渲染 → AI路径永不可达；
//  - 文档与解析候选列表不过滤保留集（triageFinalized=false 时显示全部
//    候选），点已排除候选的『下载并解析』被后端拒
//    『candidate is not approved for document ingestion』；
//  - 打开结构与译文确认报
//    『translation scope is not ready: start Protocol preparation …』——
//    准备面板不可达导致永远没有批次。
//
// 修复契约（红先修后）：后端 _frozen_scope 已把"锁定快照的已确认
// discovery 投影"作为准备批次权威（Authority path B）；前端必须同一口径：
// basketConfirmed = triageFinalized || (discovery投影已确认且快照一致)。
// 满足 basketConfirmed 即渲染准备批次/OCR复核/逐文件入口，并把文档视图
// 候选限制为保留集（corpus_triage 优先，discovery 投影兜底）。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WritingReferencePanel } from "./WritingReferencePanel";

const PROJECT_ID = "proj_basket_authority_front";
const SNAPSHOT_ID = "wref_snap_basket_authority";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

function candidate(nctId, { relevance = "excluded", withProtocol = false } = {}) {
  return {
    nct_id: nctId,
    brief_title: `研究 ${nctId}`,
    official_title: "",
    lead_sponsor: "Sponsor",
    phases: ["PHASE2"],
    conditions: ["Heart Failure"],
    relevance_status: relevance,
    public_documents: withProtocol
      ? [{
        document_id: `${nctId}_protocol`,
        document_type: "protocol",
        label: `${nctId} Protocol`,
        filename: `${nctId}.pdf`,
        download_url: `https://example.test/${nctId}.pdf`,
      }]
      : [],
  };
}

function installFetch({ aiTriageRunStatus = "confirmed" } = {}) {
  const fetchMock = vi.fn(async (url) => {
    const target = String(url);
    if (target.includes("/references/workspace")) {
      return jsonResponse({
        project_id: PROJECT_ID,
        initialized: true,
        snapshot: {
          snapshot_id: SNAPSHOT_ID,
          request: { indication: "Heart Failure", phases: ["PHASE2"] },
          candidates: [
            candidate("NCT01951625", { relevance: "direct_competitor", withProtocol: true }),
            candidate("NCT03547583", { relevance: "excluded", withProtocol: true }),
          ],
          api_version: "v2",
          data_timestamp: "2026-10-03",
          returned_count: 2,
          total_count: 2,
        },
        decisions: [
          { nct_id: "NCT01951625", relevance_status: "direct_competitor", revision: 1 },
          { nct_id: "NCT03547583", relevance_status: "excluded", revision: 1 },
        ],
        artifacts: [],
        document_validations: [],
        artifact_span_counts: {},
        ocr_consistency_reviews: [],
      });
    }
    if (target.includes("/competitor-triage/latest")) {
      return jsonResponse({
        run: {
          run_id: "ct_run_basket_front",
          snapshot_id: SNAPSHOT_ID,
          status: aiTriageRunStatus,
        },
        summary: { status: aiTriageRunStatus },
      });
    }
    if (target.includes("/research-pipeline/status")) {
      return jsonResponse({ pipeline: null });
    }
    if (target.includes("/preparation-batches/latest")) {
      return notFound(target);
    }
    return notFound(target);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

const JOURNEY_DISCOVERY_CONFIRMED = {
  revision: 8,
  picos_sha256: "",
  corpus_triage: { status: "pending", snapshot_id: SNAPSHOT_ID, retained_candidate_ids: [] },
  discovery_basket_projection: {
    confirmation_id: "ct_conf_basket_front",
    confirmation_hash: "hash_front",
    snapshot_id: SNAPSHOT_ID,
    retained_nct_ids: ["NCT01951625"],
    excluded_nct_ids: ["NCT03547583"],
    run_id: "ct_run_basket_front",
    actor: "medical_manager",
    reason: "确认竞品篮子",
    projected_at: "2026-10-03T00:00:00Z",
  },
};

async function openDocumentsView(journey) {
  render(
    <WritingReferencePanel
      projectId={PROJECT_ID}
      variant="authoring"
      snapshotId={SNAPSHOT_ID}
      journey={journey}
      onJourneyChange={() => {}}
    />,
  );
  fireEvent.click(await screen.findByRole("tab", { name: "文档与解析" }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AI-confirmed discovery basket unlocks preparation UI (R26 self-check #4 P0-2)", () => {
  it("renders the preparation batch panel after AI basket confirm (discovery projection)", async () => {
    installFetch();

    await openDocumentsView(JOURNEY_DISCOVERY_CONFIRMED);

    // 批次面板的启动控件可达（无批次时呈现『开始批量准备』按钮）。
    expect(
      await screen.findByRole("button", { name: /开始批量准备/ }),
    ).toBeTruthy();
  });

  it("limits the documents candidate list to the retained basket scope", async () => {
    installFetch();

    await openDocumentsView(JOURNEY_DISCOVERY_CONFIRMED);

    // 篮子确认后逐文件工具收起在『逐文件问题处理』入口之后，展开后再核对。
    fireEvent.click(await screen.findByRole("button", { name: /逐文件问题处理/ }));
    const select = await screen.findByLabelText(/候选研究/);
    const options = Array.from(select.options || []).map((option) => option.value);
    expect(options).toContain("NCT01951625");
    expect(options).not.toContain("NCT03547583");
  });

  it("keeps the manual finalize gating when no basket authority exists", async () => {
    installFetch();

    await openDocumentsView({
      revision: 8,
      corpus_triage: { status: "pending", snapshot_id: SNAPSHOT_ID, retained_candidate_ids: [] },
      discovery_basket_projection: null,
    });

    // 未确认篮子（corpus_triage 未固化、无 discovery 投影）时准备面板仍不可达。
    expect(screen.queryByRole("button", { name: /开始批量准备/ }))
      .toBeNull();
  });
});
