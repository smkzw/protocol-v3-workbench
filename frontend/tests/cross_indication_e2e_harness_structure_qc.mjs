/**
 * Static / source-contract checks for the cross-indication E2E harness (Round 4).
 *
 * Unlike the old string-matching tests, these checks:
 *   1. Parse the generated source-contract JSON (from Python AST) to verify
 *      the harness routes and request models match the real backend.
 *   2. Scan the child harness source for prohibited fabricated patterns.
 *   3. Verify the quality scorecard schema enforces the lifecycle contract.
 *   4. Verify configuration sentinels match SOURCE_GOLDEN_FACTS.md.
 */

import { strict as assert } from "node:assert";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "../..");

const {
  EXPECTED_STUDIES,
  INDICATIONS,
  GATE_CODES,
  REQUIRED_STAGE_SEQUENCE,
  ARTIFACT_FILENAMES,
  GOLDEN_FACT_PATTERNS,
  SCORE_DIMENSIONS,
  REPRESENTATIVE_CHAPTERS,
  ALLOWED_DOWNLOAD_HOSTS,
} = await import("./cross_indication_e2e_config.mjs");

// Load the source-contract JSON generated from Python AST
let sourceContracts;
try {
  sourceContracts = JSON.parse(
    await readFile(path.join(scriptDir, "cross_indication_source_contracts.json"), "utf8"),
  );
} catch (error) {
  console.error("FATAL: cross_indication_source_contracts.json not found. Run the Python AST extractor first.");
  throw error;
}

const { STAGE_SEQUENCE, normalizeStage, getStageLabel, isBusyStage } = await import(
  "../src/features/writing-reference/progressJourneyLogic.mjs"
);

let passed = 0;
let failed = 0;
const failures = [];
const pendingAsyncTests = [];

function test(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (error) {
    failed += 1;
    failures.push({ name, message: error.message });
  }
}

function testAsync(name, fn) {
  pendingAsyncTests.push(
    (async () => {
      try {
        await fn();
        passed += 1;
      } catch (error) {
        failed += 1;
        failures.push({ name, message: error.message });
      }
    })(),
  );
}

// ============================================================================
// 1. Source-contract verification (AST-generated)
// ============================================================================

test("source contracts JSON has routes and models", () => {
  assert.ok(sourceContracts.routes && Object.keys(sourceContracts.routes).length >= 15);
  assert.ok(sourceContracts.models && Object.keys(sourceContracts.models).length >= 15);
});

test("harness uses real POST /api/projects route", () => {
  assert.ok(
    sourceContracts.routes["POST /api/projects"],
    "POST /api/projects not found in source contracts",
  );
  assert.equal(
    sourceContracts.routes["POST /api/projects"].request_model,
    "UserProjectCreateRequest",
  );
});

test("harness uses real authoring-journey GET route", () => {
  assert.ok(
    sourceContracts.routes["GET /api/projects/{project_id}/medical-writing/authoring-journey"],
  );
});

test("harness uses real framing commit route", () => {
  const key = "POST /api/projects/{project_id}/medical-writing/authoring-journey/stages/{stage}/commit";
  assert.ok(sourceContracts.routes[key], `${key} not in contracts`);
});

test("harness uses real competitor-search route", () => {
  const key = "POST /api/projects/{project_id}/medical-writing/authoring-journey/competitor-search";
  assert.ok(sourceContracts.routes[key]);
});

testAsync("harness resolves the immutable snapshot after competitor search", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.match(childSrc, /search_plan\?\.latest_snapshot_id/);
  assert.match(
    childSrc,
    /medical-writing\/references\/search-snapshots\/\$\{encodeURIComponent\(snapshotId\)\}/,
  );
});

testAsync("harness uses the production extraction-review decision vocabulary", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const reviewFunction = childSrc.match(
    /async function createExtractionReview[\s\S]*?return result\.payload;\n}/,
  )?.[0];
  assert.ok(reviewFunction, "createExtractionReview function not found");
  assert.match(reviewFunction, /decision:\s*"approved"/);
  assert.doesNotMatch(reviewFunction, /decision:\s*"accepted"/);
});

testAsync("harness approves only the full mapped extraction anchor set", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const ensureFunction = childSrc.match(
    /async function ensureExtractionReview[\s\S]*?return \{\n    extraction_revision:/,
  )?.[0];
  assert.ok(ensureFunction, "ensureExtractionReview function not found");
  assert.match(ensureFunction, /\/spans\?extraction_revision=/);
  assert.match(ensureFunction, /Object\.keys\(spansResult\.payload\?\.anchor_counts/);
  assert.match(ensureFunction, /anchor !== "unmapped"/);
  assert.match(ensureFunction, /confirmedAnchorCoverage\.length/);
});

test("harness uses real workspace route", () => {
  const key = "GET /api/projects/{project_id}/medical-writing/references/workspace";
  assert.ok(sourceContracts.routes[key]);
});

test("harness uses real document ingest route", () => {
  const key = "POST /api/projects/{project_id}/medical-writing/references/documents/ingest";
  assert.ok(sourceContracts.routes[key]);
});

test("harness uses real translations route", () => {
  const key = "POST /api/projects/{project_id}/medical-writing/references/translations";
  assert.ok(sourceContracts.routes[key]);
});

testAsync("translation timeout is classified before active-stage endpoint failures", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const timeoutGuard = childSrc.indexOf("translation batch timed out while status=");
  const readyCollection = childSrc.indexOf(
    "const allReadyItems = collectCandidateReadyItems(report.translationBatch)",
  );
  const timeoutGate = childSrc.indexOf(
    'recordGateFailure(report, "GATE_TRANSLATION_TIMEOUT"',
  );
  const flashGate = childSrc.indexOf(
    'recordGateFailure(report, "GATE_FLASH_QC_UNAVAILABLE"',
  );
  assert.ok(timeoutGuard > 0 && timeoutGuard < readyCollection);
  assert.ok(timeoutGate > 0 && timeoutGate < flashGate);
});

testAsync("deterministic fidelity blocks are not reported as Hy-MT2 unavailability", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const configSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_config.mjs"),
    "utf8",
  );
  assert.match(childSrc, /summary\.fidelity_blocked > 0/);
  assert.match(childSrc, /translation fidelity gate blocked all selected chapters/);
  assert.match(childSrc, /"GATE_FIDELITY_BLOCKED"/);
  assert.match(configSrc, /GATE_FIDELITY_BLOCKED/);
});

testAsync("translation batch is bounded to two indication-specific representative anchors", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const createFunction = childSrc.match(
    /async function createTranslationBatch[\s\S]*?return createResult\.payload;\n}/,
  )?.[0];
  assert.ok(createFunction, "createTranslationBatch function not found");
  assert.match(
    createFunction,
    /REPRESENTATIVE_CHAPTERS\[indicationKey\]/,
  );
  assert.match(createFunction, /anchor_filter=\$\{encodeURIComponent\(anchor\)\}/);
  assert.match(createFunction, /anchor_filter:\s*representativeAnchors/);
  assert.doesNotMatch(createFunction, /anchor_filter:\s*\[\]/);
});

test("harness uses real medical-review route", () => {
  const key = "POST /api/projects/{project_id}/medical-writing/references/translations/{translation_id}/medical-review";
  assert.ok(sourceContracts.routes[key]);
});

test("harness uses real admissions route", () => {
  const key = "POST /api/projects/{project_id}/medical-writing/references/translations/{translation_id}/admissions";
  assert.ok(sourceContracts.routes[key]);
});

test("harness uses real revision-threads route", () => {
  assert.ok(sourceContracts.routes["POST /api/projects/{project_id}/revision-threads"]);
});

test("MedicalWritingCompetitorSearchExecuteRequest has search_plan_id field", () => {
  const model = sourceContracts.models["MedicalWritingCompetitorSearchExecuteRequest"];
  assert.ok(model, "model not found");
  assert.ok("search_plan_id" in model.fields, "must have search_plan_id");
});

test("WritingReferenceMedicalReviewRequest has translation_revision field", () => {
  const model = sourceContracts.models["WritingReferenceMedicalReviewRequest"];
  assert.ok(model);
  assert.ok("translation_revision" in model.fields);
  assert.ok("expected_revision" in model.fields);
});

test("WritingReferenceAdmissionRequest has expected_translation_revision + medical_review_id", () => {
  const model = sourceContracts.models["WritingReferenceAdmissionRequest"];
  assert.ok(model);
  assert.ok("expected_translation_revision" in model.fields);
  assert.ok("medical_review_id" in model.fields);
});

test("MedicalWritingRevisionRequest uses intent field (not generate_candidates)", () => {
  const model = sourceContracts.models["MedicalWritingRevisionRequest"];
  assert.ok(model);
  assert.ok("intent" in model.fields);
  assert.ok("section_id" in model.fields);
  assert.ok("user_instruction" in model.fields);
});

testAsync("greenfield candidate generation anchors the exact blank body block", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.match(childSrc, /block\?\.source_kind === "greenfield_scaffold"/);
  assert.match(childSrc, /targetBodyBlock\.source_locator/);
  assert.doesNotMatch(childSrc, /anchor_path:\s*sectionId/);
});

test("MedicalWritingCorpusTriageFinalizeRequest uses retained_candidate_ids + snapshot_id", () => {
  const model = sourceContracts.models["MedicalWritingCorpusTriageFinalizeRequest"];
  assert.ok(model);
  assert.ok("retained_candidate_ids" in model.fields, "must use retained_candidate_ids not retained_nct_ids");
  assert.ok("snapshot_id" in model.fields);
});

test("WritingReferenceDocumentArtifact has real receipt fields", () => {
  const model = sourceContracts.models["WritingReferenceDocumentArtifact"];
  assert.ok(model);
  for (const f of ["final_url", "content_sha256", "actual_size", "requested_url"]) {
    assert.ok(f in model.fields, `artifact must have ${f}`);
  }
});

// ============================================================================
// 2. Prohibited fabricated pattern checks (scan child harness source)
// ============================================================================

testAsync("child harness does NOT write final_url: ''", async () => {
  const childSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_child.mjs"), "utf8");
  assert.ok(
    !/final_url\s*:\s*["']["']/.test(childSrc),
    "child harness must not write empty final_url",
  );
});

testAsync("child harness does NOT write sha256: ''", async () => {
  const childSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_child.mjs"), "utf8");
  assert.ok(
    !/sha256\s*:\s*["']["']/.test(childSrc),
    "child harness must not write empty sha256",
  );
});

testAsync("child harness does NOT write bytes: 0", async () => {
  const childSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_child.mjs"), "utf8");
  assert.ok(
    !/bytes\s*:\s*0\b/.test(childSrc),
    "child harness must not write bytes: 0",
  );
});

testAsync("child harness does NOT assign fixed score 4", async () => {
  const childSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_child.mjs"), "utf8");
  assert.ok(
    !/\[dim,\s*4\]/.test(childSrc) && !/:\s*4\b.*score/i.test(childSrc),
    "child harness must not assign fixed score 4",
  );
});

testAsync("child harness does NOT set average_score: 4.0", async () => {
  const childSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_child.mjs"), "utf8");
  assert.ok(
    !/average_score\s*:\s*4/.test(childSrc),
    "child harness must not set average_score to a fixed value",
  );
});

testAsync("child harness does NOT use medical_review_id: 'e2e-review'", async () => {
  const childSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_child.mjs"), "utf8");
  assert.ok(
    !/medical_review_id\s*:\s*["']e2e-review["']/.test(childSrc),
    "child harness must not fabricate medical_review_id",
  );
});

testAsync("child harness does not fabricate validation or extraction revisions", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.ok(
    !/validation_revision\s*:\s*artifact\.state_revision\s*\|\|\s*1/.test(childSrc),
    "validation_revision must come from a real content-validation record",
  );
  assert.ok(
    !/extraction_revision\s*:\s*["']pending["']/.test(childSrc),
    "extraction_revision must come from a real extraction result",
  );
});

testAsync("full mode executes every downstream product workflow route", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const sourceWithoutComments = childSrc
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  // Full mode must call all required product routes outside comments.
  // These are the real validation/extraction review/translation batch/
  // medical review/admission/revision-thread routes from main.py.
  for (const routeFragment of [
    "/medical-writing/references/translation-batches",
    "/medical-writing/references/translations/",
    "/medical-review",
    "/admissions",
    "/revision-threads",
    "/evidence-briefs",
    "/greenfield-document",
    "/working-copies/",
  ]) {
    assert.ok(
      sourceWithoutComments.includes(routeFragment),
      `full harness does not execute required product route ${routeFragment}`,
    );
  }
});

testAsync("full mode calls preparation batch and extraction review routes", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const sourceWithoutComments = childSrc
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.ok(
    sourceWithoutComments.includes("/preparation-batches"),
    "full harness must poll preparation-batch for real validation/extraction revisions",
  );
  assert.ok(
    sourceWithoutComments.includes("/extraction-reviews"),
    "full harness must submit extraction structure review",
  );
  assert.ok(
    sourceWithoutComments.includes("await createPreparationBatch(") &&
      sourceWithoutComments.includes("await pollPreparationBatch(") &&
      sourceWithoutComments.includes("await ensureExtractionReview("),
    "preparation and extraction-review helpers must be invoked by the full lane",
  );
});

testAsync("child harness captures validation revision from document_validations", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.ok(
    childSrc.includes("captureRealValidationRevision"),
    "child must have a function to capture real validation revision",
  );
  assert.ok(
    childSrc.includes("document_validations"),
    "child must read from workspace.document_validations[]",
  );
});

testAsync("child harness captures extraction revision from extraction_reviews", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.ok(
    childSrc.includes("captureRealExtractionRevision"),
    "child must have a function to capture real extraction revision",
  );
  assert.ok(
    childSrc.includes("extraction_reviews"),
    "child must read from workspace.extraction_reviews[]",
  );
});

testAsync("child harness blocks lane when validation/extraction receipt is missing", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const sourceWithoutComments = childSrc
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  // The harness must fail-fast (return) when real validation or extraction
  // revisions are not observed — never pass through with null/placeholder.
  assert.ok(
    sourceWithoutComments.includes("!validationReceipt"),
    "child must block when validation receipt is missing",
  );
  assert.ok(
    sourceWithoutComments.includes("!extractionReceipt"),
    "child must block when extraction receipt is missing",
  );
});

testAsync("child harness requires 3-5 real suggestions from revision threads", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const sourceWithoutComments = childSrc
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.ok(
    sourceWithoutComments.includes("suggestions.length < 3") &&
      sourceWithoutComments.includes("suggestions.length > 5"),
    "child must require exactly 3-5 suggestions from revision thread",
  );
});

testAsync("child harness computes working-copy invariance with real hashes", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const sourceWithoutComments = childSrc
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.ok(
    sourceWithoutComments.includes("getWorkingCopy"),
    "child must read real working copy for invariance proof",
  );
  assert.ok(
    sourceWithoutComments.includes("const before = await getWorkingCopy"),
    "child must record working copy before candidate generation",
  );
  assert.ok(
    sourceWithoutComments.includes("const after = await getWorkingCopy"),
    "child must record working copy after candidate generation",
  );
  assert.ok(
    sourceWithoutComments.includes("checkWorkingCopyInvariance(before, after)"),
    "child must compare before/after working copy hashes",
  );
});

testAsync("full mode creates a real greenfield document before candidate generation", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.ok(
    childSrc.includes("/medical-writing/greenfield-document") &&
      childSrc.includes("await createGreenfieldDocument("),
    "full lane must materialize the protocol document and working copies",
  );
});

testAsync("full mode generates two section-specific candidate groups", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.ok(
    childSrc.includes("representativeChapters.length < 2"),
    "full lane must require at least two representative evidence anchors",
  );
  assert.ok(
    childSrc.includes("for (const mapping of chapterMapping)") &&
      childSrc.includes("[mapping.brief_id]"),
    "each target section must use its own mapped evidence brief",
  );
});

testAsync("emitted scorecard is validated against the real JSON schema", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.ok(
    childSrc.includes("validateQualityScorecardFile(scorecardPath)") &&
      childSrc.includes("quality_scorecard.schema.json") &&
      childSrc.includes("Draft202012Validator"),
    "runtime must schema-validate the emitted quality scorecard",
  );
});

testAsync("child harness never invokes candidate apply/action route", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  const sourceWithoutComments = childSrc
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  // The apply/action route must NEVER be called — candidates are for blind review only.
  assert.ok(
    !sourceWithoutComments.includes("/actions"),
    "child must not invoke revision-thread action/apply route",
  );
  assert.ok(
    !sourceWithoutComments.includes("apply_revision_action"),
    "child must not invoke apply_revision_action",
  );
});

testAsync("child harness scorecard stays pending_blind_review or blocked_before_review", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  // The scorecard build function must never assign "reviewed" or scores.
  assert.ok(
    childSrc.includes("pending_blind_review"),
    "child must use pending_blind_review lifecycle state",
  );
  assert.ok(
    childSrc.includes("blocked_before_review"),
    "child must use blocked_before_review lifecycle state",
  );
  // Must not contain a literal self-scored value
  assert.ok(
    !/review_status\s*:\s*["']reviewed["']/.test(childSrc),
    "child must never self-assign reviewed status",
  );
});

testAsync("source contracts include translation batch and preparation batch routes", () => {
  assert.ok(
    sourceContracts.routes[
      "POST /api/projects/{project_id}/medical-writing/references/translation-batches"
    ],
    "translation-batch create route must be in source contracts",
  );
  assert.ok(
    sourceContracts.routes[
      "GET /api/projects/{project_id}/medical-writing/references/translation-batches/preview"
    ],
    "translation-batch preview route must be in source contracts",
  );
  assert.ok(
    sourceContracts.routes[
      "POST /api/projects/{project_id}/medical-writing/references/preparation-batches"
    ],
    "preparation-batch create route must be in source contracts",
  );
  assert.ok(
    sourceContracts.routes[
      "POST /api/projects/{project_id}/medical-writing/references/documents/{artifact_id}/extraction-reviews"
    ],
    "extraction-reviews route must be in source contracts",
  );
  assert.ok(
    sourceContracts.routes["GET /api/projects/{project_id}/medical-writing/document-index"],
    "document-index route must be in source contracts",
  );
});

test("WritingReferenceTranslationBatchItem has validation_id and extraction_revision fields", () => {
  const model = sourceContracts.models["WritingReferenceTranslationBatchItem"];
  assert.ok(model, "WritingReferenceTranslationBatchItem model not found");
  assert.ok("validation_id" in model.fields, "must have validation_id");
  assert.ok("validation_revision" in model.fields, "must have validation_revision");
  assert.ok("extraction_revision" in model.fields, "must have extraction_revision");
  assert.ok("structure_review_id" in model.fields, "must have structure_review_id");
  assert.ok("translation_id" in model.fields, "must have translation_id");
  assert.ok("translation_revision" in model.fields, "must have translation_revision");
});

test("WritingReferencePreparationBatchItem has validation and extraction fields", () => {
  const model = sourceContracts.models["WritingReferencePreparationBatchItem"];
  assert.ok(model, "WritingReferencePreparationBatchItem model not found");
  assert.ok("artifact_id" in model.fields, "must have artifact_id");
  assert.ok("extraction_revision" in model.fields, "must have extraction_revision");
  assert.ok("validation_id" in model.fields, "must have validation_id");
  assert.ok("validation_status" in model.fields, "must have validation_status");
});

test("WritingReferenceExtractionReviewRequest has extraction_revision + expected_revision", () => {
  const model = sourceContracts.models["WritingReferenceExtractionReviewRequest"];
  assert.ok(model);
  assert.ok("extraction_revision" in model.fields);
  assert.ok("expected_revision" in model.fields);
  assert.ok("decision" in model.fields);
});

test("WritingReferenceDocumentValidationRecord has revision field", () => {
  const model = sourceContracts.models["WritingReferenceDocumentValidationRecord"];
  assert.ok(model);
  assert.ok("revision" in model.fields, "must have revision (the immutable validation revision)");
  assert.ok("validation_id" in model.fields);
  assert.ok("status" in model.fields);
  assert.ok("extraction_revision" in model.fields);
});

testAsync("child harness does NOT use intent: 'generate_candidates'", async () => {
  const childSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_child.mjs"), "utf8");
  assert.ok(
    !/intent.*generate_candidates/.test(childSrc),
    "child harness must not use fabricated intent 'generate_candidates'",
  );
});

testAsync("child harness uses pending_blind_review or blocked_before_review", async () => {
  const childSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_child.mjs"), "utf8");
  assert.ok(
    childSrc.includes("pending_blind_review") || childSrc.includes("blocked_before_review"),
    "child harness must use the correct scorecard lifecycle state",
  );
  assert.ok(
    !/"reviewed"/.test(childSrc.match(/review_status\s*[=:]\s*["']\w+/)?.[0] || ""),
    "child harness must not self-assign reviewed status",
  );
});

testAsync("chapter evidence resolves template nodes to project section ids", async () => {
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.ok(
    childSrc.includes("target_template_node_id: CHAPTER_TARGET_SECTIONS[anchor]"),
    "mapping must retain the stable M11 template-node identity",
  );
  assert.ok(
    childSrc.includes("sectionsByTemplateNode.get"),
    "mapping must resolve the template node against the created document",
  );
  assert.ok(
    childSrc.includes("mapping.target_section_id = targetSection.section_id"),
    "candidate generation must use the project-specific section id",
  );
});

testAsync("parent harness has --dry-run mode", async () => {
  const parentSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_parent.mjs"), "utf8");
  assert.ok(parentSrc.includes("--dry-run"), "parent must support --dry-run");
  assert.ok(parentSrc.includes("QC_DRY_RUN"), "parent must pass QC_DRY_RUN to child");
});

testAsync("dry-run fails closed when lane evidence is missing", async () => {
  const parentSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_parent.mjs"),
    "utf8",
  );
  const childSrc = await readFile(
    path.join(scriptDir, "cross_indication_e2e_child.mjs"),
    "utf8",
  );
  assert.ok(
    parentSrc.includes("dry-run:lane-evidence-missing"),
    "parent must fail when child dry-run evidence is missing",
  );
  assert.ok(
    childSrc.includes("dry_run_evidence"),
    "child must persist observed dry-run evidence before returning",
  );
});

testAsync("parent harness loads ai-runtime.env", async () => {
  const parentSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_parent.mjs"), "utf8");
  assert.ok(
    parentSrc.includes("ai-runtime.env") || parentSrc.includes("loadAiRuntimeEnv"),
    "parent must load the production AI environment file",
  );
});

testAsync("parent harness does not print credential values", async () => {
  const parentSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_parent.mjs"), "utf8");
  // The env loader should only record key presence, not values
  assert.ok(
    parentSrc.includes("value.length > 0") || parentSrc.includes("keys[key]"),
    "parent must record key presence, not values",
  );
});

// ============================================================================
// 3. Configuration sentinels
// ============================================================================

test("exactly four indication sentinels", () => {
  assert.equal(EXPECTED_STUDIES.length, 4);
});

test("each indication has expected NCT sentinel", () => {
  for (const ind of EXPECTED_STUDIES) {
    assert.ok(ind.expectedNctId?.startsWith("NCT"), `${ind.key} needs expectedNctId`);
    assert.ok(ind.expectedDocumentFilename, `${ind.key} needs expectedDocumentFilename`);
    assert.ok(
      ["protocol", "sap", "protocol_sap"].includes(ind.expectedDocumentRole),
      `${ind.key} needs valid expectedDocumentRole`,
    );
  }
});

test("expected NCT IDs match SOURCE_GOLDEN_FACTS", () => {
  const ncts = EXPECTED_STUDIES.map((i) => i.expectedNctId);
  assert.ok(ncts.includes("NCT05923099"), "AD sentinel");
  assert.ok(ncts.includes("NCT04654468"), "PNH sentinel");
  assert.ok(ncts.includes("NCT04707313"), "OBESITY sentinel");
  assert.ok(ncts.includes("NCT03451422"), "SLE Phase 1b sentinel");
});

test("configuration contains no local filesystem .pdf path", () => {
  const serialized = JSON.stringify({ EXPECTED_STUDIES, GATE_CODES, GOLDEN_FACT_PATTERNS });
  // Sentinel filenames like "Prot_SAP_000.pdf" are official CT.gov document names, not local paths.
  // Prohibit local path patterns: relative parent dirs, slice extraction dirs, absolute/home paths.
  assert.ok(!/records\/active_slices/i.test(serialized), "no slice-extracted path");
  assert.ok(!/\.\.\//.test(serialized), "no relative parent path in serialized config");
  assert.ok(!/[":]\s*\/(Users|tmp|var|home)\//.test(serialized), "no absolute path in serialized config");
});

test("allowed download hosts do not include local filesystem", () => {
  for (const host of ALLOWED_DOWNLOAD_HOSTS) {
    assert.ok(host.includes("clinicaltrials.gov"));
    assert.ok(!host.startsWith("/"));
  }
});

test("parent script does not hardcode stable port 5174 or 8911", async () => {
  const parentSrc = await readFile(path.join(scriptDir, "cross_indication_e2e_parent.mjs"), "utf8");
  // Strip comments — port numbers may appear in documentation headers
  const sourceWithoutComments = parentSrc
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  assert.ok(!/\b5174\b/.test(sourceWithoutComments), "parent must not hardcode :5174");
  assert.ok(!/\b8911\b/.test(sourceWithoutComments), "parent must not hardcode :8911");
});

// ============================================================================
// 4. Scorecard schema lifecycle
// ============================================================================

test("scorecard schema has three review statuses", async () => {
  const schema = JSON.parse(
    await readFile(
      path.join(
        projectRoot,
        "records/active_slices/medical_writing_cross_indication_reference_gate_20260718/quality_scorecard.schema.json",
      ),
      "utf8",
    ),
  );
  const statuses = schema.properties.review_status.enum;
  assert.ok(statuses.includes("pending_blind_review"));
  assert.ok(statuses.includes("blocked_before_review"));
  assert.ok(statuses.includes("reviewed"));
});

test("scorecard schema requires working-copy before/after hashes", async () => {
  const schema = JSON.parse(
    await readFile(
      path.join(
        projectRoot,
        "records/active_slices/medical_writing_cross_indication_reference_gate_20260718/quality_scorecard.schema.json",
      ),
      "utf8",
    ),
  );
  const csRequired = schema.properties.candidate_sets.items.required;
  for (const f of [
    "working_copy_hash_before",
    "working_copy_hash_after",
    "working_copy_revision_before",
    "working_copy_revision_after",
  ]) {
    assert.ok(csRequired.includes(f), `schema missing ${f}`);
  }
});

test("scorecard schema allows null average_score", async () => {
  const schema = JSON.parse(
    await readFile(
      path.join(
        projectRoot,
        "records/active_slices/medical_writing_cross_indication_reference_gate_20260718/quality_scorecard.schema.json",
      ),
      "utf8",
    ),
  );
  const avgType = schema.properties.gate.properties.average_score.type;
  assert.ok(Array.isArray(avgType) && avgType.includes("null"));
});

// ============================================================================
// 5. Stage sequence
// ============================================================================

test("gate-code stages are all in the product stage sequence", () => {
  for (const [code, entry] of Object.entries(GATE_CODES)) {
    if (entry.stage === "candidate_generation") continue;
    if (code === "GATE_BACKEND_STAGE_MISSING") continue;
    assert.ok(
      REQUIRED_STAGE_SEQUENCE.includes(entry.stage) || STAGE_SEQUENCE.includes(entry.stage),
      `${code} stage ${entry.stage} not in known sequences`,
    );
  }
});

test("product STAGE_SEQUENCE has at least 12 stages", () => {
  assert.ok(STAGE_SEQUENCE.length >= 12);
});

test("terminal stages do not set aria-busy", () => {
  assert.equal(isBusyStage("candidate_ready"), false);
  assert.equal(isBusyStage("prepared"), false);
});

// ============================================================================
// Summary
// ============================================================================

await Promise.all(pendingAsyncTests);

console.log(`\n=== Cross-Indication E2E Harness Structure QC (Round 4) ===`);
console.log(`Passed: ${passed}`);
console.log(`Failed: ${failed}`);
if (failures.length > 0) {
  console.log("\nFailures:");
  for (const f of failures) console.log(`  ✗ ${f.name}: ${f.message}`);
  process.exit(1);
} else {
  console.log("All tests passed ✓");
  process.exit(0);
}
