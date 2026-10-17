// 自检第1次红节点④前端两缺陷（20261015，现场 proj_user_333afc0399e6）：
// ①一键确认请求无超时：服务端挂起时 fetch 永不 settle，action 永久停留
//   "确认中"、全部按钮死锁、零用户可见报错（现场30s静默挂起实据）。
//   期望：POST 超时后必须给出受控人话报错（errorContract 超时文案），
//   按钮退出忙碌态可重试。
// ②行"核对译文"按钮只回传 artifact/span/anchor：章节级译文按章节首片段
//   span_id 落库，片段区按 span_id 找不到该行候选。期望：行点击必须把
//   translation_id/translation_revision 一并交给片段区。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ReferenceTranslationBatchPanel } from "./ReferenceTranslationBatchPanel";

const PROJECT_ID = "proj_cancel_actions_front";
const SNAPSHOT_ID = "wref_snap_cancel_actions";
const BATCH_ID = "wref_translation_batch_cancel_front";
const TRANSLATION_ID = "wref_translation_ch_cancel_front";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function batchPayload() {
  return {
    batch_id: BATCH_ID,
    project_id: PROJECT_ID,
    snapshot_id: SNAPSHOT_ID,
    glossary_version: "cms_regulatory_zh_v1",
    anchor_filter: ["objectives_endpoints"],
    preparation_batch_id: "prep_front",
    scope_sha256: "scope_front",
    status: "completed",
    attempt: 1,
    counts: {
      candidate_ready_count: 1,
      pending_author_confirmation_count: 1,
    },
    items: [
      {
        item_id: "item_front_1",
        nct_id: "NCT00000042",
        artifact_id: "artifact_front_1",
        span_id: "span_front_1",
        filename: "protocol.pdf",
        document_type: "protocol",
        ich_m11_anchor: "objectives_endpoints",
        source_locator: "p14 b2",
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
    eligible_count: 1,
    eligible_new_count: 0,
    existing_candidate_count: 1,
    fidelity_blocked_count: 0,
    anchor_filter: ["objectives_endpoints"],
    anchor_summaries: [
      {
        ich_m11_anchor: "objectives_endpoints",
        eligible_new: 0,
        existing_candidate: 1,
        fidelity_blocked: 0,
      },
    ],
    exclusions: [],
    document_exclusion_reason_counts: {},
    span_exclusion_reason_counts: {},
  };
}

function installFetch({ reviewBehavior } = {}) {
  const fetchMock = vi.fn(async (url, options = {}) => {
    const target = String(url);
    if (target.includes("/translation-batches/latest")) {
      return jsonResponse(batchPayload());
    }
    if (target.includes("/translation-batches/preview")) {
      return jsonResponse(previewPayload());
    }
    if (target.includes("/medical-review")) {
      return reviewBehavior(options);
    }
    return jsonResponse({ detail: `not found: ${target}` }, { ok: false, status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock };
}

async function flushMount() {
  // 挂载后的 loadLatest/loadPreview/setTimeout(0) 全部走假定时器。
  for (let round = 0; round < 5; round += 1) {
    await vi.advanceTimersByTimeAsync(0);
  }
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("一键确认请求超时必须有用户可见反馈（自检红节点④）", () => {
  it("服务端35秒不响应时展示受控超时文案并退出忙碌态", async () => {
    vi.useFakeTimers();
    installFetch({
      // 永不返回的服务端（现场挂起同型）：真实 fetch 在 signal 中止时会以
      // AbortError 拒绝，stub 必须同型——挂起 + 尊重 abort。
      reviewBehavior: (options) => new Promise((_, reject) => {
        options?.signal?.addEventListener("abort", () => {
          const abortError = new Error("The operation was aborted.");
          abortError.name = "AbortError";
          reject(abortError);
        });
      }),
    });
    render(
      <ReferenceTranslationBatchPanel
        projectId={PROJECT_ID}
        snapshotId={SNAPSHOT_ID}
      />,
    );
    await flushMount();

    const button = screen.getByRole("button", { name: /一键确认合格候选/ });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(screen.getByRole("button", { name: /确认中/ })).toBeTruthy();

    // 服务端一直不响应：35秒后客户端必须自行中止并给出报错。
    await vi.advanceTimersByTimeAsync(35000);

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("超时");
    expect(
      screen.getByRole("button", { name: /一键确认合格候选/ }).textContent,
    ).not.toContain("确认中");
  });
});

describe("行核对译文必须携带章节译文上下文（自检红节点④）", () => {
  it("onOpenSpan 收到 translation_id 与 translation_revision", async () => {
    vi.useFakeTimers();
    installFetch({});
    const onOpenSpan = vi.fn();
    render(
      <ReferenceTranslationBatchPanel
        projectId={PROJECT_ID}
        snapshotId={SNAPSHOT_ID}
        onOpenSpan={onOpenSpan}
      />,
    );
    await flushMount();

    fireEvent.click(screen.getByRole("button", { name: /核对译文/ }));

    expect(onOpenSpan).toHaveBeenCalledTimes(1);
    const payload = onOpenSpan.mock.calls[0][0];
    expect(payload.span_id).toBe("span_front_1");
    expect(payload.translation_id).toBe(
      TRANSLATION_ID,
      "行点击必须携带该行候选的 translation_id，否则章节级译文在片段区无法定位。",
    );
    expect(payload.translation_revision).toBe(1);
  });
});
