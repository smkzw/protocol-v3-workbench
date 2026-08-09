"""Conservative human-readable semantics for real-loop upstream evidence.

Freshness, reviewer-decision completeness, content/replay resolution and
signature verification are separate observations.  This module deliberately
does not collapse any of them into runtime authority and does not treat a hash
or a reviewer-looking field as an e-signature.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any

from .monitoring_real_loop_readiness import REAL_LOOP_UPSTREAM_GATE_NAMES
from .monitoring_real_loop_status_mapping import (
    RealLoopStatusMappingResult,
    derive_real_loop_upstream_status,
)
from .monitoring_real_loop_upstream_assembly import REAL_LOOP_UPSTREAM_EVIDENCE_KINDS


SEMANTICS_SCHEMA_VERSION = "medical_monitoring_real_loop_evidence_semantics_v1"
SEMANTIC_FRESHNESS_STATUSES = {
    "fresh_observed",
    "blocked",
    "not_observed",
    "missing",
}
SEMANTIC_DECISION_STATUSES = {
    "complete",
    "pending",
    "blocked",
    "not_applicable",
    "missing",
}
SEMANTIC_REPLAY_STATUSES = {
    "complete",
    "incomplete",
    "not_proven",
    "blocked",
    "not_applicable",
    "missing",
}


class RealLoopEvidenceSemanticsError(ValueError):
    """Raised when a semantic observation violates its own contract."""


class RealLoopEvidenceSemanticsIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    SIGNATURE_SCHEMA_UNSUPPORTED = "signature_schema_unsupported"
    STATUS_MAPPING_ISSUE = "status_mapping_issue"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RealLoopEvidenceSemanticsError(
            "semantic evidence must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RealLoopEvidenceSemanticsIssue:
    code: RealLoopEvidenceSemanticsIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise RealLoopEvidenceSemanticsError("semantic issue subject is required")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise RealLoopEvidenceSemanticsError("semantic issue detail is required")
        object.__setattr__(self, "subject", self.subject.strip())
        object.__setattr__(self, "detail", self.detail.strip())

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopEvidenceSemanticsReport:
    gate: str
    evidence_kind: str
    derived_status: str
    freshness_status: str
    decision_status: str
    replay_status: str
    signature_status: str
    interpretation: str
    mapping_result_sha256: str
    issues: tuple[RealLoopEvidenceSemanticsIssue, ...] = ()
    schema_version: str = SEMANTICS_SCHEMA_VERSION
    semantic_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.gate not in REAL_LOOP_UPSTREAM_GATE_NAMES:
            raise RealLoopEvidenceSemanticsError("semantic gate is not canonical")
        if self.evidence_kind != REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[self.gate]:
            raise RealLoopEvidenceSemanticsError("semantic evidence kind does not match gate")
        if self.derived_status not in {"proven", "blocked", "not_proven", "missing"}:
            raise RealLoopEvidenceSemanticsError("invalid derived status")
        if self.freshness_status not in SEMANTIC_FRESHNESS_STATUSES:
            raise RealLoopEvidenceSemanticsError("invalid freshness status")
        if self.decision_status not in SEMANTIC_DECISION_STATUSES:
            raise RealLoopEvidenceSemanticsError("invalid decision status")
        if self.replay_status not in SEMANTIC_REPLAY_STATUSES:
            raise RealLoopEvidenceSemanticsError("invalid replay status")
        if self.signature_status != "not_verified":
            raise RealLoopEvidenceSemanticsError(
                "signature status cannot be promoted without a formal signature schema"
            )
        if not isinstance(self.interpretation, str) or not self.interpretation.strip():
            raise RealLoopEvidenceSemanticsError("semantic interpretation is required")
        if self.mapping_result_sha256 and (
            len(self.mapping_result_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.mapping_result_sha256)
        ):
            raise RealLoopEvidenceSemanticsError("mapping_result_sha256 must be lowercase SHA-256")
        issues = tuple(self.issues)
        if any(not isinstance(item, RealLoopEvidenceSemanticsIssue) for item in issues):
            raise RealLoopEvidenceSemanticsError("semantic issues contain an invalid value")
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "semantic_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gate": self.gate,
            "evidence_kind": self.evidence_kind,
            "derived_status": self.derived_status,
            "freshness_status": self.freshness_status,
            "decision_status": self.decision_status,
            "replay_status": self.replay_status,
            "signature_status": self.signature_status,
            "interpretation": self.interpretation,
            "mapping_result_sha256": self.mapping_result_sha256,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "semantic_sha256": self.semantic_sha256,
            "runtime_activation_permitted": False,
            "provider_call_permitted": False,
            "write_permitted": False,
        }


def _issue(
    code: RealLoopEvidenceSemanticsIssueCode,
    subject: str,
    detail: str,
) -> RealLoopEvidenceSemanticsIssue:
    return RealLoopEvidenceSemanticsIssue(code, subject, detail)


def _signature_marker_issue(payload: Mapping[str, Any], gate: str) -> RealLoopEvidenceSemanticsIssue | None:
    for key in ("signature_verified", "e_signature_verified", "legal_signature_verified"):
        if payload.get(key) is True:
            return _issue(
                RealLoopEvidenceSemanticsIssueCode.SIGNATURE_SCHEMA_UNSUPPORTED,
                f"{gate}.{key}",
                "a generic signature flag is not an accepted e-signature schema",
            )
    return None


def _semantic_statuses(
    gate: str,
    payload: Mapping[str, Any],
    mapped: RealLoopStatusMappingResult,
) -> tuple[str, str, str, str]:
    if mapped.status == "missing":
        return "missing", "missing", "missing", "not_verified"
    if gate == "b6_approved":
        nested = payload.get("gate")
        if not isinstance(nested, Mapping):
            return "missing", "missing", "missing", "not_verified"
        decision = "complete" if mapped.status == "proven" else "pending"
        replay = "incomplete" if nested.get("unresolved_blockers") else "not_applicable"
        return "not_observed", decision, replay, "not_verified"
    if gate == "approved_input_ready":
        nested = payload.get("current_package_observation", payload)
        if not isinstance(nested, Mapping):
            return "missing", "missing", "missing", "not_verified"
        freshness = "blocked" if nested.get("status") == "blocked" else "not_observed"
        decision = "complete" if mapped.status == "proven" else "blocked"
        replay = (
            "complete"
            if nested.get("source_manifest_replay_complete") is True
            and nested.get("source_batch_preflight_complete") is True
            else "incomplete"
        )
        return freshness, decision, replay, "not_verified"
    nested = payload.get("report")
    if not isinstance(nested, Mapping):
        return "missing", "missing", "missing", "not_verified"
    freshness = (
        "fresh_observed"
        if nested.get("status") == "fresh" and nested.get("evidence_fresh") is True
        else "blocked"
    )
    if gate == "source_token_revalidated":
        replay = (
            "complete"
            if nested.get("source_token_revalidation_status") == "proven"
            else "not_proven"
        )
    else:
        replay = "complete" if nested.get("cas_replay_complete") is True else "incomplete"
    return freshness, "not_applicable", replay, "not_verified"


def assess_real_loop_evidence_semantics(
    gate: str,
    payload: Mapping[str, Any] | None,
    *,
    payload_sha256: str = "",
) -> RealLoopEvidenceSemanticsReport:
    """Describe freshness/decision/replay/signature separately and fail closed."""

    if gate not in REAL_LOOP_UPSTREAM_GATE_NAMES:
        raise RealLoopEvidenceSemanticsError("gate is outside canonical upstream set")
    mapped = derive_real_loop_upstream_status(gate, payload, payload_sha256=payload_sha256)
    issues: list[RealLoopEvidenceSemanticsIssue] = []
    if mapped.issues:
        issues.extend(
            _issue(
                RealLoopEvidenceSemanticsIssueCode.STATUS_MAPPING_ISSUE,
                item.subject,
                item.detail,
            )
            for item in mapped.issues
        )
    if isinstance(payload, Mapping):
        marker = _signature_marker_issue(payload, gate)
        if marker is not None:
            issues.append(marker)
    freshness, decision, replay, signature = (
        _semantic_statuses(gate, payload, mapped)
        if isinstance(payload, Mapping)
        else ("missing", "missing", "missing", "not_verified")
    )
    if payload is None:
        interpretation = "no persisted payload; semantic status remains missing"
    elif gate == "source_token_revalidated" and freshness == "fresh_observed" and replay == "not_proven":
        interpretation = "freshness is observed, but source-token content proof is not proven"
    elif gate == "aggregate_cas_complete" and freshness == "fresh_observed" and replay == "incomplete":
        interpretation = "freshness is observed, but aggregate/CAS replay remains incomplete"
    elif gate == "b6_approved" and decision == "pending":
        interpretation = "engineering review rows exist, but formal reviewer decisions remain pending"
    elif gate == "approved_input_ready" and decision == "blocked":
        interpretation = "source preflight or reviewer prerequisites block approved input"
    else:
        interpretation = "semantic observations remain separate from runtime authority"
    return RealLoopEvidenceSemanticsReport(
        gate=gate,
        evidence_kind=REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[gate],
        derived_status=mapped.status,
        freshness_status=freshness,
        decision_status=decision,
        replay_status=replay,
        signature_status=signature,
        interpretation=interpretation,
        mapping_result_sha256=mapped.result_sha256,
        issues=tuple(issues),
    )


__all__ = [
    "SEMANTICS_SCHEMA_VERSION",
    "RealLoopEvidenceSemanticsError",
    "RealLoopEvidenceSemanticsIssue",
    "RealLoopEvidenceSemanticsIssueCode",
    "RealLoopEvidenceSemanticsReport",
    "assess_real_loop_evidence_semantics",
]
