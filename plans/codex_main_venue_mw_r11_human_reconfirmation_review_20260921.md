# Codex Main-Venue Plan: mw_r11_human_reconfirmation_review_20260921

Date: 2026-09-21
Objective: 独立审阅Protocol v3既有竞品篮子按当前医学条件人工复核与受控重绑实现，验证不会重复AI、检索、下载、OCR或翻译，并检查状态一致性、审计链、API与前端交互。

## Task Decomposition

1. Freeze the current diff and deterministic verification evidence.
2. Ask one fresh read-only reviewer to trace contracts, service transactions, retry paths, API behavior, and frontend state from changed medical facts through final rebind.
3. Owner checks every finding against source, applies only concrete fixes, then reruns the concentrated affected matrix.
4. Record accepted/rejected findings and the exact next safe action in the Trellis checkpoint before committing and pushing.

## Source Packet

See `context/mw_r11_human_reconfirmation_review_20260921_conference_context.md`.

## Participant Assignments

| Role | Provider | Model | Output |
|---|---|---|---|
| `general_single_object` | `zcode` | `GLM-5.3-Flash` | `runs/conference/mw_r11_human_reconfirmation_review_20260921/general_single_object.md` |

## Conference Panel Coordination

- No sub-venue chair. Codex leads the assigned panel directly.

## Main-Venue Review

- Codex performs the final synthesis and acceptance.
- This conference mode has no Reasonix second-review role.

## Timeout And Retry Tracking

Record runner timestamps, route receipt, session id, terminal status, and any same-session follow-up in the metrics and review files.

## Codex Verification Checklist

- Reviewer read the actual diff and named files.
- Reviewer checked all external-work entry points remain uncalled.
- Reviewer checked current-facts hash semantics, latest-confirmation selection, and transaction/idempotency behavior.
- Reviewer checked retry after partial projection and repeated reconfirm calls.
- Reviewer checked frontend preselection, coverage, optional explanation, concise criteria, and no misleading AI rerun language.
- Owner independently verifies each accepted finding and reruns tests after repair.
