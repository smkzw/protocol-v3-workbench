"""Read-only, fail-closed admission contract for monitoring project identities.

This contract sits before a future controlled real-LOOP manifest is consumed.  It
does not register an adapter, write a source registry, approve a batch, call a
provider, start a runtime or create a medical decision.  It only proves that a
declared project *could* be handed to a later, separately-authorized admission
workflow without confusing a candidate root or a non-monitoring project alias
with a monitoring project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


PROJECT_ADMISSION_SCHEMA_VERSION = "medical_monitoring_project_admission_v1"
ELIGIBLE_LISTING_CLASSES = frozenset({"raw_full_snapshot", "raw_locked_snapshot"})
REQUIRED_UPSTREAM_GATES = (
    "b6_approved",
    "approved_input_ready",
    "source_token_revalidated",
    "aggregate_cas_complete",
    "runtime_identity_verified",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{1,239}$")


class ProjectAdmissionContractError(ValueError):
    """Raised when a project admission payload is structurally unsafe."""


class ProjectAdmissionIssueCode(str, Enum):
    PROJECT_ID_INVALID = "project_id_invalid"
    PROJECT_SET_MISMATCH = "project_set_mismatch"
    PROJECT_IDENTITY_MISMATCH = "project_identity_mismatch"
    CANDIDATE_NOT_ADMISSIBLE = "candidate_not_admissible"
    NON_MONITORING_ALIAS_FORBIDDEN = "non_monitoring_alias_forbidden"
    ADAPTER_NOT_REGISTERED = "adapter_not_registered"
    ADAPTER_IDENTITY_MISMATCH = "adapter_identity_mismatch"
    SOURCE_BINDING_MISSING = "source_binding_missing"
    SOURCE_REVISION_MISSING = "source_revision_missing"
    BATCH_COVERAGE_INSUFFICIENT = "batch_coverage_insufficient"
    BATCH_DUPLICATE = "batch_duplicate"
    BATCH_NOT_ELIGIBLE = "batch_not_eligible"
    BATCH_REFERENCE_MISSING = "batch_reference_missing"
    PROMPT_COVERAGE_MISSING = "prompt_coverage_missing"
    PROMPT_DUPLICATE = "prompt_duplicate"
    UPSTREAM_GATE_NOT_READY = "upstream_gate_not_ready"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_id(value: Any, field_name: str) -> str:
    text = _text(value)
    if not _SAFE_ID_RE.fullmatch(text):
        raise ProjectAdmissionContractError(
            f"{field_name} must be a non-empty opaque identifier"
        )
    return text


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ProjectAdmissionContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _unique_ids(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_safe_id(value, field_name) for value in values)
    if len(normalized) != len(set(normalized)):
        raise ProjectAdmissionContractError(f"{field_name} must not repeat")
    return tuple(sorted(normalized))


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ProjectAdmissionContractError(
            "admission payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProjectAdmissionBatch:
    """One explicit, provenance-bound full listing snapshot."""

    batch_ref: str
    snapshot_date: str
    listing_sha256: str
    listing_class: str
    source_status: str
    full_snapshot_proven: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "batch_ref", _safe_id(self.batch_ref, "batch_ref"))
        object.__setattr__(self, "snapshot_date", _text(self.snapshot_date))
        try:
            date.fromisoformat(self.snapshot_date)
        except ValueError as exc:
            raise ProjectAdmissionContractError(
                "batch.snapshot_date must be an ISO calendar date"
            ) from exc
        object.__setattr__(
            self, "listing_sha256", _sha256(self.listing_sha256, "batch.listing_sha256")
        )
        object.__setattr__(self, "listing_class", _text(self.listing_class))
        object.__setattr__(self, "source_status", _text(self.source_status))
        if not isinstance(self.full_snapshot_proven, bool):
            raise ProjectAdmissionContractError(
                "batch.full_snapshot_proven must be a boolean"
            )


@dataclass(frozen=True)
class ProjectAdmissionPrompt:
    """One project-specific prompt row bound to its exact content hash."""

    prompt_ref: str
    prompt_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "prompt_ref", _safe_id(self.prompt_ref, "prompt_ref"))
        object.__setattr__(
            self, "prompt_sha256", _sha256(self.prompt_sha256, "prompt_sha256")
        )


@dataclass(frozen=True)
class ProjectAdmissionInput:
    """Declarative admission evidence; all authority fields remain diagnostic."""

    project_id: str
    canonical_project_id: str
    expected_project_set: tuple[str, ...]
    adapter_registered: bool
    adapter_project_id: str
    source_binding_present: bool
    monitoring_module_binding_present: bool
    source_content_revision: str
    parse_revision: str
    batches: tuple[ProjectAdmissionBatch, ...]
    prompts: tuple[ProjectAdmissionPrompt, ...]
    expected_prompt_refs: tuple[str, ...]
    upstream_gates: Mapping[str, bool]
    candidate_only: bool = False
    non_monitoring_alias: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _safe_id(self.project_id, "project_id"))
        object.__setattr__(
            self,
            "canonical_project_id",
            _safe_id(self.canonical_project_id, "canonical_project_id"),
        )
        expected_projects = _unique_ids(
            self.expected_project_set, "expected_project_id"
        )
        if not expected_projects:
            raise ProjectAdmissionContractError(
                "expected_project_set must not be empty"
            )
        object.__setattr__(self, "expected_project_set", expected_projects)
        for field_name in (
            "adapter_registered",
            "source_binding_present",
            "monitoring_module_binding_present",
            "candidate_only",
            "non_monitoring_alias",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ProjectAdmissionContractError(f"{field_name} must be a boolean")
        object.__setattr__(self, "adapter_project_id", _text(self.adapter_project_id))
        object.__setattr__(
            self, "source_content_revision", _text(self.source_content_revision)
        )
        object.__setattr__(self, "parse_revision", _text(self.parse_revision))
        batches = tuple(self.batches)
        if any(not isinstance(item, ProjectAdmissionBatch) for item in batches):
            raise ProjectAdmissionContractError(
                "batches must contain ProjectAdmissionBatch rows"
            )
        prompts = tuple(self.prompts)
        if any(not isinstance(item, ProjectAdmissionPrompt) for item in prompts):
            raise ProjectAdmissionContractError(
                "prompts must contain ProjectAdmissionPrompt rows"
            )
        object.__setattr__(self, "batches", batches)
        object.__setattr__(self, "prompts", prompts)
        expected_prompt_refs = _unique_ids(
            self.expected_prompt_refs, "expected_prompt_ref"
        )
        object.__setattr__(self, "expected_prompt_refs", expected_prompt_refs)
        if not isinstance(self.upstream_gates, Mapping):
            raise ProjectAdmissionContractError("upstream_gates must be an object")
        gates = dict(self.upstream_gates)
        unknown = set(gates) - set(REQUIRED_UPSTREAM_GATES)
        missing = set(REQUIRED_UPSTREAM_GATES) - set(gates)
        if unknown:
            raise ProjectAdmissionContractError(
                "upstream_gates contain unknown keys: " + ", ".join(sorted(unknown))
            )
        if missing:
            raise ProjectAdmissionContractError(
                "upstream_gates are missing: " + ", ".join(sorted(missing))
            )
        if any(not isinstance(value, bool) for value in gates.values()):
            raise ProjectAdmissionContractError("upstream gate values must be booleans")
        object.__setattr__(self, "upstream_gates", gates)


@dataclass(frozen=True)
class ProjectAdmissionIssue:
    code: ProjectAdmissionIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise ProjectAdmissionContractError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class ProjectAdmissionReport:
    """Diagnostic admission result; never grants product or medical authority."""

    status: str
    admission_complete: bool
    project_id: str
    batch_refs: tuple[str, ...]
    prompt_refs: tuple[str, ...]
    issues: tuple[ProjectAdmissionIssue, ...]
    schema_version: str = PROJECT_ADMISSION_SCHEMA_VERSION
    diagnostic_only: bool = True
    runtime_activation_permitted: bool = False
    provider_call_permitted: bool = False
    write_permitted: bool = False
    medical_confirmation_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != PROJECT_ADMISSION_SCHEMA_VERSION:
            raise ProjectAdmissionContractError(
                "unsupported project admission schema version"
            )
        if self.status not in {"blocked", "diagnostic_admissible"}:
            raise ProjectAdmissionContractError("invalid project admission status")
        for name in (
            "admission_complete",
            "diagnostic_only",
            "runtime_activation_permitted",
            "provider_call_permitted",
            "write_permitted",
            "medical_confirmation_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ProjectAdmissionContractError(f"{name} must be a boolean")
        if not self.diagnostic_only:
            raise ProjectAdmissionContractError(
                "project admission report must remain diagnostic_only"
            )
        if any(
            (
                self.runtime_activation_permitted,
                self.provider_call_permitted,
                self.write_permitted,
                self.medical_confirmation_permitted,
            )
        ):
            raise ProjectAdmissionContractError(
                "admission evidence cannot grant authority"
            )
        issues = tuple(self.issues)
        expected_complete = not issues and self.status == "diagnostic_admissible"
        if self.admission_complete != expected_complete:
            raise ProjectAdmissionContractError(
                "admission_complete does not match issues"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "batch_refs", tuple(sorted(self.batch_refs)))
        object.__setattr__(self, "prompt_refs", tuple(sorted(self.prompt_refs)))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "admission_complete": self.admission_complete,
            "project_id": self.project_id,
            "batch_refs": list(self.batch_refs),
            "prompt_refs": list(self.prompt_refs),
            "issues": [item.to_dict() for item in self.issues],
            "schema_version": self.schema_version,
            "diagnostic_only": self.diagnostic_only,
            "runtime_activation_permitted": self.runtime_activation_permitted,
            "provider_call_permitted": self.provider_call_permitted,
            "write_permitted": self.write_permitted,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _issue(
    issues: list[ProjectAdmissionIssue],
    code: ProjectAdmissionIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(ProjectAdmissionIssue(code, subject, detail))


def assess_project_admission(
    admission: ProjectAdmissionInput,
    *,
    required_batch_count: int = 2,
) -> ProjectAdmissionReport:
    """Assess one project without mutating a registry or granting authority."""

    if not isinstance(admission, ProjectAdmissionInput):
        raise ProjectAdmissionContractError("admission must be a ProjectAdmissionInput")
    if (
        isinstance(required_batch_count, bool)
        or not isinstance(required_batch_count, int)
        or required_batch_count < 2
    ):
        raise ProjectAdmissionContractError(
            "required_batch_count must be an integer >= 2"
        )

    issues: list[ProjectAdmissionIssue] = []
    project_id = admission.project_id
    if project_id not in admission.expected_project_set:
        _issue(
            issues,
            ProjectAdmissionIssueCode.PROJECT_SET_MISMATCH,
            project_id,
            "project_id is outside the declared project set",
        )
    if admission.canonical_project_id != project_id:
        _issue(
            issues,
            ProjectAdmissionIssueCode.PROJECT_IDENTITY_MISMATCH,
            project_id,
            "canonical_project_id must equal project_id for a monitoring admission",
        )
    if admission.candidate_only:
        _issue(
            issues,
            ProjectAdmissionIssueCode.CANDIDATE_NOT_ADMISSIBLE,
            project_id,
            "candidate-only roots require a separate controlled promotion and cannot enter the executable set",
        )
    if admission.non_monitoring_alias:
        _issue(
            issues,
            ProjectAdmissionIssueCode.NON_MONITORING_ALIAS_FORBIDDEN,
            project_id,
            "a non-monitoring project alias cannot be reused as a monitoring identity",
        )
    if not admission.adapter_registered:
        _issue(
            issues,
            ProjectAdmissionIssueCode.ADAPTER_NOT_REGISTERED,
            project_id,
            "a monitoring adapter registration is required",
        )
    if admission.adapter_project_id != project_id:
        _issue(
            issues,
            ProjectAdmissionIssueCode.ADAPTER_IDENTITY_MISMATCH,
            project_id,
            "adapter_project_id must equal the declared monitoring project_id",
        )
    if (
        not admission.source_binding_present
        or not admission.monitoring_module_binding_present
    ):
        _issue(
            issues,
            ProjectAdmissionIssueCode.SOURCE_BINDING_MISSING,
            project_id,
            "source content/parse identity and the medical-monitoring module binding are both required",
        )
    if not admission.source_content_revision or not admission.parse_revision:
        _issue(
            issues,
            ProjectAdmissionIssueCode.SOURCE_REVISION_MISSING,
            project_id,
            "source_content_revision and parse_revision must be present",
        )

    batches = admission.batches
    batch_refs = [item.batch_ref for item in batches]
    batch_hashes = [item.listing_sha256 for item in batches]
    if len(batches) < required_batch_count:
        _issue(
            issues,
            ProjectAdmissionIssueCode.BATCH_COVERAGE_INSUFFICIENT,
            project_id,
            f"at least {required_batch_count} explicit full batches are required",
        )
    if len(batch_refs) != len(set(batch_refs)) or len(batch_hashes) != len(
        set(batch_hashes)
    ):
        _issue(
            issues,
            ProjectAdmissionIssueCode.BATCH_DUPLICATE,
            project_id,
            "batch_ref and listing_sha256 must both be unique within a project",
        )
    for batch in batches:
        if (
            batch.listing_class not in ELIGIBLE_LISTING_CLASSES
            or batch.source_status != "confirmed"
            or batch.full_snapshot_proven is not True
        ):
            _issue(
                issues,
                ProjectAdmissionIssueCode.BATCH_NOT_ELIGIBLE,
                batch.batch_ref,
                "each batch must be confirmed, eligible and explicitly proven full",
            )
    if not batch_refs:
        _issue(
            issues,
            ProjectAdmissionIssueCode.BATCH_REFERENCE_MISSING,
            project_id,
            "at least one opaque batch reference is required",
        )

    prompts = admission.prompts
    prompt_refs = [item.prompt_ref for item in prompts]
    prompt_hashes = [item.prompt_sha256 for item in prompts]
    if len(prompt_refs) != len(set(prompt_refs)) or len(prompt_hashes) != len(
        set(prompt_hashes)
    ):
        _issue(
            issues,
            ProjectAdmissionIssueCode.PROMPT_DUPLICATE,
            project_id,
            "prompt references and exact hashes must be unique within a project",
        )
    expected_prompt_refs = set(admission.expected_prompt_refs)
    observed_prompt_refs = set(prompt_refs)
    if observed_prompt_refs != expected_prompt_refs:
        _issue(
            issues,
            ProjectAdmissionIssueCode.PROMPT_COVERAGE_MISSING,
            project_id,
            "project prompt rows must exactly match the declared project-specific manifest rows",
        )

    for gate_name in REQUIRED_UPSTREAM_GATES:
        if admission.upstream_gates[gate_name] is not True:
            _issue(
                issues,
                ProjectAdmissionIssueCode.UPSTREAM_GATE_NOT_READY,
                gate_name,
                "all upstream B6/approved-input/source-token/CAS/runtime gates must be explicitly true",
            )

    ordered_issues = tuple(
        sorted(issues, key=lambda item: (item.subject, item.code.value, item.detail))
    )
    complete = not ordered_issues
    return ProjectAdmissionReport(
        status="diagnostic_admissible" if complete else "blocked",
        admission_complete=complete,
        project_id=project_id,
        batch_refs=tuple(batch_refs),
        prompt_refs=tuple(prompt_refs),
        issues=ordered_issues,
    )


__all__ = [
    "ELIGIBLE_LISTING_CLASSES",
    "PROJECT_ADMISSION_SCHEMA_VERSION",
    "REQUIRED_UPSTREAM_GATES",
    "ProjectAdmissionBatch",
    "ProjectAdmissionContractError",
    "ProjectAdmissionInput",
    "ProjectAdmissionIssue",
    "ProjectAdmissionIssueCode",
    "ProjectAdmissionPrompt",
    "ProjectAdmissionReport",
    "assess_project_admission",
]
