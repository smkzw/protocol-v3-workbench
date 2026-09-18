"""3R.5A R03: deterministic QC criteria registry extraction (E04 worker).

Reads the frozen CMSS-SOP-MD-5101-R03-00 QC-table DOCX (zip/XML read-only,
never written, never opened in Word) and emits
``config/medical_writing/protocol_v3/qc/r03_criteria.json`` containing:

- the complete raw source: 17 tables / 104 physical rows = 4 identity rows +
  32 repeated header rows + 68 content rows, with zero-based
  ``table/row/cell`` locators, gridSpan / vMerge markers and verbatim
  paragraph text (empty labels, merged cells and source typos preserved);
- the T5/R0/C1 header-embedded recruitment obligation as a separate fragment
  (never counted as a 69th content row, never silently dropped);
- the signature paragraph recorded as a legal blank control (never forged,
  never treated as a draft placeholder);
- atomic obligations per content row: every atom keeps its source locator,
  verbatim raw fragment, a normalized check (source typos never leak in),
  check category (deterministic / agent4 / human), semantic node ids from the
  current tp_ma_07_v2 node tree, applicability (real rule id or explicitly
  not-wired), evidence requirement and honest implementation status;
- six L1 checks registered with honest implementation status: only version
  four-point consistency and textual cross-reference resolution are
  implemented (typed input only, in ``services/api/app/protocol_workflow/
  qc/r03.py``); the other four stay pending with explicit reasons.

Criterion ids are derived from the source locator, never from the E6 label
(empty, duplicated, trailing-space and garbled labels like 6.4.0 / 6.16 are
not stable identifiers).  Every run is deterministic: same inputs produce
byte-identical output, standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
SOURCE_DOCX_PATH = Path(
    "/Users/smkzw/Documents/康哲项目资料/SOP/CMSS-SOP-MD-5101_GCP2026_ICHE6R3_修订版_DOCX/"
    "CMSS-SOP-MD-5101-R03-00  临床研究方案QC表_修订版.docx"
)
EXPECTED_SHA256 = (
    "5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9"
)
NODE_TREE_PATH = (
    ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json"
)
APPLICABILITY_RULES_PATH = (
    ROOT
    / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/applicability_rules.json"
)
DEFAULT_OUT_PATH = ROOT / "config/medical_writing/protocol_v3/qc/r03_criteria.json"

TEMPLATE_ID = "cmss_sop_md_5101_r03_qc_table"
SCHEMA_VERSION = "r03_criteria_v1"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

HEADER_COLUMN_PREFIX = "描述/文本"
HEADER_FRAGMENT_EXPECTED = "试验参与者识别和招募方法。"
SIGNATURE_MARKER = "填表人签字"

# Source-noise markers that must stay in raw text and must never appear in
# any normalized obligation text (self-checked at generation time).
SOURCE_NOISE_MARKERS = ("Lal", "试验目的和目的", "DescrIDescription")


class RegistrySourceError(RuntimeError):
    """Raised when the source gate or generation invariants fail."""


def verify_source_hash(path: Path | str = SOURCE_DOCX_PATH) -> str:
    path = Path(path)
    if not path.is_file():
        raise RegistrySourceError(f"source file missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RegistrySourceError(
            f"source hash mismatch: expected {EXPECTED_SHA256}, "
            f"observed {digest} for {path}"
        )
    return digest


# ---------------------------------------------------------------------------
# Read-only DOCX structural extraction (zip/XML, standard library)
# ---------------------------------------------------------------------------


def _read_document_root(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def extract_body_paragraphs(path: Path | str = SOURCE_DOCX_PATH) -> list[str]:
    """Verbatim text of every top-level body paragraph, by body child index."""
    root = _read_document_root(Path(path))
    body = root.find(f"{W}body")
    paragraphs: list[str] = []
    for child in body:
        if child.tag == f"{W}p":
            paragraphs.append(
                "".join(t.text or "" for t in child.iter(f"{W}t"))
            )
    return paragraphs


def extract_source_rows(path: Path | str = SOURCE_DOCX_PATH) -> list[dict]:
    """All physical table rows with zero-based locators and merge markers.

    Byte-format compatible with the audited baseline
    ``runs/mw_protocol_v3_3r5a_source_audit_20260913/r03_source_rows.json``.
    """
    root = _read_document_root(Path(path))
    body = root.find(f"{W}body")
    rows: list[dict] = []
    table_index = 0
    for body_index, child in enumerate(body):
        if child.tag != f"{W}tbl":
            continue
        for row_index, tr in enumerate(child.findall(f"{W}tr")):
            cells: list[dict] = []
            for cell_index, tc in enumerate(tr.findall(f"{W}tc")):
                tc_pr = tc.find(f"{W}tcPr")
                grid_span = None
                vertical_merge = None
                if tc_pr is not None:
                    span = tc_pr.find(f"{W}gridSpan")
                    if span is not None:
                        grid_span = span.get(f"{W}val")
                    merge = tc_pr.find(f"{W}vMerge")
                    if merge is not None:
                        vertical_merge = merge.get(f"{W}val") or "continue"
                paragraphs = [
                    "".join(t.text or "" for t in p.iter(f"{W}t"))
                    for p in tc.findall(f"{W}p")
                ]
                cells.append(
                    {
                        "cell_index": cell_index,
                        "paragraphs": paragraphs,
                        "grid_span": grid_span,
                        "vertical_merge": vertical_merge,
                    }
                )
            rows.append(
                {
                    "table_index": table_index,
                    "body_index": body_index,
                    "row_index": row_index,
                    "cells": cells,
                }
            )
        table_index += 1
    return rows


def row_kind(table_index: int, row_index: int) -> str:
    if table_index == 0:
        return "identity"
    if row_index in (0, 1):
        return "header"
    return "content"


def row_locator(row: dict) -> str:
    return f"table[{row['table_index']}]/row[{row['row_index']}]"


def row_text(row: dict) -> str:
    return " ".join(
        "".join(cell["paragraphs"]) for cell in row["cells"]
    )


def row_text_index(source_rows: list[dict]) -> dict[str, str]:
    return {row_locator(row): row_text(row) for row in source_rows}


def norm(text: str) -> str:
    return "".join(text.split())


def _cell_text(row: dict, cell_index: int) -> str:
    cells = row["cells"]
    if cell_index >= len(cells):
        return ""
    return "".join(cells[cell_index]["paragraphs"])


def extract_header_fragment(source_rows: list[dict]) -> dict:
    """T5/R0/C1 carries an obligation inside the repeated header row.

    The raw cell keeps the source column title and the stray quote character
    verbatim; only the embedded obligation text is extracted for the atom.
    """
    row = next(
        r for r in source_rows
        if r["table_index"] == 5 and r["row_index"] == 0
    )
    raw_text = _cell_text(row, 1)
    obligation = raw_text.replace(HEADER_COLUMN_PREFIX, "", 1)
    obligation = obligation.lstrip("“").strip()
    if obligation != HEADER_FRAGMENT_EXPECTED:
        raise RegistrySourceError(
            "header-embedded obligation changed: expected "
            f"{HEADER_FRAGMENT_EXPECTED!r}, observed {obligation!r}"
        )
    return {
        "source_locator": "table[5]/row[0]/cell[1]",
        "raw_text": raw_text,
        "obligation_text": obligation,
        "note": (
            "表头内嵌义务：不作为第69条内容行计入分母，也不得随表头过滤丢失；"
            "原文中的杂引号按源保留，不进入规范化正文。"
        ),
    }


def extract_identity_fields(source_rows: list[dict]) -> list[dict]:
    fields = []
    for row in source_rows:
        if row["table_index"] != 0:
            continue
        fields.append(
            {
                "source_locator": row_locator(row),
                "label": _cell_text(row, 0),
                "value": _cell_text(row, 1),
                "note": "空白表格身份栏；实际值由被QC的方案版本承载。",
            }
        )
    if len(fields) != 4:
        raise RegistrySourceError(
            f"identity rows changed: expected 4, observed {len(fields)}"
        )
    return fields


def extract_signature_area(source_rows: list[dict], path: Path) -> dict:
    paragraphs = extract_body_paragraphs(path)
    for index, text in enumerate(paragraphs):
        if SIGNATURE_MARKER in text:
            return {
                "source_locator": f"body/paragraph[{index}]",
                "raw_text": text,
                "blank_controls_legal": True,
                "note": (
                    "签署控件按原文保留为空白；不生成签名、日期或已审批事实，"
                    "不把空白控件判为草稿占位符；行内孤立字符按源保留。"
                ),
            }
    raise RegistrySourceError("signature paragraph not found in source body")


# ---------------------------------------------------------------------------
# Atomic obligation table (authored from the audited source rows; fragments
# are validated against the real DOCX text at generation time)
# ---------------------------------------------------------------------------


def _atom(
    locator,
    key,
    category,
    nodes,
    normalized,
    evidence,
    frag,
    status="pending",
    check_ref=None,
    rule=None,
    applicability="always",
    flags=(),
    human=None,
    note="",
):
    if rule is not None:
        applicability_block = {
            "status": applicability,
            "rule_ref": rule,
            "wiring": "declared_not_evaluated",
            "note": "规则ID已存在于当前applicability_rules.json；本注册表不重复评估，适用性由现有适用性引擎按研究事实裁定。",
        }
    elif applicability == "always":
        applicability_block = {
            "status": "always",
            "rule_ref": None,
            "wiring": "not_applicable",
            "note": "对进入QC的方案普遍适用，无需条件规则。",
        }
    else:
        applicability_block = {
            "status": applicability,
            "rule_ref": None,
            "wiring": "not_wired",
            "note": "适用条件依赖研究事实且当前没有可复用的已登记规则ID；未知按未决处理，不得当false。",
        }
    return {
        "source_locator": locator,
        "sub_key": key,
        "check_category": category,
        "semantic_node_ids": list(nodes),
        "normalized_check": normalized,
        "evidence_requirement": evidence,
        "raw_fragment": frag,
        "implementation_status": status,
        "check_ref": check_ref,
        "human_confirmation_ref": human,
        "flags": list(flags),
        "applicability": applicability_block,
        "note": note,
    }


NOT_WIRED_VERSION_NOTE = (
    "typed输入检查已实现；真实文档投影与产品消费者（生成模型/Word/UI）属V1接线，本阶段不对真实文档声称已执行。"
)


def _criteria() -> list[dict]:
    a = _atom
    DT, A4, HU = "deterministic", "agent4", "human"
    EV_DOC = "生成方案正文对应章节的实际内容投影。"
    EV_FACT = "已确认研究事实（StudyDefinition投影）与正文的一致性证据。"
    EV_TYPED = "QC表身份四点的typed投影（封面/文档控制区/QC表身份栏实测值）。"

    atoms: list[dict] = []

    # -- identity rows (table 0): version four-point, implemented ----------
    identity_specs = [
        ("table[0]/row[0]", "title", "研究方案题目",
         "方案题目已填写，且与封面/文档控制区及QC表身份栏完全一致。"),
        ("table[0]/row[1]", "protocol_number", "方案编号",
         "方案编号已填写，且与封面/文档控制区及QC表身份栏完全一致。"),
        ("table[0]/row[2]", "version_number", "方案版本号",
         "方案版本号已填写，且与封面/文档控制区及QC表身份栏完全一致。"),
        ("table[0]/row[3]", "version_date", "方案版本日期",
         "方案版本日期已填写，且与封面/文档控制区及QC表身份栏完全一致；修订历史旧行保留旧值不参与当前一致性比较。"),
    ]
    for locator, key, frag, normalized in identity_specs:
        atoms.append(a(locator, key, category=DT, nodes=["v2_front_block"],
                       normalized=normalized, evidence=EV_TYPED, frag=frag,
                       status="implemented", check_ref="qc.r03:version_four_point"))

    # -- table 1: 6.1 一般信息 ---------------------------------------------
    atoms += [
        a("table[1]/row[2]", "identification", DT,
          ["v2_front_block", "v2_n_front_1"],
          "方案给出题目、方案识别号和版本日期；存在修正案时注明修正案编号和日期。",
          EV_TYPED, "方案标题、方案识别号和日期", status="implemented",
          check_ref="qc.r03:version_four_point"),
        a("table[1]/row[2]", "amendment_numbering", DT,
          ["v2_n_front_1"],
          "存在修正案时，修正案带修正案编号和日期，且与修订历史记录一致。",
          "修订历史记录与修正案文档的实际投影。", "任何修正案还应注明修正案编号和日期",
          rule="applicability:front-1:amendment"),
        a("table[1]/row[3]", "sponsor_monitor", HU,
          ["v2_n_front_4"],
          "方案载明申办者及监查员（如非申办者）的名称和地址，与已确认研究事实一致。",
          "申办者/监查员实体信息的已确认事实。", "申办者和监查员",
          human="confirm_contact_entities"),
        a("table[1]/row[4]", "signatory", HU,
          ["v2_n_front_3"],
          "方案载明被授权签署方案及修正案人员的姓名和职位；签署授权真实性由人工确认，签署控件本身保留空白。",
          "授权签署人已确认事实；正式签署回执属V1。", "被授权为申办者签署方案",
          human="confirm_signature_authority"),
        a("table[1]/row[5]", "medical_expert", HU,
          ["v2_n_front_4"],
          "方案载明申办方医学专家（或牙医，如适用）的姓名、职位、地址和电话号码，与已确认事实一致。",
          "医学专家实体信息的已确认事实。", "试验申办方医学专家",
          human="confirm_contact_entities"),
        a("table[1]/row[6]", "investigator_center", HU,
          ["v2_n_front_2", "v2_n_front_4"],
          "方案载明主要研究者姓名和职位及中心地址电话，与已确认事实一致；不虚构人员或中心。",
          "研究者与中心的已确认事实。", "负责开展试验的研究者的姓名和职位",
          human="confirm_contact_entities"),
        a("table[1]/row[6]", "collaborative_centers", A4,
          ["v2_n_front_2", "v2_n_front_4"],
          "存在协作研究中心时，方案逐一列出；无协作中心时该项按适用性为不适用而非缺失。",
          "中心安排的已确认事实。", "列出将进行研究的任何协作研究中心",
          applicability="conditional"),
        a("table[1]/row[7]", "medical_decider", HU,
          ["v2_n_front_4"],
          "相关医学决策负责医师（如非研究者）的姓名、职位、地址和电话载明且真实。",
          "医学决策负责人的已确认事实。", "负责所有试验中心相关医学",
          applicability="conditional", human="confirm_contact_entities"),
        a("table[1]/row[8]", "labs_institutions", HU,
          ["v2_n_front_4", "v2_n_16_x3"],
          "参与试验的实验室和其他医疗/技术部门/机构的名称和地址载明且真实；未取得实际供应商名称时保持缺失状态，不填假名。",
          "中心实验室/供应商已确认信息。", "临床实验室和参与试验的其他医疗",
          applicability="conditional", rule="applicability:front-4:service-parties",
          human="confirm_contact_entities"),
    ]

    # -- table 2: 6.2 背景信息 ---------------------------------------------
    atoms += [
        a("table[2]/row[2]", "imp_description", A4,
          ["v2_n_2_2_1", "v2_n_6_1_1"],
          "方案给出试验用药品的名称和描述，与已确认研究事实同一版本。",
          EV_FACT, "试验用药品的名称和描述"),
        a("table[2]/row[3]", "prior_results", A4,
          ["v2_n_2_2_2_1", "v2_n_2_2_1"],
          "方案总结具有临床意义的非临床研究及相关临床试验结果，关键结论有证据定位。",
          "IB及已准入证据单元。", "非临床研究和与试验相关的临床试验的结果总结"),
        a("table[2]/row[4]", "risk_benefit", A4,
          ["v2_n_2_3"],
          "方案总结试验参与者已知和潜在风险与获益（如有），与证据一致。",
          EV_DOC + "证据定位由Agent④复核。", "已知和潜在风险和获益"),
        a("table[2]/row[5]", "administration_description", A4,
          ["v2_n_4_3", "v2_n_6_1_2"],
          "方案描述给药途径、剂量、给药方案和治疗阶段。",
          EV_FACT, "给药途径、剂量、给药方案和治疗阶段的描述"),
        a("table[2]/row[5]", "administration_rationale", A4,
          ["v2_n_4_3"],
          "给药途径/剂量/方案/治疗阶段的依据给出，与SOA及剂量选择依据一致。",
          EV_FACT, "和治疗阶段的描述和依据"),
        a("table[2]/row[6]", "gcp_statement", DT,
          ["v2_n_13_1"],
          "方案含按方案、GCP和适用法规要求开展试验的声明。",
          EV_DOC, "声明试验将按照方案、GCP和适用的法规要求进行"),
        a("table[2]/row[7]", "population_description", A4,
          ["v2_n_5_1", "v2_n_3_1_2_1"],
          "方案描述待研究人群，与目标人群/入排标准同一事实版本。",
          EV_FACT, "待研究人群描述"),
        a("table[2]/row[8]", "references_present", A4,
          ["v2_n_2_1", "v2_n_15"],
          "方案引用与试验相关的文献和数据并为试验提供背景，引文可定位。",
          EV_DOC, "引用与试验相关的文献和数据"),
        a("table[2]/row[8]", "references_bidirectional", DT,
          ["v2_n_15"],
          "正文文献引用与参考文献列表双向闭合；闭合不等于证据仍适用，时效性由来源/语义复核另行判断。",
          "参考文献列表与正文引文投影。", "引用与试验相关的文献和数据",
          note="属L1文献双向登记项，检查实现pending；不得用年份阈值冒充医学时效性验收。"),
    ]

    # -- table 3: 6.3 目的 ---------------------------------------------------
    atoms += [
        a("table[3]/row[2]", "objective_statement", A4,
          ["v2_n_3_1_1", "v2_n_3_2_1", "v2_n_3_3_1", "v2_n_3_4_1"],
          "方案详细描述研究目的（科学/次要/安全性/探索性，按实际安排）。",
          EV_FACT, "试验目的和目的的详细描述",
          note="源行原文为“试验目的和目的”，系源文措辞重复；规范化表述不复制该拼写，原文在raw区保留。"),
    ]
    atoms += [
        a("table[3]/row[3]", "scientific_question", A4,
          ["v2_n_3_1_2_1"],
          "科学目的清晰明确，可由目的-终点-估计目标链条核对。",
          EV_DOC, "科学目的是否清晰明确"),
        a("table[3]/row[3]", "population", A4,
          ["v2_n_3_1_2_1"],
          "估计目标的目标人群属性明确，与研究人群同一事实版本。",
          EV_FACT, "目标人群、治疗条件、结局变量"),
        a("table[3]/row[3]", "treatment_condition", A4,
          ["v2_n_3_1_2_3"],
          "估计目标的治疗条件属性明确（含背景/补救治疗安排）。",
          EV_FACT, "目标人群、治疗条件、结局变量"),
        a("table[3]/row[3]", "outcome_variable", A4,
          ["v2_n_3_1_2_2"],
          "估计目标的结局变量属性明确，与终点定义一致。",
          EV_FACT, "结局变量"),
        a("table[3]/row[3]", "intercurrent_event", A4,
          ["v2_n_3_1_2_4"],
          "伴发事件处理策略明确，与ICE及统计分析一致。",
          EV_FACT, "伴发事件处理策略"),
        a("table[3]/row[3]", "population_summary", A4,
          ["v2_n_3_1_2_4"],
          "人群汇总量属性明确；按源审阅该属性由3.1.2.4区承载，不因目录没有第五个标题而判缺失。",
          EV_DOC, "人群汇总量",
          note="候选映射标注：群体汇总量实际由3.1.2.4承载；由Agent④按实际文本复核，不能只数标题数量。"),
        a("table[3]/row[3]", "consistency", DT,
          ["v2_n_11_4_3_1", "v2_n_11_4_3_2"],
          "估计目标各属性与终点及统计分析保持一致（跨章同一事实版本）。",
          "一致性图（consistency edges）与事实标签投影。", "并与终点及统计分析保持一致",
          rule="applicability:n-3-1-2-4:strategy-crosscheck",
          note="结构一致性属确定性检查；跨章检查实现pending，未接线前不声称已执行。"),
    ]

    # -- table 4: 6.4 试验设计 ----------------------------------------------
    atoms += [
        a("table[4]/row[2]", "primary_endpoint", A4,
          ["v2_n_3_1_2_2", "v2_n_3_2_2"],
          "主要终点具体声明，与目的及统计分析一致。",
          EV_FACT, "主要终点和次要终点"),
        a("table[4]/row[2]", "secondary_endpoints", A4,
          ["v2_n_3_2_2"],
          "次要终点（如有）具体声明；无次要终点时按适用性处理而非缺失。",
          EV_FACT, "主要终点和次要终点（如有）",
          applicability="conditional"),
        a("table[4]/row[3]", "design_description", A4,
          ["v2_n_4_1", "v2_n_1_2"],
          "试验类型/设计描述给出，与已确认设计事实一致。",
          EV_FACT, "试验类型/设计描述"),
        a("table[4]/row[3]", "design_schematic", DT,
          ["v2_n_1_2"],
          "试验设计、程序和阶段示意图存在且与研究流程表一致。",
          EV_DOC, "试验设计、程序和阶段示意图"),
        a("table[4]/row[4]", "enrollment_definition", A4,
          ["v2_n_4_1", "v2_n_7_1"],
          "给出试验参与者何时被视为入组（研究中）的定义。",
          EV_DOC, "何时被视为“入组”（研究中）的定义"),
        a("table[4]/row[5]", "substudies", A4,
          ["v2_n_4_1", "v2_n_9_3", "v2_n_12_7"],
          "确定任何亚研究并说明其安排；无亚研究时按适用性处理。",
          EV_FACT, "确定任何亚研究",
          flags=("source_noise",),
          note="源行以杂引号开头（“确定任何亚研究。），杂符按源保留，不进入规范化正文。"),
        a("table[4]/row[6]", "visit_schedule", A4,
          ["v2_n_1_3", "v2_n_7_1", "v2_n_7_2", "v2_n_7_3"],
          "详细描述访视次数、各访视窗口期程序和研究访视时长，与SOA一致。",
          EV_FACT, "访视次数、每个访视窗口期的程序"),
        a("table[4]/row[7]", "randomization_measures", A4,
          ["v2_n_4_5", "v2_n_11_3"],
          "随机化设计下描述随机化措施以减少偏差。",
          EV_FACT, "（a）随机化",
          applicability="conditional", rule="applicability:n-7-2:randomization"),
        a("table[4]/row[7]", "blinding_measures", A4,
          ["v2_n_4_5", "v2_n_11_3"],
          "设盲设计下描述设盲措施以减少偏差；源行以“设盲”截尾，原文按源保留。",
          EV_FACT, "（b）设盲",
          applicability="conditional", rule="applicability:v2_n_4_5:blinding"),
        a("table[4]/row[8]", "drug_dosing", A4,
          ["v2_n_6_1_1", "v2_n_6_1_2", "v2_n_6_2_2"],
          "药物/补充剂/生物制剂场景：描述试验治疗和试验药物剂量与给药方案。",
          EV_FACT, "药物、补充剂或生物制剂",
          applicability="conditional"),
        a("table[4]/row[8]", "drug_formulation_labeling", A4,
          ["v2_n_6_2_2"],
          "药物/补充剂/生物制剂场景：描述试验用药品剂型、包装和标签。",
          EV_DOC, "剂型、包装和标签描述",
          applicability="conditional"),
        a("table[4]/row[9]", "device_application", A4,
          ["v2_n_6_1_1", "v2_n_6_1_2", "v2_n_6_2_2"],
          "器械场景：描述试验治疗及器械植入/应用/移除。",
          EV_FACT, "器械：试验治疗和器械植入/应用的描述",
          applicability="conditional",
          note="仅器械研究适用；当前模板/研究事实未裁定产品类型时不评估，不当false也不作普遍缺陷。"),
        a("table[4]/row[9]", "device_quality_labeling", A4,
          ["v2_n_6_2_2"],
          "器械场景：描述试验用产品（器械）质量标准、包装和标签。",
          EV_DOC, "器械质量标准、包装和标签的描述",
          applicability="conditional",
          note="同上：器械适用条件未接线，未知不当false。"),
        a("table[4]/row[10]", "participation_duration", A4,
          ["v2_n_4_1", "v2_n_7_1", "v2_n_7_2", "v2_n_7_3"],
          "描述参与者参与的预期持续时间及所有阶段的序列和持续时间（含随访，如有）。",
          EV_FACT, "预期持续时间，以及所有试验阶段的序列"),
        a("table[4]/row[11]", "individual_stop", A4,
          ["v2_n_8_1", "v2_n_8_2", "v2_n_14_7", "v2_n_11_4_9"],
          "给出个体试验参与者停止规则/停药标准。",
          EV_FACT, "个体试验参与者、部分试验和整个试验",
          rule="applicability:n-8-1:individual-hold"),
        a("table[4]/row[11]", "partial_stop", A4,
          ["v2_n_8_1", "v2_n_14_7"],
          "给出部分试验层面的停止规则；无此安排时按适用性处理。",
          EV_FACT, "部分试验和整个试验的“停止规则”",
          applicability="conditional"),
        a("table[4]/row[11]", "trial_stop", A4,
          ["v2_n_8_1", "v2_n_14_7", "v2_n_11_4_9"],
          "给出整个试验的停止规则；整试验停止安排不默认全部绑定到期中分析。",
          EV_FACT, "整个试验的“停止规则”或“停药标准”",
          rule="applicability:n-8-1:hold-to-stop"),
        a("table[4]/row[12]", "imp_accountability", A4,
          ["v2_n_6_2_1"],
          "给出试验用药品清点程序。",
          EV_DOC, "试验用药品的清点程序"),
        a("table[4]/row[12]", "placebo_accountability", A4,
          ["v2_n_6_2_1"],
          "使用安慰剂/假手术/对照药物时，其清点一并覆盖；未使用时按适用性处理。",
          EV_FACT, "包括安慰剂/假手术和对照药物（如有）",
          applicability="conditional", rule="applicability:v2_n_4_2:placebo"),
        a("table[4]/row[13]", "randomization_code", A4,
          ["v2_n_4_5"],
          "给出维持试验治疗随机化代码的程序。",
          EV_DOC, "维持试验治疗随机化代码"),
        a("table[4]/row[13]", "code_break", A4,
          ["v2_n_4_5"],
          "给出破解代码程序；非盲设计下按适用性处理。",
          EV_DOC, "和破解代码的程序",
          applicability="conditional", rule="applicability:v2_n_4_5:emergency"),
        a("table[4]/row[14]", "direct_crf_source", A4,
          ["v2_n_12_2", "v2_n_12_6"],
          "标识直接记录在CRF上、无先前书面/电子记录即视为源数据的数据项。",
          EV_DOC, "直接记录在CRF上的任何数据的标识"),
        a("table[4]/row[15]", "iit_reference", DT,
          ["v2_n_14_2", "v2_n_14_4"],
          "研究者发起的多中心研究引用的IIT指导原则可定位；非IIT研究该项不适用，不得标记为普遍缺陷。",
          "IIT指导原则的目标对象登记。", "请参阅IIT的相关指导原则",
          applicability="conditional", flags=("reference_hint",),
          check_ref="qc.r03:internal_cross_reference",
          note="检查函数已实现但适用条件（IIT且多中心）未接线；接线前不对真实文档运行。"),
        a("table[4]/row[16]", "ctq_identification", A4,
          ["v2_n_14_1"],
          "方案识别关键质量因素（CtQ）。",
          EV_FACT, "识别关键质量因素（CtQ）"),
        a("table[4]/row[16]", "proportionate_controls", A4,
          ["v2_n_14_1"],
          "制定与风险相称的控制措施。",
          EV_DOC, "与风险相称的控制措施"),
        a("table[4]/row[16]", "critical_handling", A4,
          ["v2_n_6_2_4", "v2_n_1_3"],
          "覆盖关键给药及配制操作的控制。",
          EV_DOC, "关键给药及配制操作"),
        a("table[4]/row[16]", "critical_time_windows", A4,
          ["v2_n_1_3"],
          "覆盖关键访视及评估时间窗的控制。",
          EV_DOC, "关键访视及评估时间窗"),
        a("table[4]/row[16]", "individual_stop", A4,
          ["v2_n_8_1", "v2_n_14_7"],
          "覆盖个体层面暂停或终止规则。",
          EV_DOC, "个体及全试验层面的暂停或终止规则",
          rule="applicability:n-8-1:individual-hold"),
        a("table[4]/row[16]", "trial_stop", A4,
          ["v2_n_14_7"],
          "覆盖全试验层面暂停或终止规则；不默认绑定到期中分析。",
          EV_DOC, "个体及全试验层面的暂停或终止规则",
          rule="applicability:n-8-1:hold-to-stop"),
        a("table[4]/row[16]", "dose_adjustment", A4,
          ["v2_n_6_1_2"],
          "给出剂量调整标准；是否需要具体调整方案由研究事实决定，不复用其他药物数值。",
          EV_FACT, "及剂量调整标准",
          applicability="conditional", rule="applicability:n-6-1-2:dose-modification"),
    ]

    # -- table 5: 6.5 选择和退出 ---------------------------------------------
    atoms += [
        a("table[5]/row[2]", "inclusion_criteria", A4,
          ["v2_n_5_1"],
          "给出试验参与者入选标准，与研究人群事实同一版本。",
          EV_FACT, "试验参与者入选标准"),
        a("table[5]/row[3]", "exposure_criteria", A4,
          ["v2_n_5_2"],
          "给出试验参与者暴露标准。",
          EV_DOC, "试验参与者暴露标准",
          note="源词为“暴露标准”；规范化为排除标准需独立出处，本注册表保留源词不改写。"),
        a("table[5]/row[4]", "eligibility_determination", A4,
          ["v2_n_5_1", "v2_n_5_2", "v2_n_7_1"],
          "描述如何确定合格标准。",
          EV_DOC, "描述如何确定合格标准"),
        a("table[5]/row[5]", "subject_reported_info", A4,
          ["v2_n_7_1", "v2_n_12_2"],
          "说明合格性判定中试验参与者报告的信息。",
          EV_DOC, "试验参与者报告的信息"),
        a("table[5]/row[6]", "medical_records_review", A4,
          ["v2_n_7_1", "v2_n_12_2"],
          "说明合格性判定中的病历审查。",
          EV_DOC, "病历审查"),
        a("table[5]/row[7]", "screening_assessments", A4,
          ["v2_n_7_1", "v2_n_9_1", "v2_n_9_2"],
          "说明筛查评估结果（如问卷、日记等）在合格性判定中的使用。",
          EV_DOC, "筛查评估结果（如问卷、日记等）"),
        a("table[5]/row[8]", "withdrawal_standards", A4,
          ["v2_n_8_1", "v2_n_8_2"],
          "给出试验参与者退出标准（终止试验药物治疗/试验治疗）和程序规定。",
          EV_DOC, "试验参与者退出标准（即终止试验药物治疗/试验治疗）"),
        a("table[5]/row[9]", "situation_stop_treatment", A4,
          ["v2_n_8_1", "v2_n_8_2"],
          "情形（1）：明确参与者停止试验干预但继续随访的安排。",
          EV_DOC, "（1）试验参与者停止试验干预但继续随访"),
        a("table[5]/row[9]", "situation_withdraw_consent", A4,
          ["v2_n_8_2", "v2_n_13_2"],
          "情形（2）：明确参与者自主退出试验（撤回知情同意）的安排。",
          EV_DOC, "（2）试验参与者自主退出试验（撤回知情同意）"),
        a("table[5]/row[9]", "situation_investigator_termination", A4,
          ["v2_n_8_1", "v2_n_11_3"],
          "情形（3）：明确研究者决定终止其参加试验的安排。",
          EV_DOC, "（3）研究者决定终止其参加试验"),
        a("table[5]/row[9]", "data_collection", A4,
          ["v2_n_8_2", "v2_n_7_3", "v2_n_12_6"],
          "分别明确各情形下数据收集类型和时间。",
          EV_DOC, "各情形下的数据收集类型、时间"),
        a("table[5]/row[9]", "medical_followup", A4,
          ["v2_n_8_1", "v2_n_8_2"],
          "分别明确各情形下医学随访安排。",
          EV_DOC, "数据收集类型、时间、医学随访"),
        a("table[5]/row[9]", "existing_data", A4,
          ["v2_n_12_6"],
          "明确各情形下已收集数据的处理。",
          EV_DOC, "已收集数据处理"),
        a("table[5]/row[9]", "replacement", A4,
          ["v2_n_8_2", "v2_n_11_1"],
          "明确试验参与者替换规则；与表[5]/row[13]的独立替换行互为相关义务。",
          EV_DOC, "及试验参与者替换规则"),
        a("table[5]/row[10]", "rejection_reaction", A4,
          ["v2_n_8_1", "v2_n_9_2"],
          "原文问句所述情形（排斥反应）的处理安排：缺少清楚适用语境，按source ambiguity处理；"
          "具体研究语境下由语义审阅裁定该情形应当如何处置，并核对正文是否已覆盖。",
          EV_DOC + "语境判定由Agent④完成。", "如果试验参与者发生排斥反应怎么办",
          applicability="unknown_context", flags=("source_ambiguity",),
          note="原文保留“排斥反应”，不替它改写为妊娠/过敏/输血反应等其他医学概念，"
               "也不设为所有方案必须出现的自动门槛；候选节点仅用于定位，不等于已裁定医学含义。"),
        a("table[5]/row[11]", "excluded_medication", A4,
          ["v2_n_6_4_1", "v2_n_8_1"],
          "明确参与者开始服用排除药物时的处理。",
          EV_DOC, "如果试验参与者开始服用排除药物怎么办"),
        a("table[5]/row[12]", "withdrawal_procedure", A4,
          ["v2_n_8_2", "v2_n_7_3", "v2_n_12_2"],
          "给出研究退出程序的详细描述，含退出参与者数据收集的类型和时间。",
          EV_DOC, "研究退出程序的详细描述"),
        a("table[5]/row[13]", "replacement_rule", A4,
          ["v2_n_8_2", "v2_n_11_1"],
          "说明是否以及如何替换试验参与者。",
          EV_DOC, "是否以及如何替换试验参与者"),
        a("table[5]/row[14]", "post_discontinuation_followup", A4,
          ["v2_n_8_1", "v2_n_7_3"],
          "给出退出试验药物治疗/试验治疗后的随访安排。",
          EV_DOC, "试验参与者退出试验药物治疗/试验治疗的随访"),
    ]

    # -- table 6: 6.6 治疗 ---------------------------------------------------
    atoms += [
        a("table[6]/row[2]", "treatments", A4,
          ["v2_n_6_1_1", "v2_n_6_1_2", "v2_n_7_3"],
          "给出各组要给予的治疗：产品名称、剂量、给药计划、途径/模式和治疗期。",
          EV_FACT, "要给予的治疗，包括所有产品的名称"),
        a("table[6]/row[2]", "treatment_followup_periods", A4,
          ["v2_n_7_3"],
          "给出各组试验参与者的随访期。",
          EV_FACT, "各试验药物治疗/试验治疗组/试验组试验参与者的随访期"),
        a("table[6]/row[3]", "allowed_medications", A4,
          ["v2_n_6_4_2", "v2_n_6_4_3"],
          "给出允许使用的药物/治疗（含急救药物）。",
          EV_DOC, "允许使用的药物/治疗（包括急救药物）"),
        a("table[6]/row[3]", "prohibited_medications", A4,
          ["v2_n_6_4_1"],
          "给出试验前和/或试验期间不允许使用的药物/治疗。",
          EV_DOC, "试验前和/或试验期间不允许使用"),
        a("table[6]/row[4]", "adherence_monitoring", A4,
          ["v2_n_6_3"],
          "给出监测试验参与者依从性的程序。",
          EV_DOC, "监测试验参与者依从性的程序"),
    ]

    # -- table 7: 6.7 疗效评估 ----------------------------------------------
    atoms += [
        a("table[7]/row[2]", "efficacy_quality_criteria", A4,
          ["v2_n_3_1_2_2", "v2_n_9_1"],
          "给出有效性参数的质量标准。",
          EV_DOC, "有效性参数的质量标准"),
        a("table[7]/row[3]", "efficacy_methods_timing", A4,
          ["v2_n_9_1", "v2_n_1_3", "v2_n_11_4_3_1", "v2_n_11_4_4"],
          "给出疗效参数评估、记录和分析的方法和时间。",
          EV_DOC, "评估、记录和分析疗效参数的方法和时间"),
    ]

    # -- table 8: 6.8 安全性评估 --------------------------------------------
    atoms += [
        a("table[8]/row[2]", "safety_parameters", A4,
          ["v2_n_9_2", "v2_n_3_3_2"],
          "给出安全参数规范。",
          EV_DOC, "安全参数规范"),
        a("table[8]/row[3]", "safety_methods_timing", A4,
          ["v2_n_9_2", "v2_n_1_3", "v2_n_11_4_5"],
          "给出安全性参数评估、记录和分析的方法和时间。",
          EV_DOC, "评估、记录和分析安全性参数的方法和时间"),
        a("table[8]/row[4]", "ae_recording_reporting", A4,
          ["v2_n_10_1_4", "v2_n_10_1_5", "v2_n_10_2_2"],
          "给出不良事件和并发疾病的记录和报告程序。",
          EV_DOC, "记录和报告不良事件和并发疾病的程序"),
        a("table[8]/row[5]", "ae_followup_duration", A4,
          ["v2_n_10_1_6", "v2_n_10_2_3", "v2_n_10_3_3"],
          "给出不良事件后随访的类型和持续时间。",
          EV_DOC, "不良事件后试验参与者随访的类型和持续时间"),
        a("table[8]/row[6]", "committee_duties", A4,
          ["v2_n_9_4", "v2_n_14_7"],
          "设置IDMC/DMC、CEC或SRC时，方案或其引用文件明确其职责；未设置委员会时按适用性处理，不构成缺陷。",
          EV_DOC, "独立数据监查委员会（IDMC/DMC）",
          applicability="conditional", rule="applicability:n-14-7:oversight-charter"),
        a("table[8]/row[6]", "committee_procedures", A4,
          ["v2_n_9_4", "v2_n_14_7"],
          "设置相应委员会时，明确其工作程序。",
          EV_DOC, "其职责、工作程序",
          applicability="conditional", rule="applicability:n-14-7:oversight-charter"),
        a("table[8]/row[6]", "committee_decision_interface", A4,
          ["v2_n_9_4", "v2_n_14_7"],
          "设置相应委员会时，明确其与申办者/研究团队的决策接口。",
          EV_DOC, "及决策接口",
          applicability="conditional", rule="applicability:n-14-7:oversight-charter"),
        a("table[8]/row[6]", "ae_followup", A4,
          ["v2_n_10_1_6", "v2_n_14_7"],
          "明确不良事件的随访周期与要求；该义务不因未设置委员会而被免除。",
          EV_DOC, "是否明确不良事件及妊娠等特定事件的随访周期与要求"),
        a("table[8]/row[6]", "specific_event_followup", A4,
          ["v2_n_10_6"],
          "研究存在妊娠等相应特定事件适用性时，明确该类事件的随访周期与要求；"
          "该义务独立于委员会设置：设置委员会不替代它，未设置委员会也不免除它。"
          "研究无相应事件适用性时按适用性处理；适用性未知保持未决，不当false。",
          "研究特定事件适用性事实（如妊娠风险/妊娠队列安排）与正文随访安排投影；"
          "以研究自身事件适用性为准，不复用避孕排除等其他规则冒充已接线。",
          "妊娠等特定事件的随访周期与要求",
          applicability="conditional",
          note="科学性修正（owner failed-acceptance 2026-09-13）：委员会独立性"
               "不等于普遍适用；特殊事件随访以研究相应事件适用性为条件。当前无"
               "可复用的已登记事件适用性规则ID，保持not_wired；未知未决，"
               "不当false，源义务不删除。本registry不声称已执行运行时适用性判定。"),
    ]

    # -- table 9: 6.9 统计 ---------------------------------------------------
    atoms += [
        a("table[9]/row[2]", "statistical_methods", A4,
          ["v2_n_11_3", "v2_n_11_4_3_1", "v2_n_11_4_9"],
          "描述要采用的统计方法，与估计目标及终点一致。",
          EV_DOC, "描述要采用的统计方法"),
        a("table[9]/row[2]", "interim_timing", A4,
          ["v2_n_11_4_9", "v2_n_14_7"],
          "计划中期分析时给出其时间；无期中分析时按适用性处理，不要求虚构时点/信息量/alpha消耗表。",
          EV_FACT, "包括任何计划的中期分析的时间",
          applicability="conditional", rule="conditional:v2-n-11-4-9:interim"),
        a("table[9]/row[3]", "planned_sample_size", DT,
          ["v2_n_11_1", "v2_n_4_1"],
          "给出计划入组参与者数量；该数值可由研究事实复算。",
          "样本量事实投影与正文数值复算。", "计划入组的试验参与者数量"),
        a("table[9]/row[3]", "multicenter_distribution", A4,
          ["v2_n_11_1", "v2_n_4_1"],
          "多中心试验给出各中心预计入组人数；未确定中心名单时不虚构中心或人数，中心分布表达按实际安排审阅。",
          EV_FACT, "每个试验中心预计入组的试验参与者人数",
          applicability="conditional"),
        a("table[9]/row[3]", "sample_size_justification", A4,
          ["v2_n_11_1"],
          "给出样本量选择原因，含试验效力考虑（或计算）。",
          EV_DOC, "选择样本量的原因，包括试验效力的反思（或计算）"),
        a("table[9]/row[3]", "clinical_rationale", A4,
          ["v2_n_11_1"],
          "给出样本量的临床依据。",
          EV_DOC, "和临床依据"),
        a("table[9]/row[4]", "significance_level", DT,
          ["v2_n_11_3", "v2_n_11_4_8"],
          "给出要使用的显著性水平，与统计方法及多重性考虑一致。",
          EV_DOC, "要使用的显著性水平"),
        a("table[9]/row[5]", "termination_criteria", A4,
          ["v2_n_11_4_9", "v2_n_14_7", "v2_n_8_1"],
          "给出统计层面的试验终止标准；与6.4.6停止规则相关但不相互替代。",
          EV_DOC, "试验终止标准"),
        a("table[9]/row[6]", "missing_data_handling", A4,
          ["v2_n_11_3", "v2_n_11_4_3_1", "v2_n_11_4_3_2", "v2_n_12_3"],
          "说明缺失、未使用和虚假数据的处理程序。",
          EV_DOC, "说明缺失、未使用和虚假数据的程序"),
        a("table[9]/row[7]", "sap_creation", A4,
          ["v2_n_11_3", "v2_n_12_5"],
          "明确要求制定统计分析计划（SAP）。",
          EV_DOC, "是否明确要求制定统计分析计划（SAP）"),
        a("table[9]/row[7]", "sap_approval_timing", DT,
          ["v2_n_12_5"],
          "明确SAP在数据库锁定和揭盲前批准的安排；这是将来时点安排，不等于已有批准事实，不伪造签署或批准。",
          EV_DOC, "并在数据库锁定和揭盲前批准"),
        a("table[9]/row[7]", "sap_deviation_reporting", A4,
          ["v2_n_11_3", "v2_n_12_5"],
          "声明对SAP的任何偏离将在临床试验报告中如实记录和解释。",
          EV_DOC, "如实记录和解释"),
        a("table[9]/row[8]", "analysis_sets", A4,
          ["v2_n_11_2"],
          "给出纳入分析的试验参与者选择（分析集）。",
          EV_DOC, "选择纳入分析的试验参与者"),
    ]

    # -- table 10: 6.10 直接访问 ---------------------------------------------
    atoms += [
        a("table[10]/row[2]", "direct_access_parties", A4,
          ["v2_n_14_3", "v2_n_14_4", "v2_n_14_5", "v2_n_12_8"],
          "方案或书面协议明确研究者、临床试验机构及持有源记录的服务供应商允许直接查阅源数据和源记录。",
          EV_DOC + "以外部协议承载时须引用已核实文件。", "研究者、临床试验机构及持有源记录的服务供应商"),
        a("table[10]/row[2]", "direct_access_purposes", A4,
          ["v2_n_14_3", "v2_n_14_5", "v2_n_12_8"],
          "查阅目的覆盖试验相关监查、稽查、药品监管检查及依适用法规开展的伦理审查。",
          EV_DOC, "试验相关监查、稽查、药品监管检查"),
    ]

    # -- table 11: 6.11 质量控制 ---------------------------------------------
    atoms += [
        a("table[11]/row[2]", "quality_management_method", A4,
          ["v2_n_14_1"],
          "阐明基于关键质量因素的质量管理方法。",
          EV_DOC, "基于关键质量因素的质量管理方法"),
        a("table[11]/row[2]", "monitoring_strategy", A4,
          ["v2_n_14_3"],
          "阐明与风险相称的监查策略（如中心化与现场监查结合）；具体组合由项目安排决定。",
          EV_FACT, "与风险相称的监查策略（如中心化与现场监查结合）"),
        a("table[11]/row[2]", "noncompliance_identification", A4,
          ["v2_n_14_6"],
          "给出方案/GCP不依从事件的识别机制。",
          EV_DOC, "不依从事件的识别"),
        a("table[11]/row[2]", "cause_analysis", A4,
          ["v2_n_14_6"],
          "给出不依从事件的原因分析安排。",
          EV_DOC, "原因分析"),
        a("table[11]/row[2]", "capa", A4,
          ["v2_n_14_6"],
          "给出纠正预防措施（CAPA）安排；出现缩写本身不构成通过，须有实际机制描述。",
          EV_DOC, "纠正预防（CAPA）"),
        a("table[11]/row[2]", "reporting_mechanism", A4,
          ["v2_n_14_6"],
          "给出不依从事件的报告机制。",
          EV_DOC, "与报告机制"),
    ]

    # -- table 12: 6.12 伦理 --------------------------------------------------
    atoms += [
        a("table[12]/row[2]", "ethics_description", A4,
          ["v2_n_13_1", "v2_n_13_2", "v2_n_13_3", "v2_n_13_4"],
          "给出与试验相关的伦理考虑描述。",
          EV_DOC, "与试验相关的伦理考虑的描述"),
    ]

    # -- table 13: 6.13 数据治理 ---------------------------------------------
    atoms += [
        a("table[13]/row[2]", "data_collection_set", A4,
          ["v2_n_12_1", "v2_n_12_2"],
          "明确拟采集数据的集合。",
          EV_DOC, "是否明确拟采集数据"),
        a("table[13]/row[2]", "data_sources", A4,
          ["v2_n_12_2"],
          "明确数据来源。",
          EV_DOC, "数据来源及直接录入数据采集工具的源数据"),
        a("table[13]/row[2]", "direct_entry_source", A4,
          ["v2_n_12_2"],
          "明确直接录入数据采集工具的源数据。",
          EV_DOC, "直接录入数据采集工具的源数据"),
        a("table[13]/row[2]", "electronic_source_records", A4,
          ["v2_n_12_2", "v2_n_12_6"],
          "明确电子原始记录不得仅以打印件替代。",
          EV_DOC, "电子原始记录不得仅以打印件替代"),
        a("table[13]/row[2]", "computerized_systems", A4,
          ["v2_n_12_6"],
          "明确计算机化系统具备适度验证、用户权限、稽查轨迹及备份安全。",
          EV_DOC, "计算机化系统是否具备适度验证、用户权限、稽查轨迹及备份安全",
          note="本条是临床方案的数据治理正文义务；不扩展为本工作台软件安全工程。"),
        a("table[13]/row[2]", "record_retention", A4,
          ["v2_n_12_8"],
          "明确试验必备记录按规定妥善保存及可追溯。",
          EV_DOC, "试验必备记录按规定妥善保存及可追溯"),
        a("table[13]/row[2]", "medical_record_extraction", A4,
          ["v2_n_12_2"],
          "识别将从医疗记录中提取的信息。",
          EV_DOC, "识别将从医疗记录中提取的信息"),
    ]

    # -- tables 14-16 ---------------------------------------------------------
    atoms += [
        a("table[14]/row[2]", "funding", A4,
          ["v2_n_13_4", "v2_n_14_2"],
          "单独协议未提及经费安排时，方案提供融资安排；以已核实引用承载时可指向协议，未知不得按“已在协议中处理”自动不适用。",
          EV_DOC, "如果在单独协议中未提及，则提供融资和保险",
          applicability="conditional"),
        a("table[14]/row[2]", "insurance", A4,
          ["v2_n_13_4"],
          "单独协议未提及保险安排时，方案提供保险安排；未知不得自动不适用。",
          EV_DOC, "如果在单独协议中未提及，则提供融资和保险",
          applicability="conditional"),
        a("table[15]/row[2]", "publication_policy", A4,
          ["v2_n_12_9"],
          "单独协议未处理出版政策时，方案给出出版政策；未知不得自动不适用。",
          EV_DOC, "出版政策，如果未在单独协议中处理",
          applicability="conditional"),
        a("table[16]/row[2]", "csr_reference_hint", A4,
          ["v2_n_15"],
          "源行是关于方案与临床试验报告结构/内容指南相关的参考提示；保留原文，不生成方案正文必填义务，也不作为普遍内容检查门槛。",
          "无（参考提示）。", "更多相关信息见Lal临床结构和内容指南研究报告",
          flags=("reference_hint", "source_noise"),
          note="源文含乱码（“Lal临床结构和内容指南研究报告。”），原文在raw区保留；规范化表述不复制乱码。"),
    ]

    # -- header-embedded recruitment fragment atom ---------------------------
    atoms.append(
        a("table[5]/row[0]/cell[1]", "recruitment_method", A4,
          ["v2_n_5_5"],
          "描述试验参与者识别和招募方法（表头内嵌义务，独立于68条内容行分母）。",
          EV_DOC, "试验参与者识别和招募方法",
          flags=("header_embedded",),
          note="该义务物理上位于T5/R0表头描述列内；单独保留，既不丢失也不计入68内容行。"),
    )
    return atoms


# Normalized obligation text must never carry source noise; "note" is
# provenance documentation and may mention the noise marker verbatim.
NOISE_FREE_FIELDS = ("normalized_check", "evidence_requirement")


def _validate_generation(data: dict) -> None:
    rows = data["source_rows"]
    index = row_text_index(rows)
    for atom in data["criteria"]:
        locator = atom["source_locator"]
        if locator.endswith("cell[1]"):
            haystack = next(
                f["raw_text"] for f in data["header_embedded_fragments"]
            )
        else:
            if locator not in index:
                raise RegistrySourceError(f"atom locator unknown: {locator}")
            haystack = index[locator]
        if norm(atom["raw_fragment"]) not in norm(haystack):
            raise RegistrySourceError(
                f"raw_fragment not found in source for {atom['atom_id']}"
            )
        for field in NOISE_FREE_FIELDS:
            for marker in SOURCE_NOISE_MARKERS:
                if marker in atom[field]:
                    raise RegistrySourceError(
                        f"source noise {marker!r} leaked into {field} of "
                        f"{atom['atom_id']}"
                    )
    covered = {
        atom["source_locator"] for atom in data["criteria"]
        if not atom["source_locator"].endswith("cell[1]")
    }
    for row in rows:
        if row["row_kind"] != "content":
            continue
        if row_locator(row) not in covered:
            raise RegistrySourceError(
                f"content row {row_locator(row)} has no atom"
            )
    _validate_semantic_nodes(data)
    _validate_rule_refs(data)


def _validate_semantic_nodes(data: dict) -> None:
    node_tree = json.loads(NODE_TREE_PATH.read_text(encoding="utf-8"))
    known = {
        node["id"]
        for tree in ("heading_style_tree", "outlined_tree")
        for node in (node_tree.get(tree, {}).get("nodes") or [])
    }
    if node_tree.get("front_block"):
        known.add("v2_front_block")
    for atom in data["criteria"]:
        for node_id in atom["semantic_node_ids"]:
            if node_id not in known:
                raise RegistrySourceError(
                    f"unknown semantic node {node_id} in {atom['atom_id']}"
                )


def _validate_rule_refs(data: dict) -> None:
    rules = json.loads(APPLICABILITY_RULES_PATH.read_text(encoding="utf-8"))
    known = {rule["rule_id"] for rule in rules.get("rules", [])}
    for atom in data["criteria"]:
        rule_ref = atom["applicability"].get("rule_ref")
        if rule_ref is not None and rule_ref not in known:
            raise RegistrySourceError(
                f"unknown applicability rule {rule_ref} in {atom['atom_id']}"
            )


# ---------------------------------------------------------------------------
# Registry assembly (deterministic)
# ---------------------------------------------------------------------------

L1_CHECKS = [
    {
        "id": "l1_version_four_point",
        "name": "版本四点一致",
        "implemented": True,
        "wiring": "typed_input_only",
        "check_ref": "qc.r03:version_four_point",
        "notes": [
            "当前版本须与各当前位置（封面/文档控制区/QC表身份栏）一致；修订历史旧行合法保留旧值，不参与当前一致性比较。",
            "真实文档投影与产品消费者属V1接线，当前仅对typed输入负责。",
        ],
    },
    {
        "id": "l1_abbreviation_closure",
        "name": "缩略语闭环",
        "implemented": False,
        "wiring": "pending",
        "check_ref": None,
        "pending_reason": "缩略语集合须从实际正文生成并与权威术语条目绑定；全称医学正确不能凭字符串非空判定（3R.7术语库接线）。",
    },
    {
        "id": "l1_literature_bidirectional",
        "name": "文献双向",
        "implemented": False,
        "wiring": "pending",
        "check_ref": None,
        "pending_reason": "双向闭合与日期识别不等于证据仍适用；文献是否被替代、适用对象是否匹配由来源/语义复核提供证据，不用年份阈值冒充时效性验收。",
    },
    {
        "id": "l1_textual_cross_reference",
        "name": "文字性交叉引用",
        "implemented": True,
        "wiring": "typed_input_only",
        "check_ref": "qc.r03:internal_cross_reference",
        "notes": [
            "以明确目标对象清单为准解析文字引用，不以“含数字”冒充引用检查；缺目标显式失败。",
            "真实文档投影V1接线。",
        ],
    },
    {
        "id": "l1_numbers_units",
        "name": "数字单位",
        "implemented": False,
        "wiring": "pending",
        "check_ref": None,
        "pending_reason": "数值复算需绑定研究事实投影（样本量/显著性水平等）；单位规范检查未实现，不得用正则匹配冒充医学正确。",
    },
    {
        "id": "l1_registration_consistency",
        "name": "登记一致性",
        "implemented": False,
        "wiring": "pending",
        "check_ref": None,
        "pending_reason": "先核实实际适用登记源和版本；尚无已登记材料时不得生成“已登记一致”回执；字段结构相等与入排医学语义等价须分别登记。",
    },
]

WIRED_CHECKS = [
    {
        "check_ref": "qc.r03:version_four_point",
        "module": "services/api/app/protocol_workflow/qc/r03.py",
        "function": "check_version_consistency",
        "input_type": "R03VersionMaterial",
        "wiring": "typed_input_only",
    },
    {
        "check_ref": "qc.r03:internal_cross_reference",
        "module": "services/api/app/protocol_workflow/qc/r03.py",
        "function": "check_internal_citations",
        "input_type": "R03CitationMaterial",
        "wiring": "typed_input_only",
    },
]

PRODUCT_WIRING = {
    "generation_model": "not_wired_v1",
    "word_export": "not_wired_v1",
    "ui_consumers": "not_wired_v1",
    "document_projection": "pending",
    "note": "已实现的两个确定性检查只对typed输入负责；生成模型、原生Word与UI消费者的实际接线及全量核对属V1/V1.5，本注册表不声称已接。",
}

HUMAN_CONFIRMATIONS = [
    {
        "ref": "confirm_contact_entities",
        "description": "申办者/监查员/医学专家/研究者/医学决策医师/实验室与机构等实体信息的真实性与已确认研究事实一致。",
        "eight_card_mapping": "pending_v1",
    },
    {
        "ref": "confirm_signature_authority",
        "description": "签署授权的真实性与最终签署事实；签署控件保持空白，正式签署回执属V1。",
        "eight_card_mapping": "pending_v1",
    },
]


def build_registry(source_path: Path | str = SOURCE_DOCX_PATH,
                   out_path: Path | str = DEFAULT_OUT_PATH) -> Path:
    verify_source_hash(source_path)
    source_path = Path(source_path)
    rows = extract_source_rows(source_path)
    for row in rows:
        row["row_kind"] = row_kind(row["table_index"], row["row_index"])

    counts = {"identity": 0, "header": 0, "content": 0}
    for row in rows:
        counts[row["row_kind"]] += 1
    if (len(rows), counts["identity"], counts["header"], counts["content"]) != (
        104, 4, 32, 68
    ):
        raise RegistrySourceError(
            f"source denominator drifted: {len(rows)} rows {counts}"
        )

    criteria = _criteria()
    # attach verbatim source labels from the actual rows (never hand-copied)
    labels = {
        row_locator(row): _cell_text(row, 0).strip()
        for row in rows
    }
    for atom in criteria:
        locator = atom["source_locator"]
        if locator.endswith("cell[1]"):
            atom["source_label"] = ""
            atom["atom_id"] = f"r03-t05-r00hdr-{atom['sub_key']}"
            continue
        atom["source_label"] = labels[locator]
        locator_inner = locator[len("table["):-1]
        t, r = locator_inner.split("]/row[")
        atom["atom_id"] = f"r03-t{int(t):02d}-r{int(r):02d}-{atom['sub_key']}"

    seen = set()
    for atom in criteria:
        if atom["atom_id"] in seen:
            raise RegistrySourceError(f"duplicate atom id {atom['atom_id']}")
        seen.add(atom["atom_id"])

    by_category: dict[str, int] = {
        c: 0 for c in ("deterministic", "agent4", "human")
    }
    by_status = {"implemented": 0, "pending": 0}
    for atom in criteria:
        by_category[atom["check_category"]] += 1
        by_status[atom["implementation_status"]] += 1

    flags_count: dict[str, int] = {}
    for atom in criteria:
        for flag in atom["flags"]:
            flags_count[flag] = flags_count.get(flag, 0) + 1

    fragment = extract_header_fragment(rows)
    data = {
        "schema_version": SCHEMA_VERSION,
        "template_id": TEMPLATE_ID,
        "status": "registered_not_accepted",
        "source": [
            {
                "path": str(source_path),
                "sha256": EXPECTED_SHA256,
                "source_member": "word/document.xml",
                "owner": "clinical_template_authority",
                "allowed": "read_only",
                "authority_role": "qc_or_sop_reference",
            }
        ],
        "denominator": {
            "physical_tables": 17,
            "physical_rows": len(rows),
            "identity_rows": counts["identity"],
            "repeated_header_rows": counts["header"],
            "source_content_rows": counts["content"],
            "header_embedded_fragments": 1,
            "atomic_obligations": len(criteria),
            "atomic_by_category": by_category,
            "atomic_by_status": by_status,
            "atomic_by_flags": flags_count,
            "note": (
                "68内容行是源覆盖分母，不是原子检查总数；每条内容行至少有一个原子义务，复合行拆成多个。"
            ),
        },
        "identity_fields": extract_identity_fields(rows),
        "header_embedded_fragments": [fragment],
        "signature_area": extract_signature_area(rows, source_path),
        "source_rows": rows,
        "criteria": criteria,
        "human_confirmations": HUMAN_CONFIRMATIONS,
        "l1_checks": L1_CHECKS,
        "wired_checks": WIRED_CHECKS,
        "product_wiring": PRODUCT_WIRING,
        "status_note": (
            "本注册表是R03源义务的结构化登记，不是已接受医学registry：逐原子医学充分性、"
            "适用性判定与正式人工确认仍未执行；注册不等于通过。"
        ),
    }
    _validate_generation(data)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    out_path.write_bytes(payload.encode("utf-8"))
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=SOURCE_DOCX_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument(
        "--check", action="store_true",
        help="regenerate and compare bytes instead of writing",
    )
    args = parser.parse_args(argv)
    if args.check:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            generated = build_registry(args.source, Path(tmp) / "registry.json")
            expected = Path(args.out)
            if not expected.is_file():
                print(f"registry missing: {expected}")
                return 1
            if generated.read_bytes() != expected.read_bytes():
                print("registry drift: regenerated bytes differ from committed")
                return 1
        print(f"deterministic registry verified: {args.out}")
        return 0
    out = build_registry(args.source, args.out)
    print(f"registry written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
