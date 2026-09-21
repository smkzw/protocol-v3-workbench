审阅完成，所有关键路径已实证。以下是完整报告。

# Conference Participant Output: mw_r11_human_reconfirmation_review_20260921 - general_single_object

## Boundary Check

- 仅读取了初始阅读集指定的两份文件与 git diff 范围内的 11 个源文件；为验证调用链额外只读了 `medical_writing_condition_term_resolver.py`、`writing_reference_repository.py` 的相关片段（只读，属于证据补充，未越出工作区）。
- 未修改任何仓库文件；未读取其他参会者输出；未访问网络；未触碰生产路径与 live 服务（测试运行仅使用仓库内既有 venv `runs/mw_protocol_v3_1r_integration_20260905/venv` 和 tempfile）。
- 报告由本消息返回，未写入 runner 管理的报告路径。
- 不主张最终验收；Codex 保留最终决定权。

## Independent Work Product

**审阅方法**：通读全部 diff（938 行新增）→ 追踪 reconfirm 全链路（contracts → service 事务 → journey 投影 → endpoint → 前端状态机）→ 对照测试 → 用可执行复现脚本实证了两个可疑缺陷（复现脚本为内联 heredoc，未落盘仓库）。

### 一、核心不变量验证（通过，有证据）

1. **不重复 AI/检索/下载/OCR/翻译：成立。** `reconfirm_basket` 的完整调用面为：repository 读（run/confirmation/snapshot）→ `journey_service.get` → `build_competitor_search_request`（纯构建，内部 `resolve_clinicaltrials_condition_term` 是确定性本地别名词表，无网络；已核 `medical_writing_condition_term_resolver.py:132` 起）→ `_atomic_human_reconfirmation`（本地 SQLite BEGIN IMMEDIATE）→ `project_human_reconfirmed_basket`（本地 SQLite，revision+1，事件记录 `external_work_repeated: False`，`searched_at=snapshot.created_at` 沿用原检索时间）→ `_project_corpus` → `finalize_corpus_triage`（本地 SQLite，幂等）。路径上无 provider/HTTP/registry 调用。
2. **不推进父研究流水线：成立。** 端点显式返回 `pipeline_advanced=False` 且不调用 `advance_after_basket_confirm`；测试 `test_reconfirm_reuses_existing_work_without_advancing_pipeline` 用 mock 断言 `advance_mock.assert_not_called()`。
3. **快照身份与新鲜度：成立。** 重绑前验证 `snapshot.request == build_competitor_search_request(...).search`（当前检索契约仍匹配）；重试路径 `_confirmation_stale_reason` 对 human_reconfirmation 校验 `_snapshot_hash(snapshot)==run.snapshot_hash` 且 facts 哈希（按确认时 revision 折算）未再变化；journey 侧 `latest_snapshot_id` 守卫阻止绑到别的快照。
4. **确认谱系与幂等：成立。** 新确认 `ct_reconf_{hash}` 携带 `confirmation_kind`、`source_confirmation_id`、`confirmed_material_facts_hash`、`confirmed_search_plan_id`；同请求同 hash 确定性 ID；BEGIN IMMEDIATE 事务内先查 replay、再查同内容不同键去重；同键不同材料由 `_idempotent_result` 抛 `WritingReferenceConflictError`→409。逐候选 relevance decision 在同一事务写入，reason 含“来源确认 X。原AI分类 Y，本次确认 Z”谱系。
5. **前端交互：基本达标。** `payload.reconfirmation.required` 时预选完整替换为 `final_classifications`；`current_triage_criteria` 以 bullets 渲染；确认入口唯一（`reconfirm`）；文案明示“不会重复调用AI/未重复运行AI或原文处理”；复核期间解除锁定、隐藏手工定稿入口；两个 GET 路由（`latest`、`{run_id}`）均走已打补丁的 `get_run`，前端接线完整。
6. **定向测试实测通过**：`tests/test_medical_writing_competitor_triage.py -k "reconfirmation or all_excluded or ProjectionRetry"` 34 passed；`tests/test_medical_writing_triage_recovery_api.py` 11 passed。

### 二、发现（按影响排序）

**F1（高）重绑投影失败后 run 状态不变，UI 进入死角。** 已用运行时复现证实：reconfirm 投影失败时端点返回 200（`projection_status=failed`），但 `reconfirm_basket` 的 except 分支不改 run 状态——run 仍是 `confirmed`，且新确认使 `reconfirmation.required=False`。结果前端：横幅“已确认锁定”（WritingReferencePanel.jsx:1461）、“重试同步”按钮不渲染（:1472，仅 `projection_pending` 显示）、reconfirm 区块隐藏（required=False）——而 journey 的 `discovery_basket_projection` 实际为空（事实变更 commit 会清空旧投影）。重复点击确认只会走 replay 返回同一条 failed 确认、不重试投影（复现 E 步实证 `projection retried = False`）。后端 `projection-retry` 本可修复（复现 F 步：直接调用后 `corpus_projected`、journey 正确重绑），但 UI 无任何入口。对照：初次确认路径 `_project_discovery_basket`（:6025-6044）失败时置 run→`PROJECTION_PENDING`，这正是现有 UI 重试按钮的数据来源；reconfirm 路径漏掉了对称处理。前端另有一点：成功消息（:987）不检查 `confirmation.projection_status`，投影失败时也报“已按当前研究信息确认……”。

**F2（中）初次确认后可能立即出现假阳性“需重新复核”。** 已实证 `_material_facts_hash` 把 `journey_revision` 计入哈希材料（revision 1→2 仅改 revision，哈希 `2beb6787…`→`fb511ffb…`）。初次确认存 `confirmed_material_facts_hash=run.material_facts_hash`（含 run 创建时 revision），而 `_reconfirmation_status` 用 `confirmation.journey_revision`（确认时 revision，`confirm_basket` 不校验它与 run/当前状态的关系）折算当前哈希。凡 run 创建到确认之间 revision 有过无实质变化的前进（`_stale_reason` 注释 :5045-5053 明确承认这是合法场景，如派生标题采用），确认完成即 `required=True`，用户刚确认就被要求再确认。方向是 fail-safe，但破坏“一次确认”承诺。修复取最小：initial 确认在 `_reconfirmation_status` 中按 `run.journey_revision` 折算比较基准。

**F3（低）端点异常映射缺口。** `reconfirm_competitor_triage_basket`（main.py:8772）未捕获 `MedicalWritingAuthoringJourneyConflictError`（继承 ValueError，非 CompetitorTriageError 子类）→ `build_competitor_search_request` 的冲突（检索契约不完整/竞态换计划）和 `project_human_reconfirmed_basket` 事务内竞态（"search plan changed during re-review"等）会 500 而非 409。另：projection-retry 端点把 stale 映射为 422（confirm 端点映射 409）——属既有不一致，但 reconfirmation 语料重试现在也会抛 stale，前端按 422 文案处理需确认可读。

**F4（低）审计文本失真。** `_project_corpus`（:6065-6069）对 human_reconfirmation 也写"AI triage confirmation ct_reconf_…"；全排除篮子现因理由改为可选，`finalize_corpus_triage` 的 reason 取 `confirmation.no_suitable_competitor_reason` 可能为空串。建议按 `confirmation_kind` 区分文案并回退到 `confirmation.reason`。

**F5（低）PROJECTION_PENDING run 重绑成功后状态残留。** 初次投影失败（run=projection_pending）后事实变更→重绑成功，run 仍停在 projection_pending，横幅“正在同步到写作旅程”失真。reconfirm 成功路径应置 run→CONFIRMED。

**F6（测试缺口）** 以下路径无测试：重复 reconfirm（同键 replay 与新键同材料去重）、reconfirm 投影失败 + `_retry_discovery_projection` human 分支（完全未覆盖）、`snapshot.request != expected_search` 冲突、`_confirmation_stale_reason`（重绑后事实再变、语料重试被阻）、谱系链（对 reconfirmation 再 reconfirm）、retained/excluded 重复 ID 校验。F1/F2 若有对应测试本可被拦截。

**F7（有意放宽，请 Codex 确认授权）** `validate_all_excluded_reason` 合同校验器被删除，服务层 10 字实质理由检查改为服务端默认文案（“医学经理确认本次候选均不适合……”），前端字段改为可选；测试同步改写（`test_all_excluded_reason_is_optional`）说明本轮有意。但影响面是**初次 AI 辅助确认的既有 API 合同**，不只是 reconfirm：全排除确认不再强制用户留实质理由，审计只落通用默认文案。Checkpoint F04 记载“不少于10字”移除仅限用户简述流程且“未改全仓其他有独立业务含义的旧合同”，与本改动存在表述张力，需要显式确认。

**F8（信息）** `journey.search_plan is None` 时 `required=True` 且横幅文案“当前研究信息已更新…请确认”，但 reconfirm 动作会 409"current competitor search plan is missing"——该边缘下提示误导。`triage_confirmation_for_run` 排序无次级 tiebreaker（同微秒 created_at 理论歧义，实际可忽略）。`project_human_reconfirmed_basket` 重置 corpus_triage/picos alignment、沿用 corpus gate——与 checkpoint“篮子变更需重新语料准入、Study A 停在 corpus admission 前”的意图一致。

## Evidence And Assumptions

- **观察（实测）**：34+11 定向测试通过；F1/F2 复现脚本输出（`run.status = confirmed` / `reconfirmation.required = False` / `journey bound to = ''` / `projection retried = False`；revision-only bump 改变 facts 哈希）为直接证据。
- **源码事实**：`_material_facts_hash` 含 revision（medical_writing_competitor_triage.py:501）；`confirm_basket` 记录 `confirmed_material_facts_hash=run.material_facts_hash`（:5435）且不校验 `expected_journey_revision`；`reconfirm_basket` 失败分支只写 confirmation（:5636-5648 附近）；`_retry_discovery_projection` human 分支（:6235-6252）；`resolve_clinicaltrials_condition_term` 为本地表（resolver 模块头注释明示 deterministic/fail-open）。
- **推断**：F1 的用户影响为“静默分歧”——UI 显示已锁定而 journey 无活动篮子；后果在下一次 corpus admission 才暴露。标注为推断，因为未做浏览器端验证（超范围）。
- **假设**：以 `git diff HEAD` 冻结态为审阅对象；`runs/` 下 dirty 运行时文件不属审阅范围（按 context 声明）。前端 110 Vitest 通过为 context 声称、本会话未复跑全量，仅复跑了本 diff 触及的 Node 测试文件。

## Risks, Gaps, And Verification Needs

1. **最高风险（F1）**：Study A 真实使用中，若重绑投影一旦失败（竞态、快照契约漂移、并发确认），用户界面将永久显示已锁定且无恢复入口，而 journey 实际没有篮子——这与本轮“受控重绑、状态一致”的目标直接冲突。验证需要：修复后补一条“reconfirm 投影失败→run=projection_pending→projection-retry 成功→run=confirmed”回归测试，并做一次真实浏览器故障注入（Codex 权限）。
2. **F2 修复选择**是行为决策：(a) 仅在 `_reconfirmation_status` 对 initial 确认改用 `run.journey_revision` 比较（最小）；(b) 同时在 `confirm_basket` 校验 `expected_journey_revision==当前 revision`（更严但可能新增 409）。我建议 (a)，(b) 可选。
3. F7 若 Codex 判定不应放宽 initial 合同，需恢复校验器并在前端还原必填；若判定放宽是本轮授权，建议在 checkpoint 补一句授权记录，消除与 F04 注记的矛盾。
4. 未验证项：前端组件级预选交互（仅有 presentation-state 单测）；`MedicalWritingAuthoringJourneyConflictError` 500 路径未实际触发复现（属代码路径推断，证据充分）。

## Recommended Next Step

给 Codex 的三个有界决策问题（均有安全暂定路径）：

- **Q1（对应 F1/F5）**：是否授权在 `reconfirm_basket` 失败分支置 run→`PROJECTION_PENDING`、成功分支置 run→`CONFIRMED`（镜像 `_project_discovery_basket` 的既有语义，前端无需改动即恢复重试入口）？暂定路径：未答复前不修改，本发现列为 P1 待办。
- **Q2（对应 F2）**：假阳性修复选 (a) 比较基准改用 `run.journey_revision`（推荐，最小），还是 (b) 加严 `confirm_basket` 的 expected revision 校验？暂定路径：维持现状（fail-safe 方向，仅 UX 损害）。
- **Q3（对应 F7）**：初次确认“全排除理由”放宽为可选是否为本轮授权的产品决定？暂定路径：按现状（已测试、有默认审计文案），但请在 checkpoint 记录决定与理由。

下一步安全动作：Codex 裁决 Q1–Q3 后，owner 按裁决做最小修复，并补 F6 所列缺失回归（优先：reconfirm replay 去重、投影失败+重试链路、`_confirmation_stale_reason`），再跑集中受影响测试矩阵。
