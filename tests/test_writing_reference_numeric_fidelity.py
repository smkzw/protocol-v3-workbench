"""Numeric fidelity regressions migrated from the 0926V1 review kit probes
(runs/requirements_v2_20260919/t17_round18_review_kit_0926v1/.../probes/).

History: migrated verbatim during G0 (2026-09-26) and run red BEFORE the G1
fix (7 failed / 5 passed) to fix the failing side first. A101-A104/A106 are
the counterexamples; the 1.16亿/6350亿 pairs are the A105 controls. A107
cases (test_numeric_fidelity_a107_strict_semantics) were added after probing
current behavior case-by-case: percent/sign/threshold/unit-change were
already blocked (kept as guards), the range-endpoint case was silently
forgiven by the old zero-padding relaxation (red before the G1 fix).
A passing numeric assertion does not assert the other fidelity gates or
medical approval.
"""
import pytest

from services.api.app.writing_reference import evaluate_translation_fidelity


@pytest.mark.parametrize(
    "source, target, should_flag",
    [
        ("Dose 5 mg.", "剂量50 mg。", True),
        ("Dose 1.5 mg.", "剂量15 mg。", True),
        ("Dose 15 mg.", "剂量1.5 mg。", True),
        ("Enroll 120 participants.", "入组1200例受试者。", True),
        ("Evaluate at week 12.", "在第120周评估。", True),
        ("116 million people.", "1.16万人。", True),
        ("2 visits and 2 calls.", "2次访视和电话随访。", True),
        ("116 million people.", "1.16亿人。", False),
        ("$635 billion.", "6350亿美元。", False),
        ("116 million people.", "2.50亿人。", True),
        ("Dose 5 mg.", "剂量7 mg。", True),
        ("Dose 5 mg.", "剂量5 mg。", False),
    ],
)
def test_numeric_fidelity_does_not_forgive_unlicensed_scaling(source, target, should_flag):
    result = evaluate_translation_fidelity(source, target)
    assert ("numeric_tokens_changed" in result.failure_codes) is should_flag


# A107: percentages, sign, thresholds, unit changes, range endpoints, and
# exact magnitude conversions must never pass silently when equivalence
# cannot be proven. Expectations were fixed by probing the PRE-FIX checker
# (evidence: g1 step-2 targeted run), not by guessing.
@pytest.mark.parametrize(
    "source, target, expect_blocked",
    [
        # already strictly blocked pre-fix (guards: must stay blocked)
        ("Response rate was 5%.", "应答率为50%。", True),
        ("Dose was -5 mg.", "剂量为5 mg。", True),
        ("Threshold: at least 50 patients.", "阈值：至少5例患者。", True),
        ("Dose is 5 mg.", "剂量为5 g。", True),
        # red pre-fix: 5-10 -> 50-100 slipped through the zero-padding
        # forgiveness; the tightened checker must block it
        ("Range 5-10 mg.", "范围50-100 mg。", True),
        # positive control: exact magnitude conversion stays green
        ("1.2 million people.", "120万人。", False),
    ],
)
def test_numeric_fidelity_a107_strict_semantics(source, target, expect_blocked):
    result = evaluate_translation_fidelity(source, target)
    assert (not result.passed) is expect_blocked
