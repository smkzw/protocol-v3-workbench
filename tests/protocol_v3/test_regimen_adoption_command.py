"""A human adoption uses the persisted design, never a browser-supplied regimen."""
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from test_clinical_design_worker import prepared_reference
from app.protocol_workflow.agent2.clinical_worker import read_regimen_response

def test_adoption_command_binds_saved_output_and_keeps_replay_material_identical():
    from app.protocol_workflow.agent2.study_definition import prepare_regimen_adoption
    prepared, output = prepared_reference()
    proposal = read_regimen_response(prepared, output)
    state = {"status": "ready_for_review", "validation": {"valid": True, "proposal": proposal,
             "raw_response": {"output_sha256": "b" * 64}}}
    reads = []
    def read(run):
        reads.append(run)
        return state
    coordinator = SimpleNamespace(project_id="project:one", read=read, prepared_request=lambda run: prepared)
    intent = dict(study_definition_id="study:one", operation_id="operation:one", expected_revision=1,
        snapshot_sha256="a" * 64, actor_id="user:one", decided_at=datetime(2026,9,13,tzinfo=timezone.utc), reason="采用完整方案")
    first = prepare_regimen_adoption(coordinator,"regimen:one",**intent)
    again = prepare_regimen_adoption(coordinator,"regimen:one",**intent)
    assert first == again
    assert reads == ["regimen:one", "regimen:one"]
    assert len(first.fact_updates["intervention.dose_regimen"]["schedules"]) == 4
    assert first.decision_record.actor_type.value == "user"
    assert first.decision_record.snapshot_sha256 == intent["snapshot_sha256"]
    assert first.template_adoption.template_id == "tp_ma_07_v2"
    assert {ref.fact_path for ref in first.decision_input_refs} == {"intervention.dose_regimen", "research.input_context", "research.regimen_producer"}
    assert first.fact_updates["research.regimen_producer"]["output_sha256"] == "b" * 64
    assert first.fact_updates["research.regimen_producer"]["input_sha256"] == prepared.input_sha256
    assert "research.input_context" not in first.fact_updates  # Adoption cannot silently replace selected materials.
    state["validation"]["raw_response"]["output_sha256"] = "c" * 64
    changed = prepare_regimen_adoption(coordinator,"regimen:one",**intent)
    assert changed.decision_record.selected_option_id != first.decision_record.selected_option_id
    assert changed.idempotency_key == first.idempotency_key

@pytest.mark.parametrize("status,valid", [("blocked",False),("needs_information",True),("needs_structure_correction",False)])
def test_unresolved_saved_design_cannot_form_an_adoption(status, valid):
    from app.protocol_workflow.agent2.study_definition import prepare_regimen_adoption
    coordinator=SimpleNamespace(project_id="project:one",read=lambda run: {"status":status,"validation":{"valid":valid}})
    with pytest.raises(ValueError,match="regimen_information_unresolved"):
        prepare_regimen_adoption(coordinator,"regimen:one",study_definition_id="study:one",operation_id="operation:one",
            expected_revision=1,snapshot_sha256="a"*64,actor_id="user:one",decided_at=datetime.now(timezone.utc),reason="确认")
