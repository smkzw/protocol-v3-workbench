# Conference Metrics: mw_protocol_v3_phase0_task08_acceptance_20260810

Date: 2026-08-10

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_pi_qwen38` | `cms-smk` | `cms-model` | complete | 358.269 s | provider-reported session | 85,825 | READY |
| `general_pi_qwen38` lineage update | `cms-smk` | `cms-model` | complete, same session | 158.269 s | 1 same-session pass; 43 tool calls | 108,463 | READY |
| `general_grok45` | `grok-build` | `grok-4.5` | complete after 2 recoveries | 45.151 + 34.630 + 123.656 s | 3 same-session passes | 239,422 + 124,625 + 131,777 | READY_WITH_RESIDUALS |

## Timeout And Retry Evidence

- Pi daytime route rewrite was recorded; no fallback.
- Pi lineage update resumed session `019fe981-3e54-7000-a68e-ae2c4ff8afaa`; one pass ended
  normally with 67 tests and exact current-identity validation. No fallback.
- Grok pass 1 and recovery 1 ended `cancelled` with incomplete progress text. Session
  `a68dc987-6507-4370-8685-c40785e76a12` was reused; recovery 2 ended `end_turn` with the full
  report. No fallback or re-dispatch.

## Quality Decision

Panel accepted, including the current producer lineage update. Codex resolved the actionable
residuals and retained target-workstation/corpus scope limitations. Gate:
`P0-WORD_TECHNICAL_PASS_WITH_RESIDUALS`.
