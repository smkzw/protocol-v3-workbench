from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from scripts.monitoring_mapping_candidate_audit import (
    CandidateRecord,
    audit_candidates,
    load_candidate_json,
    load_candidate_sqlite,
    main,
    render_markdown,
)


def _mapping(
    domain: str,
    field: str,
    role: str,
    *,
    field_kind: str = "source_collected",
    derivation_lineage: dict | None = None,
    standards_reference: dict | None = None,
) -> dict:
    value = {
        "domain": domain,
        "source_field": field,
        "recommended_role": role,
        "field_kind": field_kind,
        "related_fields": [],
    }
    if derivation_lineage is not None:
        value["derivation_lineage"] = derivation_lineage
    if standards_reference is not None:
        value["standards_reference"] = standards_reference
    return value


def _candidate(
    project_id: str,
    job_id: str,
    business_key: str,
    mappings: list[dict],
    *,
    deterministic: set[tuple[str, str]] | None = None,
    evidence_overrides: dict[tuple[str, str], dict] | None = None,
    extra_evidence: list[tuple[str, str]] | None = None,
) -> dict:
    deterministic = deterministic or set()
    evidence_overrides = evidence_overrides or {}
    evidence = []
    for index, mapping in enumerate(mappings, start=1):
        pair = (mapping["domain"], mapping["source_field"])
        raw_fields = {
            "domain": pair[0],
            "field": pair[1],
            "inferred_type": "string",
            "representative_values": [],
            **evidence_overrides.get(pair, {}),
        }
        evidence.append(
            {
                "evidence_id": f"evidence-{job_id}-{index}",
                "raw_fields": raw_fields,
            }
        )
    for index, pair in enumerate(extra_evidence or [], start=len(evidence) + 1):
        evidence.append(
            {
                "evidence_id": f"evidence-{job_id}-{index}",
                "raw_fields": {
                    "domain": pair[0],
                    "field": pair[1],
                    "inferred_type": "string",
                    "representative_values": [],
                },
            }
        )
    return {
        "candidate_id": f"candidate-{job_id}",
        "candidate_type": "listing_field_mapping_set",
        "job_id": job_id,
        "project_id": project_id,
        "prompt_version": "monitoring-listing-field-mapping-v13",
        "status": "proposed",
        "created_at": "2026-07-30T01:00:00Z",
        "structured_payload": {
            "field_mappings": mappings,
            "mapping_provenance": {
                "schema_version": "monitoring_field_mapping_provenance_v1",
                "field_origins": [
                    {
                        "domain": mapping["domain"],
                        "source_field": mapping["source_field"],
                        "origin": (
                            "deterministic_rule"
                            if (mapping["domain"], mapping["source_field"])
                            in deterministic
                            else "independent_ai"
                        ),
                    }
                    for mapping in mappings
                ],
            },
        },
        "evidence": evidence,
    }


def _record(candidate: dict, business_key: str) -> CandidateRecord:
    return CandidateRecord(
        job_id=candidate["job_id"],
        project_id=candidate["project_id"],
        business_key=business_key,
        prompt_version=candidate["prompt_version"],
        job_status="completed",
        candidate_status="proposed",
        created_at=candidate["created_at"],
        updated_at="2026-07-30T01:05:00Z",
        candidate=candidate,
    )


def _codes(report: dict) -> set[str]:
    return {item["code"] for item in report["findings"]}


def test_clean_cross_project_candidates_preserve_stable_technical_roles() -> None:
    records = []
    for project, batch in (("project-a", "batch-a"), ("project-b", "batch-b")):
        key = f"listing-field-mapping:{batch}:AE:0001-of-0001"
        candidate = _candidate(
            project,
            f"job-{project}",
            key,
            [
                _mapping(
                    "AE",
                    "SITEID",
                    "site_identifier",
                    field_kind="source_metadata",
                ),
                _mapping(
                    "AE",
                    "PTCODE",
                    "meddra_pt_code",
                    field_kind="standardized_coded",
                    derivation_lineage={
                        "source_fields": ["PTTERM"],
                        "coding_system": "MedDRA",
                        "dictionary_version_field": "MDRAVER",
                        "coding_chain_id": "ae-meddra",
                    },
                ),
                _mapping(
                    "AE",
                    "PTTERM",
                    "meddra_pt_term",
                    field_kind="standardized_coded",
                    derivation_lineage={
                        "source_fields": ["PTCODE"],
                        "coding_system": "MedDRA",
                        "dictionary_version_field": "MDRAVER",
                        "coding_chain_id": "ae-meddra",
                    },
                ),
                _mapping(
                    "AE",
                    "MDRAVER",
                    "meddra_dictionary_version",
                    field_kind="source_metadata",
                ),
            ],
            deterministic={("AE", "SITEID")},
        )
        records.append(_record(candidate, key))

    report = audit_candidates(records, source={"kind": "test"})
    reversed_report = audit_candidates(
        list(reversed(records)),
        source={"kind": "test"},
    )

    assert report["summary"]["project_count"] == 2
    assert report["summary"]["error_count"] == 0
    assert report["report_sha256"] == reversed_report["report_sha256"]
    assert "XJOB-TECH-ROLE-DRIFT" not in _codes(report)
    coding = report["inventories"]["coding_lineage"]
    assert coding == [
        {
            "coding_system": "MedDRA",
            "field_count": 6,
            "complete_lineage_count": 4,
            "incomplete_lineage_count": 0,
            "support_field_count": 2,
            "support_fields": ["MDRAVER"],
            "versions": ["MDRAVER"],
            "field_kinds": ["source_metadata", "standardized_coded"],
        }
    ]


def test_audit_detects_cross_job_medical_and_lineage_failures() -> None:
    first_key = "listing-field-mapping:batch-a:AE:0001-of-0002"
    first = _candidate(
        "project-a",
        "job-a1",
        first_key,
        [
            _mapping(
                "AE",
                "SITEID",
                "site_identifier",
                field_kind="source_metadata",
            ),
            _mapping("AE", "AESTDAT", "ae_start_date"),
            _mapping(
                "AE",
                "PTCODE",
                "meddra_pt_code",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": [],
                    "coding_system": "MedDRA",
                },
            ),
            _mapping(
                "AE",
                "CALC",
                "ae_duration",
                field_kind="deterministic_derived",
                derivation_lineage={
                    "source_fields": ["MISSING_SOURCE"],
                    "formula": "",
                    "user_confirmed": False,
                },
            ),
            _mapping("AE", "CDLQIQ1", "cdlqi_total_item_score"),
        ],
        deterministic={("AE", "SITEID")},
        evidence_overrides={
            ("AE", "AESTDAT"): {
                "inferred_type": "date",
                "representative_values": ["2024-10-uk"],
            }
        },
        extra_evidence=[("AE", "EXPECTED_BUT_MISSING")],
    )
    second_key = "listing-field-mapping:batch-b:CM:0001-of-0001"
    second = _candidate(
        "project-b",
        "job-b1",
        second_key,
        [
            _mapping(
                "CM",
                "SITEID",
                "subject_identifier",
                field_kind="source_metadata",
            ),
            _mapping("CM", "CMTRT", "ip_administration_dose"),
            _mapping("CM", "ACTION", "ip_dose_adjustment_and_restart_date"),
            _mapping(
                "CM",
                "WHOCODE",
                "whodrug_code",
                field_kind="source_collected",
            ),
        ],
        deterministic={("CM", "SITEID")},
    )

    report = audit_candidates(
        [_record(first, first_key), _record(second, second_key)]
    )
    codes = _codes(report)

    assert "XJOB-TECH-ROLE-DRIFT" in codes
    assert "XJOB-CM-IP-BOUNDARY" in codes
    assert "XJOB-IP-ACTION-COLLAPSE" in codes
    assert "XJOB-CODING-FALSE-STANDARDIZED" not in codes
    assert "XJOB-CODING-LINEAGE-INCOMPLETE" in codes
    assert "XJOB-DERIVED-LINEAGE-INCOMPLETE" in codes
    assert "XJOB-DATE-PRECISION-UNDECLARED" in codes
    assert "XJOB-SCALE-ROLE-AMBIGUOUS" in codes
    assert "XJOB-FIELD-COVERAGE" in codes
    # Collapse and incomplete-standardized shapes are deterministically
    # quarantined/downgraded by draft assembly and must be resolved warnings.
    assert report["summary"]["error_count"] == 6
    collapse = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-IP-ACTION-COLLAPSE"
    )
    assert collapse["severity"] == "warning"
    assert (
        "resolution=draft_assembly_multi_action_quarantine"
        in collapse["variants"]
    )
    standardized = [
        item
        for item in report["findings"]
        if item["code"] == "XJOB-CODING-LINEAGE-INCOMPLETE"
        and "field_kind=standardized_coded" in item["variants"]
    ]
    assert standardized
    assert all(item["severity"] == "warning" for item in standardized)
    assert all(
        "resolution=draft_assembly_incomplete_coding_downgrade"
        in item["variants"]
        for item in standardized
    )


def test_source_scale_total_is_observation_not_false_derived_claim() -> None:
    key = "listing-field-mapping:batch-a:CDLQI:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-scale",
        key,
        [
            _mapping("CDLQI", "CDLQIRES", "cdlqi_total_score"),
            _mapping("CDLQI", "CDLQIQ1", "cdlqi_question_1_score"),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    finding = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-SCALE-SOURCE-TOTAL"
    )
    assert finding["severity"] == "observation"
    assert report["summary"]["error_count"] == 0


def test_score_or_assessment_number_is_a_scale_role_error() -> None:
    key = "listing-field-mapping:batch-a:RES_7:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-scale-ambiguous",
        key,
        [
            _mapping(
                "RES_7",
                "ITOSSNUM",
                "clinical_score_or_assessment_number",
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    finding = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-SCALE-ROLE-AMBIGUOUS"
    )
    assert finding["severity"] == "error"
    assert report["summary"]["error_count"] == 1


def test_audit_applies_draft_context_normalization_and_ignores_empty_variant() -> None:
    first_key = "listing-field-mapping:batch-a:AE:0001-of-0001"
    first = _candidate(
        "project-a",
        "job-context-a",
        first_key,
        [
            _mapping("AE", "PAGE", "form_page_identifier"),
            _mapping(
                "AE",
                "LINE",
                "listing_line_number",
                field_kind="source_metadata",
            ),
        ],
    )
    second_key = "listing-field-mapping:batch-a:CM:0001-of-0001"
    second = _candidate(
        "project-a",
        "job-context-b",
        second_key,
        [
            _mapping(
                "CM",
                "PAGE",
                "page_display_name",
                field_kind="source_metadata",
            ),
            _mapping(
                "CM",
                "LINE",
                "record_sequence_number",
                field_kind="source_metadata",
            ),
        ],
    )
    empty_key = "listing-field-mapping:batch-a:DD:0001-of-0001"
    empty = _candidate(
        "project-a",
        "job-context-empty",
        empty_key,
        [
            _mapping(
                "DD",
                "PAGE",
                "unmapped_field",
                field_kind="unmapped",
            ),
            _mapping(
                "DD",
                "LINE",
                "unmapped_field",
                field_kind="unmapped",
            ),
        ],
    )

    report = audit_candidates(
        [
            _record(first, first_key),
            _record(second, second_key),
            _record(empty, empty_key),
        ]
    )

    assert "XJOB-TECH-ROLE-DRIFT" not in _codes(report)
    assert report["summary"]["error_count"] == 0


def test_unstandardized_coding_candidates_do_not_create_chain_drift_error() -> None:
    key = "listing-field-mapping:batch-a:CM:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-coding-candidates",
        key,
        [
            _mapping(
                "CM",
                "CMCODE1",
                "whodrug_code_candidate",
                field_kind="source_collected",
                standards_reference={
                    "reference_name": "WHODrug",
                    "reference_only": True,
                },
            ),
            _mapping(
                "CM",
                "CMCODE2",
                "whodrug_code_candidate",
                field_kind="unmapped",
                standards_reference={
                    "reference_name": "WHODrug",
                    "reference_only": True,
                },
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    assert "XJOB-CODING-CHAIN-DRIFT" not in _codes(report)
    assert report["summary"]["error_count"] == 0


def test_standardized_coding_waits_for_declared_cross_chunk_version_support() -> None:
    key = "listing-field-mapping:batch-a:MH:0001-of-0002"
    candidate = _candidate(
        "project-a",
        "job-mh-partial",
        key,
        [
            _mapping("MH", "MHTERM", "mh_reported_term"),
            _mapping(
                "MH",
                "HLGTCODE",
                "meddra_hlgt_code",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["MHTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    finding = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-CODING-LINEAGE-INCOMPLETE"
    )
    assert finding["severity"] == "warning"
    assert "domain_chunks=incomplete" in finding["variants"]
    assert "XJOB-CODING-FALSE-STANDARDIZED" not in _codes(report)


def test_declared_coding_support_is_warning_until_draft_normalization() -> None:
    key = "listing-field-mapping:batch-a:AE:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-ae-support",
        key,
        [
            _mapping(
                "AE",
                "MDRAVER",
                "meddra_dictionary_version",
                field_kind="source_collected",
            ),
            _mapping(
                "AE",
                "PTCODE",
                "meddra_pt_code",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["PTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _mapping(
                "AE",
                "PTTERM",
                "meddra_pt_term",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["PTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    assert report["summary"]["error_count"] == 0
    assert "XJOB-CODING-CHAIN-DRIFT" not in _codes(report)
    finding = next(
        item
        for item in report["findings"]
        if item["code"]
        == "XJOB-CODING-SUPPORT-METADATA-NORMALIZATION"
    )
    assert finding["severity"] == "warning"
    assert (
        "resolution=draft_assembly_coding_support_metadata"
        in finding["variants"]
    )


def test_audit_finds_unresolved_ip_drug_coding_and_ae_chain_boundaries() -> None:
    daa_key = "listing-field-mapping:batch-a:DAB:0001-of-0001"
    daa = _candidate(
        "project-a",
        "job-dab",
        daa_key,
        [
            _mapping("DAB", "DABMECO", "compliance_percentage_value"),
            _mapping("DAB", "DABNRNUM", "returned_or_unreturned_item_count"),
            _mapping("DAB", "DABWDOSE", "dab_withdrawn_dose_amount"),
        ],
    )
    cm_key = "listing-field-mapping:batch-a:CM:0001-of-0001"
    cm = _candidate(
        "project-a",
        "job-cm",
        cm_key,
        [
            _mapping("CM", "ATC1CODE", "atc_level1_code"),
            _mapping("CM", "ATC1TEXT", "atc_level1_term"),
            _mapping(
                "CM",
                "DRUGVER",
                "drug_dictionary_version",
                field_kind="source_metadata",
            ),
        ],
    )
    ae_key = "listing-field-mapping:batch-a:AE:0001-of-0001"
    ae = _candidate(
        "project-a",
        "job-ae",
        ae_key,
        [
            _mapping("AE", "AETERM", "ae_reported_term"),
            _mapping(
                "AE",
                "MDRAVER",
                "meddra_dictionary_version",
                field_kind="source_metadata",
            ),
            _mapping(
                "AE",
                "PTCODE",
                "meddra_pt_code",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["PTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _mapping(
                "AE",
                "PTTERM",
                "meddra_pt_term",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["PTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
        ],
    )

    report = audit_candidates(
        [
            _record(daa, daa_key),
            _record(cm, cm_key),
            _record(ae, ae_key),
        ]
    )
    codes = _codes(report)

    assert "XJOB-IP-ACTION-ROLE-UNRESOLVED" in codes
    assert "XJOB-IP-ACCOUNTABILITY-ROLE-UNRESOLVED" in codes
    assert "XJOB-CODING-LINEAGE-INCOMPLETE" in codes
    assert "XJOB-AE-CODING-SOURCE-ANCHOR-MISSING" in codes
    assert "XJOB-CODING-FALSE-STANDARDIZED" not in codes
    assert report["summary"]["error_count"] == 0
    ae_finding = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-AE-CODING-SOURCE-ANCHOR-MISSING"
    )
    assert "resolution=draft_assembly_cross_chunk_anchor" in ae_finding["variants"]


def test_multi_action_role_collapse_is_deterministic_quarantine_warning() -> None:
    key = "listing-field-mapping:batch-a:DAB:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-multi-action",
        key,
        [
            _mapping("DAB", "IPCOMP", "drug_return_compliance_percent"),
            _mapping(
                "DAB",
                "IPCOMP_UNIT",
                "drug_return_compliance_percent_unit",
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    collapse = [
        item
        for item in report["findings"]
        if item["code"] == "XJOB-IP-ACTION-COLLAPSE"
    ]
    assert len(collapse) == 2
    assert all(item["severity"] == "warning" for item in collapse)
    assert all(
        "resolution=draft_assembly_multi_action_quarantine"
        in item["variants"]
        for item in collapse
    )
    assert report["summary"]["error_count"] == 0


def test_incomplete_standardized_claim_is_warning_with_downgrade_resolution() -> None:
    key = "listing-field-mapping:batch-a:AE:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-ae-false-standard",
        key,
        [
            _mapping("AE", "AETERM", "ae_reported_term"),
            _mapping(
                "AE",
                "PTCODE",
                "meddra_pt_code",
                field_kind="standardized_coded",
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    finding = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-CODING-LINEAGE-INCOMPLETE"
        and "field_kind=standardized_coded" in item["variants"]
    )
    assert finding["severity"] == "warning"
    assert (
        "resolution=draft_assembly_incomplete_coding_downgrade"
        in finding["variants"]
    )
    assert "XJOB-CODING-FALSE-STANDARDIZED" not in _codes(report)
    assert report["summary"]["error_count"] == 0


def test_chain_drift_is_warning_when_assembly_downgrades_all_standardized() -> None:
    key = "listing-field-mapping:batch-a:PR:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-pr-chain",
        key,
        [
            _mapping(
                "PR",
                "HLTCODE",
                "meddra_hlt_code",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["HLTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _mapping(
                "PR",
                "HLTTERM",
                "meddra_hlt_term",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["HLTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _mapping("PR", "PTCODE", "meddra_pt_code"),
            _mapping("PR", "MDRAVER", "dictionary_version"),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    finding = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-CODING-CHAIN-DRIFT"
    )
    assert finding["severity"] == "warning"
    assert (
        "resolution=draft_assembly_incomplete_coding_downgrade"
        in finding["variants"]
    )
    assert report["summary"]["error_count"] == 0


def test_implicit_default_chain_partial_standardization_is_capability_warning() -> None:
    key = "listing-field-mapping:batch-a:PR:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-pr-closed",
        key,
        [
            _mapping(
                "PR",
                "HLTCODE",
                "meddra_hlt_code",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["HLTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _mapping(
                "PR",
                "HLTTERM",
                "meddra_hlt_term",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["HLTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _mapping("PR", "PTCODE", "meddra_pt_code"),
            _mapping(
                "PR",
                "MDRAVER",
                "meddra_dictionary_version",
                field_kind="source_metadata",
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    finding = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-CODING-CHAIN-DRIFT"
    )
    assert finding["severity"] == "warning"
    assert (
        "resolution=draft_assembly_incomplete_coding_downgrade"
        not in finding["variants"]
    )
    assert "scope=implicit_default_chain" in finding["variants"]
    assert (
        "resolution=formal_semantic_quality_partial_coding_restriction"
        in finding["variants"]
    )
    assert report["summary"]["error_count"] == 0


def test_explicit_chain_version_drift_stays_error() -> None:
    key = "listing-field-mapping:batch-a:PR:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-pr-explicit-drift",
        key,
        [
            _mapping(
                "PR",
                "HLTCODE",
                "meddra_hlt_code",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["HLTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                    "coding_chain_id": "pr-meddra-explicit",
                },
            ),
            _mapping(
                "PR",
                "HLTTERM",
                "meddra_hlt_term",
                field_kind="standardized_coded",
                derivation_lineage={
                    "source_fields": ["HLTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER_ALT",
                    "coding_chain_id": "pr-meddra-explicit",
                },
            ),
            _mapping(
                "PR",
                "MDRAVER",
                "meddra_dictionary_version",
                field_kind="source_metadata",
            ),
            _mapping(
                "PR",
                "MDRAVER_ALT",
                "meddra_dictionary_version",
                field_kind="source_metadata",
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    finding = next(
        item
        for item in report["findings"]
        if item["code"] == "XJOB-CODING-CHAIN-DRIFT"
    )
    assert finding["severity"] == "error"
    assert "version=MDRAVER" in finding["variants"]
    assert "version=MDRAVER_ALT" in finding["variants"]
    assert report["summary"]["error_count"] >= 1


def test_audit_uses_closed_ip_role_family_before_raw_role_markers() -> None:
    key = "listing-field-mapping:batch-a:DAB:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-closed-ip-aliases",
        key,
        [
            _mapping("DAB", "DABMECO", "compliance_percentage_value"),
            _mapping("DAB", "DABNRYN", "item_returned_flag_code"),
            _mapping("EX", "EXDAT", "exposure_administration_date"),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    assert "XJOB-IP-ACTION-ROLE-UNRESOLVED" not in _codes(report)
    assert report["summary"]["error_count"] == 0


def test_audit_rejects_ae_seriousness_severity_collapse() -> None:
    key = "listing-field-mapping:batch-a:AE:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-ae-boundary",
        key,
        [
            _mapping(
                "AE",
                "AEGRADE",
                "ae_seriousness_and_severity",
            )
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    assert "XJOB-AE-SERIOUSNESS-SEVERITY-COLLAPSE" in _codes(report)
    assert report["summary"]["error_count"] == 1


def test_ctcae_version_is_lineage_support_not_a_coded_result() -> None:
    key = "listing-field-mapping:batch-a:LB:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-ctcae",
        key,
        [
            _mapping(
                "LB",
                "TOXGR",
                "ctcae_grade",
                standards_reference={"ctcae_version": "5.0"},
            ),
            _mapping(
                "LB",
                "CTCAEVER",
                "ctcae_version",
                field_kind="source_metadata",
                standards_reference={"reference_name": "CTCAE"},
            ),
        ],
    )

    report = audit_candidates([_record(candidate, key)])

    assert "XJOB-CODING-LINEAGE-INCOMPLETE" not in _codes(report)
    assert "XJOB-CODING-CHAIN-DRIFT" not in _codes(report)
    assert report["inventories"]["coding_lineage"] == [
        {
            "coding_system": "CTCAE",
            "field_count": 2,
            "complete_lineage_count": 1,
            "incomplete_lineage_count": 0,
            "support_field_count": 1,
            "support_fields": ["CTCAEVER"],
            "versions": ["5.0"],
            "field_kinds": ["source_collected", "source_metadata"],
        }
    ]


def test_exported_candidate_json_accepts_database_rows_and_envelopes(
    tmp_path: Path,
) -> None:
    key = "listing-field-mapping:batch-a:AE:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-a",
        key,
        [_mapping("AE", "SITEID", "site_identifier", field_kind="source_metadata")],
    )
    database_export = tmp_path / "database-export.json"
    database_export.write_text(
        json.dumps(
            [
                {
                    "job_id": "job-a",
                    "project_id": "project-a",
                    "business_key": key,
                    "prompt_version": "monitoring-listing-field-mapping-v13",
                    "job_status": "completed",
                    "candidate_status": "proposed",
                    "candidate_json": json.dumps(candidate, ensure_ascii=False),
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    envelope = tmp_path / "envelope.json"
    envelope.write_text(
        json.dumps(
            {
                "task_id": "job-a",
                "project_id": "project-a",
                "business_key": key,
                "prompt_version": "monitoring-listing-field-mapping-v13",
                "candidates": [candidate],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    database_records = load_candidate_json(database_export)
    envelope_records = load_candidate_json(envelope)

    assert len(database_records) == 1
    assert database_records[0].business_key == key
    assert len(envelope_records) == 1
    assert envelope_records[0].candidate["candidate_id"] == "candidate-job-a"


def _create_ai_database(path: Path, candidate: dict, business_key: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE monitoring_ai_jobs (
                job_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL,
                business_key TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE monitoring_ai_candidates (
                candidate_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                candidate_json TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO monitoring_ai_jobs(
                job_id, project_id, task_type, status, business_key,
                prompt_version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate["job_id"],
                candidate["project_id"],
                "listing_field_mapping",
                "completed",
                business_key,
                candidate["prompt_version"],
                "2026-07-30T01:05:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO monitoring_ai_candidates(
                candidate_id, job_id, status, created_at, candidate_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                candidate["candidate_id"],
                candidate["job_id"],
                "proposed",
                candidate["created_at"],
                json.dumps(candidate, ensure_ascii=False),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def test_sqlite_loader_is_read_only_and_cli_writes_compact_reports(
    tmp_path: Path,
) -> None:
    key = "listing-field-mapping:batch-a:AE:0001-of-0001"
    candidate = _candidate(
        "project-a",
        "job-a",
        key,
        [_mapping("AE", "SITEID", "site_identifier", field_kind="source_metadata")],
        deterministic={("AE", "SITEID")},
    )
    database = tmp_path / "monitoring_ai.sqlite3"
    _create_ai_database(database, candidate, key)
    before = sha256(database.read_bytes()).hexdigest()

    records = load_candidate_sqlite(
        database,
        prompt_versions=["monitoring-listing-field-mapping-v13"],
    )
    after = sha256(database.read_bytes()).hexdigest()

    assert len(records) == 1
    assert before == after
    assert not database.with_name(f"{database.name}-journal").exists()
    json_output = tmp_path / "audit.json"
    markdown_output = tmp_path / "audit.md"
    exit_code = main(
        [
            "--sqlite",
            str(database),
            "--prompt-version",
            "monitoring-listing-field-mapping-v13",
            "--output-json",
            str(json_output),
            "--output-markdown",
            str(markdown_output),
            "--fail-on",
            "error",
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["source"]["kind"] == "sqlite_read_only"
    assert payload["summary"]["job_count"] == 1
    assert payload["report_sha256"]
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "# 医学监查字段映射候选跨作业审计" in markdown
    assert "不替代完整 mapping draft" in markdown


def test_markdown_limits_long_locator_lists() -> None:
    report = {
        "summary": {
            "project_count": 1,
            "job_count": 1,
            "domain_count": 1,
            "field_occurrence_count": 10,
            "error_count": 1,
            "warning_count": 0,
            "observation_count": 0,
        },
        "observed_through": "2026-07-30T01:00:00Z",
        "report_sha256": "a" * 64,
        "domain_summaries": [],
        "inventories": {"coding_lineage": []},
        "findings": [
            {
                "severity": "error",
                "code": "TEST",
                "title": "测试",
                "detail": "测试详情",
                "variants": [],
                "locators": [f"location-{index}" for index in range(10)],
            }
        ],
    }

    markdown = render_markdown(report)

    assert "location-7" in markdown
    assert "location-8" not in markdown
    assert "另 2 处" in markdown
