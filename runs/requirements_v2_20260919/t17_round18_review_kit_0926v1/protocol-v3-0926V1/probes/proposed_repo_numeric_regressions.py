"""PROPOSED repository regressions; NOT RUN against the full repository here.

Copy/adapt into the repository test suite using its existing import convention.
These call the real function (unlike the isolated excerpt probes). A passing
numeric assertion does not assert the other fidelity gates or medical approval.
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
