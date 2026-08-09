from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from packages.contracts.workbench_contracts import (
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
    WritingReferenceTrialIntervention,
)
from services.api.app.medical_writing_competitor_triage import (
    _build_chunk_input,
    _build_system_prompt,
    _snapshot_hash,
)
from services.api.app.writing_reference import (
    CTGOV_DISCOVERY_FIELDS,
    candidate_from_study,
)


def _ctgov_study_fixture() -> dict:
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT03562377",
                "briefTitle": "Tralokinumab Vaccine Response Study",
                "officialTitle": "A Phase 2 Vaccine Response Study",
            },
            "descriptionModule": {
                "briefSummary": (
                    "This trial evaluates concomitant tralokinumab and vaccines "
                    "in participants with atopic dermatitis."
                )
            },
            "conditionsModule": {"conditions": ["Atopic Dermatitis"]},
            "designModule": {
                "phases": ["PHASE2"],
                "studyType": "INTERVENTIONAL",
                "designInfo": {
                    "allocation": "RANDOMIZED",
                    "interventionModel": "PARALLEL",
                    "maskingInfo": {"masking": "DOUBLE"},
                },
                "enrollmentInfo": {"count": 215, "type": "ACTUAL"},
            },
            "armsInterventionsModule": {
                "interventions": [
                    {"type": "DRUG", "name": "Tralokinumab"},
                    {"type": "DRUG", "name": "Placebo"},
                    {"type": "BIOLOGICAL", "name": "Tdap vaccine"},
                ]
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "LEO Pharma"}
            },
            "statusModule": {
                "overallStatus": "COMPLETED",
                "studyFirstPostDateStruct": {"date": "2018-06-18"},
                "studyLastUpdatePostDateStruct": {"date": "2021-11-08"},
            },
        }
    }


def _candidate(**updates: object) -> WritingReferenceTrialCandidate:
    material = {
        "nct_id": "NCT03562377",
        "brief_title": "Tralokinumab Vaccine Response Study",
        "official_title": "A Phase 2 Vaccine Response Study",
        "conditions": ["Atopic Dermatitis"],
        "phases": ["PHASE2"],
        "study_type": "INTERVENTIONAL",
        "lead_sponsor": "LEO Pharma",
        "overall_status": "COMPLETED",
        "study_record_url": "https://clinicaltrials.gov/study/NCT03562377",
    }
    material.update(updates)
    return WritingReferenceTrialCandidate(**material)


def _snapshot(
    candidate: WritingReferenceTrialCandidate,
) -> WritingReferenceSearchSnapshot:
    request = WritingReferenceSearchRequest(
        indication="Atopic Dermatitis",
        phases=["PHASE2"],
    )
    return WritingReferenceSearchSnapshot(
        snapshot_id="wref_search_candidate_enrichment",
        project_id="proj_candidate_enrichment",
        request=request,
        query_url="https://clinicaltrials.gov/api/v2/studies",
        api_version="2.0",
        data_timestamp="2026-07-24",
        total_count=1,
        returned_count=1,
        page_count=1,
        candidates=[candidate],
        created_by="test",
        created_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
    )


def _journey() -> SimpleNamespace:
    product_profile = SimpleNamespace(
        technology_type="monoclonal_antibody",
        administration_routes=["subcutaneous"],
        dosage_forms=["injection"],
        exposure_scope="systemic",
    )
    framing = SimpleNamespace(
        investigational_product="Example mAb",
        indication="Atopic Dermatitis",
        study_phase="PHASE2",
        intrinsic_objectives=["proof_of_concept"],
        design_pattern="randomized_double_blind_parallel",
        target_mechanism="",
        competitor_target_scope="same_indication",
        product_profile=product_profile,
        population_intent="moderate-to-severe disease",
        clinicaltrials_condition_term="Atopic Dermatitis",
    )
    picos = SimpleNamespace(
        population_summary="Adults with moderate-to-severe atopic dermatitis",
        intervention_summary="Example mAb",
        comparator_summary="Placebo",
        primary_endpoint="EASI-75 at Week 16",
    )
    return SimpleNamespace(framing=framing, picos=picos, revision=3)


class CtgovCandidateEnrichmentTests(unittest.TestCase):
    def test_discovery_fields_and_v2_paths_map_to_structured_candidate(self) -> None:
        expected_fields = {
            "BriefSummary",
            "InterventionName",
            "InterventionType",
            "DesignAllocation",
            "DesignInterventionModel",
            "DesignMasking",
            "EnrollmentCount",
        }
        self.assertTrue(
            expected_fields.issubset(set(CTGOV_DISCOVERY_FIELDS.split(",")))
        )

        candidate = candidate_from_study(_ctgov_study_fixture())

        self.assertIn("concomitant tralokinumab", candidate.brief_summary)
        self.assertEqual(
            [
                ("Tralokinumab", "DRUG"),
                ("Placebo", "DRUG"),
                ("Tdap vaccine", "BIOLOGICAL"),
            ],
            [
                (item.name, item.intervention_type)
                for item in candidate.interventions
            ],
        )
        self.assertEqual("RANDOMIZED", candidate.design_allocation)
        self.assertEqual("PARALLEL", candidate.design_intervention_model)
        self.assertEqual("DOUBLE", candidate.design_masking)
        self.assertEqual(215, candidate.enrollment_count)

    def test_legacy_snapshot_without_new_fields_still_loads(self) -> None:
        legacy_snapshot = {
            "snapshot_id": "legacy_snapshot",
            "project_id": "legacy_project",
            "request": {
                "indication": "Atopic Dermatitis",
                "phases": ["PHASE2"],
            },
            "query_url": "https://clinicaltrials.gov/api/v2/studies",
            "total_count": 1,
            "returned_count": 1,
            "page_count": 1,
            "candidates": [
                {
                    "nct_id": "NCT03562377",
                    "brief_title": "Legacy candidate",
                    "conditions": ["Atopic Dermatitis"],
                    "phases": ["PHASE2"],
                    "study_type": "INTERVENTIONAL",
                    "study_record_url": (
                        "https://clinicaltrials.gov/study/NCT03562377"
                    ),
                }
            ],
            "created_at": "2026-07-14T00:00:00Z",
        }

        loaded = WritingReferenceSearchSnapshot.model_validate(legacy_snapshot)
        candidate = loaded.candidates[0]

        self.assertEqual("", candidate.brief_summary)
        self.assertEqual([], candidate.interventions)
        self.assertEqual("", candidate.design_allocation)
        self.assertEqual("", candidate.design_intervention_model)
        self.assertEqual("", candidate.design_masking)
        self.assertIsNone(candidate.enrollment_count)

    def test_snapshot_hash_changes_for_each_new_medical_fact(self) -> None:
        baseline_hash = _snapshot_hash(_snapshot(_candidate()))
        mutations = {
            "brief_summary": "Active treatment is compared with placebo.",
            "interventions": [
                WritingReferenceTrialIntervention(
                    name="Tralokinumab",
                    intervention_type="DRUG",
                )
            ],
            "design_allocation": "RANDOMIZED",
            "design_intervention_model": "PARALLEL",
            "design_masking": "DOUBLE",
            "enrollment_count": 215,
        }

        for field_name, value in mutations.items():
            with self.subTest(field_name=field_name):
                changed = _snapshot_hash(
                    _snapshot(_candidate(**{field_name: value}))
                )
                self.assertNotEqual(baseline_hash, changed)

    def test_chunk_input_contains_explicit_candidate_facts(self) -> None:
        candidate = candidate_from_study(_ctgov_study_fixture())

        payload = _build_chunk_input(_journey(), [candidate], 0)
        facts = payload["candidates"][0]

        self.assertEqual(candidate.brief_summary, facts["brief_summary"])
        self.assertEqual(
            [
                {"name": "Tralokinumab", "intervention_type": "DRUG"},
                {"name": "Placebo", "intervention_type": "DRUG"},
                {"name": "Tdap vaccine", "intervention_type": "BIOLOGICAL"},
            ],
            facts["interventions"],
        )
        self.assertEqual("RANDOMIZED", facts["design_allocation"])
        self.assertEqual("PARALLEL", facts["design_intervention_model"])
        self.assertEqual("DOUBLE", facts["design_masking"])
        self.assertEqual(215, facts["enrollment_count"])

    def test_missing_registry_facts_remain_empty_and_prompt_forbids_inference(
        self,
    ) -> None:
        payload = _build_chunk_input(_journey(), [_candidate()], 0)
        facts = payload["candidates"][0]

        self.assertEqual("", facts["brief_summary"])
        self.assertEqual([], facts["interventions"])
        self.assertEqual("", facts["design_allocation"])
        self.assertEqual("", facts["design_intervention_model"])
        self.assertEqual("", facts["design_masking"])
        self.assertIsNone(facts["enrollment_count"])
        self.assertNotIn("unknown", facts.values())

        prompt = _build_system_prompt()
        self.assertIn("prioritize its supplied brief summary", prompt)
        self.assertIn("record the missing fact in evidence_gaps", prompt)
        self.assertIn(
            "never infer target, route, or modality from an absent field",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
