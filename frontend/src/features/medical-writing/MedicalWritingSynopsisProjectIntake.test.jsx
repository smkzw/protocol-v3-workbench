import { afterEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { webcrypto } from "node:crypto";

import {
  MedicalWritingSynopsisProjectIntake,
  SynopsisRequestTimeoutError,
  cancelSynopsisJob,
  modelLifecycleSummary,
  pollSynopsisJob,
  requestJsonWithTimeout,
  synopsisAttemptLabel,
  synopsisJobErrorKind,
  synopsisJobMessage,
  synopsisJobState,
} from "./MedicalWritingSynopsisProjectIntake";

const startedJob = {
  intake_id: "mwintake_test",
  idempotency_key: "file-first-synopsis-test",
  status: "chunking",
  phase: "chunking",
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("structured failure guidance (AGG25-P1-1 / ENV-02 修订)", () => {
  // ENV-02 策略变更：前两轮的"报错语义层"修复里，"系统会自动排队并在模型
  // 可用时拉起"是一句假承诺（该任务从未进仲裁器队列，云 fallback 也不受管）。
  // R26 定性后按集成人裁定选 b：撤回承诺、如实说明，等待面板给出真实进度。
  it("maps failure_code model_timeout to busy-model guidance without any queueing promise", () => {
    const job = {
      status: "failed",
      failure_code: "model_timeout",
      error_message: "AiProviderRuntimeError: after bounded retries: TimeoutError",
    };
    expect(synopsisJobErrorKind(job)).toBe("model_timeout");
    const message = synopsisJobMessage(job);
    expect(message).toContain("超时");
    expect(message).toContain("继续处理");
    expect(message).toContain("取消");
    expect(message).not.toContain("自动排队");
    expect(message).not.toContain("未就绪");
  });

  it("maps legacy timeout-only messages to the busy-model guidance", () => {
    const job = {
      status: "failed",
      error_message:
        "chunk 0 AI call failed: AiProviderRuntimeError: AI provider request failed after bounded retries: TimeoutError",
    };
    expect(synopsisJobErrorKind(job)).toBe("model_timeout");
    expect(synopsisJobMessage(job)).not.toContain("自动排队");
  });

  it("keeps offline guidance for refused connections and drops the queueing promise", () => {
    const job = {
      status: "failed",
      failure_code: "local_model_offline",
      error_message: "URLError: connection refused",
    };
    expect(synopsisJobErrorKind(job)).toBe("model_offline");
    const message = synopsisJobMessage(job);
    expect(message).toContain("本地模型服务未就绪");
    expect(message).toContain("继续处理");
    expect(message).not.toContain("自动排队");
    expect(message).not.toContain("已批准列表");
  });

  it("maps failure_code binding_mismatch to rebinding guidance", () => {
    const job = {
      status: "failed",
      failure_code: "binding_mismatch",
      error_message: "binding_base_url_mismatch",
    };
    expect(synopsisJobErrorKind(job)).toBe("binding_mismatch");
    expect(synopsisJobMessage(job)).toContain("AI 设置");
  });

  it("still classifies legacy rows that only have a message", () => {
    const job = {
      status: "failed",
      error_message: "route configuration changed after task start",
    };
    expect(synopsisJobErrorKind(job)).toBe("route_config");
  });
});

describe("honest waiting-panel progress (ENV-02 如实进度)", () => {
  it("labels a retried job with its real attempt number", () => {
    expect(synopsisAttemptLabel({ attempt_count: 1 })).toBe("");
    expect(synopsisAttemptLabel({})).toBe("");
    expect(synopsisAttemptLabel({ attempt_count: 3 })).toBe("第3次解析尝试");
  });

  it("summarises model residency without engineering jargon", () => {
    expect(modelLifecycleSummary(null)).toBe("");
    expect(modelLifecycleSummary({ status: "degraded" })).toBe("");
    expect(modelLifecycleSummary({ status: "ok", arbiter: {} })).toContain("空闲");
    expect(
      modelLifecycleSummary({
        status: "ok",
        arbiter: { current: "mtplx", users: { mtplx: 2 }, queue: [] },
      }),
    ).toContain("2个任务");
    expect(
      modelLifecycleSummary({
        status: "ok",
        arbiter: { current: "mtplx", users: { mtplx: 1 }, queue: [{}] },
      }),
    ).toContain("1项在排队");
  });
});

describe("synopsis intake recovery", () => {
  it("aborts a hung poll request and stops after a bounded failure budget", async () => {
    vi.useFakeTimers();
    const hungFetch = vi.fn((_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => {
        reject(new DOMException("Aborted", "AbortError"));
      }, { once: true });
    }));
    const timedRequest = requestJsonWithTimeout("/hung", {}, {
      timeoutMs: 25,
      fetchImpl: hungFetch,
    });
    const timedAssertion = expect(timedRequest).rejects.toBeInstanceOf(SynopsisRequestTimeoutError);
    await vi.advanceTimersByTimeAsync(25);
    await timedAssertion;

    const request = vi.fn().mockRejectedValue(new SynopsisRequestTimeoutError());
    await expect(pollSynopsisJob(startedJob, {
      request,
      wait: () => Promise.resolve(),
      maxConsecutiveFailures: 3,
    })).rejects.toThrow("后台任务仍会保留");
    expect(request).toHaveBeenCalledTimes(3);
  });

  it("surfaces a backend failed terminal state and preserves its error", async () => {
    const failed = {
      status: "failed",
      phase: "failed",
      error_message: "产品 AI 结构化调用超时",
    };
    const onJob = vi.fn();
    const terminal = await pollSynopsisJob(startedJob, {
      request: vi.fn().mockResolvedValue(failed),
      onJob,
    });

    expect(synopsisJobState(terminal)).toBe("failed");
    expect(synopsisJobMessage(terminal)).toBe("产品 AI 结构化调用超时");
    expect(onJob).toHaveBeenCalledWith(failed);
  });

  it("translates route-policy denials into plain guidance and hides the dead-end resume button", async () => {
    const denied = {
      status: "failed",
      phase: "failed",
      error_message:
        "chunk 0 AI call failed: AI task protocol_synopsis_structuring requires a product-owned approved direct route: base URL must be one of http://127.0.0.1:8002/v1",
    };

    expect(synopsisJobErrorKind(denied)).toBe("route_config");
    expect(synopsisJobMessage(denied)).toContain("重新选择文件重新导入");
    expect(synopsisJobMessage(denied)).not.toContain("approved direct route");

    vi.stubGlobal("crypto", webcrypto);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...startedJob, ...denied }),
    }));
    const { container } = render(
      <StrictMode><MedicalWritingSynopsisProjectIntake /></StrictMode>,
    );
    const file = new File(["source"], "synopsis.docx");
    file.arrayBuffer = async () => new Uint8Array([1, 2, 3]).buffer;
    fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "导入并提取" }));

    expect((await screen.findByRole("alert")).textContent).toContain("重新选择文件重新导入");
    expect(screen.queryByRole("button", { name: "继续处理" })).toBeNull();
    expect(screen.getByRole("button", { name: /重新选择/ })).toBeTruthy();
  });

  it("keeps the resume button for transient failures without route-policy markers", async () => {
    const transient = {
      status: "failed",
      phase: "failed",
      error_message: "产品 AI 结构化调用超时",
    };

    expect(synopsisJobErrorKind(transient)).toBe("");

    vi.stubGlobal("crypto", webcrypto);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...startedJob, ...transient }),
    }));
    const { container } = render(
      <StrictMode><MedicalWritingSynopsisProjectIntake /></StrictMode>,
    );
    const file = new File(["source"], "synopsis.docx");
    file.arrayBuffer = async () => new Uint8Array([1, 2, 3]).buffer;
    fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "导入并提取" }));

    const alertBox = await screen.findByRole("alert");
    expect(alertBox).toBeTruthy();
    expect(screen.getByRole("button", { name: "继续处理" })).toBeTruthy();
  });

  it("aborts polling before issuing an independent cancel command", async () => {
    const order = [];
    const cancelled = { status: "cancelled", cancellation_state: "cancelled" };
    const result = await cancelSynopsisJob(startedJob, {
      abortPolling: () => order.push("abort-poll"),
      request: vi.fn().mockImplementation(async (_url, options) => {
        order.push(`cancel-${options.method}`);
        return cancelled;
      }),
    });

    expect(order).toEqual(["abort-poll", "cancel-POST"]);
    expect(result).toEqual(cancelled);
    expect(synopsisJobMessage(result)).toContain("已取消");
  });

  it("treats a same-hash reused failed job as resumable without polling", async () => {
    const replay = {
      ...startedJob,
      status: "reused",
      phase: "failed",
    };
    const request = vi.fn();
    const terminal = await pollSynopsisJob(replay, { request });

    expect(request).not.toHaveBeenCalled();
    expect(synopsisJobState(terminal)).toBe("failed");
    expect(synopsisJobMessage(terminal)).toContain("继续处理");
  });
});

it("settles a failed import after StrictMode replays the mount effect", async () => {
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ ...startedJob, status: "failed", phase: "failed",
      error_message: "资料提取失败，原文件已保留" }),
  }));
  const { container } = render(<StrictMode><MedicalWritingSynopsisProjectIntake /></StrictMode>);
  const file = new File(["source"], "synopsis.docx");
  file.arrayBuffer = async () => new Uint8Array([1, 2, 3]).buffer;
  fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "导入并提取" }));
  expect((await screen.findByRole("alert")).textContent).toContain("资料提取失败");
  expect(screen.getByRole("button", { name: "继续处理" }).disabled).toBe(false);
  expect(container.querySelector(".file-first-progress")).toBeNull();
});

describe("refresh-proof job restore (NEW-5) + queue feedback (NEW-11)", () => {
  const STORAGE_KEY = "workbench.synopsisIntake.activeJob";
  const JOB_URL = "/api/medical-writing/project-intake/synopsis/mwintake_restore/jobs/file-first-synopsis-restore";

  afterEach(() => {
    globalThis.sessionStorage.clear();
  });

  const activeJob = () => ({
    job_id: "mwjob_restore",
    status: "ai_synthesis",
    phase: "ai_synthesis",
    chunk_index: 1,
    chunk_total: 3,
    provider_status: "queued",
    waiting_on: "model_wait",
    elapsed_seconds: 120,
    attempt_count: 1,
  });

  const extractedResult = () => ({
    source: {
      source_id: "mwsource_restore",
      original_filename: "refresh.docx",
      content_sha256: "abc123",
      validation_warnings: [],
    },
    proposed_framing: {
      investigational_product: "恢复测试药",
      indication: "恢复测试适应症",
      study_phase: "II期",
    },
    proposed_picos: {},
    proposed_synopsis_text: "这是恢复出的方案摘要文本。",
  });

  it("restores an in-flight job after refresh: waiting panel returns and names the model wait", async () => {
    globalThis.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ intake_id: "mwintake_restore", idempotency_key: "file-first-synopsis-restore" }),
    );
    let jobCalls = 0;
    const fetchMock = vi.fn((url, options = {}) => {
      if (String(url).endsWith("/jobs/file-first-synopsis-restore")) {
        jobCalls += 1;
        // 第一次恢复查询给出排队中的活跃任务；随后挂起，保持等待面板可见。
        if (jobCalls === 1) {
          return Promise.resolve({ ok: true, status: 200, json: async () => activeJob() });
        }
        return new Promise(() => {});
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: "not found" }) });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MedicalWritingSynopsisProjectIntake />);

    // 恢复提示出现，等待面板不再回默认空态
    await screen.findByText(/已恢复上次的提取任务/);
    // NEW-11：排队期点名模型等待，而不是只显示「AI正在提取」黑等
    expect(await screen.findByText(/模型处理中或排队等待空位/)).toBeTruthy();
    expect(screen.getByText(/2 \/ 3 个内容块/)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url) === JOB_URL)).toBe(true);
  });

  it("restores a finished review_ready job directly to the confirmation view", async () => {
    globalThis.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ intake_id: "mwintake_restore", idempotency_key: "file-first-synopsis-restore" }),
    );
    const fetchMock = vi.fn((url) => {
      if (String(url).endsWith("/jobs/file-first-synopsis-restore")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ...activeJob(), status: "review_ready", phase: "review_ready", result_ref: "file-first-synopsis-restore" }),
        });
      }
      if (String(url).endsWith("/result")) {
        return Promise.resolve({ ok: true, status: 200, json: async () => extractedResult() });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: "not found" }) });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MedicalWritingSynopsisProjectIntake />);

    // 刷新后直接回到确认视图，不再要求重传同一文件（NEW-5 现场）
    expect(await screen.findByText("AI 已提取 · 一次确认")).toBeTruthy();
  });

  it("clears the stored fingerprint and stays on the default view when the job is gone", async () => {
    globalThis.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ intake_id: "mwintake_restore", idempotency_key: "file-first-synopsis-restore" }),
    );
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "synopsis import job not found" }),
    }));

    render(<MedicalWritingSynopsisProjectIntake />);

    await waitFor(() => expect(globalThis.sessionStorage.getItem(STORAGE_KEY)).toBeNull());
    // 未选文件时的默认视图文案（导入按钮只在选中文件后出现）
    expect(screen.getByText(/选择方案摘要或完整方案/)).toBeTruthy();
    expect(screen.queryByText(/已恢复上次的提取任务/)).toBeNull();
  });

  // NEW-8（R27 第1轮末修订）：AI 提取的分期不在下拉选项内时，旧行为是
  // select 显示「请选择」而 state 非空 → canConfirm 放行 → 合同层收到
  // 'MW-PHASE' 原料。修复：可映射的写法（Ⅲ期/三期/２期）自动映射进选项；
  // 不可映射的显式标「分期待确认」并阻断确认。
  it("NEW-8: maps the AI-extracted Ⅲ期 into the III期 option so confirmation carries a real phase", async () => {
    globalThis.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ intake_id: "mwintake_restore", idempotency_key: "file-first-synopsis-restore" }),
    );
    vi.stubGlobal("fetch", vi.fn((url) => {
      if (String(url).endsWith("/jobs/file-first-synopsis-restore")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ...activeJob(), status: "review_ready", phase: "review_ready", result_ref: "file-first-synopsis-restore" }),
        });
      }
      if (String(url).endsWith("/result")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            ...extractedResult(),
            proposed_framing: { ...extractedResult().proposed_framing, study_phase: "Ⅲ期" },
          }),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: "not found" }) });
    }));

    render(<MedicalWritingSynopsisProjectIntake />);

    await screen.findByText("AI 已提取 · 一次确认");
    const select = screen.getByLabelText(/研究分期/);
    expect(select.value).toBe("III期");
    expect(screen.queryByText(/分期待确认/)).toBeNull();
    expect(screen.getByRole("button", { name: /确认并进入写作/ }).disabled).toBe(false);
  });

  it("NEW-8: marks an unmappable AI phase as 待确认 and blocks confirmation", async () => {
    globalThis.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ intake_id: "mwintake_restore", idempotency_key: "file-first-synopsis-restore" }),
    );
    vi.stubGlobal("fetch", vi.fn((url) => {
      if (String(url).endsWith("/jobs/file-first-synopsis-restore")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ ...activeJob(), status: "review_ready", phase: "review_ready", result_ref: "file-first-synopsis-restore" }),
        });
      }
      if (String(url).endsWith("/result")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            ...extractedResult(),
            proposed_framing: { ...extractedResult().proposed_framing, study_phase: "探索性研究" },
          }),
        });
      }
      return Promise.resolve({ ok: false, status: 404, json: async () => ({ detail: "not found" }) });
    }));

    render(<MedicalWritingSynopsisProjectIntake />);

    await screen.findByText("AI 已提取 · 一次确认");
    expect(await screen.findByText(/分期待确认/)).toBeTruthy();
    const select = screen.getByLabelText(/研究分期/);
    expect(select.value).toBe("");
    expect(screen.getByRole("button", { name: /确认并进入写作/ }).disabled).toBe(true);
  });
});


describe("NEW-30: file input truly clears on 重新选择", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    globalThis.sessionStorage.clear();
  });

  it("remounts the file input so the previously chosen file is gone", async () => {
    vi.stubGlobal("crypto", webcrypto);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...startedJob,
        status: "failed",
        phase: "failed",
        error_message: "产品 AI 结构化调用超时",
      }),
    }));
    const { container } = render(<MedicalWritingSynopsisProjectIntake />);
    const input = container.querySelector('input[type="file"]');
    const file = new File(["source"], "same-name.docx");
    file.arrayBuffer = async () => new Uint8Array([1, 2, 3]).buffer;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "导入并提取" }));

    expect((await screen.findByRole("alert")).textContent).toContain("重新选择");
    fireEvent.click(screen.getByRole("button", { name: /重新选择/ }));

    // NEW-30 现场：视觉清空但控件仍挂同一份 docx——重挂后必须真清空。
    const inputAfter = container.querySelector('input[type="file"]');
    expect(inputAfter.files.length).toBe(0);
    expect(inputAfter.value).toBe("");
  });
});
