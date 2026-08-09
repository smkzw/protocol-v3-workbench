from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import pytest

from services.api.app.monitoring_real_loop_acceptance import (
    ACCEPTANCE_PROJECT_IDS,
    ACCEPTANCE_ROLES,
    ACCEPTANCE_TESTER_IDS,
    assess_real_loop_acceptance,
)
from services.api.app.monitoring_real_loop_acceptance_revalidation import (
    REAL_LOOP_ACCEPTANCE_REVALIDATION_SCHEMA_VERSION,
    RealLoopAcceptanceRevalidationError,
    RealLoopAcceptanceRevalidationIssueCode,
    revalidate_real_loop_acceptance_file,
    revalidate_real_loop_acceptance_payload,
)
from tests.test_monitoring_real_loop_acceptance import (
    EVIDENCE_CHAIN_KWARGS,
    clean_runs,
    prompt_manifest,
)


def _payload() -> dict[str, object]:
    rows = clean_runs()
    prompts = prompt_manifest(rows)
    report = assess_real_loop_acceptance(
        rows,
        prompt_manifest=prompts,
        **EVIDENCE_CHAIN_KWARGS,
    )
    return {
        "schema_version": REAL_LOOP_ACCEPTANCE_REVALIDATION_SCHEMA_VERSION,
        "mode": "read_only",
        "authority_granted": False,
        "release_ready": False,
        "prompt_manifest": [
            {"prompt_ref": item.prompt_ref, "prompt_sha256": item.prompt_sha256}
            for item in prompts
        ],
        "runs": [item.to_dict() for item in rows],
        "expected_testers": list(ACCEPTANCE_TESTER_IDS),
        "expected_roles": list(ACCEPTANCE_ROLES),
        "allowed_project_ids": list(ACCEPTANCE_PROJECT_IDS),
        "required_consecutive_clean_rounds": 2,
        **EVIDENCE_CHAIN_KWARGS,
        "acceptance_report": report.to_dict(),
    }


def test_clean_persisted_payload_replays_canonical_acceptance() -> None:
    report = revalidate_real_loop_acceptance_payload(_payload())

    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.payload_valid is True
    assert report.report_matches is True
    assert report.file_checked is False
    assert report.acceptance_status == "accepted_for_user_acceptance"
    assert report.acceptance_complete_observed is True
    assert (report.tester_count, report.role_count, report.run_count) == (5, 2, 20)
    assert report.readiness_report_sha256 == EVIDENCE_CHAIN_KWARGS["readiness_report_sha256"]
    assert report.generalization_evidence_sha256 == EVIDENCE_CHAIN_KWARGS[
        "generalization_evidence_sha256"
    ]
    assert report.execution_report_sha256 == EVIDENCE_CHAIN_KWARGS["execution_report_sha256"]
    assert report.semantics_binding_sha256 == EVIDENCE_CHAIN_KWARGS[
        "semantics_binding_sha256"
    ]
    assert report.issues == ()
    assert report.authority_granted is False
    assert report.release_ready is False
    assert report.medical_confirmation_permitted is False
    assert report.runtime_write_permitted is False


def test_revalidation_report_chain_hash_rejects_noncanonical_shape() -> None:
    report = revalidate_real_loop_acceptance_payload(_payload())
    with pytest.raises(
        RealLoopAcceptanceRevalidationError,
        match="lowercase SHA-256",
    ):
        replace(report, readiness_report_sha256="A" * 64)


def test_derived_report_drift_is_blocked() -> None:
    payload = _payload()
    report = dict(payload["acceptance_report"])  # type: ignore[arg-type]
    report["run_count"] = 19
    payload["acceptance_report"] = report

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.REPORT_DERIVED_MISMATCH in {
        item.code for item in result.issues
    }
    assert result.report_matches is False


def test_non_boolean_persisted_acceptance_complete_is_blocked() -> None:
    payload = _payload()
    report = dict(payload["acceptance_report"])  # type: ignore[arg-type]
    report["acceptance_complete"] = "false"
    payload["acceptance_report"] = report

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert result.acceptance_complete_observed is False
    assert RealLoopAcceptanceRevalidationIssueCode.REPORT_SHAPE_INVALID in {
        item.code for item in result.issues
    }


def test_authority_and_release_flags_never_pass() -> None:
    payload = _payload()
    payload["authority_granted"] = True
    payload["release_ready"] = True

    result = revalidate_real_loop_acceptance_payload(payload)

    codes = {item.code for item in result.issues}
    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.AUTHORITY_FLAG_TRUE in codes
    assert RealLoopAcceptanceRevalidationIssueCode.RELEASE_READY_FLAG_TRUE in codes


def test_file_identity_and_mutation_are_revalidated(tmp_path) -> None:
    path = tmp_path / "acceptance.json"
    path.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")
    raw = path.read_bytes()
    expected_sha = hashlib.sha256(raw).hexdigest()

    fresh = revalidate_real_loop_acceptance_file(
        "acceptance.json",
        expected_bytes=len(raw),
        expected_sha256=expected_sha,
        workspace_root=tmp_path,
    )
    assert fresh.status == "fresh"
    assert fresh.file_checked is True
    assert fresh.file_fresh is True

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    mutated = revalidate_real_loop_acceptance_file(
        "acceptance.json",
        expected_bytes=len(raw),
        expected_sha256=expected_sha,
        workspace_root=tmp_path,
    )
    codes = {item.code for item in mutated.issues}
    assert mutated.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.FILE_BYTES_MISMATCH in codes
    assert RealLoopAcceptanceRevalidationIssueCode.FILE_SHA256_MISMATCH in codes


def test_unsafe_path_and_missing_file_fail_closed(tmp_path) -> None:
    unsafe = revalidate_real_loop_acceptance_file(
        "../acceptance.json",
        expected_bytes=0,
        expected_sha256="0" * 64,
        workspace_root=tmp_path,
    )
    assert unsafe.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.FILE_PATH_UNSAFE in {
        item.code for item in unsafe.issues
    }

    missing = revalidate_real_loop_acceptance_file(
        "acceptance.json",
        expected_bytes=0,
        expected_sha256="0" * 64,
        workspace_root=tmp_path,
    )
    assert missing.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.FILE_MISSING in {
        item.code for item in missing.issues
    }


def test_missing_matrix_field_does_not_synthesize_defaults() -> None:
    payload = _payload()
    del payload["prompt_manifest"]

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID in {
        item.code for item in result.issues
    }


def test_missing_evidence_chain_field_does_not_synthesize_identity() -> None:
    payload = _payload()
    del payload["generalization_evidence_sha256"]

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID in {
        item.code for item in result.issues
    }


def test_missing_semantics_binding_field_does_not_synthesize_identity() -> None:
    payload = _payload()
    del payload["semantics_binding_sha256"]

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID in {
        item.code for item in result.issues
    }


def test_semantics_binding_mutation_invalidates_persisted_report() -> None:
    payload = _payload()
    payload["semantics_binding_sha256"] = hashlib.sha256(
        b"different-semantics-binding"
    ).hexdigest()

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.REPORT_DERIVED_MISMATCH in {
        item.code for item in result.issues
    }


def test_evidence_chain_mutation_invalidates_persisted_report() -> None:
    payload = _payload()
    payload["execution_report_sha256"] = hashlib.sha256(b"different-chain").hexdigest()

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.REPORT_DERIVED_MISMATCH in {
        item.code for item in result.issues
    }


def test_acceptance_matrix_drift_is_blocked_even_when_its_local_report_is_clean() -> (
    None
):
    payload = _payload()
    payload["expected_testers"] = list(payload["expected_testers"])[1:]  # type: ignore[arg-type]

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.MATRIX_FIELD_INVALID in {
        item.code for item in result.issues
    }


def test_prompt_hashes_are_not_replaced_by_route_or_login_metadata() -> None:
    payload = _payload()
    prompt = dict(payload["prompt_manifest"][0])  # type: ignore[index]
    prompt["prompt_sha256"] = hashlib.sha256(b"different").hexdigest()
    payload["prompt_manifest"][0] = prompt  # type: ignore[index]

    result = revalidate_real_loop_acceptance_payload(payload)

    assert result.status == "blocked"
    assert RealLoopAcceptanceRevalidationIssueCode.REPORT_DERIVED_MISMATCH in {
        item.code for item in result.issues
    }
