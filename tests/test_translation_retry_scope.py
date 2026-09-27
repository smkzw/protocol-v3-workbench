"""G5 范围限定恢复命令（0927V1 §3 恢复命令语义：范围是命令的组成部分）。

A511 nct_ids 归一化（去空白/剔除空项）
A512 非法条目（过短）拒绝
A513 空范围 = 全量（过滤助手原样返回）
A514 范围过滤只保留目标研究的失败项
A515 范围入 request_hash：同键不同范围产生不同命令身份
"""

from types import SimpleNamespace
import unittest

from packages.contracts.workbench_contracts.models import (
    WritingReferenceTranslationBatchRetryRequest,
)
from services.api.app.writing_reference_translation_batch import (
    _filter_items_by_nct_scope,
)


def _item(nct_id, item_id=None):
    return SimpleNamespace(
        nct_id=nct_id,
        item_id=item_id or ("wref_translation_item_" + nct_id.lower()),
    )


class RetryScopeContractTests(unittest.TestCase):
    def test_a511_nct_ids_normalized(self):
        req = WritingReferenceTranslationBatchRetryRequest(
            idempotency_key="scope-test-key-01",
            nct_ids=[" NCT02176291 ", "", "NCT041"],
        )
        self.assertEqual(req.nct_ids, ["NCT02176291", "NCT041"])

    def test_a512_invalid_entry_rejected(self):
        with self.assertRaises(Exception):
            WritingReferenceTranslationBatchRetryRequest(
                idempotency_key="scope-test-key-02",
                nct_ids=["N1"],
            )


class RetryScopeFilterTests(unittest.TestCase):
    def test_a513_empty_scope_returns_all(self):
        items = [_item("NCT1"), _item("NCT2")]
        self.assertEqual(len(_filter_items_by_nct_scope(items, [])), 2)

    def test_a514_scope_keeps_only_matching(self):
        items = [_item("NCT02176291"), _item("NCT999"), _item("NCT041")]
        kept = _filter_items_by_nct_scope(items, ["NCT02176291"])
        self.assertEqual([i.nct_id for i in kept], ["NCT02176291"])


class RetryScopeHashTests(unittest.TestCase):
    def test_a515_scope_changes_command_identity(self):
        from services.api.app.writing_reference_translation_batch import _payload_hash

        base = {"batch_id": "b", "idempotency_key": "k"}
        scoped = dict(base, nct_ids=["NCT02176291"])
        self.assertNotEqual(_payload_hash(base), _payload_hash(scoped))
        self.assertEqual(
            _payload_hash(scoped),
            _payload_hash({"batch_id": "b", "idempotency_key": "k", "nct_ids": ["NCT02176291"]}),
        )


if __name__ == "__main__":
    unittest.main()
