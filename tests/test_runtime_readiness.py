import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.runtime_readiness import (
    API_CONTRACT_VERSION,
    BACKEND_BUILD_ID,
    CLIENT_CONTRACT_HEADER,
    RUNTIME_CONTRACT,
    RuntimeContractError,
    evaluate_required_capabilities,
    load_runtime_contract,
    runtime_readiness_report,
)


DIRECT_AI_ENV = {
    "WORKBENCH_AI_PROVIDER": "deepseek",
    "WORKBENCH_AI_TRANSPORT": "openai_compatible",
    "WORKBENCH_AI_BASE_URL": "https://api.deepseek.com/v1",
    "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
    "DEEPSEEK_API_KEY": "test-only-placeholder",
    "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
}


class _Route:
    def __init__(self, path, methods):
        self.path = path
        self.methods = methods


class RuntimeReadinessTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_runtime_contract_rejects_duplicate_capability_ids(self):
        payload = dict(RUNTIME_CONTRACT)
        payload["required_capabilities"] = [
            {"id": "duplicate", "method": "GET", "path": "/api/a"},
            {"id": "duplicate", "method": "POST", "path": "/api/b"},
        ]
        path = Path(self.id().replace(".", "_") + ".json")
        try:
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeContractError, "unique"):
                load_runtime_contract(path)
        finally:
            path.unlink(missing_ok=True)

    def test_missing_registered_route_is_reported_by_capability(self):
        routes = [
            _Route(item["path"], {item["method"]})
            for item in RUNTIME_CONTRACT["required_capabilities"]
            if item["id"] != "document_export"
        ]
        result = evaluate_required_capabilities(routes)
        missing = [item["id"] for item in result if not item["available"]]
        self.assertEqual(["document_export"], missing)

    def test_readiness_reports_current_contract_routes_schema_and_ai_without_paths(self):
        with patch.dict(os.environ, DIRECT_AI_ENV, clear=True):
            response = self.client.get("/api/runtime-readiness")
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertTrue(payload["ready"])
        self.assertEqual(API_CONTRACT_VERSION, payload["api_contract_version"])
        self.assertEqual(BACKEND_BUILD_ID, payload["backend_build_id"])
        self.assertEqual(16, payload["runtime_schema_version"])
        self.assertEqual([], payload["missing_capabilities"])
        self.assertTrue(payload["runtime_store_ready"])
        self.assertFalse(payload["independent_ai"]["codex_runtime_dependency"])
        self.assertNotIn("/Users/", response.text)
        self.assertNotIn("api_key", response.text.lower())

    def test_readiness_fails_closed_when_independent_ai_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_settings = str(Path(temp_dir) / "ai_provider_settings.json")
            with patch.dict(
                os.environ,
                {"WORKBENCH_AI_SETTINGS_PATH": empty_settings},
                clear=True,
            ):
                response = self.client.get("/api/runtime-readiness")
        self.assertEqual(503, response.status_code, response.text)
        payload = response.json()
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["independent_ai"]["ready"])
        self.assertIn("independent_ai", payload["missing_capabilities"])

    def test_readiness_requires_literal_boolean_ai_status_fields(self):
        routes = [
            _Route(item["path"], {item["method"]})
            for item in RUNTIME_CONTRACT["required_capabilities"]
        ]
        report = runtime_readiness_report(
            routes,
            runtime_health={
                "status": "ok",
                "integrity_check": "ok",
                "foreign_key_violations": 0,
                "schema_version": 16,
            },
            ai_status={
                "configured": "true",
                "semantic_ai_tasks_enabled": "true",
                "codex_runtime_dependency": "false",
                "route_validation_errors": [],
            },
        )

        assert report["ready"] is False
        assert report["independent_ai"]["ready"] is False
        assert report["independent_ai"]["configured"] is False
        assert report["independent_ai"]["semantic_ai_tasks_enabled"] is False
        assert report["independent_ai"]["codex_runtime_dependency"] is False

    def test_enforced_mode_rejects_missing_contract_on_medical_writing_routes(self):
        with patch.dict(os.environ, {"WORKBENCH_CLIENT_CONTRACT_MODE": "enforce"}):
            response = self.client.get(
                "/api/projects/proj_rux_03_002/medical-writing/document-session"
            )
        self.assertEqual(409, response.status_code)
        self.assertEqual(
            "workbench_client_contract_mismatch",
            response.json()["detail"]["code"],
        )

    def test_enforced_mode_accepts_current_contract_and_leaves_health_public(self):
        with patch.dict(os.environ, {"WORKBENCH_CLIENT_CONTRACT_MODE": "enforce"}):
            health = self.client.get("/api/health")
            writing = self.client.get(
                "/api/projects/proj_rux_03_002/medical-writing/document-session",
                headers={CLIENT_CONTRACT_HEADER: API_CONTRACT_VERSION},
            )
        self.assertEqual(200, health.status_code)
        self.assertNotEqual(409, writing.status_code)

    def test_project_create_is_protected_but_project_catalog_is_readable(self):
        with patch.dict(os.environ, {"WORKBENCH_CLIENT_CONTRACT_MODE": "enforce"}):
            catalog = self.client.get("/api/projects")
            create = self.client.post("/api/projects", json={})
        self.assertEqual(200, catalog.status_code)
        self.assertEqual(409, create.status_code)
