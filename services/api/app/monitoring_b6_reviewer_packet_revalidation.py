"""Read-only freshness validation for the persisted B6 reviewer packet.

The B6 packet is a reviewer handoff, not an approval record.  This contract
reopens the packet, the current formal provenance package, the current B6/C14
gate payloads, and every declared package source file through an explicit
bytes/SHA-256 observation.  A packet is fresh only when all of those bindings
agree.  The result never creates reviewer outcomes and never grants medical,
aggregate/CAS, migration, activation, runtime, or write authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


B6_REVIEWER_PACKET_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_b6_reviewer_packet_revalidation_v1"
)
PACKET_SCHEMA_VERSION = "medical_monitoring.b6.review_packet.v1"
PACKET_PATH = (
    "records/active_slices/medical_monitoring_b6_reviewer_packet_20260802/"
    "B6_REVIEW_PACKET.json"
)
PACKAGE_PATH = (
    "records/active_slices/medical_monitoring_formal_reviewer_provenance_package_20260802/"
    "B6_FORMAL_REVIEWER_PROVENANCE_PACKAGE.json"
)
B6_GATE_PATH = (
    "runs/execution/medical_monitoring_phase_b6_review_gate_20260801/"
    "B6_REVIEW_OUTCOME_GATE.json"
)
C14_GATE_PATH = (
    "runs/execution/medical_monitoring_phase_c14_b6_activation_gate_20260802/"
    "B6_TO_C13_ACTIVATION_GATE_REPORT.json"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_B6_STATE_FIELDS = (
    "status",
    "candidate_count",
    "outcome_count",
    "missing_candidate_record_ids",
    "pending_candidate_record_ids",
    "rejected_candidate_record_ids",
    "accepted_review_ids",
    "unresolved_blockers",
    "migration_ready",
    "write_permitted",
)
_B6_PACKAGE_STATE_FIELDS = _B6_STATE_FIELDS
_C14_STATE_FIELDS = (
    "status",
    "b6_status",
    "candidate_count",
    "outcome_count",
    "c13_row_count",
    "c13_blocked_row_count",
    "unresolved_blockers",
    "review_required",
    "migration_ready",
    "write_permitted",
    "activation_allowed",
    "event_creation_allowed",
    "projection_allowed",
)
_C14_PACKAGE_STATE_FIELDS = tuple(
    field_name
    for field_name in _C14_STATE_FIELDS
    if field_name != "unresolved_blockers"
)
_AUTHORITY_FIELDS = (
    "medical_approval_granted",
    "engineering_approval_granted",
    "medical_approval_present",
    "engineering_approval_present",
    "review_outcome_present",
    "write_authority",
    "migration_authority",
    "activation_allowed",
    "event_creation_allowed",
    "projection_allowed",
    "source_token_synthesized",
    "aggregate_cas_applied",
    "authority_granted",
    "release_ready",
    "medical_confirmation_permitted",
    "runtime_write_permitted",
)


class B6ReviewerPacketRevalidationError(ValueError):
    """Raised when the revalidation input cannot be evaluated safely."""


class B6ReviewerPacketRevalidationIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    PACKET_SCHEMA_INVALID = "packet_schema_invalid"
    OBSERVED_FILES_MISSING = "observed_files_missing"
    OBSERVED_FILE_SHAPE_INVALID = "observed_file_shape_invalid"
    OBSERVED_FILE_MISSING = "observed_file_missing"
    OBSERVED_FILE_BYTES_MISMATCH = "observed_file_bytes_mismatch"
    OBSERVED_FILE_SHA256_MISMATCH = "observed_file_sha256_mismatch"
    PACKAGE_HASH_MISMATCH = "package_hash_mismatch"
    PACKAGE_SOURCE_MANIFEST_INVALID = "package_source_manifest_invalid"
    PACKAGE_SOURCE_MANIFEST_UNVERIFIED = "package_source_manifest_unverified"
    PACKET_PACKAGE_BINDING_MISSING = "packet_package_binding_missing"
    PACKET_PACKAGE_BINDING_MISMATCH = "packet_package_binding_mismatch"
    PACKET_B6_BINDING_MISSING = "packet_b6_binding_missing"
    PACKET_B6_SOURCE_MISMATCH = "packet_b6_source_mismatch"
    PACKET_C14_BINDING_MISSING = "packet_c14_binding_missing"
    PACKET_C14_SOURCE_MISMATCH = "packet_c14_source_mismatch"
    B6_STATE_MISMATCH = "b6_state_mismatch"
    C14_STATE_MISMATCH = "c14_state_mismatch"
    CANDIDATE_SET_MISMATCH = "candidate_set_mismatch"
    CANDIDATE_FINGERPRINT_MISMATCH = "candidate_fingerprint_mismatch"
    CURRENT_OUTCOME_BINDING_MISMATCH = "current_outcome_binding_mismatch"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    READ_ONLY_FLAG_MISMATCH = "read_only_flag_mismatch"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise B6ReviewerPacketRevalidationError(
            "revalidation values must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _safe_relative_path(value: Any) -> bool:
    path = _text(value)
    return bool(path) and not path.startswith("/") and ".." not in path.split("/")


@dataclass(frozen=True)
class B6ReviewerPacketRevalidationIssue:
    code: B6ReviewerPacketRevalidationIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise B6ReviewerPacketRevalidationError(
                "issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class B6ReviewerPacketRevalidationReport:
    """Immutable evidence-freshness result; never an authority grant."""

    status: str
    evidence_fresh: bool
    packet_file_checked: bool
    package_file_checked: bool
    source_manifest_replay_complete: bool
    packet_gate_binding_verified: bool
    candidate_binding_verified: bool
    current_outcome_binding_verified: bool
    authority_safe: bool
    packet_candidate_count: int
    package_candidate_count: int
    current_candidate_count: int
    packet_outcome_count: int
    current_outcome_count: int
    issues: tuple[B6ReviewerPacketRevalidationIssue, ...]
    schema_version: str = B6_REVIEWER_PACKET_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    medical_approval_granted: bool = False
    write_authority: bool = False
    migration_authority: bool = False
    activation_allowed: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != B6_REVIEWER_PACKET_REVALIDATION_SCHEMA_VERSION:
            raise B6ReviewerPacketRevalidationError("unsupported revalidation schema")
        if self.status not in {"fresh", "stale"}:
            raise B6ReviewerPacketRevalidationError("status must be fresh or stale")
        if self.read_only is not True:
            raise B6ReviewerPacketRevalidationError("revalidation must remain read-only")
        for name in (
            "medical_approval_granted",
            "write_authority",
            "migration_authority",
            "activation_allowed",
        ):
            if getattr(self, name) is not False:
                raise B6ReviewerPacketRevalidationError(
                    f"{name} must remain false"
                )
        for name in (
            "evidence_fresh",
            "packet_file_checked",
            "package_file_checked",
            "source_manifest_replay_complete",
            "packet_gate_binding_verified",
            "candidate_binding_verified",
            "current_outcome_binding_verified",
            "authority_safe",
        ):
            if not isinstance(getattr(self, name), bool):
                raise B6ReviewerPacketRevalidationError(f"{name} must be boolean")
        for name in (
            "packet_candidate_count",
            "package_candidate_count",
            "current_candidate_count",
            "packet_outcome_count",
            "current_outcome_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise B6ReviewerPacketRevalidationError(
                    f"{name} must be a non-negative integer"
                )
        issues = tuple(self.issues)
        if any(not isinstance(item, B6ReviewerPacketRevalidationIssue) for item in issues):
            raise B6ReviewerPacketRevalidationError("issues contain an invalid value")
        expected_fresh = (
            not issues
            and self.packet_file_checked
            and self.package_file_checked
            and self.source_manifest_replay_complete
            and self.packet_gate_binding_verified
            and self.candidate_binding_verified
            and self.current_outcome_binding_verified
            and self.authority_safe
        )
        if self.evidence_fresh != expected_fresh or (self.status == "fresh") != expected_fresh:
            raise B6ReviewerPacketRevalidationError(
                "status does not match the observed freshness state"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "packet_file_checked": self.packet_file_checked,
            "package_file_checked": self.package_file_checked,
            "source_manifest_replay_complete": self.source_manifest_replay_complete,
            "packet_gate_binding_verified": self.packet_gate_binding_verified,
            "candidate_binding_verified": self.candidate_binding_verified,
            "current_outcome_binding_verified": self.current_outcome_binding_verified,
            "authority_safe": self.authority_safe,
            "packet_candidate_count": self.packet_candidate_count,
            "package_candidate_count": self.package_candidate_count,
            "current_candidate_count": self.current_candidate_count,
            "packet_outcome_count": self.packet_outcome_count,
            "current_outcome_count": self.current_outcome_count,
            "issues": [item.to_dict() for item in self.issues],
            "read_only": self.read_only,
            "medical_approval_granted": self.medical_approval_granted,
            "write_authority": self.write_authority,
            "migration_authority": self.migration_authority,
            "activation_allowed": self.activation_allowed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "issue_count": len(self.issues), "report_sha256": self.report_sha256}


def _issue(
    issues: list[B6ReviewerPacketRevalidationIssue],
    code: B6ReviewerPacketRevalidationIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(B6ReviewerPacketRevalidationIssue(code, subject, detail))


def _observed_file(
    observed_files: Mapping[str, tuple[int, str]] | None,
    path: str,
    issues: list[B6ReviewerPacketRevalidationIssue],
) -> tuple[int, str] | None:
    if observed_files is None:
        return None
    value = observed_files.get(path)
    if value is None:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.OBSERVED_FILE_MISSING,
            path,
            "required current file is absent from the explicit observation map",
        )
        return None
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or isinstance(value[0], bool)
        or not isinstance(value[0], int)
        or value[0] < 0
        or not _valid_sha(value[1])
    ):
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.OBSERVED_FILE_SHAPE_INVALID,
            path,
            "observed file must be (non-negative bytes, lowercase SHA-256)",
        )
        return None
    return value


def _package_hash(package: Mapping[str, Any]) -> str | None:
    declared = package.get("package_sha256")
    if not _valid_sha(declared):
        return None
    payload = dict(package)
    payload.pop("package_sha256", None)
    return declared if _digest(payload) == declared else None


def _source_manifest_replay(
    package: Mapping[str, Any],
    observed_files: Mapping[str, tuple[int, str]] | None,
    issues: list[B6ReviewerPacketRevalidationIssue],
) -> bool:
    manifest = package.get("source_manifest")
    if not isinstance(manifest, list) or not manifest:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.PACKAGE_SOURCE_MANIFEST_INVALID,
            "source_manifest",
            "formal package source_manifest must be a non-empty list",
        )
        return False
    if observed_files is None:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.PACKAGE_SOURCE_MANIFEST_UNVERIFIED,
            "source_manifest",
            "source manifest replay requires explicit bytes/SHA observations",
        )
        return False
    complete = True
    seen: set[str] = set()
    for index, item in enumerate(manifest):
        subject = f"source_manifest[{index}]"
        if not isinstance(item, Mapping):
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.PACKAGE_SOURCE_MANIFEST_INVALID,
                subject,
                "manifest rows must be objects",
            )
            complete = False
            continue
        path = _text(item.get("path"))
        expected_bytes = item.get("bytes")
        expected_sha = item.get("sha256")
        if not _safe_relative_path(path) or path in seen or not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool) or expected_bytes < 0 or not _valid_sha(expected_sha):
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.PACKAGE_SOURCE_MANIFEST_INVALID,
                subject,
                "manifest path, bytes, and SHA-256 must be unique and well typed",
            )
            complete = False
            continue
        seen.add(path)
        observed = _observed_file(observed_files, path, issues)
        if observed is None:
            complete = False
            continue
        if observed[0] != expected_bytes:
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.OBSERVED_FILE_BYTES_MISMATCH,
                path,
                f"expected {expected_bytes} bytes, observed {observed[0]}",
            )
            complete = False
        if observed[1] != expected_sha:
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.OBSERVED_FILE_SHA256_MISMATCH,
                path,
                "observed source SHA-256 differs from the formal package manifest",
            )
            complete = False
    return complete


def _compare_state(
    expected: Mapping[str, Any] | None,
    observed: Mapping[str, Any] | None,
    fields: tuple[str, ...],
    code: B6ReviewerPacketRevalidationIssueCode,
    subject: str,
    issues: list[B6ReviewerPacketRevalidationIssue],
) -> bool:
    if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
        _issue(issues, code, subject, "state must be an object")
        return False
    ok = True
    for field_name in fields:
        if field_name not in expected:
            _issue(issues, code, f"{subject}.{field_name}", "state field is missing")
            ok = False
        elif expected.get(field_name) != observed.get(field_name):
            _issue(
                issues,
                code,
                f"{subject}.{field_name}",
                f"expected={expected.get(field_name)!r}, observed={observed.get(field_name)!r}",
            )
            ok = False
    return ok


def _candidate_map(rows: Any, key: str) -> dict[str, str] | None:
    if not isinstance(rows, list):
        return None
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        identifier = _text(row.get(key))
        fingerprint = _text(row.get("candidate_fingerprint"))
        if not identifier or not _valid_sha(fingerprint) or identifier in result:
            return None
        result[identifier] = fingerprint
    return result


def _outcome_map(rows: Any) -> dict[str, str] | None:
    """Build a one-to-one outcome binding without silently folding duplicates."""

    if not isinstance(rows, list):
        return None
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        candidate_id = _text(row.get("candidate_record_id"))
        fingerprint = _text(row.get("candidate_fingerprint"))
        if not candidate_id or not _valid_sha(fingerprint) or candidate_id in result:
            return None
        result[candidate_id] = fingerprint
    return result


def _authority_safe(
    packet: Mapping[str, Any],
    package: Mapping[str, Any],
    b6_gate: Mapping[str, Any],
    c14_gate: Mapping[str, Any],
    issues: list[B6ReviewerPacketRevalidationIssue],
) -> bool:
    safe = True
    for subject, payload in (
        ("package.authority", package.get("authority")),
        ("packet.authority", packet.get("authority")),
        ("b6_gate.gate", b6_gate.get("gate")),
        ("b6_gate", b6_gate),
        ("c14_gate", c14_gate),
        ("packet.b6_gate", packet.get("b6_gate")),
        ("packet.c14_gate", packet.get("c14_gate")),
    ):
        if not isinstance(payload, Mapping):
            continue
        for field_name in _AUTHORITY_FIELDS:
            if field_name in payload and payload.get(field_name) is not False:
                _issue(
                    issues,
                    B6ReviewerPacketRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
                    f"{subject}.{field_name}",
                    "freshness evidence cannot carry a true authority flag",
                )
                safe = False
    for subject, payload in (
        ("package", package),
        ("packet", packet),
        ("b6_gate", b6_gate),
        ("b6_gate.gate", b6_gate.get("gate")),
        ("c14_gate", c14_gate),
        ("packet.b6_gate", packet.get("b6_gate")),
        ("packet.c14_gate", packet.get("c14_gate")),
    ):
        if not isinstance(payload, Mapping):
            continue
        for field_name in ("write_permitted", "migration_ready", "migration_write_permitted"):
            if field_name in payload and payload.get(field_name) is not False:
                _issue(
                    issues,
                    B6ReviewerPacketRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
                    f"{subject}.{field_name}",
                    "freshness evidence cannot carry a true write or migration flag",
                )
                safe = False
    if package.get("read_only") is not True or packet.get("mode") != "read_only_reviewer_packet":
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.READ_ONLY_FLAG_MISMATCH,
            "read_only",
            "package and packet must explicitly remain read-only",
        )
        safe = False
    return safe


def revalidate_b6_reviewer_packet(
    packet: Mapping[str, Any],
    formal_package: Mapping[str, Any],
    current_b6_gate: Mapping[str, Any],
    current_c14_gate: Mapping[str, Any],
    *,
    observed_files: Mapping[str, tuple[int, str]] | None = None,
    packet_path: str = PACKET_PATH,
    package_path: str = PACKAGE_PATH,
    b6_gate_path: str = B6_GATE_PATH,
    c14_gate_path: str = C14_GATE_PATH,
) -> B6ReviewerPacketRevalidationReport:
    """Revalidate a persisted reviewer packet without changing any state."""

    if not all(isinstance(value, Mapping) for value in (packet, formal_package, current_b6_gate, current_c14_gate)):
        raise B6ReviewerPacketRevalidationError(
            "packet, formal_package, current_b6_gate and current_c14_gate must be mappings"
        )
    for name, path in (
        ("packet_path", packet_path),
        ("package_path", package_path),
        ("b6_gate_path", b6_gate_path),
        ("c14_gate_path", c14_gate_path),
    ):
        if not _safe_relative_path(path):
            raise B6ReviewerPacketRevalidationError(
                f"{name} must be a safe workspace-relative path"
            )
    issues: list[B6ReviewerPacketRevalidationIssue] = []
    if packet.get("schema_version") != PACKET_SCHEMA_VERSION:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.PACKET_SCHEMA_INVALID,
            "packet.schema_version",
            "packet schema_version is not the canonical B6 reviewer packet schema",
        )
    if observed_files is None:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.OBSERVED_FILES_MISSING,
            "observed_files",
            "current packet/package/source files must be reopened through explicit observations",
        )

    packet_observed = _observed_file(observed_files, packet_path, issues)
    package_observed = _observed_file(observed_files, package_path, issues)
    packet_file_checked = packet_observed is not None
    package_file_checked = package_observed is not None

    declared_package_hash = formal_package.get("package_sha256")
    package_hash_verified = _package_hash(formal_package) is not None
    if not package_hash_verified:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.PACKAGE_HASH_MISMATCH,
            "formal_package.package_sha256",
            "formal package payload does not match its declared package_sha256",
        )
    if package_observed is not None and package_observed[1] != _text(
        packet.get("formal_package_file_sha256")
    ):
        # A fresh packet may bind the package file bytes; old packets omitted it.
        if "formal_package_file_sha256" not in packet:
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.PACKET_PACKAGE_BINDING_MISSING,
                "packet.formal_package_file_sha256",
                "packet must bind the observed formal package file SHA-256",
            )
        else:
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.PACKET_PACKAGE_BINDING_MISMATCH,
                "packet.formal_package_file_sha256",
                "packet package-file SHA-256 differs from the observed formal package",
            )
    if _text(packet.get("formal_package_sha256")) != _text(declared_package_hash):
        code = (
            B6ReviewerPacketRevalidationIssueCode.PACKET_PACKAGE_BINDING_MISSING
            if "formal_package_sha256" not in packet
            else B6ReviewerPacketRevalidationIssueCode.PACKET_PACKAGE_BINDING_MISMATCH
        )
        _issue(
            issues,
            code,
            "packet.formal_package_sha256",
            "packet is not bound to the current formal package payload",
        )

    source_manifest_complete = _source_manifest_replay(formal_package, observed_files, issues)
    current_b6_file = _observed_file(observed_files, b6_gate_path, issues)
    current_c14_file = _observed_file(observed_files, c14_gate_path, issues)
    packet_b6 = packet.get("b6_gate")
    packet_c14 = packet.get("c14_gate")
    b6_source_ok = False
    if not isinstance(packet_b6, Mapping):
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.PACKET_B6_BINDING_MISSING,
            "packet.b6_gate",
            "packet b6_gate binding must be an object",
        )
    else:
        source_file = _text(packet_b6.get("source_file"))
        source_sha = _text(packet_b6.get("source_sha256"))
        if source_file != b6_gate_path or not _valid_sha(source_sha):
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.PACKET_B6_BINDING_MISSING,
                "packet.b6_gate.source_file",
                "packet must bind the canonical current B6 gate path and SHA-256",
            )
        elif current_b6_file is not None and source_sha == current_b6_file[1]:
            b6_source_ok = True
        else:
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.PACKET_B6_SOURCE_MISMATCH,
                "packet.b6_gate.source_sha256",
                "packet B6 SHA-256 differs from the observed current B6 gate",
            )
    c14_source_ok = False
    if not isinstance(packet_c14, Mapping):
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.PACKET_C14_BINDING_MISSING,
            "packet.c14_gate",
            "packet must include a C14/C13 activation-gate binding",
        )
    else:
        source_file = _text(packet_c14.get("source_file"))
        source_sha = _text(packet_c14.get("source_sha256"))
        if source_file != c14_gate_path or not _valid_sha(source_sha):
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.PACKET_C14_BINDING_MISSING,
                "packet.c14_gate.source_file",
                "packet must bind the canonical current C14 activation-gate path and SHA-256",
            )
        elif current_c14_file is not None and source_sha == current_c14_file[1]:
            c14_source_ok = True
        else:
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.PACKET_C14_SOURCE_MISMATCH,
                "packet.c14_gate.source_sha256",
                "packet C14 SHA-256 differs from the observed current C14 gate",
            )

    package_b6 = formal_package.get("gate_state", {}).get("b6") if isinstance(formal_package.get("gate_state"), Mapping) else None
    package_c14 = formal_package.get("gate_state", {}).get("c14") if isinstance(formal_package.get("gate_state"), Mapping) else None
    current_b6_state = current_b6_gate.get("gate")
    b6_state_ok = _compare_state(
        packet_b6,
        current_b6_state,
        _B6_STATE_FIELDS,
        B6ReviewerPacketRevalidationIssueCode.B6_STATE_MISMATCH,
        "packet.b6_gate",
        issues,
    )
    if not _compare_state(
        package_b6,
        current_b6_state,
        _B6_PACKAGE_STATE_FIELDS,
        B6ReviewerPacketRevalidationIssueCode.B6_STATE_MISMATCH,
        "formal_package.gate_state.b6",
        issues,
    ):
        b6_state_ok = False
    c14_state_ok = _compare_state(
        packet_c14,
        current_c14_gate,
        _C14_STATE_FIELDS,
        B6ReviewerPacketRevalidationIssueCode.C14_STATE_MISMATCH,
        "packet.c14_gate",
        issues,
    )
    if not _compare_state(
        package_c14,
        current_c14_gate,
        _C14_PACKAGE_STATE_FIELDS,
        B6ReviewerPacketRevalidationIssueCode.C14_STATE_MISMATCH,
        "formal_package.gate_state.c14",
        issues,
    ):
        c14_state_ok = False
    for subject, packet_state, current_state in (
        ("packet.b6_gate.migration_write_permitted", packet_b6, current_b6_gate),
        ("packet.c14_gate.migration_write_permitted", packet_c14, current_c14_gate),
    ):
        if not isinstance(packet_state, Mapping) or packet_state.get(
            "migration_write_permitted"
        ) != current_state.get("migration_write_permitted"):
            _issue(
                issues,
                B6ReviewerPacketRevalidationIssueCode.B6_STATE_MISMATCH
                if subject.startswith("packet.b6")
                else B6ReviewerPacketRevalidationIssueCode.C14_STATE_MISMATCH,
                subject,
                "packet migration_write_permitted differs from the current gate payload",
            )
            if subject.startswith("packet.b6"):
                b6_state_ok = False
            else:
                c14_state_ok = False

    packet_candidates = _candidate_map(packet.get("candidates"), "candidate_id")
    package_candidates = _candidate_map(formal_package.get("candidates"), "candidate_record_id")
    current_fingerprints = current_b6_gate.get("candidate_fingerprints")
    if not isinstance(current_fingerprints, Mapping):
        current_fingerprints = None
    candidate_binding_ok = (
        packet_candidates is not None
        and package_candidates is not None
        and packet_candidates == package_candidates
        and current_fingerprints is not None
        and dict(current_fingerprints) == package_candidates
    )
    if packet_candidates != package_candidates:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.CANDIDATE_SET_MISMATCH,
            "candidates",
            "packet candidate IDs/fingerprints differ from the formal package",
        )
    if current_fingerprints != package_candidates:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.CANDIDATE_FINGERPRINT_MISMATCH,
            "current_b6_gate.candidate_fingerprints",
            "current B6 candidate fingerprints differ from the formal package",
        )

    current_outcomes = current_b6_gate.get("outcomes")
    current_outcome_map = _outcome_map(current_outcomes)
    current_outcome_ok = (
        current_outcome_map is not None
        and current_outcome_map == package_candidates
        and isinstance(current_b6_state, Mapping)
        and current_b6_state.get("outcome_count") == len(current_outcome_map)
        and len(current_outcomes) == len(current_outcome_map)
    )
    if not current_outcome_ok:
        _issue(
            issues,
            B6ReviewerPacketRevalidationIssueCode.CURRENT_OUTCOME_BINDING_MISMATCH,
            "current_b6_gate.outcomes",
            "current B6 outcomes do not cover exactly the formal package candidates",
        )

    authority_safe = _authority_safe(packet, formal_package, current_b6_gate, current_c14_gate, issues)
    packet_b6_count = packet_b6.get("candidate_count", 0) if isinstance(packet_b6, Mapping) else 0
    package_count = len(package_candidates or {})
    current_count = current_b6_state.get("candidate_count", 0) if isinstance(current_b6_state, Mapping) else 0
    packet_outcome_count = packet_b6.get("outcome_count", 0) if isinstance(packet_b6, Mapping) else 0
    current_outcome_count = current_b6_state.get("outcome_count", 0) if isinstance(current_b6_state, Mapping) else 0
    counts = {
        "packet_candidate_count": packet_b6_count,
        "package_candidate_count": package_count,
        "current_candidate_count": current_count,
        "packet_outcome_count": packet_outcome_count,
        "current_outcome_count": current_outcome_count,
    }
    for name, value in counts.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise B6ReviewerPacketRevalidationError(f"{name} must be a non-negative integer")
    packet_gate_ok = b6_source_ok and c14_source_ok and b6_state_ok and c14_state_ok
    return B6ReviewerPacketRevalidationReport(
        status="fresh" if not issues and packet_file_checked and package_file_checked and source_manifest_complete and packet_gate_ok and candidate_binding_ok and current_outcome_ok and authority_safe else "stale",
        evidence_fresh=not issues and packet_file_checked and package_file_checked and source_manifest_complete and packet_gate_ok and candidate_binding_ok and current_outcome_ok and authority_safe,
        packet_file_checked=packet_file_checked,
        package_file_checked=package_file_checked,
        source_manifest_replay_complete=source_manifest_complete,
        packet_gate_binding_verified=packet_gate_ok,
        candidate_binding_verified=candidate_binding_ok,
        current_outcome_binding_verified=current_outcome_ok,
        authority_safe=authority_safe,
        packet_candidate_count=packet_b6_count,
        package_candidate_count=package_count,
        current_candidate_count=current_count,
        packet_outcome_count=packet_outcome_count,
        current_outcome_count=current_outcome_count,
        issues=tuple(issues),
    )


__all__ = [
    "B6_GATE_PATH",
    "B6_REVIEWER_PACKET_REVALIDATION_SCHEMA_VERSION",
    "B6ReviewerPacketRevalidationError",
    "B6ReviewerPacketRevalidationIssue",
    "B6ReviewerPacketRevalidationIssueCode",
    "B6ReviewerPacketRevalidationReport",
    "C14_GATE_PATH",
    "PACKAGE_PATH",
    "PACKET_PATH",
    "PACKET_SCHEMA_VERSION",
    "revalidate_b6_reviewer_packet",
]
