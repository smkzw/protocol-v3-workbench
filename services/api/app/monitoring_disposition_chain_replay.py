"""Read-only append-only disposition-chain replay for Phase B.

The B6 gate requires the historical disposition chain to be replayed into the
canonical aggregate before any migration.  This module replays only explicit
event metadata in memory.  It does not load a database, mutate an aggregate,
or turn a successful replay into approval.
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


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class MonitoringDispositionChainReplayError(ValueError):
    """Raised when chain replay input is malformed or duplicated."""


class DispositionChainIssueCode(str, Enum):
    CHAIN_GAP = "disposition_chain_gap"
    DUPLICATE_EVENT = "duplicate_disposition_event"
    EXPECTED_STATE_DRIFT = "aggregate_state_drift"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise MonitoringDispositionChainReplayError(
            "disposition replay payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise MonitoringDispositionChainReplayError(f"{field_name} is required")
    if not _SAFE_ID_RE.fullmatch(text):
        raise MonitoringDispositionChainReplayError(
            f"{field_name} contains unsupported characters"
        )
    return text


def _state(value: Any, field_name: str) -> str:
    text = _required(value, field_name)
    try:
        return MedicalRiskDispositionState(text).value
    except ValueError as exc:
        raise MonitoringDispositionChainReplayError(
            f"{field_name} is not a canonical disposition state"
        ) from exc


def _utc(value: Any, field_name: str) -> datetime:
    text = "" if value is None else str(value).strip()
    if not text:
        raise MonitoringDispositionChainReplayError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MonitoringDispositionChainReplayError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise MonitoringDispositionChainReplayError(
            f"{field_name} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class MonitoringDispositionChainEvent:
    """One immutable append-only state transition."""

    record_id: str
    previous_state: str
    new_state: str
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "record_id", _required(self.record_id, "event.record_id")
        )
        object.__setattr__(
            self,
            "previous_state",
            _state(self.previous_state, "event.previous_state"),
        )
        object.__setattr__(self, "new_state", _state(self.new_state, "event.new_state"))
        parsed = _utc(self.created_at, "event.created_at")
        object.__setattr__(self, "created_at", parsed.isoformat())

    def to_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class MonitoringDispositionChainCase:
    """One risk-instance chain and its optional aggregate state snapshot."""

    project_id: str
    risk_instance_id: str
    events: tuple[MonitoringDispositionChainEvent, ...]
    expected_aggregate_state: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "project_id", _required(self.project_id, "case.project_id")
        )
        object.__setattr__(
            self,
            "risk_instance_id",
            _required(self.risk_instance_id, "case.risk_instance_id"),
        )
        events = tuple(self.events)
        if not events:
            raise MonitoringDispositionChainReplayError("case.events must not be empty")
        if any(
            not isinstance(item, MonitoringDispositionChainEvent) for item in events
        ):
            raise MonitoringDispositionChainReplayError(
                "case.events must contain MonitoringDispositionChainEvent values"
            )
        expected = str(self.expected_aggregate_state or "").strip()
        if expected:
            expected = _state(expected, "case.expected_aggregate_state")
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "expected_aggregate_state", expected)


@dataclass(frozen=True)
class MonitoringDispositionChainIssue:
    code: DispositionChainIssueCode
    project_id: str
    risk_instance_id: str
    record_id: str
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "project_id", _required(self.project_id, "issue.project_id")
        )
        object.__setattr__(
            self,
            "risk_instance_id",
            _required(self.risk_instance_id, "issue.risk_instance_id"),
        )
        object.__setattr__(
            self, "record_id", _required(self.record_id, "issue.record_id")
        )
        detail = str(self.detail or "").strip()
        if not detail:
            raise MonitoringDispositionChainReplayError("issue.detail is required")
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "project_id": self.project_id,
            "risk_instance_id": self.risk_instance_id,
            "record_id": self.record_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MonitoringDispositionChainReplay:
    project_id: str
    risk_instance_id: str
    initial_state: str
    final_state: str
    event_ids: tuple[str, ...]
    issues: tuple[MonitoringDispositionChainIssue, ...]
    replay_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "project_id", _required(self.project_id, "replay.project_id")
        )
        object.__setattr__(
            self,
            "risk_instance_id",
            _required(self.risk_instance_id, "replay.risk_instance_id"),
        )
        object.__setattr__(
            self, "initial_state", _state(self.initial_state, "replay.initial_state")
        )
        object.__setattr__(
            self, "final_state", _state(self.final_state, "replay.final_state")
        )
        event_ids = tuple(
            _required(value, "replay.event_ids item") for value in self.event_ids
        )
        if len(event_ids) != len(set(event_ids)):
            raise MonitoringDispositionChainReplayError(
                "replay.event_ids must not repeat"
            )
        issues = tuple(self.issues)
        if any(
            not isinstance(item, MonitoringDispositionChainIssue) for item in issues
        ):
            raise MonitoringDispositionChainReplayError(
                "replay.issues contain an invalid issue"
            )
        object.__setattr__(self, "event_ids", event_ids)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "replay_sha256", _digest(self._payload()))

    @property
    def replay_complete(self) -> bool:
        return not self.issues

    def _payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "risk_instance_id": self.risk_instance_id,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "event_ids": list(self.event_ids),
            "issues": [item.to_dict() for item in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "replay_complete": self.replay_complete,
            "replay_sha256": self.replay_sha256,
        }


def replay_monitoring_disposition_chain(
    case: MonitoringDispositionChainCase,
) -> MonitoringDispositionChainReplay:
    """Replay a chain in memory from the canonical pending-review state."""

    if not isinstance(case, MonitoringDispositionChainCase):
        raise MonitoringDispositionChainReplayError(
            "case must be a MonitoringDispositionChainCase"
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
    issues: list[MonitoringDispositionChainIssue] = []
    event_ids: list[str] = []
    seen_payloads: dict[str, tuple[str, str, str]] = {}
    current_state = MedicalRiskDispositionState.PENDING_REVIEW.value
    for event in ordered:
        payload = (event.previous_state, event.new_state, event.created_at)
        if event.record_id in seen_payloads:
            issues.append(
                MonitoringDispositionChainIssue(
                    code=DispositionChainIssueCode.DUPLICATE_EVENT,
                    project_id=case.project_id,
                    risk_instance_id=case.risk_instance_id,
                    record_id=event.record_id,
                    detail=(
                        "event record_id appears more than once with "
                        + (
                            "the same payload"
                            if seen_payloads[event.record_id] == payload
                            else "different payload"
                        )
                    ),
                )
            )
        else:
            seen_payloads[event.record_id] = payload
            event_ids.append(event.record_id)
        if event.previous_state != current_state:
            issues.append(
                MonitoringDispositionChainIssue(
                    code=DispositionChainIssueCode.CHAIN_GAP,
                    project_id=case.project_id,
                    risk_instance_id=case.risk_instance_id,
                    record_id=event.record_id,
                    detail=(
                        f"expected previous_state={current_state!r}, "
                        f"found {event.previous_state!r}"
                    ),
                )
            )
        current_state = event.new_state
    if case.expected_aggregate_state and current_state != case.expected_aggregate_state:
        issues.append(
            MonitoringDispositionChainIssue(
                code=DispositionChainIssueCode.EXPECTED_STATE_DRIFT,
                project_id=case.project_id,
                risk_instance_id=case.risk_instance_id,
                record_id=event_ids[-1],
                detail=(
                    f"expected aggregate state={case.expected_aggregate_state!r} differs from "
                    f"replayed state={current_state!r}"
                ),
            )
        )
    return MonitoringDispositionChainReplay(
        project_id=case.project_id,
        risk_instance_id=case.risk_instance_id,
        initial_state=MedicalRiskDispositionState.PENDING_REVIEW.value,
        final_state=current_state,
        event_ids=tuple(event_ids),
        issues=tuple(issues),
    )


@dataclass(frozen=True)
class MonitoringDispositionChainReplayReport:
    replays: tuple[MonitoringDispositionChainReplay, ...]
    aggregate_write_permitted: bool = False
    migration_ready: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        replays = tuple(self.replays)
        if not replays:
            raise MonitoringDispositionChainReplayError(
                "replay report must contain a replay"
            )
        if any(
            not isinstance(item, MonitoringDispositionChainReplay) for item in replays
        ):
            raise MonitoringDispositionChainReplayError(
                "replay report contains an invalid replay"
            )
        keys = tuple((item.project_id, item.risk_instance_id) for item in replays)
        if len(keys) != len(set(keys)):
            raise MonitoringDispositionChainReplayError(
                "replay report must not repeat project/risk_instance_id"
            )
        if self.aggregate_write_permitted or self.migration_ready:
            raise MonitoringDispositionChainReplayError(
                "chain replay report cannot grant aggregate or migration authority"
            )
        ordered = tuple(
            sorted(replays, key=lambda item: (item.project_id, item.risk_instance_id))
        )
        object.__setattr__(self, "replays", ordered)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    @property
    def replay_complete(self) -> bool:
        return all(item.replay_complete for item in self.replays)

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
            "replay_complete": self.replay_complete,
            "issue_count": self.issue_count,
            "report_sha256": self.report_sha256,
        }


def build_monitoring_disposition_chain_replay_report(
    cases: Sequence[MonitoringDispositionChainCase],
) -> MonitoringDispositionChainReplayReport:
    """Replay distinct risk-instance chains without persistence or mutation."""

    normalized = tuple(cases)
    if any(not isinstance(case, MonitoringDispositionChainCase) for case in normalized):
        raise MonitoringDispositionChainReplayError(
            "replay cases must contain MonitoringDispositionChainCase values"
        )
    return MonitoringDispositionChainReplayReport(
        replays=tuple(replay_monitoring_disposition_chain(case) for case in normalized)
    )


__all__ = [
    "DispositionChainIssueCode",
    "MonitoringDispositionChainCase",
    "MonitoringDispositionChainEvent",
    "MonitoringDispositionChainIssue",
    "MonitoringDispositionChainReplay",
    "MonitoringDispositionChainReplayError",
    "MonitoringDispositionChainReplayReport",
    "build_monitoring_disposition_chain_replay_report",
    "replay_monitoring_disposition_chain",
]
