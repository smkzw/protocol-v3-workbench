# Metrics: mw_protocol_v3_phase1_task13_20260810

Date: 2026-08-10

| Field | Value |
|---|---|
| Task type | `finite_code_task` |
| Risk | `high` |
| Selected provider | `cms-smk` |
| Selected model | `cms-model` |
| Selected effort | `high` |
| Duration | about 1 h 40 min wall time including long independent verification |
| API calls | 3 initial worker passes, 3 same-session worker/manager repair passes, 2 fresh Luna verifier sessions |
| Artifact size | 176 KiB product/test source across seven Task 1.3 files |
| Result | `ACCEPTED` — fresh verifier `READY`; focused suite `151 passed` |

## Verification Burden

High because persistence identities, CAS, idempotency, immutable revision lineage and replay semantics are shared foundations for every later workflow phase. Acceptance therefore required deterministic functional tests plus a fresh isolated verifier after manager review.

## Routing Decision

Finite-code execution used the guard-selected CMS route with Cursor manager. The current App explicitly rejected native `gpt-5.6-luna`; per global routing policy Codex used the CLI compatibility route at max reasoning. No fallback was triggered by latency.
