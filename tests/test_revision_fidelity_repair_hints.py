# -*- coding: utf-8 -*-
"""SMOKE-r1-4 ⑦（R27 收敛修订）反例：保真缺漏修复轮不可执行。

跨轮现场（r2→r4）：医学修订在云端耗时50分钟级返回后仍被保真校验拒收——
『revision.proposal_text omits required source timing labels
['timing.last_dose']…omits source Roman-numeral level ranges…』。修复轮
（validation_errors 触发的一次重试）此前只把规范标签id（'timing.last_dose'）
放进错误串——模型无法把id映射回原文短语，修复照样缺漏。修后契约：修复
上下文携带 must_preserve_verbatim——从 allowed_sources 提取的必须逐字保留
的时间锚点短语与罗马数字分级区间原文；校验器本身不放松。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts import AiTaskRequest, AiTaskSourceRef
from services.api.app.ai_execution_policy import AiExecutionPolicyResolver
from services.api.app.ai_gateway import AiPromptEnvelope
from services.api.app.ai_task_runner import (
    AiTaskRunner,
    AiTaskRunStatus,
    AiTaskStore,
    _medical_writing_fidelity_preservation_hints,
)
from services.api.app.demo_repository import DemoRepository

SOURCE_TEXT = (
    "末次给药后28天内完成安全性随访；肝功能Child-Pugh分级为II至IV级的"
    "患者可入选本研究。"
)
PROJECT_ID = "proj_revision_fidelity_repair"
TIMING_PHRASE = "末次给药后"
ROMAN_PHRASE = "II至IV级"


def _source() -> AiTaskSourceRef:
    return AiTaskSourceRef(
        source_id="protocol_span_fidelity",
        source_type="protocol_docx_paragraph_selection",
        title="随访与入选",
        locator="docx:p88",
        text_preview=SOURCE_TEXT,
        project_id=PROJECT_ID,
        module="medical_writing",
    )


def _request() -> AiTaskRequest:
    return AiTaskRequest(
        module="medical_writing",
        task_type="medical_writing_revision",
        prompt_version="medical_writing_revision_v1_4",
        allowed_sources=[_source()],
        user_instruction="规范表述并保留全部医学事实。",
        task_context={
            "revision_intent": "medical_writing_revision",
            "intent_label": "改写",
            "directional_goal": "在不改变事实的前提下规范表达。",
            "preservation_rules": ["不得新增事实。"],
            "candidate_count": 3,
            "candidate_blueprints": ["标准版", "精炼版", "保守版"],
        },
    )


class _FidelityRepairProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(self):
        self.envelopes = []

    def _candidates(self, timing: str, roman: str):
        bodies = [
            (
                f"{timing}28天内完成安全性随访；肝功能Child-Pugh分级为"
                f"{roman}的患者可入选本研究。"
            ),
            (
                f"{timing}28天内完成安全性随访；经评估肝功能Child-Pugh"
                f"分级为{roman}的患者可入选本研究。"
            ),
            (
                f"{timing}28天内完成安全性随访；肝功能Child-Pugh分级"
                f"符合{roman}的患者可入选本研究。"
            ),
        ]

        def candidate(index: int) -> dict:
            return {
                "proposal_text": bodies[index],
                "rationale": "保留原文事实。",
                "diff_patch": "无正文变更：保留原文",
                "evidence_span_ids": ["revision_ev_1"],
            }

        return candidate

    def run(self, envelope: AiPromptEnvelope):
        self.envelopes.append(envelope)
        repairing = "repair_context" in envelope.payload
        # 首轮：丢时间锚点 + 改罗马分级区间（r2 现场的失败形态）
        # 修复轮：逐字保留两个必须短语
        timing = TIMING_PHRASE if repairing else "研究结束后"
        roman = ROMAN_PHRASE if repairing else "III至IV级"
        candidate = self._candidates(timing, roman)
        return {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.prompt_version,
            "input_source_ids": [
                item["source_id"]
                for item in envelope.payload["allowed_sources"]
            ],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "schema_version": "ai_task_output_v0_1",
            "findings": [],
            "evidence_spans": [
                {
                    "span_id": "revision_ev_1",
                    "source_id": "protocol_span_fidelity",
                    "locator": "docx:p88",
                    "quote": SOURCE_TEXT,
                }
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "revision": {
                **candidate(0),
                "alternatives": [
                    candidate(1),
                    candidate(2),
                ],
            },
        }


class FidelityPreservationHintsTests(unittest.TestCase):
    def test_hints_list_exact_source_phrases(self):
        hints = _medical_writing_fidelity_preservation_hints([_source()])
        phrases = {hint["phrase"] for hint in hints}
        kinds = {(hint["kind"], hint["phrase"]) for hint in hints}
        self.assertIn(TIMING_PHRASE, phrases)
        self.assertIn(ROMAN_PHRASE, phrases)
        self.assertIn(("timing_label", TIMING_PHRASE), kinds)
        self.assertIn(("roman_level_range", ROMAN_PHRASE), kinds)

    def test_hints_empty_without_matching_phrases(self):
        source = _source().model_copy(
            update={"text_preview": "本研究为随机双盲安慰剂对照研究。"}
        )
        self.assertEqual([], _medical_writing_fidelity_preservation_hints([source]))


class RevisionFidelityRepairTests(unittest.TestCase):
    def test_repair_pass_carries_verbatim_preservation_hints(self):
        provider = _FidelityRepairProvider()
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            runner = AiTaskRunner(
                DemoRepository(
                    repo_root / "demo_data" / "workbench_demo_v0_1.json"
                ),
                AiTaskStore(Path(tmp) / "ai_runs.jsonl"),
                provider_factory=lambda resolution: provider,
                policy_resolver=AiExecutionPolicyResolver(
                    deployment_profile="local_private_clinical",
                    provider_name="buddy",
                    model_name="deepseek-v4-pro",
                    test_only_provider_injection=True,
                ),
            )
            run = runner.submit_internal(PROJECT_ID, _request())

        # 修复轮生效后整体完成
        self.assertEqual(
            AiTaskRunStatus.COMPLETED, run.status, run.validation_errors
        )
        self.assertEqual(2, len(provider.envelopes))
        repair_payload = provider.envelopes[1].payload
        self.assertIn("repair_context", repair_payload)
        preserve = repair_payload["repair_context"].get(
            "must_preserve_verbatim"
        )
        self.assertIsNotNone(
            preserve, "保真缺漏修复必须携带逐字保留清单"
        )
        phrases = {item["phrase"] for item in preserve}
        self.assertIn(TIMING_PHRASE, phrases)
        self.assertIn(ROMAN_PHRASE, phrases)


if __name__ == "__main__":
    unittest.main()
