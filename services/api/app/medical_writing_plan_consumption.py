"""Shared fail-closed helper for ProtocolAssemblyPlan consumption.

Every downstream consumer (synopsis, sections, SoA, flowchart, evidence,
AI candidate, DOCX export) must call this helper to obtain a confirmed,
source-current plan projection.  If the plan is missing, stale, unconfirmed,
or has unresolved blocking drivers, the helper raises a domain conflict
error — it never returns a silent default or invented content.

This module is the single authorized entry point for plan consumption.
Workers 02 and 03 inject this helper into their respective services; they
must not call ``MedicalWritingProtocolAssemblyPlanService`` directly.
"""

from __future__ import annotations

from packages.contracts.workbench_contracts import (
    MedicalWritingProtocolAssemblyPlanCurrentState,
    MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS,
)

from .medical_writing_protocol_assembly_plan import (
    MedicalWritingProtocolAssemblyPlanConflictError,
    MedicalWritingProtocolAssemblyPlanService,
)
from .medical_writing_design_projection import normalize_study_design


class PlanConsumptionError(MedicalWritingProtocolAssemblyPlanConflictError):
    """Raised when a consumer cannot safely obtain a plan projection."""


class PlanUnconfirmedError(PlanConsumptionError):
    """Plan exists but has not been confirmed by an author."""


class PlanStaleError(PlanConsumptionError):
    """Plan is stale relative to the source StudyDefinition."""


class PlanUnresolvedDriverError(PlanConsumptionError):
    """Plan has unresolved blocking drivers for the requested projection."""


class PlanProjectionMissingError(PlanConsumptionError):
    """The requested projection kind is not present in the plan."""


_VALID_PROJECTIONS = frozenset(MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS)


class MedicalWritingPlanConsumptionHelper:
    """Fail-closed helper for downstream plan projection consumption.

    Usage::

        helper = MedicalWritingPlanConsumptionHelper(plan_service)
        state = helper.require_confirmed_projection(
            project_id=project_id,
            projection_kind="synopsis",
        )
        # state.plan contains the confirmed plan with modules, drivers,
        # and projection_manifests
    """

    def __init__(
        self,
        plan_service: MedicalWritingProtocolAssemblyPlanService,
    ) -> None:
        self._plan_service = plan_service

    def require_confirmed_projection(
        self,
        *,
        project_id: str,
        projection_kind: str,
    ) -> MedicalWritingProtocolAssemblyPlanCurrentState:
        """Return the confirmed, source-current plan state for *projection_kind*.

        Raises:
            PlanUnconfirmedError: plan missing or not confirmed.
            PlanStaleError: plan is stale (source_current=false).
            PlanUnresolvedDriverError: plan has blocking unresolved questions
                targeting the requested projection.
            PlanProjectionMissingError: projection kind not in plan manifests.
        """
        if projection_kind not in _VALID_PROJECTIONS:
            raise PlanProjectionMissingError(
                f"unknown projection kind: {projection_kind}"
            )

        try:
            state = self._plan_service.current_state(project_id)
        except KeyError as exc:
            raise PlanUnconfirmedError(
                f"no protocol assembly plan found for project {project_id}: {exc}"
            ) from exc
        except MedicalWritingProtocolAssemblyPlanConflictError as exc:
            raise PlanStaleError(
                f"plan conflict for project {project_id}: {exc}"
            ) from exc

        if not state.available or state.plan is None:
            raise PlanUnconfirmedError(
                f"no plan revision exists for project {project_id}"
            )

        plan = state.plan
        if plan.confirmation_status != "author_confirmed" or not plan.confirmed_by:
            raise PlanUnconfirmedError(
                f"plan revision {plan.revision} for project {project_id} "
                f"has not been confirmed by an author"
            )

        if not state.source_current:
            raise PlanStaleError(
                f"plan revision {plan.revision} for project {project_id} "
                f"is stale relative to the source StudyDefinition"
            )

        # Check for blocking unresolved questions in the requested projection.
        blocking_questions = [
            q
            for module in plan.modules
            if projection_kind in module.projection_targets
            for q in module.unresolved_questions
            if q.severity == "blocker"
        ]
        if blocking_questions:
            driver_ids = ", ".join(q.question_id for q in blocking_questions[:5])
            raise PlanUnresolvedDriverError(
                f"plan revision {plan.revision} for project {project_id} "
                f"has {len(blocking_questions)} blocking unresolved driver(s) "
                f"for projection '{projection_kind}': {driver_ids}"
            )

        # Verify the projection manifest exists and is not empty.
        projection_manifests = plan.projection_manifest or []
        manifest = next(
            (m for m in projection_manifests if m.projection == projection_kind),
            None,
        )
        if manifest is None:
            raise PlanProjectionMissingError(
                f"projection '{projection_kind}' not found in plan manifests "
                f"for project {project_id}"
            )

        return state

    def require_confirmed_projections(
        self,
        *,
        project_id: str,
        projection_kinds: list[str],
    ) -> MedicalWritingProtocolAssemblyPlanCurrentState:
        """Return confirmed plan state covering multiple projection kinds.

        Validates each kind via :meth:`require_confirmed_projection` but
        returns the single shared plan state (one revision for all kinds).
        """
        if not projection_kinds:
            raise PlanProjectionMissingError("no projection kinds requested")

        # Validate the first kind to get the state.
        state = self.require_confirmed_projection(
            project_id=project_id,
            projection_kind=projection_kinds[0],
        )

        # Validate remaining kinds against the same plan state.
        plan = state.plan
        assert plan is not None  # guaranteed by require_confirmed_projection

        for kind in projection_kinds[1:]:
            if kind not in _VALID_PROJECTIONS:
                raise PlanProjectionMissingError(
                    f"unknown projection kind: {kind}"
                )
            blocking_questions = [
                q
                for module in plan.modules
                if kind in module.projection_targets
                for q in module.unresolved_questions
                if q.severity == "blocker"
            ]
            if blocking_questions:
                driver_ids = ", ".join(q.question_id for q in blocking_questions[:5])
                raise PlanUnresolvedDriverError(
                    f"plan revision {plan.revision} for project {project_id} "
                    f"has {len(blocking_questions)} blocking unresolved driver(s) "
                    f"for projection '{kind}': {driver_ids}"
                )

        return state

    def require_confirmed_design_projection(
        self,
        *,
        project_id: str,
        projection_kind: str,
    ):
        """Return one source-current plan, StudyDefinition and design projection.

        This is the authoritative Slice C consumer boundary. It prevents a
        downstream output surface from validating a plan and then independently
        re-reading legacy design prose or compatibility booleans.
        """

        state = self.require_confirmed_projection(
            project_id=project_id,
            projection_kind=projection_kind,
        )
        definition = self._plan_service.definition_provider(project_id)
        plan = state.plan
        assert plan is not None
        source_identity = (
            definition.definition_id,
            definition.revision,
            definition.state_sha256,
        )
        if source_identity != (
            plan.source_definition_id,
            plan.source_definition_revision,
            plan.source_definition_sha256,
        ):
            raise PlanStaleError(
                f"confirmed plan revision {plan.revision} is not bound to the "
                "current StudyDefinition"
            )
        projection = normalize_study_design(definition, include_sources=True)
        if source_identity != (
            projection.source_definition_id,
            projection.source_definition_revision,
            projection.source_definition_sha256,
        ):
            raise PlanStaleError(
                "NormalizedDesignProjection identity does not match the current "
                "StudyDefinition"
            )
        blocking = [
            question
            for question in projection.blockers
            if question.severity == "blocker"
            and projection_kind in projection.affected_projections
        ]
        if blocking:
            raise PlanUnresolvedDriverError(
                f"NormalizedDesignProjection has {len(blocking)} blocking "
                f"driver(s) for projection '{projection_kind}': "
                + ", ".join(item.question_id for item in blocking[:5])
            )
        return state, definition, projection
