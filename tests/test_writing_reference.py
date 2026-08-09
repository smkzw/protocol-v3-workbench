from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlparse

from packages.contracts.workbench_contracts import WritingReferenceSearchRequest
from services.api.app.writing_reference import (
    candidate_from_study,
    document_url,
    evaluate_translation_fidelity,
    is_corpus_admissible,
    search_url,
    validate_pdf_payload,
)
from services.api.app.regulatory_translation_glossary import (
    evaluate_controlled_term_fidelity,
    load_regulatory_translation_glossary,
    regulatory_translation_glossary_hash,
    render_regulatory_translation_glossary_contract,
    render_preferred_abbreviation_contract,
    select_regulatory_translation_terms,
)


def study_fixture() -> dict:
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT05014438",
                "briefTitle": "Phase 2 Atopic Dermatitis Study",
                "officialTitle": "A Randomized Phase 2 Study in Atopic Dermatitis",
            },
            "conditionsModule": {"conditions": ["Atopic Dermatitis"]},
            "designModule": {"phases": ["PHASE2"], "studyType": "INTERVENTIONAL"},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example Sponsor"}},
            "statusModule": {
                "overallStatus": "COMPLETED",
                "studyFirstPostDateStruct": {"date": "2021-01-01"},
                "studyLastUpdatePostDateStruct": {"date": "2024-03-02"},
            },
        },
        "documentSection": {
            "largeDocumentModule": {
                "largeDocs": [
                    {
                        "typeAbbrev": "Prot_SAP",
                        "hasProtocol": True,
                        "hasSap": True,
                        "label": "Protocol and SAP",
                        "date": "2022-05-01",
                        "uploadDate": "2024-03-01",
                        "filename": "Prot_SAP_000.pdf",
                        "size": 1024,
                    }
                ]
            }
        },
    }


class WritingReferenceTests(unittest.TestCase):
    def test_regulatory_glossary_has_governed_sources_and_licensed_boundaries(
        self,
    ) -> None:
        glossary = load_regulatory_translation_glossary()

        self.assertIn(
            "official_regulatory_translation",
            glossary["governance"]["authority_priority"],
        )
        self.assertTrue(glossary["governance"]["conflict_rules"])
        self.assertEqual(
            {"license_required_not_bundled"},
            {item["status"] for item in glossary["licensed_connectors"]},
        )
        self.assertIn(
            "cdisc_ct_release_20260327",
            {item["source_id"] for item in glossary["source_registry"]},
        )

    def test_regulatory_glossary_selects_only_source_matched_context(self) -> None:
        selected = select_regulatory_translation_terms(
            "This randomized fixed-sequence design includes an interim review and interim analysis."
        )
        terms = {item["id"]: item["chinese"] for item in selected}

        self.assertEqual("随机", terms["randomized"])
        self.assertEqual("固定顺序设计", terms["fixed_sequence"])
        self.assertEqual("中期审查", terms["interim_review"])
        self.assertEqual("期中分析", terms["interim_analysis"])
        self.assertNotIn("washout_period", terms)
        self.assertEqual(64, len(regulatory_translation_glossary_hash()))

    def test_regulatory_glossary_contract_is_compact_and_supports_project_override(
        self,
    ) -> None:
        contract = render_regulatory_translation_glossary_contract(
            "The screening period is followed by a washout period.",
            project_overrides={"washout_period": "停药洗脱期"},
        )

        self.assertIn("english: screening period", contract)
        self.assertIn("preferred_zh: 筛选期", contract)
        self.assertIn("english: washout period", contract)
        self.assertIn("preferred_zh: 停药洗脱期", contract)
        self.assertIn("project_override_base_zh: 洗脱期", contract)
        self.assertNotIn("adverse event", contract)

    def test_regulatory_glossary_prefers_longest_phrase_without_losing_separate_match(
        self,
    ) -> None:
        nested_only = select_regulatory_translation_terms(
            "The End of Study Visit is at Week 24."
        )
        nested_ids = {item["id"] for item in nested_only}
        self.assertIn("end_of_study_visit", nested_ids)
        self.assertNotIn("study_visit", nested_ids)

        separate = select_regulatory_translation_terms(
            "The End of Study Visit is at Week 24; another study visit occurs at Week 12."
        )
        separate_ids = {item["id"] for item in separate}
        self.assertIn("end_of_study_visit", separate_ids)
        self.assertIn("study_visit", separate_ids)

    def test_regulatory_glossary_does_not_invent_unwritten_abbreviation(self) -> None:
        without_abbreviation = render_regulatory_translation_glossary_contract(
            "Patient-reported outcomes will be assessed."
        )
        with_abbreviation = render_regulatory_translation_glossary_contract(
            "Patient-reported outcomes (PRO) will be assessed."
        )

        self.assertNotIn("preserve_source_abbreviation: PRO", without_abbreviation)
        self.assertIn("preserve_source_abbreviation: PRO", with_abbreviation)

    def test_preferred_abbreviation_contract_only_uses_source_abbreviations(
        self,
    ) -> None:
        contract = render_preferred_abbreviation_contract(("DLQI", "POEM", "XYZ"))

        self.assertIn("abbreviation: DLQI", contract)
        self.assertIn("preferred_zh: 皮肤病生活质量指数", contract)
        self.assertIn("abbreviation: POEM", contract)
        self.assertNotIn("XYZ", contract)
        self.assertNotIn("18", contract)

    def test_preferred_abbreviation_contract_includes_degrees_and_safety_terms(
        self,
    ) -> None:
        contract = render_preferred_abbreviation_contract(
            ("MD", "MS", "AE", "SAE", "CRF")
        )

        for abbreviation, preferred in (
            ("MD", "医学博士"),
            ("MS", "理学硕士"),
            ("AE", "不良事件"),
            ("SAE", "严重不良事件"),
            ("CRF", "病例报告表"),
        ):
            self.assertIn(f"abbreviation: {abbreviation}", contract)
            self.assertIn(f"preferred_zh: {preferred}", contract)

    def test_controlled_term_fidelity_blocks_wrong_or_forbidden_protocol_terms(
        self,
    ) -> None:
        source = (
            "The formulation is evaluated after the washout period with H2 blockers."
        )
        accepted = evaluate_controlled_term_fidelity(
            source,
            "洗脱期后评价该制剂与H2受体拮抗剂合用时的表现。",
        )
        rejected = evaluate_controlled_term_fidelity(
            source,
            "清洗期后评价该处方与H2阻断剂合用时的表现。",
        )

        self.assertEqual((), accepted)
        self.assertIn("controlled_term_missing:formulation", rejected)
        self.assertIn("controlled_term_forbidden:washout_period", rejected)
        self.assertIn("controlled_term_forbidden:h2_blocker", rejected)

    def test_participant_term_blocks_patient_but_preserves_named_patient_measures(
        self,
    ) -> None:
        source = (
            "Subjects will complete the Patient-Oriented Eczema Measure and "
            "patient-reported outcomes."
        )
        accepted = evaluate_controlled_term_fidelity(
            source,
            "受试者将完成患者导向型湿疹评估量表和患者报告结局。",
        )
        rejected = evaluate_controlled_term_fidelity(
            source,
            "患者将完成患者导向型湿疹评估量表和患者报告结局。",
        )

        self.assertEqual((), accepted)
        self.assertIn("controlled_term_missing:participant", rejected)
        self.assertIn("controlled_term_forbidden:participant", rejected)

    def test_regulatory_glossary_avoids_dose_unit_collision_and_locks_long_phrases(
        self,
    ) -> None:
        dose_units = select_regulatory_translation_terms(
            "The assessment may include dosing of multiple dose units."
        )
        missed_dose = select_regulatory_translation_terms(
            "Return the used and unused medication (bottles), in addition to the instructions on the label."
        )

        self.assertNotIn("multiple_dose", {item["id"] for item in dose_units})
        self.assertEqual(
            {"used_unused_medication", "label_additional_instruction"},
            {item["id"] for item in missed_dose},
        )

        nonpreferred = select_regulatory_translation_terms(
            "PPI is a nonpreferable ARA selection in this study."
        )
        self.assertEqual(
            "不宜选用ARA",
            next(
                item["chinese"]
                for item in nonpreferred
                if item["id"] == "nonpreferred_ara"
            ),
        )

    def test_regulatory_glossary_matches_pdf_line_wraps_and_accepts_governed_variants(
        self,
    ) -> None:
        source = (
            "Return used and unused medication (bottles), in\n"
            "addition to the instructions on the label. The color of\n"
            "capsules (100 mg capsule) differs."
        )
        selected_ids = {
            item["id"] for item in select_regulatory_translation_terms(source)
        }

        self.assertIn("label_additional_instruction", selected_ids)
        self.assertIn("capsule_strength_color", selected_ids)
        self.assertEqual(
            (),
            evaluate_controlled_term_fidelity(
                source,
                "应归还已使用和未使用的药品（药瓶）。除标签说明外，授权人员必须进行指导。"
                "100 mg规格胶囊的颜色略有不同。",
            ),
        )

    def test_regulatory_glossary_preserves_ir_and_allows_subject_for_patient_specific(
        self,
    ) -> None:
        source = "A crossover design is recommended for BA of IR dosage forms due to patient-specific factors."
        accepted = evaluate_controlled_term_fidelity(
            source,
            "由于受试者个体因素，IR剂型的BA推荐采用交叉设计。",
        )
        missing_ir = evaluate_controlled_term_fidelity(
            source,
            "由于受试者个体因素，速释剂型的BA推荐采用交叉设计。",
        )

        self.assertEqual((), accepted)
        self.assertIn("controlled_term_missing:ir_dosage_form", missing_ir)

    def test_regulatory_glossary_uses_official_chinese_drug_name(self) -> None:
        accepted = evaluate_controlled_term_fidelity(
            "The half-life of abrocitinib is 3 hours and it does not exhibit accumulation.",
            "阿布昔替尼的半衰期为3小时，且不具有蓄积性。",
        )
        untranslated = evaluate_controlled_term_fidelity(
            "The half-life of abrocitinib is 3 hours.",
            "abrocitinib的半衰期为3小时。",
        )

        self.assertEqual((), accepted)
        self.assertIn("controlled_term_missing:abrocitinib", untranslated)

    def test_translation_fidelity_blocks_duplicate_approximation_marker(self) -> None:
        duplicated = evaluate_translation_fidelity(
            "The effect lasts ~10-12 hours.",
            "该作用持续约为~10-12小时。",
        )
        accepted = evaluate_translation_fidelity(
            "The effect lasts ~10-12 hours.",
            "该作用持续约10-12小时。",
        )

        self.assertIn("approximation_marker_duplicated", duplicated.failure_codes)
        self.assertTrue(accepted.passed, accepted.failure_codes)

    def test_translation_fidelity_blocks_pharmacology_phrase_drift(self) -> None:
        source = (
            "It is preferable to select an ARA. The washout of the drug from plasma is adequate. "
            "H2 blockers maximize the pH-elevating effect with a duration of action lasting 10 hours."
        )
        drifted = evaluate_translation_fidelity(
            source,
            "优选选择一种ARA。该药物可从血浆中洗脱。H2受体拮抗剂可提高pH升高效应的持续时间，"
            "持续10小时。",
        )
        accepted = evaluate_translation_fidelity(
            source,
            "宜选择一种ARA。该药物可从血浆中清除。H2受体拮抗剂可使pH升高效应最大化，"
            "作用持续时间为10小时。",
        )

        self.assertFalse(drifted.passed)
        self.assertIn("regulatory_chinese_term_calque", drifted.failure_codes)
        self.assertIn(
            "controlled_term_forbidden:preferable_to_select", drifted.failure_codes
        )
        self.assertTrue(accepted.passed, accepted.failure_codes)

    def test_translation_fidelity_accepts_english_number_words_as_chinese_digits(
        self,
    ) -> None:
        accepted = evaluate_translation_fidelity(
            "Two sentinel subjects receive all six treatments for 18 days.",
            "2名哨兵受试者接受全部6种治疗，共18天。",
        )

        self.assertTrue(accepted.passed, accepted.failure_codes)

    def test_translation_fidelity_preserves_consecutive_day_unit(self) -> None:
        accepted = evaluate_translation_fidelity(
            "Treatment continues for at least 10 consecutive days with a 150 mg dose.",
            "以150 mg剂量连续治疗至少10天。",
        )

        self.assertTrue(accepted.passed, accepted.failure_codes)

    def test_regulatory_glossary_locks_phase1_sentinel_and_packaging_terms(
        self,
    ) -> None:
        source = (
            "The sentinel dosing approach includes two sentinel subjects. The medical monitor "
            "reviews the active comparator and vehicle. Return the blister package."
        )
        accepted = evaluate_controlled_term_fidelity(
            source,
            "哨兵给药方法包括2名哨兵受试者。医学监查员审查阳性对照药和赋形剂。归还泡罩包装。",
        )
        rejected = evaluate_controlled_term_fidelity(
            source,
            "前哨给药包括2名前哨受试者。医学监查员审查阳性对照药和赋形剂。归还铝塑包装。",
        )

        self.assertEqual((), accepted)
        self.assertIn("controlled_term_forbidden:sentinel_dosing", rejected)
        self.assertIn("controlled_term_forbidden:sentinel_subject", rejected)
        self.assertIn("controlled_term_forbidden:blister_package", rejected)

    def test_search_url_is_reproducible_and_requires_indication_and_phase(self) -> None:
        request = WritingReferenceSearchRequest(
            indication="Atopic Dermatitis",
            phases=["PHASE2"],
            study_type="INTERVENTIONAL",
            page_size=100,
        )

        first = search_url(request)
        second = search_url(request)
        params = parse_qs(urlparse(first).query)

        self.assertEqual(first, second)
        self.assertEqual(["Atopic Dermatitis"], params["query.cond"])
        self.assertEqual(
            ["AREA[Phase]PHASE2 AND AREA[StudyType]INTERVENTIONAL"],
            params["query.term"],
        )
        self.assertEqual(["true"], params["countTotal"])
        self.assertEqual(["100"], params["pageSize"])
        self.assertNotIn("StudyLastUpdatePostDate", params["fields"][0])

        with self.assertRaises(ValueError):
            search_url(WritingReferenceSearchRequest(indication="", phases=["PHASE2"]))
        with self.assertRaises(ValueError):
            search_url(WritingReferenceSearchRequest(indication="AD", phases=[]))

    def test_candidate_preserves_registry_identity_and_all_document_versions(
        self,
    ) -> None:
        candidate = candidate_from_study(study_fixture())

        self.assertEqual("NCT05014438", candidate.nct_id)
        self.assertEqual(["PHASE2"], candidate.phases)
        self.assertEqual("pending_medical_relevance", candidate.relevance_status)
        self.assertEqual(1, len(candidate.public_documents))
        document = candidate.public_documents[0]
        self.assertEqual("protocol_sap", document.document_type)
        self.assertEqual("2022-05-01", document.document_date)
        self.assertEqual("2024-03-01", document.upload_date)
        self.assertEqual(1024, document.declared_size)
        self.assertTrue(document.download_url.endswith("/NCT05014438/Prot_SAP_000.pdf"))

    def test_document_url_and_pdf_receipt_fail_closed(self) -> None:
        self.assertEqual(
            "https://clinicaltrials.gov/ProvidedDocs/38/NCT05014438/Prot_000.pdf",
            document_url("NCT05014438", "Prot_000.pdf"),
        )
        for nct_id, filename in (
            ("NCT50", "Prot_000.pdf"),
            ("NCT05014438", "../secret.pdf"),
            ("NCT05014438", "not-a-pdf.txt"),
        ):
            with self.assertRaises(ValueError):
                document_url(nct_id, filename)

        valid = validate_pdf_payload(
            b"%PDF-1.7\nbody", declared_size=13, content_type="application/pdf"
        )
        self.assertTrue(valid.is_valid)
        self.assertTrue(valid.magic_valid)
        self.assertTrue(valid.declared_size_matches)

        invalid = validate_pdf_payload(
            b"<html>error</html>", declared_size=18, content_type="text/html"
        )
        self.assertFalse(invalid.is_valid)
        self.assertFalse(invalid.magic_valid)

    def test_translation_fidelity_blocks_numeric_unit_abbreviation_and_negation_drift(
        self,
    ) -> None:
        source = "Participants must not receive SCS within 14 days before Day 1; dose is 200 mg."
        accepted = evaluate_translation_fidelity(
            source,
            "受试者在第1天前14天内不得接受SCS；剂量为200 mg。",
        )
        self.assertTrue(accepted.passed)

        drifted = evaluate_translation_fidelity(
            source,
            "受试者在第1天前7天内接受系统性糖皮质激素；剂量为100 mg。",
        )
        self.assertFalse(drifted.passed)
        self.assertIn("numeric_tokens_changed", drifted.failure_codes)
        self.assertIn("source_abbreviation_missing", drifted.failure_codes)
        self.assertIn("negation_signal_missing", drifted.failure_codes)

    def test_translation_fidelity_accepts_compact_units_thousands_and_gauge_before_chinese(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "A 10 cm area will be injected with 1–2 mL lidocaine 1:100,000 "
            "using a 30G needle after a 5 mm punch biopsy.",
            "在5 mm环钻皮肤活检后，使用30G针头向10 cm区域注射1–2 mL、"
            "浓度为1:100,000的利多卡因。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_ignores_sub_investigator_heading_but_keeps_degrees(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "SUB-INVESTIGATOR: Antonia Valenzuela, MD, MS",
            "助理研究者：Antonia Valenzuela，医学博士、理学硕士（MD, MS）",
        )

        self.assertTrue(result.passed, result.failure_codes)
        self.assertEqual(("MD", "MS"), result.source_abbreviations)

    def test_translation_fidelity_accepts_more_than_rendered_as_chinese_exceeded(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Follow-up is required for at least 4 weeks; the participant is "
            "more than 4 weeks beyond the follow-up window.",
            "至少需随访4周；受试者已超出4周随访期限。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_accepts_questionnaire_no_not_limited_wording(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Moderate activities: ❑ Yes, limited a lot. ❑ Yes, limited a "
            "little. ❑ No, not limited at all.",
            "中等强度活动：❑ 是的，受到很大限制。❑ 是的，受到一些限制。"
            "❑ 没有，完全不受任何限制。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_accepts_questionnaire_yes_no_rendered_as_shi_fou(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "a. Cut down the amount of time you spent on work or other "
            "activities? \uf063 Yes \uf063 No",
            "a. 您是否减少了用于工作或其他活动的时间？\uf063 是 \uf063 否",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_accepts_address_abbreviations_as_chinese_regions(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Palo Alto VA Health Care System, CA; Novadaq Technologies Inc., "
            "Richmond, BC, Canada.",
            "帕洛阿尔托VA医疗系统（加利福尼亚州）；加拿大不列颠哥伦比亚省"
            "里士满的Novadaq Technologies Inc.公司。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_handles_plural_and_hyphenated_abbreviations(
        self,
    ) -> None:
        source = (
            "Diagnosis of active PNH based on clone size of >=10% by RBCs, "
            "measured by GPI-deficiency; COVID-19 history must be recorded."
        )
        accepted = evaluate_translation_fidelity(
            source,
            "活动性PNH诊断依据为RBCs克隆比例>=10%，采用GPI缺乏检测；必须记录COVID-19病史。",
        )

        self.assertTrue(accepted.passed)
        self.assertEqual(
            ("COVID-19", "GPI", "PNH", "RBCs"), accepted.source_abbreviations
        )

        drifted = evaluate_translation_fidelity(
            source,
            "活动性PNH诊断依据为红细胞克隆比例>=10%，采用GPI缺乏检测；必须记录COVID-19病史。",
        )
        self.assertIn("source_abbreviation_missing", drifted.failure_codes)

    def test_translation_fidelity_accepts_chinese_phase_age_and_reordered_thresholds(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "A Phase 1 study in children 6 to less than 12 years with >=50% hair loss, reviewed by the US FDA.",
            "这是一项Ⅰ期研究，入选脱发面积≥50%的6至<12岁儿童，并经美国FDA审评。",
        )
        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_ignores_rich_text_break_markup_in_comparator_checks(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "EASI at Week 16 must be >=4.",
            "第16周EASI评分必须≥4。<br>继续随访。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_understands_zh_age_measure_words_and_citation_years(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Adults 18 to 75 years with disease for >=12 months according to Hanifin and Rajka (1980).",
            "按Hanifin和Rajka（1980年）标准，纳入18至75周岁且病史≥12个月的成人。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_treats_trailing_decimal_zero_as_equivalent(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "The score must be >=2.0.",
            "评分必须≥2。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_accepts_standard_chinese_abbreviation_equivalents(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "EU subjects with AEs or SAEs require review by IRBs/IECs; ECG and ULN are recorded.",
            "欧盟受试者发生不良事件或严重不良事件时须经伦理委员会审查；记录心电图和正常值上限。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_does_not_treat_scale_suffix_as_litre_unit(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Change in EQ-5D-5L score at Week 16.",
            "第16周EQ-5D-5L评分的变化。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_accepts_singularized_plural_abbreviation(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "The study evaluates gastric pH-mediated DDIs.",
            "本研究评价胃pH介导的DDI。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_does_not_read_cycle_number_as_weeks(self) -> None:
        result = evaluate_translation_fidelity(
            "Period 7 lasted 7 days.",
            "第7周期持续7天。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_accepts_buzu_as_strict_less_than(self) -> None:
        result = evaluate_translation_fidelity(
            "Skip the dose if the interval is less than 8 hours.",
            "若给药间隔不足8小时，则跳过该剂量。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_blocks_bare_eg_connector_and_subject_patient_drift(
        self,
    ) -> None:
        connector = evaluate_translation_fidelity(
            "Use an H2 antagonist, e.g. famotidine.",
            "使用H2受体拮抗剂，eg法莫替丁。",
        )
        population = evaluate_translation_fidelity(
            "Healthy subjects receive one dose.",
            "健康患者接受一次给药。",
        )

        self.assertFalse(connector.passed)
        self.assertIn("untranslated_source_connector", connector.failure_codes)
        self.assertFalse(population.passed)
        self.assertIn("regulatory_chinese_term_calque", population.failure_codes)

    def test_translation_fidelity_blocks_nonstandard_phase1_regulatory_terms(
        self,
    ) -> None:
        cases = [
            ("Period 7 only", "仅限第7期"),
            ("A minimum washout of 7 days", "至少7天清洗期"),
            ("the slowest minitab MR formulation", "最慢的minitab MR制剂"),
            ("a single-dose study", "一项单剂量研究"),
            ("Scientific rationale", "科学理由"),
            ("an H2 blocker", "H2阻断剂"),
            ("a nonpreferable ARA", "非优选的ARA选择"),
            ("an interim review", "中期审评"),
            ("an additional site visit", "一次额外现场访视"),
            (
                "in addition to the instructions on the label",
                "此外还有标签上的说明",
            ),
            (
                "The patient shall be instructed to not skip any doses.",
                "应指导患者不要漏服任何剂量。",
            ),
            ("MR tablet formulations", "MR片剂处方"),
            ("a 6-treatment sequence design", "6种处理设计"),
            (
                "a single oral dose of study treatment",
                "单次口服剂量的研究治疗",
            ),
            (
                "return the used and unused medication (bottles)",
                "归还已用和未用药物（瓶）",
            ),
            (
                "The color of capsules (100 mg capsule) will be different.",
                "胶囊（100 mg胶囊）的颜色会略有不同。",
            ),
        ]
        for source, translated in cases:
            with self.subTest(source=source, translated=translated):
                result = evaluate_translation_fidelity(source, translated)

                self.assertFalse(result.passed)
                self.assertIn("regulatory_chinese_term_calque", result.failure_codes)

    def test_translation_fidelity_blocks_removed_space_between_value_and_unit(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Reduce from 150 mg to 100 mg.",
            "从150mg减至100mg。",
        )

        self.assertFalse(result.passed)
        self.assertIn("unit_spacing_changed", result.failure_codes)

    def test_translation_fidelity_still_blocks_threshold_direction_drift_after_reordering(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Children 6 to less than 12 years with >=50% hair loss.",
            "入选脱发面积≤50%的6至<12岁儿童。",
        )
        self.assertFalse(result.passed)
        self.assertIn("comparison_direction_changed", result.failure_codes)

    def test_translation_fidelity_accepts_shared_range_unit_and_chinese_unman(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Children 6 to less than 12 years with >=50% hair loss.",
            "入选因脱发面积≥50%的6岁至未满12岁儿童。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_accepts_symbolic_less_than_shared_age_unit(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Children 6 to <12 years of age will participate.",
            "将入组6岁至<12岁的儿童。",
        )
        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_counts_each_repeated_shared_age_unit(self) -> None:
        result = evaluate_translation_fidelity(
            "Children 6 to <12 years and another group 6 to <12 years will participate.",
            "将入组6岁至<12岁的儿童和另一组6岁至<12岁的儿童。",
        )
        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_does_not_treat_duration_label_as_interval_comparator(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Participation will last approximately 7 weeks (minimum) to 11 weeks (maximum).",
            "研究参与时间约为7周（最短）至11周（最长）。",
        )
        self.assertTrue(result.passed, result.failure_codes)

        not_full = evaluate_translation_fidelity(
            "Children 6 to less than 12 years with >=50% hair loss.",
            "入选因脱发面积≥50%的6岁至不满12岁儿童。",
        )
        self.assertTrue(not_full.passed, not_full.failure_codes)

    def test_translation_fidelity_does_not_read_period_as_week(self) -> None:
        result = evaluate_translation_fidelity(
            "Periods 4 to 6 include a 7 to 9 day follow-up window.",
            "第4至6周期包括7至9天的随访窗。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_binds_reordered_chinese_threshold_clause(
        self,
    ) -> None:
        result = evaluate_translation_fidelity(
            "Take one tablet at least 3 days before dosing and after at least 10 consecutive days.",
            "至少在首次给药前3天服用一片，并在连续给药至少10天后服用一片。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_handles_minimum_of_and_ordinal_words(self) -> None:
        comparator = evaluate_translation_fidelity(
            "A minimum of 10 days is required between cohorts.",
            "队列之间至少间隔10天。",
        )
        self.assertTrue(comparator.passed, comparator.failure_codes)

        ordinals = evaluate_translation_fidelity(
            "Review the first subject before dosing the second subject.",
            "在第2名受试者给药前审查第1名受试者。",
        )
        self.assertTrue(ordinals.passed, ordinals.failure_codes)

    def test_translation_fidelity_handles_shared_visit_list_units(self) -> None:
        result = evaluate_translation_fidelity(
            "Visits occur at Weeks 3, 6, 9, and 12 and after 48 weeks belimumab treatment.",
            "在第3、6、9和12周进行访视，并在完成48周贝利尤单抗治疗后继续。",
        )

        self.assertTrue(result.passed, result.failure_codes)

    def test_translation_fidelity_enforces_phase1_drug_and_pk_glossary(self) -> None:
        source = (
            "Ritlecitinib steady state PK will be evaluated using "
            "non-compartmental analysis."
        )
        accepted = evaluate_translation_fidelity(
            source,
            "采用非房室分析评价利特昔替尼的稳态PK。",
        )
        self.assertTrue(accepted.passed, accepted.failure_codes)

        untranslated = evaluate_translation_fidelity(
            source,
            "采用非房室模型分析评价ritlecitinib的稳态PK。",
        )
        self.assertIn(
            "controlled_term_missing:ritlecitinib",
            untranslated.failure_codes,
        )
        self.assertIn(
            "controlled_term_forbidden:noncompartmental_analysis",
            untranslated.failure_codes,
        )

    def test_translation_fidelity_normalizes_verified_drug_typo_and_preserves_taste(
        self,
    ) -> None:
        source = "Assess the taste and palatability of abocitinib formulations."
        accepted = evaluate_translation_fidelity(
            source,
            "评估阿布昔替尼制剂的口味和适口性。",
        )
        self.assertTrue(accepted.passed, accepted.failure_codes)

        compressed = evaluate_translation_fidelity(
            source,
            "评估阿布昔替尼制剂的适口性。",
        )
        self.assertIn(
            "controlled_term_missing:taste_and_palatability",
            compressed.failure_codes,
        )

    def test_translation_fidelity_enforces_biologic_drug_and_sampling_terms(
        self,
    ) -> None:
        source = (
            "Belimumab population PK models and dupilumab anti-drug antibodies "
            "will be assessed using serial biopsies and tape stripping."
        )
        accepted = evaluate_translation_fidelity(
            source,
            "将通过连续活检和胶带剥离取样评价贝利尤单抗群体PK模型及度普利尤单抗抗药抗体。",
        )
        self.assertTrue(accepted.passed, accepted.failure_codes)

        untranslated = evaluate_translation_fidelity(
            source,
            "将通过serial biopsies和tape stripping评价belimumab群体PK模型及dupilumab抗药抗体。",
        )
        self.assertIn("controlled_term_missing:belimumab", untranslated.failure_codes)
        self.assertIn("controlled_term_missing:dupilumab", untranslated.failure_codes)
        self.assertIn(
            "controlled_term_missing:serial_biopsies", untranslated.failure_codes
        )
        self.assertIn(
            "controlled_term_missing:tape_stripping", untranslated.failure_codes
        )

    def test_translation_fidelity_blocks_first_subject_temporal_inversion(self) -> None:
        source = (
            "A dose escalation committee review of the 24-hour safety data for the first subject "
            "in Cohort 1 will be performed before dosing the second subject."
        )
        accepted = evaluate_translation_fidelity(
            source,
            "在给第2例受试者用药前，剂量递增委员会将审查队列1第1例受试者给药后24小时的安全性数据。",
        )
        inverted = evaluate_translation_fidelity(
            source,
            "在队列1第1例受试者给药前，将由剂量递增委员会审查第1例受试者24小时安全性数据，随后给第2例受试者用药。",
        )
        shortened_inversion = evaluate_translation_fidelity(
            source,
            "在队列1中对第1例受试者给药前，将进行剂量递增委员会对24小时安全性数据的审查。",
        )

        self.assertTrue(accepted.passed, accepted.failure_codes)
        self.assertIn("temporal_dependency_changed", inverted.failure_codes)
        self.assertIn("temporal_dependency_changed", shortened_inversion.failure_codes)

    def test_translation_fidelity_blocks_phase1_chinese_calques_and_spacing(
        self,
    ) -> None:
        contact_source = (
            "After each of the first 2 infusions, subjects will be contacted by phone/email "
            "the following day."
        )
        active_source = "The first 2 participants (1 active: 1 placebo) will be dosed."

        awkward_contact = evaluate_translation_fidelity(
            contact_source,
            "前2次输注后，每次均次日在电话/邮件联系受试者。",
        )
        wrong_active = evaluate_translation_fidelity(
            active_source,
            "前2例受试者（1名活性药物：1名安慰剂）将接受给药。",
        )
        wrong_active_noun = evaluate_translation_fidelity(
            active_source,
            "前2例受试者（1例试验药物：1例安慰剂）将接受给药。",
        )
        spaced = evaluate_translation_fidelity(
            "PK and PD data will be reviewed at the DLRM.",
            "PK 和 PD 数据将在 DLRM 期间审查。",
        )

        self.assertIn("regulatory_chinese_term_calque", awkward_contact.failure_codes)
        self.assertIn("regulatory_chinese_term_calque", wrong_active.failure_codes)
        self.assertIn("regulatory_chinese_term_calque", wrong_active_noun.failure_codes)
        self.assertIn("chinese_typography_spacing", spaced.failure_codes)

    def test_translation_fidelity_accepts_frequency_expansion_and_minimum_interval(
        self,
    ) -> None:
        frequency = evaluate_translation_fidelity(
            "Participants receive 8 infusions q3W.",
            "受试者每3周一次（q3W）接受输注，共8次。",
        )
        interval = evaluate_translation_fidelity(
            "There will be a minimum of 10 days between cohorts for dose escalation.",
            "各队列之间用于剂量递增的最短间隔为10天。",
        )

        self.assertTrue(frequency.passed, frequency.failure_codes)
        self.assertTrue(interval.passed, interval.failure_codes)

    def test_translation_fidelity_blocks_unsupported_efficacy_purpose(self) -> None:
        source = "The study will compare TAK-079 with matching placebo."
        faithful = evaluate_translation_fidelity(
            source, "本研究将比较TAK-079与匹配安慰剂。"
        )
        expanded = evaluate_translation_fidelity(
            source,
            "本研究将比较TAK-079与匹配安慰剂的疗效。",
        )

        self.assertTrue(faithful.passed, faithful.failure_codes)
        self.assertIn("unsupported_medical_concept_added", expanded.failure_codes)

    def test_translation_fidelity_blocks_cross_scale_identity_contamination(
        self,
    ) -> None:
        source = (
            "Failure to maintain low disease activity is defined as "
            "Investigator Global Assessment (IGA) 0=clear to 2=mild."
        )
        faithful = evaluate_translation_fidelity(
            source,
            "未能维持低疾病活动状态，定义为研究者整体评估（IGA）评分"
            "0分（清除）至2分（轻度）。",
        )
        contaminated = evaluate_translation_fidelity(
            source,
            "未能维持低疾病活动状态，定义为湿疹面积和严重程度指数评分"
            "相当于研究者整体评估（IGA）评分0分（清除）至2分（轻度）。",
        )

        self.assertTrue(faithful.passed, faithful.failure_codes)
        self.assertIn(
            "unsupported_scale_identity_added:EASI",
            contaminated.failure_codes,
        )

    def test_translation_fidelity_accepts_viga_ad_without_false_generic_iga_addition(
        self,
    ) -> None:
        source = (
            "At Week 16, validated Investigator Global Assessment Scale for "
            "Atopic Dermatitis (vIGA-AD) score of 0 or 1."
        )
        translated = (
            "第16周时，经验证的特应性皮炎研究者整体评估量表（vIGA-AD）评分为0分或1分。"
        )

        result = evaluate_translation_fidelity(source, translated)

        self.assertTrue(result.passed, result.failure_codes)
        self.assertNotIn(
            "unsupported_scale_identity_added:IGA",
            result.failure_codes,
        )

    def test_translation_fidelity_accepts_chinese_negation_but_blocks_untranslated_connectors(
        self,
    ) -> None:
        source = "An AE may or may not be causally associated with treatment."

        accepted = evaluate_translation_fidelity(
            source,
            "AE可能与治疗存在因果关系，也可能不存在因果关系。",
        )
        self.assertTrue(accepted.passed)

        with_or_without = evaluate_translation_fidelity(
            "Administer the tablet with or without famotidine 40 mg.",
            "给予该片剂，可与或不与法莫替丁40 mg合并使用。",
        )
        self.assertTrue(with_or_without.passed, with_or_without.failure_codes)

        not_coadministered = evaluate_translation_fidelity(
            "Administer the tablet with or without famotidine 40 mg.",
            "给予该片剂，联用或不联用法莫替丁40 mg。",
        )
        self.assertTrue(
            not_coadministered.passed,
            not_coadministered.failure_codes,
        )

        not_combined = evaluate_translation_fidelity(
            "Administer the tablet with or without famotidine 40 mg.",
            "给予该片剂，联合或不联合法莫替丁40 mg。",
        )
        self.assertTrue(not_combined.passed, not_combined.failure_codes)

        untranslated = evaluate_translation_fidelity(
            "Refer to treatment and/or study discontinuation guidance.",
            "请参照治疗 and/or 研究终止指导。",
        )
        self.assertIn("untranslated_source_connector", untranslated.failure_codes)

        untranslated_example = evaluate_translation_fidelity(
            "Any untoward occurrence, e.g. an abnormal laboratory finding, is an AE.",
            "任何不良医学事件，e.g. 异常实验室检查结果，均属于AE。",
        )
        self.assertIn(
            "untranslated_source_connector", untranslated_example.failure_codes
        )

    def test_translation_fidelity_blocks_context_specific_regulatory_chinese_calques(
        self,
    ) -> None:
        product_source = (
            "An AE may be associated with a medicinal (investigational) product."
        )
        product_calque = evaluate_translation_fidelity(
            product_source,
            "AE可能与药用（研究用）产品相关。",
        )
        self.assertIn("regulatory_chinese_term_calque", product_calque.failure_codes)
        self.assertTrue(
            evaluate_translation_fidelity(
                product_source, "AE可能与试验用药品相关。"
            ).passed
        )
        duplicated_product_term = evaluate_translation_fidelity(
            product_source,
            "AE可能与试验用药品（研究用药品）相关。",
        )
        self.assertIn(
            "regulatory_chinese_term_calque", duplicated_product_term.failure_codes
        )

        association_source = (
            "An AE may or may not be temporally or causally associated with treatment."
        )
        weak_negation = evaluate_translation_fidelity(
            association_source,
            "AE可能与治疗存在时间或因果关系，也可能没有。",
        )
        self.assertIn("regulatory_chinese_term_calque", weak_negation.failure_codes)
        self.assertTrue(
            evaluate_translation_fidelity(
                association_source,
                "AE与治疗可能存在、也可能不存在时间或因果关联。",
            ).passed
        )

        visit_source = (
            "Missed or rescheduled visits should not lead to automatic discontinuation."
        )
        visit_calque = evaluate_translation_fidelity(
            visit_source,
            "漏访或改期不应导致自动终止。",
        )
        self.assertIn("regulatory_chinese_term_calque", visit_calque.failure_codes)
        self.assertTrue(
            evaluate_translation_fidelity(
                visit_source, "漏访或访视改期不应自动导致退出研究。"
            ).passed
        )

        pnh_endpoint_source = "For PNH, the response rate is the primary variable and each patient may be a responder."
        self.assertIn(
            "regulatory_chinese_term_calque",
            evaluate_translation_fidelity(
                pnh_endpoint_source,
                "PNH的主要变量为缓解率，每位患者可视为缓解者。",
            ).failure_codes,
        )
        self.assertTrue(
            evaluate_translation_fidelity(
                pnh_endpoint_source,
                "PNH的主要变量为应答率，每位患者可视为应答者。",
            ).passed
        )

        pnh_clone_source = "Diagnosis of PNH requires a clone size of at least 10%."
        self.assertIn(
            "regulatory_chinese_term_calque",
            evaluate_translation_fidelity(
                pnh_clone_source,
                "PNH诊断要求克隆大小至少10%。",
            ).failure_codes,
        )
        self.assertTrue(
            evaluate_translation_fidelity(
                pnh_clone_source,
                "PNH诊断要求克隆比例至少10%。",
            ).passed
        )

    def test_only_current_medically_approved_translation_is_admissible(self) -> None:
        self.assertTrue(
            is_corpus_admissible(
                source_current=True,
                extraction_status="passed",
                fidelity_status="passed",
                medical_review_status="approved",
                translation_status="completed",
            )
        )
        for override in (
            {"source_current": False},
            {"extraction_status": "pending"},
            {"fidelity_status": "blocked"},
            {"medical_review_status": "pending"},
            {"translation_status": "failed"},
        ):
            values = {
                "source_current": True,
                "extraction_status": "passed",
                "fidelity_status": "passed",
                "medical_review_status": "approved",
                "translation_status": "completed",
            }
            values.update(override)
            self.assertFalse(is_corpus_admissible(**values))


if __name__ == "__main__":
    unittest.main()
