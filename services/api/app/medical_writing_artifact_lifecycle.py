"""Policy-neutral lifecycle persistence for medical-writing export artifacts.

This module is deliberately route-free.  It provides an isolated repository
for the contract designed in ``mw_protocol_p0_artifact_lifecycle_contract``:
artifact identity is immutable, lifecycle transitions are audited and
idempotent, retention is policy-driven (never duration-driven here), and
rollback moves an immutable current-generation pointer rather than mutating or
deleting an artifact.

Authentication, policy selection, physical storage, and electronic-signature
providers remain outside this module.  Callers must provide a typed,
server-derived authenticated principal; a client ``actor`` string is not a
trust boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4


MEDICAL_WRITING_ARTIFACT_LIFECYCLE_SCHEMA = (
    "medical_writing_artifact_lifecycle_v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_MODES = frozenset({"draft_preview", "approved_final"})
_STATES = frozenset({"active", "purge_requested", "purged"})


class MedicalWritingArtifactLifecycleError(ValueError):
    """Base error for the isolated artifact lifecycle repository."""


class MedicalWritingArtifactLifecycleConflict(
    MedicalWritingArtifactLifecycleError
):
    """Raised when an idempotency key or immutable identity conflicts."""


class MedicalWritingArtifactLifecycleNotFound(
    MedicalWritingArtifactLifecycleError
):
    """Raised when a project-scoped artifact or pointer is not present."""


class MedicalWritingArtifactLifecycleStale(
    MedicalWritingArtifactLifecycleError
):
    """Raised when a caller's expected pointer/version is stale."""


class MedicalWritingArtifactLifecycleAuthorizationError(
    MedicalWritingArtifactLifecycleError
):
    """Raised when the caller does not provide a trusted principal."""


class MedicalWritingArtifactLifecycleIntegrityError(
    MedicalWritingArtifactLifecycleError
):
    """Raised when identity, policy, or proof data is malformed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_datetime(value: datetime | str, *, field_name: str) -> str:
    if isinstance(value, datetime):
        candidate = value
    else:
        candidate = _parse_datetime(str(value), field_name=field_name)
    if candidate.tzinfo is None:
        raise MedicalWritingArtifactLifecycleIntegrityError(
            f"{field_name} must include a timezone"
        )
    return candidate.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str, *, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise MedicalWritingArtifactLifecycleIntegrityError(
            f"{field_name} is required"
        )
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MedicalWritingArtifactLifecycleIntegrityError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise MedicalWritingArtifactLifecycleIntegrityError(
            f"{field_name} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _require_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MedicalWritingArtifactLifecycleIntegrityError(
            f"{field_name} is required"
        )
    return text


def _require_sha256(value: Any, *, field_name: str) -> str:
    text = _require_text(value, field_name=field_name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise MedicalWritingArtifactLifecycleIntegrityError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return text


def _safe_relative_path(value: Any) -> str:
    raw = _require_text(value, field_name="artifact_relpath")
    if "\\" in raw:
        raise MedicalWritingArtifactLifecycleIntegrityError(
            "artifact_relpath must use POSIX separators"
        )
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise MedicalWritingArtifactLifecycleIntegrityError(
            "artifact_relpath must be a normalized relative path"
        )
    normalized = candidate.as_posix()
    if normalized != raw:
        raise MedicalWritingArtifactLifecycleIntegrityError(
            "artifact_relpath must be a normalized relative path"
        )
    return normalized


@dataclass(frozen=True)
class MedicalWritingArtifactPrincipal:
    """A server-derived identity assertion consumed by this repository."""

    subject_id: str
    tenant_id: str
    role: str
    assurance: str
    authenticated: bool = False

    def validate_for(self, *, tenant_id: str, project_id: str) -> None:
        if not self.authenticated:
            raise MedicalWritingArtifactLifecycleAuthorizationError(
                "authenticated principal is required"
            )
        if str(self.tenant_id or "").strip() != str(tenant_id or "").strip():
            raise MedicalWritingArtifactLifecycleAuthorizationError(
                "principal tenant does not match the artifact tenant"
            )
        _require_text(self.subject_id, field_name="principal.subject_id")
        _require_text(self.role, field_name="principal.role")
        _require_text(self.assurance, field_name="principal.assurance")
        _require_text(project_id, field_name="project_id")

    def as_dict(self) -> Dict[str, Any]:
        return {
            "subject_id": _require_text(
                self.subject_id, field_name="principal.subject_id"
            ),
            "tenant_id": _require_text(
                self.tenant_id, field_name="principal.tenant_id"
            ),
            "role": _require_text(self.role, field_name="principal.role"),
            "assurance": _require_text(
                self.assurance, field_name="principal.assurance"
            ),
            "authenticated": bool(self.authenticated),
        }


@dataclass(frozen=True)
class MedicalWritingArtifactRetentionPolicy:
    """A caller-selected policy reference; no retention duration is inferred."""

    policy_id: str
    policy_revision: int
    minimum_retain_until: str
    purge_eligible_at: str
    legal_hold: bool = False

    def as_dict(self) -> Dict[str, Any]:
        policy_id = _require_text(self.policy_id, field_name="policy_id")
        try:
            revision = int(self.policy_revision)
        except (TypeError, ValueError) as exc:
            raise MedicalWritingArtifactLifecycleIntegrityError(
                "policy_revision must be an integer"
            ) from exc
        if revision < 1:
            raise MedicalWritingArtifactLifecycleIntegrityError(
                "policy_revision must be >= 1"
            )
        minimum = _iso_datetime(
            self.minimum_retain_until,
            field_name="minimum_retain_until",
        )
        eligible = _iso_datetime(
            self.purge_eligible_at,
            field_name="purge_eligible_at",
        )
        return {
            "policy_id": policy_id,
            "policy_revision": revision,
            "minimum_retain_until": minimum,
            "purge_eligible_at": eligible,
            "legal_hold": bool(self.legal_hold),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "MedicalWritingArtifactRetentionPolicy":
        return cls(
            policy_id=str(payload.get("policy_id") or ""),
            policy_revision=int(payload.get("policy_revision") or 0),
            minimum_retain_until=str(payload.get("minimum_retain_until") or ""),
            purge_eligible_at=str(payload.get("purge_eligible_at") or ""),
            legal_hold=bool(payload.get("legal_hold")),
        )


@dataclass(frozen=True)
class MedicalWritingArtifactIdentity:
    tenant_id: str
    project_id: str
    document_id: str
    generation_id: str
    export_job_id: str
    mode: str
    source_snapshot_sha256: str
    docx_sha256: str
    manifest_sha256: str

    def as_dict(self) -> Dict[str, Any]:
        mode = _require_text(self.mode, field_name="mode")
        if mode not in _SUPPORTED_MODES:
            raise MedicalWritingArtifactLifecycleIntegrityError(
                f"unsupported artifact mode: {mode!r}"
            )
        return {
            "schema_version": MEDICAL_WRITING_ARTIFACT_LIFECYCLE_SCHEMA,
            "tenant_id": _require_text(self.tenant_id, field_name="tenant_id"),
            "project_id": _require_text(self.project_id, field_name="project_id"),
            "document_id": _require_text(self.document_id, field_name="document_id"),
            "generation_id": _require_text(
                self.generation_id, field_name="generation_id"
            ),
            "export_job_id": _require_text(
                self.export_job_id, field_name="export_job_id"
            ),
            "mode": mode,
            "source_snapshot_sha256": _require_sha256(
                self.source_snapshot_sha256,
                field_name="source_snapshot_sha256",
            ),
            "docx_sha256": _require_sha256(
                self.docx_sha256,
                field_name="docx_sha256",
            ),
            "manifest_sha256": _require_sha256(
                self.manifest_sha256,
                field_name="manifest_sha256",
            ),
        }

    @property
    def artifact_id(self) -> str:
        return "mwartifact_" + _payload_hash(self.as_dict())[:32]

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "MedicalWritingArtifactIdentity":
        return cls(
            tenant_id=str(payload.get("tenant_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            document_id=str(payload.get("document_id") or ""),
            generation_id=str(payload.get("generation_id") or ""),
            export_job_id=str(payload.get("export_job_id") or ""),
            mode=str(payload.get("mode") or ""),
            source_snapshot_sha256=str(payload.get("source_snapshot_sha256") or ""),
            docx_sha256=str(payload.get("docx_sha256") or ""),
            manifest_sha256=str(payload.get("manifest_sha256") or ""),
        )


@dataclass(frozen=True)
class MedicalWritingArtifactRecord:
    artifact_id: str
    identity: MedicalWritingArtifactIdentity
    artifact_relpath: str
    policy: MedicalWritingArtifactRetentionPolicy
    state: str
    current_pointer: bool
    version: int
    created_at: str
    updated_at: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "identity": self.identity.as_dict(),
            "artifact_relpath": self.artifact_relpath,
            "policy": self.policy.as_dict(),
            "state": self.state,
            "current_pointer": bool(self.current_pointer),
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class MedicalWritingArtifactLifecycleResult:
    record: MedicalWritingArtifactRecord
    event_id: str
    action: str
    allowed: bool
    reason: str
    replayed: bool = False
    pointer_revision: int = 0


class MedicalWritingArtifactLifecycleRepository:
    """Isolated SQLite metadata/event repository; it never stores artifact bytes."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS medical_writing_artifact_lifecycle_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    generation_id TEXT NOT NULL,
                    identity_json TEXT NOT NULL,
                    artifact_relpath TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id),
                    UNIQUE (tenant_id, project_id, document_id, generation_id)
                );
                CREATE TABLE IF NOT EXISTS medical_writing_artifact_lifecycle_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('active', 'purge_requested', 'purged')),
                    policy_json TEXT NOT NULL,
                    current_pointer INTEGER NOT NULL CHECK (current_pointer IN (0, 1)),
                    version INTEGER NOT NULL CHECK (version >= 1),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, artifact_id),
                    FOREIGN KEY (tenant_id, project_id, artifact_id)
                    REFERENCES medical_writing_artifact_lifecycle_records(
                        tenant_id, project_id, artifact_id
                    )
                );
                CREATE TABLE IF NOT EXISTS medical_writing_artifact_lifecycle_pointers (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    pointer_revision INTEGER NOT NULL CHECK (pointer_revision >= 1),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, document_id),
                    FOREIGN KEY (tenant_id, project_id, artifact_id)
                    REFERENCES medical_writing_artifact_lifecycle_records(
                        tenant_id, project_id, artifact_id
                    )
                );
                CREATE TABLE IF NOT EXISTS medical_writing_artifact_lifecycle_events (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    state_from TEXT NOT NULL,
                    state_to TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    principal_subject TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, event_id),
                    UNIQUE (tenant_id, project_id, idempotency_key),
                    FOREIGN KEY (tenant_id, project_id, artifact_id)
                    REFERENCES medical_writing_artifact_lifecycle_records(
                        tenant_id, project_id, artifact_id
                    )
                );
                CREATE TRIGGER IF NOT EXISTS trg_mw_artifact_lifecycle_records_no_update
                BEFORE UPDATE ON medical_writing_artifact_lifecycle_records BEGIN
                    SELECT RAISE(ABORT, 'medical-writing artifact identities are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_mw_artifact_lifecycle_records_no_delete
                BEFORE DELETE ON medical_writing_artifact_lifecycle_records BEGIN
                    SELECT RAISE(ABORT, 'medical-writing artifact identities are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_mw_artifact_lifecycle_events_no_update
                BEFORE UPDATE ON medical_writing_artifact_lifecycle_events BEGIN
                    SELECT RAISE(ABORT, 'medical-writing artifact lifecycle events are immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_mw_artifact_lifecycle_events_no_delete
                BEFORE DELETE ON medical_writing_artifact_lifecycle_events BEGIN
                    SELECT RAISE(ABORT, 'medical-writing artifact lifecycle events are immutable');
                END;
                """
            )

    @staticmethod
    def _require_key(idempotency_key: str) -> str:
        return _require_text(idempotency_key, field_name="idempotency_key")

    @staticmethod
    def _validate_principal(
        principal: MedicalWritingArtifactPrincipal,
        *,
        tenant_id: str,
        project_id: str,
    ) -> None:
        if not isinstance(principal, MedicalWritingArtifactPrincipal):
            raise MedicalWritingArtifactLifecycleAuthorizationError(
                "a typed authenticated principal is required"
            )
        principal.validate_for(tenant_id=tenant_id, project_id=project_id)

    @staticmethod
    def _event_id() -> str:
        return "mwart_event_" + uuid4().hex

    @staticmethod
    def _state_result(
        *,
        artifact_id: str,
        state: str,
        allowed: bool,
        reason: str,
        pointer_revision: int = 0,
    ) -> Dict[str, Any]:
        return {
            "artifact_id": artifact_id,
            "state": state,
            "allowed": bool(allowed),
            "reason": reason,
            "pointer_revision": int(pointer_revision or 0),
        }

    @staticmethod
    def _existing_event(
        connection: sqlite3.Connection,
        *,
        tenant_id: str,
        project_id: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Optional[sqlite3.Row]:
        row = connection.execute(
            """
            SELECT * FROM medical_writing_artifact_lifecycle_events
            WHERE tenant_id = ? AND project_id = ? AND idempotency_key = ?
            """,
            (tenant_id, project_id, idempotency_key),
        ).fetchone()
        if row is not None and str(row["request_hash"]) != request_hash:
            raise MedicalWritingArtifactLifecycleConflict(
                "idempotency key reused with a different lifecycle payload"
            )
        return row

    @staticmethod
    def _row_record(
        connection: sqlite3.Connection,
        *,
        tenant_id: str,
        project_id: str,
        artifact_id: str,
    ) -> MedicalWritingArtifactRecord:
        row = connection.execute(
            """
            SELECT r.*, s.state, s.policy_json, s.current_pointer,
                   s.version, s.updated_at
            FROM medical_writing_artifact_lifecycle_records r
            JOIN medical_writing_artifact_lifecycle_state s
              ON s.tenant_id = r.tenant_id
             AND s.project_id = r.project_id
             AND s.artifact_id = r.artifact_id
            WHERE r.tenant_id = ? AND r.project_id = ? AND r.artifact_id = ?
            """,
            (tenant_id, project_id, artifact_id),
        ).fetchone()
        if row is None:
            raise MedicalWritingArtifactLifecycleNotFound(
                f"medical-writing artifact not found: {project_id}/{artifact_id}"
            )
        identity = MedicalWritingArtifactIdentity.from_dict(
            json.loads(str(row["identity_json"]))
        )
        policy = MedicalWritingArtifactRetentionPolicy.from_dict(
            json.loads(str(row["policy_json"]))
        )
        state = str(row["state"])
        if state not in _STATES:
            raise MedicalWritingArtifactLifecycleIntegrityError(
                "stored artifact lifecycle state is invalid"
            )
        return MedicalWritingArtifactRecord(
            artifact_id=str(row["artifact_id"]),
            identity=identity,
            artifact_relpath=str(row["artifact_relpath"]),
            policy=policy,
            state=state,
            current_pointer=bool(row["current_pointer"]),
            version=int(row["version"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    def _public_record(
        self,
        principal: MedicalWritingArtifactPrincipal,
        project_id: str,
        artifact_id: str,
    ) -> MedicalWritingArtifactRecord:
        self._validate_principal(
            principal,
            tenant_id=principal.tenant_id,
            project_id=project_id,
        )
        with self._connect() as connection:
            return self._row_record(
                connection,
                tenant_id=principal.tenant_id,
                project_id=project_id,
                artifact_id=artifact_id,
            )

    def register(
        self,
        *,
        principal: MedicalWritingArtifactPrincipal,
        identity: MedicalWritingArtifactIdentity,
        artifact_relpath: str,
        policy: MedicalWritingArtifactRetentionPolicy,
        idempotency_key: str,
        make_current: bool = False,
        now: datetime | str | None = None,
    ) -> MedicalWritingArtifactLifecycleResult:
        identity_payload = identity.as_dict()
        tenant_id = identity_payload["tenant_id"]
        project_id = identity_payload["project_id"]
        self._validate_principal(
            principal, tenant_id=tenant_id, project_id=project_id
        )
        relpath = _safe_relative_path(artifact_relpath)
        policy_payload = policy.as_dict()
        key = self._require_key(idempotency_key)
        timestamp = _iso_datetime(now or _utc_now(), field_name="now")
        artifact_id = identity.artifact_id
        request_payload = {
            "action": "register",
            "identity": identity_payload,
            "artifact_relpath": relpath,
            "policy": policy_payload,
            "make_current": bool(make_current),
            "principal": principal.as_dict(),
        }
        request_hash = _payload_hash(request_payload)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_event = self._existing_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                idempotency_key=key,
                request_hash=request_hash,
            )
            if existing_event is not None:
                connection.rollback()
                record = self._public_record(principal, project_id, artifact_id)
                result = json.loads(str(existing_event["result_json"]))
                return MedicalWritingArtifactLifecycleResult(
                    record=record,
                    event_id=str(existing_event["event_id"]),
                    action=str(existing_event["action"]),
                    allowed=bool(result["allowed"]),
                    reason=str(result["reason"]),
                    replayed=True,
                    pointer_revision=int(result.get("pointer_revision") or 0),
                )

            existing = connection.execute(
                """
                SELECT * FROM medical_writing_artifact_lifecycle_records
                WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                """,
                (tenant_id, project_id, artifact_id),
            ).fetchone()
            if existing is not None:
                raise MedicalWritingArtifactLifecycleConflict(
                    "artifact identity already exists; use a new idempotency key only for a new generation"
                )
            pointer = connection.execute(
                """
                SELECT artifact_id, pointer_revision
                FROM medical_writing_artifact_lifecycle_pointers
                WHERE tenant_id = ? AND project_id = ? AND document_id = ?
                """,
                (tenant_id, project_id, identity_payload["document_id"]),
            ).fetchone()
            if make_current and pointer is not None:
                raise MedicalWritingArtifactLifecycleConflict(
                    "a current generation already exists; use rollback_to for a pointer transition"
                )

            connection.execute(
                """
                INSERT INTO medical_writing_artifact_lifecycle_records(
                    tenant_id, project_id, artifact_id, document_id,
                    generation_id, identity_json, artifact_relpath, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    project_id,
                    artifact_id,
                    identity_payload["document_id"],
                    identity_payload["generation_id"],
                    _canonical_json(identity_payload),
                    relpath,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO medical_writing_artifact_lifecycle_state(
                    tenant_id, project_id, artifact_id, state, policy_json,
                    current_pointer, version, updated_at
                ) VALUES (?, ?, ?, 'active', ?, ?, 1, ?)
                """,
                (
                    tenant_id,
                    project_id,
                    artifact_id,
                    _canonical_json(policy_payload),
                    1 if make_current else 0,
                    timestamp,
                ),
            )
            pointer_revision = 0
            if make_current:
                pointer_revision = 1
                connection.execute(
                    """
                    INSERT INTO medical_writing_artifact_lifecycle_pointers(
                        tenant_id, project_id, document_id, artifact_id,
                        pointer_revision, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        project_id,
                        identity_payload["document_id"],
                        artifact_id,
                        pointer_revision,
                        timestamp,
                    ),
                )
            result_payload = self._state_result(
                artifact_id=artifact_id,
                state="active",
                allowed=True,
                reason="registered",
                pointer_revision=pointer_revision,
            )
            event_id = self._insert_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                artifact_id=artifact_id,
                action="registered",
                state_from="",
                state_to="active",
                idempotency_key=key,
                request_hash=request_hash,
                principal=principal,
                created_at=timestamp,
                detail={"make_current": bool(make_current)},
                result=result_payload,
            )
            connection.commit()
            record = self._public_record(principal, project_id, artifact_id)
            return MedicalWritingArtifactLifecycleResult(
                record=record,
                event_id=event_id,
                action="registered",
                allowed=True,
                reason="registered",
                pointer_revision=pointer_revision,
            )
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise MedicalWritingArtifactLifecycleConflict(
                f"artifact lifecycle persistence conflict: {exc}"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(
        self,
        *,
        principal: MedicalWritingArtifactPrincipal,
        project_id: str,
        artifact_id: str,
    ) -> MedicalWritingArtifactRecord:
        return self._public_record(principal, project_id, artifact_id)

    def request_purge(
        self,
        *,
        principal: MedicalWritingArtifactPrincipal,
        project_id: str,
        artifact_id: str,
        idempotency_key: str,
        now: datetime | str | None = None,
    ) -> MedicalWritingArtifactLifecycleResult:
        key = self._require_key(idempotency_key)
        timestamp = _iso_datetime(now or _utc_now(), field_name="now")
        tenant_id = _require_text(principal.tenant_id, field_name="principal.tenant_id")
        self._validate_principal(principal, tenant_id=tenant_id, project_id=project_id)
        request_hash = _payload_hash(
            {
                "action": "request_purge",
                "project_id": project_id,
                "artifact_id": artifact_id,
                "principal": principal.as_dict(),
            }
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_event = self._existing_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                idempotency_key=key,
                request_hash=request_hash,
            )
            if existing_event is not None:
                connection.rollback()
                record = self._public_record(principal, project_id, artifact_id)
                result = json.loads(str(existing_event["result_json"]))
                return MedicalWritingArtifactLifecycleResult(
                    record=record,
                    event_id=str(existing_event["event_id"]),
                    action=str(existing_event["action"]),
                    allowed=bool(result["allowed"]),
                    reason=str(result["reason"]),
                    replayed=True,
                    pointer_revision=int(result.get("pointer_revision") or 0),
                )
            record = self._row_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                artifact_id=artifact_id,
            )
            policy_payload = record.policy.as_dict()
            now_dt = _parse_datetime(timestamp, field_name="now")
            reason = "purge_requested"
            allowed = True
            target_state = "purge_requested"
            action = "purge_requested"
            if record.state == "purged":
                allowed = False
                reason = "already_purged"
                target_state = record.state
                action = "purge_blocked"
            elif bool(policy_payload["legal_hold"]):
                allowed = False
                reason = "legal_hold_active"
                target_state = record.state
                action = "purge_blocked"
            elif record.current_pointer:
                allowed = False
                reason = "current_pointer_cannot_be_purged"
                target_state = record.state
                action = "purge_blocked"
            else:
                minimum = _parse_datetime(
                    policy_payload["minimum_retain_until"],
                    field_name="minimum_retain_until",
                )
                eligible = _parse_datetime(
                    policy_payload["purge_eligible_at"],
                    field_name="purge_eligible_at",
                )
                if now_dt < max(minimum, eligible):
                    allowed = False
                    reason = "retention_window_not_reached"
                    target_state = record.state
                    action = "purge_blocked"
                else:
                    connection.execute(
                        """
                        UPDATE medical_writing_artifact_lifecycle_state
                        SET state = 'purge_requested', version = version + 1,
                            updated_at = ?
                        WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                        """,
                        (timestamp, tenant_id, project_id, artifact_id),
                    )
            result_payload = self._state_result(
                artifact_id=artifact_id,
                state=target_state,
                allowed=allowed,
                reason=reason,
                pointer_revision=0,
            )
            event_id = self._insert_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                artifact_id=artifact_id,
                action=action,
                state_from=record.state,
                state_to=target_state,
                idempotency_key=key,
                request_hash=request_hash,
                principal=principal,
                created_at=timestamp,
                detail={"policy_id": policy_payload["policy_id"]},
                result=result_payload,
            )
            connection.commit()
            updated = self._public_record(principal, project_id, artifact_id)
            return MedicalWritingArtifactLifecycleResult(
                record=updated,
                event_id=event_id,
                action=action,
                allowed=allowed,
                reason=reason,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def commit_purge(
        self,
        *,
        principal: MedicalWritingArtifactPrincipal,
        project_id: str,
        artifact_id: str,
        deletion_proof_sha256: str,
        idempotency_key: str,
        now: datetime | str | None = None,
    ) -> MedicalWritingArtifactLifecycleResult:
        proof = _require_sha256(
            deletion_proof_sha256, field_name="deletion_proof_sha256"
        )
        key = self._require_key(idempotency_key)
        timestamp = _iso_datetime(now or _utc_now(), field_name="now")
        tenant_id = _require_text(principal.tenant_id, field_name="principal.tenant_id")
        self._validate_principal(principal, tenant_id=tenant_id, project_id=project_id)
        request_hash = _payload_hash(
            {
                "action": "commit_purge",
                "project_id": project_id,
                "artifact_id": artifact_id,
                "deletion_proof_sha256": proof,
                "principal": principal.as_dict(),
            }
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_event = self._existing_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                idempotency_key=key,
                request_hash=request_hash,
            )
            if existing_event is not None:
                connection.rollback()
                record = self._public_record(principal, project_id, artifact_id)
                result = json.loads(str(existing_event["result_json"]))
                return MedicalWritingArtifactLifecycleResult(
                    record=record,
                    event_id=str(existing_event["event_id"]),
                    action=str(existing_event["action"]),
                    allowed=bool(result["allowed"]),
                    reason=str(result["reason"]),
                    replayed=True,
                    pointer_revision=int(result.get("pointer_revision") or 0),
                )
            record = self._row_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                artifact_id=artifact_id,
            )
            if record.state == "purged":
                allowed = False
                reason = "already_purged"
                action = "purge_commit_replay"
                target_state = record.state
            elif record.state != "purge_requested":
                raise MedicalWritingArtifactLifecycleConflict(
                    "artifact must be purge_requested before deletion proof can be committed"
                )
            elif record.current_pointer:
                raise MedicalWritingArtifactLifecycleConflict(
                    "current artifact pointer cannot be purged"
                )
            else:
                allowed = True
                reason = "purged_with_deletion_proof"
                action = "purge_committed"
                target_state = "purged"
                connection.execute(
                    """
                    UPDATE medical_writing_artifact_lifecycle_state
                    SET state = 'purged', version = version + 1, updated_at = ?
                    WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                    """,
                    (timestamp, tenant_id, project_id, artifact_id),
                )
            result_payload = self._state_result(
                artifact_id=artifact_id,
                state=target_state,
                allowed=allowed,
                reason=reason,
            )
            event_id = self._insert_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                artifact_id=artifact_id,
                action=action,
                state_from=record.state,
                state_to=target_state,
                idempotency_key=key,
                request_hash=request_hash,
                principal=principal,
                created_at=timestamp,
                detail={"deletion_proof_sha256": proof},
                result=result_payload,
            )
            connection.commit()
            updated = self._public_record(principal, project_id, artifact_id)
            return MedicalWritingArtifactLifecycleResult(
                record=updated,
                event_id=event_id,
                action=action,
                allowed=allowed,
                reason=reason,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def rollback_to(
        self,
        *,
        principal: MedicalWritingArtifactPrincipal,
        project_id: str,
        document_id: str,
        target_artifact_id: str,
        expected_pointer_revision: int,
        reason: str,
        idempotency_key: str,
        now: datetime | str | None = None,
        expected_current_artifact_id: str | None = None,
        expected_current_identity_sha256: str | None = None,
        request_context: Dict[str, Any] | None = None,
    ) -> MedicalWritingArtifactLifecycleResult:
        reason = _require_text(reason, field_name="rollback_reason")
        key = self._require_key(idempotency_key)
        try:
            expected_revision = int(expected_pointer_revision)
        except (TypeError, ValueError) as exc:
            raise MedicalWritingArtifactLifecycleStale(
                "expected_pointer_revision must be an integer"
            ) from exc
        if expected_revision < 1:
            raise MedicalWritingArtifactLifecycleStale(
                "expected_pointer_revision must be >= 1"
            )
        timestamp = _iso_datetime(now or _utc_now(), field_name="now")
        tenant_id = _require_text(principal.tenant_id, field_name="principal.tenant_id")
        self._validate_principal(principal, tenant_id=tenant_id, project_id=project_id)
        request_hash = _payload_hash(
            {
                "action": "rollback_to",
                "project_id": project_id,
                "document_id": document_id,
                "target_artifact_id": target_artifact_id,
                "expected_pointer_revision": expected_revision,
                "expected_current_artifact_id": str(
                    expected_current_artifact_id or ""
                ),
                "expected_current_identity_sha256": str(
                    expected_current_identity_sha256 or ""
                ).lower(),
                "reason": reason,
                "request_context": request_context or {},
                "principal": principal.as_dict(),
            }
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_event = self._existing_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                idempotency_key=key,
                request_hash=request_hash,
            )
            if existing_event is not None:
                connection.rollback()
                record = self._public_record(
                    principal, project_id, target_artifact_id
                )
                result = json.loads(str(existing_event["result_json"]))
                return MedicalWritingArtifactLifecycleResult(
                    record=record,
                    event_id=str(existing_event["event_id"]),
                    action=str(existing_event["action"]),
                    allowed=bool(result["allowed"]),
                    reason=str(result["reason"]),
                    replayed=True,
                    pointer_revision=int(result.get("pointer_revision") or 0),
                )
            target = self._row_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                artifact_id=target_artifact_id,
            )
            if target.identity.document_id != document_id:
                raise MedicalWritingArtifactLifecycleConflict(
                    "rollback target does not belong to the requested document"
                )
            if target.state != "active":
                raise MedicalWritingArtifactLifecycleConflict(
                    "rollback target must be active"
                )
            pointer = connection.execute(
                """
                SELECT artifact_id, pointer_revision
                FROM medical_writing_artifact_lifecycle_pointers
                WHERE tenant_id = ? AND project_id = ? AND document_id = ?
                """,
                (tenant_id, project_id, document_id),
            ).fetchone()
            if pointer is None:
                raise MedicalWritingArtifactLifecycleNotFound(
                    "current document generation pointer is missing"
                )
            actual_revision = int(pointer["pointer_revision"])
            if actual_revision != expected_revision:
                raise MedicalWritingArtifactLifecycleStale(
                    "current document generation pointer is stale"
                )
            previous_artifact_id = str(pointer["artifact_id"])
            if expected_current_artifact_id and (
                previous_artifact_id != expected_current_artifact_id
            ):
                raise MedicalWritingArtifactLifecycleStale(
                    "current document generation artifact is stale"
                )
            if expected_current_identity_sha256:
                previous_record = self._row_record(
                    connection,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    artifact_id=previous_artifact_id,
                )
                previous_identity_sha256 = _payload_hash(
                    previous_record.identity.as_dict()
                )
                if previous_identity_sha256 != expected_current_identity_sha256:
                    raise MedicalWritingArtifactLifecycleStale(
                        "current document generation identity is stale"
                    )
            if previous_artifact_id == target_artifact_id:
                allowed = False
                action = "rollback_noop"
                transition_reason = "target_is_current"
                next_revision = actual_revision
            else:
                allowed = True
                action = "rollback_succeeded"
                transition_reason = "rollback_pointer_moved"
                next_revision = actual_revision + 1
                connection.execute(
                    """
                    UPDATE medical_writing_artifact_lifecycle_state
                    SET current_pointer = 0, version = version + 1, updated_at = ?
                    WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                    """,
                    (timestamp, tenant_id, project_id, previous_artifact_id),
                )
                connection.execute(
                    """
                    UPDATE medical_writing_artifact_lifecycle_state
                    SET current_pointer = 1, version = version + 1, updated_at = ?
                    WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                    """,
                    (timestamp, tenant_id, project_id, target_artifact_id),
                )
                connection.execute(
                    """
                    UPDATE medical_writing_artifact_lifecycle_pointers
                    SET artifact_id = ?, pointer_revision = ?, updated_at = ?
                    WHERE tenant_id = ? AND project_id = ? AND document_id = ?
                    """,
                    (
                        target_artifact_id,
                        next_revision,
                        timestamp,
                        tenant_id,
                        project_id,
                        document_id,
                    ),
                )
            result_payload = self._state_result(
                artifact_id=target_artifact_id,
                state=target.state,
                allowed=allowed,
                reason=transition_reason,
                pointer_revision=next_revision,
            )
            event_id = self._insert_event(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                artifact_id=target_artifact_id,
                action=action,
                state_from=f"pointer:{previous_artifact_id}",
                state_to=f"pointer:{target_artifact_id}",
                idempotency_key=key,
                request_hash=request_hash,
                principal=principal,
                created_at=timestamp,
                detail={
                    "document_id": document_id,
                    "previous_artifact_id": previous_artifact_id,
                    "reason": reason,
                },
                result=result_payload,
            )
            connection.commit()
            updated = self._public_record(principal, project_id, target_artifact_id)
            return MedicalWritingArtifactLifecycleResult(
                record=updated,
                event_id=event_id,
                action=action,
                allowed=allowed,
                reason=transition_reason,
                pointer_revision=next_revision,
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def current_pointer(
        self,
        *,
        principal: MedicalWritingArtifactPrincipal,
        project_id: str,
        document_id: str,
    ) -> Optional[MedicalWritingArtifactRecord]:
        tenant_id = _require_text(principal.tenant_id, field_name="principal.tenant_id")
        self._validate_principal(principal, tenant_id=tenant_id, project_id=project_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT artifact_id FROM medical_writing_artifact_lifecycle_pointers
                WHERE tenant_id = ? AND project_id = ? AND document_id = ?
                """,
                (tenant_id, project_id, document_id),
            ).fetchone()
            if row is None:
                return None
            return self._row_record(
                connection,
                tenant_id=tenant_id,
                project_id=project_id,
                artifact_id=str(row["artifact_id"]),
            )

    def events(
        self,
        *,
        principal: MedicalWritingArtifactPrincipal,
        project_id: str,
        artifact_id: str,
    ) -> List[Dict[str, Any]]:
        tenant_id = _require_text(principal.tenant_id, field_name="principal.tenant_id")
        self._validate_principal(principal, tenant_id=tenant_id, project_id=project_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, artifact_id, action, state_from, state_to,
                       idempotency_key, request_hash, principal_subject,
                       created_at, detail_json, result_json
                FROM medical_writing_artifact_lifecycle_events
                WHERE tenant_id = ? AND project_id = ? AND artifact_id = ?
                ORDER BY created_at, rowid
                """,
                (tenant_id, project_id, artifact_id),
            ).fetchall()
        return [
            {
                "event_id": str(row["event_id"]),
                "artifact_id": str(row["artifact_id"]),
                "action": str(row["action"]),
                "state_from": str(row["state_from"]),
                "state_to": str(row["state_to"]),
                "idempotency_key": str(row["idempotency_key"]),
                "request_hash": str(row["request_hash"]),
                "principal_subject": str(row["principal_subject"]),
                "created_at": str(row["created_at"]),
                "detail": json.loads(str(row["detail_json"])),
                "result": json.loads(str(row["result_json"])),
            }
            for row in rows
        ]

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        tenant_id: str,
        project_id: str,
        artifact_id: str,
        action: str,
        state_from: str,
        state_to: str,
        idempotency_key: str,
        request_hash: str,
        principal: MedicalWritingArtifactPrincipal,
        created_at: str,
        detail: Dict[str, Any],
        result: Dict[str, Any],
    ) -> str:
        event_id = MedicalWritingArtifactLifecycleRepository._event_id()
        connection.execute(
            """
            INSERT INTO medical_writing_artifact_lifecycle_events(
                tenant_id, project_id, event_id, artifact_id, action,
                state_from, state_to, idempotency_key, request_hash,
                principal_subject, created_at, detail_json, result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                project_id,
                event_id,
                artifact_id,
                action,
                state_from,
                state_to,
                idempotency_key,
                request_hash,
                principal.subject_id,
                created_at,
                _canonical_json(detail),
                _canonical_json(result),
            ),
        )
        return event_id
