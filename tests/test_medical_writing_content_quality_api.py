from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from services.api.app import main as app_main
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_manifest import RUX_PROTOCOL_DOCX
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


@pytest.mark.skipif(not RUX_PROTOCOL_DOCX.exists(), reason="RUX protocol is unavailable")
class TestMedicalWritingContentQualityApi:
    def setup_method(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.repository = MedicalWritingRuntimeRepository(
            MedicalWritingDocumentService(),
            SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3"),
        )
        self.repository_patch = patch(
            "services.api.app.main.medical_writing_runtime_repository",
            self.repository,
        )
        self.repository_patch.start()
        self.client = TestClient(app_main.app)

    def teardown_method(self):
        self.repository_patch.stop()
        self.tmpdir.cleanup()

    def test_get_returns_exact_source_text_before_secondary_locator(self):
        response = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/content-quality"
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["finding_count"] == 1
        assert payload["approval_blocking_count"] == 1
        finding = payload["findings"][0]
        assert finding["source_text"] == "对于研究中具有生育能力的女性受试者：<0}"
        assert finding["matched_text"] == "<0}"
        assert finding["source_locator"] == "docx:table:10:row:2:cell:0"
        assert "/Users/" not in response.text

    def test_disposition_requires_current_fingerprint_and_persists_audited_confirmation(self):
        finding = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/content-quality"
        ).json()["findings"][0]
        response = self.client.post(
            f"/api/projects/proj_rux_03_002/medical-writing/content-quality/findings/{finding['finding_id']}/disposition",
            params={"section_id": finding["section_id"]},
            json={
                "status": "confirmed_source_text",
                "reason": "医学经理已复核原始方案上下文，确认按当前源文本沿用并保留警示。",
                "actor": "medical_manager_api_test",
                "expected_content_fingerprint": finding["content_fingerprint"],
                "expected_content_revision": finding["content_revision"],
                "expected_disposition_revision": finding["disposition_revision"],
                "idempotency_key": "content-quality-api-confirm-001",
            },
        )

        assert response.status_code == 200, response.text
        updated = response.json()
        assert updated["disposition_status"] == "confirmed_source_text"
        assert updated["disposition_revision"] == 1
        assert updated["source_text"] == finding["source_text"]
        assert self.repository.runtime_store.verify_audit_chain("proj_rux_03_002") == []

        stale = self.client.post(
            f"/api/projects/proj_rux_03_002/medical-writing/content-quality/findings/{finding['finding_id']}/disposition",
            params={"section_id": finding["section_id"]},
            json={
                "status": "correction_required",
                "reason": "医学经理要求修订该处源文本后再进入批准流程。",
                "actor": "medical_manager_api_test",
                "expected_content_fingerprint": "0" * 64,
                "expected_content_revision": finding["content_revision"],
                "expected_disposition_revision": 1,
                "idempotency_key": "content-quality-api-stale-001",
            },
        )
        assert stale.status_code == 409

    def test_short_reason_is_rejected_without_changing_state(self):
        finding = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/content-quality"
        ).json()["findings"][0]
        response = self.client.post(
            f"/api/projects/proj_rux_03_002/medical-writing/content-quality/findings/{finding['finding_id']}/disposition",
            params={"section_id": finding["section_id"]},
            json={
                "status": "confirmed_source_text",
                "reason": "确认",
                "actor": "medical_manager_api_test",
                "expected_content_fingerprint": finding["content_fingerprint"],
                "expected_content_revision": finding["content_revision"],
                "expected_disposition_revision": 0,
                "idempotency_key": "content-quality-api-short-001",
            },
        )

        assert response.status_code == 422
        current = self.client.get(
            "/api/projects/proj_rux_03_002/medical-writing/content-quality"
        ).json()["findings"][0]
        assert current["disposition_status"] == "open"
