"""Actual SQLite + local bytes; importing a source is not medical admission."""
from datetime import datetime, timezone

import pytest

from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.storage.selected import create_product_unit_of_work_factory
from app.protocol_workflow.agent1.source_identity import SourceIdentityService


def service(root):
    return SourceIdentityService(
        create_product_unit_of_work_factory(config={'backend': 'sqlite', 'path': str(root / 'product.db')}),
        LocalArtifactStore(str(root / 'artifacts')),
    )


def adopt(svc, content=b'first', **kwargs):
    args = dict(project_id='project-1', logical_source_key='ib', content=content,
                source_role='project_primary', source_version='1.0', jurisdiction='CN',
                mime_type='application/octet-stream', captured_at=datetime(2026, 9, 13, tzinfo=timezone.utc))
    args.update(kwargs)
    return svc.adopt(**args)


def test_restart_retains_exact_bytes_and_identity(tmp_path):
    first = adopt(service(tmp_path))
    reopened = service(tmp_path)
    assert reopened.list_current('project-1') == (first.current,)
    assert reopened.read_content('project-1', first.source.source.source_artifact_id) == b'first'
    assert first.source.source.source_role.value == 'project_primary'


def test_old_content_replay_does_not_replace_successor(tmp_path):
    svc = service(tmp_path)
    first = adopt(svc)
    second = adopt(svc, b'second', source_version='2.0')
    replay = adopt(service(tmp_path))
    assert replay.replayed
    assert replay.source == first.source
    assert replay.current == second.current
    assert len(svc.history('project-1')) == 2
    assert svc.read_content('project-1', first.source.source.source_artifact_id) == b'first'


def test_same_bytes_different_role_cannot_relabel_previous_source(tmp_path):
    svc = service(tmp_path)
    first = adopt(svc)
    with pytest.raises(ValueError, match='source_metadata_conflict'):
        adopt(svc, source_role='competitor_full_protocol')
    assert svc.list_current('project-1') == (first.current,)
    assert len(svc.history('project-1')) == 1


def test_same_bytes_keep_distinct_project_provenance(tmp_path):
    svc = service(tmp_path)
    one = adopt(svc)
    two = adopt(svc, project_id='project-2')
    assert one.source.source.source_artifact_id != two.source.source.source_artifact_id
    assert one.source.storage_key != two.source.storage_key
    assert one.source.source.content_sha256 == two.source.source.content_sha256
    assert svc.list_current('project-1') == (one.current,)


def test_failed_canonical_commit_does_not_adopt_staged_files(tmp_path, monkeypatch):
    from app.protocol_workflow.storage.sqlite import SqliteUnitOfWork

    svc = service(tmp_path)
    first = adopt(svc)
    original = SqliteUnitOfWork.commit

    def fail(self):
        raise RuntimeError('simulated commit failure')

    with monkeypatch.context() as m:
        m.setattr(SqliteUnitOfWork, 'commit', fail)
        with pytest.raises(RuntimeError, match='simulated commit failure'):
            adopt(svc, b'second', source_version='2.0')
    assert SqliteUnitOfWork.commit is original
    assert service(tmp_path).list_current('project-1') == (first.current,)
    second = adopt(service(tmp_path), b'second', source_version='2.0')
    assert not second.replayed
    assert len(svc.history('project-1')) == 2


def test_two_service_instances_import_same_source_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    services = (service(tmp_path), service(tmp_path))
    barrier = Barrier(2)

    def run(svc):
        barrier.wait(timeout=5)
        return adopt(svc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run, services))
    assert sorted(result.replayed for result in results) == [False, True]
    assert results[0].source == results[1].source
    assert len(service(tmp_path).history('project-1')) == 1


def test_contract_whitespace_normalization_keeps_one_logical_source(tmp_path):
    svc = service(tmp_path)
    first = adopt(svc, logical_source_key=' ib ')
    again = adopt(svc, logical_source_key=' ib ')
    assert again.replayed and again.source == first.source
    assert adopt(svc, logical_source_key='ib').source == first.source
    assert len(svc.history('project-1')) == 1
