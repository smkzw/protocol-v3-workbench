import json
from pathlib import Path

from app.protocol_workflow.registries.chapters import check_fixture, load_chapter_registry
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registry

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'config/medical_writing/protocol_v3/templates/tp_ma_07_v2'
BATCH = ROOT / 'tests/fixtures/protocol_v3/chapter_content_v2/batch1.json'


def registry():
    return load_chapter_registry(assemble_registry(TEMPLATE / 'chapter_contracts', TEMPLATE / 'chapter_skills', BATCH))


def test_contact_without_external_service_party_is_valid():
    document = registry()
    fixture = next(f for f in document.fixtures if f.fixture_kind == 'positive' and f.chapter_contract_id == 'contract:v2-n-front-4:v2')
    content = fixture.model_dump(mode='json')
    content['content']['facts'] = [f for f in content['content']['facts'] if not f['fact_path'].startswith('contact.service_parties')]
    content['content']['facts'].append({'fact_path': 'contact.service_parties_applicable', 'value': 'false'})
    for obj in content['content']['objects']:
        if obj['object_kind'] == 'table':
            obj['occurrences'] = 2
            obj['cells'] = [c for c in obj['cells'] if ':service.' not in c['cell_id']]
    assert check_fixture(document, type(fixture).model_validate(content)).passed


def test_single_arm_diagram_does_not_require_randomization_ratio():
    document = registry()
    fixture = next(f for f in document.fixtures if f.fixture_kind == 'positive' and f.chapter_contract_id == 'contract:v2-n-1-2:v2')
    content = fixture.model_dump(mode='json')
    content['content']['facts'] = [f for f in content['content']['facts'] if f['fact_path'] != 'diagram.allocation_ratio']
    content['content']['facts'].append({'fact_path': 'diagram.randomized', 'value': 'false'})
    assert check_fixture(document, type(fixture).model_validate(content)).passed


def test_cover_and_summary_bind_existing_protocol_identity():
    document = registry()
    for node in ('v2_front_block', 'v2_n_1_1'):
        contract = next(e.contract for e in document.chapters if e.node_id == node)
        required = {f.fact_path for f in contract.substantive_content.fact_requirements if f.obligation.value == 'required'}
        assert 'framing.protocol_id' in required


def test_diagram_reference_identifies_real_supporting_asset():
    skill = json.loads((TEMPLATE / 'chapter_skills/v2_n_1_2.json').read_text())
    assert 'c08dc55324b92ed45e283335c1e28a7955993cd42f687c0ca1395c4730c0372c' in '\n'.join(skill['provenance_requirements'])


def test_summary_distinguishes_drug_registration_category_from_trial_registry():
    contract = json.loads((TEMPLATE / 'chapter_contracts/v2_n_1_1.json').read_text())
    for obligation in contract.get('registry_consistency_obligations', []):
        assert 'synopsis.registration_classification' not in obligation['eligibility_fact_paths']


def test_glossary_requires_entry_content_beyond_column_headers():
    document = registry()
    contract = next(e.contract for e in document.chapters if e.node_id == 'v2_n_front_5')
    cells = {c for o in contract.substantive_content.structural_object_obligations for c in o.required_object_cells}
    assert any(not c.startswith('glossary:header:') for c in cells)
