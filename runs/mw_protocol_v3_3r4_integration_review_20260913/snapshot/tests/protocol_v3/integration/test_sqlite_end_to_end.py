"""Protocol v3 Task 1R.3 — real SQLite end-to-end integration.

Through the product adapter (``storage.sqlite`` + ``ApplicationService``),
never PoC code.  Every database is synthetic (``proj:1r3:*``) in a pytest tmp
directory.  Covers: commit durability across close/fresh-factory reopen,
separate-process reads with identical canonical hashes, exact-replay
idempotence, same-key/different-payload conflicts, WAL-consistent
backup/restore via the SQLite backup API (with a bare-main-file contrast),
atomic CAS/event/outbox fault rollback, the typed error mapping, and the
unknown-COMMIT-outcome reconcile-before-retry discipline.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.protocol_workflow.application import GetStudyDefinitionQuery

import integration_shared as shared


PROJ_A = "proj:1r3:e2e:a"
PROJ_B = "proj:1r3:e2e:b"
SD_A = "sd:1r3:a:1"
SD_B = "sd:1r3:b:1"


def _service(db_path: Path):
    return shared.make_service(shared.make_factory(db_path))


def _stream_head(db_path: Path, project_id: str, sd_id: str):
    from app.protocol_workflow.application.service import (
        study_definition_stream_id,
    )

    factory = shared.make_factory(db_path)
    with factory() as uow:
        return uow.event_stream_repository.get_stream_head(
            project_id, study_definition_stream_id(sd_id)
        )


def _event_count(db_path: Path, project_id: str, sd_id: str) -> int:
    head = _stream_head(db_path, project_id, sd_id)
    return 0 if head is None else head.event_count


# ---------------------------------------------------------------------------
# Commit / restart / replay
# ---------------------------------------------------------------------------


class TestCommitRestartReplay:
    def test_commit_survives_close_and_fresh_factory_reopen(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "e2e_restart.sqlite"
        first = _service(db_path)
        created = first.create_study_definition(
            shared.create_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:restart:create",
                side_effect=shared.side_effect_spec(
                    workflow_run_id="wr:1r3:restart"
                ),
            )
        )
        assert created.revision == 1
        assert len(created.revision_sha256) == 64
        snapshot_before = shared.fingerprint_dict(first, PROJ_A, SD_A)
        outbox_before = shared.outbox_rows(db_path, PROJ_A)
        assert len(outbox_before) == 1

        # Fresh factory over the same file: a full close/reopen boundary.
        reopened = _service(db_path)
        snapshot_after = shared.fingerprint_dict(reopened, PROJ_A, SD_A)
        assert snapshot_after == snapshot_before
        assert shared.outbox_rows(db_path, PROJ_A) == outbox_before
        assert shared.integrity_check(db_path) == "ok"

    def test_separate_process_reads_identical_canonical_hash(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "e2e_subprocess.sqlite"
        service = _service(db_path)
        service.create_study_definition(
            shared.create_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:subproc:create",
            )
        )
        current = service.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=PROJ_A, study_definition_id=SD_A
            )
        )
        applied = service.apply_decision(
            shared.apply_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:subproc:apply",
                expected_revision=1,
                snapshot_sha256=current.revision_sha256,
                decision_record_id="decision:1r3:dose:001",
                fact_updates=dict(shared.NEW_FACT),
            )
        )
        assert applied.revision == 2
        expected = shared.fingerprint_dict(service, PROJ_A, SD_A)

        child = (
            "import json, sys\n"
            "db_path, project_id, sd_id, root, shared_dir = sys.argv[1:6]\n"
            "sys.path.insert(0, root)\n"
            "sys.path.insert(0, root + '/services/api')\n"
            "sys.path.insert(0, root + '/packages')\n"
            "sys.path.insert(0, shared_dir)\n"
            "import sqlite3\n"
            "import integration_shared as shared\n"
            "assert tuple(int(p) for p in sqlite3.sqlite_version.split('.')[:3]) >= (3, 51, 3), sqlite3.sqlite_version\n"
            "service = shared.make_service(shared.make_factory(db_path))\n"
            "print(json.dumps(shared.fingerprint_dict(service, project_id, sd_id), sort_keys=True))\n"
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                str(db_path),
                PROJ_A,
                SD_A,
                str(shared.ROOT),
                str(Path(shared.__file__).resolve().parent),
            ],
            env=dict(os.environ),
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert completed.returncode == 0, (
            f"separate-process read failed rc={completed.returncode}\n"
            f"STDOUT:\n{completed.stdout[-3000:]}\n"
            f"STDERR:\n{completed.stderr[-3000:]}"
        )
        observed = json.loads(completed.stdout.strip().splitlines()[-1])
        assert observed == json.loads(json.dumps(expected, sort_keys=True))

    def test_exact_replay_after_restart_writes_nothing(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "e2e_replay.sqlite"
        service = _service(db_path)
        command = shared.create_command(
            project_id=PROJ_A,
            study_definition_id=SD_A,
            idempotency_key="idem:1r3:replay:create",
            side_effect=shared.side_effect_spec(workflow_run_id="wr:1r3:replay"),
        )
        first = service.create_study_definition(command)
        assert first.replayed is False

        # Same process duplicate: exact CAS replay, no second write.
        replay = service.create_study_definition(command)
        assert replay.replayed is True
        assert replay.revision == 1
        assert replay.revision_sha256 == first.revision_sha256
        assert replay.appended_events == ()
        assert replay.enqueued_outbox is None
        assert _event_count(db_path, PROJ_A, SD_A) == 1
        assert len(shared.outbox_rows(db_path, PROJ_A)) == 1

        # Same duplicate after a full close/reopen: ledger rebuilt from the
        # authoritative event stream, still an exact replay.
        restarted = _service(db_path)
        replay_after_restart = restarted.create_study_definition(command)
        assert replay_after_restart.replayed is True
        assert replay_after_restart.revision_sha256 == first.revision_sha256
        assert _event_count(db_path, PROJ_A, SD_A) == 1
        assert len(shared.outbox_rows(db_path, PROJ_A)) == 1
        assert shared.fingerprint_dict(
            restarted, PROJ_A, SD_A
        ) == shared.fingerprint_dict(service, PROJ_A, SD_A)

    def test_same_cas_triple_different_payload_conflicts_without_write(
        self, tmp_path: Path
    ) -> None:
        from app.protocol_workflow.errors import (
            ProtocolErrorCode,
            ProtocolWorkflowError,
        )

        db_path = tmp_path / "e2e_payload_conflict.sqlite"
        service = _service(db_path)
        service.create_study_definition(
            shared.create_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:payload:create",
            )
        )
        # Same CAS triple (record id + snapshot + expected revision) carrying
        # a different material payload (different reason): the ledger proves a
        # conflicting prior apply.
        conflicting = shared.create_command(
            project_id=PROJ_A,
            study_definition_id=SD_A,
            idempotency_key="idem:1r3:payload:create",
            reason="另一份不同的剂量设计说明。",
        )
        with pytest.raises(ProtocolWorkflowError) as exc_info:
            service.create_study_definition(conflicting)
        assert exc_info.value.code == ProtocolErrorCode.P1_DECISION_CAS
        assert _event_count(db_path, PROJ_A, SD_A) == 1
        assert shared.outbox_rows(db_path, PROJ_A) == []


# ---------------------------------------------------------------------------
# WAL-consistent backup / restore via the SQLite backup API
# ---------------------------------------------------------------------------


class TestWalConsistentBackupRestore:
    def test_backup_while_wal_uncheckpointed_restores_fully(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "live.sqlite"
        shared.admit(db_path, PROJ_A)
        shared.admit(db_path, PROJ_B)
        service = _service(db_path)
        created_a = service.create_study_definition(
            shared.create_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:bak:create:a",
                side_effect=shared.side_effect_spec(workflow_run_id="wr:1r3:bak"),
            )
        )
        applied_a = service.apply_decision(
            shared.apply_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:bak:apply:a",
                expected_revision=1,
                snapshot_sha256=created_a.revision_sha256,
                decision_record_id="decision:1r3:bak:dose:001",
                fact_updates=dict(shared.NEW_FACT),
                side_effect=shared.side_effect_spec(
                    workflow_run_id="wr:1r3:bak:2"
                ),
            )
        )
        assert applied_a.revision == 2
        created_b = service.create_study_definition(
            shared.create_command(
                project_id=PROJ_B,
                study_definition_id=SD_B,
                idempotency_key="idem:1r3:bak:create:b",
            )
        )
        assert created_b.revision == 1

        # Hold one connection open across the next commit: with zero open
        # connections SQLite checkpoints the WAL into the main file on last
        # close (observed empirically: -wal shrinks to empty/absent), which
        # would void the still-in-WAL premise.  The open holder suppresses
        # that shutdown checkpoint, so the next committed mutation leaves its
        # frames in the WAL — exactly the condition the backup API must
        # survive while the source family is still open.
        pin = sqlite3.connect(str(db_path), timeout=30)
        try:
            pin.execute("BEGIN")
            pin.execute("SELECT COUNT(*) FROM event_stream").fetchone()
            advanced_a = service.apply_decision(
                shared.apply_command(
                    project_id=PROJ_A,
                    study_definition_id=SD_A,
                    idempotency_key="idem:1r3:bak:apply:a3",
                    expected_revision=2,
                    snapshot_sha256=applied_a.revision_sha256,
                    decision_record_id="decision:1r3:bak:dose:002",
                    fact_updates={"picos.design.blinding": "双盲"},
                )
            )
            assert advanced_a.revision == 3

            wal = shared.wal_path(db_path)
            assert wal.exists(), "WAL file must exist for a WAL-mode product DB"
            assert wal.stat().st_size > 0, (
                "precondition: committed frames must still reside in the WAL "
                f"(wal bytes={wal.stat().st_size})"
            )

            live_dump_before = shared.dump_business_tables(db_path)
            live_fp_a = shared.fingerprint_dict(service, PROJ_A, SD_A)
            live_fp_b = shared.fingerprint_dict(service, PROJ_B, SD_B)
            assert live_fp_a["revision"] == 3
            assert live_fp_a["event_count"] == 3

            # Consistent copy through the SQLite backup API while the source
            # connection family is still open.
            restored_path = tmp_path / "restored.sqlite"
            src = sqlite3.connect(str(db_path), timeout=30)
            dst = sqlite3.connect(str(restored_path))
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()

            # Contrast: a bare copy of only the main database file (what the
            # design forbids) misses the WAL frames and reads stale state.
            contrast_path = tmp_path / "bare_copy.sqlite"
            shutil.copyfile(str(db_path), str(contrast_path))
        finally:
            pin.execute("ROLLBACK")
            pin.close()

        contrast = sqlite3.connect(f"file:{contrast_path}?mode=ro", uri=True)
        try:
            contrast_rev_a = contrast.execute(
                "SELECT MAX(revision) FROM aggregate_revision "
                "WHERE aggregate_kind='study_definition' AND project_id=? "
                "AND aggregate_id=?",
                (PROJ_A, SD_A),
            ).fetchone()[0]
            contrast_events_a = contrast.execute(
                "SELECT COUNT(*) FROM event_stream WHERE project_id=? "
                "AND stream_id=?",
                (PROJ_A, f"stream:study_definition:{SD_A}"),
            ).fetchone()[0]
        finally:
            contrast.close()
        assert (contrast_rev_a, contrast_events_a) == (2, 2), (
            "bare-main-file copy must be stale (rev 2 / 2 events) while live "
            "is rev 3 / 3 events; otherwise the WAL premise did not hold"
        )

        # Restore verification walks the product adapter, never raw bytes.
        restored_factory = shared.make_factory(restored_path)
        restored_service = shared.make_service(restored_factory)
        assert shared.integrity_check(restored_path) == "ok"
        assert shared.dump_business_tables(restored_path) == live_dump_before
        assert (
            shared.fingerprint_dict(restored_service, PROJ_A, SD_A) == live_fp_a
        )
        assert (
            shared.fingerprint_dict(restored_service, PROJ_B, SD_B) == live_fp_b
        )
        assert shared.outbox_rows(restored_path, PROJ_A) == shared.outbox_rows(
            db_path, PROJ_A
        )

        from app.protocol_workflow.storage.sqlite import is_project_admitted

        config = {"backend": "sqlite", "path": str(restored_path)}
        assert is_project_admitted(config, PROJ_A) is True
        assert is_project_admitted(config, PROJ_B) is True
        # The restored copy is a live, writable product database: one more
        # decision applies cleanly on top of the restored state.
        rev3_sha = shared.fingerprint_dict(
            restored_service, PROJ_A, SD_A
        )["revision_sha256"]
        advanced = restored_service.apply_decision(
            shared.apply_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:bak:apply:a4",
                expected_revision=3,
                snapshot_sha256=rev3_sha,
                decision_record_id="decision:1r3:bak:dose:003",
                fact_updates={"picos.design.control": "安慰剂对照"},
            )
        )
        assert advanced.revision == 4


# ---------------------------------------------------------------------------
# Atomic CAS / event / outbox fault rollback
# ---------------------------------------------------------------------------


class TestAtomicFaultRollback:
    def _seeded(self, db_path: Path, project_id: str, sd_id: str):
        service = _service(db_path)
        created = service.create_study_definition(
            shared.create_command(
                project_id=project_id,
                study_definition_id=sd_id,
                idempotency_key=f"idem:1r3:fault:create:{sd_id}",
            )
        )
        return service, created

    def test_cas_save_failure_rolls_back_event_and_outbox(
        self, tmp_path: Path
    ) -> None:
        from app.protocol_workflow.application.service import (
            study_definition_stream_id,
        )
        from app.protocol_workflow.events.unit_of_work import (
            EventSourcedUnitOfWork,
            MutationAbortedError,
        )
        from app.protocol_workflow.ports.repositories import RevisionConflictError

        db_path = tmp_path / "fault_cas.sqlite"
        service, created = self._seeded(db_path, PROJ_A, SD_A)
        factory = shared.make_factory(db_path)
        with factory() as probe:
            current = probe.study_definition_repository.get_current(PROJ_A, SD_A)
            stored_events = probe.event_stream_repository.read_events(
                PROJ_A, study_definition_stream_id(SD_A)
            )
        assert len(stored_events) == 1
        bad_aggregate = current.model_copy(
            update={
                "revision": 2,
                "previous_revision_sha256": created.revision_sha256,
                "updated_at": shared.T0,
            }
        )
        coordinator = EventSourcedUnitOfWork()
        with pytest.raises(MutationAbortedError) as exc_info:
            with factory() as uow:
                coordinator.apply_mutation(
                    uow,
                    project_id=PROJ_A,
                    stream_id=study_definition_stream_id(SD_A),
                    aggregate=bad_aggregate,
                    cas_repository_handle_name="study_definition_cas_repository",
                    events=(stored_events[0],),
                    expected_revision=999,
                )
        assert exc_info.value.step == "cas_save"
        assert isinstance(exc_info.value.original, RevisionConflictError)
        # Nothing from the aborted attempt is durable.
        assert _event_count(db_path, PROJ_A, SD_A) == 1
        assert shared.fingerprint_dict(service, PROJ_A, SD_A)[
            "revision_sha256"
        ] == created.revision_sha256
        assert shared.outbox_rows(db_path, PROJ_A) == []

    def test_event_chain_failure_rolls_back_cas_save(
        self, tmp_path: Path
    ) -> None:
        from app.protocol_workflow.application.service import (
            study_definition_stream_id,
        )
        from app.protocol_workflow.events.unit_of_work import (
            EventSourcedUnitOfWork,
            MutationAbortedError,
        )
        from app.protocol_workflow.ports.repositories import (
            EventSequenceConflictError,
        )

        db_path = tmp_path / "fault_event.sqlite"
        service, created = self._seeded(db_path, PROJ_A, SD_A)
        factory = shared.make_factory(db_path)
        with factory() as probe:
            current = probe.study_definition_repository.get_current(PROJ_A, SD_A)
            stored_events = probe.event_stream_repository.read_events(
                PROJ_A, study_definition_stream_id(SD_A)
            )
        next_aggregate = current.model_copy(
            update={
                "revision": 2,
                "previous_revision_sha256": created.revision_sha256,
                "updated_at": shared.T0,
            }
        )
        # Same domain_event_id as the stored genesis event: the store must
        # reject the batch before writing any row.
        broken = stored_events[0].model_copy(
            update={"payload": {"tampered": True}}
        )
        coordinator = EventSourcedUnitOfWork()
        with pytest.raises(MutationAbortedError) as exc_info:
            with factory() as uow:
                coordinator.apply_mutation(
                    uow,
                    project_id=PROJ_A,
                    stream_id=study_definition_stream_id(SD_A),
                    aggregate=next_aggregate,
                    cas_repository_handle_name="study_definition_cas_repository",
                    events=(broken,),
                    expected_revision=1,
                )
        assert exc_info.value.step == "event_append"
        assert isinstance(
            exc_info.value.original, EventSequenceConflictError
        )
        assert _event_count(db_path, PROJ_A, SD_A) == 1
        assert shared.fingerprint_dict(service, PROJ_A, SD_A)[
            "revision_sha256"
        ] == created.revision_sha256

    def test_outbox_conflict_rolls_back_cas_save_and_event(
        self, tmp_path: Path
    ) -> None:
        from app.protocol_workflow.errors import (
            ProtocolErrorCode,
            ProtocolWorkflowError,
        )

        db_path = tmp_path / "fault_outbox.sqlite"
        service = _service(db_path)
        service.create_study_definition(
            shared.create_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:outbox:key",
                side_effect=shared.side_effect_spec(
                    workflow_run_id="wr:1r3:outbox"
                ),
            )
        )
        assert len(shared.outbox_rows(db_path, PROJ_A)) == 1
        current = service.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=PROJ_A, study_definition_id=SD_A
            )
        )
        # Fresh decision, valid snapshot, but the SAME outbox logical key with
        # a different payload: the atomic enqueue must fail and roll back the
        # CAS save and the event append with it.
        colliding = shared.apply_command(
            project_id=PROJ_A,
            study_definition_id=SD_A,
            idempotency_key="idem:1r3:outbox:key",
            expected_revision=1,
            snapshot_sha256=current.revision_sha256,
            decision_record_id="decision:1r3:outbox:dose:001",
            fact_updates=dict(shared.NEW_FACT),
            side_effect=shared.side_effect_spec(
                workflow_run_id="wr:1r3:outbox"
            ),
        )
        with pytest.raises(ProtocolWorkflowError) as exc_info:
            service.apply_decision(colliding)
        assert exc_info.value.code == ProtocolErrorCode.P1_DECISION_CAS
        assert exc_info.value.retryable is True
        assert _event_count(db_path, PROJ_A, SD_A) == 1
        assert shared.fingerprint_dict(service, PROJ_A, SD_A)[
            "revision"
        ] == 1
        assert len(shared.outbox_rows(db_path, PROJ_A)) == 1

    def test_stale_revision_apply_maps_to_typed_error_without_write(
        self, tmp_path: Path
    ) -> None:
        from app.protocol_workflow.errors import (
            ProtocolErrorCode,
            ProtocolWorkflowError,
        )

        db_path = tmp_path / "fault_stale.sqlite"
        service = _service(db_path)
        created = service.create_study_definition(
            shared.create_command(
                project_id=PROJ_A,
                study_definition_id=SD_A,
                idempotency_key="idem:1r3:stale:create",
            )
        )
        stale = shared.apply_command(
            project_id=PROJ_A,
            study_definition_id=SD_A,
            idempotency_key="idem:1r3:stale:apply",
            expected_revision=2,
            snapshot_sha256=created.revision_sha256,
            decision_record_id="decision:1r3:stale:dose:001",
            fact_updates=dict(shared.NEW_FACT),
        )
        with pytest.raises(ProtocolWorkflowError) as exc_info:
            service.apply_decision(stale)
        assert exc_info.value.code == ProtocolErrorCode.P1_REVISION_STALE
        assert _event_count(db_path, PROJ_A, SD_A) == 1


# ---------------------------------------------------------------------------
# Typed error mapping (red-test locator for future mapping changes)
# ---------------------------------------------------------------------------


class TestTypedErrorMapping:
    def _translate(self, exc):
        from app.protocol_workflow.application.service import _translate

        return _translate(exc, project_id=PROJ_A, object_id=SD_A)

    def test_cas_conflict_maps_to_revision_stale(self) -> None:
        from app.protocol_workflow.errors import ProtocolErrorCode
        from app.protocol_workflow.events.unit_of_work import MutationAbortedError
        from app.protocol_workflow.ports.repositories import RevisionConflictError

        mapped = self._translate(
            MutationAbortedError(
                "cas_save",
                RevisionConflictError(PROJ_A, SD_A, 1, 2),
            )
        )
        assert mapped.code == ProtocolErrorCode.P1_REVISION_STALE
        assert mapped.retryable is True

    def test_event_mismatch_maps_to_checkpoint_code_not_retryable(self) -> None:
        from app.protocol_workflow.errors import ProtocolErrorCode
        from app.protocol_workflow.events.unit_of_work import MutationAbortedError
        from app.protocol_workflow.ports.repositories import (
            EventSequenceConflictError,
        )

        for exc in (
            EventSequenceConflictError(
                PROJ_A,
                "stream:probe",
                expected_sequence=2,
                actual_sequence=5,
                detail="probe chain break",
            ),
            MutationAbortedError(
                "event_append",
                EventSequenceConflictError(
                    PROJ_A,
                    "stream:probe",
                    expected_sequence=2,
                    actual_sequence=5,
                    detail="probe chain break",
                ),
            ),
        ):
            mapped = self._translate(exc)
            assert mapped.code == ProtocolErrorCode.P1_CHECKPOINT_EVENT_MISMATCH
            assert mapped.retryable is False

    def test_outbox_conflict_maps_to_decision_cas(self) -> None:
        from app.protocol_workflow.errors import ProtocolErrorCode
        from app.protocol_workflow.events.unit_of_work import MutationAbortedError
        from app.protocol_workflow.ports.repositories import IdempotencyConflictError

        mapped = self._translate(
            MutationAbortedError(
                "outbox_enqueue",
                IdempotencyConflictError(PROJ_A, "idem:probe", "a" * 64, "b" * 64),
            )
        )
        assert mapped.code == ProtocolErrorCode.P1_DECISION_CAS
        assert mapped.retryable is True

    def test_abort_without_cause_stays_decision_cas(self) -> None:
        from app.protocol_workflow.errors import ProtocolErrorCode
        from app.protocol_workflow.events.unit_of_work import MutationAbortedError

        mapped = self._translate(MutationAbortedError("mystery"))
        assert mapped.code == ProtocolErrorCode.P1_DECISION_CAS


# ---------------------------------------------------------------------------
# Unknown COMMIT outcome: reconcile by logical key before any retry
# ---------------------------------------------------------------------------


class TestInjectedPrecommitAbort:
    def test_precommit_abort_reconciles_before_retry(self, tmp_path, monkeypatch) -> None:
        from app.protocol_workflow.application import GetStudyDefinitionQuery
        from app.protocol_workflow.errors import ProtocolWorkflowError
        from app.protocol_workflow.storage.sqlite import SqliteUnitOfWork

        db_path = tmp_path / "unknown_commit.sqlite"
        real_factory = shared.make_factory(db_path)
        created_uows: list = []

        def capturing_factory():
            uow = real_factory()
            created_uows.append(uow)
            return uow

        service = shared.make_service(capturing_factory)
        original_commit = SqliteUnitOfWork.commit
        fired = {"count": 0}

        def flaky_commit(self):
            if fired["count"] == 0:
                fired["count"] += 1
                raise sqlite3.OperationalError(
                    "injected COMMIT failure (1R.3 unknown-outcome probe)"
                )
            return original_commit(self)

        monkeypatch.setattr(SqliteUnitOfWork, "commit", flaky_commit)
        command = shared.create_command(
            project_id=PROJ_A,
            study_definition_id=SD_A,
            idempotency_key="idem:1r3:unknown:create",
        )
        try:
            service.create_study_definition(command)
        except sqlite3.OperationalError as exc:
            # Unknown outcome surfaces as the raw driver error: no typed code
            # may be trusted to decide a retry.
            assert not isinstance(exc, ProtocolWorkflowError)
        else:
            pytest.fail("expected the injected COMMIT failure")
        finally:
            for uow in created_uows:
                uow.rollback()

        # Reconcile by logical key on a fresh unit of work BEFORE any retry.
        reconciler = shared.make_service(shared.make_factory(db_path))
        query = GetStudyDefinitionQuery(
            project_id=PROJ_A, study_definition_id=SD_A
        )
        observed = reconciler.get_study_definition(query)
        # This injection never commits. The landed branch is independently
        # exercised by the service and mounted HTTP acknowledgement-loss tests.
        assert observed.definition is None
        retried = reconciler.create_study_definition(command)
        assert retried.replayed is False
        assert retried.revision == 1
        assert _event_count(db_path, PROJ_A, SD_A) == 1
        assert shared.integrity_check(db_path) == "ok"
