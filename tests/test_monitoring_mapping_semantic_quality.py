from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from services.api.app.monitoring_mapping_semantic_quality import (
    MappingActivationDisposition,
    MappingCapabilityStateCode,
    MappingSemanticQualityReport,
    SemanticFindingSeverity,
    SemanticQualityStatus,
    evaluate_mapping_semantic_quality,
)


def _identity_binding(binding_id: str, target_domain: str) -> dict:
    """A frozen-profile treatment identity binding validated independently
    of the mapping output: randomization arm as the auditable source."""
    return {
        "schema_version": "monitoring_treatment_identity_binding_v1",
        "binding_id": binding_id,
        "source_domain": "RANDOMIZATION",
        "source_field": "ARM",
        "target_domain": target_domain,
        "relationship_type": "subject_level_randomized_assignment",
        "join_keys": ["subject_id"],
    }


def _field(
    domain: str,
    source_field: str,
    role: str,
    *,
    field_kind: str = "source_collected",
    derivation_lineage: dict | None = None,
    coding_lineage: dict | None = None,
    standards_reference: dict | None = None,
    object_identity: str = "not_applicable",
    object_identity_evidence_fields: list[str] | None = None,
    object_identity_binding_id: str = "",
    validated_treatment_identity_binding: dict | None = None,
    dose_semantics: str = "not_applicable",
) -> dict:
    return {
        "domain": domain,
        "source_field": source_field,
        "recommended_role": role,
        "field_kind": field_kind,
        "related_fields": [],
        "standards_reference": standards_reference,
        "derivation_lineage": derivation_lineage,
        "coding_lineage": coding_lineage,
        "object_identity": object_identity,
        "object_identity_evidence_fields": (
            object_identity_evidence_fields or []
        ),
        "object_identity_binding_id": object_identity_binding_id,
        "validated_treatment_identity_binding": (
            validated_treatment_identity_binding
        ),
        "dose_semantics": dose_semantics,
    }


def _safe_fields() -> list[dict]:
    return [
        _field("EVENTS", "PERSON", "source_subject_identifier", field_kind="source_metadata"),
        _field("MEDICATIONS", "PERSON", "metadata.subject_id", field_kind="source_metadata"),
        _field("MEDICATIONS", "MEDICATION", "cm.non_ip_medication.name"),
        _field("RANDOMIZATION", "ARM", "treatment.identity.randomized_assignment"),
        _field("DOSING", "ADMIN_DATE", "ip.administration.date"),
        _field("DOSING", "ADMIN_DOSE", "ip.administration.dose"),
        _field("DOSING", "TREATMENT", "treatment.identity.name"),
        _field("DOSING", "ARM", "treatment.identity.randomized_assignment"),
        _field("DRUG_LOG", "DISPENSED", "ip.dispense.quantity"),
        _field("DRUG_LOG", "RETURNED", "ip.return.quantity"),
        _field(
            "DRUG_LOG",
            "PRODUCT",
            "treatment.identity.investigational_product",
            object_identity="investigational_product",
            object_identity_evidence_fields=["PRODUCT"],
            object_identity_binding_id="rand-to-druglog",
            validated_treatment_identity_binding=_identity_binding(
                "rand-to-druglog",
                "DRUG_LOG",
            ),
        ),
        _field(
            "DOSING",
            "ADJ_ACTION",
            "ip.dose_adjustment.action",
        ),
        _field(
            "DOSING",
            "INTERRUPT_START",
            "ip.interruption.start_date",
        ),
        _field(
            "DOSING",
            "DISCON_DATE",
            "ip.discontinuation.date",
        ),
        _field(
            "DOSING",
            "RESTART_DATE",
            "ip.restart.date",
        ),
        _field(
            "DOSING",
            "OTHER_CHANGE",
            "ip.other_change.action",
        ),
        _field("EVENTS", "AE_TERM", "ae.reported_term"),
        _field(
            "EVENTS",
            "MDRAVER",
            "meddra_dictionary_version",
            field_kind="source_metadata",
        ),
        _field(
            "EVENTS",
            "PT_CODE",
            "coding.meddra.pt_code",
            coding_lineage={
                "coding_system": "MedDRA",
                "dictionary_version_field": "MDRAVER",
                "source_fields": ["AE_TERM", "PT_TERM"],
                "coding_chain_id": "event-coding",
            },
        ),
        _field(
            "EVENTS",
            "PT_TERM",
            "coding.meddra.pt_term",
            coding_lineage={
                "coding_system": "MedDRA",
                "dictionary_version_field": "MDRAVER",
                "source_fields": ["AE_TERM", "PT_CODE"],
                "coding_chain_id": "event-coding",
            },
        ),
        _field(
            "DOSING",
            "TOTAL_DOSE",
            "ip.administration.dose",
            field_kind="deterministic_derived",
            derivation_lineage={
                "source_fields": ["ADMIN_DOSE"],
                "formula": "decimal(ADMIN_DOSE)",
                "user_confirmed": True,
            },
        ),
    ]


def _rules(report: MappingSemanticQualityReport) -> set[str]:
    return {item.rule_id for item in report.finding_groups}


def test_safe_complete_mapping_passes_with_stable_immutable_report() -> None:
    fields = _safe_fields()
    expected = {(item["domain"], item["source_field"]) for item in fields}

    first = evaluate_mapping_semantic_quality(
        fields=fields,
        expected_fields=expected,
        domain_family_hints={"MEDICATIONS": "cm", "DOSING": "ip"},
    )
    second = evaluate_mapping_semantic_quality(
        fields=list(reversed(fields)),
        expected_fields=reversed(sorted(expected)),
        domain_family_hints={"DOSING": "ip", "MEDICATIONS": "cm"},
    )

    assert first.status == SemanticQualityStatus.PASSED
    assert first.finding_groups == ()
    assert first.global_blocker_count == 0
    assert first.capability_blocker_count == 0
    assert first.report_sha256 == second.report_sha256
    assert first.input_sha256 == second.input_sha256
    assert len(first.report_sha256) == 64
    with pytest.raises(FrozenInstanceError):
        first.status = SemanticQualityStatus.BLOCKED  # type: ignore[misc]


def test_duplicate_missing_and_unexpected_fields_are_global_blockers() -> None:
    fields = [
        _field("EVENTS", "PERSON", "metadata.subject_id", field_kind="source_metadata"),
        _field("EVENTS", "PERSON", "metadata.subject_id", field_kind="source_metadata"),
        _field("EVENTS", "EXTRA", "ae.verbatim_term"),
    ]
    report = evaluate_mapping_semantic_quality(
        fields=fields,
        expected_fields={("EVENTS", "PERSON"), ("EVENTS", "TERM")},
    )

    assert report.status == SemanticQualityStatus.BLOCKED
    assert "G-COVER-001" in _rules(report)
    finding = next(item for item in report.finding_groups if item.rule_id == "G-COVER-001")
    assert finding.severity == SemanticFindingSeverity.GLOBAL_BLOCKER


def test_role_catalog_blocks_unknown_metadata_but_groups_non_core_source_roles() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("ANY", "PERSON", "technical_subject_id", field_kind="source_metadata"),
            _field(
                "ANY",
                "TECH",
                "free_form_project_specific_metadata",
                field_kind="source_metadata",
            ),
            _field("ANY", "TERM", "free_form_project_specific_source_role"),
        ],
    )

    assert "G-ROLE-002" in _rules(report)
    finding = next(item for item in report.finding_groups if item.rule_id == "G-ROLE-002")
    assert [item.source_field for item in finding.affected_fields] == ["TECH"]


@pytest.mark.parametrize(
    "role",
    [
        "source_domain_identifier",
        "study_identifier",
        "site_identifier",
        "site_name",
        "subject_identifier",
        "subject_initials",
        "visit_identifier",
        "visit_name",
        "visit_sequence_number",
        "visit_repeat_key",
        "form_identifier",
        "form_repeat_key",
        "item_group_identifier",
        "record_group_identifier",
        "crf_version",
        "form_name",
        "page_name",
        "form_name_duplicate",
        "record_block_sequence",
        "record_line_number",
        "laboratory_configuration_name",
        "record_deletion_flag",
        "page_first_saved_datetime",
        "page_last_modified_by",
        "page_last_modified_datetime",
        "study_name",
        "record_repeat_key",
        "edc_object_identifier",
        "edc_repeat_key",
    ],
)
def test_deterministic_metadata_catalog_covers_system_roles(role: str) -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[_field("ANY", "TECH", role, field_kind="source_metadata")],
    )

    assert report.status == SemanticQualityStatus.PASSED


def test_technical_metadata_must_be_consistent_across_domains() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("ONE", "PERSON", "metadata.subject_id", field_kind="source_metadata"),
            _field("TWO", "PERSON", "metadata.site_id", field_kind="source_metadata"),
        ],
    )

    assert "G-ROLE-001" in _rules(report)
    assert report.global_blocker_count == 1


def test_export_context_aliases_resolve_to_stable_metadata_concepts() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "ONE",
                "FORM",
                "edc_form_display_name",
                field_kind="source_metadata",
            ),
            _field(
                "TWO",
                "FORM",
                "form_display_name",
                field_kind="source_metadata",
            ),
            _field(
                "ONE",
                "PAGE",
                "edc_page_name",
                field_kind="source_metadata",
            ),
            _field(
                "TWO",
                "PAGE",
                "page_or_form_display_name",
                field_kind="source_metadata",
            ),
            _field(
                "ONE",
                "LINE",
                "record_sequence_number",
                field_kind="source_metadata",
            ),
            _field(
                "TWO",
                "LINE",
                "listing_line_number",
                field_kind="source_metadata",
            ),
        ],
    )

    assert report.status == SemanticQualityStatus.PASSED
    assert "G-ROLE-001" not in _rules(report)
    assert "G-ROLE-002" not in _rules(report)


@pytest.mark.parametrize(
    ("domain", "role", "hints"),
    [
        ("MEDICATIONS", "ip.administration.dose", {"MEDICATIONS": "cm"}),
        ("DOSING", "cm.non_ip_medication.name", {"DOSING": "ip"}),
        ("CM", "ip.dispense.quantity", {}),
    ],
)
def test_cm_and_investigational_product_roles_never_cross(
    domain: str,
    role: str,
    hints: dict[str, str],
) -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[_field(domain, "VALUE", role)],
        domain_family_hints=hints,
    )

    assert "G-CMIP-001" in _rules(report)
    assert report.status == SemanticQualityStatus.BLOCKED


@pytest.mark.parametrize(
    "ambiguous_role",
    [
        "ip_administration_or_dispense_quantity",
        "ip_dose_adjustment_and_restart_date",
        "ip_interruption_or_permanent_discontinuation",
        "ip_return_and_compliance_result",
    ],
)
def test_ip_lifecycle_actions_cannot_share_an_ambiguous_role(
    ambiguous_role: str,
) -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[_field("ANY", "VALUE", ambiguous_role)],
    )

    assert "G-CMIP-002" in _rules(report)
    assert "G-ROLE-002" in _rules(report)


def test_unmapped_administered_dose_role_blocks_ip_exposure_only() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "EX",
                "EXPDOSE",
                "ip_planned_or_administered_dose_with_unit_text",
                field_kind="unmapped",
            )
        ],
    )

    assert report.status == SemanticQualityStatus.PASS_WITH_WARNINGS
    assert "G-ROLE-002" not in _rules(report)
    assert "G-CMIP-003" in _rules(report)
    exposure = next(
        item
        for item in report.capability_states
        if item.capability_id == "ip_exposure_adherence"
    )
    assert exposure.state == MappingCapabilityStateCode.BLOCKED_BY_QUALITY


def test_coding_requires_explicit_system_and_version() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "EVENTS",
                "PT_CODE",
                "coding.meddra.pt_code",
                coding_lineage={"coding_system": "unknown"},
            )
        ],
    )

    assert "G-CODE-002" in _rules(report)
    finding = next(item for item in report.finding_groups if item.rule_id == "G-CODE-002")
    assert finding.severity == SemanticFindingSeverity.CAPABILITY_BLOCKER
    assert report.status == SemanticQualityStatus.PASS_WITH_WARNINGS
    assert (
        report.activation_disposition
        == MappingActivationDisposition.ACTIVATE_RESTRICTED
    )
    assert finding.affected_capability_ids == (
        "patient_profile",
        "standard_coding_rules",
        "subject_timeline",
    )
    capability_states = {
        item.capability_id: item.state for item in report.capability_states
    }
    assert (
        capability_states["standard_coding_rules"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )
    assert (
        capability_states["subject_timeline"]
        == MappingCapabilityStateCode.LIMITED
    )
    assert capability_states["raw_source_review"] == MappingCapabilityStateCode.READY


def test_false_standardized_coding_claim_is_a_global_blocker() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "EVENTS",
                "PT_CODE",
                "coding.meddra.pt_code",
                field_kind="standardized_coded",
                coding_lineage={"coding_system": "unknown"},
            )
        ],
    )

    assert "G-CODE-003" in _rules(report)
    assert report.status == SemanticQualityStatus.BLOCKED
    assert report.activation_disposition == MappingActivationDisposition.REJECT


def test_standardized_coding_requires_real_sources_and_independent_version_field() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("AE", "AETERM", "ae_reported_term"),
            _field(
                "AE",
                "PTCODE",
                "meddra_pt_code",
                field_kind="standardized_coded",
                coding_lineage={
                    "source_fields": ["AETERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version": "27.0",
                },
            ),
        ],
    )

    assert "G-CODE-003" in _rules(report)
    assert report.status == SemanticQualityStatus.BLOCKED


@pytest.mark.parametrize(
    "coding_system",
    ["项目字典", "未明确的项目词典", "term-code mapping", "local dictionary"],
)
def test_non_specific_dictionary_identity_cannot_claim_standard_coding(
    coding_system: str,
) -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("CM", "CMTRT", "cm.non_ip_medication.name"),
            _field(
                "CM",
                "DICTVER",
                "drug_dictionary_version",
                field_kind="source_metadata",
            ),
            _field(
                "CM",
                "DRUGCODE",
                "drug_code_reported",
                field_kind="standardized_coded",
                coding_lineage={
                    "source_fields": ["CMTRT"],
                    "coding_system": coding_system,
                    "dictionary_version_field": "DICTVER",
                },
            ),
        ],
    )

    assert "G-CODE-003" in _rules(report)
    assert report.status == SemanticQualityStatus.BLOCKED


def test_source_drug_codes_without_specific_lineage_restrict_coding_only() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("CM", "ATC1CODE", "atc_level1_code"),
            _field("CM", "ATC1TEXT", "atc_level1_term"),
            _field(
                "CM",
                "DRUGVER",
                "drug_dictionary_version",
                field_kind="source_metadata",
            ),
        ],
    )

    assert "G-ROLE-002" not in _rules(report)
    assert "G-CODE-002" in _rules(report)
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["standard_coding_rules"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )
    assert states["raw_source_review"] == MappingCapabilityStateCode.READY


def test_clear_ip_action_aliases_enter_closed_roles_without_global_blocking() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("DAB", "DABMECO", "compliance_percentage_value"),
            _field("DAB", "DABNRYN", "item_returned_flag_code"),
            _field("EX", "EXDAT", "exposure_administration_date"),
            _field("EX", "EXDOSE", "ip_administered_dose"),
            _field("EX", "EXDOSETXT", "ip_administered_dose_with_unit_text"),
            _field("EX", "EXREASND", "ip_dose_not_administered_reason"),
            _field("EX", "EXTPT", "ip_planned_dosing_day"),
            _field(
                "EX",
                "LINE",
                "record_line_number",
                field_kind="source_metadata",
            ),
        ],
    )

    assert "G-CMIP-003" not in _rules(report)
    assert "G-ROLE-002" not in _rules(report)
    assert report.global_blocker_count == 0


def test_ambiguous_ip_return_and_accountability_roles_restrict_exposure() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "DAB",
                "DABNRNUM",
                "returned_or_unreturned_item_count",
            ),
            _field("DAA", "DAAPRES", "drug_amount_presented"),
            _field("DAB", "DABWDOSE", "dab_withdrawn_dose_amount"),
        ],
    )

    assert "G-CMIP-003" in _rules(report)
    assert "G-CMIP-004" in _rules(report)
    assert report.global_blocker_count == 0
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["ip_exposure_adherence"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )
    assert states["raw_source_review"] == MappingCapabilityStateCode.READY


def test_ae_reported_term_must_anchor_meddra_chain_for_reconciliation() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("AE", "AETERM", "ae_reported_term"),
            _field(
                "AE",
                "MDRAVER",
                "meddra_dictionary_version",
                field_kind="source_metadata",
            ),
            _field(
                "AE",
                "PTCODE",
                "meddra_pt_code",
                field_kind="standardized_coded",
                coding_lineage={
                    "source_fields": ["PTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _field(
                "AE",
                "PTTERM",
                "meddra_pt_term",
                field_kind="standardized_coded",
                coding_lineage={
                    "source_fields": ["PTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
        ],
    )

    assert "G-AEMH-001" in _rules(report)
    assert report.global_blocker_count == 0
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["ae_mh_reconciliation"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )
    finding = next(
        item for item in report.finding_groups if item.rule_id == "G-AEMH-001"
    )
    assert finding.severity == SemanticFindingSeverity.CAPABILITY_BLOCKER


def test_each_meddra_field_requires_same_domain_reported_term_anchor() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("AE", "AETERM", "ae_reported_term"),
            _field(
                "AE",
                "MDRAVER",
                "meddra_dictionary_version",
                field_kind="source_metadata",
            ),
            _field(
                "AE",
                "PTCODE",
                "meddra_pt_code",
                field_kind="standardized_coded",
                coding_lineage={
                    "source_fields": ["AETERM", "PTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _field(
                "AE",
                "PTTERM",
                "meddra_pt_term",
                field_kind="standardized_coded",
                coding_lineage={
                    "source_fields": ["PTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
        ],
    )

    assert "G-AEMH-001" in _rules(report)
    finding = next(
        item for item in report.finding_groups if item.rule_id == "G-AEMH-001"
    )
    assert {item.source_field for item in finding.affected_fields} == {
        "AETERM",
        "PTTERM",
    }


def test_meddra_chain_cannot_borrow_reported_term_from_other_domain() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("AE", "AETERM", "ae_reported_term"),
            _field(
                "MH",
                "MDRAVER",
                "meddra_dictionary_version",
                field_kind="source_metadata",
            ),
            _field(
                "MH",
                "PTCODE",
                "meddra_pt_code",
                field_kind="standardized_coded",
                coding_lineage={
                    "source_fields": ["PTTERM"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
            _field(
                "MH",
                "PTTERM",
                "meddra_pt_term",
                field_kind="standardized_coded",
                coding_lineage={
                    "source_fields": ["PTCODE"],
                    "coding_system": "MedDRA",
                    "dictionary_version_field": "MDRAVER",
                },
            ),
        ],
    )

    assert "G-AEMH-001" in _rules(report)
    finding = next(
        item for item in report.finding_groups if item.rule_id == "G-AEMH-001"
    )
    assert {item.domain for item in finding.affected_fields} == {"MH"}
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["ae_mh_reconciliation"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )


def test_ae_seriousness_and_severity_cannot_be_one_formal_role() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "AE",
                "AEGRADE",
                "ae_seriousness_and_severity",
            )
        ],
    )

    assert "G-AEMH-003" in _rules(report)
    assert report.status == SemanticQualityStatus.BLOCKED


def test_partial_date_restricts_exact_rules_without_blocking_source_review() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "CM",
                "CMSTDTC",
                "cm.non_ip_medication.start_date",
                standards_reference={
                    "reference_only": True,
                    "date_precision": "month",
                },
            )
        ],
    )

    assert "G-DATE-001" in _rules(report)
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["precise_temporal_rules"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )
    assert states["subject_timeline"] == MappingCapabilityStateCode.LIMITED
    assert states["raw_source_review"] == MappingCapabilityStateCode.READY
    assert (
        report.activation_disposition
        == MappingActivationDisposition.ACTIVATE_RESTRICTED
    )


def test_source_scale_without_recalculation_lineage_is_locally_restricted() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[_field("EASI", "TOTAL", "easi.total_score")],
    )

    assert "G-SCALE-001" in _rules(report)
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["scale_recalculation"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )
    assert states["patient_profile"] == MappingCapabilityStateCode.LIMITED
    assert report.global_blocker_count == 0


def test_lab_without_complete_grading_lineage_is_locally_restricted() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("LB", "RESULT", "lab.result"),
            _field("LB", "UNIT", "lab.unit"),
            _field("LB", "LLN", "lab.reference.lower"),
            _field("LB", "ULN", "lab.reference.upper"),
        ],
    )

    assert "G-LAB-001" in _rules(report)
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["lab_ctcae_rules"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )
    assert states["patient_profile"] == MappingCapabilityStateCode.LIMITED
    assert report.global_blocker_count == 0


def test_one_coding_chain_must_use_one_system_version_and_field_kind() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "EVENTS",
                "CODE",
                "coding.meddra.pt_code",
                coding_lineage={
                    "coding_system": "MedDRA",
                    "dictionary_version": "26.1",
                    "coding_chain_id": "primary-event-chain",
                },
            ),
            _field(
                "EVENTS",
                "TERM",
                "coding.meddra.pt_term",
                coding_lineage={
                    "coding_system": "MedDRA",
                    "dictionary_version": "27.0",
                    "coding_chain_id": "primary-event-chain",
                },
            ),
        ],
    )

    assert "G-CODE-001" in _rules(report)
    assert report.global_blocker_count == 1


@pytest.mark.parametrize(
    "lineage",
    [
        None,
        {"source_fields": ["RAW"]},
        {"source_fields": ["RAW"], "formula": "normalize(RAW)"},
        {
            "source_fields": ["MISSING"],
            "formula": "normalize(MISSING)",
            "user_confirmed": True,
        },
        {
            "source_fields": ["DERIVED"],
            "formula": "normalize(DERIVED)",
            "user_confirmed": True,
        },
    ],
)
def test_deterministic_derivation_requires_recomputable_lineage(
    lineage: dict | None,
) -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("DATA", "RAW", "ae.verbatim_term"),
            _field(
                "DATA",
                "DERIVED",
                "ae.verbatim_term",
                field_kind="deterministic_derived",
                derivation_lineage=lineage,
            ),
        ],
    )

    assert "G-DERIVE-001" in _rules(report)
    assert report.status == SemanticQualityStatus.BLOCKED


def test_domain_names_do_not_define_semantics_without_role_evidence() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[_field("CM", "VALUE", "cm.non_ip_medication.name")],
    )

    assert report.status == SemanticQualityStatus.PASSED
    assert report.finding_groups == ()


# ---------------------------------------------------------------------------
# V14 contract: treatment-object identity, dose ambiguity, scale protection,
# IP change lifecycle capability, and project-neutral synthetic scenarios.
# ---------------------------------------------------------------------------


def test_domain_name_alone_cannot_establish_ip_identity() -> None:
    """A domain named EX is not sufficient evidence for IP identity."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("EX", "EXDAT", "ip.administration.date"),
            _field("EX", "EXDOSE", "ip.administration.dose"),
        ],
    )

    assert "G-CMIP-005" in _rules(report)
    finding = next(
        item for item in report.finding_groups if item.rule_id == "G-CMIP-005"
    )
    assert finding.severity == SemanticFindingSeverity.CAPABILITY_BLOCKER
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["ip_exposure_adherence"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )
    assert states["raw_source_review"] == MappingCapabilityStateCode.READY


def test_treatment_identity_evidence_satisfies_ip_identity_requirement() -> None:
    """An independent validated treatment binding anchors the IP domain."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("EX", "EXDAT", "ip.administration.date"),
            _field("EX", "EXDOSE", "ip.administration.dose"),
            _field("RANDOMIZATION", "ARM", "treatment.identity.randomized_assignment"),
            _field(
                "EX",
                "TRT",
                "treatment.identity.name",
                object_identity="investigational_product",
                object_identity_evidence_fields=["TRT"],
                object_identity_binding_id="rand-to-ex",
                validated_treatment_identity_binding=_identity_binding(
                    "rand-to-ex",
                    "EX",
                ),
            ),
            _field("EX", "ARM", "randomized_treatment"),
            _field("EX", "ADJ", "ip.dose_adjustment.action"),
            _field("EX", "INT", "ip.interruption.start_date"),
            _field("EX", "DISC", "ip.discontinuation.date"),
            _field("EX", "RST", "ip.restart.date"),
        ],
    )

    assert "G-CMIP-005" not in _rules(report)


def test_ip_identity_is_scoped_to_domain_and_cannot_release_background() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "RANDOMIZATION",
                "ARM",
                "treatment.identity.randomized_assignment",
                object_identity="investigational_product",
                object_identity_evidence_fields=["ARM"],
            ),
            _field(
                "IP_ADMIN",
                "PRODUCT",
                "treatment.identity.investigational_product",
                object_identity="investigational_product",
                object_identity_evidence_fields=["PRODUCT"],
                object_identity_binding_id="rand-to-ip-admin",
                validated_treatment_identity_binding=_identity_binding(
                    "rand-to-ip-admin",
                    "IP_ADMIN",
                ),
            ),
            _field("IP_ADMIN", "DOSE", "ip.administration.dose"),
            _field("BACKGROUND", "BGNAME", "ip.administration.note"),
            _field("BACKGROUND", "BGDOSE", "ip.administration.dose"),
        ],
    )

    finding = next(
        item for item in report.finding_groups if item.rule_id == "G-CMIP-005"
    )
    assert {item.domain for item in finding.affected_fields} == {"BACKGROUND"}


def test_explicit_cross_domain_treatment_binding_releases_target_domain() -> None:
    binding = {
        "schema_version": "monitoring_treatment_identity_binding_v1",
        "binding_id": "rand-to-dose",
        "source_domain": "RANDOMIZATION",
        "source_field": "ARM",
        "target_domain": "IP_ADMIN",
        "relationship_type": "subject_level_randomized_assignment",
        "join_keys": ["subject_id"],
    }
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "RANDOMIZATION",
                "ARM",
                "treatment.identity.randomized_assignment",
                object_identity="investigational_product",
                object_identity_evidence_fields=["ARM"],
            ),
            _field(
                "IP_ADMIN",
                "DOSE",
                "ip.administration.dose",
                object_identity="investigational_product",
                object_identity_binding_id="rand-to-dose",
                validated_treatment_identity_binding=binding,
                dose_semantics="actual_administered",
            ),
        ],
    )

    assert "G-CMIP-005" not in _rules(report)


def test_background_therapy_not_promoted_to_ip_role() -> None:
    """Background therapy fields with IP roles must trigger CM/IP boundary."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("BG_TX", "BGDATE", "ip.administration.date"),
            _field("BG_TX", "BGDOSE", "ip.administration.dose"),
        ],
        domain_family_hints={"BG_TX": "background"},
    )

    assert "G-CMIP-001" in _rules(report)
    assert report.status == SemanticQualityStatus.BLOCKED


def test_background_therapy_preserved_as_neutral_treatment() -> None:
    """Background therapy without IP roles and without identity is safe."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("BG_TX", "BGNAME", "cm.non_ip_medication.name"),
        ],
        domain_family_hints={"BG_TX": "background"},
    )

    assert "G-CMIP-005" not in _rules(report)
    assert "G-CMIP-001" not in _rules(report)


def test_cm_preserved_as_non_ip_medication() -> None:
    """CM fields must never be promoted to IP roles."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("CM", "CMTRT", "cm.non_ip_medication.name"),
            _field("CM", "CMDOSE", "cm.non_ip_medication.dose"),
            _field("CM", "CMROUTE", "cm.non_ip_medication.route"),
        ],
    )

    assert "G-CMIP-001" not in _rules(report)
    assert "G-CMIP-005" not in _rules(report)


def test_placebo_and_active_comparator_require_identity_evidence() -> None:
    """Placebo/active-comparator mapping needs same-domain identity evidence."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("DOSING", "DOSE", "ip.administration.dose"),
            _field("DOSING", "DATE", "ip.administration.date"),
        ],
    )

    assert "G-CMIP-005" in _rules(report)


def test_pm_self_consistent_identity_cannot_release_ip_capability() -> None:
    """PM counterexample: a provider-assigned IP role with a self-consistent
    object identity and self-cited evidence fields is circular
    self-attestation and must not release IP exposure capabilities."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                "PM",
                "MEDNAME",
                "treatment.identity.investigational_product",
                object_identity="investigational_product",
                object_identity_evidence_fields=["MEDNAME"],
            ),
            _field("PM", "DOSE", "ip.administration.dose"),
        ],
    )

    assert "G-CMIP-005" in _rules(report)
    states = {item.capability_id: item.state for item in report.capability_states}
    assert states["ip_exposure_adherence"] != MappingCapabilityStateCode.READY


@pytest.mark.parametrize("domain", ["EX", "TOPICAL"])
def test_self_consistent_identity_without_independent_anchor_fails_closed(
    domain: str,
) -> None:
    """The same self-referential structure in EX/TOPICAL-shaped mappings
    fails closed as well; domain names are never identity evidence."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field(
                domain,
                "TRT",
                "treatment.identity.investigational_product",
                object_identity="investigational_product",
                object_identity_evidence_fields=["TRT"],
            ),
            _field(domain, "DOSE", "ip.administration.dose"),
        ],
    )

    assert "G-CMIP-005" in _rules(report)


def test_confirmed_domain_family_hint_is_an_independent_identity_anchor() -> None:
    """Medically confirmed domain-family metadata anchors IP identity."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("EX", "EXDAT", "ip.administration.date"),
            _field("EX", "EXDOSE", "ip.administration.dose"),
        ],
        domain_family_hints={"EX": "ip"},
    )

    assert "G-CMIP-005" not in _rules(report)


def test_ambiguous_planned_or_administered_dose_is_blocked() -> None:
    """A role that merges planned and actual dose concepts is ambiguous."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("EX", "DOSE1", "ip_planned_or_administered_dose"),
        ],
    )

    assert "G-CMIP-006" in _rules(report)


def test_indistinguishable_same_domain_dose_pair_is_flagged() -> None:
    """Two dose-like fields with the same signature are indistinguishable."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("EX", "DOSE_A", "ip.administration.dose"),
            _field("EX", "DOSE_B", "ip.administration.dose"),
            _field("EX", "TRT", "treatment.identity.name"),
            _field("EX", "ADJ", "ip.dose_adjustment.action"),
            _field("EX", "INT", "ip.interruption.start_date"),
            _field("EX", "DISC", "ip.discontinuation.date"),
            _field("EX", "RST", "ip.restart.date"),
        ],
    )

    assert "G-CMIP-006" in _rules(report)


def test_distinct_planned_and_administered_doses_are_accepted() -> None:
    """Planned and administered doses with distinct roles are not ambiguous."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("EX", "PLAN_DOSE", "ip.dose.planned"),
            _field("EX", "ACT_DOSE", "ip.administration.dose"),
            _field("EX", "TRT", "treatment.identity.name"),
            _field("EX", "ADJ", "ip.dose_adjustment.action"),
            _field("EX", "INT", "ip.interruption.start_date"),
            _field("EX", "DISC", "ip.discontinuation.date"),
            _field("EX", "RST", "ip.restart.date"),
        ],
    )

    assert "G-CMIP-006" not in _rules(report)


def test_scale_total_score_not_classified_as_procedure_number() -> None:
    """A numeric total in a scale-form context must not be a procedure number."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("RES_7", "ITEM1", "scale.item_score"),
            _field("RES_7", "ITEM2", "scale.item_score"),
            _field(
                "RES_7",
                "TOTAL",
                "study_procedure_number",
            ),
        ],
    )

    assert "G-SCALE-002" in _rules(report)
    finding = next(
        item for item in report.finding_groups if item.rule_id == "G-SCALE-002"
    )
    assert finding.severity == SemanticFindingSeverity.GLOBAL_BLOCKER
    assert report.activation_disposition == MappingActivationDisposition.REJECT


def test_scale_total_preserved_as_source_collected() -> None:
    """Scale totals with source_collected semantics do not trigger misclassification."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("RES_7", "ITEM1", "scale.item_score"),
            _field("RES_7", "TOTAL", "scale.total_score"),
        ],
    )

    assert "G-SCALE-002" not in _rules(report)


def test_legal_procedure_number_can_coexist_with_scale_items() -> None:
    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("SCALE_FORM", "SCALE1", "scale.item_score"),
            _field("SCALE_FORM", "SCALE2", "scale.item_score"),
            _field("SCALE_FORM", "PROCNUM", "study_procedure_number"),
        ],
    )

    assert "G-SCALE-002" not in _rules(report)


def test_ip_change_lifecycle_capability_unavailable_when_fields_missing() -> None:
    """Missing IP change-action families mean capability unavailable."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("EX", "EXDAT", "ip.administration.date"),
            _field("EX", "EXDOSE", "ip.administration.dose"),
            _field("EX", "TRT", "treatment.identity.name"),
        ],
    )

    assert "G-CMIP-007" in _rules(report)
    states = {item.capability_id: item.state for item in report.capability_states}
    assert (
        states["ip_change_lifecycle"]
        == MappingCapabilityStateCode.BLOCKED_BY_QUALITY
    )


def test_ip_change_lifecycle_capability_available_with_all_families() -> None:
    """All five IP change-action families present means capability is available."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("EX", "EXDAT", "ip.administration.date"),
            _field("EX", "EXDOSE", "ip.administration.dose"),
            _field("EX", "TRT", "treatment.identity.name"),
            _field("EX", "ADJ", "ip.dose_adjustment.action"),
            _field("EX", "INT", "ip.interruption.start_date"),
            _field("EX", "DISC", "ip.discontinuation.date"),
            _field("EX", "RST", "ip.restart.date"),
            _field("EX", "OTHER", "ip.other_change.action"),
        ],
    )

    assert "G-CMIP-007" not in _rules(report)


def test_topical_product_dose_with_identity_is_accepted() -> None:
    """Topical/inhaled product with treatment identity is a valid IP mapping."""

    report = evaluate_mapping_semantic_quality(
        fields=[
            _field("TOPICAL", "APP_DATE", "ip.administration.date"),
            _field(
                "TOPICAL",
                "APP_DOSE",
                "ip.administration.dose_with_unit_text",
                dose_semantics="actual_administered",
            ),
            _field("RANDOMIZATION", "ARM", "treatment.identity.randomized_assignment"),
            _field(
                "TOPICAL",
                "TRT",
                "treatment.identity.investigational_product",
                object_identity="investigational_product",
                object_identity_evidence_fields=["TRT"],
                object_identity_binding_id="rand-to-topical",
                validated_treatment_identity_binding=_identity_binding(
                    "rand-to-topical",
                    "TOPICAL",
                ),
            ),
            _field("TOPICAL", "ADJ", "ip.dose_adjustment.action"),
            _field("TOPICAL", "INT", "ip.interruption.start_date"),
            _field("TOPICAL", "DISC", "ip.discontinuation.date"),
            _field("TOPICAL", "RST", "ip.restart.date"),
            _field("TOPICAL", "OTHER", "ip.other_change.action"),
        ],
    )

    assert "G-CMIP-005" not in _rules(report)
    assert report.global_blocker_count == 0


def test_all_ip_action_families_remain_separate() -> None:
    """Administration, dose_adjustment, interruption, discontinuation, restart,
    dispense, return and compliance are eight independent action families."""

    families = [
        ("ip.administration.dose", "EX", "DOSE"),
        ("ip.dose_adjustment.action", "EX", "ADJ"),
        ("ip.interruption.start_date", "EX", "INT"),
        ("ip.discontinuation.date", "EX", "DISC"),
        ("ip.restart.date", "EX", "RST"),
        ("ip.dispense.quantity", "DL", "DISP"),
        ("ip.return.quantity", "DL", "RET"),
        ("ip.compliance.result", "DL", "COMP"),
    ]
    fields = [
        _field(domain, source, role)
        for role, domain, source in families
    ]
    fields.append(_field("EX", "TRT", "treatment.identity.name"))

    report = evaluate_mapping_semantic_quality(fields=fields)

    assert "G-CMIP-002" not in _rules(report)
    assert report.global_blocker_count == 0
