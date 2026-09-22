# Study A 全文补写 v0.8 医学审阅

日期：2026-09-22

## 冻结工件

- job：`mwjob_cffd00bfa3697e3b95523084`
- schema：`protocol_full_draft_artifact_v8`
- SHA-256：`767923242f5cc7ca95837e67a68322990a14b2b7a1512793ccf0ce9023259133`
- 产品路由：`opencode-go/deepseek-v4.1-flash:max`
- 85/85 节；70 complete、3 decision_required、12 source_gap；4 张决定卡；407 条证据绑定；22 个 AI run。

## 独立医学会商

会商 `mw_r11_v08_medical_review_20260922` 实际使用 `grok/grok-build/grok-4.7:high`，无 fallback，只读审阅，结论 `REVISE`。数值事实稳定，v0.7 的三套安全窗、DLQI 冲突时点、伴侣妊娠/新生儿推断和 21 个空 required 壳已关闭。

仍未关闭的核心问题：统计升级消失；§1 概要被误判缺资料、§2.1 背景却误标完成；§8.2.1 自行写入 AE 定义；§4.4 自行指定盲态人员；CMS-D017 公司语料仍绑定本项目 AE 章节；合并用药卡与未定义救援治疗冲突；多个运营章节用通用句伪装完成。

## Owner 处置

v0.8 不采纳、不写入 Word。生成器升为 v0.9：决定字段只保留探索性目的/终点并加入“不设置”；缺项目来源的运营规则全部降为 source gap；概要必须用确认事实成文；统计分析保留一个 required 升级；禁止盲态人员、通用 AE 定义和安全日程推断。

集中受影响测试 90 passed。下一动作保持同一隔离环境，以新 logical work key 运行真实 v0.9，检查三态、证据绑定、决定绑定和统计升级后进行 fresh 医学会商；不得重复上游资料处理。
