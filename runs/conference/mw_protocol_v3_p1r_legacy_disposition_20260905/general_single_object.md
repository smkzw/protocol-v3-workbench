# 会议参与者输出：mw_protocol_v3_p1r_legacy_disposition_20260905 - general_single_object

## 边界检查

- 只读取授权工作区内的文件（repo 根目录 = runner 绑定的 `.`）；未读取生产路径、monitoring live 状态、凭证、外部全局文件。
- 依据 conference context 的 source-of-truth 清单收集证据：`plans/mw_protocol_v3_review_amendment_20260905.md`、`.trellis/tasks/09-05-protocol-v3-p1r-integration/prd.md`、`runs/mw_protocol_v3_1r_integration_20260905/maintained_legacy_complete_20260905.xml`（按 classname/test/message 有界解析，未 dump React traceback）、9 个 scoped diff、对应产品源码函数、资产路径存在性检查。
- 仅运行了 scoped 修复的聚焦合成测试（3 次 pytest 调用，共 119 用例），未做全量 legacy 重跑；证据只写入 `runs/mw_protocol_v3_p1r_legacy_disposition_20260905/`（`parsed_failures.txt`、`scoped_run_1.log`、`scoped_run_2.log`、`scoped_run_3.log`）。
- 未写入 runner 管理的报告路径；未声称任何最终验收；未启动会议或重新发现工具。
- 边界内受阻项：`PROJECT_ROOT`（repo 父目录）下的 `demo_data/workbench_demo_v0_1.json` 在工作区外，按边界未读取，详见 Risks。

## 独立工作成果

### 1. 维护套件总体判定（7420 pass / 167 fail / 18 error / 1 skip）

186 个非通过项按根因精确分为四类（`parsed_failures.txt` 可复核）：

**A. 缺失历史资产 — 137 fail + 18 error（合计 155，占 83%）+ 1 合规 skip。** 全部为 `FileNotFoundError`（或其衍生断言），指向 2026-07/08 历史 records/prompts/artifacts/runs 资产，15 个路径逐一验证不存在（4x3/5x3 MATRIX_ASSIGNMENT、phase1 corpus 工具脚本、omlx gate proposed 脚本、9 组 monitoring records 资产、B6 gate 运行产物、backend launcher 脚本）。唯一例外表现：`test_current_coverage_is_fresh_but_p4_evidence_blocked` 断言 `'invalid' == 'blocked'`，根因同样是 coverage 文件缺失——revalidation 函数 fail-closed 返回 `invalid` 而非 `blocked`，属同一资产簇。skip 项为 disposable Word gate fixture 的设计内跳过。**结论：这些是隔离副本从未拥有的历史批次资产，fail-closed 行为本身正确；不可伪造资产、不可重启下载/OCR/翻译，不构成产品缺陷。**

**B. 真实产品缺陷（未在 scoped 修复内）— template_upgrade ×3。** XML 显示 13 个 section 级 ValidationError：`structural_container requires completion_status=structure_ready`、`actionable_blocker requires completion_status=blocked_missing_inputs`。根因链已定位：typed readiness 构建器 `medical_writing_protocol_template.py::_section_drafting_readiness` 只产出 `drafting_status`，从不赋 `completion_status`（全文件 0 处赋值）；配对校验器在 `packages/contracts/workbench_contracts/models.py:1560-1570`；template upgrade 是第一个把含种子 section 的完整 `ProtocolDocument` 送过新合同校验的路径（`medical_writing_template_upgrade.py:442-452` 只透传 target 现值）。**这是 typed-readiness 迁移在生产者侧未完成的真缺陷，当前树未修复。**

**C. 真实行为冲突（需 Codex 决策）— study_consistency ×1。** `test_rebind_advances_all_bindings_and_reconciles_only_affected_content` 用 ~10 字绿地正文触发 `_substantive_body_gaps`（≥80 字实体正文门，`medical_writing_repository.py:352-408`）。绿地路径按设计不享 `source_kind=original_protocol_docx` 豁免（repository 注释明示）。要么 fixture 义务（正文须达到实体阈值——若重绑定只应发生在完整文档上），要么 rebind 流程错误地复用了导出门控装配路径（产品问题）。二选一必须显式决策，不得静默改为 expected-PASS。

**D. 外部环境依赖 — sqlite_runtime ×5 + real_rux ×1 + approval_center ×1（StopIteration）。** 六个测试共用 `advance_to_query_draft`，首个 `next()` 按标题 `"S01017 ALT/AST >5xULN"` 检索 demo inbox；`setUp` 从 `PROJECT_ROOT = repo父目录/demo_data/` 复制演示数据。仓库内 `workbench_inbox.py`、`demo_repository.py` 零 diff；隔离仓库内不存在任何 `workbench_demo_v0_1.json`。运行时表现为 StopIteration 而非 setup FileNotFoundError，说明外部文件存在但内容已漂移。**根因：测试依赖工作区外的同级演示数据文件，属测试基建缺陷，非产品回归。**

**E. 前端陈旧 pin — frontend 契约 ×5 + source_registry ×1。** `frontend/src/App.jsx` 自隔离基线 commit `05b7d5b` 后从未修改，且根本不含 `setSelectedAnchors`/`anchor_filter` 等被 pin 的模式——隔离基线的前端从未有过这些测试期望的代码。`test_source_registry` 的 `rglob("*")` 扫到 `*.test.mjs` fixture 中合法的 `/Users/` 字符串（`frontend/src/features/medical-monitoring/medicalMonitoringProjectNeutralContract.test.mjs`），属测试过宽匹配，非产品泄漏。

### 2. Scoped 修复逐项审查（核心问题：修复是否掩盖真实缺陷？）

逐项对照产品源码后，**未发现任何一项掩盖产品缺陷**。每项修复方向都是“产品已改、fixture 补齐、或用户已批准升版”，且多数修复是加强而非放宽：

| 修复 | 性质 | 独立验证结论 |
|---|---|---|
| `medical_writing_competitor_triage.py::_sanitize_reason`（产品代码） | 产品缺陷修复 | 新文案与既有 `document_role` 词汇一致（`competitor_triage.py:1155` 已用“无公开方案或统计分析计划”）；v5/v13 验收测试 65 项全过；`tests/` 中无任何测试断言旧文案。修复的是最后一个文案不一致的生产者，方向正确 |
| `test_ai_route_freeze` | 期望升版+**加强** | `_role_profile_id`（`ai_role_runtime_settings.py:266-272`）证实 `independent_ai__route_b` 是角色隔离规范化的确定性产物；新断言追加 base_url/model pin，变异检测改由 identity_hash 差异+端点身份证明，检测力强于旧的单标签断言 |
| `test_contracts` | 诚实化聚合 | 端点 `main.py:3869-3889` 现按 role `current_runnable` 诚实派生；旧 `assertTrue` 编码的是“未配置也声称可跑”的错误声明。遗留小缺口见 Risks#4 |
| `test_document_pipeline_round8` | 路径显式化 | patch 目标 `_recover_document_plan_fallback`（`writing_reference_translation_batch.py:6676`）存在且签名匹配；恢复成功路径在同文件有独立直测（`test_deterministic_fallback_requires_and_preserves_top_level_boundaries` 等 4 处）。不掩盖恢复能力，只是把重试记账路径与恢复成功路径分开测 |
| `test_medical_writing_durable_job_integration` | fixture 形状修复 | `RevisionAcceptAndApplyRequest.idempotency_key` 有 `min_length=8`（`models.py:10127`）；`"k1"` 先触发 422 校验再轮不到 404。校验优先于存在性检查是标准顺序，非产品缺陷 |
| `test_medical_writing_study_binding_backend` | fixture 保真修复 | 真实 DOCX 规范化路径对每个源块强制盖 `source_kind="original_protocol_docx"`（`medical_writing_document.py:456/485/518`）；fixture 缺此字段即非保真导入表示。`_substantive_body_gaps` 对无来源内容仍 fail-closed，门未松动 |
| `test_medical_writing_chapter_projection` + `test_medical_writing_dynamic_section_matrix` | 用户批准升版 | amendment 明确“动态章节矩阵已升版为 typed readiness 并补真实数值来源检查”（修订计划 L63）、“正文零占位符”（L103）。产品中已无 `待补充` 生产者（仅剩 full_draft 检测器的 fail-closed 识别与 readiness 分类器的兼容读取）；`frontend/src/App.jsx` 已消费 `drafting_blocker_code`。作用域从私有 `_REQUIRED_CORE_BODY_SEMANTIC_IDS` 扩到全部 applicable 种子，并新增 sample_size 数值来源逐字断言——净强化 |
| `test_medical_writing_direct_ai_policy` | 与产品策略对齐 | `TASK_AI_ROUTE_POLICIES`（`ai_execution_policy.py:134-153`）对全部五个 medical-writing 任务类型含 `_DIRECT_DEEPSEEK_FLASH_OR_PRO_POLICY`；`deepseek-v4-flash` 即 `DIRECT_DEEPSEEK_TRANSLATION_SUPPORT_MODEL`（`ai_gateway.py:70`）。移出拒绝列表与放开 authoring 任务均与产品一致，非掩盖。两项保留意见见 Risks#1/#2 |

### 3. 聚焦验证运行（隔离 venv，env -i，隔离 WORKBENCH_RUNTIME_DIR）

- `scoped_run_1.log`：route_freeze、contracts、round8、direct_ai_policy×2、durable_job → **6 passed**
- `scoped_run_2.log`：study_binding 全文件、chapter_projection 全文件、dynamic_section_matrix 全文件、v4 reason、crswnp → **48 passed**
- `scoped_run_3.log`：v5/v13 triage 验收邻居（产品改动波及面）→ **65 passed**

### 4. 合规项复核

三个历史工具测试（`test_cross_indication_quality_scorecard_schema`、`test_phase1_translation_manifest`、`test_phase1_translation_runner`）确认不在 7420+186 的 XML 内（758 个 classname 中无此三者），未标 PASS、未 xfail、未隐藏排除——符合 P1R-G1 报告义务，本报告按义务再次列明。

### 5. offline2R 阻断 vs 发布义务分类

**不阻断 2R.1（typed facade 构造）开工的：** A 全部（历史证据资产，与构造路径无交集）、D（StopIteration 簇，fixture 义务）、E（前端陈旧 pin，6R 义务）。依据 PRD：“Proceed 2R.1 after scope disposition, not merely after a favorable test count”——本节即 scope disposition 的独立复核结论。

**必须登记为跟踪义务、不得静默丢弃的：**
1. **B（template_upgrade 生产者缺陷）**——不阻断 2R.1 开工，但它是“新合同被显式采用”不完整的直接证据；在 3R 模板/升级流和任何旧文档升级可信之前必须修复（最小修复：`_section_drafting_readiness` 同步产出配对 `completion_status`，或 upgrade 合并时派生）。
2. **C（rebind vs 实体正文门）**——需 Codex 一句话决策后按决策修复。
3. **D（runtime_directory_configuration）**——legacy main 的运行时目录覆盖检查真实失败（main.py 在树内有早期已验收任务的改动），需一次聚焦重跑定因；发布义务。
4. **D（demo 数据外置）**——将 `demo_data/workbench_demo_v0_1.json` 以 fixture 形式收入隔离仓库，消除对工作区外文件的依赖。

**明确不得做的：** 不得因本分类宣布全仓 PASS；不得把 B/C/D/E 改为 expected-PASS 或隐藏排除；A 类资产不得伪造。

## 风险、缺口与验证需求

**最高影响的异议（对本 packet 计划本身的挑战）：** Codex 的 disposition 若只按“测试计数好转”推进 2R.1，会漏掉 B——一个真实的、当前树未修复的合同生产者缺陷，且它恰好处在“2R.1 新 typed facade 必须显式采用新合同”的同一合同面上。我的替代方案：2R.1 可以开工，但开工同批必须登记 B 为带修复边界的义务（不建议现在顺手修，避免扩 scoped diff），并在 2R.1 验收清单中加一条“template upgrade 全文档构造通过新合同校验”的关联检查。

**其余风险与缺口（按影响排序）：**

1. **Flash 参与 authoring 的策略级确认。** 产品已允许 `deepseek-v4-flash` 用于 `medical_writing_revision`/`protocol_synopsis_structuring`，测试只是追认。代码层面一致，但“哪些模型可做撰写”是医学产物质量敏感的路线决策，建议 Codex 确认这是有意批准（与“默认关闭”门控不冲突）而非路由注册时的顺带放宽。
2. **测试名失实。** `test_flash_exception_is_limited_to_structure_and_translation_tasks` 名称与内容已不符（diff 注释自认）。低风险，建议随下次触碰该文件时改名，避免未来读者误读策略。
3. **test_contracts 丢失绝对可跑 pin。** 新测试只验证字段间一致性；若回归使 `body_translation_runnable` 恒为 False，该测试仍绿。`test_mw_isolated_runtime_baseline.py:86` 的 `True` 是 fixture 造数，不构成端点级行为 pin。验证需求：在完全供给的运行时下应有一个“runnable=True”的行为断言（可登记为小义务，不阻断本次）。
4. **dynamic_section_matrix 的残余盲区。** 重写后对非 blocker 状态不再直接断言非空文本；当前状态机使“substantive_draft+空文本”不可能（构造即要求非空），且 `models.py:1552` 合同校验器兜底（"substantive drafting seed requires initial body text"）。建议下次触碰时补一条种子级非空 pin，成本一行。
5. **approval_center 的 StopIteration 根因未逐帧确认。** 其 `next()` 与 sqlite_runtime 簇同族同题（S01017），我按同簇分类但未逐帧验证；聚焦重跑 demo fixture 修复后应一并确认。
6. **未验证项清单。** （a）外部 `demo_data/workbench_demo_v0_1.json` 内容（越界未读）——漂移具体形态不明；（b）`test_runtime_directory_configuration` 具体哪个 store 未随覆盖（未运行非 scoped 测试）；（c）155 个缺失资产在历史环境中的原始通过证据未重验（依赖既有 XML 记录）；（d）全部 7420 通过项未复跑（继承 1R.6 已独立接受与 1521 v3 测试证据）。
7. **XML 无帧证据。** 维护套件 XML 的 traceback 只存了一行（如 `E StopIteration`），非 scoped 簇的定因主要靠静态阅读；若 Codex 需要帧级证据，需授权对 D/C 簇做各一次聚焦重跑。

## 建议的下一步

1. **Codex 决策（一问一答即可关闭）：** C 项 rebind 流程的预期语义是什么——(a) 重绑定只允许发生在实体正文达标的完整文档上 → 修 study_consistency fixture 至 ≥80 字正文；或 (b) rebind 对账属中间态，不应走导出门控装配 → 产品修复（为 rebind 提供非导出装配路径）。这是本次审查中唯一无法从现有证据安全推断的产品行为分叉。
2. **按上文分类固化义务台账**：B（template_upgrade 生产者补 `completion_status` 配对）、D（vendor demo 数据；runtime_directory 聚焦定因）、E（前端 pin 处置归 6R；source_registry 扫描排除 `*.test.mjs` fixture）——台账随 scope disposition 记录，2R.1 据此开工。
3. **维持两条红线：** A 类缺失历史资产不伪造、不重跑历史批次；三个未执行历史工具测试继续逐报告列明。
4. **本次 scoped diff 可进入 Codex 验收**：我的独立结论是 9 个文件的修复均不掩盖产品缺陷，119 项聚焦验证全绿，可作为 disposition 的组成部分。
