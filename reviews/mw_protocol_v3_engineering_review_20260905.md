# 医学写作 Protocol v3 工程 Review

日期：2026-09-05。范围：隔离工程的源码、合同、计划、历史验收、离线测试及适用标准核查；独立工程 reviewer 已参与。当前阶段未做浏览器视觉、真实产品模型、真实项目迁移或原生 Word 验收。以下是工程基线审阅，不把规划能力写成现有能力。

## 结论

工程不是“已经可用、只差润色”，而是**旧写作产品仍承担用户流程，新版已实现较强的离线领域内核，但产品存储、挂载、执行编排、完整模板合同和新前端尚未闭环**。继续沿 v3 接口渐进替换有价值，无须推倒所有历史成果；先验证新版能通过实际产品入口保存、恢复和执行，再构建完整用户流程。

保留：结构化研究定义、明确医学决策、输入/输出溯源、CAS防并发覆盖、事件回放、未知结果禁止重派、语义文档、Word 原生格式门。调整：繁杂运行态不要透出给用户；不要把所有资料整理步骤都要求用户逐项操作；不要用 arbitrary 10 字理由、重复确认和技术状态作为可信度的替代物。

## 来龙去脉与证据边界

1. r42/旧写作流水线已有资料检索、分诊、原文、翻译、语料、设计、编辑器、导出能力及复杂恢复机制；本轮不重复旧任务。
2. 8月冻结计划选择 typed domain contracts + ports/UoW + 事件/制品分离，完成 Phase0/Phase1 离线内核。SQLite/PostgreSQL 做过 PoC 对照，选择 SQLite；不是产品已激活。
3. 8月12日停在 Task2.1：三 case typed contracts/fakes。Task2.2未实施。P1是 functional gate，安全门曾 USER_EXCLUDED，不是安全已PASS。
4. 9月5日新 design v1.3/Plan v2 替代原直接续Task2.2的路线。模板升 TP-MA-07清洁v2，默认模型改GLM；先Phase R→1R产品闭环。
5. 本轮五项用户给定权威SHA均实测匹配；隔离起点 HEAD3d6772f，实测26个提交（另一review说25有1个计数差）。live 已有持续监查开发，不能套用7月“非git工作区”的旧认知。

## 当前前后端地图

以下路径均相对隔离根；组件分组是职责，不意味着全已产品验收。

### 后端新链

| 组件 | 含义与逻辑 | 当前限制 |
|---|---|---|
| packages/contracts/workbench_contracts/protocol_v3.py | 研究定义、决策、证据、章节/节点执行合同、工作流等 typed schema；冻结/哈希边界 | 强约束需用于真实执行；字段精简不可丢掉实质输入依赖 |
| canonical/study_definition.py + decisions.py | 已确认事实和设计决策归约；CAS revision，避免过期选择覆盖新事实 | AI候选不等于canonical；前端必须先确认后写入 |
| canonical/document.py + hashing.py | 语义正文及引用/表格对象的版本、绑定与hash | 尚非106叶完整成稿保证；有block不等于有可申报正文 |
| ports/repositories.py + unit_of_work.py + artifacts.py | 隔离存储实现的操作边界、事务、制品端口 | 不能对内存实现的通过直接外推到SQLite |
| storage/memory.py | 测试参考仓库、事务快照回滚、索引 | 非持久产品存储；进程结束丢数据 |
| storage/selected.py + sqlite.py | 已选SQLite的版本/能力与factory；本轮真实产品adapter及显式product factory已通过Task1R.1独立验收 | 版本化迁移、事务/批量原子性及约束反例已闭合；未挂载产品入口，不能当整个1R通过 |
| events/models.py + store.py + unit_of_work.py | 事件及同事务写入/回放；读模型可重建 | 回放必须保留旧事件原hash与版本语义 |
| events/outbox.py + inbox.py | 副作用派发与结果/消费去重；处理崩溃窗口 | 收到结果≠业务已采用；handler仍需要业务幂等 |
| runtime/reservations.py + idempotency.py | 发送前占位、运行中、明确终态/未知结果、显式重试决定 | 物理重试与业务semantic effect必须分开；用户已批准保留安全兼容 |
| runtime/harness.py + adapters/* | 节点执行输入/模型/工具/凭证策略；Codex/直连/OMP/oMLX适配 | 真实GLM身份和凭证内存绑定尚未接通；配置存在不是实际调用证明 |
| application/commands.py + queries.py + service.py | commands改状态、queries读投影，集中UoW事务和业务错误 | 真实product SQLite + API restart/replay尚待1R |
| api/router.py + schemas.py | 项目范围API工厂、revision/idempotency mutation、稳定中文错误 | main.py未挂载，单独TestClient factory绿不是产品可达 |
| agent5/coordinator.py + run_manifest.py + exception_cards.py | 调度/分解、固定manifest、可解释异常卡 | 无最终生产graph runner；不是完整多Agent写作已可用 |
| registries/loader.py | 角色/技能/模板等registry读取与约束 | 新模型、新模板和版本声明必须与实际一致 |
| artifacts/local_store.py | 内容寻址本地制品 | 1R.5仍需path/symlink/cross-project等对抗测试 |
| legacy/cutover_state.py + mutation_guard.py | 旧链→shadow→新canonical的写禁令、旧只读视图 | cutover表目前内存态，不能充当持久feature flag |
| legacy/migration_inventory.py + migration_map.py + quarantine.py | 旧记录映射、不可映射显式隔离，不静默丢弃 | 当前基于传入记录，未验收真实live读库 |
| legacy/mutation_route_inventory.py | 旧读写入口清单及漂移检查 | 新live共享源读取行为已有变化，cutover前须重新对账 |
| pocs/protocol_v3/orchestrator/* | 入排、目的-estimand-终点、样本量三case合同/fakes |75测试通过；真实typed facade/kill runner未做 |

### 前端与旧链

| 组件 | 现有职责 | 建议处置 |
|---|---|---|
| App.jsx / WritingPage | 文档会话、工作稿、修订、重绑定、冻结、导出、侧栏及大量互相依赖state | 不再加新v3业务；新workspace组件独立挂载。旧数据与保护保留 |
| MedicalWritingAuthoringJourneySetup | intake/framing/PICOS、证据准入、AI预填、流程推进、适用性及创建文档 | 新版把非必要人工步骤改自动；只暴露真正需医学判断的卡 |
| medical_writing_study_consistency.py（旧后端） | 比较文档与StudyDefinition的ID/revision/hash及工作稿调和状态；结构化字段优先于旧自由文本，部分冲突仅warning | “current”首先是版本绑定状态，不等于逐段医学一致性已验证。保留绑定/受影响章节机制；新版另跑正文义务和跨章QC，不让一个绿色状态代表全部验收 |
| MedicalWritingSynopsisProjectIntake | 文件先行建项、上传/解析任务、取消/恢复/确认 | 保留文件先行路线，但纳入统一草稿状态/去重，而非重复填写 |
| LegacyAuthoringBootstrapPanel | 从旧方案恢复项目信息与权威绑定 | 移为低频迁移入口，不放标准建项主线 |
| AuthoringCandidatePackagePanel | 分模块推荐/备选/缺口、候选采用和字段覆盖回执 | 有价值；v3需默认推荐预选，严分高风险逐卡与低风险整包 |
| AuthoringCompetitorDrawer | 抽屉式竞品处理，隐藏后保持状态/任务 | 保留“可查看来源”的渐进披露；主界面不要求用户管理流水线 |
| MedicalWritingLiteraturePanel | 文献/证据选择与插入、校验例外 | 来源不足要自动换检索策略/列具体缺口，禁止空成功 |
| ProtocolModuleResolutionPanel | 章节适用/不适用/暂缓及渲染策略 | 不允许把unknown直接隐藏后仍声称完整；必要项缺失阻断最终稿 |
| InterventionRulesEditor | 试验药、调药、合并/补救治疗及对象联动 | AI生成完整规则供确认；不要求用户从空表逐行建所有规则 |
| StudySchemaEditor | 研究流程图、节点/边、影响预览与提交 | 图应从研究定义派生；布局可调，不让拖图悄悄改医学事实 |
| StructuredTableDesigner | 结构表/SOA单元格、合并、脚注、访视元数据 | 保留语义表对象；AI建表用户微调；结构变更须跨章影响检测 |
| TableCellRichEditor | Tiptap格式、样式、引用和快捷键 | 新版收敛可控样式；Word输出由模板而非任意CSS保证 |
| CrossReferenceMark / editorSourceMapping | 引用目标与语义源block绑定 | 保留稳定定位，不能丢source ID后再按文本猜位置 |
| WordEditingShortcuts | 熟悉的编辑快捷键/历史 | 保留中文输入、undo/redo和选区测试，不追求复刻整个Word |
| InstrumentAppendixPreview | 量表附录逐页预览 | 真图像可查；版权/版本/语言/使用许可不能由“有图片”推定完成 |
| MedicalWritingPreviewPanel | 意图区分快速估算/Word已核验/过期 | 实际组件先看page_count_basis再看stale，合法过期状态仍绿色并声称最终版式依据；需修复优先级与组合测试，不能只测标签字典 |
| durableJobState.mjs / useDurableMwJob | 前者及shared poller被生产调用；同名hook导出目前零生产调用方 | hook中的闭包反例是潜在复用风险，不是现行用户故障。真实App内联修订回调需修复章节切换期间的代际守卫并测试实际接线 |
| protocol-workbench/protocolWorkspaceApi.mjs | v3 URL/HTTP/error transport合同 | 只有客户端且零UI调用方，不能算新前端已构建 |

## 按严重性排序的问题与方案

| 优先级 | 问题/反例 | 修复与验收 |
|---|---|---|
| P0 产品阻断 | SQLite已通过1R.1独立验收，但无main挂载、无新UI；从建项到导出尚未闭环 | 接续1R.2/API→2R执行→3R内容→6R用户流程；任一fake不得冒充live |
| 已修复：1R.1存储缺口 | 初版事务/异库/批次漏洞、约束克隆、前向迁移缓存错误及部分claim均被独立反例发现并关闭；最终140聚焦、1372+101全套通过 | 独立验证者READY且四文件hash冻结；只关闭Task1R.1。1R.2真实allowlist接线、1R.3错误分类/集成/备份仍未做 |
| P0 恢复/数据 | Plan1R.4字面删除与旧负向测试/unknown防重复冲突 | 用户已批准兼容式精简；先真实存储与kill/replay证据，再减实现 |
| P1 旧生成崩溃窗口 | full_draft.run_job在模型返回后才保存chunk；durable_store恢复过期running为queued；缺chunk时再次submit_internal，而runner生成新run_id | 真实服务+临时SQLite+假模型复现同job恢复后调用2次；1R.4/2R保留发送前reservation与unknown对账，不以文件缺失推断没执行；已持久chunk可复用的旧测试仍保留 |
| P0 准入 | “106叶都存在”不代表106叶内容完整，模板当前仅保护未落registry | 每叶正文合同+正反例+跨章QC；缺核心参数不得虚构补齐 |
| P1 QC正确性 | 旧content_quality.py对“未提供”后的任意短文本匹配，完整流程条件句也被标为待写占位并阻断；全文runner主要检查字数、标记、章节ID与来源ID存在性 | 已用实际detector复现误报并保留真正待确认的对照。3R/7R按事实义务、对象关系和上下文检查，同时覆盖漏报/误报；合法模板措辞不应靠反复人工豁免过门 |
| P1 明确失败后的用户出路 | full_draft明确failed后，相同descriptor digest的生成请求复用原失败job，start路由不唤醒终态，全文面板没有retry按钮。通用显式retry API仍存在，故不是整个系统永久死锁 | 3R/7R修QC误报；5R/6R区分需修输入与可同模型纠错的明确失败，提供有界修复/重试选项。不得自动重派所有failed，更不能把unknown当失败；保持任务血统及原负向fixture |
| P1 启动隔离 | 旧main import含全局repository与artifact mkdir、startup recovery | 新composition不得增加副作用；真实测试用隔离tmp运行边界，不能直接import生产main后称只读 |
| P1 入口依赖闭合 | 按冻结38包hash锁重建成功，但真实main导入仍缺xlrd；183模块静态依赖闭包还定位到写作OCR一致性模块顶层fitz | 旧H4/H6的import probe只导入验证器自身，不能外推main可启动；新增产品入口验证。PyMuPDF仅旧链测试的使用边界已向用户给出选项，未静默加入产品锁 |
| P1 全稿采纳 | full_draft.py:164按所有正文段落计算hash，:710只比较首段；未改正文也误报过期 | 已使用实际服务+已有fake runner复现；v3采用同一语义块集合计算/校验precondition，不能靠跳过hash解决 |
| P1 部分采纳回执缺失 | full_draft.py:692逐章保存，第二章过期时第一章已落稿；main.py:7824直接把异常转409。App:10457确实提前说明逐章写入/冲突停止，但catch只报采纳失败，未列已写章节或刷新部分结果 | 已复现saved_before_error=[sec_1]；v3整稿采用一个SemanticDocumentRevision+事务，冲突则全不落地；逐章采用则明确返回保存结果和恢复状态，不把部分成功表现为零改动 |
| 撤回现行缺陷判定：跨项目采纳回写 | 隔离回调探针未包含父级接线；App:15906使用WritingPage key={activeProjectId}，切项目重建实例，旧setter不能修改B实例 | 原探针保留为简化模型反例，不再当生产可达缺陷。6R仍测试真实卸载/切换，但不为不可达路径重复施工 |
| P1 同实例章节切换守卫 | App:9552–9582等内联修订回调在响应时捕获screenAtStart，后续poll与旧props比较。若进入poll后再切章节，检查仍可能通过；activeThread本身按当前章节过滤 | 应与当前revisionScreenGenRef比较并测试实际组件中途切章。范围是状态/进度/取消体验；不声称候选正文已跨章采用。未接线hook的同类缺陷仅是复用风险 |
| P1 非终态失联清locator | App:10443–10447和导出catch会删已保存locator；shared poller会吞单次网络错误继续，真实catch可由轮询预算耗尽或后续全文result获取失败触发 | 修正早先“单次状态查询网络失败即删”表述；同输入digest重按生成可复用原任务，并非永久丢结果。失联保留locator、对账后清理；不把网络问题当安全重生成依据 |
| P1 身份接线未证 | principal ACL、签名、回退模块有离线合同，但main未接入这些adapter；v3 router直接转发body.actor_type/actor_id，暂无服务器principal绑定 | 本轮24个纯合同/临时库测试通过，不代表HTTP已鉴权。1R.5/5R核实真实确认身份和跨项目授权；单用户可复用本地会话，不新建多租户平台；未经可信确认不得标高风险已人审 |
| P1 迁移 | live共享source registry能transaction替换元数据 | 真实reader用稳定快照/hash/项目/locator，不靠追加偏移；不重写历史 |
| P1 模型 | 动态路由、缺失effective model、共享监查配置可能污染写作身份 | 模型缺失/不一致即拒绝；写作profile独立；凭证仅内存 |
| P1 用户负担 | App.jsx:8655/8702/10207等及intake/editor大量10字门 | 原因AI预填+可编辑，取消字数门；保留真正高风险确认与审计 |
| P1 视觉 | 写作专用CSS中有10/11px声明，不仅是全局文件统计 | 6R实测computed字号与缩放；body≥14px/UI≥12px；目前不声称完成视觉验收 |
| P1 过期核验误导 | MedicalWritingPreviewPanel.jsx:28–49的tone/isVerified仅按Word页数来源优先判断；后端合同合法的stale+历史Word页数会同时显示过期标题、绿色verified类及“可作为最终版式依据” | actual React SSR+后端Pydantic验证已复现；6R过期优先，成功须当前状态+快照一致；7R导出另有后端硬门。现有2个标签helper测试不能证明组件组合正确；尚未做浏览器视觉检查 |
| P1 依据 | eCTD强制性/PDF-A唯一性/E6R3章节引用等计划依据不准确 | 已在附加计划逐条纠正并链接一手依据；保留用户要求的eCTD readiness |
| P1 导出 | 活跃WAL裸文件复制、浏览器分页、DOCX生成都不足以证明恢复/格式 | backup API+恢复后业务hash；原生Word域更新与逐页QC；不把文档就绪当完成申报sequence |
| P1 原生回执接线 | 旧回执合同只含一个docx_sha256及外部自报Word/视觉状态；API会重算上传PDF页hash，但这不证明PDF由指定DOCX经Word更新产生。Phase0新合同已区分input/saved/PDF与producer身份，尚未接入产品 | 7R.4继承现有完整PoC合同而非另造弱回执；保存后新DOCX是独立不可变制品，最终交付与该hash一致；本轮未运行Word，不声称已证明真实伪造或渲染失败 |
| P2 可维护 | App/main大文件、业务服务与UI门重复、工作台客户端孤立 | 按新链业务边界渐进替换，禁止大爆炸重写或牵连监查 |
| P2 过度建设 | 为每个章节上一个自主agent、过早加通用graph框架/多数据库/向量平台 | 保留typed facade+SQLite，专用角色按职责，不按章节数；优先交付完整正文与恢复 |

P0/P1是本产品交付阻断/风险优先级，不宣称已造成真实临床损害。

## 医学写作合同：必须从“字段齐”升级为“正文可用”

下面是实现设计建议，逐叶最终规则仍由TP-MA-07 v2、适用SOP及项目事实落定：

| 内容模块 | AI应交付的完整内容 | QC控制点 |
|---|---|---|
| 前置件/摘要/缩略语 | 编号/版本/日期、同一研究摘要、首次术语与缩写 | 封面/页眉/摘要/正文一致；无旧药物项目残留 |
| 背景/获益风险 | 疾病负担、现有治疗不足、机制/前期证据、研究依据与风险控制 | 每个实质主张有可追溯证据；公司措辞不能代替当前IB事实 |
| 目的/estimand/终点 | 人群、治疗条件、变量、伴发事件策略、汇总量，终点时间/工具/算法 | 目的-设计-数据收集-分析相互支持；ICE不同于缺失数据，不能全研究套一种策略 |
| 设计/对照/剂量 | 研究臂、分配比、盲法、时长、对照/剂量论证 | 与给药、SOA、样本量、补救规则一致；高风险逐卡确认 |
| 入排/招募保留 | 每条人群标准及可执行评估方法，合理招募/退出/保留安排 | 重复/矛盾阈值、时间窗、筛选时点、不可执行检测；避免无依据沿用竞品 |
| 干预/合并/补救 | 制剂/给药、暂停重启/永久停药、合并用药和救援标准 | 停药不等于退出随访；补救触发与estimand/数据收集联动 |
| SOA/操作流程 | 每项检查与访视窗口、条件检查/脚注、早退/计划外访视 | 摘要/流程图/正文/SOA一致，日/周/基线锚点统一；表不能只是一张图片 |
| 疗效/工具 | 操作、评分、盲态、中心评估/培训（适用时） | 量表版本/许可/语言、回顾期、定义与终点算法匹配 |
| 安全性 | AE/SAE收集和随访、适用风险、报告/联系与紧急处理 | 与IB/PV和当地要求一致；时限/责任不可模型臆造；PV专业确认 |
| 统计 | 假设、样本量参数与来源、分析集/方法、缺失、敏感性、多重性/期中 | 可复算；参数来源不是模型置信度；NI界值/alpha等统计专业确认 |
| 质量/数据 | CtQ、主要风险及控制、数据治理、源数据/系统/记录安排 | 与真实运营能力匹配，不写不存在的委员会或未部署系统 |
| 伦理/管理 | 知情同意、隐私、补偿保险、发表共享、职责等适用正文 | 地区/人群适用性；不能自动豁免真正必需内容 |
| 参考文献/附录 | 一致引用、可核实原文、量表与操作附录 | 正文编号/表图题注/书签有效；无待确认与生成过程话术 |

研究目标、estimand、设计和分析需对齐的基础见[ICH E9(R1)](https://database.ich.org/sites/default/files/E9-R1_Step4_Guideline_2019_1203.pdf)；风险比例、关键质量因素和适当患者参与见[ICH E8(R1)](https://database.ich.org/sites/default/files/E8-R1_Guideline_Step4_2022_0204%20%281%29.pdf)。不是每个研究均需同样技术方案。

## 推荐的用户体验

主页面只回答三件事：“AI已为我完成什么”“现在需要我决定什么”“稿件能否导出”。工程trace、provider、重试次数、hash不进入主阅读面；保留可展开的问题定位与审计证据。

- 建项：优先拖入已有摘要/IB/资料；AI生成研究概况，用户补少量无法推断的事实。来源冲突展示对比选项，不能要求用户懂prompt。
- 推荐：卡片包含推荐方案、短理由、关键依据、影响与1–2个真正不同备选。预选但未确认；八类高风险红tag逐卡确认，低风险可整包。
- 正文：先呈现完整可读稿而非“待生成”空章节；未确认事实在侧栏显式阻断最终稿，不把占位符藏起来后冒充成稿。
- 修改：用户可写一句要求，也可点“采用推荐”；先预览实质变化及受影响章节，保留已锁定无关内容。保存成功/失败明确，刷新不丢稿。
- 长任务：以业务阶段和已完成产物说明进展；关闭页面能恢复；失联先查结果，用户不需要知道unknown_outcome这个术语。
- 导出：一键受控格式检查/原生Word核验；不合格时列具体页面/段落及修复选项，而不是下载一个文件就亮绿灯。

推荐新增/强化：研究决定变更影响预览、资料到期/IB版本提醒（不自行创建定时自动化）、原文证据就地查看、样本量可复算说明、锁定/撤销、可恢复导出。

建议退出主流程：重复维护资料准入状态、任意字数理由、各节点手动重派/反复确认、技术模型参数面板、从空白逐行搭SOA。不是删除历史记录或把风险确认一键跳过。

技术路线：保留React/Tiptap受控编辑、Python领域服务、SQLite与typed facade；不引入Word级网页排版引擎、不为单用户引入分布式消息系统、不按“多Agent”名义增加没有职责价值的模型轮次。先让一套真实资料完成全流程，再讨论可选LangGraph对照和更大平台。

## 已做测试及未完成验收

| 检查 | 结果 | 说明 |
|---|---|---|
| R.1/R.2/R.3聚焦 |183 passed|主执行与独立reviewer均复现|
| tests/protocol_v3 |1240 passed +101 subtests；2 warnings|无失败/跳过；非全仓/产品E2E|
| 1R.1候选完整回归 |1344 passed +101 subtests；2 warnings|主执行复现22.73s，含74双后端+30产品新增用例；仍不能通过下一行验收探针|
| 1R.1初版独立验收探针 |历史5 failed，已被repair_01修复|acceptance_probes_red_v3.xml保留；不是当前仍5失败|
| 1R.1 repair_01主执行复验 |1361 passed +101 subtests；原5项+2项投影原子性通过|完整套件19.40s，7探针0.47s；新CTAS约束探针1 failed（0.44s），schema_constraints_red.xml；仍未验收|
| 1R.1执行过程审计 |原followup包FAIL，历史保留|续作声明格式与原/续作output receipt绑定两项失败，不能靠修改已发送prompt修复历史；新生成单worker执行包承担真实剩余约束修复并重新验收，不改全局guard|
| 1R.1 repair_02主执行复验 |历史134 focused passed；1366 passed +101 subtests|8个独立探针包含在134中，不重复相加；0.96s/14.36s；该执行audit通过，但后续独立review以迁移/claim反例判NOT_READY，保留历史|
| 1R.1 repair_03终验 |140 focused passed；1372 passed +101 subtests；独立READY|主执行先红（冷/热缓存+增表/增列及claim：4fail/1pass），再最小修复并补迁移失败恢复控制；1.10s/18.70s；独立review复现全套且另写2项闭合探针，主执行复跑2PASS0.28s。只接受冻结Task1R.1；旧诊断断言与报告原样保留|
| Task2.1 |75 passed；七文件hash不变|保留原离线合同证据|
| 前端inventory |3 Vitest files/18 tests；46 Node files/50 TAP tests通过|Node内部assert数不与TAP数相加冒充用例；不含受保护live浏览器QC|
| 独立review |首轮NOT_READY；fresh H-R已接受|GLM-5.3:max实际42工具调用已另核回执，183/1240/75独立复现；无产品验收|
| 主应用运行目录隔离 |入口依赖尚未闭合|原解释器cryptography缺失；新hash锁环境已建成，后续缺xlrd/fitz，不能把依赖错误算产品逻辑测试通过|
| 新锁环境重建 |38包hash安装成功|新建runs/mw_protocol_v3_1r_integration_20260905/venv；不改变全局/live；入口后续失败为xlrd缺失|
| 旧全文采纳反例 |两类问题均复现|runs/mw_protocol_v3_1r_integration_20260905/reproduce_legacy_full_draft.py；实际服务方法+测试repo/fake模型，非真实项目/模型E2E|
| 旧全文UI隔离回调反例 |机制可复现；生产可达性已修正|reproduce_legacy_full_draft_ui.mjs缺父级key重建和真实poller；跨项目回写判定撤回，网络触发细化为耗尽/结果拉取；未接线hook不算现行用户故障|
| 身份/签名/回退合同 |24 passed|新锁环境，纯函数/测试临时SQLite；acl_signature_rollback.xml；不是真实签名服务或主API鉴权证明|
| 旧任务存储聚焦 |19 passed|去重、claim、heartbeat、CAS complete/fail四类；durable_store_focused.xml；不外推外部副作用exactly-once|
| 旧StudyDefinition绑定合同聚焦 |7 passed，4 deselected|study_binding_contracts.xml，0.51s；明确只运行前七项纯合同/假文档场景，未跑余下四项存储重绑定；证明状态规则，不证明正文医学一致性|
| 导出任务/Word回执离线合同 |15 passed|export_receipt_contracts.xml，1.48s；任务使用fake DOCX字节、回执为合成数据，只证明幂等/持久/绑定/拒绝篡改，不是Word已运行或15个格式验收|
| Phase0完整native receipt合同 |55 passed|native_receipt_schema_contracts.xml，0.04s；仅离线validator，未重跑Word producer|
| 过期预览实际组件 |合法stale payload仍渲染verified/最终依据文案|reproduce_stale_preview_component.mjs：真实Pydantic校验+esbuild/React SSR，无服务/浏览器/Word；确定组件逻辑缺陷，不声称真实项目已触发|
| QC误拦截反例 |已复现|reproduce_legacy_quality_false_positive.py：完整流程条件句与真实草稿占位均被actual detector阻断；非临床建议|
| 旧QC检测器既有合同 |6 passed|quality_detector_focused.xml；合成文档，不运行真实Word fixture；原测试通过不消除新增误报反例|
| 旧全稿生成崩溃窗口 |同job恢复后假模型调用2次|reproduce_legacy_full_draft_crash_window.py；故障注入+时钟前移，无真实kill/外部调用；不宣称v3已有同样缺陷|
| native Word/实际浏览器/产品模型/cutover |未运行|仍是后续明确gate，不给PASS|

本次采用ponytail减少不必要新依赖；临床方案审阅技能只用于章节/证据控制点设计，没有修改任何实际方案。当前执行修订与任务状态分别见 plans/mw_protocol_v3_review_amendment_20260905.md、plans/mw_protocol_v3_execution_tracking_20260905.md。所有产品接受状态均以最新gate记录为准。

当前安全续作点：Task1R.2。全仓/实际main回归需要先确定旧PDF依赖的测试隔离路线，原生问题卡已发出；尚未擅自把PyMuPDF加入新版产品锁，也未提前改造旧PDF模块。最新存储gate为 reviews/codex_mw_protocol_v3_1r1_storage_gate_20260905.md。原生App goal仍为旧目标/paused，工具没有改目标或恢复接口；当前工程目标已写入Plan和tracking，不伪称App状态已改变。
