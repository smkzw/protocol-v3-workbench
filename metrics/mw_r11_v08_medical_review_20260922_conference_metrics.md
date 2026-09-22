# Conference Metrics: mw_r11_v08_medical_review_20260922

Date: 2026-09-22

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `evidence_single_object` | `grok-build` | `grok-4.7` | terminal completed | structured receipt unavailable | unavailable | unavailable | REVISE |

## Timeout And Retry Evidence

会议按北京时间高峰静态策略使用 `grok/grok-build/grok-4.7:high`。一次完整审阅得到非空终态报告；没有 fallback，也没有重复派发。当前证据包未保存 duration、API call 和 token 的结构化统计，故明确记为 unavailable，不以估算值补写。

## Quality Decision

报告全量覆盖 85/85 节，核验冻结哈希、三态分布、4 张卡、12 个缺口、407 条证据绑定及既往缺陷闭合情况，足以支持 `REVISE`。v0.9 真实产品工件必须重新生成并接受 fresh 医学审阅。
