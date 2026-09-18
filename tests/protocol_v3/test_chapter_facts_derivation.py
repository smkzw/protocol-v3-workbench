"""Chapter-facts derivation stage: gaps, batch material and output parsing."""
import json

from app.protocol_workflow.agent3.chapter_facts import (
    CHAPTER_FACTS_INSTRUCTION, collect_chapter_gaps, build_batch_material,
    parse_batch_output, _binding_index)
from app.protocol_workflow.canonical.study_definition import CanonicalState
from app.protocol_workflow.registries.template_runtime import (
    default_template_root, load_current_template)


def _study_stub(facts):
    class _Study:
        project_id = 'project:test'
        study_definition_id = 'study:v3:test'
        canonical_state = CanonicalState.CONFIRMED
        updated_at = '2026-09-19T00:00:00Z'
    s = _Study()
    s.facts = dict(facts)
    return s


def _template():
    return load_current_template(default_template_root())


def test_collect_gaps_finds_missing_required_facts():
    template = _template()
    study = _study_stub({'research.input_context': {'source_intake_sha256': 'a'}})
    gaps = collect_chapter_gaps(template, study)
    assert gaps, 'an empty design must leave derivable gaps'
    total = sum(len(g['paths']) for g in gaps.values())
    assert total >= 300


def test_batch_material_compiles_confirmed_facts_and_specs():
    template = _template()
    study = _study_stub({'research.input_context': {}})
    gaps = collect_chapter_gaps(template, study)
    index = _binding_index(template.fact_catalog.bindings)
    node = sorted(gaps)[0]
    material = build_batch_material(CHAPTER_FACTS_INSTRUCTION, {}, gaps, index, [node])
    text = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    payload = json.loads(text)
    assert payload['schema'] == 'chapter_facts_request.v1'
    first = gaps[node]['paths'][0]
    assert first in payload['chapters'][node]['facts']
    assert 'value_type' in payload['chapters'][node]['facts'][first]


def test_parse_batch_output_accepts_typed_values_and_rejects_nulls():
    template = _template()
    study = _study_stub({'research.input_context': {}})
    gaps = collect_chapter_gaps(template, study)
    index = _binding_index(template.fact_catalog.bindings)
    node = sorted(gaps)[0]
    first = gaps[node]['paths'][0]
    binding = index[first]
    if binding.value_type == 'json':
        value = {m: ('是' if t == 'boolean' else '示例')
                 for m, t in (binding.required_members or {}).items()} or {'summary': '示例'}
    else:
        value = {'boolean': True, 'string': '示例'}.get(binding.value_type, '示例')
    updates, problems = parse_batch_output(
        json.dumps({'chapters': {node: {first: value}}}, ensure_ascii=False),
        gaps, index, [node])
    assert updates.get(binding.canonical_path) is not None
    # Sibling facts of the same chapter may stay omitted in this probe.
    assert not [p for p in problems if not p.endswith(':omitted')]
    bad_updates, bad_problems = parse_batch_output(
        json.dumps({'chapters': {node: {first: None}}}), gaps, index, [node])
    assert not bad_updates and bad_problems
