from __future__ import annotations

from datetime import datetime, timezone

import pytest

from packages.contracts.workbench_contracts.models import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
)
from services.api.app.medical_monitoring_risk_taxonomy import (
    TAXONOMY_VERSION,
    canonical_risk_category_codes,
    classify_rule_risk_category,
    normalize_risk_case_category,
    project_risk_category,
    resolve_risk_category,
    risk_taxonomy_payload,
)


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _risk(
    *,
    primary_category: str,
    title: str = "展示标题",
    rationale: str = "展示理由",
    tags: list[str] | None = None,
) -> RiskCase:
    return RiskCase(
        risk_id="risk_001",
        risk_key="riskkey_001",
        risk_instance_id="riskinst_001",
        project_id="proj_test",
        module="medical_monitoring",
        risk_type="任意展示类型",
        primary_category=primary_category,
        tags=tags or [],
        title=title,
        subject_id="S001",
        site_id="01",
        severity=RiskSeverity.HIGH,
        status=RiskStatus.IN_REVIEW,
        rule_id="rule.explicit.identity",
        rationale=rationale,
        recommended_action="医学复核。",
        created_at=NOW,
    )


def test_taxonomy_is_closed_versioned_and_covers_p8a_categories() -> None:
    payload = risk_taxonomy_payload()
    codes = [item["code"] for item in payload["categories"]]

    assert payload["closed"] is True
    assert payload["taxonomy_version"] == TAXONOMY_VERSION
    assert tuple(codes) == canonical_risk_category_codes()
    assert len(codes) == len(set(codes)) == 18
    assert {
        "ae_missing_report",
        "mh_missing_report",
        "ae_mh_temporal_or_classification_review",
        "cs_ncs_inconsistent",
        "prohibited_concomitant_medication_pd",
        "restricted_concomitant_medication_pd",
        "study_treatment_dose_change",
        "study_treatment_interruption",
        "study_treatment_permanent_discontinuation",
        "study_treatment_restart",
        "study_treatment_adherence",
        "visit_window_or_order_pd",
        "other_protocol_execution_pd",
        "laboratory_abnormality",
        "ctcae_grade_worsening",
        "efficacy_assessment_missing_or_inconsistent",
        "data_quality",
        "other_medical_review",
    } == set(codes)
    assert all(
        {
            "code",
            "label",
            "taxonomy_version",
            "safety_pv_flag",
            "domain_boundary",
        }
        == set(item)
        for item in payload["categories"]
    )


def test_legacy_coarse_category_degrades_without_using_display_text() -> None:
    first = _risk(
        primary_category="safety_ae_mh",
        title="确定为AE漏报",
        rationale="标题和理由都包含AE漏报。",
    )
    second = first.model_copy(
        update={
            "title": "禁用合并用药PD",
            "rationale": "完全不同的展示文案。",
        }
    )

    first_projection = project_risk_category(first)
    second_projection = project_risk_category(second)

    assert first_projection["risk_category_code"] == "other_medical_review"
    assert second_projection["risk_category_code"] == "other_medical_review"
    assert first_projection["risk_category_lineage"] == {
        "source_code": "safety_ae_mh",
        "mapping_kind": "legacy_coarse",
    }
    normalized = normalize_risk_case_category(first)
    assert normalized.primary_category == "other_medical_review"
    assert (
        "risk_category_lineage:legacy_coarse:safety_ae_mh"
        in normalized.tags
    )


def test_safety_pv_is_an_independent_overlay_on_one_primary_category() -> None:
    unflagged = project_risk_category(
        _risk(primary_category="ae_missing_report")
    )
    flagged = project_risk_category(
        _risk(
            primary_category="ae_missing_report",
            tags=["safety_pv"],
        )
    )

    assert unflagged["risk_category_code"] == flagged["risk_category_code"]
    assert unflagged["safety_pv_flag"] is False
    assert flagged["safety_pv_flag"] is True


def test_rule_identity_and_explicit_parameters_drive_classification() -> None:
    ae_review = classify_rule_risk_category(
        rule_key="ae_mh.pre_treatment_event_without_same_day_history",
        current_domain="AE",
        evaluation={},
    )
    prohibited_cm = classify_rule_risk_category(
        rule_key="generic.medication.rule",
        current_domain="CM",
        evaluation={
            "classification": {
                "rule_family": "concomitant_medication_policy",
                "category_parameter": "prohibited",
            }
        },
    )

    assert (
        ae_review.code.value
        == "ae_mh_temporal_or_classification_review"
    )
    assert (
        prohibited_cm.code.value
        == "prohibited_concomitant_medication_pd"
    )

    with pytest.raises(ValueError, match="require CM"):
        classify_rule_risk_category(
            rule_key="generic.medication.rule",
            current_domain="EX",
            evaluation={
                "risk_category_code": "prohibited_concomitant_medication_pd"
            },
        )


def test_unknown_legacy_code_has_explicit_unknown_lineage() -> None:
    resolution = resolve_risk_category("legacy_free_text_category")

    assert resolution.definition.code.value == "other_medical_review"
    assert resolution.mapping_kind == "unknown"
    assert resolution.source_code == "legacy_free_text_category"
