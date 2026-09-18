"""Agent⑤ coordinator: the narrow orchestration/communication boundary.

Design authority: Protocol v3 multi-agent rearchitecture design sections 5.4
(Agent⑤ is the only user-side workflow coordination role), 18 (run isolation,
recovery and error handling) and the frozen plan Task 1.9.

Boundary rules
--------------
* :class:`Agent5Coordinator` receives ONLY a narrow read-only query snapshot
  adapter (:class:`Agent5QueryFacade`), an approved
  :class:`RegistrySelection` and explicitly typed callbacks.  The facade is
  built by the composition root from the :class:`ApplicationService`: it
  executes the four typed queries exactly once for the run's identity triple
  and retains ONLY the frozen result values — never the service, its injected
  ``UnitOfWorkFactory``, repositories, reducers, storage adapters, raw
  StudyDefinition fact mutators or any way to construct an unowned
  ``DecisionRecord``.  No bound method, closure cell, ``functools.partial``
  or container member of the coordinator's retained graph can reach back to
  an application authority handle; the boundary is enforced by API shape,
  runtime type checks in :meth:`Agent5Coordinator.__init__` and a recursive
  retained-object-graph scan in the authority tests.
* Allowed capabilities: pin a run manifest from already approved inputs;
  decompose only registered coordinator work into a deterministic dependency
  order; aggregate progress/versions/Gate observations without changing them;
  build a decision/request queue representation; convert a
  :class:`ProtocolWorkflowError` into a split public/audit exception card.
* Forbidden capabilities (absent from the API surface and tested): directly
  changing StudyDefinition facts, changing finding severity, lowering /
  overriding / skipping a Gate, replacing the Agent④ clean verdict, redefining
  a stable denominator, relabeling failed/unknown/interrupted work as complete
  and independently asserting ``可提交定稿``.  The four-layer submission
  verdict (design section 19) is deterministic and external; no verified
  verdict contract exists in the current baseline, so the capability is
  omitted entirely — there is no submission-ready method or field.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

from packages.contracts.workbench_contracts.protocol_v3 import CanonicalState

from app.protocol_workflow.application import (
    ApplicationService,
    GetDecisionGraphQuery,
    GetStudyDefinitionEventSummaryQuery,
    GetStudyDefinitionQuery,
    GetWorkflowRunStatusQuery,
    DecisionGraphQueryResult,
    EventSummaryQueryResult,
    StudyDefinitionQueryResult,
    WorkflowRunStatusQueryResult,
)
from app.protocol_workflow.errors import ProtocolWorkflowError

from .exception_cards import (
    ExceptionCard,
    ExceptionCardAuditPayload,
    ExceptionCardPublicPayload,
)
from .run_manifest import (
    CoordinatorWorkPackage,
    DecisionRequest,
    DecisionRequestQueue,
    GateObservation,
    GateSummary,
    GraphPin,
    PinnedSkill,
    ProgressSummary,
    RegistrySelection,
    RunManifest,
    TemplatePin,
    WorkPackageGraph,
    WorkPackageSpec,
    require_non_empty,
    require_stable_id,
)

__all__ = [
    "Agent5Coordinator",
    "Agent5QueryFacade",
]

#: StudyDefinition states an Agent⑤ run may pin to (already approved).
_APPROVED_STUDY_STATES = frozenset({CanonicalState.CONFIRMED, CanonicalState.FROZEN})


def _default_utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Agent5QueryFacade:
    """Narrow read-only snapshot adapter — the ONLY application surface
    Agent⑤ is allowed to hold (design sections 5.4 / 17.2).

    The composition root constructs the facade from an
    :class:`ApplicationService`: the facade executes the four typed queries
    exactly once for the run's identity triple, retains ONLY the frozen query
    result values (:class:`StudyDefinitionQueryResult`,
    :class:`EventSummaryQueryResult`, :class:`DecisionGraphQueryResult`,
    :class:`WorkflowRunStatusQueryResult`) and discards the service.  The
    service is a local variable of ``__init__`` and is never stored, so no
    bound method ``__self__``, closure cell, ``functools.partial`` or
    container member of the facade — or of any object the coordinator retains
    — can reach back to the service, its injected ``UnitOfWorkFactory``,
    repositories, reducers or storage adapters.

    Read methods are fail-closed by identity: a query scoped to a different
    project / study definition / workflow run than the captured snapshot is
    rejected, so a facade captured for one run can never be re-pointed at
    another project's data.
    """

    __slots__ = (
        "_project_id",
        "_study_definition_id",
        "_workflow_run_id",
        "_study_definition",
        "_event_summary",
        "_decision_graph",
        "_workflow_run_status",
    )

    def __init__(
        self,
        *,
        service: ApplicationService,
        project_id: str,
        study_definition_id: str,
        workflow_run_id: str,
    ) -> None:
        require_stable_id(project_id, "project_id")
        require_stable_id(study_definition_id, "study_definition_id")
        require_stable_id(workflow_run_id, "workflow_run_id")
        self._project_id = project_id
        self._study_definition_id = study_definition_id
        self._workflow_run_id = workflow_run_id
        # One-shot capture: the service runs the four typed queries and is
        # then dropped (local variable only).  Only the frozen result values
        # are retained; the mutation surface never crosses this boundary.
        self._study_definition = service.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=project_id, study_definition_id=study_definition_id
            )
        )
        self._event_summary = service.get_study_definition_event_summary(
            GetStudyDefinitionEventSummaryQuery(
                project_id=project_id, study_definition_id=study_definition_id
            )
        )
        self._decision_graph = service.get_decision_graph(
            GetDecisionGraphQuery(
                project_id=project_id, study_definition_id=study_definition_id
            )
        )
        self._workflow_run_status = service.get_workflow_run_status(
            GetWorkflowRunStatusQuery(
                project_id=project_id, workflow_run_id=workflow_run_id
            )
        )

    def _require_snapshot_identity(
        self,
        *,
        project_id: str,
        study_definition_id: Optional[str] = None,
        workflow_run_id: Optional[str] = None,
    ) -> None:
        if project_id != self._project_id:
            raise ValueError(
                f"query project {project_id!r} does not match the captured "
                f"snapshot project {self._project_id!r}"
            )
        if (
            study_definition_id is not None
            and study_definition_id != self._study_definition_id
        ):
            raise ValueError(
                f"query study definition {study_definition_id!r} does not match "
                f"the captured snapshot {self._study_definition_id!r}"
            )
        if workflow_run_id is not None and workflow_run_id != self._workflow_run_id:
            raise ValueError(
                f"query workflow run {workflow_run_id!r} does not match the "
                f"captured snapshot {self._workflow_run_id!r}"
            )

    def get_study_definition(
        self, query: GetStudyDefinitionQuery
    ) -> StudyDefinitionQueryResult:
        self._require_snapshot_identity(
            project_id=query.project_id,
            study_definition_id=query.study_definition_id,
        )
        return self._study_definition

    def get_study_definition_event_summary(
        self, query: GetStudyDefinitionEventSummaryQuery
    ) -> EventSummaryQueryResult:
        self._require_snapshot_identity(
            project_id=query.project_id,
            study_definition_id=query.study_definition_id,
        )
        return self._event_summary

    def get_decision_graph(
        self, query: GetDecisionGraphQuery
    ) -> DecisionGraphQueryResult:
        self._require_snapshot_identity(
            project_id=query.project_id,
            study_definition_id=query.study_definition_id,
        )
        return self._decision_graph

    def get_workflow_run_status(
        self, query: GetWorkflowRunStatusQuery
    ) -> WorkflowRunStatusQueryResult:
        self._require_snapshot_identity(
            project_id=query.project_id,
            workflow_run_id=query.workflow_run_id,
        )
        return self._workflow_run_status


class Agent5Coordinator:
    """Agent⑤ orchestration control surface (design section 5.4)."""

    def __init__(
        self,
        *,
        application: Agent5QueryFacade,
        registry_selection: RegistrySelection,
        gate_observer: Optional[Callable[[], Tuple[GateObservation, ...]]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not isinstance(application, Agent5QueryFacade):
            raise TypeError(
                "application must be an Agent5QueryFacade (the narrow read-only "
                "query surface); repositories/UoW/fact mutators are not accepted"
            )
        if not isinstance(registry_selection, RegistrySelection):
            raise TypeError(
                "registry_selection must be an approved RegistrySelection, "
                "not a mutable or unpinned selection"
            )
        if gate_observer is not None and not callable(gate_observer):
            raise TypeError("gate_observer must be callable or None")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")
        self._application = application
        self._registry_selection = registry_selection
        self._gate_observer = gate_observer
        self._clock = clock if clock is not None else _default_utc_now

    @property
    def application(self) -> Agent5QueryFacade:
        """The narrow read-only query façade (never a UoW/factory/repository)."""
        return self._application

    @property
    def registry_selection(self) -> RegistrySelection:
        """The approved immutable registry selection."""
        return self._registry_selection

    # ------------------------------------------------------------------
    # Allowed capability 1 — pin a run manifest from approved inputs
    # ------------------------------------------------------------------

    def pin_run_manifest(
        self,
        *,
        project_id: str,
        workflow_run_id: str,
        protocol_template: TemplatePin,
        graph: GraphPin,
        contract_schema_version: str,
        source_revision_hashes: Tuple[str, ...],
        study_definition_id: str,
        skills: Optional[Tuple[PinnedSkill, ...]] = None,
    ) -> RunManifest:
        """Pin a run manifest from already approved inputs only.

        The template/graph pins are approved identities; the skill pins (or
        the approved selection when ``skills`` is ``None``) are verified
        against the approved :class:`RegistrySelection` — an unknown skill or
        a hash mismatch fails closed.  The StudyDefinition identity/version is
        read through the query façade and must be in an approved
        (confirmed/frozen) state; Agent⑤ never generates or approves a
        version.
        """
        require_stable_id(project_id, "project_id")
        require_stable_id(workflow_run_id, "workflow_run_id")
        require_stable_id(study_definition_id, "study_definition_id")
        require_non_empty(contract_schema_version, "contract_schema_version")
        if not isinstance(protocol_template, TemplatePin):
            raise TypeError("protocol_template must be an approved TemplatePin")
        if not isinstance(graph, GraphPin):
            raise TypeError("graph must be an approved GraphPin")
        if not isinstance(source_revision_hashes, tuple):
            raise TypeError("source_revision_hashes must be an immutable tuple")

        result = self._application.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=project_id, study_definition_id=study_definition_id
            )
        )
        definition = result.definition
        if definition is None:
            raise ValueError(
                f"study definition {study_definition_id!r} is not available "
                "for pinning"
            )
        if definition.study_definition_id != study_definition_id:
            raise ValueError("study definition identity mismatch while pinning")
        if definition.canonical_state not in _APPROVED_STUDY_STATES:
            raise ValueError(
                "study definition is not in an approved (confirmed/frozen) "
                "state and cannot be pinned"
            )
        if result.revision_sha256 is None:
            raise ValueError("study definition revision hash is unavailable")

        pinned_skills = self._resolve_skill_pins(skills)
        return RunManifest(
            workflow_run_id=workflow_run_id,
            project_id=project_id,
            protocol_template_version=protocol_template.template_version,
            protocol_template_sha256=protocol_template.template_sha256,
            graph_version=graph.graph_version,
            graph_sha256=graph.graph_sha256,
            contract_schema_version=contract_schema_version,
            skills=pinned_skills,
            source_revision_hashes=source_revision_hashes,
            study_definition_id=definition.study_definition_id,
            study_definition_revision=definition.revision,
            study_definition_sha256=result.revision_sha256,
            created_at=self._clock(),
        )

    def _resolve_skill_pins(
        self, skills: Optional[Tuple[PinnedSkill, ...]]
    ) -> Tuple[PinnedSkill, ...]:
        if skills is None:
            return self._registry_selection.pinned()
        if not isinstance(skills, tuple):
            raise TypeError("skills must be an immutable tuple of PinnedSkill")
        resolved: list[PinnedSkill] = []
        for pin in skills:
            if not isinstance(pin, PinnedSkill):
                raise TypeError("each skill pin must be a PinnedSkill")
            approved_hash = self._registry_selection.skill_hash(
                pin.skill_definition_id
            )
            if approved_hash is None:
                raise ValueError(
                    f"unknown skill in pin: {pin.skill_definition_id!r} "
                    "(not part of the approved registry selection)"
                )
            if pin.skill_sha256 != approved_hash:
                raise ValueError(
                    f"pinned skill hash mismatch for {pin.skill_definition_id!r}: "
                    f"pin={pin.skill_sha256} approved={approved_hash}"
                )
            resolved.append(pin)
        # Deterministic manifest ordering independent of caller order.
        return tuple(sorted(resolved, key=lambda pin: pin.skill_definition_id))

    # ------------------------------------------------------------------
    # Allowed capability 2 — decompose registered coordinator work
    # ------------------------------------------------------------------

    def decompose_coordinator_work(
        self, *, packages: Tuple[WorkPackageSpec, ...]
    ) -> WorkPackageGraph:
        """Decompose work packages into a deterministic dependency order.

        Every package must reference a skill registered in the approved
        selection; unknown skills, duplicate package identities, missing
        dependencies and cycles are rejected by :class:`WorkPackageGraph`.
        """
        if not isinstance(packages, tuple):
            raise TypeError("packages must be an immutable tuple of WorkPackageSpec")
        if not packages:
            raise ValueError("packages must not be empty")
        resolved: list[CoordinatorWorkPackage] = []
        for spec in packages:
            if not isinstance(spec, WorkPackageSpec):
                raise TypeError("each work package must be a WorkPackageSpec")
            skill = self._registry_selection.skill_by_id(spec.skill_definition_id)
            if skill is None:
                raise ValueError(
                    f"unknown or unregistered skill: {spec.skill_definition_id!r} "
                    "(not part of the approved registry selection)"
                )
            resolved.append(
                CoordinatorWorkPackage(
                    work_package_id=spec.work_package_id,
                    skill_definition_id=skill.skill_definition_id,
                    skill_sha256=skill.material_sha256(),
                    input_schema_ref=skill.input_schema_ref,
                    output_schema_ref=skill.output_schema_ref,
                    depends_on=spec.depends_on,
                    exit_criteria_ref=spec.exit_criteria_ref,
                )
            )
        return WorkPackageGraph(packages=tuple(resolved))

    # ------------------------------------------------------------------
    # Allowed capability 3 — read-only aggregation
    # ------------------------------------------------------------------

    def aggregate_progress(
        self, *, project_id: str, workflow_run_id: str, study_definition_id: str
    ) -> ProgressSummary:
        """Aggregate run status and StudyDefinition version without changing
        them.  The run status is reflected verbatim; failed/interrupted/
        quarantined work is never relabeled as complete."""
        require_stable_id(project_id, "project_id")
        require_stable_id(workflow_run_id, "workflow_run_id")
        require_stable_id(study_definition_id, "study_definition_id")

        run_result = self._application.get_workflow_run_status(
            GetWorkflowRunStatusQuery(
                project_id=project_id, workflow_run_id=workflow_run_id
            )
        )
        record = run_result.status
        definition_result = self._application.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=project_id, study_definition_id=study_definition_id
            )
        )
        definition = definition_result.definition
        return ProgressSummary(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            run_status=None if record is None else record.status,
            display_progress=0.0 if record is None else record.display_progress,
            journey_counter=0 if record is None else record.journey_counter,
            study_definition_id=None if definition is None else definition.study_definition_id,
            study_definition_revision=None if definition is None else definition.revision,
            study_definition_sha256=definition_result.revision_sha256,
        )

    def aggregate_gates(
        self, *, project_id: str, workflow_run_id: str
    ) -> GateSummary:
        """Aggregate Gate observations from the typed observer without changing
        them.  The summary is sorted deterministically and has no submission-
        ready capability."""
        require_stable_id(project_id, "project_id")
        require_stable_id(workflow_run_id, "workflow_run_id")
        observations: Tuple[GateObservation, ...] = (
            () if self._gate_observer is None else self._gate_observer()
        )
        if not isinstance(observations, tuple):
            raise TypeError(
                "gate_observer must return an immutable tuple of GateObservation"
            )
        for observation in observations:
            if not isinstance(observation, GateObservation):
                raise TypeError("gate_observer must return GateObservation values")
        return GateSummary(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            observations=observations,
        )

    # ------------------------------------------------------------------
    # Allowed capability 4 — decision/request queue representation
    # ------------------------------------------------------------------

    def build_decision_request_queue(
        self, *, project_id: str, study_definition_id: str
    ) -> DecisionRequestQueue:
        """Build a deterministic queue of decisions awaiting user confirmation
        from the decision-graph read-model.  Only unresolved entries enter the
        queue; resolved decisions are excluded."""
        require_stable_id(project_id, "project_id")
        require_stable_id(study_definition_id, "study_definition_id")
        result = self._application.get_decision_graph(
            GetDecisionGraphQuery(
                project_id=project_id, study_definition_id=study_definition_id
            )
        )
        requests = tuple(
            DecisionRequest(
                decision_key=record.decision_key,
                decision_record_id=record.decision_record_id,
                state_revision=record.state_revision,
                selected_option_id=record.selected_option_id,
                canonical_state=record.canonical_state,
            )
            for record in result.records
            if record.decision_record_id is None
            or record.canonical_state is CanonicalState.PROPOSED
        )
        return DecisionRequestQueue(
            project_id=project_id,
            study_definition_id=study_definition_id,
            requests=requests,
        )

    # ------------------------------------------------------------------
    # Allowed capability 5 — exception cards (strict public/audit split)
    # ------------------------------------------------------------------

    def to_exception_card(
        self,
        error: ProtocolWorkflowError,
        *,
        card_id: str,
        created_at: Optional[datetime] = None,
    ) -> ExceptionCard:
        """Convert a :class:`ProtocolWorkflowError` into an immutable exception
        card.  The public payload is exactly the catalog's Chinese-native
        public copy; machine/audit fields stay in the audit payload."""
        if not isinstance(error, ProtocolWorkflowError):
            raise TypeError("to_exception_card requires a ProtocolWorkflowError")
        require_stable_id(card_id, "card_id")
        public = ExceptionCardPublicPayload(**error.to_public_payload())
        audit = ExceptionCardAuditPayload(**error.to_audit_payload())
        return ExceptionCard(
            card_id=card_id,
            created_at=created_at if created_at is not None else self._clock(),
            public=public,
            audit=audit,
        )
