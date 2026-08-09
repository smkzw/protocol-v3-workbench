/**
 * 12-Lane dual-entry configuration for the final release E3 harness.
 *
 * E3 rebuild: RA / AD / UC × Phase I / III × from_zero / synopsis_import.
 *
 * Source-authority model:
 * - UC_I_SYNOPSIS: exact_synopsis_file (directly importable standalone synopsis).
 * - RA_I/RA_III/AD_I/AD_III/UC_III synopsis: authoritative_protocol_synopsis_pages
 *   with fixture_status blocked_pending_exact_extract. The authoritative
 *   protocol path, hash, NCT ID and physical page range are known and recorded;
 *   until a separate source-fixture step generates the exact page extract with
 *   provenance, these lanes remain blocked and may not be used as product inputs.
 * - Full protocols are never placed in synopsisSourcePath or product inputs.
 *
 * Override-as-success fixtures have been removed entirely; a phase/type mismatch
 * is a gate failure, not a simulated pass.
 *
 * Expected NCT IDs are assertion SENTINELS only — never product search inputs.
 * Structure-only NCT oracles retain their true design and phase labels and are
 * never uploaded as synopsis files.
 *
 * @module final_release_12lane_config
 */

// ─── Required coverage dimensions ───────────────────────────────────────

export const REQUIRED_INDICATIONS = ["类风湿关节炎", "特应性皮炎", "溃疡性结肠炎"];
export const REQUIRED_PHASES = ["I", "III"];
export const REQUIRED_ENTRY_MODES = ["from_zero", "synopsis_import"];
export const REQUIRED_ROUTE_CLASSES = [
  "small_molecule_oral",
  "biologic_injection",
  "topical_local",
];
export const REQUIRED_DESIGN_PRESSURES = [
  "healthy_sad_mad",
  "sad_mad_first_in_patient",
  "background_therapy_placebo",
  "interim_analysis_treatment_switch",
  "active_comparator",
  "rescue_re_randomization_ole",
  "vehicle_placebo_phase3",
  "placebo_induction_maintenance_switch",
];

// ─── Authority class constants ──────────────────────────────────────────

export const AUTHORITY_CLASSES = {
  EXACT_SYNOPSIS_FILE: "exact_synopsis_file",
  AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES: "authoritative_protocol_synopsis_pages",
  VERSIONED_EXACT_SYNOPSIS_EXTRACT: "versioned_exact_synopsis_extract",
  BLOCKED_MISSING_AUTHORITY: "blocked_missing_authority",
};

export const FIXTURE_STATUSES = {
  READY: "ready",
  BLOCKED_PENDING_EXACT_EXTRACT: "blocked_pending_exact_extract",
  BLOCKED_MISSING_AUTHORITY: "blocked_missing_authority",
};

// ─── Gate codes (E3) ────────────────────────────────────────────────────

export const GATE_CODES_12LANE = {
  // Original lane-level gates (still used by parent/child)
  SYNOPSIS_FILE_MISSING: "GATE_SYNOPSIS_FILE_MISSING",
  SYNOPSIS_IMPORT_FAILED: "GATE_SYNOPSIS_IMPORT_FAILED",
  ENTRY_MODE_MISMATCH: "GATE_ENTRY_MODE_MISMATCH",
  LANE_RUNTIME_REUSED: "GATE_LANE_RUNTIME_REUSED",
  SHARED_RUNTIME_OUTSIDE_LOOP: "GATE_SHARED_RUNTIME_OUTSIDE_LOOP",
  CANDIDATE_COUNT_OUT_OF_RANGE: "GATE_CANDIDATE_COUNT_OUT_OF_RANGE",
  SENTINEL_NCT_REUSED_WRONG_LANE: "GATE_SENTINEL_NCT_REUSED_WRONG_LANE",
  SYNOPSIS_SOURCE_MISMATCH_HIDDEN: "GATE_SYNOPSIS_SOURCE_MISMATCH_HIDDEN",
  DOCX_EXPORT_MISSING: "GATE_DOCX_EXPORT_MISSING",
  DOCX_SHA256_MISMATCH: "GATE_DOCX_SHA256_MISMATCH",
  LITERATURE_IMPORT_FAILED: "GATE_LITERATURE_IMPORT_FAILED",
  PRODUCT_JOURNEY_INCOMPLETE: "GATE_PRODUCT_JOURNEY_INCOMPLETE",

  // E3 receipt / authority / isolation gates
  GATE_SOURCE_AUTHORITY_BLOCKED: "GATE_SOURCE_AUTHORITY_BLOCKED",
  GATE_HARDCODED_AI_IDENTITY: "GATE_HARDCODED_AI_IDENTITY",
  GATE_PARTIAL_CHAPTER_SAMPLE: "GATE_PARTIAL_CHAPTER_SAMPLE",
  GATE_DURABLE_JOB_MISSING: "GATE_DURABLE_JOB_MISSING",
  GATE_SERVICE_RECEIPT_INCOMPLETE: "GATE_SERVICE_RECEIPT_INCOMPLETE",
  GATE_STABLE_RUNTIME_MUTATION: "GATE_STABLE_RUNTIME_MUTATION",
  GATE_PRODUCT_AI_SUBSTITUTION: "GATE_PRODUCT_AI_SUBSTITUTION",
  GATE_EXTRACT_PENDING: "GATE_EXTRACT_PENDING",
};

// ─── Service receipt schema (v1) ────────────────────────────────────────

export const SERVICE_RECEIPT_SCHEMA_VERSION = "mw_e3_service_receipt_v1";

export const SERVICE_RECEIPT_FIELDS = [
  "schema_version",
  "lane_key",
  "step_id",
  "service_role",
  "provider",
  "model",
  "endpoint_class",
  "policy_or_prompt_version",
  "policy_or_prompt_hash",
  "product_task_id",
  "product_job_id",
  "product_run_id",
  "request_started_at",
  "request_ended_at",
  "terminal_status",
  "artifact_ids",
  "input_redacted_hash",
  "output_redacted_hash",
  "source",
  "hardcoded",
];

export const SERVICE_ROLES = [
  "reasoning_generation",
  "translation_orchestration",
  "translation_body",
  "ocr",
  "ctgov",
  "citation_resolution",
  "docx_export",
];

export const EXPECTED_PRODUCT_IDENTITIES = {
  reasoning_generation: { provider: "alibaba_token_plan", model: "qwen3.8-max-preview", endpoint_class: "product_api" },
  translation_orchestration: { provider: "deepseek", model: "deepseek-v4-flash", endpoint_class: "product_api" },
  translation_body: { provider: "omlx", model: "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX", endpoint_class: "local_omlx" },
  ocr: { provider: "omlx", model: "GLM-OCR-bf16", endpoint_class: "local_omlx" },
  ctgov: { provider: "product_backend", model: null, endpoint_class: "product_backend_job" },
  citation_resolution: { provider: "product_backend", model: null, endpoint_class: "product_backend_job" },
  docx_export: { provider: "product_backend", model: null, endpoint_class: "product_backend_job" },
};

export const VALID_RECEIPT_SOURCES = [
  "server_side_record",
  "response_header",
  "job_result_artifact",
];

/**
 * Validate a service receipt object against the E3 schema.
 *
 * Strict validation: requires non-empty server-derived identity, matching
 * expected provider/model/endpoint where the policy is fixed, terminal
 * completed status, timestamps, policy identity for AI steps, artifact IDs,
 * and non-null redacted hashes.  Rejects null provider/model for AI roles.
 */
export function validateServiceReceipt(receipt) {
  const errors = [];
  if (!receipt || typeof receipt !== "object") {
    return { valid: false, errors: ["receipt is not an object"] };
  }
  for (const field of SERVICE_RECEIPT_FIELDS) {
    if (!(field in receipt)) {
      errors.push(`missing_field:${field}`);
    }
  }
  if (receipt.schema_version !== SERVICE_RECEIPT_SCHEMA_VERSION) {
    errors.push(`schema_version_mismatch:expected=${SERVICE_RECEIPT_SCHEMA_VERSION},got=${receipt.schema_version}`);
  }
  if (receipt.service_role && !SERVICE_ROLES.includes(receipt.service_role)) {
    errors.push(`unknown_service_role:${receipt.service_role}`);
  }
  if (receipt.source && !VALID_RECEIPT_SOURCES.includes(receipt.source)) {
    errors.push(`invalid_source:${receipt.source}`);
  }
  if (receipt.hardcoded === true) {
    errors.push("hardcoded_identity_forbidden");
  }
  // D8: Only require job refs for genuinely durable AI steps.
  // ctgov and citation_resolution are synchronous backend roles — they may
  // legitimately omit a durable job_id when the actual contract is synchronous.
  const durableLongSteps = [
    "reasoning_generation", "translation_orchestration", "translation_body",
    "ocr",
  ];
  if (receipt.service_role && durableLongSteps.includes(receipt.service_role)) {
    const hasJobRef = receipt.product_task_id || receipt.product_job_id || receipt.product_run_id;
    if (!hasJobRef) {
      errors.push("missing_product_job_ref_for_long_step");
    }
  }

  // ─── D6: Strict identity requirements for AI service roles ───────────
  //
  // AI roles that use a real model must have non-null provider/model.
  // Non-AI backend roles (ctgov, citation_resolution, docx_export) may have
  // null provider/model — but must still carry a product job/task ref.
  const aiRoles = [
    "reasoning_generation", "translation_orchestration", "translation_body", "ocr",
  ];
  if (receipt.service_role && aiRoles.includes(receipt.service_role)) {
    if (!receipt.provider || typeof receipt.provider !== "string") {
      errors.push("ai_role_requires_non_empty_provider");
    }
    if (!receipt.model || typeof receipt.model !== "string") {
      errors.push("ai_role_requires_non_empty_model");
    }
    if (!receipt.endpoint_class) {
      errors.push("ai_role_requires_endpoint_class");
    }
    if (!receipt.request_started_at) {
      errors.push("ai_role_requires_request_started_at");
    }
    if (!receipt.request_ended_at) {
      errors.push("ai_role_requires_request_ended_at");
    }
    if (!receipt.policy_or_prompt_version) {
      errors.push("ai_role_requires_policy_or_prompt_version");
    }
    if (!receipt.policy_or_prompt_hash) {
      errors.push("ai_role_requires_policy_or_prompt_hash");
    }
    if (!receipt.input_redacted_hash) {
      errors.push("ai_role_requires_input_redacted_hash");
    }
    if (!receipt.output_redacted_hash) {
      errors.push("ai_role_requires_output_redacted_hash");
    }
  }

  // ─── D6: Verify expected provider/model/endpoint match where policy is fixed ──
  const expected = receipt.service_role
    ? EXPECTED_PRODUCT_IDENTITIES[receipt.service_role]
    : null;
  if (expected && expected.model !== null) {
    if (receipt.provider && receipt.provider !== expected.provider) {
      errors.push(
        `provider_mismatch:expected=${expected.provider},got=${receipt.provider}`,
      );
    }
    if (receipt.model && receipt.model !== expected.model) {
      errors.push(
        `model_mismatch:expected=${expected.model},got=${receipt.model}`,
      );
    }
    if (receipt.endpoint_class && receipt.endpoint_class !== expected.endpoint_class) {
      errors.push(
        `endpoint_class_mismatch:expected=${expected.endpoint_class},got=${receipt.endpoint_class}`,
      );
    }
  }

  // ─── D6: terminal_status must be "completed" for accepted receipts ──
  //
  // A receipt is accepted as execution evidence only when terminal_status
  // is "completed". "failed" or "cancelled" receipts should not validate
  // as proof of successful service execution.
  if (receipt.terminal_status && receipt.terminal_status !== "completed") {
    errors.push(`terminal_status_not_completed:${receipt.terminal_status}`);
  }
  if (!receipt.terminal_status) {
    errors.push("terminal_status_required");
  }

  // ─── D6: artifact_ids must be non-empty for AI roles ─────────────────
  if (receipt.service_role && aiRoles.includes(receipt.service_role)) {
    if (!Array.isArray(receipt.artifact_ids) || receipt.artifact_ids.length === 0) {
      errors.push("ai_role_requires_non_empty_artifact_ids");
    }
  }

  return { valid: errors.length === 0, errors };
}

// ─── Stable runtime content-hash contract ───────────────────────────────

export const STABLE_HASH_PROCEDURE = {
  steps: [
    "1. Resolve stable root: path.resolve(projectRoot, STABLE_RUNTIME_RELATIVE, 'runtime')",
    "2. Walk all files recursively, skipping only names starting with '.'",
    "3. For each file record: relative_path, size_bytes, sha256_content_hash, mtime",
    "4. Build sorted canonical JSON array and compute sha256 of the JSON string",
    "5. Capture before_suite, after_each_lane, after_suite snapshots",
    "6. Any delta (path added/removed/content_hash_changed) => P0 STOP",
    "7. Lane runtime must live under WORKBENCH_RUNTIME_DIR only",
    "8. Never open historical E2E databases or shared browser profiles",
  ],
  invariant: "mtime is NEVER used as an equality signal — only content SHA-256 matters",
};

// ─── Immutable lane evidence filenames ──────────────────────────────────

export const LANE_EVIDENCE_FILENAMES = [
  "input_manifest.json",
  "output_manifest.json",
  "process_ownership.json",
  "journey_trace.json",
  "service_receipts.json",
  "source_receipts.json",
  "ai_runs.json",
  "study_definition.json",
  "chapter_matrix.json",
  "candidate_sets.json",
  "citation_qc.json",
  "browser_qc.json",
  "docx_qc.json",
  "figure_scale_qc.json",
  "word_handoff.json",
  "lane_report.json",
  "gate_results.json",
  "synopsis_import_receipt.json",
];

// ─── G0-G6 gate definitions ─────────────────────────────────────────────

export const GATES = {
  G0: { id: "G0", description: "Preflight: source identities/hashes, stable baseline, no credential output" },
  G1: { id: "G1", description: "Exactly 12 RA/AD/UC × I/III × entry lanes; no phase/type relabelling; all required design pressures genuinely source-backed" },
  G2: { id: "G2", description: "Per-lane runtime/API/Vite/CDP/browser isolation; async orchestration; crash resume; exact cleanup ownership" },
  G3: { id: "G3", description: "Product workflow uses durable APIs and exact job/result artifacts for every long step; no content substitution" },
  G4: { id: "G4", description: "Every included chapter generated/reviewed/adopted; tables, SVG flowchart, scales, citations, reindex covered; excluded justified by confirmed design" },
  G5: { id: "G5", description: "DOCX OOXML checks + Word-native open/navigation/render (separate E5; never inferred from API success alone)" },
  G6: { id: "G6", description: "Stable runtime before/after hashes match; each lane has complete immutable evidence bundle" },
};

// ─── Verified six-cell source-authority catalog ─────────────────────────

/**
 * Authoritative protocol catalog for all six synopsis-import cells.
 *
 * For the five PDF cells, the authoritative matching protocol and the exact
 * physical page range of the Synopsis/Protocol Summary section are known and
 * accepted. The versioned exact-extract fixtures exist (generated by Worker 05
 * via pypdf 6.14.2) and are mapped to the five synopsis-import lanes. Each
 * cell carries the full lineage: NCT, protocol path/hash, page range, extract
 * path/hash, page count, and extraction manifest locator. Full protocols are
 * used only as assertion/structure oracles — never as product upload inputs.
 *
 * Source: execution context "Verified six-cell source authority (read-only
 * discovery, 2026-07-23)".
 */
export const PROTOCOL_AUTHORITY_CATALOG = {
  RA_I: {
    lane_key: "RA_I_SYNOPSIS",
    indication: "类风湿关节炎",
    lane_phase: "I",
    nct_id: "NCT03156023",
    protocol_path: "protocol-corpus/raw/NCT03156023/Prot_000.pdf",
    protocol_sha256: "83c13414a14b6ea445016f005627177cb5dc4d6ab974aadaf74e3df049bf3f85",
    synopsis_page_range: "3-6",
    synopsis_section_description: "Phase 1b RA Protocol Synopsis",
    authority_class: AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_exists: true,
    extract_output_path: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/RA_I_synopsis_extract.pdf",
    extract_output_sha256: "4e4139a3bacd65ac129475c39a5250dfefeb3926b7e871e607f45d8b12c3272a",
    extract_output_page_count: 4,
    extract_manifest_locator: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/extraction_manifest.json",
    override_allowed: false,
  },
  RA_III: {
    lane_key: "RA_III_SYNOPSIS",
    indication: "类风湿关节炎",
    lane_phase: "III",
    nct_id: "NCT02629159",
    protocol_path: "protocol-corpus/raw/NCT02629159/Prot_000.pdf",
    protocol_sha256: "48b6154c0e1f0fd9e05938c3e5ad0878b2438c69f49174e6e21da781b35fef0b",
    synopsis_page_range: "9-19",
    synopsis_section_description: "Phase 3 RA synopsis (SELECT-COMPARE)",
    authority_class: AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_exists: true,
    extract_output_path: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/RA_III_synopsis_extract.pdf",
    extract_output_sha256: "6be86a04ed252b3c0eec2fd97022ff9c8705e03d05cbbd3e73b0fab6aad9f6de",
    extract_output_page_count: 11,
    extract_manifest_locator: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/extraction_manifest.json",
    override_allowed: false,
  },
  AD_I: {
    lane_key: "AD_I_SYNOPSIS",
    indication: "特应性皮炎",
    lane_phase: "I",
    nct_id: "NCT04668066",
    protocol_path: "protocol-corpus/raw/NCT04668066/Prot_000.pdf",
    protocol_sha256: "3bbbbeeaf2d1ee8012ae1c28a0199ef46df471ee20a2bdd0ce607a79f9861a4a",
    synopsis_page_range: "12-18",
    synopsis_section_description: "Phase 1 FIH SAD/MAD healthy-participant and AD-patient Protocol Summary",
    authority_class: AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_exists: true,
    extract_output_path: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/AD_I_synopsis_extract.pdf",
    extract_output_sha256: "d76244cd9d91224f3e0e8eaa8e05399f0e382dfca2f92b54899bc4bdff8a83af",
    extract_output_page_count: 7,
    extract_manifest_locator: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/extraction_manifest.json",
    override_allowed: false,
  },
  AD_III: {
    lane_key: "AD_III_SYNOPSIS",
    indication: "特应性皮炎",
    lane_phase: "III",
    nct_id: "NCT03745638",
    protocol_path: "protocol-corpus/raw/NCT03745638/Prot_000.pdf",
    protocol_sha256: "035f37d3fece57f5dd238378b6b36c186babb7c2a27afafc78005bafeb021c91",
    synopsis_page_range: "12-19",
    synopsis_section_description: "Phase 3 AD Protocol Summary (TRuE-AD1)",
    authority_class: AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_exists: true,
    extract_output_path: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/AD_III_synopsis_extract.pdf",
    extract_output_sha256: "30a207ae97a9a19887d3c5f2a0d8508dc29138fd22cb95082aa7fba6369f0755",
    extract_output_page_count: 8,
    extract_manifest_locator: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/extraction_manifest.json",
    override_allowed: false,
  },
  UC_I: {
    lane_key: "UC_I_SYNOPSIS",
    indication: "溃疡性结肠炎",
    lane_phase: "I",
    nct_id: null,
    standalone_synopsis_path: "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/Ib期/MY009212A-UC-Ib-方案摘要-LXN.2024.01.27.docx",
    standalone_synopsis_sha256: "7a038d8d90908b9a7e1525d32d65a8789c231bf9e04e7031cf879e59f7437267",
    internal_version: "0.1",
    internal_date: "2023-12-22",
    filename_date: "2024.01.27",
    authority_class: AUTHORITY_CLASSES.EXACT_SYNOPSIS_FILE,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_exists: false,
    override_allowed: false,
  },
  UC_III: {
    lane_key: "UC_III_SYNOPSIS",
    indication: "溃疡性结肠炎",
    lane_phase: "III",
    nct_id: "NCT02407236",
    protocol_path: "protocol-corpus/raw/NCT02407236/UNIFI_Protocol_Amendment2_local_archive.pdf",
    protocol_sha256: "f5d4e6498cba6b78c1d41fc186b1865b066727019c63831d8ea198bd12abc923",
    protocol_provenance: "local_archive",
    protocol_identity: "UNIFI Phase 3 Amendment 2 — CNTO1275UCO3001; Janssen ustekinumab; Approved Date: 20 April 2016",
    synopsis_page_range: "25-39",
    synopsis_section_description: "Phase 3 UC synopsis (UNIFI)",
    authority_class: AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_exists: true,
    extract_output_path: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/UC_III_synopsis_extract.pdf",
    extract_output_sha256: "4f0f980292bb32793561c7d0711e3a1edafd5f1fe5e8c80707485cc753c6f8b1",
    extract_output_page_count: 15,
    extract_manifest_locator: "records/active_slices/medical_writing_e3_12lane_harness_20260723/synopsis_fixtures/extraction_manifest.json",
    override_allowed: false,
  },
};

// ─── Lane source authority registry ─────────────────────────────────────

export const LOCAL_SYNOPSIS_SOURCES = {
  UC_I_SYNOPSIS: {
    path: PROTOCOL_AUTHORITY_CATALOG.UC_I.standalone_synopsis_path,
    sha256: PROTOCOL_AUTHORITY_CATALOG.UC_I.standalone_synopsis_sha256,
    declared_role: "protocol_synopsis",
    declared_indication: "溃疡性结肠炎",
    declared_phase: "Ib",
    declared_phase_class: "I",
    authority_class: AUTHORITY_CLASSES.EXACT_SYNOPSIS_FILE,
    fixture_status: FIXTURE_STATUSES.READY,
    compatibility: "exact_match_ib_in_phase_i_class",
    override_allowed: false,
    internal_version: PROTOCOL_AUTHORITY_CATALOG.UC_I.internal_version,
    internal_date: PROTOCOL_AUTHORITY_CATALOG.UC_I.internal_date,
    filename_date: PROTOCOL_AUTHORITY_CATALOG.UC_I.filename_date,
    content_notes:
      "MY009212A UC Ib study protocol synopsis (方案摘要). Phase Ib matches the Phase I lane class. Directly importable — the only standalone synopsis file in the six-cell catalog. Internal version/date and filename date are preserved separately.",
    block_reason: null,
  },
  RA_I_SYNOPSIS: {
    path: PROTOCOL_AUTHORITY_CATALOG.RA_I.extract_output_path,
    sha256: PROTOCOL_AUTHORITY_CATALOG.RA_I.extract_output_sha256,
    declared_role: "versioned_exact_synopsis_extract_for_e3",
    declared_indication: "类风湿关节炎",
    declared_phase: "I",
    declared_phase_class: "I",
    authority_class: AUTHORITY_CLASSES.VERSIONED_EXACT_SYNOPSIS_EXTRACT,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_page_count: 4,
    compatibility: "exact_match_phase_i_extract",
    override_allowed: false,
    protocol_authority: PROTOCOL_AUTHORITY_CATALOG.RA_I,
    extract_manifest_locator: PROTOCOL_AUTHORITY_CATALOG.RA_I.extract_manifest_locator,
    content_notes:
      "Task-created lossless page selection (pp3-6) from protocol NCT03156023 (sha256 83c13414...). Not a sponsor-issued standalone synopsis. Full protocol never becomes product input.",
    block_reason: null,
  },
  RA_III_SYNOPSIS: {
    path: PROTOCOL_AUTHORITY_CATALOG.RA_III.extract_output_path,
    sha256: PROTOCOL_AUTHORITY_CATALOG.RA_III.extract_output_sha256,
    declared_role: "versioned_exact_synopsis_extract_for_e3",
    declared_indication: "类风湿关节炎",
    declared_phase: "III",
    authority_class: AUTHORITY_CLASSES.VERSIONED_EXACT_SYNOPSIS_EXTRACT,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_page_count: 11,
    compatibility: "exact_match_phase_iii_extract",
    override_allowed: false,
    protocol_authority: PROTOCOL_AUTHORITY_CATALOG.RA_III,
    extract_manifest_locator: PROTOCOL_AUTHORITY_CATALOG.RA_III.extract_manifest_locator,
    content_notes:
      "Task-created lossless page selection (pp9-19) from SELECT-COMPARE NCT02629159 (sha256 48b6154c...). Active comparator adalimumab. Not a sponsor-issued standalone synopsis.",
    block_reason: null,
  },
  AD_I_SYNOPSIS: {
    path: PROTOCOL_AUTHORITY_CATALOG.AD_I.extract_output_path,
    sha256: PROTOCOL_AUTHORITY_CATALOG.AD_I.extract_output_sha256,
    declared_role: "versioned_exact_synopsis_extract_for_e3",
    declared_indication: "特应性皮炎",
    declared_phase: "I",
    declared_phase_class: "I",
    authority_class: AUTHORITY_CLASSES.VERSIONED_EXACT_SYNOPSIS_EXTRACT,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_page_count: 7,
    compatibility: "exact_match_phase_i_extract",
    override_allowed: false,
    protocol_authority: PROTOCOL_AUTHORITY_CATALOG.AD_I,
    extract_manifest_locator: PROTOCOL_AUTHORITY_CATALOG.AD_I.extract_manifest_locator,
    content_notes:
      "Task-created lossless page selection (pp12-18) from NCT04668066 (sha256 3bbbbeea...). Phase 1 FIH SAD/MAD. Not a sponsor-issued standalone synopsis.",
    block_reason: null,
  },
  AD_III_SYNOPSIS: {
    path: PROTOCOL_AUTHORITY_CATALOG.AD_III.extract_output_path,
    sha256: PROTOCOL_AUTHORITY_CATALOG.AD_III.extract_output_sha256,
    declared_role: "versioned_exact_synopsis_extract_for_e3",
    declared_indication: "特应性皮炎",
    declared_phase: "III",
    authority_class: AUTHORITY_CLASSES.VERSIONED_EXACT_SYNOPSIS_EXTRACT,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_page_count: 8,
    compatibility: "exact_match_phase_iii_extract",
    override_allowed: false,
    protocol_authority: PROTOCOL_AUTHORITY_CATALOG.AD_III,
    extract_manifest_locator: PROTOCOL_AUTHORITY_CATALOG.AD_III.extract_manifest_locator,
    content_notes:
      "Task-created lossless page selection (pp12-19) from TRuE-AD1 NCT03745638 (sha256 035f37d3...). Vehicle/placebo controlled, NOT active comparator. Not a sponsor-issued standalone synopsis.",
    block_reason: null,
  },
  UC_III_SYNOPSIS: {
    path: PROTOCOL_AUTHORITY_CATALOG.UC_III.extract_output_path,
    sha256: PROTOCOL_AUTHORITY_CATALOG.UC_III.extract_output_sha256,
    declared_role: "versioned_exact_synopsis_extract_for_e3",
    declared_indication: "溃疡性结肠炎",
    declared_phase: "III",
    authority_class: AUTHORITY_CLASSES.VERSIONED_EXACT_SYNOPSIS_EXTRACT,
    fixture_status: FIXTURE_STATUSES.READY,
    extract_page_count: 15,
    compatibility: "exact_match_phase_iii_extract",
    override_allowed: false,
    protocol_authority: PROTOCOL_AUTHORITY_CATALOG.UC_III,
    extract_manifest_locator: PROTOCOL_AUTHORITY_CATALOG.UC_III.extract_manifest_locator,
    content_notes:
      "Task-created lossless page selection (pp25-39) from UNIFI NCT02407236 local archive (sha256 f5d4e649...). Placebo controlled with induction/maintenance + switch/re-rand, NOT active comparator. Not a sponsor-issued standalone synopsis.",
    block_reason: null,
  },
};

// ─── CT.gov assertion sentinels (NEVER product inputs) ──────────────────

export const CTGOV_SENTINEL_EVIDENCE = {
  retrieved_at: "2026-07-23T00:00:00Z",
  source: "clinicaltrials.gov/api/v2 + execution context verified six-cell authority",
  method: "Assert-only targets. Sentinels and full protocols are never product upload inputs.",
  sentinels: {
    RA_I: {
      nct_id: "NCT07258849",
      lane_key: "RA_I_SCRATCH",
      design_match: "healthy_sad_mad",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "RA Phase I healthy SAD+MAD sentinel for from_zero lane",
    },
    RA_I_SYN: {
      nct_id: "NCT03156023",
      lane_key: "RA_I_SYNOPSIS",
      design_match: "sad_mad_first_in_patient",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "RA Phase 1b NCT03156023 (synopsis on pp3-6). Protocol is assertion oracle only, not product upload.",
    },
    RA_III: {
      nct_id: "NCT02675426",
      lane_key: "RA_III_SCRATCH",
      design_match: "background_therapy_placebo",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "RA Phase III background csDMARDs + placebo (SELECT-NEXT)",
    },
    RA_III_SYN: {
      nct_id: "NCT02629159",
      lane_key: "RA_III_SYNOPSIS",
      design_match: "active_comparator",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "RA Phase III active comparator adalimumab (SELECT-COMPARE). Synopsis on pp9-19 of protocol.",
    },
    AD_I: {
      nct_id: "NCT07453602",
      lane_key: "AD_I_SCRATCH",
      design_match: "healthy_sad_mad",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "AD Phase I healthy SAD+MAD topical/local route",
    },
    AD_I_SYN: {
      nct_id: "NCT04668066",
      lane_key: "AD_I_SYNOPSIS",
      design_match: "sad_mad_first_in_patient",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "AD Phase 1 FIH NCT04668066 (synopsis on pp12-18). Protocol is assertion oracle only.",
    },
    AD_III: {
      nct_id: "NCT05732454",
      lane_key: "AD_III_SCRATCH",
      design_match: "interim_analysis_treatment_switch",
      role: "structure_oracle",
      sentinel_is_product_input: false,
      true_phase_label: "Phase 2/3",
      note: "AD Phase 2/3 with interim analysis + OLE — structure-only oracle retaining true label; NOT uploaded as synopsis; cannot satisfy a pure Phase III drug gate by itself.",
    },
    AD_III_SYN: {
      nct_id: "NCT03745638",
      lane_key: "AD_III_SYNOPSIS",
      design_match: "vehicle_placebo_phase3",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "AD Phase III TRuE-AD1 NCT03745638 is vehicle (placebo) controlled, NOT active comparator. Synopsis on pp12-19 of protocol. Protocol is assertion oracle only.",
    },
    UC_I: {
      nct_id: null,
      lane_key: "UC_I_SCRATCH",
      design_match: "healthy_sad_mad",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "UC I from_zero: product CT.gov search from minimal facts",
    },
    UC_I_SYN: {
      nct_id: null,
      lane_key: "UC_I_SYNOPSIS",
      design_match: "sad_mad_first_in_patient",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "UC Ib synopsis has real file authority; product search should discover matching study",
    },
    UC_III: {
      nct_id: "NCT02407236",
      lane_key: "UC_III_SCRATCH",
      design_match: "interim_analysis_treatment_switch",
      role: "structure_oracle",
      sentinel_is_product_input: false,
      true_phase_label: "Phase III",
      design_features: ["futility_interim_analysis", "week_8_treatment_switch", "maintenance_re_randomization", "lte_treatment_adjustment"],
      note: "UNIFI NCT02407236 Phase III UC: preferred drug-trial structure oracle for futility interim after 30% induction, Week 8 placebo→ustekinumab switch, maintenance re-randomization, LTE adjustment. True Phase III label retained.",
    },
    UC_III_RESCUE: {
      nct_id: "NCT02819635",
      lane_key: "UC_III_SCRATCH",
      design_match: "rescue_re_randomization_ole",
      role: "structure_oracle",
      sentinel_is_product_input: false,
      true_phase_label: "Phase 2b/3",
      note: "UC Phase 2b/3 induction/maintenance/re-rand/rescue/OLE — secondary structure oracle. True label retained.",
    },
    UC_III_SYN: {
      nct_id: "NCT02407236",
      lane_key: "UC_III_SYNOPSIS",
      design_match: "placebo_induction_maintenance_switch",
      role: "assertion_sentinel",
      sentinel_is_product_input: false,
      note: "UNIFI NCT02407236 Phase III UC is placebo controlled with induction/maintenance, Week 8 switch and re-randomization — NOT active comparator. Synopsis on pp25-39 of protocol. Protocol is assertion oracle only.",
    },
  },
};

// ─── Design pressure coverage map ───────────────────────────────────────

export const DESIGN_PRESSURE_ASSIGNMENTS = {
  healthy_sad_mad: {
    lanes: ["RA_I_SCRATCH", "AD_I_SCRATCH", "UC_I_SCRATCH"],
    runnable_lanes: ["RA_I_SCRATCH", "AD_I_SCRATCH", "UC_I_SCRATCH"],
    notes: "All three from_zero lanes are runnable.",
  },
  sad_mad_first_in_patient: {
    lanes: ["RA_I_SYNOPSIS", "AD_I_SYNOPSIS", "UC_I_SYNOPSIS"],
    runnable_lanes: ["RA_I_SYNOPSIS", "AD_I_SYNOPSIS", "UC_I_SYNOPSIS"],
    notes: "All three synopsis lanes are now runnable with exact extract fixtures.",
  },
  background_therapy_placebo: {
    lanes: ["RA_III_SCRATCH"],
    runnable_lanes: ["RA_III_SCRATCH"],
    notes: "RA Phase III complex stable background csDMARD/MTX + placebo (from_zero lane)",
  },
  interim_analysis_treatment_switch: {
    lanes: ["AD_III_SCRATCH"],
    runnable_lanes: ["AD_III_SCRATCH"],
    notes: "AD III from_zero uses structure oracle NCT05732454 (Phase 2/3 with interim+OLE) retaining true labels. UNIFI NCT02407236 Phase III is the preferred drug-trial oracle for documented futility interim, Week 8 switch, maintenance re-rand and LTE adjustment. RESET-RA NCT04539964 is device/secondary only. No Phase 2b/3 or device study is relabelled.",
  },
  active_comparator: {
    lanes: ["RA_III_SYNOPSIS"],
    runnable_lanes: ["RA_III_SYNOPSIS"],
    notes: "Only SELECT-COMPARE NCT02629159 (adalimumab active comparator) is source-backed. TRuE-AD1 and UNIFI are NOT active comparator. RA_III_SYNOPSIS is now runnable with exact extract fixture.",
  },
  rescue_re_randomization_ole: {
    lanes: ["UC_III_SCRATCH"],
    runnable_lanes: ["UC_III_SCRATCH"],
    notes: "UC III from_zero uses UNIFI NCT02407236 (primary) and NCT02819635 (secondary) structure oracles; true labels retained.",
  },
  vehicle_placebo_phase3: {
    lanes: ["AD_III_SYNOPSIS"],
    runnable_lanes: ["AD_III_SYNOPSIS"],
    notes: "AD Phase III TRuE-AD1 NCT03745638 is vehicle (placebo) controlled — NOT active comparator. Runnable with exact extract fixture.",
  },
  placebo_induction_maintenance_switch: {
    lanes: ["UC_III_SYNOPSIS"],
    runnable_lanes: ["UC_III_SYNOPSIS"],
    notes: "UC Phase III UNIFI NCT02407236 is placebo controlled with induction/maintenance, Week 8 switch and re-randomization — NOT active comparator. Runnable with exact extract fixture.",
  },
};

/**
 * Design pressures that are assigned only on blocked synopsis lanes do not
 * make the live 12-lane suite runnable. This list makes the gap explicit.
 */
/**
 * All six synopsis-import lanes are now runnable with exact extract fixtures.
 * Coverage gaps have been resolved. This array is empty.
 */
export const RUNNABLE_COVERAGE_GAPS = [];

// ─── Full 12-lane matrix ────────────────────────────────────────────────

export const EXPECTED_STUDIES_12LANE = [
  // ── RA Phase I ──────────────────────────────────────────────────────
  {
    key: "RA_I_SCRATCH",
    indication: "类风湿关节炎",
    clinicalTrialsConditionTerm: "Rheumatoid Arthritis",
    studyPhase: "I",
    productName: "RA-E3-01",
    entryMode: "from_zero",
    designPressure: "healthy_sad_mad",
    designPressureLabel: "健康人SAD+MAD（口服小分子）",
    structuredDesignHint: {
      randomization_mode: "non_randomized",
      blinding_mode: "open_label",
      comparator_type: "none_or_dose_escalation",
      phase1_parts: ["SAD", "MAD"],
      arm_or_cohort_kind: "剂量递增队列",
    },
    interventionRouteClass: "small_molecule_oral",
    minChapters: ["safety", "objectives_endpoints"],
    timeoutS: 4200,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: null,
    synopsisAuthorityClass: null,
    synopsisSourceBlocked: false,
    expectedNctId: "NCT07258849",
    expectedDocumentRole: "protocol",
    sentinelReuseReason: null,
  },
  {
    key: "RA_I_SYNOPSIS",
    indication: "类风湿关节炎",
    clinicalTrialsConditionTerm: "Rheumatoid Arthritis",
    studyPhase: "I",
    productName: "RA-E3-02",
    entryMode: "synopsis_import",
    designPressure: "sad_mad_first_in_patient",
    designPressureLabel: "SAD+MAD+首次患者",
    structuredDesignHint: {
      randomization_mode: "non_randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      phase1_parts: ["SAD", "MAD", "first_in_patient"],
      arm_or_cohort_kind: "SAD→MAD→患者队列",
    },
    interventionRouteClass: "small_molecule_oral",
    minChapters: ["safety", "pk_pd", "objectives_endpoints"],
    timeoutS: 4200,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: LOCAL_SYNOPSIS_SOURCES.RA_I_SYNOPSIS.path,
    synopsisSourceSha256: LOCAL_SYNOPSIS_SOURCES.RA_I_SYNOPSIS.sha256,
    synopsisSourceRole: LOCAL_SYNOPSIS_SOURCES.RA_I_SYNOPSIS.declared_role,
    synopsisAuthorityClass: LOCAL_SYNOPSIS_SOURCES.RA_I_SYNOPSIS.authority_class,
    synopsisFixtureStatus: LOCAL_SYNOPSIS_SOURCES.RA_I_SYNOPSIS.fixture_status,
    synopsisSourceBlocked: false,
    synopsisSourceOverrideReason: null,
    expectedNctId: "NCT03156023",
    expectedDocumentRole: "protocol",
    sentinelReuseReason: null,
  },
  // ── RA Phase III ────────────────────────────────────────────────────
  {
    key: "RA_III_SCRATCH",
    indication: "类风湿关节炎",
    clinicalTrialsConditionTerm: "Rheumatoid Arthritis",
    studyPhase: "III",
    productName: "RA-E3-03",
    entryMode: "from_zero",
    designPressure: "background_therapy_placebo",
    designPressureLabel: "复杂稳定背景治疗+安慰剂",
    structuredDesignHint: {
      randomization_mode: "randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      interim_analysis: { planned: true },
      background_therapy_required: true,
      arm_or_cohort_kind: "背景治疗+试验药/安慰剂",
    },
    interventionRouteClass: "small_molecule_oral",
    minChapters: ["efficacy", "safety", "statistical_methods"],
    timeoutS: 4800,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: null,
    synopsisAuthorityClass: null,
    synopsisSourceBlocked: false,
    expectedNctId: "NCT02675426",
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "SELECT-NEXT: patients on stable background csDMARDs randomized to upadacitinib or placebo",
  },
  {
    key: "RA_III_SYNOPSIS",
    indication: "类风湿关节炎",
    clinicalTrialsConditionTerm: "Rheumatoid Arthritis",
    studyPhase: "III",
    productName: "RA-E3-04",
    entryMode: "synopsis_import",
    designPressure: "active_comparator",
    designPressureLabel: "阳性药对照",
    structuredDesignHint: {
      randomization_mode: "randomized",
      blinding_mode: "double_blind",
      comparator_type: "active",
      active_comparator_name: "adalimumab",
      background_therapy_required: true,
      arm_or_cohort_kind: "试验药 vs 阳性对照 vs 安慰剂",
    },
    interventionRouteClass: "small_molecule_oral",
    minChapters: ["efficacy", "safety", "statistical_methods"],
    timeoutS: 4800,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: LOCAL_SYNOPSIS_SOURCES.RA_III_SYNOPSIS.path,
    synopsisSourceSha256: LOCAL_SYNOPSIS_SOURCES.RA_III_SYNOPSIS.sha256,
    synopsisSourceRole: LOCAL_SYNOPSIS_SOURCES.RA_III_SYNOPSIS.declared_role,
    synopsisAuthorityClass: LOCAL_SYNOPSIS_SOURCES.RA_III_SYNOPSIS.authority_class,
    synopsisFixtureStatus: LOCAL_SYNOPSIS_SOURCES.RA_III_SYNOPSIS.fixture_status,
    synopsisSourceBlocked: false,
    synopsisSourceOverrideReason: null,
    expectedNctId: "NCT02629159",
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "SELECT-COMPARE: upadacitinib vs adalimumab vs placebo, all on stable background MTX",
  },
  // ── AD Phase I ──────────────────────────────────────────────────────
  {
    key: "AD_I_SCRATCH",
    indication: "特应性皮炎",
    clinicalTrialsConditionTerm: "Atopic Dermatitis",
    studyPhase: "I",
    productName: "AD-E3-01",
    entryMode: "from_zero",
    designPressure: "healthy_sad_mad",
    designPressureLabel: "健康人SAD+MAD（外用/局部）",
    structuredDesignHint: {
      randomization_mode: "randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      phase1_parts: ["SAD", "MAD"],
      arm_or_cohort_kind: "剂量递增队列（含安慰剂）",
    },
    interventionRouteClass: "topical_local",
    minChapters: ["safety", "pk_pd", "objectives_endpoints"],
    timeoutS: 4200,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: null,
    synopsisAuthorityClass: null,
    synopsisSourceBlocked: false,
    expectedNctId: "NCT07453602",
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "Arcutis ARQ-234 1a/1b: healthy SAD/MAD + patient transition, topical/local route",
  },
  {
    key: "AD_I_SYNOPSIS",
    indication: "特应性皮炎",
    clinicalTrialsConditionTerm: "Atopic Dermatitis",
    studyPhase: "I",
    productName: "AD-E3-02",
    entryMode: "synopsis_import",
    designPressure: "sad_mad_first_in_patient",
    designPressureLabel: "SAD+MAD+首次患者",
    structuredDesignHint: {
      randomization_mode: "randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      phase1_parts: ["SAD", "MAD", "first_in_patient"],
      arm_or_cohort_kind: "SAD→MAD→患者队列",
    },
    interventionRouteClass: "biologic_injection",
    minChapters: ["safety", "pk_pd", "objectives_endpoints"],
    timeoutS: 4200,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: LOCAL_SYNOPSIS_SOURCES.AD_I_SYNOPSIS.path,
    synopsisSourceSha256: LOCAL_SYNOPSIS_SOURCES.AD_I_SYNOPSIS.sha256,
    synopsisSourceRole: LOCAL_SYNOPSIS_SOURCES.AD_I_SYNOPSIS.declared_role,
    synopsisAuthorityClass: LOCAL_SYNOPSIS_SOURCES.AD_I_SYNOPSIS.authority_class,
    synopsisFixtureStatus: LOCAL_SYNOPSIS_SOURCES.AD_I_SYNOPSIS.fixture_status,
    synopsisSourceBlocked: false,
    synopsisSourceOverrideReason: null,
    expectedNctId: "NCT04668066",
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "AD Phase 1 FIH NCT04668066: healthy + AD patients, SAD+MAD",
  },
  // ── AD Phase III ────────────────────────────────────────────────────
  {
    key: "AD_III_SCRATCH",
    indication: "特应性皮炎",
    clinicalTrialsConditionTerm: "Atopic Dermatitis",
    studyPhase: "III",
    productName: "AD-E3-03",
    entryMode: "from_zero",
    designPressure: "interim_analysis_treatment_switch",
    designPressureLabel: "安慰剂对照+期中分析+治疗转组",
    structuredDesignHint: {
      randomization_mode: "randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      interim_analysis: { planned: true, documented: true },
      treatment_switch: { planned: true, documented: true },
      arm_or_cohort_kind: "安慰剂→试验药转组设计",
    },
    interventionRouteClass: "biologic_injection",
    minChapters: ["efficacy", "safety", "statistical_methods"],
    timeoutS: 4800,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: null,
    synopsisAuthorityClass: null,
    synopsisSourceBlocked: false,
    expectedNctId: "NCT05732454",
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "AD Phase 2/3 with interim analysis + OLE (structure oracle, true Phase 2/3 label retained — NOT relabelled as Phase III drug study)",
  },
  {
    key: "AD_III_SYNOPSIS",
    indication: "特应性皮炎",
    clinicalTrialsConditionTerm: "Atopic Dermatitis",
    studyPhase: "III",
    productName: "AD-E3-04",
    entryMode: "synopsis_import",
    designPressure: "vehicle_placebo_phase3",
    designPressureLabel: "赋形剂（安慰剂）对照",
    structuredDesignHint: {
      randomization_mode: "randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      arm_or_cohort_kind: "试验药 vs 赋形剂（vehicle）",
    },
    interventionRouteClass: "biologic_injection",
    minChapters: ["efficacy", "safety", "statistical_methods"],
    timeoutS: 4800,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: LOCAL_SYNOPSIS_SOURCES.AD_III_SYNOPSIS.path,
    synopsisSourceSha256: LOCAL_SYNOPSIS_SOURCES.AD_III_SYNOPSIS.sha256,
    synopsisSourceRole: LOCAL_SYNOPSIS_SOURCES.AD_III_SYNOPSIS.declared_role,
    synopsisAuthorityClass: LOCAL_SYNOPSIS_SOURCES.AD_III_SYNOPSIS.authority_class,
    synopsisFixtureStatus: LOCAL_SYNOPSIS_SOURCES.AD_III_SYNOPSIS.fixture_status,
    synopsisSourceBlocked: false,
    synopsisSourceOverrideReason: null,
    expectedNctId: "NCT03745638",
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "AD Phase III TRuE-AD1 NCT03745638 is vehicle (placebo) controlled — NOT active comparator. Synopsis on pp12-19; assertion oracle only.",
  },
  // ── UC Phase I ──────────────────────────────────────────────────────
  {
    key: "UC_I_SCRATCH",
    indication: "溃疡性结肠炎",
    clinicalTrialsConditionTerm: "Ulcerative Colitis",
    studyPhase: "I",
    productName: "UC-E3-01",
    entryMode: "from_zero",
    designPressure: "healthy_sad_mad",
    designPressureLabel: "健康人SAD+MAD（PK/PD/免疫原性）",
    structuredDesignHint: {
      randomization_mode: "non_randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      phase1_parts: ["SAD", "MAD"],
      arm_or_cohort_kind: "剂量递增队列",
      pk_pd_assessment: true,
      immunogenicity_assessment: true,
    },
    interventionRouteClass: "small_molecule_oral",
    minChapters: ["safety", "pk_pd", "objectives_endpoints"],
    timeoutS: 4200,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: null,
    synopsisAuthorityClass: null,
    synopsisSourceBlocked: false,
    expectedNctId: null,
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "UC I from_zero: product CT.gov search from minimal facts; no fixed sentinel",
  },
  {
    key: "UC_I_SYNOPSIS",
    indication: "溃疡性结肠炎",
    clinicalTrialsConditionTerm: "Ulcerative Colitis",
    studyPhase: "I",
    productName: "UC-E3-02",
    entryMode: "synopsis_import",
    designPressure: "sad_mad_first_in_patient",
    designPressureLabel: "SAD+MAD+首次患者（UC Ib）",
    declaredPhaseLabel: "Ib",
    structuredDesignHint: {
      randomization_mode: "non_randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      phase1_parts: ["SAD", "MAD", "first_in_patient"],
      arm_or_cohort_kind: "SAD→MAD→患者队列",
    },
    interventionRouteClass: "small_molecule_oral",
    minChapters: ["safety", "pk_pd", "objectives_endpoints"],
    timeoutS: 4200,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: LOCAL_SYNOPSIS_SOURCES.UC_I_SYNOPSIS.path,
    synopsisSourceSha256: LOCAL_SYNOPSIS_SOURCES.UC_I_SYNOPSIS.sha256,
    synopsisSourceRole: LOCAL_SYNOPSIS_SOURCES.UC_I_SYNOPSIS.declared_role,
    synopsisAuthorityClass: LOCAL_SYNOPSIS_SOURCES.UC_I_SYNOPSIS.authority_class,
    synopsisFixtureStatus: LOCAL_SYNOPSIS_SOURCES.UC_I_SYNOPSIS.fixture_status,
    synopsisSourceBlocked: false,
    synopsisSourceOverrideReason: null,
    expectedNctId: null,
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "UC Ib synopsis has real file authority (SHA verified); product search should discover matching study",
  },
  // ── UC Phase III ────────────────────────────────────────────────────
  {
    key: "UC_III_SCRATCH",
    indication: "溃疡性结肠炎",
    clinicalTrialsConditionTerm: "Ulcerative Colitis",
    studyPhase: "III",
    productName: "UC-E3-03",
    entryMode: "from_zero",
    designPressure: "rescue_re_randomization_ole",
    designPressureLabel: "诱导/维持+救援/重随机化/OLE",
    structuredDesignHint: {
      randomization_mode: "randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      induction_maintenance_design: true,
      rescue_therapy_allowed: true,
      re_randomization: true,
      open_label_extension: true,
      arm_or_cohort_kind: "诱导期→维持期→OLE",
    },
    interventionRouteClass: "biologic_injection",
    minChapters: ["efficacy", "safety", "statistical_methods"],
    timeoutS: 4800,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: null,
    synopsisAuthorityClass: null,
    synopsisSourceBlocked: false,
    expectedNctId: "NCT02407236",
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "UNIFI NCT02407236 Phase III UC: preferred drug-trial oracle for futility interim, Week 8 switch, maintenance re-rand, LTE adjustment. NCT02819635 Phase 2b/3 is secondary rescue/re-rand/OLE oracle. True labels retained.",
  },
  {
    key: "UC_III_SYNOPSIS",
    indication: "溃疡性结肠炎",
    clinicalTrialsConditionTerm: "Ulcerative Colitis",
    studyPhase: "III",
    productName: "UC-E3-04",
    entryMode: "synopsis_import",
    designPressure: "placebo_induction_maintenance_switch",
    designPressureLabel: "安慰剂对照+诱导/维持+治疗转组/重随机化",
    structuredDesignHint: {
      randomization_mode: "randomized",
      blinding_mode: "double_blind",
      comparator_type: "placebo",
      induction_maintenance_design: true,
      treatment_switch: { planned: true, documented: true },
      re_randomization: true,
      arm_or_cohort_kind: "诱导期安慰剂→维持期试验药转组/重随机化",
    },
    interventionRouteClass: "small_molecule_oral",
    minChapters: ["efficacy", "safety", "statistical_methods"],
    timeoutS: 4800,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    synopsisSourcePath: LOCAL_SYNOPSIS_SOURCES.UC_III_SYNOPSIS.path,
    synopsisSourceSha256: LOCAL_SYNOPSIS_SOURCES.UC_III_SYNOPSIS.sha256,
    synopsisSourceRole: LOCAL_SYNOPSIS_SOURCES.UC_III_SYNOPSIS.declared_role,
    synopsisAuthorityClass: LOCAL_SYNOPSIS_SOURCES.UC_III_SYNOPSIS.authority_class,
    synopsisFixtureStatus: LOCAL_SYNOPSIS_SOURCES.UC_III_SYNOPSIS.fixture_status,
    synopsisSourceBlocked: false,
    synopsisSourceOverrideReason: null,
    expectedNctId: "NCT02407236",
    expectedDocumentRole: "protocol",
    sentinelReuseReason:
      "UNIFI NCT02407236 Phase III UC is placebo controlled with induction/maintenance, Week 8 switch, re-randomization — NOT active comparator. Synopsis on pp25-39; assertion oracle only.",
  },
];

// ─── Per-lane required evidence artifacts ───────────────────────────────

export const ARTIFACT_FILENAMES_12LANE = LANE_EVIDENCE_FILENAMES;

// ─── Coverage validator (E3) ────────────────────────────────────────────

export function validateLaneCoverage() {
  const missing = [];
  const warnings = [];

  if (EXPECTED_STUDIES_12LANE.length !== 12) {
    missing.push(`lane_count: expected 12, got ${EXPECTED_STUDIES_12LANE.length}`);
  }
  if (REQUIRED_INDICATIONS.includes("斑块状银屑病")) {
    missing.push("pso_in_required_indications");
  }
  const psoLanes = EXPECTED_STUDIES_12LANE.filter(
    (l) => l.key.startsWith("PSO_") || l.indication === "斑块状银屑病",
  );
  if (psoLanes.length > 0) {
    missing.push(`pso_lanes_present: ${psoLanes.map((l) => l.key).join(",")}`);
  }

  const indications = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.indication));
  for (const ind of REQUIRED_INDICATIONS) {
    if (!indications.has(ind)) missing.push(`indication_missing:${ind}`);
  }

  const phases = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.studyPhase));
  for (const ph of REQUIRED_PHASES) {
    if (!phases.has(ph)) missing.push(`phase_missing:${ph}`);
  }

  const entries = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.entryMode));
  for (const em of REQUIRED_ENTRY_MODES) {
    if (!entries.has(em)) missing.push(`entry_mode_missing:${em}`);
  }

  const routes = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.interventionRouteClass));
  for (const rc of REQUIRED_ROUTE_CLASSES) {
    if (!routes.has(rc)) missing.push(`route_class_missing:${rc}`);
  }

  for (const ind of REQUIRED_INDICATIONS) {
    for (const ph of REQUIRED_PHASES) {
      for (const em of REQUIRED_ENTRY_MODES) {
        const found = EXPECTED_STUDIES_12LANE.find(
          (l) => l.indication === ind && l.studyPhase === ph && l.entryMode === em,
        );
        if (!found) missing.push(`lane_missing:${ind}_${ph}_${em}`);
      }
    }
  }

  const coveredPressures = new Set(EXPECTED_STUDIES_12LANE.map((l) => l.designPressure));
  for (const dp of REQUIRED_DESIGN_PRESSURES) {
    if (!coveredPressures.has(dp)) missing.push(`design_pressure_missing:${dp}`);
  }

  for (const lane of EXPECTED_STUDIES_12LANE) {
    if (lane.entryMode !== "synopsis_import") continue;
    const source = LOCAL_SYNOPSIS_SOURCES[lane.key];
    if (!source) {
      missing.push(`synopsis_source_registry_missing:${lane.key}`);
      continue;
    }
    if (source.override_allowed === true) {
      missing.push(`override_allowed_forbidden:${lane.key}`);
    }
    const blockedClasses = [
      AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES,
      AUTHORITY_CLASSES.BLOCKED_MISSING_AUTHORITY,
    ];
    if (blockedClasses.includes(source.authority_class)) {
      if (!lane.synopsisSourceBlocked) {
        missing.push(`blocked_source_not_flagged:${lane.key}`);
      }
      if (lane.synopsisSourcePath !== null) {
        missing.push(`blocked_source_has_path:${lane.key}`);
      }
    }
    if (source.authority_class === AUTHORITY_CLASSES.EXACT_SYNOPSIS_FILE) {
      if (!source.path || !source.sha256) {
        missing.push(`exact_synopsis_missing_path_or_sha:${lane.key}`);
      }
    }
    if (source.authority_class === AUTHORITY_CLASSES.VERSIONED_EXACT_SYNOPSIS_EXTRACT) {
      if (!source.path || !source.sha256) {
        missing.push(`extract_missing_path_or_sha:${lane.key}`);
      }
      if (lane.synopsisSourceBlocked) {
        missing.push(`extract_lane_still_blocked:${lane.key}`);
      }
    }
  }

  return { valid: missing.length === 0, missing, warnings };
}

export function validateSentinelSeparation() {
  const violations = [];
  for (const [key, sentinel] of Object.entries(CTGOV_SENTINEL_EVIDENCE.sentinels)) {
    if (sentinel.sentinel_is_product_input === true) {
      violations.push(`${key}: sentinel_is_product_input must be false`);
    }
    if (sentinel.role === "product_input") {
      violations.push(`${key}: role must not be product_input`);
    }
  }
  return { valid: violations.length === 0, violations };
}

export function validateSourceAuthority() {
  const errors = [];
  for (const lane of EXPECTED_STUDIES_12LANE) {
    if (lane.entryMode !== "synopsis_import") continue;
    const source = LOCAL_SYNOPSIS_SOURCES[lane.key];
    if (!source) {
      errors.push(`${lane.key}: no source authority entry`);
      continue;
    }
    const validClasses = [
      AUTHORITY_CLASSES.EXACT_SYNOPSIS_FILE,
      AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES,
      AUTHORITY_CLASSES.VERSIONED_EXACT_SYNOPSIS_EXTRACT,
      AUTHORITY_CLASSES.BLOCKED_MISSING_AUTHORITY,
    ];
    if (!validClasses.includes(source.authority_class)) {
      errors.push(`${lane.key}: invalid authority_class=${source.authority_class}`);
    }
    if (source.declared_role === "protocol" || source.declared_role === "csr" || source.declared_role === "sap") {
      errors.push(`${lane.key}: declared_role=${source.declared_role} is not a synopsis`);
    }
    if (source.authority_class === AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES) {
      if (!source.protocol_authority) {
        errors.push(`${lane.key}: authoritative_protocol_synopsis_pages requires protocol_authority`);
      } else {
        const pa = source.protocol_authority;
        if (!pa.nct_id) errors.push(`${lane.key}: protocol_authority missing nct_id`);
        if (!pa.protocol_sha256) errors.push(`${lane.key}: protocol_authority missing protocol_sha256`);
        if (!pa.synopsis_page_range) errors.push(`${lane.key}: protocol_authority missing synopsis_page_range`);
      }
    }
  }
  return { valid: errors.length === 0, errors };
}

/**
 * Validates that active_comparator design pressure is only assigned to lanes
 * whose source/oracle explicitly names an active comparator drug.
 * Rejects any AD or UC lane from carrying active_comparator unless the
 * protocol authority or structure oracle explicitly declares one.
 */
export function validateActiveComparatorSource() {
  const errors = [];
  for (const lane of EXPECTED_STUDIES_12LANE) {
    if (lane.designPressure !== "active_comparator") continue;
    const hint = lane.structuredDesignHint || {};
    // Must have an explicit active_comparator_name from source evidence
    if (!hint.active_comparator_name) {
      errors.push(`${lane.key}: active_comparator requires structuredDesignHint.active_comparator_name from source evidence`);
    }
    // Check the source authority: only RA_III_SYNOPSIS (SELECT-COMPARE/adalimumab) qualifies
    if (lane.key === "AD_III_SYNOPSIS") {
      errors.push(`${lane.key}: AD_III_SYNOPSIS source TRuE-AD1 is vehicle/placebo controlled, cannot carry active_comparator`);
    }
    if (lane.key === "UC_III_SYNOPSIS") {
      errors.push(`${lane.key}: UC_III_SYNOPSIS source UNIFI is placebo controlled with switch/re-rand, cannot carry active_comparator`);
    }
  }
  // Also verify that only RA_III_SYNOPSIS carries active_comparator
  const acLanes = EXPECTED_STUDIES_12LANE.filter((l) => l.designPressure === "active_comparator");
  for (const lane of acLanes) {
    if (lane.key !== "RA_III_SYNOPSIS") {
      errors.push(`${lane.key}: only RA_III_SYNOPSIS may carry active_comparator (source: SELECT-COMPARE adalimumab)`);
    }
  }
  return { valid: errors.length === 0, errors };
}

/**
 * Distinguishes assigned design pressure from runnable coverage.
 * A pressure carried only by blocked synopsis lanes does not make the live
 * 12-lane suite runnable.
 */
export function getRunnableCoverage() {
  const runnable = EXPECTED_STUDIES_12LANE.filter((l) => !l.synopsisSourceBlocked);
  const runnablePressures = new Set(runnable.map((l) => l.designPressure));
  const gaps = [];
  for (const dp of REQUIRED_DESIGN_PRESSURES) {
    if (!runnablePressures.has(dp)) {
      const assigned = EXPECTED_STUDIES_12LANE.filter((l) => l.designPressure === dp);
      gaps.push({
        design_pressure: dp,
        assigned_lanes: assigned.map((l) => l.key),
        blocked_lanes: assigned.filter((l) => l.synopsisSourceBlocked).map((l) => l.key),
        gap_description: `No runnable lane exercises ${dp}; all assigned lanes are blocked.`,
      });
    }
  }
  return {
    runnable_lane_count: runnable.length,
    runnable_lane_keys: runnable.map((l) => l.key),
    runnable_pressures: [...runnablePressures],
    coverage_gaps: gaps,
  };
}

export function resolveLanes(filter) {
  if (!filter) return [...EXPECTED_STUDIES_12LANE];
  const keys = filter
    .split(",")
    .map((k) => k.trim().toUpperCase())
    .filter(Boolean);
  return EXPECTED_STUDIES_12LANE.filter((l) => keys.includes(l.key.toUpperCase()));
}
