# Conference Metrics: mw_r11_v09_medical_review_20260922

Date: 2026-09-22

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `evidence_single_object` | `grok-build` | `grok-4.7` | terminal completed | 714.392 s | CLI receipt does not expose API-call count | 983,614 total | REVISE |

Token receipt: input 266,233; cache-read input 674,944; output 42,437; reasoning 25,879. Session: `0384d0f2-205a-4a4b-9d9f-42a2e824631b`.

## Timeout And Retry Evidence

健康探针成功，路由在北京时间高峰保持 `grok/grok-build/grok-4.7:high`。单轮完成，return code 0，未超时，runner `ok=true`，fallback 和 failure 均为空；没有重派或同会话追加轮。输出 SHA-256 为 `a2783f03c20f255acb7052229ae81e4b4549cab09d3ddcf4bf057e9505e2d6e9`。

## Quality Decision

报告覆盖全部 85 节，区分事实、推断、修复责任和不确定性，定位四类高影响残留并给出低点击交互方案，足以支持 `REVISE` 和下一阶段 v0.10 修复包。它不替代正式统计、PV、运营、Word 或监管验收。
