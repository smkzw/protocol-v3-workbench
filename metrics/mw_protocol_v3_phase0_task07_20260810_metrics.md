# Metrics: mw_protocol_v3_phase0_task07_20260810

Date: 2026-08-10 09:27 CST

| Field | Value |
|---|---|
| Task type | `code_scoped_patch_plan` |
| Risk | `medium` |
| Selected provider | `codex` |
| Selected model | `codex-main` |
| Selected effort | `high` |
| Duration | 14 minutes |
| API calls | 0 product API calls; Microsoft primary documentation reviewed read-only |
| Artifact size | 49 KiB contract, fixture, tests and decision record |
| Result | PASS — Task 0.7 contract only; P0-WORD blocked |

## Verification Burden

- 1 complete native Word receipt fixture and 1 historical trace negative fixture.
- 55 focused functional contract tests; compile, JSON parse and diff check passed.
- 4 exact staleness dimensions; 3 non-Word producer labels; full bookmark/reference/page/OOXML/lineage fail-closed matrix.
- 0 Word launches, 0 services, 0 runtime mutations, 0 security/adversarial tests.
- 1 adjacent old-suite collection failure traced to a pre-existing source-only false-positive exclusion; no test body executed and no repair was hidden in this task.

## Routing Decision

Initial route reason: default route for task type.

Codex direct was retained because this producer-neutral contract fits one context. No fallback or external model route was used.
