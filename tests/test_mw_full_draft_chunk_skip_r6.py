"""R6 片B′（P0-25）续：全文初稿批次失败跳过并标记（不再整单失败）。

现场（r6-D w6截图39/48 + draft_poll.log）：第8/22批遇 HTTP 507（本地推理
层容量）→ 非校验类异常走 fail-fast → 整个作业 retryable=False 失败，
此前7批已生成的候选全部不可审阅（0 可用输出）。

契约（红先修后）：
- 批次异常分型：容量类（提供方507/5xx/空回包/梯级预算耗尽）与校验类
  （“未通过校验”）共享同一重试预算（≤2次重试），其余确定性错误保持
  fail-fast；
- 预算耗尽后：跳过该批并标记（chunk_index/section_ids/原因/次数），
  作业继续其余批次；
- 工件记录 skipped_chunks 与 coverage.skipped_section_ids；全部批次都
  失败时不落空工件（作业保持可续跑语义）。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _classify(exc: Exception) -> str:
    from services.api.app.medical_writing_full_draft import (
        classify_full_draft_chunk_failure,
    )

    return classify_full_draft_chunk_failure(exc)


class ChunkFailureClassificationTests(unittest.TestCase):
    def test_provider_507_is_capacity_class(self) -> None:
        from services.api.app.ai_gateway import AiProviderRuntimeError

        self.assertEqual(
            "capacity",
            _classify(
                AiProviderRuntimeError(
                    "AI provider request failed: HTTP 507",
                    diagnostics={"failure_code": "provider_http_error", "http_status": 507},
                )
            ),
        )

    def test_provider_ladder_budget_exhausted_is_capacity_class(self) -> None:
        from services.api.app.ai_gateway import AiProviderRuntimeError

        self.assertEqual(
            "capacity",
            _classify(
                AiProviderRuntimeError(
                    "AI provider retry ladder budget exhausted after 3 attempt(s)",
                    diagnostics={
                        "failure_code": "provider_ladder_budget_exhausted",
                        "exception_type": "TimeoutError",
                    },
                )
            ),
        )

    def test_validation_class(self) -> None:
        self.assertEqual(
            "validation",
            _classify(ValueError("独立AI全文初稿未通过校验：full_draft.sections 结构不完整")),
        )

    def test_deterministic_error_stays_fail_fast(self) -> None:
        self.assertEqual(
            "deterministic",
            _classify(RuntimeError("全文初稿上下文已变化，请重新生成候选")),
        )


class ChunkSkipAndMarkSourceContractTests(unittest.TestCase):
    def test_chunk_loop_skips_and_marks_after_bounded_retries(self) -> None:
        source = (
            ROOT / "services" / "api" / "app" / "medical_writing_full_draft.py"
        ).read_text(encoding="utf-8")

        self.assertIn("classify_full_draft_chunk_failure(", source)
        self.assertIn("skipped_chunks", source)
        self.assertIn("skipped_section_ids", source)
        # 容量/校验类重试后跳过并继续（而非整单 return DurableJobResult）。
        self.assertIn("已跳过", source)
        # 全部批次失败：不落空工件，保持可续跑（retryable=True）。
        self.assertIn("全部批次均未产出", source)

    def test_chunk_attempts_budget_is_at_most_two_retries(self) -> None:
        from services.api.app.medical_writing_full_draft import (
            FULL_DRAFT_CHUNK_ATTEMPTS,
        )

        self.assertLessEqual(FULL_DRAFT_CHUNK_ATTEMPTS, 3, "1次执行+至多2次重试。")

    def test_chunk_heartbeat_interval_is_at_most_60s(self) -> None:
        """R8 片Z（P1-45）：批级心跳≤60秒；末批校验重试附已耗时。"""
        from services.api.app.medical_writing_full_draft import (
            FULL_DRAFT_HEARTBEAT_INTERVAL_SECONDS,
        )

        self.assertLessEqual(
            FULL_DRAFT_HEARTBEAT_INTERVAL_SECONDS,
            60.0,
            "单批AI调用2~9.5分钟，心跳间隔必须≤60秒。",
        )
        source = (
            ROOT / "services" / "api" / "app" / "medical_writing_full_draft.py"
        ).read_text(encoding="utf-8")
        self.assertIn("keepalive", source)
        self.assertIn("仍在生成中", source)
        self.assertIn("末批校验中", source)


if __name__ == "__main__":
    unittest.main()
