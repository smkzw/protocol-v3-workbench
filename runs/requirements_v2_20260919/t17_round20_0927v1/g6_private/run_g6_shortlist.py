#!/usr/bin/env python3
"""G6 real run: select the 20–30 deep-read shortlist on the K3 snapshot
metadata (622 registry candidates) and map the K3 574 failed translation
entries onto real studies/versions.

Read-only sources:
* worktree fixture copy of snapshot wref_search_4d2c5d3b8476515fc38b
  candidates (public ClinicalTrials.gov registry metadata);
* journey copy (medical_writing_authoring_journey.sqlite3) for the confirmed
  discovery basket ct_conf_ebb394de59fb68021378 (69 retained / 553 excluded);
* isolated runtime writing_reference.sqlite3 opened with SQLite read-only
  URI for the batch item status mapping (574 failed_retryable / 256 excluded).

Zero model calls, zero network, zero downloads. No source database is
written.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

WORKTREE = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/"
    "protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313_g6worktree"
)
PRIVATE = WORKTREE.parent / (
    "protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/"
    "requirements_v2_20260919/t17_round20_0927v1/g6_private"
)
sys.path.insert(0, str(WORKTREE))

from services.api.app.medical_writing_discovery_shortlist import (  # noqa: E402
    ShortlistProjectFacts,
    select_shortlist,
)

FIXTURE = WORKTREE / "tests/fixtures/protocol_v3/g6_discovery_k3_snapshot_candidates.json"
JOURNEY_DB = PRIVATE / "journey_ro.sqlite3"
REFERENCE_DB = (
    WORKTREE.parent
    / (
        "protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/"
        "requirements_v2_20260919/wp6_0922v2_20260922/real_http_acceptance/"
        "isolated_runtime/writing_reference.sqlite3"
    )
)
K3_PROJECT = "proj_user_fad9f64f3151"
K3_BATCH = "wref_translation_batch_79e7f4e51e7270b75688e8e9"
OUT_DIR = PRIVATE


def main() -> None:
    fixture = json.loads(FIXTURE.read_text())
    candidates = fixture["candidates"]
    assert fixture["candidate_count"] == len(candidates) == 622

    journey_conn = sqlite3.connect(f"file:{JOURNEY_DB}?mode=ro", uri=True)
    (payload,) = journey_conn.execute(
        "SELECT payload_json FROM medical_writing_authoring_journeys "
        "WHERE project_id=?",
        (K3_PROJECT,),
    ).fetchone()
    journey = json.loads(payload)
    basket = journey["discovery_basket_projection"]
    relevance = {nct: "indirect_reference" for nct in basket["retained_nct_ids"]}
    relevance.update({nct: "excluded" for nct in basket["excluded_nct_ids"]})

    facts = ShortlistProjectFacts(
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
        endpoint_keywords=(
            "madr", "hamilton", "ham-d", "response rate", "remission", "cgi",
        ),
        comparator_keywords=("placebo",),
        treatment_duration_weeks=8,
        preferred_regions=("china",),
        reference_date="2026-09-23",
    )
    proposal = select_shortlist(
        candidates,
        facts,
        relevance=relevance,
        relevance_identity=f"basket:{basket['confirmation_id']}",
        snapshot_id=fixture["snapshot_id"],
    )
    proposal_payload = proposal.to_dict()
    (OUT_DIR / "g6_shortlist_proposal.json").write_text(
        json.dumps(proposal_payload, ensure_ascii=False, indent=1)
    )

    # --- K3 830-item batch mapping (574 failed_retryable / 256 excluded) ---
    ref_conn = sqlite3.connect(f"file:{REFERENCE_DB}?mode=ro", uri=True)
    rows = []
    for item_id, generation_status, attempt, payload_json in ref_conn.execute(
        "SELECT item_id, generation_status, attempt, payload_json "
        "FROM writing_reference_translation_batch_items "
        "WHERE project_id=? AND batch_id=?",
        (K3_PROJECT, K3_BATCH),
    ).fetchall():
        item = json.loads(payload_json)
        rows.append(
            (
                item_id,
                str(item.get("nct_id") or ""),
                str(item.get("document_type") or ""),
                str(item.get("filename") or ""),
                generation_status,
                str(item.get("error_code") or ""),
                attempt,
            )
        )
    ref_conn.close()
    status_counter = Counter(row[4] for row in rows)
    assert status_counter == Counter(
        {"failed_retryable": 574, "excluded": 256}
    ), status_counter

    selected_nct = {entry["nct_id"] for entry in proposal_payload["selected"]}
    pool_nct = {entry["nct_id"] for entry in proposal_payload["replacement_pool"]}
    item_status_by_nct: dict[str, Counter] = {}
    for _item, nct_id, doc_type, filename, status, _err, _att in rows:
        item_status_by_nct.setdefault(nct_id, Counter())[status] += 1
    mapping_rows = []
    for nct_id, counter in sorted(item_status_by_nct.items()):
        if nct_id in selected_nct:
            scope = "selected"
        elif nct_id in pool_nct:
            scope = "replacement_pool"
        elif relevance.get(nct_id) == "excluded":
            scope = "out_of_scope_triage_excluded"
        else:
            scope = "unknown"
        mapping_rows.append(
            {
                "nct_id": nct_id,
                "shortlist_scope": scope,
                "failed_retryable_items": counter.get("failed_retryable", 0),
                "excluded_items": counter.get("excluded", 0),
            }
        )
    failed_in_selected = sum(
        r["failed_retryable_items"]
        for r in mapping_rows
        if r["shortlist_scope"] == "selected"
    )
    failed_in_pool = sum(
        r["failed_retryable_items"]
        for r in mapping_rows
        if r["shortlist_scope"] == "replacement_pool"
    )
    failed_out_of_scope = sum(
        r["failed_retryable_items"]
        for r in mapping_rows
        if r["shortlist_scope"] == "out_of_scope_triage_excluded"
    )
    mapping = {
        "schema_version": "g6_k3_batch_mapping_v1",
        "project_id": K3_PROJECT,
        "batch_id": K3_BATCH,
        "snapshot_id": fixture["snapshot_id"],
        "batch_item_status_counts": dict(status_counter),
        "total_batch_items": len(rows),
        "distinct_studies_touched": len(item_status_by_nct),
        "failed_retryable_items_in_selected_scope": failed_in_selected,
        "failed_retryable_items_in_replacement_pool": failed_in_pool,
        "failed_retryable_items_out_of_scope": failed_out_of_scope,
        "recovery_note": (
            "574 failed_retryable entries are fragment-level items; this maps "
            "them to real studies. Only entries whose study is inside the "
            "adopted shortlist scope are recovery candidates; out-of-scope "
            "history is preserved and binds no new expensive tasks (A610). "
            "Actual recovery stays paused per the standing red line."
        ),
        "studies": mapping_rows,
    }
    (OUT_DIR / "g6_k3_574_mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=1)
    )

    print("proposal_hash:", proposal.proposal_hash)
    print("counts:", json.dumps(proposal.counts, ensure_ascii=False))
    print(
        "574 mapping: selected=",
        failed_in_selected,
        "pool=",
        failed_in_pool,
        "out_of_scope=",
        failed_out_of_scope,
        "studies touched:",
        len(item_status_by_nct),
    )


if __name__ == "__main__":
    main()
