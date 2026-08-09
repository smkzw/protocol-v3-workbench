from __future__ import annotations

import re


M11_HEADING_PATTERNS = {
    "front_matter": re.compile(
        r"(?:\b(?:title page|signature page|list of abbreviations|table of contents)\b|"
        r"封面|首页|签字页|缩略语表|目录)",
        re.I,
    ),
    "synopsis": re.compile(
        r"(?:\b(?:synopsis|protocol summary|study overview)\b|方案摘要|研究摘要|方案概述)",
        re.I,
    ),
    "objectives_endpoints": re.compile(
        r"(?:\b(?:objectives?|endpoints?|outcomes?|estimands?|primary efficacy variable)\b|研究目的|研究目标|研究终点|疗效终点|估计目标)",
        re.I,
    ),
    "eligibility": re.compile(
        r"(?:\b(?:inclusion|exclusion|eligibility|participant selection|study population)\b|入选标准|纳入标准|排除标准|受试者选择|试验参与者选择|研究人群)",
        re.I,
    ),
    "schedule": re.compile(
        r"(?:\b(?:schedule of activities|schedule of assessments|study schedule|visit schedule)\b|研究流程表|研究流程|(?:临床研究)?阶段流程表|访视流程表|访视和评估计划|研究评估流程)",
        re.I,
    ),
    "statistics": re.compile(
        r"(?:\b(?:statistical|sample size|analysis sets?)\b|统计学|样本量|分析集)",
        re.I,
    ),
    "rationale": re.compile(
        r"(?:\b(?:background|rationale|state of the art|research description|benefit.?risk)\b|"
        r"研究背景|研究依据|研究理由|获益.?风险)",
        re.I,
    ),
    "study_design": re.compile(
        r"(?:\b(?:study design|trial design|general study design|detailed research protocol)\b|"
        r"研究设计|试验设计|总体设计)",
        re.I,
    ),
    "intervention": re.compile(
        r"(?:\b(?:study medication|study intervention|investigational product|"
        r"treatment regimen|dose and administration)\b|试验药物|研究药物|试验干预|给药方案)",
        re.I,
    ),
    "disposition": re.compile(
        r"(?:\b(?:discontinuation|withdrawal|end of treatment|end of study)\b|"
        r"停止治疗|退出研究|提前终止|研究结束)",
        re.I,
    ),
    "assessments": re.compile(
        r"(?:\b(?:study assessments?|efficacy assessments?|laboratory assessments?|"
        r"study visits?)\b|研究评估|疗效评估|实验室检查|研究访视)",
        re.I,
    ),
    "safety": re.compile(
        r"(?:\b(?:safety|adverse events?|serious adverse events?)\b|安全性|不良事件|严重不良事件)",
        re.I,
    ),
    "data_management": re.compile(
        r"(?:\b(?:data collection|data management|source data|case report forms?)\b|"
        r"数据收集|数据管理|源数据|病例报告表)",
        re.I,
    ),
    "ethics_governance": re.compile(
        r"(?:\b(?:ethics?|informed consent|quality management|monitoring|publication policy)\b|"
        r"伦理|知情同意|质量管理|监查|发表政策)",
        re.I,
    ),
    "references": re.compile(
        r"(?:\b(?:references?|reference list|bibliography)\b|参考文献)",
        re.I,
    ),
}


def m11_anchor(text: str) -> str:
    for anchor, pattern in M11_HEADING_PATTERNS.items():
        if pattern.search(text):
            return anchor
    return "unmapped"


def m11_anchor_from_ocr_page(text: str) -> tuple[str, str]:
    """Map an OCR page from heading-like lines, not incidental body mentions."""

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    for line in lines[:20]:
        word_count = len(line.split())
        heading_like = (
            bool(re.match(r"^(?:\d+(?:\.\d+)*|[A-Z])[\.)]?\s+\S", line))
            or line.endswith(":")
            or (
                len(line) <= 180
                and word_count <= 16
                and not re.search(r"[.!?;。！？；]$", line)
            )
        )
        if not heading_like:
            continue
        anchor = m11_anchor(line)
        if anchor != "unmapped":
            return anchor, line[:500]
    return "unmapped", ""
