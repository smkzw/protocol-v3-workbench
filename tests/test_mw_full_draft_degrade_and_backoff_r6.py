"""R6 第6轮末修订 片B′（P0-25）：全文初稿校验宽容度 + 507 退避。

现场（r6-D proj 摘要，w6 截图39/48）：全文初稿 22 批续跑到 7→8 批后，
模型在 sections 里附带 `rationale_note` 等额外字段 →
`full_draft.sections[N] contains unexpected key` 整批拒绝 → 修复重试
循环 30+ 分钟无产出；再点生成立刻 HTTP 507（提供方容量），作业整单
失败（retryable=False），0 可用输出。

契约（红先修后）：
- T1 sections 未知字段降级：剥离+注记，不再产生 unexpected key 错误
  （关键字段缺失仍整批拒——既有语义不放宽）；
- T2 提供方 507 进入有界重试梯：按 Retry-After（有上限）退避，
  无头时指数退避；
- T3 批次失败（容量/校验）重试上限 ≤2 后跳过并标记，作业不再整单
  失败——其余批次照常产出候选。
"""

from __future__ import annotations

import unittest
from unittest import mock

from services.api.app.ai_gateway import (
    _validate_protocol_full_draft_output,
    sanitize_protocol_full_draft_sections,
)

EVIDENCE = {
    "ev1": {"span_id": "ev1", "source_id": "source_a"},
}


def _complete_section(extra: dict | None = None) -> dict:
    section = {
        "section_id": "sec_stat",
        "content_status": "complete",
        "proposal_text": (
            "主要终点采用分层Cochran-Mantel-Haenszel检验，双侧显著性水平0.05，"
            "并按筛选期疾病严重度与研究中心分层；次要终点按层级顺序检验并控制总体I类错误。"
            "样本量按预期应答率差异与脱落率估算，并在计划中期分析时保持盲态与既定的决策规则。"
        ),
        "rationale": "依据既定统计策略与项目研究事实。",
        "evidence_span_ids": ["ev1"],
        "decision_items": [],
        "missing_source_classes": [],
        "gap_items": [],
    }
    if extra:
        section.update(extra)
    return section


def _output_with(extra: dict | None = None) -> dict:
    return {
        "needs_medical_confirmation": True,
        "full_draft": {"sections": [_complete_section(extra)]},
    }


class FullDraftSectionDegradeTests(unittest.TestCase):
    def test_unknown_section_key_is_stripped_and_noted_not_rejected(self) -> None:
        output = _output_with({"rationale_note": "本节依据统计策略补写。"})
        notes = sanitize_protocol_full_draft_sections(output)
        # 剥离：未知键不再出现在输出里（运输契约保持严格）。
        self.assertNotIn("rationale_note", output["full_draft"]["sections"][0])
        self.assertTrue(
            any("rationale_note" in note for note in notes),
            "剥离必须留下可审计注记。",
        )
        errors = _validate_protocol_full_draft_output(output, EVIDENCE)
        self.assertFalse(
            any("unexpected key" in error for error in errors),
            f"未知字段不得再整批拒绝：{errors}",
        )

    def test_validator_direct_call_degrades_unknown_keys(self) -> None:
        output = _output_with({"rationale_note": "x", "extra_meta": 1})
        errors = _validate_protocol_full_draft_output(output, EVIDENCE)
        self.assertFalse(any("unexpected key" in error for error in errors))
        self.assertNotIn("rationale_note", output["full_draft"]["sections"][0])
        self.assertNotIn("extra_meta", output["full_draft"]["sections"][0])

    def test_missing_required_keys_still_fail_whole_output(self) -> None:
        section = _complete_section()
        section.pop("rationale")
        output = {
            "needs_medical_confirmation": True,
            "full_draft": {"sections": [section]},
        }
        errors = _validate_protocol_full_draft_output(output, EVIDENCE)
        self.assertTrue(
            any("missing required key: rationale" in error for error in errors),
            "关键字段缺失必须保持整批拒绝（fail-closed 语义不放宽）。",
        )


class Provider507BackoffTests(unittest.TestCase):
    def _provider(self):
        from services.api.app.ai_gateway import OpenAICompatibleAiProvider

        return OpenAICompatibleAiProvider(
            base_url="http://127.0.0.1:19999/v1",
            api_key="test-key",
            model_name="test-model",
            max_attempts=3,
            timeout_seconds=5,
        )

    def _envelope(self):
        from services.api.app.ai_gateway import AiPromptEnvelope, AiTaskType

        return AiPromptEnvelope(
            task_id="task_507_test",
            task_type=AiTaskType.PROTOCOL_FULL_DRAFT,
            prompt_version="v_test",
            system_prompt="test",
            payload={"instruction": "test"},
        )

    def test_507_is_retryable_and_honors_retry_after_header(self) -> None:
        import urllib.error

        provider = self._provider()
        responses = [
            urllib.error.HTTPError(
                provider.base_url, 507, "Insufficient Storage",
                {"Retry-After": "7"}, None,
            ),
            urllib.error.HTTPError(
                provider.base_url, 507, "Insufficient Storage", {}, None,
            ),
            urllib.error.HTTPError(
                provider.base_url, 507, "Insufficient Storage", {}, None,
            ),
        ]

        def fake_urlopen(request, timeout=None):
            raise responses.pop(0)

        sleeps: list[float] = []
        with mock.patch("services.api.app.ai_gateway.urllib.request.urlopen", fake_urlopen), \
                mock.patch("services.api.app.ai_gateway.time.sleep", sleeps.append):
            with self.assertRaises(Exception) as raised:
                provider.run(self._envelope())
        # 有界重试梯后按类型化错误浮出（不再首击即炸）。
        self.assertIn("507", str(raised.exception))
        self.assertEqual(2, len(sleeps), "3次尝试之间应恰有2次退避。")
        self.assertIn(7.0, sleeps, "Retry-After 头必须被采纳（首个退避=7s）。")


if __name__ == "__main__":
    unittest.main()
