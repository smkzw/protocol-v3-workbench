"""R27 第2轮末修订 批A④：同文件重传命中结构化结果缓存（零AI直出）。

现场背景（NEW-P0-08/L5）：入口B失败梯一次烧14-73分钟；同一文件重试/
重传时又从零跑AI。确定性解析已有同款键
（extraction_revision=docx_xml_v1_m11map_v5_{sha}），AI结构化缺缓存。

修复契约（红先修后）：import_and_structure 在启动AI前查
medical_writing_synopsis_imports 是否存在同
(source_sha256, media_type, expected_indication) 且 status=completed、
result_json 非空的既往导入——命中即新建一条 completed 导入直接复用
result_json（payload 带 reused_structured_result=true 留审计），AI runner
零调用；未命中走原路径。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from services.api.app.medical_writing_synopsis_import import (
    MedicalWritingSynopsisImportService,
)


class _RaisingRunner:
    """任何AI调用即失败——证明缓存命中路径零AI。"""

    called = False

    def run_task(self, *args, **kwargs):
        _RaisingRunner.called = True
        raise AssertionError("cached reupload must not invoke the AI runner")


PAYLOAD = b"%PDF-1.4\n%fake-pdf-for-cache-test\n" + b"x" * 256 + b"\n%%EOF\n"


def _seed_completed_import(db_path: Path, source_sha256: str, result: dict) -> None:
    import sqlite3

    result_json = json.dumps(result, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO medical_writing_synopsis_imports (
            project_id, idempotency_key, request_sha256, status, payload_json,
            claim_token, lease_expires_at, attempt_count, error_message,
            created_at, updated_at, phase, chunk_index, chunk_total,
            progress_json, source_sha256, source_filename, cancelled_at,
            result_json, job_id, media_type, expected_indication, actor,
            source_json, route_snapshot_json, route_identity_hash, failure_code
        ) VALUES (?, ?, ?, 'completed', ?, '', '', 1, '', ?, ?, 'completed', 0, 1,
                  '{}', ?, 'seed.pdf', '', ?, '', ?, ?, 'seed_actor',
                  '{}', '{}', '', '')
        """,
        (
            "proj_seed_cache",
            "seed-key-1",
            "seed-request-sha",
            json.dumps({"status": "completed"}, ensure_ascii=False),
            now,
            now,
            source_sha256,
            result_json,
            "application/pdf",
            "慢性咳嗽",
        ),
    )
    conn.commit()
    conn.close()


class ReuploadStructuredCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runner = _RaisingRunner()
        self.importer = MedicalWritingSynopsisImportService(
            self.root / "artifacts", self.runner
        )
        import hashlib

        self.source_sha = hashlib.sha256(PAYLOAD).hexdigest()
        # 服务构造时已建库（db_path = artifacts 父目录下的同名sqlite）。
        _seed_completed_import(
            self.importer.db_path,
            self.source_sha,
            {
                "status": "review_pending",
                "source": {
                    "source_id": "mwsynopsis_seed",
                    "original_filename": "seed.pdf",
                    "media_type": "application/pdf",
                    "actual_size": len(PAYLOAD),
                    "content_sha256": __import__("hashlib").sha256(PAYLOAD).hexdigest(),
                    "source_role_status": "matched",
                    "indication_status": "matched",
                    "validation_warnings": [],
                    "imported_at": "2026-10-05T00:00:00Z",
                    "imported_by": "seed_actor",
                    "parser_name": "seed_parser",
                    "extraction_revision": "seed_r1",
                },
                "missing_fields": [],
                "conflict_notes": [],
            },
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_same_file_reupload_reuses_structured_result_without_ai(self):
        result = self.importer.import_and_structure(
            "proj_cache_reuse",
            filename="same.pdf",
            content_type="application/pdf",
            payload=PAYLOAD,
            expected_indication="慢性咳嗽",
            actor="medical_manager",
            idempotency_key="reupload-key-1",
        )
        self.assertEqual(
            "review_pending",
            result.status,
            "同文件重传必须直接命中既往结构化结果（已结构化待确认，零AI）。",
        )
        self.assertFalse(_RaisingRunner.called, "缓存命中不得触发任何AI调用。")


if __name__ == "__main__":
    unittest.main()
