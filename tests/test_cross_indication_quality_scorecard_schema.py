from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (
        ROOT
        / "records/active_slices/medical_writing_cross_indication_reference_gate_20260718"
        / "quality_scorecard.schema.json"
    ).read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA)


def base_payload(review_status: str) -> dict:
    return {
        "schema_version": "mw_cross_indication_quality_v1",
        "review_status": review_status,
        "project_id": "qc_ad_phase2",
        "indication": "特应性皮炎",
        "study_phase": "II",
        "source_receipts": [],
        "translation_samples": [],
        "candidate_sets": [],
        "open_findings": [],
        "gate": {
            "average_score": None,
            "open_p0": 0,
            "open_p1": 0,
            "working_copy_unchanged_after_generation": None,
            "passed": False,
        },
    }


def scored_item(item_id: str, scores: dict | None) -> dict:
    reviewed = scores is not None
    return {
        "item_id": item_id,
        "target_section_id": "section_1",
        "source_span_ids": ["span_1"],
        "text": "受试者应符合方案规定的入选标准。",
        "scores": scores,
        "unsupported_claim_count": 0 if reviewed else None,
        "material_defects": [],
        "reviewer_role": "senior_medical_writer" if reviewed else None,
        "p0_findings": [] if reviewed else None,
        "p1_findings": [] if reviewed else None,
        "p2_findings": [] if reviewed else None,
        "directly_usable": True if reviewed else None,
        "needs_prompt_or_pipeline_repair": False if reviewed else None,
    }


def reviewed_payload() -> dict:
    payload = base_payload("reviewed")
    scores = {
        "usability": 4,
        "fluency": 4,
        "scientific_accuracy": 5,
        "regulatory_style": 4,
        "traceability": 5,
        "no_unsupported_addition": 5,
    }
    payload["source_receipts"] = [
        {
            "nct_id": "NCT05923099",
            "document_role": "protocol_sap",
            "final_url": "https://cdn.clinicaltrials.gov/example.pdf",
            "sha256": "a" * 64,
            "bytes": 100,
            "validation_revision": 1,
            "extraction_revision": "extract_1",
        }
    ]
    payload["translation_samples"] = [
        scored_item("translation_1", scores),
        scored_item("translation_2", scores),
    ]
    payload["candidate_sets"] = [
        {
            "section_id": f"section_{index}",
            "working_copy_hash_before": "b" * 64,
            "working_copy_hash_after": "b" * 64,
            "working_copy_revision_before": 1,
            "working_copy_revision_after": 1,
            "review_status": "reviewed",
            "recommended_candidate_id": f"candidate_{index}_0",
            "group_passed": True,
            "needs_prompt_or_pipeline_repair": False,
            "candidates": [
                scored_item(f"candidate_{index}_{candidate}", scores)
                for candidate in range(3)
            ],
        }
        for index in range(2)
    ]
    payload["gate"] = {
        "average_score": 4.5,
        "open_p0": 0,
        "open_p1": 0,
        "working_copy_unchanged_after_generation": True,
        "passed": True,
    }
    return payload


def test_pending_scorecard_cannot_claim_pass() -> None:
    pending = base_payload("pending_blind_review")
    assert not list(VALIDATOR.iter_errors(pending))
    pending["gate"]["passed"] = True
    assert list(VALIDATOR.iter_errors(pending))


def test_blocked_before_review_accepts_empty_observation_sets() -> None:
    blocked = base_payload("blocked_before_review")
    blocked["gate"]["open_p1"] = 1
    assert not list(VALIDATOR.iter_errors(blocked))


def test_reviewed_scorecard_requires_real_scored_items() -> None:
    reviewed = reviewed_payload()
    assert not list(VALIDATOR.iter_errors(reviewed))
    reviewed["candidate_sets"][0]["candidates"][0]["scores"] = None
    assert list(VALIDATOR.iter_errors(reviewed))
