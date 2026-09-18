"""Source inventory checks; these never start Microsoft Word."""
from pathlib import Path
import json

from scripts.qc.protocol_v3.extract_word_source_objects import reference_target, map_objects, build_inventory


def test_external_docx_fragment_is_not_an_internal_missing_bookmark():
    assert reference_target('HYPERLINK "file:///C:/source.docx" \\l "missing"') == ('external_document_anchor', 'missing')
    assert reference_target('HYPERLINK \\l "local"') == ('internal', 'local')
    assert reference_target('PAGEREF local \\h') == ('internal', 'local')
    assert reference_target('REF "local" \\h') == ('internal', 'local')
    assert reference_target('HYPERLINK "https://example.com"') == ('external', None)


def test_missing_reference_is_retained_and_reported_next_to_good_reference():
    inspection = {'bookmarks': [{'part': 'word/document.xml', 'bookmark_id': '1', 'name': 'kept', 'target_sha256': 'a'*64}],
                  'fields': [{'part': 'word/document.xml', 'instruction': 'REF '+name, 'result': text}
                             for name, text in [('kept', '正常'), ('lost', '错误！未找到引用源。')]]}
    result = map_objects(inspection, {('word/document.xml', '1'): 'n1'}, [], set())
    assert len(result['fields']) == 2
    assert result['fields'][0]['target_node_ids'] == ['n1']
    assert result['fields'][1]['resolution'] == 'missing'
    assert result['findings'] == [{'code': 'source_reference_missing', 'location': 'word/document.xml#field:1'}]


def test_inventory_does_not_cap_objects_at_32():
    source = {'bookmarks': [], 'fields': [{'part': 'word/document.xml', 'instruction': f'REF lost{i}', 'result': ''} for i in range(40)]}
    result = map_objects(source, {}, [], set())
    assert len(result['fields']) == len(result['findings']) == 40


def test_duplicate_names_are_ambiguous_instead_of_first_match_success():
    source = {'bookmarks': [{'part': part, 'bookmark_id': '1', 'name': 'same', 'target_sha256': 'a'*64}
                            for part in ('word/document.xml', 'word/header1.xml')],
              'fields': [{'part': 'word/document.xml', 'instruction': 'REF same', 'result': 'display'}]}
    assert map_objects(source, {}, [], set())['fields'][0]['resolution'] == 'ambiguous'


def test_missing_style_and_bookmark_requirements_are_not_filtered():
    contract = {'semantic_node_id': 'n1', 'word_rules': {'required_styles': ['needed'], 'required_bookmarks': ['lost'], 'required_cross_references': []}}
    result = map_objects({'bookmarks': [], 'fields': []}, {}, [contract], set())
    assert {f['code'] for f in result['findings']} == {'required_style_missing', 'required_bookmark_missing'}


def test_current_template_source_inventory_is_complete_and_deterministic():
    root = Path(__file__).resolve().parents[2]
    template_root = root / 'config/medical_writing/protocol_v3/templates/tp_ma_07_v2'
    source = Path('/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx')
    result = build_inventory(source, template_root)
    assert result['counts'] == {'bookmarks': 316, 'fields': 290, 'contracts': 111}
    assert len(result['table_sources']) == 17
    assert result['findings'] == []
    assert sum(f['kind'] == 'external_document_anchor' for f in result['fields']) == 1
    assert result['source_xml_observations'][0]['end_count'] - result['source_xml_observations'][0]['start_count'] == 7
    assert result['native_word_invoked'] is False
    assert result == build_inventory(source, template_root)
    stored = root / 'config/medical_writing/protocol_v3/qc/word_source_objects.json'
    assert json.loads(stored.read_text()) == result
