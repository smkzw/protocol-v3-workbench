from __future__ import annotations

import base64
import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any

from PIL import Image


MIN_RENDER_DPI = 200
DEFAULT_RENDER_DPI = 220
MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_PAGES = 100


class MedicalWritingInstrumentAppendixError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedInstrumentAppendix:
    instrument_id: str
    title: str
    original_filename: str
    source_pdf_sha256: str
    render_dpi: int
    pages: tuple[dict[str, Any], ...]

    def content_blocks(self, *, body_order_start: int) -> list[dict[str, Any]]:
        identity = hashlib.sha256(
            f"{self.instrument_id}|{self.source_pdf_sha256}".encode("utf-8")
        ).hexdigest()[:24]
        return [
            {
                "block_id": f"mwgenerated_appendix_{identity}_{page['page_number']:03d}",
                "block_type": "appendix_image",
                "attachment_kind": "assessment_instrument_page",
                "instrument_id": self.instrument_id,
                "title": self.title,
                "alt_text": (
                    f"{self.title}原始附件第{page['page_number']}页，"
                    f"共{len(self.pages)}页"
                ),
                "body_order": body_order_start + index,
                "source_kind": "medical_writing_assessment_instrument",
                "source_locator": (
                    "generated:medical_writing_assessment_instrument:"
                    f"{self.instrument_id}:{self.source_pdf_sha256}:"
                    f"page:{page['page_number']}"
                ),
                "source_filename": self.original_filename,
                "source_pdf_sha256": self.source_pdf_sha256,
                "page_number": page["page_number"],
                "page_count": len(self.pages),
                "render_dpi": self.render_dpi,
                "media_type": "image/png",
                "image_base64": page["image_base64"],
                "image_sha256": page["image_sha256"],
                "pixel_width": page["pixel_width"],
                "pixel_height": page["pixel_height"],
                "page_width_points": page["page_width_points"],
                "page_height_points": page["page_height_points"],
                "editable": False,
                "indexed": False,
                "render_contract_version": (
                    "medical_writing_assessment_instrument_appendix_v1"
                ),
            }
            for index, page in enumerate(self.pages)
        ]


def render_instrument_pdf_appendix(
    pdf_bytes: bytes,
    *,
    instrument_id: str,
    title: str,
    original_filename: str,
    dpi: int = DEFAULT_RENDER_DPI,
) -> RenderedInstrumentAppendix:
    instrument_id = _normalized_identity(instrument_id)
    title = title.strip()
    original_filename = original_filename.strip()
    if not instrument_id or not title or not original_filename:
        raise MedicalWritingInstrumentAppendixError(
            "instrument identity, title, and original filename are required"
        )
    if dpi < MIN_RENDER_DPI or dpi > 600:
        raise MedicalWritingInstrumentAppendixError(
            f"instrument appendix render DPI must be {MIN_RENDER_DPI}-600"
        )
    if not pdf_bytes.startswith(b"%PDF-"):
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix must be a readable PDF"
        )
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix PDF exceeds the 50 MB limit"
        )
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise MedicalWritingInstrumentAppendixError(
            "pypdfium2 5.12.1 is required to render instrument appendices"
        ) from exc

    try:
        document = pdfium.PdfDocument(pdf_bytes)
        page_count = len(document)
    except Exception as exc:
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix PDF cannot be opened"
        ) from exc
    if page_count < 1 or page_count > MAX_PAGES:
        raise MedicalWritingInstrumentAppendixError(
            f"instrument appendix PDF must contain 1-{MAX_PAGES} pages"
        )

    pages: list[dict[str, Any]] = []
    source_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    scale = dpi / 72.0
    try:
        for page_index in range(page_count):
            page = document[page_index]
            width_points, height_points = page.get_size()
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(
                output,
                format="PNG",
                dpi=(dpi, dpi),
                optimize=False,
                compress_level=6,
            )
            payload = output.getvalue()
            pages.append(
                {
                    "page_number": page_index + 1,
                    "image_base64": base64.b64encode(payload).decode("ascii"),
                    "image_sha256": hashlib.sha256(payload).hexdigest(),
                    "pixel_width": image.width,
                    "pixel_height": image.height,
                    "page_width_points": round(float(width_points), 3),
                    "page_height_points": round(float(height_points), 3),
                }
            )
    except Exception as exc:
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix PDF page rendering failed"
        ) from exc
    finally:
        try:
            document.close()
        except Exception:
            pass

    return RenderedInstrumentAppendix(
        instrument_id=instrument_id,
        title=title,
        original_filename=original_filename,
        source_pdf_sha256=source_sha256,
        render_dpi=dpi,
        pages=tuple(pages),
    )


def validate_instrument_appendix_block(block: dict[str, Any]) -> None:
    if block.get("block_type") != "appendix_image":
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix block type is invalid"
        )
    if block.get("attachment_kind") != "assessment_instrument_page":
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix attachment kind is invalid"
        )
    block_id = str(block.get("block_id") or "")
    if not block_id.startswith("mwgenerated_appendix_"):
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix block identity is invalid"
        )
    if block.get("source_kind") != "medical_writing_assessment_instrument":
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix provenance is invalid"
        )
    if not str(block.get("source_locator") or "").startswith(
        "generated:medical_writing_assessment_instrument:"
    ):
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix source locator is invalid"
        )
    if block.get("editable") is not False or block.get("indexed") is not False:
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix pages must remain immutable and unindexed"
        )
    if block.get("render_contract_version") != (
        "medical_writing_assessment_instrument_appendix_v1"
    ):
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix render contract is invalid"
        )
    if str(block.get("media_type") or "") != "image/png":
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix pages must use PNG"
        )
    dpi = block.get("render_dpi")
    if isinstance(dpi, bool) or not isinstance(dpi, int) or dpi < MIN_RENDER_DPI:
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix page DPI is below the required minimum"
        )
    page_number = block.get("page_number")
    page_count = block.get("page_count")
    if (
        isinstance(page_number, bool)
        or not isinstance(page_number, int)
        or isinstance(page_count, bool)
        or not isinstance(page_count, int)
        or page_number < 1
        or page_count < page_number
    ):
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix page numbering is invalid"
        )
    try:
        image_bytes = base64.b64decode(
            str(block.get("image_base64") or ""), validate=True
        )
    except ValueError as exc:
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix PNG is not valid base64"
        ) from exc
    if not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix image signature is invalid"
        )
    if hashlib.sha256(image_bytes).hexdigest() != block.get("image_sha256"):
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix image hash does not match its payload"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", str(block.get("source_pdf_sha256") or "")):
        raise MedicalWritingInstrumentAppendixError(
            "instrument appendix source PDF hash is invalid"
        )


def _normalized_identity(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    return normalized[:120]
