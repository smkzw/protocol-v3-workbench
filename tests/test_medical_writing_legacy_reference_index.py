from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from packages.contracts.workbench_contracts import ProtocolDocument, ProtocolSection
from services.api.app.medical_writing_legacy_reference_index import (
    build_legacy_reference_index,
)


def _rich_text(*nodes: dict) -> dict:
    return {"type": "paragraph", "content": list(nodes)}


def _text(value: str, *, superscript: bool = False) -> dict:
    node = {"type": "text", "text": value}
    if superscript:
        node["marks"] = [{"type": "superscript"}]
    return node


def _document(
    *,
    body_nodes: tuple[dict, ...] = (),
    references: tuple[str, ...] = ("[1] First reference.",),
    project_id: str = "proj_legacy_reference_test",
    reference_heading: str = "参考文献",
) -> ProtocolDocument:
    document_id = "mwdoc_legacy_reference_test"
    body_blocks = [
        {
            "block_id": "body_1",
            "block_type": "paragraph",
            "text": "body",
            "source_locator": "docx:paragraph:1",
            "rich_text": _rich_text(*body_nodes),
        }
    ]
    reference_blocks = [
        {
            "block_id": f"reference_{index}",
            "block_type": "paragraph",
            "text": raw_text,
            "source_locator": f"docx:paragraph:{100 + index}",
        }
        for index, raw_text in enumerate(references, start=1)
    ]
    return ProtocolDocument(
        document_id=document_id,
        project_id=project_id,
        protocol_id="LEGACY-REFERENCE-TEST",
        version="V1.0",
        sections=[
            ProtocolSection(
                section_id="body_section",
                document_id=document_id,
                heading="研究设计",
                content_blocks=body_blocks,
            ),
            ProtocolSection(
                section_id="reference_section",
                document_id=document_id,
                heading=reference_heading,
                content_blocks=reference_blocks,
            ),
        ],
    )


def _issue(index, code: str):
    return [issue for issue in index.issues if issue.code == code]


def test_indexes_single_superscript_legacy_citation_and_preserves_source_fields():
    index = build_legacy_reference_index(
        _document(body_nodes=(_text("正文 "), _text("[1]", superscript=True)))
    )

    assert len(index.entries) == 1
    entry = index.entries[0]
    assert entry.reference_id.startswith("mwref_")
    assert len(entry.reference_id) == len("mwref_") + 20
    assert entry.raw_text == "[1] First reference."
    assert entry.source_number == 1
    assert entry.block_id == "reference_1"
    assert entry.source_locator == "docx:paragraph:101"
    assert entry.source_numbers == (1,)
    assert index.number_to_reference_id == {1: entry.reference_id}
    assert index.occurrences[0].source_numbers == (1,)
    assert index.occurrences[0].reference_ids == (entry.reference_id,)
    assert not index.issues


def test_expands_multiple_numbers_and_ranges_in_source_order():
    references = tuple(f"{number}. Reference {number}." for number in range(1, 8))
    index = build_legacy_reference_index(
        _document(
            body_nodes=(
                _text("[1,2]", superscript=True),
                _text(" and "),
                _text("[1-3,7]", superscript=True),
            ),
            references=references,
            reference_heading="References",
        )
    )

    assert [item.source_numbers for item in index.occurrences] == [
        (1, 2),
        (1, 2, 3, 7),
    ]
    assert index.occurrences[1].reference_ids == tuple(
        index.number_to_reference_id[number] for number in (1, 2, 3, 7)
    )
    assert {issue.source_number for issue in _issue(index, "uncited_entry")} == {4, 5, 6}


def test_ignores_plain_body_brackets_and_non_marker_superscript_text():
    index = build_legacy_reference_index(
        _document(
            body_nodes=(
                _text("IGA[2，3]"),
                _text(" IGA[1]", superscript=True),
                _text(" [1]"),
            )
        )
    )

    assert index.occurrences == ()
    assert [issue.code for issue in index.issues] == ["uncited_entry"]


def test_duplicate_reference_number_is_blocking():
    index = build_legacy_reference_index(
        _document(
            body_nodes=(_text("[1]", superscript=True),),
            references=("[1] First reference.", "1、Different reference."),
        )
    )

    duplicate = _issue(index, "duplicate_number")
    assert len(duplicate) == 1
    assert duplicate[0].blocking is True
    assert duplicate[0].source_number == 1


def test_missing_reference_entry_is_blocking_after_range_expansion():
    index = build_legacy_reference_index(
        _document(
            body_nodes=(_text("[1-2]", superscript=True),),
            references=("[1] First reference.",),
        )
    )

    assert index.occurrences[0].missing_numbers == (2,)
    missing = _issue(index, "missing_entry")
    assert len(missing) == 1
    assert missing[0].blocking is True
    assert missing[0].source_number == 2


def test_reports_uncited_entries_and_number_gaps_as_notices():
    index = build_legacy_reference_index(
        _document(
            body_nodes=(_text("[1]", superscript=True),),
            references=("[1] First reference.", "3、Third reference."),
        )
    )

    uncited = _issue(index, "uncited_entry")
    gap = _issue(index, "number_gap")
    assert [(issue.source_number, issue.blocking) for issue in uncited] == [(3, False)]
    assert [(issue.source_number, issue.blocking) for issue in gap] == [(2, False)]


@pytest.mark.parametrize(
    "references",
    [
        (
            "[1] Same article. DOI: 10.1000/ABC-123.",
            "2. Other formatting for the same DOI https://doi.org/10.1000/abc-123",
        ),
        ("[1] Same article.", "2、  Same   article.  "),
    ],
)
def test_deduplicates_same_doi_or_normalized_text_and_keeps_number_aliases(references):
    index = build_legacy_reference_index(
        _document(
            body_nodes=(_text("[1,2]", superscript=True),),
            references=references,
        )
    )

    assert len(index.entries) == 1
    assert index.entries[0].source_numbers == (1, 2)
    assert len(index.entries[0].sources) == 2
    assert index.number_to_reference_id[1] == index.number_to_reference_id[2]
    assert not _issue(index, "uncited_entry")


@pytest.mark.parametrize(
    ("references", "field_name", "expected"),
    [
        (
            (
                "[1] Alpha. Shared article[J]. Journal A, 2021. PMID: 34567890.",
                "[2] Beta. Different rendering[J]. Journal B, 2022. PMID 34567890.",
            ),
            "pmid",
            "34567890",
        ),
        (
            (
                "[1] Alpha. Shared article[J]. Journal A, 2021. https://www.example.org/article/42/.",
                "[2] Beta. Different rendering[J]. Journal B, 2022. http://example.org/article/42.",
            ),
            "url",
            "https://example.org/article/42",
        ),
        (
            (
                "[1] Alpha. Shared Trial Title[J]. Journal A, 2021.",
                "[2] Beta. Shared-trial title[J]. Journal B, 2021.",
            ),
            "normalized_title",
            "sharedtrialtitle",
        ),
    ],
)
def test_deduplicates_by_deterministic_identity_fallbacks(
    references,
    field_name,
    expected,
):
    index = build_legacy_reference_index(
        _document(
            body_nodes=(_text("[1,2]", superscript=True),),
            references=references,
        )
    )

    assert len(index.entries) == 1
    assert getattr(index.entries[0], field_name) == expected
    assert index.number_to_reference_id[1] == index.number_to_reference_id[2]


def test_stronger_identifier_conflict_prevents_weaker_pmid_merge():
    index = build_legacy_reference_index(
        _document(
            body_nodes=(_text("[1,2]", superscript=True),),
            references=(
                "[1] Alpha. Article[J]. Journal, 2021. DOI: 10.1000/one. PMID: 34567890.",
                "[2] Alpha. Article[J]. Journal, 2021. DOI: 10.1000/two. PMID: 34567890.",
            ),
        )
    )

    assert len(index.entries) == 2
    assert index.number_to_reference_id[1] != index.number_to_reference_id[2]


def test_nonempty_unparsed_reference_block_is_blocking():
    index = build_legacy_reference_index(
        _document(
            body_nodes=(_text("[1]", superscript=True),),
            references=("(1) Word auto-numbered reference without a supported prefix.",),
        )
    )

    issues = _issue(index, "unparsed_entry")
    assert len(issues) == 1
    assert issues[0].blocking is True
    assert issues[0].block_id == "reference_1"


def test_word_decimal_list_metadata_supplies_reference_numbers():
    document = _document(
        body_nodes=(_text("[1-3]", superscript=True),),
        references=("Alpha reference.", "Beta reference.", "Gamma reference."),
    )
    reference_blocks = document.sections[1].content_blocks
    for block in reference_blocks:
        block.update(
            {
                "num_id": "60",
                "ilvl": 0,
                "numbering_format": "decimal",
                "numbering_level_text": "[%1]",
                "numbering_start": 1,
                "numbering_start_override": None,
            }
        )

    index = build_legacy_reference_index(document)

    assert [entry.source_number for entry in index.entries] == [1, 2, 3]
    assert set(index.number_to_reference_id) == {1, 2, 3}
    assert index.occurrences[0].missing_numbers == ()
    assert not any(issue.blocking for issue in index.issues)


def test_ids_and_digest_are_stable_immutable_and_project_isolated():
    document = _document(
        body_nodes=(_text("[1]", superscript=True),),
        references=("[1] Article. DOI: 10.1000/STABLE-ID.",),
    )
    first = build_legacy_reference_index(document)
    second = build_legacy_reference_index(document.model_copy(deep=True))
    other_project = build_legacy_reference_index(
        document.model_copy(update={"project_id": "proj_other"}, deep=True)
    )

    assert first == second
    assert len(first.source_digest) == 64
    assert first.entries[0].reference_id == second.entries[0].reference_id
    assert first.entries[0].reference_id != other_project.entries[0].reference_id
    assert first.source_digest != other_project.source_digest
    with pytest.raises(FrozenInstanceError):
        first.entries[0].raw_text = "changed"
    with pytest.raises(TypeError):
        first.number_to_reference_id[2] = "mwref_changed"
