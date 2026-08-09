from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Union
from urllib.parse import urlsplit

from .omlx_workload_gate_client import (
    OmlxWorkloadGateClient,
    run_gated_omlx_request,
)


PathLike = Union[str, os.PathLike]
OcrTransport = Callable[[urllib.request.Request, float], bytes]

DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_MODEL = "GLM-OCR-bf16"
ALLOWED_MODELS = frozenset(
    {
        "GLM-OCR-bf16",
        "PaddleOCR",
        "models--PaddlePaddle--PaddleOCR-VL-1.6",
    }
)
SUPPORTED_IMAGE_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
)

OCR_PROMPT = (
    "请对图像执行逐字 OCR 转写。只输出图像中实际清晰可见的文字，保持原有阅读顺序、换行、标点、大小写和数值。"
    "不得根据上下文推断模糊、裁切或遮挡内容，不得补写、改写、总结、解释或纠错。"
    "无法辨认的局部请标记为[无法辨认]，不要猜测。只返回 OCR 正文。"
)
OCR_GATEWAY_CONTRACT = "local-openai-chat-completions-image-data-url-v1"
OCR_PROFILE_MODELS = {
    "ocr-glm-v1": "GLM-OCR-bf16",
    "ocr-paddle-v1": "models--PaddlePaddle--PaddleOCR-VL-1.6",
}


def ocr_profile_digest(profile_version: str) -> str:
    model = OCR_PROFILE_MODELS.get(profile_version)
    if model is None:
        raise OcrGatewayConfigurationError("OCR profile is not allowlisted")
    payload = json.dumps(
        {
            "profile_version": profile_version,
            "model": model,
            "prompt": OCR_PROMPT,
            "gateway_contract": OCR_GATEWAY_CONTRACT,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_ocr_profile_model(profile_version: str, model: str) -> None:
    expected = OCR_PROFILE_MODELS.get(profile_version)
    if expected is None or model != expected:
        raise OcrGatewayConfigurationError(
            "OCR profile and model configuration do not match"
        )


class OcrGatewayConfigurationError(RuntimeError):
    """Raised when the local-only OCR gateway is configured unsafely."""


class OcrGatewayRequestError(RuntimeError):
    """Raised when a source request fails local validation."""


class OcrGatewayRuntimeError(RuntimeError):
    """Raised when the local OCR service fails closed."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise urllib.error.HTTPError(
            request.full_url,
            code,
            "Local OCR redirect blocked",
            headers,
            response,
        )


@dataclass(frozen=True)
class OcrGatewaySettings:
    allowed_roots: Sequence[PathLike]
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 120.0
    api_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        roots = _resolve_allowed_roots(self.allowed_roots)
        base_url = _validated_base_url(self.base_url)
        if self.model not in ALLOWED_MODELS:
            raise OcrGatewayConfigurationError("OCR model is not allowlisted")
        if self.timeout_seconds <= 0:
            raise OcrGatewayConfigurationError("OCR timeout must be positive")
        object.__setattr__(self, "allowed_roots", roots)
        object.__setattr__(self, "base_url", base_url)


@dataclass(frozen=True)
class OcrRequest:
    source_path: Optional[PathLike] = None
    image_bytes: Optional[bytes] = field(default=None, repr=False)
    image_suffix: Optional[str] = None

    def __post_init__(self) -> None:
        path_mode = self.source_path is not None
        bytes_mode = self.image_bytes is not None or self.image_suffix is not None
        if path_mode == bytes_mode:
            raise OcrGatewayRequestError(
                "OCR request must contain exactly one image source"
            )
        if bytes_mode:
            if not isinstance(self.image_bytes, bytes) or not self.image_bytes:
                raise OcrGatewayRequestError("OCR image bytes are required")
            if self.image_suffix not in SUPPORTED_IMAGE_SUFFIXES:
                raise OcrGatewayRequestError("OCR source format is not supported")


@dataclass(frozen=True)
class OcrResult:
    text: str
    model: str
    source_token: str
    content_hash: str
    character_count: int
    called_at: datetime
    duration_ms: float
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    status: str = "succeeded"
    provider: str = ""
    fell_back: bool = False
    primary_model: str = ""
    fallback_reason: str = ""

    def public_audit_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "model": self.model,
            "source_token": self.source_token,
            "character_count": self.character_count,
            "called_at": self.called_at.isoformat(),
            "duration_ms": round(self.duration_ms, 3),
        }


class LocalOcrGateway:
    def __init__(
        self,
        settings: OcrGatewaySettings,
        transport: Optional[OcrTransport] = None,
        workload_gate: OmlxWorkloadGateClient | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport or _urllib_transport
        self._workload_gate = workload_gate

    def run(self, request: OcrRequest) -> OcrResult:
        if request.source_path is not None:
            source_path = _resolve_source_file(
                request.source_path, self.settings.allowed_roots
            )
            try:
                image_bytes = source_path.read_bytes()
            except OSError:
                raise OcrGatewayRequestError("OCR source could not be read") from None
            suffix = source_path.suffix.lower()
        else:
            image_bytes = request.image_bytes
            suffix = str(request.image_suffix)
        mime_type = _validated_image_mime_type(suffix, image_bytes)
        content_hash = hashlib.sha256(image_bytes).hexdigest()
        source_token = _opaque_source_token(content_hash)

        called_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        try:
            leased_model = {}

            def _run_transport(lease: dict) -> bytes:
                # The gate only admits/constrains the oMLX workload. The role
                # binding remains authoritative for the selected model.
                model = self.settings.model
                leased_model["model"] = model
                payload = _request_payload(model, mime_type, image_bytes)
                headers = {"Content-Type": "application/json"}
                if self.settings.api_key:
                    headers["Authorization"] = f"Bearer {self.settings.api_key}"
                http_request = urllib.request.Request(
                    f"{self.settings.base_url}/chat/completions",
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                return self._transport(
                    http_request,
                    self.settings.timeout_seconds,
                )

            response_body = run_gated_omlx_request(
                _run_transport,
                kind="ocr",
                owner="medical-writing-api:ocr",
                gate_client=self._workload_gate,
            )
        except Exception:
            raise OcrGatewayRuntimeError("Local OCR request failed") from None
        duration_ms = (time.perf_counter() - started) * 1000
        text = _completion_text(response_body)
        result_model = leased_model.get("model", self.settings.model)
        return OcrResult(
            text=text,
            model=result_model,
            source_token=source_token,
            content_hash=content_hash,
            character_count=len(text),
            called_at=called_at,
            duration_ms=duration_ms,
        )


def _resolve_allowed_roots(allowed_roots: Sequence[PathLike]) -> Tuple[Path, ...]:
    if not allowed_roots:
        raise OcrGatewayConfigurationError("OCR allowed_roots must not be empty")
    resolved_roots = []
    for root in allowed_roots:
        try:
            resolved = Path(root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            raise OcrGatewayConfigurationError("OCR allowed root is invalid") from None
        if not resolved.is_dir():
            raise OcrGatewayConfigurationError("OCR allowed root must be a directory")
        resolved_roots.append(resolved)
    return tuple(resolved_roots)


def _validated_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(normalized)
        parsed.port
    except ValueError:
        raise OcrGatewayConfigurationError("OCR base_url is invalid") from None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise OcrGatewayConfigurationError(
            "OCR base_url must use localhost or 127.0.0.1"
        )
    return normalized


def _resolve_source_file(source_path: PathLike, allowed_roots: Sequence[Path]) -> Path:
    try:
        resolved = Path(source_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        raise OcrGatewayRequestError("OCR source is not an existing file") from None
    if not any(_is_relative_to(resolved, root) for root in allowed_roots):
        raise OcrGatewayRequestError("OCR source is outside allowed roots")
    if not resolved.is_file():
        raise OcrGatewayRequestError("OCR source must be a file")
    if resolved.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        raise OcrGatewayRequestError("OCR source format is not supported")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validated_image_mime_type(suffix: str, content: bytes) -> str:
    expected = {
        ".jpg": ("image/jpeg", content.startswith(b"\xff\xd8\xff")),
        ".jpeg": ("image/jpeg", content.startswith(b"\xff\xd8\xff")),
        ".png": ("image/png", content.startswith(b"\x89PNG\r\n\x1a\n")),
        ".webp": (
            "image/webp",
            len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        ),
        ".tif": (
            "image/tiff",
            content.startswith(b"II*\x00") or content.startswith(b"MM\x00*"),
        ),
        ".tiff": (
            "image/tiff",
            content.startswith(b"II*\x00") or content.startswith(b"MM\x00*"),
        ),
    }
    mime_type, signature_matches = expected[suffix]
    if not signature_matches:
        raise OcrGatewayRequestError("OCR source content is not a supported image")
    return mime_type


def _request_payload(model: str, mime_type: str, image_bytes: bytes) -> Dict[str, Any]:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                    },
                ],
            }
        ],
        "temperature": 0,
    }


def _opaque_source_token(content_hash: str) -> str:
    digest = hashlib.sha256(f"ocr-source-v1|{content_hash}".encode("ascii")).hexdigest()
    return f"ocrsrc_{digest[:16]}"


def _completion_text(response_body: bytes) -> str:
    try:
        payload = json.loads(response_body.decode("utf-8"))
        choices = payload["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ValueError
        message = choice["message"]
        if not isinstance(message, dict):
            raise ValueError
        content = message["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError
        return content
    except (AttributeError, KeyError, TypeError, UnicodeDecodeError, ValueError):
        raise OcrGatewayRuntimeError("Local OCR response is invalid") from None


def _urllib_transport(request: urllib.request.Request, timeout_seconds: float) -> bytes:
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )
    with opener.open(request, timeout=timeout_seconds) as response:
        return response.read()
