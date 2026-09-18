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
def test_document_order_uses_template_positions_instead_of_filename_sort():
    import json
    from app.protocol_workflow.registries.template_runtime import load_current_template
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    template=load_current_template(REAL_TEMPLATE_DIR)
    tree=json.loads((REAL_TEMPLATE_DIR/'node_tree.json').read_text())
    positions={n['id']:n['body_child_index'] for key in ('heading_style_tree','outlined_tree')
        for n in tree[key]['nodes']}
    positions['v2_front_block']=tree['front_block']['body_child_index_range'][0]
    expected=tuple(sorted((e.node_id for e in template.registry.chapters),key=positions.__getitem__))
    assert template.chapter_order==expected
    assert expected[0]=='v2_front_block'
    assert expected.index('v2_n_2_1') < expected.index('v2_n_10_1_1')
