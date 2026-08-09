from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from services.api.app.monitoring_ai_contracts import content_sha256
from services.api.app.monitoring_ai_field_profiler import (
    FieldAnomalyExample,
    FieldValueFrequency,
    MonitoringFieldProfile,
    MonitoringFieldProfileSnapshot,
)
from services.api.app.monitoring_metric_configuration import (
    METRIC_CANDIDATE_STATUS,
    METRIC_DECLARATION_VERSION,
    MetricConfigurationIssueCode,
    build_metric_configuration_candidates,
)
from services.api.app.monitoring_protocol_rules import ProtocolFact


PROJECT = "project-neutral-metric"
VERSION = "protocol-version-1"
SOURCE_ENTRY = "protocol-source"


def _profile(*, project_id: str = PROJECT, sparse: bool = False):
    field = MonitoringFieldProfile(
        domain="QS",
        field="EASI_TOTAL",
        total_rows=10 if not sparse else 0,
        non_empty_count=8 if not sparse else 0,
        null_rate=0.2 if not sparse else 1.0,
        inferred_type="decimal",
        unique_value_count=4,
        top_values=(FieldValueFrequency(value=1.0, count=2, observed_type="decimal"),),
        representative_values=(1.0,),
        anomaly_examples=(),
    )
    snapshot = MonitoringFieldProfileSnapshot(
        schema_version="monitoring_ai_field_profile_v3",
        batch_id="batch-001",
        project_id=project_id,
        batch_revision=2,
        mapping_revision="mapping-1",
        expected_domains=("QS",),
        source_bindings=(("listing-source", "b" * 64),),
        source_sha256s=("b" * 64,),
        row_count=field.total_rows,
        input_sha256="c" * 64,
        fields=(field,),
        relationships=(),
        profile_sha256="d" * 64,
    )
    payload = snapshot.to_dict()
    payload.pop("profile_sha256")
    return replace(snapshot, profile_sha256=content_sha256(payload))


def _fact(
    *,
    fact_type: str = "efficacy_assessment",
    status: str = "medically_confirmed",
    payload: dict | None = None,
    project_id: str = PROJECT,
    protocol_version_id: str = VERSION,
    key: str = "efficacy.easi",
):
    return ProtocolFact.create(
        project_id=project_id,
        protocol_version_id=protocol_version_id,
        fact_key=key,
        fact_type=fact_type,
        status=status,
        title="疗效终点",
        normalized_payload=(
            payload
            if payload is not None
            else {
                "metric_configuration_version": METRIC_DECLARATION_VERSION,
                "metric_candidates": [
                    {
                        "metric_kind": "efficacy",
                        "metric_key": "easi_total",
                        "metric_label": "EASI总分",
                        "unit": "分",
                        "direction": "lower_is_better",
                        "assessment_window": "Week 16",
                        "field_refs": [{"domain": "QS", "field": "EASI_TOTAL"}],
                    }
                ],
            }
        ),
        source_entry_id=SOURCE_ENTRY,
        source_locator="docx:table:4:row:2",
        source_text="EASI总分于第16周评价。",
    )


def _codes(bundle):
    return {item.code for item in bundle.issues}


def test_explicit_confirmed_fact_and_exact_profile_field_produce_pending_candidate():
    first = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[_fact()],
        field_profile=_profile(),
    )
    second = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[_fact()],
        field_profile=_profile(),
    )

    assert first.bundle_sha256 == second.bundle_sha256
    assert first.issues == ()
    assert len(first.candidates) == 1
    candidate = first.candidates[0]
    assert candidate.status == METRIC_CANDIDATE_STATUS
    assert first.medically_confirmed is False
    assert first.usable_candidate_count == 1
    assert candidate.field_refs[0].domain == "QS"
    assert candidate.field_evidence[0].non_empty_count == 8
    assert candidate.fact_source_text_sha256 == sha256(
        "EASI总分于第16周评价。".encode("utf-8")
    ).hexdigest()


def test_missing_declaration_unconfirmed_fact_and_unsupported_fact_are_gaps():
    missing = _fact(payload={"value": "方案未结构化为指标声明"})
    unconfirmed = _fact(status="ai_candidate", key="efficacy.ai")
    unsupported = _fact(
        fact_type="visit_schedule",
        key="visit.schedule",
        payload={
            "metric_configuration_version": METRIC_DECLARATION_VERSION,
            "metric_candidates": [],
        },
    )
    bundle = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[missing, unconfirmed, unsupported],
        field_profile=_profile(),
    )

    assert bundle.candidates == ()
    assert {
        MetricConfigurationIssueCode.METRIC_DECLARATIONS_MISSING,
        MetricConfigurationIssueCode.UNCONFIRMED_PROTOCOL_FACT,
        MetricConfigurationIssueCode.UNSUPPORTED_FACT_TYPE,
    } <= _codes(bundle)


def test_unknown_field_and_kind_mismatch_never_emit_candidate():
    unknown = _fact(
        payload={
            "metric_configuration_version": METRIC_DECLARATION_VERSION,
            "metric_candidates": [
                {
                    "metric_kind": "efficacy",
                    "metric_key": "unknown",
                    "metric_label": "未映射",
                    "unit": "分",
                    "direction": "lower_is_better",
                    "assessment_window": "Week 16",
                    "field_refs": [{"domain": "QS", "field": "NOT_IN_PROFILE"}],
                }
            ],
        },
        key="efficacy.unknown",
    )
    mismatch = _fact(
        payload={
            "metric_configuration_version": METRIC_DECLARATION_VERSION,
            "metric_candidates": [
                {
                    "metric_kind": "safety",
                    "metric_key": "easi_as_safety",
                    "metric_label": "错误域",
                    "unit": "分",
                    "direction": "stable_range",
                    "assessment_window": "Week 16",
                    "field_refs": [{"domain": "QS", "field": "EASI_TOTAL"}],
                }
            ],
        },
        key="efficacy.mismatch",
    )
    bundle = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[unknown, mismatch],
        field_profile=_profile(),
    )

    assert bundle.candidates == ()
    assert {
        MetricConfigurationIssueCode.LISTING_FIELD_MISSING,
        MetricConfigurationIssueCode.METRIC_KIND_MISMATCH,
    } <= _codes(bundle)


def test_sparse_exact_field_emits_candidate_with_explicit_review_flag():
    bundle = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[_fact()],
        field_profile=_profile(sparse=True),
    )

    assert len(bundle.candidates) == 1
    assert bundle.candidates[0].review_flags == ("sparse_listing_field",)
    assert MetricConfigurationIssueCode.LISTING_FIELD_SPARSE in _codes(bundle)
    assert bundle.usable_candidate_count == 0


def test_profile_is_fail_closed_and_redacted_ai_payload_is_not_accepted():
    invalid = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[_fact()],
        field_profile=None,
    )
    redacted = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[_fact()],
        field_profile=_profile().to_ai_payload(),
    )

    assert invalid.candidates == ()
    assert redacted.candidates == ()
    assert MetricConfigurationIssueCode.LISTING_PROFILE_INVALID in _codes(invalid)
    assert MetricConfigurationIssueCode.LISTING_PROFILE_INVALID in _codes(redacted)


def test_project_and_protocol_version_mismatches_are_blocked():
    bundle = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[
            _fact(project_id="other-project"),
            _fact(protocol_version_id="other-version", key="efficacy.other"),
        ],
        field_profile=_profile(),
    )

    assert bundle.candidates == ()
    assert {
        MetricConfigurationIssueCode.FACT_PROJECT_MISMATCH,
        MetricConfigurationIssueCode.FACT_PROTOCOL_VERSION_MISMATCH,
    } <= _codes(bundle)


def test_duplicate_metric_key_and_invalid_declaration_are_deterministic_gaps():
    duplicate = _fact(key="efficacy.duplicate")
    duplicate_again = _fact(key="efficacy.duplicate-again")
    invalid = _fact(
        key="efficacy.invalid",
        payload={
            "metric_configuration_version": METRIC_DECLARATION_VERSION,
            "metric_candidates": [
                {
                    "metric_kind": "efficacy",
                    "metric_key": "bad key",
                    "metric_label": "非法",
                    "unit": "",
                    "direction": "lower_is_better",
                    "assessment_window": "",
                    "field_refs": [{"domain": "QS", "field": "EASI_TOTAL"}],
                }
            ],
        },
    )
    bundle = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[duplicate, duplicate_again, invalid],
        field_profile=_profile(),
    )

    assert len(bundle.candidates) == 1
    assert MetricConfigurationIssueCode.DUPLICATE_METRIC_KEY in _codes(bundle)
    assert MetricConfigurationIssueCode.METRIC_DECLARATION_INVALID in _codes(bundle)


def test_candidate_identity_tampering_is_rejected():
    bundle = build_metric_configuration_candidates(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        facts=[_fact()],
        field_profile=_profile(),
    )
    payload = bundle.candidates[0].model_dump(mode="python")
    payload["candidate_id"] = "tampered-candidate"
    with pytest.raises(ValueError, match="identity digest drift"):
        type(bundle.candidates[0]).model_validate(payload)
