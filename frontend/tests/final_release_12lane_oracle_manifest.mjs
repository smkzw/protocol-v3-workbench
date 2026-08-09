/**
 * Lane Oracle Manifest — E3 12-lane harness.
 *
 * Separates product_inputs (extracted synopsis fixtures or standalone DOCX)
 * from assertion_oracles (NCT sentinels) and structure_oracles (design
 * reference patterns with true labels that are never uploaded as synopsis).
 *
 * For the five PDF-extract synopsis lanes (versioned_exact_synopsis_extract),
 * the manifest carries the full protocol-authority lineage (protocol path,
 * hash, NCT, page range, extract path/hash, manifest locator) in the oracle
 * layer only — never in product_inputs.synopsis_source.  A full protocol is
 * not a product input.
 *
 * UC_I_SYNOPSIS has a standalone exact DOCX synopsis; its protocol_authority
 * is null unless an explicit authoritative mapping provides one.
 *
 * @module final_release_12lane_oracle_manifest
 */

import {
  EXPECTED_STUDIES_12LANE,
  LOCAL_SYNOPSIS_SOURCES,
  CTGOV_SENTINEL_EVIDENCE,
  PROTOCOL_AUTHORITY_CATALOG,
  AUTHORITY_CLASSES,
} from "./final_release_12lane_config.mjs";

export const ORACLE_ROLES = {
  PRODUCT_INPUT: "product_input",
  ASSERTION_SENTINEL: "assertion_sentinel",
  STRUCTURE_ORACLE: "structure_oracle",
  PROTOCOL_AUTHORITY: "protocol_authority",
};

/**
 * For each lane, defines:
 * - product_inputs: what the product actually receives
 * - assertion_oracles: NCT IDs the product must rediscover (assert-only)
 * - structure_oracles: design reference patterns with true labels (never uploaded)
 * - protocol_authority: full protocol lineage for extract lanes (oracle layer only)
 */
export const LANE_ORACLE_MANIFEST = EXPECTED_STUDIES_12LANE.map((lane) => ({
  lane_key: lane.key,
  indication: lane.indication,
  phase: lane.studyPhase,
  entry_mode: lane.entryMode,
  design_pressure: lane.designPressure,
  product_inputs: buildProductInputs(lane),
  assertion_oracles: buildAssertionOracles(lane),
  structure_oracles: buildStructureOracles(lane),
  protocol_authority: buildProtocolAuthority(lane),
}));

function buildProductInputs(lane) {
  const inputs = {
    entry_mode: lane.entryMode,
    minimal_facts: {
      product_name: lane.productName,
      indication: lane.indication,
      study_phase: lane.studyPhase,
    },
  };

  if (lane.entryMode === "synopsis_import") {
    const source = LOCAL_SYNOPSIS_SOURCES[lane.key];
    // Product input is the exact extracted synopsis fixture (or standalone DOCX for UC Ib).
    // The full protocol is never a product input.
    inputs.synopsis_source = {
      path: source.path,
      sha256: source.sha256,
      declared_role: source.declared_role,
      declared_indication: source.declared_indication,
      declared_phase: source.declared_phase,
      declared_phase_class: source.declared_phase_class || null,
      authority_class: source.authority_class,
      fixture_status: source.fixture_status || null,
      compatibility: source.compatibility,
      override_allowed: source.override_allowed,
      block_reason: source.block_reason,
      ...(source.extract_page_count ? { extract_page_count: source.extract_page_count } : {}),
      ...(lane.declaredPhaseLabel ? { lane_phase_label: lane.declaredPhaseLabel } : {}),
    };
  }

  return inputs;
}

function buildAssertionOracles(lane) {
  const oracles = [];
  for (const [key, sentinel] of Object.entries(CTGOV_SENTINEL_EVIDENCE.sentinels)) {
    if (sentinel.lane_key === lane.key) {
      oracles.push({
        oracle_role: ORACLE_ROLES.ASSERTION_SENTINEL,
        nct_id: sentinel.nct_id,
        design_match: sentinel.design_match,
        note: sentinel.note,
        is_product_input: false,
      });
    }
  }
  return oracles;
}

function buildStructureOracles(lane) {
  const oracles = [];

  // AD III from_zero: structure oracle for interim+switch (true Phase 2/3)
  if (lane.key === "AD_III_SCRATCH") {
    oracles.push({
      oracle_role: ORACLE_ROLES.STRUCTURE_ORACLE,
      nct_id: "NCT05732454",
      true_phase_label: "Phase 2/3",
      design_features: ["interim_analysis", "open_label_extension"],
      note: "AD Phase 2/3 with interim analysis + OLE. Structure-only oracle retaining true label. NOT uploaded as synopsis. Cannot satisfy a pure Phase III drug gate by itself.",
      is_product_input: false,
    });
  }

  // UC III from_zero: UNIFI is preferred drug-trial oracle for interim/switch/rescue/re-rand/OLE
  if (lane.key === "UC_III_SCRATCH") {
    oracles.push({
      oracle_role: ORACLE_ROLES.STRUCTURE_ORACLE,
      nct_id: "NCT02407236",
      true_phase_label: "Phase III",
      is_preferred_drug_trial_oracle: true,
      design_features: [
        "futility_interim_analysis",
        "week_8_treatment_switch",
        "maintenance_re_randomization",
        "lte_treatment_adjustment",
      ],
      note: "UNIFI NCT02407236 Phase III UC: preferred drug-trial oracle. Planned futility interim after 30% induction completion, Week 8 placebo nonresponder switch to IV ustekinumab, maintenance re-randomization, LTE treatment adjustment. True Phase III label retained.",
      is_product_input: false,
    });
    oracles.push({
      oracle_role: ORACLE_ROLES.STRUCTURE_ORACLE,
      nct_id: "NCT02819635",
      true_phase_label: "Phase 2b/3",
      is_preferred_drug_trial_oracle: false,
      design_features: ["induction_maintenance", "re_randomization", "rescue_therapy", "open_label_extension"],
      note: "UC Phase 2b/3 secondary structure oracle for rescue/re-rand/OLE. True label retained.",
      is_product_input: false,
    });
  }

  // RA III: RESET-RA device study is secondary only
  if (lane.key === "RA_III_SCRATCH" || lane.key === "RA_III_SYNOPSIS") {
    oracles.push({
      oracle_role: ORACLE_ROLES.STRUCTURE_ORACLE,
      nct_id: "NCT04539964",
      true_phase_label: "Phase III (device study)",
      is_preferred_drug_trial_oracle: false,
      design_features: ["interim_analysis", "one_way_crossover"],
      note: "RESET-RA NCT04539964 is a device study with formal interim analysis and one-way crossover. Secondary/structure-only oracle — NOT the primary drug-design oracle.",
      is_product_input: false,
    });
  }

  // SLE Ib biologic structure oracle for immunogenicity reference
  if (lane.key === "UC_I_SCRATCH" || lane.key === "UC_I_SYNOPSIS") {
    oracles.push({
      oracle_role: ORACLE_ROLES.STRUCTURE_ORACLE,
      nct_id: "NCT03724916",
      true_phase_label: "Phase Ib",
      design_features: ["biologic_immunogenicity", "first_in_patient"],
      note: "SLE Phase Ib biologic immunogenicity structure oracle. NOT uploaded as synopsis.",
      is_product_input: false,
    });
  }

  return oracles;
}

/**
 * Builds the oracle-layer protocol-authority record for extract lanes.
 *
 * For versioned_exact_synopsis_extract lanes (the five PDF-extract synopsis
 * lanes), binds the full lineage: NCT, canonical protocol path, protocol SHA,
 * synopsis page range, extract path, extract SHA, extract manifest locator,
 * authority class, READY fixture status, and is_product_input:false.
 *
 * For exact_synopsis_file lanes (UC Ib standalone DOCX), no full-protocol
 * authority record is required unless an explicit mapping provides one.
 *
 * For from_zero lanes, returns null.
 */
function buildProtocolAuthority(lane) {
  if (lane.entryMode !== "synopsis_import") return null;
  const source = LOCAL_SYNOPSIS_SOURCES[lane.key];
  if (!source) return null;

  // versioned_exact_synopsis_extract: five PDF-extract lanes with full lineage
  if (source.authority_class === AUTHORITY_CLASSES.VERSIONED_EXACT_SYNOPSIS_EXTRACT) {
    const pa = source.protocol_authority;
    if (!pa) return null;
    return {
      oracle_role: ORACLE_ROLES.PROTOCOL_AUTHORITY,
      lane_key: lane.key,
      nct_id: pa.nct_id,
      protocol_path: pa.protocol_path,
      protocol_sha256: pa.protocol_sha256,
      synopsis_page_range: pa.synopsis_page_range,
      synopsis_section_description: pa.synopsis_section_description,
      authority_class: source.authority_class,
      fixture_status: source.fixture_status,
      extract_exists: pa.extract_exists,
      extract_output_path: pa.extract_output_path,
      extract_output_sha256: pa.extract_output_sha256,
      extract_output_page_count: pa.extract_output_page_count,
      extract_manifest_locator: pa.extract_manifest_locator,
      is_product_input: false,
      note: `Full protocol lineage for ${lane.key}. Protocol is an oracle, not a product upload. Extract is a task-created lossless page selection.`,
    };
  }

  // authoritative_protocol_synopsis_pages (legacy/obsolete class — kept for compatibility)
  if (source.authority_class === AUTHORITY_CLASSES.AUTHORITATIVE_PROTOCOL_SYNOPSIS_PAGES) {
    const pa = source.protocol_authority;
    if (!pa) return null;
    return {
      oracle_role: ORACLE_ROLES.PROTOCOL_AUTHORITY,
      lane_key: lane.key,
      nct_id: pa.nct_id,
      protocol_path: pa.protocol_path,
      protocol_sha256: pa.protocol_sha256,
      synopsis_page_range: pa.synopsis_page_range,
      synopsis_section_description: pa.synopsis_section_description,
      authority_class: pa.authority_class,
      fixture_status: pa.fixture_status,
      extract_exists: pa.extract_exists,
      extract_output_path: pa.extract_output_path || null,
      extract_output_sha256: pa.extract_output_sha256 || null,
      extract_output_page_count: pa.extract_output_page_count || null,
      extract_manifest_locator: pa.extract_manifest_locator || null,
      is_product_input: false,
      note: `Authoritative protocol NCT record. Full protocol is an oracle, not a product upload.`,
    };
  }

  // exact_synopsis_file (UC Ib standalone DOCX): no full-protocol authority needed
  return null;
}

// ─── Oracle separation validator ────────────────────────────────────────

export function validateOracleSeparation() {
  const violations = [];

  for (const manifest of LANE_ORACLE_MANIFEST) {
    for (const oracle of manifest.assertion_oracles) {
      if (oracle.is_product_input !== false) {
        violations.push(`${manifest.lane_key}: assertion oracle ${oracle.nct_id} has is_product_input != false`);
      }
    }
    for (const oracle of manifest.structure_oracles) {
      if (oracle.is_product_input !== false) {
        violations.push(`${manifest.lane_key}: structure oracle ${oracle.nct_id} has is_product_input != false`);
      }
    }
    if (manifest.protocol_authority && manifest.protocol_authority.is_product_input !== false) {
      violations.push(`${manifest.lane_key}: protocol_authority has is_product_input != false`);
    }
  }

  // Verify that no product_inputs.synopsis_source.path contains a full protocol path
  for (const manifest of LANE_ORACLE_MANIFEST) {
    if (manifest.entry_mode !== "synopsis_import") continue;
    const ss = manifest.product_inputs.synopsis_source;
    if (!ss || !ss.path) continue;
    // Product input paths must be extract fixtures or standalone synopses,
    // never full protocols from protocol-corpus
    if (ss.path.includes("protocol-corpus/raw/")) {
      violations.push(`${manifest.lane_key}: full protocol path must not appear in product_inputs.synopsis_source.path`);
    }
  }

  return { valid: violations.length === 0, violations };
}

export function getFullManifest() {
  return {
    schema_version: "mw_e3_oracle_manifest_v1",
    lane_count: LANE_ORACLE_MANIFEST.length,
    lanes: LANE_ORACLE_MANIFEST,
  };
}
