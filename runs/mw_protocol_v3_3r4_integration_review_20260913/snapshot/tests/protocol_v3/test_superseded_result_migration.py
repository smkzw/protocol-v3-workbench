"""Historical terminal results never become actionable through consolidation."""

import sqlite3

from app.protocol_workflow.events.inbox import ConsumeOutcomeKind, InboxConsumer
from app.protocol_workflow.ports.repositories import InboxStatus
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
from test_result_storage_consolidation import (
    _CountingSemantic, _enqueue, _inbox_rows, _outbox_result_cols, _PROJ, _SHA_A, _T0, _T1,
)


def test_superseded_history_replay_stays_terminal_without_reactivating(tmp_path):
    path = tmp_path / "superseded.sqlite"
    factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
    with factory() as uow:
        original = uow.inbox_repository.record_result(_PROJ, "lk:old", _SHA_A, _T0)
    # Synthetic historical state supported by the existing InboxStatus contract.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE inbox_result SET status='superseded'")
    history = _inbox_rows(path)
    _enqueue(factory, "lk:old")
    semantic = _CountingSemantic()
    with factory() as uow:
        replay = uow.inbox_repository.record_result(_PROJ, "lk:old", _SHA_A, _T1)
        assert replay.status is InboxStatus.SUPERSEDED
        assert replay.inbox_result_id == original.inbox_result_id
        outcome = InboxConsumer(inbox=uow.inbox_repository, handler=semantic).consume(_PROJ, "lk:old")
        assert outcome.kind is ConsumeOutcomeKind.SKIPPED_SUPERSEDED
    assert semantic.calls == 0
    assert _inbox_rows(path) == history
    assert _outbox_result_cols(path, _PROJ, "lk:old") == (None, None, None)
