from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from PIL import Image, ImageCms, PngImagePlugin

from services.api.app import vlm_gateway as vlm_gateway_module
from packages.contracts.workbench_contracts.models import EligibilityVlmDescriptor
from services.api.app.vlm_gateway import (
    LocalVlmGateway,
    VlmCircuitBreaker,
    VlmCircuitBreakerPolicy,
    VlmGatewayConfigurationError,
    VlmGatewayRequestError,
    VlmGatewayRuntimeError,
    VlmGatewaySettings,
    VlmNormalizationPolicy,
    VlmPrivacyViolationError,
    VlmProfile,
    assert_vlm_public_payload_safe,
    normalize_vlm_image,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "packages"
    / "contracts"
    / "schemas"
    / "eligibility_visual_descriptor_v1.schema.json"
)


def image_bytes(
    image_format: str = "PNG",
    *,
    mode: str = "RGB",
    size=(32, 24),
    metadata: bool = False,
) -> bytes:
    color = (30, 90, 180, 128) if mode == "RGBA" else (30, 90, 180)
    image = Image.new(mode, size, color)
    output = io.BytesIO()
    kwargs = {}
    if image_format == "PNG" and metadata:
        info = PngImagePlugin.PngInfo()
        info.add_text("patient_name", "Synthetic Person")
        kwargs["pnginfo"] = info
    if image_format == "JPEG":
        image = image.convert("RGB")
    image.save(output, format=image_format, **kwargs)
    return output.getvalue()


def descriptor_payload(**overrides):
    payload = {
        "schema_version": "eligibility_visual_descriptor_v1",
        "media_class": "document_page",
        "primary_document_type": "medical_record",
        "capture_quality": {
            "overall": "adequate_for_human_qc",
            "flags": ["none"],
        },
        "orientation": "upright",
        "requires_human_attention": ["none"],
    }
    payload.update(overrides)
    return payload


def completion_bytes(content=None) -> bytes:
    if content is None:
        content = json.dumps(descriptor_payload(), separators=(",", ":"))
    return json.dumps(
        {
            "model": "synthetic-vlm-model",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def profile(**overrides) -> VlmProfile:
    values = {
        "profile_version": "vlm-profile-v1",
        "model": "synthetic-vlm-model",
        "model_artifact_digest": "a" * 64,
        "processor": "synthetic-processor",
        "processor_digest": "b" * 64,
        "serving_engine": "vllm",
        "serving_engine_version": "fixture",
        "normalization": VlmNormalizationPolicy(
            max_bytes=1_000_000,
            max_width=512,
            max_height=512,
            max_pixels=262_144,
        ),
        "circuit_breaker": VlmCircuitBreakerPolicy(
            minimum_sample_size=2,
            rolling_window_size=4,
            failure_threshold=0.5,
            cooldown_seconds=30,
        ),
    }
    values.update(overrides)
    return VlmProfile(**values)


class MutableClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class VlmGatewayTests(unittest.TestCase):
    def test_schema_artifact_matches_runtime_model(self):
        self.assertTrue(SCHEMA_PATH.is_file())
        self.assertEqual(
            EligibilityVlmDescriptor.model_json_schema(),
            json.loads(SCHEMA_PATH.read_text(encoding="utf-8")),
        )

    def test_profile_digest_is_deterministic_and_binds_material_settings(self):
        baseline = profile()
        baseline_digest = baseline.profile_digest
        self.assertEqual(baseline.profile_digest, profile().profile_digest)
        changed = profile(model="different-model")
        self.assertNotEqual(baseline.profile_digest, changed.profile_digest)
        changed = profile(max_response_bytes=32_768)
        self.assertNotEqual(baseline.profile_digest, changed.profile_digest)
        changed = profile(max_content_bytes=8_192)
        self.assertNotEqual(baseline.profile_digest, changed.profile_digest)
        mutations = (
            {"model_artifact_digest": "c" * 64},
            {"processor": "changed-processor"},
            {"processor_digest": "d" * 64},
            {"serving_engine_version": "changed-engine"},
            {"cross_field_policy_digest": "e" * 64},
            {"forbidden_output_policy_digest": "f" * 64},
            {"error_taxonomy_version": "changed-error-taxonomy"},
            {"max_attempts_default": 2},
            {"request_timeout_seconds": 60.0},
            {
                "normalization": VlmNormalizationPolicy(
                    max_bytes=900_000,
                    max_width=512,
                    max_height=512,
                    max_pixels=262_144,
                )
            },
            {
                "circuit_breaker": VlmCircuitBreakerPolicy(
                    minimum_sample_size=2,
                    rolling_window_size=4,
                    failure_threshold=0.75,
                    cooldown_seconds=30,
                )
            },
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertNotEqual(
                    baseline_digest, profile(**mutation).profile_digest
                )
        with mock.patch.object(
            vlm_gateway_module,
            "VLM_SYSTEM_PROMPT",
            vlm_gateway_module.VLM_SYSTEM_PROMPT + "\nSynthetic change.",
        ):
            self.assertNotEqual(baseline_digest, profile().profile_digest)
        altered_schema = EligibilityVlmDescriptor.model_json_schema()
        altered_schema = {**altered_schema, "title": "Synthetic schema change"}
        with mock.patch.object(
            EligibilityVlmDescriptor,
            "model_json_schema",
            return_value=altered_schema,
        ):
            self.assertNotEqual(baseline_digest, profile().profile_digest)

    def test_profile_rejects_placeholder_digests_and_timeout_drift(self):
        with self.assertRaisesRegex(VlmGatewayConfigurationError, "digest field"):
            profile(model_artifact_digest="pending")
        with self.assertRaisesRegex(VlmGatewayConfigurationError, "does not match"):
            VlmGatewaySettings(
                base_url="http://127.0.0.1:8000",
                profile=profile(request_timeout_seconds=60),
                timeout_seconds=120,
            )

    def test_settings_accept_only_local_openai_base_paths(self):
        for url in (
            "http://127.0.0.1:8000",
            "http://127.0.0.1:8000/v1",
        ):
            settings = VlmGatewaySettings(base_url=url, profile=profile())
            self.assertFalse(settings.base_url.endswith("/"))
        for url in (
            "https://127.0.0.1:8000/v1",
            "http://0.0.0.0:8000/v1",
            "http://localhost:8000/v1",
            "http://[::1]:8000/v1",
            "http://127.0.0.1.evil.test/v1",
            "http://user:pass@localhost:8000/v1",
            "http://localhost:8000/v1?token=x",
            "http://localhost:8000/other",
        ):
            with self.subTest(url=url), self.assertRaises(VlmGatewayConfigurationError):
                VlmGatewaySettings(base_url=url, profile=profile())

    def test_default_transport_ignores_proxy_and_blocks_redirects(self):
        response = completion_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/v1/chat/completions")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/chat/completions",
                data=b"{}",
                method="POST",
            )
            with mock.patch.dict(
                os.environ,
                {"HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""},
                clear=False,
            ):
                self.assertEqual(
                    response,
                    vlm_gateway_module._urllib_transport(request, 2.0, 65_536),
                )
                approved = profile(request_timeout_seconds=2.0)
                gateway = LocalVlmGateway(
                    VlmGatewaySettings(
                        base_url=f"http://127.0.0.1:{port}/v1",
                        profile=approved,
                        timeout_seconds=2.0,
                    )
                )
                result = gateway.run(
                    image_bytes=image_bytes(),
                    mime_type="image/png",
                    expected_profile_digest=approved.profile_digest,
                )
                self.assertEqual("descriptor_valid", result.outcome.value)
            redirect = urllib.request.Request(
                f"http://127.0.0.1:{port}/redirect", data=b"{}", method="POST"
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                vlm_gateway_module._urllib_transport(redirect, 2.0, 65_536)
            self.assertEqual(302, caught.exception.code)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_normalization_strips_png_metadata_and_flattens_alpha(self):
        normalized = normalize_vlm_image(
            image_bytes(mode="RGBA", metadata=True),
            "image/png",
            profile().normalization,
        )
        self.assertEqual("image/png", normalized.mime_type)
        with Image.open(io.BytesIO(normalized.image_bytes)) as reopened:
            self.assertEqual("RGB", reopened.mode)
            self.assertNotIn("patient_name", reopened.info)
        self.assertNotIn(normalized.content_hash, repr(normalized))
        self.assertNotIn("image_bytes", repr(normalized))

    def test_f14_jpeg_and_webp_exif_are_removed(self):
        exif = Image.Exif()
        exif[270] = "Synthetic metadata instruction"
        for image_format, mime_type in (("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
            source = Image.new("RGB", (20, 12), (80, 100, 120))
            output = io.BytesIO()
            source.save(output, format=image_format, exif=exif)
            raw = output.getvalue()
            with Image.open(io.BytesIO(raw)) as original:
                self.assertTrue(original.getexif())
            normalized = normalize_vlm_image(
                raw, mime_type, profile().normalization
            )
            with Image.open(io.BytesIO(normalized.image_bytes)) as reopened:
                self.assertFalse(reopened.getexif())
                self.assertNotIn("exif", reopened.info)

    def test_f14_orientation_is_applied_and_icc_profile_is_removed(self):
        source = Image.new("RGB", (12, 20), (40, 80, 120))
        exif = Image.Exif()
        exif[274] = 6
        icc_profile = ImageCms.ImageCmsProfile(
            ImageCms.createProfile("sRGB")
        ).tobytes()
        output = io.BytesIO()
        source.save(
            output,
            format="JPEG",
            exif=exif,
            icc_profile=icc_profile,
            quality=95,
        )
        raw = output.getvalue()
        with Image.open(io.BytesIO(raw)) as original:
            self.assertIn("icc_profile", original.info)
            self.assertEqual(6, original.getexif()[274])
        normalized = normalize_vlm_image(
            raw, "image/jpeg", profile().normalization
        )
        self.assertEqual((20, 12), (normalized.width, normalized.height))
        with Image.open(io.BytesIO(normalized.image_bytes)) as reopened:
            self.assertNotIn("icc_profile", reopened.info)
            self.assertFalse(reopened.getexif())

    def test_palette_transparency_is_flattened_against_profile_background(self):
        source = Image.new("P", (4, 4), 0)
        source.putpalette([255, 0, 0] + [0, 0, 0] * 255)
        output = io.BytesIO()
        source.save(output, format="PNG", transparency=0)
        normalized = normalize_vlm_image(
            output.getvalue(), "image/png", profile().normalization
        )
        with Image.open(io.BytesIO(normalized.image_bytes)) as reopened:
            self.assertEqual((255, 255, 255), reopened.getpixel((0, 0)))

    def test_normalized_output_byte_budget_is_enforced(self):
        restrictive = VlmNormalizationPolicy(
            max_bytes=1_000_000,
            max_width=512,
            max_height=512,
            max_pixels=262_144,
            max_normalized_bytes=10,
        )
        with self.assertRaisesRegex(VlmGatewayRequestError, "normalized image"):
            normalize_vlm_image(image_bytes(), "image/png", restrictive)

    def test_png_jpeg_and_webp_are_decoded_by_signature(self):
        cases = (
            ("PNG", "image/png"),
            ("JPEG", "image/jpeg"),
            ("WEBP", "image/webp"),
        )
        for image_format, mime_type in cases:
            with self.subTest(image_format=image_format):
                normalized = normalize_vlm_image(
                    image_bytes(image_format), mime_type, profile().normalization
                )
                self.assertEqual((32, 24), (normalized.width, normalized.height))
        with self.assertRaisesRegex(
            VlmGatewayRequestError, "MIME signature mismatch|container is malformed"
        ):
            normalize_vlm_image(
                image_bytes("PNG"), "image/jpeg", profile().normalization
            )

    def test_image_limits_and_unsupported_media_fail_before_inference(self):
        png = image_bytes(size=(32, 24))
        with self.assertRaisesRegex(VlmGatewayRequestError, "byte limit"):
            normalize_vlm_image(
                png,
                "image/png",
                VlmNormalizationPolicy(
                    max_bytes=8,
                    max_width=512,
                    max_height=512,
                    max_pixels=262_144,
                ),
            )
        with self.assertRaisesRegex(VlmGatewayRequestError, "dimension limit"):
            normalize_vlm_image(
                png,
                "image/png",
                VlmNormalizationPolicy(
                    max_bytes=1_000_000,
                    max_width=16,
                    max_height=512,
                    max_pixels=262_144,
                ),
            )
        with self.assertRaisesRegex(VlmGatewayRequestError, "unsupported"):
            normalize_vlm_image(png, "image/gif", profile().normalization)
        with self.assertRaisesRegex(VlmGatewayRequestError, "container is malformed"):
            normalize_vlm_image(png + b"hidden payload", "image/png", profile().normalization)
        with self.assertRaisesRegex(VlmGatewayRequestError, "aspect-ratio limit"):
            normalize_vlm_image(
                image_bytes(size=(64, 2)), "image/png", profile().normalization
            )

    def test_f12_decompression_bomb_and_f13_animated_webp_are_rejected(self):
        bomb = image_bytes(size=(100, 100))
        previous_limit = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = 1_000
            with self.assertRaisesRegex(VlmGatewayRequestError, "decode failed"):
                normalize_vlm_image(bomb, "image/png", profile().normalization)
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit

        first = Image.new("RGB", (16, 16), (200, 10, 10))
        second = Image.new("RGB", (16, 16), (10, 200, 10))
        output = io.BytesIO()
        try:
            first.save(
                output,
                format="WEBP",
                save_all=True,
                append_images=[second],
                duration=100,
                loop=0,
            )
        except OSError as exc:
            self.skipTest(f"Pillow WebP animation support unavailable: {exc}")
        with self.assertRaisesRegex(VlmGatewayRequestError, "multi-frame"):
            normalize_vlm_image(
                output.getvalue(), "image/webp", profile().normalization
            )

    def test_f12_truncated_and_jpeg_polyglot_variants_are_rejected(self):
        cases = (
            (image_bytes("PNG")[:-8], "image/png"),
            (image_bytes("JPEG")[:-2], "image/jpeg"),
            (image_bytes("WEBP")[:-4], "image/webp"),
            (image_bytes("JPEG") + b"hidden payload\xff\xd9", "image/jpeg"),
        )
        for raw, mime_type in cases:
            with self.subTest(mime_type=mime_type), self.assertRaises(
                VlmGatewayRequestError
            ):
                normalize_vlm_image(raw, mime_type, profile().normalization)

    def test_gateway_sends_fixed_model_bytes_only_and_strict_schema(self):
        captured = {}

        def transport(request, timeout_seconds, max_response_bytes):
            captured["url"] = request.full_url
            captured["timeout"] = timeout_seconds
            captured["limit"] = max_response_bytes
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return completion_bytes()

        approved = profile()
        gateway = LocalVlmGateway(
            VlmGatewaySettings(
                base_url="http://127.0.0.1:8000/v1",
                profile=approved,
            ),
            transport=transport,
        )
        result = gateway.run(
            image_bytes=image_bytes(),
            mime_type="image/png",
            expected_profile_digest=approved.profile_digest,
        )
        payload = captured["payload"]
        self.assertEqual("synthetic-vlm-model", payload["model"])
        self.assertTrue(payload["response_format"]["json_schema"]["strict"])
        self.assertEqual(
            EligibilityVlmDescriptor.model_json_schema(),
            payload["response_format"]["json_schema"]["schema"],
        )
        serialized = json.dumps(payload)
        self.assertIn("data:image/png;base64,", serialized)
        for forbidden in ("/Users/", "file://", "filename", "storage_key"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual("descriptor_valid", result.outcome.value)

    def test_profile_mismatch_blocks_transport(self):
        called = False

        def transport(request, timeout_seconds, max_response_bytes):
            nonlocal called
            called = True
            return completion_bytes()

        gateway = LocalVlmGateway(
            VlmGatewaySettings(base_url="http://127.0.0.1:8000", profile=profile()),
            transport=transport,
        )
        with self.assertRaisesRegex(VlmGatewayRequestError, "digest mismatch"):
            gateway.run(
                image_bytes=image_bytes(),
                mime_type="image/png",
                expected_profile_digest="wrong",
            )
        self.assertFalse(called)

    def test_invalid_or_oversized_response_is_sanitized(self):
        responses = (
            b"x" * 65_537,
            completion_bytes("x" * 16_385),
            completion_bytes("free text"),
            completion_bytes(
                json.dumps({**descriptor_payload(), "diagnosis": "synthetic"})
            ),
        )
        for response in responses:
            with self.subTest(response_length=len(response)):
                gateway = LocalVlmGateway(
                    VlmGatewaySettings(
                        base_url="http://127.0.0.1:8000", profile=profile()
                    ),
                    transport=lambda request, timeout, limit, value=response: value,
                )
                with self.assertRaises(VlmGatewayRuntimeError) as caught:
                    gateway.run(
                        image_bytes=image_bytes(),
                        mime_type="image/png",
                        expected_profile_digest=gateway.settings.profile.profile_digest,
                    )
                self.assertIn(
                    str(caught.exception),
                    {"Local VLM request failed", "Local VLM response is invalid"},
                )
                self.assertNotIn("diagnosis", str(caught.exception))

    def test_multiple_completion_choices_are_rejected(self):
        response = json.dumps(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(descriptor_payload()),
                        },
                    },
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(descriptor_payload()),
                        },
                    },
                ],
                "model": "synthetic-vlm-model",
            }
        ).encode("utf-8")
        approved = profile()
        gateway = LocalVlmGateway(
            VlmGatewaySettings(base_url="http://127.0.0.1:8000", profile=approved),
            transport=lambda request, timeout, limit: response,
        )
        with self.assertRaisesRegex(VlmGatewayRuntimeError, "response is invalid"):
            gateway.run(
                image_bytes=image_bytes(),
                mime_type="image/png",
                expected_profile_digest=approved.profile_digest,
            )

    def test_response_model_finish_state_and_actions_are_rejected(self):
        variants = []
        for mutation in (
            {"model": "unapproved-fallback"},
            {"finish_reason": "length"},
            {"tool_calls": [{"id": "synthetic"}]},
            {"refusal": "synthetic refusal"},
        ):
            payload = json.loads(completion_bytes().decode("utf-8"))
            if "model" in mutation:
                payload["model"] = mutation["model"]
            elif "finish_reason" in mutation:
                payload["choices"][0]["finish_reason"] = mutation["finish_reason"]
            else:
                payload["choices"][0]["message"].update(mutation)
            variants.append(json.dumps(payload).encode("utf-8"))
        for response in variants:
            approved = profile()
            gateway = LocalVlmGateway(
                VlmGatewaySettings(
                    base_url="http://127.0.0.1:8000", profile=approved
                ),
                transport=lambda request, timeout, limit, value=response: value,
            )
            with self.assertRaisesRegex(VlmGatewayRuntimeError, "response is invalid"):
                gateway.run(
                    image_bytes=image_bytes(),
                    mime_type="image/png",
                    expected_profile_digest=approved.profile_digest,
                )

    def test_deeply_nested_response_is_sanitized_and_counted_as_failure(self):
        deep = (
            b'{"model":"synthetic-vlm-model","choices":'
            + b"[" * 1_200
            + b"]" * 1_200
            + b"}"
        )
        approved = profile()
        gateway = LocalVlmGateway(
            VlmGatewaySettings(base_url="http://127.0.0.1:8000", profile=approved),
            transport=lambda request, timeout, limit: deep,
        )
        for _ in range(2):
            with self.assertRaisesRegex(VlmGatewayRuntimeError, "response is invalid"):
                gateway.run(
                    image_bytes=image_bytes(),
                    mime_type="image/png",
                    expected_profile_digest=approved.profile_digest,
                )
        with self.assertRaisesRegex(VlmGatewayRuntimeError, "temporarily unavailable"):
            gateway.run(
                image_bytes=image_bytes(),
                mime_type="image/png",
                expected_profile_digest=approved.profile_digest,
            )

    def test_circuit_breaker_opens_without_fallback_then_allows_one_probe(self):
        clock = MutableClock()
        breaker = VlmCircuitBreaker(profile().circuit_breaker, clock=clock)
        permit = breaker._before_call()
        breaker._record(permit, failed=True)
        permit = breaker._before_call()
        breaker._record(permit, failed=True)
        self.assertTrue(breaker.is_open)
        with self.assertRaisesRegex(VlmGatewayRuntimeError, "temporarily unavailable"):
            breaker._before_call()
        clock.value = 31
        permit = breaker._before_call()
        with self.assertRaises(VlmGatewayRuntimeError):
            breaker._before_call()
        breaker._record(permit, failed=False)
        self.assertFalse(breaker.is_open)
        breaker._before_call()

    def test_f25_half_open_concurrency_allows_exactly_one_probe(self):
        clock = MutableClock()
        breaker = VlmCircuitBreaker(profile().circuit_breaker, clock=clock)
        for _ in range(2):
            permit = breaker._before_call()
            breaker._record(permit, failed=True)
        clock.value = 31
        barrier = threading.Barrier(8)
        outcomes = []
        outcome_lock = threading.Lock()

        def attempt():
            barrier.wait()
            try:
                permit = breaker._before_call()
                outcome = "probe"
            except VlmGatewayRuntimeError:
                permit = None
                outcome = "blocked"
            with outcome_lock:
                outcomes.append((outcome, permit))

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(1, sum(outcome == "probe" for outcome, _ in outcomes))
        self.assertEqual(7, sum(outcome == "blocked" for outcome, _ in outcomes))
        probe_permit = None
        for outcome, permit in outcomes:
            if outcome == "probe":
                probe_permit = permit
        self.assertIsNotNone(probe_permit)
        breaker._record(probe_permit, failed=False)

    def test_stale_success_cannot_close_circuit_opened_by_concurrent_failure(self):
        breaker = VlmCircuitBreaker(profile().circuit_breaker)
        initial = breaker._before_call()
        breaker._record(initial, failed=True)
        slow_success = breaker._before_call()
        opening_failure = breaker._before_call()
        breaker._record(opening_failure, failed=True)
        self.assertTrue(breaker.is_open)
        breaker._record(slow_success, failed=False)
        self.assertTrue(breaker.is_open)

    def test_f25_gateway_runtime_failures_open_breaker_without_fallback(self):
        calls = 0

        def failing_transport(request, timeout, limit):
            nonlocal calls
            calls += 1
            raise TimeoutError("synthetic private detail")

        approved = profile()
        gateway = LocalVlmGateway(
            VlmGatewaySettings(base_url="http://127.0.0.1:8000", profile=approved),
            transport=failing_transport,
        )
        for _ in range(2):
            with self.assertRaisesRegex(VlmGatewayRuntimeError, "request failed"):
                gateway.run(
                    image_bytes=image_bytes(),
                    mime_type="image/png",
                    expected_profile_digest=approved.profile_digest,
                )
        with self.assertRaisesRegex(VlmGatewayRuntimeError, "temporarily unavailable"):
            gateway.run(
                image_bytes=image_bytes(),
                mime_type="image/png",
                expected_profile_digest=approved.profile_digest,
            )
        self.assertEqual(2, calls)

    def test_request_preparation_failure_releases_permit_and_is_sanitized(self):
        approved = profile()
        gateway = LocalVlmGateway(
            VlmGatewaySettings(base_url="http://127.0.0.1:8000", profile=approved),
            transport=lambda request, timeout, limit: completion_bytes(),
        )
        with mock.patch.object(
            vlm_gateway_module,
            "_request_payload",
            side_effect=RuntimeError("synthetic private detail"),
        ):
            for _ in range(2):
                with self.assertRaisesRegex(VlmGatewayRuntimeError, "request failed"):
                    gateway.run(
                        image_bytes=image_bytes(),
                        mime_type="image/png",
                        expected_profile_digest=approved.profile_digest,
                    )
            with self.assertRaisesRegex(
                VlmGatewayRuntimeError, "temporarily unavailable"
            ):
                gateway.run(
                    image_bytes=image_bytes(),
                    mime_type="image/png",
                    expected_profile_digest=approved.profile_digest,
                )

    def test_public_audit_contains_no_payload_path_or_full_content_hash(self):
        approved = profile()
        gateway = LocalVlmGateway(
            VlmGatewaySettings(base_url="http://127.0.0.1:8000", profile=approved),
            transport=lambda request, timeout, limit: completion_bytes(),
        )
        result = gateway.run(
            image_bytes=image_bytes(),
            mime_type="image/png",
            expected_profile_digest=approved.profile_digest,
        )
        audit = result.public_audit_dict()
        serialized = json.dumps(audit)
        self.assertNotIn(result.descriptor.model_dump_json(), serialized)
        for forbidden in (
            "image_bytes",
            "base64",
            "file_path",
            "filename",
            "storage_key",
            "content_hash",
            "/Users/",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertNotIn("source_token", audit)

    def test_f23_privacy_scanner_rejects_seeded_forbidden_payloads(self):
        seeded = (
            {"image_bytes": "AAAA"},
            {"normalized_bytes": "AAAA"},
            {"base64": "AAAA"},
            {"file_path": "/tmp/synthetic.png"},
            {"path": "/tmp/synthetic.png"},
            {"storage_key": "fixture/object"},
            {"filename": "synthetic.png"},
            {"note": "/Users/synthetic/source.png"},
            {"value": "file:///tmp/synthetic.png"},
            {"value": "data:image/png;base64,AAAA"},
            {"content_hash": "a" * 64},
            {"value": "b" * 64},
            {"subject_id": "SYNTHETIC-001"},
            {"raw_response": "synthetic response"},
            {"partial_response": "synthetic response"},
            {"exception_body": "synthetic response"},
            {"ocr_text": "synthetic text"},
            {"prompt": "synthetic prompt"},
            {"value": "MRN: SYNTHETIC-001"},
        )
        for payload in seeded:
            with self.subTest(payload=payload), self.assertRaises(
                VlmPrivacyViolationError
            ):
                assert_vlm_public_payload_safe(payload)
        for payload in ({"imageBytes": "AAAA"}, {"filePath": "/tmp/a"}):
            with self.assertRaises(VlmPrivacyViolationError):
                assert_vlm_public_payload_safe(payload)
        assert_vlm_public_payload_safe({"profile_digest": "c" * 64})

    def test_gateway_does_not_create_files(self):
        approved = profile()
        gateway = LocalVlmGateway(
            VlmGatewaySettings(base_url="http://127.0.0.1:8000", profile=approved),
            transport=lambda request, timeout, limit: completion_bytes(),
        )
        with tempfile.TemporaryDirectory() as directory:
            before = set(Path(directory).iterdir())
            gateway.run(
                image_bytes=image_bytes(),
                mime_type="image/png",
                expected_profile_digest=approved.profile_digest,
            )
            self.assertEqual(before, set(Path(directory).iterdir()))


if __name__ == "__main__":
    unittest.main()
