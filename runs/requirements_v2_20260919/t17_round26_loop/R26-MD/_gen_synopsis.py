# -*- coding: utf-8 -*-
"""R26-MD 测试材料：重度抑郁症辅助治疗 II期 NMDA受体拮抗剂鼻喷剂 合成方案摘要（2-3页）"""
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

OUT = "/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/requirements_v2_20260919/t17_round26_loop/R26-MD/R26MD_MDD_PhaseII_NMDA_Synopsis.docx"

doc = Document()

# 全局字体
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

# 标题
t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run("XS-207 鼻喷剂辅助治疗重度抑郁症 II期临床研究方案摘要")
r.bold = True
r.font.size = Pt(15)
r.font.name = "Times New Roman"
r.element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")

st = doc.add_paragraph()
st.alignment = WD_ALIGN_PARAGRAPH.CENTER
rs = st.add_run("（合成测试材料 · 方案编号 R26-SYN-002 · 版本 V1.0 · 2026-09-28）")
rs.font.size = Pt(9)
rs.font.color.rgb = RGBColor(0x80, 0x80, 0x80)

h1("1. 研究背景与 rationale")
para("重度抑郁症（MDD）患者中约三分之一对现有口服抗抑郁药（SSRI/SNRI等）充分治疗反应不佳。谷氨酸能系统尤其是NMDA受体在抑郁快速起效机制中的作用近年来获得验证，同类机制药物已在全球获批用于难治性抑郁的辅助治疗。XS-207为新型NMDA受体拮抗剂鼻喷剂型，临床前与I期数据显示：单次鼻腔给药后15–40分钟达峰，耐受性可接受，健康受试者中出现一过性解离感与血压升高，呈剂量相关，均为一过性、无需干预可自行缓解。")
para("本研究旨在评估XS-207鼻喷剂联合口服抗抑郁药，在口服抗抑郁药疗效不佳的中重度MDD患者中的疗效、安全性与合适剂量，为III期研究提供剂量与设计依据。")

h1("2. 研究设计概要")
para("研究分期：II期（概念验证+剂量探索）。设计：多中心、随机、双盲、安慰剂平行对照。", bold=True)
para("计划入组约240例，按1:1:1随机至三组：XS-207 56 mg组、XS-207 84 mg组、安慰剂组，均以现有口服抗抑郁药为基础进行辅助治疗（背景AD在入组前已稳定使用≥4周且剂量稳定）。")
para("双盲治疗期4周：第1周为给药诱导（每周2次鼻喷给药，给药间期≥72小时），第2–4周维持每周1次；此后设8周安全性随访期。全部鼻喷给药在研究中心由研究者在场监督下自行完成，给药后留观至少90分钟。")
para("随机分层因素：基线MADRS总分（≤35 vs >35）、研究中心、背景抗抑郁药类别（SSRI vs SNRI vs 其他）。")

h1("3. 研究人群")
para("目标人群：18–65岁，符合DSM-5 MDD诊断（MINI确认），当前发作期≥8周；正在接受1种口服抗抑郁药规范治疗且经研究者判断疗效不佳（MADRS总分≥26且较治疗前改善<25%）。")
para("关键入选标准：")
para("• MADRS总分≥26（筛查与基线两次评估一致）；• 体重≥40 kg；• 能理解并配合鼻喷自我给药与电子量表填写；• 育龄女性血妊娠阴性并同意避孕。")
para("关键排除标准：")
para("• 双相障碍、精神病性症状、当前为重度自杀风险（C-SSRS第4/5类阳性且研究者判断需紧急干预）；• 具临床意义的鼻腔疾病（如未控制的鼻炎、鼻中隔重度偏曲、近期鼻手术）影响给药或吸收；• 未控制的高血压（收缩压≥160或舒张压≥100 mmHg）及其他未控制的重要全身疾病；• 物质使用障碍（尼古丁除外）、癫痫史或易导致癫痫阈值降低的情况；• 筛查前30天内使用过任何NMDA受体拮抗剂或致解离类药物；• 肝肾功能显著异常（ALT/AST>2.5×ULN，eGFR<60）。")

h1("4. 给药方案")
para("XS-207鼻喷剂，规格28 mg/喷。56 mg组：第1周每次2喷（56 mg），84 mg组：第1周首剂2喷、第2次起3喷（84 mg）；安慰剂组给予匹配安慰剂鼻喷。给药均在研究日在场监督下由受试者自行喷鼻完成，每侧鼻腔交替。")
para("给药日要求：禁食≥2小时、避免酒精；给药后受试者留观≥90分钟，给药前及给药后每30分钟测量血压、心率各1次直至离院；出现血压显著升高（收缩压≥180或舒张压≥110 mmHg持续）时按方案处理并暂缓下次给药。研究期间禁止合并电抽搐治疗、氯胺酮及其他研究性药物；苯二氮卓类按挽救用药规则使用并记录。")

h1("5. 疗效终点")
para("主要疗效终点：双盲治疗期第4周（第28天）MADRS总分较基线的变化，在意向性治疗（ITT）人群中用MMRM分析。")
para("次要疗效终点：")
para("• 给药后2小时、24小时及第1周末MADRS总分较基线变化（评价快速起效）；• 第4周MADRS应答率（较基线下降≥50%）与缓解率（MADRS≤10）；• 第4周CGI-S及CGI-I评分变化；• Sheehan残疾量表（SDS）总分变化；• 第4周HAMD-17总分较基线变化（量表间一致性）。")

h1("6. 安全性评价")
para("安全性终点：不良事件/严重不良事件发生率与性质，包括解离相关症状（CADSS评分，给药后每15分钟至60分钟）、血压/心率变化、镇静程度（MORSE量表）、鼻咽部不良事件、用药过量和滥用潜力的信号评估。")
para("全受试者接受自杀风险纵向监测（C-SSRS，每次访视及每次给药后电话随访），出现主动自杀意念升级者按方案转入开放安全随访并获精神科处置。安全性随访期内监测撤药相关症状与渴求（视觉模拟量表）。实验室（血常规、血生化、尿常规）、12导联心电图、生命体征在筛选、基线、第2周、第4周及安全性随访期末采集。")

h1("7. 统计考虑")
para("样本量：按主要终点MADRS变化组间差异≥4.5分、共同标准差10分、双侧α=0.05、90%检验效能、失访率15%估算，每组约需完成80例，计划随机240例。")
para("主要分析：MMRM纳入治疗、访视、治疗×访视交互及基线MADRS分层，未调整的多重性按固定顺序检验（56 mg与84 mg先于关键次要终点）；剂量-反应关系用MCP-MOD作为支持性分析。疗效分析集为ITT（接受至少1次给药且有基线后≥1次MADRS评估），安全性分析集为接受至少1次给药的全部受试者。期中分析不设（II期单阶段），数据监查委员会（DMC）对安全性进行例行审查。")

h1("8. 研究管理")
para("本研究在约12家研究中心开展；知情同意、方案偏离、伦理审查及数据管理均按GCP和申办方标准操作执行。研究预计启动后约14个月完成全部受试者末次随访。")

doc.save(OUT)
print("saved:", OUT)

# 页数粗估
import zipfile
print("size bytes:", __import__("os").path.getsize(OUT))
