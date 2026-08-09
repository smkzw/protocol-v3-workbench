from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from contextlib import contextmanager
from dataclasses import is_dataclass
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from services.api.app.ocr_gateway import (
    LocalOcrGateway,
    OcrGatewayConfigurationError,
    OcrGatewayRequestError,
    OcrGatewayRuntimeError,
    OcrGatewaySettings,
    OcrRequest,
    OcrResult,
)


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"synthetic-image-data"


class FakeHttpResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self.body


class FakeWorkloadGate:
    def __init__(self, model: str):
        self.model = model

    @contextmanager
    def lease(self, *, kind: str, owner: str):
        self.last_kind = kind
        self.last_owner = owner
        yield {"lease_id": "lease_test_ocr", "model": self.model}


class OcrGatewayTests(unittest.TestCase):
    @staticmethod
    def response(text: str) -> bytes:
        return json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")

    @staticmethod
    def write_png(root: Path, filename: str = "synthetic.png") -> Path:
        source = root / filename
        source.write_bytes(PNG_BYTES)
        return source

    def test_success_uses_default_glm_multimodal_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_png(root)
            captured = {}

            def transport(request, timeout_seconds):
                captured["request"] = request
                captured["timeout_seconds"] = timeout_seconds
                return json.dumps(
                    {"choices": [{"message": {"content": "TEST-001\nNegative"}}]}
                ).encode("utf-8")

            gateway = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=transport,
            )

            result = gateway.run(OcrRequest(source_path=source))

        self.assertEqual("TEST-001\nNegative", result.text)
        self.assertEqual("GLM-OCR-bf16", result.model)
        self.assertEqual(len(result.text), result.character_count)
        self.assertEqual(64, len(result.content_hash))
        self.assertTrue(result.source_token.startswith("ocrsrc_"))
        self.assertIsNotNone(result.called_at.tzinfo)
        self.assertGreaterEqual(result.duration_ms, 0)
        self.assertEqual((), result.warnings)
        self.assertEqual(0, captured["request"].data.count(b"synthetic.png"))
        payload = json.loads(captured["request"].data.decode("utf-8"))
        self.assertEqual("GLM-OCR-bf16", payload["model"])
        self.assertEqual(0, payload["temperature"])
        content = payload["messages"][0]["content"]
        self.assertEqual("text", content[0]["type"])
        self.assertIn("逐字", content[0]["text"])
        self.assertIn("不得", content[0]["text"])
        self.assertIn("遮挡", content[0]["text"])
        self.assertIn("补写", content[0]["text"])
        self.assertEqual("image_url", content[1]["type"])
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_settings_request_and_result_are_dataclasses(self) -> None:
        self.assertTrue(is_dataclass(OcrGatewaySettings))
        self.assertTrue(is_dataclass(OcrRequest))
        self.assertTrue(is_dataclass(OcrResult))

    def test_settings_allow_only_localhost_and_allowlisted_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            local = OcrGatewaySettings(
                allowed_roots=(root,),
                base_url="http://localhost:8000/v1/",
            )
            self.assertEqual("http://localhost:8000/v1", local.base_url)
            self.assertTrue(local.allowed_roots[0].is_absolute())

            for remote_url in (
                "https://ocr.example.test/v1",
                "http://localhost.example.test/v1",
                "http://127.0.0.1.example.test/v1",
                "http://user@localhost:8000/v1",
            ):
                with self.subTest(remote_url=remote_url):
                    with self.assertRaisesRegex(
                        OcrGatewayConfigurationError,
                        "must use localhost or 127.0.0.1",
                    ):
                        OcrGatewaySettings(allowed_roots=(root,), base_url=remote_url)

            with self.assertRaisesRegex(OcrGatewayConfigurationError, "not allowlisted"):
                OcrGatewaySettings(allowed_roots=(root,), model="unavailable-ocr-model")

    def test_root_traversal_and_directory_are_rejected_without_path_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            allowed = parent / "allowed"
            outside = parent / "outside"
            allowed.mkdir()
            outside.mkdir()
            outside_source = self.write_png(outside, "private-patient.png")
            gateway = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(allowed,)),
                transport=lambda request, timeout: self.response("unused"),
            )

            with self.assertRaises(OcrGatewayRequestError) as traversal:
                gateway.run(OcrRequest(source_path=allowed / ".." / "outside" / outside_source.name))
            self.assertEqual("OCR source is outside allowed roots", str(traversal.exception))
            self.assertNotIn(outside_source.name, str(traversal.exception))
            self.assertNotIn(str(parent), str(traversal.exception))

            directory = allowed / "folder.png"
            directory.mkdir()
            with self.assertRaisesRegex(OcrGatewayRequestError, "must be a file"):
                gateway.run(OcrRequest(source_path=directory))

            missing = allowed / "private-missing.png"
            with self.assertRaises(OcrGatewayRequestError) as missing_error:
                gateway.run(OcrRequest(source_path=missing))
            self.assertEqual(
                "OCR source is not an existing file",
                str(missing_error.exception),
            )
            self.assertNotIn(missing.name, str(missing_error.exception))
            self.assertIsNone(missing_error.exception.__cause__)

    def test_format_validation_rejects_extension_and_disguised_non_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsupported = root / "synthetic.gif"
            unsupported.write_bytes(b"GIF89a")
            disguised = root / "synthetic.png"
            disguised.write_bytes(b"not-an-image")
            gateway = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=lambda request, timeout: self.response("unused"),
            )

            with self.assertRaisesRegex(OcrGatewayRequestError, "format is not supported"):
                gateway.run(OcrRequest(source_path=unsupported))
            with self.assertRaisesRegex(OcrGatewayRequestError, "not a supported image"):
                gateway.run(OcrRequest(source_path=disguised))

    def test_all_supported_image_extensions_use_matching_data_url_mime_type(self) -> None:
        samples = {
            ".jpg": (b"\xff\xd8\xffjpeg", "image/jpeg"),
            ".jpeg": (b"\xff\xd8\xffjpeg", "image/jpeg"),
            ".png": (PNG_BYTES, "image/png"),
            ".webp": (b"RIFF\x04\x00\x00\x00WEBPdata", "image/webp"),
            ".tif": (b"II*\x00tiff", "image/tiff"),
            ".tiff": (b"MM\x00*tiff", "image/tiff"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for suffix, (content, mime_type) in samples.items():
                with self.subTest(suffix=suffix):
                    source = root / f"synthetic{suffix}"
                    source.write_bytes(content)
                    captured = {}

                    def transport(request, timeout):
                        captured["payload"] = json.loads(request.data.decode("utf-8"))
                        return self.response("ok")

                    gateway = LocalOcrGateway(
                        OcrGatewaySettings(allowed_roots=(root,)),
                        transport=transport,
                    )
                    gateway.run(OcrRequest(source_path=source))
                    data_url = captured["payload"]["messages"][0]["content"][1]["image_url"]["url"]
                    self.assertTrue(data_url.startswith(f"data:{mime_type};base64,"))

    def test_empty_text_and_invalid_response_structure_fail_closed(self) -> None:
        invalid_responses = (
            self.response("   \n"),
            b"not-json",
            json.dumps({"choices": []}).encode("utf-8"),
            json.dumps({"error": {"message": "missing model and private OCR body"}}).encode("utf-8"),
            json.dumps({"choices": [{"message": {"content": ["not", "text"]}}]}).encode("utf-8"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_png(root)
            for response_body in invalid_responses:
                with self.subTest(response_body=response_body[:24]):
                    gateway = LocalOcrGateway(
                        OcrGatewaySettings(allowed_roots=(root,)),
                        transport=lambda request, timeout, body=response_body: body,
                    )
                    with self.assertRaises(OcrGatewayRuntimeError) as raised:
                        gateway.run(OcrRequest(source_path=source))
                    self.assertEqual("Local OCR response is invalid", str(raised.exception))
                    self.assertIsNone(raised.exception.__cause__)

    def test_role_selected_paddle_model_is_sent_and_returned(self) -> None:
        paddle_model = "models--PaddlePaddle--PaddleOCR-VL-1.6"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_png(root)
            captured = {}
            gate = FakeWorkloadGate(paddle_model)

            def transport(request, timeout):
                captured["payload"] = json.loads(request.data.decode("utf-8"))
                return self.response("PADDLE TEST")

            result = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=transport,
                workload_gate=gate,
            ).run(OcrRequest(source_path=source))

        self.assertEqual("GLM-OCR-bf16", captured["payload"]["model"])
        self.assertEqual("GLM-OCR-bf16", result.model)
        self.assertEqual("ocr", gate.last_kind)
        self.assertEqual("medical-writing-api:ocr", gate.last_owner)

    def test_public_audit_dict_excludes_sensitive_and_reversible_fields(self) -> None:
        private_text = "PATIENT-ALPHA private OCR text"
        private_filename = "PATIENT-ALPHA-visit.png"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_png(root, private_filename)
            result = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=lambda request, timeout: self.response(private_text),
            ).run(OcrRequest(source_path=source))

        audit = result.public_audit_dict()
        serialized = json.dumps(audit, ensure_ascii=False)
        self.assertEqual(
            {
                "status",
                "model",
                "source_token",
                "character_count",
                "called_at",
                "duration_ms",
            },
            set(audit),
        )
        self.assertEqual("succeeded", audit["status"])
        self.assertEqual(len(private_text), audit["character_count"])
        self.assertNotIn(private_text, serialized)
        self.assertNotIn(private_filename, serialized)
        self.assertNotIn(str(root), serialized)
        self.assertNotIn(result.content_hash, serialized)
        self.assertNotIn("content_hash", serialized)
        self.assertNotIn("base64", serialized)
        self.assertLessEqual(len(audit["source_token"]), 24)

    def test_http_failure_uses_stable_error_without_provider_detail(self) -> None:
        private_detail = "model missing for PATIENT-ALPHA"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_png(root, "PATIENT-ALPHA.png")

            def transport(request, timeout):
                raise urllib.error.HTTPError(
                    request.full_url,
                    404,
                    private_detail,
                    hdrs=None,
                    fp=None,
                )

            gateway = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=transport,
            )
            with self.assertRaises(OcrGatewayRuntimeError) as raised:
                gateway.run(OcrRequest(source_path=source))

        self.assertEqual("Local OCR request failed", str(raised.exception))
        self.assertNotIn(private_detail, str(raised.exception))
        self.assertNotIn(source.name, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_unavailable_local_service_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_png(root)

            def transport(request, timeout):
                raise urllib.error.URLError("connection refused with private detail")

            gateway = LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=transport,
            )
            with self.assertRaises(OcrGatewayRuntimeError) as raised:
                gateway.run(OcrRequest(source_path=source))

        self.assertEqual("Local OCR request failed", str(raised.exception))
        self.assertNotIn("private detail", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_default_transport_disables_proxies_and_redirects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_png(root)
            with patch(
                "services.api.app.ocr_gateway.urllib.request.build_opener"
            ) as build_opener, patch(
                "services.api.app.ocr_gateway.urllib.request.urlopen",
                side_effect=AssertionError("redirect-following urlopen must not be used"),
            ):
                build_opener.return_value.open.return_value = FakeHttpResponse(
                    self.response("local only")
                )

                result = LocalOcrGateway(
                    OcrGatewaySettings(allowed_roots=(root,))
                ).run(OcrRequest(source_path=source))

        self.assertEqual("local only", result.text)
        handlers = build_opener.call_args.args
        self.assertTrue(any(isinstance(handler, urllib.request.ProxyHandler) for handler in handlers))
        redirect_handlers = [
            handler
            for handler in handlers
            if isinstance(handler, urllib.request.HTTPRedirectHandler)
        ]
        self.assertEqual(1, len(redirect_handlers))
        with self.assertRaises(urllib.error.HTTPError):
            redirect_handlers[0].redirect_request(
                build_opener.return_value.open.call_args.args[0],
                None,
                302,
                "redirect blocked",
                {},
                "https://remote.example.test/ocr",
            )

    def test_gateway_does_not_create_or_modify_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = self.write_png(root)
            before = {
                path.name: (
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                    sha256(path.read_bytes()).hexdigest(),
                )
                for path in root.iterdir()
            }

            LocalOcrGateway(
                OcrGatewaySettings(allowed_roots=(root,)),
                transport=lambda request, timeout: self.response("memory only"),
            ).run(OcrRequest(source_path=source))

            after = {
                path.name: (
                    path.stat().st_size,
                    path.stat().st_mtime_ns,
                    sha256(path.read_bytes()).hexdigest(),
                )
                for path in root.iterdir()
            }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
