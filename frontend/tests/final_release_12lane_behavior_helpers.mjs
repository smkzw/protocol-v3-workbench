/**
 * Shared W3 orchestration helpers — extracted from child.mjs for test invocation.
 *
 * These are the SAME functions used by the child's executable chain.
 * Tests import and invoke them directly — no source-string checks.
 *
 * @module final_release_12lane_behavior_helpers
 */

import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile, rename, open as fsOpen } from "node:fs/promises";
import { existsSync as fsExistsSync, readdirSync, statSync, createReadStream } from "node:fs";
import path from "node:path";

import {
  DurableMwClient, LaneCheckpoint, computeRawResponseHash, canonicalJsonStringify,
  LOCATOR_SCHEMA_VERSION, CHECKPOINT_SCHEMA_VERSION, stableIdempotencyKey,
} from "./final_release_12lane_durable_client.mjs";
import { ReceiptCollector, buildServiceReceipt } from "./final_release_12lane_receipts.mjs";
import * as pipeline from "./final_release_12lane_pipeline.mjs";

// ─── D3: Source lineage verifier ─────────────────────────────────────

/**
 * Verify that the checkpoint source hash matches the current source hash.
 * Used by child before Chrome/project mutation and by tests.
 * Returns true on match, throws on mismatch.
 */
export function verifySourceLineage(checkpointData, currentSourceSha) {
  if (!checkpointData) throw new Error("checkpoint data is null");
  if (!checkpointData.source_sha) throw new Error("checkpoint missing source_sha");
  if (!currentSourceSha) throw new Error("current source SHA is empty");
  if (checkpointData.source_sha !== currentSourceSha) {
    throw new Error(`source_sha mismatch: checkpoint ${checkpointData.source_sha} != current ${currentSourceSha}`);
  }
  return true;
}

// ─── D6/D11: Export completion verifier ──────────────────────────────

/**
 * Independently verify that a DOCX export result is complete and valid.
 *
 * This verifier NEVER trusts a caller-supplied header_sha256_matches boolean.
 * It independently:
 *   1. stats the actual file on disk — must exist and be non-empty
 *   2. reads the raw bytes from disk
 *   3. computes SHA-256 of those bytes
 *   4. compares the recomputed hash to the server header hash
 *   5. requires non-empty local_sha256 in the export result
 *
 * Returns true only when ALL checks pass.
 *
 * @param {object} exportResult - the pipeline export result with header_docx_sha256, local_sha256
 * @param {string} exportPath - absolute path to the actual exported file on disk
 */
export async function verifyExportCompletion(exportResult, exportPath) {
  if (!exportResult) return false;
  if (!exportResult.header_docx_sha256) return false;
  if (!exportResult.local_sha256) return false;

  // Independently stat the file
  let st;
  try {
    const { statSync } = await import("node:fs");
    st = statSync(exportPath);
  } catch {
    return false;
  }
  if (!st || st.size <= 0) return false;

  // Independently read and hash the actual file bytes
  const h = createHash("sha256");
  const s = createReadStream(exportPath);
  for await (const chunk of s) h.update(chunk);
  const recomputedSha = h.digest("hex");

  // Compare recomputed hash to the server-provided header hash
  if (recomputedSha !== exportResult.header_docx_sha256) return false;
  // Also compare to the result's local_sha256
  if (recomputedSha !== exportResult.local_sha256) return false;

  return true;
}

// ─── D11: Candidate stage verifier ───────────────────────────────────

/**
 * Verify that the candidate stage meets exact required-chapter coverage.
 * Returns true only when: every expectedIncluded has a verified candidate set,
 * set count equals expected count (no extras/duplicates), and every adoption
 * is verified.
 */
export function verifyCandidateStageComplete(expectedIncluded, candidateSets) {
  if (!expectedIncluded || expectedIncluded.length === 0) return false;
  if (!candidateSets || candidateSets.length === 0) return false;
  // Exact cardinality
  if (candidateSets.length !== expectedIncluded.length) return false;
  // Every expected section must have a verified set
  const verifiedSections = new Set(
    candidateSets.filter((cs) => cs.atomic_adopt_verified).map((cs) => cs.section_id),
  );
  for (const incl of expectedIncluded) {
    if (!verifiedSections.has(incl.section_id)) return false;
  }
  // No duplicate section IDs
  const allSections = candidateSets.map((cs) => cs.section_id);
  if (new Set(allSections).size !== allSections.length) return false;
  return true;
}

// ─── D10: Atomic adoption verifier ───────────────────────────────────

/**
 * Verify that atomic adoption is correct against the authoritative reread.
 * Returns an object with individual check results and overall `allVerified`.
 * Used by child and tests.
 */
export function verifyAtomicAdoption({
  adoptResult, threadId, selectedSuggestionId, before, after, rereadThread, sectionId,
}) {
  const adoptWc = adoptResult?.working_copy || {};
  const adoptWcRevision = adoptWc.revision;
  const adoptWcId = adoptWc.working_copy_id;
  const adoptContentHash = adoptWc.content_sha256 || adoptWc.source_working_copy_content_sha256;

  const rereadSuggestions = rereadThread?.suggestions || [];
  const selectedSuggestionState = rereadSuggestions.find((s) => s.suggestion_id === selectedSuggestionId);
  const siblingStates = rereadSuggestions.filter((s) => s.suggestion_id !== selectedSuggestionId);

  const checks = {
    thread_id_match: Boolean(adoptResult?.thread_id) && adoptResult.thread_id === threadId,
    suggestion_id_match: Boolean(adoptResult?.suggestion_id) && adoptResult.suggestion_id === selectedSuggestionId,
    wc_hash_changed: Boolean(before?.content_sha256) && Boolean(after?.content_sha256) && after.content_sha256 !== before.content_sha256,
    wc_revision_match: Boolean(adoptWcRevision) && Boolean(after?.revision) && adoptWcRevision === after.revision,
    wc_id_match: Boolean(adoptWcId) && Boolean(after?.working_copy_id) && adoptWcId === after.working_copy_id,
    reread_thread_exists: Boolean(rereadThread),
    section_id_match: Boolean(rereadThread?.section_id) && rereadThread.section_id === sectionId,
    nested_hash_matches_reread: Boolean(adoptContentHash) && adoptContentHash === after?.content_sha256,
    selected_suggestion_adopted: Boolean(selectedSuggestionState) &&
      (selectedSuggestionState.user_decision === "accepted" ||
       selectedSuggestionState.fact_adoption_status === "adopted_as_project_fact"),
    siblings_not_adopted: siblingStates.length > 0 &&
      siblingStates.every((s) => s.user_decision !== "accepted" && s.fact_adoption_status !== "adopted_as_project_fact"),
  };
  checks.allVerified = Object.entries(checks).every(([k, v]) => k === "allVerified" || v === true);
  return checks;
}

// ─── D7: Evidence transaction — sole child evidence finalization path ─

/**
 * Commit an evidence transaction as the SOLE finalization path:
 *
 *   1. Atomically write every evidence file (staging)
 *   2. Build the final manifest (staging)
 *   3. Independently re-read/hash/validate every listed file against the manifest
 *   4. If verified: atomically promote manifest to final
 *   5. If verified AND durableClient provided: clear reconciled locators
 *   6. If NOT verified: retain all locators and prior evidence — do NOT clear
 *
 * Returns { manifest, verified, locatorClearedCount }.
 */
export async function commitEvidenceTransaction({
  outputDir, laneKey, projectId, runtimeDir, allocationAttempt, sourceMode, sourceSha,
  artifacts, // object of { filename: content }
  durableClient = null, // if provided, clear reconciled locators after verified manifest
}) {
  const _atomicWrite = async (filePath, obj) => {
    await mkdir(path.dirname(filePath), { recursive: true });
    const jsonStr = JSON.stringify(obj, null, 2);
    const tmpPath = path.join(path.dirname(filePath), `.tmp.ev.${process.pid}.${Date.now()}.${Math.random().toString(36).slice(2, 8)}`);
    const fh = await fsOpen(tmpPath, "w");
    try { await fh.writeFile(jsonStr, "utf8"); await fh.sync(); } finally { await fh.close(); }
    await rename(tmpPath, filePath);
  };

  const _fileSha256 = async (fp) => {
    const h = createHash("sha256");
    const s = createReadStream(fp);
    for await (const c of s) h.update(c);
    return h.digest("hex");
  };

  // Step 1: Write all evidence files (staging)
  for (const [filename, content] of Object.entries(artifacts)) {
    await _atomicWrite(path.join(outputDir, filename), content);
  }

  // Step 2: Build manifest (staging) — scan all .json files in outputDir
  const evidenceFiles = [];
  for (const fname of readdirSync(outputDir)) {
    if (fname.endsWith(".json") && !fname.startsWith(".tmp") && fname !== "evidence_manifest.json") {
      const fp = path.join(outputDir, fname);
      const st = statSync(fp);
      const sha = await _fileSha256(fp);
      evidenceFiles.push({ path: fname, size: st.size, sha256: sha });
    }
  }

  const manifest = {
    schema_version: "mw_e3_evidence_manifest_v1",
    lane_key: laneKey,
    project_id: projectId,
    runtime_dir: runtimeDir,
    allocation_attempt: allocationAttempt,
    source_mode: sourceMode,
    source_sha: sourceSha,
    files: evidenceFiles,
    created_at: new Date().toISOString(),
  };

  // Step 3: Independently re-read/hash/validate every listed file
  for (const entry of evidenceFiles) {
    const fp = path.join(outputDir, entry.path);
    if (!fsExistsSync(fp)) {
      return { manifest, verified: false, reason: `missing file ${entry.path}`, locatorClearedCount: 0 };
    }
    // Path escape check
    const resolved = path.resolve(fp);
    const expectedDir = path.resolve(outputDir);
    if (!resolved.startsWith(expectedDir)) {
      return { manifest, verified: false, reason: `path escape ${entry.path}`, locatorClearedCount: 0 };
    }
    const st = statSync(fp);
    if (st.size !== entry.size) {
      return { manifest, verified: false, reason: `size mismatch ${entry.path}`, locatorClearedCount: 0 };
    }
    const recomputedSha = await _fileSha256(fp);
    if (recomputedSha !== entry.sha256) {
      return { manifest, verified: false, reason: `hash mismatch ${entry.path}`, locatorClearedCount: 0 };
    }
  }

  // Step 4: Atomically promote manifest to final
  await _atomicWrite(path.join(outputDir, "evidence_manifest.json"), manifest);

  // Re-read the final manifest to confirm promotion
  const manifestReread = JSON.parse(await readFile(path.join(outputDir, "evidence_manifest.json"), "utf8"));
  if (!manifestReread.files || manifestReread.files.length !== evidenceFiles.length) {
    return { manifest: manifestReread, verified: false, reason: "file count mismatch after promotion", locatorClearedCount: 0 };
  }

  // Step 5: Only after verified manifest, clear reconciled locators
  let locatorClearedCount = 0;
  if (durableClient) {
    for (const stepId of Object.keys(durableClient.locators)) {
      if (durableClient.locators[stepId]?.reconciled) {
        await durableClient.deleteLocator(stepId);
        locatorClearedCount++;
      }
    }
  }

  return { manifest: manifestReread, verified: true, locatorClearedCount };
}

// ─── Re-export canonical builders from pipeline for backward compatibility ─

export { PAYLOAD_BUILDERS, emitPayloadFixtures } from "./final_release_12lane_pipeline.mjs";

// ════════════════════════════════════════════════════════════════════════
// RESUMABLE STAGE DRIVER — used by child and acceptance tests
// ════════════════════════════════════════════════════════════════════════

/**
 * The eight orchestration boundaries where crash injection occurs.
 * Each boundary is checked AFTER the corresponding stage completes its POST
 * and persists state.
 */
export const CRASH_BOUNDARIES = [
  "project_creation",
  "competitor_search",
  "preparation",
  "translation",
  "candidate_generation",
  "pre_adoption",
  "post_adoption",
  "post_evidence",
];

/**
 * Create a resumable stage driver that executes stages in order,
 * persisting completion after each, and supporting crash injection
 * at the 8 defined boundaries.
 *
 * On crash (simulated by throwing), the driver stops.
 * On resume (new driver instance with same checkpoint), it:
 *   - skips already-completed stages (no duplicate POST)
 *   - continues the exact interrupted stage
 *   - preserves lineage (checkpoint source/project/lane binding)
 *
 * @param {object} opts
 * @param {object} opts.checkpoint - LaneCheckpoint instance
 * @param {object} opts.durableClient - DurableMwClient instance
 * @param {Map<string, Function>} opts.stages - Map of stage name → async fn(stageCtx)
 * @param {string|null} opts.crashAt - boundary name to crash after (null = no crash)
 * @returns {Promise<{completedStages: string[], crashed: boolean, crashBoundary: string|null}>}
 */
export async function runResumableStages({ checkpoint, durableClient, stages, crashAt = null }) {
  const completedStages = [...(checkpoint.data?.completed_stages || [])];
  let crashed = false;
  let crashBoundary = null;

  // Helper to check if we should crash at this boundary
  const shouldCrash = (boundary) => {
    // Crash AFTER the stage completes — the stage is in completedStages,
    // but the crash prevents subsequent stages from running.
    // The key: we only crash once, on the first time this boundary completes.
    if (crashAt === boundary) {
      return true;
    }
    return false;
  };

  // Helper to mark a stage complete and persist
  const markComplete = async (stage) => {
    if (!completedStages.includes(stage)) completedStages.push(stage);
    await checkpoint.save({
      projectId: checkpoint.data?.project_id || "resume-test",
      sourceMode: checkpoint.data?.source_mode || "from_zero",
      journeyRevision: checkpoint.data?.journey_revision || 1,
      sourceSha: checkpoint.data?.source_sha || "",
      allocationAttempt: checkpoint.data?.allocation_attempt || 1,
      completedStages: [...completedStages],
      stageArtifacts: checkpoint.data?.stage_artifacts || {},
    });
  };

  const stageCtx = {
    checkpoint,
    durableClient,
    completedStages,
    markComplete,
  };

  // Execute stages in order
  for (const [stageName, stageFn] of stages) {
    // Skip already-completed stages — no duplicate POST
    if (completedStages.includes(stageName)) continue;

    // Execute the stage
    await stageFn(stageCtx);

    // Mark complete and persist
    await markComplete(stageName);

    // Check crash boundary AFTER stage completion
    if (shouldCrash(stageName)) {
      crashed = true;
      crashBoundary = stageName;
      break;
    }
  }

  return { completedStages, crashed, crashBoundary };
}
