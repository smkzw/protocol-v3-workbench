#!/usr/bin/env python3
"""Hand-written II-phase protocol synopsis for R6D-W6 CKD-aP / KRX-451."""
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

OUT = Path(__file__).with_name("R6D-W6-CKDaP-KRX451-摘要.docx")

SECTIONS = [
    (
        "一、背景与立题依据",
        "慢性肾病相关瘙痒（CKD-aP）在维持性血液透析患者中常见，严重影响睡眠与生活质量。"
        "抗组胺药、润肤剂对中重度瘙痒疗效有限。KRX-451 为外周选择性 κ 阿片受体激动剂，"
        "拟抑制外周瘙痒信号且不激动 μ 受体，从而避免呼吸抑制与依赖风险。"
        "拟在透析人群开展 II 期研究，评估口服 KRX-451 疗效与安全性。",
    ),
    (
        "二、研究目的",
        "主要目的：评价 KRX-451 2 mg 每日两次口服，较匹配安慰剂改善第 12 周周平均最重瘙痒"
        "WI-NRS 较基线变化的疗效。次要目的：评价 WI-NRS 应答、5-D 瘙痒量表、Skindex-16"
        "及 PSQI 睡眠改善，并描述治疗期与随访期安全性。",
    ),
    (
        "三、总体设计",
        "多中心、随机、双盲、安慰剂对照 II 期试验。合格者按 1:1 分入 KRX-451 2 mg bid"
        "口服组或匹配安慰剂组。双盲治疗 12 周，随后 4 周安全随访。"
        "随机分层拟包括中心及基线周平均 WI-NRS（5–<7 分与 ≥7 分）。透析日于透析开始前给药。",
    ),
    (
        "四、研究人群",
        "拟入组 18–80 岁、维持性血液透析≥3 个月且每周透析 3 次的患者。"
        "入组前 4 周周平均最重瘙痒 WI-NRS ≥5 分，且常规抗组胺药和/或润肤剂无效。"
        "主要排除活动性恶性肿瘤、κ 受体激动剂过敏、妊娠或哺乳、预期无法完成 12 周双盲治疗者。",
    ),
    (
        "五、主要终点",
        "第 12 周周平均最重瘙痒 WI-NRS 较基线的变化。基线为随机前 7 天每日最重瘙痒均值；"
        "第 12 周周平均为第 12 周对应 7 天评分均值。",
    ),
    (
        "六、次要终点",
        "第 12 周 WI-NRS 较基线改善≥4 分的应答率；5-D 瘙痒量表总分变化；"
        "Skindex-16 总分及症状、情绪、功能维度变化；PSQI 较基线变化。"
        "探索性终点包括透析日与非透析日瘙痒差异。",
    ),
    (
        "七、统计考虑",
        "全分析集为主要分析集。主要终点用协方差分析，协变量含基线 WI-NRS 及分层因素。"
        "应答率用分层 CMH 检验。按组间差 1.5 分、标准差 3.0、把握度 80%、双侧 α=0.05 估算，"
        "计入15%脱落，拟随机120例。",
    ),
    (
        "八、安全性关注",
        "全程收集不良事件、生命体征、实验室检查及心电图。重点关注头晕、嗜睡、口干、恶心、"
        "透析中低血压、肝酶升高及电解质紊乱。允许按规定使用救援治疗并记录。",
    ),
]


def _set_run_font(run, size_pt: int, bold: bool = False) -> None:
    run.bold = bold
    run.font.size = Pt(size_pt)
    run.font.name = "Songti SC"
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), "宋体")


def main() -> None:
    doc = Document()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(
        "R6D-W6-CKDaP-KRX451 方案摘要\n"
        "KRX-451 治疗维持性血液透析患者慢性肾病相关瘙痒的 II 期研究"
    )
    _set_run_font(run, 16, bold=True)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    mrun = meta.add_run("适应症：CKD-aP（非肿瘤）　分期：II 期　研究药物：KRX-451 2 mg bid 口服")
    _set_run_font(mrun, 11)

    body_chars = 0
    for heading, body in SECTIONS:
        hp = doc.add_paragraph()
        hr = hp.add_run(heading)
        _set_run_font(hr, 14, bold=True)
        bp = doc.add_paragraph()
        br = bp.add_run(body)
        _set_run_font(br, 12)
        body_chars += len(body)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUT)
    print(f"wrote {OUT}")
    print(f"body_chars={body_chars}")
    print(f"section_count={len(SECTIONS)}")
    if not (600 <= body_chars <= 900):
        raise SystemExit(f"body_chars out of range: {body_chars}")


if __name__ == "__main__":
    main()
