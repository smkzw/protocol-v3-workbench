/**
 * Four-indication configuration for the cross-indication E2E harness.
 *
 * This file contains ONLY configuration and acceptance sentinels.  It does not
 * fabricate evidence.  Every value here is either a structural constant or an
 * acceptance sentinel derived from CROSS_INDICATION_E2E_MATRIX.md and
 * SOURCE_GOLDEN_FACTS.md.
 *
 * Expected study targets are sentinels: each full lane must discover them via a
 * fresh product ClinicalTrials.gov search, not use them as local input.
 */

/**
 * Stress lanes.  Each lane starts from a fresh product search and official
 * download.  The expected NCT and required public document are acceptance
 * sentinels — the lane proves the product search found the intended study and
 * that the chosen document role matches.
 */
export const EXPECTED_STUDIES = [
  {
    key: "AD",
    indication: "特应性皮炎",
    clinicalTrialsConditionTerm: "Atopic Dermatitis",
    studyPhase: "II",
    productName: "AD-01",
    primaryStress:
      "dermatology SoA; EASI/IGA/NRS; topical/systemic washout",
    minChapters: ["eligibility", "objectives_endpoints"],
    timeoutS: 3600,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    expectedNctId: "NCT05923099",
    expectedDocumentFilename: "Prot_SAP_000.pdf",
    expectedDocumentRole: "protocol_sap",
  },
  {
    key: "PNH",
    indication: "阵发性睡眠性血红蛋白尿",
    clinicalTrialsConditionTerm: "Paroxysmal Nocturnal Hemoglobinuria",
    studyPhase: "III",
    productName: "PNH-01",
    primaryStress:
      "rare hematology; complement MoA; LDH/transfusion independence; BTH; comparator-symbol OCR pressure",
    minChapters: ["objectives_endpoints", "safety"],
    timeoutS: 4200,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    expectedNctId: "NCT04654468",
    expectedDocumentFilename: "Prot_002.pdf",
    expectedDocumentRole: "protocol",
  },
  {
    key: "OBESITY",
    indication: "肥胖/超重",
    clinicalTrialsConditionTerm: "Obesity",
    studyPhase: "II",
    productName: "OB-01",
    primaryStress:
      "metabolic disease; large ambulatory population; dose escalation; %weight primary endpoint; table-page OCR",
    minChapters: ["objectives_endpoints", "eligibility"],
    timeoutS: 4200,
    ocrTimeoutS: 600,
    translationTimeoutS: 900,
    candidateTimeoutS: 900,
    expectedNctId: "NCT04707313",
    expectedDocumentFilename: "Prot_000.pdf",
    expectedDocumentRole: "protocol",
  },
  {
    key: "SLE",
    indication: "系统性红斑狼疮",
    clinicalTrialsConditionTerm: "Systemic Lupus Erythematosus",
    studyPhase: "I",
    productName: "SLE-01",
    primaryStress:
      "Phase 1b multiple ascending dose; five sequential cohorts; PK/PD/immunogenicity; DLRM/BLRM; redacted doses must not be guessed",
    minChapters: ["safety", "objectives_endpoints"],
    timeoutS: 4800,
    ocrTimeoutS: 900,
    translationTimeoutS: 1200,
    candidateTimeoutS: 900,
    expectedNctId: "NCT03451422",
    expectedDocumentFilename: "Prot_000.pdf",
    expectedDocumentRole: "protocol",
  },
];

/** Backwards-compatible alias used by structure QC. */
export const INDICATIONS = EXPECTED_STUDIES;

export const GATE_CODES = {
  GATE_TRANSLATION_TIMEOUT: {
    stage: "translation_batch",
    severity: "P1",
    description: "Translation batch remained non-terminal beyond the configured evidence window",
  },
  GATE_FLASH_PLAN_UNAVAILABLE: {
    stage: "toc_planning",
    severity: "P1",
    description: "DeepSeek Flash document planning failed its bounded structure contract",
  },
  GATE_HY_MT2_UNAVAILABLE: {
    stage: "translating_hy_mt2",
    severity: "P1",
    description: "Hy-MT2 model not loaded in oMLX or product returned 5xx",
  },
  GATE_FLASH_QC_UNAVAILABLE: {
    stage: "integration_qc",
    severity: "P1",
    description: "Flash integration QC endpoint missing or returned 5xx",
  },
  GATE_FIDELITY_BLOCKED: {
    stage: "integration_qc",
    severity: "P1",
    description: "Translated chapters completed but all selected content was blocked by deterministic fidelity checks",
  },
  GATE_OCR_UNAVAILABLE: {
    stage: "ocr_running",
    severity: "P1",
    description: "GLM-OCR-bf16 not loaded in oMLX or OCR endpoint returned 5xx",
  },
  GATE_PRO_CANDIDATE_UNAVAILABLE: {
    stage: "candidate_generation",
    severity: "P1",
    description: "DeepSeek Pro route returned 5xx or produced empty candidates",
  },
  GATE_CTGOV_UNREACHABLE: {
    stage: "searching",
    severity: "P1",
    description: "ClinicalTrials.gov API unreachable",
  },
  GATE_DOWNLOAD_HOST_NOT_ALLOWED: {
    stage: "downloading",
    severity: "P1",
    description: "Final download URL host is not in the product allowlist",
  },
  GATE_BACKEND_STAGE_MISSING: {
    stage: "parsing",
    severity: "P1",
    description: "Backend returned 404 for a required stage endpoint",
  },
  GATE_EXPECTED_STUDY_NOT_FOUND: {
    stage: "searching",
    severity: "P1",
    description: "Fresh product search snapshot did not contain the expected NCT",
  },
  GATE_DOCUMENT_ROLE_MISMATCH: {
    stage: "downloading",
    severity: "P1",
    description: "Downloaded document role does not match the expected Protocol/SAP role",
  },
  GATE_WORKING_COPY_MUTATED: {
    stage: "candidate_generation",
    severity: "P0",
    description: "Candidate generation mutated the working copy",
  },
};

/**
 * Stages required by the CROSS_INDICATION_E2E_MATRIX.md operation chain.
 */
export const REQUIRED_STAGE_SEQUENCE = [
  "searching",
  "screening",
  "downloading",
  "parsing",
  "extracting",
  "ocr_running",
  "validating",
  "prepared",
  "toc_planning",
  "translating_hy_mt2",
  "integration_qc",
  "translation_batch",
  "medical_review",
  "corpus_admission",
  "chapter_mapping",
  "candidate_ready",
];

/**
 * JSON artifacts emitted per CROSS_INDICATION_E2E_MATRIX.md.
 */
export const ARTIFACT_FILENAMES = [
  "source_receipts.json",
  "pipeline_lineage.json",
  "chapter_mapping.json",
  "candidate_sets.json",
  "quality_scorecard.json",
  "browser_qc.json",
];

/**
 * Comparator symbols and numeric constraints that must be preserved
 * from SOURCE_GOLDEN_FACTS.md.  These are acceptance sentinels for
 * post-hoc blind review, not harness inputs.
 */
export const GOLDEN_FACT_PATTERNS = {
  AD: [
    /EASI\s*[≥>=]+\s*12/,
    /vIGA-AD\s*[≥>=]+\s*3/,
    /BSA\s*[≥>=]+\s*10\s*%/,
    /18\s*[-–]\s*75\s*岁/,
  ],
  PNH: [
    /LDH\s*[<≤]+\s*1\.5\s*[x×]\s*ULN/,
    /LDH\s*[≥>=]+\s*2\s*[x×]\s*ULN/,
    /hemoglobin\s*[<≤]\s*10\s*g\/dL/,
    /[≥>=]+\s*18\s*years/,
  ],
  OBESITY: [
    /BMI\s*[≥>=]+\s*30\.0\s*kg\/m2/,
    /90\s*(?:天|days)/,
    /<\s*5\s*kg/,
  ],
  SLE: [
    /5\s*(?:个)?(?:顺序|sequential).*(?:队列|cohorts?)/i,
    /12\s*(?:周|weeks?).*6\s*(?:周|weeks?)/i,
    /SLEDAI-?2K/i,
    /(?:DLRM|BLRM)/i,
  ],
};

/**
 * Score dimensions required by quality_scorecard.schema.json.
 */
export const SCORE_DIMENSIONS = [
  "usability",
  "fluency",
  "scientific_accuracy",
  "regulatory_style",
  "traceability",
  "no_unsupported_addition",
];

/**
 * Representative chapter matrix for candidate generation.
 * Each indication generates candidates for at least 2 chapters.
 */
export const REPRESENTATIVE_CHAPTERS = {
  AD: ["eligibility", "objectives_endpoints"],
  PNH: ["objectives_endpoints", "safety"],
  OBESITY: ["objectives_endpoints", "eligibility"],
  SLE: ["safety", "objectives_endpoints"],
};

/**
 * Product section targets for section-specific AI candidate generation.
 * The reference anchor and target protocol section are intentionally distinct:
 * evidence is selected by extraction anchor, then mapped to the M11 writing
 * section where a medical writer would use it.
 */
export const CHAPTER_TARGET_SECTIONS = {
  eligibility: "ich_m11_5_2",
  objectives_endpoints: "ich_m11_3_1_1",
  safety: "ich_m11_9_2_4",
  schedule: "ich_m11_1_3",
  statistics: "ich_m11_10_4_1_1",
  synopsis: "ich_m11_1_1",
};

/**
 * ClinicalTrials.gov host allowlist for download URL validation.
 */
export const ALLOWED_DOWNLOAD_HOSTS = [
  "clinicaltrials.gov",
  "cdn.clinicaltrials.gov",
];

/**
 * Stable runtime directory.  Default is two levels above the project root,
 * matching the workspace layout:
 *   workbench/ -> implementation/ -> 医学经理工作台/
 *   runtime/ sits at the same level as implementation/.
 */
export const STABLE_RUNTIME_RELATIVE = "../..";
