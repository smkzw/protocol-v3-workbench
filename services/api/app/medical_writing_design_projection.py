"""Authoritative StudyDefinition design normalization for Slice A.

Consumers use :func:`normalize_study_design` instead of independently parsing
legacy prose. Decided structured facts always win. Legacy design prose and the
PICOS archetype are consulted only for a structured field that is undecided.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable

from packages.contracts.workbench_contracts import (
    MedicalWritingNormalizedDesignProjection,
    MedicalWritingNormalizedDesignProjectionWithSources,
    MedicalWritingNormalizedDesignView,
    MedicalWritingProtocolAssemblyUnresolvedQuestion,
    MedicalWritingStudyDefinition,
)


_PHASE1_BLOCKED_PROJECTIONS = [
    "synopsis",
    "sections_toc",
    "soa",
    "study_schema_flowchart",
    "evidence_intent",
    "ai_candidate_intent",
    "docx_toc",
]

_DOCUMENT_COMPLEX_DESIGN_PROJECTIONS = [
    "synopsis",
    "sections_toc",
    "evidence_intent",
    "ai_candidate_intent",
    "docx_toc",
]

_FLOW_COMPLEX_DESIGN_PROJECTIONS = [
    "synopsis",
    "sections_toc",
    "study_schema_flowchart",
    "evidence_intent",
    "ai_candidate_intent",
    "docx_toc",
]

_STRUCTURED_PATHS = {
    "randomization_mode": "framing.structured_design.randomization_mode",
    "blinding_mode": "framing.structured_design.blinding_mode",
    "comparator_type": "framing.structured_design.comparator_type",
}


def normalize_study_design(
    definition: MedicalWritingStudyDefinition,
    *,
    include_sources: bool = False,
) -> (
    MedicalWritingNormalizedDesignProjection
    | MedicalWritingNormalizedDesignProjectionWithSources
):
    """Return the single authoritative normalized design projection.

    Authority order is decided ``structured_design`` value, then a conservative
    semantic resolution of ``framing.design_pattern`` and
    ``picos.design_archetype``. Conflicting or unsupported legacy semantics stay
    ``undecided``; the normalizer never invents a design fact.
    """

    framing = definition.framing
    structured = framing.structured_design
    design_pattern = framing.design_pattern or ""
    design_archetype = definition.picos.design_archetype or ""

    randomization, randomization_source = _select_authoritative_value(
        semantic="randomization_mode",
        structured_value=structured.randomization_mode,
        design_pattern=design_pattern,
        design_archetype=design_archetype,
    )
    blinding, blinding_source = _select_authoritative_value(
        semantic="blinding_mode",
        structured_value=structured.blinding_mode,
        design_pattern=design_pattern,
        design_archetype=design_archetype,
    )
    comparator, comparator_source = _select_authoritative_value(
        semantic="comparator_type",
        structured_value=structured.comparator_type,
        design_pattern=design_pattern,
        design_archetype=design_archetype,
    )

    phase_one = _is_phase_one(framing.study_phase)
    phase1_parts = list(structured.phase1_parts) if phase_one else []
    phase1_blockers = _collect_phase1_blockers(
        framing.study_phase, phase1_parts
    )
    blockers = list(phase1_blockers)
    complex_blockers, complex_affected = _collect_complex_design_blockers(
        structured
    )
    blockers.extend(complex_blockers)
    deterministic_projection_allowed = not any(
        question.severity == "blocker" for question in blockers
    )
    affected_projections = _ordered_projection_union(
        (
            list(_PHASE1_BLOCKED_PROJECTIONS) if phase1_blockers else []
        ),
        complex_affected,
    )

    payload = {
        "source_definition_id": definition.definition_id,
        "source_definition_revision": definition.revision,
        "source_definition_sha256": definition.state_sha256,
        "design_view": MedicalWritingNormalizedDesignView(
            randomization_mode=randomization,
            blinding_mode=blinding,
            comparator_type=comparator,
            randomization_details=structured.randomization_details,
            blinded_roles=list(structured.blinded_roles),
            blinding_details=structured.blinding_details,
            comparator_intervention=structured.comparator_intervention,
            study_phase=framing.study_phase,
            phase1_parts=phase1_parts,
            phase1_sequence=structured.phase1_sequence,
            assignment_model=structured.assignment_model,
            center_model=structured.center_model,
            arm_or_cohort_kind=structured.arm_or_cohort_kind,
            arm_or_cohort_labels=list(structured.arm_or_cohort_labels),
            interim_analysis=structured.interim_analysis,
            src_planned=structured.src_planned,
            dmc_planned=structured.dmc_planned,
            treatment_switch=structured.treatment_switch,
            crossover=structured.crossover,
            open_label_extension=structured.open_label_extension,
            sample_size_reestimation=structured.sample_size_reestimation,
            adaptive_design=structured.adaptive_design,
        ),
        "blockers": blockers,
        "deterministic_projection_allowed": deterministic_projection_allowed,
        "affected_projections": affected_projections,
    }
    if not include_sources:
        return MedicalWritingNormalizedDesignProjection(**payload)

    return MedicalWritingNormalizedDesignProjectionWithSources(
        **payload,
        design_fact_paths={
            "study_phase": "framing.study_phase",
            "randomization_mode": randomization_source,
            "blinding_mode": blinding_source,
            "comparator_type": comparator_source,
            "randomization_details": (
                "framing.structured_design.randomization_details"
            ),
            "blinded_roles": "framing.structured_design.blinded_roles",
            "blinding_details": "framing.structured_design.blinding_details",
            "comparator_intervention": (
                "framing.structured_design.comparator_intervention"
            ),
            "phase1_parts": "framing.structured_design.phase1_parts",
            "phase1_sequence": "framing.structured_design.phase1_sequence",
            "assignment_model": "framing.structured_design.assignment_model",
            "center_model": "framing.structured_design.center_model",
            "arm_or_cohort_kind": (
                "framing.structured_design.arm_or_cohort_kind"
            ),
            "arm_or_cohort_labels": (
                "framing.structured_design.arm_or_cohort_labels"
            ),
            "interim_analysis": (
                "framing.structured_design.interim_analysis"
            ),
            "src_planned": "framing.structured_design.src_planned",
            "dmc_planned": "framing.structured_design.dmc_planned",
            "treatment_switch": "framing.structured_design.treatment_switch",
            "crossover": "framing.structured_design.crossover",
            "open_label_extension": (
                "framing.structured_design.open_label_extension"
            ),
            "sample_size_reestimation": (
                "framing.structured_design.sample_size_reestimation"
            ),
            "adaptive_design": "framing.structured_design.adaptive_design",
        },
    )


def _select_authoritative_value(
    *,
    semantic: str,
    structured_value: str,
    design_pattern: str,
    design_archetype: str,
) -> tuple[str, str]:
    """Select one fact without allowing legacy prose to override structure."""

    structured_path = _STRUCTURED_PATHS[semantic]
    if structured_value != "undecided":
        return structured_value, structured_path

    text_candidates = _semantic_candidates_from_design_pattern(
        semantic, design_pattern
    )
    archetype_candidate = _semantic_from_picos_archetype(
        semantic, design_archetype
    )
    combined = set(text_candidates)
    if archetype_candidate != "undecided":
        combined.add(archetype_candidate)

    if len(combined) != 1:
        return "undecided", structured_path

    resolved = next(iter(combined))
    if text_candidates:
        return resolved, "framing.design_pattern"
    return resolved, "picos.design_archetype"


def _semantic_candidates_from_design_pattern(
    semantic: str, design_pattern: str
) -> set[str]:
    """Extract only explicit, representable design semantics from prose."""

    text = (design_pattern or "").strip().lower()
    if not text:
        return set()

    if semantic == "randomization_mode":
        values: set[str] = set()
        negative_patterns = (
            r"非随机(?:化|分配)?",
            r"\bnon[-\s]?randomi[sz](?:ed|ation)\b",
        )
        scrubbed = text
        if _matches_any(scrubbed, negative_patterns):
            values.add("non_randomized")
            for pattern in negative_patterns:
                scrubbed = re.sub(pattern, " ", scrubbed)
        if _matches_any(
            scrubbed,
            (
                r"随机(?:化|分配)?",
                r"\brandomi[sz](?:ed|ation)\b",
            ),
        ):
            values.add("randomized")
        return values

    if semantic == "blinding_mode":
        patterns = {
            "open_label": (
                r"开放(?:标签|性)?(?:研究|试验)?",
                r"\bopen(?:[-\s]?label)?\b",
            ),
            "single_blind": (r"单盲", r"\bsingle[-\s]?blind(?:ed)?\b"),
            "double_blind": (r"双盲", r"\bdouble[-\s]?blind(?:ed)?\b"),
            "triple_blind": (r"三盲", r"\btriple[-\s]?blind(?:ed)?\b"),
        }
        return {
            value
            for value, value_patterns in patterns.items()
            if _matches_any(text, value_patterns)
        }

    if semantic == "comparator_type":
        patterns = {
            "placebo": (
                r"安慰剂(?:对照)?",
                r"\bplacebo[-\s]?(?:controlled|comparator|control)?\b",
            ),
            "active": (
                r"(?:阳性药|阳性对照|活性对照)",
                r"\bactive[-\s]?(?:controlled|comparator|control)\b",
            ),
            "none_or_dose_escalation": (
                r"(?:单臂|无(?:平行)?对照|剂量递增)",
                r"\b(?:single[-\s]?arm|uncontrolled|"
                r"no[-\s]?(?:parallel[-\s]?)?control(?:led)?|"
                r"dose[-\s]?escalation)\b",
            ),
        }
        return {
            value
            for value, value_patterns in patterns.items()
            if _matches_any(text, value_patterns)
        }

    raise ValueError(f"unsupported design semantic: {semantic}")


def _semantic_from_picos_archetype(
    semantic: str, design_archetype: str
) -> str:
    archetype = (design_archetype or "").strip().lower()
    if semantic == "randomization_mode":
        if archetype in {"randomized_confirmatory", "randomized_exploratory"}:
            return "randomized"
        if archetype == "single_arm_early_phase":
            return "non_randomized"
    elif semantic == "blinding_mode":
        if archetype == "open_label_extension":
            return "open_label"
    elif semantic == "comparator_type":
        if archetype == "single_arm_early_phase":
            return "none_or_dose_escalation"
    return "undecided"


def _matches_any(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _extract_randomization_from_legacy(design_pattern: str) -> str:
    """Compatibility helper used by consistency checks."""

    return _single_legacy_value("randomization_mode", design_pattern)


def _extract_blinding_from_legacy(design_pattern: str) -> str:
    """Compatibility helper used by consistency checks."""

    return _single_legacy_value("blinding_mode", design_pattern)


def _extract_comparator_from_legacy(design_pattern: str) -> str:
    """Compatibility helper used by consistency checks."""

    return _single_legacy_value("comparator_type", design_pattern)


def _single_legacy_value(semantic: str, design_pattern: str) -> str:
    values = _semantic_candidates_from_design_pattern(semantic, design_pattern)
    return next(iter(values)) if len(values) == 1 else "undecided"


def _is_phase_one(study_phase: str) -> bool:
    """Return whether a phase label explicitly includes a Phase I component."""

    if not study_phase:
        return False
    value = str(study_phase).strip()
    if not value:
        return False

    lowered = value.lower()
    first_in_human_pattern = r"first[-_\s]?in[-_\s]?human"
    if re.search(first_in_human_pattern + r"\s*=\s*false", lowered):
        return False
    if re.search(first_in_human_pattern + r"(?:\s*=\s*true)?", lowered):
        return True
    if re.search(r"\bf[\s_-]*i[\s_-]*h\b", lowered):
        return True

    compact = re.sub(r"\s+", "", value.upper())
    compact = (
        compact.replace("Ⅰ", "I")
        .replace("Ⅱ", "II")
        .replace("Ⅲ", "III")
        .replace("Ⅳ", "IV")
        .replace("／", "/")
    )
    if re.search(r"PHASE(?:I|1)(?=$|[/+\\-])", compact):
        return True
    if "一期" in compact:
        return True

    for token in re.split(r"[/+\\-]", compact):
        phase_token = token.replace("期", "")
        if phase_token in {"I", "1"}:
            return True
    return False


def _collect_phase1_blockers(
    study_phase: str,
    phase1_parts: list[Any],
) -> list[MedicalWritingProtocolAssemblyUnresolvedQuestion]:
    """Block only selected Phase I Parts missing population or cohort/dose."""

    if not _is_phase_one(study_phase):
        return []

    blockers: list[MedicalWritingProtocolAssemblyUnresolvedQuestion] = []
    for index, part in enumerate(phase1_parts):
        if not getattr(part, "unresolved", False):
            continue
        missing_required = [
            field_name
            for field_name in ("population", "cohort_dose")
            if not str(getattr(part, field_name, "") or "").strip()
        ]
        if not missing_required:
            continue

        part_code = str(getattr(part, "part_code", "") or "").strip()
        part_token = re.sub(r"[^a-zA-Z0-9_-]+", "_", part_code).strip("_")
        if not part_token:
            part_token = f"part_{index + 1}"
        prompt = (
            f"Selected Phase I Part '{part_code or part_token}' is unresolved. "
            f"Required clinical details missing: {', '.join(missing_required)}."
        )
        blockers.append(
            MedicalWritingProtocolAssemblyUnresolvedQuestion(
                question_id=f"phase1_part_{part_token}_unresolved",
                code=f"phase1_part_{part_token}_population_cohort_required",
                fact_path=f"framing.structured_design.phase1_parts[{index}]",
                prompt=prompt,
                severity="blocker",
            )
        )
    return blockers


def _ordered_projection_union(*groups: Iterable[str]) -> list[str]:
    canonical_order = _PHASE1_BLOCKED_PROJECTIONS
    selected = {item for group in groups for item in group}
    return [item for item in canonical_order if item in selected]


def _collect_complex_design_blockers(
    structured: Any,
) -> tuple[
    list[MedicalWritingProtocolAssemblyUnresolvedQuestion],
    list[str],
]:
    """Return field-level blockers only for planned typed complex designs."""

    specs = (
        (
            "treatment_switch",
            structured.treatment_switch,
            "framing.structured_design.treatment_switch",
            _PHASE1_BLOCKED_PROJECTIONS,
        ),
        (
            "crossover",
            structured.crossover,
            "framing.structured_design.crossover",
            _PHASE1_BLOCKED_PROJECTIONS,
        ),
        (
            "open_label_extension",
            structured.open_label_extension,
            "framing.structured_design.open_label_extension",
            _PHASE1_BLOCKED_PROJECTIONS,
        ),
        (
            "sample_size_reestimation",
            structured.sample_size_reestimation,
            "framing.structured_design.sample_size_reestimation",
            _DOCUMENT_COMPLEX_DESIGN_PROJECTIONS,
        ),
        (
            "adaptive_design",
            structured.adaptive_design,
            "framing.structured_design.adaptive_design",
            _FLOW_COMPLEX_DESIGN_PROJECTIONS,
        ),
    )
    questions: list[MedicalWritingProtocolAssemblyUnresolvedQuestion] = []
    affected: list[str] = []
    for semantic, design, root_path, targets in specs:
        if design.planned is not True:
            continue
        missing_fields = design.missing_required_fields()
        for field_name in missing_fields:
            questions.append(
                MedicalWritingProtocolAssemblyUnresolvedQuestion(
                    question_id=f"{semantic}_{field_name}_required",
                    code=f"{semantic}_{field_name}_required",
                    fact_path=f"{root_path}.{field_name}",
                    prompt=(
                        f"Planned {semantic.replace('_', ' ')} requires "
                        f"'{field_name}' before deterministic projection."
                    ),
                    severity="blocker",
                )
            )
        if missing_fields:
            affected.extend(targets)
    return questions, _ordered_projection_union(affected)
