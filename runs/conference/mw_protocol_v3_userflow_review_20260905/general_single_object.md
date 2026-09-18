所有证据已收集完毕。正在撰写完整的会议输出。

---

# 会议参与者输出：mw_protocol_v3_userflow_review_20260905 - general_single_object

## 边界核查

- 全部工作在 runner 绑定的工作区 `.` 内完成；未读写生产路径、live workbench、凭证、home 会话。
- 未运行服务、浏览器、产品模型、Word/OCR/翻译；未修改任何源码/测试/计划；无 git 写入；无网络访问。
- 未触碰 Task1R.1 存储修复工作流的活动文件（`protocol_workflow/storage/selected.py`、`apply_repository_hygiene.py`、`build_frozen_authority_manifest.py` 及对应 fixtures/tests）；本审阅读取的 `medical_writing_durable_jobs.py` 属旧链 durable store，不在该所有权流内。
- 新增证据仅写入授权目录 `runs/mw_protocol_v3_userflow_review_20260905/`（`reproduce_regex_and_hash.py` + 输出 + `reproduce_vacuous_screen_guard.txt`）；未写 runner 报告路径，完整报告在此返回。
- 解释器使用授权来源：`runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python` 与 PATH 中的 `node`（纯模块导入，无副作用）。
- 不主张最终临床、法规、视觉、浏览器或用户验收；Codex 保留最终权威。

## 独立工作成果

审阅路线：Plan v2（含 §5 Phase 5R/6R/7R 与 UI1 硬指标）+ 已批准附加计划 → 以基线 review 为假设而非事实 → 独立追踪 App.jsx WritingPage 主线（建项/恢复/全文初稿/采纳/修订/导出）实际接线与后端 `medical_writing_full_draft.py`、`main.py`、`medical_writing_durable_jobs.py`、`ai_task_runner.py`、`protocol_workflow/api/router.py`、`durableJobState.mjs`/`useDurableMwJob.js` → 两项确定性实际代码复现（实际模块导入）。

### 发现（按优先级，≤8）

**F1（P0，主线阻断，已确定性复现）全文初稿"生成失败后永久死锁"复合链：草稿标记正则误报合法 GCP 措辞 → 任务 FAILED 不可重试 → 重提交永远复用失败任务且 UI 无重试入口。**
- 证据链：`services/api/app/medical_writing_content_quality.py:45-46` —— `UNRESOLVED_DRAFT_MARKER_RE` 的分支 `(?:未提供|未给出|未明确)(?:具体|数值|正式)?[^。；，,\r\n]{0,18}(?:参数|数据|资料|数值|条目)?` 尾组可选，实际退化为"未提供+任意≤18字符"即命中；`ai_task_runner.py:2708-2715` 在生成时以此判 FAILED；`medical_writing_full_draft.py:425-427,533-534` 将其变为 `retryable=False`；`medical_writing_durable_jobs.py:303-332` `create_or_reuse` 对同 business_key 无条件返回既有任务（含 failed）；`main.py:7783-7787` 终态任务不唤醒；`App.jsx:11404-11413` 全文初稿面板只有"生成"和"采纳"两个按钮，无重试。
- 复现：`runs/mw_protocol_v3_userflow_review_20260905/reproduce_regex_and_hash.py`（实际导入生产正则）确认附加计划反例"筛选前未提供书面知情同意者不进入筛选。"命中（这是入排标准标准措辞，AI 生成入排章节极可能包含）；"未提供既往抗肿瘤治疗记录者须复核后方可入组。"同样命中。
- 影响：用户主线"读完整初稿"在含此类合法措辞的候选上被硬阻断，且界面无出路（除非手工改动文档使 digest 变化）。
- 最小修复：(a) 修正该退化分支——尾组改强制或限定真实草稿话术语境，保留"待确认"等既有负向 fixture 全绿；(b) `start` 路由对 reused 且 failed 的任务转投 `/retry`（或在面板加"重试"按钮复用通用 jobs/retry 端点）；(c) 5R/6R 按 amendment 以"AI 预填理由+点选"替代静态字数/话术校验。属 legacy 缺陷但直接决定 v3 主线可走通，建议在 5R 前修 (a)(b)。

**F2（P1，已确定性复现）采纳前置哈希两侧语义不一致：目标侧对全部正文段落拼接计算，采纳侧只比较首段。**
- 证据：`medical_writing_full_draft.py:147-162`（`body_sha256 = sha256(_body_text(writable))`，`body_block_id = writable[0]`）vs `:707-714`（`current_text` 仅取 `body_block_id` 那一块的文本再比对）。`_body_text` 为 "\n" 拼接所有非空 paragraph（`:77-82`）。
- 复现：同脚本 A1/A2——两个非空段落、总长 20 字（<80 非实质）的章节成为 target，target 侧哈希≠采纳侧首段哈希，零编辑即抛"全文初稿采纳遇到正文变化"。触发面：任何 ≥2 个非空正文段且（拼接 <80 字或命中 `_PLACEHOLDER_RE` 如"见方案规定/不适用"独立子句）的章节——多段占位 scaffold 常见。基线 review 曾述及（其行号 :164/:710 与当前代码有偏移），本次在当前 HEAD 独立证实。
- 最小修复：两侧统一用 `_body_text(_body_blocks(blocks))` 表达式（或存逐块哈希清单）；保留 replay 幂等分支按新语义对齐。v3 侧维持整稿 SemanticDocumentRevision 事务采纳为目标形态（6R amendment 已登记）。

**F3（P1）采纳部分成功不可见：逐章保存后冲突 409，前端只报失败不刷新、不列已写章节。**
- 证据：`medical_writing_full_draft.py:689-730` 循环逐章 `save_working_copy`（幂等键 `full-draft-adopt:{job_id}:{section_id}`，重放安全），`:711-714` 抛 `StaleRuntimeStateError`；`main.py:7841-7842` 转 409 仅含失败章节；`App.jsx:10457` 预告"任一版本冲突都会停止并保留已审计结果"，但 `:10474` catch 只 set 失败消息，无 `refreshDocumentSession()`，已落稿章节在编辑器中保持旧内容直至手工刷新。
- 不确定性：重试采纳会经 replay 收敛（`:707-710`），故为"信息缺失+界面陈旧"而非数据损坏。
- 最小修复：409 payload 附 `adopted_so_far`/`replayed_so_far`（或改为事务式全成全败）；前端 catch 后强制刷新并列明已写章节。与 F2 同文件同函数，宜一并修。

**F4（P1，触发条件修正基线）任务定位器在"非终态失败"下被删除并误报失败。**
- 证据：`App.jsx:10444-10448` catch 无条件 `localStorage.removeItem(fullDraftStorageKey)`；导出同型（`:10592-10597`）。修正点：`useDurableMwJob.js:61-63` 轮询内网络错误被吞（continue），**不会**触发删除——基线"状态查询网络失败删除 locator"的触发描述不准确。真实触发是：(a) `pollDurableMwJob` maxLoops 耗尽而任务仍在跑（全文初稿预算 900ms×1200=18 分钟；106 叶/8=14 批的 v3 目标文档现实上可超时），抛出后 catch 删 locator；(b) 任务已完成但 `/result` 拉取失败（`App.jsx:10403-10406` `readJsonOrThrow` 抛出）同样删 locator。
- 严重度修正：因 `create_or_reuse` 按 digest 复用，输入未变时一键重点即恢复（已完成者无模型成本），**非永久丢失**；实际代价是"任务仍在后台/已完成却报失败"的误导与用户中途编辑致 digest 变化后的全量重生成成本。
- 最小修复：区分 `terminal_failed` 与 `polling_exhausted/transport_error`，后者保留 locator 并提示"任务仍在后台，可稍后恢复"；为 v3 目标文档把轮询预算按批数自适应。

**F5（P1，已确定性复现核心机制）修订事件回调的屏幕代际守卫为空转比较：与闭包捕获的旧 props 自比，检不出切换后污染。**
- 证据：`App.jsx:9552-9554`（submit）、`9659-9661`（cancel）、`9712-9714`（retry）、`9887-9889`（rewrite）均为 `isScreenGenerationCurrent(screenAtStart, projectId, selectedSection)`，后两者值是回调创建时捕获的 props。复现：`reproduce_vacuous_screen_guard.txt`（导入实际 `durableJobState.mjs`）——切换到 sec_2 后 as-written 守卫仍 true；对照用 ref 新值则正确 false。
- 后果（有界）：切换章节后旧链继续 `setRevisionJobs/setRevisionMessage`（`:9568-9582` 等），在新屏幕复活幽灵任务进度；`shouldBlockStartForOperation`（`:9811`）会阻止当前屏幕发起重写；`cancelRevisionJob`（`:9663`）可取消属于另一章节的真实任务。
- 重要边界（对基线的实质修正）：`activeThread` 按当前章节过滤（`:10757-10762`），候选卡与原子采纳（`accept-and-apply`，`:9836-9845`）不会被跨章节内容污染；项目切换因 `key={activeProjectId}`（`:15906`）重挂载，旧闭包 setter 落空——**基线所称"adoptFullDraft 延迟响应设置 B 页面成功提示/nonce/busy"在当前接线不可达**（该闭包无跨实例状态通道）。另 `useDurableMwJob` hook 本身零生产调用方（仅 `pollDurableMwJob` 与纯函数被导入，`App.jsx:144-164`），基线的"共享 hook 伪隔离"发现存在于死代码中。
- 最小修复：守卫改比 `revisionScreenGenRef.current` 的新值（或直接 `screenAtStart === revisionScreenGenRef.current`），并为修订流加 `fullDraftRunRef` 式计数器；F5 修复时同步补 A→B、A→B→A、卸载真实 hook 用例（amendment 6R 已要求，勿以纯函数测试替代接线验证）。

**F6（P1）身份接线：写作 mutation 全链无服务器可信 principal。**
- 证据：`App.jsx` 26 处硬编码 `actor: "medical_manager"`（含 startFullDraft `:10432`、adopt `:10461`、saveWorkingCopy `:10089`）；v3 `protocol_workflow/api/router.py:295-296,327-328` 直接转发 `body.actor_type/actor_id`。
- 与 amendment 一致：真实高风险确认必须绑定服务器信任身份，否则 5R 八类逐卡确认不能计为"人审"。最小修复：单用户本地会话 principal，服务器侧覆写 actor 字段；1R.5 跨项目/伪造 actor 负向 + 5R 确认门绑定内容 hash。不扩多租户平台。

**F7（P2，用户负担）≥10 字自由文本门 15+ 处与 10/11px 字号违反已批准体验决议。**
- 证据（代表性）：`App.jsx:5270,5510,8655,8702,10207,10719,11826,12119-12124`；`MedicalWritingSynopsisProjectIntake.jsx:588`；`MedicalWritingLiteraturePanel.jsx:174`；`LegacyAuthoringBootstrapPanel.jsx:438,487`；`StudySchemaEditor.jsx:369,590-591`；`MedicalWritingAuthoringJourneySetup.jsx:2281-2282,3235-3263,3610,3981`（含例外进入写作、适用性不适用理由、设计变更提交——后者在主线建项路径上）。CSS：`MedicalWritingAuthoringJourneySetup.css:30,62,130,140,178,213,223,378,404,431,439,495…` 10/11px 声明（body 硬下限 14px）。
- v3 要求 vs legacy：这是 legacy 现状；6R 新组件禁止复用，UI1 的"≥10字硬校验组件存在性=0"必须把这些模式（`length < 10`、placeholder 含"不少于10"）纳入 Playwright 计数对象。

**F8（P2，计划挑战）"≤15 关键点击"目前不可测量且算术上极紧，须先冻结计数规则。**
- 证据：全前端无任何 `risk_tier/风险分层/监管答辩` 实现（rg 零命中）——八类高风险卡纯属 5R 待建面；`frontend/src/features/medical-writing/protocol-workbench/` 仅 `protocolWorkspaceApi.mjs` 且零导入方——v3 前端未开始。算术：8 张高风险卡逐卡确认=8 次点击，建项/采纳初稿/导出≥3 次，剩余预算≤4 次覆盖上传、低风险整包、冻结等全部动作。legacy 的逐章冻结语义（`allRequiredSectionsFrozen`，`App.jsx:8472,10550,11109`）若平移入 v3 将直接爆预算。
- 建议：在 6R.5 gate 文本中先冻结计数规则——抽屉内点击计入、每张高风险卡单独计数、禁止多选合并确认、高复杂方案例外单独记录（amendment 已禁止藏抽屉达标）；冻结改为整稿确认语义或计入预算。

### 对基线 review 的修正汇总（挑战而非重复）

1. `adoptFullDraft` 跨项目污染（基线 P1）在当前 `key={activeProjectId}` 接线下不可达；真实缺陷移至修订事件回调的章节级空转守卫（F5）。
2. "共享 hook 伪隔离"针对的 `useDurableMwJob` hook 无生产调用方；需修的是 App.jsx 内联链路。
3. "网络失败删除 locator"触发条件不准：轮询内网络错误被容忍；真实触发是轮询预算耗尽与 result 拉取失败，且因任务复用可一键恢复，严重度下调（F4）。
4. "run_job 崩溃窗口重复调用模型"范围过宽：`_read_reusable_chunk`（`medical_writing_full_draft.py:370-394,511-529`）使已持久化 chunk 复用，重复调用仅限崩溃时在飞的单一 chunk（成本窗口，非正确性缺陷）。

### 正面确认（避免重复施工）

文件先行建项的 durable 任务模型（`MedicalWritingSynopsisProjectIntake.jsx:13-157`：终态集、recoverable、cancel、幂等键、"重试沿用同一导入请求"）语义健全；全文初稿/导出的卸载 runToken 失效（`App.jsx:10500-10502,10539-10543`）正确；生产路径原子 `accept-and-apply`（CAS+幂等，`App.jsx:9822-9845`）与 demo-only 分步写入的隔离（`:9992-9998`）边界清晰；采纳 replay 幂等（F2 修复后仍成立）。

## 证据与假设

- 已读（全量或关键段）：`../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md`、`plans/mw_protocol_v3_review_amendment_20260905.md`、`reviews/mw_protocol_v3_engineering_review_20260905.md`、`App.jsx`（7901-8330、9300-10110、10330-10660、10719-10790、11360-11415、15860-15910 及 import 区）、`useDurableMwJob.js` 全文、`durableJobState.mjs`（160-280）、`medical_writing_full_draft.py`（1-250、370-560、560-756）、`main.py`（7771-7880、10719-10815）、`medical_writing_durable_jobs.py`（create_or_reuse）、`ai_task_runner.py`（2660-2729）、`medical_writing_content_quality.py`（1-120）、`protocol_workflow/api/router.py`（270-345）、`MedicalWritingSynopsisProjectIntake.jsx`（扫描）。
- 确定性复现（实际生产模块导入，非复述）：`runs/mw_protocol_v3_userflow_review_20260905/reproduce_regex_and_hash.py|_output.txt`（9 项检查；F1 正则 4/4 目标句复现、F2 A1/A2 复现；输出中两行"FAIL"是我测试用例预期写错——"未能提供…"因含"能"字本就不匹配该词根、"未提供+19字"因 search 非全匹配仍命中——缺陷本身全部复现）；`reproduce_vacuous_screen_guard.txt`（F5 机制，实际 `durableJobState.mjs` 导入）。
- 假设与不确定性：(a) F2 复现用合成 blocks + 纯函数路径；基线 `reproduce_legacy_full_draft.py` 据载以服务+fake repo 复现同类，我未重跑（预算内选择独立证据）；(b) F5 的用户可见后果推演自代码闭包语义，未做浏览器验证（超范围）；(c) 行号为当前工作区 HEAD 快照，Task1R.1 并行流不改变这些文件；(d) F1 中"AI 极可能生成含'未提供'入排措辞"是推断，正则命中本身是已证事实。

## 风险、差距与验证需求

- F1 修复（正则收紧）必须保住既有负向 fixture 全绿（"待确认"等仍拦截），并新增合法上下文对照（amendment 已给出合成反例）；防止用"删检测"换"误报消失"。
- F2/F3 修复需回归"多段 hash 不一致"与"第二章过期前章已保存"两个既有反例（amendment 6R 行明确要求），并确认 replay 分支在新哈希语义下不误吞真实变更。
- F4 需为 v3 目标文档（14 批）重新核定轮询预算或改为 lease/事件驱动刷新；"任务仍在后台"话术不得引入 unknown_outcome 术语透出（amendment 用户语义）。
- F5 修复必须补真实 hook/组件接线用例（A→B、A→B→A、卸载），现有 `isScreenGenerationCurrent` 纯函数测试不足以证明接线（amendment 明令）。
- F6 在 1R.5/5R 前无服务器身份，任何"已人审"标记不可信；需伪造 actor 负向测试。
- 未验证项（超本位范围）：浏览器实际呈现、真实模型生成内容分布、Word 导出运行时、CSS computed style 实测（仅静态声明计数）。
- 与 1R.1 的边界：以上发现均在旧链/前端层，不依赖也不阻塞 SQLite 修复流。

## 推荐下一步

给 Codex 的建议（按序）：
1. 将 F1 排入 5R 之前的独立小修（正则退化分支 + failed 任务重试出路），验收=正则反例双向测试 + 失败后 UI 可再生成；这是主线"读完整初稿"的硬阻断。
2. F2+F3 同函数一并修（统一哈希表达式 + 409 附 `adopted_so_far` + 前端刷新），并登记 6R 整稿事务采纳对照。
3. F4/F5 登记进 6R（异步与恢复）gate 用例集；F5 的守卫改法（比 ref 新值）可直接写入 6R.1 合同。
4. F6 落入 1R.5/5R 身份负向；F7 模式清单交给 6R.5 UI1 计数器实现；F8 请 Codex 在 6R.5 gate 文本中先冻结点击计数规则。
5. 待 Codex 裁定的有界问题：(Q1) F1 正则修复归属——现在修 legacy（建议，两行级改动+既有 fixture 保护）还是并入 3R.7 术语/QC 权威重写？(Q2) UI1 计数规则（抽屉内点击计入、逐卡计数、禁止合并确认）是否按 F8 建议冻结进 gate 文本？(Q3) failed 任务重试出口做通用 jobs 面板还是全文初稿面板内按钮（建议后者，最小面）？安全临时路径：Q1 未裁定时先在 5R 用人工核对绕过误报句，不改检测器。
