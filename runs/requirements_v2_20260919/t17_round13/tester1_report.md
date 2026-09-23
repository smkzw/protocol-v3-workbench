Working...
# T17 第十三轮独立端到端测试报告（测试者1 · COPD C7 II期）

SOURCE_HEAD=`8fbcaca758fdf9dbad91cfab6a0bdbd8f58f165f`
测试窗口：2026-09-23 14:06:35Z → 14:10:02Z（约3.5分钟）。全部交互经 ego lite 真实点击/查看；未改仓库任何代码；未直连后端API/DB/文件系统（除读取夹具路径用于上传控件外）。

## 顶线结论

写作链在入口即被**版本门禁硬阻断**，重试与换路均无法进入：`前端 web-6cad5f5cd01adc03 期望后端 api-c2e8194ba29bb425，当前后端 api-7286ca732cdc2ee0，合同 medical-writing-api-2026-07-17.1`。按追加纪律已用界面重试控件重试（重新检查×2、继续处理×2），仍为死路。下游全部链路未跑。

## PASSED / FAILED / NOT_RUN（含耗时与点击数）

全程真实点击约13次（≤20达标；计数含 evaluate 内页点击；上传 setInputFiles 与 reload 不计入点击）。

### PASSED
- 打开前端 `http://127.0.0.1:5186`，标题"康哲 AI 医学经理工作台"正常（~4s，0点击）
- 项目总览显示 `monitoring_principal_unavailable (HTTP 503)`，确认为已知非缺陷，按指引继续（0点击）
- 点击"医学写作"→ 版本门禁页完整呈现前后端构建号与合同号（~3.6s，1点击；截图01）
- "重新检查"重试一次，门禁依旧（~4s，1点击；截图02）
- reload 后重进"医学写作"，门禁持续存在（2轮确认；截图03）
- 来源台账可进：0条记录＋"服务器验证身份尚未接入…读取已阻断"（1点击）
- 证据调研与方案设计："功能未配置"；审批中心："无待审批事项，不用演示项填充"（各1点击）
- 新建项目对话框打开；"从零开始/导入方案摘要"双入口可见（1点击；截图04/05）
- 上传夹具 `synthetic-reference.docx`（1KB识别正常；截图06）
- 从零开始建项：药物=C7口服PDE3/4抑制剂2mg BID、适应症=COPD、分期=II期，项目创建成功，编号 `MW-II-15398F5A`，头部显示适应症/草案/医学写作来源（~5s，约4点击含下拉设置；截图10/11）
- 建项后"重新检查"再试，门禁依旧（~5s，1点击；截图12）

### FAILED（含耗时与点击数）
- "导入并提取"方案摘要 → `方案摘要解析失败。已完成的解析进度仍会保留，您可以继续处理。`（~3s，1点击；截图07）
- 重试"继续处理" → 错误文本变为 `synopsis import route configuration changed after task start`（~5s，1点击；截图08）
- 再次"继续处理" → 同一英文错误复现（~8s，1点击；截图09）
- 点击"医学写作"进入工作区 → 始终被版本门禁拦截，写作工作区一次都未进入（3次进入尝试均失败）

### NOT_RUN（被上游死路阻断）
上传后逐项确认、准备写作材料、竞品分诊、事实拆解、初稿生成、保存、导出Word、浏览器Office打开编辑；重点模块(a)文献引用管理、(b)目录与图表、(c)研究流程示意图的全部逐项操作验证。

## 问题清单

**P0（阻断整链，1项）**
- P0-1 版本门禁阻断医学写作工作区：期望后端 `api-c2e8194ba29bb425` vs 当前 `api-7286ca732cdc2ee0`。复现：前端→医学写作→门禁；"重新检查"×2、reload、重建项目后仍同错。截图：`/tmp/t17_r13_tester1/01_mw_version_gate.png`、`02_after_recheck.png`、`03_mw_gate_persist.png`、`11_after_create.png`、`12_recheck_postcreate.png`。

**P1（内部信息直出，1项）**
- P1-1 导入失败文案向用户直出英文内部路由信息：`synopsis import route configuration changed after task start`（中文用户面应为中文业务文案；且与首次失败文案不一致，疑似泄露内部路由状态）。复现：新建项目→导入方案摘要→上传夹具→导入并提取→继续处理×2。截图：`/tmp/t17_r13_tester1/07_extract_result.png`、`08_retry_continue.png`、`09_retry2.png`。

**P2（0项）**——本次未发现纯显示/文案类可独立确认的问题；占位提示"例如 类风湿关节炎"为静态输入 hint，非正文拟合，不记缺陷。

## 重点模块(a)(b)(c)结论表

| 模块 | 结论 | observed/缺失说明 | 最小期望 |
|---|---|---|---|
| (a) 文献引用与管理 | 缺失（未可达） | 写作工作区从未进入；全站未见文献/引用入口（导航仅9个模块，无文献管理） | 正文支持 `[n]` 插入、自动连续编号；删/移段落后编号与文末文献表联动重排；点击编号可定位到文献表条目及来源台账 |
| (b) 目录与图表呈现 | 缺失（未可达） | 无预览/导出可检；审批中心、台账均无目录/图表 | 可点击跳转的章节目录＋独立的表目录/图目录，编号规则与正文题注一致 |
| (c) 研究流程示意图 | 缺失（未可达） | 未见任何流程图呈现位置（仅访视概念在任务描述中） | 独立于SOA访视表的流程图（筛选→随机→治疗→随访分支），置于研究设计章节内嵌，与正文编号互引 |

## 反拟合检索表

本轮**无任何方案正文产出**（初稿从未生成），23个禁入词全表记"无正文可检，未出现"：子宫内膜异位、甲状腺眼病、肺纤维化、IPF、痛风、CLL、荨麻疹、白癜风、AML、骨髓瘤、便秘、镰状、IgAN、MASH、类风湿、银屑病、强直、干眼、前列腺、结直肠癌、偏头痛、多发性硬化、抑郁症、骨关节炎。唯一与禁入词字面相近的是新建对话框适应症输入框静态占位符"例如 类风湿关节炎"，属UI hint而非生成内容，不计命中。COPD场景依据检查：不可执行（无正文）。

## KNOWN_LIMITATIONS
- 后端真实AI耗时（10–40分钟）未触发：阻断发生在任何AI步骤之前，无等待轮询可做。
- 导出/Office编辑、文献/目录/流程图验证全部未覆盖，缺失结论仅基于"入口不可达＋全站无入口"，非工作区内穷举。
- 未执行 `ego-browser upgrade`（有可用更新提示，为避免污染测试环境未升级）。
- 证据共12张截图均在 `/tmp/t17_r13_tester1/`（01–12，见上文引用）。

完成输出一行：

EXIT=BLOCKED:医学写作版本门禁（期望api-c2e8194ba29bb425/当前api-7286ca732cdc2ee0）阻断工作区进入，导入路由重试亦失败，下游链路不可达

EXIT=0


--- REDISPATCH (runtime gate resynced; 请重新从首页开始完整测试) ---
Working...
# T17 第十三轮独立端到端测试报告 · Tester1 · COPD/C7 II期

## 基本信息
- SOURCE_HEAD：UI未暴露版本/commit。前端 `http://127.0.0.1:5186`，TaskSpace 53，项目 `合成药C7（口服选择性PDE3/4抑制剂，2mg口服每日两次） · 慢性阻塞性肺疾病（COPD） · II期 · MW-II-15398F5A`。无版本显示处。
- 入口：任务要求入口A（夹具 `runs/mw_protocol_v3_v1_1_20260913/browser_functional/synthetic-reference.docx` + 写作说明）。入口A死路后，改用已存在的同场景项目 `MW-II-15398F5A` 继续（未新建成功，无代码修改，全程 ego-lite 真实点击）。
- 总耗时：约 4.5h 主动操作 + 约 2h 分诊/下载等待轮询（25/25 分诊约 103min：14:30→16:13 UTC；下载+首轮语料约 10min；事实拆解 R1+R2 约 18min）。总点击约 85 次（其中事实“采用”单点约 41 次），**>20，未达标**。
- 截图目录：`/tmp/t17_r13_tester1/`（18 因 CDP 超时未生成，其余见下）。

## PASSED / FAILED / NOT_RUN（含耗时/点击）
| # | 步骤 | 结果 | 耗时 | 点击 | 证据 |
|---|---|---|---|---|---|
| 1 | 打开前端 | PASSED | <5s | 0 | space 53, title 康哲AI医学经理工作台 |
| 2 | 项目总览 503 `monitoring_principal_unavailable` | PASSED（已知非缺陷，直接进写作） | — | 1 | 快照原文 |
| 3 | 新建项目对话框（从零/导入摘要） | PASSED | <10s | 2 | 对话框快照 |
| 4 | 入口A：上传夹具→导入并提取 | FAILED | 16s+26s两次 | 5 | `01_import_failed.png` `02_import_deadend.png` `03_import_retry2.png` |
| 5 | 导入失败后“继续处理”重试（含换控件重试一次） | FAILED（仍死路） | 8s+10s | 2 | 同上，返回 `synopsis import route configuration changed after task start` / `方案摘要解析失败` |
| 6 | 选用已存在 C7/COPD 项目 + 进入写作 | PASSED（绕行） | <15s | 3 | `04_writing_landing.png` `05_writing_state.png` |
| 7 | 产品事实：小分子/全身暴露/口服固体制剂/口服 + 自然语言补全场景全部关键设计 | PASSED | ~5min | 6 | `07_product_facts.png` |
| 8 | 提交并拆解 R1 + 逐项采用 | PASSED（伴 transient stale） | ~10min | ~20 | `08_fact_result.png` `09_facts_adopted.png` `10_fact_stale_error.png` |
| 9 | 回答 R1 追问 3 问→R2 拆解 + 采用收敛（reload 后收敛） | PASSED | ~12min | ~25 | `12_fact_answers.png` `13_fact_round2.png` `14_round2_race.png` |
| 10 | AI 竞品分诊 5/25→25/25 轮询 | PASSED | ~103min | 0 | 轮询日志；`已完成 25/25 · 100%` |
| 11 | 查看分诊：保留36/排除754，锁定篮子 | PASSED | ~5min | 3 | `20_lock_note.png`，版本 3→4 |
| 12 | Protocol 下载 4/4，第一轮语料分析完成 | PASSED | ~9min | 0 | `已完成 4/4 · 100%` |
| 13 | 结构与译文确认：监管中文候选批次 | FAILED（死路） | — | 2 | `21_retry_failed.png`；19失败/0生成；重试返回 `document_plan_contract_source_missing_or_ambiguous` |
| 14 | 文献 DOI `10.1164/rccm.201604-0983PP` 导入 | FAILED | 22s | 2 | `15_lit_import_attempt.png`：`文献导入失败：HTTP Error 404: Not Found` |
| 15 | 文献 PMID `PMID: 33957195` 导入（重试控件） | PASSED（内容错配，见P1-5） | 27s | 2 | `16_lit_retry.png`：计入 1 条 |
| 16 | 文献“插入引文” | NOT_RUN（被阻断：`请先在左侧打开文档编辑器，再插入引文`，无编辑器可开） | 3s | 1 | `17_lit_insert.png` |
| 17 | PICOS→设计包→初稿→保存→导出Word→Office编辑 | NOT_RUN（上游翻译死路，无草稿） | — | — | 全程无 `初稿/生成初稿/准备写作材料/事实拆解/导出` 可点；`design模块待AI基于语料生成` |
| 18 | 目录/表目录/图目录/研究流程示意图 | NOT_RUN（无预览/导出可验） | — | — | 见 (b)(c) |
| 19 | 中途服务瞬断 `项目服务暂不可用` reload 恢复 | 观察项（见P2-2） | — | 1 | `19_service_lost.png` |

## 问题清单
### P0（阻断）
- P0-1 入口A导入死路。复现：新建→导入方案摘要→选 `synthetic-reference.docx`→导入并提取→`方案摘要解析失败`→继续处理→`synopsis import route configuration changed after task start`；重选重传再跑仍失败。截图：`01_import_failed.png` `02_import_deadend.png` `03_import_retry2.png`。
- P0-2 语料翻译死路，E2E 终止。复现：锁定790项后→结构与译文确认→`cms_regulatory_zh_v1 当前范围批次：批次失败（符合条件474/已生成0/失败19）`→`仅重试失败项`→`失败项重试未启动：document_plan_contract_source_missing_or_ambiguous`。已用界面重试控件重试一次。截图：`21_retry_failed.png`。后果：已准入证据恒 0，设计包恒 `待语料准入`，无初稿/保存/导出。

### P1（内部直出/数据错配，抠字眼）
- P1-1 来源定位符直出：结构表 `ctgov:NCT03084796:wref_doc_0ea89e…:p45:b5+p46:b2` 等 20 行。截图：`21_retry_failed.png`。
- P1-2 内部错误/契约名直出：`document_plan_contract_source_missing_or_ambiguous`，`document_plan_anchor_filter · 0/2`，`cms_regulatory_zh_v1`。同截图。
- P1-3 事实流内部 revision 直出：`事实应用失败：stale fact intake conversation revision: expected 2, current 3`；`fact intake proposal not found or already decided: p02`。截图：`10_fact_stale_error.png` `14_round2_race.png`。
- P1-4 导入路由内部直出：`synopsis import route configuration changed after task start`。截图：`02_import_deadend.png`。
- P1-5 跨适应症文献污染：COPD 项目用 `PMID: 33957195` 导入成功的是特应性皮炎 `Papp K 等 · 2021 … ruxolitinib cream … JAAD`，计入“项目文献库 1 条可追溯文献”，无 COPD 相关性校验/提示。截图：`16_lit_retry.png`。
- P1-6 枚举直出：事实候选值显示 `small_molecule`、`systemic`（应为中文）。见 `08_fact_result.png` 文本。
- P1-7 内部数字 ID `Prot_000.pdf / Prot_SAP_000.pdf / Prot_001.pdf / Prot_002.pdf` 在已登记文档/结构表直出，无业务名。见翻译页文本。

### P2
- P2-1 事实“采用”只能逐条点（R1约19+R2约22），无一键采用；快速连点触发 P1-3 race，只能 reload 收敛。点击数爆炸主因。
- P2-2 瞬断：`项目服务暂不可用/读取失败/未选择项目`，reload 后恢复（约 1 次，5min 内）。截图：`19_service_lost.png`。
- P2-3 DOI 导入 404 无指引；输入框占位 `PMID: 33957195` 恰为特应性皮炎文献，极易误导 COPD 用户。
- P2-4 790 项候选为原生 `<select><option>NCT…>`，快照点击 `zero-sized bounding box`，只能 JS 设值；用户侧无可用行级详情（标题/申办方/分期不可点）。
- P2-5 插入引文前置条件不明（“先在左侧打开文档编辑器”但本阶段无编辑器入口），文献链在写作前阶段不可验证。

## 重点模块结论表
| 项 | 结论 | observed 行为 |
|---|---|---|
| (a) 文献引用与管理 | 部分存在，未走通 | 入口存在：项目文献库、DOI/PMID/官网链接导入、GB/T 7714-2015、搜索框、手动确认表单。DOI 导入 404 失败；PMID 导入成功但内容为特应性皮炎（错配）；卡片有 PubMed 外链 + “插入引文”按钮，但点击仅提示需先开文档编辑器，无编辑器可开。编号自动/删段联动/定位回源：无初稿，不可验 = 缺失。最小期望：导入时做适应症相关性提示；编辑器占位期禁用“插入引文”并明示前置步骤；有草稿后编号自动连续、删/移段落联动重排、引文可点回文献卡。 |
| (b) 目录与图表呈现 | 缺失（不可验） | 全程无预览/导出/目录/表目录/图目录入口。最小期望：预览与导出 Word 均带可跳转目录（含章节锚点）、独立表目录/图目录（表1-/图1-顺序编号），正文交叉引用可点跳。 |
| (c) 研究流程示意图 | 缺失（未找到） | 工作台无流程图入口（非 SOA 访视表）；无图/文字框/层级呈现；与正文融合度无法评估。最小期望：在方案第3-4章附近给筛选→随机→12周双盲治疗→随访流程图（分组、访视、主要评估时点），与 SOA 表互链。 |

## 反拟合检索表（全文 UI/已见文本检索）
| 词 | 命中 | 说明 |
|---|---|---|
| 子宫内膜异位/甲状腺眼病/肺纤维化/IPF/痛风/CLL/荨麻疹/白癜风/AML/骨髓瘤/便秘/镰状/IgAN/MASH/类风湿/银屑病/强直/干眼/前列腺/结直肠癌/偏头痛/多发性硬化/抑郁症/骨关节炎 | 仅项目选择器中其他项目名命中：银屑病(CMS-D001)、类风湿(RA-GREENFIELD)、抑郁症(2项)、骨关节炎(K3)、多发性硬化(合成药M8) | 均为项目列表既有他项目，非本草稿内容；本链无初稿，无正文拟合可验 |
| 特应性皮炎（非列表词但场景外） | **命中 1**：文献卡 `ruxolitinib cream … atopic dermatitis` 计入 COPD 项目库 | 已记 P1-5；COPD 场景无依据 |
| COPD 相关（FEV1/急性加重/支气管扩张剂/沙丁胺醇/PDE3/4/C7/2mg BID/240例/12周） | 命中：事实拆解逐字回显用户输入 | 有场景依据（用户两轮输入），未见 AI 捏造数值 |

## KNOWN_LIMITATIONS
- 本轮止于语料翻译死路：PICOS/设计包/初稿/保存/导出/Office 编辑/目录/流程图均 NOT_RUN，非“通过”。
- “测试空间已完全清洁”与 observed 不符：项目选择器含 14 个既有项目（含本次 C7 项目 `MW-II-15398F5A`），入口A新建未成功，实际复用旧项目。
- 文献仅试 1 个 DOI + 1 个 PMID；候选 NCT 未逐项点开（行不可点）；Office 侧未触达。
- 单次长会话跨 9-23→9-24，轮询间隔 100–290s，大部分为后端 AI 等待。

EXIT=BLOCKED:语料翻译批次失败document_plan_contract_source_missing_or_ambiguous重试不启动，无初稿/导出，E2E死路

EXIT2=0
