# G6 研究元数据筛选（shortlist）交付 — 0927V1

生成时间：2026-09-27（北京时间）。执行人：筛选匠（功能Agent，独立工作树）。
按 0926V1 G6 口径 + 0927V1 §7/§验收矩阵 A21、A601–A610 实施：**仅用注册元数据验证选择器，不等 574 项翻译**（A21）；全程零真实模型、零网络、零下载（A16）。

## 一、输入与身份（全部当场实读）

| 项 | 值 | 来源 |
|---|---|---|
| 候选池 | 622 项注册元数据（公开 ClinicalTrials.gov 摘要字段，无正文无翻译） | 快照 `wref_search_4d2c5d3b8476515fc38b`（isolated_runtime 只读复制） |
| 相关性分诊（上游权威，本次不重判） | 已确认 discovery basket `ct_conf_ebb394de59fb68021378`：69 项入选（间接参照）/553 项排除 | K3 项目 `proj_user_fad9f64f3151` journey projection（只读副本） |
| 项目事实 | 适应症=难治性重度抑郁症/TRD+MDD；分期=II期；口服小分子辅助；安慰剂对照 add-on；MADRS/应答/缓解终点；疗程8周；参考日期 2026-09-23 | journey framing/search_plan 实读；`facts_hash` 见产物 JSON |
| proposal_hash | `086a2a3fb1ddd0bc8fe8547f7cc5dade4a6f412adeb3437be7e061c9891fe56a`（同输入重跑逐字节一致，确定性验证通过） | `g6_shortlist_proposal.json` |

相关性分诊与本轮深读入选是两步：basket 的 69/553 是上游已确认结论，选择器**不重新裁决相关性**，只在入选池内做深读排序与范围收敛。

## 二、入选范围：25 项不同研究（69 项合格 > 30 上限，按设计多样性轮转收敛到默认 25）

规则：合格 ≤30 时全部保留不凑数；本次合格 69 > 30，按"设计簇轮转、簇内按可比性排序"取 25 项（13 个设计簇），其余 44 项按可比性排序进入替换池，供"整组采用+个别替换"。

| 排名 | NCT | 简题 | 分期 | 首发年 | 选用文件/年份 | 相似维度（有明确证据） | 差异（明确相反证据） | 未知维度数 |
|---|---|---|---|---|---|---|---|---|
| 1 | NCT03915613 | Brain Insulin Resistance in Mood Disorders | P1/P2 | 2019 | protocol_sap/2021 | 总体设计、终点、分期、人群、研究目的、途径 | 无 | 4 |
| 2 | NCT02461927 | Ketamine for the Rapid Treatment of Major Depressive Disorder and Alcohol Use Di | P1/P2 | 2015 | protocol_sap/2022 | 对照、总体设计、疗程、分期、人群 | 无 | 5 |
| 3 | NCT02181231 | Buprenorphine Used With Treatment Resistant Depression in Older Adults | P1/P2 | 2014 | protocol_sap/2016 | 总体设计、终点、机制、分期、人群、研究目的 | 无 | 4 |
| 4 | NCT03505905 | A Neurosteroid Intervention for Menopausal and Perimenopausal Depression | P1/P2 | 2018 | protocol_sap/2024 | 对照、总体设计、终点、分期、人群、研究目的 | 无 | 4 |
| 5 | NCT05193318 | KAP for Depression in Abstinent Opioid Users | P2 | 2022 | protocol_sap/2022 | 疗程、机制、分期、人群 | 无 | 6 |
| 6 | NCT02418195 | miRNAs, Suicide, and Ketamine - Plasma Exosomal microRNAs as Novel Biomarkers fo | P2 | 2015 | protocol/2019 | 总体设计、分期、人群、研究目的 | 疗程:registry 2 weeks vs project 8 weeks | 5 |
| 7 | NCT04821271 | Antidepressant Effects of TS-161 in Treatment-Resistant Depression | P2 | 2021 | protocol_sap/2023 | 对照、总体设计、疗程、分期、人群、研究目的 | 无 | 4 |
| 8 | NCT06309277 | A Clinical Study to Evaluate of Single and Multiple Oral Doses of GM-1020 in Pat | P2 | 2024 | protocol_sap/2025 | 总体设计、分期、人群、研究目的、途径 | 无 | 5 |
| 9 | NCT02473289 | An Efficacy and Safety Study of Sirukumab in Participants With Major Depressive  | P2 | 2015 | protocol/2018 | 对照、总体设计、疗程、终点、分期、人群、研究目的、途径 | 无 | 2 |
| 10 | NCT02176291 | Incomplete Response in Late-Life Depression: Getting to Remission With Buprenorp | P2 | 2014 | protocol/2017 | 总体设计、终点、分期、人群、研究目的 | 无 | 5 |
| 11 | NCT03053362 | THINC-it Vortioxetine - Sensitivity to Change | P2/P3 | 2017 | protocol_sap/2017 | 总体设计、分期、人群 | 无 | 7 |
| 12 | NCT03697603 | A Study of Brexpiprazole in Patients With Major Depressive Disorder | P2/P3 | 2018 | protocol/2020 | 对照、总体设计、疗程、分期、人群、研究目的 | 无 | 4 |
| 13 | NCT02674529 | Study of Neural Responses Induced by Antidepressant Effects | P2/P3 | 2016 | protocol_sap/2022 | 总体设计、分期、人群、研究目的 | 无 | 6 |
| 14 | NCT00088699 | Rapid Antidepressant Effects of Ketamine in Major Depression | P1/P2 | 2004 | protocol_sap/2016 | 总体设计、机制、分期、人群、研究目的 | 无 | 5 |
| 15 | NCT03726658 | Zelquistinel in the Treatment of Adults With Major Depressive Disorder | P1/P2 | 2018 | protocol/2019 | 对照、总体设计、分期、人群 | 无 | 6 |
| 16 | NCT02660528 | Tocilizumab Augmentation in Treatment-Refractory Major Depressive Disorder | P2 | 2016 | protocol_sap/2019 | 分期、人群、研究目的 | 无 | 7 |
| 17 | NCT03079297 | Rapid Antidepressant Effects of Leucine | P2 | 2017 | protocol_sap/2016 | 对照、总体设计、分期、人群、研究目的 | 无 | 5 |
| 18 | NCT03283670 | Inhaled Nitrous Oxide for Treatment-Resistant Depression: Optimizing Dosing Stra | P2 | 2017 | protocol_sap/2019 | 总体设计、分期、人群、研究目的 | 无 | 6 |
| 19 | NCT03559192 | A Study to Explore the Efficacy of JNJ-67953964 in the Treatment of Depression | P2 | 2018 | protocol/2019 | 对照、总体设计、终点、机制、分期、人群、研究目的 | 无 | 3 |
| 20 | NCT03181529 | Effects of Psilocybin in Major Depressive Disorder | P2 | 2017 | protocol_sap/2020 | 总体设计、分期、人群、研究目的、途径 | 无 | 5 |
| 21 | NCT02553915 | Omega-3 Fatty Acids for Major Depressive Disorder With High Inflammation: A Pers | P2/P3 | 2015 | protocol_sap/2018 | 对照、总体设计、疗程、分期、人群、研究目的 | 无 | 4 |
| 22 | NCT03113968 | ELEKT-D: Electroconvulsive Therapy (ECT) vs. Ketamine in Patients With Treatment | P2/P3 | 2017 | protocol/2022 | 总体设计、分期、人群 | 无 | 7 |
| 23 | NCT02192099 | Open Label Extension for GLYX13-C-202, NCT01684163 | P2 | 2014 | protocol/2016 | 分期、人群、研究目的 | 无 | 7 |
| 24 | NCT04244253 | A Phase 2 Trial of OPC-64005 for Major Depressive Disorder | P2 | 2020 | protocol/2020 | 对照、总体设计、疗程、终点、分期、人群、研究目的 | 无 | 3 |
| 25 | NCT02458690 | eIMPACT Trial: Modernized Collaborative Care to Reduce the Excess CVD Risk of Ol | P2 | 2015 | protocol_sap/2018 | 总体设计、分期、人群、研究目的、途径 | 无 | 5 |

每项完整理由（匹配证据、差异说明、未知清单、时效/地区/获批关联决策因子）见产物 `g6_shortlist_proposal.json` 的 `selected[].matched/differences/unknown_fields/tiebreakers`。

## 三、替换池（44 项，按可比性排序，供个别替换，不加逐项审批负担）

前 5 名：

| 排名 | NCT | 简题 | 可比性 |
|---|---|---|---|
| 26 | NCT04080752 | A Study of JNJ-61393215 in the Treatment of Depression | 24 |
| 27 | NCT04395183 | 5-HTP and Creatine for Depression | 23 |
| 28 | NCT06280235 | A Study to Test Different Doses of BI 1569912 in People With Depression Who Take | 22 |
| 29 | NCT04521478 | A Study to Test the Effect of Different Doses of BI 1358894 and Quetiapine in Pe | 22 |
| 30 | NCT04423757 | A Home-based Study Using Mobile Technology to Test Whether BI 1358894 is Effecti | 22 |

完整 44 项见 `g6_shortlist_proposal.json` 的 `replacement_pool`。整组采用=确认 proposal_hash；个别替换由 `apply_replacement()` 生成新版本（父哈希链接、理由随条目保留），已在测试中验证。

## 四、范围外与历史保留（A610）

- **553 项排除**：分诊显式排除，逐项记录在 `excluded_by_triage`（含 NCT 与简题），历史保留、不计失败、不绑定任何昂贵任务——冻结范围提示（scope_hint）只含入选 25 项。
- **未决 0 项**、**重复归并 0 项**（本次快照无同研究重复注册；去重逻辑以指纹碰撞为条件并有专项测试）。
- 范围外零新增昂贵调用：本次运行零下载、零模型调用，范围为纯元数据。

## 五、文件范围与计量口径（A607/A608/A609）

| 计量 | 值 | 说明 |
|---|---|---|
| 研究数 | 25（入选）/ 44（替换池）/ 553（范围外） | 研究数≠文件数≠片段数 |
| 方案文件数 | 25（每研究 1 份完整 Protocol 或 Protocol+SAP 合并版，选最新版本，理由逐项记录） | 合并文件仅可靠定位的方案部分进入语料，方案自身统计/伦理章节保留（A608）；独立 SAP/ICF 不下载（A607） |
| 独立 SAP 等不下载文件数 | 16（入选范围内） | 下载调用计数=0 |
| 计划下载调用 | 25 | 只绑定选定范围 |
| 片段数 | 未计（null） | 片段只在抽取后存在；不从元数据编造，三口径分别计量（A609） |
| 需人工上传研究数 | 0 | 入选 25 项元数据中均有方案文件 |

## 六、K3 574 项失败条目 → 真实研究映射（只读勘察，重放维持暂停）

K3 批 `wref_translation_batch_79e7f4e51e7270b75688e8e9`（项目 `proj_user_fad9f64f3151`）实读：830 条 = **574 failed_retryable + 256 excluded**，落在 **7 项真实研究**上：

| NCT | 失败条目 | 排除条目 | 与本次 shortlist 关系 |
|---|---|---|---|
| NCT02176291 | 1 | 0 | selected |
| NCT02376257 | 1 | 5 | replacement_pool |
| NCT03113968 | 45 | 16 | selected |
| NCT03185819 | 384 | 47 | replacement_pool |
| NCT03283670 | 7 | 32 | selected |
| NCT03352453 | 63 | 33 | replacement_pool |
| NCT03446846 | 73 | 123 | replacement_pool |

- 574 项失败条目中 **53 项属于本次入选范围研究**（NCT02176291 / NCT03113968 / NCT03283670），是未来恢复的候选对象；**521 项落在替换池研究**（NCT02376257 / NCT03185819 / NCT03352453 / NCT03446846），若最终范围采用本 proposal，这批不需要恢复；**0 项落在分诊排除范围**。
- 按红线：大批量重放维持暂停，本映射只回答"574 条目对应哪些真实研究/版本、哪些值得恢复"，**不构成放量许可**。

## 七、测试与证据（本批实际执行）

- 定向测试：`pytest tests/test_medical_writing_discovery_shortlist.py` → **21 passed**（worktree `protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313_g6worktree`，分支 `g6-shortlist-0927v1`，基线 5b4c8c1）。覆盖 A601/A602/A603/A604/A605/A606（API 级）/A607/A608/A609/A610 + A16/A21 纯度与确定性 + 契约守卫（target 19/31 拒绝、重复 NCT 拒绝、缺参考日期拒绝）。
- 过程反例（先红后绿，均有当场输出）：①7 项合成研究被误并 1 项（token 正则丢数字）→ 修复 `_tokens`；②"week 24" 写法漏提取 → 补 `_WEEK_POST_RE`；③项目事实"II期"与注册"PHASE2"误判为差异（真实运行暴露，全部 25 项假差异）→ 修复 `_normalize_phase` 中文期数折叠，并加回归测试。
- 本轮未跑全量测试（按红线5，只跑定向子集）；FAST/REPLAY 车道零模型要求满足（模块无任何模型/网络依赖，测试 0.37s 完成）。

## 八、边界与如实未做（NOT_RUN/BLOCKED）

- **A606 的 UI 部分**（确认卡片交互）未做——本批只交付纯函数级整组采用+个别替换；接线到 journey/repository/main.py 属共享文件，按红线4留给单一集成人整合。
- **A607 入口集成级**（真实下载调用计数核查）、**A609 的 UI 展示**未做。
- 独立 SAP/ICF"零下载"当前是**计划口径**（planned_download_calls=25，范围提示不含独立SAP/ICF）；下载路径的既有准入门在 `writing_reference_preparation_batch.py`（ALLOWED_DOCUMENT_TYPES），本批未改未验其运行时行为。
- 相似度权重（人群5/目的4/终点4/设计3/分期3/机制3/药物类型3/对照3/途径2/疗程2，弱匹配半分）为可配置默认值，医学合理性待医学负责人复核后可调；unknown 不罚分、只有明确相反证据才计差异（A604）。
- 8002 MTPLX 缺席与本批无关（全程零模型）；LIVE 项无涉及。

## 九、产物清单

- 本文档：`runs/requirements_v2_20260919/t17_round20_0927v1/g6_shortlist.md`
- 入选 proposal（机器可读全量）：`.../t17_round20_0927v1/g6_private/g6_shortlist_proposal.json`
- K3 574 映射：`.../t17_round20_0927v1/g6_private/g6_k3_574_mapping.json`
- 运行脚本：`.../t17_round20_0927v1/g6_private/run_g6_shortlist.py`
- 选择器源码：分支 `g6-shortlist-0927v1` — `services/api/app/medical_writing_discovery_shortlist.py`（新文件，未触碰任何共享文件）
- 测试：分支 — `tests/test_medical_writing_discovery_shortlist.py`（21 项）
- 真实元数据 fixture：分支 — `tests/fixtures/protocol_v3/g6_discovery_k3_snapshot_candidates.json`（622 项，只读复制自 isolated_runtime 快照）
