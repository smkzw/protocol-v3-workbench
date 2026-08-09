from __future__ import annotations

import io
import zipfile

import pytest
from lxml import etree

from services.api.app.medical_writing_source_reference_reindex import (
    SourceReferenceTransformError,
    apply_source_reference_reindex,
    build_source_reference_manifest,
    decide_source_reference_reindex,
)


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _run(
    text: str,
    *,
    superscript: bool = False,
    style: str = "",
) -> str:
    properties = ""
    if superscript or style:
        properties = "<w:rPr>"
        if superscript:
            properties += '<w:vertAlign w:val="superscript"/>'
        if style:
            properties += f'<w:rStyle w:val="{style}"/>'
        properties += "</w:rPr>"
    return f"<w:r>{properties}<w:t>{text}</w:t></w:r>"


def _paragraph(content: str, *, style: str = "") -> str:
    properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{properties}{content}</w:p>"


def _bookmark(bookmark_id: int, name: str, content: str) -> str:
    return (
        f'<w:bookmarkStart w:id="{bookmark_id}" w:name="{name}"/>'
        f"{content}"
        f'<w:bookmarkEnd w:id="{bookmark_id}"/>'
    )


def _document_xml(body: str) -> str:
    return (
        f'{_XML_HEADER}<w:document xmlns:w="{_W_NS}">'
        f"<w:body>{body}<w:sectPr/></w:body></w:document>"
    )


def _story_xml(root_name: str, content: str) -> str:
    return f'{_XML_HEADER}<w:{root_name} xmlns:w="{_W_NS}">{content}</w:{root_name}>'


def _docx(
    document_body: str,
    *,
    extra_parts: dict[str, str | bytes] | None = None,
    numbering_xml: str = "",
    styles_xml: str = "",
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        package.writestr("word/document.xml", _document_xml(document_body))
        if numbering_xml:
            package.writestr("word/numbering.xml", numbering_xml)
        if styles_xml:
            package.writestr("word/styles.xml", styles_xml)
        for name, payload in (extra_parts or {}).items():
            package.writestr(name, payload)
    return output.getvalue()


def _reference_section(*entries: str) -> str:
    return _paragraph(_run("参考文献"), style="Heading1") + "".join(
        _paragraph(_run(entry)) for entry in entries
    )


def _styles_xml() -> str:
    return (
        f'{_XML_HEADER}<w:styles xmlns:w="{_W_NS}">'
        '<w:style w:type="paragraph" w:styleId="BaseHeading1">'
        '<w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="CustomReference">'
        '<w:name w:val="参考文献标题"/><w:basedOn w:val="BaseHeading1"/>'
        "</w:style>"
        '<w:style w:type="paragraph" w:styleId="CustomAppendix">'
        '<w:name w:val="自定义附录标题"/><w:basedOn w:val="BaseHeading1"/>'
        "</w:style>"
        "</w:styles>"
    )


def _table_row(number: str, text: str) -> str:
    return (
        "<w:tr><w:tc>"
        + _paragraph(_run(number))
        + "</w:tc><w:tc>"
        + _paragraph(_run(text))
        + "</w:tc></w:tr>"
    )


def _table(*rows: str) -> str:
    return "<w:tbl>" + "".join(rows) + "</w:tbl>"


def _issue_codes(manifest) -> list[str]:
    return [issue.code for issue in manifest.issues]


def _parts(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload), "r") as package:
        return {name: package.read(name) for name in package.namelist()}


def _root(payload: bytes, part_name: str = "word/document.xml"):
    from lxml import etree

    return etree.fromstring(_parts(payload)[part_name])


def test_scans_split_run_superscript_multi_citations_ranges_and_table_order():
    body = (
        _paragraph(
            _run("证据")
            + _run("[1,", superscript=True)
            + _run("3-4]", superscript=True)
        )
        + (
            "<w:tbl><w:tr><w:tc>"
            + _paragraph(_run("表格证据") + _run("[2]", superscript=True))
            + "</w:tc></w:tr></w:tbl>"
        )
        + _reference_section(
            "[1] First.",
            "[2] Second.",
            "[3] Third.",
            "[4] Fourth.",
            "[5] Uncited.",
        )
    )

    manifest = build_source_reference_manifest(_docx(body))
    decision = decide_source_reference_reindex(manifest)

    assert [item.source_numbers for item in manifest.citations] == [
        (1, 3, 4),
        (2,),
    ]
    assert "/w:tbl/" in manifest.citations[1].locator
    assert decision.action == "apply"
    assert decision.ordered_source_numbers == (1, 3, 4, 2, 5)
    assert decision.number_mapping == ((1, 1), (3, 2), (4, 3), (2, 4), (5, 5))
    assert decision.uncited_source_numbers == (5,)
    assert "uncited_reference_entry" in _issue_codes(manifest)


def test_keeps_repeated_same_number_citations_as_distinct_locators():
    body = _paragraph(
        _run("第一处")
        + _run("[1]", superscript=True)
        + _run("，第二处")
        + _run("[1]", superscript=True)
    ) + _reference_section("[1] First.")

    manifest = build_source_reference_manifest(_docx(body))

    assert [item.source_numbers for item in manifest.citations] == [(1,), (1,)]
    assert manifest.citations[0].locator != manifest.citations[1].locator
    assert decide_source_reference_reindex(manifest).ordered_source_numbers == (1,)


def test_scans_internal_anchor_and_ref_and_hyperlink_fields_but_excludes_other_fields():
    linked_reference = _bookmark(7, "_RefOne", _run("[1] First."))
    hyperlink = (
        '<w:hyperlink w:anchor="_RefOne">'
        + _run("[1]", superscript=True)
        + "</w:hyperlink>"
    )
    simple_ref = (
        '<w:fldSimple w:instr=" REF _RefOne \\h ">' + _run("[1]") + "</w:fldSimple>"
    )
    complex_hyperlink = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText> HYPERLINK \\l "_RefOne" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + _run("[1]")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    excluded_fields = (
        '<w:fldSimple w:instr=" SEQ Table \\* ARABIC ">'
        + _run("[99]")
        + "</w:fldSimple>"
        '<w:fldSimple w:instr=" PAGEREF _Toc1 \\h ">' + _run("[98]") + "</w:fldSimple>"
        '<w:fldSimple w:instr=" TOC \\o &quot;1-3&quot; \\h ">'
        + _run("[97]")
        + "</w:fldSimple>"
    )
    body = (
        _paragraph(hyperlink)
        + _paragraph(simple_ref)
        + _paragraph(complex_hyperlink)
        + _paragraph(excluded_fields)
        + _paragraph(_run("参考文献"), style="Heading1")
        + _paragraph(linked_reference)
    )

    manifest = build_source_reference_manifest(_docx(body))
    decision = decide_source_reference_reindex(manifest)

    assert [item.binding_kind for item in manifest.citations] == [
        "internal_hyperlink",
        "simple_field",
        "complex_field",
    ]
    assert all(item.source_numbers == (1,) for item in manifest.citations)
    assert [field.field_kind for field in manifest.fields] == [
        "REF",
        "HYPERLINK",
        "SEQ",
        "PAGEREF",
        "TOC",
    ]
    assert decision.action == "apply"
    assert "missing_reference_entry" not in _issue_codes(manifest)


def test_preserves_resolved_manager_field_but_blocks_unbalanced_complex_field():
    body = (
        _paragraph(
            '<w:fldSimple w:instr=" ADDIN ZOTERO_ITEM CSL_CITATION ">'
            + _run("[1]")
            + "</w:fldSimple>"
        )
        + _paragraph(
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText> REF _RefOne \\h </w:instrText></w:r>"
        )
        + _reference_section("[1] First.")
    )

    manifest = build_source_reference_manifest(_docx(body))
    decision = decide_source_reference_reindex(manifest)

    assert "citation_manager_field_preserved" in _issue_codes(manifest)
    assert "citation_manager_result_unresolved" not in _issue_codes(manifest)
    assert "unbalanced_field" in _issue_codes(manifest)
    assert decision.action == "block"


def test_plain_candidate_preserves_with_notice_and_iga_and_note_markers_are_excluded():
    footnote_story = _story_xml(
        "footnotes",
        (
            '<w:footnote w:id="1">'
            + _paragraph(
                '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
                '<w:footnoteReference w:id="1"/><w:t>[9]</w:t></w:r>'
                + _run(" note evidence ")
                + _run("[1]", superscript=True)
            )
            + "</w:footnote>"
        ),
    )
    body = _paragraph(_run("IGA[2,3]及普通[1]")) + _reference_section(
        "[1] First.", "[2] Second.", "[3] Third."
    )

    manifest = build_source_reference_manifest(
        _docx(body, extra_parts={"word/footnotes.xml": footnote_story})
    )
    decision = decide_source_reference_reindex(manifest)

    assert [(item.raw_text, item.ambiguous) for item in manifest.citations] == [
        ("[1]", True),
        ("[1]", False),
    ]
    assert all(item.source_numbers != (2, 3) for item in manifest.citations)
    assert all(item.source_numbers != (9,) for item in manifest.citations)
    assert manifest.citations[1].story_kind == "footnotes"
    assert decision.action == "preserve_with_notice"
    assert "ambiguous_plain_citation_candidate" in _issue_codes(manifest)


def test_duplicate_and_missing_reference_numbers_block_without_guessing():
    duplicate = build_source_reference_manifest(
        _docx(
            _paragraph(_run("[1]", superscript=True))
            + _reference_section("[1] First.", "1、Different.")
        )
    )
    missing = build_source_reference_manifest(
        _docx(
            _paragraph(_run("[1-3]", superscript=True))
            + _reference_section("[1] First.", "[3] Third.")
        )
    )

    assert decide_source_reference_reindex(duplicate).action == "block"
    assert "duplicate_reference_number" in _issue_codes(duplicate)
    assert decide_source_reference_reindex(missing).action == "block"
    assert "missing_reference_number" in _issue_codes(missing)
    assert "missing_reference_entry" in _issue_codes(missing)


def test_allocates_bookmarks_after_existing_1001_and_uses_unique_names():
    body = (
        _paragraph(_bookmark(1001, "_MWREF_existing", _run("Existing bookmark")))
        + _paragraph(_run("[1]", superscript=True))
        + _reference_section("[1] First.")
    )

    manifest = build_source_reference_manifest(_docx(body))
    decision = decide_source_reference_reindex(manifest)

    assert decision.action == "apply"
    assert len(decision.bookmark_allocations) == 1
    allocation = decision.bookmark_allocations[0]
    assert allocation.bookmark_id == 1002
    assert allocation.bookmark_name != "_MWREF_existing"
    assert allocation.bookmark_name.startswith("_MWREF_")


def test_scans_headers_footers_endnotes_and_preserves_story_order():
    body = _paragraph(_run("[2]", superscript=True)) + _reference_section(
        "[1] First.",
        "[2] Second.",
        "[3] Third.",
    )
    extras = {
        "word/header1.xml": _story_xml(
            "hdr",
            _paragraph(_run("[1]", superscript=True)),
        ),
        "word/footer1.xml": _story_xml(
            "ftr",
            _paragraph(_run("[3]", superscript=True)),
        ),
        "word/endnotes.xml": _story_xml(
            "endnotes",
            '<w:endnote w:id="1">'
            + _paragraph(_run("[2]", superscript=True))
            + "</w:endnote>",
        ),
    }

    manifest = build_source_reference_manifest(_docx(body, extra_parts=extras))
    decision = decide_source_reference_reindex(manifest)

    assert manifest.story_parts == (
        "word/document.xml",
        "word/header1.xml",
        "word/footer1.xml",
        "word/endnotes.xml",
    )
    assert [item.story_kind for item in manifest.citations] == [
        "document",
        "header",
        "footer",
        "endnotes",
    ]
    assert decision.ordered_source_numbers == (2, 1, 3)


def test_word_numbered_reference_groups_and_continuation_paragraph_are_recognized():
    numbering = (
        f'{_XML_HEADER}<w:numbering xmlns:w="{_W_NS}">'
        '<w:abstractNum w:abstractNumId="4">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/>'
        '<w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>'
        "</w:abstractNum>"
        '<w:num w:numId="9"><w:abstractNumId w:val="4"/></w:num>'
        "</w:numbering>"
    )
    numbered_paragraph = (
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/>'
        '<w:numId w:val="9"/></w:numPr></w:pPr>' + _run("First reference.") + "</w:p>"
    )
    body = (
        _paragraph(_run("[1]", superscript=True))
        + _paragraph(_run("References"), style="Heading1")
        + numbered_paragraph
        + _paragraph(_run("Continuation with DOI."))
    )

    manifest = build_source_reference_manifest(_docx(body, numbering_xml=numbering))

    assert len(manifest.reference_groups) == 1
    group = manifest.reference_groups[0]
    assert group.source_number == 1
    assert group.raw_text == "First reference.\nContinuation with DOI."
    assert len(group.paragraph_indexes) == 2
    decision = decide_source_reference_reindex(manifest)
    assert decision.action == "apply"

    first = apply_source_reference_reindex(
        _docx(body, numbering_xml=numbering),
        manifest,
        decision,
    )
    second_manifest = build_source_reference_manifest(first)
    second = apply_source_reference_reindex(
        first,
        second_manifest,
        decide_source_reference_reindex(second_manifest),
    )
    assert second == first


def test_manifest_and_decision_are_deterministic_across_repeated_runs():
    payload = _docx(
        _paragraph(_run("[2]", superscript=True))
        + _reference_section("[1] First.", "[2] Second.")
    )

    first_manifest = build_source_reference_manifest(payload)
    second_manifest = build_source_reference_manifest(payload)
    first_decision = decide_source_reference_reindex(first_manifest)
    second_decision = decide_source_reference_reindex(second_manifest)

    assert first_manifest == second_manifest
    assert first_decision == second_decision
    assert first_manifest.source_digest == second_manifest.source_digest


def test_transforms_old_18_to_17_with_split_runs_repeated_citations_and_zip_fidelity():
    citation_paragraphs = "".join(
        _paragraph(_run(f"证据{number}") + _run(f"[{number}]", superscript=True))
        for number in range(1, 17)
    )
    repeated_old_18 = _paragraph(
        _run("第一处")
        + _run("[18", superscript=True)
        + _run("]", superscript=True)
        + _run("，第二处")
        + _run("[18]", superscript=True)
    )
    old_18_hyperlink = _paragraph(
        '<w:hyperlink w:anchor="_Old18">'
        + _run("[18]", superscript=True)
        + "</w:hyperlink>"
    )
    old_19_ref = _paragraph(
        '<w:fldSimple w:instr=" REF _Old19 \\h ">'
        + _run("[19]", superscript=True)
        + "</w:fldSimple>"
    )
    excluded_fields = _paragraph(
        '<w:fldSimple w:instr=" SEQ Table \\* ARABIC ">'
        + _run("[99]")
        + "</w:fldSimple>"
        '<w:fldSimple w:instr=" PAGEREF _Toc1 \\h ">' + _run("[98]") + "</w:fldSimple>"
        '<w:fldSimple w:instr=" TOC \\o &quot;1-3&quot; \\h ">'
        + _run("[97]")
        + "</w:fldSimple>"
    )
    reference_entries = []
    for number in range(1, 20):
        content = _run(f"[{number}] Reference {number}.")
        if number == 18:
            content = _bookmark(18, "_Old18", content)
        elif number == 19:
            content = _bookmark(19, "_Old19", content)
        reference_entries.append(_paragraph(content))
    body = (
        _paragraph(_bookmark(1001, "_MWREF_existing", _run("Existing")))
        + citation_paragraphs
        + repeated_old_18
        + old_18_hyperlink
        + old_19_ref
        + _paragraph(_run("普通临床记号 IGA[2,3] 保持不变"))
        + excluded_fields
        + _paragraph(_run("参考文献"), style="Heading1")
        + "".join(reference_entries)
    )
    untouched_parts = {
        "[Content_Types].xml": b"<Types>opaque-content-types</Types>",
        "word/_rels/document.xml.rels": b"<Relationships>opaque-rels</Relationships>",
        "word/media/image1.png": b"\x89PNG\r\n\x1a\nopaque-image",
        "customXml/item1.xml": b"<root>opaque-custom-part</root>",
    }
    payload = _docx(body, extra_parts=untouched_parts)
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)

    assert decision.action == "apply"
    assert dict(decision.number_mapping)[18] == 17
    assert dict(decision.number_mapping)[19] == 18
    assert dict(decision.number_mapping)[17] == 19
    transformed = apply_source_reference_reindex(payload, manifest, decision)

    before_parts = _parts(payload)
    after_parts = _parts(transformed)
    for part_name, expected in untouched_parts.items():
        assert before_parts[part_name] == expected
        assert after_parts[part_name] == expected

    transformed_manifest = build_source_reference_manifest(transformed)
    transformed_groups = {
        group.raw_text: group.source_number
        for group in transformed_manifest.reference_groups
    }
    assert transformed_groups["Reference 18."] == 17
    assert transformed_groups["Reference 19."] == 18
    assert transformed_groups["Reference 17."] == 19
    assert [item.raw_text for item in transformed_manifest.citations].count("[17]") == 3
    assert "[18]" in [item.raw_text for item in transformed_manifest.citations]

    document_root = _root(transformed)
    anchors = [
        node.get(f"{{{_W_NS}}}anchor")
        for node in document_root.iter(f"{{{_W_NS}}}hyperlink")
    ]
    allocation_18 = next(
        item for item in decision.bookmark_allocations if item.source_number == 18
    )
    allocation_19 = next(
        item for item in decision.bookmark_allocations if item.source_number == 19
    )
    assert allocation_18.bookmark_name in anchors
    simple_instructions = [
        node.get(f"{{{_W_NS}}}instr")
        for node in document_root.iter(f"{{{_W_NS}}}fldSimple")
    ]
    assert any(allocation_19.bookmark_name in value for value in simple_instructions)
    assert "普通临床记号 IGA[2,3] 保持不变" in "".join(
        node.text or "" for node in document_root.iter(f"{{{_W_NS}}}t")
    )
    excluded_results = {
        (node.get(f"{{{_W_NS}}}instr") or "").strip(): "".join(
            child.text or "" for child in node.iter(f"{{{_W_NS}}}t")
        )
        for node in document_root.iter(f"{{{_W_NS}}}fldSimple")
        if (node.get(f"{{{_W_NS}}}instr") or "").strip().split(maxsplit=1)[0]
        in {"SEQ", "PAGEREF", "TOC"}
    }
    assert excluded_results == {
        "SEQ Table \\* ARABIC": "[99]",
        "PAGEREF _Toc1 \\h": "[98]",
        'TOC \\o "1-3" \\h': "[97]",
    }
    bookmark_ids = [
        int(node.get(f"{{{_W_NS}}}id"))
        for node in document_root.iter(f"{{{_W_NS}}}bookmarkStart")
    ]
    assert 1001 in bookmark_ids
    assert allocation_18.bookmark_id > 1001
    assert len(bookmark_ids) == len(set(bookmark_ids))


def test_transforms_every_supported_story_part_and_normalizes_ranges():
    extras = {
        "word/header1.xml": _story_xml(
            "hdr",
            _paragraph(_run("[1-2]", superscript=True)),
        ),
        "word/footer1.xml": _story_xml(
            "ftr",
            _paragraph(_run("[1,2]", superscript=True)),
        ),
        "word/footnotes.xml": _story_xml(
            "footnotes",
            '<w:footnote w:id="1">'
            + _paragraph(_run("[1,2]", superscript=True))
            + "</w:footnote>",
        ),
        "word/endnotes.xml": _story_xml(
            "endnotes",
            '<w:endnote w:id="1">'
            + _paragraph(_run("[1-2]", superscript=True))
            + "</w:endnote>",
        ),
        "word/comments.xml": _story_xml(
            "comments",
            '<w:comment w:id="1">'
            + _paragraph(_run("[2,1]", superscript=True))
            + "</w:comment>",
        ),
    }
    body = _paragraph(_run("[2]", superscript=True)) + _reference_section(
        "[1] First.", "[2] Second."
    )
    payload = _docx(body, extra_parts=extras)
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)

    transformed = apply_source_reference_reindex(payload, manifest, decision)
    transformed_manifest = build_source_reference_manifest(transformed)

    assert decision.number_mapping == ((2, 1), (1, 2))
    assert {item.story_kind for item in transformed_manifest.citations} == {
        "document",
        "header",
        "footer",
        "footnotes",
        "endnotes",
        "comments",
    }
    assert all(
        item.raw_text in {"[1]", "[1,2]"} for item in transformed_manifest.citations
    )
    assert all(
        item.raw_text != "[1-2]" and item.raw_text != "[2,1]"
        for item in transformed_manifest.citations
    )


def test_rewrites_safe_complex_hyperlink_field_and_blocks_multi_target_field():
    linked_first = _bookmark(7, "_RefOne", _run("[1] First."))
    linked_second = _bookmark(8, "_RefTwo", _run("[2] Second."))
    complex_hyperlink = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText> HYPERLINK \\l "_RefTwo" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + _run("[2]", superscript=True)
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    body = (
        _paragraph(complex_hyperlink)
        + _paragraph(_run("[1]", superscript=True))
        + _paragraph(_run("参考文献"), style="Heading1")
        + _paragraph(linked_first)
        + _paragraph(linked_second)
    )
    payload = _docx(body)
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)

    transformed = apply_source_reference_reindex(payload, manifest, decision)
    transformed_root = _root(transformed)
    instruction = "".join(
        node.text or "" for node in transformed_root.iter(f"{{{_W_NS}}}instrText")
    )
    allocation = next(
        item for item in decision.bookmark_allocations if item.source_number == 2
    )
    assert allocation.bookmark_name in instruction
    assert build_source_reference_manifest(transformed).citations[0].raw_text == "[1]"

    multi_target = _docx(
        _paragraph(
            '<w:fldSimple w:instr=" REF _RefOne \\h ">'
            + _run("[1,2]", superscript=True)
            + "</w:fldSimple>"
        )
        + _paragraph(_run("参考文献"), style="Heading1")
        + _paragraph(linked_first)
        + _paragraph(linked_second)
    )
    multi_manifest = build_source_reference_manifest(multi_target)
    multi_decision = decide_source_reference_reindex(multi_manifest)
    assert multi_decision.action == "apply"
    with pytest.raises(
        SourceReferenceTransformError,
        match="cannot bind multiple references",
    ):
        apply_source_reference_reindex(
            multi_target,
            multi_manifest,
            multi_decision,
        )


def test_apply_rejects_notice_block_and_source_digest_or_locator_drift():
    notice_payload = _docx(
        _paragraph(_run("普通[1]")) + _reference_section("[1] First.")
    )
    notice_manifest = build_source_reference_manifest(notice_payload)
    notice_decision = decide_source_reference_reindex(notice_manifest)
    assert notice_decision.action == "preserve_with_notice"
    with pytest.raises(
        SourceReferenceTransformError, match="physical apply is forbidden"
    ):
        apply_source_reference_reindex(
            notice_payload,
            notice_manifest,
            notice_decision,
        )

    blocked_payload = _docx(
        _paragraph(
            '<w:fldSimple w:instr=" ADDIN ZOTERO_ITEM CSL_CITATION ">'
            + _run("unresolved author-year result")
            + "</w:fldSimple>"
        )
        + _reference_section("[1] First.")
    )
    blocked_manifest = build_source_reference_manifest(blocked_payload)
    blocked_decision = decide_source_reference_reindex(blocked_manifest)
    assert blocked_decision.action == "block"
    assert "citation_manager_result_unresolved" in _issue_codes(blocked_manifest)
    with pytest.raises(
        SourceReferenceTransformError, match="physical apply is forbidden"
    ):
        apply_source_reference_reindex(
            blocked_payload,
            blocked_manifest,
            blocked_decision,
        )

    source_payload = _docx(
        _paragraph(_run("[1]", superscript=True)) + _reference_section("[1] First.")
    )
    source_manifest = build_source_reference_manifest(source_payload)
    source_decision = decide_source_reference_reindex(source_manifest)
    drifted = _docx(
        _paragraph(_run("[1]", superscript=True)) + _reference_section("[1] Changed.")
    )
    with pytest.raises(
        SourceReferenceTransformError,
        match="digest or physical locators drifted",
    ):
        apply_source_reference_reindex(
            drifted,
            source_manifest,
            source_decision,
        )


def test_transform_is_idempotent_after_rescan_and_identity_decision():
    payload = _docx(
        _paragraph(_run("[2]", superscript=True))
        + _paragraph(_run("[1]", superscript=True))
        + _reference_section("[1] First.", "[2] Second.")
    )
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)
    first = apply_source_reference_reindex(payload, manifest, decision)
    second_manifest = build_source_reference_manifest(first)
    second_decision = decide_source_reference_reindex(second_manifest)
    second = apply_source_reference_reindex(
        first,
        second_manifest,
        second_decision,
    )

    assert second_decision.number_mapping == ((1, 1), (2, 2))
    assert second == first


def test_changed_automatic_reference_numbering_fails_closed():
    numbering = (
        f'{_XML_HEADER}<w:numbering xmlns:w="{_W_NS}">'
        '<w:abstractNum w:abstractNumId="4">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/>'
        '<w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>'
        "</w:abstractNum>"
        '<w:num w:numId="9"><w:abstractNumId w:val="4"/></w:num>'
        "</w:numbering>"
    )

    def numbered_reference(text: str) -> str:
        return (
            '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/>'
            '<w:numId w:val="9"/></w:numPr></w:pPr>' + _run(text) + "</w:p>"
        )

    payload = _docx(
        _paragraph(_run("[2]", superscript=True))
        + _paragraph(_run("[1]", superscript=True))
        + _paragraph(_run("参考文献"), style="Heading1")
        + numbered_reference("First.")
        + numbered_reference("Second."),
        numbering_xml=numbering,
    )
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)

    assert decision.number_mapping == ((2, 1), (1, 2))
    assert decision.action == "block"
    assert "automatic_reference_numbering_rebind_required" in [
        issue.code for issue in decision.issues
    ]
    with pytest.raises(
        SourceReferenceTransformError,
        match="physical apply is forbidden",
    ):
        apply_source_reference_reindex(payload, manifest, decision)


def test_reference_section_uses_inherited_heading_level_and_excludes_appendix_tables():
    body = (
        _paragraph(_run("证据") + _run("[1]", superscript=True))
        + _paragraph(_run("参考文献"), style="CustomReference")
        + _paragraph(_run("[1] True reference."))
        + _paragraph(_run("附录1 量表"), style="CustomAppendix")
        + _table(
            _table_row("1", "量表第一项"),
            _table_row("2", "量表第二项"),
        )
    )

    manifest = build_source_reference_manifest(_docx(body, styles_xml=_styles_xml()))

    assert [
        (group.source_number, group.raw_text) for group in manifest.reference_groups
    ] == [(1, "True reference.")]
    assert all(
        "/w:tbl/" not in locator
        for group in manifest.reference_groups
        for locator in group.locators
    )
    assert decide_source_reference_reindex(manifest).action == "apply"


def test_table_reference_rows_transform_idempotently_without_package_part_churn():
    body = (
        _paragraph(_run("先引") + _run("[2]", superscript=True))
        + _paragraph(_run("后引") + _run("[1]", superscript=True))
        + _paragraph(_run("参考文献"), style="CustomReference")
        + _table(
            _table_row("1", "First table reference."),
            _table_row("2、", "Second table reference."),
        )
        + _paragraph(_run("附录"), style="CustomAppendix")
        + _table(_table_row("1", "不是参考文献的量表行"))
    )
    payload = _docx(
        body,
        styles_xml=_styles_xml(),
        extra_parts={
            "customXml/item1.xml": b"<opaque/>",
            "word/media/image1.png": b"opaque-image",
        },
    )
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)

    assert [group.numbering_kind for group in manifest.reference_groups] == [
        "table_cell",
        "table_cell",
    ]
    assert decision.number_mapping == ((2, 1), (1, 2))
    transformed = apply_source_reference_reindex(payload, manifest, decision)
    rescanned = build_source_reference_manifest(transformed)
    second = apply_source_reference_reindex(
        transformed,
        rescanned,
        decide_source_reference_reindex(rescanned),
    )

    before = _parts(payload)
    after = _parts(transformed)
    assert set(after) == set(before)
    assert after["customXml/item1.xml"] == before["customXml/item1.xml"]
    assert after["word/media/image1.png"] == before["word/media/image1.png"]
    assert [group.source_number for group in rescanned.reference_groups] == [2, 1]
    assert [group.raw_text for group in rescanned.reference_groups] == [
        "First table reference.",
        "Second table reference.",
    ]
    assert second == transformed


def test_balanced_endnote_field_uses_visible_result_and_preserves_addin_package():
    manager_field = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        "<w:r><w:instrText> ADDIN EN.CITE &lt;EndNote&gt;&lt;Cite&gt;"
        '&lt;DisplayText&gt;&lt;style face="superscript"&gt;[9]&lt;/style&gt;'
        "&lt;/DisplayText&gt;&lt;/Cite&gt;&lt;/EndNote&gt; </w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + _run("[1]", superscript=True)
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    payload = _docx(
        _paragraph(manager_field) + _reference_section("[1] First."),
        extra_parts={"customXml/item1.xml": b"<manager-metadata/>"},
    )
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)

    assert [
        (item.binding_kind, item.source_numbers) for item in manifest.citations
    ] == [("manager_field", (1,))]
    assert "citation_manager_field_preserved" in _issue_codes(manifest)
    assert "citation_manager_metadata_conflict" in _issue_codes(manifest)
    assert decision.action == "apply"
    transformed = apply_source_reference_reindex(payload, manifest, decision)
    before_root = _root(payload)
    after_root = _root(transformed)
    assert etree.tostring(
        before_root.find(".//w:body/w:p[1]", {"w": _W_NS}), method="c14n"
    ) == etree.tostring(
        after_root.find(".//w:body/w:p[1]", {"w": _W_NS}), method="c14n"
    )
    assert _parts(transformed)["customXml/item1.xml"] == b"<manager-metadata/>"
    rescanned = build_source_reference_manifest(transformed)
    assert (
        apply_source_reference_reindex(
            transformed,
            rescanned,
            decide_source_reference_reindex(rescanned),
        )
        == transformed
    )


def test_manager_field_that_would_be_renumbered_returns_actionable_block():
    payload = _docx(
        _paragraph(
            '<w:fldSimple w:instr=" ADDIN ZOTERO_ITEM CSL_CITATION ">'
            + _run("[2]", superscript=True)
            + "</w:fldSimple>"
        )
        + _paragraph(_run("[1]", superscript=True))
        + _reference_section("[1] First.", "[2] Second.")
    )
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)

    assert decision.number_mapping == ((2, 1), (1, 2))
    assert decision.action == "block"
    assert "citation_manager_rebind_required" in [
        issue.code for issue in decision.issues
    ]
    assert "unsupported_citation_manager_field" not in [
        issue.code for issue in decision.issues
    ]


def test_same_reference_content_under_different_numbers_blocks_without_guessing():
    payload = _docx(
        _paragraph(_run("[1]", superscript=True))
        + _reference_section("[1] Same entry.", "[2] Same entry.")
    )
    manifest = build_source_reference_manifest(payload)

    assert decide_source_reference_reindex(manifest).action == "block"
    assert "duplicate_reference_content" in _issue_codes(manifest)


@pytest.mark.parametrize(
    ("instruction", "manager_kind"),
    [
        ("ADDIN EN.CITE opaque-endnote-data", "endnote"),
        ("ADDIN ZOTERO_ITEM CSL_CITATION opaque-zotero-data", "zotero"),
        ("ADDIN Mendeley Citation opaque-mendeley-data", "mendeley"),
    ],
)
def test_common_manager_fields_map_visible_numeric_results_without_rewriting(
    instruction,
    manager_kind,
):
    payload = _docx(
        _paragraph(
            f'<w:fldSimple w:instr=" {instruction} ">'
            + _run("[1]", superscript=True)
            + "</w:fldSimple>"
        )
        + _reference_section("[1] First.")
    )
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)

    manager = next(field for field in manifest.fields if field.unsupported_manager)
    assert manager.manager_kind == manager_kind
    assert manager.manager_result_numbers == (1,)
    assert decision.action == "apply"
    transformed = apply_source_reference_reindex(payload, manifest, decision)
    assert etree.tostring(
        _root(payload).find(".//w:body/w:p[1]", {"w": _W_NS}),
        method="c14n",
    ) == etree.tostring(
        _root(transformed).find(".//w:body/w:p[1]", {"w": _W_NS}),
        method="c14n",
    )


def test_unbalanced_manager_field_fails_closed_without_guessing_from_partial_result():
    payload = _docx(
        _paragraph(
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            "<w:r><w:instrText> ADDIN EN.CITE opaque </w:instrText></w:r>"
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + _run("[1]", superscript=True)
        )
        + _reference_section("[1] First.")
    )
    manifest = build_source_reference_manifest(payload)

    assert decide_source_reference_reindex(manifest).action == "block"
    assert "unbalanced_field" in _issue_codes(manifest)
    assert not [
        occurrence
        for occurrence in manifest.citations
        if occurrence.binding_kind == "manager_field"
    ]


def test_styles_part_is_source_bound_when_heading_boundary_depends_on_it():
    body = (
        _paragraph(_run("[1]", superscript=True))
        + _paragraph(_run("参考文献"), style="CustomReference")
        + _paragraph(_run("[1] First."))
        + _paragraph(_run("附录"), style="CustomAppendix")
    )
    payload = _docx(body, styles_xml=_styles_xml())
    manifest = build_source_reference_manifest(payload)
    decision = decide_source_reference_reindex(manifest)
    drifted_styles = _styles_xml().replace(
        '<w:outlineLvl w:val="0"/>',
        '<w:outlineLvl w:val="1"/>',
        1,
    )
    drifted = _docx(body, styles_xml=drifted_styles)

    with pytest.raises(
        SourceReferenceTransformError, match="digest or physical locators drifted"
    ):
        apply_source_reference_reindex(drifted, manifest, decision)
