"""Fail-closed planning contract for the five-project medical-monitoring LOOP.

This module validates the inputs and evidence required before a controlled
real-project LOOP.  It never starts a runtime, calls a provider, approves a
medical decision, or grants write/activation authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from datetime import date
from typing import Any, Iterable


REAL_LOOP_PROJECT_IDS = (
    "proj_mgk10_sar_real",
    "proj_rux_03_002",
    "proj_my008_3_02_candidate",
    "proj_my008_3_01_candidate",
    "proj_my009_uc",
)
REAL_LOOP_TASK_TYPES = (
    "field_semantic_mapping",
    "protocol_clause_extraction",
    "risk_evidence_summary",
    "interactive_follow_up",
)
REAL_LOOP_ROLES = ("engineer", "senior_medical_monitor")
REAL_LOOP_UPSTREAM_GATE_NAMES = (
    "b6_approved",
    "approved_input_ready",
    "source_token_revalidated",
    "aggregate_cas_complete",
    "runtime_identity_verified",
)
REAL_LOOP_MODEL_ROUTES = {
    "pi/opencode-go/deepseek-v4-flash": "07:30-22:00 Asia/Shanghai",
    "pi/alibaba/qwen3.8-max-preview": "22:00-07:30 Asia/Shanghai",
}
ELIGIBLE_LISTING_CLASSES = {"raw_full_snapshot", "raw_locked_snapshot"}
ALLOWED_SCENARIO_STATUSES = {"not_run", "passed", "failed", "blocked"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_EVIDENCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class RealLoopReadinessError(ValueError):
    """Raised when the readiness input is structurally unsafe to evaluate."""


class RealLoopIssueCode(str, Enum):
    PROJECT_SET_MISMATCH = "project_set_mismatch"
    PROJECT_DUPLICATE = "project_duplicate"
    SOURCE_HASH_INVALID = "source_hash_invalid"
    SOURCE_NOT_ELIGIBLE = "source_not_eligible"
    BATCH_COVERAGE_INSUFFICIENT = "batch_coverage_insufficient"
    BATCH_EVIDENCE_INCOMPLETE = "batch_evidence_incomplete"
    BATCH_DUPLICATE = "batch_duplicate"
    TASK_COVERAGE_MISSING = "task_coverage_missing"
    ROLE_COVERAGE_MISSING = "role_coverage_missing"
    PROMPT_HASH_DUPLICATE = "prompt_hash_duplicate"
    MODEL_ROUTE_INVALID = "model_route_invalid"
    GATE_NOT_READY = "gate_not_ready"
    GATE_VALUE_INVALID = "gate_value_invalid"
    GENERALIZATION_NOT_READY = "generalization_not_ready"
    GENERALIZATION_EVIDENCE_INVALID = "generalization_evidence_invalid"
    SEMANTICS_BINDING_NOT_READY = "semantics_binding_not_ready"
    SEMANTICS_BINDING_INVALID = "semantics_binding_invalid"
    UPSTREAM_EVIDENCE_HASH_INVALID = "upstream_evidence_hash_invalid"
    UPSTREAM_EVIDENCE_HASH_DUPLICATE = "upstream_evidence_hash_duplicate"
    UPSTREAM_EVIDENCE_REF_INVALID = "upstream_evidence_ref_invalid"
    UPSTREAM_EVIDENCE_REF_DUPLICATE = "upstream_evidence_ref_duplicate"
    UPSTREAM_EVIDENCE_PAIR_INCOMPLETE = "upstream_evidence_pair_incomplete"
    ACCEPTANCE_NOT_COMPLETE = "acceptance_not_complete"
    SCENARIO_STATUS_INVALID = "scenario_status_invalid"
    SCENARIO_EXECUTION_FAILED = "scenario_execution_failed"
    PROMPT_MANIFEST_MISSING = "prompt_manifest_missing"
    PROMPT_MANIFEST_MISMATCH = "prompt_manifest_mismatch"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise RealLoopReadinessError(
            "readiness input must be JSON serializable"
        ) from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_canonical_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and value == value.lower()
        and _SHA256_RE.fullmatch(value) is not None
    )


def _source_hash(value: Any, subject: str, issues: list["RealLoopIssue"]) -> str:
    digest = value if isinstance(value, str) else ""
    if not _is_canonical_digest(value):
        issues.append(
            RealLoopIssue(
                RealLoopIssueCode.SOURCE_HASH_INVALID,
                subject,
                "protocol and listing inputs require lowercase SHA-256 evidence",
            )
        )
    return digest


@dataclass(frozen=True)
class RealLoopBatch:
    batch_ref: str
    snapshot_date: str
    listing_sha256: str
    listing_class: str
    source_status: str
    full_snapshot_proven: bool


@dataclass(frozen=True)
class RealLoopSource:
    project_id: str
    protocol_ref: str
    protocol_sha256: str
    listing_ref: str
    listing_sha256: str
    listing_class: str
    source_status: str
    batch_count: int
    batches: tuple[RealLoopBatch, ...] = ()


@dataclass(frozen=True)
class RealLoopScenario:
    scenario_id: str
    project_id: str
    role: str
    task_type: str
    prompt_sha256: str
    model_route: str
    run_status: str = "not_run"
    prompt_ref: str = ""


@dataclass(frozen=True)
class RealLoopGateInput:
    b6_approved: bool
    approved_input_ready: bool
    source_token_revalidated: bool
    aggregate_cas_complete: bool
    runtime_identity_verified: bool
    browser_acceptance_complete: bool = False
    scientific_acceptance_complete: bool = False
    generalization_evidence_complete: bool = False
    generalization_evidence_sha256: str = ""
    b6_evidence_sha256: str = ""
    approved_input_evidence_sha256: str = ""
    source_token_evidence_sha256: str = ""
    aggregate_cas_evidence_sha256: str = ""
    runtime_identity_evidence_sha256: str = ""
    b6_evidence_ref: str = ""
    approved_input_evidence_ref: str = ""
    source_token_evidence_ref: str = ""
    aggregate_cas_evidence_ref: str = ""
    runtime_identity_evidence_ref: str = ""
    semantics_binding_matched: bool = False
    semantics_binding_sha256: str = ""


@dataclass(frozen=True)
class RealLoopIssue:
    code: RealLoopIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if not _text(self.subject) or not _text(self.detail):
            raise RealLoopReadinessError("issue subject and detail are required")
        object.__setattr__(self, "subject", _text(self.subject))
        object.__setattr__(self, "detail", _text(self.detail))

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopReadinessReport:
    status: str
    execution_ready: bool
    acceptance_complete: bool
    project_count: int
    scenario_count: int
    issues: tuple[RealLoopIssue, ...]
    batch_refs_by_project: tuple[tuple[str, tuple[str, ...]], ...] = ()
    generalization_evidence_sha256: str = ""
    semantics_binding_matched: bool = False
    semantics_binding_sha256: str = ""
    upstream_gate_evidence_sha256: tuple[tuple[str, str], ...] = ()
    upstream_gate_evidence_refs: tuple[tuple[str, str], ...] = ()
    runtime_activation_permitted: bool = False
    provider_call_permitted: bool = False
    write_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.status not in {"blocked", "ready_for_controlled_execution"}:
            raise RealLoopReadinessError("invalid real-loop readiness status")
        for name in (
            "execution_ready",
            "acceptance_complete",
            "semantics_binding_matched",
            "runtime_activation_permitted",
            "provider_call_permitted",
            "write_permitted",
        ):
            if not isinstance(getattr(self, name), bool):
                raise RealLoopReadinessError(f"{name} must be a strict boolean")
        if (
            self.runtime_activation_permitted
            or self.provider_call_permitted
            or self.write_permitted
        ):
            raise RealLoopReadinessError(
                "readiness contract cannot grant execution authority"
            )
        if self.generalization_evidence_sha256 and not _SHA256_RE.fullmatch(
            self.generalization_evidence_sha256
        ):
            raise RealLoopReadinessError(
                "generalization evidence hash must be a lowercase SHA-256"
            )
        if self.semantics_binding_sha256 and not _SHA256_RE.fullmatch(
            self.semantics_binding_sha256
        ):
            raise RealLoopReadinessError(
                "semantics binding hash must be a lowercase SHA-256"
            )
        upstream_gate_evidence = tuple(
            (str(name), value if isinstance(value, str) else "")
            for name, value in self.upstream_gate_evidence_sha256
        )
        upstream_names = [name for name, _ in upstream_gate_evidence]
        upstream_hashes = [value for _, value in upstream_gate_evidence]
        if len(upstream_names) != len(set(upstream_names)):
            raise RealLoopReadinessError(
                "upstream gate evidence names must not repeat"
            )
        if any(not _is_canonical_digest(value) for value in upstream_hashes):
            raise RealLoopReadinessError(
                "upstream gate evidence values must be lowercase SHA-256"
            )
        if len(upstream_hashes) != len(set(upstream_hashes)):
            raise RealLoopReadinessError(
                "upstream gate evidence hashes must not be reused across prerequisites"
            )
        upstream_refs = tuple(
            (str(name), _text(value))
            for name, value in self.upstream_gate_evidence_refs
        )
        ref_names = [name for name, _ in upstream_refs]
        ref_values = [value for _, value in upstream_refs]
        if len(ref_names) != len(set(ref_names)):
            raise RealLoopReadinessError("upstream gate evidence ref names must not repeat")
        if any(not _SAFE_EVIDENCE_REF_RE.fullmatch(value) for value in ref_values):
            raise RealLoopReadinessError("upstream gate evidence refs must be opaque identifiers")
        if len(ref_values) != len(set(ref_values)):
            raise RealLoopReadinessError("upstream gate evidence refs must not be reused")
        if self.execution_ready:
            if not _SHA256_RE.fullmatch(self.generalization_evidence_sha256):
                raise RealLoopReadinessError(
                    "execution-ready readiness requires a generalization evidence hash"
                )
            if not _SHA256_RE.fullmatch(self.semantics_binding_sha256):
                raise RealLoopReadinessError(
                    "execution-ready readiness requires a semantics binding hash"
                )
            if self.semantics_binding_matched is not True:
                raise RealLoopReadinessError(
                    "execution-ready readiness requires a matched semantics binding"
                )
            if tuple(upstream_names) != REAL_LOOP_UPSTREAM_GATE_NAMES:
                raise RealLoopReadinessError(
                    "execution-ready readiness requires every upstream gate evidence hash"
                )
            if tuple(ref_names) != REAL_LOOP_UPSTREAM_GATE_NAMES:
                raise RealLoopReadinessError(
                    "execution-ready readiness requires every upstream gate evidence ref"
                )
        if upstream_names != ref_names:
            raise RealLoopReadinessError(
                "upstream gate evidence refs and hashes must cover the same prerequisites"
            )
        issues = tuple(self.issues)
        batch_refs_by_project = tuple(
            (str(project_id), tuple(sorted(str(ref) for ref in refs)))
            for project_id, refs in self.batch_refs_by_project
        )
        project_ids = [project_id for project_id, _ in batch_refs_by_project]
        if len(project_ids) != len(set(project_ids)):
            raise RealLoopReadinessError(
                "batch_refs_by_project must not repeat project IDs"
            )
        expected_ready = not issues and self.status == "ready_for_controlled_execution"
        if self.execution_ready != expected_ready:
            raise RealLoopReadinessError(
                "execution_ready does not match readiness issues"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "batch_refs_by_project", batch_refs_by_project)
        object.__setattr__(self, "upstream_gate_evidence_sha256", upstream_gate_evidence)
        object.__setattr__(self, "upstream_gate_evidence_refs", upstream_refs)
        object.__setattr__(self, "report_sha256", _sha256(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "execution_ready": self.execution_ready,
            "acceptance_complete": self.acceptance_complete,
            "project_count": self.project_count,
            "scenario_count": self.scenario_count,
            "generalization_evidence_sha256": self.generalization_evidence_sha256,
            "semantics_binding_matched": self.semantics_binding_matched,
            "semantics_binding_sha256": self.semantics_binding_sha256,
            "upstream_gate_evidence_sha256": [
                {"gate": name, "sha256": value}
                for name, value in self.upstream_gate_evidence_sha256
            ],
            "upstream_gate_evidence_refs": [
                {"gate": name, "ref": value}
                for name, value in self.upstream_gate_evidence_refs
            ],
            "batch_refs_by_project": [
                {"project_id": project_id, "batch_refs": list(refs)}
                for project_id, refs in self.batch_refs_by_project
            ],
            "issues": [item.to_dict() for item in self.issues],
            "runtime_activation_permitted": self.runtime_activation_permitted,
            "provider_call_permitted": self.provider_call_permitted,
            "write_permitted": self.write_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def assess_real_loop_readiness(
    sources: Iterable[RealLoopSource],
    scenarios: Iterable[RealLoopScenario],
    gates: RealLoopGateInput,
    prompt_manifest: Iterable[Any] | None = None,
) -> RealLoopReadinessReport:
    """Validate a five-project LOOP manifest without starting or mutating anything.

    ``prompt_manifest`` is required for a controlled readiness assessment.  The
    optional type annotation preserves a useful diagnostic for legacy callers,
    but omission is fail-closed and cannot produce an execution-ready report.
    """

    source_rows = tuple(sources)
    scenario_rows = tuple(scenarios)
    issues: list[RealLoopIssue] = []
    source_by_project: dict[str, RealLoopSource] = {}
    batch_refs_by_project: dict[str, tuple[str, ...]] = {}

    prompt_by_ref: dict[str, Any] = {}
    if prompt_manifest is None:
        issues.append(
            RealLoopIssue(
                RealLoopIssueCode.PROMPT_MANIFEST_MISSING,
                "prompt_manifest",
                "controlled LOOP readiness requires the exact auditable prompt manifest",
            )
        )
    else:
        from .monitoring_real_loop_prompt_manifest import (
            RealLoopPromptSpec,
            assess_real_loop_prompt_manifest,
        )

        prompt_rows = tuple(prompt_manifest)
        prompt_report = assess_real_loop_prompt_manifest(prompt_rows)
        for prompt_issue in prompt_report.issues:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.PROMPT_MANIFEST_MISMATCH,
                    prompt_issue.subject,
                    f"{prompt_issue.code.value}: {prompt_issue.detail}",
                )
            )
        for prompt_row in prompt_rows:
            if isinstance(prompt_row, RealLoopPromptSpec):
                prompt_by_ref[prompt_row.prompt_id] = prompt_row
    for source in sorted(
        source_rows, key=lambda item: (item.project_id, item.listing_ref)
    ):
        project_id = _text(source.project_id)
        if project_id in source_by_project:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.PROJECT_DUPLICATE,
                    project_id,
                    "one source manifest is required per project",
                )
            )
            continue
        source_by_project[project_id] = source
        _source_hash(source.protocol_sha256, f"{project_id}.protocol", issues)
        _source_hash(source.listing_sha256, f"{project_id}.listing", issues)
        if (
            source.listing_class not in ELIGIBLE_LISTING_CLASSES
            or source.source_status != "confirmed"
        ):
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.SOURCE_NOT_ELIGIBLE,
                    project_id,
                    "controlled LOOP requires a confirmed raw_full_snapshot or raw_locked_snapshot; processed/restored/comparison sources are not promoted",
                )
            )
        raw_batch_count = source.batch_count
        if isinstance(raw_batch_count, bool) or not isinstance(raw_batch_count, int):
            batch_count = -1
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
                    project_id,
                    "batch_count must be an integer",
                )
            )
        else:
            batch_count = raw_batch_count
        if batch_count < 2:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.BATCH_COVERAGE_INSUFFICIENT,
                    project_id,
                    "daily incremental LOOP requires two or more traceable full batches",
                )
            )
        try:
            batches = tuple(source.batches or ())
        except TypeError:
            batches = ()
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
                    project_id,
                    "batches must be an iterable of explicit batch evidence rows",
                )
            )
        if batch_count != len(batches):
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
                    project_id,
                    "batch_count must equal the explicit batch evidence rows",
                )
            )
        if len(batches) < 2:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
                    project_id,
                    "each controlled project requires at least two explicit full-batch evidence rows",
                )
            )
        batch_refs: set[str] = set()
        batch_hashes: set[str] = set()
        for index, batch in enumerate(batches):
            subject = f"{project_id}.batch[{index}]"
            if not isinstance(batch, RealLoopBatch):
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
                        subject,
                        "batch evidence rows must use the RealLoopBatch contract",
                    )
                )
                continue
            batch_ref = _text(batch.batch_ref)
            if not batch_ref or batch_ref in batch_refs:
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.BATCH_DUPLICATE,
                        subject,
                        "batch_ref must be non-empty and unique within a project",
                    )
                )
            batch_refs.add(batch_ref)
            batch_hash = _text(batch.listing_sha256)
            if batch_hash in batch_hashes:
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.BATCH_DUPLICATE,
                        subject,
                        "full-batch listing SHA-256 values must be unique within a project",
                    )
                )
            batch_hashes.add(batch_hash)
            _source_hash(batch_hash, subject, issues)
            try:
                date.fromisoformat(_text(batch.snapshot_date))
            except ValueError:
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
                        subject,
                        "snapshot_date must be an ISO calendar date",
                    )
                )
            if (
                batch.listing_class not in ELIGIBLE_LISTING_CLASSES
                or batch.source_status != "confirmed"
                or batch.full_snapshot_proven is not True
            ):
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
                        subject,
                        "each batch must be confirmed, eligible and explicitly proven full",
                    )
                )
        if batches and _text(source.listing_sha256) not in batch_hashes:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.BATCH_EVIDENCE_INCOMPLETE,
                    project_id,
                    "source listing SHA-256 must be represented by one explicit batch row",
                )
            )
        batch_refs_by_project[project_id] = tuple(sorted(batch_refs))

    observed_projects = set(source_by_project)
    required_projects = set(REAL_LOOP_PROJECT_IDS)
    if observed_projects != required_projects:
        issues.append(
            RealLoopIssue(
                RealLoopIssueCode.PROJECT_SET_MISMATCH,
                "project_set",
                f"required={sorted(required_projects)}, observed={sorted(observed_projects)}",
            )
        )

    scenario_ids: set[str] = set()
    prompt_hashes: set[str] = set()
    coverage: dict[tuple[str, str, str], int] = {}
    for scenario in sorted(
        scenario_rows,
        key=lambda item: (item.project_id, item.role, item.task_type, item.scenario_id),
    ):
        if scenario.scenario_id in scenario_ids:
            raise RealLoopReadinessError(
                f"duplicate scenario_id: {scenario.scenario_id}"
            )
        scenario_ids.add(scenario.scenario_id)
        prompt_hash = (
            scenario.prompt_sha256
            if isinstance(scenario.prompt_sha256, str)
            else ""
        )
        if not _is_canonical_digest(scenario.prompt_sha256):
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.SOURCE_HASH_INVALID,
                    scenario.scenario_id,
                    "prompt_sha256 must be a lowercase SHA-256",
                )
            )
        if prompt_hash in prompt_hashes:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.PROMPT_HASH_DUPLICATE,
                    scenario.scenario_id,
                    "each project/role/task scenario requires a distinct prompt hash",
                )
            )
        prompt_hashes.add(prompt_hash)
        prompt_ref = _text(scenario.prompt_ref)
        if not prompt_ref:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.PROMPT_MANIFEST_MISSING,
                    scenario.scenario_id,
                    "scenario must reference one exact prompt manifest row",
                )
            )
        else:
            prompt_row = prompt_by_ref.get(prompt_ref)
            if prompt_row is None:
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.PROMPT_MANIFEST_MISMATCH,
                        scenario.scenario_id,
                        "scenario prompt_ref is not present in the exact prompt manifest",
                    )
                )
            elif not (
                prompt_row.scenario_id == scenario.scenario_id
                and prompt_row.project_id == scenario.project_id
                and prompt_row.role == scenario.role
                and prompt_row.task_type == scenario.task_type
                and prompt_row.prompt_sha256 == prompt_hash
            ):
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.PROMPT_MANIFEST_MISMATCH,
                        scenario.scenario_id,
                        "prompt_ref, project, role, task and exact prompt hash must match the manifest row",
                    )
                )
        if scenario.model_route not in REAL_LOOP_MODEL_ROUTES:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.MODEL_ROUTE_INVALID,
                    scenario.scenario_id,
                    "model route is outside the approved day/night test routes",
                )
            )
        if scenario.project_id not in required_projects:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.PROJECT_SET_MISMATCH,
                    scenario.scenario_id,
                    "scenario project is outside the five-project LOOP",
                )
            )
        if scenario.role not in REAL_LOOP_ROLES:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.ROLE_COVERAGE_MISSING,
                    scenario.scenario_id,
                    "scenario role must be engineer or senior_medical_monitor",
                )
            )
        if scenario.task_type not in REAL_LOOP_TASK_TYPES:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.TASK_COVERAGE_MISSING,
                    scenario.scenario_id,
                    "scenario task is not one of the four required product-AI tasks",
                )
            )
        if scenario.run_status not in ALLOWED_SCENARIO_STATUSES:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.SCENARIO_STATUS_INVALID,
                    scenario.scenario_id,
                    "scenario run_status must be not_run, passed, failed or blocked",
                )
            )
        elif scenario.run_status in {"failed", "blocked"}:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.SCENARIO_EXECUTION_FAILED,
                    scenario.scenario_id,
                    "a failed or blocked scenario must be repaired and rerun before LOOP acceptance",
                )
            )
        coverage[(scenario.project_id, scenario.role, scenario.task_type)] = (
            coverage.get((scenario.project_id, scenario.role, scenario.task_type), 0)
            + 1
        )

    for project_id in REAL_LOOP_PROJECT_IDS:
        for role in REAL_LOOP_ROLES:
            for task_type in REAL_LOOP_TASK_TYPES:
                if coverage.get((project_id, role, task_type), 0) < 1:
                    issues.append(
                        RealLoopIssue(
                            RealLoopIssueCode.TASK_COVERAGE_MISSING,
                            f"{project_id}:{role}:{task_type}",
                            "each project requires both roles to run a distinct prompt for every required task",
                        )
                    )

    gate_values = {
        "b6_approved": gates.b6_approved,
        "approved_input_ready": gates.approved_input_ready,
        "source_token_revalidated": gates.source_token_revalidated,
        "aggregate_cas_complete": gates.aggregate_cas_complete,
        "runtime_identity_verified": gates.runtime_identity_verified,
        "browser_acceptance_complete": gates.browser_acceptance_complete,
        "scientific_acceptance_complete": gates.scientific_acceptance_complete,
        "generalization_evidence_complete": gates.generalization_evidence_complete,
        "semantics_binding_matched": gates.semantics_binding_matched,
    }
    upstream_gate_inputs = {
        "b6_approved": gates.b6_evidence_sha256,
        "approved_input_ready": gates.approved_input_evidence_sha256,
        "source_token_revalidated": gates.source_token_evidence_sha256,
        "aggregate_cas_complete": gates.aggregate_cas_evidence_sha256,
        "runtime_identity_verified": gates.runtime_identity_evidence_sha256,
    }
    upstream_ref_inputs = {
        "b6_approved": gates.b6_evidence_ref,
        "approved_input_ready": gates.approved_input_evidence_ref,
        "source_token_revalidated": gates.source_token_evidence_ref,
        "aggregate_cas_complete": gates.aggregate_cas_evidence_ref,
        "runtime_identity_verified": gates.runtime_identity_evidence_ref,
    }
    for name, value in gate_values.items():
        if not isinstance(value, bool):
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.GATE_VALUE_INVALID,
                    name,
                    "all readiness and acceptance gate values must be strict booleans; string or numeric coercion is not accepted",
                )
            )
        elif (
            name
            in {
                "b6_approved",
                "approved_input_ready",
                "source_token_revalidated",
                "aggregate_cas_complete",
                "runtime_identity_verified",
                "generalization_evidence_complete",
            }
            and value is not True
        ):
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.GATE_NOT_READY,
                    name,
                    "controlled LOOP prerequisite is not explicitly proven",
                )
            )

    raw_semantics_binding_hash = gates.semantics_binding_sha256
    semantics_binding_hash = (
        raw_semantics_binding_hash
        if isinstance(raw_semantics_binding_hash, str)
        else ""
    )
    if raw_semantics_binding_hash and not _is_canonical_digest(
        raw_semantics_binding_hash
    ):
        issues.append(
            RealLoopIssue(
                RealLoopIssueCode.SEMANTICS_BINDING_INVALID,
                "semantics_binding_sha256",
                "controlled LOOP requires the current-manifest semantics binding SHA-256",
            )
        )
        semantics_binding_hash = ""
    if gates.semantics_binding_matched is True and not semantics_binding_hash:
        issues.append(
            RealLoopIssue(
                RealLoopIssueCode.SEMANTICS_BINDING_INVALID,
                "semantics_binding_sha256",
                "a matched semantics binding must carry its explicit SHA-256",
            )
        )
    if any(
        gate_values[name] is True
        for name in (
            "b6_approved",
            "approved_input_ready",
            "source_token_revalidated",
            "aggregate_cas_complete",
            "runtime_identity_verified",
        )
    ) and gates.semantics_binding_matched is not True:
        issues.append(
            RealLoopIssue(
                RealLoopIssueCode.SEMANTICS_BINDING_NOT_READY,
                "semantics_binding_matched",
                "controlled LOOP prerequisites require an identity-bound semantics snapshot",
            )
        )

    upstream_hashes: dict[str, str] = {}
    upstream_refs: dict[str, str] = {}
    seen_upstream_hashes: dict[str, str] = {}
    seen_upstream_refs: dict[str, str] = {}
    for gate_name in REAL_LOOP_UPSTREAM_GATE_NAMES:
        raw_hash_value = upstream_gate_inputs[gate_name]
        raw_hash = raw_hash_value if isinstance(raw_hash_value, str) else ""
        raw_ref = _text(upstream_ref_inputs[gate_name])
        pair_valid = True
        if raw_ref and not _SAFE_EVIDENCE_REF_RE.fullmatch(raw_ref):
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.UPSTREAM_EVIDENCE_REF_INVALID,
                    gate_name,
                    "upstream prerequisite evidence ref must be an opaque identifier",
                )
            )
            raw_ref = ""
            pair_valid = False
        if raw_hash_value and not _is_canonical_digest(raw_hash_value):
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.UPSTREAM_EVIDENCE_HASH_INVALID,
                    gate_name,
                    "upstream prerequisite evidence must be a lowercase SHA-256",
                )
            )
            raw_hash = ""
            pair_valid = False
        if gate_values[gate_name] is True and not raw_hash:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.UPSTREAM_EVIDENCE_HASH_INVALID,
                    gate_name,
                    "a true controlled prerequisite must bind one explicit upstream evidence SHA-256",
                )
            )
            pair_valid = False
        if gate_values[gate_name] is True and not raw_ref:
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.UPSTREAM_EVIDENCE_PAIR_INCOMPLETE,
                    gate_name,
                    "a true controlled prerequisite must bind both an evidence ref and its SHA-256",
                )
            )
            pair_valid = False
        if bool(raw_hash) != bool(raw_ref):
            issues.append(
                RealLoopIssue(
                    RealLoopIssueCode.UPSTREAM_EVIDENCE_PAIR_INCOMPLETE,
                    gate_name,
                    "upstream evidence ref and SHA-256 must be supplied as a pair",
                )
            )
            pair_valid = False
        hash_duplicate = False
        if raw_hash:
            previous_gate = seen_upstream_hashes.get(raw_hash)
            if previous_gate is not None:
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.UPSTREAM_EVIDENCE_HASH_DUPLICATE,
                        gate_name,
                        f"upstream evidence hash is already bound to {previous_gate}; one artifact cannot prove two prerequisites",
                    )
                )
                hash_duplicate = True
            else:
                seen_upstream_hashes[raw_hash] = gate_name
        ref_duplicate = False
        if raw_ref:
            previous_ref_gate = seen_upstream_refs.get(raw_ref)
            if previous_ref_gate is not None:
                issues.append(
                    RealLoopIssue(
                        RealLoopIssueCode.UPSTREAM_EVIDENCE_REF_DUPLICATE,
                        gate_name,
                        f"upstream evidence ref is already bound to {previous_ref_gate}; one artifact ref cannot prove two prerequisites",
                    )
                )
                ref_duplicate = True
            else:
                seen_upstream_refs[raw_ref] = gate_name
        if hash_duplicate or ref_duplicate:
            pair_valid = False
        # A blocked report must remain structurally self-consistent.  Keep an
        # upstream prerequisite only when its opaque ref and SHA-256 form one
        # valid, unique pair; invalid or duplicate halves are never emitted as
        # if they were independently usable evidence.
        if pair_valid and raw_hash and raw_ref:
            upstream_hashes[gate_name] = raw_hash
            upstream_refs[gate_name] = raw_ref

    raw_generalization_hash = gates.generalization_evidence_sha256
    generalization_hash = (
        raw_generalization_hash
        if isinstance(raw_generalization_hash, str)
        else ""
    )
    if not _is_canonical_digest(raw_generalization_hash):
        issues.append(
            RealLoopIssue(
                RealLoopIssueCode.GENERALIZATION_EVIDENCE_INVALID,
                "generalization_evidence_sha256",
                "controlled LOOP requires the upstream generalization profile snapshot SHA-256",
            )
        )
        # Keep the report itself structurally valid while retaining the
        # fail-closed diagnostic in ``issues``.  Invalid external evidence is
        # never copied into a report hash field that claims SHA-256 semantics.
        generalization_hash = ""

    acceptance_complete = (
        gates.browser_acceptance_complete is True
        and gates.scientific_acceptance_complete is True
    )
    all_scenarios_passed = bool(scenario_rows) and all(
        scenario.run_status == "passed" for scenario in scenario_rows
    )
    if all_scenarios_passed and not acceptance_complete:
        issues.append(
            RealLoopIssue(
                RealLoopIssueCode.ACCEPTANCE_NOT_COMPLETE,
                "browser_science_acceptance",
                "browser and scientific acceptance must be recorded after execution; a readiness manifest cannot infer them",
            )
        )

    return RealLoopReadinessReport(
        status="ready_for_controlled_execution" if not issues else "blocked",
        execution_ready=not issues,
        acceptance_complete=acceptance_complete,
        project_count=len(source_by_project),
        scenario_count=len(scenario_rows),
        issues=tuple(issues),
        generalization_evidence_sha256=generalization_hash,
        semantics_binding_matched=gates.semantics_binding_matched,
        semantics_binding_sha256=semantics_binding_hash,
        upstream_gate_evidence_sha256=tuple(
            (gate_name, upstream_hashes[gate_name])
            for gate_name in REAL_LOOP_UPSTREAM_GATE_NAMES
            if gate_name in upstream_hashes
        ),
        upstream_gate_evidence_refs=tuple(
            (gate_name, upstream_refs[gate_name])
            for gate_name in REAL_LOOP_UPSTREAM_GATE_NAMES
            if gate_name in upstream_refs
        ),
        batch_refs_by_project=tuple(
            (project_id, batch_refs_by_project.get(project_id, ()))
            for project_id in sorted(source_by_project)
        ),
    )


__all__ = [
    "ALLOWED_SCENARIO_STATUSES",
    "ELIGIBLE_LISTING_CLASSES",
    "REAL_LOOP_MODEL_ROUTES",
    "REAL_LOOP_PROJECT_IDS",
    "REAL_LOOP_ROLES",
    "REAL_LOOP_UPSTREAM_GATE_NAMES",
    "REAL_LOOP_TASK_TYPES",
    "RealLoopGateInput",
    "RealLoopBatch",
    "RealLoopIssue",
    "RealLoopIssueCode",
    "RealLoopReadinessError",
    "RealLoopReadinessReport",
    "RealLoopScenario",
    "RealLoopSource",
    "assess_real_loop_readiness",
]
