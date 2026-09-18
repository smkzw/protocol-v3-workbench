"""Runtime uses current authored contracts, not historical assembled runs."""
from pathlib import Path

from app.protocol_workflow.registries.template_runtime import load_current_template


def test_current_template_loads_source_bound_fact_and_condition_catalogs():
    root = Path(__file__).resolve().parents[2] / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
    runtime = load_current_template(root)
    assert len(runtime.registry.chapters) == 111
    assert len(runtime.fact_catalog.bindings) == 743
    assert len(runtime.rules_catalog.rules) == 70
    actual = {entry.contract.semantic_node_id: entry.contract.material_sha256() for entry in runtime.registry.chapters}
    assert len(actual) == len(list((root / "chapter_contracts").glob("*.json")))
    assert runtime.registry.template_sha256 == "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
