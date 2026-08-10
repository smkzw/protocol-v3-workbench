# Codex Main-Venue Plan: mw_protocol_v3_phase1_task15_acceptance_20260810

Date: 2026-08-10
Objective: 独立反证验收 Protocol v3 Task 1.5 的事件权威、确定性重放、事务性 outbox/inbox 与真实重启恢复；不做安全性测试

## Task Decomposition

One isolated high-risk contradiction reviewer audits Task 1.5 source/tests, returns exact P0–P4 counterexamples, and remains in the same session for at most two targeted repair reviews. Codex owns all implementation repairs and executable acceptance.

## Source Packet

Frozen Task 1.5 plan and design section 18; current event/outbox/inbox/UoW source, ports/reference adapter and three focused tests. Worker/manager conclusions are excluded from the reviewer read set.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `codex_luna_acceptance` | `codex` CLI compatibility | `gpt-5.6-luna` max | `runs/conference/mw_protocol_v3_phase1_task15_acceptance_20260810/codex_luna_acceptance.md` plus round 2/3 |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

Initial 1341.21 s, round 2 839.26 s, round 3 246.48 s; one session, no timeout/fallback. All three verdicts were incorporated as repair evidence; the final remaining P2 moved to a fresh acceptance venue after same-session follow-ups were exhausted.

## Codex Verification Checklist

- Verify exact event/upcaster/stream/revision/checkpoint contracts and honest crash semantics.
- Run only the three focused tests or narrower probes; no security or medical-monitoring work.
- Preserve every report/stdout/session ID and do not accept any worker self-verdict.
