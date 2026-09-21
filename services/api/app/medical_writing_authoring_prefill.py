"""Deterministic AI-first authoring prefill package generator.

The production boundary accepts an injectable ranking adapter. Default behavior is
fully offline and testable from StudyDefinition + registry search facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Callable, Protocol

from packages.contracts.workbench_contracts import (
    AuthoringPrefillCandidate,
    AuthoringPrefillEvidenceRef,
    AuthoringPrefillFieldCandidates,
    AuthoringPrefillPackage,
    AuthoringPrefillProgress,
    MedicalWritingAuthoringJourney,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
)


PREFILL_PROMPT_VERSION = "authoring_prefill_v1"
PREFILL_MODEL_NAME = "deterministic_registry_prefill"

# Writable StudyDefinition field paths for this slice.
# Non-exact PICOS fields are included for full field-level coverage. Exact
# clinical facts (dose/endpoint/AESI/sample-size/washout) remain protected in
# EXACT_FACT_PATHS and are NOT listed here — they cannot be adopted as ready
# facts without registered evidence.
SUPPORTED_STUDY_DEFINITION_PATHS: frozenset[str] = frozenset(
    {
        "framing.protocol_id",
        "framing.version",
        "framing.document_title",
        "framing.indication",
        "framing.clinicaltrials_condition_term",
        "framing.study_phase",
        "framing.investigational_product",
        "framing.target_mechanism",
        "framing.competitor_target_scope",
        "framing.product_profile.technology_type",
        "framing.product_profile.administration_routes",
        "framing.product_profile.dosage_forms",
        "framing.product_profile.exposure_scope",
        "framing.design_pattern",
        "framing.population_intent",
        "framing.intrinsic_objectives",
        "framing.development_regions",
        "picos.design_archetype",
        # Population
        "picos.population_summary",
        "picos.inclusion_modules",
        "picos.exclusion_modules",
        # Intervention (non-exact)
        "picos.intervention_summary",
        "picos.required_background_rules",
        "picos.allowed_concomitant_rules",
        "picos.prohibited_concomitant_rules",
        "picos.assessment_timing_restrictions",
        "picos.comparator_summary",
        # Outcomes (non-exact)
        "picos.primary_objectives",
        "picos.secondary_objectives",
        "picos.exploratory_objectives",
        "picos.key_secondary_endpoints",
        "picos.other_secondary_endpoints",
        "picos.exploratory_endpoints",
        "picos.safety_endpoints",
        # Execution / statistics (non-exact)
        "picos.study_epochs",
        "picos.visit_strategy",
        "picos.estimand_strategy",
        "picos.statistical_strategy",
    }
)

# Orthogonal design proposal paths (adopt maps into StudyDefinition).
SUPPORTED_DESIGN_PROPOSAL_PATHS: frozenset[str] = frozenset(
    {
        "design.randomization",
        "design.blinding",
        "design.comparator_type",
        "design.assignment_model",
        "design.center_model",
        "design.adaptive_design",
        "design.src_dmc",
        "design.interim_analysis",
        "design.phase1_parts",
        "design.arms_or_cohorts",
        "design.crossover",
        "design.open_label_extension",
        "design.sample_size_reestimation",
        "design.treatment_switch",
    }
)

SUPPORTED_ADOPT_PATHS = SUPPORTED_STUDY_DEFINITION_PATHS | SUPPORTED_DESIGN_PROPOSAL_PATHS

# Exact clinical facts that must not be invented without evidence.
EXACT_FACT_PATHS: frozenset[str] = frozenset(
    {
        "picos.intervention_dose_regimen",
        "picos.primary_endpoint",
        "picos.aesi_definitions",
        "picos.sample_size_strategy",
        "picos.washout_rules",
    }
)


class PrefillRankingAdapter(Protocol):
    def rank_and_phrase(
        self,
        *,
        field_path: str,
        candidates: list[AuthoringPrefillCandidate],
        context: dict[str, Any],
    ) -> list[AuthoringPrefillCandidate]:
        """Optional production AI boundary. Must preserve evidence and field_path."""


class PassthroughPrefillAdapter:
    def rank_and_phrase(
        self,
        *,
        field_path: str,
        candidates: list[AuthoringPrefillCandidate],
        context: dict[str, Any],
    ) -> list[AuthoringPrefillCandidate]:
        return candidates


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def canonicalize_candidate_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip().lower()
        text = re.sub(r"[\s\u3000]+", "", text)
        text = re.sub(r"[，。、“”\"'：:；;！!？?\-—_.,()（）\[\]【】]", "", text)
        return text
    if isinstance(value, list):
        return "|".join(canonicalize_candidate_value(item) for item in value)
    if isinstance(value, dict):
        return payload_sha256(value)
    return canonicalize_candidate_value(str(value))


def values_materially_distinct(left: Any, right: Any) -> bool:
    return canonicalize_candidate_value(left) != canonicalize_candidate_value(right)


def dedupe_materially_distinct(
    candidates: list[AuthoringPrefillCandidate],
    *,
    max_alternatives: int = 4,
) -> list[AuthoringPrefillCandidate]:
    if not candidates:
        return []
    kept: list[AuthoringPrefillCandidate] = []
    for candidate in candidates:
        if any(
            not values_materially_distinct(candidate.structured_value, existing.structured_value)
            for existing in kept
        ):
            continue
        kept.append(candidate)
        if len(kept) > max_alternatives:  # 1 recommended + 4 alts
            break
    return kept[: max_alternatives + 1]


def journey_input_fingerprint(state: MedicalWritingAuthoringJourney) -> str:
    definition = state.study_definition
    framing, picos = effective_authoring_values(state)
    fingerprint_payload: dict[str, Any] = {
        "framing": framing.model_dump(mode="json"),
        "picos": picos.model_dump(mode="json"),
        "study_definition_revision": definition.revision if definition else 0,
        "study_definition_state_sha256": definition.state_sha256 if definition else "",
        "search_snapshot_id": (
            state.search_plan.latest_snapshot_id if state.search_plan else ""
        ),
        "corpus_source_hash": state.corpus_gate.source_state_hash or "",
    }
    # Round-1 corpus-analysis identity bound to the journey: a new or
    # re-run analysis (analysis id / output hash / frozen AI route drift)
    # must make packages generated under the old analysis stale.  Unbound
    # journeys keep the legacy fingerprint byte-identical.
    from .medical_writing_authoring_prefill_corpus_bridge import (
        bound_round1_analysis_identity,
    )

    identity = bound_round1_analysis_identity(state)
    if identity is not None:
        fingerprint_payload["round1_corpus_analysis"] = {
            "analysis_id": identity["analysis_id"],
            "output_hash": identity["output_hash"],
            "ai_route_identity_hash": str(
                identity["ai_route"].get("identity_hash", "")
            ).lower(),
            "pipeline_id": identity["pipeline_id"],
            "snapshot_id": identity["snapshot_id"],
        }
    return payload_sha256(fingerprint_payload)


def effective_authoring_values(
    state: MedicalWritingAuthoringJourney,
) -> tuple[Any, Any]:
    """Return the values the medical writer currently sees and edits.

    A confirmed synopsis can populate stage drafts before every required field
    is resolved. Those drafts are the active authoring surface and must drive
    prefill generation, fingerprints, and candidate adoption.
    """
    framing_draft = getattr(state, "framing_draft", None)
    picos_draft = getattr(state, "picos_draft", None)
    draft_framing = getattr(framing_draft, "framing", None)
    draft_picos = getattr(picos_draft, "picos", None)
    framing = (
        draft_framing
        if draft_framing is not None
        else state.framing
    )
    picos = (
        draft_picos
        if draft_picos is not None
        else state.picos
    )
    return framing, picos


def search_fingerprint(
    state: MedicalWritingAuthoringJourney,
    snapshot: WritingReferenceSearchSnapshot | None,
) -> str:
    return payload_sha256(
        {
            "plan_id": state.search_plan.plan_id if state.search_plan else "",
            "snapshot_id": (
                snapshot.snapshot_id
                if snapshot is not None
                else (state.search_plan.latest_snapshot_id if state.search_plan else "")
            ),
            "returned_count": (
                snapshot.returned_count
                if snapshot is not None
                else (state.search_plan.returned_count if state.search_plan else 0)
            ),
        }
    )


def package_is_stale(
    package: AuthoringPrefillPackage,
    state: MedicalWritingAuthoringJourney,
    snapshot: WritingReferenceSearchSnapshot | None = None,
) -> bool:
    if package.status == "stale":
        return True
    current_input = journey_input_fingerprint(state)
    current_search = search_fingerprint(state, snapshot)
    corpus_hash = state.corpus_gate.source_state_hash or ""
    return (
        package.input_fingerprint != current_input
        or package.search_fingerprint != current_search
        or package.corpus_fingerprint != corpus_hash
    )


def _evidence(
    *,
    source_kind: str,
    source_id: str,
    source_text: str,
    locator: str = "",
) -> AuthoringPrefillEvidenceRef:
    return AuthoringPrefillEvidenceRef(
        source_kind=source_kind,  # type: ignore[arg-type]
        source_id=source_id,
        locator=locator,
        source_text=source_text,
    )


def _candidate(
    *,
    field_path: str,
    value: Any,
    preview: str,
    rationale: str,
    evidence: list[AuthoringPrefillEvidenceRef],
    limitations: list[str] | None = None,
    confidence: str = "medium",
    suffix: str,
    recommendation_role: str = "recommended",
    adoption_mode: str = "manual_only",
    clinical_tradeoffs: list[str] | None = None,
    evidence_gaps: list[str] | None = None,
) -> AuthoringPrefillCandidate:
    digest = payload_sha256(
        {"field_path": field_path, "value": value, "suffix": suffix}
    )[:16]
    return AuthoringPrefillCandidate(
        candidate_id=f"mwprefillcand_{digest}",
        field_path=field_path,
        structured_value=value,
        preview=preview or str(value),
        evidence_refs=evidence,
        rationale=rationale,
        limitations=limitations or [],
        confidence=confidence,  # type: ignore[arg-type]
        state="ai_proposed",
        recommendation_role=recommendation_role,  # type: ignore[arg-type]
        adoption_mode=adoption_mode,  # type: ignore[arg-type]
        clinical_tradeoffs=clinical_tradeoffs or [],
        evidence_gaps=evidence_gaps or [],
    )


def _module_candidate(
    *,
    field_path: str,
    target_paths: list[str],
    structured_value: dict[str, Any],
    preview: str,
    rationale: str,
    evidence: list[AuthoringPrefillEvidenceRef],
    limitations: list[str] | None = None,
    confidence: str = "low",
    suffix: str,
    recommendation_role: str = "recommended",
    adoption_mode: str = "manual_only",
    clinical_tradeoffs: list[str] | None = None,
    evidence_gaps: list[str] | None = None,
) -> AuthoringPrefillCandidate:
    """Build a module-scope composite candidate with target_paths."""
    digest = payload_sha256(
        {
            "field_path": field_path,
            "target_paths": sorted(target_paths),
            "structured_value": structured_value,
            "suffix": suffix,
        }
    )[:16]
    return AuthoringPrefillCandidate(
        candidate_id=f"mwprefillcand_{digest}",
        field_path=field_path,
        candidate_scope="module",
        target_paths=sorted(target_paths),
        structured_value=structured_value,
        preview=preview or str(structured_value),
        evidence_refs=evidence,
        rationale=rationale,
        limitations=limitations or [],
        confidence=confidence,  # type: ignore[arg-type]
        state="ai_proposed",
        recommendation_role=recommendation_role,  # type: ignore[arg-type]
        adoption_mode=adoption_mode,  # type: ignore[arg-type]
        clinical_tradeoffs=clinical_tradeoffs or [],
        evidence_gaps=evidence_gaps or [],
    )


def _candidate_is_pending_like(candidate: AuthoringPrefillCandidate) -> bool:
    """True when a card must never be auto-labeled as the recommended pick."""
    role = str(candidate.recommendation_role or "").strip()
    if role == "pending_decision":
        return True
    if _preview_looks_pending(str(candidate.preview or "")):
        return True
    value = candidate.structured_value
    if value in ("", None, {}, []):
        return True
    if isinstance(value, dict):
        # Empty orthogonal design shells (mode/type/model blank) are undecided.
        for key in ("mode", "type", "model", "kind"):
            if key in value and not str(value.get(key) or "").strip():
                return True
    return False


def _field_group(
    field_path: str,
    candidates: list[AuthoringPrefillCandidate],
    adapter: PrefillRankingAdapter,
    context: dict[str, Any],
) -> AuthoringPrefillFieldCandidates | None:
    ranked = adapter.rank_and_phrase(
        field_path=field_path, candidates=candidates, context=context
    )
    for item in ranked:
        if item.field_path != field_path:
            raise ValueError("prefill adapter altered field_path")
        for ref in item.evidence_refs:
            AuthoringPrefillEvidenceRef.model_validate(ref.model_dump(mode="json"))
    distinct = dedupe_materially_distinct(ranked, max_alternatives=4)
    if not distinct:
        return None
    return AuthoringPrefillFieldCandidates(
        field_path=field_path,
        recommended_candidate_id=distinct[0].candidate_id,
        candidates=distinct,
    )


def _phase_bucket(study_phase: str) -> str:
    value = (study_phase or "").upper().replace(" ", "")
    if "I/II" in value or "1/2" in value:
        return "phase1_2"
    if "II/III" in value or "2/3" in value:
        return "phase2_3"
    if "III" in value or "3" in value:
        return "phase3"
    if "II" in value or "2" in value:
        return "phase2"
    if "I" in value or "1" in value or "EARLY" in value or "早期" in study_phase:
        return "phase1"
    return "other"


def _evidence_pct_rationale(label: str, count: int, total: int) -> str:
    """Format competitor corpus coverage as a Chinese clinical rationale fragment."""
    total_n = max(0, int(total))
    count_n = max(0, min(int(count), total_n)) if total_n else 0
    if total_n <= 0:
        return ""
    pct = int(round(100.0 * count_n / total_n))
    return f"已准入竞品方案中 {pct}%（{count_n}/{total_n}）采用{label}"


def _clinical_default_rationale(phase: str, label: str, *, evidence_note: str = "") -> str:
    phase_label = phase or "当前分期"
    if evidence_note:
        return f"{evidence_note}；据此推荐{label}。"
    return f"当前语料样本不足，按{phase_label}常见实践默认推荐{label}。"


def _registry_design_facet_counts(
    candidates: list[WritingReferenceTrialCandidate],
) -> dict[str, dict[str, int]]:
    """Count coarse design facets from registry candidate metadata."""
    totals = {
        "blinding": {"double": 0, "single": 0, "open": 0, "total": 0},
        "comparator": {"placebo": 0, "active": 0, "none": 0, "total": 0},
        "allocation": {"randomized": 0, "non_randomized": 0, "total": 0},
        "assignment": {"parallel": 0, "crossover": 0, "sequential": 0, "total": 0},
        "center": {"multi": 0, "single": 0, "total": 0},
    }
    for item in candidates:
        masking = str(getattr(item, "design_masking", "") or "").lower()
        allocation = str(getattr(item, "design_allocation", "") or "").lower()
        model = str(getattr(item, "design_intervention_model", "") or "").lower()
        title = (
            str(getattr(item, "official_title", "") or "")
            + " "
            + str(getattr(item, "brief_title", "") or "")
        ).lower()
        blob = f"{masking} {allocation} {model} {title}"

        if masking or "blind" in blob or "开放" in title or "open-label" in blob:
            totals["blinding"]["total"] += 1
            if "double" in masking or "双盲" in title or "triple" in masking:
                totals["blinding"]["double"] += 1
            elif "single" in masking or "单盲" in title:
                totals["blinding"]["single"] += 1
            elif "open" in masking or "开放" in title or "open-label" in blob:
                totals["blinding"]["open"] += 1
            else:
                totals["blinding"]["double"] += 1  # conservative confirmatory lean

        totals["allocation"]["total"] += 1
        if "non" in allocation or "非随机" in title:
            totals["allocation"]["non_randomized"] += 1
        elif "random" in allocation or "随机" in title or not allocation:
            totals["allocation"]["randomized"] += 1
        else:
            totals["allocation"]["non_randomized"] += 1

        totals["assignment"]["total"] += 1
        if "cross" in model or "交叉" in title:
            totals["assignment"]["crossover"] += 1
        elif "sequential" in model or "剂量递增" in title or "dose" in model:
            totals["assignment"]["sequential"] += 1
        else:
            totals["assignment"]["parallel"] += 1

        totals["comparator"]["total"] += 1
        if "placebo" in blob or "安慰剂" in title:
            totals["comparator"]["placebo"] += 1
        elif "active" in blob or "阳性" in title or "对照药" in title:
            totals["comparator"]["active"] += 1
        elif "single arm" in blob or "单臂" in title or "dose escalation" in blob:
            totals["comparator"]["none"] += 1
        else:
            # Unknown — do not inflate placebo; leave unclassified toward none/active later
            pass

        totals["center"]["total"] += 1
        if "single-center" in blob or "single centre" in blob or "单中心" in title:
            totals["center"]["single"] += 1
        else:
            totals["center"]["multi"] += 1
    return totals


_PENDING_PREVIEW_RE = re.compile(
    r"待确认|具体标准待确认|具体阈值待确认|设计待定|尚未确认|pending_decision"
)


def _preview_looks_pending(preview: str) -> bool:
    text = str(preview or "").strip()
    if not text:
        return True
    if "待确认" in text or "设计待定" in text:
        return True
    return bool(_PENDING_PREVIEW_RE.search(text))


def _rewrite_pending_wording(text: str) -> str:
    """Replace banned「待确认」shell wording with actionable Chinese defaults."""
    value = str(text or "")
    if not value:
        return value
    replacements = (
        ("研究方案设计待确认", "研究方案设计（按分期常见实践预填，请复核）"),
        ("具体设计待确认", "具体设计按分期常见实践预填"),
        ("设计待定：请先确认随机化、盲法、对照等正交设计维度", "请复核随机化、盲法、对照等正交设计维度"),
        ("待确认", "待复核"),
    )
    for old, new in replacements:
        if old in value:
            value = value.replace(old, new)
    return value


def _strip_pending_recommended_candidates(
    field_candidates: dict[str, AuthoringPrefillFieldCandidates],
) -> dict[str, AuthoringPrefillFieldCandidates]:
    """Ban「待确认」/pending_decision as recommended default; rewrite option text."""
    updated: dict[str, AuthoringPrefillFieldCandidates] = {}
    for path, group in field_candidates.items():
        candidates = list(group.candidates or [])
        if not candidates:
            updated[path] = group
            continue
        rewritten: list[AuthoringPrefillCandidate] = []
        for item in candidates:
            role = str(item.recommendation_role or "")
            preview = str(item.preview or "")
            structured = item.structured_value
            updates: dict[str, Any] = {}
            if "待确认" in preview or "设计待定" in preview:
                updates["preview"] = _rewrite_pending_wording(preview)
            if isinstance(structured, str) and (
                "待确认" in structured or "设计待定" in structured
            ):
                updates["structured_value"] = _rewrite_pending_wording(structured)
            # Never keep pending_decision / pending-looking cards as recommended.
            if role == "recommended" and (
                role == "pending_decision"
                or _preview_looks_pending(updates.get("preview", preview))
                or _candidate_is_pending_like(item)
            ):
                updates["recommendation_role"] = "alternative"
                updates["adoption_mode"] = "manual_only"
            if role == "pending_decision":
                updates["recommendation_role"] = "alternative"
                updates["adoption_mode"] = "manual_only"
            rewritten.append(
                item.model_copy(update=updates) if updates else item
            )
        preferred = next(
            (
                c
                for c in rewritten
                if c.recommendation_role == "recommended"
                and not _preview_looks_pending(c.preview)
                and not _candidate_is_pending_like(c)
            ),
            None,
        )
        if preferred is None:
            preferred = next(
                (
                    c
                    for c in rewritten
                    if not _candidate_is_pending_like(c)
                    and not _preview_looks_pending(c.preview)
                ),
                None,
            )
            if preferred is not None:
                normalized: list[AuthoringPrefillCandidate] = []
                for c in rewritten:
                    if c.candidate_id == preferred.candidate_id:
                        normalized.append(
                            c.model_copy(update={"recommendation_role": "recommended"})
                        )
                    elif c.recommendation_role == "recommended":
                        normalized.append(
                            c.model_copy(update={"recommendation_role": "alternative"})
                        )
                    else:
                        normalized.append(c)
                rewritten = normalized
        updated[path] = group.model_copy(
            update={
                "candidates": rewritten,
                "recommended_candidate_id": (
                    preferred.candidate_id if preferred is not None else ""
                ),
            }
        )
    return updated


def select_safe_recommended_candidate_id(
    candidates: list[AuthoringPrefillCandidate],
    *,
    is_disqualified: Callable[[AuthoringPrefillCandidate], bool] | None = None,
) -> str:
    """Return the first candidate that may occupy the recommended slot.

    The recommended slot never points at a pending/manual placeholder card
    (``pending_decision`` role, ``manual_only`` adoption mode, pending-
    looking preview, empty/undecided value) and never at a candidate the
    caller disqualifies (e.g. one carrying an unsupported-substantive
    evidence gap).  Every candidate's role is preserved — nothing is
    promoted or demoted, so a pending candidate keeps ``pending_decision``.
    Returns "" when no candidate is safe: the group keeps all candidates
    but has no recommendation.

    Worker_03 corrective: ``manual_only`` candidates are excluded from
    safe recommendation selection — they require explicit medical-manager
    confirmation and must never be auto-labeled as the recommended pick
    (matching the corrective contract wording "non-pending, non-manual").
    """
    for candidate in candidates:
        if _candidate_is_pending_like(candidate):
            continue
        if str(candidate.adoption_mode or "").strip() == "manual_only":
            continue
        if is_disqualified is not None and is_disqualified(candidate):
            continue
        return candidate.candidate_id
    return ""


_DETERMINISTIC_DESIGN_PENDING_VALUES: dict[str, Any] = {
    # The prose design description is itself a clinical design conclusion;
    # phase-only heuristics must not receive the same one-click mode as an
    # evidence-bound project fact.
    "framing.design_pattern": "",
    "picos.design_archetype": "",
    "design.randomization": {"mode": ""},
    "design.blinding": {"mode": "", "blinded_roles": []},
    "design.comparator_type": {"type": "", "intervention": ""},
    "design.assignment_model": {"model": ""},
    "design.center_model": {"model": ""},
    "design.adaptive_design": {"enabled": False, "features": []},
    "design.src_dmc": {"src": False, "dmc": False},
    "design.interim_analysis": {"planned": False, "purpose": ""},
    "design.arms_or_cohorts": {"kind": "", "labels": []},
}

_DETERMINISTIC_DESIGN_PENDING_LABELS: dict[str, str] = {
    "framing.design_pattern": "待独立AI基于语料生成研究设计描述",
    "picos.design_archetype": "待选择研究设计类型",
    "design.randomization": "待确认是否随机及随机化方式",
    "design.blinding": "待确认盲法",
    "design.comparator_type": "待确认对照类型",
    "design.assignment_model": "待确认分配模型",
    "design.center_model": "待确认中心模型",
    "design.adaptive_design": "待确认是否启用适应性设计",
    "design.src_dmc": "待确认SRC/DMC设置",
    "design.interim_analysis": "待确认是否计划期中分析",
    "design.arms_or_cohorts": "待确认臂/队列结构",
}


def _pending_candidate_from_group(
    group: AuthoringPrefillFieldCandidates,
    *,
    structured_value: Any,
    preview: str,
    rationale: str,
) -> AuthoringPrefillFieldCandidates:
    """Turn a deterministic group into a non-adoptable decision scaffold."""
    first = group.candidates[0]
    limitations = list(first.limitations or [])
    non_adoptable = "确定性预填不构成可采用的临床设计结论；须由医学经理确认。"
    if non_adoptable not in limitations:
        limitations.append(non_adoptable)
    pending = first.model_copy(
        update={
            "structured_value": structured_value,
            "preview": preview,
            "rationale": rationale,
            "limitations": limitations,
            "confidence": "none",
            "recommendation_role": "pending_decision",
            "adoption_mode": "manual_only",
            "evidence_status": "insufficient",
            "evidence_catalog_id": "",
            "evidence_catalog_sha256": "",
            "claim_bindings": [],
        },
        deep=True,
    )
    # Unbound deterministic alternatives are not recommendations. Retaining
    # their concrete values would leak phase/indication heuristics into the
    # project as if they were evidence-derived choices. The independent AI may
    # later add 3-5 materially distinct, catalog-bound candidates.
    #
    # Corrective round 4: every deterministic pending/manual-only scaffold
    # group keeps its visible candidate but has an EMPTY recommended slot —
    # nothing pending is ever pointed to as a recommendation (the contract
    # allows an empty recommended id for a non-empty group).
    return group.model_copy(
        update={
            "recommended_candidate_id": "",
            "candidates": [pending],
        },
        deep=True,
    )


def _safe_package_value(field_path: str, target_paths: list[str]) -> dict[str, Any]:
    """Return an identity-only module shell that contains no inferred facts."""
    list_paths = {
        "picos.inclusion_modules",
        "picos.exclusion_modules",
        "picos.washout_rules",
        "picos.required_background_rules",
        "picos.allowed_concomitant_rules",
        "picos.prohibited_concomitant_rules",
        "picos.assessment_timing_restrictions",
        "picos.primary_objectives",
        "picos.secondary_objectives",
        "picos.exploratory_objectives",
        "picos.key_secondary_endpoints",
        "picos.other_secondary_endpoints",
        "picos.exploratory_endpoints",
        "picos.safety_endpoints",
        "picos.aesi_definitions",
        "picos.assessment_instruments",
        "picos.study_epochs",
        "framing.product_profile.administration_routes",
        "framing.product_profile.dosage_forms",
    }
    value: dict[str, Any] = {}
    for path in target_paths:
        if path in list_paths:
            value[path] = []
        elif path == "design.phase1_parts":
            value[path] = {
                "parts": [],
                "sequence": "",
                "available_part_types": [
                    "SAD",
                    "MAD",
                    "首次患者",
                    "食物影响",
                    "物质平衡",
                    "肝损伤",
                    "肾损伤",
                    "DDI",
                ],
            }
        elif path in _DETERMINISTIC_DESIGN_PENDING_VALUES:
            value[path] = _DETERMINISTIC_DESIGN_PENDING_VALUES[path]
        elif path.startswith("design."):
            value[path] = {"planned": False}
        else:
            value[path] = ""
    return value


def _enforce_deterministic_prefill_safety(
    field_candidates: dict[str, AuthoringPrefillFieldCandidates],
) -> dict[str, AuthoringPrefillFieldCandidates]:
    """Keep AI-first UX without turning deterministic heuristics into facts.

    Evidence-bound AI enrichment may replace these scaffolds later. When AI or
    corpus preparation is unavailable, every design and module package remains
    explicitly pending and manual-only.
    """
    updated = dict(field_candidates)

    for path, pending_value in _DETERMINISTIC_DESIGN_PENDING_VALUES.items():
        group = updated.get(path)
        if group is None:
            continue
        updated[path] = _pending_candidate_from_group(
            group,
            structured_value=pending_value,
            preview=_DETERMINISTIC_DESIGN_PENDING_LABELS[path],
            rationale="该字段需结合已准入竞品方案、项目资料和独立AI分析后形成推荐。",
        )

    phase1_group = updated.get("design.phase1_parts")
    if phase1_group is not None:
        catalog = [
            "SAD",
            "MAD",
            "首次患者",
            "食物影响",
            "物质平衡",
            "肝损伤",
            "肾损伤",
            "DDI",
        ]
        safe_group = _pending_candidate_from_group(
            phase1_group,
            structured_value={
                "parts": [],
                "sequence": "",
                "available_part_types": catalog,
            },
            preview="待确认I期Part组合",
            rationale="I期Part组合需结合药物类型、给药途径、既往暴露和研究目的确定。",
        )
        sad_mad_source = phase1_group.candidates[0]
        sad_mad = sad_mad_source.model_copy(
            update={
                "candidate_id": f"{sad_mad_source.candidate_id}_safe_alt",
                "structured_value": {
                    "parts": [{"part_code": "SAD"}, {"part_code": "MAD"}],
                    "sequence": "sequential",
                },
                "preview": "SAD + MAD（备选组合）",
                "rationale": "常见I期Part组合备选；仅供用户选择，不代表当前研究已确定。",
                "confidence": "none",
                "recommendation_role": "alternative",
                "adoption_mode": "manual_only",
                "limitations": [
                    "该组合仅含Part代码，不包含人群、剂量、PK/PD或停止规则结论。"
                ],
                "evidence_status": "insufficient",
                "evidence_catalog_id": "",
                "evidence_catalog_sha256": "",
                "claim_bindings": [],
            },
            deep=True,
        )
        sanitized: list[AuthoringPrefillCandidate] = [
            safe_group.candidates[0],
            sad_mad,
        ]
        for item in safe_group.candidates[1:]:
            structured = item.structured_value
            if isinstance(structured, dict):
                parts = structured.get("parts") or []
                structured = {
                    "parts": [
                        {"part_code": str(part.get("part_code") or "").strip()}
                        for part in parts
                        if isinstance(part, dict) and str(part.get("part_code") or "").strip()
                    ],
                    "sequence": str(structured.get("sequence") or ""),
                }
            sanitized.append(
                item.model_copy(update={"structured_value": structured}, deep=True)
            )
        updated["design.phase1_parts"] = safe_group.model_copy(
            update={"candidates": sanitized[:5]}, deep=True
        )

    for path, preview in (
        ("framing.product_profile.technology_type", "待确认药物技术类型"),
        ("framing.product_profile.administration_routes", "待确认给药途径"),
        ("framing.target_mechanism", "待确认靶点/作用机制"),
        ("framing.population_intent", "待确认目标人群设计"),
    ):
        group = updated.get(path)
        if group is None:
            continue
        pending_value: Any = [] if path.endswith("administration_routes") else ""
        updated[path] = _pending_candidate_from_group(
            group,
            structured_value=pending_value,
            preview=preview,
            rationale="该信息不能仅凭药物代号、适应症或分期推断，需由项目资料或用户确认。",
        )

    for path, group in list(updated.items()):
        if not path.startswith("package."):
            continue
        target_paths = list(group.candidates[0].target_paths or [])
        safe_group = _pending_candidate_from_group(
            group,
            structured_value=_safe_package_value(path, target_paths),
            preview=f"{path.removeprefix('package.')}模块待AI基于语料生成",
            rationale="模块结构已准备；待语料准入和独立AI完成证据绑定后生成3–5个候选包。",
        )
        updated[path] = safe_group.model_copy(
            update={
                "candidates": [safe_group.candidates[0]]
            },
            deep=True,
        )
    return updated


def _registry_design_hints(
    candidates: list[WritingReferenceTrialCandidate],
) -> list[str]:
    titles: list[str] = []
    for item in candidates:
        title = (item.official_title or item.brief_title or "").strip()
        if title:
            titles.append(title)
    return titles[:8]


def _count_adoptable_and_pending_fields(
    field_candidates: dict[str, AuthoringPrefillFieldCandidates],
) -> tuple[int, int]:
    """Count directly-adoptable and pending/blocked fields.

    A group whose recommended slot is empty (corrective round 2: every
    visible candidate is pending, manual-only, or otherwise unsafe) has no
    effective recommendation and counts as pending/blocked; a group whose
    recommended candidate carries the pending_decision role likewise.
    """
    directly_adoptable = 0
    pending_fields = 0
    for group in field_candidates.values():
        if not group.recommended_candidate_id:
            if group.candidates:
                pending_fields += 1
            continue
        rec = next(
            (
                c for c in group.candidates
                if c.candidate_id == group.recommended_candidate_id
            ),
            None,
        )
        if rec is None:
            continue
        if rec.recommendation_role == "pending_decision":
            pending_fields += 1
        else:
            directly_adoptable += 1
    return directly_adoptable, pending_fields


def generate_prefill_package(
    *,
    state: MedicalWritingAuthoringJourney,
    now: datetime,
    actor: str = "system",
    snapshot: WritingReferenceSearchSnapshot | None = None,
    adapter: PrefillRankingAdapter | None = None,
) -> AuthoringPrefillPackage:
    adapter = adapter or PassthroughPrefillAdapter()
    framing, _ = effective_authoring_values(state)
    definition = state.study_definition
    product = framing.investigational_product.strip()
    indication = framing.indication.strip()
    phase = framing.study_phase.strip()
    condition = framing.clinicaltrials_condition_term.strip() or indication
    registry_candidates = list(snapshot.candidates) if snapshot is not None else []
    title_hints = _registry_design_hints(registry_candidates)
    phase_bucket = _phase_bucket(phase)
    facet_counts = _registry_design_facet_counts(registry_candidates)
    partial_failures: list[str] = []
    if state.search_plan and state.search_plan.latest_snapshot_id and snapshot is None:
        partial_failures.append(
            "search_snapshot_unavailable: package built without live registry rows"
        )

    context = {
        "product": product,
        "indication": indication,
        "phase": phase,
        "phase_bucket": phase_bucket,
        "condition": condition,
        "title_hints": title_hints,
    }
    field_candidates: dict[str, AuthoringPrefillFieldCandidates] = {}

    def add(field_path: str, candidates: list[AuthoringPrefillCandidate]) -> None:
        group = _field_group(field_path, candidates, adapter, context)
        if group is not None:
            field_candidates[field_path] = group

    # Identity suggestions from creation minimum.
    if product and indication and phase:
        protocol_seed = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff\-]+", "-", product).strip("-")
        add(
            "framing.protocol_id",
            [
                _candidate(
                    field_path="framing.protocol_id",
                    value=f"{protocol_seed}-001"[:80] or "PROTOCOL-001",
                    preview=f"{protocol_seed}-001"[:80] or "PROTOCOL-001",
                    rationale="基于试验药物代号生成可编辑的方案编号建议。",
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.investigational_product",
                            source_text=product,
                            locator="framing.investigational_product",
                        )
                    ],
                    confidence="low",
                    limitations=["方案编号需医学经理按公司命名规范确认。"],
                    suffix="protocol-primary",
                ),
                _candidate(
                    field_path="framing.protocol_id",
                    value=f"{protocol_seed}-{phase_bucket.upper()}"[:80],
                    preview=f"{protocol_seed}-{phase_bucket.upper()}"[:80],
                    rationale="按分期区分的备选方案编号。",
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.study_phase",
                            source_text=phase,
                            locator="framing.study_phase",
                        )
                    ],
                    confidence="low",
                    limitations=["仅为命名候选，不是注册编号。"],
                    suffix="protocol-phase",
                ),
            ],
        )
        title_primary = f"{product}治疗{indication}的{phase}临床研究方案"
        # Title alternatives must only rephrase naming/wording — they must NOT
        # inject unconfirmed design facts (randomized, controlled, adult,
        # double-blind, multicenter, etc.). Phase alone does not prove any
        # design decision.
        title_alts = [
            f"{product}用于{indication}的{phase}研究方案",
            f"{product}（{indication}）{phase}方案",
        ]
        title_candidates = [
            _candidate(
                field_path="framing.document_title",
                value=title_primary,
                preview=title_primary,
                rationale="由试验药物、适应症与分期确定性组合生成标题建议。",
                evidence=[
                    _evidence(
                        source_kind="study_definition",
                        source_id="creation_minimum",
                        source_text=f"{product}|{indication}|{phase}",
                        locator="framing.creation_minimum",
                    )
                ],
                confidence="medium",
                suffix="title-primary",
            )
        ]
        for index, alt in enumerate(title_alts):
            title_candidates.append(
                _candidate(
                    field_path="framing.document_title",
                    value=alt,
                    preview=alt,
                    rationale="标题措辞备选，保留同一研究身份事实。",
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="creation_minimum",
                            source_text=f"{product}|{indication}|{phase}",
                            locator="framing.creation_minimum",
                        )
                    ],
                    confidence="low",
                    suffix=f"title-alt-{index}",
                )
            )
        add("framing.document_title", title_candidates)

    if indication:
        add(
            "framing.clinicaltrials_condition_term",
            [
                _candidate(
                    field_path="framing.clinicaltrials_condition_term",
                    value=condition,
                    preview=condition,
                    rationale=(
                        "优先使用已录入的ClinicalTrials.gov条件词；"
                        "缺失时回退为适应症以启动宽检索。"
                    ),
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.indication",
                            source_text=indication,
                            locator="framing.indication",
                        )
                    ],
                    confidence="medium" if framing.clinicaltrials_condition_term else "low",
                    limitations=(
                        []
                        if framing.clinicaltrials_condition_term
                        else ["中文适应症可能降低英文注册库检索精度。"]
                    ),
                    suffix="condition-primary",
                )
            ],
        )
        # Lazy-writer product facts: never leave modality/route/mechanism blank.
        # Recommendations require user confirm before becoming ready facts.
        tech_candidates = [
            ("small_molecule", "小分子化学药（口服/注射候选）"),
            ("monoclonal_antibody", "单克隆抗体/生物制品"),
            ("other_biologic", "其他生物制品（非单抗）"),
            ("rna_therapy", "RNA/寡核苷酸疗法"),
            ("other", "其他/待进一步分类"),
        ]
        add(
            "framing.product_profile.technology_type",
            [
                _candidate(
                    field_path="framing.product_profile.technology_type",
                    value=tech_code,
                    preview=tech_label,
                    rationale=(
                        "无IB时给出可确认的技术类型候选，供竞品分诊与章节适用性使用；"
                        "不得在用户确认前写入正式设计事实。"
                    ),
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.investigational_product",
                            source_text=product or indication,
                            locator="framing.investigational_product",
                        )
                    ],
                    confidence="low",
                    limitations=["需医学经理按产品真实类型确认；确认前竞品接近度保持unknown。"],
                    suffix=f"tech-{tech_code}",
                )
                for tech_code, tech_label in tech_candidates
            ],
        )
        route_candidates = [
            (["口服"], "口服"),
            (["静脉输注"], "静脉输注"),
            (["皮下注射"], "皮下注射"),
            (["鼻喷"], "鼻用喷雾"),
            (["吸入"], "吸入给药"),
        ]
        add(
            "framing.product_profile.administration_routes",
            [
                _candidate(
                    field_path="framing.product_profile.administration_routes",
                    value=routes,
                    preview=label,
                    rationale="无IB时给出常用给药途径候选，用户选择后驱动SoA/安全/竞品维度。",
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.indication",
                            source_text=indication,
                            locator="framing.indication",
                        )
                    ],
                    confidence="low",
                    limitations=["精确途径以IB/说明书/已确认产品事实为准。"],
                    suffix=f"route-{label}",
                )
                for routes, label in route_candidates
            ],
        )
        mechanism_templates = [
            f"{indication}相关靶点/通路（名称按项目资料复核）",
            f"{product or '试验药物'}的主要作用机制（按IB/已确认产品事实补充）",
            "补体通路/免疫调节相关机制（若适用，按项目资料复核）",
            "靶点/机制尚未写入产品事实，先按适应症宽检索竞品",
        ]
        add(
            "framing.target_mechanism",
            [
                _candidate(
                    field_path="framing.target_mechanism",
                    value=text,
                    preview=text,
                    rationale="给出可编辑的机制/靶点候选或明确未知占位，避免空白起步。",
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.indication",
                            source_text=indication,
                            locator="framing.indication",
                        )
                    ],
                    confidence="low",
                    limitations=["不得把未确认机制当作直接竞品判定依据。"],
                    suffix=f"mech-{index}",
                )
                for index, text in enumerate(mechanism_templates)
            ],
        )
        add(
            "framing.population_intent",
            [
                _candidate(
                    field_path="framing.population_intent",
                    value=(
                        f"成人、中重度{indication}、经治或初治均可入组的目标人群"
                        f"（按项目认可诊断标准确诊）"
                    ),
                    preview=(
                        f"成人·中重度{indication}·经治/初治（按项目认可诊断标准确诊）"
                    ),
                    rationale=(
                        "默认纳入成人与中重度疾病状态，并覆盖经治/初治分面；"
                        "精确年龄切点与治疗线定义需后续按适应症确认。"
                    ),
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.indication",
                            source_text=indication,
                            locator="framing.indication",
                        )
                    ],
                    confidence="low",
                    limitations=[
                        "未锁定精确年龄上下限、儿童扩展或生物标志物富集，需后续确认。",
                    ],
                    recommendation_role="recommended",
                    suffix="population-primary",
                ),
            ],
        )
        add(
            "picos.population_summary",
            [
                _candidate(
                    field_path="picos.population_summary",
                    value=f"诊断为{indication}并满足方案入选标准的试验参与者。",
                    preview=f"诊断为{indication}并满足方案入选标准的试验参与者。",
                    rationale="由适应症派生的人群摘要骨架，不含未证据支持的阈值。",
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.indication",
                            source_text=indication,
                            locator="framing.indication",
                        )
                    ],
                    confidence="low",
                    limitations=["不包含具体年龄、实验室或疾病活动度阈值。"],
                    suffix="picos-population",
                )
            ],
        )

    # Design pattern: derive ONLY from confirmed facts (product/indication/phase).
    # Phase alone does NOT prove randomization, blinding, comparator, or center
    # model. The design pattern is a descriptive compatibility projection text;
    # orthogonal design dimensions are separate pending-decision fields below.
    design_evidence = [
        _evidence(
            source_kind="study_definition",
            source_id="framing.study_phase",
            source_text=phase or "unknown",
            locator="framing.study_phase",
        )
    ]
    if title_hints:
        design_evidence.append(
            _evidence(
                source_kind="search_snapshot",
                source_id=snapshot.snapshot_id if snapshot else "none",
                source_text=title_hints[0][:500],
                locator="registry.brief_or_official_title",
            )
        )

    if phase_bucket in {"phase3", "phase2_3"}:
        design_text = (
            f"{phase or 'III期'}（{indication or '目标适应症'}）"
            "随机、对照、多中心确证性设计（按分期常见实践预填）"
        )
        design_alts = [
            f"{phase or 'III期'}（{indication or '目标适应症'}）随机对照确证性设计（活性对照备选）",
            f"{phase or 'III期'}（{indication or '目标适应症'}）随机对照确证性设计（适应性要素可选）",
        ]
        design_rationale = (
            "按III期/确证常见实践给出明确设计描述默认；"
            "随机化、盲法、对照、中心等正交维度见下方推荐卡，禁止以「待确认」作为默认。"
        )
    elif phase_bucket == "phase1":
        design_text = (
            f"{phase or 'I期'}（{indication or '目标适应症'}）"
            "开放标签剂量递增/安全探索设计（按分期常见实践预填）"
        )
        design_alts = [
            f"{phase or 'I期'}（{indication or '目标适应症'}）单臂安全与PK/PD探索设计",
            f"{phase or 'I期'}（{indication or '目标适应症'}）多队列剂量探索设计",
        ]
        design_rationale = (
            "按I期常见实践给出开放标签剂量探索设计默认；禁止「待确认」占位。"
        )
    else:
        design_text = (
            f"{phase or 'II期'}（{indication or '目标适应症'}）"
            "随机对照探索性设计（按分期常见实践预填）"
        )
        design_alts = [
            f"{phase or 'II期'}（{indication or '目标适应症'}）单臂概念验证设计",
            f"{phase or 'II期'}（{indication or '目标适应症'}）随机对照剂量优化设计",
        ]
        design_rationale = (
            "按II期常见实践给出随机对照探索性设计默认；禁止「待确认」占位。"
        )

    design_candidates = [
        _candidate(
            field_path="framing.design_pattern",
            value=design_text,
            preview=design_text,
            rationale=design_rationale,
            evidence=design_evidence,
            confidence="medium",
            limitations=[
                "本字段为设计描述默认，仍须与下方盲法/对照/中心等正交推荐一并复核。",
            ],
            recommendation_role="recommended",
            adoption_mode="batch_allowed",
            suffix="design-recommended",
        )
    ]
    for index, alt in enumerate(design_alts):
        design_candidates.append(
            _candidate(
                field_path="framing.design_pattern",
                value=alt,
                preview=alt,
                rationale="措辞与设计侧重备选，不编造未确认的精确临床事实。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix=f"design-alt-{index}",
            )
        )
    add("framing.design_pattern", design_candidates)

    if phase_bucket in {"phase3", "phase2_3"}:
        arch_value, arch_preview, arch_rationale, arch_conf, arch_suffix = (
            "randomized_confirmatory",
            "随机确证性",
            "III期/确证常用：随机确证性设计原型。",
            "medium",
            "archetype-confirmatory",
        )
    elif phase_bucket == "phase1":
        arch_value, arch_preview, arch_rationale, arch_conf, arch_suffix = (
            "single_arm_early_phase",
            "单臂早期",
            "I期常用：单臂早期探索设计原型。",
            "medium",
            "archetype-early",
        )
    else:
        arch_value, arch_preview, arch_rationale, arch_conf, arch_suffix = (
            "randomized_exploratory",
            "随机探索性",
            "II期常用：随机探索性设计原型。",
            "medium",
            "archetype-exploratory",
        )
    archetype_candidates = [
        _candidate(
            field_path="picos.design_archetype",
            value=arch_value,
            preview=arch_preview,
            rationale=arch_rationale,
            evidence=design_evidence,
            confidence=arch_conf,
            recommendation_role="recommended",
            adoption_mode="batch_allowed",
            suffix=arch_suffix,
        ),
        _candidate(
            field_path="picos.design_archetype",
            value="randomized_confirmatory",
            preview="随机确证性",
            rationale="确证性终点与假设检验场景备选。",
            evidence=design_evidence,
            confidence="low",
            recommendation_role="alternative",
            suffix="archetype-confirmatory-alt",
        ),
        _candidate(
            field_path="picos.design_archetype",
            value="randomized_exploratory",
            preview="随机探索性",
            rationale="探索性疗效/剂量寻优场景备选。",
            evidence=design_evidence,
            confidence="low",
            recommendation_role="alternative",
            suffix="archetype-exploratory-alt",
        ),
        _candidate(
            field_path="picos.design_archetype",
            value="single_arm_early_phase",
            preview="单臂早期",
            rationale="早期开放/剂量队列场景备选。",
            evidence=design_evidence,
            confidence="low",
            recommendation_role="alternative",
            suffix="archetype-early-alt",
        ),
    ]
    seen_arch = set()
    deduped_arch = []
    for item in archetype_candidates:
        key = canonicalize_candidate_value(item.structured_value)
        if key in seen_arch:
            continue
        seen_arch.add(key)
        deduped_arch.append(item)
    add("picos.design_archetype", deduped_arch)

    # Orthogonal design proposal fields.
    # Recommended picks are concrete clinical defaults (never「待确认」/
    # pending_decision as the recommended card). Evidence % is attached when
    # registry facet counts are available; otherwise phase-typical defaults.
    phase3ish = phase_bucket in {"phase3", "phase2_3"}
    phase2ish = phase_bucket in {"phase2", "phase2_3", "phase3"}
    if phase3ish:
        randomization_candidates = [
            _candidate(
                field_path="design.randomization",
                value={
                    "mode": "随机",
                    "stratification": "分层随机",
                    "factors": ["研究中心", "基线疾病严重程度"],
                },
                preview="分层随机（中心 + 基线严重程度）",
                rationale=(
                    f"{phase or 'III期'}确证性研究默认推荐分层随机，"
                    "以控制中心与基线严重程度对主要终点的偏倚。"
                ),
                evidence=design_evidence,
                confidence="medium",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=[
                    "分层可降低基线不均衡风险，但层数过多会削弱小样本层内随机性。"
                ],
                evidence_gaps=["需按适应症确认最终分层因素（如蛋白尿分层、eGFR 等）。"],
                suffix="rand-stratified",
            ),
            _candidate(
                field_path="design.randomization",
                value={
                    "mode": "随机",
                    "stratification": "分层随机",
                    "factors": ["研究中心", "既往治疗线"],
                },
                preview="分层随机（中心 + 既往治疗线）",
                rationale="备选分层因素，适用于治疗线异质性明显的适应症。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="rand-stratified-line",
            ),
            _candidate(
                field_path="design.randomization",
                value={"mode": "随机", "stratification": "简单随机", "factors": []},
                preview="简单随机（不分层）",
                rationale="仅在样本量很大且关键预后因子可控时考虑。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="rand-simple",
            ),
            _candidate(
                field_path="design.randomization",
                value={"mode": "非随机"},
                preview="非随机",
                rationale="确证性场景通常不推荐；仅在特殊单臂/外部对照设计时选用。",
                evidence=design_evidence,
                confidence="none",
                recommendation_role="alternative",
                suffix="rand-non-randomized",
            ),
        ]
    elif phase_bucket == "phase1":
        randomization_candidates = [
            _candidate(
                field_path="design.randomization",
                value={"mode": "非随机"},
                preview="非随机（剂量探索常见）",
                rationale="I期剂量递增/队列探索通常非随机起步。",
                evidence=design_evidence,
                confidence="medium",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                suffix="rand-non-randomized",
            ),
            _candidate(
                field_path="design.randomization",
                value={"mode": "随机"},
                preview="随机",
                rationale="若含对照或扩展队列随机化，可改选本项。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="rand-randomized",
            ),
        ]
    else:
        randomization_candidates = [
            _candidate(
                field_path="design.randomization",
                value={
                    "mode": "随机",
                    "stratification": "分层随机" if phase2ish else "简单随机",
                    "factors": ["研究中心"] if phase2ish else [],
                },
                preview=(
                    "分层随机（研究中心）" if phase2ish else "随机"
                ),
                rationale=(
                    f"{phase or 'II期'}常用随机化起点；"
                    + ("建议至少按中心分层。" if phase2ish else "可按设计目的再升级分层。")
                ),
                evidence=design_evidence,
                confidence="medium",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                suffix="rand-phase2-default",
            ),
            _candidate(
                field_path="design.randomization",
                value={
                    "mode": "随机",
                    "stratification": "分层随机",
                    "factors": ["研究中心", "基线疾病严重程度"],
                },
                preview="分层随机（中心 + 基线严重程度）",
                rationale="更接近确证性设计的分层策略备选。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="rand-stratified",
            ),
            _candidate(
                field_path="design.randomization",
                value={"mode": "非随机"},
                preview="非随机",
                rationale="探索性单臂/剂量队列备选。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="rand-non-randomized",
            ),
        ]
    add("design.randomization", randomization_candidates)
    # Evidence-aware recommended defaults (never「待确认」as recommended).
    blind_total = int(facet_counts["blinding"]["total"])
    blind_double = int(facet_counts["blinding"]["double"])
    blind_open = int(facet_counts["blinding"]["open"])
    if phase_bucket in {"phase1", "phase1_2"}:
        blind_rec_mode, blind_rec_roles, blind_rec_preview = (
            "开放标签",
            [],
            "开放标签",
        )
        blind_label = "开放标签"
    elif blind_total > 0 and blind_open > blind_double:
        blind_rec_mode, blind_rec_roles, blind_rec_preview = (
            "开放标签",
            [],
            "开放标签",
        )
        blind_label = "开放标签"
    else:
        blind_rec_mode, blind_rec_roles, blind_rec_preview = (
            "双盲",
            ["受试者", "研究者", "评价者"],
            "双盲（受试者、研究者、评价者）",
        )
        blind_label = "双盲"
    blind_note = _evidence_pct_rationale(blind_label, blind_double if blind_label == "双盲" else blind_open, blind_total)
    blind_rationale = _clinical_default_rationale(phase, blind_label, evidence_note=blind_note)

    comp_total = int(facet_counts["comparator"]["total"])
    comp_placebo = int(facet_counts["comparator"]["placebo"])
    comp_none = int(facet_counts["comparator"]["none"])
    if phase_bucket in {"phase1", "phase1_2"}:
        comp_rec_type, comp_rec_preview, comp_label = (
            "无对照/剂量递增",
            "无对照/剂量递增",
            "无对照/剂量递增",
        )
        comp_count_for_pct = comp_none
    elif phase3ish or phase_bucket in {"phase2", "phase2_3"}:
        comp_rec_type, comp_rec_preview, comp_label = (
            "安慰剂",
            "安慰剂对照（匹配安慰剂）",
            "安慰剂对照",
        )
        comp_count_for_pct = comp_placebo
    else:
        comp_rec_type, comp_rec_preview, comp_label = (
            "安慰剂",
            "安慰剂对照（匹配安慰剂）",
            "安慰剂对照",
        )
        comp_count_for_pct = comp_placebo
    comp_note = _evidence_pct_rationale(comp_label, comp_count_for_pct, comp_total)
    if phase3ish and not comp_note:
        comp_rationale = (
            f"III期/确证性场景默认推荐安慰剂对照；"
            f"当前语料样本不足，按{phase or 'III期'}常见实践默认推荐安慰剂对照。"
        )
    else:
        comp_rationale = _clinical_default_rationale(
            phase, comp_label, evidence_note=comp_note
        )

    assign_total = int(facet_counts["assignment"]["total"])
    assign_parallel = int(facet_counts["assignment"]["parallel"])
    assign_seq = int(facet_counts["assignment"]["sequential"])
    if phase_bucket in {"phase1", "phase1_2"}:
        assign_rec, assign_label, assign_count = (
            "序贯/剂量递增队列",
            "序贯/剂量递增队列",
            assign_seq,
        )
    else:
        assign_rec, assign_label, assign_count = ("平行分组", "平行分组", assign_parallel)
    assign_note = _evidence_pct_rationale(assign_label, assign_count, assign_total)
    assign_rationale = _clinical_default_rationale(
        phase, assign_label, evidence_note=assign_note
    )

    center_total = int(facet_counts["center"]["total"])
    center_multi = int(facet_counts["center"]["multi"])
    if phase_bucket in {"phase1"}:
        center_rec, center_label = ("单中心或有限中心", "单中心或有限中心")
        center_count = int(facet_counts["center"]["single"])
    else:
        center_rec, center_label = ("多中心", "多中心")
        center_count = center_multi
    center_note = _evidence_pct_rationale(center_label, center_count, center_total)
    center_rationale = _clinical_default_rationale(
        phase, center_label, evidence_note=center_note
    )

    if phase3ish:
        interim_preview = "不计划期中分析（确证性默认）"
        interim_rationale = (
            f"当前语料样本不足，按{phase or 'III期'}确证性常见实践默认推荐不计划期中分析；"
            "若需无效/优势期中，可改选计划期中并明确用途与边界。"
        )
        interim_value = {"planned": False, "purpose": ""}
    elif phase_bucket in {"phase1", "phase1_2"}:
        interim_preview = "不计划正式期中疗效分析（SRC剂量决策另计）"
        interim_rationale = (
            f"按{phase or 'I期'}常见实践默认不设正式期中疗效分析；"
            "剂量递增安全审查由 SRC 承担，不在此字段冒充期中边界。"
        )
        interim_value = {"planned": False, "purpose": ""}
    else:
        interim_preview = "不计划期中分析"
        interim_rationale = _clinical_default_rationale(phase, "不计划期中分析")
        interim_value = {"planned": False, "purpose": ""}

    add(
        "design.blinding",
        [
            _candidate(
                field_path="design.blinding",
                value={"mode": blind_rec_mode, "blinded_roles": blind_rec_roles},
                preview=blind_rec_preview,
                rationale=blind_rationale,
                evidence=design_evidence,
                confidence="medium" if blind_note else "low",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                suffix="blind-recommended",
            ),
            _candidate(
                field_path="design.blinding",
                value={"mode": "双盲", "blinded_roles": ["受试者", "研究者", "评价者"]},
                preview="双盲（受试者、研究者、评价者）",
                rationale="双盲备选——适用于安慰剂/匹配对照且偏倚控制要求高的场景。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="blind-double",
            ),
            _candidate(
                field_path="design.blinding",
                value={"mode": "单盲", "blinded_roles": ["受试者"]},
                preview="单盲（受试者）",
                rationale="单盲备选。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="blind-single",
            ),
            _candidate(
                field_path="design.blinding",
                value={"mode": "开放标签", "blinded_roles": []},
                preview="开放标签",
                rationale="开放标签备选——适用于剂量探索、外用或无法匹配制剂的场景。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="blind-open",
            ),
        ],
    )
    add(
        "design.comparator_type",
        [
            _candidate(
                field_path="design.comparator_type",
                value={
                    "type": comp_rec_type,
                    "intervention": "匹配安慰剂" if comp_rec_type == "安慰剂" else "",
                },
                preview=comp_rec_preview,
                rationale=comp_rationale,
                evidence=design_evidence,
                confidence="medium" if comp_note else "low",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                suffix="comp-recommended",
            ),
            _candidate(
                field_path="design.comparator_type",
                value={"type": "安慰剂", "intervention": "匹配安慰剂"},
                preview="安慰剂对照（匹配安慰剂）",
                rationale="安慰剂对照备选。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="comp-placebo",
            ),
            _candidate(
                field_path="design.comparator_type",
                value={"type": "活性对照", "intervention": ""},
                preview="活性对照（对照药在干预规则中定义）",
                rationale=(
                    "活性对照备选；具体对照药须在试验干预规则中以"
                    " product_role=active_comparator 记录，不在此虚构品种。"
                ),
                evidence=design_evidence,
                confidence="low",
                limitations=[
                    "活性对照具体药物不得在无证据时虚构。",
                ],
                recommendation_role="alternative",
                suffix="comp-active",
            ),
            _candidate(
                field_path="design.comparator_type",
                value={"type": "无对照/剂量递增", "intervention": ""},
                preview="无对照/剂量递增",
                rationale="无对照/剂量递增备选——适用于早期探索设计。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="comp-none",
            ),
        ],
    )
    add(
        "design.assignment_model",
        [
            _candidate(
                field_path="design.assignment_model",
                value={"model": assign_rec},
                preview=assign_rec,
                rationale=assign_rationale,
                evidence=design_evidence,
                confidence="medium" if assign_note else "low",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                suffix="assign-recommended",
            ),
            _candidate(
                field_path="design.assignment_model",
                value={"model": "平行分组"},
                preview="平行分组",
                rationale="平行分组备选。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="assign-parallel",
            ),
            _candidate(
                field_path="design.assignment_model",
                value={"model": "交叉"},
                preview="交叉",
                rationale="交叉设计备选。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="assign-crossover",
            ),
            _candidate(
                field_path="design.assignment_model",
                value={"model": "序贯/剂量递增队列"},
                preview="序贯/剂量递增队列",
                rationale="序贯/剂量递增队列备选——适用于早期探索设计。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="assign-sequential",
            ),
        ],
    )
    add(
        "design.center_model",
        [
            _candidate(
                field_path="design.center_model",
                value={"model": center_rec},
                preview=center_rec,
                rationale=center_rationale,
                evidence=design_evidence,
                confidence="medium" if center_note else "low",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                suffix="center-recommended",
            ),
            _candidate(
                field_path="design.center_model",
                value={"model": "多中心"},
                preview="多中心",
                rationale="多中心备选。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="center-multi",
            ),
            _candidate(
                field_path="design.center_model",
                value={"model": "单中心"},
                preview="单中心",
                rationale="单中心备选。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="center-single",
            ),
            _candidate(
                field_path="design.center_model",
                value={"model": "单中心或有限中心"},
                preview="单中心或有限中心",
                rationale="单中心或有限中心备选——适用于早期研究。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="center-limited",
            ),
        ],
    )
    add(
        "design.adaptive_design",
        [
            _candidate(
                field_path="design.adaptive_design",
                value={"enabled": False, "features": []},
                preview="不启用适应性设计",
                rationale="默认关闭适应性设计；需要时再改选具体特征。",
                evidence=design_evidence,
                confidence="medium",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                suffix="adaptive-off",
            ),
            _candidate(
                field_path="design.adaptive_design",
                value={"enabled": True, "features": ["样本量重估"]},
                preview="适应性：样本量重估（SSR）",
                rationale="期中基于盲态/非盲样本量重估，适用于效应量不确定场景。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="adaptive-ssr",
            ),
            _candidate(
                field_path="design.adaptive_design",
                value={"enabled": True, "features": ["富集设计"]},
                preview="适应性：富集/biomarker 富集",
                rationale="基于生物标志物或早期应答富集有效人群。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="adaptive-enrichment",
            ),
            _candidate(
                field_path="design.adaptive_design",
                value={"enabled": True, "features": ["臂剔除"]},
                preview="适应性：无效臂剔除",
                rationale="多臂筛选阶段可剔除无效剂量/方案臂。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="adaptive-arm-drop",
            ),
            _candidate(
                field_path="design.adaptive_design",
                value={"enabled": True, "features": ["剂量自适应"]},
                preview="适应性：剂量自适应",
                rationale="基于暴露/毒性反应调整后续剂量分配。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="adaptive-dose",
            ),
            _candidate(
                field_path="design.adaptive_design",
                value={"enabled": True, "features": ["无缝设计"]},
                preview="适应性：无缝 I/II 或 II/III",
                rationale="阶段间无缝衔接，减少停顿与重复建库成本。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="adaptive-seamless",
            ),
        ],
    )
    src_dmc_candidates = [
        _candidate(
            field_path="design.src_dmc",
            value={"src": False, "dmc": True} if phase2ish else {"src": True, "dmc": False},
            preview="设DMC" if phase2ish else "设SRC",
            rationale=(
                "II/III 确证/对照研究默认建议独立 DMC。"
                if phase2ish
                else "早期剂量探索默认建议 SRC 剂量决策。"
            ),
            evidence=design_evidence,
            confidence="medium",
            recommendation_role="recommended",
            adoption_mode="batch_allowed",
            suffix="src-dmc-default",
        ),
        _candidate(
            field_path="design.src_dmc",
            value={"src": True, "dmc": False},
            preview="仅设SRC",
            rationale="剂量/队列安全审查场景。",
            evidence=design_evidence,
            confidence="low",
            recommendation_role="alternative",
            suffix="src-dmc-src",
        ),
        _candidate(
            field_path="design.src_dmc",
            value={"src": False, "dmc": True},
            preview="仅设DMC",
            rationale="确证性终点与累积安全性监督场景。",
            evidence=design_evidence,
            confidence="low",
            recommendation_role="alternative",
            suffix="src-dmc-dmc",
        ),
        _candidate(
            field_path="design.src_dmc",
            value={"src": True, "dmc": True},
            preview="同时设SRC与DMC",
            rationale="早期探索与后期确证并存，或风险较高产品时的双委员会设置。",
            evidence=design_evidence,
            confidence="low",
            recommendation_role="alternative",
            suffix="src-dmc-both",
        ),
        _candidate(
            field_path="design.src_dmc",
            value={"src": False, "dmc": False},
            preview="不设SRC/DMC",
            rationale="仅在风险极低且监管可接受时选用；需书面说明。",
            evidence=design_evidence,
            confidence="none",
            recommendation_role="alternative",
            suffix="src-dmc-none",
        ),
    ]
    add("design.src_dmc", src_dmc_candidates)
    add(
        "design.interim_analysis",
        [
            _candidate(
                field_path="design.interim_analysis",
                value=interim_value,
                preview=interim_preview,
                rationale=interim_rationale,
                evidence=design_evidence,
                confidence="medium",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                limitations=["不生成精确α消耗或边界。"],
                suffix="interim-none",
            ),
            _candidate(
                field_path="design.interim_analysis",
                value={
                    "planned": True,
                    "purpose": "无效性/安全性期中评估",
                },
                preview="计划期中分析（无效性/安全性）",
                rationale="计划期中分析备选——需另行确认时间点、边界与α消耗。",
                evidence=design_evidence,
                confidence="low",
                recommendation_role="alternative",
                suffix="interim-planned",
            ),
        ],
    )
    if phase_bucket in {"phase1", "phase1_2"}:
        # I期 Part可选目录：完整、稳定、机器可读。因候选上限为1推荐+4备选，
        # 无法通过候选列表传递全部8类Part。将完整目录嵌入待决定卡的
        # structured_value["available_part_types"]，前端可可靠读取。
        phase1_part_types = [
            "SAD", "MAD", "首次患者", "食物影响", "物质平衡",
            "肝损伤", "肾损伤", "DDI",
        ]
        part_candidates = [
            _candidate(
                field_path="design.phase1_parts",
                value={
                    "parts": [
                        {
                            "part_code": "SAD",
                            "part_label": "单次给药递增",
                            "population": f"符合{indication or '适应症'}入排的健康受试者或轻症患者",
                            "cohort_dose": "起始剂量队列并按方案递增",
                            "pk_pd": "单次给药后密集PK采样",
                            "safety": "DLT与不良事件监测",
                            "stopping_rules": "DLT或SRC决定暂停时停止",
                            "soa_summary": "筛选—给药日观察—安全性随访",
                            "transition_dependencies": "SRC通过后进入MAD",
                            "unresolved": False,
                        },
                        {
                            "part_code": "MAD",
                            "part_label": "多次给药递增",
                            "population": f"符合{indication or '适应症'}入排的受试者",
                            "cohort_dose": "多日/多周给药队列",
                            "pk_pd": "稳态PK与必要PD",
                            "safety": "累积暴露安全性监测",
                            "stopping_rules": "DLT/SRC门控",
                            "soa_summary": "筛选—多次给药期—安全性随访",
                            "transition_dependencies": "可与SAD序贯",
                            "unresolved": False,
                        },
                    ],
                    "sequence": "sequential",
                    "available_part_types": list(phase1_part_types),
                },
                preview="SAD + MAD（推荐组合）",
                rationale="I期常用 SAD 序贯 MAD 起步；可按药代与适应症改选其他 Part。",
                evidence=design_evidence,
                confidence="medium",
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                suffix="parts-sad-mad",
            ),
            _candidate(
                field_path="design.phase1_parts",
                value={
                    "parts": [],
                    "sequence": "",
                    "available_part_types": list(phase1_part_types),
                },
                preview="稍后自选 Part 组合",
                rationale="若暂不采用默认 SAD+MAD，可在此自选 Part 类型。",
                evidence=design_evidence,
                confidence="none",
                recommendation_role="alternative",
                adoption_mode="manual_only",
                suffix="parts-pending",
            ),
        ]
        # 提供前3个Part类型作为单独备选（受候选上限5限制）
        for part_code in phase1_part_types[:3]:
            part_candidates.append(
                _candidate(
                    field_path="design.phase1_parts",
                    value={
                        "parts": [{"part_code": part_code}],
                        "sequence": "standalone",
                    },
                    preview=f"仅{part_code}（备选）",
                    rationale=f"仅{part_code}备选——完整可选目录见待决定卡。",
                    evidence=design_evidence,
                    confidence="none",
                    recommendation_role="alternative",
                    suffix=f"parts-alt-{part_code.lower()}",
                )
            )
        add("design.phase1_parts", part_candidates[:5])
        add(
            "design.arms_or_cohorts",
            [
                _candidate(
                    field_path="design.arms_or_cohorts",
                    value={"kind": "dose_cohorts", "labels": ["队列1", "队列2", "队列3"]},
                    preview="剂量递增队列（队列1–3）",
                    rationale=_clinical_default_rationale(
                        phase, "剂量递增队列", evidence_note=""
                    ),
                    evidence=design_evidence,
                    confidence="low",
                    limitations=[
                        "不得据此推断起始剂量或爬坡步长。",
                    ],
                    recommendation_role="recommended",
                    adoption_mode="batch_allowed",
                    suffix="cohorts-dose",
                ),
                _candidate(
                    field_path="design.arms_or_cohorts",
                    value={
                        "kind": "dose_cohorts",
                        "labels": ["队列1", "队列2", "队列3", "扩展队列"],
                    },
                    preview="剂量递增队列 + 扩展队列",
                    rationale="在递增队列后增加扩展队列，便于PK/PD与初步疗效观察。",
                    evidence=design_evidence,
                    confidence="low",
                    recommendation_role="alternative",
                    suffix="cohorts-dose-expansion",
                ),
            ],
        )
    else:
        add(
            "design.arms_or_cohorts",
            [
                _candidate(
                    field_path="design.arms_or_cohorts",
                    value={
                        "kind": "parallel_arms",
                        "labels": ["试验药组", "对照组"],
                    },
                    preview="平行两组：试验药 vs 对照",
                    rationale=_clinical_default_rationale(
                        phase, "平行两组（试验药 vs 对照）"
                    ),
                    evidence=design_evidence,
                    confidence="medium",
                    recommendation_role="recommended",
                    adoption_mode="batch_allowed",
                    suffix="arms-parallel-2",
                ),
                _candidate(
                    field_path="design.arms_or_cohorts",
                    value={
                        "kind": "parallel_arms",
                        "labels": ["低剂量", "高剂量", "安慰剂"],
                    },
                    preview="平行三组：低/高剂量 vs 安慰剂",
                    rationale="剂量探索平行组备选。",
                    evidence=design_evidence,
                    confidence="low",
                    limitations=["不给出精确剂量数值。"],
                    recommendation_role="alternative",
                    suffix="arms-parallel-3",
                ),
            ],
        )

    # Intervention summary without inventing dose.
    if product:
        add(
            "picos.intervention_summary",
            [
                _candidate(
                    field_path="picos.intervention_summary",
                    value=f"{product}按方案规定给药（剂量与频次待项目资料确认）。",
                    preview=f"{product}按方案规定给药（剂量与频次待项目资料确认）。",
                    rationale="仅绑定试验药物身份，不编造剂量窗口。",
                    evidence=[
                        _evidence(
                            source_kind="study_definition",
                            source_id="framing.investigational_product",
                            source_text=product,
                            locator="framing.investigational_product",
                        )
                    ],
                    confidence="low",
                    limitations=["精确剂量、频次与时间窗需IB或既往临床证据。"],
                    suffix="intervention-summary",
                )
            ],
        )

    # ---------------------------------------------------------------
    # Four module-scope composite package candidates.
    # Each covers a PICOS module with field-level structured_value keyed
    # by target_paths. Without project evidence these are pending_decision
    # cards that explain what minimal information is needed.
    # ---------------------------------------------------------------
    _identity_evidence = [
        _evidence(
            source_kind="study_definition",
            source_id="creation_minimum",
            source_text=f"{product}|{indication}|{phase}",
            locator="framing.creation_minimum",
        )
    ] if (product and indication and phase) else design_evidence

    # package.population
    pop_paths = [
        "picos.population_summary",
        "picos.inclusion_modules",
        "picos.exclusion_modules",
        "picos.washout_rules",
    ]
    default_inclusions = [
        f"按项目认可诊断标准确诊为{indication or '目标适应症'}的成人受试者",
        f"疾病活动度/严重度符合中重度{indication or '适应症'}入组范围（量表与切点按方案规定）",
        "经治或初治受试者均可入组（治疗线定义按方案规定）",
        "年龄、性别与避孕要求符合方案规定的成人人群标准",
        "能够理解并签署知情同意，愿意遵守访视与检查要求",
        "筛选期实验室与生命体征满足方案安全阈值",
    ]
    default_exclusions = [
        "合并其他可能干扰疗效/安全性评价的活动性重大疾病",
        "对试验药物或其辅料过敏或存在禁忌",
        "筛选前规定时窗内接受过禁止治疗或未完成必要洗脱",
        "妊娠、哺乳或不同意有效避孕（若适用）",
        "研究者判断不适合参加或不太可能完成研究的其他情况",
    ]
    default_washout = [
        "既往相关治疗需完成方案规定的洗脱期后方可筛选",
    ]
    # Facets are encoded in summary/inclusion text (contract forbids extra
    # structured_value keys outside target_paths).
    pop_value = {
        "picos.population_summary": (
            f"成人、中重度{indication}、经治/初治均可、按项目认可诊断标准确诊的试验参与者。"
            if indication
            else "成人、中重度目标适应症、经治/初治均可、按项目认可诊断标准确诊的试验参与者。"
        ),
        "picos.inclusion_modules": default_inclusions,
        "picos.exclusion_modules": default_exclusions,
        "picos.washout_rules": default_washout,
    }
    pop_alt_narrow = {
        **pop_value,
        "picos.population_summary": (
            f"成人、中重度{indication or '目标适应症'}、经治受试者（偏严格）。"
        ),
        "picos.inclusion_modules": default_inclusions
        + [f"既往至少一线标准治疗失败或不耐受（经治定义按{indication or '适应症'}指南）"],
        "picos.exclusion_modules": default_exclusions
        + ["既往对同类机制药物原发无应答"],
    }
    pop_alt_broad = {
        **pop_value,
        "picos.population_summary": (
            f"成人或符合扩展条件的{indication or '目标适应症'}受试者（偏宽，含稳定背景治疗）。"
        ),
        "picos.inclusion_modules": default_inclusions[:4]
        + ["允许稳定背景治疗（允许清单按方案规定）"],
    }
    add(
        "package.population",
        [
            _module_candidate(
                field_path="package.population",
                target_paths=pop_paths,
                structured_value=pop_value,
                preview=(
                    f"研究人群推荐包A（成人·中重度·经治/初治 · {indication or '目标适应症'}）"
                ),
                rationale=(
                    "默认推荐：入选条款覆盖成人、中重度、经治/初治分面，"
                    "并以「按项目认可诊断标准确诊」替代空泛待确认表述。"
                ),
                evidence=_identity_evidence,
                confidence="low",
                limitations=[
                    "精确实验室阈值、疾病活动度切点、治疗线需IB/竞品方案/指导原则确认。",
                ],
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=[
                    "人群过宽：入组快但异质性高。",
                    "人群过窄：同质性好但入组困难。",
                ],
                evidence_gaps=[
                    "需确认精确年龄上下限、儿童扩展与生物标志物富集。",
                ],
                suffix="pkg-pop-primary",
            ),
            _module_candidate(
                field_path="package.population",
                target_paths=pop_paths,
                structured_value=pop_alt_narrow,
                preview=f"研究人群推荐包B（偏严格·经治 · {indication or '目标适应症'}）",
                rationale="在标准骨架上聚焦经治与机制相关排除，适合确证性设计。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["活动度量表与切点必须有来源。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["更严入排可提高同质性，但延长入组。"],
                evidence_gaps=["需竞品Protocol确认活动度定义。"],
                suffix="pkg-pop-narrow",
            ),
            _module_candidate(
                field_path="package.population",
                target_paths=pop_paths,
                structured_value=pop_alt_broad,
                preview=f"研究人群推荐包C（偏宽·稳定背景治疗 · {indication or '目标适应症'}）",
                rationale="保留核心入选并允许稳定背景治疗，适合探索性或入组困难场景。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["背景治疗清单不得空泛，确认前仅作候选。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["更易入组，但需更强的分层/协变量控制。"],
                evidence_gaps=["需确认允许/禁止背景治疗边界。"],
                suffix="pkg-pop-broad",
            ),
        ],
    )

    drug = product or "试验药物"
    ind = indication or "目标适应症"

    # package.intervention
    int_paths = [
        "picos.intervention_summary",
        "picos.intervention_dose_regimen",
        "picos.required_background_rules",
        "picos.allowed_concomitant_rules",
        "picos.prohibited_concomitant_rules",
        "picos.assessment_timing_restrictions",
    ]
    int_standard = {
        "picos.intervention_summary": (
            f"{drug}按方案规定给药；对照与背景治疗规则见合并用药包（剂量/频次待IB确认）。"
        ),
        "picos.intervention_dose_regimen": (
            f"{drug}用法用量：剂量、频次、给药途径与疗程待IB/既往临床证据确认后写入正式事实。"
        ),
        "picos.required_background_rules": [
            f"若{ind}标准治疗需维持，按方案规定的稳定剂量背景治疗（具体药物与剂量待确认）",
        ],
        "picos.allowed_concomitant_rules": [
            "允许治疗不良事件的支持治疗（清单与剂量限制待确认）",
            "允许稳定使用的非研究相关慢性病用药（清单待确认）",
        ],
        "picos.prohibited_concomitant_rules": [
            "禁止与试验药物存在已知重要相互作用的药物（清单待IB确认）",
            "禁止同期参加其他干预性临床试验",
        ],
        "picos.assessment_timing_restrictions": [
            "疗效/安全性评价前需按方案完成规定时窗的用药限制（时窗待确认）",
        ],
    }
    int_strict = {
        **int_standard,
        "picos.allowed_concomitant_rules": [
            "仅允许方案列出的支持治疗；其余合并用药需医学监查事先批准",
        ],
        "picos.prohibited_concomitant_rules": int_standard[
            "picos.prohibited_concomitant_rules"
        ]
        + ["禁止在评价窗内使用可能干扰主要终点的对症治疗（清单待确认）"],
    }
    int_realworld = {
        **int_standard,
        "picos.allowed_concomitant_rules": [
            "允许真实世界常用合并用药，记录但不强制洗脱（清单边界待确认）",
            "允许稳定背景治疗剂量微调（幅度与记录要求待确认）",
        ],
    }
    add(
        "package.intervention",
        [
            _module_candidate(
                field_path="package.intervention",
                target_paths=int_paths,
                structured_value=int_standard,
                preview=f"干预推荐包A（标准合并用药边界 · {drug}）",
                rationale=(
                    "默认推荐：给出试验药物摘要+背景/允许/禁止/评价前限制骨架；"
                    "精确剂量仍属精确事实，采用时若无证据将跳过并提示覆盖。"
                ),
                evidence=_identity_evidence,
                confidence="low",
                limitations=[
                    "精确剂量、频次与时间窗需IB或既往临床证据。",
                    "背景治疗和合并用药规则需方案摘要或指导原则确认。",
                ],
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=[
                    "允许更多合并用药：贴近真实世界但增加混杂因素。",
                    "严格限制合并用药：控制偏倚但可能限制入组。",
                ],
                evidence_gaps=[
                    "需IB确认试验药物的推荐剂量和给药途径。",
                    "需方案摘要或指导原则确认背景治疗和禁止用药列表。",
                ],
                suffix="pkg-int-standard",
            ),
            _module_candidate(
                field_path="package.intervention",
                target_paths=int_paths,
                structured_value=int_strict,
                preview=f"干预推荐包B（偏严格 · {ind}）",
                rationale="更严合并用药边界，适合确证性终点易受干扰的场景。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["禁止清单不得空泛，确认前仅作候选。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["偏倚控制更好，入组与依从成本更高。"],
                evidence_gaps=["需竞品Protocol核对干扰终点的药物类别。"],
                suffix="pkg-int-strict",
            ),
            _module_candidate(
                field_path="package.intervention",
                target_paths=int_paths,
                structured_value=int_realworld,
                preview=f"干预推荐包C（偏真实世界 · {drug}）",
                rationale="放宽合并用药记录策略，适合实效性/入组困难场景。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["需更强的协变量收集与敏感性分析计划。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["更易入组，终点解释需额外统计保护。"],
                evidence_gaps=["需确认哪些合并用药必须结构化采集。"],
                suffix="pkg-int-realworld",
            ),
        ],
    )

    # package.outcomes
    out_paths = [
        "picos.primary_objectives",
        "picos.secondary_objectives",
        "picos.exploratory_objectives",
        "picos.primary_endpoint",
        "picos.key_secondary_endpoints",
        "picos.other_secondary_endpoints",
        "picos.exploratory_endpoints",
        "picos.safety_endpoints",
        "picos.aesi_definitions",
        "picos.assessment_instruments",
    ]
    out_efficacy = {
        "picos.primary_objectives": [
            f"评价{drug}在{ind}目标人群中的疗效（主要）"
        ],
        "picos.secondary_objectives": [
            f"评价{drug}的其他疗效指标",
            f"评价{drug}的安全性和耐受性",
        ],
        "picos.exploratory_objectives": [
            f"探索{drug}的PK/PD或生物标志物特征（若适用）"
        ],
        "picos.primary_endpoint": (
            f"主要疗效终点：与{ind}临床获益相关的关键指标相对基线变化"
            f"（具体指标、时间点与分析集待确认）"
        ),
        "picos.key_secondary_endpoints": [
            "关键次要疗效终点（时间点与定义待确认）",
            "症状/功能或患者报告结局（量表与时间点待确认）",
        ],
        "picos.other_secondary_endpoints": [
            "其他次要疗效终点（待按竞品与指导原则补充）",
        ],
        "picos.exploratory_endpoints": [
            "探索性终点：生物标志物/机制相关指标（待确认）",
        ],
        "picos.safety_endpoints": [
            "AE/SAE/AESI发生率与严重程度",
            "实验室、生命体征、体格检查与ECG异常",
        ],
        "picos.aesi_definitions": [
            "AESI：按产品风险特征列出（无IB时先占位，确认前不作为正式事实）",
        ],
        "picos.assessment_instruments": [
            {
                "instrument_id": f"lazy_disease_activity_{ind}",
                "canonical_name_zh": f"{ind}疾病活动度/严重度量表（工具名待确认）",
                "instrument_kind": "clinician_reported",
                "study_purpose": "支持主要/关键次要疗效终点评价",
                "confirmation_status": "candidate",
            },
            {
                "instrument_id": f"lazy_pro_{ind}",
                "canonical_name_zh": "患者报告结局（PRO）量表（待确认）",
                "instrument_kind": "patient_reported",
                "study_purpose": "症状与功能相关次要/探索终点",
                "confirmation_status": "candidate",
            },
            {
                "instrument_id": "lazy_safety_panel",
                "canonical_name_zh": "安全性实验室与生命体征标准面板",
                "instrument_kind": "safety_grading",
                "study_purpose": "安全性终点与AESI监测",
                "confirmation_status": "candidate",
            },
        ],
    }
    out_safety_first = {
        **out_efficacy,
        "picos.primary_objectives": [
            f"评价{drug}在目标人群中的安全性和耐受性（主要）"
        ],
        "picos.primary_endpoint": (
            "主要安全性终点：治疗期AE/SAE/AESI及导致停药的不良事件"
            "（观察窗待确认）"
        ),
        "picos.key_secondary_endpoints": [
            f"关键疗效探索终点：与{ind}相关的疗效指标（时间点待确认）",
        ],
    }
    out_pkpd = {
        **out_efficacy,
        "picos.primary_objectives": [
            f"评价{drug}的药代动力学特征（主要）",
            f"评价{drug}的初步安全性和耐受性",
        ],
        "picos.primary_endpoint": (
            "主要PK终点：关键PK参数（如Cmax、AUC；具体参数与采样窗待确认）"
        ),
        "picos.exploratory_endpoints": [
            "PD/靶点相关生物标志物变化（若适用，待确认）",
        ],
    }
    add(
        "package.outcomes",
        [
            _module_candidate(
                field_path="package.outcomes",
                target_paths=out_paths,
                structured_value=out_efficacy,
                preview=f"终点推荐包A（疗效主导 · {ind}）",
                rationale="默认疗效主导包：主终点+关键次要+安全性骨架，供用户改/选。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["精确终点名、时间点、分析集无证据时不得当作已确认事实。"],
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["疗效主终点利于注册叙事，但需可靠效应量假设。"],
                evidence_gaps=["需竞品Protocol/指导原则确认主终点操作定义。"],
                suffix="pkg-out-efficacy",
            ),
            _module_candidate(
                field_path="package.outcomes",
                target_paths=out_paths,
                structured_value=out_safety_first,
                preview=f"终点推荐包B（安全主导 · {phase or '分期待确认'}）",
                rationale="I期或安全性优先场景：安全主终点，疗效作关键次要/探索。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["AESI必须来自产品风险，不可凭空罗列。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["安全主终点适合早期，但后期需切换疗效主终点。"],
                evidence_gaps=["需IB/同类药安全性信号确认AESI。"],
                suffix="pkg-out-safety",
            ),
            _module_candidate(
                field_path="package.outcomes",
                target_paths=out_paths,
                structured_value=out_pkpd,
                preview=f"终点推荐包C（PK/PD主导 · {drug}）",
                rationale="FIH/SAD/MAD常见：PK主终点+安全与探索性PD。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["PK参数与采样方案需临床药理确认。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["强化暴露评价，疗效证据较弱。"],
                evidence_gaps=["需确认采样窗、生物分析方法和PD标志物。"],
                suffix="pkg-out-pk",
            ),
        ],
    )

    # package.statistics
    stat_paths = [
        "picos.design_archetype",
        "picos.comparator_summary",
        "picos.study_epochs",
        "picos.visit_strategy",
        "picos.estimand_strategy",
        "picos.sample_size_strategy",
        "picos.statistical_strategy",
    ]
    phase_l = (phase or "").upper()
    if "I" in phase_l and "III" not in phase_l and "II" not in phase_l:
        default_epochs = ["筛选/基线期", "给药观察期", "安全性随访期"]
        default_visit = (
            f"筛选至基线完成入排与基线评价；给药观察期按方案密集采样/观察；"
            f"末次给药后完成安全性随访（具体研究日与窗宽待确认）。"
        )
        default_stat = (
            "描述性统计为主；PK可用非房室分析；安全性按SOC/PT汇总"
            "（分析方法待统计计划确认）。"
        )
        default_archetype = "single_arm_early_phase"
        default_comparator = "早期剂量探索可不设平行对照；若设对照则具体对照物待确认。"
    else:
        default_epochs = ["筛选期", "基线/随机", "双盲治疗期", "安全性随访期"]
        default_visit = (
            f"筛选期完成入排；基线/随机后进入治疗期，建议每4周访视评价"
            f"{ind}相关疗效与安全性；末次给药后完成安全性随访"
            f"（访视日与窗宽待按竞品Protocol确认）。"
        )
        default_stat = (
            "主要终点在主分析集上按预先指定模型分析；关键次要终点按门控/"
            "层级策略；安全性按治疗期emergent规则汇总（细节待SAP确认）。"
        )
        default_archetype = "randomized_exploratory"
        default_comparator = "安慰剂或阳性药对照（具体对照物、比例与给药匹配方式待确认）"
    stat_q4w = {
        "picos.design_archetype": default_archetype,
        "picos.comparator_summary": default_comparator,
        "picos.study_epochs": default_epochs,
        "picos.visit_strategy": default_visit,
        "picos.estimand_strategy": (
            "治疗策略estimand：关注分配治疗下的临床问题；关键伴发事件"
            "（停药、救援治疗等）的处理策略待与监管期望对齐后确认。"
        ),
        "picos.sample_size_strategy": (
            "样本量基于主要终点效应量、把握度与脱落率假设估算"
            "（精确假设待统计与竞品数据确认后写入正式事实）。"
        ),
        "picos.statistical_strategy": default_stat,
    }
    stat_q2w = {
        **stat_q4w,
        "picos.visit_strategy": (
            f"筛选与基线后，治疗期建议每2周访视以更密观察{ind}疗效/安全性；"
            f"稳定后可过渡至每4周（切换规则待确认）；结束后完成安全性随访。"
        ),
    }
    stat_pk_dense = {
        **stat_q4w,
        "picos.design_archetype": "single_arm_early_phase",
        "picos.comparator_summary": "PK/PD密集采样设计；平行对照按需设置（待确认）。",
        "picos.study_epochs": ["筛选/基线期", "密集PK/PD采样期", "安全性随访期"],
        "picos.visit_strategy": (
            f"筛选/基线后进入密集采样访视（含给药日多时间点）；"
            f"采样结束后转入常规安全随访（采样窗待临床药理确认）。"
        ),
        "picos.statistical_strategy": (
            "PK参数描述与模型探索；安全与初步疗效描述性汇总（细节待确认）。"
        ),
    }
    add(
        "package.statistics",
        [
            _module_candidate(
                field_path="package.statistics",
                target_paths=stat_paths,
                structured_value=stat_q4w,
                preview=f"执行/统计推荐包A（标准访视 · {phase or '分期待确认'}）",
                rationale="默认推荐：研究时期+访视+estimand/统计骨架，样本量仍属精确事实。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=[
                    "样本量假设需主要终点变异性和效应量数据。",
                    "estimand策略需与监管期望和伴发事件处理一致。",
                ],
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=[
                    "标准访视密度：可操作性强。",
                    "过疏访视可能漏检早期信号。",
                ],
                evidence_gaps=[
                    "需主要终点的基线变异性和预期效应量数据。",
                    "需确认伴发事件处理策略（治疗策略/复合策略等）。",
                ],
                suffix="pkg-stat-q4w",
            ),
            _module_candidate(
                field_path="package.statistics",
                target_paths=stat_paths,
                structured_value=stat_q2w,
                preview=f"执行/统计推荐包B（更密访视 · {ind}）",
                rationale="治疗早期加密访视，适合安全性或波动性终点。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["更密访视增加受试者负担与成本。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["信号捕获更好，操作性更差。"],
                evidence_gaps=["需确认加密访视的医学必要性。"],
                suffix="pkg-stat-q2w",
            ),
            _module_candidate(
                field_path="package.statistics",
                target_paths=stat_paths,
                structured_value=stat_pk_dense,
                preview=f"执行/统计推荐包C（PK密集 · {drug}）",
                rationale="FIH/临床药理常见：密集采样期+安全随访。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["采样窗与生物分析需临床药理确认。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["暴露评价强，疗效证据弱。"],
                evidence_gaps=["需确认采样矩阵与分析计划。"],
                suffix="pkg-stat-pk",
            ),
        ],
    )

    # package.soa intentionally omitted from PICOS/prefill.
    # SoA belongs after design confirmation (table designer / writing),
    # not as a PICOS composite package. study_epochs stay in package.statistics.

    # package.design — orthogonal structured design defaults so assembly plan
    # can be confirmed without blank undecided drivers.
    early_phase = (
        "I" in phase_l and "III" not in phase_l and "II" not in phase_l
    )
    design_paths = [
        "design.randomization",
        "design.blinding",
        "design.comparator_type",
        "design.assignment_model",
        "design.center_model",
        "design.adaptive_design",
        "design.src_dmc",
        "design.interim_analysis",
        "design.crossover",
        "design.open_label_extension",
        "design.sample_size_reestimation",
        "design.treatment_switch",
        "design.arms_or_cohorts",
    ]
    if early_phase:
        design_paths = [*design_paths, "design.phase1_parts"]
        phase1_parts_value = {
            "parts": [
                {
                    "part_code": "SAD",
                    "part_label": "单次给药递增",
                    "population": f"符合{ind or '适应症'}入排的健康受试者或轻症患者",
                    "cohort_dose": "起始剂量队列并按方案递增（具体剂量与爬坡规则医学确认）",
                    "pk_pd": "单次给药后密集PK采样；必要时PD标志物",
                    "safety": "剂量限制毒性与不良事件监测",
                    "stopping_rules": "出现DLT或SRC决定暂停/终止时停止递增",
                    "soa_summary": "筛选—给药日密集观察—安全性随访",
                    "transition_dependencies": "SRC审查通过后进入下一剂量或MAD",
                    "unresolved": False,
                },
                {
                    "part_code": "MAD",
                    "part_label": "多次给药递增",
                    "population": f"符合{ind or '适应症'}入排、完成或平行于SAD策略的受试者",
                    "cohort_dose": "多日/多周给药队列（具体剂量与频次医学确认）",
                    "pk_pd": "稳态PK与必要PD",
                    "safety": "累积暴露安全性监测",
                    "stopping_rules": "DLT/SRC门控",
                    "soa_summary": "筛选—多次给药期—安全性随访",
                    "transition_dependencies": "可与SAD序贯或有条件平行",
                    "unresolved": False,
                },
            ],
            "sequence": "sequential",
        }
        design_rdbpc = {
            "design.randomization": {"mode": "非随机"},
            "design.blinding": {"mode": "开放标签"},
            "design.comparator_type": {"type": "无对照/剂量递增", "intervention": ""},
            "design.assignment_model": {"model": "序贯/剂量递增队列"},
            "design.center_model": {"model": "单中心或有限中心"},
            "design.adaptive_design": {"enabled": False, "features": []},
            "design.src_dmc": {"src": True, "dmc": False},
            "design.interim_analysis": {"planned": False},
            "design.crossover": {"planned": False},
            "design.open_label_extension": {"planned": False},
            "design.sample_size_reestimation": {"planned": False},
            "design.treatment_switch": {"planned": False},
            "design.arms_or_cohorts": {
                "kind": "dose_cohorts",
                "labels": ["队列1", "队列2", "队列3"],
            },
            "design.phase1_parts": phase1_parts_value,
        }
        design_alt_open = {
            **design_rdbpc,
            "design.center_model": {"model": "多中心"},
            "design.src_dmc": {"src": True, "dmc": True},
        }
        design_alt_blind = {
            **design_rdbpc,
            "design.randomization": {"mode": "随机"},
            "design.blinding": {"mode": "单盲"},
            "design.comparator_type": {"type": "安慰剂", "intervention": "匹配安慰剂"},
            "design.assignment_model": {"model": "平行组"},
            "design.arms_or_cohorts": {
                "kind": "parallel_arms",
                "labels": ["试验药", "安慰剂"],
            },
        }
        design_rec_preview = f"设计推荐包A（早期开放剂量探索 · {phase or 'I期'}）"
        design_rec_rationale = (
            "早期常用：非随机开放、SAD+MAD、剂量队列、SRC；复杂设计默认不开展。"
        )
    else:
        design_rdbpc = {
            "design.randomization": {
                "mode": "随机",
                "stratification": "分层随机",
                "factors": ["研究中心", "基线疾病严重程度"],
            },
            "design.blinding": {"mode": "双盲"},
            "design.comparator_type": {"type": "安慰剂", "intervention": "匹配安慰剂"},
            "design.assignment_model": {"model": "平行组"},
            "design.center_model": {"model": "多中心"},
            "design.adaptive_design": {"enabled": False, "features": []},
            "design.src_dmc": {"src": False, "dmc": True},
            "design.interim_analysis": {"planned": False},
            "design.crossover": {"planned": False},
            "design.open_label_extension": {"planned": False},
            "design.sample_size_reestimation": {"planned": False},
            "design.treatment_switch": {"planned": False},
            "design.arms_or_cohorts": {
                "kind": "parallel_arms",
                "labels": ["试验药", "安慰剂"],
            },
        }
        design_alt_open = {
            **design_rdbpc,
            "design.blinding": {"mode": "开放标签"},
            "design.comparator_type": {
                "type": "活性对照",
                "intervention": "阳性对照药（具体品种与剂量待确认）",
            },
            "design.src_dmc": {"src": False, "dmc": True},
            "design.arms_or_cohorts": {
                "kind": "parallel_arms",
                "labels": ["试验药", "阳性对照"],
            },
        }
        design_alt_blind = {
            **design_rdbpc,
            "design.comparator_type": {
                "type": "活性对照",
                "intervention": "阳性对照药（具体品种与剂量待确认）",
            },
            "design.interim_analysis": {
                "planned": True,
                "purpose": "有效性/futility（边界待统计确认）",
                "independent_committee": "DMC",
            },
            "design.arms_or_cohorts": {
                "kind": "parallel_arms",
                "labels": ["试验药", "阳性对照"],
            },
        }
        design_rec_preview = f"设计推荐包A（分层随机双盲安慰剂平行 · {phase or 'II/III'}）"
        design_rec_rationale = (
            "II/III常用起点：分层随机RDBPC、多中心、设DMC；交叉/OLE/SSR/转换默认不开展。"
        )
    add(
        "package.design",
        [
            _module_candidate(
                field_path="package.design",
                target_paths=design_paths,
                structured_value=design_rdbpc,
                preview=design_rec_preview,
                rationale=design_rec_rationale,
                evidence=_identity_evidence,
                confidence="low",
                limitations=["正交设计事实须医学经理一键确认后才进入装配计划。"],
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["默认关闭复杂设计模块，需要时再改选。"],
                evidence_gaps=["需竞品Protocol确认盲法与对照匹配细节。"],
                suffix="pkg-design-primary",
            ),
            _module_candidate(
                field_path="package.design",
                target_paths=design_paths,
                structured_value=design_alt_open,
                preview=f"设计推荐包B（备选对照/开放 · {ind}）",
                rationale="备选设计骨架，供改选而非从零填写。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["活性对照/开放标签改变偏倚控制策略。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["更贴近真实世界或阳性药对照叙事。"],
                evidence_gaps=["需确认阳性药可及性与匹配给药。"],
                suffix="pkg-design-alt-b",
            ),
            _module_candidate(
                field_path="package.design",
                target_paths=design_paths,
                structured_value=design_alt_blind,
                preview=f"设计推荐包C（备选盲法/期中 · {ind}）",
                rationale="第三套设计骨架，覆盖期中或对照变体。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["期中分析边界必须统计确认。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["更强的期中/对照灵活性，操作更复杂。"],
                evidence_gaps=["需SAP与DMC章程对齐。"],
                suffix="pkg-design-alt-c",
            ),
        ],
    )

    # package.product — modality/route/exposure so assembly product facets clear.
    product_paths = [
        "framing.product_profile.technology_type",
        "framing.product_profile.administration_routes",
        "framing.product_profile.dosage_forms",
        "framing.product_profile.exposure_scope",
    ]
    product_biologic_sc = {
        "framing.product_profile.technology_type": "monoclonal_antibody",
        "framing.product_profile.administration_routes": ["皮下注射"],
        "framing.product_profile.dosage_forms": ["注射液"],
        "framing.product_profile.exposure_scope": "systemic",
    }
    product_small_oral = {
        "framing.product_profile.technology_type": "small_molecule",
        "framing.product_profile.administration_routes": ["口服"],
        "framing.product_profile.dosage_forms": ["片剂"],
        "framing.product_profile.exposure_scope": "systemic",
    }
    product_topical = {
        "framing.product_profile.technology_type": "other",
        "framing.product_profile.administration_routes": ["外用"],
        "framing.product_profile.dosage_forms": ["乳膏/软膏"],
        "framing.product_profile.exposure_scope": "local",
    }
    if any(token in ind for token in ("皮炎", "银屑病", "湿疹")):
        product_recommended = product_biologic_sc
        product_alt_b = product_topical
        product_alt_c = product_small_oral
        product_preview = f"产品画像推荐包A（生物制剂皮下 · {drug}）"
    elif any(token in ind for token in ("哮喘", "鼻窦", "COPD", "慢阻肺")):
        product_recommended = {
            "framing.product_profile.technology_type": "monoclonal_antibody",
            "framing.product_profile.administration_routes": ["皮下注射"],
            "framing.product_profile.dosage_forms": ["注射液"],
            "framing.product_profile.exposure_scope": "systemic",
        }
        product_alt_b = {
            "framing.product_profile.technology_type": "other",
            "framing.product_profile.administration_routes": ["吸入"],
            "framing.product_profile.dosage_forms": ["吸入剂"],
            "framing.product_profile.exposure_scope": "local",
        }
        product_alt_c = product_small_oral
        product_preview = f"产品画像推荐包A（生物制剂皮下 · {drug}）"
    else:
        product_recommended = product_biologic_sc
        product_alt_b = product_small_oral
        product_alt_c = product_topical
        product_preview = f"产品画像推荐包A（生物制剂皮下 · {drug}）"
    add(
        "package.product",
        [
            _module_candidate(
                field_path="package.product",
                target_paths=product_paths,
                structured_value=product_recommended,
                preview=product_preview,
                rationale="无IB时先用低置信产品画像骨架，解锁装配计划产品facet。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["真实modality/途径必须以IB或CMC为准。"],
                recommendation_role="recommended",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["错误modality会误导安全性与PK模块。"],
                evidence_gaps=["需IB确认技术类型与给药途径。"],
                suffix="pkg-product-primary",
            ),
            _module_candidate(
                field_path="package.product",
                target_paths=product_paths,
                structured_value=product_alt_b,
                preview=f"产品画像推荐包B（备选途径 · {ind}）",
                rationale="备选产品画像，便于改选而非空表。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["备选途径需与适应症给药习惯一致。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["途径改变影响安全性监测与PK。"],
                evidence_gaps=["需确认剂型与暴露范围。"],
                suffix="pkg-product-alt-b",
            ),
            _module_candidate(
                field_path="package.product",
                target_paths=product_paths,
                structured_value=product_alt_c,
                preview=f"产品画像推荐包C（第三备选 · {drug}）",
                rationale="第三套产品画像骨架。",
                evidence=_identity_evidence,
                confidence="low",
                limitations=["仅作启动候选。"],
                recommendation_role="alternative",
                adoption_mode="batch_allowed",
                clinical_tradeoffs=["与推荐包差异可能很大。"],
                evidence_gaps=["需IB确认。"],
                suffix="pkg-product-alt-c",
            ),
        ],
    )

    # Explicitly leave exact fact fields empty recommendations (no invented ready facts).
    blocked_exact = 0
    for exact_path in sorted(EXACT_FACT_PATHS):
        # Do not add ready candidates without evidence.
        blocked_exact += 1

    field_candidates = _enforce_deterministic_prefill_safety(field_candidates)

    # Progress: distinguish safe recommended fields from pending/manual fields.
    # Only fields whose recommended candidate has recommendation_role=recommended
    # (not pending_decision) and adoption_mode != batch_allowed count as
    # "directly adoptable recommendations". Pending fields count as blocked.
    directly_adoptable, pending_fields = _count_adoptable_and_pending_fields(
        field_candidates
    )

    total_fields = directly_adoptable + pending_fields + blocked_exact
    status: str
    if not field_candidates:
        status = "failed"
    elif partial_failures or blocked_exact or pending_fields:
        status = "partial"
    else:
        status = "ready"

    package_id = "mwprefill_" + payload_sha256(
        {
            "project_id": state.project_id,
            "journey_revision": state.revision,
            "input": journey_input_fingerprint(state),
        }
    )[:20]
    input_fp = journey_input_fingerprint(state)
    search_fp = search_fingerprint(state, snapshot)
    corpus_fp = state.corpus_gate.source_state_hash or ""
    progress = AuthoringPrefillProgress(
        total_fields=total_fields,
        fields_with_recommendation=directly_adoptable,
        fields_blocked_missing_evidence=blocked_exact + pending_fields,
        percent_complete=int(100 * directly_adoptable / total_fields) if total_fields else 0,
        stage="generated",
        message=(
            "基于创建最小事实与可用注册快照生成预填包；"
            "无证据时仅生成待决骨架，真实设计推荐由准入语料与独立AI生成。"
        ),
    )
    return AuthoringPrefillPackage(
        package_id=package_id,
        project_id=state.project_id,
        package_revision=1,
        journey_revision=state.revision,
        search_snapshot_id=(
            snapshot.snapshot_id
            if snapshot is not None
            else (state.search_plan.latest_snapshot_id if state.search_plan else "")
        ),
        corpus_source_hash=corpus_fp,
        status=status,  # type: ignore[arg-type]
        field_candidates=field_candidates,
        progress=progress,
        partial_source_failures=partial_failures,
        model_name=PREFILL_MODEL_NAME,
        prompt_version=PREFILL_PROMPT_VERSION,
        input_fingerprint=input_fp,
        search_fingerprint=search_fp,
        corpus_fingerprint=corpus_fp,
        source_fact_fingerprint=(
            definition.state_sha256 if definition is not None else input_fp
        ),
        generated_at=now,
        updated_at=now,
        generated_by=actor,
    )


_ACTIVE_COMPARATOR_REGIMEN_ID = "active_comparator_regimen"


def _materialize_active_comparator_ip_regimen(
    intervention_name: str,
    value: Any,
    *,
    picos_payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Upsert an active-comparator IP regimen into intervention_rules.

    Returns the updated ``intervention_rules`` payload dict, or None when
    no active-comparator regimen should exist (e.g. comparator type is not
    ``active``). The regimen carries ``product_role=active_comparator`` and
    receives ``dose_and_frequency``, ``route`` and ``treatment_period`` only
    from the explicit candidate map — never inferred from generic
    investigational-product ``intervention_dose_regimen``.
    """
    rules = dict(picos_payload.get("intervention_rules") or {})
    rules.setdefault("schema_version", "medical_writing_intervention_rules_v1")
    rules.setdefault("authority", "structured")
    rules["authority"] = "structured"

    regimens = [
        dict(r) for r in (rules.get("ip_regimens") or [])
    ]
    # Remove any existing active-comparator regimen (idempotent upsert).
    regimens = [
        r for r in regimens
        if r.get("product_role") != "active_comparator"
    ]

    regimen: dict[str, Any] = {
        "regimen_id": _ACTIVE_COMPARATOR_REGIMEN_ID,
        "product_name": (intervention_name or "").strip(),
        "product_role": "active_comparator",
        "dose_and_frequency": "",
        "route": "",
        "treatment_period": "",
        "adherence_notes": "",
        "source_location": "prefill:design.comparator_type",
    }
    if isinstance(value, dict):
        regimen["dose_and_frequency"] = str(
            value.get("dose_and_frequency") or ""
        ).strip()
        regimen["route"] = str(value.get("route") or "").strip()
        regimen["treatment_period"] = str(
            value.get("treatment_period") or ""
        ).strip()
    regimens.append(regimen)
    regimens.sort(key=lambda r: (r.get("product_role") or "", r.get("regimen_id") or ""))
    rules["ip_regimens"] = regimens
    return rules


def _clear_active_comparator_ip_regimen(
    *,
    picos_payload: dict[str, Any],
) -> dict[str, Any] | None:
    """Remove the active-comparator IP regimen and set authority=structured."""
    rules = dict(picos_payload.get("intervention_rules") or {})
    rules.setdefault("schema_version", "medical_writing_intervention_rules_v1")
    rules["authority"] = "structured"
    regimens = [
        dict(r) for r in (rules.get("ip_regimens") or [])
    ]
    filtered = [
        r for r in regimens
        if r.get("product_role") != "active_comparator"
    ]
    if len(filtered) != len(regimens) or not regimens:
        rules["ip_regimens"] = filtered
        return rules
    return rules


def _materialize_background_non_ip_rules(
    background_strings: list[str],
    *,
    picos_payload: dict[str, Any],
) -> dict[str, Any]:
    """Materialize required_background_rules as structured BACKGROUND rules.

    Each non-blank string becomes exactly one non-IP treatment rule with
    ``rule_class=background`` and a deterministic stable ID. The mapping is
    lossless — the original string is preserved verbatim as
    ``agent_or_category``. CM, rescue, dose-adjustment and other non-IP
    classes are never merged into background rules.
    """
    rules = dict(picos_payload.get("intervention_rules") or {})
    rules.setdefault("schema_version", "medical_writing_intervention_rules_v1")
    rules["authority"] = "structured"

    existing_non_ip = [
        dict(r) for r in (rules.get("non_ip_treatment_rules") or [])
    ]
    # Preserve non-background rules; replace background rules deterministically.
    preserved = [
        r for r in existing_non_ip
        if r.get("rule_class") != "background"
    ]
    background_rules: list[dict[str, Any]] = []
    for idx, text in enumerate(background_strings):
        text = (text or "").strip()
        if not text:
            continue
        background_rules.append({
            "rule_id": f"background_{idx + 1:03d}",
            "rule_class": "background",
            "policy": "allowed",
            "agent_or_category": text,
            "collection_window": "",
            "timing_restrictions": [],
            "washout_or_window": "",
            "cm_dose_rule": "",
            "phase_applicability": "",
            "exceptions": [],
            "source_location": "prefill:picos.required_background_rules",
            "notes": "",
        })
    all_non_ip = preserved + background_rules
    all_non_ip.sort(key=lambda r: (r.get("rule_class") or "", r.get("rule_id") or ""))
    rules["non_ip_treatment_rules"] = all_non_ip
    return rules


def _intervention_rules_to_legacy_projection(
    rules: dict[str, Any],
) -> dict[str, str | list[str]]:
    """Deterministic one-way projection from structured rules to legacy fields."""
    regimens = rules.get("ip_regimens") or []
    non_ip_rules = rules.get("non_ip_treatment_rules") or []

    regimen_parts: list[str] = []
    for regimen in regimens:
        if not regimen.get("regimen_id"):
            continue
        row = str(regimen.get("dose_and_frequency") or "").strip()
        name = str(regimen.get("product_name") or "").strip()
        if name:
            row = f"{name}：{row}" if row else name
        route = str(regimen.get("route") or "").strip()
        if route:
            row = f"{row}（{route}）" if row else f"（{route}）"
        period = str(regimen.get("treatment_period") or "").strip()
        if period:
            row = f"{row}；{period}" if row else period
        regimen_parts.append(row)

    background_labels: list[str] = []
    allowed_cm_labels: list[str] = []
    prohibited_cm_labels: list[str] = []
    for rule in non_ip_rules:
        if not rule.get("rule_id"):
            continue
        label = str(rule.get("agent_or_category") or rule.get("rule_id") or "").strip()
        rc = rule.get("rule_class")
        if rc == "background":
            background_labels.append(label)
        elif rc == "allowed_cm":
            allowed_cm_labels.append(label)
        elif rc == "prohibited_cm":
            prohibited_cm_labels.append(label)

    return {
        "intervention_dose_regimen": "\n".join(
            p for p in regimen_parts if p
        ).strip(),
        "required_background_rules": background_labels,
        "allowed_concomitant_rules": allowed_cm_labels,
        "prohibited_concomitant_rules": prohibited_cm_labels,
    }


def _assign_nested_update(
    updates: dict[str, Any],
    dotted_key: str,
    value: Any,
    baseline: dict[str, Any],
) -> None:
    """Assign a possibly nested dotted key into a top-level update dict."""
    parts = [part for part in dotted_key.split(".") if part]
    if not parts:
        return
    if len(parts) == 1:
        updates[parts[0]] = value
        return
    root = parts[0]
    merged = dict(updates.get(root) or baseline.get(root) or {})
    cursor = merged
    for part in parts[1:-1]:
        child = dict(cursor.get(part) or {})
        cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value
    updates[root] = merged


def _materialize_investigational_ip_regimen(
    *,
    dose_text: str,
    product_name: str,
    route: str,
    picos_payload: dict[str, Any],
) -> dict[str, Any]:
    """Upsert investigational-product regimen and default no-adjustment policy."""
    rules = dict(picos_payload.get("intervention_rules") or {})
    rules.setdefault("schema_version", "medical_writing_intervention_rules_v1")
    rules["authority"] = "structured"
    regimens = [dict(item) for item in (rules.get("ip_regimens") or [])]
    regimens = [
        item
        for item in regimens
        if item.get("product_role") != "investigational_product"
    ]
    regimens.append(
        {
            "regimen_id": "investigational_product_regimen",
            "product_name": (product_name or "").strip() or "试验药物",
            "product_role": "investigational_product",
            "dose_and_frequency": (dose_text or "").strip(),
            "route": (route or "").strip() or "待确认",
            "treatment_period": "按方案规定的治疗期（待确认）",
            "adherence_notes": "",
            "source_location": "prefill:picos.intervention_dose_regimen",
        }
    )
    regimens.sort(
        key=lambda item: (item.get("product_role") or "", item.get("regimen_id") or "")
    )
    rules["ip_regimens"] = regimens
    if rules.get("ip_adjustment_policy") in {None, "", "unspecified"}:
        rules["ip_adjustment_policy"] = "no_planned_adjustment"
        rules["no_planned_adjustment_statement"] = (
            "本方案不计划调整试验药物剂量；如需调整须经方案修订后执行"
            "（医学经理可采用后修订本默认）。"
        )
        rules["ip_action_rules"] = []
    return rules


def _materialize_placebo_ip_regimen(
    *,
    picos_payload: dict[str, Any],
    route: str = "",
) -> dict[str, Any]:
    """Upsert a matching placebo regimen for placebo-controlled designs."""
    rules = dict(picos_payload.get("intervention_rules") or {})
    rules.setdefault("schema_version", "medical_writing_intervention_rules_v1")
    rules["authority"] = "structured"
    regimens = [dict(item) for item in (rules.get("ip_regimens") or [])]
    regimens = [item for item in regimens if item.get("product_role") != "placebo"]
    ip_route = route
    if not ip_route:
        for item in regimens:
            if item.get("product_role") == "investigational_product":
                ip_route = str(item.get("route") or "").strip()
                break
    regimens.append(
        {
            "regimen_id": "placebo_regimen",
            "product_name": "匹配安慰剂",
            "product_role": "placebo",
            "dose_and_frequency": "与试验药物匹配的剂量与频次（待确认）",
            "route": ip_route or "与试验药物匹配（待确认）",
            "treatment_period": "与试验药物匹配的治疗期（待确认）",
            "adherence_notes": "",
            "source_location": "prefill:design.comparator_type",
        }
    )
    regimens.sort(
        key=lambda item: (item.get("product_role") or "", item.get("regimen_id") or "")
    )
    rules["ip_regimens"] = regimens
    return rules


def map_design_adoption_to_study_updates(
    field_path: str,
    value: Any,
    *,
    framing_payload: dict[str, Any],
    picos_payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Map orthogonal design.* adoption into framing/picos updates.

    Returns (framing_updates, picos_updates, changed_field_paths).
    """
    framing_updates: dict[str, Any] = {}
    picos_updates: dict[str, Any] = {}
    changed: list[str] = []

    if field_path.startswith("framing."):
        key = field_path.split(".", 1)[1]
        _assign_nested_update(framing_updates, key, value, framing_payload)
        changed.append(field_path)
        return framing_updates, picos_updates, changed
    if field_path.startswith("picos."):
        key = field_path.split(".", 1)[1]
        _assign_nested_update(picos_updates, key, value, picos_payload)
        changed.append(field_path)
        # Materialize required_background_rules as structured BACKGROUND
        # non-IP rules with stable deterministic IDs. This is the single
        # deterministic structured-authority path; the legacy string list
        # becomes a compatibility projection.
        if key == "required_background_rules":
            background_strings = (
                [str(s).strip() for s in value if str(s).strip()]
                if isinstance(value, list)
                else []
            )
            working_picos = {**picos_payload, **picos_updates}
            rules = _materialize_background_non_ip_rules(
                background_strings,
                picos_payload=working_picos,
            )
            picos_updates["intervention_rules"] = rules
            changed.append("picos.intervention_rules")
            # Sync the legacy compatibility projection.
            projection = _intervention_rules_to_legacy_projection(rules)
            if projection["required_background_rules"] != background_strings:
                picos_updates["required_background_rules"] = projection[
                    "required_background_rules"
                ]
        if key == "intervention_dose_regimen":
            working_picos = {**picos_payload, **picos_updates}
            profile = framing_payload.get("product_profile") or {}
            routes = list(profile.get("administration_routes") or [])
            rules = _materialize_investigational_ip_regimen(
                dose_text=str(value or ""),
                product_name=str(framing_payload.get("investigational_product") or ""),
                route=str(routes[0] if routes else ""),
                picos_payload=working_picos,
            )
            design = framing_payload.get("structured_design") or {}
            if design.get("comparator_type") == "placebo":
                rules = _materialize_placebo_ip_regimen(
                    picos_payload={**working_picos, "intervention_rules": rules},
                    route=str(routes[0] if routes else ""),
                )
            picos_updates["intervention_rules"] = rules
            changed.append("picos.intervention_rules")
        return framing_updates, picos_updates, changed

    current_design = str(framing_payload.get("design_pattern") or "")
    pieces = [part.strip() for part in re.split(r"[、,，]", current_design) if part.strip()]
    structured_design = dict(framing_payload.get("structured_design") or {})
    structured_design.setdefault(
        "schema_version", "medical_writing_structured_study_design_v1"
    )

    def ensure_piece(piece: str) -> None:
        if piece and piece not in pieces:
            pieces.append(piece)

    if field_path == "design.randomization":
        mode = value.get("mode") if isinstance(value, dict) else str(value)
        stratification = (
            str(value.get("stratification") or "").strip()
            if isinstance(value, dict)
            else ""
        )
        factors = (
            [str(item).strip() for item in (value.get("factors") or []) if str(item).strip()]
            if isinstance(value, dict)
            else []
        )
        detail_bits = []
        if stratification:
            detail_bits.append(stratification)
        if factors:
            detail_bits.append("分层因素：" + "、".join(factors))
        if mode in {"随机", "随机分配", "随机化"}:
            structured_design["randomization_mode"] = "randomized"
            ensure_piece("随机")
            if stratification:
                ensure_piece(stratification)
            if detail_bits:
                structured_design["randomization_details"] = "；".join(detail_bits)
            if picos_payload.get("design_archetype") in {"", "single_arm_early_phase"}:
                picos_updates["design_archetype"] = "randomized_exploratory"
                changed.append("picos.design_archetype")
        elif mode in {"非随机", "非随机分配"}:
            structured_design["randomization_mode"] = "non_randomized"
            pieces = [p for p in pieces if p != "随机"]
            ensure_piece("非随机" if "非随机" not in pieces else "")
            if detail_bits:
                structured_design["randomization_details"] = "；".join(detail_bits)
            if not picos_payload.get("design_archetype"):
                picos_updates["design_archetype"] = "single_arm_early_phase"
                changed.append("picos.design_archetype")
        else:
            structured_design["randomization_mode"] = "other"
            structured_design["randomization_details"] = str(mode or "").strip()
            if detail_bits:
                structured_design["randomization_details"] = "；".join(
                    [structured_design["randomization_details"], *detail_bits]
                ).strip("；")
    elif field_path == "design.blinding":
        mode = value.get("mode") if isinstance(value, dict) else str(value)
        for token in ("双盲", "单盲", "开放标签"):
            pieces = [p for p in pieces if p != token]
        ensure_piece(str(mode))
        structured_design["blinding_mode"] = {
            "开放标签": "open_label",
            "单盲": "single_blind",
            "双盲": "double_blind",
            "三盲": "triple_blind",
        }.get(str(mode), "other")
        structured_design["blinded_roles"] = (
            list(value.get("blinded_roles") or [])
            if isinstance(value, dict)
            else []
        )
        if structured_design["blinding_mode"] == "other":
            structured_design["blinding_details"] = str(mode or "").strip()
    elif field_path == "design.comparator_type":
        ctype = value.get("type") if isinstance(value, dict) else str(value)
        intervention = (
            str(value.get("intervention") or "").strip()
            if isinstance(value, dict)
            else ""
        )
        for token in ("安慰剂对照", "活性对照", "无对照/剂量递增"):
            pieces = [p for p in pieces if p != token]
        if ctype == "安慰剂":
            structured_design["comparator_type"] = "placebo"
            ensure_piece("安慰剂对照")
            picos_updates["comparator_summary"] = (
                intervention or "匹配安慰剂（具体制剂待确认）。"
            )
            changed.append("picos.comparator_summary")
            # Active comparator is no longer selected — remove any existing
            # active-comparator IP regimen deterministically.
            cleared = _clear_active_comparator_ip_regimen(
                picos_payload=picos_payload,
            )
            working = dict(picos_payload)
            if cleared is not None:
                working["intervention_rules"] = cleared
                picos_updates["intervention_rules"] = cleared
                changed.append("picos.intervention_rules")
            profile = framing_payload.get("product_profile") or {}
            routes = list(profile.get("administration_routes") or [])
            picos_updates["intervention_rules"] = _materialize_placebo_ip_regimen(
                picos_payload=working,
                route=str(routes[0] if routes else ""),
            )
            changed.append("picos.intervention_rules")
        elif ctype == "活性对照":
            structured_design["comparator_type"] = "active"
            ensure_piece("活性对照")
            picos_updates["comparator_summary"] = (
                intervention or "活性对照（具体药物待确认）。"
            )
            changed.append("picos.comparator_summary")
            # Materialize an active-comparator IP regimen. Details come
            # only from the explicit candidate map, never inferred from
            # generic investigational-product intervention_dose_regimen.
            rules = _materialize_active_comparator_ip_regimen(
                intervention,
                value,
                picos_payload=picos_payload,
            )
            picos_updates["intervention_rules"] = rules
            changed.append("picos.intervention_rules")
        elif ctype in {"无对照/剂量递增", "无对照", "剂量递增"}:
            structured_design["comparator_type"] = "none_or_dose_escalation"
            ensure_piece("无对照/剂量递增")
            picos_updates["comparator_summary"] = "无平行对照（剂量递增/自身对照框架）。"
            changed.append("picos.comparator_summary")
            cleared = _clear_active_comparator_ip_regimen(
                picos_payload=picos_payload,
            )
            if cleared is not None:
                regimens = [
                    item
                    for item in (cleared.get("ip_regimens") or [])
                    if item.get("product_role") != "placebo"
                ]
                cleared = dict(cleared)
                cleared["ip_regimens"] = regimens
                picos_updates["intervention_rules"] = cleared
                changed.append("picos.intervention_rules")
        else:
            structured_design["comparator_type"] = "other"
            picos_updates["comparator_summary"] = intervention or str(ctype or "").strip()
            changed.append("picos.comparator_summary")
            cleared = _clear_active_comparator_ip_regimen(
                picos_payload=picos_payload,
            )
            if cleared is not None:
                picos_updates["intervention_rules"] = cleared
                changed.append("picos.intervention_rules")
        structured_design["comparator_intervention"] = intervention
    elif field_path == "design.assignment_model":
        model = value.get("model") if isinstance(value, dict) else str(value)
        for token in ("平行组", "交叉", "序贯/剂量递增队列", "平行分组"):
            pieces = [p for p in pieces if p != token]
        ensure_piece(str(model))
        structured_design["assignment_model"] = str(model or "").strip()
    elif field_path == "design.center_model":
        model = value.get("model") if isinstance(value, dict) else str(value)
        for token in ("多中心", "单中心", "单中心或有限中心"):
            pieces = [p for p in pieces if p != token]
        ensure_piece(str(model))
        structured_design["center_model"] = str(model or "").strip()
    elif field_path == "design.phase1_parts":
        parts = value.get("parts") if isinstance(value, dict) else value
        if isinstance(parts, list) and parts:
            # Prefer full typed Part objects when population/cohort provided;
            # otherwise fall back to part_code migration (unresolved=True).
            typed_parts: list[Any] = []
            part_codes: list[str] = []
            for item in parts:
                if isinstance(item, dict) and item.get("part_code"):
                    code = str(item.get("part_code") or "").strip()
                    part_codes.append(code)
                    if str(item.get("population") or "").strip() and str(
                        item.get("cohort_dose") or ""
                    ).strip():
                        typed_parts.append(
                            {
                                "part_code": code,
                                "part_label": str(item.get("part_label") or code),
                                "population": str(item.get("population") or ""),
                                "cohort_dose": str(item.get("cohort_dose") or ""),
                                "pk_pd": str(item.get("pk_pd") or ""),
                                "safety": str(item.get("safety") or ""),
                                "stopping_rules": str(item.get("stopping_rules") or ""),
                                "soa_summary": str(item.get("soa_summary") or ""),
                                "transition_dependencies": str(
                                    item.get("transition_dependencies") or ""
                                ),
                                "unresolved": False,
                            }
                        )
                elif isinstance(item, str):
                    part_codes.append(item.strip())
            structured_design["phase1_parts"] = typed_parts or part_codes
            structured_design["phase1_sequence"] = (
                str(value.get("sequence") or "").strip()
                if isinstance(value, dict)
                else ""
            )
            part_text = "、".join(part_codes)
            ensure_piece(f"含{part_text}模块")
            objectives = list(framing_payload.get("intrinsic_objectives") or [])
            for part_code in part_codes:
                label = f"{part_code}模块"
                if label not in objectives:
                    objectives.append(label)
            framing_updates["intrinsic_objectives"] = objectives
            changed.append("framing.intrinsic_objectives")
            picos_updates["design_archetype"] = "single_arm_early_phase"
            changed.append("picos.design_archetype")
    elif field_path == "design.arms_or_cohorts":
        labels = value.get("labels") if isinstance(value, dict) else []
        kind = value.get("kind") if isinstance(value, dict) else ""
        structured_design["arm_or_cohort_kind"] = str(kind or "").strip()
        structured_design["arm_or_cohort_labels"] = list(labels or [])
        if kind == "dose_cohorts":
            ensure_piece("剂量递增队列")
        elif kind == "parallel_arms" and labels:
            ensure_piece("平行组")
    elif field_path == "design.adaptive_design":
        enabled = bool(value.get("enabled")) if isinstance(value, dict) else bool(value)
        existing_adaptive = dict(structured_design.get("adaptive_design") or {})
        existing_adaptive["planned"] = enabled
        existing_adaptive["adaptable_elements"] = (
            list(value.get("features") or [])
            if isinstance(value, dict) and enabled
            else []
        )
        structured_design["adaptive_design"] = existing_adaptive
        structured_design.pop("adaptive_design_enabled", None)
        structured_design.pop("adaptive_features", None)
        if enabled:
            ensure_piece("适应性设计")
        else:
            pieces = [p for p in pieces if p != "适应性设计"]
    elif field_path == "design.src_dmc":
        if isinstance(value, dict):
            structured_design["src_planned"] = bool(value.get("src"))
            structured_design["dmc_planned"] = bool(value.get("dmc"))
            if value.get("src"):
                ensure_piece("设SRC")
            if value.get("dmc"):
                ensure_piece("设DMC")
    elif field_path == "design.interim_analysis":
        planned = bool(value.get("planned")) if isinstance(value, dict) else bool(value)
        existing_interim = dict(structured_design.get("interim_analysis") or {})
        existing_interim["planned"] = planned
        if isinstance(value, dict):
            for key in (
                "purpose",
                "timing",
                "information_fraction",
                "statistical_boundary",
                "alpha_control",
                "independent_committee",
                "operational_firewall",
                "notes",
            ):
                if key in value:
                    existing_interim[key] = value.get(key)
        structured_design["interim_analysis"] = existing_interim
        if planned:
            ensure_piece("计划期中分析")
        else:
            pieces = [p for p in pieces if p != "计划期中分析"]
    elif field_path in {
        "design.crossover",
        "design.open_label_extension",
        "design.sample_size_reestimation",
        "design.treatment_switch",
    }:
        nested_key = {
            "design.crossover": "crossover",
            "design.open_label_extension": "open_label_extension",
            "design.sample_size_reestimation": "sample_size_reestimation",
            "design.treatment_switch": "treatment_switch",
        }[field_path]
        existing = dict(structured_design.get(nested_key) or {})
        if isinstance(value, dict):
            if "planned" in value:
                existing["planned"] = bool(value.get("planned"))
            for nested_field, nested_value in value.items():
                if nested_field == "planned":
                    continue
                existing[nested_field] = nested_value
        else:
            existing["planned"] = bool(value)
        structured_design[nested_key] = existing
    else:
        raise ValueError(f"unsupported prefill adopt path: {field_path}")

    composed = "、".join(p for p in pieces if p)
    if structured_design != (framing_payload.get("structured_design") or {}):
        framing_updates["structured_design"] = structured_design
        changed.append("framing.structured_design")
    if composed != current_design:
        framing_updates["design_pattern"] = composed
        changed.append("framing.design_pattern")
    return framing_updates, picos_updates, changed


def get_path_value(framing: Any, picos: Any, field_path: str) -> Any:
    if field_path.startswith("framing."):
        return getattr(framing, field_path.split(".", 1)[1], None)
    if field_path.startswith("picos."):
        return getattr(picos, field_path.split(".", 1)[1], None)
    return None


def _confirmed_candidate_is_current(
    state: MedicalWritingAuthoringJourney,
    candidate: AuthoringPrefillCandidate,
) -> bool:
    """Return whether a previously confirmed value is still a project fact."""
    framing, picos = effective_authoring_values(state)
    field_path = candidate.field_path
    if field_path.startswith(("framing.", "picos.")):
        current_value = get_path_value(framing, picos, field_path)
        return not values_materially_distinct(
            current_value,
            candidate.structured_value,
        )

    framing_payload = framing.model_dump(mode="json")
    picos_payload = picos.model_dump(mode="json")
    try:
        framing_updates, picos_updates, _ = map_design_adoption_to_study_updates(
            field_path,
            candidate.structured_value,
            framing_payload=framing_payload,
            picos_payload=picos_payload,
        )
    except ValueError:
        return False
    return all(
        not values_materially_distinct(framing_payload.get(key), value)
        for key, value in framing_updates.items()
    ) and all(
        not values_materially_distinct(picos_payload.get(key), value)
        for key, value in picos_updates.items()
    )


def preserve_current_user_confirmations(
    *,
    package: AuthoringPrefillPackage,
    previous_package: AuthoringPrefillPackage | None,
    state: MedicalWritingAuthoringJourney,
) -> AuthoringPrefillPackage:
    """Carry forward confirmations only while their values remain current.

    Regeneration may change candidate identifiers and ranking, but it must not
    turn a value already adopted by the user back into an AI proposal.
    """
    if previous_package is None:
        return package

    updated_groups = dict(package.field_candidates)
    changed = False
    for field_path, group in package.field_candidates.items():
        previous_group = previous_package.field_candidates.get(field_path)
        if previous_group is None:
            continue
        previous_confirmed = next(
            (
                candidate
                for candidate in previous_group.candidates
                if candidate.state == "user_confirmed"
            ),
            None,
        )
        if previous_confirmed is None or not _confirmed_candidate_is_current(
            state,
            previous_confirmed,
        ):
            continue

        matching_index = next(
            (
                index
                for index, candidate in enumerate(group.candidates)
                if not values_materially_distinct(
                    candidate.structured_value,
                    previous_confirmed.structured_value,
                )
            ),
            None,
        )
        candidates = [
            candidate.model_copy(
                update={
                    "state": (
                        "superseded"
                        if candidate.state == "user_confirmed"
                        else candidate.state
                    )
                },
                deep=True,
            )
            for candidate in group.candidates
        ]
        if matching_index is None:
            confirmed = previous_confirmed.model_copy(
                update={"state": "user_confirmed"},
                deep=True,
            )
            candidates = [confirmed, *candidates][:5]
            confirmed_id = confirmed.candidate_id
        else:
            confirmed = candidates[matching_index].model_copy(
                update={"state": "user_confirmed"},
                deep=True,
            )
            candidates[matching_index] = confirmed
            confirmed_id = confirmed.candidate_id
        updated_groups[field_path] = group.model_copy(
            update={
                "recommended_candidate_id": confirmed_id,
                "candidates": candidates,
            },
            deep=True,
        )
        changed = True

    if not changed:
        return package
    return package.model_copy(
        update={"field_candidates": updated_groups},
        deep=True,
    )


def lock_confirmed_synopsis_values(
    *,
    package: AuthoringPrefillPackage,
    state: MedicalWritingAuthoringJourney,
) -> AuthoringPrefillPackage:
    """Keep one-click confirmed synopsis facts authoritative in AI prefill.

    The AI may propose genuinely missing facts, but it must not present a
    conflicting title, randomization, blinding, comparator, or other extracted
    field as the recommended option after the medical manager confirmed the
    imported synopsis.
    """
    imported = state.synopsis_import
    if (
        imported is None
        or imported.status != "confirmed"
        or imported.source is None
    ):
        return package
    framing, picos = effective_authoring_values(state)
    spans = {span.span_id: span for span in imported.evidence_spans}

    def evidence_refs(paths: list[str]) -> list[AuthoringPrefillEvidenceRef]:
        refs: list[AuthoringPrefillEvidenceRef] = []
        seen: set[str] = set()
        for path in paths:
            for span_id in imported.field_evidence_span_ids.get(path, []):
                if span_id in seen:
                    continue
                span = spans.get(span_id)
                if span is None:
                    continue
                seen.add(span_id)
                refs.append(
                    _evidence(
                        source_kind="synopsis",
                        source_id=span.source_id,
                        source_text=span.source_text[:5_000],
                        locator=span.locator,
                    )
                )
                if len(refs) >= 20:
                    return refs
        return refs

    locked_values: dict[str, tuple[Any, str, list[str]]] = {}
    for field_path in package.field_candidates:
        if field_path.startswith("framing."):
            field_name = field_path.split(".", 1)[1]
            value = getattr(framing, field_name, None)
        elif field_path.startswith("picos."):
            field_name = field_path.split(".", 1)[1]
            value = getattr(picos, field_name, None)
        else:
            continue
        extracted_hash = imported.field_extracted_value_sha256.get(field_path)
        if not extracted_hash or extracted_hash != payload_sha256(value):
            continue
        refs = evidence_refs([field_path])
        if not refs:
            continue
        preview = (
            "；".join(str(item) for item in value)
            if isinstance(value, list)
            else str(value)
        )
        locked_values[field_path] = (value, preview, [field_path])

    design = framing.structured_design
    design_values: dict[str, tuple[Any, str, list[str]]] = {}
    if design.randomization_mode != "undecided":
        label = {
            "randomized": "随机",
            "non_randomized": "非随机",
            "other": design.randomization_details or "其他",
        }[design.randomization_mode]
        rand_value: dict[str, Any] = {"mode": label}
        details = str(design.randomization_details or "").strip()
        if details:
            rand_value["stratification"] = details
            if "分层" in details:
                # Keep factors text inside details; UI shows clinical preview.
                rand_value.setdefault("factors", [])
        design_values["design.randomization"] = (
            rand_value,
            f"{label}（{details}）" if details else label,
            [
                "framing.structured_design.randomization_mode",
                "framing.structured_design.randomization_details",
                "framing.structured_design",
                "framing.design_pattern",
            ],
        )
    if design.blinding_mode != "undecided":
        label = {
            "open_label": "开放标签",
            "single_blind": "单盲",
            "double_blind": "双盲",
            "triple_blind": "三盲",
            "other": design.blinding_details or "其他",
        }[design.blinding_mode]
        design_values["design.blinding"] = (
            {"mode": label, "blinded_roles": list(design.blinded_roles)},
            label,
            [
                "framing.structured_design.blinding_mode",
                "framing.structured_design",
                "framing.design_pattern",
            ],
        )
    if design.comparator_type != "undecided":
        label = {
            "placebo": "安慰剂",
            "active": "活性对照",
            "none_or_dose_escalation": "无对照/剂量递增",
            "other": "其他",
        }[design.comparator_type]
        design_values["design.comparator_type"] = (
            {
                "type": label,
                "intervention": design.comparator_intervention,
            },
            (
                f"{label}：{design.comparator_intervention}"
                if design.comparator_intervention
                else label
            ),
            [
                "framing.structured_design.comparator_type",
                "framing.structured_design.comparator_intervention",
                "framing.structured_design",
                "picos.comparator_summary",
                "framing.design_pattern",
            ],
        )
    if design.assignment_model:
        design_values["design.assignment_model"] = (
            {"model": design.assignment_model},
            design.assignment_model,
            [
                "framing.structured_design.assignment_model",
                "framing.structured_design",
                "framing.design_pattern",
            ],
        )
    if design.center_model:
        design_values["design.center_model"] = (
            {"model": design.center_model},
            design.center_model,
            [
                "framing.structured_design.center_model",
                "framing.structured_design",
                "framing.design_pattern",
            ],
        )
    for field_path, (value, preview, paths) in design_values.items():
        if field_path not in package.field_candidates:
            continue
        refs = evidence_refs(paths)
        if refs:
            locked_values[field_path] = (value, preview, paths)

    if not locked_values:
        return package
    updated_groups = dict(package.field_candidates)
    for field_path, (value, preview, paths) in locked_values.items():
        refs = evidence_refs(paths)
        digest = payload_sha256(
            {
                "field_path": field_path,
                "value": value,
                "source_id": imported.source.source_id,
            }
        )[:16]
        candidate = AuthoringPrefillCandidate(
            candidate_id=f"mwsynopsisconfirmed_{digest}",
            field_path=field_path,
            structured_value=value,
            preview=preview[:5_000],
            evidence_refs=refs,
            rationale="该内容已在方案摘要确认时由医学经理采用。",
            limitations=[],
            confidence="high",
            state="user_confirmed",
        )
        updated_groups[field_path] = AuthoringPrefillFieldCandidates(
            field_path=field_path,
            recommended_candidate_id=candidate.candidate_id,
            candidates=[candidate],
        )
    return package.model_copy(update={"field_candidates": updated_groups}, deep=True)


def validate_candidate_for_ready_exact_fact(candidate: AuthoringPrefillCandidate) -> None:
    if candidate.field_path in EXACT_FACT_PATHS and not candidate.evidence_refs:
        raise ValueError(
            f"exact clinical field {candidate.field_path} cannot be recommended without evidence"
        )


# ---------------------------------------------------------------------------
# W3: Composite adoption planner (pure, no I/O).
#
# plan_composite_adoption takes the server-authoritative candidate, user
# path_overrides, current framing/picos payloads, and an optional W2b
# evidence verifier. It produces an immutable plan describing exactly which
# paths are applied, overridden, derived, skipped, and why. Any conflict or
# evidence-gate failure raises ValueError before persistence.
# ---------------------------------------------------------------------------


# Paths that composite candidates may target.
# Exact clinical facts may appear as structured keys for review, but are only
# applied when evidence-bound or explicitly overridden by the user.
COMPOSITE_PACKAGE_STRUCTURE_PATHS: frozenset[str] = frozenset(
    {
        "picos.assessment_instruments",
    }
)
COMPOSITE_ADOPTABLE_PATHS: frozenset[str] = (
    SUPPORTED_ADOPT_PATHS | EXACT_FACT_PATHS | COMPOSITE_PACKAGE_STRUCTURE_PATHS
)


def is_deterministic_lazy_recommendation(
    candidate: AuthoringPrefillCandidate,
    package: AuthoringPrefillPackage,
) -> bool:
    """True when an unbound recommendation may be one-click adopted.

    Lazy medical writers need filled defaults. Clicking adopt is the user
    confirmation for non-exact paths. Exact facts remain gated separately.

    AI enrichers may rewrite ``package.model_name`` / phrasing without attaching
    claim bindings; those unbound recommended/alternative candidates must still
    be adoptable, otherwise the production path traps users on blank forms.
    """
    if candidate.recommendation_role not in {"recommended", "alternative"}:
        return False
    # Bound AI claims must go through the evidence verifier.
    if candidate.claim_bindings:
        return False
    # Candidate-level AI run with bindings would be handled above; a bare
    # ai_run_id without bindings is still user-confirmable skeleton text.
    return True


class EvidencePathVerifier(Protocol):
    """W2b server-side evidence verification interface.

    verify_candidate_path returns True when the candidate path's AI-origin
    binding is server-verified against the persisted evidence catalog.
    """

    def verify_candidate_path(
        self,
        *,
        project_id: str,
        package: AuthoringPrefillPackage,
        candidate: AuthoringPrefillCandidate,
        target_path: str,
        proposed_value: Any,
    ) -> bool: ...


class ServerEvidenceVerifier:
    """Server-side evidence verifier that re-validates candidate bindings
    using the exact W2b validation logic from
    ``medical_writing_authoring_prefill_evidence_binding``.

    This verifier does NOT implement its own weakened rules. It delegates
    to ``server_validate_single_binding``, ``server_validate_value_pointer``,
    and ``server_all_atomic_values_bound`` — the same functions used during
    AI candidate generation.

    The verifier is constructed with a lazy ``catalog_resolver`` that, when
    called, rebuilds the live server catalog from the current journey and
    writing-reference snapshot. This ensures source drift between the
    package's persisted catalog and the current project state is detected.
    """

    def __init__(
        self,
        *,
        catalog_resolver=None,
    ):
        """``catalog_resolver`` is a zero-argument callable that returns
        an ``AuthoringPrefillEvidenceCatalog`` built from the current
        journey + repository snapshot, or None if no catalog can be built.

        If catalog_resolver is None, the verifier uses the package's
        persisted catalog (backward-compatible, but does not detect
        source drift).
        """
        self._catalog_resolver = catalog_resolver
        self._cached_catalog = None
        self._catalog_resolved = False
        self._catalog_resolution_error: Exception | None = None

    def _resolve_catalog(
        self,
        package: AuthoringPrefillPackage,
    ) -> AuthoringPrefillEvidenceCatalog | None:
        """Resolve the authoritative server catalog.

        If a catalog_resolver was provided, call it once (lazy) to get the
        live server catalog. Otherwise fall back to the package's persisted
        catalog.
        """
        if self._catalog_resolved:
            return self._cached_catalog
        self._catalog_resolved = True
        if self._catalog_resolver is not None:
            try:
                self._cached_catalog = self._catalog_resolver()
            except Exception as exc:
                self._cached_catalog = None
                self._catalog_resolution_error = exc
        else:
            self._cached_catalog = package.evidence_catalog
        return self._cached_catalog

    def verify_candidate_path(
        self,
        *,
        project_id: str,
        package: AuthoringPrefillPackage,
        candidate: AuthoringPrefillCandidate,
        target_path: str,
        proposed_value: Any,
    ) -> bool:
        from .medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
            server_validate_single_binding,
            server_all_atomic_values_bound,
        )

        catalog = self._resolve_catalog(package)
        if catalog is None:
            if (
                self._catalog_resolver is not None
                and self._catalog_resolution_error is not None
            ):
                # Fail closed, but with the resolver's precise diagnosis
                # (stale package revision, missing snapshot, identity drift,
                # draft-diverged catalog) instead of a generic "binding
                # rejected" message — the caller must be able to distinguish
                # a recoverable state from tampering.
                raise ValueError(
                    f"live evidence catalog resolution failed: "
                    f"{self._catalog_resolution_error}"
                ) from self._catalog_resolution_error
            return False

        persisted_catalog = package.evidence_catalog
        if persisted_catalog is None:
            return False

        # A repository-backed verifier must prove that the package, persisted
        # catalog, and freshly rebuilt catalog describe the same immutable
        # evidence view. The no-resolver mode remains a bounded service-test
        # adapter that validates against the package catalog itself.
        if self._catalog_resolver is not None:
            if package.project_id != project_id:
                return False
            if (
                persisted_catalog.project_id != project_id
                or catalog.project_id != project_id
            ):
                return False
            if package.journey_revision != persisted_catalog.journey_revision:
                return False
            if package.journey_revision != catalog.journey_revision:
                return False
            if package.search_snapshot_id != persisted_catalog.snapshot_id:
                return False
            if package.search_snapshot_id != catalog.snapshot_id:
                return False
            if (
                persisted_catalog.model_dump(mode="json")
                != catalog.model_dump(mode="json")
            ):
                return False

        # Catalog identity must match between candidate, persisted package,
        # and the live catalog.
        if candidate.evidence_catalog_id != persisted_catalog.catalog_id:
            return False
        if candidate.evidence_catalog_sha256 != persisted_catalog.catalog_sha256:
            return False
        if candidate.evidence_catalog_id != catalog.catalog_id:
            return False
        if candidate.evidence_catalog_sha256 != catalog.catalog_sha256:
            return False

        # Recompute catalog hash from live entries and verify.
        from .medical_writing_authoring_prefill_evidence import _catalog_sha256
        recomputed_hash = _catalog_sha256(
            catalog.project_id,
            catalog.journey_revision,
            catalog.snapshot_id,
            catalog.entries,
        )
        if recomputed_hash != catalog.catalog_sha256:
            return False

        # Build entry lookup and sent_entry_ids from the live catalog.
        entry_lookup = {
            e.catalog_entry_id: e for e in catalog.entries
        }
        sent_entry_ids = set(entry_lookup.keys())

        # Round-1 corpus entries marked insufficient_support_do_not_generalize
        # force recommendation_role=pending_decision: a persisted candidate
        # that was promoted to recommended/alternative must never be
        # adoptable (same rule as generation-side validation).
        from .medical_writing_authoring_prefill_evidence_binding import (
            server_candidate_requires_pending_decision,
        )

        if server_candidate_requires_pending_decision(candidate, entry_lookup):
            if (
                str(candidate.recommendation_role or "").strip()
                != "pending_decision"
            ):
                return False

        # Find bindings for this target_path.
        bindings_for_path = [
            b for b in candidate.claim_bindings if b.target_path == target_path
        ]
        if not bindings_for_path:
            return False

        is_package = candidate.candidate_scope in ("module", "design_package")

        # Field-scope candidates carry no target_paths (the model clears the
        # list for ``field`` scope) yet their bindings reference the field
        # itself.  Use the candidate's own field path so single-candidate
        # adoption can live-verify field candidates with the same W2b logic
        # as composite/package candidates.
        if is_package:
            candidate_target_paths = set(candidate.target_paths)
        else:
            candidate_target_paths = {candidate.field_path}

        # Validate each binding using the exact W2b validation logic.
        for binding in bindings_for_path:
            try:
                rebound = server_validate_single_binding(
                    binding=binding,
                    entry_lookup=entry_lookup,
                    sent_entry_ids=sent_entry_ids,
                    candidate_target_paths=candidate_target_paths,
                    structured_value=candidate.structured_value,
                    is_package=is_package,
                )
                # After server rebind, verify the candidate's stored
                # binding values match the server-rebound values. This
                # detects post-persistence tampering.
                if (
                    rebound.source_id != binding.source_id
                    or rebound.locator != binding.locator
                    or rebound.quote_sha256 != binding.quote_sha256
                ):
                    return False
            except EvidenceValidationError:
                return False

        # Check that ALL non-empty atomic leaves under this target_path
        # in the structured_value are covered by bindings.
        if is_package and isinstance(candidate.structured_value, dict):
            if not server_all_atomic_values_bound(
                candidate.structured_value,
                bindings_for_path,
                [target_path],
                is_package=True,
            ):
                return False

        return True


class CompositeAdoptionPlan:
    """Immutable result of planning a composite adoption."""

    __slots__ = (
        "applied_candidate_paths",
        "applied_override_paths",
        "derived_paths",
        "skipped_paths",
        "framing_updates",
        "picos_updates",
        "all_changed_paths",
        "value_changed_paths",
        "resolution_changed_paths",
        "candidate_fully_applied",
        "impacted",
        "path_origins",
    )

    def __init__(
        self,
        *,
        applied_candidate_paths: list[str],
        applied_override_paths: list[str],
        derived_paths: list[str],
        skipped_paths: list[tuple[str, str]],
        framing_updates: dict[str, Any],
        picos_updates: dict[str, Any],
        all_changed_paths: list[str],
        value_changed_paths: list[str],
        resolution_changed_paths: list[str],
        candidate_fully_applied: bool,
        impacted: list[str],
        path_origins: dict[str, str] | None = None,
    ):
        self.applied_candidate_paths = sorted(applied_candidate_paths)
        self.applied_override_paths = sorted(applied_override_paths)
        self.derived_paths = sorted(derived_paths)
        self.skipped_paths = sorted(skipped_paths)
        self.framing_updates = dict(framing_updates)
        self.picos_updates = dict(picos_updates)
        self.all_changed_paths = sorted(all_changed_paths)
        self.value_changed_paths = sorted(value_changed_paths)
        self.resolution_changed_paths = sorted(resolution_changed_paths)
        self.candidate_fully_applied = candidate_fully_applied
        self.impacted = sorted(impacted)
        self.path_origins = dict(path_origins) if path_origins else {}


class MedicalWritingAuthoringPolicyError(ValueError):
    """Raised when a request is structurally valid but violates an
    adoption-safety policy (pending_decision / manual_only / insufficient /
    unsupported-substantive-gap without the required per-path override or
    skip).

    Carries a stable ``code`` (``POLICY_REJECTED``) plus a stable ``reason``
    so API layers can differentiate policy rejections from revision/state
    conflicts: policy rejection must never be presented as a concurrency
    conflict.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "POLICY_REJECTED",
        reason: str = "",
    ):
        super().__init__(message)
        self.code = code
        self.reason = reason


# Stable per-attribute policy reasons for the composite per-path gate.
_POLICY_REASON_LABELS: dict[str, str] = {
    "candidate_pending_decision": "pending_decision",
    "candidate_manual_only": "manual_only",
    "candidate_insufficient_evidence": "evidence_status=insufficient",
    "candidate_unsupported_evidence_gap": "unsupported-substantive-evidence-gap",
}


def _composite_path_policy_restricted(
    candidate: AuthoringPrefillCandidate,
) -> tuple[bool, str]:
    """Return ``(restricted, reason)`` for the composite per-path gate.

    A composite candidate contributes every target_path as an AI-origin
    claim, so it mirrors the single-candidate gate: a ``pending_decision``
    role, ``manual_only`` adoption mode, ``insufficient`` evidence status,
    or an unsupported-substantive evidence gap all require an explicit
    per-path override or skip before any candidate value may be applied.
    ``batch_allowed`` candidates that are supported and gap-free remain
    adoptable after server evidence verification.
    """
    role = str(candidate.recommendation_role or "").strip()
    if role == "pending_decision":
        return True, "candidate_pending_decision"
    if str(candidate.adoption_mode or "").strip() == "manual_only":
        return True, "candidate_manual_only"
    if str(candidate.evidence_status or "").strip() == "insufficient":
        return True, "candidate_insufficient_evidence"
    from .medical_writing_authoring_prefill_ai import (
        _UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX,
    )

    if any(
        str(gap).startswith(_UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX)
        for gap in (candidate.evidence_gaps or [])
    ):
        return True, "candidate_unsupported_evidence_gap"
    return False, ""


def plan_composite_adoption(
    *,
    project_id: str,
    candidate: AuthoringPrefillCandidate,
    package: AuthoringPrefillPackage,
    path_overrides: dict[str, Any],
    skipped_paths: list[str] | None = None,
    framing_payload: dict[str, Any],
    picos_payload: dict[str, Any],
    impact_map: dict[str, list[str]],
    evidence_verifier: EvidencePathVerifier | None = None,
) -> CompositeAdoptionPlan:
    """Pure planner: resolve all target_paths, overrides, evidence gates,
    derived values and conflicts into an immutable plan. Raises ValueError
    on any structural or evidence failure; never persists."""

    # 1. candidate must be module or design_package scope.
    if candidate.candidate_scope not in ("module", "design_package"):
        raise ValueError(
            f"composite adopt requires module or design_package scope, got {candidate.candidate_scope}"
        )

    # 2. target_paths non-empty, structured_value keys match exactly.
    target_paths = list(candidate.target_paths)
    if not target_paths:
        raise ValueError("composite candidate has no target_paths")

    sv = candidate.structured_value
    if not isinstance(sv, dict):
        raise ValueError("composite candidate structured_value must be an object")
    sv_keys = set(sv.keys())
    target_set = set(target_paths)
    if sv_keys != target_set:
        missing = target_set - sv_keys
        extra = sv_keys - target_set
        parts: list[str] = []
        if missing:
            parts.append(f"missing keys: {sorted(missing)}")
        if extra:
            parts.append(f"unexpected keys: {sorted(extra)}")
        raise ValueError(
            "composite candidate structured_value keys must match target_paths"
            + (" (" + "; ".join(parts) + ")" if parts else "")
        )

    # 3. All target_paths must be in the adoptable whitelist.
    for tp in target_paths:
        if tp not in COMPOSITE_ADOPTABLE_PATHS:
            raise ValueError(f"target_path not adoptable as composite: {tp}")

    # 4. Override and explicit-skip keys must be disjoint subsets of target_paths.
    override_keys = set(path_overrides.keys())
    extra_overrides = override_keys - target_set
    if extra_overrides:
        raise ValueError(
            f"path_overrides contains paths not in candidate target_paths: {sorted(extra_overrides)}"
        )
    explicit_skip_set = set(skipped_paths or [])
    extra_skips = explicit_skip_set - target_set
    if extra_skips:
        raise ValueError(
            f"skipped_paths contains paths not in candidate target_paths: {sorted(extra_skips)}"
        )
    overlap = override_keys.intersection(explicit_skip_set)
    if overlap:
        raise ValueError(
            f"path_overrides and skipped_paths overlap: {sorted(overlap)}"
        )

    # 5. Resolve per-path values and dispositions.
    applied_candidate_paths: list[str] = []
    applied_override_paths: list[str] = []
    skipped_dispositions: list[tuple[str, str]] = []
    path_origins: dict[str, str] = {}

    # Corrective round (P2): the composite path is the designated override
    # channel.  A candidate that is pending_decision, manual_only,
    # insufficient, or carrying an unsupported-substantive gap may only
    # contribute a path through an explicit override or explicit skip —
    # zero-override use rejects before any mutation, mirroring the
    # single-candidate gate.
    policy_restricted, policy_reason = _composite_path_policy_restricted(
        candidate
    )
    policy_label = _POLICY_REASON_LABELS.get(policy_reason, policy_reason)

    for tp in target_paths:
        has_override = tp in path_overrides
        if has_override:
            applied_override_paths.append(tp)
            path_origins[tp] = "user_override"
            continue
        if tp in explicit_skip_set:
            skipped_dispositions.append((tp, "user_explicit_skip"))
            path_origins[tp] = "user_explicit_skip"
            continue
        if policy_restricted:
            raise MedicalWritingAuthoringPolicyError(
                f"{policy_label} path requires an override or explicit skip: {tp}",
                reason=policy_reason,
            )
        # Recommended / alternative: use candidate value.
        candidate_value = sv[tp]
        if _is_falsy_value(candidate_value):
            skipped_dispositions.append(
                (tp, "candidate value is empty and no override provided")
            )
            continue

        verified = False
        if evidence_verifier is not None:
            verified = bool(
                evidence_verifier.verify_candidate_path(
                    project_id=project_id,
                    package=package,
                    candidate=candidate,
                    target_path=tp,
                    proposed_value=candidate_value,
                )
            )
            if verified:
                applied_candidate_paths.append(tp)
                path_origins[tp] = "ai_candidate_evidence_bound"
                continue

        # Exact clinical facts: prefer evidence binding; otherwise allow the
        # lazy-writer one-click path so packages do not leave required PICOS
        # fields blank after the medical manager explicitly adopts a skeleton.
        if tp in EXACT_FACT_PATHS:
            if is_deterministic_lazy_recommendation(candidate, package):
                applied_candidate_paths.append(tp)
                path_origins[tp] = "user_accepted_deterministic_recommendation"
                continue
            skipped_dispositions.append(
                (tp, "exact_fact requires evidence binding or user override")
            )
            continue

        # Deterministic lazy recommendation: user click = confirmation.
        if is_deterministic_lazy_recommendation(candidate, package):
            applied_candidate_paths.append(tp)
            path_origins[tp] = "user_accepted_deterministic_recommendation"
            continue

        if evidence_verifier is None:
            # No verifier injected — fail closed for AI-origin values.
            raise ValueError(
                f"no evidence verifier provided; cannot verify candidate path {tp}"
            )
        raise ValueError(
            f"evidence gate failed for candidate path {tp}: "
            f"server evidence verification rejected the binding"
        )

    # A policy-restricted candidate may record a skip-only decision only when
    # every target was explicitly skipped. Any implicit unresolved path remains
    # a rejection (policy error for restricted candidates, structural error
    # otherwise).
    if not applied_candidate_paths and not applied_override_paths:
        all_restricted_targets_explicitly_skipped = (
            policy_restricted and explicit_skip_set == target_set
        )
        if not all_restricted_targets_explicitly_skipped:
            if policy_restricted:
                raise MedicalWritingAuthoringPolicyError(
                    "composite adoption plan resolved no applicable paths; "
                    f"{policy_label} requires an override or explicit skip "
                    "for every target",
                    reason=policy_reason,
                )
            raise ValueError(
                "composite adoption plan resolved no applicable paths; "
                "pending_decision requires an override or explicit skip for every target"
            )

    # 6. Apply paths in fixed business order.
    ordered_apply_paths = [tp for tp in target_paths if tp in applied_candidate_paths or tp in applied_override_paths]

    cumulative_framing = dict(framing_payload)
    cumulative_picos = dict(picos_payload)
    final_framing_updates: dict[str, Any] = {}
    final_picos_updates: dict[str, Any] = {}
    all_changed: list[str] = []
    # Track leaf-level values contributed by each root path for conflict
    # detection. Key: (derived_path, leaf_key) -> value.
    leaf_contributions: dict[tuple[str, str], Any] = {}

    for tp in ordered_apply_paths:
        if tp in path_overrides:
            value = path_overrides[tp]
        else:
            value = sv[tp]

        f_updates, p_updates, changed = map_design_adoption_to_study_updates(
            tp,
            value,
            framing_payload=cumulative_framing,
            picos_payload=cumulative_picos,
        )
        cumulative_framing.update(f_updates)
        cumulative_picos.update(p_updates)
        final_framing_updates.update(f_updates)
        final_picos_updates.update(p_updates)
        for c in changed:
            all_changed.append(c)
            if c != tp:
                path_origins[c] = "derived"

    # 6b. Leaf-level derived conflict detection.
    # For each root path, determine the DELTA it produces on derived paths
    # (only keys that differ from the baseline). Then check that no two
    # roots produced conflicting values for the same leaf.
    derived_paths_seen: dict[str, list[tuple[str, Any]]] = {}
    for tp in ordered_apply_paths:
        if tp in path_overrides:
            value = path_overrides[tp]
        else:
            value = sv[tp]
        # Re-run mapper in isolation against the original baseline.
        try:
            f_iso, p_iso, _ = map_design_adoption_to_study_updates(
                tp,
                value,
                framing_payload=dict(framing_payload),
                picos_payload=dict(picos_payload),
            )
        except Exception:
            continue
        all_iso_updates = {}
        if isinstance(f_iso, dict):
            all_iso_updates.update(f_iso)
        if isinstance(p_iso, dict):
            all_iso_updates.update(p_iso)
        for changed_path, changed_val in all_iso_updates.items():
            if changed_path == tp:
                continue
            # Mapper returns bare field names (e.g. "structured_design"), not
            # dotted paths. Try both forms for the baseline lookup.
            baseline = (
                framing_payload.get(changed_path)
                if changed_path in framing_payload
                else picos_payload.get(changed_path)
            )
            if isinstance(changed_val, dict):
                baseline_dict = baseline if isinstance(baseline, dict) else {}
                delta_leaves = _flatten_dict_leaves(changed_val)
                # Remove leaves that match baseline (echoed, not changed by this root).
                changed_leaves = {}
                for lk, lv in delta_leaves.items():
                    baseline_val = _get_nested_value(baseline_dict, lk)
                    if canonicalize_candidate_value(baseline_val) != canonicalize_candidate_value(lv):
                        changed_leaves[lk] = lv
                for leaf_key, leaf_val in changed_leaves.items():
                    full_key = f"{changed_path}.{leaf_key}"
                    derived_paths_seen.setdefault(full_key, []).append(
                        (tp, leaf_val)
                    )
            else:
                # Scalar: only track if different from baseline.
                # Exclude known composite fields that multiple roots
                # legitimately contribute to by design.
                if changed_path in ("design_pattern",):
                    continue
                if canonicalize_candidate_value(baseline) != canonicalize_candidate_value(changed_val):
                    derived_paths_seen.setdefault(changed_path, []).append(
                        (tp, changed_val)
                    )

    for leaf_key, contributions in derived_paths_seen.items():
        if len(contributions) > 1:
            # Multiple roots changed this leaf. Check if values conflict.
            distinct_values = set()
            for _root, val in contributions:
                distinct_values.add(canonicalize_candidate_value(val))
            if len(distinct_values) > 1:
                raise ValueError(
                    f"derived leaf conflict: {leaf_key} received conflicting "
                    f"values from roots {[r for r, _ in contributions]}"
                )

    # 7. Candidate fully applied?
    candidate_fully_applied = len(skipped_dispositions) == 0

    # 8. Compute value_changed vs resolution_changed paths.
    value_changed: list[str] = []
    resolution_changed: list[str] = []
    for path in all_changed:
        old_value = _get_value_for_path(path, framing_payload, picos_payload)
        new_value = _get_value_for_path(path, cumulative_framing, cumulative_picos)
        if values_materially_distinct(old_value, new_value):
            value_changed.append(path)
        else:
            resolution_changed.append(path)

    derived_paths = sorted(
        p for p in set(all_changed)
        if p not in target_set and p not in applied_override_paths
    )

    # 9. Compute impacted dependents.
    impacted: set[str] = set()
    for path in all_changed:
        for dep in impact_map.get(path, []):
            impacted.add(dep)

    return CompositeAdoptionPlan(
        applied_candidate_paths=applied_candidate_paths,
        applied_override_paths=applied_override_paths,
        derived_paths=derived_paths,
        skipped_paths=skipped_dispositions,
        framing_updates=final_framing_updates,
        picos_updates=final_picos_updates,
        all_changed_paths=all_changed,
        value_changed_paths=value_changed,
        resolution_changed_paths=resolution_changed,
        candidate_fully_applied=candidate_fully_applied,
        impacted=sorted(impacted),
        path_origins=path_origins,
    )


def _flatten_dict_leaves(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict into leaf_key -> value pairs."""
    result: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten_dict_leaves(v, key))
        else:
            result[key] = v
    return result


def _get_nested_value(d: dict[str, Any], dotted_key: str) -> Any:
    """Get a value from a nested dict using a dotted key like 'a.b.c'."""
    parts = dotted_key.split(".")
    current: Any = d
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _is_falsy_value(value: Any) -> bool:
    """Check if a candidate value is effectively 'empty' (no decision).
    Note: False and 0 are NOT falsy here — they are valid explicit decisions."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _get_value_for_path(
    path: str,
    framing: dict[str, Any],
    picos: dict[str, Any],
) -> Any:
    """Get the current value for a dotted path from framing/picos dicts."""
    if path.startswith("framing."):
        return framing.get(path.split(".", 1)[1])
    if path.startswith("picos."):
        return picos.get(path.split(".", 1)[1])
    return None
