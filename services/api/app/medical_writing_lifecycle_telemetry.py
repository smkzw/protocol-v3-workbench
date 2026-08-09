"""Secret-free lifecycle telemetry substrate for medical-writing artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .medical_writing_artifact_lifecycle import MedicalWritingArtifactIdentity


MEDICAL_WRITING_LIFECYCLE_TELEMETRY_SCHEMA = "medical_writing_lifecycle_telemetry_v1"
_EVENT_TYPES = frozenset(
    {
        "created",
        "started",
        "completed",
        "failed",
        "read_ok",
        "read_denied",
        "integrity_mismatch",
        "manifest_missing",
        "recovery",
        "retention_hold",
        "purge_requested",
        "purge_succeeded",
        "purge_failed",
        "rollback_requested",
        "rollback_succeeded",
        "rollback_failed",
        "signature_denied",
        "signature_verified",
    }
)
_ERROR_EVENTS = frozenset(
    {
        "failed",
        "read_denied",
        "integrity_mismatch",
        "manifest_missing",
        "purge_failed",
        "rollback_failed",
        "signature_denied",
    }
)
_SENSITIVE_KEY_TOKENS = frozenset(
    {
        "bytes",
        "content",
        "credential",
        "password",
        "secret",
        "token",
        "cookie",
        "bearer",
        "private_key",
        "raw_text",
        "document_text",
    }
)


class MedicalWritingLifecycleTelemetryError(ValueError):
    """Base telemetry validation error."""


class MedicalWritingLifecycleTelemetryConflict(
    MedicalWritingLifecycleTelemetryError
):
    """Raised when an idempotency key or event identity conflicts."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MedicalWritingLifecycleTelemetryError(f"{field_name} is required")
    return text


def _iso_datetime(value: Any, *, field_name: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _require_text(value, field_name=field_name)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MedicalWritingLifecycleTelemetryError(
                f"{field_name} must be an ISO-8601 timestamp"
            ) from exc
    if parsed.tzinfo is None:
        raise MedicalWritingLifecycleTelemetryError(
            f"{field_name} must include a timezone"
        )
    return parsed.astimezone(timezone.utc).isoformat()


def _safe_detail(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise MedicalWritingLifecycleTelemetryError("detail must be an object")

    def walk(item: Any, *, depth: int) -> Any:
        if depth > 5:
            raise MedicalWritingLifecycleTelemetryError("detail nesting is too deep")
        if isinstance(item, dict):
            result: Dict[str, Any] = {}
            for raw_key, raw_value in item.items():
                key = _require_text(raw_key, field_name="detail key")
                lowered = key.lower()
                if any(token in lowered for token in _SENSITIVE_KEY_TOKENS):
                    raise MedicalWritingLifecycleTelemetryError(
                        f"detail key is not telemetry-safe: {key}"
                    )
                result[key] = walk(raw_value, depth=depth + 1)
            return result
        if isinstance(item, (list, tuple)):
            return [walk(value, depth=depth + 1) for value in item]
        if isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, str) and len(item) > 4096:
                raise MedicalWritingLifecycleTelemetryError(
                    "detail string exceeds the bounded telemetry length"
                )
            return item
        raise MedicalWritingLifecycleTelemetryError(
            f"detail contains unsupported value type: {type(item).__name__}"
        )

    result = walk(value, depth=0)
    if len(_canonical_json(result).encode("utf-8")) > 16_384:
        raise MedicalWritingLifecycleTelemetryError(
            "detail exceeds the bounded telemetry size"
        )
    return result


@dataclass(frozen=True)
class MedicalWritingLifecycleTelemetryEvent:
    event_id: str
    event_type: str
    occurred_at: str
    identity: MedicalWritingArtifactIdentity
    policy_id: str
    policy_revision: int
    request_id: str
    trace_id: str
    principal_subject: str = ""
    principal_assurance: str = ""
    error_code: str = ""
    detail: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        event_id = _require_text(self.event_id, field_name="event_id")
        event_type = _require_text(self.event_type, field_name="event_type")
        if event_type not in _EVENT_TYPES:
            raise MedicalWritingLifecycleTelemetryError(
                f"unsupported lifecycle event type: {event_type}"
            )
        occurred_at = _iso_datetime(self.occurred_at, field_name="occurred_at")
        identity = self.identity.as_dict()
        policy_id = _require_text(self.policy_id, field_name="policy_id")
        try:
            policy_revision = int(self.policy_revision)
        except (TypeError, ValueError) as exc:
            raise MedicalWritingLifecycleTelemetryError(
                "policy_revision must be an integer"
            ) from exc
        if policy_revision < 1:
            raise MedicalWritingLifecycleTelemetryError(
                "policy_revision must be >= 1"
            )
        request_id = _require_text(self.request_id, field_name="request_id")
        trace_id = _require_text(self.trace_id, field_name="trace_id")
        subject = str(self.principal_subject or "").strip()
        assurance = str(self.principal_assurance or "").strip()
        if bool(subject) != bool(assurance):
            raise MedicalWritingLifecycleTelemetryError(
                "principal_subject and principal_assurance must be supplied together"
            )
        error_code = str(self.error_code or "").strip()
        if event_type in _ERROR_EVENTS and not error_code:
            raise MedicalWritingLifecycleTelemetryError(
                f"{event_type} requires error_code"
            )
        detail = _safe_detail(self.detail)
        payload = {
            "schema_version": MEDICAL_WRITING_LIFECYCLE_TELEMETRY_SCHEMA,
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "identity": identity,
            "policy_id": policy_id,
            "policy_revision": policy_revision,
            "request_id": request_id,
            "trace_id": trace_id,
            "principal_subject": subject,
            "principal_assurance": assurance,
            "error_code": error_code,
            "detail": detail,
        }
        payload["event_hash"] = _sha256(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "MedicalWritingLifecycleTelemetryEvent":
        if not isinstance(payload, dict):
            raise MedicalWritingLifecycleTelemetryError("telemetry payload must be an object")
        expected_keys = {
            "schema_version",
            "event_id",
            "event_type",
            "occurred_at",
            "identity",
            "policy_id",
            "policy_revision",
            "request_id",
            "trace_id",
            "principal_subject",
            "principal_assurance",
            "error_code",
            "detail",
            "event_hash",
        }
        if set(payload) != expected_keys:
            raise MedicalWritingLifecycleTelemetryError(
                "telemetry payload contains unexpected or missing fields"
            )
        if payload.get("schema_version") != MEDICAL_WRITING_LIFECYCLE_TELEMETRY_SCHEMA:
            raise MedicalWritingLifecycleTelemetryError(
                "unsupported lifecycle telemetry schema version"
            )
        identity_payload = payload.get("identity")
        if not isinstance(identity_payload, dict):
            raise MedicalWritingLifecycleTelemetryError("telemetry identity must be an object")
        detail = payload.get("detail")
        if not isinstance(detail, dict):
            raise MedicalWritingLifecycleTelemetryError("telemetry detail must be an object")
        try:
            policy_revision = int(payload.get("policy_revision"))
        except (TypeError, ValueError) as exc:
            raise MedicalWritingLifecycleTelemetryError(
                "policy_revision must be an integer"
            ) from exc
        persisted_hash = str(payload.get("event_hash") or "").strip()
        if not persisted_hash:
            raise MedicalWritingLifecycleTelemetryError("persisted telemetry event_hash is required")
        event = cls(
            event_id=str(payload.get("event_id") or ""),
            event_type=str(payload.get("event_type") or ""),
            occurred_at=str(payload.get("occurred_at") or ""),
            identity=MedicalWritingArtifactIdentity.from_dict(
                identity_payload
            ),
            policy_id=str(payload.get("policy_id") or ""),
            policy_revision=policy_revision,
            request_id=str(payload.get("request_id") or ""),
            trace_id=str(payload.get("trace_id") or ""),
            principal_subject=str(payload.get("principal_subject") or ""),
            principal_assurance=str(payload.get("principal_assurance") or ""),
            error_code=str(payload.get("error_code") or ""),
            detail=detail,
        )
        normalized = event.as_dict()
        if persisted_hash != normalized["event_hash"]:
            raise MedicalWritingLifecycleTelemetryError(
                "persisted telemetry event hash mismatch"
            )
        return event


@dataclass(frozen=True)
class MedicalWritingLifecycleTelemetryAppendResult:
    event: MedicalWritingLifecycleTelemetryEvent
    event_hash: str
    idempotency_key: str
    replayed: bool


class MedicalWritingLifecycleTelemetryRepository:
    """Isolated append-only event store; no alerting or threshold semantics."""

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
                CREATE TABLE IF NOT EXISTS medical_writing_lifecycle_telemetry_events (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, event_id),
                    UNIQUE (tenant_id, project_id, idempotency_key)
                );
                CREATE TRIGGER IF NOT EXISTS trg_mw_lifecycle_telemetry_no_update
                BEFORE UPDATE ON medical_writing_lifecycle_telemetry_events BEGIN
                    SELECT RAISE(ABORT, 'medical-writing lifecycle telemetry is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_mw_lifecycle_telemetry_no_delete
                BEFORE DELETE ON medical_writing_lifecycle_telemetry_events BEGIN
                    SELECT RAISE(ABORT, 'medical-writing lifecycle telemetry is immutable');
                END;
                """
            )

    @staticmethod
    def _require_key(value: Any) -> str:
        return _require_text(value, field_name="idempotency_key")

    def append(
        self,
        event: MedicalWritingLifecycleTelemetryEvent,
        *,
        idempotency_key: str,
    ) -> MedicalWritingLifecycleTelemetryAppendResult:
        payload = event.as_dict()
        key = self._require_key(idempotency_key)
        tenant_id = payload["identity"]["tenant_id"]
        project_id = payload["identity"]["project_id"]
        event_hash = payload["event_hash"]
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT * FROM medical_writing_lifecycle_telemetry_events
                WHERE tenant_id = ? AND project_id = ? AND idempotency_key = ?
                """,
                (tenant_id, project_id, key),
            ).fetchone()
            if existing is not None:
                if str(existing["event_hash"]) != event_hash:
                    raise MedicalWritingLifecycleTelemetryConflict(
                        "idempotency key reused with a different telemetry event"
                    )
                connection.rollback()
                replay_event = MedicalWritingLifecycleTelemetryEvent.from_dict(
                    json.loads(str(existing["payload_json"]))
                )
                return MedicalWritingLifecycleTelemetryAppendResult(
                    event=replay_event,
                    event_hash=event_hash,
                    idempotency_key=key,
                    replayed=True,
                )
            connection.execute(
                """
                INSERT INTO medical_writing_lifecycle_telemetry_events(
                    tenant_id, project_id, event_id, event_type,
                    idempotency_key, event_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    project_id,
                    payload["event_id"],
                    payload["event_type"],
                    key,
                    event_hash,
                    _canonical_json(payload),
                    payload["occurred_at"],
                ),
            )
            connection.commit()
            return MedicalWritingLifecycleTelemetryAppendResult(
                event=event,
                event_hash=event_hash,
                idempotency_key=key,
                replayed=False,
            )
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise MedicalWritingLifecycleTelemetryConflict(
                f"telemetry persistence conflict: {exc}"
            ) from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def events(
        self,
        *,
        tenant_id: str,
        project_id: str,
    ) -> List[MedicalWritingLifecycleTelemetryEvent]:
        tenant = _require_text(tenant_id, field_name="tenant_id")
        project = _require_text(project_id, field_name="project_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_lifecycle_telemetry_events
                WHERE tenant_id = ? AND project_id = ?
                ORDER BY created_at, rowid
                """,
                (tenant, project),
            ).fetchall()
        return [
            MedicalWritingLifecycleTelemetryEvent.from_dict(
                json.loads(str(row["payload_json"]))
            )
            for row in rows
        ]

    def event_count(self, *, tenant_id: str, project_id: str) -> int:
        return len(self.events(tenant_id=tenant_id, project_id=project_id))
