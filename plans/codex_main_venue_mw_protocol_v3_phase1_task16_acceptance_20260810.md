# Codex Main-Venue Plan: mw_protocol_v3_phase1_task16_acceptance_20260810

Date: 2026-08-10
Objective: 隔离反证验收 Protocol v3 Task 1.6 ExecutionReservation 的预留先行、终态不确定恢复、显式 retry decision 追加谱系与 fallback 最小重打包；不做安全性测试

## Task Decomposition

1. Participant 1 independently falsifies reservation state/identity/recovery semantics.
2. Participant 2 independently falsifies the same complete scope without reading participant 1.
3. Codex reproduces every concrete finding against the current filesystem, performs bounded repairs when proved, and sends only targeted same-session follow-ups when needed.
4. Codex reruns the named Task 1.1-1.6 functional suite, static checks, frozen hash and medical-monitoring boundary before acceptance.

## Source Packet

- Frozen Task 1.6 plan and approved design sections 17.2/18.
- Current ExecutionReservation contract, runtime, repository port/reference adapter and two named functional tests listed in the conference context.
- Prior worker/manager/review/run/log outputs excluded for verifier isolation.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_pi_qwen38` | `alibaba` | `qwen3.8-max` | `runs/conference/mw_protocol_v3_phase1_task16_acceptance_20260810/general_pi_qwen38.md` |
| `general_grok45` | `grok-build` | `grok-4.5` | `runs/conference/mw_protocol_v3_phase1_task16_acceptance_20260810/general_grok45.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

- Use runner-recorded start/end/session/provider/model/fallback state.
- Wait for both declared roles to reach terminal state or explicit hard-wait return; do not redispatch due to latency.
- Same-session follow-up only for a concrete finding, incomplete output or repair recheck.

## Codex Verification Checklist

- Reproduce all P0-P4 findings; reject unsupported opinions.
- Run only `test_execution_reservations.py`, `test_repository_contract.py`, and the explicitly named Task 1.1-1.5 functional regressions; never directory-wide Protocol v3 tests.
- Ruff check/format, compileall, `git diff --check`, frozen-plan SHA-256 and zero medical-monitoring diff.
- Confirm runtime package is trackable without unignoring unrelated runtime directories.
- READY only after no open P0-P4 remains; then update task/review/metrics, archive execution/conference tool evidence, remove only regenerated cache/bytecode, and commit the Task 1.6 slice.
