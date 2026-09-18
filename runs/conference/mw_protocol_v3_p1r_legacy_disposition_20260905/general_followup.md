# Conference Participant Output: mw_protocol_v3_p1r_legacy_disposition_20260905 - general_single_object (delta review)

## Defects Still Open (with exact source evidence)

1. **Typed-readiness producer still does not sync `completion_status`（残余，已收窄）。** `_section_drafting_readiness`（`medical_writing_protocol_template.py:1961-2026`）仍然只返回 `drafting_status` 等字段，无 `completion_status`；template upgrade 侧的修复是**按 target 状态透传/重置**（`medical_writing_template_upgrade.py:440-468`），即修复点在合并处而非构建处。当前可达路径（seeds → upgrade merge → 校验）已由红→绿回归覆盖（`legacy_template_migrated_blocker_red.xml` 红、`legacy_template_upgrade_final.xml` 5 passed），但我未证明其它从种子直接构造 `ProtocolSection` 的路径不存在。**定性：legacy 合同（`models.py:1552-1570` 的 ProtocolSection 校验器）范围内的残余义务，非阻断。**
2. **外部 demo 数据依赖未消除（sqlite_runtime ×6 + approval_center 的 StopIteration 簇）。** `tests/test_sqlite_runtime_integration.py:9` `PROJECT_ROOT = ROOT.parents[1]` 指向工作区外同级 `demo_data/`；工作区内无该文件；`workbench_inbox.py`/`demo_repository.py` 零 diff。本 delta 未涉及，仍需 vendor fixture 修复。runtime_directory 的失败与此簇无关（见下）。
3. **前端契约陈旧字面 pin（6R 义务，特征存在、pin 过期）。** 修正后事实：锚点选择功能一直存在于 `frontend/src/features/writing-reference/ReferenceTranslationBatchPanel.jsx`（基线 commit `05b7d5b`，行 276/300/314/356），实际代码为 `setSelectedAnchors(supportedAnchors(returnedAnchors.map((item) => item.value)))`，测试在 `test_frontend_medical_writing_translation_batch_contract.py:165` pin 的是不带 `supportedAnchors()` 包装的字面量 → `assertIn` 失败。App.jsx:1180 存在共享条件 `emptyProjectMetricValue`。unsupported translation anchors 按 delta 指示保留为 6R 行为义务。
4. **记录为 follow-up（仍缺失，不阻断）：** 正向 endpoint-ready 行为断言（`test_mw_isolated_runtime_baseline.py:86` 的 `True` 是 fixture 造数）与种子级 nonempty substantive-seed pin。

## Corrected Findings（对原报告的更正与限定）

- **更正1（B 项范围）：** `completion_status` 配对校验器仅存在于 legacy `ProtocolSection`（`models.py:1560-1570`）；2R 的 `NodeExecutionContract`（`protocol_v3.py:921-948`）**没有** `completion_status` 字段（protocol_v3.py 中 0 处）。**未证明任何共享缺陷**；我原报告“typed contract 采用不完整”的措辞过度外推，撤回，缺陷限定为 legacy 升级路径，且该路径已修复并有红→绿回归证据。
- **更正2（C 项撤销）：** `medical_writing_study_consistency.py` 中 `assemble_document_for_export` 出现 0 次——rebind 流程从不调用导出；原始失败由测试自己的最终导出断言触发。不存在我所称“行为冲突”，delta 处置（`final_freeze_readiness().ready` + 显式期待 `substantive_body_missing` 拒绝）比我的 fixture 加字建议更诚实，且未稀释 ≥80 字门槛。采纳。
- **更正3（D 项 runtime_directory 定因）：** `legacy_runtime_directory_diagnostic.xml` 证明唯一失败断言是 `ocr_gateway_configured=False`（新鲜无凭证运行时的预期状态）；所有 store 路径断言通过（`legacy_runtime_directory_projection.xml` 绿）。修改为 `assertIsInstance(bool)` 保留载荷存在性，不弱化目录契约。我原“真实未决契约失败”定性撤销，改为“已定因、已处置”。
- **更正4（E 项前端）：** 见 Open#3——我原本核对的是 `App.jsx`，实际被测文件是 `ReferenceTranslationBatchPanel.jsx`，功能并非“从未存在”，是字面 pin 落后于 `supportedAnchors()` 包装。
- **更正5（资产存在性认识论）：** 我只能证明 15 条路径**当前**不存在；不能证明它们在隔离前的工作区“从未存在”。原报告该表述按此限定。
- **更正6（Flash 路由）：** direct_ai_policy 测试仅镜像既有 `TASK_AI_ROUTE_POLICIES` 策略，无激活/变更；v3 默认仍为 GLM，替代路由需用户显式激活。我的“策略级确认”提问按此关闭，无需进一步行动。
- **更正7（source_registry）：** `/Users/` 字面量属 `medicalMonitoringProjectNeutralContract.test.mjs` 内合成 monitoring 测试示例，按指示保留不动；我原“过宽 glob”仅作为测试卫生观察保留，非泄漏、非产品缺陷。

## Actual Test Results

- **我的独立运行（本次 delta，隔离 venv + env -i + 新 mktemp WORKBENCH_RUNTIME_DIR）：** `tests/test_medical_writing_template_upgrade.py` + `tests/test_medical_writing_study_consistency.py` + `tests/test_runtime_directory_configuration.py` → **18 passed**（`runs/mw_protocol_v3_p1r_legacy_disposition_20260905/delta_run_3files.log`）。
- **证据链复核：** `legacy_template_migrated_blocker_red.xml`（1 fail，红回归：迁移正文入空 blocker target 曾触发 "actionable drafting blocker must not contain substantive body text"）→ `legacy_template_upgrade_status.xml`（5 tests/1 fail，中间态）→ `legacy_template_upgrade_final.xml`（5 passed）→ `p1r_post_legacy_repairs.xml`（**1538 passed / 0 fail / 0 err / 0 skip**，含 template_upgrade 与 study_consistency）→ 我的 18 passed。修复方向与红→绿证据一致。
- **一处证据表述限定：** `p1r_post_legacy_repairs.xml`（236 个 classname）**不含** dynamic_section_matrix、chapter_projection、ai_route_freeze、contracts、round8、direct_ai_policy、durable_job、study_binding、triage v4/crswnp、runtime_directory；“all v3”的说法对这几个文件不成立。它们的绿态由我第一轮独立运行（119 用例）与本轮 18 用例支撑，建议 Codex 在处置记录里按实际覆盖引用证据文件。

## Verdict Requested

- **Scoped legacy repairs 可接受。** 四项新修复均不掩盖产品缺陷：template upgrade 修复以红回归先行、移除 Word 保真声明并保留完整性门（升级产物仍被 `substantive_body_missing` 正确拒绝，无完整性声称）；study_consistency 区分绑定/冻结就绪与文档完整性，未垫 fixture 文本、未降门槛；runtime_directory 保留全部路径断言，仅将无凭证环境下的 OCR 就绪从无条件 True 改为 bool 存在性断言；Flash 路由无任何激活变更。
- **其余历史/monitoring/前端问题可保留为显式发布义务，offline2R 构造可继续推进。** 依据：A 类 155 项缺失资产均为 fail-closed 历史证据缺口，与 2R.1 typed facade 构造路径无交集；C 项已撤销；B 项收窄为 legacy 义务且已有红→绿回归；StopIteration 簇与前端 pin 均为测试基建/6R 义务。前提是义务台账按本报告 Open#1–#4 及更正后的定因登记，且三个历史工具测试（`test_cross_indication_quality_scorecard_schema`、`test_phase1_translation_manifest`、`test_phase1_translation_runner`）继续逐报告列明未执行。
- 不声称 full repository PASS；不声称最终验收；Codex 保留最终裁量。
