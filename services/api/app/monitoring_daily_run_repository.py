from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping, Optional
from uuid import uuid4


RUN_STATES = (
    "prepared",
    "diffing",
    "drift_review_required",
    "rules_running",
    "ai_running",
    "analysis_partial",
    "risk_review",
    "ready_to_confirm",
    "confirmed",
    "superseded",
)
ACTIVE_RUN_STATES = frozenset(RUN_STATES) - {
    "confirmed",
    "drift_review_required",
    "superseded",
}
STEP_STATES = ("running", "completed", "failed", "skipped")
RULE_RESOLUTION_MODES = ("project_effective", "record_applicability")
_NEXT_STATES = {
    "prepared": frozenset({"diffing", "rules_running"}),
    "diffing": frozenset({"drift_review_required", "rules_running"}),
    "drift_review_required": frozenset({"superseded"}),
    "rules_running": frozenset({"ai_running", "analysis_partial", "risk_review"}),
    "ai_running": frozenset({"analysis_partial", "risk_review"}),
    "analysis_partial": frozenset({"risk_review"}),
    "risk_review": frozenset({"ready_to_confirm"}),
    "ready_to_confirm": frozenset(),
    "confirmed": frozenset(),
    "superseded": frozenset(),
}


class MonitoringDailyRunRepositoryError(ValueError):
    pass


class DailyRunNotFoundError(MonitoringDailyRunRepositoryError):
    pass


class DailyRunIdempotencyConflictError(MonitoringDailyRunRepositoryError):
    pass


class DailyRunActiveConflictError(MonitoringDailyRunRepositoryError):
    pass


class DailyRunVersionConflictError(MonitoringDailyRunRepositoryError):
    pass


class DailyRunStateConflictError(MonitoringDailyRunRepositoryError):
    pass


class DailyRunLeaseConflictError(MonitoringDailyRunRepositoryError):
    pass


class DailyRunOutputConflictError(MonitoringDailyRunRepositoryError):
    pass


class DailyRunBaselineConflictError(MonitoringDailyRunRepositoryError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat() if value is not None else ""


def _datetime(value: str) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _content_sha256(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MonitoringDailyRunRepositoryError(f"{field} is required")
    return normalized


def _optional_text(value: Any) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _require_sha256(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise MonitoringDailyRunRepositoryError(f"{field} must be a SHA-256 hex digest")
    return value


@dataclass(frozen=True)
class DailyRunInput:
    project_id: str
    batch_id: str
    baseline_batch_id: Optional[str]
    batch_version: int
    mapping_revision: str
    rule_pack_revision: str
    engine_version: str
    diff_algorithm_version: str
    rule_resolution_mode: str = "project_effective"
    rule_identity_sha256: str = ""

    def normalized(self) -> "DailyRunInput":
        if int(self.batch_version) < 1:
            raise MonitoringDailyRunRepositoryError("batch_version must be at least 1")
        project_id = _required_text(self.project_id, "project_id")
        batch_id = _required_text(self.batch_id, "batch_id")
        baseline_batch_id = _optional_text(self.baseline_batch_id)
        if baseline_batch_id == batch_id:
            raise MonitoringDailyRunRepositoryError(
                "baseline_batch_id must differ from batch_id"
            )
        rule_resolution_mode = _required_text(
            self.rule_resolution_mode,
            "rule_resolution_mode",
        ).lower()
        if rule_resolution_mode not in RULE_RESOLUTION_MODES:
            raise MonitoringDailyRunRepositoryError(
                "rule_resolution_mode is not supported"
            )
        rule_pack_revision = str(self.rule_pack_revision or "").strip()
        if rule_resolution_mode == "project_effective" and not rule_pack_revision:
            raise MonitoringDailyRunRepositoryError(
                "rule_pack_revision is required for project_effective resolution"
            )
        if rule_resolution_mode == "record_applicability" and rule_pack_revision:
            raise MonitoringDailyRunRepositoryError(
                "record_applicability resolution must not preselect one rule pack"
            )
        rule_identity_sha256 = self.rule_identity_sha256 or ""
        if rule_identity_sha256:
            rule_identity_sha256 = _require_sha256(
                rule_identity_sha256,
                "rule_identity_sha256",
            )
        if (
            rule_resolution_mode == "record_applicability"
            and not rule_identity_sha256
        ):
            raise MonitoringDailyRunRepositoryError(
                "rule_identity_sha256 is required for record_applicability resolution"
            )
        if rule_resolution_mode == "project_effective" and rule_identity_sha256:
            raise MonitoringDailyRunRepositoryError(
                "project_effective resolution must not freeze a record rule identity"
            )
        return DailyRunInput(
            project_id=project_id,
            batch_id=batch_id,
            baseline_batch_id=baseline_batch_id,
            batch_version=int(self.batch_version),
            mapping_revision=_required_text(
                self.mapping_revision,
                "mapping_revision",
            ),
            rule_pack_revision=rule_pack_revision,
            engine_version=_required_text(self.engine_version, "engine_version"),
            diff_algorithm_version=_required_text(
                self.diff_algorithm_version,
                "diff_algorithm_version",
            ),
            rule_resolution_mode=rule_resolution_mode,
            rule_identity_sha256=rule_identity_sha256,
        )

    @property
    def input_sha256(self) -> str:
        return _content_sha256(asdict(self.normalized()))


@dataclass(frozen=True)
class MonitoringDailyRun:
    run_id: str
    project_id: str
    batch_id: str
    baseline_batch_id: Optional[str]
    batch_version: int
    mapping_revision: str
    rule_pack_revision: str
    engine_version: str
    diff_algorithm_version: str
    input_sha256: str
    status: str
    version: int
    diff_snapshot_id: Optional[str]
    rule_snapshot_id: Optional[str]
    risk_snapshot_id: Optional[str]
    lease_owner: Optional[str]
    lease_expires_at: Optional[datetime]
    lease_epoch: int
    claim_count: int
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime]
    confirmed_by: Optional[str]
    rule_resolution_mode: str = "project_effective"
    rule_identity_sha256: str = ""

    @property
    def is_initial_baseline(self) -> bool:
        return self.baseline_batch_id is None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for field in ("lease_expires_at", "created_at", "updated_at", "confirmed_at"):
            payload[field] = _iso(payload[field])
        return payload


@dataclass(frozen=True)
class DailyRunMutationResult:
    run: MonitoringDailyRun
    replayed: bool


@dataclass(frozen=True)
class MonitoringDailyRunStep:
    run_id: str
    step_name: str
    status: str
    attempt_count: int
    lease_epoch: int
    input_sha256: str
    output_sha256: Optional[str]
    details: dict[str, Any]
    started_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime]


@dataclass(frozen=True)
class DailyRunStepMutationResult:
    step: MonitoringDailyRunStep
    replayed: bool


@dataclass(frozen=True)
class MonitoringDailyRunEvent:
    event_seq: int
    run_id: str
    project_id: str
    run_version: int
    event_type: str
    actor: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class MonitoringDiffSnapshot:
    snapshot_id: str
    run_id: str
    project_id: str
    previous_batch_id: str
    current_batch_id: str
    algorithm_version: str
    input_sha256: str
    output_sha256: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class DailyRunDiffMutationResult:
    run: MonitoringDailyRun
    snapshot: MonitoringDiffSnapshot
    replayed: bool


@dataclass(frozen=True)
class MonitoringRuleSnapshot:
    snapshot_id: str
    run_id: str
    project_id: str
    batch_id: str
    rule_pack_id: str
    engine_version: str
    input_sha256: str
    output_sha256: str
    payload: dict[str, Any]
    created_at: datetime
    resolution_mode: str = "project_effective"


@dataclass(frozen=True)
class DailyRunRuleMutationResult:
    run: MonitoringDailyRun
    snapshot: MonitoringRuleSnapshot
    replayed: bool


@dataclass(frozen=True)
class ProjectMonitoringBaseline:
    project_id: str
    current_baseline_batch_id: str
    confirmed_run_id: str
    revision: int
    confirmed_at: datetime
    confirmed_by: str


@dataclass(frozen=True)
class DailyRunConfirmationResult:
    run: MonitoringDailyRun
    baseline: ProjectMonitoringBaseline


class MonitoringDailyRunRepository:
    """Durable P7 run ledger, separate from ingestion and risk repositories."""

    def __init__(
        self,
        db_path: Path,
        *,
        lease_seconds: int = 300,
        clock=_utc_now,
    ):
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lease_seconds = int(lease_seconds)
        self.clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        state_values = ", ".join(f"'{state}'" for state in RUN_STATES)
        step_values = ", ".join(f"'{state}'" for state in STEP_STATES)
        statements = (
            f"""
            CREATE TABLE IF NOT EXISTS monitoring_daily_runs (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                baseline_batch_id TEXT,
                batch_version INTEGER NOT NULL CHECK(batch_version >= 1),
                mapping_revision TEXT NOT NULL,
                rule_pack_revision TEXT NOT NULL,
                rule_resolution_mode TEXT NOT NULL DEFAULT 'project_effective',
                rule_identity_sha256 TEXT NOT NULL DEFAULT '',
                engine_version TEXT NOT NULL,
                diff_algorithm_version TEXT NOT NULL,
                input_sha256 TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ({state_values})),
                version INTEGER NOT NULL CHECK(version >= 1),
                diff_snapshot_id TEXT,
                rule_snapshot_id TEXT,
                risk_snapshot_id TEXT,
                lease_owner TEXT NOT NULL DEFAULT '',
                lease_expires_at TEXT NOT NULL DEFAULT '',
                lease_epoch INTEGER NOT NULL DEFAULT 0 CHECK(lease_epoch >= 0),
                claim_count INTEGER NOT NULL DEFAULT 0 CHECK(claim_count >= 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confirmed_at TEXT NOT NULL DEFAULT '',
                confirmed_by TEXT NOT NULL DEFAULT ''
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS monitoring_daily_run_steps (
                run_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ({step_values})),
                attempt_count INTEGER NOT NULL CHECK(attempt_count >= 1),
                lease_epoch INTEGER NOT NULL DEFAULT 0 CHECK(lease_epoch >= 0),
                input_sha256 TEXT NOT NULL,
                output_sha256 TEXT NOT NULL DEFAULT '',
                details_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(run_id, step_name),
                FOREIGN KEY(run_id) REFERENCES monitoring_daily_runs(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_daily_run_events (
                event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                run_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES monitoring_daily_runs(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_daily_diff_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                project_id TEXT NOT NULL,
                previous_batch_id TEXT NOT NULL,
                current_batch_id TEXT NOT NULL,
                algorithm_version TEXT NOT NULL,
                input_sha256 TEXT NOT NULL,
                output_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES monitoring_daily_runs(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_daily_rule_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL UNIQUE,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                rule_pack_id TEXT NOT NULL,
                resolution_mode TEXT NOT NULL DEFAULT 'project_effective',
                engine_version TEXT NOT NULL,
                input_sha256 TEXT NOT NULL,
                output_sha256 TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES monitoring_daily_runs(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_project_baselines (
                project_id TEXT PRIMARY KEY,
                current_baseline_batch_id TEXT NOT NULL,
                confirmed_run_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                confirmed_at TEXT NOT NULL,
                confirmed_by TEXT NOT NULL,
                FOREIGN KEY(confirmed_run_id)
                    REFERENCES monitoring_daily_runs(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_daily_run_idempotency (
                project_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, idempotency_key),
                FOREIGN KEY(run_id) REFERENCES monitoring_daily_runs(run_id)
            )
            """,
            """
            DROP INDEX IF EXISTS idx_monitoring_daily_one_active_project
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_monitoring_daily_one_active_project
            ON monitoring_daily_runs(project_id)
            WHERE status NOT IN ('confirmed', 'drift_review_required', 'superseded')
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_daily_run_queue
            ON monitoring_daily_runs(status, lease_expires_at, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_daily_run_events
            ON monitoring_daily_run_events(run_id, event_seq)
            """,
        )
        with self._transaction() as connection:
            for statement in statements:
                connection.execute(statement)
            step_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_daily_run_steps)"
                ).fetchall()
            }
            if "lease_epoch" not in step_columns:
                connection.execute(
                    "ALTER TABLE monitoring_daily_run_steps "
                    "ADD COLUMN lease_epoch INTEGER NOT NULL DEFAULT 0"
                )
            run_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_daily_runs)"
                ).fetchall()
            }
            if "rule_snapshot_id" not in run_columns:
                connection.execute(
                    "ALTER TABLE monitoring_daily_runs ADD COLUMN rule_snapshot_id TEXT"
                )
            if "rule_resolution_mode" not in run_columns:
                connection.execute(
                    "ALTER TABLE monitoring_daily_runs "
                    "ADD COLUMN rule_resolution_mode TEXT NOT NULL "
                    "DEFAULT 'project_effective'"
                )
            if "rule_identity_sha256" not in run_columns:
                connection.execute(
                    "ALTER TABLE monitoring_daily_runs "
                    "ADD COLUMN rule_identity_sha256 TEXT NOT NULL DEFAULT ''"
                )
            snapshot_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_daily_rule_snapshots)"
                ).fetchall()
            }
            if "resolution_mode" not in snapshot_columns:
                connection.execute(
                    "ALTER TABLE monitoring_daily_rule_snapshots "
                    "ADD COLUMN resolution_mode TEXT NOT NULL "
                    "DEFAULT 'project_effective'"
                )
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise RuntimeError("monitoring daily-run repository integrity check failed")

    def create_or_get(
        self,
        run_input: DailyRunInput,
        *,
        idempotency_key: str,
        actor: str = "system",
    ) -> DailyRunMutationResult:
        normalized = run_input.normalized()
        key = _required_text(idempotency_key, "idempotency_key")
        actor = _required_text(actor, "actor")
        request_sha256 = _content_sha256(
            {
                "operation": "create_daily_run",
                "input": asdict(normalized),
            }
        )
        now = self.clock()
        with self._transaction() as connection:
            replay = connection.execute(
                """
                SELECT operation, request_sha256, run_id
                FROM monitoring_daily_run_idempotency
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (normalized.project_id, key),
            ).fetchone()
            if replay is not None:
                if (
                    replay["operation"] != "create_daily_run"
                    or replay["request_sha256"] != request_sha256
                ):
                    raise DailyRunIdempotencyConflictError(
                        "idempotency key is already bound to a different request"
                    )
                row = self._run_row(connection, replay["run_id"])
                return DailyRunMutationResult(self._run(row), True)

            active = connection.execute(
                f"""
                SELECT run_id FROM monitoring_daily_runs
                WHERE project_id = ?
                  AND status IN ({",".join("?" for _ in ACTIVE_RUN_STATES)})
                """,
                (normalized.project_id, *ACTIVE_RUN_STATES),
            ).fetchone()
            if active is not None:
                raise DailyRunActiveConflictError(
                    f"project already has active run {active['run_id']}"
                )

            run_id = f"monrun_{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO monitoring_daily_runs(
                    run_id, project_id, batch_id, baseline_batch_id,
                    batch_version, mapping_revision, rule_pack_revision,
                    rule_resolution_mode, rule_identity_sha256, engine_version,
                    diff_algorithm_version, input_sha256,
                    status, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'prepared', 1, ?, ?)
                """,
                (
                    run_id,
                    normalized.project_id,
                    normalized.batch_id,
                    normalized.baseline_batch_id,
                    normalized.batch_version,
                    normalized.mapping_revision,
                    normalized.rule_pack_revision,
                    normalized.rule_resolution_mode,
                    normalized.rule_identity_sha256,
                    normalized.engine_version,
                    normalized.diff_algorithm_version,
                    normalized.input_sha256,
                    _iso(now),
                    _iso(now),
                ),
            )
            connection.execute(
                """
                INSERT INTO monitoring_daily_run_idempotency(
                    project_id, idempotency_key, operation,
                    request_sha256, run_id, created_at
                ) VALUES (?, ?, 'create_daily_run', ?, ?, ?)
                """,
                (
                    normalized.project_id,
                    key,
                    request_sha256,
                    run_id,
                    _iso(now),
                ),
            )
            self._append_event(
                connection,
                run_id=run_id,
                project_id=normalized.project_id,
                run_version=1,
                event_type="run_created",
                actor=actor,
                payload={
                    "input_sha256": normalized.input_sha256,
                    "initial_baseline": normalized.baseline_batch_id is None,
                },
                created_at=now,
            )
            return DailyRunMutationResult(
                self._run(self._run_row(connection, run_id)),
                False,
            )

    def get(self, project_id: str, run_id: str) -> MonitoringDailyRun:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_daily_runs
                WHERE project_id = ? AND run_id = ?
                """,
                (
                    _required_text(project_id, "project_id"),
                    _required_text(run_id, "run_id"),
                ),
            ).fetchone()
        if row is None:
            raise DailyRunNotFoundError("monitoring daily run not found")
        return self._run(row)

    def list_runs(self, project_id: str) -> tuple[MonitoringDailyRun, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitoring_daily_runs
                WHERE project_id = ?
                ORDER BY created_at, run_id
                """,
                (_required_text(project_id, "project_id"),),
            ).fetchall()
        return tuple(self._run(row) for row in rows)

    def active_run(self, project_id: str) -> Optional[MonitoringDailyRun]:
        placeholders = ",".join("?" for _ in ACTIVE_RUN_STATES)
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM monitoring_daily_runs
                WHERE project_id = ? AND status IN ({placeholders})
                ORDER BY created_at DESC, run_id DESC
                LIMIT 1
                """,
                (
                    _required_text(project_id, "project_id"),
                    *ACTIVE_RUN_STATES,
                ),
            ).fetchone()
        return self._run(row) if row is not None else None

    def current_baseline(self, project_id: str) -> Optional[ProjectMonitoringBaseline]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_project_baselines
                WHERE project_id = ?
                """,
                (_required_text(project_id, "project_id"),),
            ).fetchone()
        return self._baseline(row) if row is not None else None

    def get_diff_snapshot(
        self,
        project_id: str,
        run_id: str,
    ) -> Optional[MonitoringDiffSnapshot]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot.*,
                       run.run_id AS run_run_id,
                       run.project_id AS run_project_id,
                       run.baseline_batch_id AS run_baseline_batch_id,
                       run.batch_id AS run_batch_id,
                       run.diff_algorithm_version AS run_diff_algorithm_version
                FROM monitoring_daily_diff_snapshots AS snapshot
                JOIN monitoring_daily_runs AS run ON run.run_id = snapshot.run_id
                WHERE snapshot.project_id = ? AND snapshot.run_id = ?
                  AND run.project_id = snapshot.project_id
                """,
                (
                    _required_text(project_id, "project_id"),
                    _required_text(run_id, "run_id"),
                ),
            ).fetchone()
        return self._diff(row) if row is not None else None

    def get_rule_snapshot(
        self,
        project_id: str,
        run_id: str,
    ) -> Optional[MonitoringRuleSnapshot]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot.*,
                       run.run_id AS run_run_id,
                       run.project_id AS run_project_id,
                       run.batch_id AS run_batch_id,
                       run.rule_pack_revision AS run_rule_pack_revision,
                       run.rule_resolution_mode AS run_rule_resolution_mode,
                       run.engine_version AS run_engine_version
                FROM monitoring_daily_rule_snapshots AS snapshot
                JOIN monitoring_daily_runs AS run ON run.run_id = snapshot.run_id
                WHERE snapshot.project_id = ? AND snapshot.run_id = ?
                  AND run.project_id = snapshot.project_id
                """,
                (
                    _required_text(project_id, "project_id"),
                    _required_text(run_id, "run_id"),
                ),
            ).fetchone()
        return self._rule_snapshot(row) if row is not None else None

    def list_events(self, run_id: str) -> tuple[MonitoringDailyRunEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitoring_daily_run_events
                WHERE run_id = ?
                ORDER BY event_seq
                """,
                (_required_text(run_id, "run_id"),),
            ).fetchall()
        return tuple(self._event(row) for row in rows)

    def list_steps(self, run_id: str) -> tuple[MonitoringDailyRunStep, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitoring_daily_run_steps
                WHERE run_id = ?
                ORDER BY started_at, step_name
                """,
                (_required_text(run_id, "run_id"),),
            ).fetchall()
        return tuple(self._step(row) for row in rows)

    def claim(
        self,
        project_id: str,
        run_id: str,
        *,
        owner: str,
        expected_version: Optional[int] = None,
    ) -> MonitoringDailyRun:
        owner = _required_text(owner, "owner")
        now = self.clock()
        expires_at = now + timedelta(seconds=self.lease_seconds)
        with self._transaction() as connection:
            row = self._project_run_row(connection, project_id, run_id)
            self._assert_active(row)
            if expected_version is not None and int(row["version"]) != int(expected_version):
                raise DailyRunVersionConflictError("run version CAS conflict")
            if row["lease_owner"] and row["lease_expires_at"] >= _iso(now):
                raise DailyRunLeaseConflictError("run already has an active lease")
            next_version = int(row["version"]) + 1
            next_epoch = int(row["lease_epoch"]) + 1
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET lease_owner = ?, lease_expires_at = ?,
                    lease_epoch = ?, claim_count = claim_count + 1,
                    version = ?, updated_at = ?
                WHERE run_id = ? AND version = ?
                """,
                (
                    owner,
                    _iso(expires_at),
                    next_epoch,
                    next_version,
                    _iso(now),
                    row["run_id"],
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunVersionConflictError("run claim lost version CAS")
            self._append_event(
                connection,
                run_id=row["run_id"],
                project_id=row["project_id"],
                run_version=next_version,
                event_type="run_claimed",
                actor=owner,
                payload={"lease_epoch": next_epoch, "reclaimed": bool(row["lease_owner"])},
                created_at=now,
            )
            return self._run(self._run_row(connection, row["run_id"]))

    def claim_next(
        self,
        *,
        owner: str,
        project_id: Optional[str] = None,
    ) -> Optional[MonitoringDailyRun]:
        owner = _required_text(owner, "owner")
        now = self.clock()
        expires_at = now + timedelta(seconds=self.lease_seconds)
        project_clause = ""
        parameters: list[Any] = list(ACTIVE_RUN_STATES)
        if project_id is not None:
            project_clause = " AND project_id = ?"
            parameters.append(_required_text(project_id, "project_id"))
        parameters.extend((_iso(now),))
        placeholders = ",".join("?" for _ in ACTIVE_RUN_STATES)
        with self._transaction() as connection:
            row = connection.execute(
                f"""
                SELECT * FROM monitoring_daily_runs
                WHERE status IN ({placeholders})
                  {project_clause}
                  AND (lease_owner = '' OR lease_expires_at < ?)
                ORDER BY created_at, run_id
                LIMIT 1
                """,
                tuple(parameters),
            ).fetchone()
            if row is None:
                return None
            next_version = int(row["version"]) + 1
            next_epoch = int(row["lease_epoch"]) + 1
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET lease_owner = ?, lease_expires_at = ?,
                    lease_epoch = ?, claim_count = claim_count + 1,
                    version = ?, updated_at = ?
                WHERE run_id = ? AND version = ?
                """,
                (
                    owner,
                    _iso(expires_at),
                    next_epoch,
                    next_version,
                    _iso(now),
                    row["run_id"],
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunVersionConflictError("run claim lost version CAS")
            self._append_event(
                connection,
                run_id=row["run_id"],
                project_id=row["project_id"],
                run_version=next_version,
                event_type="run_claimed",
                actor=owner,
                payload={"lease_epoch": next_epoch, "reclaimed": bool(row["lease_owner"])},
                created_at=now,
            )
            return self._run(self._run_row(connection, row["run_id"]))

    def heartbeat(
        self,
        project_id: str,
        run_id: str,
        *,
        owner: str,
        lease_epoch: int,
    ) -> MonitoringDailyRun:
        now = self.clock()
        expires_at = now + timedelta(seconds=self.lease_seconds)
        with self._transaction() as connection:
            row = self._project_run_row(connection, project_id, run_id)
            self._assert_lease(row, owner, lease_epoch, now)
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET lease_expires_at = ?, updated_at = ?
                WHERE run_id = ? AND lease_owner = ? AND lease_epoch = ?
                  AND lease_expires_at >= ?
                """,
                (
                    _iso(expires_at),
                    _iso(now),
                    row["run_id"],
                    owner,
                    int(lease_epoch),
                    _iso(now),
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunLeaseConflictError("heartbeat lost run lease")
            return self._run(self._run_row(connection, row["run_id"]))

    def release_lease(
        self,
        project_id: str,
        run_id: str,
        *,
        owner: str,
        lease_epoch: int,
    ) -> MonitoringDailyRun:
        now = self.clock()
        with self._transaction() as connection:
            row = self._project_run_row(connection, project_id, run_id)
            self._assert_lease(row, owner, lease_epoch, now)
            next_version = int(row["version"]) + 1
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET lease_owner = '', lease_expires_at = '',
                    version = ?, updated_at = ?
                WHERE run_id = ? AND version = ?
                  AND lease_owner = ? AND lease_epoch = ?
                """,
                (
                    next_version,
                    _iso(now),
                    row["run_id"],
                    row["version"],
                    owner,
                    int(lease_epoch),
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunLeaseConflictError("release lost run lease")
            self._append_event(
                connection,
                run_id=row["run_id"],
                project_id=row["project_id"],
                run_version=next_version,
                event_type="run_lease_released",
                actor=owner,
                payload={"lease_epoch": int(lease_epoch)},
                created_at=now,
            )
            return self._run(self._run_row(connection, row["run_id"]))

    def transition(
        self,
        project_id: str,
        run_id: str,
        *,
        target_status: str,
        expected_version: int,
        actor: str,
        lease_owner: Optional[str] = None,
        lease_epoch: Optional[int] = None,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> MonitoringDailyRun:
        target_status = _required_text(target_status, "target_status")
        if target_status == "confirmed":
            raise DailyRunStateConflictError(
                "confirmed requires confirm_run so baseline update is atomic"
            )
        if target_status not in RUN_STATES:
            raise DailyRunStateConflictError(f"unknown run status {target_status}")
        actor = _required_text(actor, "actor")
        now = self.clock()
        with self._transaction() as connection:
            row = self._project_run_row(connection, project_id, run_id)
            self._assert_version(row, expected_version)
            self._assert_optional_lease(row, lease_owner, lease_epoch, now)
            current_status = row["status"]
            if target_status not in _NEXT_STATES[current_status]:
                raise DailyRunStateConflictError(
                    f"invalid run transition {current_status} -> {target_status}"
                )
            self._assert_transition_outputs(row, target_status)
            next_version = int(row["version"]) + 1
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET status = ?, version = ?, updated_at = ?
                WHERE run_id = ? AND version = ? AND status = ?
                """,
                (
                    target_status,
                    next_version,
                    _iso(now),
                    row["run_id"],
                    row["version"],
                    current_status,
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunVersionConflictError("run transition lost version CAS")
            self._append_event(
                connection,
                run_id=row["run_id"],
                project_id=row["project_id"],
                run_version=next_version,
                event_type="run_status_changed",
                actor=actor,
                payload={
                    "from": current_status,
                    "to": target_status,
                    **dict(payload or {}),
                },
                created_at=now,
            )
            return self._run(self._run_row(connection, row["run_id"]))

    def supersede_drifted_run(
        self,
        project_id: str,
        run_id: str,
        *,
        replacement_run_id: str,
        expected_version: int,
        actor: str,
    ) -> MonitoringDailyRun:
        actor = _required_text(actor, "actor")
        replacement_run_id = _required_text(
            replacement_run_id,
            "replacement_run_id",
        )
        if replacement_run_id == run_id:
            raise DailyRunStateConflictError(
                "replacement run must differ from drifted run"
            )
        now = self.clock()
        with self._transaction() as connection:
            row = self._project_run_row(connection, project_id, run_id)
            self._assert_version(row, expected_version)
            if row["status"] != "drift_review_required":
                raise DailyRunStateConflictError(
                    "only a drift-review run can be superseded"
                )
            replacement = self._project_run_row(
                connection,
                project_id,
                replacement_run_id,
            )
            if replacement["batch_id"] != row["batch_id"]:
                raise DailyRunStateConflictError(
                    "replacement run must bind the same uploaded batch"
                )
            if replacement["baseline_batch_id"] != row["baseline_batch_id"]:
                raise DailyRunStateConflictError(
                    "replacement run must bind the same confirmed baseline"
                )
            if replacement["mapping_revision"] == row["mapping_revision"]:
                raise DailyRunStateConflictError(
                    "replacement run requires a new mapping revision"
                )
            next_version = int(row["version"]) + 1
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET status = 'superseded', version = ?, updated_at = ?
                WHERE run_id = ? AND version = ?
                  AND status = 'drift_review_required'
                """,
                (
                    next_version,
                    _iso(now),
                    row["run_id"],
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunVersionConflictError(
                    "drifted run supersession lost version CAS"
                )
            self._append_event(
                connection,
                run_id=row["run_id"],
                project_id=row["project_id"],
                run_version=next_version,
                event_type="drifted_run_superseded",
                actor=actor,
                payload={"replacement_run_id": replacement_run_id},
                created_at=now,
            )
            return self._run(self._run_row(connection, row["run_id"]))

    def start_step(
        self,
        project_id: str,
        run_id: str,
        *,
        step_name: str,
        input_sha256: str,
        expected_run_version: int,
        lease_owner: Optional[str] = None,
        lease_epoch: Optional[int] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> DailyRunStepMutationResult:
        step_name = _required_text(step_name, "step_name")
        input_sha256 = _require_sha256(input_sha256, "input_sha256")
        now = self.clock()
        with self._transaction() as connection:
            run_row = self._project_run_row(connection, project_id, run_id)
            self._assert_active(run_row)
            self._assert_version(run_row, expected_run_version)
            self._assert_optional_lease(
                run_row,
                lease_owner,
                lease_epoch,
                now,
            )
            existing = connection.execute(
                """
                SELECT * FROM monitoring_daily_run_steps
                WHERE run_id = ? AND step_name = ?
                """,
                (run_row["run_id"], step_name),
            ).fetchone()
            current_lease_epoch = int(lease_epoch or 0)
            if existing is not None:
                if existing["input_sha256"] != input_sha256:
                    raise DailyRunOutputConflictError(
                        "step is already bound to different input"
                    )
                if existing["status"] in {"completed", "skipped"}:
                    return DailyRunStepMutationResult(self._step(existing), True)
                if (
                    existing["status"] == "running"
                    and int(existing["lease_epoch"]) == current_lease_epoch
                ):
                    return DailyRunStepMutationResult(self._step(existing), True)
                attempt_count = int(existing["attempt_count"]) + 1
                connection.execute(
                    """
                    UPDATE monitoring_daily_run_steps
                    SET status = 'running', attempt_count = ?,
                        lease_epoch = ?, output_sha256 = '', details_json = ?,
                        started_at = ?, updated_at = ?, finished_at = ''
                    WHERE run_id = ? AND step_name = ?
                      AND status IN ('failed', 'running')
                    """,
                    (
                        attempt_count,
                        current_lease_epoch,
                        _canonical_json(dict(details or {})),
                        _iso(now),
                        _iso(now),
                        run_row["run_id"],
                        step_name,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO monitoring_daily_run_steps(
                        run_id, step_name, status, attempt_count,
                        lease_epoch, input_sha256, details_json,
                        started_at, updated_at
                    ) VALUES (?, ?, 'running', 1, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_row["run_id"],
                        step_name,
                        current_lease_epoch,
                        input_sha256,
                        _canonical_json(dict(details or {})),
                        _iso(now),
                        _iso(now),
                    ),
                )
            self._append_event(
                connection,
                run_id=run_row["run_id"],
                project_id=run_row["project_id"],
                run_version=int(run_row["version"]),
                event_type="step_started",
                actor=lease_owner or "system",
                payload={"step_name": step_name, "input_sha256": input_sha256},
                created_at=now,
            )
            current = connection.execute(
                """
                SELECT * FROM monitoring_daily_run_steps
                WHERE run_id = ? AND step_name = ?
                """,
                (run_row["run_id"], step_name),
            ).fetchone()
            return DailyRunStepMutationResult(self._step(current), False)

    def finish_step(
        self,
        project_id: str,
        run_id: str,
        *,
        step_name: str,
        status: str,
        input_sha256: str,
        output_sha256: Optional[str],
        expected_run_version: int,
        lease_owner: Optional[str] = None,
        lease_epoch: Optional[int] = None,
        details: Optional[Mapping[str, Any]] = None,
    ) -> DailyRunStepMutationResult:
        if status not in {"completed", "failed", "skipped"}:
            raise MonitoringDailyRunRepositoryError(
                "finish status must be completed, failed, or skipped"
            )
        step_name = _required_text(step_name, "step_name")
        input_sha256 = _require_sha256(input_sha256, "input_sha256")
        normalized_output = (
            _require_sha256(output_sha256, "output_sha256")
            if output_sha256
            else ""
        )
        if status == "completed" and not normalized_output:
            raise MonitoringDailyRunRepositoryError(
                "completed step requires output_sha256"
            )
        now = self.clock()
        with self._transaction() as connection:
            run_row = self._project_run_row(connection, project_id, run_id)
            self._assert_active(run_row)
            self._assert_version(run_row, expected_run_version)
            self._assert_optional_lease(
                run_row,
                lease_owner,
                lease_epoch,
                now,
            )
            existing = connection.execute(
                """
                SELECT * FROM monitoring_daily_run_steps
                WHERE run_id = ? AND step_name = ?
                """,
                (run_row["run_id"], step_name),
            ).fetchone()
            if existing is None:
                raise DailyRunStateConflictError("step must be started before finish")
            if existing["input_sha256"] != input_sha256:
                raise DailyRunOutputConflictError(
                    "step finish input does not match started input"
                )
            if existing["status"] in {"completed", "skipped"}:
                if (
                    existing["status"] == status
                    and existing["output_sha256"] == normalized_output
                ):
                    return DailyRunStepMutationResult(self._step(existing), True)
                raise DailyRunOutputConflictError(
                    "completed step cannot be replaced by different output"
                )
            if existing["status"] != "running":
                raise DailyRunStateConflictError("failed step must be restarted")
            connection.execute(
                """
                UPDATE monitoring_daily_run_steps
                SET status = ?, output_sha256 = ?, details_json = ?,
                    updated_at = ?, finished_at = ?
                WHERE run_id = ? AND step_name = ? AND status = 'running'
                """,
                (
                    status,
                    normalized_output,
                    _canonical_json(dict(details or {})),
                    _iso(now),
                    _iso(now),
                    run_row["run_id"],
                    step_name,
                ),
            )
            self._append_event(
                connection,
                run_id=run_row["run_id"],
                project_id=run_row["project_id"],
                run_version=int(run_row["version"]),
                event_type=f"step_{status}",
                actor=lease_owner or "system",
                payload={
                    "step_name": step_name,
                    "input_sha256": input_sha256,
                    "output_sha256": normalized_output,
                },
                created_at=now,
            )
            current = connection.execute(
                """
                SELECT * FROM monitoring_daily_run_steps
                WHERE run_id = ? AND step_name = ?
                """,
                (run_row["run_id"], step_name),
            ).fetchone()
            return DailyRunStepMutationResult(self._step(current), False)

    def save_diff_snapshot(
        self,
        project_id: str,
        run_id: str,
        *,
        input_sha256: str,
        payload: Mapping[str, Any],
        expected_version: int,
        actor: str,
        lease_owner: Optional[str] = None,
        lease_epoch: Optional[int] = None,
    ) -> DailyRunDiffMutationResult:
        input_sha256 = _require_sha256(input_sha256, "input_sha256")
        actor = _required_text(actor, "actor")
        payload_dict = dict(payload)
        output_sha256 = _content_sha256(payload_dict)
        now = self.clock()
        with self._transaction() as connection:
            run_row = self._project_run_row(connection, project_id, run_id)
            self._assert_version(run_row, expected_version)
            self._assert_optional_lease(
                run_row,
                lease_owner,
                lease_epoch,
                now,
            )
            if run_row["baseline_batch_id"] is None:
                raise DailyRunStateConflictError(
                    "initial baseline run does not require a diff snapshot"
                )
            if run_row["status"] != "diffing":
                raise DailyRunStateConflictError(
                    "diff snapshot requires run status diffing"
                )
            existing = connection.execute(
                """
                SELECT * FROM monitoring_daily_diff_snapshots
                WHERE run_id = ?
                """,
                (run_row["run_id"],),
            ).fetchone()
            if existing is not None:
                if (
                    existing["input_sha256"] != input_sha256
                    or existing["output_sha256"] != output_sha256
                    or existing["algorithm_version"]
                    != run_row["diff_algorithm_version"]
                ):
                    raise DailyRunOutputConflictError(
                        "run already has a different diff snapshot"
                    )
                return DailyRunDiffMutationResult(
                    self._run(run_row),
                    self._diff(existing),
                    True,
                )
            snapshot_id = f"mondiff_{sha256(f'{run_id}|{input_sha256}|{output_sha256}'.encode()).hexdigest()[:24]}"
            connection.execute(
                """
                INSERT INTO monitoring_daily_diff_snapshots(
                    snapshot_id, run_id, project_id,
                    previous_batch_id, current_batch_id,
                    algorithm_version, input_sha256, output_sha256,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    run_row["run_id"],
                    run_row["project_id"],
                    run_row["baseline_batch_id"],
                    run_row["batch_id"],
                    run_row["diff_algorithm_version"],
                    input_sha256,
                    output_sha256,
                    _canonical_json(payload_dict),
                    _iso(now),
                ),
            )
            next_version = int(run_row["version"]) + 1
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET diff_snapshot_id = ?, version = ?, updated_at = ?
                WHERE run_id = ? AND version = ? AND diff_snapshot_id IS NULL
                """,
                (
                    snapshot_id,
                    next_version,
                    _iso(now),
                    run_row["run_id"],
                    run_row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunVersionConflictError(
                    "diff snapshot binding lost run version CAS"
                )
            self._append_event(
                connection,
                run_id=run_row["run_id"],
                project_id=run_row["project_id"],
                run_version=next_version,
                event_type="diff_snapshot_saved",
                actor=actor,
                payload={
                    "snapshot_id": snapshot_id,
                    "input_sha256": input_sha256,
                    "output_sha256": output_sha256,
                },
                created_at=now,
            )
            current_run = self._run(self._run_row(connection, run_row["run_id"]))
            snapshot_row = connection.execute(
                """
                SELECT * FROM monitoring_daily_diff_snapshots
                WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchone()
            return DailyRunDiffMutationResult(
                current_run,
                self._diff(snapshot_row),
                False,
            )

    def save_rule_snapshot(
        self,
        project_id: str,
        run_id: str,
        *,
        input_sha256: str,
        payload: Mapping[str, Any],
        expected_version: int,
        actor: str,
        lease_owner: Optional[str] = None,
        lease_epoch: Optional[int] = None,
    ) -> DailyRunRuleMutationResult:
        input_sha256 = _require_sha256(input_sha256, "input_sha256")
        actor = _required_text(actor, "actor")
        payload_dict = dict(payload)
        output_sha256 = _content_sha256(payload_dict)
        analysis_complete = payload_dict.get("analysis_complete", True)
        if not isinstance(analysis_complete, bool):
            raise DailyRunOutputConflictError(
                "rule snapshot analysis_complete must be a strict boolean"
            )
        now = self.clock()
        with self._transaction() as connection:
            row = self._project_run_row(connection, project_id, run_id)
            self._assert_active(row)
            self._assert_version(row, expected_version)
            self._assert_optional_lease(row, lease_owner, lease_epoch, now)
            if row["status"] != "rules_running":
                raise DailyRunStateConflictError(
                    "rule snapshot requires run status rules_running"
                )
            if str(payload_dict.get("project_id") or "") != row["project_id"]:
                raise DailyRunOutputConflictError(
                    "rule snapshot project does not match run"
                )
            if str(payload_dict.get("batch_id") or "") != row["batch_id"]:
                raise DailyRunOutputConflictError(
                    "rule snapshot batch does not match run"
                )
            resolution_mode = str(
                payload_dict.get("resolution_mode") or "project_effective"
            ).strip()
            if resolution_mode != row["rule_resolution_mode"]:
                raise DailyRunOutputConflictError(
                    "rule snapshot resolution mode does not match run"
                )
            snapshot_rule_pack_id = str(
                payload_dict.get("rule_pack_id") or ""
            ).strip()
            if resolution_mode == "project_effective":
                if snapshot_rule_pack_id != row["rule_pack_revision"]:
                    raise DailyRunOutputConflictError(
                        "rule snapshot pack does not match run"
                    )
            else:
                self._validate_record_rule_snapshot_payload(payload_dict)
            existing = connection.execute(
                """
                SELECT * FROM monitoring_daily_rule_snapshots
                WHERE run_id = ?
                """,
                (row["run_id"],),
            ).fetchone()
            if existing is not None:
                if (
                    existing["input_sha256"] != input_sha256
                    or existing["output_sha256"] != output_sha256
                    or existing["batch_id"] != row["batch_id"]
                    or existing["rule_pack_id"] != snapshot_rule_pack_id
                    or existing["resolution_mode"] != resolution_mode
                    or existing["engine_version"] != row["engine_version"]
                ):
                    raise DailyRunOutputConflictError(
                        "run already has a different rule snapshot"
                    )
                return DailyRunRuleMutationResult(
                    self._run(row),
                    self._rule_snapshot(existing),
                    True,
                )
            snapshot_id = (
                "monrules_"
                + sha256(
                    f"{run_id}|{input_sha256}|{output_sha256}".encode("utf-8")
                ).hexdigest()[:24]
            )
            connection.execute(
                """
                INSERT INTO monitoring_daily_rule_snapshots(
                    snapshot_id, run_id, project_id, batch_id,
                    rule_pack_id, resolution_mode, engine_version, input_sha256,
                    output_sha256, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    row["run_id"],
                    row["project_id"],
                    row["batch_id"],
                    snapshot_rule_pack_id,
                    resolution_mode,
                    row["engine_version"],
                    input_sha256,
                    output_sha256,
                    _canonical_json(payload_dict),
                    _iso(now),
                ),
            )
            next_version = int(row["version"]) + 1
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET rule_snapshot_id = ?, version = ?, updated_at = ?
                WHERE run_id = ? AND version = ? AND rule_snapshot_id IS NULL
                """,
                (
                    snapshot_id,
                    next_version,
                    _iso(now),
                    row["run_id"],
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunVersionConflictError(
                    "rule snapshot binding lost run version CAS"
                )
            self._append_event(
                connection,
                run_id=row["run_id"],
                project_id=row["project_id"],
                run_version=next_version,
                event_type="rule_snapshot_saved",
                actor=actor,
                payload={
                    "snapshot_id": snapshot_id,
                    "input_sha256": input_sha256,
                    "output_sha256": output_sha256,
                    "resolution_mode": resolution_mode,
                    "rule_pack_ids": list(payload_dict.get("rule_pack_ids") or ()),
                },
                created_at=now,
            )
            current_run = self._run(self._run_row(connection, row["run_id"]))
            snapshot_row = connection.execute(
                """
                SELECT * FROM monitoring_daily_rule_snapshots
                WHERE snapshot_id = ?
                """,
                (snapshot_id,),
            ).fetchone()
            return DailyRunRuleMutationResult(
                current_run,
                self._rule_snapshot(snapshot_row),
                False,
            )

    def bind_risk_snapshot(
        self,
        project_id: str,
        run_id: str,
        *,
        risk_snapshot_id: str,
        expected_version: int,
        actor: str,
        lease_owner: Optional[str] = None,
        lease_epoch: Optional[int] = None,
    ) -> DailyRunMutationResult:
        risk_snapshot_id = _required_text(risk_snapshot_id, "risk_snapshot_id")
        actor = _required_text(actor, "actor")
        now = self.clock()
        with self._transaction() as connection:
            row = self._project_run_row(connection, project_id, run_id)
            self._assert_active(row)
            self._assert_version(row, expected_version)
            self._assert_optional_lease(row, lease_owner, lease_epoch, now)
            if row["status"] not in {
                "rules_running",
                "ai_running",
                "analysis_partial",
                "risk_review",
            }:
                raise DailyRunStateConflictError(
                    "risk snapshot can only bind during analysis or risk review"
                )
            if row["risk_snapshot_id"]:
                if row["risk_snapshot_id"] == risk_snapshot_id:
                    return DailyRunMutationResult(self._run(row), True)
                raise DailyRunOutputConflictError(
                    "run already has a different risk snapshot"
                )
            next_version = int(row["version"]) + 1
            updated = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET risk_snapshot_id = ?, version = ?, updated_at = ?
                WHERE run_id = ? AND version = ? AND risk_snapshot_id IS NULL
                """,
                (
                    risk_snapshot_id,
                    next_version,
                    _iso(now),
                    row["run_id"],
                    row["version"],
                ),
            )
            if updated.rowcount != 1:
                raise DailyRunVersionConflictError(
                    "risk snapshot binding lost run version CAS"
                )
            self._append_event(
                connection,
                run_id=row["run_id"],
                project_id=row["project_id"],
                run_version=next_version,
                event_type="risk_snapshot_bound",
                actor=actor,
                payload={"risk_snapshot_id": risk_snapshot_id},
                created_at=now,
            )
            return DailyRunMutationResult(
                self._run(self._run_row(connection, row["run_id"])),
                False,
            )

    def confirm_run(
        self,
        project_id: str,
        run_id: str,
        *,
        expected_run_version: int,
        expected_baseline_revision: int,
        confirmed_by: str,
    ) -> DailyRunConfirmationResult:
        confirmed_by = _required_text(confirmed_by, "confirmed_by")
        if int(expected_baseline_revision) < 0:
            raise MonitoringDailyRunRepositoryError(
                "expected_baseline_revision cannot be negative"
            )
        now = self.clock()
        with self._transaction() as connection:
            run_row = self._project_run_row(connection, project_id, run_id)
            self._assert_version(run_row, expected_run_version)
            if run_row["status"] != "ready_to_confirm":
                raise DailyRunStateConflictError(
                    "final confirmation requires ready_to_confirm"
                )
            if (
                run_row["lease_owner"]
                and run_row["lease_expires_at"]
                and run_row["lease_expires_at"] >= _iso(now)
            ):
                raise DailyRunLeaseConflictError(
                    "cannot confirm while the run has an active worker lease"
                )
            if not run_row["risk_snapshot_id"]:
                raise DailyRunStateConflictError(
                    "final confirmation requires a bound risk snapshot"
                )
            if run_row["baseline_batch_id"] and not run_row["diff_snapshot_id"]:
                raise DailyRunStateConflictError(
                    "non-initial run requires a bound diff snapshot"
                )

            baseline_row = connection.execute(
                """
                SELECT * FROM monitoring_project_baselines
                WHERE project_id = ?
                """,
                (run_row["project_id"],),
            ).fetchone()
            current_revision = int(baseline_row["revision"]) if baseline_row else 0
            current_batch_id = (
                str(baseline_row["current_baseline_batch_id"])
                if baseline_row
                else None
            )
            if current_revision != int(expected_baseline_revision):
                raise DailyRunBaselineConflictError(
                    "project baseline revision CAS conflict"
                )
            if current_batch_id != run_row["baseline_batch_id"]:
                raise DailyRunBaselineConflictError(
                    "project baseline changed after run preparation"
                )

            next_baseline_revision = current_revision + 1
            if baseline_row is None:
                connection.execute(
                    """
                    INSERT INTO monitoring_project_baselines(
                        project_id, current_baseline_batch_id,
                        confirmed_run_id, revision, confirmed_at, confirmed_by
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_row["project_id"],
                        run_row["batch_id"],
                        run_row["run_id"],
                        next_baseline_revision,
                        _iso(now),
                        confirmed_by,
                    ),
                )
            else:
                updated_baseline = connection.execute(
                    """
                    UPDATE monitoring_project_baselines
                    SET current_baseline_batch_id = ?, confirmed_run_id = ?,
                        revision = ?, confirmed_at = ?, confirmed_by = ?
                    WHERE project_id = ? AND revision = ?
                      AND current_baseline_batch_id = ?
                    """,
                    (
                        run_row["batch_id"],
                        run_row["run_id"],
                        next_baseline_revision,
                        _iso(now),
                        confirmed_by,
                        run_row["project_id"],
                        current_revision,
                        current_batch_id,
                    ),
                )
                if updated_baseline.rowcount != 1:
                    raise DailyRunBaselineConflictError(
                        "project baseline update lost CAS"
                    )

            next_run_version = int(run_row["version"]) + 1
            updated_run = connection.execute(
                """
                UPDATE monitoring_daily_runs
                SET status = 'confirmed', version = ?,
                    lease_owner = '', lease_expires_at = '',
                    updated_at = ?, confirmed_at = ?, confirmed_by = ?
                WHERE run_id = ? AND version = ? AND status = 'ready_to_confirm'
                """,
                (
                    next_run_version,
                    _iso(now),
                    _iso(now),
                    confirmed_by,
                    run_row["run_id"],
                    run_row["version"],
                ),
            )
            if updated_run.rowcount != 1:
                raise DailyRunVersionConflictError(
                    "final confirmation lost run version CAS"
                )
            self._append_event(
                connection,
                run_id=run_row["run_id"],
                project_id=run_row["project_id"],
                run_version=next_run_version,
                event_type="run_confirmed",
                actor=confirmed_by,
                payload={
                    "previous_baseline_batch_id": current_batch_id,
                    "current_baseline_batch_id": run_row["batch_id"],
                    "baseline_revision": next_baseline_revision,
                    "risk_snapshot_id": run_row["risk_snapshot_id"],
                    "diff_snapshot_id": run_row["diff_snapshot_id"],
                },
                created_at=now,
            )
            confirmed_run = self._run(
                self._run_row(connection, run_row["run_id"])
            )
            baseline = self._baseline(
                connection.execute(
                    """
                    SELECT * FROM monitoring_project_baselines
                    WHERE project_id = ?
                    """,
                    (run_row["project_id"],),
                ).fetchone()
            )
            return DailyRunConfirmationResult(confirmed_run, baseline)

    @staticmethod
    def _run_row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM monitoring_daily_runs WHERE run_id = ?",
            (_required_text(run_id, "run_id"),),
        ).fetchone()
        if row is None:
            raise DailyRunNotFoundError("monitoring daily run not found")
        return row

    @classmethod
    def _project_run_row(
        cls,
        connection: sqlite3.Connection,
        project_id: str,
        run_id: str,
    ) -> sqlite3.Row:
        row = cls._run_row(connection, run_id)
        if row["project_id"] != _required_text(project_id, "project_id"):
            raise DailyRunNotFoundError("monitoring daily run not found")
        return row

    @staticmethod
    def _assert_active(row: sqlite3.Row) -> None:
        if row["status"] not in ACTIVE_RUN_STATES:
            raise DailyRunStateConflictError("run is no longer active")

    @staticmethod
    def _assert_version(row: sqlite3.Row, expected_version: int) -> None:
        if int(row["version"]) != int(expected_version):
            raise DailyRunVersionConflictError("run version CAS conflict")

    @staticmethod
    def _assert_lease(
        row: sqlite3.Row,
        owner: str,
        lease_epoch: int,
        now: datetime,
    ) -> None:
        if (
            row["lease_owner"] != _required_text(owner, "owner")
            or int(row["lease_epoch"]) != int(lease_epoch)
            or not row["lease_expires_at"]
            or row["lease_expires_at"] < _iso(now)
        ):
            raise DailyRunLeaseConflictError("run lease lost or expired")

    @classmethod
    def _assert_optional_lease(
        cls,
        row: sqlite3.Row,
        owner: Optional[str],
        lease_epoch: Optional[int],
        now: datetime,
    ) -> None:
        if row["lease_owner"]:
            if owner is None or lease_epoch is None:
                raise DailyRunLeaseConflictError(
                    "active run lease must be presented"
                )
            cls._assert_lease(row, owner, lease_epoch, now)
        elif owner is not None or lease_epoch is not None:
            raise DailyRunLeaseConflictError("run has no active lease")

    @staticmethod
    def _assert_transition_outputs(
        row: sqlite3.Row,
        target_status: str,
    ) -> None:
        if row["status"] == "prepared":
            if target_status == "diffing" and row["baseline_batch_id"] is None:
                raise DailyRunStateConflictError(
                    "initial baseline run must skip diffing"
                )
            if target_status == "rules_running" and row["baseline_batch_id"] is not None:
                raise DailyRunStateConflictError(
                    "non-initial run must complete diff before rules"
                )
        if row["status"] == "diffing" and target_status in {
            "drift_review_required",
            "rules_running",
        }:
            if not row["diff_snapshot_id"]:
                raise DailyRunStateConflictError(
                    "diff result must be frozen before leaving diffing"
                )
        if row["status"] == "risk_review" and target_status == "ready_to_confirm":
            if not row["risk_snapshot_id"]:
                raise DailyRunStateConflictError(
                    "risk snapshot must be bound before confirmation review"
                )
        if row["status"] == "rules_running" and target_status in {
            "ai_running",
            "analysis_partial",
            "risk_review",
        }:
            if not row["rule_snapshot_id"]:
                raise DailyRunStateConflictError(
                    "rule snapshot must be frozen before leaving rule execution"
                )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        project_id: str,
        run_version: int,
        event_type: str,
        actor: str,
        payload: Mapping[str, Any],
        created_at: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO monitoring_daily_run_events(
                run_id, project_id, run_version, event_type,
                actor, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                int(run_version),
                _required_text(event_type, "event_type"),
                _required_text(actor, "actor"),
                _canonical_json(dict(payload)),
                _iso(created_at),
            ),
        )

    @staticmethod
    def _run(row: sqlite3.Row) -> MonitoringDailyRun:
        try:
            def required_text(value: object, label: str) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise ValueError(f"persisted daily run {label} is invalid")
                return value

            def optional_text(value: object, label: str) -> Optional[str]:
                if value is None or value == "":
                    return None
                return required_text(value, label)

            def required_sha256(value: object, label: str) -> str:
                raw = required_text(value, label)
                normalized = _require_sha256(raw, label)
                if normalized != raw:
                    raise ValueError(f"persisted daily run {label} is invalid")
                return raw

            def required_datetime(value: object, label: str) -> datetime:
                raw = required_text(value, label)
                parsed = _datetime(raw)
                if parsed is None:
                    raise ValueError(f"persisted daily run {label} is invalid")
                return parsed

            def optional_datetime(value: object, label: str) -> Optional[datetime]:
                if value is None or value == "":
                    return None
                return _datetime(required_text(value, label))

            run_id = required_text(row["run_id"], "run_id")
            project_id = required_text(row["project_id"], "project_id")
            status = required_text(row["status"], "status")
            if status not in RUN_STATES:
                raise ValueError("persisted daily run status is invalid")
            raw_batch_version = row["batch_version"]
            if (
                isinstance(raw_batch_version, bool)
                or not isinstance(raw_batch_version, int)
                or raw_batch_version < 1
            ):
                raise ValueError("persisted daily run batch_version is invalid")
            raw_version = row["version"]
            raw_lease_epoch = row["lease_epoch"]
            raw_claim_count = row["claim_count"]
            if (
                isinstance(raw_version, bool)
                or not isinstance(raw_version, int)
                or raw_version < 1
                or isinstance(raw_lease_epoch, bool)
                or not isinstance(raw_lease_epoch, int)
                or raw_lease_epoch < 0
                or isinstance(raw_claim_count, bool)
                or not isinstance(raw_claim_count, int)
                or raw_claim_count < 0
            ):
                raise ValueError("persisted daily run counters are invalid")
            rule_resolution_mode = required_text(
                row["rule_resolution_mode"]
                if "rule_resolution_mode" in row.keys()
                else "project_effective",
                "rule_resolution_mode",
            )
            if rule_resolution_mode not in RULE_RESOLUTION_MODES:
                raise ValueError("persisted daily run rule resolution mode is invalid")
            raw_rule_identity_sha256 = (
                row["rule_identity_sha256"]
                if "rule_identity_sha256" in row.keys()
                else ""
            )
            rule_identity_sha256 = (
                required_sha256(
                    raw_rule_identity_sha256,
                    "rule_identity_sha256",
                )
                if raw_rule_identity_sha256
                else ""
            )
            normalized_input = DailyRunInput(
                project_id=project_id,
                batch_id=required_text(row["batch_id"], "batch_id"),
                baseline_batch_id=optional_text(
                    row["baseline_batch_id"],
                    "baseline_batch_id",
                ),
                batch_version=raw_batch_version,
                mapping_revision=required_text(
                    row["mapping_revision"],
                    "mapping_revision",
                ),
                rule_pack_revision=optional_text(
                    row["rule_pack_revision"],
                    "rule_pack_revision",
                ) or "",
                engine_version=required_text(row["engine_version"], "engine_version"),
                diff_algorithm_version=required_text(
                    row["diff_algorithm_version"],
                    "diff_algorithm_version",
                ),
                rule_resolution_mode=rule_resolution_mode,
                rule_identity_sha256=rule_identity_sha256,
            ).normalized()
            input_sha256 = required_sha256(row["input_sha256"], "input_sha256")
            if normalized_input.input_sha256 != input_sha256:
                raise MonitoringDailyRunRepositoryError(
                    "persisted daily run input hash mismatch"
                )
            return MonitoringDailyRun(
                run_id=run_id,
                project_id=normalized_input.project_id,
                batch_id=normalized_input.batch_id,
                baseline_batch_id=normalized_input.baseline_batch_id,
                batch_version=normalized_input.batch_version,
                mapping_revision=normalized_input.mapping_revision,
                rule_pack_revision=normalized_input.rule_pack_revision,
                rule_resolution_mode=normalized_input.rule_resolution_mode,
                rule_identity_sha256=normalized_input.rule_identity_sha256,
                engine_version=normalized_input.engine_version,
                diff_algorithm_version=normalized_input.diff_algorithm_version,
                input_sha256=input_sha256,
                status=status,
                version=raw_version,
                diff_snapshot_id=optional_text(row["diff_snapshot_id"], "diff_snapshot_id"),
                rule_snapshot_id=optional_text(row["rule_snapshot_id"], "rule_snapshot_id"),
                risk_snapshot_id=optional_text(row["risk_snapshot_id"], "risk_snapshot_id"),
                lease_owner=optional_text(row["lease_owner"], "lease_owner"),
                lease_expires_at=optional_datetime(
                    row["lease_expires_at"],
                    "lease_expires_at",
                ),
                lease_epoch=raw_lease_epoch,
                claim_count=raw_claim_count,
                created_at=required_datetime(row["created_at"], "created_at"),
                updated_at=required_datetime(row["updated_at"], "updated_at"),
                confirmed_at=optional_datetime(row["confirmed_at"], "confirmed_at"),
                confirmed_by=optional_text(row["confirmed_by"], "confirmed_by"),
            )
        except MonitoringDailyRunRepositoryError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise MonitoringDailyRunRepositoryError(
                "persisted daily run root is invalid"
            ) from exc

    @staticmethod
    def _step(row: sqlite3.Row) -> MonitoringDailyRunStep:
        try:
            def required_text(value: object, label: str) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise ValueError(f"persisted daily run step {label} is invalid")
                return value

            def required_int(value: object, label: str, *, minimum: int) -> int:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < minimum
                ):
                    raise ValueError(f"persisted daily run step {label} is invalid")
                return value

            def canonical_sha256(value: object, label: str) -> str:
                raw = required_text(value, label)
                normalized = _require_sha256(raw, label)
                if normalized != raw:
                    raise ValueError(f"persisted daily run step {label} is invalid")
                return raw

            def required_datetime(value: object, label: str) -> datetime:
                raw = required_text(value, label)
                parsed = _datetime(raw)
                if parsed is None:
                    raise ValueError(f"persisted daily run step {label} is invalid")
                return parsed

            def optional_datetime(value: object, label: str) -> Optional[datetime]:
                if value is None or value == "":
                    return None
                return required_datetime(value, label)

            status = required_text(row["status"], "status")
            if status not in STEP_STATES:
                raise ValueError("persisted daily run step status is invalid")
            attempt_count = required_int(
                row["attempt_count"],
                "attempt_count",
                minimum=1,
            )
            lease_epoch = required_int(
                row["lease_epoch"],
                "lease_epoch",
                minimum=0,
            )
            details_raw = row["details_json"]
            if not isinstance(details_raw, str):
                raise ValueError("persisted daily run step details are invalid")
            details = json.loads(details_raw)
            if not isinstance(details, dict):
                raise ValueError("persisted daily run step details are invalid")
            output_raw = row["output_sha256"]
            output_sha256 = None
            if output_raw is not None and output_raw != "":
                output_sha256 = canonical_sha256(output_raw, "output_sha256")
            started_at = required_datetime(row["started_at"], "started_at")
            updated_at = required_datetime(row["updated_at"], "updated_at")
            finished_at = optional_datetime(row["finished_at"], "finished_at")
            return MonitoringDailyRunStep(
                run_id=required_text(row["run_id"], "run_id"),
                step_name=required_text(row["step_name"], "step_name"),
                status=status,
                attempt_count=attempt_count,
                lease_epoch=lease_epoch,
                input_sha256=canonical_sha256(row["input_sha256"], "input_sha256"),
                output_sha256=output_sha256,
                details=details,
                started_at=started_at,
                updated_at=updated_at,
                finished_at=finished_at,
            )
        except Exception as exc:
            raise MonitoringDailyRunRepositoryError(
                "persisted daily run step is invalid"
            ) from exc

    @staticmethod
    def _event(row: sqlite3.Row) -> MonitoringDailyRunEvent:
        try:
            def required_text(value: object, label: str) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise ValueError(f"persisted daily run event {label} is invalid")
                return value

            def required_int(value: object, label: str) -> int:
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError(f"persisted daily run event {label} is invalid")
                return value

            def required_datetime(value: object, label: str) -> datetime:
                raw = required_text(value, label)
                parsed = _datetime(raw)
                if parsed is None:
                    raise ValueError(f"persisted daily run event {label} is invalid")
                return parsed

            event_seq = required_int(row["event_seq"], "event_seq")
            run_version = required_int(row["run_version"], "run_version")
            payload_raw = row["payload_json"]
            if not isinstance(payload_raw, str):
                raise ValueError("persisted daily run event payload is invalid")
            payload = json.loads(payload_raw)
            if not isinstance(payload, dict):
                raise ValueError("persisted daily run event payload is invalid")
            created_at = required_datetime(row["created_at"], "created_at")
            return MonitoringDailyRunEvent(
                event_seq=event_seq,
                run_id=required_text(row["run_id"], "run_id"),
                project_id=required_text(row["project_id"], "project_id"),
                run_version=run_version,
                event_type=required_text(row["event_type"], "event_type"),
                actor=required_text(row["actor"], "actor"),
                payload=payload,
                created_at=created_at,
            )
        except Exception as exc:
            raise MonitoringDailyRunRepositoryError(
                "persisted daily run event is invalid"
            ) from exc

    @staticmethod
    def _diff(row: sqlite3.Row) -> MonitoringDiffSnapshot:
        payload, output_sha256 = MonitoringDailyRunRepository._snapshot_payload(
            row,
            kind="diff",
            snapshot_prefix="mondiff_",
        )
        MonitoringDailyRunRepository._validate_diff_identity(row)
        snapshot_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["snapshot_id"], kind="diff", field="snapshot_id"
        )
        run_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["run_id"], kind="diff", field="run_id"
        )
        project_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["project_id"], kind="diff", field="project_id"
        )
        previous_batch_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["previous_batch_id"], kind="diff", field="previous_batch_id"
        )
        current_batch_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["current_batch_id"], kind="diff", field="current_batch_id"
        )
        algorithm_version = MonitoringDailyRunRepository._snapshot_required_text(
            row["algorithm_version"], kind="diff", field="algorithm_version"
        )
        input_sha256 = MonitoringDailyRunRepository._snapshot_required_sha256(
            row["input_sha256"], kind="diff", field="input_sha256"
        )
        created_at = MonitoringDailyRunRepository._snapshot_required_datetime(
            row["created_at"], kind="diff", field="created_at"
        )
        return MonitoringDiffSnapshot(
            snapshot_id=snapshot_id,
            run_id=run_id,
            project_id=project_id,
            previous_batch_id=previous_batch_id,
            current_batch_id=current_batch_id,
            algorithm_version=algorithm_version,
            input_sha256=input_sha256,
            output_sha256=output_sha256,
            payload=payload,
            created_at=created_at,
        )

    @staticmethod
    def _rule_snapshot(row: sqlite3.Row) -> MonitoringRuleSnapshot:
        payload, output_sha256 = MonitoringDailyRunRepository._snapshot_payload(
            row,
            kind="rule",
            snapshot_prefix="monrules_",
        )
        MonitoringDailyRunRepository._validate_rule_identity(row, payload)
        snapshot_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["snapshot_id"], kind="rule", field="snapshot_id"
        )
        run_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["run_id"], kind="rule", field="run_id"
        )
        project_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["project_id"], kind="rule", field="project_id"
        )
        batch_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["batch_id"], kind="rule", field="batch_id"
        )
        resolution_mode = (
            row["resolution_mode"]
            if "resolution_mode" in row.keys()
            else "project_effective"
        )
        resolution_mode = MonitoringDailyRunRepository._snapshot_required_text(
            resolution_mode,
            kind="rule",
            field="resolution_mode",
        )
        if resolution_mode not in RULE_RESOLUTION_MODES:
            raise DailyRunOutputConflictError(
                "persisted rule snapshot resolution_mode is invalid"
            )
        raw_rule_pack_id = row["rule_pack_id"]
        if resolution_mode == "record_applicability":
            if not isinstance(raw_rule_pack_id, str) or (
                raw_rule_pack_id.strip() != raw_rule_pack_id
            ):
                raise DailyRunOutputConflictError(
                    "persisted rule snapshot rule_pack_id is invalid"
                )
            rule_pack_id = raw_rule_pack_id
        else:
            rule_pack_id = MonitoringDailyRunRepository._snapshot_required_text(
                raw_rule_pack_id,
                kind="rule",
                field="rule_pack_id",
            )
        engine_version = MonitoringDailyRunRepository._snapshot_required_text(
            row["engine_version"], kind="rule", field="engine_version"
        )
        input_sha256 = MonitoringDailyRunRepository._snapshot_required_sha256(
            row["input_sha256"], kind="rule", field="input_sha256"
        )
        created_at = MonitoringDailyRunRepository._snapshot_required_datetime(
            row["created_at"], kind="rule", field="created_at"
        )
        return MonitoringRuleSnapshot(
            snapshot_id=snapshot_id,
            run_id=run_id,
            project_id=project_id,
            batch_id=batch_id,
            rule_pack_id=rule_pack_id,
            engine_version=engine_version,
            input_sha256=input_sha256,
            output_sha256=output_sha256,
            payload=payload,
            created_at=created_at,
            resolution_mode=resolution_mode,
        )

    @staticmethod
    def _snapshot_required_text(
        value: object,
        *,
        kind: str,
        field: str,
    ) -> str:
        if not isinstance(value, str) or not value or value.strip() != value:
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot {field} is invalid"
            )
        return value

    @staticmethod
    def _snapshot_required_sha256(
        value: object,
        *,
        kind: str,
        field: str,
    ) -> str:
        raw = MonitoringDailyRunRepository._snapshot_required_text(
            value,
            kind=kind,
            field=field,
        )
        try:
            normalized = _require_sha256(raw, f"persisted {kind} snapshot {field}")
        except MonitoringDailyRunRepositoryError as exc:
            if (
                len(raw) == 64
                and raw.lower() != raw
                and all(
                    character in "0123456789abcdefABCDEF"
                    for character in raw
                )
            ):
                raise DailyRunOutputConflictError(
                    f"persisted {kind} snapshot {field} is not canonical"
                ) from exc
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot {field} is invalid"
            ) from exc
        if normalized != raw:
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot {field} is not canonical"
            )
        return raw

    @staticmethod
    def _snapshot_required_datetime(
        value: object,
        *,
        kind: str,
        field: str,
    ) -> datetime:
        raw = MonitoringDailyRunRepository._snapshot_required_text(
            value,
            kind=kind,
            field=field,
        )
        try:
            parsed = _datetime(raw)
        except (TypeError, ValueError) as exc:
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot {field} is invalid"
            ) from exc
        if parsed is None:
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot {field} is invalid"
            )
        return parsed

    @staticmethod
    def _snapshot_payload(
        row: sqlite3.Row,
        *,
        kind: str,
        snapshot_prefix: str,
    ) -> tuple[dict[str, Any], str]:
        payload_raw = row["payload_json"]
        if not isinstance(payload_raw, str):
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot payload is invalid"
            )
        try:
            payload = json.loads(payload_raw)
        except (TypeError, ValueError) as exc:
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot payload is invalid"
            ) from exc
        if not isinstance(payload, dict):
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot payload must be an object"
            )
        snapshot_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["snapshot_id"],
            kind=kind,
            field="snapshot_id",
        )
        run_id = MonitoringDailyRunRepository._snapshot_required_text(
            row["run_id"],
            kind=kind,
            field="run_id",
        )
        input_sha256 = MonitoringDailyRunRepository._snapshot_required_sha256(
            row["input_sha256"],
            kind=kind,
            field="input_sha256",
        )
        output_sha256 = MonitoringDailyRunRepository._snapshot_required_sha256(
            row["output_sha256"],
            kind=kind,
            field="output_sha256",
        )
        if _content_sha256(payload) != output_sha256:
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot content hash mismatch"
            )
        expected_snapshot_id = (
            snapshot_prefix
            + sha256(
                f"{run_id}|{input_sha256}|{output_sha256}".encode(
                    "utf-8"
                )
            ).hexdigest()[:24]
        )
        if snapshot_id != expected_snapshot_id:
            raise DailyRunOutputConflictError(
                f"persisted {kind} snapshot identity mismatch"
            )
        return payload, output_sha256

    @staticmethod
    def _validate_diff_identity(row: sqlite3.Row) -> None:
        keys = set(row.keys())
        if "run_run_id" not in keys:
            return
        expected = {
            "run_run_id": row["run_id"],
            "run_project_id": row["project_id"],
            "run_baseline_batch_id": row["previous_batch_id"],
            "run_batch_id": row["current_batch_id"],
            "run_diff_algorithm_version": row["algorithm_version"],
        }
        if any(row[field] != value for field, value in expected.items()):
            raise DailyRunOutputConflictError(
                "persisted diff snapshot row identity mismatch"
            )

    @staticmethod
    def _validate_rule_identity(
        row: sqlite3.Row,
        payload: Mapping[str, Any],
    ) -> None:
        if str(payload.get("project_id") or "") != str(row["project_id"]):
            raise DailyRunOutputConflictError(
                "persisted rule snapshot project identity mismatch"
            )
        if str(payload.get("batch_id") or "") != str(row["batch_id"]):
            raise DailyRunOutputConflictError(
                "persisted rule snapshot batch identity mismatch"
            )
        if "rule_pack_id" in payload and str(payload.get("rule_pack_id") or "") != str(
            row["rule_pack_id"]
        ):
            raise DailyRunOutputConflictError(
                "persisted rule snapshot pack identity mismatch"
            )
        if "resolution_mode" in row.keys() and str(
            payload.get("resolution_mode") or "project_effective"
        ) != str(row["resolution_mode"]):
            raise DailyRunOutputConflictError(
                "persisted rule snapshot resolution identity mismatch"
            )
        keys = set(row.keys())
        if "run_run_id" not in keys:
            return
        expected = {
            "run_run_id": row["run_id"],
            "run_project_id": row["project_id"],
            "run_batch_id": row["batch_id"],
            "run_rule_pack_revision": row["rule_pack_id"],
            "run_rule_resolution_mode": (
                row["resolution_mode"]
                if "resolution_mode" in row.keys()
                else "project_effective"
            ),
            "run_engine_version": row["engine_version"],
        }
        if any(row[field] != value for field, value in expected.items()):
            raise DailyRunOutputConflictError(
                "persisted rule snapshot row identity mismatch"
            )

    @staticmethod
    def _validate_record_rule_snapshot_payload(
        payload: Mapping[str, Any],
    ) -> None:
        analysis_complete = payload.get("analysis_complete", True)
        if not isinstance(analysis_complete, bool):
            raise DailyRunOutputConflictError(
                "record-applicability analysis_complete must be a strict boolean"
            )
        resolution_sha256 = payload.get("resolution_sha256")
        _require_sha256(resolution_sha256, "resolution_sha256")
        bindings = payload.get("record_rule_resolutions")
        diagnostics = payload.get("diagnostics")
        resolution_diagnostics = payload.get("record_resolution_diagnostics")
        field_mapping_identity = payload.get("field_mapping_identity")
        if (
            not isinstance(bindings, list)
            or not isinstance(diagnostics, list)
            or not isinstance(resolution_diagnostics, list)
            or not isinstance(field_mapping_identity, Mapping)
        ):
            raise DailyRunOutputConflictError(
                "record-applicability snapshot requires mapping identity, "
                "bindings and diagnostics"
            )
        required_mapping_identity = {
            "schema_version",
            "batch_id",
            "project_id",
            "batch_version",
            "mapping_revision",
            "mapping_sha256",
            "mapping_content_sha256",
            "source_batch_id",
            "source_profile_sha256",
        }
        if not required_mapping_identity.issubset(field_mapping_identity):
            raise DailyRunOutputConflictError(
                "record field-mapping identity is incomplete"
            )
        if (
            field_mapping_identity["schema_version"]
            != "monitoring_record_field_mapping_identity.v1"
            or str(field_mapping_identity["project_id"])
            != str(payload.get("project_id") or "")
            or str(field_mapping_identity["batch_id"])
            != str(payload.get("batch_id") or "")
            or str(field_mapping_identity["mapping_revision"])
            != str(payload.get("mapping_revision") or "")
        ):
            raise DailyRunOutputConflictError(
                "record field-mapping identity does not match the rule snapshot"
            )
        try:
            mapping_batch_version = int(field_mapping_identity["batch_version"])
            payload_batch_version = int(payload.get("batch_version"))
        except (TypeError, ValueError) as exc:
            raise DailyRunOutputConflictError(
                "record field-mapping batch version must be an integer"
            ) from exc
        if mapping_batch_version != payload_batch_version:
            raise DailyRunOutputConflictError(
                "record field-mapping batch version does not match the snapshot"
            )
        for field in (
            "mapping_sha256",
            "mapping_content_sha256",
            "source_profile_sha256",
        ):
            _require_sha256(field_mapping_identity[field], field)
        if not str(field_mapping_identity["source_batch_id"] or "").strip():
            raise DailyRunOutputConflictError(
                "record field-mapping source batch identity is empty"
            )
        expected_resolution_sha256 = _content_sha256(
            {
                "project_id": str(payload.get("project_id") or ""),
                "batch_id": str(payload.get("batch_id") or ""),
                "field_mapping_identity": dict(field_mapping_identity),
                "bindings": bindings,
                "diagnostics": resolution_diagnostics,
            }
        )
        if resolution_sha256 != expected_resolution_sha256:
            raise DailyRunOutputConflictError(
                "record rule resolution identity hash does not match snapshot"
            )
        required = {
            "current_business_key",
            "current_domain",
            "centre_id",
            "subject_id",
            "event_date",
            "centre_source_fields",
            "subject_source_fields",
            "event_date_source_fields",
            "compatibility_fallback_roles",
            "assignment_id",
            "assignment_state_version",
            "protocol_version_id",
            "rule_pack_id",
            "rule_pack_revision",
            "rule_pack_content_sha256",
        }
        business_keys: set[str] = set()
        pack_ids: set[str] = set()
        for binding in bindings:
            if not isinstance(binding, Mapping) or not required.issubset(binding):
                raise DailyRunOutputConflictError(
                    "record rule binding is incomplete"
                )
            if any(
                not str(binding.get(field) or "").strip()
                for field in required
                - {
                    "assignment_state_version",
                    "rule_pack_revision",
                    "subject_id",
                    "subject_source_fields",
                    "compatibility_fallback_roles",
                }
            ):
                raise DailyRunOutputConflictError(
                    "record rule binding contains an empty identity"
                )
            for field in (
                "centre_source_fields",
                "subject_source_fields",
                "event_date_source_fields",
                "compatibility_fallback_roles",
            ):
                value = binding[field]
                if not isinstance(value, (list, tuple)) or any(
                    not str(item).strip() for item in value
                ):
                    raise DailyRunOutputConflictError(
                        f"record rule binding {field} must be a text list"
                    )
            if not binding["centre_source_fields"] or not binding[
                "event_date_source_fields"
            ]:
                raise DailyRunOutputConflictError(
                    "record rule binding anchor source identity is incomplete"
                )
            if any(
                role not in {"centre", "subject", "event_date"}
                for role in binding["compatibility_fallback_roles"]
            ):
                raise DailyRunOutputConflictError(
                    "record rule binding compatibility fallback role is invalid"
                )
            try:
                assignment_state_version = int(
                    binding["assignment_state_version"]
                )
                rule_pack_revision = int(binding["rule_pack_revision"])
            except (TypeError, ValueError) as exc:
                raise DailyRunOutputConflictError(
                    "record rule binding versions must be integers"
                ) from exc
            if assignment_state_version < 1:
                raise DailyRunOutputConflictError(
                    "assignment_state_version must be positive"
                )
            if rule_pack_revision < 1:
                raise DailyRunOutputConflictError(
                    "rule_pack_revision must be positive"
                )
            _require_sha256(
                binding["rule_pack_content_sha256"],
                "rule_pack_content_sha256",
            )
            business_key = str(binding["current_business_key"])
            if business_key in business_keys:
                raise DailyRunOutputConflictError(
                    "record rule bindings contain duplicate business keys"
                )
            business_keys.add(business_key)
            pack_ids.add(str(binding["rule_pack_id"]))
        declared_pack_ids = {
            str(value).strip()
            for value in payload.get("rule_pack_ids") or ()
            if str(value).strip()
        }
        if declared_pack_ids != pack_ids:
            raise DailyRunOutputConflictError(
                "record rule binding pack identities are inconsistent"
            )
        expected_single = next(iter(pack_ids)) if len(pack_ids) == 1 else ""
        if str(payload.get("rule_pack_id") or "").strip() != expected_single:
            raise DailyRunOutputConflictError(
                "record-applicability snapshot uses an invalid aggregate pack identity"
            )
        if not bindings and not diagnostics:
            raise DailyRunOutputConflictError(
                "record-applicability snapshot cannot be empty"
            )
        if diagnostics and analysis_complete:
            raise DailyRunOutputConflictError(
                "record resolution diagnostics require an incomplete analysis state"
            )

    @staticmethod
    def _baseline(row: sqlite3.Row) -> ProjectMonitoringBaseline:
        try:
            def required_text(value: object, label: str) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise ValueError(f"persisted monitoring baseline {label} is invalid")
                return value

            revision = row["revision"]
            if (
                isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 1
            ):
                raise ValueError("persisted monitoring baseline revision is invalid")
            confirmed_at = _datetime(
                required_text(row["confirmed_at"], "confirmed_at")
            )
            if confirmed_at is None:
                raise ValueError("persisted monitoring baseline timestamp is invalid")
            return ProjectMonitoringBaseline(
                project_id=required_text(row["project_id"], "project_id"),
                current_baseline_batch_id=required_text(
                    row["current_baseline_batch_id"],
                    "current_baseline_batch_id",
                ),
                confirmed_run_id=required_text(
                    row["confirmed_run_id"],
                    "confirmed_run_id",
                ),
                revision=revision,
                confirmed_at=confirmed_at,
                confirmed_by=required_text(row["confirmed_by"], "confirmed_by"),
            )
        except Exception as exc:
            raise MonitoringDailyRunRepositoryError(
                "persisted monitoring baseline is invalid"
            ) from exc
