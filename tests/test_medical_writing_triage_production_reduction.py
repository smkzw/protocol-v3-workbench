"""Production-scale, source-bounded competitor-triage reduction tests."""

from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import (
    CompetitorTriageCreateRequest,
    WritingReferenceTrialIntervention,
)
from services.api.app.medical_writing_competitor_triage import (
    CompetitorTriageError,
    MAX_AI_CANDIDATES_PER_CHUNK,
    MAX_AI_CHUNK_INPUT_CHARS,
    TRIAGE_DETERMINISTIC_POLICY_VERSION,
    _build_chunk_input,
    _build_triage_reduction_plan,
    _canonical_json_local,
    _material_facts_hash,
    _snapshot_hash,
)
from tests.test_medical_writing_competitor_triage import (
    FakeTriageProvider,
    TriageTestBase,
    _make_candidate,
    _make_candidate_result,
    _make_snapshot,
)


class TestProductionTriageReduction(TriageTestBase):
    def _plan(self, candidates):
        journey = self.journey_service.get(self.project_id)
        snapshot = _make_snapshot(
            self.project_id,
            candidates,
            snapshot_id="wref_search_production_reduction",
        )
        return (
            journey,
            snapshot,
            _build_triage_reduction_plan(
                journey,
                snapshot,
                _snapshot_hash(snapshot),
                _material_facts_hash(journey),
            ),
        )

    def test_652_item_snapshot_has_complete_auditable_partition_and_few_ai_calls(self):
        """No NCT may disappear when deterministic gates reduce AI workload."""
        candidates = []
        # Lexically different indications still require AI because project
        # facts may be Chinese while registry terms are English or acronyms.
        candidates.extend(
            _make_candidate(
                f"NCT9{index:07d}",
                conditions=["Psoriatic Arthritis"],
            )
            for index in range(1, 501)
        )
        # Same indication but no public Protocol/SAP: not a corpus input.
        candidates.extend(
            _make_candidate(
                f"NCT8{index:07d}",
                docs=[],
            )
            for index in range(1, 61)
        )
        # Explicit device-only interventions are not drug/biologic protocol corpus.
        candidates.extend(
            _make_candidate(
                f"NCT7{index:07d}",
            ).model_copy(
                update={
                    "interventions": [
                        WritingReferenceTrialIntervention(
                            name="Study device", intervention_type="DEVICE"
                        )
                    ]
                }
            )
            for index in range(1, 11)
        )
        # Same indication and public protocol but no explicit intervention type:
        # uncertainty is retained for AI, never deterministically excluded.
        candidates.extend(
            _make_candidate(f"NCT6{index:07d}")
            for index in range(1, 83)
        )
        self.assertEqual(652, len(candidates))

        journey, snapshot, plan = self._plan(candidates)
        deterministic_ids = [
            nct_id
            for chunk in plan.deterministic_chunks
            for nct_id in chunk.nct_ids
        ]
        ai_ids = [
            candidate.nct_id
            for chunk in plan.ai_candidate_chunks
            for candidate in chunk
        ]

        self.assertEqual(
            {candidate.nct_id for candidate in snapshot.candidates},
            set(deterministic_ids) | set(ai_ids),
        )
        self.assertEqual(652, len(deterministic_ids) + len(ai_ids))
        self.assertEqual(len(deterministic_ids), len(set(deterministic_ids)))
        self.assertEqual(len(ai_ids), len(set(ai_ids)))
        self.assertEqual(60, plan.disposition_counts["no_public_protocol"])
        self.assertEqual(
            10,
            plan.disposition_counts["explicit_non_pharmacologic_intervention"],
        )
        self.assertEqual(582, plan.disposition_counts["requires_source_bounded_ai_triage"])
        self.assertEqual(582, plan.ai_candidate_count)
        self.assertEqual(117, len(plan.ai_candidate_chunks))
        self.assertLess(len(plan.ai_candidate_chunks), 120)

        for chunk in plan.deterministic_chunks:
            self.assertTrue(chunk.chunk_id.startswith("ct_det_"))
            self.assertEqual("succeeded", chunk.status.value)
            self.assertEqual(
                TRIAGE_DETERMINISTIC_POLICY_VERSION,
                chunk.provenance.prompt_version,
            )
            self.assertEqual(chunk.nct_ids, [result.nct_id for result in chunk.results])
            self.assertTrue(all(result.reason.startswith("确定性未进入语料") for result in chunk.results))

        for index, chunk in enumerate(plan.ai_candidate_chunks):
            self.assertLessEqual(len(chunk), MAX_AI_CANDIDATES_PER_CHUNK)
            payload = _build_chunk_input(journey, chunk, index)
            if len(chunk) > 1:
                self.assertLessEqual(
                    len(_canonical_json_local(payload)), MAX_AI_CHUNK_INPUT_CHARS
                )

    def test_unknown_intervention_metadata_stays_in_ai_basket(self):
        _, _, plan = self._plan([_make_candidate("NCT60000001")])
        self.assertEqual(0, plan.deterministic_candidate_count)
        self.assertEqual(["NCT60000001"], [
            candidate.nct_id for candidate in plan.ai_candidate_chunks[0]
        ])

    def test_phase_mismatch_is_ranked_but_not_deterministically_excluded(self):
        _, _, plan = self._plan(
            [_make_candidate("NCT60000002", phases=["PHASE3"])]
        )
        self.assertEqual(0, plan.deterministic_candidate_count)
        self.assertEqual(1, plan.ai_candidate_count)

    def test_lexical_indication_mismatch_stays_in_ai_basket(self):
        _, _, plan = self._plan(
            [
                _make_candidate(
                    "NCT60000004",
                    conditions=["Paroxysmal Nocturnal Hemoglobinuria (PNH)"],
                )
            ]
        )
        self.assertEqual(0, plan.deterministic_candidate_count)
        self.assertEqual(1, plan.ai_candidate_count)

    def test_no_public_document_is_audit_exclusion_not_silent_drop(self):
        _, _, plan = self._plan([_make_candidate("NCT80000001", docs=[])])
        self.assertEqual(1, plan.deterministic_candidate_count)
        result = plan.deterministic_chunks[0].results[0]
        self.assertEqual("excluded", result.classification.value)
        self.assertTrue(
            any("no_public_protocol" in gap for gap in result.evidence_gaps)
        )
        self.assertIn("不等同于否定其临床研究价值", result.reason)

    def test_duplicate_snapshot_nct_fails_closed_before_any_ai_batch(self):
        journey = self.journey_service.get(self.project_id)
        duplicate = _make_candidate("NCT60000001")
        snapshot = _make_snapshot(
            self.project_id,
            [duplicate, duplicate],
            snapshot_id="wref_search_duplicate_nct",
        )
        with self.assertRaisesRegex(CompetitorTriageError, "duplicate NCT"):
            _build_triage_reduction_plan(
                journey,
                snapshot,
                _snapshot_hash(snapshot),
                _material_facts_hash(journey),
            )

    def test_mixed_run_reports_actual_ai_route_not_deterministic_route(self):
        snapshot = self._bind_snapshot(
            [
                _make_candidate("NCT80000002", docs=[]),
                _make_candidate("NCT60000003"),
            ]
        )
        journey = self.journey_service.get(self.project_id)
        provider = FakeTriageProvider(
            responses_by_chunk={
                1: {"results": [_make_candidate_result("NCT60000003")]}
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
                idempotency_key="mixed-deterministic-and-ai-route",
            ),
            provider,
        )
        self.assertEqual("deepseek", response.run.provider)
        self.assertEqual("deepseek-v4-pro", response.run.response_model)
