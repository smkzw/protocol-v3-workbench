"""A compound regimen cannot silently lose a phase or arm on design handoff."""
from copy import deepcopy
import pytest
from app.protocol_workflow.agent2.recommendations import bind_candidate_coverage


def seed():
    return {"input_sha256": "a" * 64, "canonical": {}, "fields": {
        "anticipated_dose": [{"candidate": text, "canonical": None,
            "source_support": "reference_only", "references": [{"quote": text,
            "source_artifact_id": "source-reference", "locator": f"body/{i}"}]}
            for i, text in enumerate(["双盲试验组负荷及维持", "双盲安慰剂组", "继续治疗试验组", "继续治疗原安慰剂组"])],
        "populations": [{"candidate": "历史总样本量", "canonical": None,
                         "source_support": "reference_only", "references": []}]}}


def coverage():
    return [{"field": "anticipated_dose", "index": i, "destination": "dose_regimen",
             "relation": "component", "reason": "同一给药方案的不同组和时期"} for i in range(4)] + [
        {"field": "populations", "index": 0, "destination": "sample_size",
         "relation": "context", "reason": "历史依据，尚非本研究样本量"}]


def test_all_phase_arm_components_and_misplaced_context_survive_without_adoption():
    original = seed()
    result = bind_candidate_coverage(original, input_sha256="a" * 64, assignments=coverage())
    assert len(result) == 5
    assert [x["candidate"]["candidate"] for x in result[:4]] == [x["candidate"] for x in original["fields"]["anticipated_dose"]]
    assert result[-1]["destination"] == "sample_size"
    assert all(x["candidate"]["canonical"] is None for x in result)
    assert all(x["candidate"]["source_support"] == "reference_only" for x in result)
    result[0]["candidate"]["references"][0]["quote"] = "changed"
    assert original == seed()


def test_taking_only_first_dose_cannot_pass_as_complete_handoff():
    with pytest.raises(ValueError, match="design_candidate_coverage_incomplete"):
        bind_candidate_coverage(seed(), input_sha256="a" * 64, assignments=[coverage()[0], coverage()[-1]])


def test_repeated_candidate_cannot_hide_missing_continuation_arm():
    assignments = coverage()
    assignments[3] = deepcopy(assignments[0])
    with pytest.raises(ValueError, match="design_candidate_assignment_duplicate"):
        bind_candidate_coverage(seed(), input_sha256="a" * 64, assignments=assignments)


def test_other_intake_cannot_reuse_positional_candidate_bindings():
    with pytest.raises(ValueError, match="design_candidate_input_mismatch"):
        bind_candidate_coverage(seed(), input_sha256="b" * 64, assignments=coverage())
