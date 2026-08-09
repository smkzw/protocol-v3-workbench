from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from pydantic import BaseModel

from packages.contracts.workbench_contracts import (
    MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS,
    InterventionRulesAuthority,
    InterventionRulesIpAdjustmentPolicy,
    InterventionRulesNonIpRuleClass,
    InterventionRulesProductRole,
    MedicalWritingProtocolAssemblyFactReference,
    MedicalWritingProtocolAssemblyModuleResolution,
    MedicalWritingProtocolAssemblyPlan,
    MedicalWritingProtocolAssemblyPlanChangeResult,
    MedicalWritingProtocolAssemblyPlanConfirmRequest,
    MedicalWritingProtocolAssemblyPlanCurrentState,
    MedicalWritingProtocolAssemblyPlanRefreshRequest,
    MedicalWritingProtocolAssemblyProjectionManifest,
    MedicalWritingProtocolAssemblyUnresolvedQuestion,
    MedicalWritingStudyDefinition,
    medical_writing_protocol_assembly_sha256,
)
from packages.contracts.workbench_contracts.models import (
    MedicalWritingProtocolAssemblyConsumerProjection,
    MedicalWritingProtocolAssemblyDesignDriver,
    MedicalWritingProtocolAssemblyPlanPreviewRequest,
)

from .medical_writing_design_projection import normalize_study_design
from .sqlite_runtime_store import dump_sqlite_database, load_sqlite_database


class MedicalWritingProtocolAssemblyPlanError(ValueError):
    pass


class MedicalWritingProtocolAssemblyPlanConflictError(
    MedicalWritingProtocolAssemblyPlanError
):
    pass


class MedicalWritingProtocolAssemblyPlanStaleError(
    MedicalWritingProtocolAssemblyPlanConflictError
):
    pass


class MedicalWritingProtocolAssemblyPlanBlockedError(
    MedicalWritingProtocolAssemblyPlanConflictError
):
    pass


@dataclass(frozen=True)
class _ModuleSpec:
    module_id: str
    projection_targets: tuple[str, ...]


_ALL_PROJECTIONS = tuple(MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS)
_DESIGN_PROJECTIONS = (
    "synopsis",
    "sections_toc",
    "soa",
    "study_schema_flowchart",
    "evidence_intent",
    "ai_candidate_intent",
    "docx_toc",
)
_DOCUMENT_PROJECTIONS = (
    "synopsis",
    "sections_toc",
    "evidence_intent",
    "ai_candidate_intent",
    "docx_toc",
)
_FLOW_DESIGN_PROJECTIONS = (
    "synopsis",
    "sections_toc",
    "study_schema_flowchart",
    "evidence_intent",
    "ai_candidate_intent",
    "docx_toc",
)
_PRODUCT_PROJECTIONS = (
    "synopsis",
    "sections_toc",
    "soa",
    "study_schema_flowchart",
    "evidence_intent",
    "ai_candidate_intent",
    "docx_toc",
)
_EVIDENCE_PROJECTIONS = ("evidence_intent", "ai_candidate_intent")

_PHASE1_PART_MODULES = {
    "sad": "design.phase1.sad",
    "mad": "design.phase1.mad",
    "food_effect": "design.phase1.food_effect",
    "first_in_patient": "design.phase1.first_in_patient",
    "mass_balance": "design.phase1.mass_balance",
    "ddi": "design.phase1.ddi",
    "qt": "design.phase1.qt",
    "hepatic_impairment": "design.phase1.hepatic_impairment",
    "renal_impairment": "design.phase1.renal_impairment",
    "ba_be": "design.phase1.ba_be",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _summary_text(value: Any, *, max_length: int = 240) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        value = value.value
    if isinstance(value, bool):
        text = "planned" if value else "not planned"
    elif isinstance(value, str):
        text = value.strip()
    elif isinstance(value, list):
        text = "；".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True)
    return text[:max_length]


def _fact_reference(
    definition: MedicalWritingStudyDefinition,
    fact_path: str,
    value: Any,
) -> MedicalWritingProtocolAssemblyFactReference:
    return MedicalWritingProtocolAssemblyFactReference(
        fact_id=f"study_definition:{definition.definition_id}:{fact_path}",
        fact_path=fact_path,
        value_sha256=medical_writing_protocol_assembly_sha256(_json_value(value)),
    )


def _design_driver(
    definition: MedicalWritingStudyDefinition,
    *,
    driver_id: str,
    driver_kind: str,
    decision_state: str,
    fact_path: str,
    value: Any,
    projection_targets: Iterable[str],
    value_summary: str = "",
    extra_references: Iterable[
        MedicalWritingProtocolAssemblyFactReference
    ] = (),
) -> MedicalWritingProtocolAssemblyDesignDriver:
    reference_by_path: dict[str, MedicalWritingProtocolAssemblyFactReference] = {}
    for reference in (
        _fact_reference(definition, fact_path, value),
        *list(extra_references),
    ):
        reference_by_path.setdefault(reference.fact_path, reference)
    references = list(reference_by_path.values())
    rationale_by_state = {
        "required": "authoritative fact is required across the targeted projections",
        "design_driven": "authoritative design fact shapes the targeted projections",
        "not_applicable": "authoritative design fact excludes the targeted conditional content",
        "unknown": "authoritative design fact is unresolved; consumers must not infer a clinical default",
    }
    payload = {
        "driver_id": driver_id,
        "driver_kind": driver_kind,
        "decision_state": decision_state,
        "fact_path": fact_path,
        "source_references": [
            item.model_dump(mode="json")
            for item in sorted(references, key=lambda item: item.fact_path)
        ],
        "rationale": rationale_by_state[decision_state],
        "value_summary": value_summary if decision_state != "unknown" else "",
        "projection_targets": list(projection_targets),
    }
    payload["driver_sha256"] = medical_writing_protocol_assembly_sha256(payload)
    return MedicalWritingProtocolAssemblyDesignDriver.model_validate(payload)


def _question(
    module_id: str,
    fact_path: str,
    *,
    code: str = "authoritative_fact_required",
    prompt: str = "Confirm the authoritative structured design fact before projection.",
) -> MedicalWritingProtocolAssemblyUnresolvedQuestion:
    token = re.sub(r"[^a-zA-Z0-9_.-]+", "_", fact_path).strip("_")
    return MedicalWritingProtocolAssemblyUnresolvedQuestion(
        question_id=f"{module_id}:{token}:{code}",
        code=code,
        fact_path=fact_path,
        prompt=prompt,
        severity="blocker",
    )


def _bool_driver_state(value: Optional[bool]) -> str:
    if value is True:
        return "design_driven"
    if value is False:
        return "not_applicable"
    return "unknown"


def _known_driver_state(value: Any) -> str:
    if value is None or value == "" or value == [] or value == "unknown":
        return "unknown"
    return "design_driven"


def _resolution(
    spec: _ModuleSpec,
    *,
    applicability: str,
    reason: str,
    references: Iterable[MedicalWritingProtocolAssemblyFactReference] = (),
    questions: Iterable[MedicalWritingProtocolAssemblyUnresolvedQuestion] = (),
) -> MedicalWritingProtocolAssemblyModuleResolution:
    question_list = list(questions)
    payload = {
        "module_id": spec.module_id,
        "applicability": applicability,
        "reason": reason,
        "fact_references": [item.model_dump(mode="json") for item in references],
        "unresolved_questions": [
            item.model_dump(mode="json") for item in question_list
        ],
        "blocking_severity": "blocker" if question_list else "none",
        "deterministic_projection_allowed": not question_list,
        "projection_targets": list(spec.projection_targets),
    }
    payload["resolution_sha256"] = medical_writing_protocol_assembly_sha256(payload)
    return MedicalWritingProtocolAssemblyModuleResolution.model_validate(payload)


def _required_resolution(
    definition: MedicalWritingStudyDefinition,
    spec: _ModuleSpec,
    facts: Iterable[tuple[str, Any]],
) -> MedicalWritingProtocolAssemblyModuleResolution:
    fact_list = list(facts)
    references = [
        _fact_reference(definition, fact_path, value) for fact_path, value in fact_list
    ]
    questions = [
        _question(spec.module_id, fact_path)
        for fact_path, value in fact_list
        if value is None or value == "" or value == []
    ]
    return _resolution(
        spec,
        applicability="required",
        reason=(
            "required protocol module has unresolved authoritative facts"
            if questions
            else "required protocol module is bound to authoritative facts"
        ),
        references=references,
        questions=questions,
    )


def _planned_resolution(
    definition: MedicalWritingStudyDefinition,
    spec: _ModuleSpec,
    fact_path: str,
    planned: Optional[bool],
) -> MedicalWritingProtocolAssemblyModuleResolution:
    reference = _fact_reference(definition, fact_path, planned)
    if planned is True:
        return _resolution(
            spec,
            applicability="conditional_applicable",
            reason="authoritative planned flag enables the conditional module",
            references=[reference],
        )
    if planned is False:
        return _resolution(
            spec,
            applicability="not_applicable",
            reason="authoritative planned flag excludes the conditional module",
            references=[reference],
        )
    return _resolution(
        spec,
        applicability="conditional_applicable",
        reason="authoritative planned flag is unresolved",
        references=[reference],
        questions=[_question(spec.module_id, fact_path)],
    )


def _typed_complex_resolution(
    definition: MedicalWritingStudyDefinition,
    spec: _ModuleSpec,
    fact_path: str,
    design: Any,
) -> MedicalWritingProtocolAssemblyModuleResolution:
    reference = _fact_reference(definition, fact_path, design)
    if design.planned is False:
        return _resolution(
            spec,
            applicability="not_applicable",
            reason="authoritative typed design excludes the conditional module",
            references=[reference],
        )
    if design.planned is None:
        return _resolution(
            spec,
            applicability="conditional_applicable",
            reason="authoritative typed design planned status is unresolved",
            references=[reference],
            questions=[
                _question(
                    spec.module_id,
                    f"{fact_path}.planned",
                    code=f"{spec.module_id.replace('.', '_')}_planned_required",
                    prompt=(
                        "Confirm whether this complex design is planned before "
                        "projecting its protocol content."
                    ),
                )
            ],
        )

    questions = [
        _question(
            spec.module_id,
            f"{fact_path}.{field_name}",
            code=f"{spec.module_id.replace('.', '_')}_{field_name}_required",
            prompt=(
                f"Planned {spec.module_id} requires '{field_name}' before "
                "deterministic projection."
            ),
        )
        for field_name in design.missing_required_fields()
    ]
    return _resolution(
        spec,
        applicability="conditional_applicable",
        reason=(
            "planned typed design has unresolved writing facts"
            if questions
            else "authoritative typed design enables the conditional module"
        ),
        references=[reference],
        questions=questions,
    )


def _normalized_phase1_part(value: str) -> str:
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())
    aliases = {
        "sad": "sad",
        "singleascendingdose": "sad",
        "单次递增剂量": "sad",
        "单剂量递增": "sad",
        "mad": "mad",
        "multipleascendingdose": "mad",
        "多次递增剂量": "mad",
        "多剂量递增": "mad",
        "foodeffect": "food_effect",
        "食物影响": "food_effect",
        "firstinpatient": "first_in_patient",
        "fip": "first_in_patient",
        "首次患者": "first_in_patient",
        "首次在患者": "first_in_patient",
        "massbalance": "mass_balance",
        "物质平衡": "mass_balance",
        "ddi": "ddi",
        "drugdruginteraction": "ddi",
        "药物相互作用": "ddi",
        "qt": "qt",
        "tqt": "qt",
        "qt评价": "qt",
        "hepaticimpairment": "hepatic_impairment",
        "肝损伤": "hepatic_impairment",
        "renalimpairment": "renal_impairment",
        "肾损伤": "renal_impairment",
        "babe": "ba_be",
        "生物利用度生物等效性": "ba_be",
        "生物等效性": "ba_be",
    }
    return aliases.get(compact, "")


def _phase_one_status(study_phase: str) -> Optional[bool]:
    normalized = (
        study_phase.upper()
        .replace("Ⅰ", "I")
        .replace("Ⅱ", "II")
        .replace("Ⅲ", "III")
        .replace("期", "")
        .strip()
    )
    if not normalized:
        return None
    tokens = [token for token in re.split(r"[/+\\\-]", normalized) if token]
    if any(token == "I" for token in tokens):
        return True
    if any(token in {"II", "III", "IV"} for token in tokens):
        return False
    return None


def _resolve_phase1_parts(
    definition: MedicalWritingStudyDefinition,
) -> list[MedicalWritingProtocolAssemblyModuleResolution]:
    phase_path = "framing.study_phase"
    parts_path = "framing.structured_design.phase1_parts"
    phase_one = _phase_one_status(definition.framing.study_phase)
    raw_parts = list(definition.framing.structured_design.phase1_parts)
    projection = normalize_study_design(definition)
    parts = (
        list(projection.design_view.phase1_parts)
        if phase_one is True
        else raw_parts if phase_one is None else []
    )
    indexed_parts: dict[str, tuple[int, Any]] = {}
    unknown_selected = False
    for index, part in enumerate(parts):
        part_code = str(getattr(part, "part_code", "") or "").strip()
        normalized = _normalized_phase1_part(part_code)
        if normalized:
            indexed_parts.setdefault(normalized, (index, part))
        elif part_code:
            unknown_selected = True
    selected = set(indexed_parts)

    references = [
        _fact_reference(definition, phase_path, definition.framing.study_phase),
        _fact_reference(
            definition,
            parts_path,
            [part.model_dump(mode="json") for part in raw_parts],
        ),
    ]
    resolutions: list[MedicalWritingProtocolAssemblyModuleResolution] = []
    for part_id, module_id in _PHASE1_PART_MODULES.items():
        spec = _ModuleSpec(module_id, _DESIGN_PROJECTIONS)
        if phase_one is False:
            resolutions.append(
                _resolution(
                    spec,
                    applicability="not_applicable",
                    reason="authoritative study phase excludes phase-I part modules",
                    references=references,
                )
            )
        elif phase_one is None:
            resolutions.append(
                _resolution(
                    spec,
                    applicability="conditional_applicable",
                    reason="phase-I part selection is unresolved",
                    references=references,
                    questions=[_question(module_id, parts_path)],
                )
            )
        elif not parts:
            resolutions.append(
                _resolution(
                    spec,
                    applicability="not_applicable",
                    reason="no phase-I Part is selected",
                    references=references,
                )
            )
        else:
            selected_part = indexed_parts.get(part_id)
            questions: list[MedicalWritingProtocolAssemblyUnresolvedQuestion] = []
            if selected_part is not None:
                part_index, part = selected_part
                missing_required = [
                    field_name
                    for field_name in ("population", "cohort_dose")
                    if not str(getattr(part, field_name, "") or "").strip()
                ]
                if missing_required:
                    prompt = (
                        f"Selected Part '{part_id}' is unresolved. "
                        f"Required clinical details missing: "
                        f"{', '.join(missing_required)}."
                    )
                    questions.append(
                        MedicalWritingProtocolAssemblyUnresolvedQuestion(
                            question_id=f"phase1_part_{part_id}_clinical_details_required",
                            code=f"phase1_part_{part_id}_population_cohort_required",
                            fact_path=f"{parts_path}[{part_index}]",
                            prompt=prompt,
                            severity="blocker",
                        )
                    )
            resolutions.append(
                _resolution(
                    spec,
                    applicability=(
                        "conditional_applicable"
                        if selected_part is not None
                        else "not_applicable"
                    ),
                    reason=(
                        "authoritative phase-I part selection enables the module"
                        if selected_part is not None
                        else "authoritative phase-I part selection excludes the module"
                    ),
                    references=references,
                    questions=questions,
                )
            )
    other_spec = _ModuleSpec("design.phase1.other", _DESIGN_PROJECTIONS)
    if phase_one is False:
        other = _resolution(
            other_spec,
            applicability="not_applicable",
            reason="authoritative study phase excludes phase-I part modules",
            references=references,
        )
    elif phase_one is None or unknown_selected:
        other = _resolution(
            other_spec,
            applicability="conditional_applicable",
            reason="phase-I part classification is unresolved",
            references=references,
            questions=[
                _question(
                    other_spec.module_id,
                    parts_path,
                    code="phase1_part_classification_required",
                )
            ],
        )
    elif not parts:
        other = _resolution(
            other_spec,
            applicability="not_applicable",
            reason="no phase-I Part is selected",
            references=references,
        )
    else:
        other = _resolution(
            other_spec,
            applicability="not_applicable",
            reason="no additional phase-I part is selected",
            references=references,
        )
    resolutions.append(other)
    return resolutions


def _resolve_known_choice(
    definition: MedicalWritingStudyDefinition,
    spec: _ModuleSpec,
    fact_path: str,
    value: str,
    *,
    unknown_values: set[str],
    not_applicable_values: set[str] = frozenset(),
) -> MedicalWritingProtocolAssemblyModuleResolution:
    reference = _fact_reference(definition, fact_path, value)
    if value in unknown_values:
        return _resolution(
            spec,
            applicability="conditional_applicable",
            reason="authoritative design choice is unresolved",
            references=[reference],
            questions=[_question(spec.module_id, fact_path)],
        )
    if value in not_applicable_values:
        return _resolution(
            spec,
            applicability="not_applicable",
            reason="authoritative design choice excludes the conditional module",
            references=[reference],
        )
    return _resolution(
        spec,
        applicability="conditional_applicable",
        reason="authoritative design choice enables the conditional module",
        references=[reference],
    )


def _resolve_product_facets(
    definition: MedicalWritingStudyDefinition,
) -> list[MedicalWritingProtocolAssemblyModuleResolution]:
    profile = definition.framing.product_profile
    facets = (
        (
            "product.modality",
            "framing.product_profile.technology_type",
            profile.technology_type,
            profile.technology_type == "unknown",
        ),
        (
            "product.route",
            "framing.product_profile.administration_routes",
            profile.administration_routes,
            not profile.administration_routes,
        ),
        (
            "product.dosage_form",
            "framing.product_profile.dosage_forms",
            profile.dosage_forms,
            not profile.dosage_forms,
        ),
        (
            "product.exposure_scope",
            "framing.product_profile.exposure_scope",
            profile.exposure_scope,
            profile.exposure_scope == "unknown",
        ),
    )
    resolutions: list[MedicalWritingProtocolAssemblyModuleResolution] = []
    for module_id, fact_path, value, unknown in facets:
        spec = _ModuleSpec(module_id, _PRODUCT_PROJECTIONS)
        reference = _fact_reference(definition, fact_path, value)
        resolutions.append(
            _resolution(
                spec,
                applicability="conditional_applicable",
                reason=(
                    "authoritative product facet is unresolved"
                    if unknown
                    else "authoritative product facet enables route-specific projection"
                ),
                references=[reference],
                questions=[_question(module_id, fact_path)] if unknown else [],
            )
        )

    route_path = "framing.product_profile.administration_routes"
    exposure_path = "framing.product_profile.exposure_scope"
    default_spec = _ModuleSpec("evidence.systemic_oral_defaults", _EVIDENCE_PROJECTIONS)
    references = [
        _fact_reference(definition, route_path, profile.administration_routes),
        _fact_reference(definition, exposure_path, profile.exposure_scope),
    ]
    normalized_routes = [item.lower().strip() for item in profile.administration_routes]
    local_markers = (
        "topical",
        "inhaled",
        "intranasal",
        "nasal",
        "外用",
        "吸入",
        "鼻喷",
        "鼻内",
    )
    oral_markers = ("oral", "口服")
    has_local_route = any(
        marker in route for route in normalized_routes for marker in local_markers
    )
    has_oral_route = any(
        marker in route for route in normalized_routes for marker in oral_markers
    )
    if not normalized_routes or profile.exposure_scope == "unknown":
        questions = []
        if not normalized_routes:
            questions.append(_question(default_spec.module_id, route_path))
        if profile.exposure_scope == "unknown":
            questions.append(_question(default_spec.module_id, exposure_path))
        default_resolution = _resolution(
            default_spec,
            applicability="conditional_applicable",
            reason="route or exposure facts are unresolved",
            references=references,
            questions=questions,
        )
    elif has_local_route or profile.exposure_scope in {"local", "mixed"}:
        default_resolution = _resolution(
            default_spec,
            applicability="not_applicable",
            reason="authoritative route or exposure excludes systemic oral defaults",
            references=references,
        )
    elif has_oral_route and profile.exposure_scope == "systemic":
        default_resolution = _resolution(
            default_spec,
            applicability="conditional_applicable",
            reason="authoritative route and exposure permit systemic oral defaults",
            references=references,
        )
    else:
        default_resolution = _resolution(
            default_spec,
            applicability="not_applicable",
            reason="authoritative route does not support systemic oral defaults",
            references=references,
        )
    resolutions.append(default_resolution)
    return resolutions


def _resolve_intervention_roles(
    definition: MedicalWritingStudyDefinition,
) -> list[MedicalWritingProtocolAssemblyModuleResolution]:
    picos = definition.picos
    design = definition.framing.structured_design
    rules = picos.intervention_rules
    rules_path = "picos.intervention_rules"
    role_specs = {
        "investigational": _ModuleSpec(
            "intervention.investigational_product_regimen", _ALL_PROJECTIONS
        ),
        "active": _ModuleSpec(
            "intervention.active_comparator_regimen", _ALL_PROJECTIONS
        ),
        "placebo": _ModuleSpec("intervention.placebo_regimen", _ALL_PROJECTIONS),
        "background": _ModuleSpec(
            "intervention.background_treatment", _ALL_PROJECTIONS
        ),
        "permitted": _ModuleSpec(
            "intervention.permitted_concomitant_treatment", _ALL_PROJECTIONS
        ),
        "prohibited": _ModuleSpec(
            "intervention.prohibited_concomitant_treatment", _ALL_PROJECTIONS
        ),
        "rescue": _ModuleSpec("intervention.rescue_treatment", _ALL_PROJECTIONS),
        "ip_actions": _ModuleSpec(
            "intervention.investigational_product_dose_actions", _ALL_PROJECTIONS
        ),
    }
    if rules is None or rules.authority != InterventionRulesAuthority.STRUCTURED:
        reference = _fact_reference(definition, rules_path, rules)
        return [
            _resolution(
                spec,
                applicability="conditional_applicable",
                reason="role-distinct structured intervention authority is unresolved",
                references=[reference],
                questions=[
                    _question(
                        spec.module_id,
                        rules_path,
                        code="structured_intervention_authority_required",
                    )
                ],
            )
            for spec in role_specs.values()
        ]

    regimens_path = "picos.intervention_rules.ip_regimens"
    regimen_reference = _fact_reference(definition, regimens_path, rules.ip_regimens)
    ip_regimens = [
        item
        for item in rules.ip_regimens
        if item.product_role == InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT
    ]
    active_regimens = [
        item
        for item in rules.ip_regimens
        if item.product_role == InterventionRulesProductRole.ACTIVE_COMPARATOR
    ]
    placebo_regimens = [
        item
        for item in rules.ip_regimens
        if item.product_role == InterventionRulesProductRole.PLACEBO
    ]
    resolutions: list[MedicalWritingProtocolAssemblyModuleResolution] = []
    resolutions.append(
        _resolution(
            role_specs["investigational"],
            applicability="conditional_applicable",
            reason=(
                "authoritative investigational-product regimen is role-bound"
                if ip_regimens
                else "authoritative investigational-product regimen is missing"
            ),
            references=[regimen_reference],
            questions=(
                []
                if ip_regimens
                else [
                    _question(
                        role_specs["investigational"].module_id,
                        regimens_path,
                        code="investigational_product_regimen_required",
                    )
                ]
            ),
        )
    )

    comparator_path = "framing.structured_design.comparator_type"
    comparator_reference = _fact_reference(
        definition, comparator_path, design.comparator_type
    )
    active_questions: list[MedicalWritingProtocolAssemblyUnresolvedQuestion] = []
    if design.comparator_type == "undecided":
        active_questions.append(
            _question(role_specs["active"].module_id, comparator_path)
        )
    elif design.comparator_type == "active":
        if len(active_regimens) != 1:
            active_questions.append(
                _question(
                    role_specs["active"].module_id,
                    regimens_path,
                    code="unique_active_comparator_regimen_required",
                )
            )
        elif (
            not active_regimens[0].dose_and_frequency.strip()
            or not active_regimens[0].route.strip()
        ):
            active_questions.append(
                _question(
                    role_specs["active"].module_id,
                    regimens_path,
                    code="complete_active_comparator_regimen_required",
                )
            )
    elif active_regimens:
        active_questions.append(
            _question(
                role_specs["active"].module_id,
                comparator_path,
                code="active_comparator_role_conflict",
            )
        )
    active_applicable = design.comparator_type == "active" or bool(active_regimens)
    resolutions.append(
        _resolution(
            role_specs["active"],
            applicability=(
                "conditional_applicable"
                if active_applicable or active_questions
                else "not_applicable"
            ),
            reason=(
                "active-comparator role requires one authoritative regimen"
                if active_applicable or active_questions
                else "authoritative comparator design excludes active comparator"
            ),
            references=[comparator_reference, regimen_reference],
            questions=active_questions,
        )
    )

    placebo_questions: list[MedicalWritingProtocolAssemblyUnresolvedQuestion] = []
    if design.comparator_type == "undecided":
        placebo_questions.append(
            _question(role_specs["placebo"].module_id, comparator_path)
        )
    elif design.comparator_type == "placebo" and not placebo_regimens:
        placebo_questions.append(
            _question(
                role_specs["placebo"].module_id,
                regimens_path,
                code="placebo_regimen_required",
            )
        )
    placebo_applicable = design.comparator_type == "placebo" or bool(placebo_regimens)
    resolutions.append(
        _resolution(
            role_specs["placebo"],
            applicability=(
                "conditional_applicable"
                if placebo_applicable or placebo_questions
                else "not_applicable"
            ),
            reason=(
                "placebo remains a distinct intervention role"
                if placebo_applicable or placebo_questions
                else "authoritative comparator design excludes placebo"
            ),
            references=[comparator_reference, regimen_reference],
            questions=placebo_questions,
        )
    )

    non_ip_path = "picos.intervention_rules.non_ip_treatment_rules"
    non_ip_reference = _fact_reference(
        definition, non_ip_path, rules.non_ip_treatment_rules
    )
    rule_classes = {
        "background": InterventionRulesNonIpRuleClass.BACKGROUND,
        "permitted": InterventionRulesNonIpRuleClass.ALLOWED_CM,
        "prohibited": InterventionRulesNonIpRuleClass.PROHIBITED_CM,
        "rescue": InterventionRulesNonIpRuleClass.RESCUE,
    }
    for key, rule_class in rule_classes.items():
        present = any(
            item.rule_class == rule_class for item in rules.non_ip_treatment_rules
        )
        resolutions.append(
            _resolution(
                role_specs[key],
                applicability=(
                    "conditional_applicable" if present else "not_applicable"
                ),
                reason=(
                    "authoritative non-IP rule class enables its role-distinct module"
                    if present
                    else "authoritative non-IP rules exclude this role class"
                ),
                references=[non_ip_reference],
            )
        )

    adjustment_path = "picos.intervention_rules.ip_adjustment_policy"
    actions_path = "picos.intervention_rules.ip_action_rules"
    action_references = [
        _fact_reference(definition, adjustment_path, rules.ip_adjustment_policy),
        _fact_reference(definition, actions_path, rules.ip_action_rules),
    ]
    if rules.ip_adjustment_policy == InterventionRulesIpAdjustmentPolicy.UNSPECIFIED:
        ip_action_resolution = _resolution(
            role_specs["ip_actions"],
            applicability="conditional_applicable",
            reason="investigational-product action policy is unresolved",
            references=action_references,
            questions=[_question(role_specs["ip_actions"].module_id, adjustment_path)],
        )
    elif (
        rules.ip_adjustment_policy
        == InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
    ):
        ip_action_resolution = _resolution(
            role_specs["ip_actions"],
            applicability="not_applicable",
            reason="authoritative IP policy has no planned dose adjustment",
            references=action_references,
        )
    else:
        ip_action_resolution = _resolution(
            role_specs["ip_actions"],
            applicability="conditional_applicable",
            reason="authoritative IP action rules enable the dose-action module",
            references=action_references,
            questions=(
                []
                if rules.ip_action_rules
                else [_question(role_specs["ip_actions"].module_id, actions_path)]
            ),
        )
    resolutions.append(ip_action_resolution)
    return resolutions


def resolve_protocol_assembly_modules(
    definition: MedicalWritingStudyDefinition,
) -> list[MedicalWritingProtocolAssemblyModuleResolution]:
    design = definition.framing.structured_design
    modules: list[MedicalWritingProtocolAssemblyModuleResolution] = [
        _required_resolution(
            definition,
            _ModuleSpec("core.protocol_identity", _ALL_PROJECTIONS),
            (
                ("framing.protocol_id", definition.framing.protocol_id),
                ("framing.indication", definition.framing.indication),
                ("framing.study_phase", definition.framing.study_phase),
            ),
        ),
        _required_resolution(
            definition,
            _ModuleSpec("core.population_endpoints", _ALL_PROJECTIONS),
            (
                ("picos.population_summary", definition.picos.population_summary),
                ("picos.primary_endpoint", definition.picos.primary_endpoint),
            ),
        ),
        _resolve_known_choice(
            definition,
            _ModuleSpec("design.randomization", _DESIGN_PROJECTIONS),
            "framing.structured_design.randomization_mode",
            design.randomization_mode,
            unknown_values={"undecided"},
            not_applicable_values={"non_randomized"},
        ),
        _resolve_known_choice(
            definition,
            _ModuleSpec("design.blinding", _DOCUMENT_PROJECTIONS),
            "framing.structured_design.blinding_mode",
            design.blinding_mode,
            unknown_values={"undecided"},
            not_applicable_values={"open_label"},
        ),
        _resolve_known_choice(
            definition,
            _ModuleSpec("design.comparator_control", _DESIGN_PROJECTIONS),
            "framing.structured_design.comparator_type",
            design.comparator_type,
            unknown_values={"undecided"},
            not_applicable_values={"none_or_dose_escalation"},
        ),
    ]
    allocation_path = "framing.structured_design.assignment_model"
    allocation_reference = _fact_reference(
        definition, allocation_path, design.assignment_model
    )
    modules.append(
        _resolution(
            _ModuleSpec("design.allocation_model", _DESIGN_PROJECTIONS),
            applicability="conditional_applicable",
            reason=(
                "authoritative allocation model enables the design module"
                if design.assignment_model
                else "authoritative allocation model is unresolved"
            ),
            references=[allocation_reference],
            questions=(
                []
                if design.assignment_model
                else [_question("design.allocation_model", allocation_path)]
            ),
        )
    )
    modules.extend(_resolve_phase1_parts(definition))
    typed_complex_modules = (
        (
            "design.sample_size_reestimation",
            "framing.structured_design.sample_size_reestimation",
            design.sample_size_reestimation,
            _DOCUMENT_PROJECTIONS,
        ),
        (
            "design.adaptive",
            "framing.structured_design.adaptive_design",
            design.adaptive_design,
            _FLOW_DESIGN_PROJECTIONS,
        ),
        (
            "design.treatment_switch",
            "framing.structured_design.treatment_switch",
            design.treatment_switch,
            _DESIGN_PROJECTIONS,
        ),
        (
            "design.crossover",
            "framing.structured_design.crossover",
            design.crossover,
            _DESIGN_PROJECTIONS,
        ),
        (
            "design.open_label_extension",
            "framing.structured_design.open_label_extension",
            design.open_label_extension,
            _DESIGN_PROJECTIONS,
        ),
    )
    for module_id, fact_path, typed_design, targets in typed_complex_modules:
        modules.append(
            _typed_complex_resolution(
                definition,
                _ModuleSpec(module_id, targets),
                fact_path,
                typed_design,
            )
        )

    planned_modules = (
        (
            "design.interim_analysis",
            "framing.structured_design.interim_analysis.planned",
            design.interim_analysis.planned,
            _DESIGN_PROJECTIONS,
        ),
        (
            "governance.src",
            "framing.structured_design.src_planned",
            design.src_planned,
            _DESIGN_PROJECTIONS,
        ),
        (
            "governance.dmc",
            "framing.structured_design.dmc_planned",
            design.dmc_planned,
            _DESIGN_PROJECTIONS,
        ),
    )
    for module_id, fact_path, planned, targets in planned_modules:
        modules.append(
            _planned_resolution(
                definition,
                _ModuleSpec(module_id, targets),
                fact_path,
                planned,
            )
        )
    modules.extend(_resolve_product_facets(definition))
    modules.extend(_resolve_intervention_roles(definition))
    return sorted(modules, key=lambda item: item.module_id)


def resolve_protocol_assembly_design_drivers(
    definition: MedicalWritingStudyDefinition,
) -> list[MedicalWritingProtocolAssemblyDesignDriver]:
    framing = definition.framing
    design = framing.structured_design
    profile = framing.product_profile
    picos = definition.picos
    rules = picos.intervention_rules
    drivers: list[MedicalWritingProtocolAssemblyDesignDriver] = [
        _design_driver(
            definition,
            driver_id="core.phase",
            driver_kind="phase",
            decision_state="required",
            fact_path="framing.study_phase",
            value=framing.study_phase,
            value_summary=_summary_text(framing.study_phase),
            projection_targets=_ALL_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="core.indication",
            driver_kind="indication",
            decision_state="required",
            fact_path="framing.indication",
            value=framing.indication,
            value_summary=_summary_text(framing.indication),
            projection_targets=_ALL_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="product.modality",
            driver_kind="drug_modality",
            decision_state=_known_driver_state(profile.technology_type),
            fact_path="framing.product_profile.technology_type",
            value=profile.technology_type,
            value_summary=_summary_text(profile.technology_type),
            projection_targets=_PRODUCT_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="product.route",
            driver_kind="drug_route",
            decision_state=_known_driver_state(profile.administration_routes),
            fact_path="framing.product_profile.administration_routes",
            value=profile.administration_routes,
            value_summary=_summary_text(profile.administration_routes),
            projection_targets=_PRODUCT_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="product.dosage_form",
            driver_kind="dosage_form",
            decision_state=_known_driver_state(profile.dosage_forms),
            fact_path="framing.product_profile.dosage_forms",
            value=profile.dosage_forms,
            value_summary=_summary_text(profile.dosage_forms),
            projection_targets=_PRODUCT_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="product.exposure_scope",
            driver_kind="exposure_scope",
            decision_state=_known_driver_state(profile.exposure_scope),
            fact_path="framing.product_profile.exposure_scope",
            value=profile.exposure_scope,
            value_summary=_summary_text(profile.exposure_scope),
            projection_targets=_PRODUCT_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="design.randomization",
            driver_kind="randomization",
            decision_state=(
                "unknown"
                if design.randomization_mode == "undecided"
                else (
                    "not_applicable"
                    if design.randomization_mode == "non_randomized"
                    else "design_driven"
                )
            ),
            fact_path="framing.structured_design.randomization_mode",
            value=design.randomization_mode,
            value_summary=_summary_text(design.randomization_mode),
            projection_targets=_DESIGN_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="design.blinding",
            driver_kind="blinding",
            decision_state=(
                "unknown"
                if design.blinding_mode == "undecided"
                else (
                    "not_applicable"
                    if design.blinding_mode == "open_label"
                    else "design_driven"
                )
            ),
            fact_path="framing.structured_design.blinding_mode",
            value=design.blinding_mode,
            value_summary=_summary_text(design.blinding_mode),
            projection_targets=_DOCUMENT_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="design.control",
            driver_kind="control",
            decision_state=(
                "unknown"
                if design.comparator_type == "undecided"
                else (
                    "not_applicable"
                    if design.comparator_type == "none_or_dose_escalation"
                    else "design_driven"
                )
            ),
            fact_path="framing.structured_design.comparator_type",
            value=design.comparator_type,
            value_summary=_summary_text(design.comparator_type),
            projection_targets=_DESIGN_PROJECTIONS,
        ),
        _design_driver(
            definition,
            driver_id="design.allocation",
            driver_kind="allocation",
            decision_state=_known_driver_state(design.assignment_model),
            fact_path="framing.structured_design.assignment_model",
            value=design.assignment_model,
            value_summary=_summary_text(design.assignment_model),
            projection_targets=_DESIGN_PROJECTIONS,
        ),
    ]

    phase_one = _phase_one_status(framing.study_phase)
    # Typed Parts: extract part_code from each MedicalWritingPhase1Part.
    part_codes_for_norm = [
        p.part_code for p in design.phase1_parts if hasattr(p, "part_code")
    ]
    normalized_parts = {
        item for item in (_normalized_phase1_part(code) for code in part_codes_for_norm) if item
    }
    part_reference = _fact_reference(
        definition,
        "framing.structured_design.phase1_parts",
        [p.model_dump(mode="json") for p in design.phase1_parts],
    )
    phase_reference = _fact_reference(definition, "framing.study_phase", framing.study_phase)
    for part_id in sorted(_PHASE1_PART_MODULES):
        if phase_one is False:
            state = "not_applicable"
            summary = "study phase excludes phase-I parts"
        elif phase_one is None or not design.phase1_parts:
            state = "unknown"
            summary = ""
        elif part_id in normalized_parts:
            state = "design_driven"
            summary = f"selected:{part_id}"
        else:
            state = "not_applicable"
            summary = f"not selected:{part_id}"
        drivers.append(
            _design_driver(
                definition,
                driver_id=f"design.phase1_part.{part_id}",
                driver_kind="phase1_part",
                decision_state=state,
                fact_path="framing.structured_design.phase1_parts",
                value=design.phase1_parts,
                value_summary=summary,
                projection_targets=_DESIGN_PROJECTIONS,
                extra_references=[phase_reference, part_reference],
            )
        )

    planned_drivers = (
        (
            "design.interim_analysis",
            "interim_analysis",
            "framing.structured_design.interim_analysis.planned",
            design.interim_analysis.planned,
            _DESIGN_PROJECTIONS,
        ),
        (
            "design.treatment_switch",
            "treatment_switch",
            "framing.structured_design.treatment_switch",
            design.treatment_switch,
            _DESIGN_PROJECTIONS,
        ),
        (
            "design.crossover",
            "crossover",
            "framing.structured_design.crossover",
            design.crossover,
            _DESIGN_PROJECTIONS,
        ),
        (
            "design.open_label_extension",
            "open_label_extension",
            "framing.structured_design.open_label_extension",
            design.open_label_extension,
            _DESIGN_PROJECTIONS,
        ),
        (
            "design.sample_size_reestimation",
            "sample_size_reestimation",
            "framing.structured_design.sample_size_reestimation",
            design.sample_size_reestimation,
            _DOCUMENT_PROJECTIONS,
        ),
        (
            "design.adaptive",
            "adaptive_design",
            "framing.structured_design.adaptive_design",
            design.adaptive_design,
            _FLOW_DESIGN_PROJECTIONS,
        ),
        (
            "governance.src",
            "src",
            "framing.structured_design.src_planned",
            design.src_planned,
            _DESIGN_PROJECTIONS,
        ),
        (
            "governance.dmc",
            "dmc",
            "framing.structured_design.dmc_planned",
            design.dmc_planned,
            _DESIGN_PROJECTIONS,
        ),
    )
    for driver_id, driver_kind, fact_path, value, targets in planned_drivers:
        planned = value.planned if hasattr(value, "planned") else value
        drivers.append(
            _design_driver(
                definition,
                driver_id=driver_id,
                driver_kind=driver_kind,
                decision_state=_bool_driver_state(planned),
                fact_path=fact_path,
                value=value,
                value_summary=_summary_text(value if planned is True else planned),
                projection_targets=targets,
            )
        )

    rules_known = rules is not None and rules.authority == InterventionRulesAuthority.STRUCTURED
    non_ip_rules = rules.non_ip_treatment_rules if rules_known else []
    rule_classes = [item.rule_class for item in non_ip_rules]
    background_count = sum(
        1 for item in rule_classes if item == InterventionRulesNonIpRuleClass.BACKGROUND
    )
    drivers.append(
        _design_driver(
            definition,
            driver_id="intervention.background_treatment",
            driver_kind="background_treatment",
            decision_state=(
                "unknown"
                if not rules_known
                else ("design_driven" if background_count else "not_applicable")
            ),
            fact_path="picos.intervention_rules.non_ip_treatment_rules",
            value=non_ip_rules if rules_known else None,
            value_summary=(
                f"{background_count} background treatment rule(s)"
                if background_count
                else ("no background treatment rule" if rules_known else "")
            ),
            projection_targets=_ALL_PROJECTIONS,
        )
    )
    ip_regimens = rules.ip_regimens if rules_known else []
    role_counts = {
        "ip_regimen": sum(
            1
            for item in ip_regimens
            if item.product_role == InterventionRulesProductRole.INVESTIGATIONAL_PRODUCT
        ),
        "active_comparator": sum(
            1
            for item in ip_regimens
            if item.product_role == InterventionRulesProductRole.ACTIVE_COMPARATOR
        ),
        "placebo": sum(
            1 for item in ip_regimens if item.product_role == InterventionRulesProductRole.PLACEBO
        ),
    }
    for driver_kind, count in role_counts.items():
        drivers.append(
            _design_driver(
                definition,
                driver_id=f"intervention.{driver_kind}",
                driver_kind=driver_kind,
                decision_state=(
                    "unknown"
                    if not rules_known
                    else ("design_driven" if count else "not_applicable")
                ),
                fact_path="picos.intervention_rules.ip_regimens",
                value=ip_regimens if rules_known else None,
                value_summary=f"{count} role-bound regimen(s)" if rules_known else "",
                projection_targets=_ALL_PROJECTIONS,
            )
        )
    adjustment = rules.ip_adjustment_policy if rules_known else None
    action_count = len(rules.ip_action_rules) if rules_known else 0
    drivers.append(
        _design_driver(
            definition,
            driver_id="intervention.dose_action",
            driver_kind="dose_action",
            decision_state=(
                "unknown"
                if adjustment is None
                or adjustment == InterventionRulesIpAdjustmentPolicy.UNSPECIFIED
                else (
                    "not_applicable"
                    if adjustment
                    == InterventionRulesIpAdjustmentPolicy.NO_PLANNED_ADJUSTMENT
                    else "design_driven"
                )
            ),
            fact_path="picos.intervention_rules.ip_adjustment_policy",
            value=adjustment,
            value_summary=(
                f"{action_count} IP action rule(s)"
                if action_count
                else _summary_text(adjustment)
            ),
            projection_targets=_ALL_PROJECTIONS,
        )
    )
    drivers.append(
        _design_driver(
            definition,
            driver_id="safety.aesi",
            driver_kind="aesi",
            decision_state=(
                "design_driven" if picos.aesi_definitions else "unknown"
            ),
            fact_path="picos.aesi_definitions",
            value=picos.aesi_definitions,
            value_summary=(
                f"{len(picos.aesi_definitions)} AESI definition(s)"
                if picos.aesi_definitions
                else ""
            ),
            projection_targets=_DOCUMENT_PROJECTIONS,
        )
    )
    pk_pd_sources = [
        *profile.pk_pd_considerations,
        *([framing.study_phase] if phase_one else []),
    ]
    drivers.append(
        _design_driver(
            definition,
            driver_id="science.pk_pd",
            driver_kind="pk_pd",
            decision_state="design_driven" if pk_pd_sources else "unknown",
            fact_path="framing.product_profile.pk_pd_considerations",
            value=profile.pk_pd_considerations,
            value_summary=(
                f"{len(pk_pd_sources)} PK/PD driver(s)" if pk_pd_sources else ""
            ),
            projection_targets=_DESIGN_PROJECTIONS,
        )
    )
    drivers.append(
        _design_driver(
            definition,
            driver_id="statistics.analysis_set",
            driver_kind="analysis_set",
            decision_state=_known_driver_state(picos.statistical_strategy),
            fact_path="picos.statistical_strategy",
            value=picos.statistical_strategy,
            value_summary=_summary_text(picos.statistical_strategy),
            projection_targets=_DOCUMENT_PROJECTIONS,
        )
    )
    drivers.append(
        _design_driver(
            definition,
            driver_id="operations.soa",
            driver_kind="soa",
            decision_state=(
                "design_driven"
                if picos.visit_strategy or picos.study_epochs
                else "unknown"
            ),
            fact_path="picos.visit_strategy",
            value=picos.visit_strategy or picos.study_epochs,
            value_summary=(
                _summary_text(picos.visit_strategy)
                or f"{len(picos.study_epochs)} study epoch(s)"
            ),
            projection_targets=("soa", "evidence_intent", "ai_candidate_intent"),
        )
    )
    drivers.append(
        _design_driver(
            definition,
            driver_id="operations.study_schema_flowchart",
            driver_kind="study_schema_flowchart",
            decision_state="design_driven" if definition.study_schema else "unknown",
            fact_path="study_schema",
            value=definition.study_schema,
            value_summary=(
                f"study schema revision {definition.study_schema.revision}"
                if definition.study_schema
                else ""
            ),
            projection_targets=(
                "study_schema_flowchart",
                "evidence_intent",
                "ai_candidate_intent",
            ),
        )
    )
    return sorted(drivers, key=lambda item: item.driver_id)


def build_protocol_assembly_projection_manifest(
    modules: list[MedicalWritingProtocolAssemblyModuleResolution],
) -> list[MedicalWritingProtocolAssemblyProjectionManifest]:
    manifests: list[MedicalWritingProtocolAssemblyProjectionManifest] = []
    for projection in MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS:
        relevant = [
            module for module in modules if projection in module.projection_targets
        ]
        applicable = sorted(
            module.module_id
            for module in relevant
            if module.deterministic_projection_allowed
            and module.applicability != "not_applicable"
        )
        not_applicable = sorted(
            module.module_id
            for module in relevant
            if module.deterministic_projection_allowed
            and module.applicability == "not_applicable"
        )
        unresolved = sorted(
            module.module_id
            for module in relevant
            if not module.deterministic_projection_allowed
        )
        content_sha256 = medical_writing_protocol_assembly_sha256(
            {
                "projection": projection,
                "modules": {
                    module.module_id: module.resolution_sha256
                    for module in sorted(relevant, key=lambda item: item.module_id)
                },
            }
        )
        manifests.append(
            MedicalWritingProtocolAssemblyProjectionManifest(
                projection=projection,
                applicable_module_ids=applicable,
                not_applicable_module_ids=not_applicable,
                unresolved_module_ids=unresolved,
                content_sha256=content_sha256,
            )
        )
    return manifests


def _affected_modules(
    previous: Optional[MedicalWritingProtocolAssemblyPlan],
    modules: list[MedicalWritingProtocolAssemblyModuleResolution],
) -> list[str]:
    if previous is None:
        return [module.module_id for module in modules]
    previous_hashes = {
        module.module_id: module.resolution_sha256 for module in previous.modules
    }
    return sorted(
        module.module_id
        for module in modules
        if previous_hashes.get(module.module_id) != module.resolution_sha256
    )


def _affected_projections(
    modules: list[MedicalWritingProtocolAssemblyModuleResolution],
    affected_module_ids: list[str],
) -> list[str]:
    affected = set(affected_module_ids)
    projections = {
        projection
        for module in modules
        if module.module_id in affected
        for projection in module.projection_targets
    }
    return [
        projection
        for projection in MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS
        if projection in projections
    ]


def build_protocol_assembly_plan(
    definition: MedicalWritingStudyDefinition,
    *,
    plan_id: str,
    revision: int,
    actor: str,
    now: datetime,
    previous: Optional[MedicalWritingProtocolAssemblyPlan] = None,
    confirmed_by: str = "",
    confirmed_at: Optional[datetime] = None,
) -> MedicalWritingProtocolAssemblyPlan:
    if definition.project_id == "":
        raise ValueError("StudyDefinition project_id is required")
    modules = resolve_protocol_assembly_modules(definition)
    design_drivers = resolve_protocol_assembly_design_drivers(definition)
    affected_module_ids = _affected_modules(previous, modules)
    affected_projections = _affected_projections(modules, affected_module_ids)
    payload = {
        "schema_version": "medical_writing_protocol_assembly_plan_v1",
        "plan_id": plan_id,
        "revision": revision,
        "project_id": definition.project_id,
        "source_definition_id": definition.definition_id,
        "source_definition_revision": definition.revision,
        "source_definition_sha256": definition.state_sha256,
        "modules": [module.model_dump(mode="json") for module in modules],
        "design_drivers": [
            driver.model_dump(mode="json") for driver in design_drivers
        ],
        "projection_manifest": [
            item.model_dump(mode="json")
            for item in build_protocol_assembly_projection_manifest(modules)
        ],
        "previous_plan_revision": previous.revision if previous else 0,
        "affected_module_ids": affected_module_ids,
        "affected_projections": affected_projections,
        "confirmation_status": "author_confirmed" if confirmed_by else "draft",
        "confirmation_kind": "author_plan_confirmation",
        "created_by": previous.created_by if previous else actor,
        "created_at": previous.created_at if previous else now,
        "updated_by": actor,
        "updated_at": now,
        "confirmed_by": confirmed_by,
        "confirmed_at": confirmed_at,
    }
    payload["state_sha256"] = medical_writing_protocol_assembly_sha256(payload)
    return MedicalWritingProtocolAssemblyPlan.model_validate(payload)


def _plan_id(project_id: str) -> str:
    digest = sha256(project_id.encode("utf-8")).hexdigest()[:24]
    return f"protocol_assembly_plan_{digest}"


class MedicalWritingProtocolAssemblyPlanService:
    def __init__(
        self,
        db_path: Path,
        definition_provider: Callable[[str], MedicalWritingStudyDefinition],
        *,
        fault_injector: Optional[Callable[[str], None]] = None,
        now_factory: Callable[[], datetime] = _utc_now,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.definition_provider = definition_provider
        self.fault_injector = fault_injector
        self.now_factory = now_factory
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS medical_writing_protocol_assembly_plan_history (
                    project_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    source_definition_id TEXT NOT NULL,
                    source_definition_revision INTEGER NOT NULL CHECK (
                        source_definition_revision >= 1
                    ),
                    source_definition_sha256 TEXT NOT NULL,
                    state_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, plan_id, revision),
                    UNIQUE (project_id, revision)
                );

                CREATE TABLE IF NOT EXISTS medical_writing_protocol_assembly_plan_current (
                    project_id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    source_definition_id TEXT NOT NULL,
                    source_definition_revision INTEGER NOT NULL,
                    source_definition_sha256 TEXT NOT NULL,
                    state_sha256 TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id, plan_id, revision)
                    REFERENCES medical_writing_protocol_assembly_plan_history(
                        project_id, plan_id, revision
                    )
                );

                CREATE TABLE IF NOT EXISTS medical_writing_protocol_assembly_plan_idempotency (
                    project_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (project_id, operation, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS medical_writing_protocol_assembly_plan_audit (
                    project_id TEXT NOT NULL,
                    audit_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    plan_revision INTEGER NOT NULL CHECK (plan_revision >= 1),
                    state_sha256 TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (project_id, audit_id)
                );

                CREATE TRIGGER IF NOT EXISTS trg_protocol_assembly_history_no_update
                BEFORE UPDATE ON medical_writing_protocol_assembly_plan_history BEGIN
                    SELECT RAISE(ABORT, 'protocol assembly plan history is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_protocol_assembly_history_no_delete
                BEFORE DELETE ON medical_writing_protocol_assembly_plan_history BEGIN
                    SELECT RAISE(ABORT, 'protocol assembly plan history is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_protocol_assembly_idempotency_no_update
                BEFORE UPDATE ON medical_writing_protocol_assembly_plan_idempotency BEGIN
                    SELECT RAISE(ABORT, 'protocol assembly idempotency is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_protocol_assembly_idempotency_no_delete
                BEFORE DELETE ON medical_writing_protocol_assembly_plan_idempotency BEGIN
                    SELECT RAISE(ABORT, 'protocol assembly idempotency is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_protocol_assembly_audit_no_update
                BEFORE UPDATE ON medical_writing_protocol_assembly_plan_audit BEGIN
                    SELECT RAISE(ABORT, 'protocol assembly audit is immutable');
                END;
                CREATE TRIGGER IF NOT EXISTS trg_protocol_assembly_audit_no_delete
                BEFORE DELETE ON medical_writing_protocol_assembly_plan_audit BEGIN
                    SELECT RAISE(ABORT, 'protocol assembly audit is immutable');
                END;
                """
            )

    def current_state(
        self, project_id: str
    ) -> MedicalWritingProtocolAssemblyPlanCurrentState:
        with self._connect() as connection:
            plan = self._current_plan(connection, project_id)
        if plan is None:
            return MedicalWritingProtocolAssemblyPlanCurrentState(
                project_id=project_id,
                available=False,
            )
        definition = self._definition(project_id)
        source_current = self._source_matches(plan, definition)
        blockers = [
            module.module_id
            for module in plan.modules
            if not module.deterministic_projection_allowed
        ]
        blockers.extend(
            driver.driver_id
            for driver in plan.design_drivers
            if driver.decision_state == "unknown"
        )
        return MedicalWritingProtocolAssemblyPlanCurrentState(
            project_id=project_id,
            available=True,
            source_current=source_current,
            confirmation_current=(
                source_current and plan.confirmation_status == "author_confirmed"
            ),
            deterministic_projection_allowed=source_current and not blockers,
            stale_reason=(
                ""
                if source_current
                else "StudyDefinition revision or hash changed; refresh the assembly plan"
            ),
            plan=plan,
        )

    def history(self, project_id: str) -> list[MedicalWritingProtocolAssemblyPlan]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_protocol_assembly_plan_history
                WHERE project_id = ?
                ORDER BY revision
                """,
                (project_id,),
            ).fetchall()
        return [
            MedicalWritingProtocolAssemblyPlan.model_validate(
                json.loads(row["payload_json"])
            )
            for row in rows
        ]

    def preview(
        self,
        project_id: str,
        request: MedicalWritingProtocolAssemblyPlanPreviewRequest,
    ) -> MedicalWritingProtocolAssemblyPlanChangeResult:
        definition = self._definition(project_id)
        self._require_expected_definition(definition, request)
        with self._connect() as connection:
            current = self._current_plan(connection, project_id)
        actual_revision = current.revision if current else 0
        if actual_revision != request.expected_plan_revision:
            raise MedicalWritingProtocolAssemblyPlanStaleError(
                "stale protocol assembly plan revision: "
                f"expected {request.expected_plan_revision}, actual {actual_revision}"
            )
        candidate = build_protocol_assembly_plan(
            definition,
            plan_id=current.plan_id if current else _plan_id(project_id),
            revision=actual_revision + 1,
            actor=request.actor,
            now=self.now_factory(),
            previous=current,
        )
        self._require_definition_unchanged(project_id, definition)
        if current is not None and self._same_plan_content(current, candidate):
            return MedicalWritingProtocolAssemblyPlanChangeResult(
                plan=current,
                previous_revision=current.revision,
                affected_module_ids=[],
                affected_projections=[],
            )
        return MedicalWritingProtocolAssemblyPlanChangeResult(
            plan=candidate,
            previous_revision=actual_revision,
            affected_module_ids=candidate.affected_module_ids,
            affected_projections=candidate.affected_projections,
        )

    def consumer_projection(
        self,
        project_id: str,
        projection: str,
    ) -> MedicalWritingProtocolAssemblyConsumerProjection:
        if projection not in MEDICAL_WRITING_PROTOCOL_ASSEMBLY_PROJECTIONS:
            raise MedicalWritingProtocolAssemblyPlanConflictError(
                f"unsupported protocol assembly projection: {projection}"
            )
        with self._connect() as connection:
            plan = self._current_plan(connection, project_id)
        if plan is None:
            raise KeyError(f"protocol assembly plan not found: {project_id}")
        definition = self._definition(project_id)
        source_current = self._source_matches(plan, definition)
        manifest = next(
            item for item in plan.projection_manifest if item.projection == projection
        )
        module_by_id = {item.module_id: item for item in plan.modules}
        required_module_ids = sorted(
            module_id
            for module_id in manifest.applicable_module_ids
            if module_by_id[module_id].applicability == "required"
        )
        design_driven_module_ids = sorted(
            module_id
            for module_id in manifest.applicable_module_ids
            if module_by_id[module_id].applicability == "conditional_applicable"
        )
        design_drivers = sorted(
            (
                driver
                for driver in plan.design_drivers
                if projection in driver.projection_targets
            ),
            key=lambda item: item.driver_id,
        )
        unresolved_driver_ids = sorted(
            driver.driver_id
            for driver in design_drivers
            if driver.decision_state == "unknown"
        )
        content_sha256 = medical_writing_protocol_assembly_sha256(
            {
                "projection": projection,
                "plan_sha256": plan.state_sha256,
                "manifest_sha256": manifest.content_sha256,
                "design_driver_sha256": [
                    driver.driver_sha256 for driver in design_drivers
                ],
            }
        )
        return MedicalWritingProtocolAssemblyConsumerProjection(
            projection=projection,
            project_id=project_id,
            plan_id=plan.plan_id,
            plan_revision=plan.revision,
            plan_sha256=plan.state_sha256,
            source_definition_id=plan.source_definition_id,
            source_definition_revision=plan.source_definition_revision,
            source_definition_sha256=plan.source_definition_sha256,
            source_current=source_current,
            confirmation_status=plan.confirmation_status,
            confirmation_current=(
                source_current and plan.confirmation_status == "author_confirmed"
            ),
            required_module_ids=required_module_ids,
            design_driven_module_ids=design_driven_module_ids,
            not_applicable_module_ids=manifest.not_applicable_module_ids,
            unresolved_module_ids=manifest.unresolved_module_ids,
            unresolved_driver_ids=unresolved_driver_ids,
            deterministic_projection_allowed=not (
                manifest.unresolved_module_ids or unresolved_driver_ids
            ),
            design_drivers=design_drivers,
            content_sha256=content_sha256,
        )

    def audit_history(self, project_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_protocol_assembly_plan_audit
                WHERE project_id = ?
                ORDER BY created_at, audit_id
                """,
                (project_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def dump_state(self) -> dict[str, Any]:
        return dump_sqlite_database(self.db_path)

    def load_state(
        self,
        payload: dict[str, Any],
        *,
        replace: bool = True,
    ) -> None:
        load_sqlite_database(self.db_path, payload, replace=replace)
        self._initialize()

    def refresh(
        self,
        project_id: str,
        request: MedicalWritingProtocolAssemblyPlanRefreshRequest,
    ) -> MedicalWritingProtocolAssemblyPlanChangeResult:
        operation = "protocol_assembly_plan_refresh"
        request_hash = medical_writing_protocol_assembly_sha256(
            request.model_dump(mode="json")
        )
        replay = self._lookup_idempotent_replay(
            project_id,
            operation,
            request.idempotency_key,
            request_hash,
        )
        if replay is not None:
            return replay
        definition = self._definition(project_id)
        self._require_expected_definition(definition, request)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection,
                project_id,
                operation,
                request.idempotency_key,
                request_hash,
            )
            if replay is not None:
                connection.rollback()
                return replay
            current = self._current_plan(connection, project_id)
            actual_revision = current.revision if current else 0
            if actual_revision != request.expected_plan_revision:
                raise MedicalWritingProtocolAssemblyPlanStaleError(
                    "stale protocol assembly plan revision: "
                    f"expected {request.expected_plan_revision}, actual {actual_revision}"
                )
            now = self.now_factory()
            candidate = build_protocol_assembly_plan(
                definition,
                plan_id=current.plan_id if current else _plan_id(project_id),
                revision=actual_revision + 1,
                actor=request.actor,
                now=now,
                previous=current,
            )
            if current is not None and self._same_plan_content(current, candidate):
                self._require_definition_unchanged(project_id, definition)
                result = MedicalWritingProtocolAssemblyPlanChangeResult(
                    plan=current,
                    previous_revision=current.revision,
                    affected_module_ids=[],
                    affected_projections=[],
                )
                self._insert_audit(
                    connection,
                    project_id,
                    operation,
                    request.actor,
                    request_hash,
                    result,
                    now,
                )
                self._insert_idempotency(
                    connection,
                    project_id,
                    operation,
                    request.idempotency_key,
                    request_hash,
                    result,
                    now,
                )
                connection.commit()
                return result
            self._insert_plan_revision(connection, candidate)
            self._fault("after_history_insert")
            self._set_current(connection, candidate)
            self._fault("after_current_update")
            self._require_definition_unchanged(project_id, definition)
            result = MedicalWritingProtocolAssemblyPlanChangeResult(
                plan=candidate,
                previous_revision=actual_revision,
                affected_module_ids=candidate.affected_module_ids,
                affected_projections=candidate.affected_projections,
            )
            self._insert_audit(
                connection,
                project_id,
                operation,
                request.actor,
                request_hash,
                result,
                now,
            )
            self._insert_idempotency(
                connection,
                project_id,
                operation,
                request.idempotency_key,
                request_hash,
                result,
                now,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def confirm(
        self,
        project_id: str,
        request: MedicalWritingProtocolAssemblyPlanConfirmRequest,
    ) -> MedicalWritingProtocolAssemblyPlanChangeResult:
        operation = "protocol_assembly_plan_confirm"
        request_hash = medical_writing_protocol_assembly_sha256(
            request.model_dump(mode="json")
        )
        replay = self._lookup_idempotent_replay(
            project_id,
            operation,
            request.idempotency_key,
            request_hash,
        )
        if replay is not None:
            return replay
        definition = self._definition(project_id)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_replay(
                connection,
                project_id,
                operation,
                request.idempotency_key,
                request_hash,
            )
            if replay is not None:
                connection.rollback()
                return replay
            current = self._current_plan(connection, project_id)
            if current is None:
                raise KeyError(f"protocol assembly plan not found: {project_id}")
            if current.revision != request.expected_plan_revision:
                raise MedicalWritingProtocolAssemblyPlanStaleError(
                    "stale protocol assembly plan revision: "
                    f"expected {request.expected_plan_revision}, actual {current.revision}"
                )
            if current.state_sha256 != request.expected_plan_sha256:
                raise MedicalWritingProtocolAssemblyPlanStaleError(
                    "protocol assembly plan hash changed; refresh before confirmation"
                )
            if not self._source_matches(current, definition):
                raise MedicalWritingProtocolAssemblyPlanStaleError(
                    "StudyDefinition changed; the prior plan and confirmation are not current"
                )
            blockers = [
                module.module_id
                for module in current.modules
                if not module.deterministic_projection_allowed
            ]
            if blockers:
                raise MedicalWritingProtocolAssemblyPlanBlockedError(
                    "protocol assembly plan has unresolved blockers: "
                    + ", ".join(blockers)
                )
            now = self.now_factory()
            if current.confirmation_status == "author_confirmed":
                self._require_definition_unchanged(project_id, definition)
                result = MedicalWritingProtocolAssemblyPlanChangeResult(
                    plan=current,
                    previous_revision=current.revision,
                    affected_module_ids=[],
                    affected_projections=[],
                )
                self._insert_audit(
                    connection,
                    project_id,
                    operation,
                    request.actor,
                    request_hash,
                    result,
                    now,
                )
                self._insert_idempotency(
                    connection,
                    project_id,
                    operation,
                    request.idempotency_key,
                    request_hash,
                    result,
                    now,
                )
                connection.commit()
                return result
            confirmed = self._confirmed_revision(current, request.actor, now)
            self._insert_plan_revision(connection, confirmed)
            self._fault("after_history_insert")
            self._set_current(connection, confirmed)
            self._fault("after_current_update")
            self._require_definition_unchanged(project_id, definition)
            result = MedicalWritingProtocolAssemblyPlanChangeResult(
                plan=confirmed,
                previous_revision=current.revision,
                affected_module_ids=[],
                affected_projections=[],
            )
            self._insert_audit(
                connection,
                project_id,
                operation,
                request.actor,
                request_hash,
                result,
                now,
            )
            self._insert_idempotency(
                connection,
                project_id,
                operation,
                request.idempotency_key,
                request_hash,
                result,
                now,
            )
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _definition(self, project_id: str) -> MedicalWritingStudyDefinition:
        definition = self.definition_provider(project_id)
        if definition.project_id != project_id:
            raise MedicalWritingProtocolAssemblyPlanConflictError(
                "StudyDefinition project does not match protocol assembly plan project"
            )
        return definition

    @staticmethod
    def _source_matches(
        plan: MedicalWritingProtocolAssemblyPlan,
        definition: MedicalWritingStudyDefinition,
    ) -> bool:
        return (
            plan.source_definition_id == definition.definition_id
            and plan.source_definition_revision == definition.revision
            and plan.source_definition_sha256 == definition.state_sha256
        )

    @staticmethod
    def _require_expected_definition(
        definition: MedicalWritingStudyDefinition,
        request: (
            MedicalWritingProtocolAssemblyPlanRefreshRequest
            | MedicalWritingProtocolAssemblyPlanPreviewRequest
        ),
    ) -> None:
        if (
            request.expected_source_definition_id != definition.definition_id
            or request.expected_source_definition_revision != definition.revision
            or request.expected_source_definition_sha256 != definition.state_sha256
        ):
            raise MedicalWritingProtocolAssemblyPlanStaleError(
                "StudyDefinition binding changed; refresh its id, revision, and hash"
            )

    def _require_definition_unchanged(
        self,
        project_id: str,
        expected: MedicalWritingStudyDefinition,
    ) -> None:
        latest = self._definition(project_id)
        if (
            latest.definition_id != expected.definition_id
            or latest.revision != expected.revision
            or latest.state_sha256 != expected.state_sha256
        ):
            raise MedicalWritingProtocolAssemblyPlanStaleError(
                "StudyDefinition changed during protocol assembly plan commit"
            )

    @staticmethod
    def _same_plan_content(
        current: MedicalWritingProtocolAssemblyPlan,
        candidate: MedicalWritingProtocolAssemblyPlan,
    ) -> bool:
        return (
            current.source_definition_id == candidate.source_definition_id
            and current.source_definition_revision
            == candidate.source_definition_revision
            and current.source_definition_sha256 == candidate.source_definition_sha256
            and [item.resolution_sha256 for item in current.modules]
            == [item.resolution_sha256 for item in candidate.modules]
            and [item.driver_sha256 for item in current.design_drivers]
            == [item.driver_sha256 for item in candidate.design_drivers]
            and [item.content_sha256 for item in current.projection_manifest]
            == [item.content_sha256 for item in candidate.projection_manifest]
        )

    @staticmethod
    def _confirmed_revision(
        current: MedicalWritingProtocolAssemblyPlan,
        actor: str,
        now: datetime,
    ) -> MedicalWritingProtocolAssemblyPlan:
        payload = current.model_dump(mode="json")
        payload.update(
            {
                "revision": current.revision + 1,
                "previous_plan_revision": current.revision,
                "affected_module_ids": [],
                "affected_projections": [],
                "confirmation_status": "author_confirmed",
                "updated_by": actor,
                "updated_at": now,
                "confirmed_by": actor,
                "confirmed_at": now,
            }
        )
        payload["state_sha256"] = medical_writing_protocol_assembly_sha256(
            {key: value for key, value in payload.items() if key != "state_sha256"}
        )
        return MedicalWritingProtocolAssemblyPlan.model_validate(payload)

    @staticmethod
    def _current_plan(
        connection: sqlite3.Connection,
        project_id: str,
    ) -> Optional[MedicalWritingProtocolAssemblyPlan]:
        row = connection.execute(
            """
            SELECT history.payload_json
            FROM medical_writing_protocol_assembly_plan_current AS current
            JOIN medical_writing_protocol_assembly_plan_history AS history
              ON history.project_id = current.project_id
             AND history.plan_id = current.plan_id
             AND history.revision = current.revision
            WHERE current.project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            return None
        return MedicalWritingProtocolAssemblyPlan.model_validate(
            json.loads(row["payload_json"])
        )

    @staticmethod
    def _insert_plan_revision(
        connection: sqlite3.Connection,
        plan: MedicalWritingProtocolAssemblyPlan,
    ) -> None:
        connection.execute(
            """
            INSERT INTO medical_writing_protocol_assembly_plan_history(
                project_id, plan_id, revision,
                source_definition_id, source_definition_revision,
                source_definition_sha256, state_sha256, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.project_id,
                plan.plan_id,
                plan.revision,
                plan.source_definition_id,
                plan.source_definition_revision,
                plan.source_definition_sha256,
                plan.state_sha256,
                plan.updated_at.isoformat(),
                plan.model_dump_json(),
            ),
        )

    @staticmethod
    def _set_current(
        connection: sqlite3.Connection,
        plan: MedicalWritingProtocolAssemblyPlan,
    ) -> None:
        connection.execute(
            """
            INSERT INTO medical_writing_protocol_assembly_plan_current(
                project_id, plan_id, revision,
                source_definition_id, source_definition_revision,
                source_definition_sha256, state_sha256, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                plan_id = excluded.plan_id,
                revision = excluded.revision,
                source_definition_id = excluded.source_definition_id,
                source_definition_revision = excluded.source_definition_revision,
                source_definition_sha256 = excluded.source_definition_sha256,
                state_sha256 = excluded.state_sha256,
                updated_at = excluded.updated_at
            """,
            (
                plan.project_id,
                plan.plan_id,
                plan.revision,
                plan.source_definition_id,
                plan.source_definition_revision,
                plan.source_definition_sha256,
                plan.state_sha256,
                plan.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _idempotent_replay(
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Optional[MedicalWritingProtocolAssemblyPlanChangeResult]:
        row = connection.execute(
            """
            SELECT request_sha256, result_json
            FROM medical_writing_protocol_assembly_plan_idempotency
            WHERE project_id = ? AND operation = ? AND idempotency_key = ?
            """,
            (project_id, operation, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_hash:
            raise MedicalWritingProtocolAssemblyPlanConflictError(
                "protocol assembly idempotency key reused with different content"
            )
        result = MedicalWritingProtocolAssemblyPlanChangeResult.model_validate(
            json.loads(row["result_json"])
        )
        return result.model_copy(update={"replayed": True})

    def _lookup_idempotent_replay(
        self,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> Optional[MedicalWritingProtocolAssemblyPlanChangeResult]:
        with self._connect() as connection:
            return self._idempotent_replay(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_hash,
            )

    @staticmethod
    def _insert_idempotency(
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        result: MedicalWritingProtocolAssemblyPlanChangeResult,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            INSERT INTO medical_writing_protocol_assembly_plan_idempotency(
                project_id, operation, idempotency_key,
                request_sha256, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                operation,
                idempotency_key,
                request_hash,
                result.model_dump_json(),
                now.isoformat(),
            ),
        )

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        project_id: str,
        operation: str,
        actor: str,
        request_hash: str,
        result: MedicalWritingProtocolAssemblyPlanChangeResult,
        now: datetime,
    ) -> None:
        result_hash = medical_writing_protocol_assembly_sha256(
            result.model_dump(mode="json")
        )
        audit_id = "protocol_assembly_audit_" + sha256(
            (
                f"{project_id}|{operation}|{request_hash}|"
                f"{result.plan.revision}|{result.plan.state_sha256}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        payload = {
            "audit_id": audit_id,
            "project_id": project_id,
            "operation": operation,
            "actor": actor,
            "plan_id": result.plan.plan_id,
            "plan_revision": result.plan.revision,
            "previous_revision": result.previous_revision,
            "state_sha256": result.plan.state_sha256,
            "request_sha256": request_hash,
            "result_sha256": result_hash,
            "affected_module_ids": result.affected_module_ids,
            "affected_projections": result.affected_projections,
            "created_at": now.isoformat(),
        }
        connection.execute(
            """
            INSERT INTO medical_writing_protocol_assembly_plan_audit(
                project_id, audit_id, operation, actor, plan_id,
                plan_revision, state_sha256, request_sha256,
                result_sha256, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                audit_id,
                operation,
                actor,
                result.plan.plan_id,
                result.plan.revision,
                result.plan.state_sha256,
                request_hash,
                result_hash,
                now.isoformat(),
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            ),
        )

    def _fault(self, checkpoint: str) -> None:
        if self.fault_injector is not None:
            self.fault_injector(checkpoint)
