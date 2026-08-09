# Protocol v3 Phase 0 Task 0.3 — worker_01 Python decision record

日期：2026-08-09
任务：`mw_protocol_v3_phase0_task03_20260809_111313`
角色：`worker_01`

## 角色与能力边界

本次由声明的 `codex-subagent` fallback `codex / gpt-5.6-luna` 接管；原定的 `cms-smk / cms-model` 提供方在可恢复 session 建立前不可用，因此无法复现其提供方身份或宣称已由该提供方执行。仅执行 Python 侧的 Task 0.3 工作，不执行前端、peer 文件、最终视觉/PPT/PDF/临床/监管验收，也不写 runner 管理的 execution report。

## Source of truth 与范围

读取并遵守：

- `workbench/AGENTS.md`
- `context/mw_protocol_v3_phase0_task03_20260809_111313_execution_context.md`
- `plans/codex_execution_mw_protocol_v3_phase0_task03_20260809_111313.md`
- `prompts/mw_protocol_v3_phase0_20260809_111313_task03_execution.md`
- 隔离工作区的 `AGENTS.md`、Phase 0 计划/上下文、现有 API requirements 与 Python import 使用情况

本 worker 只获授权修改 Python requirements 输入、其机械生成 lock（本次因编译器不可用未生成）、Python 验证脚本、聚焦 Python 测试，以及本记录。没有触碰 `frontend/` 或 peer-owned manifest/wrapper 文件。

## 决策

1. `services/api/requirements-protocol-v3.in` 使用四个用途分组：`runtime_api`、`medical_writing`、`ocr_pdf`、`dev_test`。直接依赖均使用精确 `==` 版本，并声明许可证分组标签。
2. `fitz`/`PyMuPDF` 不进入新 Protocol v3 依赖输入。现有遗留 import 仍是迁移风险；任务上下文明确指出当前 PyMuPDF 为 AGPL-3.0/commercial dual license，不能自动视为本次商业工具链的合格依赖。
3. `requirements-protocol-v3.lock` 必须是 Python 3.12 环境中 `pip-tools 7.6.0` 使用 `--generate-hashes` 生成的唯一安装输入。未获得可验证的 pip-tools 编译结果时不手写或伪造 lock。
4. `scripts/qc/protocol_v3/verify_toolchain_rebuild.py` 仅实现 Python 侧：输入分组与排除项校验、pip-compile hash lock 校验、全新源树外 Python 3.12 venv、`--require-hashes` 安装、`pip check`、显式 import probe 及源树副作用检测。前端清单/包装器由集成 worker 负责。
5. 孤立快照中 `packages/contracts/workbench_contracts/models.py` 仍引用缺失的 `protected_tokens.py`；这是读取时发现的既有源缺口，本 worker 未越界修复。

## 已完成与证据

- 新增 `services/api/requirements-protocol-v3.in`，共 14 个直接依赖，分为四组；输入中不含 `pymupdf`/`fitz`。
- 新增 Python 验证脚本及 `tests/protocol_v3/test_toolchain_rebuild.py`。
- `python3.12` 实际版本为 `3.12.13`；`uv` 实际版本为 `0.11.7`。
- `python3.12 -m py_compile scripts/qc/protocol_v3/verify_toolchain_rebuild.py tests/protocol_v3/test_toolchain_rebuild.py`：退出码 0。
- 聚焦测试共 5 项：4 项通过，1 项因预期的源 `.lock` 不存在而 ERROR。该失败证明缺锁会 fail closed，不是通过跳过测试伪装成功。
- 未执行 clean venv 安装及最终 import probe，因为其前置的 pip-tools hash lock 尚未存在。

## 编译器/环境阻塞

- `pip-compile` 命令不存在，当前环境未发现 `pip-tools 7.6.0` 模块或 wheel。
- 使用 Python 3.12 创建临时 venv 成功，但在该临时环境安装 `pip-tools==7.6.0` 时，`uv` 多次访问 `https://pypi.org/simple/pip-tools/` 均因当前网络沙箱 `Operation not permitted` 失败。
- 取消代理并直接 `curl` PyPI 时 DNS 失败：`Could not resolve host: pypi.org`。
- 使用本机临时 uv cache 做离线解析也不能提供 pip-tools 及当前直接依赖的完整可验证元数据，不能替代指定的 pip-tools 编译。

## H4-H6 状态

- H4 hash lock/rebuild：`BLOCKED`。Python 3.12 与 venv 创建能力存在，但指定 pip-tools 编译器及可验证 lock 缺失，因此尚不能证明 hash lock、`--require-hashes` 安装和 clean rebuild。
- H5：`NOT ASSIGNED`。前端 package/lock、wrapper 与完整测试发现由其他 worker 负责，本 worker 未评估或修改。
- H6 Python 侧：`PARTIAL`。验证器语法检查和 fail-closed 副作用测试通过；缺少 lock，故未达到完整可复现重建证据。

## 最小恢复动作

在具备网络或提供本地、可核验的 `pip-tools==7.6.0` wheel/cache 后，在源树外 Python 3.12 临时环境安装编译器，然后执行：

```text
python -m piptools compile --generate-hashes \
  --output-file services/api/requirements-protocol-v3.lock \
  services/api/requirements-protocol-v3.in
python3.12 -m unittest -v tests.protocol_v3.test_toolchain_rebuild
python3.12 scripts/qc/protocol_v3/verify_toolchain_rebuild.py \
  --requirements services/api/requirements-protocol-v3.in \
  --lock services/api/requirements-protocol-v3.lock \
  --rebuild-root /private/tmp/mw_protocol_v3_clean_rebuild_<new-id> \
  --json
```

恢复后应重新记录 lock SHA-256、依赖 entry 数、`pip check`、import probe 及源树无变化，再由 Codex/集成 worker 进行最终 H4-H6 汇总验收。

## 参考

- [pip-tools 官方文档](https://pip-tools.readthedocs.io/en/stable/)
- [pip-tools 配置参考](https://pip-tools.readthedocs.io/en/stable/reference/configuration/)
- [pip-tools 7.6.0 PyPI 元数据](https://pypi.org/project/pip-tools/)
