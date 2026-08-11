# Metrics: mw_protocol_v3_phase1_task16_20260810

Date: 2026-08-11

| Field | Value |
|---|---|
| Task type | `finite_code_task` |
| Risk | `high` |
| Initial provider/model | `cms-smk/cms-model` (`high`) |
| Duration | approximately 13 h including long provider waits and repair reviews |
| New runtime + focused test bytes | 97,820 |
| Focused Task 1.6/repository tests | 112 passed |
| Integrated named Task 1.1–1.6 tests | 423 passed |
| Static checks | Ruff check/format, in-memory compile, diff check pass |
| Medical-monitoring changes | 0 |
| Result | `PASS` |

## Verification Burden

The initial worker output required Codex state-machine/identity repairs, an execution-manager discovery fix, a Qwen contradiction pass with five findings, a same-session Qwen READY pass, and declared Cursor fallback after three terminal Grok cancellations.

## Routing Decision

Finite-code execution used the guard-selected route. High-risk independent review used Qwen in its dispatch-time Beijing route window and native Grok Build. Cursor fallback was activated only after Grok exhausted both same-session recovery passes. All tool calls and route evidence are retained.
