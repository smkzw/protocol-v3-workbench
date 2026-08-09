"""W2b-2 r2 Evidence-binding tests — strict fail-closed semantics.

Every test verifies a concrete production safety contract:

1. Both catalog_id AND catalog_sha256 must be present and match; either missing = reject all.
2. Zero-binding candidate is rejected.
3. One valid + one invalid binding rejects the entire candidate.
4. Unmapped CT.gov field_key (document/date/status/URL) cannot bind any PICOS.
5. intervention[i].name/type for any index can bind intervention/comparator paths.
6. Package target_paths must exactly match server's set — no subset/superset/alternative.
7. value_pointer must resolve to non-empty atomic value under target_path.
8. Partial leaf coverage = partially_supported; full coverage = supported.
9. Condition term candidate has real server binding; no entry = no AI candidate.
10. Production payload has no registered_source_ids or snapshot_hints.
11. Provider still makes one bulk call; identity is deepseek-v4-pro.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.contracts.workbench_contracts import (
    AuthoringPrefillCandidate,
    AuthoringPrefillGenerateRequest,
    AuthoringPrefillPackage,
    MedicalWritingAuthoringJourneyCreateRequest,
    MedicalWritingStudyFraming,
    WritingReferenceSearchRequest,
    WritingReferenceSearchSnapshot,
    WritingReferenceTrialCandidate,
    WritingReferenceTrialIntervention,
)
from services.api.app.medical_writing_authoring_journey import (
    MedicalWritingAuthoringJourneyService,
)
from services.api.app.medical_writing_authoring_prefill import (
    generate_prefill_package,
)
from services.api.app.medical_writing_authoring_prefill_ai import (
    DEEPSEEK_PREFILL_MODEL,
    DeepSeekPrefillAdapter,
    _build_bulk_request,
    _extract_package_target_paths,
    PackageTargetPathError,
    _BULK_SYSTEM_PROMPT,
)
from services.api.app.medical_writing_authoring_prefill_evidence import (
    build_evidence_catalog,
)
from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
    MAX_TOTAL_PAYLOAD_CHARS,
    PACKAGE_KEYS,
    bind_deterministic_project_fact_candidates,
    _parse_rfc6901_pointer,
    _resolve_rfc6901,
    _is_atomic_leaf,
    _enumerate_atomic_leaves,
    _build_pointer,
    project_catalog_for_model,
    validate_and_rebind_candidates,
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
        "idempotency_key": "create-w2b2r2-001",
    }
    for key, value in overrides.items():
        if key in framing_fields:
            framing_fields[key] = value
        else:
            request_fields[key] = value
    request_fields["framing"] = MedicalWritingStudyFraming(**framing_fields)
    return MedicalWritingAuthoringJourneyCreateRequest(**request_fields)


class _CatalogAwareProvider:
    """Provider that auto-echoes catalog identity and returns canned output."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {}
        self.call_count = 0
        self.calls: list[Any] = []

    def run(self, envelope: Any) -> dict[str, Any]:
        self.call_count += 1
        self.calls.append(envelope)
        result = dict(self.response)
        result["_response_model"] = DEEPSEEK_PREFILL_MODEL
        ec = getattr(envelope, "payload", {}).get("evidence_catalog")
        if ec:
            result.setdefault("catalog_id", ec.get("catalog_id", ""))
            result.setdefault("catalog_sha256", ec.get("catalog_sha256", ""))
        return result


class _MissingCatalogIdentityProvider:
    """Returns valid candidate content but omits copied catalog metadata."""

    def run(self, envelope: Any) -> dict[str, Any]:
        return {
            "_response_model": DEEPSEEK_PREFILL_MODEL,
            "clinicaltrials_condition_term_en": (
                "Paroxysmal Nocturnal Hemoglobinuria"
            ),
            "field_suggestions": {},
            "package_suggestions": {},
        }


def _make_snapshot(project_id: str = "proj_test") -> WritingReferenceSearchSnapshot:
    candidate = WritingReferenceTrialCandidate(
        nct_id="NCT04512345",
        brief_title="Phase 2 Study of CMS-D017 in PNH",
        official_title="A Randomized, Double-Blind, Placebo-Controlled Phase 2 Study",
        brief_summary="Study in adult PNH patients with randomized allocation.",
        conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
        phases=["PHASE2"],
        study_type="INTERVENTIONAL",
        interventions=[
            WritingReferenceTrialIntervention(name="CMS-D017", intervention_type="Drug"),
            WritingReferenceTrialIntervention(name="Placebo", intervention_type="Drug"),
        ],
        design_allocation="RANDOMIZED",
        design_intervention_model="PARALLEL",
        design_masking="DOUBLE",
        enrollment_count=100,
        lead_sponsor="Test Sponsor",
        overall_status="RECRUITING",
        study_record_url="https://clinicaltrials.gov/ct2/show/NCT04512345",
        public_documents=[],
    )
    return WritingReferenceSearchSnapshot(
        snapshot_id="snap_001",
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


def _projected_catalog(journey, snapshot=None):
    cat = build_evidence_catalog(journey, snapshot=snapshot)
    pkg = generate_prefill_package(state=journey, now=NOW, actor="test")
    ptp = _extract_package_target_paths(pkg)
    proj = project_catalog_for_model(
        cat,
        deterministic_field_paths=set(pkg.field_candidates.keys()),
        package_target_paths=ptp,
    )
    return cat, proj, pkg


# ---------------------------------------------------------------------------
# Test 1: Catalog identity — both ID and SHA required
# ---------------------------------------------------------------------------

class CatalogIdentityTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.cat, self.proj, self.pkg = _projected_catalog(self.journey)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_catalog_sha_rejects_all(self):
        model_output = {
            "catalog_id": self.cat.catalog_id,
            # catalog_sha256 intentionally missing.
        }
        cond, fields, pkgs, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertIsNone(cond)
        self.assertEqual([], fields)
        self.assertEqual({}, pkgs)
        self.assertTrue(any("catalog_sha256 is missing" in e for e in errors))

    def test_missing_catalog_id_rejects_all(self):
        model_output = {
            # catalog_id intentionally missing.
            "catalog_sha256": self.cat.catalog_sha256,
        }
        cond, fields, pkgs, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertIsNone(cond)
        self.assertTrue(any("catalog_id is missing" in e for e in errors))

    def test_wrong_catalog_sha_rejects_all(self):
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": hashlib.sha256(b"wrong").hexdigest(),
        }
        cond, _, _, _, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertIsNone(cond)
        self.assertTrue(any("catalog_sha256 mismatch" in e for e in errors))

    def test_projection_exposes_exact_target_to_entry_compatibility(self):
        snapshot = _make_snapshot()
        cat, projection, _pkg = _projected_catalog(
            self.journey, snapshot=snapshot
        )
        eligible = projection["eligible_entry_ids_by_target_path"]

        intervention_ids = set(
            eligible.get("picos.intervention_summary", [])
        )
        design_ids = set(eligible.get("design.randomization", []))
        indication_ids = set(
            eligible.get("framing.clinicaltrials_condition_term", [])
        )

        entries = {
            item["catalog_entry_id"]: item
            for item in projection["evidence_entries"]
        }
        self.assertTrue(intervention_ids)
        self.assertTrue(design_ids)
        self.assertTrue(indication_ids)
        self.assertTrue(
            all(
                "picos.intervention_summary"
                in entries[entry_id]["supported_target_paths"]
                for entry_id in intervention_ids
            )
        )
        self.assertTrue(
            all(
                entries[entry_id]["provenance"].get("field_key")
                == "design_allocation"
                for entry_id in design_ids
            )
        )
        self.assertTrue(
            all(
                entries[entry_id]["support_scope"]
                == "current_project_fact"
                for entry_id in indication_ids
            )
        )

    def test_bulk_prompt_forbids_neighbor_evidence_substitution(self):
        self.assertIn(
            "eligible_entry_ids_by_target_path[target_path]",
            _BULK_SYSTEM_PROMPT,
        )
        self.assertIn("package.design", _BULK_SYSTEM_PROMPT)
        self.assertIn("package.product", _BULK_SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# Test 2: Zero-binding candidate rejected
# ---------------------------------------------------------------------------

class ZeroBindingTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.cat, self.proj, self.pkg = _projected_catalog(self.journey)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_zero_binding_candidate_rejected(self):
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "field_suggestions": {
                "framing.population_intent": [
                    {
                        "structured_value": "PNH患者",
                        "preview": "PNH患者",
                        "rationale": "基于适应症。",
                        # NO claim_bindings.
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths={"framing.population_intent"},
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("framing.population_intent", []))
        self.assertTrue(any("zero claim_bindings" in e for e in errors))


# ---------------------------------------------------------------------------
# Test 3: One valid + one invalid binding rejects entire candidate
# ---------------------------------------------------------------------------

class MixedBindingTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.snapshot = _make_snapshot()
        self.cat, self.proj, self.pkg = _projected_catalog(
            self.journey, self.snapshot
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_one_valid_one_unsent_rejects_whole_candidate(self):
        indication_entry = next(
            e for e in self.cat.entries if e.source_id == "framing.indication"
        )
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "field_suggestions": {
                "framing.population_intent": [
                    {
                        "structured_value": "PNH患者",
                        "preview": "PNH患者",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "framing.population_intent",
                                "value_pointer": "",
                                "catalog_entry_id": indication_entry.catalog_entry_id,
                                # This binding will FAIL: population_intent is
                                # not in indication's supported_target_paths.
                            },
                            {
                                "target_path": "framing.population_intent",
                                "value_pointer": "",
                                "catalog_entry_id": "nonexistent_entry_id",
                            },
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths={"framing.population_intent"},
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("framing.population_intent", []))
        self.assertTrue(any("candidate rejected" in e for e in errors))


class CurrentProjectFactAdoptionModeTests(unittest.TestCase):
    """Complete project-identity facts may be confirmed without retyping.

    Competitor/corpus observations remain manual-only; this regression covers
    the narrow exception that removes the AI-first dead end for a title built
    solely from the already confirmed product, indication, and phase.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.cat, self.proj, self.pkg = _projected_catalog(self.journey)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_complete_current_project_title_is_batch_allowed(self):
        entries = [
            e
            for e in self.cat.entries
            if e.support_scope == "current_project_fact"
            and "framing.document_title" in e.supported_target_paths
        ]
        self.assertEqual(3, len(entries))
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "field_suggestions": {
                "framing.document_title": [
                    {
                        "structured_value": (
                            "CMS-D017用于治疗阵发性睡眠性血红蛋白尿症的II期临床研究"
                        ),
                        "preview": "CMS-D017用于治疗阵发性睡眠性血红蛋白尿症的II期临床研究",
                        "rationale": "仅由当前项目已确认的产品、适应症和分期组成。",
                        "recommendation_role": "alternative",
                        "claim_bindings": [
                            {
                                "target_path": "framing.document_title",
                                "value_pointer": "",
                                "catalog_entry_id": entry.catalog_entry_id,
                                "support_kind": "exact_fact",
                            }
                            for entry in entries
                        ],
                    }
                ]
            },
        }
        _, fields, _, _, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths={"framing.document_title"},
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], errors)
        candidate = fields[0]
        self.assertEqual("supported", candidate.evidence_status)
        self.assertEqual("batch_allowed", candidate.adoption_mode)

    def test_competitor_observation_stays_manual_only(self):
        snapshot = _make_snapshot()
        cat, proj, pkg = _projected_catalog(self.journey, snapshot)
        entry = next(e for e in cat.entries if e.source_kind == "ctgov_snapshot")
        model_output = {
            "catalog_id": cat.catalog_id,
            "catalog_sha256": cat.catalog_sha256,
            "field_suggestions": {
                "picos.population_summary": [
                    {
                        "structured_value": "随机、双盲、平行对照",
                        "preview": "随机、双盲、平行对照",
                        "rationale": "竞品观察，仅供医学经理判断。",
                        "recommendation_role": "alternative",
                        "claim_bindings": [
                            {
                                "target_path": "picos.population_summary",
                                "value_pointer": "",
                                "catalog_entry_id": entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ]
            },
        }
        _, fields, _, _, errors = validate_and_rebind_candidates(
            catalog=cat,
            sent_entry_ids=set(proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths={"picos.population_summary"},
            package_target_paths=_extract_package_target_paths(pkg),
        )
        self.assertEqual([], errors)
        candidate = fields[0]
        self.assertEqual("manual_only", candidate.adoption_mode)

    def test_deterministic_creation_title_gets_full_fact_bindings(self):
        bound = bind_deterministic_project_fact_candidates(
            package=self.pkg,
            catalog=self.cat,
            product="CMS-D017",
            indication="阵发性睡眠性血红蛋白尿症",
            phase="II期",
        )
        group = bound.field_candidates["framing.document_title"]
        self.assertEqual(3, len(group.candidates))
        for candidate in group.candidates:
            self.assertEqual("batch_allowed", candidate.adoption_mode)
            self.assertEqual("supported", candidate.evidence_status)
            self.assertEqual(self.cat.catalog_id, candidate.evidence_catalog_id)
            self.assertEqual(self.cat.catalog_sha256, candidate.evidence_catalog_sha256)
            self.assertEqual(3, len(candidate.claim_bindings))
            self.assertEqual(
                {
                    "framing.investigational_product",
                    "framing.indication",
                    "framing.study_phase",
                },
                {binding.source_id for binding in candidate.claim_bindings},
            )
        self.assertIsNotNone(bound.evidence_catalog)

    def test_deterministic_binding_does_not_unlock_unlisted_title(self):
        title_group = self.pkg.field_candidates["framing.document_title"]
        altered_group = title_group.model_copy(
            update={
                "candidates": [
                    title_group.candidates[0].model_copy(
                        update={"structured_value": "凭空加入随机双盲"}
                    )
                ]
            },
            deep=True,
        )
        package = self.pkg.model_copy(
            update={
                "field_candidates": {
                    **self.pkg.field_candidates,
                    "framing.document_title": altered_group,
                }
            },
            deep=True,
        )
        bound = bind_deterministic_project_fact_candidates(
            package=package,
            catalog=self.cat,
            product="CMS-D017",
            indication="阵发性睡眠性血红蛋白尿症",
            phase="II期",
        )
        candidate = bound.field_candidates["framing.document_title"].candidates[0]
        self.assertEqual("manual_only", candidate.adoption_mode)
        self.assertEqual([], candidate.claim_bindings)


class DeterministicSafetyRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_phase_heuristic_design_description_is_manual_only(self):
        package = generate_prefill_package(
            state=self.journey,
            now=NOW,
            actor="test",
        )
        group = package.field_candidates["framing.design_pattern"]
        self.assertEqual("", group.recommended_candidate_id)
        self.assertTrue(
            all(
                candidate.adoption_mode == "manual_only"
                and candidate.evidence_status == "insufficient"
                and not candidate.claim_bindings
                for candidate in group.candidates
            )
        )


# ---------------------------------------------------------------------------
# Test 4: Unmapped CT.gov fields cannot bind any target
# ---------------------------------------------------------------------------

class UnmappedCtgovTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.snapshot = _make_snapshot()
        self.cat, self.proj, self.pkg = _projected_catalog(
            self.journey, self.snapshot
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_unmapped_document_field_cannot_bind(self):
        """CT.gov fields mapped to empty tuple (lead_sponsor, overall_status,
        nct_id, study_record_url) cannot bind to any PICOS target."""
        # lead_sponsor is explicitly mapped to () — no compatible targets.
        unmapped_entry = next(
            e for e in self.cat.entries
            if e.source_kind == "ctgov_snapshot"
            and "lead_sponsor" in e.locator
        )
        # Try to bind it to population_summary.
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.population": [
                    {
                        "target_paths": sorted({
                            "picos.population_summary",
                            "picos.inclusion_modules",
                            "picos.exclusion_modules",
                            "picos.washout_rules",
                        }),
                        "structured_value": {
                            "picos.population_summary": "test",
                            "picos.inclusion_modules": [],
                            "picos.exclusion_modules": [],
                            "picos.washout_rules": [],
                        },
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "picos.population_summary",
                                "value_pointer": "/picos.population_summary",
                                "catalog_entry_id": unmapped_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("package.population", []))
        self.assertTrue(any("cannot support" in e or "unmapped" in e for e in errors))

    def test_unmapped_nct_id_cannot_bind(self):
        """CT.gov nct_id field is mapped to empty tuple — cannot bind."""
        nct_entry = next(
            e for e in self.cat.entries
            if e.source_kind == "ctgov_snapshot"
            and "nct_id" in e.locator
        )
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.population": [
                    {
                        "target_paths": sorted({
                            "picos.population_summary",
                            "picos.inclusion_modules",
                            "picos.exclusion_modules",
                            "picos.washout_rules",
                        }),
                        "structured_value": {
                            "picos.population_summary": "test",
                            "picos.inclusion_modules": [],
                            "picos.exclusion_modules": [],
                            "picos.washout_rules": [],
                        },
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "picos.population_summary",
                                "value_pointer": "/picos.population_summary",
                                "catalog_entry_id": nct_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("package.population", []))


# ---------------------------------------------------------------------------
# Test 5: intervention[i] for any index can bind intervention/comparator
# ---------------------------------------------------------------------------

class InterventionIndexTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.snapshot = _make_snapshot()
        self.cat, self.proj, self.pkg = _projected_catalog(
            self.journey, self.snapshot
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_intervention_1_name_can_bind_intervention(self):
        """intervention[1].name (index 1, not 0) can bind to
        picos.intervention_summary."""
        interv_entry = next(
            (e for e in self.cat.entries
             if e.source_kind == "ctgov_snapshot"
             and "intervention[1].name" in e.locator),
            None,
        )
        if interv_entry is None:
            self.skipTest("snapshot does not have intervention[1].name entry")
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.intervention": [
                    {
                        "target_paths": sorted({
                            "picos.intervention_summary",
                            "picos.intervention_dose_regimen",
                            "picos.required_background_rules",
                            "picos.allowed_concomitant_rules",
                            "picos.prohibited_concomitant_rules",
                            "picos.assessment_timing_restrictions",
                        }),
                        "structured_value": {
                            "picos.intervention_summary": "Placebo对照组",
                            "picos.intervention_dose_regimen": "",
                            "picos.required_background_rules": [],
                            "picos.allowed_concomitant_rules": [],
                            "picos.prohibited_concomitant_rules": [],
                            "picos.assessment_timing_restrictions": [],
                        },
                        "preview": "test",
                        "rationale": "竞品干预观察。",
                        "recommendation_role": "pending_decision",
                        "claim_bindings": [
                            {
                                "target_path": "picos.intervention_summary",
                                "value_pointer": "/picos.intervention_summary",
                                "catalog_entry_id": interv_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, pkg_cands, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertGreater(len(pkg_cands.get("package.intervention", [])), 0)

    def test_intervention_1_name_cannot_bind_statistics(self):
        """intervention[1].name cannot bind to picos.statistical_strategy."""
        interv_entry = next(
            (e for e in self.cat.entries
             if e.source_kind == "ctgov_snapshot"
             and "intervention[1].name" in e.locator),
            None,
        )
        if interv_entry is None:
            self.skipTest("snapshot does not have intervention[1].name entry")
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.statistics": [
                    {
                        "target_paths": sorted({
                            "picos.study_epochs",
                            "picos.visit_strategy",
                            "picos.estimand_strategy",
                            "picos.sample_size_strategy",
                            "picos.statistical_strategy",
                        }),
                        "structured_value": {
                            "picos.study_epochs": [],
                            "picos.visit_strategy": "",
                            "picos.estimand_strategy": "",
                            "picos.sample_size_strategy": "test",
                            "picos.statistical_strategy": "",
                        },
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "picos.sample_size_strategy",
                                "value_pointer": "/picos.sample_size_strategy",
                                "catalog_entry_id": interv_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("package.statistics", []))


# ---------------------------------------------------------------------------
# Test 6: Package target_paths must exactly match server's set
# ---------------------------------------------------------------------------

class PackageTargetPathsTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.cat, self.proj, self.pkg = _projected_catalog(self.journey)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_missing_target_paths_rejected(self):
        indication_entry = next(
            e for e in self.cat.entries if e.source_id == "framing.indication"
        )
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.population": [
                    {
                        # Missing target_paths entirely.
                        "structured_value": {"picos.population_summary": "test"},
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "picos.population_summary",
                                "value_pointer": "/picos.population_summary",
                                "catalog_entry_id": indication_entry.catalog_entry_id,
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("package.population", []))
        self.assertTrue(any("target_paths" in e and "explicitly" in e for e in errors))

    def test_subset_target_paths_rejected(self):
        indication_entry = next(
            e for e in self.cat.entries if e.source_id == "framing.indication"
        )
        server_paths = _extract_package_target_paths(self.pkg)["package.population"]
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.population": [
                    {
                        "target_paths": server_paths[:2],  # subset
                        "structured_value": {p: "test" for p in server_paths[:2]},
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": server_paths[0],
                                "value_pointer": f"/{server_paths[0]}",
                                "catalog_entry_id": indication_entry.catalog_entry_id,
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("package.population", []))
        self.assertTrue(any("exactly match" in e for e in errors))


# ---------------------------------------------------------------------------
# Test 7: value_pointer validation
# ---------------------------------------------------------------------------

class ValuePointerTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.snapshot = _make_snapshot()
        self.cat, self.proj, self.pkg = _projected_catalog(
            self.journey, self.snapshot
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_pointer_to_nonexistent_key_rejected(self):
        enrollment_entry = next(
            e for e in self.cat.entries if "enrollment_count" in e.locator
        )
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.statistics": [
                    {
                        "target_paths": sorted({
                            "picos.study_epochs", "picos.visit_strategy",
                            "picos.estimand_strategy", "picos.sample_size_strategy",
                            "picos.statistical_strategy",
                        }),
                        "structured_value": {
                            "picos.study_epochs": [],
                            "picos.visit_strategy": "",
                            "picos.estimand_strategy": "",
                            "picos.sample_size_strategy": "100例",
                            "picos.statistical_strategy": "",
                        },
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "picos.sample_size_strategy",
                                "value_pointer": "/picos.statistical_strategy",
                                # Points to wrong key (empty value).
                                "catalog_entry_id": enrollment_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("package.statistics", []))

    def test_pointer_to_empty_value_rejected(self):
        enrollment_entry = next(
            e for e in self.cat.entries if "enrollment_count" in e.locator
        )
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.statistics": [
                    {
                        "target_paths": sorted({
                            "picos.study_epochs", "picos.visit_strategy",
                            "picos.estimand_strategy", "picos.sample_size_strategy",
                            "picos.statistical_strategy",
                        }),
                        "structured_value": {
                            "picos.study_epochs": [],
                            "picos.visit_strategy": "",
                            "picos.estimand_strategy": "",
                            "picos.sample_size_strategy": "",  # EMPTY
                            "picos.statistical_strategy": "",
                        },
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "picos.sample_size_strategy",
                                "value_pointer": "/picos.sample_size_strategy",
                                "catalog_entry_id": enrollment_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("package.statistics", []))

    def test_pointer_to_wrong_target_rejected(self):
        """Pointer resolving to a different target_path than the binding's
        target_path is rejected."""
        enrollment_entry = next(
            e for e in self.cat.entries if "enrollment_count" in e.locator
        )
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.statistics": [
                    {
                        "target_paths": sorted({
                            "picos.study_epochs", "picos.visit_strategy",
                            "picos.estimand_strategy", "picos.sample_size_strategy",
                            "picos.statistical_strategy",
                        }),
                        "structured_value": {
                            "picos.study_epochs": [],
                            "picos.visit_strategy": "",
                            "picos.estimand_strategy": "",
                            "picos.sample_size_strategy": "100",
                            "picos.statistical_strategy": "",
                        },
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "picos.sample_size_strategy",
                                "value_pointer": "/picos.visit_strategy",
                                # Points to visit_strategy, not sample_size.
                                "catalog_entry_id": enrollment_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertEqual([], all_c.get("package.statistics", []))


# ---------------------------------------------------------------------------
# Test 8: Composite package requires complete leaf coverage
# ---------------------------------------------------------------------------

class EvidenceStatusTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.snapshot = _make_snapshot()
        self.cat, self.proj, self.pkg = _projected_catalog(
            self.journey, self.snapshot
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_partial_package_leaf_coverage_is_rejected(self):
        """One bound leaf cannot mask a second unbound clinical claim."""
        enrollment_entry = next(
            e for e in self.cat.entries if "enrollment_count" in e.locator
        )
        package_paths = _extract_package_target_paths(self.pkg)
        statistics_paths = package_paths["package.statistics"]
        statistics_value = {path: "" for path in statistics_paths}
        statistics_value["picos.study_epochs"] = []
        statistics_value["picos.sample_size_strategy"] = "100例"
        statistics_value["picos.statistical_strategy"] = "额外分析"
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.statistics": [
                    {
                        "target_paths": statistics_paths,
                        "structured_value": statistics_value,
                        "preview": "test",
                        "rationale": "test",
                        "recommendation_role": "pending_decision",
                        "claim_bindings": [
                            {
                                "target_path": "picos.sample_size_strategy",
                                "value_pointer": "/picos.sample_size_strategy",
                                "catalog_entry_id": enrollment_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                            # statistical_strategy has "额外分析" but no binding.
                        ],
                    }
                ],
            },
        }
        _, _, pkg_cands, _, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        cands = pkg_cands.get("package.statistics", [])
        self.assertEqual([], cands)
        self.assertTrue(
            any("no direct claim_binding" in item for item in errors)
        )


# ---------------------------------------------------------------------------
# Test 9: Condition term candidate has real server binding
# ---------------------------------------------------------------------------

class ConditionTermBindingTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.cat, self.proj, self.pkg = _projected_catalog(self.journey)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_condition_term_has_real_binding(self):
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "clinicaltrials_condition_term_en": "Paroxysmal Nocturnal Hemoglobinuria",
        }
        cond, _, _, _, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=_extract_package_target_paths(self.pkg),
        )
        self.assertIsNotNone(cond)
        self.assertGreater(len(cond.claim_bindings), 0)
        self.assertTrue(cond.evidence_catalog_id)
        self.assertTrue(cond.evidence_catalog_sha256)
        self.assertEqual("supported", cond.evidence_status)


# ---------------------------------------------------------------------------
# Test 10: Production payload has no registered_source_ids or snapshot_hints
# ---------------------------------------------------------------------------

class PayloadContractTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_payload_has_no_registered_source_ids(self):
        journey = self.service.get("proj_test")
        deterministic = generate_prefill_package(state=journey, now=NOW, actor="test")
        provider = _CatalogAwareProvider()
        adapter = DeepSeekPrefillAdapter(provider=provider, model_name=DEEPSEEK_PREFILL_MODEL)
        adapter.enrich_package(package=deterministic, state=journey)
        payload = provider.calls[0].payload
        self.assertNotIn("registered_source_ids", payload)
        self.assertNotIn("relevance_screened_registry_hints", payload)

    def test_payload_has_evidence_catalog(self):
        journey = self.service.get("proj_test")
        deterministic = generate_prefill_package(state=journey, now=NOW, actor="test")
        provider = _CatalogAwareProvider()
        adapter = DeepSeekPrefillAdapter(provider=provider, model_name=DEEPSEEK_PREFILL_MODEL)
        adapter.enrich_package(package=deterministic, state=journey)
        payload = provider.calls[0].payload
        self.assertIn("evidence_catalog", payload)

    def test_payload_ends_with_complete_top_level_response_contract(self):
        journey = self.service.get("proj_test")
        deterministic = generate_prefill_package(state=journey, now=NOW, actor="test")
        provider = _CatalogAwareProvider()
        adapter = DeepSeekPrefillAdapter(provider=provider, model_name=DEEPSEEK_PREFILL_MODEL)
        adapter.enrich_package(package=deterministic, state=journey)
        payload = provider.calls[0].payload
        reminder = payload["response_contract_reminder"]
        self.assertEqual(
            [
                "clinicaltrials_condition_term_en",
                "field_suggestions",
                "package_suggestions",
                "catalog_id",
                "catalog_sha256",
            ],
            reminder["required_top_level_keys"],
        )
        self.assertEqual(
            payload["evidence_catalog"]["catalog_id"],
            reminder["template"]["catalog_id"],
        )
        self.assertEqual(
            payload["evidence_catalog"]["catalog_sha256"],
            reminder["template"]["catalog_sha256"],
        )

    def test_adapter_server_binds_only_missing_catalog_identity(self):
        journey = self.service.get("proj_test")
        deterministic = generate_prefill_package(state=journey, now=NOW, actor="test")
        enriched = DeepSeekPrefillAdapter(
            provider=_MissingCatalogIdentityProvider(),
            model_name=DEEPSEEK_PREFILL_MODEL,
        ).enrich_package(package=deterministic, state=journey)
        condition_group = enriched.field_candidates[
            "framing.clinicaltrials_condition_term"
        ]
        self.assertTrue(
            any(
                candidate.structured_value
                == "Paroxysmal Nocturnal Hemoglobinuria"
                and candidate.evidence_catalog_id
                for candidate in condition_group.candidates
            )
        )

    def test_adapter_never_overwrites_mismatched_catalog_identity(self):
        journey = self.service.get("proj_test")
        deterministic = generate_prefill_package(state=journey, now=NOW, actor="test")
        provider = _CatalogAwareProvider(
            {
                "catalog_id": "wrong-catalog",
                "catalog_sha256": "0" * 64,
                "clinicaltrials_condition_term_en": (
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ),
                "field_suggestions": {},
                "package_suggestions": {},
            }
        )
        enriched = DeepSeekPrefillAdapter(
            provider=provider,
            model_name=DEEPSEEK_PREFILL_MODEL,
        ).enrich_package(package=deterministic, state=journey)
        condition_group = enriched.field_candidates[
            "framing.clinicaltrials_condition_term"
        ]
        self.assertFalse(
            any(
                candidate.structured_value
                == "Paroxysmal Nocturnal Hemoglobinuria"
                and candidate.evidence_catalog_id
                for candidate in condition_group.candidates
            )
        )
        self.assertTrue(
            any(
                "catalog_id mismatch" in failure
                for failure in enriched.partial_source_failures
            )
        )


# ---------------------------------------------------------------------------
# Test 11: Provider makes one bulk call, identity is deepseek-v4-pro
# ---------------------------------------------------------------------------

class ProviderCallTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_one_bulk_call(self):
        journey = self.service.get("proj_test")
        deterministic = generate_prefill_package(state=journey, now=NOW, actor="test")
        provider = _CatalogAwareProvider()
        adapter = DeepSeekPrefillAdapter(provider=provider, model_name=DEEPSEEK_PREFILL_MODEL)
        adapter.enrich_package(package=deterministic, state=journey)
        self.assertEqual(1, provider.call_count)


# ---------------------------------------------------------------------------
# Regression: deterministic prefill still works
# ---------------------------------------------------------------------------

class RegressionTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_deterministic_prefill_still_works(self):
        journey = self.service.get("proj_test")
        package = generate_prefill_package(state=journey, now=NOW, actor="test")
        self.assertIsNotNone(package)
        self.assertIn("package.population", package.field_candidates)

    def test_no_ai_output_preserves_deterministic(self):
        """When the model returns nothing useful, deterministic pending
        candidates are preserved."""
        journey = self.service.get("proj_test")
        deterministic = generate_prefill_package(state=journey, now=NOW, actor="test")
        provider = _CatalogAwareProvider({
            "clinicaltrials_condition_term_en": "",
            "field_suggestions": {},
            "package_suggestions": {},
        })
        adapter = DeepSeekPrefillAdapter(provider=provider, model_name=DEEPSEEK_PREFILL_MODEL)
        enriched = adapter.enrich_package(package=deterministic, state=journey)
        self.assertIn("package.population", enriched.field_candidates)


# ===========================================================================
# W2b-2 r3: True RFC6901 atomic-leaf pointer tests
# ===========================================================================


class Rfc6901ParseTests(unittest.TestCase):
    """Strict RFC 6901 pointer parsing."""

    def test_simple_root_key(self):
        segs = _parse_rfc6901_pointer("/picos.population_summary")
        self.assertEqual(["picos.population_summary"], segs)

    def test_list_index(self):
        segs = _parse_rfc6901_pointer("/picos.inclusion_modules/0")
        self.assertEqual(["picos.inclusion_modules", "0"], segs)

    def test_nested_object(self):
        segs = _parse_rfc6901_pointer("/picos.assessment_instruments/0/instrument_id")
        self.assertEqual(["picos.assessment_instruments", "0", "instrument_id"], segs)

    def test_missing_leading_slash_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        with self.assertRaises(EvidenceValidationError):
            _parse_rfc6901_pointer("picos.population_summary")

    def test_empty_pointer_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        with self.assertRaises(EvidenceValidationError):
            _parse_rfc6901_pointer("")

    def test_illegal_tilde_escape_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        with self.assertRaises(EvidenceValidationError):
            _parse_rfc6901_pointer("/picos~2bad")

    def test_trailing_tilde_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        with self.assertRaises(EvidenceValidationError):
            _parse_rfc6901_pointer("/picos~")

    def test_valid_tilde_escapes(self):
        segs = _parse_rfc6901_pointer("/picos~1summary")
        self.assertEqual(["picos/summary"], segs)
        segs = _parse_rfc6901_pointer("/picos~0summary")
        self.assertEqual(["picos~summary"], segs)


class Rfc6901ResolveTests(unittest.TestCase):
    """RFC 6901 pointer resolution against structured_value."""

    def test_resolve_string_list_element(self):
        sv = {"picos.inclusion_modules": ["成人", "18-65岁"]}
        segs = _parse_rfc6901_pointer("/picos.inclusion_modules/0")
        result = _resolve_rfc6901(segs, sv)
        self.assertEqual("成人", result)

    def test_resolve_object_list_deep(self):
        sv = {
            "picos.assessment_instruments": [
                {"instrument_id": "HAQ-DI", "version": "v2"},
            ],
        }
        segs = _parse_rfc6901_pointer("/picos.assessment_instruments/0/instrument_id")
        result = _resolve_rfc6901(segs, sv)
        self.assertEqual("HAQ-DI", result)

    def test_resolve_list_out_of_bounds_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        sv = {"picos.inclusion_modules": ["one"]}
        segs = _parse_rfc6901_pointer("/picos.inclusion_modules/5")
        with self.assertRaises(EvidenceValidationError):
            _resolve_rfc6901(segs, sv)

    def test_resolve_dash_index_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        sv = {"picos.inclusion_modules": ["one"]}
        segs = _parse_rfc6901_pointer("/picos.inclusion_modules/-")
        with self.assertRaises(EvidenceValidationError):
            _resolve_rfc6901(segs, sv)

    def test_resolve_leading_zero_index_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        sv = {"picos.inclusion_modules": ["one", "two"]}
        segs = _parse_rfc6901_pointer("/picos.inclusion_modules/01")
        with self.assertRaises(EvidenceValidationError):
            _resolve_rfc6901(segs, sv)

    def test_resolve_non_integer_into_list_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        sv = {"picos.inclusion_modules": ["one"]}
        segs = _parse_rfc6901_pointer("/picos.inclusion_modules/abc")
        with self.assertRaises(EvidenceValidationError):
            _resolve_rfc6901(segs, sv)


class AtomicLeafTests(unittest.TestCase):

    def test_non_empty_string_is_atomic(self):
        self.assertTrue(_is_atomic_leaf("hello"))

    def test_empty_string_not_atomic(self):
        self.assertFalse(_is_atomic_leaf(""))

    def test_whitespace_string_not_atomic(self):
        self.assertFalse(_is_atomic_leaf("   "))

    def test_bool_is_atomic(self):
        self.assertTrue(_is_atomic_leaf(True))
        self.assertTrue(_is_atomic_leaf(False))

    def test_int_float_atomic(self):
        self.assertTrue(_is_atomic_leaf(42))
        self.assertTrue(_is_atomic_leaf(3.14))

    def test_none_not_atomic(self):
        self.assertFalse(_is_atomic_leaf(None))

    def test_list_dict_not_atomic(self):
        self.assertFalse(_is_atomic_leaf([1, 2]))
        self.assertFalse(_is_atomic_leaf({"a": 1}))
        self.assertFalse(_is_atomic_leaf([]))
        self.assertFalse(_is_atomic_leaf({}))


class EnumerateLeavesTests(unittest.TestCase):

    def test_string_root(self):
        leaves = _enumerate_atomic_leaves("test", "/picos.x")
        self.assertEqual(["/picos.x"], leaves)

    def test_string_list(self):
        leaves = _enumerate_atomic_leaves(["a", "b"], "/picos.x")
        self.assertEqual(["/picos.x/0", "/picos.x/1"], leaves)

    def test_object_list_deep(self):
        val = [{"id": "A", "v": "1"}, {"id": "B"}]
        leaves = _enumerate_atomic_leaves(val, "/picos.x")
        self.assertIn("/picos.x/0/id", leaves)
        self.assertIn("/picos.x/0/v", leaves)
        self.assertIn("/picos.x/1/id", leaves)

    def test_empty_list_no_leaves(self):
        leaves = _enumerate_atomic_leaves([], "/picos.x")
        self.assertEqual([], leaves)

    def test_nested_dict(self):
        val = {"k1": "v1", "k2": {"nested": "v2"}}
        leaves = _enumerate_atomic_leaves(val, "/picos.x")
        self.assertIn("/picos.x/k1", leaves)
        self.assertIn("/picos.x/k2/nested", leaves)


class PackagePointerBindingTests(unittest.TestCase):
    """End-to-end: model returns binding with deep pointer; server validates."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.snapshot = _make_snapshot()
        self.cat, self.proj, self.pkg = _projected_catalog(
            self.journey, self.snapshot
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_string_list_pointer_succeeds(self):
        """Binding to /picos.population_summary (string root) succeeds when
        the CT.gov brief_summary entry supports population_summary."""
        brief_summary_entry = next(
            e for e in self.cat.entries
            if e.source_kind == "ctgov_snapshot"
            and "brief_summary" in e.locator
        )
        server_paths = self.proj["package_target_paths"]["package.population"]
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.population": [
                    {
                        "target_paths": sorted(server_paths),
                        "structured_value": {
                            "picos.population_summary": "竞品PNH患者人群",
                            "picos.inclusion_modules": [],
                            "picos.exclusion_modules": [],
                            "picos.washout_rules": [],
                        },
                        "preview": "人群模块",
                        "rationale": "基于竞品摘要。",
                        "recommendation_role": "pending_decision",
                        "claim_bindings": [
                            {
                                "target_path": "picos.population_summary",
                                "value_pointer": "/picos.population_summary",
                                "catalog_entry_id": brief_summary_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, pkg_cands, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=self.proj["package_target_paths"],
        )
        cands = pkg_cands.get("package.population", [])
        self.assertGreater(len(cands), 0, f"errors: {errors}")

    def test_pointer_to_container_rejected(self):
        """Binding to /picos.inclusion_modules (a list) is rejected because
        it resolves to a container, not an atomic leaf."""
        brief_summary_entry = next(
            e for e in self.cat.entries
            if e.source_kind == "ctgov_snapshot"
            and "brief_summary" in e.locator
        )
        server_paths = self.proj["package_target_paths"]["package.population"]
        model_output = {
            "catalog_id": self.cat.catalog_id,
            "catalog_sha256": self.cat.catalog_sha256,
            "package_suggestions": {
                "package.population": [
                    {
                        "target_paths": sorted(server_paths),
                        "structured_value": {
                            "picos.population_summary": "PNH患者",
                            "picos.inclusion_modules": ["成人"],
                            "picos.exclusion_modules": [],
                            "picos.washout_rules": [],
                        },
                        "preview": "test",
                        "rationale": "test",
                        "claim_bindings": [
                            {
                                "target_path": "picos.population_summary",
                                "value_pointer": "/picos.inclusion_modules",
                                # Points to a list, not an atomic leaf.
                                "catalog_entry_id": brief_summary_entry.catalog_entry_id,
                                "support_kind": "competitor_option",
                            }
                        ],
                    }
                ],
            },
        }
        _, _, _, all_c, errors = validate_and_rebind_candidates(
            catalog=self.cat,
            sent_entry_ids=set(self.proj["sent_entry_ids"]),
            model_output=model_output,
            condition_term_path="framing.clinicaltrials_condition_term",
            eligible_field_paths=set(),
            package_target_paths=self.proj["package_target_paths"],
        )
        self.assertEqual([], all_c.get("package.population", []))


class FullCoverageSupportedTests(unittest.TestCase):
    """Test that partial vs full atomic-leaf coverage produces correct status."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())
        self.journey = self.service.get("proj_test")
        self.cat, self.proj, self.pkg = _projected_catalog(self.journey)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_two_element_list_partial_coverage(self):
        """A 2-element string list with only index 0 bound → partially_supported."""
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            _all_atomic_values_bound,
            AuthoringPrefillClaimBinding as _B,
        )
        sv = {"tp": ["a", "b"]}
        bindings = [_B(
            target_path="tp", value_pointer="/tp/0",
            catalog_entry_id="x", source_id="s", locator="l",
            quote_sha256="a"*64, support_kind="exact_fact",
        )]
        result = _all_atomic_values_bound(sv, bindings, ["tp"], is_package=True)
        self.assertFalse(result)  # /tp/1 is not covered.

    def test_two_element_list_full_coverage(self):
        """A 2-element string list with both indices bound → supported."""
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            _all_atomic_values_bound,
            AuthoringPrefillClaimBinding as _B,
        )
        sv = {"tp": ["a", "b"]}
        bindings = [
            _B(target_path="tp", value_pointer="/tp/0",
               catalog_entry_id="x", source_id="s", locator="l",
               quote_sha256="a"*64, support_kind="exact_fact"),
            _B(target_path="tp", value_pointer="/tp/1",
               catalog_entry_id="y", source_id="s2", locator="l2",
               quote_sha256="b"*64, support_kind="exact_fact"),
        ]
        result = _all_atomic_values_bound(sv, bindings, ["tp"], is_package=True)
        self.assertTrue(result)


class ServerPackageTargetPathsTests(unittest.TestCase):
    """Test fail-closed _extract_package_target_paths."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_normal_extraction_succeeds(self):
        journey = self.service.get("proj_test")
        pkg = generate_prefill_package(state=journey, now=NOW, actor="test")
        paths = _extract_package_target_paths(pkg)
        for key in PACKAGE_KEYS:
            self.assertIn(key, paths)
            self.assertGreater(len(paths[key]), 0)

    def test_missing_package_group_raises(self):
        journey = self.service.get("proj_test")
        pkg = generate_prefill_package(state=journey, now=NOW, actor="test")
        # Remove one package group.
        del pkg.field_candidates["package.population"]
        with self.assertRaises(PackageTargetPathError):
            _extract_package_target_paths(pkg)

    def test_inconsistent_target_paths_within_group_raises(self):
        journey = self.service.get("proj_test")
        pkg = generate_prefill_package(state=journey, now=NOW, actor="test")
        # Tamper: add a second candidate with different target_paths to create
        # inconsistency within the same group.
        group = pkg.field_candidates["package.population"]
        original = group.candidates[0]
        from packages.contracts.workbench_contracts import (
            AuthoringPrefillCandidate as _C,
        )
        bogus = _C(
            candidate_id=original.candidate_id + "_bogus",
            field_path=original.field_path,
            structured_value={"bogus_path": "x"},
            candidate_scope="module",
            target_paths=["bogus_path"],
        )
        tampered_group = group.model_copy(
            update={"candidates": [original, bogus]}
        )
        pkg.field_candidates["package.population"] = tampered_group
        with self.assertRaises(PackageTargetPathError):
            _extract_package_target_paths(pkg)

    def test_enrich_package_missing_group_no_provider_call(self):
        """When a package group is missing, enrich_package returns partial
        failure without calling the provider."""
        journey = self.service.get("proj_test")
        pkg = generate_prefill_package(state=journey, now=NOW, actor="test")
        del pkg.field_candidates["package.population"]
        provider = _CatalogAwareProvider()
        adapter = DeepSeekPrefillAdapter(
            provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
        )
        enriched = adapter.enrich_package(package=pkg, state=journey)
        self.assertEqual(0, provider.call_count)
        self.assertTrue(
            any("package target paths" in f for f in enriched.partial_source_failures)
        )


class SystemPromptContractTests(unittest.TestCase):
    """Test that the system prompt and payload don't reference old bypass."""

    def test_system_prompt_no_registered_source_ids(self):
        self.assertNotIn("registered_source_ids", _BULK_SYSTEM_PROMPT)
        self.assertNotIn("registry hint", _BULK_SYSTEM_PROMPT)

    def test_payload_no_registered_source_ids(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            service = MedicalWritingAuthoringJourneyService(
                Path(tmpdir.name) / "test.sqlite3"
            )
            service.create("proj_test", _create_request())
            journey = service.get("proj_test")
            deterministic = generate_prefill_package(
                state=journey, now=NOW, actor="test"
            )
            provider = _CatalogAwareProvider()
            adapter = DeepSeekPrefillAdapter(
                provider=provider, model_name=DEEPSEEK_PREFILL_MODEL
            )
            adapter.enrich_package(package=deterministic, state=journey)
            payload_str = json.dumps(provider.calls[0].payload, ensure_ascii=False)
            self.assertNotIn("registered_source_ids", payload_str)
            self.assertNotIn("relevance_screened_registry_hints", payload_str)
        finally:
            tmpdir.cleanup()


# ===========================================================================
# W2b-2 r4: Empty-segment and per-candidate scope fail-closed
# ===========================================================================


class EmptySegmentPointerTests(unittest.TestCase):
    """r4: Empty RFC 6901 segments must be rejected."""

    def test_slash_only_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        with self.assertRaises(EvidenceValidationError):
            _parse_rfc6901_pointer("/")

    def test_trailing_slash_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        with self.assertRaises(EvidenceValidationError):
            _parse_rfc6901_pointer("/picos.x/")

    def test_double_slash_in_middle_rejected(self):
        from services.api.app.medical_writing_authoring_prefill_evidence_binding import (
            EvidenceValidationError,
        )
        with self.assertRaises(EvidenceValidationError):
            _parse_rfc6901_pointer("/picos.x//0")

    def test_valid_deep_pointer_still_passes(self):
        segs = _parse_rfc6901_pointer("/picos.assessment_instruments/0/instrument_id")
        self.assertEqual(
            ["picos.assessment_instruments", "0", "instrument_id"], segs
        )

    def test_valid_tilde_escapes_still_pass(self):
        segs = _parse_rfc6901_pointer("/picos~1summary")
        self.assertEqual(["picos/summary"], segs)


class PerCandidateScopeTests(unittest.TestCase):
    """r4: Every candidate in a package group must have module/design_package
    scope, not just the first."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.service = MedicalWritingAuthoringJourneyService(
            Path(self.tmpdir.name) / "test.sqlite3"
        )
        self.service.create("proj_test", _create_request())

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_second_candidate_field_scope_rejected(self):
        """When the second candidate in a group has scope=field but the same
        target_paths, _extract_package_target_paths must fail-closed."""
        journey = self.service.get("proj_test")
        pkg = generate_prefill_package(state=journey, now=NOW, actor="test")
        group = pkg.field_candidates["package.population"]
        original = group.candidates[0]
        from packages.contracts.workbench_contracts import (
            AuthoringPrefillCandidate as _C,
        )
        # Second candidate: same target_paths but scope=field.
        # For scope=field, target_paths must be empty (enforced by validator).
        # But we need it to have the same target_paths as the first to test
        # the scope check, not the target_paths check. So we use scope=table
        # which allows target_paths.
        bogus = _C(
            candidate_id=original.candidate_id + "_field",
            field_path=original.field_path,
            structured_value={
                k: v for k, v in original.structured_value.items()
            },
            candidate_scope="table",
            target_paths=list(original.target_paths),
        )
        tampered_group = group.model_copy(
            update={"candidates": [original, bogus]}
        )
        pkg.field_candidates["package.population"] = tampered_group
        with self.assertRaises(PackageTargetPathError) as ctx:
            _extract_package_target_paths(pkg)
        self.assertIn("scope", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
