"""Focused tests for the single-candidate prefill adoption gates and the
next-revision evidence catalog identity (worker_01 corrective round).

Covers:
- ``build_evidence_catalog(..., journey_revision=...)`` builds the catalog
  against the next persisted journey revision so persisted and live catalog
  identity agree (package.journey_revision == catalog.journey_revision ==
  journey.revision).
- ``generate_prefill`` passes the next revision into ``enrich_package``.
- Evidence-bound pending / manual / server-derived-pending candidates are
  rejected by ``adopt_prefill_candidate`` with a stable conflict (4xx), and
  every rejected attempt leaves study definition, journey revision, package
  revision, and event counts unchanged.
- Evidence-bound non-pending candidates require live server verification:
  genuine bindings adopt exactly once; tampered bindings, tampered catalogs,
  and stale revisions fail closed.
- Unbound deterministic decision scaffolds keep their lazy-writer adoption
  behavior (regression guard).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from packages.contracts.workbench_contracts import (
    AuthoringPrefillAdoptRequest,
    AuthoringPrefillCandidate,
    AuthoringPrefillClaimBinding,
    AuthoringPrefillFieldCandidates,
    AuthoringPrefillGenerateRequest,
    MedicalWritingAuthoringJourney,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingStudyFraming,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyConflictError,
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill import (
    ServerEvidenceVerifier,
)
from services.api.app.medical_writing_authoring_prefill_evidence import (
    _catalog_sha256,
    build_evidence_catalog,
)
from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
    INSUFFICIENT_SUPPORT_REUSE_DECISION,
)

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

CONDITION_FIELD = "framing.clinicaltrials_condition_term"
ADOPTED_CONDITION = "Rheumatoid Arthritis"


def _create_request(project_id: str, idempotency_key: str):
    return MedicalWritingAuthoringJourneyCreateRequest(
        framing=MedicalWritingStudyFraming(
            investigational_product="CMS-D017",
            indication="类风湿关节炎",
            study_phase="II期",
            clinicaltrials_condition_term="",
        ),
        actor="medical_manager_test",
        idempotency_key=idempotency_key,
    )


def _live_resolver_verifier(svc, project_id) -> ServerEvidenceVerifier:
    """Verifier that rebuilds the live catalog from the current journey at
    adoption time (mirrors the endpoint wiring)."""

    def _catalog_resolver():
        journey = svc.get(project_id)
        return build_evidence_catalog(
            journey,
            snapshot=None,
            journey_revision=journey.revision,
        )

    return ServerEvidenceVerifier(catalog_resolver=_catalog_resolver)


def _indication_entry(catalog):
    return next(e for e in catalog.entries if e.source_id == "framing.indication")


def _make_field_candidate(
    *,
    candidate_id: str,
    catalog,
    recommendation_role: str = "recommended",
    adoption_mode: str = "manual_only",
    evidence_status: str = "supported",
    value: str = ADOPTED_CONDITION,
) -> AuthoringPrefillCandidate:
    entry = _indication_entry(catalog)
    binding = AuthoringPrefillClaimBinding(
        target_path=CONDITION_FIELD,
        value_pointer="",
        catalog_entry_id=entry.catalog_entry_id,
        source_id=entry.source_id,
        locator=entry.locator,
        quote_sha256=entry.quote_sha256,
        support_kind="exact_fact",
    )
    return AuthoringPrefillCandidate(
        candidate_id=candidate_id,
        field_path=CONDITION_FIELD,
        structured_value=value,
        preview=value,
        rationale="测试用证据绑定候选。",
        confidence="medium",
        state="ai_proposed",
        candidate_scope="field",
        recommendation_role=recommendation_role,
        adoption_mode=adoption_mode,  # type: ignore[arg-type]
        evidence_catalog_id=catalog.catalog_id,
        evidence_catalog_sha256=catalog.catalog_sha256,
        claim_bindings=[binding],
        evidence_status=evidence_status,  # type: ignore[arg-type]
    )


def _inject_field_candidate(svc, project_id, *, candidate, catalog):
    """Inject a field candidate + catalog into the persisted package."""
    with svc._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = svc._current_row(conn, project_id)
        journey = MedicalWritingAuthoringJourney.model_validate_json(
            row["payload_json"]
        )
        package = journey.prefill_package
        group = AuthoringPrefillFieldCandidates(
            field_path=candidate.field_path,
            recommended_candidate_id=candidate.candidate_id,
            candidates=[candidate],
        )
        field_candidates = dict(package.field_candidates)
        field_candidates[candidate.field_path] = group
        package = package.model_copy(
            update={
                "field_candidates": field_candidates,
                "evidence_catalog": catalog,
            },
            deep=True,
        )
        updated = journey.model_copy(
            update={"prefill_package": package}, deep=True
        )
        conn.execute(
            "UPDATE medical_writing_authoring_journeys SET payload_json = ? "
            "WHERE project_id = ?",
            (updated.model_dump_json(), project_id),
        )
        conn.commit()


def _mutate_package(svc, project_id, mutator):
    """Apply *mutator(package)* to the persisted package."""
    with svc._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = svc._current_row(conn, project_id)
        journey = MedicalWritingAuthoringJourney.model_validate_json(
            row["payload_json"]
        )
        package = mutator(journey.prefill_package)
        updated = journey.model_copy(
            update={"prefill_package": package}, deep=True
        )
        conn.execute(
            "UPDATE medical_writing_authoring_journeys SET payload_json = ? "
            "WHERE project_id = ?",
            (updated.model_dump_json(), project_id),
        )
        conn.commit()


def _event_count(svc, project_id, event_type: str) -> int:
    with svc._connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM medical_writing_authoring_journey_events "
            "WHERE project_id = ? AND event_type = ?",
            (project_id, event_type),
        ).fetchone()[0]


def _state_snapshot(svc, project_id) -> dict:
    journey = svc.get(project_id)
    return {
        "revision": journey.revision,
        "package_revision": journey.prefill_package.package_revision,
        "study_definition": (
            journey.study_definition.model_dump(mode="json")
            if journey.study_definition is not None
            else None
        ),
        "condition_term": journey.framing.clinicaltrials_condition_term,
        "adopted_events": _event_count(
            svc, project_id, "authoring_journey_prefill_adopted"
        ),
        "generated_events": _event_count(
            svc, project_id, "authoring_journey_prefill_generated"
        ),
    }


class NextRevisionCatalogIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_id = "proj_gate_identity"
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create(
            self.project_id,
            _create_request(self.project_id, "create-identity"),
        )
        self.service.generate_prefill(
            self.project_id,
            AuthoringPrefillGenerateRequest(
                expected_revision=1,
                actor="medical_manager_test",
                idempotency_key="gen-identity",
            ),
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_catalog_override_uses_next_revision(self):
        journey = self.service.get(self.project_id)
        self.assertEqual(2, journey.revision)
        default_catalog = build_evidence_catalog(journey, snapshot=None)
        next_catalog = build_evidence_catalog(
            journey, snapshot=None, journey_revision=journey.revision + 1
        )
        # Override changes the identity binding.
        self.assertEqual(journey.revision, default_catalog.journey_revision)
        self.assertEqual(journey.revision + 1, next_catalog.journey_revision)
        self.assertNotEqual(default_catalog.catalog_id, next_catalog.catalog_id)
        self.assertNotEqual(
            default_catalog.catalog_sha256, next_catalog.catalog_sha256
        )
        # Deterministic identity: recomputed sha matches the stored sha.
        recomputed = _catalog_sha256(
            next_catalog.project_id,
            next_catalog.journey_revision,
            next_catalog.snapshot_id,
            next_catalog.entries,
        )
        self.assertEqual(next_catalog.catalog_sha256, recomputed)

    def test_generate_passes_next_revision_to_enricher(self):
        calls = {}

        class StubEnricher:
            def enrich_package(
                self,
                *,
                package,
                state,
                snapshot=None,
                journey_revision=None,
            ):
                calls["journey_revision"] = journey_revision
                calls["state_revision"] = state.revision
                catalog = build_evidence_catalog(
                    state,
                    snapshot=snapshot,
                    journey_revision=journey_revision,
                )
                candidate = _make_field_candidate(
                    candidate_id="mwprefilleb_stub_identity",
                    catalog=catalog,
                )
                field_candidates = dict(package.field_candidates)
                field_candidates[candidate.field_path] = (
                    AuthoringPrefillFieldCandidates(
                        field_path=candidate.field_path,
                        recommended_candidate_id=candidate.candidate_id,
                        candidates=[candidate],
                    )
                )
                return package.model_copy(
                    update={
                        "field_candidates": field_candidates,
                        "evidence_catalog": catalog,
                    },
                    deep=True,
                )

        with patch(
            "services.api.app.medical_writing_research_pipeline."
            "research_ready_for_design_recommendations",
            return_value=(True, "test_unlocked"),
        ):
            generated = self.service.generate_prefill(
                self.project_id,
                AuthoringPrefillGenerateRequest(
                    expected_revision=2,
                    force=True,
                    actor="medical_manager_test",
                    idempotency_key="gen-identity-ai",
                ),
                ai_enricher=StubEnricher(),
            )
        # The enricher received the next persisted revision.
        self.assertEqual(2, calls["state_revision"])
        self.assertEqual(3, calls["journey_revision"])
        persisted = generated.prefill_package
        catalog = persisted.evidence_catalog
        self.assertIsNotNone(catalog)
        # Persisted package, persisted catalog, and live journey agree.
        self.assertEqual(3, generated.revision)
        self.assertEqual(persisted.journey_revision, generated.revision)
        self.assertEqual(catalog.journey_revision, generated.revision)
        self.assertEqual(catalog.journey_revision, persisted.journey_revision)
        self.assertEqual(catalog.catalog_id, persisted.evidence_catalog.catalog_id)


class SingleCandidateAdoptionGateTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_id = "proj_gate_single"
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create(
            self.project_id,
            _create_request(self.project_id, "create-single"),
        )
        self.service.generate_prefill(
            self.project_id,
            AuthoringPrefillGenerateRequest(
                expected_revision=1,
                actor="medical_manager_test",
                idempotency_key="gen-single",
            ),
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _journey_catalog(self):
        journey = self.service.get(self.project_id)
        return build_evidence_catalog(
            journey,
            snapshot=None,
            journey_revision=journey.revision,
        )

    def _adopt(self, *, candidate_id, expected_revision=None, edited_value=None,
               verifier=None, idempotency_key="adopt-single"):
        journey = self.service.get(self.project_id)
        package = journey.prefill_package
        request = AuthoringPrefillAdoptRequest(
            expected_revision=(
                expected_revision if expected_revision is not None else journey.revision
            ),
            expected_package_revision=package.package_revision,
            field_path=CONDITION_FIELD,
            candidate_id=candidate_id,
            edited_value=edited_value,
            actor="medical_manager_test",
            idempotency_key=idempotency_key,
        )
        return self.service.adopt_prefill_candidate(
            self.project_id, request, evidence_verifier=verifier
        )

    def _assert_unchanged(self, before: dict):
        after = _state_snapshot(self.service, self.project_id)
        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # Pending / manual / server-pending gates
    # ------------------------------------------------------------------

    def test_evidence_bound_pending_decision_rejected_no_mutation(self):
        """Crafted adoption of a pending/manual_only evidence-bound candidate
        returns a conflict and leaves every persisted surface unchanged."""
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_pending_gate",
            catalog=catalog,
            recommendation_role="pending_decision",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        verifier = _live_resolver_verifier(self.service, self.project_id)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(candidate_id=candidate.candidate_id, verifier=verifier)
        self.assertIn("pending_decision", str(ctx.exception))
        self.assertIn("blocked", str(ctx.exception))
        self._assert_unchanged(before)

    def test_evidence_bound_insufficient_support_promoted_rejected_no_mutation(self):
        """A promoted (recommended) candidate bound to an
        insufficient-support corpus entry is server-pending and must be
        rejected before any value is applied."""
        catalog = self._journey_catalog()
        limited_entries = [
            e.model_copy(
                update={
                    "provenance": {
                        **e.provenance,
                        "reuse_decision": INSUFFICIENT_SUPPORT_REUSE_DECISION,
                    }
                },
                deep=True,
            )
            for e in catalog.entries
        ]
        limited_catalog = catalog.model_copy(
            update={"entries": limited_entries}, deep=True
        )
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_limited_gate",
            catalog=limited_catalog,
            recommendation_role="recommended",
            adoption_mode="batch_allowed",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=limited_catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        verifier = _live_resolver_verifier(self.service, self.project_id)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(candidate_id=candidate.candidate_id, verifier=verifier)
        self.assertIn("insufficient-support", str(ctx.exception))
        self._assert_unchanged(before)

    def test_manual_only_recommended_rejected_no_mutation(self):
        """Corrective round 2: every manual_only candidate is rejected via
        the single-candidate path even when unbound and recommended."""
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_manual_only_gate",
            catalog=catalog,
            adoption_mode="manual_only",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(candidate_id=candidate.candidate_id)
        self.assertIn("manual_only", str(ctx.exception))
        self._assert_unchanged(before)

    def test_manual_only_bound_with_verifier_still_rejected_no_mutation(self):
        """The manual_only gate fires before live verification: a bound
        manual_only candidate is rejected even when a verifier would pass it."""
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_manual_only_bound_gate",
            catalog=catalog,
            adoption_mode="manual_only",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        verifier = _live_resolver_verifier(self.service, self.project_id)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(candidate_id=candidate.candidate_id, verifier=verifier)
        self.assertIn("manual_only", str(ctx.exception))
        self._assert_unchanged(before)

    def test_evidence_bound_without_verifier_fails_closed_no_mutation(self):
        """A batch_allowed evidence-bound candidate without a verifier fails
        closed (mirrors the composite path)."""
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_no_verifier",
            catalog=catalog,
            adoption_mode="batch_allowed",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(candidate_id=candidate.candidate_id)
        self.assertIn("requires server evidence verification", str(ctx.exception))
        self._assert_unchanged(before)

    def test_unbound_deterministic_pending_scaffold_rejected_no_mutation(self):
        """Corrective round 2: deterministic pending scaffolds are rejected
        on the single-candidate path even though they are unbound — the
        previous lazy-writer exception is obsolete."""
        journey = self.service.get(self.project_id)
        group = journey.prefill_package.field_candidates[
            "design.interim_analysis"
        ]
        candidate = group.candidates[0]
        self.assertEqual("pending_decision", candidate.recommendation_role)
        self.assertEqual("manual_only", candidate.adoption_mode)
        before = _state_snapshot(self.service, self.project_id)
        request = AuthoringPrefillAdoptRequest(
            expected_revision=journey.revision,
            expected_package_revision=journey.prefill_package.package_revision,
            field_path="design.interim_analysis",
            candidate_id=candidate.candidate_id,
            actor="medical_manager_test",
            idempotency_key="adopt-interim-lazy",
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self.service.adopt_prefill_candidate(self.project_id, request)
        self.assertIn("pending_decision", str(ctx.exception))
        self._assert_unchanged(before)

    # ------------------------------------------------------------------
    # Live verification: success, tamper, stale
    # ------------------------------------------------------------------

    def test_evidence_bound_adopt_success_exactly_once(self):
        """Genuine evidence-bound adoption verifies against one coherent
        next-revision catalog and persists exactly one event."""
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_success_gate",
            catalog=catalog,
            adoption_mode="batch_allowed",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        journey = self.service.get(self.project_id)
        # Identity agreement before adoption: package, persisted catalog and
        # the live-rebuilt catalog all carry the same journey revision.
        self.assertEqual(
            journey.prefill_package.journey_revision,
            journey.prefill_package.evidence_catalog.journey_revision,
        )
        self.assertEqual(
            journey.prefill_package.journey_revision,
            journey.revision,
        )
        verifier = _live_resolver_verifier(self.service, self.project_id)
        before = _state_snapshot(self.service, self.project_id)
        adopted = self._adopt(
            candidate_id=candidate.candidate_id,
            verifier=verifier,
            idempotency_key="adopt-success",
        )
        self.assertEqual(before["revision"] + 1, adopted.revision)
        self.assertEqual(ADOPTED_CONDITION, adopted.framing.clinicaltrials_condition_term)
        self.assertEqual(
            before["package_revision"] + 1,
            adopted.prefill_package.package_revision,
        )
        self.assertEqual(
            before["adopted_events"] + 1,
            _event_count(self.service, self.project_id, "authoring_journey_prefill_adopted"),
        )
        # Idempotent replay with the identical request returns the same
        # result without a second event.
        journey_after = self.service.get(self.project_id)
        replay_request = AuthoringPrefillAdoptRequest(
            expected_revision=before["revision"],
            expected_package_revision=before["package_revision"],
            field_path=CONDITION_FIELD,
            candidate_id=candidate.candidate_id,
            actor="medical_manager_test",
            idempotency_key="adopt-success",
        )
        replayed = self.service.adopt_prefill_candidate(
            self.project_id,
            replay_request,
            evidence_verifier=verifier,
        )
        self.assertEqual(journey_after.revision, replayed.revision)
        self.assertEqual(adopted.revision, replayed.revision)
        self.assertEqual(
            before["adopted_events"] + 1,
            _event_count(self.service, self.project_id, "authoring_journey_prefill_adopted"),
        )

    def test_tampered_binding_rejected_no_mutation(self):
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_tamper_binding",
            catalog=catalog,
            adoption_mode="batch_allowed",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        # Tamper with the persisted binding's source_id.
        def _tamper(package):
            group = package.field_candidates[CONDITION_FIELD]
            cand = group.candidates[0]
            binding = cand.claim_bindings[0].model_copy(
                update={"source_id": "tampered.source.id"}, deep=True
            )
            cand = cand.model_copy(
                update={"claim_bindings": [binding]}, deep=True
            )
            return package.model_copy(
                update={
                    "field_candidates": {
                        **package.field_candidates,
                        CONDITION_FIELD: group.model_copy(
                            update={"candidates": [cand]}, deep=True
                        ),
                    }
                },
                deep=True,
            )

        _mutate_package(self.service, self.project_id, _tamper)
        before = _state_snapshot(self.service, self.project_id)
        verifier = _live_resolver_verifier(self.service, self.project_id)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(candidate_id=candidate.candidate_id, verifier=verifier)
        self.assertIn("tampered, stale", str(ctx.exception))
        self._assert_unchanged(before)

    def test_tampered_catalog_rejected_no_mutation(self):
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_tamper_catalog",
            catalog=catalog,
            adoption_mode="batch_allowed",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        # Tamper with a persisted catalog entry so the persisted catalog no
        # longer matches the live rebuild (and its hash no longer matches).
        def _tamper(package):
            catalog = package.evidence_catalog
            entries = [
                e.model_copy(
                    update={
                        "quote": "篡改的引用原文",
                        "quote_sha256": hashlib.sha256(
                            "篡改的引用原文".encode("utf-8")
                        ).hexdigest(),
                    },
                    deep=True,
                )
                if e.source_id == "framing.indication"
                else e
                for e in catalog.entries
            ]
            tampered = catalog.model_copy(update={"entries": entries}, deep=True)
            return package.model_copy(
                update={"evidence_catalog": tampered}, deep=True
            )

        _mutate_package(self.service, self.project_id, _tamper)
        before = _state_snapshot(self.service, self.project_id)
        verifier = _live_resolver_verifier(self.service, self.project_id)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(candidate_id=candidate.candidate_id, verifier=verifier)
        self.assertIn("tampered, stale", str(ctx.exception))
        self._assert_unchanged(before)

    def test_stale_expected_revision_rejected_no_mutation(self):
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_stale_rev",
            catalog=catalog,
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        verifier = _live_resolver_verifier(self.service, self.project_id)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(
                candidate_id=candidate.candidate_id,
                expected_revision=1,
                verifier=verifier,
                idempotency_key="adopt-stale",
            )
        self.assertIn("stale journey revision", str(ctx.exception))
        self._assert_unchanged(before)


class EvidenceStatusGapDefenseTests(unittest.TestCase):
    """Corrective round 2 (worker_03): a candidate whose evidence status is
    insufficient or whose visible gap marks a substantive claim absent from
    its bound quotes is rejected BEFORE any verifier result; no mutation."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_id = "proj_gate_defense"
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create(
            self.project_id,
            _create_request(self.project_id, "create-defense"),
        )
        self.service.generate_prefill(
            self.project_id,
            AuthoringPrefillGenerateRequest(
                expected_revision=1,
                actor="medical_manager_test",
                idempotency_key="gen-defense",
            ),
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _journey_catalog(self):
        journey = self.service.get(self.project_id)
        return build_evidence_catalog(
            journey,
            snapshot=None,
            journey_revision=journey.revision,
        )

    def _adopt(
        self,
        *,
        candidate_id,
        verifier=None,
        idempotency_key="adopt-defense",
    ):
        journey = self.service.get(self.project_id)
        package = journey.prefill_package
        request = AuthoringPrefillAdoptRequest(
            expected_revision=journey.revision,
            expected_package_revision=package.package_revision,
            field_path=CONDITION_FIELD,
            candidate_id=candidate_id,
            actor="medical_manager_test",
            idempotency_key=idempotency_key,
        )
        return self.service.adopt_prefill_candidate(
            self.project_id, request, evidence_verifier=verifier
        )

    def _assert_unchanged(self, before: dict):
        after = _state_snapshot(self.service, self.project_id)
        self.assertEqual(before, after)

    def test_insufficient_evidence_status_rejected_before_verifier_no_mutation(self):
        """A batch_allowed evidence-bound candidate with
        evidence_status="insufficient" is rejected before the verifier runs
        and no persisted surface changes."""
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_insufficient_defense",
            catalog=catalog,
            adoption_mode="batch_allowed",
            evidence_status="insufficient",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        calls = {"verifier": 0}

        class _RecordingVerifier:
            def verify_candidate_path(self, **kwargs):
                calls["verifier"] += 1
                return True

        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(
                candidate_id=candidate.candidate_id,
                verifier=_RecordingVerifier(),
            )
        self.assertIn("insufficient", str(ctx.exception))
        self.assertEqual(0, calls["verifier"])
        self._assert_unchanged(before)

    def test_unsupported_substantive_gap_rejected_before_verifier_no_mutation(self):
        """A candidate carrying a 声称内容未在引用原文中出现：... gap is
        rejected before the verifier runs and no persisted surface changes."""
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_gap_defense",
            catalog=catalog,
            adoption_mode="batch_allowed",
            evidence_status="partially_supported",
        ).model_copy(
            update={
                "evidence_gaps": [
                    "声称内容未在引用原文中出现：AChR抗体阳性相关表述"
                ]
            },
            deep=True,
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        calls = {"verifier": 0}

        class _RecordingVerifier:
            def verify_candidate_path(self, **kwargs):
                calls["verifier"] += 1
                return True

        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self._adopt(
                candidate_id=candidate.candidate_id,
                verifier=_RecordingVerifier(),
            )
        self.assertIn("evidence gap", str(ctx.exception))
        self.assertEqual(0, calls["verifier"])
        self._assert_unchanged(before)

    def test_supported_clean_candidate_still_adopts(self):
        """Positive control: a batch_allowed supported candidate without the
        unsupported gap still adopts through the live verifier."""
        catalog = self._journey_catalog()
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_clean_defense",
            catalog=catalog,
            adoption_mode="batch_allowed",
            evidence_status="supported",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        before = _state_snapshot(self.service, self.project_id)
        verifier = _live_resolver_verifier(self.service, self.project_id)
        adopted = self._adopt(
            candidate_id=candidate.candidate_id,
            verifier=verifier,
            idempotency_key="adopt-clean-defense",
        )
        self.assertEqual(before["revision"] + 1, adopted.revision)
        self.assertEqual(
            ADOPTED_CONDITION,
            adopted.framing.clinicaltrials_condition_term,
        )


class SingleCandidateAdoptionApiTests(unittest.TestCase):
    """Crafted HTTP POST must return a stable 4xx and leave the study
    definition unchanged (recheck #1)."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.project_id = "proj_mgk10_crswnp"
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "authoring_journey.sqlite3"
        )
        self.service.create(
            self.project_id,
            _create_request(self.project_id, "api-create-single-gate"),
        )
        self.service.generate_prefill(
            self.project_id,
            AuthoringPrefillGenerateRequest(
                expected_revision=1,
                actor="medical_manager_test",
                idempotency_key="api-gen-single-gate",
            ),
        )
        catalog = build_evidence_catalog(
            self.service.get(self.project_id),
            snapshot=None,
            journey_revision=2,
        )
        candidate = _make_field_candidate(
            candidate_id="mwprefilleb_api_pending",
            catalog=catalog,
            recommendation_role="pending_decision",
        )
        _inject_field_candidate(
            self.service, self.project_id, candidate=candidate, catalog=catalog
        )
        self.patch = patch(
            "services.api.app.main.medical_writing_authoring_journey_service",
            self.service,
        )
        self.patch.start()
        from fastapi.testclient import TestClient
        from services.api.app import main as app_main

        self.client = TestClient(app_main.app)

    def tearDown(self):
        self.patch.stop()
        self.tmpdir.cleanup()

    def test_crafted_pending_post_returns_409_no_mutation(self):
        journey = self.service.get(self.project_id)
        before = _state_snapshot(self.service, self.project_id)
        response = self.client.post(
            f"/api/projects/{self.project_id}/medical-writing/"
            "authoring-journey/prefill-package/adopt",
            json={
                "expected_revision": journey.revision,
                "expected_package_revision": journey.prefill_package.package_revision,
                "field_path": CONDITION_FIELD,
                "candidate_id": "mwprefilleb_api_pending",
                "actor": "medical_manager_test",
                "idempotency_key": "api-adopt-pending",
            },
        )
        self.assertEqual(409, response.status_code, response.text)
        self.assertIn("pending_decision", response.json()["detail"])
        self._assert_unchanged(before)

    def _assert_unchanged(self, before: dict):
        after = _state_snapshot(self.service, self.project_id)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
