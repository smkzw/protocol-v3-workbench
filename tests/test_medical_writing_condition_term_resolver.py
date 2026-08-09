from services.api.app.medical_writing_condition_term_resolver import (
    resolve_clinicaltrials_condition_term,
)


def test_resolves_generalized_myasthenia_gravis_to_english() -> None:
    resolved, source = resolve_clinicaltrials_condition_term(
        indication="全身型重症肌无力",
    )

    assert resolved == "generalized myasthenia gravis"
    assert source == "zh_alias:indication"


def test_resolves_unqualified_myasthenia_gravis_to_english() -> None:
    resolved, source = resolve_clinicaltrials_condition_term(
        indication="重症肌无力",
    )

    assert resolved == "myasthenia gravis"
    assert source == "zh_alias:indication"


def test_preserves_explicit_english_condition_term() -> None:
    resolved, source = resolve_clinicaltrials_condition_term(
        indication="全身型重症肌无力",
        clinicaltrials_condition_term="Generalized Myasthenia Gravis",
    )

    assert resolved == "Generalized Myasthenia Gravis"
    assert source is None


def test_resolves_qualified_crohn_label_to_english() -> None:
    resolved, source = resolve_clinicaltrials_condition_term(
        indication="中重度活动性克罗恩病",
    )

    assert resolved == "Crohn's disease"
    assert source == "zh_alias:indication:contains"


def test_resolves_qualified_ulcerative_colitis_label_to_english() -> None:
    resolved, source = resolve_clinicaltrials_condition_term(
        indication="中重度活动性溃疡性结肠炎",
    )

    assert resolved == "ulcerative colitis"
    assert source == "zh_alias:indication:contains"
