# Conference Output: mw_protocol_v3_hr_fresh_20260905 - evidence_single_object

## Output

角色：`evidence_single_object`（重要证据审阅，fresh 独立验证人）。全部核查基于本会话实际读取文件、实际执行的哈希与测试命令，未读取任何其他 reviewer 输出，未使用 subdelegation，未调用服务/产品模型。

### 结论（建议，非最终验收）

**H-R 独立建议：READY**（限 declared source-only 重锚定范围：R.1 权威路径修订、R.2 漂移对账、R.3 测试回绿 + 计划修订一致性）。Plan v2 Gate H-R 的全部谓词均有客观证据支持，我未能找到任何实质性未决前提。此建议不构成产品验收：产品 SQLite/router/UI 的缺位是 Phase 1R+ 范围（按会议上下文约定，计划内缺位本身不构成 H-R 失败）。Codex 保留最终裁定权。

### 逐项验证证据（全部为本会话实测）

**受保护哈希与不可变字节（R.1 前提）**

| 对象 | 期望 | 实测 | 结果 |
|---|---|---|---|
| Plan v2（plan-upgrade 目录，只读） | `040eb6ad…76707` | 一致 | ✓ |
| 旧基线 mutable_source_baseline_20260809.json | `32e274b4…7d67` | 一致 | ✓ |
| immutable_protected_assets.json | `f4b385d4…ce7f` | 一致，字节未改写 | ✓ |
| protected_path_rules.json | `16012ec0…4ece` | 一致 | ✓ |
| Task 2.1 七文件（orchestrator 全部） | 暂停记录逐项 | 7/7 一致 | ✓ |
| R.1 checkpoint 登记的 4 个新文件哈希 | r1 报告逐项 | 4/4 一致 | ✓ |
| amendment 内 13 迁移 + 8 新增外部 SOP 文件 | JSON 内冻结值 | 21/21 一致，0 失败 | ✓ |

**R.1 权威路径修订**
- amendment（`config/medical_writing/protocol_v3/authority_amendment_20260905.json`）：13 项 old→new locator 逐项带 sha256/owner/read_only；8 项新增的 authority_role 正确（T02-00 修订版为 `phase_1_candidate_unresolved`，未自动升权威，符合“Ⅰ期待用户裁定”）。
- `authority_locator_amendment.py`：frozen manifest 哈希交叉校验、relocation 必须精确覆盖冻结 CMSS 权威集合（防增防漏）、TOCTOU stat 前后守卫、symlink/越界/重复/缺 owner 全部 fail-closed、新树 rglob 冻结集合等值（新增未声明文件即拒）、旧路径复现不得静默遮蔽修订。
- `build_frozen_authority_manifest.py` 改动（+35 行）：逻辑键（旧路径）保持不变、物理重定位后再哈希、未知 locator 报错；历史清单字节不动。
- 负向测试齐备：duplicate/escape/symlink/missing/owner 五类参数化缺陷 + 冻结字节守护测试 + 构建器逻辑键解析测试。

**R.2 漂移对账与 23 项共享差异**
- `source_drift.json` 实测解构：313 差异 = monitoring_protected 129 + medical_writing_review 127 + shared_manual_review 57，与报告完全一致；live_head `d2daef1d…`、isolated_head `3d6772f…` 与现场一致。
- shared_manual_review 中 changed-both-sides 恰为 23 条，路径与 R.2 处置表逐条一一对应（无遗漏、无多余）；31 right_only + 3 left_only = 34 单边，与报告一致。
- medical_writing_review 类唯一双边 changed 确为 `tests/test_medical_writing_study_schema.py`，与报告一致。
- 新 `mutable_source_baseline.json` 与 `live_source_observation.json` 字节相同（cmp 通过）；身份字段明确：`source_root` = live workbench 绝对路径、`source_commit` = d2daef1d、`observation_scope` = source-only、`supersedes_baseline_sha256` = 旧基线 SHA、`historical_baseline` 指针。旧基线字段（baseline_id/determinism/tree_audit）完整保留在历史副本。
- Python 消费者核查：旧 authority 测试已指向历史副本（diff 仅 3 行、注释明示 expected 不变）；新基线唯一消费者是 reconcile 脚本自身；“未发现其他消费者误用”的声明属实。
- 对 live 源码（仅 SOURCE 只读）抽查 8 项高风险处置，全部准确：App.jsx 13514 vs 16002 行、live 含 RouteOutlet（3 处）而隔离区 0 处；main.py 精确 +390/−5；ai_gateway expected_response_model 缺失/不匹配 fail-closed（1210–1225 行）；ListingSheetPayload.source_headers（models.py:10453）；live `__init__.py` 无 protocol_v3 导出（整文件合并确会丢 v3 导出）；source_intake live 有 fcntl/事务/原子替换（2239 行）而隔离区为 append 语义（1342 行、无锁）；study schema 测试 live import `records.active_slices…` 真实脚本 vs 隔离区纯 fixture。
- live workbench 现状：HEAD 仍为 d2daef1d（与会话观察一致），`git status --porcelain` 干净 → live/monitoring 零改动成立。

**R.3 测试回绿 + lsof 可注入**
- `_run_lsof`：`runner` 可注入、`timeout` 可配置且校验 finite/positive、默认 5.0s 保留；超时错误信息明示 "timed out … (treated as occupied)"，与真实占用（"open handle on target"）区分。`builtin_occupancy_checker` 提供 `port_probe`/`lsof_runner`/`lsof_timeout` 三个注入点。
- 原 4 失败根因处置核实：3 个 authority 测试经修订重指向后通过；脆弱测试 `test_p1_builtin_occupancy_blocks_port_8911` 改为注入 fake（断言 match 不变、fail-closed 语义不变），且另一测试删除了原 ambient-listener `pytest.skip` 路径——是变强而非降级。未见任何 expected 降低、负向 fixture 删除或 xfail。
- 本会话独立复跑（命令与会议上下文声明一致）：
  - Phase R 聚焦 4 文件：**183 passed**（与 r1 checkpoint 记录一致）
  - Task 2.1 preserved suite：**75 passed**
  - 全套 `tests/protocol_v3`：**1240 passed, 2 warnings, 101 subtests passed, 0 failed**（与 checkpoint 一致，≥1222 达标；2 warnings 为暂停记录已登记的 Phase-0 tar 弃用告警）

**范围隔离（Gate H-R 硬条件）**
- 隔离区 HEAD 仍为 `3d6772f`（Task 2.1 暂停提交）；tracked 改动恰为声明的 5 个文件（2 QC 脚本、1 fixture、2 测试，+3348/−2612）；untracked 全部落在声明的证据 overlay（context/plans/prompts/reviews/metrics/conference/runs）+ 2 个新 QC 脚本 + 2 个新测试 + 历史基线 + amendment JSON。services/frontend/packages/pocs 零改动。

**计划修订一致性**
- `plans/mw_protocol_v3_review_amendment_20260905.md` 明确记录用户已批准的 1R.4 兼容式简化（不把物理删除旧状态/字段/模块作为指标），并保留原负向 fixture/expected 不删、哈希依赖绑定不静默丢失等更强验证义务；声明 Plan v2 SHA 仍为顺序权威、不修改只读 plan-upgrade 目录——与实测（Plan v2 SHA 一致、目录只读未动）吻合。该修订只影响 1R.4 后续执行边界，不弱化任何 H-R 语义。

### 最高影响缺陷/不确定性排查（主动质询）

1. **命名误导风险（低，建议非阻断）**：新 `mutable_source_baseline.json` 内容是 LIVE 根的超替（source_root 指向 live workbench），但文件名与 `tests/fixtures/protocol_v3/` 位置仍暗示“隔离区基线”。现有防线：显式身份字段、历史副本、r2 报告的消费者警示、且当前唯一消费者正确。建议：1R+ 任何消费者使用前必须断言 `source_root`/`source_commit`/`observation_scope`；可在后续 Phase 考虑改名（本轮不必）。
2. **amendment 的 `plan_v2_sha256` 字段未被代码校验**（低）：`load_amendment` 只校验 frozen_manifest_sha256，plan SHA 为信息性字段。无门影响，未来收紧可一并校验。
3. **`_expand_patterns` CMSS 特例按后缀过滤 relocation**（低，已被守卫）：当前 13 项 old locator 全部位于旧根下，等价成立；`validate_amendment` 强制 old locator ∈ old_root，不可利用。未来追加 amendment 时需保持该不变量。
4. **“先红后绿”为历史声明**（观察）：原 3 失败的复现无法在本会话重演（路径已修），我独立确认的是当前全绿状态 + 4 失败根因与现场证据吻合。
5. **23 项处置的覆盖深度**（不确定性声明）：我通过 drift JSON 哈希核对了全部 23 项的存在性与分类，并对其中 8 项最高风险处置做了 live 源码级深查；其余 15 项（如 styles.css、start_stable_backend.zsh、各 tests/*）的分类与“不合并”处置有 drift 数据支撑但我未逐行 diff。鉴于处置的实质是“不合并 + 登记风险”（均已被范围隔离证据独立证实），此剩余深度不构成门风险。子断言“WritingPage 位于 App.jsx 无差异中段”未逐行核实，属 6R/8R 前瞻说明而非门判据。

### 给 Codex 的决策点 / 有界问题

- 唯一有界问题（非阻断）：Task 2.1 的三个 material graph hash（`f9d99776…`/`42c3ed35…`/`77870c7a…`）我未单独重推导；但七文件字节与暂停记录一致且 75 测试全绿（该套件在暂停时已验证 material hash 复现），传递性成立。如 Codex 要求显式重推导可作为 follow-up，一处命令即可。
- 安全临时路径：若 Codex 采纳建议 1，可在 1R 任务合同中加入“baseline 消费者必须校验身份字段”一条，成本一行断言。

### 汇总

H-R 全部判据（R.1–R.3 通过、隔离区 git 仅含声明 diff、live/monitoring 零改动、保护哈希全部保持、23 项共享差异逐项处置且零合并、离线测试全绿、用户批准的计划修订与权威文档链一致）均有独立复现证据，无实质性未决前提。**建议 READY**，最终验收由 Codex 裁定。
