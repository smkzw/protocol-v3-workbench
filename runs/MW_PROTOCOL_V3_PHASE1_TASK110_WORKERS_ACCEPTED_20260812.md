# Protocol v3 Phase 1 Task 1.10 — Worker Acceptance Checkpoint

Date: 2026-08-12
Status: `TASK110_ACCEPTED`

## Accepted scope

- Worker 01: immutable read-only legacy inventory and one-to-one quarantine accounting.
- Worker 02: real-contract v2→v3 mapping, deterministic dry-run, identity/revision binding, whole-payload preservation and idempotent lineage.
- Worker 03: forward-only per-project cutover state, deterministic mutation inventory, read parity and route/service fail-closed guard.

## Decisive evidence

- Mapping spec SHA-256: `34db4b34d5b94114f88c171c125c817d61962cfac3ad2329c1dd63b76b1bdfa2`; 20 real source locators verify with zero issues.
- Mutation inventory SHA-256: `2e44f83a1992b7b2da8497a761666bf77905827291f99dda38247bedb2ae9df0`; 235 route handlers, 133 mutating routes and 195 service candidates produce zero drift findings.
- Guarded operations: 101 route-level and 94 service-level legacy writes.
- Codex reproduced then closed the investigator-brochure bypass in the same Worker 03 session: both route and medical-writing source-intake service now raise `legacy_mutation_blocked` in SHADOW_READ_ONLY and NEW_CANONICAL; monitoring source intake remains excluded.
- Four Task 1.10 tests: 225 passed. API isolation: 3 passed, 29 deselected. Full Protocol v3: 1,226 passed.
- Fresh Qwen exposed and Codex reproduced the whole-payload coverage drift hole. Worker 02 Recovery 04 repaired exact two-way field equality; missing identity/project/revision, SQLite status/working-copy and fabricated fields now all fail closed.
- Frozen plan SHA-256 remains `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`; `main.py`, v2 sources and medical-monitoring have no task changes.

## Durable sessions and evidence

- Worker 01: `019ff1dd-fec4-7000-85f0-df4dd3ccfcd6`.
- Worker 02 primary: `019ff1f3-8cb2-7000-b56f-dde6d7495da1` (terminally non-resumable); accepted fallback: `019ff1fa-fdb7-7000-a01c-8985e7b81e55`.
- Worker 03 initial and repair: `019ff239-6131-7000-b581-d2ba19052dc4`; no fallback or model switch. Recovery raw stdout/tool events are retained under `archives/execution/mw_protocol_v3_phase1_task110_20260812/`; conference prompts/reports/logs remain under their original conference paths.

## Acceptance and next safe action

Cursor manager session `7656b349-59bf-412a-941f-7b1610c42c34` returned `READY_FOR_FRESH_VERIFIER`. Qwen `019ff263-0be7-7000-a840-05fc158df23f` and Grok `0f7edd46-b967-48d4-98e9-e803c92e5f88` both returned READY after repair in their original sessions; Codex final checks match. Archive retained evidence and commit the accepted Task 1.10 scope. Do not run the plan's Task 1.11 security matrix because the user explicitly excluded security testing; inspect the frozen phase gate before selecting the next non-security action.
