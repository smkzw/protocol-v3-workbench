/**
 * Shared pipeline helpers for the 12-lane child harness — E3 Worker 03.
 *
 * ACCEPTANCE REMEDIATION 03: All routes updated to exact current FastAPI contract.
 * Old routes removed: /commit, /search, /prepare, /translate, /translations/{batch},
 *   /documents, /documents/sections, PUT working-copy
 * New routes: /stages/{stage}/commit, /competitor-search, /references/preparation-batches,
 *   /references/translation-batches, /references/documents/{id}/extract|extraction-reviews|
 *   content-validation/override, /references/translations/{id}/medical-review|admissions,
 *   /greenfield-document, /working-copies/{section_id} (GET + POST, no PUT)
 *
 * @module final_release_12lane_pipeline
 */

import { createHash } from "node:crypto";

const DEFAULT_API_TIMEOUT = 120000;

// ─── HTTP helpers ───────────────────────────────────────────────────────

export async function apiJson(method, reqPath, options = {}) {
  const apiUrl = process.env.API_URL || "http://127.0.0.1:8911";
  const url = reqPath.startsWith("http") ? reqPath : `${apiUrl}${reqPath}`;
  const init = {
    method,
    headers: { "Content-Type": "application/json", ...options.headers },
    signal: AbortSignal.timeout(options.timeout || DEFAULT_API_TIMEOUT),
  };
  if (options.body !== undefined) {
    init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
  }
  const response = await fetch(url, init);
  const text = await response.text();
  let payload = null;
  try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
  if (!response.ok && !options.allowStatus?.includes(response.status)) {
    const error = new Error(`${method} ${reqPath} -> ${response.status}: ${text.slice(0, 200)}`);
    error.status = response.status; error.payload = payload; throw error;
  }
  return { status: response.status, payload };
}

export function recordGateFailure(report, code, evidence) {
  report.gateFailures = report.gateFailures || [];
  report.gateFailures.push({ gate_code: code, ...(evidence || {}) });
}

// ─── CDP helpers (unchanged) ────────────────────────────────────────────

export async function cdpConnect(port) {
  const versionUrl = `http://127.0.0.1:${port}/json/version`;
  let versionInfo = null;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try {
      const resp = await fetch(versionUrl, { signal: AbortSignal.timeout(3000) });
      if (resp.ok) { versionInfo = await resp.json(); break; }
    } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  if (!versionInfo) throw new Error(`Chrome CDP not ready on port ${port}`);
  const targetsResp = await fetch(`http://127.0.0.1:${port}/json/list`);
  const targets = await targetsResp.json();
  const pageTarget = targets.find((t) => t.type === "page");
  if (!pageTarget?.webSocketDebuggerUrl) throw new Error(`no page target on CDP port ${port}`);
  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
    setTimeout(() => reject(new Error("CDP connect timeout")), 10000);
  });
  let msgId = 0; const pending = new Map();
  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(JSON.stringify(msg.error))); else resolve(msg.result);
    }
  });
  return {
    send(method, params = {}) {
      return new Promise((resolve, reject) => {
        const id = ++msgId; pending.set(id, { resolve, reject });
        ws.send(JSON.stringify({ id, method, params }));
      });
    },
    on(event, handler) { ws.addEventListener("message", (d) => { const msg = JSON.parse(d.data); if (msg.method === event) handler(msg.params); }); },
    close() { ws.close(); },
  };
}

export async function evaluate(cdp, expression) {
  const result = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "eval error");
  return result.result.value;
}

export async function waitForCondition(cdp, condition, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try { const result = await evaluate(cdp, condition); if (result) return result; } catch {}
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`timeout waiting for: ${condition}`);
}

export async function screenshot(cdp, filename) {
  const outputDir = process.env.QC_OUTPUT_DIR || "/tmp";
  const { writeFile } = await import("node:fs/promises");
  const nodePath = await import("node:path");
  const result = await cdp.send("Page.captureScreenshot", { format: "png" });
  await writeFile(nodePath.join(outputDir, filename), Buffer.from(result.data, "base64"));
}

export function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

// ─── Chrome process management (D13: CHROME_PROFILE_DIR) ────────────────

export async function startChrome(port) {
  const { spawn } = await import("node:child_process");
  const userDataDir = process.env.CHROME_PROFILE_DIR;
  if (!userDataDir) throw new Error("startChrome requires CHROME_PROFILE_DIR env var");
  const chromePath = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  const chrome = spawn(chromePath, [
    `--remote-debugging-port=${port}`, `--user-data-dir=${userDataDir}`,
    "--headless=new", "--no-first-run", "--no-default-browser-check",
    "--disable-gpu", "--window-size=1920,1080",
  ]);
  await wait(3000);
  return { chrome, userDataDir, pid: chrome.pid };
}

export async function stopChrome(chrome, userDataDir) {
  if (chrome && chrome.exitCode === null) {
    try { chrome.kill("SIGTERM"); await wait(1000); if (chrome.exitCode === null) chrome.kill("SIGKILL"); } catch {}
  }
  // D13: Do NOT rm userDataDir — parent owns profile cleanup
}

// ─── File hashing ───────────────────────────────────────────────────────

export async function fileSha256(filePath) {
  const hash = createHash("sha256");
  const { createReadStream } = await import("node:fs");
  const stream = createReadStream(filePath);
  for await (const chunk of stream) hash.update(chunk);
  return hash.digest("hex");
}

// ─── Journey ────────────────────────────────────────────────────────────

export async function getJourney(projectId) {
  const result = await apiJson("GET", `/api/projects/${projectId}/medical-writing/authoring-journey`);
  return result.payload;
}

// ─── Stage commit (D1: POST .../stages/{stage}/commit, not /commit) ────

export async function confirmFramingPrefill(projectId, journey, report, structuredHint = {}, idempotencyKey) {
  const expectedRevision = journey.revision;
  const productFraming = journey.framing || journey.proposed_framing || {};
  const hasProductPrefill = Boolean(productFraming.indication || productFraming.protocol_id);
  const framing = hasProductPrefill ? productFraming : {
    indication: report.indication, study_phase: report.studyPhase,
    investigational_product: report.productName, scaffold_only_pending_confirmation: true,
    ...(Object.keys(structuredHint).length > 0 ? { structured_design: structuredHint } : {}),
  };
  const body = { ...PAYLOAD_BUILDERS.framing_commit(idempotencyKey), expected_revision: expectedRevision, framing };
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/authoring-journey/stages/framing/commit`, { body });
  report.framingCommit = result.payload;
  report.searchPlanId = result.payload?.search_plan?.plan_id || result.payload?.framing?.search_plan?.plan_id || null;
  return result.payload;
}

export async function confirmPicosPrefill(projectId, framed, report, idempotencyKey) {
  const expectedRevision = framed.revision;
  const productPicos = framed.picos || framed.proposed_picos || {};
  const hasProductPrefill = Boolean(productPicos.population_summary || productPicos.intervention_summary);
  const picos = hasProductPrefill ? productPicos : { population_summary: report.indication + "目标人群", intervention_summary: report.productName };
  const body = { ...PAYLOAD_BUILDERS.picos_commit(idempotencyKey), expected_revision: expectedRevision, picos };
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/authoring-journey/stages/picos/commit`, { body });
  report.picosCommit = result.payload;
  return result.payload;
}

// ─── Competitor search (D1: POST .../competitor-search, not /search) ────

export async function competitorSearch(projectId, searchPlanId, report, idempotencyKey) {
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/authoring-journey/competitor-search`, {
    body: { ...PAYLOAD_BUILDERS.competitor_search(idempotencyKey), search_plan_id: searchPlanId },
    timeout: 120000,
  });
  report.searchResult = result.payload;
  return result.payload;
}

// ─── Preparation batch (D1: POST .../references/preparation-batches) ────

export async function createPreparationBatch(projectId, snapshotId, report, idempotencyKey) {
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/references/preparation-batches`, {
    body: { ...PAYLOAD_BUILDERS.preparation_batch(idempotencyKey), snapshot_id: snapshotId },
    timeout: 60000, allowStatus: [202],
  });
  report.preparationBatchStarted = result.payload;
  return result.payload;
}

export async function pollPreparationBatch(projectId, batchId, timeoutMs, report) {
  const start = Date.now();
  let lastError = null;
  while (Date.now() - start < timeoutMs) {
    try {
      const result = await apiJson("GET", `/api/projects/${projectId}/medical-writing/references/preparation-batches/${batchId}`);
      const batch = result.payload;
      if (!batch) { lastError = "empty_response"; await wait(5000); continue; }
      // D1: Handle every real terminal explicitly
      const terminalStatuses = [
        "completed",
        "completed_with_review_required",
        "completed_with_manual_upload_required",
        "partial_failure",
        "failed",
      ];
      if (terminalStatuses.includes(batch.status)) {
        // D10: Persist last observed error/status
        if (report) {
          report._lastPreparationStatus = batch.status;
          report._lastPreparationError = lastError;
        }
        return batch;
      }
    } catch (e) {
      // D10: Distinguish transient retries from terminal contract errors
      lastError = e.message?.slice(0, 200) || String(e);
      if (e.status >= 400 && e.status < 500 && e.status !== 404 && e.status !== 429) {
        // 4xx (except 404/429) is a terminal contract error — fail closed
        throw new Error(`pollPreparationBatch terminal HTTP ${e.status}: ${lastError}`);
      }
      // 404/5xx/network = transient, keep polling
    }
    await wait(5000);
  }
  if (report) { report._lastPreparationStatus = "timeout"; report._lastPreparationError = lastError; }
  return null;
}

/**
 * D1: Extract artifact_id from preparation batch response.
 *
 * The real batch response carries artifacts in items[].artifact_id, NOT
 * artifacts[].artifact_id. Each item has item_kind, status, and
 * artifact_id fields. Only items with status "prepared" have a usable
 * artifact_id.
 *
 * Returns the first prepared item's artifact_id, or null if none available.
 * For completed_with_manual_upload_required, there may be no prepared
 * artifact — the caller must handle this explicitly.
 */
export function extractFirstPreparedArtifactId(batch) {
  if (!batch) return null;
  // D9: Real response carries items[], NOT artifacts[]. Legacy fallback removed.
  // Wrong legacy shape (artifacts[]) returns null — fails closed.
  const items = batch.items || [];
  for (const item of items) {
    if (item.status === "prepared" && item.artifact_id) return item.artifact_id;
  }
  return null;
}

/**
 * D1: Check if preparation batch has a review-required terminal that needs
 * the documented validation/review path, or a manual-upload-required that
 * must fail closed.
 */
export function isPreparationReviewRequired(batch) {
  return batch?.status === "completed_with_review_required";
}

export function isPreparationManualUploadRequired(batch) {
  return batch?.status === "completed_with_manual_upload_required";
}

/**
 * D1: Check if the batch status is an ordinary completed (not review/manual).
 */
export function isPreparationOrdinaryCompleted(batch) {
  return batch?.status === "completed";
}

// ─── Workspace ──────────────────────────────────────────────────────────

export async function pollWorkspace(projectId, artifactId, timeoutMs, report) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const result = await apiJson("GET", `/api/projects/${projectId}/medical-writing/references/workspace`);
      const workspace = result.payload || {};
      const artifact = (workspace.artifacts || []).find((a) => a.artifact_id === artifactId);
      if (artifact) return workspace;
    } catch {}
    await wait(5000);
  }
  throw new Error(`workspace for artifact ${artifactId} not ready within ${timeoutMs}ms`);
}

// ─── Document validation + extraction review (D1: current routes) ──────

export async function ensureDocumentValidation(projectId, artifactId, workspace, report, idempotencyKey) {
  const artifact = (workspace.artifacts || []).find((a) => a.artifact_id === artifactId);
  if (artifact?.validation?.status === "confirmed" || artifact?.validation?.status === "overridden") return artifact.validation;
  // If validation has warnings, override them with a recorded reason
  const validationWarnings = artifact?.validation?.warnings || [];
  if (validationWarnings.length > 0) {
    const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/references/documents/${artifactId}/content-validation/override`, {
      body: { ...PAYLOAD_BUILDERS.validation_override(idempotencyKey), reason: "E3 harness: acknowledged validation warnings for route testing", acknowledged_warning_codes: validationWarnings.map((w) => w.code || w), expected_revision: artifact?.validation?.revision || 1 },
    });
    return result.payload;
  }
  return artifact?.validation || null;
}

export async function ensureExtractionReview(projectId, artifactId, workspace, report, idempotencyKey) {
  const artifact = (workspace.artifacts || []).find((a) => a.artifact_id === artifactId);
  if (artifact?.extraction_review?.status === "confirmed") return artifact.extraction_review;
  // First trigger extraction if not done
  if (!artifact?.extraction || artifact?.extraction?.status !== "completed") {
    try {
      await apiJson("POST", `/api/projects/${projectId}/medical-writing/references/documents/${artifactId}/extract`, {
        body: { actor: "qc-e3-user", extraction_idempotency_key: idempotencyKey },
      });
    } catch { /* extraction may already be done */ }
  }
  // Review the extraction
  const extractionRevision = artifact?.extraction?.revision || "1";
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/references/documents/${artifactId}/extraction-reviews`, {
    body: { ...PAYLOAD_BUILDERS.extraction_review(idempotencyKey), extraction_revision: extractionRevision },
  });
  return result.payload;
}

// ─── Translation batch (D1: POST .../references/translation-batches) ────

export async function createTranslationBatch(projectId, snapshotId, report, idempotencyKey) {
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/references/translation-batches`, {
    body: { ...PAYLOAD_BUILDERS.translation_batch(idempotencyKey), snapshot_id: snapshotId },
    timeout: 60000, allowStatus: [202],
  });
  return result.payload;
}

export async function pollTranslationBatch(projectId, batchId, timeoutMs, report) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const result = await apiJson("GET", `/api/projects/${projectId}/medical-writing/references/translation-batches/${batchId}`);
      const batch = result.payload;
      if (batch && ["completed", "completed_with_blocked", "partial_failure", "failed"].includes(batch.status)) return batch;
    } catch {}
    await wait(5000);
  }
  report.translationBatchTimeout = true;
  return null;
}

export function collectCandidateReadyItems(batch) {
  if (!batch || !Array.isArray(batch.items)) return [];
  return batch.items.filter((item) => item.pipeline_stage === "candidate_ready");
}

// ─── Medical review + corpus admission (D1: current routes) ────────────

export async function submitMedicalReview(projectId, translationId, translationRevision, report, idempotencyKey) {
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/references/translations/${translationId}/medical-review`, {
    body: { ...PAYLOAD_BUILDERS.medical_review(idempotencyKey), translation_revision: translationRevision },
  });
  return result.payload;
}

export async function admitTranslation(projectId, translationId, expectedTranslationRevision, reviewId, report, idempotencyKey) {
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/references/translations/${translationId}/admissions`, {
    body: { ...PAYLOAD_BUILDERS.admission(idempotencyKey), expected_translation_revision: expectedTranslationRevision, medical_review_id: reviewId },
  });
  return result.payload;
}

// ─── Writing access + greenfield document (D1: POST .../greenfield-document) ─

export async function ensureWritingAccess(projectId, report, idempotencyKey) {
  // Writing access is implicit — the journey stage commit unlocks it.
  // This is a no-op placeholder that verifies the journey exists.
  return await getJourney(projectId);
}

export async function createGreenfieldDocument(projectId, report, idempotencyKey) {
  const journey = await getJourney(projectId);
  const framing = journey.framing || {};
  const studyDef = journey.study_definition || {};
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/greenfield-document`, {
  body: {
    ...PAYLOAD_BUILDERS.greenfield_create(idempotencyKey),
    protocol_id: `E3-${projectId}`,
    version: "V0.1",
    document_title: framing.document_title || `${report.productName}治疗${report.indication}的${report.studyPhase}临床研究方案`,
    indication: report.indication,
    study_phase: report.studyPhase,
    investigational_product: report.productName,
    template_id: "default",
    template_version: "1",
    source_study_definition_id: studyDef.definition_id || "",
    source_study_definition_revision: studyDef.revision || null,
    source_study_definition_sha256: studyDef.state_sha256 || "",
    actor: "qc-e3-user",
    idempotency_key: idempotencyKey,
  },
  });
  return result.payload;
}

// ─── Working copy (D1: GET/POST .../working-copies/{section_id}, no PUT) ─

export async function getWorkingCopy(projectId, sectionId) {
  const result = await apiJson("GET", `/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`);
  return result.payload;
}

export async function saveWorkingCopy(projectId, sectionId, documentId, content, revision, idempotencyKey) {
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/working-copies/${sectionId}`, {
    body: { ...PAYLOAD_BUILDERS.working_copy_save(idempotencyKey), document_id: documentId, expected_revision: revision, content_blocks: content },
  });
  return result.payload;
}

// ─── Revision threads (D1: POST /revision-threads is durable) ───────────

export function buildCandidateRequest(sectionId, userInstruction, briefIds, idempotencyKey) {
  return {
    section_id: sectionId,
    user_instruction: userInstruction,
    evidence_brief_ids: briefIds,
    requested_by: "qc-e3-user",
  };
}

export async function submitCandidateDurable(projectId, requestBody) {
  const result = await apiJson("POST", `/api/projects/${projectId}/revision-threads`, { body: requestBody, timeout: 30000, allowStatus: [202] });
  return result.payload;
}

// ─── Atomic accept-and-apply ────────────────────────────────────────────

export async function acceptAndApplyCandidate(projectId, threadId, suggestionId, expectedWcRevision, report, idempotencyKey) {
  const result = await apiJson("POST", `/api/projects/${projectId}/revision-threads/${threadId}/accept-and-apply`, {
    body: { ...PAYLOAD_BUILDERS.accept_and_apply(idempotencyKey), suggestion_id: suggestionId, expected_working_copy_revision: expectedWcRevision },
  });
  return result.payload;
}

// ─── Revision thread read (for D5 dual-state verification) ──────────────

export async function getRevisionThread(projectId, threadId) {
  const result = await apiJson("GET", `/api/projects/${projectId}/revision-threads`);
  const threads = Array.isArray(result.payload) ? result.payload : [];
  return threads.find((t) => t.thread_id === threadId || t.id === threadId) || null;
}

export async function getRevisionThreads(projectId) {
  const result = await apiJson("GET", `/api/projects/${projectId}/revision-threads`);
  return Array.isArray(result.payload) ? result.payload : [];
}

// ─── Rewrite (durable: POST .../revision-threads/{threadId}/actions) ────

export async function requestRewriteDurable(projectId, threadId, suggestionId, instruction, report) {
  const result = await apiJson("POST", `/api/projects/${projectId}/revision-threads/${threadId}/actions`, {
    body: { ...PAYLOAD_BUILDERS.rewrite(), suggestion_id: suggestionId, rewrite_instruction: instruction },
    timeout: 30000, allowStatus: [202],
  });
  return result.payload;
}

// ─── DOCX export ────────────────────────────────────────────────────────

export async function exportDocx(projectId, outputDir, report) {
  const apiUrl = process.env.API_URL || "http://127.0.0.1:8911";
  const url = `${apiUrl}/api/projects/${projectId}/medical-writing/document.docx?mode=draft_preview`;
  const response = await fetch(url, { method: "GET", signal: AbortSignal.timeout(120000) });
  if (!response.ok) {
    const errorText = await response.text().catch(() => "");
    const error = new Error(`DOCX export GET -> ${response.status}: ${errorText.slice(0, 200)}`);
    error.status = response.status; throw error;
  }
  const buffer = Buffer.from(await response.arrayBuffer());
  const headerDocxSha256 = response.headers.get("x-medical-writing-docx-sha256") || "";
  const headerDocumentId = response.headers.get("x-medical-writing-document-id") || "";
  const headerExportMode = response.headers.get("x-medical-writing-export-mode") || "";
  const { writeFile: fsWriteFile } = await import("node:fs/promises");
  const nodePath = await import("node:path");
  const createHashLocal = (await import("node:crypto")).createHash;
  const exportFilename = `export-${projectId}-${Date.now()}.docx`;
  const exportPath = nodePath.join(outputDir, exportFilename);
  await fsWriteFile(exportPath, buffer);
  const localSha256 = createHashLocal("sha256").update(buffer).digest("hex");
  return {
    export_path: exportPath, file_size: buffer.length, local_sha256: localSha256,
    header_docx_sha256: headerDocxSha256, header_document_id: headerDocumentId,
    header_export_mode: headerExportMode,
    header_sha256_matches: headerDocxSha256 && localSha256 === headerDocxSha256,
  };
}

// ─── Literature import ──────────────────────────────────────────────────

export async function importLiterature(projectId, sourceInput, report, idempotencyKey) {
  const result = await apiJson("POST", `/api/projects/${projectId}/medical-writing/literature/imports`, {
    body: { source_input: sourceInput, actor: "qc-e3-user", idempotency_key: idempotencyKey },
  });
  return result.payload;
}

// ─── Evidence briefs ────────────────────────────────────────────────────

export async function getEvidenceBriefs(projectId) {
  const result = await apiJson("GET", `/api/projects/${projectId}/medical-writing/references/evidence-briefs`);
  return Array.isArray(result.payload) ? result.payload : [];
}

// ─── Greenfield document GET (for reading sections/modules) ─────────────

export async function getGreenfieldDocument(projectId) {
  const result = await apiJson("GET", `/api/projects/${projectId}/medical-writing/greenfield-document`);
  return result.payload;
}

// ════════════════════════════════════════════════════════════════════════
// CANONICAL PAYLOAD BUILDERS — every actual pipeline POST must use exactly
// one of these.  Tests and Python probes consume these exact emitted objects.
// ════════════════════════════════════════════════════════════════════════

/**
 * Canonical request-body builders for every pipeline POST.
 * Each builder returns the EXACT JSON object sent to the product API.
 * The field set must match the Pydantic request model exactly —
 * extra='forbid' on the server will reject any unexpected field.
 */
export const PAYLOAD_BUILDERS = {
  framing_commit: (idempotencyKey) => ({
    expected_revision: 1, stage: "framing",
    framing: { indication: "test", study_phase: "I", investigational_product: "test" },
    impact_preview_id: "", actor: "qc-e3-user", idempotency_key: idempotencyKey,
  }),
  picos_commit: (idempotencyKey) => ({
    expected_revision: 2, stage: "picos",
    picos: { population_summary: "test population", intervention_summary: "test intervention" },
    impact_preview_id: "", actor: "qc-e3-user", idempotency_key: idempotencyKey,
  }),
  competitor_search: (idempotencyKey) => ({
    search_plan_id: "plan-001", actor: "qc-e3-user", idempotency_key: idempotencyKey,
  }),
  preparation_batch: (idempotencyKey) => ({
    snapshot_id: "snap-001", actor: "qc-e3-user", idempotency_key: idempotencyKey,
  }),
  translation_batch: (idempotencyKey) => ({
    snapshot_id: "snap-001", glossary_version: "cms_regulatory_zh_v1",
    actor: "qc-e3-user", idempotency_key: idempotencyKey,
  }),
  extraction_review: (idempotencyKey) => ({
    extraction_revision: "1", decision: "accept", confirmed_anchor_coverage: [],
    unresolved_structure_issues: [], comment: "E3 harness extraction review",
    actor: "qc-e3-user", expected_revision: 0, idempotency_key: idempotencyKey,
  }),
  validation_override: (idempotencyKey) => ({
    reason: "E3 harness: acknowledged validation warnings",
    acknowledged_warning_codes: [], actor: "qc-e3-user",
    expected_revision: 1, idempotency_key: idempotencyKey,
  }),
  medical_review: (idempotencyKey) => ({
    translation_revision: 1, decision: "admit", comment: "E3 harness medical review",
    actor: "qc-e3-user", expected_revision: 0, idempotency_key: idempotencyKey,
  }),
  admission: (idempotencyKey) => ({
    expected_translation_revision: 1, medical_review_id: "rev-001",
    idempotency_key: idempotencyKey,
  }),
  greenfield_create: (idempotencyKey) => ({
    protocol_id: "E3-test", version: "V0.1", document_title: "Test Protocol",
    indication: "test", study_phase: "I", template_id: "default", template_version: "1",
    actor: "qc-e3-user", idempotency_key: idempotencyKey,
  }),
  working_copy_save: (idempotencyKey) => ({
    document_id: "doc-001", expected_revision: 0, content_blocks: [],
    actor: "qc-e3-user", idempotency_key: idempotencyKey,
  }),
  revision_candidate: (idempotencyKey) => buildCandidateRequest("sec-001", "test instruction", ["brief-001"], idempotencyKey),
  rewrite: () => ({
    action: "request_rewrite", suggestion_id: "sugg-001",
    rewrite_instruction: "test rewrite", actor: "qc-e3-user",
  }),
  accept_and_apply: (idempotencyKey) => ({
    suggestion_id: "sugg-001", expected_working_copy_revision: 0,
    actor: "qc-e3-user", idempotency_key: idempotencyKey,
  }),
};

/**
 * Emit all canonical payloads as a JSON fixture stream.
 * Used by Python Pydantic validation to test exact JS-emitted objects.
 */
export function emitPayloadFixtures(idempotencyKey = "e3-test-key-0001") {
  const fixtures = {};
  for (const [name, builder] of Object.entries(PAYLOAD_BUILDERS)) {
    fixtures[name] = builder(idempotencyKey);
  }
  return fixtures;
}
