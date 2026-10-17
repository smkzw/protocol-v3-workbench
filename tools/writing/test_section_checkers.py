"""section_checkers 独立自测（不依赖主 tests/ 套件）。

运行方式：
    python3 tools/writing/test_section_checkers.py
    python3 -m unittest discover -s tools/writing -p "test_*.py" -t tools/writing
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import section_checkers  # noqa: E402


# ---------------------------------------------------------------------------
# 测试夹具：全部使用虚构实体（无任何真实药物/疾病/量表名），证明机制通用。
# ---------------------------------------------------------------------------

FACTS = {
    "endpoints.primary": "指标甲75应答率",
    "design.arms": ["A组", "B组"],
    "intervention.dose_regimen": "XX-1 600 mg q4w",
    "intervention.prev_dose": "600 mg",
    "sample_size.total": 240,
    "schedule.visit_weeks": [0, 4, 12],
}

STYLEKIT = {
    "kit_id": "kit-1",
    "per_node_examples": {
        "n1": [
            {"text": "Patients received YY-2 300 mg q4w (N=321).", "study_key": "s1"},
            {"text": "安慰剂组受试者每4周接受一次给药。", "study_key": "s1"},
        ]
    },
    "terminology": {"drug_class_terms": ["XX类抑制剂"], "endpoint_names_zh": ["指标甲"]},
    "length_profile": {},
}

ANCHORS = {
    "sample_size.total": ["样本量"],
    "schedule.visit_weeks": ["访视"],
}


def result_keys() -> set:
    """checker_results 必含 SCHEMAS.md §8 的三字段。"""
    return {"checker", "severity", "detail"}


class FactConsistencyTests(unittest.TestCase):
    def test_clean_text_has_no_findings(self) -> None:
        text = "受试者随机接受XX-1 600 mg q4w给药，主要终点为指标甲75应答率。"
        self.assertEqual(section_checkers.check_fact_consistency(text, FACTS), [])

    def test_dose_digit_conflict_is_fail(self) -> None:
        text = "受试者接受XX-1 800 mg q4w给药。"
        results = section_checkers.check_fact_consistency(text, FACTS)
        self.assertTrue(results)
        top = results[0]
        self.assertTrue(result_keys() <= set(top))
        self.assertEqual(top["checker"], "fact_consistency")
        self.assertEqual(top["severity"], "fail")
        self.assertIn("intervention.dose_regimen", top["detail"])
        self.assertIn("600", top["detail"])
        self.assertIn("800", top["detail"])

    def test_endpoint_digit_conflict_is_fail(self) -> None:
        text = "主要终点为指标甲90应答率。"
        results = section_checkers.check_fact_consistency(text, FACTS)
        self.assertEqual(results[0]["severity"], "fail")
        self.assertIn("endpoints.primary", results[0]["detail"])

    def test_exact_match_is_not_flagged(self) -> None:
        text = "终点评估采用指标甲75应答率作为主要终点。"
        self.assertEqual(section_checkers.check_fact_consistency(text, FACTS), [])

    def test_correct_and_wrong_value_both_present_is_flagged(self) -> None:
        # 正文同时含正确值与错误值：任一处不一致都要报。
        text = "受试者接受XX-1 600 mg q4w给药；挽救治疗时可增至XX-1 800 mg q4w。"
        results = section_checkers.check_fact_consistency(text, FACTS)
        kinds = [r.get("kind") for r in results]
        self.assertIn("value_conflict", kinds)
        self.assertIn("800", results[0]["detail"])

    def test_weak_fact_without_anchor_not_judged(self) -> None:
        # 弱锚事实（纯"数字+单位"）无锚词不做判断：文献引用剂量不得误报。
        text = "对照组给药为800 mg。文献报道YY-2 300 mg q4w用于既往治疗。"
        self.assertEqual(section_checkers.check_fact_consistency(text, FACTS), [])

    def test_weak_fact_with_anchor_conflict_is_fail(self) -> None:
        anchors = {"intervention.prev_dose": ["剂量"]}
        text = "对照组给药剂量为800 mg。"
        results = section_checkers.check_fact_consistency(text, FACTS, fact_anchors=anchors)
        kinds = [r.get("kind") for r in results]
        self.assertIn("anchored_number_conflict", kinds)
        for r in results:
            if r.get("kind") == "anchored_number_conflict":
                self.assertEqual(r["severity"], "fail")
                self.assertIn("intervention.prev_dose", r["detail"])

    def test_unit_conversion_consistent(self) -> None:
        anchors = {"intervention.prev_dose": ["剂量"]}
        text = "给药剂量为0.6 g。"
        self.assertEqual(
            section_checkers.check_fact_consistency(text, FACTS, fact_anchors=anchors), []
        )

    def test_same_digits_different_unit_is_flagged(self) -> None:
        anchors = {"intervention.prev_dose": ["剂量"]}
        text = "给药剂量为600 g。"
        results = section_checkers.check_fact_consistency(text, FACTS, fact_anchors=anchors)
        kinds = [r.get("kind") for r in results]
        self.assertIn("unit_mismatch", kinds)

    def test_other_entity_context_not_flagged(self) -> None:
        # 正文引用他药不同剂量（上下文实体不同）不得误报本方案事实冲突。
        text = "文献报道YY-2 300 mg q4w用于既往治疗。"
        self.assertEqual(section_checkers.check_fact_consistency(text, FACTS), [])

    def test_fullwidth_digits_normalized(self) -> None:
        text = "受试者接受XX-1 ８００ ｍｇ q4w给药。"
        results = section_checkers.check_fact_consistency(text, FACTS)
        self.assertEqual(results[0]["severity"], "fail")

    def test_anchored_sample_size_conflict(self) -> None:
        text = "本研究样本量预计为244例。"
        results = section_checkers.check_fact_consistency(text, FACTS, fact_anchors=ANCHORS)
        kinds = [r.get("kind") for r in results]
        self.assertIn("anchored_number_conflict", kinds)
        for r in results:
            if r.get("kind") == "anchored_number_conflict":
                self.assertEqual(r["severity"], "fail")
                self.assertIn("sample_size.total", r["detail"])

    def test_anchored_sample_size_correct(self) -> None:
        text = "本研究样本量预计为240例。"
        self.assertEqual(
            section_checkers.check_fact_consistency(text, FACTS, fact_anchors=ANCHORS), []
        )

    def test_anchored_sample_size_comma_format(self) -> None:
        facts = dict(FACTS, **{"sample_size.total": 1200})
        text = "本研究样本量预计为1,200例。"
        self.assertEqual(
            section_checkers.check_fact_consistency(text, facts, fact_anchors=ANCHORS), []
        )

    def test_anchored_visit_set_conflict(self) -> None:
        text = "受试者于第8周进行访视评估。"
        results = section_checkers.check_fact_consistency(text, FACTS, fact_anchors=ANCHORS)
        kinds = [r.get("kind") for r in results]
        self.assertIn("anchored_set_conflict", kinds)

    def test_anchored_visit_set_correct(self) -> None:
        text = "受试者于第12周进行访视评估，同时评估指标甲75应答率。"
        self.assertEqual(
            section_checkers.check_fact_consistency(text, FACTS, fact_anchors=ANCHORS), []
        )

    def test_no_anchor_no_numeric_check(self) -> None:
        # 未提供锚词时，纯数字事实不猜测上下文（避免泛化误报）。
        text = "本研究样本量预计为244例。"
        self.assertEqual(section_checkers.check_fact_consistency(text, FACTS), [])

    def test_inputs_not_mutated(self) -> None:
        facts_snapshot = copy.deepcopy(FACTS)
        text = "受试者接受XX-1 800 mg q4w，主要终点为指标甲90应答率。"
        section_checkers.check_fact_consistency(text, FACTS, fact_anchors=ANCHORS)
        self.assertEqual(FACTS, facts_snapshot)


class StyleLeakageTests(unittest.TestCase):
    def test_competitor_entity_leak(self) -> None:
        text = "对照组采用YY-2进行治疗。"
        results = section_checkers.check_style_leakage(text, STYLEKIT, FACTS)
        self.assertTrue(results)
        self.assertEqual(results[0]["checker"], "style_leakage")
        self.assertEqual(results[0]["severity"], "fail")
        self.assertIn("YY-2", results[0]["detail"])

    def test_own_entity_not_flagged(self) -> None:
        text = "试验药为XX-1，评估指标甲75应答率。"
        self.assertEqual(section_checkers.check_style_leakage(text, STYLEKIT, FACTS), [])

    def test_competitor_dose_pair_leak(self) -> None:
        text = "试验组给药剂量为300 mg。"
        results = section_checkers.check_style_leakage(text, STYLEKIT, FACTS)
        kinds = [r.get("kind") for r in results]
        self.assertIn("competitor_number_unit", kinds)

    def test_own_dose_pair_not_flagged(self) -> None:
        text = "试验组给药剂量为600 mg。"
        self.assertEqual(
            section_checkers.check_style_leakage(text, STYLEKIT, FACTS), []
        )

    def test_competitor_sample_size_leak(self) -> None:
        text = "本研究共入组321例受试者。"
        results = section_checkers.check_style_leakage(text, STYLEKIT, FACTS)
        kinds = [r.get("kind") for r in results]
        self.assertIn("competitor_number", kinds)

    def test_small_numbers_not_flagged(self) -> None:
        # 范例中“每4周”的小数字与本项目访视周一致，不构成泄漏。
        text = "每4周给药一次。"
        self.assertEqual(section_checkers.check_style_leakage(text, STYLEKIT, FACTS), [])

    def test_generic_tokens_not_flagged_as_entity(self) -> None:
        # mg / q4w / 普通英文词属于通用词，不作为竞品实体。
        text = "600 mg，q4w，patients received placebo。"
        results = section_checkers.check_style_leakage(text, STYLEKIT, FACTS)
        kinds = {r.get("kind") for r in results}
        self.assertNotIn("competitor_entity", kinds)

    def test_allowlist_exempts(self) -> None:
        text = "对照组采用YY-2进行治疗。"
        results = section_checkers.check_style_leakage(
            text, STYLEKIT, FACTS, allowlist=["YY-2"]
        )
        kinds = {r.get("kind") for r in results}
        self.assertNotIn("competitor_entity", kinds)

    def test_competitor_names_field(self) -> None:
        kit = dict(copy.deepcopy(STYLEKIT), competitor_names=["复方对照片"])
        text = "对照组为复方对照片。"
        results = section_checkers.check_style_leakage(text, kit, FACTS)
        kinds = [r.get("kind") for r in results]
        self.assertIn("competitor_entity", kinds)

    def test_no_stylekit_no_findings(self) -> None:
        text = "对照组采用YY-2进行治疗。"
        self.assertEqual(section_checkers.check_style_leakage(text, None, FACTS), [])


class CrossSectionTests(unittest.TestCase):
    def test_divergent_endpoint_flagged(self) -> None:
        sections = [
            {"section_id": "s1", "text": "主要终点为指标甲75应答率。"},
            {"section_id": "s2", "text": "本研究的主要终点为指标甲90应答率。"},
        ]
        results = section_checkers.check_cross_section_consistency(sections)
        self.assertTrue(results)
        top = results[0]
        self.assertEqual(top["checker"], "cross_section_consistency")
        self.assertEqual(top["severity"], "fail")
        self.assertIn("s1", top["detail"])
        self.assertIn("s2", top["detail"])

    def test_consistent_sections_not_flagged(self) -> None:
        sections = [
            {"section_id": "s1", "text": "主要终点为指标甲75应答率。"},
            {"section_id": "s2", "text": "主要终点：指标甲75应答率。"},
        ]
        self.assertEqual(section_checkers.check_cross_section_consistency(sections), [])

    def test_unrelated_contexts_not_flagged(self) -> None:
        sections = [
            {"section_id": "s1", "text": "受试者于第12周进行访视评估。"},
            {"section_id": "s2", "text": "安全性随访在第16周结束。"},
        ]
        self.assertEqual(section_checkers.check_cross_section_consistency(sections), [])

    def test_dose_frequency_divergence_flagged(self) -> None:
        sections = [
            {"section_id": "s1", "text": "试验药XX-1 600 mg q4w给药。"},
            {"section_id": "s2", "text": "试验药XX-1 600 mg q2w给药。"},
        ]
        results = section_checkers.check_cross_section_consistency(sections)
        self.assertTrue(results)

    def test_calendar_dates_not_flagged(self) -> None:
        sections = [
            {"section_id": "s1", "text": "方案签署日期为2026年10月1日。"},
            {"section_id": "s2", "text": "启动会日期为2026年11月20日。"},
        ]
        self.assertEqual(section_checkers.check_cross_section_consistency(sections), [])

    def test_proposal_text_key_supported(self) -> None:
        sections = [
            {"section_id": "s1", "proposal_text": "样本量为240例。"},
            {"section_id": "s2", "proposal_text": "样本量为244例。"},
        ]
        results = section_checkers.check_cross_section_consistency(sections)
        self.assertTrue(results)


class ProcessTalkTests(unittest.TestCase):
    def test_placeholder_marker_is_fail(self) -> None:
        text = "安全性监测【待补齐】。"
        results = section_checkers.check_process_talk(text)
        self.assertEqual(results[0]["severity"], "fail")
        self.assertEqual(results[0]["checker"], "process_talk")

    def test_bracketed_placeholder_reported_once(self) -> None:
        # 【待补齐】整体命中后，内部"待补齐"不再重复报。
        results = section_checkers.check_process_talk("安全性监测【待补齐】。")
        placeholders = [r for r in results if r.get("kind") == "placeholder"]
        self.assertEqual(len(placeholders), 1)
        self.assertEqual(placeholders[0]["span"], "【待补齐】")

    def test_tbd_placeholder_is_fail(self) -> None:
        results = section_checkers.check_process_talk("剂量信息TBD。")
        self.assertEqual(results[0]["severity"], "fail")

    def test_process_wording_is_warn(self) -> None:
        results = section_checkers.check_process_talk("具体剂量将在正式文本中明确。")
        self.assertEqual(results[0]["severity"], "warn")

    def test_ai_self_reference_is_warn(self) -> None:
        results = section_checkers.check_process_talk("作为AI语言模型，我无法确定。")
        severities = [r["severity"] for r in results]
        self.assertIn("warn", severities)

    def test_code_fence_artifact_is_warn(self) -> None:
        results = section_checkers.check_process_talk("正文如下：\n```\n一些内容\n```")
        kinds = {r.get("kind") for r in results}
        self.assertIn("engineering_artifact", kinds)

    def test_clean_text_no_findings(self) -> None:
        text = "受试者随机接受试验药或对照药，给药周期为12周。"
        self.assertEqual(section_checkers.check_process_talk(text), [])

    def test_extra_patterns_supported(self) -> None:
        results = section_checkers.check_process_talk(
            "正文包含内部标记ZEBRA-FLAG。",
            extra_patterns=[{"id": "internal_flag", "pattern": "ZEBRA-FLAG", "severity": "warn"}],
        )
        self.assertTrue(results)
        self.assertEqual(results[0]["severity"], "warn")

    def test_findings_carry_required_keys_only_data(self) -> None:
        results = section_checkers.check_process_talk("待确认TBD")
        for item in results:
            self.assertTrue(result_keys() <= set(item))
            self.assertNotIn("replacement", item)
            self.assertNotIn("fixed_text", item)


class IntegrationTests(unittest.TestCase):
    def test_run_section_checkers_merges_all(self) -> None:
        text = "受试者接受XX-1 800 mg q4w。对照组采用YY-2。内容【待补齐】。"
        results = section_checkers.run_section_checkers(
            text, FACTS, STYLEKIT, fact_anchors=ANCHORS
        )
        checkers = {r["checker"] for r in results}
        self.assertIn("fact_consistency", checkers)
        self.assertIn("style_leakage", checkers)
        self.assertIn("process_talk", checkers)
        for item in results:
            self.assertTrue(result_keys() <= set(item))

    def test_results_json_serializable(self) -> None:
        text = "受试者接受XX-1 800 mg q4w。【待补齐】"
        results = section_checkers.run_section_checkers(text, FACTS, STYLEKIT)
        json.dumps(results, ensure_ascii=False)

    def test_no_rewrite_api(self) -> None:
        # 只标记不改写：模块不得提供任何改写/替换正文的函数。
        public = [name for name in dir(section_checkers) if not name.startswith("_")]
        banned = ("rewrite", "fix", "repair", "replace", "sanitize")
        for name in public:
            for word in banned:
                self.assertNotIn(word, name.lower(), f"公开 API 不得包含改写语义：{name}")


class CliTests(unittest.TestCase):
    def _run_cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(HERE / "section_checkers.py"), *args],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_cli_clean_exit_zero(self) -> None:
        facts_file = HERE / "_tmp_cli_facts.json"
        text_file = HERE / "_tmp_cli_text.txt"
        try:
            facts_file.write_text(json.dumps(FACTS, ensure_ascii=False), encoding="utf-8")
            text_file.write_text("受试者接受XX-1 600 mg q4w给药。", encoding="utf-8")
            proc = self._run_cli("--file", str(text_file), "--facts", str(facts_file))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["checker_results"], [])
        finally:
            facts_file.unlink(missing_ok=True)
            text_file.unlink(missing_ok=True)

    def test_cli_conflict_exit_one(self) -> None:
        facts_file = HERE / "_tmp_cli_facts.json"
        text_file = HERE / "_tmp_cli_text.txt"
        try:
            facts_file.write_text(json.dumps(FACTS, ensure_ascii=False), encoding="utf-8")
            text_file.write_text("受试者接受XX-1 800 mg q4w给药。", encoding="utf-8")
            proc = self._run_cli("--file", str(text_file), "--facts", str(facts_file))
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["checker_results"])
        finally:
            facts_file.unlink(missing_ok=True)
            text_file.unlink(missing_ok=True)


class GeneralizationRedLineTests(unittest.TestCase):
    def test_module_contains_no_concrete_terms(self) -> None:
        # 泛化红线：本包代码不得出现具体药物/疾病/量表名（词表来自
        # prompt_lint 的 lint_terms.json 数据文件，只读复用，不在代码写死）。
        terms_path = HERE / "lint_terms.json"
        if not terms_path.exists():
            self.skipTest("lint_terms.json 不存在，跳过")
        terms = json.loads(terms_path.read_text(encoding="utf-8"))
        source = (HERE / "section_checkers.py").read_text(encoding="utf-8")
        for category in ("drugs", "diseases", "scales"):
            for term in terms.get(category, []):
                if term:
                    self.assertNotIn(term, source, f"代码中出现具体术语：{term}")

    def test_test_fixture_terms_are_synthetic(self) -> None:
        terms_path = HERE / "lint_terms.json"
        if not terms_path.exists():
            self.skipTest("lint_terms.json 不存在，跳过")
        terms = json.loads(terms_path.read_text(encoding="utf-8"))
        source = Path(__file__).read_text(encoding="utf-8")
        for category in ("drugs", "diseases", "scales"):
            for term in terms.get(category, []):
                if term:
                    self.assertNotIn(term, source, f"测试夹具出现真实术语：{term}")


if __name__ == "__main__":
    unittest.main()
