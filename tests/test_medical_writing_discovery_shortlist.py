"""G6 discovery shortlist selector tests (0926V1 A601–A610, 0927V1 A21/A16).

The real-metadata fixture is a read-only copy of public ClinicalTrials.gov
registry metadata from the isolated acceptance runtime snapshot
``wref_search_4d2c5d3b8476515fc38b`` (622 candidates). No downloads, no
translations, no model calls — the selector is a pure function (A16/A21).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.api.app import medical_writing_discovery_shortlist as selector_module
from services.api.app.medical_writing_discovery_shortlist import (
    DEFAULT_TARGET_STUDY_COUNT,
    MAX_SHORTLIST_STUDY_COUNT,
    MIN_TARGET_STUDY_COUNT,
    ShortlistProjectFacts,
    ShortlistSelectorError,
    apply_replacement,
    select_shortlist,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "protocol_v3"
    / "g6_discovery_k3_snapshot_candidates.json"
)

K3_SNAPSHOT_ID = "wref_search_4d2c5d3b8476515fc38b"
K3_CONFIRMATION_ID = "ct_conf_ebb394de59fb68021378"

# The authoritative retained list of the K3 confirmed discovery basket
# (confirmation ct_conf_ebb394de59fb68021378): 69 indirect references, kept
# byte-identical to the journey projection; the 553-complement is excluded.
_K3_RETAINED_SET = {
    "NCT00088699", "NCT01703039", "NCT02078817", "NCT02176291", "NCT02181231",
    "NCT02192099", "NCT02376257", "NCT02395978", "NCT02418195", "NCT02458690",
    "NCT02461927", "NCT02473289", "NCT02553915", "NCT02660528", "NCT02674529",
    "NCT02882711", "NCT03018340", "NCT03043560", "NCT03051256", "NCT03053362",
    "NCT03079297", "NCT03093025", "NCT03113968", "NCT03152409", "NCT03181529",
    "NCT03185819", "NCT03193398", "NCT03227224", "NCT03283670", "NCT03321526",
    "NCT03352453", "NCT03429075", "NCT03446846", "NCT03505905", "NCT03559192",
    "NCT03586427", "NCT03595579", "NCT03697603", "NCT03726658", "NCT03756129",
    "NCT03822416", "NCT03866174", "NCT03889756", "NCT03915613", "NCT04080752",
    "NCT04221230", "NCT04244253", "NCT04301271", "NCT04395183", "NCT04423757",
    "NCT04437485", "NCT04479852", "NCT04521478", "NCT04634669", "NCT04722666",
    "NCT04821271", "NCT04979910", "NCT05165394", "NCT05193318", "NCT05376150",
    "NCT05439603", "NCT05454410", "NCT05686408", "NCT06126497", "NCT06235905",
    "NCT06280235", "NCT06309277", "NCT06340958", "NCT06558344",
}
assert len(_K3_RETAINED_SET) == 69


def _load_real_fixture() -> tuple[list[dict], dict[str, str]]:
    payload = json.loads(FIXTURE.read_text())
    candidates = payload["candidates"]
    relevance = {
        candidate["nct_id"]: (
            "indirect_reference"
            if candidate["nct_id"] in _K3_RETAINED_SET
            else "excluded"
        )
        for candidate in candidates
    }
    return candidates, relevance


def _k3_facts() -> ShortlistProjectFacts:
    return ShortlistProjectFacts(
        condition_terms=("treatment-resistant depression", "major depressive disorder"),
        purpose_keywords=(
            "madrs", "response", "remission", "cgi", "antidepressant",
            "add-on", "adjunct",
        ),
        design_keywords=("randomized", "double-blind", "parallel", "placebo"),
        phases=("II期",),
        drug_technology="small_molecule",
        route_keywords=("oral",),
        mechanism_keywords=(
            "opioid", "norepinephrine", "dopamine", "serotonin", "glutamate", "gaba",
        ),
        endpoint_keywords=("madr", "hamilton", "ham-d", "response rate", "remission", "cgi"),
        comparator_keywords=("placebo",),
        treatment_duration_weeks=8,
        preferred_regions=("china",),
        reference_date="2026-09-23",
    )


def _candidate(nct_id: str, **overrides) -> dict:
    candidate = {
        "nct_id": nct_id,
        "brief_title": f"Study {nct_id}",
        "official_title": "",
        "brief_summary": "",
        "conditions": [],
        "phases": ["PHASE2"],
        "study_type": "INTERVENTIONAL",
        "interventions": [{"name": "DrugX", "intervention_type": "DRUG"}],
        "design_allocation": "RANDOMIZED",
        "design_intervention_model": "PARALLEL",
        "design_masking": "DOUBLE",
        "enrollment_count": 100,
        "lead_sponsor": "Sponsor",
        "overall_status": "RECRUITING",
        "first_posted": "2020-01-01",
        "last_update_posted": "",
        "public_documents": [],
        "relevance_status": "indirect_reference",
    }
    candidate.update(overrides)
    return candidate


def _trd_candidate(nct_id: str, **overrides) -> dict:
    """Synthetic eligible TRD study; the nct_id in the title keeps each
    synthetic study's duplicate fingerprint unique."""

    base = dict(
        official_title=(
            f"A Phase 2, Randomized, Double-blind, Placebo-controlled Study of "
            f"DrugX adjunctive therapy ({nct_id}) in Major Depressive Disorder"
        ),
        brief_summary=(
            "This study evaluates the efficacy of oral DrugX as add-on "
            "treatment in adults with major depressive disorder and "
            "inadequate response; MADRS total score change from baseline at "
            "week 8."
        ),
        conditions=["Major Depressive Disorder"],
    )
    base.update(overrides)
    return _candidate(nct_id, **base)


# ---------------------------------------------------------------------------
# A21 / A601 — 622 real registry metadata entries select ≤30 distinct studies
# ---------------------------------------------------------------------------

def test_a21_a601_real_622_metadata_selects_within_cap() -> None:
    candidates, relevance = _load_real_fixture()
    assert len(candidates) == 622
    proposal = select_shortlist(
        candidates,
        _k3_facts(),
        relevance=relevance,
        relevance_identity=f"basket:{K3_CONFIRMATION_ID}",
        snapshot_id=K3_SNAPSHOT_ID,
    )
    counts = proposal.counts
    assert counts["candidate_count"] == 622
    assert counts["eligible_studies"] == 69
    assert counts["selected_studies"] == DEFAULT_TARGET_STUDY_COUNT
    assert counts["selected_studies"] <= MAX_SHORTLIST_STUDY_COUNT
    selected_nct = [entry.nct_id for entry in proposal.selected]
    assert len(set(selected_nct)) == len(selected_nct) == counts["selected_studies"]
    assert counts["replacement_pool_studies"] == 44
    # Expensive tasks bind to the selected scope only (A601/A610).
    scope_nct = {entry["nct_id"] for entry in proposal.scope_hint}
    assert scope_nct == set(selected_nct)
    assert counts["planned_download_calls"] == counts["protocol_file_count"]
    # Out-of-scope history preserved, never selected.
    assert counts["excluded_by_triage_studies"] == 553
    all_reported = set(selected_nct) | {
        entry.nct_id for entry in proposal.replacement_pool
    }
    assert not (all_reported & {item["nct_id"] for item in proposal.excluded_by_triage})


def test_a16_a21_pure_deterministic_no_model_no_network() -> None:
    source = Path(selector_module.__file__).read_text()
    banned = [
        "urllib", "requests", "httpx", "socket", "ai_gateway", "vlm_gateway",
        "omlx", "model_phase_scheduler", "warm_", "subprocess",
    ]
    hits = [token for token in banned if token in source]
    assert not hits, f"selector module must stay metadata-only, found {hits}"

    candidates, relevance = _load_real_fixture()
    kwargs = dict(
        relevance=relevance,
        relevance_identity=f"basket:{K3_CONFIRMATION_ID}",
        snapshot_id=K3_SNAPSHOT_ID,
    )
    first = select_shortlist(candidates, _k3_facts(), **kwargs)
    second = select_shortlist(candidates, _k3_facts(), **kwargs)
    assert first.proposal_hash == second.proposal_hash
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# A602 — qualifying studies under the cap are all kept, no padding
# ---------------------------------------------------------------------------

def test_a602_seven_qualifying_all_kept_no_padding() -> None:
    candidates = [_trd_candidate(f"NCT6000000{i:02d}") for i in range(7)]
    proposal = select_shortlist(candidates, _k3_facts(), relevance=None)
    assert proposal.counts["eligible_studies"] == 7
    assert proposal.counts["selected_studies"] == 7
    assert proposal.counts["replacement_pool_studies"] == 0
    assert len(proposal.selected) == 7
    assert "kept in full" in " ".join(proposal.notes)
    assert DEFAULT_TARGET_STUDY_COUNT == 25  # target does not inflate the result


def test_a602_trims_to_target_never_beyond_cap() -> None:
    candidates = [_trd_candidate(f"NCT6100000{i:03d}") for i in range(41)]
    proposal = select_shortlist(candidates, _k3_facts(), relevance=None)
    assert proposal.counts["qualified_studies"] == 41
    assert proposal.counts["selected_studies"] == DEFAULT_TARGET_STUDY_COUNT
    assert (
        MIN_TARGET_STUDY_COUNT
        <= proposal.counts["selected_studies"]
        <= MAX_SHORTLIST_STUDY_COUNT
    )


# ---------------------------------------------------------------------------
# A603 — same-study duplicates collapse; different studies never merge
# ---------------------------------------------------------------------------

def test_a603_same_study_reregistration_dedup_with_explainable_choice() -> None:
    primary = _trd_candidate(
        "NCT62000001",
        first_posted="2019-01-01",
        brief_summary="add-on MADRS week 8 placebo double-blind randomized",
    )
    reregistration = dict(primary)
    reregistration["nct_id"] = "NCT62000002"
    reregistration["brief_summary"] = (
        "add-on MADRS week 8 placebo double-blind randomized primary endpoint"
    )
    proposal = select_shortlist(
        [primary, reregistration], _k3_facts(), relevance=None
    )
    assert proposal.counts["duplicate_studies_collapsed"] == 1
    duplicate = proposal.duplicates[0]
    assert duplicate["nct_id"] == "NCT62000002"
    assert duplicate["duplicate_of"] == "NCT62000001"
    assert "fingerprint" in duplicate["reason"]
    selected_nct = {entry.nct_id for entry in proposal.selected}
    assert selected_nct == {"NCT62000001"}


def test_a603_distinct_studies_with_same_drug_not_collapsed() -> None:
    study_a = _trd_candidate("NCT62000003")
    study_b = _trd_candidate(
        "NCT62000004",
        official_title=(
            "A Phase 2 Randomized Study of DrugX (NCT62000004) in Crohn's "
            "Disease patients"
        ),
        brief_summary="oral DrugX induction therapy in active Crohn's disease",
        conditions=["Crohn's Disease"],
    )
    proposal = select_shortlist([study_a, study_b], _k3_facts(), relevance=None)
    assert proposal.counts["duplicate_studies_collapsed"] == 0
    assert proposal.counts["qualified_studies"] == 2


# ---------------------------------------------------------------------------
# A604 — unknown stays separate from mismatch; nothing guessed
# ---------------------------------------------------------------------------

def test_a604_missing_metadata_is_unknown_not_mismatch() -> None:
    sparse = _candidate(
        "NCT63000001",
        brief_title="A Study of DrugX",
        official_title="A Study of DrugX",
        brief_summary="an interventional study",
        conditions=["Major Depressive Disorder"],
        phases=[],
        first_posted="",
    )
    facts = ShortlistProjectFacts(
        condition_terms=("major depressive disorder",),
        phases=("PHASE2",),
        endpoint_keywords=("madr",),
        route_keywords=("oral",),
        preferred_regions=("china",),
        reference_date="2026-09-23",
    )
    proposal = select_shortlist([sparse], facts, relevance=None)
    entry = proposal.selected[0]
    assert "phase" in entry.unknown_fields
    assert "endpoint_class" in entry.unknown_fields
    assert "duration" in entry.unknown_fields
    assert entry.unknown_fields, "missing metadata must be reported unknown"
    assert entry.differences == {}
    assert entry.tiebreakers["recency_date"] == "unknown"
    assert entry.tiebreakers["preferred_region_centre"] == "unknown"


def test_phase_notation_cn_folds_onto_registry_phases() -> None:
    """Regression: project facts "II期" must match candidate PHASE2.

    Counterexample captured 2026-09-27 on the real K3 run: before the fix
    every selection carried a false ``phase`` difference because the facts
    side kept the Chinese 期 suffix unnormalised.
    """

    candidate = _trd_candidate("NCT69500001")
    facts = ShortlistProjectFacts(
        condition_terms=("major depressive disorder",),
        phases=("II期",),
        reference_date="2026-09-23",
    )
    proposal = select_shortlist([candidate], facts, relevance=None)
    entry = proposal.selected[0]
    assert "phase" in entry.matched
    assert "phase" not in entry.differences
    assert "phase" not in entry.unknown_fields


def test_a604_explicit_contrary_evidence_is_mismatch() -> None:
    phase3 = _trd_candidate(
        "NCT63000002",
        phases=["PHASE3"],
        brief_summary="randomized double-blind placebo add-on MADRS",
    )
    long_duration = _trd_candidate(
        "NCT63000003",
        brief_summary=(
            "oral DrugX add-on in major depressive disorder, MADRS at week 24"
        ),
    )
    facts = ShortlistProjectFacts(
        condition_terms=("major depressive disorder",),
        purpose_keywords=("add-on",),
        design_keywords=("randomized", "placebo"),
        phases=("PHASE2",),
        endpoint_keywords=("madr",),
        comparator_keywords=("placebo",),
        treatment_duration_weeks=8,
        reference_date="2026-09-23",
    )
    proposal = select_shortlist(
        [phase3, long_duration], facts, relevance=None
    )
    by_nct = {entry.nct_id: entry for entry in proposal.selected}
    assert "phase" in by_nct["NCT63000002"].differences
    assert "duration" in by_nct["NCT63000003"].differences
    # Unknown never pulls a candidate below an explicit mismatch.
    sparse_known = _trd_candidate("NCT63000004", brief_summary="add-on therapy")
    sparse = _candidate(
        "NCT63000005",
        brief_title="A depression study",
        brief_summary="a study",
        conditions=["Major Depressive Disorder"],
        phases=[],
    )
    proposal2 = select_shortlist([sparse_known, sparse], facts, relevance=None)
    ranked = [entry.nct_id for entry in proposal2.selected]
    assert ranked.index("NCT63000004") < ranked.index("NCT63000005")


# ---------------------------------------------------------------------------
# A605 — comparability dominates recency
# ---------------------------------------------------------------------------

def test_a605_older_comparable_outranks_newer_less_comparable() -> None:
    older_highly_comparable = _trd_candidate(
        "NCT64000001",
        first_posted="2015-01-01",
        last_update_posted="2016-01-01",
    )
    newer_less_comparable = _trd_candidate(
        "NCT64000002",
        first_posted="2026-01-01",
        last_update_posted="2026-09-01",
        phases=["PHASE3"],
        brief_summary=(
            "randomized study of intravenous DeviceY monotherapy in major "
            "depressive disorder; endpoint is plasma biomarker level."
        ),
        interventions=[{"name": "DeviceY", "intervention_type": "DEVICE"}],
        conditions=["Treatment-Resistant Depression"],
    )
    facts = ShortlistProjectFacts(
        condition_terms=("major depressive disorder",),
        purpose_keywords=("add-on",),
        design_keywords=("randomized", "placebo"),
        phases=("PHASE2",),
        endpoint_keywords=("madr",),
        comparator_keywords=("placebo",),
        treatment_duration_weeks=8,
        reference_date="2026-09-23",
    )
    proposal = select_shortlist(
        [newer_less_comparable, older_highly_comparable], facts, relevance=None
    )
    ranks = {entry.nct_id: entry.rank for entry in proposal.selected}
    assert ranks["NCT64000001"] < ranks["NCT64000002"]


def test_a605_recency_breaks_ties_among_comparables() -> None:
    older = _trd_candidate(
        "NCT64000003", first_posted="2018-01-01", last_update_posted="2018-06-01"
    )
    newer = _trd_candidate(
        "NCT64000004", first_posted="2025-01-01", last_update_posted="2025-06-01"
    )
    proposal = select_shortlist([older, newer], _k3_facts(), relevance=None)
    ranks = {entry.nct_id: entry.rank for entry in proposal.selected}
    assert ranks["NCT64000004"] < ranks["NCT64000003"]


# ---------------------------------------------------------------------------
# A606 — whole-group adoption + individual replacement
# ---------------------------------------------------------------------------

def test_a606_whole_group_hash_and_individual_replacement() -> None:
    candidates = [_trd_candidate(f"NCT6500000{i:03d}") for i in range(40)]
    proposal = select_shortlist(candidates, _k3_facts(), relevance=None)
    assert proposal.counts["replacement_pool_studies"] > 0
    original_hash = proposal.proposal_hash
    assert proposal.version == 1 and proposal.parent_hash == ""

    removed = proposal.selected[-1]
    added = proposal.replacement_pool[0]
    updated = apply_replacement(
        proposal, remove_nct_ids=[removed.nct_id], add_nct_ids=[added.nct_id]
    )
    assert updated.version == 2
    assert updated.parent_hash == original_hash
    assert updated.proposal_hash != original_hash
    selected_nct = {entry.nct_id for entry in updated.selected}
    assert added.nct_id in selected_nct
    assert removed.nct_id not in selected_nct
    assert updated.counts["selected_studies"] == proposal.counts["selected_studies"]
    # Rationale travels with entries; scope hint follows the new group.
    updated_added = next(e for e in updated.selected if e.nct_id == added.nct_id)
    assert updated_added.entry_reason == "individual replacement in"
    assert {e["nct_id"] for e in updated.scope_hint} == selected_nct

    with pytest.raises(ShortlistSelectorError):
        apply_replacement(
            proposal, remove_nct_ids=["NCT99999999"], add_nct_ids=[added.nct_id]
        )
    with pytest.raises(ShortlistSelectorError):
        apply_replacement(
            proposal, remove_nct_ids=[removed.nct_id], add_nct_ids=[removed.nct_id]
        )


# ---------------------------------------------------------------------------
# A607 / A608 — Protocol-only document scope
# ---------------------------------------------------------------------------

def _doc(nct_id: str, index: int, doc_type: str, date: str) -> dict:
    return {
        "document_id": f"ctgov_{nct_id}_{index:03d}",
        "nct_id": nct_id,
        "document_type": doc_type,
        "filename": f"{doc_type.upper()}_{index:03d}.pdf",
        "document_date": date,
        "upload_date": date,
        "download_url": (
            f"https://clinicaltrials.gov/ProvidedDocs/{nct_id}/{doc_type}_{index}.pdf"
        ),
    }


def test_a607_standalone_sap_icf_never_downloaded() -> None:
    candidate = _trd_candidate(
        "NCT66000001",
        public_documents=[
            _doc("NCT66000001", 1, "sap", "2021-01-01"),
            _doc("NCT66000001", 2, "icf", "2021-02-01"),
            _doc("NCT66000001", 3, "protocol", "2020-01-01"),
        ],
    )
    proposal = select_shortlist([candidate], _k3_facts(), relevance=None)
    entry = proposal.selected[0]
    plan = entry.document_plan
    assert plan["chosen_document"]["document_type"] == "protocol"
    standalone_ids = {
        item["document_id"] for item in plan["standalone_documents_not_downloaded"]
    }
    assert standalone_ids == {"ctgov_NCT66000001_001", "ctgov_NCT66000001_002"}
    scope_docs = [e for e in proposal.scope_hint if e["nct_id"] == "NCT66000001"]
    assert len(scope_docs) == 1
    assert scope_docs[0]["document_id"] == "ctgov_NCT66000001_003"
    assert proposal.counts["planned_download_calls"] == 1
    assert proposal.counts["standalone_excluded_file_count"] == 2


def test_a607_real_fixture_standalone_downloads_zero() -> None:
    candidates, relevance = _load_real_fixture()
    proposal = select_shortlist(
        candidates,
        _k3_facts(),
        relevance=relevance,
        relevance_identity=f"basket:{K3_CONFIRMATION_ID}",
        snapshot_id=K3_SNAPSHOT_ID,
    )
    scope_types = {entry["document_type"] for entry in proposal.scope_hint}
    assert scope_types <= {"protocol", "protocol_sap", ""}
    assert proposal.counts["standalone_excluded_file_count"] > 0
    assert proposal.counts["planned_download_calls"] == proposal.counts["protocol_file_count"]


def test_a608_merged_protocol_sap_admitted_as_complete_protocol() -> None:
    merged_only = _trd_candidate(
        "NCT67000001",
        public_documents=[_doc("NCT67000001", 1, "protocol_sap", "2022-03-01")],
    )
    proposal = select_shortlist([merged_only], _k3_facts(), relevance=None)
    plan = proposal.selected[0].document_plan
    assert plan["chosen_document"]["document_type"] == "protocol_sap"
    assert "Protocol portions" in plan["version_choice_reason"]
    assert plan["manual_upload_required"] is False
    assert proposal.counts["planned_download_calls"] == 1


def test_no_protocol_document_requires_manual_upload() -> None:
    sap_only = _trd_candidate(
        "NCT67000002",
        public_documents=[_doc("NCT67000002", 1, "sap", "2022-03-01")],
    )
    proposal = select_shortlist([sap_only], _k3_facts(), relevance=None)
    entry = proposal.selected[0]
    assert entry.document_plan["manual_upload_required"] is True
    assert entry.document_plan["chosen_document"] is None
    hint = [e for e in proposal.scope_hint if e["nct_id"] == "NCT67000002"]
    assert hint[0]["item_kind"] == "study_manual_upload_required"
    assert proposal.counts["manual_upload_studies"] == 1
    assert proposal.counts["planned_download_calls"] == 0


def test_a608_latest_protocol_version_chosen_explainably() -> None:
    candidate = _trd_candidate(
        "NCT67000003",
        public_documents=[
            _doc("NCT67000003", 1, "protocol", "2019-01-01"),
            _doc("NCT67000003", 2, "protocol", "2023-05-01"),
        ],
    )
    proposal = select_shortlist([candidate], _k3_facts(), relevance=None)
    plan = proposal.selected[0].document_plan
    assert plan["chosen_document"]["document_id"] == "ctgov_NCT67000003_002"
    assert plan["alternate_versions_not_downloaded"] == ["ctgov_NCT67000003_001"]
    assert "latest" in plan["version_choice_reason"]


# ---------------------------------------------------------------------------
# A609 — study/file/fragment counts are separate
# ---------------------------------------------------------------------------

def test_a609_counts_reported_separately() -> None:
    candidates = [
        _trd_candidate(
            "NCT68000001",
            public_documents=[
                _doc("NCT68000001", 1, "protocol", "2021-01-01"),
                _doc("NCT68000001", 2, "sap", "2021-02-01"),
            ],
        ),
        _trd_candidate("NCT68000002"),
    ]
    proposal = select_shortlist(candidates, _k3_facts(), relevance=None)
    counts = proposal.counts
    assert counts["selected_studies"] == 2
    assert counts["protocol_file_count"] == 1
    assert counts["standalone_excluded_file_count"] == 1
    assert counts["planned_download_calls"] == 1
    assert counts["fragment_count"] is None
    assert "separately" in counts["fragment_count_basis"]


# ---------------------------------------------------------------------------
# A610 — out-of-scope keeps history, binds no expensive tasks
# ---------------------------------------------------------------------------

def test_a610_out_of_scope_history_kept_no_tasks_bound() -> None:
    eligible = [_trd_candidate(f"NCT6900000{i:02d}") for i in range(40)]
    irrelevant = _trd_candidate(
        "NCT69000100",
        brief_title="A breast cancer study",
        conditions=["Breast Cancer"],
        relevance_status="excluded",
    )
    undecided = _candidate(
        "NCT69000101",
        brief_title="An untriaged study",
        relevance_status="pending_medical_relevance",
    )
    proposal = select_shortlist(
        eligible + [irrelevant, undecided], _k3_facts(), relevance=None
    )
    excluded_nct = {item["nct_id"] for item in proposal.excluded_by_triage}
    unknown_nct = {item["nct_id"] for item in proposal.unknown_triage}
    assert excluded_nct == {"NCT69000100"}
    assert unknown_nct == {"NCT69000101"}
    scope_nct = {entry["nct_id"] for entry in proposal.scope_hint}
    pool_nct = {entry.nct_id for entry in proposal.replacement_pool}
    selected_nct = {entry.nct_id for entry in proposal.selected}
    assert "NCT69000100" not in scope_nct | pool_nct | selected_nct
    assert "NCT69000101" not in scope_nct | pool_nct | selected_nct
    assert proposal.counts["excluded_by_triage_studies"] == 1
    assert proposal.counts["unknown_triage_studies"] == 1


# ---------------------------------------------------------------------------
# Contract guards
# ---------------------------------------------------------------------------

def test_contract_target_bounds_and_input_validation() -> None:
    candidate = _trd_candidate("NCT70000001")
    with pytest.raises(ShortlistSelectorError):
        select_shortlist([candidate], _k3_facts(), relevance=None, target_size=19)
    with pytest.raises(ShortlistSelectorError):
        select_shortlist([candidate], _k3_facts(), relevance=None, target_size=31)
    with pytest.raises(ShortlistSelectorError):
        select_shortlist([candidate, dict(candidate)], _k3_facts(), relevance=None)
    dateless_facts = ShortlistProjectFacts(
        condition_terms=("depression",), reference_date=""
    )
    with pytest.raises(ShortlistSelectorError):
        select_shortlist([candidate], dateless_facts, relevance=None)


def test_real_fixture_reference_ids_are_stable() -> None:
    payload = json.loads(FIXTURE.read_text())
    assert payload["snapshot_id"] == K3_SNAPSHOT_ID
    assert payload["candidate_count"] == len(payload["candidates"]) == 622
    assert all(candidate.get("nct_id") for candidate in payload["candidates"])
