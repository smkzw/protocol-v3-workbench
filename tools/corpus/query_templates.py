"""Data-configurable retrieval query combination templates.

The strategy vocabulary below (molecule-class words, route words) is GENERIC
mechanism vocabulary shared by every project; specific drug names, target
names and disease names enter only as runtime ProjectProfile values, never as
code literals (03_WRITING_SYSTEM: 禁止在代码里加适应症分支).

Each template is data: ``strategy_id``, ``description``, ``cond`` (None or the
``"indication"`` sentinel), ``content_parts`` (the part(s) that must resolve
from the profile or the strategy is skipped), and ``term_parts`` (the query
expression parts). Callers may override the whole template list via
``build_strategies(profile, templates=...)`` — e.g. loaded from a JSON config
file — without touching this module.

First-version combination set (per WP-M2-CORPUS / Ponytail: 3–5 strategies):
1. same_target        — target tokens, phase-matched, interventional, industry
2. same_class_route   — molecule-type AND route vocabulary, phase-matched, ...
3. same_indication    — query.cond = indication, phase-matched, ...
4. same_drug          — intervention-name search for the profile drug
                        (B12 lesson: same-drug registered studies must never
                        be auto-excluded, so they are always retrieved)
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

CTGOV_API_ROOT = "https://clinicaltrials.gov/api/v2"

# Field list proven: live-validated against the API v2 /studies endpoint and
# consistent with services/api/app/writing_reference.py CTGOV_DISCOVERY_FIELDS.
RETRIEVAL_FIELDS = (
    "NCTId,BriefTitle,OfficialTitle,BriefSummary,Condition,Phase,StudyType,"
    "InterventionName,InterventionType,LeadSponsorName,LeadSponsorClass,"
    "OverallStatus,StartDate,StudyFirstPostDate,PrimaryCompletionDate,"
    "EnrollmentCount,LargeDoc"
)

# ProjectProfile.phase ("II"|"III") → ClinicalTrials.gov registry expression.
PHASE_REGISTRY = {"I": "PHASE1", "II": "PHASE2", "III": "PHASE3", "IV": "PHASE4"}

# Generic mechanism vocabulary (data, not case words). Extendable by config.
MOLECULE_TYPE_VOCAB: dict[str, list[str]] = {
    "antibody": ["monoclonal antibody", "antibody"],
    "small_molecule": ["small molecule"],
    "peptide": ["peptide"],
    "aso": ["antisense oligonucleotide"],
    "sirna": ["small interfering rna", "sirna"],
    "other": [],
}

ROUTE_VOCAB: dict[str, list[str]] = {
    "oral": ["oral"],
    "iv": ["intravenous"],
    "sc": ["subcutaneous"],
    "im": ["intramuscular"],
    "topical": ["topical"],
    "inhalation": ["inhalation"],
    "other": [],
}

DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "strategy_id": "same_target",
        "priority_hint": "same_target",
        "description": "target tokens, cross-indication, phase-matched, "
        "interventional, industry-sponsored",
        "cond": None,
        "content_parts": ["target_terms"],
        "term_parts": ["phase", "interventional", "industry", "target_terms"],
    },
    {
        "strategy_id": "same_class_route",
        "priority_hint": "same_class_route",
        "description": "molecule-type AND route vocabulary, phase-matched, "
        "interventional, industry-sponsored",
        "cond": None,
        "content_parts": ["class_route_terms"],
        "term_parts": ["phase", "interventional", "industry", "class_route_terms"],
    },
    {
        "strategy_id": "same_indication",
        "priority_hint": "same_indication",
        "description": "query.cond = indication, phase-matched, interventional, "
        "industry-sponsored",
        "cond": "indication",
        "content_parts": [],
        "term_parts": ["phase", "interventional", "industry"],
    },
    {
        "strategy_id": "same_drug",
        "priority_hint": "same_drug",
        "description": "intervention-name search for the profile drug "
        "(B12: same-drug studies are always retrieved, never auto-excluded)",
        "cond": None,
        "content_parts": ["drug_name"],
        "term_parts": ["interventional", "drug_name"],
    },
]

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# Optional deterministic zh→en indication alias + English-phrase extraction,
# reused from the existing services layer (import only; not modified).
try:  # pragma: no cover - exercised implicitly via online runs
    from services.api.app.medical_writing_condition_term_resolver import (  # noqa: E402
        resolve_clinicaltrials_condition_term as _resolver_resolve,
    )
except Exception:  # pragma: no cover - services not importable (standalone use)
    _resolver_resolve = None


def normalize_text(value: object) -> str:
    """Lowercase; keep [0-9a-z] and CJK; everything else becomes a space."""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", str(value or "").lower()).strip()


def phrase_variants(phrase: object) -> list[str]:
    """Deterministic match variants for a free phrase: normalized form plus
    space-collapsed form (e.g. ``il-23`` → ``il 23`` / ``il23``)."""
    norm = normalize_text(phrase)
    if not norm:
        return []
    variants = {norm, norm.replace(" ", "")}
    return sorted(variants)


def _contains_cjk(value: str) -> bool:
    return bool(_CJK_RE.search(value or ""))


def _quote(value: str) -> str:
    escaped = value.replace('"', " ")
    return f'"{escaped}"'


def _or_group(values: list[str]) -> str:
    return "(" + " OR ".join(_quote(v) for v in values) + ")"


def target_query_terms(profile: dict) -> list[str]:
    """Original + normalized variants of the profile target (order stable)."""
    raw = str(profile.get("target") or "").strip()
    if not raw:
        return []
    terms = [raw]
    for variant in phrase_variants(raw):
        if variant not in terms:
            terms.append(variant)
    return terms


def indication_search_terms(profile: dict) -> list[str]:
    """All indication search terms for the profile, ordered:
    raw first (for metadata matching), then the deterministic resolver's
    English variant, then any explicit ``search_terms.indication`` overrides.
    Data-driven only — no code branches on specific indications.
    """
    raw = str(profile.get("indication") or "").strip()
    terms: list[str] = []
    if raw:
        terms.append(raw)
        if _resolver_resolve is not None and _contains_cjk(raw):
            try:
                resolved, _source = _resolver_resolve(indication=raw)
            except Exception:
                resolved = None
            resolved = str(resolved or "").strip()
            if resolved and resolved.casefold() != raw.casefold():
                terms.append(resolved)
    for override in (profile.get("search_terms") or {}).get("indication") or []:
        text = str(override or "").strip()
        if text:
            terms.append(text)
    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(term)
    return unique


def indication_cond_term(profile: dict) -> str | None:
    """First indication term usable as ClinicalTrials.gov ``query.cond``
    (ASCII, no expression-reserved syntax), or None."""
    for term in indication_search_terms(profile):
        if _contains_cjk(term):
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9' \-]*", term):
            continue
        return term
    return None


def _class_route_groups(profile: dict) -> list[str]:
    molecule_key = str(profile.get("molecule_type") or "").strip().lower()
    route_key = str(profile.get("route") or "").strip().lower()
    groups: list[str] = []
    class_terms = MOLECULE_TYPE_VOCAB.get(molecule_key) or []
    route_terms = ROUTE_VOCAB.get(route_key) or []
    if class_terms:
        groups.append(_or_group(class_terms))
    if route_terms:
        groups.append(_or_group(route_terms))
    return groups


def build_strategies(
    profile: dict, templates: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Resolve templates + ProjectProfile into concrete retrieval strategies.

    Returns one record per template; unresolvable strategies are returned with
    ``skipped=True`` and a ``skip_reason`` so the gap is visible in output
    rather than silently dropped.
    """
    effective = templates if templates is not None else DEFAULT_TEMPLATES
    phase_registry = PHASE_REGISTRY.get(str(profile.get("phase") or "").strip().upper())
    target_terms = target_query_terms(profile)
    cond_term = indication_cond_term(profile)
    drug_name = str(profile.get("drug_name") or "").strip()
    class_route_groups = _class_route_groups(profile)

    strategies: list[dict[str, Any]] = []
    for template in effective:
        strategy = {
            "strategy_id": str(template.get("strategy_id") or "").strip(),
            "priority_hint": str(template.get("priority_hint") or ""),
            "description": str(template.get("description") or ""),
            "cond": None,
            "term_expr": "",
            "skipped": False,
            "skip_reason": None,
        }
        parts: list[str] = []
        missing_content = False
        for part in template.get("term_parts") or []:
            if part == "phase":
                if phase_registry:
                    parts.append(f"AREA[Phase]{phase_registry}")
            elif part == "interventional":
                parts.append("AREA[StudyType]INTERVENTIONAL")
            elif part == "industry":
                parts.append("AREA[LeadSponsorClass]INDUSTRY")
            elif part == "target_terms":
                if target_terms:
                    parts.append(_or_group(target_terms))
            elif part == "class_route_terms":
                parts.extend(class_route_groups)
            elif part == "drug_name":
                if drug_name:
                    parts.append(f'AREA[InterventionName]{_quote(drug_name)}')
        cond_mode = template.get("cond")
        if cond_mode == "indication":
            if cond_term:
                strategy["cond"] = cond_term
            elif "indication" in (template.get("content_parts") or []):
                missing_content = True

        # Content-bearing parts missing → strategy skipped with reason.
        for content_part in template.get("content_parts") or []:
            if content_part == "target_terms" and not target_terms:
                strategy["skipped"] = True
                strategy["skip_reason"] = "profile.target missing"
            elif content_part == "class_route_terms" and not class_route_groups:
                strategy["skipped"] = True
                strategy["skip_reason"] = (
                    "molecule_type/route have no search vocabulary entries"
                )
            elif content_part == "drug_name" and not drug_name:
                strategy["skipped"] = True
                strategy["skip_reason"] = "profile.drug_name missing"
        if missing_content and not strategy["skipped"]:
            strategy["skipped"] = True
            strategy["skip_reason"] = (
                "indication term not usable for query.cond (no English variant)"
            )
        if not strategy["skipped"] and not parts and not strategy["cond"]:
            strategy["skipped"] = True
            strategy["skip_reason"] = "template resolves to an empty query"
        strategy["term_expr"] = " AND ".join(f"({p})" for p in parts)
        strategies.append(strategy)
    return strategies


def build_query_url(
    strategy: dict,
    page_size: int = 25,
    page_token: str | None = None,
) -> str:
    """Build the ClinicalTrials.gov API v2 ``/studies`` URL for a strategy."""
    if strategy.get("skipped"):
        raise ValueError(f"strategy {strategy.get('strategy_id')} is skipped")
    params: dict[str, str] = {
        "pageSize": str(int(page_size)),
        "format": "json",
        "countTotal": "true",
        "fields": RETRIEVAL_FIELDS,
    }
    if strategy.get("cond"):
        params["query.cond"] = strategy["cond"]
    if strategy.get("term_expr"):
        params["query.term"] = strategy["term_expr"]
    token = page_token or strategy.get("page_token")
    if token:
        params["pageToken"] = str(token)
    return f"{CTGOV_API_ROOT}/studies?{urlencode(params)}"
