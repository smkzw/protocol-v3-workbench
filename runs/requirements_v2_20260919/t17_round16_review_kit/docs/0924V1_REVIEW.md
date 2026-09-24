# Protocol v3 · 0924V1 复审

## 结论

继续整改，尚不可认定产品全链完成。相比0923V1，MTPLX实际端点、API模型身份、主配置守卫、路由身份及尝试记录已有真实进展。新的主阻塞是预填预约恢复和阶段状态耦合；新增“等待/取消后提交”还引入了排队意图不持久化、取消失败仍继续提交尝试的问题。翻译重试的“清除多父引用”需重新审查。R15的成功汇总与原始测试范围不一致，必须先纠正验收口径。

本轮不要求重建数据库、模型路由平台、任务调度器或Office引擎，不要求重新确认用户已决定的两入口、自由工作稿及显式核对模式。

## 1. 基线和验证边界

- 仓库：`smkzw/protocol-v3-workbench`。
- 基线：`455b37ee4530628736bd6b37b622796f13e9498f`，2026-09-24 06:13:53 北京时间。
- 上轮基线：`372360cbad8e5a4bf48cfdf44fd013ea36fe2212`；compare报告36个新提交。
- 当前交接：`runs/requirements_v2_20260919/t17_round15/R15_TASK_RETRO_HANDOFF.md`。
- 已读：交接/原始测试报告、对比与关键提交、预约及完成/释放逻辑、当前前端排队/取消/刷新路径、翻译恢复方法、路由模块、主配置工厂、Office保存回执及既有验收合同。
- Git直连检查返回DNS错误，未完成clone。通过GitHub连接器读取固定提交。
- 没有访问用户Mac，没有复测当前监听端口，没有启动实际产品后端、模型、浏览器、GenOffice或桌面Word。没有修改或推送仓库。
- 隔离检查共12个场景：预约5、取消4、路由3；详见evidence。仅路由完整模块与Git blob逐字校验；其他为真实方法/函数体节选加模拟依赖。预约使用临时真实SQLite，但不是产品数据库集成测试。
- R14/R15旧版本与本轮源码须分开。原始报告的SOURCE_HEAD为`4cc2deb...`，期间还有重启；不能把全部结果直接标为当前HEAD验收。

## 2. 既有修复的复核

|主题|本轮结论|证据|
|---|---|---|
|MTPLX实际端点|发现记录报告25个listener中找到8002，API served ID为`mtplx-flash-next-optimized-speed`；11234旧假设已纠正|S03|
|本地能力|有小JSON、820 completion tokens结构化输出和产品gateway探针记录；不等于长全文或任意surgical任务质量已通过|S03|
|主配置静默跳过|当前工厂对非OpenAI-compatible主provider明确抛错，保留可选备用跳过逻辑|S04|
|路由执行身份|当前hash含端点/transport/expected model/profile revision；完整原模块隔离控制通过|S05|
|逐次尝试记录|wrapper已有attempts数组，429控制记录两路；401控制不回退|S05|
|Office回执|原有persisted/operation/hash/版本校验仍在，不再列为任意2xx成功的旧缺陷|S06|
|枚举否定语义|本批提交/交接记录已改精确映射并暴露normalized_from、downgrade_reason；未在本轮全量复测所有枚举|S01/S09|

注意：8002是有时间戳的运行证据，不应再次升级为永不变化的端口真理。模型目录、实际请求身份、能力探针、完整医学任务接受分别报告。

## 3. 工程发现

### 0924V1-R01 · P1 · 旧in_flight的强制恢复路径不收敛

**定位**：`medical_writing_authoring_journey.py::_acquire_generation_reservation()`；前端`requestPrefillPackage()`/`generatePrefill()`。

HANDOFF说“没有时间回收机制”不够准确。方法已有非force等待窗口，并在观察预算结束后以logical_call_id和status条件将原记录转为unknown_outcome；force=True却在进入这个分支前直接抛错。该分支也不按记录的updated_at判断陈旧程度。

隔离场景把in_flight时间设为2000年：两次force仍原样in_flight、无接管；使用非force并令测试观察预算为0，则现有代码确实转unknown_outcome，随后force可进入supersede helper。正常live force被拒绝和completed重放的控制也成立。

**含义**：不是删掉保护就好，也不是加个“15分钟后强制重跑”。活跃长调用、已发送但结果未知、所有者已退出必须区分。不能把用户观察超时当作模型已停止。

**整改**：复用已有durable运行身份，加入/接通所有者与租约证据、结果查询、陈旧记录的CAS归类以及同操作恢复；保留logical_call_id fencing、attempt_history和晚到结果检查。旧包仅因无关journey投影升版失效时，应核对输入/依赖指纹，不得通过篡改旧包版本绕过CAS。确实变化才刷新受影响候选，不要求用户重复输入已确认内容。

### 0924V1-R02 · P1 · “已排队，可离开”仅有组件内存

**定位**：`MedicalWritingAuthoringJourneySetup.jsx` 的`queuedImpact`状态、等待effect和影响面板。

queuedImpact仅useState；按钮只setQueuedImpact，没有提交持久化排队意图。页面重新挂载会从null开始。后台流水线能继续，不代表用户排队的payload会恢复。effect错误时还会直接清空queue并要求重新提交。

完整组件关键词核查只找到声明、effect和按钮三处，没有该意图的持久化恢复链。跨项目重用组件时也应核查队列的project/epoch绑定；本轮没有启动真实页面，未把该风险宣称为已发生串项目写入。

**整改**：优先复用已有草稿/操作记录，保存project、base revision、payload digest、operation、queue状态和创建时间。若首版只提供本页等待，必须如实标注并保全用户草稿，不能宣称跨刷新恢复。等待结束只对当前版本重算影响；有新科学影响才请用户确认，不能机械增加重复批准。刷新、关页、切项目和处理失败均需验证。

### 0924V1-R03 · P1 · 取消失败或不在原项目，仍继续确认尝试

**定位**：同组件`cancelResearchPipeline()`、`cancelPipelineThenSubmit()`。

取消函数catch后仅设置文案，没有throw或返回失败状态；项目已切换时同样只return。外层await随后无条件confirmImpact。模拟网络错误、非终态取消响应、项目切换均触发了一次confirm调用。

**边界**：这证明前端继续尝试，不证明后端接受了非法写入；后端版本/锁守卫可能拒绝。用户仍可能看到二次409、被覆盖的取消失败提示或过期影响预览。

**整改**：返回类型化取消结果；非成功立即终止该组合动作；已受理取消不等于完成取消。确认终态后重新取当前项目/版本、重算impact，不能复用取消前的preview。使用现有取消endpoint和版本合同，不另造取消任务平台。

### 0924V1-R04 · P1待集成验证 · 多父翻译失败被改写为无父新恢复

**定位**：`writing_reference_translation_batch.py::_prepare_document_plan_contract_lineage()`及`_allocate_document_plan_retry_lineage()`；提交`c3acd77...`。

len(source_ids)>1时，当前代码清空副本上的failure_source_stage_run_id，把错误改成同run先前失败，按字典序保留一个非derived source。在其后的parent=None且结构错误分支，可返回generation=0、parent=''、source_item=''。新增测试把retry_generation=3得到0/空parent写成预期。

**准确界定**：旧数据库行没有在这里被物理删除；但当前恢复描述抹平多个已知父引用，并可能重置代次。它修复了“入口抛错”，尚未证明多个父关系被正确重建，也没有解决R15的228/230规划/翻译失败。

**整改**：先按project/artifact bytes/extraction revision/planner contract及输入身份分组；多个合法祖先允许形成受控recovery事件并保留parent集合，或分别恢复子组。不能凭artifact_id和字典序挑选业务根节点。预算和源错误应保留。取一个实际失败文档和其多父图做数据库集成回归，再验证根规划器，不要对几百条条目盲目重派。

## 4. 验收和产品方向发现

### 0924V1-R05 · P1验收问题 · EXIT=OK不能表示全链完成

R15 tester2将全文生成“运行中”、预览/正式Word被拦截同时列为PASSED；HANDOFF又明确没有测试者走到导出后的Office，21批仍在运行。tester1报告同时有EXIT=BLOCKED与EXIT=0。

正确解释是：测试进程/报告完成，与业务完成分别记录；已证明部分初始化、提交、等待或负向门禁，不是全文落盘和Office成功。R15 tester3提交的文件仅11字节、tester4是中期结果，本轮不能据此宣称四场景最终通过。

### 0924V1-R06 · P1验收问题 · 双入口、操作负担、文献和语义保真仍有替代验证

- tester1在摘要导入失败后改走从零；这不是入口A通过。
- tester2称16个核心决策点击，同时报告113次交互；阶段表点击列合计22，与16不一致。113包含聚焦/复选等交互，不能全部直接称为113次物理点击，但同样不能把业务组数当≤20点击达标。
- 文献面板/导入入口/表格交叉引用存在，不证明正文引文新增、移动、删除、刷新编号及Word往返。
- 正文尚未生成完时“绝对纯净”“零污染”不能作为成品保真验收；禁词阴性也不能证明参数来自本项目。

应保留既有功能，不为测试方便删掉入口或缩减推荐。用原始操作event划清一次点击、文本填写、人审、等待、重试，并标记由测试者手填了哪些本应AI预填的内容。

### 0924V1-R07 · P2过程风险 · 测试中部署、运行身份和清理时机

R15测试报告为5186/4cc2deb；HANDOFF环境为34081/34082并记录两次测试中重启。二者可能通过proxy连接同一产品，并非端口不同就证明错环境，但需要逐段运行指纹支持。

下轮先查既有tester3/durable job真实状态；不要照handoff“开工先清理R15项目”机械执行。归档测试数据可以是合法工作，但要确认没有在途任务，并保留可独立恢复的DB/制品/索引/日志和校验。不得把真实恢复缺陷通过清库掩盖。

### 0924V1-R08 · P1验收缺口 · 空模板拦截与带缺口工作稿应各自验证

阻止把空模板当正式交付是合理的；但用户已明确关键设计确认后、非关键缺口仍可进入可编辑工作稿。R15只验证“按钮被拦”，没有验证“有可靠正文且仅非关键缺口时可保存、进入Office、重开与下载”。本轮没有将仅凭该报告就判定为后端新回归；它是必须补上的正向验收。

不得把工作稿与正式批准重新合并。安全/科学未决留作显式核对，不以清空所有正文或无限资料前置代替推进写作。

## 5. 下一阶段裁决

不直接按“修F-E→再派R16四场景从头跑”推进。优先顺序：

1. 冻结当前源码/运行指纹，收回在途结果，保存现有成功前缀。
2. 同一批关闭预约恢复、排队意图持久化、取消失败传播及stale影响预览。
3. 以一份真实失败文档修复翻译规划根因及多父恢复语义；不清空祖先信息求通过。
4. 从tester2现有任务核实最终状态，实际走到工作稿保存、Office输入、保存关闭重开、下载；结果未知先查原任务。
5. 独立修复入口A并完成摘要自动预填正向链；不能改走B代替。
6. 再以差异研究交叉测试。测试期间不非计划部署；故障注入单独隔离。记录共享本地模型的队列/内存/并发，避免四路竞争与应用缺陷混淆。
7. 最后处理十像素提示徽章、错误直出、按钮不可点击等UI问题；不得用JS click替代真实可点击的验收。

## 6. 建议产品边界

后台AI继续处理时，用户输入/工作草稿应能被可靠保留；当前运行继续读取其冻结输入。真正影响既有生成结果的研究决定，按明确依赖重算，不应因任意资料批次运行而冻结整页保存。这个方向不降低来源要求，也不擅自采纳未确认科学内容。

研究设计推荐应有真实可选备选；选区surgical修改是另一种任务。若局部模型因强制产出多份相异候选而被卡住，应先核对该门槛是否对应任务，而不是为凑数量改写用户指定范围。该项只作设计核查建议，不授权静默放宽已有产品合同。

## 7. 本轮不作出的结论

不宣称全仓逐行审查完成；不宣称R15产品全链已通过；不宣称当前Mac仍是上述端口/进程；不将820-token能力探针扩张为全文医学质量接受；不把历史Word部分证据删除或泛化为当前双入口接受；不认定228/230失败的根因已被定位。

## 来源索引（固定提交）

[S01] `runs/requirements_v2_20260919/t17_round15/R15_TASK_RETRO_HANDOFF.md`
[S02] `runs/requirements_v2_20260919/t17_round15/R15_PARTIAL_AGGREGATE.md`（通过最新提交patch与目录读取）
[S03] `runs/requirements_v2_20260919/LOCAL_ENDPOINT_DISCOVERY_0923V1.json`
[S04] `services/api/app/main.py`，1580–1745
[S05] `services/api/app/ai_runtime_fallback_provider.py`，完整模块；Git blob `661f40c430c50b7256c53461eab48d19fa21ac73`
[S06] `frontend/public/genoffice/bridge-shim.js`，95–170
[S07] `services/api/app/medical_writing_authoring_journey.py`，重点5580–6220及生成预约调用
[S08] `frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx`，重点700–965、1090–1210、2180–2370、queuedImpact全部引用
[S09] `4cc2debc16a477cf0776bed697d89b37a9ba00f7`提交patch
[S10] `services/api/app/writing_reference_translation_batch.py`，2900–3185及`c3acd77f1054f2e65f8ca638fc027dfc8c01c383`提交patch
[S11] `runs/requirements_v2_20260919/t17_round15/tester1_report.md`
[S12] `runs/requirements_v2_20260919/t17_round15/tester2_report.md`
[S13] `plans/protocol_v3_0922V2_execution/07_ACCEPTANCE.md`

完整来源链接与工具citation marker映射见 `evidence/source_manifest.json`。引用文件并不意味着已逐行审查其全部代码；读取窗口和实际测试范围已明确列出。


## 固定源码链接

- [S01] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/runs/requirements_v2_20260919/t17_round15/R15_TASK_RETRO_HANDOFF.md
- [S02] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/runs/requirements_v2_20260919/t17_round15/R15_PARTIAL_AGGREGATE.md
- [S03] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/runs/requirements_v2_20260919/LOCAL_ENDPOINT_DISCOVERY_0923V1.json
- [S04] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/services/api/app/main.py
- [S05] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/services/api/app/ai_runtime_fallback_provider.py
- [S06] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/frontend/public/genoffice/bridge-shim.js
- [S07] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/services/api/app/medical_writing_authoring_journey.py
- [S08] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/frontend/src/features/medical-writing/MedicalWritingAuthoringJourneySetup.jsx
- [S09] https://github.com/smkzw/protocol-v3-workbench/commit/4cc2debc16a477cf0776bed697d89b37a9ba00f7
- [S10] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/services/api/app/writing_reference_translation_batch.py
- [S11] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/runs/requirements_v2_20260919/t17_round15/tester1_report.md
- [S12] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/runs/requirements_v2_20260919/t17_round15/tester2_report.md
- [S13] https://github.com/smkzw/protocol-v3-workbench/blob/455b37ee4530628736bd6b37b622796f13e9498f/plans/protocol_v3_0922V2_execution/07_ACCEPTANCE.md
