from __future__ import annotations

import unittest

from services.api.app.medical_writing_protected_tokens import (
    check_protected_tokens,
    extract_protected_tokens,
    protected_token_issue_dicts,
)


class MedicalWritingProtectedTokenTests(unittest.TestCase):
    def test_preserves_numbers_units_terms_citation_and_cross_reference(self):
        source = "给药剂量为 5 mg，每 2 周一次；主要终点见表1，文献[3-4]，评分 rTNSS。"
        proposal = "给药剂量为5 mg，每2周一次；主要终点见表 1，文献［3–4］，评分 rTNSS。"
        result = check_protected_tokens(source, proposal)
        self.assertEqual("verified", result.status)
        self.assertFalse(result.missing)
        self.assertFalse(result.added)
        self.assertFalse(result.order_changed)

    def test_missing_or_changed_numeric_unit_fails_closed(self):
        result = check_protected_tokens("剂量 5 mg。", "剂量 10 g。")
        self.assertEqual("violated", result.status)
        self.assertTrue(result.violated)
        self.assertEqual(
            {"5 mg"},
            {token.text for token in result.missing},
        )
        self.assertIn("protected_token_added_unresolved", {
            item["reason_code"] for item in protected_token_issue_dicts(result)
        })

    def test_controlled_term_citation_and_cross_reference_removal_fails_closed(self):
        source = "评分 rTNSS，见表1，支持文献[3]。"
        proposal = "评分 TNSS，支持文献。"
        result = check_protected_tokens(source, proposal)
        self.assertEqual("violated", result.status)
        self.assertEqual(
            {"rTNSS", "表1", "[3]"},
            {token.text for token in result.missing},
        )

    def test_reordering_identity_tokens_is_a_violation(self):
        result = check_protected_tokens("第1周使用 5 mg，评估 10 分。", "第1周使用 10 分，评估 5 mg。")
        self.assertTrue(result.order_changed)
        self.assertEqual("violated", result.status)
        self.assertTrue(any(item["reason_code"] == "protected_token_order_changed" for item in protected_token_issue_dicts(result)))

    def test_additions_are_unresolved_but_not_automatically_blocked(self):
        result = check_protected_tokens("主要终点见表1。", "主要终点见表1，并于第2周复测 5 mg。")
        self.assertEqual("unresolved", result.status)
        self.assertFalse(result.violated)
        self.assertEqual(
            {"2周", "5 mg"},
            {token.text for token in result.added},
        )

    def test_fullwidth_numeric_equivalent_is_normalized(self):
        result = check_protected_tokens("剂量 ５ mg。", "剂量 5mg。")
        self.assertEqual("verified", result.status)

    def test_equivalent_unit_case_and_micro_sign_are_normalized(self):
        self.assertEqual("verified", check_protected_tokens("5 MG", "5 mg").status)
        self.assertEqual("verified", check_protected_tokens("5 μg", "5 ug").status)
        self.assertEqual("verified", check_protected_tokens("５％", "5%").status)
        self.assertEqual("verified", check_protected_tokens("26.04 uM", "26.04 µM").status)
        self.assertEqual("verified", check_protected_tokens("5 mg/m2", "5 mg/m^2").status)
        self.assertEqual("verified", check_protected_tokens("1,000 mg", "1000 mg").status)
        self.assertEqual("verified", check_protected_tokens("CD4-", "CD4−").status)

    def test_unit_compound_sign_comparator_and_scientific_notation_changes_fail_closed(self):
        cases = (
            ("5 mg/kg", "5 mg/L"),
            ("5 mg/kg/day", "5 mg/kg/week"),
            ("<=5 mg", ">=5 mg"),
            ("5毫克/千克", "5毫克/升"),
            ("26.04 nM", "26.04 µM"),
            ("1×10^9/L", "1×10^9/mL"),
            ("5 M", "5 m"),
            ("5 mM", "5 mm"),
            ("5 nM", "5 nm"),
            ("1630.4 ng*h/mL", "1630.4 ng*day/L"),
            ("每周一次给药", "每周两次给药"),
            ("五毫克", "十毫克"),
            ("5 μL", "5 nL"),
            ("TNF-α", "TNF-β"),
            ("CD4+", "CD4−"),
            ("I期研究", "II期研究"),
            ("A组", "B组"),
            ("Cmax", "Tmax"),
            ("零点五毫克", "一点五毫克"),
            ("每日半片", "每日一片"),
            ("IL-1α", "IL-1β"),
            ("ER+", "ER−"),
            ("H1N1", "H1N2"),
            ("5 mg qd", "5 mg bid"),
            ("α受体", "β受体"),
            ("A层", "B层"),
            ("−5 °C", "5 °C"),
            ("<140 mmHg", ">140 mmHg"),
            ("1e6", "1e9"),
            ("5毫克", "5微克"),
        )
        for source, proposal in cases:
            with self.subTest(source=source):
                self.assertEqual("violated", check_protected_tokens(source, proposal).status)

    def test_plain_chinese_without_identity_tokens_is_verified(self):
        result = check_protected_tokens("请保持原意并改善行文。", "请保持原意并改善行文。")
        self.assertEqual("verified", result.status)
        self.assertEqual((), extract_protected_tokens("请保持原意并改善行文。"))

    def test_numeric_adjacent_prose_is_not_treated_as_a_unit(self):
        for source, proposal in (
            ("共5名受试者入组", "共5名参与者入组"),
            ("第2周使用研究药物", "第2周给予研究药物"),
            ("剂量5毫克后观察", "剂量5毫克后随访"),
            ("Phase 2 study", "Phase 2 trial"),
        ):
            with self.subTest(source=source):
                self.assertEqual("verified", check_protected_tokens(source, proposal).status)

    def test_table_figure_and_roman_cross_references_are_protected(self):
        for source, proposal in (
            ("见表一。", "见表二。"),
            ("见表1A。", "见表1B。"),
            ("详见第I章。", "详见第II章。"),
        ):
            with self.subTest(source=source):
                self.assertEqual("violated", check_protected_tokens(source, proposal).status)

    def test_nfkc_compatibility_token_keeps_original_locator(self):
        token = extract_protected_tokens("剂量5㎎")[0]
        self.assertEqual("5㎎", token.text)
        self.assertEqual((2, 4), (token.start, token.end))

    def test_adversarial_controlled_terms_and_frequency_are_fail_closed(self):
        for source, proposal in (
            ("TGF-β1", "TGF-α1"),
            ("IL1β", "IL1α"),
            ("Phase I", "Phase II"),
            ("Arm A", "Arm B"),
            ("Cohort A", "Cohort B"),
            ("每日一片半", "每日一片"),
            ("百分之五", "百分之十"),
            ("c.123A>G", "c.123A>T"),
            ("c.123delA", "c.123delG"),
            ("c.123+1G>A", "c.123+1G>T"),
            ("c.76_78del", "c.76_79del"),
            ("17p13.1", "17q13.1"),
            ("≈5 mg", "5 mg"),
            ("一片半", "一片"),
            ("每次一片半", "每次一片"),
            ("Group A", "Group B"),
            ("Part A", "Part B"),
            ("不超过5 mg", "不少于5 mg"),
            ("至少5 mg", "至多5 mg"),
            ("大于5 mg", "小于5 mg"),
            ("5 mg以上", "5 mg以下"),
            ("约为5 mg", "5 mg"),
            ("p<0.05", "p>0.05"),
            ("P≤0.05", "P≥0.05"),
            ("n≥10", "n≤10"),
            ("BMI≥30 kg/m2", "BMI≤30 kg/m2"),
            ("HR>1", "HR<1"),
            ("HbA1c≥7%", "HbA1c≤7%"),
            ("eGFR≥60 mL/min", "eGFR≤60 mL/min"),
            ("SpO2<90%", "SpO2>90%"),
            ("PaO2≤60 mmHg", "PaO2≥60 mmHg"),
            ("mRS≤2", "mRS≥2"),
            ("QTc>500 ms", "QTc<500 ms"),
        ):
            with self.subTest(source=source):
                self.assertEqual("violated", check_protected_tokens(source, proposal).status)

    def test_dosing_abbreviations_are_case_equivalent(self):
        self.assertEqual("verified", check_protected_tokens("给药 QD", "给药 qd").status)
        self.assertEqual("verified", check_protected_tokens("Phase I", "phase I").status)
        self.assertEqual("verified", check_protected_tokens("Arm A", "arm A").status)
        self.assertEqual("verified", check_protected_tokens("≈5 mg", "~5 mg").status)
        self.assertEqual("verified", check_protected_tokens("约为5 mg", "~5 mg").status)
        self.assertEqual("verified", check_protected_tokens("至少5 mg", "≥5 mg").status)
        self.assertEqual("verified", check_protected_tokens("不超过5 mg", "≤5 mg").status)
        self.assertEqual("verified", check_protected_tokens("大于5 mg", ">5 mg").status)
        self.assertEqual("verified", check_protected_tokens("小于5 mg", "<5 mg").status)
        self.assertEqual("verified", check_protected_tokens("5 mg以上", "≥5 mg").status)
        self.assertEqual("verified", check_protected_tokens("p < 0.05", "p<0.05").status)
        self.assertEqual("verified", check_protected_tokens("P<=0.05", "P≤0.05").status)
        self.assertEqual("verified", check_protected_tokens("p<0.05", "P < 0.05").status)
        self.assertEqual("verified", check_protected_tokens("BMI≥30 kg/m2", "BMI >=30 kg/m^2").status)


if __name__ == "__main__":
    unittest.main()
