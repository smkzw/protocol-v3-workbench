"""第10轮末修订（P1-50 防御层）：『<field> must be unique』422 人话化。

现场（r10-A）：服务端唯一性校验拒绝时 detail 原文
『inclusion_modules must be unique』经 _mw_journey_error_detail 原样
透传——英文内部字段名直出（NEW-P1-07 族新形态）。契约：唯一性类
校验拒绝映射为中文标签+可操作指引（前端去重为主修，此为绕过前端
调用时的防御层）。
"""

from __future__ import annotations

import unittest


class UniqueDetailHumanizeTests(unittest.TestCase):
    def _detail(self, text: str) -> str:
        from services.api.app.main import _mw_journey_error_detail

        return _mw_journey_error_detail(ValueError(text))

    def test_inclusion_modules_unique_maps_to_chinese_guidance(self) -> None:
        detail = self._detail("inclusion_modules must be unique")
        self.assertIn("入选标准", detail)
        self.assertIn("重复", detail)
        self.assertIn("删除重复行", detail)
        self.assertNotIn("inclusion_modules", detail)

    def test_safety_endpoints_unique_maps_to_chinese_label(self) -> None:
        detail = self._detail("safety_endpoints must be unique")
        self.assertIn("安全性终点", detail)
        self.assertIn("重复", detail)

    def test_unknown_field_falls_back_to_generic_unique_copy(self) -> None:
        detail = self._detail("widgets must be unique")
        self.assertIn("重复", detail)
        self.assertNotIn("must be unique", detail)

    def test_unrelated_errors_unchanged(self) -> None:
        text = "样本量声明与假设不一致：复算需63例/组。"
        self.assertEqual(text, self._detail(text))


class RequestValidationHandlerTests(unittest.TestCase):
    """live-red（第10轮末修订）：模型校验 ValueError 在 FastAPI 请求解析层
    被包成 detail 数组直出（dup draft 实测 detail[0].msg='Value error,
    inclusion_modules must be unique'），根本到不了端点内的人话映射——
    需要全局 RequestValidationError 处理器。"""

    def _response(self, msgs):
        import asyncio

        from fastapi.exceptions import RequestValidationError

        from services.api.app.main import humanize_request_validation_error

        errors = [
            {
                "type": "value_error",
                "loc": ["body", "picos"],
                "msg": msg,
                "input": {},
            }
            for msg in msgs
        ]
        exc = RequestValidationError(errors, body=None)
        return asyncio.run(
            humanize_request_validation_error(None, exc)
        )

    def test_unique_value_error_humanized_with_field_label(self) -> None:
        response = self._response(["Value error, inclusion_modules must be unique"])
        self.assertEqual(response.status_code, 422)
        import json as _json

        content = _json.loads(response.body.decode("utf-8"))
        detail = content["detail"]
        self.assertIsInstance(detail, str)
        self.assertIn("入选标准", detail)
        self.assertIn("重复", detail)
        self.assertNotIn("inclusion_modules", detail)

    def test_other_validation_errors_get_controlled_chinese_copy(self) -> None:
        response = self._response(
            ["Value error, 样本量声明与假设不一致：复算需63例/组。", "Field required"]
        )
        import json as _json

        content = _json.loads(response.body.decode("utf-8"))
        detail = content["detail"]
        self.assertIsInstance(detail, str)
        self.assertTrue(any("\u4e00" <= ch <= "\u9fff" for ch in detail))


if __name__ == "__main__":
    unittest.main()
