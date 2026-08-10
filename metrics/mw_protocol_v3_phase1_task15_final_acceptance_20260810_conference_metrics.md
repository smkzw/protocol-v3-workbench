# Conference Metrics: mw_protocol_v3_phase1_task15_final_acceptance_20260810

Date: 2026-08-10

| Role/pass | Effective provider | Model | Status | Duration | Session | Result |
|---|---|---|---|---:|---|---|
| Participant 1 | `cms-smk` | `cms-model` high | completed | 724.58 s | `019feb4a-8bda-7000-a4d5-96c056acac8c` | `READY` |
| Participant 2 initial | `grok-build` | `grok-4.5` | no-progress | 30.02 s | `ddd0dfb6-2cf0-4cce-ad90-947864b3d5c3` | 295-char progress only |
| Participant 2 follow-up 1 | `grok-build` | `grok-4.5` | no-progress | 105.44 s | same | 245-char progress only |
| Participant 2 follow-up 2 | `grok-build` | `grok-4.5` | no-progress | 30.32 s | same | 140-char progress only |
| Declared fallback initial | `cursor-cli` | `cursor-grok-4.5-high` | completed | 195.73 s | `f09678ec-2a43-452d-a0d2-bd74ef62602e` | `NOT_READY` P3 |
| Fallback follow-up 1 | `cursor-cli` | `cursor-grok-4.5-high` | completed | 91.57 s | same | `NOT_READY` P4 |
| Fallback follow-up 2 | `cursor-cli` | `cursor-grok-4.5-high` | completed | 56.88 s | same | `READY` |

## Timeout And Retry Evidence

No active route was killed for latency. Grok fallback was activated only after three terminal, progress-only outputs met the no-progress breaker. Cursor remained in one session through both repair reviews. All runner stdout and reports are retained.

## Quality Decision

`READY`. Main venue also owns executable evidence: 155 focused and 376 integrated tests plus static checks; no open P0–P4.
