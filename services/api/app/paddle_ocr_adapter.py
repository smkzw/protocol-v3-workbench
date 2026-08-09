"""Dedicated PaddleOCR-VL-1.6 official async Job API adapter.

This module intentionally does NOT mimic the OpenAI chat-completions contract.
Paddle's hosted document-parsing service is an asynchronous Job API:

    POST /api/v2/ocr/jobs          -> returns {"jobId": "...", "status": "pending"}
    GET  /api/v2/ocr/jobs/{jobId}  -> polls until status is "done" or "failed"
    result JSONL at data.resultUrl.jsonUrl (one JSON object per page)

All HTTP, polling, and JSONL parsing are injectable callables so unit tests
are fully deterministic and never touch the network.  No credential is
hardcoded or requested; the caller passes ``api_key`` at runtime.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

PADDLE_OCR_MODEL = "PaddleOCR-VL-1.6"
PADDLE_OCR_PROVIDER = "paddle_official"

# Default endpoints from the user-supplied transport contract.
DEFAULT_PADDLE_BASE_URL = "https://paddleocr.aistudio-app.com"
DEFAULT_JOB_PATH = "/api/v2/ocr/jobs"
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_POLL_MAX_ATTEMPTS = 120  # ~4 minutes at 2s intervals
DEFAULT_SUBMIT_MAX_ATTEMPTS = 4
DEFAULT_SUBMIT_RETRY_BASE_SECONDS = 1.0
DEFAULT_SUBMIT_RETRY_MAX_SECONDS = 30.0
_RETRYABLE_SUBMIT_HTTP_STATUSES = frozenset({429})

# Injectable type aliases (kept as ``Any`` in signatures for maximum
# test-determinism; the production default uses urllib).
HttpSubmit = Callable[[str, str, str, dict[str, str], bytes], str]
"""Submit a job: (base_url, job_path, model, headers, body_bytes) -> response_body_text"""

HttpPoll = Callable[[str, str, dict[str, str]], str]
"""Poll a job: (base_url, job_path_with_id, headers) -> response_body_text"""

JsonlFetch = Callable[[str, dict[str, str]], str]
"""Fetch JSONL result: (json_url, headers) -> raw_jsonl_text"""

Sleep = Callable[[float], None]


def _transport_error_label(exc: Exception) -> str:
    """Return a credential-safe transport signal suitable for audit evidence."""

    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {int(exc.code)}"
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return f"URLError:{type(reason).__name__ if reason is not None else 'unknown'}"
    return type(exc).__name__


class PaddleOcrError(RuntimeError):
    """Base error for Paddle OCR adapter failures."""


class PaddleOcrSubmissionRejectedError(PaddleOcrError):
    """The provider explicitly rejected the submit request before acceptance."""


class PaddleOcrOutcomeUnknownError(PaddleOcrError):
    """The provider may have accepted or executed work; do not invoke another OCR."""

    def __init__(self, message: str, *, job_id: str = "") -> None:
        self.job_id = job_id
        super().__init__(message)


class PaddleOcrJobFailedError(PaddleOcrError):
    """The Paddle job reached terminal ``failed`` status."""

    def __init__(self, job_id: str, detail: str = "") -> None:
        self.job_id = job_id
        self.detail = detail
        msg = f"Paddle OCR job {job_id} failed"
        if detail:
            msg = f"{msg}: {detail}"
        super().__init__(msg)


class PaddleOcrTimeoutError(PaddleOcrOutcomeUnknownError):
    """The Paddle job did not reach a terminal state within the poll budget."""

    def __init__(self, job_id: str, detail: str = "") -> None:
        self.job_id = job_id
        self.detail = detail
        message = f"Paddle OCR job {job_id} timed out"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message, job_id=job_id)


class PaddleOcrResultError(PaddleOcrOutcomeUnknownError):
    """The Paddle result JSONL could not be parsed or was empty."""


@dataclass(frozen=True)
class PaddleOcrSettings:
    """Configuration for the Paddle async OCR adapter.

    ``api_key`` is passed by the caller at runtime and is never stored in
    this module or written to disk.  It is excluded from ``repr`` output.
    """

    base_url: str = DEFAULT_PADDLE_BASE_URL
    job_path: str = DEFAULT_JOB_PATH
    model: str = PADDLE_OCR_MODEL
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS
    poll_max_attempts: int = DEFAULT_POLL_MAX_ATTEMPTS
    submit_max_attempts: int = DEFAULT_SUBMIT_MAX_ATTEMPTS
    submit_retry_base_seconds: float = DEFAULT_SUBMIT_RETRY_BASE_SECONDS
    submit_retry_max_seconds: float = DEFAULT_SUBMIT_RETRY_MAX_SECONDS
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        normalized = self.base_url.strip().rstrip("/")
        if not normalized:
            raise PaddleOcrError("Paddle OCR base_url must not be empty")
        try:
            parsed = urlsplit(normalized)
            parsed.port
        except ValueError as exc:  # pragma: no cover - defensive
            raise PaddleOcrError("Paddle OCR base_url is invalid") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise PaddleOcrError("Paddle OCR base_url must use http or https")
        object.__setattr__(self, "base_url", normalized)
        if self.poll_interval_seconds <= 0:
            raise PaddleOcrError("Paddle OCR poll interval must be positive")
        if self.poll_max_attempts < 1:
            raise PaddleOcrError("Paddle OCR poll max attempts must be >= 1")
        if self.submit_max_attempts < 1:
            raise PaddleOcrError("Paddle OCR submit max attempts must be >= 1")
        if self.submit_retry_base_seconds <= 0:
            raise PaddleOcrError(
                "Paddle OCR submit retry base seconds must be positive"
            )
        if self.submit_retry_max_seconds <= 0:
            raise PaddleOcrError(
                "Paddle OCR submit retry max seconds must be positive"
            )

    def auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


@dataclass(frozen=True)
class PaddleOcrPageResult:
    """One page of Paddle OCR output, parsed from a JSONL line."""

    page_index: int
    markdown: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class PaddleOcrJobResult:
    """The complete parsed result of a finished Paddle OCR job."""

    job_id: str
    model: str
    pages: tuple[PaddleOcrPageResult, ...]
    duration_ms: float


# ---------------------------------------------------------------------------
# Default urllib-based implementations (production transport).
# ---------------------------------------------------------------------------


def _urllib_post(
    base_url: str,
    job_path: str,
    model: str,
    headers: dict[str, str],
    body_bytes: bytes,
    *,
    timeout_seconds: float = 120.0,
) -> str:
    """Default HTTP submit implementation using urllib."""
    url = f"{base_url.rstrip('/')}{job_path}"
    request = urllib.request.Request(
        url,
        data=body_bytes,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def _urllib_get(
    base_url: str,
    path_with_id: str,
    headers: dict[str, str],
    *,
    timeout_seconds: float = 120.0,
) -> str:
    """Default HTTP poll implementation using urllib."""
    url = f"{base_url.rstrip('/')}{path_with_id}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def _urllib_jsonl(
    json_url: str,
    headers: dict[str, str],
    *,
    timeout_seconds: float = 120.0,
) -> str:
    """Default JSONL fetch implementation using urllib."""
    request = urllib.request.Request(json_url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Public adapter.
# ---------------------------------------------------------------------------


class PaddleOcrAdapter:
    """Async Job API adapter for PaddleOCR-VL-1.6.

    Every external call (submit, poll, JSONL fetch, sleep) is injectable so
    tests are fully deterministic.  The adapter never stores the ``api_key``
    beyond the ``PaddleOcrSettings`` frozen dataclass lifetime.
    """

    def __init__(
        self,
        settings: PaddleOcrSettings,
        *,
        submit_fn: HttpSubmit | None = None,
        poll_fn: HttpPoll | None = None,
        jsonl_fn: JsonlFetch | None = None,
        sleep_fn: Sleep | None = None,
    ) -> None:
        self.settings = settings
        self._submit_fn = submit_fn or self._default_submit
        self._poll_fn = poll_fn or self._default_poll
        self._jsonl_fn = jsonl_fn or self._default_jsonl
        self._sleep_fn = sleep_fn or time.sleep

    # -- public API --------------------------------------------------------

    def submit_and_wait(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        *,
        filename: str = "page.png",
    ) -> PaddleOcrJobResult:
        """Submit a single-image OCR job, poll until done, and parse the result.

        This is the single entry point used by the fallback orchestrator.
        """
        started = time.perf_counter()
        headers = self.settings.auth_headers()
        body, content_type = self._build_submit_body(
            image_bytes, mime_type, filename
        )
        submit_headers = {**headers, "Content-Type": content_type}
        submit_response = ""
        for attempt in range(self.settings.submit_max_attempts):
            try:
                submit_response = self._submit_fn(
                    self.settings.base_url,
                    self.settings.job_path,
                    self.settings.model,
                    submit_headers,
                    body,
                )
                break
            except Exception as exc:
                retryable = (
                    isinstance(exc, urllib.error.HTTPError)
                    and int(exc.code) in _RETRYABLE_SUBMIT_HTTP_STATUSES
                )
                if (
                    not retryable
                    or attempt + 1 >= self.settings.submit_max_attempts
                ):
                    message = (
                        "Paddle OCR submit request failed: "
                        f"{_transport_error_label(exc)}"
                    )
                    if (
                        isinstance(exc, urllib.error.HTTPError)
                        and 400 <= int(exc.code) < 500
                    ):
                        raise PaddleOcrSubmissionRejectedError(message) from exc
                    raise PaddleOcrOutcomeUnknownError(message) from exc
                retry_after = 0.0
                response_headers = getattr(exc, "headers", None)
                if response_headers is not None:
                    retry_after = self._retry_after_seconds(
                        response_headers.get("Retry-After")
                    )
                self._sleep_fn(
                    min(
                        self.settings.submit_retry_max_seconds,
                        max(
                            retry_after,
                            self.settings.submit_retry_base_seconds
                            * (2**attempt),
                        ),
                    )
                )
        try:
            job_id = self._parse_job_id(submit_response)
        except PaddleOcrError as exc:
            raise PaddleOcrOutcomeUnknownError(
                f"Paddle OCR submit outcome is unknown: {exc}"
            ) from exc
        poll_path = f"{self.settings.job_path}/{job_id}"

        for attempt in range(self.settings.poll_max_attempts):
            try:
                poll_response = self._poll_fn(
                    self.settings.base_url,
                    poll_path,
                    headers,
                )
            except Exception as exc:
                raise PaddleOcrOutcomeUnknownError(
                    f"Paddle OCR job {job_id} poll request failed: "
                    f"{_transport_error_label(exc)}",
                    job_id=job_id,
                ) from exc
            try:
                status, result_url = self._parse_poll_response(poll_response)
            except PaddleOcrError as exc:
                raise PaddleOcrOutcomeUnknownError(
                    f"Paddle OCR job {job_id} poll outcome is unknown: {exc}",
                    job_id=job_id,
                ) from exc
            if status == "done":
                try:
                    jsonl_text = self._jsonl_fn(result_url, {})
                except Exception as exc:
                    raise PaddleOcrOutcomeUnknownError(
                        f"Paddle OCR job {job_id} result download failed: "
                        f"{_transport_error_label(exc)}",
                        job_id=job_id,
                    ) from exc
                try:
                    pages = self._parse_jsonl(jsonl_text)
                except PaddleOcrError as exc:
                    raise PaddleOcrResultError(
                        f"Paddle OCR job {job_id} returned an invalid result: {exc}",
                        job_id=job_id,
                    ) from exc
                if not pages:
                    raise PaddleOcrResultError(
                        f"Paddle OCR job {job_id} returned empty result JSONL",
                        job_id=job_id,
                    )
                duration_ms = (time.perf_counter() - started) * 1000
                return PaddleOcrJobResult(
                    job_id=job_id,
                    model=self.settings.model,
                    pages=tuple(pages),
                    duration_ms=duration_ms,
                )
            if status == "failed":
                raise PaddleOcrJobFailedError(job_id, detail=result_url)
            # status in {"pending", "running"} — continue polling
            self._sleep_fn(self.settings.poll_interval_seconds)

        raise PaddleOcrTimeoutError(
            job_id,
            f"did not complete within {self.settings.poll_max_attempts} poll attempts",
        )

    @staticmethod
    def _retry_after_seconds(value: Any) -> float:
        """Parse Retry-After seconds or HTTP-date without exceeding caller cap."""
        if value is None:
            return 0.0
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            return max(0.0, float(text))
        except ValueError:
            pass
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(
            0.0,
            (parsed.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds(),
        )

    # -- body/response parsing (injectable logic, deterministic) -----------

    @staticmethod
    def _build_submit_body(
        image_bytes: bytes,
        mime_type: str,
        filename: str,
    ) -> tuple[bytes, str]:
        """Build the official local-file multipart/form-data request body."""
        boundary = f"----cms-paddleocr-{uuid.uuid4().hex}"
        delimiter = f"--{boundary}\r\n".encode("ascii")
        chunks = [
            delimiter,
            b'Content-Disposition: form-data; name="model"\r\n\r\n',
            PADDLE_OCR_MODEL.encode("utf-8"),
            b"\r\n",
            delimiter,
            b'Content-Disposition: form-data; name="optionalPayload"\r\n\r\n',
            json.dumps(
                {
                    "useDocOrientationClassify": False,
                    "useDocUnwarping": False,
                    "useChartRecognition": False,
                },
                separators=(",", ":"),
            ).encode("utf-8"),
            b"\r\n",
            delimiter,
            (
                f'Content-Disposition: form-data; name="file"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {mime_type}\r\n\r\n".encode("ascii"),
            image_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("ascii"),
        ]
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    @staticmethod
    def _parse_job_id(response_text: str) -> str:
        try:
            payload = json.loads(response_text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PaddleOcrError(
                "Paddle OCR submit response is not valid JSON"
            ) from exc
        job_id = ""
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                job_id = str(
                    data.get("jobId") or data.get("job_id") or ""
                ).strip()
            if not job_id:
                job_id = str(
                    payload.get("jobId") or payload.get("job_id") or ""
                ).strip()
        if not job_id:
            raise PaddleOcrError(
                "Paddle OCR submit response is missing jobId"
            )
        return job_id

    @staticmethod
    def _parse_poll_response(
        response_text: str,
    ) -> tuple[str, str]:
        """Return (status, result_jsonl_url).

        On failure, ``result_jsonl_url`` carries a detail/error message for
        diagnostic purposes; on success it is the actual JSONL URL.
        """
        try:
            payload = json.loads(response_text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PaddleOcrError(
                "Paddle OCR poll response is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise PaddleOcrError("Paddle OCR poll response has unexpected shape")
        data = payload.get("data")
        nested_state = data.get("state") if isinstance(data, dict) else ""
        status = str(
            nested_state or payload.get("status") or payload.get("state") or ""
        ).strip().casefold()
        if status in {"done", "succeeded", "success", "completed"}:
            result_url = ""
            if isinstance(data, dict):
                result_url_obj = data.get("resultUrl")
                if isinstance(result_url_obj, dict):
                    result_url = str(result_url_obj.get("jsonUrl") or "").strip()
                elif isinstance(result_url_obj, str):
                    result_url = result_url_obj.strip()
            if not result_url:
                raise PaddleOcrError(
                    "Paddle OCR poll response is done but missing result JSONL URL"
                )
            return "done", result_url
        if status in {"failed", "error"}:
            detail = ""
            if isinstance(data, dict):
                detail = str(
                    data.get("errorMsg")
                    or data.get("error")
                    or data.get("message")
                    or ""
                ).strip()
            elif isinstance(data, str):
                detail = data.strip()
            return "failed", detail
        if status in {"pending", "running", "queued", "processing"}:
            return status, ""
        # Unknown status: treat as still running (be conservative).
        return "running", ""

    @staticmethod
    def _parse_jsonl(jsonl_text: str) -> list[PaddleOcrPageResult]:
        """Parse JSONL text into page results.

        Each non-empty line is one JSON object.  The adapter extracts
        ``markdown`` (or ``md`` / ``text``) and the page index.
        """
        pages: list[PaddleOcrPageResult] = []
        for index, line in enumerate(jsonl_text.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            result = obj.get("result")
            layouts = (
                result.get("layoutParsingResults")
                if isinstance(result, dict)
                else None
            )
            if isinstance(layouts, list):
                for layout in layouts:
                    if not isinstance(layout, dict):
                        continue
                    markdown_obj = layout.get("markdown")
                    markdown = (
                        str(markdown_obj.get("text") or "")
                        if isinstance(markdown_obj, dict)
                        else str(markdown_obj or "")
                    )
                    pages.append(
                        PaddleOcrPageResult(
                            page_index=len(pages),
                            markdown=markdown,
                            raw=layout,
                        )
                    )
                continue
            markdown_obj = obj.get("markdown")
            markdown = (
                str(markdown_obj.get("text") or "")
                if isinstance(markdown_obj, dict)
                else str(
                    markdown_obj or obj.get("md") or obj.get("text") or ""
                )
            )
            raw_page_idx = obj.get("page_index", obj.get("page", index))
            try:
                page_idx = int(raw_page_idx)
            except (TypeError, ValueError, OverflowError) as exc:
                raise PaddleOcrResultError(
                    "Paddle OCR result has an invalid page index"
                ) from exc
            pages.append(
                PaddleOcrPageResult(
                    page_index=page_idx,
                    markdown=markdown,
                    raw=obj,
                )
            )
        return pages

    # -- default urllib wrappers (bound to settings.timeout_seconds) -------

    def _default_submit(
        self, base_url: str, job_path: str, model: str,
        headers: dict[str, str], body: bytes,
    ) -> str:
        return _urllib_post(
            base_url, job_path, model, headers, body,
            timeout_seconds=self.settings.timeout_seconds,
        )

    def _default_poll(
        self, base_url: str, path_with_id: str, headers: dict[str, str],
    ) -> str:
        return _urllib_get(
            base_url, path_with_id, headers,
            timeout_seconds=self.settings.timeout_seconds,
        )

    def _default_jsonl(self, json_url: str, headers: dict[str, str]) -> str:
        return _urllib_jsonl(
            json_url, headers,
            timeout_seconds=self.settings.timeout_seconds,
        )
