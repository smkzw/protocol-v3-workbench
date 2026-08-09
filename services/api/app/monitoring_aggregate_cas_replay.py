"""Pure in-memory replay of canonical medical-risk aggregate/CAS events.

This contract is deliberately separate from persistence and from reviewer
authority.  It checks whether an explicit append-only event stream *could* be
applied to one aggregate under the canonical identity, source-revision, state,
and expected-version rules.  Missing ``expected_version`` is an observed
evidence gap; the module never derives or persists a replacement version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Sequence

from .medical_risk_authority import MedicalRiskDispositionState


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}$")


class MonitoringAggregateCasReplayError(ValueError):
    """Raised when aggregate/CAS replay evidence is malformed."""


class AggregateCasIssueCode(str, Enum):
    MISSING_EXPECTED_VERSION = "missing_expected_version"
    VERSION_CONFLICT = "aggregate_version_conflict"
    VERSION_SEQUENCE_UNPROVEN = "aggregate_version_sequence_unproven"
    IDENTITY_MISMATCH = "aggregate_identity_mismatch"
    SOURCE_REVISION_MISMATCH = "aggregate_source_revision_mismatch"
    CHAIN_GAP = "disposition_chain_gap"
    DUPLICATE_EVENT = "duplicate_event_id"
    FINAL_STATE_DRIFT = "aggregate_final_state_drift"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise MonitoringAggregateCasReplayError(
            "aggregate/CAS replay payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise MonitoringAggregateCasReplayError(f"{field_name} is required")
    if not _SAFE_ID_RE.fullmatch(text):
        raise MonitoringAggregateCasReplayError(
            f"{field_name} contains unsupported characters"
        )
    return text


def _state(value: Any, field_name: str) -> str:
    text = _required(value, field_name)
    try:
        return MedicalRiskDispositionState(text).value
    except ValueError as exc:
        raise MonitoringAggregateCasReplayError(
            f"{field_name} is not a canonical disposition state"
        ) from exc


def _utc(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = "" if value is None else str(value).strip()
        if not text:
            raise MonitoringAggregateCasReplayError(f"{field_name} is required")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MonitoringAggregateCasReplayError(
                f"{field_name} must be an ISO-8601 timestamp"
            ) from exc
    if parsed.tzinfo is None:
        raise MonitoringAggregateCasReplayError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _version(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MonitoringAggregateCasReplayError(
            f"{field_name} must be a non-negative integer or null"
        )
    return value


@dataclass(frozen=True)
class MonitoringAggregateCasEvent:
    """One immutable event input for a single aggregate replay."""

    record_id: str
    project_id: str
    risk_key: str
    risk_instance_id: str
    source_revision: str
    previous_state: str
    new_state: str
    created_at: str
    expected_version: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "record_id",
            "project_id",
            "risk_key",
            "risk_instance_id",
            "source_revision",
        ):
            object.__setattr__(
                self, name, _required(getattr(self, name), f"event.{name}")
            )
        object.__setattr__(
            self, "previous_state", _state(self.previous_state, "event.previous_state")
        )
        object.__setattr__(self, "new_state", _state(self.new_state, "event.new_state"))
        object.__setattr__(
            self, "created_at", _utc(self.created_at, "event.created_at").isoformat()
        )
        object.__setattr__(
            self,
            "expected_version",
            _version(self.expected_version, "event.expected_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "project_id": self.project_id,
            "risk_key": self.risk_key,
            "risk_instance_id": self.risk_instance_id,
            "source_revision": self.source_revision,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "created_at": self.created_at,
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True)
class MonitoringAggregateCasCase:
    """One aggregate identity and its explicit event stream."""

    project_id: str
    risk_key: str
    risk_instance_id: str
    source_revision: str
    events: tuple[MonitoringAggregateCasEvent, ...]
    initial_state: str = MedicalRiskDispositionState.PENDING_REVIEW.value
    initial_version: int = 0
    expected_final_state: str = ""

    def __post_init__(self) -> None:
        for name in ("project_id", "risk_key", "risk_instance_id", "source_revision"):
            object.__setattr__(
                self, name, _required(getattr(self, name), f"case.{name}")
            )
        object.__setattr__(
            self, "initial_state", _state(self.initial_state, "case.initial_state")
        )
        object.__setattr__(
            self,
            "initial_version",
            _version(self.initial_version, "case.initial_version"),
        )
        if self.initial_version is None:
            raise MonitoringAggregateCasReplayError("case.initial_version is required")
        events = tuple(self.events)
        if not events:
            raise MonitoringAggregateCasReplayError("case.events must not be empty")
        if any(not isinstance(item, MonitoringAggregateCasEvent) for item in events):
            raise MonitoringAggregateCasReplayError(
                "case.events must contain MonitoringAggregateCasEvent values"
            )
        expected = str(self.expected_final_state or "").strip()
        if expected:
            expected = _state(expected, "case.expected_final_state")
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "expected_final_state", expected)


@dataclass(frozen=True)
class MonitoringAggregateCasIssue:
    code: AggregateCasIssueCode
    record_id: str
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _required(self.record_id, "issue.record_id")
        )
        detail = str(self.detail or "").strip()
        if not detail:
            raise MonitoringAggregateCasReplayError("issue.detail is required")
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "record_id": self.record_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MonitoringAggregateCasReplay:
    project_id: str
    risk_key: str
    risk_instance_id: str
    initial_state: str
    final_state: str
    initial_version: int
    cas_version: int
    event_ids: tuple[str, ...]
    cas_applied_event_ids: tuple[str, ...]
    issues: tuple[MonitoringAggregateCasIssue, ...]
    replay_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("project_id", "risk_key", "risk_instance_id"):
            object.__setattr__(
                self, name, _required(getattr(self, name), f"replay.{name}")
            )
        object.__setattr__(
            self, "initial_state", _state(self.initial_state, "replay.initial_state")
        )
        object.__setattr__(
            self, "final_state", _state(self.final_state, "replay.final_state")
        )
        for name in ("initial_version", "cas_version"):
            value = _version(getattr(self, name), f"replay.{name}")
            if value is None:
                raise MonitoringAggregateCasReplayError(f"replay.{name} is required")
            object.__setattr__(self, name, value)
        event_ids = tuple(
            _required(value, "replay.event_ids item") for value in self.event_ids
        )
        applied = tuple(
            _required(value, "replay.cas_applied_event_ids item")
            for value in self.cas_applied_event_ids
        )
        if len(event_ids) != len(set(event_ids)) or len(applied) != len(set(applied)):
            raise MonitoringAggregateCasReplayError("replay event IDs must not repeat")
        if not set(applied).issubset(event_ids):
            raise MonitoringAggregateCasReplayError(
                "CAS-applied events must be replay events"
            )
        issues = tuple(self.issues)
        if any(not isinstance(item, MonitoringAggregateCasIssue) for item in issues):
            raise MonitoringAggregateCasReplayError(
                "replay.issues contain an invalid issue"
            )
        object.__setattr__(self, "event_ids", event_ids)
        object.__setattr__(self, "cas_applied_event_ids", applied)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "replay_sha256", _digest(self._payload()))

    @property
    def metadata_chain_complete(self) -> bool:
        return not any(
            issue.code
            in {
                AggregateCasIssueCode.IDENTITY_MISMATCH,
                AggregateCasIssueCode.SOURCE_REVISION_MISMATCH,
                AggregateCasIssueCode.CHAIN_GAP,
                AggregateCasIssueCode.DUPLICATE_EVENT,
                AggregateCasIssueCode.FINAL_STATE_DRIFT,
            }
            for issue in self.issues
        )

    @property
    def cas_replay_complete(self) -> bool:
        return (
            self.metadata_chain_complete
            and not any(
                issue.code
                in {
                    AggregateCasIssueCode.MISSING_EXPECTED_VERSION,
                    AggregateCasIssueCode.VERSION_CONFLICT,
                    AggregateCasIssueCode.VERSION_SEQUENCE_UNPROVEN,
                }
                for issue in self.issues
            )
            and len(self.cas_applied_event_ids) == len(self.event_ids)
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "risk_key": self.risk_key,
            "risk_instance_id": self.risk_instance_id,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "initial_version": self.initial_version,
            "cas_version": self.cas_version,
            "event_ids": list(self.event_ids),
            "cas_applied_event_ids": list(self.cas_applied_event_ids),
            "issues": [item.to_dict() for item in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "metadata_chain_complete": self.metadata_chain_complete,
            "cas_replay_complete": self.cas_replay_complete,
            "replay_sha256": self.replay_sha256,
        }


def replay_monitoring_aggregate_cas(
    case: MonitoringAggregateCasCase,
) -> MonitoringAggregateCasReplay:
    """Replay one aggregate in memory without persistence or authority."""

    if not isinstance(case, MonitoringAggregateCasCase):
        raise MonitoringAggregateCasReplayError(
            "case must be a MonitoringAggregateCasCase"
        )
    ordered = tuple(
        sorted(
            case.events,
            key=lambda item: (
                _utc(item.created_at, "event.created_at"),
                item.record_id,
            ),
        )
    )
    issues: list[MonitoringAggregateCasIssue] = []
    event_ids: list[str] = []
    applied_ids: list[str] = []
    seen: dict[str, tuple[Any, ...]] = {}
    state = case.initial_state
    version = case.initial_version
    version_known = True
    for event in ordered:
        state_before = state
        fingerprint = (
            event.project_id,
            event.risk_key,
            event.risk_instance_id,
            event.source_revision,
            event.previous_state,
            event.new_state,
            event.created_at,
            event.expected_version,
        )
        if event.record_id in seen:
            issues.append(
                MonitoringAggregateCasIssue(
                    AggregateCasIssueCode.DUPLICATE_EVENT,
                    event.record_id,
                    "event record_id appears more than once with "
                    + (
                        "the same payload"
                        if seen[event.record_id] == fingerprint
                        else "different payload"
                    ),
                )
            )
        else:
            seen[event.record_id] = fingerprint
            event_ids.append(event.record_id)

        identity_ok = (
            event.project_id == case.project_id
            and event.risk_key == case.risk_key
            and event.risk_instance_id == case.risk_instance_id
        )
        if not identity_ok:
            issues.append(
                MonitoringAggregateCasIssue(
                    AggregateCasIssueCode.IDENTITY_MISMATCH,
                    event.record_id,
                    "event identity does not match the aggregate case",
                )
            )
        if event.source_revision != case.source_revision:
            issues.append(
                MonitoringAggregateCasIssue(
                    AggregateCasIssueCode.SOURCE_REVISION_MISMATCH,
                    event.record_id,
                    "event source_revision does not match the aggregate case",
                )
            )
        if event.previous_state != state_before:
            issues.append(
                MonitoringAggregateCasIssue(
                    AggregateCasIssueCode.CHAIN_GAP,
                    event.record_id,
                    f"expected previous_state={state_before!r}, found {event.previous_state!r}",
                )
            )
        if event.expected_version is None:
            issues.append(
                MonitoringAggregateCasIssue(
                    AggregateCasIssueCode.MISSING_EXPECTED_VERSION,
                    event.record_id,
                    "B4 metadata does not carry an observed expected_version; no version was inferred",
                )
            )
            version_known = False
        elif not version_known:
            issues.append(
                MonitoringAggregateCasIssue(
                    AggregateCasIssueCode.VERSION_SEQUENCE_UNPROVEN,
                    event.record_id,
                    "a prior expected_version was missing, so the CAS sequence cannot be proven",
                )
            )
        elif event.expected_version != version:
            issues.append(
                MonitoringAggregateCasIssue(
                    AggregateCasIssueCode.VERSION_CONFLICT,
                    event.record_id,
                    f"expected_version={event.expected_version}, actual_version={version}",
                )
            )
        if (
            identity_ok
            and event.source_revision == case.source_revision
            and event.previous_state == state_before
        ):
            state = event.new_state
        if (
            event.record_id not in applied_ids
            and identity_ok
            and event.source_revision == case.source_revision
            and event.previous_state == state_before
            and event.expected_version is not None
            and version_known
            and event.expected_version == version
        ):
            applied_ids.append(event.record_id)
            version += 1

    if case.expected_final_state and state != case.expected_final_state:
        issues.append(
            MonitoringAggregateCasIssue(
                AggregateCasIssueCode.FINAL_STATE_DRIFT,
                event_ids[-1],
                f"expected final state={case.expected_final_state!r} differs from replayed state={state!r}",
            )
        )
    return MonitoringAggregateCasReplay(
        project_id=case.project_id,
        risk_key=case.risk_key,
        risk_instance_id=case.risk_instance_id,
        initial_state=case.initial_state,
        final_state=state,
        initial_version=case.initial_version,
        cas_version=version,
        event_ids=tuple(event_ids),
        cas_applied_event_ids=tuple(applied_ids),
        issues=tuple(issues),
    )


@dataclass(frozen=True)
class MonitoringAggregateCasReplayReport:
    replays: tuple[MonitoringAggregateCasReplay, ...]
    aggregate_write_permitted: bool = False
    migration_ready: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("aggregate_write_permitted", "migration_ready"):
            if not isinstance(getattr(self, field_name), bool):
                raise MonitoringAggregateCasReplayError(
                    f"{field_name} must be boolean"
                )
        replays = tuple(self.replays)
        if not replays or any(
            not isinstance(item, MonitoringAggregateCasReplay) for item in replays
        ):
            raise MonitoringAggregateCasReplayError(
                "replay report must contain valid replays"
            )
        keys = tuple((item.project_id, item.risk_instance_id) for item in replays)
        if len(keys) != len(set(keys)):
            raise MonitoringAggregateCasReplayError(
                "replay report must not repeat aggregate identities"
            )
        if self.aggregate_write_permitted or self.migration_ready:
            raise MonitoringAggregateCasReplayError(
                "replay report cannot grant aggregate or migration authority"
            )
        object.__setattr__(
            self,
            "replays",
            tuple(
                sorted(
                    replays, key=lambda item: (item.project_id, item.risk_instance_id)
                )
            ),
        )
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    @property
    def metadata_chain_complete(self) -> bool:
        return all(item.metadata_chain_complete for item in self.replays)

    @property
    def cas_replay_complete(self) -> bool:
        return all(item.cas_replay_complete for item in self.replays)

    @property
    def issue_count(self) -> int:
        return sum(len(item.issues) for item in self.replays)

    def _payload(self) -> dict[str, Any]:
        return {
            "replays": [item.to_dict() for item in self.replays],
            "aggregate_write_permitted": self.aggregate_write_permitted,
            "migration_ready": self.migration_ready,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "metadata_chain_complete": self.metadata_chain_complete,
            "cas_replay_complete": self.cas_replay_complete,
            "issue_count": self.issue_count,
            "report_sha256": self.report_sha256,
        }


def build_monitoring_aggregate_cas_replay_report(
    cases: Sequence[MonitoringAggregateCasCase],
) -> MonitoringAggregateCasReplayReport:
    normalized = tuple(cases)
    if any(not isinstance(case, MonitoringAggregateCasCase) for case in normalized):
        raise MonitoringAggregateCasReplayError(
            "replay cases must contain MonitoringAggregateCasCase values"
        )
    return MonitoringAggregateCasReplayReport(
        replays=tuple(replay_monitoring_aggregate_cas(case) for case in normalized)
    )


__all__ = [
    "AggregateCasIssueCode",
    "MonitoringAggregateCasCase",
    "MonitoringAggregateCasEvent",
    "MonitoringAggregateCasIssue",
    "MonitoringAggregateCasReplay",
    "MonitoringAggregateCasReplayError",
    "MonitoringAggregateCasReplayReport",
    "build_monitoring_aggregate_cas_replay_report",
    "replay_monitoring_aggregate_cas",
]
