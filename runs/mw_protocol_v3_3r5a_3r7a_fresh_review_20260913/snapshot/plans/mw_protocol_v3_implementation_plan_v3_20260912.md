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
