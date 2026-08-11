# Conference Metrics: mw_protocol_v3_phase1_task16_acceptance_20260810

Date: 2026-08-11

| Role/pass | Effective provider | Model | Status | Duration | Session | Result |
|---|---|---|---|---:|---|---|
| Participant 1 initial | `alibaba` | `qwen3.8-max` xhigh | completed | 3449.03 s | `019fec2a-bb00-7000-8b5c-fe54956ba568` | `NOT_READY` 2 P3 / 3 P4 |
| Participant 1 follow-up | `alibaba` | `qwen3.8-max` xhigh | completed | 676.92 s | same | `READY` 112 tests / 31 probes |
| Participant 2 initial | `grok-build` | `grok-4.5` | cancelled | 31.61 s | `6fe64da8-28d6-4f82-8cd8-b82519ce070c` | progress-only |
| Participant 2 recovery 1 | `grok-build` | `grok-4.5` | cancelled | 27.03 s | same | progress-only |
| Participant 2 recovery 2 | `grok-build` | `grok-4.5` | cancelled | 24.02 s | same | progress-only |
| Declared fallback | `cursor-cli` | `cursor-grok-4.5-high` | completed | 149.28 s | `d9b5af7b-caf7-463d-b6f7-c12a7fb6d6cb` | `READY` static; pytest blocked by Ask-mode |

## Timeout And Retry Evidence

No route was killed for latency. Qwen retained one session. Grok fallback occurred only after the initial pass and both allowed same-session recovery passes ended `stopReason=cancelled`; all three raw outputs are preserved. Cursor was a declared route fallback, not a silent model substitution.

## Quality Decision

`READY`. Qwen independently executed the focused suite and closed every former finding. Cursor supplied a second static falsification perspective. Codex owns the decisive executable evidence: 112 focused and 423 integrated tests plus static/hash/boundary checks; no open P0-P4 remains.
