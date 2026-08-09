from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Literal, Mapping, Protocol


SHARED_PROTOCOL_FACT_PROJECTION_VERSION = "shared_protocol_fact_projection_v1"

ProtocolFactConsumer = Literal[
    "medical_monitoring",
    "medical_writing",
    "dashboard",
]
ProtocolFactOwner = Literal["medical_monitoring", "medical_writing"]

SUPPORTED_CONSUMERS = frozenset(
    {"medical_monitoring", "medical_writing", "dashboard"}
)
SUPPORTED_OWNERS = frozenset({"medical_monitoring", "medical_writing"})

# The dashboard only needs project-design facts. It must not become another
# consumer of operational monitoring-rule facts.
CONSUMER_OWNER_ALLOWLIST: Mapping[str, frozenset[str]] = {
    "medical_monitoring": frozenset(
        {"medical_monitoring", "medical_writing"}
    ),
    "medical_writing": frozenset(
        {"medical_monitoring", "medical_writing"}
    ),
    "dashboard": frozenset({"medical_writing"}),
}

_LOCAL_PATH_RE = re.compile(
    r"(?:^|[\s\"'(=])(?:file://|/Users/|/private/|/tmp/|/var/folders/|[A-Za-z]:\\)",
    re.IGNORECASE,
)
_FORBIDDEN_VALUE_KEYS = frozenset(
    {
        "ai_prompt",
        "debug",
        "debug_log",
        "developer_prompt",
        "file_path",
        "filesystem_path",
        "internal_log",
        "local_path",
        "log",
        "logs",
        "model_name",
        "prompt",
        "provider_request",
        "provider_response",
        "raw_prompt",
        "request_trace",
        "response_trace",
        "system_prompt",
        "trace",
    }
)


class UnsafeProtocolFactProjection(ValueError):
    """Raised internally when a fact cannot cross the module boundary."""


@dataclass(frozen=True)
class SharedProtocolFactDTO:
    fact_id: str
    project_id: str
    fact_type: str
    fact_path: str
    value: Any
    source_entry_id: str
    source_revision: str
    locator: str
    confirmed_by_module: ProtocolFactOwner
    confirmed_revision: str
    consumer: ProtocolFactConsumer
    status: Literal["confirmed"] = "confirmed"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"sharedpf_[0-9a-f]{32}", self.fact_id):
            raise UnsafeProtocolFactProjection("fact_id is not a stable shared fact id")
        if self.confirmed_by_module not in SUPPORTED_OWNERS:
            raise UnsafeProtocolFactProjection("unsupported confirming module")
        if self.consumer not in SUPPORTED_CONSUMERS:
            raise UnsafeProtocolFactProjection("unsupported protocol fact consumer")
        if self.status != "confirmed":
            raise UnsafeProtocolFactProjection(
                "shared protocol facts must be confirmed"
            )
        for field_name in (
            "project_id",
            "fact_type",
            "fact_path",
            "source_entry_id",
            "source_revision",
            "locator",
            "confirmed_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_safe_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "value", _safe_json_value(self.value))

    def public_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "project_id": self.project_id,
            "fact_type": self.fact_type,
            "fact_path": self.fact_path,
            "value": _json_clone(self.value),
            "source_entry_id": self.source_entry_id,
            "source_revision": self.source_revision,
            "locator": self.locator,
            "confirmed_by_module": self.confirmed_by_module,
            "confirmed_revision": self.confirmed_revision,
            "consumer": self.consumer,
            "status": self.status,
        }


@dataclass(frozen=True)
class ConfirmedProtocolFactRecord:
    project_id: str
    fact_type: str
    fact_path: str
    value: Any
    source_entry_id: str
    source_revision: str
    locator: str
    confirmed_by_module: ProtocolFactOwner
    confirmed_revision: str


class ProtocolFactReadAdapter(Protocol):
    module_name: ProtocolFactOwner

    def read_confirmed(
        self,
        project_id: str,
    ) -> tuple[ConfirmedProtocolFactRecord, ...]: ...


class MonitoringProtocolFactReadAdapter:
    """Read-only adapter over the medical-monitoring protocol repository."""

    module_name: ProtocolFactOwner = "medical_monitoring"

    def __init__(self, repository: Any):
        self._repository = repository

    def read_confirmed(
        self,
        project_id: str,
    ) -> tuple[ConfirmedProtocolFactRecord, ...]:
        project = _required_safe_text(project_id, "project_id")
        projected: list[ConfirmedProtocolFactRecord] = []
        for version in self._repository.list_protocol_versions(project):
            if version.project_id != project or version.status != "confirmed":
                continue
            if not _is_sha256(version.content_sha256):
                continue
            permitted_source_entries = {
                value
                for value in (
                    version.source_entry_id,
                    version.amendment_source_entry_id,
                )
                if value
            }
            for fact in self._repository.facts_for_version(
                version.protocol_version_id
            ):
                if fact.project_id != project:
                    continue
                if fact.status != "medically_confirmed":
                    continue
                # A fact created directly in a confirmed state has no durable
                # confirmation transition identity and therefore stays local.
                if int(fact.state_version) < 2:
                    continue
                if fact.source_entry_id not in permitted_source_entries:
                    continue
                try:
                    value = _monitoring_fact_value(fact)
                    projected.append(
                        _validated_record(
                            project_id=project,
                            fact_type=fact.fact_type,
                            fact_path=fact.fact_key,
                            value=value,
                            source_entry_id=fact.source_entry_id,
                            source_revision=version.content_sha256,
                            locator=fact.source_locator,
                            confirmed_by_module=self.module_name,
                            confirmed_revision=(
                                f"{fact.fact_revision_id}:state-{fact.state_version}"
                            ),
                        )
                    )
                except UnsafeProtocolFactProjection:
                    continue
        return tuple(projected)


class MedicalWritingProtocolFactReadAdapter:
    """Read-only adapter over the current medical-writing StudyDefinition."""

    module_name: ProtocolFactOwner = "medical_writing"

    def __init__(self, journey_reader: Any):
        self._journey_reader = journey_reader

    def read_confirmed(
        self,
        project_id: str,
    ) -> tuple[ConfirmedProtocolFactRecord, ...]:
        project = _required_safe_text(project_id, "project_id")
        try:
            journey = self._journey_reader.get(project)
        except (KeyError, LookupError, ValueError):
            return ()
        definition = getattr(journey, "study_definition", None)
        if definition is None or getattr(definition, "project_id", "") != project:
            return ()
        definition_revision = int(getattr(definition, "revision", 0) or 0)
        definition_id = str(getattr(definition, "definition_id", "") or "")
        state_sha256 = getattr(definition, "state_sha256", "")
        if definition_revision < 1 or not definition_id or not _is_sha256(state_sha256):
            return ()
        confirmed_revision = (
            f"{definition_id}:revision-{definition_revision}:{state_sha256}"
        )

        projected: list[ConfirmedProtocolFactRecord] = []
        field_states = getattr(definition, "field_states", {}) or {}
        for fact_path, state in sorted(field_states.items()):
            if getattr(state, "status", "") != "confirmed":
                continue
            if not getattr(state, "confirmed_by", ""):
                continue
            if getattr(state, "confirmed_at", None) is None:
                continue
            evidence_items = tuple(getattr(state, "evidence", ()) or ())
            if not evidence_items:
                continue
            try:
                value = _study_definition_value(definition, fact_path)
            except (KeyError, TypeError, UnsafeProtocolFactProjection):
                continue
            for evidence in evidence_items:
                source_entry_id = str(
                    getattr(evidence, "source_id", "") or ""
                ).strip()
                source_revision = str(
                    getattr(evidence, "extraction_revision", "") or ""
                ).strip()
                locator = str(getattr(evidence, "locator", "") or "").strip()
                quote_sha256 = getattr(evidence, "quote_sha256", "")
                if not _is_sha256(quote_sha256):
                    continue
                try:
                    projected.append(
                        _validated_record(
                            project_id=project,
                            fact_type="study_definition",
                            fact_path=str(fact_path),
                            value=value,
                            source_entry_id=source_entry_id,
                            source_revision=source_revision,
                            locator=locator,
                            confirmed_by_module=self.module_name,
                            confirmed_revision=confirmed_revision,
                        )
                    )
                except UnsafeProtocolFactProjection:
                    continue
        return tuple(projected)


class SharedProtocolFactProjectionService:
    """Aggregate confirmed facts without granting cross-module write access."""

    def __init__(self, adapters: Iterable[ProtocolFactReadAdapter]):
        self._adapters: dict[str, ProtocolFactReadAdapter] = {}
        for adapter in adapters:
            module_name = str(getattr(adapter, "module_name", "") or "")
            if module_name not in SUPPORTED_OWNERS:
                raise ValueError(f"unsupported protocol fact owner: {module_name}")
            if module_name in self._adapters:
                raise ValueError(
                    f"duplicate protocol fact adapter: {module_name}"
                )
            self._adapters[module_name] = adapter

    def project(
        self,
        project_id: str,
        *,
        consumer: ProtocolFactConsumer | str,
    ) -> tuple[SharedProtocolFactDTO, ...]:
        project = _required_safe_text(project_id, "project_id")
        consumer_name = str(consumer or "").strip()
        if consumer_name not in SUPPORTED_CONSUMERS:
            raise ValueError(
                "consumer must be medical_monitoring, medical_writing, or dashboard"
            )

        records: list[ConfirmedProtocolFactRecord] = []
        for owner in sorted(CONSUMER_OWNER_ALLOWLIST[consumer_name]):
            adapter = self._adapters.get(owner)
            if adapter is None:
                continue
            records.extend(adapter.read_confirmed(project))

        # If two confirmed sources disagree on the same semantic key, neither
        # value crosses the boundary. Resolution remains with the owning module.
        groups: dict[tuple[str, str], list[ConfirmedProtocolFactRecord]] = {}
        for record in records:
            if record.project_id != project:
                continue
            groups.setdefault(
                (record.fact_type, record.fact_path),
                [],
            ).append(record)

        projected: list[SharedProtocolFactDTO] = []
        for group in groups.values():
            value_hashes = {_canonical_sha256(item.value) for item in group}
            if len(value_hashes) != 1:
                continue
            for record in group:
                try:
                    projected.append(
                        _dto_from_record(record, consumer_name)
                    )
                except UnsafeProtocolFactProjection:
                    continue

        deduplicated = {item.fact_id: item for item in projected}
        return tuple(
            sorted(
                deduplicated.values(),
                key=lambda item: (
                    item.fact_type,
                    item.fact_path,
                    item.confirmed_by_module,
                    item.source_entry_id,
                    item.fact_id,
                ),
            )
        )


def _monitoring_fact_value(fact: Any) -> Any:
    payload = getattr(fact, "normalized_payload", {}) or {}
    if not isinstance(payload, Mapping):
        raise UnsafeProtocolFactProjection("monitoring fact payload is not structured")
    if "deterministic_template" in payload:
        content = payload["deterministic_template"]
    elif "value" in payload:
        content = payload["value"]
    else:
        content = getattr(fact, "source_text", "")
    value = {
        "title": getattr(fact, "title", ""),
        "content": content,
        "applicability": getattr(fact, "applicability", {}) or {},
    }
    return _safe_json_value(value)


def _study_definition_value(definition: Any, fact_path: str) -> Any:
    path = _required_safe_text(fact_path, "fact_path")
    tokens = path.split(".")
    if len(tokens) < 2 or tokens[0] not in {"framing", "picos"}:
        raise UnsafeProtocolFactProjection(
            "study fact path is outside the shared definition roots"
        )
    current = getattr(definition, tokens[0], None)
    current = _object_payload(current)
    for token in tokens[1:]:
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(path)
        current = current[token]
    if current in ("", None, [], {}):
        raise UnsafeProtocolFactProjection("study fact has no material value")
    return _safe_json_value(current)


def _validated_record(
    *,
    project_id: str,
    fact_type: str,
    fact_path: str,
    value: Any,
    source_entry_id: str,
    source_revision: str,
    locator: str,
    confirmed_by_module: str,
    confirmed_revision: str,
) -> ConfirmedProtocolFactRecord:
    if confirmed_by_module not in SUPPORTED_OWNERS:
        raise UnsafeProtocolFactProjection("unsupported confirming module")
    return ConfirmedProtocolFactRecord(
        project_id=_required_safe_text(project_id, "project_id"),
        fact_type=_required_safe_text(fact_type, "fact_type"),
        fact_path=_required_safe_text(fact_path, "fact_path"),
        value=_safe_json_value(value),
        source_entry_id=_required_safe_text(
            source_entry_id, "source_entry_id"
        ),
        source_revision=_required_safe_text(
            source_revision, "source_revision"
        ),
        locator=_required_safe_text(locator, "locator"),
        confirmed_by_module=confirmed_by_module,  # type: ignore[arg-type]
        confirmed_revision=_required_safe_text(
            confirmed_revision, "confirmed_revision"
        ),
    )


def _dto_from_record(
    record: ConfirmedProtocolFactRecord,
    consumer: str,
) -> SharedProtocolFactDTO:
    value = _safe_json_value(record.value)
    stable_payload = {
        "project_id": record.project_id,
        "fact_type": record.fact_type,
        "fact_path": record.fact_path,
        "value_sha256": _canonical_sha256(value),
        "source_entry_id": record.source_entry_id,
        "source_revision": record.source_revision,
        "locator": record.locator,
        "confirmed_by_module": record.confirmed_by_module,
        "confirmed_revision": record.confirmed_revision,
    }
    fact_id = "sharedpf_" + _canonical_sha256(stable_payload)[:32]
    return SharedProtocolFactDTO(
        fact_id=fact_id,
        project_id=_required_safe_text(record.project_id, "project_id"),
        fact_type=_required_safe_text(record.fact_type, "fact_type"),
        fact_path=_required_safe_text(record.fact_path, "fact_path"),
        value=value,
        source_entry_id=_required_safe_text(
            record.source_entry_id, "source_entry_id"
        ),
        source_revision=_required_safe_text(
            record.source_revision, "source_revision"
        ),
        locator=_required_safe_text(record.locator, "locator"),
        confirmed_by_module=record.confirmed_by_module,
        confirmed_revision=_required_safe_text(
            record.confirmed_revision, "confirmed_revision"
        ),
        consumer=consumer,  # type: ignore[arg-type]
    )


def _object_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    return value


def _safe_json_value(value: Any) -> Any:
    value = _object_payload(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if _contains_local_path(value):
            raise UnsafeProtocolFactProjection(
                "local filesystem path cannot enter shared protocol facts"
            )
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _safe_json_value(value.value)
    if isinstance(value, Mapping):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).strip()
            lowered = normalized_key.lower()
            if (
                not normalized_key
                or lowered in _FORBIDDEN_VALUE_KEYS
                or lowered.startswith("internal_")
                or lowered.endswith("_prompt")
                or lowered.endswith("_log")
                or lowered.endswith("_trace")
            ):
                raise UnsafeProtocolFactProjection(
                    "internal execution metadata cannot enter shared protocol facts"
                )
            projected[normalized_key] = _safe_json_value(item)
        return projected
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item) for item in value]
    raise UnsafeProtocolFactProjection(
        f"unsupported shared protocol fact value type: {type(value).__name__}"
    )


def _required_safe_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise UnsafeProtocolFactProjection(f"{field_name} is required")
    if _contains_local_path(text):
        raise UnsafeProtocolFactProjection(
            f"{field_name} contains a local filesystem path"
        )
    return text


def _contains_local_path(value: str) -> bool:
    return bool(_LOCAL_PATH_RE.search(str(value or "")))


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _safe_json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_clone(value: Any) -> Any:
    return json.loads(
        json.dumps(
            _safe_json_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
