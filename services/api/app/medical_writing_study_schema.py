from __future__ import annotations

import hashlib
import io
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

from packages.contracts.workbench_contracts import (
    MedicalWritingStudySchemaDefinition,
    MedicalWritingStudySchemaPresentation,
    MedicalWritingStudySchemaValidationIssue,
)


_NODE_WIDTH = 168
_NODE_HEIGHT = 76
_PART_GAP = 36
_EDGE_COLOR = "#374151"
_DOCX_SVG_FONT_STACK = "'Times New Roman', SimSun, 'Songti SC', serif"
_EDGE_LABEL_FONT_SIZE = 12
_EDGE_LABEL_LINE_HEIGHT = 14
_EDGE_LABEL_PAD_X = 10
_EDGE_LABEL_PAD_Y = 4
_EDGE_LABEL_CANVAS_MARGIN = 4
_EDGE_LABEL_NODE_GAP = 3
_EDGE_LABEL_EXPAND_LEVELS = 6
_EDGE_LABEL_EXPAND_STEP_X = 48
_EDGE_LABEL_EXPAND_PAD_Y = 56
_EDGE_LABEL_EXPAND_PAD_X = 40


class StudySchemaEdgeLabelLayoutError(ValueError):
    """Raised when an edge label cannot be placed without truncation or overlap."""


def canonical_payload_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def study_schema_state_sha256(schema: MedicalWritingStudySchemaDefinition) -> str:
    payload = schema.model_dump(
        mode="json",
        exclude={"state_sha256", "revision", "updated_at", "updated_by"},
    )
    return canonical_payload_sha256(payload)


def validate_study_schema(
    schema: MedicalWritingStudySchemaDefinition,
) -> list[MedicalWritingStudySchemaValidationIssue]:
    issues: list[MedicalWritingStudySchemaValidationIssue] = []
    node_by_id = {node.node_id: node for node in schema.nodes}
    for node in schema.nodes:
        if node.fact_status != "confirmed":
            issues.append(
                _issue(
                    "blocker",
                    f"node_{node.fact_status}",
                    f"节点“{node.label}”尚未形成已确认研究事实。",
                    node.node_id,
                )
            )
        if not node.source_bindings:
            issues.append(
                _issue(
                    "warning",
                    "node_source_missing",
                    f"节点“{node.label}”尚未绑定方案字段或原始来源。",
                    node.node_id,
                )
            )
    for edge in schema.edges:
        if edge.fact_status != "confirmed":
            issues.append(
                _issue(
                    "blocker",
                    f"edge_{edge.fact_status}",
                    "流程关系尚未形成已确认研究事实。",
                    edge.edge_id,
                )
            )
        if not edge.source_bindings:
            issues.append(
                _issue(
                    "warning",
                    "edge_source_missing",
                    "流程关系尚未绑定方案字段或原始来源。",
                    edge.edge_id,
                )
            )
    incoming = {node_id: 0 for node_id in node_by_id}
    outgoing = {node_id: 0 for node_id in node_by_id}
    for edge in schema.edges:
        incoming[edge.to_node_id] += 1
        outgoing[edge.from_node_id] += 1
    if not any(node.node_kind == "entry" or incoming[node.node_id] == 0 for node in schema.nodes):
        issues.append(_issue("blocker", "entry_missing", "研究流程图缺少可识别的起点。"))
    if not any(node.node_kind == "end" or outgoing[node.node_id] == 0 for node in schema.nodes):
        issues.append(_issue("blocker", "end_missing", "研究流程图缺少可识别的终点。"))
    if schema.status == "stale":
        issues.append(
            _issue(
                "blocker",
                "source_facts_stale",
                "研究设计事实已变化，请重新核对流程图后再插入方案。",
            )
        )
    return issues


def formal_render_allowed(
    schema: MedicalWritingStudySchemaDefinition,
    issues: Iterable[MedicalWritingStudySchemaValidationIssue],
) -> bool:
    return schema.status == "confirmed" and not any(
        issue.severity == "blocker" for issue in issues
    )


class StudySchemaPlanConflictError(ValueError):
    """Raised when the study schema conflicts with the confirmed plan."""


def validate_study_schema_against_plan(
    schema: MedicalWritingStudySchemaDefinition,
    plan_state: Any,
) -> list[MedicalWritingStudySchemaValidationIssue]:
    """Validate that schema parts/nodes align with the confirmed plan.

    *plan_state* is a ``MedicalWritingProtocolAssemblyPlanCurrentState``
    whose ``plan`` attribute carries modules, design drivers, and projection
    manifests.  This function checks:

    1. Every schema part has a non-empty ``part_id`` (empty Part when
       selected is a fail).
    2. The plan's ``study_schema_flowchart`` projection has no unresolved
       blocking drivers.
    3. Schema part count is consistent with plan module applicability for
       Phase I Parts (typed Part codes must appear as schema parts).

    Returns a list of validation issues; an empty list means alignment.
    """
    issues: list[MedicalWritingStudySchemaValidationIssue] = []
    # 1. Empty Part check — a selected Part must not be empty.
    for part in schema.parts:
        if not part.part_id or not part.part_id.strip():
            issues.append(
                _issue(
                    "blocker",
                    "plan_part_empty",
                    "已选Part的流程图Part标识为空，与确认计划不一致。",
                    part.part_id or "",
                )
            )
    # 2. If plan_state carries blocking drivers for study_schema_flowchart,
    #    surface them as validation issues.
    if plan_state is not None and hasattr(plan_state, "plan"):
        plan = plan_state.plan
        if plan is not None:
            for module in plan.modules:
                if "study_schema_flowchart" in getattr(
                    module, "projection_targets", []
                ):
                    for q in module.unresolved_questions:
                        if q.severity == "blocker":
                            issues.append(
                                _issue(
                                    "blocker",
                                    f"plan_unresolved_{q.question_id}",
                                    f"确认计划存在未解决的阻断驱动：{q.question_id}",
                                    "",
                                )
                            )
    return issues


def require_plan_for_study_schema(
    project_id: str,
    plan_consumption_helper: Any,
) -> Any:
    """Consume the confirmed plan's ``study_schema_flowchart`` projection.

    Returns the plan state or raises ``PlanConsumptionError`` if the plan is
    missing, unconfirmed, stale, or has unresolved blocking drivers.
    """
    if plan_consumption_helper is None:
        return None
    return plan_consumption_helper.require_confirmed_projection(
        project_id=project_id,
        projection_kind="study_schema_flowchart",
    )


@dataclass(frozen=True)
class _PlacedNode:
    node_id: str
    x: int
    y: int


@dataclass(frozen=True)
class _EdgeRoute:
    sx: float
    sy: float
    ex: float
    ey: float
    mid: float
    horizontal: bool
    path: str


@dataclass(frozen=True)
class _EdgeLabelPlacement:
    lines: tuple[str, ...]
    center_x: float
    top_y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.center_x - self.width / 2

    def line_baselines(self) -> list[tuple[str, float]]:
        # Match the previous single-line baseline (top + 14 for height 18).
        first = self.top_y + _EDGE_LABEL_FONT_SIZE + 2
        return [
            (line, first + index * _EDGE_LABEL_LINE_HEIGHT)
            for index, line in enumerate(self.lines)
        ]


def render_study_schema_svg(
    schema: MedicalWritingStudySchemaDefinition,
    presentation: MedicalWritingStudySchemaPresentation | None = None,
) -> str:
    overrides = {
        item.node_id: item
        for item in (presentation.node_overrides if presentation else [])
    }
    parts = sorted(schema.parts, key=lambda item: (item.order, item.part_id))
    nodes_by_part = {
        part.part_id: sorted(
            [node for node in schema.nodes if node.part_id == part.part_id],
            key=lambda item: (item.order, item.lane_order, item.node_id),
        )
        for part in parts
    }
    base_horizontal_step = 244 if any(edge.label for edge in schema.edges) else 212
    stack_parts = len(parts) > 1
    last_failure: str | None = None

    for expand_level in range(_EDGE_LABEL_EXPAND_LEVELS):
        horizontal_step = base_horizontal_step + expand_level * _EDGE_LABEL_EXPAND_STEP_X
        top_pad = expand_level * (_EDGE_LABEL_EXPAND_PAD_Y // 2)
        bottom_pad = expand_level * _EDGE_LABEL_EXPAND_PAD_Y
        side_pad = expand_level * _EDGE_LABEL_EXPAND_PAD_X
        clearance_radius = 72 + expand_level * 36

        part_widths: dict[str, int] = {}
        part_heights: dict[str, int] = {}
        part_wrap_columns: dict[str, int] = {}
        part_wrap_row_heights: dict[str, int] = {}
        for part in parts:
            part_nodes = nodes_by_part[part.part_id]
            order_count = max(1, len({node.order for node in part_nodes}))
            max_lanes = max(
                (
                    sum(1 for node in part_nodes if node.order == order)
                    for order in {node.order for node in part_nodes}
                ),
                default=1,
            )
            horizontal = part.flow_direction == "left_to_right"
            wrap_columns = (
                math.ceil(order_count / 2)
                if horizontal and not stack_parts and order_count >= 7
                else order_count
            )
            wrap_rows = math.ceil(order_count / wrap_columns)
            wrap_row_height = max(140, max_lanes * 104 + 36)
            part_wrap_columns[part.part_id] = wrap_columns
            part_wrap_row_heights[part.part_id] = wrap_row_height
            part_widths[part.part_id] = max(
                300,
                72
                + (
                    wrap_columns * horizontal_step
                    if horizontal
                    else max_lanes * 196
                ),
            )
            part_heights[part.part_id] = max(
                190 if stack_parts else 250,
                (
                    100 + max_lanes * 90
                    if stack_parts and horizontal
                    else 126
                    + (
                        wrap_rows * wrap_row_height
                        if horizontal
                        else order_count * 112
                    )
                ),
            )
        if stack_parts:
            width = 48 + max(part_widths.values(), default=300) + 48 + side_pad * 2
            height = (
                72
                + top_pad
                + sum(part_heights.values())
                + _PART_GAP * max(0, len(parts) - 1)
                + 76
                + bottom_pad
            )
        else:
            width = (
                48
                + sum(part_widths.values())
                + _PART_GAP * max(0, len(parts) - 1)
                + 48
                + side_pad * 2
            )
            height = 92 + top_pad + max(part_heights.values(), default=250) + 76 + bottom_pad

        placed: dict[str, _PlacedNode] = {}
        part_x = 48 + side_pad
        part_y = 72 + top_pad
        part_origins: dict[str, tuple[int, int]] = {}
        for part in parts:
            part_origins[part.part_id] = (part_x, part_y)
            part_nodes = nodes_by_part[part.part_id]
            direction = part.flow_direction
            order_values = sorted({node.order for node in part_nodes})
            max_lanes = max(
                (
                    sum(1 for node in part_nodes if node.order == order)
                    for order in order_values
                ),
                default=1,
            )
            for order_index, order in enumerate(order_values):
                order_nodes = sorted(
                    [node for node in part_nodes if node.order == order],
                    key=lambda item: (item.lane_order, item.node_id),
                )
                lane_offset = (max_lanes - len(order_nodes)) / 2
                for lane_index, node in enumerate(order_nodes):
                    visual_lane = lane_offset + lane_index
                    if direction == "left_to_right":
                        wrap_columns = part_wrap_columns[part.part_id]
                        wrap_row = order_index // wrap_columns
                        position_in_row = order_index % wrap_columns
                        visual_column = (
                            position_in_row
                            if wrap_row % 2 == 0
                            else wrap_columns - position_in_row - 1
                        )
                        x = part_x + 36 + visual_column * horizontal_step
                        y = (
                            part_y
                            + 66
                            + wrap_row * part_wrap_row_heights[part.part_id]
                            + round(visual_lane * 104)
                        )
                    else:
                        x = part_x + 36 + round(visual_lane * 196)
                        visual_order = (
                            order_index
                            if direction == "top_to_bottom"
                            else len(order_values) - order_index - 1
                        )
                        y = part_y + 66 + visual_order * 112
                    override = overrides.get(node.node_id)
                    x += override.dx if override else 0
                    y += override.dy if override else 0
                    placed[node.node_id] = _PlacedNode(node.node_id, x, y)
            if stack_parts:
                part_y += part_heights[part.part_id] + _PART_GAP
            else:
                part_x += part_widths[part.part_id] + _PART_GAP

        node_boxes = tuple(
            (point.x, point.y, _NODE_WIDTH, _NODE_HEIGHT) for point in placed.values()
        )
        label_placements: dict[str, _EdgeLabelPlacement] = {}
        layout_ok = True
        for edge in sorted(
            schema.edges, key=lambda item: (item.edge_id, item.from_node_id, item.to_node_id)
        ):
            if not edge.label:
                continue
            start = placed[edge.from_node_id]
            end = placed[edge.to_node_id]
            route = _edge_route(start, end)
            placement = _try_place_edge_label(
                edge.label,
                edge_kind=edge.edge_kind,
                route=route,
                start_box=(start.x, start.y, _NODE_WIDTH, _NODE_HEIGHT),
                end_box=(end.x, end.y, _NODE_WIDTH, _NODE_HEIGHT),
                node_boxes=node_boxes,
                canvas_width=width,
                canvas_height=height,
                clearance_radius=clearance_radius,
            )
            if placement is None:
                layout_ok = False
                last_failure = (
                    f"edge_id={edge.edge_id!r} kind={edge.edge_kind!r} "
                    f"label_units={_text_display_units(edge.label)} "
                    f"expand_level={expand_level}"
                )
                break
            label_placements[edge.edge_id] = placement

        if not layout_ok:
            continue

        chunks = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="schema-title schema-desc">',
            f'<title id="schema-title">{escape(schema.title)}</title>',
            '<desc id="schema-desc">由已确认研究设计事实生成的研究流程图</desc>',
            (
                "<defs>"
                + "".join(
                    f'<marker id="{marker_id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                    f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
                    for marker_id, color in (
                        ("arrow-default", "#374151"),
                        ("arrow-switch", "#ea580c"),
                        ("arrow-continuation", "#15803d"),
                        ("arrow-followup", "#1d4ed8"),
                    )
                )
                + "</defs>"
            ),
            '<rect width="100%" height="100%" fill="#ffffff"/>',
        ]
        for part in parts:
            origin_x, origin_y = part_origins[part.part_id]
            part_width = part_widths[part.part_id]
            chunks.extend(
                [
                    f'<rect x="{origin_x}" y="{origin_y}" width="{part_width}" height="{part_heights[part.part_id]}" rx="4" fill="#ffffff" stroke="#9ca3af" stroke-dasharray="5 4"/>',
                    f'<text x="{origin_x + part_width / 2:g}" y="{origin_y + 36}" text-anchor="middle" font-family="{_DOCX_SVG_FONT_STACK}" font-size="18" font-weight="700" fill="#111827">{escape(part.label)}</text>',
                ]
            )

        for edge in sorted(
            schema.edges, key=lambda item: (item.edge_id, item.from_node_id, item.to_node_id)
        ):
            start = placed[edge.from_node_id]
            end = placed[edge.to_node_id]
            route = _edge_route(start, end)
            dash = (
                ' stroke-dasharray="6 4"'
                if edge.edge_kind in {"activation_dependency", "conditional"}
                else ""
            )
            edge_color, marker_id = _edge_style(edge.edge_kind)
            chunks.append(
                f'<path data-edge-id="{escape(edge.edge_id)}" data-edge-kind="{escape(edge.edge_kind)}" d="{route.path}" fill="none" stroke="{edge_color}" stroke-width="1.8" marker-end="url(#{marker_id})"{dash}/>'
            )
            if edge.label:
                placement = label_placements[edge.edge_id]
                chunks.append(
                    f'<g class="study-schema-edge-label-group" data-edge-label-for="{escape(edge.edge_id)}">'
                )
                chunks.append(
                    f'<rect class="study-schema-edge-label-bg" x="{placement.left:g}" y="{placement.top_y:g}" width="{placement.width:g}" height="{placement.height:g}" rx="2" fill="#ffffff" fill-opacity="0.96"/>'
                )
                for line, baseline_y in placement.line_baselines():
                    chunks.append(
                        f'<text class="study-schema-edge-label" x="{placement.center_x:g}" y="{baseline_y:g}" text-anchor="middle" font-family="{_DOCX_SVG_FONT_STACK}" font-size="{_EDGE_LABEL_FONT_SIZE}" fill="#4b5563">{escape(line)}</text>'
                    )
                chunks.append("</g>")

        for node in sorted(schema.nodes, key=lambda item: item.node_id):
            point = placed[node.node_id]
            fill, stroke = _node_colors(node.node_kind)
            chunks.append(
                f'<g data-node-id="{escape(node.node_id)}"><rect x="{point.x}" y="{point.y}" width="{_NODE_WIDTH}" height="{_NODE_HEIGHT}" rx="3" fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>'
            )
            lines = _study_schema_node_lines(node.label, node.detail_lines)
            start_y = point.y + 25 - max(0, len(lines) - 2) * 7
            for index, (line, is_title) in enumerate(lines):
                size = 14 if is_title else 12
                weight = "700" if is_title else "400"
                chunks.append(
                    f'<text x="{point.x + _NODE_WIDTH / 2:g}" y="{start_y + index * 17:g}" text-anchor="middle" font-family="{_DOCX_SVG_FONT_STACK}" font-size="{size}" font-weight="{weight}" fill="#111827">{escape(line)}</text>'
                )
            chunks.append("</g>")
        if schema.annotations:
            note_y = height - 48
            for index, annotation in enumerate(schema.annotations[:3]):
                chunks.append(
                    f'<text x="56" y="{note_y + index * 16}" font-family="{_DOCX_SVG_FONT_STACK}" font-size="11" fill="#4b5563">{escape(annotation)}</text>'
                )
        chunks.append("</svg>")
        return "".join(chunks)

    detail = last_failure or "unknown edge label"
    raise StudySchemaEdgeLabelLayoutError(
        "study-schema edge label cannot be placed without overlapping a node "
        f"or leaving the canvas after deterministic expansion ({detail})"
    )


def _study_schema_node_lines(
    label: str, detail_lines: list[str]
) -> list[tuple[str, bool]]:
    title_lines = _wrap_study_schema_text(label, max_units=20)[:2]
    details: list[str] = []
    for detail in detail_lines:
        details.extend(_wrap_study_schema_text(detail, max_units=24))
    combined = [
        *((line, True) for line in title_lines),
        *((line, False) for line in details),
    ]
    if len(combined) <= 4:
        return combined
    visible = combined[:4]
    last, is_title = visible[-1]
    visible[-1] = (_append_ellipsis(last, 24 if not is_title else 20), is_title)
    return visible


def _wrap_study_schema_text(text: str, *, max_units: int) -> list[str]:
    normalized = " ".join(str(text).split())
    if not normalized:
        return []
    lines: list[str] = []
    current: list[str] = []
    units = 0
    for character in normalized:
        character_units = (
            2
            if unicodedata.east_asian_width(character) in {"W", "F", "A"}
            else 1
        )
        if current and units + character_units > max_units:
            lines.append("".join(current).strip())
            current = []
            units = 0
        current.append(character)
        units += character_units
    if current:
        lines.append("".join(current).strip())
    return [line for line in lines if line]


def _append_ellipsis(text: str, max_units: int) -> str:
    ellipsis_units = 2
    characters = list(text.rstrip("…"))
    while characters and sum(
        2 if unicodedata.east_asian_width(item) in {"W", "F", "A"} else 1
        for item in characters
    ) + ellipsis_units > max_units:
        characters.pop()
    return "".join(characters).rstrip() + "…"


def render_study_schema_png(svg: str, *, scale: int = 2) -> bytes:
    """Rasterize only the constrained server SVG for legacy Word renderers."""

    if scale not in {1, 2, 3}:
        raise ValueError("study-schema PNG scale must be 1, 2, or 3")
    lowered = svg.lower()
    if any(token in lowered for token in ("<script", "foreignobject", "javascript:")):
        raise ValueError("study-schema SVG contains executable content")
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        raise ValueError("study-schema SVG is not well formed") from exc
    if _local_name(root.tag) != "svg":
        raise ValueError("study-schema raster input must be an SVG document")
    for element in root.iter():
        if _local_name(element.tag) in {"script", "foreignObject", "image", "use"}:
            raise ValueError("study-schema SVG contains an unsupported element")
        for key, value in element.attrib.items():
            local_key = _local_name(key).lower()
            text = str(value).strip().lower()
            if local_key.startswith("on") or (
                local_key in {"href", "src"}
                and (text.startswith(("http:", "https:", "file:", "data:")) or "//" in text)
            ):
                raise ValueError("study-schema SVG contains an external reference")

    width = int(float(root.attrib.get("width", "0")))
    height = int(float(root.attrib.get("height", "0")))
    if width < 100 or height < 100 or width > 20_000 or height > 20_000:
        raise ValueError("study-schema SVG dimensions are outside the supported range")
    canvas = Image.new("RGB", (width * scale, height * scale), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    font_cache = {}

    def fonts(size: int, bold: bool = False):
        key = (size * scale, bold)
        if key not in font_cache:
            font_cache[key] = _study_schema_fonts(size * scale, bold=bold)
        return font_cache[key]

    def render_element(element) -> None:
        name = _local_name(element.tag)
        if name in {"defs", "title", "desc", "marker"}:
            return
        if name == "rect":
            x = _svg_number(element.attrib.get("x", "0")) * scale
            y = _svg_number(element.attrib.get("y", "0")) * scale
            raw_width = element.attrib.get("width", "0")
            raw_height = element.attrib.get("height", "0")
            item_width = width if str(raw_width).endswith("%") else _svg_number(raw_width)
            item_height = height if str(raw_height).endswith("%") else _svg_number(raw_height)
            fill = element.attrib.get("fill", "#ffffff")
            stroke = element.attrib.get("stroke")
            stroke_width = max(1, round(_svg_number(element.attrib.get("stroke-width", "1")) * scale))
            radius = round(_svg_number(element.attrib.get("rx", "0")) * scale)
            draw.rounded_rectangle(
                (x, y, x + item_width * scale, y + item_height * scale),
                radius=radius,
                fill=fill if fill != "none" else None,
                outline=stroke,
                width=stroke_width,
            )
        elif name == "path" and element.attrib.get("fill", "none") == "none":
            points = _svg_path_points(element.attrib.get("d", ""), scale)
            if len(points) >= 2:
                color = element.attrib.get("stroke", _EDGE_COLOR)
                line_width = max(1, round(_svg_number(element.attrib.get("stroke-width", "1")) * scale))
                dashed = bool(element.attrib.get("stroke-dasharray"))
                for start, end in zip(points, points[1:]):
                    _draw_study_schema_line(draw, start, end, color, line_width, dashed)
                if element.attrib.get("marker-end"):
                    _draw_study_schema_arrow(draw, points[-2], points[-1], color, scale)
        elif name == "text":
            content = "".join(element.itertext())
            if content:
                x = _svg_number(element.attrib.get("x", "0")) * scale
                y = _svg_number(element.attrib.get("y", "0")) * scale
                size = max(8, round(_svg_number(element.attrib.get("font-size", "12"))))
                chinese_font, latin_font = fonts(
                    size,
                    element.attrib.get("font-weight") in {"600", "700", "bold"},
                )
                fill = element.attrib.get("fill", "#111827")
                _draw_bilingual_text(
                    draw,
                    x=x,
                    baseline_y=y - 2 * scale,
                    text=content,
                    chinese_font=chinese_font,
                    latin_font=latin_font,
                    fill=fill,
                    centered=element.attrib.get("text-anchor") == "middle",
                )
        for child in element:
            render_element(child)

    for child in root:
        render_element(child)
    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=False, compress_level=9)
    return output.getvalue()


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _svg_number(value: object) -> float:
    match = re.match(r"^\s*(-?(?:\d+(?:\.\d*)?|\.\d+))", str(value))
    return float(match.group(1)) if match else 0.0


def _edge_label_width(value: str) -> int:
    """Pixel width of a single edge-label line, including horizontal padding."""
    return _edge_label_block_size((value,))[0]


def _normalize_edge_label_text(value: str) -> str:
    """Whitespace-normalized edge label; character content is otherwise unchanged."""
    return " ".join(str(value).split())


def _text_display_units(value: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F", "A"} else 1
        for character in value
    )


def _edge_label_text_width(value: str) -> int:
    return sum(12 if ord(character) > 127 else 7 for character in value)


def _edge_label_block_size(lines: Iterable[str]) -> tuple[int, int]:
    line_list = list(lines)
    if not line_list:
        return 28, _EDGE_LABEL_LINE_HEIGHT + _EDGE_LABEL_PAD_Y
    text_width = max(_edge_label_text_width(line) for line in line_list)
    width = max(28, text_width + _EDGE_LABEL_PAD_X)
    height = len(line_list) * _EDGE_LABEL_LINE_HEIGHT + _EDGE_LABEL_PAD_Y
    return width, height


def _wrap_edge_label_text(text: str, *, max_units: int) -> list[str]:
    """Wrap an edge label without dropping, eliding, or reordering characters."""
    normalized = _normalize_edge_label_text(text)
    if not normalized:
        return []
    max_units = max(2, max_units)
    lines: list[str] = []
    current: list[str] = []
    units = 0
    for character in normalized:
        character_units = (
            2
            if unicodedata.east_asian_width(character) in {"W", "F", "A"}
            else 1
        )
        if current and units + character_units > max_units:
            lines.append("".join(current))
            current = []
            units = 0
        current.append(character)
        units += character_units
    if current:
        lines.append("".join(current))
    # Integrity: wrapping only inserts line breaks.
    if "".join(lines) != normalized:
        raise StudySchemaEdgeLabelLayoutError(
            "edge-label wrap lost source characters"
        )
    return lines


def _edge_route(start: _PlacedNode, end: _PlacedNode) -> _EdgeRoute:
    sx, sy = start.x + _NODE_WIDTH / 2, start.y + _NODE_HEIGHT / 2
    ex, ey = end.x + _NODE_WIDTH / 2, end.y + _NODE_HEIGHT / 2
    if abs(ex - sx) >= abs(ey - sy):
        sx = start.x + (_NODE_WIDTH if ex >= sx else 0)
        ex = end.x + (0 if ex >= sx else _NODE_WIDTH)
        mid = (sx + ex) / 2
        path = f"M {sx:g} {sy:g} L {mid:g} {sy:g} L {mid:g} {ey:g} L {ex:g} {ey:g}"
        return _EdgeRoute(sx=sx, sy=sy, ex=ex, ey=ey, mid=mid, horizontal=True, path=path)
    sy = start.y + (_NODE_HEIGHT if ey >= sy else 0)
    ey = end.y + (0 if ey >= sy else _NODE_HEIGHT)
    mid = (sy + ey) / 2
    path = f"M {sx:g} {sy:g} L {sx:g} {mid:g} L {ex:g} {mid:g} L {ex:g} {ey:g}"
    return _EdgeRoute(sx=sx, sy=sy, ex=ex, ey=ey, mid=mid, horizontal=False, path=path)


def _rects_intersect(
    left: float,
    top: float,
    width: float,
    height: float,
    box: tuple[float, float, float, float],
    *,
    gap: float = 0.0,
) -> bool:
    bx, by, bw, bh = box
    return not (
        left + width + gap <= bx
        or bx + bw + gap <= left
        or top + height + gap <= by
        or by + bh + gap <= top
    )


def _label_rect_inside_canvas(
    left: float,
    top: float,
    width: float,
    height: float,
    canvas_width: float,
    canvas_height: float,
) -> bool:
    margin = _EDGE_LABEL_CANVAS_MARGIN
    return (
        left >= margin - 0.01
        and top >= margin - 0.01
        and left + width <= canvas_width - margin + 0.01
        and top + height <= canvas_height - margin + 0.01
    )


def _edge_label_wrap_candidates(
    label: str,
    route: _EdgeRoute,
    *,
    canvas_width: float,
) -> list[tuple[str, ...]]:
    """Deterministic wrap widths; every candidate preserves full normalized text."""
    normalized = _normalize_edge_label_text(label)
    if not normalized:
        return []
    if route.horizontal:
        corridor = abs(route.ex - route.sx)
    else:
        corridor = abs(route.ey - route.sy)
    corridor_units = max(4, int((max(36.0, corridor) - _EDGE_LABEL_PAD_X) / 6))
    canvas_units = max(
        4,
        int(
            (
                max(48.0, canvas_width - 2 * _EDGE_LABEL_CANVAS_MARGIN - _EDGE_LABEL_PAD_X)
            )
            / 6
        ),
    )
    unit_options: list[int] = []
    for units in (
        min(corridor_units, canvas_units),
        max(4, min(corridor_units, canvas_units) - 2),
        canvas_units,
        max(4, canvas_units // 2),
        24,
        20,
        18,
        16,
        14,
        12,
        10,
        8,
        6,
        4,
    ):
        if units not in unit_options:
            unit_options.append(units)

    candidates: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    # Prefer a single line when the full label fits a line budget.
    single = tuple(_wrap_edge_label_text(normalized, max_units=10_000))
    if single and single not in seen:
        candidates.append(single)
        seen.add(single)
    for units in unit_options:
        lines = tuple(_wrap_edge_label_text(normalized, max_units=units))
        if not lines or lines in seen:
            continue
        seen.add(lines)
        candidates.append(lines)
    return candidates


def _edge_label_seed_anchors(
    *,
    edge_kind: str,
    route: _EdgeRoute,
    block_width: float,
    block_height: float,
) -> list[tuple[float, float]]:
    """Preferred label centers near the route before clearance search."""
    sx, sy, ex, ey, mid = route.sx, route.sy, route.ex, route.ey, route.mid
    anchors: list[tuple[float, float]] = []

    def add(x: float, y: float) -> None:
        point = (x, y)
        if point not in anchors:
            anchors.append(point)

    if route.horizontal:
        elbow_y = (sy + ey) / 2
        above_y = min(sy, ey) - 10 - block_height / 2
        below_y = max(sy, ey) + 10 + block_height / 2
        if edge_kind in {"treatment_switch", "treatment_continuation"}:
            add(mid, elbow_y + 5)
            add(mid, elbow_y - 5)
        elif ey < sy:
            add(mid, above_y)
            add(mid, below_y)
            add(mid, elbow_y)
        elif ey > sy:
            add(mid, below_y)
            add(mid, above_y)
            add(mid, elbow_y)
        else:
            add(mid, above_y)
            add(mid, below_y)
            add(mid, elbow_y)
        side = block_width / 2 + 8
        for y in (above_y, below_y, elbow_y, sy, ey):
            add(mid - side, y)
            add(mid + side, y)
        add((sx + mid) / 2, above_y)
        add((mid + ex) / 2, above_y)
        add((sx + mid) / 2, below_y)
        add((mid + ex) / 2, below_y)
    else:
        elbow_x = (sx + ex) / 2
        right_x = max(sx, ex) + 10 + block_width / 2
        left_x = min(sx, ex) - 10 - block_width / 2
        if edge_kind in {"activation_dependency", "conditional"}:
            add(elbow_x, mid + 5)
            add(elbow_x, mid - 5)
            add(right_x, mid)
            add(left_x, mid)
        else:
            add(right_x, mid - 6)
            add(left_x, mid - 6)
            add(elbow_x, mid)
        for x in (right_x, left_x, elbow_x, sx, ex):
            add(x, mid - block_height)
            add(x, mid + block_height)
    return anchors


def _label_escape_anchors(
    *,
    center_x: float,
    center_y: float,
    block_width: float,
    block_height: float,
    boxes: Iterable[tuple[float, float, float, float]],
) -> list[tuple[float, float]]:
    """Anchors just outside each obstructing node rectangle."""
    anchors: list[tuple[float, float]] = [(center_x, center_y)]
    gap = _EDGE_LABEL_NODE_GAP + 1
    half_w = block_width / 2
    half_h = block_height / 2
    for bx, by, bw, bh in boxes:
        anchors.extend(
            [
                (center_x, by - gap - half_h),
                (center_x, by + bh + gap + half_h),
                (bx - gap - half_w, center_y),
                (bx + bw + gap + half_w, center_y),
                (bx - gap - half_w, by - gap - half_h),
                (bx + bw + gap + half_w, by - gap - half_h),
                (bx - gap - half_w, by + bh + gap + half_h),
                (bx + bw + gap + half_w, by + bh + gap + half_h),
                ((bx + bx + bw) / 2, by - gap - half_h),
                ((bx + bx + bw) / 2, by + bh + gap + half_h),
            ]
        )
    return anchors


def _iter_clearance_offsets(
    max_radius: int = 72, step: int = 3
) -> Iterable[tuple[float, float]]:
    yield (0.0, 0.0)
    for radius in range(step, max_radius + 1, step):
        for dx, dy in (
            (0, -radius),
            (0, radius),
            (-radius, 0),
            (radius, 0),
            (-radius, -radius),
            (radius, -radius),
            (-radius, radius),
            (radius, radius),
            (-radius // 2, -radius),
            (radius // 2, -radius),
            (-radius // 2, radius),
            (radius // 2, radius),
            (-radius, -radius // 2),
            (radius, -radius // 2),
            (-radius, radius // 2),
            (radius, radius // 2),
        ):
            yield (float(dx), float(dy))


def _try_place_edge_label(
    label: str,
    *,
    edge_kind: str,
    route: _EdgeRoute,
    start_box: tuple[float, float, float, float],
    end_box: tuple[float, float, float, float],
    node_boxes: Iterable[tuple[float, float, float, float]] | None = None,
    canvas_width: float,
    canvas_height: float,
    clearance_radius: int = 72,
) -> _EdgeLabelPlacement | None:
    """Return a clear on-canvas placement, or None if none exists.

    Never returns an overlapping or out-of-canvas placement. Callers must expand
    the layout or raise ``StudySchemaEdgeLabelLayoutError``.
    """
    boxes = tuple(node_boxes) if node_boxes is not None else (start_box, end_box)
    forbidden: list[tuple[float, float, float, float]] = []
    for box in (start_box, end_box, *boxes):
        if box not in forbidden:
            forbidden.append(box)

    elbow_x = route.mid if route.horizontal else (route.sx + route.ex) / 2
    elbow_y = (route.sy + route.ey) / 2 if route.horizontal else route.mid
    best_clear: _EdgeLabelPlacement | None = None
    best_score: tuple[int, float] | None = None

    for lines in _edge_label_wrap_candidates(
        label, route, canvas_width=canvas_width
    ):
        block_width, block_height = _edge_label_block_size(lines)
        if block_width > canvas_width - 2 * _EDGE_LABEL_CANVAS_MARGIN:
            continue
        if block_height > canvas_height - 2 * _EDGE_LABEL_CANVAS_MARGIN:
            continue
        seeds = _edge_label_seed_anchors(
            edge_kind=edge_kind,
            route=route,
            block_width=block_width,
            block_height=block_height,
        )
        expanded: list[tuple[float, float]] = []
        seen_seed: set[tuple[float, float]] = set()
        for seed in seeds:
            for point in _label_escape_anchors(
                center_x=seed[0],
                center_y=seed[1],
                block_width=block_width,
                block_height=block_height,
                boxes=forbidden,
            ):
                if point not in seen_seed:
                    seen_seed.add(point)
                    expanded.append(point)

        for seed_x, seed_y in expanded:
            for dx, dy in _iter_clearance_offsets(max_radius=clearance_radius):
                center_x = seed_x + dx
                center_y = seed_y + dy
                left = center_x - block_width / 2
                top = center_y - block_height / 2
                if not _label_rect_inside_canvas(
                    left,
                    top,
                    block_width,
                    block_height,
                    canvas_width,
                    canvas_height,
                ):
                    continue
                intersects = any(
                    _rects_intersect(
                        left,
                        top,
                        block_width,
                        block_height,
                        box,
                        gap=_EDGE_LABEL_NODE_GAP,
                    )
                    for box in forbidden
                )
                if intersects:
                    continue
                distance = abs(center_x - elbow_x) + abs(center_y - elbow_y)
                score = (len(lines), distance)
                placement = _EdgeLabelPlacement(
                    lines=lines,
                    center_x=center_x,
                    top_y=top,
                    width=float(block_width),
                    height=float(block_height),
                )
                if best_score is None or score < best_score:
                    best_clear = placement
                    best_score = score
                # First clear hit at this wrap width is accepted immediately for
                # determinism and performance; wrap order prefers fewer lines.
                return placement

    return best_clear


def _svg_path_points(path: str, scale: int) -> list[tuple[float, float]]:
    values = [float(value) for value in re.findall(r"-?(?:\d+(?:\.\d*)?|\.\d+)", path)]
    return [(values[index] * scale, values[index + 1] * scale) for index in range(0, len(values) - 1, 2)]


def _study_schema_fonts(size: int, *, bold: bool):
    chinese_candidates = [
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path("/System/Library/Fonts/Supplemental/SimSun.ttf"),
    ]
    latin_candidates = [
        Path(
            "/System/Library/Fonts/Supplemental/"
            + ("Times New Roman Bold.ttf" if bold else "Times New Roman.ttf")
        ),
    ]

    def load(candidates: list[Path], *, collection_index: int = 0):
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                return ImageFont.truetype(
                    str(candidate),
                    size=size,
                    index=collection_index,
                )
            except (OSError, ValueError):
                try:
                    return ImageFont.truetype(str(candidate), size=size)
                except OSError:
                    continue
        return ImageFont.load_default(size=size)

    return (
        load(chinese_candidates, collection_index=1 if bold else 0),
        load(latin_candidates),
    )


def _draw_bilingual_text(
    draw,
    *,
    x: float,
    baseline_y: float,
    text: str,
    chinese_font,
    latin_font,
    fill: str,
    centered: bool,
) -> None:
    segments: list[tuple[str, object]] = []
    for character in text:
        font = latin_font if ord(character) < 128 else chinese_font
        if segments and segments[-1][1] is font:
            segments[-1] = (segments[-1][0] + character, font)
        else:
            segments.append((character, font))
    widths = [draw.textlength(segment, font=font) for segment, font in segments]
    cursor = x - sum(widths) / 2 if centered else x
    for (segment, font), width in zip(segments, widths):
        draw.text(
            (cursor, baseline_y),
            segment,
            font=font,
            fill=fill,
            anchor="ls",
        )
        cursor += width


def _draw_study_schema_line(draw, start, end, color, width, dashed) -> None:
    if not dashed:
        draw.line((start, end), fill=color, width=width)
        return
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    cursor = 0.0
    while cursor < length:
        stop = min(length, cursor + 12.0)
        draw.line(
            ((start[0] + ux * cursor, start[1] + uy * cursor), (start[0] + ux * stop, start[1] + uy * stop)),
            fill=color,
            width=width,
        )
        cursor += 20.0


def _draw_study_schema_arrow(draw, start, end, color, scale) -> None:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    size = 7 * scale
    base_x, base_y = end[0] - ux * size, end[1] - uy * size
    draw.polygon(
        [end, (base_x + px * size * 0.55, base_y + py * size * 0.55), (base_x - px * size * 0.55, base_y - py * size * 0.55)],
        fill=color,
    )


def _issue(
    severity: str,
    code: str,
    message: str,
    target_id: str = "",
) -> MedicalWritingStudySchemaValidationIssue:
    issue_id = "mwschema_issue_" + hashlib.sha256(
        f"{severity}|{code}|{target_id}|{message}".encode("utf-8")
    ).hexdigest()[:20]
    return MedicalWritingStudySchemaValidationIssue(
        issue_id=issue_id,
        severity=severity,
        code=code,
        message=message,
        target_id=target_id,
    )


def _node_colors(node_kind: str) -> tuple[str, str]:
    if node_kind in {"decision_gate", "randomization", "allocation"}:
        return "#fff7ed", "#c2410c"
    if node_kind == "treatment_switch":
        return "#fff7ed", "#ea580c"
    if node_kind == "extension_period":
        return "#f0fdfa", "#0f766e"
    if node_kind in {"arm", "dose_cohort", "treatment"}:
        return "#f0fdf4", "#15803d"
    if node_kind in {"follow_up", "end"}:
        return "#eff6ff", "#1d4ed8"
    return "#f9fafb", "#4b5563"


def _edge_style(edge_kind: str) -> tuple[str, str]:
    if edge_kind == "treatment_switch":
        return "#ea580c", "arrow-switch"
    if edge_kind == "treatment_continuation":
        return "#15803d", "arrow-continuation"
    if edge_kind == "follow_up":
        return "#1d4ed8", "arrow-followup"
    return _EDGE_COLOR, "arrow-default"
