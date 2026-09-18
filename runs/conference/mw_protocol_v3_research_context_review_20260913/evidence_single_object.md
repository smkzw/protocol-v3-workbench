我先读取审阅合同和产物清单，确认冻结文件范围与核验口径，再独立挑战来源采用链。合同已对齐：先核 28 个冻结文件的 hash，再读研究上下文、来源采用链和既有浏览器证据。28 个文件 hash 初核全部一致。接下来读核心源码、测试和 owner 浏览器证据。核心测试已读完。接着定位采用、恢复、fresh 校验和 study 发现的实际实现。接下来核对 ApplicationService 的 CAS/lookup、App 挂载约定，以及 owner 浏览器证据。关键边界已经定位：study_id 由 project 派生、fresh 采用靠上下文相等、genesis 没有 input binding。接下来对照源码和 fixture 做可复现反例。接下来在 scratch 里写可复现反例，并跑冻结测试与 vitest。冻结测试已通过。vitest 需要按项目配置从 `frontend` 跑；探针里 legacy 创建响应字段也要先核对再继续。探针已跑通。legacy 的 dump 对比被后续 update 污染了，我先把创建后的快照单独记下来，再按项目配置跑 vitest。# Conference Output: mw_protocol_v3_research_context_review_20260913 - evidence_single_object

## Output

独立工程合成审阅。未改产品。未声称医学/Word/整稿接受。未开额外角色。未做浏览器终验。

### Hash 初终核

| 项 | 结果 |
|---|---|
| 清单 | `artifact_manifest.json` 28 文件 |
| 初核 | `ok=28 missing=0 mismatch=0` |
| 终核 | `final_hash ok=28/28` |
| 产品改动 | 无。仅 scratch 探针 |

命令：对清单做 SHA256；终核同样 28/28。

---

### Evidence

#### 1. 冻结测试与前端单测

- `PYTHONPATH=services/api:tests:tests/protocol_v3:tests/protocol_v3/integration:.` + 指定 venv pytest：6 个冻结测试文件 **12 passed in 1.50s**。
- `cd frontend && npm run test:unit:vitest`（jsdom 清单）：**10 files / 73 tests passed**。含 `StudyContextWorkspace.test.jsx`、`ProtocolIntakeWorkspace.test.jsx`。
- 本角色未跑真实浏览器。Owner 限定证据：`runs/mw_protocol_v3_v1_1_20260913/browser_functional/context_browser_verification.json`、`context_after_adoption.json`、`context_before_browser.json`。

Owner 浏览器摘要（观察，非本角色复验）：3 次关联/找回/采用；`decision:research-request=unverified`，`decision:dose-regimen=current`；`source_context_matches=true`；`synthetic_generation_calls=2`，`real_model_calls=0`；scope 写明 synthetic prestaged，不是完整方案/Word。

#### 2. 来源身份：hash 投影不完整，但全量 intake hash 会变

`regimen_input_context`（`agent2/input_context.py:11-28`）校验 `sha256(source_intake)==seed.input_sha256`，列出的 `source_artifacts` **只有** `source_artifact_id` + `content_sha256`。

scratch 反例 `source_artifacts_omit_parse_identity`：

- 列出 keys：`content_sha256`, `source_artifact_id`
- 省略：`diagnostics`, `jurisdiction`, `parser_version`, `source_role`, `source_version`, `units`
- 只改 `units[0].text`（解析漂移）：**列出 artifacts 不变**，`source_intake_sha256` 与 `seed_proposal_sha256` **都变**

`mismatch_and_empty_sources`：

- source/seed 不一致 → `source_input_identity_mismatch`
- `sources=[]` **仍可形成 context**（`source_artifacts=[]`，brief 仍在）

不要只因有 hash 判完整：列出的 artifact hash 覆盖不了 parse/role/version/units。fresh 采用比的是 **整个** `research.input_context` 字典（`design.py:171-173`），所以官方路径能抓住 intake 漂移；只看列出的 artifacts 会漏。

#### 3. 错误 study 不误采用；同一 run 可写入两个 context 相同的 study

`design.py:157-175`：fresh 采用先 lookup 历史回执；否则要求 `ready_for_review`，再要求当前 study 的 `research.input_context == regimen_input_context(prepared)`。

scratch `wrong_study_and_cross_study_same_context`：

- 采用到 **无匹配 context** 的 `study:legacy` → **409**，dump 不变
- 经通用 `study-definitions` 建 `study:alpha` 与 `study:beta`，**同一** `research.input_context`
- 同一 `run_id=regimen-design:127a0991…` 对 alpha **200**、对 beta **200**，两边都写入 `research.regimen_producer.workflow_run_id`

Run 身份（`coordinator.py:17-22`）是 `project + branch + seed_proposal`，**不含 study id，也不含完整 source_intake body**。合同点「run 未按唯一 study id 登记，fresh 只靠显式目标 + source context 相等」被打穿：相等不是唯一占用。

#### 4. 发现/创建/重开

`design.py:83`：`study_id = "study:v3:" + sha256(project_id)[:32]`。本项目一条确定性身份。

scratch `study_context_create_identity_and_legacy`（project=`project-source-import`）：

- 派生 id `study:v3:1b79a00257fcfdfa8264534669273d23` 与公式一致
- 创建 facts **仅** `research.input_context`；无 picos、无 10mg
- genesis `decision:research-request` 的 `current_validity` = **`unverified`**
- 另一 `operation_id` 再 POST create → **409**「本项目已有研究，原内容已保留。」dump 不变
- 原 operation replay 200 `replayed=true`；recover 200 revision=1；不存在的 recover **404**
- fake opener **1** 次，未因 recover 再派模型

`prepare_research_context_creation`（`research_context.py:11-27`）**不设** `decision_input_refs`。`create_study_definition` 不写 `decision_input_binding`。`get_decision_graph`（`service.py:822-845`）无 binding → `unverified`。Owner 浏览器 `research-request=unverified` 与此同源，不是资料已漂。

官方 `/inputs` 另测：genesis `unverified`；`prepare_research_context_update` 绑定 `research.input_context` 后 → **`current`**，opener=2。

前端（`StudyContextWorkspace.jsx:69`）：`studies.length===1` **静默选中唯一 study**。`>1` 才要下拉。列表失败则创建按钮 disabled（单测覆盖）。

`ProtocolIntakeWorkspace.jsx:216-219`：`studyDefinitionId || !actorId` 时 **跳过** StudyContext，直接 `RegimenDesignWorkspace`。`App.jsx:15900` 现挂 `actorId="medical_manager"`。功能页默认 `actorId={contextMode ? … : undefined}`，非 context 模式会走旁路。

未做真实双线程 create 竞态。API 层先 `list_current` 再 create；CAS `expected_revision=0`。不同 operation 在已有聚合上应 409/stale，不是静默第二份派生 id。

#### 5. current / stale / unverified 与历史回执

scratch `historical_lookup_returns_current_after_successor`（与冻结 `test_regimen_adoption_api` 同构）：

- 采用后 `decision:dose-regimen=current`
- 通用 apply 改 `seed_proposal_sha256` 后 dose → **`stale`**；dump 在随后 recover/replay **不变**；revision 停在 3，**后继不回退**
- `lookup_decision`（`service.py:653-656`）返回 **当前** aggregate，不是采用当时的 snapshot：recover revision=3，`replayed=true`，definition 已含改过的 seed hash，同时仍有 `intervention.dose_regimen`
- `RegimenAdoptionCard.jsx:29-35` 的 `accept()` 只要求 `revision >= expected_revision+1`，**不区分** fresh / 历史回执 / stale

通用 apply 改 input **不带** `decision_input_refs` 时，图上最新 `research-request` 为 `unverified`。官方 `/inputs` 才会 `current`。冻结采用测试用的是通用 apply 来造 stale。

#### 6. 旧路径兼容；needs_information 不自动采用

- `needs_information`：recover **404**，adopt **409**，dump 不变，opener=1。与 `design.py:166-168`、`test_regimen_adoption_api.py:52-62` 一致。lookup 不把当前就绪当采用条件（`prepare_regimen_recovery` 只用 output_sha256）。
- 错误 study 409 已见上。
- 新通路 create 不写入 10mg。

**与旧 `study-definitions` 相交是本路径具体缺陷**（scratch `legacy_study_blocks_create_update_preserves_10mg`）：

- 旧 create 的 facts：`picos.intervention.dose="10 mg 每日一次"` + indication
- `GET study-context` 只列出这一条，`matches_selected_inputs=false`，`auto_select_candidate=study:legacy-10mg`
- 派生 id 的 create → **409**，dump 不变
- 对 **该旧 study** 走 `/inputs` → **200**；facts 变成 picos 两路 **加上** `research.input_context`，**10mg 仍在**
- 此后 `matches_selected_inputs` 可为 true，前端会进入设计

设计 payload 只有 `instruction/output_schema/schema/seed_proposal/source_intake`（`clinical_worker.py:116-123`），**不读**当前 StudyDefinition。旧 10mg 既不会进入生产者输入，也不会在采用时被退役。采用写入 `intervention.dose_regimen` 后，`picos.intervention.dose` 仍可并存。

#### 7. 接线

- App 写作页：`actorId="medical_manager"`，不冒称实名批准。
- 前端 create intent 仅 `actor_id, decided_at, operation_id, seed_run_id`（StudyContext 单测）。
- 424 → `notExecuted`，不把未知失败标成功；400/404/409/422 清 pending、不自动 apply。
- 未测 StudyContext 的 StrictMode 双挂载 create；Intake 有 StrictMode 只读恢复单测。

探针脚本：`runs/conference/mw_protocol_v3_research_context_review_20260913/scratch/probe_research_context_counterexamples.py`，结果 `scratch/probe_results.json`。临时 SQLite 仅 scratch/tmp。

---

### Inference

1. **身份链对「错误 study / 未就绪 run / source-seed 不一致」是闭合的**；对「context 相同的多个 study」和「列出的 artifact hash」不是。fresh 采用的充分条件被合同点打穿。
2. **study-context 创建是「每项目至多一个派生 id」**，不是「发现全部 study 再显式选择后再创建」。唯一旧 study 时，前端会把它当当前研究并提供资料更新，从而把新 source/seed **贴到旧医学事实上**。这是本路径与旧 genesis（含默认 10mg）的可复现交叉，不是抽象缺口。
3. **genesis 无 input binding ⇒ 写作请求在图上恒为 unverified**，直到官方 `/inputs`。Owner 浏览器的 unverified 不能当成「资料已漂」。当前有效性 UI 合同已列为未完成，但本路径已产出可观测错误标签。
4. **历史回执查找不回退后继**（存储层成立）；返回体是当前定义 + 历史 decision id。客户端若把 recover 当「这次采用仍为当前有效」，会把 stale 方案显示成已保存成功。
5. 设计层不读 StudyDefinition：在「旧 10mg 仍在 + 新 context 已匹配」时，生产者既看不到也不清理该剂量。这是该边界在本路径上的具体影响，不是把科学依赖改名为安全后排除。

有限范围内可成立的工程行为：错误 study 409；needs_information 不采用；同 operation 重开/lookup；第二 operation 不新建；空项目创建不带 10mg/picos；App actor 为 `medical_manager`；冻结 12 测与前端清单 73 测通过。

---

### Recommendation

**本路径不可标通过。** 建议分阶段，且先 fail-closed，不扩 Word/其余 7 类决策。

**A. 本路径 fail-closed（应先做）**

1. study-context **update** 拒绝目标 study 已有 `picos.*` / `intervention.dose_regimen` 等医学事实，或拒绝非本派生 id、非 `research.input_context` genesis 的聚合。有旧研究时列出并要求显式选择，**禁止** `length===1` 自动选中后贴资料。
2. fresh 采用增加 **run 占用**：若 `research.regimen_producer.workflow_run_id` 已在**另一** study 上，409 且不写。仅 context 相等不够。
3. genesis 写入与 `/inputs` 相同的 `decision_input_binding`，使匹配资料的 `research-request` 可为 `current`。
4. `ProtocolIntakeWorkspace`：无 `actorId` 时 fail-closed，禁止跳过 StudyContext。
5. recover 响应区分 `replayed` 与当前 `current_validity`；前端不得把 stale 历史回执画成当前确认成功。

**B. 下一阶段**

- run 身份纳入 `study_definition_id`，或登记「run → study」独占。
- 设计读集若要含当前 StudyDefinition 医学事实，必须显式、可审计，且不得在创建 baseline 采用。
- 当前有效性 UI。

**C. 仍未做、不得算过**

RecommendationOption、ClaimEvidenceLink、picos 同源投影、其余 7 类决策、全章节、Word。

不要改 fixtures/expected 来消反例。不要把旧流程门当暂停点。

---

### Uncertainty

- 未做真实并发双 POST create；CAS 推断未用线程复现。
- 未做 StudyContext StrictMode 双创建；Intake StrictMode 只覆盖资料整理恢复。
- 未做本角色浏览器终验；Owner 3 次点击不是 ≤20 全路径。
- `sources=[]` 可建 context 是否为「仅 brief」的有意行为，未在产品合同中写死。
- memory `list_current` 未另探，sqlite 已测。
- vitest 清单是 frontend 全部 10 个 jsdom 文件，不限于冻结 28 文件中的 2 个测试。
- 合成 fixture + fake transport；无真实模型、无医学接受。

---

### 有限接受 / 未决

**有限接受（仅工程合成）**

- 错误 study（context 不等）不采用，原库不变
- `needs_information` 不经 recover/adopt 写入
- 同 operation 重开/lookup；缺回执 404；另一 operation 不覆盖
- 空项目 study-context 创建不带 10mg/picos
- App 挂载 `medical_manager`
- 冻结 12 测、frontend vitest 73 测、hash 28/28

**未决 / 否决项**

- 同一 run 可 fresh 采用进多个 context 相同的 study
- 唯一旧 study 被自动选中，`/inputs` 保留 10mg
- genesis `research-request` 恒 unverified
- recover 返回后继当前态，前端可误标成功
- 无 actorId 时跳过研究上下文
- 设计不读、不退役当前医学事实
- 有效性 UI、picos 投影、其余决策、Word、真实浏览器终验

---

### 给 Codex 的异议、方案、决策点、问题

**最高影响缺陷：** 资料更新会把新 source/seed 绑到已有医学事实上（含旧默认 10mg），同时 run 不独占 study。这比「hash 投影略窄」更影响采用链。

**方案：** 见 Recommendation A。

**决策点（会改变目标/范围，需 Codex 裁断）：**

1. study-context 是「每项目恰好一个派生 study」，还是「必须显式选择已有聚合、禁止把新资料贴到旧医学事实上」？
2. fresh 采用是否要 **run 独占一个 study**，还是继续只靠显式 study_id + context 相等？
3. genesis 是否补 binding，还是接受 unverified 直到第一次 `/inputs`？
4. recover 语义是「操作回执（可带当前聚合）」还是「当时快照」？前端目前按前者的 revision 下限接受。

**问题：** 旧 `study-definitions` genesis（10mg）是否仍允许与 v3 写作页同项目并存？若否，A.1 应直接 409 并提示走新派生 id，而不是更新旧聚合。

安全暂定路径：维持现网不改产品；不把本路径标可用；修复前不要把「唯一已有研究 + 使用本次资料继续」当成已验证主路径。
