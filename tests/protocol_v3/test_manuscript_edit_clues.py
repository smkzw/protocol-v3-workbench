"""Reconciliation clue signals (B02/B03 / A18): tables, digits, negation.

Saving is never gated by these classes any more (R3); the tests pin the
explainable signals that decide whether the explicit reconciliation stage
must compare a snapshot against the confirmed design.
"""
import json

from app.protocol_workflow.application.manuscript_edits import (
    block_content_text, reclassify_edit)


def _table_block(cells, schema_key='text'):
    payload = {'schema_version': 'semantic-structured-table.v1', 'table': {
        'columns': [{'column_id': 'c1', 'order': 1}],
        'rows': [{'order': 1, 'cells': [
            {'column_id': 'c1', 'order': 1, schema_key: text} for text in cells]}],
    }}
    return {'block_kind': 'table', 'content': json.dumps(payload, ensure_ascii=False)}


FACTS = {'intervention.dose_regimen': '100mg'}


def test_cell_text_tables_feed_the_clue_signals():
    old = _table_block(['给药剂量为100mg'])
    new = _table_block(['给药剂量为150mg'])
    assert '100mg' in block_content_text(old), 'text-schema cells must be readable'
    ruling = reclassify_edit(old_text=block_content_text(old),
                             new_text=block_content_text(new),
                             confirmed_facts=FACTS, claimed_class='wording_only')
    assert ruling['edit_class'] == 'fact_or_uncertain'
    assert ruling['affected_fact_paths'] == ('intervention.dose_regimen',)


def test_legacy_cell_value_still_readable():
    block = _table_block(['剂量100mg'], schema_key='value')
    assert '100mg' in block_content_text(block)


def test_digit_boundary_catches_100_to_1000():
    ruling = reclassify_edit(old_text='给药剂量为100mg', new_text='给药剂量为1000mg',
                             confirmed_facts={'intervention.dose_regimen': 100},
                             claimed_class='wording_only')
    assert ruling['edit_class'] == 'fact_or_uncertain', '100 must not hide inside 1000'


def test_negation_flip_is_a_signal():
    ruling = reclassify_edit(old_text='本研究采用随机设计', new_text='本研究采用不随机设计',
                             confirmed_facts={'design.randomization': '随机'},
                             claimed_class='wording_only')
    assert ruling['edit_class'] == 'fact_or_uncertain'
    assert ruling['affected_fact_paths'] == ('design.randomization',)


def test_unknown_table_shape_falls_back_to_raw_payload():
    block = {'block_kind': 'table', 'content': json.dumps({'matrix': ['100mg']}, ensure_ascii=False)}
    assert '100mg' in block_content_text(block)


def test_pure_wording_stays_wording_with_semantic_note():
    ruling = reclassify_edit(old_text='给药剂量为100mg，每21天一个周期。',
                             new_text='给药剂量为100mg，每21天为一个治疗周期。',
                             confirmed_facts=FACTS, claimed_class='wording_only')
    assert ruling['edit_class'] == 'wording_only'
    assert ruling['affected_fact_paths'] == ()
