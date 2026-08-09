"""Contract tests for the AI-first composite candidate extension.

Verifies backward-compatible defaults, composite scope validation, adoption
mode rules, the composite adopt request model, and the package import smoke.
"""

from __future__ import annotations

import json
import unittest

import packages.contracts.workbench_contracts as pkg
from packages.contracts.workbench_contracts import (
    AuthoringPrefillCandidate,
    AuthoringPrefillCompositeAdoptRequest,
    AuthoringPrefillEvidenceRef,
    AuthoringPrefillFieldCandidates,
    AuthoringPrefillPackage,
)
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _field_candidate(**overrides) -> AuthoringPrefillCandidate:
    defaults = dict(
        candidate_id="cand_test_001",
        field_path="framing.protocol_id",
        structured_value="CMS-001",
        preview="CMS-001",
    )
    defaults.update(overrides)
    return AuthoringPrefillCandidate(**defaults)


def _module_candidate(**overrides) -> AuthoringPrefillCandidate:
    targets = ["picos.population_summary", "picos.inclusion_modules"]
    value = {
        "picos.population_summary": "目标人群",
        "picos.inclusion_modules": ["条件A"],
    }
    defaults = dict(
        candidate_id="cand_mod_001",
        field_path="package.population",
        candidate_scope="module",
        target_paths=list(targets),
        structured_value=value,
        recommendation_role="recommended",
        adoption_mode="batch_allowed",
    )
    defaults.update(overrides)
    return AuthoringPrefillCandidate(**defaults)


def _design_package_candidate(**overrides) -> AuthoringPrefillCandidate:
    targets = ["design.randomization", "design.blinding"]
    value = {
        "design.randomization": "分层随机",
        "design.blinding": "双盲",
    }
    defaults = dict(
        candidate_id="cand_dp_001",
        field_path="package.design",
        candidate_scope="design_package",
        target_paths=list(targets),
        structured_value=value,
        recommendation_role="recommended",
        adoption_mode="batch_allowed",
    )
    defaults.update(overrides)
    return AuthoringPrefillCandidate(**defaults)


# ---------------------------------------------------------------------------
# 1. Legacy backward compatibility
# ---------------------------------------------------------------------------

class LegacyBackwardCompatibilityTests(unittest.TestCase):

    def test_legacy_single_field_json_loads_without_new_fields(self):
        """A candidate JSON with only pre-extension fields must load and default correctly."""
        legacy_json = json.dumps(
            {
                "candidate_id": "cand_legacy_001",
                "field_path": "framing.protocol_id",
                "structured_value": "CMS-LEGACY-001",
                "preview": "CMS-LEGACY-001",
                "evidence_refs": [],
                "rationale": "legacy candidate",
                "limitations": [],
                "confidence": "medium",
                "state": "ai_proposed",
            }
        )
        candidate = AuthoringPrefillCandidate.model_validate_json(legacy_json)
        self.assertEqual("field", candidate.candidate_scope)
        self.assertEqual([], candidate.target_paths)
        self.assertEqual("recommended", candidate.recommendation_role)
        self.assertEqual("manual_only", candidate.adoption_mode)
        self.assertEqual([], candidate.clinical_tradeoffs)
        self.assertEqual([], candidate.evidence_gaps)
        self.assertEqual("", candidate.ai_run_id)

    def test_legacy_candidate_with_explicit_empty_target_paths_keeps_field_scope(self):
        """A field-scope candidate with explicitly empty target_paths is normalised to []."""
        candidate = AuthoringPrefillCandidate(
            candidate_id="cand_empty_targets",
            field_path="framing.version",
            structured_value="V1.0",
            candidate_scope="field",
            target_paths=[],
        )
        self.assertEqual("field", candidate.candidate_scope)
        self.assertEqual([], candidate.target_paths)


# ---------------------------------------------------------------------------
# 2. Candidate scope — positive
# ---------------------------------------------------------------------------

class CandidateScopePositiveTests(unittest.TestCase):

    def test_field_scope_candidate_passes(self):
        candidate = _field_candidate()
        self.assertEqual("field", candidate.candidate_scope)
        self.assertEqual([], candidate.target_paths)

    def test_module_scope_candidate_passes(self):
        candidate = _module_candidate()
        self.assertEqual("module", candidate.candidate_scope)
        self.assertGreater(len(candidate.target_paths), 0)

    def test_design_package_scope_candidate_passes(self):
        candidate = _design_package_candidate()
        self.assertEqual("design_package", candidate.candidate_scope)

    def test_table_scope_enum_accepted(self):
        candidate = AuthoringPrefillCandidate(
            candidate_id="cand_table_001",
            field_path="package.soa",
            candidate_scope="table",
        )
        self.assertEqual("table", candidate.candidate_scope)

    def test_chapter_scope_enum_accepted(self):
        candidate = AuthoringPrefillCandidate(
            candidate_id="cand_chapter_001",
            field_path="package.chapter1",
            candidate_scope="chapter",
        )
        self.assertEqual("chapter", candidate.candidate_scope)


# ---------------------------------------------------------------------------
# 3. Candidate scope — negative
# ---------------------------------------------------------------------------

class CandidateScopeNegativeTests(unittest.TestCase):

    def test_module_scope_empty_target_paths_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="cand_mod_empty",
                field_path="package.population",
                candidate_scope="module",
                target_paths=[],
                structured_value={},
            )
        self.assertIn("requires non-empty target_paths", str(ctx.exception))

    def test_design_package_scope_empty_target_paths_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="cand_dp_empty",
                field_path="package.design",
                candidate_scope="design_package",
                target_paths=[],
                structured_value={},
            )
        self.assertIn("requires non-empty target_paths", str(ctx.exception))

    def test_duplicate_target_paths_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="cand_dup",
                field_path="package.population",
                candidate_scope="module",
                target_paths=["picos.population_summary", "picos.population_summary"],
                structured_value={
                    "picos.population_summary": "val",
                },
            )
        self.assertIn("duplicates", str(ctx.exception))

    def test_empty_string_in_target_paths_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="cand_blank",
                field_path="package.population",
                candidate_scope="module",
                target_paths=["  ", "picos.population_summary"],
                structured_value={
                    "  ": "val",
                    "picos.population_summary": "val2",
                },
            )
        self.assertIn("empty strings", str(ctx.exception))


# ---------------------------------------------------------------------------
# 4. Structured value vs target_paths mismatch
# ---------------------------------------------------------------------------

class StructuredValueMismatchTests(unittest.TestCase):

    def test_module_structured_value_not_dict_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="cand_sv_not_dict",
                field_path="package.population",
                candidate_scope="module",
                target_paths=["picos.population_summary"],
                structured_value="a plain string",
            )
        self.assertIn("must be an object", str(ctx.exception))

    def test_module_structured_value_missing_key_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="cand_sv_missing",
                field_path="package.population",
                candidate_scope="module",
                target_paths=["picos.population_summary", "picos.inclusion_modules"],
                structured_value={
                    "picos.population_summary": "val",
                    # picos.inclusion_modules missing
                },
            )
        self.assertIn("missing keys", str(ctx.exception))

    def test_module_structured_value_extra_key_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="cand_sv_extra",
                field_path="package.population",
                candidate_scope="module",
                target_paths=["picos.population_summary"],
                structured_value={
                    "picos.population_summary": "val",
                    "picos.unexpected": "extra",
                },
            )
        self.assertIn("unexpected keys", str(ctx.exception))


# ---------------------------------------------------------------------------
# 5. Recommendation role and adoption mode
# ---------------------------------------------------------------------------

class RecommendationRoleAdoptionModeTests(unittest.TestCase):

    def test_pending_decision_forces_manual_only(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCandidate(
                candidate_id="cand_pd_batch",
                field_path="package.population",
                candidate_scope="module",
                target_paths=["picos.population_summary"],
                structured_value={"picos.population_summary": "val"},
                recommendation_role="pending_decision",
                adoption_mode="batch_allowed",
            )
        self.assertIn("manual_only", str(ctx.exception))

    def test_pending_decision_with_manual_only_passes(self):
        candidate = AuthoringPrefillCandidate(
            candidate_id="cand_pd_ok",
            field_path="package.population",
            candidate_scope="module",
            target_paths=["picos.population_summary"],
            structured_value={"picos.population_summary": "val"},
            recommendation_role="pending_decision",
            adoption_mode="manual_only",
        )
        self.assertEqual("pending_decision", candidate.recommendation_role)
        self.assertEqual("manual_only", candidate.adoption_mode)

    def test_recommended_with_batch_allowed_passes(self):
        candidate = _design_package_candidate(
            recommendation_role="recommended",
            adoption_mode="batch_allowed",
        )
        self.assertEqual("batch_allowed", candidate.adoption_mode)


# ---------------------------------------------------------------------------
# 6. Composite adopt request
# ---------------------------------------------------------------------------

class CompositeAdoptRequestTests(unittest.TestCase):

    def _valid_request(self, **overrides) -> dict:
        defaults = dict(
            expected_revision=1,
            expected_package_revision=1,
            package_field_path="package.population",
            candidate_id="cand_mod_001",
            actor="medical_manager",
            idempotency_key="adopt-comp-001",
        )
        defaults.update(overrides)
        return defaults

    def test_valid_composite_request_passes(self):
        request = AuthoringPrefillCompositeAdoptRequest(**self._valid_request())
        self.assertEqual("package.population", request.package_field_path)

    def test_valid_composite_request_with_overrides_passes(self):
        request = AuthoringPrefillCompositeAdoptRequest(
            **self._valid_request(
                path_overrides={
                    "picos.population_summary": "overridden value",
                }
            )
        )
        self.assertIn("picos.population_summary", request.path_overrides)

    def test_skipped_paths_are_trimmed_sorted_and_unique(self):
        request = AuthoringPrefillCompositeAdoptRequest(
            **self._valid_request(
                skipped_paths=[
                    " picos.exclusion_modules ",
                    "picos.inclusion_modules",
                    "picos.exclusion_modules",
                ]
            )
        )
        self.assertEqual(
            ["picos.exclusion_modules", "picos.inclusion_modules"],
            request.skipped_paths,
        )

    def test_override_and_skip_overlap_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCompositeAdoptRequest(
                **self._valid_request(
                    path_overrides={"picos.population_summary": "人群"},
                    skipped_paths=["picos.population_summary"],
                )
            )
        self.assertIn("must not overlap", str(ctx.exception))

    def test_blank_skipped_path_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCompositeAdoptRequest(
                **self._valid_request(skipped_paths=["  "])
            )
        self.assertIn("non-empty paths", str(ctx.exception))

    def test_empty_candidate_id_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillCompositeAdoptRequest(
                **self._valid_request(candidate_id="  ")
            )

    def test_empty_actor_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillCompositeAdoptRequest(
                **self._valid_request(actor="")
            )

    def test_empty_idempotency_key_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillCompositeAdoptRequest(
                **self._valid_request(idempotency_key="")
            )

    def test_empty_package_field_path_rejected(self):
        with self.assertRaises(ValidationError):
            AuthoringPrefillCompositeAdoptRequest(
                **self._valid_request(package_field_path="  ")
            )

    def test_override_with_empty_path_key_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCompositeAdoptRequest(
                **self._valid_request(
                    path_overrides={"  ": "value"},
                )
            )
        self.assertIn("non-empty paths", str(ctx.exception))

    def test_override_with_none_value_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillCompositeAdoptRequest(
                **self._valid_request(
                    path_overrides={"picos.population_summary": None},
                )
            )
        self.assertIn("must not be None", str(ctx.exception))


# ---------------------------------------------------------------------------
# 7. Package import smoke
# ---------------------------------------------------------------------------

class PackageImportSmokeTests(unittest.TestCase):

    def test_new_type_is_importable_from_package(self):
        self.assertTrue(hasattr(pkg, "AuthoringPrefillCompositeAdoptRequest"))
        self.assertIs(
            AuthoringPrefillCompositeAdoptRequest,
            pkg.AuthoringPrefillCompositeAdoptRequest,
        )

    def test_new_type_is_in_dunder_all(self):
        self.assertIn("AuthoringPrefillCompositeAdoptRequest", pkg.__all__)

    def test_existing_prefill_types_still_importable(self):
        for name in (
            "AuthoringPrefillEvidenceRef",
            "AuthoringPrefillCandidate",
            "AuthoringPrefillFieldCandidates",
            "AuthoringPrefillProgress",
            "AuthoringPrefillPackage",
            "AuthoringPrefillGenerateRequest",
            "AuthoringPrefillAdoptRequest",
        ):
            self.assertTrue(hasattr(pkg, name), f"{name} missing from package")
            self.assertIn(name, pkg.__all__)


# ---------------------------------------------------------------------------
# 8. Candidate with clinical_tradeoffs / evidence_gaps / ai_run_id
# ---------------------------------------------------------------------------

class ExtendedMetadataFieldsTests(unittest.TestCase):

    def test_tradeoffs_and_gaps_default_empty(self):
        candidate = _field_candidate()
        self.assertEqual([], candidate.clinical_tradeoffs)
        self.assertEqual([], candidate.evidence_gaps)

    def test_tradeoffs_and_gaps_stripped_and_filtered(self):
        candidate = _field_candidate(
            clinical_tradeoffs=["  tradeoff A  ", "", "  tradeoff B  "],
            evidence_gaps=["  gap 1  ", "   "],
            ai_run_id="  run_abc  ",
        )
        self.assertEqual(["tradeoff A", "tradeoff B"], candidate.clinical_tradeoffs)
        self.assertEqual(["gap 1"], candidate.evidence_gaps)
        self.assertEqual("run_abc", candidate.ai_run_id)


# ---------------------------------------------------------------------------
# 9. Empty recommended id for non-empty groups (corrective round 2)
# ---------------------------------------------------------------------------

class RecommendedCandidateEmptyContractTests(unittest.TestCase):
    """A non-empty candidate group may carry an empty recommended id when
    every visible candidate is pending/manual/unsafe; any non-empty id must
    still reference exactly one candidate in the same group."""

    def _group(self, **overrides) -> AuthoringPrefillFieldCandidates:
        defaults = dict(
            field_path="framing.protocol_id",
            recommended_candidate_id="",
            candidates=[_field_candidate(candidate_id="c_1")],
        )
        defaults.update(overrides)
        return AuthoringPrefillFieldCandidates(**defaults)

    def test_empty_recommended_id_allowed_for_non_empty_group(self):
        group = self._group()
        self.assertEqual("", group.recommended_candidate_id)
        self.assertEqual(1, len(group.candidates))

    def test_empty_recommended_id_round_trips_through_json(self):
        group = self._group()
        payload = group.model_dump_json()
        self.assertIn('"recommended_candidate_id":""', payload)
        restored = AuthoringPrefillFieldCandidates.model_validate_json(payload)
        self.assertEqual("", restored.recommended_candidate_id)
        self.assertEqual("c_1", restored.candidates[0].candidate_id)

    def test_non_empty_recommended_id_must_reference_group_candidate(self):
        with self.assertRaises(ValidationError) as ctx:
            self._group(recommended_candidate_id="missing_id")
        self.assertIn("must reference a candidate", str(ctx.exception))

    def test_valid_non_empty_recommended_id_passes(self):
        group = self._group(recommended_candidate_id="c_1")
        self.assertEqual("c_1", group.recommended_candidate_id)

    def test_empty_candidates_with_recommended_id_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            AuthoringPrefillFieldCandidates(
                field_path="framing.protocol_id",
                recommended_candidate_id="c_1",
                candidates=[],
            )
        self.assertIn("requires candidates", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
