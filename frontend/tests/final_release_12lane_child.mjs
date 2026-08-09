/**
 * 12-Lane child harness — E3 durable product journey (Worker 03, Acceptance 03).
 *
 * All routes updated to exact current FastAPI contract.
 * D2: completed→fetch /result; D5: dual-state atomic verify; D6: per-step reconciliation;
 * D9: chapter matrix from QC_MIN_CHAPTERS; D10: rewrite through durable + receipt/fail.
 *
 * @module final_release_12lane_child
 */

import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { GATE_CODES, CHAPTER_TARGET_SECTIONS } from "./cross_indication_e2e_config.mjs";
import { GATE_CODES_12LANE } from "./final_release_12lane_config.mjs";
import * as pipeline from "./final_release_12lane_pipeline.mjs";
import {
  DurableMwClient, LaneCheckpoint, extractCandidateArtifact, stableIdempotencyKey,
} from "./final_release_12lane_durable_client.mjs";
import { ReceiptCollector } from "./final_release_12lane_receipts.mjs";
import {
  verifySourceLineage, verifyExportCompletion, verifyCandidateStageComplete,
  verifyAtomicAdoption, commitEvidenceTransaction,
} from "./final_release_12lane_behavior_helpers.mjs";

const ALL_GATE_CODES = { ...GATE_CODES, ...GATE_CODES_12LANE };

if (process.env.QC_ISOLATED_RUNTIME !== "1") throw new Error("requires QC_ISOLATED_RUNTIME=1");
const DRY_RUN = process.env.QC_DRY_RUN === "1";
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");
const appUrl = process.env.APP_URL || "http://127.0.0.1:5174/";
const outputDir = process.env.QC_OUTPUT_DIR || path.join(projectRoot, "runs/execution/mw_e3_live_12lane_harness_20260723/child");
const laneKey = process.env.QC_LANE_KEY || "UNKNOWN";
const LANE_EVIDENCE_DIR = process.env.QC_LANE_EVIDENCE_DIR || path.join(outputDir, laneKey);
const indication = process.env.QC_INDICATION || "Unknown";
const clinicalTrialsConditionTerm = process.env.QC_CLINICALTRIALS_CONDITION_TERM || "Unknown";
const studyPhase = process.env.QC_STUDY_PHASE || "I";
const productName = process.env.QC_PRODUCT_NAME || "Test Drug";
const entryMode = process.env.QC_ENTRY_MODE || "from_zero";
const designPressure = process.env.QC_DESIGN_PRESSURE || "healthy_sad_mad";
const designPressureLabel = process.env.QC_DESIGN_PRESSURE_LABEL || "SAD+MAD";
const interventionRouteClass = process.env.QC_INTERVENTION_ROUTE_CLASS || "small_molecule_oral";
const structuredDesignHint = JSON.parse(process.env.QC_STRUCTURED_DESIGN_HINT || "{}");
const minChapters = JSON.parse(process.env.QC_MIN_CHAPTERS || '["safety","objectives_endpoints"]');
const synopsisSourcePath = process.env.QC_SYNOPSIS_SOURCE_PATH || "";
const synopsisSourceRole = process.env.QC_SYNOPSIS_SOURCE_ROLE || "";
const expectedNctId = process.env.QC_EXPECTED_NCT_ID || "";
const chromeDebugPort = Number(process.env.CHROME_DEBUG_PORT || 9222);
const runtimeDir = process.env.WORKBENCH_RUNTIME_DIR || "";
const projectCode = process.env.QC_PROJECT_CODE || `QC-E3-${laneKey}`;

const journeyTrace = {
  schema_version: "mw_e3_journey_trace_v1", lane_key: laneKey, indication, study_phase: studyPhase,
  entry_mode: entryMode, design_pressure: designPressure, design_pressure_label: designPressureLabel,
  intervention_route_class: interventionRouteClass, product_name: productName, project_code: projectCode,
  mode: DRY_RUN ? "dry-run" : "full", passed: false, steps: [],
};
function traceStep(seq, stage, action, status, evidence = "") {
  journeyTrace.steps.push({ seq, stage, action, status, evidence, timestamp: new Date().toISOString() });
}

const report = {
  schema_version: "mw_e3_child_v1", lane: laneKey, indication, studyPhase, entryMode, designPressure,
  designPressureLabel, interventionRouteClass, productName, mode: DRY_RUN ? "dry-run" : "full",
  passed: false, failures: [], gateFailures: [], projectId: null, initialRevision: null,
  framingCommit: null, picosCommit: null, searchResult: null, preparationBatch: null,
  translationBatch: null, candidateSets: null, chapterMatrix: null, documentExport: null,
  sourceReceipts: [], serviceReceipts: [], literatureImports: [], chromePid: null, resumedFromCheckpoint: false,
};

const laneArtifacts = {
  journey_trace: journeyTrace, source_receipts: [], service_receipts: [], study_definition: {},
  chapter_matrix: {}, candidate_sets: [], citation_qc: {}, browser_qc: [], docx_qc: {},
  synopsis_import_receipt: null, job_locators: {}, step_reconciliations: {}, lane_checkpoint: null,
};

const completedStages = [];
const stageArtifacts = {};
let _checkpointRef = null;
let _allocationAttempt = 0;
let durableClient = null; // D6: module-scoped for post-evidence locator deletion
/**
 * D6: Async stage transition — awaits checkpoint persistence.
 * Caller must await this.
 */
async function markStageComplete(stage, artifacts = {}) {
  if (!completedStages.includes(stage)) completedStages.push(stage);
  stageArtifacts[stage] = { ...artifacts, completed_at: new Date().toISOString() };
  // D6: Await checkpoint persistence after every successful stage transition
  if (_checkpointRef) {
    await _checkpointRef.save({
      projectId: _checkpointRef.data?.project_id || "",
      sourceMode: _checkpointRef.data?.source_mode || "",
      journeyRevision: _checkpointRef.data?.journey_revision || 0,
      sourceSha: _checkpointRef.data?.source_sha || "",
      allocationAttempt: _allocationAttempt,
      completedStages: [...completedStages],
      stageArtifacts: { ...stageArtifacts },
    });
  }
}

async function main() {
  await mkdir(outputDir, { recursive: true });
  const pageErrors = [];
  const httpFailures = [];
  const receiptCollector = new ReceiptCollector(laneKey);
  const checkpoint = new LaneCheckpoint({ laneKey, evidenceDir: LANE_EVIDENCE_DIR, runtimeDir, projectCode });
  _checkpointRef = checkpoint; // D6: for per-stage persistence
  // D2: Read parent-provided allocation attempt
  _allocationAttempt = parseInt(process.env.QC_ALLOCATION_ATTEMPT || "0", 10);
  // D3: Fail closed on checkpoint load failure — do NOT continue into Chrome/project mutation
  try { await checkpoint.load(); } catch (e) {
    console.error(`FATAL: checkpoint load failed, cannot continue: ${e.message}`);
    process.exit(1);
  }

  const { chrome, userDataDir, pid } = await pipeline.startChrome(chromeDebugPort);
  report.chromePid = pid;
  let cdp = null;

  try {
    cdp = await pipeline.cdpConnect(chromeDebugPort);
    cdp.on("Runtime.exceptionThrown", (e) => pageErrors.push(e.exceptionDetails?.exception?.description || e.exceptionDetails?.text));
    cdp.on("Network.responseReceived", (e) => { if (e.response.status >= 400) httpFailures.push({ url: e.response.url, status: e.response.status }); });
    await cdp.send("Page.enable"); await cdp.send("Runtime.enable"); await cdp.send("Network.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
    await cdp.send("Page.navigate", { url: appUrl });
    await pipeline.waitForCondition(cdp, `document.body.textContent.includes("项目总看板")`);
    await pipeline.screenshot(cdp, "dashboard_loaded.png");

    // D5: Resume or create project
    let projectId;
    if (checkpoint.hasProject() && !DRY_RUN) {
      projectId = checkpoint.getProjectId();
      report.projectId = projectId;
      report.resumedFromCheckpoint = true;
      traceStep(1, "project_creation", "resume_from_checkpoint", "completed", `project_id=${projectId}`);
      const listResult = await pipeline.apiJson("GET", `/api/projects`);
      if (!(listResult.payload || []).some((p) => p.project_id === projectId)) throw new Error(`checkpoint project ${projectId} not found in API`);
    } else {
      traceStep(1, "project_creation", "navigate_to_new_project_dialog", "started");
      projectId = await createProjectViaUi(cdp, report);
      report.projectId = projectId;
      traceStep(2, "project_creation", "project_created_via_ui", "completed", `project_id=${projectId}`);
    }

    // Verify entry-mode
    const listResult = await pipeline.apiJson("GET", `/api/projects`);
    const projectData = (listResult.payload || []).find((p) => p.project_id === projectId);
    const projectSourceMode = projectData?.source_mode || "";
    const expectedSourceMode = entryMode === "synopsis_import" ? "user_created_synopsis_import" : "user_created_from_zero";
    if (projectSourceMode !== expectedSourceMode) {
      pipeline.recordGateFailure(report, ALL_GATE_CODES.ENTRY_MODE_MISMATCH, { expected: expectedSourceMode, actual: projectSourceMode });
      report.failures.push(`entry_mode_mismatch: expected ${expectedSourceMode}, got ${projectSourceMode}`);
    }
    traceStep(3, "project_creation", "source_mode_verified", projectSourceMode === expectedSourceMode ? "passed" : "failed", `source_mode=${projectSourceMode}`);

    const journey = await pipeline.getJourney(projectId);
    report.initialRevision = journey.revision;
    const sourceSha = synopsisSourcePath ? await pipeline.fileSha256(synopsisSourcePath).catch(() => "") : "";
    // D3: Compare checkpoint source hash with current synopsis hash using shared verifier
    if (checkpoint.data?.source_sha && sourceSha) {
      verifySourceLineage(checkpoint.data, sourceSha);
    }

    // D2+D3: Rehydrate durable state from checkpoint if resuming
    // D3: Re-fetch authoritative GET endpoints for downstream state
    if (checkpoint.data) {
      const cp = checkpoint.data;
      // D2: Validate project code, project ID, runtime, lane, entry mode, source hash
      if (cp.project_code && cp.project_code !== projectCode) throw new Error(`checkpoint project_code mismatch: ${cp.project_code} != ${projectCode}`);
      if (cp.runtime_dir && runtimeDir && cp.runtime_dir !== runtimeDir) throw new Error(`checkpoint runtime_dir mismatch: ${cp.runtime_dir} != ${runtimeDir}`);
      if (cp.source_mode && cp.source_mode !== expectedSourceMode) throw new Error(`checkpoint source_mode mismatch: ${cp.source_mode} != ${expectedSourceMode}`);
      // D2: Rehydrate completed stages and stage artifacts into local state
      for (const s of (cp.completed_stages || [])) { if (!completedStages.includes(s)) completedStages.push(s); }
      Object.assign(stageArtifacts, cp.stage_artifacts || {});
      // D3: Re-fetch authoritative state from GET endpoints
      const resumedJourney = await pipeline.getJourney(projectId);
      report.initialRevision = resumedJourney.revision;
      if (cp.stage_artifacts?.framing) report.framingCommit = resumedJourney;
      if (cp.stage_artifacts?.picos) report.picosCommit = resumedJourney;
      // D3: Re-fetch search snapshot if competitor_search completed
      if (completedStages.includes("competitor_search") && cp.stage_artifacts?.competitor_search?.snapshot_id) {
        const snapResult = await pipeline.apiJson("GET", `/api/projects/${projectId}/medical-writing/references/search-snapshots/${cp.stage_artifacts.competitor_search.snapshot_id}`);
        // D4: A stage may only remain skipped when its complete authoritative artifact has been re-fetched.
        // ID-only fallbacks are prohibited — fail closed on re-fetch failure.
        report.searchResult = snapResult.payload;
        if (!report.searchResult?.snapshot?.studies && !report.searchResult?.studies) {
          throw new Error(`resume re-fetch of search snapshot ${cp.stage_artifacts.competitor_search.snapshot_id} returned no studies — cannot continue with partial state`);
        }
      }
      // D3: Re-fetch preparation batch if completed
      if (completedStages.includes("preparation") && cp.stage_artifacts?.preparation?.batch_id) {
        const prepResult = await pipeline.apiJson("GET", `/api/projects/${projectId}/medical-writing/references/preparation-batches/${cp.stage_artifacts.preparation.batch_id}`);
        report.preparationBatch = prepResult.payload;
        report._firstPreparedArtifactId = pipeline.extractFirstPreparedArtifactId(prepResult.payload);
        if (!report.preparationBatch?.items) {
          throw new Error(`resume re-fetch of preparation batch ${cp.stage_artifacts.preparation.batch_id} returned no items — cannot continue with partial state`);
        }
      }
      // D3: Re-fetch translation batch if completed
      if (completedStages.includes("translation") && cp.stage_artifacts?.translation?.batch_id) {
        const transResult = await pipeline.apiJson("GET", `/api/projects/${projectId}/medical-writing/references/translation-batches/${cp.stage_artifacts.translation.batch_id}`);
        report.translationBatch = transResult.payload;
        if (!report.translationBatch?.items) {
          throw new Error(`resume re-fetch of translation batch ${cp.stage_artifacts.translation.batch_id} returned no items — cannot continue with partial state`);
        }
      }
      // D3: Re-fetch greenfield document if writing_access completed
      if (completedStages.includes("writing_access") && cp.stage_artifacts?.writing_access?.document_id) {
        const docResult = await pipeline.apiJson("GET", `/api/projects/${projectId}/medical-writing/greenfield-document`);
        report.documentId = docResult.payload?.document?.document_id || docResult.payload?.document_id;
        report.documentSections = docResult.payload?.document?.sections || docResult.payload?.sections || [];
        if (!report.documentSections.length) {
          throw new Error(`resume re-fetch of greenfield document returned no sections — cannot continue with partial state`);
        }
      }
    }

    // D2+D6: Per-stage checkpoint save — persist after project_creation
    await checkpoint.save({ projectId, sourceMode: projectSourceMode, journeyRevision: journey.revision, sourceSha, completedStages, stageArtifacts });
    await markStageComplete("project_creation", { project_id: projectId });

    durableClient = new DurableMwClient({ projectId, laneKey, evidenceDir: LANE_EVIDENCE_DIR, apiJson: pipeline.apiJson, gateRecorder: pipeline.recordGateFailure, report });
    await durableClient.loadLocators();

    // Synopsis import
    if (entryMode === "synopsis_import" && synopsisSourcePath) {
      traceStep(4, "synopsis_import", "source_file_hash", "started");
      const sourceSha256 = await pipeline.fileSha256(synopsisSourcePath);
      laneArtifacts.synopsis_import_receipt = { source_path: synopsisSourcePath, source_sha256: sourceSha256, declared_role: synopsisSourceRole, source_exists: true };
      traceStep(4, "synopsis_import", "source_file_hashed", "completed", `sha256=${sourceSha256.slice(0, 16)}...`);
      if (!DRY_RUN) {
        traceStep(5, "synopsis_import", "durable_upload_and_poll", "started");
        const synKey = stableIdempotencyKey(laneKey, projectId, "synopsis_import");
        const synopsisResult = await durableClient.startSynopsisImport(async (stableKey) => {
          const fileBuffer = await readFile(synopsisSourcePath);
          const formData = new FormData();
          formData.append("file", new Blob([fileBuffer]), path.basename(synopsisSourcePath));
          formData.append("expected_revision", String(journey.revision));
          formData.append("actor", "qc-e3-user");
          formData.append("idempotency_key", stableKey);
          const apiUrl = process.env.API_URL || "http://127.0.0.1:8911";
          const response = await fetch(`${apiUrl}/api/projects/${projectId}/medical-writing/authoring-journey/synopsis-import`, { method: "POST", body: formData, signal: AbortSignal.timeout(parseInt(process.env.SYNOPSIS_UPLOAD_TIMEOUT_MS || "1200000", 10)) });
          const text = await response.text();
          let payload = null; try { payload = JSON.parse(text); } catch { payload = text; }
          if (!response.ok && response.status !== 202) throw new Error(`synopsis-import start failed: ${response.status}: ${text.slice(0, 200)}`);
          return payload;
        }, synKey, parseInt(process.env.SYNOPSIS_UPLOAD_TIMEOUT_MS || "1200000", 10));
        if (synopsisResult) {
          laneArtifacts.synopsis_import_receipt.durable_result = synopsisResult;
          const synLocator = durableClient.getLocator("synopsis_import");
          receiptCollector.collect({ stepId: "synopsis_import", serviceRole: "reasoning_generation", jobResult: synopsisResult, locator: synLocator, idempotencyKey: synKey, statusHash: synLocator?.status_hash, resultHash: synLocator?.result_hash }, report, pipeline.recordGateFailure);
          traceStep(5, "synopsis_import", "durable_upload_and_poll", "completed", `status=${synopsisResult.revision ? "review_ready" : "unknown"}`);
          await markStageComplete("synopsis_import", { idempotency_key: synKey });
        } else { traceStep(5, "synopsis_import", "durable_upload_and_poll", "timeout", "synopsis import timed out"); }
      } else { traceStep(5, "synopsis_import", "durable_upload_skipped_dry_run", "skipped_dry_run", "dry-run"); }
    } else if (entryMode === "synopsis_import" && !synopsisSourcePath) {
      pipeline.recordGateFailure(report, ALL_GATE_CODES.SYNOPSIS_FILE_MISSING, { lane: laneKey });
      report.failures.push("synopsis_import lane has no source file");
    }

    if (DRY_RUN) return await finishDryRun(cdp, pageErrors, httpFailures, receiptCollector, checkpoint);

    // FULL MODE
    // Framing (stages/framing/commit)
    if (!completedStages.includes("framing")) {
      traceStep(7, "framing", "confirm_product_prefill", "started");
      const framingKey = stableIdempotencyKey(laneKey, projectId, "framing");
      const framed = await pipeline.confirmFramingPrefill(projectId, journey, report, structuredDesignHint, framingKey);
      report.framingCommit = framed;
      laneArtifacts.study_definition = { framing: framed?.framing || null, structured_design: structuredDesignHint, design_pressure: designPressure };
      traceStep(7, "framing", "confirm_product_prefill", "completed", `revision=${framed?.revision}`);
      if (!report.searchPlanId) throw new Error("framing commit did not return search plan");
      await markStageComplete("framing", { revision: framed?.revision });
    }

    // PICOS (stages/picos/commit)
    if (!completedStages.includes("picos")) {
      traceStep(8, "picos", "confirm_product_prefill", "started");
      const picosKey = stableIdempotencyKey(laneKey, projectId, "picos");
      const picosResult = await pipeline.confirmPicosPrefill(projectId, report.framingCommit || await pipeline.getJourney(projectId), report, picosKey);
      report.picosCommit = picosResult;
      traceStep(8, "picos", "confirm_product_prefill", "completed", `revision=${picosResult?.revision}`);
      await markStageComplete("picos", { revision: picosResult?.revision });
    }

    // Competitor search (competitor-search)
    if (!completedStages.includes("competitor_search")) {
      traceStep(9, "competitor_search", "product_ctgov_search", "started");
      const searchKey = stableIdempotencyKey(laneKey, projectId, "competitor_search");
      const searchResult = await pipeline.competitorSearch(projectId, report.searchPlanId, report, searchKey);
      report.searchResult = searchResult;
      const snapshot = searchResult.snapshot || searchResult;
      if (!snapshot?.snapshot_id) throw new Error("competitor search returned no snapshot");
      traceStep(9, "competitor_search", "product_ctgov_search", "completed", `snapshot_id=${snapshot.snapshot_id}`);
      receiptCollector.collect({ stepId: "competitor_search", serviceRole: "ctgov", jobResult: searchResult, artifactIds: [snapshot.snapshot_id] }, report, pipeline.recordGateFailure);
      await markStageComplete("competitor_search", { snapshot_id: snapshot.snapshot_id });
    }

    const snapshot = report.searchResult?.snapshot || report.searchResult;
    const foundStudy = (snapshot?.studies || []).find((s) => s.nct_id === expectedNctId);
    if (!foundStudy && expectedNctId) {
      report.failures.push(`expected sentinel ${expectedNctId} not found`);
      pipeline.recordGateFailure(report, ALL_GATE_CODES.SENTINEL_NCT_REUSED_WRONG_LANE, { expected_nct: expectedNctId, found_ncts: (snapshot?.studies || []).slice(0, 10).map((s) => s.nct_id) });
    } else if (expectedNctId) traceStep(10, "competitor_search", "sentinel_rediscovered", "passed", `nct_id=${expectedNctId}`);

    // Preparation batch (references/preparation-batches)
    if (!completedStages.includes("preparation")) {
      traceStep(11, "preparation", "create_preparation_batch", "started");
      const prepKey = stableIdempotencyKey(laneKey, projectId, "preparation");
      const prepBatchInit = await pipeline.createPreparationBatch(projectId, snapshot.snapshot_id, report, prepKey);
      const preparationBatch = await pipeline.pollPreparationBatch(projectId, prepBatchInit.batch_id, Number(process.env.QC_OCR_TIMEOUT_S || 600) * 1000, report);
      report.preparationBatch = preparationBatch;
      if (!preparationBatch) throw new Error("preparation batch timed out");
      if (["failed", "partial_failure"].includes(preparationBatch.status)) throw new Error(`preparation batch failed: ${preparationBatch.status}`);

      // D1: Handle review-required and manual-upload-required explicitly
      if (pipeline.isPreparationReviewRequired(preparationBatch)) {
        traceStep(11, "preparation", "review_required_entering_validation_path", "started");
        // Review-required must enter the documented validation/review path
        // The artifact extraction + validation + extraction review will handle it
      } else if (pipeline.isPreparationManualUploadRequired(preparationBatch)) {
        // D1: manual-upload-required must fail closed unless a real artifact is available
        const artifactId = pipeline.extractFirstPreparedArtifactId(preparationBatch);
        if (!artifactId) {
          throw new Error(`preparation completed_with_manual_upload_required but no prepared artifact available — cannot proceed without manual upload`);
        }
      }

      // D1: Extract artifact from items[].artifact_id, not artifacts[].artifact_id
      const firstArtifactId = pipeline.extractFirstPreparedArtifactId(preparationBatch);
      if (!firstArtifactId && pipeline.isPreparationOrdinaryCompleted(preparationBatch)) {
        throw new Error("preparation completed but no prepared artifact_id found in items[]");
      }
      report._firstPreparedArtifactId = firstArtifactId;

      traceStep(11, "preparation", "ocr_pipeline_completed", "completed", `status=${preparationBatch.status}, artifact=${firstArtifactId || "none"}`);
      receiptCollector.collect({ stepId: "ocr_preparation", serviceRole: "ocr", jobResult: preparationBatch, artifactIds: firstArtifactId ? [firstArtifactId] : [] }, report, pipeline.recordGateFailure);
      await markStageComplete("preparation", { batch_id: prepBatchInit.batch_id, artifact_id: firstArtifactId });
    }

    // Workspace validation + extraction review
    if (!completedStages.includes("validation")) {
      traceStep(12, "validation", "workspace_poll", "started");
      const firstArtifactId = report._firstPreparedArtifactId || pipeline.extractFirstPreparedArtifactId(report.preparationBatch);
      if (firstArtifactId) {
        const workspace = await pipeline.pollWorkspace(projectId, firstArtifactId, 600000, report);
        const valKey = stableIdempotencyKey(laneKey, projectId, "validation", firstArtifactId);
        const extKey = stableIdempotencyKey(laneKey, projectId, "extraction_review", firstArtifactId);
        await pipeline.ensureDocumentValidation(projectId, firstArtifactId, workspace, report, valKey);
        await pipeline.ensureExtractionReview(projectId, firstArtifactId, workspace, report, extKey);
      } else {
        // D1: No prepared artifact — cannot validate
        pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PARTIAL_CHAPTER_SAMPLE, { reason: "no_prepared_artifact_for_validation" });
        report.failures.push("no prepared artifact for validation/extraction");
      }
      traceStep(13, "validation", "validation_and_extraction_completed", "completed");
      await markStageComplete("validation");
    }

    if (foundStudy) {
      const provenArtifactId = report._firstPreparedArtifactId || pipeline.extractFirstPreparedArtifactId(report.preparationBatch);
      report.sourceReceipts.push({ nct_id: foundStudy.nct_id, study_title: foundStudy.brief_title || foundStudy.title || "", phase: foundStudy.phase || "", condition: foundStudy.condition || indication, snapshot_id: snapshot.snapshot_id, artifact_id: provenArtifactId, timestamp: new Date().toISOString() });
    }

    // Translation batch (references/translation-batches)
    if (!completedStages.includes("translation")) {
      traceStep(14, "translation", "create_batch", "started");
      const transKey = stableIdempotencyKey(laneKey, projectId, "translation");
      const transBatchInit = await pipeline.createTranslationBatch(projectId, snapshot.snapshot_id, report, transKey);
      const translationBatch = await pipeline.pollTranslationBatch(projectId, transBatchInit.batch_id, Number(process.env.QC_TRANSLATION_TIMEOUT_S || 900) * 1000, report);
      report.translationBatch = translationBatch;
      if (!translationBatch || report.translationBatchTimeout) throw new Error("translation batch timed out or failed");
      traceStep(14, "translation", "batch_completed", "completed", `status=${translationBatch.status}`);
      receiptCollector.collect({ stepId: "translation_orchestration", serviceRole: "translation_orchestration", jobResult: translationBatch }, report, pipeline.recordGateFailure);
      receiptCollector.collect({ stepId: "translation_body", serviceRole: "translation_body", jobResult: translationBatch }, report, pipeline.recordGateFailure);
      await markStageComplete("translation", { batch_id: transBatchInit.batch_id });
    }

    // Corpus admission for ALL items (references/translations/{id}/medical-review + admissions)
    const candidateItems = pipeline.collectCandidateReadyItems(report.translationBatch);
    if (candidateItems.length === 0) throw new Error("no candidate-ready items from translation");
    const chapterMapping = [];
    for (const item of candidateItems) {
      const anchor = item.ich_m11_anchor || item.anchor || "unknown";
      const reviewStage = `corpus_review_${anchor}`;
      if (!completedStages.includes(reviewStage)) {
        const reviewKey = stableIdempotencyKey(laneKey, projectId, "medical_review", item.translation_id);
        const review = await pipeline.submitMedicalReview(projectId, item.translation_id, item.translation_revision, report, reviewKey);
        const admitKey = stableIdempotencyKey(laneKey, projectId, "admission", item.translation_id);
        const admission = await pipeline.admitTranslation(projectId, item.translation_id, item.translation_revision, review.review_id || review.medical_review_id, report, admitKey);
        chapterMapping.push({ brief_id: admission.brief_id, ich_m11_anchor: anchor, translation_id: item.translation_id });
        await markStageComplete(reviewStage, { brief_id: admission.brief_id });
      }
    }
    laneArtifacts.chapter_matrix = { chapters: chapterMapping, total_items: candidateItems.length, anchors: chapterMapping.map((m) => m.ich_m11_anchor) };

    // Greenfield document (POST /greenfield-document)
    if (!completedStages.includes("writing_access")) {
      traceStep(16, "writing_access", "create_greenfield_document", "started");
      const docKey = stableIdempotencyKey(laneKey, projectId, "greenfield_document");
      const createdDocument = await pipeline.createGreenfieldDocument(projectId, report, docKey);
      report.documentId = createdDocument?.document?.document_id || createdDocument?.document_id;
      report.documentSections = createdDocument?.document?.sections || createdDocument?.sections || [];
      traceStep(16, "writing_access", "document_created", "completed", `document_id=${report.documentId}, sections=${report.documentSections.length}`);
      await markStageComplete("writing_access", { document_id: report.documentId });
    }

    // D7: Chapter matrix from QC_MIN_CHAPTERS + document sections
    const documentSections = report.documentSections || [];
    const expectedIncluded = [];
    const excludedChapters = [];
    for (const anchor of minChapters) {
      const targetSection = documentSections.find((s) => s.template_node_id === CHAPTER_TARGET_SECTIONS[anchor]);
      const mapping = chapterMapping.find((m) => m.ich_m11_anchor === anchor);
      if (targetSection) {
        expectedIncluded.push({ anchor, section_id: targetSection.section_id, brief_id: mapping?.brief_id || "", template_node_id: targetSection.template_node_id });
      } else {
        // D7: A missing required chapter mapping is NOT an automatic exclusion.
        // It must fail GATE_PARTIAL_CHAPTER_SAMPLE — never silently skip.
        pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PARTIAL_CHAPTER_SAMPLE, { anchor, reason: "required_chapter_has_no_document_section" });
        report.failures.push(`required chapter ${anchor} has no matching document section — not an automatic exclusion`);
        excludedChapters.push({ anchor, reason: `FAIL_CLOSED: required chapter ${anchor} not found in ${documentSections.length} sections` });
      }
    }
    // D7: Require at least one included real section
    if (expectedIncluded.length === 0) {
      pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PARTIAL_CHAPTER_SAMPLE, { reason: "zero_included_sections_from_min_chapters" });
      report.failures.push("zero included sections from QC_MIN_CHAPTERS — cannot proceed");
    }

    // Section candidates — ALL included chapters, durable + atomic
    traceStep(17, "candidates", "durable_candidate_loop", "started");
    const candidateSets = [];
    let rewriteCompleted = false;

    for (const incl of expectedIncluded) {
      const stepId = `candidate_${incl.section_id}`;
      const before = await pipeline.getWorkingCopy(projectId, incl.section_id);
      const candidateKey = stableIdempotencyKey(laneKey, projectId, "candidate", incl.section_id);
      const candidateTimeout = Number(process.env.QC_CANDIDATE_TIMEOUT_S || 900) * 1000;
      let jobResult;
      try {
        jobResult = await durableClient.startAndPoll(stepId, `/api/projects/${projectId}/revision-threads`, (key) => pipeline.buildCandidateRequest(incl.section_id, `基于已准入的${incl.anchor}竞品方案证据，为${indication}${studyPhase}研究生成3-5个监管中文候选；不得补造剂量、阈值、时点或统计假设。`, incl.brief_id ? [incl.brief_id] : [], key), { timeoutMs: candidateTimeout });
      } catch (e) {
        if (e.needsRetry) { traceStep(17, "candidates", `retry_${incl.anchor}`, "started"); jobResult = await durableClient.retry(stepId, { timeoutMs: candidateTimeout }); }
        else throw e;
      }
      if (!jobResult || jobResult.status === "failed") {
        report.failures.push(`candidate generation failed for ${incl.anchor}`);
        pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PARTIAL_CHAPTER_SAMPLE, { anchor: incl.anchor, reason: "candidate_generation_failed" });
        continue;
      }

      let artifact;
      try { artifact = extractCandidateArtifact(jobResult); } catch (extractError) {
        report.failures.push(`artifact extraction failed: ${extractError.message}`);
        pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PARTIAL_CHAPTER_SAMPLE, { anchor: incl.anchor, reason: extractError.message });
        continue;
      }
      const { thread_id, suggestion_ids } = artifact;
      if (suggestion_ids.length < 3 || suggestion_ids.length > 5) pipeline.recordGateFailure(report, ALL_GATE_CODES.CANDIDATE_COUNT_OUT_OF_RANGE, { anchor: incl.anchor, count: suggestion_ids.length });

      const candLocator = durableClient.getLocator(stepId);
      receiptCollector.collect({ stepId: `section_candidate_${incl.anchor}`, serviceRole: "reasoning_generation", jobResult, artifactIds: [thread_id, ...suggestion_ids], locator: candLocator, idempotencyKey: candidateKey, statusHash: candLocator?.status_hash, resultHash: candLocator?.result_hash }, report, pipeline.recordGateFailure);

      // D4: Atomic adoption with dual-state verification
      // Response is MedicalWritingRevisionApplyResult with nested working_copy
      const selectedSuggestionId = suggestion_ids[0];
      const wcRevision = before.revision || 0;
      const adoptKey = stableIdempotencyKey(laneKey, projectId, "accept_apply", incl.section_id);
      const adoptResult = await pipeline.acceptAndApplyCandidate(projectId, thread_id, selectedSuggestionId, wcRevision, report, adoptKey);

      // D4: Extract from nested working_copy, not flat fields
      const adoptWc = adoptResult?.working_copy || {};
      const adoptWcRevision = adoptWc.revision;
      const adoptWcId = adoptWc.working_copy_id;
      const adoptContentHash = adoptWc.content_sha256 || adoptWc.source_working_copy_content_sha256;

      // D4: Re-read authoritative state
      const after = await pipeline.getWorkingCopy(projectId, incl.section_id);
      const rereadThread = await pipeline.getRevisionThread(projectId, thread_id);

      // D10: Atomic adoption verification using shared verifier
      const adoptVerified = verifyAtomicAdoption({
        adoptResult: adoptResult, threadId, selectedSuggestionId, before, after,
        rereadThread, sectionId: incl.section_id,
      });
      const allVerified = adoptVerified.allVerified;

      if (!allVerified) {
        const failedChecks = Object.entries(adoptVerified).filter(([, v]) => !v).map(([k]) => k);
        report.failures.push(`atomic adoption verification failed for ${incl.anchor}: ${failedChecks.join(",")}`);
        pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PRODUCT_AI_SUBSTITUTION, { anchor: incl.anchor, reason: `verification_failed: ${failedChecks.join(",")}` });
      }

      candidateSets.push({
        section_id: incl.section_id, anchor: incl.anchor, thread_id, candidate_count: suggestion_ids.length,
        all_suggestion_ids: suggestion_ids, accepted_suggestion_id: selectedSuggestionId,
        working_copy_hash_before: before.content_sha256, working_copy_hash_after: after.content_sha256,
        atomic_adopt_revision: adoptWcRevision,
        atomic_adopt_wc_id: adoptWcId,
        atomic_adopt_verified: allVerified, adopt_verification: adoptVerified,
      });
      traceStep(17, "candidates", `atomic_adopt_${incl.anchor}`, "completed", `thread=${thread_id}, suggestions=${suggestion_ids.length}`);

      // D8: Rewrite through durable client — at least one per lane
      // D8: Require authoritative /result, server receipt, resulting thread state
      if (!rewriteCompleted && suggestion_ids.length > 1) {
        const rewriteStepId = `rewrite_${incl.section_id}`;
        const rewriteKey = stableIdempotencyKey(laneKey, projectId, "rewrite", incl.section_id);
        traceStep(17.5, "rewrite", `durable_rewrite_${incl.anchor}`, "started");
        try {
          const rewriteResult = await durableClient.startAndPoll(rewriteStepId, `/api/projects/${projectId}/revision-threads/${thread_id}/actions`, (key) => ({ action: "request_rewrite", suggestion_id: selectedSuggestionId, rewrite_instruction: "请基于同一证据简报，调整表述方式，保持数据和结论不变。", actor: "qc-e3-user" }), { timeoutMs: candidateTimeout });
          // D8: Require authoritative /result — status alone does not satisfy
          if (rewriteResult && rewriteResult.status === "completed") {
            const rewriteLocator = durableClient.getLocator(rewriteStepId);
            // D8: Require result_hash from /result
            if (rewriteLocator?.result_hash) {
              receiptCollector.collect({ stepId: `rewrite_${incl.anchor}`, serviceRole: "reasoning_generation", jobResult: rewriteResult, artifactIds: [thread_id], locator: rewriteLocator, idempotencyKey: rewriteKey, statusHash: rewriteLocator?.status_hash, resultHash: rewriteLocator?.result_hash }, report, pipeline.recordGateFailure);
              rewriteCompleted = true;
              traceStep(17.5, "rewrite", `durable_rewrite_${incl.anchor}`, "completed", `job_id=${rewriteResult.job_id || "cached"}`);
            } else {
              report.failures.push(`rewrite completed but no result_hash for ${incl.anchor}`);
              traceStep(17.5, "rewrite", `durable_rewrite_${incl.anchor}`, "failed", "no result_hash");
            }
          } else {
            report.failures.push(`rewrite failed for ${incl.anchor}: status=${rewriteResult?.status}`);
            traceStep(17.5, "rewrite", `durable_rewrite_${incl.anchor}`, "failed", `status=${rewriteResult?.status}`);
          }
        } catch (rewriteErr) {
          if (rewriteErr.needsRetry) {
            // D8: Retry must also check result, not just set completed
            const retryResult = await durableClient.retry(rewriteStepId, { timeoutMs: candidateTimeout });
            if (retryResult && retryResult.status === "completed") {
              const retryLocator = durableClient.getLocator(rewriteStepId);
              if (retryLocator?.result_hash) {
                receiptCollector.collect({ stepId: `rewrite_${incl.anchor}`, serviceRole: "reasoning_generation", jobResult: retryResult, artifactIds: [thread_id], locator: retryLocator, idempotencyKey: rewriteKey, statusHash: retryLocator?.status_hash, resultHash: retryLocator?.result_hash }, report, pipeline.recordGateFailure);
                rewriteCompleted = true;
              }
            }
          } else { report.failures.push(`rewrite error: ${rewriteErr.message?.slice(0, 100)}`); traceStep(17.5, "rewrite", `durable_rewrite_${incl.anchor}`, "failed", rewriteErr.message?.slice(0, 100)); }
        }
      }

      // D5: Save per-step reconciliation record
      // D5: Only set reconciled=true when ALL verification passed
      await durableClient.saveReconciliation(stepId, {
        idempotency_key: candidateKey, status_hash: candLocator?.status_hash, result_hash: candLocator?.result_hash,
        artifact_locator: candLocator?.artifact_locator, thread_id, suggestion_ids,
        adopt_result: { thread_id: adoptResult?.thread_id, suggestion_id: adoptResult?.suggestion_id, working_copy_revision: adoptWcRevision },
        reread_wc: { content_sha256: after.content_sha256, revision: after.revision, working_copy_id: after.working_copy_id },
        adopt_verified: allVerified, rewrite_completed: rewriteCompleted,
        reconciled: allVerified, // D5: only true when verification actually passed
      });
      // D5: clearLocator only marks reconciled when explicitly confirmed
      await durableClient.clearLocator(stepId, { reconciled: allVerified });
    }

    // D10: Require at least one completed rewrite per full lane
    if (!rewriteCompleted && expectedIncluded.length > 0) {
      pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PARTIAL_CHAPTER_SAMPLE, { reason: "no_completed_rewrite_in_full_lane" });
      report.failures.push("no completed rewrite in full lane");
    }

    report.candidateSets = candidateSets;
    laneArtifacts.candidate_sets = candidateSets;
    if (excludedChapters.length > 0) laneArtifacts.excluded_chapters = excludedChapters;
    traceStep(17, "candidates", "durable_candidate_loop_completed", "completed", `sets=${candidateSets.length}, excluded=${excludedChapters.length}`);

    // D9: All-chapter fail-closed
    for (const incl of expectedIncluded) {
      const cs = candidateSets.find((c) => c.section_id === incl.section_id);
      if (!cs) { pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PARTIAL_CHAPTER_SAMPLE, { anchor: incl.anchor, reason: "included_chapter_has_no_candidate_set" }); report.failures.push(`included chapter ${incl.anchor} has no candidate set`); }
      else if (!cs.atomic_adopt_verified) { pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PRODUCT_AI_SUBSTITUTION, { anchor: incl.anchor, reason: "atomic_adoption_not_verified" }); report.failures.push(`included chapter ${incl.anchor} atomic adoption not verified`); }
    }
    // D11: Mark candidates complete using shared verifier — exact coverage, no extras
    if (verifyCandidateStageComplete(expectedIncluded, candidateSets)) {
      await markStageComplete("candidates", { sets: candidateSets.length });
    } else {
      const verifiedSectionIds = new Set(candidateSets.filter((cs) => cs.atomic_adopt_verified).map((cs) => cs.section_id));
      pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_PARTIAL_CHAPTER_SAMPLE, { reason: "candidates_stage_not_verified", expected: expectedIncluded.length, actual: candidateSets.length, verified: [...verifiedSectionIds].length });
      report.failures.push(`candidates stage not fully verified — expected ${expectedIncluded.length} sets, got ${candidateSets.length}`);
    }

    // Save/reload invariance
    if (candidateSets.length > 0) {
      traceStep(18, "save_reload", "save_working_copy", "started");
      const firstSection = candidateSets[0];
      const wc = await pipeline.getWorkingCopy(projectId, firstSection.section_id);
      const saveKey = stableIdempotencyKey(laneKey, projectId, "save_wc", firstSection.section_id);
      const saveResult = await pipeline.saveWorkingCopy(projectId, firstSection.section_id, wc.document_id || report.documentId, wc.content_blocks, wc.revision, saveKey);
      const reloaded = await pipeline.getWorkingCopy(projectId, firstSection.section_id);
      if (reloaded.content_sha256 !== saveResult?.content_sha256 && reloaded.content_sha256 !== wc.content_sha256) report.failures.push("save/reload hash mismatch");
      traceStep(18, "save_reload", "save_reload_invariance", "completed", `sha256=${reloaded.content_sha256?.slice(0, 16)}...`);
    }

    // Literature import
    const literatureDoi = "10.1056/NEJMoa2110257";
    try {
      const litKey = stableIdempotencyKey(laneKey, projectId, "literature", literatureDoi);
      const litResult = await pipeline.importLiterature(projectId, literatureDoi, report, litKey);
      report.literatureImports.push({ source_input: literatureDoi, result: litResult });
      laneArtifacts.citation_qc = { doi_imported: true, source_input: literatureDoi, reference_id: litResult?.reference_id || litResult?.id, timestamp: new Date().toISOString() };
      receiptCollector.collect({ stepId: "literature_import_doi", serviceRole: "citation_resolution", jobResult: litResult }, report, pipeline.recordGateFailure);
      traceStep(19, "literature", "import_via_doi", "completed");
    } catch (error) {
      report.literatureImports.push({ source_input: literatureDoi, error: error.message });
      laneArtifacts.citation_qc = { doi_imported: false, error: error.message };
      pipeline.recordGateFailure(report, ALL_GATE_CODES.LITERATURE_IMPORT_FAILED, { source_input: literatureDoi, error: error.message.slice(0, 200) });
    }

    // DOCX export
    traceStep(20, "export", "docx_export", "started");
    try {
      const exportResult = await pipeline.exportDocx(projectId, LANE_EVIDENCE_DIR, report);
      report.documentExport = exportResult;
      const exportStat = exportResult?.export_path ? await stat(exportResult.export_path).catch(() => null) : null;
      laneArtifacts.docx_qc = { export_path: exportResult?.export_path, file_exists: Boolean(exportStat), file_size: exportStat?.size || 0, local_sha256: exportResult?.local_sha256, header_docx_sha256: exportResult?.header_docx_sha256, is_zero_bytes: exportStat?.size === 0 };
      if (!exportStat || exportStat.size === 0) pipeline.recordGateFailure(report, ALL_GATE_CODES.DOCX_EXPORT_MISSING, { path: exportResult?.export_path, size: exportStat?.size || 0 });
      traceStep(20, "export", "docx_export", "completed", `path=${exportResult?.export_path}, size=${exportStat?.size || 0}`);
      // D11: Mark export complete using shared verifier — independently stat/read/hash the file
      const exportVerified = exportResult?.export_path ? await verifyExportCompletion(exportResult, exportResult.export_path) : false;
      if (exportVerified) {
        await markStageComplete("export", { path: exportResult.export_path, size: exportStat.size, sha256: exportResult.local_sha256 });
      } else {
        report.failures.push("export stage not verified — DOCX empty or hash mismatch");
      }
    } catch (error) {
      pipeline.recordGateFailure(report, ALL_GATE_CODES.DOCX_EXPORT_MISSING, { reason: error.message.slice(0, 200) });
      traceStep(20, "export", "docx_export", "failed", error.message.slice(0, 100));
    }

    await pipeline.screenshot(cdp, "lane_evidence_captured.png");

    // Final assessment
    journeyTrace.passed = report.gateFailures.length === 0 && report.failures.length === 0;
    report.passed = journeyTrace.passed;
    const requiredStages = ["project_creation", "framing", "picos", "competitor_search", "preparation", "validation", "translation", "candidates", "export"];
    // D6: Use successful persisted transitions, not journeyTrace.steps
    const completedSet = new Set(completedStages);
    for (const stage of requiredStages) {
      if (!completedSet.has(stage)) { pipeline.recordGateFailure(report, ALL_GATE_CODES.PRODUCT_JOURNEY_INCOMPLETE, { missing_stage: stage }); report.passed = false; journeyTrace.passed = false; }
    }

    // Save checkpoint with all completed stages
    await checkpoint.save({ projectId, sourceMode: projectSourceMode, journeyRevision: report.initialRevision, sourceSha: synopsisSourcePath ? await pipeline.fileSha256(synopsisSourcePath).catch(() => "") : "", completedStages, stageArtifacts });
    laneArtifacts.lane_checkpoint = checkpoint.data;

  } catch (error) {
    const detail = `${error.status || "error"}:${error.message}`;
    report.failures.push(detail);
    report.passed = false; journeyTrace.passed = false;
    if (error.status === 404) pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_BACKEND_STAGE_MISSING, { evidence_locator: detail });
    else if (/ClinicalTrials|competitor-search|expected study|snapshot/i.test(error.message)) pipeline.recordGateFailure(report, ALL_GATE_CODES.GATE_CTGOV_UNREACHABLE, { evidence_locator: detail });
  } finally {
    cdp?.close();
    await pipeline.stopChrome(chrome, userDataDir);
  }

  // D7: Evidence commit — sole finalization path via commitEvidenceTransaction
  laneArtifacts.source_receipts = report.sourceReceipts;
  laneArtifacts.service_receipts = receiptCollector.toJSON();
  report.serviceReceipts = receiptCollector.toJSON();
  laneArtifacts.browser_qc = [{ lane: laneKey, page_errors: pageErrors, http_failures: httpFailures, project_id: report.projectId, entry_mode: entryMode, chrome_pid: report.chromePid }];

  // Build artifacts object for the transaction
  const _artifacts = { "lane_report.json": report };
  for (const [name, content] of Object.entries(laneArtifacts)) {
    const filename = name.endsWith(".json") ? name : `${name}.json`;
    _artifacts[filename] = content;
  }

  // commitEvidenceTransaction: write staging → re-read/hash/validate → promote → clear locators
  const { verified, locatorClearedCount } = await commitEvidenceTransaction({
    outputDir, laneKey, projectId: report.projectId, runtimeDir,
    allocationAttempt: _allocationAttempt, sourceMode: entryMode,
    sourceSha: synopsisSourcePath ? await pipeline.fileSha256(synopsisSourcePath).catch(() => "") : "",
    artifacts: _artifacts,
    durableClient: durableClient && report.passed ? durableClient : null,
  });
  if (!verified) {
    throw new Error("evidence transaction verification failed — locators retained, evidence not promoted");
  }

  console.log(JSON.stringify({ lane: laneKey, entry_mode: entryMode, mode: report.mode, passed: report.passed, gateFailures: report.gateFailures.length, failures: report.failures.length, journey_steps: journeyTrace.steps.length, service_receipts: receiptCollector.receipts.length, resumed_from_checkpoint: report.resumedFromCheckpoint, chrome_pid: report.chromePid }, null, 2));
  if (!report.passed) process.exitCode = 1;
}

// ─── Project creation via UI ────────────────────────────────────────────

async function createProjectViaUi(cdp, report) {
  await pipeline.evaluate(cdp, `(() => { const t = document.querySelector('.new-project-trigger') || Array.from(document.querySelectorAll('button')).find((b) => (b.textContent||'').includes('新建项目')); if (t) t.click(); return Boolean(t); })()`);
  await pipeline.waitForCondition(cdp, `Boolean(document.querySelector('.new-project-dialog'))`);
  const entryButtonText = entryMode === "synopsis_import" ? "导入方案摘要" : "从零开始";
  await pipeline.evaluate(cdp, `(() => { const btns = document.querySelectorAll('.new-project-entry-mode button'); const t = Array.from(btns).find((b) => (b.textContent||'').includes(${JSON.stringify(entryButtonText)})); if (t) { t.click(); return true; } return false; })()`);
  const reactSetter = (sel, val, isSel) => `(() => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) throw new Error('field not found'); const p = ${isSel ? "HTMLSelectElement.prototype" : "HTMLInputElement.prototype"}; Object.getOwnPropertyDescriptor(p, 'value').set.call(el, ${JSON.stringify(val)}); el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); return true; })()`;
  const phaseLabel = studyPhase === "I" ? "I期" : "III期";
  await pipeline.evaluate(cdp, reactSetter('.new-project-fields label:nth-of-type(1) input', productName, false));
  await pipeline.evaluate(cdp, reactSetter('.new-project-fields label:nth-of-type(2) input', indication, false));
  await pipeline.evaluate(cdp, reactSetter('.new-project-fields label:nth-of-type(3) select', phaseLabel, true));
  await pipeline.evaluate(cdp, `(() => { const d = document.querySelector('.new-project-dialog form') || document.querySelector('.new-project-dialog'); if (!d) throw new Error('dialog not found'); if (d.requestSubmit) { d.requestSubmit(); return 'submit'; } d.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true})); return 'dispatch'; })()`);
  await pipeline.waitForCondition(cdp, `Boolean(document.querySelector('.authoring-journey-shell')) || document.body.textContent.includes('研究设计引导') || document.body.textContent.includes('研究方案智能设计与写作') || document.body.textContent.includes('导入已有方案') || document.body.textContent.includes('导入方案摘要')`, 60000);
  await pipeline.wait(1000);
  await pipeline.screenshot(cdp, "new_project_active.png");
  let pid = null;
  for (let i = 0; i < 10; i++) { pid = await pipeline.evaluate(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value || null`); if (pid) break; await pipeline.wait(500); }
  if (!pid) throw new Error("new project did not produce a selected project id");
  report.projectId = pid;
  return pid;
}

// ─── Dry-run finisher ───────────────────────────────────────────────────

async function finishDryRun(cdp, pageErrors, httpFailures, receiptCollector, checkpoint) {
  const shellVisible = await pipeline.evaluate(cdp, `Boolean(document.querySelector('.authoring-journey-shell'))`);
  if (!shellVisible) report.failures.push("dry-run:authoring-journey-shell-not-visible");
  const selectorValue = await pipeline.evaluate(cdp, `document.querySelector('select[aria-label="选择临床研究项目"]')?.value || null`);
  if (!selectorValue) report.failures.push("dry-run:project-selector-empty");
  const dialogOpen = await pipeline.evaluate(cdp, `Boolean(document.querySelector('.new-project-dialog'))`);
  if (dialogOpen) report.failures.push("dry-run:new-project-dialog-still-open");
  await pipeline.screenshot(cdp, "dry_run_complete.png");
  report.passed = report.failures.length === 0 && report.gateFailures.length === 0;
  journeyTrace.passed = report.passed;
  const dryRunSkippedStages = ["framing", "picos", "competitor_search", "preparation", "validation", "extraction", "translation", "corpus_admission", "candidates", "rewrite", "save_reload", "literature", "export"];
  for (const stage of dryRunSkippedStages) traceStep(99, stage, "skipped_dry_run", "skipped_dry_run", "dry-run: no product AI execution");
  if (report.projectId) { await checkpoint.save({ projectId: report.projectId, sourceMode: "dry_run", journeyRevision: report.initialRevision, completedStages: ["project_creation"], stageArtifacts: {} }); laneArtifacts.lane_checkpoint = checkpoint.data; }
  laneArtifacts.source_receipts = report.sourceReceipts;
  laneArtifacts.service_receipts = receiptCollector.toJSON();
  laneArtifacts.browser_qc = [{ lane: laneKey, page_errors: pageErrors, http_failures: httpFailures, project_id: report.projectId, entry_mode: entryMode, chrome_pid: report.chromePid }];
  const dryRunEvidence = { lane: laneKey, project_id: report.projectId, entry_mode: entryMode, authoring_journey_shell_visible: shellVisible, project_selector_value: selectorValue, new_project_dialog_closed: !dialogOpen, synopsis_source_checked: entryMode === "synopsis_import" ? Boolean(synopsisSourcePath) : false, dry_run_stages_skipped: dryRunSkippedStages.length, passed: report.passed };
  await writeFile(path.join(outputDir, "lane_artifacts.json"), JSON.stringify(laneArtifacts, null, 2));
  for (const [name, content] of Object.entries(laneArtifacts)) { const fn = name.endsWith(".json") ? name : `${name}.json`; await writeFile(path.join(outputDir, fn), JSON.stringify(content, null, 2)); }
  await writeFile(path.join(outputDir, "lane_report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(dryRunEvidence, null, 2));
  if (!report.passed) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error.message); process.exitCode = 1; });
