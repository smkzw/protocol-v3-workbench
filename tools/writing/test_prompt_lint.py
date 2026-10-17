"""prompt_lint 独立自测（不依赖主 tests/ 套件）。

运行方式：
    python3 tools/writing/test_prompt_lint.py
    python3 -m unittest discover -s tools/writing -p "test_*.py" -t tools/writing
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import prompt_lint  # noqa: E402


def terms(**overrides) -> dict:
    """测试夹具：最小术语表，可按层覆盖。"""
    base = {
        "drugs": [],
        "diseases": [],
        "scales": [],
        "allowlist": [],
        "layer_budgets": {"L0": 800, "L1": 400},
    }
    base.update(overrides)
    return base


class TestPassCases(unittest.TestCase):
    def test_clean_l0_passes(self) -> None:
        report = prompt_lint.lint_prompt(
            "你是中文临床研究方案撰写专家。只依据允许来源与已确认事实写作。",
            "L0",
            terms(),
        )
        self.assertTrue(report["pass"])
        self.assertEqual(report["violations"], [])
        self.assertEqual(report["layer"], "L0")

    def test_budget_boundary_800_passes(self) -> None:
        report = prompt_lint.lint_prompt("字" * 800, "L0", terms())
        self.assertTrue(report["pass"])
        self.assertEqual(report["char_count"], 800)

    def test_l1_budget_boundary_400_fails(self) -> None:
        report = prompt_lint.lint_prompt("字" * 401, "L1", terms())
        self.assertFalse(report["pass"])
        rules = {v["rule"] for v in report["violations"]}
        self.assertIn("budget_L1", rules)


class TestTermRules(unittest.TestCase):
    def test_drug_name_fails(self) -> None:
        report = prompt_lint.lint_prompt(
            "患者随机接受依库珠单抗治疗。", "L1", terms(drugs=["依库珠单抗"])
        )
        self.assertFalse(report["pass"])
        v = report["violations"][0]
        self.assertEqual(v["rule"], "drug_name")
        self.assertEqual(v["span"], "依库珠单抗")
        self.assertIn("依库珠单抗", v["hit"])

    def test_disease_name_ascii_case_insensitive(self) -> None:
        report = prompt_lint.lint_prompt(
            "本品适用于 pnh 患者。", "L1", terms(diseases=["PNH"])
        )
        self.assertFalse(report["pass"])
        self.assertEqual(report["violations"][0]["rule"], "disease_name")
        self.assertEqual(report["violations"][0]["span"], "pnh")

    def test_scale_name_fails(self) -> None:
        report = prompt_lint.lint_prompt(
            "不得自行新增DLQI采集时点。", "L1", terms(scales=["DLQI"])
        )
        self.assertFalse(report["pass"])
        self.assertEqual(report["violations"][0]["rule"], "scale_name")

    def test_allowlist_suppresses_match(self) -> None:
        report = prompt_lint.lint_prompt(
            "参照 ICH E6(R3) 执行。", "L0",
            terms(allowlist=["ICH E6(R3)"]),
        )
        self.assertTrue(report["pass"], report)


class TestFixedRules(unittest.TestCase):
    def test_defect_id_new_p0_r(self) -> None:
        for probe in ("P0-12", "NEW-37", "R11"):
            with self.subTest(probe=probe):
                report = prompt_lint.lint_prompt(
                    f"补丁说明 {probe} 生效。", "L0", terms()
                )
                self.assertFalse(report["pass"])
                self.assertEqual(report["violations"][0]["rule"], "defect_id")
                self.assertEqual(report["violations"][0]["span"], probe)

    def test_defect_id_not_inside_word(self) -> None:
        report = prompt_lint.lint_prompt("备用字段PART2x说明。", "L0", terms())
        self.assertTrue(report["pass"], report)

    def test_round_wording_chinese(self) -> None:
        report = prompt_lint.lint_prompt("NEW-37（新纪元第7轮末修订）", "L0", terms())
        rules = {v["rule"] for v in report["violations"]}
        self.assertIn("round_wording", rules)
        self.assertIn("defect_id", rules)

    def test_round_wording_english_word_only(self) -> None:
        hit = prompt_lint.lint_prompt("please review in round 2", "L0", terms())
        self.assertFalse(hit["pass"])
        self.assertEqual(hit["violations"][0]["rule"], "round_wording")
        clean = prompt_lint.lint_prompt("the background section", "L0", terms())
        self.assertTrue(clean["pass"], clean)


class TestReportShape(unittest.TestCase):
    def test_violation_keys_exact(self) -> None:
        report = prompt_lint.lint_prompt(
            "不得新增DLQI采集时点。", "L1", terms(scales=["DLQI"])
        )
        self.assertEqual(
            set(report["violations"][0].keys()), {"rule", "span", "hit"}
        )
        for key in ("layer", "pass", "char_count", "budget", "violations"):
            self.assertIn(key, report)

    def test_invalid_layer_rejected(self) -> None:
        with self.assertRaises(ValueError):
            prompt_lint.lint_prompt("任意文本", "L2", terms())


class TestShippedDataFile(unittest.TestCase):
    """随附 lint_terms.json 必须可加载且结构完整。"""

    def test_default_terms_load(self) -> None:
        loaded = prompt_lint.load_terms()
        for key in ("drugs", "diseases", "scales", "allowlist", "layer_budgets"):
            self.assertIn(key, loaded)
        self.assertGreater(len(loaded["drugs"]), 0, "数据文件应含示例术语")
        self.assertGreater(len(loaded["scales"]), 0)

    def test_budgets_come_from_data_file(self) -> None:
        loaded = prompt_lint.load_terms()
        self.assertEqual(loaded["layer_budgets"]["L0"], 800)
        self.assertEqual(loaded["layer_budgets"]["L1"], 400)


class TestGeneralization(unittest.TestCase):
    """泛化检查：lint/builder 实现代码中不得出现具体药物/疾病/量表名。"""

    def test_no_medical_terms_in_implementation_code(self) -> None:
        loaded = prompt_lint.load_terms()
        medical = [
            t
            for key in ("drugs", "diseases", "scales")
            for t in loaded[key]
            if not t.startswith("示例")
        ]
        self.assertGreater(len(medical), 0)
        for source_name in ("prompt_lint.py", "section_card_builder.py"):
            source = (HERE / source_name).read_text(encoding="utf-8")
            for term in medical:
                self.assertNotIn(
                    term, source, f"{source_name} 不得硬编码术语：{term}"
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
