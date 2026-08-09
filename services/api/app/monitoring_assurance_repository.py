from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, FrozenSet, Iterator, List, Mapping, Optional, Tuple
from uuid import uuid4

from .monitoring_audit_contract import (
    MonitoringAuditEvent,
    verify_monitoring_audit_chain,
)
from .monitoring_identity_authorization import (
    MonitoringAuthorizationDecision,
    MonitoringPrincipal,
)


ASSURANCE_TASK_MODES = ("pre_lock", "pre_inspection")
ASSURANCE_TASK_STATES = (
    "draft",
    "ready",
    "full_recompute_recorded",
    "medical_review",
    "ready_to_complete",
    "completed",
    "superseded",
)
_TERMINAL_STATES: FrozenSet[str] = frozenset({"completed", "superseded"})
_ACTIVE_STATES: FrozenSet[str] = frozenset(
    {"draft", "ready", "full_recompute_recorded", "medical_review", "ready_to_complete"}
)
_NEXT_STATES: Dict[str, FrozenSet[str]] = {
    "draft": frozenset({"ready", "medical_review", "draft"}),
    "ready": frozenset({"full_recompute_recorded", "medical_review", "ready", "draft"}),
    "full_recompute_recorded": frozenset({"medical_review", "full_recompute_recorded", "ready"}),
    "medical_review": frozenset({"ready_to_complete", "completed", "medical_review", "full_recompute_recorded", "ready"}),
    "ready_to_complete": frozenset({"completed", "ready_to_complete", "medical_review"}),
    "completed": frozenset(),
    "superseded": frozenset(),
}
_FROZEN_IDENTITY_FIELDS = (
    "batch_id",
    "batch_revision",
    "mapping_revision",
    "protocol_version_id",
    "rule_pack_revision",
    "dictionary_revision",
    "ctcae_revision",
    "model_revision",
    "risk_snapshot_id",
)


class MonitoringAssuranceError(ValueError):
    pass


class AssuranceTaskNotFoundError(MonitoringAssuranceError):
    pass


class AssuranceTaskStateConflictError(MonitoringAssuranceError):
    pass


class AssuranceVersionConflictError(MonitoringAssuranceError):
    pass


class AssuranceIdempotencyConflictError(MonitoringAssuranceError):
    pass


class AssuranceDriftError(MonitoringAssuranceError):
    pass


class AssuranceReadinessError(MonitoringAssuranceError):
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


def _require_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MonitoringAssuranceError(f"{field} is required")
    return normalized


def _optional_text(value: Any) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized or None


def _nonnegative_int(value: Any, field: str, *, default: int = 0) -> int:
    """Accept only explicit non-negative integer counts.

    Do not let ``int(True)`` or ``int(False)`` turn malformed proof payloads
    into seemingly valid counts.  Numeric strings are accepted for JSON
    compatibility, while floats, booleans, blanks and negatives fail closed.
    """

    if value is None:
        value = default
    if isinstance(value, bool):
        raise MonitoringAssuranceError(f"{field} must be a non-negative integer")
    if isinstance(value, int):
        if value >= 0:
            return value
        raise MonitoringAssuranceError(f"{field} must be a non-negative integer")
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    raise MonitoringAssuranceError(f"{field} must be a non-negative integer")


def _strict_bool(value: Any, field: str, *, default: bool = False) -> bool:
    """Accept a real boolean only; string values must not be coerced."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise MonitoringAssuranceError(f"{field} must be boolean")


def _sqlite_bool(value: Any, field: str) -> bool:
    """Read a SQLite INTEGER boolean without accepting arbitrary truthiness."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return value == 1
    raise MonitoringAssuranceError(f"{field} must be SQLite boolean 0 or 1")


@dataclass(frozen=True)
class FrozenIdentity:
    """Frozen source/mapping/protocol/rule/dictionary/CTCAE/model/risk-snapshot identities.

    Any drift in any field closes the task — it cannot continue and must be recreated.
    """

    batch_id: str
    batch_revision: str
    mapping_revision: str
    protocol_version_id: str
    rule_pack_revision: str
    dictionary_revision: str
    ctcae_revision: str
    model_revision: str
    risk_snapshot_id: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    def identity_hash(self) -> str:
        return _content_sha256(self.to_dict())

    def matches(self, other: Mapping[str, Any]) -> bool:
        for field in _FROZEN_IDENTITY_FIELDS:
            if str(self.to_dict().get(field, "")).strip() != str(other.get(field, "")).strip():
                return False
        return True


@dataclass(frozen=True)
class AssuranceTask:
    task_id: str
    project_id: str
    mode: str
    status: str
    version: int
    frozen_identity: FrozenIdentity
    created_at: datetime
    updated_at: datetime
    created_by: str
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    owner: Optional[str] = None
    lock_impact: Optional[str] = None
    medical_review_recorded: bool = False
    full_recompute_proof_id: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATES

    @property
    def is_active(self) -> bool:
        return self.status in _ACTIVE_STATES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "mode": self.mode,
            "status": self.status,
            "version": self.version,
            "frozen_identity": self.frozen_identity.to_dict(),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "created_by": self.created_by,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": _iso(self.confirmed_at),
            "owner": self.owner,
            "lock_impact": self.lock_impact,
            "medical_review_recorded": self.medical_review_recorded,
            "full_recompute_proof_id": self.full_recompute_proof_id,
        }


@dataclass(frozen=True)
class AssuranceTaskMutationResult:
    task: AssuranceTask
    replayed: bool


@dataclass(frozen=True)
class MonitoringAssuranceAuditContext:
    """Server-bound authorization evidence carried into one repository write."""

    principal: MonitoringPrincipal
    decision: MonitoringAuthorizationDecision
    signature_evidence_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.decision.allowed or not self.decision.write_permitted:
            raise MonitoringAssuranceError(
                "assurance audit context requires an allowed write decision"
            )
        if self.decision.principal_id != self.principal.principal_id:
            raise MonitoringAssuranceError(
                "audit decision principal does not match the principal snapshot"
            )
        if self.decision.project_id not in self.principal.project_scope:
            raise MonitoringAssuranceError(
                "audit decision project is outside the principal scope"
            )
        signature = self.signature_evidence_sha256
        if signature is None:
            signature = ""
        if not isinstance(signature, str) or (
            signature
            and (
                len(signature) != 64
                or any(char not in "0123456789abcdef" for char in signature)
            )
        ):
            raise MonitoringAssuranceError(
                "signature_evidence_sha256 must be a lowercase SHA-256"
            )
        object.__setattr__(self, "signature_evidence_sha256", signature)


@dataclass(frozen=True)
class AssuranceEvent:
    event_seq: int
    task_id: str
    project_id: str
    task_version: int
    event_type: str
    actor: str
    payload: Dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class FullRecomputeProof:
    proof_id: str
    task_id: str
    project_id: str
    mode: str
    planned_subjects: int
    actual_subjects: int
    planned_sites: int
    actual_sites: int
    critical_domains: Tuple[str, ...]
    planned_rules: int
    actual_rules: int
    per_domain_counts: Tuple[Dict[str, Any], ...]
    failures: int
    skips: int
    retries: int
    pinned_risk_snapshot_id: str
    subject_reconciliation_ok: bool
    site_reconciliation_ok: bool
    trial_reconciliation_ok: bool
    open_high_risk_count: int
    open_risk_count: int
    closed_risks_lacking_evidence_count: int
    owner: str
    lock_impact: str
    content_sha256: str
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proof_id": self.proof_id,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "mode": self.mode,
            "planned_subjects": self.planned_subjects,
            "actual_subjects": self.actual_subjects,
            "planned_sites": self.planned_sites,
            "actual_sites": self.actual_sites,
            "critical_domains": list(self.critical_domains),
            "planned_rules": self.planned_rules,
            "actual_rules": self.actual_rules,
            "per_domain_counts": [dict(item) for item in self.per_domain_counts],
            "failures": self.failures,
            "skips": self.skips,
            "retries": self.retries,
            "pinned_risk_snapshot_id": self.pinned_risk_snapshot_id,
            "subject_reconciliation_ok": self.subject_reconciliation_ok,
            "site_reconciliation_ok": self.site_reconciliation_ok,
            "trial_reconciliation_ok": self.trial_reconciliation_ok,
            "open_high_risk_count": self.open_high_risk_count,
            "open_risk_count": self.open_risk_count,
            "closed_risks_lacking_evidence_count": self.closed_risks_lacking_evidence_count,
            "owner": self.owner,
            "lock_impact": self.lock_impact,
            "content_sha256": self.content_sha256,
            "created_at": _iso(self.created_at),
        }


@dataclass(frozen=True)
class RollupSummary:
    """Pre-inspection three-level rollup — stores IDs/references only, never risk facts."""

    task_id: str
    project_id: str
    risk_snapshot_id: str
    subject_rollup: Tuple[Dict[str, Any], ...]
    site_rollup: Tuple[Dict[str, Any], ...]
    trial_rollup: Dict[str, Any]
    distributions: Dict[str, Any]
    remediation_matrix: Tuple[Dict[str, Any], ...]
    evidence_manifest: Tuple[Dict[str, Any], ...]
    content_sha256: str
    created_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "project_id": self.project_id,
            "risk_snapshot_id": self.risk_snapshot_id,
            "subject_rollup": [dict(item) for item in self.subject_rollup],
            "site_rollup": [dict(item) for item in self.site_rollup],
            "trial_rollup": dict(self.trial_rollup),
            "distributions": dict(self.distributions),
            "remediation_matrix": [dict(item) for item in self.remediation_matrix],
            "evidence_manifest": [dict(item) for item in self.evidence_manifest],
            "content_sha256": self.content_sha256,
            "created_at": _iso(self.created_at),
        }


def _normalize_frozen_identity(payload: Mapping[str, Any]) -> FrozenIdentity:
    return FrozenIdentity(
        batch_id=_require_text(payload.get("batch_id"), "batch_id"),
        batch_revision=_require_text(payload.get("batch_revision"), "batch_revision"),
        mapping_revision=_require_text(payload.get("mapping_revision"), "mapping_revision"),
        protocol_version_id=_require_text(
            payload.get("protocol_version_id"), "protocol_version_id"
        ),
        rule_pack_revision=_require_text(payload.get("rule_pack_revision"), "rule_pack_revision"),
        dictionary_revision=_require_text(payload.get("dictionary_revision"), "dictionary_revision"),
        ctcae_revision=_require_text(payload.get("ctcae_revision"), "ctcae_revision"),
        model_revision=_require_text(payload.get("model_revision"), "model_revision"),
        risk_snapshot_id=_require_text(payload.get("risk_snapshot_id"), "risk_snapshot_id"),
    )


class MonitoringAssuranceRepository:
    """Durable SQLite repository for P8 pre-lock / pre-inspection assurance tasks.

    Owns its own SQLite file — it never reads or modifies the runtime medical-risk
    database. It stores frozen public identities, references, rollups, and execution
    proofs only; it never copies risk facts or evidence blobs.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        db_path: Path,
        *,
        clock: Any = _utc_now,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
        mode_values = ", ".join(f"'{mode}'" for mode in ASSURANCE_TASK_MODES)
        state_values = ", ".join(f"'{state}'" for state in ASSURANCE_TASK_STATES)
        statements = (
            f"""
            CREATE TABLE IF NOT EXISTS monitoring_assurance_tasks (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                mode TEXT NOT NULL CHECK(mode IN ({mode_values})),
                status TEXT NOT NULL CHECK(status IN ({state_values})),
                version INTEGER NOT NULL CHECK(version >= 1),
                frozen_identity_json TEXT NOT NULL,
                identity_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                confirmed_by TEXT NOT NULL DEFAULT '',
                confirmed_at TEXT NOT NULL DEFAULT '',
                owner TEXT NOT NULL DEFAULT '',
                lock_impact TEXT NOT NULL DEFAULT '',
                medical_review_recorded INTEGER NOT NULL DEFAULT 0,
                full_recompute_proof_id TEXT
            )
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_assurance_one_active_per_project_mode
                ON monitoring_assurance_tasks(project_id, mode)
                WHERE status NOT IN ('completed', 'superseded')
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_assurance_full_recompute_proofs (
                proof_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL UNIQUE,
                project_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                proof_json TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES monitoring_assurance_tasks(task_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_assurance_rollups (
                task_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                risk_snapshot_id TEXT NOT NULL,
                rollup_json TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES monitoring_assurance_tasks(task_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_assurance_events (
                event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                task_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES monitoring_assurance_tasks(task_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_assurance_audit_chain (
                event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_id TEXT NOT NULL UNIQUE,
                task_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                prev_event_hash TEXT NOT NULL DEFAULT '',
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES monitoring_assurance_tasks(task_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_assurance_idempotency (
                project_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                task_id TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, idempotency_key),
                FOREIGN KEY(task_id) REFERENCES monitoring_assurance_tasks(task_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_assurance_tasks_project
                ON monitoring_assurance_tasks(project_id, mode, status)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_assurance_events_task
                ON monitoring_assurance_events(task_id, event_seq)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_assurance_audit_project
                ON monitoring_assurance_audit_chain(project_id, event_seq)
            """,
        )
        with self._connect() as connection:
            for statement in statements:
                connection.execute(statement)

    # ------------------------------------------------------------------
    # Row conversion helpers
    # ------------------------------------------------------------------

    def _task_from_row(self, row: sqlite3.Row) -> AssuranceTask:
        def persisted_text(value: object, field: str) -> str:
            if not isinstance(value, str) or not value or value.strip() != value:
                raise AssuranceDriftError(
                    f"persisted assurance task {field} is invalid"
                )
            return value

        def persisted_optional_text(value: object, field: str) -> Optional[str]:
            if value is None or value == "":
                return None
            return persisted_text(value, field)

        try:
            frozen_identity_raw = row["frozen_identity_json"]
            if not isinstance(frozen_identity_raw, str):
                raise AssuranceDriftError(
                    "persisted assurance task frozen identity is invalid"
                )
            frozen_payload = json.loads(frozen_identity_raw)
            frozen = _normalize_frozen_identity(frozen_payload)
        except (KeyError, TypeError, ValueError, MonitoringAssuranceError) as exc:
            raise AssuranceDriftError(
                "persisted assurance task frozen identity is invalid"
            ) from exc
        declared_hash = row["identity_hash"]
        if (
            not isinstance(declared_hash, str)
            or not declared_hash
            or _content_sha256(frozen.to_dict()) != declared_hash
        ):
            raise AssuranceDriftError(
                "persisted assurance task identity hash mismatch"
            )
        try:
            task_id = persisted_text(row["task_id"], "task_id")
            project_id = persisted_text(row["project_id"], "project_id")
            mode = persisted_text(row["mode"], "mode")
            if mode not in ASSURANCE_TASK_MODES:
                raise AssuranceDriftError(
                    "persisted assurance task mode is invalid"
                )
            status = persisted_text(row["status"], "status")
            if status not in ASSURANCE_TASK_STATES:
                raise AssuranceDriftError(
                    "persisted assurance task status is invalid"
                )
            version = row["version"]
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise AssuranceDriftError(
                    "persisted assurance task version is invalid"
                )
            try:
                created_at = _datetime(row["created_at"])
                updated_at = _datetime(row["updated_at"])
                confirmed_at = _datetime(row["confirmed_at"])
            except (TypeError, ValueError) as exc:
                raise AssuranceDriftError(
                    "persisted assurance task timestamps are invalid"
                ) from exc
            if created_at is None or updated_at is None:
                raise AssuranceDriftError(
                    "persisted assurance task timestamps are invalid"
                )
            medical_review_recorded = _sqlite_bool(
                row["medical_review_recorded"],
                "medical_review_recorded",
            )
            return AssuranceTask(
                task_id=task_id,
                project_id=project_id,
                mode=mode,
                status=status,
                version=version,
                frozen_identity=frozen,
                created_at=created_at,
                updated_at=updated_at,
                created_by=persisted_text(row["created_by"], "created_by"),
                confirmed_by=persisted_optional_text(
                    row["confirmed_by"], "confirmed_by"
                ),
                confirmed_at=confirmed_at,
                owner=persisted_optional_text(row["owner"], "owner"),
                lock_impact=persisted_optional_text(
                    row["lock_impact"], "lock_impact"
                ),
                medical_review_recorded=medical_review_recorded,
                full_recompute_proof_id=persisted_optional_text(
                    row["full_recompute_proof_id"], "full_recompute_proof_id"
                ),
            )
        except AssuranceDriftError:
            raise
        except MonitoringAssuranceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise AssuranceDriftError(
                "persisted assurance task root is invalid"
            ) from exc

    def _proof_from_row(self, row: sqlite3.Row) -> FullRecomputeProof:
        def persisted_text(value: object, field: str) -> str:
            if not isinstance(value, str) or not value or value.strip() != value:
                raise AssuranceDriftError(
                    f"persisted assurance proof {field} is invalid"
                )
            return value

        try:
            proof_raw = row["proof_json"]
            if not isinstance(proof_raw, str):
                raise AssuranceDriftError(
                    "persisted assurance proof payload is invalid"
                )
            payload = json.loads(proof_raw)
            if not isinstance(payload, Mapping):
                raise AssuranceDriftError(
                    "persisted assurance proof payload is invalid"
                )

            for field_name in ("proof_id", "task_id", "project_id"):
                payload_value = _require_text(payload.get(field_name), field_name)
                row_value = persisted_text(row[field_name], field_name)
                if payload_value != row_value:
                    raise AssuranceDriftError(
                        "persisted assurance proof identity does not match its row"
                    )

            mode = _require_text(payload.get("mode"), "mode")
            row_mode = persisted_text(row["mode"], "mode")
            if mode not in ASSURANCE_TASK_MODES or mode != row_mode:
                raise AssuranceDriftError("persisted assurance proof mode is invalid")

            critical_domains_payload = payload.get("critical_domains")
            if not isinstance(critical_domains_payload, (list, tuple)) or any(
                not isinstance(item, str) or not item.strip()
                for item in critical_domains_payload
            ):
                raise AssuranceDriftError(
                    "persisted assurance proof critical_domains is invalid"
                )

            per_domain_payload = payload.get("per_domain_counts")
            if not isinstance(per_domain_payload, (list, tuple)) or any(
                not isinstance(item, Mapping) for item in per_domain_payload
            ):
                raise AssuranceDriftError(
                    "persisted assurance proof per_domain_counts is invalid"
                )

            created_at_text = payload.get("created_at")
            try:
                created_at = _datetime(created_at_text)
                row_created_at = _datetime(row["created_at"])
            except (TypeError, ValueError) as exc:
                raise AssuranceDriftError(
                    "persisted assurance proof timestamps are invalid"
                ) from exc
            if (
                created_at is None
                or row_created_at is None
                or created_at.isoformat() != row_created_at.isoformat()
            ):
                raise AssuranceDriftError(
                    "persisted assurance proof timestamps are invalid"
                )

            proof = FullRecomputeProof(
                proof_id=_require_text(payload.get("proof_id"), "proof_id"),
                task_id=_require_text(payload.get("task_id"), "task_id"),
                project_id=_require_text(payload.get("project_id"), "project_id"),
                mode=mode,
                planned_subjects=_nonnegative_int(
                    payload.get("planned_subjects"), "planned_subjects"
                ),
                actual_subjects=_nonnegative_int(
                    payload.get("actual_subjects"), "actual_subjects"
                ),
                planned_sites=_nonnegative_int(
                    payload.get("planned_sites"), "planned_sites"
                ),
                actual_sites=_nonnegative_int(
                    payload.get("actual_sites"), "actual_sites"
                ),
                critical_domains=tuple(critical_domains_payload),
                planned_rules=_nonnegative_int(
                    payload.get("planned_rules"), "planned_rules"
                ),
                actual_rules=_nonnegative_int(
                    payload.get("actual_rules"), "actual_rules"
                ),
                per_domain_counts=tuple(dict(item) for item in per_domain_payload),
                failures=_nonnegative_int(payload.get("failures"), "failures"),
                skips=_nonnegative_int(payload.get("skips"), "skips"),
                retries=_nonnegative_int(payload.get("retries"), "retries"),
                pinned_risk_snapshot_id=_require_text(
                    payload.get("pinned_risk_snapshot_id"),
                    "pinned_risk_snapshot_id",
                ),
                subject_reconciliation_ok=_strict_bool(
                    payload.get("subject_reconciliation_ok"),
                    "subject_reconciliation_ok",
                ),
                site_reconciliation_ok=_strict_bool(
                    payload.get("site_reconciliation_ok"),
                    "site_reconciliation_ok",
                ),
                trial_reconciliation_ok=_strict_bool(
                    payload.get("trial_reconciliation_ok"),
                    "trial_reconciliation_ok",
                ),
                open_high_risk_count=_nonnegative_int(
                    payload.get("open_high_risk_count"), "open_high_risk_count"
                ),
                open_risk_count=_nonnegative_int(
                    payload.get("open_risk_count"), "open_risk_count"
                ),
                closed_risks_lacking_evidence_count=_nonnegative_int(
                    payload.get("closed_risks_lacking_evidence_count"),
                    "closed_risks_lacking_evidence_count",
                ),
                owner=_require_text(payload.get("owner"), "owner"),
                lock_impact=_require_text(payload.get("lock_impact"), "lock_impact"),
                content_sha256=_require_text(
                    payload.get("content_sha256"), "content_sha256"
                ),
                created_at=created_at,
            )
            declared_hash = proof.content_sha256
            stored_hash = _require_text(row["content_sha256"], "content_sha256")
            if declared_hash != stored_hash:
                raise AssuranceDriftError(
                    "persisted assurance proof content hash mismatch"
                )
            unhashed_payload = proof.to_dict()
            unhashed_payload["content_sha256"] = ""
            if _content_sha256(unhashed_payload) != declared_hash:
                raise AssuranceDriftError(
                    "persisted assurance proof content hash mismatch"
                )
            return proof
        except AssuranceDriftError:
            raise
        except MonitoringAssuranceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise AssuranceDriftError(
                "persisted assurance proof is invalid"
            ) from exc

    def _row_to_event(
        self,
        row: sqlite3.Row,
        *,
        expected_task_id: str = "",
        expected_project_id: str = "",
    ) -> AssuranceEvent:
        try:
            event_seq = row["event_seq"]
            task_version = row["task_version"]
            if (
                isinstance(event_seq, bool)
                or not isinstance(event_seq, int)
                or event_seq < 1
                or isinstance(task_version, bool)
                or not isinstance(task_version, int)
                or task_version < 1
            ):
                raise AssuranceDriftError(
                    "persisted assurance event sequence/version is invalid"
                )
            task_id = _require_text(row["task_id"], "task_id")
            project_id = _require_text(row["project_id"], "project_id")
            if (
                (expected_task_id and task_id != expected_task_id)
                or (expected_project_id and project_id != expected_project_id)
            ):
                raise AssuranceDriftError(
                    "persisted assurance event parent binding mismatch"
                )
            event_type = _require_text(row["event_type"], "event_type")
            actor = _require_text(row["actor"], "actor")
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, Mapping):
                raise AssuranceDriftError(
                    "persisted assurance event payload must be an object"
                )
            try:
                created_at = _datetime(row["created_at"])
            except (TypeError, ValueError) as exc:
                raise AssuranceDriftError(
                    "persisted assurance event timestamp is invalid"
                ) from exc
            if created_at is None:
                raise AssuranceDriftError(
                    "persisted assurance event timestamp is invalid"
                )
            return AssuranceEvent(
                event_seq=event_seq,
                task_id=task_id,
                project_id=project_id,
                task_version=task_version,
                event_type=event_type,
                actor=actor,
                payload=dict(payload),
                created_at=created_at,
            )
        except AssuranceDriftError:
            raise
        except (KeyError, TypeError, ValueError, MonitoringAssuranceError) as exc:
            raise AssuranceDriftError(
                "persisted assurance event is invalid"
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _task_payload(task: AssuranceTask) -> Dict[str, Any]:
        return task.to_dict()

    def _append_event(
        self,
        connection: sqlite3.Connection,
        task: AssuranceTask,
        event_type: str,
        actor: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        now = _iso(self.clock())
        connection.execute(
            """
            INSERT INTO monitoring_assurance_events
                (task_id, project_id, task_version, event_type, actor, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.task_id,
                task.project_id,
                task.version,
                event_type,
                actor,
                _canonical_json(dict(payload) if payload else {}),
                now,
            ),
        )

    @staticmethod
    def _audit_event_from_payload(
        payload: Mapping[str, Any],
        *,
        expected_project_id: str = "",
    ) -> MonitoringAuditEvent:
        event = MonitoringAuditEvent(
            audit_id=payload["audit_id"],
            project_id=payload["project_id"],
            principal_id=payload["principal_id"],
            role_claims=tuple(payload["role_claims"]),
            matched_roles=tuple(payload.get("matched_roles", [])),
            action=payload["action"],
            target_type=payload["target_type"],
            target_id=payload["target_id"],
            source_revision=payload["source_revision"],
            authorization_decision_sha256=payload[
                "authorization_decision_sha256"
            ],
            decision_allowed=payload["decision_allowed"],
            write_permitted=payload["write_permitted"],
            mutation_applied=payload["mutation_applied"],
            aggregate_version_before=payload["aggregate_version_before"],
            aggregate_version_after=payload["aggregate_version_after"],
            occurred_at=datetime.fromisoformat(payload["occurred_at"]),
            prev_event_hash=payload.get("prev_event_hash", ""),
            payload=payload.get("payload", {}),
            event_hash=payload.get("event_hash", ""),
        )
        if expected_project_id and event.project_id != expected_project_id:
            raise MonitoringAssuranceError(
                "persisted assurance audit project binding mismatch"
            )
        return event

    def _append_audit_event(
        self,
        connection: sqlite3.Connection,
        *,
        task: AssuranceTask,
        audit_context: Optional[MonitoringAssuranceAuditContext],
        mutation_applied: bool,
        aggregate_version_before: int,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> Optional[MonitoringAuditEvent]:
        """Append the server-bound hash event inside the domain transaction."""

        if audit_context is None:
            return None
        rows = connection.execute(
            """
            SELECT event_json
            FROM monitoring_assurance_audit_chain
            WHERE project_id = ?
            ORDER BY event_seq
            """,
            (task.project_id,),
        ).fetchall()
        try:
            existing_events = tuple(
                self._audit_event_from_payload(json.loads(row["event_json"]))
                for row in rows
            )
            previous_hash = verify_monitoring_audit_chain(existing_events)
        except (KeyError, TypeError, ValueError) as exc:
            raise MonitoringAssuranceError(
                "persisted assurance audit chain is invalid"
            ) from exc

        audit_id = "assurance_" + _content_sha256(
            {
                "project_id": task.project_id,
                "request_id": audit_context.decision.request_id,
                "action": audit_context.decision.action.value,
            }
        )
        event_payload = dict(payload or {})
        if audit_context.signature_evidence_sha256:
            event_payload["signature_evidence_sha256"] = (
                audit_context.signature_evidence_sha256
            )
        event_payload.setdefault("task_id", task.task_id)
        event_payload.setdefault("task_version", aggregate_version_before)
        try:
            event = MonitoringAuditEvent.from_authorization_decision(
                audit_id=audit_id,
                principal=audit_context.principal,
                decision=audit_context.decision,
                target_type="project",
                target_id=task.project_id,
                source_revision=task.frozen_identity.identity_hash(),
                mutation_applied=mutation_applied,
                aggregate_version_before=aggregate_version_before,
                aggregate_version_after=task.version,
                occurred_at=self.clock(),
                prev_event_hash=previous_hash,
                payload=event_payload,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MonitoringAssuranceError(
                "server authorization evidence cannot be audited"
            ) from exc
        if existing_events:
            existing = next(
                (item for item in existing_events if item.audit_id == event.audit_id),
                None,
            )
            if existing is not None:
                if existing.event_hash == event.event_hash:
                    return existing
                raise MonitoringAssuranceError(
                    "assurance audit id was reused with a different payload"
                )
        connection.execute(
            """
            INSERT INTO monitoring_assurance_audit_chain
                (audit_id, task_id, project_id, event_hash, prev_event_hash, event_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.audit_id,
                task.task_id,
                task.project_id,
                event.event_hash,
                event.prev_event_hash,
                _canonical_json(event.public_dict()),
                _iso(event.occurred_at),
            ),
        )
        return event

    @staticmethod
    def _audit_request_binding(
        audit_context: Optional[MonitoringAssuranceAuditContext],
    ) -> Dict[str, str]:
        if audit_context is None:
            return {}
        binding = {
            "authorization_decision_sha256": audit_context.decision.decision_sha256,
            "principal_sha256": audit_context.principal.principal_sha256,
        }
        if audit_context.signature_evidence_sha256:
            binding["signature_evidence_sha256"] = (
                audit_context.signature_evidence_sha256
            )
        return binding

    def _check_idempotency(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        idempotency_key: str,
        operation: str,
        request_payload: Mapping[str, Any],
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        request_sha = _content_sha256(request_payload)
        row = connection.execute(
            """
            SELECT task_id, operation, request_sha256, response_json, created_at
            FROM monitoring_assurance_idempotency
            WHERE project_id = ? AND idempotency_key = ?
            """,
            (project_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha:
            raise AssuranceIdempotencyConflictError(
                "idempotency_key replayed with a different request payload"
            )
        stored_operation = _require_text(row["operation"], "operation")
        if stored_operation != operation:
            raise AssuranceIdempotencyConflictError(
                "idempotency_key replayed for a different operation"
            )
        task_id = _require_text(row["task_id"], "task_id")
        try:
            created_at = _datetime(row["created_at"])
        except (TypeError, ValueError) as exc:
            raise AssuranceDriftError(
                "persisted assurance idempotency timestamp is invalid"
            ) from exc
        if created_at is None:
            raise AssuranceDriftError(
                "persisted assurance idempotency timestamp is invalid"
            )
        try:
            response = json.loads(row["response_json"])
        except (TypeError, ValueError) as exc:
            raise AssuranceDriftError(
                "persisted assurance idempotency response is invalid"
            ) from exc
        if not isinstance(response, Mapping):
            raise AssuranceDriftError(
                "persisted assurance idempotency response is invalid"
            )
        task_payload = response.get("task")
        if task_payload is not None:
            if not isinstance(task_payload, Mapping):
                raise AssuranceDriftError(
                    "persisted assurance idempotency task response is invalid"
                )
            if _require_text(task_payload.get("task_id"), "task_id") != task_id:
                raise AssuranceDriftError(
                    "persisted assurance idempotency task binding mismatch"
                )
        response_task_id = response.get("task_id")
        if response_task_id is not None and _require_text(
            response_task_id, "task_id"
        ) != task_id:
            raise AssuranceDriftError(
                "persisted assurance idempotency task binding mismatch"
            )
        return task_id, dict(response)

    def _store_idempotency(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        idempotency_key: str,
        operation: str,
        request_payload: Mapping[str, Any],
        task_id: str,
        response: Mapping[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO monitoring_assurance_idempotency
                (project_id, idempotency_key, operation, request_sha256, task_id, response_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                idempotency_key,
                operation,
                _content_sha256(request_payload),
                task_id,
                _canonical_json(response),
                _iso(self.clock()),
            ),
        )

    def _get_task_row(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        task_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM monitoring_assurance_tasks
            WHERE task_id = ? AND project_id = ?
            """,
            (task_id, project_id),
        ).fetchone()
        if row is None:
            raise AssuranceTaskNotFoundError(
                f"assurance task {task_id} not found in project {project_id}"
            )
        return row

    @staticmethod
    def _verify_expected_version(row: sqlite3.Row, expected_version: int) -> None:
        if row["version"] != expected_version:
            raise AssuranceVersionConflictError(
                f"version CAS conflict: expected {expected_version}, "
                f"found {row['version']}"
            )

    @staticmethod
    def _verify_state_transition(current: str, target: str) -> None:
        if target not in _NEXT_STATES.get(current, frozenset()):
            raise AssuranceTaskStateConflictError(
                f"transition from '{current}' to '{target}' is not allowed"
            )

    def _verify_not_drifted(
        self,
        task: AssuranceTask,
        frozen_identity: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if frozen_identity is None:
            return
        if not task.frozen_identity.matches(frozen_identity):
            raise AssuranceDriftError(
                "frozen identity drift detected — task must be recreated"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_task(
        self,
        *,
        project_id: str,
        mode: str,
        frozen_identity: Mapping[str, Any],
        idempotency_key: str,
        actor: str,
        owner: str = "",
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> AssuranceTaskMutationResult:
        project_id = _require_text(project_id, "project_id")
        mode = _require_text(mode, "mode")
        if mode not in ASSURANCE_TASK_MODES:
            raise MonitoringAssuranceError(f"unsupported mode: {mode}")
        actor = _require_text(actor, "actor")
        frozen = _normalize_frozen_identity(frozen_identity)
        request_payload: Dict[str, Any] = {
            "project_id": project_id,
            "mode": mode,
            "frozen_identity": frozen.to_dict(),
            "actor": actor,
            "owner": owner,
            "audit_binding": self._audit_request_binding(audit_context),
        }
        with self._transaction() as connection:
            replayed = self._check_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="create_task",
                request_payload=request_payload,
            )
            if replayed is not None:
                task = self._task_from_row(
                    self._get_task_row(connection, project_id, replayed[0])
                )
                return AssuranceTaskMutationResult(task=task, replayed=True)

            existing_active = connection.execute(
                """
                SELECT task_id FROM monitoring_assurance_tasks
                WHERE project_id = ? AND mode = ?
                  AND status NOT IN ('completed', 'superseded')
                """,
                (project_id, mode),
            ).fetchone()
            if existing_active is not None:
                raise AssuranceTaskStateConflictError(
                    f"project {project_id} already has an active {mode} task: "
                    f"{existing_active['task_id']}"
                )

            task_id = f"assurance_{uuid4().hex[:16]}"
            now = self.clock()
            now_text = _iso(now)
            task = AssuranceTask(
                task_id=task_id,
                project_id=project_id,
                mode=mode,
                status="draft",
                version=1,
                frozen_identity=frozen,
                created_at=now,
                updated_at=now,
                created_by=actor,
                owner=_optional_text(owner),
            )
            connection.execute(
                """
                INSERT INTO monitoring_assurance_tasks
                    (task_id, project_id, mode, status, version,
                     frozen_identity_json, identity_hash,
                     created_at, updated_at, created_by, owner)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.project_id,
                    task.mode,
                    task.status,
                    task.version,
                    _canonical_json(frozen.to_dict()),
                    frozen.identity_hash(),
                    now_text,
                    now_text,
                    actor,
                    task.owner or "",
                ),
            )
            self._append_event(
                connection,
                task,
                "task_created",
                actor,
                {"mode": mode, "frozen_identity": frozen.to_dict(), "owner": task.owner},
            )
            self._append_audit_event(
                connection,
                task=task,
                audit_context=audit_context,
                mutation_applied=True,
                aggregate_version_before=0,
                payload={
                    "operation": "task_created",
                    "mode": mode,
                    "frozen_identity_sha256": frozen.identity_hash(),
                },
            )
            response = {"task": task.to_dict(), "replayed": False}
            self._store_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="create_task",
                request_payload=request_payload,
                task_id=task.task_id,
                response=response,
            )
            return AssuranceTaskMutationResult(task=task, replayed=False)

    def get(self, project_id: str, task_id: str) -> AssuranceTask:
        with self._connect() as connection:
            return self._task_from_row(
                self._get_task_row(connection, project_id, task_id)
            )

    def list_tasks(
        self,
        project_id: str,
        *,
        mode: Optional[str] = None,
        include_terminal: bool = True,
    ) -> List[AssuranceTask]:
        with self._connect() as connection:
            if mode and not include_terminal:
                rows = connection.execute(
                    """
                    SELECT * FROM monitoring_assurance_tasks
                    WHERE project_id = ? AND mode = ?
                      AND status NOT IN ('completed', 'superseded')
                    ORDER BY created_at DESC
                    """,
                    (project_id, mode),
                ).fetchall()
            elif mode:
                rows = connection.execute(
                    """
                    SELECT * FROM monitoring_assurance_tasks
                    WHERE project_id = ? AND mode = ?
                    ORDER BY created_at DESC
                    """,
                    (project_id, mode),
                ).fetchall()
            elif not include_terminal:
                rows = connection.execute(
                    """
                    SELECT * FROM monitoring_assurance_tasks
                    WHERE project_id = ?
                      AND status NOT IN ('completed', 'superseded')
                    ORDER BY created_at DESC
                    """,
                    (project_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM monitoring_assurance_tasks
                    WHERE project_id = ?
                    ORDER BY created_at DESC
                    """,
                    (project_id,),
                ).fetchall()
            return [self._task_from_row(row) for row in rows]

    def transition(
        self,
        *,
        project_id: str,
        task_id: str,
        target_status: str,
        expected_version: int,
        actor: str,
        frozen_identity: Optional[Mapping[str, Any]] = None,
        owner: Optional[str] = None,
        lock_impact: Optional[str] = None,
    ) -> AssuranceTask:
        if target_status not in ASSURANCE_TASK_STATES:
            raise MonitoringAssuranceError(f"unsupported target status: {target_status}")
        with self._transaction() as connection:
            row = self._get_task_row(connection, project_id, task_id)
            self._verify_expected_version(row, expected_version)
            task = self._task_from_row(row)
            self._verify_not_drifted(task, frozen_identity)
            self._verify_state_transition(task.status, target_status)

            updates: Dict[str, Any] = {}
            if owner is not None:
                updates["owner"] = _optional_text(owner)
            if lock_impact is not None:
                updates["lock_impact"] = _optional_text(lock_impact)

            now_text = _iso(self.clock())
            new_version = task.version + 1
            new_task = replace(
                task,
                status=target_status,
                version=new_version,
                updated_at=_datetime(now_text) or _utc_now(),
                owner=updates.get("owner", task.owner),
                lock_impact=updates.get("lock_impact", task.lock_impact),
            )
            set_parts = ["status = ?", "version = ?", "updated_at = ?"]
            set_values: List[Any] = [target_status, new_version, now_text]
            if "owner" in updates:
                set_parts.append("owner = ?")
                set_values.append(updates["owner"] or "")
            if "lock_impact" in updates:
                set_parts.append("lock_impact = ?")
                set_values.append(updates["lock_impact"] or "")
            connection.execute(
                f"""
                UPDATE monitoring_assurance_tasks
                SET {", ".join(set_parts)}
                WHERE task_id = ? AND project_id = ?
                """,
                (*set_values, task_id, project_id),
            )
            self._append_event(
                connection,
                new_task,
                f"task_transitioned:{target_status}",
                actor,
                {
                    "from": task.status,
                    "to": target_status,
                    "expected_version": expected_version,
                    **updates,
                },
            )
            return new_task

    def save_full_recompute_proof(
        self,
        *,
        project_id: str,
        task_id: str,
        proof_payload: Mapping[str, Any],
        expected_version: int,
        actor: str,
        idempotency_key: str,
        frozen_identity: Optional[Mapping[str, Any]] = None,
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> Tuple[AssuranceTask, FullRecomputeProof, bool]:
        project_id = _require_text(project_id, "project_id")
        request_payload: Dict[str, Any] = {
            "project_id": project_id,
            "task_id": task_id,
            "proof_payload": dict(proof_payload),
            "expected_version": expected_version,
            "actor": actor,
            "audit_binding": self._audit_request_binding(audit_context),
        }
        with self._transaction() as connection:
            replayed_entry = self._check_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="save_full_recompute_proof",
                request_payload=request_payload,
            )
            if replayed_entry is not None:
                _, response = replayed_entry
                task = self._task_from_row(
                    self._get_task_row(connection, project_id, response["task"]["task_id"])
                )
                proof_row = connection.execute(
                    "SELECT * FROM monitoring_assurance_full_recompute_proofs WHERE task_id = ?",
                    (task.task_id,),
                ).fetchone()
                proof = self._proof_from_row(proof_row) if proof_row else None
                if proof is None:
                    raise AssuranceTaskNotFoundError("proof missing on idempotent replay")
                return task, proof, True

            row = self._get_task_row(connection, project_id, task_id)
            self._verify_expected_version(row, expected_version)
            task = self._task_from_row(row)
            self._verify_not_drifted(task, frozen_identity)

            pinned_snapshot = _require_text(
                proof_payload.get("pinned_risk_snapshot_id"),
                "pinned_risk_snapshot_id",
            )
            if pinned_snapshot != task.frozen_identity.risk_snapshot_id:
                raise AssuranceDriftError(
                    "full recompute proof must pin a newly generated risk snapshot "
                    "that matches the task's frozen identity"
                )

            proof_id = f"recompute_{uuid4().hex[:16]}"
            now = self.clock()
            now_text = _iso(now)
            critical_domains = tuple(
                str(d).strip().upper()
                for d in proof_payload.get("critical_domains", [])
                if str(d).strip()
            )
            per_domain = tuple(
                dict(item) for item in proof_payload.get("per_domain_counts", [])
            )
            proof = FullRecomputeProof(
                proof_id=proof_id,
                task_id=task.task_id,
                project_id=task.project_id,
                mode=task.mode,
                planned_subjects=_nonnegative_int(
                    proof_payload.get("planned_subjects"), "planned_subjects"
                ),
                actual_subjects=_nonnegative_int(
                    proof_payload.get("actual_subjects"), "actual_subjects"
                ),
                planned_sites=_nonnegative_int(
                    proof_payload.get("planned_sites"), "planned_sites"
                ),
                actual_sites=_nonnegative_int(
                    proof_payload.get("actual_sites"), "actual_sites"
                ),
                critical_domains=critical_domains,
                planned_rules=_nonnegative_int(
                    proof_payload.get("planned_rules"), "planned_rules"
                ),
                actual_rules=_nonnegative_int(
                    proof_payload.get("actual_rules"), "actual_rules"
                ),
                per_domain_counts=per_domain,
                failures=_nonnegative_int(
                    proof_payload.get("failures"), "failures"
                ),
                skips=_nonnegative_int(proof_payload.get("skips"), "skips"),
                retries=_nonnegative_int(proof_payload.get("retries"), "retries"),
                pinned_risk_snapshot_id=pinned_snapshot,
                subject_reconciliation_ok=_strict_bool(
                    proof_payload.get("subject_reconciliation_ok"),
                    "subject_reconciliation_ok",
                ),
                site_reconciliation_ok=_strict_bool(
                    proof_payload.get("site_reconciliation_ok"),
                    "site_reconciliation_ok",
                ),
                trial_reconciliation_ok=_strict_bool(
                    proof_payload.get("trial_reconciliation_ok"),
                    "trial_reconciliation_ok",
                ),
                open_high_risk_count=_nonnegative_int(
                    proof_payload.get("open_high_risk_count"),
                    "open_high_risk_count",
                ),
                open_risk_count=_nonnegative_int(
                    proof_payload.get("open_risk_count"), "open_risk_count"
                ),
                closed_risks_lacking_evidence_count=_nonnegative_int(
                    proof_payload.get("closed_risks_lacking_evidence_count"),
                    "closed_risks_lacking_evidence_count",
                ),
                owner=_require_text(proof_payload.get("owner"), "owner"),
                lock_impact=_require_text(proof_payload.get("lock_impact"), "lock_impact"),
                content_sha256="",
                created_at=now,
            )
            content = proof.to_dict()
            content_sha = _content_sha256(content)
            proof = replace(proof, content_sha256=content_sha)
            connection.execute(
                """
                INSERT INTO monitoring_assurance_full_recompute_proofs
                    (proof_id, task_id, project_id, mode, proof_json, content_sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proof.proof_id,
                    proof.task_id,
                    proof.project_id,
                    proof.mode,
                    _canonical_json(proof.to_dict()),
                    content_sha,
                    now_text,
                ),
            )
            new_version = task.version + 1
            new_task = replace(
                task,
                status="full_recompute_recorded",
                version=new_version,
                updated_at=now,
                full_recompute_proof_id=proof.proof_id,
            )
            connection.execute(
                """
                UPDATE monitoring_assurance_tasks
                SET status = ?, version = ?, updated_at = ?, full_recompute_proof_id = ?
                WHERE task_id = ? AND project_id = ?
                """,
                (
                    new_task.status,
                    new_version,
                    now_text,
                    proof.proof_id,
                    task_id,
                    project_id,
                ),
            )
            self._append_event(
                connection,
                new_task,
                "full_recompute_proof_recorded",
                actor,
                {
                    "proof_id": proof.proof_id,
                    "content_sha256": content_sha,
                    "pinned_risk_snapshot_id": pinned_snapshot,
                },
            )
            self._append_audit_event(
                connection,
                task=new_task,
                audit_context=audit_context,
                mutation_applied=True,
                aggregate_version_before=task.version,
                payload={
                    "operation": "full_recompute_proof_recorded",
                    "proof_id": proof.proof_id,
                    "content_sha256": content_sha,
                },
            )
            response = {"task": new_task.to_dict(), "replayed": False}
            self._store_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="save_full_recompute_proof",
                request_payload=request_payload,
                task_id=new_task.task_id,
                response=response,
            )
            return new_task, proof, False

    def get_full_recompute_proof(
        self,
        project_id: str,
        task_id: str,
    ) -> Optional[FullRecomputeProof]:
        with self._connect() as connection:
            self._get_task_row(connection, project_id, task_id)
            row = connection.execute(
                """
                SELECT * FROM monitoring_assurance_full_recompute_proofs
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            return self._proof_from_row(row) if row else None

    def save_rollup(
        self,
        *,
        project_id: str,
        task_id: str,
        rollup_payload: Mapping[str, Any],
        expected_version: int,
        actor: str,
        idempotency_key: str,
        frozen_identity: Optional[Mapping[str, Any]] = None,
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> Tuple[AssuranceTask, RollupSummary, bool]:
        request_payload: Dict[str, Any] = {
            "project_id": project_id,
            "task_id": task_id,
            "rollup_payload": dict(rollup_payload),
            "expected_version": expected_version,
            "actor": actor,
            "audit_binding": self._audit_request_binding(audit_context),
        }
        with self._transaction() as connection:
            replayed_entry = self._check_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="save_rollup",
                request_payload=request_payload,
            )
            if replayed_entry is not None:
                _, response = replayed_entry
                task = self._task_from_row(
                    self._get_task_row(connection, project_id, response["task"]["task_id"])
                )
                rollup_row = connection.execute(
                    "SELECT * FROM monitoring_assurance_rollups WHERE task_id = ?",
                    (task.task_id,),
                ).fetchone()
                if rollup_row is None:
                    raise AssuranceTaskNotFoundError("rollup missing on idempotent replay")
                return (
                    task,
                    self._rollup_from_row(
                        rollup_row,
                        expected_task_id=task.task_id,
                        expected_project_id=task.project_id,
                    ),
                    True,
                )

            row = self._get_task_row(connection, project_id, task_id)
            self._verify_expected_version(row, expected_version)
            task = self._task_from_row(row)
            self._verify_not_drifted(task, frozen_identity)

            snapshot_id = _require_text(
                rollup_payload.get("risk_snapshot_id"), "risk_snapshot_id"
            )
            if snapshot_id != task.frozen_identity.risk_snapshot_id:
                raise AssuranceDriftError(
                    "rollup risk snapshot must match the task's frozen identity"
                )
            now = self.clock()
            summary = RollupSummary(
                task_id=task.task_id,
                project_id=task.project_id,
                risk_snapshot_id=snapshot_id,
                subject_rollup=tuple(rollup_payload.get("subject_rollup", [])),
                site_rollup=tuple(rollup_payload.get("site_rollup", [])),
                trial_rollup=dict(rollup_payload.get("trial_rollup", {})),
                distributions=dict(rollup_payload.get("distributions", {})),
                remediation_matrix=tuple(rollup_payload.get("remediation_matrix", [])),
                evidence_manifest=tuple(rollup_payload.get("evidence_manifest", [])),
                content_sha256="",
                created_at=now,
            )
            content_sha = _content_sha256(summary.to_dict())
            summary = replace(summary, content_sha256=content_sha)
            now_text = _iso(now)
            connection.execute(
                """
                INSERT INTO monitoring_assurance_rollups
                    (task_id, project_id, risk_snapshot_id, rollup_json, content_sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    rollup_json = excluded.rollup_json,
                    content_sha256 = excluded.content_sha256,
                    created_at = excluded.created_at
                """,
                (
                    summary.task_id,
                    summary.project_id,
                    summary.risk_snapshot_id,
                    _canonical_json(summary.to_dict()),
                    content_sha,
                    now_text,
                ),
            )
            new_task = replace(
                task,
                version=task.version + 1,
                updated_at=now,
            )
            connection.execute(
                """
                UPDATE monitoring_assurance_tasks
                SET version = ?, updated_at = ?
                WHERE task_id = ? AND project_id = ?
                """,
                (new_task.version, now_text, task_id, project_id),
            )
            self._append_event(
                connection,
                new_task,
                "rollup_generated",
                actor,
                {
                    "risk_snapshot_id": snapshot_id,
                    "content_sha256": content_sha,
                },
            )
            self._append_audit_event(
                connection,
                task=new_task,
                audit_context=audit_context,
                mutation_applied=True,
                aggregate_version_before=task.version,
                payload={
                    "operation": "rollup_generated",
                    "risk_snapshot_id": snapshot_id,
                    "content_sha256": content_sha,
                },
            )
            response = {"task": new_task.to_dict(), "replayed": False}
            self._store_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="save_rollup",
                request_payload=request_payload,
                task_id=new_task.task_id,
                response=response,
            )
            return new_task, summary, False

    def _rollup_from_row(
        self,
        row: sqlite3.Row,
        *,
        expected_task_id: str = "",
        expected_project_id: str = "",
    ) -> RollupSummary:
        try:
            payload = json.loads(row["rollup_json"])
            if not isinstance(payload, Mapping):
                raise AssuranceDriftError(
                    "persisted assurance rollup payload is invalid"
                )

            def persisted_text(value: object, field: str) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise AssuranceDriftError(
                        f"persisted assurance rollup {field} is invalid"
                    )
                return value

            row_identity = {
                "task_id": persisted_text(row["task_id"], "task_id"),
                "project_id": persisted_text(row["project_id"], "project_id"),
                "risk_snapshot_id": persisted_text(
                    row["risk_snapshot_id"], "risk_snapshot_id"
                ),
            }
            payload_identity = {
                field_name: _require_text(payload.get(field_name), field_name)
                for field_name in row_identity
            }
            if payload_identity != row_identity:
                raise AssuranceDriftError(
                    "persisted assurance rollup identity does not match its row"
                )
            if (
                expected_task_id
                and payload_identity["task_id"] != expected_task_id
            ) or (
                expected_project_id
                and payload_identity["project_id"] != expected_project_id
            ):
                raise AssuranceDriftError(
                    "persisted assurance rollup parent binding mismatch"
                )

            def _mapping_sequence(field_name: str) -> Tuple[Dict[str, Any], ...]:
                value = payload.get(field_name)
                if not isinstance(value, (list, tuple)) or any(
                    not isinstance(item, Mapping) for item in value
                ):
                    raise AssuranceDriftError(
                        f"persisted assurance rollup {field_name} is invalid"
                    )
                return tuple(dict(item) for item in value)

            subject_rollup = _mapping_sequence("subject_rollup")
            site_rollup = _mapping_sequence("site_rollup")
            remediation_matrix = _mapping_sequence("remediation_matrix")
            evidence_manifest = _mapping_sequence("evidence_manifest")
            trial_rollup = payload.get("trial_rollup")
            distributions = payload.get("distributions")
            if not isinstance(trial_rollup, Mapping):
                raise AssuranceDriftError(
                    "persisted assurance rollup trial_rollup is invalid"
                )
            if not isinstance(distributions, Mapping):
                raise AssuranceDriftError(
                    "persisted assurance rollup distributions is invalid"
                )

            created_at_text = payload.get("created_at")
            try:
                created_at = _datetime(created_at_text)
                row_created_at = _datetime(row["created_at"])
            except (TypeError, ValueError) as exc:
                raise AssuranceDriftError(
                    "persisted assurance rollup timestamps are invalid"
                ) from exc
            if (
                created_at is None
                or row_created_at is None
                or created_at.isoformat() != row_created_at.isoformat()
            ):
                raise AssuranceDriftError(
                    "persisted assurance rollup timestamps are invalid"
                )

            declared_hash = _require_text(
                payload.get("content_sha256"), "content_sha256"
            )
            stored_hash = _require_text(row["content_sha256"], "content_sha256")
            if declared_hash != stored_hash:
                raise AssuranceDriftError(
                    "persisted assurance rollup content hash mismatch"
                )
            summary = RollupSummary(
                task_id=payload_identity["task_id"],
                project_id=payload_identity["project_id"],
                risk_snapshot_id=payload_identity["risk_snapshot_id"],
                subject_rollup=subject_rollup,
                site_rollup=site_rollup,
                trial_rollup=dict(trial_rollup),
                distributions=dict(distributions),
                remediation_matrix=remediation_matrix,
                evidence_manifest=evidence_manifest,
                content_sha256=declared_hash,
                created_at=created_at,
            )
            unhashed_payload = summary.to_dict()
            unhashed_payload["content_sha256"] = ""
            if _content_sha256(unhashed_payload) != declared_hash:
                raise AssuranceDriftError(
                    "persisted assurance rollup content hash mismatch"
                )
            return summary
        except AssuranceDriftError:
            raise
        except MonitoringAssuranceError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise AssuranceDriftError(
                "persisted assurance rollup is invalid"
            ) from exc

    def get_rollup(
        self,
        project_id: str,
        task_id: str,
    ) -> Optional[RollupSummary]:
        with self._connect() as connection:
            self._get_task_row(connection, project_id, task_id)
            row = connection.execute(
                "SELECT * FROM monitoring_assurance_rollups WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            return (
                self._rollup_from_row(
                    row,
                    expected_task_id=task_id,
                    expected_project_id=project_id,
                )
                if row
                else None
            )

    def record_medical_review(
        self,
        *,
        project_id: str,
        task_id: str,
        expected_version: int,
        actor: str,
        idempotency_key: str,
        review_payload: Mapping[str, Any],
        owner: Optional[str] = None,
        lock_impact: Optional[str] = None,
        frozen_identity: Optional[Mapping[str, Any]] = None,
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> AssuranceTask:
        request_payload: Dict[str, Any] = {
            "project_id": project_id,
            "task_id": task_id,
            "expected_version": expected_version,
            "actor": actor,
            "review_payload": dict(review_payload),
            "owner": owner,
            "lock_impact": lock_impact,
            "audit_binding": self._audit_request_binding(audit_context),
        }
        with self._transaction() as connection:
            replayed_entry = self._check_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="record_medical_review",
                request_payload=request_payload,
            )
            if replayed_entry is not None:
                _, response = replayed_entry
                return self._task_from_row(
                    self._get_task_row(
                        connection, project_id, response["task_id"]
                    )
                )

            row = self._get_task_row(connection, project_id, task_id)
            self._verify_expected_version(row, expected_version)
            task = self._task_from_row(row)
            self._verify_not_drifted(task, frozen_identity)
            self._verify_state_transition(task.status, "medical_review")

            now = self.clock()
            now_text = _iso(now)
            new_version = task.version + 1
            owner_val = _optional_text(owner) if owner is not None else task.owner
            lock_val = (
                _optional_text(lock_impact)
                if lock_impact is not None
                else task.lock_impact
            )
            new_task = replace(
                task,
                status="medical_review",
                version=new_version,
                updated_at=now,
                medical_review_recorded=True,
                owner=owner_val,
                lock_impact=lock_val,
            )
            set_parts = [
                "status = ?",
                "version = ?",
                "updated_at = ?",
                "medical_review_recorded = 1",
            ]
            set_values: List[Any] = [new_task.status, new_version, now_text]
            if owner is not None:
                set_parts.append("owner = ?")
                set_values.append(owner_val or "")
            if lock_impact is not None:
                set_parts.append("lock_impact = ?")
                set_values.append(lock_val or "")
            connection.execute(
                f"""
                UPDATE monitoring_assurance_tasks
                SET {", ".join(set_parts)}
                WHERE task_id = ? AND project_id = ?
                """,
                (*set_values, task_id, project_id),
            )
            self._append_event(
                connection,
                new_task,
                "medical_review_recorded",
                actor,
                {
                    "review_payload": dict(review_payload),
                    "owner": owner_val,
                    "lock_impact": lock_val,
                },
            )
            self._append_audit_event(
                connection,
                task=new_task,
                audit_context=audit_context,
                mutation_applied=True,
                aggregate_version_before=task.version,
                payload={
                    "operation": "medical_review_recorded",
                    "review_payload_sha256": _content_sha256(review_payload),
                    "owner": owner_val,
                    "lock_impact": lock_val,
                },
            )
            self._store_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="record_medical_review",
                request_payload=request_payload,
                task_id=new_task.task_id,
                response={"task_id": new_task.task_id},
            )
            return new_task

    def complete_task(
        self,
        *,
        project_id: str,
        task_id: str,
        expected_version: int,
        confirmed_by: str,
        idempotency_key: str,
        frozen_identity: Optional[Mapping[str, Any]] = None,
        audit_context: Optional[MonitoringAssuranceAuditContext] = None,
    ) -> AssuranceTask:
        request_payload: Dict[str, Any] = {
            "project_id": project_id,
            "task_id": task_id,
            "expected_version": expected_version,
            "confirmed_by": confirmed_by,
            "audit_binding": self._audit_request_binding(audit_context),
        }
        with self._transaction() as connection:
            replayed_entry = self._check_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="complete_task",
                request_payload=request_payload,
            )
            if replayed_entry is not None:
                _, response = replayed_entry
                return self._task_from_row(
                    self._get_task_row(
                        connection, project_id, response["task_id"]
                    )
                )

            row = self._get_task_row(connection, project_id, task_id)
            self._verify_expected_version(row, expected_version)
            task = self._task_from_row(row)
            self._verify_not_drifted(task, frozen_identity)
            if not task.medical_review_recorded:
                raise AssuranceTaskStateConflictError(
                    "medical review must be recorded before completion"
                )
            self._verify_state_transition(task.status, "completed")

            now = self.clock()
            now_text = _iso(now)
            new_version = task.version + 1
            new_task = replace(
                task,
                status="completed",
                version=new_version,
                updated_at=now,
                confirmed_by=_optional_text(confirmed_by) or task.created_by,
                confirmed_at=now,
            )
            connection.execute(
                """
                UPDATE monitoring_assurance_tasks
                SET status = ?, version = ?, updated_at = ?, confirmed_by = ?, confirmed_at = ?
                WHERE task_id = ? AND project_id = ?
                """,
                (
                    new_task.status,
                    new_version,
                    now_text,
                    new_task.confirmed_by or "",
                    now_text,
                    task_id,
                    project_id,
                ),
            )
            self._append_event(
                connection,
                new_task,
                "task_completed",
                confirmed_by,
                {"confirmed_at": now_text},
            )
            self._append_audit_event(
                connection,
                task=new_task,
                audit_context=audit_context,
                mutation_applied=True,
                aggregate_version_before=task.version,
                payload={
                    "operation": "task_completed",
                    "confirmed_by_principal": new_task.confirmed_by,
                },
            )
            self._store_idempotency(
                connection,
                project_id=project_id,
                idempotency_key=idempotency_key,
                operation="complete_task",
                request_payload=request_payload,
                task_id=new_task.task_id,
                response={"task_id": new_task.task_id},
            )
            return new_task

    def list_events(
        self,
        project_id: str,
        task_id: str,
    ) -> List[AssuranceEvent]:
        with self._connect() as connection:
            self._get_task_row(connection, project_id, task_id)
            rows = connection.execute(
                """
                SELECT * FROM monitoring_assurance_events
                WHERE task_id = ?
                ORDER BY event_seq
                """,
                (task_id,),
            ).fetchall()
            return [
                self._row_to_event(
                    row,
                    expected_task_id=task_id,
                    expected_project_id=project_id,
                )
                for row in rows
            ]

    def list_audit_events(
        self,
        project_id: str,
        task_id: str,
    ) -> List[MonitoringAuditEvent]:
        """Read and verify the persisted server-authorization audit chain."""

        with self._connect() as connection:
            self._get_task_row(connection, project_id, task_id)
            rows = connection.execute(
                """
                SELECT task_id, project_id, event_hash, prev_event_hash,
                       event_json, created_at
                FROM monitoring_assurance_audit_chain
                WHERE project_id = ?
                ORDER BY event_seq
                """,
                (project_id,),
            ).fetchall()
            try:
                parsed_rows: List[Tuple[MonitoringAuditEvent, str]] = []
                for row in rows:
                    row_project_id = _require_text(row["project_id"], "project_id")
                    row_task_id = _require_text(row["task_id"], "task_id")
                    if row_project_id != project_id:
                        raise AssuranceDriftError(
                            "persisted assurance audit project binding mismatch"
                        )
                    event = self._audit_event_from_payload(
                        json.loads(row["event_json"]),
                        expected_project_id=project_id,
                    )
                    if row["event_hash"] != event.event_hash:
                        raise AssuranceDriftError(
                            "persisted assurance audit row hash mismatch"
                        )
                    if row["prev_event_hash"] != event.prev_event_hash:
                        raise AssuranceDriftError(
                            "persisted assurance audit row predecessor mismatch"
                        )
                    try:
                        row_created_at = _datetime(row["created_at"])
                    except (TypeError, ValueError) as exc:
                        raise AssuranceDriftError(
                            "persisted assurance audit row timestamp is invalid"
                        ) from exc
                    if (
                        row_created_at is None
                        or row_created_at.isoformat()
                        != event.occurred_at.isoformat()
                    ):
                        raise AssuranceDriftError(
                            "persisted assurance audit row timestamp is invalid"
                        )
                    event_task_id = event.payload.get("task_id")
                    if event_task_id is not None and _require_text(
                        event_task_id, "task_id"
                    ) != row_task_id:
                        raise AssuranceDriftError(
                            "persisted assurance audit task binding mismatch"
                        )
                    parsed_rows.append((event, row_task_id))
                all_events = [event for event, _ in parsed_rows]
                verify_monitoring_audit_chain(all_events)
            except AssuranceDriftError:
                raise
            except MonitoringAssuranceError:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise MonitoringAssuranceError(
                    "persisted assurance audit chain is invalid"
                ) from exc
            return [
                event
                for event, row_task_id in parsed_rows
                if row_task_id == task_id
            ]
