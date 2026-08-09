"""Auditable prompt manifest for the five-project medical-monitoring LOOP.

The readiness and execution contracts deliberately carry opaque prompt hashes,
but a hash alone is not enough for a reviewer to reproduce a planned test.  This
module keeps the exact prompt text, its stable scenario reference and its
content hash together in a deterministic, offline manifest.  It never calls a
provider, reads a project source, starts a runtime or grants any authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Iterable


REAL_LOOP_PROMPT_MANIFEST_SCHEMA_VERSION = (
    "medical_monitoring_real_loop_prompt_manifest_v2"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_UNSAFE_PROMPT_MARKERS = ("/Users/", "/private/", "file://", "Bearer ", "sk-")


class RealLoopPromptManifestError(ValueError):
    """Raised when a prompt manifest row is structurally unsafe."""


class RealLoopPromptIssueCode(str, Enum):
    INVALID_ROW = "invalid_row"
    DUPLICATE_PROMPT_REF = "duplicate_prompt_ref"
    DUPLICATE_SCENARIO_ID = "duplicate_scenario_id"
    DUPLICATE_PROMPT_HASH = "duplicate_prompt_hash"
    DUPLICATE_VARIANT = "duplicate_variant"
    PROJECT_SET_MISMATCH = "project_set_mismatch"
    COVERAGE_MISSING = "coverage_missing"
    SCENARIO_ID_MISMATCH = "scenario_id_mismatch"
    PROMPT_CONTEXT_MISSING = "prompt_context_missing"
    PROMPT_MANIFEST_EMPTY = "prompt_manifest_empty"


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RealLoopPromptManifestError(f"{field_name} must be a non-empty string")
    return value


def _safe_id(value: Any, field_name: str) -> str:
    text = _require_text(value, field_name).strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise RealLoopPromptManifestError(
            f"{field_name} must be an opaque identifier without whitespace"
        )
    return text


def _content_sha256(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise RealLoopPromptManifestError(
            "prompt manifest payload must be JSON-serializable"
        ) from exc


@dataclass(frozen=True)
class RealLoopPromptIssue:
    code: RealLoopPromptIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "subject", _require_text(self.subject, "issue subject").strip()
        )
        object.__setattr__(
            self, "detail", _require_text(self.detail, "issue detail").strip()
        )

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopPromptSpec:
    """One exact prompt bound to one planned LOOP scenario."""

    prompt_id: str
    scenario_id: str
    project_id: str
    role: str
    task_type: str
    variant_key: str
    prompt_text: str
    prompt_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "prompt_id",
            "scenario_id",
            "project_id",
            "role",
            "task_type",
            "variant_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _safe_id(getattr(self, field_name), field_name),
            )
        prompt_text = _require_text(self.prompt_text, "prompt_text")
        if any(marker in prompt_text for marker in _UNSAFE_PROMPT_MARKERS):
            raise RealLoopPromptManifestError(
                "prompt_text must not contain local paths or credential-like markers"
            )
        object.__setattr__(self, "prompt_text", prompt_text)
        declared_hash = _require_text(self.prompt_sha256, "prompt_sha256")
        if not _SHA256_RE.fullmatch(declared_hash):
            raise RealLoopPromptManifestError(
                "prompt_sha256 must be a lowercase SHA-256"
            )
        actual_hash = _content_sha256(prompt_text)
        if declared_hash != actual_hash:
            raise RealLoopPromptManifestError(
                "prompt_sha256 must equal the exact UTF-8 prompt_text hash"
            )
        object.__setattr__(self, "prompt_sha256", declared_hash)
        required_markers = (
            f"Scenario ID: {self.scenario_id}",
            f"Project identity: {self.project_id}",
            f"Role: {self.role}",
            f"Task type: {self.task_type}",
        )
        if any(marker not in prompt_text for marker in required_markers):
            raise RealLoopPromptManifestError(
                "prompt_text must carry its scenario, project, role and task identity"
            )

    def to_dict(self, *, include_prompt_text: bool = True) -> dict[str, str]:
        payload = {
            "prompt_id": self.prompt_id,
            "scenario_id": self.scenario_id,
            "project_id": self.project_id,
            "role": self.role,
            "task_type": self.task_type,
            "variant_key": self.variant_key,
            "prompt_sha256": self.prompt_sha256,
        }
        if include_prompt_text:
            payload["prompt_text"] = self.prompt_text
        return payload


@dataclass(frozen=True)
class RealLoopPromptManifestReport:
    """Deterministic manifest assessment; it never grants runtime authority."""

    status: str
    prompt_count: int
    issues: tuple[RealLoopPromptIssue, ...]
    manifest_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.status not in {"valid", "blocked"}:
            raise RealLoopPromptManifestError("invalid prompt manifest status")
        issues = tuple(self.issues)
        if (self.status == "valid") != (not issues):
            raise RealLoopPromptManifestError("invalid prompt manifest status")
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "manifest_sha256", _canonical_hash(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": REAL_LOOP_PROMPT_MANIFEST_SCHEMA_VERSION,
            "status": self.status,
            "prompt_count": self.prompt_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "manifest_sha256": self.manifest_sha256,
        }


def _canonical_hash(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _manifest_hash(rows: Iterable[RealLoopPromptSpec]) -> str:
    payload = {
        "schema_version": REAL_LOOP_PROMPT_MANIFEST_SCHEMA_VERSION,
        "prompts": [
            row.to_dict(include_prompt_text=True)
            for row in sorted(rows, key=lambda item: item.prompt_id)
        ],
    }
    return _canonical_hash(payload)


def build_real_loop_prompt_manifest() -> tuple[RealLoopPromptSpec, ...]:
    """Build the 40 deterministic project/role/task-specific prompts."""

    from .monitoring_real_loop_readiness import (
        REAL_LOOP_PROJECT_IDS,
        REAL_LOOP_ROLES,
        REAL_LOOP_TASK_TYPES,
    )

    project_context = {
        "proj_rux_03_002": (
            "RUX-03-002",
            "visit schedule, visit-window ordering and protocol-deviation evidence",
        ),
        "proj_mgk10_sar_real": (
            "MG-K10-SAR",
            "longitudinal subject safety, efficacy and site-level risk evidence",
        ),
        "proj_my008_3_02_candidate": (
            "MY008-3-02",
            "PNH study data, treatment exposure and source-bounded risk evidence",
        ),
        "proj_my008_3_01_candidate": (
            "MY008-3-01",
            "PNH study data, visit/laboratory coherence and source-bounded risk evidence",
        ),
        "proj_my009_uc": (
            "MY009-UC",
            "ulcerative-colitis study data, AE/MH/CM coherence and trend signals",
        ),
    }
    role_guidance = {
        "engineer": (
            "Act as the test engineer. Check schema, identity, source references, "
            "deterministic ordering and uncertainty handling; never invent a medical conclusion."
        ),
        "senior_medical_monitor": (
            "Act as the senior medical monitor. Prioritize clinically meaningful risk, "
            "temporal coherence and explicit evidence; label review questions instead of guessing."
        ),
    }
    task_guidance = {
        "field_semantic_mapping": (
            "Map supplied raw fields to semantic medical-monitoring concepts, preserving "
            "source labels, units, missingness and one-to-many ambiguity."
        ),
        "protocol_clause_extraction": (
            "Extract protocol clauses with clause-level evidence, visit scope, timing, "
            "exceptions and a clear uncertainty state."
        ),
        "risk_evidence_summary": (
            "Summarize subject, site and study risk evidence with direction of trend, "
            "supporting event references and the smallest useful follow-up checklist."
        ),
        "interactive_follow_up": (
            "Answer a follow-up review question by first restating the evidence boundary, "
            "then separating confirmed facts, unresolved questions and the next source check."
        ),
    }
    rows: list[RealLoopPromptSpec] = []
    for project_id in REAL_LOOP_PROJECT_IDS:
        project_title, project_focus = project_context[project_id]
        for role in REAL_LOOP_ROLES:
            for task_type in REAL_LOOP_TASK_TYPES:
                scenario_id = f"{project_id}:{role}:{task_type}"
                prompt_id = f"rrprompt:{project_id}:{role}:{task_type}:v1"
                variant_key = f"{project_title}:{role}:{task_type}:v1"
                prompt_text = "\n".join(
                    (
                        "Controlled medical-monitoring real-LOOP prompt v1.",
                        f"Scenario ID: {scenario_id}",
                        f"Project identity: {project_id}",
                        f"Project title: {project_title}",
                        f"Project focus: {project_focus}",
                        f"Role: {role}",
                        f"Task type: {task_type}",
                        f"Role instruction: {role_guidance[role]}",
                        f"Task instruction: {task_guidance[task_type]}",
                        "Use only the opaque source, batch and evidence references supplied "
                        "by the runner. Preserve exact values and dates; do not infer missing data.",
                        "Return: findings, evidence_refs, uncertainty_state, follow_up, "
                        "and a short reviewer-facing rationale. A senior medical monitor "
                        "must confirm any clinical interpretation before downstream use.",
                    )
                )
                rows.append(
                    RealLoopPromptSpec(
                        prompt_id=prompt_id,
                        scenario_id=scenario_id,
                        project_id=project_id,
                        role=role,
                        task_type=task_type,
                        variant_key=variant_key,
                        prompt_text=prompt_text,
                        prompt_sha256=_content_sha256(prompt_text),
                    )
                )
    return tuple(rows)


def assess_real_loop_prompt_manifest(
    manifest: Iterable[RealLoopPromptSpec],
) -> RealLoopPromptManifestReport:
    """Validate exact coverage, identity markers and prompt uniqueness."""

    from .monitoring_real_loop_readiness import (
        REAL_LOOP_PROJECT_IDS,
        REAL_LOOP_ROLES,
        REAL_LOOP_TASK_TYPES,
    )

    try:
        rows = tuple(manifest)
    except TypeError as exc:
        raise RealLoopPromptManifestError("prompt manifest must be iterable") from exc
    issues: list[RealLoopPromptIssue] = []
    if not rows:
        issues.append(
            RealLoopPromptIssue(
                RealLoopPromptIssueCode.PROMPT_MANIFEST_EMPTY,
                "manifest",
                "the real LOOP requires a non-empty exact prompt manifest",
            )
        )
    prompt_ids: set[str] = set()
    scenario_ids: set[str] = set()
    prompt_hashes: set[str] = set()
    variants: set[str] = set()
    coverage: set[tuple[str, str, str]] = set()
    expected_projects = set(REAL_LOOP_PROJECT_IDS)
    expected_keys = {
        (project_id, role, task_type)
        for project_id in REAL_LOOP_PROJECT_IDS
        for role in REAL_LOOP_ROLES
        for task_type in REAL_LOOP_TASK_TYPES
    }
    for row in rows:
        if not isinstance(row, RealLoopPromptSpec):
            issues.append(
                RealLoopPromptIssue(
                    RealLoopPromptIssueCode.INVALID_ROW,
                    "manifest",
                    "all rows must be RealLoopPromptSpec instances",
                )
            )
            continue
        if row.prompt_id in prompt_ids:
            issues.append(
                RealLoopPromptIssue(
                    RealLoopPromptIssueCode.DUPLICATE_PROMPT_REF,
                    row.prompt_id,
                    "prompt_id must be unique",
                )
            )
        prompt_ids.add(row.prompt_id)
        if row.scenario_id in scenario_ids:
            issues.append(
                RealLoopPromptIssue(
                    RealLoopPromptIssueCode.DUPLICATE_SCENARIO_ID,
                    row.scenario_id,
                    "scenario_id must be unique",
                )
            )
        scenario_ids.add(row.scenario_id)
        if row.prompt_sha256 in prompt_hashes:
            issues.append(
                RealLoopPromptIssue(
                    RealLoopPromptIssueCode.DUPLICATE_PROMPT_HASH,
                    row.prompt_id,
                    "each scenario must carry a distinct exact prompt hash",
                )
            )
        prompt_hashes.add(row.prompt_sha256)
        if row.variant_key in variants:
            issues.append(
                RealLoopPromptIssue(
                    RealLoopPromptIssueCode.DUPLICATE_VARIANT,
                    row.prompt_id,
                    "variant_key must identify one project/role/task prompt",
                )
            )
        variants.add(row.variant_key)
        key = (row.project_id, row.role, row.task_type)
        coverage.add(key)
        if row.project_id not in expected_projects:
            issues.append(
                RealLoopPromptIssue(
                    RealLoopPromptIssueCode.PROJECT_SET_MISMATCH,
                    row.prompt_id,
                    "prompt project is outside the canonical five-project LOOP",
                )
            )
        expected_scenario_id = f"{row.project_id}:{row.role}:{row.task_type}"
        if row.scenario_id != expected_scenario_id:
            issues.append(
                RealLoopPromptIssue(
                    RealLoopPromptIssueCode.SCENARIO_ID_MISMATCH,
                    row.prompt_id,
                    "scenario_id must be project:role:task_type",
                )
            )
        for marker in (
            f"Scenario ID: {row.scenario_id}",
            f"Project identity: {row.project_id}",
            f"Role: {row.role}",
            f"Task type: {row.task_type}",
        ):
            if marker not in row.prompt_text:
                issues.append(
                    RealLoopPromptIssue(
                        RealLoopPromptIssueCode.PROMPT_CONTEXT_MISSING,
                        row.prompt_id,
                        f"prompt_text must contain {marker!r}",
                    )
                )
    for key in sorted(expected_keys - coverage):
        issues.append(
            RealLoopPromptIssue(
                RealLoopPromptIssueCode.COVERAGE_MISSING,
                ":".join(key),
                "each canonical project/role/task combination requires one exact prompt",
            )
        )
    if len(rows) != len(expected_keys):
        issues.append(
            RealLoopPromptIssue(
                RealLoopPromptIssueCode.COVERAGE_MISSING,
                "manifest",
                f"expected exactly {len(expected_keys)} prompt rows, observed {len(rows)}",
            )
        )
    ordered_issues = tuple(
        sorted(
            issues, key=lambda issue: (issue.subject, issue.code.value, issue.detail)
        )
    )
    return RealLoopPromptManifestReport(
        status="valid" if not ordered_issues else "blocked",
        prompt_count=len(rows),
        issues=ordered_issues,
    )


def real_loop_prompt_manifest_payload(
    manifest: Iterable[RealLoopPromptSpec],
) -> dict[str, Any]:
    """Return the hash-bound, JSON-ready manifest payload for an audit record."""

    rows = tuple(manifest)
    report = assess_real_loop_prompt_manifest(rows)
    return {
        "schema_version": REAL_LOOP_PROMPT_MANIFEST_SCHEMA_VERSION,
        "status": report.status,
        "prompt_count": len(rows),
        "manifest_sha256": _manifest_hash(rows),
        "report_sha256": report.manifest_sha256,
        "issues": [issue.to_dict() for issue in report.issues],
        "prompts": [
            row.to_dict(include_prompt_text=True)
            for row in sorted(rows, key=lambda item: item.prompt_id)
            if isinstance(row, RealLoopPromptSpec)
        ],
    }


__all__ = [
    "REAL_LOOP_PROMPT_MANIFEST_SCHEMA_VERSION",
    "RealLoopPromptIssue",
    "RealLoopPromptIssueCode",
    "RealLoopPromptManifestError",
    "RealLoopPromptManifestReport",
    "RealLoopPromptSpec",
    "assess_real_loop_prompt_manifest",
    "build_real_loop_prompt_manifest",
    "real_loop_prompt_manifest_payload",
]
