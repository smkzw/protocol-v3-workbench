"""WP-M2-CORPUS self-test.

Phase 1 (always, offline): exercises classification/ranking logic against the
3 synthetic fixture studies. Asserts the DoD ordering
(same_target score > same_indication score > adjacent score), B12 retention of
same-drug registered studies, CompetitorSet schema conformance, and that the
pipeline modules contain no case-specific words.

Phase 2 (skipped with --offline-only): runs the full
retrieve → classify_rank chain with the contract's synthetic profile and
writes artifacts to runtime/corpus_test/. Degrades to the offline fixture
retrieval automatically when the network is unavailable.

Run: python3 tools/corpus/selftest.py [--offline-only]
Exit code 0 = all checks passed; 1 = at least one failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

try:  # package-style (python3 -m tools.corpus.selftest)
    from . import classify_rank, fixtures, retrieve, query_templates
except ImportError:  # script-style (python3 tools/corpus/selftest.py)
    import classify_rank
    import fixtures
    import retrieve
    import query_templates

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_ROOT / "runtime" / "corpus_test"

# Contract-mandated synthetic profile (test words, NOT product logic branches).
SYNTHETIC_PROFILE = {
    "drug_name": "测试药物A",
    "target": "测试靶点X",
    "molecule_type": "small_molecule",
    "route": "oral",
    "indication": "类风湿关节炎",
    "phase": "III",
    "search_terms": {
        # Optional data-side override so the online run can search CT.gov with
        # English terms when no resolver alias exists for the raw indication.
        "indication": ["rheumatoid arthritis"],
    },
}

# Case-specific tokens that must never appear in the pipeline modules.
BANNED_PIPELINE_TOKENS = ["测试药物A", "测试靶点X", "类风湿关节炎", "rheumatoid"]

PIPELINE_MODULES = [query_templates, retrieve, classify_rank]

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL {name}: {detail}")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Phase 1: offline classification / ranking logic
# --------------------------------------------------------------------------
def test_offline_classification_and_ranking() -> dict:
    print("[1] offline fixture classification + ranking")
    profile = dict(SYNTHETIC_PROFILE)
    studies = fixtures.fixture_studies_copy()
    parsed = []
    for study in studies:
        nct_id = study["protocolSection"]["identificationModule"]["nctId"]
        parsed.append(
            retrieve.parse_study(
                study, fixtures.FIXTURE_STRATEGY_HINTS.get(nct_id, [])
            )
        )
    retrieved = {
        "retrieved_at": "selftest",
        "profile": profile,
        "degraded_to_offline": True,
        "strategies": [],
        "candidates": parsed,
        "gaps": [],
    }
    competitor_set = classify_rank.build_competitor_set(
        retrieved, profile, now=date(2026, 10, 17)
    )
    by_key = {s["study_key"]: s for s in competitor_set["studies"]}

    # 1a. B12: all three studies retained — nothing auto-excluded.
    check(
        "b12_all_fixtures_retained",
        set(by_key) == {"NCT00000001", "NCT00000002", "NCT00000003"},
        f"keys={sorted(by_key)}",
    )

    nct1 = by_key.get("NCT00000001")
    nct2 = by_key.get("NCT00000002")
    nct3 = by_key.get("NCT00000003")

    # 1b. Category assignment per 02_ARCHITECTURE precedence.
    check("nct1_category_same_target", nct1 is not None and nct1["category"] == "same_target",
          str(nct1))
    check("nct1_confidence_high", nct1 is not None and nct1.get("category_confidence") == "high",
          str(nct1 and nct1.get("category_confidence")))
    check("nct2_category_same_indication", nct2 is not None and nct2["category"] == "same_indication",
          str(nct2))
    check("nct3_category_adjacent", nct3 is not None and nct3["category"] == "adjacent",
          str(nct3))

    # 1c. DoD ordering: same_target score > same_indication score > adjacent score.
    check(
        "dod_score_ordering",
        nct1["priority_score"] > nct2["priority_score"] > nct3["priority_score"],
        f"scores: nct1={nct1['priority_score']} nct2={nct2['priority_score']} "
        f"nct3={nct3['priority_score']}",
    )

    # 1d. B12: same-drug registered study gets explicit retention reason.
    check(
        "b12_same_drug_reason",
        any("same_drug" in r for r in nct1["priority_reasons"]),
        str(nct1["priority_reasons"]),
    )

    # 1e. Protocol file parsing (same parser as online path).
    check(
        "protocol_file_flags",
        nct1["has_protocol_file"] is True and nct2["has_protocol_file"] is True
        and nct3["has_protocol_file"] is False,
        f"nct1={nct1['has_protocol_file']} nct2={nct2['has_protocol_file']} "
        f"nct3={nct3['has_protocol_file']}",
    )

    # 1f. Schema conformance (eval/SCHEMAS.md §2).
    errors = classify_rank.validate_competitor_set(competitor_set)
    check("competitor_set_schema_valid", not errors, "; ".join(errors))

    # 1g. Same-class-same-route category boundary (inline synthetic candidate,
    # not one of the 3 contract fixtures).
    inline = {
        "study_key": "NCT00000009",
        "title": "Phase 3 study of an oral small molecule in another condition",
        "phases": ["PHASE3"],
        "conditions": ["Another Condition"],
        "interventions": [{"name": "Anonymous small molecule tablet", "type": "DRUG"}],
        "brief_summary": "oral small molecule, other indication",
        "lead_sponsor": "X", "sponsor_class": "INDUSTRY",
        "overall_status": "RECRUITING", "start_date": "2023-05-01",
        "enrollment_count": 100, "has_protocol_file": False,
        "has_sap_file": False, "matched_strategies": ["same_class_route"],
        "source": "ct_gov",
    }
    verdict = classify_rank.classify(inline, profile)
    check(
        "same_class_route_boundary",
        verdict["category"] == "same_class_route" and verdict["confidence"] in
        {"high", "medium"},
        str(verdict),
    )

    # 1g'. MeSH-inverted condition terms ("HeadTerm, Qualifier") and
    # parenthetical abbreviations must match the indication with high
    # confidence (word-order-insensitive condition matching).
    mesh_inverted = dict(inline)
    mesh_inverted.update(
        {
            "study_key": "NCT00000011",
            "title": "Phase 3 study of an anonymous biologic injection",
            "brief_summary": "subcutaneous injection study",
            "interventions": [{"name": "Anonymous biologic injection", "type": "BIOLOGICAL"}],
            "conditions": ["Arthritis, Rheumatoid", "Rheumatoid Arthritis (RA)"],
            "matched_strategies": ["same_indication"],
        }
    )
    verdict = classify_rank.classify(mesh_inverted, profile)
    check(
        "mesh_inverted_condition_high_confidence",
        verdict["category"] == "same_indication"
        and verdict["confidence"] == "high",
        str(verdict),
    )

    # 1h. A candidate matching ONLY the drug name must still be kept
    # (category=adjacent, same_drug bonus) — the other half of B12.
    drug_only = dict(inline)
    drug_only.update(
        {
            "study_key": "NCT00000010",
            "title": "Phase 2 bioavailability study of 测试药物A",
            "interventions": [{"name": "测试药物A tablet", "type": "DRUG"}],
            "brief_summary": "oral tablet of the profile drug",
            "matched_strategies": ["same_drug"],
        }
    )
    verdict = classify_rank.classify(drug_only, profile)
    score, reasons = classify_rank.score(drug_only, verdict, profile, now=date(2026, 10, 17))
    check(
        "b12_drug_only_candidate_retained",
        verdict.get("same_drug") is True and score > 0
        and any("same_drug" in r for r in reasons),
        f"verdict={verdict} score={score} reasons={reasons}",
    )

    write_json(RUNTIME_DIR / "competitor_set_offline_fixture.json", competitor_set)
    write_json(RUNTIME_DIR / "retrieved_offline_fixture.json", retrieved)
    return competitor_set


# --------------------------------------------------------------------------
# Phase 1b: query template construction (data-configurable, generic)
# --------------------------------------------------------------------------
def test_query_templates() -> None:
    print("[2] query template construction")
    strategies = query_templates.build_strategies(dict(SYNTHETIC_PROFILE))
    ids = [s["strategy_id"] for s in strategies]
    check(
        "default_strategy_ids",
        {"same_target", "same_class_route", "same_indication", "same_drug"} <= set(ids),
        f"ids={ids}",
    )

    same_target = next(s for s in strategies if s["strategy_id"] == "same_target")
    check(
        "target_term_injected_from_profile",
        "测试靶点X" in same_target["term_expr"],
        same_target["term_expr"],
    )
    same_drug = next(s for s in strategies if s["strategy_id"] == "same_drug")
    check(
        "drug_name_injected_from_profile",
        "测试药物A" in same_drug["term_expr"],
        same_drug["term_expr"],
    )

    # Profile without target: same_target strategy must be skipped with an
    # explicit reason (never silently degraded to a generic query); the other
    # strategies stay active.
    profile_no_target = {k: v for k, v in SYNTHETIC_PROFILE.items() if k != "target"}
    profile_no_target.pop("search_terms", None)
    strategies2 = query_templates.build_strategies(profile_no_target)
    by_id2 = {s["strategy_id"]: s for s in strategies2}
    same_target2 = by_id2.get("same_target") or {}
    others2 = [s for s in strategies2 if s["strategy_id"] != "same_target"]
    check(
        "missing_target_skips_strategy_only",
        same_target2.get("skipped") is True
        and bool(same_target2.get("skip_reason"))
        and {"same_class_route", "same_drug"} <= {s["strategy_id"] for s in others2}
        and all(not s.get("skipped") for s in others2),
        f"same_target2={same_target2}",
    )

    # search_terms override mechanism (data-configurable, no code branch).
    st = query_templates.indication_search_terms(dict(SYNTHETIC_PROFILE))
    check(
        "indication_terms_include_search_override",
        "rheumatoid arthritis" in st and "类风湿关节炎" in st,
        f"terms={st}",
    )

    # All built strategies produce a well-formed CT.gov URL (no network).
    for s in strategies:
        url = query_templates.build_query_url(s, page_size=10)
        check(
            f"url_form_{s['strategy_id']}",
            url.startswith("https://clinicaltrials.gov/api/v2/studies?"),
            url,
        )


# --------------------------------------------------------------------------
# Phase 1c: pipeline module purity (no case-specific words in code)
# --------------------------------------------------------------------------
def test_pipeline_purity() -> None:
    print("[3] pipeline module purity")
    for module in PIPELINE_MODULES:
        source_path = Path(module.__file__)
        source = source_path.read_text(encoding="utf-8")
        lowered = source.lower()
        for token in BANNED_PIPELINE_TOKENS:
            check(
                f"no_case_word_{source_path.name}_{token[:6]}…",
                token.lower() not in lowered,
                f"{source_path.name} contains banned token",
            )


# --------------------------------------------------------------------------
# Phase 2: full chain with synthetic profile (online, degrades to offline)
# --------------------------------------------------------------------------
def test_full_chain() -> None:
    print("[4] full retrieve → classify chain (synthetic profile)")
    profile = dict(SYNTHETIC_PROFILE)
    try:
        retrieved = retrieve.run_retrieval(profile)
        mode = "online" if not retrieved.get("degraded_to_offline") else "offline_fallback"
    except retrieve.NetworkUnavailableError as exc:
        print(f"  network unavailable ({exc.__class__.__name__}) → degrading to offline fixtures")
        retrieved = retrieve.offline_retrieval(profile)
        mode = "offline"
    competitor_set = classify_rank.build_competitor_set(retrieved, profile)
    errors = classify_rank.validate_competitor_set(competitor_set)
    check("full_chain_schema_valid", not errors, "; ".join(errors))
    check("full_chain_has_studies", len(competitor_set["studies"]) > 0,
          "no studies in competitor set")
    for strategy_info in retrieved.get("strategies", []):
        if strategy_info.get("error"):
            retrieved.setdefault("gaps", []).append(
                {
                    "kind": "not_retrieved",
                    "where": f"strategy:{strategy_info['strategy_id']}",
                    "next": strategy_info["error"],
                }
            )
    write_json(RUNTIME_DIR / "retrieved.json", retrieved)
    write_json(RUNTIME_DIR / "competitor_set.json", competitor_set)
    print(f"  mode={mode} candidates={len(retrieved['candidates'])} "
          f"studies={len(competitor_set['studies'])}")
    print(f"  artifacts → {RUNTIME_DIR}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline-only", action="store_true",
                        help="skip the online retrieval phase")
    args = parser.parse_args(argv)

    test_offline_classification_and_ranking()
    test_query_templates()
    test_pipeline_purity()
    if not args.offline_only:
        test_full_chain()

    print()
    if FAILURES:
        print(f"SELFTEST FAILED: {len(FAILURES)} failure(s)")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("SELFTEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
