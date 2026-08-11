# Conference Metrics: mw_protocol_v3_phase1_task19_acceptance_20260812

Date: 2026-08-12

| Pass | Provider | Model | Status | Duration | Session | Result |
|---|---|---|---|---:|---|---|
| Participant 1 | `alibaba` | `qwen3.8-max` xhigh | completed | 1500.31 s | `019ff1b3-340c-7000-b05f-1f11891c5a2d` | `READY` |
| Participant 2 initial | `grok-build` | `grok-4.5` | incomplete | 23.45 s | `0f34c5e2-0370-4b70-82c3-40e4d8decb71` | tool calls cancelled |
| Participant 2 recovery 01 | same | same | incomplete | 34.17 s | same | no decisive evidence |
| Participant 2 recovery 02 | same | same | terminal incomplete | 64.62 s | same | declared fallback activated |
| Cursor fallback initial | `cursor-cli` | `cursor-grok-4.5-high` | completed | 187.34 s | `5efa0f36-3e9f-4bf9-97dd-550f54591e75` | static no-defect; Shell blocked, `NOT_READY` |
| Cursor fallback same-session completion | same | same | completed | 72.74 s | same | runtime checks complete, `READY` |

## Timeout And Retry Evidence

No route was failed for latency. Grok used the initial pass plus both allowed same-session recovery passes and still produced no usable tool evidence, satisfying the declared fallback condition. Cursor fallback retained one session; the second pass changed only execution permission from Ask to Shell-enabled and did not redispatch or change model.

## Quality Decision

`PASS`. Qwen and Cursor independently executed the decisive tests/checks and converged on no P0–P4 defect. Grok's incomplete history is retained as routing evidence, not counted as product failure or overwritten.
