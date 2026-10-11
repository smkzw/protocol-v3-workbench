"""新纪元第4轮末修订（P0-1/NEW-30）：入口B救回——失败可见化+stale清扫
接线+合同错字段细节。

钉死（P0-1①，本会话日志实测）：live 日志尾部，r4 导入尝试的 job 状态
GET 返回 404 Not Found（file-first-synopsis-a2fea930…）——作业记录缺失
而非 failed 落库，前端轮询 404 无处理 → '摘要解析中'永久无出路。

修后契约（反例先红）：
T1 extraction_pending 超时（>10 分钟）→ recover_stale_jobs 判 failed
   （failure_code=extraction_timeout、人话 error_message）；新鲜作业不动；
T2 状态路由挂接 recover_stale_jobs（main.py 源级契约）+ 404 结构化载荷
   （code=synopsis_job_missing、retryable=true、人话指引重新导入）；
T3 合同校验失败（:782 RuntimeError）消息携带字段级摘要（字段路径+原因），
   不再是一句无细节英文。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.workbench_contracts import MedicalWritingStudyFraming


def _service(tmp: str):
    from services.api.app.medical_writing_synopsis_import import (
        MedicalWritingSynopsisImportService,
    )

    return MedicalWritingSynopsisImportService(
        Path(tmp) / "artifacts",
        SimpleNamespace(),
        Path(tmp) / "synopsis.sqlite3",
    )


def _insert_stuck_job(service, project_id: str, key: str, age_minutes: int):
    now = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    with service._connect() as connection:
        connection.execute(
            """
            INSERT INTO medical_writing_synopsis_imports(
                project_id, idempotency_key, job_id, status, phase,
                error_message, failure_code, created_at, updated_at,
                request_sha256, attempt_count
            ) VALUES (?, ?, ?, 'extraction_pending', 'extraction_pending',
                      '', '', ?, ?, 'stub-sha', 1)
            """,
            (
                project_id,
                key,
                f"file-first-synopsis-{key}",
                now.isoformat(),
                now.isoformat(),
            ),
        )


class StaleExtractionTimeoutTests(unittest.TestCase):
    def test_stuck_extraction_pending_times_out_to_failed(self) -> None:
        """T1：卡死 11 分钟 → failed+extraction_timeout；新鲜作业不动。"""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        service = _service(tmp.name)
        _insert_stuck_job(service, "proj_stuck_a", "key-stuck-11min", age_minutes=11)
        _insert_stuck_job(service, "proj_fresh_a", "key-fresh-1min", age_minutes=1)

        recovered = service.recover_stale_jobs()
        self.assertGreaterEqual(recovered, 1)
        stuck = service.get_job("proj_stuck_a", "key-stuck-11min")
        self.assertEqual("failed", stuck.status)
        self.assertEqual("extraction_timeout", stuck.failure_code)
        self.assertIn("重新导入", stuck.error_message)
        fresh = service.get_job("proj_fresh_a", "key-fresh-1min")
        self.assertNotEqual("failed", fresh.status)

    def test_status_route_wires_recovery_and_structured_404(self) -> None:
        """T2：状态路由挂接清扫 + 作业缺失 404 为结构化可重试载荷。"""
        main_source = (
            Path(__file__).resolve().parents[1]
            / "services/api/app/main.py"
        ).read_text(encoding="utf-8")
        route_segment = main_source[
            main_source.index("def get_file_first_synopsis_project_intake("):
        ]
        self.assertIn("recover_stale_jobs()", route_segment[:2000])
        self.assertIn("synopsis_job_missing", route_segment[:2000])
        self.assertIn("retryable", route_segment[:2000])

        # 行为级：未知作业 → HTTPException 404 + 结构化 detail
        from fastapi import HTTPException

        from services.api.app.main import (
            get_file_first_synopsis_project_intake,
        )

        with self.assertRaises(HTTPException) as refused:
            get_file_first_synopsis_project_intake(
                "proj_unknown_p0", "key-never-created"
            )
        self.assertEqual(404, refused.exception.status_code)
        detail = refused.exception.detail
        self.assertIsInstance(detail, dict)
        self.assertEqual("synopsis_job_missing", detail["code"])
        self.assertTrue(detail["retryable"])
        self.assertIn("重新导入", detail["message"])


class ContractErrorFieldDetailTests(unittest.TestCase):
    def test_contract_mismatch_error_carries_field_summary(self) -> None:
        """T3：合同校验失败的 RuntimeError 带字段路径与原因（中文化）。"""
        from services.api.app.medical_writing_synopsis_import import (
            validate_synopsis_contract_payload,
        )

        definition = {
            "framing": {"indication": "化脓性汗腺炎", "study_phase": 123},
            "picos": {},
        }
        with self.assertRaises(RuntimeError) as refused:
            validate_synopsis_contract_payload(definition, {})
        message = str(refused.exception)
        self.assertIn("study-definition contract", message)
        self.assertIn("字段", message)
        self.assertTrue(
            any(name in message for name in ("study_phase", "project_name", "indication", "framing")),
            message,
        )


if __name__ == "__main__":
    unittest.main()
