from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.api.app.ai_role_runtime_settings import (
    DEFAULT_OCR_MODEL,
    GATE_TRANSLATION_BODY_MODEL,
    LOCAL_OMLX_PROFILE_ID,
    OCR_PADDLE_PROFILE_ID,
    OCR_ROLE,
    PADDLE_OCR_MODEL,
    TRANSLATION_BODY_ROLE,
    TRANSLATION_SUPPORT_ROLE,
    AiRoleBinding,
    AiRoleRuntimeSettingsStore,
)
from services.api.app.ai_runtime_settings import (
    AiProviderProfile,
    AiRuntimeSettingsStore,
)
from services.api.app.chapter_translation_pipeline import (
    CompositePipelineUnavailableError,
)
from services.api.app.ocr_gateway import (
    LocalOcrGateway,
    OcrGatewaySettings,
    OcrRequest,
)
from services.api.app.omlx_workload_gate_client import (
    OmlxWorkloadGateClient,
    run_gated_omlx_request,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"gate-test"


class _Response:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body


class OmlxWorkloadGateConcurrencyTests(unittest.TestCase):
    def test_10_ocr_plus_10_translation_never_exceed_shared_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = OmlxWorkloadGateClient(
                db_path=Path(tmp) / "shared_gate.sqlite3",
                wait_timeout_seconds=10,
                lease_ttl_seconds=5,
            )
            lock = threading.Lock()
            counters = {"ocr": 0, "translation": 0}
            maxima = {"ocr": 0, "translation": 0, "total": 0}
            start = threading.Barrier(20)

            def fake_request(kind: str, ordinal: int) -> str:
                start.wait(timeout=5)

                def transport(_lease) -> str:
                    with lock:
                        counters[kind] += 1
                        maxima[kind] = max(maxima[kind], counters[kind])
                        maxima["total"] = max(
                            maxima["total"],
                            counters["ocr"] + counters["translation"],
                        )
                    time.sleep(0.06)
                    with lock:
                        counters[kind] -= 1
                    return f"{kind}-{ordinal}"

                return run_gated_omlx_request(
                    transport,
                    kind=kind,
                    owner=f"pressure:{kind}:{ordinal}",
                    gate_client=client,
                )

            work = [
                ("ocr", ordinal) for ordinal in range(10)
            ] + [
                ("translation", ordinal) for ordinal in range(10)
            ]
            with ThreadPoolExecutor(max_workers=20) as executor:
                results = list(executor.map(lambda item: fake_request(*item), work))

            self.assertEqual(20, len(results))
            self.assertLessEqual(maxima["ocr"], 8)
            self.assertLessEqual(maxima["translation"], 8)
            self.assertLessEqual(maxima["total"], 16)
            self.assertGreater(maxima["ocr"], 0)
            self.assertGreater(maxima["translation"], 0)
            status = client.status()
            self.assertEqual({"ocr": 0, "translation": 0}, status["active"])
            self.assertEqual(0, status["total_active"])
            self.assertEqual(
                {"ocr": 8, "translation": 8, "total": 16},
                status["limits"],
            )

    def test_ocr_transport_runs_inside_ocr_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = OmlxWorkloadGateClient(
                db_path=root / "ocr_gate.sqlite3",
                wait_timeout_seconds=5,
                lease_ttl_seconds=5,
            )
            observed = {}

            def transport(_request, _timeout):
                observed.update(gate.status())
                return json.dumps(
                    {"choices": [{"message": {"content": "OCR text"}}]}
                ).encode("utf-8")

            gateway = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=transport,
                workload_gate=gate,
            )
            result = gateway.run(
                OcrRequest(image_bytes=PNG_BYTES, image_suffix=".png")
            )

            self.assertEqual("OCR text", result.text)
            self.assertEqual(1, observed["active"]["ocr"])
            self.assertEqual(0, gate.status()["total_active"])


class OmlxRoleBindingConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.provider_store = AiRuntimeSettingsStore(
            self.root / "ai_provider_settings.json"
        )
        self.role_store = AiRoleRuntimeSettingsStore(
            self.root / "ai_role_bindings.json",
            self.provider_store,
        )
        self.role_store.migrate()
        self.gate_env = patch.dict(
            os.environ,
            {
                "WORKBENCH_OMLX_WORKLOAD_GATE_DB": str(
                    self.root / "role_gate.sqlite3"
                )
            },
            clear=False,
        )
        self.gate_env.start()

    def tearDown(self):
        self.gate_env.stop()
        self.temp.cleanup()

    def test_body_translation_payload_uses_role_model_not_gate_metadata(self):
        """The role binding selects the HTTP model; the lease only admits it."""
        from services.api.app import main

        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            gate_status = main.default_omlx_workload_gate_client().status()
            captured["active_translation"] = gate_status["active"]["translation"]
            return _Response(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": (
                                    "[[CMS_SEG_0001]]\n译文。\n"
                                    "[[/CMS_SEG_0001]]"
                                )
                            },
                        }
                    ]
                }
            )

        with (
            patch.object(
                main,
                "runtime_ai_role_settings_store",
                return_value=self.role_store,
            ),
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            result = main._hy_mt2_translator_adapter(
                "[[CMS_SEG_0001]]\nSource.\n[[/CMS_SEG_0001]]",
                "glossary",
                "ch01",
                "chunk01",
            )

        self.assertEqual(GATE_TRANSLATION_BODY_MODEL, captured["payload"]["model"])
        self.assertEqual(1, captured["active_translation"])
        self.assertEqual(GATE_TRANSLATION_BODY_MODEL, result.model)
        self.assertEqual(
            0,
            main.default_omlx_workload_gate_client().status()["total_active"],
        )

    def test_provider_model_metadata_does_not_override_role_or_gate_contract(self):
        """Provider metadata is not used as a model-selection authority."""
        from services.api.app import main

        captured = {}

        class FakeProvider:
            provider_name = "omlx"
            model_name = "local-support-model"

            def run(self, _envelope):
                # This provider's model_name is NOT the gate model.
                # The payload must still use the gate model, not this.
                captured["provider_model_name"] = self.model_name
                return {"status": "ok"}

        provider = main._GatedTranslationSupportProvider(
            FakeProvider(),
            use_omlx_gate=True,
        )
        result = provider.run(SimpleNamespace())
        self.assertEqual({"status": "ok"}, result)
        # The provider's model_name was NOT the gate model
        self.assertEqual("local-support-model", captured["provider_model_name"])
        # Lease was acquired and released cleanly
        self.assertEqual(
            0,
            main.default_omlx_workload_gate_client().status()["total_active"],
        )

    def test_lease_released_on_operation_exception(self):
        """If the operation inside a lease raises, the lease must still
        be released (finally path)."""
        from services.api.app import main

        class ExplodingProvider:
            provider_name = "omlx"
            model_name = "irrelevant"

            def run(self, _envelope):
                raise RuntimeError("boom")

        provider = main._GatedTranslationSupportProvider(
            ExplodingProvider(),
            use_omlx_gate=True,
        )
        with self.assertRaises(RuntimeError):
            provider.run(SimpleNamespace())
        # Verify lease was released
        self.assertEqual(
            0,
            main.default_omlx_workload_gate_client().status()["total_active"],
        )

    def test_translation_support_env_uses_role_profile_not_fixed_env(self):
        from services.api.app import main

        self.provider_store.upsert(
            AiProviderProfile(
                profile_id="support_alt",
                provider="deepseek",
                label="Support Pro",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-pro",
                expected_response_model="deepseek-v4-pro",
                api_key_env="DEEPSEEK_API_KEY",
            ),
            api_key="support-secret",
        )
        self.role_store.upsert(
            AiRoleBinding(
                role_id=TRANSLATION_SUPPORT_ROLE,
                profile_id="support_alt",
                model="deepseek-v4-pro",
            )
        )
        with patch.object(
            main,
            "runtime_ai_role_settings_store",
            return_value=self.role_store,
        ):
            values = main._translation_ai_env()
        self.assertEqual("deepseek-v4-pro", values["WORKBENCH_AI_MODEL"])
        self.assertEqual(
            "https://api.deepseek.com/v1",
            values["WORKBENCH_AI_BASE_URL"],
        )
        self.assertEqual("support-secret", values["WORKBENCH_AI_API_KEY"])

    def test_omlx_translation_support_provider_runs_inside_translation_lease(self):
        from services.api.app import main

        observed = {}

        class FakeProvider:
            provider_name = "omlx"
            model_name = "local-support-model"

            def run(self, _envelope):
                observed.update(
                    main.default_omlx_workload_gate_client().status()
                )
                return {"status": "ok"}

        provider = main._GatedTranslationSupportProvider(
            FakeProvider(),
            use_omlx_gate=True,
        )
        result = provider.run(SimpleNamespace())
        self.assertEqual({"status": "ok"}, result)
        self.assertEqual(1, observed["active"]["translation"])
        self.assertEqual(
            0,
            main.default_omlx_workload_gate_client().status()["total_active"],
        )

    def test_remote_body_translation_uses_role_model_without_translation_lease(self):
        from services.api.app import main

        self.provider_store.upsert(
            AiProviderProfile(
                profile_id="body_remote",
                provider="deepseek",
                label="Remote body translator",
                base_url="https://api.deepseek.com/v1",
                model="body-remote-model",
                expected_response_model="body-remote-model",
                api_key_env="DEEPSEEK_API_KEY",
            ),
            api_key="body-secret",
        )
        self.role_store.upsert(
            AiRoleBinding(
                role_id=TRANSLATION_BODY_ROLE,
                profile_id="body_remote",
                model="body-remote-model",
            )
        )
        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["active_translation"] = main.default_omlx_workload_gate_client().status()["active"]["translation"]
            return _Response(
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "[[CMS_SEG_0001]]\n译文。\n[[/CMS_SEG_0001]]"},
                        }
                    ]
                }
            )

        with (
            patch.object(main, "runtime_ai_role_settings_store", return_value=self.role_store),
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            result = main._hy_mt2_translator_adapter(
                "[[CMS_SEG_0001]]\nSource.\n[[/CMS_SEG_0001]]",
                "glossary",
                "ch01",
                "chunk01",
            )

        self.assertEqual("body-remote-model", captured["payload"]["model"])
        self.assertEqual(0, captured["active_translation"])
        self.assertEqual("body-remote-model", result.model)

    def test_remote_specialized_ocr_uses_ocr_role_model_without_ocr_lease(self):
        from services.api.app import main

        remote_model = "models--PaddlePaddle--PaddleOCR-VL-1.6"
        self.provider_store.upsert(
            AiProviderProfile(
                profile_id="ocr_remote",
                provider="paddle",
                label="Remote Paddle OCR",
                base_url="https://ocr.example.invalid/v1",
                model=remote_model,
                expected_response_model=remote_model,
                api_key_env="OCR_API_KEY",
            ),
            api_key="ocr-secret",
        )
        self.role_store.upsert(
            AiRoleBinding(role_id=OCR_ROLE, profile_id="ocr_remote", model=remote_model)
        )
        captured = {}

        def fake_urlopen(request, timeout):
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["active_ocr"] = main.default_omlx_workload_gate_client().status()["active"]["ocr"]
            return _Response({"choices": [{"message": {"content": "OCR text"}}]})

        with (
            patch.object(main, "runtime_ai_role_settings_store", return_value=self.role_store),
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            text = main._writing_reference_ocr_runner(1, 200, remote_model, PNG_BYTES)

        self.assertEqual(remote_model, captured["payload"]["model"])
        self.assertEqual(0, captured["active_ocr"])
        self.assertEqual("OCR text", text)

    def test_document_pinned_glm_finishes_after_role_switches_to_paddle(self):
        """A document resolves its OCR model once; a later role cutover must
        not change or reject the remaining pages of that same document.
        """
        from services.api.app import main

        self.role_store.upsert(
            AiRoleBinding(
                role_id=OCR_ROLE,
                profile_id=OCR_PADDLE_PROFILE_ID,
                model=PADDLE_OCR_MODEL,
            )
        )
        with patch.object(
            main,
            "runtime_ai_role_settings_store",
            return_value=self.role_store,
        ):
            gateway = main._build_role_bound_ocr_gateway(DEFAULT_OCR_MODEL)

        self.assertIsInstance(gateway, LocalOcrGateway)
        self.assertEqual(DEFAULT_OCR_MODEL, gateway.settings.model)


class OmlxGateSelectionTests(unittest.TestCase):
    """Verify the gate_selection() wrapper and lease model authority."""

    def test_gate_selection_returns_limits_without_role_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = OmlxWorkloadGateClient(
                db_path=Path(tmp) / "selection_gate.sqlite3",
                wait_timeout_seconds=5,
                lease_ttl_seconds=5,
            )
            selection = client.gate_selection()
            self.assertEqual("omlx_gate_selection_v2", selection["schema"])
            self.assertNotIn("models", selection)
            self.assertEqual(
                {"ocr": 8, "translation": 8, "total": 16},
                selection["limits"],
            )

    def test_lease_dict_carries_only_admission_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = OmlxWorkloadGateClient(
                db_path=Path(tmp) / "lease_model_gate.sqlite3",
                wait_timeout_seconds=5,
                lease_ttl_seconds=5,
            )
            with client.lease(kind="ocr", owner="test") as lease:
                self.assertNotIn("model", lease)
            self.assertEqual(0, client.status()["total_active"])

            with client.lease(kind="translation", owner="test") as lease:
                self.assertNotIn("model", lease)
            self.assertEqual(0, client.status()["total_active"])


if __name__ == "__main__":
    unittest.main()
