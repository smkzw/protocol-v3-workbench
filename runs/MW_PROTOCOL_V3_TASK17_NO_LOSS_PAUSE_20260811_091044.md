# Protocol v3 Task 1.7 无损暂停检查点

暂停时间：2026-08-11 09:10:44 CST（Asia/Shanghai）
状态：**PAUSED — NOT ACCEPTED / NOT COMMITTED / NO ACTIVE RUNNER**
下一任务：仍为冻结 Implementation Plan 的 Phase 1 Task 1.7；不得跳到 Task 1.8。

## 1. 权威锚点

- 工作区：本文件所在 Protocol v3 隔离 worktree。
- 冻结计划：`.hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md`
- 冻结计划 SHA-256：`fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`
- 当前 HEAD：`0515361 feat(protocol-v3): add execution reservation runtime`（已验收 Task 1.6）。
- Task 1.7 主合同：`context/mw_protocol_v3_phase1_task17_20260811_context.md`
- 执行合同：`context/mw_protocol_v3_phase1_task17_20260811_execution_context.md`
- 当前文件系统为最终真相；Task 1.7 仍全为未提交工作，不得把 worker/manager 自述当作验收。

## 2. 本次已完成的可恢复工作

### 2.1 跟踪与执行初始化

- 已通过 workflow guard 初始化 Task 1.7 tracked task 和三工作包 execution。
- 已补全 source of truth、范围、成功标准、风险和允许写入路径。
- 四份初始执行提示词均已通过 guard preflight。
- 未启动服务、真实模型、OCR、翻译、数据库或前端；未进行安全性测试。

### 2.2 Worker 01：Role/Skill Registry

- Session：`019fee38-2994-7000-8861-d9455a489865`
- 报告：`runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_01.md`
- 已创建：
  - `config/medical_writing/protocol_v3/role_registry.json`
  - `config/medical_writing/protocol_v3/skill_registry.json`
  - `services/api/app/protocol_workflow/registries/{__init__.py,loader.py}`
  - `tests/protocol_v3/test_registry_loading.py`
- 当前注册 4 类产品 AI、9 个基础 Skill；canonical `SkillDefinition` 未扩宽，额外版本化元数据保留在 closed registry entry。
- Worker 01 focused evidence：31 passed；本次暂停前已由 Codex 复跑并纳入当前 149 tests。

### 2.3 Worker 02：初版 Harness / Direct API / local oMLX

- Session：`019fee41-6801-7000-bf49-469b5148a22a`（必须保留，用于同会话修复）。
- 报告：`runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02.md`
- 已创建：
  - `services/api/app/protocol_workflow/runtime/harness.py`
  - `runtime/adapters/{__init__.py,direct_api.py,local_omlx.py}`
  - `tests/protocol_v3/test_harness_policy.py`
- 初版实现不是最终可接受状态；见第 4 节 P1 缺口。

### 2.4 Worker 03：Codex/OMP 适配及同会话 CLI 语法修复

- Session：`019fee4d-35cf-7000-90de-53f7a46b8c40`
- 初次报告：`runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_03.md`
- 同会话修复报告：`runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_03_recovery_01.md`
- 已修复并由本机 `--help` 证实：
  1. Codex `--jsonl` → `--json`；
  2. Codex `--resume` flag → `exec resume SESSION_ID` 子命令；
  3. OMP `--yes` → `-p` + `--auto-approve`；
  4. OMP `--thinking on` → 精确 effort 值，`none`→`off`；
  5. 不再用 `idempotency_key` 冒充 provider session id。
- 相关文件：`runtime/adapters/{codex_app.py,omp_cli.py}`、adapter exports、CLI 测试。
- 由于 common Harness 尚未传递 provider session，CLI 适配仍需在 Worker 02 common-contract 修复后再次核对。

### 2.5 执行经理

- Cursor manager session：`4b2bc8f1-38bd-4ba6-a09e-762c7b80b3bb`
- 报告：`runs/execution/mw_protocol_v3_phase1_task17_20260811/manager.md`
- 该报告曾错误接受无效 CLI flags，已被 Codex 反证推翻；只能作为过程证据，**不是验收结论**。
- 经理做过限定范围格式化及 OMP mismatch exception 风格统一；实际文件已由后续 Worker 03 recovery 覆盖/复核。

## 3. 暂停时确定性证据

- 当前 Task 1.7 pair：
  - `PYTHONPATH='services/api:packages/contracts:.' python3.12 -m pytest -q tests/protocol_v3/test_registry_loading.py tests/protocol_v3/test_harness_policy.py`
  - **149 passed in 0.33s**。
- 这些通过测试只证明当前测试集合，不证明 P1 缺口已覆盖；不得据此标记 READY。
- 冻结计划 hash 未变化。
- `git status --porcelain` 未出现任何 medical-monitoring / monitoring 路径。
- 当前没有运行中的 runner、worker、manager、服务或模型任务。
- 当前共享 gate 事实仍为 OCR=`GLM-OCR-bf16`、translation=`dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX`；产品目标 OCR=`PaddleOCR-VL-1.6`，因此 OCR 必须继续 fail closed，不能伪装已就绪。

## 4. 已确认但尚未执行的 P1 修复

已创建、尚未 preflight/dispatch 的同会话修复提示：
`prompts/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_followup_01.md`

待修复内容（不得遗漏）：

1. `build_request()` 不能再接受可伪造的 `role_allows_thinking: bool`；必须绑定 loader 的 immutable `RoleEntry` 并核对 role kind/provider/model/harness/effort。
2. 必须核对 node skill id、input/output schema refs，并严格核对传入 artifact hashes 与 `NodeExecutionContract.input_artifact_hashes`；当前存在输入替换缺口。
3. 必须显式选择 target region，并同时满足 node allowlist 与 Role target profile；Role sensitivity tier 作为最大允许级别。
4. `ArtifactRef.ref` 必须是逻辑 artifact URI/ID，拒绝绝对路径、home、traversal 和任意文件路径。
5. workload gate 必须位于 common Harness 边界，对 Paddle Direct API OCR 和 local oMLX translation 一视同仁；当前仅 local adapter 检查 OCR，Direct Paddle 可绕过。
6. OCR/translation 必须有真实注入的 effective model selection 与 lease context；不允许 local oMLX 在缺少 lease factory 时生成 fake lease。
7. 四个 adapter 都必须要求显式 probe callable；不能默认 `lambda: True`。
8. `provider_session_id` 必须从 NodeExecutionContract 进入 Harness request，并由 Dispatcher 传给 adapter；不能要求恢复流程绕过 Probe/Policy。
9. `DispatchReceipt` 必须包含逻辑 output artifact ref + output schema ref，并核对 request schema；当前只有 hash，不足以证明 typed artifact。
10. preflight/policy/probe/gate/lease-acquisition failure 必须 `dispatched=False`；只有真正进入 injected physical transport 才可为 true。
11. Skill allowed tools/paths 的 subset 检查即便 Skill closed set 为空也必须执行。
12. Worker 02 修复后必须再次适配 Codex/OMP common interface，并解决 Codex `--output-schema` 需要本地 schema **文件路径**而 registry 使用 schema URI 的映射问题；不得把 URI 直接作为 CLI 文件路径。

## 5. 唯一下一安全动作

恢复时先重新锚定本文件、Task 1.7 context、冻结计划 hash、`git status`，然后：

1. 对 `worker_02_followup_01.md` 运行 workflow guard preflight；若失败，只修提示词，不运行新 session。
2. 使用 **原 Worker 02 session** `019fee41-6801-7000-bf49-469b5148a22a` 和 runner `--resume-session` 执行该单次集中修复；输出应写入：
   - `runs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_recovery_01.md`
   - `logs/execution/mw_protocol_v3_phase1_task17_20260811/worker_02_recovery_01_stdout.txt`
3. 等原 session 终态；不固定轮询、不重派、不 fallback。
4. Codex 核对实际 diff 与新失败测试；随后使用原 Worker 03 session 做必要的 common-interface/schema-path 同会话修复，而不是新开 worker。
5. 只有 common contract、CLI contract、focused/full tests 均通过后，才启动隔离 verifier/conference；当前不得 cleanup-execution、archive、commit 或进入 Task 1.8。

## 6. 当前未提交文件范围

`git status --short` 当前顶层显示以下 Task 1.7 未跟踪范围：

- `config/medical_writing/protocol_v3/{role_registry.json,skill_registry.json}`
- `context/mw_protocol_v3_phase1_task17_20260811*.md`
- `metrics/mw_protocol_v3_phase1_task17_20260811*.md`
- `plans/codex_execution_mw_protocol_v3_phase1_task17_20260811.md`
- `prompts/execution/mw_protocol_v3_phase1_task17_20260811/` 与初始 task prompt
- `reviews/codex*_mw_protocol_v3_phase1_task17_20260811*.md`
- `runs/execution/mw_protocol_v3_phase1_task17_20260811/`
- `services/api/app/protocol_workflow/registries/`
- `services/api/app/protocol_workflow/runtime/harness.py`
- `services/api/app/protocol_workflow/runtime/adapters/`
- `tests/protocol_v3/{test_registry_loading.py,test_harness_policy.py}`

不要因其均为 untracked 而清理；它们是当前唯一未验收 Task 1.7 工作集。`__pycache__`/pytest/Ruff 缓存可在最终验收前精确清理，但此暂停点不执行清理。

## 7. 禁止的恢复动作

- 不得声称 Task 1.7 READY、完成或已提交。
- 不得接受 manager/worker 自评替代 Codex 与隔离 verifier。
- 不得启动真实 Paddle/oMLX/LLM/CLI 模型调用或服务。
- 不得修改共享 gate、医学监查文件、legacy store、Task 1.8+ 文件。
- 不得删除 untracked Task 1.7 文件、runner logs 或同会话证据。
- 不得新开 Worker 02/03 session，除非原 session 明确不可恢复且按 route policy 记录终态失败。
