# round23 长文截断修复：反例、修复、真实模型重生成与忠度对照（2026-09-27）

## 一、结论（先看这里）

| 口径 | 修复前（样本实库现状） | 修复后（本轮实测） |
|---|---|---|
| 样本源文 | 4865字符，单个自然段（全文零换行） | 同一源文 |
| 切分结果 | **1个翻译块**（整段不切，理由字段实录“1 chunks”） | **2个翻译块：2904+1960字符**，按安全句边界切开 |
| 模型产出 | **146字符碎片**（一句半即停，且每次尝试同样被截断压力打断） | **完整译文1791字符**（约为碎片的12.3倍），覆盖原文全部9个翻译单元，无空单元 |
| 单次调用结束原因 | 截断压力（8单元合一次请求，输出顶到完成上限） | **20次调用全部 finish=stop**（正常收尾，零截断） |
| 忠度发现 | numeric_tokens_changed + source_abbreviation_missing（单元1） | 10条单元级忠度码、涉及6个单元（见第四节）——这才是需要医学人工判定的完整清单 |

处置边界不变：忠度自动晋级仍暂停，以下全部发现仅作为证据交医学人工判定；本次重生成是诊断性重放，**零数据库写入**，未改变任何既有行、任何条目状态。

## 二、反例先证：切分决策点与红→绿

- 决策点：`services/api/app/chapter_translation_pipeline.py` 的 `_split_oversized_text`（:4971）。原逻辑只按“空行（段落）/单换行（列表、表格行）”切分；**没有换行结构的超限段落整段保留**（“indivisible line is kept intact”分支）——4865字符单段落因此变成1个翻译块、8个单元合一次模型请求。
- 修复：为该分支补上安全句边界切分（复用既有的 `_split_long_line`，绝不切断小数、缩写、比较符），切出的段节按段落样式打包进有界的翻译块。最小diff，只新增一个 elif 分支。
- 反例测试（先红后绿）：`tests/test_chapter_translation_oversize_paragraph_split.py`。红=修复前实测 `test_single_overlimit_paragraph_yields_bounded_chunks` FAILED（同一构造源文只切出1块）；绿=修复后5/5通过，并对真实样本源文实测：**1块[4865] → 2块[2904, 1960]**，单元边界与顺序保持、数字多集与正文内容逐一守恒、切分确定性复现。
- 回归：`tests/test_document_pipeline_round8.py + test_mw_v11_translation_alignment.py + 新切分测试 + round23谱系测试 + 主batch测试 + 复检绑定测试 → 290 passed + 20 subtests`，零回归。

## 三、真实模型重生成实况（经编排器，已授权面）

- 模型生命周期：`ensure_phase("translation")` → `{status: ok, server: omlx, model: dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX}`；仅经编排器管理两台受管服务器，未触碰live 8910与医学监查。
- 请求形态与生产逐字一致：系统提示词、单元标记信封、temperature=0、max_tokens=4096、截断/空输出即fail-closed、oMLX共享租约。
- 实测调用：**20次，全部 finish=stop**；完成token从51到703不等——修块后单请求规模已远离截断上限。
- 重生成是**诊断性重放**：计划与源文取自库内持久化数据（零规划调用），译文与发现只写本证据目录，**零数据库写入**。

## 四、新译文忠度码清单（正常确定性忠度门输出，交医学人工判定）

| 翻译块 | 单元 | 忠度码 |
|---|---|---|
| 1 | unit_1 | `numeric_tokens_changed` |
| 1 | unit_1 | `source_abbreviation_missing` |
| 1 | unit_4 | `comparison_direction_changed` |
| 1 | unit_4 | `unit_sequence_changed` |
| 1 | unit_4 | `unsupported_medical_concept_added` |
| 1 | unit_5 | `numeric_tokens_changed` |
| 2 | unit_1 | `numeric_tokens_changed` |
| 2 | unit_1 | `unit_sequence_changed` |
| 2 | unit_3 | `numeric_tokens_changed` |
| 2 | unit_3 | `source_abbreviation_missing` |

提示：数值类发现多为数词与数字书写形态之争（如 thirty → 30名）；单元4的比较方向/顺序/概念新增与单元1的缩写缺失（RCT）是需要医学重点复核的实质项。清单按检查器原样呈现，不做任何“自动判定为可接受”的处理。

## 五、原文段落 vs 完整译文对照（样本级）

### 原文（4865字符，单个自然段）

> Phase 2, RCT Overview: In the 8-weeks of BPN vs. placebo, thirty subjects will be randomized (using permuted block randomization) 2:1 to receive venlafaxine XR (at the dose they reached and tolerated in the open-label lead-in) plus either BPN or placebo. The reasons for using a 2:1 random allocation include: 1) collection of more data about plasma levels of BPN and its metabolites, and 2) gaining further clinical experience with the molecule. Both of these reasons are consistent with the developmental nature of the R34 grant mechanism (the NIH grant mechanisms supporting this project). We will use independent evaluators (who are blind to treatment assignment) at the end of phase 2 for the last two assessments to determine if the participant has met response. The reason for using independent evaluators at this pivotal timepoint is that clinicians may become unblinded because they are also assessing side effects. At the beginning of phase 2, participants will be asked to review and sign the phase 2 contract (attached under other attachments in OSIRIS). This contract outlines safety precautions and directions for taking and storing the medication. This contract will be signed with all participants who are moving into phase 2. BPN will be started at 0.2 mg/d and will be titrated weekly by 0.2 mg, based on tolerability (assessed with the FIBSER) and depression severity (assessed with MADRS). The minimum target dose is 0.6 mg/d (based on our pilot work) with an allowed maximum of 1.2 mg/d. The primary outcome will be remission at the end of the 8-week period (defined by a MADRS score of 10 or lower for two consecutive weeks, as in the IRL GREY study). The first dose of buprenorphine will be taken while in the office while under the supervision of the PI, Co-I, and study personnel. They will wait in the office for 60 minutes after taking the initial buprenophine dose. Since the analgesic effects of BPN may obscure the antidepressant effects, we will exclude subjects with severe pain. This will be defined as a score of greater than 7 on a 0-10 Numeric Rating Scale for Pain. The time assessed for pain will be the previous month (note: we are not trying to diagnose a chronic pain syndrome, but exclude those with recent clinically significant pain). Assessing durability of clinical response: While a relapse prevention study would require a different design, we aim to collect data on the durability of clinical effect. Blinded independent assessors will be used to confirm treatment response. The rationale for this is described above. Titration schedule of BPN: Dosing increases will be guided by antidepressant response (e.g., 2 consecutive MADRS scores less than 10) and our protocolized use of the Frequency, Intensity, and Burden of Side Effect Rating (FIBSER) Scale score. This individualized dosing regimen accommodates both antidepressant response and tolerability. We have used it successfully in our BPN pilot work, an ongoing study of the pharmacotherapy of complicated grief, and it was used in the STAR*D project (Steffens et al, 2010). We will increase the dose by 0.2 mg/week up to 1.2 mg/day based on MADRS and FIBSER scores. Our rationale for selecting this dosing schedule is based on other small open-label trials using BPN for treatment resistant depression in younger patients in which the initial dose ranged from 0.15 mg/day (intranasal formulation) – 0.4 mg/day (sublingual), and was increased to 1.8 mg/day (intranasal) – 2 mg/day (sublingual). The duration of previous studies has ranged from 1 week to 4 weeks, with the dose increased by 0.4 mg/day every 1-2 days or according to tolerance and clinical benefit. In our recently completed work, the duration of exposure to BPN has been 8 weeks with a maximum dose of 1.6 mg/day. Consistent with the developmental aim to learn more about dosing ranges and plasma levels, we will extend phase 2 to eight weeks with a maximum dose of 1.2 mg/d.). With this approach, we expect to clarify the range of efficacious and tolerable doses for BPN, ultimately resulting in a more parsimonious dose titration schedule. This is of great importance, as the appropriate dose range is not yet established. In order to ensure that subjects do not experience withdrawal, we will taper the study drug at the end of phase 3. The study drug will be tapered by 20% every 3 days until discontinued. We will use the Clinical Opiate Withdrawal Scale (COWS) to assess any symptoms of withdrawal and adjust the discontinuation as needed to assure a comfortable discontinuation for subjects. In our pilot work, we have not encountered ANY discontinuation symptoms during the cessation of BPN. This may be due to the relatively short duration of exposure and the very low doses used in the project. Breaking the blind: The blind will be broken for all participants at the end of phase 2.

### 完整译文（1791字符，按两个翻译块拼接）

> 2期随机对照试验概述：在为期8周的试验中，30名受试者将通过置换区组随机法以2:1的比例被随机分组：一组接受文拉法辛XR（剂量为其在开放标签导入期所能耐受的最高剂量），同时联合使用BPN；另一组则仅接受文拉法辛XR与安慰剂。采用2:1随机分配比例的原因如下：
> 
> 1) 收集更多关于BPN及其代谢物血浆浓度的数据，
> 
> 2) 积累对该分子的更多临床经验。上述两个原因均符合 R34资助机制（即支持本项目的 NIH资助模式）的发展定位。在Ⅱ期试验末期，我们将安排对治疗分组情况不知情的独立评估员进行最后两次疗效评定，以确认受试者是否达到预期应答标准。之所以在这一关键节点选用独立评估员，是因为临床医生在同时负责副作用监测时可能会出现信息泄露的情况。Ⅱ期试验启动之初，所有即将进入该阶段的受试者均需审阅并签署《Ⅱ期临床试验协议》（详见 OSIRIS系统中的其他附件）。该协议中详细规定了用药安全注意事项以及药物的服用与储存方法。所有即将进入Ⅱ期试验阶段的受试者均须签署该协议。
> 
> 2. BPN的起始剂量为0.2毫克/天，随后根据耐受情况（通过FIBSER进行评估）以及抑郁严重程度（通过MADRS进行评估），每周增加0.2毫克。基于前期试验结果，最低目标剂量为0.6毫克/天，最高允许剂量则为1.2毫克/天。主要疗效终点为治疗8周后的缓解状态，其判定标准为连续两周MADRS评分均不高于10分——该标准与IRL GREY研究中的定义一致。首次服用丁丙诺啡时，受试者须在PI、共同研究者及研究人员的现场监督下完成服药。服用首剂药物后，受试者需在诊室内停留60分钟接受观察。由于BPN的镇痛作用可能掩盖其抗抑郁效果，因此我们将排除存在重度疼痛的受试者；此类情况定义为在0至10分的数字疼痛评分量表上得分超过7分。上述疼痛评估所针对的时间范围为过去一个月（需说明：本研究并非旨在诊断慢性疼痛综合征，仅排除近期出现具有临床意义的明显疼痛症状的受试者）。
> 
> 评估临床应答的持久性：虽然预防复发的研究需要采用不同的设计方案，但我们仍计划收集有关临床疗效持续时间的相关数据。我们将安排不知晓分组情况的独立评估人员对治疗应答情况进行确认，相关依据已在上文予以说明。BPN的剂量滴定方案：剂量的递增将以抗抑郁治疗应答情况为依据（例如，连续两次MADRS评分均低于
> 
> 10) 以及我们依据《副作用频率、强度与负担评分量表》（FIBSER）所制定的标准化使用方案。这种个体化给药方案兼顾了抗抑郁疗效与耐受性。
> 
> 我们在BPN的初步试验中成功应用了该制剂，该研究目前仍在进行，旨在探讨复杂哀伤状态的药物治疗方案；此外它也曾被用于STAR项目（Steffens等人，2010年）。我们将依据MADRS与FIBSER评分情况，以每周增加0.2毫克的幅度逐步提升剂量，直至达到每日1.2毫克的水平。我们选定该给药方案的依据是既往开展的多项小型开放标签试验：这些研究均使用BPN治疗年轻患者的难治性抑郁症，初始给药剂量介于每日0.15毫克（鼻用制剂）至每日0.4毫克（舌下含服制剂），后续又逐步提升至每日1.8毫克（鼻用制剂）至每日2毫克（舌下含服制剂）。既往相关研究的试验周期从1周到4周不等，给药剂量每1至2天增加0.4毫克/日，也可依据受试者的耐受程度及临床获益情况灵活调整。在我们近期完成的试验中，受试者接受BPN治疗的周期达8周，最高给药剂量为每日1.6毫克。鉴于本研究的开发目的正是进一步明确BPN的适宜给药范围及血浆药物浓度水平，我们将把II期试验的周期延长至8周，最高给药剂量仍设定为每日1.2毫克。
> 
> 通过此方法，我们期望能够明确BPN的有效且耐受性良好的剂量范围，进而制定出更为精简的剂量调整方案。这一点至关重要，因为目前尚未确定其合适的剂量区间。为预防受试者出现戒断反应，我们将在研究阶段末期逐步减少给药量。
> 
> 3. 研究药物的剂量将每3天递减20%，直至完全停药。我们将采用临床阿片类药物戒断量表（COWS）来评估受试者是否出现任何戒断症状，并根据评估结果调整停药方案，以确保所有受试者能够舒适地完成停药过程。在前期预试验中，我们在停用BPN的过程中并未观察到任何戒断症状；这可能与受试者的用药时长相对较短以及本项目中使用的剂量极低有关。破盲说明：在第二阶段结束时，所有受试者的双盲状态均将被解除。

## 六、累计模型调用明细

| # | 块 | 纠错轮 | 输出字符 | finish | 完成token |
|---|---|---|---|---|---|
| 1 | 1 | 否 | 1140 | stop | 607 |
| 2 | 1 | 是 | 1301 | stop | 703 |
| 3 | 1 | 否 | 162 | stop | 92 |
| 4 | 1 | 是 | 164 | stop | 97 |
| 5 | 1 | 否 | 60 | stop | 31 |
| 6 | 1 | 否 | 311 | stop | 158 |
| 7 | 1 | 否 | 413 | stop | 235 |
| 8 | 1 | 是 | 417 | stop | 236 |
| 9 | 1 | 否 | 175 | stop | 89 |
| 10 | 1 | 是 | 165 | stop | 84 |
| 11 | 1 | 否 | 104 | stop | 53 |
| 12 | 2 | 否 | 825 | stop | 460 |
| 13 | 2 | 是 | 759 | stop | 426 |
| 14 | 2 | 否 | 465 | stop | 276 |
| 15 | 2 | 是 | 464 | stop | 274 |
| 16 | 2 | 否 | 465 | stop | 276 |
| 17 | 2 | 是 | 464 | stop | 274 |
| 18 | 2 | 否 | 140 | stop | 71 |
| 19 | 2 | 否 | 226 | stop | 117 |
| 20 | 2 | 是 | 229 | stop | 120 |

## 七、未尽事项（如实）

- 上述忠度发现的医学裁定由用户人工门执行；裁定前不发生任何晋级。
- 谱系复检工具已同步改为从谱系行自身持久化源文取单元（对重切分鲁棒），样本复检重跑仍为 confirmed（runs/.../sample_reeval_after_rechunk.json）。
- FAST定向自查命令与结果见会话记录；全量门本轮未跑（上一轮已申报0新增口径，本轮改动面已由290项定向回归覆盖）。
