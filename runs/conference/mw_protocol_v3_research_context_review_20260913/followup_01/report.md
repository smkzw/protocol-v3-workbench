先核 followup 清单和 19 个冻结文件 hash，再按 6 个否决点逐项对照修订后的定义与测试。19 个文件初核一致。接着读 API、采用、前端和测试，对照 6 个修订点。接下来写独立反例：prepare/start/recover、fresh 采用读集、FactBinding 别名冲突，以及前端 key 隔离。# Conference Output: mw_protocol_v3_research_context_review_20260913/followup_01 - evidence_single_object

## Output

同会话定向复核先前否决点修订。未改受审文件。未声称医学/Word/整稿接受。未开浏览器/模型/服务。

### Hash 初终核

| 项 | 结果 |
|---|---|
| 清单 | `followup_01/artifact_manifest.json` **19** 文件 |
| 初核 | `ok=19 missing=0 mismatch=0` |
| 终核 | `final_hash ok=19/19` |
| 产品改动 | 无。仅 `followup_01/scratch/` |

### 命令与范围

- pytest（指定 venv + `PYTHONPATH=services/api:.:tests:tests/protocol_v3:tests/protocol_v3/integration`）：冻结 5 文件 **66 passed in 2.74s**
- `cd frontend && node_modules/.bin/vitest run --config vite.config.mjs --environment jsdom`：`RegimenDesignWorkspace.test.jsx` + `RegimenAdoptionCard.test.jsx` **2 files / 17 passed**
- `node --test protocolSourceApi.test.mjs`：**8 passed**（该文件是 node:test，不能走 jsdom vitest）
- scratch：`probe_followup01.py` 六组反例均 `ok=true`；scratch vitest 因 vitest include/`--dir` 无法加载仓库外 jsx，前端隔离点改由源码+冻结单测核对
- Owner logs（只读，不替代反例）：`regimen_prepare_successor_check` 2 passed；`regimen_study_switch_check` 18 passed；`regimen_current_validity_check` 11 passed；`regimen_catalog_binding_regression` 79 passed；`clinical_readset_api_check` 17 passed

---

### Evidence

#### 1. study_input 给模型目标 study 与已确认 clinical facts

`agent2/study_input.py:10-41`：`clinical_study_facts` 去掉 `research.input_context` / `research.regimen_producer`；`bind_regimen_study_input` 写入 `confirmed_study={study_definition_id, facts}` 并追加 instruction。

`coordinator.py:17-28`：无 `confirmed_study` 时身份仍是 `project+branch+seed_proposal`（旧 source-only 不变）；有则追加 `confirmed-study.v1` + 该对象。

scratch `study_input_identity`：

- 绑定后 clinical facts 仅 `picos.phase=II`
- source-only key 稳定
- 换 study / 换 phase → **4 个不同 run id**
- 只改 `research.regimen_producer` → **同一 PreparedRegimenRequest**
- `validate`：错 study `regimen_target_study_changed`；错 facts `regimen_clinical_facts_changed`
- **source-only `validate` 直接 return**，错目标/错临床值不拒绝

#### 2. /prepare 只读；start 校验当前 key；原 key 复用

`design.py:103-131`：`/prepare` 只 `run_id(request)`，不 `start`。`start` 先 `original_state`（原 key + 原 seed_proposal + 原 `confirmed_study.study_definition_id`）；找不到再算当前 key，当前 key ≠ expected → 409「尚未开始生成」。`recover` 有 expected 则走原 key，未知 404。

scratch `http_prepare_start_recover_challenges`（真 SQLite + fake transport）：

| 挑战 | 结果 |
|---|---|
| prepare 不生成 | opener 在 prepare 后不变 |
| 空 expected recover | 200，命中**当前** key |
| 未知 expected recover | **404** |
| 未知 expected start | **409**，不新派 |
| 错 study / 错 seed recover | **409** |
| 空 prepare body | **422** |
| 后继 `picos.phase=III` 后再 prepare | **新 key** |
| 原 body recover / start | 仍是**原 run**，不因后继 facts 丢失 |
| 无 expected 的 start（当前 key） | **新 run**，因此 opener 从 2 增到 5（新 key 真实新派一次，符合「start 校验当前 key」） |

`original_state` **不比** `confirmed_study.facts`。这是有意：原 key 找回旧 run。fresh 采用另用 `validate_regimen_study_input` 挡临床漂移（见下）。

未做双线程并发；`coordinator.start` 先 `load_run` 再 `start_run`，同 key 第二次应复用。

#### 3. 前端 prepare 先存再 start；切 study 隔离；legacy 不删

`RegimenDesignWorkspace.jsx:22-31, 90-108, 142-143`：study-bound localStorage key 含 `studyDefinitionId`；组件 `key` 含 study；prepare 成功后 `setItem({pending, intent})` 再 start；重开 `recover(saved.intent \|\| seedRunId)`，不重新 prepare。legacy 仅当 `intent.study_definition_id` 指向**另一** study 时不用它，**不 delete**。

冻结单测：prepare 一次后断线重开只 recover；切 `study:b` 不带走 `study:a` 的 run；晚到 seed 不串用。

**仍在的串用面（源码，非 mock 绿）：**

1. `saved.intent || seedRunId`（L64）：study-bound 若只有 `{pending:true}` 无 intent，recover 会发 **source-only body**。
2. L31：legacy **没有** `intent.study_definition_id` 的 source-only `{runId}` **会导入**当前 study-bound 会话，旧 key 仍在。
3. localStorage `setItem` 失败发生在 `dispatched=true` 之前，catch 走 `remember({})`，理论上不 start；scratch vitest 未能在仓库外跑通，此条为源码推断。

#### 4. fresh 采用校验生成读集；历史 receipt 不回退

`design.py:219-227`：fresh 采用对 `prepared_request` 做 `validate_regimen_study_input`。lookup 先返回当前后继 + 原 effect。

`study_definition.py:37-44`：仅当 payload 含 `confirmed_study` 才加 `all_facts` ref（排除两条 research 键）。

`decision_inputs.py:49-63`：`scope=fact` 序列化 **弹出** `scope`/`excluded_fact_paths`，旧普通 refs 形状不变。

scratch `adoption_readset_receipt_validity`：

- study-bound refs 含 all_facts；source-only **3** 条、无 all_facts
- 增/删临床键 → `stale`；只改 producer 元数据 → `current`
- 采用后 `current`；加 `picos.phase` 后 dose 决策 `stale`
- 原 intent replay `replayed=true`，revision=3，**同一** `decision_record_id`，dump 不变

source-only 生成在 study 已有临床事实时，validate **跳过**，fresh 采用只比 source context。

#### 5. 历史 receipt vs current/stale/superseded/unverified

`RegimenAdoptionCard.jsx:48-60, 134-140`：`getDecisionGraph` 后按 **原 `decision_record_id`** 匹配 `decision:dose-regimen`。id 不同 → `superseded`；同 id 且 current/stale → 原值；否则 `unverified`。读失败 → `unavailable` → 「原确认已保存，当前有效性尚未核实。」**不写 current**。初始 `validity===null` 为「正在核对」。

冻结 `it.each` 覆盖 current/stale/superseded/unverified。滞后：先显示核对中，再异步结果；失败不升格为 current。

#### 6. FactBinding legacy fallback 与整值 compound

`fact_bindings.py:266-278, 82-86`：先读 `canonical_path` 再 `legacy_canonical_paths`；多 key 值不等 → `fact_alias_conflict`。无 legacy 时 `_binding_material` 弹出该字段，旧 hash 材料不变。

catalog 三整值（`test_chapter_fact_binding.py:350-357` + scratch）：

| fact_path | canonical | legacy |
|---|---|---|
| `picos.intervention_dose_regimen` | `intervention.dose_regimen` | 自身 |
| `picos.intervention_dose_regimen.selected_regimen` | 同上 | 自身 |
| `synopsis.interventions` | 同上 | `picos.intervention_dose_regimen` |

`value_type=json`，不拆角色/剂量数字。`affected_chapter_fact_paths({intervention.dose_regimen})` 含这三项。compound 与 legacy 字面值冲突可检出。

**不是产品默认 10mg：** catalog **没有** `picos.intervention.dose`。该键只出现在旧测试 fixture `integration_shared.FACTS`。改它的 affected 为空。

`picos.intervention_dose_regimen.starting_dose` / `maximum_dose` 仍指向**自身** json 槽，不并入 compound（合同已列 role-aware dose 细项未完成）。

`synopsis.interventions` 若**只**作为 vocabulary 键存在、没有 canonical/legacy 键，`available=[]`，**不会**回退读该字面键。

---

### Inference

先前否决点 1–5 的主修复在合成路径上成立：study-bound 读集进入模型身份；prepare 不派模型；原 key 在后继 phase 后仍能找回且不重派原 body；fresh 采用核对生成时 clinical facts；all_facts 只给真正读全集的生产者；普通 ref 序列化保持旧形；receipt 显示按原 decision id，失败不冒称 current；三整值别名指向已采用 compound，并做显式冲突。

剩余本路径缺陷（不能用「未完成 Word/七类决策」盖住）：

1. **source-only 采用仍跳过目标/临床校验**（`study_input.py:16-18`）。study-bound UI 还可能导入无 study 字段的 legacy `runId`，或 pending 无 intent 时用 seed 串到 source-only recover。结果：对已有临床事实的 study，仍可能采用**从未读过这些事实**的旧生成。
2. **vocabulary 键 `synopsis.interventions` 单独存在时不是 fallback**；只有列出的 legacy 路径会读。与「漏别名」相关，但低于上一项。
3. starting/maximum dose 细项未并入 compound：已知未完成，不是这次回归失败。

不要把禁止一切既有研究更新资料当成常规解法：官方 `/inputs` 与后继 phase 后「新 prepare → 新 key、旧 key 仍可 recover」是正确分叉。

---

### Recommendation

按严重性、最小修复（不扩 Word / 七类决策 / 医学准入）：

1. **P1 科学采用** `study_input.py:16-18` + `design.py` fresh 采用：当前 study 若已有 clinical facts，source-only run 不得采用（409，保留原建议）。不要禁 `/inputs`。
2. **P1 前端恢复体** `RegimenDesignWorkspace.jsx:64`：study-bound 会话 recover/start **必须**带 `study_definition_id` + `expected_workflow_run_id`；缺 intent 则当未知，禁止 `seedRunId` 回落。L31 导入 source-only `runId` 时，进入采用前须再 prepare study-bound key，或只展示、不启用 AdoptionCard。
3. **P2** 若需 `synopsis.interventions` 字面历史：把该 path 列入其 `legacy_canonical_paths`，并保留与 compound 的冲突检测。
4. **P3 / 已知范围** role-aware dose 细项、option/claim、其余决策、章节、Word：保持未完成，不在本路径标可用。

---

### Uncertainty

- 未做真实双线程 start 竞态
- scratch 前端 vitest 因仓库外路径未跑；localStorage quota 为源码推断
- 空 expected recover 在**后继 facts 之后**会找当前新 key（可能 404），不找旧 run；这与「必须带原 key」一致，但 UI 若丢掉 intent 会表现为「找不到」
- 无本角色浏览器终验
- 合成 fixture + fake HTTP，无真实模型

---

### 有限接受 / 未决

**有限接受（工程合成，非医学/Word）**

- study-bound 身份随 study/clinical facts 变 key；source-only 旧 key 不变；producer 元数据不变 key
- /prepare 不生成；错目标/错 seed/未知 key/空参数拒绝；原 key 在 SQLite 后继 phase 后可 recover/复用且原 body 不重派
- study-bound fresh 采用校验生成读集；增删临床键 stale；历史 receipt 不回退
- 普通 fact ref 序列化无 scope；all_facts 仅 study-bound 生产者
- 有效性按原 decision id；读失败不标 current
- 三整值别名指向 compound；无 legacy 时 hash 材料不含该字段；compound/legacy 冲突可检出
- 冻结 66 + vitest 17 + node:test 8；hash 19/19

**未决（本路径仍应修）**

- source-only 采用跳过临床读集；UI 可能把 source-only run/seed recover 送进已有临床事实的 study
- `synopsis.interventions` 仅 vocabulary 键时无 fallback
- role-aware dose 细项、option/claim、医学准入、其余 7 类决策、全章节、Word

**不要**：把 `picos.intervention.dose = 10 mg` fixture 说成产品自动默认剂量；不要建议禁止既有研究更新资料作为常规解法。
