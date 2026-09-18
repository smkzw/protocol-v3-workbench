"""Immutable, closed value objects for the Agent⑤ orchestration surface.

Design authority: Protocol v3 multi-agent rearchitecture design sections 5.3
(versioned skill registry), 5.4 (Agent⑤ coordination boundary), 18 (run
isolation, recovery and error handling) and the frozen plan Task 1.9.  Every
object in this module is immutable (Pydantic ``frozen=True``), closed
(``extra="forbid"``) and deterministic:

* :class:`PinnedSkill` / :class:`TemplatePin` / :class:`GraphPin` — approved
  version identities Agent⑤ may pin but never generate or approve;
* :class:`RegistrySelection` — an already-approved, registry-registered skill
  selection; per-skill hashes are derived from the canonical
  :class:`SkillDefinition` material hash, so an unpinned or mutable selection
  is rejected at construction;
* :class:`RunManifest` — pins the Protocol template, graph/schema, skill
  IDs+hashes, source revisions and the StudyDefinition identity/revision/hash;
* :class:`WorkPackageSpec` / :class:`CoordinatorWorkPackage` /
  :class:`WorkPackageGraph` — registered work packages with a deterministic
  dependency order; unknown skills, duplicate identities, missing dependencies
  and cycles are rejected;
* :class:`GateObservation` / :class:`GateSummary` — immutable Gate results
  Agent⑤ may aggregate but never lower, skip or override (the vocabulary has
  no ``skipped`` result at all);
* :class:`ProgressSummary` — a read-only aggregation that reflects run status
  verbatim and can never relabel failed/interrupted/quarantined work as
  complete;
* :class:`DecisionRequest` / :class:`DecisionRequestQueue` — a deterministic
  queue representation of decisions awaiting user confirmation.

None of these objects open a unit of work, touch a repository or mutate
canonical state; they are pure values exchanged across the coordinator
boundary.
"""

from __future__ import annotations

from enum import Enum
import heapq
import json
from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.contracts.workbench_contracts.protocol_v3 import (
    AwareDateTime,
    CanonicalState,
    NonEmptyText,
    NonNegativeInt,
    PositiveRevision,
    Sha256,
    SkillDefinition,
    StableId,
    UnitInterval,
    WorkflowRun,
    WorkflowRunStatus,
)

from app.protocol_workflow.errors import GATE_PHASE

__all__ = [
    "CoordinatorWorkPackage",
    "DecisionRequest",
    "DecisionRequestQueue",
    "GateObservation",
    "GateResult",
    "GateSummary",
    "GraphPin",
    "PinnedSkill",
    "ProgressSummary",
    "RegistrySelection",
    "RunManifest",
    "TemplatePin",
    "WorkPackageGraph",
    "WorkPackageSpec",
    "require_non_empty",
    "require_sha256",
    "require_stable_id",
]


# ---------------------------------------------------------------------------
# Validation helpers (shared with the coordinator for pre-query fail-fast)
# ---------------------------------------------------------------------------

_STABLE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def require_stable_id(value: Any, label: str) -> str:
    """Reject empty or malformed stable ids before any repository/query use."""
    if not isinstance(value, str) or _STABLE_ID_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a non-empty stable id")
    return value


def require_sha256(value: Any, label: str) -> str:
    """Reject values that cannot be a 64-char hex content hash."""
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a 64-char hex sha256")
    return value


def require_non_empty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _unique(values: tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        duplicates = sorted({item for item in values if values.count(item) > 1})
        raise ValueError(f"{label} must not contain duplicate values: {duplicates}")


def _require_tuple(value: Any, label: str) -> None:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be an immutable tuple, not a mutable sequence")


def _default_utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _deterministic_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Approved version identities
# ---------------------------------------------------------------------------


class PinnedSkill(BaseModel):
    """One approved skill identity: registered ID plus its pinned material
    hash.  The hash is the canonical :class:`SkillDefinition` material hash —
    Agent⑤ derives it from an approved object and never invents it."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    skill_definition_id: StableId
    skill_sha256: Sha256


class TemplatePin(BaseModel):
    """Approved Protocol template identity (version + content hash)."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    template_version: NonEmptyText
    template_sha256: Sha256


class GraphPin(BaseModel):
    """Approved graph/schema identity (version + content hash)."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    graph_version: NonEmptyText
    graph_sha256: Sha256


# ---------------------------------------------------------------------------
# Approved registry selection
# ---------------------------------------------------------------------------


class RegistrySelection(BaseModel):
    """An already-approved selection of registered skills.

    Construction is fail-closed: the selection must be an immutable tuple of
    canonical :class:`SkillDefinition` objects (never a mutable sequence), the
    skill IDs must be unique and every skill must be ``FROZEN`` (approved for
    use).  The pinned per-skill hashes are always derived from the immutable
    objects via :meth:`pinned`, so an unpinned or mutable selection cannot be
    represented.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    skills: tuple[SkillDefinition, ...] = Field(min_length=1)

    @field_validator("skills", mode="before")
    @classmethod
    def _skills_must_be_immutable_tuple(cls, value: Any) -> Any:
        _require_tuple(value, "skills")
        return value

    @model_validator(mode="after")
    def _selection_closed_and_approved(self) -> RegistrySelection:
        ids = tuple(skill.skill_definition_id for skill in self.skills)
        _unique(ids, "skill_definition_ids")
        for skill in self.skills:
            if skill.canonical_state is not CanonicalState.FROZEN:
                raise ValueError(
                    f"skill {skill.skill_definition_id!r} is not FROZEN; "
                    "an approved selection may only contain registered frozen skills"
                )
        return self

    def pinned(self) -> tuple[PinnedSkill, ...]:
        """Deterministic (ID-sorted) pinned identities for this selection."""
        return tuple(
            PinnedSkill(
                skill_definition_id=skill.skill_definition_id,
                skill_sha256=skill.material_sha256(),
            )
            for skill in sorted(self.skills, key=lambda item: item.skill_definition_id)
        )

    def skill_by_id(self, skill_definition_id: str) -> Optional[SkillDefinition]:
        for skill in self.skills:
            if skill.skill_definition_id == skill_definition_id:
                return skill
        return None

    def skill_hash(self, skill_definition_id: str) -> Optional[str]:
        skill = self.skill_by_id(skill_definition_id)
        return None if skill is None else skill.material_sha256()


# ---------------------------------------------------------------------------
# Pinned run manifest
# ---------------------------------------------------------------------------


class RunManifest(BaseModel):
    """An immutable pin of every version an Agent⑤ run is bound to.

    The manifest pins the Protocol template, graph/schema, contract schema,
    skill IDs+hashes, source revisions and the StudyDefinition
    identity/revision/hash — all of which must originate from already
    approved inputs.  The source lineage is non-empty (at least one SHA-256,
    matching the canonical :class:`WorkflowRun` contract), unique and
    immutable.  Agent⑤ never generates or approves a version; it only
    records and verifies the pins (see :meth:`Agent5Coordinator.pin_run_manifest`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    workflow_run_id: StableId
    project_id: StableId
    protocol_template_version: NonEmptyText
    protocol_template_sha256: Sha256
    graph_version: NonEmptyText
    graph_sha256: Sha256
    contract_schema_version: NonEmptyText
    skills: tuple[PinnedSkill, ...] = Field(min_length=1)
    # Mirrors the canonical WorkflowRun contract: a run pins at least one
    # source revision SHA-256, so an empty lineage cannot be represented.
    source_revision_hashes: tuple[Sha256, ...] = Field(min_length=1)
    study_definition_id: StableId
    study_definition_revision: PositiveRevision
    study_definition_sha256: Sha256
    created_at: AwareDateTime

    @field_validator("skills", "source_revision_hashes", mode="before")
    @classmethod
    def _collections_must_be_immutable_tuples(cls, value: Any) -> Any:
        _require_tuple(value, "manifest collection")
        return value

    @model_validator(mode="after")
    def _manifest_unique_identities(self) -> RunManifest:
        _unique(tuple(skill.skill_definition_id for skill in self.skills), "skill ids")
        _unique(self.source_revision_hashes, "source_revision_hashes")
        return self

    def content_sha256(self) -> str:
        """Deterministic content hash of the full pinned manifest."""
        return _deterministic_sha256(self.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Registered work package / dependency graph
# ---------------------------------------------------------------------------


class WorkPackageSpec(BaseModel):
    """A coordinator-proposed work package referencing a registered skill.

    ``depends_on`` names other package IDs; the dependency order is resolved
    deterministically by :class:`WorkPackageGraph`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    work_package_id: StableId
    skill_definition_id: StableId
    depends_on: tuple[StableId, ...] = ()
    exit_criteria_ref: Optional[StableId] = None

    @field_validator("depends_on", mode="before")
    @classmethod
    def _deps_must_be_immutable_tuple(cls, value: Any) -> Any:
        _require_tuple(value, "depends_on")
        return value

    @model_validator(mode="after")
    def _spec_unique_deps(self) -> WorkPackageSpec:
        _unique(self.depends_on, "depends_on")
        if self.work_package_id in self.depends_on:
            raise ValueError("a work package must not depend on itself")
        return self


class CoordinatorWorkPackage(BaseModel):
    """A resolved work package bound to a pinned registered skill."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    work_package_id: StableId
    skill_definition_id: StableId
    skill_sha256: Sha256
    input_schema_ref: NonEmptyText
    output_schema_ref: NonEmptyText
    depends_on: tuple[StableId, ...] = ()
    exit_criteria_ref: Optional[StableId] = None

    @field_validator("depends_on", mode="before")
    @classmethod
    def _deps_must_be_immutable_tuple(cls, value: Any) -> Any:
        _require_tuple(value, "depends_on")
        return value

    @model_validator(mode="after")
    def _package_unique_deps(self) -> CoordinatorWorkPackage:
        _unique(self.depends_on, "depends_on")
        if self.work_package_id in self.depends_on:
            raise ValueError("a work package must not depend on itself")
        return self


def _deterministic_topological_order(
    packages: tuple[CoordinatorWorkPackage, ...],
) -> tuple[str, ...]:
    """Kahn's algorithm over the package graph with deterministic tie-breaking.

    Ready nodes are consumed from a min-heap and dependency lists are sorted,
    so the returned order depends only on the package *set*, never on the
    input order.  A dependency cycle raises :class:`ValueError`.
    """
    ids = tuple(package.work_package_id for package in packages)
    dependents: dict[str, list[str]] = {package_id: [] for package_id in ids}
    in_degree: dict[str, int] = {package_id: 0 for package_id in ids}
    for package in packages:
        for dependency in package.depends_on:
            in_degree[package.work_package_id] += 1
            dependents[dependency].append(package.work_package_id)
    for children in dependents.values():
        children.sort()
    ready = [package_id for package_id in ids if in_degree[package_id] == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        package_id = heapq.heappop(ready)
        ordered.append(package_id)
        for child in dependents[package_id]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                heapq.heappush(ready, child)
    if len(ordered) != len(ids):
        raise ValueError("work package dependency graph contains a cycle")
    return tuple(ordered)


class WorkPackageGraph(BaseModel):
    """A validated registered work-package graph with a deterministic order.

    Construction rejects duplicate package identities, dependencies on
    unknown packages, self-dependencies and cycles.  The deterministic
    dependency order is a pure function of the graph and never depends on the
    input order.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    packages: tuple[CoordinatorWorkPackage, ...] = Field(min_length=1)

    @field_validator("packages", mode="before")
    @classmethod
    def _packages_must_be_immutable_tuple(cls, value: Any) -> Any:
        _require_tuple(value, "packages")
        return value

    @model_validator(mode="after")
    def _graph_closed_and_acyclic(self) -> WorkPackageGraph:
        ids = tuple(package.work_package_id for package in self.packages)
        _unique(ids, "work_package_ids")
        known = set(ids)
        for package in self.packages:
            unknown = [dep for dep in package.depends_on if dep not in known]
            if unknown:
                raise ValueError(
                    f"work package {package.work_package_id!r} depends on unknown "
                    f"packages: {sorted(unknown)}"
                )
        _deterministic_topological_order(self.packages)
        return self

    def ordered_package_ids(self) -> tuple[str, ...]:
        return _deterministic_topological_order(self.packages)

    def ordered_packages(self) -> tuple[CoordinatorWorkPackage, ...]:
        by_id = {package.work_package_id: package for package in self.packages}
        return tuple(by_id[package_id] for package_id in self.ordered_package_ids())


# ---------------------------------------------------------------------------
# Gate observation / summary
# ---------------------------------------------------------------------------


class GateResult(str, Enum):
    """Closed Gate outcome vocabulary.

    Deliberately has no ``skipped`` member: Agent⑤ must never be able to
    represent a skipped or overridden Gate.
    """

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    PENDING = "pending"


class GateObservation(BaseModel):
    """An immutable observation of one Gate result.

    Observations are externally produced (deterministic verifiers, Agent④
    findings); Agent⑤ aggregates them and must not change them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    gate_id: StableId
    gate_phase: NonEmptyText
    result: GateResult
    observed_at: AwareDateTime
    observed_by: StableId

    @field_validator("gate_phase")
    @classmethod
    def _phase_is_registered(cls, value: str) -> str:
        if value not in GATE_PHASE:
            raise ValueError(
                f"unknown gate phase {value!r}; allowed: {sorted(GATE_PHASE)}"
            )
        return value


class GateSummary(BaseModel):
    """A deterministic, read-only aggregation of Gate observations.

    Observations are sorted by ``gate_id`` at construction and must be unique
    per gate.  There is intentionally no submission-ready field: the
    four-layer ``可提交定稿`` verdict (design section 19) is deterministic and
    external; no verified verdict contract exists in the current baseline, so
    the capability is omitted entirely.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    project_id: StableId
    workflow_run_id: StableId
    observations: tuple[GateObservation, ...] = ()

    @field_validator("observations", mode="before")
    @classmethod
    def _observations_deterministic(cls, value: Any) -> Any:
        _require_tuple(value, "observations")
        return tuple(sorted(value, key=lambda observation: observation.gate_id))

    @model_validator(mode="after")
    def _unique_gates(self) -> GateSummary:
        _unique(tuple(observation.gate_id for observation in self.observations), "gate ids")
        return self

    def result_by_gate(self) -> dict[str, GateResult]:
        return {observation.gate_id: observation.result for observation in self.observations}


# ---------------------------------------------------------------------------
# Progress aggregation
# ---------------------------------------------------------------------------


class ProgressSummary(BaseModel):
    """A read-only progress/version aggregation.

    ``run_status`` is the workflow-run read-model status reflected verbatim;
    failed, interrupted and quarantined runs stay failed, interrupted and
    quarantined.  There is deliberately no ``completed``/``submission_ready``
    field: Agent⑤ must never relabel unfinished work as complete.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    project_id: StableId
    workflow_run_id: StableId
    run_status: Optional[WorkflowRunStatus] = None
    display_progress: UnitInterval = 0.0
    journey_counter: NonNegativeInt = 0
    study_definition_id: Optional[StableId] = None
    study_definition_revision: Optional[PositiveRevision] = None
    study_definition_sha256: Optional[Sha256] = None


# ---------------------------------------------------------------------------
# Decision / request queue
# ---------------------------------------------------------------------------


class DecisionRequest(BaseModel):
    """One pending decision request derived from the decision-graph
    read-model.  Only unresolved (not yet decided) entries enter the queue."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    decision_key: StableId
    decision_record_id: Optional[StableId] = None
    state_revision: Optional[PositiveRevision] = None
    selected_option_id: Optional[StableId] = None
    canonical_state: Optional[CanonicalState] = None
    current_validity: Literal["unverified", "current", "stale"] = "unverified"


class DecisionRequestQueue(BaseModel):
    """A deterministic queue representation of decisions awaiting user
    confirmation, sorted by ``decision_key`` with unique keys."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    project_id: StableId
    study_definition_id: StableId
    requests: tuple[DecisionRequest, ...] = ()

    @field_validator("requests", mode="before")
    @classmethod
    def _requests_deterministic(cls, value: Any) -> Any:
        _require_tuple(value, "requests")
        return tuple(sorted(value, key=lambda request: request.decision_key))

    @model_validator(mode="after")
    def _unique_decision_keys(self) -> DecisionRequestQueue:
        _unique(tuple(request.decision_key for request in self.requests), "decision keys")
        return self
