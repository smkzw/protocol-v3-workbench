import { afterEach, describe, expect, it, vi } from "vitest";
import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { webcrypto } from "node:crypto";

import {
  MedicalWritingSynopsisProjectIntake,
  SynopsisRequestTimeoutError,
  cancelSynopsisJob,
  pollSynopsisJob,
  requestJsonWithTimeout,
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
