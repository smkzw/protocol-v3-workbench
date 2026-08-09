from __future__ import annotations

import pytest

from services.api.app.monitoring_source_revision_compatibility import (
    MonitoringSourceRevisionCase,
    MonitoringSourceRevisionCompatibilityError,
    MonitoringSourceRevisionComparison,
    MonitoringSourceRevisionIdentity,
    SourceRevisionRelation,
    build_monitoring_source_revision_revalidation_report,
    compare_monitoring_source_revisions,
    parse_monitoring_source_revision,
)


MY009_LEGACY = "monitoring:MY009-UC-LAB-CS-REVIEW-001:2ef9c8d72d74"
MY009_EXPECTED = "monitoring:MY009-UC-LAB-CS-REVIEW-001:19691633b408:2ef9c8d72d74"
RUX_EXACT = "rux-p0:RUX-LAB-ANC-LT1_5-INTERRUPT:eae6da7ebac3:0ebcf78d0506"


def _case(
    record_id: str = "record-1",
    *,
    legacy: str = MY009_LEGACY,
    expected: str = MY009_EXPECTED,
    candidates: tuple[str, ...] = ("monsrcv_a", "monsrcv_b"),
) -> MonitoringSourceRevisionCase:
    return MonitoringSourceRevisionCase(
        record_id=record_id,
        project_id="proj_my009_uc",
        legacy_source_revision=legacy,
        expected_source_revision=expected,
        candidate_source_revision_ids=candidates,
    )


def test_parser_preserves_legacy_missing_source_token_and_exact_rux_identity() -> None:
    legacy = parse_monitoring_source_revision(MY009_LEGACY)
    exact = parse_monitoring_source_revision(RUX_EXACT)

    assert legacy.family == "monitoring"
    assert legacy.rule_id == "MY009-UC-LAB-CS-REVIEW-001"
    assert legacy.source_token == ""
    assert legacy.meaning_token == "2ef9c8d72d74"
    assert exact.family == "rux-p0"
    assert exact.has_source_token is True


def test_malformed_revision_fails_closed() -> None:
    with pytest.raises(MonitoringSourceRevisionCompatibilityError, match="must use"):
        parse_monitoring_source_revision("monitoring:rule-only")


@pytest.mark.parametrize("value", (True, 123, ""))
def test_revision_text_and_identity_fields_require_strings(value: object) -> None:
    with pytest.raises(MonitoringSourceRevisionCompatibilityError, match="string|required"):
        parse_monitoring_source_revision(value)  # type: ignore[arg-type]


def test_candidate_source_revision_ids_require_string_array_shape() -> None:
    with pytest.raises(MonitoringSourceRevisionCompatibilityError, match="string array"):
        _case(candidates="candidate-1")  # type: ignore[arg-type]
    with pytest.raises(MonitoringSourceRevisionCompatibilityError, match="non-empty strings"):
        _case(candidates=("candidate-1", 2))  # type: ignore[arg-type]


def test_public_dataclass_constructors_keep_strict_identity_boundaries() -> None:
    with pytest.raises(MonitoringSourceRevisionCompatibilityError, match="source_token"):
        MonitoringSourceRevisionIdentity(
            raw=MY009_LEGACY,
            family="monitoring",
            rule_id="MY009-UC-LAB-CS-REVIEW-001",
            source_token=True,  # type: ignore[arg-type]
            meaning_token="2ef9c8d72d74",
        )

    with pytest.raises(MonitoringSourceRevisionCompatibilityError, match="reason"):
        MonitoringSourceRevisionComparison(
            record_id="record-1",
            project_id="proj_my009_uc",
            relation=SourceRevisionRelation.EXACT,
            legacy_source_revision=MY009_EXPECTED,
            expected_source_revision=MY009_EXPECTED,
            candidate_source_revision_ids=(),
            reason=True,  # type: ignore[arg-type]
        )


def test_legacy_missing_source_token_requires_explicit_revalidation() -> None:
    comparison = compare_monitoring_source_revisions(_case())

    assert comparison.relation is SourceRevisionRelation.LEGACY_SOURCE_TOKEN_MISSING
    assert "source-content revalidation" in comparison.reason
    assert comparison.candidate_source_revision_ids == ("monsrcv_a", "monsrcv_b")


def test_exact_identity_is_not_migration_authority() -> None:
    comparison = compare_monitoring_source_revisions(
        _case(
            record_id="rux-1",
            legacy=RUX_EXACT,
            expected=RUX_EXACT,
            candidates=("monsrcv_rux",),
        )
    )

    assert comparison.relation is SourceRevisionRelation.EXACT
    report = build_monitoring_source_revision_revalidation_report(
        (_case(record_id="rux-1", legacy=RUX_EXACT, expected=RUX_EXACT, candidates=()),)
    )
    assert report.source_revalidation_complete is True
    assert report.migration_ready is False


@pytest.mark.parametrize(
    "legacy, expected, message",
    [
        ("monitoring:other-rule:2ef9c8d72d74", MY009_EXPECTED, "family or rule"),
        (
            "monitoring:MY009-UC-LAB-CS-REVIEW-001:other-meaning",
            MY009_EXPECTED,
            "meaning token",
        ),
        (
            "monitoring:MY009-UC-LAB-CS-REVIEW-001:other-source:2ef9c8d72d74",
            MY009_EXPECTED,
            "source token",
        ),
    ],
)
def test_token_mismatch_is_never_repaired_by_inference(
    legacy: str, expected: str, message: str
) -> None:
    comparison = compare_monitoring_source_revisions(
        _case(legacy=legacy, expected=expected)
    )

    assert comparison.relation is SourceRevisionRelation.TOKEN_MISMATCH
    assert message in comparison.reason


def test_b4_shape_report_separates_three_legacy_gaps_from_two_exact_rows() -> None:
    cases = (
        _case(record_id="my009-1"),
        _case(record_id="my009-2"),
        _case(record_id="my009-3"),
        _case(record_id="rux-1", legacy=RUX_EXACT, expected=RUX_EXACT, candidates=()),
        _case(record_id="rux-2", legacy=RUX_EXACT, expected=RUX_EXACT, candidates=()),
    )
    report = build_monitoring_source_revision_revalidation_report(cases)

    assert report.exact_count == 2
    assert report.revalidation_required_count == 3
    assert report.source_revalidation_complete is False
    assert report.migration_ready is False
    assert len(report.to_dict()["comparisons"]) == 5
    assert len(report.report_sha256) == 64


def test_report_is_deterministic_and_rejects_duplicate_cases() -> None:
    case = _case()
    first = build_monitoring_source_revision_revalidation_report((case,))
    second = build_monitoring_source_revision_revalidation_report((case,))
    assert first.to_dict() == second.to_dict()

    with pytest.raises(
        MonitoringSourceRevisionCompatibilityError, match="must not repeat"
    ):
        build_monitoring_source_revision_revalidation_report((case, case))


def test_invalid_case_type_is_rejected() -> None:
    with pytest.raises(MonitoringSourceRevisionCompatibilityError, match="Case"):
        build_monitoring_source_revision_revalidation_report(({"record_id": "x"},))
