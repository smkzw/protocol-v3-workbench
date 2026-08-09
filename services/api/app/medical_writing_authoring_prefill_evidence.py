"""Server-side evidence catalog builder for AI-first authoring prefill.

This module is a pure, no-I/O builder: it takes a ``MedicalWritingAuthoringJourney``
and an optional ``WritingReferenceSearchSnapshot``, and produces an immutable,
hash-stable ``AuthoringPrefillEvidenceCatalog``.

W2b-1 boundary: this module does NOT call AI, does NOT change the generation
path, does NOT implement composite adoption, and does NOT modify the frontend.

Entry point::

    from .medical_writing_authoring_prefill_evidence import build_evidence_catalog

    catalog = build_evidence_catalog(journey, snapshot=snapshot)
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from packages.contracts.workbench_contracts import (
    AuthoringPrefillEvidenceCatalog,
    AuthoringPrefillEvidenceCatalogEntry,
    MedicalWritingAuthoringJourney,
    MedicalWritingStudyFraming,
    MedicalWritingSynopsisEvidenceSpan,
    MedicalWritingSynopsisImport,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_PROJECT_FACT_ENTRIES = 30
MAX_SYNOPSIS_SPAN_ENTRIES = 120
MAX_CTOV_CANDIDATES = 40
MAX_CTOV_FIELDS_PER_CANDIDATE = 20

# ---------------------------------------------------------------------------
# Framing facts that are always included as project_fact entries (if non-empty).
# ---------------------------------------------------------------------------

_FRAMING_FACT_SPECS: Tuple[Tuple[str, str], ...] = (
    ("framing.investigational_product", "investigational_product"),
    ("framing.indication", "indication"),
    ("framing.study_phase", "study_phase"),
)

# Per-field supported_target_paths for framing identity facts.
# Each fact only supports itself and fields it can legitimately participate
# in deriving — never the other two identity facts, and never protocol_id.
_FRAMING_FACT_TARGET_PATHS: Dict[str, Tuple[str, ...]] = {
    "framing.investigational_product": (
        "framing.investigational_product",
        "framing.document_title",
    ),
    "framing.indication": (
        "framing.indication",
        "framing.document_title",
        "framing.clinicaltrials_condition_term",
    ),
    "framing.study_phase": (
        "framing.study_phase",
        "framing.document_title",
    ),
}

# Synopsis field_evidence_span_ids field name -> the target_paths that the
# field can support.  Only confirmed synopsis spans whose field name maps
# to this table are admitted.
_SYNOPSIS_FIELD_TARGET_PATHS: Dict[str, Tuple[str, ...]] = {
    "framing.protocol_id": ("framing.protocol_id",),
    "framing.document_title": ("framing.document_title",),
    "framing.indication": ("framing.indication",),
    "framing.clinicaltrials_condition_term": (
        "framing.clinicaltrials_condition_term",
    ),
    "framing.study_phase": ("framing.study_phase",),
    "framing.investigational_product": ("framing.investigational_product",),
    "framing.target_mechanism": ("framing.target_mechanism",),
    "framing.competitor_target_scope": ("framing.competitor_target_scope",),
    "framing.design_pattern": ("framing.design_pattern",),
    "framing.population_intent": ("framing.population_intent",),
    "picos.design_archetype": ("picos.design_archetype",),
    "picos.population_summary": ("picos.population_summary",),
    "picos.inclusion_modules": ("picos.inclusion_modules",),
    "picos.exclusion_modules": ("picos.exclusion_modules",),
    "picos.intervention_summary": ("picos.intervention_summary",),
    "picos.comparator_summary": ("picos.comparator_summary",),
    "picos.primary_objectives": ("picos.primary_objectives",),
    "picos.secondary_objectives": ("picos.secondary_objectives",),
    "picos.key_secondary_endpoints": ("picos.key_secondary_endpoints",),
    "picos.primary_endpoints": ("picos.primary_endpoints",),
    "picos.other_secondary_endpoints": ("picos.other_secondary_endpoints",),
    "picos.safety_endpoints": ("picos.safety_endpoints",),
    "picos.statistical_strategy": ("picos.statistical_strategy",),
    "picos.estimand_strategy": ("picos.estimand_strategy",),
    "picos.study_epochs": ("picos.study_epochs",),
    "picos.visit_strategy": ("picos.visit_strategy",),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_ws(text: str) -> str:
    """NFKC + whitespace collapse."""
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.split())


def _compute_quote_hash(quote: str) -> str:
    """Server-side quote hash.  Applied to the raw, unmodified quote text."""
    return _sha256_hex(quote)


def _entry_id(
    catalog_id: str,
    source_id: str,
    locator: str,
    quote_sha256: str,
) -> str:
    """Stable, deterministic entry ID."""
    raw = f"{catalog_id}|{source_id}|{locator}|{quote_sha256}"
    return _sha256_hex(raw)[:32]


def _catalog_id(project_id: str, journey_revision: int, snapshot_id: str) -> str:
    raw = f"evid|{project_id}|{journey_revision}|{snapshot_id}"
    return _sha256_hex(raw)[:32]


def _catalog_sha256(
    project_id: str,
    journey_revision: int,
    snapshot_id: str,
    entries: List[AuthoringPrefillEvidenceCatalogEntry],
) -> str:
    """Deterministic catalog hash sensitive to project, journey revision,
    snapshot ID, entry ordering, entry IDs, quote hashes and source revisions."""
    payload: List[Dict[str, Any]] = []
    for entry in entries:
        payload.append(
            {
                "id": entry.catalog_entry_id,
                "sid": entry.source_id,
                "rev": entry.source_revision,
                "qh": entry.quote_sha256,
                "sk": entry.source_kind,
                "ss": entry.support_scope,
            }
        )
    canonical = json.dumps(
        {
            "p": project_id,
            "r": journey_revision,
            "s": snapshot_id,
            "e": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256_hex(canonical)


# ---------------------------------------------------------------------------
# Project facts (framing)
# ---------------------------------------------------------------------------


def _collect_framing_facts(
    catalog_id: str,
    framing: MedicalWritingStudyFraming,
    truncation_notes: List[str],
) -> List[AuthoringPrefillEvidenceCatalogEntry]:
    entries: List[AuthoringPrefillEvidenceCatalogEntry] = []
    for target_path, attr_name in _FRAMING_FACT_SPECS:
        value = getattr(framing, attr_name, "").strip()
        if not value:
            continue
        if len(entries) >= MAX_PROJECT_FACT_ENTRIES:
            truncation_notes.append(
                f"项目事实条目已达上限{MAX_PROJECT_FACT_ENTRIES}条，"
                f"后续事实已截断"
            )
            break
        quote = value
        quote_sha = _compute_quote_hash(quote)
        source_id = target_path
        locator = target_path
        entry_id = _entry_id(catalog_id, source_id, locator, quote_sha)
        target_paths = _FRAMING_FACT_TARGET_PATHS.get(target_path, (target_path,))
        entries.append(
            AuthoringPrefillEvidenceCatalogEntry(
                catalog_entry_id=entry_id,
                catalog_id=catalog_id,
                source_kind="project_fact",
                source_id=source_id,
                source_revision=f"framing@{framing.version.strip() or 'unknown'}",
                locator=locator,
                quote=quote,
                quote_sha256=quote_sha,
                title=f"项目最小事实：{attr_name}",
                support_scope="current_project_fact",
                supported_target_paths=list(target_paths),
                provenance={"fact_path": target_path},
            )
        )

    return entries


# ---------------------------------------------------------------------------
# Synopsis evidence spans
# ---------------------------------------------------------------------------


def _collect_synopsis_entries(
    catalog_id: str,
    synopsis_import: MedicalWritingSynopsisImport,
    truncation_notes: List[str],
) -> List[AuthoringPrefillEvidenceCatalogEntry]:
    if synopsis_import.status != "confirmed":
        return []

    # Determine the authoritative source_id from the synopsis import source.
    if synopsis_import.source is None:
        return []
    expected_source_id = synopsis_import.source.source_id.strip()
    if not expected_source_id:
        return []

    # Build span lookup
    span_lookup: Dict[str, MedicalWritingSynopsisEvidenceSpan] = {}
    for span in synopsis_import.evidence_spans:
        span_lookup[span.span_id] = span

    # Map: field_name -> list of span_ids
    field_map = synopsis_import.field_evidence_span_ids
    # Map: field_name -> extracted_value_sha256
    value_sha_map = synopsis_import.field_extracted_value_sha256

    entries: List[AuthoringPrefillEvidenceCatalogEntry] = []

    for field_name, span_ids in sorted(field_map.items()):
        target_paths = _SYNOPSIS_FIELD_TARGET_PATHS.get(field_name)
        if target_paths is None:
            continue
        for span_id in span_ids:
            span = span_lookup.get(span_id)
            if span is None:
                # Span ID not found in evidence_spans — fail closed, skip.
                continue
            if len(entries) >= MAX_SYNOPSIS_SPAN_ENTRIES:
                truncation_notes.append(
                    f"已确认摘要证据条目已达上限{MAX_SYNOPSIS_SPAN_ENTRIES}条，"
                    f"后续span已截断"
                )
                return entries

            quote = span.source_text
            expected_hash = span.source_text_sha256
            # Verify the hash matches the actual text
            actual_hash = _compute_quote_hash(quote)
            if actual_hash != expected_hash:
                # Hash mismatch — fail closed, skip this span
                continue

            # Verify source_id is non-empty and consistent with the import source.
            if not span.source_id:
                continue
            if span.source_id != expected_source_id:
                # source_id inconsistency — fail closed, skip this span
                continue

            locator = span.locator
            # Same quote + different locator => different entry (by design)
            entry_id = _entry_id(
                catalog_id,
                span.source_id,
                locator,
                expected_hash,
            )
            # If entry_id already exists (same source_id + same locator + same hash),
            # skip duplicate
            if any(e.catalog_entry_id == entry_id for e in entries):
                continue

            revision = value_sha_map.get(field_name, expected_hash)
            entries.append(
                AuthoringPrefillEvidenceCatalogEntry(
                    catalog_entry_id=entry_id,
                    catalog_id=catalog_id,
                    source_kind="synopsis",
                    source_id=span.source_id,
                    source_revision=revision,
                    locator=locator,
                    quote=quote,
                    quote_sha256=expected_hash,
                    title=f"方案摘要证据：{field_name}",
                    support_scope="current_project_fact",
                    supported_target_paths=list(target_paths),
                    provenance={
                        "span_id": span_id,
                        "field_name": field_name,
                    },
                )
            )

    return entries


# ---------------------------------------------------------------------------
# ClinicalTrials.gov snapshot entries
# ---------------------------------------------------------------------------


def _ctgov_entry(
    catalog_id: str,
    snapshot_id: str,
    nct_id: str,
    field_key: str,
    quote: str,
    title: str,
) -> Optional[AuthoringPrefillEvidenceCatalogEntry]:
    """Build a single CT.gov competitor observation entry."""
    quote = quote.strip() if isinstance(quote, str) else ""
    if not quote:
        return None
    quote_sha = _compute_quote_hash(quote)
    source_id = f"ctgov:{snapshot_id}:{nct_id}"
    locator = f"ctgov:{snapshot_id}:{nct_id}:{field_key}"
    entry_id = _entry_id(catalog_id, source_id, locator, quote_sha)
    return AuthoringPrefillEvidenceCatalogEntry(
        catalog_entry_id=entry_id,
        catalog_id=catalog_id,
        source_kind="ctgov_snapshot",
        source_id=source_id,
        source_revision=snapshot_id,
        locator=locator,
        quote=quote,
        quote_sha256=quote_sha,
        title=title,
        support_scope="competitor_observation",
        supported_target_paths=[],  # CT.gov entries never support project facts
        provenance={
            "snapshot_id": snapshot_id,
            "nct_id": nct_id,
            "field_key": field_key,
        },
    )


def _collect_ctgov_entries(
    catalog_id: str,
    snapshot: WritingReferenceSearchSnapshot,
    truncation_notes: List[str],
) -> List[AuthoringPrefillEvidenceCatalogEntry]:
    entries: List[AuthoringPrefillEvidenceCatalogEntry] = []

    # Stable sort by nct_id BEFORE truncation, so different input orders
    # produce the same candidate selection and hence the same catalog hash.
    sorted_candidates = sorted(snapshot.candidates, key=lambda c: c.nct_id)
    candidates = sorted_candidates[:MAX_CTOV_CANDIDATES]
    if len(sorted_candidates) > MAX_CTOV_CANDIDATES:
        truncation_notes.append(
            f"ClinicalTrials.gov候选数超过上限{MAX_CTOV_CANDIDATES}个，"
            f"已截断"
        )

    for cand in candidates:
        if len(entries) >= MAX_CTOV_CANDIDATES * MAX_CTOV_FIELDS_PER_CANDIDATE:
            break
        field_count = 0

        def _add(field_key: str, value: str, title: str) -> None:
            nonlocal field_count
            if field_count >= MAX_CTOV_FIELDS_PER_CANDIDATE:
                return
            if not value or not str(value).strip():
                return
            entry = _ctgov_entry(
                catalog_id,
                snapshot.snapshot_id,
                cand.nct_id,
                field_key,
                str(value),
                title,
            )
            if entry is not None:
                entries.append(entry)
                field_count += 1

        _add("nct_id", cand.nct_id, f"NCT编号")
        _add("brief_title", cand.brief_title, "简短标题")
        _add("official_title", cand.official_title, "正式标题")
        _add("brief_summary", cand.brief_summary, "Brief Summary")
        _add("conditions", "；".join(cand.conditions) if cand.conditions else "", "疾病")
        _add("phases", "；".join(cand.phases) if cand.phases else "", "分期")
        _add("study_type", cand.study_type, "研究类型")
        # Interventions (name + type per item)
        for idx, interv in enumerate(cand.interventions):
            if field_count >= MAX_CTOV_FIELDS_PER_CANDIDATE:
                break
            _add(
                f"intervention[{idx}].name",
                interv.name,
                f"干预{idx + 1}名称",
            )
            _add(
                f"intervention[{idx}].type",
                interv.intervention_type,
                f"干预{idx + 1}类型",
            )
        _add("design_allocation", cand.design_allocation, "分配方式")
        _add(
            "design_intervention_model",
            cand.design_intervention_model,
            "干预模型",
        )
        _add("design_masking", cand.design_masking, "盲法")
        _add(
            "enrollment_count",
            str(cand.enrollment_count) if cand.enrollment_count is not None else "",
            "入组人数",
        )
        _add("lead_sponsor", cand.lead_sponsor, "申办方")
        _add("overall_status", cand.overall_status, "状态")
        _add("study_record_url", cand.study_record_url, "研究记录URL")
        # Public documents
        for doc in cand.public_documents:
            if field_count >= MAX_CTOV_FIELDS_PER_CANDIDATE:
                break
            _add(
                f"document:{doc.document_id}:document_type",
                doc.document_type,
                f"公开文档类型：{doc.filename}",
            )
            _add(
                f"document:{doc.document_id}:filename",
                doc.filename,
                f"公开文档文件名",
            )
            _add(
                f"document:{doc.document_id}:date",
                doc.document_date,
                f"公开文档日期：{doc.filename}",
            )

    return entries


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_evidence_catalog(
    journey: MedicalWritingAuthoringJourney,
    snapshot: Optional[WritingReferenceSearchSnapshot] = None,
    *,
    corpus_analysis_reader=None,
    corpus_entries: Optional[List[AuthoringPrefillEvidenceCatalogEntry]] = None,
    corpus_source_reader=None,
    journey_revision: Optional[int] = None,
) -> AuthoringPrefillEvidenceCatalog:
    """Build an immutable, hash-stable evidence catalog from the current
    project state.

    ``journey_revision`` optionally overrides the revision the catalog is
    bound to.  Generation builds the package and its catalog against the
    *next* persisted journey revision (``journey.revision + 1``) so the
    persisted catalog identity always agrees with the live catalog rebuilt
    at adoption time.  When omitted, ``journey.revision`` is used
    (backward compatible).

    This is a pure function with no I/O of its own: it reads from the
    journey's framing, synopsis_import, and the optional search snapshot.
    Round-1 corpus analysis evidence enters through an injected read-only
    reader or prebuilt entries (see
    ``medical_writing_authoring_prefill_corpus_bridge``).

    Parameters
    ----------
    journey
        The current authoring journey.
    snapshot
        Optional ClinicalTrials.gov search snapshot.  When provided, each
        candidate's explicit fields become ``competitor_observation`` entries.
    corpus_analysis_reader
        Optional read-only ``(project_id, analysis_id) -> row dict | None``
        callable.  When the journey is bound to a round-1 corpus analysis,
        the bridge loads, verifies (project / pipeline / snapshot / analysis
        id / frozen route / output hash) and converts its eligible source
        bindings into immutable ``competitor_observation`` entries.  A bound
        journey without a reader fails closed.
    corpus_entries
        Optional prebuilt corpus catalog entries (adopted directly after a
        catalog-id consistency check).  Mutually exclusive with
        ``corpus_analysis_reader``.
    corpus_source_reader
        Optional read-only ``(project_id, source_id, span_id) -> composite
        dict | None`` callable.  When the reader path loads a bound
        round-1 analysis, every persisted evidence binding is verified
        against the immutable source span/document artifact; a bound
        journey without a source reader fails closed.

    Returns
    -------
    AuthoringPrefillEvidenceCatalog
        A fully validated, hash-stable catalog.
    """
    from .medical_writing_authoring_prefill_corpus_bridge import (
        CorpusPrefillBridgeError,
        bound_round1_analysis_identity,
        build_corpus_analysis_entries,
        load_bound_round1_analysis,
    )

    if corpus_entries is not None and corpus_analysis_reader is not None:
        raise CorpusPrefillBridgeError(
            "corpus_entries and corpus_analysis_reader are mutually exclusive"
        )
    snapshot_id = snapshot.snapshot_id if snapshot is not None else ""
    # Build the catalog against the next persisted journey revision when an
    # override is provided (generation path); otherwise the journey revision.
    effective_revision = (
        journey.revision if journey_revision is None else journey_revision
    )
    catalog_id = _catalog_id(
        journey.project_id,
        effective_revision,
        snapshot_id,
    )

    truncation_notes: List[str] = []
    entries: List[AuthoringPrefillEvidenceCatalogEntry] = []

    # 1. Project facts from framing
    entries.extend(
        _collect_framing_facts(catalog_id, journey.framing, truncation_notes)
    )

    # 2. Confirmed synopsis spans
    entries.extend(
        _collect_synopsis_entries(
            catalog_id,
            journey.synopsis_import,
            truncation_notes,
        )
    )

    # 3. CT.gov snapshot competitor observations
    if snapshot is not None:
        entries.extend(
            _collect_ctgov_entries(catalog_id, snapshot, truncation_notes)
        )

    # 4. Round-1 corpus analysis evidence (read-only bridge, fail closed)
    if corpus_entries is not None:
        for entry in corpus_entries:
            if entry.catalog_id != catalog_id:
                raise CorpusPrefillBridgeError(
                    "prebuilt corpus entry catalog_id mismatch: expected "
                    f"{catalog_id}, got {entry.catalog_id}"
                )
        entries.extend(list(corpus_entries))
    elif corpus_analysis_reader is not None:
        # A bound journey needs the read-only source reader too: admitting
        # corpus entries whose source spans/artifacts cannot be verified
        # would silently drop the integrity gate.  Fail closed instead.
        if (
            bound_round1_analysis_identity(journey) is not None
            and not callable(corpus_source_reader)
        ):
            raise CorpusPrefillBridgeError(
                "journey is bound to a round-1 corpus analysis but the "
                "catalog was built without corpus_source_reader; fail closed"
            )
        verified = load_bound_round1_analysis(
            journey,
            corpus_analysis_reader,
            source_reader=corpus_source_reader,
        )
        if verified is not None:
            entries.extend(
                build_corpus_analysis_entries(
                    verified.analysis_row,
                    catalog_id,
                    truncation_notes,
                )
            )
    else:
        # No corpus source configured: a journey that is bound to a round-1
        # analysis must fail closed instead of silently dropping the
        # persisted, source-bound analysis evidence.
        if bound_round1_analysis_identity(journey) is not None:
            raise CorpusPrefillBridgeError(
                "journey is bound to a round-1 corpus analysis but the "
                "catalog was built without corpus_analysis_reader or "
                "corpus_entries; fail closed"
            )

    # Sort entries for stable ordering:
    #   1. project_fact entries first (by source_id)
    #   2. synopsis entries next (by source_id, locator)
    #   3. ctgov_snapshot entries last (by source_id, locator)
    def _sort_key(entry: AuthoringPrefillEvidenceCatalogEntry) -> Tuple[int, str, str]:
        kind_order = {
            "project_fact": 0,
            "synopsis": 1,
            "ctgov_snapshot": 2,
            "registered_source": 3,
            "evidence_brief": 4,
        }
        return (
            kind_order.get(entry.source_kind, 99),
            entry.source_id,
            entry.locator,
        )

    entries.sort(key=_sort_key)

    catalog_sha = _catalog_sha256(
        journey.project_id,
        effective_revision,
        snapshot_id,
        entries,
    )

    return AuthoringPrefillEvidenceCatalog(
        catalog_id=catalog_id,
        project_id=journey.project_id,
        journey_revision=effective_revision,
        snapshot_id=snapshot_id,
        entries=entries,
        catalog_sha256=catalog_sha,
        truncation_notes=truncation_notes,
    )
