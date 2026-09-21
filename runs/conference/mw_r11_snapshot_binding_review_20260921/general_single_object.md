所有证据已收集完毕。以下是完整审阅报告。

---

# Conference Participant Output: mw_r11_snapshot_binding_review_20260921 - general_single_object

## Boundary Check

- 本次审阅为只读：仅使用 Read/grep/sed/`git diff`/`ast.parse`/`git diff --check`。未修改任何源码、测试、SQLite、运行态文件；未打开任何 SQLite/WAL/SHM/凭据/供应商设置文件；未运行任何测试、模型、检索或浏览器流程。
- `runs/.../recovery-result.json` 中记录的两个 pre-recovery 备份仅核对收据内声明的存在性与哈希字段，未打开备份本身(超出授权读取清单)。
- 未写入 runner 管理的报告路径；完整报告在本消息中返回，由 runner 持久化。
- 未读取 `/Users/smkzw/.codex/AGENTS.md`、`/Users/smkzw/.hermes/SOUL.md`;初始读取集之外仅追加了必要的源码契约文件(`packages/contracts/workbench_contracts/models.py`、`services/api/app/writing_reference_repository.py`、`services/api/app/medical_writing_condition_term_resolver.py`、`services/api/app/medical_writing_authoring_prefill.py`、`services/api/app/main.py`、`services/api/app/medical_writing_research_pipeline.py` 的相关片段)以闭合 (a)–(e) 的证据链。
- 本报告不构成最终验收；Codex 保留最终权威。

## Independent Work Product

**总体结论：五项判定全部 PASS(其中 (e) 为“结构一致 PASS + 数值真实性 UNVERIFIED”),另提出 1 项设计级异议、2 项健壮性/测试缺口、3 项观察。**

### (a) 同 registry_filter 的 framing 编辑保留不可变快照并刷新分诊标准 — **PASS**

- `commit_stage` framing 分支对所有 framing 提交统一走新助手:`services/api/app/medical_writing_authoring_journey.py:1487-1495`(传入 `previous=current.search_plan`、当前投影与 corpus triage)。
- `_rebuild_search_plan`(`medical_writing_authoring_journey.py:5058-5108`):先用 `medical_writing_competitor_search_contract` 全量重建;仅当 `previous.registry_filter == rebuilt.registry_filter` 且已有绑定时(`:5080-5083`)保留 `latest_snapshot_id/returned_count/public_document_count/searched_at`(`:5101-5108`),而 `triage_criteria`/`queries` 来自新构建 —— 即“快照保留、标准刷新”精确成立。
- 同源性论证(本判定的安全基础):`registry_filter` 仅由 `(解析后 condition_term, phases=f(study_phase), 固定 INTERVENTIONAL, [], [])` 构成(`packages/contracts/workbench_contracts/models.py:5361-5400` 及 `_medical_writing_ctgov_phases`),而真实注册检索请求 `build_competitor_search_request`(`medical_writing_authoring_journey.py:2996-3043`)的字段全部取自同一 plan filter 加上同一纯函数 resolver(`medical_writing_condition_term_resolver.py:132-167`,别名表+字符串判断，无 I/O、确定性)。因此对已提交 framing,filter 相等 ⟺ 请求相等；分诊-only 编辑(如 `administration_routes`,仅进入 criteria,`models.py:5449`)不会改变请求。
- 测试 `test_framing_triage_change_preserves_matching_registry_snapshot`(`tests/test_medical_writing_authoring_journey.py:2156-2216`)断言 plan_id 变化、filter 相等、快照保留、`口服` 进入新 criteria、状态 `triage_pending`,与代码分支(`:5095-5100`,无确认投影且 returned_count>0)一致。
- 变更 filter 时返回干净计划(status `planned`、`latest_snapshot_id=""`),绑定清除，需重新检索 —— (b) 成立(见下)。

### (b) registry_filter 变化仍清除绑定 — **PASS(代码路径；测试缺口见 Risks)**

- `medical_writing_authoring_journey.py:5080-5083`:filter 不等(含 `previous.registry_filter is None` 的失败闭合情形)即返回无绑定的新计划；旧快照成为孤儿，`create_run` 的绑定守卫(`medical_writing_competitor_triage.py:4091-4112`)与 `finalize_corpus_triage` 的绑定守卫(`medical_writing_authoring_journey.py:2626-2627`)共同强制重新检索后才能分诊。
- 全文件扫描确认 `latest_snapshot_id` 的写入点仅三处：attach(`:3128`)、restore(`:3274`)、rebuild(`:5103`);不存在其他静默清除或残留写入路径。API 层 attach 的快照由同一请求内 `create_search_snapshot` 新建(`services/api/app/main.py:8123` 上游)，不接受客户端传入旧快照 id。

### (c) 历史恢复只接受精确确认投影 + 匹配的注册请求 — **PASS**

`restore_confirmed_search_snapshot_binding`(`medical_writing_authoring_journey.py:3162-3306`)前置条件链：
1. 修订 CAS 预检与事务内复检(`:3175-3178`、`:3247-3253`),持久化再以 revision 条件更新兜底(`_persist_update`,`:5805-5816` rowcount 检查)。
2. 项目归属与计划存在(`:3187-3188`);已绑同一快照则幂等返回、绑异快照则冲突(`:3189-3196`)。
3. 投影四元组精确相等:`snapshot_id + confirmation_id + confirmation_hash + run_id`(`:3207-3217`),事务内复检(`:3260-3268`)。投影模型字段与写入端完全对应(`models.py:5517-5533`;`project_discovery_basket` 写入 `:2568-2578`)。
4. 注册请求仍匹配当前计划:`snapshot.request != build_competitor_search_request(...).search` 即拒绝(`:3219-3228`);快照不可变，无需事务内复检，计划变更必经 revision bump 已被 CAS 捕获。
5. 计数一致性 `returned_count == len(candidates)`(`:3229`)。恢复写 `status="triaged"` 并携带快照计数/时间(`:3271-3278`),事件 `authoring_journey_confirmed_snapshot_binding_restored`、`external_work_repeated: False`(`:3294-3304`)。
6. retry 侧追加双重门:`search_plan.latest_snapshot_id` 为空且 `projection.snapshot_id == run.snapshot_id`(`medical_writing_competitor_triage.py:5815-5820`),随后 `finalize_corpus_triage` 的绑定守卫(`:2626`)确保 finalize 只能落回该快照。

### (d) retry 全程无检索/模型/下载/OCR/翻译调用 — **PASS**

`retry_projection`(`medical_writing_competitor_triage.py:5740-5841`)仅含：确认/运行记录的库读(`:5749`、`:5758`)、journey 读(`:5760`)、restore 分支的 `repository.search_snapshot`(SELECT-only,`writing_reference_repository.py:1282-1285`)、restore(纯本地：构建请求 + 纯 resolver + 本库事务)、`_project_corpus → finalize_corpus_triage`(纯本地事务)。路径上不存在任何 provider、HTTP、下载、OCR、翻译调用点。restore 幂等性(同 idempotency key 重放、已绑定早退)与 finalize 幂等重放(`triage_corpus_{confirmation_id}`)保证重复 retry 不产生第二次外部工作。

### (e) Study A 收据与代码路径一致 — **PASS(结构)；数值真实性 UNVERIFIED**

对照 `runs/requirements_v2_20260919/f12_20260921/study_a_snapshot_binding_recovery/recovery-result.json`:
- `revision 20→22` = restore(+1)+ finalize(+1),恰好两步，无多余修订 bump。✓
- `latest_snapshot_id == corpus_snapshot_id == "wref_search_..."`:retry 门 + restore 投影相等 + finalize 守卫强制三者收敛于同一 id。✓
- `search_status: "triaged"`(finalize `:2654`/restore `:3273`)、`corpus_triage_status: "finalized"`(finalize `:2660-2672`)、`confirmation.projection_status: "corpus_projected"`(`_project_corpus` `:5717`)。✓
- `external_work_repeated: false` 与 restore 事件细节(`:3304`)及 (d) 的调用面分析一致。✓
- **UNVERIFIED 部分**(只读边界内无法核实):`retained_count: 59` 与快照/确认记录的实际数值、`projection_attempts: 2` 的两次增量的具体来源。代码中 attempts 仅在 confirm 期 discovery 投影异常(`:5680`)与每次 retry 入口(`:5768-5771`)递增；attempts=2 与“修复前一次失败 retry + 修复后一次成功 retry”或“confirm 期失败 + 一次 retry”均相容，收据本身不能区分。此不确定性不改变 PASS 判定(结构完全一致)，但审计叙述上应归属后才能声称“哪两次”。

## Evidence And Assumptions

**证据(观察/文件事实)**：四个文件 AST 解析通过、`git diff --check` 干净；上表所有 file:line 均取自当前工作区(HEAD `b14a56a` + dirty diff)。测试 helper 自洽性已验证：triage 测试复用 authoring 的 `_complete_framing`(`tests/test_medical_writing_competitor_triage.py:69`;`clinicaltrials_condition_term="Rheumatoid Arthritis"` 无 CJK → resolver 直返;`II期 → ["PHASE2"]`),`_make_snapshot` 的 request(indication+phases,其余取模型默认 `study_type="INTERVENTIONAL"`/`page_size=100`,`models.py:7991-7998`)与 `build_competitor_search_request` 产物逐字段相等 —— 即 retry 测试中 restore 的请求等价校验真实通过，不是被绕过。

**假设(已声明)**：
1. 假设收据由 owner 恢复脚本在修复后代码上运行产出 —— 收据无法自证；其与代码的结构一致性是本判定范围，真实性归属 Codex。
2. 假设 resolver 无隐藏状态(已读实现证实为纯函数)。
3. (a) 的“安全”以“注册请求等价 + 下游不丢失已确认投影”为准；分诊结果的医学新鲜度见 Risks 第 1 条，属设计异议而非实现缺陷。

## Risks, Gaps, And Verification Needs

1. **[最高影响异议 / P2 设计缺口] 标准“刷新”了，但旧标准下的确认结果未被标记过期。** `_rebuild_search_plan` 在 `has_confirmed_projection` 时保留投影与 `corpus_triage.finalized`,并把计划置为 `triaged`(`:5087-5094`)——若用户在 basket 确认或 corpus 定稿**之后**修改 `administration_routes` 等分诊标准，旧标准下做出的 retain/exclude 决策继续以“finalized”身份生效，无任何 stale 标记；framing commit 也不重置 `corpus_gate`。这不是本次修复引入的回归(旧行为更糟：直接毁掉绑定使投影死锁)，但修复把“陈旧标准 + 有效快照”变成了一个**稳定可达状态**而非死路。建议补救：在 `DiscoveryBasketProjection`/`corpus_triage` 记录确认时的 `triage_criteria_sha256`,重建时哈希不同则标记 stale 或要求重新确认(可复用 `package_is_stale` 的指纹模式，`medical_writing_authoring_prefill.py:273` 附近)。
2. **[P3 健壮性] retry 的 `discovery_projected/deferred_until_picos` 分支中，restore 调用是第一个可抛异常的调用且无 try/except**(`medical_writing_competitor_triage.py:5815-5833`;对比 `pending/failed` 分支 `:5786-5828` 有捕获)。异常会把已 +1 的 `projection_attempts` 与 `projection_error` 留在内存、不落库，调用方收到裸异常而非记录在案的失败。建议：捕获后写入 `projection_error` 并 `store_triage_confirmation`,与 `_project_corpus` 的容错风格一致。
3. **[P3 测试缺口]** 本轮新增测试仅覆盖 (a) 正路径与 (c) 经 retry 的恢复正路径。缺:(b) 负路径“变更 condition_term 后绑定清除且需重检索”(既有 `test_upstream_change...` 只断言依赖失效，未断言绑定);(c) 四个拒绝前置条件(异投影、异快照、请求不匹配、计数不一致)的逐一负测试；restore 成功后 finalize 失败的中间态。建议并入 F12 集中验收矩阵，不阻塞本轮。
4. **[观察] `attach_search_snapshot` 不校验 `snapshot.request` 与当前 plan filter 一致**(`:3045-3121` 只校验 plan_id 与计数)，比 restore 宽松。当前 API/pipeline 调用面均同请求内新建快照，直接暴露低；列为既有加固缺口。
5. **[观察] 草稿路径语义差异**:`save_stage_draft` 在 filter 相等时整计划原样保留、不刷新 criteria(`:1672-1684`),与 commit 路径“保留快照 + 刷新标准”不同。草稿非权威、正式 commit 会刷新，影响小，记录即可。
6. **[观察] 同 filter 且 returned_count>0 时无法重检索**(attach 仅允许替换空结果快照，`:3087-3094`)。这是 immutable 语义的预期行为，不是缺陷；但 UI 应明示“改检索条件才能重新检索”。

**给 Codex 的有界问题**(不阻塞判定)：
1. Study A `projection_attempts=2` 的两次增量能否从恢复脚本日志归属(修复前失败 retry + 修复后成功，还是其他组合)？影响审计叙述精确性。
2. Risks 1 的 criteria-staleness 是否纳入本轮，还是挂起到 F12 之后的批次？
3. Risks 2/3 的两处小修是否要求本轮内闭合？

## Recommended Next Step

Codex 可按以下顺序处置：① 接受 (a)–(e) 判定并采纳 Risks 2 的 try/except 小修(约 10 行，与本轮同一批次集中验证)；② 将 Risks 1 的 criteria 指纹 staleness 与 Risks 3 的负路径测试列入 F12 验收矩阵并明确批次归属；③ 归属 `projection_attempts=2` 来源后在 Study A 恢复叙事中补记一句，完成 (e) 的 UNVERIFIED 部分收口。本人建议本轮修复范围保持在 Risks 2(最小且同因)，Risks 1/3 不混入本轮 diff,避免扩大已冻结修复的表面积。
