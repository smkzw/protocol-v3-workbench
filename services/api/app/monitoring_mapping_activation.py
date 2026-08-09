from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable, Mapping, Optional, Sequence

from .monitoring_ai_contracts import canonical_json, content_sha256
from .monitoring_mapping_draft_repository import (
    MonitoringMappingDraftRepository,
    MonitoringMappingDraftStatus,
    MonitoringMappingRevision,
)
from .monitoring_mapping_semantic_quality import (
    CAPABILITY_MANIFEST_V1,
    MappingActivationDisposition,
    MappingCapabilityStateCode,
    SemanticQualityStatus,
    current_capability_manifest_sha256,
    evaluate_mapping_semantic_quality,
)


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{2,240}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAPPING_REVISION_RE = re.compile(r"^monmaprev_[0-9a-f]{28}$")


class MonitoringMappingActivationError(ValueError):
    pass


class MonitoringMappingActivationNotFoundError(MonitoringMappingActivationError):
    pass


class MonitoringMappingActivationConflictError(MonitoringMappingActivationError):
    pass


class MonitoringMappingActivationSourceError(MonitoringMappingActivationError):
    pass


class MonitoringMappingCapabilityUnavailableError(
    MonitoringMappingActivationError
):
    pass


class MonitoringMappingCompatibilityStatus(str, Enum):
    FULLY_COMPATIBLE = "fully_compatible"
    DIFFERENCE_REVIEW_REQUIRED = "difference_review_required"


class MonitoringMappingDifferenceKind(str, Enum):
    ADDED = "added"
    MISSING = "missing"
    SAME_NAME_CONFLICT = "same_name_conflict"


class MonitoringBatchMappingBindingStatus(str, Enum):
    REUSE_SUGGESTED = "reuse_suggested"
    DIFFERENCE_REVIEW_REQUIRED = "difference_review_required"


@dataclass(frozen=True)
class MonitoringMappingCapabilitySnapshot:
    capability_id: str
    state: str
    blocking_finding_group_ids: tuple[str, ...]
    limitation_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonitoringMappingActivationState:
    project_id: str
    mapping_revision: str
    mapping_content_sha256: str
    source_batch_id: str
    source_profile_sha256: str
    source_input_sha256: str
    project_version: int
    activated_by: str
    activation_reason: str
    activated_at: str
    semantic_quality_report_sha256: str = ""
    capability_manifest_sha256: str = ""
    activation_disposition: str = MappingActivationDisposition.REJECT.value
    effective_capabilities_sha256: str = ""
    effective_capabilities: tuple[str, ...] = ()
    capability_states: tuple[MonitoringMappingCapabilitySnapshot, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["effective_capabilities"] = list(self.effective_capabilities)
        payload["capability_states"] = [
            item.to_dict() for item in self.capability_states
        ]
        return payload


@dataclass(frozen=True)
class MonitoringMappingActivationResult:
    state: MonitoringMappingActivationState
    replayed: bool
    changed: bool

    def __post_init__(self) -> None:
        for name in ("replayed", "changed"):
            if not isinstance(getattr(self, name), bool):
                raise MonitoringMappingActivationError(
                    f"{name} must be a strict boolean"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "replayed": self.replayed,
            "changed": self.changed,
        }


@dataclass(frozen=True)
class MonitoringMappingFieldDifference:
    kind: MonitoringMappingDifferenceKind
    domain: str
    source_field: str
    baseline_domains: tuple[str, ...] = ()
    current_domains: tuple[str, ...] = ()
    baseline_inferred_type: str = ""
    current_inferred_type: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["kind"] = self.kind.value
        return payload


@dataclass(frozen=True)
class MonitoringMappingCompatibilityReport:
    project_id: str
    batch_id: str
    mapping_revision: str
    mapping_content_sha256: str
    profile_sha256: str
    status: MonitoringMappingCompatibilityStatus
    reuse_recommended: bool
    added: tuple[MonitoringMappingFieldDifference, ...]
    missing: tuple[MonitoringMappingFieldDifference, ...]
    same_name_conflicts: tuple[MonitoringMappingFieldDifference, ...]
    report_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.reuse_recommended, bool):
            raise MonitoringMappingActivationError(
                "reuse_recommended must be a strict boolean"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "batch_id": self.batch_id,
            "mapping_revision": self.mapping_revision,
            "mapping_content_sha256": self.mapping_content_sha256,
            "profile_sha256": self.profile_sha256,
            "status": self.status.value,
            "reuse_recommended": self.reuse_recommended,
            "added": [item.to_dict() for item in self.added],
            "missing": [item.to_dict() for item in self.missing],
            "same_name_conflicts": [
                item.to_dict() for item in self.same_name_conflicts
            ],
            "report_sha256": self.report_sha256,
        }


@dataclass(frozen=True)
class MonitoringBatchMappingBinding:
    project_id: str
    batch_id: str
    binding_version: int
    evaluated_mapping_revision: str
    mapping_content_sha256: str
    profile_sha256: str
    compatibility_report_sha256: str
    status: MonitoringBatchMappingBindingStatus
    created_by: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class MonitoringBatchMappingBindingResult:
    binding: MonitoringBatchMappingBinding
    report: MonitoringMappingCompatibilityReport
    replayed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.replayed, bool):
            raise MonitoringMappingActivationError(
                "replayed must be a strict boolean"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_dict(),
            "report": self.report.to_dict(),
            "replayed": self.replayed,
        }


@dataclass(frozen=True)
class _FieldSignature:
    domain: str
    source_field: str
    inferred_type: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.domain, self.source_field)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _require_identifier(value: str, label: str) -> str:
    cleaned = str(value).strip()
    if not _SAFE_ID_RE.fullmatch(cleaned):
        raise ValueError(f"{label} contains unsupported characters")
    return cleaned


def _require_hash(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _require_text(value: str, label: str, *, maximum: int) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if len(cleaned) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return cleaned


def _mapping_content_sha256(revision: MonitoringMappingRevision) -> str:
    return content_sha256(revision.model_dump(mode="json"))


class MonitoringMappingActivationService:
    """Activates immutable confirmed mappings and compares future batch schemas."""

    def __init__(
        self,
        mapping_repository: MonitoringMappingDraftRepository,
        *,
        state_path: Optional[Path] = None,
        clock: Callable[[], datetime] = _utc_now,
    ):
        self.mapping_repository = mapping_repository
        self.state_path = Path(state_path or mapping_repository.path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.state_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitoring_mapping_project_state (
                    project_id TEXT PRIMARY KEY,
                    mapping_revision TEXT NOT NULL,
                    mapping_content_sha256 TEXT NOT NULL,
                    source_batch_id TEXT NOT NULL,
                    source_profile_sha256 TEXT NOT NULL,
                    source_input_sha256 TEXT NOT NULL,
                    semantic_quality_report_sha256 TEXT NOT NULL,
                    capability_manifest_sha256 TEXT NOT NULL,
                    activation_disposition TEXT NOT NULL,
                    effective_capabilities_sha256 TEXT NOT NULL,
                    effective_capabilities_json TEXT NOT NULL,
                    capability_states_json TEXT NOT NULL,
                    project_version INTEGER NOT NULL,
                    activated_by TEXT NOT NULL,
                    activation_reason TEXT NOT NULL,
                    activated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS monitoring_mapping_activation_history (
                    project_id TEXT NOT NULL,
                    project_version INTEGER NOT NULL,
                    mapping_revision TEXT NOT NULL,
                    mapping_content_sha256 TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, project_version)
                );

                CREATE TABLE IF NOT EXISTS monitoring_mapping_activation_operations (
                    project_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, operation_id)
                );

                CREATE TABLE IF NOT EXISTS monitoring_mapping_batch_bindings (
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    binding_version INTEGER NOT NULL,
                    evaluated_mapping_revision TEXT NOT NULL,
                    mapping_content_sha256 TEXT NOT NULL,
                    profile_sha256 TEXT NOT NULL,
                    compatibility_report_sha256 TEXT NOT NULL,
                    compatibility_report_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, batch_id)
                );

                CREATE TABLE IF NOT EXISTS monitoring_mapping_batch_binding_history (
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    binding_version INTEGER NOT NULL,
                    binding_json TEXT NOT NULL,
                    compatibility_report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, batch_id, binding_version)
                );

                CREATE TABLE IF NOT EXISTS monitoring_mapping_binding_operations (
                    project_id TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, operation_id)
                );

                CREATE TRIGGER IF NOT EXISTS
                    trg_mapping_activation_history_no_update
                BEFORE UPDATE ON monitoring_mapping_activation_history
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'mapping activation history is immutable'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS
                    trg_mapping_activation_history_no_delete
                BEFORE DELETE ON monitoring_mapping_activation_history
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'mapping activation history deletion is forbidden'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS
                    trg_mapping_batch_binding_history_no_update
                BEFORE UPDATE ON monitoring_mapping_batch_binding_history
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'mapping batch binding history is immutable'
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS
                    trg_mapping_batch_binding_history_no_delete
                BEFORE DELETE ON monitoring_mapping_batch_binding_history
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'mapping batch binding history deletion is forbidden'
                    );
                END;
                """
            )
            state_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(monitoring_mapping_project_state)"
                ).fetchall()
            }
            state_migrations = {
                "semantic_quality_report_sha256": (
                    "TEXT NOT NULL DEFAULT ''"
                ),
                "capability_manifest_sha256": "TEXT NOT NULL DEFAULT ''",
                "activation_disposition": (
                    "TEXT NOT NULL DEFAULT 'reject'"
                ),
                "effective_capabilities_sha256": (
                    "TEXT NOT NULL DEFAULT ''"
                ),
                "effective_capabilities_json": (
                    "TEXT NOT NULL DEFAULT '[]'"
                ),
                "capability_states_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            for column, declaration in state_migrations.items():
                if column not in state_columns:
                    connection.execute(
                        "ALTER TABLE monitoring_mapping_project_state "
                        f"ADD COLUMN {column} {declaration}"
                    )
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise RuntimeError("mapping activation repository integrity check failed")

    def activate_confirmed_revision(
        self,
        project_id: str,
        mapping_revision: str,
        *,
        expected_project_version: int,
        activated_by: str,
        activation_reason: str,
        idempotency_key: str,
    ) -> MonitoringMappingActivationResult:
        project_id = _require_identifier(project_id, "project_id")
        mapping_revision = _require_identifier(
            mapping_revision,
            "mapping_revision",
        )
        idempotency_key = _require_identifier(
            idempotency_key,
            "idempotency_key",
        )
        activated_by = _require_text(activated_by, "activated_by", maximum=160)
        activation_reason = _require_text(
            activation_reason,
            "activation_reason",
            maximum=2_000,
        )
        if expected_project_version < 0:
            raise ValueError("expected_project_version cannot be negative")

        revision, _baseline = self._load_valid_confirmed_revision(
            project_id,
            mapping_revision,
            require_semantic_quality=True,
        )
        (
            activation_disposition,
            capability_manifest_sha256,
            effective_capabilities_sha256,
            effective_capabilities,
            capability_states,
        ) = self._capability_contract_from_revision(revision)
        mapping_hash = _mapping_content_sha256(revision)
        request_sha256 = content_sha256(
            {
                "project_id": project_id,
                "mapping_revision": mapping_revision,
                "mapping_content_sha256": mapping_hash,
                "semantic_quality_report_sha256": (
                    revision.semantic_quality_report_sha256
                ),
                "capability_manifest_sha256": capability_manifest_sha256,
                "activation_disposition": activation_disposition,
                "effective_capabilities_sha256": (
                    effective_capabilities_sha256
                ),
                "expected_project_version": expected_project_version,
                "activated_by": activated_by,
                "activation_reason": activation_reason,
            }
        )
        now = _iso(self.clock())

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT request_sha256, result_json
                FROM monitoring_mapping_activation_operations
                WHERE project_id = ? AND operation_id = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_sha256"] != request_sha256:
                    connection.rollback()
                    raise MonitoringMappingActivationConflictError(
                        "idempotency key was reused with another activation request"
                    )
                result = self._activation_result_from_json(replay["result_json"])
                connection.commit()
                return replace(result, replayed=True)

            current_row = connection.execute(
                """
                SELECT * FROM monitoring_mapping_project_state
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            current_version = (
                int(current_row["project_version"]) if current_row is not None else 0
            )
            if current_version != expected_project_version:
                connection.rollback()
                raise MonitoringMappingActivationConflictError(
                    "mapping activation lost project CAS"
                )

            changed = not (
                current_row is not None
                and current_row["mapping_revision"] == mapping_revision
                and current_row["mapping_content_sha256"] == mapping_hash
            )
            if changed:
                project_version = current_version + 1
                state = MonitoringMappingActivationState(
                    project_id=project_id,
                    mapping_revision=mapping_revision,
                    mapping_content_sha256=mapping_hash,
                    source_batch_id=revision.batch_id,
                    source_profile_sha256=revision.full_profile_sha256,
                    source_input_sha256=revision.full_input_sha256,
                    semantic_quality_report_sha256=(
                        revision.semantic_quality_report_sha256
                    ),
                    capability_manifest_sha256=capability_manifest_sha256,
                    activation_disposition=activation_disposition,
                    effective_capabilities_sha256=(
                        effective_capabilities_sha256
                    ),
                    effective_capabilities=effective_capabilities,
                    capability_states=capability_states,
                    project_version=project_version,
                    activated_by=activated_by,
                    activation_reason=activation_reason,
                    activated_at=now,
                )
                connection.execute(
                    """
                    INSERT INTO monitoring_mapping_project_state(
                        project_id, mapping_revision, mapping_content_sha256,
                        source_batch_id, source_profile_sha256,
                        source_input_sha256,
                        semantic_quality_report_sha256,
                        capability_manifest_sha256, activation_disposition,
                        effective_capabilities_sha256,
                        effective_capabilities_json, capability_states_json,
                        project_version, activated_by, activation_reason,
                        activated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        mapping_revision = excluded.mapping_revision,
                        mapping_content_sha256 = excluded.mapping_content_sha256,
                        source_batch_id = excluded.source_batch_id,
                        source_profile_sha256 = excluded.source_profile_sha256,
                        source_input_sha256 = excluded.source_input_sha256,
                        semantic_quality_report_sha256 =
                            excluded.semantic_quality_report_sha256,
                        capability_manifest_sha256 =
                            excluded.capability_manifest_sha256,
                        activation_disposition =
                            excluded.activation_disposition,
                        effective_capabilities_sha256 =
                            excluded.effective_capabilities_sha256,
                        effective_capabilities_json =
                            excluded.effective_capabilities_json,
                        capability_states_json =
                            excluded.capability_states_json,
                        project_version = excluded.project_version,
                        activated_by = excluded.activated_by,
                        activation_reason = excluded.activation_reason,
                        activated_at = excluded.activated_at
                    """,
                    (
                        state.project_id,
                        state.mapping_revision,
                        state.mapping_content_sha256,
                        state.source_batch_id,
                        state.source_profile_sha256,
                        state.source_input_sha256,
                        state.semantic_quality_report_sha256,
                        state.capability_manifest_sha256,
                        state.activation_disposition,
                        state.effective_capabilities_sha256,
                        canonical_json(list(state.effective_capabilities)),
                        canonical_json(
                            [
                                item.to_dict()
                                for item in state.capability_states
                            ]
                        ),
                        state.project_version,
                        state.activated_by,
                        state.activation_reason,
                        state.activated_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO monitoring_mapping_activation_history(
                        project_id, project_version, mapping_revision,
                        mapping_content_sha256, state_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        project_version,
                        mapping_revision,
                        mapping_hash,
                        canonical_json(state.to_dict()),
                        now,
                    ),
                )
            else:
                state = self._state_from_row(current_row)

            result = MonitoringMappingActivationResult(
                state=state,
                replayed=False,
                changed=changed,
            )
            connection.execute(
                """
                INSERT INTO monitoring_mapping_activation_operations(
                    project_id, operation_id, request_sha256,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    idempotency_key,
                    request_sha256,
                    canonical_json(result.to_dict()),
                    now,
                ),
            )
            connection.commit()
        return result

    def get_active_mapping(
        self,
        project_id: str,
        *,
        validate_source: bool = True,
    ) -> MonitoringMappingActivationState:
        project_id = _require_identifier(project_id, "project_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_mapping_project_state
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
        if row is None:
            raise MonitoringMappingActivationNotFoundError(
                "project has no active confirmed mapping"
            )
        state = self._state_from_row(row)
        if validate_source:
            revision, _baseline = self._load_valid_confirmed_revision(
                project_id,
                state.mapping_revision,
            )
            if _mapping_content_sha256(revision) != state.mapping_content_sha256:
                raise MonitoringMappingActivationSourceError(
                    "active mapping content no longer matches immutable source"
                )
            expected_contract = self._capability_contract_from_revision(revision)
            actual_contract = (
                state.activation_disposition,
                state.capability_manifest_sha256,
                state.effective_capabilities_sha256,
                state.effective_capabilities,
                state.capability_states,
            )
            if actual_contract != expected_contract:
                raise MonitoringMappingActivationSourceError(
                    "active mapping capability snapshot no longer matches "
                    "its immutable semantic quality report"
                )
        return state

    def require_monitoring_capability(
        self,
        project_id: str,
        capability_id: str,
    ) -> MonitoringMappingCapabilitySnapshot:
        capability_id = _require_identifier(capability_id, "capability_id")
        state = self.get_active_mapping(project_id)
        snapshot = next(
            (
                item
                for item in state.capability_states
                if item.capability_id == capability_id
            ),
            None,
        )
        if snapshot is None:
            raise MonitoringMappingCapabilityUnavailableError(
                "monitoring capability is not present in the active manifest"
            )
        if snapshot.state in {
            MappingCapabilityStateCode.BLOCKED_BY_QUALITY.value,
            MappingCapabilityStateCode.DISABLED_BY_DESIGN.value,
        }:
            raise MonitoringMappingCapabilityUnavailableError(
                "monitoring capability is unavailable for the active mapping: "
                + ",".join(snapshot.limitation_codes)
            )
        return snapshot

    def list_activation_history(
        self,
        project_id: str,
    ) -> tuple[MonitoringMappingActivationState, ...]:
        project_id = _require_identifier(project_id, "project_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT state_json
                FROM monitoring_mapping_activation_history
                WHERE project_id = ?
                ORDER BY project_version
                """,
                (project_id,),
            ).fetchall()
        return tuple(
            self._state_from_dict(json.loads(row["state_json"]))
            for row in rows
        )

    def compare_new_batch(
        self,
        project_id: str,
        field_profile: Any,
    ) -> MonitoringMappingCompatibilityReport:
        state = self.get_active_mapping(project_id, validate_source=False)
        revision, baseline = self._load_valid_confirmed_revision(
            state.project_id,
            state.mapping_revision,
        )
        if _mapping_content_sha256(revision) != state.mapping_content_sha256:
            raise MonitoringMappingActivationSourceError(
                "active mapping content no longer matches immutable source"
            )
        profile = self._normalize_profile(field_profile)
        if profile["project_id"] != state.project_id:
            raise MonitoringMappingActivationSourceError(
                "new batch profile belongs to another project"
            )
        current = {
            signature.key: signature for signature in profile["field_signatures"]
        }
        baseline_by_key = {signature.key: signature for signature in baseline}

        exact_shared = set(baseline_by_key) & set(current)
        conflicts: list[MonitoringMappingFieldDifference] = []
        conflicted_keys: set[tuple[str, str]] = set()
        for key in sorted(exact_shared):
            previous = baseline_by_key[key]
            present = current[key]
            if not self._types_compatible(
                previous.inferred_type,
                present.inferred_type,
            ):
                conflicts.append(
                    MonitoringMappingFieldDifference(
                        kind=MonitoringMappingDifferenceKind.SAME_NAME_CONFLICT,
                        domain=present.domain,
                        source_field=present.source_field,
                        baseline_domains=(previous.domain,),
                        current_domains=(present.domain,),
                        baseline_inferred_type=previous.inferred_type,
                        current_inferred_type=present.inferred_type,
                        reason="inferred_type_changed",
                    )
                )
                conflicted_keys.add(key)

        unmatched_baseline = set(baseline_by_key) - set(current)
        unmatched_current = set(current) - set(baseline_by_key)
        baseline_by_name = self._keys_by_name(unmatched_baseline)
        current_by_name = self._keys_by_name(unmatched_current)
        for normalized_name in sorted(set(baseline_by_name) & set(current_by_name)):
            previous_keys = baseline_by_name[normalized_name]
            present_keys = current_by_name[normalized_name]
            previous = baseline_by_key[previous_keys[0]]
            present = current[present_keys[0]]
            conflicts.append(
                MonitoringMappingFieldDifference(
                    kind=MonitoringMappingDifferenceKind.SAME_NAME_CONFLICT,
                    domain=present.domain,
                    source_field=present.source_field,
                    baseline_domains=tuple(key[0] for key in previous_keys),
                    current_domains=tuple(key[0] for key in present_keys),
                    baseline_inferred_type=previous.inferred_type,
                    current_inferred_type=present.inferred_type,
                    reason="same_name_moved_or_duplicated_across_domains",
                )
            )
            conflicted_keys.update(previous_keys)
            conflicted_keys.update(present_keys)

        added = tuple(
            MonitoringMappingFieldDifference(
                kind=MonitoringMappingDifferenceKind.ADDED,
                domain=domain,
                source_field=source_field,
                current_domains=(domain,),
                current_inferred_type=current[(domain, source_field)].inferred_type,
                reason="field_not_present_in_active_mapping",
            )
            for domain, source_field in sorted(
                unmatched_current - conflicted_keys
            )
        )
        missing = tuple(
            MonitoringMappingFieldDifference(
                kind=MonitoringMappingDifferenceKind.MISSING,
                domain=domain,
                source_field=source_field,
                baseline_domains=(domain,),
                baseline_inferred_type=baseline_by_key[
                    (domain, source_field)
                ].inferred_type,
                reason="active_mapping_field_absent_from_new_batch",
            )
            for domain, source_field in sorted(
                unmatched_baseline - conflicted_keys
            )
        )
        conflict_tuple = tuple(
            sorted(
                conflicts,
                key=lambda item: (
                    item.domain,
                    item.source_field,
                    item.reason,
                ),
            )
        )
        compatible = not (added or missing or conflict_tuple)
        status = (
            MonitoringMappingCompatibilityStatus.FULLY_COMPATIBLE
            if compatible
            else MonitoringMappingCompatibilityStatus.DIFFERENCE_REVIEW_REQUIRED
        )
        report_payload = {
            "project_id": state.project_id,
            "batch_id": profile["batch_id"],
            "mapping_revision": state.mapping_revision,
            "mapping_content_sha256": state.mapping_content_sha256,
            "profile_sha256": profile["profile_sha256"],
            "status": status.value,
            "reuse_recommended": compatible,
            "added": [item.to_dict() for item in added],
            "missing": [item.to_dict() for item in missing],
            "same_name_conflicts": [item.to_dict() for item in conflict_tuple],
        }
        return MonitoringMappingCompatibilityReport(
            project_id=state.project_id,
            batch_id=profile["batch_id"],
            mapping_revision=state.mapping_revision,
            mapping_content_sha256=state.mapping_content_sha256,
            profile_sha256=profile["profile_sha256"],
            status=status,
            reuse_recommended=compatible,
            added=added,
            missing=missing,
            same_name_conflicts=conflict_tuple,
            report_sha256=content_sha256(report_payload),
        )

    def register_batch_comparison(
        self,
        project_id: str,
        field_profile: Any,
        *,
        expected_binding_version: int,
        actor: str,
        idempotency_key: str,
    ) -> MonitoringBatchMappingBindingResult:
        project_id = _require_identifier(project_id, "project_id")
        actor = _require_text(actor, "actor", maximum=160)
        idempotency_key = _require_identifier(
            idempotency_key,
            "idempotency_key",
        )
        if expected_binding_version < 0:
            raise ValueError("expected_binding_version cannot be negative")
        report = self.compare_new_batch(project_id, field_profile)
        status = (
            MonitoringBatchMappingBindingStatus.REUSE_SUGGESTED
            if report.reuse_recommended
            else MonitoringBatchMappingBindingStatus.DIFFERENCE_REVIEW_REQUIRED
        )
        request_sha256 = content_sha256(
            {
                "project_id": project_id,
                "batch_id": report.batch_id,
                "expected_binding_version": expected_binding_version,
                "actor": actor,
                "report_sha256": report.report_sha256,
            }
        )
        now = _iso(self.clock())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT request_sha256, result_json
                FROM monitoring_mapping_binding_operations
                WHERE project_id = ? AND operation_id = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_sha256"] != request_sha256:
                    connection.rollback()
                    raise MonitoringMappingActivationConflictError(
                        "idempotency key was reused with another binding request"
                    )
                result = self._binding_result_from_json(replay["result_json"])
                connection.commit()
                return replace(result, replayed=True)

            current = connection.execute(
                """
                SELECT * FROM monitoring_mapping_batch_bindings
                WHERE project_id = ? AND batch_id = ?
                """,
                (project_id, report.batch_id),
            ).fetchone()
            current_version = (
                int(current["binding_version"]) if current is not None else 0
            )
            if current_version != expected_binding_version:
                connection.rollback()
                raise MonitoringMappingActivationConflictError(
                    "batch mapping comparison lost CAS"
                )
            binding = MonitoringBatchMappingBinding(
                project_id=project_id,
                batch_id=report.batch_id,
                binding_version=current_version + 1,
                evaluated_mapping_revision=report.mapping_revision,
                mapping_content_sha256=report.mapping_content_sha256,
                profile_sha256=report.profile_sha256,
                compatibility_report_sha256=report.report_sha256,
                status=status,
                created_by=actor,
                created_at=now,
            )
            connection.execute(
                """
                INSERT INTO monitoring_mapping_batch_bindings(
                    project_id, batch_id, binding_version,
                    evaluated_mapping_revision, mapping_content_sha256,
                    profile_sha256, compatibility_report_sha256,
                    compatibility_report_json, status, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, batch_id) DO UPDATE SET
                    binding_version = excluded.binding_version,
                    evaluated_mapping_revision =
                        excluded.evaluated_mapping_revision,
                    mapping_content_sha256 = excluded.mapping_content_sha256,
                    profile_sha256 = excluded.profile_sha256,
                    compatibility_report_sha256 =
                        excluded.compatibility_report_sha256,
                    compatibility_report_json =
                        excluded.compatibility_report_json,
                    status = excluded.status,
                    created_by = excluded.created_by,
                    created_at = excluded.created_at
                """,
                (
                    binding.project_id,
                    binding.batch_id,
                    binding.binding_version,
                    binding.evaluated_mapping_revision,
                    binding.mapping_content_sha256,
                    binding.profile_sha256,
                    binding.compatibility_report_sha256,
                    canonical_json(report.to_dict()),
                    binding.status.value,
                    binding.created_by,
                    binding.created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO monitoring_mapping_batch_binding_history(
                    project_id, batch_id, binding_version, binding_json,
                    compatibility_report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    binding.batch_id,
                    binding.binding_version,
                    canonical_json(binding.to_dict()),
                    canonical_json(report.to_dict()),
                    now,
                ),
            )
            result = MonitoringBatchMappingBindingResult(
                binding=binding,
                report=report,
                replayed=False,
            )
            connection.execute(
                """
                INSERT INTO monitoring_mapping_binding_operations(
                    project_id, operation_id, request_sha256,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    idempotency_key,
                    request_sha256,
                    canonical_json(result.to_dict()),
                    now,
                ),
            )
            connection.commit()
        return result

    def get_batch_binding(
        self,
        project_id: str,
        batch_id: str,
    ) -> MonitoringBatchMappingBinding:
        project_id = _require_identifier(project_id, "project_id")
        batch_id = _require_identifier(batch_id, "batch_id")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM monitoring_mapping_batch_bindings
                WHERE project_id = ? AND batch_id = ?
                """,
                (project_id, batch_id),
            ).fetchone()
        if row is None:
            raise MonitoringMappingActivationNotFoundError(
                "batch mapping comparison not found"
            )
        return self._binding_from_row(row)

    def list_batch_binding_history(
        self,
        project_id: str,
        batch_id: str,
    ) -> tuple[MonitoringBatchMappingBinding, ...]:
        project_id = _require_identifier(project_id, "project_id")
        batch_id = _require_identifier(batch_id, "batch_id")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT binding_json
                FROM monitoring_mapping_batch_binding_history
                WHERE project_id = ? AND batch_id = ?
                ORDER BY binding_version
                """,
                (project_id, batch_id),
            ).fetchall()
        return tuple(
            self._binding_from_dict(json.loads(row["binding_json"]))
            for row in rows
        )

    def _load_valid_confirmed_revision(
        self,
        project_id: str,
        mapping_revision: str,
        *,
        require_semantic_quality: bool = False,
    ) -> tuple[MonitoringMappingRevision, tuple[_FieldSignature, ...]]:
        if not _MAPPING_REVISION_RE.fullmatch(mapping_revision):
            raise MonitoringMappingActivationSourceError(
                "only formal monmaprev revisions may be activated"
            )
        try:
            revision = self.mapping_repository.get_revision(
                project_id,
                mapping_revision,
            )
            draft = self.mapping_repository.get_draft(
                project_id,
                revision.draft_id,
            )
        except Exception as exc:
            raise MonitoringMappingActivationSourceError(
                "confirmed mapping revision is unavailable"
            ) from exc
        if (
            revision.project_id != project_id
            or draft.project_id != project_id
            or draft.status != MonitoringMappingDraftStatus.CONFIRMED
            or draft.confirmed_revision_id != revision.mapping_revision
            or revision.mapping_revision != mapping_revision
        ):
            raise MonitoringMappingActivationSourceError(
                "mapping revision is not the confirmed revision for this project"
            )
        if (
            draft.batch_id != revision.batch_id
            or draft.full_profile_sha256 != revision.full_profile_sha256
            or draft.full_input_sha256 != revision.full_input_sha256
            or draft.input_revision_sha256 != revision.input_revision_sha256
            or draft.source_set_sha256 != revision.source_set_sha256
            or draft.version != revision.draft_version
            or draft.fields != revision.fields
            or draft.field_sources != revision.field_sources
            or draft.input_revision.revision_sha256
            != revision.input_revision_sha256
        ):
            raise MonitoringMappingActivationSourceError(
                "confirmed mapping revision no longer matches its immutable draft"
            )
        baseline = self._validate_source_chain(revision, draft.expected_job_ids)
        revision_pairs = {
            (field.domain, field.source_field) for field in revision.fields
        }
        if revision_pairs != {item.key for item in baseline}:
            raise MonitoringMappingActivationSourceError(
                "mapping revision does not cover its complete source profile"
            )
        if revision.semantic_quality_report_sha256:
            current_quality = evaluate_mapping_semantic_quality(
                fields=revision.fields,
                expected_fields=revision_pairs,
            )
            if (
                current_quality.status == SemanticQualityStatus.BLOCKED
                or current_quality.report_sha256
                != revision.semantic_quality_report_sha256
                or current_quality.as_payload()
                != revision.semantic_quality_report
            ):
                raise MonitoringMappingActivationSourceError(
                    "mapping semantic quality report is stale or invalid"
                )
        elif require_semantic_quality:
            raise MonitoringMappingActivationSourceError(
                "mapping revision has no semantic quality report"
            )
        return revision, baseline

    @staticmethod
    def _capability_contract_from_revision(
        revision: MonitoringMappingRevision,
    ) -> tuple[
        str,
        str,
        str,
        tuple[str, ...],
        tuple[MonitoringMappingCapabilitySnapshot, ...],
    ]:
        report = revision.semantic_quality_report
        manifest_value = report.get("capability_manifest_sha256", "")
        try:
            manifest_sha256 = _require_hash(
                manifest_value, "capability_manifest_sha256"
            )
        except ValueError as exc:
            raise MonitoringMappingActivationSourceError(
                "mapping capability manifest is stale or invalid"
            ) from exc
        if manifest_sha256 != current_capability_manifest_sha256():
            raise MonitoringMappingActivationSourceError(
                "mapping capability manifest is stale or invalid"
            )
        disposition = str(report.get("activation_disposition", "")).strip()
        if disposition not in {
            MappingActivationDisposition.ACTIVATE_FULL.value,
            MappingActivationDisposition.ACTIVATE_RESTRICTED.value,
        }:
            raise MonitoringMappingActivationSourceError(
                "mapping semantic quality does not permit activation"
            )
        raw_states = report.get("capability_states")
        if not isinstance(raw_states, list):
            raise MonitoringMappingActivationSourceError(
                "mapping semantic quality has no capability snapshot"
            )
        registered_ids = tuple(
            item.capability_id for item in CAPABILITY_MANIFEST_V1
        )
        snapshots: list[MonitoringMappingCapabilitySnapshot] = []
        for raw in raw_states:
            if not isinstance(raw, Mapping):
                raise MonitoringMappingActivationSourceError(
                    "mapping capability snapshot is malformed"
                )
            capability_id = str(raw.get("capability_id", "")).strip()
            state = str(raw.get("state", "")).strip()
            finding_ids = raw.get("blocking_finding_group_ids", ())
            limitation_codes = raw.get("limitation_codes", ())
            if (
                capability_id not in registered_ids
                or state not in {item.value for item in MappingCapabilityStateCode}
                or not isinstance(finding_ids, (list, tuple))
                or not isinstance(limitation_codes, (list, tuple))
            ):
                raise MonitoringMappingActivationSourceError(
                    "mapping capability snapshot contains invalid values"
                )
            snapshots.append(
                MonitoringMappingCapabilitySnapshot(
                    capability_id=capability_id,
                    state=state,
                    blocking_finding_group_ids=tuple(
                        sorted(
                            {
                                str(item).strip()
                                for item in finding_ids
                                if str(item).strip()
                            }
                        )
                    ),
                    limitation_codes=tuple(
                        sorted(
                            {
                                str(item).strip()
                                for item in limitation_codes
                                if str(item).strip()
                            }
                        )
                    ),
                )
            )
        snapshots.sort(key=lambda item: registered_ids.index(item.capability_id))
        if (
            tuple(item.capability_id for item in snapshots)
            != registered_ids
            or len(snapshots) != len(registered_ids)
        ):
            raise MonitoringMappingActivationSourceError(
                "mapping capability snapshot does not cover the current manifest"
            )
        has_restriction = any(
            item.state
            in {
                MappingCapabilityStateCode.LIMITED.value,
                MappingCapabilityStateCode.BLOCKED_BY_QUALITY.value,
            }
            for item in snapshots
        )
        if (
            disposition
            == MappingActivationDisposition.ACTIVATE_RESTRICTED.value
        ) != has_restriction:
            raise MonitoringMappingActivationSourceError(
                "mapping activation disposition conflicts with capability states"
            )
        effective = tuple(
            item.capability_id
            for item in snapshots
            if item.state
            in {
                MappingCapabilityStateCode.READY.value,
                MappingCapabilityStateCode.LIMITED.value,
            }
        )
        effective_sha256 = content_sha256(
            {
                "capability_manifest_sha256": manifest_sha256,
                "activation_disposition": disposition,
                "effective_capabilities": list(effective),
                "capability_states": [
                    item.to_dict() for item in snapshots
                ],
            }
        )
        return (
            disposition,
            manifest_sha256,
            effective_sha256,
            effective,
            tuple(snapshots),
        )

    def _validate_source_chain(
        self,
        revision: MonitoringMappingRevision,
        expected_job_ids: Sequence[str],
    ) -> tuple[_FieldSignature, ...]:
        source_path = Path(self.mapping_repository.path)
        try:
            connection = sqlite3.connect(source_path, timeout=30)
            connection.row_factory = sqlite3.Row
            table_names = {
                row["name"]
                for row in connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name IN (
                        'monitoring_ai_jobs',
                        'monitoring_ai_candidates'
                    )
                    """
                ).fetchall()
            }
            if table_names != {
                "monitoring_ai_jobs",
                "monitoring_ai_candidates",
            }:
                raise MonitoringMappingActivationSourceError(
                    "mapping source tables are unavailable"
                )
            source_by_job: dict[str, list[Any]] = {}
            for source in revision.field_sources:
                source_by_job.setdefault(source.job_id, []).append(source)
            if (
                len(expected_job_ids) != len(set(expected_job_ids))
                or set(source_by_job) != set(expected_job_ids)
            ):
                raise MonitoringMappingActivationSourceError(
                    "mapping source job set changed after confirmation"
                )

            signatures: dict[tuple[str, str], _FieldSignature] = {}
            for job_id, field_sources in sorted(source_by_job.items()):
                job = connection.execute(
                    """
                    SELECT * FROM monitoring_ai_jobs
                    WHERE project_id = ? AND job_id = ?
                    """,
                    (revision.project_id, job_id),
                ).fetchone()
                if (
                    job is None
                    or job["status"] != "completed"
                    or job["task_type"] != "listing_field_mapping"
                ):
                    raise MonitoringMappingActivationSourceError(
                        "mapping source job is unavailable or incomplete"
                    )
                payload = json.loads(job["input_payload_json"])
                if (
                    content_sha256(payload) != job["input_payload_sha256"]
                    or job["input_revision_sha256"]
                    != revision.input_revision_sha256
                ):
                    raise MonitoringMappingActivationSourceError(
                        "mapping source job input hash changed"
                    )
                field_profile = payload.get("field_profile")
                if not isinstance(field_profile, dict) or (
                    field_profile.get("scope") != "complete_profile_chunk"
                    or field_profile.get("batch_id") != revision.batch_id
                    or field_profile.get("full_profile_sha256")
                    != revision.full_profile_sha256
                    or field_profile.get("full_input_sha256")
                    != revision.full_input_sha256
                ):
                    raise MonitoringMappingActivationSourceError(
                        "mapping source profile no longer matches revision input"
                    )
                profile_fields = field_profile.get("fields")
                if not isinstance(profile_fields, list) or not profile_fields:
                    raise MonitoringMappingActivationSourceError(
                        "mapping source profile fields are unavailable"
                    )
                chunk_signatures = self._normalize_field_signatures(profile_fields)
                chunk_by_key = {item.key: item for item in chunk_signatures}

                candidate_ids = {source.candidate_id for source in field_sources}
                if len(candidate_ids) != 1:
                    raise MonitoringMappingActivationSourceError(
                        "one source chunk must bind exactly one candidate"
                    )
                candidate_id = next(iter(candidate_ids))
                candidate = connection.execute(
                    """
                    SELECT * FROM monitoring_ai_candidates
                    WHERE project_id = ? AND job_id = ? AND candidate_id = ?
                    """,
                    (revision.project_id, job_id, candidate_id),
                ).fetchone()
                if (
                    candidate is None
                    or candidate["status"] != "accepted"
                    or candidate["project_id"] != revision.project_id
                    or candidate["task_type"] != "listing_field_mapping"
                    or candidate["input_revision_sha256"]
                    != revision.input_revision_sha256
                ):
                    raise MonitoringMappingActivationSourceError(
                        "mapping source candidate is no longer accepted"
                    )
                candidate_payload = json.loads(candidate["candidate_json"])
                candidate_hash = content_sha256(candidate_payload)
                for source in field_sources:
                    if (
                        source.candidate_content_sha256 != candidate_hash
                        or source.input_revision_sha256
                        != revision.input_revision_sha256
                        or source.prompt_version != job["prompt_version"]
                        or candidate["input_revision_sha256"]
                        != revision.input_revision_sha256
                    ):
                        raise MonitoringMappingActivationSourceError(
                            "mapping source candidate hash or revision changed"
                        )
                    key = (source.domain, source.source_field)
                    signature = chunk_by_key.get(key)
                    if signature is None or key in signatures:
                        raise MonitoringMappingActivationSourceError(
                            "mapping source field is missing or duplicated"
                        )
                    signatures[key] = signature
        except sqlite3.Error as exc:
            raise MonitoringMappingActivationSourceError(
                "mapping source database could not be validated"
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()
        return tuple(signatures[key] for key in sorted(signatures))

    def _normalize_profile(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "to_dict") and callable(value.to_dict):
            payload = value.to_dict()
        elif isinstance(value, Mapping):
            payload = dict(value)
        else:
            raise TypeError("field_profile must be a profile snapshot or mapping")
        required = {
            "schema_version",
            "batch_id",
            "project_id",
            "batch_revision",
            "mapping_revision",
            "expected_domains",
            "source_bindings",
            "source_sha256s",
            "row_count",
            "input_sha256",
            "fields",
            "relationships",
            "profile_sha256",
        }
        if not required.issubset(payload):
            raise MonitoringMappingActivationSourceError(
                "new batch profile is incomplete"
            )
        claimed_hash = _require_hash(payload["profile_sha256"], "profile_sha256")
        unhashed = {key: payload[key] for key in payload if key != "profile_sha256"}
        if content_sha256(unhashed) != claimed_hash:
            raise MonitoringMappingActivationSourceError(
                "new batch profile hash is inconsistent"
            )
        batch_id = _require_identifier(payload["batch_id"], "batch_id")
        project_id = _require_identifier(payload["project_id"], "project_id")
        fields = payload["fields"]
        if not isinstance(fields, list) or not fields:
            raise MonitoringMappingActivationSourceError(
                "new batch profile has no fields"
            )
        return {
            "batch_id": batch_id,
            "project_id": project_id,
            "profile_sha256": claimed_hash,
            "field_signatures": self._normalize_field_signatures(fields),
        }

    @staticmethod
    def _normalize_field_signatures(
        fields: Sequence[Mapping[str, Any]],
    ) -> tuple[_FieldSignature, ...]:
        signatures: dict[tuple[str, str], _FieldSignature] = {}
        for item in fields:
            if not isinstance(item, Mapping):
                raise MonitoringMappingActivationSourceError(
                    "field profile entry is malformed"
                )
            domain = str(item.get("domain", "")).strip()
            source_field = str(item.get("field", "")).strip()
            inferred_type = str(item.get("inferred_type", "")).strip().lower()
            if not domain or not source_field or not inferred_type:
                raise MonitoringMappingActivationSourceError(
                    "field profile entry is incomplete"
                )
            signature = _FieldSignature(
                domain=domain,
                source_field=source_field,
                inferred_type=inferred_type,
            )
            if signature.key in signatures:
                raise MonitoringMappingActivationSourceError(
                    "field profile contains duplicate domain and field"
                )
            signatures[signature.key] = signature
        return tuple(signatures[key] for key in sorted(signatures))

    @staticmethod
    def _keys_by_name(
        keys: set[tuple[str, str]],
    ) -> dict[str, tuple[tuple[str, str], ...]]:
        grouped: dict[str, list[tuple[str, str]]] = {}
        for key in sorted(keys):
            grouped.setdefault(key[1].casefold(), []).append(key)
        return {name: tuple(values) for name, values in grouped.items()}

    @staticmethod
    def _types_compatible(previous: str, current: str) -> bool:
        return (
            previous == current
            or previous == "unknown"
            or current == "unknown"
            or (
            previous == "integer" and current == "decimal"
            )
        )

    @staticmethod
    def _state_from_row(row: sqlite3.Row) -> MonitoringMappingActivationState:
        keys = set(row.keys())
        try:
            effective_capabilities = (
                json.loads(row["effective_capabilities_json"])
                if "effective_capabilities_json" in keys
                else ()
            )
            capability_states = (
                json.loads(row["capability_states_json"])
                if "capability_states_json" in keys
                else ()
            )
        except (TypeError, ValueError) as exc:
            raise MonitoringMappingActivationError(
                "persisted mapping activation state JSON is invalid"
            ) from exc
        return MonitoringMappingActivationService._state_from_payload(
            {
                "project_id": row["project_id"],
                "mapping_revision": row["mapping_revision"],
                "mapping_content_sha256": row["mapping_content_sha256"],
                "source_batch_id": row["source_batch_id"],
                "source_profile_sha256": row["source_profile_sha256"],
                "source_input_sha256": row["source_input_sha256"],
                "semantic_quality_report_sha256": (
                    row["semantic_quality_report_sha256"]
                    if "semantic_quality_report_sha256" in keys
                    else ""
                ),
                "capability_manifest_sha256": (
                    row["capability_manifest_sha256"]
                    if "capability_manifest_sha256" in keys
                    else ""
                ),
                "activation_disposition": (
                    row["activation_disposition"]
                    if "activation_disposition" in keys
                    else MappingActivationDisposition.REJECT.value
                ),
                "effective_capabilities": effective_capabilities,
                "effective_capabilities_sha256": (
                    row["effective_capabilities_sha256"]
                    if "effective_capabilities_sha256" in keys
                    else ""
                ),
                "capability_states": capability_states,
                "project_version": row["project_version"],
                "activated_by": row["activated_by"],
                "activation_reason": row["activation_reason"],
                "activated_at": row["activated_at"],
            }
        )

    @staticmethod
    def _state_from_payload(
        payload: Mapping[str, Any],
    ) -> MonitoringMappingActivationState:
        required = {
            "project_id",
            "mapping_revision",
            "mapping_content_sha256",
            "source_batch_id",
            "source_profile_sha256",
            "source_input_sha256",
            "project_version",
            "activated_by",
            "activation_reason",
            "activated_at",
        }
        if not required.issubset(payload):
            raise MonitoringMappingActivationError(
                "persisted mapping activation state is incomplete"
            )

        def text(value: object, label: str, maximum: int = 4000) -> str:
            if not isinstance(value, str) or not value or value.strip() != value:
                raise MonitoringMappingActivationError(
                    f"persisted mapping activation state {label} is invalid"
                )
            if len(value) > maximum:
                raise MonitoringMappingActivationError(
                    f"persisted mapping activation state {label} is invalid"
                )
            return value

        def hash_value(value: object, label: str, allow_empty: bool = False) -> str:
            if allow_empty and value == "":
                return ""
            raw = text(value, label)
            normalized = _require_hash(raw, label)
            if raw != normalized:
                raise MonitoringMappingActivationError(
                    f"persisted mapping activation state {label} is invalid"
                )
            return raw

        try:
            project_id = _require_identifier(text(payload["project_id"], "project_id"), "project_id")
            mapping_revision = text(payload["mapping_revision"], "mapping_revision")
            if not _MAPPING_REVISION_RE.fullmatch(mapping_revision):
                raise MonitoringMappingActivationError(
                    "persisted mapping activation state mapping revision is invalid"
                )
            source_batch_id = _require_identifier(
                text(payload["source_batch_id"], "source_batch_id"),
                "source_batch_id",
            )
            project_version = payload["project_version"]
            if (
                isinstance(project_version, bool)
                or not isinstance(project_version, int)
                or project_version < 1
            ):
                raise MonitoringMappingActivationError(
                    "persisted mapping activation state project version is invalid"
                )
            disposition = MappingActivationDisposition(
                text(
                    payload.get(
                        "activation_disposition",
                        MappingActivationDisposition.REJECT.value,
                    ),
                    "activation_disposition",
                )
            ).value
            capabilities = payload.get("effective_capabilities", ())
            if not isinstance(capabilities, (list, tuple)):
                raise MonitoringMappingActivationError(
                    "persisted mapping activation state capabilities are invalid"
                )
            capabilities = tuple(text(item, "effective_capability", 240) for item in capabilities)
            if len(capabilities) != len(set(capabilities)):
                raise MonitoringMappingActivationError(
                    "persisted mapping activation state capabilities are invalid"
                )
            raw_states = payload.get("capability_states", ())
            if not isinstance(raw_states, (list, tuple)):
                raise MonitoringMappingActivationError(
                    "persisted mapping activation state capability states are invalid"
                )
            states: list[MonitoringMappingCapabilitySnapshot] = []
            for item in raw_states:
                if not isinstance(item, Mapping):
                    raise MonitoringMappingActivationError(
                        "persisted mapping activation state capability states are invalid"
                    )
                if set(item) != {
                    "capability_id",
                    "state",
                    "blocking_finding_group_ids",
                    "limitation_codes",
                }:
                    raise MonitoringMappingActivationError(
                        "persisted mapping activation state capability states are invalid"
                    )
                blocking = item.get("blocking_finding_group_ids", ())
                limitations = item.get("limitation_codes", ())
                if not isinstance(blocking, (list, tuple)) or not isinstance(limitations, (list, tuple)):
                    raise MonitoringMappingActivationError(
                        "persisted mapping activation state capability states are invalid"
                    )
                states.append(
                    MonitoringMappingCapabilitySnapshot(
                        capability_id=text(item.get("capability_id"), "capability_id", 240),
                        state=text(item.get("state"), "capability_state", 80),
                        blocking_finding_group_ids=tuple(
                            text(value, "blocking_finding_group_id", 240)
                            for value in blocking
                        ),
                        limitation_codes=tuple(
                            text(value, "limitation_code", 240)
                            for value in limitations
                        ),
                    )
                )
            state_ids = [item.capability_id for item in states]
            if len(state_ids) != len(set(state_ids)):
                raise MonitoringMappingActivationError(
                    "persisted mapping activation state capability states are invalid"
                )
            activated_at = text(payload["activated_at"], "activated_at")
            datetime.fromisoformat(activated_at)
            return MonitoringMappingActivationState(
                project_id=project_id,
                mapping_revision=mapping_revision,
                mapping_content_sha256=hash_value(
                    payload["mapping_content_sha256"],
                    "mapping_content_sha256",
                ),
                source_batch_id=source_batch_id,
                source_profile_sha256=hash_value(
                    payload["source_profile_sha256"],
                    "source_profile_sha256",
                ),
                source_input_sha256=hash_value(
                    payload["source_input_sha256"],
                    "source_input_sha256",
                ),
                semantic_quality_report_sha256=hash_value(
                    payload.get("semantic_quality_report_sha256", ""),
                    "semantic_quality_report_sha256",
                    True,
                ),
                capability_manifest_sha256=hash_value(
                    payload.get("capability_manifest_sha256", ""),
                    "capability_manifest_sha256",
                    True,
                ),
                activation_disposition=disposition,
                effective_capabilities_sha256=hash_value(
                    payload.get("effective_capabilities_sha256", ""),
                    "effective_capabilities_sha256",
                    True,
                ),
                effective_capabilities=capabilities,
                capability_states=tuple(states),
                project_version=project_version,
                activated_by=text(payload["activated_by"], "activated_by", 160),
                activation_reason=text(payload["activation_reason"], "activation_reason"),
                activated_at=activated_at,
            )
        except MonitoringMappingActivationError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise MonitoringMappingActivationError(
                "persisted mapping activation state is invalid"
            ) from exc

    @staticmethod
    def _state_from_dict(
        payload: Mapping[str, Any],
    ) -> MonitoringMappingActivationState:
        return MonitoringMappingActivationService._state_from_payload(payload)

    @staticmethod
    def _binding_from_row(row: sqlite3.Row) -> MonitoringBatchMappingBinding:
        return MonitoringMappingActivationService._binding_from_payload(
            {
                "project_id": row["project_id"],
                "batch_id": row["batch_id"],
                "binding_version": row["binding_version"],
                "evaluated_mapping_revision": row["evaluated_mapping_revision"],
                "mapping_content_sha256": row["mapping_content_sha256"],
                "profile_sha256": row["profile_sha256"],
                "compatibility_report_sha256": row["compatibility_report_sha256"],
                "status": row["status"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
            }
        )

    @staticmethod
    def _binding_from_payload(
        payload: Mapping[str, Any],
    ) -> MonitoringBatchMappingBinding:
        try:
            def text(value: object, label: str, maximum: int = 4000) -> str:
                if not isinstance(value, str) or not value or value.strip() != value:
                    raise MonitoringMappingActivationError(
                        f"persisted mapping binding {label} is invalid"
                    )
                if len(value) > maximum:
                    raise MonitoringMappingActivationError(
                        f"persisted mapping binding {label} is invalid"
                    )
                return value

            def hash_value(value: object, label: str) -> str:
                raw = text(value, label)
                normalized = _require_hash(raw, label)
                if raw != normalized:
                    raise MonitoringMappingActivationError(
                        f"persisted mapping binding {label} is invalid"
                    )
                return raw

            project_id = _require_identifier(text(payload["project_id"], "project_id"), "project_id")
            batch_id = _require_identifier(text(payload["batch_id"], "batch_id"), "batch_id")
            mapping_revision = text(
                payload["evaluated_mapping_revision"],
                "evaluated_mapping_revision",
            )
            if not _MAPPING_REVISION_RE.fullmatch(mapping_revision):
                raise MonitoringMappingActivationError(
                    "persisted mapping binding revision is invalid"
                )
            binding_version = payload["binding_version"]
            if (
                isinstance(binding_version, bool)
                or not isinstance(binding_version, int)
                or binding_version < 1
            ):
                raise MonitoringMappingActivationError(
                    "persisted mapping binding version is invalid"
                )
            status = MonitoringBatchMappingBindingStatus(
                text(payload["status"], "status")
            ).value
            created_at = text(payload["created_at"], "created_at")
            datetime.fromisoformat(created_at)
            return MonitoringBatchMappingBinding(
                project_id=project_id,
                batch_id=batch_id,
                binding_version=binding_version,
                evaluated_mapping_revision=mapping_revision,
                mapping_content_sha256=hash_value(
                    payload["mapping_content_sha256"],
                    "mapping_content_sha256",
                ),
                profile_sha256=hash_value(payload["profile_sha256"], "profile_sha256"),
                compatibility_report_sha256=hash_value(
                    payload["compatibility_report_sha256"],
                    "compatibility_report_sha256",
                ),
                status=status,
                created_by=text(payload["created_by"], "created_by", 160),
                created_at=created_at,
            )
        except MonitoringMappingActivationError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise MonitoringMappingActivationError(
                "persisted mapping binding is invalid"
            ) from exc

    @staticmethod
    def _binding_from_dict(
        payload: Mapping[str, Any],
    ) -> MonitoringBatchMappingBinding:
        return MonitoringMappingActivationService._binding_from_payload(payload)

    @classmethod
    def _activation_result_from_json(
        cls,
        value: str,
    ) -> MonitoringMappingActivationResult:
        payload = json.loads(value)
        return MonitoringMappingActivationResult(
            state=MonitoringMappingActivationService._state_from_dict(
                payload["state"]
            ),
            replayed=payload["replayed"],
            changed=payload["changed"],
        )

    @classmethod
    def _report_from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> MonitoringMappingCompatibilityReport:
        def differences(key: str) -> tuple[MonitoringMappingFieldDifference, ...]:
            return tuple(
                MonitoringMappingFieldDifference(
                    **{
                        **item,
                        "kind": MonitoringMappingDifferenceKind(item["kind"]),
                        "baseline_domains": tuple(item["baseline_domains"]),
                        "current_domains": tuple(item["current_domains"]),
                    }
                )
                for item in payload[key]
            )

        return MonitoringMappingCompatibilityReport(
            project_id=payload["project_id"],
            batch_id=payload["batch_id"],
            mapping_revision=payload["mapping_revision"],
            mapping_content_sha256=payload["mapping_content_sha256"],
            profile_sha256=payload["profile_sha256"],
            status=MonitoringMappingCompatibilityStatus(payload["status"]),
            reuse_recommended=payload["reuse_recommended"],
            added=differences("added"),
            missing=differences("missing"),
            same_name_conflicts=differences("same_name_conflicts"),
            report_sha256=payload["report_sha256"],
        )

    @classmethod
    def _binding_result_from_json(
        cls,
        value: str,
    ) -> MonitoringBatchMappingBindingResult:
        payload = json.loads(value)
        return MonitoringBatchMappingBindingResult(
            binding=cls._binding_from_dict(payload["binding"]),
            report=cls._report_from_dict(payload["report"]),
            replayed=payload["replayed"],
        )
