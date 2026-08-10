# Metrics: mw_protocol_v3_phase0_source_closure_20260810

Date: 2026-08-10

| Field | Value |
|---|---|
| Task type | `code_scoped_patch_plan` |
| Risk | `medium` |
| Selected provider | `codex` |
| Selected model | `codex-main` |
| Selected effort | `high` |
| Duration | ~7 minutes |
| API calls | Local filesystem/import/test tools only; no model dispatch |
| Artifact size | 3 restored files, 714 source/test lines plus narrow policy/test delta |
| Result | `PASS` |

## Verification Burden

Three authoritative SHA-256 comparisons; two positive source-policy/manifest tests; 14 restored
medical-writing token tests; contract/service import smoke; 8 Word verification/repository tests;
compile and diff checks.

## Routing Decision

Direct Codex route was retained because exact hashes and deterministic local functional tests fully
cover the repair. No conference or fallback was necessary; Hermes was not dispatched.
