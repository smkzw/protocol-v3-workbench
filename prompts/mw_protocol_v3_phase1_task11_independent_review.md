# Protocol v3 Phase 1.1 独立功能验收

你是与实现者上下文隔离的独立验收者。只读审阅，不编辑任何文件；保留并使用终端、文件读取等工具取得可复核证据。

## Hard boundaries

- Work only inside the current workspace and perform a read-only review.
- Do not edit any file or start any service/model/OCR/translation runtime.
- Do not run security, adversarial, permission, path, symlink, TOCTOU, malicious-input, destructive-state, or penetration tests.
- Runner-managed output path: `runs/codex_mw_protocol_v3_phase1_task11_independent_luna.md`. Never invoke a write/edit tool on this report path; return the complete report in the final response and let the runner persist it.

Read these files only:

1. `/Users/smkzw/.codex/AGENTS.md`
2. `AGENTS.md`
3. `context/mw_protocol_v3_phase1_task11_20260810_context.md`
4. `.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md` 的 Task 1.1
5. `plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md` 第6节及 Task 1.1 引用的相关合同约束

## 审阅对象

- `packages/contracts/workbench_contracts/protocol_v3.py`
- `packages/contracts/workbench_contracts/__init__.py`
- `tests/protocol_v3/test_contract_models.py`
- `services/api/assets/medical_writing_corpus/` 与 `services/api/assets/medical_writing_glossary/` 下本次恢复的五份不可变功能资产
- `scripts/qc/protocol_v3/build_source_baseline.py` 的五文件 exact closure
- `tests/protocol_v3/test_source_baseline.py` 的正向闭包测试
- `tests/_real_ibdq_study_schema_fixture.py` 与 `tests/test_medical_writing_study_schema.py` 的夹具迁移
- 当前 `git diff`、未跟踪文件和医学监查边界

## 验收条件

1. Task 1.1 最小合同组完整且可从包入口导入。
2. 所有合同 `extra=forbid`、显式 `schema_version`、稳定领域 ID；所有时间字段要求明确时区。
3. 无效状态、部分 identity、坏 SHA-256、重复 ID、未知 evidence class 确定失败。
4. 生命周期只允许 `raw -> normalized -> proposed -> confirmed -> frozen -> superseded/quarantined` 的声明边。
5. material hash 不受显示进度、`updated_at`、journey/revision counter 和生命周期元数据影响，但实质事实、规则、来源 identity 改变时必须变化。
6. `ExecutionReservation` 的终态只能是 `completed`、`failed`、`unknown_outcome`；完成结果可解释，未知结果不可伪装失败或成功。
7. 五份术语/语料功能资产与既有权威工作树逐文件 SHA-256 相同，且 source baseline 只用 exact paths 纳入；不得恢复历史 `records/active_slices` 树。
8. 旧研究设计图/旧文档会话 API 兼容套件通过；不允许靠改写旧基线或跳过断言通过。
9. 医学监查路径零修改。

你可以运行聚焦的功能测试、导入检查、hash/差异检查。禁止运行或设计任何安全性、对抗性、权限、路径、symlink、TOCTOU、恶意输入、破坏性状态、渗透测试；禁止启动服务，禁止调用外部模型、OCR 或翻译。

## 输出

首行给出 `READY` 或 `NOT_READY`。随后仅包含：

- 确定问题（按 P0/P1/P2/P3/P4 排序，含文件与行号）；
- 已运行的功能检查及结果；
- 五份资产与医学监查边界核对；
- 残余风险与下一步。

不得自行修复，验收者只可否决或接受。
