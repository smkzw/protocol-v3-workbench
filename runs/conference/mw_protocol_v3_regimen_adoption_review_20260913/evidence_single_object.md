先读完整上下文合同与计划，再独立核对接药设计采用与只读回执恢复的证据链。上下文合同已读。接下来核对 artifact manifest、相关计划与审阅目录，锁定本次冻结范围。先做哈希复核并拉取计划中的采用段落，再逐项读源码与测试。哈希全部匹配。接着读源码、测试与计划中的采用段落，核对持久化与恢复边界。命令层已看完。接下来审 `ApplicationService` 的采用、恢复与回放实现，并对照前端确认路径。后端 9 项通过、1 项断言过严；前端现有测试已过，但 scratch 探针可能没被 vitest 收录。接着核对事件落库并单独跑前端探针。# Conference Output: mw_protocol_v3_regimen_adoption_review_20260913 - evidence_single_object

## Output

独立审阅结论：冻结给药采用链在「已存 run → 服务端编译事实 → 显式用户 CAS → SQLite 一次事务 / 精确回放保留后继 / 只读 recover 不加载当前模板 / 前端先落 intent、UNKNOWN 不重派」上，定向测试与独立反例均成立。本单元**不能**当作当前确认有效、RecommendationOption/ClaimEvidenceLink 持久化、或真实浏览器采用已完成。历史真实 glm 回执是 `needs_information`，后端与前端都不会自动采用。

未改产品、未跑真实模型、未开 live 服务/浏览器。制品哈希复核 23/23 匹配。

---

### Evidence

**哈希**  
`artifact_manifest.json` 23 个路径 SHA-256 初核与终核均为 mismatch=0。审阅只写了 `runs/conference/mw_protocol_v3_regimen_adoption_review_20260913/scratch/`。

**来源绑定（服务端，不信浏览器事实）**  
- `RegimenAdoptionRequest` `extra=forbid`，无 `fact_updates`/`regimen` 字段（`api/design.py` 17–25 行）。  
- `prepare_regimen_adoption` 只从 `coordinator.read(run_id)` 取已存 `proposal`（`agent2/study_definition.py` 22–39 行）。  
- 独立探针：请求夹带 `fact_updates`/`regimen` → HTTP 422，SQLite dump 不变。

**未决设计不可采用**  
- 命令层：`needs_information`/`blocked`/`needs_structure_correction` 抛 `regimen_information_unresolved`（`test_regimen_adoption_command.py` 34–40 行）。  
- API：`status != ready_for_review` → 409「给药建议尚有未决内容，当前研究事实未改变。」（`api/design.py` 79–81 行）。  
- 探针：`needs_information` 采用 409；同 intent 的 recover 因仍走 `prepare_regimen_adoption` 得到 **422**；dump 不变；模型 opener.calls==1。  
- 前端：`canConfirm` 要求 `proposal.status === "ready_for_review"` 且无 pending（`RegimenProposalCard.jsx` 147–153 行）。

**CAS / 回放 / 只读恢复**  
- 用户 intent 携带 `expected_revision` + `snapshot_sha256`；`apply_decision` 仅在 ledger 无该 CAS 时校验当前 revision/snapshot，并仅在此时加载当前模板（`application/service.py` 468–511、986–1010 行）。  
- `recover_decision` 文档与实现：不加载当前模板；ledger 未命中返回 None→404（625–657、89–97 行）。  
- 已有集成：未知 recover 404 且无写；采用后 recover/replay `replayed=true`、dump 不变、opener.calls==1。  
- 独立探针：采用 rev2 后另写无关事实到 rev3；再 recover/replay 原给药 intent → `revision==3`、`replayed=true`、后继 `picos.population.age` 仍在、原 `effective_decision.decision_record_id` 保留；此后把 `load_current_template` 打成 `OSError`，recover/replay 仍 200，loader 计数不再增加。  
- 剂量 native int：探针与 `test_regimen_fact_adoption.py` 均见 `dose.value is int`。

**模板配置失败的 HTTP 分类（新反例）**  
- 给药命令**总是**带 `TemplateAdoptionIntent(template_id="tp_ma_07_v2")`（`study_definition.py` 38–39 行）。  
- 当前模板不可用 → `_CurrentTemplateUnavailableError` → `P1_SERVICE_CONFIGURATION_INCOMPLETE`、`retryable=False` → `_status_for` 落到 **HTTP 500**（`service.py` 1251–1260 行；`router.py` 168–176、140–145 行）。  
- 探针：`test_fresh_adopt_with_missing_template_does_not_write`：adopt=500，recover=404，dump 不变。写发生在模板校验之后，故这次 500 实际是「未提交」。

**输入绑定实际内容**  
SQLite `event_stream.body_json` 中 `decision_input_binding` 仅为：

```json
"refs": [{"fact_path": "intervention.dose_regimen", "members": []}]
```

`fully_known=true`，绑定的是采用**之后**写入的同一事实。事件公开 API 是摘要（`event_count`/`decisions[].selected_option_id`），不含 RecommendationOption / ClaimEvidenceLink。dump 中无这两类对象文本。`option_ids` 为 `regimen-option:` + sha256(run_id, output_sha256)。

**前端 intent / UNKNOWN / StrictMode / 切 ident**  
- 采用前先写 `localStorage` 再 `setIntent` 再 mutate（`RegimenAdoptionCard.jsx` 63–75 行）。设计任务同样先 `{pending:true}`（`RegimenDesignWorkspace.jsx` 84–89 行）。  
- 4xx∈{400,404,409,422} 清活动恢复指针、不自动再 adopt；其它状态保留 intent，只读 recover（79–87 行）。  
- 已有测试：重开只 recover、不确定提交不二次 adopt、409 后新 operation+新 snapshot、假 rev1 回执不显示「本次选择已保存」。  
- 独立探针 4/4：StrictMode 下 adopt 1 次；study 切换后迟到回执不显示已保存；500 后 404 lookup 仍禁用确认且不再 adopt；丢失 ACK 在 StrictMode 下只 start 1 次、随后 recover。  
- `AdoptionSession`/`DesignSession` 用 ident `key` 重挂。

**产品页未接 StudyDefinition / actor**  
`App.jsx` 15900：`<ProtocolIntakeWorkspace key={activeProjectId} projectId={activeProjectId} />`。未传 `api`/`studyDefinitionId`/`actorId`。缺后两者时只渲染无 `onConfirm` 的 `RegimenProposalCard`，确认钮禁用（`RegimenDesignWorkspace.jsx` 114–118 行）。设计 run 身份是 project+seed，**不**绑定 study。

**测试计数（非验收）**  
- 既有 pytest 6 passed；独立 pytest 探针 5 passed。  
- 既有 vitest 26 passed（4 文件）；`node --test` protocolSourceApi 6 passed；独立前端探针 4 passed。

命令：

```text
PYTHONPATH=services/api:tests:tests/protocol_v3:tests/protocol_v3/integration:.
PYTHONDONTWRITEBYTECODE=1
python3.12 -m pytest -p no:cacheprovider <existing 3 files + scratch probe> --basetemp=scratch/pytest-tmp
frontend/node_modules/.bin/vitest --environment jsdom --run <4 jsx test files>
node --test frontend/src/features/medical-writing/protocol-workbench/protocolSourceApi.test.mjs
frontend/node_modules/.bin/vitest --config scratch/vitest.config.mjs --run
```

日志：`scratch/probe_run_log.json`、`scratch/probe_option_persistence.json`。

---

### Inference

1. **输入绑定目前是自指，不是推荐生产者的完整 read-set。** 采用后 `current_input_validity` 只能发现有人改了 `intervention.dose_regimen` 本身；seed `input_sha256`、source 身份、design `output_sha256` 变化不会把该确认打成 stale。这与设计 v1.4「producer 须从实际上下文构造完整引用」不一致。`option_id` 虽含 run+output hash，但不进入 `DecisionInputRef`，也不进入当前确认投影。

2. **模板配置失败被标成「提交结果未知」。** 给药采用每次都走模板绑定；模板缺失时未写入却返回 500。前端把非 4xx 当 UNKNOWN，保留 intent、只允许核对；recover 404 后确认钮一直禁用，用户无法放弃该 intent，除非清 localStorage。这不是「配置错误不要叫用户重新确认医学推荐」，而是把确定的配置失败说成未确认提交。

3. **只读 recover 仍要当前设计能再次 `prepare_regimen_adoption`。** 因此 `needs_information` 的 recover 是 422 不是 404。已提交回放依赖「再编译的 fact_updates / option_id 与 ledger 哈希一致」。输出制品若不变则稳；编译器一变，recover 会 `DecisionPayloadConflictError`→409，前端 recover 路径不会清 intent，核对卡死。现有 frozen 编译下未触发。

4. **「本次选择已保存」是该 operation 的回执，不是当前批准。** recover 正确返回后继 definition + 原 `effective_decision`。卡片主状态仍是已保存，没有查 `current_input_validity`。后继若修订了给药，UI 仍像这次确认有效。文案有一句免责，但没有当前有效性。

5. **RecommendationOption / ClaimEvidenceLink 未落库是范围，不是回归。** 合同里有类型；本单元只持久化 DecisionRecord 的 option id 哈希 + 复合 `intervention.dose_regimen`。公开 events 只有 decision 摘要。

6. **真实浏览器采用尚未接线。** 这是预期 pending，不是后端采用函数错误。一旦 App 传入错误的 `studyDefinitionId`，同一 project 下可以把该设计写进另一份 study——服务端不校验 design run 与 study 的从属关系。

---

### Recommendation

本冻结单元：**工程上可以采用已存、已 `ready_for_review` 的设计到指定 StudyDefinition，并做精确回放/只读对账**；**不要**登记为当前确认有效、选项/证据链持久化、或产品路径采用通过。历史 `needs_information` 真实 run 不得自动采用——已有闸门，应保持。

**最高影响缺陷（已交付行为，不是「以后再做」的空范围）：**

| 级别 | 缺陷 | 位置 | 复现 | 修复 |
|---|---|---|---|---|
| P1 | 输入引用只有被写入的 `intervention.dose_regimen`，当前确认无法感知来源/seed/run 漂移 | `study_definition.py:39`；SQLite binding 见 `scratch/probe_option_persistence.json` | 采用成功后 binding.refs 仅该 path；改 seed/source 不会 stale | `prepare_regimen_adoption` 从已存 prepared request/raw_response 构造 refs：至少 `output_sha256`、seed `input_sha256`、source artifact id+hash。不要让客户端交 read-set |
| P1 | 当前模板缺失时 fresh adopt=500（未写）+ 前端当 UNKNOWN | `service.py:1251-1260` + `RegimenAdoptionCard.jsx:79-87`；探针 `test_fresh_adopt_with_missing_template_does_not_write` | 打爆 `load_current_template` 后 adopt 500、recover 404、dump 不变 | 配置类失败用确定 4xx/503 公共包（「服务配置不可用，本次未保存」），**不要**用「结果尚未确认」。前端对该状态清活动指针或提供放弃，且 next_step 不得是重新确认医学推荐 |
| P2 | recover 必须重编译当前 ready 设计，未决变成 422 而非「无回执」 | `api/design.py:86-93` + `prepare_regimen_adoption` 24-25 行 | needs_information + `/adopt/recover` → 422 | recover 只按 intent 的 operation/CAS 查 ledger；找不到 → 404；不要为了 lookup 再要求 `ready_for_review` |
| P2 | 历史回执 UI 易被当成当前批准 | `RegimenProposalCard.jsx:177,190` | 后继 revision>原结果后 recover 仍显示「本次选择已保存」 | 回执与当前有效性分开：仅当 `revision == expected+1` 且 validity=current 才说当前已确认；否则「原确认记录已保留，当前研究已有后继」 |

**不要在本轮做的：** 安全专项、真实模型、OCR、清档、把测试计数当验收、给 `needs_information` 编临床理由以便采用。

---

### Uncertainty / pending（与缺陷分开）

- **预期 pending，不是本单元回归：** RecommendationOption / ClaimEvidenceLink 持久化；产品 `App.jsx` 未传当前 `studyDefinitionId`/`actorId`；真实浏览器采用；整稿/Word；picos 等同源投影；II/III 全路径。  
- **Study 父绑定现状：** 采用目标 study 来自请求/props，不来自已存 design run。当前产品页因此根本走不到 AdoptionCard。接线时必须规定「当前 study」如何取得（已有唯一 study vs 先创建），并应把 study id 写进 design 身份或服务端校验。  
- **未做：** 真浏览器、并发双飞 HTTP、真实 glm 再跑、生产库。`can_resume=true` 每次重挂会再 resume 一次——测试第二次挂的是 blocked，不是持续 resumable。  
- **旧评审自述不作为通过证据。**

---

### Coverage matrix

| 边界 | 状态 | 依据 |
|---|---|---|
| 已存设计→DecisionRecord/SQLite，不信浏览器事实 | 通过 | 代码 + 422 extra-field 探针 + 既有 HTTP 采用 |
| 复合 4 期组 / 8 步 / native int | 通过 | fact_adoption + 后继探针 |
| 精确回放零新效果 | 通过 | 既有 API 测试 |
| 回放保留合法后继，不回退 revision | 通过 | 后继探针 rev3 |
| 只读 recover 不 apply、不加载当前模板 | 通过 | recover 404；后继+boom loader |
| 未知 commit 不自动重派 | 通过 | 设计/采用前端测试 + StrictMode 探针 |
| 未决/needs_information 不采用 | 通过 | 409 探针；真实 run 按合同不得采用 |
| 显式用户 CAS | 通过 | intent snapshot/revision；stale→409 前端测 |
| 4xx 确定 vs 5xx 未知 | **部分失败** | 模板配置未写却 500 |
| 不可变输入绑定（生产者完整引用） | **失败** | 只绑输出 path |
| 正确类型 / 不造假事实 | 通过（本单元） | 未决不写；string 剂量拒收（既有 worker 测） |
| 假已保存标签 | 通过 | rev1 回执测试 |
| StrictMode / 切 project·study·run | 通过（组件测） | ident key + 探针；产品 App 未接 study |
| RecommendationOption/ClaimEvidenceLink | 未实现（pending） | 事件/SQLite 无对象 |
| 当前 Study 父绑定 / 真浏览器采用 | 未实现（pending） | App.jsx 15900 |
| II/III 全路径 / 整稿 Word | 未实现（pending） | 合同 |

---

### Objections / solutions / Codex decision points / bounded questions

**反对把「合成 HTTP 采用 + 精确回放已验证」升级为本单元科学验收。** 回放与 CAS 成立，但当前确认有效性的输入引用不覆盖产生该推荐的资料/seed/run。这不是空范围，是已写入 ledger 的绑定形状。

**反对把模板 500 解释成 UNKNOWN 提交。** 探针证明无写；前端会按未知提交锁死 intent。

建议的安全暂定路径（在 Codex 裁定前）：保持 `needs_information` 不可采用；不要把该冻结包标产品采用完成；先修绑定形状和配置错误分类，再接 App 的 study/actor。

请 Codex 裁定：

1. P1 输入引用：本冻结包是否必须补上 seed/source/output 引用，还是明确推迟到 5R producer 覆盖测试、本包只保证「写了什么 fact」？**影响本包能否称「输入绑定完成」。**  
   暂定：未补前不得称当前确认有效。

2. 模板配置 HTTP：是否把 `P1_SERVICE_CONFIGURATION_INCOMPLETE` 从 500 改为确定 4xx/503，并让前端清 UNKNOWN 指针？**影响丢失 ACK 语义。**  
   暂定：按确定失败处理；next_step 不得为重新确认推荐。

3. 产品接线：当前 study 是「项目下已有唯一 StudyDefinition」还是采用前先创建？是否要把 `study_definition_id` 打进 design run 身份？**缺了就不能做真浏览器采用。**  
   暂定：未接线前 AdoptionCard 不可达是 pending，不是后端绿测失败。

4. recover 是否改为纯 CAS lookup（未决 → 404 而非 422）？  
   暂定：lookup 与 apply 闸门分离。

非主席，不宣布 Codex 终局或临床/监管/真浏览器验收。
