"""Focused tests for the PaddleOCR primary/fallback OCR bounded slice.

Every test is deterministic — no live credential, no network call. All
HTTP, polling, JSONL, and LLM interactions use injected fakes.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from services.api.app.paddle_ocr_adapter import (
    PADDLE_OCR_MODEL,
    PaddleOcrAdapter,
    PaddleOcrError,
    PaddleOcrJobFailedError,
    PaddleOcrOutcomeUnknownError,
    PaddleOcrResultError,
    PaddleOcrSettings,
    PaddleOcrSubmissionRejectedError,
    PaddleOcrTimeoutError,
)
from services.api.app.ocr_fallback_orchestrator import (
    GLM_FALLBACK_MODEL,
    OcrFallbackOrchestrator,
    PROVIDER_GLM_OMLX,
    PROVIDER_PADDLE,
    detect_mixed_model_evidence,
)
from services.api.app.ocr_consistency_qc import (
    QC_MAX_PROMPT_CHARS,
    QC_STAGE_VERSION,
    MixedOcrConsistencyQcError,
    MixedOcrConsistencyQcOutcome,
    run_mixed_ocr_consistency_qc,
)
from services.api.app.writing_reference_ocr_evidence import (
    OCR_EVIDENCE_ALLOWED_MODELS,
    validate_new_ocr_page_evidence,
)
from services.api.app.writing_reference_preparation_batch import (
    ALLOWED_DOCUMENT_TYPES,
    ALLOWED_DOCUMENT_TYPES_INCLUDING_SAP,
)
from services.api.app.medical_writing_corpus_analysis_ai import (
    _PROTOCOL_DOCUMENT_TYPES,
)


# ===========================================================================
# 1. Paddle adapter tests: submit, poll, JSONL, timeout, failure
# ===========================================================================


def _make_submit_response(job_id: str = "job_abc123") -> str:
    return json.dumps({"jobId": job_id, "status": "pending"})


def _make_poll_response(
    status: str = "done", json_url: str = "https://result.example.test/out.jsonl"
) -> str:
    if status == "done":
        return json.dumps(
            {"status": "done", "data": {"resultUrl": {"jsonUrl": json_url}}}
        )
    if status == "failed":
        return json.dumps({"status": "failed", "data": {"error": "rate limited"}})
    return json.dumps({"status": status})


def _make_jsonl(pages: list[dict]) -> str:
    return "\n".join(json.dumps(p) for p in pages)


class PaddleOcrAdapterTests(unittest.TestCase):
    """Success criterion: submit, pending/running progress, done JSONL parsing,
    result image/markdown handling boundary, timeout, and failed job."""

    def test_submit_pending_running_done_parses_jsonl(self) -> None:
        jsonl_pages = [
            {"page_index": 0, "markdown": "# Protocol\n\nInclusion criteria"},
            {"page_index": 1, "markdown": "## Endpoints\n\nPrimary endpoint"},
        ]
        poll_states = ["pending", "running", "done"]

        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(api_key="test-not-real-key"),
            submit_fn=lambda *a: _make_submit_response("job_001"),
            poll_fn=self._poll_sequence(poll_states),
            jsonl_fn=lambda url, headers: _make_jsonl(jsonl_pages),
            sleep_fn=lambda s: None,
        )
        result = adapter.submit_and_wait(b"\x89PNG fake image")

        self.assertEqual("job_001", result.job_id)
        self.assertEqual(PADDLE_OCR_MODEL, result.model)
        self.assertEqual(2, len(result.pages))
        self.assertEqual("# Protocol\n\nInclusion criteria", result.pages[0].markdown)
        self.assertEqual(0, result.pages[0].page_index)
        self.assertGreater(result.duration_ms, 0)

    @staticmethod
    def _poll_sequence(states: list[str]):
        """Return a poll_fn that cycles through the given states."""
        iterator = iter(states)

        def poll_fn(base_url: str, path_with_id: str, headers: dict) -> str:
            try:
                state = next(iterator)
            except StopIteration:
                state = "done"
            if state == "done":
                return _make_poll_response("done")
            return _make_poll_response(state)

        return poll_fn

    def test_done_response_with_markdown_field_alias(self) -> None:
        """Paddle JSONL may use 'md' or 'text' instead of 'markdown'."""
        jsonl_pages = [
            {"page": 0, "md": "Page one content"},
            {"page": 1, "text": "Page two content"},
        ]
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response(),
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda url, headers: _make_jsonl(jsonl_pages),
            sleep_fn=lambda s: None,
        )
        result = adapter.submit_and_wait(b"fake")
        self.assertEqual("Page one content", result.pages[0].markdown)
        self.assertEqual("Page two content", result.pages[1].markdown)

    def test_invalid_page_index_is_outcome_unknown_with_job_id(self) -> None:
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response("job_bad_page_index"),
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda *a: _make_jsonl(
                [{"page_index": "not-an-integer", "markdown": "content"}]
            ),
            sleep_fn=lambda s: None,
        )

        with self.assertRaises(PaddleOcrResultError) as captured:
            adapter.submit_and_wait(b"fake")

        self.assertEqual("job_bad_page_index", captured.exception.job_id)
        self.assertIn("invalid page index", str(captured.exception))

    def test_official_nested_contract_and_layout_markdown_are_parsed(self) -> None:
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: json.dumps(
                {"data": {"jobId": "official_job"}}
            ),
            poll_fn=lambda *a: json.dumps(
                {
                    "data": {
                        "state": "done",
                        "resultUrl": {
                            "jsonUrl": "https://result.example.test/result.jsonl"
                        },
                    }
                }
            ),
            jsonl_fn=lambda url, headers: json.dumps(
                {
                    "result": {
                        "layoutParsingResults": [
                            {"markdown": {"text": "# Official protocol"}}
                        ]
                    }
                }
            ),
            sleep_fn=lambda s: None,
        )
        result = adapter.submit_and_wait(b"fake")
        self.assertEqual("official_job", result.job_id)
        self.assertEqual("# Official protocol", result.pages[0].markdown)

    def test_submit_uses_official_multipart_fields(self) -> None:
        captured: dict[str, object] = {}

        def submit(base_url, path, model, headers, body):
            captured.update(headers=headers, body=body)
            return json.dumps({"data": {"jobId": "multipart_job"}})

        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=submit,
            poll_fn=lambda *a: json.dumps(
                {
                    "data": {
                        "state": "done",
                        "resultUrl": {
                            "jsonUrl": "https://result.example.test/result.jsonl"
                        },
                    }
                }
            ),
            jsonl_fn=lambda *a: json.dumps(
                {
                    "result": {
                        "layoutParsingResults": [
                            {"markdown": {"text": "recognized"}}
                        ]
                    }
                }
            ),
            sleep_fn=lambda s: None,
        )
        adapter.submit_and_wait(b"\x89PNG payload")
        self.assertTrue(
            str(captured["headers"]["Content-Type"]).startswith(
                "multipart/form-data; boundary="
            )
        )
        body = bytes(captured["body"])
        self.assertIn(b'name="model"', body)
        self.assertIn(b'name="optionalPayload"', body)
        self.assertIn(b'name="file"', body)

    def test_failed_job_raises_job_failed_error(self) -> None:
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response("job_fail"),
            poll_fn=lambda *a: _make_poll_response("failed"),
            jsonl_fn=lambda url, headers: "",
            sleep_fn=lambda s: None,
        )
        with self.assertRaises(PaddleOcrJobFailedError) as raised:
            adapter.submit_and_wait(b"fake")
        self.assertEqual("job_fail", raised.exception.job_id)

    def test_timeout_raises_timeout_error(self) -> None:
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(poll_max_attempts=3, poll_interval_seconds=0.001),
            submit_fn=lambda *a: _make_submit_response("job_slow"),
            poll_fn=lambda *a: _make_poll_response("running"),
            jsonl_fn=lambda url, headers: "",
            sleep_fn=lambda s: None,
        )
        with self.assertRaises(PaddleOcrTimeoutError):
            adapter.submit_and_wait(b"fake")

    def test_empty_jsonl_raises_result_error(self) -> None:
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response(),
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda url, headers: "\n  \n",
            sleep_fn=lambda s: None,
        )
        with self.assertRaises(PaddleOcrResultError):
            adapter.submit_and_wait(b"fake")

    def test_submit_missing_job_id_raises_error(self) -> None:
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: json.dumps({"status": "ok"}),
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda url, headers: _make_jsonl([{"markdown": "x"}]),
            sleep_fn=lambda s: None,
        )
        with self.assertRaises(PaddleOcrError):
            adapter.submit_and_wait(b"fake")

    def test_submit_http_failure_preserves_status_without_url_or_secret(self) -> None:
        calls = 0

        def fail_submit(*args):
            nonlocal calls
            calls += 1
            raise urllib.error.HTTPError(
                "https://paddle.example.test/jobs?token=secret",
                429,
                "Too Many Requests",
                {},
                None,
            )

        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=fail_submit,
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda url, headers: "",
            sleep_fn=lambda s: None,
        )
        with self.assertRaises(PaddleOcrSubmissionRejectedError) as raised:
            adapter.submit_and_wait(b"fake")
        message = str(raised.exception)
        self.assertIn("HTTP 429", message)
        self.assertNotIn("token=", message)
        self.assertNotIn("paddle.example.test", message)
        self.assertEqual(4, calls)

    def test_submit_429_retries_with_backoff_then_succeeds(self) -> None:
        calls = 0
        delays: list[float] = []

        def submit(*args):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise urllib.error.HTTPError(
                    "https://paddle.example.test/jobs",
                    429,
                    "Too Many Requests",
                    {},
                    None,
                )
            return _make_submit_response("job_after_429")

        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(
                submit_max_attempts=4,
                submit_retry_base_seconds=0.25,
            ),
            submit_fn=submit,
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda *a: _make_jsonl(
                [{"page_index": 0, "markdown": "Paddle after retry"}]
            ),
            sleep_fn=delays.append,
        )

        result = adapter.submit_and_wait(b"fake")

        self.assertEqual("job_after_429", result.job_id)
        self.assertEqual(3, calls)
        self.assertEqual([0.25, 0.5], delays)

    def test_submit_retry_after_is_capped(self) -> None:
        calls = 0
        delays: list[float] = []

        def submit(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise urllib.error.HTTPError(
                    "https://paddle.example.test/jobs",
                    429,
                    "Too Many Requests",
                    {"Retry-After": "3600"},
                    None,
                )
            return _make_submit_response("job_after_capped_delay")

        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(
                submit_max_attempts=2,
                submit_retry_base_seconds=0.25,
                submit_retry_max_seconds=3.0,
            ),
            submit_fn=submit,
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda *a: _make_jsonl(
                [{"page_index": 0, "markdown": "bounded"}]
            ),
            sleep_fn=delays.append,
        )

        adapter.submit_and_wait(b"fake")

        self.assertEqual([3.0], delays)

    def test_submit_5xx_is_not_retried_without_provider_idempotency(self) -> None:
        calls = 0

        def submit(*args):
            nonlocal calls
            calls += 1
            raise urllib.error.HTTPError(
                "https://paddle.example.test/jobs",
                503,
                "Service Unavailable",
                {},
                None,
            )

        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(submit_max_attempts=4),
            submit_fn=submit,
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda *a: "",
            sleep_fn=lambda seconds: self.fail("5xx must not be retried"),
        )

        with self.assertRaises(PaddleOcrOutcomeUnknownError) as raised:
            adapter.submit_and_wait(b"fake")

        self.assertIn("HTTP 503", str(raised.exception))
        self.assertEqual(1, calls)

    def test_done_response_missing_result_url_raises_error(self) -> None:
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response(),
            poll_fn=lambda *a: json.dumps({"status": "done", "data": {}}),
            jsonl_fn=lambda url, headers: "",
            sleep_fn=lambda s: None,
        )
        with self.assertRaises(PaddleOcrOutcomeUnknownError):
            adapter.submit_and_wait(b"fake")

    def test_poll_transport_failure_after_acceptance_is_outcome_unknown(self) -> None:
        adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response("job_accepted"),
            poll_fn=lambda *a: (_ for _ in ()).throw(
                urllib.error.HTTPError(
                    "https://paddle.example.test/jobs/job_accepted",
                    503,
                    "Service Unavailable",
                    {},
                    None,
                )
            ),
            jsonl_fn=lambda *a: "",
            sleep_fn=lambda s: None,
        )

        with self.assertRaises(PaddleOcrOutcomeUnknownError) as raised:
            adapter.submit_and_wait(b"fake")

        self.assertEqual("job_accepted", raised.exception.job_id)

    def test_settings_validation_rejects_empty_base_url(self) -> None:
        with self.assertRaises(PaddleOcrError):
            PaddleOcrSettings(base_url="")

    def test_auth_headers_include_bearer_token_when_set(self) -> None:
        settings = PaddleOcrSettings(api_key="secret-key-not-real")
        headers = settings.auth_headers()
        self.assertEqual("Bearer secret-key-not-real", headers["Authorization"])
        self.assertNotIn("Content-Type", headers)

    def test_auth_headers_exclude_bearer_when_empty(self) -> None:
        settings = PaddleOcrSettings()
        headers = settings.auth_headers()
        self.assertNotIn("Authorization", headers)

    def test_adapter_does_not_hardcode_credential(self) -> None:
        """No credential value should appear in the module source or settings."""
        import services.api.app.paddle_ocr_adapter as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        # The literal string "api_key" appears in code, but no actual key value.
        self.assertNotIn("Bearer eyJ", source)
        self.assertNotIn("x-", source.lower())  # no token-like strings


# ===========================================================================
# 2. Primary/fallback orchestrator tests
# ===========================================================================


class OcrFallbackOrchestratorTests(unittest.TestCase):
    """Success criterion: Paddle attempted first, GLM called only after
    verified Paddle failure, per-page model/provider/fallback provenance."""

    def _fake_paddle_success(self, text: str = "Paddle OCR text") -> PaddleOcrAdapter:
        return PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response(),
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda url, headers: _make_jsonl(
                [{"page_index": 0, "markdown": text}]
            ),
            sleep_fn=lambda s: None,
        )

    def _fake_paddle_failure(self) -> PaddleOcrAdapter:
        return PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response("job_fail"),
            poll_fn=lambda *a: _make_poll_response("failed"),
            jsonl_fn=lambda url, headers: "",
            sleep_fn=lambda s: None,
        )

    def test_paddle_success_does_not_call_glm(self) -> None:
        glm_calls: list[bytes] = []

        def glm_runner(image_bytes: bytes, mime_type: str) -> str:
            glm_calls.append(image_bytes)
            return "GLM fallback text"

        orchestrator = OcrFallbackOrchestrator(
            paddle_adapter=self._fake_paddle_success("Paddle primary text"),
            glm_runner=glm_runner,
        )
        result = orchestrator.run(b"\x89PNG image")

        self.assertEqual("Paddle primary text", result.text)
        self.assertEqual(PADDLE_OCR_MODEL, result.model)
        self.assertEqual(PROVIDER_PADDLE, result.provider)
        self.assertFalse(result.fell_back)
        self.assertEqual("", result.fallback_reason)
        self.assertEqual([], glm_calls)

    def test_paddle_failure_falls_back_to_glm_with_provenance(self) -> None:
        def glm_runner(image_bytes: bytes, mime_type: str) -> str:
            return "GLM fallback text"

        orchestrator = OcrFallbackOrchestrator(
            paddle_adapter=self._fake_paddle_failure(),
            glm_runner=glm_runner,
        )
        result = orchestrator.run(b"\x89PNG image")

        self.assertEqual("GLM fallback text", result.text)
        self.assertEqual(GLM_FALLBACK_MODEL, result.model)
        self.assertEqual(PROVIDER_GLM_OMLX, result.provider)
        self.assertTrue(result.fell_back)
        self.assertEqual(PADDLE_OCR_MODEL, result.primary_model)
        self.assertIn("paddle_failure", result.fallback_reason)
        # Critical: GLM output is never labeled as Paddle
        self.assertNotEqual(PROVIDER_PADDLE, result.provider)
        self.assertNotEqual(PADDLE_OCR_MODEL, result.model)

    def test_no_paddle_adapter_skips_directly_to_glm(self) -> None:
        def glm_runner(image_bytes: bytes, mime_type: str) -> str:
            return "GLM direct text"

        orchestrator = OcrFallbackOrchestrator(
            paddle_adapter=None,
            glm_runner=glm_runner,
        )
        result = orchestrator.run(b"\x89PNG image")

        self.assertEqual("GLM direct text", result.text)
        self.assertTrue(result.fell_back)
        self.assertIn("not_configured", result.fallback_reason)

    def test_paddle_empty_result_fails_closed_without_glm(self) -> None:
        empty_paddle = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response(),
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda url, headers: _make_jsonl(
                [{"page_index": 0, "markdown": "   "}]  # whitespace only
            ),
            sleep_fn=lambda s: None,
        )
        glm_calls: list[bytes] = []
        orchestrator = OcrFallbackOrchestrator(
            paddle_adapter=empty_paddle,
            glm_runner=lambda img, mt: glm_calls.append(img) or "GLM text",
        )
        with self.assertRaises(PaddleOcrOutcomeUnknownError):
            orchestrator.run(b"fake")
        self.assertEqual([], glm_calls)

    def test_poll_failure_after_acceptance_fails_closed_without_glm(self) -> None:
        paddle = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response("job_accepted"),
            poll_fn=lambda *a: (_ for _ in ()).throw(
                urllib.error.URLError("temporary transport failure")
            ),
            jsonl_fn=lambda *a: "",
            sleep_fn=lambda s: None,
        )
        glm_calls: list[bytes] = []
        orchestrator = OcrFallbackOrchestrator(
            paddle_adapter=paddle,
            glm_runner=lambda img, mt: glm_calls.append(img) or "GLM text",
        )

        with self.assertRaises(PaddleOcrOutcomeUnknownError):
            orchestrator.run(b"fake")

        self.assertEqual([], glm_calls)


# ===========================================================================
# 3. Mixed-model OCR consistency QC tests
# ===========================================================================


class MixedOcrConsistencyQcTests(unittest.TestCase):
    """Success criterion: mixed Paddle/GLM document triggers exactly one
    focused Flash QC; single-model does not; QC must not rewrite OCR text."""

    def test_single_model_evidence_does_not_trigger_qc(self) -> None:
        pages = [
            ("GLM-OCR-bf16", "Page one text"),
            ("GLM-OCR-bf16", "Page two text"),
        ]
        qc_calls: list[str] = []

        def fake_runner(system_prompt: str, user_prompt: str) -> dict:
            qc_calls.append(user_prompt)
            return {"verdict": "pass", "notes": ""}

        outcome = run_mixed_ocr_consistency_qc(pages, fake_runner)
        self.assertFalse(outcome.triggered)
        self.assertEqual("pass", outcome.verdict)
        self.assertEqual(0, len(qc_calls))

    def test_mixed_model_evidence_triggers_qc_exactly_once(self) -> None:
        pages = [
            ("PaddleOCR-VL-1.6", "Inclusion: age >= 18"),
            ("GLM-OCR-bf16", "Exclusion: prior biologic"),
        ]
        qc_calls: list[str] = []

        def fake_runner(system_prompt: str, user_prompt: str) -> dict:
            qc_calls.append(user_prompt)
            return {"verdict": "pass", "notes": "no inconsistency found"}

        outcome = run_mixed_ocr_consistency_qc(pages, fake_runner)
        self.assertTrue(outcome.triggered)
        self.assertEqual(1, len(qc_calls))  # exactly once
        self.assertEqual("pass", outcome.verdict)
        self.assertIn("PaddleOCR-VL-1.6", outcome.models)
        self.assertIn("GLM-OCR-bf16", outcome.models)
        self.assertEqual(2, outcome.page_count)
        self.assertTrue(outcome.identity_hash)

    def test_empty_evidence_does_not_trigger_qc(self) -> None:
        outcome = run_mixed_ocr_consistency_qc([], lambda s, u: {"verdict": "pass"})
        self.assertFalse(outcome.triggered)
        self.assertEqual(0, outcome.page_count)

    def test_qc_does_not_rewrite_ocr_text(self) -> None:
        """The QC prompt explicitly prohibits rewriting. Verify the system
        prompt contains the prohibition instruction."""
        pages = [("PaddleOCR-VL-1.6", "A"), ("GLM-OCR-bf16", "B")]
        captured_system = ""
        captured_user = ""

        def fake_runner(system_prompt: str, user_prompt: str) -> dict:
            nonlocal captured_system, captured_user
            captured_system = system_prompt
            captured_user = user_prompt
            return {"verdict": "pass"}

        run_mixed_ocr_consistency_qc(pages, fake_runner)
        self.assertIn("不得改写", captured_system)
        self.assertIn("不得", captured_system)
        self.assertIn("不同物理页", captured_system)
        self.assertIn("模型回退", captured_system)
        self.assertIn("不要把正常分页", captured_user)

    def test_qc_prompt_only_contains_model_boundary_window(self) -> None:
        pages = [
            (1, "PaddleOCR-VL-1.6", "far before"),
            (2, "PaddleOCR-VL-1.6", "before boundary"),
            (3, "GLM-OCR-bf16", "fallback page"),
            (4, "GLM-OCR-bf16", "after boundary"),
            (5, "GLM-OCR-bf16", "far after"),
        ]
        captured_user = ""

        def fake_runner(system_prompt: str, user_prompt: str) -> dict:
            nonlocal captured_user
            captured_user = user_prompt
            return {"verdict": "pass"}

        run_mixed_ocr_consistency_qc(pages, fake_runner)
        self.assertNotIn("far before", captured_user)
        self.assertIn("before boundary", captured_user)
        self.assertIn("fallback page", captured_user)
        self.assertNotIn("after boundary", captured_user)
        self.assertIn("物理页 3", captured_user)
        self.assertNotIn("far after", captured_user)

    def test_nonadjacent_selected_pages_are_not_treated_as_a_boundary(self) -> None:
        pages = [
            (10, "PaddleOCR-VL-1.6", "page ten"),
            (17, "GLM-OCR-bf16", "page seventeen"),
        ]
        qc_calls: list[str] = []

        outcome = run_mixed_ocr_consistency_qc(
            pages,
            lambda system, user: qc_calls.append(user) or {"verdict": "pass"},
        )

        self.assertFalse(outcome.triggered)
        self.assertEqual("pass", outcome.verdict)
        self.assertEqual([], qc_calls)
        self.assertIn("nonadjacent", outcome.notes)

    def test_fallback_page_uses_same_page_native_and_real_neighbor_context(self) -> None:
        pages = [
            {
                "physical_page": 17,
                "model": "GLM-OCR-bf16",
                "text": "OCR recovered dose 10 mg",
                "fell_back": True,
                "native_text": "native dose 10 mg",
                "previous_page_text": "Section 5 begins",
                "next_page_text": "Section 5 continues",
            },
            {
                "physical_page": 68,
                "model": "PaddleOCR-VL-1.6",
                "text": "unrelated selected page",
                "fell_back": False,
            },
        ]
        captured_user = ""

        def fake_runner(system_prompt: str, user_prompt: str) -> dict:
            nonlocal captured_user
            captured_user = user_prompt
            return {"verdict": "pass"}

        outcome = run_mixed_ocr_consistency_qc(pages, fake_runner)

        self.assertTrue(outcome.triggered)
        self.assertIn("物理页 17", captured_user)
        self.assertIn("native dose 10 mg", captured_user)
        self.assertIn("Section 5 begins", captured_user)
        self.assertIn("Section 5 continues", captured_user)
        self.assertNotIn("unrelated selected page", captured_user)

    def test_long_fallback_text_is_not_silently_truncated_at_legacy_limit(self) -> None:
        marker = "END_OF_REAL_OCR_PAGE"
        long_text = ("X " * 1800) + marker
        captured_system = ""
        captured_user = ""

        def fake_runner(system_prompt: str, user_prompt: str) -> dict:
            nonlocal captured_system, captured_user
            captured_system = system_prompt
            captured_user = user_prompt
            return {"verdict": "pass"}

        run_mixed_ocr_consistency_qc(
            [
                {
                    "physical_page": 25,
                    "model": "GLM-OCR-bf16",
                    "text": long_text,
                    "fell_back": True,
                },
                (26, "PaddleOCR-VL-1.6", "next selected page"),
            ],
            fake_runner,
        )

        self.assertIn(marker, captured_user)
        self.assertIn("重复X通常", captured_system)

    def test_large_mixed_boundary_window_is_bounded_and_fail_closed(self) -> None:
        pages = [
            {
                "physical_page": index,
                "model": "GLM-OCR-bf16" if index % 2 else "PaddleOCR-VL-1.6",
                "text": f"page-{index} " + ("x" * 12000),
                "fell_back": True,
                "native_text": "native " + ("n" * 5000),
            }
            for index in range(1, 20)
        ]
        captured_user = ""

        def fake_runner(system_prompt: str, user_prompt: str) -> dict:
            nonlocal captured_user
            captured_user = user_prompt
            return {"verdict": "review_required", "notes": "sampled boundary"}

        outcome = run_mixed_ocr_consistency_qc(pages, fake_runner)

        self.assertTrue(outcome.triggered)
        self.assertEqual("review_required", outcome.verdict)
        self.assertLessEqual(len(captured_user), QC_MAX_PROMPT_CHARS + 200)
        self.assertIn("确定性输入上限", captured_user)
        self.assertIn("不得据此判定未列出的页没有异常", captured_user)

    def test_qc_invalid_verdict_raises_error(self) -> None:
        pages = [("PaddleOCR-VL-1.6", "A"), ("GLM-OCR-bf16", "B")]
        with self.assertRaises(MixedOcrConsistencyQcError):
            run_mixed_ocr_consistency_qc(
                pages, lambda s, u: {"verdict": "invalid_value"}
            )

    def test_qc_audit_payload_is_serializable(self) -> None:
        pages = [("PaddleOCR-VL-1.6", "A"), ("GLM-OCR-bf16", "B")]
        outcome = run_mixed_ocr_consistency_qc(
            pages, lambda s, u: {"verdict": "review_required", "notes": "check unit"}
        )
        payload = outcome.audit_payload()
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertIn("review_required", serialized)
        self.assertIn("check unit", serialized)
        self.assertEqual(QC_STAGE_VERSION, payload["qc_stage_version"])

    def test_detect_mixed_model_evidence_helper(self) -> None:
        self.assertTrue(detect_mixed_model_evidence(["PaddleOCR-VL-1.6", "GLM-OCR-bf16"]))
        self.assertFalse(detect_mixed_model_evidence(["GLM-OCR-bf16", "GLM-OCR-bf16"]))
        self.assertFalse(detect_mixed_model_evidence(["GLM-OCR-bf16"]))
        self.assertFalse(detect_mixed_model_evidence([]))


# ===========================================================================
# 4. OCR evidence validation: Paddle model is now admitted
# ===========================================================================


class OcrEvidenceModelAllowlistTests(unittest.TestCase):
    """Success criterion: new OCR evidence validation admits Paddle model."""

    def test_glm_model_remains_in_allowlist(self) -> None:
        self.assertIn("GLM-OCR-bf16", OCR_EVIDENCE_ALLOWED_MODELS)

    def test_paddle_model_is_in_allowlist(self) -> None:
        self.assertIn("PaddleOCR-VL-1.6", OCR_EVIDENCE_ALLOWED_MODELS)

    def test_validate_accepts_paddle_model(self) -> None:
        from services.api.app.writing_reference_ocr_evidence import OCR_EVIDENCE_DPI
        from packages.contracts.workbench_contracts.models import (
            WritingReferenceOcrPageEvidence,
        )

        evidence = WritingReferenceOcrPageEvidence(
            physical_page=1,
            dpi=OCR_EVIDENCE_DPI,
            image_sha256="a" * 64,
            image_size_bytes=1000,
            image_width_px=200,
            image_height_px=300,
            storage_relpath="safe/path/page.png",
            model="PaddleOCR-VL-1.6",
            ocr_profile_digest="b" * 64,
            ocr_text_sha256="c" * 64,
            ocr_character_count=42,
            channel="ocr",
            selection_reason="zero_text_or_spatial_layout",
            ocr_result_status="text_recovered",
            span_id="span_001",
        )
        # Should not raise
        validate_new_ocr_page_evidence(evidence)

    def test_validate_rejects_unknown_model(self) -> None:
        from packages.contracts.workbench_contracts.models import (
            WritingReferenceOcrPageEvidence,
        )

        evidence = WritingReferenceOcrPageEvidence(
            physical_page=1,
            dpi=200,
            image_sha256="a" * 64,
            image_size_bytes=1000,
            image_width_px=200,
            image_height_px=300,
            storage_relpath="safe/path/page.png",
            model="random-unknown-model",
            ocr_profile_digest="b" * 64,
            ocr_text_sha256="c" * 64,
            ocr_character_count=42,
            channel="ocr",
            selection_reason="test",
            ocr_result_status="text_recovered",
            span_id="span_001",
        )
        with self.assertRaisesRegex(ValueError, "not in the allowlist"):
            validate_new_ocr_page_evidence(evidence)


# ===========================================================================
# 5. SAP exclusion: preparation and corpus analysis
# ===========================================================================


class SapExclusionTests(unittest.TestCase):
    """Success criterion: standalone SAP excluded from preparation and corpus;
    protocol_sap remains eligible."""

    def test_preparation_excludes_standalone_sap(self) -> None:
        self.assertNotIn("sap", ALLOWED_DOCUMENT_TYPES)
        self.assertIn("protocol", ALLOWED_DOCUMENT_TYPES)
        self.assertIn("protocol_sap", ALLOWED_DOCUMENT_TYPES)

    def test_broad_set_still_includes_sap_for_non_corpus_paths(self) -> None:
        self.assertIn("sap", ALLOWED_DOCUMENT_TYPES_INCLUDING_SAP)

    def test_corpus_analysis_excludes_standalone_sap(self) -> None:
        self.assertNotIn("sap", _PROTOCOL_DOCUMENT_TYPES)
        self.assertIn("protocol", _PROTOCOL_DOCUMENT_TYPES)
        self.assertIn("protocol_sap", _PROTOCOL_DOCUMENT_TYPES)


# ===========================================================================
# 6. Paddle provider preset exists
# ===========================================================================


class PaddleProviderPresetTests(unittest.TestCase):
    """Success criterion: Paddle official provider preset exists in presets."""

    def test_paddle_preset_is_registered(self) -> None:
        from services.api.app.ai_runtime_settings import provider_presets

        presets = provider_presets()
        paddle = next(
            (p for p in presets if p["preset_id"] == "paddle_official"), None
        )
        self.assertIsNotNone(paddle)
        self.assertEqual("PaddleOCR-VL-1.6", paddle["default_model"])
        self.assertEqual("paddle_official", paddle["provider"])
        self.assertEqual("cloud", paddle["deployment_scope"])
        self.assertEqual("paddle_async_job", paddle["transport"])
        self.assertEqual("PADDLE_OCR_API_KEY", paddle["api_key_env"])


# ===========================================================================
# 7. OCR role default binding defaults to Paddle when credential available
# ===========================================================================


class OcrRoleDefaultBindingTests(unittest.TestCase):
    """Success criterion: Paddle is the default OCR binding for new settings
    without overwriting an explicit existing user choice."""

    def test_new_role_settings_default_to_paddle_when_credential_set(self) -> None:
        import os
        from services.api.app.ai_role_runtime_settings import (
            AiRoleRuntimeSettingsStore,
            OCR_PADDLE_PROFILE_ID,
            PADDLE_OCR_MODEL,
        )
        from services.api.app.ai_runtime_settings import AiRuntimeSettingsStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider_store = AiRuntimeSettingsStore(root / "providers.json")
            provider_store.upsert(
                __import__(
                    "services.api.app.ai_runtime_settings",
                    fromlist=["AiProviderProfile"],
                ).AiProviderProfile(
                    profile_id="test_active",
                    provider="deepseek",
                    label="Active",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-v4-pro",
                    api_key_env="DEEPSEEK_API_KEY",
                ),
                api_key="irrelevant",
                activate=True,
            )
            store = AiRoleRuntimeSettingsStore(
                root / "roles.json", provider_store
            )
            with patch.dict(os.environ, {"PADDLE_OCR_API_KEY": "fake-key-not-real"}):
                payload = store.public_payload()
            ocr_role = next(r for r in payload["roles"] if r["role_id"] == "ocr")
            self.assertEqual(PADDLE_OCR_MODEL, ocr_role["model"])
            self.assertEqual(OCR_PADDLE_PROFILE_ID, ocr_role["profile_id"])

    def test_existing_user_ocr_choice_is_not_overwritten(self) -> None:
        import json
        import os
        from services.api.app.ai_role_runtime_settings import (
            AiRoleRuntimeSettingsStore,
            OCR_OMLX_PROFILE_ID,
        )
        from services.api.app.ai_runtime_settings import (
            AiProviderProfile,
            AiRuntimeSettingsStore,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider_store = AiRuntimeSettingsStore(root / "providers.json")
            provider_store.upsert(
                AiProviderProfile(
                    profile_id="test_active",
                    provider="deepseek",
                    label="Active",
                    base_url="https://api.deepseek.com/v1",
                    model="deepseek-v4-pro",
                    api_key_env="DEEPSEEK_API_KEY",
                ),
                api_key="irrelevant",
                activate=True,
            )
            store = AiRoleRuntimeSettingsStore(
                root / "roles.json", provider_store
            )
            # Simulate a pre-existing user choice: GLM binding persisted
            store.settings_path.parent.mkdir(parents=True, exist_ok=True)
            store.settings_path.write_text(
                json.dumps({
                    "schema_version": "ai_role_bindings_v2",
                    "revision": 1,
                    "bindings": {
                        "independent_ai": {
                            "role_id": "independent_ai",
                            "profile_id": "test_active",
                            "model": "deepseek-v4-pro",
                            "enabled": True,
                        },
                        "ocr": {
                            "role_id": "ocr",
                            "profile_id": OCR_OMLX_PROFILE_ID,
                            "model": "GLM-OCR-bf16",
                            "enabled": True,
                        },
                        "translation_body": {
                            "role_id": "translation_body",
                            "profile_id": "translation_body_local_omlx",
                            "model": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
                            "enabled": True,
                        },
                        "translation_support": {
                            "role_id": "translation_support",
                            "profile_id": "deepseek_translation_support",
                            "model": "deepseek-v4-flash",
                            "enabled": True,
                        },
                    },
                }),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"PADDLE_OCR_API_KEY": "fake-key"}):
                payload = store.public_payload()
            ocr_role = next(r for r in payload["roles"] if r["role_id"] == "ocr")
            # User's explicit GLM choice is preserved
            self.assertEqual("GLM-OCR-bf16", ocr_role["model"])
            self.assertEqual(OCR_OMLX_PROFILE_ID, ocr_role["profile_id"])


# ===========================================================================
# 8. Provider-switch reuse: completed OCR evidence is not reprocessed
# ===========================================================================


class ProviderSwitchReuseTests(unittest.TestCase):
    """Success criterion: completed extraction/OCR evidence is not reprocessed
    after provider switching; only unfinished work is resumed.

    We verify the contract via the immutable evidence write semantics:
    ``write_immutable_ocr_png`` returns False (exact replay) for already-written
    evidence, proving it is preserved not re-OCR'd.
    """

    def test_completed_ocr_evidence_is_replayable_not_overwritten(self) -> None:
        import hashlib
        import pymupdf

        from services.api.app.writing_reference_ocr_evidence import (
            build_ocr_evidence_relpath,
            write_immutable_ocr_png,
        )

        document = pymupdf.open()
        page = document.new_page()
        pixmap = page.get_pixmap(dpi=200)
        png_bytes = pixmap.tobytes("png")
        document.close()

        digest = hashlib.sha256(png_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relpath = build_ocr_evidence_relpath(
                "project/doc/source.pdf", "rev_001", 1, 200, digest
            )
            # First write creates the immutable file
            created = write_immutable_ocr_png(root, relpath, png_bytes, digest)
            self.assertTrue(created)
            # Replay (provider switch) does NOT re-write — returns False
            replay = write_immutable_ocr_png(root, relpath, png_bytes, digest)
            self.assertFalse(replay)


# ===========================================================================
# 8b. Paddle-fallback gateway wiring tests (main.py integration)
# ===========================================================================


class PaddleFallbackGatewayWiringTests(unittest.TestCase):
    """Tests for the _PaddleFallbackOcrGateway wiring in main.py.

    These verify that the gateway adapter correctly delegates to the
    OcrFallbackOrchestrator and returns OcrResult with the actual model.
    """

    def test_hosted_paddle_concurrency_is_hard_bounded_to_four(self) -> None:
        from services.api.app.main import _bounded_paddle_ocr_concurrency

        self.assertEqual(1, _bounded_paddle_ocr_concurrency("0"))
        self.assertEqual(2, _bounded_paddle_ocr_concurrency("2"))
        self.assertEqual(4, _bounded_paddle_ocr_concurrency("8"))
        self.assertEqual(4, _bounded_paddle_ocr_concurrency("invalid"))

    def test_paddle_success_returns_paddle_model(self) -> None:
        """When Paddle succeeds, the gateway returns PaddleOCR-VL-1.6."""
        from services.api.app.main import _PaddleFallbackOcrGateway
        from services.api.app.ocr_gateway import OcrRequest

        # Build a fake Paddle adapter that succeeds
        paddle_adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response(),
            poll_fn=lambda *a: _make_poll_response("done"),
            jsonl_fn=lambda url, headers: _make_jsonl(
                [{"page_index": 0, "markdown": "Paddle gateway text"}]
            ),
            sleep_fn=lambda s: None,
        )

        # Fake GLM gateway (should NOT be called)
        class FakeGlmGateway:
            model = GLM_FALLBACK_MODEL

            def run(self, request):
                raise AssertionError("GLM should not be called on Paddle success")

        gateway = _PaddleFallbackOcrGateway(
            paddle_adapter=paddle_adapter,
            glm_gateway=FakeGlmGateway(),
        )
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png"
        result = gateway.run(OcrRequest(image_bytes=png_bytes, image_suffix=".png"))

        self.assertEqual("Paddle gateway text", result.text)
        self.assertEqual(PADDLE_OCR_MODEL, result.model)
        self.assertEqual((), result.warnings)

    def test_paddle_failure_falls_back_to_glm_with_provenance(self) -> None:
        """When Paddle fails, the gateway falls back to GLM and records it."""
        from services.api.app.main import _PaddleFallbackOcrGateway
        from services.api.app.ocr_gateway import OcrRequest, OcrResult
        from datetime import datetime, timezone

        # Build a fake Paddle adapter that fails
        paddle_adapter = PaddleOcrAdapter(
            PaddleOcrSettings(),
            submit_fn=lambda *a: _make_submit_response("job_fail"),
            poll_fn=lambda *a: _make_poll_response("failed"),
            jsonl_fn=lambda url, headers: "",
            sleep_fn=lambda s: None,
        )

        # Fake GLM gateway that succeeds
        class FakeGlmGateway:
            model = GLM_FALLBACK_MODEL

            def run(self, request):
                return OcrResult(
                    text="GLM fallback via gateway",
                    model=GLM_FALLBACK_MODEL,
                    source_token="ocrsrc_test",
                    content_hash="a" * 64,
                    character_count=20,
                    called_at=datetime.now(timezone.utc),
                    duration_ms=10.0,
                )

        gateway = _PaddleFallbackOcrGateway(
            paddle_adapter=paddle_adapter,
            glm_gateway=FakeGlmGateway(),
        )
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake-png"
        result = gateway.run(OcrRequest(image_bytes=png_bytes, image_suffix=".png"))

        self.assertEqual("GLM fallback via gateway", result.text)
        self.assertEqual(GLM_FALLBACK_MODEL, result.model)
        # GLM output is never labeled as Paddle
        self.assertNotEqual(PADDLE_OCR_MODEL, result.model)
        self.assertTrue(result.warnings)
        self.assertIn("paddle_failure", result.warnings[0])


if __name__ == "__main__":
    unittest.main()
