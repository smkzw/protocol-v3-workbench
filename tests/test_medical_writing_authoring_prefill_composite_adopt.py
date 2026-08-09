"""Tests for atomic composite candidate adoption (W3 r02).

Round 02 fixes:
- Every non-override candidate path must pass server evidence verification.
- ServerEvidenceVerifier re-validates catalog/binding drift.
- Leaf-level derived conflict detection with delta computation.
- Idempotent replay fail-closed when receipt is missing/corrupted.
- Partial adoption does not supersede existing user_confirmed candidates.
- Package status uses positive allowlist (ready/partial).
- Event records path_origins with stable sort.
- User-edited composite preserves non-override evidence refs.
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
    AuthoringPrefillCandidate,
    AuthoringPrefillClaimBinding,
    AuthoringPrefillCompositeAdoptRequest,
    AuthoringPrefillEvidenceCatalog,
    AuthoringPrefillEvidenceCatalogEntry,
    AuthoringPrefillEvidenceRef,
    AuthoringPrefillFieldCandidates,
    AuthoringPrefillGenerateRequest,
    AuthoringPrefillPackage,
    MedicalWritingAuthoringJourney,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingStudyFraming,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyConflictError,
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill import (
    MedicalWritingAuthoringPolicyError,
    ServerEvidenceVerifier,
    map_design_adoption_to_study_updates,
    payload_sha256,
    plan_composite_adoption,
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


def _make_catalog_entry(
    *,
    catalog_entry_id: str = "entry_001",
    catalog_id: str = "catalog_001",
    source_id: str = "framing.investigational_product",
    locator: str = "framing.investigational_product",
    quote: str = "CMS-D017",
    target_paths: tuple[str, ...] = ("framing.investigational_product",),
    support_scope: str = "current_project_fact",
    source_kind: str = "project_fact",
    source_revision: str = "",
    title: str = "",
) -> AuthoringPrefillEvidenceCatalogEntry:
    quote_sha = hashlib.sha256(quote.encode("utf-8")).hexdigest()
    return AuthoringPrefillEvidenceCatalogEntry(
        catalog_entry_id=catalog_entry_id,
        catalog_id=catalog_id,
        source_kind=source_kind,  # type: ignore
        source_id=source_id,
        source_revision=source_revision,
        locator=locator,
        quote=quote,
        quote_sha256=quote_sha,
        title=title or quote,
        support_scope=support_scope,  # type: ignore
        supported_target_paths=list(target_paths),
    )


def _make_catalog(
    *,
    project_id: str = "proj_test",
    journey_revision: int = 1,
    entries: list[AuthoringPrefillEvidenceCatalogEntry] | None = None,
    snapshot_id: str = "",
) -> AuthoringPrefillEvidenceCatalog:
    catalog_id = "catalog_" + hashlib.sha256(
        f"{project_id}|{journey_revision}|{snapshot_id}".encode()
    ).hexdigest()[:24]
    if entries is None:
        entries = [_make_catalog_entry(catalog_id=catalog_id)]
    else:
        # Fix catalog_id on all entries to match.
        entries = [
            e.model_copy(update={"catalog_id": catalog_id}) for e in entries
        ]
    from services.api.app.medical_writing_authoring_prefill_evidence import (
        _catalog_sha256,
    )
    catalog_sha = _catalog_sha256(project_id, journey_revision, snapshot_id, entries)
    return AuthoringPrefillEvidenceCatalog(
        catalog_id=catalog_id,
        project_id=project_id,
        journey_revision=journey_revision,
        snapshot_id=snapshot_id,
        entries=entries,
        catalog_sha256=catalog_sha,
    )


def _make_bound_candidate(
    *,
    candidate_id: str = "comp_cand_001",
    field_path: str = "design.composite_001",
    target_paths: list[str] | None = None,
    structured_value: dict | None = None,
    catalog: AuthoringPrefillEvidenceCatalog | None = None,
    recommendation_role: str = "recommended",
    state: str = "ai_proposed",
    candidate_scope: str = "module",
    adoption_mode: str = "batch_allowed",
    evidence_status: str = "supported",
    evidence_gaps: list[str] | None = None,
) -> tuple[AuthoringPrefillCandidate, AuthoringPrefillEvidenceCatalog]:
    """Build a candidate with proper server-verified bindings for each
    atomic leaf in every target path.

    For package-scope candidates, W2b requires a non-empty RFC 6901
    value_pointer for every non-empty atomic leaf. This helper
    enumerates all leaves under each target_path and creates one
    binding per leaf.
    """
    if target_paths is None:
        target_paths = ["design.randomization", "design.blinding"]
    if structured_value is None:
        structured_value = {
            "design.randomization": {"mode": "随机"},
            "design.blinding": {"mode": "双盲"},
        }
    # Model invariant: pending_decision role requires manual_only mode.
    if recommendation_role == "pending_decision":
        adoption_mode = "manual_only"
    if catalog is None:
        entries = []
        for tp in target_paths:
            quote = json.dumps(structured_value[tp], ensure_ascii=False)
            entries.append(_make_catalog_entry(
                catalog_entry_id=f"entry_{tp}",
                source_id=tp,
                locator=tp,
                quote=quote,
                target_paths=(tp,),
            ))
        catalog = _make_catalog(entries=entries)

    # Build bindings: one per atomic leaf under each target path.
    from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
        _enumerate_atomic_leaves,
        _escape_pointer_segment,
    )
    bindings = []
    for tp in target_paths:
        entry = next(
            (
                e
                for e in catalog.entries
                if e.source_id == tp or tp in e.supported_target_paths
            ),
            None,
        )
        if entry is None:
            raise ValueError(f"catalog has no entry supporting {tp}")
        support_kind = (
            "competitor_option"
            if entry.support_scope == "competitor_observation"
            else "exact_fact"
        )
        value = structured_value[tp]
        if isinstance(value, dict):
            leaves = _enumerate_atomic_leaves(value, f"/{tp}")
            for leaf_pointer in leaves:
                bindings.append(AuthoringPrefillClaimBinding(
                    target_path=tp,
                    value_pointer=leaf_pointer,
                    catalog_entry_id=entry.catalog_entry_id,
                    source_id=entry.source_id,
                    locator=entry.locator,
                    quote_sha256=entry.quote_sha256,
                    support_kind=support_kind,
                ))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, (str, int, float, bool)):
                    bindings.append(AuthoringPrefillClaimBinding(
                        target_path=tp,
                        value_pointer=f"/{tp}/{i}",
                        catalog_entry_id=entry.catalog_entry_id,
                        source_id=entry.source_id,
                        locator=entry.locator,
                        quote_sha256=entry.quote_sha256,
                        support_kind=support_kind,
                    ))
        else:
            # Scalar value
            bindings.append(AuthoringPrefillClaimBinding(
                target_path=tp,
                value_pointer=f"/{tp}",
                catalog_entry_id=entry.catalog_entry_id,
                source_id=entry.source_id,
                locator=entry.locator,
                quote_sha256=entry.quote_sha256,
                support_kind=support_kind,
            ))

    candidate = AuthoringPrefillCandidate(
        candidate_id=candidate_id,
        field_path=field_path,
        structured_value=structured_value,
        preview=json.dumps(structured_value, ensure_ascii=False)[:5000],
        target_paths=sorted(target_paths),
        candidate_scope=candidate_scope,
        recommendation_role=recommendation_role,
        state=state,
        confidence="medium",
        adoption_mode=adoption_mode,  # type: ignore[arg-type]
        evidence_catalog_id=catalog.catalog_id,
        evidence_catalog_sha256=catalog.catalog_sha256,
        claim_bindings=bindings,
        evidence_status=evidence_status,  # type: ignore[arg-type]
        evidence_gaps=list(evidence_gaps or []),
    )
    return candidate, catalog


def _inject_candidate_with_catalog(
    service,
    project_id,
    candidate,
    catalog,
    field_path="design.composite_001",
    status="ready",
):
    """Inject a candidate and its evidence catalog into the persisted package."""
    with service._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = service._current_row(conn, project_id)
        journey = MedicalWritingAuthoringJourney.model_validate_json(row["payload_json"])
        package = journey.prefill_package
        group = AuthoringPrefillFieldCandidates(
            field_path=field_path,
            recommended_candidate_id=candidate.candidate_id,
            candidates=[candidate],
        )
        if package is None:
            package = AuthoringPrefillPackage(
                package_id="pkg_test_001",
                project_id=project_id,
                package_revision=1,
                journey_revision=journey.revision,
                status=status,
                field_candidates={field_path: group},
                evidence_catalog=catalog,
                generated_at=NOW,
                updated_at=NOW,
            )
        else:
            new_fc = dict(package.field_candidates)
            new_fc[field_path] = group
            package = package.model_copy(
                update={
                    "field_candidates": new_fc,
                    "status": status,
                    "evidence_catalog": catalog,
                },
                deep=True,
            )
        updated = journey.model_copy(
            update={"prefill_package": package},
            deep=True,
        )
        conn.execute(
            "UPDATE medical_writing_authoring_journeys SET payload_json = ? WHERE project_id = ?",
            (updated.model_dump_json(), project_id),
        )
        conn.commit()


class CompositeAdoptServiceTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        journey = self.service.get("proj_test")
        gen = AuthoringPrefillGenerateRequest(
            expected_revision=journey.revision,
            actor="medical_manager_test",
            idempotency_key="prefill-gen-001",
        )
        self.service.generate_prefill("proj_test", gen)
        self.verifier = ServerEvidenceVerifier()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _adopt(self, **kwargs):
        project_id = kwargs.pop("project_id", "proj_test")
        journey = self.service.get(project_id)
        package = journey.prefill_package
        field_path = kwargs.pop("field_path", "design.composite_001")
        candidate_id = kwargs.pop("candidate_id", "comp_cand_001")
        path_overrides = kwargs.pop("path_overrides", {})
        skipped_paths = kwargs.pop("skipped_paths", [])
        idempotency_key = kwargs.pop("idempotency_key", "comp-adopt-001")
        actor = kwargs.pop("actor", "medical_manager_test")
        verifier = kwargs.pop("verifier", self.verifier)

        request = AuthoringPrefillCompositeAdoptRequest(
            expected_revision=journey.revision,
            expected_package_revision=package.package_revision,
            package_field_path=field_path,
            candidate_id=candidate_id,
            path_overrides=path_overrides,
            skipped_paths=skipped_paths,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        return self.service.adopt_prefill_composite(
            project_id, request, evidence_verifier=verifier
        )

    # ----------------------------------------------------------------
    # Pending decision tests
    # ----------------------------------------------------------------

    def test_pending_no_override_422_zero_writes(self):
        candidate, catalog = _make_bound_candidate(recommendation_role="pending_decision")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        rev_before = self.service.get("proj_test").revision
        with self.assertRaises(ValueError):
            self._adopt()
        self.assertEqual(rev_before, self.service.get("proj_test").revision)

    def test_pending_partial_override_only_overridden_paths(self):
        candidate, catalog = _make_bound_candidate(recommendation_role="pending_decision")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        result = self._adopt(
            path_overrides={"design.randomization": {"mode": "非随机"}},
            skipped_paths=["design.blinding"],
            idempotency_key="comp-partial-001",
        )
        receipt = result.receipt
        self.assertIn("design.randomization", receipt.overridden_paths)
        self.assertEqual([], receipt.applied_paths)
        self.assertEqual(1, len(receipt.skipped_paths))
        self.assertEqual("user_explicit_skip", receipt.skipped_paths[0].reason)

    def test_pending_partial_override_without_explicit_skip_422_zero_writes(self):
        candidate, catalog = _make_bound_candidate(recommendation_role="pending_decision")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        rev_before = self.service.get("proj_test").revision
        with self.assertRaisesRegex(ValueError, "override or explicit skip"):
            self._adopt(
                path_overrides={"design.randomization": {"mode": "非随机"}},
                idempotency_key="comp-partial-implicit-001",
            )
        self.assertEqual(rev_before, self.service.get("proj_test").revision)

    def test_pending_all_explicitly_skipped_is_audited_without_fact_changes(self):
        candidate, catalog = _make_bound_candidate(recommendation_role="pending_decision")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        before = self.service.get("proj_test")
        before_definition = before.study_definition.model_dump(mode="json")

        result = self._adopt(
            skipped_paths=["design.blinding", "design.randomization"],
            idempotency_key="comp-all-skipped-001",
        )

        receipt = result.receipt
        self.assertEqual([], receipt.applied_paths)
        self.assertEqual([], receipt.overridden_paths)
        self.assertEqual(
            [
                ("design.blinding", "user_explicit_skip"),
                ("design.randomization", "user_explicit_skip"),
            ],
            [(item.path, item.reason) for item in receipt.skipped_paths],
        )
        after = self.service.get("proj_test")
        self.assertEqual(before.framing, after.framing)
        self.assertEqual(before.picos, after.picos)
        self.assertEqual(before_definition, after.study_definition.model_dump(mode="json"))
        self.assertEqual(before.framing_complete, after.framing_complete)
        self.assertEqual(before.picos_complete, after.picos_complete)
        self.assertEqual(before.current_stage, after.current_stage)
        self.assertEqual(before.status, after.status)
        self.assertEqual(
            before.prefill_package.package_revision + 1,
            after.prefill_package.package_revision,
        )

        with self.service._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("proj_test", "comp-all-skipped-001"),
            ).fetchone()
        detail = json.loads(row["payload_json"])
        self.assertEqual(
            {
                "design.blinding": "user_explicit_skip",
                "design.randomization": "user_explicit_skip",
            },
            detail["path_origins"],
        )

    def test_pending_all_overrides_creates_user_edited(self):
        candidate, catalog = _make_bound_candidate(recommendation_role="pending_decision")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        result = self._adopt(
            path_overrides={
                "design.randomization": {"mode": "随机"},
                "design.blinding": {"mode": "开放标签"},
            },
            idempotency_key="comp-all-ov-001",
        )
        receipt = result.receipt
        self.assertEqual(2, len(receipt.overridden_paths))
        self.assertEqual(0, len(receipt.skipped_paths))

    # ----------------------------------------------------------------
    # Corrective P2: per-path semantic gate for manual_only /
    # insufficient / unsupported-substantive-gap candidates.
    # The composite path is the audited override channel: a restricted
    # candidate may only contribute a path through an explicit override
    # or explicit skip; zero-override use rejects before any mutation.
    # ----------------------------------------------------------------

    def test_manual_only_no_override_policy_rejected_zero_writes(self):
        """Zero-override composite adoption of a manual_only candidate is a
        structured policy rejection with no mutation and no event."""
        candidate, catalog = _make_bound_candidate(adoption_mode="manual_only")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        rev_before = self.service.get("proj_test").revision
        with self.assertRaises(MedicalWritingAuthoringPolicyError) as ctx:
            self._adopt(idempotency_key="comp-manual-zero-001")
        exc = ctx.exception
        self.assertEqual("POLICY_REJECTED", exc.code)
        self.assertEqual("candidate_manual_only", exc.reason)
        self.assertIn("manual_only", str(exc))
        self.assertIn("override or explicit skip", str(exc))
        self.assertEqual(rev_before, self.service.get("proj_test").revision)
        with self.service._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("proj_test", "comp-manual-zero-001"),
            ).fetchone()
        self.assertIsNone(row, "policy rejection must not persist an event")

    def test_insufficient_no_override_policy_rejected_zero_writes(self):
        """evidence_status=insufficient blocks zero-override adoption even
        for a batch_allowed candidate."""
        candidate, catalog = _make_bound_candidate(evidence_status="insufficient")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        rev_before = self.service.get("proj_test").revision
        with self.assertRaises(MedicalWritingAuthoringPolicyError) as ctx:
            self._adopt(idempotency_key="comp-insuf-zero-001")
        exc = ctx.exception
        self.assertEqual("POLICY_REJECTED", exc.code)
        self.assertEqual("candidate_insufficient_evidence", exc.reason)
        self.assertIn("evidence_status=insufficient", str(exc))
        self.assertEqual(rev_before, self.service.get("proj_test").revision)

    def test_unsupported_gap_no_override_policy_rejected_zero_writes(self):
        """A candidate carrying an unsupported-substantive evidence gap is
        policy-restricted regardless of adoption_mode / evidence_status."""
        from services.api.app.medical_writing_authoring_prefill_ai import (
            _UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX,
        )

        candidate, catalog = _make_bound_candidate(
            evidence_gaps=[f"{_UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX}盲法设计"],
        )
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        rev_before = self.service.get("proj_test").revision
        with self.assertRaises(MedicalWritingAuthoringPolicyError) as ctx:
            self._adopt(idempotency_key="comp-gap-zero-001")
        exc = ctx.exception
        self.assertEqual("POLICY_REJECTED", exc.code)
        self.assertEqual("candidate_unsupported_evidence_gap", exc.reason)
        self.assertEqual(rev_before, self.service.get("proj_test").revision)

    def test_batch_allowed_gap_carrier_still_policy_restricted(self):
        """batch_allowed alone is not enough: an unsupported gap still
        requires per-path override/skip."""
        from services.api.app.medical_writing_authoring_prefill_ai import (
            _UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX,
        )

        candidate, catalog = _make_bound_candidate(
            evidence_gaps=[f"{_UNSUPPORTED_SUBSTANTIVE_GAP_PREFIX}背景治疗"],
        )
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        with self.assertRaises(MedicalWritingAuthoringPolicyError) as ctx:
            self._adopt(idempotency_key="comp-gap-batch-001")
        self.assertEqual("candidate_unsupported_evidence_gap", ctx.exception.reason)

    def test_manual_only_partial_override_without_skip_policy_rejected(self):
        """A manual_only candidate with one overridden path still needs the
        remaining path explicitly skipped."""
        candidate, catalog = _make_bound_candidate(adoption_mode="manual_only")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        rev_before = self.service.get("proj_test").revision
        with self.assertRaises(MedicalWritingAuthoringPolicyError) as ctx:
            self._adopt(
                path_overrides={"design.randomization": {"mode": "非随机"}},
                idempotency_key="comp-manual-partial-001",
            )
        self.assertEqual("candidate_manual_only", ctx.exception.reason)
        self.assertEqual(rev_before, self.service.get("proj_test").revision)

    def test_manual_only_full_override_succeeds_with_audit(self):
        """Full audited overrides remain allowed for manual_only candidates."""
        candidate, catalog = _make_bound_candidate(adoption_mode="manual_only")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        result = self._adopt(
            path_overrides={
                "design.randomization": {"mode": "随机"},
                "design.blinding": {"mode": "双盲"},
            },
            idempotency_key="comp-manual-full-ov-001",
        )
        receipt = result.receipt
        self.assertEqual(2, len(receipt.overridden_paths))
        self.assertEqual([], receipt.applied_paths)
        self.assertEqual([], receipt.skipped_paths)
        with self.service._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("proj_test", "comp-manual-full-ov-001"),
            ).fetchone()
        detail = json.loads(row["payload_json"])
        origins = detail["path_origins"]
        self.assertEqual("user_override", origins.get("design.blinding"))
        self.assertEqual("user_override", origins.get("design.randomization"))

    def test_manual_only_full_skip_succeeds_with_audit(self):
        """A manual_only candidate may be fully and explicitly skipped with
        an audited skip-only receipt and no fact changes."""
        candidate, catalog = _make_bound_candidate(adoption_mode="manual_only")
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        before = self.service.get("proj_test")
        result = self._adopt(
            skipped_paths=["design.randomization", "design.blinding"],
            idempotency_key="comp-manual-full-skip-001",
        )
        receipt = result.receipt
        self.assertEqual([], receipt.applied_paths)
        self.assertEqual([], receipt.overridden_paths)
        self.assertEqual(
            ["design.blinding", "design.randomization"],
            [item.path for item in receipt.skipped_paths],
        )
        after = self.service.get("proj_test")
        self.assertEqual(before.framing, after.framing)
        self.assertEqual(before.picos, after.picos)

    def test_batch_allowed_supported_clean_candidate_no_override_succeeds(self):
        """Safe batch_allowed candidate: supported and gap-free, the
        zero-override verified adoption path is preserved."""
        candidate, catalog = _make_bound_candidate()  # batch_allowed + supported
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        result = self._adopt(idempotency_key="comp-clean-001")
        receipt = result.receipt
        self.assertEqual(2, len(receipt.applied_paths))
        self.assertEqual(0, len(receipt.overridden_paths))
        self.assertEqual(0, len(receipt.skipped_paths))

    # ----------------------------------------------------------------
    # Recommended candidate with evidence verification
    # ----------------------------------------------------------------

    def test_recommended_no_override_all_paths_verified_and_applied(self):
        candidate, catalog = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        result = self._adopt(idempotency_key="comp-rec-001")
        receipt = result.receipt
        self.assertEqual(2, len(receipt.applied_paths))
        self.assertEqual(0, len(receipt.skipped_paths))
        # Verify candidate is user_confirmed.
        journey = self.service.get("proj_test")
        group = journey.prefill_package.field_candidates["design.composite_001"]
        c = next(c for c in group.candidates if c.candidate_id == "comp_cand_001")
        self.assertEqual("user_confirmed", c.state)

    def test_recommended_with_partial_override_mixed_origins(self):
        candidate, catalog = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        result = self._adopt(
            path_overrides={"design.blinding": {"mode": "开放标签"}},
            idempotency_key="comp-mixed-001",
        )
        receipt = result.receipt
        self.assertIn("design.blinding", receipt.overridden_paths)
        self.assertIn("design.randomization", receipt.applied_paths)

    def test_empty_candidate_value_skipped(self):
        candidate, catalog = _make_bound_candidate(
            target_paths=["design.randomization", "design.blinding"],
            structured_value={
                "design.randomization": {"mode": "随机"},
                "design.blinding": "",
            },
        )
        _inject_candidate_with_catalog(self.service, "proj_test", candidate, catalog)
        result = self._adopt(idempotency_key="comp-empty-001")
        self.assertEqual(1, len(result.receipt.skipped_paths))

    # ----------------------------------------------------------------
    # Package status allowlist
    # ----------------------------------------------------------------

    def test_package_status_allowlist_rejects_non_ready_partial(self):
        for bad_status in ("queued", "running", "failed", "stale"):
            with self.subTest(status=bad_status):
                service = MedicalWritingAuthoringJourneyService(
                    Path(tempfile.mkdtemp()) / "test.sqlite3"
                )
                service.create(f"proj_{bad_status}", _create_request(idempotency_key=f"c-{bad_status}"))
                j = service.get(f"proj_{bad_status}")
                service.generate_prefill(f"proj_{bad_status}", AuthoringPrefillGenerateRequest(
                    expected_revision=j.revision, actor="m", idempotency_key=f"g-{bad_status}",
                ))
                cand, cat = _make_bound_candidate()
                _inject_candidate_with_catalog(service, f"proj_{bad_status}", cand, cat, status=bad_status)
                with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
                    service.adopt_prefill_composite(
                        f"proj_{bad_status}",
                        AuthoringPrefillCompositeAdoptRequest(
                            expected_revision=service.get(f"proj_{bad_status}").revision,
                            expected_package_revision=service.get(f"proj_{bad_status}").prefill_package.package_revision,
                            package_field_path="design.composite_001",
                            candidate_id="comp_cand_001",
                            path_overrides={},
                            actor="m",
                            idempotency_key=f"a-{bad_status}",
                        ),
                        evidence_verifier=ServerEvidenceVerifier(),
                    )

    # ----------------------------------------------------------------
    # Revision CAS + idempotency
    # ----------------------------------------------------------------

    def test_stale_journey_revision_409_zero_writes(self):
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        j = self.service.get("proj_test")
        req = AuthoringPrefillCompositeAdoptRequest(
            expected_revision=j.revision + 999,
            expected_package_revision=j.prefill_package.package_revision,
            package_field_path="design.composite_001",
            candidate_id="comp_cand_001",
            path_overrides={},
            actor="m",
            idempotency_key="comp-stale-jr",
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
            self.service.adopt_prefill_composite("proj_test", req, evidence_verifier=self.verifier)
        self.assertEqual(j.revision, self.service.get("proj_test").revision)

    def test_stale_package_revision_409_zero_writes(self):
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        j = self.service.get("proj_test")
        req = AuthoringPrefillCompositeAdoptRequest(
            expected_revision=j.revision,
            expected_package_revision=j.prefill_package.package_revision + 999,
            package_field_path="design.composite_001",
            candidate_id="comp_cand_001",
            path_overrides={},
            actor="m",
            idempotency_key="comp-stale-pr",
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
            self.service.adopt_prefill_composite("proj_test", req, evidence_verifier=self.verifier)

    def test_idempotent_replay_returns_original_receipt(self):
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        result1 = self._adopt(idempotency_key="comp-replay-001")
        rev1 = self.service.get("proj_test").revision

        req2 = AuthoringPrefillCompositeAdoptRequest(
            expected_revision=result1.receipt.journey_revision_before,
            expected_package_revision=result1.receipt.package_revision_before,
            package_field_path="design.composite_001",
            candidate_id="comp_cand_001",
            path_overrides={},
            actor="medical_manager_test",
            idempotency_key="comp-replay-001",
        )
        result2 = self.service.adopt_prefill_composite("proj_test", req2, evidence_verifier=self.verifier)
        self.assertTrue(result2.receipt.replayed)
        self.assertEqual(result1.receipt.operation_id, result2.receipt.operation_id)
        self.assertEqual(rev1, self.service.get("proj_test").revision)

    def test_all_skipped_idempotent_replay_and_payload_conflict(self):
        cand, cat = _make_bound_candidate(recommendation_role="pending_decision")
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        before = self.service.get("proj_test")
        skipped = ["design.randomization", "design.blinding"]
        result1 = self._adopt(
            skipped_paths=skipped,
            idempotency_key="comp-skip-replay-001",
        )
        revision_after_first = self.service.get("proj_test").revision

        replay_request = AuthoringPrefillCompositeAdoptRequest(
            expected_revision=before.revision,
            expected_package_revision=before.prefill_package.package_revision,
            package_field_path="design.composite_001",
            candidate_id="comp_cand_001",
            path_overrides={},
            skipped_paths=list(reversed(skipped)),
            actor="medical_manager_test",
            idempotency_key="comp-skip-replay-001",
        )
        replay = self.service.adopt_prefill_composite(
            "proj_test", replay_request, evidence_verifier=self.verifier
        )
        self.assertTrue(replay.receipt.replayed)
        self.assertEqual(result1.receipt.operation_id, replay.receipt.operation_id)
        self.assertEqual(revision_after_first, self.service.get("proj_test").revision)

        conflicting_request = replay_request.model_copy(
            update={"skipped_paths": ["design.randomization"]},
            deep=True,
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
            self.service.adopt_prefill_composite(
                "proj_test", conflicting_request, evidence_verifier=self.verifier
            )

    def test_same_key_different_payload_conflict(self):
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        self._adopt(
            path_overrides={"design.randomization": {"mode": "随机"}},
            idempotency_key="comp-conflict-001",
        )
        j = self.service.get("proj_test")
        req2 = AuthoringPrefillCompositeAdoptRequest(
            expected_revision=j.revision,
            expected_package_revision=j.prefill_package.package_revision,
            package_field_path="design.composite_001",
            candidate_id="comp_cand_001",
            path_overrides={"design.randomization": {"mode": "非随机"}},
            actor="medical_manager_test",
            idempotency_key="comp-conflict-001",
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
            self.service.adopt_prefill_composite("proj_test", req2, evidence_verifier=self.verifier)

    # ----------------------------------------------------------------
    # Bounds and scope
    # ----------------------------------------------------------------

    def test_override_extra_path_rejected(self):
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        with self.assertRaises(ValueError):
            self._adopt(path_overrides={"framing.protocol_id": "WRONG"})

    def test_skip_extra_path_rejected(self):
        cand, cat = _make_bound_candidate(recommendation_role="pending_decision")
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        with self.assertRaisesRegex(ValueError, "not in candidate target_paths"):
            self._adopt(skipped_paths=["framing.protocol_id"])

    def test_field_scope_rejected(self):
        cand, cat = _make_bound_candidate(candidate_scope="field")
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        with self.assertRaises(ValueError):
            self._adopt()

    def test_candidate_not_found_404(self):
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        with self.assertRaises(KeyError):
            self._adopt(candidate_id="nonexistent")

    def test_already_confirmed_candidate_conflict(self):
        cand, cat = _make_bound_candidate(state="user_confirmed")
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError):
            self._adopt()

    # ----------------------------------------------------------------
    # Single revision increment
    # ----------------------------------------------------------------

    def test_single_success_one_revision_each(self):
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        j_before = self.service.get("proj_test")
        pkg_before = j_before.prefill_package
        sd_before = j_before.study_definition
        self._adopt(idempotency_key="comp-single-rev")
        j_after = self.service.get("proj_test")
        self.assertEqual(j_before.revision + 1, j_after.revision)
        self.assertEqual(pkg_before.package_revision + 1, j_after.prefill_package.package_revision)
        if sd_before:
            # StudyDefinition.model_validator may apply nested field-state migration
            # and bump revision once more when new structured_design leaves appear.
            self.assertGreaterEqual(
                j_after.study_definition.revision,
                sd_before.revision + 1,
            )
            self.assertLessEqual(
                j_after.study_definition.revision,
                sd_before.revision + 2,
            )

    # ----------------------------------------------------------------
    # Partial adoption does NOT supersede existing user_confirmed
    # ----------------------------------------------------------------

    def test_partial_adoption_preserves_existing_confirmed(self):
        """Partial adoption must not supersede other user_confirmed candidates."""
        # Create a candidate group with an existing confirmed candidate.
        confirmed_cand, catalog = _make_bound_candidate(
            candidate_id="confirmed_001",
            state="user_confirmed",
        )
        pending_cand, _ = _make_bound_candidate(
            candidate_id="pending_001",
            recommendation_role="pending_decision",
        )
        group = AuthoringPrefillFieldCandidates(
            field_path="design.composite_001",
            recommended_candidate_id="pending_001",
            candidates=[confirmed_cand, pending_cand],
        )
        with self.service._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.service._current_row(conn, "proj_test")
            journey = MedicalWritingAuthoringJourney.model_validate_json(row["payload_json"])
            pkg = journey.prefill_package
            new_fc = dict(pkg.field_candidates)
            new_fc["design.composite_001"] = group
            pkg = pkg.model_copy(
                update={"field_candidates": new_fc, "evidence_catalog": catalog},
                deep=True,
            )
            updated = journey.model_copy(update={"prefill_package": pkg}, deep=True)
            conn.execute(
                "UPDATE medical_writing_authoring_journeys SET payload_json = ? WHERE project_id = ?",
                (updated.model_dump_json(), "proj_test"),
            )
            conn.commit()

        # Adopt pending with partial override.
        result = self._adopt(
            candidate_id="pending_001",
            path_overrides={"design.randomization": {"mode": "随机"}},
            skipped_paths=["design.blinding"],
            idempotency_key="comp-preserve-001",
        )

        # Check that confirmed_001 is still user_confirmed (not superseded).
        j = self.service.get("proj_test")
        grp = j.prefill_package.field_candidates["design.composite_001"]
        confirmed = next(c for c in grp.candidates if c.candidate_id == "confirmed_001")
        self.assertEqual("user_confirmed", confirmed.state)

    # ----------------------------------------------------------------
    # Evidence verification fail-closed
    # ----------------------------------------------------------------

    def test_no_verifier_rejects_ai_candidate_paths(self):
        """Without a verifier, AI-origin candidate paths fail closed."""
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        with self.assertRaises(ValueError) as ctx:
            self._adopt(verifier=None)
        self.assertIn("no evidence verifier", str(ctx.exception).lower())

    def test_catalog_hash_mismatch_rejected(self):
        """Tampered catalog SHA is rejected by verifier."""
        cand, cat = _make_bound_candidate()
        # Tamper with catalog hash.
        tampered_cat = cat.model_copy(
            update={"catalog_sha256": "0" * 64},
            deep=True,
        )
        _inject_candidate_with_catalog(self.service, "proj_test", cand, tampered_cat)
        with self.assertRaises(ValueError):
            self._adopt(idempotency_key="comp-tampered-sha")

    def test_binding_source_id_mismatch_rejected(self):
        """Binding with wrong source_id is rejected."""
        cand, cat = _make_bound_candidate()
        # Tamper with one binding's source_id.
        tampered_bindings = list(cand.claim_bindings)
        tampered_bindings[0] = tampered_bindings[0].model_copy(
            update={"source_id": "WRONG_SOURCE"},
        )
        tampered_cand = cand.model_copy(update={"claim_bindings": tampered_bindings})
        _inject_candidate_with_catalog(self.service, "proj_test", tampered_cand, cat)
        with self.assertRaises(ValueError):
            self._adopt(idempotency_key="comp-binding-drift")

    def test_binding_quote_hash_mismatch_rejected(self):
        """Binding with wrong quote_sha256 is rejected."""
        cand, cat = _make_bound_candidate()
        tampered_bindings = list(cand.claim_bindings)
        tampered_bindings[0] = tampered_bindings[0].model_copy(
            update={"quote_sha256": "b" * 64},
        )
        tampered_cand = cand.model_copy(update={"claim_bindings": tampered_bindings})
        _inject_candidate_with_catalog(self.service, "proj_test", tampered_cand, cat)
        with self.assertRaises(ValueError):
            self._adopt(idempotency_key="comp-quote-drift")

    def test_competitor_option_cannot_write_framing_indication(self):
        """competitor_option binding on framing.indication is rejected."""
        target = "framing.indication"
        entry = _make_catalog_entry(
            catalog_entry_id="entry_comp_ind",
            source_id="ctgov_NCT001",
            locator="NCT001.condition",
            quote="Rheumatoid Arthritis",
            target_paths=(target,),
            support_scope="competitor_observation",
            source_kind="ctgov_snapshot",
        )
        catalog = _make_catalog(entries=[entry])
        binding = AuthoringPrefillClaimBinding(
            target_path=target,
            value_pointer="",
            catalog_entry_id="entry_comp_ind",
            source_id="ctgov_NCT001",
            locator="NCT001.condition",
            quote_sha256=entry.quote_sha256,
            support_kind="competitor_option",
        )
        candidate = AuthoringPrefillCandidate(
            candidate_id="comp_ind_001",
            field_path="module_comp_ind",
            structured_value={target: "Rheumatoid Arthritis"},
            preview="Rheumatoid Arthritis",
            target_paths=[target],
            candidate_scope="module",
            adoption_mode="batch_allowed",
            evidence_catalog_id=catalog.catalog_id,
            evidence_catalog_sha256=catalog.catalog_sha256,
            claim_bindings=[binding],
            evidence_status="supported",
        )
        _inject_candidate_with_catalog(
            self.service, "proj_test", candidate, catalog, field_path="module_comp_ind"
        )
        with self.assertRaises(ValueError):
            self._adopt(
                field_path="module_comp_ind",
                candidate_id="comp_ind_001",
                idempotency_key="comp-comp-ind-001",
            )

    def test_old_package_without_catalog_ai_paths_fail_closed(self):
        """Package without evidence_catalog: AI candidate paths fail closed,
        but pure user overrides still work."""
        cand, cat = _make_bound_candidate()
        # Inject WITHOUT catalog.
        with self.service._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.service._current_row(conn, "proj_test")
            journey = MedicalWritingAuthoringJourney.model_validate_json(row["payload_json"])
            pkg = journey.prefill_package
            group = AuthoringPrefillFieldCandidates(
                field_path="design.composite_001",
                recommended_candidate_id=cand.candidate_id,
                candidates=[cand],
            )
            new_fc = dict(pkg.field_candidates)
            new_fc["design.composite_001"] = group
            # Deliberately do NOT set evidence_catalog.
            pkg = pkg.model_copy(update={"field_candidates": new_fc}, deep=True)
            updated = journey.model_copy(update={"prefill_package": pkg}, deep=True)
            conn.execute(
                "UPDATE medical_writing_authoring_journeys SET payload_json = ? WHERE project_id = ?",
                (updated.model_dump_json(), "proj_test"),
            )
            conn.commit()

        # AI candidate path should fail.
        with self.assertRaises(ValueError):
            self._adopt(idempotency_key="comp-no-catalog")

        # Pure user override should succeed (pending + all overrides).
        cand2, _ = _make_bound_candidate(
            recommendation_role="pending_decision",
        )
        with self.service._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self.service._current_row(conn, "proj_test")
            journey = MedicalWritingAuthoringJourney.model_validate_json(row["payload_json"])
            pkg = journey.prefill_package
            group = AuthoringPrefillFieldCandidates(
                field_path="design.composite_001",
                recommended_candidate_id=cand2.candidate_id,
                candidates=[cand2],
            )
            new_fc = dict(pkg.field_candidates)
            new_fc["design.composite_001"] = group
            pkg = pkg.model_copy(update={"field_candidates": new_fc}, deep=True)
            updated = journey.model_copy(update={"prefill_package": pkg}, deep=True)
            conn.execute(
                "UPDATE medical_writing_authoring_journeys SET payload_json = ? WHERE project_id = ?",
                (updated.model_dump_json(), "proj_test"),
            )
            conn.commit()

        result = self._adopt(
            candidate_id=cand2.candidate_id,
            path_overrides={
                "design.randomization": {"mode": "随机"},
                "design.blinding": {"mode": "双盲"},
            },
            idempotency_key="comp-no-catalog-override",
        )
        self.assertEqual(2, len(result.receipt.overridden_paths))

    # ----------------------------------------------------------------
    # Path origins in event
    # ----------------------------------------------------------------

    def test_event_records_path_origins(self):
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        self._adopt(
            path_overrides={"design.blinding": {"mode": "开放标签"}},
            idempotency_key="comp-origins-001",
        )
        # Load the event and check path_origins.
        with self.service._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("proj_test", "comp-origins-001"),
            ).fetchone()
        detail = json.loads(row["payload_json"])
        self.assertIn("path_origins", detail)
        origins = detail["path_origins"]
        self.assertEqual("user_override", origins.get("design.blinding"))
        self.assertEqual("ai_candidate_evidence_bound", origins.get("design.randomization"))
        # Derived paths should be marked.
        for path in detail.get("derived_paths", []):
            self.assertEqual("derived", origins.get(path))

    # ----------------------------------------------------------------
    # Leaf-level derived conflict detection (patched mapper)
    # ----------------------------------------------------------------

    def test_leaf_level_derived_conflict_rejected(self):
        """Two root paths producing conflicting values for the same derived
        leaf path must cause a full rejection."""
        from services.api.app import medical_writing_authoring_prefill as prefill_mod

        original_mapper = prefill_mod.map_design_adoption_to_study_updates

        def conflicting_mapper(field_path, value, *, framing_payload, picos_payload):
            """Patched mapper: both design.randomization and design.blinding
            try to set framing.structured_design.conflict_key to different values."""
            if field_path in ("design.randomization", "design.blinding"):
                conflict_val = "A" if field_path == "design.randomization" else "B"
                sd = dict(framing_payload.get("structured_design") or {})
                sd["conflict_key"] = conflict_val
                return ({"structured_design": sd}, [], ["framing.structured_design"])
            return original_mapper(
                field_path, value,
                framing_payload=framing_payload, picos_payload=picos_payload,
            )

        with patch.object(prefill_mod, "map_design_adoption_to_study_updates", conflicting_mapper):
            cand, cat = _make_bound_candidate()
            _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
            with self.assertRaises(ValueError) as ctx:
                self._adopt(idempotency_key="comp-conflict-leaf")
            self.assertIn("conflict", str(ctx.exception).lower())

    def test_legitimate_dict_merge_not_conflict(self):
        """Two root paths adding different keys to structured_design is OK."""
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        # Normal mapper — design.randomization sets randomization_mode,
        # design.blinding sets blinding_mode. Different keys, no conflict.
        result = self._adopt(idempotency_key="comp-legit-merge")
        self.assertEqual(2, len(result.receipt.applied_paths))

    # ----------------------------------------------------------------
    # Idempotent replay fail-closed when receipt missing
    # ----------------------------------------------------------------

    def test_replay_missing_receipt_fails_closed(self):
        """If the event has no receipt payload, replay must fail closed."""
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        result1 = self._adopt(idempotency_key="comp-missing-receipt")

        # Corrupt the event payload by removing the receipt.
        with self.service._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload_json FROM medical_writing_authoring_journey_events "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("proj_test", "comp-missing-receipt"),
            ).fetchone()
            detail = json.loads(row["payload_json"])
            del detail["receipt"]
            conn.execute(
                "UPDATE medical_writing_authoring_journey_events SET payload_json = ? "
                "WHERE project_id = ? AND idempotency_key = ?",
                (json.dumps(detail), "proj_test", "comp-missing-receipt"),
            )
            conn.commit()

        # Replay with original expected revisions (from the receipt we captured).
        req = AuthoringPrefillCompositeAdoptRequest(
            expected_revision=result1.receipt.journey_revision_before,
            expected_package_revision=result1.receipt.package_revision_before,
            package_field_path="design.composite_001",
            candidate_id="comp_cand_001",
            path_overrides={},
            actor="medical_manager_test",
            idempotency_key="comp-missing-receipt",
        )
        with self.assertRaises(MedicalWritingAuthoringJourneyConflictError) as ctx:
            self.service.adopt_prefill_composite("proj_test", req, evidence_verifier=self.verifier)
        self.assertIn("refusing to fabricate", str(ctx.exception).lower())

    # ----------------------------------------------------------------
    # Search plan rebuild
    # ----------------------------------------------------------------

    def test_search_plan_rebuilt_when_condition_term_impacted(self):
        target = "framing.clinicaltrials_condition_term"
        cand, cat = _make_bound_candidate(
            target_paths=[target],
            structured_value={target: "Rheumatoid Arthritis"},
            field_path="module_search",
        )
        _inject_candidate_with_catalog(
            self.service, "proj_test", cand, cat, field_path="module_search"
        )
        result = self._adopt(
            field_path="module_search",
            idempotency_key="comp-search-001",
        )
        self.assertIn("competitor_search_plan", result.receipt.invalidated_dependents)

    # ----------------------------------------------------------------
    # Single-field adopt regression
    # ----------------------------------------------------------------

    def test_single_field_adopt_still_works(self):
        """Single-path field adoption still works through the user-edit
        channel.  Round 2: candidate cards are pending/manual_only and fail
        closed; the user's explicit value is the audited adoption input."""
        from packages.contracts.workbench_contracts import (
            AuthoringPrefillAdoptRequest,
        )
        j = self.service.get("proj_test")
        pkg = j.prefill_package
        fp = None
        value = None
        for path, group in pkg.field_candidates.items():
            if group.candidates:
                fp = path
                value = group.candidates[0].structured_value
                break
        if fp is None:
            self.skipTest("no field candidates")
        req = AuthoringPrefillAdoptRequest(
            expected_revision=j.revision,
            expected_package_revision=pkg.package_revision,
            field_path=fp,
            candidate_id="",
            edited_value=value,
            actor="medical_manager_test",
            idempotency_key="single-adopt-regression",
        )
        result = self.service.adopt_prefill_candidate("proj_test", req)
        self.assertIsNotNone(result)

    # ----------------------------------------------------------------
    # Falsy overrides (empty string, empty list)
    # ----------------------------------------------------------------

    def test_falsy_overrides_are_valid_explicit_decisions(self):
        target_paths = [
            "framing.intrinsic_objectives",
            "picos.study_epochs",
        ]
        structured_value = {
            "framing.intrinsic_objectives": ["obj_a"],
            "picos.study_epochs": ["筛选期"],
        }
        entries = [
            _make_catalog_entry(
                catalog_entry_id=f"entry_{tp}",
                source_id=tp,
                locator=tp,
                quote=json.dumps(structured_value[tp], ensure_ascii=False),
                target_paths=(tp,),
            )
            for tp in target_paths
        ]
        catalog = _make_catalog(entries=entries)
        bindings = []
        for tp in target_paths:
            entry = next(e for e in catalog.entries if e.source_id == tp)
            bindings.append(AuthoringPrefillClaimBinding(
                target_path=tp,
                value_pointer="",
                catalog_entry_id=entry.catalog_entry_id,
                source_id=entry.source_id,
                locator=entry.locator,
                quote_sha256=entry.quote_sha256,
                support_kind="exact_fact",
            ))
        candidate = AuthoringPrefillCandidate(
            candidate_id="comp_falsy_001",
            field_path="module_falsy",
            structured_value=structured_value,
            preview=json.dumps(structured_value, ensure_ascii=False)[:5000],
            target_paths=sorted(target_paths),
            candidate_scope="module",
            evidence_catalog_id=catalog.catalog_id,
            evidence_catalog_sha256=catalog.catalog_sha256,
            claim_bindings=bindings,
            evidence_status="supported",
        )
        _inject_candidate_with_catalog(
            self.service, "proj_test", candidate, catalog, field_path="module_falsy"
        )
        result = self._adopt(
            field_path="module_falsy",
            candidate_id="comp_falsy_001",
            path_overrides={
                "framing.intrinsic_objectives": [],
                "picos.study_epochs": [],
            },
            idempotency_key="comp-falsy-001",
        )
        self.assertEqual(2, len(result.receipt.overridden_paths))

    # ----------------------------------------------------------------
    # R03: W2b binding validation integration tests
    # ----------------------------------------------------------------

    def test_empty_value_pointer_package_candidate_rejected(self):
        """A package-scope candidate with value_pointer='' must be rejected."""
        cand, cat = _make_bound_candidate()
        # Tamper: set all bindings to empty value_pointer.
        tampered_bindings = [
            b.model_copy(update={"value_pointer": ""})
            for b in cand.claim_bindings
        ]
        tampered_cand = cand.model_copy(update={"claim_bindings": tampered_bindings})
        _inject_candidate_with_catalog(self.service, "proj_test", tampered_cand, cat)
        with self.assertRaises(ValueError):
            self._adopt(idempotency_key="comp-empty-ptr-001")

    def test_pointer_to_container_rejected(self):
        """value_pointer resolving to a dict container must be rejected."""
        cand, cat = _make_bound_candidate()
        # Tamper: set pointer to the whole target_path dict, not a leaf.
        tampered_bindings = [
            b.model_copy(update={"value_pointer": f"/{b.target_path}"})
            for b in cand.claim_bindings
        ]
        tampered_cand = cand.model_copy(update={"claim_bindings": tampered_bindings})
        _inject_candidate_with_catalog(self.service, "proj_test", tampered_cand, cat)
        with self.assertRaises(ValueError):
            self._adopt(idempotency_key="comp-ptr-container-001")

    def test_pointer_wrong_first_segment_rejected(self):
        """value_pointer whose first segment doesn't match target_path rejected."""
        cand, cat = _make_bound_candidate()
        # Tamper: first segment doesn't match target_path.
        tampered_bindings = []
        for b in cand.claim_bindings:
            tampered_bindings.append(b.model_copy(
                update={"value_pointer": f"/WRONG_TARGET/mode"}
            ))
        tampered_cand = cand.model_copy(update={"claim_bindings": tampered_bindings})
        _inject_candidate_with_catalog(self.service, "proj_test", tampered_cand, cat)
        with self.assertRaises(ValueError):
            self._adopt(idempotency_key="comp-ptr-wrong-seg-001")

    def test_missing_nested_atomic_leaf_binding_rejected(self):
        """Candidate with a multi-leaf structured_value missing one leaf binding."""
        # Structured value with two atomic leaves per target_path.
        sv = {
            "design.randomization": {"mode": "随机", "details": "分层随机"},
            "design.blinding": {"mode": "双盲"},
        }
        entries = []
        for tp in ["design.randomization", "design.blinding"]:
            entries.append(_make_catalog_entry(
                catalog_entry_id=f"entry_{tp}",
                source_id=tp,
                locator=tp,
                quote=json.dumps(sv[tp], ensure_ascii=False),
                target_paths=(tp,),
            ))
        catalog = _make_catalog(entries=entries)
        # Only bind /mode, skip /details for design.randomization.
        bindings = [
            AuthoringPrefillClaimBinding(
                target_path="design.randomization",
                value_pointer="/design.randomization/mode",
                catalog_entry_id="entry_design.randomization",
                source_id="design.randomization",
                locator="design.randomization",
                quote_sha256=entries[0].quote_sha256,
                support_kind="exact_fact",
            ),
            AuthoringPrefillClaimBinding(
                target_path="design.blinding",
                value_pointer="/design.blinding/mode",
                catalog_entry_id="entry_design.blinding",
                source_id="design.blinding",
                locator="design.blinding",
                quote_sha256=entries[1].quote_sha256,
                support_kind="exact_fact",
            ),
        ]
        candidate = AuthoringPrefillCandidate(
            candidate_id="comp_missing_leaf_001",
            field_path="design.missing_leaf",
            structured_value=sv,
            preview=json.dumps(sv, ensure_ascii=False)[:5000],
            target_paths=["design.randomization", "design.blinding"],
            candidate_scope="module",
            adoption_mode="batch_allowed",
            evidence_catalog_id=catalog.catalog_id,
            evidence_catalog_sha256=catalog.catalog_sha256,
            claim_bindings=bindings,
            evidence_status="supported",
        )
        _inject_candidate_with_catalog(
            self.service, "proj_test", candidate, catalog, field_path="design.missing_leaf"
        )
        with self.assertRaises(ValueError):
            self._adopt(
                field_path="design.missing_leaf",
                candidate_id="comp_missing_leaf_001",
                idempotency_key="comp-missing-leaf-001",
            )

    def test_ctgov_lead_sponsor_field_rejected(self):
        """CT.gov lead_sponsor field cannot support any PICOS design path."""
        entry = _make_catalog_entry(
            catalog_entry_id="entry_sponsor",
            source_id="ctgov_NCT001",
            locator="NCT001.lead_sponsor",
            quote="Sponsor Name",
            target_paths=("picos.design_archetype",),
            support_scope="competitor_observation",
            source_kind="ctgov_snapshot",
        )
        # Add field_key provenance for lead_sponsor.
        entry = entry.model_copy(
            update={"provenance": {"field_key": "lead_sponsor"}}
        )
        catalog = _make_catalog(entries=[entry])
        binding = AuthoringPrefillClaimBinding(
            target_path="picos.design_archetype",
            value_pointer="/picos.design_archetype",
            catalog_entry_id="entry_sponsor",
            source_id="ctgov_NCT001",
            locator="NCT001.lead_sponsor",
            quote_sha256=entry.quote_sha256,
            support_kind="competitor_option",
        )
        candidate = AuthoringPrefillCandidate(
            candidate_id="comp_sponsor_001",
            field_path="module_sponsor",
            structured_value={"picos.design_archetype": "randomized_exploratory"},
            preview="randomized_exploratory",
            target_paths=["picos.design_archetype"],
            candidate_scope="module",
            adoption_mode="batch_allowed",
            evidence_catalog_id=catalog.catalog_id,
            evidence_catalog_sha256=catalog.catalog_sha256,
            claim_bindings=[binding],
            evidence_status="supported",
        )
        _inject_candidate_with_catalog(
            self.service, "proj_test", candidate, catalog, field_path="module_sponsor"
        )
        with self.assertRaises(ValueError):
            self._adopt(
                field_path="module_sponsor",
                candidate_id="comp_sponsor_001",
                idempotency_key="comp-sponsor-001",
            )

    def test_ctgov_document_field_rejected(self):
        """CT.gov document:* field cannot support any target path."""
        entry = _make_catalog_entry(
            catalog_entry_id="entry_doc",
            source_id="ctgov_NCT001",
            locator="NCT001.document",
            quote="Some document field",
            target_paths=("picos.population_summary",),
            support_scope="competitor_observation",
            source_kind="ctgov_snapshot",
        )
        entry = entry.model_copy(
            update={"provenance": {"field_key": "document:some_field"}}
        )
        catalog = _make_catalog(entries=[entry])
        binding = AuthoringPrefillClaimBinding(
            target_path="picos.population_summary",
            value_pointer="/picos.population_summary",
            catalog_entry_id="entry_doc",
            source_id="ctgov_NCT001",
            locator="NCT001.document",
            quote_sha256=entry.quote_sha256,
            support_kind="competitor_option",
        )
        candidate = AuthoringPrefillCandidate(
            candidate_id="comp_doc_001",
            field_path="module_doc",
            structured_value={"picos.population_summary": "Adult RA patients"},
            preview="Adult RA patients",
            target_paths=["picos.population_summary"],
            candidate_scope="module",
            adoption_mode="batch_allowed",
            evidence_catalog_id=catalog.catalog_id,
            evidence_catalog_sha256=catalog.catalog_sha256,
            claim_bindings=[binding],
            evidence_status="supported",
        )
        _inject_candidate_with_catalog(
            self.service, "proj_test", candidate, catalog, field_path="module_doc"
        )
        with self.assertRaises(ValueError):
            self._adopt(
                field_path="module_doc",
                candidate_id="comp_doc_001",
                idempotency_key="comp-doc-001",
            )

    def test_legitimate_multileaf_candidate_succeeds(self):
        """A candidate with multiple atomic leaves per target path and
        correct per-leaf bindings must succeed."""
        sv = {
            "design.randomization": {"mode": "随机", "details": "分层按中心"},
            "design.blinding": {"mode": "双盲", "details": "受试者和研究者"},
        }
        entries = []
        for tp in ["design.randomization", "design.blinding"]:
            entries.append(_make_catalog_entry(
                catalog_entry_id=f"entry_{tp}",
                source_id=tp,
                locator=tp,
                quote=json.dumps(sv[tp], ensure_ascii=False),
                target_paths=(tp,),
            ))
        catalog = _make_catalog(entries=entries)
        # Build per-leaf bindings.
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            _enumerate_atomic_leaves,
        )
        bindings = []
        entry_by_source = {e.source_id: e for e in catalog.entries}
        for tp in ["design.randomization", "design.blinding"]:
            entry = entry_by_source[tp]
            for leaf_ptr in _enumerate_atomic_leaves(sv[tp], f"/{tp}"):
                bindings.append(AuthoringPrefillClaimBinding(
                    target_path=tp,
                    value_pointer=leaf_ptr,
                    catalog_entry_id=entry.catalog_entry_id,
                    source_id=entry.source_id,
                    locator=entry.locator,
                    quote_sha256=entry.quote_sha256,
                    support_kind="exact_fact",
                ))
        candidate = AuthoringPrefillCandidate(
            candidate_id="comp_multileaf_001",
            field_path="module_multileaf",
            structured_value=sv,
            preview=json.dumps(sv, ensure_ascii=False)[:5000],
            target_paths=["design.randomization", "design.blinding"],
            candidate_scope="module",
            adoption_mode="batch_allowed",
            evidence_catalog_id=catalog.catalog_id,
            evidence_catalog_sha256=catalog.catalog_sha256,
            claim_bindings=bindings,
            evidence_status="supported",
        )
        _inject_candidate_with_catalog(
            self.service, "proj_test", candidate, catalog, field_path="module_multileaf"
        )
        result = self._adopt(
            field_path="module_multileaf",
            candidate_id="comp_multileaf_001",
            idempotency_key="comp-multileaf-001",
        )
        self.assertEqual(2, len(result.receipt.applied_paths))

    def test_user_edited_refs_no_duplicates(self):
        """User-edited composite evidence_refs must have no duplicates."""
        cand, cat = _make_bound_candidate()
        _inject_candidate_with_catalog(self.service, "proj_test", cand, cat)
        # Adopt with one override + one candidate path.
        result = self._adopt(
            path_overrides={"design.blinding": {"mode": "开放标签"}},
            idempotency_key="comp-dedup-refs-001",
        )
        # The user-edited composite should be in the candidate list.
        j = self.service.get("proj_test")
        group = j.prefill_package.field_candidates["design.composite_001"]
        edited = None
        for c in group.candidates:
            if c.candidate_id.startswith("edited_composite_"):
                edited = c
                break
        self.assertIsNotNone(edited, "user-edited composite must exist")
        # Evidence refs should not have duplicates (by source_id + locator).
        ref_keys = [(r.source_id, r.locator) for r in edited.evidence_refs]
        self.assertEqual(
            len(ref_keys), len(set(ref_keys)),
            f"duplicate evidence refs found: {ref_keys}",
        )
        # Should have exactly one manual ref.
        manual_refs = [r for r in edited.evidence_refs if r.source_kind == "manual"]
        self.assertEqual(1, len(manual_refs))


if __name__ == "__main__":
    unittest.main()
