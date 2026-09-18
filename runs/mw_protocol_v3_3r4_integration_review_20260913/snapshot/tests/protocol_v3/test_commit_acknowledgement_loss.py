"""Committed data survives lost acknowledgement without duplicate effects."""

import sqlite3

import pytest

from app.protocol_workflow.application import GetStudyDefinitionQuery
from app.protocol_workflow.storage.sqlite import SqliteUnitOfWork
from tests.protocol_v3.integration import integration_shared as shared


def test_committed_mutation_with_lost_acknowledgement_replays_once(tmp_path, monkeypatch):
    db = tmp_path / "ack-loss.sqlite"
    service = shared.make_service(shared.make_factory(db))
    command = shared.create_command(
        project_id="proj:ack-loss", study_definition_id="sd:ack-loss",
        idempotency_key="idem:ack-loss",
    )
    original_commit = SqliteUnitOfWork.commit
    lost = False

    def commit_then_lose_ack(self):
        nonlocal lost
        original_commit(self)
        if not lost:
            lost = True
            raise sqlite3.OperationalError("synthetic acknowledgement loss")

    monkeypatch.setattr(SqliteUnitOfWork, "commit", commit_then_lose_ack)
    with pytest.raises(sqlite3.OperationalError):
        service.create_study_definition(command)

    recovered = shared.make_service(shared.make_factory(db))
    observed = recovered.get_study_definition(GetStudyDefinitionQuery(
        project_id="proj:ack-loss", study_definition_id="sd:ack-loss",
    ))
    assert observed.definition is not None
    before = shared.dump_business_tables(db)
    result = recovered.create_study_definition(command)
    assert result.replayed is True
    assert result.revision == 1
    assert shared.dump_business_tables(db) == before
    assert shared.integrity_check(db) == "ok"
