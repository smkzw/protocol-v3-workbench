"""Competitor study classification, priority scoring and CompetitorSet output.

Rules (plans/mw_reboot_20261017/02_ARCHITECTURE + 03_WRITING_SYSTEM §竞品语料):
- Category precedence: same_target > same_class_route > same_indication > adjacent.
- Score bonuses: recency (新近), Phase III registration study (Ⅲ期注册),
  protocol/SAP file availability (有方案文件).
- B12 lesson: a registered study of the profile's OWN drug must never be
  auto-excluded — same-drug studies are always kept and get an explicit bonus.

Classification is deterministic and metadata-only (title / brief summary /
interventions / conditions); every inferred category carries a confidence so
uncertain keyword inference is visible to the user who confirms the TopK.
No specific drug, target or disease names live in this module.

Run:
  python3 tools/corpus/classify_rank.py --retrieved retrieved.json \
      --profile profile.json --out competitor_set.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:  # package-style import
    from . import query_templates
except ImportError:  # script-style import
    import query_templates

# Category precedence, highest first (02_ARCHITECTURE).
CATEGORY_PRECEDENCE: list[str] = [
    "same_target",
    "same_class_route",
    "same_indication",
    "adjacent",
]
CATEGORY_BASE_SCORES: dict[str, float] = {
    "same_target": 50.0,
    "same_class_route": 40.0,
    "same_indication": 30.0,
    "adjacent": 10.0,
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
SOURCE_LEVELS = {"ct_gov", "pubmed", "user_upload"}

SAME_DRUG_BONUS = 15.0
RECENCY_5Y_BONUS = 10.0
RECENCY_10Y_BONUS = 5.0
PHASE3_BONUS = 10.0
PROTOCOL_FILE_BONUS = 10.0
SAP_FILE_BONUS = 3.0

_SCHEMA_STUDY_FIELDS = (
    "study_key",
    "title",
    "phase",
    "has_protocol_file",
    "source",
    "category",
    "priority_score",
    "priority_reasons",
)


def _norm(value: object) -> str:
    return query_templates.normalize_text(value)


def _padded(text: str) -> str:
    return f" {text} "


def _hits(variants: list[str], normalized_text: str) -> list[str]:
    padded = _padded(normalized_text)
    return [v for v in variants if f" {v} " in padded or _padded(v) == padded]


def _bag(value: object) -> tuple[str, ...]:
    """Word bag of a phrase — token-order-insensitive representation."""
    return tuple(sorted(_norm(value).split()))


_PAREN_RE = re.compile(r"\([^)]*\)")


def _condition_bag(value: object) -> tuple[str, ...]:
    """Word bag for condition/indication terms: parenthetical content
    (usually abbreviations, e.g. "(RA)") is dropped before bagging, and
    token order is ignored (CT.gov uses MeSH inversions)."""
    return _bag(_PAREN_RE.sub(" ", str(value or "")))


def _resource_text(candidate: dict) -> str:
    """title + brief summary + intervention names, normalized (one haystack)."""
    interventions = " ".join(
        str(item.get("name") or "") for item in candidate.get("interventions") or []
    )
    return _norm(
        f"{candidate.get('title') or ''} {candidate.get('brief_summary') or ''} {interventions}"
    )


def _title_intervention_text(candidate: dict) -> str:
    interventions = " ".join(
        str(item.get("name") or "") for item in candidate.get("interventions") or []
    )
    return _norm(f"{candidate.get('title') or ''} {interventions}")


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def classify(candidate: dict, profile: dict) -> dict:
    """Assign category + confidence from study metadata (deterministic).

    Returns {"category", "confidence", "same_drug", "evidence"}.
    Positive keyword inference on titles/summary alone is capped at
    ``medium``; only condition-list (indication) and title/intervention-name
    (target) hits earn ``high``. ``adjacent`` means nothing matched — marked
    ``medium`` because keyword absence can be a vocabulary gap, not proof.
    """
    searchable = _resource_text(candidate)
    strong_text = _title_intervention_text(candidate)
    evidence: dict[str, Any] = {}

    # 1. same_target — profile target tokens in title/interventions (high)
    #    or brief summary (medium).
    target_terms = query_templates.target_query_terms(profile)
    target_variants: list[str] = []
    for term in target_terms:
        target_variants.extend(v for v in query_templates.phrase_variants(term))
    category = None
    confidence = "medium"
    if target_variants:
        strong_hits = _hits(target_variants, strong_text)
        summary_hits = _hits(target_variants, searchable)
        evidence["target_hits"] = strong_hits or summary_hits
        if strong_hits:
            category, confidence = "same_target", "high"
        elif summary_hits:
            category, confidence = "same_target", "medium"

    # 2. same_class_route — generic molecule-type AND route vocabulary
    #    (always inference → confidence capped at medium).
    molecule_key = str(profile.get("molecule_type") or "").strip().lower()
    route_key = str(profile.get("route") or "").strip().lower()
    class_variants: list[str] = []
    for term in query_templates.MOLECULE_TYPE_VOCAB.get(molecule_key) or []:
        class_variants.extend(query_templates.phrase_variants(term))
    route_variants: list[str] = []
    for term in query_templates.ROUTE_VOCAB.get(route_key) or []:
        route_variants.extend(query_templates.phrase_variants(term))
    class_hits = _hits(class_variants, searchable) if class_variants else []
    route_hits = _hits(route_variants, searchable) if route_variants else []
    evidence["class_hits"] = class_hits
    evidence["route_hits"] = route_hits
    if category is None and class_hits and route_hits:
        category, confidence = "same_class_route", "medium"

    # 3. same_indication — indication terms (raw + resolver English +
    #    search_terms overrides) vs condition list (high) or title/summary
    #    (medium). Condition matching is word-order-insensitive: CT.gov
    #    conditions use MeSH inversions ("HeadTerm, Qualifier").
    indication_variants: list[str] = []
    for term in query_templates.indication_search_terms(profile):
        indication_variants.extend(query_templates.phrase_variants(term))
    condition_bags = {_condition_bag(item) for item in candidate.get("conditions") or []}
    indication_hits: list[str] = []
    if indication_variants:
        for term in query_templates.indication_search_terms(profile):
            if _condition_bag(term) in condition_bags:
                indication_hits.append(_norm(term))
        if indication_hits:
            if category is None:
                category, confidence = "same_indication", "high"
            evidence["indication_hits"] = indication_hits
        else:
            indication_hits = _hits(indication_variants, searchable)
            if indication_hits:
                if category is None:
                    category, confidence = "same_indication", "medium"
                evidence["indication_hits"] = indication_hits

    # 4. adjacent — nothing above matched (keyword absence ≠ proof → medium).
    if category is None:
        category, confidence = "adjacent", "medium"

    # same_drug flag (orthogonal to category; B12: never auto-excluded).
    drug_variants: list[str] = []
    drug_name = str(profile.get("drug_name") or "").strip()
    if drug_name:
        drug_variants.extend(query_templates.phrase_variants(drug_name))
    drug_hits = _hits(drug_variants, searchable) if drug_variants else []
    evidence["drug_hits"] = drug_hits

    return {
        "category": category,
        "confidence": confidence,
        "same_drug": bool(drug_hits),
        "evidence": evidence,
    }


def score(
    candidate: dict,
    verdict: dict,
    profile: dict,
    now: date | None = None,
) -> tuple[float, list[str]]:
    """Priority score 0–100 with machine-readable reason codes."""
    now = now or date.today()
    category = verdict.get("category") or "adjacent"
    total = CATEGORY_BASE_SCORES.get(category, 0.0)
    reasons = [f"category:{category}:+{total:g}"]

    if verdict.get("same_drug"):
        total += SAME_DRUG_BONUS
        reasons.append(
            f"same_drug:+{SAME_DRUG_BONUS:g} (B12: same-drug study retained, never auto-excluded)"
        )

    start = _parse_date(candidate.get("start_date")) or _parse_date(
        candidate.get("first_posted")
    )
    if start is not None:
        years = (now - start).days / 365.25
        if 0 <= years <= 5:
            total += RECENCY_5Y_BONUS
            reasons.append(f"recency:{years:.1f}y:+{RECENCY_5Y_BONUS:g}")
        elif 0 < years <= 10:
            total += RECENCY_10Y_BONUS
            reasons.append(f"recency:{years:.1f}y:+{RECENCY_10Y_BONUS:g}")

    phases = {str(p).strip().upper() for p in candidate.get("phases") or []}
    if "PHASE3" in phases or candidate.get("phase") == "III":
        total += PHASE3_BONUS
        reasons.append(f"phase3_registration:+{PHASE3_BONUS:g}")

    if candidate.get("has_protocol_file"):
        total += PROTOCOL_FILE_BONUS
        reasons.append(f"protocol_file:+{PROTOCOL_FILE_BONUS:g}")
    if candidate.get("has_sap_file"):
        total += SAP_FILE_BONUS
        reasons.append(f"sap_file:+{SAP_FILE_BONUS:g}")

    total = max(0.0, min(100.0, total))
    return round(total, 1), reasons


def _profile_hash(profile: dict) -> str:
    canonical = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:10]


def _slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_-]+", "-", value).strip("-")
    return slug


def build_competitor_set(
    retrieved: dict,
    profile: dict,
    project_key: str | None = None,
    now: date | None = None,
) -> dict:
    """Retrieval envelope + ProjectProfile → CompetitorSet (eval/SCHEMAS.md §2).

    Additive extensions (schema migrations only add): per-study
    ``category_confidence`` and set-level ``retrieval_mode``/``generated_at``.
    ``confirmed_topk`` stays empty until the user confirms.
    """
    now = now or date.today()
    digest = _profile_hash(profile)
    key = project_key or _slug(str(profile.get("drug_name") or "")) or ""
    if len(key) < 2:
        key = f"profile_{digest}"
    studies: list[dict] = []
    for candidate in retrieved.get("candidates") or []:
        verdict = classify(candidate, profile)
        priority_score, reasons = score(candidate, verdict, profile, now)
        studies.append(
            {
                "study_key": str(candidate.get("study_key") or ""),
                "title": str(candidate.get("title") or ""),
                "phase": str(candidate.get("phase") or ""),
                "has_protocol_file": bool(candidate.get("has_protocol_file")),
                "source": str(candidate.get("source") or "ct_gov"),
                "category": verdict["category"],
                "priority_score": priority_score,
                "priority_reasons": reasons,
                "category_confidence": verdict["confidence"],
            }
        )
    studies.sort(key=lambda item: (-item["priority_score"], item["study_key"]))
    mode = retrieved.get("retrieval_mode") or (
        "offline_fixture" if retrieved.get("degraded_to_offline") else "online"
    )
    return {
        "set_id": f"cs_{key}_{digest}",
        "project_key": key,
        "studies": studies,
        "confirmed_topk": [],
        "retrieval_mode": str(mode),
        "generated_at": now.isoformat(),
    }


def validate_competitor_set(competitor_set: dict) -> list[str]:
    """Schema conformance check (eval/SCHEMAS.md §2). Returns error strings."""
    errors: list[str] = []
    if not isinstance(competitor_set, dict):
        return ["competitor_set is not an object"]
    for field in ("set_id", "project_key"):
        if not str(competitor_set.get(field) or "").strip():
            errors.append(f"missing/empty {field}")
    studies = competitor_set.get("studies")
    if not isinstance(studies, list):
        errors.append("studies is not a list")
        return errors
    keys_seen: set[str] = set()
    for index, study in enumerate(studies):
        label = f"studies[{index}]"
        if not isinstance(study, dict):
            errors.append(f"{label} is not an object")
            continue
        for field in _SCHEMA_STUDY_FIELDS:
            if field not in study:
                errors.append(f"{label} missing {field}")
        key = str(study.get("study_key") or "")
        if not key:
            errors.append(f"{label} empty study_key")
        elif key in keys_seen:
            errors.append(f"{label} duplicate study_key {key}")
        keys_seen.add(key)
        if study.get("category") not in CATEGORY_PRECEDENCE:
            errors.append(f"{label} invalid category {study.get('category')!r}")
        if study.get("source") not in SOURCE_LEVELS:
            errors.append(f"{label} invalid source {study.get('source')!r}")
        if study.get("category_confidence") not in CONFIDENCE_LEVELS:
            errors.append(
                f"{label} invalid category_confidence {study.get('category_confidence')!r}"
            )
        score_value = study.get("priority_score")
        if not isinstance(score_value, (int, float)) or isinstance(score_value, bool):
            errors.append(f"{label} priority_score not a number")
        elif not 0.0 <= float(score_value) <= 100.0:
            errors.append(f"{label} priority_score out of range: {score_value}")
        if not isinstance(study.get("priority_reasons"), list) or not all(
            isinstance(r, str) for r in study.get("priority_reasons") or []
        ):
            errors.append(f"{label} priority_reasons not a list of strings")
        if not isinstance(study.get("has_protocol_file"), bool):
            errors.append(f"{label} has_protocol_file not a boolean")
    topk = competitor_set.get("confirmed_topk")
    if not isinstance(topk, list) or not all(isinstance(k, str) for k in topk):
        errors.append("confirmed_topk is not a list of strings")
    else:
        for key in topk:
            if key not in keys_seen:
                errors.append(f"confirmed_topk references unknown study_key {key}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="classify + rank retrieved studies into a CompetitorSet"
    )
    parser.add_argument("--retrieved", required=True,
                        help="path to retrieved.json (retrieve.py output)")
    profile_source = parser.add_mutually_exclusive_group(required=True)
    profile_source.add_argument("--profile-json", help="ProjectProfile as inline JSON")
    profile_source.add_argument("--profile", help="path to ProjectProfile JSON file")
    profile_source.add_argument("--profile-stdin", action="store_true",
                                help="read ProjectProfile JSON from stdin")
    parser.add_argument("--out", help="output JSON path (default: stdout)")
    parser.add_argument("--project-key", help="override the derived project key")
    args = parser.parse_args(argv)

    retrieved = json.loads(Path(args.retrieved).read_text(encoding="utf-8"))
    if args.profile_json:
        profile = json.loads(args.profile_json)
    elif args.profile:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    else:
        profile = json.loads(sys.stdin.read())

    competitor_set = build_competitor_set(retrieved, profile, project_key=args.project_key)
    errors = validate_competitor_set(competitor_set)
    if errors:
        print("CompetitorSet schema violations:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    payload = json.dumps(competitor_set, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(
            f"competitor_set: studies={len(competitor_set['studies'])} → {args.out}",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
