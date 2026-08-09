/**
 * ServiceReceipt collection — E3 Worker 03 (Acceptance Remediation 03).
 *
 * D8: Recursive canonical JSON hash (not shallow sort).
 * D8: ReceiptCollector recomputes hash on verify.
 * D8: Honest gap reporting — do not invent policy/input/output hashes absent
 *     from server evidence; fail the applicable gate honestly.
 *
 * @module final_release_12lane_receipts
 */

import { canonicalJsonStringify, computeRawResponseHash } from "./final_release_12lane_durable_client.mjs";
import {
  SERVICE_RECEIPT_SCHEMA_VERSION, SERVICE_RECEIPT_FIELDS, SERVICE_ROLES,
  EXPECTED_PRODUCT_IDENTITIES, VALID_RECEIPT_SOURCES, GATE_CODES_12LANE,
  validateServiceReceipt,
} from "./final_release_12lane_config.mjs";

export { canonicalJsonStringify, computeRawResponseHash };

/**
 * Build a ServiceReceipt from product job result.
 * D8: Does NOT invent policy/input/output hashes absent from server evidence.
 * If the product does not return these, the receipt stores null and the gate
 * fails honestly.
 */
export function buildServiceReceipt({
  laneKey, stepId, serviceRole, jobResult, responseHeaders, artifactIds = [],
  locator = null, idempotencyKey = null, statusHash = null, resultHash = null,
}) {
  if (!jobResult) return null;

  const provider = jobResult.provider || _header(responseHeaders, "x-mw-provider") || null;
  const model = jobResult.model || _header(responseHeaders, "x-mw-model") || null;
  const policyVersion = jobResult.policy_version || jobResult.prompt_version || _header(responseHeaders, "x-mw-policy-version") || null;
  const policyHash = jobResult.policy_hash || jobResult.prompt_hash || _header(responseHeaders, "x-mw-policy-hash") || null;

  const productTaskId = jobResult.task_id || jobResult.product_task_id || null;
  const productJobId = jobResult.job_id || jobResult.durable_job_id || null;
  const productRunId = jobResult.run_id || jobResult.run_id_ || null;

  // Provenance check — job ID must match locator
  if (locator?.job_id && productJobId && locator.job_id !== productJobId) return null;

  // Forged provider/model detection
  const expected = EXPECTED_PRODUCT_IDENTITIES[serviceRole];
  if (expected?.model && provider && model) {
    if (provider !== expected.provider || model !== expected.model) return null;
  }

  // Backend roles (ctgov, citation_resolution, docx_export) may be synchronous —
  // they do NOT require a durable job_id.  Only enforce job_id requirement for
  // truly durable AI roles.
  const isDurableAiStep = _isLongStep(serviceRole);
  if (isDurableAiStep && !productJobId && !productRunId && !productTaskId) return null;

  // D8: Store status_hash and result_hash SEPARATELY — a status hash must
  // never substitute for a result hash.  For AI roles especially, the
  // authoritative /result hash is the artifact-evidence hash.
  // raw_response_hash uses resultHash first (authoritative /result), then
  // statusHash, then a computed fallback — but the two are independently
  // carried in the receipt so collectors can verify them independently.
  const rawHash = resultHash || statusHash || computeRawResponseHash(jobResult);

  // D8: Honest gap reporting — do not invent policy/input/output hashes
  const inputHash = jobResult.input_hash || jobResult.input_redacted_hash || null;
  const outputHash = jobResult.output_hash || jobResult.output_redacted_hash || null;

  const receipt = {
    schema_version: SERVICE_RECEIPT_SCHEMA_VERSION,
    lane_key: laneKey, step_id: stepId, service_role: serviceRole,
    provider, model,
    endpoint_class: jobResult.endpoint_class || expected?.endpoint_class || null,
    policy_or_prompt_version: policyVersion,
    policy_or_prompt_hash: policyHash,
    product_task_id: productTaskId, product_job_id: productJobId, product_run_id: productRunId,
    request_started_at: jobResult.started_at || jobResult.request_started_at || null,
    request_ended_at: jobResult.finished_at || jobResult.request_ended_at || null,
    terminal_status: jobResult.status || jobResult.terminal_status || null,
    artifact_ids: artifactIds,
    input_redacted_hash: inputHash,
    output_redacted_hash: outputHash,
    source: _resolveReceiptSource(jobResult, responseHeaders),
    hardcoded: false,
    raw_response_hash: rawHash,
    // Separate status/result hash fields for independent collector verification
    status_hash: statusHash || null,
    result_hash: resultHash || null,
    request_identity: {
      step_id: stepId, lane_key: laneKey, idempotency_key: idempotencyKey,
      locator_job_id: locator?.job_id || null, result_job_id: productJobId,
      status_hash: statusHash || null, result_hash: resultHash || null,
    },
  };

  return receipt;
}

function _header(headers, name) {
  if (!headers || typeof headers.get !== "function") return null;
  return headers.get(name) || null;
}

/**
 * Truly durable AI roles that always require a durable job reference.
 * Backend roles (ctgov, citation_resolution, docx_export) may run synchronously
 * and must NOT be forced to invent a durable job_id when the response has none.
 */
function _isLongStep(role) {
  // D8: Only genuinely durable AI steps require a job_id.
  // ctgov/citation_resolution/docx_export are synchronous backend roles.
  return ["reasoning_generation", "translation_orchestration", "translation_body", "ocr"].includes(role);
}

function _resolveReceiptSource(jobResult, responseHeaders) {
  if (responseHeaders && typeof responseHeaders.get === "function") {
    if (_header(responseHeaders, "x-mw-provider") || _header(responseHeaders, "x-mw-model")) return "response_header";
  }
  if (jobResult.artifact_locator || jobResult.result) return "job_result_artifact";
  if (jobResult.status) return "server_side_record";
  return null;
}

/**
 * ReceiptCollector — D8: recomputes hash on verify.
 */
export class ReceiptCollector {
  constructor(laneKey) {
    this.laneKey = laneKey;
    this.receipts = [];
    this.failures = [];
    this._artifactOwnership = new Map();
    this._rawResponses = new Map(); // Store raw response for recompute
  }

  add(receipt, rawResponse, report, gateRecorder) {
    if (!receipt) {
      this.failures.push("receipt_null");
      if (gateRecorder) gateRecorder(report, GATE_CODES_12LANE.GATE_SERVICE_RECEIPT_INCOMPLETE, { lane_key: this.laneKey, reason: "receipt_null" });
      return false;
    }
    const validation = validateServiceReceipt(receipt);
    if (!validation.valid) {
      this.failures.push(validation.errors.join(","));
      if (gateRecorder) gateRecorder(report, GATE_CODES_12LANE.GATE_SERVICE_RECEIPT_INCOMPLETE, { lane_key: this.laneKey, step_id: receipt.step_id, errors: validation.errors });
      return false;
    }

    // D8: Recompute hash from raw response if available
    if (receipt.raw_response_hash && rawResponse) {
      const recomputed = computeRawResponseHash(rawResponse);
      if (recomputed !== receipt.raw_response_hash) {
        this.failures.push("raw_response_hash_mismatch");
        if (gateRecorder) gateRecorder(report, GATE_CODES_12LANE.GATE_SERVICE_RECEIPT_INCOMPLETE, { lane_key: this.laneKey, step_id: receipt.step_id, errors: ["raw_response_hash_mismatch"] });
        return false;
      }
    } else if (!receipt.raw_response_hash) {
      this.failures.push("missing_raw_response_hash");
      if (gateRecorder) gateRecorder(report, GATE_CODES_12LANE.GATE_SERVICE_RECEIPT_INCOMPLETE, { lane_key: this.laneKey, step_id: receipt.step_id, errors: ["missing_raw_response_hash"] });
      return false;
    }

    // D2/D8: Independent status_hash / result_hash verification.
    // A status_hash must NEVER substitute for a result_hash for AI roles.
    // AI roles require a non-null result_hash (the authoritative /result hash).
    const aiRoles = ["reasoning_generation", "translation_orchestration", "translation_body", "ocr"];
    if (aiRoles.includes(receipt.service_role)) {
      if (!receipt.result_hash) {
        this.failures.push("ai_role_missing_result_hash");
        if (gateRecorder) gateRecorder(report, GATE_CODES_12LANE.GATE_SERVICE_RECEIPT_INCOMPLETE, { lane_key: this.laneKey, step_id: receipt.step_id, errors: ["ai_role_missing_result_hash"] });
        return false;
      }
    }

    // Artifact ownership tracking
    for (const artId of receipt.artifact_ids || []) {
      const prev = this._artifactOwnership.get(artId);
      if (prev && prev !== receipt.step_id && !_isAllowedReuse(prev, receipt.step_id)) {
        this.failures.push(`artifact_cross_step_reuse:${artId}`);
        if (gateRecorder) gateRecorder(report, GATE_CODES_12LANE.GATE_SERVICE_RECEIPT_INCOMPLETE, { lane_key: this.laneKey, step_id: receipt.step_id, errors: [`artifact_cross_step_reuse:${artId}`] });
        return false;
      }
      this._artifactOwnership.set(artId, receipt.step_id);
    }

    this.receipts.push(receipt);
    if (rawResponse) this._rawResponses.set(receipt.step_id, rawResponse);
    return true;
  }

  collect({ stepId, serviceRole, jobResult, responseHeaders, artifactIds, locator, idempotencyKey, statusHash, resultHash }, report, gateRecorder) {
    const receipt = buildServiceReceipt({ laneKey: this.laneKey, stepId, serviceRole, jobResult, responseHeaders, artifactIds, locator, idempotencyKey, statusHash, resultHash });
    return this.add(receipt, jobResult, report, gateRecorder);
  }

  toJSON() { return [...this.receipts]; }
}

function _isAllowedReuse(prev, curr) {
  if (prev.startsWith("section_candidate_") && curr.startsWith("rewrite_")) return true;
  if (curr.startsWith("section_candidate_") && prev.startsWith("rewrite_")) return true;
  if ((prev === "translation_orchestration" && curr === "translation_body") || (curr === "translation_orchestration" && prev === "translation_body")) return true;
  return false;
}

export function serializeReceipts(receipts) { return JSON.stringify(receipts, null, 2); }
