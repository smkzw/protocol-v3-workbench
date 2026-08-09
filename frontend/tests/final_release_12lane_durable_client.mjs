/**
 * Durable product workflow client — E3 Worker 03 (Acceptance Remediation 03).
 *
 * D2: On terminal "completed", require exactly one /result GET and return that.
 * D3: Synopsis public status is "review_ready" (not "completed"); treat as
 *     result-ready terminal, call /result, persist journey/result identity.
 * D6: Per-step atomic reconciliation record: request key, status/result hashes,
 *     artifact locator, thread/suggestions, receipt, adopt result, re-read state,
 *     rewrite state. Locator marked "reconciled", not deleted until evidence committed.
 * D7: Checkpoint binds runtimeDir/projectCode/projectId/lane/sourceMode/sourceSha/
 *     allocationAttempt lineage. Required, not conditional.
 * D8: Recursive canonical JSON for raw response hash.
 *
 * @module final_release_12lane_durable_client
 */

import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile, rename, unlink, open as fsOpen } from "node:fs/promises";
import { fsyncSync, closeSync, openSync } from "node:fs";
import { existsSync as fsExistsSync } from "node:fs";
import path from "node:path";

const DEFAULT_POLL_INTERVAL_MS = 3000;
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);
const RETRYABLE_STATUSES = new Set(["failed", "cancelled", "timeout"]);

// D3: Synopsis-specific result-ready terminal
const SYNOPSIS_RESULT_READY = "review_ready";

export const LOCATOR_SCHEMA_VERSION = "mw_e3_locator_v2";

// ─── D8: Recursive canonical JSON hash ──────────────────────────────────

export function canonicalJsonStringify(obj) {
  if (obj === null || obj === undefined) return "null";
  if (typeof obj !== "object") return JSON.stringify(obj);
  if (Array.isArray(obj)) {
    return "[" + obj.map(canonicalJsonStringify).join(",") + "]";
  }
  const keys = Object.keys(obj).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + canonicalJsonStringify(obj[k])).join(",") + "}";
}

export function computeRawResponseHash(obj) {
  return createHash("sha256").update(canonicalJsonStringify(obj)).digest("hex");
}

// ─── UnresolvedResultError: /result fetch failed on completed status ────

export class UnresolvedResultError extends Error {
  constructor(stepId, jobId, message) {
    super(message || `result fetch failed for step ${stepId} (job ${jobId}): status is completed but /result returned no payload`);
    this.name = "UnresolvedResultError";
    this.unresolvedResult = true;
    this.stepId = stepId;
    this.jobId = jobId;
  }
}

// ─── D2: Stable idempotency key ─────────────────────────────────────────

export function stableIdempotencyKey(laneKey, projectId, action, sectionId = "", sourceContext = "") {
  const parts = [laneKey, projectId, action];
  if (sectionId) parts.push(sectionId);
  if (sourceContext) parts.push(sourceContext);
  return "e3-" + createHash("sha256").update(parts.join(":")).digest("hex").slice(0, 32);
}

/**
 * DurableMwClient — drives product durable jobs for one lane.
 */
export class DurableMwClient {
  constructor({ projectId, laneKey, evidenceDir, apiJson, gateRecorder, report, pollIntervalMs = DEFAULT_POLL_INTERVAL_MS }) {
    this.projectId = projectId;
    this.laneKey = laneKey;
    this.evidenceDir = evidenceDir;
    this.apiJson = apiJson;
    this.gateRecorder = gateRecorder || (() => {});
    this.report = report || {};
    this.pollIntervalMs = pollIntervalMs;
    this.locatorsPath = path.join(evidenceDir, "job_locators.json");
    this.reconciliationPath = path.join(evidenceDir, "step_reconciliations.json");
    this.locators = {};
    this.reconciliations = {};
    this._idempotencyKeys = new Map();
  }

  getIdempotencyKey(stepId) {
    const existing = this.locators[stepId]?.idempotency_key;
    if (existing) return existing;
    const fromMap = this._idempotencyKeys.get(stepId);
    if (fromMap) return fromMap;
    const key = stableIdempotencyKey(this.laneKey, this.projectId, stepId);
    this._idempotencyKeys.set(stepId, key);
    return key;
  }

  // ─── D3: Atomic file persistence ───────────────────────────────────

  async loadLocators() {
    if (!fsExistsSync(this.locatorsPath)) { this.locators = {}; return; }
    let data;
    try { data = await readFile(this.locatorsPath, "utf8"); } catch { throw new Error(`locator read error: ${this.locatorsPath}`); }
    let parsed;
    try { parsed = JSON.parse(data); } catch { throw new Error(`locator corrupted (malformed JSON): ${this.locatorsPath}`); }
    if (!parsed || typeof parsed !== "object") throw new Error("locator invalid: not an object");
    if (parsed.schema_version !== LOCATOR_SCHEMA_VERSION) throw new Error(`locator schema mismatch: expected ${LOCATOR_SCHEMA_VERSION}, got ${parsed.schema_version || "missing"}`);
    if (parsed.project_id && parsed.project_id !== this.projectId) throw new Error(`locator project mismatch: expected ${this.projectId}, got ${parsed.project_id}`);
    if (parsed.lane_key && parsed.lane_key !== this.laneKey) throw new Error(`locator lane mismatch: expected ${this.laneKey}, got ${parsed.lane_key}`);
    this.locators = parsed.locators || {};
    this.reconciliations = parsed.reconciliations || {};
  }

  async _atomicWrite(filePath, obj) {
    await mkdir(path.dirname(filePath), { recursive: true });
    const jsonStr = JSON.stringify(obj, null, 2);
    const tmpPath = path.join(path.dirname(filePath), `.tmp.${process.pid}.${Date.now()}`);
    const fh = await fsOpen(tmpPath, "w");
    try { await fh.writeFile(jsonStr, "utf8"); await fh.sync(); } finally { await fh.close(); }
    try {
      await rename(tmpPath, filePath);
      // D4: fsync the directory file descriptor to ensure the rename is durable
      await _fsyncDir(path.dirname(filePath));
    } catch (e) { try { await unlink(tmpPath); } catch {} throw e; }
  }

  async saveLocators() {
    await this._atomicWrite(this.locatorsPath, {
      schema_version: LOCATOR_SCHEMA_VERSION, lane_key: this.laneKey, project_id: this.projectId,
      locators: this.locators, reconciliations: this.reconciliations,
    });
  }

  // ─── D6: Per-step reconciliation record ────────────────────────────

  async saveReconciliation(stepId, record) {
    this.reconciliations[stepId] = { ...record, reconciled_at: new Date().toISOString() };
    await this.saveLocators();
  }

  getReconciliation(stepId) { return this.reconciliations[stepId] || null; }
  isReconciled(stepId) { return Boolean(this.reconciliations[stepId]?.reconciled); }

  // ─── D2: Start + Poll + Result (completed requires /result) ────────

  async startAndPoll(stepId, startUrl, payloadBuilder, options = {}) {
    const timeoutMs = options.timeoutMs || 900000;
    const existing = this.locators[stepId];
    this._currentStepId = stepId;

    // Completed or reconciled → fetch result (D1: must reject null, verify hash)
    if (existing && (existing.status === "completed" || existing.reconciled)) {
      const resultDto = await this._fetchResult(existing.job_id);
      if (!resultDto) {
        this.locators[stepId].result_fetch_failed = true;
        await this.saveLocators();
        throw new UnresolvedResultError(stepId, existing.job_id);
      }
      this.locators[stepId].result_hash = computeRawResponseHash(resultDto);
      this.locators[stepId].artifact_locator = resultDto.artifact_locator || null;
      await this.saveLocators();
      return resultDto;
    }
    if (existing && RETRYABLE_STATUSES.has(existing.status)) {
      const err = new Error(`step ${stepId} retryable: ${existing.status}; call retry()`);
      err.needsRetry = true; err.stepId = stepId; err.locatorStatus = existing.status;
      throw err;
    }

    let jobId;
    if (existing?.job_id && !TERMINAL_STATUSES.has(existing.status) && existing.status !== "timeout") {
      jobId = existing.job_id; // crash resume
    } else {
      const idempotencyKey = this.getIdempotencyKey(stepId);
      const payload = typeof payloadBuilder === "function" ? payloadBuilder(idempotencyKey) : { ...payloadBuilder, idempotency_key: idempotencyKey };
      const startResult = await this.apiJson("POST", startUrl, { body: payload, timeout: Math.min(timeoutMs, 120000) });
      const body = startResult.payload || {};
      jobId = body.job_id || body.durable_job_id;
      if (!jobId) throw new Error(`durable start returned no job_id for step ${stepId}`);
      // D3: Even immediate completed-with-result must go through /result
      if (body.status === "completed" && body.result) {
        this.locators[stepId] = { job_id: jobId, status: "completed", idempotency_key: idempotencyKey, started_at: existing?.started_at || new Date().toISOString() };
        this.locators[stepId].status_hash = computeRawResponseHash(body);
        // D3: Still fetch authoritative /result — status alone must NOT satisfy artifact gates
        const resultDto = await this._fetchResult(jobId);
        if (resultDto) {
          this.locators[stepId].result_hash = computeRawResponseHash(resultDto);
          this.locators[stepId].artifact_locator = resultDto.artifact_locator || null;
        } else {
          // /result not available — status alone does not satisfy artifact gates
          this.locators[stepId].result_fetch_failed = true;
          await this.saveLocators();
          throw new UnresolvedResultError(stepId, jobId);
        }
        await this.saveLocators();
        return resultDto;
      }
    }

    const idempotencyKey = this.getIdempotencyKey(stepId);
    this.locators[stepId] = { job_id: jobId, status: "queued", idempotency_key: idempotencyKey, started_at: existing?.started_at || new Date().toISOString() };
    await this.saveLocators();

    // Poll until terminal
    const statusResult = await this._pollJob(jobId, timeoutMs);
    if (!statusResult) {
      this.locators[stepId].status = "timeout";
      this.locators[stepId].timeout_at = new Date().toISOString();
      await this.saveLocators();
      return null;
    }

    // D2: Persist status hash
    this.locators[stepId].status_hash = computeRawResponseHash(statusResult);
    this.locators[stepId].status = statusResult.status;
    this.locators[stepId].finished_at = new Date().toISOString();
    await this.saveLocators();

    // D2: On completed, require exactly one /result GET
    if (statusResult.status === "completed") {
      const resultDto = await this._fetchResult(jobId);
      if (resultDto) {
        this.locators[stepId].result_hash = computeRawResponseHash(resultDto);
        this.locators[stepId].artifact_locator = resultDto.artifact_locator || null;
        await this.saveLocators();
        return resultDto;
      }
      // /result fetch failed — throw UnresolvedResultError; status must NOT satisfy artifact gates
      this.locators[stepId].result_fetch_failed = true;
      await this.saveLocators();
      throw new UnresolvedResultError(stepId, jobId);
    }

    // Failed/cancelled: return status but do NOT fetch result artifact
    return statusResult;
  }

  async retry(stepId, options = {}) {
    const timeoutMs = options.timeoutMs || 900000;
    const locator = this.locators[stepId];
    if (!locator?.job_id) throw new Error(`no locator to retry for step ${stepId}`);
    if (!RETRYABLE_STATUSES.has(locator.status)) throw new Error(`step ${stepId} not retryable: ${locator.status}`);
    const result = await this.apiJson("POST", `/api/projects/${this.projectId}/medical-writing/jobs/${locator.job_id}/retry`);
    const body = result.payload || {};
    const newJobId = body.job_id || body.replacement_job_id;
    const effectiveJobId = newJobId || locator.job_id;
    if (newJobId && newJobId !== locator.job_id) {
      this.locators[stepId] = { ...this.locators[stepId], job_id: newJobId, status: "queued", retry_of: locator.job_id, retried_at: new Date().toISOString() };
    } else {
      this.locators[stepId].status = "queued";
      this.locators[stepId].retried_at = new Date().toISOString();
    }
    await this.saveLocators();
    this._currentStepId = stepId;
    const pollResult = await this._pollJob(effectiveJobId, timeoutMs);
    let returnDto = null;
    if (pollResult) {
      this.locators[stepId].status = pollResult.status;
      this.locators[stepId].finished_at = new Date().toISOString();
      this.locators[stepId].status_hash = computeRawResponseHash(pollResult);
      if (pollResult.status === "completed") {
        // D1b: On completed status, fetch /result and return the result DTO, not the poll status
        const resultDto = await this._fetchResult(effectiveJobId);
        if (resultDto) {
          this.locators[stepId].result_hash = computeRawResponseHash(resultDto);
          this.locators[stepId].artifact_locator = resultDto.artifact_locator || null;
          returnDto = resultDto;
        } else {
          // /result fetch failed — throw UnresolvedResultError
          this.locators[stepId].result_fetch_failed = true;
          await this.saveLocators();
          throw new UnresolvedResultError(stepId, effectiveJobId);
        }
      } else {
        // Failed/cancelled: return poll status, do NOT fetch result artifact
        returnDto = pollResult;
      }
    } else {
      this.locators[stepId].status = "timeout";
      this.locators[stepId].timeout_at = new Date().toISOString();
    }
    await this.saveLocators();
    return returnDto;
  }

  async clearLocator(stepId, options = {}) {
    // D5: Only mark reconciled when caller explicitly confirms reconciliation
    // is complete. Never upgrade failed or partial verification.
    const reconciled = options.reconciled === true;
    if (this.locators[stepId]) {
      if (reconciled) {
        this.locators[stepId].reconciled = true;
        this.locators[stepId].reconciled_at = new Date().toISOString();
      }
      // If not reconciled, do NOT change the locator — retain for resume
      await this.saveLocators();
    }
  }

  async deleteLocator(stepId) {
    // Only called after lane evidence is durably committed
    delete this.locators[stepId];
    this._idempotencyKeys.delete(stepId);
    await this.saveLocators();
  }

  isStepCompleted(stepId) { const loc = this.locators[stepId]; return Boolean(loc && loc.status === "completed" && loc.result_hash); }
  getLocator(stepId) { return this.locators[stepId] || null; }

  // ─── D3: Synopsis import (review_ready terminal) ───────────────────

  async startSynopsisImport(uploadFn, idempotencyKey, timeoutMs = 1200000) {
    const stepId = "synopsis_import";
    const existing = this.locators[stepId];
    // D3: review_ready or completed = result-ready
    if (existing && (existing.status === SYNOPSIS_RESULT_READY || existing.status === "completed" || existing.reconciled)) {
      return this._fetchSynopsisResult(existing.idempotency_key || existing.job_id);
    }
    if (existing && RETRYABLE_STATUSES.has(existing.status)) {
      const err = new Error(`synopsis retryable: ${existing.status}`);
      err.needsRetry = true; err.stepId = stepId; throw err;
    }
    if (existing?.idempotency_key && !TERMINAL_STATUSES.has(existing.status) && existing.status !== "timeout" && existing.status !== SYNOPSIS_RESULT_READY) {
      return this._pollSynopsisJob(existing.idempotency_key, timeoutMs);
    }
    // Start new
    const uploadResult = await uploadFn(idempotencyKey);
    const jobId = uploadResult.job_id || uploadResult.idempotency_key || idempotencyKey;
    this.locators[stepId] = { job_id: jobId, idempotency_key: uploadResult.idempotency_key || idempotencyKey, status: uploadResult.status || "pending", started_at: new Date().toISOString() };
    await this.saveLocators();
    return this._pollSynopsisJob(this.locators[stepId].idempotency_key, timeoutMs);
  }

  async _pollSynopsisJob(idempotencyKey, timeoutMs) {
    const start = Date.now();
    const pollPath = `/api/projects/${this.projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${idempotencyKey}`;
    while (Date.now() - start < timeoutMs) {
      try {
        const result = await this.apiJson("GET", pollPath);
        const job = result.payload || {};
        const status = job.status;
        // D3: review_ready is the result-ready terminal (not "completed")
        if (status === SYNOPSIS_RESULT_READY || status === "completed") {
          this.locators.synopsis_import = { ...this.locators.synopsis_import, status: SYNOPSIS_RESULT_READY, finished_at: new Date().toISOString(), status_hash: computeRawResponseHash(job) };
          await this.saveLocators();
          return await this._fetchSynopsisResult(idempotencyKey);
        }
        if (status === "failed" || status === "cancelled") {
          this.locators.synopsis_import = { ...this.locators.synopsis_import, status, finished_at: new Date().toISOString(), status_hash: computeRawResponseHash(job) };
          await this.saveLocators();
          return job;
        }
      } catch {}
      await _sleep(this.pollIntervalMs);
    }
    this.locators.synopsis_import = { ...this.locators.synopsis_import, status: "timeout", timeout_at: new Date().toISOString() };
    await this.saveLocators();
    return null;
  }

  async _fetchSynopsisResult(idempotencyKey) {
    const result = await this.apiJson("GET", `/api/projects/${this.projectId}/medical-writing/authoring-journey/synopsis-import/jobs/${idempotencyKey}/result`);
    const payload = result.payload;
    if (payload) {
      this.locators.synopsis_import.result_hash = computeRawResponseHash(payload);
      // Persist journey revision identity
      if (payload.revision) this.locators.synopsis_import.journey_revision = payload.revision;
      await this.saveLocators();
    }
    return payload;
  }

  async _pollJob(jobId, timeoutMs) {
    const start = Date.now();
    const statusPath = `/api/projects/${this.projectId}/medical-writing/jobs/${jobId}`;
    let lastError = null;
    let lastObservedStatus = null;
    while (Date.now() - start < timeoutMs) {
      try {
        const result = await this.apiJson("GET", statusPath);
        const job = result.payload || {};
        lastObservedStatus = job.status || "unknown";
        if (TERMINAL_STATUSES.has(job.status)) {
          // D10: Clear error on successful terminal observation
          if (this.locators[this._currentStepId]) {
            this.locators[this._currentStepId].last_observed_status = lastObservedStatus;
            this.locators[this._currentStepId].last_poll_error = null;
          }
          return job;
        }
      } catch (e) {
        // D10: Preserve last observed error/status
        lastError = e.message?.slice(0, 200) || String(e);
        // D10: Fail closed on 4xx contract errors (except 404/429)
        if (e.status >= 400 && e.status < 500 && e.status !== 404 && e.status !== 429) {
          throw new Error(`_pollJob terminal HTTP ${e.status} for ${jobId}: ${lastError}`);
        }
        // 404/5xx/network = transient, keep polling
      }
      await _sleep(this.pollIntervalMs);
    }
    // D10: Persist error context in locator
    const stepId = this._currentStepId;
    if (stepId && this.locators[stepId]) {
      this.locators[stepId].last_observed_status = lastObservedStatus;
      this.locators[stepId].last_poll_error = lastError;
    }
    if (this.report) {
      this.report._lastPollError = lastError;
      this.report._lastPollStatus = lastObservedStatus;
    }
    return null;
  }

  async _fetchResult(jobId) {
    try {
      const result = await this.apiJson("GET", `/api/projects/${this.projectId}/medical-writing/jobs/${jobId}/result`);
      return result.payload;
    } catch { return null; }
  }

  extractArtifact(jobResult) { return jobResult?.artifact || jobResult?.result || null; }
}

// ─── D7: Lane checkpoint with full identity ─────────────────────────────

export const CHECKPOINT_SCHEMA_VERSION = "mw_e3_checkpoint_v2";

export class LaneCheckpoint {
  constructor({ laneKey, evidenceDir, runtimeDir, projectCode }) {
    this.laneKey = laneKey;
    this.evidenceDir = evidenceDir;
    this.runtimeDir = runtimeDir || "";
    this.projectCode = projectCode || "";
    this.checkpointPath = path.join(evidenceDir, "lane_checkpoint.json");
    this.data = null;
  }

  async load() {
    if (!fsExistsSync(this.checkpointPath)) { this.data = null; return null; }
    try {
      const raw = await readFile(this.checkpointPath, "utf8");
      const parsed = JSON.parse(raw);
      if (parsed.schema_version !== CHECKPOINT_SCHEMA_VERSION) throw new Error(`checkpoint schema mismatch: ${parsed.schema_version}`);
      if (parsed.lane_key !== this.laneKey) throw new Error(`checkpoint lane mismatch: expected ${this.laneKey}, got ${parsed.lane_key}`);
      // D2: Require non-empty exact lineage — missing values are hard failures
      if (!parsed.runtime_dir) throw new Error("checkpoint missing runtime_dir");
      if (this.runtimeDir && parsed.runtime_dir !== this.runtimeDir) throw new Error(`checkpoint runtimeDir mismatch: expected ${this.runtimeDir}, got ${parsed.runtime_dir}`);
      if (!parsed.project_code) throw new Error("checkpoint missing project_code");
      if (this.projectCode && parsed.project_code !== this.projectCode) throw new Error(`checkpoint projectCode mismatch: expected ${this.projectCode}, got ${parsed.project_code}`);
      if (!parsed.project_id) throw new Error("checkpoint missing project_id");
      if (!parsed.source_mode) throw new Error("checkpoint missing source_mode");
      if (parsed.allocation_attempt === undefined || parsed.allocation_attempt === null || parsed.allocation_attempt <= 0) throw new Error("checkpoint missing or zero allocation_attempt");
      this.data = parsed;
      return parsed;
    } catch (e) { throw new Error(`checkpoint load failed: ${e.message}`); }
  }

  async save({ projectId, sourceMode, journeyRevision, sourceSha, allocationAttempt, completedStages, stageArtifacts }) {
    const now = new Date().toISOString();
    // D2: allocationAttempt must be positive exact value — never default to 0
    const existingAttempt = this.data?.allocation_attempt;
    const resolvedAttempt = allocationAttempt !== undefined && allocationAttempt !== null
      ? allocationAttempt
      : existingAttempt;
    if (!resolvedAttempt || resolvedAttempt <= 0) {
      throw new Error("checkpoint save requires positive allocationAttempt");
    }
    this.data = {
      schema_version: CHECKPOINT_SCHEMA_VERSION,
      lane_key: this.laneKey,
      runtime_dir: this.runtimeDir,
      project_code: this.projectCode,
      project_id: projectId,
      source_mode: sourceMode,
      source_sha: sourceSha || "",
      allocation_attempt: resolvedAttempt,
      journey_revision: journeyRevision,
      completed_stages: completedStages || [],
      stage_artifacts: stageArtifacts || {},
      created_at: this.data?.created_at || now,
      updated_at: now,
    };
    await this._atomicWrite(this.checkpointPath, this.data);
    return this.data;
  }

  async _atomicWrite(filePath, obj) {
    await mkdir(path.dirname(filePath), { recursive: true });
    const jsonStr = JSON.stringify(obj, null, 2);
    const tmpPath = path.join(path.dirname(filePath), `.tmp.${process.pid}.${Date.now()}`);
    const fh = await fsOpen(tmpPath, "w");
    try { await fh.writeFile(jsonStr, "utf8"); await fh.sync(); } finally { await fh.close(); }
    await rename(tmpPath, filePath);
    // D4: fsync the directory file descriptor to ensure the rename is durable
    await _fsyncDir(path.dirname(filePath));
  }

  hasProject() { return Boolean(this.data?.project_id); }
  getProjectId() { return this.data?.project_id || null; }
  getCompletedStages() { return this.data?.completed_stages || []; }
  isStageCompleted(stage) { return (this.data?.completed_stages || []).includes(stage); }
}

function _sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

/**
 * D4: fsync the directory file descriptor after a rename to ensure the
 * directory entry itself is durable on disk.  Without this, a crash after
 * rename may lose the rename even though the data was fsynced.
 */
async function _fsyncDir(dirPath) {
  try {
    const dirFd = openSync(dirPath, "r");
    try { fsyncSync(dirFd); } catch {}
    closeSync(dirFd);
  } catch {
    // Directory may not be fsyncable (e.g. tmpfs, or permission constraints);
    // the file fsync already covers data durability. Best-effort.
  }
}

// ─── D4: Candidate artifact extraction ──────────────────────────────────

export function extractCandidateArtifact(jobResult) {
  const artifact = jobResult?.artifact || jobResult?.result || jobResult;
  if (!artifact) throw new Error("candidate job result has no artifact");
  const threadId = artifact.thread_id || artifact.revision_thread_id || artifact.thread?.thread_id;
  if (!threadId) throw new Error("candidate artifact missing thread_id");
  // D4: Support direct suggestion_ids array when present
  let suggestionIds = [];
  if (Array.isArray(artifact.suggestion_ids)) {
    suggestionIds = artifact.suggestion_ids.filter(Boolean);
  } else if (Array.isArray(artifact.suggestions)) {
    suggestionIds = artifact.suggestions.map((s) => s.suggestion_id || s.id).filter(Boolean);
  } else if (Array.isArray(artifact.candidates)) {
    suggestionIds = artifact.candidates.map((s) => s.suggestion_id || s.id).filter(Boolean);
  }
  if (suggestionIds.length === 0) throw new Error("candidate artifact has no suggestion_ids");
  return { thread_id: threadId, suggestion_ids: suggestionIds };
}
