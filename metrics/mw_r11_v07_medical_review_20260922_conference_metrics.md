# Conference Metrics: mw_r11_v07_medical_review_20260922

Date: 2026-09-22

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `evidence_single_object` | `grok-build` | `grok-4.7` | terminal completed | 结构化时长未保留 | 结构化计数不可用 | 结构化计数不可用 | REVISE |

## Timeout And Retry Evidence

会议在北京时间高峰路由上直接使用 `grok/grok-build/grok-4.7:high`。一次完整审阅得到非空终态报告，runner receipt 为 `ok=true`、`rounds_completed=1`、`fallback=null`、`failure=null`；没有重复派发。结构化 duration/API/token receipt 未进入当前证据包，因此明确记为不可用。

## Quality Decision

报告覆盖 85/85 节，给出事实基线、逐类缺陷、4 张决定卡、7 个 source gap、v0.5 缺陷闭合状态和低点击修复方案，足以支持 `REVISE`。v0.8 工程修改和后续工件需另行验证。
