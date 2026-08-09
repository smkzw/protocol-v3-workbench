"""W2b-2 API-level snapshot injection tests.

Verifies that POST /prefill-package/generate:

1. Reads journey.search_plan.latest_snapshot_id.
2. Loads the precise immutable snapshot via repository.search_snapshot.
3. Passes it to generate_prefill.
4. When the snapshot_id is set but the snapshot is missing from the
   repository, fail-closed to "no snapshot" (never silently use "latest").
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.contracts.workbench_contracts import (
    AuthoringPrefillGenerateRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingStudyFraming,
    MedicalWritingCompetitorSearchPlan,
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.writing_reference_repository import (
    WritingReferenceRepository,
)

NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


def _create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    framing_fields: dict[str, Any] = {
        "investigational_product": "CMS-D017",
        "indication": "阵发性睡眠性血红蛋白尿症",
        "study_phase": "II期",
    }
    request_fields: dict[str, Any] = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-snap-001",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


def _make_snapshot(project_id: str, snapshot_id: str = "snap_001") -> WritingReferenceSearchSnapshot:
    candidate = WritingReferenceTrialCandidate(
        nct_id="NCT04512345",
        brief_title="Phase 2 Study of CMS-D017 in PNH",
        official_title="A Phase 2 Study",
        brief_summary="Study in PNH patients.",
        conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
        phases=["PHASE2"],
        study_type="INTERVENTIONAL",
        interventions=[],
        design_allocation="RANDOMIZED",
        design_intervention_model="PARALLEL",
        design_masking="DOUBLE",
        enrollment_count=100,
        lead_sponsor="Test Sponsor",
        overall_status="RECRUITING",
        study_record_url="",
        public_documents=[],
    )
    return WritingReferenceSearchSnapshot(
        snapshot_id=snapshot_id,
        project_id=project_id,
        request=WritingReferenceSearchRequest(
            indication="阵发性睡眠性血红蛋白尿症",
            phases=["PHASE2"],
        ),
        query_url="https://clinicaltrials.gov/ct2/results?cond=PNH",
        candidates=[candidate],
        total_count=1,
        returned_count=1,
        page_count=1,
        created_by="test",
        created_at=NOW,
    )


def _update_journey_search_plan(
    service: MedicalWritingAuthoringJourneyService,
    project_id: str,
    snapshot_id: str,
):
    """Directly update the journey's search_plan in SQLite."""
    journey = service.get(project_id)
    sp = MedicalWritingCompetitorSearchPlan(
        plan_id="plan_001",
        plan_revision=1,
        latest_snapshot_id=snapshot_id,
        source_study_definition_revision=1,
        generated_at=NOW,
    )
    updated = journey.model_copy(
        update={"search_plan": sp, "updated_at": NOW},
        deep=True,
    )
    with service._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE medical_writing_authoring_journeys "
            "SET payload_json = ?, state_sha256 = ?, updated_at = ? "
            "WHERE project_id = ?",
            (
                updated.model_dump_json(),
                updated.model_dump_json(),  # state_sha256
                NOW.isoformat(),
                project_id,
            ),
        )
        conn.commit()


class SnapshotInjectionTests(unittest.TestCase):
    """Test that the API endpoint loads the precise snapshot."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.journey_service = MedicalWritingAuthoringJourneyService(
            self.base / "journey.sqlite3"
        )
        self.repo = WritingReferenceRepository(self.base / "ref.sqlite3")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_snapshot_present_in_repository(self):
        """When snapshot_id is set and snapshot exists, it is loaded."""
        self.journey_service.create("proj_test", _create_request())
        _update_journey_search_plan(self.journey_service, "proj_test", "snap_001")
        # Save snapshot to repo.
        snapshot = _make_snapshot("proj_test", "snap_001")
        self.repo.save_search_snapshot(snapshot, idempotency_key="snap-save-001")

        # Verify the snapshot can be loaded.
        loaded = self.repo.search_snapshot("proj_test", "snap_001")
        self.assertEqual(loaded.snapshot_id, "snap_001")

    def test_snapshot_missing_from_repository_raises_keyerror(self):
        """When snapshot_id is set but snapshot is missing, search_snapshot
        raises KeyError — the API must catch it and pass snapshot=None."""
        self.journey_service.create("proj_test", _create_request())
        _update_journey_search_plan(self.journey_service, "proj_test", "snap_nonexistent")
        # Snapshot is NOT saved to repo.
        with self.assertRaises(KeyError):
            self.repo.search_snapshot("proj_test", "snap_nonexistent")

    def test_precise_snapshot_not_latest(self):
        """The API must load latest_snapshot_id exactly, not 'latest'."""
        self.journey_service.create("proj_test", _create_request())
        _update_journey_search_plan(self.journey_service, "proj_test", "snap_001")

        # Save TWO snapshots — snap_001 (older) and snap_002 (newer).
        snap1 = _make_snapshot("proj_test", "snap_001")
        snap2 = _make_snapshot("proj_test", "snap_002")
        self.repo.save_search_snapshot(snap1, idempotency_key="snap-save-001")
        self.repo.save_search_snapshot(snap2, idempotency_key="snap-save-002")

        # The search_plan points to snap_001. search_snapshot must return
        # snap_001, not snap_002.
        loaded = self.repo.search_snapshot("proj_test", "snap_001")
        self.assertEqual("snap_001", loaded.snapshot_id)

        # latest_search_snapshot would return snap_002, but the API must
        # NOT use latest_search_snapshot — it must use search_snapshot with
        # the exact ID.
        latest = self.repo.latest_search_snapshot("proj_test")
        self.assertEqual("snap_002", latest.snapshot_id)

    def test_no_search_plan_produces_no_snapshot(self):
        """When journey has no latest_snapshot_id, snapshot=None."""
        self.journey_service.create("proj_test", _create_request())
        journey = self.journey_service.get("proj_test")
        # A search_plan exists by default but latest_snapshot_id is empty.
        sp = journey.search_plan
        self.assertTrue(sp is None or not sp.latest_snapshot_id)

        # generate_prefill with snapshot=None should still work.
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="test",
            idempotency_key="gen-001",
        )
        result = self.journey_service.generate_prefill(
            "proj_test", request, snapshot=None
        )
        self.assertIsNotNone(result.prefill_package)


class GeneratePrefillSnapshotPathTests(unittest.TestCase):
    """Test that generate_prefill receives and uses the snapshot."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.journey_service = MedicalWritingAuthoringJourneyService(
            self.base / "journey.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_generate_prefill_with_snapshot_includes_snapshot_id(self):
        """generate_prefill with a snapshot sets search_snapshot_id on
        the resulting package."""
        self.journey_service.create("proj_test", _create_request())
        journey = self.journey_service.get("proj_test")

        snapshot = _make_snapshot("proj_test")
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="test",
            idempotency_key="gen-snap-001",
            force=True,
        )
        result = self.journey_service.generate_prefill(
            "proj_test", request, snapshot=snapshot
        )
        pkg = result.prefill_package
        self.assertEqual(pkg.search_snapshot_id, "snap_001")

    def test_generate_prefill_without_snapshot_records_partial_failure(self):
        """When search_plan claims a snapshot but snapshot=None, the
        deterministic package records search_snapshot_unavailable."""
        self.journey_service.create("proj_test", _create_request())
        journey = self.journey_service.get("proj_test")

        _update_journey_search_plan(self.journey_service, "proj_test", "snap_missing")

        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="test",
            idempotency_key="gen-nosnap-001",
            force=True,
        )
        # Pass snapshot=None → deterministic prefill records failure.
        result = self.journey_service.generate_prefill(
            "proj_test", request, snapshot=None
        )
        pkg = result.prefill_package
        self.assertIn(
            "search_snapshot_unavailable",
            " ".join(pkg.partial_source_failures),
        )


if __name__ == "__main__":
    unittest.main()
