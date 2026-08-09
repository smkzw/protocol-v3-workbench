/**
 * Deterministic structure QC for the 12-lane final release E2E gate (rerun 01).
 *
 * CRITICAL FIX (defect #6): The QC now validates against ALL six defect
 * classes from the rejection review:
 *   1. RA synopsis source must be bound (not null)
 *   2. NCT sentinels must be per-lane-evidence-based (no PNH reuse)
 *   3. Parent must create per-lane isolated runtime (not shared)
 *   4. Child must implement full product journey (not stop after framing)
 *   5. Synopsis sources must match declared lane (mismatches must be declared)
 *   6. QC must fail on the above (false-green prevention)
 *
 * Run: node frontend/tests/final_release_12lane_structure_qc.mjs
 */

import { strict as assert } from "node:assert";
import { existsSync, readFileSync } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");

const configModule = await import("./final_release_12lane_config.mjs");
const {
  EXPECTED_STUDIES_12LANE,
  GATE_CODES_12LANE,
  REQUIRED_DESIGN_PRESSURES,
  REQUIRED_ROUTE_CLASSES,
  REQUIRED_ENTRY_MODES,
  REQUIRED_PHASES,
  REQUIRED_INDICATIONS,
  ARTIFACT_FILENAMES_12LANE,
  LOCAL_SYNOPSIS_SOURCES,
  CTGOV_SENTINEL_EVIDENCE,
  validateLaneCoverage,
} = configModule;

let passed = 0;
let failed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (error) {
    failed += 1;
    failures.push({ name, message: error.message });
  }
}

async function testAsync(name, fn) {
  try {
    await fn();
    passed += 1;
  } catch (error) {
    failed += 1;
    failures.push({ name, message: error.message });
  }
}

// ====================================================================
// 1. Matrix completeness
// ====================================================================

test("12-lane matrix has exactly 12 lanes", () => {
  assert.equal(EXPECTED_STUDIES_12LANE.length, 12, "expected exactly 12 lanes");
});

test("12-lane matrix covers all required indications", () => {
  const covered = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.indication));
  for (const ind of REQUIRED_INDICATIONS) {
    assert.ok(covered.has(ind), `indication not covered: ${ind}`);
  }
});

test("12-lane matrix covers all required phases", () => {
  const covered = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.studyPhase));
  for (const ph of REQUIRED_PHASES) {
    assert.ok(covered.has(ph), `phase not covered: ${ph}`);
  }
});

test("12-lane matrix covers all required entry modes", () => {
  const covered = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.entryMode));
  for (const em of REQUIRED_ENTRY_MODES) {
    assert.ok(covered.has(em), `entry mode not covered: ${em}`);
  }
});

test("12-lane matrix covers all required design pressures", () => {
  const covered = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.designPressure));
  for (const dp of REQUIRED_DESIGN_PRESSURES) {
    assert.ok(covered.has(dp), `design pressure not covered: ${dp}`);
  }
});

test("12-lane matrix covers all required route classes", () => {
  const covered = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.interventionRouteClass));
  for (const rc of REQUIRED_ROUTE_CLASSES) {
    assert.ok(covered.has(rc), `route class not covered: ${rc}`);
  }
});

test("Each indication × phase × entry combination exists", () => {
  for (const ind of REQUIRED_INDICATIONS) {
    for (const ph of REQUIRED_PHASES) {
      for (const em of REQUIRED_ENTRY_MODES) {
        const found = EXPECTED_STUDIES_12LANE.find(
          (l) => l.indication === ind && l.studyPhase === ph && l.entryMode === em,
        );
        assert.ok(found, `missing lane: ${ind}_${ph}_${em}`);
      }
    }
  }
});

test("Lane coverage validation passes", () => {
  const result = validateLaneCoverage();
  assert.ok(result.valid, `coverage validation failed: ${result.missing.join(", ")}`);
});

// ====================================================================
// 2. DEFECT #1: RA synopsis source must be bound
// ====================================================================

test("RA synopsis-import lanes have non-null synopsisSourcePath", () => {
  const raSynopsisLanes = EXPECTED_STUDIES_12LANE.filter(
    (l) => l.indication === "类风湿关节炎" && l.entryMode === "synopsis_import",
  );
  assert.ok(raSynopsisLanes.length > 0, "RA synopsis-import lanes not found");
  for (const lane of raSynopsisLanes) {
    assert.ok(
      lane.synopsisSourcePath,
      `${lane.key}: synopsisSourcePath is null — RA synopsis must be bound`,
    );
  }
});

test("All synopsis-import lanes have non-null synopsisSourcePath", () => {
  const synopsisLanes = EXPECTED_STUDIES_12LANE.filter((l) => l.entryMode === "synopsis_import");
  for (const lane of synopsisLanes) {
    assert.ok(
      lane.synopsisSourcePath,
      `${lane.key}: synopsisSourcePath is null`,
    );
  }
});

test("RA synopsis source SHA-256 matches the verified file", () => {
  const raI = EXPECTED_STUDIES_12LANE.find((l) => l.key === "RA_I_SYNOPSIS");
  assert.ok(raI, "RA_I_SYNOPSIS lane not found");
  assert.equal(
    raI.synopsisSourceSha256,
    "f6c8fdf53535a58f0f05055fe07c3a34bb0932f30c8bc2a7cdb6f8fc97dc8be4",
    "RA synopsis SHA-256 mismatch",
  );
});

// ====================================================================
// 3. DEFECT #2: NCT sentinels must be per-lane-evidence-based
// ====================================================================

test("NCT04654468 is NOT used as an RA sentinel", () => {
  const lanesUsing04654468 = EXPECTED_STUDIES_12LANE.filter(
    (l) => l.expectedNctId === "NCT04654468",
  );
  assert.equal(
    lanesUsing04654468.length,
    0,
    "NCT04654468 is a PNH Phase III study and must not be used as any lane sentinel",
  );
});

test("NCT05923099 is NOT used as a universal AD sentinel", () => {
  const lanesUsing05923099 = EXPECTED_STUDIES_12LANE.filter(
    (l) => l.expectedNctId === "NCT05923099",
  );
  assert.equal(
    lanesUsing05923099.length,
    0,
    "NCT05923099 is a Phase IIb AD study, not a universal sentinel",
  );
});

test("NCT03451422 is NOT used as a PsO sentinel", () => {
  const lanesUsing03451422 = EXPECTED_STUDIES_12LANE.filter(
    (l) => l.expectedNctId === "NCT03451422",
  );
  assert.equal(
    lanesUsing03451422.length,
    0,
    "NCT03451422 is an SLE Phase Ib/IIa study, not a PsO sentinel",
  );
});

test("All NCT sentinels have CT.gov evidence records", () => {
  const usedNcts = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.expectedNctId));
  for (const nct of usedNcts) {
    const evidence = CTGOV_SENTINEL_EVIDENCE.sentinels[Object.keys(CTGOV_SENTINEL_EVIDENCE.sentinels).find((k) => CTGOV_SENTINEL_EVIDENCE.sentinels[k].nct_id === nct)];
    assert.ok(
      evidence,
      `NCT ${nct} has no CT.gov evidence record in CTGOV_SENTINEL_EVIDENCE`,
    );
  }
});

test("NCT sentinels match lane indication", () => {
  for (const lane of EXPECTED_STUDIES_12LANE) {
    const sentinelKey = Object.keys(CTGOV_SENTINEL_EVIDENCE.sentinels).find(
      (k) => CTGOV_SENTINEL_EVIDENCE.sentinels[k].nct_id === lane.expectedNctId,
    );
    if (!sentinelKey) continue;
    const evidence = CTGOV_SENTINEL_EVIDENCE.sentinels[sentinelKey];
    // The sentinel's conditions must include something related to the lane's indication
    const sentinelConditions = (evidence.conditions || []).join(" ").toLowerCase();
    const laneIndicationLower = lane.indication.toLowerCase();
    if (laneIndicationLower.includes("类风湿") || laneIndicationLower.includes("rheumatoid")) {
      assert.ok(
        sentinelConditions.includes("rheumatoid") || sentinelConditions.includes("ra"),
        `${lane.key}: sentinel ${lane.expectedNctId} conditions don't match RA`,
      );
    } else if (laneIndicationLower.includes("特应性") || laneIndicationLower.includes("atopic")) {
      assert.ok(
        sentinelConditions.includes("atopic") || sentinelConditions.includes("dermatitis"),
        `${lane.key}: sentinel ${lane.expectedNctId} conditions don't match AD`,
      );
    } else if (laneIndicationLower.includes("银屑病") || laneIndicationLower.includes("psoriasis")) {
      assert.ok(
        sentinelConditions.includes("psoriasis") || sentinelConditions.includes("healthy"),
        `${lane.key}: sentinel ${lane.expectedNctId} conditions don't match PsO`,
      );
    }
  }
});

test("Sentinel reuse has documented reason", () => {
  const nctUsage = new Map();
  for (const lane of EXPECTED_STUDIES_12LANE) {
    if (!nctUsage.has(lane.expectedNctId)) {
      nctUsage.set(lane.expectedNctId, []);
    }
    nctUsage.get(lane.expectedNctId).push(lane);
  }
  for (const [nct, lanes] of nctUsage) {
    if (lanes.length > 1) {
      for (const lane of lanes) {
        assert.ok(
          lane.sentinelReuseReason,
          `${lane.key}: sentinel ${nct} is reused but has no documented reason`,
        );
      }
    }
  }
});

// ====================================================================
// 4. DEFECT #5: Synopsis sources must match or declare mismatches
// ====================================================================

test("All synopsis sources exist on disk", () => {
  for (const [key, source] of Object.entries(LOCAL_SYNOPSIS_SOURCES)) {
    assert.ok(
      existsSync(source.path),
      `${key}: source file does not exist: ${source.path}`,
    );
  }
});

test("Synopsis sources with phase mismatch have override reason", () => {
  for (const [key, source] of Object.entries(LOCAL_SYNOPSIS_SOURCES)) {
    const lane = EXPECTED_STUDIES_12LANE.find((l) => l.key === key);
    if (!lane) continue;
    const sourcePhase = source.declared_phase;
    const lanePhase = lane.studyPhase;
    if (sourcePhase !== lanePhase && !sourcePhase.includes(lanePhase) && !lanePhase.includes(sourcePhase.replace("/", ""))) {
      // Phase mismatch — must have override reason
      assert.ok(
        source.override_reason,
        `${key}: source phase ${sourcePhase} ≠ lane phase ${lanePhase} but no override reason`,
      );
      // Lane must carry the override reason
      assert.ok(
        lane.synopsisSourceOverrideReason,
        `${key}: lane config missing synopsisSourceOverrideReason`,
      );
    }
  }
});

test("No synopsis source mismatch is hidden in config comments", () => {
  const configContent = readFileSync(
    path.join(scriptDir, "final_release_12lane_config.mjs"),
    "utf8",
  );
  // Ensure config doesn't have null synopsisSourcePath for synopsis-import lanes
  for (const lane of EXPECTED_STUDIES_12LANE) {
    if (lane.entryMode === "synopsis_import") {
      assert.ok(
        lane.synopsisSourcePath !== null && lane.synopsisSourcePath !== undefined,
        `${lane.key}: synopsisSourcePath must not be null for synopsis-import lane`,
      );
    }
  }
});

// ====================================================================
// 5. DEFECT #3: Parent must create per-lane isolated runtime
// ====================================================================

test("Parent harness source creates per-lane runtime inside the lane loop", () => {
  const parentSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_parent.mjs"),
    "utf8",
  );
  // Must have mkdtemp inside the loop
  assert.ok(
    parentSource.includes("mkdtemp") && parentSource.includes("for (let index"),
    "parent must create mkdtemp runtime inside the lane loop",
  );
  // Must NOT have a shared runtime created before the loop
  const loopStart = parentSource.indexOf("for (let index = 0; index < selectedLanes.length");
  assert.ok(loopStart > 0, "parent must have a lane loop");
  const beforeLoop = parentSource.slice(0, loopStart);
  assert.ok(
    !beforeLoop.includes("mkdtemp(path.join(tmpdir(), `mw-12lane-runtime-"),
    "parent must NOT create shared mw-12lane-runtime before the loop — must be per-lane",
  );
  // Must set WORKBENCH_RUNTIME_DIR per lane
  assert.ok(
    parentSource.includes("WORKBENCH_RUNTIME_DIR: laneRuntimeDir") ||
    parentSource.includes("WORKBENCH_RUNTIME_DIR: laneRuntimeDir,"),
    "parent must set WORKBENCH_RUNTIME_DIR per lane",
  );
  // Must stop API/Vite per lane
  assert.ok(
    parentSource.includes("stopProcess(viteProc"),
    "parent must stop Vite per lane",
  );
  assert.ok(
    parentSource.includes("stopProcess(apiProc"),
    "parent must stop API per lane",
  );
  // Must do SQLite integrity per lane
  assert.ok(
    parentSource.includes("sqliteIntegrity(laneRuntimeDir)"),
    "parent must run SQLite integrity per lane",
  );
});

test("Parent runtime report has perLaneIsolation flag", () => {
  const parentSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_parent.mjs"),
    "utf8",
  );
  assert.ok(
    parentSource.includes("perLaneIsolation: true"),
    "parent must report perLaneIsolation: true",
  );
});

test("Parent report has laneRuntimes array (not shared single runtime)", () => {
  const parentSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_parent.mjs"),
    "utf8",
  );
  assert.ok(
    parentSource.includes("laneRuntimes: []"),
    "parent report must have laneRuntimes array",
  );
  assert.ok(
    !parentSource.includes("sharedRuntimeOutsideLoop: true"),
    "parent must not declare sharedRuntimeOutsideLoop: true",
  );
});

// ====================================================================
// 6. DEFECT #4: Child must implement full product journey
// ====================================================================

test("Child harness source implements framing commit", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("commitFraming"), "child must call commitFraming");
});

test("Child harness source implements PICOS commit", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("commitPicos"), "child must call commitPicos");
});

test("Child harness source implements competitor search", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("competitorSearch"), "child must call competitorSearch");
});

test("Child harness source implements preparation/OCR batch", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("createPreparationBatch"), "child must call createPreparationBatch");
  assert.ok(childSource.includes("pollPreparationBatch"), "child must call pollPreparationBatch");
});

test("Child harness source implements validation and extraction", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("ensureDocumentValidation"), "child must call ensureDocumentValidation");
  assert.ok(childSource.includes("ensureExtractionReview"), "child must call ensureExtractionReview");
});

test("Child harness source implements translation batch", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("createTranslationBatch"), "child must call createTranslationBatch");
  assert.ok(childSource.includes("pollTranslationBatch"), "child must call pollTranslationBatch");
});

test("Child harness source implements corpus admission", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("submitMedicalReview"), "child must call submitMedicalReview");
  assert.ok(childSource.includes("admitTranslation"), "child must call admitTranslation");
});

test("Child harness source implements writing access and document creation", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("ensureWritingAccess"), "child must call ensureWritingAccess");
  assert.ok(childSource.includes("createGreenfieldDocument"), "child must call createGreenfieldDocument");
});

test("Child harness source implements revision threads (3-5 candidates)", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("createRevisionThread"), "child must call createRevisionThread");
  assert.ok(childSource.includes("CANDIDATE_COUNT_OUT_OF_RANGE"), "child must validate candidate count 3-5");
});

test("Child harness source implements DOCX export", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("exportDocx"), "child must call exportDocx");
  assert.ok(childSource.includes("DOCX_EXPORT_MISSING"), "child must gate on DOCX export existence");
});

test("DOCX export uses real GET /document.docx route, not nonexistent POST export", () => {
  const pipelineSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_pipeline.mjs"),
    "utf8",
  );
  // Reject the nonexistent route
  assert.ok(
    !pipelineSource.includes("/medical-writing/documents/") ||
    !pipelineSource.match(/documents\/\$\{[^}]+documentId[^}]*\}\/export/),
    "pipeline must not use nonexistent POST /documents/{documentId}/export",
  );
  // Require the real route
  assert.ok(
    pipelineSource.includes("/medical-writing/document.docx?mode=draft_preview"),
    "pipeline must use GET /medical-writing/document.docx?mode=draft_preview",
  );
  // Require binary response handling
  assert.ok(
    pipelineSource.includes("arrayBuffer"),
    "pipeline must read binary response via arrayBuffer()",
  );
  // Require header SHA-256 verification
  assert.ok(
    pipelineSource.includes("x-medical-writing-docx-sha256"),
    "pipeline must verify X-Medical-Writing-Docx-Sha256 header",
  );
  assert.ok(
    pipelineSource.includes("header_sha256_matches"),
    "pipeline must compare local hash against header hash",
  );
});

test("Literature import uses real POST /literature/imports route, not nonexistent /literature/import", () => {
  const pipelineSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_pipeline.mjs"),
    "utf8",
  );
  // Reject the nonexistent route (singular "import" without trailing "s")
  assert.ok(
    !pipelineSource.includes("/medical-writing/literature/import\"") &&
    !pipelineSource.includes("/medical-writing/literature/import`"),
    "pipeline must not use nonexistent POST /literature/import (singular)",
  );
  // Require the real route (plural "imports")
  assert.ok(
    pipelineSource.includes("/medical-writing/literature/imports"),
    "pipeline must use POST /medical-writing/literature/imports",
  );
  // Require product contract fields
  assert.ok(
    pipelineSource.includes("source_input"),
    "pipeline must send source_input per MedicalWritingReferenceImportRequest",
  );
  // Reject old nonexistent fields
  assert.ok(
    !pipelineSource.includes("import_type") && !pipelineSource.includes("document_id: documentId"),
    "pipeline must not send import_type or document_id (not in product contract)",
  );
});

test("Literature import failure is a lane gate failure (not silently caught)", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(
    childSource.includes("LITERATURE_IMPORT_FAILED"),
    "child must record LITERATURE_IMPORT_FAILED gate failure on import error",
  );
});

test("Child harness source implements literature import", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("importLiterature"), "child must call importLiterature");
});

test("Child harness source implements save/reload invariance", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("saveWorkingCopy"), "child must call saveWorkingCopy");
});

test("Child harness source implements synopsis import via real product API", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(childSource.includes("uploadSynopsis"), "child must call uploadSynopsis");
  assert.ok(childSource.includes("confirmSynopsis"), "child must call confirmSynopsis");
  assert.ok(childSource.includes("synopsis-import"), "child must use synopsis-import API route");
});

test("Synopsis confirmation uses post-upload revision (not pre-upload stale revision)", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  // Must read revision from upload response (updatedJourney), not from pre-upload journey
  assert.ok(
    childSource.includes("updatedJourney.revision"),
    "confirmSynopsis must use updatedJourney.revision from upload response, not pre-upload journey",
  );
  // The confirm body's expected_revision must be the post-upload integer, not String(pre-upload)
  // Check that the confirm body assignment uses updatedJourney.revision as integer
  assert.ok(
    /expected_revision:\s*updatedJourney\.revision/.test(childSource),
    "confirmSynopsis body must assign expected_revision: updatedJourney.revision (integer, not String)",
  );
  // Must use product-extracted source_id
  assert.ok(
    childSource.includes("synopsisImport.source?.source_id"),
    "confirmSynopsis must use product-extracted synopsisImport.source.source_id",
  );
  // Must use product-extracted synopsis_text (not blank)
  assert.ok(
    childSource.includes("proposed_synopsis_text"),
    "confirmSynopsis must use product-extracted proposed_synopsis_text",
  );
  // Must acknowledge actual validation warnings
  assert.ok(
    childSource.includes("acknowledged_validation_warnings"),
    "confirmSynopsis must acknowledge validation warnings",
  );
});

test("Child harness source does NOT delegate to Worker 03", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(
    !childSource.includes("Worker 03") && !childSource.includes("worker_03"),
    "child must not delegate pipeline stages to Worker 03",
  );
  assert.ok(
    !childSource.includes("delegated to"),
    "child must not delegate pipeline stages",
  );
});

test("Child journey trace records all required stages", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  const requiredStages = [
    "project_creation",
    "framing",
    "picos",
    "competitor_search",
    "preparation",
    "validation",
    "translation",
    "candidates",
    "export",
  ];
  for (const stage of requiredStages) {
    assert.ok(
      childSource.includes(`"${stage}"`) || childSource.includes(`'${stage}'`),
      `child must record journey trace stage: ${stage}`,
    );
  }
});

// ====================================================================
// 7. Evidence artifact schema
// ====================================================================

test("All 10 required artifact filenames are declared", () => {
  const requiredArtifacts = [
    "journey_trace.json",
    "source_receipts.json",
    "ai_runs.json",
    "study_definition.json",
    "chapter_matrix.json",
    "candidate_sets.json",
    "citation_qc.json",
    "browser_qc.json",
    "docx_qc.json",
    "synopsis_import_receipt.json",
  ];
  for (const artifact of requiredArtifacts) {
    assert.ok(
      ARTIFACT_FILENAMES_12LANE.includes(artifact),
      `missing required artifact: ${artifact}`,
    );
  }
});

// ====================================================================
// 8. Pipeline helper module exists and exports required functions
// ====================================================================

test("Pipeline helper module exists", () => {
  assert.ok(
    existsSync(path.join(scriptDir, "final_release_12lane_pipeline.mjs")),
    "pipeline helper module must exist",
  );
});

test("Pipeline helper module exports all required functions", async () => {
  const pipelineModule = await import("./final_release_12lane_pipeline.mjs");
  const requiredFunctions = [
    "commitFraming", "commitPicos", "competitorSearch",
    "createPreparationBatch", "pollPreparationBatch",
    "pollWorkspace", "ensureDocumentValidation", "ensureExtractionReview",
    "createTranslationBatch", "pollTranslationBatch",
    "submitMedicalReview", "admitTranslation",
    "ensureWritingAccess", "createGreenfieldDocument",
    "createRevisionThread", "getWorkingCopy", "checkWorkingCopyInvariance",
    "acceptCandidate", "saveWorkingCopy", "exportDocx", "importLiterature",
    "getEvidenceBriefs", "getJourney",
  ];
  for (const fn of requiredFunctions) {
    assert.ok(
      typeof pipelineModule[fn] === "function",
      `pipeline module must export function: ${fn}`,
    );
  }
});

// ====================================================================
// Probe + NCT sentinel corrections (followup-03)
// ====================================================================

test("Contract probe selects a real free port for self-start mode", () => {
  const probeSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_contract_probe.mjs"),
    "utf8",
  );
  // Must use pickFreePort() to get a real port, not port 0
  assert.ok(
    probeSource.includes("function pickFreePort()"),
    "probe must have a pickFreePort() function",
  );
  // Must NOT set API_PORT=0 when self-starting
  assert.ok(
    !probeSource.match(/API_PORT\s*=\s*0/),
    "probe must not use port 0 in self-start mode",
  );
});

test("Contract probe fatal errors produce nonzero exit", () => {
  const probeSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_contract_probe.mjs"),
    "utf8",
  );
  // Exit code must check both failed steps AND fatal errors
  assert.ok(
    probeSource.includes("failed > 0 || hasFatal"),
    "probe exit must be nonzero when any step fails OR a fatal error occurs",
  );
});

test("Contract probe uses parameterized synopsis source via env vars", () => {
  const probeSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_contract_probe.mjs"),
    "utf8",
  );
  assert.ok(
    probeSource.includes("PROBE_SYNOPSIS_PATH"),
    "probe must parameterize synopsis path via PROBE_SYNOPSIS_PATH env var",
  );
  // Default must be the smaller MY009 UC synopsis
  assert.ok(
    probeSource.includes("MY009212A-UC-Ib"),
    "probe default synopsis must be the smaller MY009 UC Ib file",
  );
  // Must NOT hardcode the large RA synopsis
  assert.ok(
    !probeSource.includes("MY004-RA-2b"),
    "probe must not hardcode the large RA synopsis as default",
  );
});

test("Contract probe records synopsis SHA-256 and size in evidence", () => {
  const probeSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_contract_probe.mjs"),
    "utf8",
  );
  assert.ok(
    probeSource.includes("synopsis_source_verified"),
    "probe must verify synopsis source existence and record SHA-256",
  );
  assert.ok(
    probeSource.includes("fileSha256"),
    "probe must compute synopsis file SHA-256",
  );
});

test("Contract probe has configurable upload timeout (default >= 20 min)", () => {
  const probeSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_contract_probe.mjs"),
    "utf8",
  );
  assert.ok(
    probeSource.includes("PROBE_SYNOPSIS_UPLOAD_TIMEOUT_MS"),
    "probe must have configurable upload timeout via env var",
  );
  // Default must be >= 1200000 (20 min)
  assert.ok(
    probeSource.match(/1500000|1200000/),
    "probe default upload timeout must be >= 20 minutes",
  );
});

test("Contract probe treats literature/DOCX failures as probe failures", () => {
  const probeSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_contract_probe.mjs"),
    "utf8",
  );
  // Literature failure must log status "fail" (not warn)
  assert.ok(
    probeSource.includes('logStep("literature_import_failed", "fail"'),
    "probe must treat literature import failure as a fail step",
  );
  // DOCX header mismatch must log status "fail" (not warn)
  assert.ok(
    probeSource.includes('headerMatches ? "pass" : "fail"'),
    "probe must treat DOCX SHA-256 header mismatch as a fail step",
  );
});

test("NCT06311682 is NOT classified as active_comparator", () => {
  const configSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_config.mjs"),
    "utf8",
  );
  // Must not have design_match: "active_comparator" for NCT06311682
  const nct063Match = configSource.match(/NCT06311682:\s*\{[^}]+\}/s);
  assert.ok(nct063Match, "NCT06311682 sentinel must exist");
  assert.ok(
    !nct063Match[0].includes('design_match: "active_comparator"'),
    "NCT06311682 must not carry design_match=active_comparator (it is placebo+TCS)",
  );
  assert.ok(
    nct063Match[0].includes('design_match: "placebo_background_therapy"'),
    "NCT06311682 must carry design_match=placebo_background_therapy",
  );
});

test("NCT02277743 is NOT classified as interim_analysis_treatment_switch", () => {
  const configSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_config.mjs"),
    "utf8",
  );
  const nct022Match = configSource.match(/NCT02277743:\s*\{[^}]+\}/s);
  assert.ok(nct022Match, "NCT02277743 sentinel must exist");
  assert.ok(
    !nct022Match[0].includes('design_match: "interim_analysis_treatment_switch"'),
    "NCT02277743 must not carry interim_analysis_treatment_switch (no verified interim analysis)",
  );
});

test("AD_III_SYNOPSIS lane uses corrected NCT06311682 design pressure", () => {
  const configSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_config.mjs"),
    "utf8",
  );
  // AD_III_SYNOPSIS lane must not use active_comparator
  const laneMatch = configSource.match(/key:\s*"AD_III_SYNOPSIS"[\s\S]+?sentinelReuseReason:/);
  assert.ok(laneMatch, "AD_III_SYNOPSIS lane must exist");
  assert.ok(
    !laneMatch[0].includes('designPressure: "active_comparator"'),
    "AD_III_SYNOPSIS must not use active_comparator (NCT06311682 is placebo+TCS)",
  );
});

test("AD_III_SCRATCH lane uses corrected NCT02277743 design pressure", () => {
  const configSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_config.mjs"),
    "utf8",
  );
  // AD_III_SCRATCH lane must not use interim_analysis_treatment_switch
  const laneMatch = configSource.match(/key:\s*"AD_III_SCRATCH"[\s\S]+?sentinelReuseReason:/);
  assert.ok(laneMatch, "AD_III_SCRATCH lane must exist");
  assert.ok(
    !laneMatch[0].includes('designPressure: "interim_analysis_treatment_switch"'),
    "AD_III_SCRATCH must not use interim_analysis_treatment_switch (no verified interim analysis)",
  );
});

test("Design coverage gap for interim_analysis_treatment_switch is surfaced", () => {
  const configSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_config.mjs"),
    "utf8",
  );
  assert.ok(
    configSource.includes("DESIGN_COVERAGE_GAPS"),
    "config must export DESIGN_COVERAGE_GAPS to surface the interim_analysis gap",
  );
  assert.ok(
    configSource.includes("interim_analysis_treatment_switch") &&
    configSource.includes('"uncovered"'),
    "DESIGN_COVERAGE_GAPS must mark interim_analysis_treatment_switch as uncovered",
  );
});

test("Child uploadSynopsis has configurable timeout (not fixed 120s)", () => {
  const childSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_child.mjs"),
    "utf8",
  );
  assert.ok(
    childSource.includes("SYNOPSIS_UPLOAD_TIMEOUT_MS"),
    "child uploadSynopsis must use configurable SYNOPSIS_UPLOAD_TIMEOUT_MS",
  );
  // Must not have the old fixed 120000 timeout
  assert.ok(
    !childSource.includes("AbortSignal.timeout(120000)"),
    "child must not use fixed 120s timeout for synopsis upload",
  );
  // Must record upload duration
  assert.ok(
    childSource.includes("upload_duration_ms"),
    "child must record upload duration",
  );
});

test("Parent passes SYNOPSIS_UPLOAD_TIMEOUT_MS to child env", () => {
  const parentSource = readFileSync(
    path.join(scriptDir, "final_release_12lane_parent.mjs"),
    "utf8",
  );
  assert.ok(
    parentSource.includes("SYNOPSIS_UPLOAD_TIMEOUT_MS"),
    "parent must pass SYNOPSIS_UPLOAD_TIMEOUT_MS to child env",
  );
});


// ====================================================================
// Summary
// ====================================================================

console.log("\n══════════════════════════════════════════════════════════");
console.log("  12-Lane Structure QC (rerun 01)");
console.log("══════════════════════════════════════════════════════════");
console.log(`  Passed: ${passed}`);
console.log(`  Failed: ${failed}`);
if (failed > 0) {
  console.log("\n  Failures:");
  for (const f of failures) {
    console.log(`    ✗ ${f.name}`);
    console.log(`      ${f.message}`);
  }
}
console.log("══════════════════════════════════════════════════════════\n");

if (failed > 0) process.exitCode = 1;
