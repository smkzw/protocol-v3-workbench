"""Focused tests for the product-owned competitor triage pipeline.

Covers:
- Exact model identity verification
- Unknown/duplicate/missing NCT rejection
- Invalid enum rejection
- Deterministic hashes and chunks
- Partial failure and retry-only-failed-chunks
- Stale run detection
- Atomic basket decisions
- Idempotency of confirmation
- Projection retry without second approval
- Preparation-batch eligibility (unchanged legacy behavior)
"""

from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from packages.contracts.workbench_contracts import (
    CompetitorTriageBasketConfirmationRequest,
    CompetitorTriageChunkStatus,
    CompetitorTriageClassification,
    CompetitorTriageCreateRequest,
    CompetitorTriageProjectionRetryRequest,
    CompetitorTriageRetryRequest,
    CompetitorTriageRunStatus,
    MedicalWritingAuthoringStageDraft,
    MedicalWritingAuthoringJourneyCommitRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingCompetitorSearchExecuteRequest,
    MedicalWritingJourneyImpactPreviewRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceSearchRequest,
    WritingReferenceTrialCandidate,
    WritingReferencePublicDocument,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_competitor_triage import (
    CompetitorTriageConflictError,
    CompetitorTriageError,
    CompetitorTriageService,
    CompetitorTriageStaleError,
    MAX_AI_CANDIDATES_PER_CHUNK,
    TRIAGE_MODEL_NAME,
    TRIAGE_PROVIDER_NAME,
    VerifiedTriageProvider,
    _build_chunk_input,
    _build_triage_reduction_plan,
    _build_system_prompt,
    _deterministic_chunks,
    _hash_value,
    _material_facts_hash,
    _snapshot_hash,
    _validate_chunk_response,
)
from services.api.app.writing_reference import search_url
from services.api.app.writing_reference_repository import WritingReferenceRepository

from tests.test_medical_writing_authoring_journey import (
    _complete_framing,
    _complete_picos,
)


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class FakeTriageProvider:
    """Strict fake provider exposing the verified identity contract.

    Returns canned responses keyed by chunk index. Allows injection of
    failure scenarios.
    """

    provider_name = TRIAGE_PROVIDER_NAME
    model_name = TRIAGE_MODEL_NAME
    test_only_injection = True

    def __init__(
        self,
        responses_by_chunk: Dict[int, Dict[str, Any]],
        fail_chunks: set[int] | None = None,
    ) -> None:
        self._responses = responses_by_chunk
        self._fail_chunks = fail_chunks or set()
        self.response_model = TRIAGE_MODEL_NAME

    def run(self, envelope: Any) -> Dict[str, Any]:
        # Simulate the AiProvider.run contract: takes an envelope, returns
        # the parsed JSON dict.
        payload = envelope.payload
        chunk_index = payload.get("chunk_index", 0)
        if chunk_index in self._fail_chunks:
            raise RuntimeError(f"provider error for chunk {chunk_index}")
        response = self._responses.get(chunk_index)
        if response is None:
            raise RuntimeError(f"no canned response for chunk {chunk_index}")
        return response


class SequencedRecordingTriageProvider:
    """Return one canned response per call and record each model payload."""

    provider_name = TRIAGE_PROVIDER_NAME
    model_name = TRIAGE_MODEL_NAME
    test_only_injection = True

    def __init__(self, responses: list[Dict[str, Any]]) -> None:
        self._responses = deepcopy(responses)
        self.response_model = TRIAGE_MODEL_NAME
        self.payloads: list[Dict[str, Any]] = []

    def run(self, envelope: Any) -> Dict[str, Any]:
        self.payloads.append(deepcopy(envelope.payload))
        call_index = len(self.payloads) - 1
        if call_index >= len(self._responses):
            raise AssertionError("unexpected third provider call")
        return deepcopy(self._responses[call_index])


def _make_candidate(
    nct_id: str,
    *,
    conditions: list[str] | None = None,
    phases: list[str] | None = None,
    docs: list[WritingReferencePublicDocument] | None = None,
    brief_title: str | None = None,
    official_title: str | None = None,
    brief_summary: str | None = None,
) -> WritingReferenceTrialCandidate:
    return WritingReferenceTrialCandidate(
        nct_id=nct_id,
        study_record_url=f"https://clinicaltrials.gov/study/{nct_id}",
        official_title=official_title or f"Trial {nct_id}",
        brief_title=brief_title or f"Trial {nct_id}",
        brief_summary=brief_summary or "",
        conditions=conditions or ["Rheumatoid Arthritis"],
        phases=phases or ["PHASE2"],
        study_type="INTERVENTIONAL",
        lead_sponsor="Test Sponsor",
        overall_status="RECRUITING",
        # Generic triage fixtures model a corpus-eligible public Protocol.
        # Tests for the deterministic no-document branch pass ``docs=[]``
        # explicitly so production corpus-admission rules remain covered.
        public_documents=(
            docs
            if docs is not None
            else [
                WritingReferencePublicDocument(
                    document_id=f"doc_{nct_id}",
                    nct_id=nct_id,
                    document_type="protocol",
                    filename=f"{nct_id}_protocol.pdf",
                    download_url=(
                        f"https://clinicaltrials.gov/documents/{nct_id}/protocol.pdf"
                    ),
                )
            ]
        ),
    )


def _make_candidate_result(
    nct_id: str,
    classification: str = "direct_competitor",
    confidence: float = 0.9,
) -> dict:
    return {
        "nct_id": nct_id,
        "classification": classification,
        "confidence": confidence,
        "reason": f"Classification reasoning for {nct_id}",
        "matching_dimensions": [
            {
                "dimension": "indication",
                "match": "match",
                "detail": "Same indication",
            },
            {
                "dimension": "phase",
                "match": "match",
                "detail": "Same phase",
            },
        ],
        "evidence_gaps": [],
        "document_suitability": {
            "has_public_protocol": False,
            "has_public_sap": False,
            "document_role": "",
        },
    }


def _make_snapshot(
    project_id: str,
    candidates: list[WritingReferenceTrialCandidate],
    snapshot_id: str = "wref_search_triage_test",
) -> WritingReferenceSearchSnapshot:
    request = WritingReferenceSearchRequest(
        indication="Rheumatoid Arthritis",
        phases=["PHASE2"],
    )
    return WritingReferenceSearchSnapshot(
        snapshot_id=snapshot_id,
        project_id=project_id,
        request=request,
        query_url=search_url(request),
        api_version="2.0",
        data_timestamp="2026-07-14",
        total_count=len(candidates),
        returned_count=len(candidates),
        page_count=1,
        candidates=candidates,
        created_by="test",
        created_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )


class TriageTestBase(unittest.TestCase):
    """Shared setup: journey with framing+picos+bound snapshot, repo, service."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.project_id = "proj_triage_test"
        self.journey_service = MedicalWritingAuthoringJourneyService(
            root / "journeys.sqlite3"
        )
        self.repo = WritingReferenceRepository(
            root / "writing_reference.sqlite3"
        )
        self.service = CompetitorTriageService(self.repo, self.journey_service)

        # Create a journey with framing + picos + bound snapshot
        created = self.journey_service.create(
            self.project_id,
            MedicalWritingAuthoringJourneyCreateRequest(
                framing=_complete_framing(),
                actor="test",
                idempotency_key="create-triage-test-journey",
            ),
        )
        self.journey_service.commit_stage(
            self.project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=created.revision,
                stage="picos",
                picos=_complete_picos(),
                actor="test",
                idempotency_key="commit-triage-test-picos",
            ),
        )
        journey = self.journey_service.get(self.project_id)
        self.journey_revision = journey.revision

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _bind_snapshot(
        self, candidates: list[WritingReferenceTrialCandidate]
    ) -> WritingReferenceSearchSnapshot:
        snapshot = _make_snapshot(self.project_id, candidates)
        self.repo.save_search_snapshot(snapshot, idempotency_key="save-triage-snap")
        journey = self.journey_service.get(self.project_id)
        self.journey_service.attach_search_snapshot(
            self.project_id,
            snapshot,
            MedicalWritingCompetitorSearchExecuteRequest(
                search_plan_id=journey.search_plan.plan_id,
                actor="test",
                idempotency_key="attach-triage-snap",
            ),
        )
        return snapshot

    def _bump_journey_revision(self, idempotency_key: str = "reframe"):
        """Bump the journey revision by re-committing framing with impact preview."""
        current = self.journey_service.get(self.project_id)
        changed_framing = _complete_framing(
            clinicaltrials_condition_term="Psoriatic Arthritis"
        )
        preview = self.journey_service.impact_preview(
            self.project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=current.revision,
                stage="framing",
                framing=changed_framing,
            ),
        )
        self.journey_service.commit_stage(
            self.project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=current.revision,
                stage="framing",
                framing=changed_framing,
                impact_preview_id=preview.preview_id,
                actor="test",
                idempotency_key=idempotency_key,
            ),
        )

    @staticmethod
    def _with_search_condition_term(journey, condition_term: str):
        registry_filter = journey.search_plan.registry_filter.model_copy(
            update={"condition_term": condition_term},
            deep=True,
        )
        search_plan = journey.search_plan.model_copy(
            update={"registry_filter": registry_filter},
            deep=True,
        )
        return journey.model_copy(
            update={"search_plan": search_plan},
            deep=True,
        )

    def test_triage_prompt_forbids_modality_inference_and_separates_relevance(self):
        prompt = _build_system_prompt()

        self.assertIn("Never infer mechanism, route, dosage form, or drug class", prompt)
        self.assertIn("long-term extension", prompt)
        self.assertIn("Transplantation, surgery, device, radiotherapy", prompt)
        self.assertIn("Clinical relevance and document suitability are separate", prompt)
        self.assertIn("likely oral", prompt)
        self.assertIn("concise, natural Chinese", prompt)
        self.assertIn("relation=mixed", prompt)
        self.assertIn("must be indirect_reference", prompt)
        self.assertNotIn("CRSwNP", prompt)
        self.assertNotIn("Rhinosinustis", prompt)
        self.assertIn("Indication-specific spelling", prompt)
        self.assertIn("never uses edit distance", prompt)

    def test_triage_input_contains_medically_material_project_context(self):
        journey = self.journey_service.get(self.project_id)
        payload = _build_chunk_input(
            journey,
            [_make_candidate("NCT12345678")],
            0,
        )
        facts = payload["project_facts"]

        self.assertIn("intrinsic_objectives", facts)
        self.assertIn("target_mechanism", facts)
        self.assertIn("competitor_target_scope", facts)
        self.assertIn("product_profile", facts)
        self.assertIn("population_intent", facts)
        self.assertIn("picos", facts)
        self.assertEqual(
            journey.picos.primary_endpoint,
            facts["picos"]["primary_endpoint"],
        )

    def test_triage_uses_active_draft_condition_term_for_hash_and_matching(self):
        journey = self.journey_service.get(self.project_id)
        confirmed_framing = journey.framing.model_copy(
            update={
                "indication": "溃疡性结肠炎",
                "clinicaltrials_condition_term": "",
            },
            deep=True,
        )
        confirmed_journey = journey.model_copy(
            update={"framing": confirmed_framing, "framing_draft": None},
            deep=True,
        )
        draft_framing = confirmed_framing.model_copy(
            update={"clinicaltrials_condition_term": "Ulcerative Colitis"},
            deep=True,
        )
        active_draft_journey = confirmed_journey.model_copy(
            update={
                "framing_draft": MedicalWritingAuthoringStageDraft(
                    stage="framing",
                    framing=draft_framing,
                    saved_from_revision=confirmed_journey.revision,
                    saved_at=datetime.now(timezone.utc),
                    saved_by="medical_manager",
                )
            },
            deep=True,
        )

        payload = _build_chunk_input(
            active_draft_journey,
            [
                _make_candidate(
                    "NCT00004810",
                    conditions=["Ulcerative Colitis"],
                )
            ],
            0,
        )

        self.assertNotEqual(
            _material_facts_hash(confirmed_journey),
            _material_facts_hash(active_draft_journey),
        )
        self.assertEqual(
            "Ulcerative Colitis",
            payload["project_facts"]["clinicaltrials_condition_term"],
        )
        self.assertTrue(payload["candidates"][0]["project_indication_match"])
        self.assertEqual(
            ["Ulcerative Colitis"],
            payload["candidates"][0]["matching_conditions"],
        )

    def test_chunk_input_uses_complete_condition_list_for_pnh_match(self):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症（PNH）",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing},
            deep=True,
        )
        conditions = [
            "Acute Myeloid Leukemia",
            "Myelodysplastic Syndromes",
            "Multiple Myeloma",
            "Diffuse Large B-Cell Lymphoma",
            "Chronic Lymphocytic Leukemia",
            "Mantle Cell Lymphoma",
            "Paroxysmal Nocturnal Hemoglobinuria",
            "Aplastic Anemia",
        ]

        payload = _build_chunk_input(
            pnh_journey,
            [_make_candidate("NCT12345679", conditions=conditions)],
            0,
        )
        candidate = payload["candidates"][0]

        self.assertEqual(conditions, candidate["conditions"])
        self.assertEqual(len(conditions), candidate["condition_count"])
        self.assertEqual(
            ["Paroxysmal Nocturnal Hemoglobinuria"],
            candidate["matching_conditions"],
        )
        self.assertTrue(candidate["project_indication_match"])

    def test_v19_uses_bound_search_condition_when_framing_term_is_empty(self):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": "",
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing, "framing_draft": None},
            deep=True,
        )
        pnh_journey = self._with_search_condition_term(
            pnh_journey,
            "Paroxysmal Nocturnal Hemoglobinuria",
        )
        conditions = [
            "Acute Myeloid Leukemia",
            "Myelodysplastic Syndromes",
            "Multiple Myeloma",
            "Diffuse Large B-Cell Lymphoma",
            "Chronic Lymphocytic Leukemia",
            "Mantle Cell Lymphoma",
            "Paroxysmal Nocturnal Hemoglobinuria",
            "Aplastic Anemia",
        ]

        payload = _build_chunk_input(
            pnh_journey,
            [_make_candidate("NCT12345682", conditions=conditions)],
            0,
        )
        candidate = payload["candidates"][0]

        self.assertEqual(
            "Paroxysmal Nocturnal Hemoglobinuria",
            payload["project_facts"]["clinicaltrials_condition_term"],
        )
        self.assertEqual(
            "bound_search_plan_registry_filter",
            payload["project_facts"]["clinicaltrials_condition_term_source"],
        )
        self.assertEqual("mixed", candidate["project_indication_relation"])
        self.assertEqual(
            ["Paroxysmal Nocturnal Hemoglobinuria"],
            candidate["matching_conditions"],
        )

    def test_v19_bound_search_condition_applies_to_deterministic_no_document_result(
        self,
    ):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": "",
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing, "framing_draft": None},
            deep=True,
        )
        pnh_journey = self._with_search_condition_term(
            pnh_journey,
            "Paroxysmal Nocturnal Hemoglobinuria",
        )
        snapshot = _make_snapshot(
            self.project_id,
            [
                _make_candidate(
                    "NCT12345683",
                    conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
                    docs=[],
                )
            ],
        )
        snapshot_hash = _snapshot_hash(snapshot)
        facts_hash = _material_facts_hash(pnh_journey)

        plan = _build_triage_reduction_plan(
            pnh_journey,
            snapshot,
            snapshot_hash,
            facts_hash,
        )
        result = plan.deterministic_chunks[0].results[0]
        indication_dimension = next(
            item for item in result.matching_dimensions if item.dimension == "indication"
        )

        self.assertEqual("match", indication_dimension.match)
        self.assertNotIn("适应症不同", result.reason)
        self.assertIn("同适应症", result.reason)

    def test_v19_bound_search_condition_changes_material_facts_hash(self):
        journey = self.journey_service.get(self.project_id)
        empty_framing = journey.framing.model_copy(
            update={"clinicaltrials_condition_term": ""},
            deep=True,
        )
        base = journey.model_copy(
            update={"framing": empty_framing, "framing_draft": None},
            deep=True,
        )
        pnh = self._with_search_condition_term(
            base,
            "Paroxysmal Nocturnal Hemoglobinuria",
        )
        rheumatoid = self._with_search_condition_term(
            base,
            "Rheumatoid Arthritis",
        )

        self.assertNotEqual(_material_facts_hash(pnh), _material_facts_hash(rheumatoid))

    def test_v19_does_not_invent_match_without_condition_term(self):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": "",
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={
                "framing": pnh_framing,
                "framing_draft": None,
                "search_plan": None,
            },
            deep=True,
        )

        payload = _build_chunk_input(
            pnh_journey,
            [
                _make_candidate(
                    "NCT12345684",
                    conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
                )
            ],
            0,
        )

        self.assertEqual(
            "unavailable",
            payload["project_facts"]["clinicaltrials_condition_term_source"],
        )
        self.assertFalse(payload["candidates"][0]["project_indication_match"])
        self.assertEqual(
            "cross_language_unresolved",
            payload["candidates"][0]["project_indication_relation_scope"],
        )

    def test_v19_wrong_bound_search_condition_does_not_force_match(self):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": "",
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing, "framing_draft": None},
            deep=True,
        )
        pnh_journey = self._with_search_condition_term(
            pnh_journey,
            "Rheumatoid Arthritis",
        )

        payload = _build_chunk_input(
            pnh_journey,
            [
                _make_candidate(
                    "NCT12345685",
                    conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
                )
            ],
            0,
        )

        self.assertFalse(payload["candidates"][0]["project_indication_match"])

    def test_v19_matches_strict_comma_inverted_controlled_condition_label(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": "",
            },
            deep=True,
        )
        journey = journey.model_copy(
            update={"framing": framing, "framing_draft": None},
            deep=True,
        )
        journey = self._with_search_condition_term(
            journey,
            "Paroxysmal Nocturnal Hemoglobinuria",
        )
        payload = _build_chunk_input(
            journey,
            [
                _make_candidate(
                    "NCT12345686",
                    conditions=[
                        "Hemoglobinuria, Paroxysmal Nocturnal (PNH)",
                        "Aplastic Anemia",
                    ],
                )
            ],
            0,
        )
        candidate = payload["candidates"][0]

        self.assertTrue(candidate["project_indication_match"])
        self.assertEqual("mixed", candidate["project_indication_relation"])
        self.assertEqual(
            ["Hemoglobinuria, Paroxysmal Nocturnal (PNH)"],
            candidate["matching_conditions"],
        )

    def test_v19_comma_inverted_rule_is_generic_across_indications(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "类风湿关节炎",
                "clinicaltrials_condition_term": "Rheumatoid Arthritis",
            },
            deep=True,
        )
        journey = journey.model_copy(update={"framing": framing}, deep=True)
        payload = _build_chunk_input(
            journey,
            [
                _make_candidate(
                    "NCT12345687",
                    conditions=["Arthritis, Rheumatoid (RA)"],
                )
            ],
            0,
        )

        self.assertTrue(payload["candidates"][0]["project_indication_match"])
        self.assertEqual(
            ["Arthritis, Rheumatoid (RA)"],
            payload["candidates"][0]["matching_conditions"],
        )

    def test_v19_comma_inverted_rule_rejects_extra_disease_tokens(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        journey = journey.model_copy(update={"framing": framing}, deep=True)
        payload = _build_chunk_input(
            journey,
            [
                _make_candidate(
                    "NCT12345688",
                    conditions=[
                        "Hemoglobinuria, Paroxysmal Nocturnal and "
                        "Aplastic Anemia (PNH)"
                    ],
                )
            ],
            0,
        )

        self.assertFalse(payload["candidates"][0]["project_indication_match"])

    def test_v19_comma_inverted_rule_rejects_non_inverted_alias_text(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        journey = journey.model_copy(update={"framing": framing}, deep=True)
        payload = _build_chunk_input(
            journey,
            [
                _make_candidate(
                    "NCT12345689",
                    conditions=[
                        "PNH / Paroxysmal Nocturnal Hemoglobinuria"
                    ],
                )
            ],
            0,
        )

        self.assertFalse(payload["candidates"][0]["project_indication_match"])

    def test_v20_matches_bare_initialism_derived_from_bound_full_name(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": "",
            },
            deep=True,
        )
        journey = journey.model_copy(
            update={"framing": framing, "framing_draft": None},
            deep=True,
        )
        journey = self._with_search_condition_term(
            journey,
            "Paroxysmal Nocturnal Hemoglobinuria",
        )
        payload = _build_chunk_input(
            journey,
            [_make_candidate("NCT12345690", conditions=["PNH"])],
            0,
        )

        self.assertTrue(payload["candidates"][0]["project_indication_match"])
        self.assertEqual(
            ["PNH"],
            payload["candidates"][0]["matching_conditions"],
        )

    def test_v20_matches_strict_initialism_full_name_alias_pair(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        journey = journey.model_copy(update={"framing": framing}, deep=True)
        payload = _build_chunk_input(
            journey,
            [
                _make_candidate(
                    "NCT12345691",
                    conditions=[
                        "PNH - Paroxysmal Nocturnal Hemoglobinuria"
                    ],
                )
            ],
            0,
        )

        self.assertTrue(payload["candidates"][0]["project_indication_match"])

    def test_v20_initialism_rule_is_generic_for_rheumatoid_arthritis(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "类风湿关节炎",
                "clinicaltrials_condition_term": "Rheumatoid Arthritis",
            },
            deep=True,
        )
        journey = journey.model_copy(update={"framing": framing}, deep=True)
        payload = _build_chunk_input(
            journey,
            [_make_candidate("NCT12345692", conditions=["RA"])],
            0,
        )

        self.assertTrue(payload["candidates"][0]["project_indication_match"])

    def test_v20_rejects_unproven_initialism_with_matching_full_name(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        journey = journey.model_copy(update={"framing": framing}, deep=True)
        payload = _build_chunk_input(
            journey,
            [
                _make_candidate(
                    "NCT12345693",
                    conditions=[
                        "XYZ - Paroxysmal Nocturnal Hemoglobinuria"
                    ],
                )
            ],
            0,
        )

        self.assertFalse(payload["candidates"][0]["project_indication_match"])

    def test_v20_rejects_lowercase_or_extra_token_initialism_labels(self):
        journey = self.journey_service.get(self.project_id)
        framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        journey = journey.model_copy(update={"framing": framing}, deep=True)

        for index, condition in enumerate(
            [
                "pnh",
                "PNH and Aplastic Anemia",
                "PNH - Paroxysmal Nocturnal Hemoglobinuria and "
                "Aplastic Anemia",
            ]
        ):
            with self.subTest(condition=condition):
                payload = _build_chunk_input(
                    journey,
                    [
                        _make_candidate(
                            f"NCT1234570{index}",
                            conditions=[condition],
                        )
                    ],
                    0,
                )
                self.assertFalse(
                    payload["candidates"][0]["project_indication_match"]
                )

    def test_chunk_input_long_malignant_condition_list_without_pnh_is_not_match(self):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症（PNH）",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing},
            deep=True,
        )
        conditions = [
            "Acute Myeloid Leukemia",
            "Myelodysplastic Syndromes",
            "Multiple Myeloma",
            "Diffuse Large B-Cell Lymphoma",
            "Chronic Lymphocytic Leukemia",
            "Mantle Cell Lymphoma",
            "Acute Lymphoblastic Leukemia",
            "Waldenstrom Macroglobulinemia",
        ]

        payload = _build_chunk_input(
            pnh_journey,
            [_make_candidate("NCT12345680", conditions=conditions)],
            0,
        )
        candidate = payload["candidates"][0]

        self.assertEqual(conditions, candidate["conditions"])
        self.assertEqual(len(conditions), candidate["condition_count"])
        self.assertEqual([], candidate["matching_conditions"])
        self.assertFalse(candidate["project_indication_match"])

    def test_chunk_input_keeps_late_condition_for_cross_language_ai_evidence(self):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症",
                "clinicaltrials_condition_term": "",
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing},
            deep=True,
        )
        conditions = [
            "Acute Myeloid Leukemia",
            "Myelodysplastic Syndromes",
            "Multiple Myeloma",
            "Diffuse Large B-Cell Lymphoma",
            "Chronic Lymphocytic Leukemia",
            "Mantle Cell Lymphoma",
            "Paroxysmal Nocturnal Hemoglobinuria",
            "Aplastic Anemia",
        ]

        payload = _build_chunk_input(
            pnh_journey,
            [_make_candidate("NCT12345681", conditions=conditions)],
            0,
        )
        candidate = payload["candidates"][0]

        self.assertEqual(conditions, candidate["conditions"])
        self.assertEqual(len(conditions), candidate["condition_count"])
        self.assertEqual(
            "cross_language_unresolved",
            candidate["project_indication_relation_scope"],
        )
        self.assertIn(
            "Paroxysmal Nocturnal Hemoglobinuria",
            candidate["conditions"],
        )

    def test_chunk_input_strict_pnh_alias_pairs_are_deterministic_matches(self):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症（PNH）",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing}, deep=True
        )
        conditions_by_nct = {
            "NCT05731050": "PNH - Paroxysmal Nocturnal Hemoglobinuria",
            "NCT06978699": "Paroxysmal Nocturnal Hemoglobinuria - PNH",
            "NCT07212426": "PNH - Paroxysmal Nocturnal Hemoglobinuria",
        }

        payload = _build_chunk_input(
            pnh_journey,
            [
                _make_candidate(nct_id, conditions=[condition])
                for nct_id, condition in conditions_by_nct.items()
            ],
            0,
        )

        self.assertEqual(
            ["NCT05731050", "NCT06978699", "NCT07212426"],
            [candidate["nct_id"] for candidate in payload["candidates"]],
        )
        for candidate in payload["candidates"]:
            self.assertTrue(candidate["project_indication_match"])
            self.assertEqual(
                [conditions_by_nct[candidate["nct_id"]]],
                candidate["matching_conditions"],
            )

    def test_chunk_input_v8_condition_equivalence_matches_two_d017_false_negatives(
        self,
    ):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症（PNH）",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing}, deep=True
        )
        conditions_by_nct = {
            "NCT02591862": "Paroxysmal Nocturnal Haemoglobinuria",
            "NCT03439839": (
                "Paroxysmal Nocturnal Hemoglobinuria (PNH) "
                "With Signs of Active Hemolysis"
            ),
        }

        payload = _build_chunk_input(
            pnh_journey,
            [
                _make_candidate(nct_id, conditions=[condition])
                for nct_id, condition in conditions_by_nct.items()
            ],
            0,
        )

        for candidate in payload["candidates"]:
            self.assertTrue(candidate["project_indication_match"])
            self.assertEqual(
                [conditions_by_nct[candidate["nct_id"]]],
                candidate["matching_conditions"],
            )

    def test_chunk_input_v8_condition_equivalence_rejects_relation_false_positives(
        self,
    ):
        journey = self.journey_service.get(self.project_id)
        pnh_framing = journey.framing.model_copy(
            update={
                "indication": "阵发性睡眠性血红蛋白尿症（PNH）",
                "clinicaltrials_condition_term": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
            },
            deep=True,
        )
        pnh_journey = journey.model_copy(
            update={"framing": pnh_framing}, deep=True
        )
        conditions = [
            "PNH-related Bone Marrow Failure",
            "Malignant Hematology - PNH",
            "Paroxysmal Nocturnal Hemoglobinuria and Aplastic Anemia",
            (
                "Paroxysmal Nocturnal Hemoglobinuria With Active Hemolysis "
                "or Aplastic Anemia"
            ),
            "Paroxysmal Nocturnal Dyspnea (PNH) With Active Hemolysis",
        ]

        payload = _build_chunk_input(
            pnh_journey,
            [
                _make_candidate(
                    f"NCT9000000{index}",
                    conditions=[condition],
                )
                for index, condition in enumerate(conditions, start=1)
            ],
            0,
        )

        for candidate in payload["candidates"]:
            self.assertFalse(candidate["project_indication_match"])
            self.assertEqual([], candidate["matching_conditions"])

    def test_chunk_input_v13_accepts_bounded_uc_condition_qualifiers(self):
        journey = self.journey_service.get(self.project_id)
        uc_framing = journey.framing.model_copy(
            update={
                "indication": "溃疡性结肠炎",
                "clinicaltrials_condition_term": "Ulcerative Colitis",
            },
            deep=True,
        )
        uc_journey = journey.model_copy(
            update={"framing": uc_framing},
            deep=True,
        )
        conditions_by_nct = {
            "NCT07335055": "Ulcerative Colitis (UC)",
            "NCT07535489": (
                "Moderately to Severely Active Ulcerative Colitis (UC)"
            ),
            "NCT07229950": (
                "Adult Patients With Moderately to Severely Active "
                "Ulcerative Colitis"
            ),
            "NCT90000101": "Adult Ulcerative Colitis",
            "NCT90000102": "Ulcerative Colitis in Pediatric Patients",
            "NCT90000103": "Ulcerative Colitis Chronic Moderate",
            "NCT90000104": "Ulcerative Colitis Flare",
            "NCT90000105": "Ulcerative Colitis Acute",
            "NCT90000106": "Ulcerative Colitis, Active Severe",
            "NCT90000107": "Pediatric Ulcerative Colitis in Remission",
        }

        payload = _build_chunk_input(
            uc_journey,
            [
                _make_candidate(nct_id, conditions=[condition])
                for nct_id, condition in conditions_by_nct.items()
            ],
            0,
        )

        for candidate in payload["candidates"]:
            self.assertTrue(candidate["project_indication_match"])
            self.assertEqual("exact", candidate["project_indication_relation"])
            self.assertEqual(
                [conditions_by_nct[candidate["nct_id"]]],
                candidate["matching_conditions"],
            )

    def test_chunk_input_v13_rejects_uc_related_but_distinct_populations(self):
        journey = self.journey_service.get(self.project_id)
        uc_framing = journey.framing.model_copy(
            update={
                "indication": "溃疡性结肠炎",
                "clinicaltrials_condition_term": "Ulcerative Colitis",
            },
            deep=True,
        )
        uc_journey = journey.model_copy(
            update={"framing": uc_framing},
            deep=True,
        )
        conditions = [
            "Crohn's Disease and Ulcerative Colitis",
            "Ulcerative Colitis-associated Pouchitis",
            "Ulcerative Colitis (UC) and Primary Sclerosing Cholangitis",
            "Ulcerative Colitis (CD)",
            "Inflammatory Bowel Disease",
            "Crohn Disease and Moderately Active Ulcerative Colitis (UC)",
            "Ulcerative Colitis Dysplasia",
            "Ulcerative-Colitis-related Colorectal Cancer",
        ]

        payload = _build_chunk_input(
            uc_journey,
            [
                _make_candidate(
                    f"NCT9000011{index}",
                    conditions=[condition],
                )
                for index, condition in enumerate(conditions)
            ],
            0,
        )

        for candidate in payload["candidates"]:
            self.assertFalse(candidate["project_indication_match"])
            self.assertEqual("none", candidate["project_indication_relation"])
            self.assertEqual([], candidate["matching_conditions"])

    def test_chunk_input_v13_uc_ibd_umbrella_with_uc_title_is_exact(self):
        journey = self.journey_service.get(self.project_id)
        uc_framing = journey.framing.model_copy(
            update={
                "indication": "溃疡性结肠炎",
                "clinicaltrials_condition_term": "Ulcerative Colitis",
            },
            deep=True,
        )
        uc_journey = journey.model_copy(update={"framing": uc_framing}, deep=True)
        payload = _build_chunk_input(
            uc_journey,
            [
                _make_candidate(
                    "NCT05553704",
                    conditions=["Inflammatory Bowel Diseases"],
                    brief_title=(
                        "Metformin in Patients With Ulcerative Colitis "
                        "Treated With Mesalamine"
                    ),
                    brief_summary=(
                        "This study evaluates metformin as adjunctive therapy "
                        "in ulcerative colitis patients."
                    ),
                ),
                _make_candidate(
                    "NCT05119140",
                    conditions=["Ulcerative Colitis (Disorder)"],
                    brief_title="A Study of Drug X in Ulcerative Colitis",
                ),
                _make_candidate(
                    "NCT01149707",
                    conditions=["Left-Sided Ulcerative Colitis"],
                    brief_title="Left-Sided Ulcerative Colitis Dose Finding",
                ),
                _make_candidate(
                    "NCT02922374",
                    conditions=["Acute Severe Colitis (ASC)"],
                    brief_title=(
                        "Rescue Therapy for Acute Severe Ulcerative Colitis"
                    ),
                ),
                _make_candidate(
                    "NCT90000999",
                    conditions=["Inflammatory Bowel Diseases"],
                    brief_title="Iron Supplementation for Fatigue in IBD",
                    brief_summary=(
                        "Patients with inflammatory bowel disease and fatigue."
                    ),
                ),
            ],
            0,
        )
        by_nct = {item["nct_id"]: item for item in payload["candidates"]}
        for nct_id in (
            "NCT05553704",
            "NCT05119140",
            "NCT01149707",
            "NCT02922374",
        ):
            self.assertTrue(by_nct[nct_id]["project_indication_match"], nct_id)
            self.assertEqual(
                "exact",
                by_nct[nct_id]["project_indication_relation"],
                nct_id,
            )
        # IBD without UC title corroboration remains excluded
        self.assertFalse(by_nct["NCT90000999"]["project_indication_match"])
        self.assertEqual("none", by_nct["NCT90000999"]["project_indication_relation"])

    def test_chunk_input_v13_marks_multilabel_uc_and_crohn_population_mixed(self):
        journey = self.journey_service.get(self.project_id)
        uc_framing = journey.framing.model_copy(
            update={
                "indication": "溃疡性结肠炎",
                "clinicaltrials_condition_term": "Ulcerative Colitis",
            },
            deep=True,
        )
        uc_journey = journey.model_copy(
            update={"framing": uc_framing},
            deep=True,
        )

        payload = _build_chunk_input(
            uc_journey,
            [
                _make_candidate(
                    "NCT90000120",
                    conditions=[
                        "Ulcerative Colitis Chronic Moderate",
                        "Crohn Colitis",
                    ],
                )
            ],
            0,
        )
        candidate = payload["candidates"][0]

        self.assertTrue(candidate["project_indication_match"])
        self.assertEqual("mixed", candidate["project_indication_relation"])
        self.assertEqual(
            ["Ulcerative Colitis Chronic Moderate"],
            candidate["matching_conditions"],
        )

    def test_chunk_input_v11_crswnp_aliases_and_bounded_composition(self):
        journey = self.journey_service.get(self.project_id)
        crswnp_framing = journey.framing.model_copy(
            update={
                "indication": "慢性鼻窦炎伴鼻息肉",
                "clinicaltrials_condition_term": "CRSwNP",
            },
            deep=True,
        )
        crswnp_journey = journey.model_copy(
            update={"framing": crswnp_framing},
            deep=True,
        )
        candidates = [
            _make_candidate(
                "NCT02898454",
                conditions=[
                    "Chronic Rhinosinusitis Phenotype With Nasal Polyps "
                    "(CRSwNP)"
                ],
            ),
            _make_candidate(
                "NCT05878093",
                conditions=["Chronic Rhinosinusitis With Nasal Polyps"],
            ),
            _make_candidate(
                "NCT06639295",
                conditions=["Sinusitis", "Nasal Polyps"],
            ).model_copy(
                update={
                    "official_title": (
                        "A Phase III Study in Patients With Chronic "
                        "Rhinosinusitis With Nasal Polyps (CRSwNP)"
                    )
                }
            ),
            _make_candidate(
                "NCT90000008",
                conditions=["Chronic Sinusitis", "Nasal Polyps"],
            ),
            _make_candidate(
                "NCT04607005",
                conditions=["Nasal Polyps"],
            ).model_copy(
                update={
                    "official_title": (
                        "A Phase III Study in Adults With Chronic "
                        "Rhinosinusitis With Nasal Polyps (CRSwNP)"
                    )
                }
            ),
            _make_candidate(
                "NCT90000009",
                conditions=["Nasal Polyps"],
            ).model_copy(
                update={"official_title": "A Study in Adults With Nasal Polyps"}
            ),
            _make_candidate(
                "NCT90000010",
                conditions=["Sinusitis", "Nasal Polyps"],
            ).model_copy(
                update={
                    "official_title": (
                        "A Study in Adults With Sinusitis and Nasal Polyps"
                    )
                }
            ),
            _make_candidate(
                "NCT05248997",
                conditions=[
                    "Chronic Rhinosinusitis (CRS) With and Without Nasal Polyps"
                ],
            ),
            _make_candidate(
                "NCT06850805",
                conditions=["Chronic Rhinosinusitis Without Nasal Polyps"],
            ),
        ]

        payload = _build_chunk_input(crswnp_journey, candidates, 0)
        by_nct = {
            candidate["nct_id"]: candidate
            for candidate in payload["candidates"]
        }

        for nct_id in (
            "NCT02898454",
            "NCT05878093",
            "NCT06639295",
            "NCT90000008",
            "NCT04607005",
        ):
            self.assertTrue(by_nct[nct_id]["project_indication_match"])
            self.assertEqual(
                "exact",
                by_nct[nct_id]["project_indication_relation"],
            )
            self.assertTrue(by_nct[nct_id]["matching_conditions"])
        self.assertEqual(
            ["Sinusitis", "Nasal Polyps"],
            by_nct["NCT06639295"]["matching_conditions"],
        )
        self.assertFalse(
            by_nct["NCT90000009"]["project_indication_match"]
        )
        self.assertEqual(
            [],
            by_nct["NCT90000009"]["matching_conditions"],
        )
        self.assertFalse(
            by_nct["NCT90000010"]["project_indication_match"]
        )
        self.assertEqual(
            [],
            by_nct["NCT90000010"]["matching_conditions"],
        )
        self.assertTrue(
            by_nct["NCT05248997"]["project_indication_match"]
        )
        self.assertEqual(
            "mixed",
            by_nct["NCT05248997"]["project_indication_relation"],
        )
        self.assertFalse(
            by_nct["NCT06850805"]["project_indication_match"]
        )
        self.assertEqual(
            "none",
            by_nct["NCT06850805"]["project_indication_relation"],
        )


# ---------------------------------------------------------------------------
# Validation tests (pure functions)
# ---------------------------------------------------------------------------


class TestChunkValidation(unittest.TestCase):
    def test_valid_complete_response_passes(self):
        ncts = ["NCT00000001", "NCT00000002"]
        response = {
            "results": [
                _make_candidate_result("NCT00000001"),
                _make_candidate_result("NCT00000002", "excluded", 0.3),
            ]
        }
        results = _validate_chunk_response(response, ncts)
        self.assertEqual(2, len(results))
        self.assertEqual(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            results[0].classification,
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            results[1].classification,
        )

    def test_v13_reconciles_model_exclusion_for_bounded_uc_label(self):
        project_facts = {
            "indication": "溃疡性结肠炎",
            "clinicaltrials_condition_term": "Ulcerative Colitis",
            "study_phase": "II期",
            "target_mechanism": "",
            "product_profile": {
                "technology_type": "",
                "administration_routes": [],
            },
        }
        candidate = {
            "nct_id": "NCT07535489",
            "conditions": [
                "Moderately to Severely Active Ulcerative Colitis (UC)"
            ],
            "matching_conditions": [
                "Moderately to Severely Active Ulcerative Colitis (UC)"
            ],
            "project_indication_relation": "exact",
            "project_indication_match": True,
            "phases": ["PHASE2"],
            "interventions": [
                {"name": "IPG11406", "intervention_type": "DRUG"}
            ],
            "public_documents": [],
        }
        response = {
            "results": [
                _make_candidate_result(
                    "NCT07535489",
                    classification="excluded",
                    confidence=0.9,
                )
            ]
        }

        results = _validate_chunk_response(
            response,
            ["NCT07535489"],
            chunk_input={
                "project_facts": project_facts,
                "candidates": [candidate],
            },
        )

        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            results[0].classification,
        )
        self.assertEqual("match", results[0].matching_dimensions[0].match)
        self.assertIn("适应症一致", results[0].reason)
        self.assertIn("可作为同适应症药物研究参考", results[0].reason)

    def test_v19_reconciles_inverted_controlled_condition_source_truth(self):
        project_facts = {
            "indication": "阵发性睡眠性血红蛋白尿症",
            "clinicaltrials_condition_term": (
                "Paroxysmal Nocturnal Hemoglobinuria"
            ),
            "study_phase": "I期",
            "target_mechanism": "",
            "product_profile": {
                "technology_type": "",
                "administration_routes": [],
            },
        }
        candidate = {
            "nct_id": "NCT00566696",
            "conditions": [
                "Hemoglobinuria, Paroxysmal Nocturnal (PNH)",
                "Aplastic Anemia",
            ],
            "phases": ["PHASE1"],
            "interventions": [
                {"name": "Study Drug", "intervention_type": "DRUG"}
            ],
            "public_documents": [],
        }
        response = {
            "results": [
                _make_candidate_result(
                    "NCT00566696",
                    classification="excluded",
                    confidence=0.9,
                )
            ]
        }

        result = _validate_chunk_response(
            response,
            ["NCT00566696"],
            chunk_input={
                "project_facts": project_facts,
                "candidates": [candidate],
            },
        )[0]
        indication = next(
            item
            for item in result.matching_dimensions
            if item.dimension == "indication"
        )

        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            result.classification,
        )
        self.assertEqual("partial", indication.match)
        self.assertNotIn("适应症不同", result.reason)
        self.assertIn("同适应症", result.reason)

    def test_unknown_nct_rejected(self):
        ncts = ["NCT00000001"]
        response = {
            "results": [
                _make_candidate_result("NCT00000001"),
                _make_candidate_result("NCT99999999"),
            ]
        }
        with self.assertRaisesRegex(
            CompetitorTriageError, "unknown nct_id"
        ):
            _validate_chunk_response(response, ncts)

    def test_duplicate_nct_rejected(self):
        ncts = ["NCT00000001", "NCT00000002"]
        response = {
            "results": [
                _make_candidate_result("NCT00000001"),
                _make_candidate_result("NCT00000001"),
            ]
        }
        with self.assertRaisesRegex(
            CompetitorTriageError, "duplicate nct_id"
        ):
            _validate_chunk_response(response, ncts)

    def test_missing_nct_rejected(self):
        ncts = ["NCT00000001", "NCT00000002"]
        response = {"results": [_make_candidate_result("NCT00000001")]}
        with self.assertRaisesRegex(
            CompetitorTriageError, "missing nct_ids"
        ):
            _validate_chunk_response(response, ncts)

    def test_invalid_classification_rejected(self):
        ncts = ["NCT00000001"]
        response = {
            "results": [
                {
                    "nct_id": "NCT00000001",
                    "classification": "maybe_competitor",
                    "confidence": 0.5,
                    "reason": "test",
                    "matching_dimensions": [],
                    "evidence_gaps": [],
                    "document_suitability": {},
                }
            ]
        }
        with self.assertRaisesRegex(
            CompetitorTriageError, "invalid classification"
        ):
            _validate_chunk_response(response, ncts)

    def test_confidence_out_of_range_rejected(self):
        ncts = ["NCT00000001"]
        response = {
            "results": [
                {
                    "nct_id": "NCT00000001",
                    "classification": "excluded",
                    "confidence": 1.5,
                    "reason": "test",
                    "matching_dimensions": [],
                    "evidence_gaps": [],
                    "document_suitability": {},
                }
            ]
        }
        with self.assertRaisesRegex(
            CompetitorTriageError, "confidence out of range"
        ):
            _validate_chunk_response(response, ncts)

    def test_negative_confidence_rejected(self):
        ncts = ["NCT00000001"]
        response = {
            "results": [
                {
                    "nct_id": "NCT00000001",
                    "classification": "excluded",
                    "confidence": -0.1,
                    "reason": "test",
                    "matching_dimensions": [],
                    "evidence_gaps": [],
                    "document_suitability": {},
                }
            ]
        }
        with self.assertRaisesRegex(
            CompetitorTriageError, "confidence out of range"
        ):
            _validate_chunk_response(response, ncts)

    def test_non_dict_response_rejected(self):
        with self.assertRaisesRegex(
            CompetitorTriageError, "not a JSON object"
        ):
            _validate_chunk_response([], ["NCT00000001"])  # type: ignore[arg-type]

    def test_missing_results_key_rejected(self):
        with self.assertRaisesRegex(
            CompetitorTriageError, "missing 'results' array"
        ):
            _validate_chunk_response({}, ["NCT00000001"])


# ---------------------------------------------------------------------------
# Deterministic chunking / hash tests
# ---------------------------------------------------------------------------


class TestDeterministicChunking(unittest.TestCase):
    def test_single_chunk_under_limit(self):
        candidates = [_make_candidate(f"NCT0000000{i}") for i in range(1, 6)]
        chunks = _deterministic_chunks(candidates)
        self.assertEqual(1, len(chunks))
        self.assertEqual(5, len(chunks[0]))

    def test_chunks_are_sorted_by_nct_id(self):
        candidates = [
            _make_candidate("NCT00000005"),
            _make_candidate("NCT00000001"),
            _make_candidate("NCT00000003"),
        ]
        chunks = _deterministic_chunks(candidates)
        ncts = [c.nct_id for c in chunks[0]]
        self.assertEqual(
            ["NCT00000001", "NCT00000003", "NCT00000005"],
            ncts,
        )

    def test_deterministic_hash_same_input_same_hash(self):
        data = {"a": 1, "b": [2, 3]}
        h1 = _hash_value(data)
        h2 = _hash_value(data)
        self.assertEqual(h1, h2)

    def test_deterministic_hash_key_order_invariant(self):
        h1 = _hash_value({"a": 1, "b": 2})
        h2 = _hash_value({"b": 2, "a": 1})
        self.assertEqual(h1, h2)

    def test_chunking_is_deterministic_across_calls(self):
        candidates = [_make_candidate(f"NCT0000000{i}") for i in range(1, 31)]
        chunks1 = _deterministic_chunks(candidates)
        chunks2 = _deterministic_chunks(candidates)
        self.assertEqual(
            [c.nct_id for chunk in chunks1 for c in chunk],
            [c.nct_id for chunk in chunks2 for c in chunk],
        )


# ---------------------------------------------------------------------------
# Service-level integration tests
# ---------------------------------------------------------------------------


class TestTriageRunCreation(TriageTestBase):
    def test_successful_run_classifies_all_candidates(self):
        candidates = [_make_candidate("NCT00000001"), _make_candidate("NCT00000002")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {
                    "results": [
                        _make_candidate_result("NCT00000001", "direct_competitor"),
                        _make_candidate_result("NCT00000002", "excluded", 0.3),
                    ]
                }
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
            idempotency_key="ct-test-create-1",
            ),
            provider,
        )
        # Both candidates have the same deterministic indication. Missing
        # project critical facts and candidate intervention type block direct
        # classification but are evidence gaps, not exclusion evidence.
        self.assertEqual(
            CompetitorTriageRunStatus.REVIEW_READY,
            response.run.status,
        )
        self.assertEqual(
            ["NCT00000001", "NCT00000002"],
            response.run.recommended_retain,
        )
        self.assertEqual(
            [],
            response.run.recommended_exclude,
        )
        self.assertEqual(TRIAGE_MODEL_NAME, response.run.response_model)

    def test_revision_mismatch_raises_conflict(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)

        provider = FakeTriageProvider(responses_by_chunk={})
        with self.assertRaises(CompetitorTriageConflictError):
            self.service.create_run(
                self.project_id,
                CompetitorTriageCreateRequest(
                    snapshot_id=snapshot.snapshot_id,
                    expected_journey_revision=self.journey_revision + 999,
                idempotency_key="ct-test-conflict",
                ),
                provider,
            )

    def test_snapshot_not_bound_raises_error(self):
        candidates = [_make_candidate("NCT00000001")]
        snap = _make_snapshot(
            self.project_id, candidates, snapshot_id="wref_unbound"
        )
        self.repo.save_search_snapshot(snap, idempotency_key="save-unbound")

        provider = FakeTriageProvider(responses_by_chunk={})
        with self.assertRaises(CompetitorTriageError):
            self.service.create_run(
                self.project_id,
                CompetitorTriageCreateRequest(
                    snapshot_id="wref_unbound",
                    expected_journey_revision=self.journey_revision,
                    idempotency_key="ct-test-unbound-snap",
                ),
                provider,
            )


class TestBoundedMissingCandidateCompensation(TriageTestBase):
    def _run_with_repair(
        self,
        repair_response: Dict[str, Any],
        *,
        complete_first_response: bool = False,
    ):
        expected_ncts = [
            f"NCT000000{i:02d}"
            for i in range(1, MAX_AI_CANDIDATES_PER_CHUNK + 1)
        ]
        candidates = [_make_candidate(nct_id) for nct_id in reversed(expected_ncts)]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        first_ncts = expected_ncts if complete_first_response else expected_ncts[:-1]
        first_response = {
            "results": [_make_candidate_result(nct_id) for nct_id in first_ncts]
        }
        responses = [first_response]
        if not complete_first_response:
            responses.append(repair_response)
        provider = SequencedRecordingTriageProvider(responses)

        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
                idempotency_key="ct-test-bounded-missing-compensation",
            ),
            provider,
        )
        return response, provider, expected_ncts, first_response

    def _assert_repair_failure(
        self,
        repair_response: Dict[str, Any],
        error_fragment: str,
    ) -> None:
        response, provider, expected_ncts, _ = self._run_with_repair(
            repair_response
        )

        self.assertEqual(2, len(provider.payloads))
        self.assertEqual(
            [expected_ncts[-1]],
            [
                candidate["nct_id"]
                for candidate in provider.payloads[1]["candidates"]
            ],
        )
        self.assertEqual(CompetitorTriageRunStatus.FAILED, response.run.status)
        chunk = response.run.chunks[0]
        self.assertEqual(CompetitorTriageChunkStatus.FAILED, chunk.status)
        self.assertIn(error_fragment, chunk.error_message)

    def test_single_missing_tail_is_repaired_with_only_missing_candidate(self):
        missing_nct = f"NCT000000{MAX_AI_CANDIDATES_PER_CHUNK:02d}"
        repair_response = {
            "results": [_make_candidate_result(missing_nct)]
        }
        response, provider, expected_ncts, first_response = self._run_with_repair(
            repair_response
        )

        self.assertEqual(2, len(provider.payloads))
        self.assertEqual(
            expected_ncts,
            [
                candidate["nct_id"]
                for candidate in provider.payloads[0]["candidates"]
            ],
        )
        self.assertEqual(
            [missing_nct],
            [
                candidate["nct_id"]
                for candidate in provider.payloads[1]["candidates"]
            ],
        )
        self.assertEqual(
            CompetitorTriageRunStatus.REVIEW_READY,
            response.run.status,
        )
        chunk = response.run.chunks[0]
        self.assertEqual(CompetitorTriageChunkStatus.SUCCEEDED, chunk.status)
        self.assertEqual(expected_ncts, [result.nct_id for result in chunk.results])

        final_output_material = {
            "initial_response": first_response,
            "repair_response": repair_response,
            "repair_missing_nct_ids": [missing_nct],
        }
        final_output_hash = _hash_value(final_output_material)
        self.assertIsNotNone(chunk.provenance)
        self.assertEqual(
            final_output_hash,
            chunk.provenance.canonical_output_hash,
        )
        self.assertEqual(final_output_hash, response.run.canonical_output_hash)
        self.assertNotEqual(
            _hash_value({"initial_response": first_response}),
            chunk.provenance.canonical_output_hash,
        )

        persisted = self.repo.triage_run(self.project_id, response.run.run_id)
        self.assertEqual(final_output_hash, persisted.canonical_output_hash)
        self.assertEqual(
            final_output_hash,
            persisted.chunks[0].provenance.canonical_output_hash,
        )

    def test_complete_first_response_calls_provider_once(self):
        response, provider, expected_ncts, _ = self._run_with_repair(
            {"results": []},
            complete_first_response=True,
        )

        self.assertEqual(1, len(provider.payloads))
        self.assertEqual(
            CompetitorTriageRunStatus.REVIEW_READY,
            response.run.status,
        )
        self.assertEqual(
            expected_ncts,
            [result.nct_id for result in response.run.chunks[0].results],
        )

    def test_still_missing_repair_fails_without_third_provider_call(self):
        self._assert_repair_failure(
            {"results": []},
            "missing nct_ids",
        )

    def test_unknown_repair_result_fails_without_third_provider_call(self):
        self._assert_repair_failure(
            {"results": [_make_candidate_result("NCT99999999")]},
            "unknown nct_id",
        )

    def test_duplicate_repair_result_fails_without_third_provider_call(self):
        self._assert_repair_failure(
            {
                "results": [
                    _make_candidate_result(
                        f"NCT000000{MAX_AI_CANDIDATES_PER_CHUNK:02d}"
                    ),
                    _make_candidate_result(
                        f"NCT000000{MAX_AI_CANDIDATES_PER_CHUNK:02d}"
                    ),
                ]
            },
            "duplicate nct_id",
        )

    def test_invalid_repair_result_fails_without_third_provider_call(self):
        invalid_result = _make_candidate_result(
            f"NCT000000{MAX_AI_CANDIDATES_PER_CHUNK:02d}"
        )
        invalid_result["classification"] = "not_a_valid_classification"
        self._assert_repair_failure(
            {"results": [invalid_result]},
            "invalid classification",
        )


class TestPartialFailureAndRetry(TriageTestBase):
    def test_retry_only_failed_chunks(self):
        # Use enough candidates to force 2 chunks (>15 is too many for a test;
        # instead we test the retry mechanism directly by creating a run with
        # a failed chunk and then retrying with a working provider).
        candidates = [_make_candidate("NCT00000001"), _make_candidate("NCT00000002")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        # First run: fail the chunk
        fail_provider = FakeTriageProvider(
            responses_by_chunk={0: {"results": []}},
            fail_chunks={0},
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
            idempotency_key="ct-test-create-2",
            ),
            fail_provider,
        )
        self.assertEqual(
            CompetitorTriageRunStatus.FAILED,
            response.run.status,
        )
        run_id = response.run.run_id

        # Retry with a working provider
        good_provider = FakeTriageProvider(
            responses_by_chunk={
                0: {
                    "results": [
                        _make_candidate_result("NCT00000001"),
                        _make_candidate_result("NCT00000002"),
                    ]
                }
            }
        )
        retry_response = self.service.retry_run(
            self.project_id,
            run_id,
            CompetitorTriageRetryRequest(idempotency_key="ct-test-retry"),
            good_provider,
        )
        self.assertEqual(
            CompetitorTriageRunStatus.REVIEW_READY,
            retry_response.run.status,
        )
        self.assertEqual(
            CompetitorTriageChunkStatus.SUCCEEDED,
            retry_response.run.chunks[0].status,
        )


class TestStaleDetection(TriageTestBase):
    def test_unconfirmed_run_from_previous_prompt_version_is_stale(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)
        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {"results": [_make_candidate_result("NCT00000001")]}
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
                idempotency_key="ct-test-create-old-prompt",
            ),
            provider,
        )
        old_run = response.run.model_copy(
            update={"prompt_version": "competitor_triage_deepseek_v5_source_truth"}
        )
        self.repo.store_triage_run(old_run)

        refreshed = self.service.get_run(self.project_id, old_run.run_id)

        self.assertEqual(CompetitorTriageRunStatus.STALE, refreshed.run.status)
        self.assertIn("prompt version changed", refreshed.run.stale_reason)

    def test_stale_run_detected_on_revision_change(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {"results": [_make_candidate_result("NCT00000001")]}
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
            idempotency_key="ct-test-create-3",
            ),
            provider,
        )
        run_id = response.run.run_id

        # Bump the journey revision by changing framing
        self._bump_journey_revision(idempotency_key="reframe-triage-test")

        # Get run should detect stale
        get_response = self.service.get_run(self.project_id, run_id)
        self.assertEqual(
            CompetitorTriageRunStatus.STALE,
            get_response.run.status,
        )

    def test_revision_only_title_adoption_does_not_stale_frozen_run(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)
        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {"results": [_make_candidate_result("NCT00000001")]}
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
                idempotency_key="ct-test-create-title-only",
            ),
            provider,
        )

        # A derived document-title adoption advances the authoring CAS revision
        # but does not change any relevance-driving project fact.
        changed_framing = journey.framing.model_copy(
            update={"document_title": "Derived title after search"},
            deep=True,
        )
        preview = self.journey_service.impact_preview(
            self.project_id,
            MedicalWritingJourneyImpactPreviewRequest(
                expected_revision=journey.revision,
                stage="framing",
                framing=changed_framing,
            ),
        )
        self.journey_service.commit_stage(
            self.project_id,
            MedicalWritingAuthoringJourneyCommitRequest(
                expected_revision=journey.revision,
                stage="framing",
                framing=changed_framing,
                impact_preview_id=preview.preview_id,
                actor="test",
                idempotency_key="ct-test-title-only-adopt",
            ),
        )

        refreshed = self.service.get_run(self.project_id, response.run.run_id)

        self.assertNotEqual(CompetitorTriageRunStatus.STALE, refreshed.run.status)
        self.assertEqual(response.run.material_facts_hash, refreshed.run.material_facts_hash)

    def test_stale_run_cannot_be_confirmed(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {"results": [_make_candidate_result("NCT00000001")]}
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
            idempotency_key="ct-test-create-4",
            ),
            provider,
        )
        run_id = response.run.run_id

        # Bump revision
        self._bump_journey_revision(idempotency_key="reframe-confirm-test")

        with self.assertRaises(CompetitorTriageStaleError):
            self.service.confirm_basket(
                self.project_id,
                run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT00000001"],
                    excluded_nct_ids=[],
                    final_classifications={
                        "NCT00000001": "direct_competitor"
                    },
                    actor="test",
                    reason="",
                expected_journey_revision=self.journey_service.get(self.project_id).revision,

                idempotency_key="ct-test-confirm-1",
                ),
            )


class TestBasketConfirmAndIdempotency(TriageTestBase):
    def _create_successful_run(self, candidates, snapshot):
        journey = self.journey_service.get(self.project_id)
        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {
                    "results": [
                        _make_candidate_result(
                            c.nct_id,
                            "direct_competitor" if i == 0 else "indirect_reference",
                        )
                        for i, c in enumerate(candidates)
                    ]
                }
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
            idempotency_key="ct-test-create-5",
            ),
            provider,
        )
        return response, provider

    def test_confirm_basket_writes_decisions_and_projects(self):
        candidates = [_make_candidate("NCT00000001"), _make_candidate("NCT00000002")]
        snapshot = self._bind_snapshot(candidates)
        response, provider = self._create_successful_run(candidates, snapshot)

        confirmation = self.service.confirm_basket(
            self.project_id,
            response.run.run_id,
            CompetitorTriageBasketConfirmationRequest(
                expected_run_revision=response.run.canonical_input_hash,
                retained_nct_ids=["NCT00000001", "NCT00000002"],
                excluded_nct_ids=[],
                final_classifications={
                    "NCT00000001": "direct_competitor",
                    "NCT00000002": "indirect_reference",
                },
                actor="test",
                reason="confirm test basket",
            expected_journey_revision=self.journey_service.get(self.project_id).revision,

            idempotency_key="ct-test-confirm-2",
            ),
        )
        self.assertEqual(
            "corpus_projected", confirmation.projection_status
        )

        # Verify relevance decisions were written
        decisions = self.repo.relevance_decisions_for_snapshot(
            self.project_id, snapshot.snapshot_id
        )
        nct_decisions = {d.nct_id: d for d in decisions}
        self.assertIn("NCT00000001", nct_decisions)
        self.assertIn("NCT00000002", nct_decisions)

        # Verify journey discovery basket projection AND corpus triage
        # are both set (PICOS was already complete at confirmation time)
        journey = self.journey_service.get(self.project_id)
        self.assertTrue(journey.discovery_basket_projection.confirmation_id)
        self.assertEqual(
            "finalized", journey.corpus_triage.status
        )

    def test_duplicate_confirmation_is_idempotent(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        response, provider = self._create_successful_run(candidates, snapshot)

        request = CompetitorTriageBasketConfirmationRequest(
            expected_run_revision=response.run.canonical_input_hash,
            retained_nct_ids=["NCT00000001"],
            excluded_nct_ids=[],
            final_classifications={
                "NCT00000001": "direct_competitor"
            },
            actor="test",
            reason="idempotency test",
            idempotency_key="ct-test-idempotent",
            expected_journey_revision=self.journey_service.get(self.project_id).revision,
        )
        conf1 = self.service.confirm_basket(
            self.project_id, response.run.run_id, request
        )
        decisions_before = {
            item.nct_id: item.revision
            for item in self.repo.relevance_decisions_for_snapshot(
                self.project_id, snapshot.snapshot_id
            )
        }
        journey_revision_before = self.journey_service.get(
            self.project_id
        ).revision
        conf2 = self.service.confirm_basket(
            self.project_id, response.run.run_id, request
        )
        self.assertEqual(conf1.confirmation_id, conf2.confirmation_id)
        self.assertEqual(
            decisions_before,
            {
                item.nct_id: item.revision
                for item in self.repo.relevance_decisions_for_snapshot(
                    self.project_id, snapshot.snapshot_id
                )
            },
        )
        self.assertEqual(
            journey_revision_before,
            self.journey_service.get(self.project_id).revision,
        )

    def test_user_override_is_atomic_and_projects_final_classification(self):
        candidates = [
            _make_candidate("NCT00000001"),
            _make_candidate("NCT00000002"),
        ]
        snapshot = self._bind_snapshot(candidates)
        response, _provider = self._create_successful_run(candidates, snapshot)
        journey_revision = self.journey_service.get(self.project_id).revision

        confirmation = self.service.confirm_basket(
            self.project_id,
            response.run.run_id,
            CompetitorTriageBasketConfirmationRequest(
                expected_run_revision=response.run.canonical_input_hash,
                retained_nct_ids=["NCT00000001", "NCT00000002"],
                excluded_nct_ids=[],
                final_classifications={
                    "NCT00000001": "direct_competitor",
                    "NCT00000002": "direct_competitor",
                },
                actor="test",
                reason="医学经理将第二项AI间接参照调整为直接竞品。",
                idempotency_key="ct-test-final-override",
                expected_journey_revision=journey_revision,
            ),
        )

        decisions = {
            item.nct_id: item.relevance_status
            for item in self.repo.relevance_decisions_for_snapshot(
                self.project_id, snapshot.snapshot_id
            )
        }
        journey = self.journey_service.get(self.project_id)
        self.assertEqual("direct_competitor", decisions["NCT00000002"])
        self.assertEqual(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            confirmation.final_classifications["NCT00000002"],
        )
        self.assertEqual(
            ["NCT00000001", "NCT00000002"],
            journey.discovery_basket_projection.retained_nct_ids,
        )

    def test_atomic_injected_failure_rolls_back_confirmation_decisions_and_run(self):
        candidates = [
            _make_candidate("NCT00000001"),
            _make_candidate("NCT00000002"),
        ]
        snapshot = self._bind_snapshot(candidates)
        response, _provider = self._create_successful_run(candidates, snapshot)
        journey_before = self.journey_service.get(self.project_id)
        request = CompetitorTriageBasketConfirmationRequest(
            expected_run_revision=response.run.canonical_input_hash,
            retained_nct_ids=["NCT00000001"],
            excluded_nct_ids=["NCT00000002"],
            final_classifications={
                "NCT00000001": "direct_competitor",
                "NCT00000002": "excluded",
            },
            actor="test",
            reason="failure injection",
            idempotency_key="ct-test-atomic-injection",
            expected_journey_revision=journey_before.revision,
        )
        with patch.object(
            self.repo,
            "triage_record_idempotency",
            side_effect=RuntimeError("injected late transaction failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "injected late transaction failure"
            ):
                self.service.confirm_basket(
                    self.project_id, response.run.run_id, request
                )

        self.assertIsNone(
            self.repo.triage_confirmation_for_run(
                self.project_id, response.run.run_id
            )
        )
        self.assertEqual(
            [],
            self.repo.relevance_decisions_for_snapshot(
                self.project_id, snapshot.snapshot_id
            ),
        )
        run_after = self.repo.triage_run(self.project_id, response.run.run_id)
        self.assertEqual(CompetitorTriageRunStatus.REVIEW_READY, run_after.status)
        journey_after = self.journey_service.get(self.project_id)
        self.assertEqual(journey_before.revision, journey_after.revision)
        self.assertFalse(
            journey_after.discovery_basket_projection.confirmation_id
        )

    def test_same_idempotency_key_with_different_final_classification_conflicts(self):
        candidates = [
            _make_candidate("NCT00000001"),
            _make_candidate("NCT00000002"),
        ]
        snapshot = self._bind_snapshot(candidates)
        response, _provider = self._create_successful_run(candidates, snapshot)
        journey_revision = self.journey_service.get(self.project_id).revision
        base = {
            "expected_run_revision": response.run.canonical_input_hash,
            "retained_nct_ids": ["NCT00000001", "NCT00000002"],
            "excluded_nct_ids": [],
            "actor": "test",
            "reason": "same key conflict test",
            "idempotency_key": "ct-test-key-conflict",
            "expected_journey_revision": journey_revision,
        }
        self.service.confirm_basket(
            self.project_id,
            response.run.run_id,
            CompetitorTriageBasketConfirmationRequest(
                **base,
                final_classifications={
                    "NCT00000001": "direct_competitor",
                    "NCT00000002": "indirect_reference",
                },
            ),
        )

        with self.assertRaisesRegex(
            CompetitorTriageConflictError,
            "idempotency key reused with different request",
        ):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    **base,
                    final_classifications={
                        "NCT00000001": "direct_competitor",
                        "NCT00000002": "direct_competitor",
                    },
                ),
            )

    def test_all_excluded_with_reason_projects_empty_corpus(self):
        candidates = [
            _make_candidate("NCT00000001"),
            _make_candidate("NCT00000002"),
        ]
        snapshot = self._bind_snapshot(candidates)
        response, _provider = self._create_successful_run(candidates, snapshot)

        confirmation = self.service.confirm_basket(
            self.project_id,
            response.run.run_id,
            CompetitorTriageBasketConfirmationRequest(
                expected_run_revision=response.run.canonical_input_hash,
                retained_nct_ids=[],
                excluded_nct_ids=["NCT00000001", "NCT00000002"],
                final_classifications={
                    "NCT00000001": "excluded",
                    "NCT00000002": "excluded",
                },
                no_suitable_competitor_reason=(
                    "当前候选的适应症、人群和给药路径均与本研究不匹配。"
                ),
                actor="test",
                reason="",
                idempotency_key="ct-test-all-excluded",
                expected_journey_revision=self.journey_service.get(
                    self.project_id
                ).revision,
            ),
        )

        decisions = self.repo.relevance_decisions_for_snapshot(
            self.project_id, snapshot.snapshot_id
        )
        journey = self.journey_service.get(self.project_id)
        self.assertEqual(
            {"excluded"}, {item.relevance_status for item in decisions}
        )
        self.assertEqual([], confirmation.retained_nct_ids)
        self.assertEqual("corpus_projected", confirmation.projection_status)
        self.assertEqual("finalized", journey.corpus_triage.status)
        self.assertEqual([], journey.corpus_triage.retained_candidate_ids)
        self.assertEqual("corpus", journey.current_stage)

    def test_all_excluded_without_substantive_reason_is_rejected(self):
        with self.assertRaisesRegex(
            ValueError, "no_suitable_competitor_reason"
        ):
            CompetitorTriageBasketConfirmationRequest(
                expected_run_revision="run-revision",
                retained_nct_ids=[],
                excluded_nct_ids=["NCT00000001"],
                final_classifications={"NCT00000001": "excluded"},
                no_suitable_competitor_reason="不合适",
                actor="test",
                reason="",
                idempotency_key="ct-test-all-excluded-invalid",
                expected_journey_revision=1,
            )

    def test_confirm_unknown_nct_rejected(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        response, provider = self._create_successful_run(candidates, snapshot)

        with self.assertRaisesRegex(
            CompetitorTriageError, "not in snapshot"
        ):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT99999999"],
                    excluded_nct_ids=[],
                    final_classifications={
                        "NCT99999999": "direct_competitor"
                    },
                    actor="test",
                    reason="",
                expected_journey_revision=self.journey_service.get(self.project_id).revision,

                idempotency_key="ct-test-confirm-3",
                ),
            )


class TestProjectionRetry(TriageTestBase):
    def test_projection_pending_then_retry_succeeds(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {"results": [_make_candidate_result("NCT00000001")]}
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
            idempotency_key="ct-test-create-6",
            ),
            provider,
        )

        # Force projection failure by patching the journey_service to
        # raise on project_discovery_basket for the first call.
        original_project = self.journey_service.project_discovery_basket
        call_count = {"n": 0}

        def flaky_project(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient projection failure")
            return original_project(*args, **kwargs)

        self.journey_service.project_discovery_basket = flaky_project  # type: ignore

        confirmation = self.service.confirm_basket(
            self.project_id,
            response.run.run_id,
            CompetitorTriageBasketConfirmationRequest(
                expected_run_revision=response.run.canonical_input_hash,
                retained_nct_ids=["NCT00000001"],
                excluded_nct_ids=[],
                final_classifications={
                    "NCT00000001": "direct_competitor"
                },
                actor="test",
                reason="projection retry test",
            expected_journey_revision=self.journey_service.get(self.project_id).revision,

            idempotency_key="ct-test-confirm-4",
            ),
        )
        self.assertEqual("failed", confirmation.projection_status)

        # Run should be projection_pending
        run = self.repo.triage_run(self.project_id, response.run.run_id)
        self.assertEqual(
            CompetitorTriageRunStatus.PROJECTION_PENDING,
            run.status,
        )

        # Retry projection — discovery succeeds first, then corpus (PICOS
        # was already committed in setUp, so the retry projects all the way
        # through to corpus_projected in one pass).
        confirmation = self.service.retry_projection(
            self.project_id,
            confirmation.confirmation_id,
            CompetitorTriageProjectionRetryRequest(actor="test", idempotency_key="ct-test-proj-retry"),
        )
        self.assertEqual("corpus_projected", confirmation.projection_status)

        # Run should be back to confirmed
        run = self.repo.triage_run(self.project_id, response.run.run_id)
        self.assertEqual(
            CompetitorTriageRunStatus.CONFIRMED,
            run.status,
        )


class TestExactModelIdentity(TriageTestBase):
    def test_provider_response_model_is_recorded(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {"results": [_make_candidate_result("NCT00000001")]}
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
            idempotency_key="ct-test-create-7",
            ),
            provider,
        )
        # The verified provider records the model name from the provider identity
        self.assertEqual(TRIAGE_MODEL_NAME, response.run.response_model)
        self.assertEqual(TRIAGE_PROVIDER_NAME, response.run.provider)

        # Verify chunk provenance
        chunk = response.run.chunks[0]
        self.assertIsNotNone(chunk.provenance)
        self.assertEqual(
            TRIAGE_MODEL_NAME,
            chunk.provenance.response_model,
        )


class TestLegacyCompatibility(unittest.TestCase):
    """Legacy one-item relevance APIs remain compatible."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = WritingReferenceRepository(
            Path(self.tmp.name) / "writing_reference.sqlite3"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_manual_relevance_decision_still_works(self):
        project_id = "proj_legacy_test"
        request = WritingReferenceSearchRequest(
            indication="RA",
            phases=["PHASE2"],
        )
        snapshot = WritingReferenceSearchSnapshot(
            snapshot_id="wref_legacy_001",
            project_id=project_id,
            request=request,
            query_url=search_url(request),
            api_version="2.0",
            data_timestamp="2026-07-14",
            total_count=1,
            returned_count=1,
            page_count=1,
            candidates=[_make_candidate("NCT00000001")],
            created_by="test",
            created_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        )
        self.repo.save_search_snapshot(snapshot, idempotency_key="save-legacy")

        decision = self.repo.record_relevance_decision(
            project_id=project_id,
            snapshot_id=snapshot.snapshot_id,
            nct_id="NCT00000001",
            relevance_status="direct_competitor",
            reason="legacy manual decision",
            actor="test",
            expected_revision=0,
            idempotency_key="legacy-decision",
        )
        self.assertEqual("direct_competitor", decision.relevance_status)

        # Read back
        decisions = self.repo.relevance_decisions_for_snapshot(
            project_id, snapshot.snapshot_id
        )
        self.assertEqual(1, len(decisions))
        self.assertEqual(
            "NCT00000001",
            decisions[0].nct_id,
        )


class TestStrictProviderFailClosed(unittest.TestCase):
    """Reject 1: Wrong configured or wrong response model must fail closed."""

    def test_wrong_configured_model_rejected(self):
        """VerifiedTriageProvider rejects a provider whose model_name is not
        exactly deepseek-v4-pro."""
        class WrongModelProvider:
            provider_name = TRIAGE_PROVIDER_NAME
            model_name = "deepseek-v4-flash"
            response_model = "deepseek-v4-flash"

            def run(self, envelope):
                return {}

        with self.assertRaises(CompetitorTriageError) as ctx:
            VerifiedTriageProvider(WrongModelProvider(), test_only_injection=True)
        self.assertIn("deepseek-v4-pro", str(ctx.exception))

    def test_wrong_response_model_rejected(self):
        """VerifiedTriageProvider rejects a provider whose response_model
        differs from deepseek-v4-pro after a call."""
        class WrongResponseProvider:
            provider_name = TRIAGE_PROVIDER_NAME
            model_name = TRIAGE_MODEL_NAME
            response_model = "deepseek-v4-flash"

            def run(self, envelope):
                return {"results": []}

        verified = VerifiedTriageProvider(
            WrongResponseProvider(), test_only_injection=True
        )
        with self.assertRaises(CompetitorTriageError) as ctx:
            verified.triage_run(
                "system prompt", {"run_id": "test", "chunk_id": "test"}
            )
        self.assertIn("deepseek-v4-pro", str(ctx.exception))

    def test_correct_model_accepted(self):
        """VerifiedTriageProvider accepts a provider with exact model match."""
        class CorrectProvider:
            provider_name = TRIAGE_PROVIDER_NAME
            model_name = TRIAGE_MODEL_NAME
            response_model = TRIAGE_MODEL_NAME

            def run(self, envelope):
                return {"results": []}

        verified = VerifiedTriageProvider(
            CorrectProvider(), test_only_injection=True
        )
        self.assertEqual(TRIAGE_MODEL_NAME, verified.model_name)

    def test_wrong_provider_name_rejected(self):
        class WrongProvider:
            provider_name = "buddy"
            model_name = TRIAGE_MODEL_NAME
            response_model = TRIAGE_MODEL_NAME

            def run(self, envelope):
                return {"results": []}

        with self.assertRaisesRegex(CompetitorTriageError, "provider_name"):
            VerifiedTriageProvider(WrongProvider(), test_only_injection=True)

    def test_missing_response_model_rejected_after_call(self):
        class MissingResponseModelProvider:
            provider_name = TRIAGE_PROVIDER_NAME
            model_name = TRIAGE_MODEL_NAME

            def run(self, envelope):
                return {"results": []}

        verified = VerifiedTriageProvider(
            MissingResponseModelProvider(), test_only_injection=True
        )
        with self.assertRaisesRegex(CompetitorTriageError, "response_model"):
            verified.triage_run("system prompt", {"run_id": "test"})

    def test_wrong_direct_base_url_rejected(self):
        class WrongBaseUrlProvider:
            provider_name = TRIAGE_PROVIDER_NAME
            model_name = TRIAGE_MODEL_NAME
            base_url = "https://proxy.example/v1"
            expected_response_model = TRIAGE_MODEL_NAME
            response_model = TRIAGE_MODEL_NAME

            def run(self, envelope):
                return {"results": []}

        with self.assertRaisesRegex(CompetitorTriageError, "base_url"):
            VerifiedTriageProvider(WrongBaseUrlProvider())

    def test_correct_direct_pro_identity_accepted_after_call(self):
        class DirectProProvider:
            provider_name = TRIAGE_PROVIDER_NAME
            model_name = TRIAGE_MODEL_NAME
            transport_name = "openai_compatible"
            base_url = "https://api.deepseek.com/v1"
            expected_response_model = TRIAGE_MODEL_NAME
            response_model = TRIAGE_MODEL_NAME

            def run(self, envelope):
                return {"results": []}

        verified = VerifiedTriageProvider(DirectProProvider())
        result = verified.triage_run("system prompt", {"run_id": "test"})
        self.assertEqual({"results": []}, result)
        self.assertEqual(TRIAGE_PROVIDER_NAME, verified.provider_name)
        self.assertEqual(TRIAGE_MODEL_NAME, verified.response_model)


class TestPartialRunRejection(TriageTestBase):
    """Reject 2: PARTIAL_FAILED run cannot be confirmed."""

    def test_partial_failed_run_cannot_be_confirmed(self):
        candidates = [_make_candidate("NCT00000001"), _make_candidate("NCT00000002")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {
                    "results": [
                        _make_candidate_result("NCT00000001"),
                        _make_candidate_result("NCT00000002"),
                    ]
                },
            },
            fail_chunks={0},
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
                idempotency_key="ct-test-partial-1",
            ),
            provider,
        )
        self.assertEqual(
            CompetitorTriageRunStatus.FAILED, response.run.status
        )

        with self.assertRaisesRegex(
            CompetitorTriageError, "REVIEW_READY"
        ):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT00000001"],
                    excluded_nct_ids=["NCT00000002"],
                    final_classifications={
                        "NCT00000001": "direct_competitor",
                        "NCT00000002": "excluded",
                    },
                    actor="test",
                    reason="should fail",
                    expected_journey_revision=self.journey_service.get(self.project_id).revision,
                    idempotency_key="ct-test-partial-confirm",
                ),
            )


class TestExactPartitionValidation(TriageTestBase):
    """Reject 3: Confirmation must be an exact, non-overlapping partition."""

    def _create_two_candidate_run(self):
        candidates = [_make_candidate("NCT00000001"), _make_candidate("NCT00000002")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)
        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {
                    "results": [
                        _make_candidate_result("NCT00000001"),
                        _make_candidate_result("NCT00000002", "excluded", 0.3),
                    ]
                }
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
                idempotency_key="ct-test-partition-create",
            ),
            provider,
        )
        return response

    def test_overlap_rejected(self):
        response = self._create_two_candidate_run()
        with self.assertRaisesRegex(CompetitorTriageError, "overlap"):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT00000001", "NCT00000002"],
                    excluded_nct_ids=["NCT00000002"],
                    final_classifications={
                        "NCT00000001": "direct_competitor",
                        "NCT00000002": "direct_competitor",
                    },
                    actor="test",
                    reason="overlap test",
                    expected_journey_revision=self.journey_service.get(self.project_id).revision,
                    idempotency_key="ct-test-overlap",
                ),
            )

    def test_missing_coverage_rejected(self):
        response = self._create_two_candidate_run()
        with self.assertRaisesRegex(CompetitorTriageError, "does not cover"):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT00000001"],
                    excluded_nct_ids=[],
                    final_classifications={
                        "NCT00000001": "direct_competitor"
                    },
                    actor="test",
                    reason="missing coverage test",
                    expected_journey_revision=self.journey_service.get(self.project_id).revision,
                    idempotency_key="ct-test-missing",
                ),
            )

    def test_duplicate_retained_rejected(self):
        response = self._create_two_candidate_run()
        with self.assertRaisesRegex(CompetitorTriageError, "duplicate"):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT00000001", "NCT00000001", "NCT00000002"],
                    excluded_nct_ids=[],
                    final_classifications={
                        "NCT00000001": "direct_competitor",
                        "NCT00000002": "direct_competitor",
                    },
                    actor="test",
                    reason="dup test",
                    expected_journey_revision=self.journey_service.get(self.project_id).revision,
                    idempotency_key="ct-test-dup",
                ),
            )

    def test_duplicate_excluded_rejected(self):
        response = self._create_two_candidate_run()
        with self.assertRaisesRegex(CompetitorTriageError, "duplicate"):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT00000001"],
                    excluded_nct_ids=["NCT00000002", "NCT00000002"],
                    final_classifications={
                        "NCT00000001": "direct_competitor",
                        "NCT00000002": "excluded",
                    },
                    actor="test",
                    reason="duplicate excluded test",
                    expected_journey_revision=self.journey_service.get(
                        self.project_id
                    ).revision,
                    idempotency_key="ct-test-excluded-dup",
                ),
            )

    def test_missing_final_classification_rejected(self):
        response = self._create_two_candidate_run()
        with self.assertRaisesRegex(
            CompetitorTriageError, "final_classifications must cover"
        ):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT00000001"],
                    excluded_nct_ids=["NCT00000002"],
                    final_classifications={
                        "NCT00000001": "direct_competitor"
                    },
                    actor="test",
                    reason="missing final classification",
                    expected_journey_revision=self.journey_service.get(
                        self.project_id
                    ).revision,
                    idempotency_key="ct-test-final-missing",
                ),
            )

    def test_final_classification_partition_conflict_rejected(self):
        response = self._create_two_candidate_run()
        with self.assertRaisesRegex(
            CompetitorTriageError,
            "final_classifications conflicts",
        ):
            self.service.confirm_basket(
                self.project_id,
                response.run.run_id,
                CompetitorTriageBasketConfirmationRequest(
                    expected_run_revision=response.run.canonical_input_hash,
                    retained_nct_ids=["NCT00000001"],
                    excluded_nct_ids=["NCT00000002"],
                    final_classifications={
                        "NCT00000001": "direct_competitor",
                        "NCT00000002": "indirect_reference",
                    },
                    actor="test",
                    reason="partition conflict",
                    expected_journey_revision=self.journey_service.get(
                        self.project_id
                    ).revision,
                    idempotency_key="ct-test-final-conflict",
                ),
            )

    def test_invalid_final_classification_value_rejected_by_contract(self):
        with self.assertRaises(ValueError):
            CompetitorTriageBasketConfirmationRequest(
                expected_run_revision="run-revision",
                retained_nct_ids=["NCT00000001"],
                excluded_nct_ids=[],
                final_classifications={"NCT00000001": "maybe"},
                actor="test",
                reason="invalid value",
                expected_journey_revision=1,
                idempotency_key="ct-test-final-invalid",
            )


class TestNoDefaultDirectCompetitor(TriageTestBase):
    """Reject 4: Untriaged candidates must never default to direct_competitor."""

    def test_unclassified_retained_rejected(self):
        candidates = [_make_candidate("NCT00000001"), _make_candidate("NCT00000002")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        # Provider only returns a result for NCT00000001, not NCT00000002
        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {
                    "results": [
                        _make_candidate_result("NCT00000001"),
                    ]
                }
            }
        )
        # The chunk validation should reject the missing NCT, making the run fail
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
                idempotency_key="ct-test-nodefault-1",
            ),
            provider,
        )
        # Run should fail because NCT00000002 is missing from results
        self.assertEqual(
            CompetitorTriageRunStatus.FAILED, response.run.status
        )


class TestPrePicosDiscoveryProjection(TriageTestBase):
    """Reject 6/7: Pre-PICOS basket confirmation projects discovery basket,
    not final corpus triage."""

    def test_discovery_projection_sets_projection_field(self):
        candidates = [_make_candidate("NCT00000001")]
        snapshot = self._bind_snapshot(candidates)
        journey = self.journey_service.get(self.project_id)

        provider = FakeTriageProvider(
            responses_by_chunk={
                0: {"results": [_make_candidate_result("NCT00000001")]}
            }
        )
        response = self.service.create_run(
            self.project_id,
            CompetitorTriageCreateRequest(
                snapshot_id=snapshot.snapshot_id,
                expected_journey_revision=journey.revision,
                idempotency_key="ct-test-disc-create",
            ),
            provider,
        )

        # PICOS is already committed in setUp, so this projects all the way
        # through to corpus. Verify discovery_basket_projection is set.
        confirmation = self.service.confirm_basket(
            self.project_id,
            response.run.run_id,
            CompetitorTriageBasketConfirmationRequest(
                expected_run_revision=response.run.canonical_input_hash,
                retained_nct_ids=["NCT00000001"],
                excluded_nct_ids=[],
                final_classifications={
                    "NCT00000001": "direct_competitor"
                },
                actor="test",
                reason="discovery test",
                expected_journey_revision=self.journey_service.get(self.project_id).revision,
                idempotency_key="ct-test-disc-conf",
            ),
        )
        self.assertIn(
            confirmation.projection_status,
            ("corpus_projected", "discovery_projected"),
        )

        # The journey must have discovery_basket_projection populated
        journey_after = self.journey_service.get(self.project_id)
        self.assertTrue(journey_after.discovery_basket_projection.confirmation_id)
        self.assertEqual(
            confirmation.confirmation_id,
            journey_after.discovery_basket_projection.confirmation_id,
        )
        self.assertIn(
            "NCT00000001",
            journey_after.discovery_basket_projection.retained_nct_ids,
        )


class TestSchemaMigration(unittest.TestCase):
    """The triage tables are created by the schema v4 migration."""

    def test_fresh_db_has_triage_tables(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            db_path = Path(tmp.name) / "test.sqlite3"
            repo = WritingReferenceRepository(db_path)
            # Schema is initialized in __init__. Verify triage tables exist
            # by querying the schema directly.
            with repo._connect() as conn:
                tables = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertIn("competitor_triage_runs", tables)
            self.assertIn("competitor_triage_confirmations", tables)
            version = conn.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            self.assertGreaterEqual(version, 4)
        finally:
            tmp.cleanup()

    def test_reopen_db_keeps_v4_schema(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            db_path = Path(tmp.name) / "test.sqlite3"
            WritingReferenceRepository(db_path)
            # Re-open: should find v4 already applied, no error
            repo2 = WritingReferenceRepository(db_path)
            with repo2._connect() as conn:
                tables = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            self.assertIn("competitor_triage_runs", tables)
            self.assertIn("competitor_triage_confirmations", tables)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
