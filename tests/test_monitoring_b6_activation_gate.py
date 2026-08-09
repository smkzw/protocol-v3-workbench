from __future__ import annotations

import hashlib
import json

import pytest

from services.api.app.monitoring_b6_activation_gate import (
    B6ActivationGateError,
    B6ActivationGateReport,
    build_b6_activation_gate_report,
)


def _b6_payload():
    return {
        "read_only": True,
        "migration_write_permitted": False,
        "gate": {
            "status": "pending_review",
            "migration_ready": False,
            "write_permitted": False,
            "candidate_count": 2,
            "outcome_count": 0,
            "missing_candidate_record_ids": ["candidate-1", "candidate-2"],
            "rejected_candidate_record_ids": [],
            "pending_candidate_record_ids": [],
            "unresolved_blockers": ["replay_pending", "source_revision_review_pending"],
            "accepted_review_ids": [],
        },
    }


def _c13_payload():
    payload = {
        "schema_only": True,
        "activation_allowed": False,
        "report_content_sha256": "a" * 64,
        "reports": [
            {
                "rows": [
                    {
                        "status": "blocked_pending_approval",
                        "event_creation_allowed": False,
                        "projection_allowed": False,
                        "activation_allowed": False,
                    },
                    {
                        "status": "blocked_pending_approval",
                        "event_creation_allowed": False,
                        "projection_allowed": False,
                        "activation_allowed": False,
                    },
                ],
            },
        ],
    }
    payload["report_content_sha256"] = _content_hash(payload)
    return payload


def _content_hash(payload):
    unhashed = {key: value for key, value in payload.items() if key != "report_content_sha256"}
    return hashlib.sha256(
        json.dumps(unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_b6_gate_binds_pending_review_to_blocked_c13() -> None:
    report = build_b6_activation_gate_report(
        _b6_payload(),
        _c13_payload(),
        b6_evidence_sha256="b" * 64,
    )

    assert report.status == "blocked_pending_b6_review"
    assert report.b6_status == "pending_review"
    assert report.candidate_count == 2
    assert report.outcome_count == 0
    assert report.activation_allowed is False
    assert report.event_creation_allowed is False
    assert report.projection_allowed is False
    assert report.c13_row_count == 2
    assert report.c13_blocked_row_count == 2
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_b6_gate_rejects_status_count_or_c13_drift() -> None:
    tampered_status = _b6_payload()
    tampered_status["gate"]["status"] = "approved"
    with pytest.raises(B6ActivationGateError, match="pending_review"):
        build_b6_activation_gate_report(tampered_status, _c13_payload(), b6_evidence_sha256="b" * 64)

    tampered_count = _b6_payload()
    tampered_count["gate"]["candidate_count"] = 3
    with pytest.raises(B6ActivationGateError, match="counts|categories"):
        build_b6_activation_gate_report(tampered_count, _c13_payload(), b6_evidence_sha256="b" * 64)

    tampered_c13 = _c13_payload()
    tampered_c13["reports"][0]["rows"][0]["activation_allowed"] = True
    tampered_c13["report_content_sha256"] = _content_hash(tampered_c13)
    with pytest.raises(B6ActivationGateError, match="non-blocked"):
        build_b6_activation_gate_report(_b6_payload(), tampered_c13, b6_evidence_sha256="b" * 64)


def test_b6_gate_requires_explicit_unresolved_blockers_and_consistent_categories() -> None:
    no_blockers = _b6_payload()
    no_blockers["gate"]["unresolved_blockers"] = []
    with pytest.raises(B6ActivationGateError, match="counts"):
        build_b6_activation_gate_report(no_blockers, _c13_payload(), b6_evidence_sha256="b" * 64)

    inconsistent = _b6_payload()
    inconsistent["gate"]["outcome_count"] = 1
    with pytest.raises(B6ActivationGateError, match="categories|outcome_count"):
        build_b6_activation_gate_report(inconsistent, _c13_payload(), b6_evidence_sha256="b" * 64)


def test_b6_gate_accepts_explicit_defer_outcomes_without_activation() -> None:
    deferred = _b6_payload()
    deferred["gate"].update(
        outcome_count=2,
        missing_candidate_record_ids=[],
        pending_candidate_record_ids=["candidate-1", "candidate-2"],
    )
    report = build_b6_activation_gate_report(
        deferred,
        _c13_payload(),
        b6_evidence_sha256="b" * 64,
    )
    assert report.status == "blocked_pending_b6_review"
    assert report.outcome_count == 2
    assert report.pending_candidate_record_ids == ("candidate-1", "candidate-2")
    assert report.migration_ready is False
    assert report.activation_allowed is False
    assert report.event_creation_allowed is False
    assert report.projection_allowed is False


def test_b6_gate_rejects_string_authority_flags() -> None:
    tampered = _b6_payload()
    tampered["gate"]["write_permitted"] = "false"
    with pytest.raises(B6ActivationGateError, match="must be boolean"):
        build_b6_activation_gate_report(tampered, _c13_payload(), b6_evidence_sha256="b" * 64)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("candidate_count", True),
        ("candidate_count", "2"),
        ("outcome_count", "0"),
        ("outcome_count", 0.0),
    ),
)
def test_b6_gate_rejects_coerced_counts(field: str, value: object) -> None:
    tampered = _b6_payload()
    tampered["gate"][field] = value
    with pytest.raises(B6ActivationGateError, match="non-negative integer"):
        build_b6_activation_gate_report(
            tampered,
            _c13_payload(),
            b6_evidence_sha256="b" * 64,
        )


@pytest.mark.parametrize("field", ("missing_candidate_record_ids", "unresolved_blockers"))
def test_b6_gate_rejects_scalar_id_lists(field: str) -> None:
    tampered = _b6_payload()
    tampered["gate"][field] = "scalar-value"
    with pytest.raises(B6ActivationGateError, match="string array"):
        build_b6_activation_gate_report(
            tampered,
            _c13_payload(),
            b6_evidence_sha256="b" * 64,
        )


def test_b6_gate_rejects_non_string_id_items() -> None:
    tampered = _b6_payload()
    tampered["gate"]["missing_candidate_record_ids"] = ["candidate-1", 2]
    with pytest.raises(B6ActivationGateError, match="non-empty strings"):
        build_b6_activation_gate_report(
            tampered,
            _c13_payload(),
            b6_evidence_sha256="b" * 64,
        )


def test_b6_gate_rejects_c13_content_hash_mismatch() -> None:
    tampered = _c13_payload()
    tampered["reports"][0]["rows"][0]["status"] = "tampered"
    with pytest.raises(B6ActivationGateError, match="does not match report content"):
        build_b6_activation_gate_report(
            _b6_payload(),
            tampered,
            b6_evidence_sha256="b" * 64,
        )


@pytest.mark.parametrize(
    "reports",
    (
        "scalar",
        [None],
        [{"rows": "scalar"}],
        [{"rows": [None]}],
    ),
)
def test_b6_gate_rejects_malformed_c13_report_shape(reports) -> None:
    tampered = _c13_payload()
    tampered["reports"] = reports
    tampered["report_content_sha256"] = _content_hash(tampered)

    with pytest.raises(B6ActivationGateError, match="object array|only objects"):
        build_b6_activation_gate_report(
            _b6_payload(),
            tampered,
            b6_evidence_sha256="b" * 64,
        )


@pytest.mark.parametrize("field", ("candidate_count", "outcome_count", "c13_row_count"))
def test_b6_report_rejects_boolean_counts(field: str) -> None:
    kwargs = dict(
        b6_evidence_sha256="b" * 64,
        c13_report_content_sha256="a" * 64,
        b6_status="pending_review",
        migration_ready=False,
        write_permitted=False,
        migration_write_permitted=False,
        candidate_count=1,
        outcome_count=0,
        missing_candidate_record_ids=("candidate-1",),
        rejected_candidate_record_ids=(),
        pending_candidate_record_ids=(),
        unresolved_blockers=("review_pending",),
        accepted_review_ids=(),
        c13_row_count=1,
        c13_blocked_row_count=1,
    )
    kwargs[field] = True
    with pytest.raises(B6ActivationGateError, match="non-negative integer"):
        B6ActivationGateReport(**kwargs)


def test_b6_report_cannot_claim_activation() -> None:
    kwargs = dict(
        b6_evidence_sha256="b" * 64,
        c13_report_content_sha256="a" * 64,
        b6_status="pending_review",
        migration_ready=False,
        write_permitted=False,
        migration_write_permitted=False,
        candidate_count=1,
        outcome_count=0,
        missing_candidate_record_ids=("candidate-1",),
        rejected_candidate_record_ids=(),
        pending_candidate_record_ids=(),
        unresolved_blockers=("review_pending",),
        accepted_review_ids=(),
        c13_row_count=1,
        c13_blocked_row_count=1,
    )
    with pytest.raises(B6ActivationGateError, match="block activation"):
        B6ActivationGateReport(**kwargs, activation_allowed=True)
