import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'config/medical_writing/protocol_v3/templates/tp_ma_07_v2'
BATCH = ROOT / 'tests/fixtures/protocol_v3/chapter_content_v2/batch1.json'
spec = importlib.util.spec_from_file_location('batch_assembly', ROOT / 'scripts/qc/protocol_v3/assemble_chapter_registry.py')
assembly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assembly)


def test_unrelated_later_batch_does_not_break_first_batch(tmp_path):
    contracts = tmp_path / 'contracts'
    skills = tmp_path / 'skills'
    shutil.copytree(TEMPLATE / 'chapter_contracts', contracts)
    shutil.copytree(TEMPLATE / 'chapter_skills', skills)
    # An unfinished later batch is outside the selected batch's ownership.
    (contracts / 'v2_n_2_1.json').write_text('{}')
    (skills / 'v2_n_2_1.json').write_text('{}')
    result = assembly.assemble_registry(contracts, skills, BATCH)
    assert len(result['chapters']) == 12
    assert 'v2_n_2_1' not in {x['node_id'] for x in result['chapters']}


def test_declared_missing_carrier_cannot_be_silently_omitted(tmp_path):
    contracts = tmp_path / 'contracts'
    skills = tmp_path / 'skills'
    shutil.copytree(TEMPLATE / 'chapter_contracts', contracts)
    shutil.copytree(TEMPLATE / 'chapter_skills', skills)
    # Make the missing input explicit even after the next batch is authored.
    (contracts / 'v2_n_2_1.json').unlink(missing_ok=True)
    (skills / 'v2_n_2_1.json').unlink(missing_ok=True)
    batch = json.loads(BATCH.read_text())
    batch['coverage_roles']['v2_n_2_1'] = 'heading_leaf'
    path = tmp_path / 'batch.json'
    path.write_text(json.dumps(batch))
    with pytest.raises(assembly.AssemblyInputError):
        assembly.assemble_registry(contracts, skills, path)


def test_invalid_selected_contract_has_cli_input_error(tmp_path, capsys):
    contracts = tmp_path / 'contracts'
    shutil.copytree(TEMPLATE / 'chapter_contracts', contracts)
    (contracts / 'v2_front_block.json').write_text('{}')
    result = assembly.main(['--contracts-dir', str(contracts), '--skills-dir',
                            str(TEMPLATE / 'chapter_skills'), '--batch', str(BATCH)])
    assert result == 2
    assert 'assembly failed' in capsys.readouterr().err
