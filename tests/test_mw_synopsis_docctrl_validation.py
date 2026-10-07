"""R27 第2轮末修订 批A②（NEW-P0-08 / NEW-P1-22）：入口B校验降粒度。

现场（R2-D）：『chunk 0 validation failed: protocol synopsis non-default
value requires source evidence at framing.version』——文控字段（版本/日期/
代号）被模型填值但未逐字段挂证据span→_validate_protocol_synopsis_nested_
contract 整chunk否决→确认屏永远不出现（叠加模型超时=端到端建不成）。
另有 P1-22：标题粘文控行（『版本：1.0 日期：… 研究代号：KZ-6210』整串）、
版本1.0错成V0.1——文控字段交给自由抽取。

修复契约（红先修后）：
- ①文控字段（framing.version / framing.protocol_id）走确定性后处理：从
  源文档文本按行正则（『版本：X』『研究代号：X/方案编号：X』）抽取；
  模型值与之一致→采纳并自动挂 docctrl 证据；不一致→以确定性值为准并
  记入 docctrl_overrides 差异清单（供确认屏显示）；
- ②其余字段缺证据时不再整chunk报错：字段回退默认值+追加 missing_fields
  （确认屏标黄路径），校验返回0错误；
- ③守卫：嵌套契约的真实类型错误仍报错；已挂证据字段不动。
"""

from __future__ import annotations

import unittest

from services.api.app.ai_task_runner import AiTaskRunner


DOC_TEXT = (
    "KZ-6210治疗慢性咳嗽的II期临床研究方案\n"
    "版本：1.0\n"
    "日期：2026年10月4日\n"
    "研究代号：KZ-6210\n"
    "本研究为随机双盲安慰剂对照研究。\n"
)


def _base_study_definition() -> dict:
    return {
        "framing": {
            "protocol_id": "KZ-6210",
            "version": "1.0",
            "document_title": "KZ-6210治疗慢性咳嗽的II期临床研究方案",
        },
        "picos": {},
        "field_evidence_span_ids": {},
        "missing_fields": [],
    }


class DocControlDeterministicExtractionTests(unittest.TestCase):
    def _validate(self, study_definition: dict):
        return AiTaskRunner._validate_protocol_synopsis_nested_contract(
            None, study_definition, source_text=DOC_TEXT
        )

    def test_doc_control_fields_without_evidence_no_longer_fail_whole_chunk(self):
        sd = _base_study_definition()
        errors = self._validate(sd)
        self.assertEqual(
            [],
            [e for e in errors if "framing.version" in e or "framing.protocol_id" in e],
            "文控字段（版本/代号）缺证据span不得整chunk否决（现场：确认屏"
            "永不出現，端到端建不成）。",
        )
        self.assertEqual([], errors)
        # 确定性值已自动挂证据
        evidence = sd["field_evidence_span_ids"]
        self.assertTrue(evidence.get("framing.version"))
        self.assertTrue(evidence.get("framing.protocol_id"))
        self.assertEqual("1.0", sd["framing"]["version"])

    def test_model_drift_loses_to_deterministic_value_with_recorded_override(self):
        sd = _base_study_definition()
        sd["framing"]["version"] = "V0.1"  # 现场：1.0 被错抽成 V0.1
        errors = self._validate(sd)
        self.assertEqual([], errors)
        self.assertEqual(
            "1.0",
            sd["framing"]["version"],
            "模型值与源文档不一致时以确定性抽取值为准（现场P1-22：1.0→V0.1）。",
        )
        overrides = sd.get("docctrl_overrides") or {}
        self.assertEqual(
            {"model": "V0.1", "deterministic": "1.0"},
            overrides.get("framing.version"),
            "差异必须记录，供确认屏如实显示。",
        )

    def test_non_doc_control_field_missing_evidence_degrades_not_fails(self):
        sd = _base_study_definition()
        sd["framing"]["population_intent"] = "慢性咳嗽成人患者"
        errors = self._validate(sd)
        self.assertEqual([], errors, "缺证据的非文控字段应降级而非整chunk失败。")
        self.assertIn(
            "framing.population_intent",
            sd.get("missing_fields", []),
            "降级字段必须记入missing_fields（确认屏标黄路径）。",
        )
        self.assertNotEqual(
            "慢性咳嗽成人患者",
            sd["framing"].get("population_intent"),
            "降级即回退默认值，不得携带无证据的模型值进入确认屏。",
        )

    def test_genuine_nested_contract_type_errors_still_fail(self):
        sd = _base_study_definition()
        sd["framing"]["intrinsic_objectives"] = "不是列表"
        errors = self._validate(sd)
        self.assertTrue(
            any("nested contract error" in e for e in errors),
            "真实类型错误仍必须报错（fail-closed）。",
        )

    def test_fields_with_existing_evidence_untouched(self):
        sd = _base_study_definition()
        sd["framing"]["population_intent"] = "慢性咳嗽成人患者"
        sd["field_evidence_span_ids"]["framing.population_intent"] = ["span_1"]
        errors = self._validate(sd)
        self.assertEqual([], errors)
        self.assertEqual(
            "慢性咳嗽成人患者",
            sd["framing"]["population_intent"],
            "已挂证据字段不得回退。",
        )


if __name__ == "__main__":
    unittest.main()
