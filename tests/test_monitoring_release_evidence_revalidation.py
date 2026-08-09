from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_release_evidence_revalidation import (
    ReleaseEvidenceRevalidationIssueCode,
    ReleaseEvidenceRevalidationError,
    revalidate_release_evidence,
)


ROOT = Path(
    "records/active_slices/medical_monitoring_release_evidence_coverage_20260802"
)
B6_PATH = Path(
    "runs/execution/medical_monitoring_phase_b6_review_gate_20260801/"
    "B6_REVIEW_OUTCOME_GATE.json"
)
C14_PATH = Path(
    "runs/execution/medical_monitoring_phase_c14_b6_activation_gate_20260802/"
    "B6_TO_C13_ACTIVATION_GATE_REPORT.json"
)


def _coverage() -> dict:
    return json.loads((ROOT / "CURRENT_RELEASE_COVERAGE.json").read_text())


def _upstream() -> tuple[dict, dict]:
    return json.loads(B6_PATH.read_text()), json.loads(C14_PATH.read_text())


def test_current_release_snapshot_is_fresh_but_release_remains_blocked() -> None:
    b6, c14 = _upstream()
    report = revalidate_release_evidence(_coverage(), b6_payload=b6, c14_payload=c14)

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.source_count == 6
    assert report.source_match_count == 6
    assert report.gate_count == 16
    assert report.gate_bound_count == 16
    assert report.decision_gate_order_matches is True
    assert report.b6_snapshot_matches is True
    assert report.release_decision_status == "blocked"
    assert report.release_ready_observed is False
    assert report.issues == ()
    assert report.read_only is True
    assert report.authority_granted is False


def test_report_rejects_non_boolean_freshness_flag() -> None:
    b6, c14 = _upstream()
    report = revalidate_release_evidence(_coverage(), b6_payload=b6, c14_payload=c14)

    with pytest.raises(ReleaseEvidenceRevalidationError, match="strict boolean"):
        replace(report, evidence_fresh="true")


def test_source_content_drift_blocks_revalidation(tmp_path: Path) -> None:
    coverage = _coverage()
    b6, c14 = _upstream()
    path = tmp_path / "drifted.txt"
    path.write_text("drifted")
    coverage["sources"][0]["path"] = str(path)

    report = revalidate_release_evidence(coverage, b6_payload=b6, c14_payload=c14)

    assert report.status == "blocked"
    assert report.evidence_fresh is False
    assert any(
        issue.code is ReleaseEvidenceRevalidationIssueCode.SOURCE_BYTES_MISMATCH
        or issue.code is ReleaseEvidenceRevalidationIssueCode.SOURCE_SHA256_MISMATCH
        or issue.code is ReleaseEvidenceRevalidationIssueCode.SOURCE_PATH_UNSAFE
        for issue in report.issues
    )


def test_source_and_gate_hashes_require_exact_lowercase_bytes() -> None:
    coverage = _coverage()
    b6, c14 = _upstream()

    coverage["sources"][0]["sha256"] = coverage["sources"][0]["sha256"].upper()
    source_report = revalidate_release_evidence(
        coverage,
        b6_payload=b6,
        c14_payload=c14,
    )
    assert source_report.status == "blocked"
    assert any(
        issue.code is ReleaseEvidenceRevalidationIssueCode.SOURCE_FIELD_INVALID
        for issue in source_report.issues
    )

    coverage = _coverage()
    gate_hash = coverage["sources"][0]["sha256"].upper()
    coverage["gate_results"][0]["evidence_sha256"] = gate_hash
    coverage["decision"]["gate_results"][0]["evidence_sha256"] = gate_hash
    gate_report = revalidate_release_evidence(
        coverage,
        b6_payload=b6,
        c14_payload=c14,
    )
    assert gate_report.status == "blocked"
    assert gate_report.gate_bound_count == 15
    assert any(
        issue.code is ReleaseEvidenceRevalidationIssueCode.GATE_EVIDENCE_UNBOUND
        for issue in gate_report.issues
    )


def test_source_path_traversal_and_symlink_are_rejected(tmp_path: Path) -> None:
    coverage = _coverage()
    b6, c14 = _upstream()

    coverage["sources"][0]["path"] = "../outside.txt"
    traversal = revalidate_release_evidence(
        coverage, b6_payload=b6, c14_payload=c14
    )
    assert traversal.status == "blocked"
    assert any(
        issue.code is ReleaseEvidenceRevalidationIssueCode.SOURCE_PATH_UNSAFE
        for issue in traversal.issues
    )

    link_target = tmp_path / "target.txt"
    link_target.write_text("evidence")
    link = tmp_path / "link.txt"
    link.symlink_to(link_target)
    coverage["sources"][0]["path"] = str(link)
    symlink = revalidate_release_evidence(
        coverage, b6_payload=b6, c14_payload=c14
    )
    assert symlink.status == "blocked"
    assert any(
        issue.code is ReleaseEvidenceRevalidationIssueCode.SOURCE_PATH_UNSAFE
        or issue.code is ReleaseEvidenceRevalidationIssueCode.SOURCE_SYMLINK_UNSUPPORTED
        for issue in symlink.issues
    )


def test_unbound_gate_hash_blocks_revalidation() -> None:
    coverage = _coverage()
    b6, c14 = _upstream()
    coverage["gate_results"][0]["evidence_sha256"] = "b" * 64
    coverage["decision"]["gate_results"][0]["evidence_sha256"] = "b" * 64

    report = revalidate_release_evidence(coverage, b6_payload=b6, c14_payload=c14)

    assert report.status == "blocked"
    assert report.gate_bound_count == 15
    assert any(
        issue.code is ReleaseEvidenceRevalidationIssueCode.GATE_EVIDENCE_UNBOUND
        for issue in report.issues
    )


def test_decision_order_and_b6_snapshot_drift_fail_closed() -> None:
    coverage = _coverage()
    b6, c14 = _upstream()
    coverage["decision"]["gate_results"] = list(
        reversed(coverage["decision"]["gate_results"])
    )
    coverage["b6_current"]["status"] = "approved"

    report = revalidate_release_evidence(coverage, b6_payload=b6, c14_payload=c14)
    codes = {issue.code for issue in report.issues}

    assert report.status == "blocked"
    assert ReleaseEvidenceRevalidationIssueCode.DECISION_GATE_ORDER_MISMATCH in codes
    assert ReleaseEvidenceRevalidationIssueCode.B6_SNAPSHOT_MISMATCH in codes


def test_decision_derived_fields_and_b6_projection_must_match() -> None:
    coverage = _coverage()
    b6, c14 = _upstream()
    coverage["decision"]["status"] = "ready"
    coverage["decision"]["release_ready"] = True
    coverage["decision"]["b6_status"] = "approved"

    report = revalidate_release_evidence(coverage, b6_payload=b6, c14_payload=c14)
    codes = {issue.code for issue in report.issues}

    assert report.status == "blocked"
    assert ReleaseEvidenceRevalidationIssueCode.DECISION_DERIVED_MISMATCH in codes


def test_unknown_gate_status_is_not_fresh() -> None:
    coverage = _coverage()
    b6, c14 = _upstream()
    coverage["gate_results"][0]["status"] = "ready"
    coverage["decision"]["gate_results"][0]["status"] = "ready"

    report = revalidate_release_evidence(coverage, b6_payload=b6, c14_payload=c14)

    assert report.status == "blocked"
    assert any(
        issue.code is ReleaseEvidenceRevalidationIssueCode.GATE_STATUS_INVALID
        for issue in report.issues
    )


def test_true_authority_flag_is_rejected_even_when_sources_are_current() -> None:
    coverage = deepcopy(_coverage())
    b6, c14 = _upstream()
    coverage["authority_granted"] = True

    report = revalidate_release_evidence(coverage, b6_payload=b6, c14_payload=c14)

    assert report.status == "blocked"
    assert any(
        issue.code is ReleaseEvidenceRevalidationIssueCode.AUTHORITY_FLAG_TRUE
        for issue in report.issues
    )
