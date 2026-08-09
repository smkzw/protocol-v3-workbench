"""Server-side evidence catalog projection and claim-binding validator.

W2b-2 r2: Strict catalog-first path.  No legacy bypass, no bare source IDs,
no snapshot hints.  The catalog is the sole evidence input and the validator
enforces per-claim fail-closed semantics:

- Both catalog_id AND catalog_sha256 must be present and match exactly.
- Every AI candidate requires at least one valid binding; zero bindings = reject.
- Any binding validation failure rejects the entire candidate.
- Unmapped CT.gov field_keys are rejected (no implicit broad mapping).
- Round-1 corpus-analysis entries route through the bridge's single
  conservative module→target-path allowlist (``corpus_module_target_paths``);
  entries with an empty allowlist are rejected as bind targets.
- Candidates bound to an ``insufficient_support_do_not_generalize`` corpus
  entry must use ``recommendation_role=pending_decision`` (never
  recommended/alternative) and stay ``competitor_option``.
- All intervention[i].name/type entries support intervention/comparator paths.
- Package target_paths must exactly match the server's deterministic set.
- value_pointer is validated as RFC6901 and must resolve to a non-empty atomic
  value under the corresponding target_path.
- Condition term becomes a real catalog-bound candidate via indication entry.
- Package candidates use candidate_scope=design_package.
- A field candidate whose every bound value is a complete current-project fact
  may use the audited ``batch_allowed`` mode; competitor observations and
  mixed/partial evidence remain ``manual_only``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from packages.contracts.workbench_contracts import (
    AuthoringPrefillCandidate,
    AuthoringPrefillClaimBinding,
    AuthoringPrefillEvidenceCatalog,
    AuthoringPrefillEvidenceCatalogEntry,
    AuthoringPrefillEvidenceRef,
    AuthoringPrefillPackage,
)

from .medical_writing_authoring_prefill_corpus_bridge import (
    CORPUS_ANALYSIS_LINEAGE,
    INSUFFICIENT_SUPPORT_REUSE_DECISION,
    CorpusPrefillBridgeError,
    corpus_module_target_paths,
    reword_qualifying_support_gap,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bounded payload limits
# ---------------------------------------------------------------------------

MAX_TOTAL_EVIDENCE_CHARS = 120_000
MAX_QUOTE_CHARS_PER_ENTRY = 2_000
MAX_ENTRIES_PROJECTED = 200
MAX_PACKAGE_CANDIDATES_PER_KEY = 5
MAX_FIELD_SUGGESTIONS_PER_FIELD = 5
MAX_TOTAL_PAYLOAD_CHARS = 200_000  # Hard ceiling on entire serialized payload.

PACKAGE_KEYS: Tuple[str, ...] = (
    "package.population",
    "package.intervention",
    "package.outcomes",
    "package.statistics",
    # package.soa removed from PICOS/prefill — SoA is post-design
    "package.design",
    "package.product",
)

# ---------------------------------------------------------------------------
# CT.gov field_key → exact target path mapping.
# Unmapped field_keys are REJECTED — no implicit broad fallback.
# ---------------------------------------------------------------------------

_CTOV_FIELD_MAPPING: Dict[str, Tuple[str, ...]] = {
    "design_allocation": (
        "picos.design_archetype",
        "design.randomization",
    ),
    "design_masking": (
        "picos.design_archetype",
        "design.blinding",
    ),
    "design_intervention_model": (
        "picos.design_archetype",
        "design.assignment_model",
    ),
    "conditions": (
        "picos.population_summary",
        "framing.population_intent",
    ),
    "brief_summary": (
        "picos.population_summary",
        "picos.intervention_summary",
        "picos.primary_objectives",
        "picos.study_epochs",
    ),
    "brief_title": (
        "picos.population_summary",
        "picos.intervention_summary",
        "picos.primary_objectives",
    ),
    "official_title": (
        "picos.population_summary",
        "picos.intervention_summary",
    ),
    "phases": ("framing.study_phase",),
    "study_type": ("picos.design_archetype",),
    "enrollment_count": (
        "picos.sample_size_strategy",
        "picos.statistical_strategy",
    ),
    "lead_sponsor": (),
    "overall_status": (),
    "study_record_url": (),
    "nct_id": (),
}


def _ctgov_compatible_targets(field_key: str) -> Optional[Tuple[str, ...]]:
    """Return the target paths a CT.gov field_key can inform, or None if
    the field_key is unmapped (which means the binding must be rejected)."""
    if field_key in _CTOV_FIELD_MAPPING:
        return _CTOV_FIELD_MAPPING[field_key]
    # Check if it's an intervention[i].name or intervention[i].type pattern.
    if re.match(r"^intervention\[\d+\]\.name$", field_key):
        return ("picos.intervention_summary", "picos.comparator_summary")
    if re.match(r"^intervention\[\d+\]\.type$", field_key):
        return ("picos.intervention_summary",)
    # Check if it's a document field — unmapped, reject.
    if field_key.startswith("document:"):
        return None
    # Any other unmapped field_key → reject.
    return None


def _corpus_compatible_targets(
    entry: AuthoringPrefillEvidenceCatalogEntry,
) -> Optional[Tuple[str, ...]]:
    """Return the conservative prefill target paths a round-1 corpus
    evidence entry may support.

    The allowlist is recomputed through the corpus bridge's single
    ``corpus_module_target_paths`` function from the entry provenance
    (module / transfer_scope / pattern_kind / reuse_decision) — there is no
    divergent table here.  Returns ``None`` for non-corpus entries; raises
    ``CorpusPrefillBridgeError`` when the provenance cannot be routed
    (unknown module), and returns ``()`` when the finding is not reusable
    for any design path.  Callers reject bindings for ``None`` and empty
    allowlists alike.
    """
    if entry.provenance.get("analysis_lineage") != CORPUS_ANALYSIS_LINEAGE:
        return None
    return tuple(
        corpus_module_target_paths(
            str(entry.provenance.get("module", "")),
            transfer_scope=str(entry.provenance.get("transfer_scope", "")),
            pattern_kind=str(entry.provenance.get("pattern_kind", "")) or None,
            reuse_decision=str(entry.provenance.get("reuse_decision", "")) or None,
        )
    )


# ---------------------------------------------------------------------------
# 1. Project catalog for model input
# ---------------------------------------------------------------------------


def project_catalog_for_model(
    catalog: AuthoringPrefillEvidenceCatalog,
    *,
    deterministic_field_paths: Set[str],
    package_target_paths: Dict[str, List[str]],
) -> Dict[str, Any]:
    """Project the immutable catalog into a bounded JSON payload."""
    projected_entries: List[Dict[str, Any]] = []
    sent_entry_ids: List[str] = []
    eligible_entry_ids_by_target_path: Dict[str, List[str]] = {}
    total_chars = 0

    # The immutable catalog is assembled from project facts, the registry
    # snapshot, and (when available) the verified round-1 Protocol analysis.
    # A large registry snapshot can contain hundreds of field-level entries.
    # Preserve the catalog's own deterministic order within each tier, but
    # project the scarce/high-value evidence first so the 200-entry transport
    # ceiling cannot silently hide the entire Protocol corpus from the model.
    projection_entries = sorted(
        enumerate(catalog.entries),
        key=lambda item: (
            0
            if item[1].support_scope == "current_project_fact"
            else 1
            if item[1].provenance.get("analysis_lineage")
            == CORPUS_ANALYSIS_LINEAGE
            else 2,
            item[0],
        ),
    )

    for _, entry in projection_entries:
        if len(projected_entries) >= MAX_ENTRIES_PROJECTED:
            break
        quote = entry.quote
        if len(quote) > MAX_QUOTE_CHARS_PER_ENTRY:
            quote = quote[:MAX_QUOTE_CHARS_PER_ENTRY]

        entry_chars = len(quote) + len(entry.source_id) + len(entry.locator)
        if total_chars + entry_chars > MAX_TOTAL_EVIDENCE_CHARS:
            if entry.support_scope == "current_project_fact":
                pass  # Always include project facts.
            else:
                break

        compatible_target_paths = list(entry.supported_target_paths)
        if entry.source_kind == "ctgov_snapshot":
            field_key = str(entry.provenance.get("field_key", ""))
            compatible_target_paths = list(
                _ctgov_compatible_targets(field_key) or ()
            )
        elif (
            entry.provenance.get("analysis_lineage") == CORPUS_ANALYSIS_LINEAGE
        ):
            # Round-1 corpus entries: recompute through the bridge's single
            # allowlist function.  An unrouteable entry (unknown module) is a
            # catalog-integrity failure and must fail closed, not be silently
            # dropped from the eligible set.
            compatible_target_paths = list(
                _corpus_compatible_targets(entry) or ()
            )

        projected_entries.append({
            "catalog_entry_id": entry.catalog_entry_id,
            "source_kind": entry.source_kind,
            "support_scope": entry.support_scope,
            "source_id": entry.source_id,
            "source_revision": entry.source_revision,
            "locator": entry.locator,
            "quote": quote,
            "quote_sha256": entry.quote_sha256,
            "title": entry.title,
            "supported_target_paths": compatible_target_paths,
            "provenance": _minimize_provenance(entry),
        })
        sent_entry_ids.append(entry.catalog_entry_id)
        for target_path in compatible_target_paths:
            eligible_entry_ids_by_target_path.setdefault(
                target_path, []
            ).append(entry.catalog_entry_id)
        total_chars += entry_chars

    return {
        "catalog_id": catalog.catalog_id,
        "catalog_sha256": catalog.catalog_sha256,
        "journey_revision": catalog.journey_revision,
        "snapshot_id": catalog.snapshot_id,
        "evidence_entries": projected_entries,
        "sent_entry_ids": sent_entry_ids,
        "eligible_entry_ids_by_target_path": {
            target_path: entry_ids
            for target_path, entry_ids in sorted(
                eligible_entry_ids_by_target_path.items()
            )
        },
        "deterministic_field_paths": sorted(deterministic_field_paths),
        "package_target_paths": {
            key: sorted(paths) for key, paths in package_target_paths.items()
        },
        "total_chars": total_chars,
    }


def _minimize_provenance(
    entry: AuthoringPrefillEvidenceCatalogEntry,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key in (
        "nct_id",
        "snapshot_id",
        "field_name",
        "span_id",
        "fact_path",
        "field_key",
        # Round-1 corpus-analysis lineage (additive: only forwarded when
        # present, so existing entry projections are byte-identical).
        "analysis_lineage",
        "analysis_id",
        "analysis_output_hash",
        "finding_id",
        "module",
        "transfer_scope",
        "pattern_kind",
        "reuse_decision",
        "content_role",
        "evidence_tier",
        "evidence_id",
        "indication_relation",
        "document_sha256",
        "source_text_sha256",
        # Source-specific limitation and unresolved gaps so the AI and the
        # reviewer can see why medical judgment is required.
        "source_count",
        "sponsor_count",
        "unresolved_gaps",
        "indication_alignment_status",
        "limitation_note",
    ):
        if key in entry.provenance:
            result[key] = entry.provenance[key]
    return result


# ---------------------------------------------------------------------------
# 2. Validate and rebind model output
# ---------------------------------------------------------------------------


class EvidenceValidationError(Exception):
    pass


def validate_and_rebind_candidates(
    *,
    catalog: AuthoringPrefillEvidenceCatalog,
    sent_entry_ids: Set[str],
    model_output: Dict[str, Any],
    condition_term_path: str,
    eligible_field_paths: Set[str],
    package_target_paths: Dict[str, List[str]],
) -> Tuple[
    Optional[AuthoringPrefillCandidate],
    List[AuthoringPrefillCandidate],
    Dict[str, List[AuthoringPrefillCandidate]],
    Dict[str, List[AuthoringPrefillCandidate]],
    List[str],
]:
    """Validate model output against the server-side catalog.

    Returns:
    1. condition_term_candidate (AuthoringPrefillCandidate or None)
    2. field_candidates list
    3. package_candidates dict
    4. all_candidates flat dict
    5. validation_errors list
    """
    entry_lookup: Dict[str, AuthoringPrefillEvidenceCatalogEntry] = {
        e.catalog_entry_id: e for e in catalog.entries
    }

    validation_errors: List[str] = []

    # -- Strict catalog identity: both ID and SHA must be present and match. --
    returned_catalog_id = str(model_output.get("catalog_id", "")).strip()
    returned_catalog_sha = str(model_output.get("catalog_sha256", "")).strip().lower()

    if not returned_catalog_id:
        validation_errors.append("catalog_id is missing")
    elif returned_catalog_id != catalog.catalog_id:
        validation_errors.append(
            f"catalog_id mismatch: expected {catalog.catalog_id}, "
            f"got {returned_catalog_id}"
        )

    if not returned_catalog_sha:
        validation_errors.append("catalog_sha256 is missing")
    elif returned_catalog_sha != catalog.catalog_sha256:
        validation_errors.append(
            f"catalog_sha256 mismatch: expected {catalog.catalog_sha256}, "
            f"got {returned_catalog_sha}"
        )

    if validation_errors:
        return (None, [], {}, {}, validation_errors)

    # -- Parse condition term as catalog-bound candidate. --
    condition_candidate: Optional[AuthoringPrefillCandidate] = None
    raw_condition = model_output.get("clinicaltrials_condition_term_en", "")
    if isinstance(raw_condition, str) and raw_condition.strip():
        condition_str = raw_condition.strip()
        # Find an indication entry that supports framing.clinicaltrials_condition_term.
        indication_entry = _find_supporting_entry(
            entry_lookup, sent_entry_ids, condition_term_path,
        )
        if indication_entry is not None:
            condition_candidate = _build_catalog_bound_candidate(
                field_path=condition_term_path,
                structured_value=condition_str,
                preview=condition_str,
                rationale=f"AI基于适应症提出的英文ClinicalTrials.gov检索词。",
                entry=indication_entry,
                target_path=condition_term_path,
                support_kind="normalized_enum",
                value_pointer="",
                is_package=False,
                catalog_id=catalog.catalog_id,
                catalog_sha256=catalog.catalog_sha256,
            )
        else:
            validation_errors.append(
                "condition_term: no supporting catalog entry for "
                f"{condition_term_path}; AI condition term rejected"
            )
    # If no condition term returned, that's fine — it's optional.

    # -- Parse field_suggestions (non-condition, non-package). --
    field_candidates: List[AuthoringPrefillCandidate] = []
    raw_field_suggestions = model_output.get("field_suggestions", {})
    if isinstance(raw_field_suggestions, dict):
        for field_path, suggestions in raw_field_suggestions.items():
            if field_path not in eligible_field_paths:
                validation_errors.append(
                    f"field_suggestions: unsupported field_path '{field_path}'"
                )
                continue
            if field_path == condition_term_path:
                continue  # Handled above.
            if not isinstance(suggestions, list):
                continue
            parsed = _parse_and_validate_suggestions(
                field_path=field_path,
                suggestions=suggestions,
                entry_lookup=entry_lookup,
                sent_entry_ids=sent_entry_ids,
                is_package=False,
                server_package_target_paths=package_target_paths,
                catalog_id=catalog.catalog_id,
                catalog_sha256=catalog.catalog_sha256,
            )
            field_candidates.extend(parsed["candidates"])
            validation_errors.extend(parsed["errors"])

    # -- Parse package_suggestions. --
    package_candidates: Dict[str, List[AuthoringPrefillCandidate]] = {}
    raw_package_suggestions = model_output.get("package_suggestions", {})
    if isinstance(raw_package_suggestions, dict):
        for pkg_key, suggestions in raw_package_suggestions.items():
            if pkg_key not in PACKAGE_KEYS:
                validation_errors.append(
                    f"package_suggestions: unknown package key '{pkg_key}'"
                )
                continue
            if not isinstance(suggestions, list):
                continue
            parsed = _parse_and_validate_suggestions(
                field_path=pkg_key,
                suggestions=suggestions,
                entry_lookup=entry_lookup,
                sent_entry_ids=sent_entry_ids,
                is_package=True,
                server_package_target_paths=package_target_paths,
                catalog_id=catalog.catalog_id,
                catalog_sha256=catalog.catalog_sha256,
            )
            package_candidates[pkg_key] = parsed["candidates"][:MAX_PACKAGE_CANDIDATES_PER_KEY]
            validation_errors.extend(parsed["errors"])

    # Build flat merge dict.
    all_candidates: Dict[str, List[AuthoringPrefillCandidate]] = {}
    for cand in field_candidates:
        all_candidates.setdefault(cand.field_path, []).append(cand)
    for pkg_key, cand_list in package_candidates.items():
        all_candidates.setdefault(pkg_key, []).extend(cand_list)

    return (
        condition_candidate,
        field_candidates,
        package_candidates,
        all_candidates,
        validation_errors,
    )


def _find_supporting_entry(
    entry_lookup: Dict[str, AuthoringPrefillEvidenceCatalogEntry],
    sent_entry_ids: Set[str],
    target_path: str,
) -> Optional[AuthoringPrefillEvidenceCatalogEntry]:
    """Find the first sent entry that supports the given target_path."""
    for eid, entry in entry_lookup.items():
        if eid not in sent_entry_ids:
            continue
        if entry.support_scope != "current_project_fact":
            continue
        if target_path in entry.supported_target_paths:
            return entry
    return None


def _build_catalog_bound_candidate(
    *,
    field_path: str,
    structured_value: Any,
    preview: str,
    rationale: str,
    entry: AuthoringPrefillEvidenceCatalogEntry,
    target_path: str,
    support_kind: str,
    value_pointer: str,
    is_package: bool,
    catalog_id: str,
    catalog_sha256: str,
    recommendation_role: str = "recommended",
    clinical_tradeoffs: Optional[List[str]] = None,
    evidence_gaps: Optional[List[str]] = None,
) -> AuthoringPrefillCandidate:
    """Build a single candidate with one validated binding."""
    binding = AuthoringPrefillClaimBinding(
        target_path=target_path,
        value_pointer=value_pointer,
        catalog_entry_id=entry.catalog_entry_id,
        source_id=entry.source_id,
        locator=entry.locator,
        quote_sha256=entry.quote_sha256,
        support_kind=support_kind,  # type: ignore[arg-type]
    )
    evidence_ref = AuthoringPrefillEvidenceRef(
        source_kind=_entry_source_kind_to_ref(entry.source_kind),
        source_id=entry.source_id,
        source_text=entry.quote[:5000],
        locator=entry.locator,
        quote_sha256=entry.quote_sha256,
    )
    digest = hashlib.sha256(
        json.dumps(
            {"field_path": field_path, "value": structured_value, "e": entry.catalog_entry_id},
            ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]

    evidence_status = "supported"  # Single binding to a project fact = supported.

    return AuthoringPrefillCandidate(
        candidate_id=f"mwprefilleb_{digest}",
        field_path=field_path,
        structured_value=structured_value,
        preview=str(preview)[:5000],
        evidence_refs=[evidence_ref],
        rationale=str(rationale)[:5000],
        limitations=["AI预填候选，需由医学经理核对后采用。"],
        confidence="medium",
        state="ai_proposed",
        candidate_scope="design_package" if is_package else "field",
        target_paths=[target_path] if is_package else [],
        recommendation_role=recommendation_role,  # type: ignore[arg-type]
        adoption_mode="manual_only",
        clinical_tradeoffs=clinical_tradeoffs or [],
        evidence_gaps=evidence_gaps or [],
        evidence_catalog_id=catalog_id,
        evidence_catalog_sha256=catalog_sha256,
        claim_bindings=[binding],
        evidence_status=evidence_status,  # type: ignore[arg-type]
    )


def _field_candidate_adoption_mode(
    *,
    validated_bindings: List[AuthoringPrefillClaimBinding],
    entry_lookup: Dict[str, AuthoringPrefillEvidenceCatalogEntry],
    evidence_status: str,
    recommendation_role: str,
    evidence_gaps: List[str],
) -> str:
    """Return the narrow safe adoption mode for an evidence-bound field.

    A field-level AI suggestion may be one-click confirmed only when every
    atomic value is bound to the immutable current-project fact projection.
    Registry/corpus observations, mixed provenance, incomplete support, or any
    pending/unsupported gap remain manual-only.  This keeps the existing
    fail-closed policy for competitor-derived design/PICOS options while
    removing the dead-end where a deterministic project identity (for example
    a title built only from product/indication/phase) could never be adopted
    without retyping the same value.
    """
    if evidence_status != "supported":
        return "manual_only"
    if recommendation_role == "pending_decision":
        return "manual_only"
    if evidence_gaps:
        return "manual_only"
    if not validated_bindings:
        return "manual_only"
    if not all(
        entry_lookup.get(binding.catalog_entry_id) is not None
        and entry_lookup[binding.catalog_entry_id].support_scope
        == "current_project_fact"
        for binding in validated_bindings
    ):
        return "manual_only"
    return "batch_allowed"


def bind_deterministic_project_fact_candidates(
    *,
    package: AuthoringPrefillPackage,
    catalog: AuthoringPrefillEvidenceCatalog,
    product: str,
    indication: str,
    phase: str,
) -> AuthoringPrefillPackage:
    """Bind the narrowly safe creation-minimum title candidates.

    Deterministic prefill is intentionally not allowed to turn phase-based
    clinical heuristics into project facts.  One exception is the document
    title assembled from the three creation-minimum identity facts.  Those
    facts are already immutable ``current_project_fact`` catalog entries and
    the title variants are a bounded, exact wording set generated by
    ``generate_prefill_package``.  Attach all three bindings so the normal
    live verifier, catalog hash, idempotency, and audit path are used instead
    of creating a legacy no-evidence bypass.

    No other deterministic field is touched.  In particular, design/PICOS,
    product-profile, competitor, mixed, partial, and pending candidates stay
    manual-only until the evidence-bound AI path supplies validated bindings.
    """
    product = str(product or "").strip()
    indication = str(indication or "").strip()
    phase = str(phase or "").strip()
    if not product or not indication or not phase:
        return package

    # Keep this allowlist coupled to the exact deterministic title templates.
    # A later wording change must add an explicit test rather than silently
    # broadening the one-click identity contract.
    allowed_titles = {
        f"{product}治疗{indication}的{phase}临床研究方案",
        f"{product}用于{indication}的{phase}研究方案",
        f"{product}（{indication}）{phase}方案",
    }
    fact_paths = (
        "framing.investigational_product",
        "framing.indication",
        "framing.study_phase",
    )
    entry_by_source = {
        entry.source_id: entry
        for entry in catalog.entries
        if entry.support_scope == "current_project_fact"
        and entry.source_id in fact_paths
        and "framing.document_title" in entry.supported_target_paths
    }
    if any(path not in entry_by_source for path in fact_paths):
        return package

    updated_groups: Dict[str, Any] = dict(package.field_candidates)
    changed = False
    for field_path, group in package.field_candidates.items():
        if field_path != "framing.document_title":
            continue
        updated_candidates: List[AuthoringPrefillCandidate] = []
        for candidate in group.candidates:
            # AI-enriched candidates already carry a validated catalog
            # binding.  Never overwrite their lineage or adoption decision.
            if (
                candidate.candidate_scope != "field"
                or candidate.claim_bindings
                or candidate.evidence_catalog_id
                or str(candidate.structured_value or "") not in allowed_titles
            ):
                updated_candidates.append(candidate)
                continue

            bindings: List[AuthoringPrefillClaimBinding] = []
            evidence_refs: List[AuthoringPrefillEvidenceRef] = []
            for fact_path in fact_paths:
                entry = entry_by_source[fact_path]
                bindings.append(
                    AuthoringPrefillClaimBinding(
                        target_path=field_path,
                        value_pointer="",
                        catalog_entry_id=entry.catalog_entry_id,
                        source_id=entry.source_id,
                        locator=entry.locator,
                        quote_sha256=entry.quote_sha256,
                        support_kind="normalized_enum",
                    )
                )
                evidence_refs.append(
                    AuthoringPrefillEvidenceRef(
                        source_kind="study_definition",
                        source_id=entry.source_id,
                        source_text=entry.quote[:5000],
                        locator=entry.locator,
                        quote_sha256=entry.quote_sha256,
                    )
                )

            updated_candidates.append(
                candidate.model_copy(
                    update={
                        "evidence_refs": evidence_refs,
                        "adoption_mode": "batch_allowed",
                        "evidence_catalog_id": catalog.catalog_id,
                        "evidence_catalog_sha256": catalog.catalog_sha256,
                        "claim_bindings": bindings,
                        "evidence_status": "supported",
                    },
                    deep=True,
                )
            )
            changed = True

        if changed:
            updated_groups[field_path] = group.model_copy(
                update={"candidates": updated_candidates},
                deep=True,
            )

    if not changed:
        return package
    return package.model_copy(
        update={
            "field_candidates": updated_groups,
            "evidence_catalog": catalog,
        },
        deep=True,
    )


def _parse_and_validate_suggestions(
    *,
    field_path: str,
    suggestions: List[Any],
    entry_lookup: Dict[str, AuthoringPrefillEvidenceCatalogEntry],
    sent_entry_ids: Set[str],
    is_package: bool,
    server_package_target_paths: Dict[str, List[str]],
    catalog_id: str = "",
    catalog_sha256: str = "",
) -> Dict[str, Any]:
    candidates: List[AuthoringPrefillCandidate] = []
    errors: List[str] = []

    max_count = MAX_PACKAGE_CANDIDATES_PER_KEY if is_package else MAX_FIELD_SUGGESTIONS_PER_FIELD
    for index, item in enumerate(suggestions[:max_count]):
        if not isinstance(item, dict):
            errors.append(f"{field_path}[{index}]: not a dict")
            continue

        structured_value = item.get("structured_value")
        preview = item.get("preview") or ""
        rationale = item.get("rationale") or ""
        recommendation_role = item.get("recommendation_role") or "pending_decision"
        clinical_tradeoffs = item.get("clinical_tradeoffs") or []
        evidence_gaps = item.get("evidence_gaps") or []
        raw_bindings = item.get("claim_bindings") or []

        if structured_value is None:
            errors.append(f"{field_path}[{index}]: missing structured_value")
            continue

        # -- Package: target_paths must EXACTLY match the server's set. --
        if is_package:
            model_target_paths = item.get("target_paths")
            if not isinstance(model_target_paths, list) or not model_target_paths:
                errors.append(
                    f"{field_path}[{index}]: package candidate must explicitly "
                    f"provide target_paths"
                )
                continue
            model_set = {str(tp).strip() for tp in model_target_paths if str(tp).strip()}
            server_set = set(server_package_target_paths.get(field_path, []))
            if model_set != server_set:
                errors.append(
                    f"{field_path}[{index}]: target_paths must exactly match "
                    f"server set; expected {sorted(server_set)}, got {sorted(model_set)}"
                )
                continue
            target_paths = sorted(model_set)
        else:
            target_paths = [field_path]

        # -- Package: structured_value keys must match target_paths. --
        if is_package:
            if not isinstance(structured_value, dict):
                errors.append(f"{field_path}[{index}]: package structured_value must be dict")
                continue
            value_keys = set(structured_value.keys())
            target_set = set(target_paths)
            if value_keys != target_set:
                missing = target_set - value_keys
                extra = value_keys - target_set
                parts: List[str] = []
                if missing:
                    parts.append(f"missing: {sorted(missing)}")
                if extra:
                    parts.append(f"unexpected: {sorted(extra)}")
                errors.append(
                    f"{field_path}[{index}]: structured_value keys mismatch "
                    f"({'; '.join(parts)})"
                )
                continue

        # -- Every candidate MUST have at least one binding. --
        if not raw_bindings:
            errors.append(
                f"{field_path}[{index}]: candidate rejected — zero claim_bindings"
            )
            continue

        # -- Validate each binding; ANY failure rejects the whole candidate. --
        validated_bindings: List[AuthoringPrefillClaimBinding] = []
        evidence_refs: List[AuthoringPrefillEvidenceRef] = []
        has_project_fact_binding = False

        binding_failed = False
        for binding_idx, raw_binding in enumerate(raw_bindings):
            if not isinstance(raw_binding, dict):
                errors.append(
                    f"{field_path}[{index}].claim_bindings[{binding_idx}]: not a dict"
                )
                binding_failed = True
                break

            try:
                binding = _validate_and_rebind_single_binding(
                    raw_binding=raw_binding,
                    entry_lookup=entry_lookup,
                    sent_entry_ids=sent_entry_ids,
                    candidate_target_paths=set(target_paths),
                    structured_value=structured_value,
                    is_package=is_package,
                )
                validated_bindings.append(binding)
                entry = entry_lookup[binding.catalog_entry_id]
                _append_deduped_evidence_ref(
                    evidence_refs,
                    AuthoringPrefillEvidenceRef(
                        source_kind=_entry_source_kind_to_ref(entry.source_kind),
                        source_id=entry.source_id,
                        source_text=entry.quote[:5000],
                        locator=entry.locator,
                        quote_sha256=entry.quote_sha256,
                    ),
                )
                if entry.support_scope == "current_project_fact":
                    has_project_fact_binding = True
            except EvidenceValidationError as exc:
                errors.append(
                    f"{field_path}[{index}].claim_bindings[{binding_idx}]: {exc}"
                )
                binding_failed = True
                break  # Any failure → reject whole candidate.

        if binding_failed:
            errors.append(
                f"{field_path}[{index}]: candidate rejected due to binding failure"
            )
            continue

        # Single-source competitor observations (insufficient support) must
        # remain medical-review decisions: any candidate bound to them is
        # forced to recommendation_role=pending_decision.  A model that
        # marks such a candidate recommended/alternative is rejected rather
        # than silently upgraded.
        limited_corpus_entries = [
            entry_lookup[b.catalog_entry_id]
            for b in validated_bindings
            if b.catalog_entry_id in entry_lookup
            and entry_lookup[b.catalog_entry_id].provenance.get(
                "reuse_decision"
            )
            == INSUFFICIENT_SUPPORT_REUSE_DECISION
        ]
        limited_corpus_binding = bool(limited_corpus_entries)
        if limited_corpus_binding:
            visible_gaps: List[str] = []
            if isinstance(evidence_gaps, list):
                visible_gaps.extend(
                    str(gap).strip()
                    for gap in evidence_gaps
                    if str(gap).strip()
                )
            visible_gaps.append(
                "该候选含支持不足的单项竞品Protocol观察，不得视为当前项目事实。"
            )
            for entry in limited_corpus_entries:
                limitation_note = str(
                    entry.provenance.get("limitation_note", "")
                ).strip()
                if limitation_note:
                    visible_gaps.append(limitation_note)
                unresolved_gaps = entry.provenance.get(
                    "unresolved_gaps", []
                )
                if isinstance(unresolved_gaps, list):
                    visible_gaps.extend(
                        reword_qualifying_support_gap(str(gap)).strip()
                        for gap in unresolved_gaps
                        if str(gap).strip()
                    )
            # Live bound-source re-derivation at the display boundary: the
            # distinct original sources actually bound to this candidate,
            # kept distinct from the analysis-declared qualifying counts.
            bound_source_ids = sorted(
                {
                    entry_lookup[binding.catalog_entry_id].source_id
                    for binding in validated_bindings
                    if binding.catalog_entry_id in entry_lookup
                }
            )
            if bound_source_ids:
                visible_gaps.append(
                    f"已绑定原始来源：{len(bound_source_ids)}"
                    "（仅作单项竞品观察）"
                )
            # Preserve first occurrence and bound the reader-facing payload.
            evidence_gaps = list(dict.fromkeys(visible_gaps))[:20]

        if limited_corpus_binding and (
            str(recommendation_role).strip() != "pending_decision"
        ):
            errors.append(
                f"{field_path}[{index}]: candidate relies on "
                "insufficient-support corpus evidence; "
                "recommendation_role must be 'pending_decision' "
                f"(got '{recommendation_role}'); rejected"
            )
            continue

        # A composite package is selectable only when every non-empty atomic
        # leaf is directly bound. Allowing an unbound leaf to remain merely
        # "partially supported" lets one condition/title observation mask
        # invented criteria, washout periods, endpoints or analysis rules.
        if is_package and not _all_atomic_values_bound(
            structured_value,
            validated_bindings,
            target_paths,
            is_package=True,
        ):
            errors.append(
                f"{field_path}[{index}]: package candidate rejected because "
                "one or more non-empty atomic leaves have no direct claim_binding"
            )
            continue

        # -- Determine evidence_status. --
        if has_project_fact_binding and _all_atomic_values_bound(
            structured_value, validated_bindings, target_paths, is_package,
        ):
            evidence_status = "supported"
        else:
            evidence_status = "partially_supported"

        # Only a field whose complete value is supported by current-project
        # facts may be directly confirmed.  Composite packages retain their
        # existing per-path policy gate; competitor/corpus observations and
        # mixed provenance stay manual-only.
        adoption_mode = "manual_only"
        if not is_package:
            adoption_mode = _field_candidate_adoption_mode(
                validated_bindings=validated_bindings,
                entry_lookup=entry_lookup,
                evidence_status=evidence_status,
                recommendation_role=str(recommendation_role).strip(),
                evidence_gaps=(
                    evidence_gaps if isinstance(evidence_gaps, list) else []
                ),
            )

        # -- Build candidate. --
        digest = hashlib.sha256(
            json.dumps(
                {
                    "field_path": field_path,
                    "structured_value": structured_value,
                    "suffix": f"w2b2r2-{index}",
                },
                ensure_ascii=False, sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]

        try:
            candidate = AuthoringPrefillCandidate(
                candidate_id=f"mwprefilleb_{digest}",
                field_path=field_path,
                structured_value=structured_value,
                preview=str(preview)[:5000] if preview else "",
                evidence_refs=evidence_refs[:20],
                rationale=str(rationale)[:5000] or "",
                limitations=["AI预填候选，需由医学经理核对后采用。"],
                confidence="medium",
                state="ai_proposed",
                candidate_scope="design_package" if is_package else "field",
                target_paths=target_paths if is_package else [],
                recommendation_role=recommendation_role,  # type: ignore[arg-type]
                adoption_mode=adoption_mode,  # type: ignore[arg-type]
                clinical_tradeoffs=clinical_tradeoffs if isinstance(clinical_tradeoffs, list) else [],
                evidence_gaps=evidence_gaps if isinstance(evidence_gaps, list) else [],
                evidence_catalog_id=catalog_id,
                evidence_catalog_sha256=catalog_sha256,
                claim_bindings=validated_bindings,
                evidence_status=evidence_status,  # type: ignore[arg-type]
            )
            candidates.append(candidate)
        except Exception as exc:
            errors.append(f"{field_path}[{index}]: candidate construction failed: {exc}")

    return {"candidates": candidates, "errors": errors}


# Negation guards: a design term asserted inside a negated sentence
# ("非随机"/"不随机"/"未随机"/"non-randomized") must never generate a positive
# design value.  Chinese alternatives carry 非/不/未 single-char lookbehinds;
# English alternatives carry a word-boundary guard plus a ``non[\s-]``
# prefix lookbehind so "non-randomized"/"non randomized" are excluded while
# "randomized" after any other word is kept.
_CORPUS_DESIGN_TERM_RULES: Tuple[
    Tuple[str, str, re.Pattern[str]], ...
] = (
    (
        "design.blinding",
        "双盲",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])double[\s-]?blind|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)双盲",
            re.IGNORECASE,
        ),
    ),
    (
        "design.blinding",
        "单盲",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])single[\s-]?blind|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)单盲",
            re.IGNORECASE,
        ),
    ),
    (
        "design.blinding",
        "开放标签",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])open[\s-]?label|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)开放标签",
            re.IGNORECASE,
        ),
    ),
    (
        "design.randomization",
        "随机",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])randomi[sz](?:ed|ation)(?![A-Za-z])|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)随机",
            re.IGNORECASE,
        ),
    ),
    (
        "design.assignment_model",
        "平行分组",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])parallel[\s-]?group|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)平行分组",
            re.IGNORECASE,
        ),
    ),
    (
        "design.assignment_model",
        "单臂",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])single[\s-]?arm|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)单臂",
            re.IGNORECASE,
        ),
    ),
    (
        "design.center_model",
        "多中心",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])multic(?:enter|entre)|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)多中心",
            re.IGNORECASE,
        ),
    ),
    (
        "design.center_model",
        "单中心",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])single[\s-]?cent(?:er|re)|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)单中心",
            re.IGNORECASE,
        ),
    ),
    (
        "design.comparator_type",
        "安慰剂对照",
        re.compile(
            r"(?<![A-Za-z])(?<!non[\s-])placebo|"
            r"(?<!非)(?<!不)(?<!未)(?<!无)安慰剂",
            re.IGNORECASE,
        ),
    ),
)


def build_round1_corpus_review_candidates(
    *,
    catalog: AuthoringPrefillEvidenceCatalog,
    sent_entry_ids: Set[str],
    package_target_paths: Dict[str, List[str]],
) -> Tuple[List[AuthoringPrefillCandidate], List[str]]:
    """Materialize deterministic, review-only design options from Protocol.

    A valid model response is not required to cite every eligible catalog
    entry.  That freedom must not make a verified round-1 Protocol analysis
    disappear from the user-facing review surface.  This helper extracts only
    explicit, controlled design terms from the original quote and routes the
    result back through the same strict binding validator as model output.

    These candidates are always ``pending_decision`` competitor options.  They
    never fill exact-fact paths, never become current-project facts, and cannot
    be automatically adopted.
    """
    design_paths = package_target_paths.get("package.design", [])
    if not design_paths:
        return [], []
    design_path_set = set(design_paths)
    entry_lookup = {
        entry.catalog_entry_id: entry for entry in catalog.entries
    }
    suggestions: List[Dict[str, Any]] = []

    for entry in catalog.entries:
        if entry.catalog_entry_id not in sent_entry_ids:
            continue
        provenance = entry.provenance
        if (
            provenance.get("analysis_lineage") != CORPUS_ANALYSIS_LINEAGE
            or provenance.get("module") != "design"
            or provenance.get("reuse_decision")
            != INSUFFICIENT_SUPPORT_REUSE_DECISION
        ):
            continue

        extracted: Dict[str, str] = {}
        quote = entry.quote
        for target_path, label, pattern in _CORPUS_DESIGN_TERM_RULES:
            if target_path in design_path_set and target_path not in extracted:
                if pattern.search(quote):
                    extracted[target_path] = label

        if (
            "design.open_label_extension" in design_path_set
            and re.search(
                r"(?<![A-Za-z])(?<!non[\s-])open[\s-]?label|"
                r"(?<!非)(?<!不)(?<!未)(?<!无)开放标签",
                quote,
                re.IGNORECASE,
            )
            and re.search(
                r"\bextension\b|"
                r"(?<!非)(?<!不)(?<!未)(?<!无)(?:延展|扩展)",
                quote,
                re.IGNORECASE,
            )
        ):
            extracted["design.open_label_extension"] = "是"

        if not extracted:
            continue

        structured_value: Dict[str, str] = {
            target_path: "" for target_path in design_paths
        }
        structured_value.update(extracted)
        preview_values = [
            (
                "开放标签延展"
                if target_path == "design.open_label_extension" and value == "是"
                else value
            )
            for target_path, value in extracted.items()
        ]
        preview = "、".join(dict.fromkeys(preview_values))
        source_label = str(
            provenance.get("nct_id") or entry.source_id
        ).strip()
        suggestions.append(
            {
                "structured_value": structured_value,
                "preview": f"竞品Protocol观察：{preview}",
                "rationale": (
                    f"服务器从已验证的round1竞品Protocol原文"
                    f"（{source_label}）提取明确设计要素；仅供医学经理"
                    "判断，不代表当前项目设计。"
                ),
                "recommendation_role": "pending_decision",
                "target_paths": list(design_paths),
                "clinical_tradeoffs": [
                    "仅展示原文明确出现的设计要素；项目适用性仍需医学判断。"
                ],
                "evidence_gaps": [],
                "claim_bindings": [
                    {
                        "target_path": target_path,
                        "value_pointer": f"/{target_path}",
                        "catalog_entry_id": entry.catalog_entry_id,
                        "support_kind": "competitor_option",
                    }
                    for target_path in extracted
                ],
            }
        )

    parsed = _parse_and_validate_suggestions(
        field_path="package.design",
        suggestions=suggestions,
        entry_lookup=entry_lookup,
        sent_entry_ids=sent_entry_ids,
        is_package=True,
        server_package_target_paths=package_target_paths,
        catalog_id=catalog.catalog_id,
        catalog_sha256=catalog.catalog_sha256,
    )
    return parsed["candidates"], parsed["errors"]


def _validate_and_rebind_single_binding(
    *,
    raw_binding: Dict[str, Any],
    entry_lookup: Dict[str, AuthoringPrefillEvidenceCatalogEntry],
    sent_entry_ids: Set[str],
    candidate_target_paths: Set[str],
    structured_value: Any,
    is_package: bool,
) -> AuthoringPrefillClaimBinding:
    """Validate one raw binding. Raises EvidenceValidationError on any failure."""
    catalog_entry_id = str(raw_binding.get("catalog_entry_id", "")).strip()
    if not catalog_entry_id:
        raise EvidenceValidationError("missing catalog_entry_id")

    if catalog_entry_id not in sent_entry_ids:
        raise EvidenceValidationError(
            f"catalog_entry_id '{catalog_entry_id}' was not sent to model"
        )

    entry = entry_lookup.get(catalog_entry_id)
    if entry is None:
        raise EvidenceValidationError(
            f"catalog_entry_id '{catalog_entry_id}' not found in server catalog"
        )

    target_path = str(raw_binding.get("target_path", "")).strip()
    if not target_path:
        raise EvidenceValidationError("missing target_path")
    if target_path not in candidate_target_paths:
        raise EvidenceValidationError(
            f"target_path '{target_path}' not in candidate target_paths "
            f"{sorted(candidate_target_paths)}"
        )

    support_kind = str(raw_binding.get("support_kind", "")).strip()
    value_pointer = str(raw_binding.get("value_pointer", "")).strip()

    # -- value_pointer validation. --
    if is_package:
        if not value_pointer:
            raise EvidenceValidationError(
                "package binding requires non-empty value_pointer (RFC6901)"
            )
        # Validate pointer resolves to a non-empty atomic value under target_path.
        _validate_value_pointer(
            value_pointer, structured_value, target_path,
        )
    else:
        # Field candidates: empty pointer means "the whole field".
        if value_pointer:
            raise EvidenceValidationError(
                "field candidate binding must use empty value_pointer"
            )

    # Server-rebind.
    rebound_source_id = entry.source_id
    rebound_locator = entry.locator
    rebound_quote_sha = entry.quote_sha256

    if entry.support_scope == "current_project_fact":
        if target_path not in entry.supported_target_paths:
            raise EvidenceValidationError(
                f"target_path '{target_path}' not supported by entry "
                f"supported_target_paths {entry.supported_target_paths}"
            )
        if not support_kind:
            support_kind = "exact_fact"
        if support_kind not in ("exact_fact", "normalized_enum"):
            raise EvidenceValidationError(
                f"current_project_fact entry can only use exact_fact or "
                f"normalized_enum, got '{support_kind}'"
            )
    elif entry.support_scope == "competitor_observation":
        if not support_kind:
            support_kind = "competitor_option"
        if support_kind != "competitor_option":
            raise EvidenceValidationError(
                f"competitor_observation entry can only use competitor_option, "
                f"got '{support_kind}'"
            )
        if entry.provenance.get("analysis_lineage") == CORPUS_ANALYSIS_LINEAGE:
            # Round-1 corpus-analysis evidence: recompute the conservative
            # allowlist through the bridge's single function (no divergent
            # table).  Both the recomputed allowlist AND the entry's own
            # supported_target_paths must admit the target — AND semantics
            # keeps the validator narrow even if an entry were constructed
            # without the bridge.
            try:
                compatible = _corpus_compatible_targets(entry)
            except CorpusPrefillBridgeError as exc:
                raise EvidenceValidationError(
                    f"corpus evidence entry cannot be routed to target paths: "
                    f"{exc}"
                ) from exc
            if compatible is None:
                raise EvidenceValidationError(
                    "corpus evidence entry cannot support any target path"
                )
            if not compatible:
                raise EvidenceValidationError(
                    f"corpus evidence entry supports no target paths and "
                    f"cannot support target_path '{target_path}'; binding rejected"
                )
            if target_path not in entry.supported_target_paths:
                raise EvidenceValidationError(
                    f"corpus entry cannot support target_path '{target_path}': "
                    f"not in entry supported_target_paths "
                    f"{entry.supported_target_paths}"
                )
        else:
            field_key = str(entry.provenance.get("field_key", ""))
            compatible = _ctgov_compatible_targets(field_key)
            if compatible is None:
                raise EvidenceValidationError(
                    f"CT.gov field_key '{field_key}' is unmapped; binding rejected"
                )
        if not compatible:
            raise EvidenceValidationError(
                f"competitor_observation entry supports no target paths and "
                f"cannot support target_path '{target_path}'; binding rejected"
            )
        if target_path not in compatible:
            raise EvidenceValidationError(
                f"competitor_observation entry cannot support "
                f"target_path '{target_path}'; compatible: {list(compatible)}"
            )
    else:
        raise EvidenceValidationError(
            f"unknown support_scope '{entry.support_scope}'"
        )

    return AuthoringPrefillClaimBinding(
        target_path=target_path,
        value_pointer=value_pointer,
        catalog_entry_id=catalog_entry_id,
        source_id=rebound_source_id,
        locator=rebound_locator,
        quote_sha256=rebound_quote_sha,
        support_kind=support_kind,  # type: ignore[arg-type]
    )


def _parse_rfc6901_pointer(pointer: str) -> List[str]:
    """Parse a JSON Pointer (RFC 6901) into reference-token segments.

    Strict rules:
    - Pointer must start with ``/`` (non-empty pointer for package bindings).
    - Each segment is separated by ``/``.
    - Within a segment, only ``~0`` (→ ``~``) and ``~1`` (→ ``/``) are valid
      escape sequences.  Any other ``~`` (e.g. ``~2``, ``~a``) raises.
    - Empty segments (``//``) raise.

    Returns the list of decoded segment strings.

    Raises EvidenceValidationError on any violation.
    """
    if not pointer:
        raise EvidenceValidationError("value_pointer is empty")
    if not pointer.startswith("/"):
        raise EvidenceValidationError(
            f"value_pointer '{pointer}' must start with '/'"
        )
    segments: List[str] = []
    # Split on '/' — the first element is always '' because pointer starts with '/'.
    raw_segments = pointer.split("/")[1:]
    for i, raw_seg in enumerate(raw_segments):
        # Reject empty segments: "/", trailing "/", "//", "/x//y".
        if raw_seg == "":
            raise EvidenceValidationError(
                f"value_pointer '{pointer}' contains empty segment at index {i}"
            )
        # Check for illegal tilde sequences before unescaping.
        if "~" in raw_seg:
            # Validate every tilde is followed by exactly 0 or 1.
            for j, ch in enumerate(raw_seg):
                if ch == "~":
                    if j + 1 >= len(raw_seg) or raw_seg[j + 1] not in ("0", "1"):
                        raise EvidenceValidationError(
                            f"value_pointer '{pointer}' contains illegal tilde "
                            f"escape at segment {i}"
                        )
        decoded = raw_seg.replace("~1", "/").replace("~0", "~")
        segments.append(decoded)
    return segments


def _resolve_rfc6901(
    segments: List[str],
    structured_value: Any,
) -> Any:
    """Resolve parsed RFC 6901 segments against *structured_value*.

    Raises EvidenceValidationError on any KeyError/IndexError/TypeError.
    """
    current = structured_value
    for i, seg in enumerate(segments):
        if isinstance(current, dict):
            if seg not in current:
                raise EvidenceValidationError(
                    f"pointer segment '{seg}' not found in dict "
                    f"(segment index {i})"
                )
            current = current[seg]
        elif isinstance(current, list):
            # Must be a valid non-negative integer index.
            if not seg.isdigit():
                if seg == "-":
                    raise EvidenceValidationError(
                        f"pointer segment '-' is not a valid array index "
                        f"(segment index {i})"
                    )
                raise EvidenceValidationError(
                    f"pointer segment '{seg}' is not a valid array index "
                    f"(segment index {i})"
                )
            # Reject leading zeros like "01".
            if len(seg) > 1 and seg.startswith("0"):
                raise EvidenceValidationError(
                    f"pointer segment '{seg}' has leading zero "
                    f"(segment index {i})"
                )
            idx = int(seg)
            if idx < 0 or idx >= len(current):
                raise EvidenceValidationError(
                    f"pointer index {idx} out of bounds "
                    f"(list length {len(current)}, segment index {i})"
                )
            current = current[idx]
        else:
            raise EvidenceValidationError(
                f"cannot descend into {type(current).__name__} "
                f"at segment '{seg}' (segment index {i})"
            )
    return current


def _is_atomic_leaf(value: Any) -> bool:
    """Return True if value is a non-empty atomic scalar (str, bool, int, float).

    None, empty string, list, and dict are NOT atomic leaves.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    # list, dict, and any other type are NOT atomic.
    return False


def _validate_value_pointer(
    pointer: str,
    structured_value: Any,
    expected_target_path: str,
) -> None:
    """Validate that a JSON Pointer resolves to a non-empty atomic leaf.

    The pointer's first decoded segment must equal *expected_target_path*.
    Subsequent segments may descend into nested dicts/lists.

    The resolved value must be a non-empty atomic scalar (str, bool, int,
    float).  Containers (list, dict) are rejected — they are not atomic
    claims.

    Raises EvidenceValidationError on any failure.
    """
    segments = _parse_rfc6901_pointer(pointer)

    if not isinstance(structured_value, dict):
        raise EvidenceValidationError(
            "package structured_value is not a dict; cannot resolve pointer"
        )

    if not segments:
        raise EvidenceValidationError(
            f"value_pointer '{pointer}' has no segments"
        )

    # First segment must match the binding's target_path.
    first_seg = segments[0]
    if first_seg != expected_target_path:
        raise EvidenceValidationError(
            f"value_pointer first segment '{first_seg}' does not match "
            f"binding target_path '{expected_target_path}'"
        )
    if first_seg not in structured_value:
        raise EvidenceValidationError(
            f"value_pointer target_path '{first_seg}' not found "
            f"in structured_value"
        )

    # Resolve full pointer.
    resolved = _resolve_rfc6901(segments, structured_value)

    # Must be an atomic leaf, not a container.
    if not _is_atomic_leaf(resolved):
        if isinstance(resolved, (list, dict)):
            raise EvidenceValidationError(
                f"value_pointer '{pointer}' resolves to a container "
                f"({type(resolved).__name__}), not an atomic leaf"
            )
        raise EvidenceValidationError(
            f"value_pointer '{pointer}' resolves to non-atomic value "
            f"(type={type(resolved).__name__})"
        )


def _entry_source_kind_to_ref(source_kind: str) -> str:
    mapping = {
        "project_fact": "study_definition",
        "synopsis": "synopsis",
        "ctgov_snapshot": "search_snapshot",
        "registered_source": "registry",
        "evidence_brief": "registry",
    }
    return mapping.get(source_kind, "study_definition")


def _append_deduped_evidence_ref(
    refs: List[AuthoringPrefillEvidenceRef],
    ref: AuthoringPrefillEvidenceRef,
) -> None:
    """Append *ref* unless an identical reader-facing reference already exists.

    Multiple claim bindings to the same source quote (same source kind, id,
    locator and quote hash) must render as ONE evidence reference while every
    atomic claim binding is preserved.
    """
    for existing in refs:
        if (
            existing.source_kind == ref.source_kind
            and existing.source_id == ref.source_id
            and existing.locator == ref.locator
            and existing.quote_sha256 == ref.quote_sha256
        ):
            return
    refs.append(ref)


def _enumerate_atomic_leaves(
    value: Any,
    pointer_prefix: str,
) -> List[str]:
    """Enumerate all non-empty atomic leaves reachable from *value*.

    Returns a list of canonical RFC 6901 pointers pointing to each non-empty
    atomic scalar (str, bool, int, float).

    *pointer_prefix* is already a partial RFC 6901 pointer (e.g. ``/picos.x``)
    with escaped segments.  New segments are escaped before appending.
    """
    if _is_atomic_leaf(value):
        return [pointer_prefix]
    if isinstance(value, dict):
        result: List[str] = []
        for k, v in value.items():
            child_pointer = f"{pointer_prefix}/{_escape_pointer_segment(k)}"
            if _is_atomic_leaf(v):
                result.append(child_pointer)
            elif isinstance(v, (dict, list)) and len(v) > 0:
                result.extend(_enumerate_atomic_leaves(v, child_pointer))
        return result
    if isinstance(value, list):
        result = []
        for i, item in enumerate(value):
            child_pointer = f"{pointer_prefix}/{i}"
            if _is_atomic_leaf(item):
                result.append(child_pointer)
            elif isinstance(item, (dict, list)) and len(item) > 0:
                result.extend(_enumerate_atomic_leaves(item, child_pointer))
        return result
    return []


def _escape_pointer_segment(seg: str) -> str:
    """Re-escape a single pointer segment per RFC 6901: ~ → ~0, / → ~1."""
    return seg.replace("~", "~0").replace("/", "~1")


def _build_pointer(parts: List[str]) -> str:
    """Build a canonical RFC 6901 pointer from decoded segment parts."""
    escaped = [_escape_pointer_segment(p) for p in parts]
    return "/" + "/".join(escaped)


def _all_atomic_values_bound(
    structured_value: Any,
    bindings: List[AuthoringPrefillClaimBinding],
    target_paths: List[str],
    is_package: bool,
) -> bool:
    """Check whether every non-empty atomic leaf has at least one binding.

    For package candidates, this recursively enumerates all atomic leaves
    under every target_path in *structured_value*, builds their canonical
    RFC 6901 pointers, and checks that each pointer is covered by at least
    one binding whose ``value_pointer`` matches (after re-escaping).

    For field candidates, a single binding suffices.
    """
    if not is_package:
        return len(bindings) >= 1

    if not isinstance(structured_value, dict):
        return len(bindings) >= 1

    # Collect all bound pointers (normalized to canonical RFC 6901 form).
    bound_pointers: Set[str] = set()
    for b in bindings:
        try:
            segs = _parse_rfc6901_pointer(b.value_pointer)
            bound_pointers.add(_build_pointer(segs))
        except EvidenceValidationError:
            pass

    # Enumerate all atomic leaves under each target_path.
    for tp in target_paths:
        if tp not in structured_value:
            continue
        value = structured_value[tp]
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        leaves = _enumerate_atomic_leaves(value, f"/{tp}")
        for leaf_pointer in leaves:
            if leaf_pointer not in bound_pointers:
                return False
    return True


# ---------------------------------------------------------------------------
# Public stable server-side validation interface (promoted from private
# W2b functions for W3 composite adoption reuse).
# ---------------------------------------------------------------------------


def server_validate_single_binding(
    *,
    binding: AuthoringPrefillClaimBinding,
    entry_lookup: Dict[str, AuthoringPrefillEvidenceCatalogEntry],
    sent_entry_ids: Set[str],
    candidate_target_paths: Set[str],
    structured_value: Any,
    is_package: bool,
) -> AuthoringPrefillClaimBinding:
    """Validate one already-typed claim binding against the server catalog.

    This is the stable public wrapper around ``_validate_and_rebind_single_binding``.
    It accepts a typed ``AuthoringPrefillClaimBinding`` (not a raw dict) and
    performs exactly the same validation: entry existence, sent-entry check,
    target_path membership, support_scope/kind consistency, CT.gov field_key
    compatibility, and strict RFC 6901 value_pointer resolution to a non-empty
    atomic leaf.

    Returns the server-rebound binding on success.
    Raises ``EvidenceValidationError`` on any failure.
    """
    raw_binding = {
        "catalog_entry_id": binding.catalog_entry_id,
        "target_path": binding.target_path,
        "value_pointer": binding.value_pointer,
        "support_kind": binding.support_kind,
    }
    return _validate_and_rebind_single_binding(
        raw_binding=raw_binding,
        entry_lookup=entry_lookup,
        sent_entry_ids=sent_entry_ids,
        candidate_target_paths=candidate_target_paths,
        structured_value=structured_value,
        is_package=is_package,
    )


def server_validate_value_pointer(
    pointer: str,
    structured_value: Any,
    expected_target_path: str,
) -> None:
    """Public wrapper around ``_validate_value_pointer``.

    Validates that a JSON Pointer resolves to a non-empty atomic leaf
    under the expected target path. Raises ``EvidenceValidationError``
    on any failure.
    """
    _validate_value_pointer(pointer, structured_value, expected_target_path)


def server_all_atomic_values_bound(
    structured_value: Any,
    bindings: List[AuthoringPrefillClaimBinding],
    target_paths: List[str],
    is_package: bool,
) -> bool:
    """Public wrapper around ``_all_atomic_values_bound``.

    Returns True if every non-empty atomic leaf under each target_path
    has at least one binding covering it.
    """
    return _all_atomic_values_bound(
        structured_value, bindings, target_paths, is_package,
    )


def server_ctgov_compatible_targets(field_key: str) -> Optional[Tuple[str, ...]]:
    """Public wrapper around ``_ctgov_compatible_targets``.

    Returns the target paths a CT.gov field_key can inform, or None if
    the field_key is unmapped (which means the binding must be rejected).
    """
    return _ctgov_compatible_targets(field_key)


def server_candidate_requires_pending_decision(
    candidate: AuthoringPrefillCandidate,
    entry_lookup: Dict[str, AuthoringPrefillEvidenceCatalogEntry],
) -> bool:
    """True when any claim binding references a round-1 corpus entry whose
    finding was marked ``insufficient_support_do_not_generalize``.

    Such candidates must stay ``recommendation_role="pending_decision"`` and
    can never be adopted automatically.  The adoption verifier rejects any
    persisted candidate that was promoted to ``recommended``/``alternative``.
    """
    for binding in candidate.claim_bindings:
        entry = entry_lookup.get(binding.catalog_entry_id)
        if entry is None:
            continue
        if (
            entry.provenance.get("reuse_decision")
            == INSUFFICIENT_SUPPORT_REUSE_DECISION
        ):
            return True
    return False
