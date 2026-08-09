"""API-level tests for the composite adopt endpoint (W3 r03).

Tests the HTTP layer: route registration, OpenAPI exposure, error code
mapping, live catalog resolver injection, and that the API constructs and
injects a real ServerEvidenceVerifier (not a mock).

Key r03 behavior: the API endpoint constructs a lazy catalog_resolver that
rebuilds the live server catalog from the current journey + snapshot.
Candidates whose persisted catalog doesn't match the live catalog are
rejected. Pure override (pending_decision) adoptions succeed without
calling the verifier.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    AuthoringPrefillCandidate,
    AuthoringPrefillClaimBinding,
    AuthoringPrefillFieldCandidates,
    AuthoringPrefillGenerateRequest,
    AuthoringPrefillPackage,
    AuthoringPrefillCompositeAdoptRequest,
    MedicalWritingAuthoringJourney,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingCompetitorSearchPlan,
    MedicalWritingStudyFraming,
)

from services.api.app import main as app_main
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill_evidence import (
    build_evidence_catalog,
)

from tests.test_medical_writing_authoring_prefill_composite_adopt import (
    _make_bound_candidate,
    _inject_candidate_with_catalog,
    _make_catalog,
    _make_catalog_entry,
)
from tests.test_medical_writing_authoring_prefill_api_snapshot_injection import (
    _make_snapshot,
)


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


def _create_request(**overrides):
    framing_fields = {
        "investigational_product": "CMS-D017",
        "indication": "类风湿关节炎",
        "study_phase": "II期",
    }
    request_fields = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-001",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


class CompositeAdoptApiTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service_patch = patch(
            "services.api.app.main.medical_writing_authoring_journey_service",
            self.service,
        )
        self.service_patch.start()

        self.canon_patch = patch(
            "services.api.app.main._canonical_module_project_id",
            side_effect=lambda pid, module: pid,
        )
        self.canon_patch.start()

        self.client = TestClient(app_main.app)

        self.service.create("proj_test", _create_request())
        journey = self.service.get("proj_test")
        gen = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="prefill-gen-001",
        )
        self.service.generate_prefill("proj_test", gen)

        # Inject a pending_decision candidate so pure-override tests succeed
        # without triggering the evidence verifier.
        cand, cat = _make_bound_candidate(recommendation_role="pending_decision")
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)

    def tearDown(self):
        self.service_patch.stop()
        self.canon_patch.stop()
        self.tmpdir.cleanup()

    def _adopt_url(self, project_id="proj_test"):
        return (
            f"/api/projects/{project_id}/medical-writing/"
            f"authoring-journey/prefill-package/adopt-composite"
        )

    def _adopt_payload(self, **overrides):
        journey = self.service.get("proj_test")
        package = journey.prefill_package
        payload = {
            "expected_revision": journey.revision,
            "expected_package_revision": package.package_revision,
            "package_field_path": "design.composite_001",
            "candidate_id": "comp_cand_001",
            "path_overrides": {},
            "skipped_paths": [],
            "actor": "medical_manager_test",
            "idempotency_key": "comp-api-001",
        }
        payload.update(overrides)
        return payload

    def _reinject(self, candidate, catalog, field_path="design.composite_001"):
        _inject_candidate_with_catalog(
            self.service, "proj_test", candidate, catalog, field_path=field_path
        )

    def _inject_live_candidate(
        self,
        *,
        catalog=None,
        target_paths=None,
        structured_value=None,
        field_path="framing.identity_package",
    ):
        journey = self.service.get("proj_test")
        live_catalog = catalog or build_evidence_catalog(journey, snapshot=None)
        paths = target_paths or [
            "framing.investigational_product",
            "framing.indication",
        ]
        values = structured_value or {
            "framing.investigational_product": "CMS-D017",
            "framing.indication": "类风湿关节炎",
        }
        candidate, _ = _make_bound_candidate(
            field_path=field_path,
            target_paths=paths,
            structured_value=values,
            catalog=live_catalog,
            recommendation_role="recommended",
        )
        self._reinject(candidate, live_catalog, field_path=field_path)
        return candidate, live_catalog

    def _set_search_plan_snapshot(self, snapshot_id):
        journey = self.service.get("proj_test")
        search_plan = MedicalWritingCompetitorSearchPlan(
            plan_id="plan_live_evidence",
            plan_revision=1,
            latest_snapshot_id=snapshot_id,
            source_study_definition_revision=1,
            generated_at=NOW,
        )
        updated = journey.model_copy(
            update={"search_plan": search_plan, "updated_at": NOW},
            deep=True,
        )
        with self.service._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE medical_writing_authoring_journeys "
                "SET payload_json = ? WHERE project_id = ?",
                (updated.model_dump_json(), "proj_test"),
            )
            connection.commit()

    def _save_divergent_framing_draft(self, idempotency_key="draft-div-001"):
        """Save an uncommitted framing draft whose indication diverges from
        the persisted framing (draft-wins authoring surface)."""
        from packages.contracts.workbench_contracts import (
            MedicalWritingAuthoringJourneyDraftSaveRequest,
        )

        journey = self.service.get("proj_test")
        draft_framing = journey.framing.model_copy(
            update={"indication": "全身型重症肌无力（草稿）"},
            deep=True,
        )
        request = MedicalWritingAuthoringJourneyDraftSaveRequest(
            expected_revision=journey.revision,
            stage="framing",
            framing=draft_framing,
            actor="medical_manager_test",
            idempotency_key=idempotency_key,
        )
        return self.service.save_stage_draft("proj_test", request)

    # ----------------------------------------------------------------
    # Route registration and OpenAPI
    # ----------------------------------------------------------------

    def test_route_exists_in_openapi(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(200, response.status_code)
        spec = response.json()
        path_key = (
            "/api/projects/{project_id}/medical-writing/"
            "authoring-journey/prefill-package/adopt-composite"
        )
        self.assertIn(path_key, spec["paths"])
        self.assertIn("post", spec["paths"][path_key])

    # ----------------------------------------------------------------
    # Pure override adoption succeeds without verifier
    # ----------------------------------------------------------------

    def test_pure_override_adoption_succeeds(self):
        """Pending_decision + all overrides succeeds without evidence verification."""
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={
                    "design.randomization": {"mode": "随机"},
                    "design.blinding": {"mode": "双盲"},
                },
                idempotency_key="comp-override-api-001",
            ),
        )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        receipt = body["receipt"]
        self.assertFalse(receipt["replayed"])
        self.assertEqual(2, len(receipt["overridden_paths"]))

    def test_successful_adoption_no_pending_medical_approval(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={
                    "design.randomization": {"mode": "随机"},
                    "design.blinding": {"mode": "双盲"},
                },
                idempotency_key="comp-no-approval-001",
            ),
        )
        self.assertEqual(200, response.status_code)
        body_str = json.dumps(response.json())
        self.assertNotIn("待医学批准", body_str)
        self.assertNotIn("pending_medical_approval", body_str)

    # ----------------------------------------------------------------
    # AI candidate with mismatched catalog is rejected (live resolver)
    # ----------------------------------------------------------------

    def test_ai_candidate_catalog_mismatch_rejected(self):
        """The API's live catalog resolver detects when the candidate's
        persisted catalog doesn't match the current journey."""
        # Re-inject a recommended candidate (not pending) with a catalog
        # that doesn't match the live journey.
        cand, cat = _make_bound_candidate(recommendation_role="recommended")
        self._reinject(cand, cat)
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(idempotency_key="comp-mismatch-001"),
        )
        # The live resolver rebuilds the catalog from the journey, which
        # produces a different catalog_id/sha than the injected one.
        self.assertEqual(422, response.status_code)

    def test_valid_live_multileaf_ai_candidate_succeeds_through_api(self):
        candidate, _ = self._inject_live_candidate()
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                package_field_path="framing.identity_package",
                candidate_id=candidate.candidate_id,
                idempotency_key="comp-live-success-001",
            ),
        )
        self.assertEqual(200, response.status_code, response.text)
        receipt = response.json()["receipt"]
        self.assertEqual(
            [
                "framing.indication",
                "framing.investigational_product",
            ],
            receipt["applied_paths"],
        )

    def test_missing_bound_snapshot_rejected(self):
        self._set_search_plan_snapshot("snap_deleted")
        journey = self.service.get("proj_test")
        catalog = build_evidence_catalog(
            journey,
            snapshot=_make_snapshot("proj_test", "snap_deleted"),
        )
        candidate, _ = self._inject_live_candidate(catalog=catalog)
        with self.service._connect() as connection:
            row = self.service._current_row(connection, "proj_test")
            persisted = MedicalWritingAuthoringJourney.model_validate_json(
                row["payload_json"]
            )
            package = persisted.prefill_package.model_copy(
                update={"search_snapshot_id": "snap_deleted"},
                deep=True,
            )
            updated = persisted.model_copy(
                update={"prefill_package": package},
                deep=True,
            )
            connection.execute(
                "UPDATE medical_writing_authoring_journeys "
                "SET payload_json = ? WHERE project_id = ?",
                (updated.model_dump_json(), "proj_test"),
            )
            connection.commit()
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                package_field_path="framing.identity_package",
                candidate_id=candidate.candidate_id,
                idempotency_key="comp-snapshot-deleted-001",
            ),
        )
        self.assertEqual(422, response.status_code)

    def test_search_plan_snapshot_switch_rejected(self):
        self._set_search_plan_snapshot("snap_old")
        journey = self.service.get("proj_test")
        catalog = build_evidence_catalog(
            journey,
            snapshot=_make_snapshot("proj_test", "snap_old"),
        )
        candidate, _ = self._inject_live_candidate(catalog=catalog)
        with self.service._connect() as connection:
            row = self.service._current_row(connection, "proj_test")
            persisted = MedicalWritingAuthoringJourney.model_validate_json(
                row["payload_json"]
            )
            package = persisted.prefill_package.model_copy(
                update={"search_snapshot_id": "snap_old"},
                deep=True,
            )
            switched_plan = persisted.search_plan.model_copy(
                update={"latest_snapshot_id": "snap_new"},
                deep=True,
            )
            updated = persisted.model_copy(
                update={
                    "prefill_package": package,
                    "search_plan": switched_plan,
                },
                deep=True,
            )
            connection.execute(
                "UPDATE medical_writing_authoring_journeys "
                "SET payload_json = ? WHERE project_id = ?",
                (updated.model_dump_json(), "proj_test"),
            )
            connection.commit()
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                package_field_path="framing.identity_package",
                candidate_id=candidate.candidate_id,
                idempotency_key="comp-plan-switched-001",
            ),
        )
        self.assertEqual(422, response.status_code)

    def test_persisted_catalog_entry_drift_rejected_even_when_hash_identity_matches(self):
        candidate, catalog = self._inject_live_candidate()
        drifted_entry = catalog.entries[0].model_copy(
            update={"title": "被篡改但未进入旧哈希的标题"},
            deep=True,
        )
        drifted_catalog = catalog.model_copy(
            update={"entries": [drifted_entry, *catalog.entries[1:]]},
            deep=True,
        )
        self._reinject(
            candidate,
            drifted_catalog,
            field_path="framing.identity_package",
        )
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                package_field_path="framing.identity_package",
                candidate_id=candidate.candidate_id,
                idempotency_key="comp-catalog-entry-drift-001",
            ),
        )
        self.assertEqual(422, response.status_code)

    def test_package_journey_revision_drift_rejected(self):
        candidate, catalog = self._inject_live_candidate()
        with self.service._connect() as connection:
            row = self.service._current_row(connection, "proj_test")
            persisted = MedicalWritingAuthoringJourney.model_validate_json(
                row["payload_json"]
            )
            package = persisted.prefill_package.model_copy(
                update={"journey_revision": persisted.revision + 1},
                deep=True,
            )
            updated = persisted.model_copy(
                update={"prefill_package": package},
                deep=True,
            )
            connection.execute(
                "UPDATE medical_writing_authoring_journeys "
                "SET payload_json = ? WHERE project_id = ?",
                (updated.model_dump_json(), "proj_test"),
            )
            connection.commit()
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                package_field_path="framing.identity_package",
                candidate_id=candidate.candidate_id,
                idempotency_key="comp-package-revision-drift-001",
            ),
        )
        self.assertEqual(422, response.status_code)

    # ----------------------------------------------------------------
    # Draft-divergent catalog: precise diagnosis + draft-wins alignment
    # ----------------------------------------------------------------

    def test_divergent_stage_draft_gets_regeneration_diagnosis(self):
        """A stage draft saved after generation advances the journey past
        the package; adoption must fail closed with a draft-aware
        regeneration diagnosis, never a generic tamper/stale error."""
        journey = self.service.get("proj_test")
        updated = self._save_divergent_framing_draft()
        self.assertEqual(journey.revision + 1, updated.revision)
        self.assertIsNotNone(updated.framing_draft)
        self.assertNotEqual(
            updated.framing_draft.framing.indication,
            updated.framing.indication,
            "draft must diverge from persisted framing",
        )
        # Live candidate bound to the current (raw) journey catalog.
        candidate, _ = self._inject_live_candidate()
        # Adoption at the pre-draft revision is a stale-journey conflict.
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                expected_revision=journey.revision,
                package_field_path="framing.identity_package",
                candidate_id=candidate.candidate_id,
                idempotency_key="comp-draft-stale-rev-001",
            ),
        )
        self.assertEqual(409, response.status_code, response.text)
        # Adoption at the current revision hits the stale-package diagnosis
        # with regeneration guidance.
        response2 = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                package_field_path="framing.identity_package",
                candidate_id=candidate.candidate_id,
                idempotency_key="comp-draft-stale-pkg-001",
            ),
        )
        self.assertEqual(422, response2.status_code, response2.text)
        detail = response2.json()["detail"]
        message = detail["message"] if isinstance(detail, dict) else str(detail)
        self.assertIn("journey revision is stale", message)
        self.assertIn("draft", message)
        self.assertIn("regenerate", message)

    def test_divergent_stage_draft_aligned_resolution_adopts_evidence_bound_candidate(self):
        """Generation builds the catalog from draft-wins effective state;
        after regeneration the live resolver must rebuild from the same
        draft-wins state so persisted and live catalogs agree and
        evidence-bound adoption succeeds. A candidate bound to the raw
        (pre-draft) catalog must still fail closed — tamper/stale checks
        are not weakened."""
        from services.api.app.medical_writing_authoring_prefill import (
            effective_authoring_values,
        )

        journey = self.service.get("proj_test")
        updated = self._save_divergent_framing_draft(
            idempotency_key="draft-div-align-001"
        )
        # Regenerate against the draft-wins effective state.
        regen = AuthoringPrefillGenerateRequest(
            expected_revision=updated.revision,
            actor="medical_manager_test",
            idempotency_key="prefill-regen-draft-001",
        )
        self.service.generate_prefill("proj_test", regen)
        journey = self.service.get("proj_test")
        package = journey.prefill_package
        self.assertEqual(journey.revision, package.journey_revision)

        # The draft-wins live rebuild is the catalog generation would bind;
        # a raw-framing rebuild must differ (the draft diverges), proving
        # the resolver alignment is what keeps identity, not a weakened
        # check.  (The deterministic package itself carries no catalog —
        # the AI enricher attaches it — so alignment is proven behaviorally
        # below through adoption outcomes.)
        effective_framing, effective_picos = effective_authoring_values(journey)
        effective_journey = journey.model_copy(
            update={"framing": effective_framing, "picos": effective_picos},
            deep=True,
        )
        live_catalog = build_evidence_catalog(effective_journey, snapshot=None)
        raw_catalog = build_evidence_catalog(journey, snapshot=None)
        self.assertNotEqual(
            raw_catalog.model_dump(mode="json"),
            live_catalog.model_dump(mode="json"),
            "raw rebuild must diverge from the draft-wins catalog",
        )

        # A candidate bound to the draft-wins catalog adopts successfully.
        draft_values = {
            "framing.investigational_product": "CMS-D017",
            "framing.indication": "全身型重症肌无力（草稿）",
        }
        candidate, _ = _make_bound_candidate(
            field_path="framing.identity_package",
            target_paths=["framing.investigational_product", "framing.indication"],
            structured_value=draft_values,
            catalog=live_catalog,
            recommendation_role="recommended",
        )
        self._reinject(candidate, live_catalog, field_path="framing.identity_package")
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                package_field_path="framing.identity_package",
                candidate_id=candidate.candidate_id,
                idempotency_key="comp-draft-aligned-001",
            ),
        )
        self.assertEqual(200, response.status_code, response.text)
        receipt = response.json()["receipt"]
        self.assertEqual(
            ["framing.indication", "framing.investigational_product"],
            receipt["applied_paths"],
        )

        # A candidate bound to the RAW (pre-draft) catalog must fail closed:
        # the live resolver rebuilds draft-wins, so the persisted raw
        # catalog no longer matches — tamper/stale detection intact.
        raw_candidate, _ = _make_bound_candidate(
            field_path="framing.identity_package",
            target_paths=["framing.investigational_product", "framing.indication"],
            structured_value={
                "framing.investigational_product": "CMS-D017",
                "framing.indication": "类风湿关节炎",
            },
            catalog=raw_catalog,
            recommendation_role="recommended",
        )
        self._reinject(
            raw_candidate, raw_catalog, field_path="framing.identity_package"
        )
        response2 = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                package_field_path="framing.identity_package",
                candidate_id=raw_candidate.candidate_id,
                idempotency_key="comp-raw-bound-001",
            ),
        )
        self.assertEqual(422, response2.status_code, response2.text)

    # ----------------------------------------------------------------
    # Error mapping: 404
    # ----------------------------------------------------------------

    def test_journey_not_found_returns_404(self):
        response = self.client.post(
            self._adopt_url("nonexistent_project"),
            json=self._adopt_payload(),
        )
        self.assertEqual(404, response.status_code)

    def test_candidate_not_found_returns_404(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(candidate_id="nonexistent"),
        )
        self.assertEqual(404, response.status_code)

    def test_field_group_not_found_returns_404(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(package_field_path="nonexistent_field"),
        )
        self.assertEqual(404, response.status_code)

    # ----------------------------------------------------------------
    # Error mapping: 422
    # ----------------------------------------------------------------

    def test_field_scope_candidate_returns_422(self):
        cand, cat = _make_bound_candidate(
            candidate_scope="field",
            recommendation_role="pending_decision",
        )
        self._reinject(cand, cat)
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={
                    "design.randomization": {"mode": "随机"},
                    "design.blinding": {"mode": "双盲"},
                },
            ),
        )
        self.assertEqual(422, response.status_code)

    def test_pending_no_override_returns_422(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(),
        )
        self.assertEqual(422, response.status_code)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, dict, "policy rejections must be structured")
        self.assertEqual("POLICY_REJECTED", detail["code"])
        self.assertEqual("candidate_pending_decision", detail["reason"])
        self.assertIn("override or explicit skip", detail["message"])

    def test_manual_only_zero_override_returns_structured_policy_422(self):
        """A manual_only candidate with zero overrides is rejected with a
        structured policy code, distinct from a revision conflict."""
        cand, cat = _make_bound_candidate(adoption_mode="manual_only")
        self._reinject(cand, cat)
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(idempotency_key="comp-policy-api-001"),
        )
        self.assertEqual(422, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertIsInstance(detail, dict, "policy rejections must be structured")
        self.assertEqual("POLICY_REJECTED", detail["code"])
        self.assertEqual("candidate_manual_only", detail["reason"])
        self.assertIn("override or explicit skip", detail["message"])
        # No mutation.
        self.assertEqual(
            2,
            self.service.get("proj_test").revision,
        )

    def test_extra_override_path_returns_422(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={"framing.protocol_id": "WRONG"},
            ),
        )
        self.assertEqual(422, response.status_code)

    # ----------------------------------------------------------------
    # Error mapping: 409
    # ----------------------------------------------------------------

    def test_stale_journey_revision_returns_409(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(expected_revision=99999),
        )
        self.assertEqual(409, response.status_code)

    def test_stale_package_revision_returns_409(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(expected_package_revision=99999),
        )
        self.assertEqual(409, response.status_code)

    def test_already_confirmed_candidate_returns_409(self):
        cand, cat = _make_bound_candidate(
            state="user_confirmed",
            recommendation_role="pending_decision",
        )
        self._reinject(cand, cat)
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(),
        )
        self.assertEqual(409, response.status_code)

    def test_stale_package_status_returns_409(self):
        cand, cat = _make_bound_candidate(recommendation_role="pending_decision")
        self._reinject(cand, cat)
        with self.service._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.service._current_row(conn, "proj_test")
            j = MedicalWritingAuthoringJourney.model_validate_json(row["payload_json"])
            pkg = j.prefill_package.model_copy(update={"status": "stale"})
            j2 = j.model_copy(update={"prefill_package": pkg}, deep=True)
            conn.execute(
                "UPDATE medical_writing_authoring_journeys SET payload_json = ? WHERE project_id = ?",
                (j2.model_dump_json(), "proj_test"),
            )
            conn.commit()
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(),
        )
        self.assertEqual(409, response.status_code)

    # ----------------------------------------------------------------
    # Idempotency
    # ----------------------------------------------------------------

    def test_idempotent_replay_returns_same_receipt(self):
        payload = self._adopt_payload(
            path_overrides={
                "design.randomization": {"mode": "随机"},
                "design.blinding": {"mode": "双盲"},
            },
            idempotency_key="comp-replay-api-001",
        )
        response1 = self.client.post(self._adopt_url(), json=payload)
        self.assertEqual(200, response1.status_code, response1.text)
        receipt1 = response1.json()["receipt"]

        payload2 = dict(payload)
        payload2["expected_revision"] = receipt1["journey_revision_before"]
        payload2["expected_package_revision"] = receipt1["package_revision_before"]
        response2 = self.client.post(self._adopt_url(), json=payload2)
        self.assertEqual(200, response2.status_code, response2.text)
        receipt2 = response2.json()["receipt"]
        self.assertTrue(receipt2["replayed"])
        self.assertEqual(receipt1["operation_id"], receipt2["operation_id"])

    def test_same_key_different_payload_returns_409(self):
        self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={
                    "design.randomization": {"mode": "随机"},
                    "design.blinding": {"mode": "双盲"},
                },
                idempotency_key="comp-conflict-api-001",
            ),
        )
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                idempotency_key="comp-conflict-api-001",
                path_overrides={
                    "design.randomization": {"mode": "非随机"},
                    "design.blinding": {"mode": "双盲"},
                },
            ),
        )
        self.assertEqual(409, response.status_code)

    # ----------------------------------------------------------------
    # Partial adoption receipt shape
    # ----------------------------------------------------------------

    def test_partial_adoption_receipt_shows_skipped_paths(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={"design.randomization": {"mode": "随机"}},
                skipped_paths=["design.blinding"],
                idempotency_key="comp-partial-api-001",
            ),
        )
        self.assertEqual(200, response.status_code, response.text)
        receipt = response.json()["receipt"]
        self.assertEqual(1, len(receipt["overridden_paths"]))
        self.assertEqual(1, len(receipt["skipped_paths"]))
        self.assertEqual("user_explicit_skip", receipt["skipped_paths"][0]["reason"])

    def test_all_skipped_adoption_and_idempotent_replay(self):
        payload = self._adopt_payload(
            skipped_paths=["design.blinding", "design.randomization"],
            idempotency_key="comp-all-skip-api-001",
        )
        first = self.client.post(self._adopt_url(), json=payload)
        self.assertEqual(200, first.status_code, first.text)
        first_receipt = first.json()["receipt"]
        self.assertEqual([], first_receipt["applied_paths"])
        self.assertEqual([], first_receipt["overridden_paths"])
        self.assertEqual(
            ["user_explicit_skip", "user_explicit_skip"],
            [item["reason"] for item in first_receipt["skipped_paths"]],
        )

        replay = self.client.post(
            self._adopt_url(),
            json={**payload, "skipped_paths": list(reversed(payload["skipped_paths"]))},
        )
        self.assertEqual(200, replay.status_code, replay.text)
        self.assertTrue(replay.json()["receipt"]["replayed"])
        self.assertEqual(
            first_receipt["operation_id"],
            replay.json()["receipt"]["operation_id"],
        )

        conflict = self.client.post(
            self._adopt_url(),
            json={**payload, "skipped_paths": ["design.randomization"]},
        )
        self.assertEqual(409, conflict.status_code, conflict.text)

    def test_partial_override_without_explicit_skip_returns_422(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={"design.randomization": {"mode": "随机"}},
                idempotency_key="comp-unresolved-api-001",
            ),
        )
        self.assertEqual(422, response.status_code, response.text)

    def test_overlap_and_out_of_scope_skips_return_422(self):
        overlap = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={"design.randomization": {"mode": "随机"}},
                skipped_paths=["design.randomization"],
                idempotency_key="comp-overlap-api-001",
            ),
        )
        self.assertEqual(422, overlap.status_code, overlap.text)

        out_of_scope = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                skipped_paths=["framing.protocol_id"],
                idempotency_key="comp-skip-scope-api-001",
            ),
        )
        self.assertEqual(422, out_of_scope.status_code, out_of_scope.text)

    # ----------------------------------------------------------------
    # Validation: missing required fields
    # ----------------------------------------------------------------

    def test_missing_idempotency_key_returns_422(self):
        payload = self._adopt_payload()
        del payload["idempotency_key"]
        response = self.client.post(self._adopt_url(), json=payload)
        self.assertEqual(422, response.status_code)

    def test_none_override_value_returns_422(self):
        response = self.client.post(
            self._adopt_url(),
            json=self._adopt_payload(
                path_overrides={"design.randomization": None},
            ),
        )
        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()
