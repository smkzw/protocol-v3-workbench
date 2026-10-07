"""R27 第3轮末修订 片1②（NEW-P0-15 后端）：cancelled导入重放=重新提交。

现场（R3-D）：入口B单点『导入并提取』后秒级红条『本次解析已取消』——
前端误触取消置cancelled_at；此后同一文件重选重传四次POST全202但解析
永不启动（fileRequestKey=内容sha256=同一幂等键→服务端重放cancelled态）
→同一文件被永久毒化，180秒空等核对页不出现。

修复契约（红先修后）：
- 同幂等键重放命中 status='cancelled' 行且 request_sha256 相同=视为用户
  重新提交：清 cancelled_at、status 回 pending、attempt+1、正常重启解析；
- completed 保持幂等回放（不重启）；
- failed 语义不变。
"""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile

from services.api.app.medical_writing_synopsis_import import (
    MedicalWritingSynopsisImportService,
)

import tests.test_medical_writing_synopsis_import as base

def _real_pdf_bytes() -> bytes:
    import io

    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 96), "Cancelled replay test protocol synopsis")
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


PDF_BYTES = _real_pdf_bytes()



ROUTE_SNAPSHOT = {
    "schema_version": "route_snapshot_v1",
    "role_id": "protocol_synopsis_structuring",
    "profile_id": "test_profile",
    "profile_revision": 1,
    "provider": "test_provider",
    "model": "test_model",
    "base_url": "https://example.invalid/v1",
    "transport": "openai_compatible",
    "expected_response_model": "test_model",
    "deployment_profile": "test",
}


def _route_identity() -> tuple[str, str]:
    import hashlib
    import json as _json

    snapshot = dict(ROUTE_SNAPSHOT)
    identity = hashlib.sha256(
        _json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    normalized = {**snapshot, "identity_sha256": identity}
    return _json.dumps(normalized, ensure_ascii=False), identity


def request_sha_of(payload: bytes) -> str:
    import hashlib
    import json as _json

    content_sha = hashlib.sha256(payload).hexdigest()
    return hashlib.sha256(
        _json.dumps(
            {
                "filename": "same.pdf",
                "media_type": "application/pdf",
                "content_sha256": content_sha,
                "expected_indication": "慢性咳嗽",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

class _CancelledReplayRunner:
    """Records invocations; carries a route identity snapshot."""

    def __init__(self, payload_result=None):
        self.calls = 0
        self.payload_result = payload_result

    def route_identity_snapshot(self, refresh=False):
        return dict(ROUTE_SNAPSHOT)

    def fallback_chain_identities(self):
        return []

    def run_task(self, *args, **kwargs):
        self.calls += 1
        return self.payload_result


class CancelledReplayResubmitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _service(self, runner):
        return MedicalWritingSynopsisImportService(
            self.root / f"artifacts_{id(runner)}", runner
        )

    def _cancel_row(self, service, key: str) -> None:
        with service._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM medical_writing_synopsis_imports "
                "WHERE project_id=? AND idempotency_key=?",
                ("proj_cancel_replay", key),
            ).fetchone()
            assert row is not None, "seed row missing"
            from datetime import datetime, timezone

            connection.execute(
                """
                UPDATE medical_writing_synopsis_imports
                SET status='cancelled', cancelled_at=?
                WHERE project_id=? AND idempotency_key=?
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    "proj_cancel_replay",
                    key,
                ),
            )
            connection.commit()

    def test_same_key_replay_of_cancelled_import_restarts_parsing(self):
        runner = _CancelledReplayRunner(None)
        service = self._service(runner)
        # 第一次提交：走claim→_run_import。用一个立即取消的正常导入来做种子：
        # 直接建行再置cancelled更可控。
        key = "cancel-replay-key-0001"
        self._seed_row(service, key, PDF_BYTES)
        self._cancel_row(service, key)

        runner2 = _CancelledReplayRunner(None)
        service2 = self._service(runner2)
        # 直接驱动决策层（现场链路同一入口）：同键同内容重放cancelled行
        # 必须返回 claimed（重启解析），而不是 unknown-state 崩溃/静默回放。
        decision = service2._claim_once(
            project_id="proj_cancel_replay",
            idempotency_key=key,
            request_sha256=request_sha_of(PDF_BYTES),
            claim_token="replay-token",
            observed_attempt=None,
        )
        self.assertEqual(
            "claimed",
            decision["action"],
            "cancelled导入同键重放必须重启解析（现场：同文件被永久毒化）",
        )
        with service2._connect() as connection:
            row = connection.execute(
                "SELECT status, cancelled_at FROM medical_writing_synopsis_imports "
                "WHERE project_id=? AND idempotency_key=?",
                ("proj_cancel_replay", key),
            ).fetchone()
        self.assertEqual("pending", row["status"])
        self.assertEqual("", row["cancelled_at"])

    def _seed_row(self, service, key: str, payload: bytes) -> None:
        import hashlib
        from datetime import datetime, timezone

        content_sha = hashlib.sha256(payload).hexdigest()
        request_sha = request_sha_of(payload)
        now = datetime.now(timezone.utc).isoformat()
        with service._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO medical_writing_synopsis_imports (
                    project_id, idempotency_key, request_sha256, status,
                    payload_json, claim_token, lease_expires_at, attempt_count,
                    error_message, created_at, updated_at, phase, chunk_index,
                    chunk_total, progress_json, source_sha256, source_filename,
                    cancelled_at, result_json, job_id, media_type,
                    expected_indication, actor, source_json,
                    route_snapshot_json, route_identity_hash, failure_code
                ) VALUES (?, ?, ?, 'pending', '{}', '', '', 1, '', ?, ?, 'pending',
                          0, 1, '{}', ?, 'same.pdf', '', '', '', 'application/pdf',
                          '慢性咳嗽', 'medical_manager', '{}', ?, ?, '')
                """,
                (
                    "proj_cancel_replay",
                    key,
                    request_sha,
                    now,
                    now,
                    content_sha,
                    *_route_identity(),
                ),
            )
            connection.commit()


if __name__ == "__main__":
    unittest.main()
