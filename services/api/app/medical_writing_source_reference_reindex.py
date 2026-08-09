from __future__ import annotations

import hashlib
import html
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from typing import Literal

from lxml import etree


_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f"{{{_W_NS}}}"
_NS = {"w": _W_NS}

_STORY_PART_RE = re.compile(
    r"^word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml$"
)
_REFERENCE_HEADING_RE = re.compile(
    r"^(?:(?:\d+(?:\.\d+)*)[.\s、]*)?(?:参考文献|references)$",
    re.IGNORECASE,
)
_REFERENCE_ENTRY_RE = re.compile(
    r"^\s*(?:\[\s*(\d{1,4})\s*\]|(\d{1,4})[.、])\s*(\S.*)\s*$",
    re.DOTALL,
)
_REFERENCE_TABLE_NUMBER_RE = re.compile(
    r"^\s*(?:\[\s*(\d{1,4})\s*\]|(\d{1,4})([.、]?))\s*$"
)
_CITATION_MARKER_RE = re.compile(
    r"\[\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?"
    r"(?:\s*[,，]\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?)*\s*\]"
)
_STRICT_MARKER_RE = re.compile(
    r"^\[\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?"
    r"(?:\s*[,，]\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?)*\s*\]$"
)
_RANGE_RE = re.compile(r"^\s*(\d{1,4})\s*[-‐‑‒–—]\s*(\d{1,4})\s*$")
_EXCLUDED_FIELD_RE = re.compile(r"^\s*(?:SEQ|PAGEREF|TOC)\b", re.IGNORECASE)
_REF_FIELD_RE = re.compile(r"^\s*REF\s+([^\s\\]+)", re.IGNORECASE)
_HYPERLINK_LOCAL_RE = re.compile(
    r"""^\s*HYPERLINK\b.*?\\l\s+(?:"([^"]+)"|'([^']+)'|([^\s\\]+))""",
    re.IGNORECASE,
)
_REF_TARGET_TOKEN_RE = re.compile(
    r"""^(\s*REF\s+)("[^"]*"|'[^']*'|[^\s\\]+)""",
    re.IGNORECASE,
)
_HYPERLINK_TARGET_TOKEN_RE = re.compile(
    r"""(\\l\s+)("[^"]*"|'[^']*'|[^\s\\]+)""",
    re.IGNORECASE,
)
_REFERENCE_ENTRY_PREFIX_RE = re.compile(r"^(\s*)(?:\[\s*(\d{1,4})\s*\]|(\d{1,4})[.、])")
_TRAILING_ASCII_ACRONYM_RE = re.compile(r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9_-]{1,15}$")
_HEADING_STYLE_RE = re.compile(r"^(?:heading|标题)\s*([1-9])$", re.IGNORECASE)
_APPENDIX_HEADING_RE = re.compile(
    r"^(?:(?:\d+(?:\.\d+)*)[.\s、]*)?(?:附录|appendix)(?:\s*\d+)?(?:\s|$)",
    re.IGNORECASE,
)
_MANAGER_DISPLAY_TEXT_RE = re.compile(
    r"<DisplayText>(.*?)</DisplayText>",
    re.IGNORECASE | re.DOTALL,
)
_XML_TAG_RE = re.compile(r"<[^>]+>")
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

ReindexAction = Literal["apply", "preserve_with_notice", "block"]
IssueSeverity = Literal["blocking", "notice"]
CitationBindingKind = Literal[
    "superscript",
    "plain_candidate",
    "internal_hyperlink",
    "simple_field",
    "complex_field",
    "manager_field",
]
ReferenceNumberingKind = Literal["explicit", "automatic", "table_cell"]


class SourceReferenceScanError(ValueError):
    """Raised when the supplied bytes are not a readable Word OOXML package."""


class SourceReferenceTransformError(ValueError):
    """Raised when an OOXML reindex operation cannot be proven safe."""


@dataclass(frozen=True)
class SourceReferenceIssue:
    code: str
    severity: IssueSeverity
    message: str
    part_name: str = ""
    locator: str = ""
    source_number: int | None = None

    @property
    def blocking(self) -> bool:
        return self.severity == "blocking"


@dataclass(frozen=True)
class SourceBookmark:
    bookmark_id: int
    name: str
    part_name: str
    locator: str
    end_present: bool


@dataclass(frozen=True)
class SourceInternalHyperlink:
    anchor: str
    text: str
    part_name: str
    locator: str


@dataclass(frozen=True)
class SourceField:
    field_kind: str
    instruction: str
    target: str
    result_text: str
    part_name: str
    locator: str
    simple: bool
    balanced: bool
    unsupported_manager: bool
    manager_kind: str = ""
    manager_metadata_text: str = ""
    manager_metadata_numbers: tuple[int, ...] = ()
    manager_result_numbers: tuple[int, ...] = ()
    manager_data_conflict: bool = False


@dataclass(frozen=True)
class SourceCitationOccurrence:
    raw_text: str
    source_numbers: tuple[int, ...]
    part_name: str
    story_kind: str
    paragraph_index: int
    locator: str
    binding_kind: CitationBindingKind
    target_bookmark: str = ""
    field_instruction: str = ""
    ambiguous: bool = False


@dataclass(frozen=True)
class SourceReferenceGroup:
    source_number: int
    raw_text: str
    part_name: str
    paragraph_indexes: tuple[int, ...]
    locators: tuple[str, ...]
    bookmark_names: tuple[str, ...]
    numbering_kind: ReferenceNumberingKind
    source_order: int
    content_digest: str


@dataclass(frozen=True)
class SourceBookmarkAllocation:
    source_number: int
    bookmark_id: int
    bookmark_name: str


@dataclass(frozen=True)
class SourceReferenceManifest:
    citations: tuple[SourceCitationOccurrence, ...]
    reference_groups: tuple[SourceReferenceGroup, ...]
    bookmarks: tuple[SourceBookmark, ...]
    internal_hyperlinks: tuple[SourceInternalHyperlink, ...]
    fields: tuple[SourceField, ...]
    issues: tuple[SourceReferenceIssue, ...]
    story_parts: tuple[str, ...]
    source_digest: str


@dataclass(frozen=True)
class SourceReindexDecision:
    action: ReindexAction
    ordered_source_numbers: tuple[int, ...]
    number_mapping: tuple[tuple[int, int], ...]
    uncited_source_numbers: tuple[int, ...]
    bookmark_allocations: tuple[SourceBookmarkAllocation, ...]
    issues: tuple[SourceReferenceIssue, ...]

    @property
    def can_apply(self) -> bool:
        return self.action == "apply"


@dataclass(frozen=True)
class _TextFragment:
    start: int
    end: int
    superscript: bool
    excluded_note_marker: bool
    inside_hyperlink: bool
    inside_simple_field: bool
    inside_balanced_complex_field: bool


@dataclass(frozen=True)
class _ParagraphRecord:
    element: etree._Element
    index: int
    locator: str
    text: str


@dataclass(frozen=True)
class _NumberingLevel:
    start: int
    number_format: str
    level_text: str


@dataclass(frozen=True)
class _ParagraphStyleDefinition:
    style_id: str
    name: str
    based_on: str
    outline_level: int | None


@dataclass
class _ComplexFieldState:
    part_name: str
    locator: str
    instructions: list[str]
    results: list[str]
    separated: bool = False


def build_source_reference_manifest(docx_bytes: bytes) -> SourceReferenceManifest:
    """Build a deterministic, read-only OOXML manifest from DOCX bytes."""

    if not isinstance(docx_bytes, bytes) or not docx_bytes:
        raise SourceReferenceScanError("DOCX content must be non-empty bytes")

    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as package:
            names = set(package.namelist())
            if "word/document.xml" not in names:
                raise SourceReferenceScanError(
                    "DOCX package does not contain word/document.xml"
                )
            story_parts = tuple(
                sorted(
                    (name for name in names if _STORY_PART_RE.fullmatch(name)),
                    key=_story_sort_key,
                )
            )
            numbering_levels = _read_numbering_levels(
                package.read("word/numbering.xml")
                if "word/numbering.xml" in names
                else b""
            )
            paragraph_styles = _read_paragraph_styles(
                package.read("word/styles.xml") if "word/styles.xml" in names else b""
            )
            roots: dict[str, etree._Element] = {}
            canonical_parts: list[bytes] = []
            for part_name in story_parts:
                try:
                    root = etree.fromstring(
                        package.read(part_name),
                        parser=etree.XMLParser(
                            resolve_entities=False,
                            no_network=True,
                            remove_blank_text=False,
                        ),
                    )
                except etree.XMLSyntaxError as exc:
                    raise SourceReferenceScanError(
                        f"invalid OOXML story part: {part_name}"
                    ) from exc
                roots[part_name] = root
                canonical_parts.append(part_name.encode("utf-8"))
                canonical_parts.append(
                    etree.tostring(root, method="c14n", with_comments=False)
                )
            if "word/numbering.xml" in names:
                canonical_parts.append(b"word/numbering.xml")
                canonical_parts.append(package.read("word/numbering.xml"))
            if "word/styles.xml" in names:
                canonical_parts.append(b"word/styles.xml")
                canonical_parts.append(package.read("word/styles.xml"))
    except zipfile.BadZipFile as exc:
        raise SourceReferenceScanError(
            "content is not a valid DOCX ZIP package"
        ) from exc

    bookmarks, bookmark_issues = _scan_bookmarks(roots)
    hyperlinks = _scan_internal_hyperlinks(roots)
    fields, field_issues = _scan_fields(roots)
    reference_groups, reference_region_paths = _scan_reference_groups(
        roots,
        numbering_levels=numbering_levels,
        paragraph_styles=paragraph_styles,
    )
    citations = _scan_citations(
        roots,
        reference_groups=reference_groups,
        reference_region_paths=reference_region_paths,
        hyperlinks=hyperlinks,
        fields=fields,
    )
    issues = _build_manifest_issues(
        citations=citations,
        reference_groups=reference_groups,
        bookmarks=bookmarks,
        hyperlinks=hyperlinks,
        fields=fields,
        initial_issues=bookmark_issues + field_issues,
    )
    return SourceReferenceManifest(
        citations=citations,
        reference_groups=reference_groups,
        bookmarks=bookmarks,
        internal_hyperlinks=hyperlinks,
        fields=fields,
        issues=issues,
        story_parts=story_parts,
        source_digest=hashlib.sha256(b"\0".join(canonical_parts)).hexdigest(),
    )


scan_source_reference_manifest = build_source_reference_manifest


def decide_source_reference_reindex(
    manifest: SourceReferenceManifest,
) -> SourceReindexDecision:
    """Return a fail-closed reindex plan without changing any OOXML."""

    issues = list(manifest.issues)
    groups_by_number: dict[int, list[SourceReferenceGroup]] = {}
    for group in manifest.reference_groups:
        groups_by_number.setdefault(group.source_number, []).append(group)

    cited_numbers: list[int] = []
    seen_cited: set[int] = set()
    for occurrence in manifest.citations:
        if occurrence.ambiguous:
            continue
        for number in occurrence.source_numbers:
            if number not in seen_cited:
                seen_cited.add(number)
                cited_numbers.append(number)

    remaining_groups = sorted(
        manifest.reference_groups,
        key=lambda item: item.source_order,
    )
    remaining_numbers: list[int] = []
    for group in remaining_groups:
        if (
            group.source_number not in seen_cited
            and group.source_number not in remaining_numbers
        ):
            remaining_numbers.append(group.source_number)
    ordered_numbers = tuple(cited_numbers + remaining_numbers)
    mapping = tuple(
        (source_number, new_number)
        for new_number, source_number in enumerate(ordered_numbers, start=1)
    )
    mapping_by_number = dict(mapping)
    for occurrence in manifest.citations:
        if occurrence.binding_kind != "manager_field":
            continue
        changed_numbers = tuple(
            number
            for number in occurrence.source_numbers
            if mapping_by_number.get(number) != number
        )
        if changed_numbers:
            issues.append(
                SourceReferenceIssue(
                    code="citation_manager_rebind_required",
                    severity="blocking",
                    message=(
                        "first-occurrence reindex would change an external "
                        "citation-manager result; preserve the ADDIN field and "
                        "rebind it in the originating Word plugin before apply"
                    ),
                    part_name=occurrence.part_name,
                    locator=occurrence.locator,
                    source_number=changed_numbers[0],
                )
            )
    for group in manifest.reference_groups:
        if (
            group.numbering_kind == "automatic"
            and mapping_by_number.get(group.source_number) != group.source_number
        ):
            issues.append(
                SourceReferenceIssue(
                    code="automatic_reference_numbering_rebind_required",
                    severity="blocking",
                    message=(
                        "first-occurrence reindex would change automatic Word "
                        "reference numbering, which cannot be rebound without "
                        "altering the numbering definition"
                    ),
                    part_name=group.part_name,
                    locator=group.locators[0],
                    source_number=group.source_number,
                )
            )
    issues = _deduplicate_issues(issues)
    allocations = allocate_reference_bookmarks(manifest, ordered_numbers)

    blocking = any(issue.blocking for issue in issues)
    ambiguous = any(citation.ambiguous for citation in manifest.citations)
    if blocking:
        action: ReindexAction = "block"
    elif (
        ambiguous
        or not manifest.reference_groups
        or not any(not citation.ambiguous for citation in manifest.citations)
    ):
        action = "preserve_with_notice"
    else:
        action = "apply"

    return SourceReindexDecision(
        action=action,
        ordered_source_numbers=ordered_numbers,
        number_mapping=mapping,
        uncited_source_numbers=tuple(remaining_numbers),
        bookmark_allocations=allocations,
        issues=tuple(issues),
    )


def allocate_reference_bookmarks(
    manifest: SourceReferenceManifest,
    ordered_source_numbers: tuple[int, ...],
) -> tuple[SourceBookmarkAllocation, ...]:
    """Allocate deterministic bookmark identities outside the source namespace."""

    used_ids = {bookmark.bookmark_id for bookmark in manifest.bookmarks}
    used_names = {bookmark.name for bookmark in manifest.bookmarks}
    next_id = max(used_ids, default=0) + 1
    allocations: list[SourceBookmarkAllocation] = []
    for source_number in ordered_source_numbers:
        while next_id in used_ids:
            next_id += 1
        base_name = (
            "_MWREF_"
            + hashlib.sha256(
                f"{manifest.source_digest}:{source_number}".encode("utf-8")
            ).hexdigest()[:16]
        )
        name = base_name
        suffix = 1
        while name in used_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        allocations.append(
            SourceBookmarkAllocation(
                source_number=source_number,
                bookmark_id=next_id,
                bookmark_name=name,
            )
        )
        used_ids.add(next_id)
        used_names.add(name)
        next_id += 1
    return tuple(allocations)


def apply_source_reference_reindex(
    docx_bytes: bytes,
    manifest: SourceReferenceManifest,
    decision: SourceReindexDecision,
) -> bytes:
    """Apply a source-bound reference reindex directly to safe OOXML locators."""

    if not isinstance(manifest, SourceReferenceManifest):
        raise SourceReferenceTransformError(
            "source reference manifest has an invalid type"
        )
    if not isinstance(decision, SourceReindexDecision):
        raise SourceReferenceTransformError(
            "source reindex decision has an invalid type"
        )

    try:
        rescanned = build_source_reference_manifest(docx_bytes)
    except SourceReferenceScanError as exc:
        raise SourceReferenceTransformError(
            "source DOCX cannot be rescanned safely"
        ) from exc
    if rescanned.source_digest != manifest.source_digest or rescanned != manifest:
        raise SourceReferenceTransformError(
            "source DOCX digest or physical locators drifted after manifest scan"
        )
    expected_decision = decide_source_reference_reindex(manifest)
    if decision != expected_decision:
        raise SourceReferenceTransformError(
            "source reindex decision does not match the scanned manifest"
        )
    if not decision.can_apply:
        raise SourceReferenceTransformError(
            f"source reindex decision is {decision.action}; physical apply is forbidden"
        )

    items, package_comment, payloads, roots = _load_source_package(docx_bytes)
    if _is_already_reindexed(roots, manifest, decision):
        return docx_bytes

    number_mapping = dict(decision.number_mapping)
    allocations = {
        allocation.source_number: allocation
        for allocation in decision.bookmark_allocations
    }
    group_numbers = {group.source_number for group in manifest.reference_groups}
    if (
        set(number_mapping) != group_numbers
        or set(allocations) != group_numbers
        or len(number_mapping) != len(decision.number_mapping)
        or len(allocations) != len(decision.bookmark_allocations)
    ):
        raise SourceReferenceTransformError(
            "decision mapping or bookmark allocation does not cover each reference"
        )

    used_bookmark_ids = {bookmark.bookmark_id for bookmark in manifest.bookmarks}
    used_bookmark_names = {
        bookmark.name for bookmark in manifest.bookmarks if bookmark.name
    }
    for allocation in allocations.values():
        if (
            allocation.bookmark_id in used_bookmark_ids
            or allocation.bookmark_name in used_bookmark_names
        ):
            raise SourceReferenceTransformError(
                "decision bookmark allocation collides with source OOXML"
            )
        used_bookmark_ids.add(allocation.bookmark_id)
        used_bookmark_names.add(allocation.bookmark_name)

    changed_parts: set[str] = set()
    _rewrite_textual_citations(
        roots,
        manifest.citations,
        number_mapping=number_mapping,
        changed_parts=changed_parts,
    )
    _rewrite_bound_citations(
        roots,
        manifest.citations,
        number_mapping=number_mapping,
        allocations=allocations,
        changed_parts=changed_parts,
    )
    _rewrite_reference_entries(
        roots,
        manifest.reference_groups,
        number_mapping=number_mapping,
        changed_parts=changed_parts,
    )
    _insert_reference_bookmarks(
        roots,
        manifest.reference_groups,
        allocations=allocations,
        changed_parts=changed_parts,
    )

    if not changed_parts:
        return docx_bytes
    for part_name in changed_parts:
        payloads[part_name] = etree.tostring(
            roots[part_name],
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )
    return _write_source_package(
        items=items,
        package_comment=package_comment,
        payloads=payloads,
    )


transform_source_reference_reindex = apply_source_reference_reindex


def _load_source_package(
    docx_bytes: bytes,
) -> tuple[
    tuple[zipfile.ZipInfo, ...],
    bytes,
    dict[str, bytes],
    dict[str, etree._Element],
]:
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as package:
            items = tuple(package.infolist())
            names = [item.filename for item in items]
            if len(names) != len(set(names)):
                raise SourceReferenceTransformError(
                    "DOCX package contains duplicate ZIP part names"
                )
            payloads = {item.filename: package.read(item.filename) for item in items}
            comment = package.comment
    except zipfile.BadZipFile as exc:
        raise SourceReferenceTransformError(
            "content is not a valid DOCX ZIP package"
        ) from exc

    roots: dict[str, etree._Element] = {}
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_blank_text=False,
    )
    for part_name in sorted(
        (name for name in payloads if _STORY_PART_RE.fullmatch(name)),
        key=_story_sort_key,
    ):
        try:
            roots[part_name] = etree.fromstring(payloads[part_name], parser=parser)
        except etree.XMLSyntaxError as exc:
            raise SourceReferenceTransformError(
                f"invalid OOXML story part: {part_name}"
            ) from exc
    if tuple(sorted(roots, key=_story_sort_key)) == ():
        raise SourceReferenceTransformError("DOCX package has no Word story parts")
    return items, comment, payloads, roots


def _write_source_package(
    *,
    items: tuple[zipfile.ZipInfo, ...],
    package_comment: bytes,
    payloads: dict[str, bytes],
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as package:
        package.comment = package_comment
        for item in items:
            package.writestr(item, payloads[item.filename])
    return output.getvalue()


def _is_already_reindexed(
    roots: dict[str, etree._Element],
    manifest: SourceReferenceManifest,
    decision: SourceReindexDecision,
) -> bool:
    if any(source != target for source, target in decision.number_mapping):
        return False
    groups_by_number = {
        group.source_number: group for group in manifest.reference_groups
    }
    governed_bookmarks: dict[int, set[str]] = {}
    for group in manifest.reference_groups:
        names = {name for name in group.bookmark_names if name.startswith("_MWREF_")}
        if not names:
            return False
        governed_bookmarks[group.source_number] = names
        paragraph = _resolve_xpath_one(
            roots,
            part_name=group.part_name,
            locator=group.locators[0],
            expected_tag=f"{_W}p",
        )
        paragraph_text = _element_text(paragraph)
        marker = _reference_entry_marker(
            paragraph_text,
            numbering_kind=group.numbering_kind,
        )
        if marker is None:
            if paragraph.find("w:pPr/w:numPr", _NS) is None:
                return False
        elif marker[0] != group.source_number:
            return False

    for occurrence in manifest.citations:
        if occurrence.ambiguous:
            return False
        if occurrence.binding_kind == "manager_field":
            if _parse_marker(occurrence.raw_text) != occurrence.source_numbers:
                return False
        elif occurrence.raw_text != _canonical_marker(occurrence.source_numbers, {}):
            return False
        if occurrence.binding_kind in {
            "internal_hyperlink",
            "simple_field",
            "complex_field",
        }:
            if len(occurrence.source_numbers) != 1:
                return False
            source_number = occurrence.source_numbers[0]
            if (
                source_number not in groups_by_number
                or occurrence.target_bookmark not in governed_bookmarks[source_number]
            ):
                return False
    return True


def _rewrite_textual_citations(
    roots: dict[str, etree._Element],
    citations: tuple[SourceCitationOccurrence, ...],
    *,
    number_mapping: dict[int, int],
    changed_parts: set[str],
) -> None:
    by_paragraph: dict[tuple[str, str], list[tuple[int, int, str, str]]] = {}
    for occurrence in citations:
        if occurrence.binding_kind == "plain_candidate":
            raise SourceReferenceTransformError(
                "ambiguous plain citation cannot be physically rewritten"
            )
        if occurrence.binding_kind != "superscript":
            continue
        paragraph_locator, start, end = _parse_char_locator(occurrence.locator)
        by_paragraph.setdefault(
            (occurrence.part_name, paragraph_locator),
            [],
        ).append(
            (
                start,
                end,
                occurrence.raw_text,
                _canonical_marker(occurrence.source_numbers, number_mapping),
            )
        )

    for (part_name, locator), edits in by_paragraph.items():
        paragraph = _resolve_xpath_one(
            roots,
            part_name=part_name,
            locator=locator,
            expected_tag=f"{_W}p",
        )
        ascending = sorted(edits, key=lambda item: (item[0], item[1]))
        for previous, current in zip(ascending, ascending[1:]):
            if previous[1] > current[0]:
                raise SourceReferenceTransformError(
                    f"overlapping citation locators in {part_name}:{locator}"
                )
        for start, end, expected, replacement in reversed(ascending):
            if replacement == expected:
                continue
            _replace_element_text_span(
                paragraph,
                start=start,
                end=end,
                expected=expected,
                replacement=replacement,
                context=f"{part_name}:{locator}",
            )
            changed_parts.add(part_name)


def _rewrite_bound_citations(
    roots: dict[str, etree._Element],
    citations: tuple[SourceCitationOccurrence, ...],
    *,
    number_mapping: dict[int, int],
    allocations: dict[int, SourceBookmarkAllocation],
    changed_parts: set[str],
) -> None:
    for occurrence in citations:
        if occurrence.binding_kind in {
            "superscript",
            "plain_candidate",
            "manager_field",
        }:
            continue
        if len(occurrence.source_numbers) != 1:
            raise SourceReferenceTransformError(
                "one hyperlink or Word field cannot bind multiple references safely"
            )
        source_number = occurrence.source_numbers[0]
        allocation = allocations.get(source_number)
        if allocation is None:
            raise SourceReferenceTransformError(
                f"citation points outside the decision mapping: {source_number}"
            )
        replacement = _canonical_marker(
            occurrence.source_numbers,
            number_mapping,
        )
        if occurrence.binding_kind == "internal_hyperlink":
            hyperlink = _resolve_xpath_one(
                roots,
                part_name=occurrence.part_name,
                locator=occurrence.locator,
                expected_tag=f"{_W}hyperlink",
            )
            if (
                str(hyperlink.get(f"{_W}anchor") or "") != occurrence.target_bookmark
                or _element_text(hyperlink) != occurrence.raw_text
            ):
                raise SourceReferenceTransformError(
                    "internal hyperlink locator or source text drifted"
                )
            hyperlink.set(f"{_W}anchor", allocation.bookmark_name)
            _replace_all_text_nodes(
                tuple(hyperlink.iter(f"{_W}t")),
                expected=occurrence.raw_text,
                replacement=replacement,
                context=f"{occurrence.part_name}:{occurrence.locator}",
            )
        elif occurrence.binding_kind == "simple_field":
            field = _resolve_xpath_one(
                roots,
                part_name=occurrence.part_name,
                locator=occurrence.locator,
                expected_tag=f"{_W}fldSimple",
            )
            instruction = str(field.get(f"{_W}instr") or "")
            if _normalize_space(instruction) != _normalize_space(
                occurrence.field_instruction
            ):
                raise SourceReferenceTransformError(
                    "simple field instruction drifted after manifest scan"
                )
            field.set(
                f"{_W}instr",
                _replace_field_target(
                    instruction,
                    allocation.bookmark_name,
                ),
            )
            _replace_all_text_nodes(
                tuple(field.iter(f"{_W}t")),
                expected=occurrence.raw_text,
                replacement=replacement,
                context=f"{occurrence.part_name}:{occurrence.locator}",
            )
        elif occurrence.binding_kind == "complex_field":
            _rewrite_complex_field(
                roots[occurrence.part_name],
                occurrence=occurrence,
                replacement=replacement,
                target_bookmark=allocation.bookmark_name,
            )
        else:
            raise SourceReferenceTransformError(
                f"unsupported citation binding kind: {occurrence.binding_kind}"
            )
        changed_parts.add(occurrence.part_name)


def _rewrite_complex_field(
    root: etree._Element,
    *,
    occurrence: SourceCitationOccurrence,
    replacement: str,
    target_bookmark: str,
) -> None:
    tree = root.getroottree()
    try:
        matches = tree.xpath(occurrence.locator, namespaces=_NS)
    except etree.XPathError as exc:
        raise SourceReferenceTransformError(
            "complex field locator is not a valid XPath"
        ) from exc
    if len(matches) != 1:
        raise SourceReferenceTransformError(
            "complex field locator no longer resolves exactly once"
        )
    begin = matches[0]
    if (
        begin.tag != f"{_W}fldChar"
        or str(begin.get(f"{_W}fldCharType") or "") != "begin"
    ):
        raise SourceReferenceTransformError(
            "complex field locator no longer resolves to a begin marker"
        )
    paragraph = _nearest_ancestor(begin, f"{_W}p")
    if paragraph is None:
        raise SourceReferenceTransformError("complex field has no paragraph owner")

    nodes = list(root.iter())
    try:
        begin_index = nodes.index(begin)
    except ValueError as exc:
        raise SourceReferenceTransformError(
            "complex field begin marker is detached"
        ) from exc
    instruction_nodes: list[etree._Element] = []
    result_nodes: list[etree._Element] = []
    separated = False
    ended = False
    for node in nodes[begin_index + 1 :]:
        if _nearest_ancestor(node, f"{_W}p") is not paragraph:
            raise SourceReferenceTransformError(
                "complex citation field crosses a paragraph boundary"
            )
        if node.tag == f"{_W}fldSimple":
            raise SourceReferenceTransformError(
                "nested simple fields inside a complex citation field are not rewritten"
            )
        if node.tag == f"{_W}fldChar":
            field_type = str(node.get(f"{_W}fldCharType") or "")
            if field_type == "begin":
                raise SourceReferenceTransformError(
                    "nested complex citation fields are not rewritten"
                )
            if field_type == "separate":
                if separated:
                    raise SourceReferenceTransformError(
                        "complex citation field has multiple separators"
                    )
                separated = True
                continue
            if field_type == "end":
                ended = True
                break
        elif node.tag == f"{_W}instrText" and not separated:
            instruction_nodes.append(node)
        elif node.tag == f"{_W}t" and separated:
            result_nodes.append(node)
    if not separated or not ended or not instruction_nodes or not result_nodes:
        raise SourceReferenceTransformError(
            "complex citation field structure cannot be rewritten safely"
        )
    instruction = "".join(str(node.text or "") for node in instruction_nodes)
    if _normalize_space(instruction) != _normalize_space(occurrence.field_instruction):
        raise SourceReferenceTransformError(
            "complex field instruction drifted after manifest scan"
        )
    _replace_all_text_nodes(
        tuple(instruction_nodes),
        expected=instruction,
        replacement=_replace_field_target(instruction, target_bookmark),
        context=f"{occurrence.part_name}:{occurrence.locator}:instruction",
    )
    _replace_all_text_nodes(
        tuple(result_nodes),
        expected=occurrence.raw_text,
        replacement=replacement,
        context=f"{occurrence.part_name}:{occurrence.locator}:result",
    )


def _rewrite_reference_entries(
    roots: dict[str, etree._Element],
    groups: tuple[SourceReferenceGroup, ...],
    *,
    number_mapping: dict[int, int],
    changed_parts: set[str],
) -> None:
    for group in groups:
        paragraph = _resolve_xpath_one(
            roots,
            part_name=group.part_name,
            locator=group.locators[0],
            expected_tag=f"{_W}p",
        )
        paragraph_text = _element_text(paragraph)
        marker = _reference_entry_marker(
            paragraph_text,
            numbering_kind=group.numbering_kind,
        )
        target_number = number_mapping[group.source_number]
        if marker is None:
            if target_number != group.source_number:
                raise SourceReferenceTransformError(
                    "automatic Word reference numbering cannot be remapped safely"
                )
            continue
        parsed_number, start, end = marker
        if parsed_number != group.source_number:
            raise SourceReferenceTransformError(
                "reference entry prefix drifted after manifest scan"
            )
        replacement = (
            _replace_first_number_token(paragraph_text[start:end], target_number)
            if group.numbering_kind == "table_cell"
            else f"[{target_number}]"
        )
        expected = paragraph_text[start:end]
        if expected == replacement:
            continue
        _replace_element_text_span(
            paragraph,
            start=start,
            end=end,
            expected=expected,
            replacement=replacement,
            context=f"{group.part_name}:{group.locators[0]}",
        )
        changed_parts.add(group.part_name)


def _insert_reference_bookmarks(
    roots: dict[str, etree._Element],
    groups: tuple[SourceReferenceGroup, ...],
    *,
    allocations: dict[int, SourceBookmarkAllocation],
    changed_parts: set[str],
) -> None:
    for group in groups:
        allocation = allocations[group.source_number]
        paragraph = _resolve_xpath_one(
            roots,
            part_name=group.part_name,
            locator=group.locators[0],
            expected_tag=f"{_W}p",
        )
        start = etree.Element(f"{_W}bookmarkStart")
        start.set(f"{_W}id", str(allocation.bookmark_id))
        start.set(f"{_W}name", allocation.bookmark_name)
        end = etree.Element(f"{_W}bookmarkEnd")
        end.set(f"{_W}id", str(allocation.bookmark_id))
        insert_at = 1 if len(paragraph) and paragraph[0].tag == f"{_W}pPr" else 0
        paragraph.insert(insert_at, start)
        paragraph.append(end)
        changed_parts.add(group.part_name)


def _resolve_xpath_one(
    roots: dict[str, etree._Element],
    *,
    part_name: str,
    locator: str,
    expected_tag: str,
) -> etree._Element:
    root = roots.get(part_name)
    if root is None:
        raise SourceReferenceTransformError(
            f"manifest story part is unavailable: {part_name}"
        )
    try:
        matches = root.getroottree().xpath(locator, namespaces=_NS)
    except etree.XPathError as exc:
        raise SourceReferenceTransformError(
            f"invalid physical locator: {part_name}:{locator}"
        ) from exc
    if len(matches) != 1 or matches[0].tag != expected_tag:
        raise SourceReferenceTransformError(
            f"physical locator drifted: {part_name}:{locator}"
        )
    return matches[0]


def _parse_char_locator(locator: str) -> tuple[str, int, int]:
    try:
        paragraph_locator, raw_range = locator.rsplit(":chars:", 1)
        raw_start, raw_end = raw_range.split("-", 1)
        start = int(raw_start)
        end = int(raw_end)
    except (ValueError, TypeError) as exc:
        raise SourceReferenceTransformError(
            f"invalid citation character locator: {locator}"
        ) from exc
    if not paragraph_locator or start < 0 or end <= start:
        raise SourceReferenceTransformError(
            f"invalid citation character locator: {locator}"
        )
    return paragraph_locator, start, end


def _replace_element_text_span(
    element: etree._Element,
    *,
    start: int,
    end: int,
    expected: str,
    replacement: str,
    context: str,
) -> None:
    text_nodes = tuple(element.iter(f"{_W}t"))
    values = [str(node.text or "") for node in text_nodes]
    combined = "".join(values)
    if end > len(combined) or combined[start:end] != expected:
        raise SourceReferenceTransformError(
            f"source text drifted at physical locator: {context}"
        )

    positions: list[tuple[etree._Element, int, int]] = []
    cursor = 0
    for node, value in zip(text_nodes, values):
        node_start = cursor
        node_end = cursor + len(value)
        if node_start < end and node_end > start:
            positions.append((node, node_start, node_end))
        cursor = node_end
    if not positions:
        raise SourceReferenceTransformError(
            f"physical text locator has no text nodes: {context}"
        )

    first_node, first_start, first_end = positions[0]
    first_value = str(first_node.text or "")
    prefix = first_value[: max(0, start - first_start)]
    if len(positions) == 1:
        suffix = first_value[max(0, end - first_start) :]
        _set_text_node(first_node, prefix + replacement + suffix)
        return

    _set_text_node(first_node, prefix + replacement)
    for node, _, _ in positions[1:-1]:
        _set_text_node(node, "")
    last_node, last_start, _ = positions[-1]
    last_value = str(last_node.text or "")
    _set_text_node(last_node, last_value[max(0, end - last_start) :])


def _replace_all_text_nodes(
    text_nodes: tuple[etree._Element, ...],
    *,
    expected: str,
    replacement: str,
    context: str,
) -> None:
    if (
        not text_nodes
        or "".join(str(node.text or "") for node in text_nodes) != expected
    ):
        raise SourceReferenceTransformError(
            f"source text drifted at physical locator: {context}"
        )
    _set_text_node(text_nodes[0], replacement)
    for node in text_nodes[1:]:
        _set_text_node(node, "")


def _set_text_node(node: etree._Element, value: str) -> None:
    node.text = value
    if value[:1].isspace() or value[-1:].isspace():
        node.set(_XML_SPACE, "preserve")
    else:
        node.attrib.pop(_XML_SPACE, None)


def _replace_field_target(instruction: str, bookmark_name: str) -> str:
    field_kind = instruction.split(maxsplit=1)[0].upper() if instruction else ""
    pattern = (
        _REF_TARGET_TOKEN_RE
        if field_kind == "REF"
        else _HYPERLINK_TARGET_TOKEN_RE
        if field_kind == "HYPERLINK"
        else None
    )
    if pattern is None:
        raise SourceReferenceTransformError(
            f"unsupported citation field kind: {field_kind or '<empty>'}"
        )
    match = pattern.search(instruction)
    if match is None:
        raise SourceReferenceTransformError(
            f"{field_kind} field has no safe local bookmark target"
        )
    token = match.group(2)
    if token.startswith('"') and token.endswith('"'):
        replacement = f'"{bookmark_name}"'
    elif token.startswith("'") and token.endswith("'"):
        replacement = f"'{bookmark_name}'"
    else:
        replacement = bookmark_name
    return instruction[: match.start(2)] + replacement + instruction[match.end(2) :]


def _reference_entry_marker(
    paragraph_text: str,
    *,
    numbering_kind: ReferenceNumberingKind,
) -> tuple[int, int, int] | None:
    if numbering_kind == "table_cell":
        match = _REFERENCE_TABLE_NUMBER_RE.fullmatch(paragraph_text)
        if match is None:
            return None
        number_group = 1 if match.group(1) is not None else 2
        return int(match.group(number_group)), match.start(), match.end()
    match = _REFERENCE_ENTRY_PREFIX_RE.match(paragraph_text)
    if match is None:
        return None
    return int(match.group(2) or match.group(3)), len(match.group(1)), match.end()


def _replace_first_number_token(value: str, target_number: int) -> str:
    return re.sub(r"\d{1,4}", str(target_number), value, count=1)


def _canonical_marker(
    source_numbers: tuple[int, ...],
    number_mapping: dict[int, int],
) -> str:
    mapped: list[int] = []
    for source_number in source_numbers:
        target = number_mapping.get(source_number, source_number)
        if target not in mapped:
            mapped.append(target)
    if not mapped:
        raise SourceReferenceTransformError("citation marker has no reference numbers")
    return "[" + ",".join(str(number) for number in sorted(mapped)) + "]"


def _story_sort_key(part_name: str) -> tuple[int, str]:
    if part_name == "word/document.xml":
        return (0, part_name)
    if "/header" in part_name:
        return (1, part_name)
    if "/footer" in part_name:
        return (2, part_name)
    if part_name == "word/footnotes.xml":
        return (3, part_name)
    if part_name == "word/endnotes.xml":
        return (4, part_name)
    return (5, part_name)


def _story_kind(part_name: str) -> str:
    return part_name.removeprefix("word/").removesuffix(".xml").rstrip("0123456789")


def _scan_bookmarks(
    roots: dict[str, etree._Element],
) -> tuple[tuple[SourceBookmark, ...], list[SourceReferenceIssue]]:
    records: list[SourceBookmark] = []
    issues: list[SourceReferenceIssue] = []
    seen_names: dict[str, tuple[str, str]] = {}
    for part_name, root in roots.items():
        tree = root.getroottree()
        end_ids = {
            str(node.get(f"{_W}id") or "") for node in root.iter(f"{_W}bookmarkEnd")
        }
        seen_part_ids: set[int] = set()
        for node in root.iter(f"{_W}bookmarkStart"):
            locator = tree.getpath(node)
            raw_id = str(node.get(f"{_W}id") or "")
            name = str(node.get(f"{_W}name") or "")
            try:
                bookmark_id = int(raw_id)
            except ValueError:
                issues.append(
                    SourceReferenceIssue(
                        code="invalid_bookmark_id",
                        severity="blocking",
                        message="bookmark id is not an integer",
                        part_name=part_name,
                        locator=locator,
                    )
                )
                continue
            if bookmark_id in seen_part_ids:
                issues.append(
                    SourceReferenceIssue(
                        code="duplicate_bookmark_id",
                        severity="blocking",
                        message="bookmark id is duplicated within one story",
                        part_name=part_name,
                        locator=locator,
                    )
                )
            seen_part_ids.add(bookmark_id)
            if name and name in seen_names:
                first_part, first_locator = seen_names[name]
                issues.append(
                    SourceReferenceIssue(
                        code="duplicate_bookmark_name",
                        severity="blocking",
                        message=(
                            "bookmark name is ambiguous across the package: "
                            f"{first_part}:{first_locator}"
                        ),
                        part_name=part_name,
                        locator=locator,
                    )
                )
            elif name:
                seen_names[name] = (part_name, locator)
            end_present = raw_id in end_ids
            if not end_present:
                issues.append(
                    SourceReferenceIssue(
                        code="unbalanced_bookmark",
                        severity="blocking",
                        message="bookmark start has no matching end in the same story",
                        part_name=part_name,
                        locator=locator,
                    )
                )
            records.append(
                SourceBookmark(
                    bookmark_id=bookmark_id,
                    name=name,
                    part_name=part_name,
                    locator=locator,
                    end_present=end_present,
                )
            )
    return tuple(records), issues


def _scan_internal_hyperlinks(
    roots: dict[str, etree._Element],
) -> tuple[SourceInternalHyperlink, ...]:
    records: list[SourceInternalHyperlink] = []
    for part_name, root in roots.items():
        tree = root.getroottree()
        for node in root.iter(f"{_W}hyperlink"):
            anchor = str(node.get(f"{_W}anchor") or "").strip()
            if not anchor:
                continue
            records.append(
                SourceInternalHyperlink(
                    anchor=anchor,
                    text=_element_text(node),
                    part_name=part_name,
                    locator=tree.getpath(node),
                )
            )
    return tuple(records)


def _scan_fields(
    roots: dict[str, etree._Element],
) -> tuple[tuple[SourceField, ...], list[SourceReferenceIssue]]:
    records: list[SourceField] = []
    issues: list[SourceReferenceIssue] = []
    for part_name, root in roots.items():
        tree = root.getroottree()
        stack: list[_ComplexFieldState] = []
        for node in root.iter():
            if node.tag == f"{_W}fldSimple":
                instruction = _normalize_space(str(node.get(f"{_W}instr") or ""))
                records.append(
                    _field_record(
                        instruction=instruction,
                        result_text=_element_text(node),
                        part_name=part_name,
                        locator=tree.getpath(node),
                        simple=True,
                        balanced=True,
                    )
                )
                continue
            if _has_ancestor(node, f"{_W}fldSimple"):
                continue
            if node.tag == f"{_W}fldChar":
                field_type = str(node.get(f"{_W}fldCharType") or "")
                if field_type == "begin":
                    stack.append(
                        _ComplexFieldState(
                            part_name=part_name,
                            locator=tree.getpath(node),
                            instructions=[],
                            results=[],
                        )
                    )
                elif field_type == "separate":
                    if not stack:
                        issues.append(
                            SourceReferenceIssue(
                                code="unbalanced_field",
                                severity="blocking",
                                message="field separator has no matching begin",
                                part_name=part_name,
                                locator=tree.getpath(node),
                            )
                        )
                    else:
                        stack[-1].separated = True
                elif field_type == "end":
                    if not stack:
                        issues.append(
                            SourceReferenceIssue(
                                code="unbalanced_field",
                                severity="blocking",
                                message="field end has no matching begin",
                                part_name=part_name,
                                locator=tree.getpath(node),
                            )
                        )
                    else:
                        state = stack.pop()
                        records.append(
                            _field_record(
                                instruction=_normalize_space(
                                    "".join(state.instructions)
                                ),
                                result_text="".join(state.results),
                                part_name=state.part_name,
                                locator=state.locator,
                                simple=False,
                                balanced=True,
                            )
                        )
                continue
            if node.tag == f"{_W}instrText" and stack:
                stack[-1].instructions.append(str(node.text or ""))
            elif node.tag == f"{_W}t" and stack and stack[-1].separated:
                stack[-1].results.append(str(node.text or ""))
        for state in stack:
            instruction = _normalize_space("".join(state.instructions))
            records.append(
                _field_record(
                    instruction=instruction,
                    result_text="".join(state.results),
                    part_name=state.part_name,
                    locator=state.locator,
                    simple=False,
                    balanced=False,
                )
            )
            issues.append(
                SourceReferenceIssue(
                    code="unbalanced_field",
                    severity="blocking",
                    message="field begin has no matching end",
                    part_name=state.part_name,
                    locator=state.locator,
                )
            )
    for field in records:
        if not field.unsupported_manager or not field.balanced:
            continue
        if not field.manager_result_numbers:
            issues.append(
                SourceReferenceIssue(
                    code="citation_manager_result_unresolved",
                    severity="blocking",
                    message=(
                        "external citation-manager field has no unambiguous numeric "
                        "visible result; refresh or convert the field in Word before "
                        "controlled reindex"
                    ),
                    part_name=field.part_name,
                    locator=field.locator,
                )
            )
            continue
        issues.append(
            SourceReferenceIssue(
                code="citation_manager_field_preserved",
                severity="notice",
                message=(
                    "external citation-manager ADDIN metadata and visible result "
                    "will be preserved byte-for-byte; the visible result is used "
                    "only for the controlled citation map"
                ),
                part_name=field.part_name,
                locator=field.locator,
            )
        )
        if field.manager_data_conflict:
            issues.append(
                SourceReferenceIssue(
                    code="citation_manager_metadata_conflict",
                    severity="notice",
                    message=(
                        "citation-manager embedded display metadata differs from "
                        "the visible Word result; the visible result governs this "
                        "scan and the source field requires plugin review"
                    ),
                    part_name=field.part_name,
                    locator=field.locator,
                )
            )
    return tuple(records), issues


def _field_record(
    *,
    instruction: str,
    result_text: str,
    part_name: str,
    locator: str,
    simple: bool,
    balanced: bool,
) -> SourceField:
    target = ""
    field_kind = instruction.split(maxsplit=1)[0].upper() if instruction else ""
    ref_match = _REF_FIELD_RE.match(instruction)
    hyperlink_match = _HYPERLINK_LOCAL_RE.match(instruction)
    if ref_match:
        target = ref_match.group(1).strip("\"'")
    elif hyperlink_match:
        target = next(
            (value for value in hyperlink_match.groups() if value is not None),
            "",
        )
    manager_kind = _manager_kind(instruction)
    manager_metadata_text = _manager_metadata_display(instruction)
    manager_metadata_numbers = _parse_marker(manager_metadata_text)
    manager_result_numbers = _parse_marker(result_text)
    return SourceField(
        field_kind=field_kind,
        instruction=instruction,
        target=target,
        result_text=result_text,
        part_name=part_name,
        locator=locator,
        simple=simple,
        balanced=balanced,
        unsupported_manager=bool(manager_kind),
        manager_kind=manager_kind,
        manager_metadata_text=manager_metadata_text,
        manager_metadata_numbers=manager_metadata_numbers,
        manager_result_numbers=manager_result_numbers,
        manager_data_conflict=bool(
            manager_metadata_numbers
            and manager_result_numbers
            and manager_metadata_numbers != manager_result_numbers
        ),
    )


def _manager_kind(instruction: str) -> str:
    normalized = str(instruction or "")
    if re.search(r"\bADDIN\s+EN\.CITE\b", normalized, re.IGNORECASE):
        return "endnote"
    if re.search(
        r"\b(?:ADDIN\s+ZOTERO_ITEM|ZOTERO_ITEM|CSL_CITATION)\b",
        normalized,
        re.IGNORECASE,
    ):
        return "zotero"
    if re.search(r"\bADDIN\s+Mendeley\b", normalized, re.IGNORECASE):
        return "mendeley"
    return ""


def _manager_metadata_display(instruction: str) -> str:
    match = _MANAGER_DISPLAY_TEXT_RE.search(html.unescape(str(instruction or "")))
    if match is None:
        return ""
    return _normalize_space(_XML_TAG_RE.sub("", match.group(1)))


def _scan_reference_groups(
    roots: dict[str, etree._Element],
    *,
    numbering_levels: dict[tuple[str, int], _NumberingLevel],
    paragraph_styles: dict[str, _ParagraphStyleDefinition],
) -> tuple[tuple[SourceReferenceGroup, ...], frozenset[str]]:
    groups: list[SourceReferenceGroup] = []
    reference_region_paths: set[str] = set()
    source_order = 0
    for part_name, root in roots.items():
        paragraphs = _paragraph_records(root)
        paragraph_indexes = {
            paragraph.locator: paragraph.index for paragraph in paragraphs
        }
        in_references = False
        reference_heading_level = 0
        active: dict[str, object] | None = None
        counters: dict[tuple[str, int], int] = {}
        consumed_table_paths: set[str] = set()
        inspected_table_rows: set[str] = set()
        for paragraph in paragraphs:
            normalized = _normalize_heading(paragraph.text)
            if _REFERENCE_HEADING_RE.fullmatch(normalized):
                if active is not None:
                    groups.append(_finalize_reference_group(active))
                    active = None
                in_references = True
                reference_heading_level = (
                    _paragraph_heading_level(
                        paragraph.element,
                        paragraph_styles=paragraph_styles,
                    )
                    or 0
                )
                counters.clear()
                reference_region_paths.add(paragraph.locator)
                continue
            if not in_references:
                continue

            heading_level = _paragraph_heading_level(
                paragraph.element,
                paragraph_styles=paragraph_styles,
            )
            if (
                heading_level is None
                and not _has_ancestor(paragraph.element, f"{_W}tbl")
                and _APPENDIX_HEADING_RE.match(normalized)
            ):
                heading_level = 0
            if heading_level is not None:
                if active is not None:
                    groups.append(_finalize_reference_group(active))
                    active = None
                if heading_level <= reference_heading_level:
                    in_references = False
                else:
                    reference_region_paths.add(paragraph.locator)
                continue

            reference_region_paths.add(paragraph.locator)
            if paragraph.locator in consumed_table_paths:
                continue
            if not paragraph.text.strip():
                continue

            row = _nearest_ancestor(paragraph.element, f"{_W}tr")
            if row is not None:
                row_locator = root.getroottree().getpath(row)
                if row_locator not in inspected_table_rows:
                    inspected_table_rows.add(row_locator)
                    table_values, row_paths = _table_reference_group_values(
                        row,
                        part_name=part_name,
                        paragraph_indexes=paragraph_indexes,
                    )
                    reference_region_paths.update(row_paths)
                    if table_values is not None:
                        if active is not None:
                            groups.append(_finalize_reference_group(active))
                            active = None
                        source_order += 1
                        table_values["source_order"] = source_order
                        groups.append(_finalize_reference_group(table_values))
                        consumed_table_paths.update(row_paths)
                        continue

            explicit_match = _REFERENCE_ENTRY_RE.match(paragraph.text)
            source_number: int | None = None
            entry_text = paragraph.text.strip()
            numbering_kind: ReferenceNumberingKind | None = None
            if explicit_match:
                source_number = int(explicit_match.group(1) or explicit_match.group(2))
                entry_text = explicit_match.group(3).strip()
                numbering_kind = "explicit"
            else:
                source_number = _numbered_paragraph_value(
                    paragraph.element,
                    numbering_levels=numbering_levels,
                    counters=counters,
                )
                if source_number is not None:
                    numbering_kind = "automatic"
            if source_number is not None:
                if active is not None:
                    groups.append(_finalize_reference_group(active))
                source_order += 1
                active = {
                    "source_number": source_number,
                    "texts": [entry_text],
                    "part_name": part_name,
                    "paragraph_indexes": [paragraph.index],
                    "locators": [paragraph.locator],
                    "bookmark_names": list(
                        _paragraph_bookmark_names(paragraph.element)
                    ),
                    "numbering_kind": numbering_kind,
                    "source_order": source_order,
                }
            elif active is not None:
                active["texts"].append(paragraph.text.strip())
                active["paragraph_indexes"].append(paragraph.index)
                active["locators"].append(paragraph.locator)
                active["bookmark_names"].extend(
                    _paragraph_bookmark_names(paragraph.element)
                )
        if active is not None:
            groups.append(_finalize_reference_group(active))
    return tuple(groups), frozenset(reference_region_paths)


def _table_reference_group_values(
    row: etree._Element,
    *,
    part_name: str,
    paragraph_indexes: dict[str, int],
) -> tuple[dict[str, object] | None, tuple[str, ...]]:
    tree = row.getroottree()
    row_paragraphs = tuple(row.iter(f"{_W}p"))
    row_paths = tuple(tree.getpath(paragraph) for paragraph in row_paragraphs)
    cells = tuple(row.findall("w:tc", _NS))
    if len(cells) < 2:
        return None, row_paths

    cell_texts = tuple(_normalize_space(_element_text(cell)) for cell in cells)
    first_nonempty = next(
        (index for index, value in enumerate(cell_texts) if value),
        None,
    )
    if first_nonempty is None or first_nonempty >= len(cells) - 1:
        return None, row_paths
    number_match = _REFERENCE_TABLE_NUMBER_RE.fullmatch(cell_texts[first_nonempty])
    if number_match is None:
        return None, row_paths
    entry_cells = tuple(value for value in cell_texts[first_nonempty + 1 :] if value)
    if not entry_cells:
        return None, row_paths

    number_cell_paragraphs = tuple(cells[first_nonempty].iter(f"{_W}p"))
    entry_paragraphs = tuple(
        paragraph
        for cell in cells[first_nonempty + 1 :]
        for paragraph in cell.iter(f"{_W}p")
        if _element_text(paragraph).strip()
    )
    group_paragraphs = number_cell_paragraphs + entry_paragraphs
    group_paths = tuple(tree.getpath(paragraph) for paragraph in group_paragraphs)
    return (
        {
            "source_number": int(number_match.group(1) or number_match.group(2)),
            "texts": ["\n".join(entry_cells)],
            "part_name": part_name,
            "paragraph_indexes": [paragraph_indexes[path] for path in group_paths],
            "locators": list(group_paths),
            "bookmark_names": [
                name
                for paragraph in group_paragraphs
                for name in _paragraph_bookmark_names(paragraph)
            ],
            "numbering_kind": "table_cell",
        },
        row_paths,
    )


def _finalize_reference_group(values: dict[str, object]) -> SourceReferenceGroup:
    raw_text = "\n".join(str(value) for value in values["texts"])
    return SourceReferenceGroup(
        source_number=int(values["source_number"]),
        raw_text=raw_text,
        part_name=str(values["part_name"]),
        paragraph_indexes=tuple(int(value) for value in values["paragraph_indexes"]),
        locators=tuple(str(value) for value in values["locators"]),
        bookmark_names=tuple(
            dict.fromkeys(str(value) for value in values["bookmark_names"])
        ),
        numbering_kind=str(values["numbering_kind"]),
        source_order=int(values["source_order"]),
        content_digest=hashlib.sha256(
            unicodedata.normalize("NFKC", raw_text).strip().encode("utf-8")
        ).hexdigest(),
    )


def _scan_citations(
    roots: dict[str, etree._Element],
    *,
    reference_groups: tuple[SourceReferenceGroup, ...],
    reference_region_paths: frozenset[str],
    hyperlinks: tuple[SourceInternalHyperlink, ...],
    fields: tuple[SourceField, ...],
) -> tuple[SourceCitationOccurrence, ...]:
    occurrences: list[SourceCitationOccurrence] = []
    reference_paths = {
        locator for group in reference_groups for locator in group.locators
    }
    bookmark_to_number = {
        name: group.source_number
        for group in reference_groups
        for name in group.bookmark_names
    }

    for part_name, root in roots.items():
        complex_field_result_nodes = _balanced_complex_field_result_nodes(root)
        for paragraph in _paragraph_records(root):
            if (
                paragraph.locator in reference_paths
                or paragraph.locator in reference_region_paths
            ):
                continue
            text, fragments = _paragraph_text_fragments(
                paragraph.element,
                complex_field_result_nodes=complex_field_result_nodes,
            )
            for match in _CITATION_MARKER_RE.finditer(text):
                if _is_embedded_clinical_notation(text, match.start()):
                    continue
                overlapping = [
                    fragment
                    for fragment in fragments
                    if fragment.start < match.end() and fragment.end > match.start()
                ]
                if not overlapping:
                    continue
                if any(
                    fragment.inside_hyperlink
                    or fragment.inside_simple_field
                    or fragment.inside_balanced_complex_field
                    for fragment in overlapping
                ):
                    continue
                if any(fragment.excluded_note_marker for fragment in overlapping):
                    continue
                superscript = all(fragment.superscript for fragment in overlapping)
                occurrences.append(
                    SourceCitationOccurrence(
                        raw_text=match.group(0),
                        source_numbers=_expand_marker(match.group(0)),
                        part_name=part_name,
                        story_kind=_story_kind(part_name),
                        paragraph_index=paragraph.index,
                        locator=f"{paragraph.locator}:chars:{match.start()}-{match.end()}",
                        binding_kind=(
                            "superscript" if superscript else "plain_candidate"
                        ),
                        ambiguous=not superscript,
                    )
                )

    for hyperlink in hyperlinks:
        numbers = _parse_marker(hyperlink.text)
        if not numbers and hyperlink.anchor in bookmark_to_number:
            numbers = (bookmark_to_number[hyperlink.anchor],)
        if not numbers:
            continue
        occurrences.append(
            SourceCitationOccurrence(
                raw_text=hyperlink.text,
                source_numbers=numbers,
                part_name=hyperlink.part_name,
                story_kind=_story_kind(hyperlink.part_name),
                paragraph_index=_paragraph_index_for_locator(
                    roots[hyperlink.part_name],
                    hyperlink.locator,
                ),
                locator=hyperlink.locator,
                binding_kind="internal_hyperlink",
                target_bookmark=hyperlink.anchor,
            )
        )

    for field in fields:
        if field.unsupported_manager:
            if field.balanced and field.manager_result_numbers:
                occurrences.append(
                    SourceCitationOccurrence(
                        raw_text=field.result_text,
                        source_numbers=field.manager_result_numbers,
                        part_name=field.part_name,
                        story_kind=_story_kind(field.part_name),
                        paragraph_index=_paragraph_index_for_locator(
                            roots[field.part_name],
                            field.locator,
                        ),
                        locator=field.locator,
                        binding_kind="manager_field",
                        field_instruction=field.instruction,
                    )
                )
            continue
        if (
            not field.balanced
            or _EXCLUDED_FIELD_RE.match(field.instruction)
            or field.field_kind not in {"REF", "HYPERLINK"}
        ):
            continue
        numbers = _parse_marker(field.result_text)
        if not numbers and field.target in bookmark_to_number:
            numbers = (bookmark_to_number[field.target],)
        if not numbers and re.fullmatch(r"\s*\d{1,4}\s*", field.result_text):
            numbers = (int(field.result_text.strip()),)
        if not numbers:
            continue
        occurrences.append(
            SourceCitationOccurrence(
                raw_text=field.result_text,
                source_numbers=numbers,
                part_name=field.part_name,
                story_kind=_story_kind(field.part_name),
                paragraph_index=_paragraph_index_for_locator(
                    roots[field.part_name],
                    field.locator,
                ),
                locator=field.locator,
                binding_kind="simple_field" if field.simple else "complex_field",
                target_bookmark=field.target,
                field_instruction=field.instruction,
            )
        )
    occurrences.sort(key=_citation_sort_key)
    return tuple(_deduplicate_occurrences(occurrences))


def _citation_sort_key(
    occurrence: SourceCitationOccurrence,
) -> tuple[tuple[int, str], int, tuple[tuple[int, object], ...], int]:
    binding_order = {
        "internal_hyperlink": 0,
        "simple_field": 1,
        "complex_field": 2,
        "manager_field": 3,
        "superscript": 4,
        "plain_candidate": 5,
    }
    return (
        _story_sort_key(occurrence.part_name),
        occurrence.paragraph_index,
        _natural_locator_key(occurrence.locator),
        binding_order[occurrence.binding_kind],
    )


def _natural_locator_key(value: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (1, int(token)) if token.isdigit() else (0, token)
        for token in re.split(r"(\d+)", str(value or ""))
        if token
    )


def _deduplicate_occurrences(
    occurrences: list[SourceCitationOccurrence],
) -> list[SourceCitationOccurrence]:
    result: list[SourceCitationOccurrence] = []
    seen: set[tuple[str, int, str, tuple[int, ...], str]] = set()
    for occurrence in occurrences:
        key = (
            occurrence.part_name,
            occurrence.paragraph_index,
            occurrence.locator,
            occurrence.source_numbers,
            occurrence.binding_kind,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(occurrence)
    return result


def _build_manifest_issues(
    *,
    citations: tuple[SourceCitationOccurrence, ...],
    reference_groups: tuple[SourceReferenceGroup, ...],
    bookmarks: tuple[SourceBookmark, ...],
    hyperlinks: tuple[SourceInternalHyperlink, ...],
    fields: tuple[SourceField, ...],
    initial_issues: list[SourceReferenceIssue],
) -> tuple[SourceReferenceIssue, ...]:
    issues = list(initial_issues)
    groups_by_number: dict[int, list[SourceReferenceGroup]] = {}
    for group in reference_groups:
        groups_by_number.setdefault(group.source_number, []).append(group)
    for source_number, groups in sorted(groups_by_number.items()):
        if len(groups) > 1:
            issues.append(
                SourceReferenceIssue(
                    code="duplicate_reference_number",
                    severity="blocking",
                    message="multiple reference groups use the same source number",
                    part_name=groups[1].part_name,
                    locator=groups[1].locators[0],
                    source_number=source_number,
                )
            )

    groups_by_content: dict[str, list[SourceReferenceGroup]] = {}
    for group in reference_groups:
        groups_by_content.setdefault(group.content_digest, []).append(group)
    for duplicate_groups in groups_by_content.values():
        source_numbers = {group.source_number for group in duplicate_groups}
        if len(source_numbers) <= 1:
            continue
        second = duplicate_groups[1]
        issues.append(
            SourceReferenceIssue(
                code="duplicate_reference_content",
                severity="blocking",
                message="the same reference entry is assigned to multiple source numbers",
                part_name=second.part_name,
                locator=second.locators[0],
                source_number=second.source_number,
            )
        )

    if groups_by_number:
        expected = set(range(1, max(groups_by_number) + 1))
        for source_number in sorted(expected - set(groups_by_number)):
            issues.append(
                SourceReferenceIssue(
                    code="missing_reference_number",
                    severity="blocking",
                    message="reference list numbering contains a gap",
                    source_number=source_number,
                )
            )

    for citation in citations:
        if citation.ambiguous:
            issues.append(
                SourceReferenceIssue(
                    code="ambiguous_plain_citation_candidate",
                    severity="notice",
                    message=(
                        "plain non-superscript bracket text requires explicit binding"
                    ),
                    part_name=citation.part_name,
                    locator=citation.locator,
                )
            )
            continue
        for source_number in citation.source_numbers:
            if source_number not in groups_by_number:
                issues.append(
                    SourceReferenceIssue(
                        code="missing_reference_entry",
                        severity="blocking",
                        message="citation points to a missing reference entry",
                        part_name=citation.part_name,
                        locator=citation.locator,
                        source_number=source_number,
                    )
                )

    bookmark_names = {bookmark.name for bookmark in bookmarks if bookmark.name}
    reference_bookmarks = {
        name for group in reference_groups for name in group.bookmark_names
    }
    for hyperlink in hyperlinks:
        if _parse_marker(hyperlink.text) and hyperlink.anchor not in bookmark_names:
            issues.append(
                SourceReferenceIssue(
                    code="missing_internal_citation_anchor",
                    severity="blocking",
                    message="citation hyperlink target bookmark does not exist",
                    part_name=hyperlink.part_name,
                    locator=hyperlink.locator,
                )
            )
    for field in fields:
        if (
            field.field_kind in {"REF", "HYPERLINK"}
            and field.target
            and (
                _parse_marker(field.result_text) or field.target in reference_bookmarks
            )
            and field.target not in bookmark_names
        ):
            issues.append(
                SourceReferenceIssue(
                    code="missing_internal_citation_anchor",
                    severity="blocking",
                    message="citation field target bookmark does not exist",
                    part_name=field.part_name,
                    locator=field.locator,
                )
            )

    cited = {
        source_number
        for citation in citations
        if not citation.ambiguous
        for source_number in citation.source_numbers
    }
    for group in reference_groups:
        if group.source_number not in cited:
            issues.append(
                SourceReferenceIssue(
                    code="uncited_reference_entry",
                    severity="notice",
                    message=(
                        "uncited reference is retained after first-occurrence cited entries "
                        "as an explicit review notice"
                    ),
                    part_name=group.part_name,
                    locator=group.locators[0],
                    source_number=group.source_number,
                )
            )
    return tuple(_deduplicate_issues(issues))


def _deduplicate_issues(
    issues: list[SourceReferenceIssue],
) -> list[SourceReferenceIssue]:
    result: list[SourceReferenceIssue] = []
    seen: set[tuple[str, str, str, int | None]] = set()
    for issue in issues:
        key = (issue.code, issue.part_name, issue.locator, issue.source_number)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return result


def _read_paragraph_styles(
    payload: bytes,
) -> dict[str, _ParagraphStyleDefinition]:
    if not payload:
        return {}
    try:
        root = etree.fromstring(
            payload,
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError as exc:
        raise SourceReferenceScanError("invalid Word styles part") from exc

    result: dict[str, _ParagraphStyleDefinition] = {}
    for style in root.findall("w:style", _NS):
        if str(style.get(f"{_W}type") or "") not in {"", "paragraph"}:
            continue
        style_id = str(style.get(f"{_W}styleId") or "")
        if not style_id:
            continue
        name_node = style.find("w:name", _NS)
        based_on_node = style.find("w:basedOn", _NS)
        outline_node = style.find("w:pPr/w:outlineLvl", _NS)
        outline_level: int | None = None
        if outline_node is not None:
            try:
                parsed = int(str(outline_node.get(f"{_W}val") or "9"))
            except ValueError:
                parsed = 9
            if 0 <= parsed <= 8:
                outline_level = parsed
        result[style_id] = _ParagraphStyleDefinition(
            style_id=style_id,
            name=(
                str(name_node.get(f"{_W}val") or "") if name_node is not None else ""
            ),
            based_on=(
                str(based_on_node.get(f"{_W}val") or "")
                if based_on_node is not None
                else ""
            ),
            outline_level=outline_level,
        )
    return result


def _read_numbering_levels(payload: bytes) -> dict[tuple[str, int], _NumberingLevel]:
    if not payload:
        return {}
    try:
        root = etree.fromstring(
            payload,
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError:
        return {}
    abstract_levels: dict[tuple[str, int], _NumberingLevel] = {}
    for abstract in root.findall("w:abstractNum", _NS):
        abstract_id = str(abstract.get(f"{_W}abstractNumId") or "")
        for level in abstract.findall("w:lvl", _NS):
            try:
                ilvl = int(level.get(f"{_W}ilvl") or "0")
            except ValueError:
                continue
            start_node = level.find("w:start", _NS)
            format_node = level.find("w:numFmt", _NS)
            text_node = level.find("w:lvlText", _NS)
            try:
                start = int(
                    (start_node.get(f"{_W}val") if start_node is not None else "1")
                    or "1"
                )
            except ValueError:
                start = 1
            abstract_levels[(abstract_id, ilvl)] = _NumberingLevel(
                start=max(1, start),
                number_format=(
                    str(format_node.get(f"{_W}val") or "")
                    if format_node is not None
                    else ""
                ),
                level_text=(
                    str(text_node.get(f"{_W}val") or "")
                    if text_node is not None
                    else ""
                ),
            )
    result: dict[tuple[str, int], _NumberingLevel] = {}
    for num in root.findall("w:num", _NS):
        num_id = str(num.get(f"{_W}numId") or "")
        abstract_node = num.find("w:abstractNumId", _NS)
        if abstract_node is None:
            continue
        abstract_id = str(abstract_node.get(f"{_W}val") or "")
        overrides: dict[int, int] = {}
        for override in num.findall("w:lvlOverride", _NS):
            try:
                ilvl = int(override.get(f"{_W}ilvl") or "0")
            except ValueError:
                continue
            start_override = override.find("w:startOverride", _NS)
            if start_override is not None:
                try:
                    overrides[ilvl] = int(start_override.get(f"{_W}val") or "1")
                except ValueError:
                    pass
        for (candidate_abstract_id, ilvl), level in abstract_levels.items():
            if candidate_abstract_id != abstract_id:
                continue
            result[(num_id, ilvl)] = _NumberingLevel(
                start=max(1, overrides.get(ilvl, level.start)),
                number_format=level.number_format,
                level_text=level.level_text,
            )
    return result


def _numbered_paragraph_value(
    paragraph: etree._Element,
    *,
    numbering_levels: dict[tuple[str, int], _NumberingLevel],
    counters: dict[tuple[str, int], int],
) -> int | None:
    num_pr = paragraph.find("w:pPr/w:numPr", _NS)
    if num_pr is None:
        return None
    num_id_node = num_pr.find("w:numId", _NS)
    ilvl_node = num_pr.find("w:ilvl", _NS)
    if num_id_node is None:
        return None
    num_id = str(num_id_node.get(f"{_W}val") or "")
    try:
        ilvl = int(
            str(ilvl_node.get(f"{_W}val") or "0") if ilvl_node is not None else "0"
        )
    except ValueError:
        return None
    level = numbering_levels.get((num_id, ilvl))
    if (
        level is None
        or level.number_format != "decimal"
        or "%1" not in level.level_text
        or ilvl != 0
    ):
        return None
    key = (num_id, ilvl)
    value = counters.setdefault(key, level.start)
    counters[key] = value + 1
    return value


def _paragraph_records(root: etree._Element) -> tuple[_ParagraphRecord, ...]:
    tree = root.getroottree()
    records: list[_ParagraphRecord] = []
    for index, paragraph in enumerate(root.iter(f"{_W}p")):
        records.append(
            _ParagraphRecord(
                element=paragraph,
                index=index,
                locator=tree.getpath(paragraph),
                text=_element_text(paragraph),
            )
        )
    return tuple(records)


def _paragraph_text_fragments(
    paragraph: etree._Element,
    *,
    complex_field_result_nodes: set[etree._Element],
) -> tuple[str, tuple[_TextFragment, ...]]:
    text_parts: list[str] = []
    fragments: list[_TextFragment] = []
    cursor = 0
    for text_node in paragraph.iter(f"{_W}t"):
        value = str(text_node.text or "")
        if not value:
            continue
        run = _nearest_ancestor(text_node, f"{_W}r")
        superscript = False
        excluded = False
        if run is not None:
            vertical = run.find("w:rPr/w:vertAlign", _NS)
            superscript = (
                vertical is not None
                and str(vertical.get(f"{_W}val") or "") == "superscript"
            )
            excluded = (
                run.find("w:footnoteReference", _NS) is not None
                or run.find("w:endnoteReference", _NS) is not None
                or _run_is_note_reference_style(run)
            )
        fragments.append(
            _TextFragment(
                start=cursor,
                end=cursor + len(value),
                superscript=superscript,
                excluded_note_marker=excluded,
                inside_hyperlink=_has_ancestor(text_node, f"{_W}hyperlink"),
                inside_simple_field=_has_ancestor(text_node, f"{_W}fldSimple"),
                inside_balanced_complex_field=text_node in complex_field_result_nodes,
            )
        )
        text_parts.append(value)
        cursor += len(value)
    return "".join(text_parts), tuple(fragments)


def _balanced_complex_field_result_nodes(
    story_root: etree._Element,
) -> set[etree._Element]:
    """Return result text nodes only for complex fields closed in this story."""

    stack: list[tuple[bool, list[etree._Element]]] = []
    result_nodes: set[etree._Element] = set()
    for node in story_root.iter():
        if node.tag == f"{_W}fldSimple" or _has_ancestor(node, f"{_W}fldSimple"):
            continue
        if node.tag == f"{_W}fldChar":
            field_type = str(node.get(f"{_W}fldCharType") or "")
            if field_type == "begin":
                stack.append((False, []))
            elif field_type == "separate" and stack:
                _, nodes = stack[-1]
                stack[-1] = (True, nodes)
            elif field_type == "end" and stack:
                _, nodes = stack.pop()
                result_nodes.update(nodes)
            continue
        if node.tag == f"{_W}t":
            for separated, nodes in stack:
                if separated:
                    nodes.append(node)
    return result_nodes


def _run_is_note_reference_style(run: etree._Element) -> bool:
    style = run.find("w:rPr/w:rStyle", _NS)
    if style is None:
        return False
    value = str(style.get(f"{_W}val") or "").lower()
    return value in {"footnotereference", "endnotereference", "脚注引用", "尾注引用"}


def _paragraph_heading_level(
    paragraph: etree._Element,
    *,
    paragraph_styles: dict[str, _ParagraphStyleDefinition],
) -> int | None:
    direct_outline = paragraph.find("w:pPr/w:outlineLvl", _NS)
    if direct_outline is not None:
        try:
            parsed = int(str(direct_outline.get(f"{_W}val") or "9"))
        except ValueError:
            parsed = 9
        if 0 <= parsed <= 8:
            return parsed

    style_node = paragraph.find("w:pPr/w:pStyle", _NS)
    if style_node is None:
        return None
    style_id = str(style_node.get(f"{_W}val") or "")
    visited: set[str] = set()
    while style_id and style_id not in visited:
        visited.add(style_id)
        definition = paragraph_styles.get(style_id)
        candidates = [style_id]
        if definition is not None:
            if definition.outline_level is not None:
                return definition.outline_level
            candidates.append(definition.name)
        for candidate in candidates:
            match = _HEADING_STYLE_RE.fullmatch(
                _normalize_space(candidate).replace("_", " ")
            )
            if match is not None:
                return int(match.group(1)) - 1
        if definition is None:
            break
        style_id = definition.based_on
    return None


def _paragraph_bookmark_names(paragraph: etree._Element) -> tuple[str, ...]:
    return tuple(
        name
        for node in paragraph.iter(f"{_W}bookmarkStart")
        if (name := str(node.get(f"{_W}name") or "").strip())
    )


def _paragraph_index_for_locator(
    root: etree._Element,
    locator: str,
) -> int:
    tree = root.getroottree()
    try:
        nodes = tree.xpath(locator, namespaces=_NS)
    except etree.XPathError:
        return -1
    if not nodes:
        return -1
    node = nodes[0]
    paragraph = node if node.tag == f"{_W}p" else _nearest_ancestor(node, f"{_W}p")
    if paragraph is None:
        return -1
    for index, candidate in enumerate(root.iter(f"{_W}p")):
        if candidate is paragraph:
            return index
    return -1


def _parse_marker(value: str) -> tuple[int, ...]:
    normalized = str(value or "").strip()
    if not _STRICT_MARKER_RE.fullmatch(normalized):
        return ()
    return _expand_marker(normalized)


def _expand_marker(value: str) -> tuple[int, ...]:
    inner = value.strip()[1:-1]
    numbers: list[int] = []
    for item in re.split(r"[,，]", inner):
        range_match = _RANGE_RE.fullmatch(item)
        if range_match:
            start, end = (int(range_match.group(1)), int(range_match.group(2)))
            if start <= end and end - start <= 1000:
                numbers.extend(range(start, end + 1))
            continue
        stripped = item.strip()
        if stripped.isdigit():
            numbers.append(int(stripped))
    return tuple(dict.fromkeys(numbers))


def _is_embedded_clinical_notation(text: str, start: int) -> bool:
    if start <= 0:
        return False
    return bool(_TRAILING_ASCII_ACRONYM_RE.search(text[:start]))


def _element_text(element: etree._Element) -> str:
    return "".join(str(node.text or "") for node in element.iter(f"{_W}t"))


def _normalize_heading(value: str) -> str:
    return _normalize_space(unicodedata.normalize("NFKC", value)).strip(" ：:")


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _nearest_ancestor(
    node: etree._Element,
    tag: str,
) -> etree._Element | None:
    current = node.getparent()
    while current is not None:
        if current.tag == tag:
            return current
        current = current.getparent()
    return None


def _has_ancestor(node: etree._Element, tag: str) -> bool:
    return _nearest_ancestor(node, tag) is not None
