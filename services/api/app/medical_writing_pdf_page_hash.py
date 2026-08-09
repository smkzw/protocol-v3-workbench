"""Canonical, deterministic per-page hashes for Word/PDF evidence.

The Word receipt contract stores a per-page ``pdf_page_sha256`` but must not
depend on whichever PDF splitter happened to be used by a verifier.  This
adapter fixes the renderer, version, DPI, pixel format, stride, dimensions,
and digest preimage.  It hashes PDFium's canonical RGB bitmap buffer rather
than a PNG container or a re-serialized one-page PDF, both of which can carry
non-semantic metadata differences.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable


CANONICAL_PDF_PAGE_HASH_CONTRACT = "medical_writing_pdf_page_hash_v1"
CANONICAL_PDF_PAGE_HASH_RENDERER = "pypdfium2"
CANONICAL_PDF_PAGE_HASH_RENDERER_VERSION = "5.12.1"
CANONICAL_PDF_PAGE_HASH_DPI = 200
CANONICAL_PDF_PAGE_HASH_PIXEL_FORMAT = "RGB8"
MAX_CANONICAL_PDF_BYTES = 50 * 1024 * 1024
MAX_CANONICAL_PDF_PAGES = 100


class MedicalWritingPdfPageHashError(ValueError):
    """Raised when canonical PDF page evidence cannot be produced safely."""


@dataclass(frozen=True)
class MedicalWritingCanonicalPdfPageHash:
    """One page's canonical hash and the metadata needed to audit it."""

    page_number: int
    page_width_points: float
    page_height_points: float
    pixel_width: int
    pixel_height: int
    row_stride_bytes: int
    render_dpi: int
    pixel_format: str
    renderer: str
    renderer_version: str
    contract_version: str
    pdf_page_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "page_width_points": self.page_width_points,
            "page_height_points": self.page_height_points,
            "pixel_width": self.pixel_width,
            "pixel_height": self.pixel_height,
            "row_stride_bytes": self.row_stride_bytes,
            "render_dpi": self.render_dpi,
            "pixel_format": self.pixel_format,
            "renderer": self.renderer,
            "renderer_version": self.renderer_version,
            "contract_version": self.contract_version,
            "pdf_page_sha256": self.pdf_page_sha256,
        }


def _runtime_renderer_version() -> str:
    try:
        return importlib.metadata.version(CANONICAL_PDF_PAGE_HASH_RENDERER)
    except importlib.metadata.PackageNotFoundError as exc:
        raise MedicalWritingPdfPageHashError(
            "canonical PDF page hashing requires pypdfium2 5.12.1"
        ) from exc


def _canonical_digest_header(
    *,
    page_number: int,
    page_width_points: float,
    page_height_points: float,
    pixel_width: int,
    pixel_height: int,
    row_stride_bytes: int,
) -> bytes:
    payload = {
        "contract_version": CANONICAL_PDF_PAGE_HASH_CONTRACT,
        "renderer": CANONICAL_PDF_PAGE_HASH_RENDERER,
        "renderer_version": CANONICAL_PDF_PAGE_HASH_RENDERER_VERSION,
        "render_dpi": CANONICAL_PDF_PAGE_HASH_DPI,
        "pixel_format": CANONICAL_PDF_PAGE_HASH_PIXEL_FORMAT,
        "page_number": page_number,
        "page_width_points": round(page_width_points, 3),
        "page_height_points": round(page_height_points, 3),
        "pixel_width": pixel_width,
        "pixel_height": pixel_height,
        "row_stride_bytes": row_stride_bytes,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\0"


def canonical_pdf_page_hashes(
    pdf_bytes: bytes,
) -> tuple[MedicalWritingCanonicalPdfPageHash, ...]:
    """Render a PDF with one fixed contract and hash each RGB bitmap buffer.

    The function deliberately has no configurable DPI or renderer arguments.
    Changing any rendering parameter requires a new contract version and a
    new receipt migration decision; silently mixing hashes is unsafe.
    """

    if not isinstance(pdf_bytes, (bytes, bytearray, memoryview)):
        raise MedicalWritingPdfPageHashError("PDF bytes are required")
    payload = bytes(pdf_bytes)
    if not payload.startswith(b"%PDF-"):
        raise MedicalWritingPdfPageHashError("canonical page hashing requires a PDF")
    if len(payload) > MAX_CANONICAL_PDF_BYTES:
        raise MedicalWritingPdfPageHashError("PDF exceeds the canonical hash size limit")
    runtime_version = _runtime_renderer_version()
    if runtime_version != CANONICAL_PDF_PAGE_HASH_RENDERER_VERSION:
        raise MedicalWritingPdfPageHashError(
            "canonical page hashing requires pypdfium2=="
            f"{CANONICAL_PDF_PAGE_HASH_RENDERER_VERSION}; found {runtime_version}"
        )
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - metadata check normally catches it
        raise MedicalWritingPdfPageHashError(
            "canonical PDF page hashing requires pypdfium2"
        ) from exc

    try:
        document = pdfium.PdfDocument(payload)
    except Exception as exc:
        raise MedicalWritingPdfPageHashError("PDF cannot be opened for page hashing") from exc

    page_count = len(document)
    if page_count < 1 or page_count > MAX_CANONICAL_PDF_PAGES:
        try:
            document.close()
        finally:
            raise MedicalWritingPdfPageHashError(
                f"PDF must contain 1-{MAX_CANONICAL_PDF_PAGES} pages"
            )

    pages: list[MedicalWritingCanonicalPdfPageHash] = []
    scale = CANONICAL_PDF_PAGE_HASH_DPI / 72.0
    try:
        for index in range(page_count):
            page_number = index + 1
            page = document[index]
            try:
                width_points, height_points = page.get_size()
                width_points = float(width_points)
                height_points = float(height_points)
                if not (
                    math.isfinite(width_points)
                    and math.isfinite(height_points)
                    and width_points > 0
                    and height_points > 0
                ):
                    raise MedicalWritingPdfPageHashError(
                        f"page {page_number} has invalid dimensions"
                    )
                bitmap = page.render(
                    scale=scale,
                    rotation=0,
                    crop=(0, 0, 0, 0),
                    may_draw_forms=True,
                    optimize_mode="print",
                    draw_annots=True,
                    no_smoothtext=False,
                    no_smoothimage=False,
                    no_smoothpath=False,
                    force_halftone=False,
                    limit_image_cache=False,
                    rev_byteorder=True,
                )
                try:
                    if bitmap.mode != "RGB" or bitmap.n_channels != 3:
                        raise MedicalWritingPdfPageHashError(
                            f"page {page_number} did not render as RGB8"
                        )
                    pixel_bytes = bytes(bitmap.buffer)
                    header = _canonical_digest_header(
                        page_number=page_number,
                        page_width_points=width_points,
                        page_height_points=height_points,
                        pixel_width=int(bitmap.width),
                        pixel_height=int(bitmap.height),
                        row_stride_bytes=int(bitmap.stride),
                    )
                    digest = hashlib.sha256(header + pixel_bytes).hexdigest()
                    pages.append(
                        MedicalWritingCanonicalPdfPageHash(
                            page_number=page_number,
                            page_width_points=round(width_points, 3),
                            page_height_points=round(height_points, 3),
                            pixel_width=int(bitmap.width),
                            pixel_height=int(bitmap.height),
                            row_stride_bytes=int(bitmap.stride),
                            render_dpi=CANONICAL_PDF_PAGE_HASH_DPI,
                            pixel_format=CANONICAL_PDF_PAGE_HASH_PIXEL_FORMAT,
                            renderer=CANONICAL_PDF_PAGE_HASH_RENDERER,
                            renderer_version=CANONICAL_PDF_PAGE_HASH_RENDERER_VERSION,
                            contract_version=CANONICAL_PDF_PAGE_HASH_CONTRACT,
                            pdf_page_sha256=digest,
                        )
                    )
                finally:
                    bitmap.close()
            finally:
                close_page = getattr(page, "close", None)
                if close_page is not None:
                    close_page()
    except MedicalWritingPdfPageHashError:
        raise
    except Exception as exc:
        raise MedicalWritingPdfPageHashError(
            "PDF page rendering for canonical hashing failed"
        ) from exc
    finally:
        try:
            document.close()
        except Exception:
            pass
    return tuple(pages)


def canonical_pdf_page_hash_manifest_sha256(
    pages: Iterable[MedicalWritingCanonicalPdfPageHash],
    *,
    pdf_sha256: str,
) -> str:
    """Hash the ordered page evidence and full-PDF identity as one manifest."""

    if not re.fullmatch(r"[0-9a-f]{64}", str(pdf_sha256 or "")):
        raise MedicalWritingPdfPageHashError("pdf_sha256 must be lowercase SHA-256")
    ordered = tuple(pages)
    if not ordered or [page.page_number for page in ordered] != list(
        range(1, len(ordered) + 1)
    ):
        raise MedicalWritingPdfPageHashError(
            "canonical page hash manifest requires contiguous ordered pages"
        )
    payload = {
        "contract_version": CANONICAL_PDF_PAGE_HASH_CONTRACT,
        "pdf_sha256": pdf_sha256,
        "pages": [page.as_dict() for page in ordered],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
