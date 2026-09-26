"""G6 discovery shortlist selector — deterministic, metadata-only.

Scope (0926V1 §8, 0927V1 §7 / A21 / A601–A610):

* Relevance triage (direct competitor / indirect reference / excluded) is an
  upstream authority — AI-assisted and user-confirmed as a discovery basket.
  This module NEVER re-adjudicates relevance. It takes the triage outcome as
  an explicit input and performs the distinct deep-read shortlist selection
  over registry metadata alone.
* Zero real models, zero network, zero downloads (A16/A21): the selector is a
  pure function of its inputs. Runs on ~600 registry metadata entries without
  waiting for the 574-entry translation debt (A21).
* Default 25 distinct studies, usually 20–30, hard cap 30. When the qualified
  pool is within the cap it is kept in full — no padding, no extra deletion
  (A602). Trimming only happens above the cap and is diversity-aware.
* Ranking follows clinical comparability (population, purpose, phase, drug
  technology/route, mechanism, endpoints, comparator, treatment duration).
  Among comparables, recency / preferred-region centres / verifiable approval
  linkage act only as tiebreakers — a newer but less comparable study never
  outranks an older highly comparable one by a raw total (A605).
* Unknown is not mismatch (A604): a dimension without explicit registry
  evidence is ``unknown`` and contributes nothing to comparability; only
  explicit contrary evidence is ``mismatched`` and is reported as a
  difference. Unknown dimensions are reported separately from mismatches.
* Same-study re-registrations collapse into one slot with an explainable
  representative choice (A603); different studies never merge.
* Protocol-only document plans: standalone SAP/ICF are never downloaded
  (A607); a merged protocol+SAP document is admitted as the complete
  Protocol version with protocol-only corpus admission enforced downstream
  (A608).
* Study counts, file counts and fragment counts are reported separately
  (A609); fragment counts are unknowable from metadata and stay ``None``
  until ingestion.
* Out-of-scope studies keep their history in the proposal groups and bind no
  expensive tasks: the frozen-scope hint contains selected studies only
  (A610, A601).
* Whole-group adoption + individual replacement (A606): the proposal carries
  a stable hash for whole-group confirmation; :func:`apply_replacement`
  derives a new version without per-item confirmation cards.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import date
from hashlib import sha256
from typing import Any, Mapping, Sequence

__all__ = [
    "DEFAULT_TARGET_STUDY_COUNT",
    "MAX_SHORTLIST_STUDY_COUNT",
    "MIN_TARGET_STUDY_COUNT",
    "DimensionStatus",
    "ShortlistEntry",
    "ShortlistProjectFacts",
    "ShortlistProposal",
    "ShortlistSelectorError",
    "apply_replacement",
    "select_shortlist",
]


DEFAULT_TARGET_STUDY_COUNT = 25
MIN_TARGET_STUDY_COUNT = 20
MAX_SHORTLIST_STUDY_COUNT = 30

# Relevance triage statuses that form the eligible pool. Anything else triage
# explicitly decided is out of scope; anything triage has not decided is
# ``unknown_triage`` — never silently selected.
ELIGIBLE_RELEVANCE_STATUSES = frozenset({"direct_competitor", "indirect_reference"})
EXCLUDED_RELEVANCE_STATUSES = frozenset({"excluded", "not_related", "mismatch"})

# Protocol-only document scope. ``protocol_sap`` is a merged document that
# contains the Protocol; standalone SAP/ICF are never downloaded.
PROTOCOL_DOCUMENT_TYPES = frozenset({"protocol", "protocol_sap"})
STANDALONE_DOCUMENT_TYPES = frozenset({"sap", "icf", "other"})

_PHASE_ALIASES = {
    "1": "PHASE1",
    "2": "PHASE2",
    "3": "PHASE3",
    "4": "PHASE4",
    "I": "PHASE1",
    "II": "PHASE2",
    "III": "PHASE3",
    "IV": "PHASE4",
    "PHASE1": "PHASE1",
    "PHASE2": "PHASE2",
    "PHASE3": "PHASE3",
    "PHASE4": "PHASE4",
    "EARLY_PHASE1": "EARLY_PHASE1",
    "NA": "NA",
    "N/A": "NA",
}

# Explainable weights aligned with the basket triage criteria ordering
# (population, purpose, design, drug/mechanism/endpoint/comparator, then
# route/duration). Unknown contributes zero; only explicit contrary evidence
# is penalised.
_DIMENSION_WEIGHTS = {
    "population": 5,
    "purpose": 4,
    "endpoint_class": 4,
    "design": 3,
    "phase": 3,
    "mechanism": 3,
    "drug_technology": 3,
    "comparator": 3,
    "route": 2,
    "duration": 2,
}

_WEEK_RE = re.compile(r"(\d+)\s*[\-\s]?(?:week|wk)", re.IGNORECASE)
# Registry summaries also state durations as "at week 24" / "week 24".
_WEEK_POST_RE = re.compile(r"weeks?\s*[\-:]?\s*(\d+)", re.IGNORECASE)
_WEEK_CN_RE = re.compile(r"(\d+)\s*周")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")

_STOPWORD_TOKENS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in",
        "is", "of", "on", "or", "that", "the", "this", "to", "with", "will",
        "study", "trial", "patients", "subjects", "participants", "adults",
        "treatment", "treated", "evaluate", "evaluates", "evaluated",
        "efficacy", "safety", "tolerability", "compared", "compare",
    }
)


class ShortlistSelectorError(ValueError):
    """Raised for selector contract violations (bad params / bad inputs)."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stem(token: str) -> str:
    token = token.strip().casefold()
    for suffix in ("ies", "ive", "ion", "ic", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    return token


def _tokens(text: str) -> frozenset[str]:
    # Digits stay inside tokens: registry identifiers ("NCT02181231") and
    # dose/duration figures ("8") carry study identity and must not collapse
    # distinct studies into one duplicate fingerprint.
    return frozenset(
        _stem(tok)
        for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-']*", text or "")
        if tok.casefold() not in _STOPWORD_TOKENS
    )


def _normalize_phase(value: Any) -> str:
    token = str(value or "").strip().upper()
    # Chinese project facts use "II期"/"2期" spellings; strip the 期 suffix
    # and fold CJK numeral variants onto the ClinicalTrials.gov tokens.
    if token.endswith("期"):
        token = token[:-1]
    token = {
        "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV",
        "１": "1", "２": "2", "３": "3", "４": "4",
    }.get(token, token)
    return _PHASE_ALIASES.get(token, token)


def _as_date(value: str) -> date | None:
    match = _ISO_DATE_RE.match(str(value or "").strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _text_of(candidate: Mapping[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in ("brief_title", "official_title", "brief_summary")
    )


def _conditions_of(candidate: Mapping[str, Any]) -> list[str]:
    return [str(item) for item in (candidate.get("conditions") or []) if str(item)]


@dataclass(frozen=True)
class ShortlistProjectFacts:
    """Project-side facts the candidate metadata is compared against.

    Every field is optional; a missing field makes the corresponding
    dimension ``unknown`` for every candidate — it is never guessed
    (A604). ``reference_date`` anchors recency deterministically instead of
    a wall clock; an absent anchor is a contract error, not a fallback.
    """

    condition_terms: tuple[str, ...] = ()
    purpose_keywords: tuple[str, ...] = ()
    design_keywords: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    drug_technology: str = ""
    route_keywords: tuple[str, ...] = ()
    mechanism_keywords: tuple[str, ...] = ()
    endpoint_keywords: tuple[str, ...] = ()
    comparator_keywords: tuple[str, ...] = ()
    treatment_duration_weeks: int | None = None
    preferred_regions: tuple[str, ...] = ()
    reference_date: str = ""

    def facts_payload(self) -> dict[str, Any]:
        return {
            "condition_terms": list(self.condition_terms),
            "purpose_keywords": list(self.purpose_keywords),
            "design_keywords": list(self.design_keywords),
            "phases": [_normalize_phase(p) for p in self.phases],
            "drug_technology": self.drug_technology,
            "route_keywords": list(self.route_keywords),
            "mechanism_keywords": list(self.mechanism_keywords),
            "endpoint_keywords": list(self.endpoint_keywords),
            "comparator_keywords": list(self.comparator_keywords),
            "treatment_duration_weeks": self.treatment_duration_weeks,
            "preferred_regions": list(self.preferred_regions),
            "reference_date": self.reference_date,
        }

    @property
    def facts_hash(self) -> str:
        """Study-facts identity: changed facts create a new scope version."""

        return _payload_hash(self.facts_payload())


class DimensionStatus:
    MATCHED = "matched"
    WEAK = "weak_matched"
    UNKNOWN = "unknown"
    MISMATCHED = "mismatched"


@dataclass(frozen=True)
class CandidateAssessment:
    nct_id: str
    brief_title: str
    dimensions: dict[str, tuple[str, str]]  # dim -> (status, evidence)
    matched_weight: float
    mismatch_penalty: float
    unknown_dimensions: tuple[str, ...]
    mismatched_dimensions: tuple[str, ...]
    recency_date: date | None
    region_matched: bool
    region_known: bool
    approval_linkage: str
    design_cluster: tuple[str, ...]
    duplicate_key: tuple[str, ...]

    @property
    def comparability(self) -> float:
        return self.matched_weight - self.mismatch_penalty

    def sort_key(self, reference: date) -> tuple[Any, ...]:
        # Comparability first (A605); recency / preferred-region / approval
        # linkage only tiebreak among comparables; nct_id keeps the total
        # order deterministic. Unknown recency sorts after known dates so a
        # study cannot claim recency it does not evidence.
        recency_days = (
            (reference - self.recency_date).days
            if self.recency_date is not None
            else 10**9
        )
        return (
            -self.comparability,
            recency_days,
            0 if self.region_matched else 1,
            0 if self.approval_linkage else 1,
            self.nct_id,
        )


def _keyword_dimension(
    dimensions: dict[str, tuple[str, str]],
    name: str,
    keywords: Sequence[str],
    text: str,
    text_tokens: frozenset[str],
) -> None:
    """Matched only on explicit registry evidence; otherwise unknown (A604)."""

    if not keywords:
        dimensions[name] = (DimensionStatus.UNKNOWN, "project facts absent")
        return
    text_lower = text.casefold()
    hits = [kw for kw in keywords if kw.strip().casefold() and kw.strip().casefold() in text_lower]
    token_hits = [kw for kw in keywords if _tokens(kw) and _tokens(kw) <= text_tokens]
    if hits or token_hits:
        dimensions[name] = (
            DimensionStatus.MATCHED,
            "explicit evidence: " + ", ".join(sorted(set(hits or token_hits))[:4]),
        )
    else:
        dimensions[name] = (DimensionStatus.UNKNOWN, "no explicit registry evidence")


def _assess_candidate(
    candidate: Mapping[str, Any], facts: ShortlistProjectFacts
) -> CandidateAssessment:
    nct_id = str(candidate.get("nct_id") or "")
    text = _text_of(candidate)
    text_tokens = _tokens(text)
    dimensions: dict[str, tuple[str, str]] = {}

    # --- population -------------------------------------------------------
    conditions = _conditions_of(candidate)
    fact_terms = [t.casefold() for t in facts.condition_terms if t.strip()]
    fact_token_sets = [_tokens(t) for t in facts.condition_terms if t.strip()]
    best = 0.0
    best_evidence = ""
    if conditions and fact_terms:
        for condition in conditions:
            cond_lower = condition.casefold()
            cond_tokens = _tokens(condition)
            for term, term_tokens in zip(fact_terms, fact_token_sets):
                if term in cond_lower or cond_lower in term:
                    strength = 1.0
                elif cond_tokens and cond_tokens == term_tokens:
                    strength = 1.0
                elif cond_tokens & term_tokens:
                    strength = 0.5
                else:
                    strength = 0.0
                if strength > best:
                    best = strength
                    best_evidence = f"condition '{condition}' ~ term '{term}'"
        if best >= 1.0:
            dimensions["population"] = (DimensionStatus.MATCHED, best_evidence)
        elif best > 0.0:
            dimensions["population"] = (
                DimensionStatus.WEAK,
                f"weak family-token overlap only: {best_evidence}",
            )
        else:
            dimensions["population"] = (
                DimensionStatus.MISMATCHED,
                "no registry condition overlaps the project condition terms: "
                + "; ".join(conditions[:5]),
            )
    elif conditions and not fact_terms:
        dimensions["population"] = (DimensionStatus.UNKNOWN, "project facts carry no condition terms")
    else:
        dimensions["population"] = (DimensionStatus.UNKNOWN, "candidate has no registry conditions")

    # --- keyword dimensions -------------------------------------------------
    _keyword_dimension(dimensions, "purpose", facts.purpose_keywords, text, text_tokens)
    _keyword_dimension(dimensions, "mechanism", facts.mechanism_keywords, text, text_tokens)
    _keyword_dimension(dimensions, "endpoint_class", facts.endpoint_keywords, text, text_tokens)
    _keyword_dimension(dimensions, "comparator", facts.comparator_keywords, text, text_tokens)
    _keyword_dimension(dimensions, "route", facts.route_keywords, text, text_tokens)

    # --- design -----------------------------------------------------------
    design_fields = " ".join(
        [
            str(candidate.get("design_allocation") or ""),
            str(candidate.get("design_masking") or ""),
            str(candidate.get("design_intervention_model") or ""),
        ]
    ).casefold()
    if facts.design_keywords:
        hits = [
            kw
            for kw in facts.design_keywords
            if kw.strip().casefold() and kw.strip().casefold() in design_fields
        ]
        if hits:
            dimensions["design"] = (
                DimensionStatus.MATCHED,
                "explicit design fields: " + ", ".join(sorted(set(hits))[:4]),
            )
        else:
            dimensions["design"] = (DimensionStatus.UNKNOWN, "no explicit design evidence")
    else:
        dimensions["design"] = (DimensionStatus.UNKNOWN, "project facts absent")

    # --- phase ------------------------------------------------------------
    fact_phases = {_normalize_phase(p) for p in facts.phases if _normalize_phase(p)}
    cand_phases = {_normalize_phase(p) for p in (candidate.get("phases") or [])}
    if fact_phases and cand_phases:
        if cand_phases & fact_phases:
            dimensions["phase"] = (
                DimensionStatus.MATCHED,
                f"phases {sorted(cand_phases & fact_phases)}",
            )
        elif cand_phases == {"NA"}:
            dimensions["phase"] = (DimensionStatus.UNKNOWN, "registry phase is NA")
        else:
            dimensions["phase"] = (
                DimensionStatus.MISMATCHED,
                f"registry phases {sorted(cand_phases)} outside project phases {sorted(fact_phases)}",
            )
    else:
        dimensions["phase"] = (DimensionStatus.UNKNOWN, "phase absent on one side")

    # --- drug technology ----------------------------------------------------
    if not facts.drug_technology:
        dimensions["drug_technology"] = (DimensionStatus.UNKNOWN, "project facts absent")
    else:
        interventions = candidate.get("interventions") or []
        types = {
            str(item.get("intervention_type") or "").strip().upper()
            for item in interventions
            if isinstance(item, Mapping)
        }
        types.discard("")
        if types and types.isdisjoint({"DRUG"}):
            dimensions["drug_technology"] = (
                DimensionStatus.MISMATCHED,
                f"registry intervention types {sorted(types)} include no DRUG arm "
                f"while project technology is {facts.drug_technology}",
            )
        else:
            dimensions["drug_technology"] = (
                DimensionStatus.UNKNOWN,
                "registry metadata does not state technology type",
            )

    # --- duration -------------------------------------------------------------
    if facts.treatment_duration_weeks is None:
        dimensions["duration"] = (DimensionStatus.UNKNOWN, "project facts absent")
    else:
        weeks = (
            [int(m) for m in _WEEK_RE.findall(text)]
            + [int(m) for m in _WEEK_POST_RE.findall(text)]
            + [int(m) for m in _WEEK_CN_RE.findall(text)]
        )
        if not weeks:
            dimensions["duration"] = (DimensionStatus.UNKNOWN, "registry text states no duration")
        else:
            candidate_weeks = max(weeks)
            ratio = candidate_weeks / float(facts.treatment_duration_weeks)
            if 0.5 <= ratio <= 2.0:
                dimensions["duration"] = (
                    DimensionStatus.MATCHED,
                    f"registry {candidate_weeks} weeks vs project "
                    f"{facts.treatment_duration_weeks} weeks (same order)",
                )
            else:
                dimensions["duration"] = (
                    DimensionStatus.MISMATCHED,
                    f"registry {candidate_weeks} weeks vs project "
                    f"{facts.treatment_duration_weeks} weeks",
                )

    matched_weight = 0.0
    mismatch_penalty = 0.0
    unknown_dims: list[str] = []
    mismatched_dims: list[str] = []
    for dim, (status, _evidence) in dimensions.items():
        weight = _DIMENSION_WEIGHTS.get(dim, 1)
        if status == DimensionStatus.MATCHED:
            matched_weight += weight
        elif status == DimensionStatus.WEAK:
            matched_weight += weight * 0.5
        elif status == DimensionStatus.MISMATCHED:
            mismatch_penalty += weight
            mismatched_dims.append(dim)
        else:
            unknown_dims.append(dim)

    # --- tiebreakers ----------------------------------------------------------
    recency_date = _as_date(
        candidate.get("last_update_posted") or candidate.get("first_posted") or ""
    )
    locations = [str(x).casefold() for x in (candidate.get("location_countries") or [])]
    preferred = [r.casefold() for r in facts.preferred_regions if r.strip()]
    region_matched = bool(set(locations) & set(preferred))
    approval_linkage = str(candidate.get("approval_evidence") or "")

    phases_cluster = tuple(sorted(cand_phases))
    comparator_class = (
        "placebo"
        if "placebo" in text.casefold()
        else ("active" if "active comparator" in text.casefold() else "unknown")
    )
    design_cluster = (
        phases_cluster,
        str(candidate.get("design_allocation") or "").casefold(),
        str(candidate.get("design_intervention_model") or "").casefold(),
        comparator_class,
    )

    # --- duplicate fingerprint (A603) -------------------------------------------
    title_source = str(candidate.get("official_title") or candidate.get("brief_title") or "")
    intervention_names = tuple(
        sorted(
            {
                _stem(str(item.get("name") or ""))
                for item in (candidate.get("interventions") or [])
                if isinstance(item, Mapping) and item.get("name")
            }
        )
    )
    condition_tokens = tuple(sorted({tok for cond in conditions for tok in _tokens(cond)}))
    duplicate_key = (
        tuple(sorted(_tokens(title_source))),
        intervention_names,
        phases_cluster,
        condition_tokens,
    )

    return CandidateAssessment(
        nct_id=nct_id,
        brief_title=str(candidate.get("brief_title") or ""),
        dimensions=dimensions,
        matched_weight=matched_weight,
        mismatch_penalty=mismatch_penalty,
        unknown_dimensions=tuple(sorted(unknown_dims)),
        mismatched_dimensions=tuple(sorted(mismatched_dims)),
        recency_date=recency_date,
        region_matched=region_matched,
        region_known=bool(locations),
        approval_linkage=approval_linkage,
        design_cluster=design_cluster,
        duplicate_key=duplicate_key,
    )


def _reference_date(facts: ShortlistProjectFacts) -> date:
    parsed = _as_date(facts.reference_date)
    if parsed is None:
        raise ShortlistSelectorError(
            "project facts must carry an explicit reference_date (YYYY-MM-DD) "
            "so recency ranking is deterministic"
        )
    return parsed


def _dedup_by_study(
    assessments: Sequence[CandidateAssessment],
) -> tuple[list[CandidateAssessment], list[dict[str, str]]]:
    """Collapse same-study re-registrations; different studies never merge.

    A duplicate requires the full fingerprint to collide: normalised title
    tokens, intervention names, phases AND condition tokens together.
    """

    by_key: dict[tuple[str, ...], list[CandidateAssessment]] = {}
    for assessment in assessments:
        by_key.setdefault(assessment.duplicate_key, []).append(assessment)
    kept: list[CandidateAssessment] = []
    duplicates: list[dict[str, str]] = []
    for group in by_key.values():
        if len(group) == 1:
            kept.append(group[0])
            continue
        latest = max(
            (a.recency_date for a in group if a.recency_date is not None),
            default=None,
        )
        group_sorted = sorted(
            group,
            key=lambda a: (
                -a.matched_weight,
                -(
                    (latest - a.recency_date).days
                    if a.recency_date and latest
                    else 0
                ),
                a.nct_id,
            ),
        )
        representative = group_sorted[0]
        kept.append(representative)
        for other in group_sorted[1:]:
            duplicates.append(
                {
                    "nct_id": other.nct_id,
                    "duplicate_of": representative.nct_id,
                    "reason": (
                        "same title/interventions/phases/conditions fingerprint; "
                        "representative has stronger metadata evidence or the "
                        "newer record"
                    ),
                }
            )
    duplicates.sort(key=lambda item: item["nct_id"])
    kept.sort(key=lambda a: a.nct_id)
    return kept, duplicates


def _document_plan(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Protocol-only per-study document plan (A607/A608)."""

    documents = [
        doc
        for doc in (candidate.get("public_documents") or [])
        if isinstance(doc, Mapping) and str(doc.get("filename") or "")
    ]

    def _doc_key(doc: Mapping[str, Any]) -> tuple[str, str]:
        return (
            str(doc.get("document_date") or doc.get("upload_date") or ""),
            str(doc.get("document_id") or ""),
        )

    protocol_docs = sorted(
        (
            doc
            for doc in documents
            if str(doc.get("document_type")) in PROTOCOL_DOCUMENT_TYPES
        ),
        key=_doc_key,
        reverse=True,
    )
    standalone = sorted(
        (
            doc
            for doc in documents
            if str(doc.get("document_type")) in STANDALONE_DOCUMENT_TYPES
        ),
        key=_doc_key,
        reverse=True,
    )
    chosen = protocol_docs[0] if protocol_docs else None
    alternates = protocol_docs[1:]
    plan: dict[str, Any] = {
        "nct_id": candidate.get("nct_id"),
        "chosen_document": None,
        "version_choice_reason": "",
        "alternate_versions_not_downloaded": [
            str(doc.get("document_id") or "") for doc in alternates
        ],
        "standalone_documents_not_downloaded": [
            {
                "document_id": str(doc.get("document_id") or ""),
                "document_type": str(doc.get("document_type") or ""),
                "reason": (
                    "standalone non-Protocol document; download calls must "
                    "stay 0 for it (A607)"
                ),
            }
            for doc in standalone
        ],
        "manual_upload_required": chosen is None,
        "planned_download_calls": 1 if chosen is not None else 0,
    }
    if chosen is not None:
        doc_type = str(chosen.get("document_type") or "")
        reason = "latest complete Protocol version by document/upload date"
        if doc_type == "protocol_sap":
            reason += (
                "; merged protocol+SAP document — only reliably located "
                "Protocol portions enter the corpus, protocol-only admission "
                "enforced downstream (A608)"
            )
        plan["chosen_document"] = {
            "document_id": str(chosen.get("document_id") or ""),
            "document_type": doc_type,
            "filename": str(chosen.get("filename") or ""),
            "document_date": str(chosen.get("document_date") or ""),
            "upload_date": str(chosen.get("upload_date") or ""),
            "download_url": str(chosen.get("download_url") or ""),
        }
        plan["version_choice_reason"] = reason
    return plan


@dataclass(frozen=True)
class ShortlistEntry:
    nct_id: str
    brief_title: str
    rank: int
    comparability: float
    matched: dict[str, str]
    differences: dict[str, str]
    unknown_fields: tuple[str, ...]
    tiebreakers: dict[str, Any]
    design_cluster: str
    document_plan: dict[str, Any]
    entry_reason: str = ""


def _scope_entries_for(entries: Sequence[ShortlistEntry]) -> tuple[dict[str, str], ...]:
    """Frozen-scope entries bounded to the given studies only.

    Entry shape mirrors ``writing_reference_preparation_batch._frozen_scope``
    entries so the downstream preparation admission contract stays identical.
    Out-of-scope studies appear nowhere here — they keep history but bind no
    expensive tasks (A601/A610).
    """

    scope_entries: list[dict[str, str]] = []
    for entry in entries:
        plan = entry.document_plan
        chosen = plan.get("chosen_document")
        if chosen:
            scope_entries.append(
                {
                    "item_kind": "public_document",
                    "nct_id": entry.nct_id,
                    "document_id": str(chosen["document_id"]),
                    "document_type": str(chosen["document_type"]),
                    "filename": str(chosen["filename"]),
                    "download_url": str(chosen["download_url"]),
                }
            )
        else:
            scope_entries.append(
                {
                    "item_kind": "study_manual_upload_required",
                    "nct_id": entry.nct_id,
                    "document_id": "",
                    "document_type": "",
                    "filename": "",
                }
            )
    return tuple(scope_entries)


@dataclass(frozen=True)
class ShortlistProposal:
    """Immutable, hash-identified shortlist proposal (whole-group adoption)."""

    version: int
    parent_hash: str
    proposal_hash: str
    snapshot_id: str
    relevance_identity: str
    facts_hash: str
    params: dict[str, Any]
    selected: tuple[ShortlistEntry, ...]
    replacement_pool: tuple[ShortlistEntry, ...]
    excluded_by_triage: tuple[dict[str, str], ...]
    unknown_triage: tuple[dict[str, str], ...]
    duplicates: tuple[dict[str, str], ...]
    counts: dict[str, Any]
    scope_hint: tuple[dict[str, str], ...] = field(default=())
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": "discovery_shortlist_proposal_v1",
            "version": self.version,
            "parent_hash": self.parent_hash,
            "proposal_hash": self.proposal_hash,
            "snapshot_id": self.snapshot_id,
            "relevance_identity": self.relevance_identity,
            "facts_hash": self.facts_hash,
            "params": self.params,
            "selected": [vars(entry) | {} for entry in self.selected],
            "replacement_pool": [vars(entry) | {} for entry in self.replacement_pool],
            "excluded_by_triage": list(self.excluded_by_triage),
            "unknown_triage": list(self.unknown_triage),
            "duplicates": list(self.duplicates),
            "counts": self.counts,
            "scope_hint": list(self.scope_hint),
            "notes": list(self.notes),
        }
        # dataclasses with dicts/tuples serialize fine as plain structures
        return json.loads(_canonical_json(payload))


def _entry_from_assessment(
    assessment: CandidateAssessment,
    candidate: Mapping[str, Any],
    rank: int,
    reference: date,
    entry_reason: str,
) -> ShortlistEntry:
    matched: dict[str, str] = {}
    differences: dict[str, str] = {}
    for dim, (status, evidence) in assessment.dimensions.items():
        if status in (DimensionStatus.MATCHED, DimensionStatus.WEAK):
            matched[dim] = evidence
        elif status == DimensionStatus.MISMATCHED:
            differences[dim] = evidence
    tiebreakers = {
        "recency_date": assessment.recency_date.isoformat()
        if assessment.recency_date
        else "unknown",
        "preferred_region_centre": (
            assessment.region_matched if assessment.region_known else "unknown"
        ),
        "approval_linkage": assessment.approval_linkage or "unknown",
    }
    return ShortlistEntry(
        nct_id=assessment.nct_id,
        brief_title=assessment.brief_title,
        rank=rank,
        comparability=assessment.comparability,
        matched=matched,
        differences=differences,
        unknown_fields=assessment.unknown_dimensions,
        tiebreakers=tiebreakers,
        design_cluster=_payload_hash(assessment.design_cluster)[:12],
        document_plan=_document_plan(candidate),
        entry_reason=entry_reason,
    )


def select_shortlist(
    candidates: Sequence[Mapping[str, Any]],
    facts: ShortlistProjectFacts,
    *,
    relevance: Mapping[str, str] | None = None,
    relevance_identity: str = "",
    snapshot_id: str = "",
    target_size: int = DEFAULT_TARGET_STUDY_COUNT,
) -> ShortlistProposal:
    """Select the 20–30 deep-read shortlist from registry metadata alone.

    ``relevance`` maps nct_id -> triage status (the confirmed basket output).
    When omitted, the candidates' embedded ``relevance_status`` is used.
    Statuses outside the eligible set are reported — explicitly decided
    exclusions under ``excluded_by_triage``, undecided ones under
    ``unknown_triage`` — and are never selected (A604/A610).
    """

    if not (MIN_TARGET_STUDY_COUNT <= target_size <= MAX_SHORTLIST_STUDY_COUNT):
        raise ShortlistSelectorError(
            f"target_size must be within [{MIN_TARGET_STUDY_COUNT}, "
            f"{MAX_SHORTLIST_STUDY_COUNT}], got {target_size}"
        )
    nct_ids = [str(candidate.get("nct_id") or "") for candidate in candidates]
    if len(set(nct_ids)) != len(nct_ids):
        raise ShortlistSelectorError("candidates contain duplicate nct_id entries")

    reference = _reference_date(facts)
    eligible_inputs: list[tuple[Mapping[str, Any], CandidateAssessment]] = []
    excluded_by_triage: list[dict[str, str]] = []
    unknown_triage: list[dict[str, str]] = []
    for candidate, nct_id in zip(candidates, nct_ids):
        status = (
            str(relevance.get(nct_id))
            if relevance is not None
            else str(candidate.get("relevance_status") or "pending_medical_relevance")
        )
        record = {
            "nct_id": nct_id,
            "brief_title": str(candidate.get("brief_title") or ""),
        }
        if status in ELIGIBLE_RELEVANCE_STATUSES:
            eligible_inputs.append((candidate, _assess_candidate(candidate, facts)))
        elif status in EXCLUDED_RELEVANCE_STATUSES:
            excluded_by_triage.append({**record, "relevance_status": status})
        else:
            unknown_triage.append({**record, "relevance_status": status})
    excluded_by_triage.sort(key=lambda item: item["nct_id"])
    unknown_triage.sort(key=lambda item: item["nct_id"])

    deduped, duplicates = _dedup_by_study([assessment for _c, assessment in eligible_inputs])
    candidates_by_nct = dict(zip(nct_ids, candidates))
    ranked = sorted(deduped, key=lambda a: a.sort_key(reference))

    notes: list[str] = []
    if len(ranked) <= MAX_SHORTLIST_STUDY_COUNT:
        # Qualified pool fits under the cap: keep it in full — no padding to
        # the target, no extra deletion (A602).
        chosen = list(ranked)
        pool: list[CandidateAssessment] = []
        notes.append(
            f"qualified pool {len(ranked)} ≤ cap {MAX_SHORTLIST_STUDY_COUNT}: "
            "kept in full (no padding, no extra deletion)"
        )
    else:
        # Diversity-aware trim: round-robin across design clusters, best rank
        # first inside each cluster, until target_size is reached.
        clusters: dict[tuple[str, ...], list[CandidateAssessment]] = {}
        for assessment in ranked:
            clusters.setdefault(assessment.design_cluster, []).append(assessment)
        for members in clusters.values():
            members.sort(key=lambda a: a.sort_key(reference))
        chosen = []
        cluster_order = sorted(clusters)
        depth = 0
        while len(chosen) < target_size:
            progressed = False
            for cluster in cluster_order:
                members = clusters[cluster]
                if depth < len(members):
                    chosen.append(members[depth])
                    progressed = True
                    if len(chosen) >= target_size:
                        break
            if not progressed:
                break
            depth += 1
        chosen_nct = {assessment.nct_id for assessment in chosen}
        pool = [a for a in ranked if a.nct_id not in chosen_nct]
        notes.append(
            f"qualified pool {len(ranked)} > cap {MAX_SHORTLIST_STUDY_COUNT}: "
            f"diversity-aware trim to target {target_size} (round-robin over "
            f"{len(cluster_order)} design clusters); {len(pool)} ranked "
            "replacements kept"
        )

    keep_reason = (
        "kept in full (qualified ≤ cap)"
        if len(ranked) <= MAX_SHORTLIST_STUDY_COUNT
        else "ranked selection with design diversity"
    )
    selected_entries = tuple(
        _entry_from_assessment(
            assessment,
            candidates_by_nct[assessment.nct_id],
            rank,
            reference,
            entry_reason=keep_reason,
        )
        for rank, assessment in enumerate(chosen, start=1)
    )
    pool_entries = tuple(
        _entry_from_assessment(
            assessment,
            candidates_by_nct[assessment.nct_id],
            rank,
            reference,
            entry_reason="ranked replacement candidate",
        )
        for rank, assessment in enumerate(pool, start=len(selected_entries) + 1)
    )

    protocol_files = sum(
        1 for entry in selected_entries if entry.document_plan.get("chosen_document")
    )
    manual_uploads = sum(
        1
        for entry in selected_entries
        if entry.document_plan.get("manual_upload_required")
    )
    standalone_excluded = sum(
        len(entry.document_plan.get("standalone_documents_not_downloaded") or [])
        for entry in selected_entries
    )
    alternates_excluded = sum(
        len(entry.document_plan.get("alternate_versions_not_downloaded") or [])
        for entry in selected_entries
    )
    counts = {
        # A609: study/file/fragment counts are separate numbers. Fragment
        # counts are unknowable from metadata and stay None until ingestion.
        "candidate_count": len(candidates),
        "eligible_studies": len(eligible_inputs),
        "qualified_studies": len(ranked),
        "selected_studies": len(selected_entries),
        "replacement_pool_studies": len(pool_entries),
        "excluded_by_triage_studies": len(excluded_by_triage),
        "unknown_triage_studies": len(unknown_triage),
        "duplicate_studies_collapsed": len(duplicates),
        "protocol_file_count": protocol_files,
        "manual_upload_studies": manual_uploads,
        "standalone_excluded_file_count": standalone_excluded,
        "alternate_version_file_count": alternates_excluded,
        "planned_download_calls": protocol_files,
        "fragment_count": None,
        "fragment_count_basis": (
            "fragment counts exist only after extraction; reported separately "
            "and never merged into study or file counts (A609)"
        ),
    }

    params = {
        "target_size": target_size,
        "max_size": MAX_SHORTLIST_STUDY_COUNT,
        "dimension_weights": dict(_DIMENSION_WEIGHTS),
    }
    proposal_hash = _payload_hash(
        {
            "schema_version": "discovery_shortlist_proposal_v1",
            "snapshot_id": snapshot_id,
            "relevance_identity": relevance_identity,
            "facts_hash": facts.facts_hash,
            "params": params,
            "selected": [entry.nct_id for entry in selected_entries],
            "replacement_pool": [entry.nct_id for entry in pool_entries],
            "excluded_by_triage": [item["nct_id"] for item in excluded_by_triage],
            "unknown_triage": [item["nct_id"] for item in unknown_triage],
            "duplicates": duplicates,
            "counts": counts,
        }
    )

    return ShortlistProposal(
        version=1,
        parent_hash="",
        proposal_hash=proposal_hash,
        snapshot_id=snapshot_id,
        relevance_identity=relevance_identity,
        facts_hash=facts.facts_hash,
        params=params,
        selected=selected_entries,
        replacement_pool=pool_entries,
        excluded_by_triage=tuple(excluded_by_triage),
        unknown_triage=tuple(unknown_triage),
        duplicates=tuple(duplicates),
        counts=counts,
        scope_hint=_scope_entries_for(selected_entries),
        notes=tuple(notes),
    )


def apply_replacement(
    proposal: ShortlistProposal,
    *,
    remove_nct_ids: Sequence[str],
    add_nct_ids: Sequence[str],
) -> ShortlistProposal:
    """Individual replacement on top of whole-group adoption (A606).

    Pure: returns a new proposal version; removals must be selected, adds
    must come from the ranked replacement pool. Rationales travel with the
    entries; the new version links to its parent hash.
    """

    selected = list(proposal.selected)
    pool = list(proposal.replacement_pool)
    selected_nct = {entry.nct_id for entry in selected}
    pool_nct = {entry.nct_id for entry in pool}
    unknown_removals = sorted(set(remove_nct_ids) - selected_nct)
    unknown_adds = sorted(set(add_nct_ids) - pool_nct)
    if unknown_removals or unknown_adds:
        raise ShortlistSelectorError(
            "replacement contract violated — "
            + (f"not selected: {unknown_removals} " if unknown_removals else "")
            + (f"not in replacement pool: {unknown_adds}" if unknown_adds else "")
        )
    removed_entries = [entry for entry in selected if entry.nct_id in set(remove_nct_ids)]
    added_entries = [entry for entry in pool if entry.nct_id in set(add_nct_ids)]
    new_selected = [
        entry for entry in selected if entry.nct_id not in set(remove_nct_ids)
    ] + [
        _dc_replace(entry, entry_reason="individual replacement in")
        for entry in added_entries
    ]
    new_pool = [
        entry for entry in pool if entry.nct_id not in set(add_nct_ids)
    ] + [
        _dc_replace(
            entry,
            entry_reason=f"replaced by individual decision (was rank {entry.rank})",
        )
        for entry in removed_entries
    ]
    ranks = {entry.nct_id: idx for idx, entry in enumerate(new_selected, start=1)}
    new_selected = [_dc_replace(entry, rank=ranks[entry.nct_id]) for entry in new_selected]
    pool_ranks = {
        entry.nct_id: idx
        for idx, entry in enumerate(new_pool, start=len(new_selected) + 1)
    }
    new_pool = [_dc_replace(entry, rank=pool_ranks[entry.nct_id]) for entry in new_pool]

    protocol_files = sum(
        1 for entry in new_selected if entry.document_plan.get("chosen_document")
    )
    manual_uploads = sum(
        1 for entry in new_selected if entry.document_plan.get("manual_upload_required")
    )
    counts = dict(proposal.counts)
    counts.update(
        {
            "selected_studies": len(new_selected),
            "replacement_pool_studies": len(new_pool),
            "protocol_file_count": protocol_files,
            "manual_upload_studies": manual_uploads,
            "planned_download_calls": protocol_files,
        }
    )
    new_hash = _payload_hash(
        {
            "parent_hash": proposal.proposal_hash,
            "selected": [entry.nct_id for entry in new_selected],
            "replacement_pool": [entry.nct_id for entry in new_pool],
            "counts": counts,
        }
    )
    return _dc_replace(
        proposal,
        version=proposal.version + 1,
        parent_hash=proposal.proposal_hash,
        proposal_hash=new_hash,
        selected=tuple(new_selected),
        replacement_pool=tuple(new_pool),
        counts=counts,
        scope_hint=_scope_entries_for(new_selected),
    )
