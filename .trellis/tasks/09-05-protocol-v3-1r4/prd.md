# Protocol v3 — 1R.4 运行时语义简化与兼容迁移

## Goal

简化个人工作台运行时与存储，保留真实恢复、历史兼容和科学内容依赖。
1R.3独立复核已完成，本任务正在实施；验收证据见前置任务最终复核记录。

## Requirements

- 权威：Implementation Plan v2 Task1R.4加plans/mw_protocol_v3_review_amendment_20260905.md用户修订。
- 合并请求与结果的持久化表示；旧inbox ports/imports保留为轻量兼容，不以物理删模块作为成果。结果接收与业务消费必须分开。
- 结果三态复用ExecutionTerminalState；活动lease和历史attempt仍需真实表达，unknown先对账，不自动重派。
- 新合同压缩重复依赖表示，保留完整material绑定；旧字段和旧事件可读，原hash不改写。不能仅加缓存就宣称完成合同简化。
- 禁止任何历史rows/runs/records/logs清理；旧schema迁移须保留原始证据，重复执行无额外效果。
- 不引入安全专项工程或测试；不调用产品模型、OCR、翻译；不碰live/监查或全局配置。
- 允许路径仅隔离区protocol_workflow、protocol_v3合同、对应测试与任务证据，具体写入归属由实施包进一步限定。

## Acceptance Criteria

- [x] 合并后真实SQLite结果接收、消费、重启与重复投递无重复业务效果。
- [x] 既有无outbox的独立结果可兼容，不伪造可派发请求或工作流身份。
- [x] 迁移前后结果ID、来源、历史事件与重放结果保持可核对，旧行不删除。
- [x] completed可复用、failed有明确恢复、unknown不重派；内部活动状态不丢失。
- [x] 改任一实质输入或章节合同会使依赖绑定变化；版本化迁移不伪称hash不变。
- [x] 旧负向用例保留，新增失败测试先于实现；protocol_v3及1R.3集成回归通过。
- [x] 独立verifier检查实际结果后由Codex关闭任务；未完成项不得因排程而标PASS。

验收：reviews/codex_conference_mw_protocol_v3_1r4_durable_fresh_20260905_review.md
及contract_fresh复核；1477mergedpass35.17s。真实产品首个v1_1构造与已提交
dispatch factory强制接线仍属2R.1，P1R全套/产品模型接入仍未完成。

## Notes

- 原计划1R.5为USER_EXCLUDED；1R.4完成后进入1R.6，不新增安全断点。
- 本任务不代表全仓遗留对账完成；1R.2相关债务仍在P1R-G1之前处理。
