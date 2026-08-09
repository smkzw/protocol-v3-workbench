"""Read-only bridge from the persisted round-1 Protocol corpus analysis to
the authoring-prefill evidence catalog.

W2c-1 boundary: this module performs NO writes, NO AI calls, NO schema
migration and NO table creation.  It loads the immutable corpus-analysis row
(through an injected reader, or a read-only SQLite connection), verifies the
exact journey-bound identity — project, pipeline, snapshot, analysis id,
frozen product AI route — and the persisted output hash, then converts the
eligible source bindings of every finding into immutable
``AuthoringPrefillEvidenceCatalogEntry`` objects.

Competitor semantics are preserved: every corpus entry is
``support_scope="competitor_observation"`` (never ``current_project_fact``)
and the binding layer therefore forces ``support_kind="competitor_option"``
for any claim bound to it.  Exact-fact gates (dose, endpoint, AESI, sample
size, washout) are never weakened: the corpus bridge only surfaces competitor
evidence and the conservative module→target-path allowlist below bounds which
design paths a finding may inform.  Cross-indication structure-only findings
and findings the analysis marked ``conflict_preserved_do_not_select`` support
NO target paths.

Findings marked ``insufficient_support_do_not_generalize`` (the dominant
real-world round-1 outcome: single-source competitor observations) support
the module's bounded paths as explicitly limited review candidates: the
binding layer must require ``recommendation_role="pending_decision"`` for any
candidate bound to them, they stay ``competitor_option`` forever, and they can
never be adopted without a medical-manager override.

Fail-closed rules:

- Any identity field drift (project / pipeline / snapshot / analysis id /
  frozen route identity hash) rejects the whole bridge load.
- Any output-hash drift (persisted hash vs journey-bound hash, or persisted
  hash vs recomputation over the stored analysis payload) rejects the load.
- A journey that is bound to a round-1 analysis but is built without a
  corpus reader raises instead of silently dropping the analysis.
- A bound analysis whose source bindings cannot be verified against the
  immutable source spans/artifacts in the same project (missing span or
  artifact, identity/hash mismatch, invalidated source state) rejects the
  whole load.
- An analysis schema version outside the current corpus contract, or a
  finding module outside the closed analysis-module set, rejects the load.

Determinism: entry ids, quote hashes, source revisions, ordering, truncation
and supported target paths are pure functions of the persisted analysis row
and the catalog id, so generation and later adoption verification rebuild
byte-identical catalog identity from the same authoritative artifact.

Integration contract (W2c): the binding validator must consult
``corpus_module_target_paths`` (via ``entry.provenance["module"]`` /
``["transfer_scope"]`` / ``["pattern_kind"]`` / ``["reuse_decision"]``) when
rebinding ``competitor_observation`` entries whose provenance carries
``analysis_lineage="round1_corpus_analysis"``; entries with no allowed path
must be rejected as bind targets.  Entries whose provenance carries
``reuse_decision="insufficient_support_do_not_generalize"`` additionally
force ``recommendation_role="pending_decision"`` on any candidate bound to
them (never ``recommended``/``alternative``), and the source limitation
fields (``source_count``/``sponsor_count``/``unresolved_gaps``/
``indication_alignment_status``/``limitation_note``) are preserved in the
catalog projection so the AI and reviewer can see why medical judgment is
required.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from packages.contracts.workbench_contracts import (
    AuthoringPrefillEvidenceCatalogEntry,
    MedicalWritingAuthoringJourney,
)

from .medical_writing_corpus_analysis_ai import (
    CORPUS_ANALYSIS_SCHEMA_VERSION,
    CORPUS_ANALYSIS_TABLE,
    _ANALYSIS_MODULES,
    _TRANSFER_SCOPES,
)
from .writing_reference_repository import TENANT_ID


class CorpusPrefillBridgeError(ValueError):
    """Raised when the round-1 corpus-analysis bridge cannot verify identity
    or convert source bindings — the caller must fail closed."""


# ---------------------------------------------------------------------------
# Limits and fixed semantics
# ---------------------------------------------------------------------------

# Existing contract literal closest to a corpus-analysis evidence brief.
# The AI evidence ref kind is resolved by the binding module; corpus entries
# may be mapped to a distinct ref kind there without contract changes.
CORPUS_EVIDENCE_SOURCE_KIND = "evidence_brief"

CORPUS_ANALYSIS_LINEAGE = "round1_corpus_analysis"

MAX_CORPUS_ANALYSIS_ENTRIES = 60
# The corpus service already caps excerpts at 3_200 chars; this guard only
# detects schema drift that would break entry hashing.
MAX_CORPUS_QUOTE_CHARS = 20_000

# Findings the analysis marked conflict-preserved never support target
# paths (they remain visible as context evidence only).  They stay
# unbindable: the analysis itself warns that selecting them would
# contradict preserved competitor evidence.
CONFLICT_PRESERVED_REUSE_DECISIONS = frozenset(
    {"conflict_preserved_do_not_select"}
)

# Single-source competitor observations with insufficient support remain
# available as EXPLICITLY LIMITED review candidates: they support the
# module's bounded paths, but every candidate bound to them must carry
# recommendation_role="pending_decision" and they can never become
# exact_fact / normalized_enum / a current-project fact / an automatically
# adopted recommendation.
INSUFFICIENT_SUPPORT_REUSE_DECISION = "insufficient_support_do_not_generalize"

# Read-only source-binding integrity tables (writing-reference store).
# The bridge only SELECTs from them; it never creates or writes them.
CORPUS_ARTIFACT_TABLE = "writing_reference_document_artifacts"
CORPUS_ARTIFACT_STATE_TABLE = "writing_reference_document_state"
CORPUS_SPAN_TABLE = "writing_reference_source_spans"

# Findings about wording conventions or regulatory fixed structure are
# writing-style evidence, not clinical design evidence.
_NON_DESIGN_PATTERN_KINDS = frozenset(
    {"wording_convention", "regulatory_common_structure"}
)


# ---------------------------------------------------------------------------
# Conservative module → target-path allowlist.
#
# Every path listed here exists in the deterministic prefill package or the
# eligible field set.  The mapping is intentionally narrow: a corpus module
# may only inform paths its clinical content can legitimately participate in,
# and every admission remains a competitor_option, never an exact_fact.
# ---------------------------------------------------------------------------

CORPUS_MODULE_TARGET_PATHS: Dict[str, Tuple[str, ...]] = {
    "objectives_endpoints": (
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
    ),
    "eligibility": (
        "picos.population_summary",
        "picos.inclusion_modules",
        "picos.exclusion_modules",
        "picos.washout_rules",
    ),
    "intervention": (
        "picos.intervention_summary",
        "picos.intervention_dose_regimen",
        "picos.required_background_rules",
        "picos.allowed_concomitant_rules",
        "picos.prohibited_concomitant_rules",
        "picos.assessment_timing_restrictions",
    ),
    "comparator": (
        "picos.comparator_summary",
    ),
    "safety": (
        "picos.safety_endpoints",
        "picos.aesi_definitions",
        "picos.assessment_instruments",
    ),
    "schedule": (
        "picos.study_epochs",
        "picos.visit_strategy",
        "picos.assessment_timing_restrictions",
    ),
    "statistics": (
        "picos.sample_size_strategy",
        "picos.statistical_strategy",
        "picos.estimand_strategy",
        "picos.design_archetype",
    ),
    "design": (
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
        "design.phase1_parts",
        "picos.design_archetype",
    ),
    # Cross-indication structure / regulatory commonality findings describe
    # competitor document structure, not current-project design content.
    # They support NO prefill target path and stay context evidence only.
    "structure": (),
    "regulatory_commonality": (),
}


# ---------------------------------------------------------------------------
# Helpers (identical canonicalization to the corpus analysis service)
# ---------------------------------------------------------------------------


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def analysis_output_hash(analysis_payload: Dict[str, Any]) -> str:
    """Deterministic hash of a persisted analysis payload.

    Byte-identical to the corpus service's ``_hash_json`` over the validated
    output: ``json.dumps(..., ensure_ascii=False, sort_keys=True,
    separators=(",", ":"))`` + sha256 hex.
    """
    return _sha256_hex(_canonical_json(analysis_payload))


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _corpus_entry_id(
    catalog_id: str,
    source_id: str,
    locator: str,
    quote_sha256: str,
    finding_id: str,
) -> str:
    """Stable entry id scoped per (source, locator, quote, finding).

    Distinct from the generic catalog entry-id scheme: the same source
    excerpt supporting two different findings yields two distinct entries,
    each carrying its own finding lineage.
    """
    raw = (
        f"corpus|{catalog_id}|{source_id}|{locator}|{quote_sha256}|{finding_id}"
    )
    return _sha256_hex(raw)[:32]


# ---------------------------------------------------------------------------
# Dual-count reword of the analysis-derived qualifying gaps
# ---------------------------------------------------------------------------

# The persisted analysis finding states the *qualifying* independent-source
# count ("服务器校验：独立来源不足（当前0，至少需要2）…"), which reads as if no
# source existed even when one bound original source is visible on the same
# panel.  These rewrites make the qualifying semantics explicit; the live
# bound-source count is appended separately by the binding layer at the
# display boundary.  The upstream analysis payload is never altered.
_QUALIFYING_SOURCE_GAP_RE = re.compile(
    r"服务器校验：独立来源不足（当前(\d+)，至少需要2）"
)
_QUALIFYING_SPONSOR_GAP_RE = re.compile(
    r"服务器校验：独立申办方不足（当前(\d+)，至少需要2）"
)


def reword_qualifying_support_gap(gap: str) -> str:
    """Reword an analysis-derived qualifying-count gap at the display boundary.

    ``服务器校验：独立来源不足（当前N，至少需要2）；…`` becomes
    ``可计入本结论通用化门槛的独立来源：N/2；…`` (sponsor variant likewise),
    keeping the trailing context.  Unrelated gap text passes through
    unchanged.
    """
    value = str(gap or "")
    match = _QUALIFYING_SOURCE_GAP_RE.search(value)
    if match:
        return (
            f"可计入本结论通用化门槛的独立来源：{match.group(1)}/2"
            + value[match.end():]
        )
    match = _QUALIFYING_SPONSOR_GAP_RE.search(value)
    if match:
        return (
            f"可计入本结论通用化门槛的独立申办方：{match.group(1)}/2"
            + value[match.end():]
        )
    return value


# ---------------------------------------------------------------------------
# Journey-bound identity
# ---------------------------------------------------------------------------


def bound_round1_analysis_identity(
    journey: MedicalWritingAuthoringJourney,
) -> Optional[Dict[str, Any]]:
    """Extract the exact round-1 analysis identity bound to *journey*.

    The identity lives in the persisted research-pipeline state on the
    journey row (``round1_analysis_id``, ``round1_analysis_output_hash``,
    ``pipeline_id``, ``snapshot_id``, ``round1_ai_route``).  The pipeline
    writes these five fields together only after the analysis row was
    persisted.

    Returns None when the journey is not bound to a round-1 analysis.
    Raises ``CorpusPrefillBridgeError`` when the binding is partial or
    malformed — a bound journey must carry the complete identity.
    """
    raw = getattr(journey, "research_pipeline", None)
    if raw is None:
        return None
    if isinstance(raw, dict):
        state: Any = raw
    elif hasattr(raw, "as_dict") and callable(raw.as_dict):
        state = raw.as_dict()
    else:
        state = vars(raw) if not isinstance(raw, str) else {}

    def _field(name: str) -> Any:
        if isinstance(state, dict):
            return state.get(name)
        return getattr(state, name, None)

    analysis_id = _clean(_field("round1_analysis_id"))
    if not analysis_id:
        return None

    pipeline_id = _clean(_field("pipeline_id"))
    snapshot_id = _clean(_field("snapshot_id"))
    output_hash = _clean(_field("round1_analysis_output_hash")).lower()
    ai_route = _field("round1_ai_route")
    if (
        not pipeline_id
        or not snapshot_id
        or not output_hash
        or not isinstance(ai_route, dict)
        or not ai_route
    ):
        raise CorpusPrefillBridgeError(
            "journey round-1 corpus-analysis binding is incomplete "
            "(requires pipeline_id, snapshot_id, round1_analysis_id, "
            "round1_analysis_output_hash and round1_ai_route); fail closed"
        )
    route_hash = _clean(ai_route.get("identity_hash")).lower()
    if not route_hash:
        raise CorpusPrefillBridgeError(
            "journey round-1 corpus-analysis frozen route has no "
            "identity_hash; fail closed"
        )
    return {
        "pipeline_id": pipeline_id,
        "snapshot_id": snapshot_id,
        "analysis_id": analysis_id,
        "output_hash": output_hash,
        "ai_route": ai_route,
    }


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_round1_analysis(
    analysis_row: Any,
    identity: Dict[str, Any],
    project_id: str,
) -> None:
    """Verify the persisted analysis row against the journey-bound identity.

    Raises ``CorpusPrefillBridgeError`` on any drift.  Every check is
    independent; a single mismatch rejects the whole load.
    """
    if not isinstance(analysis_row, dict):
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis row is not a JSON object"
        )
    for key in (
        "project_id",
        "analysis_id",
        "pipeline_id",
        "snapshot_id",
        "status",
        "output_hash",
        "ai_route",
        "analysis",
    ):
        if key not in analysis_row:
            raise CorpusPrefillBridgeError(
                f"round-1 corpus analysis row is missing '{key}'"
            )

    field_checks = (
        ("project_id", identity.get("project_id", project_id)),
        ("analysis_id", identity["analysis_id"]),
        ("pipeline_id", identity["pipeline_id"]),
        ("snapshot_id", identity["snapshot_id"]),
    )
    for field, expected in field_checks:
        actual = _clean(analysis_row[field])
        if actual != expected:
            raise CorpusPrefillBridgeError(
                f"round-1 corpus analysis {field} mismatch: expected "
                f"'{expected}', got '{actual}'"
            )

    if _clean(analysis_row["status"]) != "completed":
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis status is not 'completed': "
            f"'{_clean(analysis_row['status'])}'"
        )

    stored_hash = _clean(analysis_row["output_hash"]).lower()
    if stored_hash != identity["output_hash"]:
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis output_hash mismatch: journey-bound "
            f"'{identity['output_hash']}', persisted '{stored_hash}'"
        )

    route = analysis_row["ai_route"]
    if not isinstance(route, dict) or not route:
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis has no frozen AI route"
        )
    if _canonical_json(route) != _canonical_json(identity["ai_route"]):
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis frozen AI route does not match the "
            "journey-bound route"
        )

    payload = analysis_row["analysis"]
    if not isinstance(payload, dict):
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis payload is not an object"
        )
    recomputed = analysis_output_hash(payload)
    if recomputed != stored_hash:
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis output hash recomputation mismatch; "
            "persisted payload was altered or hashed by a different "
            "canonicalization"
        )
    if _clean(payload.get("analysis_id")) != identity["analysis_id"]:
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis payload analysis_id does not match "
            "the row identity"
        )
    if _clean(payload.get("schema_version")) != CORPUS_ANALYSIS_SCHEMA_VERSION:
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis payload schema_version "
            f"'{_clean(payload.get('schema_version'))}' is not the current "
            f"'{CORPUS_ANALYSIS_SCHEMA_VERSION}'; fail closed"
        )
    if not isinstance(payload.get("findings"), list):
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis payload findings must be an array"
        )


# ---------------------------------------------------------------------------
# Conservative module → target-path compatibility
# ---------------------------------------------------------------------------


def corpus_module_target_paths(
    module: str,
    *,
    transfer_scope: str,
    pattern_kind: Optional[str] = None,
    reuse_decision: Optional[str] = None,
) -> Tuple[str, ...]:
    """Return the prefill target paths a corpus finding may support.

    Conservative gates, applied in order:

    1. Cross-indication structure-only findings never support clinical
       design paths.
    2. Wording-convention and regulatory-common-structure findings are
       writing-style evidence and support no design paths.
    3. Findings the analysis marked conflict-preserved (selecting them
       would contradict preserved competitor evidence) support no paths.
    4. Unknown modules raise — the closed module set is part of the
       analysis schema contract.

    Findings marked ``insufficient_support_do_not_generalize`` pass through
    the module allowlist: they remain available as explicitly limited
    ``competitor_option`` review candidates (never exact_fact, never
    current-project facts), and the binding layer must force
    ``recommendation_role="pending_decision"`` on candidates bound to them.

    Every admitted path remains a competitor_option admission; the binding
    layer must apply this same function when rebinding corpus entries.
    """
    if transfer_scope == "cross_indication_structure_only":
        return ()
    if pattern_kind in _NON_DESIGN_PATTERN_KINDS:
        return ()
    if reuse_decision in CONFLICT_PRESERVED_REUSE_DECISIONS:
        return ()
    paths = CORPUS_MODULE_TARGET_PATHS.get(module)
    if paths is None:
        raise CorpusPrefillBridgeError(
            f"unknown corpus analysis module: '{module}'"
        )
    return tuple(paths)


# ---------------------------------------------------------------------------
# Deterministic entry conversion
# ---------------------------------------------------------------------------


def build_corpus_analysis_entries(
    analysis_row: Dict[str, Any],
    catalog_id: str,
    truncation_notes: Optional[List[str]] = None,
) -> List[AuthoringPrefillEvidenceCatalogEntry]:
    """Convert the verified analysis row into immutable catalog entries.

    One entry per (finding, evidence binding): every entry retains the
    source id, locator, source-text hash and document hash, the finding id,
    and the full analysis lineage (analysis id + persisted output hash).
    Ordering is deterministic: findings sorted by finding_id, bindings in
    their persisted order.  Truncation applies after that stable ordering.

    The caller must have verified identity and output hash first
    (``verify_round1_analysis`` / ``load_bound_round1_analysis``).
    """
    if truncation_notes is None:
        truncation_notes = []
    payload = analysis_row["analysis"]
    analysis_id = _clean(analysis_row["analysis_id"])
    stored_hash = _clean(analysis_row["output_hash"]).lower()

    findings = sorted(
        payload["findings"],
        key=lambda finding: _clean(finding.get("finding_id")),
    )

    entries: List[AuthoringPrefillEvidenceCatalogEntry] = []
    for finding in findings:
        if not isinstance(finding, dict):
            raise CorpusPrefillBridgeError(
                "corpus analysis finding is not an object"
            )
        finding_id = _clean(finding.get("finding_id"))
        module = _clean(finding.get("module"))
        transfer_scope = _clean(finding.get("transfer_scope"))
        pattern_kind = _clean(finding.get("pattern_kind"))
        reuse_decision = _clean(finding.get("reuse_decision"))
        if not finding_id:
            raise CorpusPrefillBridgeError(
                "corpus analysis finding has no finding_id"
            )
        if module not in _ANALYSIS_MODULES:
            raise CorpusPrefillBridgeError(
                f"corpus analysis finding '{finding_id}' has unknown "
                f"module '{module}'"
            )
        if transfer_scope not in _TRANSFER_SCOPES:
            raise CorpusPrefillBridgeError(
                f"corpus analysis finding '{finding_id}' has unknown "
                f"transfer_scope '{transfer_scope}'"
            )
        target_paths = corpus_module_target_paths(
            module,
            transfer_scope=transfer_scope,
            pattern_kind=pattern_kind,
            reuse_decision=reuse_decision,
        )

        bindings = finding.get("evidence_bindings")
        if not isinstance(bindings, list):
            raise CorpusPrefillBridgeError(
                f"corpus analysis finding '{finding_id}' evidence_bindings "
                "must be an array"
            )
        for binding in bindings:
            if len(entries) >= MAX_CORPUS_ANALYSIS_ENTRIES:
                truncation_notes.append(
                    f"第一轮语料分析证据条目已达上限"
                    f"{MAX_CORPUS_ANALYSIS_ENTRIES}条，后续绑定已截断"
                )
                return entries
            if not isinstance(binding, dict):
                raise CorpusPrefillBridgeError(
                    f"corpus analysis finding '{finding_id}' has a "
                    "non-object evidence binding"
                )
            excerpt = binding.get("source_excerpt")
            source_id = _clean(binding.get("source_id"))
            evidence_id = _clean(binding.get("evidence_id"))
            if (
                not evidence_id
                or not isinstance(excerpt, str)
                or not excerpt.strip()
                or not source_id
            ):
                raise CorpusPrefillBridgeError(
                    f"corpus analysis finding '{finding_id}' binding "
                    "is missing source_excerpt/source_id/evidence_id; "
                    "fail closed"
                )
            if len(excerpt) > MAX_CORPUS_QUOTE_CHARS:
                raise CorpusPrefillBridgeError(
                    f"corpus analysis finding '{finding_id}' excerpt "
                    f"exceeds {MAX_CORPUS_QUOTE_CHARS} chars; schema drift"
                )

            locator = _clean(binding.get("locator"))
            quote_sha = _sha256_hex(excerpt)
            entry_id = _corpus_entry_id(
                catalog_id,
                source_id,
                locator,
                quote_sha,
                finding_id,
            )
            if any(e.catalog_entry_id == entry_id for e in entries):
                # Same finding cannot repeat an evidence id (server
                # validation), but keep conversion idempotent regardless.
                continue

            document_sha = _clean(binding.get("document_sha256")).lower()
            source_text_sha = _clean(
                binding.get("source_text_sha256")
            ).lower()

            # Source-specific limitation data: single-source findings must
            # stay visible as limited review candidates.  These fields are
            # forwarded by the binding-layer projection so the AI and the
            # reviewer can see why medical judgment is required.
            support = finding.get("support")
            source_count = 0
            sponsor_count = 0
            if isinstance(support, dict):
                try:
                    source_count = int(support.get("source_count") or 0)
                except (TypeError, ValueError):
                    source_count = 0
                try:
                    sponsor_count = int(support.get("sponsor_count") or 0)
                except (TypeError, ValueError):
                    sponsor_count = 0
            unresolved_gaps = finding.get("unresolved_gaps")
            if not isinstance(unresolved_gaps, list):
                unresolved_gaps = []
            unresolved_gaps = [
                reword_qualifying_support_gap(str(gap))
                for gap in unresolved_gaps[:20]
                if str(gap).strip()
            ]
            indication_alignment_status = _clean(
                finding.get("indication_alignment_status")
            )
            if reuse_decision == INSUFFICIENT_SUPPORT_REUSE_DECISION:
                limitation_note = (
                    "单一来源竞品观察，支持不足，不可推广为当前项目事实；"
                    "仅可作为待医学经理决策的候选选项（pending_decision）。"
                )
            elif reuse_decision in CONFLICT_PRESERVED_REUSE_DECISIONS:
                limitation_note = (
                    "分析标记为冲突保留（do_not_select），不可选为设计候选。"
                )
            else:
                limitation_note = ""

            entries.append(
                AuthoringPrefillEvidenceCatalogEntry(
                    catalog_entry_id=entry_id,
                    catalog_id=catalog_id,
                    source_kind=CORPUS_EVIDENCE_SOURCE_KIND,
                    source_id=source_id,
                    source_revision=(
                        f"analysis:{analysis_id}:doc:"
                        f"{document_sha[:16] or 'none'}"
                    ),
                    locator=locator,
                    quote=excerpt,
                    quote_sha256=quote_sha,
                    title=f"第一轮语料分析证据：{module}",
                    support_scope="competitor_observation",
                    supported_target_paths=list(target_paths),
                    provenance={
                        "analysis_lineage": CORPUS_ANALYSIS_LINEAGE,
                        "analysis_id": analysis_id,
                        "analysis_output_hash": stored_hash,
                        "finding_id": finding_id,
                        "module": module,
                        "pattern_kind": pattern_kind,
                        "transfer_scope": transfer_scope,
                        "content_role": _clean(
                            finding.get("content_role")
                        ),
                        "evidence_tier": _clean(finding.get("evidence_tier")),
                        "reuse_decision": reuse_decision,
                        "evidence_id": evidence_id,
                        "span_id": _clean(binding.get("span_id")),
                        "nct_id": _clean(binding.get("nct_id")),
                        "document_sha256": document_sha,
                        "source_text_sha256": source_text_sha,
                        "indication_relation": _clean(
                            binding.get("indication_relation")
                        ),
                        "source_count": source_count,
                        "sponsor_count": sponsor_count,
                        "unresolved_gaps": unresolved_gaps,
                        "indication_alignment_status": indication_alignment_status,
                        "limitation_note": limitation_note,
                    },
                )
            )
    return entries


# ---------------------------------------------------------------------------
# Combined load: identity extraction + read + verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifiedRound1CorpusAnalysis:
    """A round-1 analysis row whose journey-bound identity and output hash
    were fully verified."""

    analysis_row: Dict[str, Any]
    identity: Dict[str, Any]


def load_bound_round1_analysis(
    journey: MedicalWritingAuthoringJourney,
    analysis_reader: Callable[[str, str], Optional[Dict[str, Any]]],
    *,
    source_reader: Optional[
        Callable[[str, str, str], Optional[Dict[str, Any]]]
    ] = None,
) -> Optional[VerifiedRound1CorpusAnalysis]:
    """Read and verify the round-1 analysis bound to *journey*.

    ``analysis_reader(project_id, analysis_id)`` is a read-only lookup that
    returns the persisted analysis row dict (as produced by
    ``MedicalWritingCorpusAnalysisAiService.get_analysis``) or None.

    ``source_reader(project_id, source_id, span_id)`` is an optional read-only
    span/artifact composite lookup; when provided, every persisted binding is
    additionally verified against the immutable source span and document
    artifact in the same project — a missing span/artifact, identity or hash
    mismatch, or an invalidated source state fails the whole load.

    Returns None when the journey is not bound to a round-1 analysis.
    Raises ``CorpusPrefillBridgeError`` when the row is missing or any
    identity/hash/source-binding check fails — the caller must fail closed.
    """
    identity = bound_round1_analysis_identity(journey)
    if identity is None:
        return None
    project_id = _clean(getattr(journey, "project_id", ""))
    if not project_id:
        raise CorpusPrefillBridgeError(
            "journey has no project_id for round-1 corpus analysis binding"
        )
    identity = dict(identity)
    identity["project_id"] = project_id

    if not callable(analysis_reader):
        raise CorpusPrefillBridgeError(
            "journey is bound to a round-1 corpus analysis but no read-only "
            "analysis reader was provided; fail closed"
        )
    analysis_row = analysis_reader(project_id, identity["analysis_id"])
    if analysis_row is None:
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis row is missing from the writing "
            f"reference store: {identity['analysis_id']}"
        )
    verify_round1_analysis(analysis_row, identity, project_id)
    if source_reader is not None:
        verify_analysis_source_bindings(
            analysis_row,
            project_id=project_id,
            source_reader=source_reader,
        )
    return VerifiedRound1CorpusAnalysis(
        analysis_row=analysis_row,
        identity=identity,
    )


# ---------------------------------------------------------------------------
# Read-only SQLite reader (no DDL, no writes, URI mode=ro)
# ---------------------------------------------------------------------------


def read_only_analysis_reader(
    db_path: Any,
) -> Callable[[str, str], Optional[Dict[str, Any]]]:
    """Build a read-only corpus-analysis row reader over *db_path*.

    Opens SQLite in ``mode=ro`` URI form so the bridge can never create the
    database, run DDL or take a write lock.  Raises ``CorpusPrefillBridgeError``
    when the path is unusable.
    """
    path = str(db_path)
    if not path:
        raise CorpusPrefillBridgeError(
            "writing-reference repository has no db_path for the read-only "
            "corpus analysis reader"
        )

    def _reader(project_id: str, analysis_id: str) -> Optional[Dict[str, Any]]:
        try:
            connection = sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, timeout=10.0
            )
        except sqlite3.Error as exc:
            raise CorpusPrefillBridgeError(
                f"cannot open writing-reference store read-only: {exc}"
            ) from exc
        try:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                f"""
                SELECT result_json
                FROM {CORPUS_ANALYSIS_TABLE}
                WHERE tenant_id=? AND project_id=? AND analysis_id=?
                """,
                (TENANT_ID, project_id, analysis_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CorpusPrefillBridgeError(
                f"read-only corpus analysis lookup failed: {exc}"
            ) from exc
        finally:
            connection.close()
        if row is None:
            return None
        return json.loads(str(row["result_json"]))

    return _reader


def corpus_analysis_reader_for_repository(
    repository: Any,
) -> Callable[[str, str], Optional[Dict[str, Any]]]:
    """Build the read-only reader from a writing-reference repository."""
    db_path = getattr(repository, "db_path", None)
    return read_only_analysis_reader(db_path)


# ---------------------------------------------------------------------------
# Source-binding integrity verification (read-only)
# ---------------------------------------------------------------------------


def verify_analysis_source_bindings(
    analysis_row: Dict[str, Any],
    *,
    project_id: str,
    source_reader: Callable[[str, str, str], Optional[Dict[str, Any]]],
) -> None:
    """Verify every persisted evidence binding resolves to the immutable
    source span and document artifact in the same project.

    ``source_reader(project_id, source_id, span_id)`` returns a composite
    dict (``artifact_content_sha256``, ``source_current``, ``span_artifact_id``,
    ``span_source_text_sha256``) or None when any row is missing.  Any of the
    following rejects the whole load (fail closed):

    - missing artifact row, artifact source-state row, or span row;
    - span belongs to a different artifact than the binding's source_id;
    - artifact content hash != binding document_sha256;
    - span source_text hash != binding source_text_sha256;
    - binding locator != the immutable span's own source_locator;
    - span payload carries no locator (schema drift);
    - artifact source state is not current (invalidated / unknown).

    Read-only SQL/repository access only: this function never writes, runs
    DDL or creates tables.
    """
    if not callable(source_reader):
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis source verification requires a "
            "read-only source reader; fail closed"
        )
    payload = analysis_row.get("analysis")
    if not isinstance(payload, dict):
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis payload is not an object"
        )
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise CorpusPrefillBridgeError(
            "round-1 corpus analysis payload findings must be an array"
        )
    for finding in findings:
        if not isinstance(finding, dict):
            raise CorpusPrefillBridgeError(
                "corpus analysis finding is not an object"
            )
        bindings = finding.get("evidence_bindings")
        if not isinstance(bindings, list):
            raise CorpusPrefillBridgeError(
                "corpus analysis finding "
                f"'{_clean(finding.get('finding_id'))}' evidence_bindings "
                "must be an array"
            )
        for binding in bindings:
            if not isinstance(binding, dict):
                raise CorpusPrefillBridgeError(
                    "corpus analysis finding has a non-object evidence binding"
                )
            source_id = _clean(binding.get("source_id"))
            span_id = _clean(binding.get("span_id"))
            doc_sha = _clean(binding.get("document_sha256")).lower()
            text_sha = _clean(binding.get("source_text_sha256")).lower()
            if not source_id or not span_id or not doc_sha or not text_sha:
                raise CorpusPrefillBridgeError(
                    "corpus analysis binding is missing source_id/span_id/"
                    "document_sha256/source_text_sha256; fail closed"
                )
            source = source_reader(project_id, source_id, span_id)
            if source is None:
                raise CorpusPrefillBridgeError(
                    "corpus analysis binding cannot resolve to the immutable "
                    f"source span/artifact: source_id='{source_id}' "
                    f"span_id='{span_id}'"
                )
            if not isinstance(source, dict):
                raise CorpusPrefillBridgeError(
                    "corpus analysis source reader returned a non-object"
                )
            artifact_content_sha = _clean(
                source.get("artifact_content_sha256")
            ).lower()
            span_artifact_id = _clean(source.get("span_artifact_id"))
            span_text_sha = _clean(source.get("span_source_text_sha256")).lower()
            if (
                not artifact_content_sha
                or not span_artifact_id
                or not span_text_sha
            ):
                raise CorpusPrefillBridgeError(
                    "corpus analysis source composite is missing artifact "
                    "hash / span artifact id / span text hash; fail closed"
                )
            if span_artifact_id != source_id:
                raise CorpusPrefillBridgeError(
                    f"corpus analysis binding span '{span_id}' belongs to "
                    f"artifact '{span_artifact_id}', not '{source_id}'"
                )
            if artifact_content_sha != doc_sha:
                raise CorpusPrefillBridgeError(
                    "corpus analysis binding document_sha256 mismatch: "
                    f"persisted '{doc_sha}', artifact "
                    f"'{artifact_content_sha}'"
                )
            if span_text_sha != text_sha:
                raise CorpusPrefillBridgeError(
                    "corpus analysis binding source_text_sha256 mismatch for "
                    f"span '{span_id}': persisted '{text_sha}', span "
                    f"'{span_text_sha}'"
                )
            # The persisted binding locator must equal the immutable span's
            # own locator: a binding whose page/block locator drifted from
            # the span row is not the same source excerpt.  A span payload
            # without a locator is schema drift and fails closed too.
            span_locator = _clean(source.get("span_source_locator"))
            if not span_locator:
                raise CorpusPrefillBridgeError(
                    "corpus analysis source composite is missing the "
                    "immutable span locator; fail closed"
                )
            binding_locator = _clean(binding.get("locator"))
            if binding_locator != span_locator:
                raise CorpusPrefillBridgeError(
                    "corpus analysis binding locator mismatch: persisted "
                    f"'{binding_locator}', immutable span '{span_locator}'"
                )
            if source.get("source_current") is not True:
                raise CorpusPrefillBridgeError(
                    "corpus analysis binding source is not current "
                    f"(invalidated or unknown state): artifact '{source_id}'"
                )


def read_only_source_binding_reader(
    db_path: Any,
) -> Callable[[str, str, str], Optional[Dict[str, Any]]]:
    """Build a read-only span/artifact composite reader over *db_path*.

    Runs three pure SELECTs (document artifact, artifact source state, span
    payload) in a single ``mode=ro`` connection; never creates the database,
    runs DDL or takes a write lock.  Returns None when any row is missing;
    raises ``CorpusPrefillBridgeError`` on unusable path or invalid payload.
    """
    path = str(db_path)
    if not path:
        raise CorpusPrefillBridgeError(
            "writing-reference repository has no db_path for the read-only "
            "source binding reader"
        )

    def _reader(
        project_id: str, source_id: str, span_id: str
    ) -> Optional[Dict[str, Any]]:
        try:
            connection = sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, timeout=10.0
            )
        except sqlite3.Error as exc:
            raise CorpusPrefillBridgeError(
                f"cannot open writing-reference store read-only: {exc}"
            ) from exc
        try:
            connection.row_factory = sqlite3.Row
            artifact = connection.execute(
                f"""
                SELECT content_sha256
                FROM {CORPUS_ARTIFACT_TABLE}
                WHERE tenant_id=? AND project_id=? AND artifact_id=?
                """,
                (TENANT_ID, project_id, source_id),
            ).fetchone()
            state = connection.execute(
                f"""
                SELECT source_current
                FROM {CORPUS_ARTIFACT_STATE_TABLE}
                WHERE tenant_id=? AND project_id=? AND artifact_id=?
                """,
                (TENANT_ID, project_id, source_id),
            ).fetchone()
            span = connection.execute(
                f"""
                SELECT artifact_id, payload_json
                FROM {CORPUS_SPAN_TABLE}
                WHERE tenant_id=? AND project_id=? AND span_id=?
                """,
                (TENANT_ID, project_id, span_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CorpusPrefillBridgeError(
                f"read-only corpus source binding lookup failed: {exc}"
            ) from exc
        finally:
            connection.close()
        if artifact is None or state is None or span is None:
            return None
        try:
            span_payload = json.loads(str(span["payload_json"]))
        except (TypeError, ValueError):
            raise CorpusPrefillBridgeError(
                f"corpus source span '{span_id}' payload is not valid JSON"
            )
        if not isinstance(span_payload, dict):
            raise CorpusPrefillBridgeError(
                f"corpus source span '{span_id}' payload is not an object"
            )
        return {
            "artifact_content_sha256": str(artifact["content_sha256"]),
            "source_current": bool(int(state["source_current"])),
            "span_artifact_id": _clean(span["artifact_id"]),
            "span_source_text_sha256": _clean(
                span_payload.get("source_text_sha256")
            ),
            "span_source_locator": _clean(
                span_payload.get("source_locator")
            ),
        }

    return _reader


def corpus_source_reader_for_repository(
    repository: Any,
) -> Callable[[str, str, str], Optional[Dict[str, Any]]]:
    """Build the read-only source-binding reader from a writing-reference
    repository (same store as the analysis reader)."""
    db_path = getattr(repository, "db_path", None)
    return read_only_source_binding_reader(db_path)
