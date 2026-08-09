from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)
from uuid import uuid4


class MonitoringBatchRepositoryError(ValueError):
    pass


class RepositoryIntegrityError(MonitoringBatchRepositoryError):
    pass


class RecordNotFoundError(MonitoringBatchRepositoryError):
    pass


class IdempotencyConflictError(MonitoringBatchRepositoryError):
    pass


class OptimisticVersionConflictError(MonitoringBatchRepositoryError):
    pass


class InvalidStateTransitionError(MonitoringBatchRepositoryError):
    pass


class FrozenBatchError(MonitoringBatchRepositoryError):
    pass


class TechnicalValidationError(MonitoringBatchRepositoryError):
    pass


class ContentValidationError(MonitoringBatchRepositoryError):
    pass


class DuplicateBusinessKeyError(MonitoringBatchRepositoryError):
    pass


class CompletenessGateError(MonitoringBatchRepositoryError):
    pass


BATCH_STATES = ("draft", "parsed", "validated", "confirmed", "frozen")
TECHNICAL_STATUSES = ("pending", "passed", "failed")
BASELINE_ELIGIBLE_SOURCE_CLASSES = {
    "raw_full_snapshot",
    "raw_full_snapshot_candidate",
    "verified_derived_full_snapshot",
}
_NEXT_STATE = {
    "draft": "parsed",
    "parsed": "validated",
    "validated": "confirmed",
    "confirmed": "frozen",
}


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _required_sha256(value: Any, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise RepositoryIntegrityError(
            f"frozen batch mapping {field} is invalid"
        )
    return normalized


def _require_exact_sha256(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or value != value.lower()
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RepositoryIntegrityError(
            f"{field} must be a canonical SHA-256 value"
        )
    return value


def _require_cache_identity_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or value != value.lower():
        raise RepositoryIntegrityError(
            f"field-profile cache identity {field} is not canonical"
        )
    normalized = value
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise RepositoryIntegrityError(
            f"field-profile cache identity {field} is invalid"
        )
    return normalized


def _rows_hash(rows: Iterable["NormalizedRow"]) -> str:
    digest = sha256()
    for row in rows:
        digest.update(_canonical_json(row.to_dict()).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _require_text(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise MonitoringBatchRepositoryError(f"{field} is required")
    return normalized


def _normalize_domains(domains: Iterable[str]) -> Tuple[str, ...]:
    normalized = sorted({_require_text(domain, "domain").upper() for domain in domains})
    return tuple(normalized)


@dataclass(frozen=True)
class SourceRegistration:
    source_id: str
    project_id: str
    source_entry_id: str
    validation_id: str
    validation_revision: int
    validator_version: str
    validation_use_status: str
    role: str
    source_class: str
    file_name: str
    content_sha256: str
    size_bytes: int
    parser_version: str
    technical_status: str
    content_warnings: Tuple[str, ...]
    medical_override_reason: Optional[str]
    binding_revision: int
    classification_version: str
    binding_sha256: str
    supersedes_source_id: Optional[str]
    blob_relative_path: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BatchRecord:
    batch_id: str
    project_id: str
    state: str
    version: int
    expected_domains: Tuple[str, ...]
    active_mapping_revision: Optional[str]
    full_snapshot_proof: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    frozen_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BatchMutationResult:
    batch: BatchRecord
    replayed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {"batch": self.batch.to_dict(), "replayed": self.replayed}


@dataclass(frozen=True)
class DerivedSnapshotVerificationResult:
    batch: BatchRecord
    proof: Dict[str, Any]
    source_summary: Dict[str, Any]
    fact_summary: Dict[str, Any]
    medical_summary: Dict[str, str]
    replayed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch": self.batch.to_dict(),
            "proof": dict(self.proof),
            "source": dict(self.source_summary),
            "facts": dict(self.fact_summary),
            "medical_summary": dict(self.medical_summary),
            "replayed": self.replayed,
        }


@dataclass(frozen=True)
class NormalizedRow:
    business_key: str
    domain: str
    data: Dict[str, Any]
    source_locator: Dict[str, Any]
    row_fingerprint: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DiffReadyBatch:
    batch_id: str
    project_id: str
    state: str
    version: int
    expected_domains: Tuple[str, ...]
    mapping_revision: Optional[str]
    source_bindings: Tuple[Tuple[str, str], ...]
    source_hashes: Tuple[str, ...]
    rows: Tuple[NormalizedRow, ...]
    schema_fields: Tuple[Tuple[str, str, str], ...] = ()
    full_snapshot_proven: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "project_id": self.project_id,
            "state": self.state,
            "version": self.version,
            "expected_domains": list(self.expected_domains),
            "mapping_revision": self.mapping_revision,
            "source_bindings": [
                {
                    "source_entry_id": source_entry_id,
                    "source_content_sha256": content_sha256,
                }
                for source_entry_id, content_sha256 in self.source_bindings
            ],
            "source_hashes": list(self.source_hashes),
            "schema_fields": [
                {
                    "domain": domain,
                    "field": field,
                    "source_sheet": source_sheet,
                }
                for domain, field, source_sheet in self.schema_fields
            ],
            "full_snapshot_proven": self.full_snapshot_proven,
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True)
class FieldProfileSourceBindingIdentity:
    source_id: str
    source_entry_id: str
    source_content_sha256: str
    binding_revision: int
    binding_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FieldProfileBatchIdentity:
    schema_version: str
    batch_id: str
    project_id: str
    state: str
    batch_version: int
    expected_domains: Tuple[str, ...]
    mapping_revision: Optional[str]
    source_bindings: Tuple[FieldProfileSourceBindingIdentity, ...]
    row_count: int
    row_set_sha256: str
    schema_field_count: int
    schema_fields_sha256: str
    content_identity_sha256: str
    source_binding_identity_sha256: str
    identity_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "project_id": self.project_id,
            "state": self.state,
            "batch_version": self.batch_version,
            "expected_domains": list(self.expected_domains),
            "mapping_revision": self.mapping_revision,
            "source_bindings": [
                binding.to_dict() for binding in self.source_bindings
            ],
            "row_count": self.row_count,
            "row_set_sha256": self.row_set_sha256,
            "schema_field_count": self.schema_field_count,
            "schema_fields_sha256": self.schema_fields_sha256,
            "content_identity_sha256": self.content_identity_sha256,
            "source_binding_identity_sha256": (
                self.source_binding_identity_sha256
            ),
            "identity_sha256": self.identity_sha256,
        }


@dataclass(frozen=True)
class FrozenBatchMappingContract:
    """Exact confirmed field mapping embedded in one frozen listing batch."""

    schema_version: str
    batch_id: str
    project_id: str
    batch_version: int
    mapping_revision: str
    mapping_sha256: str
    mapping_content_sha256: str
    source_batch_id: str
    source_profile_sha256: str
    fields: Tuple[Dict[str, Any], ...]
    semantic_quality_report_sha256: str = ""
    capability_manifest_sha256: str = ""
    activation_disposition: str = ""
    effective_capabilities_sha256: str = ""
    effective_capabilities: Tuple[str, ...] = ()
    capability_states: Tuple[Dict[str, Any], ...] = ()

    def identity_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "monitoring_record_field_mapping_identity.v1",
            "batch_id": self.batch_id,
            "project_id": self.project_id,
            "batch_version": self.batch_version,
            "mapping_revision": self.mapping_revision,
            "mapping_sha256": self.mapping_sha256,
            "mapping_content_sha256": self.mapping_content_sha256,
            "source_batch_id": self.source_batch_id,
            "source_profile_sha256": self.source_profile_sha256,
            "semantic_quality_report_sha256": (
                self.semantic_quality_report_sha256
            ),
            "capability_manifest_sha256": self.capability_manifest_sha256,
            "activation_disposition": self.activation_disposition,
            "effective_capabilities_sha256": (
                self.effective_capabilities_sha256
            ),
        }


@dataclass(frozen=True)
class BatchDiff:
    previous_batch_id: str
    current_batch_id: str
    added_business_keys: Tuple[str, ...]
    removed_business_keys: Tuple[str, ...]
    changed_business_keys: Tuple[str, ...]
    unchanged_business_keys: Tuple[str, ...]
    removal_eligible_business_keys: Tuple[str, ...] = ()
    removal_blocked_business_keys: Tuple[str, ...] = ()
    full_snapshot_proven: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MonitoringBatchRepository:
    """Durable, API-neutral ingestion repository for medical-monitoring listings."""

    def __init__(self, db_path: Path, object_root: Path):
        self.db_path = Path(db_path)
        self.object_root = Path(object_root)
        self.blob_root = self.object_root / "objects" / "sha256"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.blob_root.mkdir(parents=True, exist_ok=True)
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
        statements = (
            """
            CREATE TABLE IF NOT EXISTS monitoring_content_objects (
                content_sha256 TEXT PRIMARY KEY,
                size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                blob_relative_path TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_sources (
                source_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                source_entry_id TEXT NOT NULL,
                validation_id TEXT NOT NULL,
                validation_revision INTEGER NOT NULL CHECK(validation_revision >= 1),
                validator_version TEXT NOT NULL,
                validation_use_status TEXT NOT NULL,
                role TEXT NOT NULL,
                source_class TEXT NOT NULL,
                file_name TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                parser_version TEXT NOT NULL,
                technical_status TEXT NOT NULL
                    CHECK(technical_status IN ('pending', 'passed', 'failed')),
                content_warnings_json TEXT NOT NULL,
                medical_override_reason TEXT,
                binding_revision INTEGER NOT NULL CHECK(binding_revision >= 1),
                classification_version TEXT NOT NULL,
                binding_sha256 TEXT NOT NULL,
                supersedes_source_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(
                    project_id, source_entry_id, validation_id, binding_revision
                ),
                FOREIGN KEY(content_sha256)
                    REFERENCES monitoring_content_objects(content_sha256),
                FOREIGN KEY(supersedes_source_id)
                    REFERENCES monitoring_sources(source_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_batches (
                batch_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                state TEXT NOT NULL
                    CHECK(state IN ('draft', 'parsed', 'validated', 'confirmed', 'frozen')),
                version INTEGER NOT NULL CHECK(version >= 1),
                expected_domains_json TEXT NOT NULL,
                active_mapping_revision TEXT,
                full_snapshot_proof_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                frozen_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_batch_sources (
                batch_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                attached_at TEXT NOT NULL,
                PRIMARY KEY(batch_id, source_id),
                FOREIGN KEY(batch_id) REFERENCES monitoring_batches(batch_id),
                FOREIGN KEY(source_id) REFERENCES monitoring_sources(source_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_normalized_rows (
                batch_id TEXT NOT NULL,
                business_key TEXT NOT NULL,
                domain TEXT NOT NULL,
                data_json TEXT NOT NULL,
                source_locator_json TEXT NOT NULL,
                row_fingerprint TEXT NOT NULL,
                PRIMARY KEY(batch_id, business_key),
                FOREIGN KEY(batch_id) REFERENCES monitoring_batches(batch_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_batch_schema_fields (
                batch_id TEXT NOT NULL,
                domain TEXT NOT NULL,
                field_name TEXT NOT NULL,
                source_sheet TEXT NOT NULL,
                PRIMARY KEY(batch_id, domain, field_name, source_sheet),
                FOREIGN KEY(batch_id) REFERENCES monitoring_batches(batch_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_mapping_revisions (
                batch_id TEXT NOT NULL,
                mapping_revision TEXT NOT NULL,
                mapping_json TEXT NOT NULL,
                mapping_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(batch_id, mapping_revision),
                FOREIGN KEY(batch_id) REFERENCES monitoring_batches(batch_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_batch_events (
                event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                batch_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                state TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES monitoring_batches(batch_id),
                UNIQUE(batch_id, batch_version)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_idempotency (
                project_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                operation TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                response_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, idempotency_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitoring_derived_snapshot_proofs (
                proof_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                batch_id TEXT NOT NULL UNIQUE,
                source_id TEXT NOT NULL,
                source_content_sha256 TEXT NOT NULL,
                original_source_class TEXT NOT NULL,
                verified_source_class TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                transformation_type TEXT NOT NULL,
                execution_tool TEXT NOT NULL,
                execution_tool_version TEXT NOT NULL,
                original_parse_sheet_count INTEGER NOT NULL
                    CHECK(original_parse_sheet_count >= 1),
                original_parse_row_count INTEGER NOT NULL
                    CHECK(original_parse_row_count >= 0),
                original_parse_sheets_json TEXT NOT NULL,
                normalized_row_count INTEGER NOT NULL
                    CHECK(normalized_row_count >= 1),
                expected_domains_json TEXT NOT NULL,
                verified_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                canonical_proof_json TEXT NOT NULL,
                proof_sha256 TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES monitoring_batches(batch_id),
                FOREIGN KEY(source_id) REFERENCES monitoring_sources(source_id)
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS
                trg_monitoring_derived_snapshot_proofs_no_update
            BEFORE UPDATE ON monitoring_derived_snapshot_proofs
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'monitoring derived snapshot proofs are immutable'
                );
            END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS
                trg_monitoring_derived_snapshot_proofs_no_delete
            BEFORE DELETE ON monitoring_derived_snapshot_proofs
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'monitoring derived snapshot proofs are immutable'
                );
            END
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_sources_project
                ON monitoring_sources(project_id, source_class, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_sources_hash
                ON monitoring_sources(content_sha256)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_batches_project
                ON monitoring_batches(project_id, created_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_rows_domain
                ON monitoring_normalized_rows(batch_id, domain, business_key)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_batch_sources_source
                ON monitoring_batch_sources(source_id, batch_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_derived_snapshot_source
                ON monitoring_derived_snapshot_proofs(source_id, created_at)
            """,
        )
        connection = self._connect()
        try:
            # Rebuilding the source parent table is required to remove the legacy
            # inline UNIQUE constraint. Child references are checked explicitly
            # before commit and foreign-key enforcement is restored afterwards.
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            for statement in statements:
                connection.execute(statement)
            self._migrate_monitoring_sources(connection)
            violations = connection.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RepositoryIntegrityError(
                    "monitoring source migration produced foreign-key violations"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.close()

    @staticmethod
    def _migrate_monitoring_sources(connection: sqlite3.Connection) -> None:
        """Upgrade legacy source bindings to immutable, revisioned registrations."""
        columns = {
            str(row["name"])
            for row in connection.execute(
                "PRAGMA table_info(monitoring_sources)"
            ).fetchall()
        }
        revision_columns = {
            "binding_revision",
            "classification_version",
            "binding_sha256",
            "supersedes_source_id",
        }
        needs_rebuild = not revision_columns.issubset(columns)
        if not needs_rebuild:
            legacy_binding_indexes = []
            for index_row in connection.execute(
                "PRAGMA index_list(monitoring_sources)"
            ).fetchall():
                if not int(index_row["unique"]):
                    continue
                index_name = str(index_row["name"])
                index_columns = tuple(
                    str(row["name"])
                    for row in connection.execute(
                        f'PRAGMA index_info("{index_name}")'
                    ).fetchall()
                )
                if index_columns == (
                    "project_id",
                    "source_entry_id",
                    "validation_id",
                    "source_class",
                ) or index_columns == ("binding_sha256",):
                    legacy_binding_indexes.append(index_name)
            needs_rebuild = bool(legacy_binding_indexes)

        if needs_rebuild:
            lineage_order = [
                name
                for name in (
                    "project_id",
                    "source_entry_id",
                    "validation_id",
                    "created_at",
                    "source_id",
                )
                if name in columns
            ]
            legacy_rows = connection.execute(
                "SELECT * FROM monitoring_sources ORDER BY "
                + ", ".join(lineage_order)
            ).fetchall()
            legacy_columns = set(columns)
            connection.execute(
                """
                CREATE TABLE monitoring_sources__revision_migration (
                    source_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    source_entry_id TEXT NOT NULL,
                    validation_id TEXT NOT NULL,
                    validation_revision INTEGER NOT NULL
                        CHECK(validation_revision >= 1),
                    validator_version TEXT NOT NULL,
                    validation_use_status TEXT NOT NULL,
                    role TEXT NOT NULL,
                    source_class TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
                    parser_version TEXT NOT NULL,
                    technical_status TEXT NOT NULL
                        CHECK(technical_status IN ('pending', 'passed', 'failed')),
                    content_warnings_json TEXT NOT NULL,
                    medical_override_reason TEXT,
                    binding_revision INTEGER NOT NULL
                        CHECK(binding_revision >= 1),
                    classification_version TEXT NOT NULL,
                    binding_sha256 TEXT NOT NULL,
                    supersedes_source_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(
                        project_id, source_entry_id, validation_id,
                        binding_revision
                    ),
                    FOREIGN KEY(content_sha256)
                        REFERENCES monitoring_content_objects(content_sha256),
                    FOREIGN KEY(supersedes_source_id)
                        REFERENCES monitoring_sources(source_id)
                )
                """
            )
            lineage_state: Dict[Tuple[str, str, str], Tuple[int, Optional[str]]] = {}
            for row in legacy_rows:
                project_id = str(row["project_id"])
                source_entry_id = (
                    str(row["source_entry_id"])
                    if "source_entry_id" in legacy_columns
                    else ""
                )
                validation_id = (
                    str(row["validation_id"])
                    if "validation_id" in legacy_columns
                    else ""
                )
                lineage = (project_id, source_entry_id, validation_id)
                prior_revision, prior_source_id = lineage_state.get(lineage, (0, None))
                binding_revision = prior_revision + 1
                classification_version = (
                    str(row["classification_version"])
                    if "classification_version" in legacy_columns
                    and row["classification_version"]
                    else "legacy_unversioned"
                )
                metadata = {
                    "project_id": project_id,
                    "source_entry_id": source_entry_id,
                    "validation_id": validation_id,
                    "validation_revision": (
                        int(row["validation_revision"])
                        if "validation_revision" in legacy_columns
                        else 1
                    ),
                    "validator_version": (
                        str(row["validator_version"])
                        if "validator_version" in legacy_columns
                        else "legacy_unbound"
                    ),
                    "validation_use_status": (
                        str(row["validation_use_status"])
                        if "validation_use_status" in legacy_columns
                        else "legacy_unbound"
                    ),
                    "role": str(row["role"]),
                    "source_class": str(row["source_class"]),
                    "file_name": str(row["file_name"]),
                    "content_sha256": _require_exact_sha256(
                        row["content_sha256"],
                        "legacy source content hash",
                    ),
                    "size_bytes": int(row["size_bytes"]),
                    "parser_version": str(row["parser_version"]),
                    "technical_status": str(row["technical_status"]),
                    "content_warnings": json.loads(
                        str(row["content_warnings_json"])
                    ),
                    "medical_override_reason": (
                        str(row["medical_override_reason"])
                        if row["medical_override_reason"] is not None
                        else None
                    ),
                    "classification_version": classification_version,
                }
                binding_sha256 = _json_hash(metadata)
                supersedes_source_id = (
                    str(row["supersedes_source_id"])
                    if "supersedes_source_id" in legacy_columns
                    and row["supersedes_source_id"]
                    else prior_source_id
                )
                connection.execute(
                    """
                    INSERT INTO monitoring_sources__revision_migration(
                        source_id, project_id, source_entry_id, validation_id,
                        validation_revision, validator_version,
                        validation_use_status, role, source_class, file_name,
                        content_sha256, size_bytes, parser_version,
                        technical_status, content_warnings_json,
                        medical_override_reason, binding_revision,
                        classification_version, binding_sha256,
                        supersedes_source_id, created_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        str(row["source_id"]),
                        project_id,
                        source_entry_id,
                        validation_id,
                        metadata["validation_revision"],
                        metadata["validator_version"],
                        metadata["validation_use_status"],
                        metadata["role"],
                        metadata["source_class"],
                        metadata["file_name"],
                        metadata["content_sha256"],
                        metadata["size_bytes"],
                        metadata["parser_version"],
                        metadata["technical_status"],
                        _canonical_json(metadata["content_warnings"]),
                        metadata["medical_override_reason"],
                        binding_revision,
                        classification_version,
                        binding_sha256,
                        supersedes_source_id,
                        str(row["created_at"]),
                    ),
                )
                lineage_state[lineage] = (
                    binding_revision,
                    str(row["source_id"]),
                )
            connection.execute("DROP TABLE monitoring_sources")
            connection.execute(
                "ALTER TABLE monitoring_sources__revision_migration "
                "RENAME TO monitoring_sources"
            )

        connection.execute("DROP INDEX IF EXISTS idx_monitoring_source_registry_binding")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_monitoring_source_registry_binding
            ON monitoring_sources(
                project_id, source_entry_id, validation_id, binding_revision
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_monitoring_source_binding_sha256
            ON monitoring_sources(binding_sha256)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_sources_project
            ON monitoring_sources(project_id, source_class, created_at)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_sources_hash
            ON monitoring_sources(content_sha256)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_monitoring_source_lineage
            ON monitoring_sources(
                project_id, source_entry_id, validation_id, binding_revision
            )
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_monitoring_sources_no_update
            BEFORE UPDATE ON monitoring_sources
            BEGIN
                SELECT RAISE(ABORT, 'monitoring source bindings are immutable');
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_monitoring_sources_no_delete
            BEFORE DELETE ON monitoring_sources
            BEGIN
                SELECT RAISE(ABORT, 'monitoring source bindings are immutable');
            END
            """
        )

    def _blob_path(self, content_sha256: str) -> Path:
        return self.blob_root / content_sha256[:2] / content_sha256

    @staticmethod
    def _hash_file(path: Path) -> Tuple[str, int]:
        digest = sha256()
        size = 0
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def _store_object(self, source_path: Path) -> Tuple[str, int, str]:
        source = Path(source_path)
        if not source.is_file():
            raise MonitoringBatchRepositoryError(
                f"source file does not exist or is not a regular file: {source}"
            )

        digest = sha256()
        size = 0
        temporary_path: Optional[Path] = None
        temporary_fd: Optional[int] = None
        try:
            temporary_fd, temporary_name = tempfile.mkstemp(
                prefix=".monitoring-object-",
                dir=str(self.blob_root),
            )
            temporary_path = Path(temporary_name)
            with (
                source.open("rb") as input_stream,
                os.fdopen(temporary_fd, "wb", closefd=True) as output_stream,
            ):
                temporary_fd = None
                while True:
                    chunk = input_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                    output_stream.write(chunk)
                output_stream.flush()
                os.fsync(output_stream.fileno())

            content_sha256 = digest.hexdigest()
            final_path = self._blob_path(content_sha256)
            final_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.chmod(0o444)
            try:
                os.link(str(temporary_path), str(final_path))
            except FileExistsError:
                existing_hash, existing_size = self._hash_file(final_path)
                if existing_hash != content_sha256 or existing_size != size:
                    raise RepositoryIntegrityError(
                        f"content-addressed object is corrupt: {final_path}"
                    )
            finally:
                temporary_path.unlink(missing_ok=True)

            stored_hash, stored_size = self._hash_file(final_path)
            if stored_hash != content_sha256 or stored_size != size:
                raise RepositoryIntegrityError(
                    f"stored object bytes do not match source: {final_path}"
                )
            relative_path = str(final_path.relative_to(self.object_root))
            return content_sha256, size, relative_path
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def register_source(
        self,
        *,
        project_id: str,
        source_entry_id: str,
        validation_id: str,
        validation_revision: int,
        validator_version: str,
        validation_use_status: str,
        role: str,
        source_class: str,
        file_path: Path,
        file_name: Optional[str] = None,
        parser_version: str,
        classification_version: str = "monitoring_source_classifier.unspecified",
        technical_status: str = "passed",
        content_warnings: Sequence[str] = (),
        medical_override_reason: Optional[str] = None,
    ) -> SourceRegistration:
        project_id = _require_text(project_id, "project_id")
        source_entry_id = _require_text(source_entry_id, "source_entry_id")
        validation_id = _require_text(validation_id, "validation_id")
        validator_version = _require_text(validator_version, "validator_version")
        validation_use_status = _require_text(
            validation_use_status, "validation_use_status"
        )
        if int(validation_revision) < 1:
            raise MonitoringBatchRepositoryError(
                "validation_revision must be at least 1"
            )
        role = _require_text(role, "role")
        source_class = _require_text(source_class, "source_class")
        parser_version = _require_text(parser_version, "parser_version")
        classification_version = _require_text(
            classification_version, "classification_version"
        )
        technical_status = _require_text(technical_status, "technical_status").lower()
        if technical_status not in TECHNICAL_STATUSES:
            raise TechnicalValidationError(
                f"unsupported technical_status: {technical_status}"
            )
        warnings = tuple(
            _require_text(warning, "content_warning") for warning in content_warnings
        )
        override_reason = (
            _require_text(medical_override_reason, "medical_override_reason")
            if medical_override_reason is not None
            else None
        )
        if technical_status == "failed" and override_reason:
            raise TechnicalValidationError(
                "technical failure cannot be overridden by medical review"
            )

        source_path = Path(file_path)
        public_file_name = _require_text(
            file_name if file_name is not None else source_path.name,
            "file_name",
        )
        content_sha256, size_bytes, relative_path = self._store_object(source_path)
        created_at = _utc_now_text()
        source_id = f"monsrc_{uuid4().hex}"
        binding_metadata = {
            "project_id": project_id,
            "source_entry_id": source_entry_id,
            "validation_id": validation_id,
            "validation_revision": int(validation_revision),
            "validator_version": validator_version,
            "validation_use_status": validation_use_status,
            "role": role,
            "source_class": source_class,
            "file_name": public_file_name,
            "content_sha256": content_sha256,
            "size_bytes": size_bytes,
            "parser_version": parser_version,
            "technical_status": technical_status,
            "content_warnings": list(warnings),
            "medical_override_reason": override_reason,
            "classification_version": classification_version,
        }
        binding_sha256 = _json_hash(binding_metadata)
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO monitoring_content_objects(
                    content_sha256, size_bytes, blob_relative_path, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (content_sha256, size_bytes, relative_path, created_at),
            )
            object_row = connection.execute(
                """
                SELECT size_bytes, blob_relative_path
                FROM monitoring_content_objects
                WHERE content_sha256 = ?
                """,
                (content_sha256,),
            ).fetchone()
            if (
                object_row is None
                or int(object_row["size_bytes"]) != size_bytes
                or str(object_row["blob_relative_path"]) != relative_path
            ):
                raise RepositoryIntegrityError(
                    "content object metadata does not match stored bytes"
                )
            prior = connection.execute(
                """
                SELECT s.*, o.blob_relative_path
                FROM monitoring_sources s
                JOIN monitoring_content_objects o
                  ON o.content_sha256 = s.content_sha256
                WHERE s.project_id = ?
                  AND s.source_entry_id = ?
                  AND s.validation_id = ?
                ORDER BY s.binding_revision DESC
                LIMIT 1
                """,
                (project_id, source_entry_id, validation_id),
            ).fetchone()
            if prior is not None:
                prior_binding_sha256 = _require_exact_sha256(
                    prior["binding_sha256"],
                    "persisted source binding hash",
                )
                prior_content_sha256 = _require_exact_sha256(
                    prior["content_sha256"],
                    "persisted source content hash",
                )
                if prior_binding_sha256 == binding_sha256:
                    return self._source_from_row(prior)
                if (
                    prior_content_sha256 != content_sha256
                    or int(prior["size_bytes"]) != size_bytes
                ):
                    raise RepositoryIntegrityError(
                        "source binding revision cannot replace content bytes; "
                        "register a new source entry"
                    )
                processed_in_lineage = connection.execute(
                    """
                    SELECT 1
                    FROM monitoring_sources
                    WHERE project_id = ?
                      AND source_entry_id = ?
                      AND validation_id = ?
                      AND source_class = 'processed_full_snapshot'
                    LIMIT 1
                    """,
                    (project_id, source_entry_id, validation_id),
                ).fetchone()
                if processed_in_lineage is not None and source_class in {
                    "raw_full_snapshot",
                    "raw_full_snapshot_candidate",
                }:
                    raise RepositoryIntegrityError(
                        "processed B-grade source cannot be promoted to a raw "
                        "snapshot source class"
                    )
                binding_revision = int(prior["binding_revision"]) + 1
                supersedes_source_id = str(prior["source_id"])
            else:
                binding_revision = 1
                supersedes_source_id = None
            connection.execute(
                """
                INSERT INTO monitoring_sources(
                    source_id, project_id, source_entry_id, validation_id,
                    validation_revision, validator_version, validation_use_status,
                    role, source_class, file_name,
                    content_sha256, size_bytes, parser_version, technical_status,
                    content_warnings_json, medical_override_reason,
                    binding_revision, classification_version, binding_sha256,
                    supersedes_source_id, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?
                )
                """,
                (
                    source_id,
                    project_id,
                    source_entry_id,
                    validation_id,
                    int(validation_revision),
                    validator_version,
                    validation_use_status,
                    role,
                    source_class,
                    public_file_name,
                    content_sha256,
                    size_bytes,
                    parser_version,
                    technical_status,
                    _canonical_json(list(warnings)),
                    override_reason,
                    binding_revision,
                    classification_version,
                    binding_sha256,
                    supersedes_source_id,
                    created_at,
                ),
            )
        return SourceRegistration(
            source_id=source_id,
            project_id=project_id,
            source_entry_id=source_entry_id,
            validation_id=validation_id,
            validation_revision=int(validation_revision),
            validator_version=validator_version,
            validation_use_status=validation_use_status,
            role=role,
            source_class=source_class,
            file_name=public_file_name,
            content_sha256=content_sha256,
            size_bytes=size_bytes,
            parser_version=parser_version,
            technical_status=technical_status,
            content_warnings=warnings,
            medical_override_reason=override_reason,
            binding_revision=binding_revision,
            classification_version=classification_version,
            binding_sha256=binding_sha256,
            supersedes_source_id=supersedes_source_id,
            blob_relative_path=relative_path,
            created_at=created_at,
        )

    def get_source(self, source_id: str) -> SourceRegistration:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT s.*, o.blob_relative_path
                FROM monitoring_sources s
                JOIN monitoring_content_objects o
                  ON o.content_sha256 = s.content_sha256
                WHERE s.source_id = ?
                """,
                (_require_text(source_id, "source_id"),),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"source not found: {source_id}")
        return self._source_from_row(row)

    def read_source_bytes(self, source_id: str) -> bytes:
        source = self.get_source(source_id)
        object_path = (self.object_root / source.blob_relative_path).resolve()
        object_root = self.object_root.resolve()
        try:
            object_path.relative_to(object_root)
        except ValueError as exc:
            raise RepositoryIntegrityError(
                "source object resolved outside the monitoring object store"
            ) from exc
        payload = object_path.read_bytes()
        if sha256(payload).hexdigest() != source.content_sha256:
            raise RepositoryIntegrityError("source object hash no longer matches registration")
        if len(payload) != source.size_bytes:
            raise RepositoryIntegrityError("source object size no longer matches registration")
        return payload

    def object_path(self, source_id: str) -> Path:
        source = self.get_source(source_id)
        path = self.object_root / source.blob_relative_path
        content_hash, size = self._hash_file(path)
        if content_hash != source.content_sha256 or size != source.size_bytes:
            raise RepositoryIntegrityError(
                f"stored object failed integrity verification: {source_id}"
            )
        return path

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> SourceRegistration:
        try:
            def text(value: Any, field: str) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise RepositoryIntegrityError(
                        f"persisted source {field} is invalid"
                    )
                return value

            def canonical_hash(value: Any, field: str) -> str:
                raw = text(value, field)
                normalized = _required_sha256(raw, field)
                if raw != normalized:
                    raise RepositoryIntegrityError(
                        f"persisted source {field} is not canonical"
                    )
                return raw

            content_warnings = json.loads(row["content_warnings_json"])
            if not isinstance(content_warnings, list) or any(
                not isinstance(warning, str) or not warning.strip()
                or warning.strip() != warning
                for warning in content_warnings
            ):
                raise RepositoryIntegrityError(
                    "source binding content warnings are invalid"
                )
            medical_override_reason = row["medical_override_reason"]
            if medical_override_reason is not None:
                medical_override_reason = text(
                    medical_override_reason,
                    "medical_override_reason",
                )
            validation_revision = row["validation_revision"]
            binding_revision = row["binding_revision"]
            size_bytes = row["size_bytes"]
            if (
                isinstance(validation_revision, bool)
                or not isinstance(validation_revision, int)
                or validation_revision < 1
                or isinstance(binding_revision, bool)
                or not isinstance(binding_revision, int)
                or binding_revision < 1
                or isinstance(size_bytes, bool)
                or not isinstance(size_bytes, int)
                or size_bytes < 0
            ):
                raise RepositoryIntegrityError(
                    "persisted source numeric metadata is invalid"
                )
            content_sha256 = canonical_hash(row["content_sha256"], "content_sha256")
            binding_sha256 = canonical_hash(row["binding_sha256"], "binding_sha256")
            created_at = text(row["created_at"], "created_at")
            datetime.fromisoformat(created_at)
            supersedes_source_id = row["supersedes_source_id"]
            if supersedes_source_id is not None:
                supersedes_source_id = text(
                    supersedes_source_id,
                    "supersedes_source_id",
                )
            source_id = text(row["source_id"], "source_id")
            project_id = text(row["project_id"], "project_id")
            source_entry_id = text(row["source_entry_id"], "source_entry_id")
            validation_id = text(row["validation_id"], "validation_id")
            validator_version = text(row["validator_version"], "validator_version")
            validation_use_status = text(
                row["validation_use_status"],
                "validation_use_status",
            )
            role = text(row["role"], "role")
            source_class = text(row["source_class"], "source_class")
            file_name = text(row["file_name"], "file_name")
            parser_version = text(row["parser_version"], "parser_version")
            technical_status = text(row["technical_status"], "technical_status")
            classification_version = text(
                row["classification_version"],
                "classification_version",
            )
            binding_metadata = {
                "project_id": project_id,
                "source_entry_id": source_entry_id,
                "validation_id": validation_id,
                "validation_revision": validation_revision,
                "validator_version": validator_version,
                "validation_use_status": validation_use_status,
                "role": role,
                "source_class": source_class,
                "file_name": file_name,
                "content_sha256": content_sha256,
                "size_bytes": size_bytes,
                "parser_version": parser_version,
                "technical_status": technical_status,
                "content_warnings": content_warnings,
                "medical_override_reason": medical_override_reason,
                "classification_version": classification_version,
            }
            if binding_sha256 != _json_hash(binding_metadata):
                raise RepositoryIntegrityError(
                    "source binding metadata hash mismatch"
                )
            return SourceRegistration(
                source_id=source_id,
                project_id=project_id,
                source_entry_id=source_entry_id,
                validation_id=validation_id,
                validation_revision=validation_revision,
                validator_version=validator_version,
                validation_use_status=validation_use_status,
                role=role,
                source_class=source_class,
                file_name=file_name,
                content_sha256=content_sha256,
                size_bytes=size_bytes,
                parser_version=parser_version,
                technical_status=technical_status,
                content_warnings=tuple(content_warnings),
                medical_override_reason=medical_override_reason,
                binding_revision=binding_revision,
                classification_version=classification_version,
                binding_sha256=binding_sha256,
                supersedes_source_id=supersedes_source_id,
                blob_relative_path=text(row["blob_relative_path"], "blob_relative_path"),
                created_at=created_at,
            )
        except RepositoryIntegrityError:
            raise
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError(
                "persisted source registration is invalid"
            ) from exc

    def create_batch(
        self,
        *,
        project_id: str,
        idempotency_key: str,
        expected_domains: Iterable[str] = (),
    ) -> BatchMutationResult:
        project_id = _require_text(project_id, "project_id")
        idempotency_key = _require_text(idempotency_key, "idempotency_key")
        normalized_domains = _normalize_domains(expected_domains)
        request = {
            "operation": "create_batch",
            "project_id": project_id,
            "expected_domains": list(normalized_domains),
        }
        request_sha256 = _json_hash(request)
        with self._transaction() as connection:
            replay = self._idempotent_replay(
                connection,
                project_id,
                idempotency_key,
                request_sha256,
                expected_operation="create_batch",
            )
            if replay is not None:
                return self._mutation_result_from_dict(replay, replayed=True)

            now = _utc_now_text()
            batch_id = f"monbatch_{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO monitoring_batches(
                    batch_id, project_id, state, version,
                    expected_domains_json, active_mapping_revision,
                    full_snapshot_proof_json, created_at, updated_at, frozen_at
                ) VALUES (?, ?, 'draft', 1, ?, NULL, NULL, ?, ?, NULL)
                """,
                (
                    batch_id,
                    project_id,
                    _canonical_json(list(normalized_domains)),
                    now,
                    now,
                ),
            )
            batch = self._batch_by_id(connection, batch_id)
            result = BatchMutationResult(batch=batch, replayed=False)
            self._append_event(
                connection,
                batch,
                "batch_created",
                {"expected_domains": list(normalized_domains)},
            )
            self._store_idempotency(
                connection,
                project_id,
                idempotency_key,
                "create_batch",
                request_sha256,
                result.to_dict(),
            )
            return result

    def attach_source(
        self,
        *,
        batch_id: str,
        source_id: str,
        expected_version: int,
        idempotency_key: str,
    ) -> BatchMutationResult:
        batch_id = _require_text(batch_id, "batch_id")
        source_id = _require_text(source_id, "source_id")
        idempotency_key = _require_text(idempotency_key, "idempotency_key")
        request = {
            "operation": "attach_source",
            "batch_id": batch_id,
            "source_id": source_id,
            "expected_version": expected_version,
        }
        return self._mutate_batch(
            batch_id=batch_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation="attach_source",
            request=request,
            allowed_states=("draft",),
            mutation=lambda connection, batch: self._attach_source_mutation(
                connection, batch, source_id
            ),
        )

    def _attach_source_mutation(
        self,
        connection: sqlite3.Connection,
        batch: BatchRecord,
        source_id: str,
    ) -> Dict[str, Any]:
        source = connection.execute(
            "SELECT project_id FROM monitoring_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if source is None:
            raise RecordNotFoundError(f"source not found: {source_id}")
        if str(source["project_id"]) != batch.project_id:
            raise MonitoringBatchRepositoryError(
                "source project does not match batch project"
            )
        try:
            connection.execute(
                """
                INSERT INTO monitoring_batch_sources(batch_id, source_id, attached_at)
                VALUES (?, ?, ?)
                """,
                (batch.batch_id, source_id, _utc_now_text()),
            )
        except sqlite3.IntegrityError as exc:
            raise MonitoringBatchRepositoryError(
                f"source already attached to batch: {source_id}"
            ) from exc
        return {"source_id": source_id}

    def replace_rows(
        self,
        *,
        batch_id: str,
        rows: Iterable[Mapping[str, Any]],
        schema_fields: Iterable[Mapping[str, Any]] = (),
        expected_version: int,
        idempotency_key: str,
    ) -> BatchMutationResult:
        normalized_rows = self._normalize_rows(rows)
        normalized_schema_fields = self._normalize_schema_fields(schema_fields)
        batch_id = _require_text(batch_id, "batch_id")
        idempotency_key = _require_text(idempotency_key, "idempotency_key")
        row_set_sha256 = _rows_hash(normalized_rows)
        schema_fields_sha256 = _json_hash(
            [
                {
                    "domain": domain,
                    "field": field,
                    "source_sheet": source_sheet,
                }
                for domain, field, source_sheet in normalized_schema_fields
            ]
        )
        request = {
            "operation": "replace_rows",
            "batch_id": batch_id,
            "expected_version": expected_version,
            "row_count": len(normalized_rows),
            "row_set_sha256": row_set_sha256,
            "schema_field_count": len(normalized_schema_fields),
            "schema_fields_sha256": schema_fields_sha256,
        }
        return self._mutate_batch(
            batch_id=batch_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation="replace_rows",
            request=request,
            allowed_states=("draft", "parsed"),
            mutation=lambda connection, batch: self._replace_rows_mutation(
                connection,
                batch,
                normalized_rows,
                normalized_schema_fields,
                row_set_sha256,
                schema_fields_sha256,
            ),
        )

    @staticmethod
    def _normalize_rows(
        rows: Iterable[Mapping[str, Any]],
    ) -> Tuple[NormalizedRow, ...]:
        normalized: List[NormalizedRow] = []
        seen: set = set()
        for raw in rows:
            business_key = _require_text(raw.get("business_key", ""), "business_key")
            if business_key in seen:
                raise DuplicateBusinessKeyError(
                    f"duplicate business_key in batch: {business_key}"
                )
            seen.add(business_key)
            domain = _require_text(raw.get("domain", ""), "domain").upper()
            data = raw.get("data")
            locator = raw.get("source_locator")
            if not isinstance(data, Mapping):
                raise MonitoringBatchRepositoryError(
                    f"row data must be a mapping: {business_key}"
                )
            if not isinstance(locator, Mapping) or not locator:
                raise MonitoringBatchRepositoryError(
                    f"source_locator must be a non-empty mapping: {business_key}"
                )
            data_dict = data if isinstance(data, dict) else dict(data)
            locator_dict = locator if isinstance(locator, dict) else dict(locator)
            calculated_fingerprint = _json_hash(
                {
                    "domain": domain,
                    "data": data_dict,
                }
            )
            provided_fingerprint = raw.get("row_fingerprint")
            if provided_fingerprint is not None:
                provided_fingerprint = _require_exact_sha256(
                    provided_fingerprint,
                    "row_fingerprint",
                )
                if provided_fingerprint != calculated_fingerprint:
                    raise RepositoryIntegrityError(
                        f"row_fingerprint mismatch: {business_key}"
                    )
            normalized.append(
                NormalizedRow(
                    business_key=business_key,
                    domain=domain,
                    data=data_dict,
                    source_locator=locator_dict,
                    row_fingerprint=calculated_fingerprint,
                )
            )
        return tuple(sorted(normalized, key=lambda item: item.business_key))

    @staticmethod
    def _normalize_schema_fields(
        fields: Iterable[Mapping[str, Any]],
    ) -> Tuple[Tuple[str, str, str], ...]:
        normalized: set[Tuple[str, str, str]] = set()
        for raw in fields:
            if not isinstance(raw, Mapping):
                raise MonitoringBatchRepositoryError(
                    "schema field must be a mapping"
                )
            domain = _require_text(raw.get("domain", ""), "schema domain").upper()
            field = _require_text(raw.get("field", ""), "schema field")
            source_sheet = _require_text(
                raw.get("source_sheet", ""),
                "schema source_sheet",
            )
            normalized.add((domain, field, source_sheet))
        return tuple(sorted(normalized))

    @staticmethod
    def _replace_rows_mutation(
        connection: sqlite3.Connection,
        batch: BatchRecord,
        rows: Tuple[NormalizedRow, ...],
        schema_fields: Tuple[Tuple[str, str, str], ...],
        row_set_sha256: str,
        schema_fields_sha256: str,
    ) -> Dict[str, Any]:
        connection.execute(
            "DELETE FROM monitoring_normalized_rows WHERE batch_id = ?",
            (batch.batch_id,),
        )
        try:
            connection.executemany(
                """
                INSERT INTO monitoring_normalized_rows(
                    batch_id, business_key, domain, data_json,
                    source_locator_json, row_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        batch.batch_id,
                        row.business_key,
                        row.domain,
                        _canonical_json(row.data),
                        _canonical_json(row.source_locator),
                        row.row_fingerprint,
                    )
                    for row in rows
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise DuplicateBusinessKeyError(
                "duplicate business_key rejected by repository"
            ) from exc
        connection.execute(
            "DELETE FROM monitoring_batch_schema_fields WHERE batch_id = ?",
            (batch.batch_id,),
        )
        connection.executemany(
            """
            INSERT INTO monitoring_batch_schema_fields(
                batch_id, domain, field_name, source_sheet
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (batch.batch_id, domain, field, source_sheet)
                for domain, field, source_sheet in schema_fields
            ),
        )
        return {
            "row_count": len(rows),
            "row_set_sha256": row_set_sha256,
            "schema_field_count": len(schema_fields),
            "schema_fields_sha256": schema_fields_sha256,
        }

    @staticmethod
    def _normalize_parse_sheet_facts(
        sheets: Iterable[Mapping[str, Any]],
        *,
        field: str,
    ) -> Tuple[Tuple[str, int], ...]:
        normalized: List[Tuple[str, int]] = []
        seen: set[str] = set()
        for raw in sheets:
            if not isinstance(raw, Mapping):
                raise CompletenessGateError(f"{field} must contain mappings")
            sheet_name = _require_text(raw.get("sheet_name", ""), f"{field}.sheet_name")
            if sheet_name in seen:
                raise CompletenessGateError(
                    f"{field} contains duplicate sheet_name: {sheet_name}"
                )
            seen.add(sheet_name)
            try:
                parsed_row_count = int(raw.get("parsed_row_count"))
            except (TypeError, ValueError) as exc:
                raise CompletenessGateError(
                    f"{field}.parsed_row_count must be an integer"
                ) from exc
            if parsed_row_count < 0:
                raise CompletenessGateError(
                    f"{field}.parsed_row_count cannot be negative"
                )
            normalized.append((sheet_name, parsed_row_count))
        if not normalized:
            raise CompletenessGateError(f"{field} cannot be empty")
        return tuple(sorted(normalized))

    def verify_derived_snapshot(
        self,
        *,
        batch_id: str,
        source_id: str,
        source_content_sha256: str,
        original_source_class: str,
        parser_version: str,
        transformation_type: str,
        execution_tool: str,
        execution_tool_version: str,
        original_parse_sheets: Iterable[Mapping[str, Any]],
        observed_original_parse_sheets: Iterable[Mapping[str, Any]],
        observed_original_source_class: str,
        normalized_row_count: int,
        expected_domains: Iterable[str],
        verified_by: str,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> DerivedSnapshotVerificationResult:
        batch_id = _require_text(batch_id, "batch_id")
        source_id = _require_text(source_id, "source_id")
        source_content_sha256 = _require_exact_sha256(
            source_content_sha256,
            "source content hash",
        )
        original_source_class = _require_text(
            original_source_class, "original_source_class"
        )
        observed_original_source_class = _require_text(
            observed_original_source_class,
            "observed_original_source_class",
        )
        parser_version = _require_text(parser_version, "parser_version")
        transformation_type = _require_text(
            transformation_type, "transformation_type"
        )
        execution_tool = _require_text(execution_tool, "execution_tool")
        execution_tool_version = _require_text(
            execution_tool_version, "execution_tool_version"
        )
        verified_by = _require_text(verified_by, "verified_by")
        reason = _require_text(reason, "reason")
        if len(reason) < 8:
            raise CompletenessGateError(
                "verification reason must describe the concrete recovery evidence"
            )
        idempotency_key = _require_text(idempotency_key, "idempotency_key")
        if transformation_type != "parser_dimension_recovery":
            raise CompletenessGateError(
                "only parser_dimension_recovery is supported"
            )
        if execution_tool != "listing_file_parser":
            raise CompletenessGateError(
                "execution tool must be listing_file_parser"
            )
        if execution_tool_version != parser_version:
            raise CompletenessGateError(
                "execution tool version must match parser_version"
            )
        if original_source_class != "raw_snapshot_with_format_defect":
            raise CompletenessGateError(
                "source class is not eligible for derived snapshot verification"
            )
        if observed_original_source_class != original_source_class:
            raise CompletenessGateError(
                "source class does not match the classification reproduced from original bytes"
            )
        try:
            normalized_row_count = int(normalized_row_count)
        except (TypeError, ValueError) as exc:
            raise CompletenessGateError(
                "normalized row count must be an integer"
            ) from exc
        if normalized_row_count < 1:
            raise CompletenessGateError("normalized row count must be positive")
        parse_sheets = self._normalize_parse_sheet_facts(
            original_parse_sheets,
            field="original parse sheets",
        )
        observed_parse_sheets = self._normalize_parse_sheet_facts(
            observed_original_parse_sheets,
            field="observed original parse sheets",
        )
        if parse_sheets != observed_parse_sheets:
            raise CompletenessGateError(
                "original parse facts do not match the parser output reproduced from source bytes"
            )
        domains = _normalize_domains(expected_domains)
        if not domains:
            raise CompletenessGateError("expected domains cannot be empty")

        request = {
            "operation": "verify_derived_snapshot",
            "batch_id": batch_id,
            "source_id": source_id,
            "source_content_sha256": source_content_sha256,
            "original_source_class": original_source_class,
            "parser_version": parser_version,
            "transformation_type": transformation_type,
            "execution_tool": execution_tool,
            "execution_tool_version": execution_tool_version,
            "original_parse_sheets": [
                {"sheet_name": name, "parsed_row_count": count}
                for name, count in parse_sheets
            ],
            "normalized_row_count": normalized_row_count,
            "expected_domains": list(domains),
            "verified_by": verified_by,
            "reason": reason,
            "expected_version": int(expected_version),
        }
        request_sha256 = _json_hash(request)
        with self._transaction() as connection:
            project_row = connection.execute(
                "SELECT project_id FROM monitoring_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if project_row is None:
                raise RecordNotFoundError(f"batch not found: {batch_id}")
            project_id = str(project_row["project_id"])
            replay = self._idempotent_replay(
                connection,
                project_id,
                idempotency_key,
                request_sha256,
                expected_operation="verify_derived_snapshot",
            )
            if replay is not None:
                return self._derived_snapshot_result_from_dict(
                    replay,
                    replayed=True,
                )

            batch = self._batch_by_id(connection, batch_id)
            if batch.state != "parsed":
                raise InvalidStateTransitionError(
                    "derived snapshot verification requires a parsed batch"
                )
            if batch.version != int(expected_version):
                raise OptimisticVersionConflictError(
                    f"batch version conflict: expected {expected_version}, "
                    f"current {batch.version}"
                )
            source_rows = connection.execute(
                """
                SELECT s.*
                FROM monitoring_batch_sources bs
                JOIN monitoring_sources s ON s.source_id = bs.source_id
                WHERE bs.batch_id = ?
                ORDER BY s.source_id
                """,
                (batch_id,),
            ).fetchall()
            if len(source_rows) != 1:
                raise CompletenessGateError(
                    "derived snapshot verification requires a single source batch"
                )
            source_row = source_rows[0]
            if str(source_row["source_id"]) != source_id:
                raise RepositoryIntegrityError(
                    "source_id does not match the batch source"
                )
            if str(source_row["source_class"]) != original_source_class:
                raise CompletenessGateError(
                    "source class cannot be promoted by this verification flow"
                )
            if str(source_row["content_sha256"]) != source_content_sha256:
                raise RepositoryIntegrityError(
                    "source content hash does not match the saved original parent file"
                )
            if str(source_row["parser_version"]) != parser_version:
                raise RepositoryIntegrityError(
                    "parser_version does not match source registration"
                )

            persisted_row_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM monitoring_normalized_rows
                    WHERE batch_id = ?
                    """,
                    (batch_id,),
                ).fetchone()["count"]
            )
            if normalized_row_count != persisted_row_count:
                raise CompletenessGateError(
                    "normalized row count does not match the batch repository"
                )
            observed_domains = {
                str(row["domain"])
                for row in connection.execute(
                    """
                    SELECT DISTINCT domain
                    FROM monitoring_normalized_rows
                    WHERE batch_id = ?
                    """,
                    (batch_id,),
                ).fetchall()
            }
            observed_domains.update(
                str(row["domain"])
                for row in connection.execute(
                    """
                    SELECT DISTINCT domain
                    FROM monitoring_batch_schema_fields
                    WHERE batch_id = ?
                    """,
                    (batch_id,),
                ).fetchall()
            )
            normalized_observed_domains = tuple(sorted(observed_domains))
            if domains != batch.expected_domains or domains != normalized_observed_domains:
                raise CompletenessGateError(
                    "expected domains do not match the batch repository facts"
                )

            parse_sheet_payload = [
                {"sheet_name": name, "parsed_row_count": count}
                for name, count in parse_sheets
            ]
            proof_payload = {
                "proof_schema_version": "monitoring_derived_snapshot_proof.v1",
                "project_id": project_id,
                "batch_id": batch_id,
                "source_id": source_id,
                "source_content_sha256": source_content_sha256,
                "original_source_class": original_source_class,
                "verified_source_class": "verified_derived_full_snapshot",
                "parser_version": parser_version,
                "transformation_type": transformation_type,
                "execution_tool": execution_tool,
                "execution_tool_version": execution_tool_version,
                "original_parse_sheet_count": len(parse_sheets),
                "original_parse_row_count": sum(count for _, count in parse_sheets),
                "original_parse_sheets": parse_sheet_payload,
                "normalized_row_count": normalized_row_count,
                "expected_domains": list(domains),
                "verified_by": verified_by,
                "reason": reason,
            }
            proof_sha256 = _json_hash(proof_payload)
            proof_id = f"monderived_{proof_sha256[:24]}"
            created_at = _utc_now_text()
            try:
                connection.execute(
                    """
                    INSERT INTO monitoring_derived_snapshot_proofs(
                        proof_id, project_id, batch_id, source_id,
                        source_content_sha256, original_source_class,
                        verified_source_class, parser_version,
                        transformation_type, execution_tool,
                        execution_tool_version, original_parse_sheet_count,
                        original_parse_row_count, original_parse_sheets_json,
                        normalized_row_count, expected_domains_json,
                        verified_by, reason, canonical_proof_json,
                        proof_sha256, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proof_id,
                        project_id,
                        batch_id,
                        source_id,
                        source_content_sha256,
                        original_source_class,
                        "verified_derived_full_snapshot",
                        parser_version,
                        transformation_type,
                        execution_tool,
                        execution_tool_version,
                        len(parse_sheets),
                        sum(count for _, count in parse_sheets),
                        _canonical_json(parse_sheet_payload),
                        normalized_row_count,
                        _canonical_json(list(domains)),
                        verified_by,
                        reason,
                        _canonical_json(proof_payload),
                        proof_sha256,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RepositoryIntegrityError(
                    "an immutable derived snapshot proof already exists for this batch"
                ) from exc
            verified_source_id = f"monsrc_{uuid4().hex}"
            verified_classification_version = (
                "monitoring_derived_snapshot_verification.v1"
            )
            verified_binding_revision = int(source_row["binding_revision"]) + 1
            verified_binding_metadata = {
                "project_id": project_id,
                "source_entry_id": str(source_row["source_entry_id"]),
                "validation_id": str(source_row["validation_id"]),
                "validation_revision": int(source_row["validation_revision"]),
                "validator_version": str(source_row["validator_version"]),
                "validation_use_status": str(source_row["validation_use_status"]),
                "role": str(source_row["role"]),
                "source_class": "verified_derived_full_snapshot",
                "file_name": str(source_row["file_name"]),
                "content_sha256": source_content_sha256,
                "size_bytes": int(source_row["size_bytes"]),
                "parser_version": parser_version,
                "technical_status": str(source_row["technical_status"]),
                "content_warnings": json.loads(
                    str(source_row["content_warnings_json"])
                ),
                "medical_override_reason": (
                    str(source_row["medical_override_reason"])
                    if source_row["medical_override_reason"] is not None
                    else None
                ),
                "classification_version": verified_classification_version,
            }
            verified_binding_sha256 = _json_hash(verified_binding_metadata)
            connection.execute(
                """
                INSERT INTO monitoring_sources(
                    source_id, project_id, source_entry_id, validation_id,
                    validation_revision, validator_version,
                    validation_use_status, role, source_class, file_name,
                    content_sha256, size_bytes, parser_version,
                    technical_status, content_warnings_json,
                    medical_override_reason, binding_revision,
                    classification_version, binding_sha256,
                    supersedes_source_id, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?
                )
                """,
                (
                    verified_source_id,
                    project_id,
                    verified_binding_metadata["source_entry_id"],
                    verified_binding_metadata["validation_id"],
                    verified_binding_metadata["validation_revision"],
                    verified_binding_metadata["validator_version"],
                    verified_binding_metadata["validation_use_status"],
                    verified_binding_metadata["role"],
                    verified_binding_metadata["source_class"],
                    verified_binding_metadata["file_name"],
                    source_content_sha256,
                    verified_binding_metadata["size_bytes"],
                    parser_version,
                    verified_binding_metadata["technical_status"],
                    _canonical_json(
                        verified_binding_metadata["content_warnings"]
                    ),
                    verified_binding_metadata["medical_override_reason"],
                    verified_binding_revision,
                    verified_classification_version,
                    verified_binding_sha256,
                    source_id,
                    created_at,
                ),
            )
            replaced_batch_source = connection.execute(
                """
                UPDATE monitoring_batch_sources
                SET source_id = ?
                WHERE batch_id = ? AND source_id = ?
                """,
                (verified_source_id, batch_id, source_id),
            )
            if replaced_batch_source.rowcount != 1:
                raise RepositoryIntegrityError(
                    "batch source binding changed before derived snapshot "
                    "verification completed"
                )
            now = _utc_now_text()
            next_version = batch.version + 1
            updated_batch = connection.execute(
                """
                UPDATE monitoring_batches
                SET version = ?, updated_at = ?
                WHERE batch_id = ? AND version = ? AND state = 'parsed'
                """,
                (next_version, now, batch_id, batch.version),
            )
            if updated_batch.rowcount != 1:
                raise OptimisticVersionConflictError(
                    "batch version changed during derived snapshot verification"
                )
            current = self._batch_by_id(connection, batch_id)
            proof_summary = {
                "proof_id": proof_id,
                "proof_sha256": proof_sha256,
                "proof_schema_version": proof_payload["proof_schema_version"],
                "original_source_class": original_source_class,
                "created_at": created_at,
            }
            source_summary = {
                "source_id": verified_source_id,
                "original_source_id": source_id,
                "source_content_sha256": source_content_sha256,
                "original_source_class": original_source_class,
                "verified_source_class": "verified_derived_full_snapshot",
                "parser_version": parser_version,
                "binding_revision": verified_binding_revision,
                "supersedes_source_id": source_id,
            }
            fact_summary = {
                "transformation_type": transformation_type,
                "execution_tool": execution_tool,
                "execution_tool_version": execution_tool_version,
                "original_parse_sheet_count": len(parse_sheets),
                "original_parse_row_count": sum(count for _, count in parse_sheets),
                "original_parse_sheets": parse_sheet_payload,
                "normalized_row_count": normalized_row_count,
                "expected_domains": list(domains),
                "verified_by": verified_by,
                "reason": reason,
            }
            medical_summary = {
                "status": "已核实为可审计派生全量来源",
                "source": (
                    f"原始父文件哈希已绑定（{source_content_sha256[:12]}…），"
                    "来源对象字节未替换。"
                ),
                "recovery": (
                    f"使用 {execution_tool} {execution_tool_version} 恢复工作表范围"
                    f"元数据，共解析 {len(parse_sheets)} 个工作表、"
                    f"{sum(count for _, count in parse_sheets)} 条原始记录。"
                ),
                "conservation": (
                    f"批次已持久化 {normalized_row_count} 条标准化记录，"
                    f"覆盖域：{'、'.join(domains)}；与当前批次事实一致。"
                ),
                "review": f"{verified_by}：{reason}",
            }
            result = DerivedSnapshotVerificationResult(
                batch=current,
                proof=proof_summary,
                source_summary=source_summary,
                fact_summary=fact_summary,
                medical_summary=medical_summary,
                replayed=False,
            )
            self._append_event(
                connection,
                current,
                "verify_derived_snapshot",
                {
                    "proof_id": proof_id,
                    "proof_sha256": proof_sha256,
                    "source_id": verified_source_id,
                    "original_source_id": source_id,
                    "source_content_sha256": source_content_sha256,
                    "original_source_class": original_source_class,
                    "verified_source_class": "verified_derived_full_snapshot",
                    "normalized_row_count": normalized_row_count,
                    "expected_domains": list(domains),
                },
            )
            self._store_idempotency(
                connection,
                project_id,
                idempotency_key,
                "verify_derived_snapshot",
                request_sha256,
                result.to_dict(),
            )
            return result

    def record_validation_evidence(
        self,
        *,
        batch_id: str,
        mapping_revision: str,
        mapping: Mapping[str, Any],
        expected_domains: Iterable[str],
        full_snapshot_proof: Mapping[str, Any],
        expected_version: int,
        idempotency_key: str,
    ) -> BatchMutationResult:
        batch_id = _require_text(batch_id, "batch_id")
        mapping_revision = _require_text(mapping_revision, "mapping_revision")
        idempotency_key = _require_text(idempotency_key, "idempotency_key")
        if not isinstance(mapping, Mapping) or not mapping:
            raise CompletenessGateError("mapping must be a non-empty mapping")
        if not isinstance(full_snapshot_proof, Mapping):
            raise CompletenessGateError("full_snapshot_proof must be a mapping")
        domains = _normalize_domains(expected_domains)
        proof = dict(full_snapshot_proof)
        request = {
            "operation": "record_validation_evidence",
            "batch_id": batch_id,
            "mapping_revision": mapping_revision,
            "mapping": dict(mapping),
            "expected_domains": list(domains),
            "full_snapshot_proof": proof,
            "expected_version": expected_version,
        }
        return self._mutate_batch(
            batch_id=batch_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation="record_validation_evidence",
            request=request,
            allowed_states=("parsed",),
            mutation=lambda connection, batch: self._validation_evidence_mutation(
                connection,
                batch,
                mapping_revision,
                dict(mapping),
                domains,
                proof,
            ),
        )

    @staticmethod
    def _validation_evidence_mutation(
        connection: sqlite3.Connection,
        batch: BatchRecord,
        mapping_revision: str,
        mapping: Dict[str, Any],
        expected_domains: Tuple[str, ...],
        proof: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not expected_domains:
            raise CompletenessGateError("expected_domains cannot be empty")
        mapping_json = _canonical_json(mapping)
        mapping_sha256 = sha256(mapping_json.encode("utf-8")).hexdigest()
        existing = connection.execute(
            """
            SELECT mapping_sha256 FROM monitoring_mapping_revisions
            WHERE batch_id = ? AND mapping_revision = ?
            """,
            (batch.batch_id, mapping_revision),
        ).fetchone()
        if existing is not None:
            persisted_mapping_sha256 = _require_exact_sha256(
                existing["mapping_sha256"],
                "persisted mapping revision hash",
            )
            if persisted_mapping_sha256 != mapping_sha256:
                raise RepositoryIntegrityError(
                    "mapping revision identifier already exists with different content"
                )
        connection.execute(
            """
            INSERT OR IGNORE INTO monitoring_mapping_revisions(
                batch_id, mapping_revision, mapping_json,
                mapping_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                batch.batch_id,
                mapping_revision,
                mapping_json,
                mapping_sha256,
                _utc_now_text(),
            ),
        )

        source_ids = [
            str(row["source_id"])
            for row in connection.execute(
                """
                SELECT source_id FROM monitoring_batch_sources
                WHERE batch_id = ? ORDER BY source_id
                """,
                (batch.batch_id,),
            ).fetchall()
        ]
        row_count = int(
            connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM monitoring_normalized_rows
                WHERE batch_id = ?
                """,
                (batch.batch_id,),
            ).fetchone()["count"]
        )
        normalized_proof = dict(proof)
        normalized_proof["snapshot_source_ids"] = source_ids
        normalized_proof["observed_row_count"] = row_count
        normalized_proof["expected_domains"] = list(expected_domains)
        connection.execute(
            """
            UPDATE monitoring_batches
            SET expected_domains_json = ?,
                active_mapping_revision = ?,
                full_snapshot_proof_json = ?
            WHERE batch_id = ?
            """,
            (
                _canonical_json(list(expected_domains)),
                mapping_revision,
                _canonical_json(normalized_proof),
                batch.batch_id,
            ),
        )
        return {
            "mapping_revision": mapping_revision,
            "mapping_sha256": mapping_sha256,
            "expected_domains": list(expected_domains),
            "full_snapshot_proof": normalized_proof,
        }

    def transition_batch(
        self,
        *,
        batch_id: str,
        target_state: str,
        expected_version: int,
        idempotency_key: str,
    ) -> BatchMutationResult:
        batch_id = _require_text(batch_id, "batch_id")
        target_state = _require_text(target_state, "target_state").lower()
        idempotency_key = _require_text(idempotency_key, "idempotency_key")
        if target_state not in BATCH_STATES:
            raise InvalidStateTransitionError(
                f"unsupported target state: {target_state}"
            )
        request = {
            "operation": "transition_batch",
            "batch_id": batch_id,
            "target_state": target_state,
            "expected_version": expected_version,
        }

        def transition(
            connection: sqlite3.Connection,
            batch: BatchRecord,
        ) -> Dict[str, Any]:
            expected_target = _NEXT_STATE.get(batch.state)
            if expected_target != target_state:
                raise InvalidStateTransitionError(
                    f"illegal batch transition: {batch.state} -> {target_state}"
                )
            self._validate_transition_gate(connection, batch, target_state)
            frozen_at = _utc_now_text() if target_state == "frozen" else None
            connection.execute(
                """
                UPDATE monitoring_batches
                SET state = ?, frozen_at = COALESCE(?, frozen_at)
                WHERE batch_id = ?
                """,
                (target_state, frozen_at, batch.batch_id),
            )
            return {"from_state": batch.state, "to_state": target_state}

        return self._mutate_batch(
            batch_id=batch_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            operation=f"transition_to_{target_state}",
            request=request,
            allowed_states=tuple(_NEXT_STATE.keys()),
            mutation=transition,
        )

    def _validate_transition_gate(
        self,
        connection: sqlite3.Connection,
        batch: BatchRecord,
        target_state: str,
    ) -> None:
        if target_state == "parsed":
            source_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM monitoring_batch_sources
                    WHERE batch_id = ?
                    """,
                    (batch.batch_id,),
                ).fetchone()["count"]
            )
            row_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM monitoring_normalized_rows
                    WHERE batch_id = ?
                    """,
                    (batch.batch_id,),
                ).fetchone()["count"]
            )
            if source_count == 0 or row_count == 0:
                raise CompletenessGateError(
                    "parsed state requires at least one source and one normalized row"
                )
            failed_sources = connection.execute(
                """
                SELECT source_id, technical_status, validation_use_status
                FROM monitoring_sources
                WHERE source_id IN (
                    SELECT source_id FROM monitoring_batch_sources
                    WHERE batch_id = ?
                )
                  AND (
                    technical_status != 'passed'
                    OR validation_use_status NOT IN ('allowed', 'confirmed_after_warning')
                  )
                ORDER BY source_id
                """,
                (batch.batch_id,),
            ).fetchall()
            if failed_sources:
                details = ", ".join(
                    (
                        f"{row['source_id']}=technical:{row['technical_status']},"
                        f"admission:{row['validation_use_status']}"
                    )
                    for row in failed_sources
                )
                raise TechnicalValidationError(
                    f"all attached sources must pass source admission: {details}"
                )
            return

        if target_state == "validated":
            current = self._batch_by_id(connection, batch.batch_id)
            if not current.active_mapping_revision:
                raise CompletenessGateError(
                    "validated state requires an active mapping revision"
                )
            if not current.expected_domains:
                raise CompletenessGateError("validated state requires expected_domains")
            observed_domains = {
                str(row["domain"])
                for row in connection.execute(
                    """
                    SELECT DISTINCT domain
                    FROM monitoring_normalized_rows
                    WHERE batch_id = ?
                    """,
                    (batch.batch_id,),
                ).fetchall()
            }
            observed_domains.update(
                str(row["domain"])
                for row in connection.execute(
                    """
                    SELECT DISTINCT domain
                    FROM monitoring_batch_schema_fields
                    WHERE batch_id = ?
                    """,
                    (batch.batch_id,),
                ).fetchall()
            )
            missing_domains = sorted(set(current.expected_domains) - observed_domains)
            if missing_domains:
                raise CompletenessGateError(
                    "normalized rows are missing expected domains: "
                    + ", ".join(missing_domains)
                )
            unresolved_warnings = connection.execute(
                """
                SELECT source_id, content_warnings_json
                FROM monitoring_sources
                WHERE source_id IN (
                    SELECT source_id FROM monitoring_batch_sources
                    WHERE batch_id = ?
                )
                  AND content_warnings_json != '[]'
                  AND (
                    medical_override_reason IS NULL
                    OR TRIM(medical_override_reason) = ''
                  )
                ORDER BY source_id
                """,
                (batch.batch_id,),
            ).fetchall()
            if unresolved_warnings:
                raise ContentValidationError(
                    "content warnings require a medical override reason before validation: "
                    + ", ".join(str(row["source_id"]) for row in unresolved_warnings)
                )
            return

        if target_state == "confirmed":
            current = self._batch_by_id(connection, batch.batch_id)
            proof = current.full_snapshot_proof
            if not current.active_mapping_revision or not current.expected_domains:
                raise CompletenessGateError(
                    "confirmed state requires mapping revision and expected_domains"
                )
            if not isinstance(proof, dict) or proof.get("confirmed") is not True:
                raise CompletenessGateError(
                    "full snapshot proof must be explicitly confirmed"
                )
            if not str(proof.get("basis", "")).strip():
                raise CompletenessGateError("full snapshot proof must state its basis")
            if not str(proof.get("confirmed_by", "")).strip():
                raise CompletenessGateError(
                    "full snapshot proof must record who confirmed it"
                )
            source_ids = [
                str(row["source_id"])
                for row in connection.execute(
                    """
                    SELECT source_id FROM monitoring_batch_sources
                    WHERE batch_id = ? ORDER BY source_id
                    """,
                    (batch.batch_id,),
                ).fetchall()
            ]
            row_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count FROM monitoring_normalized_rows
                    WHERE batch_id = ?
                    """,
                    (batch.batch_id,),
                ).fetchone()["count"]
            )
            if proof.get("snapshot_source_ids") != source_ids:
                raise CompletenessGateError(
                    "full snapshot proof source set no longer matches the batch"
                )
            if proof.get("observed_row_count") != row_count:
                raise CompletenessGateError(
                    "full snapshot proof row count no longer matches the batch"
                )
            if proof.get("expected_domains") != list(current.expected_domains):
                raise CompletenessGateError(
                    "full snapshot proof expected domains no longer match the batch"
                )
            disallowed_sources = connection.execute(
                """
                SELECT source_id, source_class, medical_override_reason
                FROM monitoring_sources
                WHERE source_id IN (
                    SELECT source_id FROM monitoring_batch_sources
                    WHERE batch_id = ?
                )
                ORDER BY source_id
                """,
                (batch.batch_id,),
            ).fetchall()
            processed_source_proof_is_sufficient = (
                proof.get("source_authority_grade") == "B"
                and proof.get("processed_source_acknowledged") is True
            )
            disallowed_sources = [
                row
                for row in disallowed_sources
                if (
                    str(row["source_class"]) not in BASELINE_ELIGIBLE_SOURCE_CLASSES
                    and not (
                        str(row["source_class"]) == "processed_full_snapshot"
                        and processed_source_proof_is_sufficient
                        and str(row["medical_override_reason"] or "").strip()
                    )
                )
            ]
            if disallowed_sources:
                details = ", ".join(
                    f"{row['source_id']}={row['source_class']}"
                    for row in disallowed_sources
                )
                raise CompletenessGateError(
                    "source class cannot qualify as a frozen full-snapshot baseline: "
                    + details
                )
            return

        if target_state == "frozen":
            return

        raise InvalidStateTransitionError(
            f"unsupported transition target: {target_state}"
        )

    def _mutate_batch(
        self,
        *,
        batch_id: str,
        expected_version: int,
        idempotency_key: str,
        operation: str,
        request: Dict[str, Any],
        allowed_states: Tuple[str, ...],
        mutation: Any,
    ) -> BatchMutationResult:
        request_sha256 = _json_hash(request)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT project_id FROM monitoring_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if row is None:
                raise RecordNotFoundError(f"batch not found: {batch_id}")
            project_id = str(row["project_id"])
            replay = self._idempotent_replay(
                connection,
                project_id,
                idempotency_key,
                request_sha256,
                expected_operation=operation,
            )
            if replay is not None:
                return self._mutation_result_from_dict(replay, replayed=True)

            batch = self._batch_by_id(connection, batch_id)
            if batch.state == "frozen":
                raise FrozenBatchError(f"batch is frozen: {batch_id}")
            if batch.version != expected_version:
                raise OptimisticVersionConflictError(
                    f"batch version conflict: expected {expected_version}, "
                    f"current {batch.version}"
                )
            if batch.state not in allowed_states:
                raise InvalidStateTransitionError(
                    f"operation {operation} is not allowed in state {batch.state}"
                )

            event_payload = mutation(connection, batch)
            now = _utc_now_text()
            next_version = batch.version + 1
            updated = connection.execute(
                """
                UPDATE monitoring_batches
                SET version = ?, updated_at = ?
                WHERE batch_id = ? AND version = ?
                """,
                (next_version, now, batch_id, expected_version),
            )
            if updated.rowcount != 1:
                raise OptimisticVersionConflictError(
                    "batch version changed during transaction"
                )
            current = self._batch_by_id(connection, batch_id)
            result = BatchMutationResult(batch=current, replayed=False)
            self._append_event(connection, current, operation, event_payload)
            self._store_idempotency(
                connection,
                project_id,
                idempotency_key,
                operation,
                request_sha256,
                result.to_dict(),
            )
            return result

    @staticmethod
    def _idempotent_replay(
        connection: sqlite3.Connection,
        project_id: str,
        idempotency_key: str,
        request_sha256: str,
        *,
        expected_operation: str,
    ) -> Optional[Dict[str, Any]]:
        row = connection.execute(
            """
            SELECT operation, request_sha256, response_json
            FROM monitoring_idempotency
            WHERE project_id = ? AND idempotency_key = ?
            """,
            (project_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != expected_operation:
            raise IdempotencyConflictError(
                "idempotency key was already used for a different operation"
            )
        persisted_request_sha256 = _require_exact_sha256(
            row["request_sha256"],
            "persisted idempotency request hash",
        )
        if persisted_request_sha256 != request_sha256:
            raise IdempotencyConflictError(
                "idempotency key was already used for a different request"
            )
        try:
            response = json.loads(row["response_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError(
                "persisted idempotency response is invalid JSON"
            ) from exc
        if not isinstance(response, Mapping):
            raise RepositoryIntegrityError(
                "persisted idempotency response must be an object"
            )
        payload = dict(response)
        batch = payload.get("batch")
        if not isinstance(batch, Mapping):
            raise RepositoryIntegrityError(
                "persisted idempotency response batch must be an object"
            )
        if str(batch.get("project_id") or "").strip() != project_id:
            raise RepositoryIntegrityError(
                "persisted idempotency response project binding mismatch"
            )
        return payload

    @staticmethod
    def _store_idempotency(
        connection: sqlite3.Connection,
        project_id: str,
        idempotency_key: str,
        operation: str,
        request_sha256: str,
        response: Dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO monitoring_idempotency(
                project_id, idempotency_key, operation,
                request_sha256, response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                idempotency_key,
                operation,
                request_sha256,
                _canonical_json(response),
                _utc_now_text(),
            ),
        )

    @staticmethod
    def _mutation_result_from_dict(
        payload: Dict[str, Any],
        *,
        replayed: bool,
    ) -> BatchMutationResult:
        batch_payload = dict(payload["batch"])
        batch_payload["expected_domains"] = tuple(
            batch_payload.get("expected_domains", ())
        )
        return BatchMutationResult(
            batch=BatchRecord(**batch_payload),
            replayed=replayed,
        )

    @staticmethod
    def _derived_snapshot_result_from_dict(
        payload: Dict[str, Any],
        *,
        replayed: bool,
    ) -> DerivedSnapshotVerificationResult:
        batch_payload = dict(payload["batch"])
        batch_payload["expected_domains"] = tuple(
            batch_payload.get("expected_domains", ())
        )
        return DerivedSnapshotVerificationResult(
            batch=BatchRecord(**batch_payload),
            proof=dict(payload["proof"]),
            source_summary=dict(payload["source"]),
            fact_summary=dict(payload["facts"]),
            medical_summary=dict(payload["medical_summary"]),
            replayed=replayed,
        )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        batch: BatchRecord,
        event_type: str,
        payload: Dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO monitoring_batch_events(
                batch_id, project_id, batch_version,
                event_type, state, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch.batch_id,
                batch.project_id,
                batch.version,
                event_type,
                batch.state,
                _canonical_json(payload),
                _utc_now_text(),
            ),
        )

    def get_batch(self, batch_id: str) -> BatchRecord:
        with self._connect() as connection:
            return self._batch_by_id(connection, _require_text(batch_id, "batch_id"))

    def load_field_profile_cache_identity(
        self,
        batch_id: str,
    ) -> FieldProfileBatchIdentity:
        """Return a lightweight immutable identity for field-profile caching."""
        normalized_batch_id = _require_text(batch_id, "batch_id")
        with self._connect() as connection:
            batch = self._batch_by_id(connection, normalized_batch_id)
            if batch.state not in {"parsed", "validated", "confirmed", "frozen"}:
                raise CompletenessGateError(
                    "batch must be parsed before a field profile can be built: "
                    f"{batch.batch_id}"
                )
            source_rows = connection.execute(
                """
                SELECT s.source_id, s.source_entry_id, s.content_sha256,
                       s.binding_revision, s.binding_sha256
                FROM monitoring_batch_sources bs
                JOIN monitoring_sources s ON s.source_id = bs.source_id
                WHERE bs.batch_id = ?
                ORDER BY s.source_entry_id, s.source_id
                """,
                (normalized_batch_id,),
            ).fetchall()
            replace_event = connection.execute(
                """
                SELECT batch_version, payload_json
                FROM monitoring_batch_events
                WHERE batch_id = ? AND event_type = 'replace_rows'
                ORDER BY batch_version DESC
                LIMIT 1
                """,
                (normalized_batch_id,),
            ).fetchone()
            row_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM monitoring_normalized_rows
                    WHERE batch_id = ?
                    """,
                    (normalized_batch_id,),
                ).fetchone()["count"]
            )
            schema_fields = tuple(
                (
                    str(row["domain"]),
                    str(row["field_name"]),
                    str(row["source_sheet"]),
                )
                for row in connection.execute(
                    """
                    SELECT domain, field_name, source_sheet
                    FROM monitoring_batch_schema_fields
                    WHERE batch_id = ?
                    ORDER BY domain, field_name, source_sheet
                    """,
                    (normalized_batch_id,),
                ).fetchall()
            )

        if replace_event is None:
            raise RepositoryIntegrityError(
                "field-profile cache identity requires a replace_rows event"
            )
        if int(replace_event["batch_version"]) > batch.version:
            raise RepositoryIntegrityError(
                "replace_rows event is newer than the current batch revision"
            )
        try:
            event_payload = dict(json.loads(str(replace_event["payload_json"])))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError(
                "replace_rows event payload is invalid"
            ) from exc
        try:
            event_row_count = int(event_payload.get("row_count", -1))
            event_schema_count = int(
                event_payload.get("schema_field_count", -1)
            )
        except (TypeError, ValueError) as exc:
            raise RepositoryIntegrityError(
                "replace_rows event counts are invalid"
            ) from exc
        if event_row_count != row_count:
            raise RepositoryIntegrityError(
                "normalized row count no longer matches replace_rows evidence"
            )
        if event_schema_count != len(schema_fields):
            raise RepositoryIntegrityError(
                "schema field count no longer matches replace_rows evidence"
            )
        row_set_sha256 = _require_cache_identity_sha256(
            event_payload.get("row_set_sha256"),
            "row_set_sha256",
        )
        schema_fields_sha256 = _require_cache_identity_sha256(
            event_payload.get("schema_fields_sha256"),
            "schema_fields_sha256",
        )
        current_schema_sha256 = _json_hash(
            [
                {
                    "domain": domain,
                    "field": field,
                    "source_sheet": source_sheet,
                }
                for domain, field, source_sheet in schema_fields
            ]
        )
        if current_schema_sha256 != schema_fields_sha256:
            raise RepositoryIntegrityError(
                "schema fields no longer match replace_rows evidence"
            )

        source_bindings = tuple(
            FieldProfileSourceBindingIdentity(
                source_id=str(row["source_id"]),
                source_entry_id=str(row["source_entry_id"]),
                source_content_sha256=_require_cache_identity_sha256(
                    row["content_sha256"],
                    "source_content_sha256",
                ),
                binding_revision=int(row["binding_revision"]),
                binding_sha256=_require_cache_identity_sha256(
                    row["binding_sha256"],
                    "binding_sha256",
                ),
            )
            for row in source_rows
        )
        entry_content_pairs = {
            (binding.source_entry_id, binding.source_content_sha256)
            for binding in source_bindings
        }
        entry_ids = [source_entry_id for source_entry_id, _ in entry_content_pairs]
        if len(entry_ids) != len(set(entry_ids)):
            raise CompletenessGateError(
                "batch binds one source entry ID to multiple content hashes"
            )
        content_identity_sha256 = _json_hash(
            {
                "row_count": row_count,
                "row_set_sha256": row_set_sha256,
                "schema_field_count": len(schema_fields),
                "schema_fields_sha256": schema_fields_sha256,
            }
        )
        source_binding_payload = [
            binding.to_dict() for binding in source_bindings
        ]
        source_binding_identity_sha256 = _json_hash(source_binding_payload)
        identity_payload = {
            "schema_version": "monitoring_field_profile_batch_identity.v1",
            "batch_id": batch.batch_id,
            "project_id": batch.project_id,
            "state": batch.state,
            "batch_version": batch.version,
            "expected_domains": list(batch.expected_domains),
            "mapping_revision": batch.active_mapping_revision,
            "source_bindings": source_binding_payload,
            "content_identity_sha256": content_identity_sha256,
            "source_binding_identity_sha256": (
                source_binding_identity_sha256
            ),
        }
        return FieldProfileBatchIdentity(
            schema_version="monitoring_field_profile_batch_identity.v1",
            batch_id=batch.batch_id,
            project_id=batch.project_id,
            state=batch.state,
            batch_version=batch.version,
            expected_domains=batch.expected_domains,
            mapping_revision=batch.active_mapping_revision,
            source_bindings=source_bindings,
            row_count=row_count,
            row_set_sha256=row_set_sha256,
            schema_field_count=len(schema_fields),
            schema_fields_sha256=schema_fields_sha256,
            content_identity_sha256=content_identity_sha256,
            source_binding_identity_sha256=(
                source_binding_identity_sha256
            ),
            identity_sha256=_json_hash(identity_payload),
        )

    def list_batches(self, project_id: str) -> Tuple[BatchRecord, ...]:
        project_id = _require_text(project_id, "project_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM monitoring_batches
                WHERE project_id = ?
                ORDER BY created_at DESC, batch_id DESC
                """,
                (project_id,),
            ).fetchall()
        return tuple(self._batch_from_row(row) for row in rows)

    def batch_summary(self, batch_id: str) -> Dict[str, Any]:
        batch_id = _require_text(batch_id, "batch_id")
        with self._connect() as connection:
            batch = self._batch_by_id(connection, batch_id)
            source_rows = connection.execute(
                """
                SELECT s.*, o.blob_relative_path
                FROM monitoring_batch_sources bs
                JOIN monitoring_sources s ON s.source_id = bs.source_id
                JOIN monitoring_content_objects o
                  ON o.content_sha256 = s.content_sha256
                WHERE bs.batch_id = ?
                ORDER BY bs.attached_at, s.source_id
                """,
                (batch_id,),
            ).fetchall()
            row_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM monitoring_normalized_rows
                    WHERE batch_id = ?
                    """,
                    (batch_id,),
                ).fetchone()["count"]
            )
            domain_rows = connection.execute(
                """
                SELECT domain, COUNT(*) AS count
                FROM monitoring_normalized_rows
                WHERE batch_id = ?
                GROUP BY domain
                ORDER BY domain
                """,
                (batch_id,),
            ).fetchall()
        return {
            "batch": batch.to_dict(),
            "sources": [self._source_from_row(row).to_dict() for row in source_rows],
            "row_count": row_count,
            "domain_counts": {
                str(row["domain"]): int(row["count"]) for row in domain_rows
            },
        }

    @staticmethod
    def _batch_by_id(
        connection: sqlite3.Connection,
        batch_id: str,
    ) -> BatchRecord:
        row = connection.execute(
            "SELECT * FROM monitoring_batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if row is None:
            raise RecordNotFoundError(f"batch not found: {batch_id}")
        return MonitoringBatchRepository._batch_from_row(row)

    @staticmethod
    def _batch_from_row(row: sqlite3.Row) -> BatchRecord:
        try:
            batch_id = _require_text(row["batch_id"], "batch_id")
            project_id = _require_text(row["project_id"], "project_id")
            state = _require_text(row["state"], "state")
            if state not in BATCH_STATES:
                raise RepositoryIntegrityError(
                    "persisted monitoring batch state is invalid"
                )

            raw_version = row["version"]
            if isinstance(raw_version, bool):
                raise RepositoryIntegrityError(
                    "persisted monitoring batch version is invalid"
                )
            if not isinstance(raw_version, int) or raw_version < 1:
                raise RepositoryIntegrityError(
                    "persisted monitoring batch version is invalid"
                )
            version = raw_version

            raw_domains = json.loads(str(row["expected_domains_json"]))
            if not isinstance(raw_domains, list) or not all(
                isinstance(domain, str) for domain in raw_domains
            ):
                raise RepositoryIntegrityError(
                    "persisted monitoring batch expected domains must be a list of strings"
                )
            expected_domains = _normalize_domains(raw_domains)
            if list(expected_domains) != raw_domains:
                raise RepositoryIntegrityError(
                    "persisted monitoring batch expected domains are non-canonical"
                )

            raw_proof = row["full_snapshot_proof_json"]
            if raw_proof is None:
                full_snapshot_proof = None
            else:
                proof = json.loads(str(raw_proof))
                if not isinstance(proof, Mapping):
                    raise RepositoryIntegrityError(
                        "persisted monitoring batch full snapshot proof must be an object"
                    )
                full_snapshot_proof = dict(proof)

            def persisted_timestamp(value: Any, field: str) -> str:
                timestamp = str(value or "").strip()
                if not timestamp:
                    raise RepositoryIntegrityError(
                        f"persisted monitoring batch {field} is invalid"
                    )
                try:
                    datetime.fromisoformat(timestamp)
                except (TypeError, ValueError) as exc:
                    raise RepositoryIntegrityError(
                        f"persisted monitoring batch {field} is invalid"
                    ) from exc
                return timestamp

            created_at = persisted_timestamp(row["created_at"], "created_at")
            updated_at = persisted_timestamp(row["updated_at"], "updated_at")
            raw_frozen_at = row["frozen_at"]
            if state == "frozen":
                frozen_at = persisted_timestamp(raw_frozen_at, "frozen_at")
            else:
                if raw_frozen_at is not None:
                    raise RepositoryIntegrityError(
                        "persisted monitoring batch frozen_at conflicts with state"
                    )
                frozen_at = None
        except RepositoryIntegrityError:
            raise
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError(
                "persisted monitoring batch root is invalid"
            ) from exc

        return BatchRecord(
            batch_id=batch_id,
            project_id=project_id,
            state=state,
            version=version,
            expected_domains=expected_domains,
            active_mapping_revision=(
                str(row["active_mapping_revision"])
                if row["active_mapping_revision"] is not None
                else None
            ),
            full_snapshot_proof=full_snapshot_proof,
            created_at=created_at,
            updated_at=updated_at,
            frozen_at=frozen_at,
        )

    def list_rows(self, batch_id: str) -> Tuple[NormalizedRow, ...]:
        with self._connect() as connection:
            normalized_batch_id = _require_text(batch_id, "batch_id")
            self._batch_by_id(connection, normalized_batch_id)
            rows = connection.execute(
                """
                SELECT business_key, domain, data_json,
                       source_locator_json, row_fingerprint
                FROM monitoring_normalized_rows
                WHERE batch_id = ?
                ORDER BY business_key
                """,
                (normalized_batch_id,),
            ).fetchall()
            normalized = tuple(
                self._normalized_row_from_row(row)
                for row in rows
            )
            if normalized:
                replace_event = connection.execute(
                    """
                    SELECT payload_json
                    FROM monitoring_batch_events
                    WHERE batch_id = ? AND event_type = 'replace_rows'
                    ORDER BY batch_version DESC
                    LIMIT 1
                    """,
                    (normalized_batch_id,),
                ).fetchone()
                if replace_event is None:
                    raise RepositoryIntegrityError(
                        "normalized rows lack replace_rows evidence"
                    )
                try:
                    event_payload = json.loads(str(replace_event["payload_json"]))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RepositoryIntegrityError(
                        "replace_rows event payload is invalid"
                    ) from exc
                if not isinstance(event_payload, Mapping):
                    raise RepositoryIntegrityError(
                        "replace_rows event payload must be an object"
                    )
                expected_row_set_sha256 = _require_cache_identity_sha256(
                    event_payload.get("row_set_sha256"),
                    "row_set_sha256",
                )
                if _rows_hash(normalized) != expected_row_set_sha256:
                    raise RepositoryIntegrityError(
                        "normalized rows no longer match replace_rows evidence"
                    )
        return normalized

    @staticmethod
    def _normalized_row_from_row(row: sqlite3.Row) -> NormalizedRow:
        try:
            data = json.loads(str(row["data_json"]))
            source_locator = json.loads(str(row["source_locator_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError(
                "normalized row payload is invalid JSON"
            ) from exc
        if not isinstance(data, Mapping) or not isinstance(source_locator, Mapping):
            raise RepositoryIntegrityError(
                "normalized row payload must contain object data and source locator"
            )
        business_key = str(row["business_key"] or "").strip()
        domain = str(row["domain"] or "").strip().upper()
        if not business_key or not domain or not source_locator:
            raise RepositoryIntegrityError("normalized row identity is incomplete")
        data_dict = dict(data)
        source_locator_dict = dict(source_locator)
        expected_fingerprint = _json_hash(
            {
                "domain": domain,
                "data": data_dict,
            }
        )
        raw_fingerprint = row["row_fingerprint"]
        if (
            not isinstance(raw_fingerprint, str)
            or raw_fingerprint != raw_fingerprint.strip()
            or raw_fingerprint != raw_fingerprint.lower()
        ):
            raise RepositoryIntegrityError(
                "normalized row fingerprint is not canonical"
            )
        if raw_fingerprint != expected_fingerprint:
            raise RepositoryIntegrityError(
                "normalized row fingerprint does not match its payload"
            )
        return NormalizedRow(
            business_key=business_key,
            domain=domain,
            data=data_dict,
            source_locator=source_locator_dict,
            row_fingerprint=expected_fingerprint,
        )

    def load_diff_ready_batch(self, batch_id: str) -> DiffReadyBatch:
        batch = self.load_profile_ready_batch(batch_id)
        if batch.state != "frozen":
            raise CompletenessGateError(
                f"batch is not frozen and cannot be used for diff: {batch.batch_id}"
            )
        return batch

    def load_frozen_mapping_contract(
        self,
        batch_id: str,
    ) -> FrozenBatchMappingContract:
        """Read and integrity-check the mapping revision frozen with a batch."""

        with self._connect() as connection:
            batch = self._batch_by_id(
                connection,
                _require_text(batch_id, "batch_id"),
            )
            if batch.state != "frozen":
                raise CompletenessGateError(
                    "field mapping may be resolved only from a frozen batch"
                )
            mapping_revision = str(batch.active_mapping_revision or "").strip()
            if not mapping_revision:
                raise CompletenessGateError(
                    "frozen batch has no confirmed field mapping revision"
                )
            row = connection.execute(
                """
                SELECT mapping_json, mapping_sha256
                FROM monitoring_mapping_revisions
                WHERE batch_id = ? AND mapping_revision = ?
                """,
                (batch.batch_id, mapping_revision),
            ).fetchone()
            if row is None:
                raise RepositoryIntegrityError(
                    "frozen batch mapping revision is absent from its repository"
                )

        try:
            payload = json.loads(str(row["mapping_json"]))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RepositoryIntegrityError(
                "frozen batch mapping payload is not valid JSON"
            ) from exc
        if not isinstance(payload, Mapping):
            raise RepositoryIntegrityError(
                "frozen batch mapping payload must be an object"
            )
        def canonical_mapping_hash(value: Any, field: str) -> str:
            if not isinstance(value, str) or value != value.strip():
                raise RepositoryIntegrityError(
                    f"frozen batch mapping {field} is invalid"
                )
            if value != value.lower():
                raise RepositoryIntegrityError(
                    f"frozen batch mapping {field} is not canonical"
                )
            if len(value) != 64 or any(
                character not in "0123456789abcdef" for character in value
            ):
                raise RepositoryIntegrityError(
                    f"frozen batch mapping {field} is invalid"
                )
            return value

        mapping_sha256 = canonical_mapping_hash(
            row["mapping_sha256"],
            "repository hash",
        )
        if _json_hash(payload) != mapping_sha256:
            raise RepositoryIntegrityError(
                "frozen batch mapping payload does not match its repository hash"
            )
        if payload.get("schema_version") not in {
            "monitoring_project_mapping_v1",
            "monitoring_project_mapping_v2",
        }:
            raise RepositoryIntegrityError(
                "frozen batch mapping schema is not supported for record resolution"
            )
        if str(payload.get("mapping_revision") or "").strip() != mapping_revision:
            raise RepositoryIntegrityError(
                "frozen batch mapping revision identity is inconsistent"
            )

        mapping_content_sha256 = canonical_mapping_hash(
            payload.get("mapping_content_sha256"),
            "mapping_content_sha256",
        )
        source_profile_sha256 = canonical_mapping_hash(
            payload.get("source_profile_sha256"),
            "source_profile_sha256",
        )
        source_batch_id = str(payload.get("source_batch_id") or "").strip()
        if not source_batch_id:
            raise RepositoryIntegrityError(
                "frozen batch mapping source_batch_id is required"
            )
        raw_fields = payload.get("fields")
        if not isinstance(raw_fields, list):
            raise RepositoryIntegrityError(
                "frozen batch mapping fields must be a list"
            )
        fields: List[Dict[str, Any]] = []
        field_keys: set[Tuple[str, str]] = set()
        for raw_field in raw_fields:
            if not isinstance(raw_field, Mapping):
                raise RepositoryIntegrityError(
                    "frozen batch mapping contains an invalid field entry"
                )
            field = dict(raw_field)
            domain = str(field.get("domain") or "").strip().upper()
            source_field = str(field.get("source_field") or "").strip()
            recommended_role = str(
                field.get("recommended_role") or ""
            ).strip()
            if not domain or not source_field or not recommended_role:
                raise RepositoryIntegrityError(
                    "frozen batch mapping field identity is incomplete"
                )
            key = (domain, source_field.casefold())
            if key in field_keys:
                raise RepositoryIntegrityError(
                    "frozen batch mapping contains duplicate domain/field identities"
                )
            field_keys.add(key)
            field["domain"] = domain
            field["source_field"] = source_field
            field["recommended_role"] = recommended_role
            fields.append(field)

        semantic_quality_report_sha256 = ""
        capability_manifest_sha256 = ""
        activation_disposition = ""
        effective_capabilities_sha256 = ""
        effective_capabilities: Tuple[str, ...] = ()
        capability_states: Tuple[Dict[str, Any], ...] = ()
        if payload.get("schema_version") == "monitoring_project_mapping_v2":
            semantic_quality_report_sha256 = canonical_mapping_hash(
                payload.get("semantic_quality_report_sha256"),
                "semantic_quality_report_sha256",
            )
            capability_manifest_sha256 = canonical_mapping_hash(
                payload.get("capability_manifest_sha256"),
                "capability_manifest_sha256",
            )
            effective_capabilities_sha256 = canonical_mapping_hash(
                payload.get("effective_capabilities_sha256"),
                "effective_capabilities_sha256",
            )
            activation_disposition = str(
                payload.get("activation_disposition") or ""
            ).strip()
            if activation_disposition not in {
                "activate_full",
                "activate_restricted",
            }:
                raise RepositoryIntegrityError(
                    "frozen batch mapping activation disposition is invalid"
                )
            raw_effective = payload.get("effective_capabilities")
            raw_states = payload.get("capability_states")
            if not isinstance(raw_effective, list) or not isinstance(
                raw_states, list
            ):
                raise RepositoryIntegrityError(
                    "frozen batch mapping capability snapshot is incomplete"
                )
            effective_capabilities = tuple(
                str(item).strip()
                for item in raw_effective
                if str(item).strip()
            )
            normalized_states: list[Dict[str, Any]] = []
            seen_capabilities: set[str] = set()
            for raw_state in raw_states:
                if not isinstance(raw_state, Mapping):
                    raise RepositoryIntegrityError(
                        "frozen batch mapping capability state is invalid"
                    )
                state = dict(raw_state)
                capability_id = str(
                    state.get("capability_id") or ""
                ).strip()
                capability_state = str(state.get("state") or "").strip()
                if (
                    not capability_id
                    or capability_id in seen_capabilities
                    or capability_state
                    not in {
                        "ready",
                        "limited",
                        "blocked_by_quality",
                        "disabled_by_design",
                    }
                ):
                    raise RepositoryIntegrityError(
                        "frozen batch mapping capability identity is invalid"
                    )
                seen_capabilities.add(capability_id)
                state["capability_id"] = capability_id
                state["state"] = capability_state
                normalized_states.append(state)
            if set(effective_capabilities) != {
                str(item["capability_id"])
                for item in normalized_states
                if item["state"] in {"ready", "limited"}
            }:
                raise RepositoryIntegrityError(
                    "frozen batch mapping effective capability set is inconsistent"
                )
            capability_states = tuple(normalized_states)

        return FrozenBatchMappingContract(
            schema_version=str(payload["schema_version"]),
            batch_id=batch.batch_id,
            project_id=batch.project_id,
            batch_version=batch.version,
            mapping_revision=mapping_revision,
            mapping_sha256=mapping_sha256,
            mapping_content_sha256=mapping_content_sha256,
            source_batch_id=source_batch_id,
            source_profile_sha256=source_profile_sha256,
            fields=tuple(fields),
            semantic_quality_report_sha256=semantic_quality_report_sha256,
            capability_manifest_sha256=capability_manifest_sha256,
            activation_disposition=activation_disposition,
            effective_capabilities_sha256=effective_capabilities_sha256,
            effective_capabilities=effective_capabilities,
            capability_states=capability_states,
        )

    def load_profile_ready_batch(self, batch_id: str) -> DiffReadyBatch:
        with self._connect() as connection:
            batch = self._batch_by_id(connection, _require_text(batch_id, "batch_id"))
            if batch.state not in {"parsed", "validated", "confirmed", "frozen"}:
                raise CompletenessGateError(
                    "batch must be parsed before a field profile can be built: "
                    f"{batch.batch_id}"
                )
            source_bindings = tuple(
                (
                    str(row["source_entry_id"]),
                    _require_exact_sha256(
                        row["content_sha256"],
                        "source content hash",
                    ),
                )
                for row in connection.execute(
                    """
                    SELECT DISTINCT s.source_entry_id, s.content_sha256
                    FROM monitoring_sources s
                    JOIN monitoring_batch_sources bs
                      ON bs.source_id = s.source_id
                    WHERE bs.batch_id = ?
                    ORDER BY s.source_entry_id, s.content_sha256
                    """,
                    (batch_id,),
                ).fetchall()
            )
            source_ids = tuple(
                str(row["source_id"])
                for row in connection.execute(
                    """
                    SELECT source_id
                    FROM monitoring_batch_sources
                    WHERE batch_id = ?
                    ORDER BY source_id
                    """,
                    (batch_id,),
                ).fetchall()
            )
            entry_ids = [source_entry_id for source_entry_id, _ in source_bindings]
            if len(entry_ids) != len(set(entry_ids)):
                raise CompletenessGateError(
                    "frozen batch binds one source entry ID to multiple content hashes"
                )
            source_hashes = tuple(
                sorted({content_sha256 for _, content_sha256 in source_bindings})
            )
            schema_fields = tuple(
                (
                    str(row["domain"]),
                    str(row["field_name"]),
                    str(row["source_sheet"]),
                )
                for row in connection.execute(
                    """
                    SELECT domain, field_name, source_sheet
                    FROM monitoring_batch_schema_fields
                    WHERE batch_id = ?
                    ORDER BY domain, field_name, source_sheet
                    """,
                    (batch_id,),
                ).fetchall()
            )
        rows = self.list_rows(batch_id)
        full_snapshot_proven = self._full_snapshot_proof_is_valid(
            batch,
            source_ids=source_ids,
            rows=rows,
        )
        return DiffReadyBatch(
            batch_id=batch.batch_id,
            project_id=batch.project_id,
            state=batch.state,
            version=batch.version,
            expected_domains=batch.expected_domains,
            mapping_revision=batch.active_mapping_revision,
            source_bindings=source_bindings,
            source_hashes=source_hashes,
            rows=rows,
            schema_fields=schema_fields,
            full_snapshot_proven=full_snapshot_proven,
        )

    @staticmethod
    def _full_snapshot_proof_is_valid(
        batch: BatchRecord,
        *,
        source_ids: Tuple[str, ...],
        rows: Tuple[NormalizedRow, ...],
    ) -> bool:
        """Re-check immutable proof before a diff can resolve removals."""

        proof = batch.full_snapshot_proof
        if batch.state != "frozen" or not isinstance(proof, Mapping):
            return False
        if proof.get("confirmed") is not True:
            return False
        if not str(proof.get("basis") or "").strip():
            return False
        if not str(proof.get("confirmed_by") or "").strip():
            return False
        if proof.get("snapshot_source_ids") != list(source_ids):
            return False
        if proof.get("observed_row_count") != len(rows):
            return False
        if proof.get("expected_domains") != list(batch.expected_domains):
            return False
        return True

    def diff_batches(
        self,
        previous_batch_id: str,
        current_batch_id: str,
    ) -> BatchDiff:
        from .monitoring_batch_diff import diff_monitoring_batches

        previous = self.load_diff_ready_batch(previous_batch_id)
        current = self.load_diff_ready_batch(current_batch_id)
        if previous.project_id != current.project_id:
            raise MonitoringBatchRepositoryError(
                "cannot diff batches from different projects"
            )
        detailed = diff_monitoring_batches(
            (row.to_dict() for row in previous.rows),
            (row.to_dict() for row in current.rows),
            previous_mapping_revision=previous.mapping_revision or "",
            current_mapping_revision=current.mapping_revision or "",
            expected_domains=set(current.expected_domains),
            full_snapshot_proven=bool(
                previous.full_snapshot_proven and current.full_snapshot_proven
            ),
            previous_schema_fields=previous.schema_fields,
            current_schema_fields=current.schema_fields,
        )
        return BatchDiff(
            previous_batch_id=previous.batch_id,
            current_batch_id=current.batch_id,
            added_business_keys=tuple(detailed.row_diff.new_keys),
            removed_business_keys=tuple(detailed.row_diff.removed_keys),
            changed_business_keys=tuple(detailed.row_diff.changed_keys),
            unchanged_business_keys=tuple(detailed.row_diff.persisting_keys),
            removal_eligible_business_keys=tuple(detailed.removal_eligible_keys),
            removal_blocked_business_keys=tuple(detailed.removal_blocked_keys),
            full_snapshot_proven=detailed.full_snapshot_proven,
        )

    def integrity_check(self) -> str:
        with self._connect() as connection:
            result = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if result != "ok":
            raise RepositoryIntegrityError(f"sqlite integrity_check failed: {result}")
        return result
