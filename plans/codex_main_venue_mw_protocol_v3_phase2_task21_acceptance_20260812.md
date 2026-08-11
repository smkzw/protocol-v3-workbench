# Codex Main-Venue Plan: mw_protocol_v3_phase2_task21_acceptance_20260812

Date: 2026-08-12
Objective: Fresh-context independent acceptance of Protocol v3 Task 2.1 immutable typed case contracts, deterministic fakes, three clinical design graphs and fail-closed recovery/isolation evidence; read-only, no security tests

## Task Decomposition

1. Two fresh, read-only participants independently falsify the same Task 2.1 artifact set without reading worker/manager/peer reports.
2. Concrete counterexamples outrank a nominal verdict. Any reproduced blocker returns to the original owning worker session for a bounded repair.
3. The same participant session rechecks a repaired tree; Codex reproduces the decisive anchors and owns acceptance.
4. No service, provider, scheduler, database, product route, medical-monitoring path, Task 2.2 work or security test is in scope.

## Source Packet

- Frozen plan Task 2.1, SHA-256 `fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914`.
- Conference context `context/mw_protocol_v3_phase2_task21_acceptance_20260812_conference_context.md`.
- Exactly seven files under `pocs/protocol_v3/orchestrator/` listed in that context.
- Reproducible anchors: focused tests, full `tests/protocol_v3`, pinned material hashes, import isolation and protected-path diff.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_pi_qwen38` | `alibaba` | `qwen3.8-max` | `runs/conference/mw_protocol_v3_phase2_task21_acceptance_20260812/general_pi_qwen38.md` |
| `general_grok45` | `grok-build` | `grok-4.5` | `runs/conference/mw_protocol_v3_phase2_task21_acceptance_20260812/general_grok45.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

- Qwen session `019ff2f2-be75-7000-a21c-2f98c582c16d`: round 1 vetoed a hidden-cycle false negative and mutable fake-record payload; the owning sessions repaired both; round 2 reused the same session and returned `TASK21_READY`. Total 1519.884 s, 139 recorded tool events, no fallback.
- Grok session `e63af615-c538-47f9-b160-7043a8482bd7`: initial and two same-session continuations produced no usable review; final continuation failed explicitly. Total 53.904 s. Recovery was exhausted and no fallback/new session was dispatched because the user requested closure and pause.
- No late participant output was incorporated after the final decision.

## Codex Verification Checklist

- [x] Frozen plan hash matches.
- [x] Seven-file allowlist and protected-path boundary verified.
- [x] Hidden parallel-edge cycle fails closed at construction and read time.
- [x] Direct mutable fake-record payloads fail closed; frozen equivalents remain immutable.
- [x] Focused suite passes 75/75; full functional suite passes 1,226 tests plus 101 subtests.
- [x] Three pinned material hashes reproduce unchanged.
- [x] Qwen fresh verifier returns `TASK21_READY` after repair.
- [x] Grok degradation, recovery history and missing usable verdict are disclosed rather than treated as agreement.
- [x] Acceptance is explicitly limited to Task 2.1 PoC contracts; Task 2.2 and release remain pending.
