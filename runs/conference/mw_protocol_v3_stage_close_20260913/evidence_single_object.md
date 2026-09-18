全部证据收集完毕。29/29 哈希核验通过，后端接线零属性名错误，前端状态机发现 2 个 P1 级缺陷与多个 P2 欠项。现在提交完整会商报告。

# 会议输出：mw_protocol_v3_stage_close_20260913 - evidence_single_object

## 输出

### 0. 审阅方法与证据基线

- **哈希核验**：`runs/conference/mw_protocol_v3_stage_close_20260913/artifact_manifest.json` 全部 29 文件 SHA-256 实测 **29/29 匹配、0 缺失**（工具核验，非目测）。审阅期间未修改任何被审文件。
- **相邻定义核对**（manifest 外、链路必需）：`events/unit_of_work.py`、`storage/sqlite.py`（UoW 属性/CAS）、`storage/selected.py`、`graph/runtime.py`（start_run/read_events/proposal_outcome）、`canonical/hashing.py`、`agent1/research_seed.py`、`agent2/clinical_worker.py`、`agent2/input_context.py`、`agent3/{pinned_sources,source_material,subgraph}.py`、`registries/{applicability,chapters,fact_bindings,ordered_draft}.py`、`application/service.py`、`events/models.py`。
- 全程只读；未运行测试、未起服务、未浏览器、未产品模型调用。以下所有 PASS 均为**源码级核验通过**，不等价于运行通过。

### 1. 总体裁定（按合同审计面）

| 审计面 | 裁定 | 关键证据 |
|---|---|---|
| 覆盖输入编译 | PASS（源码） | `manuscript_request.py:41-78`：先 `manuscript_preparation_view` 全载体计划、`all_applicable_inputs_ready` 门禁；逐章 `prepare_study_chapter` 服务器端编译；共享材料跨章全等校验（`manuscript_shared_material_mismatch`）；`chapter_requests()` 用 `{**shared, **chapter}` 逐字节重建原请求（与 `prepare_chapter_draft` 的 canonical_json 序列化参数一致，hash 恒等） |
| 全章 child 恢复 | PASS（源码） | `manuscript_coordinator.py:64-116`：进度由全部 child 派生（`complete_candidate` 要求全部适用章 `needs_content_review`+`valid`），注册图仅存身份；`graph_run_unknown` → 补 `not_started`；resume 串行、健康/unknown child 不换身份重派 |
| source identity | PASS（源码） | 闭环成立：`PreparedSeedRequest` payload 即 source_intake；`regimen_input_context`（`input_context.py:11-28`）的 `source_intake_sha256 == seed.input_sha256`（两者序列化参数逐项一致，`hashing.py:55-67`）；`manuscript_sources.py:73-76` 强等 study 存储的 `research.input_context`；`source_preparation.py:78-82` 从 run 存储重建同 hash seed；`manuscript_request.py:47-50` 与 `application/service.py:764-766` 双重核对 |
| API 默认 mount | PASS（源码） | `composition.py:320-347`：sources/chapters/manuscripts/documents 五路由全部默认懒挂载；`ManuscriptDocumentService` 单例持有懒 UoW 工厂；admission gate 保持项目级 404 信封；`product.py:43-63` factory 全局锁懒加载 |
| UoW CAS/event | PASS（源码） | `manuscript_documents.py:53-91`：事务内二次查重（`_receipt` 重扫+`verify_event_integrity`）→ revision/hash CAS 预检 → `assemble` → `build_and_apply`。`EventSourcedUnitOfWork.build_and_apply`（`unit_of_work.py:334-380`）签名/kwargs 完全匹配；`SqliteUnitOfWork`（`sqlite.py:2448-2510`）具备全部所需属性名，`BEGIN IMMEDIATE` 使预检+写入原子串行 |
| PROPOSED 医学绑定 | PASS（源码） | `protocol_v3.py:815-824`：仅非 PROPOSED 块强制证据/准入非空；`852-857`：CONFIRMED/FROZEN 文档强制全部块已绑定。`manuscript_document.py:53-54` 恒写空链接+PROPOSED；事件 `acceptance_scope='working_draft_only'`、reason 明示"尚未完成医学和Word验收"；来源证据 `quality_score=0`+`not_assessed`（`source_material.py:51-55`）不伪造准入 |
| 前端 save 先持久 intent | PASS（源码，含 P1 缺陷） | `ManuscriptWorkspace.jsx:42-47,127-150`：`remember` 在 dispatch 前写 localStorage；先 recover 再 save；`loadSavedDocument:109-116` 恢复回执后**另读**当前 SemanticDocument，不用历史回执冒充当前版本 |
| GET 恢复和版本读取 | PASS（源码） | 客户端 13 个新方法与后端路由逐条对上（含 `/save/prepare`、`/save`、`/save/recover`、`manuscript-sources` 五条）；`get_semantic_document`（`service.py:779-799`）返回 current 文档+`study_binding_status` |
| 生命周期/显示当前版本 | PARTIAL | 见 P2-2：`study_binding_status` 后端已算、前端未消费；研究变更后旧稿仍以"当前文档"展示 |
| 品牌风险语义 | PASS（源码） | `RegimenProposalCard.jsx:191`"监管答辩级·需确认/确认记录"标签在位（owner 已纠 E09 worker 误删）；`kangzheProtocol.css` 及 5 个 CSS 统一 `--kz-orange:#FF9900/--kz-yellow:#FFCC00`，正文 16px/辅助 14px/圆角≤8px；`logo_bot.svg` 本地资产已接 `ProtocolIntakeWorkspace.jsx:1,174`。**视觉终验 UNVERIFIED**（ego 浏览器未跑，E09 pending） |
| 真实类型/字段名/缺参 | PASS（源码） | `SemanticBlock`/`SemanticDocumentRevision` 构造字段名与 contracts 逐一对齐；StableId 模式验证过全部新 ID 形态（`manuscript-block:`、`manuscript-save:` 等，长度 75-82≤160）；`chapter_contract_hashes` 非空且按构造唯一（DependencyBoundModel v1 要求） |
| not_applicable/目录一致/table decode | PASS（源码） | 计划与协调器双处跳过 `not_applicable` 但保留展示（前端"本研究不适用"）；`chapter_order` 用 `body_child_index`（`template_runtime.py:78-83`）非文件名排序；表格以 `semantic-structured-table.v1` 存 content，前端 `savedChapter:20-29` 解码，坏内容降级 `unreadable` 不显示 JSON 原文 |

### 2. 缺陷清单（P1/P2/P3，含触发、影响、最小修复、阶段归属）

**P1-1 保存意图 (saveIntent) 在版本竞争 409 后永久毒化（重复保存/并发审计面，本阶段核心功能缺陷）**
- 证据：`ManuscriptWorkspace.jsx:132-141`——`saveIntent` 一旦生成即被 `remember` 持久化并永续复用；`saveCompleteDraft` 无任何路径重新 `prepareManuscriptSave` 铸新 `operation_id`/`expected_revision`。后端 `manuscript_drafts.py:41-45` 将 `manuscript_document_revision_changed` 回 409。
- 触发：两个标签页/两次保存竞争同一文档 revision（一胜一败），或保存后文档被其他路径推进 revision。败者的 intent 因 `expected_revision` 过期永远 409；刷新页面也从 localStorage 读回同一毒化 packet（`savedValue(key)`），`/save/prepare` 已不再被调用。
- 影响：用户被锁死在"核对并完成原稿保存"→409 循环，无自助恢复路径。
- 最小修复：捕获 `reason?.status===409` 且 detail 指向版本竞争时，清空 `saveIntent`（保留原 intent 于历史 key），重新走 `prepareManuscriptSave` 并以新 `operation_id` 重试一次。
- 归属：**建议本阶段修**（前端局部小改）。用户已禁阶段测试，未测修改有回归风险——见有界问题 Q1。

**P1-2 研究变更后 packet 毒化循环（study_sha 过期无新稿入口）**
- 证据：`ManuscriptWorkspace.jsx:58-72,152-173`——`studySha` 只在 `begin()` 读取一次并存入 packet；`finishSources` 用它 `prepareManuscriptDraft`，study 已变 → `manuscript_request_changed` 409（`manuscript_drafts.py:54-55`）；`resume()` 对 sources-completed 状态不做任何事，refresh 后轮询再触 409。`begin` 按钮仅 `!packet` 时存在。
- 影响：研究在资料准备期间被确认修改后，整稿工作区死循环报错，无"开始新整稿"出口（除手清 localStorage）。
- 归属：**下一阶段欠项 #3**（"研究改变时明确新稿入口"已在 `plans/mw_protocol_v3_next_stage_20260913.md:9` 明列）。本阶段暂停说明中应向用户披露该已知死端。

**P2-1 整稿 blocked 静默停滞**
- 证据：`manuscript_coordinator.py:87-88` 可返回 `status='blocked'`+`can_resume=False`（某适用章终态失败且不可恢复）；`ManuscriptWorkspace.jsx:211-218` 无 blocked 分支——状态文案停留在"正在撰写方案"，且 `(error || job?.can_resume)` 均假 → 无任何按钮。
- 最小修复：对 `job?.status==='blocked'` 显示"本次写作已停止，可阅读已生成章节"，并列出失败章节标题。
- 归属：下一阶段（生命周期）。

**P2-2 `study_binding_status` 未消费**
- 证据：`service.py:791-798` 专门计算 current/changed/missing；`ManuscriptWorkspace.jsx:109-116` 取整个响应但渲染（216 行）只读 `document.revision`。研究后续演进后，旧稿仍显示"完整工作初稿已保存，第 N 版"而无失效提示。
- 归属：下一阶段 #3（设计 v1.4 与 next-stage 已列）；改动极小（一条状态文案），可与 P1-2 同批。

**P2-3 源准备失败无 UI 重试入口**
- 证据：后端 `source_preparation.py:119-142` 与 API `manuscript_sources.py:105-122` 已实现一次显式 retry；客户端 `protocolWorkspaceApi.mjs:148-150` 有 `retryManuscriptSources`；但 `ManuscriptWorkspace` 全文不调用，`resume()` 仅处理 `can_resume`（failed 态为 False）。本地读取瞬时失败后用户无出路。
- 归属：下一阶段；修复=读 `can_retry` 时给一个重试按钮（带新 `retry_decision_id`）。

**P3 项**（记录不阻塞）：① `remember` 写入的 per-run localStorage 副本（`ManuscriptWorkspace.jsx:45`）无任何读取方，死写；② 组装期内部不变量错误（`manuscript_shared_material_mismatch`、`manuscript_document_fact_binding_missing` 等）未入 `checked` 映射，落 422"请求内容与当前工作台要求不符"，文案误导（实为服务端不变量，应 5xx 或专属文案）；③ 真实 CAS 竞争（`RevisionConflictError`→`MutationAbortedError`→500 未知信封）与预检 409 共用"研究内容或所选资料已变化"文案，版本竞争语义区分不足（design v1.4 要求分别处理；因 BEGIN IMMEDIATE 串行化实际难触发）；④ `crypto.randomUUID()` 需 secure context（localhost/HTTPS 可用，file:// 会崩，与既有架构约束一致，仅备注）。

### 3. PROPOSED 空准入语义与 confirmed validator 兼容（独立评估）

- 允许空准入的设计边界在 contracts 层已闭环：`SemanticBlock` 仅对非 PROPOSED 强制链接（`protocol_v3.py:820-823`），`SemanticDocumentRevision` 仅对 CONFIRMED/FROZEN 强制全块绑定（`852-857`）。assemble 恒定 PROPOSED，正式确认文档无法夹带未确认块——"工作稿"与"验收稿"的合同分离成立，且不是靠前端自觉。
- DependencyBoundModel v1/v1_1 兼容：assemble 用默认 v1（`chapter_contract_hashes` 全量非空元组），序列化器按 schema 弹出对应字段（`protocol_v3.py:289-296`），`_receipt` 的 `model_validate` 往返成立；不强制升级 compact 格式，历史兼容正确。
- `manuscript_request.py:64-67` 的 `fact_provenance` 已按 canonical+legacy 别名键集存证（且逐键核 `study.facts` 存在性）——这实际是章节级事实读集的雏形。**推断**：下一阶段 #1 `confirmation_binding` 应复用同一别名映射实现，避免出现第二套读集语义（见有界问题 Q2）。

### 4. 下一阶段计划审阅（顺序/遗漏/≤20 点击）

顺序（确认语义→七卡→生命周期→编辑→QC→Word→统一测试）与 design v1.4 的依赖方向一致，无倒置。建议增补：

1. **把 P1-1 的"重复保存/版本竞争恢复"作为 #3/#4 的显式验收用例**（当前计划只写"当前版本 CAS、同 operation 回执"，未写竞争后的客户端自愈）。
2. **表格 decode/encode 提为共享模块**：前端 `savedChapter`（`ManuscriptWorkspace.jsx:15-30`）与后端 `assemble_working_manuscript`（`manuscript_document.py:42-48`）各持一份 `semantic-structured-table.v1` 逆操作；#4 受控编辑表格时必须继续走同一 schema 并重算 `content_sha256`，双份实现易漂移。
3. **Word 分母来源**：block 上的 `substantive_content_contract_id` 是 ID 无 hash 绑定；Word 验收分母应从 ChapterContractV2 合同直接派生（`chapter_contract_hashes` 已入文档版本可作对账锚），不要用 block 字段当分母。
4. 点击预算（推断，未实测）：正常路径（资料→基础信息→给药→生成 1→保存 1→阅读）远低于 20；当前超支风险全部在异常路径（P1-1/P1-2/P2-1/P2-3 的重试与死端），修复合并到统一测试期实测。

### 5. 经验教训（复盘）

1. **后端复用模式有效**：新链 5 个 API/2 个协调器/1 个文档服务对 UoW/graph/CAS/contracts 的全部属性名、签名、错误码零错误——`original()先找回、fresh()才新建`、`run 身份自校验`（重建→hash→run_id 比对）两个模式在 seed/chapter/manuscript 三层一致复用，值得保留为标准模式。
2. **前端 localStorage 状态机是缺陷集中区**：本次全部 P1/P2 都在前端恢复路径（毒化 intent、死端状态、未消费的后端语义字段）。后端已把 `can_retry`、`study_binding_status`、`blocked` 算好，前端没接——下一阶段应把"后端新增状态字段必须同步前端消费"写进接线清单。
3. 未测试接线的会商价值在本轮成立：29 文件全链相邻定义核对发现了纯读被审文件无法发现的属性名/签名类问题（本轮未发现，但方法上必须核）。

### 6. 无损暂停与清理建议

- **不可删**（证据/历史/用户 dirty）：`runs/`（全部会商回执与 owner_receipt_summary）、`output/playwright/` 截图（验收证据）、`reviews/`、`conference/`、`.trellis/`、`plans/`、既有 tests/fixtures、git 106 个 modified+628 个 untracked（chapter contracts/skills/qc schemas 等新资产与用户改动）。
- **确定可再生、非证据缓存**（建议暂停时清理，本会商未执行任何清理）：`__pycache__` 目录（实测 180 个）、`.pytest_cache`（1 个）、`frontend/node_modules/.vite`。仅此三类；浏览器 profile、SQLite 库、artifact store 均不在可再生之列。
- 暂停检查点：Trellis checkpoint 已记至 stage_close 初始化；建议 owner 把本次会商结论与 P1 清单补记后再执行暂停（由 owner 决定，本角色不写）。

### 7. PASS/FAIL/UNVERIFIED 边界与不确定性

- 本报告全部结论为**只读源码级**核验；无任何执行、测试、浏览器、真实模型验证。源码支持≠运行通过。
- UNVERIFIED 清单：E09 视觉终验（ego 浏览器）、整稿链真实 HTTP/真实模型行为、SQLite 并发竞争实测、Word 导出、IME/编辑（未实现）、康哲视觉在 390/1440 实渲。
- 不确定项：`json.loads` 大 payload 的整稿请求性能（111 章共享全文源材料，单 request 可能数 MB——仅记录，无实测依据）；`crypto.randomUUID` 在最终部署上下文的可用性。

### 8. 对 Codex 的最重要异议、决策点与有界问题

1. **Q1（决策点）**：P1-1 是否允许暂停前做前端小修？我的安全默认是**只记录不修**（用户明令禁止阶段测试，未测修改有回归风险；且该缺陷触发需要多标签页竞争，单用户正常路径不触发）。若 Codex 裁定修复，改动应限于 `saveCompleteDraft` 的 409 分支。
2. **Q2**：下一阶段 #1 的 `confirmation_binding` 是否复用 `manuscript_request.fact_provenance` 的 canonical+legacy 别名键集作为共享读集实现？若另建映射，需要在计划中显式声明两套语义的对账规则。
3. **异议（对暂停范围）**：P1-2/P2-1/P2-2/P2-3 均会让用户在暂停期间遇到死端或误导文案；建议暂停说明中向用户明示"整稿工作区在研究变更/源读取失败/写作中断三种情况下需要等待下一阶段"，而不是笼统说"整稿保存与阅读已可用"。
4. **对 next-stage 计划的补充请求**：将 §4.1（竞争恢复验收用例）与 §4.2（表格 codec 共享）两条写入计划，避免 #4 编辑实现时漂移。
