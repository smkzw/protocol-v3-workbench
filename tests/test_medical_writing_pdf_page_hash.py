from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

pytest.importorskip("pypdfium2")
from services.api.app.medical_writing_pdf_page_hash import (  # noqa: E402
    CANONICAL_PDF_PAGE_HASH_CONTRACT,
    CANONICAL_PDF_PAGE_HASH_DPI,
    CANONICAL_PDF_PAGE_HASH_PIXEL_FORMAT,
    MedicalWritingPdfPageHashError,
    canonical_pdf_page_hash_manifest_sha256,
    canonical_pdf_page_hashes,
)
import services.api.app.medical_writing_pdf_page_hash as page_hash_module  # noqa: E402


def _pdf_bytes(page_count: int = 2) -> bytes:
    if page_count != 2:
        raise ValueError("the static test PDF contains exactly two pages")
    return base64.b64decode(
        "JVBERi0xLjMKJeLjz9MKMSAwIG9iago8PAovUHJvZHVjZXIgKHB5cGRmKQo+PgplbmRvYmoK"
        "MiAwIG9iago8PAovVHlwZSAvUGFnZXMKL0NvdW50IDIKL0tpZHMgWyA0IDAgUiA1IDAgUiBdCj4+CmVuZG9iagozIDAgb2JqCjw8Ci9UeXBlIC9DYXRhbG9nCi9QYWdlcyAyIDAgUgo+PgplbmRvYmoKNCAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Cj4+Ci9NZWRpYUJveCBbIDAuMCAwLjAgNTk1LjIgODQxLjkyIF0KL1BhcmVudCAyIDAgUgo+PgplbmRvYmoKNSAwIG9iago8PAovVHlwZSAvUGFnZQovUmVzb3VyY2VzIDw8Cj4+Ci9NZWRpYUJveCBbIDAuMCAwLjAgNTk1LjIgODQxLjkyIF0KL1BhcmVudCAyIDAgUgo+PgplbmRvYmoKeHJlZgowIDYKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDE1IDAwMDAwIG4gCjAwMDAwMDAwNTQgMDAwMDAgbiAKMDAwMDAwMDExOSAwMDAwMCBuIAowMDAwMDAwMTY4IDAwMDAwIG4gCjAwMDAwMDI2NyAwMDAwMCBuIAowMDAwMDAwMjY3IDAwMDAgbiAKdHJhaWxlcgo8PAovU2l6ZSA2Ci9Sb290IDMgMCBSCi9JbmZvIDEgMCBSCj4+CnN0YXJ0eHJlZgozNjYKJSVFT0YK"
    )


def test_canonical_page_hashes_are_deterministic_and_auditable() -> None:
    payload = _pdf_bytes()
    first = canonical_pdf_page_hashes(payload)
    second = canonical_pdf_page_hashes(payload)

    assert first == second
    assert len(first) == 2
    assert [page.page_number for page in first] == [1, 2]
    assert all(page.contract_version == CANONICAL_PDF_PAGE_HASH_CONTRACT for page in first)
    assert all(page.render_dpi == CANONICAL_PDF_PAGE_HASH_DPI for page in first)
    assert all(page.pixel_format == CANONICAL_PDF_PAGE_HASH_PIXEL_FORMAT for page in first)
    assert all(len(page.pdf_page_sha256) == 64 for page in first)
    assert all(page.pixel_width > 0 and page.pixel_height > 0 for page in first)
    assert all(page.row_stride_bytes >= page.pixel_width * 3 for page in first)
    assert first[0].pdf_page_sha256 != first[1].pdf_page_sha256


def test_manifest_is_order_sensitive_and_binds_full_pdf_hash() -> None:
    payload = _pdf_bytes()
    pages = canonical_pdf_page_hashes(payload)
    pdf_sha256 = hashlib.sha256(payload).hexdigest()
    first = canonical_pdf_page_hash_manifest_sha256(pages, pdf_sha256=pdf_sha256)
    second = canonical_pdf_page_hash_manifest_sha256(pages, pdf_sha256="a" * 64)

    assert first != second
    with pytest.raises(MedicalWritingPdfPageHashError, match="contiguous"):
        canonical_pdf_page_hash_manifest_sha256(
            (pages[1], pages[0]),
            pdf_sha256=pdf_sha256,
        )


@pytest.mark.parametrize("payload", [b"", b"not-a-pdf", b"%PDF-1.7\ntruncated"])
def test_malformed_pdf_fails_closed(payload: bytes) -> None:
    with pytest.raises(MedicalWritingPdfPageHashError):
        canonical_pdf_page_hashes(payload)


def test_non_bytes_input_fails_closed() -> None:
    with pytest.raises(MedicalWritingPdfPageHashError, match="PDF bytes"):
        canonical_pdf_page_hashes("%PDF-1.7")  # type: ignore[arg-type]


def test_renderer_version_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        page_hash_module.importlib.metadata,
        "version",
        lambda _name: "5.12.0",
    )
    with pytest.raises(MedicalWritingPdfPageHashError, match="requires pypdfium2==5.12.1"):
        canonical_pdf_page_hashes(_pdf_bytes())


def test_disposable_word_gate_fixture_is_hashable_when_present() -> None:
    fixture = Path("/tmp/mw_word_verify.nKvrBb/medical_writing_word_gate_fixture.pdf")
    if not fixture.exists():
        pytest.skip("disposable Word gate fixture is not present")
    pages = canonical_pdf_page_hashes(fixture.read_bytes())
    assert len(pages) == 2
    assert [page.page_number for page in pages] == [1, 2]
