# Conference Metrics: mw_protocol_v3_interactive_fallback_review_20260923

Date: 2026-09-23

| Role | Provider | Model | Status | Duration | API calls | Tokens | Result |
|---|---|---|---|---:|---:|---:|---|
| `general_single_object` | `zcode` | `GLM-5.3-Flash` | completed | 1600.845 s | 3 | 2873 in / 6714 out | incorporated; no route fallback |

## Timeout And Retry Evidence

The first pass ran 1018.172 s. Two requested same-session follow-ups ran 222.549 s and 360.124 s. All used session `sess_b561bbbe-5075-4299-86de-b03c7792183d`; runner receipts report request and response model `GLM-5.3-Flash` on `zcode-live-bigmodel`. There was no transport/model fallback and no replacement session.

## Quality Decision

The initial review found five repairable defects. Codex repaired them and the same reviewer rechecked the frozen current diff. Final deterministic evidence is 297 focused tests and 2608 Protocol v3 tests passing. The bounded code review passes; live MTPLX quality and final browser/Word/medical acceptance remain outside this decision.
