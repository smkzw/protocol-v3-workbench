# Codex Main-Venue Plan: mw_protocol_v3_phase1_task15_final_acceptance_20260810

Date: 2026-08-10
Objective: 独立验收 Protocol v3 Task 1.5 最终 checkpoint 全前缀双重 replay 修复及既有事件/outbox/inbox 权威合同无回归

## Task Decomposition

Two fresh independent participants falsify the complete-prefix double replay and check prior Task 1.5 invariants for regression. Codex reproduces and repairs any P0–P4; the discovering participant closes each repair in the same session.

## Source Packet

Frozen Task 1.5 plan/design section 18 and the current narrowly listed source/test files. Prior reports are Codex decision history and excluded from participant read sets.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_pi_qwen38` | effective daytime `cms-smk` | `cms-model` high | `runs/conference/mw_protocol_v3_phase1_task15_final_acceptance_20260810/general_pi_qwen38.md` |
| `general_grok45` | `grok-build`; declared fallback `cursor-cli` | `grok-4.5`; fallback `cursor-grok-4.5-high` | Grok initial/round2/round3 plus Cursor fallback initial/round2/round3 reports |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

Participant 1 completed in 724.58 s. Grok returned progress-only output in 30.02/105.44/30.32 s, exhausting the no-progress breaker; declared Cursor fallback completed 195.73/91.57/56.88 s in one session. No late output or undeclared fallback was used.

## Codex Verification Checklist

- Require unknown-schema predecessor and pairwise-stateful migration to quarantine before checkpoint success.
- Require PENDING/no-handler paths to perform no incorrect effect or terminal classification.
- Require no open P0–P4, 155 focused tests, 376 integrated tests and clean static checks.
