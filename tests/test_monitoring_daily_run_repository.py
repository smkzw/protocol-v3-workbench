from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
import sqlite3
from threading import Barrier, Lock

import pytest

from services.api.app.monitoring_daily_run_repository import (
    DailyRunActiveConflictError,
    DailyRunBaselineConflictError,
    DailyRunIdempotencyConflictError,
    DailyRunInput,
    DailyRunLeaseConflictError,
    DailyRunOutputConflictError,
    DailyRunStateConflictError,
    DailyRunVersionConflictError,
    MonitoringDailyRunRepository,
    MonitoringDailyRunRepositoryError,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


class MutableClock:
    def __init__(self) -> None:
        self._value = datetime(2026, 7, 29, 4, 0, tzinfo=timezone.utc)
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._value

    def advance(self, **kwargs: int) -> None:
        with self._lock:
            self._value += timedelta(**kwargs)


def run_input(
    *,
    project_id: str = "proj-rux",
    batch_id: str = "batch-001",
    baseline_batch_id: str | None = None,
    batch_version: int = 7,
    mapping_revision: str = "mapping-v3",
) -> DailyRunInput:
    return DailyRunInput(
        project_id=project_id,
        batch_id=batch_id,
        baseline_batch_id=baseline_batch_id,
        batch_version=batch_version,
        mapping_revision=mapping_revision,
        rule_pack_revision="rules-v5",
        engine_version="monitoring-engine/2.0",
        diff_algorithm_version="monitoring-diff/2.0",
    )


def bind_rule_output(
    repository: MonitoringDailyRunRepository,
    run,
):
    return repository.save_rule_snapshot(
        run.project_id,
        run.run_id,
        input_sha256=HASH_A,
        payload={
            "project_id": run.project_id,
            "batch_id": run.batch_id,
            "rule_pack_id": run.rule_pack_revision,
            "candidates": [],
            "diagnostics": [],
        },
        expected_version=run.version,
        actor="orchestrator",
    ).run


def prepare_initial_for_confirmation(
    repository: MonitoringDailyRunRepository,
    *,
    project_id: str = "proj-rux",
    batch_id: str = "batch-001",
):
    created = repository.create_or_get(
        run_input(project_id=project_id, batch_id=batch_id),
        idempotency_key=f"create:{batch_id}",
        actor="medical-manager",
    ).run
    rules = repository.transition(
        project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )
    rules = bind_rule_output(repository, rules)
    bound = repository.bind_risk_snapshot(
        project_id,
        created.run_id,
        risk_snapshot_id=f"risksnap:{batch_id}",
        expected_version=rules.version,
        actor="orchestrator",
    ).run
    review = repository.transition(
        project_id,
        created.run_id,
        target_status="risk_review",
        expected_version=bound.version,
        actor="orchestrator",
    )
    return repository.transition(
        project_id,
        created.run_id,
        target_status="ready_to_confirm",
        expected_version=review.version,
        actor="medical-manager",
    )


def prepare_incremental_for_confirmation(
    repository: MonitoringDailyRunRepository,
    *,
    project_id: str,
    batch_id: str,
    baseline_batch_id: str,
):
    created = repository.create_or_get(
        run_input(
            project_id=project_id,
            batch_id=batch_id,
            baseline_batch_id=baseline_batch_id,
            batch_version=8,
        ),
        idempotency_key=f"create:{batch_id}",
    ).run
    diffing = repository.transition(
        project_id,
        created.run_id,
        target_status="diffing",
        expected_version=created.version,
        actor="orchestrator",
    )
    diff = repository.save_diff_snapshot(
        project_id,
        created.run_id,
        input_sha256=HASH_A,
        payload={
            "previous_batch_id": baseline_batch_id,
            "current_batch_id": batch_id,
            "added": ["AE:S001:2"],
            "changed": ["LB:S001:ALT:W4"],
        },
        expected_version=diffing.version,
        actor="orchestrator",
    )
    rules = repository.transition(
        project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=diff.run.version,
        actor="orchestrator",
    )
    rules = bind_rule_output(repository, rules)
    bound = repository.bind_risk_snapshot(
        project_id,
        created.run_id,
        risk_snapshot_id=f"risksnap:{batch_id}",
        expected_version=rules.version,
        actor="orchestrator",
    ).run
    review = repository.transition(
        project_id,
        created.run_id,
        target_status="risk_review",
        expected_version=bound.version,
        actor="orchestrator",
    )
    return repository.transition(
        project_id,
        created.run_id,
        target_status="ready_to_confirm",
        expected_version=review.version,
        actor="medical-manager",
    )


def test_create_idempotency_replays_same_request_and_rejects_changed_request(
    tmp_path: Path,
) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    request = run_input()

    created = repository.create_or_get(
        request,
        idempotency_key="daily-run:001",
        actor="medical-manager",
    )
    replay = repository.create_or_get(
        request,
        idempotency_key="daily-run:001",
        actor="another-actor",
    )

    assert created.replayed is False
    assert replay.replayed is True
    assert replay.run == created.run
    with pytest.raises(DailyRunIdempotencyConflictError, match="different request"):
        repository.create_or_get(
            run_input(batch_id="batch-002"),
            idempotency_key="daily-run:001",
        )


def test_persisted_daily_run_root_rejects_text_batch_version_without_coercion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="root-shape-version",
    ).run

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_runs SET batch_version = ? WHERE run_id = ?",
            ("not-an-int", created.run_id),
        )

    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="persisted daily run root is invalid",
    ):
        repository.get(created.project_id, created.run_id)


def test_project_has_only_one_active_run_and_state_survives_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    first = repository.create_or_get(
        run_input(),
        idempotency_key="create:1",
    ).run

    with pytest.raises(DailyRunActiveConflictError, match="active run"):
        repository.create_or_get(
            run_input(batch_id="batch-002"),
            idempotency_key="create:2",
        )

    reopened = MonitoringDailyRunRepository(path)
    assert reopened.get(first.project_id, first.run_id) == first
    assert reopened.list_events(first.run_id)[0].event_type == "run_created"


def test_additive_resolution_mode_migration_preserves_project_effective_records(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:migration",
    ).run
    rules = repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )
    saved = repository.save_rule_snapshot(
        rules.project_id,
        rules.run_id,
        input_sha256=HASH_A,
        payload={
            "project_id": rules.project_id,
            "batch_id": rules.batch_id,
            "rule_pack_id": rules.rule_pack_revision,
            "candidates": [],
            "diagnostics": [],
        },
        expected_version=rules.version,
        actor="orchestrator",
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE monitoring_daily_rule_snapshots "
            "DROP COLUMN resolution_mode"
        )
        connection.execute(
            "ALTER TABLE monitoring_daily_runs "
            "DROP COLUMN rule_resolution_mode"
        )

    reopened = MonitoringDailyRunRepository(path)
    migrated_run = reopened.get(created.project_id, created.run_id)
    migrated_snapshot = reopened.get_rule_snapshot(
        created.project_id,
        created.run_id,
    )

    assert migrated_run.rule_resolution_mode == "project_effective"
    assert migrated_run.version == saved.run.version
    assert migrated_snapshot is not None
    assert migrated_snapshot.resolution_mode == "project_effective"
    assert migrated_snapshot.rule_pack_id == created.rule_pack_revision
    with sqlite3.connect(path) as connection:
        run_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(monitoring_daily_runs)"
            )
        }
        snapshot_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(monitoring_daily_rule_snapshots)"
            )
        }
    assert "rule_resolution_mode" in run_columns
    assert "resolution_mode" in snapshot_columns


def test_state_progression_uses_version_cas_and_enforces_initial_diff_boundary(
    tmp_path: Path,
) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    initial = repository.create_or_get(
        run_input(),
        idempotency_key="create:1",
    ).run

    with pytest.raises(DailyRunStateConflictError, match="skip diffing"):
        repository.transition(
            initial.project_id,
            initial.run_id,
            target_status="diffing",
            expected_version=initial.version,
            actor="orchestrator",
        )
    rules = repository.transition(
        initial.project_id,
        initial.run_id,
        target_status="rules_running",
        expected_version=initial.version,
        actor="orchestrator",
    )
    with pytest.raises(DailyRunVersionConflictError, match="version CAS"):
        repository.transition(
            initial.project_id,
            initial.run_id,
            target_status="risk_review",
            expected_version=initial.version,
            actor="stale-worker",
        )
    with pytest.raises(DailyRunStateConflictError, match="confirm_run"):
        repository.transition(
            initial.project_id,
            initial.run_id,
            target_status="confirmed",
            expected_version=rules.version,
            actor="medical-manager",
        )


def test_lease_heartbeat_expiry_reclaim_and_stale_worker_fence(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringDailyRunRepository(
        tmp_path / "daily.sqlite3",
        lease_seconds=10,
        clock=clock,
    )
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:1",
    ).run
    first = repository.claim(
        created.project_id,
        created.run_id,
        owner="worker-a",
        expected_version=created.version,
    )
    heartbeat = repository.heartbeat(
        first.project_id,
        first.run_id,
        owner="worker-a",
        lease_epoch=first.lease_epoch,
    )
    assert heartbeat.lease_expires_at == clock() + timedelta(seconds=10)

    clock.advance(seconds=11)
    reclaimed = repository.claim(
        first.project_id,
        first.run_id,
        owner="worker-b",
        expected_version=first.version,
    )
    assert reclaimed.lease_epoch == first.lease_epoch + 1
    assert reclaimed.claim_count == 2

    with pytest.raises(DailyRunLeaseConflictError, match="lease"):
        repository.transition(
            reclaimed.project_id,
            reclaimed.run_id,
            target_status="rules_running",
            expected_version=reclaimed.version,
            actor="worker-a",
            lease_owner="worker-a",
            lease_epoch=first.lease_epoch,
        )
    transitioned = repository.transition(
        reclaimed.project_id,
        reclaimed.run_id,
        target_status="rules_running",
        expected_version=reclaimed.version,
        actor="worker-b",
        lease_owner="worker-b",
        lease_epoch=reclaimed.lease_epoch,
    )
    assert transitioned.status == "rules_running"


def test_concurrent_claim_next_allows_only_one_worker(tmp_path: Path) -> None:
    path = tmp_path / "daily.sqlite3"
    MonitoringDailyRunRepository(path).create_or_get(
        run_input(),
        idempotency_key="create:1",
    )
    barrier = Barrier(2)

    def claim(owner: str):
        repository = MonitoringDailyRunRepository(path)
        barrier.wait()
        return repository.claim_next(owner=owner)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("worker-a", "worker-b")))

    claimed = [result for result in results if result is not None]
    assert len(claimed) == 1
    assert claimed[0].claim_count == 1


def test_completed_step_replays_by_hash_and_changed_output_fails_closed(
    tmp_path: Path,
) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:1",
    ).run
    claimed = repository.claim(
        created.project_id,
        created.run_id,
        owner="worker-a",
        expected_version=created.version,
    )
    started = repository.start_step(
        claimed.project_id,
        claimed.run_id,
        step_name="rules",
        input_sha256=HASH_A,
        expected_run_version=claimed.version,
        lease_owner="worker-a",
        lease_epoch=claimed.lease_epoch,
    )
    completed = repository.finish_step(
        claimed.project_id,
        claimed.run_id,
        step_name="rules",
        status="completed",
        input_sha256=HASH_A,
        output_sha256=HASH_B,
        expected_run_version=claimed.version,
        lease_owner="worker-a",
        lease_epoch=claimed.lease_epoch,
        details={"risk_count": 4},
    )
    replay = repository.finish_step(
        claimed.project_id,
        claimed.run_id,
        step_name="rules",
        status="completed",
        input_sha256=HASH_A,
        output_sha256=HASH_B,
        expected_run_version=claimed.version,
        lease_owner="worker-a",
        lease_epoch=claimed.lease_epoch,
    )

    assert started.replayed is False
    assert completed.step.status == "completed"
    assert replay.replayed is True
    assert repository.start_step(
        claimed.project_id,
        claimed.run_id,
        step_name="rules",
        input_sha256=HASH_A,
        expected_run_version=claimed.version,
        lease_owner="worker-a",
        lease_epoch=claimed.lease_epoch,
    ).replayed
    with pytest.raises(DailyRunOutputConflictError, match="different output"):
        repository.finish_step(
            claimed.project_id,
            claimed.run_id,
            step_name="rules",
            status="completed",
            input_sha256=HASH_A,
            output_sha256="c" * 64,
            expected_run_version=claimed.version,
            lease_owner="worker-a",
            lease_epoch=claimed.lease_epoch,
        )
    assert [step.step_name for step in repository.list_steps(claimed.run_id)] == [
        "rules"
    ]


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("details_json", json.dumps([])),
        ("input_sha256", "A" * 64),
        ("step_name", " "),
    ),
)
def test_persisted_daily_step_read_shape_is_rejected(
    tmp_path: Path,
    column: str,
    value: str,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:step-shape",
    ).run
    claimed = repository.claim(
        created.project_id,
        created.run_id,
        owner="worker-a",
        expected_version=created.version,
    )
    repository.start_step(
        claimed.project_id,
        claimed.run_id,
        step_name="rules",
        input_sha256=HASH_A,
        expected_run_version=claimed.version,
        lease_owner="worker-a",
        lease_epoch=claimed.lease_epoch,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE monitoring_daily_run_steps SET {column} = ? "
            "WHERE run_id = ? AND step_name = ?",
            (value, claimed.run_id, "rules"),
        )

    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="persisted daily run step is invalid",
    ):
        reopened.list_steps(claimed.run_id)


def test_persisted_daily_step_rejects_float_counter_without_coercion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:step-counter-shape",
    ).run
    claimed = repository.claim(
        created.project_id,
        created.run_id,
        owner="worker-a",
        expected_version=created.version,
    )
    repository.start_step(
        claimed.project_id,
        claimed.run_id,
        step_name="rules",
        input_sha256=HASH_A,
        expected_run_version=claimed.version,
        lease_owner="worker-a",
        lease_epoch=claimed.lease_epoch,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_run_steps SET attempt_count = ? "
            "WHERE run_id = ? AND step_name = ?",
            (1.5, claimed.run_id, "rules"),
        )

    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="persisted daily run step is invalid",
    ):
        reopened.list_steps(claimed.run_id)


def test_persisted_daily_event_read_shape_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:event-shape",
    ).run
    repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_run_events SET payload_json = ? "
            "WHERE run_id = ?",
            (json.dumps([]), created.run_id),
        )

    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="persisted daily run event is invalid",
    ):
        reopened.list_events(created.run_id)


def test_persisted_daily_event_rejects_float_version_without_coercion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:event-counter-shape",
    ).run
    repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_run_events SET run_version = ? "
            "WHERE run_id = ?",
            (1.5, created.run_id),
        )

    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="persisted daily run event is invalid",
    ):
        reopened.list_events(created.run_id)


def test_persisted_monitoring_baseline_read_shape_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    ready = prepare_initial_for_confirmation(repository)
    confirmed = repository.confirm_run(
        ready.project_id,
        ready.run_id,
        expected_run_version=ready.version,
        expected_baseline_revision=0,
        confirmed_by="medical-manager",
    )
    assert confirmed.baseline.revision == 1
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_project_baselines SET confirmed_by = ? "
            "WHERE project_id = ?",
            ("", ready.project_id),
        )

    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="persisted monitoring baseline is invalid",
    ):
        reopened.current_baseline(ready.project_id)


def test_persisted_monitoring_baseline_rejects_float_revision_without_coercion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    ready = prepare_initial_for_confirmation(repository)
    repository.confirm_run(
        ready.project_id,
        ready.run_id,
        expected_run_version=ready.version,
        expected_baseline_revision=0,
        confirmed_by="medical-manager",
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_project_baselines SET revision = ? "
            "WHERE project_id = ?",
            (1.5, ready.project_id),
        )

    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="persisted monitoring baseline is invalid",
    ):
        reopened.current_baseline(ready.project_id)


def test_running_step_restarts_after_run_lease_is_reclaimed(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    repository = MonitoringDailyRunRepository(
        tmp_path / "daily.sqlite3",
        lease_seconds=10,
        clock=clock,
    )
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:1",
    ).run
    first_claim = repository.claim(
        created.project_id,
        created.run_id,
        owner="worker-a",
        expected_version=created.version,
    )
    first_step = repository.start_step(
        created.project_id,
        created.run_id,
        step_name="rules",
        input_sha256=HASH_A,
        expected_run_version=first_claim.version,
        lease_owner="worker-a",
        lease_epoch=first_claim.lease_epoch,
    )
    assert first_step.step.attempt_count == 1
    assert first_step.step.lease_epoch == first_claim.lease_epoch

    clock.advance(seconds=11)
    reclaimed = repository.claim(
        created.project_id,
        created.run_id,
        owner="worker-b",
        expected_version=first_claim.version,
    )
    restarted = repository.start_step(
        created.project_id,
        created.run_id,
        step_name="rules",
        input_sha256=HASH_A,
        expected_run_version=reclaimed.version,
        lease_owner="worker-b",
        lease_epoch=reclaimed.lease_epoch,
    )

    assert restarted.replayed is False
    assert restarted.step.status == "running"
    assert restarted.step.attempt_count == 2
    assert restarted.step.lease_epoch == reclaimed.lease_epoch
    with pytest.raises(DailyRunLeaseConflictError):
        repository.finish_step(
            created.project_id,
            created.run_id,
            step_name="rules",
            status="completed",
            input_sha256=HASH_A,
            output_sha256=HASH_B,
            expected_run_version=reclaimed.version,
            lease_owner="worker-a",
            lease_epoch=first_claim.lease_epoch,
        )


def test_diff_snapshot_is_immutable_versioned_and_required_before_rules(
    tmp_path: Path,
) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    created = repository.create_or_get(
        run_input(batch_id="batch-002", baseline_batch_id="batch-001"),
        idempotency_key="create:2",
    ).run
    diffing = repository.transition(
        created.project_id,
        created.run_id,
        target_status="diffing",
        expected_version=created.version,
        actor="orchestrator",
    )
    with pytest.raises(DailyRunStateConflictError, match="diff result"):
        repository.transition(
            created.project_id,
            created.run_id,
            target_status="rules_running",
            expected_version=diffing.version,
            actor="orchestrator",
        )

    saved = repository.save_diff_snapshot(
        created.project_id,
        created.run_id,
        input_sha256=HASH_A,
        payload={"added": ["AE:1"], "changed": [], "schema": {"LB": ["LBORRES"]}},
        expected_version=diffing.version,
        actor="orchestrator",
    )
    replay = repository.save_diff_snapshot(
        created.project_id,
        created.run_id,
        input_sha256=HASH_A,
        payload={"schema": {"LB": ["LBORRES"]}, "changed": [], "added": ["AE:1"]},
        expected_version=saved.run.version,
        actor="orchestrator",
    )

    assert saved.replayed is False
    assert replay.replayed is True
    assert saved.snapshot.output_sha256 == replay.snapshot.output_sha256
    with pytest.raises(DailyRunOutputConflictError, match="different diff"):
        repository.save_diff_snapshot(
            created.project_id,
            created.run_id,
            input_sha256=HASH_A,
            payload={"added": ["AE:2"]},
            expected_version=saved.run.version,
            actor="orchestrator",
        )
    rules = repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=saved.run.version,
        actor="orchestrator",
    )
    assert rules.status == "rules_running"


def test_drift_review_closes_active_slot_and_diff_is_recoverable_after_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(batch_id="batch-002", baseline_batch_id="batch-001"),
        idempotency_key="create:drift",
    ).run
    diffing = repository.transition(
        created.project_id,
        created.run_id,
        target_status="diffing",
        expected_version=created.version,
        actor="orchestrator",
    )
    saved = repository.save_diff_snapshot(
        created.project_id,
        created.run_id,
        input_sha256=HASH_A,
        payload={"schema_drift": {"LB": {"added": ["LBSTRESC"]}}},
        expected_version=diffing.version,
        actor="orchestrator",
    )
    drifted = repository.transition(
        created.project_id,
        created.run_id,
        target_status="drift_review_required",
        expected_version=saved.run.version,
        actor="orchestrator",
    )

    assert drifted.status == "drift_review_required"
    assert repository.active_run(created.project_id) is None
    reopened = MonitoringDailyRunRepository(path)
    restored = reopened.get_diff_snapshot(created.project_id, created.run_id)
    assert restored == saved.snapshot
    replacement = reopened.create_or_get(
        run_input(
            batch_id="batch-002",
            baseline_batch_id="batch-001",
            mapping_revision="mapping-v4",
        ),
        idempotency_key="create:replacement",
    )
    assert replacement.run.status == "prepared"
    assert reopened.active_run(created.project_id) == replacement.run
    superseded = reopened.supersede_drifted_run(
        created.project_id,
        drifted.run_id,
        replacement_run_id=replacement.run.run_id,
        expected_version=drifted.version,
        actor="medical-manager",
    )
    assert superseded.status == "superseded"
    assert reopened.list_events(drifted.run_id)[-1].payload == {
        "replacement_run_id": replacement.run.run_id
    }


def test_persisted_diff_snapshot_tamper_is_rejected_on_restart_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(batch_id="batch-002", baseline_batch_id="batch-001"),
        idempotency_key="create:diff-tamper",
    ).run
    diffing = repository.transition(
        created.project_id,
        created.run_id,
        target_status="diffing",
        expected_version=created.version,
        actor="orchestrator",
    )
    saved = repository.save_diff_snapshot(
        created.project_id,
        created.run_id,
        input_sha256=HASH_A,
        payload={"added": ["AE:1"], "changed": []},
        expected_version=diffing.version,
        actor="orchestrator",
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_diff_snapshots SET payload_json = ? "
            "WHERE snapshot_id = ?",
            ('{"added":["AE:tampered"],"changed":[]}', saved.snapshot.snapshot_id),
        )
    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        DailyRunOutputConflictError,
        match="diff snapshot content hash mismatch",
    ):
        reopened.get_diff_snapshot(created.project_id, created.run_id)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_diff_snapshots SET payload_json = ?, "
            "previous_batch_id = ? WHERE snapshot_id = ?",
            (
                '{"added":["AE:1"],"changed":[]}',
                "batch-tampered",
                saved.snapshot.snapshot_id,
            ),
        )
    with pytest.raises(
        DailyRunOutputConflictError,
        match="diff snapshot row identity mismatch",
    ):
        reopened.get_diff_snapshot(created.project_id, created.run_id)


def test_persisted_diff_snapshot_rejects_noncanonical_input_hash(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(batch_id="batch-002", baseline_batch_id="batch-001"),
        idempotency_key="create:diff-input-shape",
    ).run
    diffing = repository.transition(
        created.project_id,
        created.run_id,
        target_status="diffing",
        expected_version=created.version,
        actor="orchestrator",
    )
    saved = repository.save_diff_snapshot(
        created.project_id,
        created.run_id,
        input_sha256=HASH_A,
        payload={"added": ["AE:1"], "changed": []},
        expected_version=diffing.version,
        actor="orchestrator",
    )
    uppercase_input = HASH_A.upper()
    replacement_snapshot_id = (
        "mondiff_"
        + sha256(
            f"{created.run_id}|{uppercase_input}|{saved.snapshot.output_sha256}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_diff_snapshots SET input_sha256 = ?, "
            "snapshot_id = ? WHERE run_id = ?",
            (uppercase_input, replacement_snapshot_id, created.run_id),
        )

    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        DailyRunOutputConflictError,
        match="diff snapshot input_sha256 is not canonical",
    ):
        reopened.get_diff_snapshot(created.project_id, created.run_id)


def test_persisted_daily_run_input_tamper_is_rejected_on_restart_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily-run-input-tamper.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:root-input-tamper",
    ).run

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_runs SET engine_version = ? "
            "WHERE run_id = ?",
            ("tampered-engine", created.run_id),
        )

    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="daily run input hash mismatch",
    ):
        reopened.get(created.project_id, created.run_id)
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="daily run input hash mismatch",
    ):
        reopened.list_runs(created.project_id)


def test_final_confirmation_atomically_advances_baseline_and_allows_next_run(
    tmp_path: Path,
) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    ready = prepare_initial_for_confirmation(repository)

    confirmed = repository.confirm_run(
        ready.project_id,
        ready.run_id,
        expected_run_version=ready.version,
        expected_baseline_revision=0,
        confirmed_by="medical-manager-a",
    )

    assert confirmed.run.status == "confirmed"
    assert confirmed.baseline.current_baseline_batch_id == "batch-001"
    assert confirmed.baseline.revision == 1
    next_run = repository.create_or_get(
        run_input(batch_id="batch-002", baseline_batch_id="batch-001"),
        idempotency_key="create:2",
    ).run
    assert next_run.status == "prepared"


def test_incremental_confirmation_rejects_stale_baseline_pointer(
    tmp_path: Path,
) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    first = prepare_initial_for_confirmation(repository)
    repository.confirm_run(
        first.project_id,
        first.run_id,
        expected_run_version=first.version,
        expected_baseline_revision=0,
        confirmed_by="medical-manager",
    )
    second = prepare_incremental_for_confirmation(
        repository,
        project_id="proj-rux",
        batch_id="batch-002",
        baseline_batch_id="batch-001",
    )

    with pytest.raises(DailyRunBaselineConflictError, match="revision CAS"):
        repository.confirm_run(
            second.project_id,
            second.run_id,
            expected_run_version=second.version,
            expected_baseline_revision=0,
            confirmed_by="stale-client",
        )
    confirmed = repository.confirm_run(
        second.project_id,
        second.run_id,
        expected_run_version=second.version,
        expected_baseline_revision=1,
        confirmed_by="medical-manager",
    )
    assert confirmed.baseline.current_baseline_batch_id == "batch-002"
    assert confirmed.baseline.revision == 2


def test_two_confirmers_cannot_both_advance_project_baseline(tmp_path: Path) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    ready = prepare_initial_for_confirmation(repository)
    barrier = Barrier(2)

    def confirm(actor: str):
        contender = MonitoringDailyRunRepository(path)
        barrier.wait()
        try:
            result = contender.confirm_run(
                ready.project_id,
                ready.run_id,
                expected_run_version=ready.version,
                expected_baseline_revision=0,
                confirmed_by=actor,
            )
            return ("confirmed", result.baseline.revision)
        except (DailyRunVersionConflictError, DailyRunStateConflictError):
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(confirm, ("medical-manager-a", "medical-manager-b"))
        )

    assert outcomes.count(("confirmed", 1)) == 1
    assert outcomes.count(("conflict", None)) == 1
    baseline = MonitoringDailyRunRepository(path).current_baseline("proj-rux")
    assert baseline is not None
    assert baseline.revision == 1


def test_final_confirmation_requires_diff_and_risk_outputs(tmp_path: Path) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:1",
    ).run
    rules = repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )
    rules = bind_rule_output(repository, rules)
    review = repository.transition(
        created.project_id,
        created.run_id,
        target_status="risk_review",
        expected_version=rules.version,
        actor="orchestrator",
    )
    with pytest.raises(DailyRunStateConflictError, match="risk snapshot"):
        repository.transition(
            created.project_id,
            created.run_id,
            target_status="ready_to_confirm",
            expected_version=review.version,
            actor="medical-manager",
        )


def test_rule_snapshot_is_immutable_replayable_and_required_before_review(
    tmp_path: Path,
) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:rule-snapshot",
    ).run
    rules = repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )
    with pytest.raises(DailyRunStateConflictError, match="rule snapshot"):
        repository.transition(
            created.project_id,
            created.run_id,
            target_status="risk_review",
            expected_version=rules.version,
            actor="orchestrator",
        )

    payload = {
        "project_id": rules.project_id,
        "batch_id": rules.batch_id,
        "rule_pack_id": rules.rule_pack_revision,
        "candidates": [{"candidate_id": "candidate-1"}],
        "diagnostics": [{"code": "missing_field"}],
    }
    saved = repository.save_rule_snapshot(
        rules.project_id,
        rules.run_id,
        input_sha256=HASH_A,
        payload=payload,
        expected_version=rules.version,
        actor="orchestrator",
    )
    stored = repository.get_rule_snapshot(rules.project_id, rules.run_id)
    assert stored is not None
    assert stored.snapshot_id == saved.snapshot.snapshot_id
    assert stored.payload == payload
    assert saved.run.rule_snapshot_id == stored.snapshot_id

    replayed = repository.save_rule_snapshot(
        rules.project_id,
        rules.run_id,
        input_sha256=HASH_A,
        payload=payload,
        expected_version=saved.run.version,
        actor="orchestrator",
    )
    assert replayed.replayed is True
    with pytest.raises(DailyRunOutputConflictError, match="different rule snapshot"):
        repository.save_rule_snapshot(
            rules.project_id,
            rules.run_id,
            input_sha256=HASH_A,
            payload={**payload, "diagnostics": []},
            expected_version=saved.run.version,
            actor="orchestrator",
        )


def test_persisted_rule_snapshot_tamper_is_rejected_on_restart_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:rule-tamper",
    ).run
    rules = repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )
    payload = {
        "project_id": rules.project_id,
        "batch_id": rules.batch_id,
        "rule_pack_id": rules.rule_pack_revision,
        "candidates": [],
        "diagnostics": [],
    }
    saved = repository.save_rule_snapshot(
        rules.project_id,
        rules.run_id,
        input_sha256=HASH_A,
        payload=payload,
        expected_version=rules.version,
        actor="orchestrator",
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_rule_snapshots SET payload_json = ? "
            "WHERE snapshot_id = ?",
            (
                '{"batch_id":"batch-001","candidates":[],"diagnostics":['
                '{"code":"tampered"}],"project_id":"proj-rux",'
                '"rule_pack_id":"rules-v5"}',
                saved.snapshot.snapshot_id,
            ),
        )
    reopened = MonitoringDailyRunRepository(path)
    with pytest.raises(
        DailyRunOutputConflictError,
        match="rule snapshot content hash mismatch",
    ):
        reopened.get_rule_snapshot(created.project_id, created.run_id)

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE monitoring_daily_rule_snapshots SET payload_json = ?, "
            "batch_id = ? WHERE snapshot_id = ?",
            (
                '{"batch_id":"batch-001","candidates":[],"diagnostics":[],'
                '"project_id":"proj-rux","rule_pack_id":"rules-v5"}',
                "batch-tampered",
                saved.snapshot.snapshot_id,
            ),
        )
    with pytest.raises(
        DailyRunOutputConflictError,
        match="rule snapshot batch identity mismatch",
    ):
        reopened.get_rule_snapshot(created.project_id, created.run_id)


def test_rule_snapshot_rejects_non_boolean_analysis_completion(
    tmp_path: Path,
) -> None:
    repository = MonitoringDailyRunRepository(tmp_path / "daily.sqlite3")
    created = repository.create_or_get(
        run_input(), idempotency_key="create:analysis-complete-shape"
    ).run
    rules = repository.transition(
        created.project_id,
        created.run_id,
        target_status="rules_running",
        expected_version=created.version,
        actor="orchestrator",
    )

    with pytest.raises(DailyRunOutputConflictError, match="analysis_complete"):
        repository.save_rule_snapshot(
            rules.project_id,
            rules.run_id,
            input_sha256=HASH_A,
            payload={
                "project_id": rules.project_id,
                "batch_id": rules.batch_id,
                "rule_pack_id": rules.rule_pack_revision,
                "candidates": [],
                "diagnostics": [],
                "analysis_complete": "false",
            },
            expected_version=rules.version,
            actor="orchestrator",
        )


def record_run_input(
    *,
    project_id: str = "proj-rux",
    batch_id: str = "batch-record",
    rule_identity_sha256: str = "e" * 64,
) -> DailyRunInput:
    return DailyRunInput(
        project_id=project_id,
        batch_id=batch_id,
        baseline_batch_id=None,
        batch_version=7,
        mapping_revision="mapping-v3",
        rule_pack_revision="",
        engine_version="monitoring-engine/2.0",
        diff_algorithm_version="monitoring-diff/2.0",
        rule_resolution_mode="record_applicability",
        rule_identity_sha256=rule_identity_sha256,
    )


def test_record_applicability_run_requires_and_persists_frozen_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)

    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="rule_identity_sha256 is required",
    ):
        record_run_input(rule_identity_sha256="").normalized()
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="must be a SHA-256 hex digest",
    ):
        record_run_input(rule_identity_sha256="not-a-hash").normalized()
    for malformed in (
        f" {'e' * 64}",
        f"{'e' * 64} ",
        "E" * 64,
        "g" * 64,
        "e" * 63,
        123,
    ):
        with pytest.raises(
            MonitoringDailyRunRepositoryError,
            match="must be a SHA-256 hex digest",
        ):
            record_run_input(rule_identity_sha256=malformed).normalized()
    with pytest.raises(
        MonitoringDailyRunRepositoryError,
        match="must not freeze a record rule identity",
    ):
        DailyRunInput(
            project_id="proj-rux",
            batch_id="batch-001",
            baseline_batch_id=None,
            batch_version=7,
            mapping_revision="mapping-v3",
            rule_pack_revision="rules-v5",
            engine_version="monitoring-engine/2.0",
            diff_algorithm_version="monitoring-diff/2.0",
            rule_identity_sha256="e" * 64,
        ).normalized()

    created = repository.create_or_get(
        record_run_input(),
        idempotency_key="record:1",
        actor="medical-manager",
    )
    assert created.replayed is False
    assert created.run.rule_resolution_mode == "record_applicability"
    assert created.run.rule_pack_revision == ""
    assert created.run.rule_identity_sha256 == "e" * 64
    assert created.run.to_dict()["rule_identity_sha256"] == "e" * 64

    replay = repository.create_or_get(
        record_run_input(),
        idempotency_key="record:1",
        actor="another-actor",
    )
    assert replay.replayed is True
    assert replay.run == created.run

    with pytest.raises(
        DailyRunIdempotencyConflictError,
        match="different request",
    ):
        repository.create_or_get(
            record_run_input(rule_identity_sha256="f" * 64),
            idempotency_key="record:1",
        )

    reopened = MonitoringDailyRunRepository(path)
    restored = reopened.get(created.run.project_id, created.run.run_id)
    assert restored.rule_identity_sha256 == "e" * 64
    assert restored.input_sha256 == created.run.input_sha256


def test_additive_rule_identity_migration_defaults_legacy_runs(
    tmp_path: Path,
) -> None:
    path = tmp_path / "daily.sqlite3"
    repository = MonitoringDailyRunRepository(path)
    created = repository.create_or_get(
        run_input(),
        idempotency_key="create:identity-migration",
    ).run

    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE monitoring_daily_runs "
            "DROP COLUMN rule_identity_sha256"
        )

    reopened = MonitoringDailyRunRepository(path)
    migrated = reopened.get(created.project_id, created.run_id)
    assert migrated.rule_identity_sha256 == ""
    with sqlite3.connect(path) as connection:
        run_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(monitoring_daily_runs)"
            )
        }
    assert "rule_identity_sha256" in run_columns
