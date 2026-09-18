"""HTTP readiness projection with supplied roles, no provider or gate calls."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from services.api.app import main


@pytest.mark.parametrize("unavailable", [None, "ocr", "body", "support"])
@pytest.mark.parametrize("gate_failed", [False, True])
@pytest.mark.parametrize("provider", ["omlx", "remote"])
def test_translation_endpoint_reports_supplied_role_readiness(unavailable, gate_failed, provider):
    role_ids = {
        "ocr": main.OCR_ROLE,
        "body": main.TRANSLATION_BODY_ROLE,
        "support": main.TRANSLATION_SUPPORT_ROLE,
    }
    profiles = [
        SimpleNamespace(profile_id=name, provider=provider, enabled=True)
        for name in role_ids
    ]
    store = SimpleNamespace(
        provider_store=SimpleNamespace(profiles=lambda: profiles),
        public_payload=lambda: {
            "roles": [
                {
                    "role_id": role_id, "profile_id": name,
                    "model": "synthetic-model", "enabled": True,
                    "ready": name != unavailable,
                    "requires_local_inventory": False,
                }
                for name, role_id in role_ids.items()
            ]
        },
    )
    gate = SimpleNamespace(status=Mock(
        return_value={"limits": {"ocr": 8, "translation": 8, "total": 16}},
        side_effect=OSError("synthetic unavailable") if gate_failed else None,
    ))
    with (
        patch.object(main, "runtime_ai_role_settings_store", return_value=store),
        patch.object(main, "default_omlx_workload_gate_client", return_value=gate),
        patch.object(main, "_translation_ai_env", return_value={}),
        patch.object(main, "ai_gateway_status_from_env", return_value={}),
    ):
        response = TestClient(main.app).get(
            "/api/medical-writing/reference-translation/ai-status"
        )
    assert response.status_code == 200
    payload = response.json()
    shared_service_ready = not (gate_failed and provider == "omlx")
    assert payload["body_translation_runnable"] is (unavailable != "body" and shared_service_ready)
    assert payload["support_runnable"] is (unavailable != "support" and shared_service_ready)
    assert payload["ocr"]["current_runnable"] is (unavailable != "ocr" and shared_service_ready)
    assert payload["currently_runnable"] is (unavailable is None and shared_service_ready)
    if gate_failed and provider == "omlx":
        assert payload["ocr"]["execution_blocked_reason"] == (
            "本地 OCR/翻译服务状态暂不可用，请稍后重新检查。"
        )
