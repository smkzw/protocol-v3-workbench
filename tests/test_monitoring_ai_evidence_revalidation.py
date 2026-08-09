import hashlib
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_ai_evidence_revalidation import (
    AiEvidenceRevalidationIssueCode,
    ai_evidence_revalidation_payload,
    revalidate_p4_ai_evidence,
)


WORKSPACE = Path(__file__).resolve().parents[1]
COVERAGE = Path(
    "records/active_slices/medical_monitoring_release_evidence_coverage_20260802/"
    "CURRENT_RELEASE_COVERAGE.json"
)


def _write_coverage(root: Path, *, mutate=None) -> Path:
    payload = json.loads((WORKSPACE / COVERAGE).read_text(encoding="utf-8"))
    source = root / "source.md"
    source.write_text("source", encoding="utf-8")
    source_bytes = source.stat().st_size
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    payload["sources"] = [
        {
            "id": "source",
            "path": "source.md",
            "bytes": source_bytes,
            "sha256": source_sha,
            "role": "fixture",
        }
    ]
    if mutate:
        mutate(payload)
    path = root / "coverage.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path.relative_to(root)


def test_current_coverage_is_fresh_but_p4_evidence_blocked():
    report = revalidate_p4_ai_evidence(COVERAGE, workspace_root=WORKSPACE)

    assert report.status == "blocked"
    assert report.evidence_fresh is True
    assert report.product_ai_evidence_complete is False
    assert report.coverage_status == "blocked"
    assert report.independent_ai_gate_status == "partial"
    assert report.missing_artifact_ids == (
        "real_product_ai_observations",
        "evaluation_matrix_snapshot",
        "prompt_model_release_snapshot",
    )
    codes = {item.code for item in report.issues}
    assert AiEvidenceRevalidationIssueCode.REAL_OBSERVATIONS_MISSING in codes
    assert AiEvidenceRevalidationIssueCode.EVALUATION_MATRIX_MISSING in codes
    assert AiEvidenceRevalidationIssueCode.RELEASE_SNAPSHOT_MISSING in codes
    assert report.provider_call_permitted is False
    assert report.runtime_activation_permitted is False
    assert report.write_permitted is False


def test_source_drift_is_fail_closed(tmp_path):
    coverage = _write_coverage(tmp_path)
    (tmp_path / "source.md").write_text("drift", encoding="utf-8")

    report = revalidate_p4_ai_evidence(
        coverage,
        workspace_root=tmp_path,
        required_artifacts=(),
    )

    assert report.status == "blocked"
    assert report.evidence_fresh is False
    assert any(
        item.code == AiEvidenceRevalidationIssueCode.SOURCE_BYTES_MISMATCH
        for item in report.issues
    )
    assert any(
        item.code == AiEvidenceRevalidationIssueCode.SOURCE_SHA256_MISMATCH
        for item in report.issues
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 123),
        ("path", 123),
        ("bytes", "6"),
        ("bytes", True),
        ("sha256", 123),
        ("role", 123),
    ],
)
def test_source_declaration_rejects_implicit_type_coercion(tmp_path, field, value):
    def mutate(payload):
        payload["sources"][0][field] = value

    coverage = _write_coverage(tmp_path, mutate=mutate)
    report = revalidate_p4_ai_evidence(
        coverage,
        workspace_root=tmp_path,
        required_artifacts=(),
    )

    assert report.declared_source_count == 0
    assert any(
        item.code == AiEvidenceRevalidationIssueCode.COVERAGE_SHAPE_INVALID
        and item.subject == "sources"
        for item in report.issues
    )


def test_coverage_path_traversal_is_rejected(tmp_path):
    report = revalidate_p4_ai_evidence(
        "../outside.json",
        workspace_root=tmp_path,
        required_artifacts=(),
    )

    assert report.status == "invalid"
    assert any(
        item.code == AiEvidenceRevalidationIssueCode.COVERAGE_PATH_UNSAFE
        for item in report.issues
    )


def test_independent_ai_status_and_decision_drift_are_visible(tmp_path):
    def mutate(payload):
        for row in payload["gate_results"]:
            if row["gate_id"] == "independent_product_ai":
                row["status"] = "passed"
        payload["decision"]["status"] = "ready"
        payload["decision"]["release_ready"] = True

    coverage = _write_coverage(tmp_path, mutate=mutate)
    report = revalidate_p4_ai_evidence(
        coverage,
        workspace_root=tmp_path,
        required_artifacts=(),
    )

    codes = {item.code for item in report.issues}
    assert AiEvidenceRevalidationIssueCode.INDEPENDENT_AI_STATUS_DRIFT in codes
    assert AiEvidenceRevalidationIssueCode.DECISION_STATUS_DRIFT in codes
    assert report.product_ai_evidence_complete is False


def test_existing_unbound_artifact_does_not_become_evidence(tmp_path):
    coverage = _write_coverage(tmp_path)
    (tmp_path / "candidate.json").write_text("{}", encoding="utf-8")

    report = revalidate_p4_ai_evidence(
        coverage,
        workspace_root=tmp_path,
        required_artifacts=(("candidate", "candidate.json"),),
    )

    assert report.missing_artifact_ids == ()
    assert any(
        item.code == AiEvidenceRevalidationIssueCode.ARTIFACT_INVALID
        for item in report.issues
    )
    assert report.product_ai_evidence_complete is False


def test_report_payload_is_deterministic():
    first = revalidate_p4_ai_evidence(COVERAGE, workspace_root=WORKSPACE)
    second = revalidate_p4_ai_evidence(COVERAGE, workspace_root=WORKSPACE)

    assert first.to_dict() == second.to_dict()
    assert ai_evidence_revalidation_payload(first) == ai_evidence_revalidation_payload(
        second
    )


@pytest.mark.parametrize(
    "field",
    ["authority_granted", "decision"],
)
def test_authority_drift_never_grants_permission(tmp_path, field):
    def mutate(payload):
        if field == "authority_granted":
            payload["authority_granted"] = True
        else:
            payload["decision"]["authority_granted"] = True

    coverage = _write_coverage(tmp_path, mutate=mutate)
    report = revalidate_p4_ai_evidence(
        coverage,
        workspace_root=tmp_path,
        required_artifacts=(),
    )

    assert any(
        item.code == AiEvidenceRevalidationIssueCode.AUTHORITY_FLAG_DRIFT
        for item in report.issues
    )
    assert report.authority_granted is False
    assert report.provider_call_permitted is False
    assert report.runtime_activation_permitted is False
    assert report.write_permitted is False
