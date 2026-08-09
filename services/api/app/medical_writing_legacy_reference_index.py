from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterator, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit

from packages.contracts.workbench_contracts import ProtocolDocument


_REFERENCE_ENTRY_RE = re.compile(
    r"^\s*(?:\[\s*(\d{1,4})\s*\]|(\d{1,4})[.、])\s*(\S.*)\s*$",
    re.DOTALL,
)
_REFERENCE_HEADING_RE = re.compile(r"(?:参考文献|references)\s*$", re.IGNORECASE)
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
_PMID_RE = re.compile(
    r"(?:\bPMID\s*[:：]?\s*|pubmed\.ncbi\.nlm\.nih\.gov/)(\d{5,10})\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s<>\[\]{}]+", re.IGNORECASE)
_TITLE_WITH_TYPE_RE = re.compile(
    r"(?:^|[.。]\s*)([^.。]+?)\s*\[[A-Z/]+\]",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_CITATION_MARKER_RE = re.compile(
    r"^\[\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?"
    r"(?:\s*[,，]\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?)*\s*\]$"
)
_RANGE_RE = re.compile(r"^\s*(\d{1,4})\s*[-‐‑‒–—]\s*(\d{1,4})\s*$")


@dataclass(frozen=True)
class LegacyReferenceSource:
    source_number: int
    raw_text: str
    block_id: str
    source_locator: str


@dataclass(frozen=True)
class LegacyReferenceEntry:
    reference_id: str
    raw_text: str
    source_number: int
    block_id: str
    source_locator: str
    normalized_text: str
    doi: str
    pmid: str
    url: str
    normalized_title: str
    year: str
    sources: tuple[LegacyReferenceSource, ...]

    @property
    def source_numbers(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(source.source_number for source in self.sources))


@dataclass(frozen=True)
class LegacyReferenceOccurrence:
    raw_text: str
    source_numbers: tuple[int, ...]
    reference_ids: tuple[str, ...]
    missing_numbers: tuple[int, ...]
    section_id: str
    block_id: str
    source_locator: str
    node_path: str


@dataclass(frozen=True)
class LegacyReferenceIssue:
    code: Literal[
        "duplicate_number",
        "missing_entry",
        "unparsed_entry",
        "uncited_entry",
        "number_gap",
    ]
    severity: Literal["blocking", "notice"]
    message: str
    source_number: int | None = None
    reference_id: str = ""
    block_id: str = ""
    source_locator: str = ""

    @property
    def blocking(self) -> bool:
        return self.severity == "blocking"


@dataclass(frozen=True)
class LegacyReferenceIndex:
    entries: tuple[LegacyReferenceEntry, ...]
    occurrences: tuple[LegacyReferenceOccurrence, ...]
    number_to_reference_id: Mapping[int, str]
    issues: tuple[LegacyReferenceIssue, ...]
    source_digest: str


@dataclass(frozen=True)
class _ReferenceCandidate:
    source_number: int
    raw_text: str
    normalized_text: str
    doi: str
    pmid: str
    url: str
    normalized_title: str
    year: str
    block_id: str
    source_locator: str


@dataclass(frozen=True)
class _UnparsedReferenceBlock:
    raw_text: str
    block_id: str
    source_locator: str


def build_legacy_reference_index(document: ProtocolDocument) -> LegacyReferenceIndex:
    """Build a deterministic, read-only index of references already in a protocol."""

    candidates, reference_blocks, unparsed_blocks = _collect_reference_candidates(document)
    entries, candidate_reference_ids = _deduplicate_candidates(document.project_id, candidates)

    number_to_reference_id: dict[int, str] = {}
    candidates_by_number: dict[int, list[int]] = {}
    for candidate_index, candidate in enumerate(candidates):
        candidates_by_number.setdefault(candidate.source_number, []).append(candidate_index)
        number_to_reference_id.setdefault(
            candidate.source_number,
            candidate_reference_ids[candidate_index],
        )

    occurrences = _collect_occurrences(document, reference_blocks, number_to_reference_id)
    issues = _build_issues(
        candidates=candidates,
        entries=entries,
        occurrences=occurrences,
        candidates_by_number=candidates_by_number,
        unparsed_blocks=unparsed_blocks,
    )
    return LegacyReferenceIndex(
        entries=entries,
        occurrences=occurrences,
        number_to_reference_id=MappingProxyType(dict(sorted(number_to_reference_id.items()))),
        issues=issues,
        source_digest=_source_digest(document),
    )


index_legacy_references = build_legacy_reference_index


def parse_legacy_reference_marker(value: str) -> tuple[int, ...]:
    """Parse only a strict bracketed numeric citation marker."""

    marker = str(value or "")
    if not _CITATION_MARKER_RE.fullmatch(marker):
        return ()
    return _expand_marker(marker)


def is_superscript_reference_marker(node: Mapping[str, Any]) -> bool:
    """Use imported DOCX superscript structure to exclude clinical bracket notation."""

    return _has_superscript_mark(node) and bool(
        parse_legacy_reference_marker(str(node.get("text") or ""))
    )


def is_reference_heading(value: str) -> bool:
    """Recognize Chinese and English bibliography headings with one rule."""

    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    return bool(_REFERENCE_HEADING_RE.search(normalized))


def _collect_reference_candidates(
    document: ProtocolDocument,
) -> tuple[
    list[_ReferenceCandidate],
    set[tuple[int, int]],
    list[_UnparsedReferenceBlock],
]:
    candidates: list[_ReferenceCandidate] = []
    reference_blocks: set[tuple[int, int]] = set()
    unparsed_blocks: list[_UnparsedReferenceBlock] = []
    automatic_number_counters: dict[tuple[int, str, int], int] = {}
    for section_index, section in enumerate(document.sections):
        in_reference_section = is_reference_heading(section.heading)
        for block_index, block in enumerate(section.content_blocks):
            if (
                str(block.get("block_type") or "").strip().lower() == "heading"
                and is_reference_heading(str(block.get("text") or ""))
            ):
                in_reference_section = True
            if not in_reference_section:
                continue
            reference_blocks.add((section_index, block_index))
            raw_text = str(block.get("text") or "")
            if not raw_text.strip() or is_reference_heading(raw_text):
                continue
            match = _REFERENCE_ENTRY_RE.match(raw_text)
            automatic_number = None
            if not match:
                automatic_number = _word_automatic_reference_number(
                    block,
                    section_index=section_index,
                    counters=automatic_number_counters,
                )
            if not match and automatic_number is None:
                unparsed_blocks.append(
                    _UnparsedReferenceBlock(
                        raw_text=raw_text,
                        block_id=str(block.get("block_id") or ""),
                        source_locator=str(block.get("source_locator") or ""),
                    )
                )
                continue
            if match:
                source_number = int(match.group(1) or match.group(2))
                entry_text = match.group(3).strip()
            else:
                source_number = automatic_number
                entry_text = raw_text.strip()
            candidates.append(
                _ReferenceCandidate(
                    source_number=source_number,
                    raw_text=raw_text,
                    normalized_text=_normalize_reference_text(entry_text),
                    doi=_normalize_doi(entry_text),
                    pmid=_normalize_pmid(entry_text),
                    url=_normalize_publication_url(entry_text),
                    normalized_title=_normalize_reference_title(entry_text),
                    year=_unambiguous_year(entry_text),
                    block_id=str(block.get("block_id") or ""),
                    source_locator=str(block.get("source_locator") or ""),
                )
            )
    return candidates, reference_blocks, unparsed_blocks


def _word_automatic_reference_number(
    block: Mapping[str, Any],
    *,
    section_index: int,
    counters: dict[tuple[int, str, int], int],
) -> int | None:
    """Resolve a decimal Word list only when its numbering metadata is explicit."""

    num_id = str(block.get("num_id") or "").strip()
    level_text = unicodedata.normalize(
        "NFKC",
        str(block.get("numbering_level_text") or ""),
    ).strip()
    if (
        not num_id
        or str(block.get("numbering_format") or "").strip() != "decimal"
        or "%1" not in level_text
    ):
        return None
    try:
        level = int(block.get("ilvl"))
    except (TypeError, ValueError):
        return None
    if level != 0:
        return None
    key = (section_index, num_id, level)
    if key not in counters:
        start = _positive_int(block.get("numbering_start_override"))
        if start is None:
            start = _positive_int(block.get("numbering_start"))
        counters[key] = start or 1
    number = counters[key]
    counters[key] += 1
    return number


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _deduplicate_candidates(
    project_id: str,
    candidates: list[_ReferenceCandidate],
) -> tuple[tuple[LegacyReferenceEntry, ...], dict[int, str]]:
    if not candidates:
        return (), {}

    groups: list[list[int]] = []
    for index, candidate in enumerate(candidates):
        matching_groups = [
            group
            for group in groups
            if not _identity_conflicts(candidate, (candidates[item] for item in group))
            and any(_same_reference_identity(candidate, candidates[item]) for item in group)
        ]
        if len(matching_groups) == 1:
            matching_groups[0].append(index)
        else:
            # Multiple possible groups are ambiguous; keep the candidate independent.
            groups.append([index])

    entries: list[LegacyReferenceEntry] = []
    candidate_reference_ids: dict[int, str] = {}
    for indexes in groups:
        group = [candidates[index] for index in indexes]
        dois = sorted({candidate.doi for candidate in group if candidate.doi})
        pmids = sorted({candidate.pmid for candidate in group if candidate.pmid})
        urls = sorted({candidate.url for candidate in group if candidate.url})
        title_years = sorted(
            {
                f"{candidate.normalized_title}|{candidate.year}"
                for candidate in group
                if candidate.normalized_title and candidate.year
            }
        )
        if dois:
            canonical_key = f"doi:{dois[0]}"
        elif pmids:
            canonical_key = f"pmid:{pmids[0]}"
        elif urls:
            canonical_key = f"url:{urls[0]}"
        elif title_years:
            canonical_key = f"title_year:{title_years[0]}"
        else:
            canonical_key = f"text:{min(candidate.normalized_text for candidate in group)}"
        reference_id = "mwref_" + hashlib.sha256(
            f"{project_id}|{canonical_key}".encode("utf-8")
        ).hexdigest()[:20]
        primary = group[0]
        sources = tuple(
            LegacyReferenceSource(
                source_number=candidate.source_number,
                raw_text=candidate.raw_text,
                block_id=candidate.block_id,
                source_locator=candidate.source_locator,
            )
            for candidate in group
        )
        unambiguous_title_year = title_years[0] if len(title_years) == 1 else ""
        normalized_title, year = (
            unambiguous_title_year.split("|", 1)
            if unambiguous_title_year
            else ("", "")
        )
        entries.append(
            LegacyReferenceEntry(
                reference_id=reference_id,
                raw_text=primary.raw_text,
                source_number=primary.source_number,
                block_id=primary.block_id,
                source_locator=primary.source_locator,
                normalized_text=primary.normalized_text,
                doi=dois[0] if dois else "",
                pmid=pmids[0] if pmids else "",
                url=urls[0] if urls else "",
                normalized_title=normalized_title,
                year=year,
                sources=sources,
            )
        )
        for index in indexes:
            candidate_reference_ids[index] = reference_id
    return tuple(entries), candidate_reference_ids


def _collect_occurrences(
    document: ProtocolDocument,
    reference_blocks: set[tuple[int, int]],
    number_to_reference_id: Mapping[int, str],
) -> tuple[LegacyReferenceOccurrence, ...]:
    occurrences: list[LegacyReferenceOccurrence] = []
    for section_index, section in enumerate(document.sections):
        for block_index, block in enumerate(section.content_blocks):
            if (section_index, block_index) in reference_blocks:
                continue
            for rich_text, source_locator, path_prefix in _rich_text_containers(block):
                for node, node_path in _text_nodes(rich_text):
                    marker = str(node.get("text") or "")
                    if not is_superscript_reference_marker(node):
                        continue
                    numbers = parse_legacy_reference_marker(marker)
                    if not numbers:
                        continue
                    references = tuple(
                        number_to_reference_id[number]
                        for number in numbers
                        if number in number_to_reference_id
                    )
                    missing = tuple(number for number in numbers if number not in number_to_reference_id)
                    occurrences.append(
                        LegacyReferenceOccurrence(
                            raw_text=marker,
                            source_numbers=numbers,
                            reference_ids=references,
                            missing_numbers=missing,
                            section_id=section.section_id,
                            block_id=str(block.get("block_id") or ""),
                            source_locator=source_locator,
                            node_path=f"{path_prefix}{node_path}",
                        )
                    )
    return tuple(occurrences)


def _build_issues(
    *,
    candidates: list[_ReferenceCandidate],
    entries: tuple[LegacyReferenceEntry, ...],
    occurrences: tuple[LegacyReferenceOccurrence, ...],
    candidates_by_number: Mapping[int, list[int]],
    unparsed_blocks: list[_UnparsedReferenceBlock],
) -> tuple[LegacyReferenceIssue, ...]:
    issues: list[LegacyReferenceIssue] = []
    for block in unparsed_blocks:
        issues.append(
            LegacyReferenceIssue(
                code="unparsed_entry",
                severity="blocking",
                message="reference-list block is non-empty but cannot be parsed as a numbered entry",
                block_id=block.block_id,
                source_locator=block.source_locator,
            )
        )
    for number in sorted(candidates_by_number):
        indexes = candidates_by_number[number]
        if len(indexes) < 2:
            continue
        duplicate = candidates[indexes[1]]
        issues.append(
            LegacyReferenceIssue(
                code="duplicate_number",
                severity="blocking",
                message=f"reference number {number} is defined more than once",
                source_number=number,
                block_id=duplicate.block_id,
                source_locator=duplicate.source_locator,
            )
        )

    missing_numbers = sorted(
        {number for occurrence in occurrences for number in occurrence.missing_numbers}
    )
    for number in missing_numbers:
        occurrence = next(item for item in occurrences if number in item.missing_numbers)
        issues.append(
            LegacyReferenceIssue(
                code="missing_entry",
                severity="blocking",
                message=f"cited reference number {number} has no reference-list entry",
                source_number=number,
                block_id=occurrence.block_id,
                source_locator=occurrence.source_locator,
            )
        )

    cited_reference_ids = {
        reference_id for occurrence in occurrences for reference_id in occurrence.reference_ids
    }
    for entry in entries:
        if entry.reference_id in cited_reference_ids:
            continue
        issues.append(
            LegacyReferenceIssue(
                code="uncited_entry",
                severity="notice",
                message=f"reference-list entry {entry.source_number} is not cited in body rich text",
                source_number=entry.source_number,
                reference_id=entry.reference_id,
                block_id=entry.block_id,
                source_locator=entry.source_locator,
            )
        )

    defined_numbers = set(candidates_by_number)
    if defined_numbers:
        for number in sorted(set(range(1, max(defined_numbers) + 1)) - defined_numbers):
            issues.append(
                LegacyReferenceIssue(
                    code="number_gap",
                    severity="notice",
                    message=f"reference list skips number {number}",
                    source_number=number,
                )
            )
    return tuple(issues)


def _rich_text_containers(
    block: Mapping[str, Any],
) -> Iterator[tuple[Mapping[str, Any], str, str]]:
    rich_text = block.get("rich_text")
    if isinstance(rich_text, Mapping):
        yield rich_text, str(block.get("source_locator") or ""), "rich_text"
    rows = block.get("rows")
    if not isinstance(rows, list):
        return
    for row_index, row in enumerate(rows):
        if not isinstance(row, list):
            continue
        for cell_index, cell in enumerate(row):
            if not isinstance(cell, Mapping) or not isinstance(cell.get("rich_text"), Mapping):
                continue
            yield (
                cell["rich_text"],
                str(cell.get("source_locator") or block.get("source_locator") or ""),
                f"rows[{row_index}][{cell_index}].rich_text",
            )


def _text_nodes(
    node: Mapping[str, Any],
    path: str = "",
) -> Iterator[tuple[Mapping[str, Any], str]]:
    if node.get("type") == "text":
        yield node, path
        return
    content = node.get("content")
    if not isinstance(content, list):
        return
    for index, child in enumerate(content):
        if isinstance(child, Mapping):
            yield from _text_nodes(child, f"{path}.content[{index}]")


def _has_superscript_mark(node: Mapping[str, Any]) -> bool:
    marks = node.get("marks")
    return isinstance(marks, list) and any(
        isinstance(mark, Mapping) and mark.get("type") == "superscript" for mark in marks
    )


def _expand_marker(marker: str) -> tuple[int, ...]:
    numbers: list[int] = []
    inner = marker.strip()[1:-1]
    for item in re.split(r"[,，]", inner):
        range_match = _RANGE_RE.fullmatch(item)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if end < start:
                return ()
            numbers.extend(range(start, end + 1))
        else:
            numbers.append(int(item.strip()))
    return tuple(dict.fromkeys(numbers))


def _normalize_reference_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_doi(value: str) -> str:
    match = _DOI_RE.search(value)
    if not match:
        return ""
    return match.group(0).rstrip(".,;:)]}>，。；：）】").lower()


def _normalize_pmid(value: str) -> str:
    match = _PMID_RE.search(value)
    return match.group(1) if match else ""


def _normalize_publication_url(value: str) -> str:
    for match in _URL_RE.finditer(value):
        raw_url = match.group(0).rstrip(".,;:)]}>，。；：）】")
        parsed = urlsplit(raw_url)
        host = (parsed.hostname or "").casefold()
        if not host or host in {"doi.org", "dx.doi.org"}:
            continue
        if host.startswith("www."):
            host = host[4:]
        path = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
        return urlunsplit(("https", host, path, parsed.query, ""))
    return ""


def _normalize_reference_title(value: str) -> str:
    matches = _TITLE_WITH_TYPE_RE.findall(value)
    if len(matches) != 1:
        return ""
    normalized = unicodedata.normalize("NFKC", matches[0]).casefold()
    return re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE)


def _unambiguous_year(value: str) -> str:
    years = tuple(dict.fromkeys(_YEAR_RE.findall(value)))
    return years[0] if len(years) == 1 else ""


def _same_reference_identity(
    left: _ReferenceCandidate,
    right: _ReferenceCandidate,
) -> bool:
    for field_name in ("doi", "pmid", "url"):
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        if left_value and right_value:
            return left_value == right_value
    if (
        left.normalized_title
        and right.normalized_title
        and left.year
        and right.year
    ):
        return (
            left.normalized_title == right.normalized_title
            and left.year == right.year
        )
    return left.normalized_text == right.normalized_text


def _identity_conflicts(
    candidate: _ReferenceCandidate,
    group: Iterator[_ReferenceCandidate],
) -> bool:
    members = tuple(group)
    for field_name in ("doi", "pmid", "url"):
        candidate_value = getattr(candidate, field_name)
        group_values = {
            getattr(member, field_name)
            for member in members
            if getattr(member, field_name)
        }
        if candidate_value and group_values and candidate_value not in group_values:
            return True
    return False


def _source_digest(document: ProtocolDocument) -> str:
    payload = json.dumps(
        document.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
