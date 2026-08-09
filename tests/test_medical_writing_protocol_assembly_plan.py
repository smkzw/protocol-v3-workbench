from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    InterventionRulesAuthority,
    InterventionRulesIpAdjustmentPolicy,
    InterventionRulesNonIpRuleClass,
    InterventionRulesProductRole,
    MedicalWritingInterventionIpRegimen,
    MedicalWritingInterventionNonIpTreatmentRule,
    MedicalWritingInterventionRules,
    MedicalWritingInterimAnalysisDesign,
    MedicalWritingPhase1Part,
    MedicalWritingPicosDefinition,
    MedicalWritingProtocolAssemblyPlan,
    MedicalWritingProtocolAssemblyPlanConfirmRequest,
    MedicalWritingProtocolAssemblyPlanRefreshRequest,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingStructuredStudyDesign,
)
from packages.contracts.workbench_contracts.models import (
    EvidencePicosWorkflowResult,
    MedicalWritingProtocolAssemblyPlanPreviewRequest,
    WritingSectionSummary,
    WritingSourcePackageSummary,
)
from services.api.app.medical_writing_protocol_assembly_plan import (
    MedicalWritingProtocolAssemblyPlanBlockedError,
    MedicalWritingProtocolAssemblyPlanConflictError,
    MedicalWritingProtocolAssemblyPlanService,
    MedicalWritingProtocolAssemblyPlanStaleError,
    build_protocol_assembly_plan,
)
from services.api.app.sqlite_runtime_store import RuntimeStoreIntegrityError


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)


def _definition(
    project_id: str = "proj_assembly",
    *,
    revision: int = 1,
    definition_hash: str = "a" * 64,
    study_phase: str = "I期",
    phase1_parts: list[object] | None = None,
    interim_planned: bool | None = False,
    src_planned: bool | None = False,
    dmc_planned: bool | None = False,
    comparator_type: str = "active",
    include_active_comparator: bool = True,
    routes: list[str] | None = None,
    dosage_forms: list[str] | None = None,
    exposure_scope: str = "systemic",
    background_mtx: bool = False,
    pk_pd_considerations: list[str] | None = None,
    aesi_definitions: list[str] | None = None,
    statistical_strategy: str = "",
    visit_strategy: str = "",
) -> MedicalWritingStudyDefinition:
    regimens = [
        MedicalWritingInterventionIpRegimen(
            regimen_id="ip-main",
            product_name="IP-001",
            product_role=InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT,
            dose_and_frequency="authoritative dose",
            route="authoritative route",
            treatment_period="authoritative period",
        )
    ]
    if include_active_comparator:
        regimens.append(
            MedicalWritingInterventionIpRegimen(
                regimen_id="active-main",
                product_name="AC-001",
                product_role=InterventionRulesProductRole.ACTIVE_COMPARATOR,
                dose_and_frequency="authoritative comparator dose",
                route="authoritative comparator route",
                treatment_period="authoritative comparator period",
            )
        )
    non_ip_rules = []
    if background_mtx:
        non_ip_rules.append(
            MedicalWritingInterventionNonIpTreatmentRule(
                rule_id="background-mtx",
                rule_class=InterventionRulesNonIpRuleClass.BACKGROUND,
                agent_or_category="MTX",
                cm_dose_rule="stable background dose",
            )
        )
    intervention_rules = MedicalWritingInterventionRules(
        authority=InterventionRulesAuthority.STRUCTURED,
        ip_regimens=regimens,
        ip_adjustment_policy=(
            InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
        ),
        no_planned_adjustment_statement="No planned IP dose adjustment.",
        non_ip_treatment_rules=non_ip_rules,
    )
    design = MedicalWritingStructuredStudyDesign(
        randomization_mode="randomized",
        blinding_mode="double_blind",
        comparator_type=comparator_type,
        assignment_model="parallel_group",
        adaptive_design_enabled=False,
        sample_size_reestimation_planned=False,
        treatment_switch_planned=False,
        crossover_planned=False,
        open_label_extension_planned=False,
        src_planned=src_planned,
        dmc_planned=dmc_planned,
        interim_analysis=MedicalWritingInterimAnalysisDesign(planned=interim_planned),
        phase1_parts=list(
            phase1_parts
            if phase1_parts is not None
            else [
                MedicalWritingPhase1Part(
                    part_code="SAD",
                    population="健康受试者",
                    cohort_dose="SAD剂量递增队列",
                ),
                MedicalWritingPhase1Part(
                    part_code="MAD",
                    population="健康受试者",
                    cohort_dose="MAD剂量递增队列",
                ),
                MedicalWritingPhase1Part(
                    part_code="first-in-patient",
                    population="目标适应症患者",
                    cohort_dose="患者队列及剂量方案",
                ),
            ]
        ),
    )
    framing = MedicalWritingStudyFraming(
        protocol_id="PROTO-001",
        document_title="Protocol title",
        indication="Authoritative indication",
        clinicaltrials_condition_term="Authoritative condition",
        study_phase=study_phase,
        investigational_product="IP-001",
        structured_design=design,
        product_profile={
            "technology_type": "small_molecule",
            "administration_routes": list(routes or ["口服"]),
            "dosage_forms": list(dosage_forms or ["片剂"]),
            "exposure_scope": exposure_scope,
            "pk_pd_considerations": list(pk_pd_considerations or []),
        },
    )
    picos = MedicalWritingPicosDefinition(
        population_summary="Authoritative population",
        primary_endpoint="Authoritative primary endpoint",
        intervention_rules=intervention_rules,
        aesi_definitions=list(aesi_definitions or []),
        statistical_strategy=statistical_strategy,
        visit_strategy=visit_strategy,
    )
    return MedicalWritingStudyDefinition(
        definition_id=f"definition-{project_id}",
        project_id=project_id,
        revision=revision,
        origin="guided_greenfield",
        framing=framing,
        picos=picos,
        state_sha256=definition_hash,
        created_at=NOW,
        updated_at=NOW,
        updated_by="fixture_author",
    )


def _module(plan: MedicalWritingProtocolAssemblyPlan, module_id: str):
    return next(item for item in plan.modules if item.module_id == module_id)


def _manifest(plan: MedicalWritingProtocolAssemblyPlan, projection: str):
    return next(
        item for item in plan.projection_manifest if item.projection == projection
    )


def _driver(plan: MedicalWritingProtocolAssemblyPlan, driver_id: str):
    return next(item for item in plan.design_drivers if item.driver_id == driver_id)


def _build(definition: MedicalWritingStudyDefinition):
    return build_protocol_assembly_plan(
        definition,
        plan_id="assembly-plan-test",
        revision=1,
        actor="medical_author",
        now=NOW,
    )


def _refresh_request(
    definition: MedicalWritingStudyDefinition,
    *,
    expected_plan_revision: int,
    key: str,
):
    return MedicalWritingProtocolAssemblyPlanRefreshRequest(
        expected_plan_revision=expected_plan_revision,
        expected_source_definition_id=definition.definition_id,
        expected_source_definition_revision=definition.revision,
        expected_source_definition_sha256=definition.state_sha256,
        actor="medical_author",
        idempotency_key=key,
    )


def _preview_request(
    definition: MedicalWritingStudyDefinition,
    *,
    expected_plan_revision: int,
):
    return MedicalWritingProtocolAssemblyPlanPreviewRequest(
        expected_plan_revision=expected_plan_revision,
        expected_source_definition_id=definition.definition_id,
        expected_source_definition_revision=definition.revision,
        expected_source_definition_sha256=definition.state_sha256,
        actor="medical_author",
    )


def test_phase1_parts_are_present_in_every_relevant_projection_and_omission_fails():
    plan = _build(_definition())
    phase1_modules = {
        "design.phase1.sad",
        "design.phase1.mad",
        "design.phase1.first_in_patient",
    }
    for module_id in phase1_modules:
        resolution = _module(plan, module_id)
        assert resolution.applicability == "conditional_applicable"
        assert resolution.deterministic_projection_allowed is True
        for projection in resolution.projection_targets:
            assert module_id in _manifest(plan, projection).applicable_module_ids

    corrupted = plan.model_dump(mode="json")
    synopsis = next(
        item
        for item in corrupted["projection_manifest"]
        if item["projection"] == "synopsis"
    )
    synopsis["applicable_module_ids"].remove("design.phase1.sad")
    with pytest.raises(ValidationError, match="manifest is incomplete"):
        MedicalWritingProtocolAssemblyPlan.model_validate(corrupted)


def test_only_selected_unresolved_phase1_part_blocks_its_own_module():
    plan = _build(
        _definition(
            phase1_parts=[
                MedicalWritingPhase1Part(part_code="SAD"),
            ]
        )
    )
    sad = _module(plan, "design.phase1.sad")
    mad = _module(plan, "design.phase1.mad")

    assert sad.applicability == "conditional_applicable"
    assert sad.deterministic_projection_allowed is False
    assert sad.blocking_severity == "blocker"
    assert len(sad.unresolved_questions) == 1
    assert sad.unresolved_questions[0].fact_path.endswith("phase1_parts[0]")
    assert "population" in sad.unresolved_questions[0].prompt
    assert "cohort_dose" in sad.unresolved_questions[0].prompt
    assert "pk_pd" not in sad.unresolved_questions[0].prompt

    assert mad.applicability == "not_applicable"
    assert mad.deterministic_projection_allowed is True
    assert mad.unresolved_questions == []


def test_interim_false_true_and_unknown_have_fail_closed_cross_projection_semantics(
    tmp_path: Path,
):
    false_plan = _build(_definition(interim_planned=False))
    false_resolution = _module(false_plan, "design.interim_analysis")
    assert false_resolution.applicability == "not_applicable"
    assert all(
        "design.interim_analysis" not in manifest.applicable_module_ids
        for manifest in false_plan.projection_manifest
    )

    true_plan = _build(
        _definition(interim_planned=True, src_planned=True, dmc_planned=False)
    )
    assert _module(true_plan, "design.interim_analysis").applicability == (
        "conditional_applicable"
    )
    assert (
        "design.interim_analysis"
        in _manifest(true_plan, "synopsis").applicable_module_ids
    )
    assert (
        "design.interim_analysis"
        in _manifest(true_plan, "sections_toc").applicable_module_ids
    )
    assert _module(true_plan, "governance.src").applicability == (
        "conditional_applicable"
    )
    assert _module(true_plan, "governance.dmc").applicability == "not_applicable"

    unknown_definition = _definition(interim_planned=None)
    unknown_plan = _build(unknown_definition)
    unknown_resolution = _module(unknown_plan, "design.interim_analysis")
    assert unknown_resolution.applicability == "conditional_applicable"
    assert unknown_resolution.deterministic_projection_allowed is False
    assert unknown_resolution.blocking_severity == "blocker"
    assert (
        "design.interim_analysis"
        in _manifest(unknown_plan, "synopsis").unresolved_module_ids
    )
    assert (
        "design.interim_analysis"
        not in _manifest(unknown_plan, "synopsis").applicable_module_ids
    )

    definitions = {unknown_definition.project_id: unknown_definition}
    service = MedicalWritingProtocolAssemblyPlanService(
        tmp_path / "assembly.sqlite3", definitions.__getitem__
    )
    refreshed = service.refresh(
        unknown_definition.project_id,
        _refresh_request(
            unknown_definition, expected_plan_revision=0, key="refresh-unknown"
        ),
    )
    with pytest.raises(
        MedicalWritingProtocolAssemblyPlanBlockedError,
        match="design.interim_analysis",
    ):
        service.confirm(
            unknown_definition.project_id,
            MedicalWritingProtocolAssemblyPlanConfirmRequest(
                expected_plan_revision=refreshed.plan.revision,
                expected_plan_sha256=refreshed.plan.state_sha256,
                actor="medical_author",
                idempotency_key="confirm-unknown",
            ),
        )


def test_active_comparator_without_one_authoritative_regimen_blocks_confirmation(
    tmp_path: Path,
):
    definition = _definition(include_active_comparator=False)
    plan = _build(definition)
    resolution = _module(plan, "intervention.active_comparator_regimen")
    assert resolution.deterministic_projection_allowed is False
    assert {item.code for item in resolution.unresolved_questions} == {
        "unique_active_comparator_regimen_required"
    }

    service = MedicalWritingProtocolAssemblyPlanService(
        tmp_path / "assembly.sqlite3", {definition.project_id: definition}.__getitem__
    )
    refreshed = service.refresh(
        definition.project_id,
        _refresh_request(definition, expected_plan_revision=0, key="refresh-active"),
    )
    with pytest.raises(MedicalWritingProtocolAssemblyPlanBlockedError):
        service.confirm(
            definition.project_id,
            MedicalWritingProtocolAssemblyPlanConfirmRequest(
                expected_plan_revision=refreshed.plan.revision,
                expected_plan_sha256=refreshed.plan.state_sha256,
                actor="medical_author",
                idempotency_key="confirm-active",
            ),
        )


def test_background_mtx_stays_non_ip_background_and_is_not_copied_into_plan():
    plan = _build(_definition(background_mtx=True))
    background = _module(plan, "intervention.background_treatment")
    ip_actions = _module(plan, "intervention.investigational_product_dose_actions")
    permitted = _module(plan, "intervention.permitted_concomitant_treatment")

    assert background.applicability == "conditional_applicable"
    assert permitted.applicability == "not_applicable"
    assert ip_actions.applicability == "not_applicable"
    assert {item.fact_path for item in background.fact_references} == {
        "picos.intervention_rules.non_ip_treatment_rules"
    }
    assert all(
        item.fact_path != "picos.intervention_rules.non_ip_treatment_rules"
        for item in ip_actions.fact_references
    )
    assert "intervention.concomitant_medication" not in {
        item.module_id for item in plan.modules
    }
    assert "MTX" not in json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)


@pytest.mark.parametrize(
    ("route", "dosage_form"),
    [
        ("topical", "cream"),
        ("inhaled", "inhalation powder"),
        ("intranasal", "nasal spray"),
    ],
)
def test_local_routes_never_inherit_systemic_oral_defaults(
    route: str,
    dosage_form: str,
):
    plan = _build(
        _definition(
            routes=[route],
            dosage_forms=[dosage_form],
            exposure_scope="local",
        )
    )
    route_module = _module(plan, "product.route")
    defaults = _module(plan, "evidence.systemic_oral_defaults")
    assert route_module.applicability == "conditional_applicable"
    assert defaults.applicability == "not_applicable"
    for projection in defaults.projection_targets:
        manifest = _manifest(plan, projection)
        assert defaults.module_id in manifest.not_applicable_module_ids
        assert defaults.module_id not in manifest.applicable_module_ids


def test_definition_change_invalidates_current_confirmation_and_stale_updates(
    tmp_path: Path,
):
    first = _definition()
    definitions = {first.project_id: first}
    service = MedicalWritingProtocolAssemblyPlanService(
        tmp_path / "assembly.sqlite3", definitions.__getitem__
    )
    initial_request = _refresh_request(
        first, expected_plan_revision=0, key="refresh-r1"
    )
    initial = service.refresh(
        first.project_id,
        initial_request,
    )
    confirmation_request = MedicalWritingProtocolAssemblyPlanConfirmRequest(
        expected_plan_revision=initial.plan.revision,
        expected_plan_sha256=initial.plan.state_sha256,
        actor="medical_author",
        idempotency_key="confirm-r1",
    )
    confirmed = service.confirm(
        first.project_id,
        confirmation_request,
    )
    assert confirmed.plan.confirmation_status == "author_confirmed"
    assert confirmed.plan.confirmation_kind == "author_plan_confirmation"
    assert service.current_state(first.project_id).confirmation_current is True

    second = _definition(
        revision=2,
        definition_hash="b" * 64,
        interim_planned=True,
    )
    definitions[first.project_id] = second
    refresh_replay = service.refresh(first.project_id, initial_request)
    confirmation_replay = service.confirm(first.project_id, confirmation_request)
    assert refresh_replay.replayed is True
    assert confirmation_replay.replayed is True
    assert confirmation_replay.plan.state_sha256 == confirmed.plan.state_sha256
    stale_state = service.current_state(first.project_id)
    assert stale_state.source_current is False
    assert stale_state.confirmation_current is False
    refreshed = service.refresh(
        first.project_id,
        _refresh_request(
            second,
            expected_plan_revision=confirmed.plan.revision,
            key="refresh-r2",
        ),
    )
    assert refreshed.plan.confirmation_status == "draft"
    assert "design.interim_analysis" in refreshed.affected_module_ids
    assert (
        _module(refreshed.plan, "core.protocol_identity").resolution_sha256
        == _module(confirmed.plan, "core.protocol_identity").resolution_sha256
    )
    old_history = service.history(first.project_id)[1]
    assert old_history.state_sha256 == confirmed.plan.state_sha256
    assert old_history.confirmation_status == "author_confirmed"

    with pytest.raises(MedicalWritingProtocolAssemblyPlanStaleError):
        service.refresh(
            first.project_id,
            _refresh_request(
                second,
                expected_plan_revision=confirmed.plan.revision,
                key="stale-refresh",
            ),
        )


def test_definition_revision_only_invalidates_confirmation_but_keeps_projections_stable(
    tmp_path: Path,
):
    first = _definition()
    definitions = {first.project_id: first}
    service = MedicalWritingProtocolAssemblyPlanService(
        tmp_path / "assembly.sqlite3", definitions.__getitem__
    )
    initial = service.refresh(
        first.project_id,
        _refresh_request(first, expected_plan_revision=0, key="refresh-r1"),
    )
    confirmed = service.confirm(
        first.project_id,
        MedicalWritingProtocolAssemblyPlanConfirmRequest(
            expected_plan_revision=initial.plan.revision,
            expected_plan_sha256=initial.plan.state_sha256,
            actor="medical_author",
            idempotency_key="confirm-r1",
        ),
    )
    second = _definition(revision=2, definition_hash="c" * 64)
    definitions[first.project_id] = second
    refreshed = service.refresh(
        first.project_id,
        _refresh_request(
            second,
            expected_plan_revision=confirmed.plan.revision,
            key="refresh-r2",
        ),
    )
    assert refreshed.affected_module_ids == []
    assert refreshed.affected_projections == []
    assert refreshed.plan.confirmation_status == "draft"
    assert [item.content_sha256 for item in refreshed.plan.projection_manifest] == [
        item.content_sha256 for item in confirmed.plan.projection_manifest
    ]


def test_project_isolation_idempotency_and_transaction_rollback(tmp_path: Path):
    first = _definition("project-one")
    second = _definition("project-two", definition_hash="d" * 64)
    failing = _definition("project-failing", definition_hash="e" * 64)
    definitions = {
        first.project_id: first,
        second.project_id: second,
        failing.project_id: failing,
    }
    db_path = tmp_path / "assembly.sqlite3"
    service = MedicalWritingProtocolAssemblyPlanService(
        db_path, definitions.__getitem__
    )
    first_request = _refresh_request(
        first, expected_plan_revision=0, key="same-project-scoped-key"
    )
    first_result = service.refresh(first.project_id, first_request)
    replay = service.refresh(first.project_id, first_request)
    assert replay.replayed is True
    assert replay.plan.state_sha256 == first_result.plan.state_sha256
    assert len(service.history(first.project_id)) == 1

    second_result = service.refresh(
        second.project_id,
        _refresh_request(
            second, expected_plan_revision=0, key="same-project-scoped-key"
        ),
    )
    assert second_result.plan.project_id == second.project_id
    assert service.current_state(first.project_id).plan.project_id == first.project_id
    assert service.current_state(second.project_id).plan.project_id == second.project_id

    def fail_after_history(checkpoint: str) -> None:
        if checkpoint == "after_history_insert":
            raise RuntimeError("injected rollback")

    failing_service = MedicalWritingProtocolAssemblyPlanService(
        db_path,
        definitions.__getitem__,
        fault_injector=fail_after_history,
    )
    with pytest.raises(RuntimeError, match="injected rollback"):
        failing_service.refresh(
            failing.project_id,
            _refresh_request(failing, expected_plan_revision=0, key="rollback-refresh"),
        )
    assert failing_service.history(failing.project_id) == []
    assert failing_service.current_state(failing.project_id).available is False


def test_plan_history_is_immutable_at_the_database_boundary(tmp_path: Path):
    definition = _definition()
    db_path = tmp_path / "assembly.sqlite3"
    service = MedicalWritingProtocolAssemblyPlanService(
        db_path, {definition.project_id: definition}.__getitem__
    )
    service.refresh(
        definition.project_id,
        _refresh_request(definition, expected_plan_revision=0, key="refresh"),
    )
    with sqlite3.connect(db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="history is immutable"):
            connection.execute(
                """
                UPDATE medical_writing_protocol_assembly_plan_history
                SET state_sha256 = ?
                WHERE project_id = ?
                """,
                ("f" * 64, definition.project_id),
            )


def test_design_drivers_explicitly_model_protocol_facts_and_consumer_impact():
    plan = _build(
        _definition(
            background_mtx=True,
            routes=["intranasal"],
            dosage_forms=["nasal spray"],
            exposure_scope="local",
            pk_pd_considerations=["local exposure PK bridge"],
            aesi_definitions=["AESI category"],
            statistical_strategy="FAS, PPS, and safety set",
            visit_strategy="Screening through follow-up visits",
        )
    )

    assert _driver(plan, "core.phase").decision_state == "required"
    assert _driver(plan, "core.indication").decision_state == "required"
    assert _driver(plan, "product.modality").decision_state == "design_driven"
    assert _driver(plan, "product.route").decision_state == "design_driven"
    assert _driver(plan, "design.randomization").decision_state == "design_driven"
    assert _driver(plan, "design.blinding").decision_state == "design_driven"
    assert _driver(plan, "design.control").decision_state == "design_driven"
    assert _driver(plan, "design.phase1_part.sad").decision_state == "design_driven"
    assert _driver(plan, "design.phase1_part.food_effect").decision_state == (
        "not_applicable"
    )
    assert _driver(plan, "design.interim_analysis").decision_state == (
        "not_applicable"
    )
    assert _driver(plan, "governance.src").decision_state == "not_applicable"
    assert _driver(plan, "governance.dmc").decision_state == "not_applicable"
    assert _driver(plan, "intervention.background_treatment").decision_state == (
        "design_driven"
    )
    assert _driver(plan, "science.pk_pd").decision_state == "design_driven"
    assert _driver(plan, "safety.aesi").decision_state == "design_driven"
    assert _driver(plan, "statistics.analysis_set").decision_state == (
        "design_driven"
    )
    assert _driver(plan, "operations.soa").decision_state == "design_driven"
    assert _driver(plan, "operations.study_schema_flowchart").decision_state == (
        "unknown"
    )
    for driver in plan.design_drivers:
        assert driver.source_references
        assert driver.projection_targets
        assert driver.fact_path
        assert driver.rationale
    assert "MTX" not in json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)


def test_preview_is_non_persistent_and_all_consumers_share_one_plan(tmp_path: Path):
    first = _definition()
    definitions = {first.project_id: first}
    service = MedicalWritingProtocolAssemblyPlanService(
        tmp_path / "assembly.sqlite3", definitions.__getitem__
    )
    initial = service.refresh(
        first.project_id,
        _refresh_request(first, expected_plan_revision=0, key="refresh-r1"),
    )
    second = _definition(
        revision=2,
        definition_hash="b" * 64,
        interim_planned=True,
        pk_pd_considerations=["PK sampling"],
        aesi_definitions=["AESI definition"],
        statistical_strategy="FAS and safety set",
        visit_strategy="Protocol SoA visit schedule",
    )
    definitions[first.project_id] = second

    preview = service.preview(
        first.project_id,
        _preview_request(second, expected_plan_revision=initial.plan.revision),
    )
    assert preview.plan.revision == initial.plan.revision + 1
    assert "design.interim_analysis" in preview.affected_module_ids
    assert service.current_state(first.project_id).plan.revision == initial.plan.revision
    assert len(service.history(first.project_id)) == 1

    refreshed = service.refresh(
        first.project_id,
        _refresh_request(
            second,
            expected_plan_revision=initial.plan.revision,
            key="refresh-r2",
        ),
    )
    projections = [
        service.consumer_projection(first.project_id, projection)
        for projection in (
            "synopsis",
            "sections_toc",
            "soa",
            "study_schema_flowchart",
            "evidence_intent",
            "ai_candidate_intent",
            "docx_toc",
        )
    ]
    assert {item.plan_id for item in projections} == {refreshed.plan.plan_id}
    assert {item.plan_revision for item in projections} == {refreshed.plan.revision}
    assert {item.plan_sha256 for item in projections} == {
        refreshed.plan.state_sha256
    }
    assert {item.source_definition_sha256 for item in projections} == {
        second.state_sha256
    }
    assert "design.interim_analysis" in projections[0].design_driven_module_ids
    assert any(
        driver.driver_id == "operations.soa"
        for driver in service.consumer_projection(first.project_id, "soa").design_drivers
    )
    flow_projection = service.consumer_projection(
        first.project_id, "study_schema_flowchart"
    )
    assert "operations.study_schema_flowchart" in (
        flow_projection.unresolved_driver_ids
    )
    assert flow_projection.deterministic_projection_allowed is False
    with pytest.raises(MedicalWritingProtocolAssemblyPlanConflictError):
        service.consumer_projection(first.project_id, "invented_projection")


def test_audit_dump_load_and_restart_recovery_are_project_scoped(tmp_path: Path):
    first = _definition("project-one")
    second = _definition("project-two", definition_hash="d" * 64)
    definitions = {first.project_id: first, second.project_id: second}
    db_path = tmp_path / "assembly.sqlite3"
    service = MedicalWritingProtocolAssemblyPlanService(
        db_path, definitions.__getitem__
    )
    initial = service.refresh(
        first.project_id,
        _refresh_request(first, expected_plan_revision=0, key="refresh-one"),
    )
    confirmed = service.confirm(
        first.project_id,
        MedicalWritingProtocolAssemblyPlanConfirmRequest(
            expected_plan_revision=initial.plan.revision,
            expected_plan_sha256=initial.plan.state_sha256,
            actor="medical_author",
            idempotency_key="confirm-one",
        ),
    )
    service.refresh(
        second.project_id,
        _refresh_request(second, expected_plan_revision=0, key="refresh-two"),
    )
    assert [item["operation"] for item in service.audit_history(first.project_id)] == [
        "protocol_assembly_plan_refresh",
        "protocol_assembly_plan_confirm",
    ]
    assert len(service.audit_history(second.project_id)) == 1

    restarted = MedicalWritingProtocolAssemblyPlanService(
        db_path, definitions.__getitem__
    )
    restarted_state = restarted.current_state(first.project_id)
    assert restarted_state.plan.state_sha256 == confirmed.plan.state_sha256
    assert restarted_state.confirmation_current is True

    dump = restarted.dump_state()
    restored = MedicalWritingProtocolAssemblyPlanService(
        tmp_path / "restored.sqlite3", definitions.__getitem__
    )
    restored.load_state(dump)
    assert restored.current_state(first.project_id).confirmation_current is True
    assert restored.current_state(second.project_id).plan.project_id == second.project_id
    assert len(restored.audit_history(first.project_id)) == 2

    tampered = dict(dump)
    tampered["statements"] = [*dump["statements"], "SELECT 1;"]
    with pytest.raises(RuntimeStoreIntegrityError, match="content hash mismatch"):
        restored.load_state(tampered)
    assert restored.current_state(first.project_id).plan.state_sha256 == (
        confirmed.plan.state_sha256
    )


def test_cas_conflict_and_current_update_failure_roll_back_all_state(tmp_path: Path):
    first = _definition("project-cas")
    failing = _definition("project-failing", definition_hash="e" * 64)
    definitions = {first.project_id: first, failing.project_id: failing}
    db_path = tmp_path / "assembly.sqlite3"
    service = MedicalWritingProtocolAssemblyPlanService(
        db_path, definitions.__getitem__
    )
    service.refresh(
        first.project_id,
        _refresh_request(first, expected_plan_revision=0, key="refresh-first"),
    )
    with pytest.raises(MedicalWritingProtocolAssemblyPlanStaleError):
        service.refresh(
            first.project_id,
            _refresh_request(first, expected_plan_revision=0, key="stale-refresh"),
        )
    assert len(service.history(first.project_id)) == 1
    assert len(service.audit_history(first.project_id)) == 1

    def fail_after_current(checkpoint: str) -> None:
        if checkpoint == "after_current_update":
            raise RuntimeError("injected current rollback")

    failing_service = MedicalWritingProtocolAssemblyPlanService(
        db_path,
        definitions.__getitem__,
        fault_injector=fail_after_current,
    )
    with pytest.raises(RuntimeError, match="injected current rollback"):
        failing_service.refresh(
            failing.project_id,
            _refresh_request(
                failing, expected_plan_revision=0, key="rollback-current"
            ),
        )
    assert failing_service.current_state(failing.project_id).available is False
    assert failing_service.history(failing.project_id) == []
    assert failing_service.audit_history(failing.project_id) == []


def test_medical_writing_candidate_defaults_require_author_confirmation():
    picos = EvidencePicosWorkflowResult(
        project_id="project-one",
        package_id="package-one",
        generated_at=NOW,
    )
    section = WritingSectionSummary(
        section_id="section-one",
        source_document_id="document-one",
        heading="Study design",
        anchor_path="protocol/study-design",
        source_locator="document-one#study-design",
    )
    package = WritingSourcePackageSummary(
        package_id="package-one",
        package_label="Protocol package",
        project_code="PROTO-001",
        indication="Authoritative indication",
        source_root_label="source",
        package_role="protocol",
    )

    assert section.medical_approval_status == "待作者确认"
    assert "待作者确认" in picos.formal_output_boundary
    assert "作者确认后方可冻结当前版本" in package.ai_revision_boundary
    assert "待医学批准" not in picos.formal_output_boundary
    assert "待医学批准" not in package.ai_revision_boundary


def test_protocol_assembly_plan_routes_execute_against_the_persistent_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from services.api.app import main as app_main

    definition = _definition()
    service = MedicalWritingProtocolAssemblyPlanService(
        tmp_path / "api-assembly.sqlite3",
        {definition.project_id: definition}.__getitem__,
    )
    monkeypatch.setattr(
        app_main,
        "_canonical_module_project_id",
        lambda project_id, module: project_id,
    )
    monkeypatch.setattr(
        app_main,
        "medical_writing_protocol_assembly_plan_service",
        service,
    )
    client = TestClient(app_main.app)
    base = (
        f"/api/projects/{definition.project_id}/medical-writing/"
        "protocol-assembly-plan"
    )

    preview_response = client.post(
        f"{base}/preview",
        json=_preview_request(
            definition, expected_plan_revision=0
        ).model_dump(mode="json"),
    )
    assert preview_response.status_code == 200
    assert client.get(base).json()["available"] is False

    refresh_response = client.post(
        f"{base}/refresh",
        json=_refresh_request(
            definition, expected_plan_revision=0, key="api-refresh"
        ).model_dump(mode="json"),
    )
    assert refresh_response.status_code == 200
    projection_response = client.get(f"{base}/projections/synopsis")
    assert projection_response.status_code == 200
    assert projection_response.json()["plan_sha256"] == refresh_response.json()[
        "plan"
    ]["state_sha256"]
    audit_response = client.get(f"{base}/audit")
    assert audit_response.status_code == 200
    assert len(audit_response.json()["audit"]) == 1


def test_focused_protocol_assembly_plan_endpoints_are_registered():
    from services.api.app.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    base = "/api/projects/{project_id}/medical-writing/protocol-assembly-plan"
    assert base in paths
    assert f"{base}/history" in paths
    assert f"{base}/audit" in paths
    assert f"{base}/projections/{{projection}}" in paths
    assert f"{base}/preview" in paths
    assert f"{base}/refresh" in paths
    assert f"{base}/confirm" in paths
