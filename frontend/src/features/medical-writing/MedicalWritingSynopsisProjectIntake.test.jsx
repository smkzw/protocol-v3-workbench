import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SynopsisRequestTimeoutError,
  cancelSynopsisJob,
  pollSynopsisJob,
  requestJsonWithTimeout,
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
