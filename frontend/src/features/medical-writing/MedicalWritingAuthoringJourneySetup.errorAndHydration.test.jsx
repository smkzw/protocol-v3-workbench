// NEW-6（R27 第2轮修订）反例：客户端替换层把用户已填的结构化字段回滚。
//
// 现场（r2-A 截图44→87、88/89；grok 18/19）：给药途径「口服」勾选并保存后、
// 三臂名单填后，任何一个异步响应（草稿保存回包/调研写回）带回来的载荷缺
// product_profile / structured_design 等结构化子对象时，applyJourneyResponse
// 无条件整替 setFraming/setPicos —— 已填内容被清空，textarea 存活只因
// factConversation 是独立 state。期望：
// 1) 响应缺该 stage 载荷（无 framing/framing_draft.framing）→ 保留当前值，
//    绝不 setFraming(null)；
// 2) 脏状态下（用户有未保存修改）覆写改为逐键合并且空值不清空本地已填。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  MedicalWritingAuthoringJourneySetup,
  blockerJumpDestination,
  normalizeWorkbenchError,
} from "./MedicalWritingAuthoringJourneySetup";

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return { ok, status, json: async () => body };
}

function notFound(url) {
  return jsonResponse({ detail: `not found: ${url}` }, { ok: false, status: 404 });
}

function journeyPayload({ framing } = {}) {
  const baseFraming = {
    protocol_id: "",
    version: "",
    document_title: "",
    indication: "",
    study_phase: "",
    investigational_product: "",
    design_pattern: "",
    population_intent: "",
    intrinsic_objectives: [],
    product_profile: {
      technology_type: "unknown",
      exposure_scope: "unknown",
      dosage_forms: [],
      administration_routes: [],
    },
    structured_design: {
      arm_or_cohort_kind: "",
      arm_or_cohort_labels: [],
    },
  };
  const effective = framing === undefined ? baseFraming : framing;
  return {
    project_id: "proj_hydration_test",
    revision: 3,
    entry_mode: "guided_greenfield",
    current_stage: "framing",
    framing_complete: false,
    picos_complete: false,
    framing: effective,
    framing_draft: {
      stage: "framing",
      framing: effective,
      missing_required_fields: ["protocol_id"],
      saved_from_revision: 2,
      saved_at: "2026-09-29T03:00:00Z",
      saved_by: "medical_manager",
    },
    synopsis_import: { status: "confirmed" },
    corpus_gate: {
      readiness_status: "not_ready",
      access_permitted: false,
      missing_requirements: [],
      covered_requirements: [],
      requirements: [],
      override: { active: false, reason: "", actor: "", recorded_at: null, acknowledged_missing_requirements: [] },
    },
    search_plan: null,
    corpus_triage: { status: "", snapshot_id: "", retained_candidate_ids: [] },
    study_definition: null,
    prefill_package: null,
  };
}

function installFetch({ savedJourney } = {}) {
  const draftBodies = [];
  const fetchMock = vi.fn((url, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method === "GET" && url.endsWith("/medical-writing/authoring-journey")) {
      return Promise.resolve(jsonResponse(journeyPayload()));
    }
    if (method === "GET" && url.includes("/fact-intake/study_framing")) {
      return Promise.resolve(jsonResponse({ available: false }));
    }
    if (method === "POST" && url.includes("/stages/framing/draft")) {
      try { draftBodies.push(JSON.parse(options.body || "{}")); } catch { draftBodies.push({}); }
      return Promise.resolve(jsonResponse(savedJourney || journeyPayload()));
    }
    return Promise.resolve(notFound(url));
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, draftBodies };
}

async function renderOnFramingStage() {
  render(<MedicalWritingAuthoringJourneySetup projectId="proj_hydration_test" projectHeader={{}} />);
  await screen.findByRole("checkbox", { name: /口服/ });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("hydration preserves structured fields (NEW-6)", () => {
  it("keeps the checked administration route when the draft-save response omits product_profile", async () => {
    const saved = journeyPayload();
    delete saved.framing.product_profile;
    saved.framing_draft.framing = saved.framing;
    const { draftBodies } = installFetch({ savedJourney: saved });
    await renderOnFramingStage();

    const route = screen.getByRole("checkbox", { name: /口服/ });
    fireEvent.click(route);
    expect(route.checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));

    await waitFor(() => expect(draftBodies.length).toBe(1));
    await waitFor(() => expect(screen.getByText(/草稿已保存/)).toBeTruthy());
    // r2-A 现场：回包缺 product_profile → 勾选被清空。修后必须保留。
    expect(route.checked).toBe(true);
  });

  it("keeps the filled protocol id and arm labels when the response carries no framing payload at all", async () => {
    const saved = journeyPayload();
    delete saved.framing;
    delete saved.framing_draft;
    const { draftBodies } = installFetch({ savedJourney: saved });
    await renderOnFramingStage();

    fireEvent.change(screen.getByLabelText("方案号"), { target: { value: "MW-HYD-001" } });
    fireEvent.click(screen.getByRole("button", { name: /保存草稿/ }));

    await waitFor(() => expect(draftBodies.length).toBe(1));
    await waitFor(() => expect(screen.getByText(/草稿已保存/)).toBeTruthy());
    // 响应不含 framing 载荷：当前值必须原样保留，绝不回空/崩溃。
    expect(screen.getByLabelText("方案号").value).toBe("MW-HYD-001");
  });
});

describe("error normalization (NEW-12a / NEW-1(4))", () => {
  it("translates assembly blockers into Chinese field labels with jump destinations", () => {
    const normalized = normalizeWorkbenchError(
      "protocol assembly plan still has unresolved scientific design blockers: "
      + "intervention.active_comparator_regimen, intervention.placebo_regimen, "
      + "design.phase1.sad, product.route",
    );
    expect(normalized.title).toContain("方案装配仍有未决设计事实");
    expect(normalized.title).not.toMatch(/[A-Za-z]{4,}/);
    const labels = normalized.items.map((item) => item.label);
    expect(labels).toContain("活动对照的具体方案");
    expect(labels).toContain("安慰剂给药方案");
    expect(labels).toContain("给药途径");
    expect(normalized.items.every((item) => item.fieldPath)).toBe(true);
    expect(normalized.technical).toBe(false);

    const jump = blockerJumpDestination("intervention.placebo_regimen");
    expect(jump).toEqual({ stage: "picos", group: "intervention" });
    expect(blockerJumpDestination("design.phase1.sad")).toEqual({ stage: "picos", group: "applicability" });
    expect(blockerJumpDestination("product.route")).toEqual({ stage: "framing", group: "identity" });
  });

  it("translates the immutable search snapshot conflict", () => {
    const normalized = normalizeWorkbenchError(
      "the current competitor search plan already has an immutable search snapshot",
    );
    expect(normalized.title).toContain("该检索计划已锁定快照");
    expect(normalized.title).toContain("刷新");
    expect(normalized.items).toEqual([]);
  });

  it("translates managed local model unavailability (ensure/triage) into busy-model guidance", () => {
    const normalized = normalizeWorkbenchError(
      "Managed local model server unavailable: ensure(triage) failed on mtplx; queued dispatch aborted",
    );
    expect(normalized.title).toContain("本地模型服务");
    expect(normalized.title).toContain("稍候重试");
    expect(normalized.technical).toBe(true);
  });

  it("translates AI execution policy denial into actionable Chinese without dumping endpoints", () => {
    const normalized = normalizeWorkbenchError(
      "AI task medical_writing_revision requires a product-owned approved direct route: "
      + "provider must be one of alibaba_token_plan, cms-router, deepseek, mtplx, opencode-go; "
      + "allowed routes: mtplx via openai_compatible at http://127.0.0.1:8002/v1 using mtplx-flash-next-optimized-speed; "
      + "opencode-go via openai_compatible at https://opencode.ai/zen/go/v1 using deepseek-v4.1-flash",
    );
    expect(normalized.title).toContain("修订通道");
    expect(normalized.title).toContain("路由白名单");
    expect(normalized.technical).toBe(true);
  });

  it("translates bounded-retries provider failures into busy-model guidance", () => {
    const normalized = normalizeWorkbenchError(
      "AI provider request failed after bounded retries: TimeoutError",
    );
    expect(normalized.title).toContain("模型服务繁忙或响应超时");
    expect(normalized.title).toContain("稍候重试");
    expect(normalized.technical).toBe(true);
  });

  it("keeps raw provider enum dumps folded as technical detail", () => {
    const normalized = normalizeWorkbenchError(
      "provider must be one of opencode-go, cms-router",
    );
    expect(normalized.technical).toBe(true);
  });

  it("NEW-42: explains disabled stage-strip buttons and always shows missing framing fields", async () => {
    installFetch();
    await renderOnFramingStage();

    // 02 PICOS 设计在第一步未完成时禁用，但必须说明原因（grok：全灰零说明）
    const picosStrip = screen.getByRole("button", { name: /PICOS设计/ });
    expect(picosStrip.disabled).toBe(true);
    expect((picosStrip.getAttribute("title") || "").length).toBeGreaterThan(0);

    // 已填但缺项时，缺项清单在按钮旁常显（不只藏在 title 里）
    fireEvent.click(screen.getByRole("tab", { name: "总体设计" }));
    await new Promise((r) => setTimeout(r, 200));
    const design = screen.getByLabelText(/总体设计模式/);
    fireEvent.change(design, { target: { value: "随机、双盲、安慰剂对照、平行组" } });
    const commit = screen.getByRole("button", { name: /完成第一步/ });
    expect(commit.disabled).toBe(true);
    expect(commit.title).toContain("请先补齐第一步必填项");
  });

  it("keeps unknown messages readable and flags them as technical", () => {
    const normalized = normalizeWorkbenchError("some never seen provider error xyz");
    expect(normalized.title).toBe("some never seen provider error xyz");
    expect(normalized.technical).toBe(true);
  });
});
