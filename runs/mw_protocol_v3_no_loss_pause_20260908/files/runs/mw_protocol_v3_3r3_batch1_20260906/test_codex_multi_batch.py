import json
from pathlib import Path

import pytest
from scripts.qc.protocol_v3 import assemble_chapter_registry as assembly

SNAPSHOT = Path(__file__).with_name('assembled_batch1_registry.json')


@pytest.fixture
def split_batches(tmp_path):
    # Immutable pre-repair snapshot: no race with the active content worker.
    original = json.loads(SNAPSHOT.read_text())
    contracts, skills = tmp_path / 'contracts', tmp_path / 'skills'
    contracts.mkdir()
    skills.mkdir()
    batches = []
    for offset in (0, 6):
        entries = original['chapters'][offset:offset + 6]
        ids = {e['contract']['chapter_contract_id'] for e in entries}
        batch = {k: original[k] for k in ('generated_for', 'authority', 'template_id', 'template_sha256', 'fact_vocabulary', 'claim_vocabulary')}
        batch.update(schema_version=assembly.BATCH_SCHEMA_VERSION,
                     coverage_roles={e['node_id']: e['coverage_role'] for e in entries},
                     fixtures=[f for f in original['fixtures'] if f['chapter_contract_id'] in ids])
        for e in entries:
            (contracts / (e['node_id'] + '.json')).write_text(json.dumps(e['contract']))
            (skills / (e['node_id'] + '.json')).write_text(json.dumps(e['skills'][0]))
        path = tmp_path / f'batch{offset}.json'
        path.write_text(json.dumps(batch))
        batches.append(path)
    return contracts, skills, batches


def test_merge_preserves_every_chapter_and_fixture(split_batches):
    contracts, skills, batches = split_batches
    result = assembly.assemble_registries(contracts, skills, batches)
    assert len(result['chapters']) == 12
    assert len(result['fixtures']) == 48
    assert len({e['node_id'] for e in result['chapters']}) == 12


def test_duplicate_batch_is_not_silently_overwritten(split_batches):
    contracts, skills, batches = split_batches
    with pytest.raises(ValueError):
        assembly.assemble_registries(contracts, skills, [batches[0], batches[0]])


def test_different_template_batch_is_not_merged(split_batches):
    contracts, skills, batches = split_batches
    payload = json.loads(batches[1].read_text())
    payload['template_sha256'] = 'a' * 64
    batches[1].write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        assembly.assemble_registries(contracts, skills, batches)


def test_cli_accepts_repeated_batch_option(split_batches, capsys):
    contracts, skills, batches = split_batches
    assert assembly.main(['--contracts-dir', str(contracts), '--skills-dir', str(skills),
                          '--batch', str(batches[0]), '--batch', str(batches[1])]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result['chapters']) == 12
