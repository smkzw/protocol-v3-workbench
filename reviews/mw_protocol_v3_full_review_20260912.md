# Protocol v3 全局工程审阅与重规划

2026-09-12｜Codex接回。此次工作：当前源码/源模板/接线审阅，隔离测试与具体反例，设计/Plan/Goal修订。产品暂停保持，未启动服务、OCR/翻译、真实产品模型或Word。本文后续的实现建议尚未写入产品源码。

## 1. 结论

已具备可继续使用的存储、事务/恢复、typed编排和111个模板载体合同底座，保留这些成果。下一步应以真实用户路径检验它们：先补事实类型、条件义务和精确影响传播，再交付一条Ⅱ/Ⅲ期完整路径。用户已明确选择这个顺序。

主要风险集中在“结构成果被理解成真实产品能力”：当前111合同/558fixtures完成的是结构检查，49条条件尚未执行；新前端未挂载v3 client；旧界面存在已复现的状态矛盾和恢复缺口。不能因1860项回归通过就宣称可用于完整申报。

此次按全局模块和实际用户路径审阅，不声称对整个共享工作台每行源码或每种临床设计作形式证明。完整组件/入口地图见reviews/mw_protocol_v3_component_map_20260912.md；771文件inventory用于版本边界。深审覆盖新链关键模块、60个新后端文件的职责、111合同与skills的内容义务/源定位、当前WritingPage主要读写路径。旧大型编辑器、memory测试替身、部分事件与领域定义采用结构和关键边界审阅；真实浏览器E2E与Word原生仍未执行。后端worker明确列出未深审区，Codex补读GLM transport、API请求/响应、decision replay和图服务输入接线；剩余逐行覆盖限制保留，不用组件清单冒充全部定义已读。

## 2. 来龙去脉及当前状态

1. 早期r42资料恢复是历史背景，原父JSONL已删除；本项目不声称恢复了逐条对话，也不能按当年的translation planner提示重新启动旧工作。
2. 2026-08-09冻结计划建设独立Protocol v3，保留旧链作为strangler迁移来源；8月暂停在Task2.1附近。
3. 2026-09-05用户批准design v1.3/Plan v2：新模板TP-MA-07清洁版v2、产品SQLite、typed facade、默认GLM-5.3-Flash:max、受控编辑面与Word原生/eCTD文档就绪。
4. 随后用户明确：1R.4保留功能兼容/恢复语义；工程subAgent可用；PyMuPDF个人使用不阻断；Trellis管理；20点击/5文本；纯安全专项退出；过时阶段约束经科学性/功能评估可升版；正常阶段不中断。
5. 前一Codex阶段完成R、1R/2R离线范围及3R.1/2基础，3R.3分批推进；用户要求无损暂停并转交。上位Agent于9月11日新增8个提交，完成8批111载体结构交付，开始3R.4依赖图。
6. 新交接/暂停文件名带20260912，内部记录实际是9月11日23:22/23:30附近。3R.4第一轮fresh因GLM配额错误结束，属于历史未完成验收，不代表依赖图已通过；也不是今天仍缺配额的证据。
7. 本次当前HEAD=84488d307eae240cc48808dea506691091817354；工作树包含大量已有tracked/untracked工作，不能只凭HEAD恢复，禁止reset/clean丢弃。当前Goal API仍paused且旧objective写着从1R.2开始，未随其他Agent的文档自动更新。

## 3. 本轮实测

| 检查 | 结果 | 能证明/不能证明 |
|---|---|---|
| tests/protocol_v3完整回归 | 1860 passed，1 DeprecationWarning，70.91s | 当前隔离v3回归通过；不是旧链全仓/医学/Word通过 |
| 8批重新组装 | 与历史final_all8_assembled.json逐字段相同 | 当前合同/skill/fixture与上次验收对象一致 |
| 从原始DOCX重新抽取 | SHA018d28d3…符合；node_tree逐字段相同 | 源结构/定位没有漂移；不是逐段正文医学验收 |
| full lint | complete，111/111，558 fixtures，0 error | 105标题叶+1聚合+4大纲叶+1封面；每项均明确medical judgment未执行 |
| Word声明源绑定 | required style ID均存在；required bookmarks均存在 | 消除了把ID误当名称的假警报；未证明实际输出Word或全部引用正确 |
| 前端3文件Vitest | 18 passed | 当前helper/合同测试通过，部分并不渲染组件 |
| durableJobState Node测试 | 1 passed | 此文件现有检查通过，非整个恢复流程验收 |
| 当前预览组件SSR | stale标题与verified样式/最终依据文案同时出现 | 确认状态真相错误，见UI-01 |
| 实际React StrictMode/jsdom组件对照 | 普通挂载2次mock请求并显示结果；StrictMode仅1次、停在进度状态 | 开发入口的effect重放触发UI-02；未调用真实API/模型 |
| 依赖桥接反例 | 仅变x，C{y}仍被列受影响 | 确认影响传播丢失事实标签，见RG-01 |
| 输入/条件反例 | 布尔/数值/对象拒绝，字符串false接受；无期中仍要求11项详细事实 | 确认输入合同断层及条件/required矛盾，见RG-02/03 |
| 不存在对象的错误转换 | 实际service translator→router status helper返回409、can_retry=true和“推荐已更新” | 明确误分类，见BE-01；此诊断不是完整HTTP调用 |

现有测试解释器和命令写在Plan v3。原始证据都在runs/mw_protocol_v3_full_review_20260912；两次诊断草稿的构造错误（过短node ID、漏occurrences）修正后才运行正式反例，不当作产品缺陷或有效RED。未重跑旧分诊、下载/OCR/翻译和五失败项，未重做单次产品探针。

## 4. 已确认问题与修复方案

### RG-01｜P1：影响图把无关事实传播成章节失效

位置：services/api/app/protocol_workflow/registries/dependency_graph.py:320、:348。构建neighbours时丢失shared_fact_paths，然后对所有一致性边闭包。A{x}、B{x,y}、C{y}只变x，实际返回A/B/C；没有y变更、没有派生或调度依据。

目前模块是未接入产品的3R.4首交付，因此不是已观察到真实用户文稿损坏。若直接接入确认/写作，会过度重新生成和重开确认，违背20点击和“只重开受影响”的要求。现有test_unrelated只测试断开的两个群组，reference closure与被测算法同构，漏掉桥接反例。

修复：事实标签贯穿传播，显式派生值变化才能再传播；区分候选检查与实际确认失效；保留真正调度扇出。Plan3R.4C。

### RG-02｜P1：技能输入与canonical事实类型不一致

位置：registries/chapters.py:258；packages/contracts/workbench_contracts/protocol_v3.py:654。研究事实允许JsonValue，技能输入仅Mapping[str,str]。布尔、数值、对象无法无损传递，恰与本批合同要求“裸true/false”、结构化时间/分析参数冲突。

修复：同一StudyDefinition解析到typed输入，兼容旧字符串版本，明确false/0/缺失/不适用；724路径建立可执行映射而不是只在rationale写“统一归属”。这属于接线前的真实合同缺陷，不能用全部字符串化宣称解决。Plan3R.4A。

### RG-03｜P1：条件规则与无条件义务相互抵触

位置：chapter_contracts/v2_n_11_4_9.json:25及:223附近；registries/chapters.py:591–870；schema的ConditionalApplicabilityRule.condition仍为自然语言。49条条件延期执行，14条规则的active事实又列为无条件required。

具体源DOCX body-child806写“如开展期中分析”；当前合同即使applicable=false，仍要求时点、信息量、责任、alpha、表格单元格等。反例定位的是这些不应无条件要求的字段，不把缺少来源的全部失败都归咎于条件。附录16_x3无条件要求中心实验室和销毁供应商，且没有条件规则，需核实不使用外部供应商的合法研究路径，不能用N/A冒充适用但缺失事实。

修复：true/false/unknown明确；将条件同时应用到facts/claims/evidence/objects；逐条纠偏，完整保留适用时的义务。补“无期中、无IRC、无外部供应商”等反例，不能只测试内容删掉会报错。Plan3R.4B。

### RG-04｜P1（验收缺口）：纯函数hash被描述成单次业务采用证明

位置：tests/protocol_v3/test_dependency_graph.py:549–588及dependency_graph.py:370。该测试只比较两次impact返回相同；函数输入只有registry与fact path，没有project/旧新revision/值/操作key，未提交SQLite，也没有文档采用。

不是已证明产生了重复调用或吞更新，而是3R.4所需“单次semantic effect”尚无证据。修复：保留投影hash用途；在既有UoW/CAS/ledger中做真实采用和重开对账，测试同key重放及同路径不同修订。Plan3R.4D。

### RG-05｜P2：错误图可继续产生正常执行用结果

位置：dependency_graph.py:504–664；tests/test_dependency_graph.py:412–471。未知目标/缺owner确实被标成error，但topological_order/impact仍返回可消费值；仅hard cycle抛错。诊断视图允许这一点，消费者却没有明确执行有效性约束。

修复：不必破坏原诊断能力，增加不能从error图取得可执行计划的边界与实际消费者检查。旧诊断测试保留。属于依赖正确性，不恢复被用户排除的安全专项。

### RG-06｜P2：模板文字引用尚未成为真实目标

位置：chapter_contracts/v2_n_11_4_9.json:182，写“已接受的…v2_n_13_x载体族”，当前树不存在该ID；本轮111合同只有一条required_cross_references。不能把原模板过时14.6换成另一条不存在的目标就宣称引用修复。

修复：源说明/历史编号/现行semantic target分别存放，按真实节点和项目监督安排解析；Word最后生成显示编号并验证跳转。当前style ID与bookmarks源绑定良好，避免无依据重做。Plan3R.4B、3R.5A、7R。

### UI-01｜P1：Word过期状态仍呈现最终格式依据

位置：frontend/src/features/medical-writing/MedicalWritingPreviewPanel.jsx:29–49。tone先看page_count_basis，isVerified完全不看stale；SSR实测标题“核验已过期”同时出现verified class与“可作为最终版式依据”。现有测试仅检查标签helper，因此绿灯漏检。

修复：当前状态和快照绑定优先，历史页数来源单独说明。增加真实组件的stale/unknown/刷新失败/当前verified对照。迁移V1导出页前处理。

### UI-02｜P2：StrictMode开发入口导入后卡住

位置：MedicalWritingSynopsisProjectIntake.jsx:207–211、:300；frontend/src/main.jsx:10。effect cleanup把mountedRef=false，setup不重置。React StrictMode开发重放后上传成功也忽略返回；同一组件非StrictMode对照正常。该结论限开发/集成入口，不冒称生产build一定会同样重放。

修复：setup重新声明mounted状态，异步响应再绑定generation；加入真实StrictMode组件挂载测试。现有测试主要是helper，未覆盖这个生命周期。

### UI-03｜P1：查询/结果拉取失败时删除恢复定位

位置：App.jsx:10415–10542、:10590。全文初稿和Word导出在catch中直接移除localStorage locator；monitor可能因poll预算耗尽、非终态或result下载失败抛错，此时后台工作不一定失败。用户刷新后失去恢复入口，可能重新发起工作。

Codex校正worker措辞：两者已调用pollDurableMwJob，并非完全独立的轮询实现；真正问题是locator生命周期与终态/结果确认不一致。修复：未知结果保留定位；明确取消/已确认终态/制品已取得或采用后才清理；复用现有状态模块，不重写轮询平台。PlanV1.3/4/5接线必测。

### UI-04｜P2：机械10字理由仍出现在当前流程

位置：App.jsx:8655、模板升级相邻流程；MedicalWritingAuthoringJourneySetup.jsx:2283；Synopsis intake canConfirm:219。worker把有这些约束列为“机制良好”，与本用户已批准目标冲突，Codex不接受这一评价。

修复：保留实质决定与内容差异确认，AI拟理由+点选/必要修改，删除任意字符阈值。同步查API schema/服务验证，不能只改按钮。纯安全专用放行界面不迁入新路径；涉及医学证据缺口时仍须明确选择与理由，不扩大新平台。

### UI-05｜P2：v3新client尚无消费者；旧流程负担大

位置：protocol-workbench/protocolWorkspaceApi.mjs；App.jsx WritingPage。新client未接UI是原6R未实施范围，不是刚引入的回归。当前旧链已具备整稿生成入口，不应声称只有逐章生成；但默认/冻结等仍分散。worker估算120–135点击基于逐章路线且未浏览器计数，只能作负担风险，不能当当前唯一最短路径或硬门实测。

修复：以V1整稿路径为默认入口，自动准备编辑副本、合并低风险操作，高风险逐卡；把v3API/client/真实用户动作一并测试。风险页签目前无面板且永远禁用，可从常驻UI移除。局部标题fallback属于窄路径潜在问题，随进口旧稿案例确认，不列成普遍生产损坏。

### BE-01｜P2：找不到研究对象却提示重新确认推荐

位置：application/service.py:940–957、api/router.py:164。独立后端worker发现，Codex调用真实转换函数复验：AggregateNotFoundError被归入MW-PRO-P1-DECISION-CAS，HTTP409、can_retry=true，提示“推荐已被更新”。这与项目下研究对象不存在的实际原因不符，用户照着重试也不能恢复。

修复：复用已有未找到错误包，真实缺失返回404；真正版本竞争保持409；缺repository配置的潜在错误另归为非用户可重试的服务错误。相邻测试test_application_service.py:648目前只锁code，按正确行为补HTTP/文案/是否可重试用例。用户已经授权过时断言升版，不为这类常规修复重复提问。Plan3R.4D。

### RT-01｜V1接线缺口：模型可连通不等于章节执行器可用

位置：runtime/adapters/zhipu_api.py:248–291、runtime/harness.py:264、graph/runtime.py:1232–1274。GLM transport现阶段仅把artifact ref/hash/snippet装成消息；每项snippet最多8192字符。图runtime仍建立deterministic-offline合同，build_zhipu_api_adapter在当前产品模块没有实际接入调用方。这符合已完成的连通性/离线阶段范围，不能认作新回归。

尚需把章节skill指令、typed事实、完整且相关的真实材料、输出schema编译到真实请求，并验证输出后才采用。远端模型不能因收到本地ref就读取文件；8192字符片段也不代表整份输入。PlanV1.3现明确请求组装、覆盖、实际validator与真实模型接线验收，复用transport而非再建harness。

## 5. 审阅中的纠正与保留

- 保留111载体结构成果，本轮fresh assembly与源提取双重一致支持这一范围；不要求重造全部合同。
- 所有required style ID和书签都在模板中，不能把ID当显示名称制造全部格式错误的报告。
- “新前端未挂载”是未完成产品工作，不是router从未挂载：后端composition已做，UI消费尚未做。
- 原先跨项目异步污染的泛化结论已因App key重建撤回；不能再次以一个缺失父组件的探针复活。无消费者useDurableMwJob的error刷新仅是低优先级候选，不列为可达缺陷。
- 现有保存409保留恢复稿、实际revision accept-and-apply、领域版本绑定等有价值，沿用，不为了简化而删掉。
- 结构passed明确保留deferred信息；应修订验收语言与消费者接线，而不是把代码已经写明的延期说成秘密伪造医学检查。

## 6. 为什么看起来长期停在底层

可证实的直接暂停原因：用户明确要求无损暂停；上位Agent的3R.4fresh遇配额终态失败；当前原生Goal仍paused。没有证据说明存在一个强制每几分钟停止的系统计时器，不把此前自动分轮行为归因于不存在的产品机制。

工程层面的拖累是：Goal和索引仍保存旧入口；3R.4缺完整PRD、验收名称与实际谓词不一致；从结构合同到真实输入/条件/采用/前端/Word之间仍有断层；以按文件/阶段交付为重，完整用户路径被排得太后。每个阶段结束发最终答复，又使用户需要反复唤醒。这些是本轮依据资料的分析，不是恢复出的原始逐条对话。

解决方法已落实新Plan：一个Trellis状态入口、精简但具体的Goal、3R.4A–D、完整路径V1及后续全范围V2；正常阶段用进展更新持续施工，非必要不问权限。不删除科学义务，不增加安全专项，复用现有底座和整稿功能。

## 7. 功能与路线建议

立即做：类型保真/适用性/影响与采用，当前版本状态真相，恢复定位；按资料自动填事实；推荐有依据和备选；一键完整初稿、一次整稿采用；真实Word制品下载。

随V1做：精简准备/建议/正文/导出四阶段，八类人审，自动暂存/保存失败恢复，结构化反馈、精准引用和SOA表格；适用性和源缺口只在相关位置显示。≤20/5以实际完整路径计算，字号使用computed style，不拿全局CSS频次代替页面验收。

保留并扩充：公司先例只读检索、R03原子检查、术语/缩略语/参考文献闭合、真实模型准入、Word回流和多场景E2E。公司常用信息可自动填身份/联系信息，科学参数不盲目继承旧项目。

减少或后置：死页签、无调用方hook优先维修、重复管理看板、固定多Agent人数、重复基础设施、LangGraph/MAF比较、浏览器Word排版引擎；Standalone Synopsis、竞品对比、修订说明和审稿回复保留后续计划。

本轮复核官方第8号公告使用“可按照eCTD方式申报”，旧文档“全部IND强制”停用；保留用户要求的eCTD文档就绪交付。[官方公告转载](https://yjj.sh.gov.cn/qtgzwj/20260115/975448586280412d9ddb6a2fec2cb44e.html)。E6(R3)方案内容对照Appendix B；旧R03源标签不冒充R3新条款。[ICH原文](https://database.ich.org/sites/default/files/ICH_E6(R3)_Step4_FinalGuideline_2025_0106.pdf)。其他已核实边界由新设计继承，不在此重复扩大法规结论。

## 8. 已更新文档与当前Goal

- plans/mw_protocol_v3_design_v1.4_20260912.md：事实/条件/依赖/采用、四阶段交互、视觉、Word和范围边界。
- plans/mw_protocol_v3_implementation_plan_v3_20260912.md：文件、步骤、行为验收、原任务映射、V1/V2及明确替代条款。
- plans/mw_protocol_v3_goal_prompt_20260912.txt：可直接手动替换Goal的优化文本，保留周期重读AGENTS、长hard wait、同句柄等待、恢复对账和连续施工要求。
- runs/mw_protocol_v3_full_review_20260912/GOAL_BEFORE_VERBATIM.txt：本轮get_goal读取的旧objective原文，未从历史摘要拼接。

本平台可用Goal工具不能修改进行中/暂停Goal的objective或恢复状态，因此没有改Codex内部数据库，也不声称文件写好等于App Goal已改。当前产品暂停不因文档修订自动解除。

## 9. 独立审阅、裁定与证据限制

两个只读worker和一个fresh设计reviewer均已终态返回。实际报告：

- runs/execution/mw_protocol_v3_full_review_20260912/worker_01.md：后端；最终实际Pi/opencode-go/muse-spark-1.3-contributor，requested effort=xhigh，实际effort未单独报告。
- runs/execution/mw_protocol_v3_full_review_20260912/worker_02.md：前端；ZCode/GLM-5.3-Flash，模型I/O记录有max；工具计数遥测只显示末段2次调用，不足以证明报告所称全部读取，关键发现已由Codex读源码/诊断复核。
- runs/conference/mw_protocol_v3_replan_review_20260912/general_single_object.md：fresh设计审阅；另一个Pi/Muse会话，requested xhigh，实际effort未单独报告；输入冻结在runs/mw_protocol_v3_full_review_20260912/plan_review_snapshot。

后端runner自动使用声明的fallback；顶层effective仍写ZCode/GLM，actual round却是Muse，fallback理由“无可恢复会话”又与primary attempt的exit0/session id冲突。因此只确认实际最终模型、报告与验证，不推断今天GLM额度用尽或健康会话不可恢复。audit-execution通过只表示该工具规则通过，不能消除这项原始回执矛盾；后续工程派发前需按最新runner/manifest对账，不改本项目产品模型配置。

fresh reviewer与最终后端worker同模型、不同会话，属于上下文独立而非跨模型后端复核；它读取过前端诊断，不是完全隔离于所有执行意见。Codex保留该限制，没有为凑模型人数再派发。所有节点、原始日志和失败/切换血统保留，无清理。

已采纳：无期中必须处置全部专属义务（含canonical_reference）；按声明类型兼容旧字符串；影响记录via_paths；unknown保留候选检查；重组装/新hash；高风险卡适用性和点击证据；前后端取消机械10字规则；BE-01与真实模型接线补齐。

经源码裁定未照搬：不能把所有显示单元格强改JsonValue；不能把bool("false")的语言特性当已发生的业务损坏；不能删除unknown条件的潜在依赖；不能让上游变化改写已完成操作的精确重放结果。历史回执与当前确认有效性分别验证。fresh所称缺失的综合review在其读取时尚未生成，现已存在并核对链接；120–135点击不是实测；不存在目标v2_n_13_x已由Codex定位到合同182行。

再核对StudyDefinitionReducer.replay_or_apply:368–397后明确：历史重放返回当前合法后继definition不变、原effective_decision及原效果证据；“返回原回执”不是回退研究版本，也不是强行缓存旧HTTP响应。新设计/Plan/Goal已保留这一现有语义。

后端剩余F2–F7分级：缺repository错误文案随BE-01处理；causeless abort、RESERVED+result仅在异常构造/未接线路径出现，暂列低优先级；查询BEGIN IMMEDIATE可能争写锁，未测得卡顿，不先加读写平台；启用时registry错误的启动行为随真实激活检查；死分支/日志措辞不抢占完整路径。artifact_store未接线是未来任务，当前无调用方，不能泛称产品存储坏了。

本轮最终结论是“工程审阅及文档修订交付”，不是3R.4或产品验收。保护校验、文档引用/状态和runner检查结果见runs/mw_protocol_v3_full_review_20260912/final_verification.json。当前暂停保持；唯一下一实施动作是核对最新树后，从3R.4A已确认反例开始。


## 2026-09-13 后续源核对：生成与Word验收消费者

以下为本轮继续实施中的新增证据，不覆盖前述2026-09-12历史状态或把尚未实施项标完成。

- GLM传输层的成功仅为请求/身份/回执成功：离线注入响应“This is not chapter JSON.”，实际HarnessDispatcher仍返回success，sink保存该原文；请求messages仅含seed/ref/hash，output_schema_ref未进入模型消息。证据runs/mw_protocol_v3_3r5a_source_audit_20260913/v1_transport_boundary_probe.json。没有真实模型/网络/凭证调用。这是缺少章节应用消费者的范围，不能误修为让通用transport承担全部医学验证，既有1R.6传输验收仍保留。
- V1.3必须将实际ChapterPromptContract、适用内容义务、完整选定证据、原生typed事实及已解析输出schema编译进模型请求，并对sink实际字节做hash核对、JSON/Pydantic解析、check_applicable_output，之后再进入整稿候选。请求中的schema名称被原样放回receipt，不是provider证明产物遵守该schema。8192字符snippet是现有摘要限制，不是全文证据完成证明；不以机械切成大量片段掩盖总context超额，按相关完整证据单元和实际模型容量编排。
- 现有ChapterSkillOutput为facts/claims/evidence/objects结构，SemanticDocumentRevision另有有序SemanticBlock；尚无实际两者到编辑保存/Word的应用装配链。优先实现一个确定性的typed转换和整稿采用消费者，验证段落/表格/公式次序、稳定ID、实际出处、重复保存及研究版本绑定，不另造文档平台。模型自报passed不参与接受。
- Word旧PoC的成功交集和32项上限遗漏失败对象，已用原函数反例验证；源所需13种样式和172书签本身均存在。见reviews/mw_protocol_v3_3r5a_source_preflight_20260913.md。产品化逐一核对应有对象，不重写历史PoC结论或以安装Word版本代替实际运行。


## 2026-09-13 D最终制品的owner反例（回修中，非接受）

首轮worker十个源码/测试hash全部与owner冻结的source_before.json相符；实际GLM-5.3-Flash/max同session执行3005.143秒，2230测试通过。另行实际mounted API/隔离SQLite三反例全部失败，见runs/mw_protocol_v3_3r4d_preflight_20260913/owner_adoption_cases.json：

- P1：原精确请求在当前模板不可用时422且调用loader一次。历史replay应只依赖记录时材料，回原回执且保留后继revision。首轮报告将模板漂移409称合理，与用户合同不符，不能接受。
- P1：同一idempotency_key换decision及新CAS返回200，再改写申办方。无side-effect也要按逻辑操作身份拒绝不同意图，不只查CAS triple。
- P1：期中true+alpha参数采用后，仅改false仍200且保留参数。必须看完整结果事实；明确退休应能一次合法修改，保留历史，不能只补永久拒绝。

三项已合并交回原session定向修复（owner_followup_01，86523），不重复启动新worker。独立整合review待终态源码冻结后执行。以上是实证功能/研究一致性缺陷，不是安全专项。

后续完整路径的可执行设计补充：章节输出当前分组claims/objects且对象无稳定实例ID，不能可靠还原正文与表格穿插顺序，V1.3需显式有序内容/对象及证据映射，复用SemanticDocumentRevision，不造第二事实库。真实18份资料与现有5份支持性条款库已只读对账；clean文件名不保证无修订，9DOCX结构筛查发现一份Ⅰ期文件仍含6处插入标记。上述准备材料未构成真实项目准入、产品生成或Word验收。


## 2026-09-13 真实应用与模型输入增量
应用限定复核及owner改进见[codex_mw_protocol_v3_v1_1_application_scoped_review_20260913.md](codex_mw_protocol_v3_v1_1_application_scoped_review_20260913.md)。实际SQLite/API/React资料链已完成有限操作验收，真实GLM全文参考整理已返回，但推荐/整稿/Word仍未通过；不要把前文接手基线与最新进展混作同一版本。
真实材料揭示八字段入口和最终设计之间仍需语义结构桥接：互补信息不能当互斥选项，样本量不能塞入人群。V1.2按治疗期/组保留复合设计，引用检查仅证明文本出处，科学含义还需逐项复核。当前独立来源语义审阅的具体运行状态以Trellis checkpoint和runs/mw_protocol_v3_v1_1_seed_semantic_review_20260913终态receipt为准，未返回时不报告通过。
当前已知有限UI遗留：缺口仍为长串说明；自动后台任务短暂显示继续入口；仅已知runID/同浏览器localStorage恢复，不是跨浏览器自动任务发现；完整App导航与原生Word未验收。所有事项沿完整路径继续处理，不重开无关旧阶段或新建安全专项。
