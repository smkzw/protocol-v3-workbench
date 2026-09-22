# Study A 全文补写 v0.9 与独立医学审阅

日期：2026-09-22

## 真实产品运行

- job：`mwjob_bb370670e7bc8936451212fd`
- schema：`protocol_full_draft_artifact_v9`
- SHA-256：`d1e5ad959fd5cdce693e86f072ae39fff9a4056d1601320b86061bfa9d216820`
- 实际路由：`opencode-go/deepseek-v4.1-flash:max`
- attempt：1/2；22/22 批；无 fallback；运行约 57 分钟。
- 85/85 节；44 complete、1 decision_required、40 source_gap；2 张决定卡；1 个 required；264 个节级证据引用；104 个来源绑定；22 个 AI run。

## 相比 v0.8 的改善

方案概要恢复成文；疾病背景、筛选失败、剂量调整、药物过量、计划外访视、AE 定义、具体药物风险、保险等缺项目来源的章节不再用通用句伪装完成。盲法章节不再指定盲态人员。探索性卡只使用语义匹配字段并提供“不设置”选项。统计分析恢复一个明确升级口。

## Fresh 医学会商

会商 `mw_r11_v09_medical_review_20260922` 实际使用 `grok/grok-build/grok-4.7:high`，session `0384d0f2-205a-4a4b-9d9f-42a2e824631b`，单轮完成、无 fallback，结论 `REVISE`。

数值事实稳定，没有 Critical 级剂量、人群、终点、访视或样本量冲突。仍需修复：§9.5 自行设定安全性采集从第1天开始；估计目标跨章措辞不一致且统计闸只显于 §9；§7.3.1 把体格检查并入安全性终点；多个运营/伦理章节把公司语料写成本项目义务；两张探索性卡尚不能原子联动。

## 验证与处置

受影响集中测试最终 `106 passed`，Python 编译与 `git diff --check` 通过。v0.9 不采纳、不写入 Word，保留为不可变专家审阅基线。下一阶段从 v0.10 生成规则修复开始；修复前不得重跑上游资料处理或重复 v0.9 job。
