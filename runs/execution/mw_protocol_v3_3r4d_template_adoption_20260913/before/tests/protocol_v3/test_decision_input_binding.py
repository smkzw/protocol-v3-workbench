"""Input identity must follow actual native values, not whole-study revisions."""
import pytest

from app.protocol_workflow.canonical.decision_inputs import (
    DecisionInputRef, bind_decision_inputs, current_input_validity,
)


def test_literal_key_and_explicit_member_leave_unread_siblings_alone():
    refs = (DecisionInputRef(fact_path="design.features", members=("interim",)),)
    binding = bind_decision_inputs(refs, {"design.features": {"interim": False, "blinding": True}}, "a" * 64)
    assert current_input_validity(binding, {"design.features": {"interim": False, "blinding": False}}) == "current"
    assert current_input_validity(binding, {"design": {"features": {"interim": False}}}) == "stale"
    assert current_input_validity(binding, {"design.features": {"interim": 0}}) == "stale"


@pytest.mark.parametrize("before,after", [({}, {"x": None}), ({"x": None}, {})])
def test_unknown_is_not_false_and_presence_is_preserved(before, after):
    refs = (DecisionInputRef(fact_path="x"),)
    binding = bind_decision_inputs(refs, before, "b" * 64)
    assert current_input_validity(binding, before) == "unverified"
    assert current_input_validity(binding, after) == "stale"


def test_empty_or_duplicate_input_declarations_do_not_assert_validity():
    ref = DecisionInputRef(fact_path="x")
    for refs in ((), (ref, ref)):
        with pytest.raises(ValueError):
            bind_decision_inputs(refs, {"x": False}, "c" * 64)
