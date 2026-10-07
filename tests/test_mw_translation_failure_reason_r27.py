"""R27 自检（本轮）③产品侧补丁：翻译条目失败原因回显真实拒因。

现场（批次 wref_translation_batch_c4e1c16e…，16项 failed_retryable）：
底层拒因是编排器 LifecycleRefusal（refusing to stop a server we do not
own——8002 被非本部署进程占用，相位切换被拒），但条目 error_detail 只写
『监管中文候选生成未完成；批次响应不回显供应商原始错误，请按错误码
重试。』——把环境性阻断伪装成可重试抖动，现场照此连重试3轮×20项，烧掉
约2.5小时与3次durable尝试后仍同错。

契约（红先修后）：translation_generation_failed 的公开文案在异常链携带
编排器拒因（LifecycleRefusal / server_unowned / not this deployment 等）
时，必须把该拒因要点附在 error_detail/blocker_message 末尾（人话+可行动：
说明重试不会好转、需处置模型服务器占用），而不是一律『请按错误码重试』。
"""

from __future__ import annotations

import unittest

from services.api.app.writing_reference_translation_batch import (
    WritingReferenceTranslationBatchService,
)


class _FakeRepo:
    def _append_audit(self, *args, **kwargs):
        return None


def _service() -> WritingReferenceTranslationBatchService:
    service = object.__new__(WritingReferenceTranslationBatchService)
    service.repository = _FakeRepo()
    return service


def _refusal_exc() -> Exception:
    """Mimic the field exception chain: AiProviderRuntimeError caused by LifecycleRefusal."""
    from services.api.app.model_lifecycle_orchestrator import LifecycleRefusal

    refusal = LifecycleRefusal(
        "server_unowned",
        "refusing to stop a server we do not own "
        "(live listener is not this deployment) "
        "(switch retried 2x, budget capped)",
    )
    runtime = RuntimeError(
        "AiProviderRuntimeError: translation dispatch refused by orchestrator"
    )
    runtime.__cause__ = refusal
    return runtime


class FailureDetailEchoesRefusalReasonTests(unittest.TestCase):
    def test_orchestrator_refusal_surfaces_in_public_detail(self):
        service = _service()
        detail = service._public_failure_detail(
            "translation_generation_failed", error=_refusal_exc()
        )
        self.assertIn("模型服务器", detail, (
            "编排器拒因必须上屏（现场：环境性阻断被写成『请按错误码重试』，"
            "误导连重试3轮×20项约2.5小时）。"
        ))
        self.assertIn("不会自行好转", detail)
        # 真实拒因关键词之一必须出现（拒绝停非本部署进程）。
        self.assertTrue(
            ("不属于本系统" in detail) or ("we do not own" in detail)
            or ("占用" in detail),
            f"实际文案：{detail}",
        )

    def test_generic_detail_without_refusal_unchanged(self):
        service = _service()
        detail = service._public_failure_detail(
            "translation_generation_failed",
            error=RuntimeError("some unrelated provider hiccup"),
        )
        self.assertIn("监管中文候选生成未完成", detail)
        self.assertNotIn("模型服务器占用", detail)

    def test_refusal_detection_walks_cause_chain(self):
        service = _service()
        outer = ValueError("wrapped failure")
        outer.__cause__ = _refusal_exc()
        detail = service._public_failure_detail(
            "translation_generation_failed", error=outer
        )
        self.assertIn("模型服务器", detail)


if __name__ == "__main__":
    unittest.main()
