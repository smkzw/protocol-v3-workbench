# Codex Main-Venue Plan: mw_protocol_v3_phase0_task08_acceptance_20260810

Date: 2026-08-10
Objective: 独立只读验收Protocol v3 Task 0.8 Word原生producer功能闭环、失败阻断、不可变回导lineage和逐页证据；禁止任何安全、对抗、权限、路径、符号链接、竞态、恶意输入或破坏性测试

## Task Decomposition

1. Participant 1 independently validates contract/code/recovery/lineage and focused functional tests.
2. Participant 2 independently challenges evidence sufficiency, failed-path classification and
   page-evidence claims from the existing artifacts.
3. Codex compares both reports with its own 27-page visual review, exact source hashes, current
   Word inventory and strict receipt validation. Only Codex disposes the P0-WORD result.

## Source Packet

- Frozen plan Task 0.7–0.8, contract and checked-in focused tests.
- `pocs/protocol_v3/word_receipt/decision.md` and `README.md`.
- CMS initial/final roundtrip receipts and all 27 page images/contact sheets.
- TP-MA-07 candidate/contact sheets and D017 immutable events.
- Task 0.8 context. No external or medical-monitoring path is assigned to participants.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_pi_qwen38` | `alibaba` | `qwen3.8-max` | `runs/conference/mw_protocol_v3_phase0_task08_acceptance_20260810/general_pi_qwen38.md` |
| `general_grok45` | `grok-build` | `grok-4.5` | `runs/conference/mw_protocol_v3_phase0_task08_acceptance_20260810/general_grok45.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

- Start: 2026-08-10 10:28 after both prompts passed preflight.
- Each route is launched once with the guard-generated command and a 120-minute hard wait.
- Same-session follow-up only for an actionable gap; no fixed polling or latency fallback.

## Codex Verification Checklist

- [x] Both prompts pass guard preflight and preserve tools.
- [x] Both participants return terminal, independent reports or explicit runner failure evidence.
- [x] 67 focused functional tests passed.
- [x] Initial, historical r2 and current-identity roundtrip receipts pass the frozen validator;
  only the current identity is eligible for replay.
- [x] CMS current-identity roundtrip 27 pages were visually reviewed by Codex.
- [x] Word inventory returned to the same three user documents.
- [x] TP-MA-07, D017 and CMS originals retain their exact hashes.
- [x] Participant objections are resolved or recorded before P0-WORD disposition.
- [x] No prohibited security test or medical-monitoring access occurred.

Final panel outcome: Pi initial `READY` plus same-session lineage update `READY`; Grok
`READY_WITH_RESIDUALS`; Codex
`P0-WORD_TECHNICAL_PASS_WITH_RESIDUALS`.
