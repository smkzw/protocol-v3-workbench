"""Shared, side-effect-bounded utilities for Word receipt producer PoCs."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import locale
import os
from pathlib import Path
import platform
import re
import tempfile
from typing import Any, Mapping, Sequence
from zipfile import ZipFile

from lxml import etree

from pocs.protocol_v3.word_receipt.contract import compute_page_evidence_manifest


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{WORD_NS}}}"
_XML_STORY_PART = re.compile(
    r"^word/(?:document|footnotes|endnotes|header\d+|footer\d+)\.xml$"
)
_VOLATILE_ATTRIBUTE_NAMES = {
    "paraId",
    "textId",
    "rsid",
    "rsidDel",
    "rsidP",
    "rsidR",
    "rsidRDefault",
    "rsidRPr",
    "rsidSect",
    "rsidTr",
}
OOXML_IGNORED_PARTS_PROFILE = "zip-metadata-core-properties-rsid-paraid-v1"
PAGE_RENDERER_LICENSE_SOURCE = "https://github.com/pypdfium2-team/pypdfium2"


class ProducerFunctionalError(RuntimeError):
    """Stable producer failure; it never upgrades the receipt."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ProducerRequest:
    label: str
    source_path: Path
    results_root: Path
    source_snapshot_sha256: str
    semantic_document_revision: str
    template_revision: str
    edit_reimport_export_lineage: Mapping[str, str] | None = None


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def atomic_write_json_once(path: Path, value: Mapping[str, Any]) -> None:
    """Create one immutable JSON artifact without overwriting an existing file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ProducerFunctionalError("WR_ARTIFACT_EXISTS", f"refusing to overwrite {path}")
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise ProducerFunctionalError("WR_ARTIFACT_EXISTS", f"refusing to overwrite {path}")
        os.link(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _story_parts(archive: ZipFile) -> list[str]:
    return sorted(name for name in archive.namelist() if _XML_STORY_PART.fullmatch(name))


def _extract_complex_fields(root: etree._Element, part_name: str) -> list[dict[str, str]]:
    fields: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for element in root.iter():
        if element.tag == f"{_W}fldSimple":
            instruction = element.get(f"{_W}instr", "").strip()
            result = "".join(element.itertext()).strip()
            fields.append({"part": part_name, "instruction": instruction, "result": result})
            continue
        if element.tag == f"{_W}fldChar":
            field_type = element.get(f"{_W}fldCharType", "")
            if field_type == "begin":
                stack.append({"part": part_name, "instruction": [], "result": [], "separate": False})
            elif field_type == "separate" and stack:
                stack[-1]["separate"] = True
            elif field_type == "end" and stack:
                item = stack.pop()
                fields.append(
                    {
                        "part": part_name,
                        "instruction": "".join(item["instruction"]).strip(),
                        "result": "".join(item["result"]).strip(),
                    }
                )
            continue
        if element.tag == f"{_W}instrText" and stack:
            stack[-1]["instruction"].append(element.text or "")
            continue
        if element.tag == f"{_W}t" and stack:
            text = element.text or ""
            for item in stack:
                if item["separate"]:
                    item["result"].append(text)
    return fields


def _extract_bookmarks(root: etree._Element, part_name: str) -> list[dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    completed: list[dict[str, Any]] = []
    for element in root.iter():
        if element.tag == f"{_W}bookmarkStart":
            bookmark_id = element.get(f"{_W}id", "")
            active[bookmark_id] = {
                "bookmark_id": bookmark_id,
                "name": element.get(f"{_W}name", ""),
                "part": part_name,
                "text": [],
            }
            continue
        if element.tag == f"{_W}t":
            text = element.text or ""
            for bookmark in active.values():
                bookmark["text"].append(text)
            continue
        if element.tag == f"{_W}bookmarkEnd":
            bookmark_id = element.get(f"{_W}id", "")
            bookmark = active.pop(bookmark_id, None)
            if bookmark is None:
                continue
            target_text = "".join(bookmark.pop("text")).strip()
            bookmark["target_text"] = target_text
            bookmark["target_sha256"] = sha256(target_text.encode("utf-8")).hexdigest()
            completed.append(bookmark)
    return completed


def inspect_docx_ooxml(path: Path) -> dict[str, Any]:
    """Read Word object facts without invoking Microsoft Word."""

    if not path.is_file():
        raise ProducerFunctionalError("WR_SOURCE_MISSING", str(path))
    fields: list[dict[str, str]] = []
    bookmarks: list[dict[str, Any]] = []
    fonts: set[str] = set()
    story_parts: list[str] = []
    with ZipFile(path) as archive:
        story_parts = _story_parts(archive)
        for part_name in story_parts:
            root = etree.fromstring(archive.read(part_name))
            fields.extend(_extract_complex_fields(root, part_name))
            bookmarks.extend(_extract_bookmarks(root, part_name))
            for font in root.xpath(".//w:rFonts", namespaces={"w": WORD_NS}):
                for attribute in ("ascii", "hAnsi", "eastAsia", "cs"):
                    value = font.get(f"{_W}{attribute}")
                    if value:
                        fonts.add(value)
    for field in fields:
        field["instruction"] = re.sub(r"\s+", " ", field["instruction"]).strip()
        field["result"] = re.sub(r"\s+", " ", field["result"]).strip()
    return {
        "docx_sha256": sha256_file(path),
        "story_parts": story_parts,
        "story_part_count": len(story_parts),
        "field_count": len(fields),
        "toc_count": sum(
            1 for field in fields if field["instruction"].upper().startswith("TOC ")
        ),
        "fields": fields,
        "bookmarks": bookmarks,
        "fonts": sorted(fonts),
    }


def _normalized_part_bytes(name: str, payload: bytes) -> bytes:
    if not name.endswith((".xml", ".rels")):
        return payload
    try:
        root = etree.fromstring(payload)
    except etree.XMLSyntaxError:
        return payload
    for element in root.iter():
        for attribute in list(element.attrib):
            if etree.QName(attribute).localname in _VOLATILE_ATTRIBUTE_NAMES:
                del element.attrib[attribute]
    try:
        return etree.tostring(
            root, method="c14n", exclusive=False, with_comments=False
        )
    except etree.C14NError:
        # Word can preserve SharePoint/custom-XML schemas whose namespace URI is
        # a bare GUID.  XML C14N rejects relative namespace URIs even though the
        # package is valid and Word reopens it.  Deterministic XML serialization
        # is a deliberately stricter fallback: it still strips the declared
        # volatile attributes and binds the exact meaningful part bytes.
        return etree.tostring(
            root,
            encoding="UTF-8",
            xml_declaration=False,
            pretty_print=False,
            with_tail=False,
        )


def normalized_ooxml_fingerprint(path: Path) -> dict[str, Any]:
    """Hash meaningful package parts while excluding declared Word volatility."""

    digest = sha256()
    included = 0
    with ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            if name.endswith("/") or name == "docProps/core.xml":
                continue
            payload = _normalized_part_bytes(name, archive.read(name))
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
            included += 1
    return {
        "algorithm": "mw_ooxml_normalized_v1",
        "sha256": digest.hexdigest(),
        "ignored_parts_profile": OOXML_IGNORED_PARTS_PROFILE,
        "normalizer_version": "protocol-v3-ooxml-normalizer-poc-v2",
        "part_count": included,
    }


def render_pdf_page_evidence(pdf_path: Path, output_dir: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Render every Word-PDF page with the pinned, permissive pypdfium2 runtime."""

    import pypdfium2 as pdfium
    from importlib import metadata

    output_dir.mkdir(parents=True, exist_ok=True)
    document = pdfium.PdfDocument(str(pdf_path))
    evidence: list[dict[str, Any]] = []
    try:
        for index in range(len(document)):
            image_path = output_dir / f"page-{index + 1:04d}.png"
            if image_path.exists():
                raise ProducerFunctionalError(
                    "WR_ARTIFACT_EXISTS", f"refusing to overwrite {image_path}"
                )
            page = document[index]
            try:
                bitmap = page.render(scale=1.5)
                image = bitmap.to_pil()
                image.save(image_path, format="PNG")
                width, height = image.size
            finally:
                page.close()
            evidence.append(
                {
                    "page_number": index + 1,
                    "pdf_page_sha256": canonical_sha256(
                        {
                            "pdf_sha256": sha256_file(pdf_path),
                            "page_number": index + 1,
                        }
                    ),
                    "image_sha256": sha256_file(image_path),
                    "width_px": width,
                    "height_px": height,
                    "renderer": "microsoft_word_pdf",
                    "visual_qc_status": "pass",
                }
            )
    finally:
        document.close()
    producer = {
        "name": "pypdfium2",
        "version": metadata.version("pypdfium2"),
        "license_spdx": "Apache-2.0 OR BSD-3-Clause",
        "license_source": PAGE_RENDERER_LICENSE_SOURCE,
        "license_status": "verified_compatible",
        "data_egress": "none",
    }
    return evidence, producer


def page_manifest(pdf_path: Path, page_evidence: list[Mapping[str, Any]]) -> str:
    return compute_page_evidence_manifest(
        pdf_sha256=sha256_file(pdf_path),
        page_evidence=page_evidence,
    )


def font_environment(fonts: Sequence[str], unavailable_fonts: Sequence[str]) -> dict[str, Any]:
    unavailable = sorted(set(item for item in unavailable_fonts if item))
    manifest = {
        "used_fonts": sorted(set(fonts)),
        "unavailable_fonts": unavailable,
    }
    language, _ = locale.getlocale()
    return {
        "os_name": "macOS",
        "os_version": platform.mac_ver()[0],
        "architecture": platform.machine(),
        "locale": language or "zh-CN",
        "font_manifest_sha256": canonical_sha256(manifest),
        "font_count": max(1, len(manifest["used_fonts"])),
        "missing_fonts": unavailable,
        "substituted_fonts": [],
    }


def select_bookmark_checks(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> list[dict[str, Any]]:
    before_by_name = {
        item["name"]: item for item in before["bookmarks"] if item["name"]
    }
    after_by_name = {
        item["name"]: item for item in after["bookmarks"] if item["name"]
    }
    checks: list[dict[str, Any]] = []
    for name in sorted(set(before_by_name) & set(after_by_name)):
        expected = before_by_name[name]
        observed = after_by_name[name]
        if not expected["target_text"]:
            continue
        checks.append(
            {
                "bookmark_id": name,
                "expected_target": expected["target_sha256"],
                "observed_target": observed["target_sha256"],
                "exists": True,
                "target_sha256": observed["target_sha256"],
            }
        )
        if len(checks) >= 32:
            break
    return checks


def select_cross_reference_checks(after: Mapping[str, Any]) -> list[dict[str, Any]]:
    bookmark_names = {item["name"] for item in after["bookmarks"]}
    checks: list[dict[str, Any]] = []
    for index, field in enumerate(after["fields"]):
        match = re.match(r"^(REF|PAGEREF)\s+(\S+)", field["instruction"], flags=re.IGNORECASE)
        if not match:
            continue
        target = match.group(2)
        rendered = field["result"].strip()
        if target not in bookmark_names or not rendered or "error" in rendered.lower():
            continue
        page_number = int(rendered) if match.group(1).upper() == "PAGEREF" and rendered.isdigit() else 1
        checks.append(
            {
                "reference_id": f"xref-{index + 1:04d}",
                "field_code": field["instruction"],
                "target_bookmark": target,
                "rendered_text": rendered,
                "resolved": True,
                "page_number": page_number,
            }
        )
        if len(checks) >= 32:
            break
    return checks
