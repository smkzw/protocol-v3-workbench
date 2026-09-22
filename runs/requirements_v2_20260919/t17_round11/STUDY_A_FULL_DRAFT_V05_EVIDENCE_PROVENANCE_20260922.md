# Study A 全文初稿 v0.5 证据持久化修复

日期：2026-09-22  
状态：源码、集中回归、真实产品模型重跑与独立医学会商完成；v0.5 判定不可采纳，v0.6 决定治理修复继续
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
- 首轮集中回归 115 项通过；会商修复后同一测试集最终 117 项通过。
- 覆盖：章节证据绑定持久化、v4 只读兼容、证据损坏分批拒绝复用、既有全文初稿与 AI gateway/runner 回归。

## 独立工程会商

- 实际路由：`zcode/zcode/GLM-5.3-Flash:max`，同一 session 两轮，无 fallback。
- 首轮复现最终工件损坏后被直接复用的问题；修复后，最终复用也必须先过证据链验证，失败时从有效 chunk 重建且不重复调用模型。
- 读取时的 `adoption_ready` 现在同时要求证据链可解析；空章节数组、跨批次重复 span ID、来源归属与 locator 一致性均有回归覆盖。
- 续审最终判定工程范围 PASS；真实 v0.5 候选及医学内容不在该 PASS 范围。

## 下一安全动作

1. 冻结并推送会商修复。
2. 在隔离 5299 环境生成新的 v0.5 Study A 候选；产品路由必须仍为 `opencode-go / deepseek-v4.1-flash / max`。
3. 确认 85 个章节的所有证据 ID 均可解析，再冻结工件并发起 fresh 医学会商。
4. 会商通过前不得采纳正文；v0.4 工件只保留为历史证据。

## 真实 v0.5 工件与医学结论

- Study A job：`mwjob_bf28987c132c1b13527f252a`；最终工件 SHA-256：`a9731b65bf919ac83cb32da94b16fae6a24e857c08df39d6a83cb8b1d6c59c40`。
- 产品运行实际路由：`opencode-go/deepseek-v4.1-flash:max`。首次在第 15 批 provider timeout；连通性复核通过后按同一 job 唯一剩余 attempt 续作，复用前 14 批，最终完成 85/85 节。
- 结果：23 complete、49 decision_required、13 source_gap；73 个决定项；367 个证据引用全部可解析；22 个 AI run 全部与运行账本对上。
- fresh 医学会商实际使用 `zcode/zcode/GLM-5.3-Flash:max`。结论为 `REVISE`：事实与数字整体可靠，但推荐正文提前落地、重复/冲突卡、错误字段绑定与点击负担使工件不可整体进入用户审阅。
- v0.5 保持不可采纳。后续从 v0.6 决定合同重跑：只允许仍未确认的整字段决定，一字段一卡，待决定章节确认前不生成倾向正文。
