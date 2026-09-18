"""Read-only diagnostic; writes only this run directory, no product invocation."""
import dataclasses
import hashlib
import importlib.util
import json
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TEMPLATE = ROOT / 'config/medical_writing/protocol_v3/templates/tp_ma_07_v2'
def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str)+'\n')
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registries
from scripts.qc.protocol_v3.extract_tp_ma_07_v2_registry import extract_docx_structure, build_node_tree, SOURCE_DOCX_PATH
from app.protocol_workflow.registries.chapters import load_chapter_registry, lint_registry
from app.protocol_workflow.registries.dependency_graph import build_dependency_graph

payload = assemble_registries(TEMPLATE/'chapter_contracts', TEMPLATE/'chapter_skills',
    [ROOT/f'tests/fixtures/protocol_v3/chapter_content_v2/batch{i}.json' for i in range(1,9)])
write('current_assembled_registry.json', payload)
old = json.loads((ROOT/'runs/mw_protocol_v3_3r3_batch8_fresh_20260911/final_all8_assembled.json').read_text())
registry = load_chapter_registry(payload)
lint = lint_registry(TEMPLATE, registry)
write('current_registry_lint.json', lint.model_dump(mode='json'))
structure = extract_docx_structure(SOURCE_DOCX_PATH)
rebuilt = build_node_tree(structure)
stored = json.loads((TEMPLATE/'node_tree.json').read_text())
write('source_reextraction.json', rebuilt)

h = module('graph_test_helpers', 'tests/protocol_v3/test_dependency_graph.py')
bridge = h._registry([
    h._chapter('node_a', facts=(('x','required'),)),
    h._chapter('node_b', facts=(('x','required'), ('y','required'))),
    h._chapter('node_c', facts=(('y','required'),)),
])
g = build_dependency_graph(bridge)
impact = g.impact(['x'])
bad = h._registry([
    h._chapter('node_a', facts=(('x','required'),)),
    h._chapter('node_b', facts=(('y','required'),), deps=(h._contract_id('node_a'), h._contract_id('missing')),
        repair_policy=h._policy('node_b',(h._contract_id('node_a'),))),
])
badg = build_dependency_graph(bad)
realg = build_dependency_graph(registry)
nodes = {n['id']:n for n in stored['outlined_tree']['nodes']}
inventory=[]
for e in registry.chapters:
    c=e.contract
    inventory.append({'node_id':e.node_id,'title':nodes.get(e.node_id,{}).get('title','封面'),
      'coverage_role':e.coverage_role, 'facts':[f.model_dump(mode='json') for f in c.substantive_content.fact_requirements],
      'claims':[x.model_dump(mode='json') for x in c.substantive_content.claim_requirements],
      'sources':[x.model_dump(mode='json') for x in c.substantive_content.evidence_source_requirements],
      'objects':[x.model_dump(mode='json') for x in c.substantive_content.structural_object_obligations],
      'conditions':[x.model_dump(mode='json') for x in c.conditional_applicability_rules],
      'qc':[x.model_dump(mode='json') for x in c.positive_qc_rules],
      'word':c.word_rules.model_dump(mode='json'),
      'prompt':e.skills[0].prompt_contract.instructions,
      'source_node':nodes.get(e.node_id,{})})
write('chapter_semantic_inventory.json',inventory)
style_names={v['name'] for v in structure['styles'].values()}
style_requests=Counter(x for e in registry.chapters for x in e.contract.word_rules.required_styles)
summary={
 'fresh_assembly_equals_previous_artifact':payload==old,
 'assembly_different_top_level_keys':[k for k in set(payload)|set(old) if payload.get(k)!=old.get(k)],
 'source_docx_sha256':hashlib.sha256(SOURCE_DOCX_PATH.read_bytes()).hexdigest(),
 'fresh_extraction_equals_stored':rebuilt==stored,
 'extraction_different_top_level_keys':[k for k in set(rebuilt)|set(stored) if rebuilt.get(k)!=stored.get(k)],
 'coverage':lint.coverage.model_dump(mode='json'),'lint_status':lint.status,
 'lint_errors':len(lint.errors()),'fixtures':len(registry.fixtures),
 'all_fixtures_defer_medical_judgment':all('medical_and_qc_judgment_not_executed' in r.deferred_qc_obligations for r in lint.fixture_results),
 'condition_count':sum(len(e.contract.conditional_applicability_rules) for e in registry.chapters),
 'condition_texts':[{'node':e.node_id,'id':r.conditional_applicability_rule_id,'condition':r.condition} for e in registry.chapters for r in e.contract.conditional_applicability_rules],
 'fact_path_count':len(registry.fact_vocabulary),
 'graph_counts':{'nodes':len(realg.nodes),'scheduling':len(realg.scheduling_edges),'consistency':len(realg.consistency_edges)},
 'bridge_expected_affected':[h._contract_id('node_a'),h._contract_id('node_b')],
 'bridge_actual':dataclasses.asdict(impact),
 'bridge_false_positive_c':h._contract_id('node_c') in impact.affected_contract_ids,
 'invalid_graph_findings':[dataclasses.asdict(f) for f in badg.findings],
 'invalid_graph_impact_returns':dataclasses.asdict(badg.impact(['y'])),
 'hash_scope':'Only registry and changed fact paths; function accepts no study/project/value/revision. This is a projection hash, not an adoption receipt.',
 'required_style_names':dict(style_requests),
 'required_styles_absent_exact_name':sorted(set(style_requests)-style_names),
 'style_names':sorted(style_names),
}
write('source_and_graph_summary.json',summary)
print(json.dumps({k:v for k,v in summary.items() if k not in {'condition_texts','style_names','invalid_graph_impact_returns'}},ensure_ascii=False,indent=2))
