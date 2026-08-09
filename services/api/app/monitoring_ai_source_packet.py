from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .monitoring_ai_contracts import (
    MonitoringAiInputRevision,
    MonitoringAiSourceBinding,
    content_sha256,
)


@dataclass(frozen=True)
class MonitoringAiSourcePacket:
    input_revision: MonitoringAiInputRevision
    source_ids: tuple[str, ...]
    evidence_packet: tuple[dict[str, Any], ...]


PROTOCOL_EVIDENCE_PACKET_VERSION = "monitoring_protocol_evidence_packet_v3"
MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS = 200
MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS = 50
PROTOCOL_STRUCTURAL_REPAIR_VERSION = "monitoring_protocol_structural_repair_v2"
_PARAGRAPH_INDEX_RE = re.compile(r":paragraph:(\d+)$")
_TABLE_LOCATOR_RE = re.compile(
    r"^docx:table:(\d+):row:(\d+):cell:(\d+):paragraph:(\d+)$"
)
_LIST_ITEM_RE = re.compile(
    r"^\s*(?:"
    r"[（(]?[0-9一二三四五六七八九十百]+[）)、.)．]"
    r"|[①②③④⑤⑥⑦⑧⑨⑩]"
    r"|[-–—•●▪]"
    r")\s*"
)
_HEADING_NUMBER_RE = re.compile(
    r"^\s*(?:"
    r"第[一二三四五六七八九十百0-9]+[章节]"
    r"|[0-9]+(?:\.[0-9]+){1,5}\s*"
    r"|[0-9]+[、.．]\s*[\u4e00-\u9fff]"
    r")"
)
_HEADING_TERMS = (
    "入选标准",
    "排除标准",
    "访视计划",
    "研究流程",
    "试验药物",
    "合并用药",
    "禁用药",
    "不良事件",
    "严重不良事件",
    "安全性",
    "疗效评估",
    "统计分析",
    "数据管理",
)
_LIST_TITLE_TERMS = (
    "如下",
    "以下",
    "包括",
    "不包括",
    "允许",
    "禁止",
    "禁用",
    "限制",
    "例外",
    "除外",
    "洗脱",
)
_TABLE_HEADER_TERMS = (
    "项目",
    "标准",
    "条件",
    "阈值",
    "访视",
    "研究日",
    "时间窗",
    "处理",
    "措施",
    "要求",
    "检查",
    "评估",
)


def _is_typed_index(value: Any) -> bool:
    """Accept integer table coordinates without Python bool coercion."""

    return isinstance(value, int) and not isinstance(value, bool)


def expand_protocol_evidence_spans(
    spans: Sequence[Any],
    matches: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS,
) -> tuple[dict[str, Any], ...]:
    """Expand keyword hits with bounded document-structure context.

    The expansion is deterministic and project-neutral. It preserves nearby
    section context, table headers and same-row condition/action cells, and
    contiguous list blocks without making a medical interpretation.
    """

    if not 1 <= limit <= MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS:
        raise ValueError(
            "protocol evidence context limit must be between 1 and "
            f"{MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS}"
        )
    span_by_id = {
        str(getattr(span, "source_id", "") or "").strip(): span
        for span in spans
        if str(getattr(span, "source_id", "") or "").strip()
    }
    match_by_id = {
        str(item.get("source_id") or "").strip(): dict(item)
        for item in matches
        if str(item.get("source_id") or "").strip() in span_by_id
    }
    if not match_by_id:
        return ()

    ordered = sorted(
        span_by_id.values(),
        key=lambda span: _span_sort_key(span),
    )
    ordered_ids = [str(span.source_id).strip() for span in ordered]
    position_by_id = {
        source_id: index for index, source_id in enumerate(ordered_ids)
    }
    roles_by_id: dict[str, set[str]] = {}
    parents_by_id: dict[str, set[str]] = {}
    # Stable typed list bundle identity: the exact source identity of the
    # detected ancestor title. ``parent_match_source_ids`` stays causal
    # expansion lineage only and never defines list identity. A member bound
    # to more than one ancestor title is ambiguous and fails closed by
    # receiving no bundle identity at all.
    bundle_assignments: dict[str, set[str]] = {}

    def add(source_id: str, role: str, parent_id: str) -> None:
        if source_id not in span_by_id:
            return
        roles_by_id.setdefault(source_id, set()).add(role)
        parents_by_id.setdefault(source_id, set()).add(parent_id)

    def bind(source_id: str, bundle_id: str) -> None:
        if source_id not in span_by_id:
            return
        bundle_assignments.setdefault(source_id, set()).add(bundle_id)

    for matched_id in match_by_id:
        matched_span = span_by_id[matched_id]
        add(matched_id, "primary_match", matched_id)
        structure = _span_structure(matched_span)
        if structure["kind"] == "table_cell":
            _expand_table_context(
                ordered,
                matched_id,
                structure,
                add,
            )
        else:
            _expand_paragraph_context(
                ordered,
                position_by_id[matched_id],
                matched_id,
                add,
                bind,
            )

    selected_ids = set(roles_by_id)
    if len(selected_ids) > limit:
        priority = {
            "primary_match": 0,
            "table_row_context": 1,
            "table_header": 2,
            "table_caption": 3,
            "list_title": 4,
            "list_item": 5,
            "section_heading": 6,
            "table_note": 7,
            "adjacent_paragraph": 8,
        }
        selected_ids = set(
            sorted(
                selected_ids,
                key=lambda source_id: (
                    min(
                        priority.get(role, 99)
                        for role in roles_by_id[source_id]
                    ),
                    _span_sort_key(span_by_id[source_id]),
                ),
            )[:limit]
        )

    result = []
    for span in ordered:
        source_id = str(span.source_id).strip()
        if source_id not in selected_ids:
            continue
        primary = source_id in match_by_id
        item = dict(
            match_by_id.get(
                source_id,
                {
                    "source_id": source_id,
                    "source_entry_id": str(span.entry_id).strip(),
                    "locator": str(span.locator).strip(),
                    "text": str(span.text_preview).strip(),
                    "score": 0,
                    "matched_keywords": [],
                    "match_reason": "结构化邻接语境",
                },
            )
        )
        roles = sorted(roles_by_id[source_id])
        evidence_context: dict[str, Any] = {
            "packet_version": PROTOCOL_EVIDENCE_PACKET_VERSION,
            "primary_match": primary,
            "roles": roles,
            "parent_match_source_ids": sorted(parents_by_id[source_id]),
            "structure": _span_structure(span),
        }
        assignments = bundle_assignments.get(source_id)
        if assignments is not None and len(assignments) == 1:
            evidence_context["list_bundle_id"] = next(iter(assignments))
        item["evidence_context"] = evidence_context
        result.append(item)
    return tuple(result)


def _expand_table_context(
    ordered: Sequence[Any],
    matched_id: str,
    structure: Mapping[str, Any],
    add: Any,
) -> None:
    table_index = structure["table_index"]
    row_index = structure["row_index"]
    table_spans = [
        span
        for span in ordered
        if _span_structure(span).get("table_index") == table_index
    ]
    if not table_spans:
        return
    for span in table_spans:
        item = _span_structure(span)
        source_id = str(span.source_id).strip()
        if item["row_index"] == row_index:
            add(source_id, "table_row_context", matched_id)
        if item["row_index"] == 0:
            add(source_id, "table_header", matched_id)
        elif (
            item["row_index"] == 1
            and row_index > 1
            and _looks_like_table_header(str(span.text_preview))
        ):
            add(source_id, "table_header", matched_id)

    first_index = min(_paragraph_index(span) for span in table_spans)
    last_index = max(_paragraph_index(span) for span in table_spans)
    paragraphs = [
        span
        for span in ordered
        if _span_structure(span)["kind"] == "paragraph"
    ]
    preceding = [
        span
        for span in paragraphs
        if 0 < first_index - _paragraph_index(span) <= 3
    ]
    for span in preceding[-2:]:
        text = str(span.text_preview or "").strip()
        if _is_heading(text) or text.startswith("表") or len(text) <= 80:
            add(str(span.source_id).strip(), "table_caption", matched_id)
    following = [
        span
        for span in paragraphs
        if 0 < _paragraph_index(span) - last_index <= 3
    ]
    for span in following[:2]:
        text = str(span.text_preview or "").strip()
        if text.startswith(("注", "注：", "注:", "*", "缩写")):
            add(str(span.source_id).strip(), "table_note", matched_id)


def _expand_paragraph_context(
    ordered: Sequence[Any],
    matched_position: int,
    matched_id: str,
    add: Any,
    bind: Any,
) -> None:
    paragraph_positions = [
        index
        for index, span in enumerate(ordered)
        if _span_structure(span)["kind"] == "paragraph"
    ]
    heading_positions = [
        index
        for index in paragraph_positions
        if _is_heading(str(ordered[index].text_preview or "").strip())
    ]
    previous_heading = max(
        (index for index in heading_positions if index <= matched_position),
        default=None,
    )
    next_heading = min(
        (index for index in heading_positions if index > matched_position),
        default=len(ordered),
    )
    section_start = previous_heading if previous_heading is not None else 0
    section_end = next_heading
    if previous_heading is not None:
        add(
            str(ordered[previous_heading].source_id).strip(),
            "section_heading",
            matched_id,
        )

    for index in paragraph_positions:
        if (
            section_start <= index < section_end
            and abs(index - matched_position) <= 2
        ):
            add(
                str(ordered[index].source_id).strip(),
                "adjacent_paragraph",
                matched_id,
            )

    matched_text = str(ordered[matched_position].text_preview or "").strip()
    list_title_position: int | None = None
    if _is_list_title(matched_text) or _is_heading(matched_text):
        list_title_position = matched_position
    elif _is_list_item(matched_text):
        # A keyword can match a list item without matching its preceding
        # title. Recover the nearest bounded title inside the same section so
        # downstream provider focus never sees an orphaned list entry.
        scan_start = max(section_start, matched_position - 12)
        list_title_position = max(
            (
                index
                for index in paragraph_positions
                if scan_start <= index < matched_position
                and (
                    _is_list_title(
                        str(ordered[index].text_preview or "").strip()
                    )
                    or _is_heading(
                        str(ordered[index].text_preview or "").strip()
                    )
                )
            ),
            default=None,
        )
    else:
        for index in paragraph_positions:
            if matched_position < index <= min(
                section_end,
                matched_position + 3,
            ):
                if _is_list_title(
                    str(ordered[index].text_preview or "").strip()
                ):
                    list_title_position = index
                    break
    if list_title_position is None:
        return
    title_source_id = str(ordered[list_title_position].source_id).strip()
    add(title_source_id, "list_title", matched_id)
    bind(title_source_id, title_source_id)
    scan_end = min(section_end, list_title_position + 13)
    for index in paragraph_positions:
        if not list_title_position < index < scan_end:
            continue
        text = str(ordered[index].text_preview or "").strip()
        if not _is_list_item(text):
            # Only explicit list-item syntax is a list item; unmarked
            # paragraphs after a title remain paragraphs and end the block.
            break
        add(str(ordered[index].source_id).strip(), "list_item", matched_id)
        bind(str(ordered[index].source_id).strip(), title_source_id)


def _span_sort_key(span: Any) -> tuple[int, int, int, str]:
    structure = _span_structure(span)
    return (
        int(structure.get("paragraph_index") or 10**9),
        int(structure.get("row_index") or 0),
        int(structure.get("cell_index") or 0),
        str(getattr(span, "source_id", "") or "").casefold(),
    )


def _span_structure(span: Any) -> dict[str, Any]:
    locator = str(getattr(span, "locator", "") or "").strip()
    table_match = _TABLE_LOCATOR_RE.match(locator)
    if table_match:
        table_index, row_index, cell_index, paragraph_index = (
            int(value) for value in table_match.groups()
        )
        return {
            "kind": "table_cell",
            "paragraph_index": paragraph_index,
            "table_index": table_index,
            "row_index": row_index,
            "cell_index": cell_index,
        }
    return {
        "kind": "paragraph",
        "paragraph_index": _paragraph_index(span),
        "table_index": None,
        "row_index": None,
        "cell_index": None,
    }


def _paragraph_index(span: Any) -> int:
    locator = str(getattr(span, "locator", "") or "").strip()
    match = _PARAGRAPH_INDEX_RE.search(locator)
    return int(match.group(1)) if match else 10**9


def _is_list_item(text: str) -> bool:
    return bool(_LIST_ITEM_RE.match(text))


def _is_list_title(text: str) -> bool:
    """Eligible list titles: short colon-ending text, or short term-based
    titles that are not sentence prose. Term-based prose ending in a full
    stop (``。``) can never become a list title, so narrative paragraphs such
    as PROMIS descriptions stay paragraphs.
    """

    if not text or len(text) > 220:
        return False
    if text.endswith(("：", ":")):
        return True
    return bool(
        any(term in text for term in _LIST_TITLE_TERMS)
        and not text.endswith("。")
    )


def _is_heading(text: str) -> bool:
    if not text or len(text) > 120 or _is_list_item(text):
        return False
    if _HEADING_NUMBER_RE.match(text):
        return True
    if text.endswith(("。", "；", ";", "，", ",")):
        return False
    return len(text) <= 48 and any(term in text for term in _HEADING_TERMS)


def _looks_like_table_header(text: str) -> bool:
    cleaned = " ".join(text.split())
    return bool(
        cleaned
        and len(cleaned) <= 80
        and any(term in cleaned for term in _TABLE_HEADER_TERMS)
    )


def _protocol_context(item: Mapping[str, Any]) -> Any:
    raw_fields = item.get("raw_fields")
    if isinstance(raw_fields, Mapping):
        context = raw_fields.get("protocol_context")
        if isinstance(context, Mapping):
            return context
    return item.get("evidence_context")


def focus_protocol_provider_evidence(
    evidence_packet: Sequence[Mapping[str, Any]],
    *,
    conflict_evidence_ids: Sequence[str] = (),
    limit: int = MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS,
) -> tuple[dict[str, Any], ...]:
    """Deterministic provider-facing focus of a frozen protocol evidence packet.

    The packet is the persisted authoritative input; this function returns a
    bounded, auditable view for the independent AI without mutating the input
    or its identity. Selection keeps every primary match, every evidence ID
    referenced by detected source conflicts, and complete structural bundles:

    - a selected table cell keeps every available same-row cell and the
      table header cells;
    - a selected list item keeps only its unique ancestor list title when
      the typed ancestry is unambiguous; a primary list item without a
      stable bundle, or without exactly one typed ancestor title in that
      bundle, is omitted so an orphan can never reach the provider; a
      selected list title alone stays title-only and sibling list items are
      never auto-added;
    - section headings of retained paragraph matches are kept as anchors.

    Non-essential adjacency (caption, note, adjacent paragraphs) is dropped
    unless it is itself a primary match. If any item lacks a v3 protocol
    context, the packet is returned unchanged so legacy payloads never shrink.
    Ordering and content are deterministic; full-document coverage is never
    asserted by this function.
    """

    if not 1 <= limit <= MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS:
        raise ValueError(
            "protocol evidence focus limit must be between 1 and "
            f"{MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS}"
        )
    items = [
        dict(item)
        for item in evidence_packet
        if isinstance(item, Mapping) and str(item.get("evidence_id") or "").strip()
    ]
    if not items:
        return ()
    contexts = [_protocol_context(item) for item in items]
    if any(
        not isinstance(context, Mapping)
        or not isinstance(context.get("roles"), (list, tuple))
        for context in contexts
    ):
        return tuple(items)
    by_id = {
        str(item["evidence_id"]).strip(): (item, context)
        for item, context in zip(items, contexts)
    }
    list_groups, member_parent = _protocol_list_groups(
        (
            (evidence_id, context)
            for evidence_id, (_item, context) in by_id.items()
        )
    )
    roots: set[str] = {
        str(item["evidence_id"]).strip()
        for item, context in zip(items, contexts)
        if "primary_match" in set(context.get("roles") or ())
    }
    roots.update(
        str(item).strip()
        for item in conflict_evidence_ids
        if str(item).strip() in by_id
    )
    conflict_ids = {
        str(item).strip()
        for item in conflict_evidence_ids
        if str(item).strip() in by_id
    }
    for evidence_id in list(roots):
        if evidence_id in conflict_ids:
            # Conflict evidence sets stay exact: they are never pruned by
            # the focus orphan rule.
            continue
        roles = set(by_id[evidence_id][1].get("roles") or ())
        if "list_item" not in roles:
            continue
        parent_key = member_parent.get(evidence_id)
        if parent_key is None:
            # A primary list item without a stable bundle identity is an
            # orphan: omit it instead of exposing it without its ancestor.
            roots.discard(evidence_id)
            continue
        group = list_groups[parent_key]
        if evidence_id not in group["items"]:
            roots.discard(evidence_id)
            continue
        if _unique_group_title(group) is None:
            # Multiple or missing typed ancestor titles are ambiguous:
            # fail closed by omitting the item.
            roots.discard(evidence_id)
    retained = set(roots)
    root_source_ids = {
        str((by_id[evidence_id][0].get("raw_fields") or {}).get("source_id") or "")
        .strip()
        for evidence_id in roots
    }

    for evidence_id, (_item, context) in by_id.items():
        roles = set(context.get("roles") or ())
        parents = {
            str(parent).strip()
            for parent in context.get("parent_match_source_ids") or ()
            if str(parent).strip()
        }
        if (
            "section_heading" in roles
            and (context.get("structure") or {}).get("kind") != "table_cell"
            and parents.intersection(root_source_ids)
        ):
            retained.add(evidence_id)

    table_headers: dict[int, set[str]] = {}
    table_rows: dict[tuple[int, int], set[str]] = {}
    for evidence_id, (_item, context) in by_id.items():
        structure = context.get("structure") or {}
        if (
            structure.get("kind") != "table_cell"
            or not _is_typed_index(structure.get("table_index"))
        ):
            continue
        table_index = int(structure["table_index"])
        row_index = structure.get("row_index")
        if not _is_typed_index(row_index):
            continue
        roles = set(context.get("roles") or ())
        if "table_header" in roles:
            table_headers.setdefault(table_index, set()).add(evidence_id)
        table_rows.setdefault((table_index, row_index), set()).add(evidence_id)

    for (table_index, row_index), row_ids in table_rows.items():
        if not row_ids.intersection(retained):
            continue
        retained.update(row_ids)
        retained.update(table_headers.get(table_index, ()))

    for evidence_id in list(retained):
        parent_key = member_parent.get(evidence_id)
        if parent_key is None:
            continue
        group = list_groups[parent_key]
        if evidence_id in group["items"]:
            # A selected list item may only pull its unique ancestor title;
            # sibling items are never auto-added. A group without a single
            # typed title keeps no title here; the server repair gate rejects
            # such citations fail-closed.
            title_id = _unique_group_title(group)
            if title_id is not None:
                retained.add(title_id)

    if len(retained) > limit:
        # Structural bundles of primary/conflict roots are mandatory: the
        # limit may only trim optional section-heading anchors, never split
        # a selected table row from its cells/headers or a selected list
        # item from its unique ancestor title.
        mandatory: set[str] = set(roots)
        for (table_index, row_index), row_ids in table_rows.items():
            if row_ids.intersection(roots):
                mandatory.update(row_ids)
                mandatory.update(table_headers.get(table_index, ()))
        for evidence_id in roots:
            parent_key = member_parent.get(evidence_id)
            if parent_key is None:
                continue
            group = list_groups[parent_key]
            if evidence_id in group["items"]:
                title_id = _unique_group_title(group)
                if title_id is not None:
                    mandatory.add(title_id)
        headings = [
            evidence_id
            for evidence_id in retained
            if "section_heading"
            in set(by_id[evidence_id][1].get("roles") or ())
        ]
        retained = set(mandatory)
        for evidence_id in headings:
            if len(retained | {evidence_id}) <= limit:
                retained.add(evidence_id)

    return tuple(
        item
        for item in items
        if str(item["evidence_id"]).strip() in retained
    )


class ProtocolStructuralRepairError(ValueError):
    """Deterministic fail-closed error for an unrepairable citation.

    Raised when provider-selected evidence cannot be closed with exact
    typed table/list context from the frozen packet. The message is the
    lineage failure reason and is deterministic for identical inputs.
    """

    def __init__(
        self,
        reason: str,
        *,
        evidence_ids: Sequence[str] = (),
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.evidence_ids = tuple(
            str(item).strip() for item in evidence_ids if str(item).strip()
        )


@dataclass(frozen=True)
class ProtocolStructuralRepairResult:
    """Typed structural-bundle repair outcome for one protocol clause.

    Original, added and expanded evidence IDs are ordered and deterministic:
    original keeps provider order (first occurrence), expanded follows the
    frozen packet order, added is expanded minus original in packet order.
    """

    schema_version: str
    original_evidence_ids: tuple[str, ...]
    added_structural_context_ids: tuple[str, ...]
    expanded_evidence_ids: tuple[str, ...]
    bundle_bindings: tuple[dict[str, Any], ...]

    def to_lineage(self) -> dict[str, Any]:
        """Deterministic server-persisted repair lineage payload."""
        return {
            "schema_version": self.schema_version,
            "original_evidence_ids": list(self.original_evidence_ids),
            "added_structural_context_ids": list(
                self.added_structural_context_ids
            ),
            "expanded_evidence_ids": list(self.expanded_evidence_ids),
            "bundle_bindings": [
                dict(binding) for binding in self.bundle_bindings
            ],
        }


def _protocol_list_groups(
    items: Sequence[tuple[str, Mapping[str, Any]]],
) -> tuple[
    dict[str, dict[str, set[str]]],
    dict[str, str],
]:
    """Group protocol list members by their stable typed bundle identity.

    The bundle identity is the exact source identity of the detected
    ancestor title recorded at expansion time (``list_bundle_id``). It never
    depends on the causal ``parent_match_source_ids`` lineage, so adjacent
    members with different keyword-match windows still share one identity,
    and physically different lists with identical match-parent sets stay
    separate. Each group carries its title and item member sets; groups
    with zero or multiple titles are ambiguous for item closure. Members
    without any bundle identity, and members bound to more than one bundle,
    have no stable typed identity: they are excluded from every group and
    can never pull an ancestor title.
    """

    groups: dict[str, dict[str, set[str]]] = {}
    member_parent: dict[str, str] = {}
    memberships: dict[str, set[str]] = {}
    for evidence_id, context in items:
        if not isinstance(context, Mapping):
            continue
        roles = set(context.get("roles") or ())
        if not roles.intersection(("list_title", "list_item")):
            continue
        bundle_id = str(context.get("list_bundle_id") or "").strip()
        if not bundle_id:
            # Missing bundle identity is not a typed list identity. Such
            # members stay out of the groups; the repair gate rejects any
            # citation of them.
            continue
        memberships.setdefault(evidence_id, set()).add(bundle_id)
        group = groups.setdefault(
            bundle_id,
            {"titles": set(), "items": set(), "members": set()},
        )
        group["members"].add(evidence_id)
        if "list_title" in roles:
            group["titles"].add(evidence_id)
        if "list_item" in roles:
            group["items"].add(evidence_id)
        member_parent[evidence_id] = bundle_id
    for evidence_id, bundle_ids in memberships.items():
        if len(bundle_ids) < 2:
            continue
        # Ambiguous multiple bundle membership fails closed: the member is
        # removed from every group and can never pull an ancestor title.
        for bundle_id in bundle_ids:
            group = groups[bundle_id]
            group["members"].discard(evidence_id)
            group["titles"].discard(evidence_id)
            group["items"].discard(evidence_id)
        member_parent.pop(evidence_id, None)
    return groups, member_parent


def _unique_group_title(
    group: Mapping[str, set[str]],
) -> str | None:
    titles = group["titles"]
    if len(titles) != 1:
        return None
    return next(iter(titles))


def _packet_order(
    evidence_ids: set[str] | Sequence[str],
    by_id: Mapping[str, tuple[dict[str, Any], Mapping[str, Any]]],
) -> list[str]:
    return [
        evidence_id
        for evidence_id in by_id
        if evidence_id in evidence_ids
    ]


def repair_protocol_structural_bundles(
    evidence_ids: Sequence[str],
    evidence_packet: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS,
) -> ProtocolStructuralRepairResult:
    """Close provider-selected protocol evidence with exact typed context.

    Deterministic, project-neutral structural-bundle repair over one frozen
    packet. Only exact same-row table cells plus the available typed header
    path, or the unique ancestor list title of an explicitly selected item,
    may be added. The provider's original evidence IDs stay separately
    recorded; automatically added context IDs never enter claim evidence.

    The caller supplies the full provider-selected semantic union in
    ``evidence_ids`` (structured payload IDs, exact conflict evidence IDs and
    every claim evidence ID, in that deterministic order); expansion and the
    post-expansion limit are evaluated over that union.

    Fail-closed rules (no text similarity or proximity inference):

    - every selected ID must exist in the exact frozen packet;
    - a header-only table selection cannot select a row;
    - table cells must share one typed (table_index, row_index) data row
      and one table; cross-row, cross-table and header-from-another-table
      unions are rejected;
    - a selected list item requires a unique typed ancestor title;
      missing, duplicate or ambiguous ancestry is rejected;
    - a selected list member without any recorded stable bundle identity,
      or bound to more than one bundle, is rejected because ambiguous
      membership is not a typed list identity;
    - a selected title from another list is rejected; items from different
      lists are rejected as a cross-list union;
    - a title alone never adds items;
    - the expanded ID set is evaluated against the limit after expansion
      and fails closed without truncation.

    Raises ProtocolStructuralRepairError on any fail-closed condition.
    """

    if not 1 <= limit <= MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS:
        raise ValueError(
            "protocol structural repair limit must be between 1 and "
            f"{MAX_PROTOCOL_CANDIDATE_EVIDENCE_IDS}"
        )
    original: list[str] = []
    for evidence_id in evidence_ids:
        cleaned = str(evidence_id).strip()
        if not cleaned or cleaned in original:
            continue
        original.append(cleaned)
    if not original:
        return ProtocolStructuralRepairResult(
            schema_version=PROTOCOL_STRUCTURAL_REPAIR_VERSION,
            original_evidence_ids=(),
            added_structural_context_ids=(),
            expanded_evidence_ids=(),
            bundle_bindings=(),
        )
    by_id: dict[str, tuple[dict[str, Any], Mapping[str, Any]]] = {}
    for item in evidence_packet:
        if not isinstance(item, Mapping):
            continue
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id or evidence_id in by_id:
            continue
        context = _protocol_context(item)
        by_id[evidence_id] = (
            dict(item),
            context if isinstance(context, Mapping) else {},
        )
    missing = [
        evidence_id for evidence_id in original if evidence_id not in by_id
    ]
    if missing:
        raise ProtocolStructuralRepairError(
            "protocol structural repair requires evidence ids from the "
            "frozen packet",
            evidence_ids=missing,
        )

    expanded: set[str] = set(original)
    bindings: list[dict[str, Any]] = []

    packet_cells: dict[int, dict[int, set[str]]] = {}
    packet_headers: dict[int, set[str]] = {}
    for evidence_id, (_item, context) in by_id.items():
        structure = context.get("structure") or {}
        if structure.get("kind") != "table_cell":
            continue
        table_index = structure.get("table_index")
        row_index = structure.get("row_index")
        if not (_is_typed_index(table_index) and _is_typed_index(row_index)):
            continue
        packet_cells.setdefault(table_index, {}).setdefault(
            row_index, set()
        ).add(evidence_id)
        if "table_header" in set(context.get("roles") or ()):
            packet_headers.setdefault(table_index, set()).add(evidence_id)

    selected_cells = [
        (evidence_id, context)
        for evidence_id in original
        for context in (by_id[evidence_id][1],)
        if ((context.get("structure") or {})).get("kind") == "table_cell"
    ]
    if selected_cells:
        typed: list[tuple[str, int, int, bool]] = []
        for evidence_id, context in selected_cells:
            structure = context.get("structure") or {}
            table_index = structure.get("table_index")
            row_index = structure.get("row_index")
            roles = set(context.get("roles") or ())
            header = "table_header" in roles
            if not (
                _is_typed_index(table_index)
                and _is_typed_index(row_index)
                and row_index >= 0
            ):
                raise ProtocolStructuralRepairError(
                    "protocol structural repair requires a typed table "
                    "identity",
                    evidence_ids=(evidence_id,),
                )
            if row_index == 0 and not header:
                raise ProtocolStructuralRepairError(
                    "protocol structural repair requires typed table "
                    "headers",
                    evidence_ids=(evidence_id,),
                )
            typed.append((evidence_id, table_index, row_index, header))
        data_rows = {
            (table_index, row_index)
            for _evidence_id, table_index, row_index, _header in typed
            if row_index > 0
        }
        if not data_rows:
            raise ProtocolStructuralRepairError(
                "protocol structural repair cannot select a row from "
                "header-only evidence"
            )
        if len({table_index for table_index, _row in data_rows}) > 1:
            raise ProtocolStructuralRepairError(
                "protocol structural repair cannot union table cells "
                "across tables"
            )
        if len(data_rows) > 1:
            raise ProtocolStructuralRepairError(
                "protocol structural repair cannot union table cells "
                "across rows"
            )
        table_index, row_index = next(iter(data_rows))
        header_tables = {
            table_index
            for _evidence_id, t_index, _row_index, header in typed
            if header
        }
        if header_tables and header_tables != {table_index}:
            raise ProtocolStructuralRepairError(
                "protocol structural repair cannot bind a header from "
                "another table"
            )
        expanded.update(packet_cells.get(table_index, {}).get(row_index, ()))
        expanded.update(packet_headers.get(table_index, ()))
        bindings.append(
            {
                "kind": "table",
                "table_index": table_index,
                "row_index": row_index,
                "row_evidence_ids": _packet_order(
                    packet_cells[table_index][row_index],
                    by_id,
                ),
                "header_evidence_ids": _packet_order(
                    packet_headers.get(table_index, ()),
                    by_id,
                ),
            }
        )

    list_groups, member_parent = _protocol_list_groups(
        (
            (evidence_id, context)
            for evidence_id, (_item, context) in by_id.items()
        )
    )
    selected_items: list[str] = []
    selected_titles: list[str] = []
    for evidence_id in original:
        parent_key = member_parent.get(evidence_id)
        if parent_key is None:
            if set(by_id[evidence_id][1].get("roles") or ()).intersection(
                ("list_title", "list_item")
            ):
                raise ProtocolStructuralRepairError(
                    "protocol structural repair requires a typed list "
                    "identity",
                    evidence_ids=(evidence_id,),
                )
            continue
        group = list_groups[parent_key]
        if evidence_id in group["items"]:
            selected_items.append(evidence_id)
        if evidence_id in group["titles"]:
            selected_titles.append(evidence_id)
    if selected_items:
        if len({member_parent[item_id] for item_id in selected_items}) > 1:
            raise ProtocolStructuralRepairError(
                "protocol structural repair cannot union list items "
                "across lists"
            )
        parent_key = member_parent[selected_items[0]]
        title_id = _unique_group_title(list_groups[parent_key])
        if title_id is None:
            raise ProtocolStructuralRepairError(
                "protocol structural repair requires a unique list "
                "ancestor title",
                evidence_ids=(selected_items[0],),
            )
        expanded.add(title_id)
        for title in selected_titles:
            if title != title_id:
                raise ProtocolStructuralRepairError(
                    "protocol structural repair cannot mix a list title "
                    "from another list",
                    evidence_ids=(title,),
                )
        bindings.append(
            {
                "kind": "list",
                "list_bundle_id": parent_key,
                "ancestor_title_evidence_id": title_id,
                "item_evidence_ids": _packet_order(
                    list_groups[parent_key]["items"],
                    by_id,
                ),
            }
        )
    elif selected_titles:
        # A title alone never adds items; each selected title stays visible
        # as a title-only view with its typed group identity recorded.
        for title_id in selected_titles:
            parent_key = member_parent[title_id]
            bindings.append(
                {
                    "kind": "list",
                    "list_bundle_id": parent_key,
                    "ancestor_title_evidence_id": title_id,
                    "item_evidence_ids": _packet_order(
                        list_groups[parent_key]["items"],
                        by_id,
                    ),
                }
            )

    expanded_ordered = _packet_order(expanded, by_id)
    if len(expanded_ordered) > limit:
        raise ProtocolStructuralRepairError(
            "protocol structural repair expanded evidence ids exceed "
            f"{limit}"
        )
    return ProtocolStructuralRepairResult(
        schema_version=PROTOCOL_STRUCTURAL_REPAIR_VERSION,
        original_evidence_ids=tuple(original),
        added_structural_context_ids=tuple(
            evidence_id
            for evidence_id in expanded_ordered
            if evidence_id not in original
        ),
        expanded_evidence_ids=tuple(expanded_ordered),
        bundle_bindings=tuple(bindings),
    )


class MonitoringAiSourcePacketResolver:
    """Resolve server-registered spans into immutable monitoring AI evidence."""

    def __init__(self, source_registry: Any):
        self.source_registry = source_registry

    def resolve(
        self,
        project_id: str,
        source_ids: Sequence[str],
    ) -> MonitoringAiSourcePacket:
        requested = tuple(dict.fromkeys(str(item).strip() for item in source_ids))
        if not requested or any(not item for item in requested):
            raise ValueError("monitoring AI source_ids must be non-empty")
        if len(requested) > 200:
            raise ValueError("monitoring AI source_ids exceed 200 items")

        self.source_registry._assert_registered_sources_usable(  # noqa: SLF001
            project_id,
            requested,
        )
        spans = self.source_registry.store.get_spans(project_id, requested)
        entries = {
            entry.entry_id: entry
            for entry in self.source_registry.list_entries(project_id)
        }
        bindings: dict[str, MonitoringAiSourceBinding] = {}
        evidence_packet = []
        for span in spans:
            entry = entries.get(span.entry_id)
            if entry is None:
                raise ValueError(
                    f"registered source entry is unavailable: {span.entry_id}"
                )
            bindings[entry.entry_id] = MonitoringAiSourceBinding(
                source_entry_id=entry.entry_id,
                source_content_sha256=entry.content_hash,
            )
            quote = str(span.text_preview or "").strip()
            if not quote:
                raise ValueError(
                    f"registered source span has no usable content: {span.source_id}"
                )
            evidence_packet.append(
                {
                    "evidence_id": "monsrc_"
                    + content_sha256(
                        {
                            "project_id": project_id,
                            "source_id": span.source_id,
                            "entry_id": entry.entry_id,
                            "content_hash": entry.content_hash,
                            "locator": span.locator,
                            "quote": quote,
                        }
                    )[:28],
                    "source_entry_id": entry.entry_id,
                    "source_content_sha256": entry.content_hash,
                    "locator": span.locator,
                    "quote": quote,
                    "raw_fields": {
                        "source_id": span.source_id,
                        "source_type": span.source_type,
                        "title": span.title,
                    },
                }
            )

        ordered_bindings = tuple(
            bindings[key]
            for key in sorted(bindings, key=lambda value: (value.casefold(), value))
        )
        revision_seed = {
            "project_id": project_id,
            "source_ids": list(requested),
            "bindings": [
                item.model_dump(mode="json") for item in ordered_bindings
            ],
            "evidence_ids": [item["evidence_id"] for item in evidence_packet],
        }
        revision_token = content_sha256(revision_seed)
        return MonitoringAiSourcePacket(
            input_revision=MonitoringAiInputRevision(
                project_id=project_id,
                batch_revision=f"source-registry:{revision_token[:24]}",
                protocol_version=revision_token,
                sources=ordered_bindings,
            ),
            source_ids=requested,
            evidence_packet=tuple(evidence_packet),
        )

    def search(
        self,
        project_id: str,
        entry_id: str,
        query_terms: Sequence[str],
        *,
        limit: int = 50,
    ) -> tuple[dict[str, Any], ...]:
        """Return bounded source excerpts only; no medical interpretation."""
        return tuple(
            self.source_registry.search_protocol_spans(
                project_id,
                entry_id,
                query_terms,
                limit=limit,
                required_module="medical_monitoring",
            )
        )

    def expand_protocol_context(
        self,
        project_id: str,
        entry_id: str,
        matches: Sequence[Mapping[str, Any]],
        *,
        limit: int = MAX_PROTOCOL_EVIDENCE_CONTEXT_SPANS,
    ) -> tuple[dict[str, Any], ...]:
        spans = [
            span
            for span in self.source_registry.list_spans(project_id)
            if str(span.entry_id).strip() == entry_id
        ]
        return expand_protocol_evidence_spans(
            spans,
            matches,
            limit=limit,
        )
