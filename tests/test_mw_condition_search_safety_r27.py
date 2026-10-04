"""R27 第1轮末修订 NEW-P0-01：竞品检索条件未规范化 → CT.gov 400 → 500。

现场（R1-A，proj_user_d828e848b004，backend 日志11次500）：AI 富化产物
『难治性/不明原因慢性咳嗽（Refractory Chronic cough / Unexplained
Cough，RCC/UCC）』被 resolve_clinicaltrials_condition_term 无别名可映射
fail-open 原样放行 → search_url() 把全角括号/斜杠/保留字直接放进
query.cond → ClinicalTrials.gov 表达式解析 400 → _open_with_retry 只重试
429/5xx，400 直接上抛 HTTPError → 端点无映射 → 500。

修复契约（红先修后）：
- ① resolver：混合串含 ASCII 英文段（含全角/半角括注）时抽取英文段作
  条件词（en_extract）；别名表补 慢性咳嗽/难治性慢性咳嗽；
- ② search_url：query.cond 防御性安全化——剔除括号/斜杠/AND/OR 保留字，
  只保留英文短语词元；安全化后仍无有效词元则 422 人话（不再放行复杂串）；
- ③ fetch_json：HTTP 400 → ValueError 中文领域错误（端点已有 ValueError→422
  映射），不再裸抛 HTTPError→500；
- ④ 真实 CT.gov 对照：毒化 cond 400（红基线外部实证），安全化 cond 200。
"""

from __future__ import annotations

import unittest
import urllib.error
import urllib.parse
import urllib.request

from packages.contracts.workbench_contracts import (
    WritingReferenceSearchRequest,
)
from services.api.app.medical_writing_condition_term_resolver import (
    resolve_clinicaltrials_condition_term,
)
from services.api.app.writing_reference import (
    ClinicalTrialsGovClient,
    search_url,
)

POISON_TERM = "难治性/不明原因慢性咳嗽（Refractory Chronic cough / Unexplained Chronic Cough，RCC/UCC）"


class ResolverEnglishExtractionTests(unittest.TestCase):
    def test_poisoned_mixed_term_extracts_english_segment(self):
        resolved, source = resolve_clinicaltrials_condition_term(
            clinicaltrials_condition_term=POISON_TERM,
            indication="",
        )
        self.assertEqual("Refractory Chronic cough", resolved, (
            "混合串含 ASCII 英文段时必须抽取英文段作条件词，而不是把"
            "全角括号串原样放行给 query.cond（现场500根因）。"
        ))
        self.assertTrue(source and "en_extract" in source)

    def test_chronic_cough_aliases_added(self):
        resolved, _ = resolve_clinicaltrials_condition_term(
            clinicaltrials_condition_term="难治性慢性咳嗽", indication=""
        )
        self.assertEqual("refractory chronic cough", resolved)
        resolved2, _ = resolve_clinicaltrials_condition_term(
            clinicaltrials_condition_term="慢性咳嗽", indication=""
        )
        self.assertEqual("chronic cough", resolved2)

    def test_clean_english_and_known_chinese_aliases_unchanged(self):
        resolved, source = resolve_clinicaltrials_condition_term(
            clinicaltrials_condition_term="benign prostatic hyperplasia",
            indication="",
        )
        self.assertEqual("benign prostatic hyperplasia", resolved)
        self.assertIsNone(source)
        resolved2, source2 = resolve_clinicaltrials_condition_term(
            indication="特应性皮炎", clinicaltrials_condition_term=""
        )
        self.assertEqual("atopic dermatitis", resolved2)
        self.assertTrue(source2 and "zh_alias" in source2)


class SearchUrlSanitizationTests(unittest.TestCase):
    def _request(self, indication: str) -> WritingReferenceSearchRequest:
        return WritingReferenceSearchRequest(
            indication=indication,
            phases=["PHASE2"],
            study_type="INTERVENTIONAL",
        )

    def test_query_cond_never_contains_parens_slashes_cjk_or_reserved(self):
        url = search_url(self._request(POISON_TERM))
        cond = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)[
            "query.cond"
        ][0]
        self.assertNotIn("(", cond)
        self.assertNotIn("（", cond)
        self.assertNotIn("/", cond)
        self.assertNotIn(" AND ", cond.upper())
        self.assertNotIn(" OR ", cond.upper())
        self.assertFalse(any("\u4e00" <= ch <= "\u9fff" for ch in cond), (
            f"query.cond 不得含中文（CT.gov 表达式解析会 400）：{cond}"
        ))

    def test_unsanitizable_condition_fails_with_human_422_not_passthrough(self):
        with self.assertRaises(ValueError) as raised:
            search_url(self._request("【待确认】///"))
        message = str(raised.exception)
        self.assertIn("检索条件", message)

    def test_clean_condition_untouched(self):
        url = search_url(self._request("atopic dermatitis"))
        cond = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)[
            "query.cond"
        ][0]
        self.assertEqual("atopic dermatitis", cond)


class FetchJson400DomainErrorTests(unittest.TestCase):
    def test_http_400_maps_to_value_error_with_human_message(self):
        class _400Opener:
            def open(self, request, timeout=None):
                raise urllib.error.HTTPError(
                    request.full_url,
                    400,
                    "Bad Request",
                    hdrs=None,
                    fp=None,
                )

        client = ClinicalTrialsGovClient()
        client.__dict__["_opener_for_test"] = None
        # 直接替换 opener 构造路径：fetch_json 内部 build_opener —— 用最小
        # 打桩：monkeypatch build_opener 于本模块。
        import services.api.app.writing_reference as wr

        original = wr.urllib.request.build_opener
        wr.urllib.request.build_opener = lambda *a, **k: _400Opener()
        try:
            with self.assertRaises(ValueError) as raised:
                client.fetch_json(
                    "https://clinicaltrials.gov/api/v2/studies?query.cond=x"
                )
        finally:
            wr.urllib.request.build_opener = original
        message = str(raised.exception)
        self.assertIn("检索条件", message)
        self.assertIn("400", message)


class RealCtGovCrossCheckTests(unittest.TestCase):
    """对照实证：毒化 cond 400 / 安全化 cond 200（真实 CT.gov，只读）。"""

    @classmethod
    def setUpClass(cls) -> None:
        import re

        def sanitize(value: str) -> str:
            from services.api.app.medical_writing_condition_term_resolver import (
                extract_english_condition_phrase,
            )

            return extract_english_condition_phrase(value)

        cls.sanitized = sanitize(POISON_TERM)
        cls.poison_encoded = urllib.parse.quote(POISON_TERM)

    def test_sanitized_term_is_clean_english(self):
        self.assertEqual("Refractory Chronic cough", self.sanitized)

    def test_real_ctgov_poison_400_and_sanitized_200(self):
        base = "https://clinicaltrials.gov/api/v2/studies"
        poison_url = (
            f"{base}?query.cond={self.poison_encoded}"
            "&pageSize=1&format=json&countTotal=true"
        )
        req = urllib.request.Request(
            poison_url, headers={"User-Agent": "workbench-contract-check"}
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(req, timeout=30)
        self.assertEqual(400, raised.exception.code)

        sanitized_url = (
            f"{base}?query.cond={urllib.parse.quote(self.sanitized)}"
            "&pageSize=1&format=json&countTotal=true"
        )
        with urllib.request.urlopen(
            urllib.request.Request(
                sanitized_url, headers={"User-Agent": "workbench-contract-check"}
            ),
            timeout=30,
        ) as response:
            self.assertEqual(200, response.status)


if __name__ == "__main__":
    unittest.main()
