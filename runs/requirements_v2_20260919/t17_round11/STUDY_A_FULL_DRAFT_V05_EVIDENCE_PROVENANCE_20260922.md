# Study A 全文初稿 v0.5 证据持久化修复

日期：2026-09-22  
状态：源码与集中回归完成；真实产品模型重跑和医学会商待继续  
执行模式：owner 直接实现，冻结提交后独立工程审阅；真实 v0.5 工件形成后再做 fresh 医学会商。

## 问题

Study A 的 v0.4 候选 `mwjob_96ee70138c21a86568eb3f3d` 在生成时通过证据引用校验，但最终 `full-draft.json` 只保存章节的 `evidence_span_ids`，没有保存 ID 对应的 `source_id`、`locator` 和原文摘录。批次之间还可能重复使用短 `span_id`，因此不能用一个无作用域的全局列表补救。该工件可审阅正文，但不能证明每个章节引用的具体证据，不得采纳。

## 修复

- 工件升为 `protocol_full_draft_artifact_v5`，分批工件升为 `protocol_full_draft_chunk_v5`，描述符升为 v6。
- 每个章节直接持久化 `evidence_bindings`：原始 span ID、来源 ID、定位、证据摘录和摘录 SHA-256。章节作用域避免跨批次 ID 碰撞。
- 分批恢复时重新核对每个引用、来源和摘录哈希；缺失或损坏的批次不得复用。
- 合并最终候选和采纳前再次核对完整证据链。
- v3/v4 仍可读取，但统一标记为历史只读，不能采纳。未改写既有 v0.4 原始工件。

## 验证

- `python -m py_compile`：通过。
- 集中回归：`tests/test_medical_writing_full_draft.py`、`tests/test_ai_gateway.py`、`tests/test_ai_task_runner.py` 共 115 项通过。
- 覆盖：章节证据绑定持久化、v4 只读兼容、证据损坏分批拒绝复用、既有全文初稿与 AI gateway/runner 回归。

## 下一安全动作

1. 冻结并独立审阅本次实现。
2. 在隔离 5299 环境生成新的 v0.5 Study A 候选；产品路由必须仍为 `opencode-go / deepseek-v4.1-flash / max`。
3. 确认 85 个章节的所有证据 ID 均可解析，再冻结工件并发起 fresh 医学会商。
4. 会商通过前不得采纳正文；v0.4 工件只保留为历史证据。
