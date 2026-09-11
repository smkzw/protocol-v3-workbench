"""Task 3R.1: deterministic TP-MA-07 v2 candidate registry extraction.

Reads the approved TP-MA-07 v2.0 clean DOCX (zip/XML only, never written) and
the legacy company template module (AST only, never imported), then emits the
three candidate JSON registries:

- template.json            candidate registry summary + authoritative counts
- node_tree.json           heading-style tree, outlined tree, tables, sections
- v1_to_v2_mapping.json    explicit two-way legacy mapping + projection evidence

Every run is deterministic: same inputs produce byte-identical outputs, with no
timestamps or volatile paths. The output stays ``candidate_not_current`` until
Codex and a fresh independent reviewer finish source coverage checks.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
SOURCE_DOCX_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/"
    "TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx"
)
EXPECTED_SHA256 = (
    "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
)
LEGACY_MODULE_REL = "services/api/app/medical_writing_protocol_template.py"
LEGACY_MODULE_PATH = ROOT / LEGACY_MODULE_REL
DEFAULT_OUT_DIR = ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"

TEMPLATE_ID = "tp_ma_07_v2"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
FRONT_BLOCK_ID = "v2_front_block"


class RegistrySourceError(RuntimeError):
    """Raised when the source gate or extraction invariants fail."""


# ---------------------------------------------------------------------------
# Source gate
# ---------------------------------------------------------------------------


def verify_source_hash(path: Path | str = SOURCE_DOCX_PATH) -> str:
    path = Path(path)
    if not path.is_file():
        raise RegistrySourceError(f"source file missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RegistrySourceError(
            "source hash mismatch: expected "
            f"{EXPECTED_SHA256}, observed {digest} for {path}"
        )
    return digest


# ---------------------------------------------------------------------------
# DOCX structural extraction (read-only zip/XML)
# ---------------------------------------------------------------------------


def _style_table(styles_xml: bytes) -> dict[str, dict]:
    root = ET.fromstring(styles_xml)
    styles: dict[str, dict] = {}
    for style in root.findall(f"{{{W}}}style"):
        style_id = style.get(f"{{{W}}}styleId") or ""
        name_el = style.find(f"{{{W}}}name")
        name = name_el.get(f"{{{W}}}val") if name_el is not None else ""
        ppr = style.find(f"{{{W}}}pPr")
        outline = None
        numbering = {"num_id": None, "ilvl": None}
        if ppr is not None:
            outline_el = ppr.find(f"{{{W}}}outlineLvl")
            if outline_el is not None:
                outline = int(outline_el.get(f"{{{W}}}val"))
            num_pr = ppr.find(f"{{{W}}}numPr")
            if num_pr is not None:
                num_id_el = num_pr.find(f"{{{W}}}numId")
                if num_id_el is not None:
                    numbering["num_id"] = int(num_id_el.get(f"{{{W}}}val"))
                ilvl_el = num_pr.find(f"{{{W}}}ilvl")
                if ilvl_el is not None:
                    numbering["ilvl"] = int(ilvl_el.get(f"{{{W}}}val"))
        based_el = style.find(f"{{{W}}}basedOn")
        font = {
            "ascii": None,
            "east_asia": None,
            "size_half_points": None,
            "bold": None,
        }
        rpr = style.find(f"{{{W}}}rPr")
        if rpr is not None:
            fonts_el = rpr.find(f"{{{W}}}rFonts")
            if fonts_el is not None:
                font["ascii"] = fonts_el.get(f"{{{W}}}ascii")
                font["east_asia"] = fonts_el.get(f"{{{W}}}eastAsia")
            size_el = rpr.find(f"{{{W}}}sz")
            if size_el is not None:
                font["size_half_points"] = int(size_el.get(f"{{{W}}}val"))
            bold_el = rpr.find(f"{{{W}}}b")
            if bold_el is not None:
                value = bold_el.get(f"{{{W}}}val")
                font["bold"] = value not in ("0", "false", "off")
        styles[style_id] = {
            "name": name,
            "outline": outline,
            "based_on": based_el.get(f"{{{W}}}val") if based_el is not None else None,
            "numbering": numbering,
            "font": font,
        }
    return styles


def _resolved_outline(style_id: str | None, styles: dict[str, dict]) -> int | None:
    seen: set[str] = set()
    current = style_id
    while current and current not in seen and current in styles:
        seen.add(current)
        info = styles[current]
        if info["outline"] is not None:
            return info["outline"]
        current = info["based_on"]
    return None


def _is_heading_style_name(name: str) -> bool:
    lowered = name.lower()
    return ("heading" in lowered or name.startswith("标题")) and not name.endswith(
        "字符"
    )


def _para_text(paragraph) -> str:
    return "".join(node.text or "" for node in paragraph.iter(f"{{{W}}}t"))


def _para_style(paragraph) -> tuple[str | None, int | None]:
    ppr = paragraph.find(f"{{{W}}}pPr")
    if ppr is None:
        return None, None
    style_el = ppr.find(f"{{{W}}}pStyle")
    style_id = style_el.get(f"{{{W}}}val") if style_el is not None else None
    outline_el = ppr.find(f"{{{W}}}outlineLvl")
    local = int(outline_el.get(f"{{{W}}}val")) if outline_el is not None else None
    return style_id, local


def _leaf_flags(levels: list[int]) -> list[bool]:
    return [
        index == len(levels) - 1 or levels[index + 1] <= level
        for index, level in enumerate(levels)
    ]


def _field_inventory(root) -> dict[str, int]:
    """Count field starts, not instruction fragments such as MERGEFORMAT."""
    kinds = {"TOC", "PAGEREF", "HYPERLINK", "REF", "SEQ", "PAGE", "NUMPAGES",
             "SECTION", "SECTIONPAGES", "DATE", "TIME", "DOCPROPERTY", "STYLEREF"}
    instructions = [node.text or "" for node in root.iter(f"{{{W}}}instrText")]
    instructions += [node.get(f"{{{W}}}instr", "") for node in root.iter(f"{{{W}}}fldSimple")]
    return dict(sorted(Counter(
        text.strip().split()[0].upper() for text in instructions
        if text.strip() and text.strip().split()[0].upper() in kinds
    ).items()))


def extract_docx_structure(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        styles_xml = archive.read("word/styles.xml")
        document_xml = archive.read("word/document.xml")
        part_fields = {
            name: _field_inventory(ET.fromstring(archive.read(name)))
            for name in sorted(archive.namelist())
            if re.fullmatch(r"word/(document|header\d+|footer\d+)\.xml", name)
        }
        rels_xml = archive.read("word/_rels/document.xml.rels")
    rel_targets = {
        rel.get("Id"): rel.get("Target") or ""
        for rel in ET.fromstring(rels_xml).iter(f"{{{PKG_REL}}}Relationship")
    }
    styles = _style_table(styles_xml)
    document = ET.fromstring(document_xml)
    body = document.find(f"{{{W}}}body")
    if body is None:
        raise RegistrySourceError("document.xml has no body")

    body_children = list(body)
    paragraph_records: list[dict] = []
    table_records: list[dict] = []
    tracked_changes = sum(
        len(list(document.iter(f"{{{W}}}{tag}")))
        for tag in ("ins", "del", "moveFrom", "moveTo")
    )

    for index, element in enumerate(body_children):
        if element.tag == f"{{{W}}}p":
            style_id, local_outline = _para_style(element)
            style_outline = (
                _resolved_outline(style_id, styles) if style_id else None
            )
            effective = (
                local_outline if local_outline is not None else style_outline
            )
            heading_style = bool(
                style_id
                and style_id in styles
                and _is_heading_style_name(styles[style_id]["name"])
            )
            text = _para_text(element)
            paragraph_records.append(
                {
                    "index": index,
                    "style_id": style_id,
                    "style_name": (
                        styles[style_id]["name"] if style_id in styles else ""
                    ),
                    "outline_local": local_outline,
                    "outline_effective": effective,
                    "heading_style": heading_style,
                    "nonblank": bool(text.strip()),
                    "text": text.strip(),
                    "para_id": element.get(f"{{{W14}}}paraId"),
                    "bookmarks": [
                        marker.get(f"{{{W}}}name") or ""
                        for marker in element.iter(f"{{{W}}}bookmarkStart")
                    ],
                    "field_kinds": list(_field_inventory(element)),
                }
            )
        elif element.tag == f"{{{W}}}tbl":
            rows = element.findall(f"{{{W}}}tr")
            cols = len(rows[0].findall(f"{{{W}}}tc")) if rows else 0
            nested = len(list(element.iter(f"{{{W}}}tbl"))) - 1
            caption = None
            previous = body_children[index - 1] if index else None
            if previous is not None and previous.tag == f"{{{W}}}p":
                style_id, _ = _para_style(previous)
                text = _para_text(previous).strip()
                if text and (
                    (style_id in styles and styles[style_id]["name"] == "caption")
                    or re.match(r"^表\s*\d+", text)
                ):
                    caption = text
            table_records.append(
                {
                    "body_child_index": index,
                    "owner_node_id": "",
                    "row_count": len(rows),
                    "column_count": cols,
                    "nested_table_count": nested,
                    "caption": caption,
                }
            )

    instruction_tokens = _field_inventory(document)
    bookmark_names = [
        node.get(f"{{{W}}}name") or ""
        for node in document.iter(f"{{{W}}}bookmarkStart")
    ]

    sections = []
    ordinal = 0
    for index, element in enumerate(body_children):
        sect = None
        holder = None
        if element.tag == f"{{{W}}}sectPr":
            sect, holder = element, "body-final"
        elif element.tag == f"{{{W}}}p":
            ppr = element.find(f"{{{W}}}pPr")
            if ppr is not None and ppr.find(f"{{{W}}}sectPr") is not None:
                sect, holder = ppr.find(f"{{{W}}}sectPr"), "p"
        if sect is None:
            continue
        ordinal += 1
        type_el = sect.find(f"{{{W}}}type")
        size_el = sect.find(f"{{{W}}}pgSz")
        num_type_el = sect.find(f"{{{W}}}pgNumType")

        def reference_bindings(tag: str) -> list[dict]:
            bindings = []
            for ref in sect.findall(f"{{{W}}}{tag}"):
                rid = ref.get(f"{{{R}}}id")
                target = rel_targets.get(rid, "")
                bindings.append(
                    {
                        "type": ref.get(f"{{{W}}}type"),
                        "r_id": rid,
                        "part": f"word/{target}" if target else "",
                    }
                )
            return bindings

        sections.append(
            {
                "ordinal": ordinal,
                "holder": holder,
                "body_child_index": index,
                "type": (
                    type_el.get(f"{{{W}}}val") if type_el is not None else "nextPage"
                ),
                "page_size": (
                    {k.split("}")[1]: v for k, v in size_el.attrib.items()}
                    if size_el is not None
                    else {}
                ),
                "pg_num_type": (
                    {k.split("}")[1]: v for k, v in num_type_el.attrib.items()}
                    if num_type_el is not None
                    else {}
                ),
                "header_reference": reference_bindings("headerReference"),
                "footer_reference": reference_bindings("footerReference"),
            }
        )

    # Outlined nodes: nonblank paragraphs with effective outline level 0-8.
    outlined = [
        record
        for record in paragraph_records
        if record["outline_effective"] is not None
        and record["outline_effective"] <= 8
        and record["nonblank"]
    ]
    outlined_indexes = {record["index"] for record in outlined}

    chapter_style_ids = {
        style_id
        for style_id, info in styles.items()
        if info["name"] == "标题 1 1."
    }
    chapter_start = None
    for position, record in enumerate(outlined):
        if record["style_id"] in chapter_style_ids:
            chapter_start = position
            break
    if chapter_start is None:
        raise RegistrySourceError("no numbered chapter style found in outlined tree")

    # Build the outlined tree with derived section numbers.
    nodes: list[dict] = []
    stack: list[dict] = []
    front_counter = 0
    chapter_counter = 0
    section_counters: list[int] = []
    extra_counter = 0
    for position, record in enumerate(outlined):
        level = record["outline_effective"]
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        parent = stack[-1] if stack else None
        if position < chapter_start:
            front_counter += 1
            node_id = f"v2_n_front_{front_counter}"
            section_number = ""
        elif not record["heading_style"]:
            extra_counter += 1
            parent_number = parent["section_number"] if parent else ""
            node_id = (
                f"v2_n_{parent_number.replace('.', '_')}_x{extra_counter}"
                if parent_number
                else f"v2_n_x{extra_counter}"
            )
            section_number = (
                f"{parent_number} 附录{extra_counter}" if parent_number else ""
            )
        elif level == 0:
            chapter_counter += 1
            section_counters = [chapter_counter]
            section_number = str(chapter_counter)
            node_id = "v2_n_" + section_number.replace(".", "_")
        else:
            target = level + 1
            while len(section_counters) < target:
                section_counters.append(0)
            section_counters = section_counters[:target]
            section_counters[-1] += 1
            section_number = ".".join(str(part) for part in section_counters)
            node_id = "v2_n_" + section_number.replace(".", "_")
        node = {
            "id": node_id,
            "section_number": section_number,
            "title_zh": record["text"],
            "level": level,
            "parent_id": parent["id"] if parent else "",
            "order": position,
            "body_child_index": record["index"],
            "para_id": record["para_id"],
            "style_id": record["style_id"],
            "style_name": record["style_name"],
            "outline_source": (
                "paragraph_local"
                if record["outline_local"] is not None
                else "style"
            ),
            "in_heading_style_tree": record["heading_style"],
            "is_leaf": False,
            "is_leaf_heading": False,
            "bookmarks": record["bookmarks"],
            "field_kinds": record["field_kinds"],
            "content_paragraph_indexes": [],
        }
        nodes.append(node)
        stack.append(node)

    outlined_levels = [node["level"] for node in nodes]
    for position, flag in enumerate(_leaf_flags(outlined_levels)):
        nodes[position]["is_leaf"] = flag

    heading_seq = [node for node in nodes if node["in_heading_style_tree"]]
    heading_levels = [node["level"] for node in heading_seq]
    heading_leaf_ids = set()
    for position, flag in enumerate(_leaf_flags(heading_levels)):
        if flag:
            heading_leaf_ids.add(heading_seq[position]["id"])
        heading_seq[position]["is_leaf_heading"] = flag

    node_by_body_index = {node["body_child_index"]: node for node in nodes}
    for table in table_records:
        owner = None
        for position in range(table["body_child_index"] - 1, -1, -1):
            candidate = node_by_body_index.get(position)
            if candidate is not None:
                owner = candidate
                break
        table["owner_node_id"] = owner["id"] if owner else ""

    # Content paragraphs attach to the nearest preceding outlined node.
    first_outlined_index = nodes[0]["body_child_index"]
    front_content: list[int] = []
    for record in paragraph_records:
        index = record["index"]
        if index < first_outlined_index:
            if record["nonblank"]:
                front_content.append(index)
            continue
        if index in outlined_indexes or not record["nonblank"]:
            continue
        owner = None
        for position in range(index - 1, first_outlined_index - 1, -1):
            candidate = node_by_body_index.get(position)
            if candidate is not None:
                owner = candidate
                break
        if owner is not None:
            owner["content_paragraph_indexes"].append(index)

    excluded_blank = [
        {
            "body_child_index": record["index"],
            "style_id": record["style_id"],
            "outline_level": record["outline_effective"],
        }
        for record in paragraph_records
        if record["outline_effective"] is not None
        and record["outline_effective"] <= 8
        and not record["nonblank"]
    ]

    # Semantic findings derived from structural rules.
    by_id = {node["id"]: node for node in nodes}
    findings: list[dict] = []

    companion = by_id.get("v2_n_3_1_2_4")
    if companion is not None and companion["content_paragraph_indexes"]:
        findings.append(
            {
                "id": "estimand_fifth_attribute_tail_content",
                "v2_node_id": companion["id"],
                "body_child_indexes": list(
                    companion["content_paragraph_indexes"]
                ),
                "note": (
                    "主要估计目标第四属性（伴发事件）标题之后仍存在未标题正文"
                    "（候选第五属性，如群体层面汇总），逐叶合同不得默认四属性闭合。"
                ),
            }
        )
    preclinical = by_id.get("v2_n_2_2_2_1")
    if preclinical is not None and preclinical["content_paragraph_indexes"]:
        findings.append(
            {
                "id": "unheaded_preclinical_content",
                "v2_node_id": preclinical["id"],
                "body_child_indexes": list(
                    preclinical["content_paragraph_indexes"]
                ),
                "note": (
                    "药效学研究标题下存在未标题内容段落（如毒理学/药代/一般药理），"
                    "标题叶计数不代表内容闭合。"
                ),
            }
        )
    example_hits = [
        {
            "body_child_index": record["index"],
            "snippet": record["text"][:60],
        }
        for record in paragraph_records
        if record["nonblank"] and "示例" in record["text"]
    ]
    findings.append(
        {
            "id": "example_labeled_content",
            "body_child_indexes": [item["body_child_index"] for item in example_hits],
            "items": example_hits,
            "note": "标记为示例的段落是模板指引，不是项目事实；投影与合同禁止照抄。",
        }
    )

    direct_text = "".join(record["text"] for record in paragraph_records)
    table_text = "".join(
        node.text or ""
        for element in body_children
        if element.tag == f"{{{W}}}tbl"
        for node in element.iter(f"{{{W}}}t")
    )
    all_text = "".join(node.text or "" for node in document.iter(f"{{{W}}}t"))

    return {
        "nodes": nodes,
        "styles": styles,
        "heading_leaf_ids": sorted(heading_leaf_ids),
        "heading_leaf_count": len(heading_leaf_ids),
        "direct_body_paragraphs": len(paragraph_records),
        "top_level_tables": table_records,
        "recursive_tables": sum(
            1
            for element in body_children
            if element.tag == f"{{{W}}}tbl"
            for _ in element.iter(f"{{{W}}}tbl")
        ),
        "tracked_changes": tracked_changes,
        "sections": sections,
        "bookmark_inventory": {
            "total": len(bookmark_names),
            "toc_anchored": sum(
                1 for name in bookmark_names if name.startswith("_Toc")
            ),
            "other": sum(
                1 for name in bookmark_names if not name.startswith("_Toc")
            ),
        },
        "field_inventory": dict(sorted(instruction_tokens.items())),
        "part_field_inventory": part_fields,
        "excluded_blank_outlined": excluded_blank,
        "front_block": {
            "body_child_index_range": [0, first_outlined_index],
            "content_paragraph_indexes": front_content,
            "note": "首个标题之前的无标题前置块（封面、版本、保密声明等内容承载区）。",
        },
        "semantic_findings": findings,
        "terminology": {
            "试验参与者": {
                "direct_body_paragraphs": direct_text.count("试验参与者"),
                "top_level_tables": table_text.count("试验参与者"),
                "all_document_text": all_text.count("试验参与者"),
            },
            "受试者": {
                "direct_body_paragraphs": direct_text.count("受试者"),
                "top_level_tables": table_text.count("受试者"),
                "all_document_text": all_text.count("受试者"),
            },
        },
    }


# ---------------------------------------------------------------------------
# Legacy module inventory (AST only, module never imported)
# ---------------------------------------------------------------------------


def _literal(node):
    return ast.literal_eval(node)


def _strip_constant(value):
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        value = value.func.value
    if isinstance(value, ast.Constant):
        return value.value
    return None


def extract_legacy_inventory(path: Path = LEGACY_MODULE_PATH) -> dict:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    chapters_text = None
    chapters_lineno = None
    conditional_prefixes: tuple[str, ...] = ()
    chapter_paths: dict[str, tuple[str, ...]] = {}
    chapter_paths_lineno = None
    node_kind_map: dict[str, str] = {}
    front_nodes: list[dict] = []
    function_index: dict[str, int] = {}
    section_seed_branches: list[dict] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function_index[node.name] = node.lineno
            if node.name == "_node_kind":
                for sub in ast.walk(node):
                    if not isinstance(sub, ast.Return):
                        continue
                    value = sub.value
                    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                        value = value.func.value
                    if isinstance(value, ast.Dict):
                        node_kind_map = {
                            key.value: item.value
                            for key, item in zip(value.keys, value.values)
                        }
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            targets = node.targets
        target_names = {
            target.id for target in targets if isinstance(target, ast.Name)
        }
        value = node.value
        if "_COMPANY_CHAPTERS" in target_names:
            constant = _strip_constant(value)
            if constant is not None:
                chapters_text = constant
                chapters_lineno = node.lineno
        elif "_CONDITIONAL_PREFIXES" in target_names and isinstance(
            value, (ast.Tuple, ast.List)
        ):
            conditional_prefixes = tuple(_literal(value))
        elif "_CHAPTER_BODY_FACT_PATHS" in target_names and isinstance(value, ast.Dict):
            chapter_paths = {
                key.value: tuple(_literal(item))
                for key, item in zip(value.keys, value.values)
            }
            chapter_paths_lineno = node.lineno

    if chapters_text is None:
        raise RegistrySourceError("_COMPANY_CHAPTERS not found via AST")

    rows: list[dict] = []
    for line in chapters_text.splitlines():
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) != 5:
            raise RegistrySourceError(f"unexpected _COMPANY_CHAPTERS row: {line!r}")
        number, semantic_id, title, rules_text, anchors_text = parts
        rows.append(
            {
                "section_number": number,
                "semantic_node_id": semantic_id,
                "title_zh": title,
                "applicability_rules": [
                    rule for rule in rules_text.split(",") if rule
                ],
                "m11_coverage_anchors": [
                    anchor for anchor in anchors_text.split(",") if anchor
                ],
            }
        )

    def level_of(number: str) -> int:
        return number.count(".") + 1

    for position, row in enumerate(rows):
        number = row["section_number"]
        row["level"] = level_of(number)
        row["parent_section_number"] = (
            number.rsplit(".", 1)[0] if "." in number else ""
        )
        row["is_leaf"] = position == len(rows) - 1 or (
            level_of(rows[position + 1]["section_number"]) <= row["level"]
        )
        conditional = any(
            number == item or number.startswith(f"{item}.")
            for item in conditional_prefixes
        )
        row["applicability_mode"] = (
            "conditional_by_design" if conditional else "required"
        )
        row["node_kind"] = node_kind_map.get(number, "section")

    company_function = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_company_nodes":
            company_function = node
    if company_function is None:
        raise RegistrySourceError("_company_nodes not found via AST")
    for item in company_function.body:
        if (
            isinstance(item, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "nodes"
                for target in item.targets
            )
            and isinstance(item.value, ast.List)
        ):
            for element in item.value.elts:
                if not isinstance(element, ast.Call):
                    continue
                keywords = {keyword.arg: keyword.value for keyword in element.keywords}
                front_nodes.append(
                    {
                        "node_id": _literal(keywords["node_id"]),
                        "semantic_node_id": _literal(keywords["semantic_node_id"]),
                        "title_zh": _literal(keywords["title_zh"]),
                        "level": _literal(keywords["level"]),
                        "node_kind": _literal(keywords["node_kind"]),
                        "applicability_mode": _literal(keywords["applicability_mode"]),
                        "repeatable": _literal(keywords["repeatable"]),
                        "include_in_toc": _literal(keywords["include_in_toc"]),
                    }
                )
            break

    seeds_function = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == (
            "MedicalWritingProtocolTemplateService"
        ):
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == (
                    "section_seeds"
                ):
                    seeds_function = member
    if seeds_function is not None:
        for node in ast.walk(seeds_function):
            if not isinstance(node, ast.Compare):
                continue
            sides = [node.left, *node.comparators]
            has_semantic = any(
                isinstance(side, ast.Attribute) and side.attr == "semantic_node_id"
                for side in sides
            )
            has_kind = any(
                isinstance(side, ast.Attribute) and side.attr == "node_kind"
                for side in sides
            )
            constants: list[str] = []
            for side in sides:
                if isinstance(side, ast.Constant) and isinstance(side.value, str):
                    constants.append(side.value)
                elif isinstance(side, (ast.Set, ast.Tuple, ast.List)):
                    try:
                        constants.extend(
                            str(item)
                            for item in _literal(side)
                            if isinstance(item, str)
                        )
                    except ValueError:
                        pass
            if has_semantic and constants:
                section_seed_branches.append(
                    {
                        "kind": "semantic_node_id_branch",
                        "values": constants,
                        "lineno": node.lineno,
                    }
                )
            elif has_kind and constants:
                section_seed_branches.append(
                    {
                        "kind": "node_kind_branch",
                        "values": constants,
                        "lineno": node.lineno,
                    }
                )

    inventory: list[dict] = []
    for front in front_nodes:
        inventory.append(
            {
                "node_id": front["node_id"],
                "semantic_node_id": front["semantic_node_id"],
                "section_number": "",
                "parent_node_id": "",
                "title_zh": front["title_zh"],
                "level": 0,
                "node_kind": front["node_kind"],
                "applicability_mode": front["applicability_mode"],
                "applicability_rules": [],
                "m11_coverage_anchors": [],
                "repeatable": front["repeatable"],
                "is_leaf": True,
            }
        )
    node_id_by_number: dict[str, str] = {}
    for row in rows:
        number = row["section_number"]
        node_id_by_number[number] = (
            "cms_"
            + re.sub(r"[^a-z0-9]+", "_", row["semantic_node_id"].lower()).strip("_")
        )
    for row in rows:
        inventory.append(
            {
                "node_id": node_id_by_number[row["section_number"]],
                "semantic_node_id": row["semantic_node_id"],
                "section_number": row["section_number"],
                "parent_node_id": node_id_by_number.get(
                    row["parent_section_number"], ""
                ),
                "title_zh": row["title_zh"],
                "level": row["level"],
                "node_kind": row["node_kind"],
                "applicability_mode": row["applicability_mode"],
                "applicability_rules": row["applicability_rules"],
                "m11_coverage_anchors": row["m11_coverage_anchors"],
                "repeatable": False,
                "is_leaf": row["is_leaf"],
            }
        )

    row_leaves = [row for row in rows if row["is_leaf"]]
    leaves = [node for node in inventory if node["is_leaf"]]
    phase1_leaves = [
        node
        for node in leaves
        if any(rule.startswith("phase:1") for rule in node["applicability_rules"])
    ]

    return {
        "module_path": LEGACY_MODULE_REL,
        "module_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "chapters_lineno": chapters_lineno,
        "_conditional_prefixes": list(conditional_prefixes),
        "chapter_row_count": len(rows),
        "chapter_row_leaves": len(row_leaves),
        "front_node_count": len(front_nodes),
        "node_count": len(inventory),
        "leaf_count": len(leaves),
        "phase1_leaf_count": len(phase1_leaves),
        "nodes": inventory,
        "chapter_body_fact_paths": {
            semantic: list(paths) for semantic, paths in chapter_paths.items()
        },
        "chapter_body_fact_paths_lineno": chapter_paths_lineno,
        "section_seed_branches": section_seed_branches,
        "function_index": dict(sorted(function_index.items())),
    }


def _projection_evidence(legacy: dict) -> dict[str, list[dict]]:
    evidence: dict[str, list[dict]] = {}
    fact_lineno = legacy["chapter_body_fact_paths_lineno"]
    for semantic, paths in legacy["chapter_body_fact_paths"].items():
        evidence.setdefault(semantic, []).append(
            {
                "mechanism": "_CHAPTER_BODY_FACT_PATHS",
                "location": f"{LEGACY_MODULE_REL}:{fact_lineno}",
                "fact_paths": list(paths),
            }
        )
    for branch in legacy["section_seed_branches"]:
        if branch["kind"] != "semantic_node_id_branch":
            continue
        location = f"{LEGACY_MODULE_REL}:{branch['lineno']}"
        for value in branch["values"]:
            evidence.setdefault(value, []).append(
                {
                    "mechanism": "section_seeds_branch",
                    "location": location,
                    "fact_paths": [],
                }
            )
    return evidence


def count_explicit_projection_leaves(legacy: dict | None = None) -> int:
    legacy = legacy or extract_legacy_inventory()
    evidence = _projection_evidence(legacy)
    node_kinds = {
        value
        for branch in legacy["section_seed_branches"]
        if branch["kind"] == "node_kind_branch"
        for value in branch["values"]
    }
    count = 0
    for node in legacy["nodes"]:
        if not node["is_leaf"]:
            continue
        if node["semantic_node_id"] in evidence or node["node_kind"] in node_kinds:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Explicit two-way mapping tables (worker semantic judgment, pending Codex review)
# ---------------------------------------------------------------------------

PHASE1_RATIONALE = (
    "Ⅰ期专属章节（applicability 含 phase:1），本候选面向 TP-MA-07 v2（Ⅱ/Ⅲ期）模板；"
    "Ⅰ期模板权威为 Task 3R.6 用户决策，历史身份按 cms 编号原样保留，不静默退役。"
)


def _m(disposition, targets, rationale, confidence="structural", ambiguity_note=""):
    return {
        "disposition": disposition,
        "target_v2_node_ids": targets,
        "rationale": rationale,
        "confidence": confidence,
        "ambiguity_note": ambiguity_note,
    }


LEGACY_MAPPING: dict[str, dict] = {
    # --- front matter nodes (cms_*) ---
    "document_control.front_matter": _m(
        "mapped_to_v2", [FRONT_BLOCK_ID],
        "v2 以首标题前的无标题前置块承载首页与版本信息。",
    ),
    "document_control.confidentiality": _m(
        "mapped_to_v2", [FRONT_BLOCK_ID],
        "v2 无独立保密声明标题，保密内容位于无标题前置块。",
        "partial",
        "保密声明在 v2 无专属标题节点，仅由前置块承载，语义复核归 Codex。",
    ),
    "document_control.signatures": _m(
        "split", ["v2_n_front_2", "v2_n_front_3"],
        "v2 将签字页拆分为主要研究者签字页与申办者签字页。",
    ),
    "document_control.version_history": _m(
        "mapped_to_v2", ["v2_n_front_1"], "对应 v2 方案修订历史记录。"
    ),
    "document_control.indexes": _m(
        "split", ["v2_n_front_6", "v2_n_front_7", "v2_n_front_8"],
        "v2 拆分为目录、表目录、图目录三个标题。",
    ),
    "document_control.glossary": _m(
        "mapped_to_v2", ["v2_n_front_5"],
        "对应 v2 缩略语表（Normal 样式加本地大纲级别，保留为大纲节点）。",
    ),
    # --- chapter 1 ---
    "synopsis": _m("mapped_to_v2", ["v2_n_1"], "方案概要对 v2 第1章方案摘要（容器）。"),
    "synopsis.summary": _m("mapped_to_v2", ["v2_n_1_1"], "方案摘要对 v2 1.1 概要。"),
    "synopsis.schema": _m("mapped_to_v2", ["v2_n_1_2"], "研究示意图在 v2 更名为研究流程图。"),
    "synopsis.schedule": _m("mapped_to_v2", ["v2_n_1_3"], "研究流程表对应 v2 1.3 研究流程表（SOA）。"),
    # --- chapter 2 ---
    "background": _m("mapped_to_v2", ["v2_n_2"], "研究背景和立项依据对 v2 第2章引言（容器）。"),
    "background.disease": _m(
        "mapped_to_v2", ["v2_n_2_2"],
        "疾病背景及治疗现状由 v2 2.2 背景下未标题内容承载。",
        "partial",
        "v2 未单列疾病背景标题，承载边界需 Codex 语义复核。",
    ),
    "background.mechanism": _m(
        "split", ["v2_n_2_2_1", "v2_n_2_2_3"],
        "作用机制并入研究药物，同类药物进展对应同类药物研究概述。",
        "partial",
        "v1 2.2 一节承担两个主题，v2 拆分后的内容边界需语义复核。",
    ),
    "background.product": _m(
        "mapped_to_v2", ["v2_n_2_2_1"], "研究药物简介对 v2 2.2.1 研究药物（容器）。"
    ),
    "background.product.nonclinical": _m(
        "mapped_to_v2", ["v2_n_2_2_2"],
        "非临床研究结果对应 v2 2.2.2 临床前研究概述（含未标题内容）。",
        "partial",
        "子树含未标题毒理学/药代/一般药理义务与 v2 新增药效学研究子标题，"
        "非临床证据的完整覆盖边界需语义复核（见 semantic_findings "
        "unheaded_preclinical_content）。",
    ),
    "background.product.clinical": _m(
        "mapped_to_v2", ["v2_n_2_2_3"],
        "既往临床研究结果暂按最近邻标题同类药物研究概述承载。",
        "partial",
        "v2 未单列既往临床研究标题，与研究药物临床信息的边界需语义复核。",
    ),
    "background.rationale": _m(
        "mapped_to_v2", ["v2_n_2_1"], "理论基础对应 v2 2.1 研究理论依据。"
    ),
    "background.benefit_risk": _m(
        "mapped_to_v2", ["v2_n_2_3"], "获益/风险评估对应 v2 2.3 风险/获益评估。"
    ),
    # --- chapter 3 ---
    "objectives_endpoints": _m(
        "mapped_to_v2", ["v2_n_3"], "研究目的和终点对 v2 第3章（容器）。"
    ),
    "objectives_endpoints.primary": _m(
        "split", ["v2_n_3_1_1", "v2_n_3_1_2"],
        "v2 将主要目的与主要估计目标分列，估计目标五属性为新义务。",
    ),
    "objectives_endpoints.secondary": _m(
        "split", ["v2_n_3_2_1", "v2_n_3_2_2"], "次要目的与次要终点在 v2 分列。"
    ),
    "objectives_endpoints.exploratory": _m(
        "split", ["v2_n_3_4_1", "v2_n_3_4_2"], "探索性目的与探索性终点在 v2 分列。"
    ),
    # --- chapter 4 ---
    "study_design": _m(
        "mapped_to_v2", ["v2_n_4"], "研究设计对 v2 第4章试验设计（容器）。"
    ),
    "study_design.overall": _m("mapped_to_v2", ["v2_n_4_1"], "总体设计对 v2 4.1。"),
    "study_design.phase1_parts": _m("nonapplicable_phase1", [], PHASE1_RATIONALE),
    "study_design.phase1_sad": _m("nonapplicable_phase1", [], PHASE1_RATIONALE),
    "study_design.phase1_mad": _m("nonapplicable_phase1", [], PHASE1_RATIONALE),
    "study_design.phase1_food_effect": _m("nonapplicable_phase1", [], PHASE1_RATIONALE),
    "study_design.phase1_special_population": _m(
        "nonapplicable_phase1", [], PHASE1_RATIONALE
    ),
    "study_design.rationale": _m(
        "mapped_to_v2", ["v2_n_4_2"], "设计依据（容器）对应 v2 4.2 研究设计的依据。"
    ),
    "study_design.starting_dose": _m("nonapplicable_phase1", [], PHASE1_RATIONALE),
    "study_design.escalation": _m("nonapplicable_phase1", [], PHASE1_RATIONALE),
    "study_design.dose_selection": _m(
        "mapped_to_v2", ["v2_n_4_3"], "剂量选择依据（phase:2）对应 v2 4.3 剂量选择依据。"
    ),
    "study_design.confirmatory": _m(
        "merged", ["v2_n_4_2"],
        "确证性设计与假设依据（phase:3）并入 v2 研究设计的依据。",
        "partial",
        "确证性设计内容并入 4.2 的边界需语义复核。",
    ),
    "study_design.pk_pd_sampling": _m(
        "mapped_to_v2", ["v2_n_9_3"],
        "v2 未设置 PK/PD 采集点设计条件标题；相关义务候选由 6.1.2 给药方案与 "
        "9.3 群体药动学药效学评估承载。",
        "partial",
        "条件章节在 v2 无对应标题，承载位置需 Codex 语义复核。",
    ),
    "study_design.randomization": _m(
        "merged", ["v2_n_4_5"], "随机化与盲法在 v2 合并为 4.5 随机化和盲法。"
    ),
    "study_design.blinding": _m(
        "merged", ["v2_n_4_5"], "盲法与揭盲并入 v2 4.5 随机化和盲法。"
    ),
    "study_design.safety_committee": _m(
        "mapped_to_v2", ["v2_n_14_7"],
        "安全性审评/数据监查委员会由14.7安全性监督承载；9.4是疗效IRC，不得混同。",
    ),
    "study_design.study_end": _m(
        "mapped_to_v2", ["v2_n_4_4"], "研究结束与研究持续时间对应 v2 4.4 研究结束的定义。"
    ),
    "study_design.pause_stop": _m(
        "mapped_to_v2", ["v2_n_8_1"],
        "研究暂停和终止标准暂由 v2 8.1 研究干预中止/终止承载。",
        "partial",
        "暂停标准与中止/终止的边界需语义复核。",
    ),
    # --- chapter 5 ---
    "population": _m("mapped_to_v2", ["v2_n_5"], "研究人群对 v2 第5章（容器）。"),
    "population.size": _m(
        "mapped_to_v2", ["v2_n_5", "v2_n_11_1"],
        "v2 未单列计划入组人数标题，候选由第5章概述与 11.1 样本量估算共同承载。",
        "partial",
        "计划入组人数义务在 v2 无专属标题，需语义复核。",
    ),
    "population.selection": _m(
        "mapped_to_v2", ["v2_n_5"],
        "研究人群选择及依据由 v2 第5章章首内容承载。",
        "partial",
        "v2 无专属标题，承载边界需语义复核。",
    ),
    "population.inclusion": _m("mapped_to_v2", ["v2_n_5_1"], "入选标准对 v2 5.1。"),
    "population.exclusion": _m("mapped_to_v2", ["v2_n_5_2"], "排除标准对 v2 5.2。"),
    "population.screen_failure": _m(
        "mapped_to_v2", ["v2_n_5_4"], "筛选失败与重新筛选对应 v2 5.4 筛选失败。"
    ),
    "population.replacement": _m("nonapplicable_phase1", [], PHASE1_RATIONALE),
    # --- chapter 6 ---
    "intervention": _m(
        "mapped_to_v2", ["v2_n_6"], "研究治疗/干预对 v2 第6章研究干预（容器）。"
    ),
    "intervention.product": _m(
        "mapped_to_v2", ["v2_n_6_1"], "试验用药品对 v2 6.1 研究药物（容器）。"
    ),
    "intervention.product_description": _m(
        "mapped_to_v2", ["v2_n_6_1_1"], "研究药物信息对 v2 6.1.1 研究药物描述。"
    ),
    "intervention.preparation_storage": _m(
        "split", ["v2_n_6_2_1", "v2_n_6_2_2", "v2_n_6_2_3", "v2_n_6_2_4"],
        "制备/包装/标签/储存与管理在 v2 拆分为 6.2.1-6.2.4 四个标题。",
    ),
    "intervention.accountability": _m(
        "merged", ["v2_n_6_2_1"], "发放、回收与清点并入 v2 6.2.1 药物接收和清点。"
    ),
    "intervention.regimen": _m(
        "mapped_to_v2", ["v2_n_6_1_2"], "研究治疗给药对应 v2 6.1.2 研究药物给药方案。"
    ),
    "intervention.dose_modification": _m(
        "mapped_to_v2", ["v2_n_6_1_2", "v2_n_8_1"],
        "剂量调整、暂停、恢复与永久停药暂由给药方案与中止/终止承载。",
        "partial",
        "v2 无剂量调整专属标题，承载边界需语义复核。",
    ),
    "intervention.overdose_error": _m(
        "mapped_to_v2", ["v2_n_6_1_2"],
        "药物过量与给药错误管理暂由给药方案承载。",
        "partial",
        "v2 无专属标题，承载边界需语义复核。",
    ),
    "intervention.compliance": _m(
        "mapped_to_v2", ["v2_n_6_3"], "研究治疗依从性对应 v2 6.3 研究干预的依从性。"
    ),
    "intervention.concomitant": _m(
        "mapped_to_v2", ["v2_n_6_4"], "合并用药/治疗对 v2 6.4 合并治疗（容器）。"
    ),
    "intervention.concomitant_allowed": _m(
        "mapped_to_v2", ["v2_n_6_4_2"], "允许的合并用药/治疗对应 v2 6.4.2。"
    ),
    "intervention.concomitant_prohibited": _m(
        "mapped_to_v2", ["v2_n_6_4_1"], "禁止的合并用药/治疗对应 v2 6.4.1（含食物）。"
    ),
    "intervention.background": _m(
        "mapped_to_v2", ["v2_n_6_4_2"],
        "必须使用的背景治疗暂由允许使用的药物和治疗承载。",
        "partial",
        "v2 无背景治疗专属标题，需语义复核。",
    ),
    "intervention.rescue": _m("mapped_to_v2", ["v2_n_6_4_3"], "补救治疗对 v2 6.4.3。"),
    # --- chapter 7 ---
    "procedures_assessments": _m(
        "mapped_to_v2", ["v2_n_7", "v2_n_8", "v2_n_9"],
        "研究程序和评估在 v2 拆分为研究步骤、中止/退出、评估与流程三章（容器）。",
    ),
    "procedures_assessments.schedule": _m(
        "mapped_to_v2", ["v2_n_7", "v2_n_1_3"],
        "研究程序（含访视安排）由 v2 1.3 SOA 与第7章各期指引共同承载；"
        "SOA 表为模板示例，访视/时间窗须按项目设计重算。",
        "partial",
        "第7章容器无章首正文，访视义务由 SOA（表 body_child_index=265）承载，"
        "项目化时不得照抄示例访视。",
    ),
    "procedures_assessments.screening": _m(
        "mapped_to_v2", ["v2_n_7_1"], "筛选期与基线对应 v2 7.1 筛选期。"
    ),
    "procedures_assessments.treatment_followup": _m(
        "split", ["v2_n_7_2", "v2_n_7_3"], "治疗期及随访在 v2 拆分为治疗期与随访期。"
    ),
    "procedures_assessments.unscheduled": _m(
        "split", ["v2_n_7_3"],
        "计划外访视义务由 7.3 随访期正文显式承载（@492 记录要求与第10章衔接）。",
        "partial",
        "源文将计划外访视置于随访期章；若项目设计要求独立小节，由 3R.3 合同决定。",
    ),
    "procedures_assessments.withdrawal": _m(
        "split", ["v2_n_8_1", "v2_n_8_2", "v2_n_8_3"],
        "研究治疗终止、退出研究及失访处理在 v2 拆分为 8.1-8.3。",
    ),
    "procedures_assessments.efficacy": _m(
        "mapped_to_v2", ["v2_n_9_1"], "有效性评估对 v2 9.1 疗效评估。"
    ),
    "procedures_assessments.safety": _m(
        "mapped_to_v2", ["v2_n_9_2"], "安全性评估（容器）对 v2 9.2 安全性和其他评估。"
    ),
    "procedures_assessments.vital_physical": _m(
        "merged", ["v2_n_9_2"], "生命体征和体格检查并入 v2 安全性和其他评估。"
    ),
    "procedures_assessments.ecg": _m(
        "merged", ["v2_n_9_2"], "心电图检查并入 v2 安全性和其他评估。"
    ),
    "procedures_assessments.laboratory": _m(
        "merged", ["v2_n_9_2", "v2_n_16_x3"],
        "实验室检查并入安全性和其他评估，检测项目信息关联附录 3。",
        "partial",
        "实验室检查项目与附录 3 的边界需语义复核。",
    ),
    "procedures_assessments.pregnancy": _m(
        "mapped_to_v2", ["v2_n_10_6"],
        "妊娠检查和避孕问询暂对应 v2 10.6 妊娠。",
        "partial",
        "检查类义务与妊娠事件章节的边界需语义复核。",
    ),
    "procedures_assessments.pk": _m(
        "mapped_to_v2", ["v2_n_9_3"],
        "药代动力学评估暂对应 v2 9.3 群体药动学药效学评估。",
        "partial",
        "群体 PK/PD 标题与非群体评估义务的覆盖边界需语义复核。",
    ),
    "procedures_assessments.pd": _m(
        "mapped_to_v2", ["v2_n_9_3"],
        "药效动力学评估暂对应 v2 9.3 群体药动学药效学评估。",
        "partial",
        "同上，覆盖边界需语义复核。",
    ),
    "procedures_assessments.immunogenicity": _m(
        "mapped_to_v2", ["v2_n_9_2"],
        "v2 未设免疫原性评估标题；相关义务候选并入 9.2 安全性和其他评估。",
        "partial",
        "条件章节在 v2 无对应标题，承载位置需语义复核。",
    ),
    "procedures_assessments.biomarker": _m(
        "split", ["v2_n_9_1", "v2_n_9_2"],
        "v2 未设生物标志物评估标题；相关义务候选并入 9.1 疗效评估或 9.2。",
        "partial",
        "条件章节在 v2 无对应标题，承载位置需语义复核。",
    ),
    "procedures_assessments.specimen": _m(
        "mapped_to_v2", ["v2_n_9_2"],
        "样本采集/制备/处理/存储/运输义务由 9.2 正文显式承载（@574-575，含 MOP 细化）。",
        "partial",
        "12.7 储备样本和数据的未来使用（@830-836）是另一项 v2 新义务；"
        "未来使用同意不得与现行样本处理义务混同。",
    ),
    # --- chapter 8 ---
    "safety": _m("mapped_to_v2", ["v2_n_10"], "安全性评价对 v2 第10章（容器）。"),
    "safety.general": _m(
        "mapped_to_v2", ["v2_n_10"],
        "总则由 v2 第10章章首内容承载。",
        "partial",
        "v2 无总则标题，承载边界需语义复核。",
    ),
    "safety.definitions": _m(
        "mapped_to_v2", ["v2_n_10"],
        "定义（容器）由 v2 第10章各定义标题承载。",
        "partial",
        "v1 定义容器在 v2 的对应边界需语义复核。",
    ),
    "safety.ae": _m(
        "mapped_to_v2", ["v2_n_10_1"], "不良事件对 v2 10.1 不良事件（含子标题）。"
    ),
    "safety.sae": _m(
        "mapped_to_v2", ["v2_n_10_2"], "严重不良事件对 v2 10.2（含定义/报告/随访）。"
    ),
    "safety.susar": _m(
        "mapped_to_v2", ["v2_n_10_3"], "SUSAR 对 v2 10.3 可疑非预期严重不良反应。"
    ),
    "safety.product_risks": _m(
        "mapped_to_v2", ["v2_n_2_3"],
        "研究药物相关风险移至 v2 2.3 风险/获益评估承载。",
        "partial",
        "章节移动后的内容边界需语义复核。",
    ),
    "safety.collection": _m(
        "split", ["v2_n_10_1_4", "v2_n_10_1_5"],
        "采集与记录在 v2 拆分为收集与记录两个标题。"
    ),
    "safety.assessment": _m(
        "split", ["v2_n_10_1_2", "v2_n_10_1_3"],
        "评估在 v2 拆分为严重程度与相关性判断。"
    ),
    "safety.reporting": _m(
        "mapped_to_v2", ["v2_n_10_2_2", "v2_n_10_3_2"],
        "报告义务由 SAE 报告与 SUSAR 报告共同承载。",
        "partial",
        "一般报告义务与两类快速报告的边界需语义复核。",
    ),
    "safety.followup": _m(
        "mapped_to_v2", ["v2_n_10_1_6"], "不良事件的随访对 v2 10.1.6。"
    ),
    "safety.aesi": _m(
        "mapped_to_v2", ["v2_n_10_5"], "特别关注的不良事件对 v2 10.5 特殊关注不良事件。"
    ),
    "safety.pregnancy": _m(
        "mapped_to_v2", ["v2_n_10_6"], "妊娠事件的报告与随访对 v2 10.6 妊娠。"
    ),
    # --- chapter 9 ---
    "statistics": _m(
        "mapped_to_v2", ["v2_n_11"], "统计分析对 v2 第11章统计考量（容器）。"
    ),
    "statistics.sample_size": _m(
        "mapped_to_v2", ["v2_n_11_1"], "样本量对 v2 11.1 样本量估算。"
    ),
    "statistics.analysis_sets": _m(
        "mapped_to_v2", ["v2_n_11_2"], "统计分析数据集对 v2 11.2 分析集。"
    ),
    "statistics.general": _m(
        "mapped_to_v2", ["v2_n_11_3"], "统计分析一般原则对 v2 11.3 一般分析考虑。"
    ),
    "statistics.efficacy": _m(
        "split", ["v2_n_11_4_3", "v2_n_11_4_4", "v2_n_11_4_6"],
        "有效性数据分析在 v2 拆为主要估计目标、次要终点、探索性终点分析。",
    ),
    "statistics.safety": _m(
        "mapped_to_v2", ["v2_n_11_4_5"], "安全性数据分析对 v2 11.4.5。"
    ),
    "statistics.pk": _m(
        "mapped_to_v2", ["v2_n_11_4"],
        "v2 未设 PK 数据分析条件标题；相关义务候选并入 11.4 统计分析。",
        "partial",
        "条件章节在 v2 无对应标题，承载位置需语义复核。",
    ),
    "statistics.pd": _m(
        "mapped_to_v2", ["v2_n_11_4"],
        "v2 未设 PD 数据分析条件标题；相关义务候选并入 11.4 统计分析。",
        "partial",
        "条件章节在 v2 无对应标题，承载位置需语义复核。",
    ),
    "statistics.er": _m(
        "mapped_to_v2", ["v2_n_11_4"],
        "v2 未设暴露-效应分析条件标题；相关义务候选并入 11.4 统计分析。",
        "partial",
        "条件章节在 v2 无对应标题，承载位置需语义复核。",
    ),
    "statistics.interim": _m(
        "mapped_to_v2", ["v2_n_11_4_9"], "期中分析对 v2 11.4.9。"
    ),
    "statistics.multiplicity": _m(
        "mapped_to_v2", ["v2_n_11_4_8"], "多重性控制对 v2 11.4.8 多重性问题考量。"
    ),
    "statistics.subgroup": _m(
        "mapped_to_v2", ["v2_n_11_4_7"], "亚组及其他分析对 v2 11.4.7 亚组分析。",
        "partial",
        "其他分析义务与亚组分析的边界需语义复核。",
    ),
    # --- chapter 10 ---
    "data_management": _m(
        "mapped_to_v2", ["v2_n_12"], "数据采集与管理对 v2 第12章（容器）。"
    ),
    "data_management.crf": _m(
        "mapped_to_v2", ["v2_n_12_2"],
        "病例报告表暂对应 v2 12.2 数据采集与方式。",
        "partial",
        "CRF 义务与数据采集方式的边界需语义复核。",
    ),
    "data_management.source": _m(
        "mapped_to_v2", ["v2_n_12_1", "v2_n_12_2"],
        "源文件/源数据要求由 12.2 承载（@816）；12.1 正文为数据管理计划（DMP）。",
        "partial",
        "数据源定义义务未由 12.1 正文承载（@813 为 DMP），保留待 3R.3。",
    ),
    "data_management.quality": _m(
        "split", ["v2_n_12_3", "v2_n_12_4", "v2_n_12_6"],
        "数据质量保证在 v2 拆分为清理质疑、修改审核与数据治理。",
    ),
    "data_management.retention": _m(
        "mapped_to_v2", ["v2_n_12_8"], "资料保存与数据保护对 v2 12.8 研究记录的保存。"
    ),
    "data_management.publication": _m(
        "mapped_to_v2", ["v2_n_12_9"],
        "数据发布和研究发表策略对 v2 12.9 研究发表和数据共享政策。"
    ),
    # --- chapter 11 ---
    "ethics": _m("mapped_to_v2", ["v2_n_13"], "伦理考虑对 v2 第13章（容器）。"),
    "ethics.compliance": _m(
        "mapped_to_v2", ["v2_n_13_1"], "遵守法律法规对 v2 13.1 伦理规范。"
    ),
    "ethics.consent": _m("mapped_to_v2", ["v2_n_13_2"], "知情同意对 v2 13.2。"),
    "ethics.committee": _m(
        "mapped_to_v2", ["v2_n_13_1"],
        "伦理委员会暂并入 v2 13.1 伦理规范。",
        "partial",
        "伦理委员会义务在 v2 无专属标题，需语义复核。",
    ),
    "ethics.privacy": _m(
        "mapped_to_v2", ["v2_n_13_3"], "保密与隐私对 v2 13.3 保密和隐私。"
    ),
    "ethics.insurance": _m(
        "mapped_to_v2", ["v2_n_13_4"],
        "保险与赔偿对应13.4补偿、赔偿与保险；章节义务必需，具体安排由项目事实确定。",
    ),
    # --- chapter 12 ---
    "study_management": _m(
        "mapped_to_v2", ["v2_n_14"], "研究文件、监查和管理对 v2 第14章（容器）。"
    ),
    "study_management.compliance": _m(
        "mapped_to_v2", ["v2_n_14"],
        "研究方案的依从由 v2 第14章质量保证与质量控制承载。",
        "partial",
        "v2 无方案依从专属标题，承载边界需语义复核。",
    ),
    "study_management.monitoring": _m(
        "mapped_to_v2", ["v2_n_14_3"], "监查对应 v2 14.3 监查员职责。"
    ),
    "study_management.audit_inspection": _m(
        "mapped_to_v2", ["v2_n_14_5"], "稽查和核查对 v2 14.5 稽查和视察。"
    ),
    "study_management.deviation": _m(
        "mapped_to_v2", ["v2_n_14_6"], "方案偏离对 v2 14.6。"
    ),
    "study_management.roles": _m(
        "split", ["v2_n_14_2", "v2_n_14_3", "v2_n_14_4"],
        "关键角色和研究管理在 v2 分布于申办者要求、监查员职责、研究者要求三个节点联合承载。",
    ),
    "study_management.closeout": _m(
        "mapped_to_v2", ["v2_n_14"],
        "研究和研究中心的关闭暂由第14章承载。",
        "partial",
        "v2 无关闭专属标题，承载边界需语义复核。",
    ),
    "study_management.quality": _m(
        "mapped_to_v2", ["v2_n_14_1", "v2_n_14"],
        "各方质控措施义务由第14章章首承载（@883）；14.1 QbD/CtQ（@885）为 v2 "
        "新增互补内容，不替代质控义务。",
        "partial",
        "质控体系与 QbD 新节点的分工边界需语义复核。",
    ),
    # --- chapters 13/14 ---
    "references": _m("mapped_to_v2", ["v2_n_15"], "参考文献对 v2 第15章。"),
    "appendices": _m("mapped_to_v2", ["v2_n_16"], "附录（容器）对 v2 第16章附录。"),
    "appendices.contraception": _m(
        "mapped_to_v2", ["v2_n_5", "v2_n_10_6"],
        "避孕义务由第5章入排指引（@378）与 10.6 避孕期限要求（@749）共同承载；"
        "v2 无独立避孕附录，具体方法由项目事实确定。",
        "partial",
        "避孕方法明细（药物/屏障法清单）未由源文承载，保留待 3R.3。",
    ),
    "appendices.instruments": _m(
        "split", ["v2_n_16_x1", "v2_n_16_x2"],
        "研究量表和评价工具对应 v2 附录 1（ECOG）与附录 2（NYHA）。",
        "partial",
        "v2 附录为示例性量表，项目量表义务的覆盖需语义复核。",
    ),
    "appendices.lab_panels": _m(
        "mapped_to_v2", ["v2_n_16_x3"],
        "实验室检查项目暂对应 v2 附录 3 中心实验室信息和样本销毁公司信息。",
        "partial",
        "检测项目清单与中心实验室信息的边界需语义复核。",
    ),
    "appendices.safety_reporting": _m(
        "split", ["v2_n_10_2_2", "v2_n_10_3_2"],
        "v2 未承载安全信息报告途径附录；报告义务由 10.2.2/10.3.2 报告标题承载。",
        "partial",
        "条件附录在 v2 无对应标题，承载位置需语义复核。",
    ),
    "appendices.project_specific": _m(
        "mapped_to_v2", ["v2_n_16"],
        "项目特异附录义务在第16章附录容器内保留，项目事实决定重复项；"
        "源示例附录不限制项目附录的种类和数量。",
        "partial",
        "可重复附录机制在 v2 无对应结构，需显式复核。",
    ),
}


def _r(v2_node_id, disposition, from_v1, rationale):
    return {
        "v2_node_id": v2_node_id,
        "disposition": disposition,
        "from_v1_semantic_ids": from_v1,
        "rationale": rationale,
    }


REVERSE_MAPPING: dict[str, dict] = {
    "v2_n_front_1": _r("v2_n_front_1", "from_v1", ["document_control.version_history"], "v1 版本更新记录对应本标题。"),
    "v2_n_front_2": _r("v2_n_front_2", "from_v1", ["document_control.signatures"], "v1 签字页拆分出的主要研究者签字页。"),
    "v2_n_front_3": _r("v2_n_front_3", "from_v1", ["document_control.signatures"], "v1 签字页拆分出的申办者签字页。"),
    "v2_n_front_4": _r("v2_n_front_4", "new_in_v2", [], "v1 树无临床试验相关单位联系方式节点；承载位置差异需 Codex 复核。"),
    "v2_n_front_5": _r("v2_n_front_5", "from_v1", ["document_control.glossary"], "v1 缩略语与术语定义对应本节点（Normal 样式大纲节点）。"),
    "v2_n_front_6": _r("v2_n_front_6", "from_v1", ["document_control.indexes"], "v1 目录、表目录、图目录拆分出的目录。"),
    "v2_n_front_7": _r("v2_n_front_7", "from_v1", ["document_control.indexes"], "v1 索引容器拆分出的表目录。"),
    "v2_n_front_8": _r("v2_n_front_8", "from_v1", ["document_control.indexes"], "v1 索引容器拆分出的图目录。"),
    "v2_n_1_1": _r("v2_n_1_1", "from_v1", ["synopsis.summary"], "v1 方案摘要对应 1.1 概要。"),
    "v2_n_1_2": _r("v2_n_1_2", "from_v1", ["synopsis.schema"], "v1 研究示意图更名为研究流程图。"),
    "v2_n_1_3": _r("v2_n_1_3", "from_v1", ["synopsis.schedule", "procedures_assessments.schedule"], "研究流程表及访视程序安排共同对应SOA。"),
    "v2_n_2_1": _r("v2_n_2_1", "from_v1", ["background.rationale"], "v1 理论基础对应研究理论依据。"),
    "v2_n_2_2_1": _r("v2_n_2_2_1", "from_v1", ["background.product", "background.mechanism"], "研究药物承接 v1 药物简介与作用机制拆分。"),
    "v2_n_2_2_2_1": _r("v2_n_2_2_2_1", "new_in_v2", [], "药效学研究在 v1 无对应标题，v1 该内容为无标题正文。"),
    "v2_n_2_2_3": _r("v2_n_2_2_3", "mixed", ["background.mechanism", "background.product.clinical"], "同类靶点/机制数据由@298承载，本药早期临床结果由@299承载；本药证据与同类药物证据是不同证据源，不得混同。"),
    "v2_n_2_3": _r("v2_n_2_3", "from_v1", ["background.benefit_risk", "safety.product_risks"], "风险/获益评估承接获益风险评估与药物相关风险迁移。"),
    "v2_n_3_1_1": _r("v2_n_3_1_1", "from_v1", ["objectives_endpoints.primary"], "主要目的承接 v1 主要目的和主要终点拆分。"),
    "v2_n_3_1_2_1": _r("v2_n_3_1_2_1", "new_in_v2", [], "估计目标属性（目标人群）为 v2 新义务。"),
    "v2_n_3_1_2_2": _r("v2_n_3_1_2_2", "new_in_v2", [], "估计目标属性（研究变量）为 v2 新义务。"),
    "v2_n_3_1_2_3": _r("v2_n_3_1_2_3", "new_in_v2", [], "估计目标属性（治疗效应）为 v2 新义务。"),
    "v2_n_3_1_2_4": _r("v2_n_3_1_2_4", "new_in_v2", [], "估计目标属性（伴发事件，含表 1）为 v2 新义务。"),
    "v2_n_3_2_1": _r("v2_n_3_2_1", "from_v1", ["objectives_endpoints.secondary"], "次要目的承接 v1 次要拆分。"),
    "v2_n_3_2_2": _r("v2_n_3_2_2", "from_v1", ["objectives_endpoints.secondary"], "次要终点承接 v1 次要拆分。"),
    "v2_n_3_3_1": _r("v2_n_3_3_1", "new_in_v2", [], "安全性目的在 v1 无对应节点（v1 仅主要/次要/探索性三类）。"),
    "v2_n_3_3_2": _r("v2_n_3_3_2", "new_in_v2", [], "安全性终点在 v1 无对应节点。"),
    "v2_n_3_4_1": _r("v2_n_3_4_1", "from_v1", ["objectives_endpoints.exploratory"], "探索性目的承接 v1 探索性拆分。"),
    "v2_n_3_4_2": _r("v2_n_3_4_2", "from_v1", ["objectives_endpoints.exploratory"], "探索性终点承接 v1 探索性拆分。"),
    "v2_n_4_1": _r("v2_n_4_1", "from_v1", ["study_design.overall"], "总体设计一一对应。"),
    "v2_n_4_2": _r("v2_n_4_2", "mixed", ["study_design.rationale", "study_design.confirmatory"], "研究设计的依据承接设计依据容器与确证性设计依据并入。"),
    "v2_n_4_3": _r("v2_n_4_3", "from_v1", ["study_design.dose_selection"], "剂量选择依据承接 v1 phase:2 同名章节。"),
    "v2_n_4_4": _r("v2_n_4_4", "from_v1", ["study_design.study_end"], "研究结束的定义承接 v1 研究结束与研究持续时间。"),
    "v2_n_4_5": _r("v2_n_4_5", "from_v1", ["study_design.randomization", "study_design.blinding"], "随机化和盲法合并 v1 随机化与盲法两节。"),
    "v2_n_5_1": _r("v2_n_5_1", "from_v1", ["population.inclusion"], "入选标准一一对应。"),
    "v2_n_5_2": _r("v2_n_5_2", "from_v1", ["population.exclusion"], "排除标准一一对应。"),
    "v2_n_5_3": _r("v2_n_5_3", "new_in_v2", [], "生活方式注意事项在 v1 无对应节点。"),
    "v2_n_5_4": _r("v2_n_5_4", "from_v1", ["population.screen_failure"], "筛选失败承接 v1 筛选失败与重新筛选。"),
    "v2_n_5_5": _r("v2_n_5_5", "new_in_v2", [], "试验参与者招募与保留为 v2 新增义务（计划 micro-step 明示）。"),
    "v2_n_6_1_1": _r("v2_n_6_1_1", "from_v1", ["intervention.product_description"], "研究药物描述承接 v1 研究药物信息。"),
    "v2_n_6_1_2": _r("v2_n_6_1_2", "mixed", ["intervention.regimen", "intervention.dose_modification", "intervention.overdose_error"], "给药方案承接给药义务并暂承载剂量调整与过量错误候选。"),
    "v2_n_6_2_1": _r("v2_n_6_2_1", "from_v1", ["intervention.accountability", "intervention.preparation_storage"], "药物接收和清点承接发放回收清点与制备拆分。"),
    "v2_n_6_2_2": _r("v2_n_6_2_2", "from_v1", ["intervention.preparation_storage"], "剂型、外观、包装和标签承接制备拆分。"),
    "v2_n_6_2_3": _r("v2_n_6_2_3", "from_v1", ["intervention.preparation_storage"], "产品储存和稳定性承接制备拆分。"),
    "v2_n_6_2_4": _r("v2_n_6_2_4", "from_v1", ["intervention.preparation_storage"], "准备承接制备拆分。"),
    "v2_n_6_3": _r("v2_n_6_3", "from_v1", ["intervention.compliance"], "研究干预的依从性承接 v1 治疗依从性。"),
    "v2_n_6_4_1": _r("v2_n_6_4_1", "from_v1", ["intervention.concomitant_prohibited"], "禁止使用的食物、药物和治疗承接禁止合并用药。"),
    "v2_n_6_4_2": _r("v2_n_6_4_2", "mixed", ["intervention.concomitant_allowed", "intervention.background"], "允许使用的药物和治疗承接允许合并用药并暂承载背景治疗。"),
    "v2_n_6_4_3": _r("v2_n_6_4_3", "from_v1", ["intervention.rescue"], "补救治疗一一对应。"),
    "v2_n_7_1": _r("v2_n_7_1", "from_v1", ["procedures_assessments.screening"], "筛选期承接筛选期与基线。"),
    "v2_n_7_2": _r("v2_n_7_2", "from_v1", ["procedures_assessments.treatment_followup"], "治疗期承接治疗期及随访拆分。"),
    "v2_n_7_3": _r("v2_n_7_3", "from_v1", ["procedures_assessments.treatment_followup", "procedures_assessments.unscheduled"], "随访期承接治疗期及随访拆分；计划外访视义务由@492显式承载。"),
    "v2_n_8_1": _r("v2_n_8_1", "mixed", ["procedures_assessments.withdrawal", "study_design.pause_stop", "intervention.dose_modification"], "研究干预中止/终止承接退出拆分并暂承载暂停与剂量调整候选。"),
    "v2_n_8_2": _r("v2_n_8_2", "from_v1", ["procedures_assessments.withdrawal"], "试验参与者中止/退出研究承接退出拆分。"),
    "v2_n_8_3": _r("v2_n_8_3", "from_v1", ["procedures_assessments.withdrawal"], "失访承接退出拆分。"),
    "v2_n_9_1": _r("v2_n_9_1", "mixed", ["procedures_assessments.efficacy", "procedures_assessments.biomarker"], "疗效评估及相关生物标志物义务；具体检测由项目决定。"),
    "v2_n_9_2": _r("v2_n_9_2", "mixed", ["procedures_assessments.safety", "procedures_assessments.vital_physical", "procedures_assessments.ecg", "procedures_assessments.laboratory", "procedures_assessments.specimen", "procedures_assessments.immunogenicity", "procedures_assessments.biomarker"], "评估、样本处理及保留的免疫原性/生物标志物义务；源承载程度见正向source_resolution。"),
    "v2_n_9_3": _r("v2_n_9_3", "mixed", ["procedures_assessments.pk", "procedures_assessments.pd", "study_design.pk_pd_sampling"], "PK/PD评估及采样设计义务，具体设计合同仍需项目化。"),
    "v2_n_9_4": _r("v2_n_9_4", "new_in_v2", [], "疗效独立评审委员会；不承接安全性SRC/DMC义务。"),
    "v2_n_10_1_1": _r("v2_n_10_1_1", "from_v1", ["safety.ae"], "不良事件的定义承接 v1 不良事件定义义务。"),
    "v2_n_10_1_2": _r("v2_n_10_1_2", "from_v1", ["safety.assessment"], "严重程度承接 v1 评估拆分。"),
    "v2_n_10_1_3": _r("v2_n_10_1_3", "from_v1", ["safety.assessment"], "相关性判断承接 v1 评估拆分。"),
    "v2_n_10_1_4": _r("v2_n_10_1_4", "from_v1", ["safety.collection"], "收集承接 v1 采集记录拆分。"),
    "v2_n_10_1_5": _r("v2_n_10_1_5", "from_v1", ["safety.collection"], "记录承接 v1 采集记录拆分。"),
    "v2_n_10_1_6": _r("v2_n_10_1_6", "from_v1", ["safety.followup"], "随访承接 v1 不良事件随访。"),
    "v2_n_10_2_1": _r("v2_n_10_2_1", "from_v1", ["safety.sae"], "SAE 定义承接 v1 SAE 义务。"),
    "v2_n_10_2_2": _r("v2_n_10_2_2", "from_v1", ["safety.sae", "safety.reporting", "appendices.safety_reporting"], "SAE报告及报告途径义务。"),
    "v2_n_10_2_3": _r("v2_n_10_2_3", "from_v1", ["safety.sae"], "SAE 随访承接 v1 SAE 义务。"),
    "v2_n_10_3_1": _r("v2_n_10_3_1", "from_v1", ["safety.susar"], "SUSAR 定义承接 v1 SUSAR 义务。"),
    "v2_n_10_3_2": _r("v2_n_10_3_2", "from_v1", ["safety.susar", "safety.reporting", "appendices.safety_reporting"], "SUSAR报告及报告途径义务。"),
    "v2_n_10_3_3": _r("v2_n_10_3_3", "from_v1", ["safety.susar"], "快速报告的随访承接 v1 SUSAR 义务。"),
    "v2_n_10_4": _r("v2_n_10_4", "new_in_v2", [], "其他潜在的严重安全性风险信息的报告在 v1 无对应节点。"),
    "v2_n_10_5": _r("v2_n_10_5", "from_v1", ["safety.aesi"], "特殊关注不良事件承接 AESI 义务。"),
    "v2_n_10_6": _r("v2_n_10_6", "mixed", ["safety.pregnancy", "procedures_assessments.pregnancy", "appendices.contraception"], "妊娠承接妊娠事件报告随访（@750-751）与避孕期限（@749）；妊娠检测安排待3R.3，不得与事件报告混同。"),
    "v2_n_11_1": _r("v2_n_11_1", "mixed", ["statistics.sample_size", "population.size"], "样本量估算承接统计样本量并暂承载计划入组人数候选。"),
    "v2_n_11_2": _r("v2_n_11_2", "from_v1", ["statistics.analysis_sets"], "分析集承接统计分析数据集。"),
    "v2_n_11_3": _r("v2_n_11_3", "from_v1", ["statistics.general"], "一般分析考虑承接统计分析一般原则。"),
    "v2_n_11_4_1": _r("v2_n_11_4_1", "new_in_v2", [], "人口学及基线情况汇总在 v1 无专属节点。"),
    "v2_n_11_4_2": _r("v2_n_11_4_2", "new_in_v2", [], "依从性和合并用药分析在 v1 无专属统计节点。"),
    "v2_n_11_4_3_1": _r("v2_n_11_4_3_1", "from_v1", ["statistics.efficacy"], "主要分析承接有效性分析拆分。"),
    "v2_n_11_4_3_2": _r("v2_n_11_4_3_2", "new_in_v2", [], "敏感性分析为 v2 新义务（同一估计目标的敏感性分析）。"),
    "v2_n_11_4_4": _r("v2_n_11_4_4", "from_v1", ["statistics.efficacy"], "次要终点分析承接有效性分析拆分。"),
    "v2_n_11_4_5": _r("v2_n_11_4_5", "from_v1", ["statistics.safety"], "安全性分析一一对应。"),
    "v2_n_11_4_6": _r("v2_n_11_4_6", "from_v1", ["statistics.efficacy"], "探索性终点分析承接有效性分析拆分。"),
    "v2_n_11_4_7": _r("v2_n_11_4_7", "from_v1", ["statistics.subgroup"], "亚组分析承接亚组及其他分析。"),
    "v2_n_11_4_8": _r("v2_n_11_4_8", "from_v1", ["statistics.multiplicity"], "多重性问题考量承接多重性控制。"),
    "v2_n_11_4_9": _r("v2_n_11_4_9", "from_v1", ["statistics.interim"], "期中分析一一对应。"),
    "v2_n_12_1": _r("v2_n_12_1", "mixed", ["data_management.source"], "数据收集和管理职责暂承载数据源定义候选。"),
    "v2_n_12_2": _r("v2_n_12_2", "mixed", ["data_management.crf", "data_management.source"], "数据采集、病例报告表及数据来源义务。"),
    "v2_n_12_3": _r("v2_n_12_3", "from_v1", ["data_management.quality"], "数据清理与质疑解决承接数据质量拆分。"),
    "v2_n_12_4": _r("v2_n_12_4", "from_v1", ["data_management.quality"], "数据的修改和审核承接数据质量拆分。"),
    "v2_n_12_5": _r("v2_n_12_5", "new_in_v2", [], "数据锁定及导出在 v1 无对应节点。"),
    "v2_n_12_6": _r("v2_n_12_6", "mixed", ["data_management.quality"], "数据治理与计算机化系统承接数据质量拆分并为计划新增义务。"),
    "v2_n_12_7": _r("v2_n_12_7", "new_in_v2", [], "储备样本和数据的未来使用为 v2 新义务（@830-836 未来使用同意/资源库）；现行样本采集/处置/保存由 9.2 承接，两者不得混同。"),
    "v2_n_12_8": _r("v2_n_12_8", "from_v1", ["data_management.retention"], "研究记录的保存承接资料保存与数据保护。"),
    "v2_n_12_9": _r("v2_n_12_9", "from_v1", ["data_management.publication"], "研究发表和数据共享政策承接数据发布和研究发表策略。"),
    "v2_n_13_1": _r("v2_n_13_1", "mixed", ["ethics.compliance", "ethics.committee"], "伦理规范承接法律法规并暂承载伦理委员会候选。"),
    "v2_n_13_2": _r("v2_n_13_2", "from_v1", ["ethics.consent"], "知情同意一一对应。"),
    "v2_n_13_3": _r("v2_n_13_3", "from_v1", ["ethics.privacy"], "保密和隐私承接保密与隐私。"),
    "v2_n_13_4": _r("v2_n_13_4", "from_v1", ["ethics.insurance"], "补偿、赔偿与保险承接保险与赔偿，缺失项目事实不豁免章节。"),
    "v2_n_14_1": _r("v2_n_14_1", "mixed", ["study_management.quality"], "质量源于设计与风险管理为计划新增并暂承接质量控制候选。"),
    "v2_n_14_2": _r("v2_n_14_2", "from_v1", ["study_management.roles"], "对申办者的要求承接关键角色管理拆分。"),
    "v2_n_14_3": _r("v2_n_14_3", "from_v1", ["study_management.roles", "study_management.monitoring"], "监查员职责承接关键角色拆分与监查义务。"),
    "v2_n_14_4": _r("v2_n_14_4", "from_v1", ["study_management.roles"], "对研究者的要求承接关键角色管理拆分。"),
    "v2_n_14_5": _r("v2_n_14_5", "from_v1", ["study_management.audit_inspection"], "稽查和视察承接稽查和核查。"),
    "v2_n_14_6": _r("v2_n_14_6", "from_v1", ["study_management.deviation"], "方案偏离一一对应。"),
    "v2_n_14_7": _r("v2_n_14_7", "from_v1", ["study_design.safety_committee"], "安全性监督承接安全性审评及数据监查委员会义务，与疗效IRC分离。"),
    "v2_n_15": _r("v2_n_15", "from_v1", ["references"], "参考文献一一对应。"),
    "v2_n_16": _r("v2_n_16", "from_v1", ["appendices", "appendices.project_specific"], "附录容器承接附录章及可重复项目附录义务。"),
    "v2_n_16_x1": _r("v2_n_16_x1", "mixed", ["appendices.instruments"], "附录 1（ECOG）承接量表附录拆分，源文档标注为附录示例。"),
    "v2_n_16_x2": _r("v2_n_16_x2", "mixed", ["appendices.instruments"], "附录 2（NYHA）承接量表附录拆分，源文档标注为附录示例。"),
    "v2_n_16_x3": _r("v2_n_16_x3", "mixed", ["appendices.lab_panels", "procedures_assessments.laboratory"], "附录3实验室信息框架及保留的检测清单义务；不能以机构信息代替项目检测项。"),
}


# Content-based resolution of partial forward mappings. Locators are zero-based
# body-child indexes in word/document.xml (paragraphs and tables in one
# sequence), computed by extract_docx_structure; status vocabulary:
#   source_carried / partially_carried / awaiting_3r3_contract / unresolved.
# "awaiting_3r3_contract" = the v2 source does NOT carry the legacy obligation;
# it is deliberately preserved and awaits a 3R.3 leaf contract. No entry may
# claim source content that the source does not contain.
def _sl(v2_node_id, status, evidence, note):
    return {
        "v2_node_id": v2_node_id,
        "status": status,
        "evidence_body_child_indexes": evidence,
        "note": note,
    }


def _sr(status, targets, note=""):
    return {"status": status, "targets": targets, "note": note}


SOURCE_RESOLUTIONS: dict[str, dict] = {
    "document_control.confidentiality": _sr(
        "source_carried",
        [_sl(FRONT_BLOCK_ID, "source_carried", [41, 42],
             "保密声明以模板示例承载（@41 示例标记、@42 声明正文）；定稿时按项目信息替换。")],
    ),
    "background.disease": _sr(
        "source_carried",
        [_sl("v2_n_2_2", "source_carried", [280, 281],
             "章首义务清单含临床/流行病学/公共卫生背景（@280）与目标适应症流行病学、"
             "SOC 及未满足临床需求（@281）；为编写指示，项目事实待 3R.3。")],
    ),
    "background.mechanism": _sr(
        "partially_carried",
        [
            _sl("v2_n_2_2_3", "source_carried", [298],
                "同类靶点/作用机制药物的疗效安全性数据总结由 @298 承载（如适用）。"),
            _sl("v2_n_2_2_1", "awaiting_3r3_contract", [284],
                "本药作用机制未在 2.2.1 正文出现；@284 仅列研发代号/化学名/结构式/"
                "理化性质等基本信息。机制义务保留待 3R.3。"),
        ],
    ),
    "background.product.nonclinical": _sr(
        "source_carried",
        [_sl("v2_n_2_2_2", "source_carried", [286, 288, 289, 290, 291, 292, 293, 294],
             "临床前概述标题及其子结构承载非临床义务：@286 概述引言；@288-294 为"
             "药效学研究子标题下未标题的毒理学/药代/一般药理段落（见 "
             "unheaded_preclinical_content finding）。")],
    ),
    "background.product.clinical": _sr(
        "source_carried",
        [_sl("v2_n_2_2_3", "source_carried", [298, 299],
             "本药早期临床研究结果由 @299 显式承载（如试验药物已完成早期临床研究…）；"
             "@298 承载同类药物数据。本药证据与同类药物证据是不同证据源，"
             "投影与合同不得混同。")],
    ),
    "study_design.confirmatory": _sr(
        "partially_carried",
        [_sl("v2_n_4_2", "source_carried", [355],
             "对照类型与设计选择理由（安慰剂/活性对照/非劣效等）由 @355 承载。")],
        "假设与假设依据未在 4.2 正文显式出现；该切片保留待 3R.3。",
    ),
    "study_design.pk_pd_sampling": _sr(
        "partially_carried",
        [_sl("v2_n_9_3", "source_carried", [584, 585],
             "PopPK/PKPD/E-R 数据采集流程说明由 @585 承载（标题可按分析内容修改）；"
             "@584 为如适用否则注明不适用的条件指示。")],
        "采集点设计依据作为设计章视角未在源文出现；设计切片保留待 3R.3。",
    ),
    "study_design.pause_stop": _sr(
        "source_carried",
        [_sl("v2_n_8_1", "source_carried", [500, 502, 504, 505, 506, 507, 508, 509, 510, 511],
             "研究终止/暂停原因与程序由 @500-510 显式承载；@511 为源文自身对"
             "干预中止与研究中止的区分，个体停治/个体退出/整研究终止须在 3R.3 "
             "分别立义。")],
    ),
    "population.size": _sr(
        "partially_carried",
        [
            _sl("v2_n_11_1", "source_carried", [762, 763, 764, 765, 766, 767, 768, 769, 770, 771, 772],
                "样本量确定依据（含脱落考虑）由 11.1 正文承载，计划入组人数为其输出。"),
            _sl("v2_n_5", "awaiting_3r3_contract", [372, 373],
                "第5章章首为人群描述与招募指引（@372-373），未设计划入组人数栏位。"),
        ],
    ),
    "population.selection": _sr(
        "source_carried",
        [_sl("v2_n_5", "source_carried", [372, 373, 374, 375, 376, 377, 378, 379],
             "人群选择依据与入排制定准则由章首 @372-379 承载。")],
    ),
    "intervention.dose_modification": _sr(
        "source_carried",
        [
            _sl("v2_n_6_1_2", "source_carried", [430, 432],
                "剂量调整情形与递减计划由 @430 承载；@432 为剂量调整与漏服处理示例"
                "（示例值不得成为项目默认）。"),
            _sl("v2_n_8_1", "source_carried", [504, 505, 506, 507, 508, 509, 511],
                "暂停/终止原因与干预中止不等于研究中止的区分由 8.1 承载。"),
        ],
    ),
    "intervention.overdose_error": _sr(
        "awaiting_3r3_contract",
        [_sl("v2_n_6_1_2", "awaiting_3r3_contract", [],
             "源文 6.1.2 正文无药物过量/给药错误内容（全文 0 处匹配）；义务保留待 "
             "3R.3，不得宣称源文已承载。")],
    ),
    "intervention.background": _sr(
        "awaiting_3r3_contract",
        [_sl("v2_n_6_4_2", "awaiting_3r3_contract", [479, 480],
             "6.4.2 仅含允许用药示例（@480）与如适用指示（@479）；必须使用的背景治疗"
             "内容未由源文承载，义务保留待 3R.3。")],
    ),
    "procedures_assessments.schedule": _sr(
        "source_carried",
        [
            _sl("v2_n_7", "awaiting_3r3_contract", [],
                "第7章容器无章首正文。"),
            _sl("v2_n_1_3", "source_carried", [260, 261, 262, 263, 264],
                "访视/程序安排由 1.3 SOA 承载（SOA 表 body_child_index=265）；"
                "表内访视/时间窗为模板示例（含疾病特异量表），项目化须按确认设计重算。"),
        ],
    ),
    "procedures_assessments.unscheduled": _sr(
        "source_carried",
        [_sl("v2_n_7_3", "source_carried", [492],
             "计划外访视记录要求与第10章安全性衔接由 @492 显式承载。")],
    ),
    "procedures_assessments.laboratory": _sr(
        "partially_carried",
        [
            _sl("v2_n_9_2", "source_carried", [574, 575],
                "实验室评估与特殊化验义务由 @574-575 承载（含资质/室间质评要求）。"),
            _sl("v2_n_16_x3", "source_carried", [982, 983, 984, 985, 987, 988, 989, 990, 992, 993, 994, 995],
                "附录 3 承载中心实验室与样本销毁机构信息框架（示例占位 @982-995）。"),
        ],
        "项目检测项目清单本身为项目事实，源文仅承载机构信息框架与检测义务指引。",
    ),
    "procedures_assessments.pregnancy": _sr(
        "partially_carried",
        [
            _sl("v2_n_10_6", "source_carried", [749, 750, 751],
                "避孕要求与期限由 @749 承载；妊娠报告表/24小时报告/妊娠结局随访由 "
                "@750-751 承载。"),
            _sl("v2_n_10_6", "awaiting_3r3_contract", [],
                "妊娠检测（检测时点/方式/SOA 安排）未在 10.6 正文出现（妊娠仅见"
                "于入排标准 @402/@523 与 SOA 示例）；检测义务与妊娠事件报告是不同"
                "义务，保留待 3R.3，不得以事件报告冒充检测安排。"),
        ],
    ),
    "procedures_assessments.pk": _sr(
        "source_carried",
        [_sl("v2_n_9_3", "source_carried", [584, 585],
             "PK 评估由 9.3 条件承载（如适用否则注明不适用；标题可按分析内容修改，"
             "非群体 PK 亦可在修改标题后承载）。")],
    ),
    "procedures_assessments.pd": _sr(
        "source_carried",
        [_sl("v2_n_9_3", "source_carried", [584, 585],
             "PD 评估由 9.3 条件承载（同 PK，标题可修改）。")],
    ),
    "procedures_assessments.immunogenicity": _sr(
        "partially_carried",
        [_sl("v2_n_9_2", "partially_carried", [574, 575],
             "源文仅列通用免疫学检测及样本处理框架；不等同免疫原性策略。"
             "免疫原性适用性、抗药抗体检测及采样分析要求须在3R.3按产品证据建立。")],
    ),
    "procedures_assessments.biomarker": _sr(
        "source_carried",
        [
            _sl("v2_n_9_1", "source_carried", [558, 559],
                "疗效评估章含生物样本/特殊化验（微阵列、DNA测序等科研测定，@559）。"),
            _sl("v2_n_9_2", "source_carried", [574, 575],
                "安全性章同样列明特殊化验与科研测定（@575）。"),
        ],
    ),
    "procedures_assessments.specimen": _sr(
        "source_carried",
        [_sl("v2_n_9_2", "source_carried", [574, 575],
             "样本采集/制备/处理/存储/运输义务由 @574-575 显式承载（含 MOP 细化要求）。")],
        "12.7 储备样本和数据的未来使用（@830-836）是独立的 v2 新义务；"
        "未来使用同意不得与现行样本处理义务混同。",
    ),
    "safety.general": _sr(
        "awaiting_3r3_contract",
        [_sl("v2_n_10", "awaiting_3r3_contract", [594],
             "第10章章首仅 @594 起草指引（综合 IB/说明书等风险信息），无总则义务正文；"
             "定义义务由 10.1.1/10.2.1/10.3.1 子标题承载。")],
    ),
    "safety.definitions": _sr(
        "source_carried",
        [_sl("v2_n_10", "source_carried", [597, 598, 599, 709, 710, 722],
             "定义义务由子标题承载（forward-container/reverse-descendant 约定）："
             "10.1.1 @597-599、10.2.1 @709-710、10.3.1 @722。")],
    ),
    "safety.product_risks": _sr(
        "source_carried",
        [_sl("v2_n_2_3", "source_carried", [301, 302, 303, 305, 306],
             "已知风险/获益评估义务由 @302-303 承载；@306 为源文风险正当性表述，"
             "与 ICH E6(R3) 原则 1.1-1.3 的表述冲突已由 Codex source check 记录，"
             "保留源文并在 3R.2/3R.3 QC 标记。")],
    ),
    "safety.reporting": _sr(
        "source_carried",
        [
            _sl("v2_n_10_2_2", "source_carried", [713, 714, 715, 716],
                "SAE 报告时限/流程/因果评估由 @713-716 承载。"),
            _sl("v2_n_10_3_2", "source_carried", [724, 725, 726, 727, 728, 729],
                "SUSAR 快速报告对象/期限由 @724-729 承载；@729 签字版第0天口径与 "
                "ICH E2A 存在张力，保留源文待 3R.3 QC 按现行法规核验。"),
        ],
    ),
    "statistics.pk": _sr(
        "awaiting_3r3_contract",
        [_sl("v2_n_11_4", "awaiting_3r3_contract", [783],
             "11.4 章首仅有章节结构参考注（@783 引《药物临床试验数据管理及统计分析"
             "计划指导原则》），无 PK 分析内容；义务保留待 3R.3。")],
    ),
    "statistics.pd": _sr(
        "awaiting_3r3_contract",
        [_sl("v2_n_11_4", "awaiting_3r3_contract", [783],
             "同 statistics.pk：仅 @783 结构参考注；义务保留待 3R.3。")],
    ),
    "statistics.er": _sr(
        "awaiting_3r3_contract",
        [_sl("v2_n_11_4", "awaiting_3r3_contract", [783],
             "同 statistics.pk：仅 @783 结构参考注；义务保留待 3R.3。")],
    ),
    "statistics.subgroup": _sr(
        "source_carried",
        [_sl("v2_n_11_4_7", "source_carried", [800],
             "亚组分析以示例承载（@800；结果为探索性，不作为确证性结论依据）。")],
    ),
    "data_management.crf": _sr(
        "source_carried",
        [_sl("v2_n_12_2", "source_carried", [815, 816],
             "EDC/eCRF 数据采集与源文件一致性由 @815-816 承载。")],
    ),
    "data_management.source": _sr(
        "partially_carried",
        [
            _sl("v2_n_12_2", "source_carried", [816],
                "源文件/源数据一致性要求由 @816 承载。"),
            _sl("v2_n_12_1", "awaiting_3r3_contract", [813],
                "数据源定义义务未由 12.1 正文承载；@813 为数据管理计划（DMP）内容。"),
        ],
    ),
    "ethics.committee": _sr(
        "source_carried",
        [_sl("v2_n_13_1", "source_carried", [853],
             "伦理审查委员会审阅/批准义务由 @853 承载（源文术语为伦理审查委员会）。")],
    ),
    "study_management.compliance": _sr(
        "partially_carried",
        [_sl("v2_n_14", "source_carried", [883],
             "GCP/赫尔辛基/法规合规总则由 @883 承载。")],
        "方案依从的操作性义务（偏离处理衔接 14.6）未单列；操作切片保留待 3R.3。",
    ),
    "study_management.closeout": _sr(
        "awaiting_3r3_contract",
        [_sl("v2_n_14", "awaiting_3r3_contract", [883],
             "第14章章首无研究/中心关闭义务内容（@883 为合规总则）；关闭义务保留"
             "待 3R.3。")],
    ),
    "study_management.quality": _sr(
        "source_carried",
        [
            _sl("v2_n_14", "source_carried", [883],
                "各方（申办者/中心/CRO）质控措施义务由 @883 承载。"),
            _sl("v2_n_14_1", "source_carried", [885],
                "14.1 QbD/CtQ（@885）为 v2 新增互补内容，不替代 @883 质控义务。"),
        ],
    ),
    "appendices.contraception": _sr(
        "source_carried",
        [
            _sl("v2_n_5", "source_carried", [378],
                "避孕措施要求指引由 @378 承载（生殖状况入排时提供具体避孕要求）。"),
            _sl("v2_n_10_6", "source_carried", [749],
                "避孕期限要求由 @749 承载（停药后 3/6 个月等）。"),
        ],
        "避孕方法明细（药物/屏障法清单）未由源文承载，由项目事实确定。",
    ),
    "appendices.instruments": _sr(
        "awaiting_3r3_contract",
        [
            _sl("v2_n_16_x1", "awaiting_3r3_contract", [974],
                "附录 1 为 ECOG 示例量表（表 body_child_index=974）。"),
            _sl("v2_n_16_x2", "awaiting_3r3_contract", [978],
                "附录 2 为 NYHA 示例量表（表 body_child_index=978）。"),
        ],
        "示例量表不定义项目允许量表的全部；项目量表与评价工具清单义务保留待 "
        "3R.3，由项目事实与终点来源决定。",
    ),
    "appendices.lab_panels": _sr(
        "partially_carried",
        [_sl("v2_n_16_x3", "source_carried", [982, 983, 984, 985, 987, 988, 989, 990, 992, 993, 994, 995],
             "中心实验室与样本销毁机构信息框架由 @982-995 承载（示例占位）。")],
        "项目检测项目清单义务未由源文承载，待项目事实（3R.3）。",
    ),
    "appendices.safety_reporting": _sr(
        "partially_carried",
        [
            _sl("v2_n_10_2_2", "source_carried", [713],
                "SAE 上报途径（申办者/CRO/伦理审查委员会）由 @713 承载。"),
            _sl("v2_n_10_3_2", "source_carried", [724],
                "SUSAR 快速报告对象由 @724 承载。"),
        ],
        "24 小时联系途径明细（电话/邮箱表）未在 v2 出现；项目联系方式义务保留"
        "待 3R.3。",
    ),
    "appendices.project_specific": _sr(
        "source_carried",
        [_sl("v2_n_16", "source_carried", [971, 972],
             "附录容器开放承载项目附录：@971 罗列方案正文备注的附录，@972 示例可"
             "自定义；源示例附录不限制项目附录的种类和数量。")],
    ),
}

# Ten formerly retired conditional obligations, retained with their original
# applicability rules and concrete v2 carriers (Codex acceptance decision).
RETAINED_CONDITIONAL: tuple[str, ...] = (
    "study_design.pk_pd_sampling",
    "procedures_assessments.unscheduled",
    "procedures_assessments.immunogenicity",
    "procedures_assessments.biomarker",
    "statistics.pk",
    "statistics.pd",
    "statistics.er",
    "appendices.contraception",
    "appendices.safety_reporting",
    "appendices.project_specific",
)

MAPPING_CONVENTIONS = {
    "forward_container_reverse_descendant": (
        "forward 映射允许指向容器节点（如 safety.ae→v2_n_10_1、"
        "objectives_endpoints.primary→v2_n_3_1_2）；reverse 按叶子逐一登记，"
        "容器的每个 v2 叶子各自引用其 v1 来源。两者结合保证逐叶对账不丢义务。"
    ),
    "source_vs_additional_content": (
        "source_resolution 区分源文已承载内容（附 body-child 定位）与源文未承载、"
        "有意保留等待 3R.3 逐叶合同的 legacy 义务（awaiting_3r3_contract）；"
        "后者不得宣称源文已包含，也不得因此被退役。"
    ),
    "retained_conditional": (
        "原 retired 的十条条件义务改为保留承载：沿用原 applicability 规则"
        "（行内规则或 _CONDITIONAL_PREFIXES）并给出具体承载节点，状态为 "
        "retained_conditional_awaiting_3r3_contract；不使用 retired/reopen 叙事。"
    ),
}


CONDITIONAL_REGISTRATIONS = {
    "financial_disclosure": {
        "default": "not_applicable",
        "reason": (
            "按已批准工作台默认路径暂不启用独立财务披露模块，并非监管豁免。"
            "项目申报法域或申办者要求适用时须开启，在13.1伦理规范承载并保留项目依据。"
        ),
        "source_basis": (
            "源标题树无财务披露标题；该观察不证明项目不适用。默认来自批准Plan3R.1，"
            "适用性须结合项目申报要求，不能由标题缺失推导。"
        ),
    },
    "management_structure": {
        "carrying_v2_node_ids": ["v2_n_14_2", "v2_n_14_3", "v2_n_14_4"],
        "declaration": (
            "管理结构义务由 v2 多节点联合承载：14.2 对申办者的要求、"
            "14.3 申办者或其代表委派的监查员职责、14.4 对研究者的要求；"
            "对应 v1 12.5 关键角色和研究管理的显式拆分。"
        ),
        "source_basis": (
            "v1_to_v2_mapping.json forward_mapping study_management.roles（split）。"
        ),
    },
    "ethics_compensation_insurance": {
        "default": "required",
        "reason": (
            "13.4补偿、赔偿与保险的章节义务必须保留；金额与具体保险安排需项目事实。"
            "缺失事实进入待补事实清单，不豁免章节、不编造安排，最终正文不输出占位符。"
        ),
        "source_basis": (
            "v2 源标题 13.4；v1 对应节点 ethics.insurance（11.5 保险与赔偿）。"
        ),
    },
}

CANDIDATE_FINDINGS = [
    {
        "id": "projection_claim_76_not_accepted",
        "status": "unverified_candidate_finding",
        "claim_ref": "计划 v2 Task 3R.1 所述“已实现投影的约 76 v1 叶”",
        "observation": (
            "以 AST 实测，legacy 模块显式投影路径（_CHAPTER_BODY_FACT_PATHS 与 "
            "section_seeds 分支）覆盖的 v1 叶子数以 projection_reconciliation "
            "实际输出为准；标题相似不构成投影证据，76 的说法不作为对账基线。"
        ),
    },
    {
        "id": "legacy_counts_differ_from_frozen_plan_identity",
        "status": "observed_source_fact",
        "claim_ref": "冻结计划 Task 3.1 的 v1 语义计数 124/110",
        "observation": (
            "当前源码实际为 _COMPANY_CHAPTERS 124 行/103 叶，_company_nodes "
            "含 6 个前置节点合计 130 节点/109 叶；映射按实际源码身份对账，"
            "不回填历史计数。"
        ),
    },
    {
        "id": "no_v1_json_registry_exists",
        "status": "observed_source_fact",
        "claim_ref": "v1 registry JSON",
        "observation": (
            "仓库中不存在独立 v1 JSON registry；v1 身份唯一来源为 "
            "services/api/app/medical_writing_protocol_template.py，"
            "本任务不以臆造 JSON 充当 v1。"
        ),
    },
    {
        "id": "phase1_authority_deferred_to_3r6",
        "status": "user_decision_pending",
        "claim_ref": "Ⅰ期模板权威（TP-MA-05/06、T02-00 修订版或待提供清洁版）",
        "observation": (
            "本候选仅面向 TP-MA-07 v2（Ⅱ/Ⅲ期）；7 个 phase:1 v1 叶显式登记为 "
            "nonapplicable_phase1 并保留历史身份，Ⅰ期权威选择留待 Task 3R.6。"
        ),
    },
    {
        "id": "unheaded_content_not_covered_by_leaf_count",
        "status": "observed_source_fact",
        "claim_ref": "106 叶 = 全部内容义务",
        "observation": (
            "源文档存在无标题内容义务（临床前概述下毒理学/药代/一般药理段落、"
            "主要估计目标尾部第五属性段落、示例段落、无标题前置块）；"
            "标题叶计数不等于内容闭合，逐叶合同须读取 content_paragraph_indexes。"
        ),
    },
]


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------

EXTRACTION_ALGORITHM = [
    "sha256 门禁：源 DOCX 哈希必须等于冻结值，否则显式报错停止。",
    "styles.xml 解析样式大纲级别（含 basedOn 继承）；document.xml 仅读 body 直接子元素。",
    "标题树 = 非空正文段落且样式名为 heading/标题（排除字符样式）且有效大纲级别 0-8。",
    "大纲树 = 非空正文段落且（样式继承或段落本地 outlineLvl）有效级别 0-8；"
    "Normal/caption 本地大纲节点（缩略语表、附录 1-3）因此保留。",
    "叶子判定 = 紧邻下一标题级别 <= 当前级别或为末节点（与 2026-09-05 只读预检一致）。",
    "章节号 = 标题 1 1. 样式起按层级推导；前置件 = 首个编号章之前的 0 级大纲节点。",
    "正文段落归属最近前置大纲节点；表格单独登记并归属最近前置大纲节点。",
    "试验参与者/受试者计数按直接正文段落、顶层表格、全文档 w:t 三个口径分列。",
    "legacy 模块仅经 AST 读取 _COMPANY_CHAPTERS/_CONDITIONAL_PREFIXES/"
    "_CHAPTER_BODY_FACT_PATHS/_company_nodes/section_seeds/_node_kind，绝不 import。",
]


def build_node_tree(structure: dict) -> dict:
    nodes = structure["nodes"]
    heading_nodes = [node for node in nodes if node["in_heading_style_tree"]]
    extras = [node["id"] for node in nodes if not node["in_heading_style_tree"]]
    styles_export = {
        style_id: {
            "name": info["name"],
            "outline": info["outline"],
            "outline_resolved": _resolved_outline(style_id, structure["styles"]),
            "based_on": info["based_on"],
            "numbering": dict(info["numbering"]),
            "font": dict(info["font"]),
        }
        for style_id, info in sorted(structure["styles"].items())
    }
    return {
        "schema_version": "tp-ma-07-v2-node-tree-v1",
        "template_id": TEMPLATE_ID,
        "candidate_status": "candidate_not_current",
        "source": {
            "path": str(SOURCE_DOCX_PATH),
            "sha256": EXPECTED_SHA256,
            "access": "zip_xml_read_only",
        },
        "extraction_algorithm": EXTRACTION_ALGORITHM,
        "heading_style_tree": {
            "node_count": len(heading_nodes),
            "leaf_count": structure["heading_leaf_count"],
            "nodes": heading_nodes,
        },
        "outlined_tree": {
            "node_count": len(nodes),
            "leaf_count": sum(1 for node in nodes if node["is_leaf"]),
            "outlined_extra_node_ids": extras,
            "nodes": nodes,
        },
        "front_block": structure["front_block"],
        "excluded_blank_outlined": structure["excluded_blank_outlined"],
        "tables": structure["top_level_tables"],
        "sections": structure["sections"],
        "bookmark_inventory": structure["bookmark_inventory"],
        "field_inventory": structure["field_inventory"],
        "part_field_inventory": structure["part_field_inventory"],
        "style_properties": styles_export,
        "semantic_findings": structure["semantic_findings"],
        "terminology": structure["terminology"],
    }


def build_mapping(structure: dict, legacy: dict) -> dict:
    nodes = structure["nodes"]
    v2_ids = {node["id"] for node in nodes} | {FRONT_BLOCK_ID}

    missing = [
        node["semantic_node_id"]
        for node in legacy["nodes"]
        if node["semantic_node_id"] not in LEGACY_MAPPING
    ]
    if missing:
        raise RegistrySourceError(f"legacy nodes missing mapping entries: {missing}")
    stale_targets = []
    for semantic, entry in LEGACY_MAPPING.items():
        for target in entry["target_v2_node_ids"]:
            if target not in v2_ids:
                stale_targets.append((semantic, target))
    if stale_targets:
        raise RegistrySourceError(
            f"mapping targets missing in v2 tree: {stale_targets}"
        )
    for semantic, entry in LEGACY_MAPPING.items():
        for target in entry["target_v2_node_ids"]:
            reverse = REVERSE_MAPPING.get(target)
            if reverse is not None and semantic not in reverse["from_v1_semantic_ids"]:
                raise RegistrySourceError(f"reverse mapping missing forward edge: {semantic} -> {target}")

    outlined_leaf_ids = {node["id"] for node in nodes if node["is_leaf"]}
    required_reverse = outlined_leaf_ids | set(structure["heading_leaf_ids"])
    missing_reverse = sorted(required_reverse - set(REVERSE_MAPPING))
    if missing_reverse:
        raise RegistrySourceError(
            f"v2 leaves missing reverse dispositions: {missing_reverse}"
        )
    extra_reverse = sorted(set(REVERSE_MAPPING) - required_reverse)
    if extra_reverse:
        raise RegistrySourceError(
            f"reverse entries point at non-leaves: {extra_reverse}"
        )
    legacy_semantics = {node["semantic_node_id"] for node in legacy["nodes"]}
    for entry in REVERSE_MAPPING.values():
        for semantic in entry["from_v1_semantic_ids"]:
            if semantic not in legacy_semantics:
                raise RegistrySourceError(
                    f"reverse entry references unknown legacy node: {semantic}"
                )

    # Content resolutions must cover exactly the partial-confidence population.
    valid_statuses = {
        "source_carried",
        "partially_carried",
        "awaiting_3r3_contract",
        "unresolved",
    }
    partial_ids = {
        node["semantic_node_id"]
        for node in legacy["nodes"]
        if LEGACY_MAPPING[node["semantic_node_id"]]["confidence"] == "partial"
    }
    missing_resolutions = sorted(partial_ids - set(SOURCE_RESOLUTIONS))
    if missing_resolutions:
        raise RegistrySourceError(
            f"partial mappings missing source_resolution: {missing_resolutions}"
        )
    extra_resolutions = sorted(set(SOURCE_RESOLUTIONS) - partial_ids)
    if extra_resolutions:
        raise RegistrySourceError(
            f"source_resolution present on non-partial mapping: {extra_resolutions}"
        )
    owners = {index: node["id"] for node in nodes
              for index in [node["body_child_index"], *node["content_paragraph_indexes"]]}
    owners.update({table["body_child_index"]: table["owner_node_id"]
                   for table in structure["top_level_tables"]})
    owners.update({index: FRONT_BLOCK_ID
                   for index in structure["front_block"]["content_paragraph_indexes"]})
    parents = {node["id"]: node["parent_id"] for node in nodes}
    resolved_sources = {}
    for semantic, resolution in SOURCE_RESOLUTIONS.items():
        if resolution["status"] not in valid_statuses:
            raise RegistrySourceError(
                f"invalid source_resolution status: {semantic} "
                f"{resolution['status']}"
            )
        slices = []
        for slice_entry in resolution["targets"]:
            if slice_entry["status"] not in valid_statuses:
                raise RegistrySourceError(
                    f"invalid resolution slice status: {semantic} "
                    f"{slice_entry['status']}"
                )
            for locator in slice_entry["evidence_body_child_indexes"]:
                if not isinstance(locator, int) or locator < 0:
                    raise RegistrySourceError(
                        f"invalid evidence locator: {semantic} {locator!r}"
                    )
                owner = owners.get(locator)
                ancestor = owner
                while ancestor and ancestor != slice_entry["v2_node_id"]:
                    ancestor = parents.get(ancestor)
                if not owner or not ancestor:
                    raise RegistrySourceError(f"evidence locator outside carrier: {semantic} @{locator}")
            slices.append({**slice_entry, "actual_owner_v2_node_ids": [
                owners[index] for index in slice_entry["evidence_body_child_indexes"]
            ]})
        resolved_sources[semantic] = {**resolution, "targets": slices}

    retained_by_semantic = {
        node["semantic_node_id"]: node
        for node in legacy["nodes"]
        if node["semantic_node_id"] in RETAINED_CONDITIONAL
    }
    missing_retained = sorted(set(RETAINED_CONDITIONAL) - set(retained_by_semantic))
    if missing_retained:
        raise RegistrySourceError(
            f"retained conditional obligations missing in legacy: {missing_retained}"
        )

    evidence = _projection_evidence(legacy)
    node_kind_branches = [
        branch
        for branch in legacy["section_seed_branches"]
        if branch["kind"] == "node_kind_branch"
    ]
    node_kinds = {
        value for branch in node_kind_branches for value in branch["values"]
    }
    forward_entries = []
    projection_rows = []
    for node in legacy["nodes"]:
        semantic = node["semantic_node_id"]
        entry = LEGACY_MAPPING[semantic]
        merged = {
            "node_id": node["node_id"],
            "semantic_node_id": semantic,
            "title_zh": node["title_zh"],
            "section_number": node["section_number"],
            "is_leaf": node["is_leaf"],
            "conditional_rules": node["applicability_rules"],
            "applicability_mode": node["applicability_mode"],
            "m11_coverage_anchors": node["m11_coverage_anchors"],
            "anchor_provenance": (
                "legacy_frozen_3_1_chapter_row"
                if node["m11_coverage_anchors"]
                else "none_in_legacy"
            ),
            "disposition": entry["disposition"],
            "target_v2_node_ids": entry["target_v2_node_ids"],
            "rationale": entry["rationale"],
            "confidence": entry["confidence"],
            "phase1_identity_retained": (
                entry["disposition"] == "nonapplicable_phase1"
            ),
        }
        if entry["ambiguity_note"]:
            merged["ambiguity_note"] = entry["ambiguity_note"]
        if entry["confidence"] == "partial":
            merged["source_resolution"] = resolved_sources[semantic]
        forward_entries.append(merged)
        if node["is_leaf"]:
            items = list(evidence.get(semantic, []))
            if node["node_kind"] in node_kinds:
                branch = node_kind_branches[0]
                items.append(
                    {
                        "mechanism": "section_seeds_branch",
                        "location": f"{LEGACY_MODULE_REL}:{branch['lineno']}",
                        "fact_paths": [],
                    }
                )
            projection_rows.append(
                {
                    "semantic_node_id": semantic,
                    "node_id": node["node_id"],
                    "projection_status": (
                        "explicit_projection"
                        if items
                        else "no_explicit_projection_found"
                    ),
                    "evidence": items,
                }
            )

    explicit_count = sum(
        1
        for row in projection_rows
        if row["projection_status"] == "explicit_projection"
    )
    ast_count = count_explicit_projection_leaves(legacy)
    if explicit_count != ast_count:
        raise RegistrySourceError(
            f"projection leaf count drift: mapping={explicit_count} ast={ast_count}"
        )

    disposition_counts = Counter(
        entry["disposition"] for entry in forward_entries if entry["is_leaf"]
    )
    resolution_status_counts = Counter(
        entry["source_resolution"]["status"]
        for entry in forward_entries
        if "source_resolution" in entry
    )
    retained_block = []
    for semantic in RETAINED_CONDITIONAL:
        legacy_node = retained_by_semantic[semantic]
        rules = legacy_node["applicability_rules"]
        if rules:
            conditional_source = "row_rules"
        elif any(
            legacy_node["section_number"] == item
            or legacy_node["section_number"].startswith(f"{item}.")
            for item in legacy["_conditional_prefixes"]
        ):
            conditional_source = "conditional_prefixes"
        else:
            conditional_source = "required_in_legacy"
        retained_block.append(
            {
                "semantic_node_id": semantic,
                "original_applicability_rules": rules,
                "applicability_mode": legacy_node["applicability_mode"],
                "conditional_source": conditional_source,
                "carrier_v2_node_ids": LEGACY_MAPPING[semantic][
                    "target_v2_node_ids"
                ],
                "carrying_status": "retained_conditional_awaiting_3r3_contract",
            }
        )
    new_anchor_ids = sorted(
        entry["v2_node_id"]
        for entry in REVERSE_MAPPING.values()
        if entry["disposition"] == "new_in_v2"
    )
    anchor_policy = {
        "policy": (
            "M11 锚点仅继承自冻结计划 Task 3.1 对应的 _COMPANY_CHAPTERS 行"
            "（anchor_provenance=legacy_frozen_3_1_chapter_row），本候选不发明新锚点；"
            "new_in_v2 节点的锚点要求未经验证，显式列为 unverified 待 3R.3 确认。"
            "legacy 锚点编号是历史清单标签，不等同已核实的 ICH E6(R3) B.x 条款锚点，"
            "引用前须对照现行指南原文。"
        ),
        "unverified_new_anchor_requirement_v2_node_ids": new_anchor_ids,
    }

    return {
        "schema_version": "tp-ma-07-v2-v1-mapping-v1",
        "template_id": TEMPLATE_ID,
        "candidate_status": "candidate_not_current",
        "dispositions_vocabulary": [
            "mapped_to_v2",
            "split",
            "merged",
            "retired",
            "nonapplicable_phase1",
        ],
        "reverse_dispositions_vocabulary": ["from_v1", "new_in_v2", "mixed"],
        "legacy_source": {
            "module_path": legacy["module_path"],
            "module_sha256": legacy["module_sha256"],
            "company_chapters_lineno": legacy["chapters_lineno"],
            "access": "ast_only_never_imported",
        },
        "legacy_inventory": {
            "chapter_row_count": legacy["chapter_row_count"],
            "chapter_row_leaves": legacy["chapter_row_leaves"],
            "front_node_count": legacy["front_node_count"],
            "node_count": legacy["node_count"],
            "leaf_count": legacy["leaf_count"],
            "phase1_leaf_count": legacy["phase1_leaf_count"],
            "nodes": legacy["nodes"],
        },
        "forward_mapping": forward_entries,
        "reverse_mapping": [
            REVERSE_MAPPING[node_id] for node_id in sorted(REVERSE_MAPPING)
        ],
        "mapping_conventions": MAPPING_CONVENTIONS,
        "retained_conditional_obligations": retained_block,
        "m11_anchor_policy": anchor_policy,
        "projection_reconciliation": {
            "explicit_projection_leaf_count": explicit_count,
            "no_explicit_projection_leaf_count": len(projection_rows) - explicit_count,
            "historical_claim": "约 76 v1 叶已实现投影（未经证实，不作为对账基线）",
            "leaves": projection_rows,
        },
        "candidate_findings": [
            {
                "id": "partial_confidence_mapping_requires_review",
                "status": "unverified_candidate_finding",
                "v1_semantic_ids": sorted(
                    entry["semantic_node_id"]
                    for entry in forward_entries
                    if entry.get("confidence") == "partial" and entry["is_leaf"]
                ),
                "observation": (
                    "部分映射基于结构近邻而非内容复核，已在 ambiguity_note 中列明；"
                    "标题相似不构成投影或内容对应证据。"
                ),
            }
        ],
        "mapping_summary": {
            "legacy_leaf_total": legacy["leaf_count"],
            "legacy_leaf_dispositions": dict(sorted(disposition_counts.items())),
            "reverse_entry_total": len(REVERSE_MAPPING),
            "new_in_v2_leaf_count": sum(
                1
                for entry in REVERSE_MAPPING.values()
                if entry["disposition"] == "new_in_v2"
                and entry["v2_node_id"] in outlined_leaf_ids
            ),
            "source_resolution_statuses": dict(
                sorted(resolution_status_counts.items())
            ),
        },
    }


def build_template(structure: dict, legacy: dict, mapping: dict) -> dict:
    counts = {
        "direct_body_paragraphs": structure["direct_body_paragraphs"],
        "heading_style_nodes": len(
            [n for n in structure["nodes"] if n["in_heading_style_tree"]]
        ),
        "heading_style_leaves": structure["heading_leaf_count"],
        "outlined_nodes": len(structure["nodes"]),
        "outlined_leaves": sum(1 for node in structure["nodes"] if node["is_leaf"]),
        "top_level_tables": len(structure["top_level_tables"]),
        "recursive_tables": structure["recursive_tables"],
        "sections": len(structure["sections"]),
        "tracked_changes": structure["tracked_changes"],
        "excluded_blank_outlined": len(structure["excluded_blank_outlined"]),
    }
    return {
        "schema_version": "tp-ma-07-v2-template-registry-v1",
        "template_id": TEMPLATE_ID,
        "candidate_status": "candidate_not_current",
        "promotion_requirements": [
            "Codex 对源内容、legacy 投影义务与候选映射的独立语义复核；",
            "独立新评审人的源覆盖复核；",
            "映射 partial 条目与 candidate_findings 逐条处置；",
            "以上全部通过前，本 registry 不得进入 current 或产品运行时。",
        ],
        "source": {
            "path": str(SOURCE_DOCX_PATH),
            "sha256": EXPECTED_SHA256,
            "access": "zip_xml_read_only_never_written",
        },
        "legacy_source": {
            "module_path": legacy["module_path"],
            "module_sha256": legacy["module_sha256"],
            "access": "ast_only_never_imported",
            "identity_note": (
                "company 权威元数据指向历史 D017/D001/MG-K10 方案；本候选按当前源码"
                "实际身份（124 行/103 叶 + 6 前置 = 130/109）对账。"
            ),
        },
        "extraction_algorithm": EXTRACTION_ALGORITHM,
        "authoritative_counts": counts,
        "count_scope_notes": [
            "135/106 为标题样式树口径；139/109 为含 Normal/caption 本地大纲的大纲树口径；两者分列。",
            "17 为 body 顶层表格数，18 为 document.xml 递归表格数；嵌套表随宿主表登记不另计。",
            "试验参与者计数按直接正文段落、顶层表格、全文档 w:t 三个口径分列。",
            "空白大纲段落不计入节点，但保留定位记录。",
        ],
        "terminology": structure["terminology"],
        "conditional_registrations": CONDITIONAL_REGISTRATIONS,
        "candidate_findings": CANDIDATE_FINDINGS,
        "legacy_projection_reconciliation": {
            "explicit_projection_leaf_count": mapping["projection_reconciliation"][
                "explicit_projection_leaf_count"
            ],
            "no_explicit_projection_leaf_count": mapping["projection_reconciliation"][
                "no_explicit_projection_leaf_count"
            ],
            "detail_ref": "v1_to_v2_mapping.json projection_reconciliation.leaves",
        },
        "mapping_summary": mapping["mapping_summary"],
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")


def build_all(out_dir: Path | str = DEFAULT_OUT_DIR) -> dict:
    out_dir = Path(out_dir)
    verify_source_hash()
    structure = extract_docx_structure(SOURCE_DOCX_PATH)
    legacy = extract_legacy_inventory()
    mapping = build_mapping(structure, legacy)
    tree = build_node_tree(structure)
    template = build_template(structure, legacy, mapping)
    _write_json(out_dir / "template.json", template)
    _write_json(out_dir / "node_tree.json", tree)
    _write_json(out_dir / "v1_to_v2_mapping.json", mapping)
    return {
        "out_dir": str(out_dir),
        "template_json_bytes": len(json.dumps(template)),
        "node_tree_json_bytes": len(json.dumps(tree)),
        "v1_to_v2_mapping_json_bytes": len(json.dumps(mapping)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract the TP-MA-07 v2 candidate registry (Task 3R.1)."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="output directory for the three candidate JSON files",
    )
    args = parser.parse_args(argv)
    summary = build_all(args.out_dir)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
