"""Read-only migration ledger and startup reconciliation contract.

Phase G needs an explicit migration ledger before any monitoring database is
changed.  This module intentionally does not open SQLite, create backups, or
execute migrations.  It validates a versioned plan against an in-memory
startup snapshot and returns a deterministic decision that a future,
explicitly-authorized executor may consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


MIGRATION_LEDGER_SCHEMA_VERSION = "monitoring_migration_ledger_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class MonitoringMigrationContractError(ValueError):
    """Raised when a migration plan or startup snapshot is unsafe."""


class MigrationObservationStatus(str, Enum):
    APPLIED = "applied"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    PENDING = "pending"
    UNKNOWN = "unknown"


class MigrationReconciliationStatus(str, Enum):
    BLOCKED_PENDING_AUTHORITY = "blocked_pending_authority"
    PENDING_MIGRATION = "pending_migration"
    RECONCILE_REQUIRED = "reconcile_required"
    NOOP = "noop"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise MonitoringMigrationContractError(
            "migration contract payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise MonitoringMigrationContractError(f"{field_name} is required")
    if not _SAFE_ID_RE.fullmatch(text):
        raise MonitoringMigrationContractError(
            f"{field_name} contains unsupported characters"
        )
    return text


def _hash(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise MonitoringMigrationContractError(
            f"{field_name} must be a lowercase SHA-256"
        )
    return value


def _ids(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_required(value, f"{field_name} item") for value in values)
    if not normalized:
        raise MonitoringMigrationContractError(f"{field_name} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise MonitoringMigrationContractError(f"{field_name} must not repeat")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class MonitoringMigrationSpec:
    """One immutable, versioned migration declaration."""

    migration_id: str
    from_schema_version: int
    to_schema_version: int
    affected_store_ids: tuple[str, ...]
    preflight_check_ids: tuple[str, ...]
    post_check_ids: tuple[str, ...]
    migration_sha256: str
    rollback_sha256: str
    transaction_scope: str = "per_store"
    backup_required: bool = True
    rollback_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "migration_id", _required(self.migration_id, "migration_id")
        )
        if (
            not isinstance(self.from_schema_version, int)
            or isinstance(self.from_schema_version, bool)
            or self.from_schema_version < 0
        ):
            raise MonitoringMigrationContractError(
                "from_schema_version must be a non-negative integer"
            )
        if (
            not isinstance(self.to_schema_version, int)
            or isinstance(self.to_schema_version, bool)
            or self.to_schema_version <= self.from_schema_version
        ):
            raise MonitoringMigrationContractError(
                "to_schema_version must be greater than from_schema_version"
            )
        object.__setattr__(
            self,
            "affected_store_ids",
            _ids(self.affected_store_ids, "affected_store_ids"),
        )
        object.__setattr__(
            self,
            "preflight_check_ids",
            _ids(self.preflight_check_ids, "preflight_check_ids"),
        )
        object.__setattr__(
            self,
            "post_check_ids",
            _ids(self.post_check_ids, "post_check_ids"),
        )
        object.__setattr__(
            self, "migration_sha256", _hash(self.migration_sha256, "migration_sha256")
        )
        object.__setattr__(
            self, "rollback_sha256", _hash(self.rollback_sha256, "rollback_sha256")
        )
        if self.transaction_scope not in {"per_store", "all_stores"}:
            raise MonitoringMigrationContractError(
                "transaction_scope must be per_store or all_stores"
            )
        if self.backup_required is not True or self.rollback_required is not True:
            raise MonitoringMigrationContractError(
                "monitoring migrations require backup and rollback plans"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_id": self.migration_id,
            "from_schema_version": self.from_schema_version,
            "to_schema_version": self.to_schema_version,
            "affected_store_ids": list(self.affected_store_ids),
            "preflight_check_ids": list(self.preflight_check_ids),
            "post_check_ids": list(self.post_check_ids),
            "migration_sha256": self.migration_sha256,
            "rollback_sha256": self.rollback_sha256,
            "transaction_scope": self.transaction_scope,
            "backup_required": self.backup_required,
            "rollback_required": self.rollback_required,
        }


@dataclass(frozen=True)
class MonitoringMigrationLedger:
    """An immutable, deterministic plan spanning one or more stores."""

    migrations: tuple[MonitoringMigrationSpec, ...]
    schema_version: str = MIGRATION_LEDGER_SCHEMA_VERSION
    ledger_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MIGRATION_LEDGER_SCHEMA_VERSION:
            raise MonitoringMigrationContractError(
                "unsupported migration ledger schema version"
            )
        migrations = tuple(self.migrations)
        if not migrations:
            raise MonitoringMigrationContractError(
                "migration ledger must contain a migration"
            )
        if any(not isinstance(item, MonitoringMigrationSpec) for item in migrations):
            raise MonitoringMigrationContractError(
                "migration ledger contains an invalid spec"
            )
        migration_ids = tuple(item.migration_id for item in migrations)
        if len(migration_ids) != len(set(migration_ids)):
            raise MonitoringMigrationContractError("migration IDs must not repeat")

        by_store: dict[str, list[MonitoringMigrationSpec]] = {}
        for migration in migrations:
            for store_id in migration.affected_store_ids:
                by_store.setdefault(store_id, []).append(migration)
        for store_id, store_migrations in by_store.items():
            ordered = sorted(
                store_migrations,
                key=lambda item: (
                    item.from_schema_version,
                    item.to_schema_version,
                    item.migration_id,
                ),
            )
            for previous, current in zip(ordered, ordered[1:]):
                if current.from_schema_version < previous.to_schema_version:
                    raise MonitoringMigrationContractError(
                        f"migration intervals overlap for store {store_id}"
                    )

        ordered_migrations = tuple(
            sorted(
                migrations,
                key=lambda item: (
                    item.from_schema_version,
                    item.to_schema_version,
                    item.migration_id,
                ),
            )
        )
        object.__setattr__(self, "migrations", ordered_migrations)
        object.__setattr__(self, "ledger_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "migrations": [item.to_dict() for item in self.migrations],
        }

    @property
    def store_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    store_id
                    for migration in self.migrations
                    for store_id in migration.affected_store_ids
                }
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "ledger_sha256": self.ledger_sha256}


@dataclass(frozen=True)
class MonitoringMigrationObservation:
    """Read-only evidence from a prior migration attempt."""

    migration_id: str
    store_id: str
    status: MigrationObservationStatus | str
    schema_version_before: int
    schema_version_after: int
    backup_id: str = ""
    backup_sha256: str = ""
    rollback_verified: bool = False
    error_code: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "migration_id",
            _required(self.migration_id, "observation.migration_id"),
        )
        object.__setattr__(
            self, "store_id", _required(self.store_id, "observation.store_id")
        )
        try:
            status = MigrationObservationStatus(self.status)
        except ValueError as exc:
            raise MonitoringMigrationContractError(
                "observation.status is unsupported"
            ) from exc
        object.__setattr__(self, "status", status)
        for name, value in (
            ("schema_version_before", self.schema_version_before),
            ("schema_version_after", self.schema_version_after),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise MonitoringMigrationContractError(
                    f"observation.{name} must be non-negative"
                )
        if self.schema_version_after < self.schema_version_before and status not in {
            MigrationObservationStatus.ROLLED_BACK,
            MigrationObservationStatus.FAILED,
        }:
            raise MonitoringMigrationContractError(
                "only failed or rolled_back observations may move backwards"
            )
        backup_id = str(self.backup_id or "").strip()
        if backup_id:
            object.__setattr__(
                self, "backup_id", _required(backup_id, "observation.backup_id")
            )
        if self.backup_sha256:
            object.__setattr__(
                self,
                "backup_sha256",
                _hash(self.backup_sha256, "observation.backup_sha256"),
            )
        error_code = str(self.error_code or "").strip()
        if error_code:
            object.__setattr__(
                self, "error_code", _required(error_code, "observation.error_code")
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_id": self.migration_id,
            "store_id": self.store_id,
            "status": self.status.value,
            "schema_version_before": self.schema_version_before,
            "schema_version_after": self.schema_version_after,
            "backup_id": self.backup_id,
            "backup_sha256": self.backup_sha256,
            "rollback_verified": self.rollback_verified,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class MonitoringMigrationDecision:
    migration_id: str
    status: str
    reason: str
    affected_store_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "migration_id": self.migration_id,
            "status": self.status,
            "reason": self.reason,
            "affected_store_ids": list(self.affected_store_ids),
        }


@dataclass(frozen=True)
class MonitoringMigrationReconciliationReport:
    """Deterministic startup decision; this report never grants write access."""

    ledger_sha256: str
    authority_status: str
    authority_evidence_sha256: str
    decisions: tuple[MonitoringMigrationDecision, ...]
    status: MigrationReconciliationStatus
    write_permitted: bool = False
    migration_write_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "ledger_sha256", _hash(self.ledger_sha256, "ledger_sha256")
        )
        object.__setattr__(
            self,
            "authority_status",
            _required(self.authority_status, "authority_status"),
        )
        object.__setattr__(
            self,
            "authority_evidence_sha256",
            _hash(self.authority_evidence_sha256, "authority_evidence_sha256"),
        )
        decisions = tuple(self.decisions)
        if len({item.migration_id for item in decisions}) != len(decisions):
            raise MonitoringMigrationContractError(
                "reconciliation decisions must not repeat migrations"
            )
        if self.write_permitted or self.migration_write_permitted:
            raise MonitoringMigrationContractError(
                "reconciliation report cannot grant database write access"
            )
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "ledger_sha256": self.ledger_sha256,
            "authority_status": self.authority_status,
            "authority_evidence_sha256": self.authority_evidence_sha256,
            "decisions": [item.to_dict() for item in self.decisions],
            "status": self.status.value,
            "write_permitted": self.write_permitted,
            "migration_write_permitted": self.migration_write_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def _validate_store_versions(
    ledger: MonitoringMigrationLedger,
    store_versions: Mapping[str, int],
) -> dict[str, int]:
    if not isinstance(store_versions, Mapping):
        raise MonitoringMigrationContractError("store_versions must be an object")
    normalized = {}
    for raw_store_id, version in store_versions.items():
        store_id = _required(raw_store_id, "store_versions store_id")
        if not isinstance(version, int) or isinstance(version, bool) or version < 0:
            raise MonitoringMigrationContractError(
                f"store_versions[{store_id}] must be a non-negative integer"
            )
        normalized[store_id] = version
    expected = set(ledger.store_ids)
    actual = set(normalized)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise MonitoringMigrationContractError(
            f"store_versions must exactly cover ledger stores; missing={missing}, extra={extra}"
        )
    return normalized


def _validate_observations(
    ledger: MonitoringMigrationLedger,
    observations: tuple[MonitoringMigrationObservation, ...],
) -> dict[tuple[str, str], MonitoringMigrationObservation]:
    known_migrations = {item.migration_id: item for item in ledger.migrations}
    index: dict[tuple[str, str], MonitoringMigrationObservation] = {}
    for observation in observations:
        if not isinstance(observation, MonitoringMigrationObservation):
            raise MonitoringMigrationContractError(
                "migration observations must contain MonitoringMigrationObservation values"
            )
        key = (observation.migration_id, observation.store_id)
        if key in index:
            raise MonitoringMigrationContractError(
                f"duplicate migration observation: {observation.migration_id}/{observation.store_id}"
            )
        migration = known_migrations.get(observation.migration_id)
        if migration is None:
            raise MonitoringMigrationContractError(
                f"observation references unknown migration: {observation.migration_id}"
            )
        if observation.store_id not in migration.affected_store_ids:
            raise MonitoringMigrationContractError(
                f"observation store is outside migration scope: {observation.store_id}"
            )
        index[key] = observation
    return index


def _decision_for_migration(
    migration: MonitoringMigrationSpec,
    store_versions: Mapping[str, int],
    observation_index: Mapping[tuple[str, str], MonitoringMigrationObservation],
) -> MonitoringMigrationDecision:
    observations = [
        observation_index.get((migration.migration_id, store_id))
        for store_id in migration.affected_store_ids
    ]
    if any(item is None for item in observations):
        if any(
            item is not None
            and item.status
            not in {
                MigrationObservationStatus.PENDING,
                MigrationObservationStatus.UNKNOWN,
            }
            for item in observations
        ):
            return MonitoringMigrationDecision(
                migration_id=migration.migration_id,
                status="reconcile_required",
                reason="terminal execution evidence is incomplete for one or more affected stores",
                affected_store_ids=migration.affected_store_ids,
            )
        if all(
            store_versions[store_id] == migration.from_schema_version
            for store_id in migration.affected_store_ids
        ):
            return MonitoringMigrationDecision(
                migration_id=migration.migration_id,
                status="pending",
                reason="no complete execution evidence; every store is at the declared source version",
                affected_store_ids=migration.affected_store_ids,
            )
        return MonitoringMigrationDecision(
            migration_id=migration.migration_id,
            status="reconcile_required",
            reason="execution evidence is incomplete and store versions are not uniformly at the source version",
            affected_store_ids=migration.affected_store_ids,
        )

    complete = tuple(item for item in observations if item is not None)
    if any(
        item.status == MigrationObservationStatus.APPLIED
        and (
            item.schema_version_before != migration.from_schema_version
            or item.schema_version_after != migration.to_schema_version
            or not item.backup_id
            or not item.backup_sha256
            or not item.rollback_verified
        )
        for item in complete
    ):
        return MonitoringMigrationDecision(
            migration_id=migration.migration_id,
            status="reconcile_required",
            reason="applied evidence is missing source/target, backup, or verified rollback fields",
            affected_store_ids=migration.affected_store_ids,
        )
    if any(
        item.status
        in {
            MigrationObservationStatus.FAILED,
            MigrationObservationStatus.PENDING,
            MigrationObservationStatus.UNKNOWN,
        }
        for item in complete
    ):
        if any(
            item.status == MigrationObservationStatus.FAILED and not item.error_code
            for item in complete
        ):
            reason = "failed migration evidence lacks an error code"
        else:
            reason = "migration has failed, pending, or unknown execution evidence"
        return MonitoringMigrationDecision(
            migration_id=migration.migration_id,
            status="reconcile_required",
            reason=reason,
            affected_store_ids=migration.affected_store_ids,
        )
    if any(
        item.status == MigrationObservationStatus.ROLLED_BACK
        and (
            item.schema_version_before != migration.from_schema_version
            or item.schema_version_after != migration.from_schema_version
            or not item.backup_id
            or not item.backup_sha256
            or not item.rollback_verified
        )
        for item in complete
    ):
        return MonitoringMigrationDecision(
            migration_id=migration.migration_id,
            status="reconcile_required",
            reason="rollback evidence is incomplete or store is not proven at the source version",
            affected_store_ids=migration.affected_store_ids,
        )
    if all(item.status == MigrationObservationStatus.APPLIED for item in complete):
        if all(
            store_versions[store_id] == migration.to_schema_version
            for store_id in migration.affected_store_ids
        ):
            return MonitoringMigrationDecision(
                migration_id=migration.migration_id,
                status="applied",
                reason="all affected stores match the verified migration target version",
                affected_store_ids=migration.affected_store_ids,
            )
        return MonitoringMigrationDecision(
            migration_id=migration.migration_id,
            status="reconcile_required",
            reason="applied evidence conflicts with one or more current store versions",
            affected_store_ids=migration.affected_store_ids,
        )
    return MonitoringMigrationDecision(
        migration_id=migration.migration_id,
        status="reconcile_required",
        reason="migration observations do not form a uniform terminal state",
        affected_store_ids=migration.affected_store_ids,
    )


def build_migration_reconciliation_report(
    ledger: MonitoringMigrationLedger,
    store_versions: Mapping[str, int],
    observations: tuple[MonitoringMigrationObservation, ...] = (),
    *,
    authority_status: str,
    authority_write_permitted: bool,
    authority_evidence_sha256: str,
) -> MonitoringMigrationReconciliationReport:
    """Build a read-only startup decision from a versioned migration ledger.

    ``authority_write_permitted`` is an input assertion, not a grant.  The
    returned report always has both write flags set to ``False``; an eventual
    executor must perform a separate authorization and rollback check.
    """

    if not isinstance(ledger, MonitoringMigrationLedger):
        raise MonitoringMigrationContractError(
            "ledger must be a MonitoringMigrationLedger"
        )
    versions = _validate_store_versions(ledger, store_versions)
    observation_index = _validate_observations(ledger, tuple(observations))
    authority = _required(authority_status, "authority_status")
    authority_hash = _hash(authority_evidence_sha256, "authority_evidence_sha256")
    decisions = tuple(
        _decision_for_migration(migration, versions, observation_index)
        for migration in ledger.migrations
    )

    if authority != "approved" or authority_write_permitted is not True:
        status = MigrationReconciliationStatus.BLOCKED_PENDING_AUTHORITY
    elif any(item.status == "reconcile_required" for item in decisions):
        status = MigrationReconciliationStatus.RECONCILE_REQUIRED
    elif any(item.status == "pending" for item in decisions):
        status = MigrationReconciliationStatus.PENDING_MIGRATION
    else:
        status = MigrationReconciliationStatus.NOOP
    return MonitoringMigrationReconciliationReport(
        ledger_sha256=ledger.ledger_sha256,
        authority_status=authority,
        authority_evidence_sha256=authority_hash,
        decisions=decisions,
        status=status,
    )


__all__ = [
    "MIGRATION_LEDGER_SCHEMA_VERSION",
    "MigrationObservationStatus",
    "MigrationReconciliationStatus",
    "MonitoringMigrationContractError",
    "MonitoringMigrationDecision",
    "MonitoringMigrationLedger",
    "MonitoringMigrationObservation",
    "MonitoringMigrationReconciliationReport",
    "MonitoringMigrationSpec",
    "build_migration_reconciliation_report",
]
