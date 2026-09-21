全部锚点确认。以下为纠正性验证结论。

---

# Conference Participant Output: mw_r11_snapshot_binding_review_20260921 - general_single_object(纠正性验证)

## Boundary Check

- 只读：仅 `git diff --stat`/`grep`/`Read`。未打开任何 SQLite/备份/凭据，未修改文件，未运行测试。
- 四文件 diff 足迹与本会话上一轮完全一致(275/48/75/169,共 547 insertions、20 deletions,HEAD `b14a56a`)——即 owner 采纳的报告项 1–3 对应的源码正是我上一轮已逐行审过的状态；本轮新增证据只有 `recovery-reversal-result.json`。以下按当前工作区行号引用。

## Independent Work Product

**逐项判定:1 PASS,2 PASS,3 PASS,4 PASS(证据一致性)/ UNVERIFIED(实际库状态),5 UNVERIFIED(orange 主报告)。未发现新回归。Study A 阻断状态 PASS。**

**1. 同 filter 复用 + criteria 变更置 `triage_pending` + commit 清投影/终稿且保留库历史 — PASS。**
`_rebuild_search_plan` 中 `has_confirmed_projection` 前置 `triage_criteria_unchanged`(`medical_writing_authoring_journey.py:5112-5113`),criteria 变更时状态落 `triage_pending`(`:5118-5123`);`commit_stage` 在 `search_contract_changed`(filter 或 criteria 任一变化，含 `next_search_plan is None` 失败闭合)时重置 `discovery_basket_projection/corpus_triage/corpus_gate/picos_corpus_alignment`(`:1492-1502, 1519-1531`)。重置块内无任何 repository/journey-service 外写——仅 journey 侧字段，writing_reference 的确认与运行历史原样保留，与"preserving repository history"声明一致。测试:`tests/test_medical_writing_authoring_journey.py:2156-2216`(保留)、`:2293-2295`(变更清除);`tests/test_medical_writing_competitor_triage.py:2719-2722`(快照保留 + 投影清空 + `triage_pending`)。

**2. retry 先查 `_stale_reason`,stale run 不得重绑或定稿 — PASS。**
retry 的 corpus 分支在 restore 之前调用 `_stale_reason` 并在非空时抛 `CompetitorTriageStaleError`(`medical_writing_competitor_triage.py:5816-5818`);`_stale_reason`(`:5012-5055`)校验 prompt/schema 版本、快照存在性与内容哈希、`_material_facts_hash`(`:468-500`,含 `administration_routes`、PICOS 摘要等 relevance 驱动字段，带 revision 对齐技巧)。stale 时整个 restore+finalize 序列被跳过。测试 `test_retry_does_not_restore_confirmation_after_material_facts_change`(`:2687-2757`)断言拒绝、错误信息、库内持久化、corpus 保持 `pending`。

**3. restore 失败持久化为 `deferred_until_picos` + `projection_error` — PASS。**
retry 分支整体包入 try/except,异常写入 `projection_status="deferred_until_picos"` + `projection_error` 并 `store_triage_confirmation` 落库(`:5843-5851`);测试断言 `persisted.projection_error == retried.projection_error`(`:2749-2752`)。

**4. Study A 恢复被拒并回滚 — 证据一致性 PASS;实际库状态 UNVERIFIED。**
`recovery-reversal-result.json` 与代码语义、时间线完全自洽:`reason`("route/design enrichment 后 material facts hash 不符”)正是 `_material_facts_hash` 覆盖字段的变更——即造成绑定丢失的那批 framing 编辑同时使 run 变 stale;第一轮修复无 stale 门，故收据曾显示成功，这正是回滚的科学依据(也实证了我第一轮的 Risk 1 在真实数据中成立)。`restored` 状态(revision 20、无绑定、corpus `pending`、`deferred_until_picos`、`projection_attempts: 1`)同时解开了我先前 attempts 来源问题：恢复前 attempts=1(一次 PICOS 后失败重试)+ 恢复 retry +1 = 旧收据的 2,数值闭环。旧收据未被删除而是被 `reversed_receipt` 引用，证据链干净。
**UNVERIFIED**:两库回滚后的实际状态与备份哈希复核——SQLite/备份文件在禁止清单内，`reversal-result.json` 未记录回滚后哈希；该事实仅 owner 书面声明，Codex 验收时如需可由 owner 补一次只读哈希对账。

**5. 集中套件 469 passed — UNVERIFIED(orange 主报告)。**
我被禁止运行测试；此项为 owner 声明，本会话无独立执行证据。静态旁证：四文件 AST 解析通过、`git diff --check` 干净、新增测试与代码路径逐点对应，未见会导致失败的结构性问题。

**Study A 阻断状态(核心要求)— PASS:当前代码下 Study A 被至少四道独立守卫挡在 corpus 准入之外，且无任何自动 AI 重跑路径。**
在回滚后的 revision 20 状态(绑定丢失、旧确认投影在、run stale):① retry 被 stale 门拒绝(`:5816-5818`);② `finalize_corpus_triage` 被绑定守卫拒绝(`medical_writing_authoring_journey.py:2652`);③ 对旧 run 重新 `confirm_basket` 会在 discovery 投影处被绑定守卫拒绝(`:2577`);④ 新建分诊 run(create_run,唯一会触发 AI 的路径)被绑定守卫拒绝并提示先执行检索(`medical_writing_competitor_triage.py:4091-4112`);⑤ `apply_corpus_projection` 独立绑定守卫(`medical_writing_authoring_journey.py:2823`)。retry 全程无 provider 调用((d) 结论维持)，不存在自动重分诊。语料门侧 `_carry_forward_corpus_gate` 仅活跃 override 可保留访问，且 override 不绕过绑定守卫。

## Evidence And Assumptions

- 关键事实：diff 足迹与上轮逐文件一致 → 代码未变，本轮为纯证据增量审阅；关键锚点行号重新校准(2577/2652/2823/5335/5816/1520)。
- 假设 1:reversal JSON 由 owner 恢复脚本产出，真实性归属 Codex;本审阅核其与代码及时间线的结构一致性(结论：一致，且 attempts 数值闭环)。
- 假设 2:"469 passed”为 owner 声明；测试被禁止执行。

## Risks, Gaps, And Verification Needs

1. **[最重要的前瞻缺口，非本轮回归]"无 AI 重跑的人工复核”尚无实现路径。** `next_safe_action` 要求在不重跑模型的前提下人工对照新标准复核既有 basket,但当前代码中能解除阻断的路径只有：全量重检索 + 新 run(违反约束)或 retry/restore(被 stale 门正确拒绝)。即系统**能保持阻断**(本轮要求已满足)，但**还不能按声明的安全方式解锁**——需要下一批次新增一个显式的人工复核动作(例如：人类对照当前 criteria 重申 retain/exclude → 生成新 confirmation 身份 → 走带人工签核的受控重绑)，并让它绕过的每道守卫都有明确的人工授权语义。建议 Codex 在下一任务合同中定义该路径，尤其要写明它与 `_stale_reason`、绑定守卫的关系。
2. **[操作面，无法验证]** writing_reference 库整体回滚到 pre-recovery 备份，会一并撤销该窗口内**任何**其他写入(含其他项目)；reversal JSON 未记录回滚后库哈希。建议 owner 补一次只读哈希对账并与首份收据中记录的备份 SHA-256 比对，即可把本项转 PASS。
3. **[语义备忘，非缺陷]** stale 门同时覆盖 PICOS 摘要与 framing draft(effective values)变化——偏保守、科学上安全；commit 期投影重置仅覆盖 framing 合同变更，PICOS 漂移由 retry stale 门兜底。两条防线不对称但方向一致，建议在设计说明中记一句，避免后人误删其一。
4. restore 的四个拒绝前置条件仍无逐一负测试(维持上轮建议，并入 F12 矩阵)。

## Recommended Next Step

Codex 可接受本批次(1–3 PASS、4 证据一致、5 记 owner 声明)，随后：① 由 owner 补一次两库只读哈希对账，关闭 4 的 UNVERIFIED 尾巴；② 把“人工 basket 复核 + 受控重绑”定义为下一任务(含与 stale 门/绑定守卫的授权关系)，在此之前 Study A 保持现状阻断即为正确终态；③ F12 矩阵补 restore 负路径四例。本轮无需代码返工。
