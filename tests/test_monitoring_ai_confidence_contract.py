from types import SimpleNamespace

from services.api.app.monitoring_ai_contracts import (
    MONITORING_AI_LOW_CONFIDENCE_THRESHOLD,
    candidate_confidence_summary,
)


def _candidate(*claims):
    return SimpleNamespace(
        claims=tuple(SimpleNamespace(confidence=value) for value in claims),
    )


def test_confidence_summary_is_visible_and_never_automation_authorized():
    summary = candidate_confidence_summary(_candidate(0.92, 0.81))

    assert summary["status"] == "review_required"
    assert summary["confidence_floor"] == 0.81
    assert summary["threshold"] == MONITORING_AI_LOW_CONFIDENCE_THRESHOLD
    assert summary["requires_user_review"] is True
    assert summary["requires_additional_evidence"] is False
    assert summary["automation_permitted"] is False


def test_low_or_malformed_confidence_requires_evidence_or_explanation():
    low = candidate_confidence_summary(_candidate(0.69, 0.95))
    malformed = candidate_confidence_summary(_candidate("unknown"))

    assert low["status"] == "low"
    assert low["requires_additional_evidence"] is True
    assert low["automation_permitted"] is False
    assert malformed["status"] == "low"
    assert malformed["confidence_floor"] is None
    assert malformed["requires_user_review"] is True
    assert malformed["automation_permitted"] is False


def test_missing_claims_are_not_treated_as_high_confidence():
    summary = candidate_confidence_summary(SimpleNamespace(claims=()))

    assert summary["status"] == "not_scored"
    assert summary["confidence_floor"] is None
    assert summary["requires_user_review"] is True
    assert summary["automation_permitted"] is False
