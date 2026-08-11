# Metrics: mw_protocol_v3_p1g1_functional_gate_20260812

Date: 2026-08-12

| Field | Value |
|---|---|
| Task type | `high_risk_contradiction_review` |
| Risk | `high` |
| Selected provider | `codex` |
| Selected model | `gpt-5.6-luna` |
| Selected effort | `max` |
| Duration | Luna first pass 53.774 s; same-session recheck 39.488 s |
| API calls | Runner reports 0 explicit tool-call events; CLI command/test evidence retained in stdout/report |
| Artifact size | 51,035 inventory rows; 5,992 protected assets; 20 migration source types |
| Result | `P1-G1_FUNCTIONAL_READY`; frozen P1-G1 incomplete because security is `USER_EXCLUDED` |

## Verification Burden

High: reconcile accepted Task 1.1–1.10 evidence, current tests, immutable manifests, zero-write/migration/replay properties and H0/H1/H3 without running prohibited security tests or inventing a live cleanup.

## Routing Decision

Initial native `gpt-5.6-luna:max` probe returned unknown model. Per global policy the exact Luna CLI compatibility route was used; the same CLI session handled the targeted recheck. No alternate model or Hermes route.
