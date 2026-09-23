Working...
# T17 第十四轮独立端到端测试报告（Tester 1 · COPD II期 · C7）

- SOURCE_HEAD：`c3acd77f1054f2e65f8ca638fc027dfc8c01c383`（`fix(protocol-v3): ambiguous document-plan retry parents reclassify onto parentless structural recovery`）
- 项目：C7（合成药，口服选择性PDE3/4抑制剂，2mg BID）· 慢性阻塞性肺疾病（COPD）· II期 · `MW-II-524E8DE3`（从零开始建项，版本7）
- 会话：2026-09-23 17:19 → 19:39 UTC（约140分钟）；前端 http://127.0.0.1:5186；TaskSpace 56；截图 /tmp/t17_r14_tester1/（01–73，共约60张）
- 真实点击数：**21次**（含按纪律要求的各1次重试；达标线≤20，**超标1次**，超标全部来自失败重试）

## PASSED / FAILED / NOT_RUN

| 结果 | 步骤 | 耗时 | 点击 | 证据 |
|---|---|---|---|---|
| PASSED | 开局项目总览503确认为已知非缺陷，按指引点医学写作继续 | ~1min | 1 | 01_landing.png（monitoring_principal_unavailable） |
| FAILED | 入口A：上传synthetic-reference.docx→导入并提取 | ~1min（含1次重试） | 4 | 05_uploaded.png；06_extracting.png"方案摘要解析失败"；07_continue_after_fail.png"synopsis import route configuration changed after task start"；08_retry_import.png重试仍失败 |
| PASSED | 从零开始建项（C7/COPD/II期）+ 属性补全（small_molecule/systemic/口服固体制剂/写作说明全文） | ~3min | 2 | 11_newproject2.png；12_created.png；14_facts_filled.png |
| PASSED | AI竞品分诊全程等待至完成（5/25 16% → 25/25 100%，790候选） | ~54min（17:38→18:32 UTC，多轮1–2min/4–7min轮询） | 0（轮询）+1（刷新） | 16_poll1.png…47_poll14.png；21_refresh_clicked.png |
| PASSED | 手选NCT02242227标记直接竞品；锁定单项成功 | ~2min | 2 | 29_selected_candidate.png；30_marked_direct2.png（"当前已有1项"） |
| PASSED | 确认并锁定全部790项（保留36/排除754）→ 进入原文处理 | ~1min | 1 | 48_triage_done.png；49_confirmed_all.png（版本6，"已开始继续处理原文"） |
| BLOCKED | 文档提取→翻译→语料准入：监管中文候选批次失败19项，"仅重试失败项"返回`document_plan_retry_parent_missing_or_ambiguous`；已准入证据恒0条 | ~67min（18:32→19:39+，仍未解） | 1（重试） | 54_structure.png；55_retry_failed.png；56_poll18.png；72_poll22.png |
| NOT_RUN | 逐项确认→生成完整初稿→保存→导出Word→Office编辑保存 | — | — | 门控：保存草稿/完成第一步/一键采用/02 PICOS/03语料全部disabled |
| PASSED（部分） | 文献导入：DOI 10.1183/13993003.00677-2020失败→PMID:33957195成功1条 | ~3min | 3 | 60_lit_import.png；61_lit_retry.png（404）；62_lit_pmid.png（"文献已加入"） |
| NOT_RUN | 引用插入正文/自动编号/删除联动/定位回源 | — | 1（插入点击被门控拦截） | 64_insert_citation.png"请先在左侧打开文档编辑器，再插入引文"（当前阶段无编辑器） |
| NOT_RUN | 目录/表目录/图目录/跳转锚点/编号规则 | — | — | 无初稿/预览/导出入口 |
| NOT_RUN | 研究流程示意图（非SOA） | — | — | 同上 |
| NOT_RUN | 反拟合正文检索 | — | — | 无初稿可检；仅检索候选列表噪声（见下） |

## 问题清单

- **P0-1 · 入口A夹具导入链死路**：`synthetic-reference.docx`→"导入并提取"→"方案摘要解析失败。已完成的解析进度仍会保留"→"继续处理"→"synopsis import route configuration changed after task start"；界面重试控件重试一次仍失败。复现：医学写作→新建项目→导入方案摘要→选夹具→导入并提取→继续处理→再点导入并提取。截图 06/07/08/09。任务书入口A要求走此链，本轮被迫改用"从零开始" workaround，入口A判FAILED。
- **P0-2 · 语料准入死路，全链阻断**：结构与译文确认→cms_regulatory_zh_v1批次失败（符合条件775/已生成0/失败19，`document_plan_anchor_filter·0/3·100%`，1项规划后排除）；"仅重试失败项"返回`失败项重试未启动：document_plan_retry_parent_missing_or_ambiguous`（重试纪律已执行一次）；已准入证据"0条·尚无作者已确认"；PICOS与语料核对停留在空结论。后果：02/03步骤、保存草稿、完成第一步、一键采用推荐方案全部disabled，初稿/保存/导出/目录/流程图不可达。截图 54/55/66/73。复现：竞品抽屉→结构与译文确认→点"仅重试失败项"。
- **P1-1 · 内部标识符直出**：结构与译文确认表"M11结构与来源定位"列直接显示 `ctgov:NCT03084796:wref_doc_3a24f37e32b514038c77:p45:b5`、`wref_doc_d22cf49ccc559ca66690:p84:b1` 等；运行标识 `Prot_000.pdf / Prot_SAP_000.pdf / Prot_001.pdf / Prot_002.pdf`、锚点 `document_plan_anchor_filter · 0/3` 同屏直出。截图 54。按测试纪律记P1。
- **P1-2 · 文献DOI导入404**：`10.1183/13993003.00677-2020`→"文献导入失败：HTTP Error 404: Not Found"（重试纪律：换PMID:33957195成功，证明导入通道正常，DOI解析/映射有问题）。截图 60/61/62。记P1（ COPD金标准文献DOI失败影响真实用户）。
- **P2-1 · 检索候选首屏噪声大**：790项首屏混入Axatilimab-sclerotic GVHD、Ponesimod-GVHD、Ibrutinib-GVHD预防、Ofatumumab-GVHD、QGE031-慢性自发性荨麻疹(CSU)、Acalabrutinib-CLL/MCL、Ponatinib-CML等多项非COPD条目；AI分诊完成后收敛为36项COPD间接参照（RPL554×4、Tezepelumab、Itepekimab、Mepolizumab、MEDI3506、AZD4831等，全部PHASE2 COPD相关）。属检索召回噪声、AI分诊已纠正，不记拟合缺陷。截图 25/26/28。
- **P2-2 · 服务两次瞬断需reload恢复**：18:0x与19:2x两次出现"项目列表读取失败·工作台服务未连接"（截图32_poll6/67_poll21/68）；reload后恢复，COPD项目与版本7、分诊锁定、文献1条均保留。开局503为已知非缺陷，未计入。
- **P2-3 · 文献库无适应症相关性提示**：PMID:33957195（ruxolitinib cream特应性皮炎III期）可无警告导入COPD项目文献库并显示PubMed外链与"插入引文"；用户自选责任为主，但系统无"与本项目适应症不一致"提示。截图 62/63。

## 重点模块结论表

| 模块 | 存在性 | observed行为（逐步） | 结论 |
|---|---|---|---|
| (a)文献引用与管理 | 入口存在，链路半通 | 项目文献库显示"0/1条可追溯文献"；DOI/PMID/官网链接输入框+导入按钮+GB/T 7714-2015固定格式+搜索框均可见；DOI导入404失败，PMID导入成功显示作者/题名/期刊/卷期页码/DOI/PubMed外链+"插入引文"；点"插入引文"返回"请先在左侧打开文档编辑器，再插入引文"，当前阶段无编辑器；已准入证据0条 | 部分验证：导入通道OK（PMID）/DOI映射坏；**编号自动、删除/移动联动、定位回源均NOT_RUN**（无正文可插）。最小期望：初稿编辑器内选中文字→插入引文→顺序编号→文献表自动追加GB/T条目→点击编号回跳文献表/来源链接；删除段落后续编号自动前移 |
| (b)目录与图表 | 缺失（本阶段无入口） | 全页按钮枚举无目录/导出/预览/表目录/图目录；"准备写作材料/生成初稿/导出"零命中 | **缺失**。最小期望：预览/导出含可跳转目录（含章节锚点）、表目录、图目录，表注"表1/表2…"、图注"图1/图2…"按章或全文顺序编号 |
| (c)研究流程示意图 | 缺失（本阶段无入口） | 同上；翻译阶段出现"NCT05492877/研究流程与访视"处理中字样，但用户侧无图可看 | **缺失**。最小期望：研究设计章内嵌独立流程图（筛选→随机→双盲治疗12周→主要终点访视→随访），非SOA表格，图文同页融合 |

## 反拟合检索表

| 词 | 正文命中 | 备注 |
|---|---|---|
| 子宫内膜异位/甲状腺眼病/肺纤维化/IPF/痛风/CLL/荨麻疹/白癜风/AML/骨髓瘤/便秘/镰状/IgAN/MASH/类风湿/银屑病/强直/干眼/前列腺/结直肠癌/偏头痛/多发性硬化/抑郁症/骨关节炎 | 无正文可检（初稿NOT_RUN） | 检索候选列表含CLL（Acalabrutinib-CLL/MCL）、荨麻疹（QGE031-CSU）条目，属检索噪声非正文拟合；AI分诊已排除（754项排除中）；项目内唯一文献为特应性皮炎系用户自选PMID导入，非系统生成 |
| COPD场景依据 | 框架/候选/COPD写作说明一致 | 适应症COPD、II期、C7 PDE3/4 2mg BID、随机双盲安慰剂对照12周、FEV1谷值主要终点、加重年化率次要、240例、长效支气管扩张剂背景+沙丁胺醇急救均以用户输入为准；36项保留参照全部COPD II期相关 |

## KNOWN_LIMITATIONS

- 本轮止于语料准入：初稿/保存/导出/Office编辑/目录/流程图/引用联动均未进入，非"通过"，判BLOCKED。
- AI分诊/提取/翻译真实耗时：分诊约54min（5/25→25/25），提取+翻译+准入等待67min+仍未完成；轮询间隔1–7min，未打断。
- 文献DOI 404 vs PMID成功：通道正常，DOI解析需修。
- 浏览器仅ego-lite真实点击，未直连后端/API/DB/文件（除夹具上传与截图落盘）。

EXIT=BLOCKED:语料准入死路（document_plan_retry_parent_missing_or_ambiguous，19项失败不可重试，已准入0条），初稿/导出及模块(b)(c)不可达

EXIT=0
