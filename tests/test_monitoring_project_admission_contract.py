from dataclasses import replace

import pytest

from services.api.app.monitoring_project_admission_contract import (
    ProjectAdmissionBatch,
    ProjectAdmissionContractError,
    ProjectAdmissionInput,
    ProjectAdmissionIssueCode,
    ProjectAdmissionPrompt,
    assess_project_admission,
)


PROJECT_ID = "proj_rux_03_002"
EXPECTED_PROJECTS = (PROJECT_ID, "proj_mgk10_sar_real", "proj_my009_uc")
GATES = {
    "b6_approved": True,
    "approved_input_ready": True,
    "source_token_revalidated": True,
    "aggregate_cas_complete": True,
    "runtime_identity_verified": True,
}


def _batch(ref: str, digest: str, snapshot_date: str) -> ProjectAdmissionBatch:
    return ProjectAdmissionBatch(
        batch_ref=ref,
        snapshot_date=snapshot_date,
        listing_sha256=digest,
        listing_class="raw_full_snapshot",
        source_status="confirmed",
        full_snapshot_proven=True,
    )


def _prompt(ref: str, digest: str) -> ProjectAdmissionPrompt:
    return ProjectAdmissionPrompt(prompt_ref=ref, prompt_sha256=digest)


def _admission(**overrides) -> ProjectAdmissionInput:
    value = ProjectAdmissionInput(
        project_id=PROJECT_ID,
        canonical_project_id=PROJECT_ID,
        expected_project_set=EXPECTED_PROJECTS,
        adapter_registered=True,
        adapter_project_id=PROJECT_ID,
        source_binding_present=True,
        monitoring_module_binding_present=True,
        source_content_revision="source-r17",
        parse_revision="parse-v4",
        batches=(
            _batch("batch-1", "a" * 64, "2026-01-01"),
            _batch("batch-2", "b" * 64, "2026-02-01"),
        ),
        prompts=(
            _prompt("prompt-rux-1", "1" * 64),
            _prompt("prompt-rux-2", "2" * 64),
        ),
        expected_prompt_refs=("prompt-rux-1", "prompt-rux-2"),
        upstream_gates=GATES,
    )
    return replace(value, **overrides)


def test_complete_project_admission_is_diagnostic_only() -> None:
    report = assess_project_admission(_admission())

    assert report.status == "diagnostic_admissible"
    assert report.admission_complete is True
    assert report.issues == ()
    assert report.diagnostic_only is True
    assert report.runtime_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.write_permitted is False
    assert report.medical_confirmation_permitted is False
    assert report.to_dict()["report_sha256"] == report.report_sha256


def test_candidate_and_non_monitoring_alias_fail_closed() -> None:
    report = assess_project_admission(
        _admission(candidate_only=True, non_monitoring_alias=True)
    )

    codes = {item.code for item in report.issues}
    assert report.status == "blocked"
    assert ProjectAdmissionIssueCode.CANDIDATE_NOT_ADMISSIBLE in codes
    assert ProjectAdmissionIssueCode.NON_MONITORING_ALIAS_FORBIDDEN in codes


def test_missing_adapter_source_batch_prompt_and_upstream_gate_are_visible() -> None:
    bad_batch = _batch("batch-only", "c" * 64, "2026-03-01")
    report = assess_project_admission(
        _admission(
            adapter_registered=False,
            adapter_project_id="proj_other",
            source_binding_present=False,
            monitoring_module_binding_present=False,
            source_content_revision="",
            parse_revision="",
            batches=(bad_batch,),
            prompts=(),
            expected_prompt_refs=("prompt-rux-1",),
            upstream_gates={**GATES, "b6_approved": False},
        )
    )

    codes = {item.code for item in report.issues}
    assert report.status == "blocked"
    assert {
        ProjectAdmissionIssueCode.ADAPTER_NOT_REGISTERED,
        ProjectAdmissionIssueCode.ADAPTER_IDENTITY_MISMATCH,
        ProjectAdmissionIssueCode.SOURCE_BINDING_MISSING,
        ProjectAdmissionIssueCode.SOURCE_REVISION_MISSING,
        ProjectAdmissionIssueCode.BATCH_COVERAGE_INSUFFICIENT,
        ProjectAdmissionIssueCode.PROMPT_COVERAGE_MISSING,
        ProjectAdmissionIssueCode.UPSTREAM_GATE_NOT_READY,
    }.issubset(codes)


def test_duplicate_batch_and_prompt_identity_is_blocked() -> None:
    duplicate_batch = _batch("batch-1", "a" * 64, "2026-02-01")
    duplicate_prompt = _prompt("prompt-rux-1", "1" * 64)
    report = assess_project_admission(
        _admission(
            batches=(_batch("batch-1", "a" * 64, "2026-01-01"), duplicate_batch),
            prompts=(_prompt("prompt-rux-1", "1" * 64), duplicate_prompt),
        )
    )

    assert report.status == "blocked"
    assert (
        sum(
            item.code == ProjectAdmissionIssueCode.BATCH_DUPLICATE
            for item in report.issues
        )
        == 1
    )
    assert (
        sum(
            item.code == ProjectAdmissionIssueCode.PROMPT_DUPLICATE
            for item in report.issues
        )
        == 1
    )


def test_boolean_coercion_and_invalid_batch_inputs_are_rejected() -> None:
    with pytest.raises(ProjectAdmissionContractError):
        _batch("batch-1", "a" * 64, "2026-02-30")

    with pytest.raises(ProjectAdmissionContractError):
        ProjectAdmissionBatch(
            batch_ref="batch-1",
            snapshot_date="2026-01-01",
            listing_sha256="a" * 64,
            listing_class="raw_full_snapshot",
            source_status="confirmed",
            full_snapshot_proven="true",
        )

    with pytest.raises(ProjectAdmissionContractError):
        _admission(upstream_gates={**GATES, "b6_approved": "true"})


def test_batch_and_prompt_hashes_require_exact_lowercase_bytes() -> None:
    with pytest.raises(ProjectAdmissionContractError, match="listing_sha256"):
        _batch("batch-upper", "A" * 64, "2026-04-01")

    with pytest.raises(ProjectAdmissionContractError, match="listing_sha256"):
        _batch("batch-padded", "a" * 64 + " ", "2026-04-01")

    with pytest.raises(ProjectAdmissionContractError, match="listing_sha256"):
        _batch("batch-non-string", 123, "2026-04-01")

    with pytest.raises(ProjectAdmissionContractError, match="prompt_sha256"):
        _prompt("prompt-upper", "B" * 64)

    with pytest.raises(ProjectAdmissionContractError, match="prompt_sha256"):
        _prompt("prompt-padded", "b" * 64 + "\n")

    with pytest.raises(ProjectAdmissionContractError, match="prompt_sha256"):
        _prompt("prompt-non-string", 456)


def test_report_rejects_non_boolean_completion_flag() -> None:
    report = assess_project_admission(_admission())
    with pytest.raises(ProjectAdmissionContractError, match="admission_complete"):
        replace(report, admission_complete="true")
