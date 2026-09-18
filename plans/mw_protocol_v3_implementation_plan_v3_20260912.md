# Protocol v3 Implementation Plan v3

2026-09-12审阅修订；2026-09-13状态校正：用户已激活新版Goal，按本计划连续实施。当前精确进度以Trellis为准。

用户已选择：先修依赖与条件规则，尽早交付Ⅱ/Ⅲ期完整可用路径，再补齐全部场景。此选择明确替代旧“所有Phase模块先分别完成才做完整路径”的施工顺序；不降低内容、科学性、Word或最终全范围验收。

## 1. 执行权威与入口

唯一实施区：/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313。

本文件+plans/mw_protocol_v3_design_v1.4_20260912.md是本轮显式修订。未修改的产品义务继承20260905附加修订、只读Plan v2/design v1.3和冻结20260809计划；不按旧状态或旧路由续作。最新全局AGENTS管理方法学，Trellis是任务状态唯一看板，历史execution_tracking只作索引。

开始先读最新全局AGENTS、最新用户消息、当前Trellis checkpoint与本轮review，再核对Git及本任务源文件。3R.3结构验收保留，3R.4未验收；不得回到1R.2、重新初始化Trellis、重跑旧下载/OCR/翻译/五失败项或重复1R.6探针。

历史2026-09-12审阅轮范围为review/诊断/文档修订；其后用户已激活新版Goal，现授权按以下顺序实施。不得把历史暂停描述当作新的施工停点。原生Goal文字和计划分别管理，不直接改Codex内部数据库。

## 2. 当前状态与不重做项

| 项目 | 当前可承认范围 | 后续处理 |
|---|---|---|
| Phase R、1R、2R.1 | 原验收记录的离线/集成范围保留；本轮1860项Protocol v3回归通过 | 有当前反例才开对应修复，不重走全阶段 |
| 1R.5 | USER_EXCLUDED / 未执行 | 不新建安全专项，不伪报PASS |
| 1R.6产品连通性 | 既有单次真实探针成功记录 | 先查logical key；相同探针不得重复 |
| 3R.1/3R.2 | 源结构与schema成果保留；本轮从原DOCX复提取完全一致 | 输入类型/适用性属于本轮3R.4补齐 |
| 3R.3 | 111载体、111skills、558fixtures结构覆盖；当前组装等于历史已审制品 | 只对明确反例涉及的合同做版本化修订，不将旧结构验收说成医学通过 |
| 3R.4 | 首交付图未完成独立验收；本轮发现标签传播和业务采用证据缺口 | 按A–D补齐，保留原交付与失败日志 |
| 3R.5以后 | 规划/部分既有基础；未形成当前产品完整路径 | 按下述串行依赖与路径里程碑实施 |
| 老链全仓 | 历史维护套件7420通过、167失败、18错误、1跳过，另三历史工具未执行；不是当前重新实测 | 用适用范围和新增原因决定重跑，不将1860误称全仓通过 |

## 3. Task 3R.4拆分：先保证事实、条件、影响真实可用

### 3R.4A — 类型保真与canonical事实解析

Files：修改services/api/app/protocol_workflow/registries/chapters.py的ChapterSkillInput/ContentFact接线；packages/contracts/workbench_contracts/protocol_v3.py仅做必要版本化合同；新建registries/fact_bindings.py和config/medical_writing/protocol_v3/templates/tp_ma_07_v2/fact_bindings.json（若现有等价解析器可复用则合并，不重复创建）。测试tests/protocol_v3/test_chapter_fact_binding.py。

步骤：

1. 从本轮conditional_probe.json复现bool/number/object无法进入输入的问题，写实际调用边界测试。
2. 用同一StudyDefinition版本解析facts并保留JsonValue；原字符串输入仅按已声明类型转换，文字“false”不全局猜成布尔；历史事件不改写。区别false、0、null/缺失和不适用。
3. 为724路径逐项登记解析方式：canonical直接读取、确定性派生/别名、明确尚不支持。先打通身份、终点、estimand/ICE、人群、剂量、SOA和样本量链，再覆盖其他执行章节；不能仅写“统一归属”说明却无读取者。
4. skill输出不得替换已确认facts；绑定输入study revision和证据引用。多段正文和结构化表格保留完整值；ContentCell显示文字与typed事实绑定分开，不能盲目扩大所有显示字段类型。

完成证据：从真实StudyDefinition→ChapterSkillInput→序列化/重开，false/0/列表/对象不变；别名不产生第二可编辑事实；改某值准确映射受影响路径；旧合同回归通过。尚不支持字段有明确清单，不能进入已支持完整路径。

### 3R.4B — 条件规则可执行及合同纠偏

Files：在registries/applicability.py或已有等价模块实现小型谓词；必要合同版本同3R.4A串行修改；chapter_contracts中涉及条件的文件逐项改；tests/protocol_v3/test_chapter_applicability.py；测试fixture增量保留旧版本证据。

步骤：

1. 对49条条件和本轮14条重复无条件required逐条对账，输出“原文来源、触发、true/false/unknown、facts/claims/evidence/objects处置”矩阵，存入本任务新run的applicability_obligation_matrix.json；14项逐条裁定而非统一删除。
2. 保留人类说明，加入最小类型化predicate；复用ApplicabilitySnapshot。不运行自然语言eval，不用模型一句话决定无条件删除义务。
3. 期中分析false时保留真实“不计划开展”的处置与依据，逐项处理全部专属详细事实（含canonical_reference）、claims、来源和表格，不能只释放10个交集字段；true时完整要求；unknown时等待事实，不自动套模板。false却残留计划期中参数时须处理矛盾，不静默采入正文。
4. 同步检查随机/盲法、IRC、PK/PD/E-R、未来样本、外部实验室/销毁方、妊娠风险、补救治疗、ECOG/NYHA等条件；“确实不适用”与“适用但材料缺失”分开。
5. 修正期中合同中不存在的v2_n_13_x目标；引用真实载体或记录需要源核实，不能把带文字说明的虚拟ID当已解析。
6. 合同/skill/fixture改变后重新全量组装及lint，保存新hash和源版本；历史all8制品不改写，不强求新版本与旧版本字节相等。

完成证据：true/false/unknown及互相冲突事实三类用例；每种激活义务都在实际checker中执行；无期中/无IRC/无中心实验室实例不被迫填假信息；原负向功能义务仍有等价或更准确测试。预期变更须记录用户授权的旧断言升版依据，不能静默改expected凑绿。

### 3R.4C — 带事实标签的影响计划

Files：修改registries/dependency_graph.py；tests/protocol_v3/test_dependency_graph.py增量行为用例；如需JSON/Mermaid导出只新增scripts/qc/protocol_v3/render_chapter_dependency_graph.py。

步骤：

1. 采用本轮x/y桥接反例：A{x}、B{x,y}、C{y}，只变x不能仅因一致性连接重开C。
2. 分开直接事实使用、明确调度依赖、语义一致性检查；传播保留具体changed paths和via_paths。明确派生规则确实改变y时才按新变化传播。unknown条件关系保留为候选检查/待决，不直接激活确认失效，也不删除关系。
3. 计算候选修复范围与实际需要重新确认的范围，不截断真实扇出；摘要/索引更新不得反向重开未变医学决定。
4. 图有未知目标/缺owner时仍可查看诊断，但不能生成可执行写作计划；保留原诊断测试，增加消费者拒绝测试。hard-cycle仍拒绝，reciprocal一致性边不误判环。
5. 保留impact_sha256兼容接口但明确它是投影hash，不能作项目事实采用幂等键。

完成证据：桥接反例、明确派生变更、完整扇出、无关章节稳定、未知依赖不可执行、图投影与当前组装registry绑定。用独立期望集合验证，禁止只复制被测BFS作为reference oracle。

### 3R.4D — 接入既有采用事务并独立验收

Files：按实际接线修改canonical/document.py、canonical/study_definition.py、application/service.py、graph/runtime.py中的最小消费者；复用现有SQLite/UoW/reservation/ledger，不建立新平台。新增tests/protocol_v3/integration/test_fact_impact_adoption.py。

步骤：将typed事实变化、适用性和impact接入一次采用；base revision、operation key和actual fact changes绑定同一事务；旧结果对账后恢复。纯函数调用两次相等不再作为业务采用证明。

完成证据：tmp SQLite中同key重复提交仅一份有效文档版本/事件效果；相同fact path不同已确认revision能完成两次不同操作；并发CAS一胜一待处理；提交结果未知先查询不重复模型调用；重开后未变决定保留。独立review冻结制品后，由Codex登记3R.4验收，不沿用旧配额失败报告当通过。

精确验证回放边界：先采用A，再用另一操作修改其相关输入，最后精确重放A仍返回原回执、零新效果；当前读取须把受影响确认标为过期，不能把旧回执显示成当前批准。新operation提交过期卡片或旧revision要拒绝；不要把“检查当前确认有效性”塞回历史ledger而改变旧结果。

保留现有replay_or_apply响应语义：返回当前合法后继definition不变和原effective_decision/效果记录，不用历史definition覆盖当前revision，也不要求API逐字复现旧HTTP响应。上述“原回执”不代表倒退当前研究状态。

相邻真实错误分类一并在接线前定向修复：application/service.py的AggregateNotFoundError目前被映射为可重试CAS冲突/HTTP409。允许项目下不存在的study应返回明确未找到，真正CAS竞争仍409；已配置错误的repository不提示重新确认推荐。复用现有中文错误包与稳定错误定义，新增实际API边界用例，不建设安全专项。

2026-09-13真实接口预检补充：`runs/mw_protocol_v3_3r4d_preflight_20260913/`保留三组独立SQLite与响应。不存在study返回可重试409；创建及采用成功后决策图仍200/空列表；新decision和正确base snapshot也无法修改既有已确认剂量。这些属于本项原目标的具体缺口，不是额外平台任务。实施细化：

1. 在既有事务上提供明确的事实修订语义，验证当前revision、原生类型和新决策输入，保存新版本及旧版本/事件；旧采用禁止静默覆盖的负例保留。需要调整API请求或合同则显式版本化，不改变旧历史hash。不能用新增另一fact path冒充修改同一已确认事实的验收。
2. 补齐真实当前决策投影及实际事实依赖绑定，复用现有事件/存储；GET不得造成新采用或新的模型调用。新增调用→查询的内容断言，至少真实剂量决策可见，不能只断言HTTP200。输入绑定缺失的历史决定与当前已证实有效的决定分开，不全局重开全部确认。
3. 以“采用A→显式修订相关事实B→精确回放A→当前查询”验证原回执零新效果、当前后继revision不变、相关确认过期且无关确认保持。重复/并发/重启测试必须走真实SQLite事务和实际消费者。
4. 必要Files补充：`errors.py`、`api/router.py`及当前API请求/响应模型、`ports/repositories.py`/`storage/sqlite.py`只在上述接线确有需要时修改。优先稳定中文包与现有存储；不要引入新数据库、通用审批系统或新安全专项。

2026-09-13接线顺序细化（保留义务，不以未实现冒充验收）：现有ApplicationService仅有StudyDefinition采用，SemanticDocumentReducer是尚无整稿应用消费者的纯内核，且正确拒绝把旧文档直接绑定新研究事实。为避免在编辑器之前另造文档保存链，3R.4D先在现有一次事务完成研究事实版本、显式输入绑定、条件快照、带标签影响范围和事件效果，并以真实SQLite确认同key零新效果、并发CAS、恢复与相关/无关确认状态。上述“同key仅一份有效文档版本”的整稿应用验收移至V1的6R/7R集成任务，与编辑保存/整稿采用同时实现；它仍是V1完成的必要证据，不得因3R.4工程子项通过而标记已验。旧文档保留原事实绑定并显示需要同步，不能只换header hash。独立3R.4 review须核对这一分工和未实现边界。

## 4. 路径前置：只补实际需要的检查，保留后续全范围

### 3R.5A — R03与Word引用最小闭合

继承Task3R.5，完整保存R03的68源内容行并拆原子义务，登记deterministic/agent4/human及章节。Files按原Plan：scripts/qc/protocol_v3/extract_r03_criteria.py、config/medical_writing/protocol_v3/qc/r03_criteria.json、tests/protocol_v3/test_r03_criteria_registry.py。

本阶段先实现路径所需检查及明确未实现清单：版本/编号/日期、引用目标解析、实际缩略语与文献集合、内容义务覆盖、核心设计链一致性。Word style ID/书签源绑定按当前模板全量对账；“有1个required_cross_reference”不代表所有文字引用。语义类仍由Agent④/人工评估，不把年份或非空字符串冒充医学适用性。

2026-09-13源预检落实：R03使用authority_amendment指定的修订版，68源内容行之外保留表头内招募义务，原始条款号/拼写与规范化解释分开；见reviews/mw_protocol_v3_3r5a_source_preflight_20260913.md。Word当前源13种required styles及172个required bookmarks均找到，不以不存在的缺失立项。实际问题是自动_Toc名称不适合作稳定业务身份、全书跨引用声明不足，以及旧PoC selector只返回成功交集/最多32项。3R.5A建立源对象清单与语义目标映射；V1.5产品化时改为逐一核对实际生成文档的应有业务书签、内部引用和全部相关story中的字段，丢失/错误项目显式失败，不能从分母中滤掉。没有引用的合法文档不硬造引用。已有P0回执保持历史技术证明，不冒称新版模板或当前Word版本已验收；版本变化仅作当前制品的针对性能力验证。

### 3R.6 — Ⅰ期问题卡

准备候选源、差异、推荐理由；不能用Ⅲ期模板默认填Ⅰ期。用户决定只影响Ⅰ期支持。保存无损锚点并原生提问；按用户当时指令暂停需该决定的工作。独立的Ⅱ/Ⅲ期路径不因Ⅰ期未决被判不合格或删除分母。

### 3R.7A — 路径术语与文本质量

按原路径实现terminology/library.py与terminology.json；新正文首选试验参与者，法规/引用标题保留原文；缩略语从实际使用生成。占位检测区分正文、模板说明、合法否定句、签名控件；重放“未提供书面知情同意者不进入筛选”不能被误判缺失材料。

## 5. V1完整路径里程碑（交付路径，不是额外平台）

任务编号仍映射4R/5R/6R/7R，Trellis用子项标识vpath，避免另一套编号独立管理。只针对一个来源充分的标准Ⅱ/Ⅲ期实例先串通全部适用载体；不用三章demo、占位正文或fake模型冒充完成。

| 顺序 | 原任务映射 / 主要文件 | 工作内容 | 可观察完成证据 |
|---|---|---|---|
| V1.1 | 4R.0/4R.1/4R.4/4R.6；新增knowledge_base、资料准入相应原计划模块 | 首选已有完整DOCX/已准入材料，减少不必要下载/OCR；证据单元有真实定位与版本；AI整理研究事实和少数缺口 | 实际资料进入产品，出处可打开，冲突与缺失不编造；fixture与真实资料分开 |
| V1.2 | 5R.1–5R.5；recommendations原计划模块与API | 完整设计推荐、八类高风险逐卡、低风险合并；同一事实版本派生摘要/估计目标/适用性 | 浏览器真实采用写入SQLite；修改剂量/终点后仅重开真实受影响确认 |
| V1.3 | 6R.2/6R.3；graph/runtime、chapter executor、全文reducer | 全部适用章节一次生成；临床、统计、PV和SOA由同一研究事实驱动；先形成完整候选再统一采用 | 每个适用载体有实质正文/对象/出处；整稿采用单版本，刷新/重开不丢、不重复外部调用 |
| V1.4 | 6R.1/6R.4–6R.6；frontend/src/features/medical-writing/protocol-workbench、App.jsx最小路由桥 | 准备→确认建议→阅读修改→导出四态界面；受控编辑/选区/表格；旧链逐步抽离 | 真浏览器、IME、快捷键、切章、保存失败、超时恢复、20/5和字号computed style证据 |
| V1.5 | 7R.1–7R.4/7R.6；qc、word、export产品模块 | 核心医学/统计review与必要修复；复用Phase0 Word producer产品化；eCTD文档检查 | 实际Word打开/更新域/保存/导出PDF，当前制品绑定；页面/表头/SOA/引用实际检查；剩余human项明确 |

V1.3必须补真实模型接线：当前graph/runtime仍构造deterministic-offline执行合同，GLM transport目前将artifact ref/hash/snippet拼成用户消息，连通性成功不证明已装配章节任务。以既有skill为依据编译角色说明、完整适用义务、typed研究事实、可解析的来源材料和实际输出schema；不要只把本地路径或schema ref发给远端模型。现有snippet每项8192字符上限不能被当作全文读取完成，按完整证据单元组装并明确覆盖，不静默截断。先用注入transport断言实际请求包含必要材料及输出经真实validator解析、失败不采用，再按既有logical key和真实调用授权运行完整路径；不为此重复首次探针。

实际产物接受链明确为：取得sink字节并核对回执hash→JSON/ChapterSkillOutput解析→基于相同study/template/rules的check_applicable_output→有序SemanticBlock候选装配→全适用载体汇合/必要QC→一次整稿采用。新增反例须覆盖非JSON但transport成功、schema引用相同但内容错误、缺失来源或相关输入已改、段落/表格顺序丢失，以及重复整稿采用零新文档效果；这些是应用消费者检查，不用通用transport伪造医学通过。模型/来源暂时失败保留已有完整候选和logical key；不以读回receipt中的schema名称替代实际解析，也不将离线graph的300秒示例直接套成真实产品长任务限时。

V1路径材料优先从已经齐备的Ⅱ/Ⅲ期项目中选，不以简单程度掩盖缺失；选择依据记录材料完整度和设计适用性。无期中路径至少有可执行合同/组件用例；fixture反例与真实项目医学验收分别记录。点击日志、适用卡清单、必填项、computed style、浏览器操作与当前制品版本存入该V1任务run的user_path_acceptance.json及关联证据；全部八类适用的预算场景另测，不能用删掉非劣效/期中卡凑绿。

不能用未完成V1.4或V1.5的后端接口冒称“完整可用”。V1输出只有在其科学、正文和Word范围均通过时才能称该实例可用；生产切换仍另需授权。资料不足不能伪造完整初稿，先给用户最少、具体且有推荐的科学问题。

前端review发现的实际旧链缺陷按触达程度处理：迁移路径必经者先最小修复；仅存在旧组件且将被新链替代者记录并在接线时带回归，不先重写整段16000行App。不要为无调用方hook投入优先施工。

## 6. V2范围扩充与原计划义务清单

| 原Phase/特性 | V1后继续落实 | 完成边界 |
|---|---|---|
| 4R.0全18份公司corpus | 分批只读准入、语义映射、匹配程度/版本适用性 | 公司惯例不能覆盖当前项目事实；不是18文件名存在即通过 |
| 4R.2/3/5/7 | 发现/下载完整性、OCR翻译、三分母、零结果根因、E1时间盒和监管时效 | 相同logical work key不重跑；旧失败状态不复活；72h无进展问题卡按计划处理 |
| 5R完整推荐 | 多设计、多适用性、八类确认/内容绑定、临床统计协作 | 标准推荐不套上个项目剂量/界值 |
| 6R完整编辑 | 选区7动作、候选diff、表格/引用保护、锁定语义、局部重跑 | 实际接线验证A→B→A、切章、刷新、取消/重试，不靠helper假装UI测试 |
| 7R全部QC与回流 | R03全义务、术语文献闭合、Word外部改动回流、四层交付证据 | 无法定位的Word改动保留原稿/差异，不静默全覆盖；人工项不冒自动通过 |
| 8R shadow/E2E/cutover | 最新live源与实际snapshot parity、回滚演练、多角色多场景连续验收 | 保护监查；Ⅰ期未决保持标明；真实项目切换由用户授权 |
| 后置能力 | Synopsis、修订说明/版本diff、审稿回复、竞品对比 | 本轮不提前实现；不以占位API冒称可用 |

不重启LangGraph/MAF评比，不增加PostgreSQL/工作流平台，不做浏览器Word排版引擎。所有原计划未被明确裁定删除的实质科学/功能义务保留在对应任务，不能因V1成功从清单消失。

## 7. 测试与工程执行规则

缺陷修复先用真实触发反例证明；低风险可逆文档/元数据修改只做必要检查。不再机械要求每个文件先造“文件不存在”红测。不删负向fixture、不用xfail/弱化expected掩盖未修问题；用户已授权的阶段断言升版写明旧要求、替代行为和科学性/功能影响。

每次更改先跑受影响测试，涉及共享合同再跑Protocol v3套件；完成后不无原因反复扩大测试。1860不是未来固定期望数量。三个历史工具测试未执行必须单列，旧全仓故障不凭猜测分类。产品真实调用、浏览器E2E、医学判断和Word原生各有独立证据，不互相替代。

当前已验证的隔离测试解释器：runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python。示例命令在工作区根执行，先检查环境仍可用：

    env -i PATH=/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin HOME=/Users/smkzw TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)" LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONPATH=tests/protocol_v3:services/api:packages:. runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python -m pytest tests/protocol_v3 -q -p no:cacheprovider --tb=short

2026-09-12实施校正：env-i必须保留本机TMPDIR；遗漏时tempfile回落/tmp，旧macOS /var别名用例会在其环境前提断言失败。不要修改该测试expected或产品逻辑来掩盖运行命令遗漏；本次定向补齐环境后通过。

前端按frontend/package.json当前脚本和实际锁定Node版本运行；不擅自npm install升级依赖。日志与JUnit写新的run目录，旧证据保持。

每个阶段开始、派发前、用户改要求、压缩/恢复后、重复失败或路由异常时，重读最新全局AGENTS和当前任务；其余时候避免循环全文读取不变大文档。工程执行/审阅按当前Codex guard/route/runner，不照搬其他Agent固定模型；声明节点全部真正运行，不增加默认chair/manager。

长任务使用runner长hard wait、完成事件和必要lease心跳；工具短时yield只继续原句柄。健康运行不重派；终态失败才按manifest处理；unknown先按logical work key对账。OCR/翻译继续共享oMLX gate。凭证只在内存。

任务完成依据实际产物、源版本、测试和所需独立review，由Codex整合后更新Trellis；worker不能自行关闭任务。不要为正常阶段总结发送最终答复停止连续实施。只有用户要求暂停、需要其科学/产品重大决定、授权动作边界或无法自行解决的外部阻塞，才作无损暂停。

## 8. 明确取代的旧条款

- Goal旧入口1R.2、Trellis尚未初始化：已过时，入口为当前3R.4纠偏任务。
- 15点击/3文本硬门：用户改为20/5；15仍可作设计预算。
- 旧前后端“至少10字理由”等断言：按用户已批准目标升版为实质决定/必要理由确认，AI预填、无任意字符下限；不得只移除UI而保留后端同一拒绝。
- 安全专项与全部旧安全停点：USER_EXCLUDED，不换名再建；科学与产品正确性保留。
- 1R.4物理删除状态/字段：改为已批准兼容简化，不破坏恢复与旧事件。
- 全模块先齐备才看用户成品：被本轮用户选择V1完整路径优先替代。
- 所有任务固定worker/会商人数、固定模型、反复健康重派：由最新AGENTS和当前manifest判断。
- Word版本变化永久阻塞/强制修改系统更新设置：改为针对性producer能力复验，不擅改系统设置。
- eCTD全IND强制、PDF/A唯一合法、受试者法规禁词：停用这些过强表述，按设计v1.4及此前官方源校核执行。

## 9. 本轮交付与恢复检查

本轮review产物和诊断证据见reviews/mw_protocol_v3_full_review_20260912.md及runs/mw_protocol_v3_full_review_20260912。2026-09-12版本Goal文本保留；最新细化文本见plans/mw_protocol_v3_goal_prompt_20260913.txt。2026-09-13再次通过get_goal核实原生Goal为active，当前Trellis为3R.5A实施中，3R.4 A–D已由Codex接受工程范围（reviews/codex_mw_protocol_v3_3r4_acceptance_20260913.md）；仅更新prompt文件不等于修改原生objective，恢复时须读取实际Goal与当前checkpoint。

恢复时先检查最新用户指令和当前树，阅读当前.trellis/tasks/09-13-protocol-v3-3r7a/checkpoint.md，以及仍运行R03的09-13-protocol-v3-3r5a/checkpoint.md。3R.4 A–D已工程验收，不重跑原三反例回修或旧fresh review；当前R03执行会话按记录等待终态，接续3R.5A/3R.7A及V1。若复核发现某前提已由其他Agent完成，核对证据后跳过；不用日期/报告标题猜测最新状态。


### 2026-09-13 独立审阅后执行细化（不关闭3R.4）
A新增逐字保真：事实JSON字符串及嵌套值不沿用标签trim；ID/NonEmptyText仍显式规范化，旧已保存值不逆向复原。真实111合同机械绑定与输入/输出错误分类纳入验证。
D/V1新增具体恢复用例：已确认事实更新、legacy projection-only输入和冲突通过显式新决定/别名退役恢复，保留当前后继版本和旧回执；采用前在真实SQLite验证。禁止读取时偷偷把alias升级为规范事实或静默丢弃冲突。准入写边界使用声明类型和显式来源格式，native文本false不自动当布尔。
A机械解析登记与临床资料获取分开：resolution_registration逐项记录direct/projection/unsupported，generic JSON的legacy类型未决单列；新canonical字段允许由事实准入填入，不要求凭空造出不属于模板的正文义务来扩充词表。


### 2026-09-13 B运行合同投影细化（实施中，未验收）
章节是否出现与章节内某项义务是否适用分开：无期中仍保留“不计划开展”声明与依据；明确不适用的ECOG附录可由整章规则排除。复用ApplicabilitySnapshot记录节点状态，规则状态由绑定研究版本与规则集确定性重算，不创建第二事实库。
先以source_rule/source_contract哈希绑定的显式条件义务投影接入真实bind_applicable_input/check_applicable_output；不能仅修checker而输入仍强索取不适用参数。共享义务由任一适用控制者保留，未知保留未决状态，全部不适用才检查残留冲突。旧原始静态合同/夹具的兼容结构检查与研究实例有效合同区分；历史制品保留。原49规则/14重叠仅是接手盘点基线；最终须按当前合同全部规则及新增、拆分、退役谱系完整登记与复核，不能按旧数量截断或用少量示例关闭B。

B/D/V1贯通要求：按设计新增的“方案计划与执行记录”区分修正7.3及相邻消费者。反例覆盖尚无实际计划外访视记录时仍可生成记录规则、未来日期不需捏造、实际随访窗口和安全性信息处理仍保留。新内部适用性字段由已确认设计投影与资料准入形成，接入用户路径时不得新增逐字段填写表；以真实浏览器问题数/点击数验证。此要求属于科学与写作功能正确性，不是新增安全专项或阶段暂停点。


### 2026-09-13 D验收反例补实（不改变阶段顺序）

D最终2230通过后，owner实际API补验仍发现三项：当前模板不可用导致历史精确回放422；同操作key使用新decision/CAS重复写入；关闭期中保留旧受控参数。补入D必要行为：用历史记录材料判定精确回放，先于当前模板装配；逻辑操作身份去重覆盖无side-effect路径；校验完整结果事实并支持明确退休不适用参数、保留历史。未知及仍有active owner的共享事实不能退休。V1.2一次影响预览确认自动构造这组明确变更，不让用户操作字段或手工清空。证明材料在D owner_adoption_cases及同session回修目录；未修复/验收前不能用测试总数关闭。


### V1.1语料入口对账（2026-09-13，只读）

研究方案库实测仍18份（9DOCX/9PDF），文件路径/hash见runs/mw_protocol_v3_3r5a_source_audit_20260913/v1_material_inventory.json。clinical-protocol-corpus现有template_manifest仅5份，来自上层方案模版中的支持性全文/概要，其中含tracked稿，不能把该条款库当18份已准入。复用其来源定位和reuse_level分类，调用前核对实际源版本/修订状态；竞品仅用于分类启发，不抄作公司条款。V1优先完整clean DOCX并核对正文/表格/修订标记，不能按文件名clean单独认定有效最终内容；本轮仅盘点/hash，未重建语料、未做OCR或真实资料生成验收。


### V1.3/1.4章节产物结构细化（源代码复核）

registries/chapters.py当前ChapterSkillOutput仅分组facts/claims/evidence/objects；ContentObject有kind/occurrences/text/cells而无独立对象ID。不能从这四组内容可靠还原“段落→表格→说明段落”的原顺序，也不能把occurrences计数当多个实际对象。SemanticDocumentRevision已有有序semantic_blocks，可复用；SemanticBlock.content目前文本载体，表格编辑应复用现有结构化表格表达而不是把模型任意JSON当正文字符串。V1接线时最小升版章节输出：显式有序内容块、稳定对象/证据链接；保留旧checker兼容和历史fixtures，生成新路径使用可解析实际结构。验收具体往返：段落A→2×2表→段落B→第二张同kind表，生成解析/采用/保存重开/导出保持顺序、各对象身份、单元格和来源；不能只检occurrences>=2。此为原完整初稿/编辑/Word义务的落地，不提前改B已接受源或另造排版引擎。


### 3R.7A共享正文检查消费边界（2026-09-13）

实际旧链有三个直接消费者：medical_writing_content_quality.py逐块检查、ai_task_runner.py完整初稿输出验证、medical_writing_full_draft.py采用。后两者直接导入UNRESOLVED_DRAFT_MARKER_RE，故仅修detector过滤仍会在生成/采用拒绝合法正文。3R.7A采用一个可复用、带文本角色和定位的检查入口，覆盖三处实际消费者；保留旧真占位反例及定位语义，不全局删除规则或通过声明引用角色放行整篇草稿。正文中的研究执行要求（未同意不筛选、确认后锁库）与写作指令（样本量待确认后写入）分别验证。法规/文献标题保留原词，合法签署空白通过类型判断而非空字符串豁免全部正文。未接入的v3正文消费者须在V1显式接线，库测试不称端到端可用。


### V1.1 DOCX解析复用边界（2026-09-13实测）

旧writing_reference_docx.extract_docx_sections仅遍历body直接p/tbl，合成SDT内研究文字被漏掉；9份现有DOCX原始XML复核中，6份有目录控件（其中1份只以docPartGallery声明，无TOC域），CMS-D008Ⅰ期的EndNote.ReferenceList控件含13条参考文献，被旧解析路径整体跳过。证据docx_reuse_probe.json及docx_controls_adjudication.json。V1.1复用时需递归处理内容控件并分类目录/参考文献/正文，保留被排除结构的定位与理由；不能只把所有SDT过滤掉，也不能把目录重复当正文。此发现不要求现在重新解析历史语料或重跑OCR，且不激活Ⅰ期支持。旧parser物理页固定1实际为逻辑容器，V1来源应显示DOCX部件/段落/表格定位；原生分页完成前不能显示成真实第1页证据。脚注/尾注、修订标记与合并表格必须按实际输入对账，未支持内容明确登记。


### V1.1 产品来源持久化前提（2026-09-13当前代码）

产品SqliteUnitOfWork.artifact_store目前返回None（前期端口允许out-of-scope，不倒推取消1R工程验收），但已有artifacts/local_store.py的LocalArtifactStore及共享合同测试，不能只因SQLite handle未接就另造BLOB存储。V1.1优先复用该内容寻址文件存储作为持久化暂存，将SourceArtifact/证据/项目关联在现有SQLite事务中采用；不建立第二个事实库。接线前定向验证同logical key+相同hash复用、不同内容保留修订、重开读取、并发实例不覆盖清单及实际字节可用。若现有本地存储在实际并发/持久性行为不满足，先做必要最小修复，不无依据复制整个存储实现。失败采用可以保留未绑定暂存制品，但不能称已医学准入；禁止清理历史。按logical key/revision读取具体来源（hash检索不是唯一来源证明），上传完成必须基于实际持久化。当前SourceArtifact/EvidenceUnit/MedicalAdmissionUnit已有合同，解析产物不因非空或quality_score自填就自动医学准入，目录/引言不能单独支持设计关键事实。


### 2026-09-13 owner验收与完整路径续接

3R.5A/3R.7A限定工程范围已接受，证据reviews/codex_mw_protocol_v3_3r5a_3r7a_acceptance_20260913.md，原子登记/源Word清单不是医学或生成Word通过。唯一活动V1.1；有序DOCX解析与SourceIdentityService已实际临时SQLite/LocalArtifactStore验证，后续接入实际资料API、预填与确认、V1.2整稿。来源当前版本只从已提交source_catalog事件投影，暂存manifest latest不能决定当前来源；相同内容回放不退回后继。模型不得自填准入评分。此前源投影/医学充分性/Word义务继续保留，不以通过数字代替完整可用路径。Goal prompt已更新文件锚点，未通过内部DB修改原生Goal。

V1.1种子入口显式替代旧4.1“高置信自动采用”的范围：高置信可自动预填候选，涉及八类高风险仍经后续卡明确确认；不能由模型confidence自动批准剂量/人群/对照。八类非空ResearchSeed保留为完整对象，入口支持稀疏意图与资料，缺口单独表示，不制造八个必填文本或用待确认占位填满合同。出处绑定已保存source_id/hash/XML块，source identity与医学准入分开。


#### V1.1 接线后的剩余交付义务（2026-09-13）

以当前Trellis checkpoint为执行状态：资料/研究预填API已形成候选，继续完成独立复核、实际应用的共享探针及凭证内存绑定、页面入口与任务恢复，再进入推荐/全稿/编辑/Word链；不能以新接口测试通过关闭V1.1。资料分组添加、元数据改回未注明、后台初始失败到纠错中断恢复纳入真实用户验收。接口后台回调使用既有GraphRuntime，不扩建第二任务引擎。


#### V1.1→V1.2 实际页面后的连续实施细化（2026-09-13）
1. 现25文件候选由原C03同会话集中复核；owner查证真实结果/哈希后解决实际缺陷，不因阶段绿测暂停。
2. 浏览器已证明说明提交、批量DOCX保存、类别更正、带资料提交与刷新恢复的有限路径。证据runs/mw_protocol_v3_v1_1_20260913/browser_functional/owner_browser_observations.md。继续验证跨刷新排除选择、错误/恢复按钮、实际字体与窄屏。不得称整个App、真实模型或Word已验收。
3. 推荐入口复用既有StudyDefinition采用/影响传播与同一Graph模型合同，先补最少研究意图，再产完整有来源推荐。缺口长串自由文本替换为有推荐的问题，八类高风险只在相应卡显式人审；不要新增第二事实库或重复批准步骤。
4. 单个真实Ⅱ/Ⅲ期实例贯穿所有适用章节、有序段落/表格、受控编辑、原生Word；此前源库CSU仅是候选参考资料，不因工程测试自动成为本项目权威。未知事实仍需最少用户输入，不借默认值制造“完整”。


#### V1.2 推荐采用必须保留复合设计（真实资料反例）
复用冻结5.1–5.5约定agent2/clinical_worker.py、statistical_worker.py、reducers.py、recommendations.py、study_definition.py、applicability.py、protocol_summary.py、subgraph.py与api/design.py；复用既有RecommendationOption、DecisionRecord、SQLite采用/适用性/影响接口，不另造事实或任务库。
首先用真实参考整理中的互补项/治疗期和治疗组构造反例：任何“选一个剂量”不能丢负荷量或另一治疗期，样本量不得写入人群定义；原始候选全量对账为采用包/重复引用/真正备选/错置待归位，不按字段数组长度当决策数。其次将完整设计包接到一个高风险卡，确认通过真实API只写一次关联typed facts，再扩展其余卡与整稿。数据不足时集中最少意图问题，避免八文本框。
标准文案和确定性投影不额外调用模型；科学备选和统计假设通过实际材料形成，未解决重大科学取舍才问用户。当前独立语义审阅runs/mw_protocol_v3_v1_1_seed_semantic_review_20260913不替代来源/医学准入，owner核对终态与原文后再采用其意见。

V1.2事实桥接附加检查：当前fact_bindings有743条登记，但intervention.dose_regimen、picos.intervention_dose_regimen及其selected_regimen等多处仍为legacy json；此为已登记兼容形状，不是完整给药结构已经建模。新设计包需保留治疗期/组、负荷/维持、频次、途径和单位的结构，明确这些消费路径的同源投影；不能把一段候选文字复制成几套可分别编辑的事实，也不能以json可接受任意对象代替组合完整性。按相关章节实际合同解释投影含义后定向扩展，不重做全部3R.4或把此项变成全工程停点。


#### 给药推荐首条采用链进展（2026-09-13补充）
原独立语义审阅已终态并按原文裁定，见reviews/codex_mw_protocol_v3_v1_1_seed_semantic_adjudication_20260913.md。不得将所有摘要省略判为事实错误，真实原始输出不修改。已实现候选全量对账、复合给药typed proposal、完整输入编译、原引文校验、既有Graph/harness/SQLite执行与单一intervention.dose_regimen事实提议；实际合成HTTP采用/精确回放已验证，尚非实际UI采用或全产品通过。下一顺序：后端已存run到推荐/采用接口（不信任浏览器拼接事实）→独立复合给药卡接线→picos等章节的同源投影→其余适用高风险卡/整稿。登记skill.regimen-design-proposal，不复用seed技能身份；seed registry的key_basis说明按已有原始请求身份实现纠正，不改变历史图/调用。


给药链实测更新：真实glm原请求完成needs_information（0纠错），96源hash零漂移/原seed未变；证据real_reference_regimen/owner_receipt_summary.json。RegimenDesignWorkspace已从已存seed接新API、按project+seed保存run/丢ACK意图，读取/恢复与UNKNOWN不重派定向测试通过，原生Goal不篡改。仍无真实采用/整稿/Word验收。后续采用前补问题分流及来源裁定的版本记录，保留真实回执；核正文+SOA支持的继续期给药次数，不向用户询问单位空格或工程是否看图。实际readonly viewer仅预置已知ID，不能据此声称新浏览器自动发现全部任务。


### 2026-09-13 配置失败回执合同纠正

依据用户允许非科学性旧阶段断言升版和fresh C03反例，确定发生在写入前的P1_SERVICE_CONFIGURATION_INCOMPLETE由HTTP500调整为424（依赖未就绪），四字段公共错误包不变。原commit边界故障仍500/unknown，不放宽、不删除负向fixture。前端保留原选择与CAS，收到424后明确显示未执行；只在用户点击继续保存时重用原intent，不再要求重新做医学选择，不自动重派。模板采用旧测试的500断言同步按此真实协议纠正为424，并加强未执行文案及原有零写断言；不是为了测试回绿忽略缺陷。来源read-set、纯回执查询和当前有效性仍待完成。

### 2026-09-13 当前研究读集与采用链审阅修订

以 C03 `mw_protocol_v3_research_context_review_20260913` 的冻结28文件、实际反例及owner源码核对为依据，首条完整路径继续推进，不以审阅返回作为暂停点。优先完成以下衔接，再扩大章节生成：

1. 设计输入必须带目标StudyDefinition身份及实际已确认医学facts。source/seed提议保留其候选性质；资料更新保留已有研究内容，同时按依赖使受影响确认失效。不得通过禁止所有已有研究更新资料来回避实现。
2. 新study-bound生成的逻辑身份包含目标与医学读集。旧source-only请求身份、原始输出及回执原样保留；不得以编译器升级为由重跑成功调用。未知回执恢复必须使用原请求的身份材料，不能改读最新facts后错误地认定旧任务不存在。
3. 采用前核对目标、来源及临床读集；历史精确操作仍返回原效果和当前后继定义，不回退版本。UI分别呈现原操作已保存和当前确认有效性。
4. 章节当前词汇为`picos.intervention_dose_regimen`及其子字段，已采用复合事实为`intervention.dose_regimen`。建立显式同源投影，保留治疗期/组/时点/剂量体积类型；试验药/对照角色缺失不能靠名称猜，最大剂量与起始剂量不能把不同药物或单位混算。旧测试中的`picos.intervention.dose=10mg`是fixture输入，不能写成产品自动默认值；实际已有旧事实与新事实冲突仍必须处理。
5. RecommendationOption/引用记录持久化只证明已保存的候选和定位。原文前后文随引用保留；文字匹配分数不得当作医学准入。CHECK纯函数不新增clock/store副作用，producer产物在既有可写边界保存并绑定明确版本。

当前证据：confirmed-study纯输入/逻辑身份与旧coordinator共7测试通过，引用上下文3测试通过；两者尚未完成API全链接入。新增入口57测试文件inventory完整，正确v3 flag构建成功。独立审阅和合成浏览器结果不替代真实医学、完整章节或Word验收。

### 2026-09-13 V1.3/1.4实际文稿接线顺序

当前源码核对：canonical/document.py已有纯reducer，SQLite已有semantic_document当前/历史仓储；原ApplicationService/API/client无文稿读写入口。已补只读按研究/文稿身份查询并单事务标示绑定current/changed/missing，实际SQLite/HTTP重开保持原正文。该状态只表示研究版本是否一致，不表示医学正确性或导出批准。

下一接线复用现有组件，依次完成：有序章节候选（复用StructuredTable，真实对象而非occurrences）→服务端指定研究/模板/证据版本的全部适用章节产物→整稿原子采用到同一SemanticDocumentRevision→受控正文/表格编辑与保存恢复→Word导出/原生校验。原medical_writing_full_draft.adopt逐章节save，前章成功后后章失败可能部分采用；不可直接套入v3“整稿一次采用”的承诺。旧链只复用可验证的解析/表格/导出工具，不能搬其循环写入作为整稿单事务。

候选载体不创造MedicalAdmissionUnit、confirmed状态或可信评分；known_evidence_ids仅输入集成员检查，实际生成由服务端从已记录来源供给并核版本。SemanticDocument的事实/准入绑定未就绪前，不用虚构ID把完整初稿标为可申报。段落/表格顺序与引用结构的工程通过不替代正文科学性、医学准入或Word。补全原计划义务，不取消剩余7类决定、章节范围与Ⅰ期未决。


### 2026-09-13 章节接线与研究期别统一

基础信息明确确认后，framing.study_phase作为期别唯一当前字段；总体设计framing.structured_design.phase仅为章节词汇/历史别名。读取旧字段保持兼容，同时存在且不一致时报事实别名冲突，不自动迁移历史研究或写两份值。两章影响传播均读取该声明。其余设计参数仍由对应已确认事实提供，不能由期别推断。

生成表的provenance_lineage与note.source_refs只存输入EvidenceUnit身份，原文定位保留在source_locator/marker_source_locator。通用旧表格载体保持原语义；不把定位字符串注册成假证据。章节工厂强制绑定真实研究/版本；整章排除与条件未决均不启动生成。结构纠错仅原模型固定一次，保存具体错误位置、原输出和原输入。上述链路仍为候选，未替代内容核对或Word验收。


### 完整初稿调度前的当前接线义务

使用CurrentTemplate.chapter_order（源模板body_child_index），不能用文件名排序装配正文。manuscript-plan接口逐一保留全部载体，facts_ready仅表示章节输入可编译；未知/缺失保持显式，不能丢弃节点后称整稿完成。该计划不评估来源充分性、不调用模型。

生成输入使用已保存来源版本的完整DOCX结构，既有seed units的文字投影不能代替合并格/脚注/story/诊断。read_pinned_chapter_sources从项目已提交source history读取原字节，并核原seed来源投影；恢复不选latest。fresh生成仍先核当前StudyDefinition活动context。source_material目前为proposed、quality_score=0（未评估）、无MedicalAdmission，正文候选与医学准入分开。来源编译需要实际extracted_at，首次bundle必须通过既有持久运行/制品机制保存，重开读回同一bundle，不以每次新时间戳产生新请求。完整请求不得静默截断，容量不足要保持已存材料并明确处理。

剩余7类高风险卡接线前须处理现有all_facts读集：新确认不得机械使全部早先确认失效。不能简单删除读集掩盖真实依赖；区分生成输入是否变化与医学确认是否受影响，验证逐卡确认到整稿的实际点击数及无关修改不重开。该问题仍未实现解决，不把单张给药卡通过当八卡通过。


### 2026-09-13 整稿准备与修改恢复补充

基础信息采用集中预选；只有用户选择“自行修改”才出现已有内容预填的输入，不增加必填空框。用户修改作为本研究事实保存，不改写来源摘录。恢复原确认时，主卡展示服务端当前研究信息，历史选择单独保留；再次调整从当前值开始，不能把旧回执中的值覆盖回去。

整稿准备口径为111个合同载体（包含封面与前置件）；目录容器标题属于模板结构，不独立生成第二份章节。未确认研究仍返回完整待补清单和study_not_confirmed，不推断任何章节不适用。已确认路径同时展示适用性未决和已检出的事实别名冲突；未决不得遮蔽摘要/设计期别矛盾，也不得按未投影原合同强加已排除的条件义务。

DOCX来源解析v2读取styles.xml名称与大纲继承，数字样式标题保留在完整上下文、不当正文候选证据。原v1只用于核对历史seed的原投影；旧seed、模型回执与完成bundle不改写。源bundle首次通过现有graph完成事件保存，重开读原extracted_at和全文；新编译版本产生明确的新准备身份，不重跑旧成功模型调用。已实现独立SQLite恢复用例，产品API和整稿调度接入仍待完成。

下一衔接：服务端核当前研究活动来源→读取或准备持久来源包→按模板顺序逐章绑定研究事实并生成候选→内容与证据核对→整稿原子采用→编辑与原生Word。facts_ready、解析完成和结构校验均不能作为正文完成判据；source diagnostics与未评估质量必须随整稿内容核对保留，不能只传裸evidence丢失版本/修订信息。


### 章节持久请求接入后的连续实施顺序（2026-09-13）

当前源包准备与单章prepare/start/recover已挂默认composition，仍默认flag off；Trellis记录实际验证，不以此关闭V1或启动生产。source bundle成功任务只读恢复；明确本地读取失败保留原失败并最多一个固定retry子任务，未知执行结果不自动重派。新章请求服务端读取当前研究、模板和已保存完整bundle，前端只提交原来源任务、研究版本及服务端计算的expected key，不提交医学facts。旧章恢复先读原request，不借研究后来更新重复生成。

下一工程顺序保持完整路径优先：
1. 集中完成本批source/条件诊断/章节HTTP的原会话独立复核；owner检查实际结果和冻结哈希，解决实质问题，同时继续冻结外前端。浏览器重启前保留现有成功来源包及失败设计身份。
2. 前端使用已接七个来源/章节方法，准备身份→持久保存意图→开始→只读找回原结果。不能以404清空未核明意图后自动发新任务；写作任务仍在运行时只观察/恢复同一身份。
3. 建立章节候选阅读视图，段落/表格按原顺序展示，完整表头、合并单元格、脚注可见；区分候选与已采用全文。复用StructuredTable数据合同，现有StructuredTableDesigner偏来源编辑且只读文案为“原始来源只读”，不能原样用于生成候选而冒充来源。
4. 全稿调度需一次固定研究/模板/来源快照，保留全部适用章节及明确排除记录；任一需要信息或失败都不得把已完成子集标为完整。结合剩余七类高风险推荐及all_facts读集纠偏，先让AI补候选和问题，不让用户填合同字段表。
5. 后续仍为真实来源/内容核对→整稿单事务采用→受控编辑及失败恢复→原生Word成品。当前单章fake HTTP结果不作为本研究医学决定或整稿完成证明；真实研究方案重构/新研究目标尚未收到用户明确选择，独立工程继续。


## 用户最新构建约定（2026-09-13，覆盖此前阶段红测要求）

先完成整体构建，期间不新增或运行阶段性测试；保留全部既有测试和证据。完整构建后统一进行功能、恢复、真实模型、科学内容、ego(lite)浏览器及Word原生完整测试，再按实际失败修复。持续施工，不以阶段验收或会商等待结束当前任务。工程执行与会商仍遵循最新全局AGENTS/live manifest和超长hard wait；后续派发显式禁止阶段测试。

前端参照kangzhe-design-3d包的core+site视觉：浅底、橙#FF9900/黄#FFCC00识别、橙底深字、白卡光影层次、正文16px以上、辅助文字14px优先、卡圆角不超过8px、长正文与表格保持静止可读，减少动态干扰。资料→确认建议→阅读修改→导出共用导航与操作层。用户指定的是美学参考，保留已批准React/API/SQLite架构；不套静态file://、window.DATA_X或幻灯片画布，不增加无业务目的的dashboard/3D模型/粒子库。原生Word格式仍以研究方案模板权威为准。

### 工作初稿的真实持久保存（2026-09-13施工补充）

整稿候选按全部适用章节一次保存到既有SemanticDocumentRevision/SQLite UoW，不另造文档存储。PROPOSED工作正文允许医学准入与claim链接为空，来源和事实仍绑定原请求，不伪造审核；已确认/冻结块继续要求真实准入与证据，正式确认文档不得夹带未确认块。保存用原operation、文档revision/hash CAS及原回执恢复；恢复后另读当前文档，不能用历史版本覆盖后续修改。自由正文改写不自动成为研究事实或医学批准，事实变化仍经StudyDefinition方案确认。此修订尚在构建，完整构建后统一核验历史兼容、编辑恢复、科学一致性与Word，不宣称阶段验收。
