from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Callable

logger = logging.getLogger(__name__)

from packages.contracts.workbench_contracts.models import (
    ChapterIntegrationResult,
    ChapterIntegrationWindow,
    CompositePipelineRun,
    CompositePipelineRunStage,
    DocumentStructurePlan,
    DocumentStructurePlanChapter,
    TranslationChunkRecord,
    WritingReferenceExtractedSpan,
    WritingReferenceTranslationBatch,
    WritingReferenceTranslationBatchAnchorSummary,
    WritingReferenceTranslationBatchCounts,
    WritingReferenceTranslationBatchCreateRequest,
    WritingReferenceTranslationBatchExclusion,
    WritingReferenceTranslationBatchItem,
    WritingReferenceTranslationBatchPreview,
    WritingReferenceTranslationBatchPreviewRequest,
    WritingReferenceTranslationBatchRetryRequest,
    WritingReferenceTranslationDownstreamTransitionRecord,
    WritingReferenceTranslationDownstreamTransitionRequest,
    WritingReferenceTranslationDownstreamTransitionState,
    WritingReferenceTranslationRequest,
    WritingReferenceTranslationRevision,
)

from .writing_reference import (
    COMPOSITE_TRANSLATION_BODY_MODEL,
    COMPOSITE_TRANSLATION_CONTRACT_HASH,
    COMPOSITE_TRANSLATION_PROMPT_VERSION,
    COMPOSITE_TRANSLATION_SCHEMA_VERSION,
    COMPOSITE_TRANSLATION_TASK_TYPE,
    DEFAULT_REGULATORY_TRANSLATION_INSTRUCTION,
    REGULATORY_TRANSLATION_CONTRACT_HASH,
    REGULATORY_TRANSLATION_PROMPT_VERSION,
    REGULATORY_TRANSLATION_SCHEMA_VERSION,
    render_regulatory_translation_glossary_contract,
)
from .chapter_translation_pipeline import (
    ChapterTranslationPipeline,
    CompositePipelineUnavailableError,
    DocumentPlanRequest,
    DocumentPlanValidationError,
    FidelityBlockedError,
    INTEGRATION_PROVIDER_INPUT_LIMIT,
    TRANSLATION_CONTRACT_FINGERPRINT,
    TranslationPipelineStage,
    TranslationUnit,
    WRITING_REFERENCE_OCR_MAX_CONCURRENCY,
    WRITING_REFERENCE_OCR_MIN_DPI,
    HY_MT2_MODEL_ID,
    FLASH_PLANNING_MODEL,
    FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
    FLASH_QC_MODEL,
    FLASH_PLANNING_PROMPT_VERSION,
    FLASH_QC_PROMPT_VERSION,
    HY_MT2_PROMPT_VERSION,
    PRO_UPPER_LAYER_MODEL,
    PLANNER_CONTRACT_TRANSITION_VERSION,
    SERVER_CONTRACT_MIGRATION_NAMESPACE,
    TRANSLATION_ALIGNMENT_CONTRACT,
    UPPER_LAYER_DOCUMENT_PLANNING,
    UPPER_LAYER_POST_HY_INTEGRATION_QC,
    UpperLayerStageExecutionResult,
    UpperLayerStageOwner,
    _planner_contract_fingerprint,
    _sha256 as _pipeline_sha256,
    build_document_planner_input,
    build_document_planner_segments,
    build_deterministic_document_plan_fallback,
    build_anchor_grouped_document_plan_fallback,
    build_chunks_from_plan,
    _make_chunk,
    build_integration_windows,
    contains_unit_markers,
    evaluate_translation_fidelity_aligned_units,
    integrate_units_with_flash,
    reassemble_aligned_translation,
    reconstruct_unit_map,
    split_source_into_units,
    strip_unit_markers,
    translate_units_with_bounded_correction,
    validate_document_plan,
    canonicalize_persisted_document_plan_chapters,
    _upper_layer_hash_payload,
)
from .writing_reference_repository import (
    TENANT_ID,
    WritingReferenceConflictError,
    WritingReferenceRepository,
)
from .writing_reference_protocol_scope import protocol_corpus_span_scope


REFERENCE_TRANSLATION_JOB_TYPE = "reference_translation"
DOWNSTREAM_CONTRACT_TRANSITION_VERSION = (
    "downstream_translation_contract_transition_v1"
)
DOWNSTREAM_CONTRACT_PLAN_NAMESPACE = (
    "server_downstream_translation_contract_transition_v1"
)
DOWNSTREAM_MODEL_CALL_STAGES = frozenset(
    {
        TranslationPipelineStage.TRANSLATING_HY_MT2.value,
        TranslationPipelineStage.INTEGRATION_QC.value,
    }
)


TERMINAL_PREPARATION_STATUSES = {
    "completed",
    "completed_with_review_required",
    "completed_with_manual_upload_required",
    "partial_failure",
    "failed",
}
FAILED_ITEM_STATUSES = {"failed_retryable", "failed_terminal"}
DOCUMENT_PLAN_RETRY_PARENT_STATUSES = {
    "failed_retryable",
    "failed_escalatable",
    "failed_terminal",
    "interrupted",
}
EXCLUSION_EXAMPLE_LIMIT = 4

# A malformed planner structure is recoverable from the immutable extracted
# M11 segments; a provider/runtime failure is not.  Keep this allow-list
# deliberately narrow so a transport, route, or model failure can never be
# silently replaced by a deterministic plan.
_STRUCTURAL_PLANNER_FAILURE_CODES = frozenset(
    {
        "flash_planner_structural_failure",
        "document_plan_failed_earlier_in_same_run",
        "planning_chapters_missing",
        "planning_document_role_missing",
        "planner_missing_required_boundary",
        "planner_output_not_structured",
        "planner_duplicate_chapter_identity",
        "planner_range_out_of_bounds",
        "planner_range_overlap",
        "planner_range_gap",
    }
)
_STRUCTURAL_PLANNER_FAILURE_PREFIXES = (
    "planner_missing_top_level_boundary_",
    "planner_segments_not_fully_covered_",
    "chapter_",
)


def _is_structural_planner_failure(
    error: DocumentPlanValidationError,
) -> bool:
    """Return whether *error* is safe for deterministic structure recovery.

    The planner adapter may include one primary structural code plus detailed
    boundary/chapter diagnostics.  Every code must remain in that structural
    vocabulary; unknown codes fail closed rather than being treated as a
    recoverable formatting defect.
    """
    codes = tuple(str(code).strip() for code in error.codes if str(code).strip())
    if not codes:
        return False
    return all(
        code in _STRUCTURAL_PLANNER_FAILURE_CODES
        or any(code.startswith(prefix) for prefix in _STRUCTURAL_PLANNER_FAILURE_PREFIXES)
        for code in codes
    )


def _item_has_structural_planner_failure(item: Any) -> bool:
    """Recognize a persisted structural planner failure for legacy recovery."""
    codes = tuple(
        str(code).strip()
        for code in (getattr(item, "document_plan_failure_codes", ()) or ())
        if str(code).strip()
    )
    return bool(codes) and _is_structural_planner_failure(
        DocumentPlanValidationError(codes)
    )
def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


_PLAN_TITLE_ANCHOR_TOKENS: dict[str, tuple[str, ...]] = {
    "eligibility": (
        "trial population",
        "study population",
        "subject eligibility",
        "eligibility criteria",
        "inclusion criteria",
        "exclusion criteria",
        "subject selection",
        "patient selection",
        "selection of subjects",
        "selection of patients",
        "inclusion and exclusion",
    ),
    "objectives_endpoints": ("objective", "endpoint", "estimand"),
    "safety": (
        "safety reporting",
        "safety assessment",
        "adverse event",
        " ae,",
        "sae",
        "adverse experience",
        "safety evaluation",
    ),
    "schedule": (
        "schedule of",
        "study assessments",
        "study assessment",
        "study procedures",
        "study procedure",
        "visit schedule",
        "schedule of activities",
        "schedule of assessments",
        "time and events schedule",
        "time and event schedule",
    ),
    "statistics": ("statistical", "statistics"),
    "synopsis": ("synopsis", "protocol summary"),
    "assessments": ("assessment", "laboratory", "physical examination"),
    "disposition": ("discontinuation", "withdrawal", "disposition", "end of study"),
    "ethics_governance": (
        "informed consent",
        "ethical review",
        "regulatory considerations",
        "publication policy",
    ),
    "references": ("reference", "references"),
    "rationale": ("rationale", "introduction", "background"),
    "data_management": ("data collection", "data management", "data quality"),
    "front_matter": ("front matter", "title page", "signature page", "table of contents"),
}


_PLAN_ANCHOR_ALIASES = {
    "endpoint": "objectives_endpoints",
    "endpoints": "objectives_endpoints",
    "objectives": "objectives_endpoints",
    "objectives_and_endpoints": "objectives_endpoints",
    "statistical_analysis": "statistics",
    "schedule_of_activities": "schedule",
}

# Research batches are intentionally small, but their capped spans must still
# be representative of the requested M11 anchor.  Length alone is a poor
# proxy: a protocol's longest span is often a schedule table, a table of
# contents, or a reference list that happened to inherit a nearby anchor.
# Keep the ranking deterministic and explainable; this is selection metadata,
# not an admission override.
_RESEARCH_ANCHOR_HEADING_HINTS: dict[str, tuple[str, ...]] = {
    "eligibility": (
        "eligib",
        "inclusion",
        "exclusion",
        "subject selection",
        "patient selection",
        "selection of subjects",
        "selection of patients",
    ),
    "objectives_endpoints": (
        "objective",
        "endpoint",
        "estimand",
        "outcome",
        "study design",
    ),
    "safety": (
        "safety",
        "adverse",
        "tolerab",
        "risk",
    ),
    "schedule": (
        "schedule",
        "visit",
        "assessment",
        "procedure",
    ),
}
_RESEARCH_ANCHOR_COMPETING_HEADING_HINTS: dict[str, tuple[str, ...]] = {
    "eligibility": ("reference", "bibliograph", "table of contents", "safety"),
    "objectives_endpoints": (
        "reference",
        "bibliograph",
        "table of contents",
        "eligib",
        "inclusion",
        "exclusion",
        "safety",
    ),
    "safety": (
        "reference",
        "bibliograph",
        "table of contents",
        "eligib",
        "inclusion",
        "exclusion",
    ),
    "schedule": (
        "reference",
        "bibliograph",
        "table of contents",
        "eligib",
    ),
}


def _research_span_cap_rank(spec: dict[str, Any]) -> tuple[Any, ...]:
    """Return a stable quality rank for a capped research source span.

    The ordering is deliberately conservative: an already-passed candidate
    and a Protocol source still win first, then a semantically titled span
    beats a larger but noisy span.  A bounded size penalty avoids selecting
    multi-page HTML tables that routinely exceed the translation/QC budget;
    source length is only the final tie-breaker.  This function never marks a
    span admissible by itself -- the downstream source-fidelity and medical
    gates remain authoritative.
    """
    span = spec.get("span")
    text = str(getattr(span, "source_text", "") or "")
    heading = str(getattr(span, "section_heading", "") or "")
    anchor = _canonical_plan_anchor(
        getattr(span, "ich_m11_anchor", "") or ""
    )
    folded_text = " ".join(text.casefold().split())
    folded_heading = " ".join(heading.casefold().split())
    hints = _RESEARCH_ANCHOR_HEADING_HINTS.get(anchor, ())
    competing = _RESEARCH_ANCHOR_COMPETING_HEADING_HINTS.get(anchor, ())
    heading_hits = sum(token in folded_heading for token in hints)
    text_hits = sum(token in folded_text[:12000] for token in hints)
    competing_heading_hits = sum(
        token in folded_heading for token in competing
    )
    heading_positions = [
        folded_heading.find(token)
        for token in hints
        if folded_heading.find(token) >= 0
    ]
    heading_distance_penalty = (
        0
        if not heading_positions or min(heading_positions) < 120
        else 1
    )

    prefer_ready = 0 if spec.get("generation_status") == "candidate_ready" else 1
    protocol_roles = {"protocol", "protocol_sap"}
    doc_type = str(
        getattr(spec.get("artifact"), "document_type", "") or ""
    ).casefold()
    prefer_protocol = 0 if doc_type in protocol_roles else 1

    compact = folded_text.strip()
    generic_penalty = 0
    short_penalty = 0
    if len(compact) < 20 or compact in {
        "cci",
        "无",
        "包含：",
        "具体为：",
        "补充内容：",
        "新增：",
        "添加：",
    }:
        generic_penalty = 4
    elif len(compact) < 500:
        # A short paragraph can still be a complete criterion or endpoint;
        # only generic cross-reference sentences receive the stronger penalty
        # below.  This lets a titled, complete criterion beat a much larger
        # neighbouring table while keeping ``...meet the criteria...eligible``
        # boilerplate out of the preferred cap.
        short_penalty = 1
        if re.search(
            r"(?i)^(?:patients?|subjects?)\s+who\s+meet\b.*"
            r"(?:criteria|criterion).*\beligible\b",
            compact,
        ):
            generic_penalty = 4
    elif len(compact) < 1_000:
        short_penalty = 2

    noise_penalty = 0
    if re.search(r"\.{5,}|…{2,}", text):
        noise_penalty += 2
    if re.search(r"(?i)references?|bibliograph|table of contents", folded_heading):
        noise_penalty += 4
    if re.search(r"(?i)^abbreviations?\s*:", compact[:1200]):
        noise_penalty += 3
    # A table is valid evidence, especially for schedule, but an untitled
    # table attached to another anchor is less reliable than a titled
    # narrative/criterion span.  Keep it as a fallback rather than excluding
    # it outright.
    if "<table" in folded_text and not heading_hits and anchor != "schedule":
        noise_penalty += 1

    if len(text) > 20_000:
        size_penalty = 3
    elif len(text) > 12_000:
        size_penalty = 2
    elif len(text) > 10_000:
        size_penalty = 1
    else:
        size_penalty = 0

    # Lower tuples sort first.  Heading relevance is weighted before raw text
    # relevance so a short explicit endpoint/eligibility section wins over a
    # long neighbouring references or visit-table span.
    return (
        prefer_ready,
        prefer_protocol,
        generic_penalty,
        competing_heading_hits,
        noise_penalty,
        size_penalty,
        heading_distance_penalty,
        -min(heading_hits, 3),
        -min(text_hits, 3),
        short_penalty,
        -len(text),
        str(getattr(span, "span_id", "") or ""),
    )


def _canonical_plan_anchor(value: Any) -> str:
    anchor = str(value or "").strip()
    return _PLAN_ANCHOR_ALIASES.get(anchor, anchor)


def _plan_title_anchor_hints(title: Any) -> set[str]:
    folded = " ".join(str(title or "").casefold().split())
    return {
        anchor
        for anchor, tokens in _PLAN_TITLE_ANCHOR_TOKENS.items()
        if any(token in folded for token in tokens)
    }


def _document_plan_semantic_alignment_codes(
    chapters: Any,
    source_spans: tuple[Any, ...],
) -> tuple[str, ...]:
    """Detect structurally valid plans that put mapped spans in a wrong chapter.

    The planner contract already guarantees complete, ordered span coverage, but
    that alone cannot catch a planner collapsing most of a document into one
    unrelated chapter.  Such a plan would make an anchor-filtered research batch
    exclude valid spans after chapter resolution.  Keep this check conservative:
    only a declared/title anchor conflict is rejected; unmapped spans are allowed
    as surrounding context.
    """
    span_lookup = {str(span.span_id): span for span in source_spans}
    issues: list[str] = []
    for chapter in chapters or ():
        if isinstance(chapter, dict):
            chapter_id = str(chapter.get("id") or chapter.get("chapter_id") or "").strip()
            title = chapter.get("title") or ""
            declared = _canonical_plan_anchor(
                chapter.get("ich_m11_anchor") or chapter.get("anchor") or "unmapped"
            )
            span_ids = chapter.get("source_span_ids") or chapter.get("span_ids") or []
        else:
            chapter_id = str(getattr(chapter, "chapter_id", "")).strip()
            title = getattr(chapter, "title", "")
            declared = _canonical_plan_anchor(
                getattr(chapter, "ich_m11_anchor", "") or "unmapped"
            )
            span_ids = getattr(chapter, "source_span_ids", ()) or ()
        if not chapter_id:
            continue
        mapped = {
            _canonical_plan_anchor(
                getattr(span_lookup[sid], "ich_m11_anchor", "") or ""
            )
            for sid in span_ids
            if str(sid).strip() in span_lookup
            and _canonical_plan_anchor(
                getattr(span_lookup[str(sid)], "ich_m11_anchor", "") or ""
            )
            not in {"", "unmapped"}
        }
        if not mapped:
            continue
        hints = _plan_title_anchor_hints(title)
        mismatch = False
        if declared not in {"", "unmapped"}:
            # A declared anchor is the stronger server-side signal.  Provider
            # titles such as ``Background`` are often generic even when the
            # source mapping is already precise; reject only an actual
            # cross-anchor assignment.
            mismatch = any(anchor != declared for anchor in mapped)
        else:
            if hints and any(anchor not in hints for anchor in mapped):
                mismatch = True
        if mismatch:
            issues.append(f"chapter_{chapter_id}_semantic_anchor_mismatch")
    return tuple(sorted(dict.fromkeys(issues)))


class WritingReferenceTranslationBatchStaleLineageError(RuntimeError):
    pass


class WritingReferenceTranslationModelCallOutcomeUnknownError(RuntimeError):
    """A transition-scoped external call was dispatched without safe output."""

    pass


class _OwnershipLostError(RuntimeError):
    """Raised internally when the durable-job claim is lost or cancelled.

    This exception unwinds the composite pipeline without writing any further
    business state.  It is caught in ``_process_claimed_item`` and suppressed
    (no _fail_claim) because the owner is stale and must not persist failure.
    """

    pass


@dataclass(frozen=True)
class _ScopeProjection:
    preview: WritingReferenceTranslationBatchPreview
    item_specs: list[dict[str, Any]]
    scope_documents: list[dict[str, Any]]
    exclusions: list[WritingReferenceTranslationBatchExclusion]


@dataclass(frozen=True)
class _PlannerContractPreparation:
    item_lineage: dict[str, dict[str, Any]]
    migration_plans: tuple[DocumentStructurePlan, ...] = ()

    def bounded_identity(self) -> dict[str, Any]:
        return {
            "item_lineage": {
                item_id: {
                    key: value
                    for key, value in sorted(lineage.items())
                    if key
                    not in {
                        "document_plan_contract_source_item_id",
                    }
                    or value
                }
                for item_id, lineage in sorted(self.item_lineage.items())
            },
            "migration_plans": [
                {
                    "plan_id": plan.plan_id,
                    "artifact_id": plan.artifact_id,
                    "source_plan_id": plan.contract_source_plan_id,
                    "source_fingerprint": plan.contract_source_fingerprint,
                    "target_fingerprint": plan.contract_target_fingerprint,
                    "transition_version": plan.contract_transition_version,
                    "source_payload_sha256": (
                        plan.contract_source_payload_sha256
                    ),
                    "target_payload_sha256": (
                        plan.contract_target_payload_sha256
                    ),
                    "chapter_count": len(plan.chapters),
                }
                for plan in self.migration_plans
            ],
        }


class WritingReferenceTranslationBatchService:
    """Durable, span-scoped generation over a frozen writing-reference snapshot."""

    def __init__(
        self,
        repository: WritingReferenceRepository,
        journey_service: Any,
        preparation_service: Any,
        translation_service: Any,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        chapter_pipeline: ChapterTranslationPipeline | None = None,
        durable_store: Any = None,
    ) -> None:
        self.repository = repository
        self.journey_service = journey_service
        self.preparation_service = preparation_service
        self.translation_service = translation_service
        self.clock = clock
        self.chapter_pipeline = chapter_pipeline
        self._durable_store = durable_store
        # This is deliberately an in-process, single-entry projection cache.
        # It never persists source text, credentials, or lineage outside the
        # service process.  The key is recomputed from current durable state
        # before every read, so a changed lineage cannot reuse this entry.
        self._unfiltered_scope_cache_key: str | None = None
        self._unfiltered_scope_cache: _ScopeProjection | None = None
        self._initialize()

    def attach_durable_store(self, store: Any) -> None:
        """Attach or replace the durable job store (e.g. on startup wiring)."""
        self._durable_store = store

    def ensure_reference_translation_job(
        self,
        project_id: str,
        batch_id: str,
        *,
        actor: str,
        retry_request_hash: str = "",
    ) -> str | None:
        """Ensure one ``reference_translation`` durable job exists for *batch_id*.

        Returns the ``job_id`` when a durable store is attached, or ``None``
        when no durable store is configured (legacy synchronous mode).

        The ``business_key`` is the batch_id; ``request_hash`` is derived from
        project + batch so the stable id is deterministic across restarts.
        For retry, a ``retry_request_hash`` may be supplied so retry is its
        own durable job attempt rather than a no-op reuse.
        """
        if self._durable_store is None:
            return None
        from packages.contracts.workbench_contracts import DurableJobCreateRequest

        transition_payload: dict[str, Any] = {}
        with self.repository._connect() as connection:
            transition_row = connection.execute(
                """
                SELECT transition_id, target_item_id
                FROM writing_reference_translation_downstream_transition_records
                WHERE tenant_id=? AND project_id=? AND target_batch_id=?
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchone()
        if transition_row is not None:
            transition_payload = {
                "downstream_contract_transition_id": str(
                    transition_row["transition_id"]
                ),
                "target_item_id": str(transition_row["target_item_id"]),
            }
        request_hash = retry_request_hash or _payload_hash(
            {
                "project_id": project_id,
                "batch_id": batch_id,
                **transition_payload,
            }
        )
        request = DurableJobCreateRequest(
            project_id=project_id,
            job_type=REFERENCE_TRANSLATION_JOB_TYPE,
            business_key=(
                transition_payload.get("downstream_contract_transition_id")
                or batch_id
            ),
            request_hash=request_hash,
            payload_json=_canonical_json(
                {
                    "batch_id": batch_id,
                    "actor": actor,
                    "retry": bool(retry_request_hash),
                    **transition_payload,
                }
            ),
            created_by=actor,
        )
        response = self._durable_store.create_or_reuse(request)
        return response.job_id

    def _initialize(self) -> None:
        with self.repository._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS writing_reference_translation_batch_schema (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_batches (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    glossary_version TEXT NOT NULL,
                    anchor_filter_json TEXT NOT NULL,
                    preparation_batch_id TEXT NOT NULL,
                    scope_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL CHECK (attempt >= 1),
                    exclusions_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, batch_id),
                    FOREIGN KEY (tenant_id, project_id, snapshot_id)
                    REFERENCES writing_reference_search_snapshots(tenant_id, project_id, snapshot_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_batch_items (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    span_id TEXT NOT NULL,
                    generation_status TEXT NOT NULL,
                    attempt INTEGER NOT NULL CHECK (attempt >= 0),
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, item_id),
                    UNIQUE (tenant_id, project_id, batch_id, span_id),
                    FOREIGN KEY (tenant_id, project_id, batch_id)
                    REFERENCES writing_reference_translation_batches(tenant_id, project_id, batch_id),
                    FOREIGN KEY (tenant_id, project_id, span_id)
                    REFERENCES writing_reference_source_spans(tenant_id, project_id, span_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_batch_idempotency (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, operation, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_downstream_transition_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    transition_id TEXT NOT NULL,
                    source_batch_id TEXT NOT NULL,
                    source_item_id TEXT NOT NULL,
                    source_translation_id TEXT NOT NULL,
                    source_translation_revision INTEGER NOT NULL,
                    source_downstream_fingerprint TEXT NOT NULL,
                    target_downstream_fingerprint TEXT NOT NULL,
                    target_batch_id TEXT NOT NULL,
                    target_item_id TEXT NOT NULL,
                    target_plan_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, transition_id),
                    UNIQUE (
                        tenant_id, project_id, source_batch_id, source_item_id,
                        source_translation_id, source_translation_revision,
                        target_downstream_fingerprint
                    )
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_downstream_transition_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    transition_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, transition_id)
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_downstream_model_call_records (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    transition_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, call_id),
                    UNIQUE (
                        tenant_id, project_id, transition_id, stage, scope_id
                    )
                );

                CREATE TABLE IF NOT EXISTS writing_reference_translation_downstream_model_call_state (
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('dispatched', 'completed')),
                    result_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, project_id, call_id)
                );

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_batch_scope_immutable
                BEFORE UPDATE ON writing_reference_translation_batches
                WHEN OLD.snapshot_id <> NEW.snapshot_id
                  OR OLD.glossary_version <> NEW.glossary_version
                  OR OLD.anchor_filter_json <> NEW.anchor_filter_json
                  OR OLD.preparation_batch_id <> NEW.preparation_batch_id
                  OR OLD.scope_sha256 <> NEW.scope_sha256
                  OR OLD.exclusions_json <> NEW.exclusions_json
                BEGIN
                    SELECT RAISE(ABORT, 'writing reference translation batch scope is immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_batch_no_delete
                BEFORE DELETE ON writing_reference_translation_batches BEGIN
                    SELECT RAISE(ABORT, 'writing reference translation batches are auditable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_batch_item_no_delete
                BEFORE DELETE ON writing_reference_translation_batch_items BEGIN
                    SELECT RAISE(ABORT, 'writing reference translation batch items are auditable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_downstream_transition_no_update
                BEFORE UPDATE ON writing_reference_translation_downstream_transition_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference downstream transitions are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_downstream_transition_no_delete
                BEFORE DELETE ON writing_reference_translation_downstream_transition_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference downstream transitions are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_downstream_state_no_delete
                BEFORE DELETE ON writing_reference_translation_downstream_transition_state BEGIN
                    SELECT RAISE(ABORT, 'writing reference downstream transition state is auditable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_downstream_call_no_update
                BEFORE UPDATE ON writing_reference_translation_downstream_model_call_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference downstream model-call intents are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_downstream_call_no_delete
                BEFORE DELETE ON writing_reference_translation_downstream_model_call_records BEGIN
                    SELECT RAISE(ABORT, 'writing reference downstream model-call intents are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_wref_translation_downstream_call_state_no_delete
                BEFORE DELETE ON writing_reference_translation_downstream_model_call_state BEGIN
                    SELECT RAISE(ABORT, 'writing reference downstream model-call state is auditable');
                END;
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO writing_reference_translation_batch_schema(
                    version, applied_at
                ) VALUES (1, ?)
                """,
                (self.clock().isoformat(),),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO writing_reference_translation_batch_schema(
                    version, applied_at
                ) VALUES (2, ?)
                """,
                (self.clock().isoformat(),),
            )

    def preview(
        self,
        project_id: str,
        request: WritingReferenceTranslationBatchPreviewRequest,
    ) -> WritingReferenceTranslationBatchPreview:
        return self._derive_scope(project_id, request).preview

    def create(
        self,
        project_id: str,
        request: WritingReferenceTranslationBatchCreateRequest,
    ) -> WritingReferenceTranslationBatch:
        request_hash = _payload_hash(
            {
                "snapshot_id": request.snapshot_id,
                "glossary_version": request.glossary_version,
                "anchor_filter": request.anchor_filter,
                "max_spans_per_anchor": getattr(request, "max_spans_per_anchor", None),
            }
        )
        replay = self._idempotent_result(
            project_id,
            "create_translation_batch",
            request.idempotency_key,
            request_hash,
        )
        if replay:
            return self.get(project_id, replay)

        scope = self._derive_scope(project_id, request)
        if not scope.item_specs:
            raise ValueError("translation batch scope contains no eligible spans")

        batch_id = "wref_translation_batch_" + _payload_hash(
            {
                "project_id": project_id,
                "snapshot_id": request.snapshot_id,
                "scope_sha256": scope.preview.scope_sha256,
                "idempotency_key": request.idempotency_key,
            }
        )[:24]
        now = self.clock()
        items = [
            self._new_item(project_id, batch_id, request.snapshot_id, spec, now)
            for spec in scope.item_specs
        ]
        status = self._aggregate_status(items)
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result_with(
                connection,
                project_id,
                "create_translation_batch",
                request.idempotency_key,
                request_hash,
            )
            if replay:
                connection.commit()
                return self.get(project_id, replay)
            connection.execute(
                """
                INSERT INTO writing_reference_translation_batches(
                    tenant_id, project_id, batch_id, snapshot_id, glossary_version,
                    anchor_filter_json, preparation_batch_id, scope_sha256, status,
                    attempt, exclusions_json, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    project_id,
                    batch_id,
                    request.snapshot_id,
                    request.glossary_version,
                    _canonical_json(request.anchor_filter),
                    scope.preview.preparation_batch_id,
                    scope.preview.scope_sha256,
                    status,
                    _canonical_json(
                        [item.model_dump(mode="json") for item in scope.preview.exclusions]
                    ),
                    request.actor,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            created_counts = self._counts(items, scope.preview.exclusions)
            self.repository._append_audit(
                connection,
                project_id,
                "translation_batch_created",
                batch_id,
                request.actor,
                {
                    "snapshot_id": request.snapshot_id,
                    "glossary_version": request.glossary_version,
                    "anchor_filter": request.anchor_filter,
                    "scope_sha256": scope.preview.scope_sha256,
                    "eligible_count": created_counts.eligible_count,
                    "item_count": created_counts.item_count,
                    "candidate_ready_count": created_counts.candidate_ready_count,
                    "fidelity_blocked_count": created_counts.fidelity_blocked_count,
                    "reused_count": created_counts.reused_count,
                    "excluded_count": created_counts.excluded_count,
                },
            )
            for item in items:
                self._insert_item_with(connection, item)
                if item.generation_status in {
                    "candidate_ready",
                    "fidelity_blocked",
                }:
                    self._append_item_completed_audit(
                        connection,
                        item,
                        request.actor,
                    )
            self._record_idempotency_with(
                connection,
                project_id,
                "create_translation_batch",
                request.idempotency_key,
                request_hash,
                batch_id,
            )
            connection.commit()
        self.ensure_reference_translation_job(
            project_id, batch_id, actor=request.actor
        )
        return self.get(project_id, batch_id)

    def retry(
        self,
        project_id: str,
        batch_id: str,
        request: WritingReferenceTranslationBatchRetryRequest,
    ) -> WritingReferenceTranslationBatch:
        request_hash = _payload_hash(
            {"batch_id": batch_id, "idempotency_key": request.idempotency_key}
        )
        # Idempotency replay first — a duplicate request must return the
        # original result regardless of current batch status.
        replay = self._idempotent_result(
            project_id,
            "retry_translation_batch",
            request.idempotency_key,
            request_hash,
        )
        if replay:
            return self.get(project_id, replay)

        with self.repository._connect() as connection:
            transition_child = connection.execute(
                """
                SELECT transition_id
                FROM writing_reference_translation_downstream_transition_records
                WHERE tenant_id=? AND project_id=? AND target_batch_id=?
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchone()
        if transition_child is not None:
            raise ValueError(
                "downstream_contract_transition_child_requires_exact_executor"
            )

        current_batch = self.get(project_id, batch_id)
        # Reject retry while the batch is actively running.
        if current_batch.status == "running":
            raise ValueError(
                "cannot retry a translation batch that is currently running"
            )

        # Preflight every ordinary retry / v2-to-v3 transition before durable
        # job creation. Invalid or ambiguous intent therefore creates neither
        # a job nor a business-state mutation.
        transition_created_at = self.clock()
        with self.repository._connect() as connection:
            failed_rows = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND generation_status='failed_retryable'
                ORDER BY item_id
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchall()
            preflight_items = [
                WritingReferenceTranslationBatchItem.model_validate_json(
                    row["payload_json"]
                )
                for row in failed_rows
            ]
            preflight = self._prepare_document_plan_contract_lineage(
                connection,
                preflight_items,
                retry_generation=current_batch.attempt + 1,
                created_at=transition_created_at,
                persist_migrations=False,
            )
        failed_item_ids = [item.item_id for item in preflight_items]
        if not failed_item_ids:
            return self.get(project_id, batch_id)
        transition_identity = preflight.bounded_identity()
        transition_identity_hash = _payload_hash(transition_identity)

        # Stable retry business key derived from batch_id + idempotency key.
        retry_key = f"{batch_id}:retry:{request.idempotency_key}"

        # Create/reuse the durable retry job BEFORE business mutation.
        # If this fails, the batch is unchanged.
        if self._durable_store is not None:
            from packages.contracts.workbench_contracts import (
                DurableJobCreateRequest,
            )

            retry_hash = _payload_hash(
                {
                    "project_id": project_id,
                    "batch_id": batch_id,
                    "retry_key": retry_key,
                    "failed_item_ids": failed_item_ids,
                    "planner_contract_transition_sha256": (
                        transition_identity_hash
                    ),
                }
            )
            retry_request = DurableJobCreateRequest(
                project_id=project_id,
                job_type=REFERENCE_TRANSLATION_JOB_TYPE,
                business_key=retry_key,
                request_hash=retry_hash,
                payload_json=_canonical_json(
                    {
                        "batch_id": batch_id,
                        "actor": request.actor,
                        "retry": True,
                        "failed_item_ids": failed_item_ids,
                        "planner_contract_transition_sha256": (
                            transition_identity_hash
                        ),
                    }
                ),
                created_by=request.actor,
            )
            # This must succeed before any business mutation.
            self._durable_store.create_or_reuse(retry_request)

        # Durable job created — now mutate business state atomically.
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result_with(
                connection,
                project_id,
                "retry_translation_batch",
                request.idempotency_key,
                request_hash,
            )
            if replay:
                connection.commit()
                return self.get(project_id, replay)
            batch_row = connection.execute(
                """
                SELECT status, attempt
                FROM writing_reference_translation_batches
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchone()
            if batch_row is None:
                connection.rollback()
                raise KeyError(batch_id)
            if str(batch_row["status"]) == "running":
                connection.rollback()
                raise ValueError(
                    "cannot retry a translation batch that is currently running"
                )
            failed_payload_rows = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND generation_status='failed_retryable'
                ORDER BY item_id
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchall()
            failed_items = [
                WritingReferenceTranslationBatchItem.model_validate_json(
                    row["payload_json"]
                )
                for row in failed_payload_rows
            ]
            if not failed_items:
                connection.commit()
                return self.get(project_id, batch_id)
            next_batch_attempt = int(batch_row["attempt"]) + 1
            prepared = self._prepare_document_plan_contract_lineage(
                connection,
                failed_items,
                retry_generation=next_batch_attempt,
                created_at=transition_created_at,
                persist_migrations=True,
            )
            if prepared.bounded_identity() != transition_identity:
                connection.rollback()
                raise WritingReferenceConflictError(
                    "document-plan contract transition changed after preflight"
                )
            retry_lineage = prepared.item_lineage
            now = self.clock()
            for item in failed_items:
                lineage = retry_lineage.get(item.item_id)
                if lineage is None:
                    continue
                updated = item.model_copy(
                    update={
                        **lineage,
                        "updated_at": now,
                    },
                    deep=True,
                )
                cursor = self._write_item_with(
                    connection,
                    updated,
                    expected_status="failed_retryable",
                    expected_attempt=item.attempt,
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "document-plan retry lineage allocation lost item ownership"
                    )
            cursor = connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status='running', attempt=?, updated_at=?
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND status=? AND attempt=?
                """,
                (
                    next_batch_attempt,
                    now.isoformat(),
                    TENANT_ID,
                    project_id,
                    batch_id,
                    str(batch_row["status"]),
                    int(batch_row["attempt"]),
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise WritingReferenceConflictError(
                    "translation batch retry lost batch ownership"
                )
            self._record_idempotency_with(
                connection,
                project_id,
                "retry_translation_batch",
                request.idempotency_key,
                request_hash,
                batch_id,
            )
            retry_group_audit: list[dict[str, Any]] = []
            for source_item_id in sorted(
                {
                    values.get("document_plan_retry_source_item_id", "")
                    for values in retry_lineage.values()
                    if values.get("document_plan_retry_source_item_id", "")
                }
            ):
                source_item = next(
                    item
                    for item in failed_items
                    if item.item_id == source_item_id
                )
                lineage = retry_lineage[source_item_id]
                retry_group_audit.append(
                    {
                        "artifact_id": source_item.artifact_id,
                        "generation": lineage[
                            "document_plan_retry_generation"
                        ],
                        "parent_stage_run_id": lineage[
                            "document_plan_retry_parent_stage_run_id"
                        ],
                        "source_item_id": source_item_id,
                        "item_count": sum(
                            candidate.artifact_id
                            == source_item.artifact_id
                            and candidate.item_id in retry_lineage
                            for candidate in failed_items
                        ),
                    }
                )
            # Keep a durable audit marker for the bounded legacy recovery
            # path where a structural planner failure had no persisted parent
            # stage row.  The item lineage remains zero-generation so the
            # next worker performs a fresh, idempotent planner call rather
            # than pretending to retry an absent immutable stage.
            for artifact_id in sorted(
                {
                    item.artifact_id
                    for item in failed_items
                    if item.item_id in retry_lineage
                    and not retry_lineage[item.item_id].get(
                        "document_plan_retry_source_item_id", ""
                    )
                }
            ):
                artifact_items = [
                    item
                    for item in failed_items
                    if item.artifact_id == artifact_id
                    and item.item_id in retry_lineage
                ]
                if artifact_items and all(
                    _item_has_structural_planner_failure(item)
                    and not item.document_plan_failure_source_stage_run_id
                    for item in artifact_items
                ):
                    retry_group_audit.append(
                        {
                            "artifact_id": artifact_id,
                            "generation": 0,
                            "parent_stage_run_id": "",
                            "source_item_id": "",
                            "item_count": len(artifact_items),
                            "recovery_kind": (
                                "fresh_planner_after_unpersisted_structural_failure"
                            ),
                        }
                    )
            contract_transition_audit: list[dict[str, Any]] = []
            transition_keys = {
                (
                    values.get(
                        "document_plan_contract_transition_kind",
                        "",
                    ),
                    values.get(
                        "document_plan_contract_source_item_id",
                        "",
                    ),
                    values.get(
                        "document_plan_contract_source_plan_id",
                        "",
                    ),
                    values.get(
                        "document_plan_contract_source_stage_run_id",
                        "",
                    ),
                )
                for values in retry_lineage.values()
                if values.get(
                    "document_plan_contract_transition_kind",
                    "",
                )
            }
            for (
                transition_kind,
                source_item_id,
                source_plan_id,
                source_stage_run_id,
            ) in sorted(transition_keys):
                lineage = next(
                    values
                    for values in retry_lineage.values()
                    if values.get(
                        "document_plan_contract_transition_kind",
                        "",
                    )
                    == transition_kind
                    and values.get(
                        "document_plan_contract_source_item_id",
                        "",
                    )
                    == source_item_id
                    and values.get(
                        "document_plan_contract_source_plan_id",
                        "",
                    )
                    == source_plan_id
                    and values.get(
                        "document_plan_contract_source_stage_run_id",
                        "",
                    )
                    == source_stage_run_id
                )
                source_item = next(
                    item
                    for item in failed_items
                    if item.item_id == source_item_id
                )
                contract_transition_audit.append(
                    {
                        "artifact_id": source_item.artifact_id,
                        "kind": transition_kind,
                        "generation": lineage[
                            "document_plan_contract_generation"
                        ],
                        "transition_version": lineage[
                            "document_plan_contract_transition_version"
                        ],
                        "source_item_id": source_item_id,
                        "source_plan_id": source_plan_id,
                        "target_plan_id": lineage.get(
                            "document_plan_contract_target_plan_id",
                            "",
                        ),
                        "source_stage_run_id": source_stage_run_id,
                        "source_execution_fingerprint": lineage.get(
                            "document_plan_contract_source_execution_fingerprint",
                            "",
                        ),
                        "source_prompt_version": lineage[
                            "document_plan_contract_source_prompt_version"
                        ],
                        "target_prompt_version": lineage[
                            "document_plan_contract_target_prompt_version"
                        ],
                        "source_fingerprint": lineage.get(
                            "document_plan_contract_source_fingerprint",
                            "",
                        ),
                        "target_fingerprint": lineage.get(
                            "document_plan_contract_target_fingerprint",
                            "",
                        ),
                        "item_count": sum(
                            candidate.artifact_id
                            == source_item.artifact_id
                            and candidate.item_id in retry_lineage
                            for candidate in failed_items
                        ),
                    }
                )
            self.repository._append_audit(
                connection,
                project_id,
                "translation_batch_retry_requested",
                batch_id,
                request.actor,
                {
                    "failed_item_ids": sorted(
                        item.item_id for item in failed_items
                    ),
                    "document_plan_retry_groups": retry_group_audit,
                    "document_plan_contract_transitions": (
                        contract_transition_audit
                    ),
                    "planner_contract_transition_sha256": (
                        transition_identity_hash
                    ),
                },
            )
            connection.commit()
        return self.get(project_id, batch_id)

    def create_downstream_contract_transition(
        self,
        project_id: str,
        source_batch_id: str,
        source_item_id: str,
        request: WritingReferenceTranslationDownstreamTransitionRequest,
    ) -> WritingReferenceTranslationDownstreamTransitionRecord:
        """Create one immutable, single-item downstream-contract transition.

        The source batch/item and every source plan/chunk/integration/
        translation row are read-only.  A deterministic child batch and a new
        target-contract plan are inserted in one transaction.
        """
        request_hash = _payload_hash(
            {
                "source_batch_id": source_batch_id,
                "source_item_id": source_item_id,
                **request.model_dump(
                    mode="json",
                    exclude={"actor", "idempotency_key"},
                ),
            }
        )
        replay = self._idempotent_result(
            project_id,
            "create_downstream_contract_transition",
            request.idempotency_key,
            request_hash,
        )
        if replay:
            return self.downstream_contract_transition(project_id, replay)

        created_at = self.clock()
        with self.repository._connect() as connection:
            prepared = self._prepare_downstream_contract_transition_with(
                connection,
                project_id,
                source_batch_id,
                source_item_id,
                request,
                created_at=created_at,
            )
        record, target_plan, target_item, target_batch_values = prepared

        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idempotent_result_with(
                connection,
                project_id,
                "create_downstream_contract_transition",
                request.idempotency_key,
                request_hash,
            )
            if replay:
                connection.commit()
                return self.downstream_contract_transition(project_id, replay)

            revalidated = self._prepare_downstream_contract_transition_with(
                connection,
                project_id,
                source_batch_id,
                source_item_id,
                request,
                created_at=created_at,
            )
            if (
                revalidated[0].model_dump(mode="json")
                != record.model_dump(mode="json")
                or revalidated[1].model_dump(mode="json")
                != target_plan.model_dump(mode="json")
                or revalidated[2].model_dump(mode="json")
                != target_item.model_dump(mode="json")
            ):
                connection.rollback()
                raise WritingReferenceConflictError(
                    "downstream contract transition changed after preflight"
                )

            existing_row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_downstream_transition_records
                WHERE tenant_id=? AND project_id=?
                  AND source_batch_id=? AND source_item_id=?
                  AND source_translation_id=?
                  AND source_translation_revision=?
                  AND target_downstream_fingerprint=?
                """,
                (
                    TENANT_ID,
                    project_id,
                    source_batch_id,
                    source_item_id,
                    record.source_translation_id,
                    record.source_translation_revision,
                    record.target_downstream_fingerprint,
                ),
            ).fetchone()
            if existing_row is not None:
                existing = (
                    WritingReferenceTranslationDownstreamTransitionRecord
                    .model_validate_json(existing_row["payload_json"])
                )
                semantic_exclusions = {"created_by", "created_at"}
                if existing.model_dump(
                    mode="json",
                    exclude=semantic_exclusions,
                ) != record.model_dump(
                    mode="json",
                    exclude=semantic_exclusions,
                ):
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "downstream transition semantic identity collision"
                    )
                self._record_idempotency_with(
                    connection,
                    project_id,
                    "create_downstream_contract_transition",
                    request.idempotency_key,
                    request_hash,
                    existing.transition_id,
                )
                connection.commit()
                return existing

            self.repository.save_document_structure_plan_with_connection(
                connection,
                target_plan,
                idempotency_key=(
                    f"downstream-transition-plan:{record.transition_id}:"
                    f"{record.target_downstream_fingerprint}"
                ),
            )
            connection.execute(
                """
                INSERT INTO writing_reference_translation_batches(
                    tenant_id, project_id, batch_id, snapshot_id,
                    glossary_version, anchor_filter_json,
                    preparation_batch_id, scope_sha256, status, attempt,
                    exclusions_json, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'accepted', 1, '[]', ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    project_id,
                    record.target_batch_id,
                    target_batch_values["snapshot_id"],
                    target_batch_values["glossary_version"],
                    _canonical_json(target_batch_values["anchor_filter"]),
                    target_batch_values["preparation_batch_id"],
                    target_batch_values["scope_sha256"],
                    target_batch_values["created_by"],
                    created_at.isoformat(),
                    created_at.isoformat(),
                ),
            )
            self._insert_item_with(connection, target_item)
            connection.execute(
                """
                INSERT INTO writing_reference_translation_downstream_transition_records(
                    tenant_id, project_id, transition_id, source_batch_id,
                    source_item_id, source_translation_id,
                    source_translation_revision,
                    source_downstream_fingerprint,
                    target_downstream_fingerprint, target_batch_id,
                    target_item_id, target_plan_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    project_id,
                    record.transition_id,
                    record.source_batch_id,
                    record.source_item_id,
                    record.source_translation_id,
                    record.source_translation_revision,
                    record.source_downstream_fingerprint,
                    record.target_downstream_fingerprint,
                    record.target_batch_id,
                    record.target_item_id,
                    record.target_plan_id,
                    _canonical_json(record.model_dump(mode="json")),
                    created_at.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO writing_reference_translation_downstream_transition_state(
                    tenant_id, project_id, transition_id, status,
                    error_code, updated_at
                ) VALUES (?, ?, ?, 'pending', '', ?)
                """,
                (
                    TENANT_ID,
                    project_id,
                    record.transition_id,
                    created_at.isoformat(),
                ),
            )
            self._record_idempotency_with(
                connection,
                project_id,
                "create_downstream_contract_transition",
                request.idempotency_key,
                request_hash,
                record.transition_id,
            )
            self.repository._append_audit(
                connection,
                project_id,
                "translation_downstream_contract_transition_created",
                record.transition_id,
                request.actor,
                {
                    "source_batch_id": record.source_batch_id,
                    "source_item_id": record.source_item_id,
                    "source_translation_id": record.source_translation_id,
                    "source_translation_revision": (
                        record.source_translation_revision
                    ),
                    "source_plan_id": record.source_plan_id,
                    "source_integration_id": record.source_integration_id,
                    "source_downstream_fingerprint": (
                        record.source_downstream_fingerprint
                    ),
                    "target_batch_id": record.target_batch_id,
                    "target_item_id": record.target_item_id,
                    "target_plan_id": record.target_plan_id,
                    "target_downstream_fingerprint": (
                        record.target_downstream_fingerprint
                    ),
                    "transition_version": record.transition_version,
                },
            )
            connection.commit()
        return record

    def _prepare_downstream_contract_transition_with(
        self,
        connection: Any,
        project_id: str,
        source_batch_id: str,
        source_item_id: str,
        request: WritingReferenceTranslationDownstreamTransitionRequest,
        *,
        created_at: datetime,
    ) -> tuple[
        WritingReferenceTranslationDownstreamTransitionRecord,
        DocumentStructurePlan,
        WritingReferenceTranslationBatchItem,
        dict[str, Any],
    ]:
        """Read-only validation and deterministic target construction."""
        batch_row = connection.execute(
            """
            SELECT *
            FROM writing_reference_translation_batches
            WHERE tenant_id=? AND project_id=? AND batch_id=?
            """,
            (TENANT_ID, project_id, source_batch_id),
        ).fetchone()
        item_row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_translation_batch_items
            WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
            """,
            (TENANT_ID, project_id, source_batch_id, source_item_id),
        ).fetchone()
        if batch_row is None or item_row is None:
            raise KeyError(source_item_id)
        source_item = WritingReferenceTranslationBatchItem.model_validate_json(
            item_row["payload_json"]
        )
        if (
            str(batch_row["status"])
            != request.expected_source_batch_status
            or int(batch_row["attempt"])
            != request.expected_source_batch_attempt
        ):
            raise ValueError(
                "downstream_contract_transition_source_batch_state_mismatch"
            )
        if (
            source_item.generation_status
            != request.expected_source_item_status
            or source_item.attempt != request.expected_source_item_attempt
            or source_item.fidelity_status != "blocked"
        ):
            raise ValueError(
                "downstream_contract_transition_source_item_state_mismatch"
            )
        if (
            source_item.translation_id
            != request.expected_source_translation_id
            or source_item.translation_revision
            != request.expected_source_translation_revision
            or source_item.ai_run_id != request.expected_source_ai_run_id
            or source_item.document_structure_plan_id
            != request.expected_source_plan_id
            or source_item.hy_mt2_prompt_version
            != request.expected_source_hy_mt2_prompt_version
            or request.expected_source_failure_code
            not in source_item.fidelity_failure_codes
        ):
            raise ValueError(
                "downstream_contract_transition_source_item_identity_mismatch"
            )
        if source_item.downstream_contract_transition_id:
            raise ValueError(
                "downstream_contract_transition_source_must_be_original_item"
            )
        if (
            request.expected_source_downstream_fingerprint
            == TRANSLATION_CONTRACT_FINGERPRINT
        ):
            raise ValueError(
                "downstream_contract_transition_requires_new_contract"
            )

        translation_row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_translation_records
            WHERE tenant_id=? AND project_id=? AND translation_id=?
              AND revision=?
            """,
            (
                TENANT_ID,
                project_id,
                request.expected_source_translation_id,
                request.expected_source_translation_revision,
            ),
        ).fetchone()
        plan_row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_document_structure_plans
            WHERE tenant_id=? AND project_id=? AND plan_id=?
            """,
            (TENANT_ID, project_id, request.expected_source_plan_id),
        ).fetchone()
        integration_row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_chapter_integration_results
            WHERE tenant_id=? AND project_id=? AND integration_id=?
            """,
            (
                TENANT_ID,
                project_id,
                request.expected_source_integration_id,
            ),
        ).fetchone()
        run_row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_composite_pipeline_runs
            WHERE tenant_id=? AND project_id=? AND run_id=?
            """,
            (TENANT_ID, project_id, request.expected_source_ai_run_id),
        ).fetchone()
        if any(
            row is None
            for row in (translation_row, plan_row, integration_row, run_row)
        ):
            raise ValueError(
                "downstream_contract_transition_source_lineage_missing"
            )
        source_translation = WritingReferenceTranslationRevision.model_validate_json(
            translation_row["payload_json"]
        )
        source_plan = DocumentStructurePlan.model_validate_json(
            plan_row["payload_json"]
        )
        source_integration = ChapterIntegrationResult.model_validate_json(
            integration_row["payload_json"]
        )
        source_run = CompositePipelineRun.model_validate_json(
            run_row["payload_json"]
        )
        expected_source_plan_fingerprint = _planner_contract_fingerprint(
            artifact_id=source_item.artifact_id,
            extraction_revision=source_item.extraction_revision,
            planner_model=source_plan.planner_model,
            planner_prompt_version=source_plan.planner_prompt_version,
            document_sha256=source_item.artifact_sha256,
            translation_contract=(
                request.expected_source_downstream_fingerprint
            ),
        )
        if (
            source_translation.contract_hash
            != request.expected_source_composite_contract_hash
            or source_translation.ai_run_id
            != request.expected_source_ai_run_id
            or source_translation.document_structure_plan_id
            != source_plan.plan_id
            or source_translation.chapter_integration_result_id
            != source_integration.integration_id
            or source_integration.plan_id != source_plan.plan_id
            or source_integration.translation_contract_fingerprint
            != request.expected_source_downstream_fingerprint
            or source_plan.planner_contract_fingerprint
            != expected_source_plan_fingerprint
            or source_run.run_id != source_translation.ai_run_id
            or source_run.plan_id != source_plan.plan_id
            or source_plan.project_id != project_id
            or source_plan.artifact_id != source_item.artifact_id
            or source_plan.extraction_revision
            != source_item.extraction_revision
            or source_plan.document_sha256 != source_item.artifact_sha256
            or source_integration.fidelity_status != "blocked"
        ):
            raise ValueError(
                "downstream_contract_transition_source_lineage_mismatch"
            )
        source_span = self._source_span_with(
            connection,
            project_id,
            source_item.span_id,
        )
        if source_span is None:
            raise ValueError(
                "downstream_contract_transition_source_lineage_missing"
            )
        blocked_output = str(
            source_integration.blocked_raw_provider_output or ""
        ).strip()
        blocked_output_sha256 = _pipeline_sha256(blocked_output)
        if (
            not blocked_output
            or source_integration.blocked_raw_provider_output_sha256
            != blocked_output_sha256
        ):
            raise ValueError(
                "downstream_contract_transition_blocked_output_missing"
            )
        units = split_source_into_units(source_span.source_text)
        if len(units) != 1:
            raise ValueError(
                "downstream_contract_transition_preflight_unaligned"
            )
        current_failure_codes = evaluate_translation_fidelity_aligned_units(
            units,
            {units[0].ordinal: blocked_output},
        )
        if current_failure_codes:
            raise ValueError(
                "downstream_contract_transition_preflight_failed:"
                + ",".join(current_failure_codes)
            )

        target_plan_fingerprint = _planner_contract_fingerprint(
            artifact_id=source_item.artifact_id,
            extraction_revision=source_item.extraction_revision,
            planner_model=DOWNSTREAM_CONTRACT_PLAN_NAMESPACE,
            planner_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            document_sha256=source_item.artifact_sha256,
            translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        target_payload_sha256 = _payload_hash(
            {
                "document_role": source_plan.document_role,
                "chapters": [
                    chapter.model_dump(mode="json")
                    for chapter in source_plan.chapters
                ],
            }
        )
        source_plan_payload_sha256 = _payload_hash(
            source_plan.model_dump(mode="json")
        )
        target_plan_id = "docplan_" + _payload_hash(
            {
                "namespace": DOWNSTREAM_CONTRACT_PLAN_NAMESPACE,
                "transition_version": DOWNSTREAM_CONTRACT_TRANSITION_VERSION,
                "source_plan_id": source_plan.plan_id,
                "source_plan_payload_sha256": source_plan_payload_sha256,
                "source_downstream_fingerprint": (
                    request.expected_source_downstream_fingerprint
                ),
                "target_downstream_fingerprint": (
                    TRANSLATION_CONTRACT_FINGERPRINT
                ),
                "target_plan_fingerprint": target_plan_fingerprint,
                "target_payload_sha256": target_payload_sha256,
            }
        )[:24]
        transition_id = "wref_downstream_transition_" + _payload_hash(
            {
                "project_id": project_id,
                "source_batch_id": source_batch_id,
                "source_item_id": source_item_id,
                "source_translation_id": source_translation.translation_id,
                "source_translation_revision": source_translation.revision,
                "source_plan_id": source_plan.plan_id,
                "source_integration_id": source_integration.integration_id,
                "source_downstream_fingerprint": (
                    request.expected_source_downstream_fingerprint
                ),
                "target_downstream_fingerprint": (
                    TRANSLATION_CONTRACT_FINGERPRINT
                ),
                "transition_version": DOWNSTREAM_CONTRACT_TRANSITION_VERSION,
            }
        )[:24]
        target_batch_id = "wref_translation_batch_" + _payload_hash(
            {
                "transition_id": transition_id,
                "scope": "single_item_downstream_contract_transition",
            }
        )[:24]
        target_item_id = "wref_translation_item_" + _payload_hash(
            {
                "transition_id": transition_id,
                "target_batch_id": target_batch_id,
                "source_item_id": source_item_id,
            }
        )[:24]
        target_plan = DocumentStructurePlan(
            plan_id=target_plan_id,
            project_id=project_id,
            artifact_id=source_plan.artifact_id,
            extraction_revision=source_plan.extraction_revision,
            document_sha256=source_plan.document_sha256,
            document_role=source_plan.document_role,
            planner_model=DOWNSTREAM_CONTRACT_PLAN_NAMESPACE,
            planner_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            planner_input_hash=source_plan.planner_input_hash,
            planner_output_hash=target_payload_sha256,
            planner_contract_fingerprint=target_plan_fingerprint,
            chapters=[
                chapter.model_copy(deep=True)
                for chapter in source_plan.chapters
            ],
            ambiguity_codes=list(source_plan.ambiguity_codes),
            status="active",
            created_at=created_at,
            parent_plan_id=source_plan.plan_id,
            contract_migration_namespace=(
                DOWNSTREAM_CONTRACT_PLAN_NAMESPACE
            ),
            contract_transition_version=(
                DOWNSTREAM_CONTRACT_TRANSITION_VERSION
            ),
            contract_source_plan_id=source_plan.plan_id,
            contract_source_fingerprint=(
                source_plan.planner_contract_fingerprint
            ),
            contract_target_fingerprint=target_plan_fingerprint,
            contract_source_prompt_version=(
                source_plan.planner_prompt_version
            ),
            contract_target_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            contract_source_payload_sha256=source_plan_payload_sha256,
            contract_target_payload_sha256=target_payload_sha256,
        )
        if not any(
            source_item.span_id in chapter.source_span_ids
            for chapter in target_plan.chapters
        ):
            raise ValueError(
                "downstream_contract_transition_target_plan_unassigned"
            )

        target_item = self._new_downstream_transition_item(
            source_item,
            transition_id=transition_id,
            target_batch_id=target_batch_id,
            target_item_id=target_item_id,
            target_plan_id=target_plan_id,
            source_integration_id=source_integration.integration_id,
            source_downstream_fingerprint=(
                request.expected_source_downstream_fingerprint
            ),
            created_at=created_at,
        )
        record = WritingReferenceTranslationDownstreamTransitionRecord(
            transition_id=transition_id,
            project_id=project_id,
            source_batch_id=source_batch_id,
            source_item_id=source_item_id,
            source_batch_attempt=int(batch_row["attempt"]),
            source_item_attempt=source_item.attempt,
            source_translation_id=source_translation.translation_id,
            source_translation_revision=source_translation.revision,
            source_ai_run_id=source_translation.ai_run_id,
            source_plan_id=source_plan.plan_id,
            source_integration_id=source_integration.integration_id,
            source_composite_contract_hash=source_translation.contract_hash,
            source_downstream_fingerprint=(
                request.expected_source_downstream_fingerprint
            ),
            source_hy_mt2_prompt_version=(
                request.expected_source_hy_mt2_prompt_version
            ),
            source_failure_code=request.expected_source_failure_code,
            source_blocked_output_sha256=blocked_output_sha256,
            target_batch_id=target_batch_id,
            target_item_id=target_item_id,
            target_plan_id=target_plan_id,
            target_composite_contract_hash=(
                COMPOSITE_TRANSLATION_CONTRACT_HASH
            ),
            target_downstream_fingerprint=(
                TRANSLATION_CONTRACT_FINGERPRINT
            ),
            target_hy_mt2_prompt_version=HY_MT2_PROMPT_VERSION,
            target_alignment_contract=TRANSLATION_ALIGNMENT_CONTRACT,
            transition_version=DOWNSTREAM_CONTRACT_TRANSITION_VERSION,
            created_by=request.actor,
            created_at=created_at,
        )
        target_batch_values = {
            "snapshot_id": str(batch_row["snapshot_id"]),
            "glossary_version": str(batch_row["glossary_version"]),
            "anchor_filter": [source_item.ich_m11_anchor],
            "preparation_batch_id": str(batch_row["preparation_batch_id"]),
            "scope_sha256": _payload_hash(
                {
                    "transition_id": transition_id,
                    "source_item_id": source_item_id,
                    "source_text_sha256": source_item.source_text_sha256,
                    "target_downstream_fingerprint": (
                        TRANSLATION_CONTRACT_FINGERPRINT
                    ),
                }
            ),
            "created_by": (
                "research_pipeline_downstream_contract_transition"
            ),
        }
        return record, target_plan, target_item, target_batch_values

    @staticmethod
    def _source_span_with(
        connection: Any,
        project_id: str,
        span_id: str,
    ) -> WritingReferenceExtractedSpan | None:
        row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_source_spans
            WHERE tenant_id=? AND project_id=? AND span_id=?
            """,
            (TENANT_ID, project_id, span_id),
        ).fetchone()
        if row is None:
            return None
        return WritingReferenceExtractedSpan.model_validate_json(
            row["payload_json"]
        )

    @staticmethod
    def _new_downstream_transition_item(
        source_item: WritingReferenceTranslationBatchItem,
        *,
        transition_id: str,
        target_batch_id: str,
        target_item_id: str,
        target_plan_id: str,
        source_integration_id: str,
        source_downstream_fingerprint: str,
        created_at: datetime,
    ) -> WritingReferenceTranslationBatchItem:
        """Project frozen source lineage into a clean target child item."""
        return source_item.model_copy(
            update={
                "item_id": target_item_id,
                "batch_id": target_batch_id,
                "origin": "new",
                "generation_status": "pending",
                "attempt": 0,
                "translation_id": "",
                "translation_revision": 0,
                "ai_run_id": "",
                "fidelity_status": "",
                "fidelity_failure_codes": [],
                "error_code": "",
                "error_detail": "",
                "medical_review_status": "not_reviewed",
                "author_confirmation_status": "not_confirmed",
                "admission_status": "not_admitted",
                "pipeline_stage": "",
                "pipeline_stage_detail": "",
                "ocr_lineage_json": "",
                "flash_plan_model": "",
                "flash_plan_prompt_version": "",
                "hy_mt2_model": "",
                "hy_mt2_prompt_version": "",
                "flash_qc_model": "",
                "flash_qc_prompt_version": "",
                "plan_model": "",
                "qc_model": "",
                "active_upper_layer_stage": "",
                "active_upper_layer_stage_run_id": "",
                "latest_upper_layer_stage_run_id": "",
                "upper_layer_escalation_id": "",
                "upper_layer_escalation_status": "",
                "document_plan_failure_source_stage_run_id": "",
                "document_plan_failure_codes": [],
                "document_plan_failure_is_derived": False,
                "document_plan_retry_generation": 0,
                "document_plan_retry_parent_stage_run_id": "",
                "document_plan_retry_source_item_id": "",
                "document_plan_contract_transition_kind": "",
                "document_plan_contract_transition_version": "",
                "document_plan_contract_generation": 0,
                "document_plan_contract_source_item_id": "",
                "document_plan_contract_source_plan_id": "",
                "document_plan_contract_target_plan_id": "",
                "document_plan_contract_source_stage_run_id": "",
                "document_plan_contract_source_execution_fingerprint": "",
                "document_plan_contract_source_prompt_version": "",
                "document_plan_contract_target_prompt_version": "",
                "document_plan_contract_source_fingerprint": "",
                "document_plan_contract_target_fingerprint": "",
                "downstream_contract_transition_id": transition_id,
                "downstream_contract_transition_version": (
                    DOWNSTREAM_CONTRACT_TRANSITION_VERSION
                ),
                "downstream_contract_source_batch_id": source_item.batch_id,
                "downstream_contract_source_item_id": source_item.item_id,
                "downstream_contract_source_item_attempt": source_item.attempt,
                "downstream_contract_source_translation_id": (
                    source_item.translation_id
                ),
                "downstream_contract_source_translation_revision": (
                    source_item.translation_revision
                ),
                "downstream_contract_source_plan_id": (
                    source_item.document_structure_plan_id
                ),
                "downstream_contract_source_integration_id": (
                    source_integration_id
                ),
                "downstream_contract_source_fingerprint": (
                    source_downstream_fingerprint
                ),
                "downstream_contract_target_plan_id": target_plan_id,
                "downstream_contract_target_fingerprint": (
                    TRANSLATION_CONTRACT_FINGERPRINT
                ),
                "pipeline_fingerprint": "",
                "document_structure_plan_id": "",
                "document_total": 0,
                "document_index": 0,
                "document_label": "",
                "chapter_id": "",
                "chapter_title": "",
                "chapter_total": 0,
                "chapter_index": 0,
                "chunk_count": 0,
                "chunk_completed": 0,
                "chunk_running": 0,
                "chunk_failed": 0,
                "chunk_reused": 0,
                "source_span_count": 0,
                "blocker_kind": "",
                "blocker_message": "",
                "contract_hash": COMPOSITE_TRANSLATION_CONTRACT_HASH,
                "prompt_version": COMPOSITE_TRANSLATION_PROMPT_VERSION,
                "schema_version": COMPOSITE_TRANSLATION_SCHEMA_VERSION,
                "created_at": created_at,
                "updated_at": created_at,
            },
            deep=True,
        )

    def downstream_contract_transition(
        self,
        project_id: str,
        transition_id: str,
    ) -> WritingReferenceTranslationDownstreamTransitionRecord:
        with self.repository._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_downstream_transition_records
                WHERE tenant_id=? AND project_id=? AND transition_id=?
                """,
                (TENANT_ID, project_id, transition_id),
            ).fetchone()
        if row is None:
            raise KeyError(transition_id)
        return WritingReferenceTranslationDownstreamTransitionRecord.model_validate_json(
            row["payload_json"]
        )

    def downstream_contract_transition_state(
        self,
        project_id: str,
        transition_id: str,
    ) -> WritingReferenceTranslationDownstreamTransitionState:
        with self.repository._connect() as connection:
            row = connection.execute(
                """
                SELECT status, error_code, updated_at
                FROM writing_reference_translation_downstream_transition_state
                WHERE tenant_id=? AND project_id=? AND transition_id=?
                """,
                (TENANT_ID, project_id, transition_id),
            ).fetchone()
        if row is None:
            raise KeyError(transition_id)
        return WritingReferenceTranslationDownstreamTransitionState(
            transition_id=transition_id,
            project_id=project_id,
            status=str(row["status"]),
            error_code=str(row["error_code"]),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def _prepare_document_plan_contract_lineage(
        self,
        connection: Any,
        failed_items: list[WritingReferenceTranslationBatchItem],
        *,
        retry_generation: int,
        created_at: datetime,
        persist_migrations: bool,
    ) -> _PlannerContractPreparation:
        """Validate and prepare ordinary retry or the allowlisted v2->v3 edge.

        The read-only preflight and the in-transaction revalidation call this
        same function.  When ``persist_migrations`` is true, deterministic
        migration plans are written through the caller's transaction before
        any item or batch state changes.
        """
        if not failed_items:
            return _PlannerContractPreparation(item_lineage={})

        groups: dict[str, list[WritingReferenceTranslationBatchItem]] = (
            defaultdict(list)
        )
        for item in failed_items:
            groups[item.artifact_id].append(item)

        allocated: dict[str, dict[str, Any]] = {}
        migration_plans: list[DocumentStructurePlan] = []
        ordinary_candidates: list[
            WritingReferenceTranslationBatchItem
        ] = []

        for artifact_id, items in sorted(groups.items()):
            source_item = sorted(items, key=lambda item: item.item_id)[0]
            self._validate_contract_group_identity(
                connection,
                items,
                artifact_id=artifact_id,
            )
            current_plans = self._contract_plans_with(
                connection,
                source_item,
                prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            )
            if current_plans:
                # The current contract is already accepted. Downstream retry
                # reuses it and requires no planning lineage mutation.
                continue

            source_plans = self._contract_plans_with(
                connection,
                source_item,
                prompt_version=FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
            )
            if len(source_plans) > 1:
                # R13: multiple previous-contract plans used to abort the
                # whole retry as "ambiguous". Deterministically continue the
                # lineage from the LATEST previous plan instead — migration
                # writes a new immutable row, so nothing historical mutates.
                source_plans.sort(
                    key=lambda plan: (
                        plan.created_at,
                        plan.plan_id,
                    )
                )
                source_plan_latest = source_plans[-1]
                logger.warning(
                    "document plan contract lineage ambiguous for artifact "
                    "%s: %d previous plans, migrating from the latest %s",
                    artifact_id,
                    len(source_plans),
                    source_plan_latest.plan_id,
                )
                source_plans = [source_plan_latest]
            if len(source_plans) == 1:
                source_plan = source_plans[0]
                migration_plan = self._build_contract_migration_plan(
                    connection,
                    source_item,
                    source_plan,
                    created_at=created_at,
                )
                if persist_migrations:
                    migration_plan = (
                        self.repository.save_document_structure_plan_with_connection(
                            connection,
                            migration_plan,
                            idempotency_key=(
                                "contract-migration:"
                                f"{migration_plan.contract_source_plan_id}:"
                                f"{migration_plan.contract_target_fingerprint}"
                            ),
                        )
                    )
                migration_plans.append(migration_plan)
                source_item_id = self._transition_source_item_id(
                    items,
                    fallback=source_item.item_id,
                )
                lineage = {
                    "document_plan_retry_generation": 0,
                    "document_plan_retry_parent_stage_run_id": "",
                    "document_plan_retry_source_item_id": "",
                    "document_plan_contract_transition_kind": "migration",
                    "document_plan_contract_transition_version": (
                        PLANNER_CONTRACT_TRANSITION_VERSION
                    ),
                    "document_plan_contract_generation": retry_generation,
                    "document_plan_contract_source_item_id": source_item_id,
                    "document_plan_contract_source_plan_id": (
                        source_plan.plan_id
                    ),
                    "document_plan_contract_target_plan_id": (
                        migration_plan.plan_id
                    ),
                    "document_plan_contract_source_stage_run_id": "",
                    "document_plan_contract_source_execution_fingerprint": "",
                    "document_plan_contract_source_prompt_version": (
                        FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
                    ),
                    "document_plan_contract_target_prompt_version": (
                        FLASH_PLANNING_PROMPT_VERSION
                    ),
                    "document_plan_contract_source_fingerprint": (
                        source_plan.planner_contract_fingerprint
                    ),
                    "document_plan_contract_target_fingerprint": (
                        migration_plan.planner_contract_fingerprint
                    ),
                }
                for item in items:
                    allocated[item.item_id] = lineage
                continue

            if any(
                item.error_code == "document_plan_failed"
                for item in items
            ):
                document_plan_failed_items = [
                    item
                    for item in items
                    if item.error_code == "document_plan_failed"
                ]
                # R14: several distinct persisted parents used to abort the
                # retry as "document_plan_retry_parent_missing_or_ambiguous"
                # (830+ items stranded with zero translations). The retry
                # must not pick between immutable parents, so reclassify the
                # group onto the parentless structural recovery path BEFORE
                # the allocator: clear parent links, keep the
                # lexicographically first item as the single non-derived
                # planner source, and mark the structural no-lineage code.
                distinct_parents = {
                    item.document_plan_failure_source_stage_run_id
                    for item in document_plan_failed_items
                    if item.document_plan_failure_source_stage_run_id
                }
                if len(distinct_parents) > 1:
                    logger.warning(
                        "document plan retry parents ambiguous for artifact "
                        "%s (%d distinct parents); reclassifying group onto "
                        "the parentless structural recovery path",
                        artifact_id,
                        len(distinct_parents),
                    )
                    primary_item_id = min(
                        item.item_id for item in document_plan_failed_items
                    )
                    document_plan_failed_items = [
                        item.model_copy(
                            update={
                                "document_plan_failure_source_stage_run_id": "",
                                "document_plan_failure_codes": [
                                    "document_plan_failed_earlier_in_same_run"
                                ],
                                "document_plan_failure_is_derived": (
                                    item.item_id != primary_item_id
                                ),
                            },
                            deep=True,
                        )
                        for item in document_plan_failed_items
                    ]
                ordinary_candidates.extend(document_plan_failed_items)
                continue
            if all(
                item.error_code == "service_restart_interrupted"
                for item in items
            ):
                # The prior owner may have died before any planner call or
                # immutable plan existed.  This is an ordinary failed-item
                # retry with no planner supersession lineage to allocate.
                continue
            # R13: any other failure shape with no planner lineage used to
            # abort the whole retry as
            # "document_plan_contract_source_missing_or_ambiguous", leaving
            # items permanently unretryable (e.g. failures recorded under an
            # unexpected error code before a plan existed). With no current
            # and no previous plan there is no supersession lineage to
            # allocate — treat these as ordinary failed items and let the
            # allocator run a fresh planner call against the same frozen
            # source, which is exactly the no-lineage recovery path above.
            logger.warning(
                "document plan contract lineage missing for artifact %s "
                "(error codes: %s); retrying as ordinary planner candidates",
                artifact_id,
                sorted({item.error_code or "" for item in items}),
            )
            # Reclassify as the internal "needs a fresh planner call" shape so
            # the allocator accepts them: document_plan_failed is the retry
            # classification, and document_plan_failed_earlier_in_same_run is
            # the honest structural marker that no plan lineage survived (the
            # persisted rows are rewritten by the retry machinery anyway).
            ordinary_candidates.extend(
                item.model_copy(
                    update={
                        "error_code": "document_plan_failed",
                        "document_plan_failure_codes": [
                            "document_plan_failed_earlier_in_same_run"
                        ],
                    },
                    deep=True,
                )
                for item in items
            )
            continue

        if ordinary_candidates:
            fallback_parentless = False
            try:
                ordinary = self._allocate_document_plan_retry_lineage(
                    connection,
                    ordinary_candidates,
                    retry_generation=retry_generation,
                )
            except ValueError as exc:
                if "parent_missing_or_ambiguous" not in str(exc):
                    raise
                fallback_parentless = True
                # 0924V1-R04: ancestry cannot be reconstructed safely, but a
                # retry must still converge. Allocate the parentless
                # zero-generation lineage directly (same shape as the
                # allocator's structural path), keeping every known parent
                # auditable in the warning log instead of leaving hundreds
                # of items permanently unretryable.
                known_parents = sorted(
                    {
                        item.document_plan_failure_source_stage_run_id or ""
                        for item in ordinary_candidates
                    }
                )
                logger.warning(
                    "document plan retry ancestry unresolved for %d items; "
                    "known parents=%s; allocating parentless structural "
                    "recovery (audit required before formal export)",
                    len(ordinary_candidates),
                    known_parents,
                )
                ordinary = {
                    item.item_id: {
                        "document_plan_retry_generation": 0,
                        "document_plan_retry_parent_stage_run_id": "",
                        "document_plan_retry_source_item_id": "",
                    }
                    for item in ordinary_candidates
                }
            by_parent: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
            for item_id, lineage in ordinary.items():
                by_parent[
                    lineage["document_plan_retry_parent_stage_run_id"]
                ][item_id] = lineage
            for parent_id, item_lineages in sorted(by_parent.items()):
                # Some early production attempts persisted a structural
                # planner failure on the batch item before the durable
                # upper-layer stage row was written.  The retry must not
                # invent a parent or mutate an immutable historical row.  A
                # parentless, zero-generation lineage is therefore allowed
                # only for the narrowly classified structural recovery path;
                # it will run a fresh planner call against the same frozen
                # source document and remains auditable in the retry event.
                if not parent_id:
                    if not fallback_parentless and not all(
                        _item_has_structural_planner_failure(item)
                        and not item.document_plan_failure_source_stage_run_id
                        for item in ordinary_candidates
                        if item.item_id in item_lineages
                    ):
                        raise ValueError(
                            "document_plan_retry_parent_missing_or_ambiguous"
                        )
                    allocated.update(item_lineages)
                    continue
                parent = self._upper_layer_stage_run_with(
                    connection,
                    failed_items[0].project_id,
                    parent_id,
                )
                if parent.prompt_version == FLASH_PLANNING_PROMPT_VERSION:
                    allocated.update(item_lineages)
                    continue
                if (
                    parent.prompt_version
                    != FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
                ):
                    raise ValueError(
                        "document_plan_contract_transition_not_allowlisted"
                    )
                parent_execution = connection.execute(
                    """
                    SELECT execution_fingerprint, input_hash
                    FROM writing_reference_upper_layer_stage_runs
                    WHERE tenant_id=? AND project_id=? AND stage_run_id=?
                    """,
                    (TENANT_ID, parent.project_id, parent.stage_run_id),
                ).fetchone()
                if parent_execution is None:
                    raise ValueError(
                        "document_plan_contract_source_missing_or_ambiguous"
                    )
                source_item_id = next(iter(item_lineages.values()))[
                    "document_plan_retry_source_item_id"
                ]
                source_item = next(
                    item
                    for item in failed_items
                    if item.item_id == source_item_id
                )
                expected_input_hash = self._current_planner_input_hash(
                    connection,
                    source_item,
                )
                expected_profile = str(
                    getattr(
                        getattr(
                            self.chapter_pipeline,
                            "upper_layer_executor",
                            None,
                        ),
                        "deployment_profile",
                        "",
                    )
                    or ""
                )
                source_fingerprint = str(
                    parent_execution["execution_fingerprint"]
                )
                if (
                    str(parent_execution["input_hash"])
                    != expected_input_hash
                    or parent.input_hash != expected_input_hash
                    or not expected_profile
                    or parent.deployment_profile != expected_profile
                    or parent.parent_stage_run_id
                    or parent.escalation_id
                    or parent.status
                    not in DOCUMENT_PLAN_RETRY_PARENT_STATUSES
                    or parent.retry_generation >= retry_generation
                    or len(source_fingerprint) != 64
                ):
                    raise ValueError(
                        "document_plan_contract_supersession_source_invalid"
                    )
                supersession = {
                    "document_plan_retry_generation": 0,
                    "document_plan_retry_parent_stage_run_id": "",
                    "document_plan_retry_source_item_id": "",
                    "document_plan_contract_transition_kind": (
                        "supersession"
                    ),
                    "document_plan_contract_transition_version": (
                        PLANNER_CONTRACT_TRANSITION_VERSION
                    ),
                    "document_plan_contract_generation": retry_generation,
                    "document_plan_contract_source_item_id": source_item_id,
                    "document_plan_contract_source_plan_id": "",
                    "document_plan_contract_target_plan_id": "",
                    "document_plan_contract_source_stage_run_id": (
                        parent.stage_run_id
                    ),
                    "document_plan_contract_source_execution_fingerprint": (
                        source_fingerprint
                    ),
                    "document_plan_contract_source_prompt_version": (
                        FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
                    ),
                    "document_plan_contract_target_prompt_version": (
                        FLASH_PLANNING_PROMPT_VERSION
                    ),
                    "document_plan_contract_source_fingerprint": "",
                    "document_plan_contract_target_fingerprint": "",
                }
                for item_id in item_lineages:
                    allocated[item_id] = supersession

        return _PlannerContractPreparation(
            item_lineage=allocated,
            migration_plans=tuple(
                sorted(migration_plans, key=lambda plan: plan.artifact_id)
            ),
        )

    @staticmethod
    def _transition_source_item_id(
        items: list[WritingReferenceTranslationBatchItem],
        *,
        fallback: str,
    ) -> str:
        retained = {
            item.document_plan_retry_source_item_id
            for item in items
            if item.document_plan_retry_source_item_id
        }
        if len(retained) > 1:
            raise ValueError(
                "document_plan_contract_source_missing_or_ambiguous"
            )
        source_item_id = next(iter(retained), fallback)
        if source_item_id not in {item.item_id for item in items}:
            raise ValueError(
                "document_plan_contract_source_missing_or_ambiguous"
            )
        return source_item_id

    @staticmethod
    def _validate_contract_group_identity(
        connection: Any,
        items: list[WritingReferenceTranslationBatchItem],
        *,
        artifact_id: str,
    ) -> None:
        source = items[0]
        if any(
            item.project_id != source.project_id
            or item.batch_id != source.batch_id
            or item.artifact_id != artifact_id
            or item.extraction_revision != source.extraction_revision
            or item.artifact_sha256 != source.artifact_sha256
            for item in items
        ):
            raise ValueError(
                "document_plan_contract_source_missing_or_ambiguous"
            )
        artifact_row = connection.execute(
            """
            SELECT content_sha256
            FROM writing_reference_document_artifacts
            WHERE tenant_id=? AND project_id=? AND artifact_id=?
            """,
            (TENANT_ID, source.project_id, artifact_id),
        ).fetchone()
        extraction_row = connection.execute(
            """
            SELECT 1
            FROM writing_reference_extractions
            WHERE tenant_id=? AND project_id=? AND artifact_id=?
              AND extraction_revision=?
            """,
            (
                TENANT_ID,
                source.project_id,
                artifact_id,
                source.extraction_revision,
            ),
        ).fetchone()
        if (
            artifact_row is None
            or extraction_row is None
            or str(artifact_row["content_sha256"])
            != source.artifact_sha256
        ):
            raise ValueError(
                "document_plan_contract_source_missing_or_ambiguous"
            )

    @staticmethod
    def _source_spans_with(
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
    ) -> tuple[WritingReferenceExtractedSpan, ...]:
        rows = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_source_spans
            WHERE tenant_id=? AND project_id=? AND artifact_id=?
              AND extraction_revision=?
            """,
            (
                TENANT_ID,
                item.project_id,
                item.artifact_id,
                item.extraction_revision,
            ),
        ).fetchall()
        spans = [
            WritingReferenceExtractedSpan.model_validate_json(
                row["payload_json"]
            )
            for row in rows
        ]
        return tuple(
            sorted(
                spans,
                key=lambda span: (
                    span.physical_page,
                    span.block_index,
                    span.span_id,
                ),
            )
        )

    def _current_planner_input_hash(
        self,
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
    ) -> str:
        spans = self._source_spans_with(connection, item)
        if not spans or item.span_id not in {span.span_id for span in spans}:
            raise ValueError(
                "document_plan_contract_source_missing_or_ambiguous"
            )
        artifact_row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_document_artifacts
            WHERE tenant_id=? AND project_id=? AND artifact_id=?
            """,
            (TENANT_ID, item.project_id, item.artifact_id),
        ).fetchone()
        if artifact_row is None:
            raise ValueError(
                "document_plan_contract_source_missing_or_ambiguous"
            )
        artifact_payload = json.loads(str(artifact_row["payload_json"]))
        source_text, context = build_document_planner_input(
            spans,
            document_context={
                "artifact_id": item.artifact_id,
                "document_type": str(
                    artifact_payload.get("document_type") or item.document_type
                ),
                "document_sha256": item.artifact_sha256,
                "extraction_revision": item.extraction_revision,
                "span_count": len(spans),
            },
        )
        return _payload_hash(
            _upper_layer_hash_payload(
                {
                    "source_text": source_text,
                    "document_context": context,
                }
            )
        )

    @staticmethod
    def _contract_plans_with(
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
        *,
        prompt_version: str,
    ) -> list[DocumentStructurePlan]:
        rows = connection.execute(
            """
            SELECT record.payload_json
            FROM writing_reference_document_structure_plan_state AS state
            JOIN writing_reference_document_structure_plans AS record
              ON record.tenant_id=state.tenant_id
             AND record.project_id=state.project_id
             AND record.plan_id=state.plan_id
            WHERE state.tenant_id=? AND state.project_id=?
              AND state.artifact_id=? AND state.extraction_revision=?
              AND record.planner_prompt_version=?
            ORDER BY record.created_at, record.plan_id
            """,
            (
                TENANT_ID,
                item.project_id,
                item.artifact_id,
                item.extraction_revision,
                prompt_version,
            ),
        ).fetchall()
        exact: list[DocumentStructurePlan] = []
        seen_ids: set[str] = set()
        for row in rows:
            plan = DocumentStructurePlan.model_validate_json(
                row["payload_json"]
            )
            expected = _planner_contract_fingerprint(
                artifact_id=item.artifact_id,
                extraction_revision=item.extraction_revision,
                planner_model=plan.planner_model,
                planner_prompt_version=prompt_version,
                document_sha256=item.artifact_sha256,
                translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
            )
            if (
                plan.plan_id not in seen_ids
                and plan.project_id == item.project_id
                and plan.artifact_id == item.artifact_id
                and plan.extraction_revision == item.extraction_revision
                and plan.document_sha256 == item.artifact_sha256
                and plan.planner_prompt_version == prompt_version
                and plan.planner_contract_fingerprint == expected
                and plan.status == "active"
            ):
                exact.append(plan)
                seen_ids.add(plan.plan_id)
        return exact

    def _build_contract_migration_plan(
        self,
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
        source_plan: DocumentStructurePlan,
        *,
        created_at: datetime,
    ) -> DocumentStructurePlan:
        if (
            source_plan.planner_prompt_version
            != FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
            or source_plan.document_role
            not in {"protocol", "protocol_with_sap", "sap", "csr"}
        ):
            raise ValueError(
                "document_plan_contract_transition_not_allowlisted"
            )
        expected_source_fingerprint = _planner_contract_fingerprint(
            artifact_id=item.artifact_id,
            extraction_revision=item.extraction_revision,
            planner_model=source_plan.planner_model,
            planner_prompt_version=FLASH_PLANNING_PREVIOUS_PROMPT_VERSION,
            document_sha256=item.artifact_sha256,
            translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        if (
            source_plan.planner_contract_fingerprint
            != expected_source_fingerprint
        ):
            raise ValueError(
                "document_plan_contract_source_fingerprint_mismatch"
            )

        spans = self._source_spans_with(connection, item)
        segments = build_document_planner_segments(spans)
        canonical = canonicalize_persisted_document_plan_chapters(
            source_plan.chapters,
            segments,
        )
        planner_input_hash = self._current_planner_input_hash(
            connection,
            item,
        )
        if source_plan.planner_input_hash != planner_input_hash:
            raise ValueError(
                "document_plan_contract_source_input_hash_mismatch"
            )
        target_fingerprint = _planner_contract_fingerprint(
            artifact_id=item.artifact_id,
            extraction_revision=item.extraction_revision,
            planner_model=SERVER_CONTRACT_MIGRATION_NAMESPACE,
            planner_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            document_sha256=item.artifact_sha256,
            translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        target_chapters = [
            DocumentStructurePlanChapter(
                chapter_id=chapter["id"],
                chapter_order=chapter["chapter_order"],
                title=chapter["title"],
                heading_path=list(chapter["heading_path"]),
                ich_m11_anchor=chapter["ich_m11_anchor"],
                source_span_ids=list(chapter["source_span_ids"]),
                ambiguity_codes=list(chapter["ambiguity_codes"]),
            )
            for chapter in canonical
        ]
        target_payload_sha256 = _payload_hash(
            {
                "document_role": source_plan.document_role,
                "chapters": [
                    chapter.model_dump(mode="json")
                    for chapter in target_chapters
                ],
            }
        )
        source_payload_sha256 = _payload_hash(
            source_plan.model_dump(mode="json")
        )
        plan_id = "docplan_" + _payload_hash(
            {
                "namespace": SERVER_CONTRACT_MIGRATION_NAMESPACE,
                "transition_version": PLANNER_CONTRACT_TRANSITION_VERSION,
                "source_plan_id": source_plan.plan_id,
                "source_payload_sha256": source_payload_sha256,
                "target_fingerprint": target_fingerprint,
                "target_payload_sha256": target_payload_sha256,
            }
        )[:24]
        return DocumentStructurePlan(
            plan_id=plan_id,
            project_id=item.project_id,
            artifact_id=item.artifact_id,
            extraction_revision=item.extraction_revision,
            document_sha256=item.artifact_sha256,
            document_role=source_plan.document_role,
            planner_model=SERVER_CONTRACT_MIGRATION_NAMESPACE,
            planner_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            planner_input_hash=planner_input_hash,
            planner_output_hash=target_payload_sha256,
            planner_contract_fingerprint=target_fingerprint,
            chapters=target_chapters,
            ambiguity_codes=list(source_plan.ambiguity_codes),
            status="active",
            created_at=created_at,
            parent_plan_id=source_plan.plan_id,
            contract_migration_namespace=(
                SERVER_CONTRACT_MIGRATION_NAMESPACE
            ),
            contract_transition_version=(
                PLANNER_CONTRACT_TRANSITION_VERSION
            ),
            contract_source_plan_id=source_plan.plan_id,
            contract_source_fingerprint=(
                source_plan.planner_contract_fingerprint
            ),
            contract_target_fingerprint=target_fingerprint,
            contract_source_prompt_version=(
                FLASH_PLANNING_PREVIOUS_PROMPT_VERSION
            ),
            contract_target_prompt_version=FLASH_PLANNING_PROMPT_VERSION,
            contract_source_payload_sha256=source_payload_sha256,
            contract_target_payload_sha256=target_payload_sha256,
        )

    def _allocate_document_plan_retry_lineage(
        self,
        connection: Any,
        failed_items: list[WritingReferenceTranslationBatchItem],
        *,
        retry_generation: int,
    ) -> dict[str, dict[str, Any]]:
        groups: dict[str, list[WritingReferenceTranslationBatchItem]] = (
            defaultdict(list)
        )
        for item in failed_items:
            if item.error_code == "document_plan_failed":
                groups[item.artifact_id].append(item)

        allocated: dict[str, dict[str, Any]] = {}
        for artifact_id, items in sorted(groups.items()):
            source_ids = {
                item.document_plan_failure_source_stage_run_id
                for item in items
                if item.document_plan_failure_source_stage_run_id
            }
            if len(source_ids) > 1:
                # R14: several distinct persisted parents used to abort the
                # whole retry as "document_plan_retry_parent_missing_or_ambiguous",
                # leaving 800+ translation items permanently unretryable.
                # The retry must not pick between immutable parents, so
                # reclassify the group onto the parentless structural
                # recovery path: clear parent links on all copies, keep the
                # lexicographically first item as the single non-derived
                # planner source, and mark the structural no-lineage code.
                logger.warning(
                    "document plan retry parents ambiguous for artifact %s "
                    "(%d distinct parents); reclassifying group onto the "
                    "parentless structural recovery path",
                    artifact_id,
                    len(source_ids),
                )
                primary_item_id = min(item.item_id for item in items)
                items = [
                    item.model_copy(
                        update={
                            "error_code": "document_plan_failed",
                            "document_plan_failure_codes": [
                                "document_plan_failed_earlier_in_same_run"
                            ],
                            "document_plan_failure_source_stage_run_id": "",
                            "document_plan_failure_is_derived": (
                                item.item_id != primary_item_id
                            ),
                        },
                        deep=True,
                    )
                    for item in items
                ]
                source_ids = set()
            source_items = [
                item
                for item in items
                if not item.document_plan_failure_is_derived
            ]
            parent = None
            source_item = None
            if len(source_ids) == 1:
                parent = self._upper_layer_stage_run_with(
                    connection,
                    items[0].project_id,
                    next(iter(source_ids)),
                )
                matching_sources = [
                    item
                    for item in source_items
                    if item.item_id == parent.owner_id
                ]
                if len(matching_sources) == 1:
                    source_item = matching_sources[0]
            elif len(source_items) == 1:
                source_item = source_items[0]
                active_run_id = source_item.active_upper_layer_stage_run_id
                if active_run_id:
                    parent = self._upper_layer_stage_run_with(
                        connection,
                        source_item.project_id,
                        active_run_id,
                    )
                else:
                    parent = (
                        self.repository.latest_failed_upper_layer_source_stage_run(
                            source_item.project_id,
                            owner_type="translation_batch_item",
                            owner_id=source_item.item_id,
                            artifact_id=source_item.artifact_id,
                            extraction_revision=source_item.extraction_revision,
                            requested_model=FLASH_PLANNING_MODEL,
                            connection=connection,
                        )
                    )
                if parent is None:
                    # A pre-fix structural failure may have no persisted
                    # upper-layer parent at all.  Permit only a fully
                    # structural, source-stage-less group to retry from the
                    # immutable extracted segments; all other missing-parent
                    # cases remain fail-closed.
                    if not (
                        all(
                            not item.document_plan_failure_source_stage_run_id
                            and _item_has_structural_planner_failure(item)
                            for item in items
                        )
                        and len(source_items) == 1
                    ):
                        raise ValueError(
                            "document_plan_retry_parent_missing_or_ambiguous"
                        )
                    allocated_lineage = {
                        "document_plan_retry_generation": 0,
                        "document_plan_retry_parent_stage_run_id": "",
                        "document_plan_retry_source_item_id": "",
                    }
                    for item in items:
                        allocated[item.item_id] = allocated_lineage
                    continue
            elif len(source_items) == len(items):
                # Legacy payloads omit both source-lineage fields, so every
                # member parses as non-derived. Infer only from exact persisted
                # ownership and only when one group member is a candidate.
                candidates: list[
                    tuple[
                        WritingReferenceTranslationBatchItem,
                        Any,
                    ]
                ] = []
                for candidate_item in items:
                    candidate_parent = (
                        self.repository.latest_failed_upper_layer_source_stage_run(
                            candidate_item.project_id,
                            owner_type="translation_batch_item",
                            owner_id=candidate_item.item_id,
                            artifact_id=candidate_item.artifact_id,
                            extraction_revision=(
                                candidate_item.extraction_revision
                            ),
                            requested_model=FLASH_PLANNING_MODEL,
                            connection=connection,
                        )
                    )
                    if candidate_parent is not None:
                        candidates.append(
                            (candidate_item, candidate_parent)
                        )
                if len(candidates) != 1:
                    raise ValueError(
                        "document_plan_retry_parent_missing_or_ambiguous"
                    )
                source_item, parent = candidates[0]
            else:
                raise ValueError(
                    "document_plan_retry_parent_missing_or_ambiguous"
                )
            if parent is None or source_item is None:
                raise ValueError(
                    "document_plan_retry_parent_missing_or_ambiguous"
                )
            if (
                parent.project_id != source_item.project_id
                or parent.owner_type != "translation_batch_item"
                or parent.owner_id != source_item.item_id
                or parent.batch_id != source_item.batch_id
                or parent.item_id != source_item.item_id
                or parent.artifact_id != artifact_id
                or parent.extraction_revision
                != source_item.extraction_revision
                or parent.stage != UPPER_LAYER_DOCUMENT_PLANNING
                or parent.requested_model != FLASH_PLANNING_MODEL
                or parent.response_model != FLASH_PLANNING_MODEL
                or parent.parent_stage_run_id
                or parent.escalation_id
                or parent.status not in DOCUMENT_PLAN_RETRY_PARENT_STATUSES
                or parent.retry_generation >= retry_generation
                or any(
                    item.project_id != source_item.project_id
                    or item.batch_id != source_item.batch_id
                    or item.artifact_id != artifact_id
                    or item.extraction_revision
                    != source_item.extraction_revision
                    for item in items
                )
            ):
                raise ValueError(
                    "document_plan_retry_parent_missing_or_ambiguous"
                )
            lineage = {
                "document_plan_retry_generation": retry_generation,
                "document_plan_retry_parent_stage_run_id": (
                    parent.stage_run_id
                ),
                "document_plan_retry_source_item_id": source_item.item_id,
            }
            for item in items:
                allocated[item.item_id] = lineage
        return allocated

    @staticmethod
    def _upper_layer_stage_run_with(
        connection: Any,
        project_id: str,
        stage_run_id: str,
    ) -> Any:
        from packages.contracts.workbench_contracts import (
            WritingReferenceUpperLayerStageRun,
        )

        row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_upper_layer_stage_runs
            WHERE tenant_id=? AND project_id=? AND stage_run_id=?
            """,
            (TENANT_ID, project_id, stage_run_id),
        ).fetchone()
        if row is None:
            raise ValueError(
                "document_plan_retry_parent_missing_or_ambiguous"
            )
        return WritingReferenceUpperLayerStageRun.model_validate_json(
            row["payload_json"]
        )

    def run_pending(self, project_id: str, batch_id: str, actor: str) -> None:
        self._run_items(project_id, batch_id, actor, {"pending"})

    def run_failed(self, project_id: str, batch_id: str, actor: str) -> None:
        self._run_items(project_id, batch_id, actor, {"failed_retryable"})

    def run_pending_with_callbacks(
        self,
        project_id: str,
        batch_id: str,
        actor: str,
        cancel_check: Callable[[], bool] | None = None,
        heartbeat: Callable[..., bool] | None = None,
    ) -> None:
        """Run pending items under durable job claim/heartbeat/cancel semantics.

        When *cancel_check* returns True (lost lease or explicit cancel), the
        executor stops processing further items without writing terminal state.
        """
        self._run_items(
            project_id,
            batch_id,
            actor,
            {"pending"},
            cancel_check=cancel_check,
            heartbeat=heartbeat,
        )

    def run_failed_with_callbacks(
        self,
        project_id: str,
        batch_id: str,
        actor: str,
        cancel_check: Callable[[], bool] | None = None,
        heartbeat: Callable[..., bool] | None = None,
    ) -> None:
        """Run failed-retryable items under durable job claim/heartbeat/cancel."""
        self._run_items(
            project_id,
            batch_id,
            actor,
            {"failed_retryable"},
            cancel_check=cancel_check,
            heartbeat=heartbeat,
        )

    def run_downstream_contract_transition_with_callbacks(
        self,
        project_id: str,
        transition_id: str,
        actor: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
        heartbeat: Callable[..., bool] | None = None,
    ) -> None:
        """Claim and process exactly the target item named by a transition."""
        record = self.downstream_contract_transition(
            project_id,
            transition_id,
        )
        batch = self.get(project_id, record.target_batch_id)
        raw_items = [
            item
            for item in batch.items
            if item.item_id == record.target_item_id
        ]
        if (
            len(batch.items) != 1
            or len(raw_items) != 1
            or raw_items[0].downstream_contract_transition_id
            != transition_id
        ):
            raise WritingReferenceConflictError(
                "downstream transition child batch is not exactly one item"
            )
        if cancel_check is not None:
            try:
                if cancel_check():
                    return
            except Exception:
                return
        with self.repository._connect() as connection:
            row = connection.execute(
                """
                SELECT generation_status
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND item_id=?
                """,
                (
                    TENANT_ID,
                    project_id,
                    record.target_batch_id,
                    record.target_item_id,
                ),
            ).fetchone()
        if row is None:
            raise WritingReferenceConflictError(
                "downstream transition target item is missing"
            )
        if str(row["generation_status"]) not in {
            "pending",
            "failed_retryable",
        }:
            self._refresh_batch_status(project_id, record.target_batch_id)
            return
        self._set_batch_status(
            project_id,
            record.target_batch_id,
            "running",
        )
        claimed = self._claim_item(
            project_id,
            record.target_batch_id,
            record.target_item_id,
            {"pending", "failed_retryable"},
        )
        if claimed is None:
            self._refresh_batch_status(project_id, record.target_batch_id)
            return
        self._process_claimed_item(
            claimed,
            batch.preparation_batch_id,
            actor,
            cancel_check=cancel_check,
        )
        if heartbeat is not None:
            from packages.contracts.workbench_contracts import (
                DurableJobProgressPayload,
            )

            try:
                heartbeat(
                    DurableJobProgressPayload(
                        phase="translating",
                        percent=1.0,
                        step=1,
                        step_total=1,
                        message="1/1 downstream transition item processed",
                    )
                )
            except Exception:
                pass
        self._refresh_batch_status(project_id, record.target_batch_id)

    def get(self, project_id: str, batch_id: str) -> WritingReferenceTranslationBatch:
        with self.repository._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM writing_reference_translation_batches
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchone()
            if row is None:
                raise KeyError(batch_id)
            item_rows = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                ORDER BY item_id
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchall()
        items = [
            WritingReferenceTranslationBatchItem.model_validate_json(item["payload_json"])
            for item in item_rows
        ]
        items = self._project_review_and_admission(project_id, items)
        exclusions = [
            WritingReferenceTranslationBatchExclusion.model_validate(item)
            for item in json.loads(row["exclusions_json"])
        ]
        return WritingReferenceTranslationBatch(
            batch_id=str(row["batch_id"]),
            project_id=str(row["project_id"]),
            snapshot_id=str(row["snapshot_id"]),
            glossary_version=str(row["glossary_version"]),
            anchor_filter=json.loads(row["anchor_filter_json"]),
            preparation_batch_id=str(row["preparation_batch_id"]),
            scope_sha256=str(row["scope_sha256"]),
            status=str(row["status"]),
            attempt=int(row["attempt"]),
            counts=self._counts(items, exclusions),
            items=items,
            exclusions=exclusions,
            created_by=str(row["created_by"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def latest(self, project_id: str, snapshot_id: str) -> WritingReferenceTranslationBatch:
        with self.repository._connect() as connection:
            row = connection.execute(
                """
                SELECT batch_id
                FROM writing_reference_translation_batches
                WHERE tenant_id=? AND project_id=? AND snapshot_id=?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (TENANT_ID, project_id, snapshot_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"{project_id}/{snapshot_id}")
        return self.get(project_id, str(row["batch_id"]))

    def _derive_scope(
        self,
        project_id: str,
        request: WritingReferenceTranslationBatchPreviewRequest,
    ) -> _ScopeProjection:
        base_request = request.model_copy(
            update={"anchor_filter": [], "max_spans_per_anchor": None}
        )
        cache_key, snapshot_context = self._preview_scope_cache_key(
            project_id, base_request
        )
        base_scope = self._unfiltered_scope_cache
        if (
            base_scope is None
            or self._unfiltered_scope_cache_key != cache_key
        ):
            base_scope = self._derive_scope_uncached(
                project_id,
                base_request,
                snapshot_context=snapshot_context,
            )
            self._unfiltered_scope_cache_key = cache_key
            self._unfiltered_scope_cache = base_scope
        return self._project_scope(base_scope, request)

    def _derive_scope_uncached(
        self,
        project_id: str,
        request: WritingReferenceTranslationBatchPreviewRequest,
        *,
        snapshot_context: tuple[Any, Any] | None = None,
    ) -> _ScopeProjection:
        journey, preparation = snapshot_context or self._snapshot_scope(
            project_id, request.snapshot_id
        )
        retained_ids = self._effective_retained_ids(
            journey, preparation, snapshot_id=request.snapshot_id
        )
        artifacts = [
            artifact
            for artifact in self.repository.document_artifacts(
                project_id, request.snapshot_id
            )
            if artifact.source_current and artifact.nct_id in retained_ids
        ]
        by_nct: dict[str, list[Any]] = defaultdict(list)
        for artifact in artifacts:
            by_nct[artifact.nct_id].append(artifact)

        exclusions: list[WritingReferenceTranslationBatchExclusion] = []
        item_specs: list[dict[str, Any]] = []
        scope_documents: list[dict[str, Any]] = []
        for nct_id in retained_ids:
            if not by_nct.get(nct_id):
                exclusions.append(
                    WritingReferenceTranslationBatchExclusion(
                        scope="document",
                        reason_code="no_current_artifact",
                        nct_id=nct_id,
                    )
                )
                continue
            for artifact in sorted(by_nct[nct_id], key=lambda item: item.artifact_id):
                document_scope = {
                    "nct_id": nct_id,
                    "artifact_id": artifact.artifact_id,
                    "artifact_sha256": artifact.content_sha256,
                    "artifact_state_revision": artifact.state_revision,
                    "validation_id": "",
                    "validation_revision": 0,
                    "validation_status": "",
                    "extraction_revision": "",
                    "structure_review_id": "",
                    "structure_review_revision": 0,
                    "ocr_qc_effective_status": "",
                    "ocr_qc_recheck_id": "",
                    "ocr_qc_recheck_revision": 0,
                    "ocr_qc_disposition_id": "",
                    "ocr_qc_disposition_revision": 0,
                    "spans": [],
                }
                exclusion_reason = self._document_gate(
                    project_id, artifact, document_scope
                )
                if exclusion_reason:
                    exclusions.append(
                        WritingReferenceTranslationBatchExclusion(
                            scope="document",
                            reason_code=exclusion_reason,
                            nct_id=nct_id,
                            artifact_id=artifact.artifact_id,
                        )
                    )
                    scope_documents.append(document_scope)
                    continue

                spans = self.repository.source_spans(
                    project_id,
                    artifact.artifact_id,
                    extraction_revision=document_scope["extraction_revision"],
                )
                if not spans:
                    exclusions.append(
                        WritingReferenceTranslationBatchExclusion(
                            scope="document",
                            reason_code="latest_extraction_has_no_spans",
                            nct_id=nct_id,
                            artifact_id=artifact.artifact_id,
                        )
                    )
                protocol_span_ids, corpus_scope_reasons = protocol_corpus_span_scope(
                    artifact,
                    spans,
                )
                for span in spans:
                    reason = corpus_scope_reasons.get(span.span_id, "")
                    if not reason and span.span_id in protocol_span_ids:
                        reason = self._span_exclusion_reason(
                            span,
                            request.anchor_filter,
                        )
                    elif not reason:
                        reason = "standalone_sap_not_corpus_input"
                    span_scope = {
                        "span_id": span.span_id,
                        "source_text_sha256": span.source_text_sha256,
                        "ich_m11_anchor": span.ich_m11_anchor,
                        "exclusion": reason,
                    }
                    document_scope["spans"].append(span_scope)
                    if reason:
                        exclusions.append(
                            WritingReferenceTranslationBatchExclusion(
                                scope="span",
                                reason_code=reason,
                                nct_id=nct_id,
                                artifact_id=artifact.artifact_id,
                                span_id=span.span_id,
                                ich_m11_anchor=span.ich_m11_anchor,
                            )
                        )
                        continue
                    existing = self._current_translation(
                        project_id,
                        span.span_id,
                        request.glossary_version,
                        artifact.content_sha256,
                    )
                    if existing is not None and existing.fidelity_status == "passed":
                        origin = "existing"
                        generation_status = "candidate_ready"
                    else:
                        # Never adopt fidelity_blocked rows into a new batch —
                        # that short-circuits Hy-MT2/single-span regeneration and
                        # leaves research unlock stuck on stale chapter ZH.
                        existing = None
                        origin = "new"
                        generation_status = "pending"
                    contract = self._contract_provenance(existing)
                    item_specs.append(
                        {
                            "glossary_version": request.glossary_version,
                            "span": span,
                            "artifact": artifact,
                            "validation_id": document_scope["validation_id"],
                            "validation_revision": document_scope["validation_revision"],
                            "validation_status": document_scope["validation_status"],
                            "extraction_revision": document_scope["extraction_revision"],
                            "structure_review_id": document_scope["structure_review_id"],
                            "structure_review_revision": document_scope[
                                "structure_review_revision"
                            ],
                            "ocr_qc_effective_status": document_scope[
                                "ocr_qc_effective_status"
                            ],
                            "ocr_qc_recheck_id": document_scope[
                                "ocr_qc_recheck_id"
                            ],
                            "ocr_qc_recheck_revision": document_scope[
                                "ocr_qc_recheck_revision"
                            ],
                            "ocr_qc_disposition_id": document_scope[
                                "ocr_qc_disposition_id"
                            ],
                            "ocr_qc_disposition_revision": document_scope[
                                "ocr_qc_disposition_revision"
                            ],
                            "contract_hash": contract["contract_hash"],
                            "prompt_version": contract["prompt_version"],
                            "schema_version": contract["schema_version"],
                            "origin": origin,
                            "generation_status": generation_status,
                            "translation": existing,
                        }
                    )
                scope_documents.append(document_scope)

        max_per_anchor = getattr(request, "max_spans_per_anchor", None)
        if max_per_anchor:
            by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for spec in item_specs:
                by_anchor[str(spec["span"].ich_m11_anchor)].append(spec)
            capped: list[dict[str, Any]] = []
            for anchor in sorted(by_anchor):
                ranked = sorted(by_anchor[anchor], key=_research_span_cap_rank)
                capped.extend(ranked[: int(max_per_anchor)])
            item_specs = capped

        scope_sha256 = _payload_hash(
            {
                "project_id": project_id,
                "snapshot_id": request.snapshot_id,
                "glossary_version": request.glossary_version,
                "anchor_filter": request.anchor_filter,
                "max_spans_per_anchor": max_per_anchor,
                "documents": scope_documents,
                "contract": self._contract_provenance(None),
                "exclusions": [
                    item.model_dump(mode="json")
                    for item in sorted(
                        exclusions,
                        key=lambda item: (
                            item.scope,
                            item.reason_code,
                            item.nct_id,
                            item.artifact_id,
                            item.span_id,
                        ),
                    )
                ],
            }
        )
        anchor_counts: dict[str, Counter[str]] = defaultdict(Counter)
        for spec in item_specs:
            anchor = spec["span"].ich_m11_anchor
            if spec["generation_status"] == "pending":
                anchor_counts[anchor]["eligible_new"] += 1
            elif spec["generation_status"] == "candidate_ready":
                anchor_counts[anchor]["existing_candidate"] += 1
            else:
                anchor_counts[anchor]["fidelity_blocked"] += 1
        summaries = [
            WritingReferenceTranslationBatchAnchorSummary(
                ich_m11_anchor=anchor,
                eligible_new=counts["eligible_new"],
                existing_candidate=counts["existing_candidate"],
                fidelity_blocked=counts["fidelity_blocked"],
            )
            for anchor, counts in sorted(anchor_counts.items())
        ]
        document_reasons = Counter(
            item.reason_code for item in exclusions if item.scope == "document"
        )
        span_reasons = Counter(
            item.reason_code for item in exclusions if item.scope == "span"
        )
        preview = WritingReferenceTranslationBatchPreview(
            project_id=project_id,
            snapshot_id=request.snapshot_id,
            glossary_version=request.glossary_version,
            anchor_filter=request.anchor_filter,
            preparation_batch_id=preparation.batch_id,
            scope_sha256=scope_sha256,
            eligible_count=len(item_specs),
            eligible_new_count=sum(spec["origin"] == "new" for spec in item_specs),
            existing_candidate_count=sum(
                spec["generation_status"] == "candidate_ready" for spec in item_specs
            ),
            fidelity_blocked_count=sum(
                spec["generation_status"] == "fidelity_blocked" for spec in item_specs
            ),
            excluded_count=sum(item.count for item in exclusions),
            anchor_summaries=summaries,
            document_exclusion_reason_counts=dict(sorted(document_reasons.items())),
            span_exclusion_reason_counts=dict(sorted(span_reasons.items())),
            exclusions=self._fold_exclusions(exclusions),
        )
        return _ScopeProjection(
            preview=preview,
            item_specs=item_specs,
            scope_documents=scope_documents,
            exclusions=exclusions,
        )

    def _preview_scope_cache_key(
        self,
        project_id: str,
        request: WritingReferenceTranslationBatchPreviewRequest,
    ) -> tuple[str, tuple[Any, Any]]:
        """Return a current, non-persistent fingerprint for the base scope.

        The query intentionally reads only state/provenance rows.  It does not
        deserialize source spans or translations, which is the expensive part
        of preview.  Extraction payload hashes cover the immutable span set;
        state/revision columns cover all current validation, structure-review,
        and effective OCR lineage transitions.  Current translation state is
        included because it changes ``pending`` versus ``candidate_ready``.
        """
        journey, preparation = self._snapshot_scope(project_id, request.snapshot_id)
        retained_ids = self._effective_retained_ids(
            journey, preparation, snapshot_id=request.snapshot_id
        )
        lineage = self._current_scope_lineage(
            project_id,
            request.snapshot_id,
            retained_ids,
        )
        triage = getattr(journey, "corpus_triage", None)
        discovery = getattr(journey, "discovery_basket_projection", None)
        context = {
            "project_id": project_id,
            "snapshot_id": request.snapshot_id,
            "glossary_version": request.glossary_version,
            "preparation": {
                "batch_id": getattr(preparation, "batch_id", ""),
                "status": getattr(preparation, "status", ""),
                "retained_candidate_ids": sorted(
                    dict.fromkeys(
                        getattr(preparation, "retained_candidate_ids", None) or []
                    )
                ),
            },
            "journey_authority": {
                "search_snapshot_id": getattr(
                    getattr(journey, "search_plan", None),
                    "latest_snapshot_id",
                    "",
                ),
                "triage": {
                    "status": getattr(triage, "status", ""),
                    "snapshot_id": getattr(triage, "snapshot_id", ""),
                    "retained_candidate_ids": sorted(
                        dict.fromkeys(
                            getattr(triage, "retained_candidate_ids", None) or []
                        )
                    ),
                },
                "discovery": {
                    "confirmation_id": getattr(discovery, "confirmation_id", ""),
                    "snapshot_id": getattr(discovery, "snapshot_id", ""),
                    "retained_nct_ids": sorted(
                        dict.fromkeys(
                            getattr(discovery, "retained_nct_ids", None) or []
                        )
                    ),
                },
            },
            "contract": self._contract_provenance(None),
            "lineage": lineage,
        }
        return _payload_hash(context), (journey, preparation)

    def _current_scope_lineage(
        self,
        project_id: str,
        snapshot_id: str,
        retained_ids: list[str],
    ) -> dict[str, Any]:
        """Read only current lineage rows used to validate a cached preview.

        This is intentionally implemented here rather than as a repository
        schema change for R42-005.  The query is cheap and deterministic, while
        the actual source-span/protocol-scope walk remains reserved for a cache
        miss.  All values are identifiers, revisions, hashes, and statuses;
        source text and credentials are never placed in the cache key.
        """
        if not retained_ids:
            return {"artifacts": [], "translations": []}
        placeholders = ",".join("?" for _ in retained_ids)
        artifact_params: list[Any] = [
            TENANT_ID,
            project_id,
            TENANT_ID,
            project_id,
            snapshot_id,
            *retained_ids,
        ]
        artifact_query = f"""
            WITH latest_extractions AS (
                SELECT artifact_id, extraction_revision, payload_hash,
                       ROW_NUMBER() OVER (
                           PARTITION BY artifact_id
                           ORDER BY created_at DESC, extraction_revision DESC
                       ) AS row_number
                FROM writing_reference_extractions
                WHERE tenant_id=? AND project_id=?
            )
            SELECT artifact.artifact_id, artifact.nct_id,
                   artifact.content_sha256, artifact.payload_hash,
                   document_state.revision AS artifact_state_revision,
                   document_state.source_current,
                   extraction.extraction_revision,
                   extraction.payload_hash AS extraction_payload_hash,
                   validation_state.validation_id,
                   validation_state.revision AS validation_revision,
                   validation_state.status AS validation_status,
                   review_state.review_id AS structure_review_id,
                   review_state.revision AS structure_review_revision,
                   review_state.extraction_revision AS structure_review_extraction_revision,
                   review_state.decision AS structure_review_decision,
                   ocr_state.recheck_id AS ocr_recheck_id,
                   ocr_state.revision AS ocr_recheck_revision,
                   ocr_state.verdict AS ocr_recheck_verdict,
                   disposition_state.disposition_id AS ocr_disposition_id,
                   disposition_state.revision AS ocr_disposition_revision,
                   disposition_state.decision AS ocr_disposition_decision
            FROM writing_reference_document_artifacts AS artifact
            JOIN writing_reference_document_state AS document_state
              ON document_state.tenant_id=artifact.tenant_id
             AND document_state.project_id=artifact.project_id
             AND document_state.artifact_id=artifact.artifact_id
            LEFT JOIN latest_extractions AS extraction
              ON extraction.artifact_id=artifact.artifact_id
             AND extraction.row_number=1
            LEFT JOIN writing_reference_document_validation_state AS validation_state
              ON validation_state.tenant_id=artifact.tenant_id
             AND validation_state.project_id=artifact.project_id
             AND validation_state.artifact_id=artifact.artifact_id
            LEFT JOIN writing_reference_extraction_review_state AS review_state
              ON review_state.tenant_id=artifact.tenant_id
             AND review_state.project_id=artifact.project_id
             AND review_state.artifact_id=artifact.artifact_id
             AND review_state.extraction_revision=extraction.extraction_revision
            LEFT JOIN writing_reference_ocr_consistency_qc_recheck_state AS ocr_state
              ON ocr_state.tenant_id=artifact.tenant_id
             AND ocr_state.project_id=artifact.project_id
             AND ocr_state.artifact_id=artifact.artifact_id
             AND ocr_state.extraction_revision=extraction.extraction_revision
            LEFT JOIN writing_reference_ocr_consistency_medical_disposition_state AS disposition_state
              ON disposition_state.tenant_id=artifact.tenant_id
             AND disposition_state.project_id=artifact.project_id
             AND disposition_state.artifact_id=artifact.artifact_id
             AND disposition_state.extraction_revision=extraction.extraction_revision
            WHERE artifact.tenant_id=? AND artifact.project_id=?
              AND artifact.snapshot_id=?
              AND artifact.nct_id IN ({placeholders})
            ORDER BY artifact.artifact_id
        """
        translation_params: list[Any] = [
            TENANT_ID,
            project_id,
            snapshot_id,
            *retained_ids,
        ]
        translation_query = f"""
            SELECT translation_state.translation_id,
                   translation_state.revision,
                   translation_state.span_id,
                   translation_state.status,
                   translation_state.updated_at
            FROM writing_reference_translation_state AS translation_state
            JOIN writing_reference_source_spans AS span
              ON span.tenant_id=translation_state.tenant_id
             AND span.project_id=translation_state.project_id
             AND span.span_id=translation_state.span_id
            JOIN writing_reference_document_artifacts AS artifact
              ON artifact.tenant_id=span.tenant_id
             AND artifact.project_id=span.project_id
             AND artifact.artifact_id=span.artifact_id
            WHERE translation_state.tenant_id=? AND translation_state.project_id=?
              AND artifact.snapshot_id=?
              AND artifact.nct_id IN ({placeholders})
            ORDER BY translation_state.translation_id, translation_state.revision
        """
        with self.repository._connect() as connection:
            artifact_rows = connection.execute(
                artifact_query, artifact_params
            ).fetchall()
            translation_rows = connection.execute(
                translation_query, translation_params
            ).fetchall()
        return {
            "artifacts": [dict(row) for row in artifact_rows],
            "translations": [dict(row) for row in translation_rows],
        }

    def _project_scope(
        self,
        base_scope: _ScopeProjection,
        request: WritingReferenceTranslationBatchPreviewRequest,
    ) -> _ScopeProjection:
        """Project anchor/cap filters from the cached no-filter scope."""
        if not request.anchor_filter and not getattr(
            request, "max_spans_per_anchor", None
        ):
            return base_scope

        exclusions = list(base_scope.exclusions)
        scope_documents: list[dict[str, Any]] = []
        selected_anchors = set(request.anchor_filter)
        for document in base_scope.scope_documents:
            projected_document = {
                key: value for key, value in document.items() if key != "spans"
            }
            projected_spans: list[dict[str, Any]] = []
            for span_scope in document.get("spans", []):
                projected_span = dict(span_scope)
                if (
                    selected_anchors
                    and not projected_span.get("exclusion")
                    and projected_span.get("ich_m11_anchor") not in selected_anchors
                ):
                    projected_span["exclusion"] = "anchor_filtered"
                    exclusions.append(
                        WritingReferenceTranslationBatchExclusion(
                            scope="span",
                            reason_code="anchor_filtered",
                            nct_id=str(document.get("nct_id", "")),
                            artifact_id=str(document.get("artifact_id", "")),
                            span_id=str(projected_span.get("span_id", "")),
                            ich_m11_anchor=str(
                                projected_span.get("ich_m11_anchor", "")
                            ),
                        )
                    )
                projected_spans.append(projected_span)
            projected_document["spans"] = projected_spans
            scope_documents.append(projected_document)

        item_specs = [
            spec
            for spec in base_scope.item_specs
            if not selected_anchors
            or spec["span"].ich_m11_anchor in selected_anchors
        ]
        max_per_anchor = getattr(request, "max_spans_per_anchor", None)
        if max_per_anchor:
            item_specs = self._cap_item_specs(item_specs, int(max_per_anchor))

        scope_sha256 = _payload_hash(
            {
                "project_id": base_scope.preview.project_id,
                "snapshot_id": request.snapshot_id,
                "glossary_version": request.glossary_version,
                "anchor_filter": request.anchor_filter,
                "max_spans_per_anchor": max_per_anchor,
                "documents": scope_documents,
                "contract": self._contract_provenance(None),
                "exclusions": [
                    item.model_dump(mode="json")
                    for item in sorted(
                        exclusions,
                        key=lambda item: (
                            item.scope,
                            item.reason_code,
                            item.nct_id,
                            item.artifact_id,
                            item.span_id,
                        ),
                    )
                ],
            }
        )
        anchor_counts: dict[str, Counter[str]] = defaultdict(Counter)
        for spec in item_specs:
            anchor = spec["span"].ich_m11_anchor
            if spec["generation_status"] == "pending":
                anchor_counts[anchor]["eligible_new"] += 1
            elif spec["generation_status"] == "candidate_ready":
                anchor_counts[anchor]["existing_candidate"] += 1
            else:
                anchor_counts[anchor]["fidelity_blocked"] += 1
        summaries = [
            WritingReferenceTranslationBatchAnchorSummary(
                ich_m11_anchor=anchor,
                eligible_new=counts["eligible_new"],
                existing_candidate=counts["existing_candidate"],
                fidelity_blocked=counts["fidelity_blocked"],
            )
            for anchor, counts in sorted(anchor_counts.items())
        ]
        document_reasons = Counter(
            item.reason_code for item in exclusions if item.scope == "document"
        )
        span_reasons = Counter(
            item.reason_code for item in exclusions if item.scope == "span"
        )
        preview = WritingReferenceTranslationBatchPreview(
            project_id=base_scope.preview.project_id,
            snapshot_id=request.snapshot_id,
            glossary_version=request.glossary_version,
            anchor_filter=request.anchor_filter,
            preparation_batch_id=base_scope.preview.preparation_batch_id,
            scope_sha256=scope_sha256,
            eligible_count=len(item_specs),
            eligible_new_count=sum(spec["origin"] == "new" for spec in item_specs),
            existing_candidate_count=sum(
                spec["generation_status"] == "candidate_ready" for spec in item_specs
            ),
            fidelity_blocked_count=sum(
                spec["generation_status"] == "fidelity_blocked"
                for spec in item_specs
            ),
            excluded_count=sum(item.count for item in exclusions),
            anchor_summaries=summaries,
            document_exclusion_reason_counts=dict(sorted(document_reasons.items())),
            span_exclusion_reason_counts=dict(sorted(span_reasons.items())),
            exclusions=self._fold_exclusions(exclusions),
        )
        return _ScopeProjection(
            preview=preview,
            item_specs=item_specs,
            scope_documents=scope_documents,
            exclusions=exclusions,
        )

    @staticmethod
    def _cap_item_specs(
        item_specs: list[dict[str, Any]], max_per_anchor: int
    ) -> list[dict[str, Any]]:
        by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for spec in item_specs:
            by_anchor[str(spec["span"].ich_m11_anchor)].append(spec)
        capped: list[dict[str, Any]] = []
        for anchor in sorted(by_anchor):
            capped.extend(
                sorted(by_anchor[anchor], key=_research_span_cap_rank)[:max_per_anchor]
            )
        return capped

    @staticmethod
    def _effective_retained_ids(
        journey: Any,
        preparation: Any,
        *,
        snapshot_id: str,
    ) -> list[str]:
        """Return the retained scope that _snapshot_scope already validated.

        Authority selection (finalized corpus triage vs confirmed discovery
        projection) happens in ``_snapshot_scope``. Once that gate passes, the
        preparation batch's frozen ``retained_candidate_ids`` is the single
        effective scope for preview/create and frozen-lineage checks.
        """
        _ = journey  # journey is part of the validated lineage context
        if not snapshot_id:
            raise ValueError("batch translation requires a locked snapshot id")
        retained_ids = sorted(
            dict.fromkeys(getattr(preparation, "retained_candidate_ids", None) or [])
        )
        if not retained_ids:
            raise ValueError("confirmed basket has no retained candidates")
        return retained_ids

    def _snapshot_scope(self, project_id: str, snapshot_id: str) -> tuple[Any, Any]:
        journey = self.journey_service.get(project_id)
        triage = journey.corpus_triage

        # Authority path A (post-PICOS): finalized corpus triage.
        corpus_finalized = (
            triage is not None
            and triage.status == "finalized"
            and triage.snapshot_id == snapshot_id
        )

        # Authority path B (pre-PICOS): authoritative confirmed discovery
        # basket projection — the same authority the preparation service
        # already accepts. Without this, translation is deadlocked waiting
        # for corpus triage finalization that cannot happen until PICOS is
        # complete, but PICOS itself needs competitor Protocol/SAP
        # translation to be informed. This does NOT weaken content
        # validation or corpus admission; it only supplies the retained
        # candidate scope for document preparation/translation.
        discovery = getattr(journey, "discovery_basket_projection", None)
        discovery_confirmed = (
            discovery is not None
            and getattr(discovery, "confirmation_id", "")
            and getattr(discovery, "snapshot_id", "") == snapshot_id
            and journey.search_plan is not None
            and journey.search_plan.latest_snapshot_id == snapshot_id
        )

        if not corpus_finalized and not discovery_confirmed:
            raise ValueError(
                "batch translation requires either finalized corpus triage "
                "or a confirmed discovery basket projection for the locked "
                "snapshot"
            )

        if (
            journey.search_plan is None
            or journey.search_plan.latest_snapshot_id != snapshot_id
        ):
            raise ValueError(
                "batch translation must use the authoring journey's locked current snapshot"
            )

        self.repository.search_snapshot(project_id, snapshot_id)
        try:
            preparation = self.preparation_service.latest(project_id, snapshot_id)
        except KeyError as exc:
            # A newly locked search snapshot has no preparation batch until the
            # user starts the visible Protocol preparation step.  Do not leak
            # the repository's ``project/snapshot`` KeyError into the browser;
            # this is an expected, recoverable workflow state and the user
            # needs an actionable next step rather than a raw identifier.
            raise ValueError(
                "translation scope is not ready: start Protocol preparation "
                "for the locked snapshot in 文档与解析 before opening 结构与译文确认"
            ) from exc
        if preparation.status not in TERMINAL_PREPARATION_STATUSES:
            raise ValueError("latest writing-reference preparation batch is not terminal")

        # Retained IDs: prefer finalized corpus triage, fall back to the
        # confirmed discovery projection (same effective scope the
        # preparation batch was built from).
        if corpus_finalized and triage is not None:
            retained_ids = sorted(dict.fromkeys(triage.retained_candidate_ids))
        elif discovery is not None:
            retained_ids = sorted(dict.fromkeys(discovery.retained_nct_ids))
        else:
            retained_ids = []

        if not retained_ids:
            raise ValueError("confirmed basket has no retained candidates")
        if sorted(preparation.retained_candidate_ids) != retained_ids:
            raise ValueError(
                "latest preparation batch does not match the confirmed retained scope"
            )
        return journey, preparation

    def _document_gate(
        self,
        project_id: str,
        artifact: Any,
        document_scope: dict[str, Any],
    ) -> str:
        try:
            validation = self.repository.document_validation(
                project_id, artifact.artifact_id
            )
        except KeyError:
            return "validation_missing"
        document_scope.update(
            {
                "validation_id": validation.validation_id,
                "validation_revision": validation.revision,
                "validation_status": validation.status,
            }
        )
        if validation.status not in {"confirmed", "user_overridden"}:
            return "validation_not_confirmed"
        if validation.document_sha256 != artifact.content_sha256:
            return "validation_document_hash_mismatch"
        if validation.source_state_revision != artifact.state_revision:
            return "validation_state_stale"
        try:
            extraction_revision = self.repository.latest_extraction_revision(
                project_id, artifact.artifact_id
            )
        except KeyError:
            return "latest_extraction_missing"
        document_scope["extraction_revision"] = extraction_revision
        if validation.extraction_revision != extraction_revision:
            return "validation_extraction_stale"
        review = next(
            (
                item
                for item in self.repository.extraction_reviews(
                    project_id, artifact_id=artifact.artifact_id
                )
                if item.extraction_revision == extraction_revision
            ),
            None,
        )
        if review is None:
            return "structure_review_missing"
        document_scope.update(
            {
                "structure_review_id": review.review_id,
                "structure_review_revision": review.revision,
            }
        )
        if review.decision != "approved":
            return "structure_review_not_approved"
        ocr_projection = self.repository.effective_ocr_consistency_qc(
            project_id,
            artifact.artifact_id,
            extraction_revision,
        )
        document_scope.update(
            {
                "ocr_qc_effective_status": ocr_projection.effective_status,
                "ocr_qc_recheck_id": ocr_projection.recheck_id,
                "ocr_qc_recheck_revision": ocr_projection.recheck_revision,
                "ocr_qc_disposition_id": ocr_projection.disposition_id,
                "ocr_qc_disposition_revision": ocr_projection.disposition_revision,
            }
        )
        if ocr_projection.effective_status == "pending_medical_confirmation":
            return "ocr_consistency_pending_confirmation"
        if ocr_projection.effective_status == "blocked":
            return "ocr_consistency_blocked"
        return ""

    @staticmethod
    def _span_exclusion_reason(span: Any, anchor_filter: list[str]) -> str:
        if span.source_text_sha256 != sha256(span.source_text.encode("utf-8")).hexdigest():
            return "source_text_hash_mismatch"
        if span.ich_m11_anchor == "unmapped":
            return "unmapped"
        if anchor_filter and span.ich_m11_anchor not in anchor_filter:
            return "anchor_filtered"
        if span.source_text.strip().endswith((",", "，")):
            return "semantic_fragment_incomplete"
        return ""

    def _current_translation(
        self,
        project_id: str,
        span_id: str,
        glossary_version: str,
        document_sha256: str,
    ) -> WritingReferenceTranslationRevision | None:
        matcher = getattr(
            self.translation_service, "translation_matches_current_contract", None
        )
        projector = getattr(
            self.translation_service,
            "project_translation_to_current_contract",
            None,
        )
        if not callable(matcher):
            return None
        matches = []
        for translation in self.repository.translations(project_id, span_id):
            if (
                translation.glossary_version != glossary_version
                or translation.document_sha256 != document_sha256
                or translation.status
                not in {
                    "pending_author_confirmation",
                    "author_confirmed_admitted",
                    "pending_medical_approval",
                }
            ):
                continue
            try:
                current_contract = bool(matcher(project_id, translation))
            except (KeyError, OSError, TypeError, ValueError):
                current_contract = False
            if current_contract:
                if callable(projector):
                    try:
                        translation = projector(project_id, translation)
                    except (KeyError, OSError, TypeError, ValueError):
                        continue
                elif not translation.contract_hash:
                    translation = translation.model_copy(
                        update={
                            **self._contract_provenance(None),
                        }
                    )
                matches.append(translation)
        if not matches:
            return None
        return sorted(matches, key=lambda item: (item.revision, item.created_at))[-1]

    def _contract_provenance(
        self, translation: WritingReferenceTranslationRevision | None
    ) -> dict[str, str]:
        current = {
            "contract_hash": getattr(
                self.translation_service,
                "contract_hash",
                REGULATORY_TRANSLATION_CONTRACT_HASH,
            ),
            "prompt_version": getattr(
                self.translation_service,
                "prompt_version",
                REGULATORY_TRANSLATION_PROMPT_VERSION,
            ),
            "schema_version": getattr(
                self.translation_service,
                "schema_version",
                REGULATORY_TRANSLATION_SCHEMA_VERSION,
            ),
        }
        if translation is not None:
            return {
                "contract_hash": translation.contract_hash
                or current["contract_hash"],
                "prompt_version": translation.prompt_version
                or current["prompt_version"],
                "schema_version": translation.schema_version
                or current["schema_version"],
            }
        return current

    @staticmethod
    def _fold_exclusions(
        exclusions: list[WritingReferenceTranslationBatchExclusion],
    ) -> list[WritingReferenceTranslationBatchExclusion]:
        grouped: dict[
            tuple[str, str, str], list[WritingReferenceTranslationBatchExclusion]
        ] = defaultdict(list)
        for item in exclusions:
            anchor = item.ich_m11_anchor if item.reason_code == "anchor_filtered" else ""
            grouped[(item.scope, item.reason_code, anchor)].append(item)

        visible: list[WritingReferenceTranslationBatchExclusion] = []
        for (scope, reason_code, anchor), items in sorted(grouped.items()):
            if reason_code == "anchor_filtered":
                visible.append(
                    WritingReferenceTranslationBatchExclusion(
                        scope=scope,
                        reason_code=reason_code,
                        count=sum(item.count for item in items),
                        ich_m11_anchor=anchor,
                    )
                )
                continue
            examples = items[:EXCLUSION_EXAMPLE_LIMIT]
            visible.extend(examples)
            remainder = sum(item.count for item in items[EXCLUSION_EXAMPLE_LIMIT:])
            if remainder:
                visible.append(
                    WritingReferenceTranslationBatchExclusion(
                        scope=scope,
                        reason_code=reason_code,
                        count=remainder,
                    )
                )
        return visible

    def _new_item(
        self,
        project_id: str,
        batch_id: str,
        snapshot_id: str,
        spec: dict[str, Any],
        now: datetime,
    ) -> WritingReferenceTranslationBatchItem:
        span = spec["span"]
        artifact = spec["artifact"]
        translation = spec["translation"]
        item_id = "wref_translation_item_" + _payload_hash(
            {"batch_id": batch_id, "span_id": span.span_id}
        )[:24]
        return WritingReferenceTranslationBatchItem(
            item_id=item_id,
            batch_id=batch_id,
            project_id=project_id,
            snapshot_id=snapshot_id,
            glossary_version=spec["glossary_version"],
            span_id=span.span_id,
            artifact_id=artifact.artifact_id,
            nct_id=artifact.nct_id,
            filename=artifact.filename,
            document_type=artifact.document_type,
            ich_m11_anchor=span.ich_m11_anchor,
            source_locator=span.source_locator,
            source_text_sha256=span.source_text_sha256,
            source_span_revision=f"{span.span_id}_r1",
            artifact_sha256=artifact.content_sha256,
            artifact_state_revision=artifact.state_revision,
            validation_id=spec["validation_id"],
            validation_revision=spec["validation_revision"],
            validation_status=spec["validation_status"],
            extraction_revision=spec["extraction_revision"],
            structure_review_id=spec["structure_review_id"],
            structure_review_revision=spec["structure_review_revision"],
            ocr_qc_effective_status=spec["ocr_qc_effective_status"],
            ocr_qc_recheck_id=spec["ocr_qc_recheck_id"],
            ocr_qc_recheck_revision=spec["ocr_qc_recheck_revision"],
            ocr_qc_disposition_id=spec["ocr_qc_disposition_id"],
            ocr_qc_disposition_revision=spec["ocr_qc_disposition_revision"],
            contract_hash=spec["contract_hash"],
            prompt_version=spec["prompt_version"],
            schema_version=spec["schema_version"],
            origin=spec["origin"],
            generation_status=spec["generation_status"],
            translation_id=translation.translation_id if translation else "",
            translation_revision=translation.revision if translation else 0,
            ai_run_id=translation.ai_run_id if translation else "",
            fidelity_status=translation.fidelity_status if translation else "",
            fidelity_failure_codes=(
                list(translation.fidelity_failure_codes) if translation else []
            ),
            created_at=now,
            updated_at=now,
        )

    def _run_items(
        self,
        project_id: str,
        batch_id: str,
        actor: str,
        allowed_statuses: set[str],
        *,
        cancel_check: Callable[[], bool] | None = None,
        heartbeat: Callable[..., bool] | None = None,
    ) -> None:
        batch = self.get(project_id, batch_id)
        item_ids = self._item_ids(project_id, batch_id, allowed_statuses)
        if item_ids:
            # Fail-closed ownership check before the first business write.
            # If the claim was lost after executor entry but before
            # _run_items, we must not mutate batch status.
            if cancel_check is not None:
                try:
                    _lost = cancel_check()
                except Exception:
                    _lost = True
                if _lost:
                    return
            self._set_batch_status(project_id, batch_id, "running")
        document_plan_failures: dict[str, DocumentPlanValidationError] = {}
        for item_id in item_ids:
            # Cooperative cancel: stop processing further items when the
            # durable job has been cancelled or the lease was lost.
            # Exception in cancel_check = treat as lost (fail-closed).
            if cancel_check is not None:
                try:
                    _lost = cancel_check()
                except Exception:
                    _lost = True
                if _lost:
                    return
            item = self._claim_item(
                project_id, batch_id, item_id, allowed_statuses
            )
            if item is None:
                continue
            if item.artifact_id in document_plan_failures:
                source_failure = document_plan_failures[item.artifact_id]
                self._fail_claim(
                    item,
                    "failed_retryable",
                    "document_plan_failed",
                    DocumentPlanValidationError(
                        (
                            "document_plan_failed_earlier_in_same_run",
                            *source_failure.codes,
                        ),
                        source_stage_run_id=(
                            source_failure.source_stage_run_id
                        ),
                        latest_stage_run_id=(
                            source_failure.latest_stage_run_id
                        ),
                        derived_from_source_failure=True,
                    ),
                    actor,
                    cancel_check=cancel_check,
                )
                continue
            document_plan_failure = self._process_claimed_item(
                item, batch.preparation_batch_id, actor,
                cancel_check=cancel_check,
            )
            if (
                document_plan_failure is not None
                and not document_plan_failure.derived_from_source_failure
            ):
                document_plan_failures[item.artifact_id] = document_plan_failure
            # Heartbeat after each item so the durable worker knows we
            # are alive and the lease is renewed.  A False return means
            # claim loss — must stop immediately.
            if heartbeat is not None:
                from packages.contracts.workbench_contracts import (
                    DurableJobProgressPayload,
                )

                completed = self.get(project_id, batch_id)
                total = len(completed.items) if completed.items else len(item_ids)
                # A failed-retryable item has still been processed for this
                # execution pass.  Excluding it made the durable progress
                # remain at e.g. 2/20 while the UI correctly showed 17/20,
                # which obscured the active item and looked like a stalled
                # worker.  Only pending/running items are unprocessed.
                done = sum(
                    1
                    for i in completed.items
                    if i.generation_status not in {"pending", "running"}
                )
                try:
                    hb_ok = heartbeat(
                        DurableJobProgressPayload(
                            phase="translating",
                            percent=(done / total) if total else 0.0,
                            step=done,
                            step_total=total,
                            message=f"{done}/{total} items processed",
                        )
                    )
                except Exception:
                    # Unexpected heartbeat error: claim may be unstable.
                    # Stop processing without terminal business writes.
                    return
                if not hb_ok:
                    # Heartbeat returned False — claim lost.
                    return
        self._refresh_batch_status(project_id, batch_id)

    def _item_ids(
        self,
        project_id: str,
        batch_id: str,
        statuses: set[str],
    ) -> list[str]:
        placeholders = ",".join("?" for _ in statuses)
        with self.repository._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND generation_status IN ({placeholders})
                """,
                (TENANT_ID, project_id, batch_id, *sorted(statuses)),
            ).fetchall()
        items = [
            WritingReferenceTranslationBatchItem.model_validate_json(
                row["payload_json"]
            )
            for row in rows
        ]
        return [
            item.item_id
            for item in sorted(
                items,
                key=lambda item: (
                    item.artifact_id,
                    0
                    if (
                        (
                            item.document_plan_retry_generation > 0
                            and item.item_id
                            == item.document_plan_retry_source_item_id
                        )
                        or (
                            item.document_plan_contract_transition_kind
                            == "supersession"
                            and item.item_id
                            == item.document_plan_contract_source_item_id
                        )
                    )
                    else 1,
                    item.item_id,
                ),
            )
        ]

    def _claim_item(
        self,
        project_id: str,
        batch_id: str,
        item_id: str,
        allowed_statuses: set[str],
    ) -> WritingReferenceTranslationBatchItem | None:
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT generation_status, attempt, payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
                """,
                (TENANT_ID, project_id, batch_id, item_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise KeyError(item_id)
            status = str(row["generation_status"])
            attempt = int(row["attempt"])
            if status not in allowed_statuses:
                connection.commit()
                return None
            item = WritingReferenceTranslationBatchItem.model_validate_json(
                row["payload_json"]
            ).model_copy(
                update={
                    "generation_status": "running",
                    "attempt": attempt + 1,
                    "error_code": "",
                    "error_detail": "",
                    "document_plan_failure_source_stage_run_id": "",
                    "document_plan_failure_codes": [],
                    "document_plan_failure_is_derived": False,
                    "updated_at": self.clock(),
                },
                deep=True,
            )
            cursor = connection.execute(
                """
                UPDATE writing_reference_translation_batch_items
                SET generation_status='running', attempt=?, payload_json=?, updated_at=?
                WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
                  AND generation_status=? AND attempt=?
                """,
                (
                    item.attempt,
                    _canonical_json(item.model_dump(mode="json")),
                    item.updated_at.isoformat(),
                    TENANT_ID,
                    project_id,
                    batch_id,
                    item_id,
                    status,
                    attempt,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return None
            self._set_downstream_transition_state_with(
                connection,
                item,
                status="running",
                error_code="",
            )
            connection.commit()
            return item

    def _process_claimed_item(
        self,
        item: WritingReferenceTranslationBatchItem,
        preparation_batch_id: str,
        actor: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> DocumentPlanValidationError | None:
        # Check ownership before expensive product AI work.
        if cancel_check is not None and cancel_check():
            return None
        try:
            self._validate_frozen_lineage(item, preparation_batch_id)
            if self.chapter_pipeline is None:
                # Production must fail closed — no silent legacy fallback.
                raise CompositePipelineUnavailableError(
                    "composite chapter translation pipeline is not configured"
                )
            self._process_with_composite_pipeline(
                item, actor, cancel_check=cancel_check
            )
            return None
        except _OwnershipLostError:
            # Ownership lost during pipeline execution.  Do NOT write any
            # terminal business state — the stale owner must not persist
            # failure or completion, and no document-plan failure propagates
            # to sibling items.
            return None
        except WritingReferenceTranslationBatchStaleLineageError as exc:
            # Re-check ownership before writing terminal failure state.
            if cancel_check is not None and cancel_check():
                return None
            self._fail_claim(
                item,
                "failed_terminal",
                "stale_lineage",
                exc,
                actor,
                cancel_check=cancel_check,
            )
            return None
        except WritingReferenceTranslationModelCallOutcomeUnknownError as exc:
            if cancel_check is not None and cancel_check():
                return None
            self._fail_claim(
                item,
                "failed_terminal",
                "model_call_outcome_unknown_after_restart",
                exc,
                actor,
                cancel_check=cancel_check,
            )
            return None
        except DocumentPlanValidationError as exc:
            if cancel_check is not None and cancel_check():
                return None
            self._fail_claim(
                item,
                "failed_retryable",
                "document_plan_failed",
                exc,
                actor,
                cancel_check=cancel_check,
            )
            return exc
        except Exception as exc:
            if cancel_check is not None and cancel_check():
                return None
            # 0924V2 §5 temporary diagnostics: the generic wrapper hides the
            # real cause for the 26 stuck items (failure precedes stage-run
            # creation). Full stack goes to the operational log; remove once
            # the root cause is fixed.
            import traceback as _tb

            logger.error(
                "translation item %s failed with full stack:\n%s",
                item.item_id,
                _tb.format_exc(),
            )
            self._fail_claim(
                item,
                "failed_retryable",
                "translation_generation_failed",
                exc,
                actor,
                cancel_check=cancel_check,
            )
            return None

    def _process_with_legacy_translation(
        self, item: WritingReferenceTranslationBatchItem, actor: str
    ) -> None:
        """Legacy Flash-only translation path (backward compatibility).

        Used only when no composite pipeline is wired.  This preserves
        existing behavior for deployments that have not yet enabled the
        composite Flash plan -> Hy-MT2 -> Flash QC pipeline.
        """
        translation = self.translation_service.translate(
            item.project_id,
            WritingReferenceTranslationRequest(
                span_id=item.span_id,
                glossary_version=item.glossary_version,
                actor=actor,
                idempotency_key=(
                    f"batch:{item.batch_id}:{item.item_id}:attempt:{item.attempt}"
                ),
            ),
        )
        self._validate_translation_result(item, translation)
        status = (
            "candidate_ready"
            if translation.fidelity_status == "passed"
            else "fidelity_blocked"
        )
        completed = item.model_copy(
            update={
                "generation_status": status,
                "pipeline_stage": status,
                "pipeline_stage_detail": (
                    "翻译完成，可核对并使用"
                    if status == "candidate_ready"
                    else "译文忠实度校验未通过，请处理异常"
                ),
                "translation_id": translation.translation_id,
                "translation_revision": translation.revision,
                "ai_run_id": translation.ai_run_id,
                "fidelity_status": translation.fidelity_status,
                "fidelity_failure_codes": list(
                    translation.fidelity_failure_codes
                ),
                "error_code": "",
                "error_detail": "",
                "updated_at": self.clock(),
            },
            deep=True,
        )
        self._finish_claim(item, completed, actor)

    def _process_with_composite_pipeline(
        self, item: WritingReferenceTranslationBatchItem, actor: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Authoritative document-level composite pipeline body path (Round 8).

        Contract:

            one immutable document plan
            -> deterministic chapter chunks
            -> Hy-MT2 once per pending chunk
            -> Flash integration/QC once per ordinary chapter or ordered windows
            -> deterministic final fidelity
            -> exactly one immutable WritingReferenceTranslationRevision
               per integrated chapter

        Span items only carry a primary ``span_id`` for foreign-key
        compatibility; every item in the same chapter references the same
        translation_id/revision.
        """
        assert self.chapter_pipeline is not None
        span = self.repository.source_span(item.project_id, item.span_id)
        artifact = self.repository.document_artifact(item.project_id, item.artifact_id)

        ocr_page_lineage = self._lookup_ocr_lineage(item)
        batch = self.get(item.project_id, item.batch_id)
        document_ids = list(dict.fromkeys(i.artifact_id for i in batch.items))
        document_total = len(document_ids)
        document_index = (
            document_ids.index(item.artifact_id) + 1
            if item.artifact_id in document_ids
            else 0
        )
        document_label = item.filename or artifact.filename or item.artifact_id
        progress_context: dict[str, Any] = {
            "document_total": document_total,
            "document_index": document_index,
            "document_label": document_label,
        }

        def _guard() -> None:
            """Fail-closed ownership check. Raises _OwnershipLostError."""
            if cancel_check is not None:
                try:
                    lost = cancel_check()
                except Exception:
                    # Ownership-check exception = treat as lost.
                    lost = True
                if lost:
                    raise _OwnershipLostError("ownership lost or cancelled")

        def _stage_observer(
            phase: str, stage: Any, detail: dict | None = None, **kwargs: Any
        ) -> None:
            _guard()
            merged = dict(progress_context)
            merged.update(detail or {})
            merged.update(kwargs)
            self._persist_pipeline_stage(item, stage, phase, merged)
            # The stage transaction is the durable precondition for an
            # external model call. Recheck the durable claim after that commit:
            # a takeover in the guard-to-commit window must stop this owner
            # before it can invoke the provider.
            _guard()

        # -- Step 1: Get-or-create document plan (once per identity). -----
        _guard()
        plan = self._get_or_create_document_plan(
            item, artifact, span, _stage_observer
        )

        # -- Step 2: Resolve chapter membership (fail closed). -----------
        chapter_id = self._resolve_chapter_for_span(plan, span.span_id)
        chapter_title = self._chapter_title(plan, chapter_id)
        chapter_index = self._chapter_index(plan, chapter_id)
        chapter_total = len(plan.chapters)
        source_span_count = next(
            (
                len(chapter.source_span_ids)
                for chapter in plan.chapters
                if chapter.chapter_id == chapter_id
            ),
            0,
        )
        progress_context.update(
            {
                "document_structure_plan_id": plan.plan_id,
                "chapter_id": chapter_id,
                "chapter_title": chapter_title,
                "chapter_total": chapter_total,
                "chapter_index": chapter_index,
                "source_span_count": source_span_count,
            }
        )

        research_like = str(getattr(batch, "created_by", "") or "").startswith(
            "research_pipeline"
        ) or (
            bool(getattr(batch, "anchor_filter", None))
            and len(getattr(batch, "items", ()) or ()) <= 24
        )

        if batch.anchor_filter and not self._chapter_matches_anchor_filter(
            plan, chapter_id, batch.anchor_filter
        ):
            # The accepted document plan refines the extraction-time anchor.
            # Once the plan assigns a span outside the requested chapter scope,
            # the sticky extraction anchor must not widen that scope again.
            _guard()
            self._exclude_claim_after_document_plan(
                item,
                plan,
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                chapter_index=chapter_index,
                chapter_total=chapter_total,
                source_span_count=source_span_count,
                document_total=document_total,
                document_index=document_index,
                document_label=document_label,
                actor=actor,
                cancel_check=cancel_check,
            )
            return

        # -- Step 3: Reuse completed chapter integration + revision. -----
        # Only an integration produced under the CURRENT downstream
        # translation contract (explicit fingerprint) may be reused.  Rows
        # written under an older contract stay immutable on disk but are
        # never silently returned as current output.
        integration_chapter_id = (
            f"{chapter_id}::{item.span_id}::{item.batch_id}"
            if research_like
            else chapter_id
        )
        existing_integration = self.repository.chapter_integration_result(
            item.project_id,
            plan.plan_id,
            integration_chapter_id,
            translation_contract_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
        )
        # Abbreviation glossaries (``X = definition; Y = …`` walls) are not
        # clinical narrative — Hy-MT2 collapses them and blocks critical-anchor
        # unlock. Exclude from research single-span translation.
        if research_like and self._looks_like_abbreviation_glossary(
            str(getattr(span, "source_text", "") or "")
        ):
            _guard()
            self._exclude_claim_after_document_plan(
                item,
                plan,
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                chapter_index=chapter_index,
                chapter_total=chapter_total,
                source_span_count=source_span_count,
                document_total=document_total,
                document_index=document_index,
                document_label=document_label,
                actor=actor,
                cancel_check=cancel_check,
                exclude_reason="abbreviation_glossary_span",
            )
            return
        if existing_integration is not None:
            _guard()
            saved = self._link_item_to_chapter_revision(
                item, artifact, span, plan, chapter_id, chapter_title,
                existing_integration, ocr_page_lineage,
                research_like=research_like,
            )
            _guard()
            self._finish_composite_item(
                item, saved, existing_integration, plan,
                chapter_id, chapter_title, ocr_page_lineage,
                reused=True, actor=actor,
                chunk_count=len(existing_integration.chunk_ids),
                chunk_completed=len(existing_integration.chunk_ids),
                chunk_reused=len(existing_integration.chunk_ids),
                span_count=source_span_count,
                document_total=document_total,
                document_index=document_index,
                document_label=document_label,
                chapter_total=chapter_total,
                chapter_index=chapter_index,
                cancel_check=cancel_check,
            )
            return

        # -- Step 4: Deterministic chunks for this chapter. --------------
        all_spans = self.repository.source_spans(
            item.project_id,
            artifact.artifact_id,
            extraction_revision=span.extraction_revision,
        )
        all_spans_tuple = tuple(all_spans)
        from .chapter_translation_pipeline import DocumentPlanResult as _DPR
        plan_result = _DPR(
            flash_plan=None,  # type: ignore[arg-type]
            chapters=tuple(
                (ch.chapter_id, ch.title, ch.ich_m11_anchor, tuple(ch.source_span_ids))
                for ch in plan.chapters
            ),
            document_role=plan.document_role,
            ambiguity_codes=tuple(plan.ambiguity_codes),
        )
        chapter_chunks_map = build_chunks_from_plan(plan_result, all_spans_tuple)
        chapter_chunks: list = []
        for entry in chapter_chunks_map:
            for key, chunks in entry.items():
                if key[0] == chapter_id:
                    chapter_chunks = list(chunks)
                    break

        if not chapter_chunks:
            raise DocumentPlanValidationError(
                (f"chapter_{chapter_id}_empty_chunks",)
            )

        # Research / capped batches: translate ONLY this item's source span.
        # Multi-span chapter chunks otherwise Hy-MT2 a whole neighborhood and
        # the chapter-level integrated ZH can be a different unit than the
        # batch item's span — fidelity then fails on every item (wrong source
        # vs wrong target). Single-span chunks keep lineage span-addressable.
        # max_spans_per_anchor is create-request-only today; research actors
        # and small anchor-filtered batches are the durable runtime signal.
        max_spans = getattr(batch, "max_spans_per_anchor", None)
        # research_like already computed above for integration reuse skip
        if (max_spans is not None and int(max_spans) > 0) or research_like:
            primary = next(
                (s for s in all_spans_tuple if s.span_id == item.span_id),
                span,
            )
            chapter_span_ids = set(
                next(
                    (
                        tuple(ch.source_span_ids)
                        for ch in plan.chapters
                        if ch.chapter_id == chapter_id
                    ),
                    (item.span_id,),
                )
            )
            chapter_span_objs = [
                s for s in all_spans_tuple if s.span_id in chapter_span_ids
            ] or [primary]
            span_order = {
                s.span_id: idx for idx, s in enumerate(chapter_span_objs)
            }
            chapter_chunks = [
                _make_chunk(
                    chapter_id=chapter_id,
                    span_ids=[item.span_id],
                    texts=[str(getattr(primary, "source_text", "") or "")],
                    all_spans=list(all_spans_tuple),
                    span_order=span_order,
                    chapter_spans=chapter_span_objs,
                    next_span_idx=span_order.get(item.span_id, 0) + 1,
                    chunk_order=1,
                    context_chars=0,
                    oversize_mark="research_single_span",
                )
            ]
        # Full-document batches keep every chunk assigned to the chapter.
        # The persisted integration and translation revision are chapter-level
        # artifacts, so narrowing them to the current batch item's span would
        # silently omit sibling chunks and make oversized chapters appear
        # non-windowed. Subsequent sibling items reuse the completed chapter
        # integration instead of retranslating it.

        chunk_count = len(chapter_chunks)
        chunk_reused = 0
        chunk_completed = 0
        chunk_failed = 0
        chunk_running = 0
        stage_ledger: list[CompositePipelineRunStage] = [
            CompositePipelineRunStage(
                stage="toc_planning",
                model=plan.planner_model,
                prompt_version=plan.planner_prompt_version,
                input_hash=plan.planner_input_hash,
                output_hash=plan.planner_output_hash,
            )
        ]

        # -- Step 5: Hy-MT2 per pending chunk (reuse completed). ---------
        existing_chunks = self.repository.translation_chunks_for_plan(
            item.project_id, plan.plan_id
        )
        existing_by_fp = {ec.chunk_fingerprint: ec for ec in existing_chunks}
        chunk_translations: list[tuple[Any, str]] = []
        # Aligned unit data per chunk: (chunk_spec, units, target_map).
        # Chapter-level Flash integration consumes these to build the
        # aligned marked source/target envelope.
        chunk_aligned: list[tuple[Any, tuple, dict[int, str]]] = []
        # Hy-stage blocking state: a second failed corrective pass stops the
        # chapter as fidelity-blocked (never silently admitted, never an
        # unbounded retry loop).
        hy_block_codes: list[str] = []
        hy_block_text = ""
        hy_block_raw_text = ""
        hy_block_chunk_id = ""
        for chunk_spec in chapter_chunks:
            existing_chunk = existing_by_fp.get(chunk_spec.chunk_fingerprint)
            if existing_chunk is not None and existing_chunk.status == "completed":
                reused_units = split_source_into_units(chunk_spec.source_text)
                reused_map = reconstruct_unit_map(
                    existing_chunk.translated_text,
                    existing_chunk.unit_targets,
                    reused_units,
                )
                chunk_translations.append(
                    (chunk_spec, existing_chunk.translated_text)
                )
                chunk_aligned.append((chunk_spec, reused_units, reused_map))
                chunk_reused += 1
                chunk_completed += 1
                stage_ledger.append(
                    CompositePipelineRunStage(
                        stage="translating_hy_mt2_reused",
                        model=existing_chunk.hy_mt2_model,
                        prompt_version=existing_chunk.hy_mt2_prompt_version,
                        input_hash=existing_chunk.hy_mt2_input_hash,
                        output_hash=existing_chunk.translated_text_sha256,
                    )
                )
                continue

            chunk_running = 1
            _stage_observer(
                "before",
                TranslationPipelineStage.TRANSLATING_HY_MT2,
                {
                    "chapter_id": chapter_id,
                    "chunk_id": chunk_spec.chunk_id,
                    "chunk_count": chunk_count,
                    "chunk_completed": chunk_completed,
                    "chunk_running": chunk_running,
                },
            )
            glossary_contract = render_regulatory_translation_glossary_contract(
                chunk_spec.source_text
            )
            # V11: split chunk source into ordered semantic translation units
            # and translate with at most one deterministic corrective retry
            # naming the exact failing unit IDs/codes.  A second failure
            # blocks the chunk — no unbounded loop.
            chunk_units = split_source_into_units(chunk_spec.source_text)
            # Keep the model-facing logical unit stable and readable while
            # the repository-facing chunk_id remains fingerprint-versioned.
            # This also prevents storage identity details from leaking into
            # provider prompts and preserves span-addressable diagnostics.
            translation_unit_id = (
                chunk_spec.source_span_ids[0]
                if len(chunk_spec.source_span_ids) == 1
                else chunk_spec.chunk_id
            )
            try:
                hy_mt2_result, chunk_parsed = translate_units_with_bounded_correction(
                    self.chapter_pipeline.hy_mt2_translator,
                    units=chunk_units,
                    glossary=glossary_contract or item.glossary_version,
                    chapter_id=chapter_id,
                    chunk_id=translation_unit_id,
                    read_only_context=chunk_spec.adjacent_context or "",
                )
            except FidelityBlockedError as exc:
                # Second deterministic failure: stop and block the chapter.
                # The raw output is retained (markers stripped) for
                # diagnostics only; it is never admitted.
                hy_block_codes = list(exc.failure_codes)
                hy_block_text = strip_unit_markers(exc.last_output)
                hy_block_raw_text = strip_unit_markers(
                    exc.raw_provider_output
                )
                hy_block_chunk_id = chunk_spec.chunk_id
                chunk_failed += 1
                chunk_running = 0
                stage_ledger.append(
                    CompositePipelineRunStage(
                        stage="translating_hy_mt2_blocked",
                        model=HY_MT2_MODEL_ID,
                        prompt_version=HY_MT2_PROMPT_VERSION,
                        input_hash=_pipeline_sha256(chunk_spec.source_text),
                        output_hash=_pipeline_sha256(hy_block_text),
                    )
                )
                break
            # Reassemble aligned translation for downstream integration.
            aligned_chunk_text = reassemble_aligned_translation(
                chunk_units, chunk_parsed
            )
            # Malformed empty body fails closed.
            if not (aligned_chunk_text or "").strip():
                raise CompositePipelineUnavailableError(
                    f"Hy-MT2 returned empty translation for chunk {chunk_spec.chunk_id}"
                )
            stage_ledger.append(
                CompositePipelineRunStage(
                    stage="translating_hy_mt2",
                    model=hy_mt2_result.model,
                    prompt_version=hy_mt2_result.prompt_version,
                    input_hash=hy_mt2_result.input_hash,
                    output_hash=hy_mt2_result.output_hash,
                )
            )

            chunk_record = TranslationChunkRecord(
                chunk_id=chunk_spec.chunk_id,
                plan_id=plan.plan_id,
                project_id=item.project_id,
                artifact_id=artifact.artifact_id,
                chapter_id=chapter_id,
                chunk_order=chunk_spec.chunk_order,
                source_span_ids=list(chunk_spec.source_span_ids),
                source_text=chunk_spec.source_text,
                source_text_sha256=chunk_spec.source_text_sha256,
                adjacent_context_sha256=chunk_spec.adjacent_context_sha256,
                table_header_prefix=chunk_spec.table_header_prefix,
                chunk_fingerprint=chunk_spec.chunk_fingerprint,
                hy_mt2_model=hy_mt2_result.model,
                hy_mt2_prompt_version=hy_mt2_result.prompt_version,
                hy_mt2_input_hash=hy_mt2_result.input_hash,
                translated_text=aligned_chunk_text,
                translated_text_sha256=_pipeline_sha256(aligned_chunk_text),
                unit_targets={str(k): v for k, v in chunk_parsed.items()},
                translation_strategy=hy_mt2_result.translation_strategy,
                status="completed",
                created_at=self.clock(),
            )
            _guard()
            self.repository.save_translation_chunk(
                chunk_record,
                idempotency_key=(
                    f"chunk:{plan.plan_id}:{chunk_spec.chunk_id}:"
                    f"{chunk_spec.chunk_fingerprint[:16]}:"
                    f"{TRANSLATION_CONTRACT_FINGERPRINT[:12]}"
                ),
            )
            chunk_translations.append((chunk_spec, aligned_chunk_text))
            chunk_aligned.append((chunk_spec, chunk_units, chunk_parsed))
            chunk_completed += 1
            chunk_running = 0
            _stage_observer(
                "after",
                TranslationPipelineStage.TRANSLATING_HY_MT2,
                {
                    "chapter_id": chapter_id,
                    "chunk_id": chunk_spec.chunk_id,
                    "hy_mt2_model": hy_mt2_result.model,
                    "hy_mt2_prompt_version": hy_mt2_result.prompt_version,
                    "translation_strategy": hy_mt2_result.translation_strategy,
                    "translated_text_sha256": hy_mt2_result.translated_text_sha256,
                    "chunk_count": chunk_count,
                    "chunk_completed": chunk_completed,
                    "chunk_running": chunk_running,
                    "chunk_failed": chunk_failed,
                    "chunk_reused": chunk_reused,
                },
            )

        # -- Step 6: Flash integration (ordinary or windowed). -----------
        chapter_translated_text = "\n\n".join(
            translated for _, translated in chunk_translations
        )
        window_records: list[ChapterIntegrationWindow] = []
        window_texts: list[str] = []
        qc_failure_codes: list[str] = []
        qc_advisory_codes: list[str] = []
        flash_qc_model = FLASH_QC_MODEL
        flash_qc_prompt = FLASH_QC_PROMPT_VERSION
        flash_input_hash = ""
        flash_output_hash = ""
        final_envelope_input_hash = ""
        final_envelope_output_hash = ""
        flash_passed = True
        integration_executions: list[UpperLayerStageExecutionResult] = []
        # 0924V2 root-cause fix: the retry generation MUST flow into the
        # upper-layer request identity. Without it every recovery attempt
        # regenerated the same execution fingerprint and the shared executor
        # replayed the old failed run forever (26 items stuck as
        # failed_retryable across three recovery rounds).
        integration_owner = UpperLayerStageOwner(
            project_id=item.project_id,
            owner_type="translation_batch_item",
            owner_id=item.item_id,
            artifact_id=artifact.artifact_id,
            extraction_revision=span.extraction_revision,
            batch_id=item.batch_id,
            item_id=item.item_id,
            plan_id=plan.plan_id,
            chapter_id=chapter_id,
            retry_generation=int(
                getattr(item, "document_plan_retry_generation", 0) or 0
            ),
            retry_parent_stage_run_id=str(
                getattr(
                    item,
                    "document_plan_retry_parent_stage_run_id",
                    "",
                )
                or ""
            ),
        )

        if hy_block_codes:
            # Hy-stage second failure: chapter stops as fidelity-blocked
            # without calling Flash integration. Never expose the failed raw
            # provider output as the chapter translation: it may be truncated
            # or belong to a different source unit. Keep only already parsed,
            # span-bound chunk text in the diagnostic projection; the raw
            # failed output remains available exclusively in
            # blocked_raw_provider_output.
            integration_windowed = False
            flash_passed = False
            qc_failure_codes.extend(hy_block_codes)
            final_text = chapter_translated_text
            final_text_sha256 = _pipeline_sha256(final_text)
        else:
            windows = build_integration_windows(
                chunk_translations, input_limit=INTEGRATION_PROVIDER_INPUT_LIMIT
            )
            integration_windowed = len(windows) > 1

            _stage_observer(
                "before",
                TranslationPipelineStage.INTEGRATION_QC,
                {
                    "chapter_id": chapter_id,
                    "windowed": integration_windowed,
                    "chunk_count": chunk_count,
                    "chunk_completed": chunk_completed,
                    "chunk_running": 0,
                    "chunk_failed": chunk_failed,
                    "chunk_reused": chunk_reused,
                },
            )

            # Chapter-level aligned units: chunk units renumbered into one
            # ordered sequence with their Hy-MT2 draft targets.  Flash
            # integration/QC consumes the aligned marked envelope built from
            # these and must preserve the markers exactly; they are validated
            # deterministically and stripped only after validation.
            chapter_units: list[TranslationUnit] = []
            chapter_target_map: dict[int, str] = {}
            next_ordinal = 1
            for _cs, _units, _map in chunk_aligned:
                for _u in _units:
                    chapter_units.append(
                        TranslationUnit(ordinal=next_ordinal, text=_u.text)
                    )
                    chapter_target_map[next_ordinal] = _map.get(_u.ordinal, "")
                    next_ordinal += 1

        if hy_block_codes:
            pass  # Blocked above; Flash integration is skipped.
        elif not integration_windowed:
            # Ordinary chapter: one aligned Flash integration (plus at most
            # one bounded corrective pass inside the helper).
            integration, stage_execution = (
                self.chapter_pipeline.execute_integration_qc_stage(
                    units=chapter_units,
                    target_map=chapter_target_map,
                    owner=integration_owner,
                )
            )
            integration_executions.append(stage_execution)
            flash_qc = integration.qc_result
            if flash_qc is not None:
                flash_qc_model = flash_qc.qc_model
                flash_qc_prompt = flash_qc.qc_prompt_version
                flash_input_hash = flash_qc.qc_input_hash
                flash_output_hash = flash_qc.qc_output_hash
            flash_passed = integration.passed
            qc_failure_codes.extend(integration.failure_codes)
            qc_advisory_codes.extend(integration.diagnostic_codes)
            final_text = (
                integration.final_text if integration.passed
                else chapter_translated_text
            )
            final_text_sha256 = _pipeline_sha256(final_text)
            stage_ledger.append(
                CompositePipelineRunStage(
                    stage="integration_qc",
                    model=flash_qc_model,
                    prompt_version=flash_qc_prompt,
                    input_hash=flash_input_hash,
                    output_hash=flash_output_hash,
                )
            )
            if integration.fallback_used:
                stage_ledger.append(
                    CompositePipelineRunStage(
                        stage="integration_qc_hy_fallback",
                        model="deterministic",
                        prompt_version="aligned_hy_fidelity_fallback_v1",
                        input_hash=_payload_hash(chapter_target_map),
                        output_hash=final_text_sha256,
                    )
                )
        else:
            # Windowed path: one aligned Flash integration per ordered
            # window, followed only by deterministic concatenation. Window
            # lineage is persisted additively.
            aligned_by_chunk_id = {
                cs.chunk_id: (u, m) for cs, u, m in chunk_aligned
            }
            for w_idx, window in enumerate(windows, start=1):
                w_units: list[TranslationUnit] = []
                w_map: dict[int, str] = {}
                w_ordinal = 1
                for cs, _t in window:
                    u_list, m_map = aligned_by_chunk_id[cs.chunk_id]
                    for u in u_list:
                        w_units.append(TranslationUnit(ordinal=w_ordinal, text=u.text))
                        w_map[w_ordinal] = m_map.get(u.ordinal, "")
                        w_ordinal += 1
                w_integration, stage_execution = (
                    self.chapter_pipeline.execute_integration_qc_stage(
                        units=w_units,
                        target_map=w_map,
                        owner=integration_owner,
                    )
                )
                integration_executions.append(stage_execution)
                w_qc = w_integration.qc_result
                if w_qc is not None:
                    flash_qc_model = w_qc.qc_model
                    flash_qc_prompt = w_qc.qc_prompt_version
                if not w_integration.passed:
                    flash_passed = False
                    qc_failure_codes.extend(w_integration.failure_codes)
                    w_text = reassemble_aligned_translation(w_units, w_map)
                else:
                    w_text = w_integration.final_text
                qc_advisory_codes.extend(w_integration.diagnostic_codes)
                window_texts.append(w_text)
                window_records.append(
                    ChapterIntegrationWindow(
                        window_index=w_idx,
                        chunk_ids=[cs.chunk_id for cs, _ in window],
                        chunk_hashes=[cs.chunk_fingerprint for cs, _ in window],
                        input_hash=w_qc.qc_input_hash if w_qc else "",
                        output_hash=w_qc.qc_output_hash if w_qc else "",
                        integrated_text_sha256=_pipeline_sha256(w_text),
                    )
                )
                stage_ledger.append(
                    CompositePipelineRunStage(
                        stage=f"integration_qc_window_{w_idx}",
                        model=flash_qc_model,
                        prompt_version=flash_qc_prompt,
                        input_hash=w_qc.qc_input_hash if w_qc else "",
                        output_hash=w_qc.qc_output_hash if w_qc else "",
                    )
                )
                if w_integration.fallback_used:
                    stage_ledger.append(
                        CompositePipelineRunStage(
                            stage=f"integration_qc_window_{w_idx}_hy_fallback",
                            model="deterministic",
                            prompt_version="aligned_hy_fidelity_fallback_v1",
                            input_hash=_payload_hash(w_map),
                            output_hash=_pipeline_sha256(w_text),
                        )
                    )
            # Final chapter assembly is deterministic.  Every window has
            # already passed aligned Flash integration and per-unit fidelity;
            # sending the plain concatenated chapter through another
            # unconstrained model rewrite could reintroduce omissions while
            # exceeding the very input limit that required windowing.
            envelope_translated = "\n\n".join(window_texts)
            final_envelope_input_hash = _payload_hash(
                {
                    "translation_contract": TRANSLATION_CONTRACT_FINGERPRINT,
                    "assembly": "aligned_window_concat_v1",
                    "windows": [
                        {
                            "window_index": record.window_index,
                            "chunk_hashes": record.chunk_hashes,
                            "input_hash": record.input_hash,
                            "output_hash": record.output_hash,
                            "integrated_text_sha256": record.integrated_text_sha256,
                        }
                        for record in window_records
                    ],
                }
            )
            final_text = envelope_translated
            if not final_text.strip():
                raise CompositePipelineUnavailableError(
                    "windowed integration produced an empty final chapter"
                )
            final_text_sha256 = _pipeline_sha256(final_text)
            final_envelope_output_hash = final_text_sha256
            flash_input_hash = final_envelope_input_hash
            flash_output_hash = final_envelope_output_hash
            stage_ledger.append(
                CompositePipelineRunStage(
                    stage="integration_qc_final_assembly",
                    model="deterministic",
                    prompt_version="aligned_window_concat_v1",
                    input_hash=final_envelope_input_hash,
                    output_hash=final_envelope_output_hash,
                )
            )

        # Marker transport must never leak into the admitted chapter
        # candidate (table structure is preserved; only the alignment
        # markers are stripped).
        if contains_unit_markers(final_text):
            raise CompositePipelineUnavailableError(
                "translation-unit markers leaked into the integrated "
                "chapter candidate"
            )

        integration_stage_after_detail = {
            "qc_model": flash_qc_model,
            "qc_prompt_version": flash_qc_prompt,
            "qc_passed": flash_passed,
            "qc_failure_codes": list(dict.fromkeys(qc_failure_codes)),
            "qc_advisory_codes": list(
                dict.fromkeys(qc_advisory_codes)
            ),
            "integration_windowed": integration_windowed,
            "hy_fallback_used": any(
                stage.stage.endswith("_hy_fallback")
                for stage in stage_ledger
            ),
            "upper_layer_stage": (
                integration_executions[-1].stage
                if integration_executions
                else UPPER_LAYER_POST_HY_INTEGRATION_QC
            ),
            "upper_layer_stage_run_id": (
                (
                    integration_executions[-1].latest_stage_run_id
                    or integration_executions[-1].stage_run_id
                )
                if integration_executions
                else ""
            ),
            "upper_layer_parent_stage_run_id": (
                integration_executions[-1].parent_stage_run_id
                if integration_executions
                else ""
            ),
            "upper_layer_escalation_id": (
                integration_executions[-1].escalation_id
                if integration_executions
                else ""
            ),
            "upper_layer_status": (
                (
                    integration_executions[-1].latest_status
                    or integration_executions[-1].status
                )
                if integration_executions
                else (
                    "failed_terminal" if hy_block_codes else "succeeded"
                )
            ),
            "upper_layer_progress_label": (
                "增强分析未通过，已保留原译文供核对"
                if integration_executions
                and integration_executions[-1].latest_status
                in {"failed_retryable", "failed_terminal", "interrupted"}
                else "已使用增强分析完成译文核对"
                if integration_executions
                and integration_executions[-1].requested_model
                == PRO_UPPER_LAYER_MODEL
                else (
                    "译文忠实度校验未通过，请处理异常"
                    if hy_block_codes
                    else "译文结构与章节衔接核对完成"
                )
            ),
        }

        # A blocked Hy chunk only yields a diagnostic fragment, not a complete
        # chapter candidate.  Comparing that fragment with the full source
        # chapter creates misleading chapter-wide omission codes and obscures
        # the unit-level root cause.  Run the final deterministic gate only
        # after every chunk and the integration stage have completed.
        if hy_block_codes:
            fidelity_passed = False
            deterministic_failure_codes: list[str] = []
        else:
            deterministic_failure_codes = []
            for _chunk, units, target_map in chunk_aligned:
                deterministic_failure_codes.extend(
                    evaluate_translation_fidelity_aligned_units(
                        units,
                        target_map,
                    )
                )
            fidelity_passed = flash_passed and not deterministic_failure_codes

        merged_failure_codes: list[str] = []
        for code in list(qc_failure_codes) + deterministic_failure_codes:
            if code and code not in merged_failure_codes:
                merged_failure_codes.append(code)

        latest_integration_execution = (
            integration_executions[-1] if integration_executions else None
        )
        integration_contract_fingerprint = _payload_hash(
            {
                "translation_contract": TRANSLATION_CONTRACT_FINGERPRINT,
                "plan_id": plan.plan_id,
                "chapter_id": chapter_id,
                "stage": UPPER_LAYER_POST_HY_INTEGRATION_QC,
                "requested_model": (
                    latest_integration_execution.requested_model
                    if latest_integration_execution is not None
                    else ""
                ),
                "prompt_version": flash_qc_prompt,
                "input_hash": flash_input_hash,
            }
        )
        # DB UNIQUE(plan_id, chapter_id) — research single-span must not collide
        # when multiple batch items share a plan chapter. Include batch_id so a
        # force re-run can persist a new immutable row instead of ConflictError
        # against a prior batch's span-scoped integration.
        integration_chapter_id = (
            f"{chapter_id}::{item.span_id}::{item.batch_id}"
            if research_like
            else chapter_id
        )
        integration_id = "integration_" + _payload_hash(
            {
                "plan_id": plan.plan_id,
                "chapter_id": integration_chapter_id,
                "integration_contract": integration_contract_fingerprint,
                **(
                    {
                        "span_id": item.span_id,
                        "batch_id": item.batch_id,
                        "scope": "research_single_span",
                    }
                    if research_like
                    else {}
                ),
            }
        )[:24]
        chunk_ids = [cs.chunk_id for cs, _ in chunk_translations]
        chunk_hashes = [cs.chunk_fingerprint for cs, _ in chunk_translations]
        integration_result = ChapterIntegrationResult(
            integration_id=integration_id,
            plan_id=plan.plan_id,
            project_id=item.project_id,
            artifact_id=artifact.artifact_id,
            chapter_id=integration_chapter_id,
            chunk_ids=chunk_ids,
            chunk_hashes=chunk_hashes,
            integrated_chinese_text=final_text,
            integrated_text_sha256=final_text_sha256,
            flash_model=flash_qc_model,
            flash_prompt_version=flash_qc_prompt,
            flash_input_hash=flash_input_hash,
            flash_output_hash=flash_output_hash,
            fidelity_status="passed" if fidelity_passed else "blocked",
            fidelity_failure_codes=list(merged_failure_codes),
            fidelity_advisory_codes=list(dict.fromkeys(qc_advisory_codes)),
            blocked_raw_provider_output=hy_block_raw_text,
            blocked_raw_provider_output_sha256=(
                _pipeline_sha256(hy_block_raw_text)
                if hy_block_raw_text
                else ""
            ),
            integration_windowed=integration_windowed,
            integration_windows=window_records,
            final_envelope_input_hash=final_envelope_input_hash,
            final_envelope_output_hash=final_envelope_output_hash,
            translation_contract_fingerprint=TRANSLATION_CONTRACT_FINGERPRINT,
            integration_contract_fingerprint=integration_contract_fingerprint,
            upper_layer_stage_run_id=(
                latest_integration_execution.stage_run_id
                if latest_integration_execution is not None
                else ""
            ),
            status="completed",
            created_at=self.clock(),
        )
        _guard()
        integration_result = self.repository.save_chapter_integration_result(
            integration_result,
            idempotency_key=(
                f"integration:{plan.plan_id}:{integration_chapter_id}:"
                f"{integration_contract_fingerprint[:12]}"
            ),
        )
        # In a concurrent exact-contract run the repository may return the
        # first immutable integration committed for plan/chapter. All
        # downstream identities and text must reference that persisted result,
        # never an unpersisted local contender.
        integration_id = integration_result.integration_id
        chunk_ids = list(integration_result.chunk_ids)
        chunk_hashes = list(integration_result.chunk_hashes)
        final_text = integration_result.integrated_chinese_text
        merged_failure_codes = list(integration_result.fidelity_failure_codes)
        fidelity_passed = integration_result.fidelity_status == "passed"

        # Persist "after" only after the immutable output row exists.  If the
        # process dies after a provider response but before this point, the
        # transition call remains dispatched and restart fails closed instead
        # of issuing a duplicate call.
        if hy_block_chunk_id and item.downstream_contract_transition_id:
            _stage_observer(
                "after",
                TranslationPipelineStage.TRANSLATING_HY_MT2,
                {
                    "chapter_id": chapter_id,
                    "chunk_id": hy_block_chunk_id,
                    "hy_mt2_model": HY_MT2_MODEL_ID,
                    "hy_mt2_prompt_version": HY_MT2_PROMPT_VERSION,
                    "translated_text_sha256": (
                        integration_result.blocked_raw_provider_output_sha256
                    ),
                    "blocked": True,
                },
            )
        integration_stage_after_detail.update(
            {
                "chapter_id": chapter_id,
                "integrated_text_sha256": (
                    integration_result.integrated_text_sha256
                ),
                "model_call_skipped": bool(hy_block_codes),
            }
        )
        _stage_observer(
            "after",
            TranslationPipelineStage.INTEGRATION_QC,
            integration_stage_after_detail,
        )

        # -- Step 7: Immutable composite run ledger (real ai_run_id). ----
        run_chapter_id = (
            f"{chapter_id}::{item.span_id}::{item.batch_id}"
            if research_like
            else chapter_id
        )
        run_id = "composite_run_" + _payload_hash(
            {
                "plan_id": plan.plan_id,
                "chapter_id": run_chapter_id,
                "chunk_ids": chunk_ids,
                "chunk_hashes": chunk_hashes,
                "integration_id": integration_id,
                "stages": [s.model_dump(mode="json") for s in stage_ledger],
            }
        )[:28]
        composite_run = CompositePipelineRun(
            run_id=run_id,
            project_id=item.project_id,
            plan_id=plan.plan_id,
            chapter_id=run_chapter_id,
            artifact_id=artifact.artifact_id,
            stages=stage_ledger,
            status="completed",
            created_at=self.clock(),
        )
        _guard()
        self.repository.save_composite_pipeline_run(
            composite_run,
            idempotency_key=(
                f"composite_run:{plan.plan_id}:{run_chapter_id}:"
                f"{TRANSLATION_CONTRACT_FINGERPRINT[:12]}"
            ),
        )

        # -- Step 8: Exactly one chapter translation revision. -----------
        # Research single-span batches must key translations by span, otherwise
        # save_translation idempotency replays the prior chapter-level ZH and
        # fidelity compares the wrong target forever.
        translation_id = self._chapter_translation_id(
            item.project_id,
            plan.plan_id,
            chapter_id,
            integration_id=integration_id,
            span_id=item.span_id if research_like else "",
            batch_id=item.batch_id if research_like else "",
        )
        all_span_ids: list[str] = []
        for cs, _ in chunk_translations:
            all_span_ids.extend(cs.source_span_ids)
        # Primary span is the first assigned span of the chapter for FK compat;
        # research single-span path always binds the batch item's span.
        primary_span_id = (
            item.span_id
            if research_like
            else (all_span_ids[0] if all_span_ids else span.span_id)
        )
        revision_payload = WritingReferenceTranslationRevision(
            translation_id=translation_id,
            project_id=item.project_id,
            span_id=primary_span_id,
            source_span_revision=f"{primary_span_id}_r1",
            document_sha256=artifact.content_sha256,
            glossary_version=item.glossary_version,
            revision=1,
            translated_text=final_text,
            rationale=(
                f"document-plan/chunk: {plan.planner_model} plan, "
                f"{HY_MT2_MODEL_ID} body ({chunk_count} chunks), "
                f"{flash_qc_model} integration QC"
                + (" windowed" if integration_windowed else "")
            ),
            fidelity_status="passed" if fidelity_passed else "blocked",
            fidelity_failure_codes=list(merged_failure_codes),
            ai_run_id=run_id,
            task_type=COMPOSITE_TRANSLATION_TASK_TYPE,
            prompt_version=COMPOSITE_TRANSLATION_PROMPT_VERSION,
            schema_version=COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            provider="composite_pipeline",
            model_name=COMPOSITE_TRANSLATION_BODY_MODEL,
            contract_hash=COMPOSITE_TRANSLATION_CONTRACT_HASH,
            created_at=self.clock(),
            document_structure_plan_id=plan.plan_id,
            chapter_id=chapter_id,
            source_span_ids=list(dict.fromkeys(all_span_ids)),
            translation_chunk_ids=chunk_ids,
            chapter_integration_result_id=integration_id,
        )
        _guard()
        saved = self.repository.save_translation(
            revision_payload,
            idempotency_key=(
                f"chapter_translation:{plan.plan_id}:{chapter_id}:"
                f"{integration_id}:{item.span_id}:{item.batch_id}"
                if research_like
                else (
                    f"chapter_translation:{plan.plan_id}:{chapter_id}:"
                    f"{integration_id}"
                )
            ),
        )

        # Re-check ownership before the final item terminal-state write.
        _guard()

        self._finish_composite_item(
            item, saved, integration_result, plan,
            chapter_id, chapter_title, ocr_page_lineage,
            reused=False, actor=actor,
            upper_layer_execution=latest_integration_execution,
            chunk_count=chunk_count, chunk_completed=chunk_completed,
            chunk_failed=chunk_failed, chunk_reused=chunk_reused,
            span_count=source_span_count,
            document_total=document_total,
            document_index=document_index,
            document_label=document_label,
            chapter_total=chapter_total,
            chapter_index=chapter_index,
            chunk_running=chunk_running,
            cancel_check=cancel_check,
        )

    def _get_or_create_document_plan(
        self,
        item: WritingReferenceTranslationBatchItem,
        artifact: Any,
        span: Any,
        stage_observer: Callable[..., None],
    ) -> DocumentStructurePlan:
        """Get the existing plan for this artifact or create a new one.

        Flash planning runs exactly once per artifact/extraction/planner
        contract.  A retry reuses the immutable accepted plan.
        """
        # Never reuse a fingerprint-agnostic historical plan. The document
        # plan identity includes the downstream translation contract, so a
        # contract bump must reach a fresh immutable plan namespace.
        contract_fp = ""
        route_models: list[str] = []
        upper_executor = getattr(
            self.chapter_pipeline,
            "upper_layer_executor",
            None,
        )
        upper_service = getattr(upper_executor, "service", None)
        for candidate in (
            str(getattr(upper_service, "default_model", "") or ""),
            str(getattr(upper_service, "escalation_model", "") or ""),
            FLASH_PLANNING_MODEL,
            PRO_UPPER_LAYER_MODEL,
            SERVER_CONTRACT_MIGRATION_NAMESPACE,
            DOWNSTREAM_CONTRACT_PLAN_NAMESPACE,
            "deterministic_structure_fallback",
            "anchor_grouped_structure_fallback",
        ):
            if candidate and candidate not in route_models:
                route_models.append(candidate)
        # Fallback plans retain a suffix in their prompt identity so the
        # deterministic recovery is auditable.  Include those exact prompt
        # variants when a sibling item looks for an already persisted plan;
        # otherwise every item would re-invoke the planner after the first
        # semantic-recovery fallback.
        route_prompt_versions = (
            FLASH_PLANNING_PROMPT_VERSION,
            f"{FLASH_PLANNING_PROMPT_VERSION}:anchor_grouped_fallback_v2",
            f"{FLASH_PLANNING_PROMPT_VERSION}:deterministic_fallback_v1",
        )
        for existing_model in route_models:
            for prompt_version in route_prompt_versions:
                candidate_fp = _planner_contract_fingerprint(
                    artifact_id=artifact.artifact_id,
                    extraction_revision=span.extraction_revision,
                    planner_model=existing_model,
                    planner_prompt_version=prompt_version,
                    document_sha256=artifact.content_sha256,
                    translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
                )
                existing = self.repository.current_document_structure_plan(
                    item.project_id,
                    artifact.artifact_id,
                    span.extraction_revision,
                    candidate_fp,
                )
                if existing is not None:
                    return existing

        if (
            item.document_plan_contract_transition_kind == "migration"
            and item.document_plan_contract_target_fingerprint
        ):
            raise DocumentPlanValidationError(
                ("document_plan_contract_migration_missing",)
            )

        transition_source_item_id = (
            item.document_plan_contract_source_item_id
            if item.document_plan_contract_transition_kind
            == "supersession"
            else ""
        )
        if (
            (
                item.document_plan_retry_generation > 0
                and item.document_plan_retry_source_item_id
                and item.item_id
                != item.document_plan_retry_source_item_id
            )
            or (
                transition_source_item_id
                and item.item_id != transition_source_item_id
            )
        ):
            raise DocumentPlanValidationError(
                ("document_plan_retry_source_not_recovered",),
                source_stage_run_id=(
                    item.document_plan_retry_parent_stage_run_id
                    or item.document_plan_contract_source_stage_run_id
                ),
                latest_stage_run_id=(
                    item.document_plan_retry_parent_stage_run_id
                    or item.document_plan_contract_source_stage_run_id
                ),
                derived_from_source_failure=True,
            )

        # Get all source spans for the artifact.
        all_spans = self.repository.source_spans(
            item.project_id,
            artifact.artifact_id,
            extraction_revision=span.extraction_revision,
        )
        all_spans_tuple = tuple(all_spans)

        # Run Flash planning once for the whole document.
        stage_observer(
            "before", TranslationPipelineStage.TOC_PLANNING,
            artifact_id=artifact.artifact_id,
        )
        planner_fallback_codes: list[str] = []
        plan_execution: UpperLayerStageExecutionResult | None = None
        fallback_stage_run_id = ""
        flash_plan = None
        base_document_context = {
            "artifact_id": artifact.artifact_id,
            "document_type": artifact.document_type,
            "document_sha256": artifact.content_sha256,
            "extraction_revision": span.extraction_revision,
            "span_count": len(all_spans_tuple),
        }
        try:
            doc_text, document_context = build_document_planner_input(
                all_spans_tuple,
                document_context=base_document_context,
            )
        except DocumentPlanValidationError as manifest_exc:
            # Oversized CT.gov protocols exceed the Flash planner manifest
            # budget — skip Flash and build an anchor-grouped plan from
            # extracted M11 segments so translation can still run.
            planner_fallback_codes = [
                "planner_manifest_exceeds_bounded_contract",
                *list(manifest_exc.codes),
            ]
            segments = build_document_planner_segments(all_spans_tuple)
            document_context = {
                **base_document_context,
                "_planner_segments": segments,
                "segment_count": len(segments),
            }
            doc_text = _pipeline_sha256(
                json.dumps(
                    {
                        "artifact_id": artifact.artifact_id,
                        "extraction_revision": span.extraction_revision,
                        "segment_count": len(segments),
                        "fallback": "anchor_grouped",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            flash_plan = build_anchor_grouped_document_plan_fallback(
                segments,
                document_type=artifact.document_type,
                plan_input_hash=doc_text,
            )
        plan_owner = UpperLayerStageOwner(
            project_id=item.project_id,
            owner_type="translation_batch_item",
            owner_id=item.item_id,
            artifact_id=artifact.artifact_id,
            extraction_revision=span.extraction_revision,
            batch_id=item.batch_id,
            item_id=item.item_id,
            retry_generation=(
                item.document_plan_retry_generation
                if item.item_id == item.document_plan_retry_source_item_id
                else 0
            ),
            retry_parent_stage_run_id=(
                item.document_plan_retry_parent_stage_run_id
                if item.item_id == item.document_plan_retry_source_item_id
                else ""
            ),
            contract_supersession_generation=(
                item.document_plan_contract_generation
                if (
                    item.document_plan_contract_transition_kind
                    == "supersession"
                    and item.item_id
                    == item.document_plan_contract_source_item_id
                )
                else 0
            ),
            contract_supersession_transition_version=(
                item.document_plan_contract_transition_version
                if (
                    item.document_plan_contract_transition_kind
                    == "supersession"
                    and item.item_id
                    == item.document_plan_contract_source_item_id
                )
                else ""
            ),
            contract_supersession_source_stage_run_id=(
                item.document_plan_contract_source_stage_run_id
                if (
                    item.document_plan_contract_transition_kind
                    == "supersession"
                    and item.item_id
                    == item.document_plan_contract_source_item_id
                )
                else ""
            ),
            contract_supersession_source_execution_fingerprint=(
                item.document_plan_contract_source_execution_fingerprint
                if (
                    item.document_plan_contract_transition_kind
                    == "supersession"
                    and item.item_id
                    == item.document_plan_contract_source_item_id
                )
                else ""
            ),
            contract_supersession_source_prompt_version=(
                item.document_plan_contract_source_prompt_version
                if (
                    item.document_plan_contract_transition_kind
                    == "supersession"
                    and item.item_id
                    == item.document_plan_contract_source_item_id
                )
                else ""
            ),
            contract_supersession_target_prompt_version=(
                item.document_plan_contract_target_prompt_version
                if (
                    item.document_plan_contract_transition_kind
                    == "supersession"
                    and item.item_id
                    == item.document_plan_contract_source_item_id
                )
                else ""
            ),
        )
        if flash_plan is None:
            try:
                flash_plan, plan_execution = (
                    self.chapter_pipeline.execute_document_planning_stage(
                        doc_text,
                        document_context,
                        owner=plan_owner,
                        bounded_structural_retry=True,
                    )
                )
            except DocumentPlanValidationError as exc:
                structural_error = DocumentPlanValidationError(
                    (
                        "flash_planner_structural_failure",
                        *tuple(exc.codes),
                    ),
                    source_stage_run_id=exc.source_stage_run_id,
                    latest_stage_run_id=exc.latest_stage_run_id,
                )
                if not _is_structural_planner_failure(structural_error):
                    raise structural_error from exc
                # The upper-layer service has already persisted its
                # immutable failed attempts.  Recover only the structural
                # contract failure from the same frozen source segments;
                # never turn a provider/runtime error into a fake success.
                planner_fallback_codes = [
                    "planner_structural_retry_exhausted",
                    *list(structural_error.codes),
                ]
                fallback_stage_run_id = (
                    structural_error.latest_stage_run_id
                    or structural_error.source_stage_run_id
                )
                try:
                    flash_plan = self._recover_document_plan_fallback(
                        document_context=document_context,
                        document_type=artifact.document_type,
                        plan_input_hash=doc_text,
                        planner_fallback_codes=planner_fallback_codes,
                    )
                except DocumentPlanValidationError as fallback_exc:
                    raise DocumentPlanValidationError(
                        (
                            *planner_fallback_codes,
                            *tuple(fallback_exc.codes),
                        ),
                        source_stage_run_id=structural_error.source_stage_run_id,
                        latest_stage_run_id=structural_error.latest_stage_run_id,
                    ) from fallback_exc
            except Exception as exc:
                raise DocumentPlanValidationError(
                    (
                        "flash_planner_runtime_failure",
                        f"planner_error_{type(exc).__name__}",
                    )
                ) from exc
        if not flash_plan.chapters or not flash_plan.document_role:
            raise DocumentPlanValidationError(("malformed_planner_output",))

        # Structural coverage is necessary but not sufficient: a planner can
        # legally cover every span while collapsing unrelated M11 anchors into
        # one chapter.  That makes the later document-plan anchor gate discard
        # valid research spans.  Replace only this semantically misaligned plan
        # with the deterministic, source-ordered fallback; all AI/planner rows
        # remain immutable audit evidence.
        semantic_alignment_codes = _document_plan_semantic_alignment_codes(
            flash_plan.chapters,
            all_spans_tuple,
        )
        if semantic_alignment_codes:
            planner_fallback_codes.extend(
                [
                    "planner_semantic_alignment_failure",
                    *semantic_alignment_codes,
                ]
            )
            segments = document_context.get("_planner_segments")
            if not segments:
                segments = build_document_planner_segments(all_spans_tuple)
            flash_plan = build_anchor_grouped_document_plan_fallback(
                segments,
                document_type=artifact.document_type,
                plan_input_hash=doc_text,
            )
        stage_observer(
            "after", TranslationPipelineStage.TOC_PLANNING,
            plan_model=flash_plan.plan_model,
            plan_prompt_version=flash_plan.plan_prompt_version,
            upper_layer_stage=(
                plan_execution.stage
                if plan_execution is not None
                else UPPER_LAYER_DOCUMENT_PLANNING
            ),
            upper_layer_stage_run_id=(
                (
                    plan_execution.latest_stage_run_id
                    or plan_execution.stage_run_id
                )
                if plan_execution is not None
                else fallback_stage_run_id
            ),
            upper_layer_parent_stage_run_id=(
                plan_execution.parent_stage_run_id
                if plan_execution is not None
                else ""
            ),
            upper_layer_escalation_id=(
                plan_execution.escalation_id if plan_execution is not None else ""
            ),
            upper_layer_status=(
                (
                    plan_execution.latest_status
                    or plan_execution.status
                )
                if plan_execution is not None
                else "completed_degraded"
            ),
            upper_layer_progress_label=(
                "增强分析未通过，已保留可用的章节结构"
                if plan_execution is not None
                and plan_execution.latest_status
                in {"failed_retryable", "failed_terminal", "interrupted"}
                else "已使用增强分析完成章节结构识别"
                if plan_execution is not None
                and plan_execution.requested_model == PRO_UPPER_LAYER_MODEL
                else (
                    "已通过确定性结构规则完成章节识别"
                    if planner_fallback_codes
                    else "章节结构识别完成"
                )
            ),
        )

        # Validate the plan.
        plan_request = DocumentPlanRequest(
            artifact_id=artifact.artifact_id,
            extraction_revision=span.extraction_revision,
            document_sha256=artifact.content_sha256,
            source_spans=all_spans_tuple,
        )
        validated = validate_document_plan(flash_plan, plan_request)
        if planner_fallback_codes:
            validated = type(validated)(
                flash_plan=validated.flash_plan,
                chapters=validated.chapters,
                document_role=validated.document_role,
                ambiguity_codes=tuple(dict.fromkeys(planner_fallback_codes)),
            )

        contract_fp = _planner_contract_fingerprint(
            artifact_id=artifact.artifact_id,
            extraction_revision=span.extraction_revision,
            planner_model=flash_plan.plan_model,
            planner_prompt_version=flash_plan.plan_prompt_version,
            document_sha256=artifact.content_sha256,
            translation_contract=TRANSLATION_CONTRACT_FINGERPRINT,
        )

        # Build and persist the plan.
        plan_id = "docplan_" + _payload_hash(
            {
                "artifact_id": artifact.artifact_id,
                "extraction_revision": span.extraction_revision,
                "contract_fp": contract_fp,
            }
        )[:24]
        chapters = [
            DocumentStructurePlanChapter(
                chapter_id=ch_id,
                chapter_order=idx + 1,
                title=ch_title,
                heading_path=[],
                ich_m11_anchor=ch_anchor,
                source_span_ids=list(ch_span_ids),
                ambiguity_codes=[],
            )
            for idx, (ch_id, ch_title, ch_anchor, ch_span_ids) in enumerate(
                validated.chapters
            )
        ]
        plan = DocumentStructurePlan(
            plan_id=plan_id,
            project_id=item.project_id,
            artifact_id=artifact.artifact_id,
            extraction_revision=span.extraction_revision,
            document_sha256=artifact.content_sha256,
            document_role=validated.document_role,
            planner_model=flash_plan.plan_model,
            planner_prompt_version=flash_plan.plan_prompt_version,
            planner_input_hash=flash_plan.plan_input_hash,
            planner_output_hash=flash_plan.plan_output_hash,
            planner_contract_fingerprint=contract_fp,
            chapters=chapters,
            ambiguity_codes=list(validated.ambiguity_codes),
            status="active",
            created_at=self.clock(),
            planner_provider=(
                plan_execution.provider if plan_execution is not None else ""
            ),
            planner_transport=(
                plan_execution.transport if plan_execution is not None else ""
            ),
            planner_deployment_profile=(
                plan_execution.deployment_profile
                if plan_execution is not None
                else ""
            ),
            planner_response_model=(
                plan_execution.response_model if plan_execution is not None else ""
            ),
            upper_layer_stage_run_id=(
                plan_execution.stage_run_id
                if plan_execution is not None
                else fallback_stage_run_id
            ),
        )
        try:
            return self.repository.save_document_structure_plan(
                plan,
                idempotency_key=(
                    f"docplan:{artifact.artifact_id}:{span.extraction_revision}:{contract_fp}"
                ),
            )
        except Exception as exc:
            # Concurrent/retry rebuilds can collide on the same idempotency key
            # with a different created_at in the payload. Reuse only the plan
            # produced under this exact planner/translation contract.
            from .writing_reference_repository import WritingReferenceConflictError

            if not isinstance(exc, WritingReferenceConflictError):
                raise
            reused = self.repository.current_document_structure_plan(
                item.project_id,
                artifact.artifact_id,
                span.extraction_revision,
                contract_fp,
            )
            if reused is None:
                raise
            return reused

    @staticmethod
    def _resolve_chapter_for_span(
        plan: DocumentStructurePlan, span_id: str
    ) -> str:
        """Determine which chapter a span belongs to in the plan.

        Fail closed when the span is not a member of any chapter — never
        fall back to the first chapter.
        """
        for ch in plan.chapters:
            if span_id in ch.source_span_ids:
                return ch.chapter_id
        raise DocumentPlanValidationError((f"span_{span_id}_unassigned",))

    @staticmethod
    def _chapter_title(
        plan: DocumentStructurePlan, chapter_id: str
    ) -> str:
        for ch in plan.chapters:
            if ch.chapter_id == chapter_id:
                return ch.title or ch.chapter_id
        return chapter_id

    @staticmethod
    def _chapter_index(
        plan: DocumentStructurePlan, chapter_id: str
    ) -> int:
        for idx, ch in enumerate(plan.chapters, start=1):
            if ch.chapter_id == chapter_id:
                return idx
        return 0

    def _link_item_to_chapter_revision(
        self,
        item: WritingReferenceTranslationBatchItem,
        artifact: Any,
        span: Any,
        plan: DocumentStructurePlan,
        chapter_id: str,
        chapter_title: str,
        integration: ChapterIntegrationResult,
        ocr_page_lineage: Any,
        *,
        research_like: bool = False,
    ) -> WritingReferenceTranslationRevision:
        """Link an item to the existing single chapter revision (no new ID).

        Exactly one ``WritingReferenceTranslationRevision`` exists per
        plan/chapter/contract.  Later span items only project that same
        translation_id/revision onto the batch item.
        """
        translation_id = self._chapter_translation_id(
            item.project_id,
            plan.plan_id,
            chapter_id,
            integration_id=integration.integration_id,
            span_id=item.span_id if research_like else "",
            batch_id=item.batch_id if research_like else "",
        )
        existing = self.repository.current_translation_by_id(
            item.project_id, translation_id
        )
        if existing is not None:
            return existing
        # Should not happen if the first item created the revision, but keep
        # a fail-closed recreate path using the chapter identity.
        primary_span_id = span.span_id
        # Prefer the primary span stored on any chunk membership.
        chapter = next(
            (ch for ch in plan.chapters if ch.chapter_id == chapter_id),
            None,
        )
        if chapter and chapter.source_span_ids and not research_like:
            primary_span_id = chapter.source_span_ids[0]
        run_chapter_id = (
            f"{chapter_id}::{item.span_id}::{item.batch_id}"
            if research_like
            else chapter_id
        )
        with self.repository._connect() as connection:
            run_row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_composite_pipeline_runs
                WHERE tenant_id=? AND project_id=? AND plan_id=?
                  AND chapter_id=?
                ORDER BY created_at DESC, run_id DESC
                LIMIT 1
                """,
                (
                    TENANT_ID,
                    item.project_id,
                    plan.plan_id,
                    run_chapter_id,
                ),
            ).fetchone()
        if run_row is not None:
            run_id = CompositePipelineRun.model_validate_json(
                run_row["payload_json"]
            ).run_id
        else:
            persisted_chunks = {
                chunk.chunk_id: chunk
                for chunk in self.repository.translation_chunks_for_plan(
                    item.project_id,
                    plan.plan_id,
                )
            }
            recovery_stages = [
                CompositePipelineRunStage(
                    stage="toc_planning_reused",
                    model=plan.planner_model,
                    prompt_version=plan.planner_prompt_version,
                    input_hash=plan.planner_input_hash,
                    output_hash=plan.planner_output_hash,
                )
            ]
            for chunk_id in integration.chunk_ids:
                chunk = persisted_chunks.get(chunk_id)
                if chunk is None:
                    raise CompositePipelineUnavailableError(
                        "persisted integration references a missing translation chunk"
                    )
                recovery_stages.append(
                    CompositePipelineRunStage(
                        stage="translating_hy_mt2_reused",
                        model=chunk.hy_mt2_model,
                        prompt_version=chunk.hy_mt2_prompt_version,
                        input_hash=chunk.hy_mt2_input_hash,
                        output_hash=chunk.translated_text_sha256,
                    )
                )
            if (
                not integration.chunk_ids
                and integration.blocked_raw_provider_output_sha256
            ):
                recovery_stages.append(
                    CompositePipelineRunStage(
                        stage="translating_hy_mt2_blocked_reused",
                        model=HY_MT2_MODEL_ID,
                        prompt_version=HY_MT2_PROMPT_VERSION,
                        input_hash="",
                        output_hash=(
                            integration.blocked_raw_provider_output_sha256
                        ),
                    )
                )
            recovery_stages.append(
                CompositePipelineRunStage(
                    stage="integration_qc_reused",
                    model=integration.flash_model,
                    prompt_version=integration.flash_prompt_version,
                    input_hash=integration.flash_input_hash,
                    output_hash=integration.flash_output_hash,
                )
            )
            run_id = "composite_run_" + _payload_hash(
                {
                    "plan_id": plan.plan_id,
                    "chapter_id": run_chapter_id,
                    "integration_id": integration.integration_id,
                    "stages": [
                        stage.model_dump(mode="json")
                        for stage in recovery_stages
                    ],
                    "recovery": "persisted_current_contract_rows",
                }
            )[:28]
            self.repository.save_composite_pipeline_run(
                CompositePipelineRun(
                    run_id=run_id,
                    project_id=item.project_id,
                    plan_id=plan.plan_id,
                    chapter_id=run_chapter_id,
                    artifact_id=artifact.artifact_id,
                    stages=recovery_stages,
                    status="completed",
                    created_at=self.clock(),
                ),
                idempotency_key=(
                    f"composite_run_recovery:{plan.plan_id}:"
                    f"{run_chapter_id}:{integration.integration_id}"
                ),
            )
        revision_payload = WritingReferenceTranslationRevision(
            translation_id=translation_id,
            project_id=item.project_id,
            span_id=primary_span_id,
            source_span_revision=f"{primary_span_id}_r1",
            document_sha256=artifact.content_sha256,
            glossary_version=item.glossary_version,
            revision=1,
            translated_text=integration.integrated_chinese_text,
            rationale=(
                f"document-plan/chunk reuse: chapter {chapter_id} "
                f"integration {integration.integration_id}"
            ),
            fidelity_status=integration.fidelity_status,
            fidelity_failure_codes=list(integration.fidelity_failure_codes),
            ai_run_id=run_id,
            task_type=COMPOSITE_TRANSLATION_TASK_TYPE,
            prompt_version=COMPOSITE_TRANSLATION_PROMPT_VERSION,
            schema_version=COMPOSITE_TRANSLATION_SCHEMA_VERSION,
            provider="composite_pipeline",
            model_name=COMPOSITE_TRANSLATION_BODY_MODEL,
            contract_hash=COMPOSITE_TRANSLATION_CONTRACT_HASH,
            created_at=self.clock(),
            document_structure_plan_id=plan.plan_id,
            chapter_id=chapter_id,
            source_span_ids=(
                [item.span_id]
                if research_like
                else list(chapter.source_span_ids)
                if chapter
                else [span.span_id]
            ),
            translation_chunk_ids=list(integration.chunk_ids),
            chapter_integration_result_id=integration.integration_id,
        )
        return self.repository.save_translation(
            revision_payload,
            idempotency_key=(
                f"chapter_translation:{plan.plan_id}:{chapter_id}:"
                f"{integration.integration_id}:{item.span_id}:{item.batch_id}"
                if research_like
                else (
                    f"chapter_translation:{plan.plan_id}:{chapter_id}:"
                    f"{integration.integration_id}"
                )
            ),
        )

    @staticmethod
    def _chapter_matches_anchor_filter(
        plan: DocumentStructurePlan,
        chapter_id: str,
        anchor_filter: list[str],
    ) -> bool:
        chapter = next(
            (entry for entry in plan.chapters if entry.chapter_id == chapter_id),
            None,
        )
        if chapter is None:
            return False
        folded = " ".join((chapter.title or "").casefold().split())
        title_anchors: set[str] = set()
        if any(
            token in folded
            for token in (
                "trial population",
                "study population",
                "subject eligibility",
                "eligibility criteria",
                "inclusion criteria",
                "exclusion criteria",
                "subject selection",
                "patient selection",
                "selection of subjects",
                "selection of patients",
                "inclusion and exclusion",
            )
        ):
            title_anchors.add("eligibility")
        if any(
            token in folded for token in ("objective", "endpoint", "estimand")
        ):
            title_anchors.add("objectives_endpoints")
        if any(
            token in folded
            for token in (
                "safety reporting",
                "safety assessment",
                "adverse event",
                " ae,",
                "sae",
                "adverse experience",
                "safety evaluation",
            )
        ):
            title_anchors.add("safety")
        if any(
            token in folded
            for token in (
                "schedule of",
                "study assessments",
                "study assessment",
                "study procedures",
                "study procedure",
                "visit schedule",
                "schedule of activities",
                "schedule of assessments",
                "time and events schedule",
                "time and event schedule",
            )
        ):
            title_anchors.add("schedule")
        if any(token in folded for token in ("statistical", "statistics")):
            title_anchors.add("statistics")
        if any(token in folded for token in ("synopsis", "protocol summary")):
            title_anchors.add("synopsis")

        requested = set(anchor_filter)
        if title_anchors:
            return bool(title_anchors & requested)
        if re.match(r"^\d{1,2}(?:\s|[.:])", folded):
            return False
        return chapter.ich_m11_anchor in requested

    def _exclude_claim_after_document_plan(
        self,
        item: WritingReferenceTranslationBatchItem,
        plan: DocumentStructurePlan,
        *,
        chapter_id: str,
        chapter_title: str,
        chapter_index: int,
        chapter_total: int,
        source_span_count: int,
        document_total: int,
        document_index: int,
        document_label: str,
        actor: str,
        cancel_check: Callable[[], bool] | None = None,
        exclude_reason: str = "document_plan_anchor_filter",
    ) -> None:
        excluded = item.model_copy(
            update={
                "generation_status": "excluded",
                "pipeline_stage": "excluded",
                "pipeline_stage_detail": exclude_reason,
                "document_structure_plan_id": plan.plan_id,
                "document_total": document_total,
                "document_index": document_index,
                "document_label": document_label or item.filename,
                "chapter_id": chapter_id,
                "chapter_title": chapter_title,
                "chapter_total": chapter_total,
                "chapter_index": chapter_index,
                "source_span_count": source_span_count,
                "error_code": "",
                "error_detail": "",
                "blocker_kind": "",
                "blocker_message": "",
                "updated_at": self.clock(),
            },
            deep=True,
        )
        self._finish_claim(item, excluded, actor, cancel_check=cancel_check)

    @staticmethod
    def _looks_like_abbreviation_glossary(source_text: str) -> bool:
        """True when the span is mostly ``ABBR = definition`` glossary lines.

        Also treats hybrid ``Abbreviations: …`` walls that prepend a long
        COVID/visit narrative — those poison research single-span Hy-MT2.
        """
        text = (source_text or "").strip()
        if len(text) < 400:
            return False
        head = text[:1200]
        equals_head = len(re.findall(r"\b[A-Z][A-Za-z0-9+\-/]*\s*=\s*", head))
        if re.match(r"(?i)^abbreviations?\s*:", text) and equals_head >= 6:
            return True
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) < 6:
            equals = len(re.findall(r"\b[A-Z][A-Za-z0-9+\-/]*\s*=\s*", text))
            return equals >= 8 and equals * 40 >= len(text)
        def_lines = 0
        for line in lines:
            if re.match(
                r"^(?:Abbreviations?\s*:)?\s*[A-Z][A-Za-z0-9+\-/]*\s*=\s+\S",
                line,
            ):
                def_lines += 1
            elif " = " in line and re.search(r"\b[A-Z]{2,}\b", line):
                def_lines += 1
        return def_lines >= max(6, int(0.5 * len(lines)))

    def _finish_composite_item(
        self,
        item: WritingReferenceTranslationBatchItem,
        saved: WritingReferenceTranslationRevision,
        integration: ChapterIntegrationResult,
        plan: DocumentStructurePlan,
        chapter_id: str,
        chapter_title: str,
        ocr_page_lineage: Any,
        *,
        reused: bool,
        actor: str,
        upper_layer_execution: UpperLayerStageExecutionResult | None = None,
        chunk_count: int = 0,
        chunk_completed: int = 0,
        chunk_failed: int = 0,
        chunk_reused: int = 0,
        span_count: int = 0,
        document_total: int = 0,
        document_index: int = 0,
        document_label: str = "",
        chapter_total: int = 0,
        chapter_index: int = 0,
        chunk_running: int = 0,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        """Finish a composite pipeline item with chapter/chunk progress."""
        persisted_chunks = {
            chunk.chunk_id: chunk
            for chunk in self.repository.translation_chunks_for_plan(
                item.project_id,
                plan.plan_id,
            )
        }
        body_models = {
            persisted_chunks[chunk_id].hy_mt2_model
            for chunk_id in integration.chunk_ids
            if chunk_id in persisted_chunks
            and persisted_chunks[chunk_id].hy_mt2_model
        }
        if len(body_models) > 1:
            raise CompositePipelineUnavailableError(
                "one chapter integration cannot mix body-translation models"
            )
        body_model = next(iter(body_models), HY_MT2_MODEL_ID)
        ocr_lineage_json_list = [
            {
                "page": p.physical_page,
                "dpi": p.dpi,
                "model": p.model,
                "profile_digest": p.ocr_profile_digest,
                "text_sha256": p.source_text_sha256,
                "channel": p.channel,
            }
            for p in ocr_page_lineage
        ]
        status = (
            "candidate_ready"
            if integration.fidelity_status == "passed"
            else "fidelity_blocked"
        )
        blocker_kind = ""
        blocker_message = ""
        if status == "fidelity_blocked":
            blocker_kind = "terminal"
            blocker_message = (
                "忠实度校验未通过，请核对原文数字、单位、否定关系或时间窗后处理。"
            )
        completed = item.model_copy(
            update={
                "generation_status": status,
                "pipeline_stage": status,
                "pipeline_stage_detail": (
                    "翻译完成，可核对并使用"
                    if status == "candidate_ready"
                    else "译文忠实度校验未通过，请处理异常"
                ),
                "ocr_lineage_json": (
                    _canonical_json(ocr_lineage_json_list) if ocr_lineage_json_list else ""
                ),
                "flash_plan_model": plan.planner_model,
                "flash_plan_prompt_version": plan.planner_prompt_version,
                "plan_model": plan.planner_model,
                "hy_mt2_model": body_model,
                "hy_mt2_prompt_version": HY_MT2_PROMPT_VERSION,
                "flash_qc_model": integration.flash_model,
                "flash_qc_prompt_version": integration.flash_prompt_version,
                "qc_model": integration.flash_model,
                "active_upper_layer_stage": "",
                "active_upper_layer_stage_run_id": "",
                "latest_upper_layer_stage_run_id": (
                    (
                        upper_layer_execution.latest_stage_run_id
                        or upper_layer_execution.stage_run_id
                    )
                    if upper_layer_execution is not None
                    else (
                        integration.upper_layer_stage_run_id
                        or plan.upper_layer_stage_run_id
                    )
                ),
                "upper_layer_escalation_id": (
                    upper_layer_execution.escalation_id
                    if upper_layer_execution is not None
                    else ""
                ),
                "upper_layer_escalation_status": (
                    (
                        "completed"
                        if (
                            upper_layer_execution.latest_status
                            or upper_layer_execution.status
                        )
                        in {"succeeded", "completed_degraded"}
                        else (
                            "failed_retryable"
                            if (
                                upper_layer_execution.latest_status
                                or upper_layer_execution.status
                            )
                            == "failed_retryable"
                            else "failed_terminal"
                        )
                    )
                    if upper_layer_execution is not None
                    and upper_layer_execution.escalation_id
                    else ""
                ),
                "pipeline_fingerprint": integration.integrated_text_sha256,
                "translation_id": saved.translation_id,
                "translation_revision": saved.revision,
                "ai_run_id": saved.ai_run_id,
                "contract_hash": saved.contract_hash,
                "prompt_version": saved.prompt_version,
                "schema_version": saved.schema_version,
                "fidelity_status": saved.fidelity_status,
                "fidelity_failure_codes": list(saved.fidelity_failure_codes),
                "error_code": "",
                "error_detail": "",
                # Document/chapter/chunk progress (Round 8).
                "document_structure_plan_id": plan.plan_id,
                "document_total": document_total,
                "document_index": document_index,
                "document_label": document_label or item.filename,
                "chapter_id": chapter_id,
                "chapter_title": chapter_title,
                "chapter_total": chapter_total or len(plan.chapters),
                "chapter_index": chapter_index,
                "chunk_count": chunk_count or len(integration.chunk_ids),
                "chunk_completed": chunk_completed or len(integration.chunk_ids),
                "chunk_running": chunk_running,
                "chunk_failed": chunk_failed,
                "chunk_reused": chunk_reused,
                "source_span_count": span_count,
                "blocker_kind": blocker_kind,
                "blocker_message": blocker_message,
                "updated_at": self.clock(),
            },
            deep=True,
        )
        self._finish_claim(item, completed, actor, cancel_check=cancel_check)


    def _recover_document_plan_fallback(
        self,
        *,
        document_context: dict[str, Any],
        document_type: str,
        plan_input_hash: str,
        planner_fallback_codes: list[str] | None = None,
    ):
        """Deterministic plan recovery when Flash planning is unavailable."""
        segments = document_context.get("_planner_segments")
        if not segments:
            source_spans = document_context.get("source_spans") or ()
            if source_spans:
                segments = build_document_planner_segments(tuple(source_spans))
        if segments:
            try:
                return build_anchor_grouped_document_plan_fallback(
                    segments,
                    document_type=document_type,
                    plan_input_hash=plan_input_hash,
                )
            except DocumentPlanValidationError:
                pass
        # Last resort: TOC-style deterministic fallback from segments if any.
        if segments:
            return build_deterministic_document_plan_fallback(
                segments,
                document_type=document_type,
                plan_input_hash=plan_input_hash,
            )
        raise DocumentPlanValidationError(
            tuple(planner_fallback_codes or ("planner_fallback_unavailable",))
        )

    @staticmethod
    def _chapter_translation_id(
        project_id: str,
        plan_id: str,
        chapter_id: str,
        *,
        integration_id: str = "",
        span_id: str = "",
        batch_id: str = "",
    ) -> str:
        """Deterministic translation_id for a chapter (or research span).

        Default identity: project + plan + chapter + translation contract.
        Research single-span batches pass ``span_id`` (and ``batch_id`` on
        force re-runs) so each batch item gets its own revision and does not
        replay a prior chapter-level or prior-batch ZH.
        """
        payload = {
            "project_id": project_id,
            "plan_id": plan_id,
            "chapter_id": chapter_id,
            "contract_hash": COMPOSITE_TRANSLATION_CONTRACT_HASH,
        }
        if integration_id:
            payload["integration_id"] = integration_id
        if span_id:
            payload["span_id"] = span_id
            payload["scope"] = "research_single_span"
        if batch_id:
            payload["batch_id"] = batch_id
        return "wref_translation_ch_" + _payload_hash(payload)[:24]

    @staticmethod
    def _batch_translation_id(item: WritingReferenceTranslationBatchItem) -> str:
        """Legacy span-keyed ID — retained only for non-composite paths.

        Composite chapter revisions must use ``_chapter_translation_id``.
        """
        return "wref_translation_batch_" + _payload_hash(
            {"batch_id": item.batch_id, "span_id": item.span_id}
        )[:24]

    def _lookup_ocr_lineage(self, item: WritingReferenceTranslationBatchItem):
        """Retrieve OCR page lineage from the extraction result.

        OCR lineage originates at extraction and travels through the
        extraction result's ``ocr_recovery_pages`` field.  We look up the
        extraction for the item's artifact and convert stored OCR page
        records to ``OcrPageLineage`` tuples.
        """
        from .chapter_translation_pipeline import OcrPageLineage

        try:
            extraction_revision = self.repository.latest_extraction_revision(
                item.project_id, item.artifact_id
            )
            with self.repository._connect() as connection:
                row = connection.execute(
                    "SELECT payload_json FROM writing_reference_extractions "
                    "WHERE tenant_id=? AND project_id=? AND artifact_id=? "
                    "AND extraction_revision=?",
                    (
                        TENANT_ID,
                        item.project_id,
                        item.artifact_id,
                        extraction_revision,
                    ),
                ).fetchone()
            if row is None:
                return ()
            import json as _json

            payload = _json.loads(row["payload_json"])
            ocr_pages = payload.get("ocr_recovery_pages", []) or []
        except Exception:
            return ()
        if not ocr_pages:
            return ()
        lineage = []
        for entry in ocr_pages:
            lineage.append(
                OcrPageLineage(
                    physical_page=entry.get("physical_page", 0),
                    dpi=entry.get("dpi", 0),
                    model=entry.get("model", ""),
                    ocr_profile_digest=entry.get("ocr_profile_digest", ""),
                    source_text_sha256=entry.get("source_text_sha256", ""),
                    channel=entry.get("channel", "ocr"),
                )
            )
        return tuple(lineage)

    def _persist_pipeline_stage(
        self,
        item: WritingReferenceTranslationBatchItem,
        stage: Any,
        phase: str,
        detail: dict,
    ) -> None:
        """Persist a single pipeline stage transition onto the batch item.

        Called before/after each external call so the persisted stage reflects
        real-time progress, not retroactive reconstruction.

        Persistence errors are NOT swallowed: they propagate to the caller
        (_process_claimed_item) which marks the item failed_retryable.  This
        is the correct product state when stage persistence is broken — the
        alternative (silently eating the error) makes UI progress unverifiable.
        """
        stage_value = stage.value if hasattr(stage, "value") else str(stage)
        progress_labels = {
            "toc_planning": "正在识别目录与章节",
            "translating_hy_mt2": "正在按章节翻译正文",
            "integration_qc": "正在核对译文结构与章节衔接",
        }
        update_fields: dict[str, Any] = {
            "pipeline_stage": stage_value,
            "pipeline_stage_detail": detail.get(
                "upper_layer_progress_label",
                progress_labels.get(stage_value, stage_value),
            ),
            "updated_at": self.clock(),
        }
        if stage_value == "toc_planning":
            update_fields["active_upper_layer_stage"] = (
                UPPER_LAYER_DOCUMENT_PLANNING if phase == "before" else ""
            )
        elif stage_value == "integration_qc":
            update_fields["active_upper_layer_stage"] = (
                UPPER_LAYER_POST_HY_INTEGRATION_QC if phase == "before" else ""
            )
        if phase == "after":
            if "plan_model" in detail:
                update_fields["flash_plan_model"] = detail["plan_model"]
                update_fields["plan_model"] = detail["plan_model"]
            if "plan_prompt_version" in detail:
                update_fields["flash_plan_prompt_version"] = detail[
                    "plan_prompt_version"
                ]
            if "hy_mt2_model" in detail:
                update_fields["hy_mt2_model"] = detail["hy_mt2_model"]
            if "hy_mt2_prompt_version" in detail:
                update_fields["hy_mt2_prompt_version"] = detail[
                    "hy_mt2_prompt_version"
                ]
            if "qc_model" in detail:
                update_fields["flash_qc_model"] = detail["qc_model"]
                update_fields["qc_model"] = detail["qc_model"]
            if "qc_prompt_version" in detail:
                update_fields["flash_qc_prompt_version"] = detail[
                    "qc_prompt_version"
                ]
            stage_run_id = str(detail.get("upper_layer_stage_run_id") or "")
            if stage_run_id:
                update_fields["active_upper_layer_stage_run_id"] = ""
                update_fields["latest_upper_layer_stage_run_id"] = stage_run_id
            escalation_id = str(detail.get("upper_layer_escalation_id") or "")
            if escalation_id:
                update_fields["upper_layer_escalation_id"] = escalation_id
                stage_status = str(detail.get("upper_layer_status") or "")
                update_fields["upper_layer_escalation_status"] = {
                    "succeeded": "completed",
                    "completed_degraded": "completed",
                    "failed_retryable": "failed_retryable",
                    "interrupted": "failed_retryable",
                    "failed_terminal": "failed_terminal",
                }.get(stage_status, "running")
        for field_name in (
            "document_structure_plan_id",
            "document_total",
            "document_index",
            "document_label",
            "chapter_id",
            "chapter_title",
            "chapter_total",
            "chapter_index",
            "chunk_count",
            "chunk_completed",
            "chunk_running",
            "chunk_failed",
            "chunk_reused",
            "source_span_count",
        ):
            if field_name in detail:
                update_fields[field_name] = detail[field_name]
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT generation_status, attempt, payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
                """,
                (
                    TENANT_ID,
                    item.project_id,
                    item.batch_id,
                    item.item_id,
                ),
            ).fetchone()
            if (
                row is None
                or str(row["generation_status"]) != "running"
                or int(row["attempt"]) != item.attempt
            ):
                connection.rollback()
                raise _OwnershipLostError(
                    "pipeline stage ownership changed before persistence"
                )
            current = WritingReferenceTranslationBatchItem.model_validate_json(
                row["payload_json"]
            )
            self._persist_downstream_model_call_with(
                connection,
                current,
                stage_value=stage_value,
                phase=phase,
                detail=detail,
            )
            updated = current.model_copy(update=update_fields, deep=True)
            cursor = self._write_item_with(
                connection,
                updated,
                expected_status="running",
                expected_attempt=item.attempt,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise _OwnershipLostError(
                    "pipeline stage ownership changed during persistence"
                )
            self.repository._append_audit(
                connection,
                item.project_id,
                "translation_batch_pipeline_stage",
                item.item_id,
                "system_pipeline",
                {
                    "batch_id": item.batch_id,
                    "stage": stage_value,
                    "phase": phase,
                    "detail_keys": sorted(detail.keys()),
                },
            )
            connection.commit()

    def _persist_downstream_model_call_with(
        self,
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
        *,
        stage_value: str,
        phase: str,
        detail: dict[str, Any],
    ) -> None:
        """Persist transition-scoped call intent/result in the item transaction."""
        transition_id = item.downstream_contract_transition_id
        if (
            not transition_id
            or stage_value not in DOWNSTREAM_MODEL_CALL_STAGES
            or bool(detail.get("model_call_skipped"))
        ):
            return
        if stage_value == TranslationPipelineStage.TRANSLATING_HY_MT2.value:
            scope_id = str(detail.get("chunk_id") or "").strip()
        else:
            chapter_id = str(detail.get("chapter_id") or "").strip()
            scope_id = (
                f"{chapter_id}::{item.span_id}::{item.batch_id}"
                if chapter_id
                else ""
            )
        if not scope_id:
            raise WritingReferenceTranslationModelCallOutcomeUnknownError(
                "model_call_outcome_unknown_after_restart"
            )
        request_payload = {
            "transition_id": transition_id,
            "target_batch_id": item.batch_id,
            "target_item_id": item.item_id,
            "target_plan_id": item.downstream_contract_target_plan_id,
            "target_downstream_fingerprint": (
                item.downstream_contract_target_fingerprint
            ),
            "stage": stage_value,
            "scope_id": scope_id,
            "hy_mt2_prompt_version": HY_MT2_PROMPT_VERSION,
            "flash_qc_prompt_version": FLASH_QC_PROMPT_VERSION,
            "alignment_contract": TRANSLATION_ALIGNMENT_CONTRACT,
        }
        request_hash = _payload_hash(request_payload)
        call_id = "wref_downstream_call_" + _payload_hash(
            request_payload
        )[:24]
        existing = connection.execute(
            """
            SELECT record.request_hash, state.status, state.result_hash
            FROM writing_reference_translation_downstream_model_call_records AS record
            JOIN writing_reference_translation_downstream_model_call_state AS state
              ON state.tenant_id=record.tenant_id
             AND state.project_id=record.project_id
             AND state.call_id=record.call_id
            WHERE record.tenant_id=? AND record.project_id=?
              AND record.call_id=?
            """,
            (TENANT_ID, item.project_id, call_id),
        ).fetchone()
        if phase == "before":
            if existing is not None:
                # Any pre-existing dispatch belongs to an earlier invocation.
                # Recovery must settle it from immutable output or fail closed
                # before the pipeline reaches this point.
                raise WritingReferenceTranslationModelCallOutcomeUnknownError(
                    "model_call_outcome_unknown_after_restart"
                )
            now = self.clock().isoformat()
            connection.execute(
                """
                INSERT INTO writing_reference_translation_downstream_model_call_records(
                    tenant_id, project_id, call_id, transition_id, stage,
                    scope_id, request_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    TENANT_ID,
                    item.project_id,
                    call_id,
                    transition_id,
                    stage_value,
                    scope_id,
                    request_hash,
                    _canonical_json(request_payload),
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO writing_reference_translation_downstream_model_call_state(
                    tenant_id, project_id, call_id, status, result_hash,
                    updated_at
                ) VALUES (?, ?, ?, 'dispatched', '', ?)
                """,
                (TENANT_ID, item.project_id, call_id, now),
            )
            self.repository._append_audit(
                connection,
                item.project_id,
                "translation_downstream_model_call_dispatched",
                call_id,
                "system_pipeline",
                {
                    "transition_id": transition_id,
                    "target_batch_id": item.batch_id,
                    "target_item_id": item.item_id,
                    "target_plan_id": (
                        item.downstream_contract_target_plan_id
                    ),
                    "stage": stage_value,
                    "scope_id": scope_id,
                    "request_hash": request_hash,
                },
            )
            return
        if phase != "after" or existing is None:
            raise WritingReferenceTranslationModelCallOutcomeUnknownError(
                "model_call_outcome_unknown_after_restart"
            )
        if str(existing["request_hash"]) != request_hash:
            raise WritingReferenceConflictError(
                "downstream model-call identity collision"
            )
        result_hash = self._downstream_model_call_output_hash_with(
            connection,
            item,
            stage_value=stage_value,
            scope_id=scope_id,
        )
        if not result_hash:
            raise WritingReferenceTranslationModelCallOutcomeUnknownError(
                "model_call_outcome_unknown_after_restart"
            )
        if str(existing["status"]) == "completed":
            if str(existing["result_hash"]) != result_hash:
                raise WritingReferenceConflictError(
                    "downstream model-call result hash changed"
                )
            return
        cursor = connection.execute(
            """
            UPDATE writing_reference_translation_downstream_model_call_state
            SET status='completed', result_hash=?, updated_at=?
            WHERE tenant_id=? AND project_id=? AND call_id=?
              AND status='dispatched'
            """,
            (
                result_hash,
                self.clock().isoformat(),
                TENANT_ID,
                item.project_id,
                call_id,
            ),
        )
        if cursor.rowcount != 1:
            raise WritingReferenceConflictError(
                "downstream model-call completion lost ownership"
            )
        self.repository._append_audit(
            connection,
            item.project_id,
            "translation_downstream_model_call_completed",
            call_id,
            "system_pipeline",
            {
                "transition_id": transition_id,
                "stage": stage_value,
                "scope_id": scope_id,
                "request_hash": request_hash,
                "result_hash": result_hash,
            },
        )

    @staticmethod
    def _downstream_model_call_output_hash_with(
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
        *,
        stage_value: str,
        scope_id: str,
    ) -> str:
        plan_id = item.downstream_contract_target_plan_id
        if stage_value == TranslationPipelineStage.TRANSLATING_HY_MT2.value:
            row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_chunks
                WHERE tenant_id=? AND project_id=? AND plan_id=?
                  AND chunk_id=?
                """,
                (TENANT_ID, item.project_id, plan_id, scope_id),
            ).fetchone()
            if row is not None:
                chunk = TranslationChunkRecord.model_validate_json(
                    row["payload_json"]
                )
                if chunk.hy_mt2_prompt_version != HY_MT2_PROMPT_VERSION:
                    return ""
                return chunk.translated_text_sha256
            # A bounded Hy fidelity failure has no admitted chunk row.  Its
            # immutable blocked provider output is retained by the exact
            # single-span integration row instead.
            integration_scope = (
                f"{item.chapter_id}::{item.span_id}::{item.batch_id}"
                if item.chapter_id
                else ""
            )
            if integration_scope:
                integration_row = connection.execute(
                    """
                    SELECT payload_json
                    FROM writing_reference_chapter_integration_results
                    WHERE tenant_id=? AND project_id=? AND plan_id=?
                      AND chapter_id=?
                    """,
                    (
                        TENANT_ID,
                        item.project_id,
                        plan_id,
                        integration_scope,
                    ),
                ).fetchone()
                if integration_row is not None:
                    integration = ChapterIntegrationResult.model_validate_json(
                        integration_row["payload_json"]
                    )
                    if (
                        integration.translation_contract_fingerprint
                        == TRANSLATION_CONTRACT_FINGERPRINT
                        and integration.blocked_raw_provider_output_sha256
                    ):
                        return (
                            integration.blocked_raw_provider_output_sha256
                        )
            return ""
        row = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_chapter_integration_results
            WHERE tenant_id=? AND project_id=? AND plan_id=?
              AND chapter_id=?
            """,
            (TENANT_ID, item.project_id, plan_id, scope_id),
        ).fetchone()
        if row is None:
            return ""
        integration = ChapterIntegrationResult.model_validate_json(
            row["payload_json"]
        )
        if (
            integration.translation_contract_fingerprint
            != TRANSLATION_CONTRACT_FINGERPRINT
        ):
            return ""
        return integration.integrated_text_sha256

    def _validate_frozen_lineage(
        self,
        item: WritingReferenceTranslationBatchItem,
        preparation_batch_id: str,
    ) -> None:
        journey, preparation = self._snapshot_scope(
            item.project_id, item.snapshot_id
        )
        if preparation.batch_id != preparation_batch_id:
            raise WritingReferenceTranslationBatchStaleLineageError(
                "latest preparation batch changed after scope freeze"
            )
        retained_ids = self._effective_retained_ids(
            journey, preparation, snapshot_id=item.snapshot_id
        )
        if item.nct_id not in retained_ids:
            raise WritingReferenceTranslationBatchStaleLineageError(
                "retained candidate scope changed after scope freeze"
            )
        try:
            artifact = self.repository.document_artifact(
                item.project_id, item.artifact_id
            )
            validation = self.repository.document_validation(
                item.project_id, item.artifact_id
            )
            latest_extraction = self.repository.latest_extraction_revision(
                item.project_id, item.artifact_id
            )
            span = self.repository.source_span(item.project_id, item.span_id)
        except KeyError as exc:
            raise WritingReferenceTranslationBatchStaleLineageError(
                "frozen source lineage is missing"
            ) from exc
        if (
            not artifact.source_current
            or artifact.snapshot_id != item.snapshot_id
            or artifact.nct_id != item.nct_id
            or artifact.content_sha256 != item.artifact_sha256
            or artifact.state_revision != item.artifact_state_revision
        ):
            raise WritingReferenceTranslationBatchStaleLineageError(
                "frozen artifact is no longer current"
            )
        if (
            validation.validation_id != item.validation_id
            or validation.revision != item.validation_revision
            or validation.status != item.validation_status
            or validation.status not in {"confirmed", "user_overridden"}
            or validation.document_sha256 != item.artifact_sha256
            or validation.source_state_revision != item.artifact_state_revision
            or validation.extraction_revision != item.extraction_revision
        ):
            raise WritingReferenceTranslationBatchStaleLineageError(
                "frozen document validation is no longer current"
            )
        if latest_extraction != item.extraction_revision:
            raise WritingReferenceTranslationBatchStaleLineageError(
                "frozen extraction is no longer latest"
            )
        review = next(
            (
                candidate
                for candidate in self.repository.extraction_reviews(
                    item.project_id, artifact_id=item.artifact_id
                )
                if candidate.extraction_revision == item.extraction_revision
            ),
            None,
        )
        if (
            review is None
            or review.review_id != item.structure_review_id
            or review.revision != item.structure_review_revision
            or review.decision != "approved"
        ):
            raise WritingReferenceTranslationBatchStaleLineageError(
                "frozen structure review is no longer approved"
            )
        ocr_projection = self.repository.effective_ocr_consistency_qc(
            item.project_id,
            item.artifact_id,
            item.extraction_revision,
        )
        if (
            ocr_projection.effective_status
            not in {"pass", "medical_confirmed_with_residual_issue"}
            or ocr_projection.effective_status != item.ocr_qc_effective_status
            or ocr_projection.recheck_id != item.ocr_qc_recheck_id
            or ocr_projection.recheck_revision != item.ocr_qc_recheck_revision
            or ocr_projection.disposition_id != item.ocr_qc_disposition_id
            or ocr_projection.disposition_revision
            != item.ocr_qc_disposition_revision
        ):
            raise WritingReferenceTranslationBatchStaleLineageError(
                "frozen OCR consistency disposition is no longer current"
            )
        if (
            span.artifact_id != item.artifact_id
            or span.extraction_revision != item.extraction_revision
            or span.source_text_sha256 != item.source_text_sha256
            or span.source_text_sha256
            != sha256(span.source_text.encode("utf-8")).hexdigest()
            or span.ich_m11_anchor != item.ich_m11_anchor
            or span.ich_m11_anchor == "unmapped"
        ):
            raise WritingReferenceTranslationBatchStaleLineageError(
                "frozen source span lineage changed"
            )

    @staticmethod
    def _validate_translation_result(
        item: WritingReferenceTranslationBatchItem,
        translation: WritingReferenceTranslationRevision,
    ) -> None:
        if (
            translation.span_id != item.span_id
            or translation.source_span_revision != item.source_span_revision
            or translation.document_sha256 != item.artifact_sha256
            or translation.glossary_version != item.glossary_version
            or translation.contract_hash != item.contract_hash
            or translation.prompt_version != item.prompt_version
            or translation.schema_version != item.schema_version
        ):
            raise WritingReferenceTranslationBatchStaleLineageError(
                "translation result does not match the frozen contract and source lineage"
            )
        if translation.fidelity_status not in {"passed", "blocked"}:
            raise WritingReferenceTranslationBatchStaleLineageError(
                "translation result has an unsupported fidelity status"
            )

    def _finish_claim(
        self,
        claimed: WritingReferenceTranslationBatchItem,
        completed: WritingReferenceTranslationBatchItem,
        actor: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        # Final ownership recheck before committing terminal item state.
        # Exception-safe: any check failure = ownership lost.
        if cancel_check is not None:
            try:
                _lost = cancel_check()
            except Exception:
                _lost = True
            if _lost:
                return
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = self._write_item_with(
                connection,
                completed,
                expected_status="running",
                expected_attempt=claimed.attempt,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return
            self._append_item_completed_audit(connection, completed, actor)
            self._set_downstream_transition_state_with(
                connection,
                completed,
                status=completed.generation_status,
                error_code="",
            )
            connection.commit()

    def _fail_claim(
        self,
        claimed: WritingReferenceTranslationBatchItem,
        status: str,
        error_code: str,
        error: Exception,
        actor: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        # Ownership recheck before persisting failure state — a stale owner
        # must not write terminal business state after lease loss.
        # Exception-safe: any check failure = ownership lost.
        if cancel_check is not None:
            try:
                _lost = cancel_check()
            except Exception:
                _lost = True
            if _lost:
                return
        blocker_kind = (
            "retryable" if status == "failed_retryable"
            else "terminal" if status == "failed_terminal"
            else ""
        )
        failure_codes: list[str] = []
        source_stage_run_id = ""
        latest_stage_run_id = ""
        derived_from_source_failure = False
        if isinstance(error, DocumentPlanValidationError):
            source_stage_run_id = error.source_stage_run_id
            latest_stage_run_id = error.latest_stage_run_id
            derived_from_source_failure = error.derived_from_source_failure
            for code in error.codes:
                value = str(code)
                if "span_" in value:
                    value = "source_span_assignment_failed"
                failure_codes.append(value[:160])
            failure_codes = sorted(dict.fromkeys(failure_codes))
        failed = claimed.model_copy(
            update={
                "generation_status": status,
                "pipeline_stage": status,
                "pipeline_stage_detail": f"failed:{error_code}",
                "error_code": error_code,
                "error_detail": self._public_failure_detail(error_code),
                "blocker_kind": blocker_kind,
                "blocker_message": self._public_failure_detail(error_code),
                "active_upper_layer_stage": (
                    "document_planning"
                    if isinstance(error, DocumentPlanValidationError)
                    else claimed.active_upper_layer_stage
                ),
                "active_upper_layer_stage_run_id": (
                    source_stage_run_id
                    if source_stage_run_id
                    else claimed.active_upper_layer_stage_run_id
                ),
                "latest_upper_layer_stage_run_id": (
                    latest_stage_run_id
                    if latest_stage_run_id
                    else claimed.latest_upper_layer_stage_run_id
                ),
                "document_plan_failure_source_stage_run_id": (
                    source_stage_run_id
                ),
                "document_plan_failure_codes": failure_codes,
                "document_plan_failure_is_derived": (
                    derived_from_source_failure
                ),
                "updated_at": self.clock(),
            },
            deep=True,
        )
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = self._write_item_with(
                connection,
                failed,
                expected_status="running",
                expected_attempt=claimed.attempt,
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return
            self.repository._append_audit(
                connection,
                failed.project_id,
                "translation_batch_item_failed",
                failed.item_id,
                actor,
                {
                    "batch_id": failed.batch_id,
                    "error_code": failed.error_code,
                    "generation_status": failed.generation_status,
                    "attempt": failed.attempt,
                    "failure_codes": failure_codes,
                    "source_stage_run_id": source_stage_run_id,
                    "latest_stage_run_id": latest_stage_run_id,
                    "derived_from_source_failure": (
                        derived_from_source_failure
                    ),
                    "document_plan_retry_generation": (
                        failed.document_plan_retry_generation
                    ),
                    "document_plan_retry_parent_stage_run_id": (
                        failed.document_plan_retry_parent_stage_run_id
                    ),
                    "document_plan_retry_source_item_id": (
                        failed.document_plan_retry_source_item_id
                    ),
                    "exc_type": type(error).__name__,
                    "exc_message": str(error)[:500],
                },
            )
            self._set_downstream_transition_state_with(
                connection,
                failed,
                status=failed.generation_status,
                error_code=failed.error_code,
            )
            connection.commit()

    def _set_downstream_transition_state_with(
        self,
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
        *,
        status: str,
        error_code: str,
    ) -> None:
        transition_id = item.downstream_contract_transition_id
        if not transition_id:
            return
        cursor = connection.execute(
            """
            UPDATE writing_reference_translation_downstream_transition_state
            SET status=?, error_code=?, updated_at=?
            WHERE tenant_id=? AND project_id=? AND transition_id=?
            """,
            (
                status,
                error_code,
                self.clock().isoformat(),
                TENANT_ID,
                item.project_id,
                transition_id,
            ),
        )
        if cursor.rowcount != 1:
            raise WritingReferenceConflictError(
                "downstream transition state is missing"
            )

    @staticmethod
    def _public_failure_detail(error_code: str) -> str:
        if error_code == "stale_lineage":
            return "冻结来源或合同状态已变化，请刷新范围后重新生成。"
        if error_code == "translation_generation_failed":
            return "监管中文候选生成未完成；批次响应不回显供应商原始错误，请按错误码重试。"
        if error_code == "document_plan_failed":
            return "文档章节规划未完成；本轮已停止该文档的后续生成，请修复后按文档重试。"
        if error_code == "model_call_outcome_unknown_after_restart":
            return (
                "模型调用已发出但无可验证的持久化结果；为防止重复调用，"
                "本项已终止并等待人工审计。"
            )
        return "批次项未完成；请依据错误码处置。"

    def _append_item_completed_audit(
        self,
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
        actor: str,
    ) -> None:
        self.repository._append_audit(
            connection,
            item.project_id,
            "translation_batch_item_completed",
            item.item_id,
            actor,
            {
                "batch_id": item.batch_id,
                "translation_id": item.translation_id,
                "translation_revision": item.translation_revision,
                "origin": item.origin,
                "fidelity_status": item.fidelity_status,
                "generation_status": item.generation_status,
                "attempt": item.attempt,
            },
        )

    def _project_review_and_admission(
        self,
        project_id: str,
        items: list[WritingReferenceTranslationBatchItem],
    ) -> list[WritingReferenceTranslationBatchItem]:
        current_translations = {
            translation.translation_id: translation
            for translation in self.repository.translations(project_id)
        }
        reviews = {
            (review.translation_id, review.translation_revision): review
            for review in self.repository.medical_reviews(project_id)
        }
        briefs: dict[tuple[str, int], list[Any]] = defaultdict(list)
        for brief in self.repository.evidence_brief_history(project_id):
            briefs[(brief.translation_id, brief.translation_revision)].append(brief)
        projected = []
        for item in items:
            current = current_translations.get(item.translation_id)
            if current is not None and current.span_id == item.span_id:
                generation_status = (
                    "candidate_ready"
                    if current.fidelity_status == "passed"
                    else "fidelity_blocked"
                )
                item = item.model_copy(
                    update={
                        "generation_status": generation_status,
                        "translation_revision": current.revision,
                        "ai_run_id": current.ai_run_id,
                        "fidelity_status": current.fidelity_status,
                        "fidelity_failure_codes": list(
                            current.fidelity_failure_codes
                        ),
                    },
                    deep=True,
                )
            key = (item.translation_id, item.translation_revision)
            review = reviews.get(key)
            medical_status = review.decision if review is not None else "not_reviewed"
            item_briefs = briefs.get(key, []) if item.translation_id else []
            has_current_brief = any(
                brief.status == "approved_current" for brief in item_briefs
            )
            current_translation_valid = bool(
                current is not None
                and current.span_id == item.span_id
                and current.revision == item.translation_revision
                and current.status
                in {
                    "pending_author_confirmation",
                    "author_confirmed_admitted",
                    "pending_medical_approval",
                }
            )
            current_author_confirmation = bool(
                current_translation_valid
                and current is not None
                and current.status == "author_confirmed_admitted"
                and review is not None
                and review.decision == "approved"
                and review.decision_type == "author_confirmation"
                and review.admission_status == "admitted"
                and has_current_brief
            )
            if current_author_confirmation:
                author_confirmation_status = "confirmed"
            elif current_translation_valid and medical_status in {"returned", "rejected"}:
                author_confirmation_status = medical_status
            else:
                author_confirmation_status = "not_confirmed"
            if has_current_brief:
                admission_status = "admitted"
            elif item_briefs:
                admission_status = "invalidated"
            else:
                admission_status = "not_admitted"
            projected.append(
                item.model_copy(
                    update={
                        "medical_review_status": medical_status,
                        "author_confirmation_status": author_confirmation_status,
                        "admission_status": admission_status,
                    },
                    deep=True,
                )
            )
        return projected

    @staticmethod
    def _counts(
        items: list[WritingReferenceTranslationBatchItem],
        exclusions: list[WritingReferenceTranslationBatchExclusion],
    ) -> WritingReferenceTranslationBatchCounts:
        return WritingReferenceTranslationBatchCounts(
            eligible_count=sum(
                item.generation_status != "excluded" for item in items
            ),
            item_count=len(items),
            candidate_ready_count=sum(
                item.generation_status == "candidate_ready" for item in items
            ),
            fidelity_blocked_count=sum(
                item.generation_status == "fidelity_blocked" for item in items
            ),
            failed_count=sum(
                item.generation_status in FAILED_ITEM_STATUSES for item in items
            ),
            reused_count=sum(item.origin == "existing" for item in items),
            pending_medical_review_count=sum(
                item.generation_status == "candidate_ready"
                and item.medical_review_status in {"not_reviewed", "returned"}
                for item in items
            ),
            approved_count=sum(
                item.medical_review_status == "approved" for item in items
            ),
            pending_author_confirmation_count=sum(
                item.generation_status == "candidate_ready"
                and item.author_confirmation_status
                in {"not_confirmed", "returned"}
                and item.admission_status != "invalidated"
                for item in items
            ),
            author_confirmed_count=sum(
                item.author_confirmation_status == "confirmed" for item in items
            ),
            admitted_count=sum(
                item.admission_status == "admitted" for item in items
            ),
            excluded_count=(
                sum(item.count for item in exclusions)
                + sum(item.generation_status == "excluded" for item in items)
            ),
        )

    @staticmethod
    def _aggregate_status(items: list[WritingReferenceTranslationBatchItem]) -> str:
        statuses = {item.generation_status for item in items}
        if "running" in statuses:
            return "running"
        if "pending" in statuses:
            return "accepted"
        failures = sum(item.generation_status in FAILED_ITEM_STATUSES for item in items)
        completed = sum(
            item.generation_status in {"candidate_ready", "fidelity_blocked"}
            for item in items
        )
        if failures:
            return "partial_failure" if completed else "failed"
        if "fidelity_blocked" in statuses:
            return "completed_with_blocked"
        return "completed"

    def _refresh_batch_status(self, project_id: str, batch_id: str) -> None:
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._refresh_batch_status_with(connection, project_id, batch_id)
            connection.commit()

    def _refresh_batch_status_with(
        self, connection: Any, project_id: str, batch_id: str
    ) -> None:
        rows = connection.execute(
            """
            SELECT payload_json
            FROM writing_reference_translation_batch_items
            WHERE tenant_id=? AND project_id=? AND batch_id=?
            """,
            (TENANT_ID, project_id, batch_id),
        ).fetchall()
        items = [
            WritingReferenceTranslationBatchItem.model_validate_json(row["payload_json"])
            for row in rows
        ]
        connection.execute(
            """
            UPDATE writing_reference_translation_batches
            SET status=?, updated_at=?
            WHERE tenant_id=? AND project_id=? AND batch_id=?
            """,
            (
                self._aggregate_status(items),
                self.clock().isoformat(),
                TENANT_ID,
                project_id,
                batch_id,
            ),
        )

    def _set_batch_status(self, project_id: str, batch_id: str, status: str) -> None:
        with self.repository._connect() as connection:
            connection.execute(
                """
                UPDATE writing_reference_translation_batches
                SET status=?, updated_at=?
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                """,
                (
                    status,
                    self.clock().isoformat(),
                    TENANT_ID,
                    project_id,
                    batch_id,
                ),
            )

    @staticmethod
    def _insert_item_with(
        connection: Any, item: WritingReferenceTranslationBatchItem
    ) -> None:
        connection.execute(
            """
            INSERT INTO writing_reference_translation_batch_items(
                tenant_id, project_id, batch_id, item_id, span_id,
                generation_status, attempt, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_ID,
                item.project_id,
                item.batch_id,
                item.item_id,
                item.span_id,
                item.generation_status,
                item.attempt,
                _canonical_json(item.model_dump(mode="json")),
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
            ),
        )

    @staticmethod
    def _write_item_with(
        connection: Any,
        item: WritingReferenceTranslationBatchItem,
        *,
        expected_status: str,
        expected_attempt: int,
    ) -> Any:
        return connection.execute(
            """
            UPDATE writing_reference_translation_batch_items
            SET generation_status=?, attempt=?, payload_json=?, updated_at=?
            WHERE tenant_id=? AND project_id=? AND batch_id=? AND item_id=?
              AND generation_status=? AND attempt=?
            """,
            (
                item.generation_status,
                item.attempt,
                _canonical_json(item.model_dump(mode="json")),
                item.updated_at.isoformat(),
                TENANT_ID,
                item.project_id,
                item.batch_id,
                item.item_id,
                expected_status,
                expected_attempt,
            ),
        )

    def _idempotent_result(
        self,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> str | None:
        with self.repository._connect() as connection:
            return self._idempotent_result_with(
                connection,
                project_id,
                operation,
                idempotency_key,
                request_hash,
            )

    @staticmethod
    def _idempotent_result_with(
        connection: Any,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT request_hash, result_id
            FROM writing_reference_translation_batch_idempotency
            WHERE tenant_id=? AND project_id=? AND operation=? AND idempotency_key=?
            """,
            (TENANT_ID, project_id, operation, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != request_hash:
            raise WritingReferenceConflictError(
                "translation batch idempotency key was reused with different content"
            )
        return str(row["result_id"])

    def _record_idempotency_with(
        self,
        connection: Any,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_hash: str,
        result_id: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO writing_reference_translation_batch_idempotency(
                tenant_id, project_id, operation, idempotency_key,
                request_hash, result_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                TENANT_ID,
                project_id,
                operation,
                idempotency_key,
                request_hash,
                result_id,
                self.clock().isoformat(),
            ),
        )

    def _recover_interrupted_items(self) -> None:
        """Recover running items across ALL batches.

        This must NOT be called from the constructor because it would steal
        live owners in concurrent-process scenarios.  It is retained for
        explicit startup wiring by the HTTP layer (worker_05) when the
        durable store has confirmed that all prior leases have expired.
        """
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND generation_status='running'
                """,
                (TENANT_ID,),
            ).fetchall()
            affected: set[tuple[str, str]] = set()
            for row in rows:
                item = WritingReferenceTranslationBatchItem.model_validate_json(
                    row["payload_json"]
                )
                if item.downstream_contract_transition_id:
                    # Transition recovery requires call-ledger settlement and
                    # is handled only by the exact transition executor.
                    continue
                recovered = item.model_copy(
                    update={
                        "generation_status": "failed_retryable",
                        "error_code": "service_restart_interrupted",
                        "error_detail": (
                            "Translation generation was interrupted before completion "
                            "and is eligible for failed-only retry."
                        ),
                        "updated_at": self.clock(),
                    },
                    deep=True,
                )
                cursor = self._write_item_with(
                    connection,
                    recovered,
                    expected_status="running",
                    expected_attempt=item.attempt,
                )
                if cursor.rowcount == 1:
                    self.repository._append_audit(
                        connection,
                        item.project_id,
                        "translation_batch_item_recovered_after_restart",
                        item.item_id,
                        "system_recovery",
                        {
                            "batch_id": item.batch_id,
                            "error_code": recovered.error_code,
                            "generation_status": recovered.generation_status,
                            "attempt": recovered.attempt,
                        },
                    )
                    affected.add((item.project_id, item.batch_id))
            for project_id, batch_id in affected:
                self._refresh_batch_status_with(connection, project_id, batch_id)
            connection.commit()

    def recover_pending_batches(self) -> list[tuple[str, str]]:
        """Identify batches that need recovery scheduling on startup.

        Returns ``(project_id, batch_id)`` pairs for batches that have items
        in ``pending``, ``running``, or ``failed_retryable`` state.

        After Gap 1 removed the blanket constructor recovery, ``running``
        items survive startup and are recovered per-batch only after durable
        takeover.  ``pending`` items were never recovered before.  This method
        identifies all non-terminal batches so startup wiring can schedule
        durable jobs for each.
        """
        with self.repository._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT project_id, batch_id
                FROM writing_reference_translation_batch_items
                WHERE tenant_id = ?
                  AND generation_status IN ('pending', 'running', 'failed_retryable')
                """,
                (TENANT_ID,),
            ).fetchall()
        return [
            (str(row["project_id"]), str(row["batch_id"])) for row in rows
        ]

    def recover_downstream_contract_transition_for_execution(
        self,
        project_id: str,
        transition_id: str,
    ) -> WritingReferenceTranslationDownstreamTransitionState:
        """Settle one transition after durable takeover without re-calling AI."""
        record = self.downstream_contract_transition(
            project_id,
            transition_id,
        )
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT generation_status, attempt, payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND item_id=?
                """,
                (
                    TENANT_ID,
                    project_id,
                    record.target_batch_id,
                    record.target_item_id,
                ),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise WritingReferenceConflictError(
                    "downstream transition target item is missing"
                )
            item = WritingReferenceTranslationBatchItem.model_validate_json(
                row["payload_json"]
            )
            call_rows = connection.execute(
                """
                SELECT record.call_id, record.stage, record.scope_id,
                       state.status
                FROM writing_reference_translation_downstream_model_call_records AS record
                JOIN writing_reference_translation_downstream_model_call_state AS state
                  ON state.tenant_id=record.tenant_id
                 AND state.project_id=record.project_id
                 AND state.call_id=record.call_id
                WHERE record.tenant_id=? AND record.project_id=?
                  AND record.transition_id=?
                ORDER BY record.call_id
                """,
                (TENANT_ID, project_id, transition_id),
            ).fetchall()
            unknown_call_ids: list[str] = []
            recovered_call_ids: list[str] = []
            for call_row in call_rows:
                if str(call_row["status"]) != "dispatched":
                    continue
                result_hash = self._downstream_model_call_output_hash_with(
                    connection,
                    item,
                    stage_value=str(call_row["stage"]),
                    scope_id=str(call_row["scope_id"]),
                )
                if not result_hash:
                    unknown_call_ids.append(str(call_row["call_id"]))
                    continue
                connection.execute(
                    """
                    UPDATE writing_reference_translation_downstream_model_call_state
                    SET status='completed', result_hash=?, updated_at=?
                    WHERE tenant_id=? AND project_id=? AND call_id=?
                      AND status='dispatched'
                    """,
                    (
                        result_hash,
                        self.clock().isoformat(),
                        TENANT_ID,
                        project_id,
                        str(call_row["call_id"]),
                    ),
                )
                recovered_call_ids.append(str(call_row["call_id"]))
                self.repository._append_audit(
                    connection,
                    project_id,
                    "translation_downstream_model_call_recovered",
                    str(call_row["call_id"]),
                    "system_recovery",
                    {
                        "transition_id": transition_id,
                        "stage": str(call_row["stage"]),
                        "scope_id": str(call_row["scope_id"]),
                        "result_hash": result_hash,
                    },
                )

            current_status = str(row["generation_status"])
            if unknown_call_ids:
                failed = item.model_copy(
                    update={
                        "generation_status": "failed_terminal",
                        "pipeline_stage": "failed_terminal",
                        "pipeline_stage_detail": (
                            "failed:model_call_outcome_unknown_after_restart"
                        ),
                        "error_code": (
                            "model_call_outcome_unknown_after_restart"
                        ),
                        "error_detail": self._public_failure_detail(
                            "model_call_outcome_unknown_after_restart"
                        ),
                        "blocker_kind": "terminal",
                        "blocker_message": self._public_failure_detail(
                            "model_call_outcome_unknown_after_restart"
                        ),
                        "updated_at": self.clock(),
                    },
                    deep=True,
                )
                cursor = self._write_item_with(
                    connection,
                    failed,
                    expected_status=current_status,
                    expected_attempt=item.attempt,
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "downstream transition restart recovery lost ownership"
                    )
                self._set_downstream_transition_state_with(
                    connection,
                    failed,
                    status="failed_terminal",
                    error_code=failed.error_code,
                )
                self.repository._append_audit(
                    connection,
                    project_id,
                    "translation_downstream_contract_transition_failed_closed",
                    transition_id,
                    "system_recovery",
                    {
                        "target_batch_id": record.target_batch_id,
                        "target_item_id": record.target_item_id,
                        "error_code": failed.error_code,
                        "unknown_call_ids": unknown_call_ids,
                    },
                )
                self._refresh_batch_status_with(
                    connection,
                    project_id,
                    record.target_batch_id,
                )
                connection.commit()
                return self.downstream_contract_transition_state(
                    project_id,
                    transition_id,
                )

            if current_status == "running":
                persisted_output_exists = bool(call_rows)
                recovery_code = (
                    "service_restart_persisted_output_recovered"
                    if persisted_output_exists
                    else "service_restart_interrupted"
                )
                recovery_detail = (
                    "Persisted target-contract output was recovered; "
                    "the exact item may resume without another model call."
                    if persisted_output_exists
                    else (
                        "Transition execution stopped before any external-call "
                        "intent was committed and may resume safely."
                    )
                )
                recovered = item.model_copy(
                    update={
                        "generation_status": "failed_retryable",
                        "error_code": recovery_code,
                        "error_detail": recovery_detail,
                        "updated_at": self.clock(),
                    },
                    deep=True,
                )
                cursor = self._write_item_with(
                    connection,
                    recovered,
                    expected_status="running",
                    expected_attempt=item.attempt,
                )
                if cursor.rowcount != 1:
                    connection.rollback()
                    raise WritingReferenceConflictError(
                        "downstream transition restart recovery lost ownership"
                    )
                self._set_downstream_transition_state_with(
                    connection,
                    recovered,
                    status="failed_retryable",
                    error_code=recovered.error_code,
                )
                self.repository._append_audit(
                    connection,
                    project_id,
                    "translation_downstream_contract_transition_recovered",
                    transition_id,
                    "system_recovery",
                    {
                        "target_batch_id": record.target_batch_id,
                        "target_item_id": record.target_item_id,
                        "generation_status": recovered.generation_status,
                        "attempt": recovered.attempt,
                        "recovered_call_ids": recovered_call_ids,
                    },
                )
                self._refresh_batch_status_with(
                    connection,
                    project_id,
                    record.target_batch_id,
                )
            connection.commit()
        return self.downstream_contract_transition_state(
            project_id,
            transition_id,
        )

    def recover_interrupted_items_for_batch(
        self, project_id: str, batch_id: str
    ) -> None:
        """Recover running items for a *single* batch after durable takeover.

        This is the safe replacement for the blanket constructor recovery.
        It must be called only after the durable worker has successfully
        claimed the job for this specific batch (proving the prior owner's
        lease has expired or been taken over).  Running items are converted
        to ``failed_retryable`` so the new owner's ``_run_items`` picks them
        up in the retryable set.
        """
        with self.repository._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_translation_batch_items
                WHERE tenant_id=? AND project_id=? AND batch_id=?
                  AND generation_status='running'
                """,
                (TENANT_ID, project_id, batch_id),
            ).fetchall()
            affected = False
            for row in rows:
                item = WritingReferenceTranslationBatchItem.model_validate_json(
                    row["payload_json"]
                )
                if item.downstream_contract_transition_id:
                    continue
                recovered = item.model_copy(
                    update={
                        "generation_status": "failed_retryable",
                        "error_code": "service_restart_interrupted",
                        "error_detail": (
                            "Translation generation was interrupted before "
                            "completion and is eligible for failed-only retry."
                        ),
                        "updated_at": self.clock(),
                    },
                    deep=True,
                )
                cursor = self._write_item_with(
                    connection,
                    recovered,
                    expected_status="running",
                    expected_attempt=item.attempt,
                )
                if cursor.rowcount == 1:
                    self.repository._append_audit(
                        connection,
                        item.project_id,
                        "translation_batch_item_recovered_after_restart",
                        item.item_id,
                        "system_recovery",
                        {
                            "batch_id": item.batch_id,
                            "error_code": recovered.error_code,
                            "generation_status": recovered.generation_status,
                            "attempt": recovered.attempt,
                        },
                    )
                    affected = True
            if affected:
                self._refresh_batch_status_with(connection, project_id, batch_id)
            connection.commit()


class TranslationBatchDurableExecutor:
    """Durable job executor that drives translation batch item processing.

    Implements the :class:`DurableJobExecutor` protocol.  The durable worker
    claims the job, provides ``cancel_check`` and ``heartbeat`` callbacks, and
    this executor delegates to the batch service's ``run_pending_with_callbacks``
    or ``run_failed_with_callbacks``.

    Completed items and immutable document-plan work are reused (never
    retranslated) because the batch service's ``_run_items`` only selects items
    matching ``allowed_statuses``.  Cancellation is checked between items so a
    cancelled or stale-owner job stops promptly without writing terminal
    business state for unprocessed items.
    """

    job_type = REFERENCE_TRANSLATION_JOB_TYPE

    def __init__(
        self,
        batch_service: WritingReferenceTranslationBatchService,
        *,
        mode: str = "pending",
        actor: str = "durable_worker",
    ) -> None:
        self._batch_service = batch_service
        self._mode = mode
        self._actor = actor

    def execute(
        self,
        job: Any,
        claim_token: str,
        cancel_check: Callable[[], bool],
        heartbeat: Callable[..., bool],
    ) -> Any:
        """Run the batch items under durable claim/heartbeat/cancel.

        After _run_items returns, recheck ownership and aggregate batch state.
        Cancelled/lost-claim/retryable-failure must NOT return success.
        Only genuinely terminal batch state (all items candidate_ready,
        fidelity_blocked, excluded, or failed_terminal) may return success.
        """
        from services.api.app.medical_writing_durable_jobs import DurableJobResult

        payload = {}
        if job.payload_json:
            try:
                payload = json.loads(job.payload_json)
            except (json.JSONDecodeError, TypeError):
                payload = {}
        batch_id = payload.get("batch_id") or job.business_key
        actor = payload.get("actor", self._actor)
        is_retry = payload.get("retry", False)
        transition_id = str(
            payload.get("downstream_contract_transition_id") or ""
        )

        # Check ownership before any mutation — a stale/cancelled executor
        # invocation must not recover or mutate running items.
        if cancel_check():
            from services.api.app.medical_writing_durable_jobs import DurableJobResult
            return DurableJobResult(
                error="executor invoked with stale or cancelled claim",
                retryable=True,
            )

        if transition_id:
            try:
                state = (
                    self._batch_service
                    .recover_downstream_contract_transition_for_execution(
                        job.project_id,
                        transition_id,
                    )
                )
                if (
                    state.status == "failed_terminal"
                    and state.error_code
                    == "model_call_outcome_unknown_after_restart"
                ):
                    return DurableJobResult(
                        error=state.error_code,
                        retryable=False,
                    )
                self._batch_service.run_downstream_contract_transition_with_callbacks(
                    job.project_id,
                    transition_id,
                    actor,
                    cancel_check=cancel_check,
                    heartbeat=heartbeat,
                )
            except Exception as exc:
                return DurableJobResult(
                    error=f"{type(exc).__name__}: {exc}",
                    retryable=not isinstance(
                        exc,
                        WritingReferenceTranslationModelCallOutcomeUnknownError,
                    ),
                )
            if cancel_check():
                return DurableJobResult(
                    error="claim lost or cancelled during execution",
                    retryable=True,
                )
            state = self._batch_service.downstream_contract_transition_state(
                job.project_id,
                transition_id,
            )
            if state.status in {"pending", "running", "failed_retryable"}:
                return DurableJobResult(
                    error=(
                        state.error_code
                        or "downstream transition item remains retryable"
                    ),
                    retryable=True,
                )
            if state.status == "failed_terminal":
                return DurableJobResult(
                    error=state.error_code or "downstream transition failed",
                    retryable=False,
                )
            return DurableJobResult(
                artifact_locator=json.dumps(
                    {
                        "batch_id": batch_id,
                        "transition_id": transition_id,
                        "target_item_id": payload.get("target_item_id", ""),
                    }
                ),
                provider="composite_pipeline",
                model=HY_MT2_MODEL_ID,
            )

        # After durable claim but before running items, recover any running
        # items that belong to this specific batch.  This is safe because
        # we have just claimed the durable job (proving prior lease expired).
        self._batch_service.recover_interrupted_items_for_batch(
            job.project_id, batch_id
        )

        try:
            if is_retry or self._mode == "failed":
                self._batch_service.run_failed_with_callbacks(
                    job.project_id,
                    batch_id,
                    actor,
                    cancel_check=cancel_check,
                    heartbeat=heartbeat,
                )
            else:
                self._batch_service.run_pending_with_callbacks(
                    job.project_id,
                    batch_id,
                    actor,
                    cancel_check=cancel_check,
                    heartbeat=heartbeat,
                )
        except Exception as exc:
            return DurableJobResult(
                error=f"{type(exc).__name__}: {exc}",
                retryable=True,
            )

        # Recheck ownership: if we lost the claim, do not return success.
        if cancel_check():
            return DurableJobResult(
                error="claim lost or cancelled during execution",
                retryable=True,
            )

        # Aggregate batch state to decide terminal vs retryable.
        batch = self._batch_service.get(job.project_id, batch_id)
        item_statuses = {item.generation_status for item in batch.items}
        has_pending = "pending" in item_statuses
        has_running = "running" in item_statuses
        has_failed_retryable = "failed_retryable" in item_statuses

        if has_pending or has_running:
            # Cancellation or claim loss stopped work with unprocessed items.
            return DurableJobResult(
                error="batch has pending or running items after execution",
                retryable=True,
            )

        if has_failed_retryable:
            # Retryable failures present — return error so the durable job
            # enters retry_wait, not completed.
            return DurableJobResult(
                error="batch has failed_retryable items",
                retryable=True,
            )

        return DurableJobResult(
            artifact_locator=json.dumps({"batch_id": batch_id}),
            provider="composite_pipeline",
            model=HY_MT2_MODEL_ID,
        )
