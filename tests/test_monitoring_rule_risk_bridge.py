from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import inspect

import pytest

from packages.contracts.workbench_contracts.models import (
    RiskSeverity,
    RiskStatus,
)
from services.api.app.monitoring_batch_rule_runner import (
    BatchRuleCandidate,
    BatchRuleDiagnostic,
    BatchRuleRunResult,
)
from services.api.app.monitoring_rule_risk_bridge import (
    MonitoringRuleRiskBridge,
    MonitoringRuleRiskBridgeError,
)


NOW = datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)
PROJECT_ID = "proj_bridge"
SOURCE_HASH = "a" * 64


def _candidate(
    *,
    batch_id: str = "batch_001",
    batch_version: int = 1,
    mapping_revision: str = "maprev_001",
    candidate_id: str = "candidate_001",
    rule_key: str = "ae_mh.cross_domain_review",
    rule_revision_id: str = "monrule_001",
    domain: str = "AE",
    business_key: str = "AE|S01001|1",
    severity: str = "high",
    confidence: str = "deterministic",
    summary: str = "2026-07-20 V3D8 头痛，原始AE记录需与病史记录复核",
    source_hash: object = SOURCE_HASH,
) -> BatchRuleCandidate:
    locator = {
        "source_entry_id": "listing_source",
        "source_content_sha256": source_hash,
        "sheet": domain,
        "row": 12,
    }
    return BatchRuleCandidate(
        candidate_id=candidate_id,
        project_id=PROJECT_ID,
        batch_id=batch_id,
        batch_version=batch_version,
        mapping_revision=mapping_revision,
        rule_pack_id="pack_001",
        rule_revision_id=rule_revision_id,
        rule_key=rule_key,
        subject_id="S01001",
        current_domain=domain,
        current_business_key=business_key,
        severity=severity,
        confidence=confidence,
        evidence_summary=summary,
        evaluation={
            "rule_key": rule_key,
            "rule_revision_id": rule_revision_id,
            "matched": True,
            "preconditions_met": True,
            "excluded": False,
            "missing_required_domains": [],
            "evidence": {
                "medical_review_candidate_only": True,
                "current_record": {
                    "raw_data": {
                        "SUBJID": "S01001",
                        "SITEID": "010",
                        "AETERM": "头痛",
                        "AESTDAT": "2026-07-20",
                        "__source_locator__": [locator],
                        "__batch_row__": {"row_fingerprint": "rowfp_001"},
                    },
                    "source_locators": [locator],
                },
                "previous_record": None,
                "related_records": {},
                "missing_record_queries": [],
            },
            "evidence_summary": summary,
            "protocol_source": {
                "source_entry_id": "protocol_source",
                "source_locator": "docx:paragraph:88",
                "source_text": "需结合既往病史复核不良事件记录。",
            },
        },
    )


def _result(
    candidate: BatchRuleCandidate | None = None,
    *,
    diagnostic: BatchRuleDiagnostic | None = None,
) -> BatchRuleRunResult:
    candidates = (candidate,) if candidate is not None else ()
    diagnostics = (diagnostic,) if diagnostic is not None else ()
    exemplar = candidate or _candidate()
    return BatchRuleRunResult(
        run_id="batch_rule_run_001",
        project_id=PROJECT_ID,
        batch_id=exemplar.batch_id,
        batch_version=exemplar.batch_version,
        mapping_revision=exemplar.mapping_revision,
        rule_pack_id="pack_001",
        rule_revision_ids=(exemplar.rule_revision_id,),
        evaluated_record_count=1,
        candidates=candidates,
        diagnostics=diagnostics,
        output_sha256="f" * 64,
    )


def _bridge(result: BatchRuleRunResult):
    return MonitoringRuleRiskBridge.convert(
        result,
        source_revision="source_revision_001",
        engine_version="monitoring-engine-v1",
        created_at=NOW,
    )


def test_public_convert_interface_is_stable() -> None:
    signature = inspect.signature(MonitoringRuleRiskBridge.convert)

    assert list(signature.parameters) == [
        "result",
        "engine_version",
        "source_revision",
        "created_at",
    ]
    assert signature.parameters["engine_version"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["source_revision"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["created_at"].default is None
    assert signature.return_annotation == "tuple[RiskCase, ...]"


def test_bridge_maps_review_candidate_contract_and_source_lineage() -> None:
    risk = _bridge(_result(_candidate()))[0]

    assert risk.severity is RiskSeverity.HIGH
    assert risk.confidence == 1.0
    assert (
        risk.primary_category
        == "ae_mh_temporal_or_classification_review"
    )
    assert risk.status is RiskStatus.IN_REVIEW
    assert risk.risk_type == "AE/MH关系复核规则候选"
    assert risk.title == "S01001 AE/MH关系复核候选"
    assert risk.scope_type == "subject"
    assert risk.scope_id == "S01001"
    assert risk.site_id == "010"
    assert risk.aggregation_scope == "episode"
    assert risk.episode_key == "AE:AE|S01001|1"
    assert risk.source_batch_id == "batch_001"
    assert risk.source_revision == "source_revision_001"
    assert risk.rule_profile_revision == "pack_001"
    assert risk.engine_version == "monitoring-engine-v1"
    assert risk.rule_id == "ae_mh.cross_domain_review"
    assert {
        "medical_review_candidate",
        "deterministic_rule",
        "cfdi_review_candidate",
        "ae_mh_temporal_or_classification_review",
        "safety_pv",
        "source_domain:ae",
    }.issubset(set(risk.tags))

    assert risk.rationale.startswith(
        "原始数据触发摘要（待医学复核）：2026-07-20 V3D8 头痛"
    )
    assert "不代表已确认诊断、漏报、方案违背或需发出 Query" in risk.rationale
    assert "定位" not in risk.rationale
    assert risk.evidence_span_ids == [
        (
            "source:entry:listing_source:sha256:"
            f"{SOURCE_HASH}:sheet:AE:row:12"
        ),
        "protocol:protocol_source:docx:paragraph:88",
    ]
    snapshot = risk.evidence_snapshots[0]
    assert snapshot.fragment["batch_id"] == "batch_001"
    assert snapshot.fragment["batch_version"] == 1
    assert snapshot.fragment["mapping_revision"] == "maprev_001"
    assert snapshot.fragment["rule_pack_id"] == "pack_001"
    assert snapshot.fragment["rule_revision_id"] == "monrule_001"
    assert snapshot.fragment["engine_version"] == "monitoring-engine-v1"
    assert snapshot.fragment["current_raw_data"] == {
        "SUBJID": "S01001",
        "SITEID": "010",
        "AETERM": "头痛",
        "AESTDAT": "2026-07-20",
    }
    assert snapshot.fragment["raw_value_summary"].startswith("2026-07-20")
    assert snapshot.fragment["medical_review_candidate_only"] is True


@pytest.mark.parametrize("source_hash", [f" {SOURCE_HASH}", SOURCE_HASH.upper(), 123])
def test_source_locator_hash_requires_exact_lowercase_bytes(source_hash: object) -> None:
    with pytest.raises(
        MonitoringRuleRiskBridgeError,
        match="source_content_sha256 must be an exact lowercase SHA-256",
    ):
        _bridge(_result(_candidate(source_hash=source_hash)))


def test_bridge_category_does_not_change_with_evidence_summary_text() -> None:
    ae_wording = _bridge(
        _result(
            _candidate(
                candidate_id="candidate_ae_wording",
                summary="展示文案声称这是AE漏报，但规则身份保持不变。",
            )
        )
    )[0]
    cm_wording = _bridge(
        _result(
            _candidate(
                candidate_id="candidate_cm_wording",
                summary="展示文案改为禁用合并用药PD，规则身份仍保持不变。",
            )
        )
    )[0]

    assert (
        ae_wording.primary_category
        == cm_wording.primary_category
        == "ae_mh_temporal_or_classification_review"
    )
    assert ae_wording.rationale != cm_wording.rationale


@pytest.mark.parametrize(
    ("severity", "confidence", "expected_severity", "expected_confidence"),
    [
        ("low", "low", RiskSeverity.LOW, 0.40),
        ("medium", "medium", RiskSeverity.MEDIUM, 0.65),
        ("high", "high", RiskSeverity.HIGH, 0.85),
        ("critical", "deterministic", RiskSeverity.CRITICAL, 1.00),
    ],
)
def test_severity_and_confidence_mapping(
    severity: str,
    confidence: str,
    expected_severity: RiskSeverity,
    expected_confidence: float,
) -> None:
    risk = _bridge(
        _result(_candidate(severity=severity, confidence=confidence))
    )[0]

    assert risk.severity is expected_severity
    assert risk.confidence == expected_confidence


def test_risk_key_is_cross_batch_stable_but_instance_tracks_batch_and_evidence() -> None:
    first_candidate = _candidate()
    second_candidate = _candidate(
        batch_id="batch_002",
        batch_version=2,
        mapping_revision="maprev_002",
        candidate_id="candidate_002",
        summary="2026-07-21 V4D15 头痛程度变化，原始记录需复核",
    )

    first = _bridge(_result(first_candidate))[0]
    second = _bridge(_result(second_candidate))[0]

    assert first.risk_key == second.risk_key
    assert first.episode_key == second.episode_key
    assert first.risk_instance_id != second.risk_instance_id
    assert first.risk_id != second.risk_id
    assert first.evidence_snapshots[0].fragment["mapping_revision"] == "maprev_001"
    assert second.evidence_snapshots[0].fragment["mapping_revision"] == "maprev_002"

    repeated = _bridge(_result(first_candidate))[0]
    assert repeated.risk_key == first.risk_key
    assert repeated.risk_instance_id == first.risk_instance_id
    assert repeated.model_dump(mode="json") == first.model_dump(mode="json")

    changed_engine = MonitoringRuleRiskBridge.convert(
        _result(first_candidate),
        source_revision="source_revision_001",
        engine_version="monitoring-engine-v2",
        created_at=NOW,
    )[0]
    assert changed_engine.risk_key == first.risk_key
    assert changed_engine.risk_instance_id != first.risk_instance_id


def test_episode_identity_changes_stable_risk_key() -> None:
    first = _bridge(_result(_candidate()))[0]
    another_episode = _bridge(
        _result(
            _candidate(
                candidate_id="candidate_episode_2",
                business_key="AE|S01001|2",
            )
        )
    )[0]

    assert first.risk_key != another_episode.risk_key


def test_cm_and_study_treatment_domains_remain_distinct() -> None:
    cm_risk = _bridge(
        _result(
            _candidate(
                rule_key="concomitant_medication.prohibited.complement_inhibitor",
                rule_revision_id="monrule_cm",
                domain="CM",
                business_key="CM|S01001|1",
            )
        )
    )[0]
    ex_risk = _bridge(
        _result(
            _candidate(
                rule_key="study_treatment.change.restart",
                rule_revision_id="monrule_ex",
                domain="EX",
                business_key="EX|S01001|1",
            )
        )
    )[0]

    assert (
        cm_risk.primary_category
        == "prohibited_concomitant_medication_pd"
    )
    assert cm_risk.risk_type == "禁用合并用药PD规则复核候选"
    assert "non_study_concomitant_medication" in cm_risk.tags
    assert "study_treatment_restart" not in cm_risk.tags
    assert "study_treatment_record" not in cm_risk.tags

    assert ex_risk.primary_category == "study_treatment_restart"
    assert ex_risk.risk_type == "试验药物重启规则复核候选"
    assert "study_treatment_record" in ex_risk.tags
    assert "prohibited_concomitant_medication_pd" not in ex_risk.tags
    assert "non_study_concomitant_medication" not in ex_risk.tags


def test_diagnostics_are_not_converted_into_no_risk_or_risk_cases() -> None:
    diagnostic = BatchRuleDiagnostic(
        diagnostic_id="diag_001",
        code="evaluation_indeterminate",
        message="关键字段缺失，规则结果不确定",
        batch_id="batch_001",
        rule_pack_id="pack_001",
        rule_key="ae_mh.cross_domain_review",
        rule_revision_id="monrule_001",
        subject_id="S01001",
        current_domain="AE",
        current_business_key="AE|S01001|1",
    )

    assert _bridge(_result(diagnostic=diagnostic)) == ()


def test_bridge_rejects_nonmatched_or_cross_lineage_candidates() -> None:
    candidate = _candidate()
    nonmatched = replace(
        candidate,
        evaluation={**candidate.evaluation, "matched": False},
    )
    with pytest.raises(
        MonitoringRuleRiskBridgeError,
        match="only matched candidates",
    ):
        _bridge(_result(nonmatched))

    wrong_batch = replace(candidate, batch_id="batch_other")
    result = _result(candidate)
    with pytest.raises(
        MonitoringRuleRiskBridgeError,
        match="candidate lineage",
    ):
        _bridge(replace(result, candidates=(wrong_batch,)))


def test_original_value_fallback_precedes_locator_metadata() -> None:
    candidate = _candidate(summary="")
    risk = _bridge(_result(candidate))[0]

    assert risk.rationale.startswith(
        "原始数据触发摘要（待医学复核）："
    )
    assert "AETERM=头痛" in risk.rationale
    assert "source:entry:" not in risk.rationale
    assert risk.evidence_span_ids
