from __future__ import annotations

import hashlib
import os
import re
import struct
import uuid
from pathlib import Path
from typing import Any


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
OCR_EVIDENCE_DPI = 200
# Models accepted for new OCR evidence rows. GLM is the original model;
# PaddleOCR-VL-1.6 is admitted when the Paddle primary route is active.
OCR_EVIDENCE_MODEL = "GLM-OCR-bf16"
OCR_EVIDENCE_ALLOWED_MODELS: frozenset[str] = frozenset(
    {
        OCR_EVIDENCE_MODEL,
        "PaddleOCR-VL-1.6",
        "PaddleOCR",
        "models--PaddlePaddle--PaddleOCR-VL-1.6",
    }
)
_SAFE_REVISION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _validated_relpath(storage_relpath: str) -> Path:
    relative = Path(storage_relpath)
    if (
        not storage_relpath
        or relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
    ):
        raise ValueError("OCR evidence storage path must be a safe relative path")
    return relative


def build_ocr_evidence_relpath(
    artifact_storage_relpath: str,
    extraction_revision: str,
    physical_page: int,
    dpi: int,
    image_sha256: str,
) -> str:
    """Return the immutable PNG sidecar path for one extracted PDF page."""

    artifact_relative = _validated_relpath(artifact_storage_relpath)
    if not _SAFE_REVISION_PATTERN.fullmatch(extraction_revision):
        raise ValueError("OCR extraction revision is not path-safe")
    if physical_page < 1:
        raise ValueError("OCR physical page must be positive")
    if dpi != OCR_EVIDENCE_DPI:
        raise ValueError(f"OCR evidence must be rendered at {OCR_EVIDENCE_DPI} DPI")
    if not re.fullmatch(r"[0-9a-f]{64}", image_sha256):
        raise ValueError("OCR image SHA-256 is invalid")
    filename = (
        f"page_{physical_page:04d}_{dpi}dpi_{image_sha256[:16]}.png"
    )
    return str(
        artifact_relative.parent
        / "ocr"
        / extraction_revision
        / filename
    )


def png_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """Read dimensions from a complete PNG IHDR without decoding page pixels."""

    if not image_bytes.startswith(PNG_SIGNATURE):
        raise ValueError("OCR evidence is not a PNG image")
    if len(image_bytes) < 33:
        raise ValueError("OCR evidence PNG is truncated")
    ihdr_length = struct.unpack(">I", image_bytes[8:12])[0]
    if image_bytes[12:16] != b"IHDR" or ihdr_length != 13:
        raise ValueError("OCR evidence PNG has an invalid IHDR")
    width, height = struct.unpack(">II", image_bytes[16:24])
    if width <= 0 or height <= 0:
        raise ValueError("OCR evidence PNG dimensions are invalid")
    return width, height


def resolve_ocr_evidence_path(
    artifact_root: Path | str,
    storage_relpath: str,
) -> Path:
    """Resolve a sidecar path while keeping it beneath the artifact root."""

    relative = _validated_relpath(storage_relpath)
    root = Path(artifact_root).resolve()
    resolved = (root / relative).resolve()
    if root not in resolved.parents:
        raise ValueError("OCR evidence path is outside the artifact root")
    return resolved


def write_immutable_ocr_png(
    artifact_root: Path | str,
    storage_relpath: str,
    image_bytes: bytes,
    expected_sha256: str,
) -> bool:
    """Atomically create an immutable PNG; return False for an exact replay."""

    png_dimensions(image_bytes)
    actual_sha256 = hashlib.sha256(image_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("OCR evidence PNG hash does not match")
    output_path = resolve_ocr_evidence_path(artifact_root, storage_relpath)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if hashlib.sha256(output_path.read_bytes()).hexdigest() != expected_sha256:
            raise RuntimeError("immutable OCR evidence PNG hash mismatch")
        return False

    temporary_path = output_path.with_name(
        f".{output_path.name}.{uuid.uuid4().hex}.tmp"
    )
    created = False
    try:
        with temporary_path.open("xb") as handle:
            handle.write(image_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Hard-link publication fails rather than overwriting a concurrent
            # immutable writer. Both paths are in the same directory.
            os.link(temporary_path, output_path)
            created = True
        except FileExistsError:
            if hashlib.sha256(output_path.read_bytes()).hexdigest() != expected_sha256:
                raise RuntimeError("immutable OCR evidence PNG hash mismatch")
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    if hashlib.sha256(output_path.read_bytes()).hexdigest() != expected_sha256:
        raise RuntimeError("immutable OCR evidence PNG hash mismatch")
    return created


def validate_new_ocr_page_evidence(evidence: Any) -> None:
    """Enforce fields that remain optional only for legacy extraction rows."""

    if evidence.dpi != OCR_EVIDENCE_DPI:
        raise ValueError(f"new OCR evidence must use {OCR_EVIDENCE_DPI} DPI")
    if evidence.model not in OCR_EVIDENCE_ALLOWED_MODELS:
        raise ValueError(
            f"new OCR evidence model '{evidence.model}' is not in the "
            f"allowlist {sorted(OCR_EVIDENCE_ALLOWED_MODELS)}"
        )
    if evidence.fell_back:
        if not evidence.primary_model or not evidence.fallback_reason:
            raise ValueError(
                "fallback OCR evidence must record primary model and reason"
            )
    elif evidence.fallback_reason:
        raise ValueError(
            "non-fallback OCR evidence cannot record a fallback reason"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.image_sha256):
        raise ValueError("new OCR evidence image SHA-256 is invalid")
    if evidence.image_size_bytes <= 0:
        raise ValueError("new OCR evidence image size is missing")
    if evidence.image_width_px <= 0 or evidence.image_height_px <= 0:
        raise ValueError("new OCR evidence image dimensions are missing")
    _validated_relpath(evidence.storage_relpath)
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.ocr_profile_digest):
        raise ValueError("new OCR evidence profile digest is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence.ocr_text_sha256):
        raise ValueError("new OCR evidence text SHA-256 is invalid")
    if evidence.ocr_result_status not in {"text_recovered", "empty_text"}:
        raise ValueError("new OCR evidence status is invalid")
    if evidence.ocr_result_status == "empty_text":
        if evidence.ocr_character_count != 0 or evidence.span_id:
            raise ValueError("empty OCR evidence cannot reference recovered text")
    elif evidence.ocr_character_count <= 0 or not evidence.span_id:
        raise ValueError("recovered OCR evidence must reference recovered text")
    if evidence.channel == "ocr_reconciled":
        if not evidence.native_channel:
            raise ValueError(
                "reconciled OCR evidence must retain the native text channel"
            )
        required_native_fields = {
            "span_id",
            "source_locator",
            "source_text_sha256",
            "channel",
        }
        for native in evidence.native_channel:
            if set(native) != required_native_fields:
                raise ValueError(
                    "reconciled OCR native channel fields are incomplete"
                )
            if (
                not native["span_id"]
                or not native["source_locator"]
                or native["channel"] != "native_text"
                or not re.fullmatch(r"[0-9a-f]{64}", native["source_text_sha256"])
            ):
                raise ValueError(
                    "reconciled OCR native channel evidence is invalid"
                )
