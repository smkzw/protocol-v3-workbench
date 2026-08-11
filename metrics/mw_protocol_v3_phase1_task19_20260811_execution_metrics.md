# Execution Metrics: mw_protocol_v3_phase1_task19_20260811

Date: 2026-08-12

| Role/pass | Effective provider | Model | Status | Duration | Session | Result |
|---|---|---|---|---:|---|---|
| Worker 01 initial | `opencode-go` | `deepseek-v4-flash` max | rejected | 90.01 s | `019ff153-096a-7000-af85-e8ab7032277f` | runtime identity mismatch; artifacts retained |
| Worker 01 fallback | `deepseek` | `deepseek-v4-flash` max | completed | 192.47 s | `019ff16e-cc82-7000-96cc-d03b8f9e9a90` | verified application service |
| Worker 02 initial | `opencode-go` | `deepseek-v4-flash` max | completed | 860.62 s | `019ff174-71ab-7000-8c4b-3411b2dfe529` | repair required |
| Worker 02 recovery 01 | same | same | completed | 485.65 s | same | removed retained authority |
| Worker 02 recovery 02 | same | same | completed | 211.46 s | same | enforced non-empty lineage |
| Worker 03 initial | `opencode-go` | `deepseek-v4-flash` max | completed | 1379.22 s | `019ff18c-83ef-7000-8617-dab46af43dab` | repair required |
| Worker 03 recovery 01 | same | same | completed | 488.39 s | same | hardened API/client public contract |
| Manager initial | `cursor-cli` | `auto` | completed | 220.59 s | `ffdaef29-2498-48dd-a5f8-c1da52b18669` | bounded review |
| Manager final | same | same | completed | 164.37 s | same | `READY_FOR_FRESH_VERIFIER` |

Tool-call counts were not separately emitted by every harness; complete stdout/tool histories are retained in the runner logs rather than replaced by estimates.
