# T17 第十轮会商审阅意见书

审阅者：架构+质量双视角独立复核
复核基线：`SOURCE_HEAD=6de4afb3e774d1c05fe000af2204a10c16a0c3c7`
证据来源（第一手，非转述）：

| 证据 | 路径 | 用途 |
|---|---|---|
| 现场产品库（只读） | `runs/mw_protocol_v3_unified_tests_20260919/e2e_test_mw.sqlite` | 运行/预约/章节级终态 |
| 导出产物 | `/tmp/t17_tester2/ted_t1_protocol_export.docx`、`iga_protocol_work.docx` | docx QC 复核 |
| 源模板 | `…/TP-MA-07 …_v2.0_20260905.docx` | 对照 TOC/图片是否被丢弃 |
| 代码 | 见各节 `文件:函数` | 根因定位 |

项目↔测试者映射（由 study_definition 适应症反查，**与聚合报告的假定不同**）：

| project_id | 适应症 | 建项(UTC) | 对应 |
|---|---|---|---|
| `proj_user_e3e097d072f0` | 活动性中重度甲状腺眼病 | 20:32 | tester2 |
| `proj_user_5f800b8408f7` | 特发性肺纤维化 | 20:31 | tester3 |
| `proj_user_520b0aa75b22` | 慢性痛风石性疾病 | 20:36 | tester4 |
| `proj_user_69d9156ab281` | 子宫内膜异位症 | 21:16 | tester1 |
| `proj_user_26ea92f426a7` | 子宫内膜异位症相关盆腔疼痛 | 20:34 | tester1 首轮（gemini 429 会话）遗留，同一缺陷 |

---

## 一、P0-A 初稿生成停滞 —— 判定：**真缺陷**（三测试者同因，代码+数据双证）

### 1.1 根因链（四环，逐环可验证）

**环 1｜模型输出常不合格，进入"结构纠正"分支。**
`chapter-validate` 对 `chapter-generate` 的输出做 JSON/Schema/引用校验（`agent3/subgraph.py:validate`）。现场数据里这不是偶发：

| 项目 | 派发章节 | 校验通过 | 需纠正 | 纠正派发失败→阻断 |
|---|---|---|---|---|
| tester2 TED（最终稿） | 7 | 7 | 0 | 0 |
| tester4 痛风 | 12 | 11 | 1 | **1** |
| tester3 IPF（第1次） | 7 | 6 | 1 | **1** |
| tester3 IPF（第2次） | 7 | 3 | 4 | **4** |
| tester1 内异症 | 8 | 6 | 2 | **2** |
| 首轮内异症遗留项目 | 7 | 2 | 5 | **5** |

**环 2｜唯一一次纠正派发异常 → `UNKNOWN_OUTCOME`（不可再派发）。**
`runtime/reservations.py:613-643`：派发已进入 RUNNING 后，任何异常（`TimeoutError` → `dispatch_timeout`，其它 → `dispatch_exception`）一律落 `UNKNOWN_OUTCOME`，**永不降级为 FAILED**。现场 19 条 unknown_outcome 全部 `error_code=dispatch_exception`、`transport_attempts=1`，其中 `chapter-generate` 12 条、`regimen-generate` 2 条、`seed-generate` 4 条、其它 1 条；**`failed` 终态一条都没有**。
纠正请求体积是原请求的近 2 倍（`runtime/proposal_correction.py:structure_correction_inputs` 把 `prepared.to_payload()` 全量 + `previous_output` 全文 + errors 一起回传），且 `_correction_budget_exhausted` 限定**每章只有一次纠正机会**——"最容易失败的章节，其唯一重试也最容易失败"。

**环 3｜节点状态被投影为"阻断且不可续跑"。**
`graph/runtime.py:1012-1033`：`UNKNOWN_OUTCOME/RUNNING` → `BLOCKED_UNKNOWN`；`graph/proposal_progress.py:6-17`：run 为 blocked 时返回 `{'status':'blocked','can_resume':False}`。章节坐标因此变成 `status='blocked'`。

**环 4｜一章阻断 → 全稿冻结，且产品无出口。**
- `agent3/manuscript_coordinator.py:103-107`：`stopped = any(status not in {not_started,running,needs_content_review} and not can_resume)`；`applicable` 含 `blocked` → 全稿 `status='blocked'`、`can_resume=False`。
- `agent3/manuscript_coordinator.py:113`：`if not state['can_resume']: return state` —— 服务端续跑直接短路。
- `api/manuscript_drafts.py:334-341`：`POST /recover` **只读**，不派发任何东西。
- `frontend/.../ManuscriptWorkspace.jsx:539-544`：blocked 分支的"继续写作（重试未完成的章节）"只做 `setRefresh(v=>v+1)`，effect 落到 `recoverManuscriptDraft` → 只读接口。**按钮在语义上是空的。**
- `ManuscriptWorkspace.jsx:575`：真正会调 `resume`/`start` 的"核对并继续本次写作"仅在 `error || job?.can_resume` 时渲染——blocked 时 `can_resume=False`，按钮根本不出现。

**附：第七轮那条"一章失败不冻结全稿"的修复是死代码。**
`manuscript_coordinator.py:96`：`({**item,'can_resume':True} if item.get('status')=='failed' else item)`。而 `GraphRunStatus` 只有 `RUNNING/AWAITING_DECISION/BLOCKED/COMPLETED`（`graph/state.py:48-54`），`proposal_outcome` 永不会吐出 `'failed'`；`validation['status']` 也只有 `needs_content_review/needs_structure_correction`。**该判定恒为假**，所以 round-7/8/9/10 反复复现同一个 P0。

**附：运行时其实有恢复算子，但没有任何产品入口。**
`graph/runtime.py:615 resolve_blocked_with_failure` / `:658 resolve_unknown_with_receipt` / `:787 retry_node` —— 全仓调用者**只有 `tests/protocol_v3/*`**。设计上写着"Recovery requires explicit owner action"，产品里并不存在这个 owner action。

### 1.2 对"前端 0 网络请求"的判读
tester4 的"fetch hook 捕获 0 请求"应视为**测量口径问题**：按代码，点击必然发出 `POST …/manuscript-draft/recover`（`protocolWorkspaceApi.mjs:133`）。功能结论不受影响——**该请求是只读的，服务端不会因此推进任何章节**。这一条建议复测时用 Network 面板而非 hook 断言。

### 1.3 最小验证方案
1. 直接读库（不改状态）：`e2e_test_mw.sqlite` → `execution_reservation` 中 `logical_call_id like '%:correction:1:chapter-generate' and status='unknown_outcome'`；对 tester4 项目应为 1 条，tester1 项目 2 条。
2. 单元级复现：构造一个 `chapter-generate` 成功但 `chapter-validate=needs_structure_correction` 的 fixture，令纠正派发抛异常，断言 `ManuscriptDraftCoordinator.read()['status']=='blocked'`、`can_resume is False`。修复后应变为 `running/can_resume True`。
3. 端到端：阻断 1 章后点"继续写作"，修复前章节数不变，修复后应新增已完成章节。

### 1.4 修复建议（按序）
1. **给 unknown/blocked 章节装产品级恢复入口**：`/manuscript-draft/resume`（显式调用 `resolve_blocked_with_failure`+`retry_node`，或在 coordinator 内对 `blocked_unknown` 且无 live dispatch 的章节走"派生幂等 retry"）。这是唯一能同时救 round-7/8/9/10 的改动。
2. **修死代码**：`manuscript_coordinator.py:96` 改为按节点终态判定（`outcome['status']=='blocked'` 且 reservation 为 FAILED/BLOCKED_UNKNOWN），或直接以 `_latest_reservation` 判定。
3. **让按钮名副其实**：blocked 分支的按钮改调 `start`（服务端 `api/manuscript_drafts.py:313` 会在 `can_resume` 时挂 BackgroundTask 续跑），或在 `can_resume=False` 时渲染显式"重试未完成章节（会新建尝试）"。
4. **纠正派发减负 + 可重试**：纠正上下文只回传错误定位与必要片段，而不是全文回灌；`allowed_attempts` 提到 2。
5. **可诊断性**：`error_code` 目前把所有异常压成 `dispatch_exception`（异常文本只进 stderr，本轮 stderr 日志已不可得）。应把异常类型/摘要持久化到预约或事件，否则运维永远无法区分 504、上下文超限与网关身份不符。

---

## 二、P0-B 确认门禁不收敛 —— 判定：**真缺陷（设计性不收敛）**＋一个环境放大器

### 2.1 根因：门禁判的是"模型自报完整度"，而用户唯一通道（写作说明）在结构上无法满足它

`agent2/clinical_worker.py:159-162`：
```python
missing = (regimen is None or response.questions or
           regimen["unresolved_questions"] or
           any(item["relation"] == "unresolved" for item in coverage))
return {"status": "needs_information" if missing else "ready_for_review", ...}
```
- `regimen_source_quote_not_found` 强制每条 step 引用必须命中 `source_artifact_id + locator + quote`（`:141-153`）。**自由文本"写作说明"没有 locator/quote 级出处**，因此用户补答不可能让模型停用 `questions`。
- `bind_candidate_coverage`（`agent2/recommendations.py:22-51`）要求**每个种子候选**都有归属；`unresolved` 直接计入 missing。用户每补一轮，种子候选集就长大一批 → 门禁追自己的尾巴。
- 前端 `RegimenProposalCard.jsx:147-155` 的 `canConfirm` 要求 `proposal.status==='ready_for_review' && pending.length===0`；`:216-222` 只把未决项渲染成 `<ul>`，**卡内没有任何作答控件**（与三份报告一致）。

**现场证据（tester3 项目 6 个 regimen run 全部 `needs_information`，逐轮问题原文）**：
- 第1轮：剂量/频次/疗程、"52周"含义、治疗组划分；
- 第2轮：片数换算、**"source_intake.sources 为空，当前给药候选无法附 source_artifact_id/locator/quote 级来源引用"**；
- 第4轮：**"100 mg/200 mg剂量、安慰剂组、52周治疗期、50 mg/片规格和减量规则来自用户意图/种子候选，confirmed_study与source未确认这些给药事实"** ← 这就是"要求用户确认自己刚补答的内容"的机制：补答进入了**素材/种子候选**，从未进入 `confirmed_study` 事实。
- tester2 项目另有一条 `regimen-generate` 的 `unknown_outcome`（20:41:21 UTC = 04:41 CST），正对应其"归属尚未核实"。

### 2.2 "重新生成给药设计"同样是空按钮
`RegimenDesignWorkspace.jsx:162-171`：点击只做 `setSaved({pending:true,intent,previousRunIds})` + `setRefresh` → effect 走 `recoverRegimenDesign(...)`（只读）→ 拿回**同一个已阻断 run**。因为 run id 由输入哈希决定（`agent2/design_coordinator.py:run_id`），输入不变则永远是同一个 run。tester1 的"重新生成×2 均回未完成"由此而来。

### 2.3 第4卡静默无效
`DesignElementsCards.jsx:154`：`confirmCard` 首行 `if (flight.current || !actorId || !runId) return;` —— 静默返回，无 toast、无请求；按钮只按 `busy` 禁用（`:79-80`），因此"可点但无反应"可复现。属 P2，但应改成显式禁用+原因。

### 2.4 修复建议
1. **把门禁从"模型自报"改为"用户决策覆盖"**：`questions/unresolved` 降为"提示项"，允许用户在卡片内就地作答并落成 `StudyDefinition` 事实（写 `confirmed_study`），再以"事实是否齐备"判定可确认。
2. **给写作说明以一等公民身份**：补答写入 `confirmed_study`（USER 决策 + 决策记录），而不是只当 source。这一条同时修掉"要求确认自己补答内容"的观感。
3. **每轮未决项做差分**：`questions` 与上一轮做集合差，只展示**新增**未决项；纯复述项折叠。
4. **blocked 出口接 `retry_node`**（与 P0-A 同源修复）。

---

## 三、P0-C 跨项目内容串染 —— 判定：**误报（聚合报告用错文件）**

### 3.1 直接证据

| 文件 | 段/表 | `缺口身份` | IgAN | 补体 | 甲状腺眼病/突眼 | 归属 |
|---|---|---|---|---|---|---|
| `iga_protocol_work.docx`（聚合报告实际 QC 的文件） | **572 / 6** | 108 | 2 | 1 | 0 | **IgA 肾病项目自身导出** |
| `ted_t1_protocol_export.docx`（第十轮 TED 产物） | 628 / 10 | **0** | **0** | **0** | 7 / 22 | TED 项目 |

聚合报告写"24,538字符/572段/6表"，**段/表数与 `iga_protocol_work.docx` 完全吻合**；该文件时间戳为 09-20 11:04，而第十轮 TED 导出为 09-21 04:52，早于测试 17.5 小时。其正文"本研究的实际适应症为原发性IgA肾病（IgAN）"对 IgAN 项目是**正确内容**，不是串染。

旁证：tester2 自己的反拟合表把 IgAN 记为"0 未命中"，与聚合报告冲突；tester2 的导出正文（`ted_t1_protocol_export.docx`）经我逐段扫描，IgAN/补体/IgA 全部为 0，`甲状腺眼病/TED/突眼` 正常出现。

### 3.2 结论与残留风险
- **P0-C 撤销**。根因是 QC 取件口径：`/tmp/t17_tester2/` 是跨轮共享目录（多个测试者共写），QC 脚本按文件名 glob 取到了上一轮 IgAN 的产物。
- 保留一条**工程改进**：导出产物目前无法自证项目归属。建议在 docx 核心属性或 `X-Export-Scope` 头之外，把 `project_id/study_definition_id/document_sha256` 写入 `docProps/core.xml`（或 `custom.xml`），让 QC 与用户都能一眼判定"这份稿子属于哪个项目"。这能把此类误报从"靠文件名"升级为"靠指纹"。

---

## 四、P1 逐项审阅

### P1-A 缺口锚点泄漏 —— 判定：**真缺陷（三个面，不是一条）**
- 语义稿里锚点是**设计内**：`agent3/manuscript_document.py:26` `content = f'{text}（缺口身份：{node_id}）'`（注释明说"语义稿内原样保留供校验"）。
- 导出段路径**已剥离且生效**：`agent3/word_export_production.py:148-156,331`；实测 TED 导出 `缺口身份=0`。
- 但仍有三个未覆盖面：
  1. **表格路径不剥离**：`:339-345` `_add_table(doc, block.get('content'))` 未过 `_redact_gap_paths`；
  2. **UI 阅读面不剥离**：`ChapterDraftPreview` 直出语义块内容（tester4 截图里的 `v2_n_16_x1/x2/x3` 属另一类，见 P1-D）；
  3. **旧产物**：`iga_protocol_work.docx` 108 处系 ac035b2（09-20 12:04）之前的产物 —— 这一点聚合报告把"历史产物"当成了"当前泄漏"，**P1-A 的严重度应下调**，但仍需修 1) 与 2)。
- 建议：把 `_redact_gap_paths` 提升为"导出前对整份 semantic document 的统一投影"（段落+表格+脚注+批注一次过），并在语义稿读接口做同一投影，保证"用户看到的 = 导出的"。

### P1-B 导入方案摘要挂死 —— 判定：**真缺陷，但根因与报告完全不同**

**后端并未挂死。** 现场记录（`runtime/medical_writing_synopsis_import.sqlite3`，tester1 的 `synthetic-reference.docx`，`mwintake_5a65f553ab275dd70aa44809`）：
```
created_at 2026-09-20T21:03:30.998Z → updated_at 21:03:31.123Z（125 ms）
status=failed  phase=failed
error_message = "chunk 0 validation failed: AI provider request failed: HTTP 401"
route_snapshot = base_url https://api.deepseek.com/v1, expected_response_model deepseek-v4-flash
```
即：**125 毫秒内就以 401 终结**（round-9 的网关/凭证修复只覆盖了 protocol v3 链路，没覆盖这条 legacy 摘要导入链路）。

**13 分钟无限转圈的真正原因在前端一行 latch：**
```jsx
// MedicalWritingSynopsisProjectIntake.jsx:207-211
const mountedRef = useRef(true);
useEffect(() => () => { mountedRef.current = false; … }, []);   // ← 只有 body 无 reset
```
`frontend/src/main.jsx:10` 挂了 `<React.StrictMode>`。开发模式下 StrictMode 会"挂载→卸载→再挂载"，首次清理把 `mountedRef.current` 永久置 false，此后 `start()` 里 `if (!mountedRef.current) return;`（`:305`）直接返回：`busy` 停在 `"processing"`、`job` 为 null → 渲染 `phaseLabel(null)="准备导入"` + `total=0` 的"正在准备文档内容"，**既不报错也不超时**，与 tester1 的截图文字逐字吻合。
对照：同类组件早已修好这个坑（`DesignElementsCards.jsx:98-102`、`RegimenAdoptionCard.jsx:41-42` 都写了 `alive.current = true` 的 reset，注释还专门写了"StrictMode remounts effects"）——**同一个团队知道这个 hazard，只漏了 legacy 这个文件**。
- 修复：`useEffect(() => { mountedRef.current = true; return () => {…}; }, [])`（1 行）。
- 附带：错误文案不应直出 `HTTP 401`（`synopsisJobMessage` 会原样显示 `error_message`），以及这条 legacy 链路的 provider 配置需与 v3 对齐。

### P1-C 内部标识符 UI 直出 —— 判定：**真缺陷**
`ManuscriptWorkspace.jsx:98-99`：历史记录按钮文本直接拼 run id —— `资料准备（${entry.sourceRunId?.slice(0,24)}…）` / `初稿（${entry.intent?.expected_workflow_run_id?.slice(0,24)}…）`。同文件 `:20-31` 已有 `RESIDUAL_KEY_LABELS` 这套"内部键名不直出"的先例，历史标签漏了。
- 修复：改用人类可读标签（时间 + "资料准备/初稿" + 序号），run id 只在 hover/详情里给。

### P1-D 内容质量（"继承性义务"病句 + 与已确认靶点矛盾）—— 判定：**真缺陷，两个独立机制**

**机制一：章节契约的内部治理文本被当作提示材料喂给模型，模型照抄进正文。**
`agent3/chapter_draft.py:63-70`：`payload["chapter_contract"] = contract.model_dump(mode="json")` —— **整份契约**（含 `fact_requirements[].rationale`、`positive_qc_rules[].rule`、`registry_consistency_obligations`）进提示词。命中的原文：

| 模型写进正文的句子 | 来源 |
|---|---|
| "本药作用机制为继承性义务…不得反向引用源文作为已含证据" | `chapter_contracts/v2_n_2_2_1.json:45` `fact_requirements[4].rationale` |
| "不得反向引用源文作为已含证据"（tester2 2.2.1 章） | 同上 |
| "v2_n_16_x1、v2_n_16_x2、v2_n_16_x3各自的独立覆盖义务"（tester4 附录章） | `chapter_contracts/v2_n_16.json:54` `positive_qc_rules[qc:v2-n-16:leaf-preservation]` |

导出侧的 `engineering_markers`（`word_export_production.py:355-380`）只**报告**不清洗，且白名单里没有这些句子。
- 修复：生成提示词只给"写作约束"（去掉 rationale/QC 规则/node id），治理文本走独立非内容通道；导出侧把"契约来源句"纳入可见候选清洗（保持 R-C04 的"可见候选、非静默删除"原则）。

**机制二：同一语义有两条事实路径，只有一条有写入方。**
- 用户确认的靶点/机制 → `framing.target_mechanism`（`agent2/research_intent.py:9-14`，由 2.1 章消费）。
- 2.2.1 章要求的是 `background.product.mechanism`（`chapter_contracts/v2_n_2_2_1.json:43`），**全仓唯一写入方是可选 AI 补齐器**（`agent3/chapter_facts.py`）。于是"已确认靶点=尿酸转运蛋白1抑制剂"与正文"未载明作用机制"并存。
- 建议：为 2.2.1 增加 `framing.target_mechanism` 的派生绑定，或把 `background.product.mechanism` 纳入研究信息确认流。

### P1-E OCR 对图片型 DOCX 不可用 —— 判定：**真缺陷（功能缺口）+ 文案归因错误**
- `agent1/docx_parse.py:218` `raise ValueError('DOCX contains no extractable source text')`；
- `api/sources.py:36-42` 把 `BadZipFile/ParseError/KeyError/ValueError` **一律**映射为"这份文件暂时无法按 Word 方案读取…请另存为 DOCX 后重选" —— 文件本身合法，真实原因是**无文字层**；
- `ProtocolSourceIntake.jsx:487` `accept=".docx,…"`，无 PDF/图片入口，链路中无 OCR 兜底。
- 判级：同意聚合报告把它从 tester3 的 P0 下调为 **P1**（是能力缺口，不是回归；且只影响上传扫描件的项目）。
- 修复：至少把 `no extractable text` 单列错误码 + 准确文案（"该文件没有可提取的文字层，请上传可选中文字的版本或等待 OCR 支持"），并接上仓库已有的 OCR/omlx 通道。

---

## 五、P2 判定（简表）

| 项 | 判定 | 说明 |
|---|---|---|
| 39 项确认需先"更新研究与文档状态" | 真缺陷（UX） | `api/manuscript_drafts.py:266` 的 CAS 409 是正确保护，但前端应自动刷新 revision 后重试，而非让用户猜顺序 |
| 第4卡确认静默无效 | 真缺陷 | `DesignElementsCards.jsx:154` 静默 return；应禁用+原因 |
| 版本门禁开局阻塞约 5 分钟 | **环境噪声**（非产品） | 现场确有后端中途重启（tester3 记录 build 变化）；另发现 `e2e_test_mw.sqlite.pre-cleanup-20260921_043238`，04:32 做过一次项目清理，正是 tester3 观察到"下拉 25→11 项"的原因。门禁页"无返回路径"（`<main>` 覆盖侧栏）是**真 UI 缺陷**，值得单独修 |
| 写作说明 textarea 被折叠面板遮挡 | 真缺陷（a11y） | `pvi-seed-details` 覆盖可点区 |
| 点击未完成章节无反馈 | 真缺陷 | 章节按钮 `disabled` 无 tooltip/原因 |
| 章节标题模板残留"有'状况/疾病'的试验参与者" | 真缺陷 | `_chapter_titles`（`word_export_production.py:41-51`）直读 `node_tree.json:827` 原始 `title_zh`；而 `v2_n_3_1_2_1.json:79` 明写"源标题去占位…不得作为定稿标题输出"——规则只约束模型，没约束标题来源 |
| 封面方案编号/版本日期空白 | 真缺陷（与 P1-D 同族） | `deterministic_document_facts`（`chapter_facts.py:135-176`）**只被可选补齐器调用**，`_real_values` 又坚持"未确认不造号"，于是封面留白；而 1.1 章又要求这些字段 → "可选补齐"实为必做，产品文案误导 |
| 附录 1/2 出现 ECOG/NYHA | 半误报 | 二者各有条件适用规则（`appendix.ecog_assessment_applicable` 等），未决时正确落"待判定"；TED 方案里应引导用户判"不适用"而非保留标题 |
| tester2 目录/图表模块 | **真缺陷且比报告更重** | 源模板含 2 处 TOC 域、864 fldChar、`word/media/flow.png`；导出后 **TOC 域 0、hyperlink 0、media 0**。即：TOC 域被前置手术删掉且未重建，模板流程图被丢弃且无替代生成 |
| "完整初稿"名实不符 | 真缺陷（语义） | `manuscript_coordinator.py:99-101` 的 `complete` 只在 `applicable`（=有已解析事实的章节）上计算，`kept_as_gap` 不计入 → **7/111 也算 complete_candidate**，可保存可导出（tester2 实证）。"完整初稿"这个词应改，或把 gap 密度纳入出口条件 |

---

## 六、举一反三：同类根因的其它影响面

| 根因 | 已知命中 | 还可能命中 |
|---|---|---|
| unknown_outcome 无恢复入口（环2-4） | chapter-generate、regimen-generate | **seed-generate 已有 4 例**（"准备写作材料"）；design-elements、object-revision、save/adopt 等所有走 `_ServiceTransport` 的节点；任何 `run_to_completion` 内的模型节点 |
| "按钮只 recover 不 retry" | 继续写作、重新生成给药设计、核对本次设计 | 资料准备重试、设计要素重生成、历史恢复（`onRestore`）——凡是"以输入哈希定 run id + 只读 recover"的组合 |
| StrictMode latch | legacy 摘要导入 | 其余 7 处 `useRef(true)` 组件需逐一核对是否有 body reset；任何"卸载后不复位"的 alive 标志都会让长任务永远不结算 |
| 契约内部文本进提示词 | 2.2.1、v2_n_16 | **全部 111 章**（每章 payload 都带整份 contract）；尤其 `ctq_items`/`registry_consistency_obligations` 密集的章 |
| 事实路径分叉（写一端读另一端） | `background.product.mechanism` | 所有 `synopsis.*`（14 条，仅 1.1 消费，无产品写入方）、`appendix.*` 条件事实、`document_control.*`（靠可选补齐器）——本质是"确认流写入命名空间"与"章节契约读取命名空间"缺一致性校验 |
| 导出侧投影不全 | 段落已脱敏、表格/UI 未脱敏 | 脚注、批注、页眉页脚、文本框；以及"用户看到≠导出内容"的所有分叉面 |
| 门禁基于模型自报 | 给药（needs_information） | 设计要素 `needs_information`、章节 `needs_content_review`——凡是"模型说齐了才算齐"的地方都会不收敛 |

---

## 七、Top 修复优先级清单（含最小验证）

| # | 优先级 | 项 | 改动点 | 最小验证 |
|---|---|---|---|---|
| 1 | **P0** | 给 blocked/unknown 章节装可用的重试入口 | `agent3/manuscript_coordinator.py` + 新 `/manuscript-draft/resume`（接 `runtime.retry_node`/`resolve_blocked_with_failure`）+ `ManuscriptWorkspace.jsx:539-544` 按钮改调它 | 用现场库 tester4 项目复现：修前"继续写作"章节数不变，修后 v2_n_1_1 进入重试并落 `needs_content_review` |
| 2 | **P0** | 修死代码：`'failed'` 判定恒假 | `manuscript_coordinator.py:96` 改按节点终态 | 单测：构造 FAILED 节点 → `can_resume is True`；构造 BLOCKED_UNKNOWN → 走 #1 路径 |
| 3 | **P0** | 纠正派发减负 + 允许第二次纠正 + 异常可诊断 | `runtime/proposal_correction.py`、`agent3/subgraph.py`（`allowed_attempts`）、`runtime/reservations.py` 错误码细分 | 单测：纠正超限 → FAILED（可重试），而非 UNKNOWN_OUTCOME；预约表能读到异常类型 |
| 4 | **P0** | 给药门禁改为"用户决策可闭环" | `agent2/clinical_worker.py:159-162`、`RegimenProposalCard.jsx`（就地作答/确认写入 `confirmed_study`） | 端到端：零附件项目补答 → `ready_for_review` 且 `canConfirm=true`（当前 6/6 失败） |
| 5 | **P1** | legacy 摘要导入 StrictMode latch（1 行） | `MedicalWritingSynopsisProjectIntake.jsx:207` | 开发模式走 入口A：失败时**必须**出现错误框与"继续处理"，不再无限转圈 |
| 6 | **P1** | 该链路的 provider 凭证（401）对齐 v3 | 路由/env（`medical_writing_synopsis_import` 的 route snapshot） | 同一夹具导入返回 `review_ready` |
| 7 | **P1** | 契约内部文本不进提示词 + 导出侧纳入清洗候选 | `agent3/chapter_draft.py:63-70`、`word_export_production.py:355-380` | 生成 2.2.1/v2_n_16：正文不再出现"继承性义务""独立覆盖义务""不得反向引用" |
| 8 | **P1** | 事实路径一致性（`background.product.mechanism`、`synopsis.*`、封面文控） | 绑定表 + 确认流写入端；把"补齐章节事实"从"可选"改为显式必经步骤或自动前置 | 确认靶点后生成 2.2.1：正文出现已确认机制而非"未载明"；1.1 概要不再全【待补充】 |
| 9 | **P1** | 导出统一投影：TOC 域重建 + 表格/脚注脱敏 + 缺口锚点全路径剥离 | `word_export_production.py`（`_find_toc_end` 之后插入 TOC 域；`_add_table` 过 `_redact_gap_paths`） | 导出 docx：`instrText` 含 TOC ≥1；表格内 `缺口身份=0`；UI 与导出文本一致 |
| 10 | **P1** | 章节标题去占位 + 内部标识符 UI 清理 | `_chapter_titles` 增加"去占位"投影；`ManuscriptWorkspace.jsx:98-99` 改人类标签 | 章节树/导出标题不含"状况/疾病"；历史按钮不含 `chapter-sources:` |
| 11 | **P1** | 摘要导入 OCR 缺口与归因文案 | `api/sources.py:36-42` 细分错误码 + `docx_parse.py` 语义化；评估接 OCR | 图片型 DOCX 得到"无文字层"的准确提示 |
| 12 | **P2** | QC/验收流程：导出加项目指纹；共享 /tmp 目录按轮次隔离 | `export/docx` 写 `docProps/custom.xml`；测试产物目录按轮次分桶 | 任意 docx 可自证 project/study/document sha；P0-C 类误报不再可能 |
| 13 | **P2** | 版本门禁页可返回；39 项确认自动刷新；卡片静默 return 改显式禁用 | 三处前端 | 门禁页可导航离开；确认一次成功；卡片点击有反馈 |

**本轮最重要的结论**：P0-A 与 P0-B 不是两个问题，而是**同一个根因族**——`UNKNOWN_OUTCOME` 不可再派发 + 前端"终态按钮只 recover 不 retry" + 门禁以模型自报为准。只修 UI 文案或只加超时都不会收敛；必须补上"显式重试（新建尝试）"这条产品路径。P0-C 应予撤销并把 QC 取件口径修好，否则会持续消耗修复预算在不存在的问题上。
