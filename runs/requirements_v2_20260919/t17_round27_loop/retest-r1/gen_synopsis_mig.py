# -*- coding: utf-8 -*-
"""retest-r1 测试材料：偏头痛预防性治疗 II期 CGRP受体拮抗剂（口服小分子）合成方案摘要（2-3页）
测试者本人在浏览器里以文件选择方式导入本文件；本脚本仅生成测试输入材料，不操作系统。"""
from docx import Document
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

OUT = "/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round27_loop/retest-r1/R1RT-MIG_偏头痛_CGRP受体拮抗剂_II期_方案摘要V1.docx"

doc = Document()
style = doc.styles["Normal"]
style.font.name = "Times New Roman"
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")


def h1(text):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor(0x1F, 0x3B, 0x63)
    r.font.name = "Times New Roman"
    r.element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    return p


def para(text, bold=False):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    p.paragraph_format.space_after = Pt(3)
    return p


t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("R1RT-MIG-201（CGRP受体拮抗剂口服片）预防性治疗成人偏头痛 II期临床研究方案摘要")
r.bold = True
r.font.size = Pt(15)
r.font.name = "Times New Roman"
r.element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

st = doc.add_paragraph()
st.alignment = WD_ALIGN_PARAGRAPH.CENTER
rs = st.add_run("（合成测试材料 · 方案编号 R1RT-MIG-201 · 版本 V1.0 · 2026-09-29）")
rs.font.size = Pt(9)
rs.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

h1("1. 研究背景与目的")
para("偏头痛是高致残性原发性头痛，全球患病率约14%。发作性偏头痛患者每月头痛日≥8天、生活质量显著受损时需要预防性治疗。现有预防药物（β受体阻滞剂、托吡酯、丙戊酸、抗CGRP单抗等）或因中枢副作用耐受差，或因注射给药与停药后疗效减退受限。降钙素基因相关肽（CGRP）通路是偏头痛发病机制的核心证据通路，口服小分子CGRP受体拮抗剂（gepant类）已在发作性治疗与预防领域获批同类品种，优势为口服给药、无血管收缩作用、肝毒性总体可控但需肝酶监测。")
para("R1RT-MIG-201为新型口服CGRP受体拮抗剂，I期健康受试者数据显示半衰期约11小时、食物影响可接受、未见肝酶异常信号。本研究旨在评估其在发作性偏头痛成人患者预防性治疗中的疗效、安全性与合适剂量，为III期注册研究提供剂量与设计依据。")

h1("2. 研究设计概要")
para("研究分期：II期（剂量探索+概念验证）。设计：多中心、随机、双盲、安慰剂平行对照。", bold=True)
para("计划入组约180例，按1:1:1随机至三组：R1RT-MIG-201 20 mg每日一次组、60 mg每日一次组、安慰剂组。")
para("设4周前瞻性基线期（电子头痛日记建立基线每月偏头痛日MMD与每月急性止痛药使用日），随后12周双盲治疗期，4周治疗结束后安全性随访期2周。")
para("随机分层因素：基线MMD（8–14天 vs ≥15天）、研究中心、既往预防治疗失败线数（0线 vs ≥1线）。")

h1("3. 目标人群（入排要点）")
para("入选：18–65岁；符合ICHD-3发作性偏头痛诊断（有先兆或无先兆）；筛选前≥3个月每月偏头痛日8–22天且头痛日≥15天者排除；基线期电子日记依从率≥80%；能够吞服整片药片。")
para("排除：慢性偏头痛（≥15头痛日/月持续>3个月）；筛选期或既往肝功能异常（ALT/AST>1.5×ULN）；既往使用抗CGRP单抗或gepant类药物且停药不足3个月或疗效不佳者；未控制的高血压；妊娠或哺乳期。")

h1("4. 给药方案")
para("试验药：R1RT-MIG-201片，20 mg或60 mg口服每日一次，每日固定时间给药，不受进餐影响。安慰剂：外观一致安慰剂片，每日一次。12周双盲治疗期内依从性以片剂计数与电子日记双核对，依从率80%–120%为可评估。")

h1("5. 疗效终点")
para("主要终点：治疗期第9–12周每月偏头痛日（MMD）自基线的变化。")
para("次要终点：第9–12周MMD较基线减少≥50%的应答者比例；每月急性止痛药使用日变化；头痛影响量表HIT-6总分变化；每次偏头痛发作2小时无痛率。")
para("安全性终点：治疗 emergent不良事件（TEAE）发生率与严重程度、肝功能（ALT/AST/胆红素，每4周监测）、生命体征、心电图、12导联ECG与临床实验室检查。")

h1("6. 统计分析概要")
para("样本量：主要终点MMD变化按组间差值1.2天、标准差3.5天估算，双侧α=0.05、把握度90%，并按15%脱落率放大，每组60例、共180例。")
para("主要分析：第9–12周MMD自基线变化采用混合效应重复测量模型（MMRM），固定效应含治疗组、访视、基线MMD与分层因素；多重性采用Holm程序控制三组比较族第一类错误。缺失数据在敏感性分析中采用多重插补与tipping-point分析。安全性分析采用安全性分析集（SS）描述性汇总；疗效分析采用全分析集（FAS，IT T原则）。")

h1("7. 安全性与风险管理要点")
para("特别关注不良事件（AESI）：肝功能异常（ALT/AST>3×ULN触发暂停并复测随访）、过敏反应。设安全性审查委员会（SRC）定期审查肝酶信号。育龄期女性需避孕至末次给药后2周。")

doc.save(OUT)
print("saved:", OUT)
