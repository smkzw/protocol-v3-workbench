# Conference Metrics: mw_r11_v05_evidence_review_20260922

Date: 2026-09-22

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_single_object` | `zcode` | `GLM-5.3-Flash` | completed, 2 rounds | initial 868s; continuation 315s | 2 model rounds | estimated 6,198 | PASS after repair |

## Timeout And Retry Evidence

The first runner held one session through its 868-second completion; latency did not trigger cancellation or fallback. The repair verification resumed the exact session ID and completed a second round in 315 seconds. Both returned code 0. Health probe passed; fallback was null.

## Quality Decision

Round 1 produced actionable M1/L1/L2 findings backed by probes. Round 2 verified their repair and found one bounded empty-section edge, which Codex closed directly and re-ran in the same 117-test matrix. Final quality decision: engineering PASS; real product-model artifact and medical conference pending.
