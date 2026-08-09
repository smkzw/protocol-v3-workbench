from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_migration_contract import (
    MigrationObservationStatus,
    MigrationReconciliationStatus,
    MonitoringMigrationContractError,
    MonitoringMigrationLedger,
    MonitoringMigrationObservation,
    MonitoringMigrationSpec,
    build_migration_reconciliation_report,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
AUTH_HASH = "c" * 64


def _spec(
    migration_id: str = "monitoring-v16-to-v17",
    *,
    from_version: int = 16,
    to_version: int = 17,
    stores: tuple[str, ...] = ("ai", "risk"),
) -> MonitoringMigrationSpec:
    return MonitoringMigrationSpec(
        migration_id=migration_id,
        from_schema_version=from_version,
        to_schema_version=to_version,
        affected_store_ids=stores,
        preflight_check_ids=("integrity", "foreign_keys"),
        post_check_ids=("schema", "row_counts"),
        migration_sha256=HASH_A,
        rollback_sha256=HASH_B,
    )


def _ledger() -> MonitoringMigrationLedger:
    return MonitoringMigrationLedger(migrations=(_spec(),))


def _report(
    ledger: MonitoringMigrationLedger,
    versions: dict[str, int],
    observations: tuple[MonitoringMigrationObservation, ...] = (),
    *,
    authority_status: str = "pending_review",
    authority_write_permitted: bool = False,
):
    return build_migration_reconciliation_report(
        ledger,
        versions,
        observations,
        authority_status=authority_status,
        authority_write_permitted=authority_write_permitted,
        authority_evidence_sha256=AUTH_HASH,
    )


def test_ledger_is_sorted_hashed_and_covers_store_chain() -> None:
    later = _spec("monitoring-v17-to-v18", from_version=17, to_version=18)
    ledger = MonitoringMigrationLedger(migrations=(later, _spec()))

    assert [item.migration_id for item in ledger.migrations] == [
        "monitoring-v16-to-v17",
        "monitoring-v17-to-v18",
    ]
    assert ledger.store_ids == ("ai", "risk")
    assert len(ledger.ledger_sha256) == 64
    assert ledger.to_dict()["ledger_sha256"] == ledger.ledger_sha256


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"from_version": 17, "to_version": 17}, "to_schema_version"),
        ({"from_version": True, "to_version": 17}, "from_schema_version"),
        ({"from_version": 0, "to_version": True}, "to_schema_version"),
        ({"stores": ("ai", "ai")}, "must not repeat"),
    ],
)
def test_ledger_rejects_unsafe_spec_shape(kwargs, message: str) -> None:
    with pytest.raises(MonitoringMigrationContractError, match=message):
        _spec(**kwargs)


@pytest.mark.parametrize("field", ["migration_sha256", "rollback_sha256"])
@pytest.mark.parametrize("encoding", ["padded", "uppercase"])
def test_migration_spec_hash_requires_exact_lowercase_bytes(
    field: str, encoding: str
) -> None:
    spec = _spec()
    value = getattr(spec, field)
    invalid = f" {value}" if encoding == "padded" else value.upper()

    with pytest.raises(
        MonitoringMigrationContractError,
        match=f"{field} must be a lowercase SHA-256",
    ):
        replace(spec, **{field: invalid})


def test_migration_observation_backup_hash_requires_exact_lowercase_bytes() -> None:
    observation = MonitoringMigrationObservation(
        migration_id="monitoring-v16-to-v17",
        store_id="ai",
        status=MigrationObservationStatus.APPLIED,
        schema_version_before=16,
        schema_version_after=17,
        backup_id="backup-ai",
        backup_sha256=HASH_A,
        rollback_verified=True,
    )

    with pytest.raises(
        MonitoringMigrationContractError,
        match="observation.backup_sha256 must be a lowercase SHA-256",
    ):
        replace(observation, backup_sha256=f" {observation.backup_sha256}")


def test_migration_reconciliation_authority_hash_requires_exact_lowercase_bytes() -> None:
    with pytest.raises(
        MonitoringMigrationContractError,
        match="authority_evidence_sha256 must be a lowercase SHA-256",
    ):
        build_migration_reconciliation_report(
            _ledger(),
            {"ai": 16, "risk": 16},
            authority_status="pending_review",
            authority_write_permitted=False,
            authority_evidence_sha256=f" {AUTH_HASH}",
        )


def test_ledger_rejects_overlapping_store_intervals() -> None:
    with pytest.raises(MonitoringMigrationContractError, match="overlap"):
        MonitoringMigrationLedger(
            migrations=(
                _spec("m1", from_version=16, to_version=18),
                _spec("m2", from_version=17, to_version=19),
            )
        )


def test_pending_snapshot_is_blocked_by_current_authority_gate() -> None:
    report = _report(_ledger(), {"ai": 16, "risk": 16})

    assert report.status == MigrationReconciliationStatus.BLOCKED_PENDING_AUTHORITY
    assert report.decisions[0].status == "pending"
    assert report.write_permitted is False
    assert report.migration_write_permitted is False


def test_approved_authority_only_changes_read_only_decision() -> None:
    report = _report(
        _ledger(),
        {"ai": 16, "risk": 16},
        authority_status="approved",
        authority_write_permitted=True,
    )

    assert report.status == MigrationReconciliationStatus.PENDING_MIGRATION
    assert report.decisions[0].reason.startswith("no complete execution evidence")
    assert report.write_permitted is False
    assert report.migration_write_permitted is False


def test_verified_applied_evidence_produces_noop() -> None:
    observations = tuple(
        MonitoringMigrationObservation(
            migration_id="monitoring-v16-to-v17",
            store_id=store_id,
            status=MigrationObservationStatus.APPLIED,
            schema_version_before=16,
            schema_version_after=17,
            backup_id=f"backup-{store_id}",
            backup_sha256=HASH_A,
            rollback_verified=True,
        )
        for store_id in ("ai", "risk")
    )
    report = _report(
        _ledger(),
        {"ai": 17, "risk": 17},
        observations,
        authority_status="approved",
        authority_write_permitted=True,
    )

    assert report.status == MigrationReconciliationStatus.NOOP
    assert report.decisions[0].status == "applied"


def test_partial_failure_requires_manual_reconciliation() -> None:
    observations = (
        MonitoringMigrationObservation(
            migration_id="monitoring-v16-to-v17",
            store_id="ai",
            status=MigrationObservationStatus.APPLIED,
            schema_version_before=16,
            schema_version_after=17,
            backup_id="backup-ai",
            backup_sha256=HASH_A,
            rollback_verified=True,
        ),
        MonitoringMigrationObservation(
            migration_id="monitoring-v16-to-v17",
            store_id="risk",
            status=MigrationObservationStatus.FAILED,
            schema_version_before=16,
            schema_version_after=16,
            error_code="post_check_failed",
        ),
    )
    report = _report(
        _ledger(),
        {"ai": 17, "risk": 16},
        observations,
        authority_status="approved",
        authority_write_permitted=True,
    )

    assert report.status == MigrationReconciliationStatus.RECONCILE_REQUIRED
    assert report.decisions[0].status == "reconcile_required"
    assert report.write_permitted is False


def test_partial_terminal_evidence_is_not_downgraded_to_pending() -> None:
    applied = MonitoringMigrationObservation(
        migration_id="monitoring-v16-to-v17",
        store_id="ai",
        status=MigrationObservationStatus.APPLIED,
        schema_version_before=16,
        schema_version_after=17,
        backup_id="backup-ai",
        backup_sha256=HASH_A,
        rollback_verified=True,
    )
    report = _report(
        _ledger(),
        {"ai": 16, "risk": 16},
        (applied,),
        authority_status="approved",
        authority_write_permitted=True,
    )

    assert report.status == MigrationReconciliationStatus.RECONCILE_REQUIRED
    assert report.decisions[0].status == "reconcile_required"


def test_missing_store_duplicate_observation_and_unknown_migration_fail_closed() -> (
    None
):
    with pytest.raises(MonitoringMigrationContractError, match="exactly cover"):
        _report(_ledger(), {"ai": 16})

    duplicate = MonitoringMigrationObservation(
        migration_id="monitoring-v16-to-v17",
        store_id="ai",
        status="pending",
        schema_version_before=16,
        schema_version_after=16,
    )
    with pytest.raises(MonitoringMigrationContractError, match="duplicate"):
        _report(_ledger(), {"ai": 16, "risk": 16}, (duplicate, duplicate))

    unknown = MonitoringMigrationObservation(
        migration_id="not-in-ledger",
        store_id="ai",
        status="pending",
        schema_version_before=16,
        schema_version_after=16,
    )
    with pytest.raises(MonitoringMigrationContractError, match="unknown migration"):
        _report(_ledger(), {"ai": 16, "risk": 16}, (unknown,))

    with pytest.raises(MonitoringMigrationContractError, match="must contain"):
        _report(_ledger(), {"ai": 16, "risk": 16}, ({"not": "an observation"},))


def test_boolean_versions_fail_closed_in_observation_and_store_snapshot() -> None:
    with pytest.raises(MonitoringMigrationContractError, match="schema_version_before"):
        MonitoringMigrationObservation(
            migration_id="monitoring-v16-to-v17",
            store_id="ai",
            status="pending",
            schema_version_before=True,
            schema_version_after=16,
        )

    with pytest.raises(MonitoringMigrationContractError, match=r"store_versions\[ai\]"):
        _report(_ledger(), {"ai": True, "risk": 16})


def test_report_hash_is_stable_and_tamper_flags_remain_false() -> None:
    first = _report(_ledger(), {"ai": 16, "risk": 16})
    second = _report(_ledger(), {"ai": 16, "risk": 16})

    assert first.to_dict() == second.to_dict()
    assert first.report_sha256 == second.report_sha256
    with pytest.raises(MonitoringMigrationContractError, match="cannot grant"):
        type(first)(
            ledger_sha256=first.ledger_sha256,
            authority_status=first.authority_status,
            authority_evidence_sha256=first.authority_evidence_sha256,
            decisions=first.decisions,
            status=first.status,
            write_permitted=True,
        )
