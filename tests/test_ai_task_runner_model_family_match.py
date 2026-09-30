"""Owner directive 2026-10-01: MTPLX 模型身份校验改为同家族模糊匹配。

根因：MTPLX 以 --profile turbo 启动时，聊天响应的 model 字段自报
mtplx-flash-next-turbo（同一驻留模型在 speed/turbo/quality 档位下的别名），
而冻结路由期望 mtplx-flash-next-optimized-speed——严格相等把合法的全文初稿
输出整批判死（"独立AI全文初稿未通过校验：model mismatch"）。

边界（R14教训——模糊匹配不得放成语义洞）：
- 只对 mtplx-flash-next 前三段同家族放宽；其他 provider 仍严格相等；
- 回执仍记录原始 observed id；放宽命中写审计日志；
- 不同家族（如期望deepseek、实得mtplx）依旧拦截。
"""
import unittest

from services.api.app.ai_task_runner import _mtplx_model_family_match


class ModelFamilyMatchTests(unittest.TestCase):
    def test_exact_match_passes(self):
        self.assertTrue(
            _mtplx_model_family_match(
                "mtplx-flash-next-optimized-speed", "mtplx-flash-next-optimized-speed"
            )
        )

    def test_turbo_alias_same_family_passes(self):
        self.assertTrue(
            _mtplx_model_family_match(
                "mtplx-flash-next-optimized-speed", "mtplx-flash-next-turbo"
            )
        )

    def test_quality_alias_same_family_passes(self):
        self.assertTrue(
            _mtplx_model_family_match(
                "mtplx-flash-next-optimized-quality", "mtplx-flash-next-optimized-speed"
            )
        )

    def test_different_family_rejected(self):
        self.assertFalse(
            _mtplx_model_family_match(
                "mtplx-flash-next-optimized-speed", "mtplx-qwen38-speed"
            )
        )

    def test_cross_provider_rejected(self):
        self.assertFalse(
            _mtplx_model_family_match(
                "mtplx-flash-next-optimized-speed", "deepseek-v4.1-flash"
            )
        )

    def test_other_providers_strict(self):
        self.assertFalse(
            _mtplx_model_family_match("deepseek-v4.1-flash", "deepseek-v4-pro")
        )
        self.assertTrue(
            _mtplx_model_family_match("deepseek-v4.1-flash", "deepseek-v4.1-flash")
        )

    def test_empty_observed_rejected(self):
        self.assertFalse(
            _mtplx_model_family_match("mtplx-flash-next-optimized-speed", "")
        )


if __name__ == "__main__":
    unittest.main()
