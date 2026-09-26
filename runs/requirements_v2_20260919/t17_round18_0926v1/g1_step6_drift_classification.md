# G1 Step 6 — 漂移失败族归类（suspected_fingerprint_drift 人工证据档）

- 采样时间：2026-09-26（live HEAD `623ff21e487574177b310290c2c2aff6b00d33ac`，即 G0+G1 工件提交后）
- 对照树：`/tmp/headcheck_0926v1` = `git archive 53feb06fc1402df820a6dba5d8b6e3fa15d50437`
- 方法：`g1_step6_run_drift_samples.py` 对 32 个机制族各取 1 个代表用例，在 live 仓库与导出树**双环境实跑**（门同款子进程调用：`PYTHONPATH=services/api:.` + `--continue-on-collection-errors`），比对首失败指纹与消息；机器可读结论在 `g1_step6_drift_caveats.json`（155 唯一 nodeid / 157 列表条目全覆盖），原始双跑输出在 `g1_step6_drift_samples.json`。
- 前提：157 条均为 gate_full2（HEAD 53feb06、基线 53feb06 三对照）标注的 `suspected_fingerprint_drift` = 同一 nodeid 在 633 条基线已在案但输出指纹漂移；**无一是 G1 数字/忠实度面新增**（该面独立绿：18/18 定向 + 门全量 numeric/final_candidate 零失败）。

## 三类结论（155 唯一 nodeid）

| 类 | 判据 | 族数 | 用例数 |
|---|---|---|---|
| A_env_content_drift | 双环境皆失败、首失败指纹不同——失败输出随仓库内容/运行时数据路径漂移 | 19 | 105 |
| B_order_pollution_standalone_green | live 单跑**通过**（export 单跑亦通过），仅全量顺序下失败——测试间污染/共享状态敏感 | 12 | 42 |
| C_cross_run_drift_fp_stable | 双环境皆失败且当前指纹一致，但与基线采集时点不同——时间敏感输出 | 1 | 7（synopsis_async_real_chunks） |

代表例（完整消息对见 samples JSON）：

- A 类：`tests/protocol_v3/test_chapter_batch1.py::test_assembly_cli_stdout_only_readonly_and_lint_cli_roundtrip` — live fp=`a5be2683fd80` vs export fp=`f5479329e95e`，同为 `assemble_chapter_registry.py` line 36 的 `from packages.contracts...` 导入链断言，随两树 `models.py` 内容差异而输出不同。
- A 类（失败模式随环境变）：`tests/test_ai_fallback_chain.py::AiFallbackChainTests::test_429_uses_next_profile_and_links_both_runs` — live 报 `AiExecutionPolicyDenied: ...base URL must be one of http://127.0.0.1:8...`（live WP6 profile 配置面），export 报 `PermissionError: /private/runtime`（导出树无 live runtime 目录）——同一测试两种环境性失败形态。
- B 类：`tests/test_ai_execution_policy.py::AiExecutionPolicyTests::test_ai_result_reads_fail_closed_before_runner_access` — live 单跑 PASSED、export 单跑报 `PermissionError: /private/runtime`、全量皆败 → 纯顺序污染。
- C 类：`tests/test_synopsis_async_real_chunks.py`（7 条）— 双环境当前同指纹、与采集时点漂移。

## 归类边界（防豁免声明）

1. 本档只证明这 157 条**不是 G1 新增面**（nodeid 在 53feb06 基线全部在案 + 数字/忠实度面独立绿），**不证明"永久已知"**：live 数据（批次静默但可复活）、模型服务器状态（omlx_workload_gate 18 条依赖 8001 可用性，仅经应用 API）、工作树状态都可使指纹再次漂移；后续门跑同族指纹再变仍走 suspected 通道人工复归。
2. caveat 逐条绑定：`g1_step6_drift_caveats.json` 的 `nodeid_caveats` 字段（类 + 族 + 代表 + 采样时间 + 双 HEAD 条件），重采基线时逐条写入 `pytest_failures[].caveat`。
3. 身份类 4-5 条（test_toolchain_manifest / test_frontend_check_wrapper）**不在漂移类内**：根因是工作树未提交工件与冻结 manifest 失配，已按 2a4837e 先例推进工具链权威（manifest+常量 package/lock 哈希与 package_count 329）并在提交 623ff21 后定向转绿（`g1_step6_identity_pre_manifest_red.txt` 4 failed → `g1_step6_identity_post_manifest_green.txt` 33 passed + 31 subtests）。
