# 医学写作子系统 Protocol v3：完整工程交接
生成日期：2026-09-11（Asia/Shanghai）  
交出任务：医学写作子系统（恢复），019fb62b-2a50-7ed0-8fb6-e66bbeb8e641  
文档用途：让接手 Agent 了解完整背景、当前事实、已批准变更、准确续作边界和剩余工程；本文件不是产品完成证明，也不自动启动实施。

## 0. 接手前先读这一页

**现在停在 Task 3R.3：逐章节内容合同。3R.1 模板抽取、3R.2 合同 schema、3R.3 检查器核心已有各自验收；首批内容修复尚未验收，第二批尚未交付。产品远未达到完整方案生成、前端与原生 Word 最终验收。**

- 当前原生 Goal 是 paused。2026-09-08 用户明确“无损暂停”；9月11日只要求编写交接。本轮没有恢复 Goal、执行者、产品模型、测试、服务或 Word。
- 正确实施区是 [/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.>)。不要在 live workbench 构建，也不要从最初 r42 translation planner 继续。
- 当前 main 的 HEAD 为 3d6772f1014f2a86f96eb3dae4fd878c70a5251c，26个提交。大量已完成及在制工作尚未提交；只克隆此 HEAD 会丢掉9月续作成果。
- 本轮核对暂停快照73项及收尾清单4项，去重并以收尾版本覆盖后共74个文件：全部与现文件一致。7项权威文件哈希也一致。这只是选定范围的核对，不代表全仓、所有外部文件和 live 无变化。
- 当前存在12个 chapter_contracts、12个 chapter_skills、首批52条 fixture；第二批 fixture 不存在。12/111 是部分覆盖，并且这12个内容仍待修复验收，不能写成“12章完成”。
- **新增恢复缺口：暂停时原位保留的两个 ZCode model-io 日志，9月11日在原路径均不存在。** 对 ~/.zcode 与 Documents/AI Cache 的限定文件名搜索未找到搬移副本；不能推断删除原因或声称所有备份已搜尽。两个原生 session 数据库记录仍存在，但不等于会话历史完整或保证可续接。
- 开工授权后，先对账两个 logical work key 和原生 session 可用性，再继续首批修复与第二批；不重跑 R/1R/2R/3R.1/3R.2，不重复1R.6产品连通性探针。
- 用户已经明确排除纯安全工程及其测试。Task 1R.5 是 USER_EXCLUDED，不是 PASS。旧安全门不得成为阶段暂停点。科学性、事实真实性、高风险人审、稿件保存恢复与实际功能正确性仍须实现。
- 用户要求连续推进；常规阶段报告、执行者终态、测试通过，都不是让用户再次说“继续”的理由。只有用户主动暂停、Ⅰ期模板等真正需要其决策之处才停。

本次工作方式：direct。交接是当前文件、Goal 与既有证据的事实整理，不重新派发工程/会商，不对未完成产品作新的主观验收。

### 0.1 本交接包

| 文件 | 用途 |
|---|---|
| 本文 | 全局背景、状态、工程路线、当前恢复步骤 |
| [GOAL_CURRENT_VERBATIM.txt](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/GOAL_CURRENT_VERBATIM.txt>) | 9月11日从正式 Goal API 读取的 objective 原文，保留原始内容 |
| [goal_snapshot.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/goal_snapshot.json>) | Goal 状态、任务ID、时间戳与同一原文；没有改写应用状态 |
| [current_state_verification.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/current_state_verification.json>) | 当天 SHA-256、Git、Trellis、章节数量、原日志缺失的机器可读核对 |
| [session_recovery_availability.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/session_recovery_availability.json>) | 原生 ZCode session 的只读元数据检查；不含私有消息正文 |
| [git_status_at_handoff.txt](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/git_status_at_handoff.txt>) | Git 状态清单；untracked 条目可能是整个目录 |
| [tracked_worktree_at_handoff.patch](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/tracked_worktree_at_handoff.patch>) | 已跟踪文件的工作树差异，仅辅助核对，不能恢复全部未跟踪成果 |
| [verify_handoff_state.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/verify_handoff_state.py>) | 本轮核对脚本，只读来源并写本交接目录，不导入产品代码 |
| [artifact_manifest.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/artifact_manifest.json>) | 本交接包最终文件哈希与大小 |
| [document_validation.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/document_validation.json>) | 链接、Goal逐字一致、章节和包校验结果 |

交接包不能代替原隔离区。新 Agent 若不在同一台机器，需要完整转交未提交源码、Trellis任务、合同、prompt/report及相关证据；不要仅传 git diff，也不要打包凭证、真实运行库或整个私有会话数据库。

## 1. 任务为什么存在，如何发展到现在

### 1.1 产品最初目标

用户是资深医学写作人员，熟悉医学研究，却不希望学习计算机、模型、提示词、编排和运维。目标不是一个“AI聊天加富文本框”，而是一个个人本地研究方案工作台：导入已有资料，AI提取事实、补充检索、形成研究设计推荐，用户点选和确认，AI写出完整正文，最后给出格式完善的 Word 与文档就绪材料。

旧系统已经积累了大量真实资料处理、竞品研究方案筛选、OCR/翻译、写作、编辑、导出和测试实现。但页面/后端单体大、事实和状态分散，出现空骨架、来源与正文脱节、重复确认、保存/重试状态不清、生成不等于可申报等问题。新系统因此采用 Protocol 专属领域合同和五类职责，逐步替换旧链，而不是抛弃所有历史成果或原地大改 live。

### 1.2 时间线与权威变化

| 时段 | 发生的事 | 对接手者的含义 |
|---|---|---|
| 2026-07-24至30 | 原医学写作父任务推进旧系统 r42 | 是产品来源及问题历史，不是当前续作位置 |
| 2026-07-31 | 原父 JSONL 与索引已删除，创建证据重建替代任务 | 不能声称恢复了原始逐条对话；现任务 lineage 指向原父 |
| 2026-08-08/09 | 设计多 Agent 重构，冻结 Implementation Plan，在独立 source-only 区构建 | 当前隔离目录及原 Phase0–8 编号的来源 |
| 2026-08-12 | Phase1及 Task2.1 离线合同推进后无损暂停，HEAD 3d6772f | 旧 Task2.2不是9月重锚定后的直接起点 |
| 2026-09-05 | 另一 Agent 整理 design-v1.3、Plan v2、handoff，用户批准DC-019至DC-030 | 新模板、简化路线、GLM默认、R阶段等取代旧计划相应部分 |
| 2026-09-05之后 | 本任务完整工程review、独立审阅、PhaseR、1R产品接线与修复、Trellis接入 | 老review中“无SQLite/未挂载”是当时基线，后续已实现 |
| 2026-09-06起 | 2R.1 typed facade验收；3R.1模板抽取、3R.2 schema、3R.3核心验收；准备8批内容 | 重心从基础设施转向真正的逐章内容义务 |
| 2026-09-08 09:34 | 用户要求无损暂停，首批修复和第二批runner被明确停止 | 工程未完成；保存未验收修改、会话血统、原测试失败证据 |
| 2026-09-11 | 用户要求移交，本轮只读重锚定并编写本文 | Goal当前paused；发现原始模型日志路径缺失，新增如实记录 |

历史原父ID：019f92f7-8268-7f00-9544-9b7c61ae5128。恢复组织任务来源：019fb615-3845-7033-96c4-f4a80553eda6。现在的工程续作任务：019fb62b-2a50-7ed0-8fb6-e66bbeb8e641。

### 1.3 r42 的遗留成果与不可重复阶段

[CONTINUE_MEDICAL_WRITING.md](</Users/smkzw/Documents/AI Cache/Codex x Hermes/runs/medical_workbench_session_recovery_20260731/CONTINUE_MEDICAL_WRITING.md>)、[RECOVERY_MANIFEST.md](</Users/smkzw/Documents/AI Cache/Codex x Hermes/runs/medical_workbench_session_recovery_20260731/RECOVERY_MANIFEST.md>)、[recovered_thread_metadata.json](</Users/smkzw/Documents/AI Cache/Codex x Hermes/runs/medical_workbench_session_recovery_20260731/recovered_thread_metadata.json>) 保存了重建依据及原父记录。其当时状态：

- 项目 MW-III-1A3A1248；外层分诊19/19，候选665/665并锁定。
- 90个Protocol/组合文件准备；独立SAP不进入Protocol语料。
- 89个OCR pass、1个经医学确认保留残余问题；10704个Protocol spans合格，29910个SAP spans排除。
- translation batch为2 ready、13 excluded、5 retryable failed。生产持久化executor没有接入同模型一次结构纠错重试，错误码被泛化。
- 当时尚无完整corpus、全文、DOCX、原生Word验收意义上的PASS。

这些是2026年7月的历史证据。9月的Protocol v3计划已经改换实施主线，**当前不能据该续接提示重启五个失败项，更不能重新分诊、下载、OCR或写旧运行库。** 日后4R迁入旧资料时，必须用当时现状、来源身份和可复用性对账；不能把历史计数当新产品已经完成。

## 2. 目标、范围与用户体验合同

### 2.1 最终交付是什么

一个适合该用户个人使用的 Protocol 工作台，完成“资料→已确认研究事实→有依据的设计推荐→完整研究方案→受控修改→QC→原生 Word→文档就绪导出”。默认首先覆盖已确定模板的Ⅱ/Ⅲ期；Ⅰ期模板在3R.6由用户选择后纳入。

正式成果应具备：模板规定的实质正文、跨章节医学和统计一致性、可追溯的关键事实与引用、可编辑的表格/访视表/图与附录、真实版本与保存恢复、可复算样本量依据、受控原生Word排版和回流。eCTD仅指文档就绪；没有自动取得正式申报批准、专业签字或完整申报序列验证。

本项目不是扩建CTMS、CSR平台、预算/采购系统、多租户身份平台、通用Agent平台或电子签名平台。独立Synopsis导出、方案修订管理/T07、审评回复、竞品比较等按计划列为后续延伸，不挤占当前完整Protocol闭环。

### 2.2 已批准的用户体验要求

| 领域 | 当前要求 | 设计含义 |
|---|---|---|
| AI lead | AI先读材料、提事实、给推荐、写完整初稿 | 少空表、少自由填写、少“请用户逐项研究” |
| 操作预算 | 标准Ⅱ/Ⅲ期关键路径≤20次点击、≤5个必填自由文本 | 包括适用高风险确认、原生文件选择/保存；旧15/3是历史/优选预算 |
| 可读性 | 正文≥14px、UI≥12px；优先16/14px | 用实际computed字号、页面与缩放验证，不能只数CSS |
| 推荐 | 默认预选，但未确认 | 低风险可合并确认；高风险必须单卡 |
| 高风险 | 主要终点、estimand及ICE、样本量假设、对照、NI界值、期中及alpha、剂量、核心人群 | 8类逐卡人审，监管答辩级红tag；理由由AI写好，可修改，无“至少10字” |
| 信息层级 | 一屏一个主动作、主界面安静清晰 | 技术trace、hash、模型身份放可展开详情，不能占正文 |
| 异常 | 解释影响、保留内容和可行下一步 | 不显示一串技术码后要求重来；失联先查原任务结果 |
| 变更 | 只重开受影响的确认和章节 | 不因为局部改字让整份方案重生成 |
| 成稿 | 正文零占位符、零待确认、零生成过程话术 | 真实缺口在侧栏解决；不能掩藏缺口冒充完整正文 |
| 长任务 | 可恢复，显示真实业务阶段及进度依据 | 不虚构百分比，不让用户手动管理每个子Agent |

红tag用于实际医学/统计重大决策，不把所有工程细节变成红色警告。终稿“零AI痕迹”指没有生成过程文字，不是删除内部溯源或伪造人工来源。

## 3. 权威层级与已经决定的事项

### 3.1 阅读顺序

1. 最新 [AGENTS.md](</Users/smkzw/.codex/AGENTS.md>) 与 [AGENTS.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/AGENTS.md>)。项目文件保留了历史路由表，以最新全局机制和用户决定为准。
2. [mw_protocol_v3_design_v1.3_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/../plan-upgrade-20260905/mw_protocol_v3_design_v1.3_20260905.md>)、[mw_protocol_v3_implementation_plan_v2_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md>)、[mw_protocol_v3_execution_handoff_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/../plan-upgrade-20260905/mw_protocol_v3_execution_handoff_20260905.md>)。
3. [plans/mw_protocol_v3_review_amendment_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/mw_protocol_v3_review_amendment_20260905.md>)。它追加了用户批准变更、review修正和科学来源更正。
4. [runs/MW_PROTOCOL_V3_3R3_NO_LOSS_PAUSE_20260908_0934.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/MW_PROTOCOL_V3_3R3_NO_LOSS_PAUSE_20260908_0934.md>)，当前 [.trellis/tasks/09-06-protocol-v3-3r3/task.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-06-protocol-v3-3r3/task.json>)、[.trellis/tasks/09-06-protocol-v3-3r3/checkpoint.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-06-protocol-v3-3r3/checkpoint.md>)，再看本交接的当天差异。
5. [plans/mw_protocol_v3_execution_tracking_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/mw_protocol_v3_execution_tracking_20260905.md>) 只作索引；其历史表不能覆盖文件顶部的当前Trellis指针。
6. [.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md>) 中未被替代的Files/Micro-steps/Gate，按当前任务逐段继承。

不是“最新文件日期总是压倒一切”。用户当前明确决定具有优先性；正式Plan管理任务，Trellis管理执行；review结论、模型回复、日志和本文是证据与导航，不自行赋予新授权。

### 3.2 不要再重复询问或重新争论

| 旧要求/疑问 | 用户已决定或当前适用状态 |
|---|---|
| 1R.1–1R.5禁止模型是否连工程review也禁止 | 只禁止产品真实调用；工程审阅subAgent可运行 |
| 1R.4直接删除旧状态/字段 | 改为简化实现与展示，保留恢复、去重、过期检测、安全语义及必要兼容层 |
| 旧“不得main挂载”和schema-v1阶段断言 | 允许升版；用新的阶段合同验证，不把过时断言当永久禁止 |
| 纯安全工程/测试和安全阶段门 | 用户排除；1R.5 USER_EXCLUDED/NOT_EXECUTED；不得换名重新加入 |
| 其他旧约束挡实施 | 评估科学性/功能影响，记录理由及替代依据，可废弃，无须反复请示 |
| PyMuPDF许可讨论 | 个人本地使用获准，不再成为阻断；隔离环境记录依赖，不污染live/全局 |
| Trellis | 用于PRD/上下文/状态/验收，保留任务编号；不另造一套调度器 |
| 阶段暂停 | 不暂停；已授权范围内连续实施，真实用户决策点才询问 |
| 长任务慢 | 不是失败；长hard wait、完成事件、必要lease心跳，保持同一运行血统 |
| 默认产品模型 | glm-5.3-flash，thinking=max；同omp zhipu-coding-plan凭证来源 |
| 备选模型 | deepseek-v4-flash(max)仅可配置备选，切换须用户确认，不能静默fallback |
| OCR/翻译 | PaddleOCR-1.6-vl官方服务、Hy-MT2-30B-A3B-oQ8-MLX，共享oMLX workload gate |
| 权威模板 | TP-MA-07清洁版v2.0；旧版仅作历史映射 |
| 点击/自由文本 | 当前硬指标20/5；不要被旧文件15/3覆盖 |
| 历史清理 | 不自动清理；只检查冗余体积，清理另需明确授权 |
| 当前暂停 | 9月8日明确暂停优先；9月11日写交接不等于恢复实施 |

科学章节中的安全性（AE/SAE、获益风险、报告、停药等）是研究方案正文必需内容，与被用户排除的网络/权限等纯安全工程不是一回事。保持凭证不落盘、保护无关live和不伪造证据也是既有边界，不据此新增安全项目。

### 3.3 原始 Goal 中的过时句子

本交接附录逐字保留当前Goal，而不是悄悄润色。它仍写“从Trellis及1R.2开始”，但任务已经推进到3R.3；仍保留“不得降gate”等早期通用用语，后续用户已经允许科学性不受损的阶段约束升版，并排除纯安全工程。接手时用本节及当前Trellis解读，不倒退重做1R.2，也不修改原文来掩盖历史。

## 4. 当前工程完成度：逐项可用的事实

### 4.1 总体状态矩阵

| 工作 | 当前判断 | 已有成果 / 尚不代表什么 |
|---|---|---|
| 历史Phase0 | 已有离线工具链、隔离、失败corpus、Word PoC证据 | 不是当前v3端到端产品Word验收 |
| 历史Phase1/Task2.1 | 有已冻结合同与验收 | 不是5个Agent产品全部实现 |
| R.1/R.2/R.3、H-R | 已接受 | 路径修复、source drift对账、测试环境脆弱性修复；不合并live |
| 1R.1 | 已接受 | 真实产品SQLite adapter，迁移约束、原子性等经多轮修复 |
| 1R.2 | 功能独立验证已完成；Trellis状态仍in_progress | actual main默认off挂载已实现；状态遗留待按证据对账 |
| 1R.3 | Trellis completed | 实际API/SQLite/reopen/replay/备份恢复/错误分类等集成 |
| 1R.4 | Trellis completed | 简化结果存储与依赖合同，保留旧语义；持久化reservation接线 |
| 1R.5 | USER_EXCLUDED | 用户不要求实施；不能记成测试PASS |
| 1R.6 | Trellis completed，单次产品探针SUCCEEDED | 默认模型profile/传输；不是真实方案生成测试 |
| P1R integration | completed，带明确scope disposition | 允许继续offline构建，不代表全仓零失败或产品发布 |
| 2R.1 | 已接受 | typed facade三类真实持久化离线case及kill/recovery |
| 2R.2 | 可选spike未执行 | 保留typed facade；没有理由为“多Agent”另加框架 |
| 3R.1 | 已接受candidate抽取 | v2注册候选/精确树/映射，不等于切换运行模板 |
| 3R.2 | 已接受schema | ChapterContractV2等结构，不等于正文语义完整 |
| 3R.3 core | 已接受限定版本 | 实质字段/来源组/覆盖结构检查核心，不是医学完整性自动判定器 |
| 3R.3 batch1 | 修复中，未验收 | 12合同+12技能+52fixtures保留；6类主审内容问题待复核 |
| 3R.3 batch2 | 已启动过，暂停；尚无交付 | 16载体的执行合同与原session保留；不能记成未派发 |
| 3R.3 batch3–8 | 来源准备已写，尚未实现验收 | 内容spec是输入，不是已完成合同 |
| 3R.4–3R.7 | 待实现 | 依赖图/R03/Ⅰ期决策/术语；3R.4仅准备文档 |
| 4R–8R | 待实现和真实验收 | 资料链、推荐、写作、编辑器、QC、Word、切换/E2E |
| 最终用户产品目标 | 未达成 | 不可称现在已能生成申报级完整方案 |

### 4.2 可恢复状态与未提交风险

9月11日保存Git状态时：31个已跟踪修改条目、318个untracked普通条目（含本交接目录，目录条目不等于文件数量）。HEAD仍停留8月暂停基线。**当前工程成果主要在工作树，而非新commit。** 不执行reset、stash、clean，也不要git add全部把venv、运行证据和私有数据混入提交。

Trellis的00-bootstrap-guidelines仍in_progress；这意味着生成的通用规范模板并未全部填写，不是Trellis完全没装。execution_tracking明确记录0.6.14初始化。已有任务PRD/design/implement/checkpoint为实际工作入口。恢复后可以整理状态一致性，但不能用“修看板”替代继续产品实现。

1R.2仍in_progress的元数据写着functional_review已验证、full_repository_reconciliation待P1R-G1前处理；后续已有P1R scoped disposition完成。应对照真实acceptance与任务定义，把遗留状态清楚标注/收束；不能擅称全仓已经PASS，也不应因一个旧状态重复挂载实现。

### 4.3 关键验收证据和测试数字应如何理解

| 检查 | 历史结果 | 范围与限制 |
|---|---|---|
| PhaseR聚焦 | 183 passed | 路径/漂移/探针等；主执行及独立review复现 |
| PhaseR protocol_v3 | 1240 passed +101 subtests | 不是全仓、浏览器或真实产品模型验收 |
| 1R.1最终存储 | 140 focused；1372 passed+101 subtests；另2独立闭合探针 | 早期失败保留；最终绑定存储版本 |
| P1R全仓维护套件尝试 | 7420 passed、167 failed、18 errors、1 skipped | 不能改写为全仓绿；明确旧链/历史/监查范围处置 |
| 三项历史工具测试 | NOT_EXECUTED | cross_indication_quality_scorecard_schema、phase1_translation_manifest、phase1_translation_runner；不隐藏成skip后称PASS |
| P1R后续模板/ready修复 | 1538 passed；独立119+18 | 按checkpoint实际scope，不与全仓数字混合相加 |
| 2R.1 | 1687 passed，18 warnings，46.33s；独立round3 | 三case产品SQLite持久化离线验收，不是五Agent真实业务闭环 |
| 3R.1 | 51 focused，独立round3 | template候选抽取和映射 |
| 3R.2 | 1745 passed，1 warning，49.3s，独立round2 | schema；v1字节/hash未变 |
| 3R.3 core | 96 focused；1771 expanded，1 warning，48.57s | 只针对核心checker及绑定版本 |
| 主审组装器 | 3RED修复后，连原8项共11PASS；多批4RED→4PASS | 最后一个测试前提修订尚未重跑，不外推章节内容通过 |
| 旧前端StrictMode反例 | 普通1PASS、StrictMode1FAIL | 单组件隔离探针，不是真实浏览器E2E |
| 浏览器全流程 / 原生Word / cutover | 当前未验收 | 不能从pytest、合成回执、React SSR代替 |

以上数字均为9月5至8日记录；**9月11日未重新运行任何产品测试**。这次实际做的是文件/状态/哈希/会话可用性核对。

直接读：[reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md>)、[.trellis/tasks/09-05-protocol-v3-p1r-integration/checkpoint.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-05-protocol-v3-p1r-integration/checkpoint.md>)、[reviews/mw_protocol_v3_2r1_acceptance_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_2r1_acceptance_20260906.md>)、[reviews/mw_protocol_v3_3r1_acceptance_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r1_acceptance_20260906.md>)、[reviews/mw_protocol_v3_3r2_acceptance_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r2_acceptance_20260906.md>)、[reviews/mw_protocol_v3_3r3_core_acceptance_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_core_acceptance_20260906.md>)。旧失败XML、独立反例、runner报告保留在各自runs目录；不能删除来让新报告显得干净。


## 5. 工程架构：每一层为什么存在

### 5.1 业务中的五类Agent职责

这是职责分工，不是要求每章创建一个独立自主Agent，也不是五种模型必须各跑一遍：

| 角色 | 输入、职责、输出 | 当前进度 |
|---|---|---|
| Agent① 研究与证据 | ResearchSeed、公司/外部资料→检索、文件处理、来源准入、可追溯证据与当前指南 | 4R产品链未完成；不能把旧pipeline或schema当新Agent已闭环 |
| Agent② 设计推荐 | 证据与项目事实→临床/统计建议、理由、备选、风险分层卡；确认后进入StudyDefinition | 5R未完成 |
| Agent③ 撰写与编辑 | 已确认事实、章节合同、来源→写作计划、完整章节、全文reducer、局部AI修改 | 6R未完成；3R只准备其写作合同 |
| Agent④ 独立质量审阅 | 当前完整方案与真实证据→typed findings、跨章QC、修复复核 | 7R未完成；区别于本次工程fresh reviewer |
| Agent⑤ 协调与异常 | 管运行状态、依赖、问题卡、阶段编排与输出包 | 部分基础代码存在；不替医学/统计决策，不等于整体产品已完成 |

工程worker与fresh verifier是构建此产品的工具，不能与产品内Agent①–⑤混为一谈。工程GLM完成代码不代表产品GLM完成真实研究方案。

### 5.2 状态与事实：避免重新造一套表单

- StudyDefinition是已确认研究事实的权威；决定在相应内容版本上确认。摘要、图、表、正文从同一事实投影，不给每个地方再造可独立编辑的protocol_id。
- SemanticDocumentRevision承载可定位的正文、表格、引用与版本。整稿采纳应形成单个一致版本；局部修改要说明影响。
- 来源对象、医学准入、claim到evidence的链接各有含义。chapter fixture里的ContentEvidence只是测试载荷，不等于已持久化的EvidenceUnit、MedicalAdmissionUnit、ClaimEvidenceLink。
- 运行记录负责“是否已经执行、结果是否收到、业务是否消费、当前输入是否仍有效”。这些不同事件不能合并成一个“完成”标志。
- 对用户可以把状态简化；内部仍要知道结果未知、明确失败、过期和成功分别是什么，否则会重复模型调用或丢已保存内容。

### 5.3 新后端模块地图

所有相对模块从 [services/api/app/protocol_workflow](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow>) 进入；共享合同在 [packages/contracts/workbench_contracts/protocol_v3.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages/contracts/workbench_contracts/protocol_v3.py>)。

| 模块 | 主要意义与关键逻辑 | 接手注意 |
|---|---|---|
| canonical/study_definition.py、decisions.py | 事实、修订、确认与前置版本 | 保留CAS、确认与内容绑定；高风险“预选”不等于已确认 |
| canonical/document.py、hashing.py | 语义文档、材料身份与canonical hash | 新旧hash版本明确，旧事件字节/身份不重写 |
| ports/repositories.py、unit_of_work.py、artifacts.py | 存储与事务接口 | 产品通过接口使用SQLite；不导入PoC实现 |
| storage/sqlite.py | 产品SQLite及版本迁移、约束、reservation生命周期 | 真实磁盘持久化，不是内存demo；迁移和claim经历了多轮修复 |
| storage/memory.py、selected.py | 显式测试后端、产品工厂选择 | memory只用于明确测试；默认产品不可静默退回memory |
| events/models.py、store.py、unit_of_work.py | 状态重建的事件与同事务提交 | 文件修改不能破坏event与projection一致性 |
| events/outbox.py、inbox.py | 交付、结果接收/消费兼容 | 1R.4已减少重复存储，但旧imports/ports和防重语义需保留 |
| runtime/reservations.py、idempotency.py | logical key、执行占位、尝试与结果恢复 | unknown先对账；不能仅看到缺报告就再次执行 |
| runtime/harness.py | 模型调用合同、身份与执行回执接线 | 不在这里混入监查角色配置或无界fallback |
| runtime/product_profiles.py、omp_credentials.py | 医学写作独立profile、运行时凭证读取 | key只在内存；不能放registry/prompt/checkpoint |
| runtime/adapters/zhipu_api.py | GLM产品真实传输 | 一次最小probe已SUCCEEDED；不要再当首次调用 |
| runtime/adapters其他文件 | Codex/OMP/direct/oMLX等适配边界 | 文件存在不等于每条真实路线均已验证或当前可用 |
| application/commands.py、queries.py、service.py | 业务命令、读模型、事务编排与错误归属 | 行为从这里与真实API核对，不只测试孤立helper |
| application/reconstruction.py | 事件重建与历史兼容 | 损坏不能误判成“重新确认推荐”，提交结果未知不能建议直接重做 |
| api/router.py、schemas.py | 请求/响应合同与路由 | 保留稳定中文业务错误；技术细节不泄到用户主界面 |
| api/composition.py | actual main挂载与产品storage接线 | 默认off；显式产品库配置；懒初始化；持久化项目allowlist |
| graph/plan.py、state.py、ports.py、runtime.py | typed facade和三case持久化执行 | 2R.1完成的是三case，别虚报通用Agent编排完成 |
| registries/loader.py、chapters.py | registry与章节合同加载、lint/内容结构验证 | accepted core范围有限，条件医学判断/真实证据真实性未实现 |
| agent5/coordinator.py、run_manifest.py、exception_cards.py | 控制面与问题卡基础 | 不把工程控制规则全部暴露给用户 |
| artifacts/local_store.py | 制品持久化与定位 | 新稿、Word保存后稿、PDF分别是制品，不相互覆盖 |
| legacy/* | 迁移清单、只读/隔离适配、切换状态与旧入口边界 | 是渐进替换支撑，不代表live已迁移、项目已切换 |

当前实际开关名来自 [services/api/app/protocol_workflow/api/composition.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/api/composition.py>)：

- WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED，默认off；
- WORKBENCH_PROTOCOL_V3_WORKFLOW_DB，仅在显式启用时要求；
- WORKBENCH_PROTOCOL_V3_WORKFLOW_BUSY_TIMEOUT_MS，可配置，默认5000ms。

本文列出名称是为了代码定位，**不要求新Agent现在启用**。最终真实项目activation/cutover仍需明确授权。

### 5.4 旧后端如何看待

旧业务主要在services/api/app/medical_writing_*，例如research_pipeline、competitor_triage、full_draft、study_consistency、template_upgrade、content_quality、durable_store，以及庞大的main.py。旧链有大量功能与真实历史，不应全删，也不应继续往大文件堆新v3业务。

采用渐进替换：通过新包和新入口接线；保留旧项目只读与必要兼容；共享变动检查医学监查消费者；最终8R按最新live状态再对账。9月5日313处source差异、23个共享变化的处置是当时证据，不是9月11日live切换许可。

### 5.5 前端逐组件地图

现有写作页仍以 [frontend/src/App.jsx](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/App.jsx>) 中WritingPage为主。新目录 [frontend/src/features/medical-writing/protocol-workbench](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/frontend/src/features/medical-writing/protocol-workbench>) 目前主要有protocolWorkspaceApi.mjs客户端，尚没有完成的新工作台页面。

| 当前组件/模块 | 它的职责 | 后续处理 |
|---|---|---|
| MedicalWritingAuthoringJourneySetup.jsx | 研究建项/写作旅程入口 | AI预填、主动作与进度整合到6R入口 |
| MedicalWritingSynopsisProjectIntake.jsx | 从摘要/资料导入研究概况 | 修StrictMode挂载状态，减少填写，不把失败变永久spinner |
| LegacyAuthoringBootstrapPanel.jsx | 旧资料/旧状态启动入口 | 保留历史兼容，退出新链主路径 |
| AuthoringCandidatePackagePanel.jsx | 候选方案包、采用与冲突反馈 | 明确采用的范围、事务结果与受影响事实 |
| AuthoringCompetitorDrawer.jsx | 竞品列表/研究资料侧栏 | AI先筛选和组织，用户只处理关键差异 |
| MedicalWritingLiteraturePanel.jsx | 文献/来源展示 | 原文和关键依据就地查看，不让用户管理下载队列 |
| ProtocolModuleResolutionPanel.jsx | 模块适用性/内容选择 | 自动推荐、条件解释；不要逐模块重复确认 |
| InterventionRulesEditor.jsx | 干预、合并/救援/停药规则 | 与StudyDefinition/estimand/SoA同源 |
| StudySchemaEditor.jsx | 研究结构/事实编辑 | 统一事实权威，少重复表单 |
| StructuredTableDesigner.jsx | 结构化表格/访视表编辑 | AI生成可用表格，不从空白逐格搭建 |
| TableCellRichEditor.jsx | 单元格富文本 | 保留语义、可编辑和稳定定位，不能仅图片化 |
| CrossReferenceMark.js、editorSourceMapping.js | 引用标记与源定位 | 文档变更后引用、来源、跳转稳定 |
| WordEditingShortcuts.js | 类Word编辑快捷操作 | 中文输入法、撤销和受控编辑器一起验收 |
| InstrumentAppendixPreview.jsx | 量表/附录预览 | 核版本、语言、适用性及图文完整性 |
| MedicalWritingPreviewPanel.jsx | 文档预览与Word页码/验证提示 | 修复过期状态仍绿色“最终依据”误导 |
| durableJobState.mjs及共享poller | 任务locator/轮询/恢复 | 失联保留身份并对账，当前实例/ref防过期响应 |
| protocol-workbench/protocolWorkspaceApi.mjs | 新业务API客户端 | 需与新页面、持久状态及真实交互接通；孤立客户端不算产品完成 |

以上文件均位于frontend/src/features/medical-writing（已核对文件库存）；具体链接和逐文件大小/哈希见附录源码索引。

WritingPage以key={activeProjectId}重建实例。之前“旧项目A采纳直接污染B”的简化回调探针没有包含父级key，已撤回该生产缺陷判断；不要据错误结论重新施工。未接线的useDurableMwJob一类hook也不能作为当前真实用户故障证据。

## 6. 工程review发现的问题、修复进度与建议

原完整review：[reviews/mw_protocol_v3_engineering_review_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_engineering_review_20260905.md>)。它包含已被后续修复的基线和仍未完成的问题；不要只读结尾“从1R.2开始”便当现在状态。

### 6.1 已处理的核心问题

| 原问题 | 后续解决与边界 |
|---|---|
| 新包大部分是离线合同，产品没有真实SQLite | 1R.1 adapter、迁移/约束/原子性修复，1R.3实际API与重启恢复验证 |
| v3路由未挂actual main | 1R.2 composition完成默认off挂载及产品库接线；未做生产激活 |
| 阶段断言与新计划冲突 | 用户允许升版；避免用冻结测试阻止合法挂载/迁移 |
| 结果重复存储、过多状态导致维护困难 | 1R.4合并重复实现，保留receipt/消费、恢复/过期/去重必要差别 |
| unknown提交与损坏事件错误分类不清 | 1R.3/1R.4区分失联未知、真实损坏和需重新确认的业务状态 |
| orchestration只停留在PoC | 2R.1 typed facade接产品SQLite与持久reservation，三case已验收 |
| “76个旧叶已实现”缺乏事实 | 3R.1重新抽取并区分130节点、109叶、35显式routes；不外推已实现写作 |
| 只数标题/字数当正文合格 | 3R.2/3R.3core增加实质义务与来源组结构；逐章内容及语义仍待完成 |

### 6.2 仍需进入相应阶段解决

| 优先级/问题 | 已观察到的证据或限制 | 建议处理 |
|---|---|---|
| P1 首批章节合同不够真实 | 主审6类内容反例；52fixtures修复未验收 | 先完成3R.3首批，不跳去造新平台 |
| P1 新前端尚未形成 | 新目录只有客户端，旧WritingPage仍复杂 | 6R抽离新页面，把业务主流程做完整 |
| P1 StrictMode导入挂载 | cleanup把mountedRef=false却未在setup复位；隔离探针普通通过、StrictMode失败 | 修实际组件生命周期，验证卸载/重新挂载和任务结果显示 |
| P1 过期Word预览误绿 | 合法stale载荷+历史Word页数在真实React SSR显示verified/最终依据 | 状态优先于历史页数来源；成功必须绑定当前快照 |
| P1 同实例异步章节切换 | 内联回调captured props不能证明当前页面仍相同 | 使用当前generation/ref，验证poll期间切章、取消及finally |
| P1 失联后删job locator | poll耗尽或结果拉取失败catch可清locator | 保留任务定位，先查询原结果；不要把网络异常等同可重生成 |
| P1 旧整稿hash不一致 | 生成按多段计算、采用只验首段，可误报冲突 | 同一语义块集合计算并检验precondition |
| P1 逐章部分采纳回执 | 第二章冲突前第一章可能已保存，UI只报采纳失败 | 整稿单SemanticDocumentRevision事务；逐章采用则明确已保存哪些 |
| P1 旧全稿崩溃窗口 | 假模型返回后chunk落盘前崩溃，同job恢复产生2次调用 | 新链持久receipt/reservation对账；不外推现有v3也同样失败 |
| P1 QC全局禁词误报 | 合法“未提供书面知情同意者…”被当占位符 | 根据章节实质义务/上下文判定，保留真正占位负例 |
| P1 任意理由字数/小字号 | 旧UI有10字门及10/11px声明 | 6R取消机械门，按实际视觉及点击预算验收 |
| P1 Word回执证据弱 | 旧客户端可自报Word/visual状态；PDFhash不证明来自指定Word流程 | 产品继承Phase0完整input/saved/PDF与producer合同，受控原生执行 |
| P1 全仓仍有残留失败 | 7420/167/18/1和3项NOT_EXECUTED有scope处置 | 按影响做必要回归，不能宣布全仓通过或修监查无关源码 |
| P2 看板/文档时代混杂 | tracking历史表、1R.2metadata、旧review尾部不同步 | 一个Trellis当前状态，其他保留历史并引用；不重写历史证据 |
| P2 工作树成果缺commit边界 | 9月工作大量未提交 | 在恢复后的已验证工作边界逐项整理提交，避免全目录打包式commit |

“P1”指当前产品交付重要缺口，不是在声称已经造成临床损害。用户排除的纯安全专项不在此重新派工；旧review中相关建议已由用户后续决定覆盖。

### 6.3 功能与技术路线建议

已纳入路线的方向：React/Tiptap受控语义编辑、Python领域服务、SQLite、typed facade、专门职责Agent、只读预览与原生Word回流。既有实现和标准库优先，不因为“多Agent”增加多数据库、分布式队列或每章自主智能体。

建议落实到现有4R–7R任务的功能细节：

1. 研究事实导入对比：资料冲突时AI并排列出差异、推荐及依据，用户只决策关键冲突。
2. 设计变更影响预览：更改主要终点或人群后，先展示受影响的样本量、SoA、统计和正文，再执行修改。
3. 证据就地查看：点击关键结论即可看到具体页/段，不跳转到一堆文件列表。
4. 样本量复算卡：给参数值、来源、公式/计算结果、适用假设和备选；“模型很有信心”不是计算依据。
5. 稿件锁定、撤销和可恢复导出：用户不用担心刷新/关闭后丢稿，不用自己管理重试按钮。
6. 材料版本提醒：发现IB或指南版本变化时提示实际影响；这是产品能力建议，不在当前交接创建定时自动化。
7. 低负担长任务页面：显示已完成资料、当前阶段和等待原因；留稿件阅读空间，避免满屏工程控制项。

建议退出新链主流程：任意字数理由、重复资料准入确认、逐章手动“开始生成”、逐文件手动下载/OCR确认、技术模型参数大面板、从零逐格搭SoA。保留必要的细节修改入口和历史数据，不把精简理解为删除事实来源或跳过重大设计确认。

可选LangGraph只在typed facade无法满足明确需求时做有界对照。MAF在原评估中不具备当前采用条件；不要未经新事实与路线决策擅自切换。浏览器不要实现Word级分页排版引擎，最终版式由原生Word及回流闭环承担。


## 7. 最关键的当前工作：Task 3R.3

### 7.1 数字与覆盖义务不能混为一谈

TP-MA-07 v2.0原始抽取：135个标题节点、106个标题叶、17张顶层表。后续还核对了139个outline节点、109个outline叶、18张递归含嵌套表及8个节。以标题叶和outline叶的并集得到110个载体，加无标题封面为111个合同载体。章标题、outline、正文义务是三个不同概念。

历史“试验参与者218处”是既定正文计数；表格另22处，总XML计数240。不要为了让数字一致删除内容或改抽取脚本。“受试者0”是清洁模板特征，不是法规禁止该同义词。

正确覆盖是全部适用语义义务，而不只“106个JSON”。当前已经存在的12个载体尚未内容验收。

| 批次 | 范围 | 载体数 | 当前状态 |
|---|---|---:|---|
| batch1 | 封面、前置件、摘要、图、SoA | 12 | 12合同+12技能已写，修复未验收 |
| batch2 | 第2–3章：背景、目的、estimand等 | 16 | 已启动过并读材料，没有交付 |
| batch3 | 第4–5章：设计、人群 | 10 | 来源spec完成，待实现 |
| batch4 | 第6–8章：干预及相关程序 | 16 | 来源spec完成，待实现 |
| batch5 | 第9–10章：评估与安全性 | 19 | 来源spec完成，待实现 |
| batch6 | 第11章：统计 | 13 | 来源spec完成，待实现 |
| batch7 | 第12–13章：质量与数据等 | 13 | 来源spec完成，待实现 |
| batch8 | 第14–16章及outline附录 | 12 | 来源spec完成，待实现 |
| 总计 | 110并集+封面 | 111 | 不能称完整 |

总对账：[reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch_coverage_reconciliation_20260906.md>)。各批详细输入为reviews/mw_protocol_v3_3r3_batch1_content_spec_20260906.md至batch8；附录分别链接。

### 7.2 已验收checker做什么、没有做什么

[services/api/app/protocol_workflow/registries/chapters.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/chapters.py>) 与 [scripts/qc/protocol_v3/lint_chapter_registry.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/scripts/qc/protocol_v3/lint_chapter_registry.py>) 检查声明的facts、claims、对象、typed cells、source floor与覆盖结构。ChapterContractV2 schema位于共享protocol_v3.py。

重要语义：一个EvidenceSourceRequirement组中有多个可接受claim时，是“任意一个符合即可”，不是“组内全部必需”。如果封面身份与保密、摘要目的与estimand、图的内容与转移分别独立必需，应建独立组，不能塞一个组后自称都校验了。

每个载体至少有4类被实际执行的正文fixture：合格内容、缺实质claim或control、错误来源、空骨架。111载体基础至少444条只是最低结构，不是完整医学覆盖。不能通过增加无意义fixture或让负例先因无关身份错误失败凑数。

当前core不证明：
- 条件医学适用性运行时已经实现；
- 自然语言主张在医学上成立；
- 真实来源已经下载/准入或主张得到其支持；
- 正文写作及跨章一致性已完成；
- SVG/表格/Word真实视觉验收通过。

partial clean仍必须incomplete；full必须在全部预期载体、独立义务与fixture完整时才可能通过。accepted schema中的CtQ、dependency、repair ownership字段也不是相应业务executor已经实现。

### 7.3 首批六个已复现问题与修复合同

主审在worker最初交付后逐个读过24个JSON，原8测试可通过，但新增6个内容反例失败。当前修复结果已经落部分文件，还没有独立验收。

| 问题 | 准确修复要求 |
|---|---|
| 无外部服务方仍要求3张联系人表/服务方cell | 申办方/研究者基本信息保留；CRO等按实际存在条件要求，不能伪造N/A联系人 |
| 非随机单臂仍强制分配比 | 实际随机才要求ratio；合适简单设计可按模板说明记录图适用性，不无条件删除图 |
| 封面/摘要研究身份各自造字段 | 复用framing.protocol_id、document_title、version、study_phase及已有PICOS事实；同义字段不重复存储 |
| SVG辅助来源身份/hash缺失 | 绑定真实支持SVG，标example-only；例子1:1、IWRS、12周、安慰剂不能变项目事实 |
| “药品注册分类”被当临床试验登记 | 区分申报分类与登记记录；摘要17行完整投影，不发明登记信息 |
| 缩略语只有表头即通过 | 实际使用缩写必须有条目、全称、中文含义；空条目有有效负例 |

其他必须一起复核：

- 摘要表242的17行：编号、标题、版本/日期、分期、药品注册分类、申办方、PI、中心、目的/estimand/终点、设计、人群、试验药物、干预、样本量、统计、总试验时长、参与者访视时长。
- 版本和日期不可混成一个无结构字符串而丢掉版本。
- 独立证据义务分组；适用与不适用场景均有准确正负例。
- 原48个fixture ID保留且仍有效；当前52条仅库存计数，尚未证明48条语义完整保留。
- 字段改名后，负例删除旧字段可能变成“什么也没删”的空操作；逐条检查负例实际命中目标失败原因。
- 去除新写SoA CtQ里的“受试者”残留，改用“试验参与者”；不篡改历史引文。
- batch1只统计本批coverage_roles，不因未来batch2新增导致“全目录必须恰好12个”失败。

准确可写范围及原反例：[context/mw_protocol_v3_3r3_batch1_repair_20260908.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/context/mw_protocol_v3_3r3_batch1_repair_20260908.md>)。原12个contract、12个skill、batch1 fixture、test_chapter_batch1.py及新diagnostics可写；core/schema/assembler/Main反例/计划/他批文件对该worker只读。

### 7.4 主审已修复的组装器

[scripts/qc/protocol_v3/assemble_chapter_registry.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/scripts/qc/protocol_v3/assemble_chapter_registry.py>) 现在按coverage_roles读取切片，可重复传batch参数合并全局词汇。缺被选章节文件或非法schema应报AssemblyInputError/CLI exit2，不能吞异常后输出干净结果。

对应诊断在 [runs/mw_protocol_v3_3r3_batch1_20260906](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_3r3_batch1_20260906>)：
test_codex_batch_content.py、test_codex_batch_assembly.py、test_codex_multi_batch.py。
暂停前修改了一个缺章节反例：在tmp副本中显式制造缺失，避免下一批文件出现后原测试前提失效。**这个最后改动尚未重跑。** 新Agent首先完成精确测试，不把旧11PASS/4PASS套在最后新版本上。

### 7.5 第二批尤其容易写错的科学内容

第二批准确16个ID及范围见 [context/mw_protocol_v3_3r3_batch2_20260908_context.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/context/mw_protocol_v3_3r3_batch2_20260908_context.md>)。它只拥有16个新contract、16个新skill、batch2 fixture/test及新diagnostics，不能读写正在修复的batch1可变内容。

- 模板未单列标题的毒理、PK、一般药理信息不能因“不是叶标题”丢失；保留来源和适用性。
- 模板body299在竞品标题区域内含本品临床证据义务。不能让竞品来源替代本品真实临床结果。
- estimand第五属性“群体层面汇总量”实际在body323，位于v2_n_3_1_2_4内部。不能凭理想化五属性结构新造第5标题，也不能把它当ICE。
- picos.population_summary表示人群描述，不表示estimand的summary measure，不可复用同名词根造成语义错配。
- 独立证据义务各自分组，空ICE条目、缺汇总量、本品证据被竞品替代均要有效负例。
- 至少64条四类基础fixture；合成示例清楚标明，不能假装真实项目医学验收。

### 7.6 跨批继承义务不能被叶抽取丢掉

- 模板父节点v2_n_5的避孕：按适用性展开至纳入/排除v2_n_5_1/_2、持续限制v2_n_5_3、妊娠事件v2_n_10_6。
- 统计父节点v2_n_11_4的PK/PD/暴露反应：探索性可由v2_n_11_4_6承载；若确证性则绑定相应主要/次要分析，不能统一改成探索性。
- 总体研究人群body372–379等父段落、药物背景、SAP框架需载体或聚合规则，不能叶遍历时抛掉。
- AE、SAE、TEAE、严重程度、严重性、因果关系、预期性相互不同；pregnancy不是天然SAE或自动退出全部随访。
- 停药、退出研究、撤回同意、试验暂停/终止要分清，与随访和estimand联动。
- 模板CTCAE v5示例不等于任何未来研究都适用或永远最新；研究实际版本须绑定。
- 五级因果关系评估不能未经约定直接简化成二元ADR判定。
- investigator SAE与sponsor SUSAR报告时限的对象/起点不同，不能只抓一个数字统一写正文。

来源准备见 [reviews/mw_protocol_v3_3r3_source_preparation_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_source_preparation_20260906.md>)、[reviews/mw_protocol_v3_3r3_additional_m11_anchors_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_additional_m11_anchors_20260906.md>)、各批spec。这些是实现输入与来源定位，不是临床专业签字。

## 8. 剩余完整路线图

以Plan v2每项Files/Micro-steps/Gate为权威；表中对照被冻结继承任务，避免编号错位。阶段检查是完成条件，不是用户再次授权按钮。被用户排除的安全阶段不执行、不冒标PASS。

| 当前任务 | 主要交付与完成重点 | 依赖、需保留的旧计划内容 |
|---|---|---|
| 3R.3 | 完成8批111载体、skill、有效四类fixture、继承义务crosswalk、主审和fresh复核 | 当前首批修复/第二批恢复；不能只补JSON到111 |
| 3R.4 | 研究事实→章节→表格/图→QC的dependency/impact图 | 继承旧3.4；schema edge不等于影响执行已完成 |
| 3R.5 | R03 criteria registry，把复合行拆原子检查，分类deterministic/agent4/human | 68条内容行=54有代码+14无代码；每项保留原行/单元格定位 |
| 3R.6 | Ⅰ期模板权威问题卡，列候选差异与推荐 | **真正用户决策点**；推荐T02修订版但不能自行视作已批准 |
| 3R.7 | 术语库v1、缩略语schema、L1术语检查 | 试验参与者优先，原引文/题名保留；不全局强制替换 |
| 4R.0 | 18份公司方案只读corpus，9DOCX+9PDF，元数据/章节映射/适用性 | 是待建目标库存，不是已完成检索库 |
| 4R.1 | ResearchSeed | 继承旧4.1；已知项目事实、范围、检索问题、来源缺口 |
| 4R.2 | acquisition计划与来源分母 | 继承旧4.2；三类分母分别记录，不能用找到文件数冒充成功率 |
| 4R.3 | discovery与零结果解释 | 继承旧4.3；竞品方案没有找到要查搜索/入口/地域/资料可得性原因 |
| 4R.4 | source integrity与下载完整性 | 继承旧4.4；成功HTTP/文件名不等于真实Protocol |
| 4R.5 | 解析/OCR/翻译及E1 | 继承旧4.5；复用已有效结果，准确来源与lease；72h无进展问题卡不删失败分母 |
| 4R.6 | 医学准入、章节映射、E3 | 继承旧4.6；公司先例不能覆盖当前IB/已确认项目事实 |
| 4R.7 | 当前指南与E2 | 继承旧4.7；适用版本与有效期，不把旧指南标题当最新证据 |
| 5R.1 | 临床建议worker | 继承旧5.1；有推荐/依据/备选/适用假设 |
| 5R.2 | 统计建议worker | 继承旧5.2；可复算样本量、estimand/方法、关键假设 |
| 5R.3 | consistency reducer | 继承旧5.3；临床和统计不能各自正确、合起来矛盾 |
| 5R.4 | 推荐卡与确认 | 继承旧5.4加风险分层；低风险整包、8高风险逐卡 |
| 5R.5 | StudyDefinition与Protocol Summary | 继承旧5.5；确认后同源投影，D1 |
| 6R.1 | 受控编辑面 | 替代旧6.0；语义编辑+只读预览，非网页Word引擎 |
| 6R.2 | writing planner、chapter-skill executor、validator、全文reducer | 合并继承旧6.1–6.3；真正写完整正文与表图附录 |
| 6R.3 | ChapterLockSnapshot、EditClass | 继承旧6.4；锁定无关内容，fact_or_uncertain回提案 |
| 6R.4 | WritingPage渐进抽离 | 继承旧6.5；新页面挂新链，不继续无限加App状态 |
| 6R.5 | A+C页面与交互预算 | 继承旧6.6并应用20/5；真实浏览器/系统对话框计数 |
| 6R.6 | 选区AI | 继承旧6.7；7动作、3–5候选、局部diff、数字/单位/术语/引用保护、stale拒绝 |
| 7R.1 | coverage digest | 继承旧7.1；当前111载体及全部适用义务，无抽样冒充全覆盖 |
| 7R.2 | fresh-context reviewer | 继承旧7.2与修订；实际当前稿、来源、版本，明确typed finding |
| 7R.3 | repair loop与Q1 | 继承旧7.3；R03自动/Agent④/人签分别闭合，不让writer自己说clean |
| 7R.4 | Word producer产品化与版本指纹preflight | 继承旧7.4；绑定输入DOCX、Word保存后DOCX、PDF和producer |
| 7R.5 | Word回流与语义合并 | 继承旧7.5；无法定位/外部表格改动不能整文静默覆盖，重新QC |
| 7R.6 | 四层终验、eCTD文档检查、人签QC表 | 继承旧7.6及v2扩展；正式Protocol与审计包分开 |
| 8R.1 | shadow | 继承旧8.1；真实数据只读对比，不先切生产 |
| 8R.2 | snapshot/rollback | 继承旧8.2；SQLite一致备份、恢复后业务hash，不裸复制WAL数据库 |
| 8R.3 | API/发布合同 | 继承旧8.3；旧新项目路径明确，监查不受扰动 |
| 8R.4 | 集成测试 | 继承旧8.4；真实API/持久化/恢复/并发及用户可达错误 |
| 8R.5 | E2E runner | 继承旧8.5；真实浏览器、实际素材、正文、Word证据 |
| 8R.6 | 测试矩阵与修复循环 | 继承旧8.6加v2可用性与新模板；大/小适应症、期别/设计/给药差异避免过拟合 |
| 8R.7 | 真项目cutover与最终签收 | 继承旧8.7；**明确用户授权**、最新live漂移、恢复方案、实际交付 |

“A+C”具体是：顶部A显示结论、关键卡、实际异常、真实进度与采用动作；下方C为左目录、中稿件画布、右AI/证据/QC。每章有自己的AI/问题区，建议和semantic block双向定位，overlay不进Word，普通审计身份说明不占常驻竖条。中间画布受v2约束为受控编辑/只读预览，不实现浏览器Word分页引擎。桌面为主要验收，mobile仅退化烟测。

选区AI的7动作是润色、改写、扩写、缩写、监管语气、补证据、一致性。anchor绑定block_id、semantic_node_id、range、revision、selected_hash；范围合同要测中文、emoji、组合字符、IME和表格单元格。事实或不确定修改转proposal，已锁章节编辑产生明确解锁事件。

### 8.1 四层最终验收到底检查什么

1. Layer1：准确事实与文档修订一致。
2. Layer2：所有适用内容实质完整且有来源约束，正文内部生成痕迹为0。
3. Layer3：Agent④审阅clean、覆盖完整、按当前适用的质量规则闭合未决项。旧“P0–P4 open=0”中的被用户排除纯安全任务不能复活。
4. Layer4：对应Microsoft Word真实回执与round-trip闭环。

同时冻结事实、合同、决定、QC、回执、模型/工具版本、hash至SubmissionEvidencePackage。正式正文与内部审计包分离。人签QC表回执、PDF可搜索/链接/字体/书签等eCTD文档条件按适用规范验证，不能把“导出了DOCX”当全部完成。

### 8.2 Ⅰ期模板真正待用户决策

3R.6候选为旧TP-MA-05/06、T02-00修订版、用户提供新的Ⅰ期清洁版。计划预选推荐T02修订版，仍需要用户选择。到达时准备清楚的差异、风险、迁移影响和推荐理由，以平台原生提问方式询问；无需现在在交接回合提前打断用户。

原生Word验收、生产激活、真实项目cutover等关键节点，如果需要用户实际提供审批或操作，也以具体可审阅结果提问，不能拿空计划反复要授权。

### 8.3 最终E2E保留的要求，不能只跑一个演示项目

冻结8.5/8.6与v2扩展仍要求：工程师角色与“懒惰、专业、视觉敏感的原生中文医学写作经理”角色分开prompt、分开session；每个tester/角色至少3个不同非肿瘤适应症，覆盖Ⅰ/Ⅱ/Ⅲ及不同设计，每轮采用不同prompt/项目/适应症/设计。结合用户最早要求，注意大适应症、小/罕见适应症及非口服/注射情境等差异，避免单一模板过拟合；不扩成细胞/基因/器械任务。

用户角色通过实际浏览器点击建项→初稿→导出，记录点击与必填文本计数，逐章读最终DOCX，核内容科学性、监管中文、完整性、目录/参考文献跳转和Word可编辑性。模型/角色矩阵用当前批准route，不从旧prompt恢复失效时段或固定模型名称。

每个tester/role连续两轮符合当前有效质量要求才计入clean streak；准备阶段、API-only、空正文、未Word-verified不能计入。适用且未闭合的功能/科学问题仍要修；被用户明确排除的纯安全项不再放入分母。Ⅰ期模板未确认/未验收时保留其缺口，不通过删除Ⅰ期场景宣称全范围通过。

每次E2E用新run_id和独立根目录，不清空旧目录复用。此处是未来8R合同，不是在本交接启动E2E或重新派发历史5×3任务。


## 9. 医学与监管来源：已纠正的误读

以下是此前review与9月8日来源核对形成的工程输入。本轮只核对相关文件，没有重新作2026-09-11全面法规检索；涉及未来研究实际适用版本，实施时按原一手来源检查。

| 主题 | 已纠正结论 | 工程处理 |
|---|---|---|
| GCP2026 | 既有核对记录确认2026-09-01实施 | 新正文对当前版本；实际适用性仍按项目/地区 |
| eCTD是否所有IND强制 | 2026年第8号公告为特定范围“可以”以eCTD提交，不能泛化成所有IND强制 | 保留用户自定readiness目标，不编造法律必需性 |
| PDF/A | eCTD v1.1 §7.2允许PDF1.x/PDF/A，并非只允许PDF/A | 验实际格式、可检索、字体/链接等，不为错误“唯一格式”增加阻断 |
| E6(R3)方案结构 | 使用Appendix B，不拿E6(R2)的6.x当新条号 | crosswalk真实版本/条款 |
| 财务披露 | 不是笼统Annex2必需一段；地区如21CFR54等另有适用条件 | 默认N/A只能是产品约定，不能冒充法律豁免 |
| M11 | Step4用于内容crosswalk，不取代已批准公司模板 | 保留实际TP-MA-07定位和载体结构 |
| 试验参与者/受试者 | 新正文首选“试验参与者”；GCP54将其定义为同义词 | 原题名/法规引文/历史记录不全局替换 |
| R03 QC表 | 68内容行=54有代码+14无代码，不能只收有编号行 | 复合行拆原子检查，保留table/row/cell来源 |
| 6类QC | 版本身份、缩略语、引用、链接、中文格式、登记一致性 | 可确定部分自动化，医学含义交Agent④/人审 |
| 模板示例 | SVG、剂量、周期、CTCAE等示例不自动成为项目事实 | example-only、适用性、真实项目来源/版本 |
| AE因果与报告 | 五级关系保留，AE/ADR/SAE/SUSAR与不同报告时限分清 | 从现行IB/PV/SOP来源落正文，不凭模板例子自动填 |

关键核查文档：[reviews/mw_protocol_v3_gcp2026_source_check_20260908.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_gcp2026_source_check_20260908.md>)、[reviews/mw_protocol_v3_registration_field_check_20260908.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_registration_field_check_20260908.md>)、[reviews/mw_protocol_v3_3r3_diagram_reference_check_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_diagram_reference_check_20260906.md>)、[plans/mw_protocol_v3_review_amendment_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/mw_protocol_v3_review_amendment_20260905.md>)。

这些问题主要关系科学性和申报文件质量，不属于用户已排除的纯安全工程。可以减少过程控制，不可以编造药物结果、风险时限、统计参数或人员/机构事实。

## 10. 中断执行血统与9月11日恢复条件

### 10.1 暂停前两个执行者

| 项目 | 首批原执行/同会话修复 | 第二批执行 |
|---|---|---|
| logical work key | mw_protocol_v3_3r3_batch1_repair_20260908 | mw_protocol_v3_3r3_batch2_20260908 |
| 原生session | sess_b91d51c2-ce9c-48fe-9add-59201fcf8927 | sess_4df83643-16c7-405c-af7a-1ab779584ad3 |
| 中断turn | turn_6c01694b-a569-4b4c-a2ea-145b0b387d93 | turn_a4bc05a9-f84c-4680-9540-1491e4e29fc7 |
| 历史runner handle / PID | 28260 / 51942 | 16850 / 66286 |
| 路线 | ZCode / GLM-5.3-Flash / max | 同左 |
| 当时终态 | 用户SIGINT，exit130/KeyboardInterrupt | 同左 |
| 9月8日model-io条数 | 22 | 30 |
| 中断后的最终runner报告/receipt | 未落盘 | 未落盘 |
| 9月11日现有文件 | 24JSON、52fixtures、测试/诊断保留 | 无batch2合同/fixture/test交付 |

首批最初一次完整执行的报告 [runs/zcode_mw_protocol_v3_3r3_batch1_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/zcode_mw_protocol_v3_3r3_batch1_20260906.md>) 与 [runs/zcode_mw_protocol_v3_3r3_batch1_20260906_stdout.txt](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/zcode_mw_protocol_v3_3r3_batch1_20260906_stdout.txt>) 已存在；完成约2031.78秒。它不覆盖9月8日未完成修复，也不是章节验收。

3R.3核心fresh reviewer的session为01a07306-8334-7000-9a3d-f9d3d3975e37，历史路线MuseSpark1.3:xhigh；ACCEPT只绑定核心版本。没有首批修复的fresh最终验收。新review应按当前可用route，不盲抄旧身份或旧结论。

9月8日暂停核对原runner及后代均已不存在；旧handle是历史终态，不再wait它们，不向同号新进程发信号。9月11日未新开进程，也未声称检查了全机所有活动任务。

### 10.2 原日志缺口：接手者必须看到

原两个日志位置和旧SHA：

- /Users/smkzw/.zcode/cli/rollout/model-io-sess_b91d51c2-ce9c-48fe-9add-59201fcf8927.jsonl  
  旧SHA-256：17d759454594d97fe4435469d2a7bdbdad7f3edf8b1b026d4d3afe4558add5a2；旧大小8473797字节。
- /Users/smkzw/.zcode/cli/rollout/model-io-sess_4df83643-16c7-405c-af7a-1ab779584ad3.jsonl  
  旧SHA-256：140e7f3e8ddc312d7472a45e7f9a0ec1cfbad1f8a8e35b1955407adb4401d0dc；旧大小8706377字节。

本轮这两个原路径均不存在；在~/.zcode及Documents/AI Cache范围按原session/日志文件名查找也未找到。不是“日志hash变了”，而是“文件缺失”。不知道原因，没有作全盘/全部备份搜索，也没有恢复或伪造它们。

本轮仅以SQLite mode=ro、query_only读取原生数据库 /Users/smkzw/.zcode/cli/db/db.sqlite 的有限元数据：

- 首批session记录存在、未归档、directory匹配隔离区，session_entry数量8；有最初已完成turn_usage记录，41个model requests、44个tool calls；6个原生工具制品文件仍存在。
- 第二批session记录存在、未归档、directory匹配，session_entry数量1；未查到turn_usage行或工具制品。
- 不读取/导出私有消息正文；上述条目计数不证明上下文完整，也不证明原生续接实际可用。
- 旧stdout/执行报告/暂停清单/项目prompt和当前产物仍可作为恢复依据。日志缺失影响证据完整性与原生续接把握，不等于工程源码丢失。

详见 [session_recovery_availability.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/session_recovery_availability.json>)。接手后应优先使用原生会话读取/恢复能力确认可用性；不能手工写session数据库或造原日志。若原会话无法续接，记录明确的恢复合同：原logical key、session/turn、已有产物hash、缺失记录、剩余范围、新运行身份。从现有成果继续，不伪称“同会话无损恢复”，也不当未启动重新从零写一遍。

### 10.3 产品连通性探针不可重复

已完成的1R.6最小真实产品探针：

- logical key：protocol-v3:1r6:glm-5.3-flash:max:initial-connectivity:20260905。
- 状态：SUCCEEDED。
- 记录：[runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json>)。
- 原响应ID：20260905204513dd949ba3c4514e37。
- requested/observed模型身份匹配；服务端未明确回报effective effort时，不能把max请求值说成服务端已证明的推理强度。
- 不因接手换Agent、日志不全或文档重新整理就再发“首次连通性”产品调用。未来真实产品任务按阶段合同另行执行，不借probe名义重复。

### 10.4 现有prompt/context/report定位

| 内容 | 路径 |
|---|---|
| 首批原执行上下文 | [context/mw_protocol_v3_3r3_batch1_20260906_context.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/context/mw_protocol_v3_3r3_batch1_20260906_context.md>) |
| 首批修复合同 | [context/mw_protocol_v3_3r3_batch1_repair_20260908.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/context/mw_protocol_v3_3r3_batch1_repair_20260908.md>) |
| 首批修复prompt | [prompts/zcode_mw_protocol_v3_3r3_batch1_repair_20260908.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/prompts/zcode_mw_protocol_v3_3r3_batch1_repair_20260908.md>) |
| 第二批执行合同 | [context/mw_protocol_v3_3r3_batch2_20260908_context.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/context/mw_protocol_v3_3r3_batch2_20260908_context.md>) |
| 第二批prompt | [prompts/zcode_mw_protocol_v3_3r3_batch2_20260908.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/prompts/zcode_mw_protocol_v3_3r3_batch2_20260908.md>) |
| 主审组装/内容反例与结果 | [runs/mw_protocol_v3_3r3_batch1_20260906](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_3r3_batch1_20260906>) |
| 首批修复新增诊断 | [runs/mw_protocol_v3_3r3_batch1_repair_20260908](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_3r3_batch1_repair_20260908>) |
| 无损暂停记录 | [runs/MW_PROTOCOL_V3_3R3_NO_LOSS_PAUSE_20260908_0934.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/MW_PROTOCOL_V3_3R3_NO_LOSS_PAUSE_20260908_0934.md>) |
| 原文件快照与清单 | [runs/mw_protocol_v3_no_loss_pause_20260908/snapshot_manifest.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_no_loss_pause_20260908/snapshot_manifest.json>) |
| 暂停后收尾版本 | [runs/mw_protocol_v3_no_loss_pause_20260908/pause_closure_manifest.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_no_loss_pause_20260908/pause_closure_manifest.json>) |
| 当时停止/保存验证 | [runs/mw_protocol_v3_no_loss_pause_20260908/pause_verification.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_no_loss_pause_20260908/pause_verification.json>) |

不要修改已发送prompt来“修复历史审计”。旧execution审计曾因原/续作output绑定、包装器解析不一致出现FAIL；实际runtime receipt与独立检查分别记录。保留历史包装器失败，不为使文件名对齐而无故重复模型执行。

## 11. 为什么任务推进慢、反复停顿

### 11.1 已证实的直接停点

现在停止的直接原因是2026-09-08用户“无损暂停”，不是新的技术失败，也不是等待用户重新批准1R.4/PyMuPDF/工程subAgent。9月11日当前Goal正式状态为paused；旧暂停文档说“active flag不得自动续作”是当时工具状态说明，不能覆盖今天API返回。

两个worker按用户要求被中断，不是模型terminal failure，不能据exit130自动换模型或重派。当前需要的是章节内容修复/验收，而不是再建一个安全门或编排平台。

### 11.2 工程确有难点，但不足以解释所有停顿

1. 基础设施初版通过普通测试后，独立反例发现SQLite CTAS约束丢失、迁移/claim、投影原子性、事件重建、结果恢复等真实问题。修复这些是必要的，不应只看测试数字否认价值。
2. 模板不是一棵标题树。无标题正文、outline-only附录、父节点条件义务、摘要/图表共享事实、证据组“任一/全部”差别都需要逐条核对；批次内容天然比增加schema字段慢。
3. 部分外部执行约20–30分钟甚至更长。慢本身不是失败；应保持同一任务等待并做无依赖工作，不能短等待后从零派发。
4. 历史计划带有错误法规推论、过时路径和阶段断言。早期没有尽快分清“需求”“实现阶段限制”“历史证据”，增加了重复讨论。
5. UI与最终用户价值还没有进入主要实施阶段；大量后端测试绿使工程看似前进，但用户看不到完整正文和可用页面。这是阶段规划和反馈方式需要改善的事实。

### 11.3 本任务处理方式的问题，需要明确承担

用户多次指出“运行几分钟就停一下”。从对话中连续出现阶段式收尾、用户重复要求继续可见，工作曾被过细分成短回合；在仍有已授权下一步时用最终回复结束，让用户承担了重新启动成本。这不应归因于用户没有授权，也没有证据证明每次都由平台硬限制导致。

过程文档、会商包装、重复重锚定与重复扩大回归也形成成本。全局AGENTS必须按约定定期读取，但不是每次读取都要重做全部历史review。旧文档仍写“未挂载/无存储”、tracking旧表与Trellis不同步，会让后续Agent误判从头开始。9月成果未形成清晰commit边界，也增加交接难度。

用户后续决定已经解决了多项过程阻断：取消纯安全工程、允许旧阶段断言升版、允许工程subAgent、批准1R.4保留兼容语义、个人使用PyMuPDF、用Trellis统一状态。接手者应落实，不再让用户重复回答。

### 11.4 恢复后的执行改进

- 每次只维护一个当前Trellis checkpoint，Plan列需求/依赖、tracking列索引；历史证据保持原样。
- 开始阶段、派发前、用户变更后、压缩/恢复后、重复失败/路由异常时读最新global AGENTS；其余按hash和变更范围读取相关文件，不重新遍历整个项目。
- 一位owner整合共享文件，独立批次可以并行；内容batch与core/assembler分开拥有。不要设没有价值的固定worker数量或会议层级。
- 先做能证明真实问题的失败测试，修复后运行最小决定性测试及受影响相邻范围；没有新改动/新疑问不重复全仓扫描。
- 循环内部持续工作并发简短进度；测试完成、worker返回、fresh审阅通过后直接进入已授权下一项。
- runner采用长hard wait或完成事件，必要lease heartbeat；平台短返回则继续等待同一handle，不固定频率反复询问，不把等待当新任务。
- 先对账logical key再retry/resume/fallback。对unknown结果先恢复可见性，不能以缺最终report为“没执行过”的证据。
- 已验证的有界工作按当前仓库规则整理可审阅提交，先明确文件归属；不要用git add全部、清理历史或改expected制造整洁。
- 真正需要用户决策时，把具体候选/推荐/影响准备好；如用户暂停，立即停止新增派发，保存并等待。

这是减少实施摩擦的执行方式，不新建“流程优化项目”拖延3R.3，也不承诺无需实际素材即可一次输出“完美方案”。

## 12. 新 Agent 获得恢复授权后的第一段操作

### 12.1 先核查，不从头施工

1. 按第3节读最新权威及Trellis，确认用户是否已明确让接手Agent继续；本次交出任务仍暂停。
2. 比较HEAD、Git dirty状态、暂停snapshot加closure与本文current_state。新变化须先辨别归属，绝不把快照覆盖现文件。
3. 确认任务位置3R.3；3R.1/3R.2/core接受仅适用于绑定hash，无漂移不重做。
4. 查看原logical keys、session元数据与可用原生历史。原model-io缺失事实保留；原handle不要再wait。
5. 首批：让原会话可用时同模型续接，先检查现24JSON/52fixtures，再只完成合同指定剩余修复和报告。无法原生续接则显式记录恢复身份/缺口，从现文件继续。
6. 第二批：同样先对账，再在原16载体范围续作。不因最终report不存在新派一个“从零写batch2”的重叠任务。
7. 主owner保持core/schema/assembler独占，按第7节验首批6内容反例、组装、多批；复核所有原48ID及有效失败原因。
8. 首批修复稳定后给fresh reviewer当前源模板、合同、事实定义、反例和acceptance criteria，不给执行者私人推理来诱导接受。
9. 对实际接受范围同步Trellis，然后继续batch2到8、3R.4、3R.5。常规阶段不向用户要“继续”。
10. 到3R.6准备Ⅰ期模板问题卡并等待真实选择；继续保留已完成成果。

工程恢复缺日志可以用明确记录和来源/制品核对推进，不必自动变成用户决策门；只有原生恢复能力/合法范围确实不明确或出现必须取舍的事实缺口才提问。

### 12.2 环境与测试启动注意

已有隔离Python：[runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python>)。历史环境记录Python3.12.13、SQLite3.53.4、Node22.22.3；PyMuPDF1.28.2、xlrd2.0.2是入口依赖闭合中增加的隔离依赖。重新开工先核版本与现锁，不默认全局环境相同。

旧main导入有全局repository/artifact mkdir及startup recovery，不能随便import生产main后声称只读。测试必须使用隔离runtime、临时产品库和净化child env，避免继承AI/role/eligibility路径逃逸。不要执行start_stable_backend.zsh，它指向LIVE。不要碰8910，也不要为了避端口冲突停任何监查服务。

只在恢复授权后运行的首批聚焦例子（XML输出使用新的文件名，不覆盖历史）：

~~~sh
cd '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313'
env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin \
  HOME=/Users/smkzw \
  TMPDIR=/var/folders/yb/31r9763x6_54mdxswxk36c4w0000gn/T/ \
  LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
  PYTHONPATH=tests/protocol_v3:services/api:packages:. \
  runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest \
  tests/protocol_v3/test_chapter_batch1.py \
  runs/mw_protocol_v3_3r3_batch1_20260906/test_codex_batch_content.py \
  runs/mw_protocol_v3_3r3_batch1_20260906/test_codex_batch_assembly.py \
  runs/mw_protocol_v3_3r3_batch1_20260906/test_codex_multi_batch.py \
  -q -p no:cacheprovider --tb=short \
  --junitxml=runs/mw_protocol_v3_3r3_batch1_repair_20260908/handoff_resume_focused_NEW.xml
~~~

这是待执行模板，本文没有运行此命令。先确认TMPDIR当前存在；历史hygiene假失败与env-i缺该路径有关。NEW须替换为本次唯一标识。之后按实际失败修复，不盲目扩大为全legacy回归、不复制缺失监查fixture、不引入xfail。

### 12.3 工作机制入口

恢复构建时按现有技能与当前工具使用：
- trellis-framework用于任务管理；当前工作规范 [.trellis/spec/protocol-v3.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/spec/protocol-v3.md>)。
- coding任务按全局要求加载ponytail，最小完整实现，不为交接/核对重新造工程。
- 真实前端阶段使用适用的browser/E2E及视觉规范技能；科研内容按具体来源/方案技能，不仅靠代码测试。
- 执行/会商查最新 [tools/hermes_workflow_guard.py](</Users/smkzw/.codex/tools/hermes_workflow_guard.py>)、[tools/route_policy.py](</Users/smkzw/.codex/tools/route_policy.py>)、[tools/conference_session_runner.py](</Users/smkzw/.codex/tools/conference_session_runner.py>) 及其当前批准route manifest。
- 先查实际CLI/adapter支持和route，不照搬8月Kimi/Grok模型表、旧日夜窗口或强制manager数量。
- 当前平台若没有某旧harness，只报告能力差异并用已允许恢复方式；不要伪造调用、回执或模型独立性。

## 13. 保护范围与交出后的状态

| 区域 | 操作边界 |
|---|---|
| 当前隔离实施区W | 恢复授权后可在任务范围改代码；本轮仅新增handoff/2026-09-11 |
| [/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/../workbench](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/../workbench/.>) | live只读，医学监查持续独立开发；不写、不停、不迁移、不清理 |
| live 8910 | 历史在运行，本轮未探测服务健康；不得因新工程停止它 |
| [/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/../plan-upgrade-20260905](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/../plan-upgrade-20260905/.>) | 用户已给定权威升版目录只读；修订通过隔离区附加Plan |
| 外部SOP/公司模板/真实资料 | 来源只读，不“顺手清理”或改模板权威 |
| 原rows/runs/records/logs/evidence/session | 保留原样；缺失的如实记录，不补造历史 |
| 凭证与全局模型配置 | 不复制、不落handoff/prompt/trace，不为接手者导出密钥 |
| 当前Goal | paused，未冒标complete/blocked，也未改目标或自动恢复 |

当前已足够让新Agent从准确的工程边界继续，无需重新做一次全项目从零review。需要的重点是3R.3内容交付与证据闭合，然后按现Plan推进到用户真正需要选择的节点。

## 14. 权威文档与逐文件证据索引

### 14.1 当前权威文件：9月11日实测哈希

原文件只读。本次以下7项均与9月8日暂停权威哈希一致；新Agent仍须在实际开工时读最新全局AGENTS。

| 文件 | SHA-256 |
|---|---|
| [/Users/smkzw/.codex/AGENTS.md](</Users/smkzw/.codex/AGENTS.md>) | e01f795dcdf886743fe6ab7140ff3740654b8eb5eff16281dc6136414bf691b7 |
| [/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/AGENTS.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/AGENTS.md>) | 5603d6516f79946f490eb815a65081f06774cac41c03d360ece7c8728542e6ea |
| [/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md>) | fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914 |
| [/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/plan-upgrade-20260905/mw_protocol_v3_design_v1.3_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/plan-upgrade-20260905/mw_protocol_v3_design_v1.3_20260905.md>) | d97a0d3de6f4a5cf3ed9b8c17d43e35895c04910605605be9f668aba0f80efc5 |
| [/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/plan-upgrade-20260905/mw_protocol_v3_execution_handoff_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/plan-upgrade-20260905/mw_protocol_v3_execution_handoff_20260905.md>) | ab5136d65bedf28f81d6c64405f71130986fa415f0e1dbc7b7e7b793a149e200 |
| [/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md>) | 040eb6ad323047737e8be6a3a23344fdb719dc85230ef7994b96c9af29257607 |
| [/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx](</Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx>) | 018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756 |

### 14.2 补充模板来源

| 文件及意义 | 当天SHA-256 | 与既有记录 |
|---|---|---|
| [TP-MA-07_研究流程图示例.svg](</Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07_研究流程图示例.svg>)：支持SVG，example-only | c08dc55324b92ed45e283335c1e28a7955993cd42f687c0ca1395c4730c0372c | 一致 |
| [TP-MA-07 临床试验方案（2期或3期）_AI修订追踪版_20260905.docx](</Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_AI修订追踪版_20260905.docx>)：修订历史，不替代清洁版 | cc352adc4a2363a14eabc143a0298c9ad25fcacf43442724dc44738b4ee1e319 | 一致 |
| [CMSS-SOP-MD-5101-R03-00  临床研究方案QC表_修订版.docx](</Users/smkzw/Documents/康哲项目资料/SOP/CMSS-SOP-MD-5101_GCP2026_ICHE6R3_修订版_DOCX/CMSS-SOP-MD-5101-R03-00  临床研究方案QC表_修订版.docx>)：3R.5来源；文件名中R03-00后有两个空格 | 5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9 | 一致 |
| [CMSS-SOP-MD-5101-T02-00 I期临床研究方案模板_修订版.docx](</Users/smkzw/Documents/康哲项目资料/SOP/CMSS-SOP-MD-5101_GCP2026_ICHE6R3_修订版_DOCX/CMSS-SOP-MD-5101-T02-00 I期临床研究方案模板_修订版.docx>)：3R.6推荐候选，尚待用户选择 | fb89e3eb539e17485274f0c6c4add78527fe596c8c0a20b82e448b94fa7676db | 一致 |

### 14.3 状态、review、来源准备与历史设计

| 用途 | 路径 |
|---|---|
| 当前附加Plan | [plans/mw_protocol_v3_review_amendment_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/mw_protocol_v3_review_amendment_20260905.md>) |
| 状态索引（历史表与当前指针分开） | [plans/mw_protocol_v3_execution_tracking_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/mw_protocol_v3_execution_tracking_20260905.md>) |
| Trellis执行规范 | [.trellis/spec/protocol-v3.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/spec/protocol-v3.md>) |
| 当前Task3R.3 PRD | [.trellis/tasks/09-06-protocol-v3-3r3/prd.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-06-protocol-v3-3r3/prd.md>) |
| 当前Task3R.3 design | [.trellis/tasks/09-06-protocol-v3-3r3/design.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-06-protocol-v3-3r3/design.md>) |
| 当前Task3R.3 implement | [.trellis/tasks/09-06-protocol-v3-3r3/implement.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-06-protocol-v3-3r3/implement.md>) |
| 当前Task3R.3 checkpoint | [.trellis/tasks/09-06-protocol-v3-3r3/checkpoint.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-06-protocol-v3-3r3/checkpoint.md>) |
| 完整工程review（含已被修复/撤回历史） | [reviews/mw_protocol_v3_engineering_review_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_engineering_review_20260905.md>) |
| 前端专门发现 | [reviews/mw_protocol_v3_frontend_readonly_findings_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_frontend_readonly_findings_20260906.md>) |
| 全仓旧链失败处置 | [reviews/mw_protocol_v3_legacy_collection_disposition_20260905.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_legacy_collection_disposition_20260905.md>) |
| P1R scoped integration | [.trellis/tasks/09-05-protocol-v3-p1r-integration/checkpoint.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-05-protocol-v3-p1r-integration/checkpoint.md>) |
| 1R.2功能与未收束状态 | [.trellis/tasks/09-05-protocol-v3-1r2/checkpoint.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-05-protocol-v3-1r2/checkpoint.md>) |
| 1R.3集成验收 | [.trellis/tasks/09-05-protocol-v3-1r3/checkpoint.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-05-protocol-v3-1r3/checkpoint.md>) |
| 1R.4持久化与兼容验收 | [.trellis/tasks/09-05-protocol-v3-1r4/checkpoint.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-05-protocol-v3-1r4/checkpoint.md>) |
| 1R.6模型与probe验收 | [.trellis/tasks/09-05-protocol-v3-1r6/checkpoint.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/.trellis/tasks/09-05-protocol-v3-1r6/checkpoint.md>) |
| 3R.1来源核对 | [reviews/mw_protocol_v3_3r1_codex_source_checks_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r1_codex_source_checks_20260906.md>) |
| 3R.4依赖准备（不是已实现图） | [reviews/mw_protocol_v3_3r4_dependency_preparation_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r4_dependency_preparation_20260906.md>) |
| 8月12日暂停 | [runs/MW_PROTOCOL_V3_TASK21_NO_LOSS_PAUSE_20260812_0708.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/runs/MW_PROTOCOL_V3_TASK21_NO_LOSS_PAUSE_20260812_0708.md>) |
| 8月Phase1功能门 | [reviews/codex_mw_protocol_v3_p1g1_functional_gate_20260812_review.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/codex_mw_protocol_v3_p1g1_functional_gate_20260812_review.md>) |
| 原始多Agent设计 | [plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md>) |
| 原始设计决定 | [plans/mw_system_rearchitecture_design_decisions_20260808.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/mw_system_rearchitecture_design_decisions_20260808.md>) |
| batch1逐段来源义务 | [reviews/mw_protocol_v3_3r3_batch1_content_spec_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch1_content_spec_20260906.md>) |
| batch2逐段来源义务 | [reviews/mw_protocol_v3_3r3_batch2_content_spec_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch2_content_spec_20260906.md>) |
| batch3逐段来源义务 | [reviews/mw_protocol_v3_3r3_batch3_content_spec_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch3_content_spec_20260906.md>) |
| batch4逐段来源义务 | [reviews/mw_protocol_v3_3r3_batch4_content_spec_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch4_content_spec_20260906.md>) |
| batch5逐段来源义务 | [reviews/mw_protocol_v3_3r3_batch5_content_spec_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch5_content_spec_20260906.md>) |
| batch6逐段来源义务 | [reviews/mw_protocol_v3_3r3_batch6_content_spec_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch6_content_spec_20260906.md>) |
| batch7逐段来源义务 | [reviews/mw_protocol_v3_3r3_batch7_content_spec_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch7_content_spec_20260906.md>) |
| batch8逐段来源义务 | [reviews/mw_protocol_v3_3r3_batch8_content_spec_20260906.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/reviews/mw_protocol_v3_3r3_batch8_content_spec_20260906.md>) |

### 14.4 关键代码冻结身份与源码导航

下表是本轮读取当前文件的hash，不是重新验收。3R.3内容文件与checker/assembler的接受范围仍按第7节分别判断。

| 文件 | SHA-256 |
|---|---|
| [packages/contracts/workbench_contracts/protocol_v3.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages/contracts/workbench_contracts/protocol_v3.py>) | b76a048ff1f50cb89ea0504819281e7ef0d0f6f481c73496d577b2cb7ba0f2e9 |
| [services/api/app/protocol_workflow/registries/chapters.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api/app/protocol_workflow/registries/chapters.py>) | 9297ed918d402a46ce47cc2ad15e80dda7ab8cf07a38632ecef4049eb9f1b739 |
| [scripts/qc/protocol_v3/lint_chapter_registry.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/scripts/qc/protocol_v3/lint_chapter_registry.py>) | 348abbd00a047097eaab20310fa2d6c4bf19030cc94801c089b0ae308887b353 |
| [scripts/qc/protocol_v3/assemble_chapter_registry.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/scripts/qc/protocol_v3/assemble_chapter_registry.py>) | 3c96750782c68a1473715388a33f845c33b250cf04ab200e46187c99984c2b63 |
| [tests/fixtures/protocol_v3/chapter_content_v2/batch1.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/fixtures/protocol_v3/chapter_content_v2/batch1.json>) | bafa03e19765408c4d7aa74d51eb8bd697dd1840c1e1d48dc4a287ebbfee8cfa |
| [tests/protocol_v3/test_chapter_batch1.py](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/test_chapter_batch1.py>) | f04564b29ab7ef79941dfd567f5e6b62d1960594777e87e5d530f6e17d21612b |

逐个模块、前端组件、样式/测试文件的可点击路径：[SOURCE_COMPONENT_INDEX.md](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/SOURCE_COMPONENT_INDEX.md>)；机器索引：[source_component_inventory.json](</Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/handoff/2026-09-11/source_component_inventory.json>)。共87个文件；不把目录/文件存在等同业务已实现。

## 15. 当前原生 Goal 原文（逐字保留）

2026-09-11通过正式get_goal只读取得，状态paused。下面仅复制objective，不重新激活、不改写目标。原文中的1R.2续作位置、阶段门泛称，应结合第3节后续用户决定和第4/7节最新状态解释。纯文本文件的UTF-8 SHA-256：fcc090427b9d7c9d78bd7143ddec7845940f76bf86d19520c887919ee8ac30b6。

~~~text
持续完成医学写作子系统 Protocol v3 的工程审阅、修复、构建和真实验收，直至形成适合我个人使用的完整研究方案工作台。不要停留在分析、演示或测试数字；在授权范围内连续推进，遇到必须由我决定的问题才无损暂停。

一、权威与续作位置

隔离项目：
/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313

首先完整读取最新全局 /Users/smkzw/.codex/AGENTS.md、隔离项目 AGENTS.md，以及相邻 plan-upgrade-20260905 目录内的 design v1.3、Implementation Plan v2、execution handoff。再读取隔离区 plans/mw_protocol_v3_review_amendment_20260905.md、execution_tracking、最新工程 review 和无损检查点。

Implementation Plan v2 加用户批准的附加修订为当前任务权威；冻结的 2026-08-09 原计划仅继承未被替代的要求。核对当前文件系统、Git 差异、权威哈希和验收证据，不按旧 Goal 或历史恢复提示盲目续作。

已验收 Phase R/H-R 和 Task 1R.1；确认当前文件没有相关漂移后，从 Trellis 管理接入及 Task 1R.2 开始。不得重做已完成阶段，也不得重跑旧分诊、下载、OCR 或五个失败项。相关源码或环境变化时允许有针对性的回归验证。

二、用户与产品目标

始终站在“懒惰、视觉敏感、不熟悉计算机和 AI 使用的资深医学写作人员”视角构建。真正做到 AI lead：AI 理解已有材料、提取事实、给选项与推荐、写完整初稿；用户主要做简单确认和点选，仅在必要时少量修改，最终获得内容规范、格式完善、可进入申报流程的研究方案。

不要要求用户理解模型、提示词、任务队列、哈希或技术错误码。页面清晰、安静、精致，一屏一个主动作；错误必须说明影响、已保留的内容和下一步。

标准 II/III 期路径从建项到初稿到导出，关键点击不超过20次，包含适用的高风险确认和原生文件操作；必填自由文本不超过5处。正文区字号至少14px，UI至少12px，优先采用更舒适的16px/14px。用真实浏览器和实际操作计数验收。

推荐默认预选，但不等于已经确认。主要终点、估计目标及伴发事件策略、样本量假设、对照选择、非劣效界值、期中分析及alpha消耗、剂量、核心人群定义，必须逐卡明确人审，并显示监管答辩级红色风险标识。理由由AI预填并允许修改，禁止“至少10字”等机械校验。内容变化后只重开受影响的确认。

三、Trellis 项目管理

使用 trellis-framework 技能，在隔离项目接入 Trellis；保留已有用户配置，不修改全局或 live 配置。Trellis 管理任务 PRD、依赖、执行状态、工程规范、上下文和验收证据，保留原 Plan 的任务编号与串行门。

Plan 管需求与任务顺序，Trellis 管执行状态，避免两套重复看板。已有验收记录只引用原始证据，不重写历史或伪造重新验收。每项任务明确范围、允许文件、依赖、失败测试、完成条件、验证证据和下一安全动作。

Trellis 不替代当前 workflow guard、路由清单和 runner，不启用绕过治理的自动派发。Codex 负责分解、整合和最终验收；工程 subAgent 按实际需要并行审阅、交叉验证，避免多个执行者同时修改同一文件。执行者不得自行关闭自己的任务；由独立 verifier 验证后同步任务状态。

四、执行纪律与超长等待

每个阶段开始、每次派发前、用户改变要求后、上下文压缩或恢复后，以及出现重复失败或路由异常时，重新读取最新全局 AGENTS.md 和当前任务记录。遵循当前方法学、执行/会商机制和 Token 节省规则，不照搬旧项目文件中的过时路由表。

首次使用测试者、执行者、会商或产品模型 adapter 时，先进行与该 harness 匹配的最小连通性检查，核实实际 provider/model/effort。健康检查不是实际运行成功的替代证据。

测试、执行和会商期间保持超长等待：使用 runner 的长 hard wait、完成事件及必要的 lease heartbeat。不要因运行缓慢就重派、强杀或随意 fallback；不要用固定间隔轮询反复消耗模型轮次。平台要求短时返回时分段等待同一运行句柄，不启动重复任务。仅在确认终态失败、不可用或验收失败后按当前 manifest 处理，并保留实际调用与恢复 lineage。

所有 retry、resume、fallback 先查询 logical work key；unknown_outcome 必须先对账，禁止自动重派。凭证只在内存中使用，不进入 prompt、registry、checkpoint、trace、日志或交付物。

五、工程方法与模型配置

每项改动先写能证明问题的失败测试，再做最小完整实现。优先复用现有实现、标准库和成熟工具，避免为了“多 Agent”堆叠平台、数据库和抽象。不得删除负向 fixture、降低 gate、修改 expected 或使用 xfail 掩盖问题。

Task 1R.4 按已批准方案实施：简化内部实现和用户展示，但保留断点恢复、过期检测、防重复调用、安全记录与必要旧接口兼容层。

产品默认模型为 glm-5.3-flash，thinking=max；鉴权来源与 omp 的 zhipu-coding-plan 一致，但不复制或落盘 key。deepseek-v4-flash(max) 仅为需用户确认的可配置备选。declared 与 effective 身份缺失或不一致时 fail closed。

OCR 使用 PaddleOCR 官方 PaddleOCR-1.6-vl，翻译使用 Hy-MT2-30B-A3B-oQ8-MLX，按项目约定经过共享 oMLX workload gate 并正确持有、续约和释放 lease。产品真实模型调用在1R.1–1R.5期间禁止，1R.6按计划先做最小真实探针；工程审阅 subAgent 不受该产品调用禁令限制。

这是个人本地使用系统，允许使用 PyMuPDF，不再将其许可路线讨论作为当前工程阻断，也不为规避它提前改造旧 PDF 链。仍需记录依赖版本、用途并验证环境；不得污染 live 或全局运行环境。

六、真实质量与最终验收

每次出现预期外结果，必须模拟真实用户深挖根因。没有找到竞品方案、正文不完整、推荐缺依据、保存状态异常或格式错误，都不能仅因按钮能点、流程能通就接受。始终以第一性原理和批判视角构建、测试。

模板权威为 TP-MA-07 清洁版 v2.0；逐叶落实内容义务、格式和正负 QC 合同，不以标题齐全、字数达标代替正文质量。医学与监管要求按适用权威来源核对，重要事实、参数、计算和引用可追溯；缺失事实不得由模型编造。

验证跨章节的一致性，包括目标、终点、estimand、样本量、分析方法、人群、剂量、安全性和访视表。最终正文零占位符、零待确认、零生成过程提示；内部来源与AI执行记录仍须保留。

真实 API、SQLite 持久化、重启恢复、并发与重复提交、浏览器交互、中文输入法、项目切换、保存失败和异常恢复均须按门验证。原生 Word 验收必须覆盖目录、页码、题注、书签、交叉引用、横向访视表、跨页表头、字体和实际渲染；验收绑定当前源稿和最终文件，不能靠客户端声明或截图文件名冒充执行证据。

eCTD 目标是文档就绪，不冒充完整申报序列验证或正式监管批准。单元测试通过、AI审阅通过、Word生成成功和真实项目验收分别记录，不互相替代。

七、保护与暂停

严格保护并行开发中的医学监查子系统。live workbench、8910服务、plan-upgrade-20260905和外部SOP源文件只读；不得停服务、覆盖、迁移或清理。保留用户已有改动。

禁止自动删除、改写或清理历史 immutable rows、runs、records、logs、evidence、会话和检查点。原 Goal 的定期清理改为定期检查冗余与体积；如确需清理，先列明可重建对象、影响和恢复方案，取得单独授权。

按 Phase R→1R→2R→3R→后续阶段串行过门，不因阶段报告而停止已授权工作。到 Task 3R.6 的Ⅰ期模板选择、生产激活、真实项目 cutover 或其他重大用户决策点，准备清晰问题及推荐理由，按当前平台允许的原生提问机制询问并暂停。

暂停时保存状态、权威与文件哈希、验证证据、执行/会商 lineage、未决问题和精确恢复指令；不清理、不丢失、不虚报完成。正常阶段持续更新 Trellis 与简洁检查点，直到全部授权目标真实通过验收。
~~~

## 16. 给接手 Agent 的首条续作提示

以下是可直接使用的交接提示。由用户在接手任务中明确发送继续后执行，不是本交出任务自动恢复的指令：

~~~text
请按 HANDOFF_PROTOCOL_V3_20260911.md 接手医学写作子系统 Protocol v3。先完整读取最新全局与项目AGENTS、design-v1.3、Implementation Plan v2、隔离区附加Plan、3R.3 Trellis与2026-09-08无损暂停记录，并核对9月11日交接验证。
当前在Task3R.3。不要从Goal旧句1R.2或r42翻译失败项重做。R、1R、2R.1、3R.1/3R.2及3R.3 core有各自验收；首批12合同修复未验收，第二批16合同已启动过但未交付。先对账两个logical key及原生session。原model-io日志已在9月11日发现缺失，session数据库记录仍在，不能保证逐条历史完整；确认原生续接可用性，无法原生续接时显式记录恢复血统，从现有产物继续，不伪造日志或重派重复工作。
完成首批六类内容问题、17行摘要、独立证据组、原48fixture保留与有效负例，运行现有主审内容/组装/多批测试并独立复核。然后继续第二批至第八批、dependency图、R03 QC；到3R.6准备Ⅰ期模板问题卡等我选择。保持Trellis单一执行状态，阶段报告不暂停，不再让我反复说继续。
用户已批准：纯安全工程及测试不构建，旧阶段断言若不损科学性可评估废弃；1R.4保留功能恢复语义；PyMuPDF个人使用；工程subAgent允许；当前UX上限20点击/5必填自由文本。高风险8类逐卡人审，理由AI预填；最终方案内容与Word格式必须真实验收。
不碰live、8910、医学监查、plan-upgrade或外部SOP，不清理历史。产品1R.6连通性探针已经SUCCEEDED，不重复。按当前global route和runner，定期重读AGENTS；慢任务同会话长等待，先logical key对账再resume/retry/fallback。持续向完整AI lead研究方案产品推进，不以测试数字替代正文、浏览器、Word及真实项目验收。
~~~
