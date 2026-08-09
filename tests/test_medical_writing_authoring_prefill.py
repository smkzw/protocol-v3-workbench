"""Comprehensive tests for the AI-first authoring prefill backend.

Covers greenfield creation, prefill generation, staleness detection, candidate
validation, adoption semantics, idempotency, conflict detection, dependent
invalidation, legacy compatibility, and phase-specific behavior.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts import (
    AuthoringPrefillAdoptRequest,
    AuthoringPrefillCandidate,
    AuthoringPrefillFieldCandidates,
    AuthoringPrefillGenerateRequest,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingAuthoringJourneyDraftSaveRequest,
    MedicalWritingStudyFraming,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyConflictError,
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill import (
    EXACT_FACT_PATHS,
    SUPPORTED_ADOPT_PATHS,
    _count_adoptable_and_pending_fields,
    effective_authoring_values,
    generate_prefill_package,
    get_path_value,
    package_is_stale,
    preserve_current_user_confirmations,
    values_materially_distinct,
    validate_candidate_for_ready_exact_fact,
)


NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def _create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    """Build a create request with sensible defaults for a Phase II RA study."""
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


def _phase1_create_request(**overrides) -> MedicalWritingAuthoringJourneyCreateRequest:
    """Build a create request for a Phase I study."""
    framing_fields = {
        "investigational_product": "CMS-D017",
        "indication": "类风湿关节炎",
        "study_phase": "I期",
    }
    request_fields = {
        "actor": "medical_manager_test",
        "idempotency_key": "create-phase1-001",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


class AuthoringPrefillBackendTests(unittest.TestCase):
    """Core test suite for the authoring prefill backend."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_journey(self, project_id: str = "proj_test", **overrides):
        return self.service.create(project_id, _create_request(**overrides))

    def _generate_prefill(self, project_id: str = "proj_test", idempotency_key: str = "prefill-gen-001"):
        journey = self.service.get(project_id)
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key=idempotency_key,
        )
        return self.service.generate_prefill(project_id, request)

    def _adopt_candidate(
        self,
        project_id: str = "proj_test",
        field_path: str = "framing.protocol_id",
        idempotency_key: str = "adopt-001",
        candidate_index: int = 0,
        edited_value=None,
    ):
        """Adopt a user decision for *field_path* through the single-candidate
        endpoint's user-edit channel (``candidate_id=""`` + ``edited_value``).

        Corrective round 2: every candidate card in a generated package is
        pending_decision and/or manual_only, so candidate-card adoption via
        this endpoint fails closed.  The value applied here is the user's
        explicit edit (defaulting to the candidate's suggested value), which
        is recorded as a user_confirmed manual edit with audit.
        """
        journey = self.service.get(project_id)
        package = journey.prefill_package
        self.assertIsNotNone(package, "prefill package must exist before adoption")
        group = package.field_candidates[field_path]
        candidate = group.candidates[candidate_index]
        request = AuthoringPrefillAdoptRequest(
            expected_revision=journey.revision,
            expected_package_revision=package.package_revision,
            field_path=field_path,
            candidate_id="",
            edited_value=(
                edited_value
                if edited_value is not None
                else candidate.structured_value
            ),
            actor="medical_manager_test",
            idempotency_key=idempotency_key,
        )
        return self.service.adopt_prefill_candidate(project_id, request)

    # ------------------------------------------------------------------
    # 1. Three-field greenfield creation creates search plan
    # ------------------------------------------------------------------

    def test_three_field_greenfield_creation_creates_search_plan(self):
        """Creating a journey with only product/indication/phase generates a search plan."""
        journey = self._create_journey()

        # Creation minimum is met (investigational_product, indication, study_phase).
        self.assertTrue(journey.framing.creation_minimum_complete())

        # Search plan should be generated because creation_minimum_complete is True.
        self.assertIsNotNone(journey.search_plan)
        self.assertTrue(journey.search_plan.plan_id.startswith("mwsearch_"))
        self.assertEqual("broad_then_triage", journey.search_plan.strategy)

        # Framing is NOT fully complete (missing protocol_id, document_title, etc.).
        self.assertFalse(journey.framing_complete)
        self.assertEqual("stage1_in_progress", journey.status)
        for path in (
            "framing.investigational_product",
            "framing.indication",
            "framing.study_phase",
        ):
            self.assertEqual(
                "confirmed",
                journey.study_definition.field_states[path].status,
            )
            self.assertEqual(
                "medical_manager_test",
                journey.study_definition.field_states[path].confirmed_by,
            )
        self.assertNotEqual(
            "confirmed",
            journey.study_definition.field_states["framing.document_title"].status,
        )

    # ------------------------------------------------------------------
    # 2. Search executes before framing completion
    # ------------------------------------------------------------------

    def test_search_executes_before_framing_completion(self):
        """Prefill generation works when creation_minimum is met but framing_complete is False."""
        journey = self._create_journey()

        # Verify precondition: creation minimum met, framing not complete.
        self.assertTrue(journey.framing.creation_minimum_complete())
        self.assertFalse(journey.framing_complete)

        # Generate prefill should succeed.
        updated = self._generate_prefill()
        self.assertIsNotNone(updated.prefill_package)
        package = updated.prefill_package
        self.assertIn(package.status, {"partial", "ready"})
        self.assertGreater(len(package.field_candidates), 0)
        self.assertEqual("generated", package.progress.stage)
        self.assertGreater(package.progress.fields_with_recommendation, 0)

    def test_prefill_generation_and_adoption_use_active_synopsis_style_draft(self):
        created = self._create_journey(
            project_id="proj_draft_prefill",
            investigational_product="OLD-DRUG",
            indication="旧适应症",
            study_phase="II期",
            idempotency_key="create-draft-prefill",
        )
        draft = MedicalWritingStudyFraming(
            protocol_id="D017-02-001",
            document_title="CMS-D017治疗PNH的II期临床研究方案",
            indication="阵发性睡眠性血红蛋白尿症",
            study_phase="II期",
            intrinsic_objectives=["剂量探索"],
            investigational_product="CMS-D017",
            design_pattern="随机、开放标签、剂量探索",
            population_intent="补体抑制剂未治PNH患者",
        )
        saved = self.service.save_stage_draft(
            "proj_draft_prefill",
            MedicalWritingAuthoringJourneyDraftSaveRequest(
                expected_revision=created.revision,
                stage="framing",
                framing=draft,
                actor="medical_manager_test",
                idempotency_key="save-draft-prefill",
            ),
        )

        generated = self.service.generate_prefill(
            "proj_draft_prefill",
            AuthoringPrefillGenerateRequest(
                expected_revision=saved.revision,
                actor="medical_manager_test",
                idempotency_key="generate-draft-prefill",
            ),
        )

        title_group = generated.prefill_package.field_candidates[
            "framing.document_title"
        ]
        self.assertTrue(
            any(
                "CMS-D017" in str(candidate.structured_value)
                and "阵发性睡眠性血红蛋白尿症" in str(candidate.structured_value)
                for candidate in title_group.candidates
            )
        )
        protocol_group = generated.prefill_package.field_candidates[
            "framing.protocol_id"
        ]
        candidate = protocol_group.candidates[0]
        adopted = self.service.adopt_prefill_candidate(
            "proj_draft_prefill",
            AuthoringPrefillAdoptRequest(
                expected_revision=generated.revision,
                expected_package_revision=generated.prefill_package.package_revision,
                field_path="framing.protocol_id",
                # Round 2: user-edit channel (candidate cards are
                # manual_only and fail closed on this endpoint).
                candidate_id="",
                edited_value="D017-02-001-EDITED",
                actor="medical_manager_test",
                idempotency_key="adopt-draft-prefill",
            ),
        )

        self.assertEqual("OLD-DRUG", adopted.framing.investigational_product)
        self.assertEqual(
            "D017-02-001-EDITED",
            adopted.framing_draft.framing.protocol_id,
        )
        self.assertEqual(
            "CMS-D017",
            adopted.framing_draft.framing.investigational_product,
        )

    def test_effective_values_tolerate_narrow_legacy_draft_objects(self):
        state = SimpleNamespace(
            framing="confirmed-framing",
            picos="confirmed-picos",
            framing_draft=SimpleNamespace(),
            picos_draft=SimpleNamespace(),
        )

        self.assertEqual(
            ("confirmed-framing", "confirmed-picos"),
            effective_authoring_values(state),
        )

    def test_get_path_value_returns_none_for_missing_legacy_field(self):
        self.assertIsNone(
            get_path_value(
                SimpleNamespace(indication="类风湿关节炎"),
                SimpleNamespace(),
                "framing.protocol_id",
            )
        )
        self.assertIsNone(
            get_path_value(
                SimpleNamespace(),
                SimpleNamespace(),
                "picos.primary_endpoint",
            )
        )

    # ------------------------------------------------------------------
    # 3. Package persists and cold-reloads
    # ------------------------------------------------------------------

    def test_package_persists_and_cold_reloads(self):
        """Generated package survives service restart (new instance on same DB)."""
        self._create_journey()
        updated = self._generate_prefill()
        original_package = updated.prefill_package
        self.assertIsNotNone(original_package)

        # Create a brand-new service instance pointing at the same SQLite file.
        cold_service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        reloaded = cold_service.get("proj_test")

        self.assertIsNotNone(reloaded.prefill_package)
        self.assertEqual(original_package.package_id, reloaded.prefill_package.package_id)
        self.assertEqual(
            original_package.package_revision,
            reloaded.prefill_package.package_revision,
        )
        self.assertEqual(
            set(original_package.field_candidates.keys()),
            set(reloaded.prefill_package.field_candidates.keys()),
        )
        self.assertEqual(
            original_package.input_fingerprint,
            reloaded.prefill_package.input_fingerprint,
        )

    # ------------------------------------------------------------------
    # 4. Package becomes stale after study definition change
    # ------------------------------------------------------------------

    def test_package_becomes_stale_after_study_definition_change(self):
        """After framing changes, package_is_stale returns True."""
        self._create_journey()
        updated = self._generate_prefill()
        package = updated.prefill_package
        self.assertIsNotNone(package)

        # Package should not be stale immediately after generation.
        self.assertFalse(package_is_stale(package, state=updated))

        # Mutate framing by adopting a different protocol_id candidate.
        after_adopt = self._adopt_candidate(
            field_path="framing.protocol_id",
            idempotency_key="adopt-stale-test",
        )

        # Now the original package should be stale relative to the new state.
        self.assertTrue(package_is_stale(package, state=after_adopt))

    # ------------------------------------------------------------------
    # 5. Candidate paths and evidence references are validated
    # ------------------------------------------------------------------

    def test_candidate_paths_and_evidence_references_are_validated(self):
        """All candidates have valid field_path in SUPPORTED_ADOPT_PATHS and evidence_refs
        have source_id or source_text."""
        self._create_journey()
        updated = self._generate_prefill()
        package = updated.prefill_package
        self.assertIsNotNone(package)
        self.assertGreater(len(package.field_candidates), 0)

        for field_path, group in package.field_candidates.items():
            # Field path must be in the supported set, or be a module-scope
            # package.* synthetic path (composite candidate).
            if not field_path.startswith("package."):
                self.assertIn(
                    field_path,
                    SUPPORTED_ADOPT_PATHS,
                    f"field_path {field_path!r} not in SUPPORTED_ADOPT_PATHS",
                )
            # Group field_path must match its key.
            self.assertEqual(field_path, group.field_path)

            for candidate in group.candidates:
                # Candidate field_path must match parent.
                self.assertEqual(field_path, candidate.field_path)

                # Every evidence ref must have source_id or source_text.
                for ref in candidate.evidence_refs:
                    self.assertTrue(
                        ref.source_id or ref.source_text,
                        f"evidence ref in {field_path}/{candidate.candidate_id} "
                        f"lacks both source_id and source_text",
                    )

    # ------------------------------------------------------------------
    # 6. Alternatives are materially distinct and limited to four
    # ------------------------------------------------------------------

    def test_alternatives_are_materially_distinct_and_limited_to_four(self):
        """No two candidates in a field share the same canonicalized value;
        max 5 total (1 recommended + 4 alternatives)."""
        self._create_journey()
        updated = self._generate_prefill()
        package = updated.prefill_package
        self.assertIsNotNone(package)

        for field_path, group in package.field_candidates.items():
            # At most 5 candidates (1 rec + 4 alt).
            self.assertLessEqual(
                len(group.candidates),
                5,
                f"field {field_path} has {len(group.candidates)} candidates (max 5)",
            )

            # All pairs must be materially distinct.
            for i in range(len(group.candidates)):
                for j in range(i + 1, len(group.candidates)):
                    left = group.candidates[i].structured_value
                    right = group.candidates[j].structured_value
                    self.assertTrue(
                        values_materially_distinct(left, right),
                        f"field {field_path}: candidates "
                        f"{group.candidates[i].candidate_id} and "
                        f"{group.candidates[j].candidate_id} are not materially distinct",
                    )

    # ------------------------------------------------------------------
    # 7. Exact unsupported clinical facts not invented without evidence
    # ------------------------------------------------------------------

    def test_exact_unsupported_clinical_facts_not_invented_without_evidence(self):
        """EXACT_FACT_PATHS candidates all have evidence_refs; the generator does not
        produce ready candidates for exact facts without evidence."""
        self._create_journey()
        updated = self._generate_prefill()
        package = updated.prefill_package
        self.assertIsNotNone(package)

        # The deterministic generator should NOT produce candidates for exact fact
        # paths when there is no evidence source. Verify none appear.
        for exact_path in EXACT_FACT_PATHS:
            if exact_path in package.field_candidates:
                group = package.field_candidates[exact_path]
                for candidate in group.candidates:
                    # If present, must have evidence.
                    self.assertGreater(
                        len(candidate.evidence_refs),
                        0,
                        f"exact fact path {exact_path} candidate "
                        f"{candidate.candidate_id} has no evidence_refs",
                    )
                    # validate_candidate_for_ready_exact_fact should not raise.
                    validate_candidate_for_ready_exact_fact(candidate)

        # Additionally, verify that the progress reports blocked fields.
        self.assertGreater(
            package.progress.fields_blocked_missing_evidence,
            0,
            "expected some exact fact fields to be blocked due to missing evidence",
        )

    # ------------------------------------------------------------------
    # 8. Adopting recommended updates correct study definition path
    # ------------------------------------------------------------------

    def test_adopting_recommended_updates_correct_study_definition_path(self):
        """Adopting a framing.protocol_id candidate updates framing.protocol_id."""
        self._create_journey()
        self._generate_prefill()

        journey = self.service.get("proj_test")
        package = journey.prefill_package
        group = package.field_candidates["framing.protocol_id"]
        candidate = group.candidates[0]
        expected_value = candidate.structured_value

        updated = self._adopt_candidate(
            field_path="framing.protocol_id",
            idempotency_key="adopt-protocol-id",
        )

        # framing.protocol_id should now equal the adopted value.
        self.assertEqual(expected_value, updated.framing.protocol_id)

        # The package records the interaction state on the user_confirmed
        # (edited) candidate while the original manual_only card stays
        # ai_proposed — candidate-card adoption fails closed in round 2.
        updated_group = updated.prefill_package.field_candidates["framing.protocol_id"]
        state_entry = next(
            item for item in updated_group.candidates
            if item.state == "user_confirmed"
        )
        self.assertEqual("user_confirmed", state_entry.state)
        self.assertEqual(expected_value, state_entry.structured_value)
        self.assertNotEqual(candidate.candidate_id, state_entry.candidate_id)
        fact_state = updated.study_definition.field_states["framing.protocol_id"]
        self.assertEqual("confirmed", fact_state.status)
        self.assertEqual("medical_manager_edit", fact_state.value_origin)
        self.assertEqual("medical_manager_test", fact_state.confirmed_by)

    def test_adoption_preserves_unchanged_fact_governance_and_sources(self):
        """Adoption must not rewrite unrelated fact states or source identities."""
        created = self._create_journey()
        original_indication_state = created.study_definition.field_states[
            "framing.indication"
        ].model_dump(mode="json")
        original_source_ids = list(created.study_definition.source_artifact_ids)
        self._generate_prefill()

        updated = self._adopt_candidate(
            field_path="framing.protocol_id",
            idempotency_key="adopt-preserve-governance-001",
        )

        self.assertEqual(
            original_indication_state,
            updated.study_definition.field_states[
                "framing.indication"
            ].model_dump(mode="json"),
        )
        self.assertEqual(
            original_source_ids,
            updated.study_definition.source_artifact_ids,
        )

    def test_two_independent_fields_can_be_adopted_from_one_package(self):
        """A confirmed field must not make the remaining package unusable."""
        self._create_journey()
        generated = self._generate_prefill()
        package_id = generated.prefill_package.package_id

        first = self._adopt_candidate(
            field_path="framing.protocol_id",
            idempotency_key="adopt-sequential-001",
        )
        self.assertEqual(package_id, first.prefill_package.package_id)
        self.assertFalse(package_is_stale(first.prefill_package, state=first))

        # Adopt the randomization alternative (not the pending_decision card)
        # to verify two independent fields can be adopted from one package.
        second = self._adopt_candidate(
            field_path="design.randomization",
            idempotency_key="adopt-sequential-002",
            edited_value={"mode": "随机", "details": "医学经理确认采用随机分配。"},
        )
        self.assertEqual(package_id, second.prefill_package.package_id)
        self.assertFalse(package_is_stale(second.prefill_package, state=second))
        self.assertGreater(
            second.prefill_package.package_revision,
            first.prefill_package.package_revision,
        )
        confirmed_protocol = [
            item
            for item in second.prefill_package.field_candidates[
                "framing.protocol_id"
            ].candidates
            if item.state == "user_confirmed"
        ]
        confirmed_randomization = [
            item
            for item in second.prefill_package.field_candidates[
                "design.randomization"
            ].candidates
            if item.state == "user_confirmed"
        ]
        self.assertEqual(1, len(confirmed_protocol))
        self.assertEqual(1, len(confirmed_randomization))

    # ------------------------------------------------------------------
    # 9. Adoption is idempotent and stale writes conflict
    # ------------------------------------------------------------------

    def test_adoption_is_idempotent_and_stale_writes_conflict(self):
        """Same idempotency key replays the same result; wrong expected_revision
        raises ConflictError."""
        self._create_journey()
        self._generate_prefill()

        journey = self.service.get("proj_test")
        package = journey.prefill_package
        group = package.field_candidates["framing.protocol_id"]
        candidate = group.candidates[0]

        request = AuthoringPrefillAdoptRequest(
            expected_revision=journey.revision,
            expected_package_revision=package.package_revision,
            field_path="framing.protocol_id",
            # Round 2: user-edit channel (manual_only cards fail closed).
            candidate_id="",
            edited_value=candidate.structured_value,
            actor="medical_manager_test",
            idempotency_key="adopt-idempotent-001",
        )

        # First adoption succeeds.
        first_result = self.service.adopt_prefill_candidate("proj_test", request)
        self.assertEqual(journey.revision + 1, first_result.revision)

        # Replay with same idempotency key returns the same result.
        replay_result = self.service.adopt_prefill_candidate("proj_test", request)
        self.assertEqual(first_result.revision, replay_result.revision)
        self.assertEqual(
            first_result.framing.protocol_id,
            replay_result.framing.protocol_id,
        )

        # Stale write: use the old revision with a different idempotency key.
        stale_request = AuthoringPrefillAdoptRequest(
            expected_revision=journey.revision,  # stale
            expected_package_revision=package.package_revision,
            field_path="framing.protocol_id",
            candidate_id="",
            edited_value=candidate.structured_value,
            actor="medical_manager_test",
            idempotency_key="adopt-stale-002",
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
            self.service.adopt_prefill_candidate("proj_test", stale_request)

    # ------------------------------------------------------------------
    # 10. User-confirmed newer values not silently overwritten
    # ------------------------------------------------------------------

    def test_user_confirmed_newer_values_not_silently_overwritten(self):
        """After adopting a candidate (state becomes user_confirmed), trying to adopt
        the same candidate again raises ConflictError."""
        self._create_journey()
        self._generate_prefill()

        # First adoption.
        updated = self._adopt_candidate(
            field_path="framing.protocol_id",
            idempotency_key="adopt-confirm-001",
        )

        # Verify the candidate is now user_confirmed in the package.
        package = updated.prefill_package
        group = package.field_candidates["framing.protocol_id"]
        confirmed_candidate = group.candidates[0]
        self.assertEqual("user_confirmed", confirmed_candidate.state)

        # Attempt to adopt the same candidate again with a new idempotency key.
        second_request = AuthoringPrefillAdoptRequest(
            expected_revision=updated.revision,
            expected_package_revision=package.package_revision,
            field_path="framing.protocol_id",
            candidate_id=confirmed_candidate.candidate_id,
            actor="medical_manager_test",
            idempotency_key="adopt-confirm-002",
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self.service.adopt_prefill_candidate("proj_test", second_request)
        self.assertIn("already confirmed", str(ctx.exception))

    # ------------------------------------------------------------------
    # 11. Adoption triggers dependent invalidation
    # ------------------------------------------------------------------

    def test_adoption_triggers_dependent_invalidation(self):
        """Adopting a design.randomization candidate invalidates downstream dependents."""
        self._create_journey()
        self._generate_prefill()

        journey = self.service.get("proj_test")
        # Precondition: no invalidated dependents initially.
        initial_invalidated = set(journey.invalidated_dependents or [])

        updated = self._adopt_candidate(
            field_path="design.randomization",
            idempotency_key="adopt-randomization-001",
        )

        # invalidated_dependents should be non-empty after adopting a design field
        # that maps to framing.design_pattern changes.
        new_invalidated = set(updated.invalidated_dependents or [])
        self.assertGreater(
            len(new_invalidated),
            len(initial_invalidated),
            "expected new invalidated dependents after design.randomization adoption",
        )
        # framing.design_pattern dependents should appear.
        self.assertTrue(
            new_invalidated & {"picos_recommendations", "protocol_synopsis", "study_schema", "schedule_of_activities"},
            f"expected design-related dependents in {new_invalidated}",
        )

    # ------------------------------------------------------------------
    # 12. Legacy journey JSON loads without package
    # ------------------------------------------------------------------

    def test_legacy_journey_json_loads_without_package(self):
        """A journey payload without prefill_package field loads with None."""
        self._create_journey()
        journey = self.service.get("proj_test")

        # Serialize and strip prefill_package to simulate legacy data.
        payload = json.loads(journey.model_dump_json())
        payload.pop("prefill_package", None)

        # Re-validate: should load without error and prefill_package should be None.
        from packages.contracts.workbench_contracts import MedicalWritingAuthoringJourney

        legacy_journey = MedicalWritingAuthoringJourney.model_validate(payload)
        self.assertIsNone(legacy_journey.prefill_package)
        self.assertEqual(journey.project_id, legacy_journey.project_id)
        self.assertEqual(journey.revision, legacy_journey.revision)

    # ------------------------------------------------------------------
    # 13. Phase I multi-part and randomized Phase II cases
    # ------------------------------------------------------------------

    def test_phase1_multi_part_and_randomized_phase2_cases(self):
        """Phase I generates design.phase1_parts with pending card + multi-select
        alternatives; Phase II design.randomization starts as pending_decision,
        not hardcoded to 随机."""
        # --- Phase I ---
        phase1_service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "phase1.sqlite3"
        )
        phase1_service.create("proj_phase1", _phase1_create_request())
        p1_journey = phase1_service.get("proj_phase1")
        p1_request = AuthoringPrefillGenerateRequest(
            expected_revision=p1_journey.revision,
            actor="medical_manager_test",
            idempotency_key="prefill-phase1-001",
        )
        p1_updated = phase1_service.generate_prefill("proj_phase1", p1_request)
        p1_package = p1_updated.prefill_package
        self.assertIsNotNone(p1_package)

        # Phase I should have design.phase1_parts field.
        self.assertIn(
            "design.phase1_parts",
            p1_package.field_candidates,
            "Phase I package should contain design.phase1_parts candidates",
        )
        parts_group = p1_package.field_candidates["design.phase1_parts"]
        self.assertGreater(len(parts_group.candidates), 0)
        # Primary candidate should be a pending_decision card with empty parts.
        primary = parts_group.candidates[0]
        self.assertIsInstance(primary.structured_value, dict)
        self.assertIn("parts", primary.structured_value)
        self.assertEqual(
            "pending_decision", primary.recommendation_role,
            "Phase I parts primary must be pending_decision, not recommended",
        )
        # Alternatives should include SAD/MAD and other part types as choices.
        all_part_previews = " ".join(c.preview for c in parts_group.candidates)
        self.assertIn("SAD", all_part_previews)
        self.assertIn("MAD", all_part_previews)

        # --- Phase II (default) ---
        self._create_journey()
        p2_updated = self._generate_prefill()
        p2_package = p2_updated.prefill_package
        self.assertIsNotNone(p2_package)

        # Phase II should have design.randomization field.
        self.assertIn(
            "design.randomization",
            p2_package.field_candidates,
            "Phase II package should contain design.randomization candidates",
        )
        rand_group = p2_package.field_candidates["design.randomization"]
        self.assertGreater(len(rand_group.candidates), 0)
        # Primary candidate for Phase II must be pending_decision (not 随机).
        primary_rand = rand_group.candidates[0]
        self.assertIsInstance(primary_rand.structured_value, dict)
        self.assertEqual(
            "pending_decision", primary_rand.recommendation_role,
            "Phase II randomization primary must be pending_decision, not recommended",
        )
        self.assertNotEqual(
            "随机", primary_rand.structured_value.get("mode"),
            "Phase II must not hardcode 随机 as recommended",
        )
        # Without research-ready evidence the group stays pending-only. The
        # medical manager can still enter an explicit value through the edit
        # path, but the system must not manufacture a randomization option.
        self.assertTrue(
            all(
                candidate.recommendation_role == "pending_decision"
                for candidate in rand_group.candidates
            )
        )

        # Phase II should NOT have design.phase1_parts.
        self.assertNotIn(
            "design.phase1_parts",
            p2_package.field_candidates,
            "Phase II package should not contain design.phase1_parts",
        )

    # ------------------------------------------------------------------
    # 14. No second approval object created
    # ------------------------------------------------------------------

    def test_no_second_approval_object_created(self):
        """After adoption, no ApprovalGate or '待医学批准' state exists;
        the package candidate shows user_confirmed directly."""
        self._create_journey()
        self._generate_prefill()

        updated = self._adopt_candidate(
            field_path="framing.protocol_id",
            idempotency_key="adopt-no-approval-001",
        )

        group = updated.prefill_package.field_candidates["framing.protocol_id"]
        confirmed = [item for item in group.candidates if item.state == "user_confirmed"]
        self.assertEqual(1, len(confirmed))

        # No approval gate or pending-approval state should exist anywhere.
        payload = json.loads(updated.model_dump_json())
        payload_str = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("待医学批准", payload_str)
        self.assertNotIn("ApprovalGate", payload_str)
        self.assertNotIn("approval_gate", payload_str)
        self.assertNotIn("pending_approval", payload_str)

        # The candidate state in the package should be user_confirmed, not
        # routed through any approval workflow.
        package = updated.prefill_package
        group = package.field_candidates["framing.protocol_id"]
        adopted_candidate = next(
            c for c in group.candidates if c.state == "user_confirmed"
        )
        self.assertIsNotNone(adopted_candidate)

    def test_force_regeneration_preserves_current_user_confirmation(self):
        self._create_journey()
        self._generate_prefill()
        adopted = self._adopt_candidate(
            field_path="framing.protocol_id",
            idempotency_key="adopt-before-regenerate-001",
        )
        confirmed_value = adopted.framing.protocol_id

        regenerated = self.service.generate_prefill(
            "proj_test",
            AuthoringPrefillGenerateRequest(
                expected_revision=adopted.revision,
                actor="medical_manager_test",
                idempotency_key="force-regenerate-confirmed-001",
                force=True,
            ),
        )

        group = regenerated.prefill_package.field_candidates["framing.protocol_id"]
        confirmed = [item for item in group.candidates if item.state == "user_confirmed"]
        self.assertEqual(1, len(confirmed))
        self.assertEqual(confirmed_value, confirmed[0].structured_value)
        self.assertEqual(confirmed[0].candidate_id, group.recommended_candidate_id)

    def test_force_regeneration_drops_confirmation_when_project_fact_changed(self):
        self._create_journey()
        self._generate_prefill()
        adopted = self._adopt_candidate(
            field_path="framing.protocol_id",
            idempotency_key="adopt-before-change-001",
        )
        changed = adopted.model_copy(
            update={
                "framing": adopted.framing.model_copy(
                    update={"protocol_id": "MANUALLY-CHANGED"},
                    deep=True,
                )
            },
            deep=True,
        )
        regenerated_package = preserve_current_user_confirmations(
            package=generate_prefill_package(
                state=changed,
                now=NOW,
                actor="medical_manager_test",
            ),
            previous_package=adopted.prefill_package,
            state=changed,
        )

        group = regenerated_package.field_candidates["framing.protocol_id"]
        self.assertFalse(
            any(item.state == "user_confirmed" for item in group.candidates)
        )

    def test_user_edited_candidate_is_the_confirmed_visible_project_fact(self):
        self._create_journey()
        generated = self._generate_prefill()
        group = generated.prefill_package.field_candidates["framing.protocol_id"]
        source_candidate = group.candidates[0]
        edited_value = "RUX-03-002-AI-FIRST"

        adopted = self.service.adopt_prefill_candidate(
            "proj_test",
            AuthoringPrefillAdoptRequest(
                expected_revision=generated.revision,
                expected_package_revision=generated.prefill_package.package_revision,
                field_path="framing.protocol_id",
                # Round 2: user-edit channel (the source card is manual_only
                # and fails closed on this endpoint).
                candidate_id="",
                edited_value=edited_value,
                actor="medical_manager_test",
                idempotency_key="adopt-edited-visible-001",
            ),
        )

        self.assertEqual(edited_value, adopted.framing.protocol_id)
        refreshed_group = adopted.prefill_package.field_candidates["framing.protocol_id"]
        confirmed = [
            item for item in refreshed_group.candidates if item.state == "user_confirmed"
        ]
        self.assertEqual(1, len(confirmed))
        self.assertEqual(edited_value, confirmed[0].structured_value)
        self.assertEqual(confirmed[0].candidate_id, refreshed_group.recommended_candidate_id)
        self.assertEqual("manual", confirmed[0].evidence_refs[0].source_kind)
        self.assertNotEqual(source_candidate.candidate_id, confirmed[0].candidate_id)
        self.assertLessEqual(len(refreshed_group.candidates), 5)

        regenerated = self.service.generate_prefill(
            "proj_test",
            AuthoringPrefillGenerateRequest(
                expected_revision=adopted.revision,
                actor="medical_manager_test",
                idempotency_key="force-regenerate-edited-visible-001",
                force=True,
            ),
        )
        regenerated_group = regenerated.prefill_package.field_candidates[
            "framing.protocol_id"
        ]
        regenerated_confirmed = [
            item
            for item in regenerated_group.candidates
            if item.state == "user_confirmed"
        ]
        self.assertEqual(1, len(regenerated_confirmed))
        self.assertEqual(edited_value, regenerated_confirmed[0].structured_value)
        self.assertEqual(
            regenerated_confirmed[0].candidate_id,
            regenerated_group.recommended_candidate_id,
        )
        self.assertLessEqual(len(regenerated_group.candidates), 5)


class AuthoringPrefillUnitTests(unittest.TestCase):
    """Unit tests for standalone prefill utility functions."""

    def test_values_materially_distinct_whitespace_and_punctuation(self):
        """Canonicalization strips whitespace and punctuation for comparison."""
        self.assertFalse(
            values_materially_distinct("随机、双盲", "随机 双盲"),
            "punctuation-only difference should not be materially distinct",
        )
        self.assertTrue(
            values_materially_distinct("随机", "非随机"),
            "semantically different values must be materially distinct",
        )

    def test_values_materially_distinct_lists(self):
        """List values are canonicalized element-wise."""
        self.assertFalse(
            values_materially_distinct(["SAD", "MAD"], ["SAD", "MAD"]),
        )
        self.assertTrue(
            values_materially_distinct(["SAD", "MAD"], ["SAD"]),
        )

    def test_validate_candidate_for_ready_exact_fact_raises_without_evidence(self):
        """validate_candidate_for_ready_exact_fact raises for exact fact paths
        without evidence_refs."""
        from packages.contracts.workbench_contracts import AuthoringPrefillCandidate

        candidate = AuthoringPrefillCandidate(
            candidate_id="test_exact_no_evidence",
            field_path="picos.primary_endpoint",
            structured_value="第12周ACR20应答率",
            preview="第12周ACR20应答率",
            evidence_refs=[],
            rationale="test",
        )
        with self.assertRaises(ValueError) as ctx:
            validate_candidate_for_ready_exact_fact(candidate)
        self.assertIn("cannot be recommended without evidence", str(ctx.exception))

    def test_validate_candidate_for_ready_exact_fact_passes_with_evidence(self):
        """validate_candidate_for_ready_exact_fact passes when evidence_refs exist."""
        from packages.contracts.workbench_contracts import (
            AuthoringPrefillCandidate,
            AuthoringPrefillEvidenceRef,
        )

        candidate = AuthoringPrefillCandidate(
            candidate_id="test_exact_with_evidence",
            field_path="picos.primary_endpoint",
            structured_value="第12周ACR20应答率",
            preview="第12周ACR20应答率",
            evidence_refs=[
                AuthoringPrefillEvidenceRef(
                    source_kind="synopsis",
                    source_id="synopsis_001",
                    source_text="主要终点：第12周ACR20应答率",
                )
            ],
            rationale="test",
        )
        # Should not raise.
        validate_candidate_for_ready_exact_fact(candidate)

    def test_validate_candidate_non_exact_path_passes_without_evidence(self):
        """Non-exact fact paths pass validation even without evidence."""
        from packages.contracts.workbench_contracts import AuthoringPrefillCandidate

        candidate = AuthoringPrefillCandidate(
            candidate_id="test_non_exact",
            field_path="framing.design_pattern",
            structured_value="随机、双盲、安慰剂对照",
            preview="随机、双盲、安慰剂对照",
            evidence_refs=[],
            rationale="test",
        )
        # Should not raise for non-exact paths.
        validate_candidate_for_ready_exact_fact(candidate)

    def test_package_is_stale_with_stale_status(self):
        """A package with status='stale' is always considered stale."""
        self_tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(self_tmpdir.name) / "stale_test.sqlite3"
            )
            service.create("proj_stale", _create_request(idempotency_key="create-stale"))
            journey = service.get("proj_stale")
            gen_request = AuthoringPrefillGenerateRequest(
                expected_revision=journey.revision,
                actor="medical_manager_test",
                idempotency_key="prefill-stale-gen",
            )
            updated = service.generate_prefill("proj_stale", gen_request)
            package = updated.prefill_package

            # Force status to stale.
            stale_package = package.model_copy(update={"status": "stale"})
            self.assertTrue(package_is_stale(stale_package, state=updated))
        finally:
            self_tmpdir.cleanup()

    def test_supported_adopt_paths_coverage(self):
        """SUPPORTED_ADOPT_PATHS includes both study definition and design proposal paths."""
        # Framing paths.
        self.assertIn("framing.protocol_id", SUPPORTED_ADOPT_PATHS)
        self.assertIn("framing.design_pattern", SUPPORTED_ADOPT_PATHS)
        # Picos paths.
        self.assertIn("picos.design_archetype", SUPPORTED_ADOPT_PATHS)
        self.assertIn("picos.population_summary", SUPPORTED_ADOPT_PATHS)
        # Design proposal paths.
        self.assertIn("design.randomization", SUPPORTED_ADOPT_PATHS)
        self.assertIn("design.blinding", SUPPORTED_ADOPT_PATHS)
        self.assertIn("design.phase1_parts", SUPPORTED_ADOPT_PATHS)
        self.assertIn("design.arms_or_cohorts", SUPPORTED_ADOPT_PATHS)

    def test_exact_fact_paths_are_not_in_supported_adopt_paths(self):
        """EXACT_FACT_PATHS are deliberately excluded from SUPPORTED_ADOPT_PATHS
        to prevent unvalidated adoption of precise clinical facts."""
        for path in EXACT_FACT_PATHS:
            self.assertNotIn(
                path,
                SUPPORTED_ADOPT_PATHS,
                f"exact fact path {path!r} should not be directly adoptable",
            )


class AuthoringPrefillGenerateIdempotencyTests(unittest.TestCase):
    """Tests for generate_prefill idempotency and force-regeneration."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_generate_idempotent_replay(self):
        """Same idempotency key returns the same package without revision bump."""
        journey = self.service.get("proj_test")
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="prefill-idem-001",
        )
        first = self.service.generate_prefill("proj_test", request)
        second = self.service.generate_prefill("proj_test", request)

        self.assertEqual(first.revision, second.revision)
        self.assertEqual(
            first.prefill_package.package_id,
            second.prefill_package.package_id,
        )

    def test_generate_stale_revision_raises_conflict(self):
        """Wrong expected_revision raises ConflictError."""
        journey = self.service.get("proj_test")
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="prefill-conflict-001",
        )
        self.service.generate_prefill("proj_test", request)

        # Now use the old revision with a different key.
        stale_request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,  # stale after first generate
            actor="medical_manager_test",
            idempotency_key="prefill-conflict-002",
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
            self.service.generate_prefill("proj_test", stale_request)

    def test_generate_without_creation_minimum_raises(self):
        """Prefill generation without creation minimum raises ValueError."""
        # Create a journey with incomplete framing (missing study_phase).
        incomplete_service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "incomplete.sqlite3"
        )
        incomplete_service.create(
            "proj_incomplete",
            _create_request(
                study_phase="",
                idempotency_key="create-incomplete",
            ),
        )
        journey = incomplete_service.get("proj_incomplete")
        request = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="prefill-incomplete-001",
        )
        with self.assertRaises(ValueError) as ctx:
            incomplete_service.generate_prefill("proj_incomplete", request)
        self.assertIn("creation minimum", str(ctx.exception))


# ---------------------------------------------------------------------------
# Corrective round 2: progress treats an empty recommended slot as blocked
# ---------------------------------------------------------------------------

class RecommendedSlotProgressTests(unittest.TestCase):
    """A group whose recommended slot is empty (every visible candidate is
    pending/manual/unsafe) has no effective recommendation and counts as
    pending/blocked in the package progress computation."""

    def _candidate(
        self, candidate_id: str, *, role: str
    ) -> AuthoringPrefillCandidate:
        return AuthoringPrefillCandidate(
            candidate_id=candidate_id,
            field_path="package.design",
            structured_value="随机",
            preview="随机",
            recommendation_role=role,
        )

    def _group(
        self, candidate_id: str, *, role: str, recommended: str
    ) -> AuthoringPrefillFieldCandidates:
        return AuthoringPrefillFieldCandidates(
            field_path="package.design",
            recommended_candidate_id=recommended,
            candidates=[self._candidate(candidate_id, role=role)],
        )

    def test_pending_only_empty_recommendation_counts_as_blocked(self):
        groups = {
            "package.design": self._group(
                "c_pending", role="pending_decision", recommended=""
            )
        }
        adoptable, pending = _count_adoptable_and_pending_fields(groups)
        self.assertEqual((0, 1), (adoptable, pending))

    def test_mixed_group_with_safe_recommendation_counts_as_adoptable(self):
        # Progress counts groups by their recommended candidate: a mixed
        # group whose slot points at a safe non-pending candidate counts as
        # adoptable; the pending sibling does not add a blocked field.
        groups = {
            "package.design": AuthoringPrefillFieldCandidates(
                field_path="package.design",
                recommended_candidate_id="c_alt",
                candidates=[
                    self._candidate("c_pending", role="pending_decision"),
                    self._candidate("c_alt", role="alternative"),
                ],
            )
        }
        adoptable, pending = _count_adoptable_and_pending_fields(groups)
        self.assertEqual((1, 0), (adoptable, pending))

    def test_pending_role_recommendation_counts_as_blocked(self):
        groups = {
            "package.design": self._group(
                "c_pending", role="pending_decision", recommended="c_pending"
            )
        }
        adoptable, pending = _count_adoptable_and_pending_fields(groups)
        self.assertEqual((0, 1), (adoptable, pending))

    def test_empty_group_with_empty_recommendation_counts_neither(self):
        groups = {
            "package.design": AuthoringPrefillFieldCandidates(
                field_path="package.design",
                recommended_candidate_id="",
                candidates=[],
            )
        }
        adoptable, pending = _count_adoptable_and_pending_fields(groups)
        self.assertEqual((0, 0), (adoptable, pending))


if __name__ == "__main__":
    unittest.main()
