from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_document_exporter import (
    export_medical_writing_document_docx,
)
from services.api.app.medical_writing_legacy_reference_index import (
    build_legacy_reference_index,
)


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{WORD_NS}}}"
REAL_PROJECTS = (
    "proj_rux_03_002",
    "proj_d001",
    "proj_my008_pnh_3_01",
)


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{W}t"))


def _inspect_docx(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{W}body")
    if body is None:
        raise AssertionError("word/document.xml has no body")
    paragraphs = list(body.iter(f"{W}p"))
    texts = [_paragraph_text(paragraph).strip() for paragraph in paragraphs]
    headings = [index for index, text in enumerate(texts) if text == "参考文献"]
    bookmarks = {
        node.attrib.get(f"{W}name", "")
        for node in root.iter(f"{W}bookmarkStart")
        if node.attrib.get(f"{W}name", "")
    }
    citation_links = []
    for hyperlink in root.iter(f"{W}hyperlink"):
        anchor = hyperlink.attrib.get(f"{W}anchor", "")
        text = _paragraph_text(hyperlink)
        if anchor.startswith("_MWREF_"):
            citation_links.append({"text": text, "anchor": anchor})
    reference_rows = []
    if headings:
        for text in texts[headings[0] + 1 :]:
            if re.match(r"^\[\d+\]\s+", text):
                reference_rows.append(text)
    return {
        "reference_heading_count": len(headings),
        "reference_row_count": len(reference_rows),
        "citation_hyperlink_count": len(citation_links),
        "citation_link_numbers": [item["text"] for item in citation_links],
        "all_citation_anchors_resolve": all(
            item["anchor"] in bookmarks for item in citation_links
        ),
        "reference_rows": reference_rows,
    }


def run(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    service = MedicalWritingDocumentService()
    results = []
    failures = []
    for project_id in REAL_PROJECTS:
        document = service.document_for_revision(project_id)
        index = build_legacy_reference_index(document)
        blocking = [issue for issue in index.issues if issue.blocking]
        export = export_medical_writing_document_docx(document, mode="draft_preview")
        docx_path = output_dir / f"{project_id}_legacy_reindexed.docx"
        docx_path.write_bytes(export.content)
        word = _inspect_docx(docx_path)
        expected_numbers = list(range(1, len(index.entries) + 1))
        actual_numbers = [
            int(match.group(1))
            for row in word["reference_rows"]
            if (match := re.match(r"^\[(\d+)\]", row))
        ]
        project_failures = []
        if not index.entries:
            project_failures.append("no imported bibliography entries")
        if not index.occurrences:
            project_failures.append("no imported in-text citation occurrences")
        if blocking:
            project_failures.append(
                "blocking issues: " + ",".join(issue.code for issue in blocking)
            )
        if word["reference_heading_count"] != 1:
            project_failures.append("reference heading was not regenerated exactly once")
        if word["reference_row_count"] != len(index.entries):
            project_failures.append("reference row count differs from indexed entries")
        if actual_numbers != expected_numbers:
            project_failures.append("reference numbering is not contiguous from first occurrence")
        if not word["all_citation_anchors_resolve"]:
            project_failures.append("one or more citation hyperlinks have no bookmark target")
        result = {
            "project_id": project_id,
            "protocol_id": document.protocol_id,
            "source_section_count": len(document.sections),
            "legacy_entry_count": len(index.entries),
            "legacy_occurrence_count": len(index.occurrences),
            "issue_codes": [issue.code for issue in index.issues],
            "blocking_issue_count": len(blocking),
            "source_digest": index.source_digest,
            "docx_path": str(docx_path),
            "docx_bytes": len(export.content),
            "export_metadata": {
                key: export.metadata.get(key)
                for key in (
                    "schema_version",
                    "document_id",
                    "project_id",
                    "protocol_id",
                    "protocol_version",
                    "mode",
                    "docx_sha256",
                    "citation_style",
                    "citation_count",
                    "reference_count",
                    "cited_reference_ids",
                    "uncited_reference_ids",
                    "legacy_reference_count",
                    "legacy_reference_source_sha256",
                    "reference_index_issue_codes",
                )
            },
            "word": word,
            "failures": project_failures,
            "passed": not project_failures,
        }
        results.append(result)
        failures.extend(f"{project_id}: {item}" for item in project_failures)
    report = {
        "schema_version": "medical_writing_legacy_reference_real_projects_qc_v1",
        "source_mode": "original_docx_reparse_read_only",
        "project_count": len(results),
        "results": results,
        "failures": failures,
        "passed": not failures and len(results) == len(REAL_PROJECTS),
    }
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
