# Study A 全文初稿 v0.7 医学复核

日期：2026-09-22
状态：真实产品生成与 fresh 医学会商完成；v0.7 判定不可采纳，v0.8 修复已启动

## 冻结工件

- Job：`mwjob_6ea88e6715579409992c43ee`
- 工件：`protocol_full_draft_artifact_v7`
- SHA-256：`e199d57fd14d6d78ea630e02bdc8ba20592f01dc06233f4fd83d32f41c1a99ce`
- 产品路由：`opencode-go/deepseek-v4.1-flash:max`
- 执行：22/22 批，85/85 节，attempt 1 完成，无 fallback
- 状态：75 complete、3 decision_required、7 source_gap
- 决定项：4 个；待决定 proposal 全为空
- 证据：469 个逐节 evidence binding；22 个 AI run 且全部唯一
- required review：21 节；adoption_ready=false

## 相对 v0.5 的改善

- 73 个决定项降为 4 个，没有重复 fact_path。
- 用户确认前不再预写决定正文。
- SUSAR“转归”错误定义、错误 field path 和多数通用填充已消失。
- source gap 从 13 个收敛为 7 个，且 7 个均属真实资料缺口。

## fresh 医学会商

- 路由：`grok/grok-build/grok-4.7:high`，与产品生成模型独立。
- 结论：REVISE。
- 关键问题：由访视日推断安全性日程；自定 TEAE 窗；DLQI 时点前后不一致；伴侣妊娠、新生儿随访和避孕问询缺乏项目依据；估计目标术语混用；部分 complete 只是“本章应覆盖”的范围说明；21 个 required 没有实际卡片；合并用药卡选择写法而非医学边界。
- 报告：`runs/conference/mw_r11_v07_medical_review_20260922/evidence_single_object.md`
- Owner review：`reviews/codex_conference_mw_r11_v07_medical_review_20260922_review.md`

## 已启动的 v0.8 修复

- 明确禁止从访视策略推断检查日程、从终点推断 DLQI 采集日程、从排除标准推断避孕/伴侣妊娠规则。
- complete 只允许可直接入方案的正文，范围说明不得冒充正文。
- 决定选项必须具体、互斥且可执行；否则退回 source gap。
- 复述性高影响章节改为合并摘要核对；统计混合估计目标保留一个明确升级口。
- 122 项集中回归通过，`git diff --check` 通过。

## 下一动作

同一隔离环境已启动 v0.8 新 logical job。完成后核对 85 节状态、危险规则、决定质量、证据链和 required 数量，再发起 fresh 医学会商。v0.7 不写入 Word，不触发上游检索、分诊、下载、OCR 或翻译。
