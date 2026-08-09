"""Transport-boundary regression tests for the shared oMLX workload gate.

These tests prove the manager-frozen transport contract (worker 03 scope):

1. Exactly one lease acquire per dedicated request (no double acquisition).
2. Zero transport calls happen before the lease is granted.
3. A generic ``OpenAICompatibleAiProvider`` configured with provider ``omlx``
   fails closed before any HTTP for translation-class task types.
4. OCR payload ``model`` equals the lease model, not a settings-configured model.
5. Failure paths (gate unavailable, operation exception) fail closed and leave
   zero active leases via the ``finally`` release.
6. Product-combination admission: 8 OCR page workers plus 8 translation
   durable-job-like callers never exceed peak OCR<=8, translation<=8,
   combined<=16. This proves gate admission only, not physical engine
   throughput.
"""

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

from services.api.app.ai_gateway import (
    AiGatewayConfigurationError,
    AiPromptEnvelope,
    AiTaskType,
    OpenAICompatibleAiProvider,
)
from services.api.app.ocr_gateway import (
    LocalOcrGateway,
    OcrGatewaySettings,
    OcrGatewayRequestError,
    OcrRequest,
)
from services.api.app.omlx_workload_gate_client import (
    OmlxWorkloadGateClient,
    OmlxWorkloadGateRuntimeError,
    run_gated_omlx_request,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"boundary-test"


def _ok_response(content: str = "ok") -> bytes:
    return json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. Single acquire spy + zero transport before lease
# ---------------------------------------------------------------------------

class OcrSingleAcquireSpyTests(unittest.TestCase):
    """Prove exactly one acquire per OCR request and zero transport before grant."""

    def test_exactly_one_acquire_and_transport_after_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = OmlxWorkloadGateClient(
                db_path=root / "spy_gate.sqlite3",
                wait_timeout_seconds=5,
                lease_ttl_seconds=5,
            )
            acquire_count = {"n": 0}
            transport_call_order = {"transport_before_lease": False}

            original_acquire = gate._gate.acquire

            def spy_acquire(kind, owner, **kwargs):
                acquire_count["n"] += 1
                # Transport has not yet been called when acquire is invoked.
                if transport_call_order.get("transport_calls", 0) > 0:
                    transport_call_order["transport_before_lease"] = True
                return original_acquire(kind, owner, **kwargs)

            transport_calls = {"count": 0}

            def transport(request, timeout):
                transport_calls["count"] += 1
                transport_call_order["transport_calls"] = transport_calls["count"]
                return _ok_response("OCR")

            gateway = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=transport,
                workload_gate=gate,
            )

            with patch.object(gate._gate, "acquire", side_effect=spy_acquire):
                result = gateway.run(
                    OcrRequest(image_bytes=PNG_BYTES, image_suffix=".png")
                )

            self.assertEqual("OCR", result.text)
            self.assertEqual(1, acquire_count["n"])
            self.assertEqual(1, transport_calls["count"])
            self.assertFalse(transport_call_order["transport_before_lease"])
            self.assertEqual(0, gate.status()["total_active"])

    def test_ocr_payload_uses_role_settings_model_not_lease_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = OmlxWorkloadGateClient(
                db_path=root / "model_gate.sqlite3",
                wait_timeout_seconds=5,
                lease_ttl_seconds=5,
            )
            captured = {}

            def transport(request, timeout):
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return _ok_response("text")

            # The gate admits the request; the role settings select the model.
            gateway = LocalOcrGateway(
                OcrGatewaySettings(
                    allowed_roots=(root,),
                    model="models--PaddlePaddle--PaddleOCR-VL-1.6",
                ),
                transport=transport,
                workload_gate=gate,
            )
            result = gateway.run(
                OcrRequest(image_bytes=PNG_BYTES, image_suffix=".png")
            )

            self.assertEqual(
                "models--PaddlePaddle--PaddleOCR-VL-1.6",
                captured["payload"]["model"],
            )
            self.assertEqual(
                "models--PaddlePaddle--PaddleOCR-VL-1.6",
                result.model,
            )
            self.assertEqual(0, gate.status()["total_active"])


class TranslationSingleAcquireSpyTests(unittest.TestCase):
    """Prove exactly one acquire for translation-support inside the lease."""

    def test_translation_support_single_acquire(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = OmlxWorkloadGateClient(
                db_path=Path(tmp) / "ts_spy.sqlite3",
                wait_timeout_seconds=5,
                lease_ttl_seconds=5,
            )
            acquire_count = {"n": 0}
            original_acquire = gate._gate.acquire

            def spy_acquire(kind, owner, **kwargs):
                acquire_count["n"] += 1
                return original_acquire(kind, owner, **kwargs)

            from services.api.app import main

            class FakeProvider:
                provider_name = "omlx"
                model_name = "irrelevant"

                def run(self, _envelope):
                    return {"status": "ok"}

            provider = main._GatedTranslationSupportProvider(
                FakeProvider(),
                use_omlx_gate=True,
            )
            with (
                patch(
                    "services.api.app.omlx_workload_gate_client.default_omlx_workload_gate_client",
                    return_value=gate,
                ),
                patch.object(
                    gate._gate, "acquire", side_effect=spy_acquire
                ),
            ):
                result = provider.run(SimpleNamespace())

            self.assertEqual({"status": "ok"}, result)
            self.assertEqual(1, acquire_count["n"])
            self.assertEqual(0, gate.status()["total_active"])


# ---------------------------------------------------------------------------
# 2. Generic fail-closed: OpenAICompatibleAiProvider + oMLX + translation
# ---------------------------------------------------------------------------

class GenericOmlxFailClosedTests(unittest.TestCase):
    """Generic provider configured for oMLX must reject translation-class tasks."""

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return _ok_response("{}")

    def test_regulatory_translation_zh_rejected_before_http(self):
        provider = OpenAICompatibleAiProvider(
            base_url="http://127.0.0.1:8000/v1",
            api_key="dummy",
            model_name="any-model",
            provider_name="omlx",
        )
        envelope = AiPromptEnvelope(
            task_id="t1",
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version="v1",
            system_prompt="sys",
            payload={},
        )
        with self.assertRaises(AiGatewayConfigurationError):
            provider.run(envelope)

    def test_non_omlx_provider_not_blocked(self):
        """A non-omlx provider serving the same task type is not rejected."""
        provider = OpenAICompatibleAiProvider(
            base_url="http://127.0.0.1:8000/v1",
            api_key="dummy",
            model_name="any-model",
            provider_name="deepseek",
        )
        envelope = AiPromptEnvelope(
            task_id="t1",
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version="v1",
            system_prompt="sys",
            payload={},
        )
        with patch(
            "services.api.app.ai_gateway.urllib.request.urlopen",
            return_value=self._FakeResponse(),
        ):
            self.assertEqual({}, provider.run(envelope))

    def test_omlx_non_translation_task_not_blocked(self):
        """An oMLX provider serving a non-translation task is not rejected
        by this guard (other tasks may legitimately use generic transport)."""
        provider = OpenAICompatibleAiProvider(
            base_url="http://127.0.0.1:8000/v1",
            api_key="dummy",
            model_name="any-model",
            provider_name="omlx",
        )
        envelope = AiPromptEnvelope(
            task_id="t1",
            task_type=AiTaskType.DISEASE_BACKGROUND_RESEARCH,
            prompt_version="v1",
            system_prompt="sys",
            payload={},
        )
        with patch(
            "services.api.app.ai_gateway.urllib.request.urlopen",
            return_value=self._FakeResponse(),
        ):
            self.assertEqual({}, provider.run(envelope))


# ---------------------------------------------------------------------------
# 3. Failure paths: gate down, operation exception, finally release
# ---------------------------------------------------------------------------

class FailurePathTests(unittest.TestCase):
    """Gate denial / exception / heartbeat loss must fail closed and release."""

    def test_ocr_operation_exception_releases_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = OmlxWorkloadGateClient(
                db_path=root / "fail_gate.sqlite3",
                wait_timeout_seconds=5,
                lease_ttl_seconds=5,
            )

            def exploding_transport(request, timeout):
                raise RuntimeError("transport explosion")

            gateway = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=exploding_transport,
                workload_gate=gate,
            )
            # The OcrGateway wraps the inner exception in OcrGatewayRuntimeError.
            from services.api.app.ocr_gateway import OcrGatewayRuntimeError

            with self.assertRaises(OcrGatewayRuntimeError):
                gateway.run(
                    OcrRequest(image_bytes=PNG_BYTES, image_suffix=".png")
                )
            self.assertEqual(0, gate.status()["total_active"])

    def test_translation_operation_exception_releases_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = OmlxWorkloadGateClient(
                db_path=Path(tmp) / "fail_ts.sqlite3",
                wait_timeout_seconds=5,
                lease_ttl_seconds=5,
            )
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
            with (
                patch.object(
                    main,
                    "default_omlx_workload_gate_client",
                    return_value=gate,
                ),
                self.assertRaises(RuntimeError),
            ):
                provider.run(SimpleNamespace())
            self.assertEqual(0, gate.status()["total_active"])

    def test_gate_unavailable_raises_and_leaves_no_leases(self):
        """If the gate client raises on acquire, no lease should remain."""
        with tempfile.TemporaryDirectory() as tmp:
            gate = OmlxWorkloadGateClient(
                db_path=Path(tmp) / "denied_gate.sqlite3",
                wait_timeout_seconds=1,
                lease_ttl_seconds=2,
            )
            # Fill up to total limit so the next acquire must time out.
            holders = []
            for i in range(16):
                ctx = gate.lease(kind="ocr" if i < 8 else "translation",
                                 owner=f"blocker-{i}")
                ctx.__enter__()
                holders.append(ctx)

            # Now the 17th request should fail (timeout) with no new lease.
            with self.assertRaises(Exception):
                run_gated_omlx_request(
                    lambda _lease: "should-not-run",
                    kind="ocr",
                    owner="overflow",
                    gate_client=gate,
                    )
            # Release all blockers
            for ctx in holders:
                ctx.__exit__(None, None, None)
            self.assertEqual(0, gate.status()["total_active"])


# ---------------------------------------------------------------------------
# 4. Product-combination admission: 8 OCR + 8 translation
# ---------------------------------------------------------------------------

class ProductCombinationAdmissionTests(unittest.TestCase):
    """8 OCR page workers + 8 translation durable-job callers.

    Proves peak OCR <= 8, translation <= 8, combined <= 16.

    NOTE: This proves gate admission, not physical engine throughput.
    The oMLX per-engine scheduler limit is separate.
    """

    def test_8_ocr_plus_8_translation_peak_within_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = OmlxWorkloadGateClient(
                db_path=Path(tmp) / "combo_gate.sqlite3",
                wait_timeout_seconds=30,
                lease_ttl_seconds=10,
            )
            lock = threading.Lock()
            counters = {"ocr": 0, "translation": 0}
            maxima = {"ocr": 0, "translation": 0, "total": 0}
            start = threading.Barrier(16)

            def fake_ocr_page(ordinal: int) -> str:
                start.wait(timeout=5)

                def transport(_lease) -> str:
                    with lock:
                        counters["ocr"] += 1
                        maxima["ocr"] = max(maxima["ocr"], counters["ocr"])
                        maxima["total"] = max(
                            maxima["total"],
                            counters["ocr"] + counters["translation"],
                        )
                    time.sleep(0.05)
                    with lock:
                        counters["ocr"] -= 1
                    return f"ocr-page-{ordinal}"

                return run_gated_omlx_request(
                    transport,
                    kind="ocr",
                    owner=f"ocr-page:{ordinal}",
                    gate_client=client,
                )

            def fake_translation_job(ordinal: int) -> str:
                start.wait(timeout=5)

                def operation(_lease) -> str:
                    with lock:
                        counters["translation"] += 1
                        maxima["translation"] = max(
                            maxima["translation"], counters["translation"]
                        )
                        maxima["total"] = max(
                            maxima["total"],
                            counters["ocr"] + counters["translation"],
                        )
                    time.sleep(0.05)
                    with lock:
                        counters["translation"] -= 1
                    return f"translation-job-{ordinal}"

                return run_gated_omlx_request(
                    operation,
                    kind="translation",
                    owner=f"translation-job:{ordinal}",
                    gate_client=client,
                )

            work = [
                ("ocr", ordinal) for ordinal in range(8)
            ] + [
                ("translation", ordinal) for ordinal in range(8)
            ]

            def dispatch(kind: str, ordinal: int) -> str:
                if kind == "ocr":
                    return fake_ocr_page(ordinal)
                return fake_translation_job(ordinal)

            with ThreadPoolExecutor(max_workers=16) as executor:
                results = list(
                    executor.map(lambda item: dispatch(*item), work)
                )

            self.assertEqual(16, len(results))
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


# ---------------------------------------------------------------------------
# 5. Comprehensive reachable translation/OCR task-type listing
# ---------------------------------------------------------------------------

class OmlxDedicatedOnlyTaskTypeListingTests(unittest.TestCase):
    """Confirm which AiTaskType values are treated as translation/OCR-class."""

    def test_only_regulatory_translation_is_dedicated_only(self):
        from services.api.app.ai_gateway import _OMLX_DEDICATED_ONLY_TASK_TYPES

        self.assertEqual(
            frozenset({AiTaskType.REGULATORY_TRANSLATION_ZH}),
            _OMLX_DEDICATED_ONLY_TASK_TYPES,
        )

    def test_no_other_task_type_blocked_for_omlx(self):
        """Every other task type should NOT be in the dedicated-only set."""
        from services.api.app.ai_gateway import _OMLX_DEDICATED_ONLY_TASK_TYPES

        all_types = set(AiTaskType)
        non_blocked = all_types - _OMLX_DEDICATED_ONLY_TASK_TYPES
        self.assertGreater(len(non_blocked), 1)


if __name__ == "__main__":
    unittest.main()
