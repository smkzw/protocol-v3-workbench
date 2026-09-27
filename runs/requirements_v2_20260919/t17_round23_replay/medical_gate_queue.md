# 医学人工门·忠度拦截待处置清单（medical gate queue）

生成时间：2026-09-27（第23轮）。本清单只汇总证据、**不做任何处置**；
每项是否放行/重译/废弃，由医学经理人工裁定。数据源：隔离runtime库
（5301工作台所用 writing_reference.sqlite3）中全部
generation_status=fidelity_blocked 的翻译条目。

## 范围与数量

| 项目 | 研究数 | 拦截条目数 |
|---|---|---|
| 存量项目 proj_user_a5f104df6d03 | 5 | 165 |
| K3 项目（本轮样本与第1波） | 3 | 38 |
| **合计** | 8 | 203 |

说明：口径=隔离runtime库现状（存量165 + 本轮第1波新增37 + 样本1）。
另一份 390 项的旧快照读的是共享runtime库（2026-09-27 20:44），
不属于本工作台本轮操作面，未并入本清单。

## 阅读方法

- **发现的问题**由确定性忠度检查器输出翻译成人话；“第 N 单元（段）”指
  译文按原文切分后的第 N 段。带“请重点复核”的是医学含义风险较高的类型
  （比较方向、概念新增、条目数量）。
- **原文段落**为该章节的英文原文（按文档计划拼装的源文；个别历史条目
  仅存锚点短标题，已如实标注——那是历史谱系缺口的表现）。
- **中文译文段落**为被拦时的中文译文（标注“对齐译文”或“原始模型输出”）。
- 覆盖统计：有对齐译文 37 项、仅原始输出 165 项；
  有单元级谱系 37 项；原文段落完整（≥80字符）203 项、
  过短/缺失 0 项。


---

# 1. 存量项目（proj_user_a5f104df6d03）

## 研究 NCT03008590（59 项待处置）

### NCT03008590·条目 1：Unlabelled section (safety) (safety) · 2

- 条目ID：`wref_translation_item_06525041c1200d8323ef8bc6`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> In-person visits are at screening / enrollment and weeks (Wks) 8 and 16. Wk 0 (Baseline) may occur in-person at enrollment or within 14 days at home. Phone reminders to complete questionnaires weekly may occur but are not essential to the protocol. Non-serious adverse events (AEs) will be collected at in-person visits; subjects will be instructed to report potential serious adverse events (SAEs) as soon as possible and will be asked about non-serious AEs during the weekly phone conversations when those occur. * Complete blood count with differential, electrolytes, BUN, creatinine, liver function tests, ESR, CRP. Inability to provide these samples will be regarded simply as missing data (as with an incomplete questionnaire) rather than as a protocol deviation.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 现场访视安排在筛选/入组时以及第8周和第16周进行。基线检查（即第0周）可在入组时现场完成，也可在入组后14天内于受试者家中进行。可每周通过电话提醒受试者填写问卷，但这并非本方案的强制要求。非严重不良事件（AEs）的收集在现场访视时进行；同时会指导受试者尽快报告任何疑似严重不良事件（SAEs），并在每周电话沟通时询问其是否出现非严重的AEs。

### NCT03008590·条目 2：a. Registration (safety)

- 条目ID：`wref_translation_item_0d1bb5cf789b05aa807a7ffd`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
  - 译文第 1 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_1:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> At enrollment, each patient will be assigned an ID number beginning with the type of arthritis (OA or IA) followed by order of enrollment among patients with OA or IA (01-60). This ID number will be seen by the investigator and study participant and used on all questionnaires as well as the case report forms used for the additional data obtained at in-person visits. A file that links the patient’s name and chronological ID number to the random study ID number will be maintained by the study coordinator on a VA network drive. This process will minimize the chance that the PI will be able to identify individual subjects if he is participating in data analysis, particularly important for any exploratory analyses beyond those that are pre-specified. b. Randomization The research pharmacy will perform the randomization using a varying block design provided by the statistician, and the study staff will remain blinded to group assignment. The pharmacist will log treatment assignments. The patient and investigator will remain blinded to the treatment assignments until completion of the last visit of the last patient enrolled. At that time, the blind will be broken and the PI will be informed about treatment assignments and will notify the patients and their MDs which treatments they received. Patients will be notified of their treatment assignments by the sending of an IRB approved letter within one month after the last patient’s last visit or within one month after IRB approval of the letter, whichever is later. The participants’ PCPs and/or rheumatologists will be notified by being copied on a CPRS note containing the approximate dates of study treatment and the treatment assignments within one month after the last patient’s last visit. Unblinding of the treatment assignment 
> …（中略）…
>  will occur directly on the SharePoint site. Research records will be kept indefinitely or until the law allows their destruction in accordance with the VA Record Control Schedule. Paper records will be shredded, and electronic records will be destroyed in a manner in which they cannot be retrieved.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 在受试者入组时，将为每位患者分配一个识别编号。该编号以所患关节炎的类型（OA或IA）开头，随后为该患者在同类关节炎患者中的入组顺序号（01-60）。该识别编号仅由研究者和受试者本人知晓，并将用于所有调查问卷以及现场随访时所填写的病例报告表。研究协调员会在VA网络硬盘中保存一份文件，其中记录了患者的姓名、原始识别编号与随机分配的研究编码之间的对应关系。这一做法能最大程度降低主要研究者在参与数据分析时识别出特定受试者的可能性，对于开展任何超出预先设定范围的探索性分析而言尤为重要。

### NCT03008590·条目 3：i. Inclusion Criteria (eligibility)

- 条目ID：`wref_translation_item_163202df6237fc74e7cad27d`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）

**【原文段落】**（英文原文）

> i. Inclusion Criteria
> Patients must meet all of the following criteria in order to be eligible for enrollment: • One or more of the following chronic conditions: osteoarthritis, rheumatoid arthritis, peripheral spondyloarthritis (which may include shoulder or hip involvement) • Average daily pain interference with function (average of the 7 parts of question 9 on the BPI) rated at least 4 on a scale of 0-10, and no higher than 9 • No increase in medication in the past 8 weeks made with the expectation of improving pain, including acetaminophen, any NSAID, any opioid, tramadol, gabapentin, pregabalin, cyclobenzaprine, any tricyclic antidepressant, duloxetine, systemic or injectable corticosteroids, or injectable viscosupplements • No plan to start another medication or a non-pharmacologic treatment regimen likely to affect pain during the next 16 weeks • Age at least 18 • Capable of informed consent, and willingness to comply with study procedures, including receipt of weekly phone calls from the study coordinator ii. Exclusion Criteria
> • Use of opioids, including tramadol, in the past 7 days (determined by asking participant if they have used any opioid containing medications in the past 7 days or plan to use any opioid containing medications) • Pregnant, breast feeding, or unwilling to engage in contraceptive practices if sexually active and capable of conceiving (determined by asking participant if they are pregnant or breast feeding or plan to become pregnant during the duration of the study) • Schizophrenia, bipolar disorder, or poorly controlled depression or anxiety • Previous use of naltrexone for more than 8 weeks or in the past 2 weeks, at a low dose or FDA approved dose • Back pain described by the patient as greater in severity than arthritic pain in all peri
> …（中略）…
> n arthritic pain. There is no specific screening procedure. • Plan to have surgery during the next 16 weeks
> • Other qualitative circumstances that the investigator feels would make the patient a poor candidate for this clinical trial, such as an unstable social situation or unreliable transportation

**【中文译文段落】**（原始模型输出（未经对齐组装））

> i. 纳入标准
> 符合以下所有标准的患者方可入选本研究：
> • 患有一种或多种下述慢性疾病：骨关节炎、类风湿关节炎、外周型脊柱关节炎（可累及肩部或髋部）
> • 根据BPI量表第9题的7个分项评分平均值计算，每日疼痛对功能的影响程度在0至10分的量表上至少为4分且不超过9分
> • 过去8周内未出于缓解疼痛的目的增加任何药物的使用剂量，此类药物包括对乙酰氨基酚、各类NSAID、所有阿片类药物、曲马多、加巴喷丁、普瑞巴林、环苯扎林、各类三环类抗抑郁药、度洛西汀、全身或注射型皮质类固醇以及注射用黏弹性补充剂
> • 未来16周内无开始使用其他药物或实施可能影响疼痛程度的非药物治疗方案的计划
> • 年龄满18周岁及以上
> • 具备作出知情同意的能力，且愿意配合完成研究流程，包括接听研究协调员每周打来的电话
> ii. 排除标准

### NCT03008590·条目 4：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_177a9e1146c7d2e768417305`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 5：i. Inclusion Criteria (eligibility)

- 条目ID：`wref_translation_item_1c35a200b75abf1ac5ca9a81`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）

**【原文段落】**（英文原文）

> i. Inclusion Criteria
> Patients must meet all of the following criteria in order to be eligible for enrollment: • One or more of the following chronic conditions: osteoarthritis, rheumatoid arthritis, peripheral spondyloarthritis (which may include shoulder or hip involvement) • Average daily pain interference with function (average of the 7 parts of question 9 on the BPI) rated at least 4 on a scale of 0-10, and no higher than 9 • No increase in medication in the past 8 weeks made with the expectation of improving pain, including acetaminophen, any NSAID, any opioid, tramadol, gabapentin, pregabalin, cyclobenzaprine, any tricyclic antidepressant, duloxetine, systemic or injectable corticosteroids, or injectable viscosupplements • No plan to start another medication or a non-pharmacologic treatment regimen likely to affect pain during the next 16 weeks • Age at least 18 • Capable of informed consent, and willingness to comply with study procedures, including receipt of weekly phone calls from the study coordinator ii. Exclusion Criteria
> • Use of opioids, including tramadol, in the past 7 days (determined by asking participant if they have used any opioid containing medications in the past 7 days or plan to use any opioid containing medications) • Pregnant, breast feeding, or unwilling to engage in contraceptive practices if sexually active and capable of conceiving (determined by asking participant if they are pregnant or breast feeding or plan to become pregnant during the duration of the study) • Schizophrenia, bipolar disorder, or poorly controlled depression or anxiety • Previous use of naltrexone for more than 8 weeks or in the past 2 weeks, at a low dose or FDA approved dose • Back pain described by the patient as greater in severity than arthritic pain in all peri
> …（中略）…
> n arthritic pain. There is no specific screening procedure. • Plan to have surgery during the next 16 weeks
> • Other qualitative circumstances that the investigator feels would make the patient a poor candidate for this clinical trial, such as an unstable social situation or unreliable transportation

**【中文译文段落】**（原始模型输出（未经对齐组装））

> i. 纳入标准
> 符合以下所有标准的患者方可入选本研究：
> • 患有一种或多种下述慢性疾病：骨关节炎、类风湿关节炎、外周型脊柱关节炎（可累及肩部或髋部）
> • 根据BPI量表第9题的7个分项评分平均值计算，每日疼痛对功能的影响程度在0至10分的量表上至少为4分且不超过9分
> • 过去8周内未出于缓解疼痛的目的增加任何药物的使用剂量，此类药物包括对乙酰氨基酚、各类NSAID、所有阿片类药物、曲马多、加巴喷丁、普瑞巴林、环苯扎林、各类三环类抗抑郁药、度洛西汀、全身或注射型皮质类固醇以及注射用黏弹性补充剂
> • 未来16周内无开始使用其他药物或实施可能影响疼痛程度的非药物治疗方案的计划
> • 年龄满18周岁及以上
> • 具备作出知情同意的能力，且愿意配合完成研究流程，包括接听研究协调员每周打来的电话
> ii. 排除标准

### NCT03008590·条目 6：g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_1c9699a057a9b0954a425247`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 8 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_8:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> As only naltrexone and placebo will be considered to be study drugs in this trial, only adverse events possibly, probably, or definitely related to naltrexone will be considered reportable for this study. e. Relation to Study Therapy The relation or attribution of an adverse event to an investigational product is determined by the investigator and then recorded on the appropriate case report form and/or SAE reporting form. The CTCAE provides the following descriptors and definitions for assigning an attribution to each adverse event. Code Descriptor Definition
> “ Unrelated” Category Code 1 Unrelated The adverse event is clearly not related to the investigational product “Related” Category Codes 2 Unlikely The adverse event is doubtfully related to the investigational product 3 Possible The adverse event may be related to the investigational product 4 Probable The adverse event is likely related to the investigational product 5 Definite The adverse event is clearly related to the investigational product f. Standard Elements A set of standard elements for adverse event data will be collected. These elements include: patient ID, dates for event/event reported/date resolved, the event itself, event severity, whether it was expected and/or serious (as defined above), patient status, place of adverse event treatment (to further determine serious events), causality, and subsequent changes to protocol or consent form. Additionally, the reporter may write a more detailed description of the event and any other pertinent information. g. Expected / Known Risks and Adverse Events Associated with Study
> Intervention and Procedures
> i. Study Drug/Intervention: For known risks of study intervention, see Section 9. ii. Study Procedures: For risks of study procedures, see Section 9. h. Repo
> …（中略）…
> ted reportable adverse events must be reported within 20 working days of the notification of the event or of the site becoming aware of the event. i. Investigational New Drug Application (IND) The FDA has made a formal ruling that this study is exempt from needing an IND. j. Planned Interim Analysis

**【中文译文段落】**（原始模型输出（未经对齐组装））

> h. 报告时限 • 研究者须履行VA波士顿医疗系统伦理委员会的所有报告要求。• 在获悉任何严重不良事件后24小时内，共同研究者须将该事件（无论是否与试验用药品相关）汇报给主要研究者。随后，主要研究者在获悉该事件后24小时内须向伦理委员会报告；在2个工作日内还需向DMC进行汇报。• 对于1级程度的预期或非预期的不良事件，是否收集与报告由主要研究者自行决定；例如既往研究中曾报道过的神经精神类副作用。• 所有其他需要报告的预期或非预期的不良事件，均须在获悉该事件或研究中心知晓事件发生后的20个工作日内予以报告。

### NCT03008590·条目 7：i. Inclusion Criteria (eligibility)

- 条目ID：`wref_translation_item_1db041492489548416a40fee`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）

**【原文段落】**（英文原文）

> i. Inclusion Criteria
> Patients must meet all of the following criteria in order to be eligible for enrollment: • One or more of the following chronic conditions: osteoarthritis, rheumatoid arthritis, peripheral spondyloarthritis (which may include shoulder or hip involvement) • Average daily pain interference with function (average of the 7 parts of question 9 on the BPI) rated at least 4 on a scale of 0-10, and no higher than 9 • No increase in medication in the past 8 weeks made with the expectation of improving pain, including acetaminophen, any NSAID, any opioid, tramadol, gabapentin, pregabalin, cyclobenzaprine, any tricyclic antidepressant, duloxetine, systemic or injectable corticosteroids, or injectable viscosupplements • No plan to start another medication or a non-pharmacologic treatment regimen likely to affect pain during the next 16 weeks • Age at least 18 • Capable of informed consent, and willingness to comply with study procedures, including receipt of weekly phone calls from the study coordinator ii. Exclusion Criteria
> • Use of opioids, including tramadol, in the past 7 days (determined by asking participant if they have used any opioid containing medications in the past 7 days or plan to use any opioid containing medications) • Pregnant, breast feeding, or unwilling to engage in contraceptive practices if sexually active and capable of conceiving (determined by asking participant if they are pregnant or breast feeding or plan to become pregnant during the duration of the study) • Schizophrenia, bipolar disorder, or poorly controlled depression or anxiety • Previous use of naltrexone for more than 8 weeks or in the past 2 weeks, at a low dose or FDA approved dose • Back pain described by the patient as greater in severity than arthritic pain in all peri
> …（中略）…
> n arthritic pain. There is no specific screening procedure. • Plan to have surgery during the next 16 weeks
> • Other qualitative circumstances that the investigator feels would make the patient a poor candidate for this clinical trial, such as an unstable social situation or unreliable transportation

**【中文译文段落】**（原始模型输出（未经对齐组装））

> i. 纳入标准
> 符合以下所有标准的患者方可入选本研究：
> • 患有一种或多种下述慢性疾病：骨关节炎、类风湿关节炎、外周型脊柱关节炎（可累及肩部或髋部）
> • 根据BPI量表第9题的7个分项评分平均值计算，每日疼痛对功能的影响程度在0至10分的量表上至少为4分且不超过9分
> • 过去8周内未出于缓解疼痛的目的增加任何药物的使用剂量，此类药物包括对乙酰氨基酚、各类NSAID、所有阿片类药物、曲马多、加巴喷丁、普瑞巴林、环苯扎林、各类三环类抗抑郁药、度洛西汀、全身或注射型皮质类固醇以及注射用黏弹性补充剂
> • 未来16周内无开始使用其他药物或实施可能影响疼痛程度的非药物治疗方案的计划
> • 年龄满18周岁及以上
> • 具备作出知情同意的能力，且愿意配合完成研究流程，包括接听研究协调员每周打来的电话
> ii. 排除标准

### NCT03008590·条目 8：i. Inclusion Criteria (objectives_endpoints)

- 条目ID：`wref_translation_item_1e47b3d14444c8192ce3ba63`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> iii. Notes on Inclusion and Exclusion Criteria Patients will be regarded as having rheumatoid arthritis or spondyloarthritis based on their assessment by a rheumatologist (including the PI) in the VA Boston Healthcare System. Although criteria exist for diagnosis of RA and psoriatic arthritis, these criteria were created primarily to have high specificity for enrollment of patients in clinical trials in which disease activity and structural damage (rather than pain) are the outcomes of interest. Applying such criteria in the current study may be too restrictive. Average daily pain of at least 4 on a scale of 0-10 is widely recommended and used in trials in OA (14, 32), since lower levels of pain may not induce a patient to seek treatment (i.e. are not clinically significant), and inclusion of patients with lower levels of pain may make it more difficult to see differences between treatment arms. Patients with severe psychiatric illnesses will be excluded in part because of uncertain safety of the treatment and in part because of concerns about reliability of data. Current DSM-5 diagnoses of bipolar and related disorders or schizophrenia spectrum and other psychotic disorders (APA, 2013) will be grounds for exclusion. Patients with severe depression will be identified and excluded on the basis of a total score ≥ 29, or a score of 2 or 3 on the question of suicidality, on the Beck Depression Inventory-II administered at screening. Previous extended use of naltrexone is an exclusion so as to avoid enrolling patients who have previously reported benefit at a low dose, or who had side effects at the FDA- approved dose. Patients with moderate to severe chronic kidney or liver disease are excluded due to delayed drug elimination and metabolism, in accordance with the Prescribi
> …（中略）…
> = 4.5 mg To ensure that equal numbers of patients with OA and IA are incorporated into the two groups, stratification by these two diagnostic groups will be used.
> | Group | Weeks 1-8 | Weeks 9-16 |
> | 1 | Low-Dose Naltrexone | Placebo |
> | 2 | Placebo | Low-Dose Naltrexone |
> ii. Prohibited Medications

**【中文译文段落】**（原始模型输出（未经对齐组装））

> iii. 入选与排除标准说明：患者是否被判定为患有类风湿关节炎或脊柱关节炎，需由VA波士顿医疗系统中的风湿病专家（包括PI）进行评估。虽然目前已有诊断类风湿关节炎及银屑病关节炎的标准，但这些标准主要是为确保受试者具备较高的特异性而制定——即确保他们参与的是以疾病活动度及结构损伤（而非疼痛程度）为主要研究终点的临床试验。若将这些标准直接应用于本研究，则可能限制受试者的入选范围。在骨关节炎相关试验中，普遍推荐并采用的标准为：受试者每日平均疼痛评分至少为4分（满分10分）(14, 32)。这是因为若疼痛程度较低，患者往往不会主动寻求治疗。

### NCT03008590·条目 9：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_1fbd7a03dadf36c29d3d40df`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 10：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_213000ba0f37fc6f0cb98ba2`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 11：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 6

- 条目ID：`wref_translation_item_246076777db2bda0cd7071f1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> The design has 80% power to detect a mean difference between treatments of 0.6 or larger with a two-sided type I error of 5%. This allows for up to 4 of 30 patients in each group to drop out before 12 weeks. b. Secondary Outcomes The secondary outcome measures include : • Brief Pain Inventory (other individual questions than those used for the primary outcome, especially average pain severity = question 5) • painDETECT (continuous measure 0-38, or classified as nociceptive/unclear/neuropathic per the questionnaire guidelines) • Brief Fatigue Inventory, specifically question 2 (usual level in past 24 hours, 0-10) and question 4 (interference in the past 24 hours, average of 6 questions 0-10 each) • PROMIS-29 (total score, continuous measure, 28-150) • Beck Depression Inventory-II (continuous measure 0-63, or classified as minimal/mild/moderate/severe per the questionnaire guidelines) • Use of “as-needed” analgesic medications (expressed as % of maximum prescription dose) • Patient global assessment of improvement or worsening on a 7-point scale [Clinical Global Impression of Severity (CGI-S) and Improvement (CGI-I) Scales] • CRP • Adverse events, including pre-specified minor adverse events (vivid dreams, headache, dizziness, insomnia, fatigue, nausea) and categories of severe adverse events (cardiovascular, neuropsychiatric, malignancy, serious infection) Secondary outcome measures for specific diseases: • Rheumatoid arthritis: DAS28, as a continuous measure or classified as good/moderate/no response per EULAR criteria • Spondyloarthritis: BASDAI, as a continuous measure The primary and secondary analytical approaches for the secondary outcomes will be the same as for the primary outcome measures for all continuous variables. Weightings will change for outcomes measured every 4 or 8 weeks rather than weekly. Outcomes based on classification will use analysis of proportions of patients transitioning from one class to another. Proportions of patients experiencing categories of adverse events while receiving LDN or placebo will be compared by Fisher’s exact tests. 8. Data Management
> a. Registration

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 该研究设计具备80%的检验效能，能够在双侧I类错误率控制在5%的前提下检测出各治疗组间平均差异达到0.6或更大的情况。该设计还允许每组最多有4名患者，在治疗满12周前退出研究。

### NCT03008590·条目 12：a. Registration (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_2732698571fa31166b058d7f`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_3:unsupported_medical_concept_added`）
  - 译文第 3 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_3:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> The risk associated with potential delay in seeking other approaches to pain management is also considered to be minimal. Only patients who report stable pain for the previous 2 months and stable use of medications to control pain, and who report no intention of making other efforts to control pain during the coming 16 weeks, will be approached for participation in this study. Standard approaches to preserving confidentiality of research data are noted in Section 8. 10. References 1. Lee YC. Effect and treatment of chronic pain in inflammatory arthritis. Current rheumatology reports. 2013 Jan;15(1):300. PubMed PMID: 23292816. Pubmed Central PMCID: 3552517. 2. Cohen E, Lee YC. A Mechanism-Based Approach to the Management of Osteoarthritis Pain. Current osteoporosis reports. 2015 Dec;13(6):399-406. PubMed PMID: 26419467. Pubmed Central PMCID: 4623875. 3. Ding C, Zhang Y, Hunter D. Use of imaging techniques to predict progression in osteoarthritis. Curr Opin Rheumatol. 2013 Jan;25(1):127-35. PubMed PMID: 23080226. 4. Torres L, Dunlop DD, Peterfy C, Guermazi A, Prasad P, Hayes KW, et al. The relationship between specific tissue lesions and pain severity in persons with knee osteoarthritis. Osteoarthritis Cartilage. 2006 Oct;14(10):1033-40. PubMed PMID: 16713310. 5. Lee YC, Cui J, Lu B, Frits ML, Iannaccone CK, Shadick NA, et al. Pain persists in DAS28 rheumatoid arthritis remission but not in ACR/EULAR remission: a longitudinal observational study. Arthritis Res Ther. 2011;13(3):R83. PubMed PMID: 21651807. Pubmed Central PMCID: 3218896. 6. American College of Rheumatology Pain Management Task F. Report of the American College of Rheumatology Pain Management Task Force. Arthritis Care Res (Hoboken). 2010 May;62(5):590-9. PubMed PMID: 20461782. 7. Neogi T, Guermazi A, Roemer 
> …（中略）…
> kin RH, Turk DC, Wyrwich KW, Beaton D, Cleeland CS, Farrar JT, et al. Interpreting the clinical importance of treatment outcomes in chronic pain clinical trials: IMMPACT recommendations. The journal of pain : official journal of the American Pain Society. 2008 Feb;9(2):105-21. PubMed PMID: 18055266.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 1. Lee YC. 炎症性关节炎所致慢性疼痛的疗效与治疗。Current Rheumatology Reports杂志，2013年1月；15卷(第1期)：300页。PubMed PMID: 23292816。Pubmed Central PMCID: 3552517。

### NCT03008590·条目 13：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_27873309b1cff49f055c0574`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> 2. Study Abstract (summary for lay-persons) Naltrexone is an FDA approved drug (for alcoholism) that has found widespread use “off-label” to treat pain and fatigue at much lower doses than are used for the approved indication. There are a few scientific studies in three conditions (fibromyalgia, Crohn's disease, and multiple sclerosis) that suggest that this drug has benefit and is safe. However, considering the extent of use in other conditions, and uncertainty about the mechanism of action (purely a pain reliever? other benefits on brain chemistry? anti-inflammatory?), study is needed in diverse diseases. The current study is intended to generate preliminary data in several rheumatologic conditions (osteoarthritis and multiple forms of inflammatory arthritis) in order to select such conditions for future study in larger clinical trials. Although it is a pilot study, a placebo- controlled component is used because of the prominent placebo group effect seen in studies in which self-reported pain is the main outcome. A "blinded cross-over" design is used so that patients will not know when they might be transitioning between placebo and naltrexone. 3. Study Endpoints
> a. Primary Outcome
> • Average interference of pain with general activity (question 9 on the Brief Pain Inventory, an average of 7 sub-questions, each 0-10) will be compared during naltrexone treatment and during placebo treatment. b. Secondary Outcomes
> The secondary outcome measures include : • Brief Pain Inventory [other individual questions than those used for the primary outcome, particularly question 5 (average pain severity)] • painDETECT (continuous measure 0-38, or classified as nociceptive/unclear/neuropathic per the questionnaire guidelines) • Brief Fatigue Inventory, specifically question 2 (usual l
> …（中略）…
> , collected using the IRB’s and DMC’s standard forms
> Secondary outcome measures for specific diseases: • Rheumatoid arthritis: DAS28, as a continuous measure or classified as good/moderate/no response per EULAR criteria • Spondyloarthritis: BASDAI, as a continuous measure 4. Background and Rationale

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 2. 研究摘要（面向普通大众的概述）纳曲酮是一种经FDA批准用于治疗酒精依赖的药物，目前该药在未经官方适应症许可的情况下被广泛使用：以远低于获批用途的剂量来治疗疼痛与疲劳。目前已有少量科学研究针对三种疾病（纤维肌痛、克罗恩病及多发性硬化症）开展，结果显示该药具有疗效且安全性良好。然而鉴于其在其他多种疾病中的使用频率较高，加之对其作用机制尚不明确（仅具备镇痛效果？是否对脑内生化环境有其他影响？是否具有抗炎作用？），因此有必要在更多疾病中开展相关研究。本研究旨在针对多种风湿性疾病（骨关节炎及各类炎症性关节炎）获取初步数据，从而为后续更大规模的临床试验筛选合适的研究病种。尽管本研究属于探索性试验，但由于以受试者自我报告的疼痛程度为主要评价指标时常会出现明显的安慰剂效应，故本研究仍设置了安慰剂对照组。此外研究采用了“盲法交叉设计”，以确保患者无法知晓自己何时会从接受安慰剂治疗转为使用纳曲酮治疗。

### NCT03008590·条目 14：a. Background (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_2fa790f8de6041b2cb215ec1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> 1 Thus, approaches to pain management in the arthritides could include reduction of inflammation, nociception, and central sensitization. Treatment of Arthritic Pain Unfortunately, management of pain in OA, as in management of chronic pain more generally, remains a challenge despite great effort. Acetaminophen produces little if any benefit above placebo (11). Non-steroidal anti-inflammatory drugs (NSAIDs) are clearly superior to placebo or acetaminophen, with effect sizes 0.3 – 0.5 (“small” in common interpretation (12)) in meta-analyses of multiple trials (11, 13), but this benefit corresponds to median absolute reductions in pain, relative to placebo, of less than 20%, a common standard for the minimum clinically significant difference (12, 14, 15). However, excess cardiovascular risk has now been attributed to NSAIDs as an entire class (16), not just to Cox-2 selective drugs, and NSAIDs were already known to confer important risks of peptic ulcer disease and kidney damage. Tramadol, stronger opioids, and a variety of non- pharmacologic interventions perform no better than NSAIDs based on effect sizes and improvement in pain reduction versus placebo (13) (and see numerous Cochrane reviews), and an “epidemic” of abuse of prescription opioids has received great attention in both the medical literature and popular media. FDA approval of duloxetine to treat pain in OA, on the basis of an absolute difference in pain relief of 10% compared to placebo (17), is arguably the biggest advance in pain management in OA in the past decade. Intra-articular injections of corticosteroids (CS) or hyaluronic acid (HA) derivatives have higher absolute improvements than oral drugs, but since the placebo effect of intra-articular injection is also high, the improvement after CS or HA inje
> …（中略）…
> tions of web-based MDs and other self- appointed experts, most of whom recommend a range of other unproven remedies as well. The testimonials are essentially case reports using patient-reported outcomes (as a class, the type of outcome used in all studies of pain management), but of course they must

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 1 因此，关节炎相关疼痛的管理措施可包含减轻炎症反应、痛觉传导及中枢敏化现象。遗憾的是，与慢性疼痛的整体管理情况类似，即便付出了诸多努力，骨关节炎患者的疼痛控制依然面临巨大挑战。对乙酰氨基酚所产生的疗效几乎与安慰剂无异（11）。非甾体抗炎药类（NSAIDs）的疗效明显优于安慰剂或对乙酰氨基酚；多项临床试验的荟萃分析显示，其效应量介于0.3至0.5之间（按照常规判定标准属于“小幅度改善”）（12），但相较于安慰剂而言，此类药物带来的疼痛绝对降幅中位数不足20%，而这一数值正是临床公认的最小有意义改善阈值（12、14、15）。不过，目前已有研究证实：整个非甾体抗炎药类均存在增加心血管风险的可能（16），该影响并不仅限于选择性Cox-2抑制剂；此外，此类药物本身也已被证实易诱发消化性溃疡及肾脏损伤等不良反应。基于效应量及对疼痛缓解程度的评估，曲马多、强效阿片类药物以及各类非药物干预手段的疗效均不优于非甾体抗炎药类（

### NCT03008590·条目 15：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_36f99f1796d9c1721b9f307e`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 5 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_5:numeric_tokens_changed`）
  - 译文第 5 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_5:negation_signal_missing`）
  - 译文第 5 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_5:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> Use of any opioid agonist, including tramadol, is an exclusion criterion for enrollment, and these drugs must also be avoided during the trial. If a patient must use an opioid agonist for more than 2 days during the trial, that patient must be removed from the trial, and data will be censored at the time of that treatment. Medications to treat pain must not have been increased for 8 weeks prior to enrollment. Opioids, including tramadol, may not have been used for at least 7 days prior to enrollment. If a patient must have a change in treatment (pharmacologic or non- pharmacologic) related to pain or arthritis, that patient must be removed from the trial, and data will be censored at the time of that treatment change. Stable treatment with IV medications that require pre-treatment with other medications to prevent infusion reactions (e.g., rituximab, infliximab, IVIG) will not be regarded as a change in treatment. Corticosteroid or viscosupplementation injection intended to improve musculoskeletal pain must have been given at least 8 weeks prior to enrollment. It is expected that many patients will be using acetaminophen or NSAIDs as needed before enrollment. Rather than requiring patients to move to a fixed schedule, data on use of such drugs will be collected and used in analyses.
> d. Study Procedures
> i. Recruitment
> Recruitment will occur through the clinical practices of the rheumatologists at the three main campuses of the VA Boston Healthcare System. Primary care providers will be notified about the trial and will be encouraged to contact the PI about potential participants. Pre-screening by discussion with the referring physician and review of medical records will greatly reduce the number of screening failures. Referring physicians will be asked to ask prospective
> …（中略）…
> ributed at (in person) or shortly after (by mail or in person) the first two of these visits. Patients who are unable to attend the second and/or third in-person visits may remain in the study if completed questionnaires, new questionnaires, and study drug are delivered by mail. v. Study Assessments

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 招募工作将在波士顿VA医疗系统三大院区的风湿病科医师所在的临床实践中开展。基层保健医生将获知本试验的相关信息，并被鼓励就潜在的受试者情况与PI取得联系。通过与转诊医生沟通并进行病历审查的方式开展预筛选，可大幅减少筛查失败的情况。将要求转诊医生请拟入选的受试者对过去两周内其每日平均疼痛严重程度及疼痛干扰程度进行评分（0至10分），但须叮嘱医生切勿告知患者其入选标准为年满18周岁及以上。

### NCT03008590·条目 16：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_3906464f205d579c166f8580`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> 2. Study Abstract (summary for lay-persons) Naltrexone is an FDA approved drug (for alcoholism) that has found widespread use “off-label” to treat pain and fatigue at much lower doses than are used for the approved indication. There are a few scientific studies in three conditions (fibromyalgia, Crohn's disease, and multiple sclerosis) that suggest that this drug has benefit and is safe. However, considering the extent of use in other conditions, and uncertainty about the mechanism of action (purely a pain reliever? other benefits on brain chemistry? anti-inflammatory?), study is needed in diverse diseases. The current study is intended to generate preliminary data in several rheumatologic conditions (osteoarthritis and multiple forms of inflammatory arthritis) in order to select such conditions for future study in larger clinical trials. Although it is a pilot study, a placebo- controlled component is used because of the prominent placebo group effect seen in studies in which self-reported pain is the main outcome. A "blinded cross-over" design is used so that patients will not know when they might be transitioning between placebo and naltrexone. 3. Study Endpoints
> a. Primary Outcome
> • Average interference of pain with general activity (question 9 on the Brief Pain Inventory, an average of 7 sub-questions, each 0-10) will be compared during naltrexone treatment and during placebo treatment. b. Secondary Outcomes
> The secondary outcome measures include : • Brief Pain Inventory [other individual questions than those used for the primary outcome, particularly question 5 (average pain severity)] • painDETECT (continuous measure 0-38, or classified as nociceptive/unclear/neuropathic per the questionnaire guidelines) • Brief Fatigue Inventory, specifically question 2 (usual l
> …（中略）…
> , collected using the IRB’s and DMC’s standard forms
> Secondary outcome measures for specific diseases: • Rheumatoid arthritis: DAS28, as a continuous measure or classified as good/moderate/no response per EULAR criteria • Spondyloarthritis: BASDAI, as a continuous measure 4. Background and Rationale

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 2. 研究摘要（面向普通大众的概述）纳曲酮是一种经FDA批准用于治疗酒精依赖的药物，目前该药在未经官方适应症许可的情况下被广泛使用：以远低于获批用途的剂量来治疗疼痛与疲劳。目前已有少量科学研究针对三种疾病（纤维肌痛、克罗恩病及多发性硬化症）开展，结果显示该药具有疗效且安全性良好。然而鉴于其在其他多种疾病中的使用频率较高，加之对其作用机制尚不明确（仅具备镇痛效果？是否对脑内生化环境有其他影响？是否具有抗炎作用？），因此有必要在更多疾病中开展相关研究。本研究旨在针对多种风湿性疾病（骨关节炎及各类炎症性关节炎）获取初步数据，从而为后续更大规模的临床试验筛选合适的研究病种。尽管本研究属于探索性试验，但由于以受试者自我报告的疼痛程度为主要评价指标时常会出现明显的安慰剂效应，故本研究仍设置了安慰剂对照组。此外研究采用了“盲法交叉设计”，以确保患者无法知晓自己何时会从接受安慰剂治疗转为使用纳曲酮治疗。

### NCT03008590·条目 17：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 5

- 条目ID：`wref_translation_item_3ba130bdb3777054fb25af72`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> a. Primary Outcome Interference of pain with general activity (question 9 on the Brief Pain Inventory, an average of 7 sub-questions, each 0-10) is the primary outcome measure. Pain severity is the primary outcome reported in studies of pain in OA. However, some patients will choose to increase activity at the expense of a level of pain that they have learned to tolerate, so “pain interference” is of at least equal interest (12, 23).
> i. Primary Analytic Approach to the Primary Outcome The goal is to determine the difference in pain interference during treatment with LDN versus placebo. We will take advantage of the multiple data points obtained from each patient to improve the precision of that estimate, reducing the risk of type II error. The summary of each patient’s response to LDN compared to placebo will be made using linear contrasts. Thus, for each patient: d = a n1 x n1 + a n2 x n2 … + a n8 x n8 – a p1 x p1 – a p2 x p2 … – a p8 x p8 where each “a” indicates a weight assigned to that observation on the basis of fitting the pre-post crossover data from all patients with a cubic spline or two linear splines; n indicates treatment with naltrexone; p indicates treatment with placebo; x indicates pain severity or pain interference; and numbers indicate weeks on the treatment. The first observation following cross-over will be dropped in each patient. Thus, in group 1, weights a p1 and a p2 will be 0, and in group 2, weights a n1 and a n2 will be 0. Weights will be adjusted in individual patients in the event of missing data, and data obtained during an active adverse event will not be included; the weight given to the summary value of each patient’s data (d) in the full analysis, however, will be equal. In each patient, the sum of all weights will be set to 0. The distribution of d among all patients will then be compared to a null distribution by t- test.
> ii. Secondary Analytic Approaches to the Primary Outcome

**【中文译文段落】**（原始模型输出（未经对齐组装））

> a. 主要终点：疼痛对日常活动的影响程度（即简明疼痛量表中的第9个问题，由7个0至10分的子问题构成的平均值）是本研究的主要终点指标。在骨关节炎相关疼痛研究中，疼痛严重程度也是最常报告的主要结局指标。不过也有部分患者会选择增加活动量，即便这意味着承受他们已能适应的疼痛水平；因此“疼痛对日常活动的干扰程度”同样值得重点关注 (12, 23)。

### NCT03008590·条目 18：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 5

- 条目ID：`wref_translation_item_3c896e56829cd7d0e295e3bc`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> a. Primary Outcome Interference of pain with general activity (question 9 on the Brief Pain Inventory, an average of 7 sub-questions, each 0-10) is the primary outcome measure. Pain severity is the primary outcome reported in studies of pain in OA. However, some patients will choose to increase activity at the expense of a level of pain that they have learned to tolerate, so “pain interference” is of at least equal interest (12, 23).
> i. Primary Analytic Approach to the Primary Outcome The goal is to determine the difference in pain interference during treatment with LDN versus placebo. We will take advantage of the multiple data points obtained from each patient to improve the precision of that estimate, reducing the risk of type II error. The summary of each patient’s response to LDN compared to placebo will be made using linear contrasts. Thus, for each patient: d = a n1 x n1 + a n2 x n2 … + a n8 x n8 – a p1 x p1 – a p2 x p2 … – a p8 x p8 where each “a” indicates a weight assigned to that observation on the basis of fitting the pre-post crossover data from all patients with a cubic spline or two linear splines; n indicates treatment with naltrexone; p indicates treatment with placebo; x indicates pain severity or pain interference; and numbers indicate weeks on the treatment. The first observation following cross-over will be dropped in each patient. Thus, in group 1, weights a p1 and a p2 will be 0, and in group 2, weights a n1 and a n2 will be 0. Weights will be adjusted in individual patients in the event of missing data, and data obtained during an active adverse event will not be included; the weight given to the summary value of each patient’s data (d) in the full analysis, however, will be equal. In each patient, the sum of all weights will be set to 0. The distribution of d among all patients will then be compared to a null distribution by t- test.
> ii. Secondary Analytic Approaches to the Primary Outcome

**【中文译文段落】**（原始模型输出（未经对齐组装））

> a. 主要终点：疼痛对日常活动的影响程度（即简明疼痛量表中的第9个问题，由7个0至10分的子问题构成的平均值）是本研究的主要终点指标。在骨关节炎相关疼痛研究中，疼痛严重程度也是最常报告的主要结局指标。不过也有部分患者会选择增加活动量，即便这意味着承受他们已能适应的疼痛水平；因此“疼痛对日常活动的干扰程度”同样值得重点关注 (12, 23)。

### NCT03008590·条目 19：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_49588690410735b44a0c76b9`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 5 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_5:numeric_tokens_changed`）
  - 译文第 5 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_5:negation_signal_missing`）
  - 译文第 5 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_5:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> Use of any opioid agonist, including tramadol, is an exclusion criterion for enrollment, and these drugs must also be avoided during the trial. If a patient must use an opioid agonist for more than 2 days during the trial, that patient must be removed from the trial, and data will be censored at the time of that treatment. Medications to treat pain must not have been increased for 8 weeks prior to enrollment. Opioids, including tramadol, may not have been used for at least 7 days prior to enrollment. If a patient must have a change in treatment (pharmacologic or non- pharmacologic) related to pain or arthritis, that patient must be removed from the trial, and data will be censored at the time of that treatment change. Stable treatment with IV medications that require pre-treatment with other medications to prevent infusion reactions (e.g., rituximab, infliximab, IVIG) will not be regarded as a change in treatment. Corticosteroid or viscosupplementation injection intended to improve musculoskeletal pain must have been given at least 8 weeks prior to enrollment. It is expected that many patients will be using acetaminophen or NSAIDs as needed before enrollment. Rather than requiring patients to move to a fixed schedule, data on use of such drugs will be collected and used in analyses.
> d. Study Procedures
> i. Recruitment
> Recruitment will occur through the clinical practices of the rheumatologists at the three main campuses of the VA Boston Healthcare System. Primary care providers will be notified about the trial and will be encouraged to contact the PI about potential participants. Pre-screening by discussion with the referring physician and review of medical records will greatly reduce the number of screening failures. Referring physicians will be asked to ask prospective
> …（中略）…
> ributed at (in person) or shortly after (by mail or in person) the first two of these visits. Patients who are unable to attend the second and/or third in-person visits may remain in the study if completed questionnaires, new questionnaires, and study drug are delivered by mail. v. Study Assessments

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 招募工作将在波士顿VA医疗系统三大院区的风湿病科医师所在的临床实践中开展。基层保健医生将获知本试验的相关信息，并被鼓励就潜在的受试者情况与PI取得联系。通过与转诊医生沟通并进行病历审查的方式开展预筛选，可大幅减少筛查失败的情况。将要求转诊医生请拟入选的受试者对过去两周内其每日平均疼痛严重程度及疼痛干扰程度进行评分（0至10分），但须叮嘱医生切勿告知患者其入选标准为年满18周岁及以上。

### NCT03008590·条目 20：g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting (objectives_endpoints)

- 条目ID：`wref_translation_item_4b3a2f5e76a065bd55a5f0e2`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_4:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting
> a. Nature of Study In determining what type of adverse events will be reported, several facts about the drug being tested and the nature of the underlying disease need to be considered. Naltrexone is an FDA approved drug at 50 mg, a dose 11-fold higher than is to be used in this study. The side effects with this higher dose – as well as a 300 mg dose that is no longer used – are described in the Prescribing Information. Side effects of low-dose naltrexone have been described in several published trials, but those encompass only about 170 patients followed for a few months. b. Study Oversight The Principal Investigator has primary oversight responsibility of this clinical trial. The IRB of the VA Boston Healthcare System has oversight responsibility for this clinical trial. A Data Monitoring Committee (DMC) will be assigned by VA Central Office. The DMC and IRB will review accrual, patterns and frequencies of all adverse events and protocol compliance every 4 months. The DMC and IRB make recommendations to the Principal Investigator regarding the continuation status of the protocol. The Principal Investigator and the research team are responsible for identifying adverse events. Adverse events and protocol compliance will be reviewed once a month by the Principal Investigator. c. Definitions This section defines the types of adverse events and outlines a process for the appropriate collecting, grading, and reporting procedures. The information in this section complies with ICH Guidelines E2A: Clinical Safety Data Management: Definitions and Standards for Expedited Reporting of the International Conference of Harmonization (ICH) Guideline for Good Clinical Practice and appl
> …（中略）…
> dered an SAE when, based upon appropriate medical judgment, it may jeopardize the patient and may require medical or surgical intervention to prevent one of the outcomes listed above.
> In addition, other events that will be reported as SAEs in conjunction with this trial include: • Pregnancy • Cancer

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 研究监督：主要研究者对本临床试验承担首要监督责任。波士顿VA医疗系统的伦理审查委员会（IRB）亦负责本试验的监督工作。VA中央办公室将委派数据监测委员会（DMC）。该DMC与IRB每4个月对受试者入组情况、各类不良事件的发生规律及频次以及方案依从性予以审查。DMC与IRB将就本试验是否可继续开展向主要研究者提出建议。主要研究者及其研究团队负责识别各类不良事件；其主要研究者本人亦每月对不良事件发生情况及方案依从性开展一次审查。

### NCT03008590·条目 21：g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting (safety)

- 条目ID：`wref_translation_item_4c02c0a7dc28acf6efe2503f`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> • Overdose of the study drug • Suspected transmission of an infectious agent (eg, pathogenic or nonpathogenic) via the study drug An unexpected adverse event is defined as any adverse experience, the specificity or severity of which is not consistent with the risks of information described in the protocol. Therefore, expected adverse events are those that are identified in the research protocol, package insert, or investigational brochure as having been previously associated with the study agents or are known consequences of a person’s medical condition and thus having the potential to arise as a consequence of participation in the study.
> d. Toxicity Grading of Adverse Events Toxicity grades will be assessed according to the NCI Common Terminology Criteria for Adverse Events (CTCAE) (http://ctep.cancer.gov/reporting/ctc.html). The purpose of using the CTCAE system is to provide a standard language to describe toxicities, to facilitate tabulation and analysis of the data and to facilitate the assessment of the clinical significance of all adverse events. The CTCAE provides the following grades and descriptions in the CTCAE manual (v4.0). Adverse events should be recorded and graded 1 to 5 according to the CTCAE grade provided below: • Grade 1 = Mild; asymptomatic or mild symptoms; clinical or diagnostic observations only; intervention not indicated. • Grade 2 = Moderate; minimal, local or noninvasive intervention indicated; limiting age appropriate instrumental activities of daily living • Grade 3 = Severe or medically significant but not immediately life-threatening; hospitalization or prolongation of hospitalization indicated; disabling; limiting self care activities of daily living • Grade 4 = Life-threatening consequences; urgent intervention indicated • Grade 5 = Death related to adverse event

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 研究药物过量
> • 怀疑通过研究药物传播了某种感染性病原体（如致病性或非致病性）
> 所谓“非预期不良事件”是指任何其特异性或严重程度与研究方案中所描述的风险信息不符的不良事件。相反，“预期不良事件”则是指那些在研究方案中、药品说明书或研究资料中被明确列为既往与所用试验药物相关，或是已知为受试者自身疾病状态所致、因而有可能因参与本研究而发生的不良事件。
> d. 不良事件的毒性分级
> 将依据美国国家癌症研究所通用术语标准不良事件分级系统（NCI CTCAE）（http://ctep.cancer.gov/reporting/ctc.html）对毒性等级进行评估。采用该CTCAE系统的目的，在于提供一套标准化的术语来描述各类毒性反应、便于数据的汇总与分析并有助于评估所有不良事件的临床意义。该CTCAE手册（第4.0版）中规定的毒性分级及其描述如下。

### NCT03008590·条目 22：Unlabelled section (schedule) (schedule) · 2

- 条目ID：`wref_translation_item_4cf5e6650bf40b7eadf22840`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_2:comparison_direction_changed`）
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_2:negation_signal_missing`）

**【原文段落】**（英文原文）

> e. Common Closing Date - Study Duration The study will close 16 weeks after enrollment of the last subject. Data will not be collected from subjects after they have completed the 16 weeks of the study.
> f. Criteria for Withdrawal of Study Medication – Early Termination • Use of any opioid agonist, including tramadol, for more than two days • Rise in AST or ALT to a level 3-fold above the upper limit of normal, or more than 2-fold above the patient’s level at baseline if that baseline was abnormal. • Decline in kidney function (drop in GFR to < 30 ml/min) • Pregnancy or nursing • Addition or discontinuation of any medication given on a scheduled basis to treat pain. For medications taken as-needed, changes in frequency will not be grounds for withdrawal; rather, patients will be asked how frequently they have been using such medications.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> f. 停用研究药物的判定标准——提前终止情形 • 使用任何阿片类激动剂（包括曲马多）超过两天。• AST或ALT水平升高至正常值上限的3倍，若基线值已异常则升至较该基线值高出2倍以上。• 肾功能下降（GFR降至30 ml/min以下）。• 妊娠或处于哺乳期。• 开始使用或停用任何用于镇痛的常规用药方案中的药物；对于按需服用的镇痛药，其使用频率的变化不构成停药依据，此时仅需询问患者此类药物的使用频次即可。

### NCT03008590·条目 23：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_4f15577202f05fadff98808a`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 24：a. Background (objectives_endpoints) · 3

- 条目ID：`wref_translation_item_585a5f995033c4f0b9299737`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> Intriguingly, 23 members of a group reporting RA (presumably overlapping with the “arthritis” group) also placed LDN with TJR and corticosteroids and seemingly above DMARDs, biologics, and non-pharmacologic therapies. In a group of patients reporting OA, only 5 commented on LDN, and only 2 of those reported benefit. In fibromyalgia, 72 respondents again gave LDN the highest rating among pharmacologic therapies, with the only approaches giving comparable relief being rest/sleep, application of heat, and stress reduction. Scanning across other disease states was both encouraging and concerning for the survey reaching a biased population: LDN was at or near the top of therapies reported in patients with multiple sclerosis (n=128), fatigue (n=112), Crohn’s disease (n=33), neuropathy (v=22), Sjogren’s syndrome (v=9), Hashimoto’s (v=9), psoriasis (v=7), hepatitis C (v=6), sarcoidosis (v=4), symptom relief in breast cancer (v=4) or non-small-cell lung cancer (v=4), psoriatic arthritis (v=3), ankylosing spondylitis (v=3), polymyositis (v=3), scleroderma (v=3), HIV (v=2), lupus (v=1), and complex partial seizures (v=1). Reassuringly with regard to bias based on belief systems, LDN was not reported as being reliably helpful in 4-20 patients each with irritable bowel syndrome, anxiety, depression, asthma, dandruff, Raynaud’s, night cramps, Lyme disease, low back pain, or prostate cancer. Reassuringly with regard to possible bias by the survey designers, LDN was not suggested as an option for diabetes, COPD, gout, eczema, congestive heart failure, or many other conditions. These data provide further support that LDN may provide an important advance in management of pain and other symptoms – particularly in inflammatory diseases – but do little to alleviate the concern that hype has
> …（中略）…
> ion.
> The study also includes the four outcome domains identified by consensus in the Initiative on Methods, Measurement, and Pain Assessment in Clinical Trials (IMMPACT): pain intensity, physical functioning, emotional functioning, and global rating of improvement (12).
> b. Identification of Patients

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 有趣的是，在报告患有RA的23名受试者中（该群体很可能与前述“关节炎”组存在重叠），他们同样将LDN排在TJR、皮质类固醇之后，且似乎也将其置于DMARDs、生物制剂以及非药物疗法之前。而在报告患有OA的患者组中，仅有5人提及LDN，其中仅2名受试者表示该药带来了疗效。在纤维肌痛患者群体中，共有72人将LDN评为各类药物治疗手段中的首选；能带来类似缓解效果的其他方式仅为休息/睡眠、热敷以及减压。对其他各类疾病患者的调查结果既令人鼓舞又引发担忧，因为该调查样本可能存在偏差：在多发性硬化症（n=128）、疲劳症状患者（n=112）、克罗恩病患者（n=33）、神经病变患者（v=22）、干燥综合征患者（v=9）、桥本氏病患者（v=9）、银屑病患者（v=7）、丙型肝炎患者（v=6）以及结节病、乳腺癌症状缓解需求者中，LDN均位列治疗手段前列或接近榜首。

### NCT03008590·条目 25：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_5cbe1d86761aa0100e085d3c`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 26：g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting (objectives_endpoints)

- 条目ID：`wref_translation_item_5e46969df285818c40773af1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_4:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting
> a. Nature of Study In determining what type of adverse events will be reported, several facts about the drug being tested and the nature of the underlying disease need to be considered. Naltrexone is an FDA approved drug at 50 mg, a dose 11-fold higher than is to be used in this study. The side effects with this higher dose – as well as a 300 mg dose that is no longer used – are described in the Prescribing Information. Side effects of low-dose naltrexone have been described in several published trials, but those encompass only about 170 patients followed for a few months. b. Study Oversight The Principal Investigator has primary oversight responsibility of this clinical trial. The IRB of the VA Boston Healthcare System has oversight responsibility for this clinical trial. A Data Monitoring Committee (DMC) will be assigned by VA Central Office. The DMC and IRB will review accrual, patterns and frequencies of all adverse events and protocol compliance every 4 months. The DMC and IRB make recommendations to the Principal Investigator regarding the continuation status of the protocol. The Principal Investigator and the research team are responsible for identifying adverse events. Adverse events and protocol compliance will be reviewed once a month by the Principal Investigator. c. Definitions This section defines the types of adverse events and outlines a process for the appropriate collecting, grading, and reporting procedures. The information in this section complies with ICH Guidelines E2A: Clinical Safety Data Management: Definitions and Standards for Expedited Reporting of the International Conference of Harmonization (ICH) Guideline for Good Clinical Practice and appl
> …（中略）…
> dered an SAE when, based upon appropriate medical judgment, it may jeopardize the patient and may require medical or surgical intervention to prevent one of the outcomes listed above.
> In addition, other events that will be reported as SAEs in conjunction with this trial include: • Pregnancy • Cancer

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 研究监督：主要研究者对本临床试验承担首要监督责任。波士顿VA医疗系统的伦理审查委员会（IRB）亦负责本试验的监督工作。VA中央办公室将委派数据监测委员会（DMC）。该DMC与IRB每4个月对受试者入组情况、各类不良事件的发生规律及频次以及方案依从性予以审查。DMC与IRB将就本试验是否可继续开展向主要研究者提出建议。主要研究者及其研究团队负责识别各类不良事件；其主要研究者本人亦每月对不良事件发生情况及方案依从性开展一次审查。

### NCT03008590·条目 27：i. Recruitment (objectives_endpoints)

- 条目ID：`wref_translation_item_5edf307e846c738dfb09eea2`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 1). Study Assessment Patient-reported outcomes will be reported weekly on paper forms. Subjects may receive reminders by phone. The outcome measures used will be: Primary outcome measure (all patients): • Brief Pain Inventory-short form (BPI) (33): The BPI is a 9-item self-report questionnaire that allows patients to rate the severity of their pain and the degree to which their pain interferes with common dimensions of feeling and function. For the purpose of the proposed study, we will be particularly interested in pain “interference”. A recent consensus panel recommended that the two domains measured by the BPI – pain intensity (severity) and the impact of pain on functioning (interference) – be included as outcomes in all chronic-pain clinical trials (IMMPACT, (34)). The IMMPACT panel (www.immpact.org) specifically identified the interference items of the BPI, rated on a 0–10 scale, as one of the two scales recommended for assessment of pain-related functional impairment (35). It has excellent reliability and validity and it has been used widely in OA research (36). (weekly questionnaire)
> Secondary outcome measures: • Brief Pain Inventory short form, other questions than those used for the primary outcome, particularly question 5, average pain severity (weekly) • painDETECT (for neuropathic component of pain) (37, 38) (only at weeks 0, 4, 8, 12, and 16) • PROMIS-29 (survey of quality of life in multiple domains) (40) (only at weeks 0, 4, 8, 12, and 16) • Brief Fatigue Inventory, specifically question 2 (usual level in past 24 hours, 0-10) and question 4 (interference in the past 24 hours, average of 6 questions 0-10 each) • Beck Depression Inventory-II (purchase pending), a widely used 21-question assessment of the severity of depression (only at weeks 0, 4, 8, 12, 1
> …（中略）…
>  between treatment periods is appropriate; inclusion of a protocolized “wash-out” period is a common design in cross-over studies. Because there is no defined wash-out period in this study, the analysis plan already included omission of data from the first two weeks after cross-over (see Section 7).

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 1). 研究评估：患者报告结局将每周通过纸质表格进行记录。研究者可通过电话提醒受试者填写问卷。本研究采用的评估指标如下：主要患者报告结局（适用于所有患者）：• 简明疼痛量表简版（BPI）（33）。该量表是一项包含9个条目的自我报告式问卷，可帮助患者评估自身疼痛的严重程度以及该疼痛对其情绪与功能各方面的影响程度。在本研究中，我们重点关注“疼痛对功能的干扰”这一指标。近期由相关专家组成的共识小组建议：所有慢性疼痛临床试验均应将简明疼痛量表所测定的两个维度——即疼痛强度（严重程度）以及疼痛对功能的影响程度纳入评估指标之列（IMMPACT，(34)）。该共识小组（www.immpact.org）特别指出，以0至10分进行评分的简明疼痛量表中的功能干扰相关条目属于推荐用于评估疼痛所致功能障碍的两项指标之一（35）。该量表具备极佳的可靠性与有效性，并已在骨关节炎相关研究中被广泛采用（36）。（每周填写一次问卷）

### NCT03008590·条目 28：a. Background (objectives_endpoints) · 3

- 条目ID：`wref_translation_item_675b48fcaefa181e11416201`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> Intriguingly, 23 members of a group reporting RA (presumably overlapping with the “arthritis” group) also placed LDN with TJR and corticosteroids and seemingly above DMARDs, biologics, and non-pharmacologic therapies. In a group of patients reporting OA, only 5 commented on LDN, and only 2 of those reported benefit. In fibromyalgia, 72 respondents again gave LDN the highest rating among pharmacologic therapies, with the only approaches giving comparable relief being rest/sleep, application of heat, and stress reduction. Scanning across other disease states was both encouraging and concerning for the survey reaching a biased population: LDN was at or near the top of therapies reported in patients with multiple sclerosis (n=128), fatigue (n=112), Crohn’s disease (n=33), neuropathy (v=22), Sjogren’s syndrome (v=9), Hashimoto’s (v=9), psoriasis (v=7), hepatitis C (v=6), sarcoidosis (v=4), symptom relief in breast cancer (v=4) or non-small-cell lung cancer (v=4), psoriatic arthritis (v=3), ankylosing spondylitis (v=3), polymyositis (v=3), scleroderma (v=3), HIV (v=2), lupus (v=1), and complex partial seizures (v=1). Reassuringly with regard to bias based on belief systems, LDN was not reported as being reliably helpful in 4-20 patients each with irritable bowel syndrome, anxiety, depression, asthma, dandruff, Raynaud’s, night cramps, Lyme disease, low back pain, or prostate cancer. Reassuringly with regard to possible bias by the survey designers, LDN was not suggested as an option for diabetes, COPD, gout, eczema, congestive heart failure, or many other conditions. These data provide further support that LDN may provide an important advance in management of pain and other symptoms – particularly in inflammatory diseases – but do little to alleviate the concern that hype has
> …（中略）…
> ion.
> The study also includes the four outcome domains identified by consensus in the Initiative on Methods, Measurement, and Pain Assessment in Clinical Trials (IMMPACT): pain intensity, physical functioning, emotional functioning, and global rating of improvement (12).
> b. Identification of Patients

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 有趣的是，在报告患有RA的23名受试者中（该群体很可能与前述“关节炎”组存在重叠），他们同样将LDN排在TJR、皮质类固醇之后，且似乎也将其置于DMARDs、生物制剂以及非药物疗法之前。而在报告患有OA的患者组中，仅有5人提及LDN，其中仅2名受试者表示该药带来了疗效。在纤维肌痛患者群体中，共有72人将LDN评为各类药物治疗手段中的首选；能带来类似缓解效果的其他方式仅为休息/睡眠、热敷以及减压。对其他各类疾病患者的调查结果既令人鼓舞又引发担忧，因为该调查样本可能存在偏差：在多发性硬化症（n=128）、疲劳症状患者（n=112）、克罗恩病患者（n=33）、神经病变患者（v=22）、干燥综合征患者（v=9）、桥本氏病患者（v=9）、银屑病患者（v=7）、丙型肝炎患者（v=6）以及结节病、乳腺癌症状缓解需求者中，LDN均位列治疗手段前列或接近榜首。

### NCT03008590·条目 29：a. Registration (objectives_endpoints) · 3

- 条目ID：`wref_translation_item_74c52a891d8fecae52a5da0b`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 13 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_13:numeric_tokens_changed`）
  - 译文第 13 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_13:untranslated_source_connector`）

**【原文段落】**（英文原文）

> 27. Cree BA, Kornyeyeva E, Goodin DS. Pilot trial of low-dose naltrexone and quality of life in multiple sclerosis. Annals of neurology. 2010 Aug;68(2):145-50. PubMed PMID: 20695007. 28. Chopra P, Cooper MS. Treatment of Complex Regional Pain Syndrome (CRPS) using low dose naltrexone (LDN). Journal of neuroimmune pharmacology : the official journal of the Society on NeuroImmune Pharmacology. 2013 Jun;8(3):470-6. PubMed PMID: 23546884. Pubmed Central PMCID: 3661907. 29. Ghai B, Bansal D, Hota D, Shah CS. Off-label, low-dose naltrexone for refractory chronic low back pain. Pain medicine. 2014 May;15(5):883-4. PubMed PMID: 24967470. 30. Frech T, Novak K, Revelo MP, Murtaugh M, Markewitz B, Hatton N, et al. Low-dose naltrexone for pruritus in systemic sclerosis. Int J Rheumatol. 2011;2011:804296. PubMed PMID: 21918649. Pubmed Central PMCID: 3171757. 31. Younger J, Parkitny L, McLain D. The use of low-dose naltrexone (LDN) as a novel anti- inflammatory treatment for chronic pain. Clin Rheumatol. 2014 Apr;33(4):451-9. PubMed PMID: 24526250. Pubmed Central PMCID: 3962576. 32. Chappell AS, Desaiah D, Liu-Seifert H, Zhang S, Skljarevski V, Belenkov Y, et al. A double-blind, randomized, placebo-controlled study of the efficacy and safety of duloxetine for the treatment of chronic pain due to osteoarthritis of the knee. Pain practice : the official journal of World Institute of Pain. 2011 Jan-Feb;11(1):33-41. PubMed PMID: 20602715. 33. Cleeland CS, Ryan KM. Pain assessment: global use of the Brief Pain Inventory. Annals of the Academy of Medicine, Singapore. 1994 Mar;23(2):129-38. PubMed PMID: 8080219. 34. Turk DC, Dworkin RH, Allen RR, Bellamy N, Brandenburg N, Carr DB, et al. Core outcome domains for chronic pain clinical trials: IMMPACT recommendations. Pain. 2003 Dec;106(3):33
> …（中略）…
> outcome measures in systemic sclerosis: Patient-Reported Outcomes Measurement Information System 29-item Health Profile and Functional Assessment of Chronic Illness Therapy-Dyspnea short form. Arthritis Care Res (Hoboken). 2011 Nov;63(11):1620-8. PubMed PMID: 22034123. Pubmed Central PMCID: 3205420.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 37. Freynhagen R, Baron R, Gockel U, Tolle TR。painDETECT：一种用于识别背痛患者中是否存在神经病理性疼痛成分的新型筛查问卷。《Current Medical Research and Opinion》杂志，2006年10月；第22卷，第10期：1911-1920页。PubMed PMID: 17022849。

### NCT03008590·条目 30：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_75f83f9a9e010b554747deee`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 31：a. Registration (objectives_endpoints)

- 条目ID：`wref_translation_item_777580cc2bae154da3406f8d`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_2:numeric_tokens_changed`）
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> d. Data Quality Control As an assessment of compliance with treatment, patients will be asked to return the previous containers of study drug at the next in-person visit, and asked not to throw out any extra doses that might remain because they forgot to take them. At the second and third in-person study visits, it will be clear to the study coordinator which patients are completing study questionnaires and which are not. One of the reasons for planning to average the results of patient-reported outcome measures at multiple time points in a weighted manner is so that data will still be usable if a patient only completes the forms at in-person visits. At in-person visits, patients will complete questionnaires without the participation of the investigator of coordinator, since their presence might influence reporting compared to data recorded when alone. Two steps will be taken to maximize the numbers of patients who complete all 3 in-person visits. First, they will be given a financial incentive at a level that is not expected to raise concerns about coercion: $20 for the screening visit, $20 for visit 2, $20 for visit 3, and an additional $20 at visit 3 if all 3 visits were completed. Second, the study coordinator and PI will arrange schedules such that patients can be seen at at least 2 of the 3 campuses of the VA Boston Healthcare System. 9. Protection of Human Subjects
> a. GCP Statement This clinical trial will be conducted in accordance with the ethical principles that have their origin in the Declaration of Helsinki, and that are consistent with Good Clinical Practice and all applicable regulatory requirements. b. Benefits and Risks The potential benefits of participating in this study are improvement in pain and/or improvement in function as limited by pain. The potential risks of this study are side effects of naltrexone, delay in seeking other approaches to pain management, and potential loss of confidentiality.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 首先，我们将向受试者提供一定数额的经济激励；该金额预计不会引发强制性方面的顾虑：筛选访视时发放20美元，第2次访视时发放20美元，第3次访视时也发放20美元；若受试者完成了全部三次访视，则在第3次访视时再额外发放20美元。其次，研究协调员与主要研究者将共同安排日程，确保每位患者都能在波士顿VA医疗系统的三个院区中至少两个地点接受诊疗。

### NCT03008590·条目 32：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_79c299e870f1ec3919e929b1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> 2. Study Abstract (summary for lay-persons) Naltrexone is an FDA approved drug (for alcoholism) that has found widespread use “off-label” to treat pain and fatigue at much lower doses than are used for the approved indication. There are a few scientific studies in three conditions (fibromyalgia, Crohn's disease, and multiple sclerosis) that suggest that this drug has benefit and is safe. However, considering the extent of use in other conditions, and uncertainty about the mechanism of action (purely a pain reliever? other benefits on brain chemistry? anti-inflammatory?), study is needed in diverse diseases. The current study is intended to generate preliminary data in several rheumatologic conditions (osteoarthritis and multiple forms of inflammatory arthritis) in order to select such conditions for future study in larger clinical trials. Although it is a pilot study, a placebo- controlled component is used because of the prominent placebo group effect seen in studies in which self-reported pain is the main outcome. A "blinded cross-over" design is used so that patients will not know when they might be transitioning between placebo and naltrexone. 3. Study Endpoints
> a. Primary Outcome
> • Average interference of pain with general activity (question 9 on the Brief Pain Inventory, an average of 7 sub-questions, each 0-10) will be compared during naltrexone treatment and during placebo treatment. b. Secondary Outcomes
> The secondary outcome measures include : • Brief Pain Inventory [other individual questions than those used for the primary outcome, particularly question 5 (average pain severity)] • painDETECT (continuous measure 0-38, or classified as nociceptive/unclear/neuropathic per the questionnaire guidelines) • Brief Fatigue Inventory, specifically question 2 (usual l
> …（中略）…
> , collected using the IRB’s and DMC’s standard forms
> Secondary outcome measures for specific diseases: • Rheumatoid arthritis: DAS28, as a continuous measure or classified as good/moderate/no response per EULAR criteria • Spondyloarthritis: BASDAI, as a continuous measure 4. Background and Rationale

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 2. 研究摘要（面向普通大众的概述）纳曲酮是一种经FDA批准用于治疗酒精依赖的药物，目前该药在未经官方适应症许可的情况下被广泛使用：以远低于获批用途的剂量来治疗疼痛与疲劳。目前已有少量科学研究针对三种疾病（纤维肌痛、克罗恩病及多发性硬化症）开展，结果显示该药具有疗效且安全性良好。然而鉴于其在其他多种疾病中的使用频率较高，加之对其作用机制尚不明确（仅具备镇痛效果？是否对脑内生化环境有其他影响？是否具有抗炎作用？），因此有必要在更多疾病中开展相关研究。本研究旨在针对多种风湿性疾病（骨关节炎及各类炎症性关节炎）获取初步数据，从而为后续更大规模的临床试验筛选合适的研究病种。尽管本研究属于探索性试验，但由于以受试者自我报告的疼痛程度为主要评价指标时常会出现明显的安慰剂效应，故本研究仍设置了安慰剂对照组。此外研究采用了“盲法交叉设计”，以确保患者无法知晓自己何时会从接受安慰剂治疗转为使用纳曲酮治疗。

### NCT03008590·条目 33：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_7bd0a16a21e704b5cf15baa1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 34：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_7f29d3e845d36d301f846a9b`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> 2. Study Abstract (summary for lay-persons) Naltrexone is an FDA approved drug (for alcoholism) that has found widespread use “off-label” to treat pain and fatigue at much lower doses than are used for the approved indication. There are a few scientific studies in three conditions (fibromyalgia, Crohn's disease, and multiple sclerosis) that suggest that this drug has benefit and is safe. However, considering the extent of use in other conditions, and uncertainty about the mechanism of action (purely a pain reliever? other benefits on brain chemistry? anti-inflammatory?), study is needed in diverse diseases. The current study is intended to generate preliminary data in several rheumatologic conditions (osteoarthritis and multiple forms of inflammatory arthritis) in order to select such conditions for future study in larger clinical trials. Although it is a pilot study, a placebo- controlled component is used because of the prominent placebo group effect seen in studies in which self-reported pain is the main outcome. A "blinded cross-over" design is used so that patients will not know when they might be transitioning between placebo and naltrexone. 3. Study Endpoints
> a. Primary Outcome
> • Average interference of pain with general activity (question 9 on the Brief Pain Inventory, an average of 7 sub-questions, each 0-10) will be compared during naltrexone treatment and during placebo treatment. b. Secondary Outcomes
> The secondary outcome measures include : • Brief Pain Inventory [other individual questions than those used for the primary outcome, particularly question 5 (average pain severity)] • painDETECT (continuous measure 0-38, or classified as nociceptive/unclear/neuropathic per the questionnaire guidelines) • Brief Fatigue Inventory, specifically question 2 (usual l
> …（中略）…
> , collected using the IRB’s and DMC’s standard forms
> Secondary outcome measures for specific diseases: • Rheumatoid arthritis: DAS28, as a continuous measure or classified as good/moderate/no response per EULAR criteria • Spondyloarthritis: BASDAI, as a continuous measure 4. Background and Rationale

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 2. 研究摘要（面向普通大众的概述）纳曲酮是一种经FDA批准用于治疗酒精依赖的药物，目前该药在未经官方适应症许可的情况下被广泛使用：以远低于获批用途的剂量来治疗疼痛与疲劳。目前已有少量科学研究针对三种疾病（纤维肌痛、克罗恩病及多发性硬化症）开展，结果显示该药具有疗效且安全性良好。然而鉴于其在其他多种疾病中的使用频率较高，加之对其作用机制尚不明确（仅具备镇痛效果？是否对脑内生化环境有其他影响？是否具有抗炎作用？），因此有必要在更多疾病中开展相关研究。本研究旨在针对多种风湿性疾病（骨关节炎及各类炎症性关节炎）获取初步数据，从而为后续更大规模的临床试验筛选合适的研究病种。尽管本研究属于探索性试验，但由于以受试者自我报告的疼痛程度为主要评价指标时常会出现明显的安慰剂效应，故本研究仍设置了安慰剂对照组。此外研究采用了“盲法交叉设计”，以确保患者无法知晓自己何时会从接受安慰剂治疗转为使用纳曲酮治疗。

### NCT03008590·条目 35：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_8a8a829f365836cc91a03a1f`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 36：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_8c7ffece9fef2812a0f2f1cc`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 37：a. Background (safety)

- 条目ID：`wref_translation_item_8cf49530f0acdde8ac5c9183`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_1:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> be viewed with skepticism because of massive selection bias and uncertainty about the patients’ diagnoses. Considering the modest benefit of other options, use of LDN will continue or increase in the absence of studies that support its effectiveness and systematically gather data on safety. Since the drug can be prescribed but only via compounding pharmacies, its use produces significant cost to patients (~$40/month). What makes LDN of greater interest than most unproven treatments for arthritic pain is a combination of pharmacologic plausibility, the afore mentioned trials in other painful conditions, and striking results of an internet-based survey (http://curetogether.com/Arthritis/ig/treatment-effectiveness-vs-popularity). The survey itself was unbiased in asking persons to rate a large number of approaches they might have used for arthritic pain, but there was no way to validate what type of arthritis the participants had, and the population of responders (who sign up as members based on self-reported conditions) was undoubtedly biased in multiple ways. That being acknowledged, LDN was ranked as high as any therapy, and most notably, the other therapies that did as well are known to be highly effective in IA or OA (Enbrel, oral or injectable corticosteroids, TJR), whereas the numerous approaches that did not perform as well include all of the pharmacologic and non-pharmacologic approaches known to provide mediocre benefit based on randomized trials (Fig. 1). On closer inspection, the survey is not nearly as large as it appears: although the group has 1554 members, fewer than 200 produced the 2127 total evaluations of all therapies, and only 17 persons commented on LDN.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 这些研究结果值得审慎看待，因为其中存在严重的选择偏倚且受试者的诊断情况尚不确定。鉴于其他治疗方案的疗效也较为有限，在缺乏能证实LDN有效性并系统收集其安全性数据的临床研究的情况下，该药物的使用仍会持续甚至增多。由于LDN只能通过配制药房开具处方使用，因此患者需承担较高的用药成本（约每月40美元）。相较于大多数尚未被证实有效的关节炎疼痛治疗方案，LDN之所以更受关注，主要归因于其药理机制具备合理性、前文提及的在其他疼痛性疾病中的相关试验结果，以及一项基于互联网的调查所得出的显著结论（http://curetogether.com/Arthritis/ig/treatment-effectiveness-vs-popularity）。该调查在要求受试者对多种可能用于缓解关节炎疼痛的治疗方式进行评分时保持了中立性，但无法核实这些受试者所患的究竟是哪种类型的关节炎；此外，参与调查的人群（即根据自身病情自愿注册成为会员的人士）无疑在多方面存在选择偏倚。

### NCT03008590·条目 38：a. Background (objectives_endpoints) · 3

- 条目ID：`wref_translation_item_8e29c99bd972839ed2bc6eba`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> Intriguingly, 23 members of a group reporting RA (presumably overlapping with the “arthritis” group) also placed LDN with TJR and corticosteroids and seemingly above DMARDs, biologics, and non-pharmacologic therapies. In a group of patients reporting OA, only 5 commented on LDN, and only 2 of those reported benefit. In fibromyalgia, 72 respondents again gave LDN the highest rating among pharmacologic therapies, with the only approaches giving comparable relief being rest/sleep, application of heat, and stress reduction. Scanning across other disease states was both encouraging and concerning for the survey reaching a biased population: LDN was at or near the top of therapies reported in patients with multiple sclerosis (n=128), fatigue (n=112), Crohn’s disease (n=33), neuropathy (v=22), Sjogren’s syndrome (v=9), Hashimoto’s (v=9), psoriasis (v=7), hepatitis C (v=6), sarcoidosis (v=4), symptom relief in breast cancer (v=4) or non-small-cell lung cancer (v=4), psoriatic arthritis (v=3), ankylosing spondylitis (v=3), polymyositis (v=3), scleroderma (v=3), HIV (v=2), lupus (v=1), and complex partial seizures (v=1). Reassuringly with regard to bias based on belief systems, LDN was not reported as being reliably helpful in 4-20 patients each with irritable bowel syndrome, anxiety, depression, asthma, dandruff, Raynaud’s, night cramps, Lyme disease, low back pain, or prostate cancer. Reassuringly with regard to possible bias by the survey designers, LDN was not suggested as an option for diabetes, COPD, gout, eczema, congestive heart failure, or many other conditions. These data provide further support that LDN may provide an important advance in management of pain and other symptoms – particularly in inflammatory diseases – but do little to alleviate the concern that hype has
> …（中略）…
> ion.
> The study also includes the four outcome domains identified by consensus in the Initiative on Methods, Measurement, and Pain Assessment in Clinical Trials (IMMPACT): pain intensity, physical functioning, emotional functioning, and global rating of improvement (12).
> b. Identification of Patients

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 有趣的是，在报告患有RA的23名受试者中（该群体很可能与前述“关节炎”组存在重叠），他们同样将LDN排在TJR、皮质类固醇之后，且似乎也将其置于DMARDs、生物制剂以及非药物疗法之前。而在报告患有OA的患者组中，仅有5人提及LDN，其中仅2名受试者表示该药带来了疗效。在纤维肌痛患者群体中，共有72人将LDN评为各类药物治疗手段中的首选；能带来类似缓解效果的其他方式仅为休息/睡眠、热敷以及减压。对其他各类疾病患者的调查结果既令人鼓舞又引发担忧，因为该调查样本可能存在偏差：在多发性硬化症（n=128）、疲劳症状患者（n=112）、克罗恩病患者（n=33）、神经病变患者（v=22）、干燥综合征患者（v=9）、桥本氏病患者（v=9）、银屑病患者（v=7）、丙型肝炎患者（v=6）以及结节病、乳腺癌症状缓解需求者中，LDN均位列治疗手段前列或接近榜首。

### NCT03008590·条目 39：i. Inclusion Criteria (eligibility)

- 条目ID：`wref_translation_item_931dff9cb2ec5f0de237b178`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）

**【原文段落】**（英文原文）

> i. Inclusion Criteria
> Patients must meet all of the following criteria in order to be eligible for enrollment: • One or more of the following chronic conditions: osteoarthritis, rheumatoid arthritis, peripheral spondyloarthritis (which may include shoulder or hip involvement) • Average daily pain interference with function (average of the 7 parts of question 9 on the BPI) rated at least 4 on a scale of 0-10, and no higher than 9 • No increase in medication in the past 8 weeks made with the expectation of improving pain, including acetaminophen, any NSAID, any opioid, tramadol, gabapentin, pregabalin, cyclobenzaprine, any tricyclic antidepressant, duloxetine, systemic or injectable corticosteroids, or injectable viscosupplements • No plan to start another medication or a non-pharmacologic treatment regimen likely to affect pain during the next 16 weeks • Age at least 18 • Capable of informed consent, and willingness to comply with study procedures, including receipt of weekly phone calls from the study coordinator ii. Exclusion Criteria
> • Use of opioids, including tramadol, in the past 7 days (determined by asking participant if they have used any opioid containing medications in the past 7 days or plan to use any opioid containing medications) • Pregnant, breast feeding, or unwilling to engage in contraceptive practices if sexually active and capable of conceiving (determined by asking participant if they are pregnant or breast feeding or plan to become pregnant during the duration of the study) • Schizophrenia, bipolar disorder, or poorly controlled depression or anxiety • Previous use of naltrexone for more than 8 weeks or in the past 2 weeks, at a low dose or FDA approved dose • Back pain described by the patient as greater in severity than arthritic pain in all peri
> …（中略）…
> n arthritic pain. There is no specific screening procedure. • Plan to have surgery during the next 16 weeks
> • Other qualitative circumstances that the investigator feels would make the patient a poor candidate for this clinical trial, such as an unstable social situation or unreliable transportation

**【中文译文段落】**（原始模型输出（未经对齐组装））

> i. 纳入标准
> 符合以下所有标准的患者方可入选本研究：
> • 患有一种或多种下述慢性疾病：骨关节炎、类风湿关节炎、外周型脊柱关节炎（可累及肩部或髋部）
> • 根据BPI量表第9题的7个分项评分平均值计算，每日疼痛对功能的影响程度在0至10分的量表上至少为4分且不超过9分
> • 过去8周内未出于缓解疼痛的目的增加任何药物的使用剂量，此类药物包括对乙酰氨基酚、各类NSAID、所有阿片类药物、曲马多、加巴喷丁、普瑞巴林、环苯扎林、各类三环类抗抑郁药、度洛西汀、全身或注射型皮质类固醇以及注射用黏弹性补充剂
> • 未来16周内无开始使用其他药物或实施可能影响疼痛程度的非药物治疗方案的计划
> • 年龄满18周岁及以上
> • 具备作出知情同意的能力，且愿意配合完成研究流程，包括接听研究协调员每周打来的电话
> ii. 排除标准

### NCT03008590·条目 40：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_94b07fe0cd603593bc5bcc02`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 41：g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting (objectives_endpoints)

- 条目ID：`wref_translation_item_981b70782b5163a64ca605df`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_4:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting
> a. Nature of Study In determining what type of adverse events will be reported, several facts about the drug being tested and the nature of the underlying disease need to be considered. Naltrexone is an FDA approved drug at 50 mg, a dose 11-fold higher than is to be used in this study. The side effects with this higher dose – as well as a 300 mg dose that is no longer used – are described in the Prescribing Information. Side effects of low-dose naltrexone have been described in several published trials, but those encompass only about 170 patients followed for a few months. b. Study Oversight The Principal Investigator has primary oversight responsibility of this clinical trial. The IRB of the VA Boston Healthcare System has oversight responsibility for this clinical trial. A Data Monitoring Committee (DMC) will be assigned by VA Central Office. The DMC and IRB will review accrual, patterns and frequencies of all adverse events and protocol compliance every 4 months. The DMC and IRB make recommendations to the Principal Investigator regarding the continuation status of the protocol. The Principal Investigator and the research team are responsible for identifying adverse events. Adverse events and protocol compliance will be reviewed once a month by the Principal Investigator. c. Definitions This section defines the types of adverse events and outlines a process for the appropriate collecting, grading, and reporting procedures. The information in this section complies with ICH Guidelines E2A: Clinical Safety Data Management: Definitions and Standards for Expedited Reporting of the International Conference of Harmonization (ICH) Guideline for Good Clinical Practice and appl
> …（中略）…
> dered an SAE when, based upon appropriate medical judgment, it may jeopardize the patient and may require medical or surgical intervention to prevent one of the outcomes listed above.
> In addition, other events that will be reported as SAEs in conjunction with this trial include: • Pregnancy • Cancer

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 研究监督：主要研究者对本临床试验承担首要监督责任。波士顿VA医疗系统的伦理审查委员会（IRB）亦负责本试验的监督工作。VA中央办公室将委派数据监测委员会（DMC）。该DMC与IRB每4个月对受试者入组情况、各类不良事件的发生规律及频次以及方案依从性予以审查。DMC与IRB将就本试验是否可继续开展向主要研究者提出建议。主要研究者及其研究团队负责识别各类不良事件；其主要研究者本人亦每月对不良事件发生情况及方案依从性开展一次审查。

### NCT03008590·条目 42：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_9a1a00203aa19c9d2b4c3834`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_3:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Safety and Monitoring
> Standardized definitions and timelines will be used for the reporting of serious and non-serious adverse events.
> A VA-assigned Data Monitoring Committee (DMC) and the Institutional Review Board of the VA Boston Healthcare System will monitor safety and all other aspects of the study.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 由美国退伍军人事务部指定的数据监测委员会（DMC）以及波士顿退伍军人医疗系统机构审查委员会将负责监督本研究的安全性及其他各项事宜。

### NCT03008590·条目 43：g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting (safety)

- 条目ID：`wref_translation_item_a6215882addbc322f8eab916`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> • Overdose of the study drug • Suspected transmission of an infectious agent (eg, pathogenic or nonpathogenic) via the study drug An unexpected adverse event is defined as any adverse experience, the specificity or severity of which is not consistent with the risks of information described in the protocol. Therefore, expected adverse events are those that are identified in the research protocol, package insert, or investigational brochure as having been previously associated with the study agents or are known consequences of a person’s medical condition and thus having the potential to arise as a consequence of participation in the study.
> d. Toxicity Grading of Adverse Events Toxicity grades will be assessed according to the NCI Common Terminology Criteria for Adverse Events (CTCAE) (http://ctep.cancer.gov/reporting/ctc.html). The purpose of using the CTCAE system is to provide a standard language to describe toxicities, to facilitate tabulation and analysis of the data and to facilitate the assessment of the clinical significance of all adverse events. The CTCAE provides the following grades and descriptions in the CTCAE manual (v4.0). Adverse events should be recorded and graded 1 to 5 according to the CTCAE grade provided below: • Grade 1 = Mild; asymptomatic or mild symptoms; clinical or diagnostic observations only; intervention not indicated. • Grade 2 = Moderate; minimal, local or noninvasive intervention indicated; limiting age appropriate instrumental activities of daily living • Grade 3 = Severe or medically significant but not immediately life-threatening; hospitalization or prolongation of hospitalization indicated; disabling; limiting self care activities of daily living • Grade 4 = Life-threatening consequences; urgent intervention indicated • Grade 5 = Death related to adverse event

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 研究药物过量
> • 怀疑通过研究药物传播了某种感染性病原体（如致病性或非致病性）
> 所谓“非预期不良事件”是指任何其特异性或严重程度与研究方案中所描述的风险信息不符的不良事件。相反，“预期不良事件”则是指那些在研究方案中、药品说明书或研究资料中被明确列为既往与所用试验药物相关，或是已知为受试者自身疾病状态所致、因而有可能因参与本研究而发生的不良事件。
> d. 不良事件的毒性分级
> 将依据美国国家癌症研究所通用术语标准不良事件分级系统（NCI CTCAE）（http://ctep.cancer.gov/reporting/ctc.html）对毒性等级进行评估。采用该CTCAE系统的目的，在于提供一套标准化的术语来描述各类毒性反应、便于数据的汇总与分析并有助于评估所有不良事件的临床意义。该CTCAE手册（第4.0版）中规定的毒性分级及其描述如下。

### NCT03008590·条目 44：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_a62e781ec0621f529ad05a3a`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 45：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_b1e5ee23c52e620fee357d9d`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 46：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_baf69712a355460e173e34e4`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> 2. Study Abstract (summary for lay-persons) Naltrexone is an FDA approved drug (for alcoholism) that has found widespread use “off-label” to treat pain and fatigue at much lower doses than are used for the approved indication. There are a few scientific studies in three conditions (fibromyalgia, Crohn's disease, and multiple sclerosis) that suggest that this drug has benefit and is safe. However, considering the extent of use in other conditions, and uncertainty about the mechanism of action (purely a pain reliever? other benefits on brain chemistry? anti-inflammatory?), study is needed in diverse diseases. The current study is intended to generate preliminary data in several rheumatologic conditions (osteoarthritis and multiple forms of inflammatory arthritis) in order to select such conditions for future study in larger clinical trials. Although it is a pilot study, a placebo- controlled component is used because of the prominent placebo group effect seen in studies in which self-reported pain is the main outcome. A "blinded cross-over" design is used so that patients will not know when they might be transitioning between placebo and naltrexone. 3. Study Endpoints
> a. Primary Outcome
> • Average interference of pain with general activity (question 9 on the Brief Pain Inventory, an average of 7 sub-questions, each 0-10) will be compared during naltrexone treatment and during placebo treatment. b. Secondary Outcomes
> The secondary outcome measures include : • Brief Pain Inventory [other individual questions than those used for the primary outcome, particularly question 5 (average pain severity)] • painDETECT (continuous measure 0-38, or classified as nociceptive/unclear/neuropathic per the questionnaire guidelines) • Brief Fatigue Inventory, specifically question 2 (usual l
> …（中略）…
> , collected using the IRB’s and DMC’s standard forms
> Secondary outcome measures for specific diseases: • Rheumatoid arthritis: DAS28, as a continuous measure or classified as good/moderate/no response per EULAR criteria • Spondyloarthritis: BASDAI, as a continuous measure 4. Background and Rationale

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 2. 研究摘要（面向普通大众的概述）纳曲酮是一种经FDA批准用于治疗酒精依赖的药物，目前该药在未经官方适应症许可的情况下被广泛使用：以远低于获批用途的剂量来治疗疼痛与疲劳。目前已有少量科学研究针对三种疾病（纤维肌痛、克罗恩病及多发性硬化症）开展，结果显示该药具有疗效且安全性良好。然而鉴于其在其他多种疾病中的使用频率较高，加之对其作用机制尚不明确（仅具备镇痛效果？是否对脑内生化环境有其他影响？是否具有抗炎作用？），因此有必要在更多疾病中开展相关研究。本研究旨在针对多种风湿性疾病（骨关节炎及各类炎症性关节炎）获取初步数据，从而为后续更大规模的临床试验筛选合适的研究病种。尽管本研究属于探索性试验，但由于以受试者自我报告的疼痛程度为主要评价指标时常会出现明显的安慰剂效应，故本研究仍设置了安慰剂对照组。此外研究采用了“盲法交叉设计”，以确保患者无法知晓自己何时会从接受安慰剂治疗转为使用纳曲酮治疗。

### NCT03008590·条目 47：a. Registration (safety) · 2

- 条目ID：`wref_translation_item_bec8099275671bb92871e4d0`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 13. Zhang W, Nuki G, Moskowitz RW, Abramson S, Altman RD, Arden NK, et al. OARSI recommendations for the management of hip and knee osteoarthritis: part III: Changes in evidence following systematic cumulative update of research published through January 2009. Osteoarthritis Cartilage. 2010 Apr;18(4):476-99. PubMed PMID: 20170770. 14. McAlindon TE, Driban JB, Henrotin Y, Hunter DJ, Jiang GL, Skou ST, et al. OARSI Clinical Trials Recommendations: Design, conduct, and reporting of clinical trials for knee osteoarthritis. Osteoarthritis Cartilage. 2015 May;23(5):747-60. PubMed PMID: 25952346. 15. Wolfe F, Michaud K. Assessment of pain in rheumatoid arthritis: minimal clinically significant difference, predictors, and the effect of anti-tumor necrosis factor therapy. J Rheumatol. 2007 Aug;34(8):1674-83. PubMed PMID: 17611989. 16. Coxib, traditional NTC, Bhala N, Emberson J, Merhi A, Abramson S, et al. Vascular and upper gastrointestinal effects of non-steroidal anti-inflammatory drugs: meta-analyses of individual participant data from randomised trials. Lancet. 2013 Aug 31;382(9894):769-79. PubMed PMID: 23726390. Pubmed Central PMCID: 3778977. 17. Brown JP, Boulay LJ. Clinical experience with duloxetine in the management of chronic musculoskeletal pain. A focus on osteoarthritis of the knee. Therapeutic advances in musculoskeletal disease. 2013 Dec;5(6):291-304. PubMed PMID: 24294303. Pubmed Central PMCID: 3836379. 18. Bannuru RR, McAlindon TE, Sullivan MC, Wong JB, Kent DM, Schmid CH. Effectiveness and Implications of Alternative Placebo Treatments: A Systematic Review and Network Meta-analysis of Osteoarthritis Trials. Ann Intern Med. 2015 Sep 1;163(5):365-72. PubMed PMID: 26215539. 19. Ramiro S, Radner H, van der Heijde DM, Buchbinder R, Aletaha D, Landewe RB. Combinatio
> …（中略）…
> 1945. 26. Smith JP, Field D, Bingaman SI, Evans R, Mauger DT. Safety and tolerability of low- dose naltrexone therapy in children with moderate to severe Crohn's disease: a pilot study. Journal of clinical gastroenterology. 2013 Apr;47(4):339-45. PubMed PMID: 23188075. Pubmed Central PMCID: 3586944.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 13. 张伟、Nuki G、Moskowitz RW、Abramson S、Altman RD、Arden NK等。OARSI关于髋关节与膝关节骨关节炎诊疗建议：第三部分——截至2009年1月已发表研究系统性累积更新后的证据变化。《骨关节炎与软骨》杂志，2010年4月；18卷(第4期)：476-499页。PubMed PMID: 20170770。

### NCT03008590·条目 48：Unlabelled section (schedule) (schedule) · 2

- 条目ID：`wref_translation_item_bf7ea86d6e68474d009f8346`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_2:comparison_direction_changed`）
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_2:negation_signal_missing`）

**【原文段落】**（英文原文）

> e. Common Closing Date - Study Duration The study will close 16 weeks after enrollment of the last subject. Data will not be collected from subjects after they have completed the 16 weeks of the study.
> f. Criteria for Withdrawal of Study Medication – Early Termination • Use of any opioid agonist, including tramadol, for more than two days • Rise in AST or ALT to a level 3-fold above the upper limit of normal, or more than 2-fold above the patient’s level at baseline if that baseline was abnormal. • Decline in kidney function (drop in GFR to < 30 ml/min) • Pregnancy or nursing • Addition or discontinuation of any medication given on a scheduled basis to treat pain. For medications taken as-needed, changes in frequency will not be grounds for withdrawal; rather, patients will be asked how frequently they have been using such medications.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> f. 停用研究药物的判定标准——提前终止情形 • 使用任何阿片类激动剂（包括曲马多）超过两天。• AST或ALT水平升高至正常值上限的3倍，若基线值已异常则升至较该基线值高出2倍以上。• 肾功能下降（GFR降至30 ml/min以下）。• 妊娠或处于哺乳期。• 开始使用或停用任何用于镇痛的常规用药方案中的药物；对于按需服用的镇痛药，其使用频率的变化不构成停药依据，此时仅需询问患者此类药物的使用频次即可。

### NCT03008590·条目 49：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_cc16ce67db4480ed23b9d4db`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_3:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Safety and Monitoring
> Standardized definitions and timelines will be used for the reporting of serious and non-serious adverse events.
> A VA-assigned Data Monitoring Committee (DMC) and the Institutional Review Board of the VA Boston Healthcare System will monitor safety and all other aspects of the study.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 由美国退伍军人事务部指定的数据监测委员会（DMC）以及波士顿退伍军人医疗系统机构审查委员会将负责监督本研究的安全性及其他各项事宜。

### NCT03008590·条目 50：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_ceb5a986025a68c185582d79`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 5 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_5:numeric_tokens_changed`）
  - 译文第 5 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_5:negation_signal_missing`）
  - 译文第 5 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_5:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> Use of any opioid agonist, including tramadol, is an exclusion criterion for enrollment, and these drugs must also be avoided during the trial. If a patient must use an opioid agonist for more than 2 days during the trial, that patient must be removed from the trial, and data will be censored at the time of that treatment. Medications to treat pain must not have been increased for 8 weeks prior to enrollment. Opioids, including tramadol, may not have been used for at least 7 days prior to enrollment. If a patient must have a change in treatment (pharmacologic or non- pharmacologic) related to pain or arthritis, that patient must be removed from the trial, and data will be censored at the time of that treatment change. Stable treatment with IV medications that require pre-treatment with other medications to prevent infusion reactions (e.g., rituximab, infliximab, IVIG) will not be regarded as a change in treatment. Corticosteroid or viscosupplementation injection intended to improve musculoskeletal pain must have been given at least 8 weeks prior to enrollment. It is expected that many patients will be using acetaminophen or NSAIDs as needed before enrollment. Rather than requiring patients to move to a fixed schedule, data on use of such drugs will be collected and used in analyses.
> d. Study Procedures
> i. Recruitment
> Recruitment will occur through the clinical practices of the rheumatologists at the three main campuses of the VA Boston Healthcare System. Primary care providers will be notified about the trial and will be encouraged to contact the PI about potential participants. Pre-screening by discussion with the referring physician and review of medical records will greatly reduce the number of screening failures. Referring physicians will be asked to ask prospective
> …（中略）…
> ributed at (in person) or shortly after (by mail or in person) the first two of these visits. Patients who are unable to attend the second and/or third in-person visits may remain in the study if completed questionnaires, new questionnaires, and study drug are delivered by mail. v. Study Assessments

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 招募工作将在波士顿VA医疗系统三大院区的风湿病科医师所在的临床实践中开展。基层保健医生将获知本试验的相关信息，并被鼓励就潜在的受试者情况与PI取得联系。通过与转诊医生沟通并进行病历审查的方式开展预筛选，可大幅减少筛查失败的情况。将要求转诊医生请拟入选的受试者对过去两周内其每日平均疼痛严重程度及疼痛干扰程度进行评分（0至10分），但须叮嘱医生切勿告知患者其入选标准为年满18周岁及以上。

### NCT03008590·条目 51：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_d9f75c8e62136a035c6f14a8`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 52：g. Outcome Definitions See Section 7, Data Analysis 6. Safety Monitoring and Adverse Event Reporting (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_de79b8b8947b80e7d39cb790`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 8 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_8:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> As only naltrexone and placebo will be considered to be study drugs in this trial, only adverse events possibly, probably, or definitely related to naltrexone will be considered reportable for this study. e. Relation to Study Therapy The relation or attribution of an adverse event to an investigational product is determined by the investigator and then recorded on the appropriate case report form and/or SAE reporting form. The CTCAE provides the following descriptors and definitions for assigning an attribution to each adverse event. Code Descriptor Definition
> “ Unrelated” Category Code 1 Unrelated The adverse event is clearly not related to the investigational product “Related” Category Codes 2 Unlikely The adverse event is doubtfully related to the investigational product 3 Possible The adverse event may be related to the investigational product 4 Probable The adverse event is likely related to the investigational product 5 Definite The adverse event is clearly related to the investigational product f. Standard Elements A set of standard elements for adverse event data will be collected. These elements include: patient ID, dates for event/event reported/date resolved, the event itself, event severity, whether it was expected and/or serious (as defined above), patient status, place of adverse event treatment (to further determine serious events), causality, and subsequent changes to protocol or consent form. Additionally, the reporter may write a more detailed description of the event and any other pertinent information. g. Expected / Known Risks and Adverse Events Associated with Study
> Intervention and Procedures
> i. Study Drug/Intervention: For known risks of study intervention, see Section 9. ii. Study Procedures: For risks of study procedures, see Section 9. h. Repo
> …（中略）…
> ted reportable adverse events must be reported within 20 working days of the notification of the event or of the site becoming aware of the event. i. Investigational New Drug Application (IND) The FDA has made a formal ruling that this study is exempt from needing an IND. j. Planned Interim Analysis

**【中文译文段落】**（原始模型输出（未经对齐组装））

> h. 报告时限 • 研究者须履行VA波士顿医疗系统伦理委员会的所有报告要求。• 在获悉任何严重不良事件后24小时内，共同研究者须将该事件（无论是否与试验用药品相关）汇报给主要研究者。随后，主要研究者在获悉该事件后24小时内须向伦理委员会报告；在2个工作日内还需向DMC进行汇报。• 对于1级程度的预期或非预期的不良事件，是否收集与报告由主要研究者自行决定；例如既往研究中曾报道过的神经精神类副作用。• 所有其他需要报告的预期或非预期的不良事件，均须在获悉该事件或研究中心知晓事件发生后的20个工作日内予以报告。

### NCT03008590·条目 53：a. Background (objectives_endpoints)

- 条目ID：`wref_translation_item_eb528cfba342f492c225ed28`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> Chronic Pain and Arthritis According to an Institute of Medicine report, 116 million Americans are affected by chronic pain, at an overall annual cost of $635 billion (1). Veterans are expected to be disproportionately affected for multiple reasons, including service-related injuries and psychiatric comorbidities such as post-traumatic stress disorder and depression. Treatment for chronic pain has been and continues to be a priority research area for VA CSR&D. The two most common causes of chronic pain are osteoarthritis (OA) and back pain (2). OA is defined by cartilage loss that is usually attributable in large part to mechanical causes, but abnormalities are numerous and the relationships between them are complex (3, 4). OA is estimated to affect 12.1 million Americans, at an annual cost of $89 billion in medical expenses and additional costs related to reduced productivity (2). Important risk factors for OA in different locations include obesity, advancing age, and prior injury, all of which are highly relevant to the population served by the VA. Inflammatory arthritis (IA) includes multiple diseases, but the most common and destructive are rheumatoid arthritis (RA) and spondyloarthritis (SpA), a term that encompasses psoriatic arthritis, ankylosing spondylitis, reactive arthritis, and arthritis associated with inflammatory bowel disease. Together, RA and SpA affect 2-3% of persons and usually require treatment with immune-suppressive drugs in order to prevent severe joint damage. Most patients achieve good control of disease, but there is often evidence of some ongoing inflammation; e.g. in one large cohort, only 25% met criteria for remission one year after enrollment, and 72% of those patients had already been in remission at enrollment (5). SpA is the one form o
> …（中略）…
> e regardless of the stimulus, peripheral sources can be subdivided into those that are purely nociceptive and those that include an inflammatory component. In all persons experiencing pain, central nervous system mechanisms are involved, and these mechanisms are variably active in different persons.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 根据美国医学研究所的报告，约有1.16亿美国人受到慢性疼痛的困扰，由此产生的年度总费用高达6350亿美元(1)。由于服役期间所受损伤以及创伤后应激障碍、抑郁等精神类共病等多种因素，退伍军人受慢性疼痛的影响尤为显著。对慢性疼痛的治疗一直以来都是VA CSR重点开展的研究领域，今后亦将如此。

### NCT03008590·条目 54：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_ed5acf81c89d22e9a9b3df7e`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 55：Unlabelled section (schedule) (schedule)

- 条目ID：`wref_translation_item_f8726bcf6808ec1d3a41dd25`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> 2). Study Schedule Table
> | | Screen / Enroll | Wk 0 | Wks 1-3 | Wk 4 | Wks 5-7 | Wk 8 | Wks 9-11 | Wk 12 | Wks 13-15 | Wk 16 |
> | Consent | X | | | | | | | | | |
> | Eligibility | X | | | | | | | | | |
> | Phone reminders | | X | X | X | X | | X | X | X | |
> | Complete weekly questionnaires | X | X | X | X | X | X | X | X | X | X |
> | Complete every-4- week questionnaires | X | | | X | | X | | X | | X |
> | Return questionnaires | | | | | | X | | | | X |
> | Distribute questionnaires | X | | | | | X | | | | |
> | Distribute study drug | X | | | | | X | | | | |
> | Collect unused study drug | | | | | | X | | | | X |
> | Report AEs | | | X | X | X | X | X | X | X | X |
> | Assess disease activity | X | | | | | X | | | | X |
> | Assess medication use | X | | X | X | X | X | X | X | X | X |
> | Laboratory tests * | X | | | | | X | | | | X |

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | 每4周填写一次问卷 | X | | | X | | X | | X | | X |

### NCT03008590·条目 56：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_f920e0da84193abc4d8e0e2c`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_3:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Safety and Monitoring
> Standardized definitions and timelines will be used for the reporting of serious and non-serious adverse events.
> A VA-assigned Data Monitoring Committee (DMC) and the Institutional Review Board of the VA Boston Healthcare System will monitor safety and all other aspects of the study.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 由美国退伍军人事务部指定的数据监测委员会（DMC）以及波士顿退伍军人医疗系统机构审查委员会将负责监督本研究的安全性及其他各项事宜。

### NCT03008590·条目 57：i. Recruitment (objectives_endpoints)

- 条目ID：`wref_translation_item_fcb6f21fa6256385c2ca6992`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 1). Study Assessment Patient-reported outcomes will be reported weekly on paper forms. Subjects may receive reminders by phone. The outcome measures used will be: Primary outcome measure (all patients): • Brief Pain Inventory-short form (BPI) (33): The BPI is a 9-item self-report questionnaire that allows patients to rate the severity of their pain and the degree to which their pain interferes with common dimensions of feeling and function. For the purpose of the proposed study, we will be particularly interested in pain “interference”. A recent consensus panel recommended that the two domains measured by the BPI – pain intensity (severity) and the impact of pain on functioning (interference) – be included as outcomes in all chronic-pain clinical trials (IMMPACT, (34)). The IMMPACT panel (www.immpact.org) specifically identified the interference items of the BPI, rated on a 0–10 scale, as one of the two scales recommended for assessment of pain-related functional impairment (35). It has excellent reliability and validity and it has been used widely in OA research (36). (weekly questionnaire)
> Secondary outcome measures: • Brief Pain Inventory short form, other questions than those used for the primary outcome, particularly question 5, average pain severity (weekly) • painDETECT (for neuropathic component of pain) (37, 38) (only at weeks 0, 4, 8, 12, and 16) • PROMIS-29 (survey of quality of life in multiple domains) (40) (only at weeks 0, 4, 8, 12, and 16) • Brief Fatigue Inventory, specifically question 2 (usual level in past 24 hours, 0-10) and question 4 (interference in the past 24 hours, average of 6 questions 0-10 each) • Beck Depression Inventory-II (purchase pending), a widely used 21-question assessment of the severity of depression (only at weeks 0, 4, 8, 12, 1
> …（中略）…
>  between treatment periods is appropriate; inclusion of a protocolized “wash-out” period is a common design in cross-over studies. Because there is no defined wash-out period in this study, the analysis plan already included omission of data from the first two weeks after cross-over (see Section 7).

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 1). 研究评估：患者报告结局将每周通过纸质表格进行记录。研究者可通过电话提醒受试者填写问卷。本研究采用的评估指标如下：主要患者报告结局（适用于所有患者）：• 简明疼痛量表简版（BPI）（33）。该量表是一项包含9个条目的自我报告式问卷，可帮助患者评估自身疼痛的严重程度以及该疼痛对其情绪与功能各方面的影响程度。在本研究中，我们重点关注“疼痛对功能的干扰”这一指标。近期由相关专家组成的共识小组建议：所有慢性疼痛临床试验均应将简明疼痛量表所测定的两个维度——即疼痛强度（严重程度）以及疼痛对功能的影响程度纳入评估指标之列（IMMPACT，(34)）。该共识小组（www.immpact.org）特别指出，以0至10分进行评分的简明疼痛量表中的功能干扰相关条目属于推荐用于评估疼痛所致功能障碍的两项指标之一（35）。该量表具备极佳的可靠性与有效性，并已在骨关节炎相关研究中被广泛采用（36）。（每周填写一次问卷）

### NCT03008590·条目 58：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 5

- 条目ID：`wref_translation_item_fce0a8420af5a2884540d891`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> a. Primary Outcome Interference of pain with general activity (question 9 on the Brief Pain Inventory, an average of 7 sub-questions, each 0-10) is the primary outcome measure. Pain severity is the primary outcome reported in studies of pain in OA. However, some patients will choose to increase activity at the expense of a level of pain that they have learned to tolerate, so “pain interference” is of at least equal interest (12, 23).
> i. Primary Analytic Approach to the Primary Outcome The goal is to determine the difference in pain interference during treatment with LDN versus placebo. We will take advantage of the multiple data points obtained from each patient to improve the precision of that estimate, reducing the risk of type II error. The summary of each patient’s response to LDN compared to placebo will be made using linear contrasts. Thus, for each patient: d = a n1 x n1 + a n2 x n2 … + a n8 x n8 – a p1 x p1 – a p2 x p2 … – a p8 x p8 where each “a” indicates a weight assigned to that observation on the basis of fitting the pre-post crossover data from all patients with a cubic spline or two linear splines; n indicates treatment with naltrexone; p indicates treatment with placebo; x indicates pain severity or pain interference; and numbers indicate weeks on the treatment. The first observation following cross-over will be dropped in each patient. Thus, in group 1, weights a p1 and a p2 will be 0, and in group 2, weights a n1 and a n2 will be 0. Weights will be adjusted in individual patients in the event of missing data, and data obtained during an active adverse event will not be included; the weight given to the summary value of each patient’s data (d) in the full analysis, however, will be equal. In each patient, the sum of all weights will be set to 0. The distribution of d among all patients will then be compared to a null distribution by t- test.
> ii. Secondary Analytic Approaches to the Primary Outcome

**【中文译文段落】**（原始模型输出（未经对齐组装））

> a. 主要终点：疼痛对日常活动的影响程度（即简明疼痛量表中的第9个问题，由7个0至10分的子问题构成的平均值）是本研究的主要终点指标。在骨关节炎相关疼痛研究中，疼痛严重程度也是最常报告的主要结局指标。不过也有部分患者会选择增加活动量，即便这意味着承受他们已能适应的疼痛水平；因此“疼痛对日常活动的干扰程度”同样值得重点关注 (12, 23)。

### NCT03008590·条目 59：a. Background (objectives_endpoints) · 3

- 条目ID：`wref_translation_item_fdad0aea8953217e44b58454`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_1:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> Intriguingly, 23 members of a group reporting RA (presumably overlapping with the “arthritis” group) also placed LDN with TJR and corticosteroids and seemingly above DMARDs, biologics, and non-pharmacologic therapies. In a group of patients reporting OA, only 5 commented on LDN, and only 2 of those reported benefit. In fibromyalgia, 72 respondents again gave LDN the highest rating among pharmacologic therapies, with the only approaches giving comparable relief being rest/sleep, application of heat, and stress reduction. Scanning across other disease states was both encouraging and concerning for the survey reaching a biased population: LDN was at or near the top of therapies reported in patients with multiple sclerosis (n=128), fatigue (n=112), Crohn’s disease (n=33), neuropathy (v=22), Sjogren’s syndrome (v=9), Hashimoto’s (v=9), psoriasis (v=7), hepatitis C (v=6), sarcoidosis (v=4), symptom relief in breast cancer (v=4) or non-small-cell lung cancer (v=4), psoriatic arthritis (v=3), ankylosing spondylitis (v=3), polymyositis (v=3), scleroderma (v=3), HIV (v=2), lupus (v=1), and complex partial seizures (v=1). Reassuringly with regard to bias based on belief systems, LDN was not reported as being reliably helpful in 4-20 patients each with irritable bowel syndrome, anxiety, depression, asthma, dandruff, Raynaud’s, night cramps, Lyme disease, low back pain, or prostate cancer. Reassuringly with regard to possible bias by the survey designers, LDN was not suggested as an option for diabetes, COPD, gout, eczema, congestive heart failure, or many other conditions. These data provide further support that LDN may provide an important advance in management of pain and other symptoms – particularly in inflammatory diseases – but do little to alleviate the concern that hype has
> …（中略）…
> ion.
> The study also includes the four outcome domains identified by consensus in the Initiative on Methods, Measurement, and Pain Assessment in Clinical Trials (IMMPACT): pain intensity, physical functioning, emotional functioning, and global rating of improvement (12).
> b. Identification of Patients

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 有趣的是，在报告患有RA的23名受试者中（该群体很可能与前述“关节炎”组存在重叠），他们同样将LDN排在TJR、皮质类固醇之后，且似乎也将其置于DMARDs、生物制剂以及非药物疗法之前。而在报告患有OA的患者组中，仅有5人提及LDN，其中仅2名受试者表示该药带来了疗效。在纤维肌痛患者群体中，共有72人将LDN评为各类药物治疗手段中的首选；能带来类似缓解效果的其他方式仅为休息/睡眠、热敷以及减压。对其他各类疾病患者的调查结果既令人鼓舞又引发担忧，因为该调查样本可能存在偏差：在多发性硬化症（n=128）、疲劳症状患者（n=112）、克罗恩病患者（n=33）、神经病变患者（v=22）、干燥综合征患者（v=9）、桥本氏病患者（v=9）、银屑病患者（v=7）、丙型肝炎患者（v=6）以及结节病、乳腺癌症状缓解需求者中，LDN均位列治疗手段前列或接近榜首。

## 研究 NCT03485157（4 项待处置）

### NCT03485157·条目 1：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_42abdbd56b9d48154b82f9e8`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_2:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> Exploratory Endpoint: For the cohort of subjects in the main phase of the study, i.e. who did not receive or have not yet received an open-label injection, the following exploratory endpoints will be assessed:
> • Change in VAS score for pain between baseline and i-day (with i=30, 60, 270, and 365 days) • Change in Total WOMAC score between baseline and i-day (with i=30, 60, 270, and 365 days) • Change in pain, stiffness, and physical function WOMAC subscale scores between baseline and i-day (with i=30, 60, 90, 180, 270, and 365 days) • Change in VAS score for satisfaction between baseline and i-day (with i=30, 60, 90, 180, 270, and 365 days) • Change in KOOS scores between baseline and i-day (with i=30, 60, 90, 180, 270, and 365 days) • Patient pain diary endpoints will be collected and summarized across applicable time points For the cohort of subjects in the extension phase, i.e. who received the open-label injection and are within the period after the open-label injection, the following endpoints will be collected and summarized across applicable time points: VAS score for pain, Total WOMAC, WOMAC subscales for pain, stiffness and physical function, VAS score for satisfaction, KOOS, and pain diary entries. Inclusion Criteria All subjects enrolled must meet all the following criteria:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 从基线至第30、60、270及365天疼痛相关视觉模拟量表评分的变化 • 从基线至第30、60、270及365天WOMAC总评分的变化 • 从基线至第30、60、90、180、270及365天WOMAC疼痛、僵硬程度与躯体功能子量表评分的变化 • 从基线至第30、60、90、180、270及365天满意度相关视觉模拟量表评分的变化 • 从基线至第30、60、90、180、270及365天KOOS评分的变化 • 将在各适用时间点收集并汇总患者疼痛日记相关终点指标。对于扩展阶段的受试者队列，即已接受开放标签注射且处于该注射后随访期的受试者群体，将在各适用时间点收集并汇总以下终点指标：疼痛相关视觉模拟量表评分、WOMAC总评分、WOMAC疼痛/僵硬程度与躯体功能子量表评分、满意度相关视觉模拟量表评分、KOOS评分以及疼痛日记记录。入选标准：所有入组受试者均须符合以下全部条件：

### NCT03485157·条目 2：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_56c5e2e91e174ddfa053cf63`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_3:numeric_tokens_changed`）
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）
  - 译文第 3 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_3:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Exclusion Criteria Any potential subjects meeting any of the following criteria will be excluded from enrollment and subsequent randomization.
> 1. Subject has a diagnosis of osteoarthritis (OA) defined as Grade 4 on the Kellgren Lawrence grading scale 2. BMI greater than 40 kg/m 2 3. Subject has active infection at the injection site 4. Symptomatic OA of the contralateral knee or of either hip that is not responsive to acetaminophen (Tylenol ® ) and requires other therapy. 5. Subject has rheumatoid arthritis, psoriatic arthritis, or have been diagnosed with any other disorders that is the primary source of their knee pain, including but not limited to: osteonecrosis, radiculopathy, bursitis, tendinitis, tumor, cancer 6. Subject has documented history of gout or pseudo-gout 7. Subject has autoimmune disease or a known history of having Acquired Immunodeficiency Syndromes (AIDS) or HIV 8. Subject has received any of the following to the target knee:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 2. 体重指数大于40公斤/平方米

### NCT03485157·条目 3：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_79ddfe4a770b15a68397afdc`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_2:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> Exploratory Endpoint: For the cohort of subjects in the main phase of the study, i.e. who did not receive or have not yet received an open-label injection, the following exploratory endpoints will be assessed:
> • Change in VAS score for pain between baseline and i-day (with i=30, 60, 270, and 365 days) • Change in Total WOMAC score between baseline and i-day (with i=30, 60, 270, and 365 days) • Change in pain, stiffness, and physical function WOMAC subscale scores between baseline and i-day (with i=30, 60, 90, 180, 270, and 365 days) • Change in VAS score for satisfaction between baseline and i-day (with i=30, 60, 90, 180, 270, and 365 days) • Change in KOOS scores between baseline and i-day (with i=30, 60, 90, 180, 270, and 365 days) • Patient pain diary endpoints will be collected and summarized across applicable time points For the cohort of subjects in the extension phase, i.e. who received the open-label injection and are within the period after the open-label injection, the following endpoints will be collected and summarized across applicable time points: VAS score for pain, Total WOMAC, WOMAC subscales for pain, stiffness and physical function, VAS score for satisfaction, KOOS, and pain diary entries. Inclusion Criteria All subjects enrolled must meet all the following criteria:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 从基线至第30、60、270及365天疼痛相关视觉模拟量表评分的变化 • 从基线至第30、60、270及365天WOMAC总评分的变化 • 从基线至第30、60、90、180、270及365天WOMAC疼痛、僵硬程度与躯体功能子量表评分的变化 • 从基线至第30、60、90、180、270及365天满意度相关视觉模拟量表评分的变化 • 从基线至第30、60、90、180、270及365天KOOS评分的变化 • 将在各适用时间点收集并汇总患者疼痛日记相关终点指标。对于扩展阶段的受试者队列，即已接受开放标签注射且处于该注射后随访期的受试者群体，将在各适用时间点收集并汇总以下终点指标：疼痛相关视觉模拟量表评分、WOMAC总评分、WOMAC疼痛/僵硬程度与躯体功能子量表评分、满意度相关视觉模拟量表评分、KOOS评分以及疼痛日记记录。入选标准：所有入组受试者均须符合以下全部条件：

### NCT03485157·条目 4：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_b00156f60a77fc05cdd86206`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_3:numeric_tokens_changed`）
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）
  - 译文第 3 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_3:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Exclusion Criteria Any potential subjects meeting any of the following criteria will be excluded from enrollment and subsequent randomization.
> 1. Subject has a diagnosis of osteoarthritis (OA) defined as Grade 4 on the Kellgren Lawrence grading scale 2. BMI greater than 40 kg/m 2 3. Subject has active infection at the injection site 4. Symptomatic OA of the contralateral knee or of either hip that is not responsive to acetaminophen (Tylenol ® ) and requires other therapy. 5. Subject has rheumatoid arthritis, psoriatic arthritis, or have been diagnosed with any other disorders that is the primary source of their knee pain, including but not limited to: osteonecrosis, radiculopathy, bursitis, tendinitis, tumor, cancer 6. Subject has documented history of gout or pseudo-gout 7. Subject has autoimmune disease or a known history of having Acquired Immunodeficiency Syndromes (AIDS) or HIV 8. Subject has received any of the following to the target knee:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 2. 体重指数大于40公斤/平方米

## 研究 NCT04210986（65 项待处置）

### NCT04210986·条目 1：Unlabelled section (safety) (safety) · 11

- 条目ID：`wref_translation_item_0259a164a801b41baa9135c5`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Time frame : within 3 months of Visit 1 • Visit length : 3-4 hours • Vital signs, medication information, and any adverse events that occurred since the last visit will be collected. • A pregnancy test will be performed for all pre-menopausal female participants. • The following procedures and tests will be performed: ▪ Medication instructions; ▪ Magnetic resonance imaging (MRI) scan; ▪ Functional performance testing; ▪ Physical exam; ▪ Muscle strength testing; ▪ Video-motion analysis. • Note that the blood test and knee x-ray may be performed at this visit if it was not done at visit 1. • Some of the screening procedures may need to be repeated for accuracy, fidelity, and/or safety.
> Page 89
> • Vail Health Pharmacy will be responsible for dispensing the Fisetin or placebo capsules. Fisetin or placebo capsules will be given to you in a bottle with a set of instructions. • After completing the study tests for this visit, you will be given Fisetin or placebo capsules as treatment. You will be instructed to take capsules while at the study site and the next day (10-15 capsules per day, amount based on body weight). You will be instructed to take the capsules for 2 cycles of treatment:
> o Cycle 1: 2 days on (days 1 and 2), followed by 28 days off (day 30). o Cycle 2: 2 days on (days 31 and 32). o Treatment will occur over the course of approximately 5 weeks. • All capsules must be taken within 60 minutes after the first capsule is consumed. • At Visit 4, please return any remaining capsules in the bottle. These extra capsules will be counted and discarded at your next on-site visit. • You will be given a drug diary/schedule to log each dose you take during the 2 treatment cycles. • A member of the clinical team will contact you via phone call three times while you are schedu
> …（中略）…
> m/study will not cover the costs of any follow-up consultations or actions. If you are not interested in receiving this information, please do not consent to participate in this study.
> Page 101
> XVI. Who should I contact if I have questions about the research? Contact the researchers at 970-476-1100:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • Vail Health药房将负责发放非瑟酮或安慰剂胶囊。这些胶囊会连同使用说明一同装入药瓶中提供给您。• 完成本次访视的各项研究检查后，您将开始服用非瑟酮或安慰剂胶囊进行治疗。工作人员会指导您在研究中心及次日按时服药（每日剂量为10至15粒，具体数量视体重而定）。您需连续完成2个治疗周期： o 第1周期：服药2天（即第1和第2日），随后停药28天（至第30日）。 o 第2周期：服药2天（即第31和第32日）。 o 整个治疗过程约持续5周。• 所有胶囊必须在您服下第一粒后的60分钟内全部服用完毕。• 在第4次访视时，请您将药瓶中剩余的胶囊一并交回。这些多余的胶囊会在您下次到研究中心时经清点后予以废弃处理。• 我们将向您提供用药记录本/日程表，以便详细记载您在2个治疗周期内每次的服药情况。

### NCT04210986·条目 2：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 7

- 条目ID：`wref_translation_item_03c47fa43b5fa0c2c00302ae`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_2:numeric_tokens_changed`）
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Patient Reported Outcomes (PROs): (Visits 1, 2, 4, 5, 6)
> All PROs may be completed either on paper documents or by online questionnaire administration conducted via formsite (Vroman Systems, Inc.). Patients may complete questionnaires on a variety of electronic devices (personal computer, mobile phone, tablet). PRO data to be collected include: Augmented Numerical Rating Scale (NRS) (visit 2): At baseline then once every 3 days during FIRST 6 weeks of study medication treatment then once a week for an ADDITIONAL 6 weeks. IKDC, Lysholm, TEGNER, WOMAC and SF-12 (visit 2, visits 4, 5, and 6 and remote assessments at 3- and 18-months post completion of medication).
> Page 46
> The Numerical Rating Scale is a simple 0-10 self-reported severity of pain scale, (zero being no pain and 10 being the worst pain imaginable). This tool has been validated to provide excellent test-retest reliability in assessing knee pain associated with OA 31 . The Steadman Philippon Research Institute has added several stand-alone questions that are administered with the questionnaire. Only the validated portion, the simple NRS will be used to screen patients. In follow-up, each question will be analyzed individually. There is no composite score. A sample can be found in Appendix C, Section 22.3 of this document.
> The Lysholm knee scale is a condition-specific outcome measure that was originally designed to assess ligament injuries of the knee. It has been tested to provide excellent construct validity and overall acceptable psychometric performance for outcomes assessment of various chondral disorders of the knee. It is recommended that this tool be administered with additional psychometric measurements 32,33 . The TEGNER Activity Scale is a numerical scale ranging from 0 to 10. Each value indicates th
> …（中略）…
> n left/right sides (5 min). As is standard practice when using the HUMAC NORM system, padded straps will be used on the participant's torso and legs in order to isolate the lower leg movements and reduce the contribution of other muscles. All measurements will be normalized to % body weight.
> Page 50

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 所有患者报告结局（PRO）问卷均可通过纸质表格填写，也可借助Formsite平台（Vroman Systems, Inc.公司开发）在线完成。患者可在各类电子设备上填写问卷，包括个人电脑、手机及平板电脑等。需采集的患者报告结局数据如下：增强型数值评分量表（NRS）（第2次访视）：于基线时填写一次，随后在研究用药治疗的前6周内每隔3天填写一次；再接下来的6周则每周填写一次。此外还需采集IKDC量表、Lysholm评分表、TEGNER活动分级量表、WOMAC膝关节功能评估量表以及SF-12健康调查简表的相关数据（第2、4、5及6次访视时填写，并在用药结束后3个月与18个月时进行远程评估）。

### NCT04210986·条目 3：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 7

- 条目ID：`wref_translation_item_0553f9da90131de7c0eaa2d9`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_2:numeric_tokens_changed`）
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Patient Reported Outcomes (PROs): (Visits 1, 2, 4, 5, 6)
> All PROs may be completed either on paper documents or by online questionnaire administration conducted via formsite (Vroman Systems, Inc.). Patients may complete questionnaires on a variety of electronic devices (personal computer, mobile phone, tablet). PRO data to be collected include: Augmented Numerical Rating Scale (NRS) (visit 2): At baseline then once every 3 days during FIRST 6 weeks of study medication treatment then once a week for an ADDITIONAL 6 weeks. IKDC, Lysholm, TEGNER, WOMAC and SF-12 (visit 2, visits 4, 5, and 6 and remote assessments at 3- and 18-months post completion of medication).
> Page 46
> The Numerical Rating Scale is a simple 0-10 self-reported severity of pain scale, (zero being no pain and 10 being the worst pain imaginable). This tool has been validated to provide excellent test-retest reliability in assessing knee pain associated with OA 31 . The Steadman Philippon Research Institute has added several stand-alone questions that are administered with the questionnaire. Only the validated portion, the simple NRS will be used to screen patients. In follow-up, each question will be analyzed individually. There is no composite score. A sample can be found in Appendix C, Section 22.3 of this document.
> The Lysholm knee scale is a condition-specific outcome measure that was originally designed to assess ligament injuries of the knee. It has been tested to provide excellent construct validity and overall acceptable psychometric performance for outcomes assessment of various chondral disorders of the knee. It is recommended that this tool be administered with additional psychometric measurements 32,33 . The TEGNER Activity Scale is a numerical scale ranging from 0 to 10. Each value indicates th
> …（中略）…
> n left/right sides (5 min). As is standard practice when using the HUMAC NORM system, padded straps will be used on the participant's torso and legs in order to isolate the lower leg movements and reduce the contribution of other muscles. All measurements will be normalized to % body weight.
> Page 50

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 所有患者报告结局（PRO）问卷均可通过纸质表格填写，也可借助Formsite平台（Vroman Systems, Inc.公司开发）在线完成。患者可在各类电子设备上填写问卷，包括个人电脑、手机及平板电脑等。需采集的患者报告结局数据如下：增强型数值评分量表（NRS）（第2次访视）：于基线时填写一次，随后在研究用药治疗的前6周内每隔3天填写一次；再接下来的6周则每周填写一次。此外还需采集IKDC量表、Lysholm评分表、TEGNER活动分级量表、WOMAC膝关节功能评估量表以及SF-12健康调查简表的相关数据（第2、4、5及6次访视时填写，并在用药结束后3个月与18个月时进行远程评估）。

### NCT04210986·条目 4：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 5

- 条目ID：`wref_translation_item_0fd46f9055c4fd79e8111776`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）

**【原文段落】**（英文原文）

> Administration of Study Medication 7.4.1 Route and Dosage Fisetin (FIS) 100 mg capsules (~20 mg/ kg/ day) will be administered orally for two consecutive days (days 1 and 2) followed by 28 days off. A second course will be given for two consecutive days (days 31 and 32) Placebo (visually identical) will be taken orally using the same dosing schedule described for FIS. Number of capsules per day will be the same number as if receiving FIS. There are no recommended dosing adjustments for kidney or liver dysfunction. Subjects will be instructed to complete dosing in as short of a time as possible, with a goal of 10 minutes and a maximum time of 60 minutes to complete ingestion of the capsules. They will further be instructed not to increase medication dosing should a particular dose be missed. 7.4.2 Rationale for FIS Dose and Intermittent Dosing Schedule 7.4.3 Dose We previously treated 4 male and 4 female 8-month-old C57/Bl6 mice with FIS 500 mg/kg/day, (a dose 25-fold higher than the dose to be used in this clinical trial) by oral gavage for two consecutive days and compared study endpoints to four male and four female mice treated with control. We found no evidence of substantial toxicity, as assessed by monitoring activity, food intake, and respiratory quotient in metabolic cages (Comprehensive Laboratory Animal Monitoring System, Columbus Instruments) for 48 hours after the last FIS dose. In addition, we administered 100 mg/kg/day for 2 consecutive days by mouth (a dose five times the dose proposed in in this clinical trial) to two older Rhesus monkeys, ages 18 and 28 years. Because these animals are considered elderly for their species it would be expected that they be more vulnerable to adverse events. In over one month of close monitoring, neither monkey showed evi
> …（中略）…
> eated mice with our proposed dose and more, for over two months (equivalent of ~20 years in the human lifespan). Considering the comparative life span between the mouse model and of humans, we believe that a 2-month duration is a safe and effective length of time.
> 7.4.6 Human Evidence of Safe Dosing

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 研究药物的给药方式：7.4.1 途径与剂量。非瑟酮（FIS）100毫克胶囊的给药方案为：每日口服约20毫克/公斤体重，连续服用2天（即第1天与

### NCT04210986·条目 5：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_119b99715dc3cf628dbe59ca`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> Enrollment Criteria ..........................................................................................37 9.1.1 Inclusion Criteria .................................................................................37 9.1.2 Exclusion Criteria ................................................................................37 10.0 Study Visits .................................................................................................................40
> Visit 2 (Baseline): (Within 3 months of Visit 1)..............................................40
> Visit 3: Two Weeks after first dose of Fisetin or Placebo (+/- 2 days) ...........41
> Visit 4: Two Weeks from the Subject's Last Dose of Fisetin or Placebo (+/- 10 days) ............................................................................................................41
> Visit 5: Six Months from the Subject's First Dose of Fisetin or Placebo (+/- 4 weeks) ...........................................................................................................42

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 访视3：给予非瑟酮或安慰剂首次给药后两周（±2天）....................41

### NCT04210986·条目 6：12.0 Study Management of Adverse Events (safety)

- 条目ID：`wref_translation_item_136ea75dbd50ac8592ece4da`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_4:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 12.0 Study Management of Adverse Events
> Definition An adverse event (AE) is any untoward medical occurrence in a subject administered a Study Medication and which does not necessarily have a causal relationship with this treatment. An AE can therefore be any unfavorable and unintended sign (including an abnormal laboratory finding), symptom, or disease temporally associated with the use of whether or not related to the Study Medication (ICH E2A II/A/1, 21 CFR 312.32).
> All pre-existing medical conditions will be recorded on the medical history study document. Starting with the administration of the Study Medication any new experience that was not present at baseline or worsening of an event present at baseline in intensity or frequency, is considered an adverse event.
> Note: Unchanged, chronic conditions are NOT adverse events and should not be recorded.
> It is recognized that subjects will exhibit (throughout follow-up) symptoms of the underlying disease process of that fluctuates in severity and duration.
> Adverse events will include those occurrences, which when compared to before treatment meets any of the following criteria:
> • Represent a new event or escalation of an event; • Require a new escalation in treatment; • Lasts longer; • Experienced more frequently; • More intense; • Different in character ( e.g. stabbing vs. ache); • Experienced in a different part of the body; and/or • Brought on by activity that previously did not cause the symptom.
> Page 51

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 注意：既往已存在的慢性病症不属于不良事件（AE），因此无需记录。

### NCT04210986·条目 7：Unlabelled section (eligibility) (eligibility) · 8

- 条目ID：`wref_translation_item_1a86e980022f7c8dccce011d`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_1:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> • if you have any questions about this study or your part in it, • if you feel you have had a research-related injury (or a bad reaction to the study treatment), and/or • if you have questions, concerns, or complaints about the research. XVII. Who should I contact if I have questions about my rights as a research subject? If you have questions about your rights as a research subject or concerns, complaints, or to offer input you may call Mary Crumbaker, Chief Ethics and Compliance Officer at Vail Health at 970-477-5197. XVIII. Authorization to use and disclose Protected Health Information The purpose of this section is to give your permission to the research team to obtain and use your patient information. Your patient information will be used to do the research named above. State and federal privacy laws protect your patient information. These laws say that, in most cases, your health care provider can release your identifiable patient information to the research team only if you give permission by signing this form. You do not have to sign this permission form. If you do not sign it, you will not be allowed to join the research study. Your decision to not sign this permission will not affect any of your treatment or any other treatment, healthcare, enrollment in health plans, or eligibility for benefits. What information will be obtained and used? “Patient information” means the health information in your medical or other healthcare records. It also includes information in your records that can identify you. For example, it can include your name, address, phone number, birthdate, and medical record number. By signing this form, you are giving permission to the following organization(s) to disclose your patient information for use in this research.
> • Vail Health (inclu
> …（中略）…
>  Information to the researchers for use in this project. Your Personal Health Information includes health information in your medical records, financial records and other information that can identify you. The specific information that will be released and used for this research is described below :

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 如果您对本研究或您作为受试者所承担的职责有任何疑问，
> • 若您认为自己出现了与研究相关的损伤（或对研究治疗产生了不良反应），和/或
> • 如果您对本研究有任何疑问、顾虑或投诉。 XVII. 若我对自身作为研究受试者的权利存有疑虑，该联系谁呢？倘若您对自身的受试者权益存在疑问、有顾虑或想要投诉/提出建议，可拨打970-477-5197联系Vail Health机构的首席伦理与合规官Mary Crumbaker。 XVIII. 使用并披露受保护健康信息的授权 本部分的目的是征得您的许可，以便研究团队获取并使用您的患者信息。上述患者信息将仅用于开展本研究工作。州及联邦层面的隐私保护法规均对您的患者信息安全予以保障；这些法律规定，在大多数情况下，唯有在您签署本表格给予许可后，您的医疗服务提供方方可将可识别身份的患者信息提供给研究团队。您并无义务必须签署本授权表格；若选择不签，则无法参与本研究。

### NCT04210986·条目 8：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 9

- 条目ID：`wref_translation_item_1ac6c384c33f70fa7adf0125`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_2:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> An AE or suspected adverse reaction is considered “serious” if, in the view of either the Principal Investigator, it results in any of the following outcomes:
> • Death; • A life-threatening adverse event; • Hospitalization; • Disability or permanent damage; • Congenital anomaly/birth defect; • Other serious events that may jeopardize the patient and may require medical or surgical intervention (treatment) to prevent one of the other outcomes. An AE or suspected adverse reaction is considered “life-threatening” if, (in the view of the Principal Investigator) its occurrence places the patient or subject at immediate risk of death. It does not include an AE or suspected adverse reaction that, had it occurred in a more severe form, might have caused death. Serious and/or unexpected adverse event(s) may present as either a local or systemic response, or both, which may present as an anaphylactic response associated with generalized urticaria, shortness of breath, or respiratory or circulatory arrest. Subjects will be instructed to contact the study site immediately if a systemic reaction occurs between scheduled study visits. Subjects may be assessed initially over the phone and may be asked to return to the study site for an additional visit to assess the reaction.
> Page 55

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 死亡； • 危及生命的不良事件； • 住院治疗； • 残疾或永久性损伤； • 先天性异常/出生缺陷； • 其他可能危及患者健康并需要药物或手术干预方可避免上述不良后果的严重事件。若某不良事件或疑似不良反应的发生会使患者即刻面临死亡风险（以主要研究者的判断为准），则该不良事件即被视为“危及生命的”。但若某不良事件或疑似不良反应即便以更严重的形式出现也未必导致死亡，则不属于此类。严重及/或非预期的不良事件可表现为局部反应、全身反应或两者兼有，例如伴随全身性荨麻疹的过敏性休克、呼吸急促甚至呼吸或循环衰竭。若在预定的研究随访期间出现全身性反应，受试者须立即联系研究中心；研究人员可先通过电话对情况进行初步评估，随后可能要求受试者再次前往研究中心以进一步检查。

### NCT04210986·条目 9：6. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12; 7. Protocol deviation assessment; 8. Adverse event assessment. (safety)

- 条目ID：`wref_translation_item_1d06986192c03d7123dc3938`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_4:unit_sequence_changed`）

**【原文段落】**（英文原文）

> 6. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12; 7. Protocol deviation assessment; 8. Adverse event assessment.
> Visit 5: Six Months from the Subject's First Dose of Fisetin or Placebo (+/- 4 weeks) 1. Vital signs; 2. Medical and surgical history; 3. Physical exam with ROM of target limb(s); 4. Blood analysis; 5. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12; 6. Medications; 7. Protocol deviation assessment; 8. Adverse event assessment; 9. Quantitative MRI; 10. Lower-extremity kinematic testing with video-motion analysis; 11. Isokinetic dynamometry testing; 12. Functional performance testing.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 访视5：受试者首次服用非瑟酮或安慰剂后6个月（前后浮动不超过4周）

### NCT04210986·条目 10：6. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12; 7. Protocol deviation assessment; 8. Adverse event assessment. (safety)

- 条目ID：`wref_translation_item_1ed398cf18ac152179d88c73`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_4:unit_sequence_changed`）

**【原文段落】**（英文原文）

> 6. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12; 7. Protocol deviation assessment; 8. Adverse event assessment.
> Visit 5: Six Months from the Subject's First Dose of Fisetin or Placebo (+/- 4 weeks) 1. Vital signs; 2. Medical and surgical history; 3. Physical exam with ROM of target limb(s); 4. Blood analysis; 5. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12; 6. Medications; 7. Protocol deviation assessment; 8. Adverse event assessment; 9. Quantitative MRI; 10. Lower-extremity kinematic testing with video-motion analysis; 11. Isokinetic dynamometry testing; 12. Functional performance testing.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 访视5：受试者首次服用非瑟酮或安慰剂后6个月（前后浮动不超过4周）

### NCT04210986·条目 11：Unlabelled section (safety) (safety) · 8

- 条目ID：`wref_translation_item_249d2f7d9f03b9a28c9956c5`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_2:controlled_term_missing:participant`）

**【原文段落】**（英文原文）

> The subject’s Private Health Information could be accidentally breached during the research process. Many system wide safety guards are in place to prevent this occurrence, including: Subject de-Identification, Badge-access, locked offices; controlled access to research offices and documents, password protected work stations and password complexity enforced; state-of-the-art and promptly updated firewall to block external web traffic; end-to-end encryption on all connections, automatic email encryption system for all outbound (off TSC server) email, Electronically secure online questionnaire access.
> Risk Analysis
> The Study Team will perform regular review of cumulative adverse events and will modify mitigation strategy as necessary. Baseline risk analysis is shown in Table 13.11 below. It is intended that risks with higher overall risk score will be subject to greater and more frequent scrutiny and discussion of mitigation. As the study progresses, modifications to this analysis will be fully document and retained. Table 13.11 Risk Analysis
> | Risk | Likelihood of Occurrence 1= not likely 2= possible 3= very likely | Potential Impact on Subject Safety 1=little 2= moderate 3= severe | Detectability 1= high 2= moderate 3= low | Overall Risk Score (Hierarchy of assessment and follow-up) (3-9) |
> Page 60
> | Associated with FIS Administration | 2 | 3 | 2 | 7 |
> | Associated with Placebo Administration | 1 | 1 | 3 | 5 |
> | Associated with MRI | 2 | 1 | 1 | 4 |
> | Associated With PRO Questionnaires | 2 | 1 | 1 | 4 |
> | Associated With Physical Exam | 2 | 1 | 1 | 4 |
> | Associated With Blood Draw | 2 | 2 | 1 | 5 |
> | Associated With Isokinetic Muscle Strength Testing | 2 | 1 | 1 | 4 |
> | Associated with Functional Performance Testing | 2 | 1 | 1 | 4 |
> | Associated With Motion Capture | 2
> …（中略）…
> ay remove a subject from the study if:
> 1. A subject demonstrates poor compliance with study protocol; 2. There is concurrent illness or required medical treatment that interferes with study assessments; 3. The Principal Investigator determines that the subject’s health, safety or welfare is at risk.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 风险分析：研究团队将定期审查累积发生的各类不良事件，并根据需要调整相应的风险控制措施。基线风险分析结果见下表13.11所示。总体风险评估得分较高的风险项将受到更为严密的监测，并需针对其制定更多且更频繁的风险控制措施。随着研究推进，相关风险分析结果的任何调整均会予以完整记录并妥善保存。表13.11 风险分析

### NCT04210986·条目 12：12.0 Study Management of Adverse Events (safety)

- 条目ID：`wref_translation_item_26d8ee15a5bf60817c78621e`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_4:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 12.0 Study Management of Adverse Events
> Definition An adverse event (AE) is any untoward medical occurrence in a subject administered a Study Medication and which does not necessarily have a causal relationship with this treatment. An AE can therefore be any unfavorable and unintended sign (including an abnormal laboratory finding), symptom, or disease temporally associated with the use of whether or not related to the Study Medication (ICH E2A II/A/1, 21 CFR 312.32).
> All pre-existing medical conditions will be recorded on the medical history study document. Starting with the administration of the Study Medication any new experience that was not present at baseline or worsening of an event present at baseline in intensity or frequency, is considered an adverse event.
> Note: Unchanged, chronic conditions are NOT adverse events and should not be recorded.
> It is recognized that subjects will exhibit (throughout follow-up) symptoms of the underlying disease process of that fluctuates in severity and duration.
> Adverse events will include those occurrences, which when compared to before treatment meets any of the following criteria:
> • Represent a new event or escalation of an event; • Require a new escalation in treatment; • Lasts longer; • Experienced more frequently; • More intense; • Different in character ( e.g. stabbing vs. ache); • Experienced in a different part of the body; and/or • Brought on by activity that previously did not cause the symptom.
> Page 51

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 注意：既往已存在的慢性病症不属于不良事件（AE），因此无需记录。

### NCT04210986·条目 13：Unlabelled section (eligibility) (eligibility) · 9

- 条目ID：`wref_translation_item_27bd462552100c4f34332fbc`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 11 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_11:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> If you take back your permission, you will need to leave the research study. Changing your mind will not affect any other treatment, payment, health care, enrollment in health plans, or eligibility for benefits.
> Page 105
> Consent to take Part in Research and Authorization for the Collection, Use, and Disclosure of Health Information Signature of Subject I have read (or someone has read to me) the above information. I have been given an opportunity to ask questions and my questions have been answered to my satisfaction. I agree to participate in this research and authorize the use of my health information as outlined above. I will be given a copy of this signed and dated form.
> Signature of Subject
> Date
> Print Name of Subject
> Time of Consent Signing
> Page 106
> Statement of Person Obtaining Informed Consent and Research Authorization I have carefully explained to the person taking part in the study what he or she can expect from their participation. I confirm that this research subject speaks the language that was used to explain this research and is receiving an informed consent form in their primary language. This research subject has provided legally effective informed consent.
> Signature of Person Obtaining Consent
> Date (must be same as subject’s)
> (must be the PI or delegated MD, NP, or PA)
> Printed Name of Person Obtaining Consent
> Page 107
> Page 108
> Appendix B – Study Schemata
> Page 109
> Appendix C-Augmented Numerical Rating Scale
> Page 110
> Appendix D: Potential Drug Interactions with Fisetin Fisetin has been demonstrated to have inhibitory activity of cytochrome P450 Fisetin has been demonstrated to have inhibitory (competitive mainly) activity of cytochrome P450 isozymes especially CYP2C9 and CYP3A4. CYP2C9 is an important cytochrome P450 isozyme with a major role in the oxid
> …（中略）…
> eizure drugs (i.e. Phenytoin or Dilantin). To accommodate for this, we have constructed an exclusion criteria to mitigate these effects and provide a list of drugs known to interact with crucial CYPs that must be withheld for 2 days prior to Fisetin dosing and during Fisetin administration.
> Page 111

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 日期（须与受试者填写的日期一致）（必须由主要研究者或经授权的医学博士、执业护士或助理医师签署）

### NCT04210986·条目 14：Unlabelled section (eligibility) (eligibility) · 3

- 条目ID：`wref_translation_item_2950ca2c150721cdb752df8b`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 24 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_24:negation_signal_missing`）

**【原文段落】**（英文原文）

> 9.0 Study Population Male and female patients who present to the clinical practices of the Principal Investigator or Sub-Investigators will be enrolled if they meet all eligibility criteria. Subjects from the community who self-identify in response to a flyer, newspaper advertisement, or website will be enrolled if they meet all eligibility criteria.
> Enrollment Criteria
> 9.1.1 Inclusion Criteria Subjects will be included if all of the following criteria are met:
> 1. Are male or female, ages 40-80; 2. Are willing to comply with all study related procedures and assessments; 3. Are ambulatory as defined by ability to complete functional performance testing; 4. Radiographic evidence of Kellgren-Lawrence grade II-IV osteoarthritis in one or both knees; 5. Scores 4-10 on the Numerical Rating Scale (NRS) for pain; 6. Stable dose of screening/baseline medications for at least 2 months prior to the anticipated date of study drug dosing.
> 9.1.2 Exclusion Criteria Subjects will be excluded if any of the following criteria are met:
> 1. Females who are nursing, pregnant or planning to become pregnant during the duration of study drug dosing; 2. Males who do not wish to abstain from sex or use contraceptive protection during study drug dosing and for 2 weeks after the
> last dose; 3. Subjects who do not have the capacity to consent themselves; 4. Subjects who are unable to tolerate oral medication; 5. Subjects having previously undergone any of the following treatments in the stated time window:
> a. Surgery on the Study Knee in the past 6 months; b. Partial or complete joint replacement in the study knee. Partial or complete joint replacement in the
> contralateral knee is acceptable as long as the surgery was performed at least 6 months prior to enrollment and the operative knee is asymptoma
> …（中略）…
> tal involvement or any history of systemic
> inflammatory arthritis; e. Patients with type 1 or 2 diabetes (HbA1c > 6.5%) and/or taking medications that affect insulin levels,
> including: Metformin (within the last week), Glucocorticoids (within the last month), Acarbose (within the last week);
> Page 38

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 过去8周内曾使用过阿片类镇痛药，且不愿意在整个研究期间停用此类药物的受试者；

### NCT04210986·条目 15：Unlabelled section (eligibility) (eligibility) · 7

- 条目ID：`wref_translation_item_2af92ee8432a1781ee0de83e`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Cycle 1: 2 day on (days 1 and 2), followed by 28 days off (day 30). • Cycle 2: 2 days on (days 31 and 32). You will need to come to the study site 4 more times over the next 12 months, for a total of five visits in all. Each research visit will take between 1 and 4 hours to complete. Procedure Visits: If you are an existing patient of one of the study doctors, the physical exams, medical record review, and questionnaire collection are part of standard of care procedures at The Steadman Clinic and may be used to determine eligibility and for Visit 1 of the research study. All other research procedures and treatments for existing patients will be provided at no cost to you. If you are not a current patient of one of the study doctors, all of the research-related procedures and treatments will be provided at no cost to you. Visit 1 (Pre-Treatment/Enrollment)
> Page 88
> • Time frame : Immediately • Visit length : 2-3 hours • A clinical member of the study team will determine if you are eligible to participate. If you're an existing patient, a clinical team member will access your medical records to collect information about you and your medical history. This will include any medications you currently take and other information in your medical records related to your condition or treatment that may be important to your participation in the study. If you are not an existing patient, a member of the clinical team will ask you about yourself and your medical history to determine your eligibility. • A pregnancy test will be performed for all pre-menopausal female participants.
> • If you do not have recent x-rays on file, you will have x-rays taken of your knees. • You will have a 50% chance of being randomly assigned to one of the two treatment groups: 1. Fisetin group (investigat
> …（中略）…
> nt information. o What the placebo in this study is:
> ▪ The placebo is a pill that looks like medicine but is not real; it will have no medical effect on you. • You will have your blood drawn to collect 50 milliliters (10 teaspoons) of blood for lab screenings and protein testing. Visit 2 (Treatment)

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 第一周期：用药2天（第1天和第2天），随后停药28天（至第30天）。 • 第二周期：用药2天（第31天和第32天）。在接下来的12个月内，您还需前往研究中心4次，合计共进行5次访视。每次研究相关的访视耗时约1至4小时。
> 检查流程相关说明：如果您已经是参与研究的某位医生的就诊患者，那么体格检查、病史查阅以及问卷调查均属于Steadman诊所的常规诊疗流程；这些内容也可用于判定您是否符合研究入组条件，并作为研究的第1次访视。对于此类患者而言，所有其他研究相关的流程与治疗均无需您支付任何费用。
> 如果您目前并非参与研究的某位医生的就诊患者，那么所有研究相关的流程与治疗同样均无需您支付任何费用。
> 第1次访视（治疗前/入组阶段）

### NCT04210986·条目 16：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 11

- 条目ID：`wref_translation_item_2c13479b0770dd5feea783d0`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）

**【原文段落】**（英文原文）

> Whenever applicable, assessment of endpoints that are measured at serial time points will be analyzed using methods that account for this repeated measure structure. Listwise deletion in response to missing data points and categorization/dichotomization of continuous measurements will be avoided to every extent possible. Summary statistics will be reported as group medians with quartiles or extrema. Meanwhile estimates calculated for statistical inference will be reported with (1-α)% confidence intervals. Model fit and satisfactorily meeting model assumptions will be assessed for all multivariable regression and linear mixed-effects models using residual analysis. The Statistical Computing Language R will be used to produce all analyses and plots.
> Endpoints
> 15.5.1 Primary Endpoint The safety of FIS administration is the primary endpoint of this study. All adverse events will be compared by category of description incidence, relatedness to treatment, severity, duration and expectedness. The occurrence of non-serious and serious and unexpected adverse events will be compared between treatment groups. Bivariate analysis will be performed between group and each safety variable of interest independently. When comparing the two treatment groups, dichotomous (yes/no) endpoints will be assessed for association using Fisher’s exact test. Adverse events and symptoms that may occur multiple times in a single subject will be analyzed as count variables, and group differences will be assessed using simple Poisson regression or simple negative binomial regression. This is a small Phase I/II trial in which to assess safety, thus we will report all safety data thoroughly and aim to liberally identify potential side-effects and risks that may warrant close study in future, larger trials
> …（中略）…
> ow aspirate concentrate) or a surgical intervention (e.g. microfracture or total joint replacement), they will be removed from the study. Cox proportional hazards regression will be performed to compare the hazard rate of conversion to each of these two treatment categories between treatment groups.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 将在研究药物末次给药后第2周，以及用药开始后第6个月、12个月和18个月时，对IKDC评分、WOMAC量表得分、Tegner活动能力分级以及Lysholm患者报告结局指标进行测量。在每个时间点，均将采用ANCOVA分析方法，并以该受试者基线时的PROM数值作为协变量。在用于评估这些经验证的PROM指标的4个术后时间点中，将采用Holm-Bonferroni法对各量表的整体第一类错误率加以控制，确保其不高于0.05。由于不同PROM指标之间通常存在高度相关性，因此不会针对这些指标另行实施多重性校正。

### NCT04210986·条目 17：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_2ec2667e4b0b78b5a1d6d187`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> To evaluate as compared to placebo: The safety of administering Fisetin in subjects with osteoarthritis (OA) of the knee. Secondary Objectives To evaluate as compared to placebo:
> 1. Reduction of pro-inflammatory and cartilage degenerating SASP markers;
> 2. Improvement in physical function of the Study Knee;
> 3. Improvement in patient reported outcomes;
> 4. Improvement in the quality of articular cartilage in the Study Knee with quantitative
> magnetic resonance imaging (MRI);
> 5. Reduction in time to conversion to alternative treatment. Endpoints:
> Primary Endpoint: Occurrence of adverse events. Secondary Endpoints Statistically significant as compared to placebo:
> 1. Improvement in serum measures of inflammation and cartilage degenerating senescence
> associated secretory phenotype (SASP) markers; 2. Improvement in lower-extremity kinematic testing with video-motion analysis;
> isokinetic dynamometry testing, functional performance testing, range of motion (ROM);
> Page 14
> | (EOSa). While the Sponsor will be u Investigator and the subject will rem | 3. Improvement in patient reported outcomes (PROs), including: IKDC, Lysholm, TEGNER, WOMAC and SF-12 surveys; 4. Improvement in the quality of articular cartilage in the knee joint as measured by T2 and T1rho relaxometry; 5. Days from day one of Study Medication intake to conversion to alternative therapy. Additionally, we will review and discuss any possible correlation among secondary endpoint results. nblinded to study treatment after the Phase A analysis, the ain blinded. SS OF BLINDING BLIND/PARTICIPANT CODE ied physician who is an Investigator in this study in the ich knowledge of the identity of the study medication is |
> | 10.6.2 EVALUATION OF SUCCE Not applicable to this study. | |
> | 10.6.3 BREAKING THE STUDY The blind may be br
> …（中略）…
> sis; 13. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER,
> WOMAC and SF-12; 14. A radiograph of the target knee will be performed to confirm the presence of Kellgren-
> Lawrence grade II-IV OA; 15. The patients’ medical record will be reviewed, and the subject will be interviewed to

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 3. 患者报告结局（PROs）的改善情况，具体指标包括：IKDC、Lysholm评分表、TEGNER量表、WOMAC评估及SF-12调查问卷；4. 通过T2与T1rho弛豫测量法测定的膝关节软骨质量改善情况；5. 从开始服用研究药物之日起至改用其他治疗方案所需的天数。此外，我们还将对各项次要终点结果之间可能存在的关联性予以评估与探讨。在A阶段分析完成后，所有受试者均处于盲态；CODE为BLIND/PARTICIPANT CODE。本研究中的研究者均为对研究药物具体成分完全不知情的医师，即处于BLIND状态。

### NCT04210986·条目 18：Unlabelled section (eligibility) (eligibility) · 3

- 条目ID：`wref_translation_item_2f42617e309ec1c1480e5add`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 24 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_24:negation_signal_missing`）

**【原文段落】**（英文原文）

> 9.0 Study Population Male and female patients who present to the clinical practices of the Principal Investigator or Sub-Investigators will be enrolled if they meet all eligibility criteria. Subjects from the community who self-identify in response to a flyer, newspaper advertisement, or website will be enrolled if they meet all eligibility criteria.
> Enrollment Criteria
> 9.1.1 Inclusion Criteria Subjects will be included if all of the following criteria are met:
> 1. Are male or female, ages 40-80; 2. Are willing to comply with all study related procedures and assessments; 3. Are ambulatory as defined by ability to complete functional performance testing; 4. Radiographic evidence of Kellgren-Lawrence grade II-IV osteoarthritis in one or both knees; 5. Scores 4-10 on the Numerical Rating Scale (NRS) for pain; 6. Stable dose of screening/baseline medications for at least 2 months prior to the anticipated date of study drug dosing.
> 9.1.2 Exclusion Criteria Subjects will be excluded if any of the following criteria are met:
> 1. Females who are nursing, pregnant or planning to become pregnant during the duration of study drug dosing; 2. Males who do not wish to abstain from sex or use contraceptive protection during study drug dosing and for 2 weeks after the
> last dose; 3. Subjects who do not have the capacity to consent themselves; 4. Subjects who are unable to tolerate oral medication; 5. Subjects having previously undergone any of the following treatments in the stated time window:
> a. Surgery on the Study Knee in the past 6 months; b. Partial or complete joint replacement in the study knee. Partial or complete joint replacement in the
> contralateral knee is acceptable as long as the surgery was performed at least 6 months prior to enrollment and the operative knee is asymptoma
> …（中略）…
> tal involvement or any history of systemic
> inflammatory arthritis; e. Patients with type 1 or 2 diabetes (HbA1c > 6.5%) and/or taking medications that affect insulin levels,
> including: Metformin (within the last week), Glucocorticoids (within the last month), Acarbose (within the last week);
> Page 38

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 过去8周内曾使用过阿片类镇痛药，且不愿意在整个研究期间停用此类药物的受试者；

### NCT04210986·条目 19：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 7

- 条目ID：`wref_translation_item_3077fb0801b57e10a82cbab0`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_2:numeric_tokens_changed`）
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Patient Reported Outcomes (PROs): (Visits 1, 2, 4, 5, 6)
> All PROs may be completed either on paper documents or by online questionnaire administration conducted via formsite (Vroman Systems, Inc.). Patients may complete questionnaires on a variety of electronic devices (personal computer, mobile phone, tablet). PRO data to be collected include: Augmented Numerical Rating Scale (NRS) (visit 2): At baseline then once every 3 days during FIRST 6 weeks of study medication treatment then once a week for an ADDITIONAL 6 weeks. IKDC, Lysholm, TEGNER, WOMAC and SF-12 (visit 2, visits 4, 5, and 6 and remote assessments at 3- and 18-months post completion of medication).
> Page 46
> The Numerical Rating Scale is a simple 0-10 self-reported severity of pain scale, (zero being no pain and 10 being the worst pain imaginable). This tool has been validated to provide excellent test-retest reliability in assessing knee pain associated with OA 31 . The Steadman Philippon Research Institute has added several stand-alone questions that are administered with the questionnaire. Only the validated portion, the simple NRS will be used to screen patients. In follow-up, each question will be analyzed individually. There is no composite score. A sample can be found in Appendix C, Section 22.3 of this document.
> The Lysholm knee scale is a condition-specific outcome measure that was originally designed to assess ligament injuries of the knee. It has been tested to provide excellent construct validity and overall acceptable psychometric performance for outcomes assessment of various chondral disorders of the knee. It is recommended that this tool be administered with additional psychometric measurements 32,33 . The TEGNER Activity Scale is a numerical scale ranging from 0 to 10. Each value indicates th
> …（中略）…
> n left/right sides (5 min). As is standard practice when using the HUMAC NORM system, padded straps will be used on the participant's torso and legs in order to isolate the lower leg movements and reduce the contribution of other muscles. All measurements will be normalized to % body weight.
> Page 50

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 所有患者报告结局（PRO）问卷均可通过纸质表格填写，也可借助Formsite平台（Vroman Systems, Inc.公司开发）在线完成。患者可在各类电子设备上填写问卷，包括个人电脑、手机及平板电脑等。需采集的患者报告结局数据如下：增强型数值评分量表（NRS）（第2次访视）：于基线时填写一次，随后在研究用药治疗的前6周内每隔3天填写一次；再接下来的6周则每周填写一次。此外还需采集IKDC量表、Lysholm评分表、TEGNER活动分级量表、WOMAC膝关节功能评估量表以及SF-12健康调查简表的相关数据（第2、4、5及6次访视时填写，并在用药结束后3个月与18个月时进行远程评估）。

### NCT04210986·条目 20：Unlabelled section (safety) (safety) · 11

- 条目ID：`wref_translation_item_32b4de338c6800ffb2bf8941`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Time frame : within 3 months of Visit 1 • Visit length : 3-4 hours • Vital signs, medication information, and any adverse events that occurred since the last visit will be collected. • A pregnancy test will be performed for all pre-menopausal female participants. • The following procedures and tests will be performed: ▪ Medication instructions; ▪ Magnetic resonance imaging (MRI) scan; ▪ Functional performance testing; ▪ Physical exam; ▪ Muscle strength testing; ▪ Video-motion analysis. • Note that the blood test and knee x-ray may be performed at this visit if it was not done at visit 1. • Some of the screening procedures may need to be repeated for accuracy, fidelity, and/or safety.
> Page 89
> • Vail Health Pharmacy will be responsible for dispensing the Fisetin or placebo capsules. Fisetin or placebo capsules will be given to you in a bottle with a set of instructions. • After completing the study tests for this visit, you will be given Fisetin or placebo capsules as treatment. You will be instructed to take capsules while at the study site and the next day (10-15 capsules per day, amount based on body weight). You will be instructed to take the capsules for 2 cycles of treatment:
> o Cycle 1: 2 days on (days 1 and 2), followed by 28 days off (day 30). o Cycle 2: 2 days on (days 31 and 32). o Treatment will occur over the course of approximately 5 weeks. • All capsules must be taken within 60 minutes after the first capsule is consumed. • At Visit 4, please return any remaining capsules in the bottle. These extra capsules will be counted and discarded at your next on-site visit. • You will be given a drug diary/schedule to log each dose you take during the 2 treatment cycles. • A member of the clinical team will contact you via phone call three times while you are schedu
> …（中略）…
> m/study will not cover the costs of any follow-up consultations or actions. If you are not interested in receiving this information, please do not consent to participate in this study.
> Page 101
> XVI. Who should I contact if I have questions about the research? Contact the researchers at 970-476-1100:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • Vail Health药房将负责发放非瑟酮或安慰剂胶囊。这些胶囊会连同使用说明一同装入药瓶中提供给您。• 完成本次访视的各项研究检查后，您将开始服用非瑟酮或安慰剂胶囊进行治疗。工作人员会指导您在研究中心及次日按时服药（每日剂量为10至15粒，具体数量视体重而定）。您需连续完成2个治疗周期： o 第1周期：服药2天（即第1和第2日），随后停药28天（至第30日）。 o 第2周期：服药2天（即第31和第32日）。 o 整个治疗过程约持续5周。• 所有胶囊必须在您服下第一粒后的60分钟内全部服用完毕。• 在第4次访视时，请您将药瓶中剩余的胶囊一并交回。这些多余的胶囊会在您下次到研究中心时经清点后予以废弃处理。• 我们将向您提供用药记录本/日程表，以便详细记载您在2个治疗周期内每次的服药情况。

### NCT04210986·条目 21：5.0 Introduction (objectives_endpoints)

- 条目ID：`wref_translation_item_32bd73a13a754c1387612846`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_4:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> In this randomized, double-blind, placebo-controlled clinical trial, we intend to measure and compare safety via the gathering of all adverse events and preliminary evidence of efficacy through recording of SASP, inflammatory biomarkers and senescent cells. In addition, magnetic resonance imaging (MRI) exams, self-reported outcomes, functional performance and other relevant clinical data will be gathered. Possible correlation among outcomes, both structural and non-structural, will be described. Each subject is to be followed for 18 months.
> Page 23
> Rationale Aging is associated with the accumulation of senescent cells, which have lost their ability to proliferate and resist apoptosis. Aging cells produce a SASP consisting of potent pro-inflammatory and stress inducing factors 2-5 . OA, along with a litany of other age-related pathologies, is associated with cellular senescence, which is thought to promote aging via the chronic induction of inflammation 2-6 . OA is a debilitating and costly joint disease that affects millions of individuals each year for which there are no available disease modifying therapies 7,8 . Several studies have shown that spontaneous age-associated and post-traumatic OA (PTOA) is characterized by an increase in senescent chondrocytes within the joint capsule 9-13 that is thought to promote early inflammation and OA pathogenesis. Importantly, it was found that injection of senescent cells into the joint capsule of healthy mice could alone induce OA-like conditions in mice including severe cartilage degeneration, erosion of femoral condyles, subchondral bone structure alteration, osteophyte formation, and meniscal damage 14 . Inversely, other groups have shown that local clearance of senescent cells genetically within the intra-articular space sig
> …（中略）…
> by T-Cell assay and by senescence biomarker assay. Further blood analyses will be performed. At 6-, 12- and 18-months post first dose of Study Medication, subjects will be asked to complete the augmented NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12 remotely, either electronically or on paper.
> Page 29

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 相反，其他研究团队已证实：在关节腔内通过基因手段清除衰老细胞可显著减轻损伤诱发的OA发生，并营造出有利于组织再生的环境15。由此可见，细胞衰老与OA发病机制之间存在密切关联；这也使得清除衰老细胞的药物成为预防或治疗OA极具前景且创新的治疗手段。目前共有三项II期临床试验正在开展，旨在评估FIS在多种衰老相关疾病中的疗效：包括虚弱、炎症以及糖尿病与慢性肾脏病，对应的试验编号分别为NCT03430037、NCT03675724和NCT03325322。迄今为止，尚未有任何人体研究对清除衰老细胞药物用于膝关节OA治疗的情况进行过对试验药物的评估。

### NCT04210986·条目 22：Unlabelled section (eligibility) (eligibility) · 9

- 条目ID：`wref_translation_item_3377b024a25694af6344de1b`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 11 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_11:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> If you take back your permission, you will need to leave the research study. Changing your mind will not affect any other treatment, payment, health care, enrollment in health plans, or eligibility for benefits.
> Page 105
> Consent to take Part in Research and Authorization for the Collection, Use, and Disclosure of Health Information Signature of Subject I have read (or someone has read to me) the above information. I have been given an opportunity to ask questions and my questions have been answered to my satisfaction. I agree to participate in this research and authorize the use of my health information as outlined above. I will be given a copy of this signed and dated form.
> Signature of Subject
> Date
> Print Name of Subject
> Time of Consent Signing
> Page 106
> Statement of Person Obtaining Informed Consent and Research Authorization I have carefully explained to the person taking part in the study what he or she can expect from their participation. I confirm that this research subject speaks the language that was used to explain this research and is receiving an informed consent form in their primary language. This research subject has provided legally effective informed consent.
> Signature of Person Obtaining Consent
> Date (must be same as subject’s)
> (must be the PI or delegated MD, NP, or PA)
> Printed Name of Person Obtaining Consent
> Page 107
> Page 108
> Appendix B – Study Schemata
> Page 109
> Appendix C-Augmented Numerical Rating Scale
> Page 110
> Appendix D: Potential Drug Interactions with Fisetin Fisetin has been demonstrated to have inhibitory activity of cytochrome P450 Fisetin has been demonstrated to have inhibitory (competitive mainly) activity of cytochrome P450 isozymes especially CYP2C9 and CYP3A4. CYP2C9 is an important cytochrome P450 isozyme with a major role in the oxid
> …（中略）…
> eizure drugs (i.e. Phenytoin or Dilantin). To accommodate for this, we have constructed an exclusion criteria to mitigate these effects and provide a list of drugs known to interact with crucial CYPs that must be withheld for 2 days prior to Fisetin dosing and during Fisetin administration.
> Page 111

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 日期（须与受试者填写的日期一致）（必须由主要研究者或经授权的医学博士、执业护士或助理医师签署）

### NCT04210986·条目 23：Unlabelled section (safety) (safety) · 11

- 条目ID：`wref_translation_item_40fccab7773156d62b7f33b5`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Time frame : within 3 months of Visit 1 • Visit length : 3-4 hours • Vital signs, medication information, and any adverse events that occurred since the last visit will be collected. • A pregnancy test will be performed for all pre-menopausal female participants. • The following procedures and tests will be performed: ▪ Medication instructions; ▪ Magnetic resonance imaging (MRI) scan; ▪ Functional performance testing; ▪ Physical exam; ▪ Muscle strength testing; ▪ Video-motion analysis. • Note that the blood test and knee x-ray may be performed at this visit if it was not done at visit 1. • Some of the screening procedures may need to be repeated for accuracy, fidelity, and/or safety.
> Page 89
> • Vail Health Pharmacy will be responsible for dispensing the Fisetin or placebo capsules. Fisetin or placebo capsules will be given to you in a bottle with a set of instructions. • After completing the study tests for this visit, you will be given Fisetin or placebo capsules as treatment. You will be instructed to take capsules while at the study site and the next day (10-15 capsules per day, amount based on body weight). You will be instructed to take the capsules for 2 cycles of treatment:
> o Cycle 1: 2 days on (days 1 and 2), followed by 28 days off (day 30). o Cycle 2: 2 days on (days 31 and 32). o Treatment will occur over the course of approximately 5 weeks. • All capsules must be taken within 60 minutes after the first capsule is consumed. • At Visit 4, please return any remaining capsules in the bottle. These extra capsules will be counted and discarded at your next on-site visit. • You will be given a drug diary/schedule to log each dose you take during the 2 treatment cycles. • A member of the clinical team will contact you via phone call three times while you are schedu
> …（中略）…
> m/study will not cover the costs of any follow-up consultations or actions. If you are not interested in receiving this information, please do not consent to participate in this study.
> Page 101
> XVI. Who should I contact if I have questions about the research? Contact the researchers at 970-476-1100:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • Vail Health药房将负责发放非瑟酮或安慰剂胶囊。这些胶囊会连同使用说明一同装入药瓶中提供给您。• 完成本次访视的各项研究检查后，您将开始服用非瑟酮或安慰剂胶囊进行治疗。工作人员会指导您在研究中心及次日按时服药（每日剂量为10至15粒，具体数量视体重而定）。您需连续完成2个治疗周期： o 第1周期：服药2天（即第1和第2日），随后停药28天（至第30日）。 o 第2周期：服药2天（即第31和第32日）。 o 整个治疗过程约持续5周。• 所有胶囊必须在您服下第一粒后的60分钟内全部服用完毕。• 在第4次访视时，请您将药瓶中剩余的胶囊一并交回。这些多余的胶囊会在您下次到研究中心时经清点后予以废弃处理。• 我们将向您提供用药记录本/日程表，以便详细记载您在2个治疗周期内每次的服药情况。

### NCT04210986·条目 24：5.0 Introduction (objectives_endpoints)

- 条目ID：`wref_translation_item_4c5dfa46b0b044bfe9496dce`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_4:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> In this randomized, double-blind, placebo-controlled clinical trial, we intend to measure and compare safety via the gathering of all adverse events and preliminary evidence of efficacy through recording of SASP, inflammatory biomarkers and senescent cells. In addition, magnetic resonance imaging (MRI) exams, self-reported outcomes, functional performance and other relevant clinical data will be gathered. Possible correlation among outcomes, both structural and non-structural, will be described. Each subject is to be followed for 18 months.
> Page 23
> Rationale Aging is associated with the accumulation of senescent cells, which have lost their ability to proliferate and resist apoptosis. Aging cells produce a SASP consisting of potent pro-inflammatory and stress inducing factors 2-5 . OA, along with a litany of other age-related pathologies, is associated with cellular senescence, which is thought to promote aging via the chronic induction of inflammation 2-6 . OA is a debilitating and costly joint disease that affects millions of individuals each year for which there are no available disease modifying therapies 7,8 . Several studies have shown that spontaneous age-associated and post-traumatic OA (PTOA) is characterized by an increase in senescent chondrocytes within the joint capsule 9-13 that is thought to promote early inflammation and OA pathogenesis. Importantly, it was found that injection of senescent cells into the joint capsule of healthy mice could alone induce OA-like conditions in mice including severe cartilage degeneration, erosion of femoral condyles, subchondral bone structure alteration, osteophyte formation, and meniscal damage 14 . Inversely, other groups have shown that local clearance of senescent cells genetically within the intra-articular space sig
> …（中略）…
> by T-Cell assay and by senescence biomarker assay. Further blood analyses will be performed. At 6-, 12- and 18-months post first dose of Study Medication, subjects will be asked to complete the augmented NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12 remotely, either electronically or on paper.
> Page 29

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 相反，其他研究团队已证实：在关节腔内通过基因手段清除衰老细胞可显著减轻损伤诱发的OA发生，并营造出有利于组织再生的环境15。由此可见，细胞衰老与OA发病机制之间存在密切关联；这也使得清除衰老细胞的药物成为预防或治疗OA极具前景且创新的治疗手段。目前共有三项II期临床试验正在开展，旨在评估FIS在多种衰老相关疾病中的疗效：包括虚弱、炎症以及糖尿病与慢性肾脏病，对应的试验编号分别为NCT03430037、NCT03675724和NCT03325322。迄今为止，尚未有任何人体研究对清除衰老细胞药物用于膝关节OA治疗的情况进行过对试验药物的评估。

### NCT04210986·条目 25：Unlabelled section (safety) (safety) · 11

- 条目ID：`wref_translation_item_4ca420008d8217bc4f49c7be`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Time frame : within 3 months of Visit 1 • Visit length : 3-4 hours • Vital signs, medication information, and any adverse events that occurred since the last visit will be collected. • A pregnancy test will be performed for all pre-menopausal female participants. • The following procedures and tests will be performed: ▪ Medication instructions; ▪ Magnetic resonance imaging (MRI) scan; ▪ Functional performance testing; ▪ Physical exam; ▪ Muscle strength testing; ▪ Video-motion analysis. • Note that the blood test and knee x-ray may be performed at this visit if it was not done at visit 1. • Some of the screening procedures may need to be repeated for accuracy, fidelity, and/or safety.
> Page 89
> • Vail Health Pharmacy will be responsible for dispensing the Fisetin or placebo capsules. Fisetin or placebo capsules will be given to you in a bottle with a set of instructions. • After completing the study tests for this visit, you will be given Fisetin or placebo capsules as treatment. You will be instructed to take capsules while at the study site and the next day (10-15 capsules per day, amount based on body weight). You will be instructed to take the capsules for 2 cycles of treatment:
> o Cycle 1: 2 days on (days 1 and 2), followed by 28 days off (day 30). o Cycle 2: 2 days on (days 31 and 32). o Treatment will occur over the course of approximately 5 weeks. • All capsules must be taken within 60 minutes after the first capsule is consumed. • At Visit 4, please return any remaining capsules in the bottle. These extra capsules will be counted and discarded at your next on-site visit. • You will be given a drug diary/schedule to log each dose you take during the 2 treatment cycles. • A member of the clinical team will contact you via phone call three times while you are schedu
> …（中略）…
> m/study will not cover the costs of any follow-up consultations or actions. If you are not interested in receiving this information, please do not consent to participate in this study.
> Page 101
> XVI. Who should I contact if I have questions about the research? Contact the researchers at 970-476-1100:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • Vail Health药房将负责发放非瑟酮或安慰剂胶囊。这些胶囊会连同使用说明一同装入药瓶中提供给您。• 完成本次访视的各项研究检查后，您将开始服用非瑟酮或安慰剂胶囊进行治疗。工作人员会指导您在研究中心及次日按时服药（每日剂量为10至15粒，具体数量视体重而定）。您需连续完成2个治疗周期： o 第1周期：服药2天（即第1和第2日），随后停药28天（至第30日）。 o 第2周期：服药2天（即第31和第32日）。 o 整个治疗过程约持续5周。• 所有胶囊必须在您服下第一粒后的60分钟内全部服用完毕。• 在第4次访视时，请您将药瓶中剩余的胶囊一并交回。这些多余的胶囊会在您下次到研究中心时经清点后予以废弃处理。• 我们将向您提供用药记录本/日程表，以便详细记载您在2个治疗周期内每次的服药情况。

### NCT04210986·条目 26：12.0 Study Management of Adverse Events (safety)

- 条目ID：`wref_translation_item_4ff1684d04097ac9eda352b9`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_4:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 12.0 Study Management of Adverse Events
> Definition An adverse event (AE) is any untoward medical occurrence in a subject administered a Study Medication and which does not necessarily have a causal relationship with this treatment. An AE can therefore be any unfavorable and unintended sign (including an abnormal laboratory finding), symptom, or disease temporally associated with the use of whether or not related to the Study Medication (ICH E2A II/A/1, 21 CFR 312.32).
> All pre-existing medical conditions will be recorded on the medical history study document. Starting with the administration of the Study Medication any new experience that was not present at baseline or worsening of an event present at baseline in intensity or frequency, is considered an adverse event.
> Note: Unchanged, chronic conditions are NOT adverse events and should not be recorded.
> It is recognized that subjects will exhibit (throughout follow-up) symptoms of the underlying disease process of that fluctuates in severity and duration.
> Adverse events will include those occurrences, which when compared to before treatment meets any of the following criteria:
> • Represent a new event or escalation of an event; • Require a new escalation in treatment; • Lasts longer; • Experienced more frequently; • More intense; • Different in character ( e.g. stabbing vs. ache); • Experienced in a different part of the body; and/or • Brought on by activity that previously did not cause the symptom.
> Page 51

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 注意：既往已存在的慢性病症不属于不良事件（AE），因此无需记录。

### NCT04210986·条目 27：12.0 Study Management of Adverse Events (safety)

- 条目ID：`wref_translation_item_5430105918723e6dd8209847`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_4:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 12.0 Study Management of Adverse Events
> Definition An adverse event (AE) is any untoward medical occurrence in a subject administered a Study Medication and which does not necessarily have a causal relationship with this treatment. An AE can therefore be any unfavorable and unintended sign (including an abnormal laboratory finding), symptom, or disease temporally associated with the use of whether or not related to the Study Medication (ICH E2A II/A/1, 21 CFR 312.32).
> All pre-existing medical conditions will be recorded on the medical history study document. Starting with the administration of the Study Medication any new experience that was not present at baseline or worsening of an event present at baseline in intensity or frequency, is considered an adverse event.
> Note: Unchanged, chronic conditions are NOT adverse events and should not be recorded.
> It is recognized that subjects will exhibit (throughout follow-up) symptoms of the underlying disease process of that fluctuates in severity and duration.
> Adverse events will include those occurrences, which when compared to before treatment meets any of the following criteria:
> • Represent a new event or escalation of an event; • Require a new escalation in treatment; • Lasts longer; • Experienced more frequently; • More intense; • Different in character ( e.g. stabbing vs. ache); • Experienced in a different part of the body; and/or • Brought on by activity that previously did not cause the symptom.
> Page 51

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 注意：既往已存在的慢性病症不属于不良事件（AE），因此无需记录。

### NCT04210986·条目 28：Unlabelled section (eligibility) (eligibility) · 7

- 条目ID：`wref_translation_item_556e504ff4ea59f6863967ce`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Cycle 1: 2 day on (days 1 and 2), followed by 28 days off (day 30). • Cycle 2: 2 days on (days 31 and 32). You will need to come to the study site 4 more times over the next 12 months, for a total of five visits in all. Each research visit will take between 1 and 4 hours to complete. Procedure Visits: If you are an existing patient of one of the study doctors, the physical exams, medical record review, and questionnaire collection are part of standard of care procedures at The Steadman Clinic and may be used to determine eligibility and for Visit 1 of the research study. All other research procedures and treatments for existing patients will be provided at no cost to you. If you are not a current patient of one of the study doctors, all of the research-related procedures and treatments will be provided at no cost to you. Visit 1 (Pre-Treatment/Enrollment)
> Page 88
> • Time frame : Immediately • Visit length : 2-3 hours • A clinical member of the study team will determine if you are eligible to participate. If you're an existing patient, a clinical team member will access your medical records to collect information about you and your medical history. This will include any medications you currently take and other information in your medical records related to your condition or treatment that may be important to your participation in the study. If you are not an existing patient, a member of the clinical team will ask you about yourself and your medical history to determine your eligibility. • A pregnancy test will be performed for all pre-menopausal female participants.
> • If you do not have recent x-rays on file, you will have x-rays taken of your knees. • You will have a 50% chance of being randomly assigned to one of the two treatment groups: 1. Fisetin group (investigat
> …（中略）…
> nt information. o What the placebo in this study is:
> ▪ The placebo is a pill that looks like medicine but is not real; it will have no medical effect on you. • You will have your blood drawn to collect 50 milliliters (10 teaspoons) of blood for lab screenings and protein testing. Visit 2 (Treatment)

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 第一周期：用药2天（第1天和第2天），随后停药28天（至第30天）。 • 第二周期：用药2天（第31天和第32天）。在接下来的12个月内，您还需前往研究中心4次，合计共进行5次访视。每次研究相关的访视耗时约1至4小时。
> 检查流程相关说明：如果您已经是参与研究的某位医生的就诊患者，那么体格检查、病史查阅以及问卷调查均属于Steadman诊所的常规诊疗流程；这些内容也可用于判定您是否符合研究入组条件，并作为研究的第1次访视。对于此类患者而言，所有其他研究相关的流程与治疗均无需您支付任何费用。
> 如果您目前并非参与研究的某位医生的就诊患者，那么所有研究相关的流程与治疗同样均无需您支付任何费用。
> 第1次访视（治疗前/入组阶段）

### NCT04210986·条目 29：Unlabelled section (safety) (safety) · 11

- 条目ID：`wref_translation_item_577063617cbf2c67674106bc`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Time frame : within 3 months of Visit 1 • Visit length : 3-4 hours • Vital signs, medication information, and any adverse events that occurred since the last visit will be collected. • A pregnancy test will be performed for all pre-menopausal female participants. • The following procedures and tests will be performed: ▪ Medication instructions; ▪ Magnetic resonance imaging (MRI) scan; ▪ Functional performance testing; ▪ Physical exam; ▪ Muscle strength testing; ▪ Video-motion analysis. • Note that the blood test and knee x-ray may be performed at this visit if it was not done at visit 1. • Some of the screening procedures may need to be repeated for accuracy, fidelity, and/or safety.
> Page 89
> • Vail Health Pharmacy will be responsible for dispensing the Fisetin or placebo capsules. Fisetin or placebo capsules will be given to you in a bottle with a set of instructions. • After completing the study tests for this visit, you will be given Fisetin or placebo capsules as treatment. You will be instructed to take capsules while at the study site and the next day (10-15 capsules per day, amount based on body weight). You will be instructed to take the capsules for 2 cycles of treatment:
> o Cycle 1: 2 days on (days 1 and 2), followed by 28 days off (day 30). o Cycle 2: 2 days on (days 31 and 32). o Treatment will occur over the course of approximately 5 weeks. • All capsules must be taken within 60 minutes after the first capsule is consumed. • At Visit 4, please return any remaining capsules in the bottle. These extra capsules will be counted and discarded at your next on-site visit. • You will be given a drug diary/schedule to log each dose you take during the 2 treatment cycles. • A member of the clinical team will contact you via phone call three times while you are schedu
> …（中略）…
> m/study will not cover the costs of any follow-up consultations or actions. If you are not interested in receiving this information, please do not consent to participate in this study.
> Page 101
> XVI. Who should I contact if I have questions about the research? Contact the researchers at 970-476-1100:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • Vail Health药房将负责发放非瑟酮或安慰剂胶囊。这些胶囊会连同使用说明一同装入药瓶中提供给您。• 完成本次访视的各项研究检查后，您将开始服用非瑟酮或安慰剂胶囊进行治疗。工作人员会指导您在研究中心及次日按时服药（每日剂量为10至15粒，具体数量视体重而定）。您需连续完成2个治疗周期： o 第1周期：服药2天（即第1和第2日），随后停药28天（至第30日）。 o 第2周期：服药2天（即第31和第32日）。 o 整个治疗过程约持续5周。• 所有胶囊必须在您服下第一粒后的60分钟内全部服用完毕。• 在第4次访视时，请您将药瓶中剩余的胶囊一并交回。这些多余的胶囊会在您下次到研究中心时经清点后予以废弃处理。• 我们将向您提供用药记录本/日程表，以便详细记载您在2个治疗周期内每次的服药情况。

### NCT04210986·条目 30：Unlabelled section (safety) (safety) · 3

- 条目ID：`wref_translation_item_5b00434f92cddd77ac479c2d`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> Independent Medical Monitoring will be provided by an appropriately certified physician responsible for overseeing the occurrence of adverse events and for providing medical advisory assistance to the Study Team. Medical Monitor Gil Price, M.D. Chief Medical Officer at ProPharma Group 8717 W. 110th St., Ste. 300 Overland Park, Kansas, United States (913) 661-1662 Gil.Price@propharmagroup.com
> The Study Team Dr. Evans and his team will lead the clinical elements of the study. In addition, the teams of Dr. Kim, Dr. Leslie Vidal, Dr. Armando Vidal, and Dr. Godin at TSC will assist in enrollment of patients into the study. Dr. Ho will read and analyze all MRI imaging. Dr. Tashman will lead a team of research associates for all duties related to functional performance, muscle strength testing, and kinematics. There will also be a team of investigators and research associates at SPRI selected by Dr. Huard to whom appropriated duties will be delegated according to their specific qualifications. Collectively Dr. Evans, Dr. Kim, Dr. L. Vidal, Dr. A. Vidal, Dr. Godin, Dr. Huard, Dr. Ho, Dr. Tashman and their designees are referred to as the “Study Team”. Primary Contact for the Study Johnny Huard, Ph.D. Chief Scientific Officer and Director of the Center for Regenerative Sports Medicine
> Steadman Philippon Research Institute 181 West Meadow Drive, Suite 1000 Vail, CO 81657 (970) 476-1100 jhuard@sprivail.org
> Page 11
> 2.0 Protocol Signature Page The signature below constitutes the approval of this protocol entitled, Senolytic Drugs Attenuate Osteoarthritis-Related Articular Cartilage Degeneration: A Clinical Trial with attachments, and provides the necessary assurances that this trial will be conducted in compliance of all stipulations of the protocol, including all statements regardi
> …（中略）…
>  E6 (ICH-GCP), and applicable US regulatory requirements.
> Principal Investigator: ___________________________________________________
> Print/Type Title: __________________________________________________________________ Signed: ________________________________________ Date : _________________
> Page 12

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 将由具备相应资质的医师担任独立医学监查员，负责监督不良事件的发生情况并向研究团队提供医学咨询协助。该医学监查员为Gil Price医师，现任ProPharma Group公司首席医疗官。办公地址：美国堪萨斯州欧弗兰帕克市西110街8717号300室；联系电话：(913) 661-1662；电子邮箱：Gil.Price@propharmagroup.com。

### NCT04210986·条目 31：12.0 Study Management of Adverse Events (safety)

- 条目ID：`wref_translation_item_5c8cf326c88517142668fa89`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_4:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 12.0 Study Management of Adverse Events
> Definition An adverse event (AE) is any untoward medical occurrence in a subject administered a Study Medication and which does not necessarily have a causal relationship with this treatment. An AE can therefore be any unfavorable and unintended sign (including an abnormal laboratory finding), symptom, or disease temporally associated with the use of whether or not related to the Study Medication (ICH E2A II/A/1, 21 CFR 312.32).
> All pre-existing medical conditions will be recorded on the medical history study document. Starting with the administration of the Study Medication any new experience that was not present at baseline or worsening of an event present at baseline in intensity or frequency, is considered an adverse event.
> Note: Unchanged, chronic conditions are NOT adverse events and should not be recorded.
> It is recognized that subjects will exhibit (throughout follow-up) symptoms of the underlying disease process of that fluctuates in severity and duration.
> Adverse events will include those occurrences, which when compared to before treatment meets any of the following criteria:
> • Represent a new event or escalation of an event; • Require a new escalation in treatment; • Lasts longer; • Experienced more frequently; • More intense; • Different in character ( e.g. stabbing vs. ache); • Experienced in a different part of the body; and/or • Brought on by activity that previously did not cause the symptom.
> Page 51

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 注意：既往已存在的慢性病症不属于不良事件（AE），因此无需记录。

### NCT04210986·条目 32：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 9

- 条目ID：`wref_translation_item_5e401897bc962d9a42194107`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_2:regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> An AE or suspected adverse reaction is considered “serious” if, in the view of either the Principal Investigator, it results in any of the following outcomes:
> • Death; • A life-threatening adverse event; • Hospitalization; • Disability or permanent damage; • Congenital anomaly/birth defect; • Other serious events that may jeopardize the patient and may require medical or surgical intervention (treatment) to prevent one of the other outcomes. An AE or suspected adverse reaction is considered “life-threatening” if, (in the view of the Principal Investigator) its occurrence places the patient or subject at immediate risk of death. It does not include an AE or suspected adverse reaction that, had it occurred in a more severe form, might have caused death. Serious and/or unexpected adverse event(s) may present as either a local or systemic response, or both, which may present as an anaphylactic response associated with generalized urticaria, shortness of breath, or respiratory or circulatory arrest. Subjects will be instructed to contact the study site immediately if a systemic reaction occurs between scheduled study visits. Subjects may be assessed initially over the phone and may be asked to return to the study site for an additional visit to assess the reaction.
> Page 55

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • 死亡； • 危及生命的不良事件； • 住院治疗； • 残疾或永久性损伤； • 先天性异常/出生缺陷； • 其他可能危及患者健康并需要药物或手术干预方可避免上述不良后果的严重事件。若某不良事件或疑似不良反应的发生会使患者即刻面临死亡风险（以主要研究者的判断为准），则该不良事件即被视为“危及生命的”。但若某不良事件或疑似不良反应即便以更严重的形式出现也未必导致死亡，则不属于此类。严重及/或非预期的不良事件可表现为局部反应、全身反应或两者兼有，例如伴随全身性荨麻疹的过敏性休克、呼吸急促甚至呼吸或循环衰竭。若在预定的研究随访期间出现全身性反应，受试者须立即联系研究中心；研究人员可先通过电话对情况进行初步评估，随后可能要求受试者再次前往研究中心以进一步检查。

### NCT04210986·条目 33：Unlabelled section (safety) (safety) · 11

- 条目ID：`wref_translation_item_615f1fb66b57c7d0e28f1ae1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Time frame : within 3 months of Visit 1 • Visit length : 3-4 hours • Vital signs, medication information, and any adverse events that occurred since the last visit will be collected. • A pregnancy test will be performed for all pre-menopausal female participants. • The following procedures and tests will be performed: ▪ Medication instructions; ▪ Magnetic resonance imaging (MRI) scan; ▪ Functional performance testing; ▪ Physical exam; ▪ Muscle strength testing; ▪ Video-motion analysis. • Note that the blood test and knee x-ray may be performed at this visit if it was not done at visit 1. • Some of the screening procedures may need to be repeated for accuracy, fidelity, and/or safety.
> Page 89
> • Vail Health Pharmacy will be responsible for dispensing the Fisetin or placebo capsules. Fisetin or placebo capsules will be given to you in a bottle with a set of instructions. • After completing the study tests for this visit, you will be given Fisetin or placebo capsules as treatment. You will be instructed to take capsules while at the study site and the next day (10-15 capsules per day, amount based on body weight). You will be instructed to take the capsules for 2 cycles of treatment:
> o Cycle 1: 2 days on (days 1 and 2), followed by 28 days off (day 30). o Cycle 2: 2 days on (days 31 and 32). o Treatment will occur over the course of approximately 5 weeks. • All capsules must be taken within 60 minutes after the first capsule is consumed. • At Visit 4, please return any remaining capsules in the bottle. These extra capsules will be counted and discarded at your next on-site visit. • You will be given a drug diary/schedule to log each dose you take during the 2 treatment cycles. • A member of the clinical team will contact you via phone call three times while you are schedu
> …（中略）…
> m/study will not cover the costs of any follow-up consultations or actions. If you are not interested in receiving this information, please do not consent to participate in this study.
> Page 101
> XVI. Who should I contact if I have questions about the research? Contact the researchers at 970-476-1100:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • Vail Health药房将负责发放非瑟酮或安慰剂胶囊。这些胶囊会连同使用说明一同装入药瓶中提供给您。• 完成本次访视的各项研究检查后，您将开始服用非瑟酮或安慰剂胶囊进行治疗。工作人员会指导您在研究中心及次日按时服药（每日剂量为10至15粒，具体数量视体重而定）。您需连续完成2个治疗周期： o 第1周期：服药2天（即第1和第2日），随后停药28天（至第30日）。 o 第2周期：服药2天（即第31和第32日）。 o 整个治疗过程约持续5周。• 所有胶囊必须在您服下第一粒后的60分钟内全部服用完毕。• 在第4次访视时，请您将药瓶中剩余的胶囊一并交回。这些多余的胶囊会在您下次到研究中心时经清点后予以废弃处理。• 我们将向您提供用药记录本/日程表，以便详细记载您在2个治疗周期内每次的服药情况。

### NCT04210986·条目 34：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 7

- 条目ID：`wref_translation_item_68ceeb44aee008cc30345c29`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_2:numeric_tokens_changed`）
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Patient Reported Outcomes (PROs): (Visits 1, 2, 4, 5, 6)
> All PROs may be completed either on paper documents or by online questionnaire administration conducted via formsite (Vroman Systems, Inc.). Patients may complete questionnaires on a variety of electronic devices (personal computer, mobile phone, tablet). PRO data to be collected include: Augmented Numerical Rating Scale (NRS) (visit 2): At baseline then once every 3 days during FIRST 6 weeks of study medication treatment then once a week for an ADDITIONAL 6 weeks. IKDC, Lysholm, TEGNER, WOMAC and SF-12 (visit 2, visits 4, 5, and 6 and remote assessments at 3- and 18-months post completion of medication).
> Page 46
> The Numerical Rating Scale is a simple 0-10 self-reported severity of pain scale, (zero being no pain and 10 being the worst pain imaginable). This tool has been validated to provide excellent test-retest reliability in assessing knee pain associated with OA 31 . The Steadman Philippon Research Institute has added several stand-alone questions that are administered with the questionnaire. Only the validated portion, the simple NRS will be used to screen patients. In follow-up, each question will be analyzed individually. There is no composite score. A sample can be found in Appendix C, Section 22.3 of this document.
> The Lysholm knee scale is a condition-specific outcome measure that was originally designed to assess ligament injuries of the knee. It has been tested to provide excellent construct validity and overall acceptable psychometric performance for outcomes assessment of various chondral disorders of the knee. It is recommended that this tool be administered with additional psychometric measurements 32,33 . The TEGNER Activity Scale is a numerical scale ranging from 0 to 10. Each value indicates th
> …（中略）…
> n left/right sides (5 min). As is standard practice when using the HUMAC NORM system, padded straps will be used on the participant's torso and legs in order to isolate the lower leg movements and reduce the contribution of other muscles. All measurements will be normalized to % body weight.
> Page 50

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 所有患者报告结局（PRO）问卷均可通过纸质表格填写，也可借助Formsite平台（Vroman Systems, Inc.公司开发）在线完成。患者可在各类电子设备上填写问卷，包括个人电脑、手机及平板电脑等。需采集的患者报告结局数据如下：增强型数值评分量表（NRS）（第2次访视）：于基线时填写一次，随后在研究用药治疗的前6周内每隔3天填写一次；再接下来的6周则每周填写一次。此外还需采集IKDC量表、Lysholm评分表、TEGNER活动分级量表、WOMAC膝关节功能评估量表以及SF-12健康调查简表的相关数据（第2、4、5及6次访视时填写，并在用药结束后3个月与18个月时进行远程评估）。

### NCT04210986·条目 35：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_71a820d69b6194b167101473`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 10 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_10:unit_sequence_changed`）

**【原文段落】**（英文原文）

> determine if inclusion/exclusion criteria are met; 16. Randomization.
> Patients who have met all eligibility criteria will be assigned, 1:1 via block randomization, to one of the two blinded study groups. Visit 2 (Baseline) (Within 3 months of Visit 1) Some procedures performed in this visit may be performed in Visit 1 provided that Informed Consent has been signed.
> 1. Urine pregnancy test for Women of Child Bearing Potential (WOCBP) 2. Quantitative MRI; 3. Kinematic movement; 4. Assessment of muscle strength, isokinetic dynamometry; 5. Functional performance testing.
> Page 18
> After randomization is performed, a Study Team member will then inform the Vail Hospital pharmacist of the subject’s assigned randomization code the study medication will be obtained. The subject will take the first dose of study medication at the clinic. Subjects will be instructed to self-medicate for day 2 followed by 28 days off. They will be instructed to begin a second course of treatment for two consecutive days (days 31 and 32). Subjects will be reminded at Visit 3 in-person and over the phone 2-4 days prior to the last dosing of study medication about their upcoming dosing. If applicable, they will also be reminded to withhold current medications as instructed by the PI. A Medication Log recording medication administration will be provided to the subject with instructions to complete during the period of administration. Subject Follow-up: All adverse events and protocol deviations will be assessed at each follow-up visit. Visit 3: Two Weeks after first dose of Fisetin or Placebo (+/- 2 days) All subjects will return to the study site 2-weeks from the subject's last dose of Fisetin or placebo. The following procedures will be performed: 1. Blood Analysis Visit 4: Two Weeks from the Subject's Last Dose of Fisetin or Placebo (+/- 10 days) All subjects will return to the study site 2-weeks from the subject's last dose of Fisetin or placebo. The following procedures will be performed:
> 1. Vital signs; 2. Medical and surgical history; 3. Physical exam with ROM of target limb; 4. Blood analysis;
> Page 19
> 5. Medications; 6. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER,

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 完成随机分组后，研究团队成员将把分配给受试者的随机代码告知Vail医院的药师，以便受试者领取试验用药。该受试者将在诊所内服用第一剂研究药物。随后将指导受试者在第2天自行用药，之后停药28天；接着再连续两天（即第31和32天）开始第二个疗程的治疗。在受试者最后一次服用研究药物前2至4天，研究人员会在第3次访视时当面提醒其即将到来的用药安排，同时也会通过电话进行提示。若适用，还会提醒受试者按照主要研究者（PI）的指示暂停服用当前所用药物。研究方会向每位受试者提供一份记录用药情况的日志，并指导其在整个服药期间如实填写。 受试者随访：每次随访时均需评估所有不良事件及方案偏离情况。第3次访视时间定为：受试者服用非瑟酮或安慰剂最后一剂后两周左右（前后浮动不超过2天）。届时所有受试者均需返回研究中心，需实施的检查与操作如下：

### NCT04210986·条目 36：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_76ed75a6e71faf82ceb7b72d`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 10 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_10:unit_sequence_changed`）

**【原文段落】**（英文原文）

> determine if inclusion/exclusion criteria are met; 16. Randomization.
> Patients who have met all eligibility criteria will be assigned, 1:1 via block randomization, to one of the two blinded study groups. Visit 2 (Baseline) (Within 3 months of Visit 1) Some procedures performed in this visit may be performed in Visit 1 provided that Informed Consent has been signed.
> 1. Urine pregnancy test for Women of Child Bearing Potential (WOCBP) 2. Quantitative MRI; 3. Kinematic movement; 4. Assessment of muscle strength, isokinetic dynamometry; 5. Functional performance testing.
> Page 18
> After randomization is performed, a Study Team member will then inform the Vail Hospital pharmacist of the subject’s assigned randomization code the study medication will be obtained. The subject will take the first dose of study medication at the clinic. Subjects will be instructed to self-medicate for day 2 followed by 28 days off. They will be instructed to begin a second course of treatment for two consecutive days (days 31 and 32). Subjects will be reminded at Visit 3 in-person and over the phone 2-4 days prior to the last dosing of study medication about their upcoming dosing. If applicable, they will also be reminded to withhold current medications as instructed by the PI. A Medication Log recording medication administration will be provided to the subject with instructions to complete during the period of administration. Subject Follow-up: All adverse events and protocol deviations will be assessed at each follow-up visit. Visit 3: Two Weeks after first dose of Fisetin or Placebo (+/- 2 days) All subjects will return to the study site 2-weeks from the subject's last dose of Fisetin or placebo. The following procedures will be performed: 1. Blood Analysis Visit 4: Two Weeks from the Subject's Last Dose of Fisetin or Placebo (+/- 10 days) All subjects will return to the study site 2-weeks from the subject's last dose of Fisetin or placebo. The following procedures will be performed:
> 1. Vital signs; 2. Medical and surgical history; 3. Physical exam with ROM of target limb; 4. Blood analysis;
> Page 19
> 5. Medications; 6. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER,

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 完成随机分组后，研究团队成员将把分配给受试者的随机代码告知Vail医院的药师，以便受试者领取试验用药。该受试者将在诊所内服用第一剂研究药物。随后将指导受试者在第2天自行用药，之后停药28天；接着再连续两天（即第31和32天）开始第二个疗程的治疗。在受试者最后一次服用研究药物前2至4天，研究人员会在第3次访视时当面提醒其即将到来的用药安排，同时也会通过电话进行提示。若适用，还会提醒受试者按照主要研究者（PI）的指示暂停服用当前所用药物。研究方会向每位受试者提供一份记录用药情况的日志，并指导其在整个服药期间如实填写。 受试者随访：每次随访时均需评估所有不良事件及方案偏离情况。第3次访视时间定为：受试者服用非瑟酮或安慰剂最后一剂后两周左右（前后浮动不超过2天）。届时所有受试者均需返回研究中心，需实施的检查与操作如下：

### NCT04210986·条目 37：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_790b526b3f5fe70f844655a5`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 10 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_10:unit_sequence_changed`）

**【原文段落】**（英文原文）

> determine if inclusion/exclusion criteria are met; 16. Randomization.
> Patients who have met all eligibility criteria will be assigned, 1:1 via block randomization, to one of the two blinded study groups. Visit 2 (Baseline) (Within 3 months of Visit 1) Some procedures performed in this visit may be performed in Visit 1 provided that Informed Consent has been signed.
> 1. Urine pregnancy test for Women of Child Bearing Potential (WOCBP) 2. Quantitative MRI; 3. Kinematic movement; 4. Assessment of muscle strength, isokinetic dynamometry; 5. Functional performance testing.
> Page 18
> After randomization is performed, a Study Team member will then inform the Vail Hospital pharmacist of the subject’s assigned randomization code the study medication will be obtained. The subject will take the first dose of study medication at the clinic. Subjects will be instructed to self-medicate for day 2 followed by 28 days off. They will be instructed to begin a second course of treatment for two consecutive days (days 31 and 32). Subjects will be reminded at Visit 3 in-person and over the phone 2-4 days prior to the last dosing of study medication about their upcoming dosing. If applicable, they will also be reminded to withhold current medications as instructed by the PI. A Medication Log recording medication administration will be provided to the subject with instructions to complete during the period of administration. Subject Follow-up: All adverse events and protocol deviations will be assessed at each follow-up visit. Visit 3: Two Weeks after first dose of Fisetin or Placebo (+/- 2 days) All subjects will return to the study site 2-weeks from the subject's last dose of Fisetin or placebo. The following procedures will be performed: 1. Blood Analysis Visit 4: Two Weeks from the Subject's Last Dose of Fisetin or Placebo (+/- 10 days) All subjects will return to the study site 2-weeks from the subject's last dose of Fisetin or placebo. The following procedures will be performed:
> 1. Vital signs; 2. Medical and surgical history; 3. Physical exam with ROM of target limb; 4. Blood analysis;
> Page 19
> 5. Medications; 6. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER,

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 完成随机分组后，研究团队成员将把分配给受试者的随机代码告知Vail医院的药师，以便受试者领取试验用药。该受试者将在诊所内服用第一剂研究药物。随后将指导受试者在第2天自行用药，之后停药28天；接着再连续两天（即第31和32天）开始第二个疗程的治疗。在受试者最后一次服用研究药物前2至4天，研究人员会在第3次访视时当面提醒其即将到来的用药安排，同时也会通过电话进行提示。若适用，还会提醒受试者按照主要研究者（PI）的指示暂停服用当前所用药物。研究方会向每位受试者提供一份记录用药情况的日志，并指导其在整个服药期间如实填写。 受试者随访：每次随访时均需评估所有不良事件及方案偏离情况。第3次访视时间定为：受试者服用非瑟酮或安慰剂最后一剂后两周左右（前后浮动不超过2天）。届时所有受试者均需返回研究中心，需实施的检查与操作如下：

### NCT04210986·条目 38：Unlabelled section (safety) (safety) · 8

- 条目ID：`wref_translation_item_7cbfcf02cd466e52e9af7dda`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_2:controlled_term_missing:participant`）

**【原文段落】**（英文原文）

> The subject’s Private Health Information could be accidentally breached during the research process. Many system wide safety guards are in place to prevent this occurrence, including: Subject de-Identification, Badge-access, locked offices; controlled access to research offices and documents, password protected work stations and password complexity enforced; state-of-the-art and promptly updated firewall to block external web traffic; end-to-end encryption on all connections, automatic email encryption system for all outbound (off TSC server) email, Electronically secure online questionnaire access.
> Risk Analysis
> The Study Team will perform regular review of cumulative adverse events and will modify mitigation strategy as necessary. Baseline risk analysis is shown in Table 13.11 below. It is intended that risks with higher overall risk score will be subject to greater and more frequent scrutiny and discussion of mitigation. As the study progresses, modifications to this analysis will be fully document and retained. Table 13.11 Risk Analysis
> | Risk | Likelihood of Occurrence 1= not likely 2= possible 3= very likely | Potential Impact on Subject Safety 1=little 2= moderate 3= severe | Detectability 1= high 2= moderate 3= low | Overall Risk Score (Hierarchy of assessment and follow-up) (3-9) |
> Page 60
> | Associated with FIS Administration | 2 | 3 | 2 | 7 |
> | Associated with Placebo Administration | 1 | 1 | 3 | 5 |
> | Associated with MRI | 2 | 1 | 1 | 4 |
> | Associated With PRO Questionnaires | 2 | 1 | 1 | 4 |
> | Associated With Physical Exam | 2 | 1 | 1 | 4 |
> | Associated With Blood Draw | 2 | 2 | 1 | 5 |
> | Associated With Isokinetic Muscle Strength Testing | 2 | 1 | 1 | 4 |
> | Associated with Functional Performance Testing | 2 | 1 | 1 | 4 |
> | Associated With Motion Capture | 2
> …（中略）…
> ay remove a subject from the study if:
> 1. A subject demonstrates poor compliance with study protocol; 2. There is concurrent illness or required medical treatment that interferes with study assessments; 3. The Principal Investigator determines that the subject’s health, safety or welfare is at risk.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 风险分析：研究团队将定期审查累积发生的各类不良事件，并根据需要调整相应的风险控制措施。基线风险分析结果见下表13.11所示。总体风险评估得分较高的风险项将受到更为严密的监测，并需针对其制定更多且更频繁的风险控制措施。随着研究推进，相关风险分析结果的任何调整均会予以完整记录并妥善保存。表13.11 风险分析

### NCT04210986·条目 39：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 11

- 条目ID：`wref_translation_item_7f35ee72fb572a55e7858e51`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）

**【原文段落】**（英文原文）

> Whenever applicable, assessment of endpoints that are measured at serial time points will be analyzed using methods that account for this repeated measure structure. Listwise deletion in response to missing data points and categorization/dichotomization of continuous measurements will be avoided to every extent possible. Summary statistics will be reported as group medians with quartiles or extrema. Meanwhile estimates calculated for statistical inference will be reported with (1-α)% confidence intervals. Model fit and satisfactorily meeting model assumptions will be assessed for all multivariable regression and linear mixed-effects models using residual analysis. The Statistical Computing Language R will be used to produce all analyses and plots.
> Endpoints
> 15.5.1 Primary Endpoint The safety of FIS administration is the primary endpoint of this study. All adverse events will be compared by category of description incidence, relatedness to treatment, severity, duration and expectedness. The occurrence of non-serious and serious and unexpected adverse events will be compared between treatment groups. Bivariate analysis will be performed between group and each safety variable of interest independently. When comparing the two treatment groups, dichotomous (yes/no) endpoints will be assessed for association using Fisher’s exact test. Adverse events and symptoms that may occur multiple times in a single subject will be analyzed as count variables, and group differences will be assessed using simple Poisson regression or simple negative binomial regression. This is a small Phase I/II trial in which to assess safety, thus we will report all safety data thoroughly and aim to liberally identify potential side-effects and risks that may warrant close study in future, larger trials
> …（中略）…
> ow aspirate concentrate) or a surgical intervention (e.g. microfracture or total joint replacement), they will be removed from the study. Cox proportional hazards regression will be performed to compare the hazard rate of conversion to each of these two treatment categories between treatment groups.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 将在研究药物末次给药后第2周，以及用药开始后第6个月、12个月和18个月时，对IKDC评分、WOMAC量表得分、Tegner活动能力分级以及Lysholm患者报告结局指标进行测量。在每个时间点，均将采用ANCOVA分析方法，并以该受试者基线时的PROM数值作为协变量。在用于评估这些经验证的PROM指标的4个术后时间点中，将采用Holm-Bonferroni法对各量表的整体第一类错误率加以控制，确保其不高于0.05。由于不同PROM指标之间通常存在高度相关性，因此不会针对这些指标另行实施多重性校正。

### NCT04210986·条目 40：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 16

- 条目ID：`wref_translation_item_7fffe8732c1b14cf47386f65`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 5 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_5:negation_signal_missing`）

**【原文段落】**（英文原文）

> II. Conflict of Interest If you are currently receiving care at The Steadman Clinic, your health care provider may be an investigator on this research protocol, and as an investigator, is interested in both your clinical welfare and in the conduct of this study. Before entering this study or at any time during the research, you may ask for a second opinion about your care from a clinician who is not associated with this project. You are not obligated to participate in any research project offered by your clinician. Your participation in this research study is voluntary, and you do not have to participate. The decision to not participate will not affect your clinical care now or in the future. Neither the study doctors nor any members of the research team have any financial relationships with any manufacturer or supplier of Fisetin. Johnny Huard, PhD is the Principal Investigator on the contract of all four of our studies funded by the Department of Defense (DOD), including this one. While Dr. Huard is the lead PhD scientist on the four DOD-funded studies, Thos Evans, MD, a physician, is the principal investigator of the present study due to its clinical nature. ProofPoint Biologics (PPB) is an operating division of the Steadman Clinic that may draw and prepare your blood for analysis. Some of Dr. Huard’s compensation is covered by PPB. Dr. Thos Evans is the medical director and part owner of PPB. Dr. Raymond Kim is a part owner of PPB. However, their financial interest in and/or part ownership of PPB will not affect the research procedures or outcomes of this study.
> Page 86
> III. Why am I being asked to participate in this research? You have been asked to participate in the research because you have a painful joint condition called knee osteoarthritis.
> Approximately 100 
> …（中略）…
> FDA to study Fisetin as a treatment for patients with knee pain due to osteoarthritis and for this reason, Fisetin is referred to as an investigational drug in this consent form. You will be asked to take Fisetin or placebo capsules for 2 cycles of treatment over the course of approximately 5 weeks:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 预计约有100名受试者将参与由斯蒂德曼诊所与斯蒂德曼·菲利波恩研究所共同开展的此项联合研究项目。即便您同意参与本研究并签署了知情同意书，研究医生仍有可能判定您不符合入组条件。符合以下条件的受试者方可参与本研究：

### NCT04210986·条目 41：12.0 Study Management of Adverse Events (safety)

- 条目ID：`wref_translation_item_825057058eb2db28501e7926`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_4:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> 12.0 Study Management of Adverse Events
> Definition An adverse event (AE) is any untoward medical occurrence in a subject administered a Study Medication and which does not necessarily have a causal relationship with this treatment. An AE can therefore be any unfavorable and unintended sign (including an abnormal laboratory finding), symptom, or disease temporally associated with the use of whether or not related to the Study Medication (ICH E2A II/A/1, 21 CFR 312.32).
> All pre-existing medical conditions will be recorded on the medical history study document. Starting with the administration of the Study Medication any new experience that was not present at baseline or worsening of an event present at baseline in intensity or frequency, is considered an adverse event.
> Note: Unchanged, chronic conditions are NOT adverse events and should not be recorded.
> It is recognized that subjects will exhibit (throughout follow-up) symptoms of the underlying disease process of that fluctuates in severity and duration.
> Adverse events will include those occurrences, which when compared to before treatment meets any of the following criteria:
> • Represent a new event or escalation of an event; • Require a new escalation in treatment; • Lasts longer; • Experienced more frequently; • More intense; • Different in character ( e.g. stabbing vs. ache); • Experienced in a different part of the body; and/or • Brought on by activity that previously did not cause the symptom.
> Page 51

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 注意：既往已存在的慢性病症不属于不良事件（AE），因此无需记录。

### NCT04210986·条目 42：Unlabelled section (safety) (safety) · 4

- 条目ID：`wref_translation_item_82b7b47252fe9d5fa8fd3ba3`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> At 6- and 12-months post first dose (Visits 5 and 6) subjects will be evaluated at the study site. A review of concomitant medications, vital signs, and a physical exam with ROM will be performed. All adverse events and protocol deviations will be documented. A blood draw will be performed to measure senescent cells by T-Cell assay and by senescence biomarker assay. Further blood analyses will be performed. A quantitative MRI, lower-extremity kinematics testing with video motion analysis, isokinetic dynamometry testing, and functional performance testing will be performed. adverse event and protocol deviation data will be collected.
> Blinding Blinding will be maintained through study follow-up until the last subject has been seen at 18- months and data has been analyzed. All study subjects and Study Team members responsible for subject evaluation, data management and analysis (including the Principal Investigator) will be blinded. In addition, any individual engaged by the Principal Investigator to provide radiographic, laboratory testing and and/or verification of data will be blinded to treatment. Those unblinded include the Group Allocation Manager (not a member of the Study Team) that will be responsible for maintaining group assignment. In addition, the pharmacist responsible for medication distribution (including their team) will maintain a similar log and need to be unblinded to distribute study medication accurately.
> Non-Prohibition of Additional/Alternative Procedures In the event that a subject feels that he/she is unresponsive to the Study Medication (Fisetin or placebo) and/or and is having difficulty managing knee pain, he/she will be free to receive a single corticosteroid intra-articular knee injection and still remain in the study. In addition, subjects will be free to seek alternative treatment at any time; however, this may necessitate withdraw from the study as further described in Section 14.3 of this protocol.
> Page 30

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 在首次给药后第6周及第12周（即访视5和访视6），受试者将在研究中心接受评估。届时将核查其合并用药情况、测量生命体征，并开展体格检查以及关节活动度检测。所有出现的不良事件与方案偏离均须予以记录。随后将采集血样，用于通过T细胞检测法及衰老生物标志物检测方法来测定体内衰老细胞的含量；此外还将开展其他血液分析项目。同时将实施定量MRI检查、结合视频运动分析的下肢运动学检测、等速肌力测定以及功能性表现测试。上述所有不良事件与方案偏离的相关数据均须予以收集记录。

### NCT04210986·条目 43：5.0 Introduction (objectives_endpoints)

- 条目ID：`wref_translation_item_832f55ab17551f4fa4684296`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：译文出现了原文没有的医学概念/限定（可能引入原文不包含的含义——请重点复核）（检查器代码 `unit_4:unsupported_medical_concept_added`）

**【原文段落】**（英文原文）

> In this randomized, double-blind, placebo-controlled clinical trial, we intend to measure and compare safety via the gathering of all adverse events and preliminary evidence of efficacy through recording of SASP, inflammatory biomarkers and senescent cells. In addition, magnetic resonance imaging (MRI) exams, self-reported outcomes, functional performance and other relevant clinical data will be gathered. Possible correlation among outcomes, both structural and non-structural, will be described. Each subject is to be followed for 18 months.
> Page 23
> Rationale Aging is associated with the accumulation of senescent cells, which have lost their ability to proliferate and resist apoptosis. Aging cells produce a SASP consisting of potent pro-inflammatory and stress inducing factors 2-5 . OA, along with a litany of other age-related pathologies, is associated with cellular senescence, which is thought to promote aging via the chronic induction of inflammation 2-6 . OA is a debilitating and costly joint disease that affects millions of individuals each year for which there are no available disease modifying therapies 7,8 . Several studies have shown that spontaneous age-associated and post-traumatic OA (PTOA) is characterized by an increase in senescent chondrocytes within the joint capsule 9-13 that is thought to promote early inflammation and OA pathogenesis. Importantly, it was found that injection of senescent cells into the joint capsule of healthy mice could alone induce OA-like conditions in mice including severe cartilage degeneration, erosion of femoral condyles, subchondral bone structure alteration, osteophyte formation, and meniscal damage 14 . Inversely, other groups have shown that local clearance of senescent cells genetically within the intra-articular space sig
> …（中略）…
> by T-Cell assay and by senescence biomarker assay. Further blood analyses will be performed. At 6-, 12- and 18-months post first dose of Study Medication, subjects will be asked to complete the augmented NRS, IKDC, Lysholm, TEGNER, WOMAC and SF-12 remotely, either electronically or on paper.
> Page 29

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 相反，其他研究团队已证实：在关节腔内通过基因手段清除衰老细胞可显著减轻损伤诱发的OA发生，并营造出有利于组织再生的环境15。由此可见，细胞衰老与OA发病机制之间存在密切关联；这也使得清除衰老细胞的药物成为预防或治疗OA极具前景且创新的治疗手段。目前共有三项II期临床试验正在开展，旨在评估FIS在多种衰老相关疾病中的疗效：包括虚弱、炎症以及糖尿病与慢性肾脏病，对应的试验编号分别为NCT03430037、NCT03675724和NCT03325322。迄今为止，尚未有任何人体研究对清除衰老细胞药物用于膝关节OA治疗的情况进行过对试验药物的评估。

### NCT04210986·条目 44：Unlabelled section (safety) (safety) · 12

- 条目ID：`wref_translation_item_87a19af1e8d1ca44477d5d5d`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_3:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> • The research team for the research described in the Consent Form; • Vail Health Institutional Review Board (VH IRB); • Others who are required by law to review the quality and safety of the research, including U. S. government agencies such as The U.S. Food and Drug Administration (FDA) or the Department of Defense Office of Human Research Protections.
> Page 103
> Your patient information will be used and/or given to others for the following reasons:
> • To do the research • To study the results, and • To see if the research was done right If the results of this study are made public, information that identifies you will not be used. The researcher will use your patient information only in the ways that are described in the research consent form that you sign and as described in this HIPAA Authorization. You can ask questions about what the research team will do with your information and how they will protect it. The privacy laws do not always require the receiver of your information to keep your information confidential. After your information is given to an organization that is not subjected to the privacy laws, e.g., a research organization, there is a risk that it could be shared without your permission. How long will this authorization be valid? This permission for the researchers to obtain your patient information:
> • Ends when the research is complete and any required monitoring of the study is finished. Cancelling your permission: You may change your mind at any time. To take back your permission, you must send your written request to:
> Kate Wilmouth Steadman Philippon Research Institute 181 W. Meadow Dr. Suite 1000 Vail, CO 81657 If you take back your permission, the research team may still keep and use any patient information about you that they already have. But they can’t obtain more health information about you for this research unless it is required by a federal agency that is monitoring the research.
> Page 104

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 美国食品药品监督管理局（FDA）或国防部人类研究保护办公室等美国政府机构。

### NCT04210986·条目 45：Unlabelled section (eligibility) (eligibility) · 5

- 条目ID：`wref_translation_item_a2ffab1810a64c0e31b54e9b`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 11 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_11:negation_signal_missing`）

**【原文段落】**（英文原文）

> In addition, FIS has been demonstrated to have inhibitory activity of cytochrome P450, and to have adverse interaction with caffeine, tobacco/nicotine consumption for which we have established exclusion criteria. These are listed in detail in Section 9.1.2 of this protocol. In addition, a list of possible drug interactions with FIS are provided in Section 22.4 , Appendix D of this document.
> Risk Associated with Placebo Administration
> If results of this study reveal that administration of FIS improves OA symptoms and/or joint structure, subjects randomized to placebo may miss these benefit(s).
> Page 57
> All subjects will be fully informed that they have only a 50% chance of being randomized to receive FIS. In addition, subjects will be told that the advantages of receiving FIS in the treatment of OA in humans are unknown.
> Associated with MRI
> The MRI scan involves exposure to loud noise and positioning in a small space. Subjects may feel claustrophobic, fatigued or nauseated especially if they are uncomfortable with tight spaces. The MRI scan does not involve the use of x-rays or injectable dyes. There are no known reports of increased cancer or birth defects associated with this procedure. The MRI scan exposes the subject to high magnetic fields, which can be dangerous for those with pacemakers and some metal implants. All subjects will be carefully screened for potential contraindications for MRI. Subjects will be provided with hearing protection and may listen to their choice of streamed music for comfort. MRI-compatible padding and/or blankets may be used as requested for subject comfort. Subjects will be provided with a ‘squeeze ball’ activated microphone to allow communication with the MRI technologists so that they can notify the technologist of any problems or the d
> …（中略）…
> of general fatigue or discomfort, slight risk of fall, additional knee pain from performing the tests, muscle soreness, shortness of breath and dizziness. To mitigate this, the staff conducting the tests will assist with the procedures and apply protections.
> Associated with Breach of Confidentiality

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 该操作存在引发疼痛和/或不适的潜在风险。对膝关节进行触诊或使用力度较小的手法施力时，可能使受试者产生轻度至中度的不适感；具体程度取决于其主观感受及膝关节的实际状况。我们将尽力确保这种不适的程度不超过受试者日常活动（如步行、上下楼梯及穿鞋等）时所经历的不适程度。仅由经验丰富且经过专业培训的临床医师实施该项检查；若受试者表示不适，则将对检查方法作出相应调整。

### NCT04210986·条目 46：Unlabelled section (safety) (safety) · 11

- 条目ID：`wref_translation_item_a3a94db32e750f2bb4a373e1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Time frame : within 3 months of Visit 1 • Visit length : 3-4 hours • Vital signs, medication information, and any adverse events that occurred since the last visit will be collected. • A pregnancy test will be performed for all pre-menopausal female participants. • The following procedures and tests will be performed: ▪ Medication instructions; ▪ Magnetic resonance imaging (MRI) scan; ▪ Functional performance testing; ▪ Physical exam; ▪ Muscle strength testing; ▪ Video-motion analysis. • Note that the blood test and knee x-ray may be performed at this visit if it was not done at visit 1. • Some of the screening procedures may need to be repeated for accuracy, fidelity, and/or safety.
> Page 89
> • Vail Health Pharmacy will be responsible for dispensing the Fisetin or placebo capsules. Fisetin or placebo capsules will be given to you in a bottle with a set of instructions. • After completing the study tests for this visit, you will be given Fisetin or placebo capsules as treatment. You will be instructed to take capsules while at the study site and the next day (10-15 capsules per day, amount based on body weight). You will be instructed to take the capsules for 2 cycles of treatment:
> o Cycle 1: 2 days on (days 1 and 2), followed by 28 days off (day 30). o Cycle 2: 2 days on (days 31 and 32). o Treatment will occur over the course of approximately 5 weeks. • All capsules must be taken within 60 minutes after the first capsule is consumed. • At Visit 4, please return any remaining capsules in the bottle. These extra capsules will be counted and discarded at your next on-site visit. • You will be given a drug diary/schedule to log each dose you take during the 2 treatment cycles. • A member of the clinical team will contact you via phone call three times while you are schedu
> …（中略）…
> m/study will not cover the costs of any follow-up consultations or actions. If you are not interested in receiving this information, please do not consent to participate in this study.
> Page 101
> XVI. Who should I contact if I have questions about the research? Contact the researchers at 970-476-1100:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • Vail Health药房将负责发放非瑟酮或安慰剂胶囊。这些胶囊会连同使用说明一同装入药瓶中提供给您。• 完成本次访视的各项研究检查后，您将开始服用非瑟酮或安慰剂胶囊进行治疗。工作人员会指导您在研究中心及次日按时服药（每日剂量为10至15粒，具体数量视体重而定）。您需连续完成2个治疗周期： o 第1周期：服药2天（即第1和第2日），随后停药28天（至第30日）。 o 第2周期：服药2天（即第31和第32日）。 o 整个治疗过程约持续5周。• 所有胶囊必须在您服下第一粒后的60分钟内全部服用完毕。• 在第4次访视时，请您将药瓶中剩余的胶囊一并交回。这些多余的胶囊会在您下次到研究中心时经清点后予以废弃处理。• 我们将向您提供用药记录本/日程表，以便详细记载您在2个治疗周期内每次的服药情况。

### NCT04210986·条目 47：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_a8078d4411bffdde9b020455`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> To evaluate as compared to placebo: The safety of administering Fisetin in subjects with osteoarthritis (OA) of the knee. Secondary Objectives To evaluate as compared to placebo:
> 1. Reduction of pro-inflammatory and cartilage degenerating SASP markers;
> 2. Improvement in physical function of the Study Knee;
> 3. Improvement in patient reported outcomes;
> 4. Improvement in the quality of articular cartilage in the Study Knee with quantitative
> magnetic resonance imaging (MRI);
> 5. Reduction in time to conversion to alternative treatment. Endpoints:
> Primary Endpoint: Occurrence of adverse events. Secondary Endpoints Statistically significant as compared to placebo:
> 1. Improvement in serum measures of inflammation and cartilage degenerating senescence
> associated secretory phenotype (SASP) markers; 2. Improvement in lower-extremity kinematic testing with video-motion analysis;
> isokinetic dynamometry testing, functional performance testing, range of motion (ROM);
> Page 14
> | (EOSa). While the Sponsor will be u Investigator and the subject will rem | 3. Improvement in patient reported outcomes (PROs), including: IKDC, Lysholm, TEGNER, WOMAC and SF-12 surveys; 4. Improvement in the quality of articular cartilage in the knee joint as measured by T2 and T1rho relaxometry; 5. Days from day one of Study Medication intake to conversion to alternative therapy. Additionally, we will review and discuss any possible correlation among secondary endpoint results. nblinded to study treatment after the Phase A analysis, the ain blinded. SS OF BLINDING BLIND/PARTICIPANT CODE ied physician who is an Investigator in this study in the ich knowledge of the identity of the study medication is |
> | 10.6.2 EVALUATION OF SUCCE Not applicable to this study. | |
> | 10.6.3 BREAKING THE STUDY The blind may be br
> …（中略）…
> sis; 13. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER,
> WOMAC and SF-12; 14. A radiograph of the target knee will be performed to confirm the presence of Kellgren-
> Lawrence grade II-IV OA; 15. The patients’ medical record will be reviewed, and the subject will be interviewed to

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 3. 患者报告结局（PROs）的改善情况，具体指标包括：IKDC、Lysholm评分表、TEGNER量表、WOMAC评估及SF-12调查问卷；4. 通过T2与T1rho弛豫测量法测定的膝关节软骨质量改善情况；5. 从开始服用研究药物之日起至改用其他治疗方案所需的天数。此外，我们还将对各项次要终点结果之间可能存在的关联性予以评估与探讨。在A阶段分析完成后，所有受试者均处于盲态；CODE为BLIND/PARTICIPANT CODE。本研究中的研究者均为对研究药物具体成分完全不知情的医师，即处于BLIND状态。

### NCT04210986·条目 48：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_a8ef5e38d476bf19b8d54627`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> To evaluate as compared to placebo: The safety of administering Fisetin in subjects with osteoarthritis (OA) of the knee. Secondary Objectives To evaluate as compared to placebo:
> 1. Reduction of pro-inflammatory and cartilage degenerating SASP markers;
> 2. Improvement in physical function of the Study Knee;
> 3. Improvement in patient reported outcomes;
> 4. Improvement in the quality of articular cartilage in the Study Knee with quantitative
> magnetic resonance imaging (MRI);
> 5. Reduction in time to conversion to alternative treatment. Endpoints:
> Primary Endpoint: Occurrence of adverse events. Secondary Endpoints Statistically significant as compared to placebo:
> 1. Improvement in serum measures of inflammation and cartilage degenerating senescence
> associated secretory phenotype (SASP) markers; 2. Improvement in lower-extremity kinematic testing with video-motion analysis;
> isokinetic dynamometry testing, functional performance testing, range of motion (ROM);
> Page 14
> | (EOSa). While the Sponsor will be u Investigator and the subject will rem | 3. Improvement in patient reported outcomes (PROs), including: IKDC, Lysholm, TEGNER, WOMAC and SF-12 surveys; 4. Improvement in the quality of articular cartilage in the knee joint as measured by T2 and T1rho relaxometry; 5. Days from day one of Study Medication intake to conversion to alternative therapy. Additionally, we will review and discuss any possible correlation among secondary endpoint results. nblinded to study treatment after the Phase A analysis, the ain blinded. SS OF BLINDING BLIND/PARTICIPANT CODE ied physician who is an Investigator in this study in the ich knowledge of the identity of the study medication is |
> | 10.6.2 EVALUATION OF SUCCE Not applicable to this study. | |
> | 10.6.3 BREAKING THE STUDY The blind may be br
> …（中略）…
> sis; 13. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER,
> WOMAC and SF-12; 14. A radiograph of the target knee will be performed to confirm the presence of Kellgren-
> Lawrence grade II-IV OA; 15. The patients’ medical record will be reviewed, and the subject will be interviewed to

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 3. 患者报告结局（PROs）的改善情况，具体指标包括：IKDC、Lysholm评分表、TEGNER量表、WOMAC评估及SF-12调查问卷；4. 通过T2与T1rho弛豫测量法测定的膝关节软骨质量改善情况；5. 从开始服用研究药物之日起至改用其他治疗方案所需的天数。此外，我们还将对各项次要终点结果之间可能存在的关联性予以评估与探讨。在A阶段分析完成后，所有受试者均处于盲态；CODE为BLIND/PARTICIPANT CODE。本研究中的研究者均为对研究药物具体成分完全不知情的医师，即处于BLIND状态。

### NCT04210986·条目 49：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_ab4a316ec0fcae3a2772fd41`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Patient Reported Outcomes (PROs): (Visits 1, 2, 4, 5, 6) ...............................46
> Imaging Assessment of OA .............................................................................48 11.6.1 Radiographic Assessment: (Visit 1).....................................................48 11.6.2 Quantitative Magnetic Resonance Imaging (MRI): (Visits 2, 5, 6) .....48
> Functional Performance Testing: (Visits 2, 5, 6) .............................................49
> Lower-Extremity Kinematics, Video-Motion Analysis: (Visits 2, 5, 6)...................................................................................................50

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 骨关节炎的影像学评估 .............................................................................48
> 11.6.1 X线影像评估：（第1次访视）.....................................................48
> 11.6.2 定量磁共振成像（MRI）：（第2、5、6次访视） .....48

### NCT04210986·条目 50：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 12

- 条目ID：`wref_translation_item_ae0f8c98564250b7e9747e3a`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> Whenever possible, statistical methods such as linear mixed-effects modeling which naturally handle missing data will be utilized. Missing data will be investigated carefully by the biostatistician, the study manager and the clinical staff to assess its probable cause, and whether missing not at random (MNAR, missingness dependent on outcome), missing at random (MAR, missingness not dependent
> Page 67
> on outcome but can be fully accounted for by other non-missing covariates) or missing completely at random (MCAR, missingness independent of both observed variables and unobserved parameters of interest) is most likely. If any missing data patterns are determined to be MNAR, this observance will be reported narratively in the final report(s) and publication(s), and no imputation methods will be pursued. Little’s test will be used to assess whether missing values are missing completely at random (MCAR) For methods that require complete data or listwise deletion (e.g. PCA), and where missing data is determined to be reasonably missing at random (MAR or MCAR), multiple imputation using predictive mean matching will be employed.
> Data Preparation and Maintenance of Blinding

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 在条件允许的情况下，将采用线性混合效应模型等能够自然处理缺失数据的统计学方法。生物统计学家、研究管理员及临床工作人员将对缺失数据予以细致分析，以判定其可能成因以及属于非随机性缺失（MNAR，即缺失情况与结局相关）还是随机性缺失（MAR）。

### NCT04210986·条目 51：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 7

- 条目ID：`wref_translation_item_af38327646e05410b0ce385e`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_2:numeric_tokens_changed`）
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Patient Reported Outcomes (PROs): (Visits 1, 2, 4, 5, 6)
> All PROs may be completed either on paper documents or by online questionnaire administration conducted via formsite (Vroman Systems, Inc.). Patients may complete questionnaires on a variety of electronic devices (personal computer, mobile phone, tablet). PRO data to be collected include: Augmented Numerical Rating Scale (NRS) (visit 2): At baseline then once every 3 days during FIRST 6 weeks of study medication treatment then once a week for an ADDITIONAL 6 weeks. IKDC, Lysholm, TEGNER, WOMAC and SF-12 (visit 2, visits 4, 5, and 6 and remote assessments at 3- and 18-months post completion of medication).
> Page 46
> The Numerical Rating Scale is a simple 0-10 self-reported severity of pain scale, (zero being no pain and 10 being the worst pain imaginable). This tool has been validated to provide excellent test-retest reliability in assessing knee pain associated with OA 31 . The Steadman Philippon Research Institute has added several stand-alone questions that are administered with the questionnaire. Only the validated portion, the simple NRS will be used to screen patients. In follow-up, each question will be analyzed individually. There is no composite score. A sample can be found in Appendix C, Section 22.3 of this document.
> The Lysholm knee scale is a condition-specific outcome measure that was originally designed to assess ligament injuries of the knee. It has been tested to provide excellent construct validity and overall acceptable psychometric performance for outcomes assessment of various chondral disorders of the knee. It is recommended that this tool be administered with additional psychometric measurements 32,33 . The TEGNER Activity Scale is a numerical scale ranging from 0 to 10. Each value indicates th
> …（中略）…
> n left/right sides (5 min). As is standard practice when using the HUMAC NORM system, padded straps will be used on the participant's torso and legs in order to isolate the lower leg movements and reduce the contribution of other muscles. All measurements will be normalized to % body weight.
> Page 50

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 所有患者报告结局（PRO）问卷均可通过纸质表格填写，也可借助Formsite平台（Vroman Systems, Inc.公司开发）在线完成。患者可在各类电子设备上填写问卷，包括个人电脑、手机及平板电脑等。需采集的患者报告结局数据如下：增强型数值评分量表（NRS）（第2次访视）：于基线时填写一次，随后在研究用药治疗的前6周内每隔3天填写一次；再接下来的6周则每周填写一次。此外还需采集IKDC量表、Lysholm评分表、TEGNER活动分级量表、WOMAC膝关节功能评估量表以及SF-12健康调查简表的相关数据（第2、4、5及6次访视时填写，并在用药结束后3个月与18个月时进行远程评估）。

### NCT04210986·条目 52：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 15

- 条目ID：`wref_translation_item_b04b669a6b36903b5246b652`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_2:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 32 Briggs, T. W. et al. Histological evaluation of chondral defects after autologous chondrocyte implantation of the knee. J Bone Joint Surg Br 85 , 1077-1083 (2003). 33 Lysholm, J. & Wiklander, J. Injuries in runners. Am J Sports Med 15 , 168-171, doi:10.1177/036354658701500213 (1987). 34 Bellamy, N., Buchanan, W. W., Goldsmith, C. H., Campbell, J. & Stitt, L. W. Validation study of WOMAC: a health status instrument for measuring clinically important patient relevant outcomes to antirheumatic drug therapy in patients with osteoarthritis of the hip or knee. J Rheumatol 15 , 1833-1840 (1988). 35 Galanos, A. N., Fillenbaum, G. G., Cohen, H. J. & Burchett, B. M. The comprehensive assessment of community dwelling elderly: why functional status is not enough. Aging (Milano) 6 , 343-352 (1994). 36 Ware, J., Jr., Kosinski, M. & Keller, S. D. A 12-Item Short-Form Health Survey: construction of scales and preliminary tests of reliability and validity. Med Care 34 , 220-233 (1996). 37 Braun, H. J. & Gold, G. E. Diagnosis of osteoarthritis: imaging. Bone 51 , 278-288, doi:10.1016/j.bone.2011.11.019 (2012). 38 Moffet, H. et al. Effectiveness of intensive rehabilitation on functional ability and quality of life after first total knee arthroplasty: A single-blind randomized controlled trial. Arch Phys Med Rehabil 85 , 546-556 (2004). 39 Parent, E. & Moffet, H. Comparative responsiveness of locomotor tests and questionnaires used to follow early recovery after total knee arthroplasty. Arch Phys Med Rehabil 83 , 70-80 (2002). 40 Parent, E. & Moffet, H. Preoperative predictors of locomotor ability two months after total knee arthroplasty for severe osteoarthritis. Arthritis Rheum 49 , 36-50, doi:10.1002/art.10906 (2003). 41 Montgomery, P. S. & Gardner, A. W. The clinical utility of a si
> …（中略）…
> . Can elderly patients who have had a hip fracture perform moderate- to high-intensity exercise at home? Physical Therapy 85 , 727-739 (2005). 55 Osternig, L. R. Isokinetic dynamometry: implications for muscle testing and rehabilitation. Exerc Sport Sci Rev 14 , 45-80 (1986).
> Page 83
> 22.0 Appendices

**【中文译文段落】**（原始模型输出（未经对齐组装））

> W.等人。膝关节自体软骨细胞移植术后软骨缺损的组织学评估。《英国骨与关节外科杂志》85卷，第1077至1083页（2003年）。33 Lysholm, J.与Wiklander。

### NCT04210986·条目 53：Unlabelled section (eligibility) (eligibility) · 3

- 条目ID：`wref_translation_item_b0ece92411ba6499bc0bbf45`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 24 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_24:negation_signal_missing`）

**【原文段落】**（英文原文）

> 9.0 Study Population Male and female patients who present to the clinical practices of the Principal Investigator or Sub-Investigators will be enrolled if they meet all eligibility criteria. Subjects from the community who self-identify in response to a flyer, newspaper advertisement, or website will be enrolled if they meet all eligibility criteria.
> Enrollment Criteria
> 9.1.1 Inclusion Criteria Subjects will be included if all of the following criteria are met:
> 1. Are male or female, ages 40-80; 2. Are willing to comply with all study related procedures and assessments; 3. Are ambulatory as defined by ability to complete functional performance testing; 4. Radiographic evidence of Kellgren-Lawrence grade II-IV osteoarthritis in one or both knees; 5. Scores 4-10 on the Numerical Rating Scale (NRS) for pain; 6. Stable dose of screening/baseline medications for at least 2 months prior to the anticipated date of study drug dosing.
> 9.1.2 Exclusion Criteria Subjects will be excluded if any of the following criteria are met:
> 1. Females who are nursing, pregnant or planning to become pregnant during the duration of study drug dosing; 2. Males who do not wish to abstain from sex or use contraceptive protection during study drug dosing and for 2 weeks after the
> last dose; 3. Subjects who do not have the capacity to consent themselves; 4. Subjects who are unable to tolerate oral medication; 5. Subjects having previously undergone any of the following treatments in the stated time window:
> a. Surgery on the Study Knee in the past 6 months; b. Partial or complete joint replacement in the study knee. Partial or complete joint replacement in the
> contralateral knee is acceptable as long as the surgery was performed at least 6 months prior to enrollment and the operative knee is asymptoma
> …（中略）…
> tal involvement or any history of systemic
> inflammatory arthritis; e. Patients with type 1 or 2 diabetes (HbA1c > 6.5%) and/or taking medications that affect insulin levels,
> including: Metformin (within the last week), Glucocorticoids (within the last month), Acarbose (within the last week);
> Page 38

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 过去8周内曾使用过阿片类镇痛药，且不愿意在整个研究期间停用此类药物的受试者；

### NCT04210986·条目 54：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 12

- 条目ID：`wref_translation_item_b1669c792816d4f4d2d9d478`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> Whenever possible, statistical methods such as linear mixed-effects modeling which naturally handle missing data will be utilized. Missing data will be investigated carefully by the biostatistician, the study manager and the clinical staff to assess its probable cause, and whether missing not at random (MNAR, missingness dependent on outcome), missing at random (MAR, missingness not dependent
> Page 67
> on outcome but can be fully accounted for by other non-missing covariates) or missing completely at random (MCAR, missingness independent of both observed variables and unobserved parameters of interest) is most likely. If any missing data patterns are determined to be MNAR, this observance will be reported narratively in the final report(s) and publication(s), and no imputation methods will be pursued. Little’s test will be used to assess whether missing values are missing completely at random (MCAR) For methods that require complete data or listwise deletion (e.g. PCA), and where missing data is determined to be reasonably missing at random (MAR or MCAR), multiple imputation using predictive mean matching will be employed.
> Data Preparation and Maintenance of Blinding

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 在条件允许的情况下，将采用线性混合效应模型等能够自然处理缺失数据的统计学方法。生物统计学家、研究管理员及临床工作人员将对缺失数据予以细致分析，以判定其可能成因以及属于非随机性缺失（MNAR，即缺失情况与结局相关）还是随机性缺失（MAR）。

### NCT04210986·条目 55：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 16

- 条目ID：`wref_translation_item_b68aa5291cf155f35fe1bffe`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 5 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_5:negation_signal_missing`）

**【原文段落】**（英文原文）

> II. Conflict of Interest If you are currently receiving care at The Steadman Clinic, your health care provider may be an investigator on this research protocol, and as an investigator, is interested in both your clinical welfare and in the conduct of this study. Before entering this study or at any time during the research, you may ask for a second opinion about your care from a clinician who is not associated with this project. You are not obligated to participate in any research project offered by your clinician. Your participation in this research study is voluntary, and you do not have to participate. The decision to not participate will not affect your clinical care now or in the future. Neither the study doctors nor any members of the research team have any financial relationships with any manufacturer or supplier of Fisetin. Johnny Huard, PhD is the Principal Investigator on the contract of all four of our studies funded by the Department of Defense (DOD), including this one. While Dr. Huard is the lead PhD scientist on the four DOD-funded studies, Thos Evans, MD, a physician, is the principal investigator of the present study due to its clinical nature. ProofPoint Biologics (PPB) is an operating division of the Steadman Clinic that may draw and prepare your blood for analysis. Some of Dr. Huard’s compensation is covered by PPB. Dr. Thos Evans is the medical director and part owner of PPB. Dr. Raymond Kim is a part owner of PPB. However, their financial interest in and/or part ownership of PPB will not affect the research procedures or outcomes of this study.
> Page 86
> III. Why am I being asked to participate in this research? You have been asked to participate in the research because you have a painful joint condition called knee osteoarthritis.
> Approximately 100 
> …（中略）…
> FDA to study Fisetin as a treatment for patients with knee pain due to osteoarthritis and for this reason, Fisetin is referred to as an investigational drug in this consent form. You will be asked to take Fisetin or placebo capsules for 2 cycles of treatment over the course of approximately 5 weeks:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 预计约有100名受试者将参与由斯蒂德曼诊所与斯蒂德曼·菲利波恩研究所共同开展的此项联合研究项目。即便您同意参与本研究并签署了知情同意书，研究医生仍有可能判定您不符合入组条件。符合以下条件的受试者方可参与本研究：

### NCT04210986·条目 56：Unlabelled section (eligibility) (eligibility) · 3

- 条目ID：`wref_translation_item_b90b88a4b10ec912a7db21c1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 24 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_24:negation_signal_missing`）

**【原文段落】**（英文原文）

> 9.0 Study Population Male and female patients who present to the clinical practices of the Principal Investigator or Sub-Investigators will be enrolled if they meet all eligibility criteria. Subjects from the community who self-identify in response to a flyer, newspaper advertisement, or website will be enrolled if they meet all eligibility criteria.
> Enrollment Criteria
> 9.1.1 Inclusion Criteria Subjects will be included if all of the following criteria are met:
> 1. Are male or female, ages 40-80; 2. Are willing to comply with all study related procedures and assessments; 3. Are ambulatory as defined by ability to complete functional performance testing; 4. Radiographic evidence of Kellgren-Lawrence grade II-IV osteoarthritis in one or both knees; 5. Scores 4-10 on the Numerical Rating Scale (NRS) for pain; 6. Stable dose of screening/baseline medications for at least 2 months prior to the anticipated date of study drug dosing.
> 9.1.2 Exclusion Criteria Subjects will be excluded if any of the following criteria are met:
> 1. Females who are nursing, pregnant or planning to become pregnant during the duration of study drug dosing; 2. Males who do not wish to abstain from sex or use contraceptive protection during study drug dosing and for 2 weeks after the
> last dose; 3. Subjects who do not have the capacity to consent themselves; 4. Subjects who are unable to tolerate oral medication; 5. Subjects having previously undergone any of the following treatments in the stated time window:
> a. Surgery on the Study Knee in the past 6 months; b. Partial or complete joint replacement in the study knee. Partial or complete joint replacement in the
> contralateral knee is acceptable as long as the surgery was performed at least 6 months prior to enrollment and the operative knee is asymptoma
> …（中略）…
> tal involvement or any history of systemic
> inflammatory arthritis; e. Patients with type 1 or 2 diabetes (HbA1c > 6.5%) and/or taking medications that affect insulin levels,
> including: Metformin (within the last week), Glucocorticoids (within the last month), Acarbose (within the last week);
> Page 38

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 过去8周内曾使用过阿片类镇痛药，且不愿意在整个研究期间停用此类药物的受试者；

### NCT04210986·条目 57：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 4

- 条目ID：`wref_translation_item_c164903e4a43911bf6162667`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> To evaluate as compared to placebo: The safety of administering Fisetin in subjects with osteoarthritis (OA) of the knee. Secondary Objectives To evaluate as compared to placebo:
> 1. Reduction of pro-inflammatory and cartilage degenerating SASP markers;
> 2. Improvement in physical function of the Study Knee;
> 3. Improvement in patient reported outcomes;
> 4. Improvement in the quality of articular cartilage in the Study Knee with quantitative
> magnetic resonance imaging (MRI);
> 5. Reduction in time to conversion to alternative treatment. Endpoints:
> Primary Endpoint: Occurrence of adverse events. Secondary Endpoints Statistically significant as compared to placebo:
> 1. Improvement in serum measures of inflammation and cartilage degenerating senescence
> associated secretory phenotype (SASP) markers; 2. Improvement in lower-extremity kinematic testing with video-motion analysis;
> isokinetic dynamometry testing, functional performance testing, range of motion (ROM);
> Page 14
> | (EOSa). While the Sponsor will be u Investigator and the subject will rem | 3. Improvement in patient reported outcomes (PROs), including: IKDC, Lysholm, TEGNER, WOMAC and SF-12 surveys; 4. Improvement in the quality of articular cartilage in the knee joint as measured by T2 and T1rho relaxometry; 5. Days from day one of Study Medication intake to conversion to alternative therapy. Additionally, we will review and discuss any possible correlation among secondary endpoint results. nblinded to study treatment after the Phase A analysis, the ain blinded. SS OF BLINDING BLIND/PARTICIPANT CODE ied physician who is an Investigator in this study in the ich knowledge of the identity of the study medication is |
> | 10.6.2 EVALUATION OF SUCCE Not applicable to this study. | |
> | 10.6.3 BREAKING THE STUDY The blind may be br
> …（中略）…
> sis; 13. Completion of augmented PROs, including: NRS, IKDC, Lysholm, TEGNER,
> WOMAC and SF-12; 14. A radiograph of the target knee will be performed to confirm the presence of Kellgren-
> Lawrence grade II-IV OA; 15. The patients’ medical record will be reviewed, and the subject will be interviewed to

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 3. 患者报告结局（PROs）的改善情况，具体指标包括：IKDC、Lysholm评分表、TEGNER量表、WOMAC评估及SF-12调查问卷；4. 通过T2与T1rho弛豫测量法测定的膝关节软骨质量改善情况；5. 从开始服用研究药物之日起至改用其他治疗方案所需的天数。此外，我们还将对各项次要终点结果之间可能存在的关联性予以评估与探讨。在A阶段分析完成后，所有受试者均处于盲态；CODE为BLIND/PARTICIPANT CODE。本研究中的研究者均为对研究药物具体成分完全不知情的医师，即处于BLIND状态。

### NCT04210986·条目 58：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 11

- 条目ID：`wref_translation_item_d99af567d98c0e6689b8531a`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）

**【原文段落】**（英文原文）

> Whenever applicable, assessment of endpoints that are measured at serial time points will be analyzed using methods that account for this repeated measure structure. Listwise deletion in response to missing data points and categorization/dichotomization of continuous measurements will be avoided to every extent possible. Summary statistics will be reported as group medians with quartiles or extrema. Meanwhile estimates calculated for statistical inference will be reported with (1-α)% confidence intervals. Model fit and satisfactorily meeting model assumptions will be assessed for all multivariable regression and linear mixed-effects models using residual analysis. The Statistical Computing Language R will be used to produce all analyses and plots.
> Endpoints
> 15.5.1 Primary Endpoint The safety of FIS administration is the primary endpoint of this study. All adverse events will be compared by category of description incidence, relatedness to treatment, severity, duration and expectedness. The occurrence of non-serious and serious and unexpected adverse events will be compared between treatment groups. Bivariate analysis will be performed between group and each safety variable of interest independently. When comparing the two treatment groups, dichotomous (yes/no) endpoints will be assessed for association using Fisher’s exact test. Adverse events and symptoms that may occur multiple times in a single subject will be analyzed as count variables, and group differences will be assessed using simple Poisson regression or simple negative binomial regression. This is a small Phase I/II trial in which to assess safety, thus we will report all safety data thoroughly and aim to liberally identify potential side-effects and risks that may warrant close study in future, larger trials
> …（中略）…
> ow aspirate concentrate) or a surgical intervention (e.g. microfracture or total joint replacement), they will be removed from the study. Cox proportional hazards regression will be performed to compare the hazard rate of conversion to each of these two treatment categories between treatment groups.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 将在研究药物末次给药后第2周，以及用药开始后第6个月、12个月和18个月时，对IKDC评分、WOMAC量表得分、Tegner活动能力分级以及Lysholm患者报告结局指标进行测量。在每个时间点，均将采用ANCOVA分析方法，并以该受试者基线时的PROM数值作为协变量。在用于评估这些经验证的PROM指标的4个术后时间点中，将采用Holm-Bonferroni法对各量表的整体第一类错误率加以控制，确保其不高于0.05。由于不同PROM指标之间通常存在高度相关性，因此不会针对这些指标另行实施多重性校正。

### NCT04210986·条目 59：Unlabelled section (safety) (safety) · 6

- 条目ID：`wref_translation_item_dbed6aa048b9dafe411ce419`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Physical exams are to include height, weight, ROM of the target limb, and general wellness check up to examine any adverse events.
> Range of Motion (ROM): (Visits 1, 4, 5, 6)
> Both the active and passive range of motion should be assessed. The normal knee extension is between 0 to 10 degrees. The normal knee flexion is between 130 to 150 degrees. Any pain, abnormal movement, or crepitus of the patella will be noted.
> Blood Laboratory Analysis: (Visits 1, 3, 4, 5, 6)
> Analyses in Column A will be performed by a CLIA-Certified Laboratory: Vail Health Laboratory. Analyses in Column B will be performed at the Steadman-Philippon Research Institute (SPRI)
> Page 44
> Column A Column B
> CBC w/Diff CMP CRP
> ESR Creatine Kinase Uric Acid
> Vit D (25 hydroxy)
> Hb A1c
> T-Cell Assay: Peripheral blood CD3+ T cell assay for P16INK4a: 30 mL blood will be collected using EDTA tubes to measure p16 INK positive lymphocyte population in the peripheral blood- a biomarker of senescence and chronological aging. T-Cells will be enriched from whole blood using a commercial kit following manufactures instructions (RosetteSep, Stem Cell Technologies #15021). P16 expression will be measured by RT-PCR using Taq-man primer- probe system from enriched T-cells. C 12 FDG Detection of Senescent Cells in Flow: A portion of enriched T-cells collected from 30 ml blood described above will be stained with C 12 FDG, a fluorescent marker to detect senescent cells using flow cytometry (Guava EasyCyte, Luminex). Biomarker Assessment for Senescent cells: Quantification of Growth Factor and Cytokine/Chemokine Composition: The whole blood sample will be pipetted to microcentrifuge tubes for Luminex® multiplex immunoassays (EMD Millipore Corp, Billerca, MA) that measure concentrations of growth factors, cytokines and chemokines
> …（中略）…
> lt-3, IFN- 𝛂 2, IFN-ɣ, IL-1 𝛂 , IL-1β, IL-1ra, IL-2, IL-3, IL-4, IL-5, IL-6, IL-7, IL-8, IL-9, IL-10, IL-12 (p40 and p70), IL-13, IL- 15, IL-17A, IP-10, MCP-1, MCP-3, MDC, MIP-1 𝛂 , MIP-1β, PDGF- AA, PDGF-AB/BB, RANTES, TGF- 𝛂 , TNF- 𝛂 , TNF-β, VEGF, MMP (1,2,3,7,9,10,12,13), TGF-β (isoforms 1,2,3).

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 体格检查内容应包含身高、体重、目标肢体的活动度范围以及全身健康状况评估，以便发现任何不良事件。

### NCT04210986·条目 60：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 11

- 条目ID：`wref_translation_item_e228abebf87ef5f3bbbec67a`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_2:unit_sequence_changed`）

**【原文段落】**（英文原文）

> Whenever applicable, assessment of endpoints that are measured at serial time points will be analyzed using methods that account for this repeated measure structure. Listwise deletion in response to missing data points and categorization/dichotomization of continuous measurements will be avoided to every extent possible. Summary statistics will be reported as group medians with quartiles or extrema. Meanwhile estimates calculated for statistical inference will be reported with (1-α)% confidence intervals. Model fit and satisfactorily meeting model assumptions will be assessed for all multivariable regression and linear mixed-effects models using residual analysis. The Statistical Computing Language R will be used to produce all analyses and plots.
> Endpoints
> 15.5.1 Primary Endpoint The safety of FIS administration is the primary endpoint of this study. All adverse events will be compared by category of description incidence, relatedness to treatment, severity, duration and expectedness. The occurrence of non-serious and serious and unexpected adverse events will be compared between treatment groups. Bivariate analysis will be performed between group and each safety variable of interest independently. When comparing the two treatment groups, dichotomous (yes/no) endpoints will be assessed for association using Fisher’s exact test. Adverse events and symptoms that may occur multiple times in a single subject will be analyzed as count variables, and group differences will be assessed using simple Poisson regression or simple negative binomial regression. This is a small Phase I/II trial in which to assess safety, thus we will report all safety data thoroughly and aim to liberally identify potential side-effects and risks that may warrant close study in future, larger trials
> …（中略）…
> ow aspirate concentrate) or a surgical intervention (e.g. microfracture or total joint replacement), they will be removed from the study. Cox proportional hazards regression will be performed to compare the hazard rate of conversion to each of these two treatment categories between treatment groups.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 将在研究药物末次给药后第2周，以及用药开始后第6个月、12个月和18个月时，对IKDC评分、WOMAC量表得分、Tegner活动能力分级以及Lysholm患者报告结局指标进行测量。在每个时间点，均将采用ANCOVA分析方法，并以该受试者基线时的PROM数值作为协变量。在用于评估这些经验证的PROM指标的4个术后时间点中，将采用Holm-Bonferroni法对各量表的整体第一类错误率加以控制，确保其不高于0.05。由于不同PROM指标之间通常存在高度相关性，因此不会针对这些指标另行实施多重性校正。

### NCT04210986·条目 61：Unlabelled section (safety) (safety) · 8

- 条目ID：`wref_translation_item_e22d184061030654efe4b35f`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_2:controlled_term_missing:participant`）

**【原文段落】**（英文原文）

> The subject’s Private Health Information could be accidentally breached during the research process. Many system wide safety guards are in place to prevent this occurrence, including: Subject de-Identification, Badge-access, locked offices; controlled access to research offices and documents, password protected work stations and password complexity enforced; state-of-the-art and promptly updated firewall to block external web traffic; end-to-end encryption on all connections, automatic email encryption system for all outbound (off TSC server) email, Electronically secure online questionnaire access.
> Risk Analysis
> The Study Team will perform regular review of cumulative adverse events and will modify mitigation strategy as necessary. Baseline risk analysis is shown in Table 13.11 below. It is intended that risks with higher overall risk score will be subject to greater and more frequent scrutiny and discussion of mitigation. As the study progresses, modifications to this analysis will be fully document and retained. Table 13.11 Risk Analysis
> | Risk | Likelihood of Occurrence 1= not likely 2= possible 3= very likely | Potential Impact on Subject Safety 1=little 2= moderate 3= severe | Detectability 1= high 2= moderate 3= low | Overall Risk Score (Hierarchy of assessment and follow-up) (3-9) |
> Page 60
> | Associated with FIS Administration | 2 | 3 | 2 | 7 |
> | Associated with Placebo Administration | 1 | 1 | 3 | 5 |
> | Associated with MRI | 2 | 1 | 1 | 4 |
> | Associated With PRO Questionnaires | 2 | 1 | 1 | 4 |
> | Associated With Physical Exam | 2 | 1 | 1 | 4 |
> | Associated With Blood Draw | 2 | 2 | 1 | 5 |
> | Associated With Isokinetic Muscle Strength Testing | 2 | 1 | 1 | 4 |
> | Associated with Functional Performance Testing | 2 | 1 | 1 | 4 |
> | Associated With Motion Capture | 2
> …（中略）…
> ay remove a subject from the study if:
> 1. A subject demonstrates poor compliance with study protocol; 2. There is concurrent illness or required medical treatment that interferes with study assessments; 3. The Principal Investigator determines that the subject’s health, safety or welfare is at risk.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 风险分析：研究团队将定期审查累积发生的各类不良事件，并根据需要调整相应的风险控制措施。基线风险分析结果见下表13.11所示。总体风险评估得分较高的风险项将受到更为严密的监测，并需针对其制定更多且更频繁的风险控制措施。随着研究推进，相关风险分析结果的任何调整均会予以完整记录并妥善保存。表13.11 风险分析

### NCT04210986·条目 62：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_e9ab4bfe7871fe6d23d95307`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_2:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> Patient Reported Outcomes (PROs): (Visits 1, 2, 4, 5, 6) ...............................46
> Imaging Assessment of OA .............................................................................48 11.6.1 Radiographic Assessment: (Visit 1).....................................................48 11.6.2 Quantitative Magnetic Resonance Imaging (MRI): (Visits 2, 5, 6) .....48
> Functional Performance Testing: (Visits 2, 5, 6) .............................................49
> Lower-Extremity Kinematics, Video-Motion Analysis: (Visits 2, 5, 6)...................................................................................................50

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 骨关节炎的影像学评估 .............................................................................48
> 11.6.1 X线影像评估：（第1次访视）.....................................................48
> 11.6.2 定量磁共振成像（MRI）：（第2、5、6次访视） .....48

### NCT04210986·条目 63：Unlabelled section (safety) (safety) · 11

- 条目ID：`wref_translation_item_f0c01cf6fe74ebaa9ee32a24`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 3 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_3:unit_sequence_changed`）

**【原文段落】**（英文原文）

> • Time frame : within 3 months of Visit 1 • Visit length : 3-4 hours • Vital signs, medication information, and any adverse events that occurred since the last visit will be collected. • A pregnancy test will be performed for all pre-menopausal female participants. • The following procedures and tests will be performed: ▪ Medication instructions; ▪ Magnetic resonance imaging (MRI) scan; ▪ Functional performance testing; ▪ Physical exam; ▪ Muscle strength testing; ▪ Video-motion analysis. • Note that the blood test and knee x-ray may be performed at this visit if it was not done at visit 1. • Some of the screening procedures may need to be repeated for accuracy, fidelity, and/or safety.
> Page 89
> • Vail Health Pharmacy will be responsible for dispensing the Fisetin or placebo capsules. Fisetin or placebo capsules will be given to you in a bottle with a set of instructions. • After completing the study tests for this visit, you will be given Fisetin or placebo capsules as treatment. You will be instructed to take capsules while at the study site and the next day (10-15 capsules per day, amount based on body weight). You will be instructed to take the capsules for 2 cycles of treatment:
> o Cycle 1: 2 days on (days 1 and 2), followed by 28 days off (day 30). o Cycle 2: 2 days on (days 31 and 32). o Treatment will occur over the course of approximately 5 weeks. • All capsules must be taken within 60 minutes after the first capsule is consumed. • At Visit 4, please return any remaining capsules in the bottle. These extra capsules will be counted and discarded at your next on-site visit. • You will be given a drug diary/schedule to log each dose you take during the 2 treatment cycles. • A member of the clinical team will contact you via phone call three times while you are schedu
> …（中略）…
> m/study will not cover the costs of any follow-up consultations or actions. If you are not interested in receiving this information, please do not consent to participate in this study.
> Page 101
> XVI. Who should I contact if I have questions about the research? Contact the researchers at 970-476-1100:

**【中文译文段落】**（原始模型输出（未经对齐组装））

> • Vail Health药房将负责发放非瑟酮或安慰剂胶囊。这些胶囊会连同使用说明一同装入药瓶中提供给您。• 完成本次访视的各项研究检查后，您将开始服用非瑟酮或安慰剂胶囊进行治疗。工作人员会指导您在研究中心及次日按时服药（每日剂量为10至15粒，具体数量视体重而定）。您需连续完成2个治疗周期： o 第1周期：服药2天（即第1和第2日），随后停药28天（至第30日）。 o 第2周期：服药2天（即第31和第32日）。 o 整个治疗过程约持续5周。• 所有胶囊必须在您服下第一粒后的60分钟内全部服用完毕。• 在第4次访视时，请您将药瓶中剩余的胶囊一并交回。这些多余的胶囊会在您下次到研究中心时经清点后予以废弃处理。• 我们将向您提供用药记录本/日程表，以便详细记载您在2个治疗周期内每次的服药情况。

### NCT04210986·条目 64：Unlabelled section (eligibility) (eligibility) · 3

- 条目ID：`wref_translation_item_f34e6b7a2e3126489cd7904e`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 24 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_24:negation_signal_missing`）

**【原文段落】**（英文原文）

> 9.0 Study Population Male and female patients who present to the clinical practices of the Principal Investigator or Sub-Investigators will be enrolled if they meet all eligibility criteria. Subjects from the community who self-identify in response to a flyer, newspaper advertisement, or website will be enrolled if they meet all eligibility criteria.
> Enrollment Criteria
> 9.1.1 Inclusion Criteria Subjects will be included if all of the following criteria are met:
> 1. Are male or female, ages 40-80; 2. Are willing to comply with all study related procedures and assessments; 3. Are ambulatory as defined by ability to complete functional performance testing; 4. Radiographic evidence of Kellgren-Lawrence grade II-IV osteoarthritis in one or both knees; 5. Scores 4-10 on the Numerical Rating Scale (NRS) for pain; 6. Stable dose of screening/baseline medications for at least 2 months prior to the anticipated date of study drug dosing.
> 9.1.2 Exclusion Criteria Subjects will be excluded if any of the following criteria are met:
> 1. Females who are nursing, pregnant or planning to become pregnant during the duration of study drug dosing; 2. Males who do not wish to abstain from sex or use contraceptive protection during study drug dosing and for 2 weeks after the
> last dose; 3. Subjects who do not have the capacity to consent themselves; 4. Subjects who are unable to tolerate oral medication; 5. Subjects having previously undergone any of the following treatments in the stated time window:
> a. Surgery on the Study Knee in the past 6 months; b. Partial or complete joint replacement in the study knee. Partial or complete joint replacement in the
> contralateral knee is acceptable as long as the surgery was performed at least 6 months prior to enrollment and the operative knee is asymptoma
> …（中略）…
> tal involvement or any history of systemic
> inflammatory arthritis; e. Patients with type 1 or 2 diabetes (HbA1c > 6.5%) and/or taking medications that affect insulin levels,
> including: Metformin (within the last week), Glucocorticoids (within the last month), Acarbose (within the last week);
> Page 38

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 过去8周内曾使用过阿片类镇痛药，且不愿意在整个研究期间停用此类药物的受试者；

### NCT04210986·条目 65：Unlabelled section (eligibility) (eligibility) · 3

- 条目ID：`wref_translation_item_ff59fe56c6755216b12c15a4`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 24 单元（段）：（未知问题类型，原文样式的检查器代码）（检查器代码 `unit_24:negation_signal_missing`）

**【原文段落】**（英文原文）

> 9.0 Study Population Male and female patients who present to the clinical practices of the Principal Investigator or Sub-Investigators will be enrolled if they meet all eligibility criteria. Subjects from the community who self-identify in response to a flyer, newspaper advertisement, or website will be enrolled if they meet all eligibility criteria.
> Enrollment Criteria
> 9.1.1 Inclusion Criteria Subjects will be included if all of the following criteria are met:
> 1. Are male or female, ages 40-80; 2. Are willing to comply with all study related procedures and assessments; 3. Are ambulatory as defined by ability to complete functional performance testing; 4. Radiographic evidence of Kellgren-Lawrence grade II-IV osteoarthritis in one or both knees; 5. Scores 4-10 on the Numerical Rating Scale (NRS) for pain; 6. Stable dose of screening/baseline medications for at least 2 months prior to the anticipated date of study drug dosing.
> 9.1.2 Exclusion Criteria Subjects will be excluded if any of the following criteria are met:
> 1. Females who are nursing, pregnant or planning to become pregnant during the duration of study drug dosing; 2. Males who do not wish to abstain from sex or use contraceptive protection during study drug dosing and for 2 weeks after the
> last dose; 3. Subjects who do not have the capacity to consent themselves; 4. Subjects who are unable to tolerate oral medication; 5. Subjects having previously undergone any of the following treatments in the stated time window:
> a. Surgery on the Study Knee in the past 6 months; b. Partial or complete joint replacement in the study knee. Partial or complete joint replacement in the
> contralateral knee is acceptable as long as the surgery was performed at least 6 months prior to enrollment and the operative knee is asymptoma
> …（中略）…
> tal involvement or any history of systemic
> inflammatory arthritis; e. Patients with type 1 or 2 diabetes (HbA1c > 6.5%) and/or taking medications that affect insulin levels,
> including: Metformin (within the last week), Glucocorticoids (within the last month), Acarbose (within the last week);
> Page 38

**【中文译文段落】**（原始模型输出（未经对齐组装））

> b. 过去8周内曾使用过阿片类镇痛药，且不愿意在整个研究期间停用此类药物的受试者；

## 研究 NCT04886258（1 项待处置）

### NCT04886258·条目 1：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_91a262ce5d90a02ca7179fc4`（第 70 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> As wit h a n y i m m u ne -m o d ulati n g c o m p o u n d, t here is a t he oretical ris k of i m m u ne s yste m i m pair me nt, w hic h mi g ht i ncrease ris k of i nfecti o n i n treate d partici pa nts. H o we ver, D F V 8 9 0 is n ot e x pecte d t o elicit br oa d i m m u ne s u p pressi o n. M ore o ver, t he tar get N L R P 3 is n ot esse ntial f or healt h ( N L R P 3 deficie nt mice are ge nerall y healt h y). I n a 4 6-wee k G L P t o xic ol o g y st u d y i n c y n o m ol g us m o n ke ys, m ori b u n dit y was re p orte d i n f o ur of t hirtee n a ni mals recei vi n g t he hi g hest d ose of D F V 8 9 0 ( 1 5 0 f oll o we d b y 1 0 0 m g/ k g/ da y). T w o of t he a ni mals were e ut ha nize d d ue t o i nj uries ( n ot relate d t o D F V 8 9 0). I n t he ot her t w o m o n ke ys, a d verse cli nical fi n di n gs were see n wit h e vi de nce of j oi nt i nfla m mati o n (c o nsiste nt wit h a p ost -i nfecti o us reacti ve art hritis). T he ca use has n ot bee n deter mi ne d, a n d a p ossi ble relati o n t o D F V 8 9 0 ca n n ot be e xcl u de d. T hese fi n di n gs were n ot see n i n a pre vi o us 1 3 -wee k t o xic ol o g y m o n ke y st u d y, w hic h ha d hi g her s yste mic e x p os ures. T he ris k f or patie nts i n c urre ntl y o n g oi n g trials is c o nsi dere d l o w base d o n safety mar gi ns a n d/ or s h ort treat me nt d urati o n. T o miti gate p ote ntial ris ks of i m m u ne s u p pressi o n a n d i nfecti o n i n t his st u d y, e xcl usi o n criteria i ncl u de ot her i m m u ne s u p pressi ve treat me nts a d mi nistere d 2 8 da ys or 5 half-li ves, w hic he ver is l o n ger, pri or t o scree ni n g. Partici pa nts will als o be e xcl u de d wit h k n o w n or s us pecte d i m m u n o deficie nc y state or e vi de nce of acti ve 
> …（中略）…
>  nsi dere d a n I C E, a n d/ or i n w hic h treat me nt p olic y strate g y w o ul d be a p plie d t o all I C E (i.e., use all data as c ollecte d). T hese s u p ple me ntar y esti ma n ds will be s pecifie d i n t he S A P.
> 1 2. 5 A n al y si s of s e c o n d ar y e n d p oi nt s/ e sti m a n d s

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 与任何免疫调节类药物一样，理论上存在导致免疫系统功能受损的风险，这可能会增加接受治疗的受试者发生感染的可能性。不过预计DFV890不会引发广泛的免疫抑制作用。此外，其靶标NLRP3并非维持机体健康所必需（缺乏该蛋白的小鼠通常健康状况良好）。在一项为期46周的食蟹猴GLP毒理学研究中，接受最高剂量DFV890（先给予150毫克/千克/天、随后调整为100毫克/千克/天）的13只实验动物中，有4只出现濒死状态。其中2只因受伤被实施安乐死（该损伤与DFV890无关）。其余两只猴子则出现不良临床体征，并有关节炎症的相关证据（符合感染后反应性关节炎的特征）。目前尚未查明确切诱因，也无法排除其与DFV890存在关联的可能性。

## 研究 NCT05080660（36 项待处置）

### NCT05080660·条目 1：Unlabelled section (safety) (safety) · 3

- 条目ID：`wref_translation_item_040650ce6f3f5f9a662e1ab6`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 6 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_6:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> S af et y a nal yses ha ve bee n descri be d i n t he C P M P Master Pr ot oc ol. A d dit i on al I S A-s pecific safety a nal yses ma y be describe d i n t he I S A S A P.
> 9. 3. 4. Ot her A n al yses
> 9. 3. 4. 1. P h ar m ac o ki netic a n d P h ar m ac o d y n a mic A n al yses
> T he o bser ve d plas ma c o nce ntrati o ns f or L Y 3 5 2 6 3 1 8 will be re p orte d gra p hicall y a n d descri pt i vel y.
> P har mac o ki net ic m o deli n g a n d e x p os ure -res p o nse a nal yses of efficac y meas ures ma y be c o n d ucte d. If c o n d ucte d, t he a nal yses will be perf or me d usi n g p o p ulat i on a nal ysis s o ftware, N O N M E M ® , if data allo ws. T he versi o n of a n y s oft ware use d f or t he a nal ysis will be d oc u m e nte d, a n d t he pr o gra m will meet t he Lill y re q uire me nts of s oft ware vali dat i on. It i s p ossi ble t hat ot her vali date d, e q ui vale nt P K s oft ware pr o gra ms ma y be use d if a p pr o priate, warra nte d, a n d a p pr o ve d b y Gl o bal P K/ p har mac o d y na mic ma na ge me nt. Data ma y be p o ole d wi t h data fr o m ot her st u dies for a n i nte grate d P K a n d/ or P K/ p ha r mac o d y na mic a nal ysis.
> A li mite d n u m ber of pre-i de ntifie d i n di vi d uals i n de pe n de nt of t he st u d y t e a m ma y recei ve access t o u n bli n de d data, as s pecifie d i n t he u n bli n di n g pla n, pri or t o t he i nteri m or fi nal data base l oc k, i n or der t o i nitiate t he fi nal p o p ulat i on P K a n d/ or e x p os ure -res p o nse m o del de vel o p me nt pr ocesses. I nf or mati o n t hat ma y u n bli n d t he st u d y d uri n g t he a nal yses will n ot be re p orte d t o st u d y sit es or t he bli n de d st u d y tea m u ntil t he st u d y has bee n u n bli n de d.
> 9. 4. I nteri m A n 
> …（中略）…
>  change
> The prevailing consideration for making a change is ensuring the safety of study participants. Additional important considerations for making a change are compliance with Good Clinical Practice, enabling participants to continue safely in the study and maintaining the integrity of the study.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> LY3526318的实测血浆浓度将通过图表及文字描述的方式进行报告。

### NCT05080660·条目 2：8.2. Safety Assessments (safety)

- 条目ID：`wref_translation_item_07f7adb658a35bd08a972819`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 15 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_15:numeric_tokens_changed`）
  - 译文第 15 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_15:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 8.2. Safety Assessments
> Planned time points for all safety assessments are provided in the SoAs.
> 8.2.1. Physical Examinations
> Symptom directed physical examinations of skin, eyes, mouth, lungs, and gastrointestinal tract will be performed at each visit as described in the SoA. Any clinically significant abnormal physical examination findings will be reported as AEs.
> 8.2.2. Electrocardiograms
> Single 12-lead ECG will be obtained as outlined in the SoA using an ECG machine that automatically calculates the heart rate and measures PR, RR, QRS, QT, and QTcF intervals.
> 8.2.3. Clinical Safety Laboratory Tests
> See OA02 Section 10.1 (Appendix 1) for the list of clinical laboratory tests to be performed and to the SoA for the timing and frequency for ISA OA02.
> 8.3. Adverse Events, Serious Adverse Events, and Product Complaints
> See the CPMP Master Protocol for additional details.
> 8.4. Pharmacokinetics ● Blood samples will be collected for measurement of plasma concentrations of LY3526318 as specified in the SoA.
> ● A maximum of 3 samples may be collected at additional time points during the study if warranted and agreed upon between the investigator and the sponsor. The timing of sampling may be altered during the course of the study based on newly available data (e.g., to obtain data closer to the time of peak plasma concentrations) to ensure appropriate monitoring.
> ● Instructions for the collection and handling of biological samples will be provided by the sponsor. The actual date and time (24-hour clock time) of each sample will be recorded.
> ● The date and time (24-hour clock time) of LY3526318 administration prior to the PK sampling will be recorded i.e. the dose administered in the clinic at Visit 3 and the last at home dose prior to each of Visit 4, Visit 5, Visit 6, and Visi
> …（中略）…
> s met h o ds descri be d, a n d t he j ust ificati on f or ma ki n g t he c ha n ge, will be descri be d i n t he statist ical a nal ysis pl a n ( S A P) a n d t he cli nical st u d y re p ort. A d ditio nal e xpl orat o r y a nal yses of t he data will be c o n d ucte d as dee me d a p pr o priate.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> ● 这些样本将用于评估LY3526318的药代动力学特征。为测定LY3526318血浆浓度而采集的样本，也可用于对研究期间或研究后出现的各类问题所涉及的安全性或对试验药物的评估情况进行分析。

### NCT05080660·条目 3：8.2. Safety Assessments (safety)

- 条目ID：`wref_translation_item_0c29a1725ca7ceef147e1d1b`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 15 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_15:numeric_tokens_changed`）
  - 译文第 15 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_15:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 8.2. Safety Assessments
> Planned time points for all safety assessments are provided in the SoAs.
> 8.2.1. Physical Examinations
> Symptom directed physical examinations of skin, eyes, mouth, lungs, and gastrointestinal tract will be performed at each visit as described in the SoA. Any clinically significant abnormal physical examination findings will be reported as AEs.
> 8.2.2. Electrocardiograms
> Single 12-lead ECG will be obtained as outlined in the SoA using an ECG machine that automatically calculates the heart rate and measures PR, RR, QRS, QT, and QTcF intervals.
> 8.2.3. Clinical Safety Laboratory Tests
> See OA02 Section 10.1 (Appendix 1) for the list of clinical laboratory tests to be performed and to the SoA for the timing and frequency for ISA OA02.
> 8.3. Adverse Events, Serious Adverse Events, and Product Complaints
> See the CPMP Master Protocol for additional details.
> 8.4. Pharmacokinetics ● Blood samples will be collected for measurement of plasma concentrations of LY3526318 as specified in the SoA.
> ● A maximum of 3 samples may be collected at additional time points during the study if warranted and agreed upon between the investigator and the sponsor. The timing of sampling may be altered during the course of the study based on newly available data (e.g., to obtain data closer to the time of peak plasma concentrations) to ensure appropriate monitoring.
> ● Instructions for the collection and handling of biological samples will be provided by the sponsor. The actual date and time (24-hour clock time) of each sample will be recorded.
> ● The date and time (24-hour clock time) of LY3526318 administration prior to the PK sampling will be recorded i.e. the dose administered in the clinic at Visit 3 and the last at home dose prior to each of Visit 4, Visit 5, Visit 6, and Visi
> …（中略）…
> s met h o ds descri be d, a n d t he j ust ificati on f or ma ki n g t he c ha n ge, will be descri be d i n t he statist ical a nal ysis pl a n ( S A P) a n d t he cli nical st u d y re p ort. A d ditio nal e xpl orat o r y a nal yses of t he data will be c o n d ucte d as dee me d a p pr o priate.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> ● 这些样本将用于评估LY3526318的药代动力学特征。为测定LY3526318血浆浓度而采集的样本，也可用于对研究期间或研究后出现的各类问题所涉及的安全性或对试验药物的评估情况进行分析。

### NCT05080660·条目 4：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_17dde95faad148a03b14d548`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 5：8.2. Safety Assessments (safety)

- 条目ID：`wref_translation_item_18b3c73a2ab6c56ffe9e547c`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 15 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_15:numeric_tokens_changed`）
  - 译文第 15 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_15:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 8.2. Safety Assessments
> Planned time points for all safety assessments are provided in the SoAs.
> 8.2.1. Physical Examinations
> Symptom directed physical examinations of skin, eyes, mouth, lungs, and gastrointestinal tract will be performed at each visit as described in the SoA. Any clinically significant abnormal physical examination findings will be reported as AEs.
> 8.2.2. Electrocardiograms
> Single 12-lead ECG will be obtained as outlined in the SoA using an ECG machine that automatically calculates the heart rate and measures PR, RR, QRS, QT, and QTcF intervals.
> 8.2.3. Clinical Safety Laboratory Tests
> See OA02 Section 10.1 (Appendix 1) for the list of clinical laboratory tests to be performed and to the SoA for the timing and frequency for ISA OA02.
> 8.3. Adverse Events, Serious Adverse Events, and Product Complaints
> See the CPMP Master Protocol for additional details.
> 8.4. Pharmacokinetics ● Blood samples will be collected for measurement of plasma concentrations of LY3526318 as specified in the SoA.
> ● A maximum of 3 samples may be collected at additional time points during the study if warranted and agreed upon between the investigator and the sponsor. The timing of sampling may be altered during the course of the study based on newly available data (e.g., to obtain data closer to the time of peak plasma concentrations) to ensure appropriate monitoring.
> ● Instructions for the collection and handling of biological samples will be provided by the sponsor. The actual date and time (24-hour clock time) of each sample will be recorded.
> ● The date and time (24-hour clock time) of LY3526318 administration prior to the PK sampling will be recorded i.e. the dose administered in the clinic at Visit 3 and the last at home dose prior to each of Visit 4, Visit 5, Visit 6, and Visi
> …（中略）…
> s met h o ds descri be d, a n d t he j ust ificati on f or ma ki n g t he c ha n ge, will be descri be d i n t he statist ical a nal ysis pl a n ( S A P) a n d t he cli nical st u d y re p ort. A d ditio nal e xpl orat o r y a nal yses of t he data will be c o n d ucte d as dee me d a p pr o priate.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> ● 这些样本将用于评估LY3526318的药代动力学特征。为测定LY3526318血浆浓度而采集的样本，也可用于对研究期间或研究后出现的各类问题所涉及的安全性或对试验药物的评估情况进行分析。

### NCT05080660·条目 6：3. Objectives and Endpoints.........................................................................................17 (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_20283bf191dae5b11731a98f`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_4:numeric_tokens_changed`）
  - 译文第 4 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_4:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 6. Study Intervention(s) and Concomitant Therapy ...................................................22 6.1. Study Intervention(s) Administered ............................................................................22 6.2. Preparation, Handling, Storage, and Accountability....................................................22 6.3. Measures to Minimize Bias: Randomization and Blinding..........................................22 6.4. Study Intervention Compliance...................................................................................22 6.5. Treatment of Overdose ...............................................................................................22 6.6. Concomitant Therapy .................................................................................................23
> 7. Discontinuation of Study Intervention and Participant Discontinuation/Withdrawal....................................................................................24
> 8. Study Assessments and Procedures .........................................................................25 8.1. Efficacy Assessments .................................................................................................25 8.2. Safety Assessments ....................................................................................................25 8.2.1. Physical Examinations................................................................................................25 8.2.2. Electrocardiograms.....................................................................................................25 8.2.3. Clinical Safety Laboratory Tests.................................................................................25 8.3. Adverse Events, Serious Adverse Events, and Product Complaints .............
> …（中略）…
> ttee : Yes
> S af et y re vie ws are c o vere d b y t he Assess me nt C o m mittee c harter f or t he C hr o nic Pai n Master Pr ot oc ol .
> 1.2. Schema
> Abbreviations: PDEP = preliminary data entry period; V = visit. * Medication washout and PDEP begins. ** Randomization to either LY3526318 or placebo.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 8.5 药效动力学.....................................................................................................................26

### NCT05080660·条目 7：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_23f86901481854615d2dddc2`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 8：Unlabelled section (safety) (safety) · 5

- 条目ID：`wref_translation_item_252c6e64cad03a281d9269ec`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 13 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_13:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> data monitoring committee A data monitoring committee is a group of independent scientists who are appointed to monitor the safety and scientific integrity of a human research intervention, and to make recommendations to the sponsor regarding the stopping of a study for efficacy, or for harms, or for futility. The composition of the committee is dependent upon the scientific skills and knowledge required for monitoring the particular study.
> DSA disease-state addendum
> ECG electrocardiogram
> eGFR estimated glomerular filtration rate
> enroll The act of assigning a participant to a treatment. Participants who are enrolled in the study are those who have been assigned to a treatment.
> IB Investigator’s Brochure
> IC 50 half-maximal inhibitory concentration
> IMP Investigational Medicinal Product
> informed consent A process by which a participant voluntarily confirms his or her willingness to participate in a particular study, after having been informed of all aspects of the study that are relevant to the participant’s decision to participate. Informed consent is documented by means of a written, signed, and dated informed consent form.
> interim analysis An interim analysis is an analysis of clinical study data, separated into treatment groups, that is conducted before the final reporting database is created/locked.
> investigational product A pharmaceutical form of an active ingredient or placebo being tested or used as a reference in a clinical trial, including products already on the market when used or assembled (formulated or packaged) in a way different from the authorized form, or marketed products used for an unauthorized indication, or marketed products used to gain further information about the authorized form.
> ISA intervention-specific appendix
> NIMP noninvestigational medicin
> …（中略）…
> subject”: an individual who participates in a clinical trial, either as recipient of an investigational medicinal product or as a control
> PK pharmacokinetics
> PO by mouth
> PoC proof-of-concept
> OA osteoarthritis
> QD once daily
> QTc corrected QT interval
> SAD single ascending dose
> SAE serious adverse event

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 口服给药

### NCT05080660·条目 9：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_2668a25f9270675004fb1b81`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> T he p u r p ose of t his st u d y is t o test w het her L Y 3 5 2 6 3 1 8 is efficaci o us i n relie vi n g k nee pai n d ue t o O A. Data will be c ollecte d t o assess t he safety a n d t olera bilit y of L Y 3 5 2 6 3 1 8 i n t his st u d y p o p ul at i on. P har mac o ki net ic (P K ) pr o perties will als o be e x pl ore d . T he t otality of data fr o m t his pr o of -of c o nce pt ( P o C) stu d y will assess t he be nefit s a n d ris ks ass ociate d wit h L Y 3 5 2 6 3 1 8 a n d i nf or m decisi o ns f or t he cli nical de vel o p me nt of L Y 3 5 2 6 3 1 8.
> 2. 2. B ac k gr o u n d
> T he tra nsie nt rece pt or p ote ntial ( T R P ) io n c ha n nel fa mil y c o m pr ises a gr o u p of 2 8 n o nselecti ve catio n c ha n nels t hat are dist i nct fr om classical v o lta ge gate d io n c ha n nels. A m o n g t hese, tra nsie nt rece pt or p ote ntial a n k yri n 1 ( T R P A 1) is a calci u m-p er m ea ble n o nselect i ve cati on c ha n nel, w hic h is e x presse d i n t he a x o ns a n d i n b ot h peri p heral a n d ce ntral ter mi nals of n oci ce pt ors. It is als o c o nsi dere d t o be i m p orta nt as a c he m ose ns or of n ocice pti o n ( K o vist o et al. 2 0 1 8; Maat uf et al. 2 0 1 9; Wa n g et al. 2 0 1 9 ). T R P A 1’s i n v ol ve me nt i n pai n a n d i nfla m mati on a n d its l ocalizat i on i n se ns or y ne ur o ns are k n o w n ( B o d ki n a n d Brai n 2 0 1 1 ; Üc kert et al. 2 0 1 7). D ue t o i ts r ole i n e v o ki n g pai n a n d elicit i n g a n a versi ve res p o nse, T R P A 1 ma y be a pr o misi n g tar get f or treati n g pai n (Be ne mei et al. 2 0 1 7; Berta et al. 2 0 1 7; De marti ni et al. 2 0 1 7; Maat uf et al. 2 0 1 9; Wa n g et al. 2 0 1 9).
> L Y 3 5 2 6 3 1 8 is a n orall y a d mi nistere d, p ote nt, a n d select i ve n o v
> …（中略）…
> 5 2 6 3 1 8 i n St u d y C V A C s h o we d n o cli nicall y sig nifica nt safet y or t ol era bilit y c o ncer ns at hi g her e x p os ures f o ll owi n g si n gle or m ul tiple d oses
> C CI
> C CI
> T o xic ol o g y S t u dies a n d N O A E L E x p os ure
> C CI
> C CI
> 2. 3. 1. Ris k Assess me nt
> C CI
> C CI

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 本研究旨在对LY3526318在缓解因特应性皮炎引起的膝关节疼痛方面的效果进行评估。

### NCT05080660·条目 10：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_32b6476f436c0e80c6d6e785`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 11：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_4b737575ec9f88ce70ca4a84`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 12：3. Objectives and Endpoints (objectives_endpoints)

- 条目ID：`wref_translation_item_51c9f3c1eed9ee7a58b0c867`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_2:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 3. Objectives and Endpoints
> The CPMP Master Protocol and OA DSA CPMP(1) include objectives and endpoints applicable for this study. This table describes objectives and endpoints specific for LY3526318.
> | Objectives | Endpoints |
> | Tertiary/Exploratory | |
> | Measure the PK of LY3526318 in participants with OA. | Measure of plasma concentrations of LY3526318 to enable PK evaluations. |
> Abbreviations: OA = osteoarthritis; PK = pharmacokinetic.
> 4. St u d y Desi g n
> 4. 1. O ver all Desi g n
> T he C P M P Master Pr ot oc ol descri bes t he o verall st u d y desi g n a n d st u d y d esig n r ati o nale. T his secti on descri bes visits a n d o verall pr oce d ures u ni q ue t o I S A O A 0 2 f or L Y 35 2 6 3 1 8 i n a d diti on t o t he pr oce d ures o utli ne d i n C P M P a n d C P M P( 1) .
> D o u ble - Bli n d Tre at me nt Peri o d ( Visits 3 t hr o u g h 7)
> Eac h visit is a n o ut patie nt visit.
> At Visit 3
>  parti ci pa nts are ra n d o mize d t o L Y 3 5 2 6 3 1 8 or pl ace b o  t he sit e c o mpletes t he O A 0 2 baseli ne pr oce d ures a n d sa m ple c o llecti on  parti ci pa nts recei ve t heir or al st u d y int er ve nt i on  t he site c ollects partici pa nts vitals at 2 a n d 4 h o urs after t he c o m pleti on of t he oral a d mi nistrati o n  t he sit e c o mpletes all p ost- treat me nt sa mple c ollecti o n a n d safet y mo ni t ori n g, a n d  t he site i nstr ucts partici pa nts t o c o nti n ue wit h st u d y restrict i ons a n d N u meric Rat i n g Scal e ( N R S) diar y e ntries bef ore t heir visit disc har ge.
> At Visits 4 t hr o u g h 7
>  t he site re vie ws a vaila ble safet y data a n d c o m pletes pre -d ose pr oce d ures a n d sa m ple c ollect i on  parti ci pa nts c o nti n ue oral st u d y int er ve nt i on  t he sit e c o mpletes all s
> …（中略）…
>  are pr o hi bite d fr om Visi t 2 t o Visit 7 f or partici pa nts ra n d o mize d t o t his I S A st u d y will be pr o vide d i n t he Ma n ual of O perati o ns . P artici pa nts ma y ret ur n t o t heir sta n dar d of care after Visit 7 is c om p lete d, as cli nicall y a p pr o priate.
> C CI C CI

**【中文译文段落】**（原始模型输出（未经对齐组装））

> CPMP主方案以及OA DSA CPMP(1)方案中均规定了适用于本研究的目的与终点。本表格则列出了专门针对LY3526318这一药物的研究目的和相应终点。

### NCT05080660·条目 13：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_58d7d0194ce52dadac135351`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 14：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_621abd31a5d8b0f1015d235a`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 15：3. Objectives and Endpoints.........................................................................................17 (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_6e7e5fe153b7a4bd7489a65d`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_4:numeric_tokens_changed`）
  - 译文第 4 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_4:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 6. Study Intervention(s) and Concomitant Therapy ...................................................22 6.1. Study Intervention(s) Administered ............................................................................22 6.2. Preparation, Handling, Storage, and Accountability....................................................22 6.3. Measures to Minimize Bias: Randomization and Blinding..........................................22 6.4. Study Intervention Compliance...................................................................................22 6.5. Treatment of Overdose ...............................................................................................22 6.6. Concomitant Therapy .................................................................................................23
> 7. Discontinuation of Study Intervention and Participant Discontinuation/Withdrawal....................................................................................24
> 8. Study Assessments and Procedures .........................................................................25 8.1. Efficacy Assessments .................................................................................................25 8.2. Safety Assessments ....................................................................................................25 8.2.1. Physical Examinations................................................................................................25 8.2.2. Electrocardiograms.....................................................................................................25 8.2.3. Clinical Safety Laboratory Tests.................................................................................25 8.3. Adverse Events, Serious Adverse Events, and Product Complaints .............
> …（中略）…
> ttee : Yes
> S af et y re vie ws are c o vere d b y t he Assess me nt C o m mittee c harter f or t he C hr o nic Pai n Master Pr ot oc ol .
> 1.2. Schema
> Abbreviations: PDEP = preliminary data entry period; V = visit. * Medication washout and PDEP begins. ** Randomization to either LY3526318 or placebo.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 8.5 药效动力学.....................................................................................................................26

### NCT05080660·条目 16：Unlabelled section (safety) (safety) · 5

- 条目ID：`wref_translation_item_71bb203d18347a3da4a5d005`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 13 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_13:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> data monitoring committee A data monitoring committee is a group of independent scientists who are appointed to monitor the safety and scientific integrity of a human research intervention, and to make recommendations to the sponsor regarding the stopping of a study for efficacy, or for harms, or for futility. The composition of the committee is dependent upon the scientific skills and knowledge required for monitoring the particular study.
> DSA disease-state addendum
> ECG electrocardiogram
> eGFR estimated glomerular filtration rate
> enroll The act of assigning a participant to a treatment. Participants who are enrolled in the study are those who have been assigned to a treatment.
> IB Investigator’s Brochure
> IC 50 half-maximal inhibitory concentration
> IMP Investigational Medicinal Product
> informed consent A process by which a participant voluntarily confirms his or her willingness to participate in a particular study, after having been informed of all aspects of the study that are relevant to the participant’s decision to participate. Informed consent is documented by means of a written, signed, and dated informed consent form.
> interim analysis An interim analysis is an analysis of clinical study data, separated into treatment groups, that is conducted before the final reporting database is created/locked.
> investigational product A pharmaceutical form of an active ingredient or placebo being tested or used as a reference in a clinical trial, including products already on the market when used or assembled (formulated or packaged) in a way different from the authorized form, or marketed products used for an unauthorized indication, or marketed products used to gain further information about the authorized form.
> ISA intervention-specific appendix
> NIMP noninvestigational medicin
> …（中略）…
> subject”: an individual who participates in a clinical trial, either as recipient of an investigational medicinal product or as a control
> PK pharmacokinetics
> PO by mouth
> PoC proof-of-concept
> OA osteoarthritis
> QD once daily
> QTc corrected QT interval
> SAD single ascending dose
> SAE serious adverse event

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 口服给药

### NCT05080660·条目 17：Unlabelled section (safety) (safety) · 3

- 条目ID：`wref_translation_item_7ef14c6ba7bad2d2037ada67`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 6 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_6:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> S af et y a nal yses ha ve bee n descri be d i n t he C P M P Master Pr ot oc ol. A d dit i on al I S A-s pecific safety a nal yses ma y be describe d i n t he I S A S A P.
> 9. 3. 4. Ot her A n al yses
> 9. 3. 4. 1. P h ar m ac o ki netic a n d P h ar m ac o d y n a mic A n al yses
> T he o bser ve d plas ma c o nce ntrati o ns f or L Y 3 5 2 6 3 1 8 will be re p orte d gra p hicall y a n d descri pt i vel y.
> P har mac o ki net ic m o deli n g a n d e x p os ure -res p o nse a nal yses of efficac y meas ures ma y be c o n d ucte d. If c o n d ucte d, t he a nal yses will be perf or me d usi n g p o p ulat i on a nal ysis s o ftware, N O N M E M ® , if data allo ws. T he versi o n of a n y s oft ware use d f or t he a nal ysis will be d oc u m e nte d, a n d t he pr o gra m will meet t he Lill y re q uire me nts of s oft ware vali dat i on. It i s p ossi ble t hat ot her vali date d, e q ui vale nt P K s oft ware pr o gra ms ma y be use d if a p pr o priate, warra nte d, a n d a p pr o ve d b y Gl o bal P K/ p har mac o d y na mic ma na ge me nt. Data ma y be p o ole d wi t h data fr o m ot her st u dies for a n i nte grate d P K a n d/ or P K/ p ha r mac o d y na mic a nal ysis.
> A li mite d n u m ber of pre-i de ntifie d i n di vi d uals i n de pe n de nt of t he st u d y t e a m ma y recei ve access t o u n bli n de d data, as s pecifie d i n t he u n bli n di n g pla n, pri or t o t he i nteri m or fi nal data base l oc k, i n or der t o i nitiate t he fi nal p o p ulat i on P K a n d/ or e x p os ure -res p o nse m o del de vel o p me nt pr ocesses. I nf or mati o n t hat ma y u n bli n d t he st u d y d uri n g t he a nal yses will n ot be re p orte d t o st u d y sit es or t he bli n de d st u d y tea m u ntil t he st u d y has bee n u n bli n de d.
> 9. 4. I nteri m A n 
> …（中略）…
>  change
> The prevailing consideration for making a change is ensuring the safety of study participants. Additional important considerations for making a change are compliance with Good Clinical Practice, enabling participants to continue safely in the study and maintaining the integrity of the study.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> LY3526318的实测血浆浓度将通过图表及文字描述的方式进行报告。

### NCT05080660·条目 18：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_7fb41bdaaf8bde1b553954f5`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 19：3. Objectives and Endpoints (objectives_endpoints)

- 条目ID：`wref_translation_item_85af8620a0166f2acbd216c1`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_2:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 3. Objectives and Endpoints
> The CPMP Master Protocol and OA DSA CPMP(1) include objectives and endpoints applicable for this study. This table describes objectives and endpoints specific for LY3526318.
> | Objectives | Endpoints |
> | Tertiary/Exploratory | |
> | Measure the PK of LY3526318 in participants with OA. | Measure of plasma concentrations of LY3526318 to enable PK evaluations. |
> Abbreviations: OA = osteoarthritis; PK = pharmacokinetic.
> 4. St u d y Desi g n
> 4. 1. O ver all Desi g n
> T he C P M P Master Pr ot oc ol descri bes t he o verall st u d y desi g n a n d st u d y d esig n r ati o nale. T his secti on descri bes visits a n d o verall pr oce d ures u ni q ue t o I S A O A 0 2 f or L Y 35 2 6 3 1 8 i n a d diti on t o t he pr oce d ures o utli ne d i n C P M P a n d C P M P( 1) .
> D o u ble - Bli n d Tre at me nt Peri o d ( Visits 3 t hr o u g h 7)
> Eac h visit is a n o ut patie nt visit.
> At Visit 3
>  parti ci pa nts are ra n d o mize d t o L Y 3 5 2 6 3 1 8 or pl ace b o  t he sit e c o mpletes t he O A 0 2 baseli ne pr oce d ures a n d sa m ple c o llecti on  parti ci pa nts recei ve t heir or al st u d y int er ve nt i on  t he site c ollects partici pa nts vitals at 2 a n d 4 h o urs after t he c o m pleti on of t he oral a d mi nistrati o n  t he sit e c o mpletes all p ost- treat me nt sa mple c ollecti o n a n d safet y mo ni t ori n g, a n d  t he site i nstr ucts partici pa nts t o c o nti n ue wit h st u d y restrict i ons a n d N u meric Rat i n g Scal e ( N R S) diar y e ntries bef ore t heir visit disc har ge.
> At Visits 4 t hr o u g h 7
>  t he site re vie ws a vaila ble safet y data a n d c o m pletes pre -d ose pr oce d ures a n d sa m ple c ollect i on  parti ci pa nts c o nti n ue oral st u d y int er ve nt i on  t he sit e c o mpletes all s
> …（中略）…
>  are pr o hi bite d fr om Visi t 2 t o Visit 7 f or partici pa nts ra n d o mize d t o t his I S A st u d y will be pr o vide d i n t he Ma n ual of O perati o ns . P artici pa nts ma y ret ur n t o t heir sta n dar d of care after Visit 7 is c om p lete d, as cli nicall y a p pr o priate.
> C CI C CI

**【中文译文段落】**（原始模型输出（未经对齐组装））

> CPMP主方案以及OA DSA CPMP(1)方案中均规定了适用于本研究的目的与终点。本表格则列出了专门针对LY3526318这一药物的研究目的和相应终点。

### NCT05080660·条目 20：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_85e34d30cd99425e1c15c014`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 21：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_8a8382245031de00e3cd7e26`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> More information about the known and expected risks, SAEs, and reasonably anticipated AEs of LY3526318 may be found in the IB. Information on AEs expected to be related to the investigational product may be found in Section 7 (Reference Safety Information for Assessment of Expectedness of Serious Adverse Reactions) of the IB. Information on SAEs that are expected in the study population independent of drug exposure will be assessed by the sponsor in aggregate, periodically during the course of the study, and may be found in Section 5 (Effects in Humans) of the IB.
> 2.3.2. Benefit Assessment
> Potential benefits for the study participants include
>  information obtained from study-related medical procedures o physical examinations o laboratory tests o ECGs  detailed evaluations of OA o knee examinations o knee X-rays  OA-associated questionnaires that may improve participants understanding their own condition.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 关于LY3526318已知的及预期存在的风险、严重不良事件以及可合理预见的不良事件的相关信息，均可查阅研究者手册。那些预计与试验用药品相关的不良事件的信息则见于该手册的第7节（用于评估严重不良反应预期性的安全性参考信息）。至于那些无论是否接触该药物均会在研究人群中出现的严重不良事件，将由申办方在整个研究过程中定期汇总评估；相关信息可查阅研究者手册的第5节（人体用药影响）。

### NCT05080660·条目 22：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_8fc9e2baafe05d95d3fd2798`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 23：8.2. Safety Assessments (safety)

- 条目ID：`wref_translation_item_926061a98bdc9750cb128d2c`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 15 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_15:numeric_tokens_changed`）
  - 译文第 15 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_15:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 8.2. Safety Assessments
> Planned time points for all safety assessments are provided in the SoAs.
> 8.2.1. Physical Examinations
> Symptom directed physical examinations of skin, eyes, mouth, lungs, and gastrointestinal tract will be performed at each visit as described in the SoA. Any clinically significant abnormal physical examination findings will be reported as AEs.
> 8.2.2. Electrocardiograms
> Single 12-lead ECG will be obtained as outlined in the SoA using an ECG machine that automatically calculates the heart rate and measures PR, RR, QRS, QT, and QTcF intervals.
> 8.2.3. Clinical Safety Laboratory Tests
> See OA02 Section 10.1 (Appendix 1) for the list of clinical laboratory tests to be performed and to the SoA for the timing and frequency for ISA OA02.
> 8.3. Adverse Events, Serious Adverse Events, and Product Complaints
> See the CPMP Master Protocol for additional details.
> 8.4. Pharmacokinetics ● Blood samples will be collected for measurement of plasma concentrations of LY3526318 as specified in the SoA.
> ● A maximum of 3 samples may be collected at additional time points during the study if warranted and agreed upon between the investigator and the sponsor. The timing of sampling may be altered during the course of the study based on newly available data (e.g., to obtain data closer to the time of peak plasma concentrations) to ensure appropriate monitoring.
> ● Instructions for the collection and handling of biological samples will be provided by the sponsor. The actual date and time (24-hour clock time) of each sample will be recorded.
> ● The date and time (24-hour clock time) of LY3526318 administration prior to the PK sampling will be recorded i.e. the dose administered in the clinic at Visit 3 and the last at home dose prior to each of Visit 4, Visit 5, Visit 6, and Visi
> …（中略）…
> s met h o ds descri be d, a n d t he j ust ificati on f or ma ki n g t he c ha n ge, will be descri be d i n t he statist ical a nal ysis pl a n ( S A P) a n d t he cli nical st u d y re p ort. A d ditio nal e xpl orat o r y a nal yses of t he data will be c o n d ucte d as dee me d a p pr o priate.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> ● 这些样本将用于评估LY3526318的药代动力学特征。为测定LY3526318血浆浓度而采集的样本，也可用于对研究期间或研究后出现的各类问题所涉及的安全性或对试验药物的评估情况进行分析。

### NCT05080660·条目 24：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_969d52fcfdaff500b4d6d1f7`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 25：3. Objectives and Endpoints (objectives_endpoints)

- 条目ID：`wref_translation_item_9d5812776af80148ca7c7c20`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_2:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 3. Objectives and Endpoints
> The CPMP Master Protocol and OA DSA CPMP(1) include objectives and endpoints applicable for this study. This table describes objectives and endpoints specific for LY3526318.
> | Objectives | Endpoints |
> | Tertiary/Exploratory | |
> | Measure the PK of LY3526318 in participants with OA. | Measure of plasma concentrations of LY3526318 to enable PK evaluations. |
> Abbreviations: OA = osteoarthritis; PK = pharmacokinetic.
> 4. St u d y Desi g n
> 4. 1. O ver all Desi g n
> T he C P M P Master Pr ot oc ol descri bes t he o verall st u d y desi g n a n d st u d y d esig n r ati o nale. T his secti on descri bes visits a n d o verall pr oce d ures u ni q ue t o I S A O A 0 2 f or L Y 35 2 6 3 1 8 i n a d diti on t o t he pr oce d ures o utli ne d i n C P M P a n d C P M P( 1) .
> D o u ble - Bli n d Tre at me nt Peri o d ( Visits 3 t hr o u g h 7)
> Eac h visit is a n o ut patie nt visit.
> At Visit 3
>  parti ci pa nts are ra n d o mize d t o L Y 3 5 2 6 3 1 8 or pl ace b o  t he sit e c o mpletes t he O A 0 2 baseli ne pr oce d ures a n d sa m ple c o llecti on  parti ci pa nts recei ve t heir or al st u d y int er ve nt i on  t he site c ollects partici pa nts vitals at 2 a n d 4 h o urs after t he c o m pleti on of t he oral a d mi nistrati o n  t he sit e c o mpletes all p ost- treat me nt sa mple c ollecti o n a n d safet y mo ni t ori n g, a n d  t he site i nstr ucts partici pa nts t o c o nti n ue wit h st u d y restrict i ons a n d N u meric Rat i n g Scal e ( N R S) diar y e ntries bef ore t heir visit disc har ge.
> At Visits 4 t hr o u g h 7
>  t he site re vie ws a vaila ble safet y data a n d c o m pletes pre -d ose pr oce d ures a n d sa m ple c ollect i on  parti ci pa nts c o nti n ue oral st u d y int er ve nt i on  t he sit e c o mpletes all s
> …（中略）…
>  are pr o hi bite d fr om Visi t 2 t o Visit 7 f or partici pa nts ra n d o mize d t o t his I S A st u d y will be pr o vide d i n t he Ma n ual of O perati o ns . P artici pa nts ma y ret ur n t o t heir sta n dar d of care after Visit 7 is c om p lete d, as cli nicall y a p pr o priate.
> C CI C CI

**【中文译文段落】**（原始模型输出（未经对齐组装））

> CPMP主方案以及OA DSA CPMP(1)方案中均规定了适用于本研究的目的与终点。本表格则列出了专门针对LY3526318这一药物的研究目的和相应终点。

### NCT05080660·条目 26：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_b2f7d4b5e3f5c5c59b52226c`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 27：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_bfebe90962e992f3c4080285`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 28：3. Objectives and Endpoints.........................................................................................17 (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_c6b8bb712098b10bdfc61426`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_4:numeric_tokens_changed`）
  - 译文第 4 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_4:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 6. Study Intervention(s) and Concomitant Therapy ...................................................22 6.1. Study Intervention(s) Administered ............................................................................22 6.2. Preparation, Handling, Storage, and Accountability....................................................22 6.3. Measures to Minimize Bias: Randomization and Blinding..........................................22 6.4. Study Intervention Compliance...................................................................................22 6.5. Treatment of Overdose ...............................................................................................22 6.6. Concomitant Therapy .................................................................................................23
> 7. Discontinuation of Study Intervention and Participant Discontinuation/Withdrawal....................................................................................24
> 8. Study Assessments and Procedures .........................................................................25 8.1. Efficacy Assessments .................................................................................................25 8.2. Safety Assessments ....................................................................................................25 8.2.1. Physical Examinations................................................................................................25 8.2.2. Electrocardiograms.....................................................................................................25 8.2.3. Clinical Safety Laboratory Tests.................................................................................25 8.3. Adverse Events, Serious Adverse Events, and Product Complaints .............
> …（中略）…
> ttee : Yes
> S af et y re vie ws are c o vere d b y t he Assess me nt C o m mittee c harter f or t he C hr o nic Pai n Master Pr ot oc ol .
> 1.2. Schema
> Abbreviations: PDEP = preliminary data entry period; V = visit. * Medication washout and PDEP begins. ** Randomization to either LY3526318 or placebo.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 8.5 药效动力学.....................................................................................................................26

### NCT05080660·条目 29：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_d52b0068ecbfd6844d000eff`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 30：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_d5fb492cb9b75c329e2238cf`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）

**【原文段落】**（英文原文）

> T he p u r p ose of t his st u d y is t o test w het her L Y 3 5 2 6 3 1 8 is efficaci o us i n relie vi n g k nee pai n d ue t o O A. Data will be c ollecte d t o assess t he safety a n d t olera bilit y of L Y 3 5 2 6 3 1 8 i n t his st u d y p o p ul at i on. P har mac o ki net ic (P K ) pr o perties will als o be e x pl ore d . T he t otality of data fr o m t his pr o of -of c o nce pt ( P o C) stu d y will assess t he be nefit s a n d ris ks ass ociate d wit h L Y 3 5 2 6 3 1 8 a n d i nf or m decisi o ns f or t he cli nical de vel o p me nt of L Y 3 5 2 6 3 1 8.
> 2. 2. B ac k gr o u n d
> T he tra nsie nt rece pt or p ote ntial ( T R P ) io n c ha n nel fa mil y c o m pr ises a gr o u p of 2 8 n o nselecti ve catio n c ha n nels t hat are dist i nct fr om classical v o lta ge gate d io n c ha n nels. A m o n g t hese, tra nsie nt rece pt or p ote ntial a n k yri n 1 ( T R P A 1) is a calci u m-p er m ea ble n o nselect i ve cati on c ha n nel, w hic h is e x presse d i n t he a x o ns a n d i n b ot h peri p heral a n d ce ntral ter mi nals of n oci ce pt ors. It is als o c o nsi dere d t o be i m p orta nt as a c he m ose ns or of n ocice pti o n ( K o vist o et al. 2 0 1 8; Maat uf et al. 2 0 1 9; Wa n g et al. 2 0 1 9 ). T R P A 1’s i n v ol ve me nt i n pai n a n d i nfla m mati on a n d its l ocalizat i on i n se ns or y ne ur o ns are k n o w n ( B o d ki n a n d Brai n 2 0 1 1 ; Üc kert et al. 2 0 1 7). D ue t o i ts r ole i n e v o ki n g pai n a n d elicit i n g a n a versi ve res p o nse, T R P A 1 ma y be a pr o misi n g tar get f or treati n g pai n (Be ne mei et al. 2 0 1 7; Berta et al. 2 0 1 7; De marti ni et al. 2 0 1 7; Maat uf et al. 2 0 1 9; Wa n g et al. 2 0 1 9).
> L Y 3 5 2 6 3 1 8 is a n orall y a d mi nistere d, p ote nt, a n d select i ve n o v
> …（中略）…
> 5 2 6 3 1 8 i n St u d y C V A C s h o we d n o cli nicall y sig nifica nt safet y or t ol era bilit y c o ncer ns at hi g her e x p os ures f o ll owi n g si n gle or m ul tiple d oses
> C CI
> C CI
> T o xic ol o g y S t u dies a n d N O A E L E x p os ure
> C CI
> C CI
> 2. 3. 1. Ris k Assess me nt
> C CI
> C CI

**【中文译文段落】**（原始模型输出（未经对齐组装））

> 本研究旨在对LY3526318在缓解因特应性皮炎引起的膝关节疼痛方面的效果进行评估。

### NCT05080660·条目 31：3. Objectives and Endpoints (objectives_endpoints)

- 条目ID：`wref_translation_item_ddbade8daad747aeb91a1f4f`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_2:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 3. Objectives and Endpoints
> The CPMP Master Protocol and OA DSA CPMP(1) include objectives and endpoints applicable for this study. This table describes objectives and endpoints specific for LY3526318.
> | Objectives | Endpoints |
> | Tertiary/Exploratory | |
> | Measure the PK of LY3526318 in participants with OA. | Measure of plasma concentrations of LY3526318 to enable PK evaluations. |
> Abbreviations: OA = osteoarthritis; PK = pharmacokinetic.
> 4. St u d y Desi g n
> 4. 1. O ver all Desi g n
> T he C P M P Master Pr ot oc ol descri bes t he o verall st u d y desi g n a n d st u d y d esig n r ati o nale. T his secti on descri bes visits a n d o verall pr oce d ures u ni q ue t o I S A O A 0 2 f or L Y 35 2 6 3 1 8 i n a d diti on t o t he pr oce d ures o utli ne d i n C P M P a n d C P M P( 1) .
> D o u ble - Bli n d Tre at me nt Peri o d ( Visits 3 t hr o u g h 7)
> Eac h visit is a n o ut patie nt visit.
> At Visit 3
>  parti ci pa nts are ra n d o mize d t o L Y 3 5 2 6 3 1 8 or pl ace b o  t he sit e c o mpletes t he O A 0 2 baseli ne pr oce d ures a n d sa m ple c o llecti on  parti ci pa nts recei ve t heir or al st u d y int er ve nt i on  t he site c ollects partici pa nts vitals at 2 a n d 4 h o urs after t he c o m pleti on of t he oral a d mi nistrati o n  t he sit e c o mpletes all p ost- treat me nt sa mple c ollecti o n a n d safet y mo ni t ori n g, a n d  t he site i nstr ucts partici pa nts t o c o nti n ue wit h st u d y restrict i ons a n d N u meric Rat i n g Scal e ( N R S) diar y e ntries bef ore t heir visit disc har ge.
> At Visits 4 t hr o u g h 7
>  t he site re vie ws a vaila ble safet y data a n d c o m pletes pre -d ose pr oce d ures a n d sa m ple c ollect i on  parti ci pa nts c o nti n ue oral st u d y int er ve nt i on  t he sit e c o mpletes all s
> …（中略）…
>  are pr o hi bite d fr om Visi t 2 t o Visit 7 f or partici pa nts ra n d o mize d t o t his I S A st u d y will be pr o vide d i n t he Ma n ual of O perati o ns . P artici pa nts ma y ret ur n t o t heir sta n dar d of care after Visit 7 is c om p lete d, as cli nicall y a p pr o priate.
> C CI C CI

**【中文译文段落】**（原始模型输出（未经对齐组装））

> CPMP主方案以及OA DSA CPMP(1)方案中均规定了适用于本研究的目的与终点。本表格则列出了专门针对LY3526318这一药物的研究目的和相应终点。

### NCT05080660·条目 32：8.2. Safety Assessments (safety)

- 条目ID：`wref_translation_item_df3a645f58d4cd8b9f3703af`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 15 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_15:numeric_tokens_changed`）
  - 译文第 15 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_15:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 8.2. Safety Assessments
> Planned time points for all safety assessments are provided in the SoAs.
> 8.2.1. Physical Examinations
> Symptom directed physical examinations of skin, eyes, mouth, lungs, and gastrointestinal tract will be performed at each visit as described in the SoA. Any clinically significant abnormal physical examination findings will be reported as AEs.
> 8.2.2. Electrocardiograms
> Single 12-lead ECG will be obtained as outlined in the SoA using an ECG machine that automatically calculates the heart rate and measures PR, RR, QRS, QT, and QTcF intervals.
> 8.2.3. Clinical Safety Laboratory Tests
> See OA02 Section 10.1 (Appendix 1) for the list of clinical laboratory tests to be performed and to the SoA for the timing and frequency for ISA OA02.
> 8.3. Adverse Events, Serious Adverse Events, and Product Complaints
> See the CPMP Master Protocol for additional details.
> 8.4. Pharmacokinetics ● Blood samples will be collected for measurement of plasma concentrations of LY3526318 as specified in the SoA.
> ● A maximum of 3 samples may be collected at additional time points during the study if warranted and agreed upon between the investigator and the sponsor. The timing of sampling may be altered during the course of the study based on newly available data (e.g., to obtain data closer to the time of peak plasma concentrations) to ensure appropriate monitoring.
> ● Instructions for the collection and handling of biological samples will be provided by the sponsor. The actual date and time (24-hour clock time) of each sample will be recorded.
> ● The date and time (24-hour clock time) of LY3526318 administration prior to the PK sampling will be recorded i.e. the dose administered in the clinic at Visit 3 and the last at home dose prior to each of Visit 4, Visit 5, Visit 6, and Visi
> …（中略）…
> s met h o ds descri be d, a n d t he j ust ificati on f or ma ki n g t he c ha n ge, will be descri be d i n t he statist ical a nal ysis pl a n ( S A P) a n d t he cli nical st u d y re p ort. A d ditio nal e xpl orat o r y a nal yses of t he data will be c o n d ucte d as dee me d a p pr o priate.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> ● 这些样本将用于评估LY3526318的药代动力学特征。为测定LY3526318血浆浓度而采集的样本，也可用于对研究期间或研究后出现的各类问题所涉及的安全性或对试验药物的评估情况进行分析。

### NCT05080660·条目 33：3. Objectives and Endpoints (objectives_endpoints)

- 条目ID：`wref_translation_item_e5eb0242b7bab86735da449c`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_2:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 3. Objectives and Endpoints
> The CPMP Master Protocol and OA DSA CPMP(1) include objectives and endpoints applicable for this study. This table describes objectives and endpoints specific for LY3526318.
> | Objectives | Endpoints |
> | Tertiary/Exploratory | |
> | Measure the PK of LY3526318 in participants with OA. | Measure of plasma concentrations of LY3526318 to enable PK evaluations. |
> Abbreviations: OA = osteoarthritis; PK = pharmacokinetic.
> 4. St u d y Desi g n
> 4. 1. O ver all Desi g n
> T he C P M P Master Pr ot oc ol descri bes t he o verall st u d y desi g n a n d st u d y d esig n r ati o nale. T his secti on descri bes visits a n d o verall pr oce d ures u ni q ue t o I S A O A 0 2 f or L Y 35 2 6 3 1 8 i n a d diti on t o t he pr oce d ures o utli ne d i n C P M P a n d C P M P( 1) .
> D o u ble - Bli n d Tre at me nt Peri o d ( Visits 3 t hr o u g h 7)
> Eac h visit is a n o ut patie nt visit.
> At Visit 3
>  parti ci pa nts are ra n d o mize d t o L Y 3 5 2 6 3 1 8 or pl ace b o  t he sit e c o mpletes t he O A 0 2 baseli ne pr oce d ures a n d sa m ple c o llecti on  parti ci pa nts recei ve t heir or al st u d y int er ve nt i on  t he site c ollects partici pa nts vitals at 2 a n d 4 h o urs after t he c o m pleti on of t he oral a d mi nistrati o n  t he sit e c o mpletes all p ost- treat me nt sa mple c ollecti o n a n d safet y mo ni t ori n g, a n d  t he site i nstr ucts partici pa nts t o c o nti n ue wit h st u d y restrict i ons a n d N u meric Rat i n g Scal e ( N R S) diar y e ntries bef ore t heir visit disc har ge.
> At Visits 4 t hr o u g h 7
>  t he site re vie ws a vaila ble safet y data a n d c o m pletes pre -d ose pr oce d ures a n d sa m ple c ollect i on  parti ci pa nts c o nti n ue oral st u d y int er ve nt i on  t he sit e c o mpletes all s
> …（中略）…
>  are pr o hi bite d fr om Visi t 2 t o Visit 7 f or partici pa nts ra n d o mize d t o t his I S A st u d y will be pr o vide d i n t he Ma n ual of O perati o ns . P artici pa nts ma y ret ur n t o t heir sta n dar d of care after Visit 7 is c om p lete d, as cli nicall y a p pr o priate.
> C CI C CI

**【中文译文段落】**（原始模型输出（未经对齐组装））

> CPMP主方案以及OA DSA CPMP(1)方案中均规定了适用于本研究的目的与终点。本表格则列出了专门针对LY3526318这一药物的研究目的和相应终点。

### NCT05080660·条目 34：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_ee46a59a0f5124457f531821`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 35：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_f910775dc95d48def7239cf4`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_1:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> This amendment addresses changes in the exclusion criteria in response to FDA feedback based on in vitro data currently available.
> | Following final d | atabase lock all roles may be consi | dered unblinded. |
> | Table 6-3 | Blinding and unblinding plan | |
> | Role | Time or Event | |
> | | Randomization Tre list generated all do | atment Safety event Interim ocation & (single Analysis/ sing subject dose unblinded) escalation/ |
> | Participants | B B | safety review UI B |
> | Site Staff Global Clinical Su Randomization O Statistician/statist programmer/ data (e.g. biomarker, P Unblinded Spons for study treatme unblinded monito analyst(s) All other Sponsor identified above (i team, manageme decision boards, functions) B Complete blinde UI Unblinded to ind | B B | UI B |
> | | pply UI UI ffice UI UI | UI UI UI UI |
> | | ical B UI analysts K) or staff, e.g. B UI | UI UI UI UI |
> | | nt re-supply, r(s), sample staff not B B .e. project nt & | UI UI |
> | | support d | |
> | | ividual participant treatment codes | |
> | 6.3.3 Emer Emergency code the participant sa | gency breaking of assigned tr breaks must only be undertaken fely. | eatment code when it is required to in order to treat |
> Added reference to Section 5.2 and the Manual of Operations for additional information.
> Additional information for excluded concomitant medications are listed in Section 5.2 and the Manual of Operations.

**【中文译文段落】**（原始模型输出（未经对齐组装））

> | | 临床 B UI分析员 K)或工作人员，例如B UI | UI UI UI UI |

### NCT05080660·条目 36：3. Objectives and Endpoints (objectives_endpoints)

- 条目ID：`wref_translation_item_fb0f948ce5d4ad707def13ef`（第 8 次尝试被拦）
- **发现的问题：**
  - 译文第 2 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_2:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> 3. Objectives and Endpoints
> The CPMP Master Protocol and OA DSA CPMP(1) include objectives and endpoints applicable for this study. This table describes objectives and endpoints specific for LY3526318.
> | Objectives | Endpoints |
> | Tertiary/Exploratory | |
> | Measure the PK of LY3526318 in participants with OA. | Measure of plasma concentrations of LY3526318 to enable PK evaluations. |
> Abbreviations: OA = osteoarthritis; PK = pharmacokinetic.
> 4. St u d y Desi g n
> 4. 1. O ver all Desi g n
> T he C P M P Master Pr ot oc ol descri bes t he o verall st u d y desi g n a n d st u d y d esig n r ati o nale. T his secti on descri bes visits a n d o verall pr oce d ures u ni q ue t o I S A O A 0 2 f or L Y 35 2 6 3 1 8 i n a d diti on t o t he pr oce d ures o utli ne d i n C P M P a n d C P M P( 1) .
> D o u ble - Bli n d Tre at me nt Peri o d ( Visits 3 t hr o u g h 7)
> Eac h visit is a n o ut patie nt visit.
> At Visit 3
>  parti ci pa nts are ra n d o mize d t o L Y 3 5 2 6 3 1 8 or pl ace b o  t he sit e c o mpletes t he O A 0 2 baseli ne pr oce d ures a n d sa m ple c o llecti on  parti ci pa nts recei ve t heir or al st u d y int er ve nt i on  t he site c ollects partici pa nts vitals at 2 a n d 4 h o urs after t he c o m pleti on of t he oral a d mi nistrati o n  t he sit e c o mpletes all p ost- treat me nt sa mple c ollecti o n a n d safet y mo ni t ori n g, a n d  t he site i nstr ucts partici pa nts t o c o nti n ue wit h st u d y restrict i ons a n d N u meric Rat i n g Scal e ( N R S) diar y e ntries bef ore t heir visit disc har ge.
> At Visits 4 t hr o u g h 7
>  t he site re vie ws a vaila ble safet y data a n d c o m pletes pre -d ose pr oce d ures a n d sa m ple c ollect i on  parti ci pa nts c o nti n ue oral st u d y int er ve nt i on  t he sit e c o mpletes all s
> …（中略）…
>  are pr o hi bite d fr om Visi t 2 t o Visit 7 f or partici pa nts ra n d o mize d t o t his I S A st u d y will be pr o vide d i n t he Ma n ual of O perati o ns . P artici pa nts ma y ret ur n t o t heir sta n dar d of care after Visit 7 is c om p lete d, as cli nicall y a p pr o priate.
> C CI C CI

**【中文译文段落】**（原始模型输出（未经对齐组装））

> CPMP主方案以及OA DSA CPMP(1)方案中均规定了适用于本研究的目的与终点。本表格则列出了专门针对LY3526318这一药物的研究目的和相应终点。


---

# 2. K3 项目（proj_user_fad9f64f3151）

## 研究 NCT02176291（1 项待处置）

### NCT02176291·条目 1：Unlabelled section (objectives_endpoints)

- 条目ID：`wref_translation_item_c561fdf957b2132967c662b1`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Phase 2, RCT Overview: In the 8-weeks of BPN vs. placebo, thirty subjects will be randomized (using permuted block randomization) 2:1 to receive venlafaxine XR (at the dose they reached and tolerated in the open-label lead-in) plus either BPN or placebo. The reasons for using a 2:1 random allocation include:
  - 第 1 单元译文：II期随机对照试验概述：在为期8周的BPN与安慰剂对比试验中，共有30名受试者将通过随机化分组方式（采用置换区组随机法）以2:1的比例被分配至两组，分别接受文拉法辛XR制剂（剂量为受试者在开放标签导入期能够耐受并达到的剂量），同时分别联合使用BPN或安慰剂。采用2:1比例随机分配的原因如下：

**【原文段落】**（英文原文）

> Phase 2, RCT Overview: In the 8-weeks of BPN vs. placebo, thirty subjects will be randomized (using permuted block randomization) 2:1 to receive venlafaxine XR (at the dose they reached and tolerated in the open-label lead-in) plus either BPN or placebo. The reasons for using a 2:1 random allocation include: 1) collection of more data about plasma levels of BPN and its metabolites, and 2) gaining further clinical experience with the molecule. Both of these reasons are consistent with the developmental nature of the R34 grant mechanism (the NIH grant mechanisms supporting this project). We will use independent evaluators (who are blind to treatment assignment) at the end of phase 2 for the last two assessments to determine if the participant has met response. The reason for using independent evaluators at this pivotal timepoint is that clinicians may become unblinded because they are also assessing side effects. At the beginning of phase 2, participants will be asked to review and sign the phase 2 contract (attached under other attachments in OSIRIS). This contract outlines safety precautions and directions for taking and storing the medication. This contract will be signed with all participants who are moving into phase 2. BPN will be started at 0.2 mg/d and will be titrated weekly by 0.2 mg, based on tolerability (assessed with the FIBSER) and depression severity (assessed with MADRS). The minimum target dose is 0.6 mg/d (based on our pilot work) with an allowed maximum of 1.2 mg/d. The primary outcome will be remission at the end of the 8-week period (defined by a MADRS score of 10 or lower for two consecutive weeks, as in the IRL GREY study). The first dose of buprenorphine will be taken while in the office while under the supervision of the PI, Co-I, and study perso
> …（中略）…
> ects. In our pilot work, we have not encountered ANY discontinuation symptoms during the cessation of BPN. This may be due to the relatively short duration of exposure and the very low doses used in the project. Breaking the blind: The blind will be broken for all participants at the end of phase 2.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> II期随机对照试验概述：在为期8周的BPN与安慰剂对比试验中，共有30名受试者将通过随机化分组方式（采用置换区组随机法）以2:1的比例被分配至两组，分别接受文拉法辛XR制剂（剂量为受试者在开放标签导入期能够耐受并达到的剂量），同时分别联合使用BPN或安慰剂。采用2:1比例随机分配的原因如下：
> 

## 研究 NCT03113968（32 项待处置）

### NCT03113968·条目 1：7.6 Non-Compliance (objectives_endpoints)

- 条目ID：`wref_translation_item_226bcc7a3c791e48fecd5635`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_4:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> • Inquire about the reason for withdrawal • Request the subject to return for an EOT Visit to assess AEs/SAEs, safety endpoints, outcome events, vital status • Follow-up with the subject regarding any unresolved adverse events.
> If the subject withdraws from the trial and also withdraws consent for disclosure of future information, no further evaluations should be performed and no additional data should be collected. Adequate documentation of this request should be obtained and retained in the subject’s source file. True withdrawal of consent should be subject initiated and in writing. The sponsor may retain and continue to use any data collected before withdrawal of consent. 7.8 Lost to Follow-Up
> Contact information from the patient, including an emergency contact will be obtained at the time of screening. This information will be reviewed and verified at each clinic visit and telephone contact. Patients will be considered lost to follow-up (LTFU) after the End of Treatment phase, when one of the following is met:
> • For Non-Responders in the one month Follow-Up Phase - patients will be considered LTFU after 3 attempts to contact the patient. • For Responders in the Follow-Up Phase - patients will be considered LTFU only after the Month 6 Visit, or at the end of study, whichever comes first. For each missed visit, study staff should make three attempts to contact the patient as soon as possible at various intervals. The site should access medical records, other health care professionals, institutional databases and any other means to contact the patient as allowed by their IRB. All attempts to contact the patient should be documented in the research chart and medical records. 7.9 Study Termination
> This study may be terminated or suspended at any time. If the study is terminated or suspended, the sponsor will promptly inform the investigators / institutions and PCORI.
> The IRB should be promptly informed and provided the reasons(s) for the termination or suspension by the sponsor and by the investigator / institution, as specified by the applicable regulatory requirement(s).

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> • 对于随访期首个月内无应答的患者：在尝试联系该患者3次后，即可将其判定为处于长期失访状态。 • 对于随访期内有应答的受试者：仅在第6个月的研究中心访视结束后，或研究结束时（以二者中较早发生者为准），方可将其判定为长期失访。对于每一次漏访情况，研究人员均应尽快在不同时间间隔内至少进行3次联系尝试。研究中心还应查阅病历资料、咨询其他医疗保健专业人员，并利用机构数据库及经IRB许可的其他任何方式与患者取得联系。所有与患者的联络尝试情况均须详细记录于研究病历及医疗档案中。7.9 研究终止

### NCT03113968·条目 2：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_2be552b9d609b397ea8c39c3`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_4:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：3) Males or females at least 21 years of age, but no older than 75 years of age
  - 第 4 单元译文：3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁

**【原文段落】**（英文原文）

> scheduled for screening within two weeks from the consult. 5.2 Inclusion Criteria
> Patients are eligible for the study if they meet the following inclusion criteria:
> 1) Written informed consent before any study related procedures are performed 2) Inpatients or outpatients referred by their providers for ECT treatment and eligible for ECT treatment 3) Males or females at least 21 years of age, but no older than 75 years of age 4) Meet DSM-5 criteria for a Major Depressive Episode as determined by both:
> • a clinician’s diagnostic evaluation and • confirmed by interview using the Mini International Neuropsychiatric Interview (MINI 7.0.2) 5) A current depressive episode that has lasted a minimum of two weeks 6) Meet all of the following criteria on symptom rating scales at screening:
> • Montgomery Asberg Depression Rating Scale (MADRS) score >20 • Young Mania Rating Scale (YMRS) ≤ 5 • Montreal Cognitive Assessment (MoCA) of ≥ 18 7) Have had ≥ 2 adequate trials of antidepressants/augmentation strategies during their lifetime. An adequate trial is defined as 4 weeks of a medication at minimum FDA approved dose. This will be equal to a trial rating of 3 or greater. 8) In the opinion of the investigator, the patient is willing and able to comply with scheduled visits, treatment plan, and other trial procedures for the duration of the study 5.3 Exclusion Criteria Patients must NOT meet any of the following exclusion criteria:
> 1) Meets DSM-5 criteria for bipolar disorder, schizophrenia, schizophreniform
> disorder, schizoaffective disorder, mental retardation, or pervasive development disorder 2) Meet any exclusion criteria for ECT or ketamine treatment as described in the
> clinical guidelines or according to investigator judgment 3) The patient is pregnant or breast feeding 4) The patient has a severe medical illness or severe neurological disorder 5) The patient has a known ketamine allergy or is taking any medication that may
> interact with ketamine 6) Diagnosis of major depressive disorder with psychotic features during the

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁
> 

### NCT03113968·条目 3：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_2f5b694554d88a03af65dce7`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：The screening period will be a maximum of 28 days. Randomization should occur within one week after eligibility is confirmed. After patients are enrolled they will be randomized to either ECT or ketamine therapy. Patients in the ECT arm will receive up to nine treatments over three weeks (+ two weeks). Patients in the ketamine arm will receive up to six treatments over three weeks (+ two weeks).
  - 第 1 单元译文：筛选期最长为28天。在确认受试者符合入组条件后一周内应完成随机分组。患者入选后将被随机分配至ECT治疗组或氯胺酮治疗组。接受ECT治疗的患者在三周（+两周）内最多可接受治疗九次；而氯胺酮治疗组的患者在同样的时间段内最多可接受六次治疗。

**【原文段落】**（英文原文）

> The screening period will be a maximum of 28 days. Randomization should occur within one week after eligibility is confirmed. After patients are enrolled they will be randomized to either ECT or ketamine therapy. Patients in the ECT arm will receive up to nine treatments over three weeks (+ two weeks). Patients in the ketamine arm will receive up to six treatments over three weeks (+ two weeks).
> Patients in both arms classified as responders may have three additional visits, at Month 1, Month 3, and Month 6 after the End of Treatment visit, depending on the date of enrollment relative to the end of study. Patients in both arms classified as Non-responders will receive a phone call one month after the End of Treatment visit.
> INCLUSION CRITERIA
> Key Selection Criteria

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 筛选期最长为28天。在确认受试者符合入组条件后一周内应完成随机分组。患者入选后将被随机分配至ECT治疗组或氯胺酮治疗组。接受ECT治疗的患者在三周（+两周）内最多可接受治疗九次；而氯胺酮治疗组的患者在同样的时间段内最多可接受六次治疗。
> 

### NCT03113968·条目 4：3. Study Design (objectives_endpoints)

- 条目ID：`wref_translation_item_4258568f37e1940de88ac888`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an
  - 第 1 单元译文：研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）

**【原文段落】**（英文原文）

> Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an outpatient has worsening depression that requires psychiatric hospitalization, the patient may continue in the study at investigator discretion. These patients can receive study ECT or ketamine treatments as an inpatient. 4. Outcome Measures
> To avoid potential bias, the patient assessments and the clinician assessments should be completed independently and without reference to one another. The research coordinator or clinician administering the questionnaires should not view the patient’s responses on patient rated scales. (They should, however, remind the patient to answer all questions and not leave any questions blank.) 4.1 Primary Outcome
> The primary outcome measure is the percent of responders. Treatment response is defined as a ≥ 50% decrease in QIDS-SR-16 scores from the Baseline Visit to the EOT
> visit. The QIDS-SR-16 will be administered prior to treatment according to the following schedules.
> ECT Arm The QIDS-SR-16 will be administered at certain time points during the acute treatment phase (Baseline/Visit 1, Visit 2, Visit 4, Visit 6, Visit 7, Visit 9, and EOT visit). Patients in the ECT arm who are classified as responders will complete the QIDS-SR-16 at all follow-up v
> …（中略）…
> ill be informed about the study and given a thorough explanation of risks, benefits, study procedures, and expectations. Patients interested in participation will be scheduled for a screening visit as soon as possible, but no later than 28 days from the clinical consult. Typically patients should be

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）
> 

### NCT03113968·条目 5：EXCLUSION CRITERIA (eligibility)

- 条目ID：`wref_translation_item_47a2466e95eec309e30f02b4`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> EXCLUSION CRITERIA
> 1. Meet DSM-5 criteria for bipolar disorder, schizophrenia,
> schizophreniform disorder, schizoaffective disorder, mental retardation, or pervasive developmental disorder 2. Meets any exclusion criteria for ECT or ketamine treatment as
> described in the clinical guidelines or according to investigator judgment 3. The patient is pregnant or breast feeding 4. The patient has a severe medical illness or severe neurological
> disorder 5. The patient has a known ketamine allergy or is taking a medication
> that may interact with ketamine 6. Diagnosis of major depressive disorder with psychotic features

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 排除标准： 1. 符合DSM-5中双相情感障碍、精神分裂症、分裂型精神障碍、精神分裂性情感障碍、智力发育迟滞或广泛性发育障碍的规范中文（EXCLUSION）

### NCT03113968·条目 6：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_4f21503725b870c50c2e0cff`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_4:unit_sequence_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：• Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.1.2 Month 3 Follow-Up Visit (+/- 2 weeks)
  - 第 4 单元译文：• 认知功能评估
o MoCA量表
o COWAT测试
o HVLT-R记忆测验
o Stroop色词测验
7.5.1.2 第3个月随访访视（允许前后浮动2周）

**【原文段落】**（英文原文）

> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation
> • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-MY o SMCQ o PGI-S & PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments
> o MoCA o COWAT o HVLT-R o Stroop 7.5.1.2 Month 3 Follow-Up Visit (+/- 2 weeks)
> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-MY o SMCQ o PGI-S & PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.1.3 Month 6 Follow-Up Visit (+/- 2 wee ks)
> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation
> • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-My o SMCQ o PGI-S& PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.2 Follow-Up Phone Call for Non-Responders 7.5.2.1 Month 1 Follow-Up Phone Call (+/- 2 weeks)
> • Evaluation for Adverse Events or Serious Adverse Events • Evaluation for additional ECT, ketamine, psychotropic treatment(s) performed o Update Somatic Therapies Log 
> …（中略）…
> nvestigator for safety or behavioral reasons, or the inability of the subject to comply with the protocol required schedule of study visits or procedures at a given study site. If the subject elects to discontinue participation in the study or to discontinue study treatment, the investigator should:

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> • 认知功能评估
> o MoCA量表
> o COWAT测试
> o HVLT-R记忆测验
> o Stroop色词测验
> 7.5.1.2 第3个月随访访视（允许前后浮动2周）
> 

### NCT03113968·条目 7：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_5044584a946327c24ddfc956`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
  - 译文第 1 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_1:regulatory_chinese_term_calque`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：The key exposures of this study are alternate day ECT treatment and twice a week ketamine infusion. We will conduct an intention to treat (ITT) analysis. A sensitivity analysis will be performed on the modified intention-to-treat (mITT) population defined as a randomized patient having at least one treatment and one valid QIDS- SR16 measurement during the acute treatment phase. Percent of responders is the primary outcome in this study. A responder is defined as a subject with a ≥50% decrease from baseline in the primary endpoint (QIDS-SR-16).
  - 第 1 单元译文：本研究的关键干预措施为隔日实施的ECT治疗以及每周两次的氯胺酮输注。我们将实施意向性分析（ITT）。此外，还会针对改良后的意向性治疗人群开展敏感性分析；该人群的界定标准为：经随机分组的患者在急性治疗期内至少接受过一次相关治疗，且至少有一次有效的QIDS-SR-16评分记录。本研究的主要终点为达到临床应答的受试者比例，所谓“临床应答”即指受试者的主要终点指标（QIDS-SR-16评分）较基线水平降幅≥50%。

**【原文段落】**（英文原文）

> The key exposures of this study are alternate day ECT treatment and twice a week ketamine infusion. We will conduct an intention to treat (ITT) analysis. A sensitivity analysis will be performed on the modified intention-to-treat (mITT) population defined as a randomized patient having at least one treatment and one valid QIDS- SR16 measurement during the acute treatment phase. Percent of responders is the primary outcome in this study. A responder is defined as a subject with a ≥50% decrease from baseline in the primary endpoint (QIDS-SR-16).
> Multiple imputations may be implemented to achieve completeness of the data. In an unlikely case that missing data are non-ignorable, pattern-mixture modeling will be applied. As a general principle, the statistical analysis will follow the pre-specified statistical analysis plan (SAP). The SAP will be finalized prior to the end of the study. The SAP will address how missing data will be handled. The primary outcome measure of response rate will be compared between ketamine and ECT using a chi-square test. A multivariable logistic regression model will be constructed, to account for potential heterogeneity of treatment effect caused by confounding variables. A similar analytic strategy will be applied to evaluate cognitive function and quality of life.
> Sample size The sample size justification will be for the primary outcome measure of response rate. Historical data reveal that the overall response rate as well as the respective response rate of ketamine and of ECT is around 50% – 60% on various scale measurements in patients with treatment-resistant depression. Assuming an observed difference of 10% and an acceptable difference margin of 5% with a 1-sided alpha=0.025, a sample of 400 patients (200 per group) provides 81.8% power to detect a treatment response, based on the Farrington-Manning score test of risk difference. The total sample also considers a 10% attrition rate. 10. Study Committees

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 本研究的关键干预措施为隔日实施的ECT治疗以及每周两次的氯胺酮输注。我们将实施意向性分析（ITT）。此外，还会针对改良后的意向性治疗人群开展敏感性分析；该人群的界定标准为：经随机分组的患者在急性治疗期内至少接受过一次相关治疗，且至少有一次有效的QIDS-SR-16评分记录。本研究的主要终点为达到临床应答的受试者比例，所谓“临床应答”即指受试者的主要终点指标（QIDS-SR-16评分）较基线水平降幅≥50%。
> 

### NCT03113968·条目 8：3. Study Design (objectives_endpoints)

- 条目ID：`wref_translation_item_537a9cf7cef0a8111cb23f43`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an
  - 第 1 单元译文：研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）

**【原文段落】**（英文原文）

> Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an outpatient has worsening depression that requires psychiatric hospitalization, the patient may continue in the study at investigator discretion. These patients can receive study ECT or ketamine treatments as an inpatient. 4. Outcome Measures
> To avoid potential bias, the patient assessments and the clinician assessments should be completed independently and without reference to one another. The research coordinator or clinician administering the questionnaires should not view the patient’s responses on patient rated scales. (They should, however, remind the patient to answer all questions and not leave any questions blank.) 4.1 Primary Outcome
> The primary outcome measure is the percent of responders. Treatment response is defined as a ≥ 50% decrease in QIDS-SR-16 scores from the Baseline Visit to the EOT
> visit. The QIDS-SR-16 will be administered prior to treatment according to the following schedules.
> ECT Arm The QIDS-SR-16 will be administered at certain time points during the acute treatment phase (Baseline/Visit 1, Visit 2, Visit 4, Visit 6, Visit 7, Visit 9, and EOT visit). Patients in the ECT arm who are classified as responders will complete the QIDS-SR-16 at all follow-up v
> …（中略）…
> ill be informed about the study and given a thorough explanation of risks, benefits, study procedures, and expectations. Patients interested in participation will be scheduled for a screening visit as soon as possible, but no later than 28 days from the clinical consult. Typically patients should be

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）
> 

### NCT03113968·条目 9：o BPRS (safety)

- 条目ID：`wref_translation_item_606d25c99551f0aaba87f8c1`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_4:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> • Update Medical History • Update Psychiatric Medication Log • Update somatic therapies log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Clinical Psychiatric Evaluation • Patient and Clinician Rated Behavioral Scales (to be completed at Baseline/Visit 1, Visit 2, Visit 4, Visit 6, Visit 7, and Visit 9) Prior to Treatment:
> • Patient Rated Behavioral Scales o QIDS-SR-16 (To be completed first) o GSE-MY (Not completed at Baseline/Visit 1) o SMCQ o PGI-S & PGI-I (PGI-I not completed at Baseline/Visit 1) o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o CGI-S & CGI-I (CGI-I not completed at Baseline/Visit 1)
> • Post Treatment (clinician rated) o CADSS o BPRS
> 7.3.2 Ketamine Arm
> Prior to each treatment, patients will be assessed if clinically appropriate for the treatment. Each site will follow their standard of care for evaluating patients for ketamine treatment. Each site will perform the following minimal set of assessments:
> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Clinical Psychiatric Evaluation • Patient and Clinician Rated Behavioral Scales (to be completed at every visit) Prior to Treatment:
> • Patient Rated Behavioral Scales (to be completed at every visit) o QIDS-SR-16 (To be completed first) o GSE-MY (Not completed at Baseline/Visit 1) o SMCQ o PGI-S & PGI-I (PGI-I not completed at Baseline/Visit 1) o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales (to be completed at every visit) o MADRS o CSSRS o YMRS o CGI-S & CGI-I (CGI-I not completed at Baseline/Visit 1)
> Post Treatment (clinician rated):
> o CADSS o BPRS 7.3.3 Completion and/or Early 
> …（中略）…
>  patient has worsening depression, severe psychotic symptoms, or becomes suicidal If these situations occur the patient should be scheduled for an End of Treatment Visit. The patient can decide not to continue treatment for any reason. They should be encouraged to complete an End of Treatment Visit.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 1) □ SMCQ □ PGI-S及PGI-I（基线/访视时尚未完成PGI-I评估）

### NCT03113968·条目 10：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_6e526fdbfe1857620e64328e`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
  - 译文第 1 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_1:regulatory_chinese_term_calque`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：The key exposures of this study are alternate day ECT treatment and twice a week ketamine infusion. We will conduct an intention to treat (ITT) analysis. A sensitivity analysis will be performed on the modified intention-to-treat (mITT) population defined as a randomized patient having at least one treatment and one valid QIDS- SR16 measurement during the acute treatment phase. Percent of responders is the primary outcome in this study. A responder is defined as a subject with a ≥50% decrease from baseline in the primary endpoint (QIDS-SR-16).
  - 第 1 单元译文：本研究的关键干预措施为隔日实施的ECT治疗以及每周两次的氯胺酮输注。我们将实施意向性分析（ITT）。此外，还会针对改良后的意向性治疗人群开展敏感性分析；该人群的界定标准为：经随机分组的患者在急性治疗期内至少接受过一次相关治疗，且至少有一次有效的QIDS-SR-16评分记录。本研究的主要终点为达到临床应答的受试者比例，所谓“临床应答”即指受试者的主要终点指标（QIDS-SR-16评分）较基线水平降幅≥50%。

**【原文段落】**（英文原文）

> The key exposures of this study are alternate day ECT treatment and twice a week ketamine infusion. We will conduct an intention to treat (ITT) analysis. A sensitivity analysis will be performed on the modified intention-to-treat (mITT) population defined as a randomized patient having at least one treatment and one valid QIDS- SR16 measurement during the acute treatment phase. Percent of responders is the primary outcome in this study. A responder is defined as a subject with a ≥50% decrease from baseline in the primary endpoint (QIDS-SR-16).
> Multiple imputations may be implemented to achieve completeness of the data. In an unlikely case that missing data are non-ignorable, pattern-mixture modeling will be applied. As a general principle, the statistical analysis will follow the pre-specified statistical analysis plan (SAP). The SAP will be finalized prior to the end of the study. The SAP will address how missing data will be handled. The primary outcome measure of response rate will be compared between ketamine and ECT using a chi-square test. A multivariable logistic regression model will be constructed, to account for potential heterogeneity of treatment effect caused by confounding variables. A similar analytic strategy will be applied to evaluate cognitive function and quality of life.
> Sample size The sample size justification will be for the primary outcome measure of response rate. Historical data reveal that the overall response rate as well as the respective response rate of ketamine and of ECT is around 50% – 60% on various scale measurements in patients with treatment-resistant depression. Assuming an observed difference of 10% and an acceptable difference margin of 5% with a 1-sided alpha=0.025, a sample of 400 patients (200 per group) provides 81.8% power to detect a treatment response, based on the Farrington-Manning score test of risk difference. The total sample also considers a 10% attrition rate. 10. Study Committees

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 本研究的关键干预措施为隔日实施的ECT治疗以及每周两次的氯胺酮输注。我们将实施意向性分析（ITT）。此外，还会针对改良后的意向性治疗人群开展敏感性分析；该人群的界定标准为：经随机分组的患者在急性治疗期内至少接受过一次相关治疗，且至少有一次有效的QIDS-SR-16评分记录。本研究的主要终点为达到临床应答的受试者比例，所谓“临床应答”即指受试者的主要终点指标（QIDS-SR-16评分）较基线水平降幅≥50%。
> 

### NCT03113968·条目 11：Unlabelled section (eligibility) (eligibility)

- 条目ID：`wref_translation_item_73777509b5300e48b4caf1e3`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：The screening period will be a maximum of 28 days. Randomization should occur within one week after eligibility is confirmed. After patients are enrolled they will be randomized to either ECT or ketamine therapy. Patients in the ECT arm will receive up to nine treatments over three weeks (+ two weeks). Patients in the ketamine arm will receive up to six treatments over three weeks (+ two weeks).
  - 第 1 单元译文：筛选期最长为28天。在确认受试者符合入组条件后一周内应完成随机分组。患者入选后将被随机分配至ECT治疗组或氯胺酮治疗组。接受ECT治疗的患者在三周（+两周）内最多可接受治疗九次；而氯胺酮治疗组的患者在同样的时间段内最多可接受六次治疗。

**【原文段落】**（英文原文）

> The screening period will be a maximum of 28 days. Randomization should occur within one week after eligibility is confirmed. After patients are enrolled they will be randomized to either ECT or ketamine therapy. Patients in the ECT arm will receive up to nine treatments over three weeks (+ two weeks). Patients in the ketamine arm will receive up to six treatments over three weeks (+ two weeks).
> Patients in both arms classified as responders may have three additional visits, at Month 1, Month 3, and Month 6 after the End of Treatment visit, depending on the date of enrollment relative to the end of study. Patients in both arms classified as Non-responders will receive a phone call one month after the End of Treatment visit.
> INCLUSION CRITERIA
> Key Selection Criteria

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 筛选期最长为28天。在确认受试者符合入组条件后一周内应完成随机分组。患者入选后将被随机分配至ECT治疗组或氯胺酮治疗组。接受ECT治疗的患者在三周（+两周）内最多可接受治疗九次；而氯胺酮治疗组的患者在同样的时间段内最多可接受六次治疗。
> 

### NCT03113968·条目 12：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_7484409324cbce0d43843115`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_4:unit_sequence_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：• Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.1.2 Month 3 Follow-Up Visit (+/- 2 weeks)
  - 第 4 单元译文：• 认知功能评估
o MoCA量表
o COWAT测试
o HVLT-R记忆测验
o Stroop色词测验
7.5.1.2 第3个月随访访视（允许前后浮动2周）

**【原文段落】**（英文原文）

> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation
> • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-MY o SMCQ o PGI-S & PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments
> o MoCA o COWAT o HVLT-R o Stroop 7.5.1.2 Month 3 Follow-Up Visit (+/- 2 weeks)
> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-MY o SMCQ o PGI-S & PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.1.3 Month 6 Follow-Up Visit (+/- 2 wee ks)
> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation
> • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-My o SMCQ o PGI-S& PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.2 Follow-Up Phone Call for Non-Responders 7.5.2.1 Month 1 Follow-Up Phone Call (+/- 2 weeks)
> • Evaluation for Adverse Events or Serious Adverse Events • Evaluation for additional ECT, ketamine, psychotropic treatment(s) performed o Update Somatic Therapies Log 
> …（中略）…
> nvestigator for safety or behavioral reasons, or the inability of the subject to comply with the protocol required schedule of study visits or procedures at a given study site. If the subject elects to discontinue participation in the study or to discontinue study treatment, the investigator should:

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> • 认知功能评估
> o MoCA量表
> o COWAT测试
> o HVLT-R记忆测验
> o Stroop色词测验
> 7.5.1.2 第3个月随访访视（允许前后浮动2周）
> 

### NCT03113968·条目 13：3. Study Design (objectives_endpoints)

- 条目ID：`wref_translation_item_752fc1d1b0ffe2a17765a362`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an
  - 第 1 单元译文：研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）

**【原文段落】**（英文原文）

> Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an outpatient has worsening depression that requires psychiatric hospitalization, the patient may continue in the study at investigator discretion. These patients can receive study ECT or ketamine treatments as an inpatient. 4. Outcome Measures
> To avoid potential bias, the patient assessments and the clinician assessments should be completed independently and without reference to one another. The research coordinator or clinician administering the questionnaires should not view the patient’s responses on patient rated scales. (They should, however, remind the patient to answer all questions and not leave any questions blank.) 4.1 Primary Outcome
> The primary outcome measure is the percent of responders. Treatment response is defined as a ≥ 50% decrease in QIDS-SR-16 scores from the Baseline Visit to the EOT
> visit. The QIDS-SR-16 will be administered prior to treatment according to the following schedules.
> ECT Arm The QIDS-SR-16 will be administered at certain time points during the acute treatment phase (Baseline/Visit 1, Visit 2, Visit 4, Visit 6, Visit 7, Visit 9, and EOT visit). Patients in the ECT arm who are classified as responders will complete the QIDS-SR-16 at all follow-up v
> …（中略）…
> ill be informed about the study and given a thorough explanation of risks, benefits, study procedures, and expectations. Patients interested in participation will be scheduled for a screening visit as soon as possible, but no later than 28 days from the clinical consult. Typically patients should be

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）
> 

### NCT03113968·条目 14：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_790bbe176a0650bf9ed77815`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_4:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：3) Males or females at least 21 years of age, but no older than 75 years of age
  - 第 4 单元译文：3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁

**【原文段落】**（英文原文）

> scheduled for screening within two weeks from the consult. 5.2 Inclusion Criteria
> Patients are eligible for the study if they meet the following inclusion criteria:
> 1) Written informed consent before any study related procedures are performed 2) Inpatients or outpatients referred by their providers for ECT treatment and eligible for ECT treatment 3) Males or females at least 21 years of age, but no older than 75 years of age 4) Meet DSM-5 criteria for a Major Depressive Episode as determined by both:
> • a clinician’s diagnostic evaluation and • confirmed by interview using the Mini International Neuropsychiatric Interview (MINI 7.0.2) 5) A current depressive episode that has lasted a minimum of two weeks 6) Meet all of the following criteria on symptom rating scales at screening:
> • Montgomery Asberg Depression Rating Scale (MADRS) score >20 • Young Mania Rating Scale (YMRS) ≤ 5 • Montreal Cognitive Assessment (MoCA) of ≥ 18 7) Have had ≥ 2 adequate trials of antidepressants/augmentation strategies during their lifetime. An adequate trial is defined as 4 weeks of a medication at minimum FDA approved dose. This will be equal to a trial rating of 3 or greater. 8) In the opinion of the investigator, the patient is willing and able to comply with scheduled visits, treatment plan, and other trial procedures for the duration of the study 5.3 Exclusion Criteria Patients must NOT meet any of the following exclusion criteria:
> 1) Meets DSM-5 criteria for bipolar disorder, schizophrenia, schizophreniform
> disorder, schizoaffective disorder, mental retardation, or pervasive development disorder 2) Meet any exclusion criteria for ECT or ketamine treatment as described in the
> clinical guidelines or according to investigator judgment 3) The patient is pregnant or breast feeding 4) The patient has a severe medical illness or severe neurological disorder 5) The patient has a known ketamine allergy or is taking any medication that may
> interact with ketamine 6) Diagnosis of major depressive disorder with psychotic features during the

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁
> 

### NCT03113968·条目 15：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_822eb2840d4b6879bf0f0b14`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_4:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：3) Males or females at least 21 years of age, but no older than 75 years of age
  - 第 4 单元译文：3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁

**【原文段落】**（英文原文）

> scheduled for screening within two weeks from the consult. 5.2 Inclusion Criteria
> Patients are eligible for the study if they meet the following inclusion criteria:
> 1) Written informed consent before any study related procedures are performed 2) Inpatients or outpatients referred by their providers for ECT treatment and eligible for ECT treatment 3) Males or females at least 21 years of age, but no older than 75 years of age 4) Meet DSM-5 criteria for a Major Depressive Episode as determined by both:
> • a clinician’s diagnostic evaluation and • confirmed by interview using the Mini International Neuropsychiatric Interview (MINI 7.0.2) 5) A current depressive episode that has lasted a minimum of two weeks 6) Meet all of the following criteria on symptom rating scales at screening:
> • Montgomery Asberg Depression Rating Scale (MADRS) score >20 • Young Mania Rating Scale (YMRS) ≤ 5 • Montreal Cognitive Assessment (MoCA) of ≥ 18 7) Have had ≥ 2 adequate trials of antidepressants/augmentation strategies during their lifetime. An adequate trial is defined as 4 weeks of a medication at minimum FDA approved dose. This will be equal to a trial rating of 3 or greater. 8) In the opinion of the investigator, the patient is willing and able to comply with scheduled visits, treatment plan, and other trial procedures for the duration of the study 5.3 Exclusion Criteria Patients must NOT meet any of the following exclusion criteria:
> 1) Meets DSM-5 criteria for bipolar disorder, schizophrenia, schizophreniform
> disorder, schizoaffective disorder, mental retardation, or pervasive development disorder 2) Meet any exclusion criteria for ECT or ketamine treatment as described in the
> clinical guidelines or according to investigator judgment 3) The patient is pregnant or breast feeding 4) The patient has a severe medical illness or severe neurological disorder 5) The patient has a known ketamine allergy or is taking any medication that may
> interact with ketamine 6) Diagnosis of major depressive disorder with psychotic features during the

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁
> 

### NCT03113968·条目 16：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_9612661aa248fb5fbd42de7e`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_4:unit_sequence_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：• Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.1.2 Month 3 Follow-Up Visit (+/- 2 weeks)
  - 第 4 单元译文：• 认知功能评估
o MoCA量表
o COWAT测试
o HVLT-R记忆测验
o Stroop色词测验
7.5.1.2 第3个月随访访视（允许前后浮动2周）

**【原文段落】**（英文原文）

> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation
> • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-MY o SMCQ o PGI-S & PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments
> o MoCA o COWAT o HVLT-R o Stroop 7.5.1.2 Month 3 Follow-Up Visit (+/- 2 weeks)
> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-MY o SMCQ o PGI-S & PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.1.3 Month 6 Follow-Up Visit (+/- 2 wee ks)
> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Psychiatric Evaluation
> • Patient Rated Behavioral Scales o QIDS-SR-16 (to be completed first) o GSE-My o SMCQ o PGI-S& PGI-I o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o BPRS o CGI-S & CGI-I o CADSS
> • Cognitive Assessments o MoCA o COWAT o HVLT-R o Stroop 7.5.2 Follow-Up Phone Call for Non-Responders 7.5.2.1 Month 1 Follow-Up Phone Call (+/- 2 weeks)
> • Evaluation for Adverse Events or Serious Adverse Events • Evaluation for additional ECT, ketamine, psychotropic treatment(s) performed o Update Somatic Therapies Log 
> …（中略）…
> nvestigator for safety or behavioral reasons, or the inability of the subject to comply with the protocol required schedule of study visits or procedures at a given study site. If the subject elects to discontinue participation in the study or to discontinue study treatment, the investigator should:

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> • 认知功能评估
> o MoCA量表
> o COWAT测试
> o HVLT-R记忆测验
> o Stroop色词测验
> 7.5.1.2 第3个月随访访视（允许前后浮动2周）
> 

### NCT03113968·条目 17：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 3

- 条目ID：`wref_translation_item_9b88c70c6fa07e65f55206ed`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 6 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_6:numeric_tokens_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 6 单元原文：Psychiatry. 2007;68 Suppl8:17-25.
  - 第 6 单元译文：《精神病学》杂志，2007年；第68卷增刊8：17-25页。

**【原文段落】**（英文原文）

> and longer-term outcomes in depressed outpatients requiring one or several treatment steps: a STAR*D report. American Journal of Psychiatry. 2006;163(11):1905-17. 5. Trivedi MH, Rush AJ, Wisniewski SR, Nierenberg AA, Warden D, Ritz L, et al. Evaluation
> of outcomes with citalopram for depression using measurement-based care in STAR*D: implications for clinical practice. American Journal of Psychiatry. 2006;163(1):28-40. 6. Mrazek DA, Hornberger JC, Altar CA, Degtiar I. A Review of the Clinical, Economic, and
> Societal Burden of Treatment-Resistant Depression: 1996-2013. Psychiatric Services. 2014;65(8):977-87. 7. Nemeroff CB. Prevalence and management of treatment-resistant depression. J Clin
> Psychiatry. 2007;68 Suppl8:17-25. 8. Crown WH, Finkelstein S, Berndt ER, Ling D, Poret AW, Rush AJ, et al. The impact of
> treatment-resistant depression on health care utilization and costs. The Journal of Clinical Psychiatry. 2002;63(11);963-71. 9. Kellner CH, Greenberg RM, Murrough JW, Bryson EO, Briggs MC, Pasculli RM. ECT in

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 《精神病学》杂志，2007年；第68卷增刊8：17-25页。
> 

### NCT03113968·条目 18：3. Study Design (objectives_endpoints)

- 条目ID：`wref_translation_item_9c242d8070189c1360587f6f`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an
  - 第 1 单元译文：研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）

**【原文段落】**（英文原文）

> Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an outpatient has worsening depression that requires psychiatric hospitalization, the patient may continue in the study at investigator discretion. These patients can receive study ECT or ketamine treatments as an inpatient. 4. Outcome Measures
> To avoid potential bias, the patient assessments and the clinician assessments should be completed independently and without reference to one another. The research coordinator or clinician administering the questionnaires should not view the patient’s responses on patient rated scales. (They should, however, remind the patient to answer all questions and not leave any questions blank.) 4.1 Primary Outcome
> The primary outcome measure is the percent of responders. Treatment response is defined as a ≥ 50% decrease in QIDS-SR-16 scores from the Baseline Visit to the EOT
> visit. The QIDS-SR-16 will be administered prior to treatment according to the following schedules.
> ECT Arm The QIDS-SR-16 will be administered at certain time points during the acute treatment phase (Baseline/Visit 1, Visit 2, Visit 4, Visit 6, Visit 7, Visit 9, and EOT visit). Patients in the ECT arm who are classified as responders will complete the QIDS-SR-16 at all follow-up v
> …（中略）…
> ill be informed about the study and given a thorough explanation of risks, benefits, study procedures, and expectations. Patients interested in participation will be scheduled for a screening visit as soon as possible, but no later than 28 days from the clinical consult. Typically patients should be

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）
> 

### NCT03113968·条目 19：Unlabelled section (safety) (safety) · 3

- 条目ID：`wref_translation_item_9f476a3ec78364df00b73786`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44.
  - 第 1 单元译文：难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。

**【原文段落】**（英文原文）

> Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44. 10. The UKECTRG. Efficacy and safety of electroconvulsive therapy in depressive disorders: a
> systematic review and meta-analysis. The Lancet. 2003;361(9360):799-808. 11. Lisanby SH. Electroconvulsive Therapy for Depression. New England Journal of Medicine.
> 2007;357(19):1939-45. 12. Golden, C. J., & Freshwater, S. M. (1978). Stroop color and word test. 13. Blair, J. R., & Spreen, O. (1989). Predicting premorbid IQ: a revision of the National Adult
> Reading Test. The Clinical Neuropsychologist, 3(2), 129-136. 14. aan het Rot M, Collins KA, Murrough JA, Perez AM, Reich DL, Charney DS, et al. Safety
> and efficacy of repeated-dose intravenous ketamine for treatment-resistant depression. Biological psychiatry. 2010;67(2):139-45. 15. Newport DJ, Carpenter LL, McDonald WM, Potash JB, Tohen M, Nemeroff CB. Ketamine
> and Other NMDA Antagonists: Early Clinical Trials and Possible Mechanisms in Depression. The American journal of psychiatry. 2015;172(10):950-66. 16. van Waarde JA, van Oudheusden LJ, Verway B, Giltay EJ, van der Mast RC. European
> archives of psychiatry and clinical neuroscience. 2013 Mar;263(2):167-75. Doi: 10.1007/s00406-012-0342-7. 17. Lapidus KA, Kellner CH. Journal of ECT. 2011 Sep;27(3):244-6. Doi:
> 10.1097/YCT.0b013e31820059e1.
> 16. Appendix
> | Table 1 Outcome Measures and Scales | | |
> | MEASURE | NAME | DESCRIPTION |
> | DIAGNOSTIC INTERVIEW | | |
> | MINI 7.0.2 | Mini Neuropsychiatric Interview | Diagnostic interview used to determine DSM-5 diagnosis (30 mins) |
> | PATIENT RATED SCALES | | |
> | QIDS-SR-16 (Primary Outcome Measure) | Quick Inventory of Depressive Symptoms | Self-report of depressive symptoms based on DSM diagnostic criteria (10 mins) |
> | GSE-My | Global Self Evaluation 
> …（中略）…
>  | | |
> | MADRS | X | X | X |
> | CSSRS | X | X | X |
> | YMRS | X | X | X |
> | BPRS | X | X | X |
> | CGI-S & CGI-I* | X | X | X |
> | CADSS | X | X | X |
> | Cognitive Assessments | | | |
> | MoCA | X | X | X |
> | COWAT | X | X | X |
> | HVLT-R | X | X | X |
> | Stroop | X | X | X |
> *To be performed by psychiatrist.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。
> 

### NCT03113968·条目 20：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 3

- 条目ID：`wref_translation_item_a38e118aa47a4850c89a61db`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 6 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_6:numeric_tokens_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 6 单元原文：Psychiatry. 2007;68 Suppl8:17-25.
  - 第 6 单元译文：《精神病学》杂志，2007年；第68卷增刊8：17-25页。

**【原文段落】**（英文原文）

> and longer-term outcomes in depressed outpatients requiring one or several treatment steps: a STAR*D report. American Journal of Psychiatry. 2006;163(11):1905-17. 5. Trivedi MH, Rush AJ, Wisniewski SR, Nierenberg AA, Warden D, Ritz L, et al. Evaluation
> of outcomes with citalopram for depression using measurement-based care in STAR*D: implications for clinical practice. American Journal of Psychiatry. 2006;163(1):28-40. 6. Mrazek DA, Hornberger JC, Altar CA, Degtiar I. A Review of the Clinical, Economic, and
> Societal Burden of Treatment-Resistant Depression: 1996-2013. Psychiatric Services. 2014;65(8):977-87. 7. Nemeroff CB. Prevalence and management of treatment-resistant depression. J Clin
> Psychiatry. 2007;68 Suppl8:17-25. 8. Crown WH, Finkelstein S, Berndt ER, Ling D, Poret AW, Rush AJ, et al. The impact of
> treatment-resistant depression on health care utilization and costs. The Journal of Clinical Psychiatry. 2002;63(11);963-71. 9. Kellner CH, Greenberg RM, Murrough JW, Bryson EO, Briggs MC, Pasculli RM. ECT in

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 《精神病学》杂志，2007年；第68卷增刊8：17-25页。
> 

### NCT03113968·条目 21：Unlabelled section (safety) (safety) · 3

- 条目ID：`wref_translation_item_a70f8f96a36e0563a15b0fe5`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44.
  - 第 1 单元译文：难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。

**【原文段落】**（英文原文）

> Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44. 10. The UKECTRG. Efficacy and safety of electroconvulsive therapy in depressive disorders: a
> systematic review and meta-analysis. The Lancet. 2003;361(9360):799-808. 11. Lisanby SH. Electroconvulsive Therapy for Depression. New England Journal of Medicine.
> 2007;357(19):1939-45. 12. Golden, C. J., & Freshwater, S. M. (1978). Stroop color and word test. 13. Blair, J. R., & Spreen, O. (1989). Predicting premorbid IQ: a revision of the National Adult
> Reading Test. The Clinical Neuropsychologist, 3(2), 129-136. 14. aan het Rot M, Collins KA, Murrough JA, Perez AM, Reich DL, Charney DS, et al. Safety
> and efficacy of repeated-dose intravenous ketamine for treatment-resistant depression. Biological psychiatry. 2010;67(2):139-45. 15. Newport DJ, Carpenter LL, McDonald WM, Potash JB, Tohen M, Nemeroff CB. Ketamine
> and Other NMDA Antagonists: Early Clinical Trials and Possible Mechanisms in Depression. The American journal of psychiatry. 2015;172(10):950-66. 16. van Waarde JA, van Oudheusden LJ, Verway B, Giltay EJ, van der Mast RC. European
> archives of psychiatry and clinical neuroscience. 2013 Mar;263(2):167-75. Doi: 10.1007/s00406-012-0342-7. 17. Lapidus KA, Kellner CH. Journal of ECT. 2011 Sep;27(3):244-6. Doi:
> 10.1097/YCT.0b013e31820059e1.
> 16. Appendix
> | Table 1 Outcome Measures and Scales | | |
> | MEASURE | NAME | DESCRIPTION |
> | DIAGNOSTIC INTERVIEW | | |
> | MINI 7.0.2 | Mini Neuropsychiatric Interview | Diagnostic interview used to determine DSM-5 diagnosis (30 mins) |
> | PATIENT RATED SCALES | | |
> | QIDS-SR-16 (Primary Outcome Measure) | Quick Inventory of Depressive Symptoms | Self-report of depressive symptoms based on DSM diagnostic criteria (10 mins) |
> | GSE-My | Global Self Evaluation 
> …（中略）…
>  | | |
> | MADRS | X | X | X |
> | CSSRS | X | X | X |
> | YMRS | X | X | X |
> | BPRS | X | X | X |
> | CGI-S & CGI-I* | X | X | X |
> | CADSS | X | X | X |
> | Cognitive Assessments | | | |
> | MoCA | X | X | X |
> | COWAT | X | X | X |
> | HVLT-R | X | X | X |
> | Stroop | X | X | X |
> *To be performed by psychiatrist.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。
> 

### NCT03113968·条目 22：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_aa8a6038bfe85a78b9c8a229`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_4:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：3) Males or females at least 21 years of age, but no older than 75 years of age
  - 第 4 单元译文：3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁

**【原文段落】**（英文原文）

> scheduled for screening within two weeks from the consult. 5.2 Inclusion Criteria
> Patients are eligible for the study if they meet the following inclusion criteria:
> 1) Written informed consent before any study related procedures are performed 2) Inpatients or outpatients referred by their providers for ECT treatment and eligible for ECT treatment 3) Males or females at least 21 years of age, but no older than 75 years of age 4) Meet DSM-5 criteria for a Major Depressive Episode as determined by both:
> • a clinician’s diagnostic evaluation and • confirmed by interview using the Mini International Neuropsychiatric Interview (MINI 7.0.2) 5) A current depressive episode that has lasted a minimum of two weeks 6) Meet all of the following criteria on symptom rating scales at screening:
> • Montgomery Asberg Depression Rating Scale (MADRS) score >20 • Young Mania Rating Scale (YMRS) ≤ 5 • Montreal Cognitive Assessment (MoCA) of ≥ 18 7) Have had ≥ 2 adequate trials of antidepressants/augmentation strategies during their lifetime. An adequate trial is defined as 4 weeks of a medication at minimum FDA approved dose. This will be equal to a trial rating of 3 or greater. 8) In the opinion of the investigator, the patient is willing and able to comply with scheduled visits, treatment plan, and other trial procedures for the duration of the study 5.3 Exclusion Criteria Patients must NOT meet any of the following exclusion criteria:
> 1) Meets DSM-5 criteria for bipolar disorder, schizophrenia, schizophreniform
> disorder, schizoaffective disorder, mental retardation, or pervasive development disorder 2) Meet any exclusion criteria for ECT or ketamine treatment as described in the
> clinical guidelines or according to investigator judgment 3) The patient is pregnant or breast feeding 4) The patient has a severe medical illness or severe neurological disorder 5) The patient has a known ketamine allergy or is taking any medication that may
> interact with ketamine 6) Diagnosis of major depressive disorder with psychotic features during the

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁
> 

### NCT03113968·条目 23：Unlabelled section (safety) (safety) · 3

- 条目ID：`wref_translation_item_ab09b73e8f441f5772e57f35`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44.
  - 第 1 单元译文：难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。

**【原文段落】**（英文原文）

> Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44. 10. The UKECTRG. Efficacy and safety of electroconvulsive therapy in depressive disorders: a
> systematic review and meta-analysis. The Lancet. 2003;361(9360):799-808. 11. Lisanby SH. Electroconvulsive Therapy for Depression. New England Journal of Medicine.
> 2007;357(19):1939-45. 12. Golden, C. J., & Freshwater, S. M. (1978). Stroop color and word test. 13. Blair, J. R., & Spreen, O. (1989). Predicting premorbid IQ: a revision of the National Adult
> Reading Test. The Clinical Neuropsychologist, 3(2), 129-136. 14. aan het Rot M, Collins KA, Murrough JA, Perez AM, Reich DL, Charney DS, et al. Safety
> and efficacy of repeated-dose intravenous ketamine for treatment-resistant depression. Biological psychiatry. 2010;67(2):139-45. 15. Newport DJ, Carpenter LL, McDonald WM, Potash JB, Tohen M, Nemeroff CB. Ketamine
> and Other NMDA Antagonists: Early Clinical Trials and Possible Mechanisms in Depression. The American journal of psychiatry. 2015;172(10):950-66. 16. van Waarde JA, van Oudheusden LJ, Verway B, Giltay EJ, van der Mast RC. European
> archives of psychiatry and clinical neuroscience. 2013 Mar;263(2):167-75. Doi: 10.1007/s00406-012-0342-7. 17. Lapidus KA, Kellner CH. Journal of ECT. 2011 Sep;27(3):244-6. Doi:
> 10.1097/YCT.0b013e31820059e1.
> 16. Appendix
> | Table 1 Outcome Measures and Scales | | |
> | MEASURE | NAME | DESCRIPTION |
> | DIAGNOSTIC INTERVIEW | | |
> | MINI 7.0.2 | Mini Neuropsychiatric Interview | Diagnostic interview used to determine DSM-5 diagnosis (30 mins) |
> | PATIENT RATED SCALES | | |
> | QIDS-SR-16 (Primary Outcome Measure) | Quick Inventory of Depressive Symptoms | Self-report of depressive symptoms based on DSM diagnostic criteria (10 mins) |
> | GSE-My | Global Self Evaluation 
> …（中略）…
>  | | |
> | MADRS | X | X | X |
> | CSSRS | X | X | X |
> | YMRS | X | X | X |
> | BPRS | X | X | X |
> | CGI-S & CGI-I* | X | X | X |
> | CADSS | X | X | X |
> | Cognitive Assessments | | | |
> | MoCA | X | X | X |
> | COWAT | X | X | X |
> | HVLT-R | X | X | X |
> | Stroop | X | X | X |
> *To be performed by psychiatrist.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。
> 

### NCT03113968·条目 24：Unlabelled section (objectives_endpoints) (objectives_endpoints)

- 条目ID：`wref_translation_item_b180eca6f85c9f5b726f669f`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_4:numeric_tokens_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：2.18.2022
  - 第 4 单元译文：2022年2月18日

**【原文段落】**（英文原文）

> Sponsor: Cleveland Clinic Foundation Funding Agency: PCORI (Patient Centered Outcomes Research Institute) Principal Investigator: Amit Anand, MD ClinicalTrials.gov Identifier: NCT03113968
> Protocol V 3.0 02 Feb 2017 Protocol V4.0 06 Apr 2017 Protocol V5.0 20 Jul 2018 Protocol V6.0 28 Jun 2019 Protocol V7.0 16 Feb 2022
> This investigational protocol contains confidential information for use by the principal investigators and their designated representatives participating in this clinical investigation. It should be held confidential and maintained in a secure location. It should not be copied or made available for review by any unauthorized person or firm.
> 2.18.2022
> Signature Page Study Title: ELEKT-D : Electroconvulsive therapy (ECT) vs. ketamine in patients with treatment resistant depression (TRD) Version date: 16Feb2022 Protocol Version: 7.0 I, the undersigned, have read and approve this protocol and agree on its contents. It is confirmed that the information and guidance given in this protocol complies with scientific principles, the guidelines of Good Clinical Practice, the Declaration of Helsinki in the latest relevant version, and the applicable legal and regulatory requirements. Principal Investigator Signature Amit Anand, MD Date

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 2022年2月18日
> 

### NCT03113968·条目 25：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_bb7c28acf28b195efba2a1b5`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_4:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：3) Males or females at least 21 years of age, but no older than 75 years of age
  - 第 4 单元译文：3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁

**【原文段落】**（英文原文）

> scheduled for screening within two weeks from the consult. 5.2 Inclusion Criteria
> Patients are eligible for the study if they meet the following inclusion criteria:
> 1) Written informed consent before any study related procedures are performed 2) Inpatients or outpatients referred by their providers for ECT treatment and eligible for ECT treatment 3) Males or females at least 21 years of age, but no older than 75 years of age 4) Meet DSM-5 criteria for a Major Depressive Episode as determined by both:
> • a clinician’s diagnostic evaluation and • confirmed by interview using the Mini International Neuropsychiatric Interview (MINI 7.0.2) 5) A current depressive episode that has lasted a minimum of two weeks 6) Meet all of the following criteria on symptom rating scales at screening:
> • Montgomery Asberg Depression Rating Scale (MADRS) score >20 • Young Mania Rating Scale (YMRS) ≤ 5 • Montreal Cognitive Assessment (MoCA) of ≥ 18 7) Have had ≥ 2 adequate trials of antidepressants/augmentation strategies during their lifetime. An adequate trial is defined as 4 weeks of a medication at minimum FDA approved dose. This will be equal to a trial rating of 3 or greater. 8) In the opinion of the investigator, the patient is willing and able to comply with scheduled visits, treatment plan, and other trial procedures for the duration of the study 5.3 Exclusion Criteria Patients must NOT meet any of the following exclusion criteria:
> 1) Meets DSM-5 criteria for bipolar disorder, schizophrenia, schizophreniform
> disorder, schizoaffective disorder, mental retardation, or pervasive development disorder 2) Meet any exclusion criteria for ECT or ketamine treatment as described in the
> clinical guidelines or according to investigator judgment 3) The patient is pregnant or breast feeding 4) The patient has a severe medical illness or severe neurological disorder 5) The patient has a known ketamine allergy or is taking any medication that may
> interact with ketamine 6) Diagnosis of major depressive disorder with psychotic features during the

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁
> 

### NCT03113968·条目 26：EXCLUSION CRITERIA (eligibility)

- 条目ID：`wref_translation_item_be26b658d1ac5230f0a40bfc`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）

**【原文段落】**（英文原文）

> EXCLUSION CRITERIA
> 1. Meet DSM-5 criteria for bipolar disorder, schizophrenia,
> schizophreniform disorder, schizoaffective disorder, mental retardation, or pervasive developmental disorder 2. Meets any exclusion criteria for ECT or ketamine treatment as
> described in the clinical guidelines or according to investigator judgment 3. The patient is pregnant or breast feeding 4. The patient has a severe medical illness or severe neurological
> disorder 5. The patient has a known ketamine allergy or is taking a medication
> that may interact with ketamine 6. Diagnosis of major depressive disorder with psychotic features

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 排除标准： 1. 符合DSM-5中双相情感障碍、精神分裂症、分裂型精神障碍、精神分裂性情感障碍、智力发育迟滞或广泛性发育障碍的规范中文（EXCLUSION）

### NCT03113968·条目 27：Unlabelled section (eligibility) (eligibility) · 2

- 条目ID：`wref_translation_item_be92fed6bdb0a93b19299916`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_4:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 4 单元原文：3) Males or females at least 21 years of age, but no older than 75 years of age
  - 第 4 单元译文：3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁

**【原文段落】**（英文原文）

> scheduled for screening within two weeks from the consult. 5.2 Inclusion Criteria
> Patients are eligible for the study if they meet the following inclusion criteria:
> 1) Written informed consent before any study related procedures are performed 2) Inpatients or outpatients referred by their providers for ECT treatment and eligible for ECT treatment 3) Males or females at least 21 years of age, but no older than 75 years of age 4) Meet DSM-5 criteria for a Major Depressive Episode as determined by both:
> • a clinician’s diagnostic evaluation and • confirmed by interview using the Mini International Neuropsychiatric Interview (MINI 7.0.2) 5) A current depressive episode that has lasted a minimum of two weeks 6) Meet all of the following criteria on symptom rating scales at screening:
> • Montgomery Asberg Depression Rating Scale (MADRS) score >20 • Young Mania Rating Scale (YMRS) ≤ 5 • Montreal Cognitive Assessment (MoCA) of ≥ 18 7) Have had ≥ 2 adequate trials of antidepressants/augmentation strategies during their lifetime. An adequate trial is defined as 4 weeks of a medication at minimum FDA approved dose. This will be equal to a trial rating of 3 or greater. 8) In the opinion of the investigator, the patient is willing and able to comply with scheduled visits, treatment plan, and other trial procedures for the duration of the study 5.3 Exclusion Criteria Patients must NOT meet any of the following exclusion criteria:
> 1) Meets DSM-5 criteria for bipolar disorder, schizophrenia, schizophreniform
> disorder, schizoaffective disorder, mental retardation, or pervasive development disorder 2) Meet any exclusion criteria for ECT or ketamine treatment as described in the
> clinical guidelines or according to investigator judgment 3) The patient is pregnant or breast feeding 4) The patient has a severe medical illness or severe neurological disorder 5) The patient has a known ketamine allergy or is taking any medication that may
> interact with ketamine 6) Diagnosis of major depressive disorder with psychotic features during the

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 3) 男性或女性，年龄需为21周岁及以上且不得超过75周岁
> 

### NCT03113968·条目 28：Unlabelled section (safety) (safety) · 3

- 条目ID：`wref_translation_item_c43a8e05246e563ee52f6291`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44.
  - 第 1 单元译文：难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。

**【原文段落】**（英文原文）

> Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44. 10. The UKECTRG. Efficacy and safety of electroconvulsive therapy in depressive disorders: a
> systematic review and meta-analysis. The Lancet. 2003;361(9360):799-808. 11. Lisanby SH. Electroconvulsive Therapy for Depression. New England Journal of Medicine.
> 2007;357(19):1939-45. 12. Golden, C. J., & Freshwater, S. M. (1978). Stroop color and word test. 13. Blair, J. R., & Spreen, O. (1989). Predicting premorbid IQ: a revision of the National Adult
> Reading Test. The Clinical Neuropsychologist, 3(2), 129-136. 14. aan het Rot M, Collins KA, Murrough JA, Perez AM, Reich DL, Charney DS, et al. Safety
> and efficacy of repeated-dose intravenous ketamine for treatment-resistant depression. Biological psychiatry. 2010;67(2):139-45. 15. Newport DJ, Carpenter LL, McDonald WM, Potash JB, Tohen M, Nemeroff CB. Ketamine
> and Other NMDA Antagonists: Early Clinical Trials and Possible Mechanisms in Depression. The American journal of psychiatry. 2015;172(10):950-66. 16. van Waarde JA, van Oudheusden LJ, Verway B, Giltay EJ, van der Mast RC. European
> archives of psychiatry and clinical neuroscience. 2013 Mar;263(2):167-75. Doi: 10.1007/s00406-012-0342-7. 17. Lapidus KA, Kellner CH. Journal of ECT. 2011 Sep;27(3):244-6. Doi:
> 10.1097/YCT.0b013e31820059e1.
> 16. Appendix
> | Table 1 Outcome Measures and Scales | | |
> | MEASURE | NAME | DESCRIPTION |
> | DIAGNOSTIC INTERVIEW | | |
> | MINI 7.0.2 | Mini Neuropsychiatric Interview | Diagnostic interview used to determine DSM-5 diagnosis (30 mins) |
> | PATIENT RATED SCALES | | |
> | QIDS-SR-16 (Primary Outcome Measure) | Quick Inventory of Depressive Symptoms | Self-report of depressive symptoms based on DSM diagnostic criteria (10 mins) |
> | GSE-My | Global Self Evaluation 
> …（中略）…
>  | | |
> | MADRS | X | X | X |
> | CSSRS | X | X | X |
> | YMRS | X | X | X |
> | BPRS | X | X | X |
> | CGI-S & CGI-I* | X | X | X |
> | CADSS | X | X | X |
> | Cognitive Assessments | | | |
> | MoCA | X | X | X |
> | COWAT | X | X | X |
> | HVLT-R | X | X | X |
> | Stroop | X | X | X |
> *To be performed by psychiatrist.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。
> 

### NCT03113968·条目 29：o BPRS (safety)

- 条目ID：`wref_translation_item_ce02a0c71242d7ad470a059c`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 4 单元（段）：编号条目的数量发生变化（如原文列3条标准，译文只剩2条或多出1条）（检查器代码 `unit_4:numbered_criterion_cardinality_changed`）

**【原文段落】**（英文原文）

> • Update Medical History • Update Psychiatric Medication Log • Update somatic therapies log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Clinical Psychiatric Evaluation • Patient and Clinician Rated Behavioral Scales (to be completed at Baseline/Visit 1, Visit 2, Visit 4, Visit 6, Visit 7, and Visit 9) Prior to Treatment:
> • Patient Rated Behavioral Scales o QIDS-SR-16 (To be completed first) o GSE-MY (Not completed at Baseline/Visit 1) o SMCQ o PGI-S & PGI-I (PGI-I not completed at Baseline/Visit 1) o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales o MADRS o CSSRS o YMRS o CGI-S & CGI-I (CGI-I not completed at Baseline/Visit 1)
> • Post Treatment (clinician rated) o CADSS o BPRS
> 7.3.2 Ketamine Arm
> Prior to each treatment, patients will be assessed if clinically appropriate for the treatment. Each site will follow their standard of care for evaluating patients for ketamine treatment. Each site will perform the following minimal set of assessments:
> • Update Medical History • Update Psychiatric Medication Log • Update Somatic Therapies Log • Vitals (BP, heart rate, weight) • Evaluation for Adverse Events or Serious Adverse Events • Clinical Psychiatric Evaluation • Patient and Clinician Rated Behavioral Scales (to be completed at every visit) Prior to Treatment:
> • Patient Rated Behavioral Scales (to be completed at every visit) o QIDS-SR-16 (To be completed first) o GSE-MY (Not completed at Baseline/Visit 1) o SMCQ o PGI-S & PGI-I (PGI-I not completed at Baseline/Visit 1) o QOLS o PRISE o CPFQ
> • Clinician Rated Behavioral Scales (to be completed at every visit) o MADRS o CSSRS o YMRS o CGI-S & CGI-I (CGI-I not completed at Baseline/Visit 1)
> Post Treatment (clinician rated):
> o CADSS o BPRS 7.3.3 Completion and/or Early 
> …（中略）…
>  patient has worsening depression, severe psychotic symptoms, or becomes suicidal If these situations occur the patient should be scheduled for an End of Treatment Visit. The patient can decide not to continue treatment for any reason. They should be encouraged to complete an End of Treatment Visit.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 1) □ SMCQ □ PGI-S及PGI-I（基线/访视时尚未完成PGI-I评估）

### NCT03113968·条目 30：Unlabelled section (objectives_endpoints) (objectives_endpoints) · 2

- 条目ID：`wref_translation_item_d0a445f664e0bb917a2b0905`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
  - 译文第 1 单元（段）：监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `unit_1:regulatory_chinese_term_calque`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：The key exposures of this study are alternate day ECT treatment and twice a week ketamine infusion. We will conduct an intention to treat (ITT) analysis. A sensitivity analysis will be performed on the modified intention-to-treat (mITT) population defined as a randomized patient having at least one treatment and one valid QIDS- SR16 measurement during the acute treatment phase. Percent of responders is the primary outcome in this study. A responder is defined as a subject with a ≥50% decrease from baseline in the primary endpoint (QIDS-SR-16).
  - 第 1 单元译文：本研究的关键干预措施为隔日实施的ECT治疗以及每周两次的氯胺酮输注。我们将实施意向性分析（ITT）。此外，还会针对改良后的意向性治疗人群开展敏感性分析；该人群的界定标准为：经随机分组的患者在急性治疗期内至少接受过一次相关治疗，且至少有一次有效的QIDS-SR-16评分记录。本研究的主要终点为达到临床应答的受试者比例，所谓“临床应答”即指受试者的主要终点指标（QIDS-SR-16评分）较基线水平降幅≥50%。

**【原文段落】**（英文原文）

> The key exposures of this study are alternate day ECT treatment and twice a week ketamine infusion. We will conduct an intention to treat (ITT) analysis. A sensitivity analysis will be performed on the modified intention-to-treat (mITT) population defined as a randomized patient having at least one treatment and one valid QIDS- SR16 measurement during the acute treatment phase. Percent of responders is the primary outcome in this study. A responder is defined as a subject with a ≥50% decrease from baseline in the primary endpoint (QIDS-SR-16).
> Multiple imputations may be implemented to achieve completeness of the data. In an unlikely case that missing data are non-ignorable, pattern-mixture modeling will be applied. As a general principle, the statistical analysis will follow the pre-specified statistical analysis plan (SAP). The SAP will be finalized prior to the end of the study. The SAP will address how missing data will be handled. The primary outcome measure of response rate will be compared between ketamine and ECT using a chi-square test. A multivariable logistic regression model will be constructed, to account for potential heterogeneity of treatment effect caused by confounding variables. A similar analytic strategy will be applied to evaluate cognitive function and quality of life.
> Sample size The sample size justification will be for the primary outcome measure of response rate. Historical data reveal that the overall response rate as well as the respective response rate of ketamine and of ECT is around 50% – 60% on various scale measurements in patients with treatment-resistant depression. Assuming an observed difference of 10% and an acceptable difference margin of 5% with a 1-sided alpha=0.025, a sample of 400 patients (200 per group) provides 81.8% power to detect a treatment response, based on the Farrington-Manning score test of risk difference. The total sample also considers a 10% attrition rate. 10. Study Committees

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 本研究的关键干预措施为隔日实施的ECT治疗以及每周两次的氯胺酮输注。我们将实施意向性分析（ITT）。此外，还会针对改良后的意向性治疗人群开展敏感性分析；该人群的界定标准为：经随机分组的患者在急性治疗期内至少接受过一次相关治疗，且至少有一次有效的QIDS-SR-16评分记录。本研究的主要终点为达到临床应答的受试者比例，所谓“临床应答”即指受试者的主要终点指标（QIDS-SR-16评分）较基线水平降幅≥50%。
> 

### NCT03113968·条目 31：3. Study Design (objectives_endpoints)

- 条目ID：`wref_translation_item_dc9d87440e81aee19036cf19`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：比较方向改变（“优于/不低于/高于/低于”等方向可能与原文相反——请重点复核）（检查器代码 `unit_1:comparison_direction_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an
  - 第 1 单元译文：研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）

**【原文段落】**（英文原文）

> Investigators may decide to stop treatment for patients who show improvement after less than nine ECT treatments or six ketamine treatments. These patients should be scheduled for an End of Treatment Visit and if they are found to be responders will participate in the follow-up visits. Investigators may also decide to stop treatment for patients who decline or have worsening depression or suicidality during the acute treatment phase. These patients should be scheduled for an End of Treatment Visit and be evaluated for response. (These patients are unlikely to be classified as responders. If an outpatient has worsening depression that requires psychiatric hospitalization, the patient may continue in the study at investigator discretion. These patients can receive study ECT or ketamine treatments as an inpatient. 4. Outcome Measures
> To avoid potential bias, the patient assessments and the clinician assessments should be completed independently and without reference to one another. The research coordinator or clinician administering the questionnaires should not view the patient’s responses on patient rated scales. (They should, however, remind the patient to answer all questions and not leave any questions blank.) 4.1 Primary Outcome
> The primary outcome measure is the percent of responders. Treatment response is defined as a ≥ 50% decrease in QIDS-SR-16 scores from the Baseline Visit to the EOT
> visit. The QIDS-SR-16 will be administered prior to treatment according to the following schedules.
> ECT Arm The QIDS-SR-16 will be administered at certain time points during the acute treatment phase (Baseline/Visit 1, Visit 2, Visit 4, Visit 6, Visit 7, Visit 9, and EOT visit). Patients in the ECT arm who are classified as responders will complete the QIDS-SR-16 at all follow-up v
> …（中略）…
> ill be informed about the study and given a thorough explanation of risks, benefits, study procedures, and expectations. Patients interested in participation will be scheduled for a screening visit as soon as possible, but no later than 28 days from the clinical consult. Typically patients should be

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 研究者可决定对接受少于9次ECT治疗或6次氯胺酮治疗后出现病情改善的患者终止治疗。此类患者须安排进行治疗结束访视；若经评估确认为有效应答者，则可继续参与后续随访。研究者亦可决定对在急性治疗期出现抑郁症状加重或自杀倾向加剧、甚至拒绝继续接受治疗的患者终止治疗。此类患者同样须安排进行治疗结束访视并接受应答评估。（这类患者被判定为有效应答者的可能性较低。若门诊患者在治疗过程中出现抑郁症状加重并需住院治疗，研究者可酌情决定其是否继续参与本研究；此类患者可在住院期间接受研究规定的ECT或氯胺酮治疗。）
> 

### NCT03113968·条目 32：Unlabelled section (safety) (safety) · 3

- 条目ID：`wref_translation_item_ebe2139cc13b752b219a0df7`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44.
  - 第 1 单元译文：难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。

**【原文段落】**（英文原文）

> Treatment-Resistant Depression. American Journal of Psychiatry. 2012;169(12):1238-44. 10. The UKECTRG. Efficacy and safety of electroconvulsive therapy in depressive disorders: a
> systematic review and meta-analysis. The Lancet. 2003;361(9360):799-808. 11. Lisanby SH. Electroconvulsive Therapy for Depression. New England Journal of Medicine.
> 2007;357(19):1939-45. 12. Golden, C. J., & Freshwater, S. M. (1978). Stroop color and word test. 13. Blair, J. R., & Spreen, O. (1989). Predicting premorbid IQ: a revision of the National Adult
> Reading Test. The Clinical Neuropsychologist, 3(2), 129-136. 14. aan het Rot M, Collins KA, Murrough JA, Perez AM, Reich DL, Charney DS, et al. Safety
> and efficacy of repeated-dose intravenous ketamine for treatment-resistant depression. Biological psychiatry. 2010;67(2):139-45. 15. Newport DJ, Carpenter LL, McDonald WM, Potash JB, Tohen M, Nemeroff CB. Ketamine
> and Other NMDA Antagonists: Early Clinical Trials and Possible Mechanisms in Depression. The American journal of psychiatry. 2015;172(10):950-66. 16. van Waarde JA, van Oudheusden LJ, Verway B, Giltay EJ, van der Mast RC. European
> archives of psychiatry and clinical neuroscience. 2013 Mar;263(2):167-75. Doi: 10.1007/s00406-012-0342-7. 17. Lapidus KA, Kellner CH. Journal of ECT. 2011 Sep;27(3):244-6. Doi:
> 10.1097/YCT.0b013e31820059e1.
> 16. Appendix
> | Table 1 Outcome Measures and Scales | | |
> | MEASURE | NAME | DESCRIPTION |
> | DIAGNOSTIC INTERVIEW | | |
> | MINI 7.0.2 | Mini Neuropsychiatric Interview | Diagnostic interview used to determine DSM-5 diagnosis (30 mins) |
> | PATIENT RATED SCALES | | |
> | QIDS-SR-16 (Primary Outcome Measure) | Quick Inventory of Depressive Symptoms | Self-report of depressive symptoms based on DSM diagnostic criteria (10 mins) |
> | GSE-My | Global Self Evaluation 
> …（中略）…
>  | | |
> | MADRS | X | X | X |
> | CSSRS | X | X | X |
> | YMRS | X | X | X |
> | BPRS | X | X | X |
> | CGI-S & CGI-I* | X | X | X |
> | CADSS | X | X | X |
> | Cognitive Assessments | | | |
> | MoCA | X | X | X |
> | COWAT | X | X | X |
> | HVLT-R | X | X | X |
> | Stroop | X | X | X |
> *To be performed by psychiatrist.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 难治性抑郁症。《美国精神病学杂志》2012年；169卷第12期：1238至1244页。
> 

## 研究 NCT03283670（5 项待处置）

### NCT03283670·条目 1：Unlabelled section (safety) (safety)

- 条目ID：`wref_translation_item_3420297c38cd1a4d3a0b1633`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_1:numeric_tokens_changed`）
  - 译文第 1 单元（段）：内容顺序/语序改变（条目排列或分句顺序与原文不同）（检查器代码 `unit_1:unit_sequence_changed`）
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：response 4.0, 95% CI 0.45–35.8; OR for remission 3.0, 95% CI 0.31– 28.8). No serious adverse events occurred; however, two patients experienced panic attacks/anxiety onset, suggesting that the inspiratory N 2 O concentration may have been too high . Importantly, the N 2 O dose in our pilot study (50% N 2 O in 50% oxygen) was based on its use in dentistry because no prior information about N 2 O in TRMD existed.
  - 第 1 单元译文：应答率为4.0%，95%置信区间为0.45至35.8；缓解的比值比为3.0，95%置信区间为0.31至28.8。研究期间未发生任何严重不良事件；不过有两名患者出现了惊恐发作或焦虑症状，提示吸入的二氧化氮浓度可能偏高。需要特别指出的是：本初步研究中所采用的50%二氧化氮与50%氧气的混合气体剂量，是参考牙科领域的使用经验确定的——此前尚无任何关于二氧化氮用于治疗TRMD的相关资料可供参考。

**【原文段落】**（英文原文）

> response 4.0, 95% CI 0.45–35.8; OR for remission 3.0, 95% CI 0.31– 28.8). No serious adverse events
> occurred; however, two patients experienced panic attacks/anxiety onset, suggesting that the inspiratory N 2 O
> concentration may have been too high . Importantly, the N 2 O dose in our pilot study (50% N 2 O in 50% oxygen)
> was based on its use in dentistry because no prior information about N 2 O in TRMD existed.
> Preclinical studies suggest that different doses of ketamine are associated with variable NMDA receptor and
> antidepressant activity. In single neurons, 50% N 2 O blocks >50% of NMDA receptors, whereas ketamine
> concentrations achieved in depression studies likely block ~25-35% of NMDA responses [11]. Thus, it is
> possible that a lower inspiratory concentration of N 2 O (25%) will have substantial antidepressant effect while
> also reducing the risk of paradoxical anxiety.
> We propose a pilot study using a double-blind, crossover (x 2), placebo-controlled design to determine
> whether different concentrations of N 2 O have different antidepressant effects. We hypothesize that 25% and
> 50% N 2 O, as compared to placebo, will have equivalent antidepressant effects. Further, we predict that these
> effects will occur rapidly (2 hours) and be sustained (24 hours, one and two weeks), but will attenuate by one
> month.
> 3. Drug Information
> Nitrous oxide (laughing gas) is a colorless, odorless gas. Nitrous oxide is the oldest and most widely used FDA-
> approved anesthetic gas. It is commonly used as a component of general anesthesia and as a sedative/analgesic
> agent used in hospitals and dentist offices. The onset as well as offset of effect is within a few minutes. Nitrous
> oxide is the least potent of inhalational anesthetics. Concentrations above 1 atm are theoretically needed to
> pr
> …（中略）…
>  nausea
> and vomiting, inactivation of vitamin B 12 (commensurate with the duration of exposure and concentration used).
> In general, exposure to 25-50% nitrous oxide for 1 hour is considered extremely safe. The use of nitrous oxide
> in this protocol is off-label and outside of the approved indication.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 应答率为4.0%，95%置信区间为0.45至35.8；缓解的比值比为3.0，95%置信区间为0.31至28.8。研究期间未发生任何严重不良事件；不过有两名患者出现了惊恐发作或焦虑症状，提示吸入的二氧化氮浓度可能偏高。需要特别指出的是：本初步研究中所采用的50%二氧化氮与50%氧气的混合气体剂量，是参考牙科领域的使用经验确定的——此前尚无任何关于二氧化氮用于治疗TRMD的相关资料可供参考。
> 

### NCT03283670·条目 2：6.3. Blinding (objectives_endpoints)

- 条目ID：`wref_translation_item_50308d12dcd57e912857f6bc`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 13 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_13:numeric_tokens_changed`）
  - 译文第 13 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_13:source_abbreviation_missing`）
- **问题单元对照（仅列被点名单元）：**
  - 第 13 单元原文：Patients will be monitored during and after the treatment according to American Society of Anesthesiologists standard which include continuous 3-lead ECG, pulsoximetry, non-invasive blood pressure and endtidal CO 2 under the supervision of an attending-level anesthesiologist. After the one hour treatment session, patients may be transferred if needed, and monitored in a recovery room for approximately 2 hours. A study team physician will determine if the patient meets criteria for discharge before the patient will be allowed to leave the suite.
  - 第 13 单元译文：患者将在治疗期间及治疗后接受监测，相关操作遵循美国麻醉医师协会的标准流程：由具备主治资质的麻醉科医师负责监督实施，监测项目包括持续3导联心电图（ECG）、脉搏血氧饱和度测定、无创血压测量以及呼气末二氧化碳浓度监测。完成1小时的治疗后，如有需要可将患者转移至其他区域；随后在恢复室继续监测约2小时。研究团队的医师将评估该患者是否符合出院标准，确认无误后方可允许其离开治疗室。

**【原文段落】**（英文原文）

> separate from the team assessing the study outcomes which will be blinded to the group assignment. Treatment
> administration and outcomes assessment may also be physically separated in different rooms within the study
> facility.
> In addition, after each inhalation session, subjects will be asked whether they thought they received the active
> nitrous oxide gas or the placebo gas. Responses will be recorded with an assessment (5 point scale) asking
> participants to rate the extent to which they knew they were exposed to nitrous oxide; 1) strongly believe the
> treatment was nitrous oxide, 2) somewhat believe the treatment was nitrous oxide, 3) somewhat believe the
> treatment was placebo, 4) strongly believe the treatment is placebo, and, 5) don’t know.
> 6.4. Setting
> The inhalation sessions will be performed in Barnes-Jewish-Hospital, or the Clinical Research Unit (CRU) suite
> within Washington University. The procedure room used is equipped with vital sign monitoring, resuscitation
> equipment and devices, and has oxygen wall outlets. As part of the standard setup, a mobile FDA-approved
> nitrous oxide delivery system will be used or an anesthesia machine.
> 6.5. Study Procedures
> Except for the choice of gas (either nitrous oxide concentration or nitrogen [inert]; all mixed with 50% oxygen)
> treatment sessions will be identical. The gas mix will be administered via a standard anesthesia facemask
> through tubing connected to the anesthesia machine or via a facemask which is connected via hose to an FDA-
> approved Porter/Praxair MXR breathing circuit. A small sample connector line will be inserted into the
> facemask which allows the measurement of inhaled and exhaled gas concentrations. Inhaled and exhaled gas
> concentrations of nitrous oxide, oxygen and nitrogen will be monitored and adjusted 
> …（中略）…
> ng-level anesthesiologist. After the one hour treatment session, patients may
> be transferred if needed, and monitored in a recovery room for approximately 2 hours. A study team physician
> will determine if the patient meets criteria for discharge before the patient will be allowed to leave the suite.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 患者将在治疗期间及治疗后接受监测，相关操作遵循美国麻醉医师协会的标准流程：由具备主治资质的麻醉科医师负责监督实施，监测项目包括持续3导联心电图（ECG）、脉搏血氧饱和度测定、无创血压测量以及呼气末二氧化碳浓度监测。完成1小时的治疗后，如有需要可将患者转移至其他区域；随后在恢复室继续监测约2小时。研究团队的医师将评估该患者是否符合出院标准，确认无误后方可允许其离开治疗室。
> 

### NCT03283670·条目 3：Unlabelled section (objectives_endpoints) (objectives_endpoints)

- 条目ID：`wref_translation_item_85aa6240bc9641a60ffa7d86`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 1 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_1:source_abbreviation_missing`）
- **问题单元对照（仅列被点名单元）：**
  - 第 1 单元原文：disassociation (CADSS) will also be measured. Outcomes will be analyzed with a repeated measures mixed effects linear model using restricted maximum likelihood estimation. To adjust for the observed carryover effect, the model will include a randomization group term and a three-way interaction (treatment x time x randomization group). To compare response and remission rates (≥50% decrease, ≤7 on HDRS-21, respectively), an exact binomial test will be used (and corresponding odds ratios [ORs] calculated). Symmetry and spectral power will be assessed from EEG acquired during periods of eye closur
  - 第 1 单元译文：此外，还将对解离症状（CADSS）进行评估。将采用基于受限最大似然估计的重复测量混合效应线性模型对各项结果进行分析。为校正观察到的延续性影响，该模型中将纳入随机分组因素以及三向交互项（治疗组×时间×随机分组）。为比较临床应答率与缓解率——即症状减轻程度分别达到50%及以上、HDRS-21评分降至7分及以下——将采用精确二项检验（并据此计算相应的比值比[ORs]）。同时，还将根据受试者闭眼或睁眼状态下的脑电图数据来评估其脑电波对称性及频谱功率。

**【原文段落】**（英文原文）

> disassociation (CADSS) will also be measured. Outcomes will be analyzed with a repeated measures mixed
> effects linear model using restricted maximum likelihood estimation. To adjust for the observed carryover
> effect, the model will include a randomization group term and a three-way interaction (treatment x time x
> randomization group). To compare response and remission rates (≥50% decrease, ≤7 on HDRS-21,
> respectively), an exact binomial test will be used (and corresponding odds ratios [ORs] calculated). Symmetry
> and spectral power will be assessed from EEG acquired during periods of eye closure or opening.
> Power Analysis

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 此外，还将对解离症状（CADSS）进行评估。将采用基于受限最大似然估计的重复测量混合效应线性模型对各项结果进行分析。为校正观察到的延续性影响，该模型中将纳入随机分组因素以及三向交互项（治疗组×时间×随机分组）。为比较临床应答率与缓解率——即症状减轻程度分别达到50%及以上、HDRS-21评分降至7分及以下——将采用精确二项检验（并据此计算相应的比值比[ORs]）。同时，还将根据受试者闭眼或睁眼状态下的脑电图数据来评估其脑电波对称性及频谱功率。
> 

### NCT03283670·条目 4：6.3. Blinding (objectives_endpoints)

- 条目ID：`wref_translation_item_c3cea8a3ef83a3ecd5875142`（第 14 次尝试被拦）
- **发现的问题：**
  - 译文第 13 单元（段）：数字/数值写法发生变化（如英文数词改为阿拉伯数字、数值或单位数字与原文不一致）（检查器代码 `unit_13:numeric_tokens_changed`）
  - 译文第 13 单元（段）：原文中的缩写在译文中缺失（如 RCT、AE/SAE 等缩写被略去或未按原文保留）（检查器代码 `unit_13:source_abbreviation_missing`）
- **问题单元对照（仅列被点名单元）：**
  - 第 13 单元原文：Patients will be monitored during and after the treatment according to American Society of Anesthesiologists standard which include continuous 3-lead ECG, pulsoximetry, non-invasive blood pressure and endtidal CO 2 under the supervision of an attending-level anesthesiologist. After the one hour treatment session, patients may be transferred if needed, and monitored in a recovery room for approximately 2 hours. A study team physician will determine if the patient meets criteria for discharge before the patient will be allowed to leave the suite.
  - 第 13 单元译文：患者将在治疗期间及治疗后接受监测，相关操作遵循美国麻醉医师协会的标准流程：由具备主治资质的麻醉科医师负责监督实施，监测项目包括持续3导联心电图（ECG）、脉搏血氧饱和度测定、无创血压测量以及呼气末二氧化碳浓度监测。完成1小时的治疗后，如有需要可将患者转移至其他区域；随后在恢复室继续监测约2小时。研究团队的医师将评估该患者是否符合出院标准，确认无误后方可允许其离开治疗室。

**【原文段落】**（英文原文）

> separate from the team assessing the study outcomes which will be blinded to the group assignment. Treatment
> administration and outcomes assessment may also be physically separated in different rooms within the study
> facility.
> In addition, after each inhalation session, subjects will be asked whether they thought they received the active
> nitrous oxide gas or the placebo gas. Responses will be recorded with an assessment (5 point scale) asking
> participants to rate the extent to which they knew they were exposed to nitrous oxide; 1) strongly believe the
> treatment was nitrous oxide, 2) somewhat believe the treatment was nitrous oxide, 3) somewhat believe the
> treatment was placebo, 4) strongly believe the treatment is placebo, and, 5) don’t know.
> 6.4. Setting
> The inhalation sessions will be performed in Barnes-Jewish-Hospital, or the Clinical Research Unit (CRU) suite
> within Washington University. The procedure room used is equipped with vital sign monitoring, resuscitation
> equipment and devices, and has oxygen wall outlets. As part of the standard setup, a mobile FDA-approved
> nitrous oxide delivery system will be used or an anesthesia machine.
> 6.5. Study Procedures
> Except for the choice of gas (either nitrous oxide concentration or nitrogen [inert]; all mixed with 50% oxygen)
> treatment sessions will be identical. The gas mix will be administered via a standard anesthesia facemask
> through tubing connected to the anesthesia machine or via a facemask which is connected via hose to an FDA-
> approved Porter/Praxair MXR breathing circuit. A small sample connector line will be inserted into the
> facemask which allows the measurement of inhaled and exhaled gas concentrations. Inhaled and exhaled gas
> concentrations of nitrous oxide, oxygen and nitrogen will be monitored and adjusted 
> …（中略）…
> ng-level anesthesiologist. After the one hour treatment session, patients may
> be transferred if needed, and monitored in a recovery room for approximately 2 hours. A study team physician
> will determine if the patient meets criteria for discharge before the patient will be allowed to leave the suite.

**【中文译文段落】**（对齐译文（管线组装的被拦译文））

> 患者将在治疗期间及治疗后接受监测，相关操作遵循美国麻醉医师协会的标准流程：由具备主治资质的麻醉科医师负责监督实施，监测项目包括持续3导联心电图（ECG）、脉搏血氧饱和度测定、无创血压测量以及呼气末二氧化碳浓度监测。完成1小时的治疗后，如有需要可将患者转移至其他区域；随后在恢复室继续监测约2小时。研究团队的医师将评估该患者是否符合出院标准，确认无误后方可允许其离开治疗室。
> 

### NCT03283670·条目 5：7) Breastfeeding women (safety)

- 条目ID：`wref_translation_item_faf7321b4aec22ca52117c2b`（第 14 次尝试被拦）
- **发现的问题：**
  - 监管术语直译（术语译法生硬，可能不符合中文监管文件惯用表述）（检查器代码 `regulatory_chinese_term_calque`）

**【原文段落】**（英文原文）

> f) Any other factor that in the investigators’ judgment may affect patient safety or compliance.
> 5. Enrollment
> Participants will be recruited in part through the Volunteer for Health registry at Washington University School
> of Medicine and the Washington University TRMD Database (120+ individuals with TRMD carefully screened
> over the past 8 years, maintained by Dr. Conway; IRB# 201102247). Eligible and interested participants will be
> consented for participation and enrolled in the study by study personnel. We will recruit a total of 40
> participants currently in an episode of major depressive disorder, medication-free or on psychotropic

**【中文译文段落】**（库内未存译文）

>（库内未存该条目的被拦译文文本。）
