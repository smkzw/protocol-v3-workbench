/**
 * useDurableMwJob — production React hook + shared poller for durable MW jobs.
 * State decisions import durableJobState.mjs (single production source of truth).
 *
 * Cleanup requires explicit domain reconciliation acknowledgement.
 * Transport /result HTTP 200 alone never clears a locator.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  isTerminal,
  isValidLocator,
  shouldClearLocator,
  shouldBlockStart,
  buildLocator,
  buildTerminalPayload,
  classifyPollOutcome,
  resolveRetryJobId,
  mergeRetryLocator,
  createScreenGeneration,
  isScreenGenerationCurrent,
} from "./durableJobState.mjs";

const POLL_INTERVAL_MS = 3000;

function readJson(response) {
  return response.json().catch(() => ({}));
}

function apiErrorText(error) {
  if (!error) return "未知错误";
  if (typeof error === "string") return error;
  return error.message || error.detail || JSON.stringify(error);
}

/**
 * Standalone async poller. Does not touch storage.
 * resultReconciled here means transport /result was fetched successfully —
 * domain reconciliation is the caller's responsibility.
 *
 * @returns {Promise<{status, result, error, outcome, transportResultOk}>}
 */
export async function pollDurableMwJob(projectId, jobId, opts = {}) {
  const intervalMs = opts.intervalMs ?? 1500;
  const maxLoops = opts.maxLoops ?? 200;
  const onUpdate = opts.onUpdate ?? null;
  const shouldContinue = opts.shouldContinue ?? (() => true);
  let lastStatus = "queued";
  let errorSummary = "";

  for (let i = 0; i < maxLoops && shouldContinue(); i++) {
    await new Promise((r) => setTimeout(r, intervalMs));
    try {
      const resp = await fetch(
        `/api/projects/${projectId}/medical-writing/jobs/${jobId}`
      );
      if (!resp.ok) continue;
      const body = await resp.json();
      lastStatus = body.status;
      errorSummary = body.error_summary || "";
      if (onUpdate) onUpdate(body);
      if (isTerminal(body.status)) break;
    } catch {
      // network error — keep polling
    }
  }

  let result = null;
  let transportResultOk = false;
  if (isTerminal(lastStatus)) {
    try {
      const r = await fetch(
        `/api/projects/${projectId}/medical-writing/jobs/${jobId}/result`
      );
      if (r.ok) {
        result = await r.json();
        transportResultOk = true;
      }
    } catch {
      transportResultOk = false;
    }
  }

  // Without domain ack, completed/failed/cancelled with transport result is still
  // reconcile_failed for cleanup purposes. outcome reflects transport-only view
  // when domainReconciled is forced false.
  const outcome = classifyPollOutcome(lastStatus, false);
  return {
    status: lastStatus,
    result,
    error: errorSummary,
    outcome,
    transportResultOk,
    // Back-compat alias: false until domain ack (never true from transport alone).
    resultReconciled: false,
  };
}

/**
 * Resolve domain acknowledgement from onTerminal callback return value.
 * true / { domainReconciled: true } => clear allowed
 */
export function resolveDomainAck(ack) {
  if (ack === true) return true;
  if (ack && typeof ack === "object" && ack.domainReconciled === true) return true;
  return false;
}

export function useDurableMwJob({
  projectId,
  jobType,
  storageKey,
  onTerminal,
  sectionId = "",
}) {
  const [jobState, setJobState] = useState(null);
  const [error, setError] = useState("");
  const pollRef = useRef(0);
  const actionInProgressRef = useRef(false);
  const onTerminalRef = useRef(onTerminal);
  onTerminalRef.current = onTerminal;
  const screenGenRef = useRef(createScreenGeneration(projectId, sectionId));

  useEffect(() => {
    screenGenRef.current = createScreenGeneration(projectId, sectionId);
  }, [projectId, sectionId]);

  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || "null");
      if (isValidLocator(stored) && stored.project_id === projectId) {
        setJobState({
          job_id: stored.job_id,
          status: "queued",
          progress: null,
          ...stored,
        });
      } else {
        setJobState(null);
      }
    } catch {
      setJobState(null);
    }
    setError("");
    pollRef.current += 1;
    return () => {
      pollRef.current += 1;
    };
  }, [projectId, storageKey]);

  useEffect(() => {
    if (!jobState?.job_id) return undefined;
    if (isTerminal(jobState.status)) return undefined;
    const generation = ++pollRef.current;
    const screenAtStart = screenGenRef.current;
    let cancelled = false;

    const poll = async () => {
      while (!cancelled && generation === pollRef.current) {
        try {
          const resp = await fetch(
            `/api/projects/${projectId}/medical-writing/jobs/${jobState.job_id}`
          );
          if (!resp.ok) {
            await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
            continue;
          }
          const body = await readJson(resp);
          if (cancelled || generation !== pollRef.current) return;
          if (!isScreenGenerationCurrent(screenAtStart, projectId, sectionId)) return;

          setJobState((previous) => {
            if (!previous) return previous;
            const prevPercent = previous.progress?.percent || 0;
            const newPercent = body.progress?.percent || 0;
            const monotonicProgress =
              newPercent >= prevPercent ? body.progress : previous.progress;
            return {
              ...previous,
              status: body.status,
              progress: monotonicProgress,
              error_summary: body.error_summary || "",
            };
          });

          if (isTerminal(body.status)) {
            let resultBody = null;
            let transportResultOk = false;
            try {
              const resultResp = await fetch(
                `/api/projects/${projectId}/medical-writing/jobs/${jobState.job_id}/result`
              );
              if (resultResp.ok) {
                resultBody = await readJson(resultResp);
                transportResultOk = true;
                if (!cancelled && generation === pollRef.current) {
                  setJobState((previous) =>
                    previous ? { ...previous, result: resultBody, transportResultOk } : previous
                  );
                }
              }
            } catch {
              transportResultOk = false;
            }

            if (cancelled || generation !== pollRef.current) return;
            if (!isScreenGenerationCurrent(screenAtStart, projectId, sectionId)) return;

            let domainReconciled = false;
            if (onTerminalRef.current) {
              const ack = await onTerminalRef.current(
                buildTerminalPayload(body.status, resultBody, body.error_summary || ""),
                { transportResultOk, locator: jobState }
              );
              domainReconciled = resolveDomainAck(ack);
            }

            if (
              !cancelled
              && generation === pollRef.current
              && isScreenGenerationCurrent(screenAtStart, projectId, sectionId)
              && shouldClearLocator(body.status, domainReconciled)
            ) {
              try {
                localStorage.removeItem(storageKey);
              } catch {
                /* ignore */
              }
              setJobState(null);
            } else if (!cancelled && generation === pollRef.current) {
              setJobState((previous) =>
                previous
                  ? {
                      ...previous,
                      status: body.status,
                      domainReconciled: false,
                      result: resultBody,
                    }
                  : previous
              );
            }
            return;
          }
        } catch (err) {
          if (
            !cancelled
            && generation === pollRef.current
            && isScreenGenerationCurrent(screenAtStart, projectId, sectionId)
          ) {
            setError(`作业状态轮询失败：${apiErrorText(err)}`);
          }
        }
        await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
      }
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [jobState?.job_id, jobState?.status, projectId, sectionId, storageKey]);

  const startJob = useCallback(
    async (startUrl, payload, headers) => {
      if (actionInProgressRef.current) return null;
      if (shouldBlockStart(jobState?.status)) return null;
      actionInProgressRef.current = true;
      setError("");
      const screenAtStart = screenGenRef.current;
      try {
        const resp = await fetch(startUrl, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...headers },
          body: JSON.stringify(payload),
        });
        const body = await readJson(resp);
        if (!isScreenGenerationCurrent(screenAtStart, projectId, sectionId)) {
          return null;
        }
        if (!resp.ok && resp.status !== 202) {
          const detail =
            typeof body.detail === "string" ? body.detail : apiErrorText(body);
          setError(detail);
          return null;
        }
        const jobId = body.job_id;
        if (!jobId) {
          return body;
        }
        if (body.status === "completed" && body.result) {
          // Do NOT clear storage until domain acknowledges exact artifact.
          let domainReconciled = false;
          if (onTerminalRef.current) {
            const ack = await onTerminalRef.current(
              buildTerminalPayload("completed", body.result, ""),
              { transportResultOk: true, locator: null, cached: true }
            );
            domainReconciled = resolveDomainAck(ack);
          }
          if (domainReconciled) {
            try {
              localStorage.removeItem(storageKey);
            } catch {
              /* ignore */
            }
            setJobState(null);
          } else {
            // Retain any prior locator; surface cached result for reconcile UI.
            setJobState((prev) => ({
              ...(prev || {}),
              job_id: jobId,
              status: "completed",
              result: body.result,
              domainReconciled: false,
            }));
          }
          return body;
        }
        // Persist locator BEFORE polling starts.
        const locator = buildLocator({
          projectId,
          jobId,
          operation: body.operation || jobType || "",
          sectionId: payload?.section_id || sectionId || body.section_id || "",
          jobType: jobType || body.job_type || "",
          runId: body.run_id || "",
          batchId: body.batch_id || body.durable_job_id || "",
          snapshotId: body.snapshot_id || payload?.snapshot_id || "",
        });
        try {
          localStorage.setItem(storageKey, JSON.stringify(locator));
        } catch {
          /* ignore */
        }
        setJobState({
          job_id: jobId,
          status: body.status || "queued",
          progress: null,
          ...locator,
        });
        return body;
      } catch (err) {
        setError(`作业启动失败：${apiErrorText(err)}`);
        return null;
      } finally {
        actionInProgressRef.current = false;
      }
    },
    [jobState, projectId, jobType, storageKey, sectionId]
  );

  const cancelJob = useCallback(async () => {
    if (!jobState?.job_id) return;
    try {
      await fetch(
        `/api/projects/${projectId}/medical-writing/jobs/${jobState.job_id}/cancel`,
        { method: "POST" }
      );
      // Never clear locator here — domain recon after poll decides.
    } catch (err) {
      setError(`取消失败：${apiErrorText(err)}`);
    }
  }, [jobState, projectId]);

  const retryJob = useCallback(async () => {
    if (!jobState?.job_id) return;
    try {
      const resp = await fetch(
        `/api/projects/${projectId}/medical-writing/jobs/${jobState.job_id}/retry`,
        { method: "POST" }
      );
      if (resp.ok) {
        const body = await readJson(resp);
        const nextJobId = resolveRetryJobId(jobState.job_id, body);
        const locator = mergeRetryLocator(jobState, nextJobId, projectId);
        try {
          localStorage.setItem(storageKey, JSON.stringify(locator));
        } catch {
          /* ignore */
        }
        setJobState({
          ...locator,
          status: "queued",
          progress: null,
          error_summary: "",
          domainReconciled: false,
        });
      }
    } catch (err) {
      setError(`重试失败：${apiErrorText(err)}`);
    }
  }, [jobState, projectId, storageKey]);

  const clearJob = useCallback(() => {
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* ignore */
    }
    setJobState(null);
    setError("");
  }, [storageKey]);

  /**
   * Explicit domain ack after caller proves exact business artifact.
   * Only path that clears storage for a terminal job via the hook.
   */
  const acknowledgeDomain = useCallback(
    (status, domainReconciled) => {
      if (shouldClearLocator(status, domainReconciled === true)) {
        try {
          localStorage.removeItem(storageKey);
        } catch {
          /* ignore */
        }
        setJobState(null);
        return true;
      }
      setJobState((previous) =>
        previous
          ? { ...previous, status, domainReconciled: false }
          : previous
      );
      return false;
    },
    [storageKey]
  );

  const isBusy = Boolean(jobState && !isTerminal(jobState.status));

  return {
    jobState,
    error,
    isBusy,
    startJob,
    cancelJob,
    retryJob,
    clearJob,
    acknowledgeDomain,
    actionInProgressRef,
  };
}

export {
  isCompletedSuccess,
  isTerminal,
  shouldClearLocator,
  shouldBlockStart,
  shouldBlockStartForOperation,
  buildLocator,
  extractArtifactThreadId,
  extractArtifactSuggestionIds,
  extractArtifactPostThreadHash,
  extractArtifactRunId,
  extractArtifactBatchId,
  extractArtifactSnapshotId,
  classifyPollOutcome,
  decideLocatorCleanup,
  isStaleCompletion,
  createScreenGeneration,
  isScreenGenerationCurrent,
  resolveRetryJobId,
  mergeRetryLocator,
  validateRevisionArtifactExact,
  acknowledgeRevisionDomain,
  acknowledgeTriageDomain,
  acknowledgeTranslationDomain,
  emptyRevisionJobMap,
  setOperationJob,
  clearOperationJob,
  pickFocusedRevisionJob,
  durableJobController,
} from "./durableJobState.mjs";
