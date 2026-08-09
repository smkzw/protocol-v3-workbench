"""v4 source-truth closure tests for competitor triage.

Covers the production anti-examples from D017 PNH:
- protocol_sap / protocol / sap / no-doc deterministic derivation
- modality/route/target_mechanism forced unknown when project or candidate
  lacks the fact
- reason sanitization removes unsourced mechanism/route claims
- tablets name must not infer oral route
- FIH/I/II/PK/PD without SAD/MAD/escalation text must not produce
  "dose escalation" in the server-side reason
- direct_competitor downgraded to indirect_reference when project facts unknown
- excluded not promoted
- backward-compatible _validate_chunk_response(response, expected_nct_ids)
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from packages.contracts.workbench_contracts import (
    CompetitorTriageClassification,
)
from services.api.app.medical_writing_competitor_triage import (
    CompetitorTriageError,
    TRIAGE_MODEL_NAME,
    TRIAGE_PROMPT_VERSION,
    TRIAGE_PROVIDER_NAME,
    _build_chunk_input,
    _candidate_indication_matches_project,
    _derive_document_suitability,
    _enforce_classification_eligibility,
    _enforce_matching_dimensions,
    _hash_value,
    _sanitize_reason,
    _validate_chunk_response,
)
from packages.contracts.workbench_contracts import (
    CompetitorTriageMatchingDimension,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate_input(
    nct_id: str,
    *,
    conditions: List[str] | None = None,
    phases: List[str] | None = None,
    interventions: List[Dict[str, str]] | None = None,
    docs: List[Dict[str, str]] | None = None,
    design_allocation: str = "",
    design_intervention_model: str = "",
    design_masking: str = "",
    enrollment_count: int | None = None,
    brief_summary: str = "",
) -> Dict[str, Any]:
    # Distinguish "not provided" (→ default PNH) from "explicitly empty" (→ [])
    if conditions is None:
        conditions = ["Paroxysmal Nocturnal Hemoglobinuria"]
    if phases is None:
        phases = ["PHASE2"]
    return {
        "nct_id": nct_id,
        "conditions": conditions,
        "phases": phases,
        "study_type": "INTERVENTIONAL",
        "brief_summary": brief_summary,
        "interventions": interventions or [],
        "design_allocation": design_allocation,
        "design_intervention_model": design_intervention_model,
        "design_masking": design_masking,
        "enrollment_count": enrollment_count,
        "lead_sponsor": "Test Sponsor",
        "overall_status": "COMPLETED",
        "public_documents": docs or [],
    }


def _project_facts_unknown() -> Dict[str, Any]:
    """Project facts matching the D017 PNH anti-example: all critical facts unknown."""
    return {
        "investigational_product": "CMS-D017",
        "indication": "阵发性睡眠性血红蛋白尿症（PNH）",
        "clinicaltrials_condition_term": "Paroxysmal Nocturnal Hemoglobinuria",
        "study_phase": "II期",
        "target_mechanism": "",
        "competitor_target_scope": "",
        "product_profile": {
            "technology_type": "unknown",
            "administration_routes": [],
            "dosage_forms": [],
            "exposure_scope": "unknown",
        },
        "population_intent": "",
        "picos": {},
    }


def _project_facts_complete() -> Dict[str, Any]:
    """Project facts with all critical dimensions known."""
    return {
        "investigational_product": "CMS-RA-201",
        "indication": "类风湿关节炎（RA）",
        "clinicaltrials_condition_term": "Rheumatoid Arthritis",
        "study_phase": "II期",
        "target_mechanism": "TNF-alpha inhibitor",
        "product_profile": {
            "technology_type": "monoclonal_antibody",
            "administration_routes": ["intravenous"],
            "dosage_forms": ["injection"],
            "exposure_scope": "systemic",
        },
        "population_intent": "",
        "picos": {},
    }


def _model_result(
    nct_id: str,
    *,
    classification: str = "indirect_reference",
    confidence: float = 0.8,
    reason: str = "",
    matching_dims: List[Dict[str, str]] | None = None,
    evidence_gaps: List[str] | None = None,
    has_protocol: bool = False,
    has_sap: bool = False,
    document_role: str = "",
) -> Dict[str, Any]:
    return {
        "nct_id": nct_id,
        "classification": classification,
        "confidence": confidence,
        "reason": reason,
        "matching_dimensions": matching_dims or [],
        "evidence_gaps": evidence_gaps or [],
        "document_suitability": {
            "has_public_protocol": has_protocol,
            "has_public_sap": has_sap,
            "document_role": document_role,
        },
    }


def _dim(name: str, match: str = "unknown", detail: str = "") -> CompetitorTriageMatchingDimension:
    return CompetitorTriageMatchingDimension(
        dimension=name, match=match, detail=detail  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# A. Document suitability deterministic derivation
# ---------------------------------------------------------------------------


class TestDocumentSuitabilityDerivation(unittest.TestCase):
    def test_protocol_sap_overrides_model_false_booleans(self):
        """Anti-example 1: model returns protocol=false, sap=true for protocol_sap."""
        candidate = _candidate_input(
            "NCT00397813",
            docs=[{"document_type": "protocol_sap", "filename": "doc.pdf"}],
        )
        result = _derive_document_suitability(candidate, "")
        self.assertTrue(result["has_public_protocol"])
        self.assertTrue(result["has_public_sap"])

    def test_protocol_only(self):
        candidate = _candidate_input(
            "NCT001",
            docs=[{"document_type": "protocol", "filename": "p.pdf"}],
        )
        result = _derive_document_suitability(candidate, "")
        self.assertTrue(result["has_public_protocol"])
        self.assertFalse(result["has_public_sap"])

    def test_sap_only(self):
        candidate = _candidate_input(
            "NCT002",
            docs=[{"document_type": "sap", "filename": "s.pdf"}],
        )
        result = _derive_document_suitability(candidate, "")
        self.assertFalse(result["has_public_protocol"])
        self.assertTrue(result["has_public_sap"])

    def test_no_documents(self):
        candidate = _candidate_input("NCT003")
        result = _derive_document_suitability(candidate, "")
        self.assertFalse(result["has_public_protocol"])
        self.assertFalse(result["has_public_sap"])

    def test_document_role_always_deterministic_ignores_model_text(self):
        """document_role is always deterministic; model free text is never kept
        because it may contain unsourced route/target/modality claims."""
        candidate = _candidate_input(
            "NCT004",
            docs=[{"document_type": "protocol", "filename": "p.pdf"}],
        )
        result = _derive_document_suitability(
            candidate, "可用于参考口服补体抑制剂的设计"
        )
        self.assertTrue(result["has_public_protocol"])
        # Model free text must NOT be preserved
        self.assertNotIn("口服", result["document_role"])
        self.assertNotIn("补体", result["document_role"])
        self.assertEqual("已提供公开方案", result["document_role"])

    def test_document_role_deterministic_when_model_empty(self):
        candidate = _candidate_input("NCT005")
        result = _derive_document_suitability(candidate, "")
        self.assertEqual("无公开方案或统计分析计划", result["document_role"])


# ---------------------------------------------------------------------------
# B. Matching dimension evidence gate
# ---------------------------------------------------------------------------


class TestMatchingDimensionEvidenceGate(unittest.TestCase):
    def test_project_unknown_forces_unknown_on_protected_dims(self):
        """Anti-example 3: model claims match but project fact is empty."""
        dims = [
            _dim("indication", "match", "Same indication"),
            _dim("route", "match", "口服给药"),  # model claims oral match
            _dim("target_mechanism", "match", "补体B因子抑制剂"),
        ]
        candidate = _candidate_input("NCT03896152")
        project = _project_facts_unknown()
        gaps: List[str] = []
        result = _enforce_matching_dimensions(dims, candidate, project, gaps)

        dim_map = {d.dimension: d for d in result}
        self.assertEqual("unknown", dim_map["route"].match)
        self.assertEqual("unknown", dim_map["target_mechanism"].match)
        self.assertEqual("unknown", dim_map["modality"].match)
        # Non-protected dim unchanged
        self.assertEqual("match", dim_map["indication"].match)
        # Evidence gaps added with Chinese labels
        self.assertTrue(any("给药途径" in g for g in gaps))
        self.assertTrue(any("靶点/机制" in g for g in gaps))
        self.assertTrue(any("技术类型" in g for g in gaps))

    def test_tablets_name_does_not_infer_oral_route(self):
        """Anti-example 4: MY008211A tablets must not infer oral route."""
        candidate = _candidate_input(
            "NCT06050226",
            interventions=[{"name": "MY008211A tablets", "intervention_type": "DRUG"}],
        )
        project = _project_facts_unknown()
        dims = [_dim("route", "match", "口服给药，与片剂名称一致")]
        gaps: List[str] = []
        result = _enforce_matching_dimensions(dims, candidate, project, gaps)

        route_dim = {d.dimension: d for d in result}["route"]
        self.assertEqual("unknown", route_dim.match)
        self.assertIn("给药途径", route_dim.detail)

    def test_complete_project_facts_but_candidate_lacks_structured_field(self):
        """Even when project has all critical facts, candidate input never has
        structured modality/route/target_mechanism fields — so protected dims
        are always forced unknown.  This is correct: the model should only
        assess route/target match when the candidate has an explicit structured
        value, not inferred from drug names or brief summary."""
        dims = [
            _dim("route", "match", "Both intravenous"),
            _dim("target_mechanism", "match", "Same target"),
        ]
        candidate = _candidate_input("NCT001")
        project = _project_facts_complete()
        gaps: List[str] = []
        result = _enforce_matching_dimensions(dims, candidate, project, gaps)

        dim_map = {d.dimension: d for d in result}
        # Candidate never has structured route/target_mechanism field → forced unknown
        self.assertEqual("unknown", dim_map["route"].match)
        self.assertEqual("unknown", dim_map["target_mechanism"].match)
        self.assertEqual("unknown", dim_map["modality"].match)


# ---------------------------------------------------------------------------
# C. Reason sanitization
# ---------------------------------------------------------------------------


class TestReasonSanitization(unittest.TestCase):
    def test_reason_strips_unsourced_mechanism_claims(self):
        """Anti-example: iptacopan/LNP023 -> "补体B因子抑制剂" must not appear."""
        candidate = _candidate_input(
            "NCT03896152",
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
            design_allocation="RANDOMIZED",
            design_intervention_model="PARALLEL",
            design_masking="NONE",
            enrollment_count=30,
        )
        project = _project_facts_unknown()
        dims = [
            _dim("indication", "match"),
            _dim("route", "unknown"),
            _dim("target_mechanism", "unknown"),
            _dim("modality", "unknown"),
        ]
        doc_suit = {"has_public_protocol": True, "has_public_sap": True}
        model_reason = "iptacopan为补体B因子抑制剂，口服给药，与项目靶点可能一致。"
        result = _sanitize_reason(
            model_reason, candidate, project, dims, doc_suit
        )
        # Must NOT contain unsourced mechanism or route
        self.assertNotIn("补体B因子抑制剂", result)
        self.assertNotIn("口服", result)
        # Must contain explicit-input-based content
        self.assertIn("iptacopan", result)
        self.assertIn("方案", result)

    def test_reason_no_dose_escalation_without_explicit_text(self):
        """Anti-example 5: FIH/I/II/PK/PD without SAD/MAD/escalation text."""
        candidate = _candidate_input(
            "NCT05876312",
            interventions=[{"name": "ADX-038", "intervention_type": "DRUG"}],
            phases=["PHASE1", "PHASE2"],
            design_allocation="RANDOMIZED",
            design_intervention_model="PARALLEL",
            design_masking="TRIPLE",
        )
        project = _project_facts_unknown()
        dims = [
            _dim("phase", "partial"),
            _dim("route", "unknown"),
            _dim("target_mechanism", "unknown"),
            _dim("modality", "unknown"),
        ]
        doc_suit = {"has_public_protocol": False, "has_public_sap": False}
        model_reason = "该研究为剂量递增设计，可提供PK/PD参考。"
        result = _sanitize_reason(
            model_reason, candidate, project, dims, doc_suit
        )
        self.assertNotIn("剂量递增", result)
        self.assertIn("ADX-038", result)

    def test_reason_is_rebuilt_even_when_no_protected_dim_is_forced(self):
        """Reviewer-visible reason never preserves model-authored free text."""
        candidate = _candidate_input("NCT001")
        project = _project_facts_complete()
        dims = [_dim("indication", "match")]
        doc_suit = {"has_public_protocol": False, "has_public_sap": False}
        model_reason = "Same indication and mechanism."
        result = _sanitize_reason(
            model_reason, candidate, project, dims, doc_suit
        )
        self.assertNotEqual(model_reason, result)
        self.assertNotIn("mechanism", result)
        self.assertIn("无公开方案或统计分析计划", result)


# ---------------------------------------------------------------------------
# D. Direct competitor downgrade
# ---------------------------------------------------------------------------


class TestDirectCompetitorDowngrade(unittest.TestCase):
    def test_direct_downgraded_to_indirect_when_same_indication_drug(self):
        """Same indication + DRUG + project facts unknown → indirect_reference."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT001",
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )
        self.assertLessEqual(result_conf, 0.5)

    def test_direct_downgraded_to_excluded_when_different_indication(self):
        """Different indication DRUG + project facts unknown → excluded."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT002",
            conditions=["Acute Leukemia"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_direct_downgraded_to_excluded_when_device_same_indication(self):
        """Same indication DEVICE/PROCEDURE → excluded."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT003",
            interventions=[{"name": "device_x", "intervention_type": "DEVICE"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_direct_downgraded_to_indirect_when_intervention_type_unknown(self):
        """Same indication INTERVENTIONAL study with no explicit intervention
        types → indirect with lower confidence. Unknown does not prove a
        pharmacologic modality, but it also must not manufacture exclusion."""
        project = _project_facts_unknown()
        candidate = _candidate_input("NCT004")  # INTERVENTIONAL, no interventions
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )
        self.assertLessEqual(result_conf, 0.4)

    def test_direct_downgraded_to_excluded_when_missing_conditions(self):
        """Has DRUG intervention but no conditions → excluded (fail-closed)."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT005",
            conditions=[],  # empty conditions
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_excluded_is_reconciled_when_unknowns_are_only_exclusion_basis(self):
        """Same-indication drug + missing project facts cannot remain excluded."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT006",
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.EXCLUDED,
            0.3,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )
        self.assertLessEqual(result_conf, 0.5)

    def test_direct_preserved_when_all_facts_known(self):
        project = _project_facts_complete()
        candidate = _candidate_input(
            "NCT007",
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.DIRECT_COMPETITOR, result_cls
        )
        self.assertEqual(0.9, result_conf)

    # --- Round-04: partial-knowledge anti-examples ---

    def test_only_tech_known_still_downgrades(self):
        """Only technology_type known, route and target unknown → not direct."""
        project = {
            "indication": "Paroxysmal Nocturnal Hemoglobinuria",
            "clinicaltrials_condition_term": "Paroxysmal Nocturnal Hemoglobinuria",
            "target_mechanism": "",
            "product_profile": {
                "technology_type": "small_molecule",
                "administration_routes": [],
                "dosage_forms": [],
                "exposure_scope": "unknown",
            },
        }
        candidate = _candidate_input(
            "NCT010",
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_only_route_known_still_downgrades(self):
        """Only administration_route known, tech and target unknown → not direct."""
        project = {
            "indication": "Paroxysmal Nocturnal Hemoglobinuria",
            "clinicaltrials_condition_term": "Paroxysmal Nocturnal Hemoglobinuria",
            "target_mechanism": "",
            "product_profile": {
                "technology_type": "unknown",
                "administration_routes": ["oral"],
                "dosage_forms": [],
                "exposure_scope": "unknown",
            },
        }
        candidate = _candidate_input(
            "NCT011",
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_only_target_known_still_downgrades(self):
        """Only target_mechanism known, tech and route unknown → not direct."""
        project = {
            "indication": "Paroxysmal Nocturnal Hemoglobinuria",
            "clinicaltrials_condition_term": "Paroxysmal Nocturnal Hemoglobinuria",
            "target_mechanism": "Factor B inhibitor",
            "product_profile": {
                "technology_type": "unknown",
                "administration_routes": [],
                "dosage_forms": [],
                "exposure_scope": "unknown",
            },
        }
        candidate = _candidate_input(
            "NCT012",
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_only_target_known_different_indication_excluded(self):
        """Only target known, different indication → excluded."""
        project = {
            "indication": "Paroxysmal Nocturnal Hemoglobinuria",
            "clinicaltrials_condition_term": "Paroxysmal Nocturnal Hemoglobinuria",
            "target_mechanism": "Factor B inhibitor",
            "product_profile": {
                "technology_type": "unknown",
                "administration_routes": [],
                "dosage_forms": [],
                "exposure_scope": "unknown",
            },
        }
        candidate = _candidate_input(
            "NCT013",
            conditions=["Breast Cancer"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.DIRECT_COMPETITOR,
            0.9,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )


# ---------------------------------------------------------------------------
# E. Full validation integration with chunk_input
# ---------------------------------------------------------------------------


class TestFullValidationWithChunkInput(unittest.TestCase):
    def test_protocol_sap_overrides_model_false_in_full_validation(self):
        nct = "NCT00397813"
        candidate = _candidate_input(
            nct,
            docs=[{"document_type": "protocol_sap", "filename": "doc.pdf"}],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    has_protocol=False,  # model says false
                    has_sap=True,
                    reason="测试",
                    matching_dims=[
                        {"dimension": "indication", "match": "match", "detail": "同适应症"},
                    ],
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(1, len(results))
        doc = results[0].document_suitability
        self.assertTrue(doc.has_public_protocol)
        self.assertTrue(doc.has_public_sap)

    def test_protected_dims_forced_unknown_in_full_validation(self):
        nct = "NCT03896152"
        candidate = _candidate_input(
            nct,
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    reason="iptacopan为补体B因子抑制剂，口服给药。",
                    matching_dims=[
                        {"dimension": "route", "match": "match", "detail": "口服"},
                        {"dimension": "target_mechanism", "match": "match", "detail": "B因子"},
                    ],
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        r = results[0]
        dim_map = {d.dimension: d for d in r.matching_dimensions}
        self.assertEqual("unknown", dim_map["route"].match)
        self.assertEqual("unknown", dim_map["target_mechanism"].match)
        self.assertEqual("unknown", dim_map["modality"].match)
        # Reason must not contain unsourced claims
        self.assertNotIn("补体B因子抑制剂", r.reason)
        self.assertNotIn("口服", r.reason)

    def test_direct_downgraded_in_full_validation(self):
        nct = "NCT001"
        candidate = _candidate_input(
            nct,
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="direct_competitor",
                    confidence=0.95,
                    reason="Direct match.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            results[0].classification,
        )
        self.assertLessEqual(results[0].confidence, 0.5)

    def test_excluded_preserved_in_full_validation(self):
        nct = "NCT002"
        candidate = _candidate_input(
            nct,
            conditions=["Acute Leukemia"],  # different indication
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="excluded",
                    confidence=0.3,
                    reason="Different indication.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            results[0].classification,
        )


# ---------------------------------------------------------------------------
# F. Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility(unittest.TestCase):
    def test_old_two_arg_call_still_works(self):
        """Anti-example 8: _validate_chunk_response(response, expected_nct_ids) must work."""
        ncts = ["NCT00000001", "NCT00000002"]
        response = {
            "results": [
                _model_result("NCT00000001", classification="indirect_reference"),
                _model_result("NCT00000002", classification="excluded", confidence=0.3),
            ]
        }
        # Old signature: no chunk_input
        results = _validate_chunk_response(response, ncts)
        self.assertEqual(2, len(results))
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            results[0].classification,
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            results[1].classification,
        )

    def test_old_validation_tests_still_pass(self):
        """Verify that existing validation error tests still work without chunk_input."""
        ncts = ["NCT00000001"]
        response = {
            "results": [
                {
                    "nct_id": "NCT99999999",  # unknown NCT
                    "classification": "direct_competitor",
                    "confidence": 0.5,
                    "reason": "test",
                    "matching_dimensions": [],
                    "evidence_gaps": [],
                    "document_suitability": {},
                }
            ]
        }
        with self.assertRaisesRegex(
            CompetitorTriageError, "unknown nct_id"
        ):
            _validate_chunk_response(response, ncts)


# ---------------------------------------------------------------------------
# G. Round-02: reason consistency and full validation downgrade targeting
# ---------------------------------------------------------------------------


class TestReasonClassificationConsistency(unittest.TestCase):
    """The sanitized reason conclusion must match the final classification."""

    def test_indirect_reference_reason_says_drug_reference(self):
        """indirect_reference + same indication + DRUG → reason says drug reference."""
        candidate = _candidate_input(
            "NCT001",
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        project = _project_facts_unknown()
        dims = [
            _dim("indication", "match"),
            _dim("route", "unknown"),
            _dim("target_mechanism", "unknown"),
            _dim("modality", "unknown"),
        ]
        doc_suit = {"has_public_protocol": True, "has_public_sap": True}
        result = _sanitize_reason(
            "model reason with 补体B因子抑制剂 and 口服",
            candidate, project, dims, doc_suit,
            final_classification=CompetitorTriageClassification.INDIRECT_REFERENCE,
        )
        self.assertIn("同适应症药物研究参考", result)
        self.assertNotIn("不纳入竞品篮子", result)
        self.assertNotIn("补体B因子抑制剂", result)
        self.assertNotIn("口服", result)

    def test_excluded_reason_says_not_included(self):
        """excluded + different indication → reason says not included."""
        candidate = _candidate_input(
            "NCT002",
            conditions=["Acute Leukemia"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        project = _project_facts_unknown()
        dims = [
            _dim("indication", "mismatch"),
            _dim("route", "unknown"),
            _dim("target_mechanism", "unknown"),
            _dim("modality", "unknown"),
        ]
        doc_suit = {"has_public_protocol": False, "has_public_sap": False}
        result = _sanitize_reason(
            "model reason claiming direct match",
            candidate, project, dims, doc_suit,
            final_classification=CompetitorTriageClassification.EXCLUDED,
        )
        self.assertIn("不纳入竞品篮子", result)
        self.assertNotIn("同适应症药物研究参考", result)

    def test_excluded_reason_for_device_same_indication(self):
        """excluded + same indication + DEVICE → reason says not included."""
        candidate = _candidate_input(
            "NCT003",
            interventions=[{"name": "device_x", "intervention_type": "DEVICE"}],
        )
        project = _project_facts_unknown()
        dims = [
            _dim("indication", "match"),
            _dim("route", "unknown"),
            _dim("target_mechanism", "unknown"),
            _dim("modality", "unknown"),
        ]
        doc_suit = {"has_public_protocol": False, "has_public_sap": False}
        result = _sanitize_reason(
            "model reason",
            candidate, project, dims, doc_suit,
            final_classification=CompetitorTriageClassification.EXCLUDED,
        )
        self.assertIn("不纳入竞品篮子", result)
        self.assertNotIn("同适应症药物研究参考", result)


class TestFullValidationDowngradeTargeting(unittest.TestCase):
    """End-to-end: model direct_competitor correctly routed based on candidate."""

    def test_different_indication_drug_direct_becomes_excluded(self):
        """Round-02 anti-example: different indication DRUG → excluded, not indirect."""
        nct = "NCT100"
        candidate = _candidate_input(
            nct,
            conditions=["Breast Cancer"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="direct_competitor",
                    confidence=0.95,
                    reason="Direct competitor.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            results[0].classification,
        )
        self.assertNotIn("同适应症药物研究参考", results[0].reason)

    def test_same_indication_device_direct_becomes_excluded(self):
        """Round-02 anti-example: same indication DEVICE → excluded."""
        nct = "NCT101"
        candidate = _candidate_input(
            nct,
            interventions=[{"name": "device_x", "intervention_type": "DEVICE"}],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="direct_competitor",
                    confidence=0.9,
                    reason="Direct competitor device.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            results[0].classification,
        )

    def test_same_indication_drug_direct_becomes_indirect(self):
        """Round-02 anti-example: same indication DRUG, facts unknown → indirect."""
        nct = "NCT102"
        candidate = _candidate_input(
            nct,
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="direct_competitor",
                    confidence=0.9,
                    reason="Direct match.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            results[0].classification,
        )
        self.assertIn("同适应症药物研究参考", results[0].reason)

    def test_missing_intervention_types_direct_becomes_indirect(self):
        """Unknown intervention type blocks direct but does not force exclusion."""
        nct = "NCT103"
        candidate = _candidate_input(nct)  # INTERVENTIONAL, no interventions
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="direct_competitor",
                    confidence=0.9,
                    reason="Direct match.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            results[0].classification,
        )
        self.assertIn("候选干预类型待核实", results[0].reason)
        self.assertNotIn("同适应症药物研究参考", results[0].reason)

    def test_unsupported_excluded_promoted_in_full_validation(self):
        """Same-indication DRUG + unknown project facts → indirect_reference."""
        nct = "NCT104"
        candidate = _candidate_input(
            nct,
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="excluded",
                    confidence=0.2,
                    reason="Already excluded.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            results[0].classification,
        )
        self.assertIn("同适应症药物研究参考", results[0].reason)

    def test_project_drug_name_does_not_invent_candidate_intervention_type(self):
        """Round-05 anti-example: even when the project name/dosage form
        signals a drug study (e.g. '注射液'), the candidate intervention type
        remains unknown. It may be retained indirectly, but the reason must not
        relabel it as a pharmacologic study."""
        nct = "NCT105"
        candidate = _candidate_input(nct)  # INTERVENTIONAL, no interventions
        # Project that clearly identifies as a drug study by name
        project = {
            "investigational_product": "CMS-RA-201注射液",
            "indication": "Paroxysmal Nocturnal Hemoglobinuria",
            "clinicaltrials_condition_term": "Paroxysmal Nocturnal Hemoglobinuria",
            "target_mechanism": "Factor B inhibitor",
            "product_profile": {
                "technology_type": "unknown",
                "administration_routes": [],
                "dosage_forms": ["注射液"],
                "exposure_scope": "unknown",
            },
        }
        chunk_input = {
            "project_facts": project,
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="direct_competitor",
                    confidence=0.9,
                    reason="Direct match.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            results[0].classification,
        )
        self.assertIn("候选干预类型待核实", results[0].reason)
        self.assertNotIn("同适应症药物研究参考", results[0].reason)


# ---------------------------------------------------------------------------
# H. Round-06: indirect_reference re-validation + indication matching
# ---------------------------------------------------------------------------


class TestIndirectReferenceRevalidation(unittest.TestCase):
    """Model indirect_reference must also verify same indication + pharmacologic."""

    def test_indirect_different_indication_drug_becomes_excluded(self):
        """Original indirect + different indication + DRUG → excluded."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT200",
            conditions=["Breast Cancer"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_indirect_same_indication_device_becomes_excluded(self):
        """Original indirect + same indication + DEVICE → excluded."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT201",
            interventions=[{"name": "device_x", "intervention_type": "DEVICE"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_indirect_same_indication_missing_type_stays_indirect(self):
        """Original indirect + same indication + unknown type stays indirect."""
        project = _project_facts_unknown()
        candidate = _candidate_input("NCT202")  # no interventions
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )
        self.assertLessEqual(result_conf, 0.6)

    def test_indirect_same_indication_drug_stays_indirect(self):
        """Original indirect + same indication + DRUG → indirect_reference."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT203",
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_indirect_pnh_abbreviation_stays_indirect(self):
        """Original indirect + PNH condition + DRUG → indirect."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT204",
            conditions=["PNH"],
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_indirect_word_order_variant_stays_indirect(self):
        """Original indirect + reordered condition name + DRUG → indirect."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT205",
            conditions=["Paroxysmal Hemoglobinuria, Nocturnal"],
            interventions=[{"name": "iptacopan", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_short_word_does_not_false_match(self):
        """Short/generic words must not create false indication match."""
        project = _project_facts_unknown()
        # "Hemoglobinuria" alone is too short to match if project says PNH
        candidate = _candidate_input(
            "NCT206",
            conditions=["Hemoglobinuria"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, result_conf = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        # Should be excluded — insufficient token overlap
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_chinese_pnh_english_candidate_reason_says_consistent(self):
        """Chinese PNH project + English candidate → reason says 适应症一致."""
        nct = "NCT207"
        candidate = _candidate_input(
            nct,
            interventions=[{"name": "danicopan", "intervention_type": "DRUG"}],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="indirect_reference",
                    confidence=0.8,
                    reason="indirect reference with 口服 route claim.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        r = results[0]
        # Must say 适应症一致, NOT 适应症不同
        self.assertIn("适应症一致", r.reason)
        self.assertNotIn("适应症不同", r.reason)
        self.assertNotIn("口服", r.reason)

    def test_cross_language_equivalence_requires_literal_source_strings(self):
        """Chinese-only project facts may be matched to English registry facts,
        but only when the independent AI quotes both literal disease names."""
        nct = "NCT207A"
        project = _project_facts_unknown()
        project["indication"] = "阵发性睡眠性血红蛋白尿症"
        project["clinicaltrials_condition_term"] = ""
        condition = "Paroxysmal Nocturnal Hemoglobinuria (PNH)"
        candidate = _candidate_input(
            nct,
            conditions=[condition],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        candidate["project_indication_relation"] = "none"
        candidate["project_indication_match"] = False
        candidate["project_indication_relation_scope"] = (
            "cross_language_unresolved"
        )
        result = _validate_chunk_response(
            {
                "results": [
                    _model_result(
                        nct,
                        classification="indirect_reference",
                        confidence=0.8,
                        matching_dims=[
                            {
                                "dimension": "indication",
                                "match": "match",
                                "detail": (
                                    "项目适应症阵发性睡眠性血红蛋白尿症与候选"
                                    "登记条件Paroxysmal Nocturnal Hemoglobinuria "
                                    "(PNH)为标准中英文疾病名称，二者等价"
                                ),
                            }
                        ],
                    )
                ]
            },
            [nct],
            chunk_input={"project_facts": project, "candidates": [candidate]},
        )[0]
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            result.classification,
        )
        self.assertIn("适应症一致", result.reason)
        self.assertEqual(
            "match",
            next(
                dim.match
                for dim in result.matching_dimensions
                if dim.dimension == "indication"
            ),
        )

    def test_cross_language_claim_without_literal_candidate_condition_fails_closed(self):
        nct = "NCT207B"
        project = _project_facts_unknown()
        project["indication"] = "阵发性睡眠性血红蛋白尿症"
        project["clinicaltrials_condition_term"] = ""
        candidate = _candidate_input(
            nct,
            conditions=["Paroxysmal Nocturnal Hemoglobinuria (PNH)"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        candidate["project_indication_relation"] = "none"
        candidate["project_indication_match"] = False
        candidate["project_indication_relation_scope"] = (
            "cross_language_unresolved"
        )
        result = _validate_chunk_response(
            {
                "results": [
                    _model_result(
                        nct,
                        classification="indirect_reference",
                        confidence=0.8,
                        matching_dims=[
                            {
                                "dimension": "indication",
                                "match": "match",
                                "detail": "项目适应症阵发性睡眠性血红蛋白尿症与PNH一致",
                            }
                        ],
                    )
                ]
            },
            [nct],
            chunk_input={"project_facts": project, "candidates": [candidate]},
        )[0]
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            result.classification,
        )
        self.assertIn("适应症不同", result.reason)

    def test_model_document_role_with_route_not_preserved(self):
        """Model document_role containing '口服补体抑制剂' must be replaced
        with deterministic label."""
        nct = "NCT208"
        candidate = _candidate_input(
            nct,
            interventions=[{"name": "danicopan", "intervention_type": "DRUG"}],
            docs=[
                {"document_type": "protocol", "filename": "p.pdf"},
                {"document_type": "sap", "filename": "s.pdf"},
            ],
        )
        chunk_input = {
            "project_facts": _project_facts_unknown(),
            "candidates": [candidate],
        }
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="indirect_reference",
                    confidence=0.8,
                    document_role="可用于参考口服补体抑制剂的设计",
                    reason="reference study.",
                )
            ]
        }
        results = _validate_chunk_response(
            response, [nct], chunk_input=chunk_input
        )
        doc = results[0].document_suitability
        self.assertNotIn("口服", doc.document_role)
        self.assertNotIn("补体", doc.document_role)
        self.assertEqual("已提供公开方案与统计分析计划", doc.document_role)


# ---------------------------------------------------------------------------
# I. Round-07: abbreviation false-match fix + indirect always re-validated
# ---------------------------------------------------------------------------


class TestAbbreviationAndIndirectRevalidation(unittest.TestCase):
    """Round-07: proven abbreviation matching + indirect always re-validated."""

    def test_common_word_severe_does_not_match(self):
        """Sharing the word 'severe' must not create a false indication match."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT300",
            conditions=["Severe Asthma"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_common_word_chronic_does_not_match(self):
        """Sharing the word 'chronic' must not create a false indication match."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT301",
            conditions=["Chronic Kidney Disease"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_common_word_disease_does_not_match(self):
        """Sharing the word 'disease' must not create a false indication match."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT302",
            conditions=["Crohn's Disease"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_standalone_pnh_matches_project_abbreviation(self):
        """Candidate condition 'PNH' matches project '（PNH）' abbreviation."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT303",
            conditions=["PNH"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_candidate_paren_pnh_matches_project_paren_pnh(self):
        """Candidate '(PNH)' matches project '（PNH）'."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT304",
            conditions=["Paroxysmal Nocturnal Hemoglobinuria (PNH)"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_word_order_variant_matches(self):
        """'Paroxysmal Hemoglobinuria, Nocturnal' matches 'Paroxysmal Nocturnal
        Hemoglobinuria' via token overlap."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT305",
            conditions=["Paroxysmal Hemoglobinuria, Nocturnal"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_all_facts_known_indirect_different_indiction_excluded(self):
        """All project facts known + indirect + different indication DRUG → excluded."""
        project = _project_facts_complete()
        candidate = _candidate_input(
            "NCT306",
            conditions=["Breast Cancer"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_all_facts_known_indirect_device_excluded(self):
        """All project facts known + indirect + same indication DEVICE → excluded."""
        project = _project_facts_complete()
        candidate = _candidate_input(
            "NCT307",
            conditions=["Rheumatoid Arthritis"],
            interventions=[{"name": "device_x", "intervention_type": "DEVICE"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_all_facts_known_indirect_missing_type_stays_indirect(self):
        """Unknown candidate type does not override an otherwise valid indirect."""
        project = _project_facts_complete()
        candidate = _candidate_input(
            "NCT308",
            conditions=["Rheumatoid Arthritis"],
        )  # no interventions
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_all_facts_known_indirect_same_indication_drug_stays(self):
        """All project facts known + indirect + same indication DRUG → indirect."""
        project = _project_facts_complete()
        candidate = _candidate_input(
            "NCT309",
            conditions=["Rheumatoid Arthritis"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )


# ---------------------------------------------------------------------------
# J. Round-08: remove fuzzy token overlap — exact-set or abbreviation only
# ---------------------------------------------------------------------------


class TestExactSetOrAbbreviationOnly(unittest.TestCase):
    """Round-08: no fuzzy token overlap; exact token-set or proven abbreviation."""

    def test_pnh_vs_dyspnea_no_match(self):
        """PNH project vs 'Paroxysmal Nocturnal Dyspnea' must NOT match."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT400",
            conditions=["Paroxysmal Nocturnal Dyspnea"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_ra_vs_rheumatoid_lung_no_match(self):
        """RA project vs 'Rheumatoid Lung Disease' must NOT match."""
        project = _project_facts_complete()
        candidate = _candidate_input(
            "NCT401",
            conditions=["Rheumatoid Lung Disease"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED, result_cls
        )

    def test_word_order_variant_still_matches(self):
        """'Paroxysmal Hemoglobinuria, Nocturnal' vs 'Paroxysmal Nocturnal
        Hemoglobinuria' — exact token-set equivalence handles word order."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT402",
            conditions=["Paroxysmal Hemoglobinuria, Nocturnal"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_standalone_pnh_matches(self):
        """Candidate 'PNH' matches project '（PNH）' abbreviation."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT403",
            conditions=["PNH"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_candidate_paren_pnh_matches(self):
        """Candidate '(PNH)' matches project '（PNH）'."""
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT404",
            conditions=["Paroxysmal Nocturnal Hemoglobinuria (PNH)"],
            interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
        )
        result_cls, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.8,
            project,
            candidate,
            "reason",
        )
        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
        )

    def test_strict_dash_alias_pairs_match_when_full_name_is_exact(self):
        project = _project_facts_unknown()
        for nct_id, condition in (
            ("NCT05731050", "PNH - Paroxysmal Nocturnal Hemoglobinuria"),
            ("NCT06978699", "Paroxysmal Nocturnal Hemoglobinuria - PNH"),
            ("NCT07212426", "PNH - Paroxysmal Nocturnal Hemoglobinuria"),
        ):
            with self.subTest(nct_id=nct_id):
                candidate = _candidate_input(
                    nct_id,
                    conditions=[condition],
                    interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
                )
                result_cls, _ = _enforce_classification_eligibility(
                    CompetitorTriageClassification.INDIRECT_REFERENCE,
                    0.8,
                    project,
                    candidate,
                    "reason",
                )
                self.assertEqual(
                    CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
                )

    def test_v8_d017_orthography_and_controlled_subgroup_matches(self):
        project = _project_facts_unknown()
        conditions_by_nct = (
            ("NCT02591862", "Paroxysmal Nocturnal Haemoglobinuria"),
            (
                "NCT03439839",
                "Paroxysmal Nocturnal Hemoglobinuria (PNH) "
                "With Signs of Active Hemolysis",
            ),
            (
                "NCT03439840",
                "Paroxysmal Nocturnal Haemoglobinuria "
                "With Signs of Active Haemolysis",
            ),
        )
        for nct_id, condition in conditions_by_nct:
            with self.subTest(nct_id=nct_id):
                candidate = _candidate_input(
                    nct_id,
                    conditions=[condition],
                    interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
                )
                result_cls, _ = _enforce_classification_eligibility(
                    CompetitorTriageClassification.INDIRECT_REFERENCE,
                    0.8,
                    project,
                    candidate,
                    "reason",
                )
                self.assertEqual(
                    CompetitorTriageClassification.INDIRECT_REFERENCE, result_cls
                )

    def test_alias_false_positive_counterexamples_remain_excluded(self):
        project = _project_facts_unknown()
        conditions = (
            "PNH - Paroxysmal Nocturnal Dyspnea",
            "Malignant Hematology - PNH",
            "PNH-related Bone Marrow Failure",
            "Paroxysmal Nocturnal Dyspnea (PNH)",
            "PNH - Paroxysmal Nocturnal Hemoglobinuria - Other Disease",
            "Paroxysmal Nocturnal Hemoglobinuria and Aplastic Anemia",
            "Paroxysmal Nocturnal Hemoglobinuria or Aplastic Anemia",
            (
                "Paroxysmal Nocturnal Hemoglobinuria With Active Hemolysis "
                "and Aplastic Anemia"
            ),
            (
                "Paroxysmal Nocturnal Hemoglobinuria With Active Hemolysis "
                "or Aplastic Anemia"
            ),
            "Paroxysmal Nocturnal Hemoglobinuria (XYZ) With Active Hemolysis",
            "PNH - Paroxysmal Nocturnal Hemoglobinuria - Active Hemolysis",
        )
        for index, condition in enumerate(conditions, start=1):
            with self.subTest(condition=condition):
                candidate = _candidate_input(
                    f"NCT418{index}",
                    conditions=[condition],
                    interventions=[{"name": "drug_x", "intervention_type": "DRUG"}],
                )
                result_cls, _ = _enforce_classification_eligibility(
                    CompetitorTriageClassification.INDIRECT_REFERENCE,
                    0.8,
                    project,
                    candidate,
                    "reason",
                )
                self.assertEqual(
                    CompetitorTriageClassification.EXCLUDED, result_cls
                )


# ---------------------------------------------------------------------------
# K. Round-11: v11 run identity — version bump produces new canonical hash
# ---------------------------------------------------------------------------


class TestCurrentRunIdentity(unittest.TestCase):
    """Current evidence-bound prompt creates a distinct run identity."""

    def test_prompt_version_is_v20(self):
        self.assertEqual(
            "competitor_triage_v20_derived_full_name_abbreviations",
            TRIAGE_PROMPT_VERSION,
        )

    def test_provider_model_unchanged(self):
        self.assertEqual("deepseek", TRIAGE_PROVIDER_NAME)
        self.assertEqual("deepseek-v4-pro", TRIAGE_MODEL_NAME)

    def test_v13_and_v14_canonical_hashes_differ(self):
        """Same snapshot/facts but different prompt_version → different hash."""
        base = {
            "snapshot_id": "wref_search_test",
            "snapshot_hash": "abc123",
            "material_facts_hash": "def456",
            "schema_version": "competitor_triage_v1",
            "chunks": [{"chunk_index": 0, "input_hash": "chunk_hash_0"}],
        }
        v13_hash = _hash_value({
            **base,
            "prompt_version": (
                "competitor_triage_deepseek_v13_controlled_condition_qualifiers"
            ),
        })
        v14_hash = _hash_value({
            **base,
            "prompt_version": TRIAGE_PROMPT_VERSION,
        })
        self.assertNotEqual(v13_hash, v14_hash)

    def test_v13_and_v14_run_ids_differ(self):
        """Different canonical hash → different run_id prefix."""
        base = {
            "snapshot_id": "wref_search_test",
            "snapshot_hash": "abc123",
            "material_facts_hash": "def456",
            "schema_version": "competitor_triage_v1",
            "chunks": [],
        }
        v13_hash = _hash_value({
            **base,
            "prompt_version": (
                "competitor_triage_deepseek_v13_controlled_condition_qualifiers"
            ),
        })
        v14_hash = _hash_value({
            **base,
            "prompt_version": TRIAGE_PROMPT_VERSION,
        })
        self.assertNotEqual(
            f"ct_run_{v13_hash[:20]}",
            f"ct_run_{v14_hash[:20]}",
        )

    def test_chunk_input_uses_v20_run_identity(self):
        """The canonical chunk input envelope carries the v20 version via
        the system prompt that references TRIAGE_PROMPT_VERSION."""
        # The prompt version enters the run record and provenance, not the
        # chunk_input dict directly.  But the system prompt is built from
        # the same constant.  Verify the constant is accessible and correct.
        self.assertIn("v20", TRIAGE_PROMPT_VERSION)


# ---------------------------------------------------------------------------
# L. Source-truth indication reconciliation and reviewer-text safeguards
# ---------------------------------------------------------------------------


class TestV6SourceTruthReconciliation(unittest.TestCase):
    def test_authoritative_indication_bool_precedes_truncated_conditions(self):
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT600",
            conditions=[
                "Acute Myeloid Leukemia",
                "Myelodysplastic Syndromes",
                "Multiple Myeloma",
                "Diffuse Large B-Cell Lymphoma",
                "Chronic Lymphocytic Leukemia",
            ],
        )
        candidate.update(
            {
                "condition_count": 7,
                "matching_conditions": [
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ],
                "project_indication_match": True,
            }
        )

        self.assertTrue(
            _candidate_indication_matches_project(candidate, project)
        )

    def test_authoritative_false_prevents_false_match(self):
        project = _project_facts_unknown()
        candidate = _candidate_input(
            "NCT601",
            conditions=["Paroxysmal Nocturnal Hemoglobinuria"],
        )
        candidate.update(
            {
                "condition_count": 8,
                "matching_conditions": [],
                "project_indication_match": False,
            }
        )

        self.assertFalse(
            _candidate_indication_matches_project(candidate, project)
        )

    def test_full_validation_keeps_hidden_pnh_match_and_removes_model_claims(self):
        nct = "NCT602"
        project = _project_facts_unknown()
        candidate = _candidate_input(
            nct,
            conditions=[
                "Acute Myeloid Leukemia",
                "Myelodysplastic Syndromes",
                "Multiple Myeloma",
                "Diffuse Large B-Cell Lymphoma",
                "Chronic Lymphocytic Leukemia",
            ],
            phases=["PHASE3"],
            interventions=[{"name": "Study Drug", "intervention_type": "DRUG"}],
            design_allocation="RANDOMIZED",
            design_intervention_model="PARALLEL",
            design_masking="DOUBLE",
        )
        candidate.update(
            {
                "condition_count": 7,
                "matching_conditions": [
                    "Paroxysmal Nocturnal Hemoglobinuria"
                ],
                "project_indication_match": True,
            }
        )
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="indirect_reference",
                    confidence=0.9,
                    reason="该口服小分子采用SAD/MAD剂量递增设计。",
                    matching_dims=[
                        {
                            "dimension": "indication",
                            "match": "mismatch",
                            "detail": "恶性血液病，与PNH不一致",
                        },
                        {
                            "dimension": "phase",
                            "match": "partial",
                            "detail": "I期剂量递增研究",
                        },
                        {
                            "dimension": "design",
                            "match": "match",
                            "detail": "SAD/MAD剂量递增设计",
                        },
                    ],
                    evidence_gaps=[
                        "该口服小分子的剂量递增队列尚未核实"
                    ],
                )
            ]
        }

        result = _validate_chunk_response(
            response,
            [nct],
            chunk_input={
                "project_facts": project,
                "candidates": [candidate],
            },
        )[0]
        dimensions = {
            item.dimension: item for item in result.matching_dimensions
        }
        reviewer_text = " ".join(
            [
                result.reason,
                *[item.detail for item in result.matching_dimensions],
                *result.evidence_gaps,
            ]
        )

        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            result.classification,
        )
        self.assertEqual("partial", dimensions["indication"].match)
        self.assertEqual("mismatch", dimensions["phase"].match)
        self.assertEqual("unknown", dimensions["design"].match)
        self.assertIn(
            "Paroxysmal Nocturnal Hemoglobinuria",
            dimensions["indication"].detail,
        )
        self.assertIn("可作为同适应症药物研究参考", result.reason)
        for unsupported in ("口服", "小分子", "SAD", "MAD", "剂量递增"):
            self.assertNotIn(unsupported, reviewer_text)
        self.assertEqual(
            [
                "当前项目及候选均未提供技术类型信息，不能判断匹配性",
                "当前项目及候选均未提供给药途径信息，不能判断匹配性",
                "当前项目及候选均未提供靶点/机制信息，不能判断匹配性",
            ],
            result.evidence_gaps,
        )

    def test_full_validation_without_full_condition_match_is_excluded(self):
        nct = "NCT603"
        project = _project_facts_unknown()
        candidate = _candidate_input(
            nct,
            conditions=[
                "Acute Myeloid Leukemia",
                "Myelodysplastic Syndromes",
                "Multiple Myeloma",
                "Diffuse Large B-Cell Lymphoma",
                "Chronic Lymphocytic Leukemia",
            ],
            interventions=[{"name": "Study Drug", "intervention_type": "DRUG"}],
        )
        candidate.update(
            {
                "condition_count": 8,
                "matching_conditions": [],
                "project_indication_match": False,
            }
        )
        response = {
            "results": [
                _model_result(
                    nct,
                    classification="indirect_reference",
                    confidence=0.9,
                    reason="模型声称这是PNH同适应症口服小分子研究。",
                    matching_dims=[
                        {
                            "dimension": "indication",
                            "match": "match",
                            "detail": "PNH匹配",
                        }
                    ],
                )
            ]
        }

        result = _validate_chunk_response(
            response,
            [nct],
            chunk_input={
                "project_facts": project,
                "candidates": [candidate],
            },
        )[0]
        indication = next(
            item
            for item in result.matching_dimensions
            if item.dimension == "indication"
        )

        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            result.classification,
        )
        self.assertEqual("mismatch", indication.match)
        self.assertIn("不纳入竞品篮子", result.reason)
        self.assertNotIn("口服", result.reason)
        self.assertNotIn("小分子", result.reason)


if __name__ == "__main__":
    unittest.main()
