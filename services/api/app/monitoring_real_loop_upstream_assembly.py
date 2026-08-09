"""Read-only assembly of the five real-loop upstream evidence gates.

This module is deliberately narrower than readiness assessment.  It accepts
source-labelled evidence rows and derives prerequisite booleans only from an
explicit ``proven`` status.  ``fresh`` or ``blocked`` evidence is useful for
audit continuity, but it can never be coerced into a release decision here.
The module does not read files, call providers, start a runtime, or grant any
authority; a separate revalidation boundary must establish the status supplied
by a caller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .monitoring_real_loop_readiness import (
    REAL_LOOP_UPSTREAM_GATE_NAMES,
    RealLoopGateInput,
)


REAL_LOOP_UPSTREAM_EVIDENCE_KINDS = {
    "b6_approved": "b6_review_gate",
    "approved_input_ready": "approved_input_source_binding",
    "source_token_revalidated": "source_token_evidence_revalidation",
    "aggregate_cas_complete": "aggregate_cas_revalidation",
    "runtime_identity_verified": "runtime_identity_revalidation",
}
REAL_LOOP_UPSTREAM_EVIDENCE_STATUSES = {
    "proven",
    "fresh",
    "blocked",
    "not_proven",
    "missing",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class RealLoopUpstreamAssemblyError(ValueError):
    """Raised when an assembly report violates its own structural contract."""


class RealLoopUpstreamAssemblyIssueCode(str, Enum):
    ROW_INVALID = "row_invalid"
    GATE_SET_MISMATCH = "gate_set_mismatch"
    GATE_DUPLICATE = "gate_duplicate"
    GATE_UNKNOWN = "gate_unknown"
    FIELD_INVALID = "field_invalid"
    EVIDENCE_KIND_MISMATCH = "evidence_kind_mismatch"
    EVIDENCE_STATUS_INVALID = "evidence_status_invalid"
    EVIDENCE_REF_INVALID = "evidence_ref_invalid"
    EVIDENCE_HASH_INVALID = "evidence_hash_invalid"
    EVIDENCE_PAIR_INCOMPLETE = "evidence_pair_incomplete"
    EVIDENCE_REF_DUPLICATE = "evidence_ref_duplicate"
    EVIDENCE_HASH_DUPLICATE = "evidence_hash_duplicate"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RealLoopUpstreamAssemblyError(
            "upstream assembly evidence must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


@dataclass(frozen=True)
class RealLoopUpstreamEvidence:
    """One source-labelled observation for a canonical upstream prerequisite."""

    gate: str
    evidence_kind: str
    evidence_ref: str = ""
    evidence_sha256: str = ""
    status: str = "missing"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RealLoopUpstreamEvidence":
        """Build a row without coercing malformed values into valid evidence."""

        return cls(
            gate=value.get("gate", ""),  # type: ignore[arg-type]
            evidence_kind=value.get("evidence_kind", ""),  # type: ignore[arg-type]
            evidence_ref=value.get("evidence_ref", ""),  # type: ignore[arg-type]
            evidence_sha256=value.get("evidence_sha256", ""),  # type: ignore[arg-type]
            status=value.get("status", ""),  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "gate": self.gate,
            "evidence_kind": self.evidence_kind,
            "evidence_ref": self.evidence_ref,
            "evidence_sha256": self.evidence_sha256,
            "status": self.status,
        }


@dataclass(frozen=True)
class RealLoopUpstreamAssemblyIssue:
    code: RealLoopUpstreamAssemblyIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise RealLoopUpstreamAssemblyError(
                "assembly issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopUpstreamAssemblyReport:
    """A valid row assembly; it never asserts runtime or medical authority."""

    status: str
    gate_input: RealLoopGateInput
    evidence_rows: tuple[RealLoopUpstreamEvidence, ...]
    issues: tuple[RealLoopUpstreamAssemblyIssue, ...] = ()
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.status not in {"assembled", "blocked"}:
            raise RealLoopUpstreamAssemblyError("invalid upstream assembly status")
        if not isinstance(self.gate_input, RealLoopGateInput):
            raise RealLoopUpstreamAssemblyError("gate_input has an invalid type")
        rows = tuple(self.evidence_rows)
        if any(not isinstance(row, RealLoopUpstreamEvidence) for row in rows):
            raise RealLoopUpstreamAssemblyError("evidence_rows contain an invalid value")
        issues = tuple(self.issues)
        if any(not isinstance(issue, RealLoopUpstreamAssemblyIssue) for issue in issues):
            raise RealLoopUpstreamAssemblyError("issues contain an invalid value")
        expected_status = "assembled" if not issues else "blocked"
        if self.status != expected_status:
            raise RealLoopUpstreamAssemblyError(
                "assembly status does not match issue state"
            )
        object.__setattr__(self, "evidence_rows", rows)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "gate_input": {
                "b6_approved": self.gate_input.b6_approved,
                "approved_input_ready": self.gate_input.approved_input_ready,
                "source_token_revalidated": self.gate_input.source_token_revalidated,
                "aggregate_cas_complete": self.gate_input.aggregate_cas_complete,
                "runtime_identity_verified": self.gate_input.runtime_identity_verified,
                "b6_evidence_sha256": self.gate_input.b6_evidence_sha256,
                "approved_input_evidence_sha256": self.gate_input.approved_input_evidence_sha256,
                "source_token_evidence_sha256": self.gate_input.source_token_evidence_sha256,
                "aggregate_cas_evidence_sha256": self.gate_input.aggregate_cas_evidence_sha256,
                "runtime_identity_evidence_sha256": self.gate_input.runtime_identity_evidence_sha256,
                "b6_evidence_ref": self.gate_input.b6_evidence_ref,
                "approved_input_evidence_ref": self.gate_input.approved_input_evidence_ref,
                "source_token_evidence_ref": self.gate_input.source_token_evidence_ref,
                "aggregate_cas_evidence_ref": self.gate_input.aggregate_cas_evidence_ref,
                "runtime_identity_evidence_ref": self.gate_input.runtime_identity_evidence_ref,
            },
            "evidence_rows": [row.to_dict() for row in self.evidence_rows],
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
            "runtime_activation_permitted": False,
            "provider_call_permitted": False,
            "write_permitted": False,
        }


def _issue(
    issues: list[RealLoopUpstreamAssemblyIssue],
    code: RealLoopUpstreamAssemblyIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(RealLoopUpstreamAssemblyIssue(code, subject, detail))


def assess_real_loop_upstream_assembly(
    rows: Iterable[RealLoopUpstreamEvidence | Mapping[str, Any]],
) -> RealLoopUpstreamAssemblyReport:
    """Assemble strict upstream gates from source-labelled evidence rows.

    ``proven`` is the only status that sets a gate boolean.  Every other known
    status remains false, even when its evidence ref/hash pair is valid and
    preserved for audit continuity.
    """

    issues: list[RealLoopUpstreamAssemblyIssue] = []
    candidates: dict[str, RealLoopUpstreamEvidence] = {}
    invalid_gates: set[str] = set()
    observed_gates: list[str] = []
    for index, raw_row in enumerate(tuple(rows)):
        subject = f"row[{index}]"
        if isinstance(raw_row, RealLoopUpstreamEvidence):
            row = raw_row
        elif isinstance(raw_row, Mapping):
            row = RealLoopUpstreamEvidence.from_mapping(raw_row)
        else:
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.ROW_INVALID,
                subject,
                "each evidence row must be RealLoopUpstreamEvidence or an object mapping",
            )
            continue
        gate = _text(row.gate)
        if not gate:
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.FIELD_INVALID,
                subject,
                "gate must be a non-empty string",
            )
            continue
        observed_gates.append(gate)
        if gate not in REAL_LOOP_UPSTREAM_GATE_NAMES:
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.GATE_UNKNOWN,
                gate,
                "gate is outside the five canonical real-loop upstream prerequisites",
            )
            continue
        if gate in candidates or gate in invalid_gates:
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.GATE_DUPLICATE,
                gate,
                "exactly one source evidence row is allowed per prerequisite",
            )
            candidates.pop(gate, None)
            invalid_gates.add(gate)
            continue
        kind = _text(row.evidence_kind)
        evidence_ref = _text(row.evidence_ref)
        evidence_hash = (
            row.evidence_sha256 if isinstance(row.evidence_sha256, str) else ""
        )
        status = _text(row.status)
        row_valid = True
        for field_name, value in (
            ("evidence_kind", row.evidence_kind),
            ("evidence_ref", row.evidence_ref),
            ("evidence_sha256", row.evidence_sha256),
            ("status", row.status),
        ):
            if not isinstance(value, str):
                _issue(
                    issues,
                    RealLoopUpstreamAssemblyIssueCode.FIELD_INVALID,
                    gate,
                    f"{field_name} must be a string",
                )
                row_valid = False
        if kind != REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[gate]:
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.EVIDENCE_KIND_MISMATCH,
                gate,
                f"expected evidence_kind={REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[gate]}",
            )
            row_valid = False
        if status not in REAL_LOOP_UPSTREAM_EVIDENCE_STATUSES:
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.EVIDENCE_STATUS_INVALID,
                gate,
                "status must be proven, fresh, blocked, not_proven or missing",
            )
            row_valid = False
        if evidence_ref and not _SAFE_REF_RE.fullmatch(evidence_ref):
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.EVIDENCE_REF_INVALID,
                gate,
                "evidence_ref must be one bounded opaque identifier, not a path",
            )
            row_valid = False
        if evidence_hash and not _SHA256_RE.fullmatch(evidence_hash):
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.EVIDENCE_HASH_INVALID,
                gate,
                "evidence_sha256 must be a lowercase SHA-256",
            )
            row_valid = False
        if bool(evidence_ref) != bool(evidence_hash):
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.EVIDENCE_PAIR_INCOMPLETE,
                gate,
                "evidence_ref and evidence_sha256 must be supplied together",
            )
            row_valid = False
        if status != "missing" and not evidence_ref:
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.EVIDENCE_PAIR_INCOMPLETE,
                gate,
                "non-missing evidence status requires an explicit ref/hash pair",
            )
            row_valid = False
        if status == "proven" and not evidence_ref:
            _issue(
                issues,
                RealLoopUpstreamAssemblyIssueCode.EVIDENCE_PAIR_INCOMPLETE,
                gate,
                "proven prerequisite requires an explicit ref/hash pair",
            )
            row_valid = False
        if row_valid:
            candidates[gate] = RealLoopUpstreamEvidence(
                gate=gate,
                evidence_kind=kind,
                evidence_ref=evidence_ref,
                evidence_sha256=evidence_hash,
                status=status,
            )
        else:
            invalid_gates.add(gate)

    observed_set = set(observed_gates)
    expected_set = set(REAL_LOOP_UPSTREAM_GATE_NAMES)
    if observed_set != expected_set:
        _issue(
            issues,
            RealLoopUpstreamAssemblyIssueCode.GATE_SET_MISMATCH,
            "gate_set",
            f"required={sorted(expected_set)}, observed={sorted(observed_set)}",
        )

    ref_owners: dict[str, list[str]] = {}
    hash_owners: dict[str, list[str]] = {}
    for gate, row in candidates.items():
        if row.evidence_ref:
            ref_owners.setdefault(row.evidence_ref, []).append(gate)
        if row.evidence_sha256:
            hash_owners.setdefault(row.evidence_sha256, []).append(gate)
    for value, owners in ref_owners.items():
        if len(owners) > 1:
            for gate in owners:
                _issue(
                    issues,
                    RealLoopUpstreamAssemblyIssueCode.EVIDENCE_REF_DUPLICATE,
                    gate,
                    f"evidence_ref is already used by {owners[0]}; one artifact ref cannot prove two prerequisites",
                )
                invalid_gates.add(gate)
    for value, owners in hash_owners.items():
        if len(owners) > 1:
            for gate in owners:
                _issue(
                    issues,
                    RealLoopUpstreamAssemblyIssueCode.EVIDENCE_HASH_DUPLICATE,
                    gate,
                    f"evidence_sha256 is already used by {owners[0]}; one artifact cannot prove two prerequisites",
                )
                invalid_gates.add(gate)

    valid_rows = tuple(
        candidates[gate]
        for gate in REAL_LOOP_UPSTREAM_GATE_NAMES
        if gate in candidates and gate not in invalid_gates
    )
    rows_by_gate = {row.gate: row for row in valid_rows}

    def _row_values(gate: str) -> tuple[bool, str, str]:
        row = rows_by_gate.get(gate)
        if row is None:
            return False, "", ""
        return row.status == "proven", row.evidence_sha256, row.evidence_ref

    b6, b6_hash, b6_ref = _row_values("b6_approved")
    approved, approved_hash, approved_ref = _row_values("approved_input_ready")
    source_token, source_token_hash, source_token_ref = _row_values(
        "source_token_revalidated"
    )
    cas, cas_hash, cas_ref = _row_values("aggregate_cas_complete")
    runtime, runtime_hash, runtime_ref = _row_values("runtime_identity_verified")
    gate_input = RealLoopGateInput(
        b6_approved=b6,
        approved_input_ready=approved,
        source_token_revalidated=source_token,
        aggregate_cas_complete=cas,
        runtime_identity_verified=runtime,
        b6_evidence_sha256=b6_hash,
        approved_input_evidence_sha256=approved_hash,
        source_token_evidence_sha256=source_token_hash,
        aggregate_cas_evidence_sha256=cas_hash,
        runtime_identity_evidence_sha256=runtime_hash,
        b6_evidence_ref=b6_ref,
        approved_input_evidence_ref=approved_ref,
        source_token_evidence_ref=source_token_ref,
        aggregate_cas_evidence_ref=cas_ref,
        runtime_identity_evidence_ref=runtime_ref,
    )
    return RealLoopUpstreamAssemblyReport(
        status="assembled" if not issues else "blocked",
        gate_input=gate_input,
        evidence_rows=valid_rows,
        issues=tuple(issues),
    )


__all__ = [
    "REAL_LOOP_UPSTREAM_EVIDENCE_KINDS",
    "REAL_LOOP_UPSTREAM_EVIDENCE_STATUSES",
    "RealLoopUpstreamAssemblyError",
    "RealLoopUpstreamAssemblyIssue",
    "RealLoopUpstreamAssemblyIssueCode",
    "RealLoopUpstreamAssemblyReport",
    "RealLoopUpstreamEvidence",
    "assess_real_loop_upstream_assembly",
]
