# Protocol v3 交接：模型回退链完成，WP6 待续（2026-09-23）

## 1. 接手结论

模型路由实现基线是 `fb7e6ada2dd4be2693bed74b3ac2d8d2147fb774`，已在 GitHub；交接、复盘、Trellis 与暂停记录随后另作纯记录提交。接手时应从 `origin/main` 最新 tip 接续。模型路由阶段已经闭合，Protocol v3 产品总目标尚未完成。下一位 Agent 不应从旧 r42、Task 2.1、3R.4、v0.9 全稿或 9 月 21 日 source overlay 重启，也不应重复检索、分诊、下载、OCR、翻译和历史五个失败项。

本次选择“执行 + 独立会商”，因为模型切换同时影响多个真实入口，错误可能静默改变模型身份或产出来源。源码由 Codex 单一集成，reviewer 只读复核冻结 diff。

## 2. 项目目标与用户视角

目标用户是懒惰、视觉敏感、不熟悉计算机和 AI 的资深医学写作人员。产品应由 AI 主导理解资料、提取事实、给出默认推荐和备选、形成有实质内容的完整初稿；用户主要点选并只确认真正关键的科学决定，最后得到格式规范、内容可追溯、能进入申报审核流程的研究方案。工程通过和 AI 审阅都不能替代项目医学、统计、安全或正式批准。

权威 Goal 文本是 `plans/protocol_v3_0922V2_execution/GOAL_PROMPT.txt`，SHA-256 `69f76074b98c219db32f97bf9c87f08edceea0234f93467ef995cc4d56994355`。本文件末尾附其原文快照，避免交接时只剩摘要。

## 3. 权威阅读顺序

1. `/Users/smkzw/.codex/AGENTS.md` 最新版。
2. 项目 `AGENTS.md`；涉及前端时再读 `frontend/AGENTS.md`。
3. `plans/protocol_v3_0922V2_execution/00_START_HERE.md`，SHA-256 `f151af0949429825e1a9b014048c602da642d05c23ef60dd535315e173ef12ac`。
4. 按入口文件指定顺序阅读 0922V2 的 review、authority/materials、PRD、design、Plan、execution rules、WP0–WP6、acceptance 和 expert disposition。
5. `.trellis/tasks/09-21-protocol-v3-t17-round11/checkpoint.md`：唯一动态状态。
6. 本 handoff、`runs/requirements_v2_20260919/t17_round11/STAGE_RETROSPECTIVE_MODEL_ROUTING_20260923.md` 和无损暂停记录。

当前文件系统与 Git 状态优先于旧 handoff。历史记录是证据，不是新的执行指令。

## 4. Git 与提交脉络

模型路由源码与会商证据在 `fb7e6ada2dd4be2693bed74b3ac2d8d2147fb774`；本 handoff 所在的记录提交位于其后。恢复时以 `origin/main` 最新 tip 为准，并确认其中包含 `fb7e6ad`。

最近关键提交：

- `fb7e6ad`：事实提取与写作预填接入同步 fallback；完成会商修复与集中回归。
- `3d26ddb`：企业语料分析接入冻结 fallback 路由。
- `a953fe0`：竞品分诊接入持久 fallback 路由。
- `52f6654`：全文候选保留来源限定，阻止把历史研究信息冒充当前项目事实。
- `4ffe3c6`：WP6 产品接受检查点。
- `e8966d5`：manuscript/Office 桥接验收修复。
- `53f2ed6`：可配置 provider/model/thinking/effort 与 fallback 设置基础。

## 5. 本阶段实际完成了什么

### 5.1 配置能力

已有设置页允许用户选择主 provider、model、thinking、reasoning effort，并配置有序 fallback。源码按当次请求把设置冻结到内存链，不在任务进行中漂移。链顺序来自当前设置；没有把某个固定顺序硬编码进 wrapper。

产品 Goal 的默认推荐是：本地 MTPLX `Youssofal--Qwen3.8-Flash-Next-MTPLX-Optimized-Speed / medium` 为主，之后 `opencode-go/deepseek-v4.1-flash:max`，再到 `cms-router/deepseek-latest-cloud:max`。当前运行时 settings 文件有未提交改动，因此接手时必须读取实际设置，不能仅凭 Goal 假定机器当前已经按该顺序保存。

### 5.2 已接入入口

- 竞品资料 AI 分诊：提交 `a953fe0`。
- 企业语料分析：提交 `3d26ddb`。
- 当前批次：事实提取和写作预填，提交 `fb7e6ad`。

### 5.3 故障切换合同

允许切换：HTTP 408、429、500、502、503、504，传输失败，HTTP 200 但有效正文为空。

终止并显式报错：400、401/403、配置/鉴权错误、无效 JSON/内容合同失败、实际模型身份与预期不符，以及其他未声明错误。每条 provider 只做一次底层尝试。成功后 provider/model 指向真正完成调用的路由；事实提取还持久化 profile、chain、depth 和 reason。

### 5.4 兼容与恢复

- 旧无链任务继续使用旧 route identity/analysis ID，不改写历史。
- 可选 fallback 缺失、禁用或重复时跳过，不阻断健康主模型。
- 写作预填没有可用 AI 链时保留确定性预填，不把页面变成 500。
- timeout 写入会广播给链内全部 provider。
- wrapper 每次运行先归零 active route 和 fallback reason，避免上次状态污染本次审计。
- 生产链只接收 `OpenAICompatibleAiProvider`，防止手工包装的通用 provider 绕过实际响应模型核验。

## 6. 独立会商与测试证据

### 6.1 交互 fallback 会商

任务：`mw_protocol_v3_interactive_fallback_review_20260923`。

- 路由：`zcode / GLM-5.3-Flash / max`。
- session：`sess_b561bbbe-5075-4299-86de-b03c7792183d`。
- 同一 session 三轮，1018.172 s + 222.549 s + 360.124 s；没有 fallback。
- review：`reviews/codex_conference_mw_protocol_v3_interactive_fallback_review_20260923_review.md`，SHA-256 `439dd26f23473a321753999f02c6e496b81cc53f49fa9e946b1a4a6221640f30`。
- metrics：`metrics/mw_protocol_v3_interactive_fallback_review_20260923_conference_metrics.md`，SHA-256 `f99f1159767f80c595ff5968d4695ce6c9e2ceebe2c7dc3093ae9a14995f7389`。
- review-gate 与 validate-conference 均通过。

reviewer 首轮发现空响应分类、超时传播、prefill 500、wrapper 信任和跨运行状态五类问题；均已修复。最终 reviewer 结论是 fallback chain 没有剩余发布阻断缺陷。

### 6.2 测试

- 交互模型相关九文件矩阵：297 passed，17 条既有 deprecation warnings。
- `tests/protocol_v3`：2608 passed，1 条 Python 3.14 tar future behavior warning；日志 `/tmp/mw_protocol_v3_interactive_fallback_final_20260923.log` 的 SHA-256 为 `caf9e66fbb2ecf23289af30e5b308825a6331d8b97c86c4557b434c6aa59ace2`。`/tmp` 日志不作为长期制品，结果已经写入 review、复盘和 checkpoint。
- 受影响 Python 文件 `py_compile` 通过；选定 diff 的 `git diff --check` 通过。

三条陈旧测试已按当前权威升级：prefill 32768→65536、full-draft v0.9→v0.11，并补齐 v0.11 的 `gap_items` fixture。没有降低 gate、xfail 或删除负向 fixture。

## 7. 当前没有完成的范围

1. MTPLX 11234 当前没有 listener；没有真实验证本地 Qwen 的 endpoint identity、结构化长输出、速度和质量。
2. Protocol v3 的 WP6 仍未完成：V01/V04/V06/V07、A01–A26/V01–V08/B01–B12 中未关闭项、三个差异研究的完整真实旅程、宽屏浏览器、原生 Word 保存重开、逐章医学/统计/安全接受。
3. authoring prefill 尚未保存与 fact intake 同等详细的 fallback profile/chain/depth/reason；全链失败只留下最后一条明确失败，不含完整尝试轨迹。这是审计增强，不是当前错误输出。
4. 一条顶层准备阶段测试仍期待旧的逐批暂停；当前产品已改为非科学批次自动连续排空。不要为了旧断言退回停停走走。
5. 全仓环境仍有历史可选依赖/旧脚本债；本批没有恢复 `jsonschema` 或已删除的历史翻译脚本。

## 8. 当前工作树与保护边界

提交后工作树仍有 5 个 tracked dirty 和约 65 个 untracked 条目，均为本批开始前或运行验收留下的内容，本次没有 reset、clean、删除或提交：

- GenOffice 构建产物：旧 hashed JS 删除、`index.html` 更新和一个新 hashed JS。
- `runs/mw_protocol_v3_unified_tests_20260919/e2e_runtime/` 下 3 个运行时设置/日志文件变更。
- 多个 SQLite backup、artifact/dispatch-lock/office-artifact 目录、WP6/three-study 运行证据、截图和服务日志。
- 一个未纳入本批的旧 `mw_protocol_v3_model_fallback_review_20260923` conference 草稿及 manifest。
- 隔离运行时存在未跟踪凭证文件；不得读取内容、提交或复制到 handoff。

暂停时仍观察到既有 Vite 服务进程监听相关开发端口（5199、5187、5188 的长期进程）。这些不是本批启动，也没有擅自停止。没有 pytest、workflow guard 或 conference runner 在途。不得把这些服务当成当前任务仍在运行的证据，也不要在未确认所有者前终止。

## 9. 精确恢复步骤

1. 读取最新全局/项目 AGENTS、0922V2 `00_START_HERE.md`、Goal、Trellis checkpoint 和本 handoff。
2. 运行 `git fetch` 后核对 `HEAD`、`origin/main` 和 dirty；保留上述未提交内容，不使用 reset/clean/`git add .`。
3. 检查是否存在在途 logical work key、durable job、conference/runner handle；不要因几分钟无输出重派。
4. 检查 11234 是否监听。若可用，做最小的 exact model identity、429/空响应合同和一条长结构化输出探针；密钥只在现有解析链和内存中。若不可用，记录并继续不依赖 MTPLX 的 WP6。
5. 从 Trellis 的 WP6 未关闭项继续：优先 V01/V04/V06/V07 与三个独立 study/project/run/document/SHA 的完整旅程；使用现有 manuscript/Office 为唯一当前稿。
6. 按批次构建，集中测试；不要恢复“改一处测一次”。真实浏览器用 ego(lite)，前端遵守 Kangzhe design 3D 和宽屏高信息密度要求。
7. 最终必须经过真实产品模型、真实 API/SQLite、浏览器、原生 Word 保存重开和逐章医学接受。局部测试、包生成或 reviewer PASS 都不能替代产品完成。

## 10. 禁止重做或改写的阶段

- 不重放终态 v0.9 job，不先启动整稿 v0.10。
- 不应用 9 月 21 日旧 source overlay。
- 不重复检索、AI 分诊、下载、OCR、翻译或五个失败项。
- 不触碰 live 8910、医学监查、共享 runtime、外部 SOP 或只读 plan-upgrade。
- 不把旧项目方案、公司语料或 reviewer 意见自动升格为当前项目事实。
- 不删除历史 immutable rows、runs、logs、evidence 或现有 dirty。

## 11. Goal 原文快照

以下内容逐字来自当前 `GOAL_PROMPT.txt`：

```text
持续完成医学写作Protocol v3个人使用产品，面向懒惰、视觉敏感、不熟悉计算机和AI的资深医学写作人员：AI整理来源、给选项和推荐、写出有实质内容的完整初稿，用户主要点选、确认关键科学问题并少量修改，最终得到格式标准、内容有据、可进入申报审核的研究方案。工程验收和AI审阅不替代专业批准。

实施区：/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313。当前执行任务01a0c203-4db6-74f0-bafd-5b32c28c7fdd，owner按用户选定gpt-5.6-sol:medium。本轮入口：/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/plans/protocol_v3_0922V2_execution/00_START_HERE.md；依次执行新PRD、设计、Plan、执行规则、WP0–WP6及集中验收。以最新用户指令/AGENTS/当前源码与证据处理差异。不要从r42/Task2.1/3R.4重启，不应用9月21日旧source_overlay，不直接重新运行v0.9或先加Study A关键词跑85章v0.10。当前核查基线acf6d8341563d56946f934dfdac65c76997e36e3，接手时核对漂移与他人dirty。

WP0消化已有接线证据，只补缺失或漂移；WP1–WP5连续实现，普通完成只写Trellis/checkpoint和简短commentary，然后推进依赖已实现的下一项，不阶段性暂停、不反复结束后等用户说继续。Trellis是唯一动态状态，不另造管理系统。只有必须用户决定的科学取舍/Ⅰ期模板权威/真实生产激活或cutover/用户明确扩大第三方互操作范围才准备具体问题与推荐；独立可做工作继续。压缩恢复从checkpoint与文件系统重锚定。

开工、压缩恢复、重要范围变化、派发前、重复失败/路由异常及长任务中适度核查 /Users/smkzw/.codex/AGENTS.md；有变化再读，不机械固定全文轮询。执行与会商按当前批准manifest和guard/runner的实际触发条件，具有清晰独立边界和收益才委派；不强制多worker、额外chair、每包会商。独立审阅只读冻结产物与原始来源，owner负责最终接受。初始化不是派发；保留实际路由/effort/终态/工具证据，不能伪报审阅完成。

保持适配超长任务的runner hard wait，用同一handle/完成事件分段等候，短yield和几分钟无输出不等于失败；不取消健康任务，不因慢而重派/换模型。恢复前查logical work key、已完成阶段和unknown_outcome，同模型兼容恢复优先，明确失败或验收不合格后才按manifest允许fallback。产品前端也不得把观察预算耗尽的running显示为生成失败，应保留job并继续观察/恢复。定期给用户实质进度，不重复无变化轮询。

严格控制过度设计：复用React/FastAPI/SQLite/StudyDefinition/durable jobs/GenOffice及标准库；无明确当前消费者不增加框架、服务、通用引擎、审批库、第二正文库。现有manuscript/Office链拥有唯一当前可编辑Word；摘要/从零入口的来源和已确认设计通过薄适配汇合，full-draft是候选生产者，旧章节库保留必要历史/兼容，不长期双写同步。人工Word与候选/来源语义记录分开，下载不重生成覆盖人工稿。

构建完成前不写阶段性测试、不改一处测一次，不强制逐任务TDD/全量回归/浏览器回归。WP1–WP5默认读源码、受影响定义和diff；任务implemented即可推进。只有真实故障阻塞且源码检查不足，或完整批次必须编译才能继续集成时，记录原因和预期信号后做最小诊断并返回构建。WP6集中执行全部A01–A26、V01–V08、B01–B12；失败按根因族批量修复、重测受影响组，不为控制流重复调用真实全稿模型。减少过程测试不降低最终科学性/原生工件验收。

带缺口工作稿：关键设计确认后有依据正文先进入真实编辑，非关键缺口可定位并能持续处理；正文与缺口/决定可同章并存，不把空章标complete或删章伪完整。技术有效、工作稿可接收、科学待定、正式就绪分开判断但不建立四套状态机。最终申报就绪稿没有未处理内容缺口、虚构引用或AI/工程过程句；合法签字空白保留。

用户已批准已批准且确认适用于当前项目的公司SOP一次项目级确认后用于常规运营起草。需记录真实文件版本/批准状态/适用范围，变版按影响处理；这不等于任何具体SOP已在项目生效。旧项目方案只参考；剂量、安全、统计等关键选择仍单独确认，不逐段再批。冻结轻量来源manifest，证明IB/项目资料实际进入生成输入；引用存在/hash相同不等于支持具体断言，区分资料确缺、存在未检索、项目未定和映射失败。

八类高影响决定按研究适用性逐卡明确人审：主要终点、estimand及ICE、样本量假设、对照、NI界值、期中/alpha、剂量、核心人群。推荐默认预选但不自动批准，不强制10字理由。成组目的/终点原子确认；确认已提交而入队失败时恢复后续，不重复问用户。局部补写只更新受影响章并组成可用整稿，保留原来源和人工编辑。estimand按同一事件的具体策略判断，不按标题/关键词断言冲突，也不由写作层替用户选策略。

前端按kangzhe-design-3d当前适用规范，充分利用1440/1920/2560宽屏：真实文档为主，目录/研究设计/证据/问题并行，紧凑留白、逻辑bullet、清晰主动作；UI>=12px、正文>=14px，关键路径点击<=20、必填自由文本<=5，不能删除科学确认凑数。浏览器用ego(lite)。保留已实现双栏/Office集成，补真实问题，不重建一套展示稿。

真实Office保存必须验证persisted/operation/hash/revision；坏回执不能报已保存，n回执不清n+1输入；unknown保留原操作与可下载缓冲。核对基于实际当前DOCX字节，零覆盖不报一致、模型失败不挡保存。局部AI保留对象结构、非目标不变和真实撤销；文献可选择插入、编号、维护文献表并保留其位置格式；证据ID/表格REF不算引文。

模板仍为TP-MA-07清洁版v2.0；标题/叶/合同/实际文档节/生成目标口径分别映射，不改expected凑数。集中验收包括差异化2+1研究和盲测、真实产品模型、真实API/SQLite/浏览器、原生Word改后保存重开、字段/分页/当前版本保真、全文逐模块医学核查。渲染器要保留上游base及必要dirty patch和源码，使bundle可重建；不要只提交minified结果。eCTD仅按实际文件/元数据就绪范围交付，不冒称正式sequence已验收。

产品综合AI默认优先本地MTPLX的`Youssofal--Qwen3.8-Flash-Next-MTPLX-Optimized-Speed`、思考强度medium；仅在限流、超时、服务不可达、服务端错误或空响应时，依次fallback到`opencode-go/deepseek-v4.1-flash:max`和`cms-router/deepseek-latest-cloud:max`。内容/合同校验失败、模型身份不符或策略不允许时不得静默换模型。前端允许用户选择provider、model、thinking和reasoning effort，并可调整有序fallback链；每次实际调用持久化effective provider/model/effort、fallback层级和原因。凭证仅经现有解析，不写prompt/checkpoint/trace/registry/日志/交付包。OCR和翻译走现有共享oMLX gate/lease心跳，保留已完成上游，不重跑旧分诊下载OCR翻译与5失败项。

个人使用不以PyMuPDF边界讨论阻断、不新增纯安全工程或专项安全测试；旧阶段约束阻挡实施且不影响科学性可评估后记录替代。保留科学准确、数据不丢、操作幂等等功能义务。禁改live8910/医学监查/共享runtime/外部SOP/只读plan-upgrade，不清库造绿、不丢dirty、不擅自生产切换或清理历史。任务包/部分测试通过不等于产品Goal complete。

用户明确无损暂停时停止新派发，保留目标原文/文件hash/当前dirty/在途handle/操作身份/终态或未知结果/会商lineage/下一安全动作，等待指令不自动恢复。全部授权产品构建、集中验收、复盘和交付真实完成后才结束目标；没有必须用户决定的阻塞时持续推进。
```
