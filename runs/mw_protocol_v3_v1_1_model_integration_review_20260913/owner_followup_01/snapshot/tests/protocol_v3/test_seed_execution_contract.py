"""Research intake uses its own registered skill with the current product model."""
from pathlib import Path
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import ArtifactRef, build_request
from test_zhipu_product_transport import _node_contract

ROOT = Path(__file__).resolve().parents[2] / 'config/medical_writing/protocol_v3'


def test_seed_contract_uses_registered_seed_skill_and_keeps_graph_work_identity():
    from app.protocol_workflow.agent1.seed_contract import seed_execution_contract
    role = next(r for r in load_role_registry(ROOT / 'role_registry.json').roles if r.role_kind == 'llm')
    skill = next(s for s in load_skill_registry(ROOT / 'skill_registry.json').skill_definitions()
                 if s.skill_definition_id == 'skill.research-seed-proposal')
    base = _node_contract()
    contract = seed_execution_contract(base, skill=skill, role_entry=role)
    assert contract.logical_call_id == base.logical_call_id
    assert contract.idempotency_key == base.idempotency_key
    assert contract.input_artifact_hashes == base.input_artifact_hashes
    request = build_request(node_contract=contract, skill=skill, role_entry=role,
                            artifacts=(ArtifactRef(ref='research-intake', sha256=base.input_artifact_hashes[0]),),
                            selected_region='cn')
    assert request.model == 'glm-5.3-flash'
    assert request.reasoning_effort == 'max'
    assert request.output_schema_ref.endswith('research-seed-proposal-output.v1.json')
