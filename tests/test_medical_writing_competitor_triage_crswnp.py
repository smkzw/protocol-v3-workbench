"""Focused CRSwNP scientific-logic regressions for competitor triage."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from packages.contracts.workbench_contracts import (
    CompetitorTriageClassification,
)
from services.api.app.medical_writing_competitor_triage import (
    _candidate_indication_matches_project,
    _enforce_classification_eligibility,
    _reconcile_source_truth_dimensions,
    _validate_chunk_response,
)


def _crswnp_project(*, complete_critical_facts: bool = False) -> Dict[str, Any]:
    return {
        "investigational_product": "MG-K10",
        "indication": "慢性鼻窦炎伴鼻息肉",
        "clinicaltrials_condition_term": "CRSwNP",
        "study_phase": "III期",
        "target_mechanism": (
            "IL-4R alpha inhibitor" if complete_critical_facts else "全部"
        ),
        "product_profile": {
            "technology_type": (
                "monoclonal_antibody"
                if complete_critical_facts
                else "unknown"
            ),
            "administration_routes": (
                ["subcutaneous"] if complete_critical_facts else []
            ),
            "dosage_forms": [],
            "exposure_scope": "unknown",
        },
        "design_pattern": "随机、双盲、安慰剂对照",
        "picos": {},
    }


def _candidate(
    nct_id: str,
    *,
    conditions: List[str],
    official_title: str = "",
    brief_title: str = "",
    interventions: List[Dict[str, str]] | None = None,
    documents: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    return {
        "nct_id": nct_id,
        "official_title": official_title,
        "brief_title": brief_title,
        "conditions": conditions,
        "condition_count": len(conditions),
        "matching_conditions": [],
        "phases": ["PHASE3"],
        "study_type": "INTERVENTIONAL",
        "brief_summary": "",
        "interventions": interventions or [],
        "design_allocation": "",
        "design_intervention_model": "",
        "design_masking": "",
        "enrollment_count": None,
        "lead_sponsor": "Test Sponsor",
        "overall_status": "COMPLETED",
        "public_documents": documents or [],
    }


def _excluded_model_result(nct_id: str) -> Dict[str, Any]:
    return {
        "nct_id": nct_id,
        "classification": "excluded",
        "confidence": 0.95,
        "reason": "适应症不同，且项目技术类型、给药途径和靶点未知。",
        "matching_dimensions": [
            {
                "dimension": "indication",
                "match": "mismatch",
                "detail": "适应症不同",
            }
        ],
        "evidence_gaps": [
            "模型声称未知项目事实意味着应排除",
        ],
        "document_suitability": {
            "has_public_protocol": False,
            "has_public_sap": False,
            "document_role": "",
        },
    }


class TestControlledCrswnpConditionEquivalence(unittest.TestCase):
    def test_exact_medical_aliases_match(self):
        project = _crswnp_project()
        cases = (
            ["Chronic Rhinosinusitis Phenotype With Nasal Polyps (CRSwNP)"],
            ["Chronic Rhinosinusitis With Nasal Polyps"],
            ["Chronic Rhinosinusitis With Nasal Polyposis"],
            ["CRSwNP"],
            ["慢性鼻窦炎伴鼻息肉"],
            ["慢性鼻-鼻窦炎合并鼻息肉"],
            ["Chronic Sinusitis", "Nasal Polyps"],
            ["Chronic Rhinosinusitis", "Nasal Polyps"],
        )
        for index, conditions in enumerate(cases, start=1):
            with self.subTest(conditions=conditions):
                self.assertTrue(
                    _candidate_indication_matches_project(
                        _candidate(
                            f"NCT8100000{index}",
                            conditions=conditions,
                        ),
                        project,
                    )
                )

    def test_isolated_nasal_polyps_requires_authoritative_corroboration(self):
        project = _crswnp_project()
        isolated = _candidate(
            "NCT82000001",
            conditions=["Nasal Polyps"],
            official_title="A Phase III Study in Adults With Nasal Polyps",
        )
        corroborated = _candidate(
            "NCT82000002",
            conditions=["Nasal Polyps"],
            official_title=(
                "A Phase III Study in Adults With Chronic Rhinosinusitis "
                "With Nasal Polyps (CRSwNP)"
            ),
        )

        self.assertFalse(
            _candidate_indication_matches_project(isolated, project)
        )
        self.assertTrue(
            _candidate_indication_matches_project(corroborated, project)
        )

    def test_generic_sinusitis_and_polyps_requires_exact_title_corroboration(self):
        project = _crswnp_project()
        uncorroborated = _candidate(
            "NCT82500001",
            conditions=["Sinusitis", "Nasal Polyps"],
            official_title="A Phase III Study in Adults With Sinusitis",
        )
        official_title_corroborated = _candidate(
            "NCT06639295",
            conditions=["Sinusitis", "Nasal Polyps"],
            official_title=(
                "A Phase III Study in Patients With Chronic Rhinosinusitis "
                "With Nasal Polyps (CRSwNP)"
            ),
        )
        brief_title_corroborated = _candidate(
            "NCT82500003",
            conditions=["Sinusitis", "Nasal Polyps"],
            brief_title=(
                "Chronic Rhinosinusitis With Nasal Polyps Phase III Study"
            ),
        )
        acute_with_title = _candidate(
            "NCT82500004",
            conditions=["Acute Sinusitis", "Nasal Polyps"],
            official_title=(
                "A Study of Chronic Rhinosinusitis With Nasal Polyps"
            ),
        )

        self.assertFalse(
            _candidate_indication_matches_project(uncorroborated, project)
        )
        self.assertTrue(
            _candidate_indication_matches_project(
                official_title_corroborated,
                project,
            )
        )
        self.assertTrue(
            _candidate_indication_matches_project(
                brief_title_corroborated,
                project,
            )
        )
        self.assertFalse(
            _candidate_indication_matches_project(acute_with_title, project)
        )

    def test_disease_subset_and_relation_false_positives_do_not_match(self):
        project = _crswnp_project()
        cases = (
            ["Nasal Polyps"],
            ["Chronic Rhinosinusitis"],
            ["Sinusitis", "Nasal Polyps"],
            ["Acute Sinusitis", "Nasal Polyps"],
            ["Asthma", "Nasal Polyps"],
            ["Chronic Rhinosinusitis Without Nasal Polyps"],
            ["Chronic Rhinitis With Nasal Polyps"],
        )
        for index, conditions in enumerate(cases, start=1):
            with self.subTest(conditions=conditions):
                self.assertFalse(
                    _candidate_indication_matches_project(
                        _candidate(
                            f"NCT8300000{index}",
                            conditions=conditions,
                        ),
                        project,
                    )
                )

    def test_real_registry_typo_requires_bounded_title_corroboration(self):
        project = _crswnp_project()
        candidate = _candidate(
            "NCT02665806",
            conditions=["Chronic Rhinosinustis With Polyps"],
            official_title=(
                "Ciclesonide vs Fluticasone Propionate Nasal Sprays in "
                "Patients With Nasal Poplyposis; a Randomized Clinical Trial"
            ),
            interventions=[
                {"name": "Ciclesonide", "intervention_type": "DRUG"},
            ],
        )
        uncorroborated = _candidate(
            "NCT82665806",
            conditions=["Chronic Rhinosinustis With Polyps"],
            official_title="A Study in Patients With Gastrointestinal Polyps",
        )

        self.assertTrue(
            _candidate_indication_matches_project(candidate, project)
        )
        self.assertFalse(
            _candidate_indication_matches_project(uncorroborated, project)
        )

    def test_real_single_condition_label_composes_crs_and_nasal_polyposis(self):
        candidate = _candidate(
            "NCT03323866",
            conditions=[
                "Chronic Rhinosinusitis (Diagnosis), Nasal Polyposis"
            ],
            official_title=(
                "Randomized Study in Patients With Chronic Rhinosinusitis "
                "With Nasal Polyposis"
            ),
            interventions=[
                {"name": "Budesonide", "intervention_type": "DRUG"},
            ],
        )

        self.assertTrue(
            _candidate_indication_matches_project(
                candidate,
                _crswnp_project(),
            )
        )

    def test_real_crs_condition_accepts_only_controlled_title_corroboration(self):
        project = _crswnp_project()
        corroborated = _candidate(
            "NCT02285283",
            conditions=["Chronic Rhinosinusitis"],
            official_title=(
                "Randomized Trial for Fungal Sensitive Chronic "
                "Rhinosinusitis With Nasal Polyps"
            ),
        )
        unrelated_polyp_title = _candidate(
            "NCT82285283",
            conditions=["Chronic Rhinosinusitis"],
            official_title=(
                "Chronic Rhinosinusitis Study With a History of Colonic Polyps"
            ),
        )

        self.assertTrue(
            _candidate_indication_matches_project(corroborated, project)
        )
        self.assertFalse(
            _candidate_indication_matches_project(
                unrelated_polyp_title,
                project,
            )
        )

    def test_real_mixed_crswnp_populations_match_but_are_not_direct(self):
        project = _crswnp_project(complete_critical_facts=True)
        candidates = (
            _candidate(
                "NCT01623323",
                conditions=[
                    "Chronic Sinusitis With or Without Nasal Polyps"
                ],
                interventions=[
                    {
                        "name": "Fluticasone Propionate",
                        "intervention_type": "DRUG",
                    },
                ],
            ),
            _candidate(
                "NCT03781804",
                conditions=["Chronic Rhinosinusitis"],
                official_title=(
                    "Study in Subjects With Chronic Rhinosinusitis With or "
                    "Without the Presence of Nasal Polyps"
                ),
                interventions=[
                    {"name": "OPN-375", "intervention_type": "DRUG"},
                ],
            ),
            _candidate(
                "NCT05248997",
                conditions=[
                    "Chronic Rhinosinusitis (CRS) With and Without Nasal Polyps"
                ],
                official_title=(
                    "Trial for Chronic Rhinosinusitis (CRS) With or Without "
                    "Nasal Polyps"
                ),
                interventions=[
                    {"name": "Rimegepant", "intervention_type": "DRUG"},
                ],
            ),
        )

        for candidate in candidates:
            with self.subTest(nct_id=candidate["nct_id"]):
                self.assertTrue(
                    _candidate_indication_matches_project(candidate, project)
                )
                classification, confidence = (
                    _enforce_classification_eligibility(
                        CompetitorTriageClassification.DIRECT_COMPETITOR,
                        0.95,
                        project,
                        candidate,
                        "model direct",
                    )
                )
                self.assertEqual(
                    CompetitorTriageClassification.INDIRECT_REFERENCE,
                    classification,
                )
                self.assertLessEqual(confidence, 0.75)

                dimensions = _reconcile_source_truth_dimensions(
                    [],
                    candidate,
                    project,
                )
                indication = next(
                    item
                    for item in dimensions
                    if item.dimension == "indication"
                )
                self.assertEqual("partial", indication.match)
                self.assertIn("包含CRSwNP人群", indication.detail)

    def test_distinct_allergic_fungal_rhinosinusitis_does_not_compose_to_crswnp(self):
        project = _crswnp_project()
        candidate = _candidate(
            "NCT06461949",
            conditions=[
                "Allergic Fungal Rhinosinusitis (AFRS)",
                "Chronic Rhinosinusitis (CRS)",
                "Asthma",
                "Nasal Polyps",
            ],
            official_title=(
                "A Study of Dupilumab After Endoscopic Sinus Surgery in "
                "Patients With Allergic Fungal Rhinosinusitis"
            ),
            interventions=[
                {"name": "Dupilumab", "intervention_type": "DRUG"},
            ],
        )

        self.assertFalse(
            _candidate_indication_matches_project(candidate, project)
        )
        classification, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.EXCLUDED,
            0.95,
            project,
            candidate,
            "model excluded",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            classification,
        )

    def test_real_without_nasal_polyps_and_non_pharmacologic_remain_excluded(self):
        project = _crswnp_project()
        without_polyps = (
            _candidate(
                "NCT03960580",
                conditions=["Chronic Rhinosinusitis"],
                official_title=(
                    "Study in Subjects With Chronic Rhinosinusitis Without "
                    "the Presence of Nasal Polyps"
                ),
                interventions=[
                    {"name": "OPN-375", "intervention_type": "DRUG"},
                ],
            ),
            _candidate(
                "NCT04678856",
                conditions=["Chronic Rhinosinusitis Without Nasal Polyps"],
                official_title=(
                    "Study in Chronic Rhinosinusitis Without Nasal Polyposis"
                ),
                interventions=[
                    {"name": "Dupilumab", "intervention_type": "DRUG"},
                ],
            ),
            _candidate(
                "NCT06850805",
                conditions=["Chronic Rhinosinusitis Without Nasal Polyps"],
                interventions=[
                    {"name": "OPN-375", "intervention_type": "DRUG"},
                ],
            ),
        )
        for candidate in without_polyps:
            with self.subTest(nct_id=candidate["nct_id"]):
                self.assertFalse(
                    _candidate_indication_matches_project(candidate, project)
                )

        procedure = _candidate(
            "NCT07184684",
            conditions=[
                "Chronic Rhinosinusitis Without Nasal Polyps",
                "Chronic Rhinosinusitis With Nasal Polyps",
            ],
            interventions=[
                {
                    "name": "Sinonasal microbiome transplant",
                    "intervention_type": "PROCEDURE",
                }
            ],
        )
        classification, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            0.95,
            project,
            procedure,
            "procedure",
        )
        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            classification,
        )


class TestCrswnpClassificationReconciliation(unittest.TestCase):
    def test_real_same_indication_drug_exclusions_are_reconciled_to_indirect(self):
        project = _crswnp_project()
        candidates = (
            _candidate(
                "NCT02665806",
                conditions=["Chronic Rhinosinustis With Polyps"],
                official_title=(
                    "Nasal Sprays in Patients With Nasal Poplyposis"
                ),
                interventions=[
                    {"name": "Ciclesonide", "intervention_type": "DRUG"},
                ],
            ),
            _candidate(
                "NCT03323866",
                conditions=[
                    "Chronic Rhinosinusitis (Diagnosis), Nasal Polyposis"
                ],
                interventions=[
                    {"name": "Budesonide", "intervention_type": "DRUG"},
                ],
            ),
            _candidate(
                "NCT02285283",
                conditions=["Chronic Rhinosinusitis"],
                official_title=(
                    "Treatment of Chronic Rhinosinusitis With Nasal Polyps"
                ),
                interventions=[
                    {"name": "Itraconazole", "intervention_type": "DRUG"},
                ],
                documents=[
                    {
                        "document_type": "protocol_sap",
                        "filename": "Prot_SAP_000.pdf",
                    }
                ],
            ),
        )

        for candidate in candidates:
            with self.subTest(nct_id=candidate["nct_id"]):
                classification, confidence = (
                    _enforce_classification_eligibility(
                        CompetitorTriageClassification.EXCLUDED,
                        0.95,
                        project,
                        candidate,
                        "model excluded",
                    )
                )
                self.assertEqual(
                    CompetitorTriageClassification.INDIRECT_REFERENCE,
                    classification,
                )
                self.assertLessEqual(confidence, 0.5)

    def test_unknown_project_facts_promote_same_indication_drug_exclusion(self):
        candidate = _candidate(
            "NCT84000001",
            conditions=["Chronic Rhinosinusitis With Nasal Polyps"],
            interventions=[
                {"name": "Study Drug", "intervention_type": "DRUG"}
            ],
        )
        classification, confidence = _enforce_classification_eligibility(
            CompetitorTriageClassification.EXCLUDED,
            0.95,
            _crswnp_project(),
            candidate,
            "unknown facts",
        )

        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            classification,
        )
        self.assertLessEqual(confidence, 0.5)

    def test_unknown_intervention_type_is_gap_not_exclusion(self):
        candidate = _candidate(
            "NCT84000002",
            conditions=["Chronic Rhinosinusitis With Nasal Polyps"],
        )
        classification, confidence = _enforce_classification_eligibility(
            CompetitorTriageClassification.EXCLUDED,
            0.95,
            _crswnp_project(),
            candidate,
            "unknown facts",
        )

        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            classification,
        )
        self.assertLessEqual(confidence, 0.4)

    def test_explicit_device_still_excludes(self):
        candidate = _candidate(
            "NCT84000003",
            conditions=["Chronic Rhinosinusitis With Nasal Polyps"],
            interventions=[
                {"name": "Study Device", "intervention_type": "DEVICE"}
            ],
        )
        classification, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.EXCLUDED,
            0.95,
            _crswnp_project(),
            candidate,
            "device",
        )

        self.assertEqual(
            CompetitorTriageClassification.EXCLUDED,
            classification,
        )

    def test_useful_protocol_preserves_indirect_even_when_project_facts_known(self):
        candidate = _candidate(
            "NCT84000004",
            conditions=["Chronic Rhinosinusitis With Nasal Polyps"],
            interventions=[
                {"name": "Study Drug", "intervention_type": "BIOLOGICAL"}
            ],
            documents=[
                {"document_type": "protocol", "filename": "Prot.pdf"}
            ],
        )
        classification, _ = _enforce_classification_eligibility(
            CompetitorTriageClassification.EXCLUDED,
            0.95,
            _crswnp_project(complete_critical_facts=True),
            candidate,
            "excluded",
        )

        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            classification,
        )

    def test_full_validation_corrects_reason_and_preserves_source_truth(self):
        nct_id = "NCT02898454"
        candidate = _candidate(
            nct_id,
            conditions=[
                "Chronic Rhinosinusitis Phenotype With Nasal Polyps "
                "(CRSwNP)"
            ],
            documents=[
                {"document_type": "protocol", "filename": "Prot.pdf"},
                {"document_type": "sap", "filename": "SAP.pdf"},
            ],
        )
        candidate.update(
            {
                "matching_conditions": candidate["conditions"],
                "project_indication_match": True,
            }
        )

        result = _validate_chunk_response(
            {"results": [_excluded_model_result(nct_id)]},
            [nct_id],
            chunk_input={
                "project_facts": _crswnp_project(),
                "candidates": [candidate],
            },
        )[0]
        indication = next(
            dimension
            for dimension in result.matching_dimensions
            if dimension.dimension == "indication"
        )

        self.assertEqual(
            CompetitorTriageClassification.INDIRECT_REFERENCE,
            result.classification,
        )
        self.assertEqual("match", indication.match)
        self.assertIn("适应症一致", result.reason)
        self.assertNotIn("适应症不同", result.reason)
        self.assertNotIn("同适应症药物研究参考", result.reason)
        self.assertIn("候选干预类型待核实", result.reason)
        self.assertIn("公开文档：方案与统计分析计划", result.reason)
        self.assertNotIn(
            "模型声称未知项目事实意味着应排除",
            result.evidence_gaps,
        )
        self.assertEqual(
            [
                "当前项目及候选均未提供技术类型信息，不能判断匹配性",
                "当前项目及候选均未提供给药途径信息，不能判断匹配性",
                "当前项目及候选均未提供靶点/机制信息，不能判断匹配性",
            ],
            result.evidence_gaps,
        )


if __name__ == "__main__":
    unittest.main()
